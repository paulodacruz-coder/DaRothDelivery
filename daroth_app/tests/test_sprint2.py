"""Sprint 2: máquina de estados, historial, asignación manual y dashboard."""
from decimal import Decimal

from daroth_app.models import EstadoPedido, HistorialEstado, Pedido, Repartidor

from .base import BaseAPITest

PEN, PRE, LIS, CAM, ENT = (EstadoPedido.PENDIENTE, EstadoPedido.PREPARANDO, EstadoPedido.LISTO,
                           EstadoPedido.EN_CAMINO, EstadoPedido.ENTREGADO)


class Sprint2Base(BaseAPITest):

    def setUp(self):
        self.como(self.encargado)
        self.pedido_id = self.crear_pedido_api().json()["id"]

    def avanzar(self, estado, pedido_id=None):
        return self.client.post(f"/api/pedidos/{pedido_id or self.pedido_id}/estado/",
                                {"estado": estado}, format="json")

    def asignar(self, repartidor, pedido_id=None):
        return self.client.post(f"/api/pedidos/{pedido_id or self.pedido_id}/asignar/",
                                {"repartidor": repartidor.pk}, format="json")


class MaquinaDeEstadosTest(Sprint2Base):

    def test_recorrido_completo(self):
        self.assertEqual(self.avanzar(PRE).status_code, 200)
        self.assertEqual(self.avanzar(LIS).status_code, 200)
        self.asignar(self.repartidor)
        self.assertEqual(self.avanzar(CAM).status_code, 200)
        r = self.avanzar(ENT)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["estado"], ENT)
        self.assertIsNone(r.json()["siguiente_estado"])
        self.assertIsNotNone(r.json()["fecha_entrega"])

        estados = list(HistorialEstado.objects.filter(pedido_id=self.pedido_id)
                       .order_by("fecha_hora", "id").values_list("estado", flat=True))
        self.assertEqual(estados, [PEN, PRE, LIS, CAM, ENT])

    def test_no_se_puede_saltear_un_estado(self):
        r = self.avanzar(LIS)
        self.assertEqual(r.status_code, 409)
        self.assertIn("Preparando", r.json()["detail"])
        self.assertEqual(Pedido.objects.get(pk=self.pedido_id).estado, PEN)
        self.assertEqual(HistorialEstado.objects.filter(pedido_id=self.pedido_id).count(), 1)

    def test_no_se_puede_retroceder_ni_repetir(self):
        self.avanzar(PRE)
        self.assertEqual(self.avanzar(PEN).status_code, 409)
        self.assertEqual(self.avanzar(PRE).status_code, 409, "un doble clic no avanza dos veces")

    def test_no_sale_sin_repartidor(self):
        self.avanzar(PRE)
        self.avanzar(LIS)
        r = self.avanzar(CAM)
        self.assertEqual(r.status_code, 409)
        self.assertIn("repartidor", r.json()["detail"])

    def test_entregado_no_admite_mas_cambios(self):
        for estado in (PRE, LIS):
            self.avanzar(estado)
        self.asignar(self.repartidor)
        self.avanzar(CAM)
        self.avanzar(ENT)
        self.assertEqual(self.avanzar(ENT).status_code, 409)

    def test_estado_inexistente_devuelve_400(self):
        self.assertEqual(self.avanzar("CANCELADO").status_code, 400)

    def test_historial_registra_usuario_solo_en_el_local(self):
        for estado in (PRE, LIS):
            self.avanzar(estado)
        self.asignar(self.repartidor)
        self.avanzar(CAM)
        r = self.client.get(f"/api/pedidos/{self.pedido_id}/historial/")
        self.assertEqual(r.status_code, 200)
        usuarios = {h["estado"]: h["usuario"] for h in r.json()}
        self.assertEqual(usuarios[PRE], "encargado_test")
        self.assertIsNone(usuarios[CAM], "EN_CAMINO lo registra el repartidor, no un usuario")

    def test_estado_del_repartidor_acompaña_al_pedido(self):
        for estado in (PRE, LIS):
            self.avanzar(estado)
        self.asignar(self.repartidor)
        self.avanzar(CAM)
        self.repartidor.refresh_from_db()
        self.assertEqual(self.repartidor.estado, Repartidor.Estado.EN_REPARTO)
        self.avanzar(ENT)
        self.repartidor.refresh_from_db()
        self.assertEqual(self.repartidor.estado, Repartidor.Estado.DISPONIBLE)

    def test_repartidor_sigue_en_reparto_si_le_quedan_pedidos_en_camino(self):
        otro_id = self.crear_pedido_api().json()["id"]
        for pid in (self.pedido_id, otro_id):
            self.avanzar(PRE, pid)
            self.avanzar(LIS, pid)
            self.asignar(self.repartidor, pid)
            self.avanzar(CAM, pid)
        self.avanzar(ENT, self.pedido_id)
        self.repartidor.refresh_from_db()
        self.assertEqual(self.repartidor.estado, Repartidor.Estado.EN_REPARTO)


