from django.contrib.auth import authenticate
from django.db.models import ProtectedError, Q
from rest_framework import mixins, status, viewsets
from rest_framework.authtoken.models import Token
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .excepciones import Conflicto
from .models import Cliente, EstadoPedido, Pedido, Producto, Repartidor, Zona
from .permissions import EsAdministradorOSoloLectura
from .serializers import (
    ClienteSerializer, LoginSerializer, PedidoActualizarSerializer, PedidoCrearSerializer,
    PedidoSerializer, ProductoSerializer, RepartidorSerializer, UsuarioSerializer,
    ZonaSerializer,
)


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

    def post(self, request):
        Token.objects.filter(user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class UsuarioActualView(APIView):
    """GET → datos y rol del usuario autenticado."""

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
    serializer_class = RepartidorSerializer
    permission_classes = [EsAdministradorOSoloLectura]

    def get_queryset(self):
        qs = Repartidor.objects.all()
        estado = self.request.query_params.get("estado")
        if estado:
            qs = qs.filter(estado=estado.upper())
        return qs


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

# Una vez que el pedido salió del local ya no se puede modificar ni borrar.
ESTADOS_EDITABLES = {EstadoPedido.PENDIENTE, EstadoPedido.PREPARANDO, EstadoPedido.LISTO}


class PedidoViewSet(mixins.CreateModelMixin, mixins.ListModelMixin,
                    mixins.RetrieveModelMixin, mixins.UpdateModelMixin,
                    mixins.DestroyModelMixin, viewsets.GenericViewSet):
    """
    CRUD de pedidos.
    Filtros: ?estado=PENDIENTE&zona=<id>&repartidor=<id>
    El cambio de estado y la asignación de repartidor tienen sus propios endpoints (Sprint 2).
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
        return qs

    def get_serializer_class(self):
        if self.action == "create":
            return PedidoCrearSerializer
        if self.action in ("update", "partial_update"):
            return PedidoActualizarSerializer
        return PedidoSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        pedido = serializer.save()
        # Se vuelve a leer con el queryset optimizado para devolver historial y detalles.
        pedido = self.get_queryset().get(pk=pedido.pk)
        return Response(PedidoSerializer(pedido, context=self.get_serializer_context()).data,
                        status=status.HTTP_201_CREATED)

    def perform_update(self, serializer):
        if serializer.instance.estado not in ESTADOS_EDITABLES:
            raise Conflicto("El pedido ya salió del local: no se puede modificar.")
        serializer.save()

    def perform_destroy(self, instance):
        if instance.estado != EstadoPedido.PENDIENTE:
            raise Conflicto("Solo se pueden borrar pedidos pendientes.")
        instance.delete()
