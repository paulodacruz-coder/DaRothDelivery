from decimal import Decimal

from django.contrib.auth import authenticate
from django.db.models import Count, ProtectedError, Q, Sum
from django.utils import timezone
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.authtoken.models import Token
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from . import services
from .excepciones import Conflicto
from .models import Alerta, Cliente, EstadoPedido, Pedido, Producto, Repartidor, Zona
from .permissions import EsAdministradorOSoloLectura
from .serializers import (
    AsignacionSerializer, CambioEstadoSerializer, ClienteSerializer, DisponibilidadSerializer,
    HistorialEstadoSerializer, LoginSerializer, PedidoActualizarSerializer,
    PedidoCrearSerializer, PedidoResumenSerializer, PedidoSerializer, ProductoSerializer,
    RepartidorCargaSerializer, RepartidorSerializer, SeguimientoSerializer,
    SugerenciaSerializer, UbicacionSerializer, UsuarioSerializer, ZonaSerializer,
)

# Respuesta de error de negocio (ver excepciones.py), para la documentación.
RESPUESTA_409 = inline_serializer("Conflicto", {"detail": serializers.CharField()})


# ---------------------------------------------------------------------------
# Autenticación
# ---------------------------------------------------------------------------

class LoginView(APIView):
    """POST {username, password} → {token, usuario}. Usar el token como 'Authorization: Token <token>'."""
    permission_classes = [AllowAny]
    serializer_class = LoginSerializer

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = authenticate(request, **serializer.validated_data)
        if user is None:
            return Response({"detail": "Usuario o contraseña incorrectos."},
                            status=status.HTTP_400_BAD_REQUEST)
        token, _ = Token.objects.get_or_create(user=user)
        return Response({"token": token.key, "usuario": UsuarioSerializer(user).data})


class LogoutView(APIView):
    """POST → invalida el token del usuario actual."""

    @extend_schema(request=None, responses={204: None})
    def post(self, request):
        Token.objects.filter(user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class UsuarioActualView(APIView):
    """GET → datos y rol del usuario autenticado."""
    serializer_class = UsuarioSerializer

    def get(self, request):
        return Response(UsuarioSerializer(request.user).data)


# ---------------------------------------------------------------------------
# Catálogo
# ---------------------------------------------------------------------------

class BorradoProtegidoMixin:
    """Convierte el error de una FK con PROTECT en un 409 legible."""

    def perform_destroy(self, instance):
        try:
            instance.delete()
        except ProtectedError:
            raise Conflicto(f"No se puede borrar «{instance}»: tiene pedidos o clientes asociados.")


class ZonaViewSet(BorradoProtegidoMixin, viewsets.ModelViewSet):
    queryset = Zona.objects.all()
    serializer_class = ZonaSerializer
    permission_classes = [EsAdministradorOSoloLectura]


class ProductoViewSet(BorradoProtegidoMixin, viewsets.ModelViewSet):
    queryset = Producto.objects.all()
    serializer_class = ProductoSerializer
    permission_classes = [EsAdministradorOSoloLectura]


class RepartidorViewSet(viewsets.ModelViewSet):
    """
    CRUD de repartidores (solo el administrador modifica). Filtro: ?estado=DISPONIBLE

    Acciones de la operación diaria, que puede hacer también el encargado:
      POST /repartidores/{id}/ubicacion/       {"latitud": ..., "longitud": ...}
      POST /repartidores/{id}/disponibilidad/  {"estado": "DISPONIBLE" | "INACTIVO"}
    """
    serializer_class = RepartidorSerializer
    permission_classes = [EsAdministradorOSoloLectura]

    def get_queryset(self):
        qs = Repartidor.objects.all()
        estado = self.request.query_params.get("estado")
        if estado:
            qs = qs.filter(estado=estado.upper())
        return qs

    def get_serializer_class(self):
        return {
            "ubicacion": UbicacionSerializer,
            "disponibilidad": DisponibilidadSerializer,
        }.get(self.action, RepartidorSerializer)

    def perform_destroy(self, instance):
        if services.pedidos_activos_de(instance).exists():
            raise Conflicto(f"{instance.nombre} tiene pedidos sin entregar: no se puede borrar.")
        instance.delete()

    @extend_schema(responses={200: RepartidorSerializer})
    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated])
    def ubicacion(self, request, pk=None):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        repartidor = services.actualizar_ubicacion(self.get_object(), **serializer.validated_data)
        return Response(RepartidorSerializer(repartidor).data)

    @extend_schema(responses={200: RepartidorSerializer, 409: RESPUESTA_409})
    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated])
    def disponibilidad(self, request, pk=None):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        repartidor = services.cambiar_disponibilidad(self.get_object(),
                                                     serializer.validated_data["estado"])
        return Response(RepartidorSerializer(repartidor).data)


