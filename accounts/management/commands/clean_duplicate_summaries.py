# accounts/management/commands/clean_duplicate_summaries.py
from django.core.management.base import BaseCommand
from accounts.models import Summary

class Command(BaseCommand):
    help = 'Cleans up duplicate summaries in the database'

    def handle(self, *args, **kwargs):
        # Group summaries by room and pdf_name
        summaries = Summary.objects.all().order_by('room', 'pdf_name', 'timestamp')
        seen = {}
        duplicates = []

        for summary in summaries:
            key = (summary.room.id, summary.pdf_name)
            if key in seen:
                duplicates.append(summary)
            else:
                seen[key] = summary

        # Delete duplicates, keeping the most recent one
        for duplicate in duplicates:
            self.stdout.write(self.style.WARNING(f"Deleting duplicate summary: {duplicate.pdf_name} in room {duplicate.room.id}"))
            duplicate.delete()

        self.stdout.write(self.style.SUCCESS(f"Deleted {len(duplicates)} duplicate summaries"))