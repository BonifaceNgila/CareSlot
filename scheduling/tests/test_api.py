from datetime import time, timedelta
from unittest import mock

from rest_framework.test import APITestCase

from scheduling.models import Appointment, Doctor, WorkingHours

from .helpers import NOW, SchedulingFixtures, at


class ApiTestCase(SchedulingFixtures, APITestCase):
    def book(self, start_at, doctor=None, patient=None):
        payload = {
            "doctor_id": (doctor or self.doctor).id,
            "patient_id": (patient or self.patient).id,
            "start_at": start_at,
        }
        return self.client.post("/appointments", payload, format="json")

    def cancel(self, appointment_id, reason="Feeling better"):
        return self.client.patch(f"/appointments/{appointment_id}/cancel", {"reason": reason}, format="json")

    def reschedule(self, appointment_id, start_at):
        return self.client.patch(f"/appointments/{appointment_id}/reschedule", {"start_at": start_at}, format="json")

    def slots(self, day="2030-01-07", doctor=None):
        response = self.client.get(f"/doctors/{(doctor or self.doctor).id}/availability", {"date": day})
        self.assertEqual(response.status_code, 200, response.content)
        return [slot["start_at"] for slot in response.json()["slots"]]

    def assertError(self, response, status_code, code):
        self.assertEqual(response.status_code, status_code, response.content)
        self.assertEqual(response.json()["error"]["code"], code)
        self.assertTrue(response.json()["error"]["message"])


class BookingTests(ApiTestCase):
    def test_books_a_free_slot(self):
        response = self.book(at(7, 9))
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual(body["status"], "booked")
        self.assertEqual(body["start_at"], at(7, 9))
        self.assertEqual(body["end_at"], at(7, 9, 30))
        self.assertEqual(body["doctor_id"], self.doctor.id)

    def test_rejects_a_taken_slot(self):
        self.book(at(7, 9))
        self.assertError(self.book(at(7, 9), patient=self.other_patient), 409, "slot_unavailable")

    def test_same_instant_in_another_offset_is_the_same_slot(self):
        self.book(at(7, 9))
        self.assertError(self.book("2030-01-07T06:00:00Z", patient=self.other_patient), 409, "slot_unavailable")

    def test_naive_datetime_is_read_as_clinic_time(self):
        response = self.book("2030-01-07T09:00:00")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["start_at"], at(7, 9))

    def test_other_doctors_slot_at_same_time_is_independent(self):
        second = Doctor.objects.create(name="Dr. Second")
        WorkingHours.objects.create(doctor=second, weekday=0, start_time=time(9), end_time=time(17))
        self.book(at(7, 9))
        self.assertEqual(self.book(at(7, 9), doctor=second, patient=self.other_patient).status_code, 201)

    def test_patient_cannot_be_in_two_places_at_once(self):
        second = Doctor.objects.create(name="Dr. Second")
        WorkingHours.objects.create(doctor=second, weekday=0, start_time=time(9), end_time=time(17))
        self.book(at(7, 9))
        self.assertError(self.book(at(7, 9), doctor=second), 409, "patient_double_booked")

    def test_rejects_slots_outside_working_hours(self):
        cases = {
            "before shift": at(7, 8, 30),
            "shift end": at(7, 17),
            "after shift": at(7, 18),
            "Saturday": at(12, 9),
        }
        for label, start_at in cases.items():
            with self.subTest(label):
                self.assertError(self.book(start_at), 400, "outside_working_hours")

    def test_last_slot_of_the_day_is_bookable(self):
        self.assertEqual(self.book(at(7, 16, 30)).status_code, 201)

    def test_rejects_times_off_the_slot_grid(self):
        for start_at in (at(7, 9, 15), "2030-01-07T09:00:30+03:00"):
            with self.subTest(start_at):
                self.assertError(self.book(start_at), 400, "invalid_slot_boundary")

    def test_rejects_past_slots(self):
        self.assertError(self.book(at(4, 10)), 400, "slot_in_past")

    def test_rejects_slots_less_than_an_hour_away(self):
        self.now = NOW.replace(hour=8, minute=30)
        self.assertError(self.book(at(7, 9)), 400, "insufficient_notice")
        self.assertEqual(self.book(at(7, 9, 30)).status_code, 201)

    def test_unknown_doctor_or_patient(self):
        self.assertError(self.client.post(
            "/appointments", {"doctor_id": 999, "patient_id": self.patient.id, "start_at": at(7, 9)}, format="json"
        ), 404, "doctor_not_found")
        self.assertError(self.client.post(
            "/appointments", {"doctor_id": self.doctor.id, "patient_id": 999, "start_at": at(7, 9)}, format="json"
        ), 404, "patient_not_found")

    def test_malformed_payload_lists_field_errors(self):
        response = self.client.post("/appointments", {"doctor_id": "x", "start_at": "tomorrow"}, format="json")
        self.assertError(response, 400, "validation_error")
        self.assertEqual(set(response.json()["error"]["details"]), {"doctor_id", "patient_id", "start_at"})

    def test_database_constraint_catches_a_race_the_precheck_missed(self):
        """Simulate two requests passing the availability check before either inserts."""
        self.book(at(7, 9))
        with mock.patch("scheduling.services._ensure_free"):
            self.assertError(self.book(at(7, 9), patient=self.other_patient), 409, "slot_unavailable")
        self.assertEqual(Appointment.objects.count(), 1)


