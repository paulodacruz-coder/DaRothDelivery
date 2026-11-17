"""
Lógica de negocio de DaRoth Delivery.

Las vistas y los serializers delegan acá las reglas del dominio, para que
se puedan reutilizar (por ejemplo, desde el comando cargar_datos) y probar
sin pasar por HTTP. Cuando una regla no se cumple se lanza ReglaDeNegocioError,
que la API traduce a HTTP 409.
"""
import math
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .asignacion import ESTRATEGIA_POR_DEFECTO
from .models import (
    Alerta, DetallePedido, EstadoPedido, HistorialEstado, Pedido, Repartidor, VistaTiemposPedido,
)


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
    if nuevo_estado == EstadoPedido.ENTREGADO:
        # Las alertas de demora se resuelven solas al entregar.
        pedido.alertas.filter(resuelta=False).update(resuelta=True)
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


def sugerir_repartidor(pedido, estrategia=None):
    """
    Ranking de repartidores para un pedido que todavía está en el local, según la
    estrategia de asignación (por defecto, cercanía y carga).
    """
    if pedido.estado not in ESTADOS_EN_LOCAL:
        raise ReglaDeNegocioError("El pedido ya salió del local: no se puede cambiar el repartidor.")
    return (estrategia or ESTRATEGIA_POR_DEFECTO()).sugerir(pedido)


@transaction.atomic
def asignar_automaticamente(pedido, estrategia=None):
    """Asigna el primer repartidor del ranking. 409 si nadie puede llevar el pedido."""
    pedido = Pedido.objects.select_for_update().select_related("zona").get(pk=pedido.pk)
    mejor = sugerir_repartidor(pedido, estrategia).mejor
    if mejor is None:
        raise ReglaDeNegocioError(
            "No hay repartidores disponibles para este pedido: todos están ocupados, "
            "inactivos, con la capacidad completa o sin ubicación.")
    # asignar_repartidor vuelve a validar estado y capacidad con las filas bloqueadas.
    return asignar_repartidor(pedido, mejor.repartidor)


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
# Ubicación y disponibilidad del repartidor
# ---------------------------------------------------------------------------

def actualizar_ubicacion(repartidor, latitud, longitud):
    """Registra la posición actual del repartidor (la envía su app o el encargado)."""
    repartidor.latitud = latitud
    repartidor.longitud = longitud
    repartidor.save(update_fields=["latitud", "longitud"])
    return repartidor


@transaction.atomic
def cambiar_disponibilidad(repartidor, nuevo_estado):
    """
    Marca al repartidor como DISPONIBLE (empieza su turno) o INACTIVO (lo termina).

    Reglas:
    - EN_REPARTO no se elige a mano: lo maneja la máquina de estados del pedido.
    - No se puede dar de baja a alguien con pedidos asignados sin entregar:
      primero hay que entregarlos o reasignarlos.
    - Mientras está en reparto no se lo puede volver a DISPONIBLE: vuelve solo
      al entregar su último pedido.
    """
    repartidor = Repartidor.objects.select_for_update().get(pk=repartidor.pk)
    if nuevo_estado == Repartidor.Estado.EN_REPARTO:
        raise ReglaDeNegocioError(
            "El estado «En reparto» lo asigna el sistema cuando el repartidor sale con un pedido.")
    if repartidor.estado == nuevo_estado:
        return repartidor

    if nuevo_estado == Repartidor.Estado.INACTIVO:
        pendientes = pedidos_activos_de(repartidor).count()
        if pendientes:
            raise ReglaDeNegocioError(
                f"{repartidor.nombre} tiene {pendientes} pedido(s) asignado(s) sin entregar: "
                "entregalos o reasignalos antes de darlo de baja.")
    elif repartidor.estado == Repartidor.Estado.EN_REPARTO:
        raise ReglaDeNegocioError(
            f"{repartidor.nombre} está en reparto: vuelve a «Disponible» solo al entregar.")

    repartidor.estado = nuevo_estado
    repartidor.save(update_fields=["estado"])
    return repartidor


# ---------------------------------------------------------------------------
# Alertas de demora
# ---------------------------------------------------------------------------

TOLERANCIA_DEMORA_MIN = 10
TIPO_DEMORA = "DEMORA"


def limite_de_demora(pedido):
    """Momento a partir del cual el pedido se considera demorado."""
    return pedido.fecha_creacion + timedelta(
        minutes=pedido.tiempo_estimado_min + TOLERANCIA_DEMORA_MIN)


def mensaje_de_demora(pedido):
    return (f"El pedido superó el tiempo estimado ({pedido.tiempo_estimado_min} min) "
            f"en más de {TOLERANCIA_DEMORA_MIN} minutos.")


@transaction.atomic
def revisar_demoras(ahora=None):
    """
    Genera una alerta DEMORA por cada pedido activo que superó su tiempo estimado
    más la tolerancia, salvo que ya tenga una alerta pendiente. Devuelve las creadas.

    No hay un proceso en segundo plano: se llama al consultar las alertas y el
    dashboard, y también desde el comando `revisar_demoras` (para programarlo).
    """
    ahora = ahora or timezone.now()
    # La tolerancia mínima posible acota la consulta; el límite exacto se mira por pedido.
    candidatos = (Pedido.objects.select_for_update()
                  .exclude(estado=EstadoPedido.ENTREGADO)
                  .filter(fecha_creacion__lt=ahora - timedelta(minutes=TOLERANCIA_DEMORA_MIN))
                  .exclude(pk__in=Alerta.objects.filter(resuelta=False, tipo=TIPO_DEMORA)
                           .values("pedido_id")))
    nuevas = [Alerta(pedido=p, tipo=TIPO_DEMORA, mensaje=mensaje_de_demora(p))
              for p in candidatos if ahora > limite_de_demora(p)]
    # bulk_create no usa save(), pero Alerta no tiene lógica propia: alcanza.
    return Alerta.objects.bulk_create(nuevas)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

