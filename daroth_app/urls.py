"""
Rutas del proyecto DaRoth Delivery.

/admin/              panel de administración de Django
/api/auth/...        login, logout y usuario actual
/api/<recurso>/      endpoints REST (ver el router)
/api-auth/           login de sesión para la API navegable de DRF
"""
from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("zonas", views.ZonaViewSet, basename="zona")
router.register("productos", views.ProductoViewSet, basename="producto")
router.register("repartidores", views.RepartidorViewSet, basename="repartidor")
router.register("clientes", views.ClienteViewSet, basename="cliente")
router.register("pedidos", views.PedidoViewSet, basename="pedido")

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/login/", views.LoginView.as_view(), name="login"),
    path("api/auth/logout/", views.LogoutView.as_view(), name="logout"),
    path("api/auth/yo/", views.UsuarioActualView.as_view(), name="usuario-actual"),
    path("api/dashboard/", views.DashboardView.as_view(), name="dashboard"),
    path("api/", include(router.urls)),
    path("api-auth/", include("rest_framework.urls")),
]
