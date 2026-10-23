import os

from django.db import connection
from django.http import JsonResponse


class HealthCheckMiddleware:
    """Answers /health before host validation: platform probes may not send the public Host header.

    Reports the deployed commit so the CI pipeline can confirm that a deploy actually went live.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.rstrip("/") != "/health":
            return self.get_response(request)
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
        except Exception:
            return JsonResponse({"status": "error", "database": "unreachable"}, status=503)
        return JsonResponse({"status": "ok", "commit": os.environ.get("RENDER_GIT_COMMIT", "local")})
