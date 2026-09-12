#!/usr/bin/env bash
# Take a fresh Ubuntu 24.04 droplet to a running CableERP. Safe to re-run: it updates code,
# dependencies and the build, and leaves your .env, database and uploads alone.
#
#   sudo DOMAIN=quotes.example.com EMAIL=you@example.com /srv/cableerp/deploy/setup.sh
#
# Put the code at /srv/cableerp first (git clone or rsync). Point DOMAIN's DNS at this
# droplet before running, or TLS will be skipped and you can re-run it later.
set -euo pipefail

APP_DIR=${APP_DIR:-/srv/cableerp}
APP_USER=${APP_USER:-cableerp}
DB_NAME=${DB_NAME:-cable_erp}
DB_USER=${DB_USER:-cable_erp}
DOMAIN=${DOMAIN:?Set DOMAIN=quotes.example.com}
EMAIL=${EMAIL:-}                      # for Let's Encrypt; without it TLS is skipped
SEED_PASSWORD=${SEED_PASSWORD:-}      # first sign-in password; generated when empty

[ "$(id -u)" -eq 0 ] || { echo "Run with sudo." >&2; exit 1; }
[ -f "$APP_DIR/backend/manage.py" ] || { echo "No code at $APP_DIR — clone or rsync it there first." >&2; exit 1; }

say() { printf "\n\033[1;34m==> %s\033[0m\n" "$1"; }

say "Installing system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-dev build-essential \
    postgresql redis-server nginx certbot python3-certbot-nginx ufw curl git \
    libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libffi-dev >/dev/null
if ! command -v node >/dev/null; then
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - >/dev/null
    apt-get install -y -qq nodejs >/dev/null
fi
systemctl enable --now postgresql redis-server >/dev/null

# A small droplet (512 MB) cannot build the frontend or run Postgres without swap.
TOTAL_MB=$(( $(getconf _PHYS_PAGES) * $(getconf PAGE_SIZE) / 1024 / 1024 ))
if [ "$TOTAL_MB" -lt 1024 ] && ! swapon --show | grep -q .; then
    say "Adding 2 GB of swap (only ${TOTAL_MB} MB of RAM)"
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile >/dev/null
    swapon /swapfile
    grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
    sysctl -q vm.swappiness=10
fi

say "Creating the service account"
id -u "$APP_USER" >/dev/null 2>&1 || useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"

ENV_FILE="$APP_DIR/backend/.env"
if [ ! -f "$ENV_FILE" ]; then
    say "Creating the database and $ENV_FILE"
    DB_PASSWORD=$(openssl rand -hex 24)
    ADMIN_PATH=$(openssl rand -hex 8)
    sudo -u postgres psql -qtc "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'" | grep -q 1 \
        || sudo -u postgres psql -qc "CREATE USER $DB_USER WITH PASSWORD '$DB_PASSWORD'" >/dev/null
    sudo -u postgres psql -qtc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" | grep -q 1 \
        || sudo -u postgres createdb -O "$DB_USER" "$DB_NAME"
    if [ -n "$EMAIL" ]; then
        ORIGINS="https://$DOMAIN"
        NO_TLS_YET=""
    else
        # No certificate yet (often a droplet IP while you wait for a domain): trust the plain-HTTP
        # origin and don't redirect, or sign-in fails. Re-run with EMAIL set once DNS is ready.
        ORIGINS="https://$DOMAIN,http://$DOMAIN"
        NO_TLS_YET=$'DJANGO_SECURE_SSL_REDIRECT=false\nDJANGO_SECURE_COOKIES=false'
    fi
    cat > "$ENV_FILE" <<ENV
# Written by deploy/setup.sh. Keep it secret; it is the key to your data.
DATABASE_URL=postgres://$DB_USER:$DB_PASSWORD@localhost:5432/$DB_NAME
DJANGO_SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(64))')
DJANGO_ALLOWED_HOSTS=$DOMAIN
DJANGO_CSRF_TRUSTED_ORIGINS=$ORIGINS
DJANGO_BEHIND_PROXY=true
$NO_TLS_YET
DJANGO_ADMIN_URL=$ADMIN_PATH
REDIS_URL=redis://127.0.0.1:6379/1
# SENTRY_DSN=
ENV
    chmod 600 "$ENV_FILE"
