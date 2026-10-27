# CareSlot: clinic booking API

**OCI deployment (prepared, not deployed):** see [DEPLOY_OCI.md](DEPLOY_OCI.md)
for the Compute VM setup, HTTPS, PostgreSQL, and deployment commands.

**IBM Cloud deployment:** see [DEPLOY_IBM.md](DEPLOY_IBM.md) for Code Engine setup,
PostgreSQL secrets, database migrations, and deployment verification.

A REST API for a small clinic: patients see a doctor's free 30-minute slots for a day, book one, cancel it, or move it. Built with **Django 5.2 + Django REST Framework** and **PostgreSQL** (Neon), deployed on **Google Cloud Run** by **Google Cloud Build**.

| | |
|---|---|
| **Live API** | `https://careslot-api-<hash>.europe-west1.run.app` ← _replace after first deploy_ |
| **Interactive docs** | `<live URL>/docs` (Swagger UI), raw schema at `/schema` |
| **Health** | `<live URL>/health` |
| **Deploy branch** | `main` (merge a PR → tests → deploy) |
| **AI reflection** | [REFLECTION.md](REFLECTION.md) |

> Cloud Run scales to zero when idle, so the first request after a quiet spell takes a few seconds longer.

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

Git Bash, macOS or Linux:

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt   # macOS/Linux: .venv/bin/python
export DJANGO_DEBUG=1
.venv/Scripts/python manage.py migrate
.venv/Scripts/python manage.py runserver
```

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
| `DATABASE_URL` | SQLite file `db.sqlite3` | Any `dj-database-url` URL; PostgreSQL in CI and production (from Secret Manager) |
| `DJANGO_DEBUG` | `0` | Set `1` locally |
| `DJANGO_SECRET_KEY` | insecure dev key | From Secret Manager in production |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | On Cloud Run (`K_SERVICE` set), `*.run.app` is added automatically |
| `GIT_COMMIT` | `local` | Set by the pipeline; reported by `/health` |
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
Dockerfile, cloudbuild.yaml
```

---

## 4. Deployment and CI/CD

**Platform:**
- **Google Cloud Run** (`europe-west1`) runs the Docker image: Gunicorn with 2 workers, static files served by WhiteNoise, scale 0–2 instances.
- **Neon** provides serverless PostgreSQL.
- `DATABASE_URL` and `DJANGO_SECRET_KEY` live in **Secret Manager**, never in the repo or the build config.

Everything fits in the free tiers at this traffic level. Cloud SQL was ruled out because it has no free tier.

**Pipeline** ([`cloudbuild.yaml`](cloudbuild.yaml), Google Cloud Build, connected to the GitHub repo):

| Trigger | Steps |
|---|---|
| Pull request into `main` (`careslot-pr`) | **test**: ruff lint and format check, then `makemigrations --check` (catches model changes without a migration), then the full test suite against a throwaway **PostgreSQL 16** container (same engine as production, so the real race test runs). **build**: builds the production image in parallel, so a broken Dockerfile fails the PR rather than the deploy. |
| Push to `main`, i.e. a merged PR (`careslot-deploy`, sets `_DEPLOY=true`) | The same test and build steps on the merged result, then: **push** the image to Artifact Registry, **migrate** the production database once from the new image, **deploy** to Cloud Run, and **verify** by polling `/health` until it reports the merged commit SHA. |

**Why migrate in the pipeline, not on container start:** Cloud Run can start several instances at once, and each would try to migrate. Running migrations once, before the new revision takes traffic, avoids that. A failed migration also stops the deploy, so the old revision keeps serving.

**Why `verify`:** a finished `gcloud run deploy` doesn't prove the new revision can reach its database. `/health` checks the database and reports the deployed commit, so a broken release fails the pipeline instead of showing green.

**Branch that deploys:** `main`. Code reaches production only through a green Cloud Build run. In GitHub, protect `main` (Settings → Branches) so merging requires the `careslot-pr` check to pass.

### One-time setup

