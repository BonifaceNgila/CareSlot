import threading
import unittest
from datetime import datetime

from django.db import connection, connections
from django.test import TransactionTestCase

from scheduling import services
from scheduling.exceptions import ConflictError
from scheduling.models import Appointment, Patient

from .helpers import SchedulingFixtures, at


@unittest.skipIf(connection.vendor == "sqlite", "needs real concurrent transactions (PostgreSQL)")
class ConcurrentBookingTests(SchedulingFixtures, TransactionTestCase):
    def test_only_one_of_many_simultaneous_bookings_wins(self):
        patients = [Patient.objects.create(name=f"Racer {i}") for i in range(8)]
        slot = datetime.fromisoformat(at(7, 9))
        barrier = threading.Barrier(len(patients))
        outcomes = []

        def attempt(patient):
            try:
                barrier.wait()
                services.book_appointment(doctor_id=self.doctor.id, patient_id=patient.id, start_at=slot)
                outcomes.append("booked")
            except ConflictError:
                outcomes.append("conflict")
            finally:
                connections.close_all()

        threads = [threading.Thread(target=attempt, args=(patient,)) for patient in patients]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(outcomes.count("booked"), 1, outcomes)
        self.assertEqual(outcomes.count("conflict"), len(patients) - 1, outcomes)
        self.assertEqual(Appointment.objects.booked().count(), 1)
