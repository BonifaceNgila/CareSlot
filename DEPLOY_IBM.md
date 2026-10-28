# Deploy CareSlot to IBM Cloud Code Engine

Use the existing Dockerfile with Code Engine and an external PostgreSQL database
(Neon or IBM Cloud Databases for PostgreSQL). Container-local SQLite is not durable.
These instructions use PowerShell from the repository root. Run each command only
after the previous command succeeds. This is a manual deployment; the existing
Google Cloud Build pipeline does not deploy to IBM.

## 1. Account and tools

Install the [IBM Cloud CLI](https://cloud.ibm.com/docs/cli?topic=cli-install-ibmcloud-cli)
and Docker Desktop with Linux containers enabled. Your IBM account must support
Code Engine and Container Registry, with permissions to create projects, secrets,
and workloads. Review [Code Engine pricing](https://cloud.ibm.com/docs/codeengine?topic=codeengine-pricing).
The example uses Frankfurt; choose a region close to your database.

```powershell
ibmcloud login --sso
ibmcloud plugin install code-engine
ibmcloud plugin install container-registry
ibmcloud target -r eu-de -g Default
ibmcloud ce project create --name careslot
ibmcloud ce project select --name careslot
ibmcloud cr region-set eu-central
# Replace with a globally unique registry namespace.
$namespace = 'your-unique-careslot-namespace'
ibmcloud cr namespace-add $namespace
ibmcloud cr login
```

For existing projects or namespaces, select and reuse them instead of creating them.

## 2. Runtime secrets

Create a local `.env` file (ignored by Git and Docker) with actual values:

```dotenv
DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/DATABASE?sslmode=require
DJANGO_SECRET_KEY=REPLACE_WITH_A_RANDOM_SECRET
DJANGO_DEBUG=0
```

Use your provider's PostgreSQL URL, URL-encode special characters in credentials,
and use its required TLS settings. For Neon, use the direct connection URL for
migrations. Generate the Django key with
`python -c "import secrets; print(secrets.token_urlsafe(50))"`.
Do not paste credentials into chat or commit them.

```powershell
ibmcloud ce secret create --name careslot-runtime --from-env-file .env
```

In the Code Engine console, create registry access named `careslot-registry` for
`de.icr.io`. Use username `iamapikey` and an IBM IAM API key that can read your
registry namespace. See [registry access](https://cloud.ibm.com/docs/codeengine?topic=codeengine-add-registry).
Keep this credential in Code Engine, separate from the runtime secret.

## 3. Build, push, and migrate

Use a new immutable image tag for every release. This builds your current working
tree, including uncommitted changes.

```powershell
$tag = Get-Date -Format 'yyyyMMddHHmmss'
$image = "de.icr.io/${namespace}/careslot:$tag"
$commit = git rev-parse HEAD
docker build --platform linux/amd64 -t $image .
docker push $image
ibmcloud ce jobrun submit --name "careslot-migrate-$tag" --image $image --registry-secret careslot-registry --env-from-secret careslot-runtime --command python --argument manage.py --argument migrate --argument --noinput --retrylimit 0 --cpu 1 --memory 2G --wait
```

Stop if the migration fails. Run migrations once per release, never on application
startup. Keep schema changes compatible with the previous revision during updates.

## 4. Create the application and configure its hostname

Initially create a private application, then configure its exact generated hostname
before making it public:

```powershell
ibmcloud ce application create --name careslot-api --image $image --registry-secret careslot-registry --env-from-secret careslot-runtime --env "GIT_COMMIT=$commit" --port 8080 --cpu 1 --memory 2G --min-scale 0 --max-scale 2 --visibility private
ibmcloud ce application get --name careslot-api
```

Copy the generated application URL from the output into `$url` below. Use only the
origin, with no trailing slash. Django derives the trusted HTTPS CSRF origin from
`DJANGO_ALLOWED_HOSTS`, so the admin also works through the Code Engine proxy.

```powershell
$url = 'https://REPLACE_WITH_GENERATED_APPLICATION_HOST'
$appHost = ([uri]$url).Host
ibmcloud ce application update --name careslot-api --env "DJANGO_ALLOWED_HOSTS=$appHost" --visibility public
Invoke-RestMethod "$url/health"
Invoke-WebRequest "$url/docs" -UseBasicParsing
```

Check that `/health` returns HTTP 200 and reports `$commit`. The image tag identifies
the build; the commit identifies its base source revision. Record the public URL in
README.md after successful verification. Initial requests after idle periods can
take longer because the minimum scale is zero.

## Later releases

Repeat build, push, and the migration job with a fresh tag. After successful migration:

```powershell
ibmcloud ce application update --name careslot-api --image $image --env "GIT_COMMIT=$commit"
Invoke-RestMethod "$url/health"
```

For troubleshooting, use `ibmcloud ce application logs --name careslot-api` and
`ibmcloud ce jobrun logs --name "careslot-migrate-$tag"`. Follow the
[IBM CLI reference](https://cloud.ibm.com/docs/codeengine?topic=codeengine-cli)
for secret updates and workload configuration.
