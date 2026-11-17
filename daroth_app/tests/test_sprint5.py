"""Sprint 5: alertas de demora, vistas SQL de reportes y estadísticas."""
from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.utils import timezone

from daroth_app import services
from daroth_app.models import (
    Alerta, EstadoPedido, HistorialEstado, Pedido, Repartidor, VistaDemandaZona,
    VistaPedidoActivo, VistaProductoVendido, VistaRendimientoRepartidor, VistaTiemposPedido,
)

from .base import BaseAPITest

PEN, PRE, LIS, CAM, ENT = services.ORDEN_ESTADOS


class Sprint5Base(BaseAPITest):
    """Una pizza a Palermo tiene un tiempo estimado de 25 min (15 de cocina + 10 de viaje)."""

    def setUp(self):
        self.como(self.encargado)

    def pedido_recorrido(self, etapas=(), hace_min=0, cliente=None, repartidor=None, items=None):
        """
        Crea un pedido y lo hace avanzar con tiempos controlados.
        etapas: minutos que tardó cada paso (Pendiente→Preparando, →Listo, →En camino,
        →Entregado); se avanza tantos estados como etapas se pasen.
        hace_min: hace cuántos minutos se tomó el pedido.
        """
        pedido_id = self.crear_pedido_api(cliente, items).json()["id"]
        momento = timezone.now() - timedelta(minutes=hace_min)
        Pedido.objects.filter(pk=pedido_id).update(fecha_creacion=momento)
        HistorialEstado.objects.filter(pedido_id=pedido_id).update(fecha_hora=momento)

        estado = PEN
        for estado, minutos in zip(services.ORDEN_ESTADOS[1:], etapas):
            momento += timedelta(minutes=minutos)
            registro = HistorialEstado.objects.create(pedido_id=pedido_id, estado=estado)
            HistorialEstado.objects.filter(pk=registro.pk).update(fecha_hora=momento)
        Pedido.objects.filter(pk=pedido_id).update(
            estado=estado, repartidor=repartidor,
            fecha_entrega=momento if estado == ENT else None)
        return Pedido.objects.get(pk=pedido_id)


# ---------------------------------------------------------------------------
# Alertas de demora
# ---------------------------------------------------------------------------

