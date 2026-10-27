# CareSlot: clinic booking API

CareSlot is a REST API for a small clinic with 5 doctors. Patients can see a doctor's free 30-minute slots, book one, cancel it, or move it to another time.

Built with Django REST Framework and PostgreSQL. Hosted on Oracle Cloud (OCI).

| | |
| --- | --- |
| Live API (Swagger) | https://careslot.84-13-134-168.sslip.io/docs |
| Health check | https://careslot.84-13-134-168.sslip.io/health |
| Repository | https://github.com/BonifaceNgila/CareSlot |
| AI reflection | [REFLECTION.md](REFLECTION.md) |
| Full report | [submission/SUBMISSION_REPORT.md](submission/SUBMISSION_REPORT.md) |

**Status**

- Done: design, all required endpoints, both bonus features, 43 tests, live HTTPS deployment with demo data.
- Written but not yet run: automatic deployment to OCI when a pull request is merged (see section 4).

---

## 1. System design

### Models

| Model | What it holds |
| --- | --- |
| Doctor | Name, specialty, active flag |
| WorkingHours | One shift per doctor per weekday (start and end time) |
| Patient | Name, optional phone and email |
| Appointment | Doctor, patient, start and end time, status (booked or cancelled), cancel reason |

```text
Doctor 1 --- * WorkingHours
Doctor 1 --- * Appointment * --- 1 Patient
```

### How it works

- **Slots are calculated, not stored.** For a given day, the API takes the doctor's working hours, splits them into 30-minute slots, and removes slots that are already booked. There is no slot table to keep in sync.
- **All booking rules live in one place:** `scheduling/services.py`. Views only read the request and return the response.
- **No double booking.** The database only allows one *booked* appointment per doctor per start time. If two people book the same slot at the same moment, one succeeds and the other gets HTTP 409. A test runs 8 bookings at once against PostgreSQL to prove this.
- **Cancelled appointments are kept** for history. Cancelling frees the slot.
- **Rescheduling** moves the same appointment. If the new slot is invalid, the old booking stays as it was.

### Assumptions

- Clinic time zone is Africa/Nairobi. Times without an offset are read as Nairobi time.
- Slots start at the beginning of each shift. A leftover piece shorter than 30 minutes is dropped.
- One shift per doctor per day. No lunch breaks, holidays or leave.
- Rescheduling keeps the same doctor.
- Bookings need at least 1 hour's notice.
- Started or cancelled appointments cannot be changed.
- A day off or a past date returns an empty list, not an error.
- No login. The API trusts `patient_id`, so only fictional data is used.

### Trade-offs

- **One Django app (monolith):** simple to run and deploy for 5 doctors. Split it only if teams or scale require it.
- **The database rule covers identical start times only.** If slot lengths ever vary, use a PostgreSQL exclusion constraint to block partial overlaps too.
- **Before real use:** add patient login, rate limiting, off-server backups and more than one server.
- **To grow:** add leave/holidays, multiple clinics, and SMS reminders through a task queue.

---

## 2. API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/doctors` | List doctors and their hours |
| GET | `/doctors/{id}/availability?date=YYYY-MM-DD` | Free slots for a day |
| POST | `/patients` | Register a patient |
| POST | `/appointments` | Book a slot |
| GET | `/appointments/{id}` | View an appointment |
| PATCH | `/appointments/{id}/cancel` | Cancel with a reason |
| PATCH | `/appointments/{id}/reschedule` | Move to a new slot |
| GET | `/patients/{id}/appointments` | Bonus: upcoming appointments, soonest first |
| GET | `/health` | App and database check |

Errors always look like this:

```json
{"error": {"code": "slot_unavailable", "message": "This slot is already booked.", "details": null}}
```

- **400:** bad input, or a slot that can never work (past, outside hours, off the 30-minute grid, under 1 hour away)
- **404:** doctor, patient or appointment not found
- **409:** conflict with current data (slot taken, already cancelled, already started)

---

## 3. Run locally

Needs Python 3.12. Uses SQLite, so no database to install.

PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
$env:DJANGO_DEBUG = "1"
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py seed_demo
.\.venv\Scripts\python.exe manage.py runserver
```

Git Bash, macOS or Linux:

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt   # macOS/Linux: .venv/bin/python
export DJANGO_DEBUG=1
.venv/Scripts/python manage.py migrate
.venv/Scripts/python manage.py seed_demo
.venv/Scripts/python manage.py runserver
```

Then open http://127.0.0.1:8000/docs.

**Tests:**

```bash
python manage.py test scheduling
python -m ruff check .
```

On SQLite, the 8-way race test is skipped. To run it, set `DATABASE_URL` to a PostgreSQL database.

**Settings** (environment variables): `DATABASE_URL` (default SQLite), `DJANGO_DEBUG`, `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `CLINIC_TIME_ZONE` (default Africa/Nairobi), `BOOKING_MIN_NOTICE_MINUTES` (default 60).

---

## 4. Deployment and CI/CD

**Hosting:** one Oracle Cloud VM (Riyadh region) running three Docker containers:

- Caddy: HTTPS, with a free Let's Encrypt certificate
- Django: the API, served by Gunicorn
- PostgreSQL 16: the database, not reachable from outside

Only ports 80 and 443 are open. Setup and update steps are in [DEPLOY_OCI.md](DEPLOY_OCI.md).

**Deploy branch:** `main`.

**Pipeline** (`.github/workflows/ci.yml`, GitHub Actions):

1. **On every pull request:** lint, migration check, all tests on PostgreSQL 16, Docker image build.
2. **On merge to `main`:** the same checks, then deploy to OCI:
   - copy the code to the server over SSH (secrets and backups on the server are never touched)
   - run `deploy/oci/deploy.sh`, which builds the image, migrates the database once and restarts the containers
   - check that `/health` on the live site reports the merged commit, and fail if it doesn't

The server's SSH host key is pinned, so the job refuses to connect if the server's identity changes.

**GitHub settings it needs:** secrets `OCI_SSH_KEY` (a deploy-only key) and `OCI_KNOWN_HOSTS`, and variables `OCI_HOST`, `OCI_USER` and `APP_URL`.

**Status:** the pipeline is written. GitHub Actions is currently blocked by a billing issue on the account, so it has not run yet. The live version was deployed by hand with the same `deploy.sh`.

`cloudbuild.yaml` is an alternative setup for Google Cloud Run. It is not used by the live server.

---

## 5. Demo data

The live API has 15 fictional patients and 15 appointments on 28–29 October 2026: 10 booked (5 of them rescheduled) and 5 cancelled.

- [Booked: appointment 1](https://careslot.84-13-134-168.sslip.io/appointments/1)
- [Rescheduled: appointment 2](https://careslot.84-13-134-168.sslip.io/appointments/2)
- [Cancelled: appointment 3](https://careslot.84-13-134-168.sslip.io/appointments/3)
- [Patient 1's upcoming appointments](https://careslot.84-13-134-168.sslip.io/patients/1/appointments)

`python manage.py seed_demo` creates this data through the normal booking rules. Running it again does not create duplicates.

---

## 6. Project layout

```text
config/          Django settings and URLs
scheduling/      the API: models, rules (services.py), views, tests, seed_demo command
deploy/oci/      live server setup: Docker Compose, Caddy, deploy script
submission/      report, checklist, API schema, test evidence
Dockerfile       the API image
```

Older files that are not used: `app/` and `tests/` (first FastAPI version), `docker-compose.yml` and `docker/` (earlier MySQL setup), `render.yaml` (earlier Render setup).
