# Sprint 3 — Seguimiento del pedido para el cliente

**Estado:** terminado · **Fecha de cierre:** 17/11/2026

## Objetivo

Que el cliente pueda ver cómo va su pedido y cuánto falta, sin registrarse y
sin llamar al local, y dejar la API documentada.

## Qué se hizo

### Seguimiento público (`GET /api/seguimiento/{token}/`)
- Es el **único endpoint sin login**: el cliente no tiene cuenta. El `token_seguimiento`
  de 32 caracteres hexadecimales (generado al crear el pedido desde el Sprint 1)
  funciona como contraseña del pedido.
- Respuesta **reducida** (`SeguimientoSerializer`): estado, historial, hora estimada
  de entrega, minutos restantes y si ya se entregó. No incluye ids, nombre, teléfono
  o dirección del cliente, zona, montos ni el usuario del local que hizo cada cambio.
- Un token inexistente da **404**, sin distinguir otros motivos. Solo acepta GET.
- No usa autenticación: un header `Authorization` vencido no provoca un 401.
- **Límite de 30 consultas por minuto por IP** (`ScopedRateThrottle`, alcance
  `seguimiento`), para que no se puedan probar tokens al azar. Al superarlo, 429.

### Enlace de seguimiento
El pedido interno trae `enlace_seguimiento`, la URL completa que el local le manda
al cliente (por WhatsApp, SMS, etc.).

### Tiempo estimado de entrega (`services.estimar_entrega` / `minutos_restantes`)
El tiempo estimado del alta (producto más lento + viaje a la zona) es lo que se le
promete al cliente. Durante el seguimiento la hora estimada se recalcula según la etapa:

| Estado | Hora estimada de entrega |
| --- | --- |
| Pendiente, Preparando, Listo | creación + tiempo estimado, pero nunca antes de *ahora + viaje a la zona* |
| En camino | hora de salida (del historial) + viaje a la zona |
| Entregado | no aplica (`null`) |

Así, si la cocina se atrasa, el cliente no ve "0 minutos" con el pedido todavía en el
local. Los minutos restantes se redondean hacia arriba y nunca dan negativo.
El dashboard también muestra `minutos_restantes` en cada pedido activo.

### Documentación de la API (`/docs/`)
- **drf-spectacular** genera el esquema OpenAPI 3 a partir del código.
- `/docs/` (Swagger UI, permite probar los endpoints con el botón *Authorize*),
  `/redoc/` (lectura) y `/api/schema/` (esquema en YAML/JSON).
- Se agregaron tipos a los campos calculados y descripciones a las vistas que no
  tienen serializer (logout, usuario actual, dashboard), y se documentan las
  respuestas 409. El esquema se genera **sin errores ni advertencias**
  (`python manage.py spectacular --validate`).

## Endpoints nuevos

| Método | Ruta | Permiso |
| --- | --- | --- |
| GET | `/api/seguimiento/{token}/` | Público (con límite de consultas) |
| GET | `/docs/`, `/redoc/`, `/api/schema/` | Público |

## Pruebas

`python manage.py test daroth_app` → **61 pruebas, todas pasan** (42 anteriores y 19 nuevas).

Cubren: el acceso sin login y con un token vencido en el header; el 404 para tokens
inexistentes; que la respuesta no contenga datos internos; el historial en orden; el
pedido entregado; que solo se acepte GET; el 429 al superar el límite; el enlace en el
pedido; la estimación recién tomado, con el tiempo corriendo, con la cocina atrasada,
en camino y en camino demorado; el redondeo; los minutos restantes en el dashboard; y
que `/docs/`, `/redoc/` y el esquema respondan e incluyan todos los endpoints.

También se probó contra la base real con los datos de `cargar_datos`.

## Archivos modificados

`services.py`, `serializers.py`, `views.py`, `urls.py`, `settings.py`,
`tests/test_sprint3.py`, `requirements.txt`, `README.md`.

## Impacto en la documentación del TP

No hay cambios en el modelo de datos ni migraciones nuevas. Para la matriz de
trazabilidad, este sprint implementa el proceso de **consulta de seguimiento** del DFD
(el cliente como entidad externa que consulta con el token) y el **cálculo del tiempo
estimado**. Si el diseño de la API del documento no incluía `/docs/`, conviene sumarlo.
