from rest_framework import serializers

from .models import Appointment, Doctor, Patient, WorkingHours


class WorkingHoursSerializer(serializers.ModelSerializer):
    weekday = serializers.CharField(source="get_weekday_display")

    class Meta:
        model = WorkingHours
        fields = ["weekday", "start_time", "end_time"]


class DoctorSerializer(serializers.ModelSerializer):
    working_hours = WorkingHoursSerializer(many=True, read_only=True)

    class Meta:
        model = Doctor
        fields = ["id", "name", "specialty", "working_hours"]


class PatientSerializer(serializers.ModelSerializer):
    class Meta:
        model = Patient
        fields = ["id", "name", "phone", "email", "created_at"]
        read_only_fields = ["id", "created_at"]


class AppointmentSerializer(serializers.ModelSerializer):
    doctor_id = serializers.IntegerField(read_only=True)
    doctor_name = serializers.CharField(source="doctor.name", read_only=True)
    patient_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = Appointment
        fields = [
            "id",
            "doctor_id",
            "doctor_name",
            "patient_id",
            "start_at",
            "end_at",
            "status",
            "cancellation_reason",
            "cancelled_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class BookAppointmentSerializer(serializers.Serializer):
    doctor_id = serializers.IntegerField(min_value=1)
    patient_id = serializers.IntegerField(min_value=1)
    start_at = serializers.DateTimeField(
        help_text="Slot start, ISO 8601. Without an offset it is read as clinic local time (Africa/Nairobi)."
    )


class RescheduleAppointmentSerializer(serializers.Serializer):
    start_at = serializers.DateTimeField(help_text="New slot start, ISO 8601.")


class CancelAppointmentSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500)


class AvailabilityQuerySerializer(serializers.Serializer):
    date = serializers.DateField(help_text="Day to list free slots for, YYYY-MM-DD.")


class SlotSerializer(serializers.Serializer):
    start_at = serializers.DateTimeField(source="start")
    end_at = serializers.DateTimeField(source="end")


class AvailabilitySerializer(serializers.Serializer):
    doctor_id = serializers.IntegerField()
    doctor_name = serializers.CharField()
    date = serializers.DateField()
    timezone = serializers.CharField()
    slot_minutes = serializers.IntegerField()
    slots = SlotSerializer(many=True)
