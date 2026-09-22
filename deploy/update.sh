#!/usr/bin/env bash
# Deploy the current main branch to a droplet already provisioned by setup.sh.
#
#   sudo /srv/cableerp/deploy/update.sh
#
# setup.sh provisions a new machine; this updates one that is already running. It backs up
# first, stops on the first failure, and never touches .env, the database role or nginx.
#
# Why this exists: the update is nine steps and skipping the frontend build leaves the API on
# new code while the browser still runs the old bundle — which looks exactly like "the deploy
# did nothing". Running the halves separately by hand is how that happens.
set -euo pipefail

APP_DIR=${APP_DIR:-/srv/cableerp}
APP_USER=${APP_USER:-cableerp}
BRANCH=${BRANCH:-main}
ENV_FILE="$APP_DIR/backend/.env"

say() { printf '\n\033[1;34m==>\033[0m %s\n' "$1"; }

[ "$(id -u)" -eq 0 ] || { echo "Run with sudo." >&2; exit 1; }
[ -f "$APP_DIR/backend/manage.py" ] || { echo "No app at $APP_DIR." >&2; exit 1; }
[ -f "$ENV_FILE" ] || { echo "No $ENV_FILE — run setup.sh first." >&2; exit 1; }

say "Backing up the database"
DATABASE_URL="$(grep '^DATABASE_URL=' "$ENV_FILE" | cut -d= -f2-)" "$APP_DIR/deploy/backup.sh"

say "Fetching $BRANCH"
git -C "$APP_DIR" config --global --add safe.directory "$APP_DIR" 2>/dev/null || true
git -C "$APP_DIR" fetch origin "$BRANCH"
if [ -z "$(git -C "$APP_DIR" log --oneline "HEAD..origin/$BRANCH")" ]; then
    echo "Already up to date with origin/$BRANCH."
    [ "${FORCE:-}" = "1" ] || exit 0
    echo "FORCE=1 — rebuilding anyway."
fi
git -C "$APP_DIR" log --oneline "HEAD..origin/$BRANCH" | sed 's/^/    /'
git -C "$APP_DIR" merge --ff-only "origin/$BRANCH"

say "Python dependencies"
"$APP_DIR/backend/venv/bin/pip" install -q -r "$APP_DIR/backend/requirements.txt"

say "Migrations"
cd "$APP_DIR/backend"
# Print the plan before applying it, so a surprising migration is visible in the log.
venv/bin/python manage.py migrate --plan
venv/bin/python manage.py migrate --noinput
venv/bin/python manage.py collectstatic --noinput >/dev/null

# The catalogue's cost columns are a cache over the purchase ledger. Replaying is cheap and
# idempotent, and it repairs rows that a previous version computed wrongly.
say "Rebuilding costs from the purchase ledger"
venv/bin/python manage.py rebuild_costs

# Vite needs more memory than this droplet has to spare while gunicorn is resident. Stopping
# the service for the build is a few seconds of downtime and the difference between a build
# and an OOM kill on a 512 MB box.
say "Building the frontend"
TOTAL_MB=$(free -m | awk '/^Mem:/ {print $2}')
HEAP=$(( TOTAL_MB < 1024 ? 768 : 1536 ))
systemctl stop cableerp
cd "$APP_DIR/frontend"
if ! NODE_OPTIONS=--max-old-space-size=$HEAP npm ci --silent; then
    systemctl start cableerp
    echo "npm ci failed — service restarted on the old build." >&2
    exit 1
fi
if ! NODE_OPTIONS=--max-old-space-size=$HEAP npm run build --silent; then
    systemctl start cableerp
    echo "Build failed — service restarted on the old build. Check 'dmesg -T | tail' for an OOM kill." >&2
    exit 1
fi

say "Permissions and restart"
# Everything above ran as root. Hand it back, including the dot-directory gunicorn's control
# server writes to, or it logs a permission error on every boot.
install -d -o "$APP_USER" -g "$APP_USER" "$APP_DIR/.gunicorn"
chown -R "$APP_USER:$APP_USER" "$APP_DIR/backend" "$APP_DIR/frontend/dist"
systemctl start cableerp
sleep 2
systemctl is-active --quiet cableerp || { journalctl -u cableerp -n 30 --no-pager; exit 1; }

say "Deployed $(git -C "$APP_DIR" log --oneline -1)"
echo "    Logs:  journalctl -u cableerp -f"
echo "    Check: curl -sI http://127.0.0.1:8000/api/auth/me/ | head -1"
