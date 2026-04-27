# Desarrollo local: API sin necesidad de venv en el host
FROM python:3.10-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DJANGO_SETTINGS_MODULE=config.settings

WORKDIR /app

# psycopg2-binary incluye dependencias de cliente; en slim suele alcanzar
COPY requirements/base.txt /app/requirements/base.txt
RUN pip install --upgrade pip && pip install -r /app/requirements/base.txt

COPY docker/entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

COPY . /app

EXPOSE 8000
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
