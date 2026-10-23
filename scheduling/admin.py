from django.contrib import admin

from .models import Appointment, Doctor, Patient, WorkingHours


class WorkingHoursInline(admin.TabularInline):
    model = WorkingHours
    extra = 0


@admin.register(Doctor)
class DoctorAdmin(admin.ModelAdmin):
    list_display = ["id", "name", "specialty", "is_active"]
    list_filter = ["is_active", "specialty"]
    inlines = [WorkingHoursInline]


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ["id", "name", "phone", "email", "created_at"]
    search_fields = ["name", "phone", "email"]


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ["id", "doctor", "patient", "start_at", "status"]
    list_filter = ["status", "doctor"]
    date_hierarchy = "start_at"
    # Edits go through the API so booking rules are always enforced.
    readonly_fields = [field.name for field in Appointment._meta.fields]

    def has_add_permission(self, request):
        return False
