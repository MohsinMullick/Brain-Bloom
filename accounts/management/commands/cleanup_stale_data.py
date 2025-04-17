# accounts/management/commands/cleanup_stale_data.py
from django.core.management.base import BaseCommand
from accounts.models import User, StudyPartnerRequest

class Command(BaseCommand):
    help = 'Cleans up stale references to deleted users'

    def handle(self, *args, **options):
        # Find study partner requests with non-existent users
        requests = StudyPartnerRequest.objects.all()
        for req in requests:
            try:
                req.sender
                req.receiver
            except User.DoesNotExist:
                self.stdout.write(self.style.WARNING(f"Deleting study partner request {req.id} with missing user"))
                req.delete()