class ClienteViewSet(BorradoProtegidoMixin, viewsets.ModelViewSet):
    """Los clientes los da de alta el encargado al tomar el pedido. Filtro: ?q=nombre o teléfono."""
    serializer_class = ClienteSerializer

    def get_queryset(self):
        qs = Cliente.objects.select_related("zona")
        q = self.request.query_params.get("q")
        if q:
            qs = qs.filter(Q(nombre__icontains=q) | Q(telefono__icontains=q))
        return qs


# ---------------------------------------------------------------------------
# Pedidos
# ---------------------------------------------------------------------------

class PedidoViewSet(mixins.CreateModelMixin, mixins.ListModelMixin,
                    mixins.RetrieveModelMixin, mixins.UpdateModelMixin,
                    mixins.DestroyModelMixin, viewsets.GenericViewSet):
    """
    CRUD de pedidos.
    Filtros: ?estado=PENDIENTE&zona=<id>&repartidor=<id>&activos=1

    Acciones:
      POST /pedidos/{id}/estado/       {"estado": "PREPARANDO"}  avanza al estado siguiente
      GET  /pedidos/{id}/historial/                              historial de estados
      POST /pedidos/{id}/asignar/      {"repartidor": 3}         asignación manual
      POST /pedidos/{id}/asignar/      {"automatica": true}      asigna el mejor del ranking
      GET  /pedidos/{id}/sugerencia/                             ranking de repartidores
      POST /pedidos/{id}/desasignar/                             quita el repartidor
    """

    def get_queryset(self):
        qs = (Pedido.objects
              .select_related("cliente", "zona", "repartidor", "usuario")
              .prefetch_related("detalles__producto", "historial__usuario")
              .order_by("-fecha_creacion"))
        params = self.request.query_params
        if params.get("estado"):
            qs = qs.filter(estado=params["estado"].upper())
        if params.get("zona"):
            qs = qs.filter(zona_id=params["zona"])
        if params.get("repartidor"):
            qs = qs.filter(repartidor_id=params["repartidor"])
        if params.get("activos") in ("1", "true", "True"):
            qs = qs.exclude(estado=EstadoPedido.ENTREGADO)
        return qs

    def get_serializer_class(self):
        return {
            "create": PedidoCrearSerializer,
            "update": PedidoActualizarSerializer,
            "partial_update": PedidoActualizarSerializer,
            "estado": CambioEstadoSerializer,
            "asignar": AsignacionSerializer,
            "historial": HistorialEstadoSerializer,
        }.get(self.action, PedidoSerializer)

    def _responder_pedido(self, pedido, codigo=status.HTTP_200_OK):
        """Devuelve el pedido completo, releído con el queryset optimizado."""
        pedido = self.get_queryset().get(pk=pedido.pk)
        return Response(PedidoSerializer(pedido, context=self.get_serializer_context()).data,
                        status=codigo)

    @extend_schema(responses={200: PedidoSerializer, 409: RESPUESTA_409})
    @action(detail=True, methods=["post"])
    def estado(self, request, pk=None):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        pedido = services.cambiar_estado(self.get_object(), serializer.validated_data["estado"],
                                         request.user)
        return self._responder_pedido(pedido)

    @extend_schema(responses=HistorialEstadoSerializer(many=True))
    @action(detail=True, methods=["get"], pagination_class=None)
    def historial(self, request, pk=None):
        registros = self.get_object().historial.select_related("usuario").order_by("fecha_hora")
        return Response(HistorialEstadoSerializer(registros, many=True).data)

    @extend_schema(responses={200: PedidoSerializer, 409: RESPUESTA_409})
    @action(detail=True, methods=["post"])
    def asignar(self, request, pk=None):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if serializer.validated_data["automatica"]:
            pedido = services.asignar_automaticamente(self.get_object())
        else:
            pedido = services.asignar_repartidor(self.get_object(),
                                                 serializer.validated_data["repartidor"])
        return self._responder_pedido(pedido)

    @extend_schema(responses={200: SugerenciaSerializer, 409: RESPUESTA_409})
    @action(detail=True, methods=["get"], pagination_class=None)
    def sugerencia(self, request, pk=None):
        """Ranking de repartidores para el pedido, del más conveniente al menos conveniente."""
        pedido = self.get_object()
        sugerencia = services.sugerir_repartidor(pedido)
        return Response(SugerenciaSerializer({
            "pedido": pedido.pk,
            "zona": pedido.zona.nombre,
            "estrategia": sugerencia.estrategia.nombre,
            "criterio": sugerencia.estrategia.criterio,
            "repartidor_actual": pedido.repartidor_id,
            "ranking": sugerencia.ranking,
            "descartados": sugerencia.descartados,
        }).data)

    @extend_schema(request=None, responses={200: PedidoSerializer, 409: RESPUESTA_409})
    @action(detail=True, methods=["post"])
    def desasignar(self, request, pk=None):
        pedido = services.desasignar_repartidor(self.get_object())
        return self._responder_pedido(pedido)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        pedido = serializer.save()
        return self._responder_pedido(pedido, status.HTTP_201_CREATED)

    def perform_update(self, serializer):
        if serializer.instance.estado not in services.ESTADOS_EN_LOCAL:
            raise Conflicto("El pedido ya salió del local: no se puede modificar.")
        serializer.save()

    def perform_destroy(self, instance):
        if instance.estado != EstadoPedido.PENDIENTE:
            raise Conflicto("Solo se pueden borrar pedidos pendientes.")
        instance.delete()


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

