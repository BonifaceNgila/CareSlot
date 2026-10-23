"""Domain errors and a single JSON error envelope for every API failure.

Every error response has the shape:
    {"error": {"code": "<machine-readable>", "message": "<human-readable>", "details": {...} | null}}
"""

from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.views import exception_handler


class BookingError(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "invalid_booking"
    default_detail = "The booking request is invalid."


class SlotValidationError(BookingError):
    """The requested time is not a bookable slot (outside hours, in the past, misaligned...)."""


class NotFoundError(BookingError):
    status_code = status.HTTP_404_NOT_FOUND
    default_code = "not_found"
    default_detail = "Resource not found."


class ConflictError(BookingError):
    """The request is valid but clashes with current state (slot taken, already cancelled...)."""

    status_code = status.HTTP_409_CONFLICT
    default_code = "conflict"
    default_detail = "The request conflicts with the current state."


def api_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        return None

    data = response.data
    if isinstance(data, dict) and set(data) == {"detail"}:
        detail = data["detail"]
        body = {"code": getattr(detail, "code", "error"), "message": str(detail), "details": None}
    else:
        # Serializer validation errors: keep DRF's per-field messages under "details".
        body = {"code": "validation_error", "message": "Request validation failed.", "details": data}
    response.data = {"error": body}
    return response
