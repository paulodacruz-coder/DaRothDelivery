"""
Lógica de negocio de DaRoth Delivery.

Las vistas y los serializers delegan acá las reglas del dominio, para que
se puedan reutilizar (por ejemplo, desde el comando cargar_datos) y probar
sin pasar por HTTP. Cuando una regla no se cumple se lanza ReglaDeNegocioError,
que la API traduce a HTTP 409.
"""
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .models import DetallePedido, EstadoPedido, HistorialEstado, Pedido, Repartidor


class ReglaDeNegocioError(Exception):
    """La operación choca con el estado actual del pedido o del repartidor."""


# ---------------------------------------------------------------------------
# Alta de pedidos
# ---------------------------------------------------------------------------

def calcular_tiempo_estimado(productos, zona):
    """
    Tiempo estimado de entrega en minutos:
    el producto que más tarda en prepararse + el viaje hasta la zona.
    """
    preparacion = max((p.tiempo_preparacion_min for p in productos), default=0)
    return preparacion + zona.tiempo_viaje_min


@transaction.atomic
def crear_pedido(*, cliente, items, usuario, direccion_entrega=""):
    """
    Crea un pedido con sus detalles y su primer registro de historial.

    items: lista de tuplas (producto, cantidad).
    El precio unitario se congela con el precio actual del producto.
    """
    zona = cliente.zona
    productos = [producto for producto, _ in items]
    total = sum((producto.precio * cantidad for producto, cantidad in items), Decimal("0"))

    pedido = Pedido.objects.create(
        cliente=cliente,
        zona=zona,
        usuario=usuario,
        direccion_entrega=direccion_entrega or cliente.direccion,
        estado=EstadoPedido.PENDIENTE,
        total=total,
        tiempo_estimado_min=calcular_tiempo_estimado(productos, zona),
    )
    DetallePedido.objects.bulk_create([
        DetallePedido(pedido=pedido, producto=producto, cantidad=cantidad,
                      precio_unitario=producto.precio)
        for producto, cantidad in items
    ])
    HistorialEstado.objects.create(pedido=pedido, usuario=usuario, estado=EstadoPedido.PENDIENTE)
    return pedido


# ---------------------------------------------------------------------------
# Máquina de estados
# ---------------------------------------------------------------------------

ORDEN_ESTADOS = [
    EstadoPedido.PENDIENTE,
    EstadoPedido.PREPARANDO,
    EstadoPedido.LISTO,
    EstadoPedido.EN_CAMINO,
    EstadoPedido.ENTREGADO,
]

# Estados en los que el pedido todavía está en el local.
ESTADOS_EN_LOCAL = {EstadoPedido.PENDIENTE, EstadoPedido.PREPARANDO, EstadoPedido.LISTO}

# Estados que registra el repartidor desde su app: van al historial sin usuario del sistema.
ESTADOS_DEL_REPARTIDOR = {EstadoPedido.EN_CAMINO, EstadoPedido.ENTREGADO}


def siguiente_estado(estado):
    """Estado al que se puede avanzar desde `estado`, o None si ya es el último."""
    indice = ORDEN_ESTADOS.index(estado)
    return ORDEN_ESTADOS[indice + 1] if indice + 1 < len(ORDEN_ESTADOS) else None


def pedidos_activos_de(repartidor):
    """Pedidos asignados al repartidor que todavía no se entregaron."""
    return repartidor.pedidos.exclude(estado=EstadoPedido.ENTREGADO)


