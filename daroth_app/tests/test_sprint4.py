"""Sprint 4: ubicación de repartidores, asignación inteligente (Strategy) y ranking."""
from decimal import Decimal

from daroth_app import services
from daroth_app.asignacion import (
    AsignacionPorCercaniaYCarga, EstrategiaAsignacion, distancia_km,
)
from daroth_app.models import EstadoPedido, Pedido, Repartidor

from .base import BaseAPITest

D, R, I = Repartidor.Estado.DISPONIBLE, Repartidor.Estado.EN_REPARTO, Repartidor.Estado.INACTIVO


class Sprint4Base(BaseAPITest):
    """
    El pedido base va a Palermo (centro -34.5889, -58.4306).
    - Lautaro (base.py): a ~0,3 km del centro de Palermo.
    - Sofía: a ~3,8 km, en Belgrano.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.sofia = Repartidor.objects.create(
            nombre="Sofía", latitud=Decimal("-34.562700"), longitud=Decimal("-58.458300"))

    def setUp(self):
        self.como(self.encargado)
        self.pedido_id = self.crear_pedido_api().json()["id"]

    def sugerencia(self, pedido_id=None):
        return self.client.get(f"/api/pedidos/{pedido_id or self.pedido_id}/sugerencia/")

    def ranking(self, pedido_id=None):
        return [c["nombre"] for c in self.sugerencia(pedido_id).json()["ranking"]]

    def asignar(self, repartidor, pedido_id=None):
        r = self.client.post(f"/api/pedidos/{pedido_id or self.pedido_id}/asignar/",
                             {"repartidor": repartidor.pk}, format="json")
        self.assertEqual(r.status_code, 200, r.content)

    def pedido_extra(self, cliente=None):
        return self.crear_pedido_api(cliente).json()["id"]


class HaversineTest(BaseAPITest):

    def test_misma_posicion_es_cero(self):
        self.assertAlmostEqual(distancia_km(-34.6, -58.4, -34.6, -58.4), 0)

    def test_distancia_conocida(self):
        # Obelisco → Plaza de Mayo: unos 1,2 km en línea recta.
        d = distancia_km("-34.603722", "-58.381592", "-34.608147", "-58.370226")
        self.assertAlmostEqual(d, 1.15, delta=0.1)

    def test_entre_palermo_y_belgrano(self):
        self.assertAlmostEqual(distancia_km(-34.5889, -58.4306, -34.5627, -58.4583), 3.8, delta=0.2)


class RankingTest(Sprint4Base):

    def test_gana_el_mas_cercano(self):
        r = self.sugerencia()
        self.assertEqual(r.status_code, 200)
        datos = r.json()
        self.assertEqual([c["nombre"] for c in datos["ranking"]], ["Lautaro", "Sofía"])
        self.assertEqual([c["posicion"] for c in datos["ranking"]], [1, 2])
        self.assertEqual(datos["estrategia"], "cercania_y_carga")
        self.assertEqual(datos["zona"], "Palermo")
        primero = datos["ranking"][0]
        self.assertLess(primero["distancia_km"], 0.5)
        self.assertEqual(primero["pedidos_activos"], 0)
        self.assertEqual(primero["puntaje"], primero["distancia_km"])

    def test_la_carga_pesa_dos_puntos_por_pedido(self):
        # Lautaro lleva dos pedidos a Belgrano: 0,3 + 2×2 = 4,3 > 3,8 de Sofía.
        for _ in range(2):
            self.asignar(self.repartidor, self.pedido_extra(self.cliente_belgrano))
        datos = self.sugerencia().json()["ranking"]
        self.assertEqual([c["nombre"] for c in datos], ["Sofía", "Lautaro"])
        lautaro = datos[1]
        self.assertEqual(lautaro["pedidos_activos"], 2)
        self.assertFalse(lautaro["misma_zona"])
        self.assertAlmostEqual(lautaro["puntaje"], lautaro["distancia_km"] + 4, places=1)

    def test_bono_por_ir_a_la_misma_zona(self):
        # Sofía ya lleva un pedido a Palermo: 3,8 + 2 − 1,5.
        self.asignar(self.sofia, self.pedido_extra())
        sofia = next(c for c in self.sugerencia().json()["ranking"] if c["nombre"] == "Sofía")
        self.assertTrue(sofia["misma_zona"])
        self.assertAlmostEqual(sofia["puntaje"], sofia["distancia_km"] + 2 - 1.5, places=1)

    def test_el_pedido_propio_no_cuenta_como_carga(self):
        self.asignar(self.repartidor)
        lautaro = self.sugerencia().json()["ranking"][0]
        self.assertEqual(lautaro["nombre"], "Lautaro")
        self.assertEqual(lautaro["pedidos_activos"], 0)
        self.assertFalse(lautaro["misma_zona"])
        self.assertEqual(self.sugerencia().json()["repartidor_actual"], self.repartidor.pk)

    def test_los_entregados_no_cuentan(self):
        otro = self.pedido_extra()
        self.asignar(self.repartidor, otro)
        Pedido.objects.filter(pk=otro).update(estado=EstadoPedido.ENTREGADO)
        self.assertEqual(self.sugerencia().json()["ranking"][0]["pedidos_activos"], 0)

    def test_descartados_con_motivo(self):
        Repartidor.objects.create(nombre="Inactivo", estado=I,
                                  latitud=Decimal("-34.59"), longitud=Decimal("-58.43"))
        Repartidor.objects.create(nombre="En la calle", estado=R,
                                  latitud=Decimal("-34.59"), longitud=Decimal("-58.43"))
        Repartidor.objects.create(nombre="Sin GPS")
        lleno = Repartidor.objects.create(nombre="Lleno", capacidad_max=1,
                                          latitud=Decimal("-34.59"), longitud=Decimal("-58.43"))
        self.asignar(lleno, self.pedido_extra())

        datos = self.sugerencia().json()
        self.assertEqual([c["nombre"] for c in datos["ranking"]], ["Lautaro", "Sofía"])
        motivos = {d["nombre"]: d["motivo"] for d in datos["descartados"]}
        self.assertIn("inactivo", motivos["Inactivo"])
        self.assertIn("en reparto", motivos["En la calle"])
        self.assertIn("ubicación", motivos["Sin GPS"])
        self.assertIn("Capacidad completa (1/1)", motivos["Lleno"])

    def test_no_se_sugiere_para_un_pedido_que_ya_salio(self):
        Pedido.objects.filter(pk=self.pedido_id).update(estado=EstadoPedido.EN_CAMINO)
        self.assertEqual(self.sugerencia().status_code, 409)

    def test_la_estrategia_se_puede_usar_sin_la_api(self):
        candidatos = AsignacionPorCercaniaYCarga().sugerir(Pedido.objects.get(pk=self.pedido_id))
        self.assertEqual(candidatos.mejor.repartidor, self.repartidor)


class EstrategiaTest(Sprint4Base):
    """El patrón Strategy permite cambiar el criterio sin tocar el resto."""

    def test_otra_estrategia_cambia_el_ranking(self):
        class AlReves(EstrategiaAsignacion):
            nombre = "al_reves"

            def puntuar(self, pedido, candidato):
                return -candidato.distancia_km

        pedido = Pedido.objects.get(pk=self.pedido_id)
        ranking = services.sugerir_repartidor(pedido, AlReves()).ranking
        self.assertEqual([c.repartidor.nombre for c in ranking], ["Sofía", "Lautaro"])

    def test_la_clase_base_es_abstracta(self):
        with self.assertRaises(TypeError):
            EstrategiaAsignacion()


class AsignacionAutomaticaTest(Sprint4Base):

    def automatica(self, pedido_id=None):
        return self.client.post(f"/api/pedidos/{pedido_id or self.pedido_id}/asignar/",
                                {"automatica": True}, format="json")

    def test_asigna_al_primero_del_ranking(self):
        r = self.automatica()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["repartidor"], self.repartidor.pk)

    def test_409_si_nadie_puede(self):
        Repartidor.objects.update(estado=I)
        r = self.automatica()
        self.assertEqual(r.status_code, 409)
        self.assertIn("No hay repartidores disponibles", r.json()["detail"])
        self.assertIsNone(Pedido.objects.get(pk=self.pedido_id).repartidor_id)

    def test_reparte_cuando_se_llena_la_capacidad(self):
        Repartidor.objects.filter(pk=self.repartidor.pk).update(capacidad_max=1)
        self.automatica()
        otro = self.pedido_extra()
        r = self.automatica(otro)
        self.assertEqual(r.json()["repartidor"], self.sofia.pk)

    def test_pide_repartidor_o_automatica(self):
        url = f"/api/pedidos/{self.pedido_id}/asignar/"
        self.assertEqual(self.client.post(url, {}, format="json").status_code, 400)
        r = self.client.post(url, {"automatica": True, "repartidor": self.sofia.pk},
                             format="json")
        self.assertEqual(r.status_code, 400)

    def test_la_manual_sigue_funcionando(self):
        self.asignar(self.sofia)
        self.assertEqual(Pedido.objects.get(pk=self.pedido_id).repartidor, self.sofia)


class UbicacionTest(Sprint4Base):

    def url(self, repartidor=None):
        return f"/api/repartidores/{(repartidor or self.sofia).pk}/ubicacion/"

    def test_el_encargado_actualiza_la_ubicacion(self):
        r = self.client.post(self.url(), {"latitud": "-34.588000", "longitud": "-58.430000"},
                             format="json")
        self.assertEqual(r.status_code, 200)
        self.sofia.refresh_from_db()
        self.assertEqual(self.sofia.latitud, Decimal("-34.588000"))
        # Ahora Sofía está más cerca de Palermo que Lautaro.
        self.assertEqual(self.ranking()[0], "Sofía")

    def test_valida_rangos(self):
        r = self.client.post(self.url(), {"latitud": "95", "longitud": "-58.43"}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.client.post(self.url(), {"latitud": "-34.5"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_requiere_login(self):
        self.client.force_authenticate(None)
        r = self.client.post(self.url(), {"latitud": "-34.5", "longitud": "-58.4"},
                             format="json")
        self.assertEqual(r.status_code, 401)

    def test_sin_ubicacion_queda_fuera_y_al_cargarla_entra(self):
        nuevo = Repartidor.objects.create(nombre="Nuevo")
        self.assertNotIn("Nuevo", self.ranking())
        self.client.post(self.url(nuevo), {"latitud": "-34.588900", "longitud": "-58.430600"},
                         format="json")
        self.assertEqual(self.ranking()[0], "Nuevo")


class DisponibilidadTest(Sprint4Base):

    def cambiar(self, estado, repartidor=None):
        return self.client.post(f"/api/repartidores/{(repartidor or self.sofia).pk}/disponibilidad/",
                                {"estado": estado}, format="json")

    def test_terminar_y_empezar_turno(self):
        self.assertEqual(self.cambiar(I).json()["estado"], I)
        self.assertNotIn("Sofía", self.ranking())
        self.assertEqual(self.cambiar(D).json()["estado"], D)
        self.assertIn("Sofía", self.ranking())

    def test_en_reparto_no_se_elige_a_mano(self):
        self.assertEqual(self.cambiar(R).status_code, 400)

    def test_no_se_da_de_baja_con_pedidos_asignados(self):
        self.asignar(self.sofia)
        r = self.cambiar(I)
        self.assertEqual(r.status_code, 409)
        self.assertIn("reasignalos", r.json()["detail"])

    def test_en_reparto_no_vuelve_a_disponible_a_mano(self):
        Repartidor.objects.filter(pk=self.sofia.pk).update(estado=R)
        self.assertEqual(self.cambiar(D).status_code, 409)

    def test_el_estado_no_se_edita_por_el_crud(self):
        self.como(self.admin)
        r = self.client.patch(f"/api/repartidores/{self.sofia.pk}/", {"estado": I}, format="json")
        self.assertEqual(r.status_code, 400)
        # El resto de los datos sí.
        r = self.client.patch(f"/api/repartidores/{self.sofia.pk}/", {"vehiculo": "bici"},
                              format="json")
        self.assertEqual(r.status_code, 200)

    def test_no_se_borra_un_repartidor_con_pedidos_activos(self):
        self.asignar(self.sofia)
        self.como(self.admin)
        self.assertEqual(self.client.delete(f"/api/repartidores/{self.sofia.pk}/").status_code,
                         409)
