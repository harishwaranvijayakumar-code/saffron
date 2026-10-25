
from django.db import connections
from django.http import JsonResponse


def health(request):
    return JsonResponse({
        "status": "ok",
        "service": "saffron",
    })


def readiness(request):
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        return JsonResponse(
            {"status": "not_ready", "service": "saffron"},
            status=503,
        )

    return JsonResponse({
        "status": "ready",
        "service": "saffron",
        "database": "connected",
    })
