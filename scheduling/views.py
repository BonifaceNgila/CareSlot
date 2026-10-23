from django.conf import settings
from django.http import JsonResponse
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .models import Doctor
from .serializers import (
    AppointmentSerializer,
    AvailabilityQuerySerializer,
    AvailabilitySerializer,
    BookAppointmentSerializer,
    CancelAppointmentSerializer,
    DoctorSerializer,
    PatientSerializer,
    RescheduleAppointmentSerializer,
)


def _validated(serializer_class, data):
    serializer = serializer_class(data=data)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


class DoctorListView(APIView):
    @extend_schema(responses=DoctorSerializer(many=True), tags=["doctors"])
    def get(self, request):
        doctors = Doctor.objects.filter(is_active=True).prefetch_related("working_hours")
        return Response(DoctorSerializer(doctors, many=True).data)


class DoctorAvailabilityView(APIView):
    @extend_schema(parameters=[AvailabilityQuerySerializer], responses=AvailabilitySerializer, tags=["doctors"])
    def get(self, request, doctor_id):
        day = _validated(AvailabilityQuerySerializer, request.query_params)["date"]
        doctor = services.get_doctor(doctor_id)
        payload = {
            "doctor_id": doctor.id,
            "doctor_name": doctor.name,
            "date": day,
            "timezone": settings.TIME_ZONE,
            "slot_minutes": settings.SLOT_MINUTES,
            "slots": services.available_slots(doctor, day),
        }
        return Response(AvailabilitySerializer(payload).data)


class PatientCreateView(APIView):
    @extend_schema(request=PatientSerializer, responses={201: PatientSerializer}, tags=["patients"])
    def post(self, request):
        serializer = PatientSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class PatientAppointmentsView(APIView):
    @extend_schema(
        responses=AppointmentSerializer(many=True),
        tags=["patients"],
        description="Upcoming (future, not cancelled) appointments for a patient, soonest first.",
    )
    def get(self, request, patient_id):
        return Response(AppointmentSerializer(services.upcoming_appointments(patient_id), many=True).data)


class AppointmentCreateView(APIView):
    @extend_schema(request=BookAppointmentSerializer, responses={201: AppointmentSerializer}, tags=["appointments"])
    def post(self, request):
        appointment = services.book_appointment(**_validated(BookAppointmentSerializer, request.data))
        return Response(AppointmentSerializer(appointment).data, status=status.HTTP_201_CREATED)


class AppointmentDetailView(APIView):
    @extend_schema(responses=AppointmentSerializer, tags=["appointments"])
    def get(self, request, appointment_id):
        return Response(AppointmentSerializer(services.get_appointment(appointment_id)).data)


class AppointmentCancelView(APIView):
    @extend_schema(request=CancelAppointmentSerializer, responses=AppointmentSerializer, tags=["appointments"])
    def patch(self, request, appointment_id):
        reason = _validated(CancelAppointmentSerializer, request.data)["reason"]
        appointment = services.cancel_appointment(appointment_id, reason=reason)
        return Response(AppointmentSerializer(appointment).data)


class AppointmentRescheduleView(APIView):
    @extend_schema(request=RescheduleAppointmentSerializer, responses=AppointmentSerializer, tags=["appointments"])
    def patch(self, request, appointment_id):
        start_at = _validated(RescheduleAppointmentSerializer, request.data)["start_at"]
        appointment = services.reschedule_appointment(appointment_id, start_at=start_at)
        return Response(AppointmentSerializer(appointment).data)


def json_not_found(request, exception=None):
    """Unmatched URLs get the same error envelope as the API instead of Django's HTML page."""
    error = {"code": "not_found", "message": f"No route for {request.path}.", "details": None}
    return JsonResponse({"error": error}, status=404)
