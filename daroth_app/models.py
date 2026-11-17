import secrets

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

class EstadoPedido(models.TextChoices):
    PENDIENTE = "PENDIENTE", "Pendiente"
    PREPARANDO = "PREPARANDO", "Preparando"
    LISTO = "LISTO", "Listo"
    EN_CAMINO = "EN_CAMINO", "En camino"
    ENTREGADO = "ENTREGADO", "Entregado"

class Zona(models.Model):
    nombre = models.CharField(max_length=80, unique=True)
    latitud_centro = models.DecimalField(max_digits=9, decimal_places=6)
    longitud_centro = models.DecimalField(max_digits=9, decimal_places=6)
    tiempo_viaje_min = models.PositiveSmallIntegerField(
        help_text="Minutos estimados de viaje hasta esta zona"
    )

    class Meta:
        verbose_name = "Zona"
        verbose_name_plural = "Zonas"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre
    
class Producto(models.Model):
    nombre = models.CharField(max_length=100, unique=True)
    precio = models.DecimalField(max_digits=12, decimal_places=2)
    tiempo_preparacion_min = models.PositiveSmallIntegerField()

    class Meta:
        verbose_name = "Producto"
        verbose_name_plural = "Productos"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre

class Cliente(models.Model):
    nombre = models.CharField(max_length=100)
    telefono = models.CharField(max_length=30, blank=True)
    direccion = models.CharField(max_length=200)
    zona = models.ForeignKey(Zona, on_delete=models.PROTECT, related_name="clientes")

    class Meta:
        verbose_name = "Cliente"
        verbose_name_plural = "Clientes"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre

class Repartidor(models.Model):
    class Estado(models.TextChoices):
        DISPONIBLE = "DISPONIBLE", "Disponible"
        EN_REPARTO = "EN_REPARTO", "En reparto"
        INACTIVO = "INACTIVO", "Inactivo"

    nombre = models.CharField(max_length=100)
    telefono = models.CharField(max_length=30, blank=True)
    vehiculo = models.CharField(max_length=30, default="moto")
    estado = models.CharField(max_length=20, choices=Estado.choices, default=Estado.DISPONIBLE)
    capacidad_max = models.PositiveSmallIntegerField(default=3)
    latitud = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitud = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    class Meta:
        verbose_name = "Repartidor"
        verbose_name_plural = "Repartidores"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre
    
class Pedido(models.Model):
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name="pedidos")
    zona = models.ForeignKey(Zona, on_delete=models.PROTECT, related_name="pedidos")
    repartidor = models.ForeignKey(Repartidor, on_delete=models.SET_NULL, null=True, blank=True, related_name="pedidos")
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    direccion_entrega = models.CharField(max_length=200)
    estado = models.CharField(max_length=20, choices=EstadoPedido.choices, default=EstadoPedido.PENDIENTE)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    token_seguimiento = models.CharField(max_length=32, unique=True, editable=False)
    tiempo_estimado_min = models.PositiveSmallIntegerField()
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_entrega = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Pedido"
        verbose_name_plural = "Pedidos"
        ordering = ["fecha_creacion"]

    def __str__(self):
        return f"Pedido #{self.pk} - {self.cliente.nombre}"

    def save(self, *args, **kwargs):
        # El token se genera una sola vez, al crear el pedido.
        if not self.token_seguimiento:
            self.token_seguimiento = generar_token_unico()
        super().save(*args, **kwargs)


def generar_token_unico():
    """Devuelve un token hexadecimal de 32 caracteres que no esté en uso."""
    while True:
        token = secrets.token_hex(16)
        if not Pedido.objects.filter(token_seguimiento=token).exists():
            return token

class DetallePedido(models.Model):
    pedido = models.ForeignKey(Pedido, on_delete=models.CASCADE, related_name="detalles")
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT)
    cantidad = models.PositiveSmallIntegerField(validators=[MinValueValidator(1)])
    precio_unitario = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        verbose_name = "Detalle de pedido"
        verbose_name_plural = "Detalles de pedido"
        ordering = ["pedido"]
        constraints = [models.UniqueConstraint(fields=["pedido", "producto"], name="uq_detalle_pedido_producto")]

    def __str__(self):
        return f"Pedido #{self.pedido_id} - {self.producto.nombre}"

class HistorialEstado(models.Model):
    pedido = models.ForeignKey(Pedido, on_delete=models.CASCADE, related_name="historial")
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    estado = models.CharField(max_length=20, choices=EstadoPedido.choices)
    fecha_hora = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Historial de estado"
        verbose_name_plural = "Historial de estados"
        ordering = ["pedido", "fecha_hora"]

    def __str__(self):
        return f"Pedido #{self.pedido_id} - {self.get_estado_display()}"

class Alerta(models.Model):
    pedido = models.ForeignKey(Pedido, on_delete=models.CASCADE, related_name="alertas")
    tipo = models.CharField(max_length=30)
    mensaje = models.CharField(max_length=255)
    fecha_hora = models.DateTimeField(auto_now_add=True)
    resuelta = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Alerta"
        verbose_name_plural = "Alertas"
        ordering = ["pedido"]

    def __str__(self):
        return f"Pedido #{self.pedido_id} - {self.mensaje}"

class Perfil(models.Model):
    class Rol(models.TextChoices):
        ADMINISTRADOR = "ADMINISTRADOR", "Administrador"
        ENCARGADO = "ENCARGADO", "Encargado"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    rol = models.CharField(max_length=20, choices=Rol.choices)

    class Meta:
        verbose_name = "Perfil"
        verbose_name_plural = "Perfiles"
        ordering = ["rol"]

    def __str__(self):
        return f"{self.user.username} ({self.get_rol_display()})"

