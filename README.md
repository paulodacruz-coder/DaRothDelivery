# DaRoth Delivery

Sistema de gestión y optimización de entregas para restaurantes con servicio de delivery propio y una cantidad reducida de repartidores.

Trabajo Práctico — **Análisis y Metodología de Sistemas**
Integrantes: **Paulo Da Cruz** y **Aixa Rothar**

## Qué resuelve

Los restaurantes chicos asignan los pedidos "a ojo", no saben qué repartidor lleva cada uno ni cuánto falta para la entrega, y los clientes llaman para preguntar. DaRoth Delivery centraliza la administración de los pedidos, sugiere qué repartidor debería llevar cada uno según su ubicación y su carga, informa el estado al cliente mediante un enlace de seguimiento y registra los tiempos para poder analizar el desempeño.

## Tecnologías

- Python 3 y Django 4.2
- Django REST Framework
- drf-spectacular (documentación OpenAPI / Swagger)
- MariaDB / MySQL
- Arquitectura REST, modelo de datos gestionado con migraciones de Django

## Instalación

```bash
# 1. Clonar el repositorio y entrar a la carpeta
git clone https://github.com/paulodacruz-coder/DaRothDelivery.git
cd DaRothDelivery

# 2. Crear y activar el entorno virtual
python -m venv env
env\Scripts\activate        # Windows
source env/bin/activate     # Linux o Mac

# 3. Instalar las dependencias
pip install -r requirements.txt

# 4. Crear la base de datos
#    En MySQL/MariaDB: CREATE DATABASE daroth_delivery CHARACTER SET utf8mb4;

# 5. Configurar las variables de entorno
#    Copiar .env.example a .env y completar los valores

# 6. Crear las tablas y cargar los datos iniciales
python manage.py migrate
python manage.py cargar_datos          # --reset para borrar y volver a cargar

# 7. Levantar el servidor
python manage.py runserver

# Pruebas automáticas
python manage.py test daroth_app
```

La API queda disponible en `http://127.0.0.1:8000/api/`, su documentación interactiva en
`/docs/` (Swagger) y `/redoc/`, y el panel de administración en `/admin/`.

Usuarios de prueba (contraseña `daroth123`): `paulo` y `aixa` son administradores;
`marcos`, `julieta`, `federico`, `camila`, `nicolas`, `rocio`, `diego` y `valeria` son encargados.

## API

Todos los endpoints exigen autenticación con el encabezado `Authorization: Token <token>`,
que se obtiene en el login. La única excepción es el seguimiento público.

| Método | Ruta | Descripción |
| --- | --- | --- |
| POST | `/api/auth/login/` | Recibe `username` y `password`, devuelve el token y el rol |
| POST | `/api/auth/logout/` | Invalida el token |
| GET | `/api/auth/yo/` | Usuario autenticado |
| CRUD | `/api/zonas/`, `/api/productos/`, `/api/repartidores/` | Catálogo (solo el administrador modifica) |
| CRUD | `/api/clientes/` | Clientes (`?q=` busca por nombre o teléfono) |
| CRUD | `/api/pedidos/` | Pedidos (`?estado=`, `?zona=`, `?repartidor=`, `?activos=1`) |
| POST | `/api/pedidos/{id}/estado/` | Avanza al estado siguiente: `{"estado": "PREPARANDO"}` |
| GET | `/api/pedidos/{id}/historial/` | Historial de estados del pedido |
| POST | `/api/pedidos/{id}/asignar/` | Asignación manual: `{"repartidor": 3}` |
| POST | `/api/pedidos/{id}/desasignar/` | Quita el repartidor |
| GET | `/api/dashboard/` | Pedidos activos, carga de repartidores y números del día |
| GET | `/api/seguimiento/{token}/` | **Público.** Estado, historial y minutos restantes del pedido |

Los estados avanzan en orden (Pendiente → Preparando → Listo → En camino → Entregado),
sin saltear ni retroceder, y no se despacha un pedido sin repartidor. Una operación que no
corresponde al estado actual responde **409 Conflict**.

Cada pedido trae un `enlace_seguimiento` para mandarle al cliente. Esa página no pide login,
muestra solo el estado y el tiempo restante (ningún dato interno) y admite hasta 30
consultas por minuto por IP.

Alta de un pedido: el total, la zona, el tiempo estimado y el token de seguimiento los calcula el sistema.

```json
POST /api/pedidos/
{ "cliente": 1, "items": [ { "producto": 3, "cantidad": 2 } ] }
```

## Variables de entorno

| Variable | Descripción |
| --- | --- |
| `SECRET_KEY` | Clave secreta de Django |
| `DEBUG` | `True` en desarrollo, `False` en producción |
| `DB_NAME` | Nombre de la base de datos |
| `DB_USER` | Usuario de la base de datos |
| `DB_PASSWORD` | Contraseña del usuario |
| `DB_HOST` | Host del servidor (por defecto `127.0.0.1`) |
| `DB_PORT` | Puerto del servidor (por defecto `3306`) |

## Estructura

```
DaRothDelivery/
├── manage.py
├── requirements.txt
├── .env.example       Plantilla de variables de entorno
└── daroth_app/        Proyecto y aplicación Django
    ├── settings.py, urls.py, wsgi.py, asgi.py
    ├── models.py      Modelo de datos (DER)
    ├── services.py    Reglas de negocio
    ├── serializers.py, views.py, permissions.py
    ├── admin.py
    ├── migrations/
    ├── management/commands/cargar_datos.py
    └── tests/         Pruebas automáticas, un archivo por sprint
```

## Estado del proyecto

El desarrollo está organizado en cinco sprints de una semana:

| Sprint | Alcance | Estado |
| --- | --- | --- |
| 1 | Base del sistema y persistencia | Terminado |
| 2 | Estados del pedido y asignación de repartidores | Terminado |
| 3 | Seguimiento del pedido para el cliente | Terminado |
| 4 | Asignación inteligente y optimización | Pendiente |
| 5 | Estadísticas y reportes | Pendiente |

## Documentación

En la carpeta `docs/` se encuentran el diagrama de contexto, el diagrama de flujo de datos de nivel 1, el diagrama entidad-relación, el diagrama de clases y el documento completo del trabajo práctico.
