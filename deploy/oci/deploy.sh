#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

command -v docker >/dev/null
command -v flock >/dev/null
docker compose version >/dev/null
test -f .env || { echo 'Run python3 deploy/oci/init_env.py api.example.com first.' >&2; exit 1; }
# Serialize releases so migrations from two deployments cannot overlap.
exec 9>.deploy.lock
flock -n 9 || { echo 'Another deployment is running.' >&2; exit 1; }
export RELEASE_TAG="$(date -u +%Y%m%d%H%M%S)-$$"
# The CI pipeline syncs files without .git and passes the merged commit in GIT_COMMIT.
if test -n "${GIT_COMMIT:-}"; then
    export GIT_COMMIT
elif git -C ../.. rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    export GIT_COMMIT="$(git -C ../.. rev-parse HEAD)"
    if test -n "$(git -C ../.. status --porcelain --untracked-files=normal)"; then
        export GIT_COMMIT="${GIT_COMMIT}-dirty"
    fi
else
    export GIT_COMMIT=source-bundle
fi
compose=(docker compose --env-file .env -f compose.yaml)
"${compose[@]}" config --quiet
"${compose[@]}" build api
"${compose[@]}" up -d --wait db
# Keep the previous API serving until this one-off migration succeeds.
"${compose[@]}" run --rm --no-deps api python manage.py migrate --noinput
"${compose[@]}" up -d --wait
"${compose[@]}" exec -T api python -c '
import json, os, urllib.request
url = "https://" + os.environ["DJANGO_ALLOWED_HOSTS"] + "/health"
import time
for attempt in range(18):
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            result = json.load(response)
        if result.get("status") != "ok" or result.get("commit") != os.environ["GIT_COMMIT"]:
            raise RuntimeError("Health response does not match this release")
        print("Deployed:", url.removesuffix("/health"), result)
        break
    except Exception:
        if attempt == 17:
            raise
        time.sleep(5)
'
printf 'Release image: careslot-oci:%s\n' "$RELEASE_TAG"
