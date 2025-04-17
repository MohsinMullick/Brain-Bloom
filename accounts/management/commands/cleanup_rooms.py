from django.core.management.base import BaseCommand
from accounts.models import Room
from django.utils import timezone

class Command(BaseCommand):
    help = 'Deletes expired rooms'

    def handle(self, *args, **options):
        rooms = Room.objects.all()  # Check all rooms, not just past dates
        for room in rooms:
            if room.is_expired():
                self.stdout.write(self.style.SUCCESS(f'Deleting expired room: {room.title}'))
                room.delete()
        self.stdout.write(self.style.SUCCESS('Cleanup completed.'))