class DashboardView(APIView):
    """
    GET → panorama del local en este momento: cuántos pedidos hay en cada estado,
    la lista de pedidos activos (los más antiguos primero, que son los urgentes),
    la carga de cada repartidor y los números del día.
    """

    @extend_schema(responses=inline_serializer("Dashboard", {
        "generado": serializers.DateTimeField(),
        "pedidos_por_estado": serializers.DictField(child=serializers.IntegerField()),
        "total_activos": serializers.IntegerField(),
        "sin_repartidor": serializers.IntegerField(),
        "alertas_pendientes": serializers.IntegerField(),
        "hoy": inline_serializer("DashboardHoy", {
            "entregados": serializers.IntegerField(),
            "facturacion": serializers.DecimalField(max_digits=12, decimal_places=2),
        }),
        "pedidos_activos": PedidoResumenSerializer(many=True),
        "repartidores": RepartidorCargaSerializer(many=True),
    }))
    def get(self, request):
        ahora = timezone.now()
        inicio_del_dia = timezone.localtime(ahora).replace(hour=0, minute=0, second=0,
                                                           microsecond=0)

        activos = (Pedido.objects.exclude(estado=EstadoPedido.ENTREGADO)
                   .select_related("cliente", "zona", "repartidor")
                   .order_by("fecha_creacion"))

        # order_by() vacío: si no, el orden por fecha se suma al GROUP BY y parte los grupos.
        conteo = dict(activos.order_by().values("estado").annotate(n=Count("id"))
                      .values_list("estado", "n"))
        por_estado = {estado: conteo.get(estado, 0) for estado in services.ORDEN_ESTADOS
                      if estado != EstadoPedido.ENTREGADO}

        entregados_hoy = Pedido.objects.filter(estado=EstadoPedido.ENTREGADO,
                                               fecha_entrega__gte=inicio_del_dia)
        repartidores = (Repartidor.objects.exclude(estado=Repartidor.Estado.INACTIVO)
                        .annotate(pedidos_activos=Count(
                            "pedidos", filter=~Q(pedidos__estado=EstadoPedido.ENTREGADO)))
                        .order_by("nombre"))

        activos = activos.prefetch_related("historial")
        contexto = {"ahora": ahora, "request": request}
        return Response({
            "generado": ahora,
            "pedidos_por_estado": por_estado,
            "total_activos": sum(por_estado.values()),
            "sin_repartidor": activos.filter(repartidor__isnull=True).count(),
            "alertas_pendientes": Alerta.objects.filter(resuelta=False).count(),
            "hoy": {
                "entregados": entregados_hoy.count(),
                "facturacion": str(entregados_hoy.aggregate(t=Sum("total"))["t"] or Decimal("0")),
            },
            "pedidos_activos": PedidoResumenSerializer(activos, many=True, context=contexto).data,
            "repartidores": RepartidorCargaSerializer(repartidores, many=True).data,
        })


# ---------------------------------------------------------------------------
# Seguimiento público
# ---------------------------------------------------------------------------

class SeguimientoView(APIView):
    """
    GET /api/seguimiento/{token}/ → estado del pedido para el cliente final.

    Es el único endpoint público: no pide login, porque el cliente no tiene cuenta.
    El token de 32 caracteres hexadecimales funciona como contraseña del pedido,
    y la respuesta solo trae el estado, el historial y el tiempo restante.
    Un token inexistente da 404, sin distinguir otros motivos.
    """
    permission_classes = [AllowAny]
    # Sin autenticación: así un header Authorization vencido no produce un 401.
    authentication_classes = []
    # Limita las consultas por IP para que no se puedan probar tokens al azar.
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "seguimiento"
    serializer_class = SeguimientoSerializer

    @extend_schema(responses={200: SeguimientoSerializer, 404: None, 429: None})
    def get(self, request, token):
        pedido = get_object_or_404(
            Pedido.objects.select_related("zona").prefetch_related("historial"),
            token_seguimiento=token)
        contexto = {"ahora": timezone.now(), "request": request}
        return Response(SeguimientoSerializer(pedido, context=contexto).data)
