"""
Helpers for in-app notifications (settings_app.Notification).
"""
from apps.settings_app.models import Notification


def notify_user(user, title, message, link=''):
    """Create a notification for a user. No-op if user is missing or not authenticated."""
    if not user or not getattr(user, 'is_authenticated', False):
        return
    Notification.create(user=user, title=title, message=message, link=link or '')


def notify_if_new_assignee(user, actor, title, message, link=''):
    """
    Notify an assignee, but not when they are the same as actor (e.g. creator assigned self).
    """
    if not user or not getattr(user, 'pk', None):
        return
    if actor and getattr(actor, 'pk', None) and user.pk == actor.pk:
        return
    notify_user(user, title, message, link)
