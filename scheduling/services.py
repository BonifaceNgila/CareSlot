"""Booking rules.

Views only parse input and render output; every decision about whether a slot can be booked,
cancelled or moved lives here so it can be tested and reused (admin, future background jobs).
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from .exceptions import ConflictError, NotFoundError, SlotValidationError
from .models import Appointment, Doctor, Patient, WorkingHours

SLOT_LENGTH = timedelta(minutes=settings.SLOT_MINUTES)
MIN_NOTICE = timedelta(minutes=settings.BOOKING_MIN_NOTICE_MINUTES)


@dataclass(frozen=True)
class Slot:
    start: datetime
    end: datetime


def now():
    """Single source of 'current time' so tests can pin it."""
    return timezone.now()


def clinic_tz():
    return timezone.get_default_timezone()


# --- lookups ---------------------------------------------------------------------------------


def get_doctor(doctor_id):
    try:
        return Doctor.objects.get(pk=doctor_id, is_active=True)
    except Doctor.DoesNotExist:
        raise NotFoundError(f"Doctor {doctor_id} not found.", code="doctor_not_found") from None


def get_patient(patient_id):
    try:
        return Patient.objects.get(pk=patient_id)
    except Patient.DoesNotExist:
        raise NotFoundError(f"Patient {patient_id} not found.", code="patient_not_found") from None


def get_appointment(appointment_id, *, for_update=False):
    queryset = Appointment.objects.select_related("doctor", "patient")
    if for_update:
        queryset = queryset.select_for_update(of=("self",))
    try:
        return queryset.get(pk=appointment_id)
    except Appointment.DoesNotExist:
        raise NotFoundError(f"Appointment {appointment_id} not found.", code="appointment_not_found") from None


# --- slots -----------------------------------------------------------------------------------


def working_hours_on(doctor, day: date):
    return WorkingHours.objects.filter(doctor=doctor, weekday=day.weekday()).first()


def shift_bounds(shift: WorkingHours, day: date):
    tz = clinic_tz()
    return datetime.combine(day, shift.start_time, tzinfo=tz), datetime.combine(day, shift.end_time, tzinfo=tz)


def slots_for_day(doctor, day: date) -> list[Slot]:
    """Every slot in the doctor's shift on `day`, ignoring bookings. A trailing partial slot is dropped."""
    shift = working_hours_on(doctor, day)
    if shift is None:
        return []
    cursor, shift_end = shift_bounds(shift, day)
    slots = []
    while cursor + SLOT_LENGTH <= shift_end:
        slots.append(Slot(cursor, cursor + SLOT_LENGTH))
        cursor += SLOT_LENGTH
    return slots


def available_slots(doctor, day: date) -> list[Slot]:
    slots = slots_for_day(doctor, day)
    if not slots:
        return []
    booked = list(
        Appointment.objects.booked()
        .filter(doctor=doctor)
        .overlapping(slots[0].start, slots[-1].end)
        .values_list("start_at", "end_at")
    )
    earliest = now() + MIN_NOTICE
    return [
        slot
        for slot in slots
        if slot.start >= earliest and not any(start < slot.end and end > slot.start for start, end in booked)
    ]


