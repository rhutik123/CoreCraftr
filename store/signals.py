from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Customer


@receiver(post_save, sender=User)
def ensure_customer_profile(sender, instance, created, **kwargs):
    """Ensure every User always has a corresponding Customer profile."""
    if created:
        Customer.objects.get_or_create(
            user=instance,
            defaults={
                'name': instance.get_full_name() or instance.username,
                'email': instance.email or '',
            },
        )