class CancelTests(ApiTestCase):
    def test_cancel_records_reason_and_frees_the_slot(self):
        appointment = self.book(at(7, 9)).json()
        response = self.cancel(appointment["id"], "Travelling")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["status"], "cancelled")
        self.assertEqual(response.json()["cancellation_reason"], "Travelling")
        self.assertIsNotNone(response.json()["cancelled_at"])
        self.assertIn(at(7, 9), self.slots())
        self.assertEqual(self.book(at(7, 9), patient=self.other_patient).status_code, 201)

    def test_cancelling_twice_is_a_conflict(self):
        appointment = self.book(at(7, 9)).json()
        self.cancel(appointment["id"])
        self.assertError(self.cancel(appointment["id"]), 409, "appointment_cancelled")

    def test_reason_is_required(self):
        appointment = self.book(at(7, 9)).json()
        for payload in ({}, {"reason": ""}, {"reason": "   "}):
            with self.subTest(payload):
                response = self.client.patch(f"/appointments/{appointment['id']}/cancel", payload, format="json")
                self.assertError(response, 400, "validation_error")

    def test_cannot_cancel_an_appointment_that_already_started(self):
        appointment = self.book(at(7, 9)).json()
        self.now = NOW.replace(hour=9, minute=10)
        self.assertError(self.cancel(appointment["id"]), 409, "appointment_started")

    def test_unknown_appointment(self):
        self.assertError(self.cancel(999), 404, "appointment_not_found")


class RescheduleTests(ApiTestCase):
    def test_moves_the_appointment_and_frees_the_original_slot(self):
        appointment = self.book(at(7, 9)).json()
        response = self.reschedule(appointment["id"], at(7, 11))
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["start_at"], at(7, 11))
        self.assertEqual(response.json()["id"], appointment["id"])
        self.assertIn(at(7, 9), self.slots())
        self.assertNotIn(at(7, 11), self.slots())

    def test_taken_target_leaves_original_booking_intact(self):
        appointment = self.book(at(7, 9)).json()
        self.book(at(7, 10), patient=self.other_patient)
        self.assertError(self.reschedule(appointment["id"], at(7, 10)), 409, "slot_unavailable")
        self.assertEqual(Appointment.objects.get(pk=appointment["id"]).start_at.isoformat(), "2030-01-07T06:00:00+00:00")
        self.assertNotIn(at(7, 9), self.slots())

    def test_new_slot_gets_full_booking_validation(self):
        appointment = self.book(at(7, 9)).json()
        self.assertError(self.reschedule(appointment["id"], at(7, 18)), 400, "outside_working_hours")
        self.assertError(self.reschedule(appointment["id"], at(7, 9, 10)), 400, "invalid_slot_boundary")
        self.assertError(self.reschedule(appointment["id"], at(4, 9)), 400, "slot_in_past")
        self.assertError(self.reschedule(appointment["id"], at(7, 6, 30)), 400, "insufficient_notice")

    def test_cannot_reschedule_a_cancelled_appointment(self):
        appointment = self.book(at(7, 9)).json()
        self.cancel(appointment["id"])
        self.assertError(self.reschedule(appointment["id"], at(7, 11)), 409, "appointment_cancelled")

    def test_cannot_reschedule_with_a_retired_doctor(self):
        appointment = self.book(at(7, 9)).json()
        self.doctor.is_active = False
        self.doctor.save()
        self.assertError(self.reschedule(appointment["id"], at(7, 11)), 409, "doctor_unavailable")
        self.assertEqual(self.cancel(appointment["id"]).status_code, 200)

    def test_rescheduling_to_the_same_slot_is_rejected(self):
        appointment = self.book(at(7, 9)).json()
        self.assertError(self.reschedule(appointment["id"], at(7, 9)), 400, "same_slot")

    def test_can_move_to_another_day(self):
        appointment = self.book(at(7, 9)).json()
        self.assertEqual(self.reschedule(appointment["id"], at(8, 9)).status_code, 200)


