from django.contrib import admin

from .models import (
    Alerta, Cliente, DetallePedido, HistorialEstado, Pedido, Perfil, Producto, Repartidor, Zona,
)


@admin.register(Zona)
class ZonaAdmin(admin.ModelAdmin):
    list_display = ["nombre", "tiempo_viaje_min", "latitud_centro", "longitud_centro"]
    search_fields = ["nombre"]


@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):
    list_display = ["nombre", "precio", "tiempo_preparacion_min"]
    search_fields = ["nombre"]


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ["nombre", "telefono", "direccion", "zona"]
    list_filter = ["zona"]
    search_fields = ["nombre", "telefono"]


@admin.register(Repartidor)
class RepartidorAdmin(admin.ModelAdmin):
    list_display = ["nombre", "vehiculo", "estado", "capacidad_max"]
    list_filter = ["estado", "vehiculo"]
    search_fields = ["nombre"]


class DetallePedidoInline(admin.TabularInline):
    model = DetallePedido
    extra = 0


class HistorialEstadoInline(admin.TabularInline):
    model = HistorialEstado
    extra = 0
    readonly_fields = ["estado", "usuario", "fecha_hora"]
    can_delete = False


@admin.register(Pedido)
class PedidoAdmin(admin.ModelAdmin):
    list_display = ["id", "cliente", "zona", "estado", "repartidor", "total", "fecha_creacion"]
    list_filter = ["estado", "zona"]
    search_fields = ["cliente__nombre", "token_seguimiento"]
    readonly_fields = ["token_seguimiento", "fecha_creacion"]
    inlines = [DetallePedidoInline, HistorialEstadoInline]


@admin.register(Alerta)
class AlertaAdmin(admin.ModelAdmin):
    list_display = ["pedido", "tipo", "fecha_hora", "resuelta"]
    list_filter = ["resuelta", "tipo"]


@admin.register(Perfil)
class PerfilAdmin(admin.ModelAdmin):
    list_display = ["user", "rol"]
    list_filter = ["rol"]