class AlertasDeDemoraTest(Sprint5Base):

    def test_se_genera_al_pasar_el_estimado_mas_la_tolerancia(self):
        pedido = self.pedido_recorrido(etapas=[2], hace_min=36)   # límite: 25 + 10 = 35
        nuevas = services.revisar_demoras()
        self.assertEqual([a.pedido_id for a in nuevas], [pedido.pk])
        alerta = Alerta.objects.get(pedido=pedido)
        self.assertEqual(alerta.tipo, "DEMORA")
        self.assertFalse(alerta.resuelta)
        self.assertIn("25 min", alerta.mensaje)

    def test_no_antes_del_limite(self):
        self.pedido_recorrido(etapas=[2], hace_min=34)
        self.assertEqual(services.revisar_demoras(), [])

    def test_no_se_duplica_si_ya_hay_una_pendiente(self):
        self.pedido_recorrido(hace_min=50)
        services.revisar_demoras()
        self.assertEqual(services.revisar_demoras(), [])
        self.assertEqual(Alerta.objects.count(), 1)

    def test_los_entregados_no_generan_alerta(self):
        self.pedido_recorrido(etapas=[5, 20, 5, 30], hace_min=120)
        self.assertEqual(services.revisar_demoras(), [])

    def test_la_tolerancia_depende_de_cada_pedido(self):
        # Belgrano: 15 + 20 = 35 min estimados, límite a los 45.
        self.pedido_recorrido(hace_min=40, cliente=self.cliente_belgrano)
        self.assertEqual(services.revisar_demoras(), [])
        self.pedido_recorrido(hace_min=46, cliente=self.cliente_belgrano)
        self.assertEqual(len(services.revisar_demoras()), 1)

    def test_se_resuelve_sola_al_entregar(self):
        pedido = self.pedido_recorrido(etapas=[2, 15, 3], hace_min=40, repartidor=self.repartidor)
        services.revisar_demoras()
        r = self.client.post(f"/api/pedidos/{pedido.pk}/estado/", {"estado": ENT}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(Alerta.objects.get(pedido=pedido).resuelta)

    def test_el_listado_revisa_las_demoras(self):
        pedido = self.pedido_recorrido(hace_min=40)
        r = self.client.get("/api/alertas/?resuelta=0")
        self.assertEqual(r.status_code, 200)
        alerta = r.json()["results"][0]
        self.assertEqual(alerta["pedido"], pedido.pk)
        self.assertEqual(alerta["cliente_nombre"], "Martina")
        self.assertEqual(alerta["estado_pedido"], PEN)
        self.assertIn(alerta["minutos_transcurridos"], (39, 40))

    def test_filtro_por_resuelta(self):
        self.pedido_recorrido(hace_min=40)
        self.client.get("/api/alertas/")
        self.assertEqual(self.client.get("/api/alertas/?resuelta=1").json()["count"], 0)
        self.assertEqual(self.client.get("/api/alertas/?resuelta=0").json()["count"], 1)

    def test_el_dashboard_cuenta_las_alertas_nuevas(self):
        self.pedido_recorrido(hace_min=40)
        self.assertEqual(self.client.get("/api/dashboard/").json()["alertas_pendientes"], 1)

    def test_las_alertas_son_de_solo_lectura(self):
        self.pedido_recorrido(hace_min=40)
        services.revisar_demoras()
        alerta = Alerta.objects.get()
        self.assertEqual(self.client.delete(f"/api/alertas/{alerta.pk}/").status_code, 405)

    def test_comando_revisar_demoras(self):
        self.pedido_recorrido(hace_min=40)
        salida = StringIO()
        call_command("revisar_demoras", stdout=salida)
        self.assertIn("Alertas nuevas: 1", salida.getvalue())


# ---------------------------------------------------------------------------
# Vistas SQL
# ---------------------------------------------------------------------------

class VistaTiemposPedidoTest(Sprint5Base):

    def test_minutos_de_cada_etapa(self):
        pedido = self.pedido_recorrido(etapas=[2, 15, 3, 20], hace_min=60,
                                       repartidor=self.repartidor)
        fila = VistaTiemposPedido.objects.get(pedido=pedido)
        self.assertEqual((fila.min_espera, fila.min_preparacion, fila.min_despacho,
                          fila.min_viaje, fila.min_total), (2, 15, 3, 20, 40))
        self.assertFalse(fila.a_tiempo, "40 min contra 25 estimados + 10 de tolerancia")
        self.assertEqual(fila.repartidor_id, self.repartidor.pk)
        self.assertEqual(fila.zona_id, self.palermo.pk)

    def test_a_tiempo_es_la_misma_regla_que_las_alertas(self):
        # 25 estimados + 10 de tolerancia = 35: hasta 35 está a tiempo, 36 ya no.
        justo = self.pedido_recorrido(etapas=[2, 15, 3, 15], hace_min=60)
        tarde = self.pedido_recorrido(etapas=[2, 15, 3, 16], hace_min=60)
        self.assertTrue(VistaTiemposPedido.objects.get(pedido=justo).a_tiempo)
        self.assertFalse(VistaTiemposPedido.objects.get(pedido=tarde).a_tiempo)

    def test_pedido_en_curso(self):
        pedido = self.pedido_recorrido(etapas=[4], hace_min=10)
        fila = VistaTiemposPedido.objects.get(pedido=pedido)
        self.assertEqual(fila.min_espera, 4)
        self.assertIsNone(fila.min_preparacion)
        self.assertIsNone(fila.min_total)
        self.assertIsNone(fila.a_tiempo)

    def test_endpoint_paginado_y_filtrado(self):
        self.pedido_recorrido(etapas=[1, 12, 2, 10], hace_min=60)
        self.pedido_recorrido(hace_min=5)
        r = self.client.get("/api/reportes/tiempos-pedido/?estado=entregado")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["count"], 1)
        self.assertEqual(r.json()["results"][0]["min_total"], 25)


