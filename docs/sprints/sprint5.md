# Sprint 5 — Alertas, reportes y estadísticas

**Estado:** terminado (backend) · **Fecha de cierre:** 17/11/2026

## Objetivo

Que el local se entere a tiempo de los pedidos que se están demorando y pueda
analizar su desempeño: tiempos de cada etapa, rendimiento de los repartidores,
demanda por zona y productos más vendidos.

## Qué se hizo

### Alertas de demora (`services.revisar_demoras`)
- Se genera una alerta `DEMORA` cuando un pedido activo supera su
  `tiempo_estimado_min` **más 10 minutos de tolerancia** (`TOLERANCIA_DEMORA_MIN`).
- **Solo una por pedido**: si ya tiene una alerta pendiente, no se crea otra.
  Las filas se bloquean durante la revisión para que dos consultas simultáneas no
  dupliquen alertas.
- **Se resuelven solas al entregar** el pedido (dentro de `cambiar_estado`).
- Como no hay un proceso en segundo plano, las demoras se revisan **al consultar
  `/api/alertas/` y `/api/dashboard/`**. Además está el comando
  `python manage.py revisar_demoras`, para programarlo cada minuto con el
  Programador de tareas de Windows y que las alertas aparezcan aunque nadie mire.
- `cargar_datos` usa las mismas funciones (`limite_de_demora`, `mensaje_de_demora`),
  así que los datos de prueba siguen exactamente la misma regla.

### Las 5 vistas SQL (migración `0003_vistas_de_reportes`, SQL crudo)

| Vista | Qué muestra | Se apoya en |
| --- | --- | --- |
| `v_tiempos_pedido` | Minutos de cada etapa de cada pedido (espera, preparación, despacho, viaje, total) y si llegó a tiempo, a partir de `HistorialEstado` | — (es la base) |
| `v_pedidos_activos` | Pedidos sin entregar con cliente, zona, repartidor, minutos transcurridos, minutos excedidos y si tiene alerta pendiente | — |
| `v_rendimiento_repartidores` | Entregas, tiempo promedio de viaje y total, % a tiempo y facturación de cada repartidor | `v_tiempos_pedido` |
| `v_demanda_zona` | Pedidos, entregados, facturación, ticket promedio, tiempo promedio y % a tiempo por zona | `v_tiempos_pedido` |
| `v_productos_mas_vendidos` | Unidades, pedidos, facturación y tiempo promedio de preparación de los pedidos que incluyen cada producto | `v_tiempos_pedido` |

Decisiones técnicas:
- **"A tiempo" = dentro del estimado + 10 min de tolerancia**, la misma regla que
  dispara las alertas. Así "demorado" significa lo mismo en todo el sistema.
- Las fechas se guardan en UTC, por eso `v_pedidos_activos` compara contra
  `UTC_TIMESTAMP()` y no contra `NOW()` (que daría 3 horas de diferencia).
- `tiempo_estimado_min` es `UNSIGNED` en MariaDB: se convierte a `SIGNED` antes de
  restar, porque si no la resta negativa desborda.
- Se evitaron las subconsultas en el `FROM` (tablas derivadas) para que las vistas
  funcionen en MariaDB 10.4.
- La migración se puede revertir (`migrate daroth_app 0002` borra las vistas).
- Cada vista tiene un modelo de solo lectura (`managed = False`) en `models.py`, para
  leerla con el ORM. Intentar guardar o borrar lanza un error.

### Estadísticas (`GET /api/estadisticas/`)
Resumen de un período (`?desde=2026-11-01&hasta=2026-11-17`, por defecto los últimos
30 días): pedidos, entregados, facturación, ticket promedio, % a tiempo, alertas de
demora, minutos promedio de cada etapa y evolución por día. Se calcula sobre
`v_tiempos_pedido`. La agrupación por día se hace en Python porque el MariaDB de XAMPP
no trae las tablas de zonas horarias y agrupar por fecha local en SQL daría NULL.

## Endpoints nuevos

| Método | Ruta | Descripción |
| --- | --- | --- |
| GET | `/api/alertas/` | Alertas, las más recientes primero (`?resuelta=0`, `?pedido=`) |
| GET | `/api/estadisticas/` | Resumen del período (`?desde=`, `?hasta=`) |
| GET | `/api/reportes/pedidos-activos/` | `v_pedidos_activos` |
| GET | `/api/reportes/tiempos-pedido/` | `v_tiempos_pedido` (paginado, `?estado=`) |
| GET | `/api/reportes/rendimiento-repartidores/` | `v_rendimiento_repartidores` |
| GET | `/api/reportes/demanda-zona/` | `v_demanda_zona` |
| GET | `/api/reportes/productos-mas-vendidos/` | `v_productos_mas_vendidos` |

Todos exigen estar autenticado. Las alertas y los reportes son de solo lectura.

## Pruebas

`python manage.py test daroth_app` → **115 pruebas, todas pasan** (89 anteriores y 26 nuevas).

Cubren: la generación de alertas justo al pasar el límite y no antes; la tolerancia según
el tiempo estimado de cada pedido; que no se dupliquen; que los entregados no generen
alertas; que se resuelvan al entregar; el listado, sus filtros y que sea de solo lectura;
el dashboard; el comando `revisar_demoras`; los minutos de cada etapa en
`v_tiempos_pedido` y el límite exacto de "a tiempo"; `v_pedidos_activos` (incluida la
comparación en UTC); los promedios y porcentajes de rendimiento por repartidor, demanda
por zona y productos; las estadísticas del período, el período por defecto, el filtro de
fechas y su validación; y que todo exija login.

Las pruebas corren sobre MariaDB, así que las vistas se crean y consultan de verdad.
También se probaron todos los endpoints contra la base real con los datos de `cargar_datos`.

## Archivos nuevos o modificados

`migrations/0003_vistas_de_reportes.py` (nuevo), `management/commands/revisar_demoras.py`
(nuevo), `models.py`, `services.py`, `serializers.py`, `views.py`, `urls.py`,
`management/commands/cargar_datos.py`, `tests/test_sprint5.py`, `README.md`.

## Pendiente

El **frontend** figuraba como tentativo y no se hizo en este sprint: el backend queda
completo y documentado en `/docs/` para conectarle una interfaz.

## Impacto en la documentación del TP

- **DER:** las 5 vistas no son tablas nuevas, pero conviene listarlas como objetos de
  la base (vistas de reportes) junto al DER, con la tabla de arriba.
- **Definición de "a tiempo":** dejar escrito que es estimado + 10 min de tolerancia,
  la misma regla que las alertas.
- **Matriz de trazabilidad:** este sprint implementa los procesos de **detección de
  demoras / alertas** y **consulta de reportes y estadísticas** del DFD. La entidad
  `Alerta` pasa a tener su flujo completo (se crea al demorarse y se resuelve al entregar).
