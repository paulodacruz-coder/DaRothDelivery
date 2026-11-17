"""
Asignación inteligente de repartidores (patrón Strategy).

`EstrategiaAsignacion` define el algoritmo general: filtrar quiénes pueden llevar
el pedido, puntuar a cada candidato y ordenarlos (menor puntaje = mejor).
Cada estrategia concreta solo decide cómo se puntúa, en `puntuar()`. Para probar
otro criterio (por ejemplo, priorizar bicicletas en zonas cercanas) alcanza con
escribir otra subclase, sin tocar las vistas ni el resto de la lógica.

La estrategia actual es `AsignacionPorCercaniaYCarga`:

    puntaje = distancia_km(repartidor → centro de la zona)
              + 2 × pedidos_activos
              − 1.5 si ya lleva otro pedido a esa misma zona
"""
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from django.db.models import Count, Q

from .models import EstadoPedido, Repartidor

RADIO_TIERRA_KM = 6371.0


def distancia_km(lat1, lon1, lat2, lon2):
    """Distancia en línea recta entre dos puntos de la Tierra (fórmula de Haversine)."""
    lat1, lon1, lat2, lon2 = map(math.radians, map(float, (lat1, lon1, lat2, lon2)))
    a = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 2 * RADIO_TIERRA_KM * math.asin(math.sqrt(a))


@dataclass
class Candidato:
    """Un repartidor evaluado para un pedido, con el detalle de su puntaje."""
    repartidor: Repartidor
    distancia_km: float
    pedidos_activos: int
    misma_zona: bool
    puntaje: float = 0.0
    posicion: int = 0


@dataclass
class Descartado:
    repartidor: Repartidor
    motivo: str


@dataclass
class Sugerencia:
    estrategia: "EstrategiaAsignacion"
    ranking: list = field(default_factory=list)      # Candidatos, el mejor primero
    descartados: list = field(default_factory=list)  # Repartidores que no participan

    @property
    def mejor(self):
        return self.ranking[0] if self.ranking else None


class EstrategiaAsignacion(ABC):
    """Algoritmo general de sugerencia. Las subclases implementan `puntuar`."""

    nombre = "abstracta"
    criterio = ""

    @abstractmethod
    def puntuar(self, pedido, candidato):
        """Devuelve el puntaje del candidato para el pedido. Menor puntaje = mejor."""

    def sugerir(self, pedido):
        """Ranking de repartidores para el pedido y motivo de cada descarte."""
        sugerencia = Sugerencia(estrategia=self)
        for repartidor in self._repartidores_con_carga(pedido):
            motivo = self._motivo_de_descarte(repartidor)
            if motivo:
                sugerencia.descartados.append(Descartado(repartidor, motivo))
                continue
            candidato = Candidato(
                repartidor=repartidor,
                distancia_km=distancia_km(repartidor.latitud, repartidor.longitud,
                                          pedido.zona.latitud_centro,
                                          pedido.zona.longitud_centro),
                pedidos_activos=repartidor.carga,
                misma_zona=repartidor.carga_en_zona > 0,
            )
            candidato.puntaje = self.puntuar(pedido, candidato)
            sugerencia.ranking.append(candidato)

        # Desempate estable: primero el más cercano, después por nombre.
        sugerencia.ranking.sort(key=lambda c: (c.puntaje, c.distancia_km,
                                               c.repartidor.nombre, c.repartidor.pk))
        for posicion, candidato in enumerate(sugerencia.ranking, start=1):
            candidato.posicion = posicion
        return sugerencia

    def _repartidores_con_carga(self, pedido):
        """
        Todos los repartidores, anotados con su carga actual. El pedido que se está
        asignando no cuenta: si ya lo tiene asignado, reasignárselo no lo penaliza.
        """
        activos = (~Q(pedidos__estado=EstadoPedido.ENTREGADO) & ~Q(pedidos__pk=pedido.pk))
        return (Repartidor.objects
                .annotate(carga=Count("pedidos", filter=activos),
                          carga_en_zona=Count("pedidos",
                                              filter=activos & Q(pedidos__zona=pedido.zona_id)))
                .order_by("nombre", "pk"))

    def _motivo_de_descarte(self, repartidor):
        """Solo participan repartidores disponibles, con lugar y con ubicación conocida."""
        if repartidor.estado != Repartidor.Estado.DISPONIBLE:
            return f"No está disponible ({repartidor.get_estado_display().lower()})."
        if repartidor.carga >= repartidor.capacidad_max:
            return f"Capacidad completa ({repartidor.carga}/{repartidor.capacidad_max})."
        if repartidor.latitud is None or repartidor.longitud is None:
            return "No tiene ubicación registrada."
        return None


class AsignacionPorCercaniaYCarga(EstrategiaAsignacion):
    """Prioriza al que está más cerca y menos cargado, y agrupa pedidos de la misma zona."""

    nombre = "cercania_y_carga"
    criterio = ("distancia en km a la zona + 2 por cada pedido activo "
                "− 1,5 si ya lleva otro pedido a la misma zona (menor = mejor)")
    PESO_CARGA = 2.0
    BONO_MISMA_ZONA = 1.5

    def puntuar(self, pedido, candidato):
        puntaje = candidato.distancia_km + self.PESO_CARGA * candidato.pedidos_activos
        if candidato.misma_zona:
            puntaje -= self.BONO_MISMA_ZONA
        return puntaje


# Estrategia que usa el sistema. Cambiar de criterio es cambiar esta línea.
ESTRATEGIA_POR_DEFECTO = AsignacionPorCercaniaYCarga