# ---------------------------------------------------------------------------
# Vistas SQL de reportes (Sprint 5)
# ---------------------------------------------------------------------------
# Las crea la migración 0003 con SQL crudo. Estos modelos no son tablas
# (managed = False): sirven para leer las vistas con el ORM. Son de solo lectura.

class VistaReporte(models.Model):
    class Meta:
        abstract = True
        managed = False

    def save(self, *args, **kwargs):
        raise NotImplementedError("Las vistas de reportes son de solo lectura.")

    def delete(self, *args, **kwargs):
        raise NotImplementedError("Las vistas de reportes son de solo lectura.")


class VistaPedidoActivo(VistaReporte):
    """v_pedidos_activos: pedidos sin entregar, con cuánto llevan y si tienen alerta."""
    pedido = models.OneToOneField(Pedido, primary_key=True, on_delete=models.DO_NOTHING,
                                  db_column="pedido_id", related_name="+")
    estado = models.CharField(max_length=20, choices=EstadoPedido.choices)
    cliente = models.CharField(max_length=100)
    zona = models.CharField(max_length=80)
    repartidor = models.CharField(max_length=100, null=True)
    direccion_entrega = models.CharField(max_length=200)
    total = models.DecimalField(max_digits=12, decimal_places=2)
    tiempo_estimado_min = models.IntegerField()
    fecha_creacion = models.DateTimeField()
    min_transcurridos = models.IntegerField()
    min_excedidos = models.IntegerField()
    alerta_pendiente = models.BooleanField()

    class Meta(VistaReporte.Meta):
        db_table = "v_pedidos_activos"


class VistaTiemposPedido(VistaReporte):
    """
    v_tiempos_pedido: minutos de cada etapa de cada pedido, a partir del historial.
    Es la base de las estadísticas y de las tres vistas siguientes.
    """
    pedido = models.OneToOneField(Pedido, primary_key=True, on_delete=models.DO_NOTHING,
                                  db_column="pedido_id", related_name="+")
    zona = models.ForeignKey(Zona, on_delete=models.DO_NOTHING, related_name="+")
    repartidor = models.ForeignKey(Repartidor, null=True, on_delete=models.DO_NOTHING,
                                   related_name="+")
    estado = models.CharField(max_length=20, choices=EstadoPedido.choices)
    total = models.DecimalField(max_digits=12, decimal_places=2)
    tiempo_estimado_min = models.IntegerField()
    fecha_creacion = models.DateTimeField()
    fecha_entrega = models.DateTimeField(null=True)
    min_espera = models.IntegerField(null=True, help_text="Creación → Preparando")
    min_preparacion = models.IntegerField(null=True, help_text="Preparando → Listo")
    min_despacho = models.IntegerField(null=True, help_text="Listo → En camino")
    min_viaje = models.IntegerField(null=True, help_text="En camino → Entregado")
    min_total = models.IntegerField(null=True, help_text="Creación → Entregado")
    a_tiempo = models.BooleanField(
        null=True, help_text="Entregado dentro del tiempo estimado + 10 min de tolerancia")

    class Meta(VistaReporte.Meta):
        db_table = "v_tiempos_pedido"


class VistaRendimientoRepartidor(VistaReporte):
    """v_rendimiento_repartidores: entregas y tiempos de cada repartidor."""
    repartidor = models.OneToOneField(Repartidor, primary_key=True, on_delete=models.DO_NOTHING,
                                      db_column="repartidor_id", related_name="+")
    nombre = models.CharField(max_length=100)
    vehiculo = models.CharField(max_length=30)
    estado = models.CharField(max_length=20, choices=Repartidor.Estado.choices)
    entregas = models.IntegerField()
    prom_min_viaje = models.DecimalField(max_digits=8, decimal_places=1, null=True)
    prom_min_total = models.DecimalField(max_digits=8, decimal_places=1, null=True)
    pct_a_tiempo = models.DecimalField(max_digits=5, decimal_places=1, null=True)
    facturacion = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta(VistaReporte.Meta):
        db_table = "v_rendimiento_repartidores"


class VistaDemandaZona(VistaReporte):
    """v_demanda_zona: pedidos, facturación y tiempos por zona."""
    zona = models.OneToOneField(Zona, primary_key=True, on_delete=models.DO_NOTHING,
                                db_column="zona_id", related_name="+")
    nombre = models.CharField(max_length=80)
    tiempo_viaje_min = models.IntegerField()
    pedidos = models.IntegerField()
    entregados = models.IntegerField()
    facturacion = models.DecimalField(max_digits=14, decimal_places=2)
    ticket_promedio = models.DecimalField(max_digits=12, decimal_places=2, null=True)
    prom_min_total = models.DecimalField(max_digits=8, decimal_places=1, null=True)
    pct_a_tiempo = models.DecimalField(max_digits=5, decimal_places=1, null=True)

    class Meta(VistaReporte.Meta):
        db_table = "v_demanda_zona"


class VistaProductoVendido(VistaReporte):
    """v_productos_mas_vendidos: unidades, pedidos y facturación por producto."""
    producto = models.OneToOneField(Producto, primary_key=True, on_delete=models.DO_NOTHING,
                                    db_column="producto_id", related_name="+")
    nombre = models.CharField(max_length=100)
    unidades = models.IntegerField()
    pedidos = models.IntegerField()
    facturacion = models.DecimalField(max_digits=14, decimal_places=2)
    prom_min_preparacion = models.DecimalField(max_digits=8, decimal_places=1, null=True,
                                               help_text="De los pedidos que lo incluyen")

    class Meta(VistaReporte.Meta):
        db_table = "v_productos_mas_vendidos"
