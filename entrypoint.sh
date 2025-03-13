#!/bin/sh

# Exit immediately if a command exits with a non-zero status
set -e

# Wait for the database to be ready (replace with proper health check if needed)
echo "Waiting for PostgreSQL to be available..."
while ! nc -z $PGHOST $PGPORT; do
  sleep 1
done

echo "Database is ready."

# Apply database migrations
echo "Applying migrations..."
python manage.py migrate


# Create a superuser if it doesn't exist
echo "Creating superuser..."
python manage.py shell <<EOF
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(username="admin").exists():
    User.objects.create_superuser("admin", "testuser@example.com", "adminpassword")
    print("Superuser created")
else:
    print("Superuser already exists")
EOF

# Collect static files
echo "Collecting static files..."
python manage.py collectstatic --noinput

# Start Gunicorn server
echo "Starting Gunicorn..."
exec gunicorn --bind 0.0.0.0:8000 voice_assistant_project.wsgi:application
