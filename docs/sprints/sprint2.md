# Sprint 2 — Estados del pedido, historial, asignación manual y dashboard

**Estado:** terminado · **Fecha de cierre:** 16/11/2026

## Objetivo

Que el local pueda llevar cada pedido desde que entra hasta que se entrega,
asignarle un repartidor a mano y ver de un vistazo cómo está la operación.

## Qué se hizo

### Máquina de estados (`services.cambiar_estado`)
`Pendiente → Preparando → Listo → En camino → Entregado`

- Solo se avanza al estado **inmediatamente siguiente**: no se saltea ni se retrocede.
- No se puede pasar a **En camino** sin repartidor asignado.
- Un pedido **Entregado** no admite más cambios.
- Cada cambio queda en `HistorialEstado`. Preparando y Listo llevan el usuario que hizo
  el cambio; En camino y Entregado van con `usuario = NULL`, porque los registra el repartidor.
- Al entregar, se completa `fecha_entrega`.
- El repartidor acompaña al pedido: pasa a **En reparto** cuando sale con un pedido y
  vuelve a **Disponible** cuando entrega el último que tenía en camino.
- El endpoint recibe el **estado destino explícito**, no un "avanzar": así un doble clic
  no hace avanzar el pedido dos veces, porque el segundo intento da 409.
- La fila del pedido se bloquea (`select_for_update`) durante el cambio, para que dos
  pedidos simultáneos no se pisen.

### Asignación manual (`services.asignar_repartidor` / `desasignar_repartidor`)
- Se asigna, se reasigna o se quita el repartidor **mientras el pedido está en el local**
  (Pendiente, Preparando o Listo).
- No se asignan repartidores **inactivos**.
- Se respeta la `capacidad_max`: cuentan como carga los pedidos asignados que no
  están entregados.
- Reasignar al mismo repartidor no cuenta dos veces para la capacidad.

### Errores de negocio → 409
`services.py` lanza `ReglaDeNegocioError` y un manejador de excepciones de DRF
(`excepciones.manejar_excepciones`) la convierte en **409 Conflict** con un mensaje claro.
Los datos mal formados (un estado que no existe, un repartidor inexistente) siguen dando 400.

### Dashboard (`GET /api/dashboard/`)
- Cantidad de pedidos activos por estado y en total.
- Cuántos pedidos activos no tienen repartidor.
- Alertas pendientes.
- Números del día: pedidos entregados y facturación.
- Lista de pedidos activos, **del más antiguo al más nuevo** (los urgentes primero),
  con los minutos transcurridos y el estado siguiente.
- Repartidores activos con su carga actual (`pedidos_activos / capacidad_max`).

### Otros
- `siguiente_estado` en la respuesta del pedido, para que el frontend sepa qué botón mostrar.
- Filtro `?activos=1` en el listado de pedidos.
- `cargar_datos` usa las mismas constantes de estados que `services.py`.

## Endpoints nuevos

| Método | Ruta | Cuerpo |
| --- | --- | --- |
| POST | `/api/pedidos/{id}/estado/` | `{"estado": "PREPARANDO"}` |
| GET | `/api/pedidos/{id}/historial/` | — |
| POST | `/api/pedidos/{id}/asignar/` | `{"repartidor": 3}` |
| POST | `/api/pedidos/{id}/desasignar/` | — |
| GET | `/api/dashboard/` | — |

## Pruebas

`python manage.py test daroth_app` → **42 pruebas, todas pasan** (21 del Sprint 1 y 21 nuevas).

Cubren: el recorrido completo de estados y su historial; el 409 al saltear, retroceder,
repetir (doble clic), despachar sin repartidor y tocar un pedido entregado; el 400 para un
estado inexistente; el usuario que queda registrado en cada estado; el estado del repartidor
al salir y al entregar, incluso cuando le quedan otros pedidos en camino; asignar, reasignar
y desasignar; el repartidor inactivo; la capacidad máxima, sin contar los entregados ni la
reasignación al mismo; el cambio de repartidor de un pedido en camino; y el contenido del
dashboard.

También se probó contra el servidor real con los datos de `cargar_datos`.

## Archivos modificados

`services.py`, `excepciones.py`, `serializers.py`, `views.py`, `urls.py`, `settings.py`,
`management/commands/cargar_datos.py`, `tests/test_sprint2.py`, `README.md`.

## Impacto en la documentación del TP

No hay cambios en el modelo de datos ni migraciones nuevas. La máquina de estados y el
409 son los que ya estaban definidos en el diseño. Para la matriz de trazabilidad,
este sprint implementa los procesos de **cambio de estado**, **asignación manual** y
**consulta del tablero** del DFD.
