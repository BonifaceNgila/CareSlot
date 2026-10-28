import json
from datetime import datetime, time
from io import StringIO
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from scheduling import services
from scheduling.models import Appointment, Doctor, Patient, WorkingHours


class DemoSeedTests(TestCase):
    def setUp(self):
        Doctor.objects.all().delete()
        self.doctor = Doctor.objects.create(name="Demo Doctor")
        WorkingHours.objects.create(doctor=self.doctor, weekday=2, start_time=time(9), end_time=time(12))
        self.clock = patch(
            "scheduling.services.now", return_value=datetime(2026, 10, 27, 18, tzinfo=ZoneInfo("Africa/Nairobi"))
        )
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def seed(self):
        output = StringIO()
        call_command("seed_demo", stdout=output)
        return json.loads(output.getvalue())["demo_examples"]

    def test_scenarios_are_valid_and_repeat_does_not_duplicate(self):
        examples = self.seed()
        self.assertEqual(len(examples), 3)
        self.assertEqual(Patient.objects.count(), 3)
        self.assertEqual(Appointment.objects.booked().count(), 2)
        cancelled = Appointment.objects.get(status="cancelled")
        available = services.available_slots(self.doctor, cancelled.start_at.astimezone(services.clinic_tz()).date())
        self.assertIn(cancelled.start_at, [slot.start for slot in available])
        self.assertEqual(examples, self.seed())
        self.assertEqual(Appointment.objects.count(), 3)
        self.assertEqual(Patient.objects.count(), 3)

    def test_missing_working_hours_rolls_back_patients(self):
        WorkingHours.objects.all().delete()
        with self.assertRaises(CommandError):
            self.seed()
        self.assertEqual(Patient.objects.count(), 0)
        self.assertEqual(Appointment.objects.count(), 0)
