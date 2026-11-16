"""
Lógica de negocio de DaRoth Delivery.

Las vistas y los serializers delegan acá las reglas del dominio, para que
se puedan reutilizar (por ejemplo, desde el comando cargar_datos) y probar
sin pasar por HTTP.
"""
from decimal import Decimal

from django.db import transaction

from .models import DetallePedido, EstadoPedido, HistorialEstado, Pedido


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
