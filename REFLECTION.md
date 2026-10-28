# Section 4: AI reflection

## 1. What I used AI for

- **Design and API (Sections 1–2):** AI coding assistants (Claude Code and Codex) generated most of the Django code: models, booking rules, views, error handling and tests. I reviewed the design and the booking rules.
- **Deployment (Section 3):** Codex helped prepare the OCI files (Docker Compose, Caddy, deploy script), set up PostgreSQL on the server and check the live endpoints. Claude Code helped switch the project back from MySQL to PostgreSQL and wrote a Google Cloud Build pipeline as an alternative.
- **Demo data:** AI wrote the `seed_demo` command and its tests.
- **Writing (Section 4):** AI helped write the README, the report, the deployment guide and the wording of this reflection. The decisions and examples are mine.

## 2. An AI suggestion that improved my work

My prompt was: *"Do a dummy data for the API"*.

I expected some rows inserted into the database. Instead, the AI wrote a `seed_demo` command that books, cancels and reschedules through the same rules as the real API. It uses clearly fake names and `example.com` emails, and running it twice does not create duplicates. Two tests check it. This gave reviewers realistic examples, including cancelled slots that become free again.

## 3. AI output that was wrong, and how I caught it

The AI wrote a command to check that the database backup could be read. It failed with "input file is too short". The backup was fine; the command was wrong. It ran `pg_restore` inside Docker without passing the file in. Adding `docker exec -i` fixed it, and the backup then listed correctly.

I caught it because the error showed in the command output. The lesson: a backup file existing is not proof it can be restored.

## 4. Two decisions I made without AI

**Hosting on OCI.** I know Oracle Cloud well: its console, networking, public IPs and security rules. With limited time, using a platform I already understand meant fewer unknowns.

**Starting with MySQL.** Doctors, working hours, patients and appointments are related records that must stay consistent, so a relational database with transactions and foreign keys fits. I trusted this because it is a standard, well-understood choice for this kind of data.

The final deployment uses PostgreSQL instead. The rule that stops double booking relies on a feature (a partial unique index) that PostgreSQL supports directly and MySQL does not. A MySQL version would need a different design and its own concurrency tests.