def minutos_transcurridos(pedido, ahora=None):
    """Minutos desde la creación hasta la entrega (o hasta ahora, si sigue activo)."""
    fin = pedido.fecha_entrega or ahora or timezone.now()
    return int((fin - pedido.fecha_creacion).total_seconds() // 60)


# ---------------------------------------------------------------------------
# Seguimiento: hora estimada de entrega
# ---------------------------------------------------------------------------

def fecha_de_estado(pedido, estado):
    """Fecha en que el pedido llegó a `estado`, según el historial (None si no llegó)."""
    # Se recorre en Python para aprovechar el historial si ya vino con prefetch_related.
    fechas = [h.fecha_hora for h in pedido.historial.all() if h.estado == estado]
    return min(fechas) if fechas else None


def estimar_entrega(pedido, ahora=None):
    """
    Hora estimada de entrega, recalculada según en qué etapa está el pedido.
    Devuelve None si el pedido ya se entregó.

    - Estimación base: fecha de creación + tiempo_estimado_min (lo que se le
      prometió al cliente al tomar el pedido).
    - Mientras está en el local: si la cocina se atrasó, el pedido igual tiene
      que viajar, así que nunca se estima antes de ahora + el viaje a la zona.
    - En camino: la mejor información es la hora de salida + el viaje a la zona.
    """
    if pedido.estado == EstadoPedido.ENTREGADO:
        return None
    ahora = ahora or timezone.now()
    viaje = timedelta(minutes=pedido.zona.tiempo_viaje_min)

    if pedido.estado == EstadoPedido.EN_CAMINO:
        salida = fecha_de_estado(pedido, EstadoPedido.EN_CAMINO) or ahora
        return salida + viaje

    base = pedido.fecha_creacion + timedelta(minutes=pedido.tiempo_estimado_min)
    return max(base, ahora + viaje)


def minutos_restantes(pedido, ahora=None):
    """
    Minutos que faltan para la entrega estimada, redondeados hacia arriba.
    0 si ya se cumplió la hora estimada; None si el pedido ya se entregó.
    """
    ahora = ahora or timezone.now()
    estimada = estimar_entrega(pedido, ahora)
    if estimada is None:
        return None
    segundos = (estimada - ahora).total_seconds()
    return max(0, math.ceil(segundos / 60))


# ---------------------------------------------------------------------------
# Estadísticas (sobre la vista v_tiempos_pedido)
# ---------------------------------------------------------------------------

DIAS_POR_DEFECTO = 30


def _promedio(valores):
    valores = [v for v in valores if v is not None]
    return round(sum(valores) / len(valores), 1) if valores else None


def calcular_estadisticas(desde=None, hasta=None):
    """
    Resumen de los pedidos tomados entre `desde` y `hasta` (fechas locales, inclusive).
    Por defecto, los últimos 30 días.

    Los tiempos promedio y el porcentaje a tiempo se calculan sobre los entregados.
    Se agrupa por día en Python: la base de XAMPP no trae las tablas de zonas
    horarias, así que agrupar por fecha local en SQL daría NULL.
    """
    hoy = timezone.localdate()
    hasta = hasta or hoy
    desde = desde or hasta - timedelta(days=DIAS_POR_DEFECTO - 1)
    zona_horaria = timezone.get_current_timezone()
    inicio = datetime.combine(desde, time.min, tzinfo=zona_horaria)
    fin = datetime.combine(hasta + timedelta(days=1), time.min, tzinfo=zona_horaria)

    filas = list(VistaTiemposPedido.objects.filter(fecha_creacion__gte=inicio,
                                                   fecha_creacion__lt=fin))
    entregados = [f for f in filas if f.estado == EstadoPedido.ENTREGADO]
    facturacion = sum((f.total for f in entregados), Decimal("0"))

    por_dia = {}
    for fila in filas:
        dia = por_dia.setdefault(timezone.localtime(fila.fecha_creacion).date(),
                                 {"pedidos": 0, "entregados": 0, "facturacion": Decimal("0")})
        dia["pedidos"] += 1
        if fila.estado == EstadoPedido.ENTREGADO:
            dia["entregados"] += 1
            dia["facturacion"] += fila.total

    a_tiempo = [f.a_tiempo for f in entregados if f.a_tiempo is not None]
    return {
        "desde": desde,
        "hasta": hasta,
        "pedidos": len(filas),
        "entregados": len(entregados),
        "facturacion": facturacion,
        "ticket_promedio": (facturacion / len(entregados)).quantize(Decimal("0.01"))
                           if entregados else None,
        "pct_a_tiempo": round(100 * sum(a_tiempo) / len(a_tiempo), 1) if a_tiempo else None,
        "alertas_de_demora": Alerta.objects.filter(
            tipo=TIPO_DEMORA, pedido__fecha_creacion__gte=inicio,
            pedido__fecha_creacion__lt=fin).count(),
        "minutos_promedio": {
            "espera": _promedio(f.min_espera for f in entregados),
            "preparacion": _promedio(f.min_preparacion for f in entregados),
            "despacho": _promedio(f.min_despacho for f in entregados),
            "viaje": _promedio(f.min_viaje for f in entregados),
            "total": _promedio(f.min_total for f in entregados),
        },
        "por_dia": [{"fecha": fecha, **datos} for fecha, datos in sorted(por_dia.items())],
    }
