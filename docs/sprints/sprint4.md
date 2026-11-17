# Sprint 4 — Asignación inteligente y optimización

**Estado:** terminado · **Fecha de cierre:** 17/11/2026

## Objetivo

Que el sistema sugiera qué repartidor conviene para cada pedido según dónde está,
cuántos pedidos lleva y a qué zona va, y que el local pueda asignar con un clic.

## Qué se hizo

### Patrón Strategy (`asignacion.py`)
- `EstrategiaAsignacion` (clase abstracta) define el algoritmo general en `sugerir()`:
  filtra quién puede llevar el pedido, puntúa a cada candidato con `puntuar()` y los
  ordena (**menor puntaje = mejor**). Las subclases solo implementan `puntuar()`.
- `AsignacionPorCercaniaYCarga` es la estrategia del sistema:

  ```
  puntaje = distancia_km(repartidor → centro de la zona)
            + 2 × pedidos_activos
            − 1,5 si ya lleva otro pedido a esa misma zona
  ```

- La distancia se calcula con la **fórmula de Haversine** (`distancia_km`).
- Cambiar de criterio es escribir otra subclase y apuntar `ESTRATEGIA_POR_DEFECTO`
  a ella; las vistas y los servicios no cambian. Hay una prueba que lo demuestra
  con una estrategia alternativa.

### Ranking (`GET /api/pedidos/{id}/sugerencia/`)
- Devuelve los candidatos ordenados, cada uno con su **desglose**: puntaje, distancia,
  pedidos activos, capacidad y si ya va a esa zona. Así el encargado entiende por
  qué se sugiere a cada uno.
- Devuelve también los **descartados con el motivo**: no está disponible (en reparto
  o inactivo), capacidad completa o sin ubicación registrada.
- Solo participan repartidores **Disponibles**, por debajo de su `capacidad_max` y
  con ubicación conocida, como define el diseño.
- El pedido que se está evaluando no cuenta como carga de su repartidor actual, para
  que reasignar no lo penalice. Los pedidos entregados no cuentan.
- Desempate estable: a igual puntaje gana el más cercano, después por nombre.
- 409 si el pedido ya salió del local.

### Asignación automática (`POST /api/pedidos/{id}/asignar/`)
- `{"automatica": true}` asigna al primero del ranking; `{"repartidor": 3}` sigue
  siendo la asignación manual del Sprint 2. Mandar las dos cosas o ninguna da 400.
- Si nadie puede llevar el pedido, 409 con el motivo y el pedido queda sin cambios.
- Pasa por la misma validación de la asignación manual, con las filas bloqueadas,
  así que dos asignaciones simultáneas no superan la capacidad.

### Ubicación (`POST /api/repartidores/{id}/ubicacion/`)
- Registra latitud y longitud actuales (validando rangos y que vengan las dos).
- La puede enviar el encargado (o, más adelante, la app del repartidor): no requiere
  ser administrador.

### Disponibilidad (`POST /api/repartidores/{id}/disponibilidad/`)
- `DISPONIBLE` (empieza el turno) o `INACTIVO` (lo termina).
- **En reparto no se elige a mano**: lo maneja la máquina de estados del pedido.
- No se da de baja a alguien con pedidos asignados sin entregar (409): primero hay
  que entregarlos o reasignarlos.
- Alguien en reparto no vuelve a Disponible a mano: vuelve solo al entregar.

### Reglas que se cerraron en el CRUD de repartidores
- El **estado ya no se edita por `PATCH /api/repartidores/{id}/`** (400): se cambia solo
  por `/disponibilidad/`, para que nadie salte las reglas anteriores.
- No se puede **borrar** un repartidor con pedidos sin entregar (409). Para los que ya
  no trabajan conviene marcarlos inactivos en lugar de borrarlos, así sus pedidos
  entregados siguen contando para las estadísticas del Sprint 5.

## Endpoints nuevos

| Método | Ruta | Cuerpo | Permiso |
| --- | --- | --- | --- |
| GET | `/api/pedidos/{id}/sugerencia/` | — | Autenticado |
| POST | `/api/pedidos/{id}/asignar/` | `{"automatica": true}` | Autenticado |
| POST | `/api/repartidores/{id}/ubicacion/` | `{"latitud": -34.58, "longitud": -58.43}` | Autenticado |
| POST | `/api/repartidores/{id}/disponibilidad/` | `{"estado": "INACTIVO"}` | Autenticado |

## Pruebas

`python manage.py test daroth_app` → **89 pruebas, todas pasan** (61 anteriores y 28 nuevas).

Cubren: Haversine con distancias conocidas; el más cercano primero; el peso de la carga;
el bono por misma zona; que el pedido propio y los entregados no cuenten; los descartados
con su motivo; el 409 para un pedido que ya salió; el cambio de estrategia; que la clase
base sea abstracta; la asignación automática, su 409 y el reparto al llenarse la capacidad;
la validación del cuerpo de `/asignar/`; la ubicación (rangos, login y que un repartidor
sin ubicación entre al ranking al cargarla); y las reglas de disponibilidad, de edición
del estado y de borrado.

También se probó la sugerencia contra la base real con los datos de `cargar_datos`.

## Archivos nuevos o modificados

`asignacion.py` (nuevo), `services.py`, `serializers.py`, `views.py`,
`tests/test_sprint4.py`, `README.md`.

## Impacto en la documentación del TP

No hay cambios en el modelo de datos ni migraciones nuevas: la ubicación usa los campos
`latitud` y `longitud` que el repartidor ya tenía en el DER. El diagrama de clases UML
coincide con el diseño (`EstrategiaAsignacion` abstracta con `puntuar()` y
`AsignacionPorCercaniaYCarga` como implementación); conviene agregar el método `sugerir()`
de la clase base si no figura. Para la matriz de trazabilidad, este sprint implementa los
procesos de **sugerencia y asignación automática**, **actualización de ubicación** y
**cambio de disponibilidad** del DFD.
