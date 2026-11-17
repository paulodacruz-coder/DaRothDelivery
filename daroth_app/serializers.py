from django.contrib.auth.models import User
from rest_framework import serializers

from . import services
from .models import (
    Alerta, Cliente, DetallePedido, EstadoPedido, HistorialEstado, Pedido, Producto,
    Repartidor, Zona,
)


# ---------------------------------------------------------------------------
# Usuarios
# ---------------------------------------------------------------------------

class UsuarioSerializer(serializers.ModelSerializer):
    rol = serializers.SerializerMethodField()
    nombre_completo = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "username", "nombre_completo", "email", "rol"]

    def get_rol(self, obj):
        perfil = getattr(obj, "perfil", None)
        return perfil.rol if perfil else None

    def get_nombre_completo(self, obj):
        return obj.get_full_name() or obj.username


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True, style={"input_type": "password"})


# ---------------------------------------------------------------------------
# Catálogo
# ---------------------------------------------------------------------------

class ZonaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Zona
        fields = ["id", "nombre", "latitud_centro", "longitud_centro", "tiempo_viaje_min"]

    def validate_latitud_centro(self, valor):
        if not -90 <= valor <= 90:
            raise serializers.ValidationError("La latitud debe estar entre -90 y 90.")
        return valor

    def validate_longitud_centro(self, valor):
        if not -180 <= valor <= 180:
            raise serializers.ValidationError("La longitud debe estar entre -180 y 180.")
        return valor


class ProductoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Producto
        fields = ["id", "nombre", "precio", "tiempo_preparacion_min"]

    def validate_precio(self, valor):
        if valor <= 0:
            raise serializers.ValidationError("El precio debe ser mayor a cero.")
        return valor


class RepartidorSerializer(serializers.ModelSerializer):
    estado_display = serializers.CharField(source="get_estado_display", read_only=True)

    class Meta:
        model = Repartidor
        fields = ["id", "nombre", "telefono", "vehiculo", "estado", "estado_display",
                  "capacidad_max", "latitud", "longitud"]

    def validate_capacidad_max(self, valor):
        if valor < 1:
            raise serializers.ValidationError("La capacidad debe ser al menos 1.")
        return valor


class ClienteSerializer(serializers.ModelSerializer):
    zona_nombre = serializers.CharField(source="zona.nombre", read_only=True)

    class Meta:
        model = Cliente
        fields = ["id", "nombre", "telefono", "direccion", "zona", "zona_nombre"]


# ---------------------------------------------------------------------------
# Pedidos
# ---------------------------------------------------------------------------

class DetallePedidoSerializer(serializers.ModelSerializer):
    producto_nombre = serializers.CharField(source="producto.nombre", read_only=True)
    subtotal = serializers.SerializerMethodField()

    class Meta:
        model = DetallePedido
        fields = ["producto", "producto_nombre", "cantidad", "precio_unitario", "subtotal"]

    def get_subtotal(self, obj):
        return str(obj.precio_unitario * obj.cantidad)


class HistorialEstadoSerializer(serializers.ModelSerializer):
    estado_display = serializers.CharField(source="get_estado_display", read_only=True)
    usuario = serializers.CharField(source="usuario.username", read_only=True, default=None)

    class Meta:
        model = HistorialEstado
        fields = ["estado", "estado_display", "fecha_hora", "usuario"]


class AlertaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Alerta
        fields = ["id", "pedido", "tipo", "mensaje", "fecha_hora", "resuelta"]


class PedidoSerializer(serializers.ModelSerializer):
    """Representación completa de un pedido, para uso interno del local."""
    cliente_nombre = serializers.CharField(source="cliente.nombre", read_only=True)
    zona_nombre = serializers.CharField(source="zona.nombre", read_only=True)
    repartidor_nombre = serializers.CharField(source="repartidor.nombre", read_only=True, default=None)
    usuario = serializers.CharField(source="usuario.username", read_only=True)
    estado_display = serializers.CharField(source="get_estado_display", read_only=True)
    siguiente_estado = serializers.SerializerMethodField()
    detalles = DetallePedidoSerializer(many=True, read_only=True)
    historial = HistorialEstadoSerializer(many=True, read_only=True)

    class Meta:
        model = Pedido
        fields = ["id", "cliente", "cliente_nombre", "zona", "zona_nombre",
                  "repartidor", "repartidor_nombre", "usuario", "direccion_entrega",
                  "estado", "estado_display", "siguiente_estado", "total",
                  "tiempo_estimado_min", "token_seguimiento", "fecha_creacion",
                  "fecha_entrega", "detalles", "historial"]
        read_only_fields = fields

    def get_siguiente_estado(self, obj):
        return services.siguiente_estado(obj.estado)


