# 3.12 har fler manylinux-wheels än 3.14 (Coolify bygger linux/amd64).
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PYTHONUNBUFFERED=1
# web | worker | beat | ais — Coolifys start_command på Dockerfile-pack
# skriver ibland över CMD felaktigt, så rollen styrs via env i stället.
ENV APP_ROLE=web
EXPOSE 8000
# Coolify/produktion. Lokalt: docker-compose eller manage.py runserver.
CMD ["sh", "-c", "case \"$APP_ROLE\" in worker) exec celery -A config worker -l info --concurrency=2;; beat) exec celery -A config beat -l info;; ais) exec python manage.py run_ais_stream;; *) exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 2 --timeout 120;; esac"]
