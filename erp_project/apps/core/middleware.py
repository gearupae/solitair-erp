"""
Core middleware for the ERP system.
"""
import threading
from django.utils.deprecation import MiddlewareMixin

# Thread local storage for current user
_thread_locals = threading.local()


def get_current_user():
    """Get the current user from thread local storage."""
    return getattr(_thread_locals, 'user', None)


def get_current_request():
    """Get the current request from thread local storage."""
    return getattr(_thread_locals, 'request', None)


class AuditMiddleware(MiddlewareMixin):
    """
    Middleware to store the current user and request in thread local storage.
    This allows models to automatically track created_by and updated_by.
    """
    
    def process_request(self, request):
        _thread_locals.user = getattr(request, 'user', None)
        _thread_locals.request = request
    
    def process_response(self, request, response):
        # Clean up thread local storage
        if hasattr(_thread_locals, 'user'):
            del _thread_locals.user
        if hasattr(_thread_locals, 'request'):
            del _thread_locals.request
        return response