else
    say "Keeping the existing $ENV_FILE"
    if [ -z "$EMAIL" ]; then
        # Still no certificate: make sure the plain-HTTP settings are present, or sign-in fails.
        grep -q '^DJANGO_SECURE_SSL_REDIRECT=' "$ENV_FILE" || echo "DJANGO_SECURE_SSL_REDIRECT=false" >> "$ENV_FILE"
        grep -q '^DJANGO_SECURE_COOKIES=' "$ENV_FILE" || echo "DJANGO_SECURE_COOKIES=false" >> "$ENV_FILE"
    else
        # A certificate is being installed: drop the plain-HTTP concessions.
        sed -i '/^DJANGO_SECURE_SSL_REDIRECT=false$/d; /^DJANGO_SECURE_COOKIES=false$/d' "$ENV_FILE"
    fi
fi

say "Installing Python dependencies"
[ -d "$APP_DIR/backend/venv" ] || python3 -m venv "$APP_DIR/backend/venv"
"$APP_DIR/backend/venv/bin/pip" install -q --upgrade pip
"$APP_DIR/backend/venv/bin/pip" install -q -r "$APP_DIR/backend/requirements.txt"

say "Database migrations and static files"
cd "$APP_DIR/backend"
venv/bin/python manage.py migrate
venv/bin/python manage.py collectstatic --noinput >/dev/null

if [ "$(venv/bin/python manage.py shell -c 'from django.contrib.auth import get_user_model; print(get_user_model().objects.count())' 2>/dev/null | tail -1)" = "0" ]; then
    SEED_PASSWORD=${SEED_PASSWORD:-$(openssl rand -hex 8)}
    say "Seeding your business and catalogue"
    venv/bin/python manage.py seed_data --password "$SEED_PASSWORD"
else
    SEED_PASSWORD=""
fi

if [ -f "$APP_DIR/frontend/dist/index.html" ] && [ "${SKIP_BUILD:-}" = "1" ]; then
    say "Using the frontend build already in dist/"
else
    say "Building the frontend"
    cd "$APP_DIR/frontend"
    PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm ci --no-audit --no-fund --silent
    # Keep node inside the box on a small droplet; swap covers the rest.
    NODE_OPTIONS=--max-old-space-size=$(( TOTAL_MB < 1024 ? 768 : 1536 )) npm run build --silent
fi
chown -R "$APP_USER:$APP_USER" "$APP_DIR/backend" "$APP_DIR/frontend/dist"

say "Starting the app service"
sed "s|/srv/cableerp|$APP_DIR|g; s|User=cableerp|User=$APP_USER|; s|Group=cableerp|Group=$APP_USER|" \
    "$APP_DIR/deploy/cableerp.service" > /etc/systemd/system/cableerp.service
systemctl daemon-reload
systemctl enable --now cableerp
systemctl restart cableerp

say "Configuring nginx"
sed "s|__DOMAIN__|$DOMAIN|g; s|/srv/cableerp|$APP_DIR|g" "$APP_DIR/deploy/nginx.conf" > /etc/nginx/sites-available/cableerp
ln -sf /etc/nginx/sites-available/cableerp /etc/nginx/sites-enabled/cableerp
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

say "Firewall"
ufw allow OpenSSH >/dev/null
ufw allow 'Nginx Full' >/dev/null
ufw --force enable >/dev/null

say "Nightly backups"
install -d -o "$APP_USER" -g "$APP_USER" /var/backups/cableerp
cat > /etc/cron.d/cableerp-backup <<CRON
# Nightly database backup. Restore drill documented in deploy/backup.sh.
0 2 * * * root DATABASE_URL="$(grep '^DATABASE_URL=' "$ENV_FILE" | cut -d= -f2-)" $APP_DIR/deploy/backup.sh >> /var/log/cableerp-backup.log 2>&1
CRON

if [ -n "$EMAIL" ]; then
    say "Requesting the TLS certificate"
    certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "$EMAIL" --redirect || {
        echo "certbot failed — check that $DOMAIN points at this droplet, then re-run this script."; }
else
    say "Skipping TLS (no EMAIL set) — the site runs on plain HTTP for now"
    echo "  WhatsApp sharing needs HTTPS: once you have a domain pointing here, re-run with"
    echo "  DOMAIN=your.domain EMAIL=you@example.com, then set DJANGO_SECURE_SSL_REDIRECT=true in .env."
fi

SCHEME=$([ -n "$EMAIL" ] && echo https || echo http)   # no certificate means plain HTTP
printf "\n\033[1;32m==> CableERP is up\033[0m\n"
echo "  Site:        $SCHEME://$DOMAIN"
echo "  Admin:       $SCHEME://$DOMAIN/$(grep '^DJANGO_ADMIN_URL=' "$ENV_FILE" | cut -d= -f2)/"
[ -n "$SEED_PASSWORD" ] && echo "  Sign in as:  acmeoaks / $SEED_PASSWORD   (change it: manage.py changepassword acmeoaks)"
echo "  Logs:        journalctl -u cableerp -f"
echo "  Restart:     systemctl restart cableerp"
