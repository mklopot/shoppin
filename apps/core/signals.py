"""
Django signals for the core application.

Enforces content moderation and profanity filtering on content models
before saving to the database.
"""

from django.db.models.signals import pre_save
from django.dispatch import receiver

from apps.core.services.moderation_service import check_model_instance_for_moderation


@receiver(pre_save)
def enforce_content_moderation_on_save(sender, instance, **kwargs):
    """
    Pre-save receiver intercepting model saves across the application to ensure
    created and updated content contains no expletives, obscenity, slurs, or hurtful language.
    """
    check_model_instance_for_moderation(instance)
