# CareSlot on Oracle Cloud Infrastructure

Status: deployment files prepared; no OCI account, resources, or live endpoint created.

This setup runs Django/Gunicorn, PostgreSQL 16, and Caddy on one Ubuntu Compute VM.
Caddy obtains HTTPS certificates and proxies to the API. Only ports 80/443 are
published; PostgreSQL and Gunicorn stay on the Compose network. Database files and
certificates live in named Docker volumes and survive container replacement.
This is a single-server deployment, without automatic failover.

## When the account is ready

1. Create an Ubuntu 24.04 LTS Compute instance with at least 2 GB RAM (4 GB is
   preferable for image builds and PostgreSQL). Either ARM Ampere A1 or x86 works:
   the image builds natively on the VM. Check current shape eligibility, regional
   capacity, storage limits, and the displayed cost before creating resources;
   this setup does not guarantee free hosting. See
   [OCI Always Free resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm).
2. Use a public subnet with an internet gateway, a default route to that gateway,
   and a public IPv4 address. Configure a security list or NSG to allow inbound
   TCP 80 and 443 from the internet, and TCP 22 only from your own public IP.
   Match these rules in the VM's existing host firewall; keep SSH allowed before
   editing firewall rules. Do not expose 5432 or 8080. Outbound DNS, HTTPS and
   certificate validation must work. See
   [OCI instance creation](https://docs.oracle.com/en-us/iaas/Content/Compute/Tasks/launchinginstance.htm)
   and [security rules](https://docs.oracle.com/en-us/iaas/Content/Network/Concepts/securityrules.htm).
3. Point a DNS hostname you control, such as `api.example.com`, to the VM public
   IPv4 address. Remove stale AAAA records unless IPv6 is configured. A hostname
   is required by this setup for trusted HTTPS; it is not provisioned for you.
4. SSH to the VM using its private key and the `ubuntu` user. Install Git, Python 3,
   `flock` (util-linux), and Docker Engine with the Compose plugin using
   [Docker's Ubuntu installation instructions](https://docs.docker.com/engine/install/ubuntu/).
   Confirm `sudo docker compose version` works. No OCI CLI or registry is needed.

## Transfer the current application

The local working tree contains uncommitted changes. A clone of GitHub alone will
not include them. From PowerShell in `C:\projects\CareSlot`, create a source bundle:

```powershell
tar -czf careslot-source.tar.gz --exclude=.git --exclude=.venv --exclude=.venv-django --exclude=.venv-* --exclude=__pycache__ --exclude=.pytest_cache --exclude=.ruff_cache --exclude=*.sqlite3 --exclude=*.db --exclude=staticfiles --exclude=.env --exclude=.env.* --exclude=backups --exclude=*.tar.gz .
scp -i C:\path\to\oci.key careslot-source.tar.gz ubuntu@VM_PUBLIC_IP:~/
```

Keep private credentials outside the repository. The source bundle excludes local
environment files and databases. On the VM:

```bash
mkdir -p ~/CareSlot
tar -xzf ~/careslot-source.tar.gz -C ~/CareSlot
cd ~/CareSlot
python3 deploy/oci/init_env.py api.example.com
sudo bash deploy/oci/deploy.sh
```

The initializer creates `deploy/oci/.env` with fresh random secrets and restrictive
permissions. It refuses to overwrite an existing file. Back it up privately;
keep the same database password and Django key on later releases. Changing the
environment password alone does not change an initialized PostgreSQL user's password.

The deploy script builds an image, waits for PostgreSQL, runs migrations once, then
updates the API and proxy. It verifies the public HTTPS `/health` response against
the release identifier. First certificate issuance can take a few minutes. Open:

- `https://api.example.com/docs`
- `https://api.example.com/health`
- `https://api.example.com/admin` (optional staff account below)

For a transferred source bundle without Git metadata, the script uses `source-bundle`
as the source identifier; its printed image tag uniquely identifies that build.

## Operations

Run these from `~/CareSlot/deploy/oci`. The following commands need a release tag
only to satisfy Compose interpolation; they operate on the running services.

```bash
export RELEASE_TAG=operations
sudo --preserve-env=RELEASE_TAG docker compose ps
sudo --preserve-env=RELEASE_TAG docker compose logs --tail=100 api proxy db
sudo --preserve-env=RELEASE_TAG docker compose exec api python manage.py createsuperuser
```

Back up the database before migrations and regularly thereafter. This writes a
PostgreSQL custom-format archive with permissions limited to your VM user:

```bash
umask 077
mkdir -p backups
sudo --preserve-env=RELEASE_TAG docker compose exec -T db pg_dump -U careslot -d careslot -Fc > "backups/careslot-$(date -u +%Y%m%d%H%M%S).dump"
```

Copy backups to separate private storage and test restoring them into a separate
database using `pg_restore` before relying on them. The VM and its volume are one
failure boundary; a Docker volume is not a backup. Never run `docker compose down -v`
on this deployment unless you intend to erase database data and certificates.

For later releases, transfer the updated source without replacing `.env`, then run
`sudo bash deploy/oci/deploy.sh` again. It locks out concurrent deployments and stops
if a migration fails. Use backward-compatible migrations because the previous API
can serve requests during migration. There is a brief interruption when the single
API container is replaced. Failed health checks do not automatically roll back.
Keep the printed release image tag; an application rollback requires that image
and a database schema compatible with it. Take a backup before any schema rollback.

For certificate failures, check DNS, OCI ingress rules, the VM firewall, and proxy
logs. For API errors, check API and database logs. No automated CI/CD is configured;
the existing Google Cloud Build file still targets Google Cloud.

The API currently has no patient authentication. Use synthetic demonstration data
until patient authentication and authorization are implemented before real clinic use.

## Local validation and remaining work

Prepared files: `deploy/oci/compose.yaml`, `Caddyfile`, `init_env.py`, and `deploy.sh`.
Docker Engine must be running to build or test the complete stack. Cloud provisioning,
DNS, certificates, PostgreSQL runtime behavior, and public endpoint verification
must be completed after account activation.
