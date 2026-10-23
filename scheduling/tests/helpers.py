from datetime import datetime, time
from unittest import mock
from zoneinfo import ZoneInfo

from scheduling.models import Doctor, Patient, WorkingHours

NAIROBI = ZoneInfo("Africa/Nairobi")
# Tests run with the clock pinned to Monday 7 January 2030, 06:00 clinic time.
NOW = datetime(2030, 1, 7, 6, 0, tzinfo=NAIROBI)


def at(day, hour, minute=0):
    """ISO timestamp in clinic time on `day` January 2030 (7th = Monday, 12th = Saturday)."""
    return datetime(2030, 1, day, hour, minute, tzinfo=NAIROBI).isoformat()


class SchedulingFixtures:
    """Mixin: pins the clock and creates a weekday 09:00-17:00 doctor and two patients."""

    now = NOW

    def setUp(self):
        super().setUp()
        patcher = mock.patch("scheduling.services.now", side_effect=lambda: self.now)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.doctor = Doctor.objects.create(name="Dr. Test", specialty="General Practice")
        for weekday in range(5):
            WorkingHours.objects.create(doctor=self.doctor, weekday=weekday, start_time=time(9), end_time=time(17))
        self.patient = Patient.objects.create(name="Patient One")
        self.other_patient = Patient.objects.create(name="Patient Two")
