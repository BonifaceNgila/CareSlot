from django.db import models
from django.db.models import Case, F, Q, When


class Doctor(models.Model):
    name = models.CharField(max_length=120)
    specialty = models.CharField(max_length=120, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return self.name


class WorkingHours(models.Model):
    """One shift per doctor per weekday, in the clinic's local time zone."""

    class Weekday(models.IntegerChoices):
        MONDAY = 0
        TUESDAY = 1
        WEDNESDAY = 2
        THURSDAY = 3
        FRIDAY = 4
        SATURDAY = 5
        SUNDAY = 6

    doctor = models.ForeignKey(Doctor, on_delete=models.CASCADE, related_name="working_hours")
    weekday = models.PositiveSmallIntegerField(choices=Weekday.choices)
    start_time = models.TimeField()
    end_time = models.TimeField()

    class Meta:
        ordering = ["doctor", "weekday"]
        verbose_name_plural = "working hours"
        constraints = [
            models.UniqueConstraint(fields=["doctor", "weekday"], name="one_shift_per_doctor_per_weekday"),
            models.CheckConstraint(condition=Q(end_time__gt=F("start_time")), name="shift_ends_after_it_starts"),
        ]

    def __str__(self):
        return f"{self.doctor} {self.get_weekday_display()} {self.start_time:%H:%M}-{self.end_time:%H:%M}"


class Patient(models.Model):
    name = models.CharField(max_length=120)
    phone = models.CharField(max_length=32, blank=True)
    email = models.EmailField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return self.name


class AppointmentQuerySet(models.QuerySet):
    def booked(self):
        return self.filter(status=Appointment.Status.BOOKED)

    def overlapping(self, start, end):
        return self.filter(start_at__lt=end, end_at__gt=start)


class Appointment(models.Model):
    class Status(models.TextChoices):
        BOOKED = "booked"
        CANCELLED = "cancelled"

    doctor = models.ForeignKey(Doctor, on_delete=models.PROTECT, related_name="appointments")
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="appointments")
    start_at = models.DateTimeField()
    end_at = models.DateTimeField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.BOOKED)
    cancellation_reason = models.TextField(blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # start_at while booked, NULL once cancelled. Maintained by the database itself. Unique indexes
    # ignore NULLs, so the constraint below means "one *active* booking per doctor per slot" while
    # cancelled rows stay for history. A generated column is used because MySQL has no partial indexes
    # (Django silently skips a conditional UniqueConstraint there).
    active_start_at = models.GeneratedField(
        expression=Case(When(status="booked", then=F("start_at")), default=None),
        output_field=models.DateTimeField(null=True),
        db_persist=True,
    )

    objects = AppointmentQuerySet.as_manager()

    class Meta:
        ordering = ["start_at"]
        constraints = [
            # The database-level guarantee against double booking, including concurrent requests.
            models.UniqueConstraint(fields=["doctor", "active_start_at"], name="unique_active_booking_per_doctor_slot"),
            models.CheckConstraint(condition=Q(end_at__gt=F("start_at")), name="appointment_ends_after_it_starts"),
        ]
        indexes = [
            models.Index(fields=["doctor", "start_at"]),
            models.Index(fields=["patient", "start_at"]),
        ]

    def __str__(self):
        return f"{self.patient} with {self.doctor} at {self.start_at:%Y-%m-%d %H:%M}"
