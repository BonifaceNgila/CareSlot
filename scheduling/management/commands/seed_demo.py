"""Create synthetic API examples without deleting or replacing existing records."""

import json
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from scheduling import services
from scheduling.models import Appointment, Doctor, Patient


class Command(BaseCommand):
    help = "Seed clearly labelled demo patients and booked, rescheduled, and cancelled appointments."

    @transaction.atomic
    def handle(self, *args, **options):
        doctors = list(Doctor.objects.select_for_update().filter(is_active=True).order_by("id"))
        if not doctors:
            raise CommandError("No active doctors. Run migrations before seeding demo data.")
        first_day = timezone.localtime(services.now()).date() + timedelta(days=1)
        examples = []
        for index, doctor in enumerate(doctors):
            for offset, scenario in enumerate(("booked", "rescheduled", "cancelled")):
                patient, _ = Patient.objects.get_or_create(
                    email=f"demo.doctor{doctor.pk}.{scenario}@example.com",
                    defaults={"name": f"Demo Patient {index * 3 + offset + 1:02d}", "phone": ""},
                )
                appointment = Appointment.objects.filter(doctor=doctor, patient=patient).order_by("id").first()
                if appointment is None:
                    slots = []
                    for days in range(14):
                        slots.extend(services.available_slots(doctor, first_day + timedelta(days=days)))
                        if len(slots) >= 2:
                            break
                    required = 2 if scenario == "rescheduled" else 1
                    if len(slots) < required:
                        raise CommandError(f"Not enough available slots for {doctor.name} in the next 14 days.")
                    appointment = services.book_appointment(
                        doctor_id=doctor.pk, patient_id=patient.pk, start_at=slots[0].start
                    )
                    if scenario == "rescheduled":
                        appointment = services.reschedule_appointment(appointment.pk, start_at=slots[1].start)
                    elif scenario == "cancelled":
                        appointment = services.cancel_appointment(
                            appointment.pk, reason="Demo: fictional patient changed plans."
                        )
                examples.append(
                    {
                        "scenario": scenario,
                        "patient_id": patient.pk,
                        "patient_name": patient.name,
                        "doctor_id": doctor.pk,
                        "doctor_name": doctor.name,
                        "appointment_id": appointment.pk,
                        "status": appointment.status,
                        "start_at": timezone.localtime(appointment.start_at).isoformat(),
                    }
                )
        self.stdout.write(json.dumps({"demo_examples": examples}, indent=2))