@transaction.atomic
def cambiar_estado(pedido, nuevo_estado, usuario):
    """
    Avanza el pedido al estado siguiente y lo registra en el historial.

    Reglas:
    - Solo se avanza al estado inmediatamente siguiente: no se saltea ni se retrocede.
    - No se puede pasar a EN_CAMINO sin repartidor asignado.
    - Al salir el pedido, el repartidor pasa a EN_REPARTO; al entregar su último
      pedido en camino, vuelve a DISPONIBLE.

    Se pide el estado destino explícito (en lugar de "avanzar") para que un doble
    clic no haga avanzar el pedido dos veces: el segundo intento da 409.
    """
    # Se bloquea la fila para que dos pedidos simultáneos no pisen el estado.
    pedido = Pedido.objects.select_for_update().get(pk=pedido.pk)
    esperado = siguiente_estado(pedido.estado)

    if esperado is None:
        raise ReglaDeNegocioError("El pedido ya fue entregado: no admite más cambios de estado.")
    if nuevo_estado != esperado:
        raise ReglaDeNegocioError(
            f"Transición inválida: el pedido está «{EstadoPedido(pedido.estado).label}» "
            f"y solo puede pasar a «{EstadoPedido(esperado).label}».")
    if nuevo_estado == EstadoPedido.EN_CAMINO and pedido.repartidor_id is None:
        raise ReglaDeNegocioError("No se puede despachar un pedido sin repartidor asignado.")

    ahora = timezone.now()
    pedido.estado = nuevo_estado
    campos = ["estado"]
    if nuevo_estado == EstadoPedido.ENTREGADO:
        pedido.fecha_entrega = ahora
        campos.append("fecha_entrega")
    pedido.save(update_fields=campos)

    HistorialEstado.objects.create(
        pedido=pedido, estado=nuevo_estado,
        usuario=None if nuevo_estado in ESTADOS_DEL_REPARTIDOR else usuario)

    _actualizar_estado_repartidor(pedido, nuevo_estado)
    return pedido


def _actualizar_estado_repartidor(pedido, nuevo_estado):
    repartidor = pedido.repartidor
    if repartidor is None or repartidor.estado == Repartidor.Estado.INACTIVO:
        return
    if nuevo_estado == EstadoPedido.EN_CAMINO:
        repartidor.estado = Repartidor.Estado.EN_REPARTO
        repartidor.save(update_fields=["estado"])
    elif nuevo_estado == EstadoPedido.ENTREGADO:
        sigue_en_calle = repartidor.pedidos.filter(estado=EstadoPedido.EN_CAMINO).exists()
        if not sigue_en_calle:
            repartidor.estado = Repartidor.Estado.DISPONIBLE
            repartidor.save(update_fields=["estado"])


# ---------------------------------------------------------------------------
# Asignación manual de repartidor
# ---------------------------------------------------------------------------

@transaction.atomic
def asignar_repartidor(pedido, repartidor):
    """
    Asigna (o reasigna) un repartidor a un pedido que todavía está en el local.

    Reglas:
    - El pedido no puede haber salido (EN_CAMINO o ENTREGADO).
    - El repartidor no puede estar INACTIVO.
    - El repartidor no puede superar su capacidad_max de pedidos activos.
    """
    pedido = Pedido.objects.select_for_update().get(pk=pedido.pk)
    repartidor = Repartidor.objects.select_for_update().get(pk=repartidor.pk)

    if pedido.estado not in ESTADOS_EN_LOCAL:
        raise ReglaDeNegocioError("El pedido ya salió del local: no se puede cambiar el repartidor.")
    if repartidor.estado == Repartidor.Estado.INACTIVO:
        raise ReglaDeNegocioError(f"{repartidor.nombre} está inactivo.")
    if pedido.repartidor_id == repartidor.pk:
        return pedido

    carga = pedidos_activos_de(repartidor).count()
    if carga >= repartidor.capacidad_max:
        raise ReglaDeNegocioError(
            f"{repartidor.nombre} ya tiene {carga} pedidos activos "
            f"(capacidad máxima: {repartidor.capacidad_max}).")

    pedido.repartidor = repartidor
    pedido.save(update_fields=["repartidor"])
    return pedido


@transaction.atomic
def desasignar_repartidor(pedido):
    """Quita el repartidor de un pedido que todavía está en el local."""
    pedido = Pedido.objects.select_for_update().get(pk=pedido.pk)
    if pedido.estado not in ESTADOS_EN_LOCAL:
        raise ReglaDeNegocioError("El pedido ya salió del local: no se puede quitar el repartidor.")
    pedido.repartidor = None
    pedido.save(update_fields=["repartidor"])
    return pedido


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

def minutos_transcurridos(pedido, ahora=None):
    """Minutos desde la creación hasta la entrega (o hasta ahora, si sigue activo)."""
    fin = pedido.fecha_entrega or ahora or timezone.now()
    return int((fin - pedido.fecha_creacion).total_seconds() // 60)
