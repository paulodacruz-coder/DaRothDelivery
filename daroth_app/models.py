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
    nombre = models.CharField(max_length=100, unique=True)
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

    nombre = models.CharField(max_length=100, unique=True)
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
        return self.estado

class DetallePedido(models.Model):
    pedido = models.ForeignKey(Pedido, on_delete=models.CASCADE, related_name="detalles")
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT)
    cantidad = models.PositiveSmallIntegerField(validators=[MinValueValidator(1)])
    precio_unitario = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        verbose_name = "DetallePedido"
        verbose_name_plural = "DetallePedidos"
        ordering = ["pedido"]
        constraints = [models.UniqueConstraint(fields=["pedido", "producto"], name="uq_detalle_pedido_producto")]

    def __str__(self):
        return self.pedido

class HistorialEstado(models.Model):
    pedido = models.ForeignKey(Pedido, on_delete=models.CASCADE, related_name="historial")
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    estado = models.CharField(max_length=20, choices=EstadoPedido.choices)
    fecha_hora = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "HistorialEstado"
        verbose_name_plural = "HistorialEstados"
        ordering = ["pedido"]

    def __str__(self):
        return self.pedido

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
        return self.pedido

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
        return self.user