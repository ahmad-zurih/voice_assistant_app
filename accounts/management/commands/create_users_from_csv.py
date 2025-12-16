from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
import csv

class Command(BaseCommand):
    help = "Create users from a CSV file (no headers, just username,password)"

    def add_arguments(self, parser):
        parser.add_argument("csv_file", type=str, help="Path to CSV file")

    def handle(self, *args, **options):
        csv_file = options["csv_file"]
        with open(csv_file, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            for row in reader:
                if len(row) < 2:
                    continue
                username, password = row[0].strip(), row[1].strip()
                if User.objects.filter(username=username).exists():
                    self.stdout.write(self.style.WARNING(f"User {username} already exists"))
                    continue
                User.objects.create_user(username=username, password=password)
                self.stdout.write(self.style.SUCCESS(f"Created {username}"))