class AsignacionManualTest(Sprint2Base):

    def test_asignar_y_reasignar(self):
        r = self.asignar(self.repartidor)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["repartidor_nombre"], "Lautaro")
        otro = Repartidor.objects.create(nombre="Daniela")
        self.assertEqual(self.asignar(otro).json()["repartidor"], otro.pk)

    def test_desasignar(self):
        self.asignar(self.repartidor)
        r = self.client.post(f"/api/pedidos/{self.pedido_id}/desasignar/")
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.json()["repartidor"])

    def test_repartidor_inactivo(self):
        inactivo = Repartidor.objects.create(nombre="Hernán", estado=Repartidor.Estado.INACTIVO)
        self.assertEqual(self.asignar(inactivo).status_code, 409)

    def test_respeta_la_capacidad_maxima(self):
        chico = Repartidor.objects.create(nombre="Gonzalo", capacidad_max=1)
        self.assertEqual(self.asignar(chico).status_code, 200)
        otro_id = self.crear_pedido_api().json()["id"]
        r = self.asignar(chico, otro_id)
        self.assertEqual(r.status_code, 409)
        self.assertIn("capacidad", r.json()["detail"])

    def test_pedidos_entregados_no_cuentan_como_carga(self):
        chico = Repartidor.objects.create(nombre="Gonzalo", capacidad_max=1)
        self.asignar(chico)
        Pedido.objects.filter(pk=self.pedido_id).update(estado=ENT)
        otro_id = self.crear_pedido_api().json()["id"]
        self.assertEqual(self.asignar(chico, otro_id).status_code, 200)

    def test_reasignar_al_mismo_no_ocupa_capacidad_extra(self):
        chico = Repartidor.objects.create(nombre="Gonzalo", capacidad_max=1)
        self.asignar(chico)
        self.assertEqual(self.asignar(chico).status_code, 200)

    def test_no_se_cambia_repartidor_de_un_pedido_en_camino(self):
        self.avanzar(PRE)
        self.avanzar(LIS)
        self.asignar(self.repartidor)
        self.avanzar(CAM)
        otro = Repartidor.objects.create(nombre="Daniela")
        self.assertEqual(self.asignar(otro).status_code, 409)
        r = self.client.post(f"/api/pedidos/{self.pedido_id}/desasignar/")
        self.assertEqual(r.status_code, 409)

    def test_repartidor_inexistente_devuelve_400(self):
        r = self.client.post(f"/api/pedidos/{self.pedido_id}/asignar/", {"repartidor": 9999},
                             format="json")
        self.assertEqual(r.status_code, 400)


class DashboardTest(Sprint2Base):

    def test_requiere_autenticacion(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get("/api/dashboard/").status_code, 401)

    def test_contenido(self):
        segundo = self.crear_pedido_api(cliente=self.cliente_belgrano).json()["id"]
        self.avanzar(PRE, segundo)
        self.asignar(self.repartidor, segundo)

        # Un pedido entregado hoy
        tercero = self.crear_pedido_api(items=[{"producto": self.gaseosa.pk, "cantidad": 2}]).json()["id"]
        self.avanzar(PRE, tercero)
        self.avanzar(LIS, tercero)
        self.asignar(self.repartidor, tercero)
        self.avanzar(CAM, tercero)
        self.avanzar(ENT, tercero)

        r = self.client.get("/api/dashboard/")
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertEqual(d["pedidos_por_estado"], {PEN: 1, PRE: 1, LIS: 0, CAM: 0})
        self.assertEqual(d["total_activos"], 2)
        self.assertEqual(d["sin_repartidor"], 1)
        self.assertEqual(d["hoy"]["entregados"], 1)
        self.assertEqual(Decimal(d["hoy"]["facturacion"]), Decimal("6000"))
        # El más antiguo primero
        self.assertEqual([p["id"] for p in d["pedidos_activos"]], [self.pedido_id, segundo])
        self.assertIn("minutos_transcurridos", d["pedidos_activos"][0])
        lautaro = next(x for x in d["repartidores"] if x["nombre"] == "Lautaro")
        self.assertEqual(lautaro["pedidos_activos"], 1)

    def test_no_muestra_repartidores_inactivos(self):
        Repartidor.objects.create(nombre="Hernán", estado=Repartidor.Estado.INACTIVO)
        nombres = [x["nombre"] for x in self.client.get("/api/dashboard/").json()["repartidores"]]
        self.assertNotIn("Hernán", nombres)

    def test_filtro_activos(self):
        Pedido.objects.filter(pk=self.pedido_id).update(estado=ENT)
        self.crear_pedido_api()
        self.assertEqual(self.client.get("/api/pedidos/?activos=1").json()["count"], 1)
