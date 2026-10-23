from django.urls import path

from . import views

urlpatterns = [
    path("doctors", views.DoctorListView.as_view(), name="doctor-list"),
    path("doctors/<int:doctor_id>/availability", views.DoctorAvailabilityView.as_view(), name="doctor-availability"),
    path("patients", views.PatientCreateView.as_view(), name="patient-create"),
    path(
        "patients/<int:patient_id>/appointments",
        views.PatientAppointmentsView.as_view(),
        name="patient-appointments",
    ),
    path("appointments", views.AppointmentCreateView.as_view(), name="appointment-create"),
    path("appointments/<int:appointment_id>", views.AppointmentDetailView.as_view(), name="appointment-detail"),
    path(
        "appointments/<int:appointment_id>/cancel",
        views.AppointmentCancelView.as_view(),
        name="appointment-cancel",
    ),
    path(
        "appointments/<int:appointment_id>/reschedule",
        views.AppointmentRescheduleView.as_view(),
        name="appointment-reschedule",
    ),
]