def validate_slot(doctor, start_at: datetime) -> Slot:
    """Check that `start_at` is a bookable slot for `doctor`, ignoring existing bookings."""
    if timezone.is_naive(start_at):
        start_at = timezone.make_aware(start_at, clinic_tz())

    current = now()
    if start_at <= current:
        raise SlotValidationError("Appointments cannot be booked in the past.", code="slot_in_past")
    if start_at < current + MIN_NOTICE:
        raise SlotValidationError(
            f"Appointments must be booked at least {settings.BOOKING_MIN_NOTICE_MINUTES} minutes in advance.",
            code="insufficient_notice",
        )

    local = timezone.localtime(start_at, clinic_tz())
    shift = working_hours_on(doctor, local.date())
    if shift is None:
        raise SlotValidationError(f"{doctor.name} does not work on {local:%A}s.", code="outside_working_hours")

    shift_start, shift_end = shift_bounds(shift, local.date())
    if not (shift_start <= local and local + SLOT_LENGTH <= shift_end):
        raise SlotValidationError(
            f"{local:%H:%M} is outside {doctor.name}'s working hours on {local:%A} "
            f"({shift.start_time:%H:%M}-{shift.end_time:%H:%M}, last slot starts "
            f"{(shift_end - SLOT_LENGTH):%H:%M}).",
            code="outside_working_hours",
        )
    if (local - shift_start) % SLOT_LENGTH:
        raise SlotValidationError(
            f"Appointments start every {settings.SLOT_MINUTES} minutes from {shift.start_time:%H:%M}; "
            f"{local:%H:%M:%S} is not a slot boundary.",
            code="invalid_slot_boundary",
        )
    return Slot(local, local + SLOT_LENGTH)


def _ensure_free(doctor, patient, slot: Slot, *, exclude_id=None):
    clashing = Appointment.objects.booked().overlapping(slot.start, slot.end).exclude(pk=exclude_id)
    if clashing.filter(doctor=doctor).exists():
        raise ConflictError("This slot is already booked.", code="slot_unavailable")
    if clashing.filter(patient=patient).exists():
        raise ConflictError("The patient already has an appointment at this time.", code="patient_double_booked")


def _ensure_modifiable(appointment, action):
    if appointment.status == Appointment.Status.CANCELLED:
        raise ConflictError(
            "Appointment is already cancelled." if action == "cancel" else "Cannot reschedule a cancelled appointment.",
            code="appointment_cancelled",
        )
    if appointment.start_at <= now():
        raise ConflictError(f"Cannot {action} an appointment that has already started.", code="appointment_started")


# --- commands --------------------------------------------------------------------------------


def book_appointment(*, doctor_id, patient_id, start_at) -> Appointment:
    doctor = get_doctor(doctor_id)
    patient = get_patient(patient_id)
    slot = validate_slot(doctor, start_at)
    try:
        with transaction.atomic():
            _ensure_free(doctor, patient, slot)
            return Appointment.objects.create(doctor=doctor, patient=patient, start_at=slot.start, end_at=slot.end)
    except IntegrityError:
        # Lost a race: another request booked the slot between our check and our insert.
        raise ConflictError("This slot is already booked.", code="slot_unavailable") from None


def cancel_appointment(appointment_id, *, reason) -> Appointment:
    with transaction.atomic():
        appointment = get_appointment(appointment_id, for_update=True)
        _ensure_modifiable(appointment, "cancel")
        appointment.status = Appointment.Status.CANCELLED
        appointment.cancellation_reason = reason
        appointment.cancelled_at = now()
        appointment.save(update_fields=["status", "cancellation_reason", "cancelled_at", "updated_at"])
    return appointment


def reschedule_appointment(appointment_id, *, start_at) -> Appointment:
    """Move an appointment within the same doctor's schedule. The row is updated in place, so the
    old slot is released and the new one taken in a single transaction: on any failure the
    appointment keeps its original slot."""
    try:
        with transaction.atomic():
            appointment = get_appointment(appointment_id, for_update=True)
            _ensure_modifiable(appointment, "reschedule")
            slot = validate_slot(appointment.doctor, start_at)
            if slot.start == appointment.start_at:
                raise SlotValidationError("The appointment is already booked for this slot.", code="same_slot")
            _ensure_free(appointment.doctor, appointment.patient, slot, exclude_id=appointment.pk)
            appointment.start_at, appointment.end_at = slot.start, slot.end
            appointment.save(update_fields=["start_at", "end_at", "updated_at"])
            return appointment
    except IntegrityError:
        raise ConflictError("This slot is already booked.", code="slot_unavailable") from None


def upcoming_appointments(patient_id):
    patient = get_patient(patient_id)
    return (
        Appointment.objects.booked()
        .filter(patient=patient, start_at__gt=now())
        .select_related("doctor", "patient")
        .order_by("start_at")
    )
