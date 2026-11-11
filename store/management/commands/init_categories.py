from django.core.management.base import BaseCommand

from store.services.category_init import initialize_starter_categories


class Command(BaseCommand):
    help = (
        'Initialize essential CoreCraftr hardware categories idempotently without '
        'creating demo products or overwriting existing owner-edited categories.'
    )

    def handle(self, *args, **options):
        result = initialize_starter_categories(overwrite_existing=False)
        created = result['created']
        skipped = result['skipped']
        total = result['total_categories']

        if created:
            self.stdout.write(
                self.style.SUCCESS(
                    f'Created {created} starter category(ies): {", ".join(result["created_names"])}.'
                )
            )
        else:
            self.stdout.write('No missing starter categories to create.')

        self.stdout.write(
            f'Skipped {skipped} existing category(ies) (owner edits preserved). '
            f'Total categories in database: {total}.'
        )
