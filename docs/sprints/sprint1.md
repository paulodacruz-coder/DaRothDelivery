# Sprint 1 — Base del sistema y persistencia

**Estado:** terminado · **Fecha de cierre:** 16/11/2026

## Objetivo

Dejar el proyecto funcionando de punta a punta: base de datos, modelo de datos
del DER, datos de prueba, autenticación y endpoints CRUD básicos.

## Qué se hizo

### Entorno y configuración
- Entorno virtual `env/` con Python 3.13 y las dependencias de `requirements.txt`
  (Django 4.2.30, DRF 3.17.2, mysqlclient 2.3.0).
- Base `daroth_delivery` en MariaDB 10.4.32 (`utf8mb4`).
- `.env.example` versionado como plantilla, sin secretos.
- Bloque `REST_FRAMEWORK` en `settings.py`: autenticación por token y por sesión,
  `IsAuthenticated` por defecto y paginación de 25 resultados.

### Modelo de datos
- Corregidos los `__str__` de `Pedido`, `HistorialEstado` y `Perfil`, que lanzaban
  `AttributeError` / `TypeError` o devolvían datos poco útiles.
- `Pedido.save()` genera un `token_seguimiento` único de 32 caracteres al crearse.
- Migración `0002_quitar_unique_nombres_y_ajustes`: quita el `unique` de
  `Cliente.nombre` y `Repartidor.nombre`, porque dos personas pueden llamarse igual,
  y ajusta nombres legibles y el orden del historial.
- Se mantiene `Pedido.repartidor` como FK nulleable, tal como está en el DER entregado.

### Reglas de negocio (`services.py`)
- `calcular_tiempo_estimado`: el producto que más tarda en prepararse más el
  tiempo de viaje a la zona.
- `crear_pedido`: crea el pedido, sus detalles con el precio congelado y el primer
  registro de historial (`PENDIENTE`) en una sola transacción.

### Datos de prueba (`cargar_datos [--reset]`)
10 zonas de CABA, 12 productos, 10 repartidores, 12 clientes, 10 usuarios con perfil,
18 pedidos (10 entregados, 2 en camino, 2 listos, 2 en preparación, 2 pendientes),
34 detalles, 70 registros de historial y 5 alertas de demora (3 resueltas y 2 pendientes).
Las fechas son relativas a `timezone.now()` y se fijan con `update()` para esquivar
`auto_now_add`.

### API
| Método | Ruta | Permiso |
| --- | --- | --- |
| POST | `/api/auth/login/` | Público |
| POST | `/api/auth/logout/` | Autenticado |
| GET | `/api/auth/yo/` | Autenticado |
| CRUD | `/api/zonas/`, `/api/productos/`, `/api/repartidores/` | Lectura: autenticado · Escritura: administrador |
| CRUD | `/api/clientes/` | Autenticado |
| CRUD | `/api/pedidos/` | Autenticado |

Reglas de los pedidos:
- El servidor calcula el total, la zona, el tiempo estimado, el token y el precio
  unitario; lo que mande el cliente de la API en esos campos se ignora.
- No se aceptan productos repetidos, pedidos vacíos ni cantidades menores a 1 (400).
- Solo se modifica la dirección, y solo mientras el pedido no salió del local (409 si salió).
- Solo se borran pedidos `PENDIENTE` (409 en otro caso).
- Borrar una zona, un producto o un cliente que está en uso devuelve 409, no un error 500.

### Panel de administración
Todos los modelos registrados. El pedido muestra sus detalles y su historial en línea.

## Pruebas

`python manage.py test daroth_app` → **21 pruebas, todas pasan.**

Cubren: los `__str__`, la unicidad del token, el cálculo del tiempo estimado, el login
correcto e incorrecto, el logout, el 401 sin autenticar, los permisos por rol, el 409 al
borrar datos en uso, el alta de pedidos con todos sus cálculos, el precio congelado,
las validaciones, los filtros, la edición y el borrado según el estado, y que
`cargar_datos` genere los conteos esperados.

## Archivos nuevos o modificados

`models.py`, `migrations/0002_*.py`, `services.py`, `serializers.py`, `views.py`,
`permissions.py`, `excepciones.py`, `urls.py`, `admin.py`, `settings.py`,
`management/commands/cargar_datos.py`, `tests/`, `.env.example`, `README.md`.

## Impacto en la documentación del TP

No hay cambios en el DER ni en el DFD: el modelo respeta el diseño entregado.