class AvailabilityTests(ApiTestCase):
    def test_lists_every_slot_in_the_shift(self):
        slots = self.slots()
        self.assertEqual(len(slots), 16)
        self.assertEqual(slots[0], at(7, 9))
        self.assertEqual(slots[-1], at(7, 16, 30))

    def test_response_shape(self):
        body = self.client.get(f"/doctors/{self.doctor.id}/availability", {"date": "2030-01-07"}).json()
        self.assertEqual(body["timezone"], "Africa/Nairobi")
        self.assertEqual(body["slot_minutes"], 30)
        self.assertEqual(body["slots"][0], {"start_at": at(7, 9), "end_at": at(7, 9, 30)})

    def test_booked_slots_are_hidden(self):
        self.book(at(7, 10))
        slots = self.slots()
        self.assertNotIn(at(7, 10), slots)
        self.assertEqual(len(slots), 15)

    def test_slots_inside_the_notice_window_are_hidden(self):
        self.now = NOW.replace(hour=10, minute=5)
        self.assertEqual(self.slots()[0], at(7, 11, 30))

    def test_day_off_and_past_day_are_empty(self):
        self.assertEqual(self.slots("2030-01-12"), [])
        self.assertEqual(self.slots("2030-01-04"), [])

    def test_date_is_required_and_validated(self):
        url = f"/doctors/{self.doctor.id}/availability"
        self.assertError(self.client.get(url), 400, "validation_error")
        self.assertError(self.client.get(url, {"date": "07/01/2030"}), 400, "validation_error")

    def test_unknown_doctor(self):
        self.assertError(self.client.get("/doctors/999/availability", {"date": "2030-01-07"}), 404, "doctor_not_found")

    def test_existing_booking_blocks_overlapping_slots_after_hours_change(self):
        """If a doctor's shift moves to a different grid, older bookings must still block overlaps."""
        self.book(at(7, 9))
        WorkingHours.objects.filter(doctor=self.doctor, weekday=0).update(start_time=time(8, 45))
        self.assertNotIn(at(7, 8, 45), self.slots())
        self.assertNotIn(at(7, 9, 15), self.slots())
        self.assertError(self.book(at(7, 9, 15), patient=self.other_patient), 409, "slot_unavailable")


class PatientAppointmentsTests(ApiTestCase):
    def test_upcoming_appointments_sorted_and_filtered(self):
        late = self.book(at(9, 14)).json()
        early = self.book(at(7, 10)).json()
        cancelled = self.book(at(8, 9)).json()
        self.cancel(cancelled["id"])
        self.book(at(7, 11), patient=self.other_patient)

        response = self.client.get(f"/patients/{self.patient.id}/appointments")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.json()], [early["id"], late["id"]])

    def test_appointments_that_have_started_are_not_upcoming(self):
        self.book(at(7, 9))
        self.now = NOW + timedelta(hours=3, minutes=5)
        self.assertEqual(self.client.get(f"/patients/{self.patient.id}/appointments").json(), [])

    def test_unknown_patient(self):
        self.assertError(self.client.get("/patients/999/appointments"), 404, "patient_not_found")


class MiscTests(ApiTestCase):
    def test_seeded_doctors_are_listed_with_hours(self):
        doctors = self.client.get("/doctors").json()
        self.assertEqual(len(doctors), 6)  # five seeded by migration + the test doctor
        self.assertTrue(all(doctor["working_hours"] for doctor in doctors))

    def test_create_patient(self):
        response = self.client.post("/patients", {"name": "New Patient", "phone": "+254700000000"}, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertError(self.client.post("/patients", {}, format="json"), 400, "validation_error")

    def test_health(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_unknown_route_returns_json_404(self):
        self.assertError(self.client.get("/nope"), 404, "not_found")
