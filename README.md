# CareSlot: clinic booking API

A REST API for a small clinic: patients see a doctor's free 30-minute slots for a day, book one, cancel it, or move it. Built with **Django 5.2 + Django REST Framework**, **PostgreSQL** in production, deployed on **Render** by **GitHub Actions**.

| | |
|---|---|
| **Live API** | `https://<your-service>.onrender.com` ← _replace after first deploy_ |
| **Interactive docs** | `<live URL>/docs` (Swagger UI), raw schema at `/schema` |
| **Health** | `<live URL>/health` |
| **Deploy branch** | `main` (merge a PR → tests → deploy) |
| **AI reflection** | [REFLECTION.md](REFLECTION.md) |

> Render's free tier sleeps after ~15 minutes idle, so the first request can take up to a minute.

---

## Contents

1. [System design](#1-system-design)
2. [API](#2-api)
3. [Running locally](#3-running-locally)
4. [Deployment and CI/CD](#4-deployment-and-cicd)
5. [Assumptions I made](#5-assumptions-i-made)
6. [Trade-offs and how this grows](#6-trade-offs-and-how-this-grows)

---

## 1. System design

### Requirements, restated

- 5 doctors, each with **their own** working hours, seeing patients in **30-minute slots**.
- A patient can list a doctor's free slots on a date, book one, cancel (with a reason), and reschedule.
- A booked slot must **never** be handed to two patients, even when two requests arrive at the same moment.
- "Starting small but want to grow": stay simple now, but don't paint ourselves into a corner.

### Models

```
Doctor 1───* WorkingHours            Patient
   │         weekday 0–6                │
   │         start_time, end_time       │
   │                                    │
   └──────────* Appointment *───────────┘
                start_at, end_at (UTC)
                status: booked | cancelled
                cancellation_reason, cancelled_at
                created_at, updated_at
```

| Model | Why it exists |
|---|---|
| **Doctor** | Name, specialty, `is_active` (to retire a doctor without deleting their history). |
| **WorkingHours** | One row per doctor per weekday. Hours vary by doctor *and* by day (one doctor works Saturdays, another only Tue/Thu). Clinic staff manage these in Django admin; no code change or deploy needed. |
| **Patient** | Minimal (name, phone, email). Needed so `/patients/{id}/appointments` and "a patient can't be in two places at once" have something to hang off. |
| **Appointment** | The booking. Stores `end_at` as well as `start_at` so overlap checks are a simple range query and slot length can change later without rewriting history. |

**Slots are computed, not stored.** No `Slot` table: a doctor's slots for a day are generated from their `WorkingHours`, then booked appointments are subtracted. A stored slot table would need a job to generate future rows, would go stale whenever hours change, and multiplies rows (5 doctors × 16 slots × 365 days) for no benefit at this size.

**Cancelled appointments are kept** (status `cancelled` + reason + timestamp), not deleted. It's a clinic, so history matters for no-show analysis, audits and disputes.

### Components

```
HTTP ─► urls ─► views (DRF APIView) ─► services ─► models / PostgreSQL
                  │ parse + validate shape      │ all booking rules
                  │ render response             │ transactions, locking
                  ▼                             ▼
            serializers                    exceptions ─► one JSON error envelope
```

- **`scheduling/services.py`**: every rule lives here: slot generation, working-hours validation, notice period, clash detection, the cancel/reschedule state machine. Views never decide anything. That makes the rules unit-testable and reusable (admin actions, a future SMS-reminder worker, etc.).
- **`scheduling/views.py`**: thin: validate input shape with a serializer → call one service function → serialize the result.
- **`scheduling/exceptions.py`**: domain errors (`SlotValidationError` → 400, `NotFoundError` → 404, `ConflictError` → 409) and a DRF exception handler that gives **every** error the same shape, including DRF's own validation errors and unknown URLs.
- **Django admin** (`/admin`): back-office for clinic staff to manage doctors, working hours and patients. Appointments are **read-only** in admin, so every booking goes through the same rules.

### Key decision: how double-booking is prevented

This is the one place where "probably fine" is not fine. There are two layers:

1. **Application check** (`_ensure_free`): inside a transaction, look for any *booked* appointment that **overlaps** the requested range for that doctor (and for that patient). This gives clear error messages (`slot_unavailable` vs `patient_double_booked`).
2. **Database guarantee**: a **partial unique index** `UNIQUE (doctor_id, start_at) WHERE status = 'booked'`. Two concurrent requests can both pass step 1, but only one INSERT can succeed; the loser's `IntegrityError` is translated to the same `409 slot_unavailable`.

The partial index (rather than plain `UNIQUE(doctor_id, start_at)`) is what makes cancellation work: a cancelled row no longer occupies the slot, so it becomes bookable again while the cancelled row stays for history.

Why not `SELECT … FOR UPDATE` on the doctor row, or a serializable transaction? Both work, but they serialize *all* bookings for a doctor, and each new code path has to remember to take the lock. The constraint protects every write path, including ones not written yet, and costs nothing when there's no contention. This is tested with 8 threads racing for one slot against real PostgreSQL in CI (`test_concurrency.py`), plus a deterministic test that bypasses the pre-check to prove the constraint alone holds.

**Rescheduling** updates the existing row in place inside one transaction (with `SELECT … FOR UPDATE` on that appointment, so a concurrent cancel and reschedule can't interleave). Releasing the old slot and taking the new one is therefore atomic: if the new slot is invalid or taken, nothing changes and the patient keeps their original slot. The appointment keeps its id, so references to it stay valid.

### Time zones

The clinic runs on **Africa/Nairobi** (`TIME_ZONE`, configurable). Times are stored in UTC (`USE_TZ=True`); working hours are wall-clock times in the clinic zone; API responses are rendered with a `+03:00` offset. Input with any offset is accepted (`06:00Z` and `09:00+03:00` are the same slot, and that's tested). Input **without** an offset is read as clinic local time, because that's what a patient typing "9am" means.

---

## 2. API

All endpoints are JSON. Full interactive docs at `/docs`.

| Method | Path | Purpose | Success |
|---|---|---|---|
| `GET` | `/doctors` | Doctors with their weekly hours | 200 |
| `GET` | `/doctors/{id}/availability?date=YYYY-MM-DD` | Free slots for that doctor on that date | 200 |
| `POST` | `/patients` | Register a patient `{name, phone?, email?}` | 201 |
| `POST` | `/appointments` | Book `{doctor_id, patient_id, start_at}` | 201 |
| `GET` | `/appointments/{id}` | One appointment | 200 |
| `PATCH` | `/appointments/{id}/cancel` | Cancel `{reason}` | 200 |
| `PATCH` | `/appointments/{id}/reschedule` | Move `{start_at}` (same doctor) | 200 |
| `GET` | `/patients/{id}/appointments` | **Bonus:** upcoming booked appointments, soonest first | 200 |
| `GET` | `/health` | Liveness + DB check + deployed commit | 200 / 503 |

**Bonus rule implemented:** bookings must be at least **1 hour** ahead (`BOOKING_MIN_NOTICE_MINUTES`, default 60). Slots inside that window are also hidden from availability.

### Example

```bash
curl -X POST $URL/patients -H 'Content-Type: application/json' -d '{"name": "Jane Doe"}'
curl "$URL/doctors/2/availability?date=2026-10-26"
curl -X POST $URL/appointments -H 'Content-Type: application/json' \
     -d '{"doctor_id": 2, "patient_id": 1, "start_at": "2026-10-26T10:00:00+03:00"}'
curl -X PATCH $URL/appointments/1/reschedule -H 'Content-Type: application/json' -d '{"start_at": "2026-10-26T11:30:00+03:00"}'
curl -X PATCH $URL/appointments/1/cancel -H 'Content-Type: application/json' -d '{"reason": "Feeling better"}'
```

### Errors

Every error has the same envelope, so clients can branch on `code` and show `message`:

```json
{"error": {"code": "outside_working_hours",
           "message": "18:00 is outside Dr. Brian Mwangi's working hours on Monday (09:00-17:00, last slot starts 16:30).",
           "details": null}}
```

| Status | When | `code` |
|---|---|---|
| **400** | Malformed body or query (per-field messages in `details`) | `validation_error` |
| **400** | Time is in the past / under 1 h away | `slot_in_past`, `insufficient_notice` |
| **400** | Doctor not working then, or slot runs past end of shift | `outside_working_hours` |
| **400** | Not on the 30-minute grid (e.g. 09:15) | `invalid_slot_boundary` |
| **400** | Reschedule to the slot it's already in | `same_slot` |
| **404** | Unknown doctor / patient / appointment / route | `doctor_not_found`, `patient_not_found`, `appointment_not_found`, `not_found` |
| **409** | Slot already booked (including a lost race) | `slot_unavailable` |
| **409** | Patient already has an overlapping appointment | `patient_double_booked` |
| **409** | Cancel/reschedule an already-cancelled appointment | `appointment_cancelled` |
| **409** | Cancel/reschedule an appointment that has already started | `appointment_started` |

**400 vs 409:** 400 means "this request could never succeed as written"; 409 means "the request is fine, but the current state of the world prevents it" (retrying with another slot, or later, could work). I used 400 rather than 422 for rule violations because that's DRF's convention and keeps one status for "fix your input". 404 is used for an unknown `doctor_id`/`patient_id` in a POST body too, since the referenced resource doesn't exist.

---

## 3. Running locally

Needs Python 3.12. Uses SQLite by default, so there's nothing else to install.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
$env:DJANGO_DEBUG = "1"
.\.venv\Scripts\python.exe manage.py migrate        # creates tables + seeds the 5 doctors
.\.venv\Scripts\python.exe manage.py runserver      # http://127.0.0.1:8000/docs
```

(macOS/Linux: `source .venv/bin/activate`, `export DJANGO_DEBUG=1`.)

Optional, for clinic-staff admin at `/admin`: `python manage.py createsuperuser`.

**Tests and lint**

```powershell
.\.venv\Scripts\python.exe manage.py test scheduling
.\.venv\Scripts\python.exe -m ruff check . ; .\.venv\Scripts\python.exe -m ruff format --check .
```

41 tests cover: booking happy path, every rejection reason, time-zone equivalence, naive-time handling, cross-doctor and same-patient clashes, cancel → slot reopens, double cancel, reschedule frees the old slot and leaves it untouched on failure, availability (shape, booked/notice filtering, days off, hours changed after booking), the patient listing, the error envelope, and the DB constraint under a simulated race. Tests pin the clock (`services.now`) so they never depend on today's date.

The real multi-threaded race test needs PostgreSQL (SQLite serializes writers, so it would prove nothing) and is skipped on SQLite. To run it locally:

```powershell
docker run -d --name careslot-pg -e POSTGRES_USER=careslot -e POSTGRES_PASSWORD=careslot -p 5432:5432 postgres:16
$env:DATABASE_URL = "postgres://careslot:careslot@localhost:5432/careslot"
.\.venv\Scripts\python.exe manage.py test scheduling
```

**Configuration** (environment variables)

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | SQLite file `db.sqlite3` | Any `dj-database-url` URL; Postgres in prod/CI |
| `DJANGO_DEBUG` | `0` | Set `1` locally |
| `DJANGO_SECRET_KEY` | insecure dev key | Generated by Render in production |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Render's hostname is added automatically |
| `CLINIC_TIME_ZONE` | `Africa/Nairobi` | |
| `BOOKING_MIN_NOTICE_MINUTES` | `60` | |

### Project layout

```
config/                 settings, root urls, wsgi
scheduling/
  models.py             Doctor, WorkingHours, Patient, Appointment (+ partial unique index)
  services.py           booking rules, transactions
  views.py, urls.py     thin HTTP layer
  serializers.py        request/response shapes
  exceptions.py         domain errors + uniform error envelope
  middleware.py         /health (answered before host validation)
  admin.py              back-office for clinic staff
  migrations/0002_…     seeds the 5 doctors and their hours
  tests/                API, rule and concurrency tests
Dockerfile, render.yaml, .github/workflows/ci.yml
```

---

## 4. Deployment and CI/CD

**Platform:** Render. One Docker web service (Gunicorn, 2 workers, static files via WhiteNoise) + one managed PostgreSQL, both declared in [`render.yaml`](render.yaml). The container runs `migrate` then starts Gunicorn.

**Pipeline** ([`.github/workflows/ci.yml`](.github/workflows/ci.yml), GitHub Actions):

| Trigger | Jobs |
|---|---|
| Pull request into `main` | **test**: ruff lint + format check → `makemigrations --check` (catches model changes without a migration) → full test suite against a **PostgreSQL 16** service container (same engine as prod, so the race test runs). **docker**: builds the production image so a broken Dockerfile fails the PR, not the deploy. |
| Push to `main` (i.e. a merged PR) | test + docker again on the merged result, then **deploy**: calls the Render deploy hook, then polls `/health` until it reports the merged commit SHA, failing the job if it's not live within 15 minutes. |

Render's own auto-deploy is **off** (`autoDeployTrigger: "off"`), so the only way code reaches production is through green CI. The final `/health` poll matters because a deploy hook only confirms Render *accepted* the request, not that the new version booted. Without it a broken release would show a green pipeline.

**Branch that deploys:** `main`. Protect it (Settings → Branches) so merging requires the `Lint & test (PostgreSQL)` and `Build image` checks to pass.

### One-time setup

1. Push the repo to GitHub.
2. Render → **New → Blueprint** → select the repo. It creates `careslot-api` and `careslot-db` from `render.yaml`, then does the first deploy.
3. Render service → Settings → **Deploy Hook**: copy the URL into GitHub → Settings → Secrets and variables → Actions → **secret** `RENDER_DEPLOY_HOOK`.
4. In the same place add a **variable** `APP_URL` = the service URL (e.g. `https://careslot-api.onrender.com`). This enables the post-deploy live check.
5. Put the URL in the table at the top of this README.

---

## 5. Assumptions I made

Where the brief was ambiguous, I made these calls:

- **Slot grid starts at each doctor's shift start** and runs every 30 min; a trailing partial slot (e.g. a shift ending at 16:45) is dropped. A booking must be exactly on the grid.
- **One shift per doctor per weekday**, no lunch breaks, holidays or leave. (The model allows adding these; see below.)
- **Rescheduling keeps the same doctor.** Changing doctor is effectively a new booking, so cancel and book.
- **Appointments that have already started can't be cancelled or rescheduled** (409). A past appointment is a matter of record (attended / no-show), not something a patient should be able to edit.
- **A patient can't hold two overlapping appointments**, even with different doctors.
- **"Upcoming" means start time is in the future and status is booked**; cancelled and started appointments are excluded.
- **Availability for a past date or a day off is an empty list, not an error.** The question "what's free?" has a valid answer: nothing.
- **No authentication.** The brief doesn't ask for it; `patient_id` is trusted. This is the first thing to change before real use (see below).
- **Patients self-register** via `POST /patients`; doctors are seeded by a migration and managed in admin.

---

## 6. Trade-offs and how this grows

| Choice now | Why | When it changes |
|---|---|---|
| Computed slots, no slot table | Always consistent with current hours, nothing to keep in sync | Probably never; even 100 doctors is cheap to compute per request |
| Partial unique index on `(doctor, start_at)` | Simple, portable (Postgres and SQLite), race-proof for a fixed grid | If slot lengths start to vary per doctor/visit type, swap it for a PostgreSQL **exclusion constraint** on `tstzrange(start_at, end_at)` (`btree_gist`), which also prevents *partial* overlaps at the DB level. Today partial overlaps (only possible if hours are changed to a new grid) are caught by the application-level overlap check, which is tested. |
| Patient clash check is application-level only | Rare, and a race needs the same patient double-submitting | Add an exclusion constraint per patient if it ever matters |
| Monolith, one Django app | 5 doctors; a service split would be cost with no benefit | Split by domain (scheduling / patients / billing) only when teams or scaling needs differ |
| Migrations run on container start | Render free plan has no pre-deploy command | With >1 instance, move to a `preDeployCommand` (paid) or a release job, so instances don't race on migrations |
| Render free tier | Zero cost for an assessment | Free Postgres is time-limited and the service sleeps; a paid instance + backups for real use |
| No auth | Out of scope | Patients log in (OTP via phone is typical in Kenya); `patient_id` comes from the token, never the body; staff roles for admin. Add rate limiting on booking. |
| Sync request/response only | Nothing slow happens on booking | Reminders (SMS/WhatsApp), notifications to doctors and waitlists go to a task queue (Celery/RQ) triggered from the service layer |

**Other growth points the design already allows:** multiple clinics/branches (add `Clinic` FK on Doctor, time zone per clinic); leave/holidays (a `ScheduleException` table subtracted in `slots_for_day`); visit types with different durations (`end_at` is already stored); per-doctor slot length (move `SLOT_MINUTES` onto Doctor); an audit trail (already have `created_at`/`updated_at`/`cancelled_at`; add an event table if needed).
