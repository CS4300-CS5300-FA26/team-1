import logging

from django.db import connections
from django.http import HttpResponse

logger = logging.getLogger(__name__)


class HealthCheckMiddleware:
    """Answer Kubernetes and load balancer health checks before host validation.

    Probes arrive with the pod IP as the Host header, which ALLOWED_HOSTS rejects,
    so this must be the first middleware and must never call request.get_host().

    /livez/   -> 200 if the process is serving requests (no DB access).
    /healthz/ -> 200 if the default database answers SELECT 1, else 503.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path_info == '/livez/':
            return HttpResponse('ok', content_type='text/plain')
        if request.path_info == '/healthz/':
            return self.readiness()
        return self.get_response(request)

    @staticmethod
    def readiness():
        try:
            with connections['default'].cursor() as cursor:
                cursor.execute('SELECT 1')
                cursor.fetchone()
        except Exception:
            logger.warning('Health check database query failed', exc_info=True)
            return HttpResponse('database unavailable', status=503, content_type='text/plain')
        return HttpResponse('ok', content_type='text/plain')
