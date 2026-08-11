#!/usr/bin/env sh
set -eu

echo "Checking for model changes without committed migrations..."
python manage.py makemigrations --check --dry-run --noinput

echo "Applying database migrations..."
python manage.py migrate --noinput

echo "Collecting static files..."
python manage.py collectstatic --noinput

