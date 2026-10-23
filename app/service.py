import sqlite3
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from .database import connection

CLINIC_TZ = timezone(timedelta(hours=3))

def now():
    return datetime.now(timezone.utc)

def doctor(db, doctor_id):
    row = db.execute("SELECT * FROM doctors WHERE id = ?", (doctor_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Doctor not found")
    return row

def appointment(db, appointment_id):
    row = db.execute("SELECT * FROM appointments WHERE id = ?", (appointment_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Appointment not found")
    if row["status"] == "cancelled":
        raise HTTPException(409, "Appointment is already cancelled")
    return row

def validate_slot(doc, starts_at):
    if starts_at.tzinfo is None or starts_at.utcoffset() is None:
        raise HTTPException(422, "starts_at must include a timezone offset")
    local = starts_at.astimezone(CLINIC_TZ)
    if local.weekday() >= 5:
        raise HTTPException(422, "Clinic is open Monday through Friday")
    if local.minute not in (0, 30) or local.second or local.microsecond:
        raise HTTPException(422, "Appointments must start on a 30-minute boundary")
    if not doc["start_hour"] <= local.hour < doc["end_hour"]:
        raise HTTPException(422, "Slot is outside doctor's working hours")
    if starts_at < now() + timedelta(hours=1):
        raise HTTPException(422, "Appointments require at least one hour notice")
    return starts_at.astimezone(timezone.utc).isoformat()

def book(payload):
    try:
        with connection() as db:
            db.execute("BEGIN IMMEDIATE")
            slot = validate_slot(doctor(db, payload.doctor_id), payload.starts_at)
            cursor = db.execute("INSERT INTO appointments (doctor_id, patient_id, starts_at) VALUES (?, ?, ?)",
                                (payload.doctor_id, payload.patient_id, slot))
            return dict(appointment(db, cursor.lastrowid))
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Slot is already booked")

def cancel(appointment_id, reason):
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        appointment(db, appointment_id)
        db.execute("UPDATE appointments SET status = 'cancelled', cancellation_reason = ? WHERE id = ?", (reason, appointment_id))
        return dict(db.execute("SELECT * FROM appointments WHERE id = ?", (appointment_id,)).fetchone())

def reschedule(appointment_id, starts_at):
    try:
        with connection() as db:
            db.execute("BEGIN IMMEDIATE")
            old = appointment(db, appointment_id)
            slot = validate_slot(doctor(db, old["doctor_id"]), starts_at)
            db.execute("UPDATE appointments SET starts_at = ? WHERE id = ?", (slot, appointment_id))
            return dict(appointment(db, appointment_id))
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Slot is already booked")

def availability(doctor_id, day):
    with connection() as db:
        doc = doctor(db, doctor_id)
        occupied = {r[0] for r in db.execute("SELECT starts_at FROM appointments WHERE doctor_id = ? AND status = 'booked'", (doctor_id,))}
    slots = []
    if day.weekday() < 5:
        start = datetime(day.year, day.month, day.day, doc["start_hour"], tzinfo=CLINIC_TZ)
        for index in range((doc["end_hour"] - doc["start_hour"]) * 2):
            slot = start + timedelta(minutes=30 * index)
            if slot >= now() + timedelta(hours=1) and slot.astimezone(timezone.utc).isoformat() not in occupied:
                slots.append(slot.isoformat())
    return {"doctor_id": doctor_id, "date": day.isoformat(), "timezone": "Africa/Nairobi", "slots": slots}
