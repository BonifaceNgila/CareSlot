import os
import sqlite3
from contextlib import contextmanager

DB_PATH = os.getenv("DATABASE_PATH", "careslot.db")

@contextmanager
def connection():
    db = sqlite3.connect(DB_PATH, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def initialize():
    with connection() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS doctors (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL,
            start_hour INTEGER NOT NULL, end_hour INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doctor_id INTEGER NOT NULL REFERENCES doctors(id),
            patient_id INTEGER NOT NULL CHECK(patient_id > 0),
            starts_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'booked' CHECK(status IN ('booked', 'cancelled')),
            cancellation_reason TEXT
        );
        CREATE UNIQUE INDEX IF NOT EXISTS active_doctor_slot
            ON appointments(doctor_id, starts_at) WHERE status = 'booked';
        """)
        db.executemany("INSERT OR IGNORE INTO doctors VALUES (?, ?, 9, 17)",
                       [(i, f"Doctor {i}") for i in range(1, 6)])