class ItemPedidoSerializer(serializers.Serializer):
    producto = serializers.PrimaryKeyRelatedField(queryset=Producto.objects.all())
    cantidad = serializers.IntegerField(min_value=1, max_value=99)


class PedidoCrearSerializer(serializers.Serializer):
    """
    Alta de un pedido. El total, la zona, el tiempo estimado, el token y el
    precio unitario de cada línea los calcula el sistema, no el cliente de la API.
    """
    cliente = serializers.PrimaryKeyRelatedField(queryset=Cliente.objects.select_related("zona"))
    direccion_entrega = serializers.CharField(max_length=200, required=False, allow_blank=True)
    items = ItemPedidoSerializer(many=True)

    def validate_items(self, items):
        if not items:
            raise serializers.ValidationError("El pedido debe tener al menos un producto.")
        ids = [item["producto"].pk for item in items]
        if len(ids) != len(set(ids)):
            raise serializers.ValidationError(
                "Hay productos repetidos: sumá las cantidades en una sola línea.")
        return items

    def create(self, validated_data):
        return services.crear_pedido(
            cliente=validated_data["cliente"],
            items=[(item["producto"], item["cantidad"]) for item in validated_data["items"]],
            usuario=self.context["request"].user,
            direccion_entrega=validated_data.get("direccion_entrega", ""),
        )

    def to_representation(self, instance):
        return PedidoSerializer(instance, context=self.context).data


class PedidoActualizarSerializer(serializers.ModelSerializer):
    """Mientras el pedido no salió del local, solo se puede corregir la dirección."""

    class Meta:
        model = Pedido
        fields = ["direccion_entrega"]

    def to_representation(self, instance):
        return PedidoSerializer(instance, context=self.context).data


# ---------------------------------------------------------------------------
# Sprint 2: estados, asignación y dashboard
# ---------------------------------------------------------------------------

class CambioEstadoSerializer(serializers.Serializer):
    """Estado destino. Tiene que ser el inmediatamente siguiente al actual."""
    estado = serializers.ChoiceField(choices=EstadoPedido.choices)


class AsignacionSerializer(serializers.Serializer):
    repartidor = serializers.PrimaryKeyRelatedField(queryset=Repartidor.objects.all())


class PedidoResumenSerializer(serializers.ModelSerializer):
    """Versión liviana del pedido para el tablero."""
    cliente_nombre = serializers.CharField(source="cliente.nombre", read_only=True)
    zona_nombre = serializers.CharField(source="zona.nombre", read_only=True)
    repartidor_nombre = serializers.CharField(source="repartidor.nombre", read_only=True, default=None)
    estado_display = serializers.CharField(source="get_estado_display", read_only=True)
    siguiente_estado = serializers.SerializerMethodField()
    minutos_transcurridos = serializers.SerializerMethodField()

    class Meta:
        model = Pedido
        fields = ["id", "cliente_nombre", "zona", "zona_nombre", "direccion_entrega",
                  "repartidor", "repartidor_nombre", "estado", "estado_display",
                  "siguiente_estado", "total", "tiempo_estimado_min",
                  "minutos_transcurridos", "fecha_creacion"]

    def get_siguiente_estado(self, obj):
        return services.siguiente_estado(obj.estado)

    def get_minutos_transcurridos(self, obj):
        return services.minutos_transcurridos(obj, self.context.get("ahora"))


class RepartidorCargaSerializer(serializers.ModelSerializer):
    """Repartidor con su carga actual. Requiere el queryset anotado con `pedidos_activos`."""
    estado_display = serializers.CharField(source="get_estado_display", read_only=True)
    pedidos_activos = serializers.IntegerField(read_only=True)

    class Meta:
        model = Repartidor
        fields = ["id", "nombre", "vehiculo", "estado", "estado_display",
                  "pedidos_activos", "capacidad_max"]
