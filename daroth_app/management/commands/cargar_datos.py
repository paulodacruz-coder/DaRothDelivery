"""
Carga los datos de prueba del sistema.

    python manage.py cargar_datos           # falla si ya hay datos
    python manage.py cargar_datos --reset   # borra los datos de prueba y los vuelve a cargar

Todas las fechas se calculan relativas a timezone.now(), para que los pedidos
activos tengan minutos transcurridos coherentes y nunca queden en el futuro.
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from daroth_app.models import (
    Alerta, Cliente, DetallePedido, EstadoPedido, HistorialEstado, Pedido,
    Perfil, Producto, Repartidor, Zona,
)
from daroth_app.services import (
    ESTADOS_DEL_REPARTIDOR, ORDEN_ESTADOS, TIPO_DEMORA, crear_pedido, limite_de_demora,
    mensaje_de_demora,
)

CONTRASENA = "daroth123"

# (nombre, latitud, longitud, tiempo de viaje en minutos)
ZONAS = [
    ("Almagro", "-34.609200", "-58.421300", 12),
    ("Balvanera", "-34.609000", "-58.403000", 15),
    ("Belgrano", "-34.562700", "-58.458300", 20),
    ("Caballito", "-34.618600", "-58.441900", 15),
    ("Colegiales", "-34.574400", "-58.449700", 18),
    ("Núñez", "-34.545000", "-58.463000", 25),
    ("Palermo", "-34.588900", "-58.430600", 10),
    ("Recoleta", "-34.587500", "-58.397400", 14),
    ("San Nicolás", "-34.603700", "-58.381600", 20),
    ("Villa Crespo", "-34.599000", "-58.438900", 8),
]

# (nombre, precio, tiempo de preparación en minutos)
PRODUCTOS = [
    ("Pizza muzzarella", "9500", 15),
    ("Pizza napolitana", "10500", 15),
    ("Fugazzeta", "10000", 15),
    ("Empanada de carne", "1500", 10),
    ("Empanada de jamón y queso", "1500", 10),
    ("Milanesa napolitana con papas", "12000", 20),
    ("Hamburguesa completa", "9000", 12),
    ("Papas fritas", "4500", 8),
    ("Ensalada César", "7500", 7),
    ("Lomito completo", "13000", 18),
    ("Flan con dulce de leche", "3500", 2),
    ("Gaseosa 1.5 L", "3000", 1),
]

# (nombre, teléfono, vehículo, capacidad, latitud, longitud, estado)
D, R, I = (Repartidor.Estado.DISPONIBLE, Repartidor.Estado.EN_REPARTO,
           Repartidor.Estado.INACTIVO)
REPARTIDORES = [
    ("Lautaro Benítez", "11-4521-3301", "moto", 3, "-34.590100", "-58.428000", D),
    ("Ezequiel Romero", "11-4521-3302", "moto", 3, "-34.600500", "-58.437200", D),
    ("Gonzalo Vera", "11-4521-3303", "bicicleta", 2, "-34.610000", "-58.420000", D),
    ("Micaela Torres", "11-4521-3304", "moto", 3, "-34.586000", "-58.400000", D),
    ("Santiago Ojeda", "11-4521-3305", "moto", 4, "-34.565000", "-58.455000", D),
    ("Brenda Molina", "11-4521-3306", "bicicleta", 2, "-34.576000", "-58.447000", D),
    ("Franco Medina", "11-4521-3307", "moto", 3, "-34.605000", "-58.385000", D),
    ("Leandro Sosa", "11-4521-3308", "moto", 3, "-34.552000", "-58.460000", R),
    ("Daniela Ruiz", "11-4521-3309", "moto", 3, "-34.598000", "-58.440000", R),
    ("Hernán Godoy", "11-4521-3310", "auto", 5, None, None, I),
]

# (nombre, teléfono, dirección, zona)
CLIENTES = [
    ("Martina López", "11-5000-0001", "Av. Santa Fe 3450", "Palermo"),
    ("Javier Gómez", "11-5000-0002", "Malabia 845", "Villa Crespo"),
    ("Lucía Fernández", "11-5000-0003", "Av. Corrientes 4120", "Almagro"),
    ("Tomás Herrera", "11-5000-0004", "Av. Rivadavia 5200", "Caballito"),
    ("Sofía Ramírez", "11-5000-0005", "Av. Las Heras 2100", "Recoleta"),
    ("Mateo Castro", "11-5000-0006", "Av. Cabildo 1850", "Belgrano"),
    ("Florencia Díaz", "11-5000-0007", "Federico Lacroze 2300", "Colegiales"),
    ("Agustín Morales", "", "Av. Pueyrredón 450", "Balvanera"),
    ("Carla Suárez", "11-5000-0009", "Lavalle 1200", "San Nicolás"),
    ("Ignacio Pereyra", "11-5000-0010", "Av. del Libertador 7300", "Núñez"),
    ("Valentina Ríos", "11-5000-0011", "Gurruchaga 1550", "Palermo"),
    ("Bruno Acosta", "", "Thames 620", "Villa Crespo"),
]

# (usuario, nombre, apellido, rol)
A, E = Perfil.Rol.ADMINISTRADOR, Perfil.Rol.ENCARGADO
USUARIOS = [
    ("paulo", "Paulo", "Da Cruz", A),
    ("aixa", "Aixa", "Rothar", A),
    ("marcos", "Marcos", "Paz", E),
    ("julieta", "Julieta", "Correa", E),
    ("federico", "Federico", "Luna", E),
    ("camila", "Camila", "Ibarra", E),
    ("nicolas", "Nicolás", "Quiroga", E),
    ("rocio", "Rocío", "Maldonado", E),
    ("diego", "Diego", "Villalba", E),
    ("valeria", "Valeria", "Aguirre", E),
]

# Pedidos. Cada uno:
#   cliente, usuario, items [(producto, cantidad)], estado final,
#   creado hace (minutos), duraciones de cada transición (minutos), repartidor
# Las duraciones son: PENDIENTE→PREPARANDO, →LISTO, →EN_CAMINO, →ENTREGADO
# (solo las que corresponden al estado final).
DIA = 24 * 60
ENT, CAM, LIS, PRE, PEN = (EstadoPedido.ENTREGADO, EstadoPedido.EN_CAMINO,
                           EstadoPedido.LISTO, EstadoPedido.PREPARANDO,
                           EstadoPedido.PENDIENTE)
PEDIDOS = [
    # --- Entregados (10) ---
    ("Martina López", "marcos", [("Pizza muzzarella", 1), ("Gaseosa 1.5 L", 1)],
     ENT, 6 * DIA + 120, [3, 14, 4, 9], "Lautaro Benítez"),
    ("Javier Gómez", "julieta", [("Empanada de carne", 6), ("Empanada de jamón y queso", 6)],
     ENT, 6 * DIA + 60, [2, 11, 3, 7], "Ezequiel Romero"),
    ("Lucía Fernández", "federico", [("Milanesa napolitana con papas", 2), ("Papas fritas", 1)],
     ENT, 5 * DIA + 90, [4, 22, 9, 15], "Gonzalo Vera"),                 # demorado
    ("Tomás Herrera", "camila", [("Hamburguesa completa", 2)],
     ENT, 4 * DIA + 150, [2, 13, 4, 14], "Lautaro Benítez"),
    ("Sofía Ramírez", "marcos", [("Fugazzeta", 1), ("Flan con dulce de leche", 2)],
     ENT, 4 * DIA + 45, [3, 16, 5, 13], "Micaela Torres"),
    ("Mateo Castro", "nicolas", [("Lomito completo", 2), ("Gaseosa 1.5 L", 1)],
     ENT, 3 * DIA + 100, [5, 20, 12, 24], "Santiago Ojeda"),             # demorado
    ("Florencia Díaz", "rocio", [("Pizza napolitana", 1), ("Empanada de carne", 3)],
     ENT, 2 * DIA + 130, [2, 15, 4, 17], "Brenda Molina"),
    ("Agustín Morales", "diego", [("Ensalada César", 2), ("Gaseosa 1.5 L", 1)],
     ENT, 2 * DIA + 40, [2, 8, 3, 14], "Ezequiel Romero"),
    ("Carla Suárez", "valeria", [("Milanesa napolitana con papas", 1)],
     ENT, 1 * DIA + 80, [6, 24, 10, 22], "Franco Medina"),               # demorado
    ("Valentina Ríos", "julieta", [("Hamburguesa completa", 1), ("Papas fritas", 1)],
     ENT, 1 * DIA + 20, [2, 12, 3, 8], "Gonzalo Vera"),
    # --- En camino (2) ---
    ("Ignacio Pereyra", "marcos", [("Pizza muzzarella", 2), ("Gaseosa 1.5 L", 1)],
     CAM, 65, [4, 18, 8], "Leandro Sosa"),                               # demorado
    ("Bruno Acosta", "camila", [("Empanada de jamón y queso", 6), ("Flan con dulce de leche", 1)],
     CAM, 22, [2, 10, 3], "Daniela Ruiz"),
    # --- Listos (2) ---
    ("Martina López", "federico", [("Lomito completo", 1), ("Papas fritas", 1)],
     LIS, 25, [3, 19], None),
    ("Sofía Ramírez", "nicolas", [("Pizza napolitana", 1), ("Gaseosa 1.5 L", 1)],
     LIS, 48, [5, 18], "Micaela Torres"),                                # demorado
    # --- En preparación (2) ---
    ("Tomás Herrera", "rocio", [("Milanesa napolitana con papas", 1), ("Ensalada César", 1)],
     PRE, 12, [3], None),
    ("Florencia Díaz", "diego", [("Hamburguesa completa", 2), ("Papas fritas", 2)],
     PRE, 8, [2], None),
    # --- Pendientes (2) ---
    ("Lucía Fernández", "valeria", [("Fugazzeta", 1), ("Empanada de carne", 2)],
     PEN, 3, [], None),
    ("Mateo Castro", "aixa", [("Pizza muzzarella", 1), ("Flan con dulce de leche", 1)],
     PEN, 1, [], None),
]



def fijar_fecha(modelo, pk, **campos):
    """Escribe fechas con update(), que no dispara auto_now_add."""
    modelo.objects.filter(pk=pk).update(**campos)


class Command(BaseCommand):
    help = "Carga los datos de prueba del sistema (zonas, productos, usuarios, pedidos, etc.)"

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true",
                            help="Borra los datos existentes antes de cargar.")

    @transaction.atomic
    def handle(self, *args, **options):
        if options["reset"]:
            self.borrar_datos()
        elif Zona.objects.exists() or Pedido.objects.exists():
            raise CommandError("Ya hay datos cargados. Usá --reset para borrarlos y volver a cargar.")

        ahora = timezone.now()
        zonas = self.cargar_zonas()
        productos = self.cargar_productos()
        repartidores = self.cargar_repartidores()
        clientes = self.cargar_clientes(zonas)
        usuarios = self.cargar_usuarios()
        self.cargar_pedidos(ahora, productos, repartidores, clientes, usuarios)

        self.stdout.write(self.style.SUCCESS("Datos cargados:"))
        for modelo in (Zona, Producto, Repartidor, Cliente, User, Pedido,
                       DetallePedido, HistorialEstado, Alerta):
            self.stdout.write(f"  {modelo._meta.verbose_name_plural}: {modelo.objects.count()}")

    def borrar_datos(self):
        # Orden inverso a las dependencias (las FK con PROTECT no dejan borrar antes).
        for modelo in (Alerta, HistorialEstado, DetallePedido, Pedido, Cliente,
                       Repartidor, Producto, Zona, Perfil):
            modelo.objects.all().delete()
        User.objects.filter(username__in=[u[0] for u in USUARIOS]).delete()
        self.stdout.write("Datos anteriores borrados.")

    def cargar_zonas(self):
        return {
            nombre: Zona.objects.create(nombre=nombre, latitud_centro=Decimal(lat),
                                        longitud_centro=Decimal(lon), tiempo_viaje_min=viaje)
            for nombre, lat, lon, viaje in ZONAS
        }

    def cargar_productos(self):
        return {
            nombre: Producto.objects.create(nombre=nombre, precio=Decimal(precio),
                                            tiempo_preparacion_min=prep)
            for nombre, precio, prep in PRODUCTOS
        }

    def cargar_repartidores(self):
        return {
            nombre: Repartidor.objects.create(
                nombre=nombre, telefono=tel, vehiculo=vehiculo, capacidad_max=capacidad,
                latitud=Decimal(lat) if lat else None, longitud=Decimal(lon) if lon else None,
                estado=estado)
            for nombre, tel, vehiculo, capacidad, lat, lon, estado in REPARTIDORES
        }

    def cargar_clientes(self, zonas):
        return {
            nombre: Cliente.objects.create(nombre=nombre, telefono=tel, direccion=direccion,
                                           zona=zonas[zona])
            for nombre, tel, direccion, zona in CLIENTES
        }

    def cargar_usuarios(self):
        usuarios = {}
        for username, nombre, apellido, rol in USUARIOS:
            es_admin = rol == Perfil.Rol.ADMINISTRADOR
            usuario = User.objects.create_user(
                username=username, password=CONTRASENA, first_name=nombre, last_name=apellido,
                email=f"{username}@daroth.local", is_staff=es_admin, is_superuser=es_admin)
            Perfil.objects.create(user=usuario, rol=rol)
            usuarios[username] = usuario
        return usuarios

    def cargar_pedidos(self, ahora, productos, repartidores, clientes, usuarios):
        for cliente, username, items, estado_final, hace_min, duraciones, repartidor in PEDIDOS:
            usuario = usuarios[username]
            pedido = crear_pedido(
                cliente=clientes[cliente], usuario=usuario,
                items=[(productos[nombre], cantidad) for nombre, cantidad in items])

            # Recorre los estados hasta el final, fijando la fecha de cada uno.
            momento = ahora - timedelta(minutes=hace_min)
            fecha_creacion = momento
            fijar_fecha(Pedido, pedido.pk, fecha_creacion=fecha_creacion)
            fijar_fecha(HistorialEstado, pedido.historial.get().pk, fecha_hora=momento)

            estados = ORDEN_ESTADOS[1:ORDEN_ESTADOS.index(estado_final) + 1]
            for estado, minutos in zip(estados, duraciones):
                momento += timedelta(minutes=minutos)
                registro = HistorialEstado.objects.create(
                    pedido=pedido, estado=estado,
                    usuario=None if estado in ESTADOS_DEL_REPARTIDOR else usuario)
                fijar_fecha(HistorialEstado, registro.pk, fecha_hora=momento)

            Pedido.objects.filter(pk=pedido.pk).update(
                estado=estado_final,
                repartidor=repartidores[repartidor] if repartidor else None,
                fecha_entrega=momento if estado_final == ENT else None,
            )

            self.cargar_alerta_si_corresponde(pedido, estado_final, fecha_creacion, momento, ahora)

    def cargar_alerta_si_corresponde(self, pedido, estado_final, fecha_creacion, fin, ahora):
        """Misma regla que services.revisar_demoras, pero con las fechas históricas."""
        pedido.fecha_creacion = fecha_creacion
        limite = limite_de_demora(pedido)
        entregado = estado_final == ENT
        referencia = fin if entregado else ahora
        if referencia <= limite:
            return
        alerta = Alerta.objects.create(pedido=pedido, tipo=TIPO_DEMORA, resuelta=entregado,
                                       mensaje=mensaje_de_demora(pedido))
        fijar_fecha(Alerta, alerta.pk, fecha_hora=limite)
