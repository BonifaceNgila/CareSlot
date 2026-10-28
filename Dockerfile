FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN python manage.py collectstatic --noinput \
    && useradd --create-home careslot
USER careslot

EXPOSE 8080
# Cloud Run injects PORT. Migrations are not run here: the pipeline runs them once, before the new
# revision starts, so several instances booting together never race on them (see cloudbuild.yaml).
CMD ["sh", "-c", "exec gunicorn config.wsgi:application --bind 0.0.0.0:${PORT} --workers 2 --access-logfile -"]