class VistaPedidosActivosTest(Sprint5Base):

    def test_solo_activos_con_minutos_y_alerta(self):
        self.pedido_recorrido(etapas=[1, 12, 2, 10], hace_min=60)
        demorado = self.pedido_recorrido(hace_min=40)
        reciente = self.pedido_recorrido(hace_min=5)
        services.revisar_demoras()

        filas = {f.pedido_id: f for f in VistaPedidoActivo.objects.all()}
        self.assertEqual(set(filas), {demorado.pk, reciente.pk})
        # Compara contra UTC_TIMESTAMP(): si usara NOW() daría 3 horas de diferencia.
        self.assertIn(filas[demorado.pk].min_transcurridos, (39, 40))
        self.assertIn(filas[demorado.pk].min_excedidos, (14, 15))
        self.assertTrue(filas[demorado.pk].alerta_pendiente)
        self.assertEqual(filas[reciente.pk].min_excedidos, 0)
        self.assertFalse(filas[reciente.pk].alerta_pendiente)
        self.assertEqual(filas[reciente.pk].cliente, "Martina")
        self.assertIsNone(filas[reciente.pk].repartidor)

    def test_endpoint_ordenado_del_mas_antiguo(self):
        viejo = self.pedido_recorrido(hace_min=40)
        self.pedido_recorrido(hace_min=5)
        datos = self.client.get("/api/reportes/pedidos-activos/").json()
        self.assertEqual(datos[0]["pedido"], viejo.pk)


class VistaRendimientoTest(Sprint5Base):

    def test_entregas_y_promedios_por_repartidor(self):
        sofia = Repartidor.objects.create(nombre="Sofía")
        self.pedido_recorrido([2, 15, 3, 20], 120, repartidor=self.repartidor)   # 40, tarde
        self.pedido_recorrido([1, 12, 2, 6], 90, repartidor=self.repartidor)     # 21, a tiempo
        self.pedido_recorrido([1, 12, 2], 20, repartidor=self.repartidor)        # en camino

        lautaro = VistaRendimientoRepartidor.objects.get(repartidor=self.repartidor)
        self.assertEqual(lautaro.entregas, 2)
        self.assertEqual(lautaro.prom_min_viaje, Decimal("13.0"))
        self.assertEqual(lautaro.prom_min_total, Decimal("30.5"))
        self.assertEqual(lautaro.pct_a_tiempo, Decimal("50.0"))
        self.assertEqual(lautaro.facturacion, Decimal("19000.00"))

        sin_entregas = VistaRendimientoRepartidor.objects.get(repartidor=sofia)
        self.assertEqual(sin_entregas.entregas, 0)
        self.assertIsNone(sin_entregas.prom_min_total)

        datos = self.client.get("/api/reportes/rendimiento-repartidores/").json()
        self.assertEqual(datos[0]["nombre"], "Lautaro")


class VistaDemandaZonaTest(Sprint5Base):

    def test_pedidos_y_facturacion_por_zona(self):
        self.pedido_recorrido([1, 12, 2, 10], 60)
        self.pedido_recorrido(hace_min=5)                                  # pendiente
        self.pedido_recorrido([1, 12, 2, 20], 90, cliente=self.cliente_belgrano)

        palermo = VistaDemandaZona.objects.get(zona=self.palermo)
        self.assertEqual((palermo.pedidos, palermo.entregados), (2, 1))
        self.assertEqual(palermo.facturacion, Decimal("9500.00"), "solo cuenta lo entregado")
        self.assertEqual(palermo.prom_min_total, Decimal("25.0"))
        self.assertEqual(palermo.pct_a_tiempo, Decimal("100.0"))

        datos = self.client.get("/api/reportes/demanda-zona/").json()
        self.assertEqual([z["nombre"] for z in datos], ["Palermo", "Belgrano"])


