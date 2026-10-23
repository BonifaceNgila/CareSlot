"""Seed the clinic's five doctors (fictional) and their weekly working hours.

Hours deliberately differ per doctor to show the schedule is per doctor, not clinic-wide.
Weekdays: 0 = Monday ... 6 = Sunday. Times are clinic local time.
"""

from datetime import time

from django.db import migrations

WEEKDAYS = range(0, 5)

DOCTORS = [
    ("Dr. Amina Odhiambo", "General Practice", {day: (time(8), time(16)) for day in WEEKDAYS}),
    ("Dr. Brian Mwangi", "Paediatrics", {day: (time(9), time(17)) for day in WEEKDAYS}),
    ("Dr. Catherine Wanjiru", "Dermatology", {day: (time(10), time(18)) for day in (0, 2, 4)}),
    ("Dr. David Kiprop", "Cardiology", {1: (time(8), time(13)), 3: (time(8), time(13)), 5: (time(9), time(12))}),
    ("Dr. Esther Achieng", "Obstetrics & Gynaecology", {day: (time(9), time(14)) for day in range(0, 6)}),
]


def seed(apps, schema_editor):
    Doctor = apps.get_model("scheduling", "Doctor")
    WorkingHours = apps.get_model("scheduling", "WorkingHours")
    for name, specialty, schedule in DOCTORS:
        doctor, _ = Doctor.objects.get_or_create(name=name, defaults={"specialty": specialty})
        for weekday, (start, end) in schedule.items():
            WorkingHours.objects.get_or_create(
                doctor=doctor, weekday=weekday, defaults={"start_time": start, "end_time": end}
            )


def unseed(apps, schema_editor):
    apps.get_model("scheduling", "Doctor").objects.filter(name__in=[name for name, _, _ in DOCTORS]).delete()


class Migration(migrations.Migration):
    dependencies = [("scheduling", "0001_initial")]

    operations = [migrations.RunPython(seed, unseed)]