You need a Google Cloud project with billing enabled and the [gcloud CLI](https://cloud.google.com/sdk/docs/install). Cloud Run, Cloud Build, Artifact Registry, and Secret Manager usage at this scale can fit their free tiers; Neon has its own plan limits. Check current pricing and add a budget alert before deploying.

1. **Create the Neon database.** Create a project in an EU region and copy its direct (not pooled) PostgreSQL connection string. It should include `sslmode=require`, for example `postgresql://user:pass@ep-xxx.eu-central-1.aws.neon.tech/neondb?sslmode=require`. Keep this string private; it grants database access.

2. **Set up Google Cloud.** Replace `your-project-id` below. Run these commands in a shell with `gcloud` authenticated to an account that can enable APIs, create service accounts and repositories, create secrets, and grant IAM roles. The `gcloud projects add-iam-policy-binding` commands grant project-wide roles, so review them against your organization's access policy.

   ```bash
   PROJECT_ID=your-project-id
   REGION=europe-west1
   gcloud config set project "$PROJECT_ID"
   gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
       artifactregistry.googleapis.com secretmanager.googleapis.com
   gcloud artifacts repositories create careslot --repository-format=docker --location="$REGION"

   # Paste the Neon URL when prompted; it is not saved in this command history.
   read -rsp 'Neon DATABASE_URL: ' DATABASE_URL; echo
   printf '%s' "$DATABASE_URL" | gcloud secrets create careslot-database-url --data-file=-
   unset DATABASE_URL
   python -c "import secrets; print(secrets.token_urlsafe(50), end='')" | gcloud secrets create careslot-secret-key --data-file=-

   # Cloud Build trigger identity. It pushes images, deploys Cloud Run, and reads the DB secret for migrations.
   gcloud iam service-accounts create careslot-deployer --display-name='CareSlot Cloud Build deployer'
   SA="careslot-deployer@$PROJECT_ID.iam.gserviceaccount.com"
   gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$SA" --role=roles/run.admin
   gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$SA" --role=roles/artifactregistry.writer
   gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$SA" --role=roles/artifactregistry.reader
   gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$SA" --role=roles/secretmanager.secretAccessor
   gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$SA" --role=roles/logging.logWriter
   gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$SA" --role=roles/iam.serviceAccountUser

   # Cloud Run runtime identity reads the two secrets. This uses the default Compute Engine service account.
   PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
   RUNTIME_SA="$PROJECT_NUMBER-compute@developer.gserviceaccount.com"
   gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$RUNTIME_SA" --role=roles/secretmanager.secretAccessor

   # Let Cloud Build use the trigger identity (required for builds that specify a custom service account).
   BUILD_SA="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')@cloudbuild.gserviceaccount.com"
   gcloud iam service-accounts add-iam-policy-binding "$SA" \
       --member="serviceAccount:$BUILD_SA" --role=roles/iam.serviceAccountUser
   ```

   If `gcloud artifacts repositories create` or service-account creation says the resource already exists, verify it is the intended resource and continue. Do not paste the Neon connection string into a source file or commit it.

3. **Connect the repository and make the triggers.** In Google Cloud Console, open **Cloud Build → Repositories** and connect the GitHub repository using the Cloud Build GitHub App. Then open **Cloud Build → Triggers → Create trigger**. For both triggers choose the connected repository, `cloudbuild.yaml` as the build configuration, and `careslot-deployer` as the service account. Configure:

   | Name | Event | Branch filter | Substitution |
   |---|---|---|---|
   | `careslot-pr` | Pull request | base branch `^main$` | none |
   | `careslot-deploy` | Push to a branch | `^main$` | `_DEPLOY` = `true` |

   Set the PR trigger to **comment control disabled** if the repository is private and you want every PR to build automatically. The first deploy trigger will only have a commit to build after the Cloud Build connection is active and the configured branch exists.

4. **Run the first deploy.** In **Cloud Build → Triggers**, use **Run** on `careslot-deploy` and select the `main` branch. A green build means lint, migrations check, PostgreSQL tests, image build/push, database migration, Cloud Run deployment, and `/health` verification all completed. Open the build's `verify` log and copy the printed `https://...run.app` URL into the Live API row at the top of this README. Then check `<URL>/docs` and `<URL>/health` in a browser.

   Afterward, protect `main` in GitHub branch protection and require the Cloud Build PR check before merging. A pull request build cannot deploy; only the deploy trigger's `_DEPLOY=true` substitution enables deployment steps.

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
| Migrations run in the pipeline before deploy, not on container start | Instances never race on migrations; a failed migration blocks the deploy | Migrations must stay backward-compatible with the previous revision (expand, then contract), because the old revision serves traffic until the new one is ready |
| Cloud Run + Neon free tiers | Zero cost for an assessment; scales to zero | Cold starts and Neon's auto-suspend add latency after idle periods. For real use: `--min-instances=1`, a paid database plan with backups, or Cloud SQL in the same region to cut network latency |
| No auth | Out of scope | Patients log in (OTP via phone is typical in Kenya); `patient_id` comes from the token, never the body; staff roles for admin. Add rate limiting on booking. |
| Sync request/response only | Nothing slow happens on booking | Reminders (SMS/WhatsApp), notifications to doctors and waitlists go to a task queue (Celery/RQ) triggered from the service layer |

**Other growth points the design already allows:** multiple clinics/branches (add `Clinic` FK on Doctor, time zone per clinic); leave/holidays (a `ScheduleException` table subtracted in `slots_for_day`); visit types with different durations (`end_at` is already stored); per-doctor slot length (move `SLOT_MINUTES` onto Doctor); an audit trail (already have `created_at`/`updated_at`/`cancelled_at`; add an event table if needed).
