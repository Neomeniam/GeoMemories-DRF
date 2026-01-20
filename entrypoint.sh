#!/bin/sh

# Stop on error
set -e

echo "Applying database migrations..."
python manage.py migrate

echo "Collecting static files..."
# We only strictly need this on the cloud, but running it locally doesn't hurt
python manage.py collectstatic --noinput

# SMART STARTUP
# If PORT is set (Cloud/Render), use Gunicorn.
# If PORT is NOT set (Localhost), use Django Dev Server (0.0.0.0:8000).
if [ -n "$PORT" ]; then
    echo "Starting Gunicorn (Production)..."
    exec gunicorn GeoMemories.wsgi:application --bind 0.0.0.0:$PORT
else
    echo "Starting Django Dev Server (Local)..."
    exec python manage.py runserver 0.0.0.0:8000
fi