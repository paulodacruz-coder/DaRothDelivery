from django.contrib.auth.models import User
from django.urls import reverse
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from . import services
from .models import (
    Alerta, Cliente, DetallePedido, EstadoPedido, HistorialEstado, Pedido, Producto,
    Repartidor, VistaDemandaZona, VistaPedidoActivo, VistaProductoVendido,
    VistaRendimientoRepartidor, VistaTiemposPedido, Zona,
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

    def get_rol(self, obj) -> str | None:
        perfil = getattr(obj, "perfil", None)
        return perfil.rol if perfil else None

    def get_nombre_completo(self, obj) -> str:
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

    def validate_estado(self, valor):
        # El estado tiene reglas propias (ver services.cambiar_disponibilidad):
        # una vez creado el repartidor, se cambia solo por /disponibilidad/.
        if self.instance is not None and valor != self.instance.estado:
            raise serializers.ValidationError(
                "El estado se cambia con POST /api/repartidores/{id}/disponibilidad/.")
        if self.instance is None and valor == Repartidor.Estado.EN_REPARTO:
            raise serializers.ValidationError("Un repartidor nuevo no puede estar en reparto.")
        return valor

    def validate(self, datos):
        validar_coordenadas(datos, "latitud", "longitud")
        return datos


def validar_coordenadas(datos, campo_lat, campo_lon):
    """Rango válido de latitud y longitud, y que vengan las dos juntas o ninguna."""
    errores = {}
    lat, lon = datos.get(campo_lat), datos.get(campo_lon)
    if lat is not None and not -90 <= lat <= 90:
        errores[campo_lat] = "La latitud debe estar entre -90 y 90."
    if lon is not None and not -180 <= lon <= 180:
        errores[campo_lon] = "La longitud debe estar entre -180 y 180."
    if (campo_lat in datos) != (campo_lon in datos):
        errores["detail"] = "La latitud y la longitud se envían juntas."
    if errores:
        raise serializers.ValidationError(errores)


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

    @extend_schema_field(serializers.DecimalField(max_digits=12, decimal_places=2))
    def get_subtotal(self, obj):
        return str(obj.precio_unitario * obj.cantidad)


class HistorialEstadoSerializer(serializers.ModelSerializer):
    estado_display = serializers.CharField(source="get_estado_display", read_only=True)
    usuario = serializers.CharField(source="usuario.username", read_only=True, default=None)

    class Meta:
        model = HistorialEstado
        fields = ["estado", "estado_display", "fecha_hora", "usuario"]


class AlertaSerializer(serializers.ModelSerializer):
    """Alerta con lo mínimo del pedido para poder actuar sin abrirlo."""
    cliente_nombre = serializers.CharField(source="pedido.cliente.nombre", read_only=True)
    zona_nombre = serializers.CharField(source="pedido.zona.nombre", read_only=True)
    repartidor_nombre = serializers.CharField(source="pedido.repartidor.nombre", read_only=True,
                                              default=None)
    estado_pedido = serializers.CharField(source="pedido.estado", read_only=True)
    minutos_transcurridos = serializers.SerializerMethodField()

    class Meta:
        model = Alerta
        fields = ["id", "pedido", "tipo", "mensaje", "fecha_hora", "resuelta",
                  "estado_pedido", "cliente_nombre", "zona_nombre", "repartidor_nombre",
                  "minutos_transcurridos"]

    def get_minutos_transcurridos(self, obj) -> int:
        return services.minutos_transcurridos(obj.pedido, self.context.get("ahora"))


class PedidoSerializer(serializers.ModelSerializer):
    """Representación completa de un pedido, para uso interno del local."""
    cliente_nombre = serializers.CharField(source="cliente.nombre", read_only=True)
    zona_nombre = serializers.CharField(source="zona.nombre", read_only=True)
    repartidor_nombre = serializers.CharField(source="repartidor.nombre", read_only=True, default=None)
    usuario = serializers.CharField(source="usuario.username", read_only=True)
    estado_display = serializers.CharField(source="get_estado_display", read_only=True)
    siguiente_estado = serializers.SerializerMethodField()
    enlace_seguimiento = serializers.SerializerMethodField()
    detalles = DetallePedidoSerializer(many=True, read_only=True)
    historial = HistorialEstadoSerializer(many=True, read_only=True)

    class Meta:
        model = Pedido
        fields = ["id", "cliente", "cliente_nombre", "zona", "zona_nombre",
                  "repartidor", "repartidor_nombre", "usuario", "direccion_entrega",
                  "estado", "estado_display", "siguiente_estado", "total",
                  "tiempo_estimado_min", "token_seguimiento", "enlace_seguimiento",
                  "fecha_creacion", "fecha_entrega", "detalles", "historial"]
        read_only_fields = fields

    def get_siguiente_estado(self, obj) -> str | None:
        return services.siguiente_estado(obj.estado)

    def get_enlace_seguimiento(self, obj) -> str:
        """URL pública que el local le pasa al cliente (por WhatsApp, SMS, etc.)."""
        ruta = reverse("seguimiento", kwargs={"token": obj.token_seguimiento})
        request = self.context.get("request")
        return request.build_absolute_uri(ruta) if request else ruta


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
    """
    Manual: {"repartidor": 3}.
    Automática (Sprint 4): {"automatica": true}, asigna el primero del ranking de sugerencias.
    """
    repartidor = serializers.PrimaryKeyRelatedField(queryset=Repartidor.objects.all(),
                                                    required=False)
    automatica = serializers.BooleanField(default=False)

    def validate(self, datos):
        if datos["automatica"] == ("repartidor" in datos):
            raise serializers.ValidationError(
                "Indicá un repartidor o pedí la asignación automática, una de las dos.")
        return datos


class PedidoResumenSerializer(serializers.ModelSerializer):
    """Versión liviana del pedido para el tablero."""
    cliente_nombre = serializers.CharField(source="cliente.nombre", read_only=True)
    zona_nombre = serializers.CharField(source="zona.nombre", read_only=True)
    repartidor_nombre = serializers.CharField(source="repartidor.nombre", read_only=True, default=None)
    estado_display = serializers.CharField(source="get_estado_display", read_only=True)
    siguiente_estado = serializers.SerializerMethodField()
    minutos_transcurridos = serializers.SerializerMethodField()
    minutos_restantes = serializers.SerializerMethodField()

    class Meta:
        model = Pedido
        fields = ["id", "cliente_nombre", "zona", "zona_nombre", "direccion_entrega",
                  "repartidor", "repartidor_nombre", "estado", "estado_display",
                  "siguiente_estado", "total", "tiempo_estimado_min",
                  "minutos_transcurridos", "minutos_restantes", "fecha_creacion"]

    def get_siguiente_estado(self, obj) -> str | None:
        return services.siguiente_estado(obj.estado)

    def get_minutos_transcurridos(self, obj) -> int:
        return services.minutos_transcurridos(obj, self.context.get("ahora"))

    def get_minutos_restantes(self, obj) -> int | None:
        return services.minutos_restantes(obj, self.context.get("ahora"))


class RepartidorCargaSerializer(serializers.ModelSerializer):
    """Repartidor con su carga actual. Requiere el queryset anotado con `pedidos_activos`."""
    estado_display = serializers.CharField(source="get_estado_display", read_only=True)
    pedidos_activos = serializers.IntegerField(read_only=True)

    class Meta:
        model = Repartidor
        fields = ["id", "nombre", "vehiculo", "estado", "estado_display",
                  "pedidos_activos", "capacidad_max"]


# ---------------------------------------------------------------------------
# Sprint 4: ubicación, disponibilidad y asignación inteligente
# ---------------------------------------------------------------------------

class UbicacionSerializer(serializers.Serializer):
    latitud = serializers.DecimalField(max_digits=9, decimal_places=6)
    longitud = serializers.DecimalField(max_digits=9, decimal_places=6)

    def validate(self, datos):
        validar_coordenadas(datos, "latitud", "longitud")
        return datos


class DisponibilidadSerializer(serializers.Serializer):
    """DISPONIBLE (empieza el turno) o INACTIVO (lo termina)."""
    estado = serializers.ChoiceField(choices=[Repartidor.Estado.DISPONIBLE,
                                              Repartidor.Estado.INACTIVO])


class CandidatoSerializer(serializers.Serializer):
    """Un puesto del ranking, con el desglose del puntaje para que se entienda la sugerencia."""
    posicion = serializers.IntegerField()
    repartidor = serializers.IntegerField(source="repartidor.pk")
    nombre = serializers.CharField(source="repartidor.nombre")
    vehiculo = serializers.CharField(source="repartidor.vehiculo")
    puntaje = serializers.FloatField()
    distancia_km = serializers.FloatField()
    pedidos_activos = serializers.IntegerField()
    capacidad_max = serializers.IntegerField(source="repartidor.capacidad_max")
    misma_zona = serializers.BooleanField()

    def to_representation(self, candidato):
        datos = super().to_representation(candidato)
        datos["puntaje"] = round(candidato.puntaje, 2)
        datos["distancia_km"] = round(candidato.distancia_km, 2)
        return datos


class DescartadoSerializer(serializers.Serializer):
    repartidor = serializers.IntegerField(source="repartidor.pk")
    nombre = serializers.CharField(source="repartidor.nombre")
    motivo = serializers.CharField()


class SugerenciaSerializer(serializers.Serializer):
    pedido = serializers.IntegerField()
    zona = serializers.CharField()
    estrategia = serializers.CharField()
    criterio = serializers.CharField()
    repartidor_actual = serializers.IntegerField(allow_null=True)
    ranking = CandidatoSerializer(many=True)
    descartados = DescartadoSerializer(many=True)


# ---------------------------------------------------------------------------
# Sprint 3: seguimiento público
# ---------------------------------------------------------------------------
# Lo ve cualquiera que tenga el enlace, así que es deliberadamente reducido:
# nada de ids, nombres, teléfonos, direcciones, montos ni usuarios del local.

class HistorialPublicoSerializer(serializers.ModelSerializer):
    estado_display = serializers.CharField(source="get_estado_display", read_only=True)

    class Meta:
        model = HistorialEstado
        fields = ["estado", "estado_display", "fecha_hora"]


class SeguimientoSerializer(serializers.ModelSerializer):
    estado_display = serializers.CharField(source="get_estado_display", read_only=True)
    entregado = serializers.SerializerMethodField()
    hora_estimada_entrega = serializers.SerializerMethodField()
    minutos_restantes = serializers.SerializerMethodField()
    historial = serializers.SerializerMethodField()

    class Meta:
        model = Pedido
        fields = ["estado", "estado_display", "entregado", "fecha_creacion",
                  "hora_estimada_entrega", "minutos_restantes", "fecha_entrega", "historial"]

    def get_entregado(self, obj) -> bool:
        return obj.estado == EstadoPedido.ENTREGADO

    @extend_schema_field(serializers.DateTimeField(allow_null=True))
    def get_hora_estimada_entrega(self, obj):
        estimada = services.estimar_entrega(obj, self.context.get("ahora"))
        return serializers.DateTimeField().to_representation(estimada) if estimada else None

    def get_minutos_restantes(self, obj) -> int | None:
        return services.minutos_restantes(obj, self.context.get("ahora"))

    @extend_schema_field(HistorialPublicoSerializer(many=True))
    def get_historial(self, obj):
        registros = sorted(obj.historial.all(), key=lambda h: (h.fecha_hora, h.pk))
        return HistorialPublicoSerializer(registros, many=True).data


# ---------------------------------------------------------------------------
# Sprint 5: reportes (vistas SQL) y estadísticas
# ---------------------------------------------------------------------------

class VistaPedidoActivoSerializer(serializers.ModelSerializer):
    class Meta:
        model = VistaPedidoActivo
        fields = "__all__"


class VistaTiemposPedidoSerializer(serializers.ModelSerializer):
    class Meta:
        model = VistaTiemposPedido
        fields = "__all__"


class VistaRendimientoRepartidorSerializer(serializers.ModelSerializer):
    class Meta:
        model = VistaRendimientoRepartidor
        fields = "__all__"


class VistaDemandaZonaSerializer(serializers.ModelSerializer):
    class Meta:
        model = VistaDemandaZona
        fields = "__all__"


class VistaProductoVendidoSerializer(serializers.ModelSerializer):
    class Meta:
        model = VistaProductoVendido
        fields = "__all__"


class PeriodoSerializer(serializers.Serializer):
    """Filtro de fechas de las estadísticas (fechas locales, ambas inclusive)."""
    desde = serializers.DateField(required=False)
    hasta = serializers.DateField(required=False)

    def validate(self, datos):
        if datos.get("desde") and datos.get("hasta") and datos["desde"] > datos["hasta"]:
            raise serializers.ValidationError("«desde» no puede ser posterior a «hasta».")
        return datos


class TiemposPromedioSerializer(serializers.Serializer):
    espera = serializers.FloatField(allow_null=True, help_text="Creación → Preparando")
    preparacion = serializers.FloatField(allow_null=True, help_text="Preparando → Listo")
    despacho = serializers.FloatField(allow_null=True, help_text="Listo → En camino")
    viaje = serializers.FloatField(allow_null=True, help_text="En camino → Entregado")
    total = serializers.FloatField(allow_null=True, help_text="Creación → Entregado")


class EstadisticaDiaSerializer(serializers.Serializer):
    fecha = serializers.DateField()
    pedidos = serializers.IntegerField()
    entregados = serializers.IntegerField()
    facturacion = serializers.DecimalField(max_digits=14, decimal_places=2)


class EstadisticasSerializer(serializers.Serializer):
    desde = serializers.DateField()
    hasta = serializers.DateField()
    pedidos = serializers.IntegerField()
    entregados = serializers.IntegerField()
    facturacion = serializers.DecimalField(max_digits=14, decimal_places=2)
    ticket_promedio = serializers.DecimalField(max_digits=12, decimal_places=2, allow_null=True)
    pct_a_tiempo = serializers.FloatField(allow_null=True)
    alertas_de_demora = serializers.IntegerField()
    minutos_promedio = TiemposPromedioSerializer()
    por_dia = EstadisticaDiaSerializer(many=True)
