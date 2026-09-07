"""
Celery-app. Ersätter (för de tasks som är portade dit, se core/tasks.py och
billing/tasks.py) run_pipeline.pys egen loop -- den kommandofilen finns kvar
oförändrad som en beroendefri reservväg, se dess docstring.
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("taxitips")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
