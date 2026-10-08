from django.core.management.base import BaseCommand
from daroth_app.models import Zona, Producto


class Command(BaseCommand):
    help = "Carga los datos iniciales del sistema"

    def handle(self, *args, **options):
        Zona.objects.create(nombre="Centro", latitud_centro=-34.6037,
                            longitud_centro=-58.3816, tiempo_viaje_min=15)
        Zona.objects.create(nombre="Palermo", latitud_centro=-34.5889,
                            longitud_centro=-58.4306, tiempo_viaje_min=20)
        # ... el resto

        self.stdout.write(self.style.SUCCESS("Datos cargados"))