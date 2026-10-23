FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN python manage.py collectstatic --noinput \
    && useradd --create-home careslot
USER careslot

EXPOSE 8000
# Migrations run on start because Render's free plan has no pre-deploy hook (see README trade-offs).
CMD ["sh", "-c", "python manage.py migrate --noinput && exec gunicorn config.wsgi:application --bind 0.0.0.0:${PORT} --workers 2 --access-logfile -"]
