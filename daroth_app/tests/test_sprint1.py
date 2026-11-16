"""Sprint 1: modelos, autenticación, permisos y CRUD básico."""
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from rest_framework.authtoken.models import Token

from daroth_app.models import (
    Alerta, DetallePedido, EstadoPedido, HistorialEstado, Pedido, Perfil, Zona,
)
from daroth_app.services import calcular_tiempo_estimado

from .base import BaseAPITest


class ModelosTest(BaseAPITest):

    def setUp(self):
        self.como(self.encargado)

    def test_str_no_lanzan_errores(self):
        pedido = self.crear_pedido_api().json()
        pedido = Pedido.objects.get(pk=pedido["id"])
        self.assertEqual(str(pedido), f"Pedido #{pedido.pk} - Martina")
        self.assertEqual(str(pedido.historial.first()), f"Pedido #{pedido.pk} - Pendiente")
        self.assertEqual(str(self.admin.perfil), "admin_test (Administrador)")

    def test_token_se_genera_y_es_unico(self):
        a = Pedido.objects.get(pk=self.crear_pedido_api().json()["id"])
        b = Pedido.objects.get(pk=self.crear_pedido_api().json()["id"])
        self.assertEqual(len(a.token_seguimiento), 32)
        self.assertNotEqual(a.token_seguimiento, b.token_seguimiento)

    def test_tiempo_estimado(self):
        # max(15, 10) de preparación + 10 de viaje a Palermo
        self.assertEqual(calcular_tiempo_estimado([self.pizza, self.empanada], self.palermo), 25)