class VistaProductosTest(Sprint5Base):

    def test_unidades_y_facturacion_por_producto(self):
        self.pedido_recorrido([1, 12, 2, 10], 60, items=[
            {"producto": self.empanada.pk, "cantidad": 6},
            {"producto": self.gaseosa.pk, "cantidad": 1}])
        self.pedido_recorrido(hace_min=5, items=[{"producto": self.empanada.pk, "cantidad": 3}])

        empanada = VistaProductoVendido.objects.get(producto=self.empanada)
        self.assertEqual((empanada.unidades, empanada.pedidos), (9, 2))
        self.assertEqual(empanada.facturacion, Decimal("13500.00"))
        self.assertEqual(empanada.prom_min_preparacion, Decimal("12.0"))
        sin_ventas = VistaProductoVendido.objects.get(producto=self.pizza)
        self.assertEqual((sin_ventas.unidades, sin_ventas.pedidos), (0, 0))

        datos = self.client.get("/api/reportes/productos-mas-vendidos/").json()
        self.assertEqual([p["nombre"] for p in datos][:2], ["Empanada", "Gaseosa"])

    def test_las_vistas_son_de_solo_lectura(self):
        self.pedido_recorrido(hace_min=5)
        with self.assertRaises(NotImplementedError):
            VistaProductoVendido.objects.first().save()


# ---------------------------------------------------------------------------
# Estadísticas
# ---------------------------------------------------------------------------

class EstadisticasTest(Sprint5Base):

    def test_resumen_del_periodo(self):
        self.pedido_recorrido([2, 15, 3, 20], 120, repartidor=self.repartidor)   # 40, tarde
        self.pedido_recorrido([1, 12, 2, 6], 90, repartidor=self.repartidor)     # 21, a tiempo
        self.pedido_recorrido(hace_min=40)                                       # pendiente
        services.revisar_demoras()

        r = self.client.get("/api/estadisticas/")
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertEqual((d["pedidos"], d["entregados"]), (3, 2))
        self.assertEqual(d["facturacion"], "19000.00")
        self.assertEqual(d["ticket_promedio"], "9500.00")
        self.assertEqual(d["pct_a_tiempo"], 50.0)
        self.assertEqual(d["alertas_de_demora"], 1)
        self.assertEqual(d["minutos_promedio"], {"espera": 1.5, "preparacion": 13.5,
                                                 "despacho": 2.5, "viaje": 13.0, "total": 30.5})
        self.assertEqual(sum(dia["pedidos"] for dia in d["por_dia"]), 3)

    def test_periodo_por_defecto_de_30_dias(self):
        d = self.client.get("/api/estadisticas/").json()
        hoy = timezone.localdate()
        self.assertEqual(d["hasta"], hoy.isoformat())
        self.assertEqual(d["desde"], (hoy - timedelta(days=29)).isoformat())

    def test_fuera_del_periodo_no_cuenta(self):
        self.pedido_recorrido([1, 12, 2, 10], 60)
        ayer = (timezone.localdate() - timedelta(days=1)).isoformat()
        d = self.client.get(f"/api/estadisticas/?desde={ayer}&hasta={ayer}").json()
        self.assertEqual(d["pedidos"], 0)
        self.assertIsNone(d["pct_a_tiempo"])
        self.assertIsNone(d["minutos_promedio"]["total"])
        self.assertEqual(d["por_dia"], [])

    def test_valida_las_fechas(self):
        self.assertEqual(self.client.get("/api/estadisticas/?desde=ayer").status_code, 400)
        r = self.client.get("/api/estadisticas/?desde=2026-11-10&hasta=2026-11-01")
        self.assertEqual(r.status_code, 400)

    def test_requiere_login(self):
        self.client.force_authenticate(None)
        for url in ("/api/estadisticas/", "/api/alertas/", "/api/reportes/demanda-zona/"):
            self.assertEqual(self.client.get(url).status_code, 401, url)
