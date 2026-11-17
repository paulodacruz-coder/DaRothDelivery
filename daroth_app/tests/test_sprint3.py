"""Sprint 3: seguimiento público del pedido y tiempo estimado de entrega."""
from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from django.utils import timezone
from rest_framework.throttling import ScopedRateThrottle

from daroth_app import services
from daroth_app.models import EstadoPedido, HistorialEstado, Pedido

from .base import BaseAPITest

PEN, PRE, LIS, CAM, ENT = (EstadoPedido.PENDIENTE, EstadoPedido.PREPARANDO, EstadoPedido.LISTO,
                           EstadoPedido.EN_CAMINO, EstadoPedido.ENTREGADO)


class Sprint3Base(BaseAPITest):

    def setUp(self):
        cache.clear()  # el límite de consultas se guarda en la caché
        self.como(self.encargado)
        r = self.crear_pedido_api()
        self.pedido_id = r.json()["id"]
        self.token = r.json()["token_seguimiento"]

    def avanzar(self, *estados):
        for estado in estados:
            r = self.client.post(f"/api/pedidos/{self.pedido_id}/estado/", {"estado": estado},
                                 format="json")
            self.assertEqual(r.status_code, 200, r.content)

    def seguir(self, token=None, **extra):
        self.client.force_authenticate(None)
        return self.client.get(f"/api/seguimiento/{token or self.token}/", **extra)

    def retroceder_reloj(self, minutos, estado=None):
        """Simula que el pedido (o la llegada a `estado`) ocurrió hace `minutos`."""
        cuando = timezone.now() - timedelta(minutes=minutos)
        if estado is None:
            Pedido.objects.filter(pk=self.pedido_id).update(fecha_creacion=cuando)
        else:
            HistorialEstado.objects.filter(pedido_id=self.pedido_id, estado=estado) \
                .update(fecha_hora=cuando)


class SeguimientoPublicoTest(Sprint3Base):

    def test_no_requiere_login(self):
        r = self.seguir()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["estado"], PEN)
        self.assertEqual(r.json()["estado_display"], "Pendiente")
        self.assertFalse(r.json()["entregado"])

    def test_un_token_vencido_en_el_header_no_bloquea_el_seguimiento(self):
        r = self.seguir(HTTP_AUTHORIZATION="Token token-que-no-existe")
        self.assertEqual(r.status_code, 200)

    def test_token_inexistente_da_404(self):
        self.assertEqual(self.seguir("0" * 32).status_code, 404)
        self.assertEqual(self.seguir("cualquier-cosa").status_code, 404)

    def test_no_expone_datos_internos(self):
        self.avanzar(PRE)
        datos = self.seguir().json()
        self.assertEqual(set(datos), {"estado", "estado_display", "entregado", "fecha_creacion",
                                      "hora_estimada_entrega", "minutos_restantes",
                                      "fecha_entrega", "historial"})
        self.assertEqual(set(datos["historial"][0]), {"estado", "estado_display", "fecha_hora"})
        # Ni el nombre del cliente ni el usuario del local aparecen en ningún lado.
        texto = self.seguir().content.decode()
        for dato in ("Martina", "Santa Fe", "encargado_test", "9500", "Palermo"):
            self.assertNotIn(dato, texto)

    def test_historial_en_orden(self):
        self.avanzar(PRE, LIS)
        estados = [h["estado"] for h in self.seguir().json()["historial"]]
        self.assertEqual(estados, [PEN, PRE, LIS])

    def test_pedido_entregado(self):
        self.avanzar(PRE, LIS)
        self.client.post(f"/api/pedidos/{self.pedido_id}/asignar/",
                         {"repartidor": self.repartidor.pk}, format="json")
        self.avanzar(CAM, ENT)
        datos = self.seguir().json()
        self.assertTrue(datos["entregado"])
        self.assertIsNone(datos["minutos_restantes"])
        self.assertIsNone(datos["hora_estimada_entrega"])
        self.assertIsNotNone(datos["fecha_entrega"])

    def test_solo_acepta_get(self):
        self.client.force_authenticate(None)
        r = self.client.post(f"/api/seguimiento/{self.token}/", {"estado": ENT}, format="json")
        self.assertEqual(r.status_code, 405)
        self.assertEqual(Pedido.objects.get(pk=self.pedido_id).estado, PEN)

    def test_limite_de_consultas(self):
        # ScopedRateThrottle lee las tasas al importarse; se bajan a 3/min para la prueba.
        with mock.patch.object(ScopedRateThrottle, "THROTTLE_RATES", {"seguimiento": "3/min"}):
            codigos = [self.seguir("f" * 32).status_code for _ in range(4)]
        self.assertEqual(codigos, [404, 404, 404, 429])


