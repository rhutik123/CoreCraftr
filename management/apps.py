from django.apps import AppConfig
from django.db.models.signals import post_migrate


def _sync_portal_roles(sender, **kwargs):
    from management.permissions import ensure_portal_roles

    try:
        ensure_portal_roles()
    except Exception:
        # Ignore before initial contenttypes/auth tables exist.
        pass


class ManagementConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'management'
    verbose_name = 'Owner & Inventory Management Portal'

    def ready(self):
        post_migrate.connect(_sync_portal_roles, sender=self)
