#!/bin/sh

# Stop script if any command fails
set -e

echo "Applying database migrations..."
python manage.py migrate

echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Starting Gunicorn..."
# This binds the app to the port Render provides
exec gunicorn GeoMemories.wsgi:application --bind 0.0.0.0:$PORT