class EnlaceSeguimientoTest(Sprint3Base):

    def test_el_pedido_trae_el_enlace_publico(self):
        r = self.client.get(f"/api/pedidos/{self.pedido_id}/")
        enlace = r.json()["enlace_seguimiento"]
        self.assertTrue(enlace.startswith("http://testserver/api/seguimiento/"))
        self.assertTrue(enlace.endswith(f"/{self.token}/"))
        self.assertEqual(self.seguir(enlace.split("/")[-2]).status_code, 200)

    def test_cada_pedido_tiene_su_propio_token(self):
        otro = self.crear_pedido_api().json()["token_seguimiento"]
        self.assertNotEqual(otro, self.token)
        self.assertEqual(len(self.token), 32)


class TiempoEstimadoTest(Sprint3Base):
    """Pizza (15 min) a Palermo (10 min de viaje): tiempo estimado de 25 minutos."""

    def pedido(self):
        return Pedido.objects.select_related("zona").get(pk=self.pedido_id)

    def test_recien_tomado_faltan_los_minutos_estimados(self):
        datos = self.seguir().json()
        self.assertIn(datos["minutos_restantes"], (24, 25))

    def test_el_tiempo_corre(self):
        self.retroceder_reloj(10)
        self.assertIn(self.seguir().json()["minutos_restantes"], (14, 15))

    def test_si_la_cocina_se_atrasa_igual_falta_el_viaje(self):
        # Pasaron 40 min (se prometió para los 25) y sigue en preparación:
        # no se le dice al cliente "0 minutos", todavía falta el viaje a Palermo.
        self.avanzar(PRE)
        self.retroceder_reloj(40)
        self.assertIn(self.seguir().json()["minutos_restantes"], (9, 10))

    def test_en_camino_se_cuenta_desde_la_salida(self):
        self.avanzar(PRE, LIS)
        self.client.post(f"/api/pedidos/{self.pedido_id}/asignar/",
                         {"repartidor": self.repartidor.pk}, format="json")
        self.avanzar(CAM)
        self.retroceder_reloj(30)
        self.retroceder_reloj(4, estado=CAM)
        self.assertIn(self.seguir().json()["minutos_restantes"], (5, 6))

    def test_en_camino_demorado_no_da_negativo(self):
        self.avanzar(PRE, LIS)
        self.client.post(f"/api/pedidos/{self.pedido_id}/asignar/",
                         {"repartidor": self.repartidor.pk}, format="json")
        self.avanzar(CAM)
        self.retroceder_reloj(25, estado=CAM)
        self.assertEqual(self.seguir().json()["minutos_restantes"], 0)

    def test_calculo_con_hora_fija(self):
        pedido = self.pedido()
        ahora = pedido.fecha_creacion + timedelta(minutes=5)
        self.assertEqual(services.estimar_entrega(pedido, ahora),
                         pedido.fecha_creacion + timedelta(minutes=25))
        self.assertEqual(services.minutos_restantes(pedido, ahora), 20)
        # 30 segundos más tarde se redondea hacia arriba: siguen siendo 20.
        self.assertEqual(services.minutos_restantes(pedido, ahora + timedelta(seconds=30)), 20)

    def test_el_dashboard_muestra_los_minutos_restantes(self):
        self.como(self.encargado)
        fila = self.client.get("/api/dashboard/").json()["pedidos_activos"][0]
        self.assertIn(fila["minutos_restantes"], (24, 25))


class DocumentacionTest(BaseAPITest):

    def test_swagger_y_redoc_responden(self):
        self.assertEqual(self.client.get("/docs/").status_code, 200)
        self.assertEqual(self.client.get("/redoc/").status_code, 200)

    def test_el_esquema_incluye_todos_los_endpoints(self):
        r = self.client.get("/api/schema/", HTTP_ACCEPT="application/vnd.oai.openapi+json")
        self.assertEqual(r.status_code, 200)
        esquema = r.json()
        rutas = esquema["paths"]
        for ruta in ("/api/auth/login/", "/api/auth/logout/", "/api/auth/yo/",
                     "/api/pedidos/{id}/estado/", "/api/dashboard/",
                     "/api/seguimiento/{token}/"):
            self.assertIn(ruta, rutas)
        # El seguimiento figura como público; el resto exige token.
        self.assertEqual(rutas["/api/seguimiento/{token}/"]["get"]["security"], [{}])
        self.assertIn({"tokenAuth": []}, rutas["/api/dashboard/"]["get"]["security"])
