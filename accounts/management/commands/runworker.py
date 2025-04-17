from django.core.management.base import BaseCommand
from celery import Celery

class Command(BaseCommand):
    help = 'Run Celery worker'

    def handle(self, *args, **options):
        app = Celery('myproject')
        app.config_from_object('django.conf:settings', namespace='CELERY')
        app.worker_main(['worker', '--loglevel=info', '--pool=solo', '--queues=default'])