# Deploying CareSlot on Oracle Cloud (OCI)

## What is running now

- **URL:** https://careslot.84-13-134-168.sslip.io/docs
- **Server:** OCI VM in Riyadh, ARM64, 4 GB RAM, Ubuntu 20.04. App folder: `/home/ubuntu/CareSlot`
- **Containers:** Caddy (HTTPS), Django API (Gunicorn), PostgreSQL 16
- **Open ports:** 80 and 443 only. The database is not reachable from outside.
- **Secrets:** stored on the server in `deploy/oci/.env`, never in Git.

Good to know:

- The IP address is temporary. If OCI changes it, the `sslip.io` address changes too. A reserved IP and your own domain avoid this.
- Ubuntu 20.04 is old. Upgrade to 24.04 before real use.
- This is one server with no automatic failover.

## Set up a new server

1. **Create a VM:** Ubuntu 24.04, at least 2 GB RAM (4 GB is better). ARM or x86 both work.
2. **Open ports:** in the OCI security list, allow TCP 80 and 443 from anywhere, and TCP 22 from your own IP only. Do not open 5432 or 8080.
3. **Domain:** point a domain name (e.g. `api.example.com`) to the VM's public IP. HTTPS needs it.
4. **Install:** Git, Python 3 and Docker with the Compose plugin. Follow [Docker's Ubuntu guide](https://docs.docker.com/engine/install/ubuntu/).

## Deploy the app

On your computer, package the code and copy it to the server:

```powershell
tar -czf careslot-source.tar.gz --exclude=.git --exclude=.venv* --exclude=__pycache__ --exclude=*.sqlite3 --exclude=.env* --exclude=backups --exclude=*.tar.gz .
scp -i C:\path\to\oci.key careslot-source.tar.gz ubuntu@VM_PUBLIC_IP:~/
```

On the server:

```bash
mkdir -p ~/CareSlot
tar -xzf ~/careslot-source.tar.gz -C ~/CareSlot
cd ~/CareSlot
python3 deploy/oci/init_env.py api.example.com   # first time only: creates secrets
sudo bash deploy/oci/deploy.sh
```

`deploy.sh` builds the image, runs database migrations, restarts the containers and checks `/health` over HTTPS. If a migration fails, it stops before replacing the API. It does not roll back automatically.

**Updates:** copy the new code the same way, but do **not** run `init_env.py` again. Keep the existing `.env`. Then run `deploy.sh` again.

## Everyday commands

Run these in `~/CareSlot/deploy/oci`:

```bash
export RELEASE_TAG=operations
sudo --preserve-env=RELEASE_TAG docker compose ps                     # status
sudo --preserve-env=RELEASE_TAG docker compose logs --tail=100 api     # API logs
sudo docker exec careslot-oci-api-1 python manage.py seed_demo         # add demo data
```

**Back up the database** (do this before every migration):

```bash
umask 077; mkdir -p backups
sudo --preserve-env=RELEASE_TAG docker compose exec -T db pg_dump -U careslot -d careslot -Fc > "backups/careslot-$(date -u +%Y%m%d%H%M%S).dump"
```

Copy backups off the server. A backup is only proven once you have restored it somewhere.

**Never run** `docker compose down -v`. It deletes the database and the HTTPS certificates.

## If something breaks

- **No HTTPS certificate:** check the domain points to the right IP, and that ports 80 and 443 are open in OCI and on the VM firewall.
- **API errors:** check the `api` and `db` logs.