class AutenticacionTest(BaseAPITest):

    def test_login_correcto_devuelve_token_y_rol(self):
        r = self.client.post("/api/auth/login/",
                             {"username": "encargado_test", "password": "clave-segura-2"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["usuario"]["rol"], Perfil.Rol.ENCARGADO)
        self.assertTrue(Token.objects.filter(key=r.json()["token"]).exists())

    def test_login_incorrecto(self):
        r = self.client.post("/api/auth/login/",
                             {"username": "encargado_test", "password": "mal"})
        self.assertEqual(r.status_code, 400)

    def test_token_permite_acceder_y_logout_lo_invalida(self):
        token = self.client.post("/api/auth/login/", {
            "username": "admin_test", "password": "clave-segura-1"}).json()["token"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        self.assertEqual(self.client.get("/api/auth/yo/").status_code, 200)
        self.assertEqual(self.client.post("/api/auth/logout/").status_code, 204)
        self.assertEqual(self.client.get("/api/auth/yo/").status_code, 401)

    def test_sin_autenticar_devuelve_401(self):
        for url in ("/api/pedidos/", "/api/zonas/", "/api/clientes/", "/api/repartidores/"):
            self.assertEqual(self.client.get(url).status_code, 401, url)


class PermisosCatalogoTest(BaseAPITest):

    def test_encargado_puede_leer_pero_no_modificar_catalogo(self):
        self.como(self.encargado)
        self.assertEqual(self.client.get("/api/zonas/").status_code, 200)
        r = self.client.post("/api/zonas/", {"nombre": "Núñez", "latitud_centro": "-34.545",
                                             "longitud_centro": "-58.463", "tiempo_viaje_min": 25})
        self.assertEqual(r.status_code, 403)

    def test_admin_puede_crear_zona(self):
        self.como(self.admin)
        r = self.client.post("/api/zonas/", {"nombre": "Núñez", "latitud_centro": "-34.545",
                                             "longitud_centro": "-58.463", "tiempo_viaje_min": 25})
        self.assertEqual(r.status_code, 201)

    def test_borrar_zona_en_uso_devuelve_409(self):
        self.como(self.admin)
        self.assertEqual(self.client.delete(f"/api/zonas/{self.palermo.pk}/").status_code, 409)
        self.assertTrue(Zona.objects.filter(pk=self.palermo.pk).exists())

    def test_encargado_puede_dar_de_alta_clientes(self):
        self.como(self.encargado)
        r = self.client.post("/api/clientes/", {"nombre": "Martina", "direccion": "Otra 123",
                                                "zona": self.palermo.pk})
        self.assertEqual(r.status_code, 201, "dos clientes pueden llamarse igual")


class PedidosTest(BaseAPITest):

    def setUp(self):
        self.como(self.encargado)

    def test_crear_pedido_calcula_todo_en_el_servidor(self):
        r = self.crear_pedido_api(items=[
            {"producto": self.pizza.pk, "cantidad": 2},
            {"producto": self.empanada.pk, "cantidad": 3},
        ])
        self.assertEqual(r.status_code, 201, r.content)
        datos = r.json()
        self.assertEqual(Decimal(datos["total"]), Decimal("23500"))   # 2×9500 + 3×1500
        self.assertEqual(datos["tiempo_estimado_min"], 25)
        self.assertEqual(datos["estado"], EstadoPedido.PENDIENTE)
        self.assertEqual(datos["zona"], self.palermo.pk)
        self.assertEqual(datos["direccion_entrega"], "Santa Fe 3450")
        self.assertEqual(datos["usuario"], "encargado_test")
        self.assertEqual(len(datos["historial"]), 1)
        self.assertEqual(len(datos["detalles"]), 2)

    def test_precio_unitario_queda_congelado(self):
        pedido_id = self.crear_pedido_api().json()["id"]
        self.pizza.precio = Decimal("12000")
        self.pizza.save()
        detalle = DetallePedido.objects.get(pedido_id=pedido_id)
        self.assertEqual(detalle.precio_unitario, Decimal("9500"))

    def test_productos_repetidos_o_sin_items_devuelve_400(self):
        r = self.crear_pedido_api(items=[{"producto": self.pizza.pk, "cantidad": 1},
                                         {"producto": self.pizza.pk, "cantidad": 2}])
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/pedidos/", {"cliente": self.cliente.pk, "items": []},
                             format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Pedido.objects.count(), 0)

    def test_cantidad_invalida_devuelve_400(self):
        r = self.crear_pedido_api(items=[{"producto": self.pizza.pk, "cantidad": 0}])
        self.assertEqual(r.status_code, 400)

    def test_no_se_puede_fijar_estado_ni_total_al_crear(self):
        r = self.client.post("/api/pedidos/", {
            "cliente": self.cliente.pk, "estado": "ENTREGADO", "total": "1",
            "items": [{"producto": self.pizza.pk, "cantidad": 1}]}, format="json")
        self.assertEqual(r.json()["estado"], EstadoPedido.PENDIENTE)
        self.assertEqual(Decimal(r.json()["total"]), Decimal("9500"))

    def test_filtro_por_estado(self):
        self.crear_pedido_api()
        self.assertEqual(self.client.get("/api/pedidos/?estado=pendiente").json()["count"], 1)
        self.assertEqual(self.client.get("/api/pedidos/?estado=ENTREGADO").json()["count"], 0)

    def test_modificar_direccion(self):
        pedido_id = self.crear_pedido_api().json()["id"]
        r = self.client.patch(f"/api/pedidos/{pedido_id}/", {"direccion_entrega": "Nueva 1"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["direccion_entrega"], "Nueva 1")

    def test_pedido_en_camino_no_se_modifica_ni_borra(self):
        pedido_id = self.crear_pedido_api().json()["id"]
        Pedido.objects.filter(pk=pedido_id).update(estado=EstadoPedido.EN_CAMINO)
        r = self.client.patch(f"/api/pedidos/{pedido_id}/", {"direccion_entrega": "X"})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.client.delete(f"/api/pedidos/{pedido_id}/").status_code, 409)

    def test_borrar_pedido_pendiente(self):
        pedido_id = self.crear_pedido_api().json()["id"]
        self.assertEqual(self.client.delete(f"/api/pedidos/{pedido_id}/").status_code, 204)
        self.assertFalse(HistorialEstado.objects.filter(pedido_id=pedido_id).exists())


class CargarDatosTest(BaseAPITest):

    def test_cargar_datos_con_reset(self):
        call_command("cargar_datos", "--reset", stdout=StringIO())
        self.assertEqual(Pedido.objects.count(), 18)
        self.assertEqual(DetallePedido.objects.count(), 34)
        self.assertEqual(HistorialEstado.objects.count(), 70)
        self.assertEqual(Alerta.objects.count(), 5)
        self.assertEqual(Pedido.objects.filter(estado=EstadoPedido.ENTREGADO).count(), 10)
        # EN_CAMINO y ENTREGADO no tienen usuario del sistema
        self.assertFalse(HistorialEstado.objects.filter(
            estado__in=[EstadoPedido.EN_CAMINO, EstadoPedido.ENTREGADO],
            usuario__isnull=False).exists())
