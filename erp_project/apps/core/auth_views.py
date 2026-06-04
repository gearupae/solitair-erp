"""Authentication views."""
from django.contrib import messages
from django.contrib.auth.views import LoginView


class ERPLoginView(LoginView):
    """Clear stale flash messages from prior requests when login succeeds."""

    template_name = 'auth/login.html'

    def form_valid(self, form):
        # Discard old errors (e.g. failed PDF download, permission denied) so they
        # do not appear on the dashboard after login.
        list(messages.get_messages(self.request))
        return super().form_valid(form)
