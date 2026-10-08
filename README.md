# DaRoth Delivery

Sistema de gestión y optimización de entregas para restaurantes con servicio de delivery propio y una cantidad reducida de repartidores.

Trabajo Práctico — **Análisis y Metodología de Sistemas**
Integrantes: **Paulo Da Cruz** y **Aixa Rothar**

## Qué resuelve

Los restaurantes chicos asignan los pedidos "a ojo", no saben qué repartidor lleva cada uno ni cuánto falta para la entrega, y los clientes llaman para preguntar. DaRoth Delivery centraliza la administración de los pedidos, sugiere qué repartidor debería llevar cada uno según su ubicación y su carga, informa el estado al cliente mediante un enlace de seguimiento y registra los tiempos para poder analizar el desempeño.

## Tecnologías

- Python 3 y Django 4.2
- Django REST Framework
- MariaDB / MySQL
- Arquitectura REST, modelo de datos gestionado con migraciones de Django

## Instalación

```bash
# 1. Clonar el repositorio y entrar a la carpeta
git clone https://github.com/<usuario>/daroth-delivery.git
cd daroth-delivery

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
python manage.py cargar_datos

# 7. Levantar el servidor
python manage.py runserver
```

La API queda disponible en `http://127.0.0.1:8000/api/`.

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
daroth-delivery/
├── manage.py
├── requirements.txt
├── database/          Configuración del proyecto (settings, urls)
├── daroth_app/        Modelos, serializers, vistas y endpoints
└── docs/              DER, diagramas y documentación del trabajo
```

## Estado del proyecto

El desarrollo está organizado en cinco sprints de una semana:

| Sprint | Alcance | Estado |
| --- | --- | --- |
| 1 | Base del sistema y persistencia | En curso |
| 2 | Estados del pedido y asignación de repartidores | Pendiente |
| 3 | Seguimiento del pedido para el cliente | Pendiente |
| 4 | Asignación inteligente y optimización | Pendiente |
| 5 | Estadísticas y reportes | Pendiente |

## Documentación

En la carpeta `docs/` se encuentran el diagrama de contexto, el diagrama de flujo de datos de nivel 1, el diagrama entidad-relación, el diagrama de clases y el documento completo del trabajo práctico.
