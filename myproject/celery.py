# myproject/celery.py
import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'myproject.settings')

app = Celery('myproject')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks(['accounts'])  # Explicitly include the 'accounts' app

@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')