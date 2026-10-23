from contextlib import asynccontextmanager
from datetime import date
from fastapi import FastAPI, Path
from . import database, service
from .schemas import Booking, Cancellation, Reschedule

@asynccontextmanager
async def lifespan(app):
    database.initialize()
    yield

app = FastAPI(title="CareSlot API", version="0.1.0", lifespan=lifespan)

@app.get("/health")
def health():
    with database.connection() as db:
        db.execute("SELECT 1")
    return {"status": "ok"}

@app.get("/doctors")
def doctors():
    with database.connection() as db:
        return [dict(row) for row in db.execute("SELECT * FROM doctors ORDER BY id")]

@app.get("/doctors/{doctor_id}/availability")
def availability(date: date, doctor_id: int = Path(gt=0)):
    return service.availability(doctor_id, date)

@app.post("/appointments", status_code=201)
def book(payload: Booking):
    return service.book(payload)

@app.patch("/appointments/{appointment_id}/cancel")
def cancel(payload: Cancellation, appointment_id: int = Path(gt=0)):
    return service.cancel(appointment_id, payload.reason)

@app.patch("/appointments/{appointment_id}/reschedule")
def reschedule(payload: Reschedule, appointment_id: int = Path(gt=0)):
    return service.reschedule(appointment_id, payload.starts_at)

@app.get("/patients/{patient_id}/appointments")
def patient_appointments(patient_id: int = Path(gt=0)):
    with database.connection() as db:
        return [dict(row) for row in db.execute(
            "SELECT * FROM appointments WHERE patient_id = ? AND status = 'booked' AND starts_at > ? ORDER BY starts_at",
            (patient_id, service.now().isoformat()))]
