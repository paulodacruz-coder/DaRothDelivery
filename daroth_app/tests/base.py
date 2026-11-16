"""Datos mínimos compartidos por las pruebas de todos los sprints."""
from decimal import Decimal

from django.contrib.auth.models import User
from rest_framework.test import APITestCase

from daroth_app.models import Cliente, Perfil, Producto, Repartidor, Zona


class BaseAPITest(APITestCase):

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user("admin_test", password="clave-segura-1")
        Perfil.objects.create(user=cls.admin, rol=Perfil.Rol.ADMINISTRADOR)
        cls.encargado = User.objects.create_user("encargado_test", password="clave-segura-2")
        Perfil.objects.create(user=cls.encargado, rol=Perfil.Rol.ENCARGADO)

        cls.palermo = Zona.objects.create(nombre="Palermo", latitud_centro=Decimal("-34.588900"),
                                          longitud_centro=Decimal("-58.430600"), tiempo_viaje_min=10)
        cls.belgrano = Zona.objects.create(nombre="Belgrano", latitud_centro=Decimal("-34.562700"),
                                           longitud_centro=Decimal("-58.458300"), tiempo_viaje_min=20)

        cls.pizza = Producto.objects.create(nombre="Pizza", precio=Decimal("9500"),
                                            tiempo_preparacion_min=15)
        cls.empanada = Producto.objects.create(nombre="Empanada", precio=Decimal("1500"),
                                               tiempo_preparacion_min=10)
        cls.gaseosa = Producto.objects.create(nombre="Gaseosa", precio=Decimal("3000"),
                                              tiempo_preparacion_min=1)

        cls.cliente = Cliente.objects.create(nombre="Martina", direccion="Santa Fe 3450",
                                             zona=cls.palermo)
        cls.cliente_belgrano = Cliente.objects.create(nombre="Mateo", direccion="Cabildo 1850",
                                                      zona=cls.belgrano)

        cls.repartidor = Repartidor.objects.create(
            nombre="Lautaro", latitud=Decimal("-34.590100"), longitud=Decimal("-58.428000"))

    def como(self, usuario):
        self.client.force_authenticate(usuario)

    def crear_pedido_api(self, cliente=None, items=None):
        cliente = cliente or self.cliente
        items = items or [{"producto": self.pizza.pk, "cantidad": 1}]
        return self.client.post("/api/pedidos/", {"cliente": cliente.pk, "items": items},
                                format="json")
