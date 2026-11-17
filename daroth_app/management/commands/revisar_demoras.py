"""
Genera las alertas de demora pendientes.

    python manage.py revisar_demoras

La API ya las genera al consultar /api/alertas/ y /api/dashboard/. Este comando
sirve para que aparezcan aunque nadie esté mirando, programándolo cada minuto con
el Programador de tareas de Windows (o cron en Linux).
"""
from django.core.management.base import BaseCommand

from daroth_app.services import revisar_demoras


class Command(BaseCommand):
    help = "Genera una alerta por cada pedido activo que superó su tiempo estimado + tolerancia."

    def handle(self, *args, **options):
        nuevas = revisar_demoras()
        for alerta in nuevas:
            self.stdout.write(f"  Pedido #{alerta.pedido_id}: {alerta.mensaje}")
        self.stdout.write(self.style.SUCCESS(f"Alertas nuevas: {len(nuevas)}"))
