# Deploying CableERP

How to run CableERP on any Linux host — a VPS from any provider, or a cloud instance with
managed services beside it. The DigitalOcean droplet already running is untouched by anything
here: nothing in this document asks the people testing on it to change address or logins.

Written for whoever is doing the deploy, working from a laptop with `ssh` and the provider's
console or CLI.

**The guide is deliberately provider-neutral.** Part A installs the app on any Ubuntu 24.04
host and is the same everywhere. Part B covers the three things you may want to move off that
host — database, uploads, TLS — and what each provider calls them. Part C is a worked AWS
example, included because it is the most fiddly; Part D is the short version for everyone else.

---

## Contents

1. [The contract — what the app actually requires](#1-the-contract--what-the-app-actually-requires)
2. [Three deployment shapes](#2-three-deployment-shapes)
3. [Code changes for object storage](#3-code-changes-for-object-storage)
4. [Part A — Install on any Ubuntu host](#part-a--install-on-any-ubuntu-host)
5. [Part B — Moving the database and uploads off the host](#part-b--moving-the-database-and-uploads-off-the-host)
6. [Part C — Worked example: AWS](#part-c--worked-example-aws)
7. [Part D — Other providers](#part-d--other-providers)
8. [Backups](#backups)
9. [Monitoring](#monitoring)
10. [Deploying updates](#deploying-updates)
11. [Rollback](#rollback)
12. [Cost comparison](#cost-comparison)

---

## 1. The contract — what the app actually requires

CableERP is portable because every external dependency is addressed by a URL in
`backend/.env`, never by a hostname baked into code. Satisfy this list and it runs anywhere:

| Requirement | Configured by | Notes |
|---|---|---|
| Linux host, Python 3.12, Node 20 | — | Ubuntu 24.04 assumed throughout. Debian 12 works identically |
| **Pango** system library | — | WeasyPrint hard dependency. Missing it fails at import, not at render |
| **PostgreSQL 16**, reachable by URL | `DATABASE_URL` | Local socket, managed service or another host — the app cannot tell |
| **Redis** (optional) | `REDIS_URL` | Throttle counters and the PDF cache. Unset means locmem, which is fine for one worker |
| **Object storage** (optional) | `S3_BUCKET` + friends | Any S3-compatible provider. Unset means uploads go to local disk |
| **A domain and TLS** | `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS` | Required: the phone share sheet only works on a secure origin |
| RAM | — | **2 GB recommended.** 512 MB runs the app but cannot build the frontend while it is running |

Nothing above names a vendor. That is the whole portability story — the rest of this document
is just filling in the URLs.

**One sizing note learned the hard way:** on a 512 MB host, `npm run build` is OOM-killed unless
gunicorn is stopped first and Node's heap capped at 768 MB. `deploy/update.sh` does both. At
2 GB neither precaution is needed, but they cost nothing.

---

## 2. Three deployment shapes

Pick by how much you want to operate yourself.

### Shape 1 — Everything on one host

Postgres, Redis, nginx, gunicorn and uploads all on one VPS. **This is what the droplet runs.**

*For:* cheapest (~$6–12/month), simplest, one machine to understand.
*Against:* your backup script is the only thing between you and data loss, and uploads die with
the host. The restore path is almost never drilled.
*Use when:* trialling, or when the whole business would survive losing a day of data.

### Shape 2 — Host + managed Postgres + object storage ★ recommended

App on a VPS; database and uploads are somebody else's problem to keep alive.

*For:* automated backups with point-in-time recovery, uploads that outlive the host, and a
**disposable app server** — if it dies you rebuild in 20 minutes and lose nothing.
*Against:* two to four times the cost, and one more bill.
*Use when:* real customers depend on the data. This is the shape the rest of the guide assumes.

### Shape 3 — Containers and a load balancer

ECS/Fargate, Kubernetes, or Docker Compose behind a managed LB.

*For:* atomic deploys, zero downtime, horizontal scale.
*Against:* an image build, a registry, and a load balancer to operate — for a monolith run by
one person.
*Use when:* you need more than one app server. **Not before.** Note that Redis must then move
to a managed cache, because two app servers cannot share a local one and the login throttle
silently stops working if they don't.

---

## 3. Code changes for object storage

Three changes, needed only for Shape 2 and 3. All are inert unless the new environment
variables are set, so the droplet is unaffected.

### 3.1 Dependency

`backend/requirements.txt`:

```
django-storages[s3]>=1.14
```

### 3.2 Provider-neutral storage config

The S3 *protocol* is the portable part — DigitalOcean Spaces, Hetzner Object Storage,
Backblaze B2, Cloudflare R2, MinIO and Scaleway all speak it. The only difference between them
is `endpoint_url`. Add to `backend/config/settings.py` after `MEDIA_ROOT`:

```python
# Uploads go to S3-compatible object storage when a bucket is configured, and to local disk
# otherwise, so development and a single-host deployment are unaffected.
#
# S3_ENDPOINT_URL is what makes this provider-neutral: leave it unset for AWS, or point it at
# DigitalOcean Spaces, Hetzner, Backblaze B2, Cloudflare R2 or a self-hosted MinIO. The rest of
# the configuration is identical across all of them.
#
# STORAGES replaces Django's defaults wholesale, so staticfiles must be restated even though it
# does not change.
S3_BUCKET = os.environ.get("S3_BUCKET", "")
if S3_BUCKET:
    _s3 = {
        "bucket_name": S3_BUCKET,
        "region_name": os.environ.get("S3_REGION", ""),
        # Private bucket: every URL is signed and short-lived. Five minutes is far longer than
        # the gap between generating a URL and WeasyPrint fetching it during a PDF render.
        "querystring_auth": True,
        "querystring_expire": 300,
        "file_overwrite": False,
        "default_acl": None,
    }
    if os.environ.get("S3_ENDPOINT_URL"):
        _s3["endpoint_url"] = os.environ["S3_ENDPOINT_URL"]
    # Credentials are omitted on AWS, where an instance role supplies them. Every other
    # provider needs an explicit key pair.
    if os.environ.get("S3_ACCESS_KEY_ID"):
        _s3["access_key"] = os.environ["S3_ACCESS_KEY_ID"]
        _s3["secret_key"] = os.environ["S3_SECRET_ACCESS_KEY"]
    STORAGES = {
        "default": {"BACKEND": "storages.backends.s3.S3Storage", "OPTIONS": _s3},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
```

### 3.3 Return absolute logo URLs when on object storage ⚠️

**The one that breaks things if skipped.** `SYSTEM_DESIGN.md` Q16 records that
`BusinessProfileSerializer` deliberately returns *relative* logo paths, because an absolute URL
built by Django in development points at `127.0.0.1` — which is the phone, not the server, when
the page is opened on a phone.

Still correct for local disk. But a relative `/media/logos/x.png` is served by nginx, and once
uploads live in object storage nginx has nothing to serve: **every logo 404s, in the app and in
the PDF.**

Make it conditional rather than reversing Q16:

```python
# Relative paths keep working on a phone in development (SYSTEM_DESIGN.md Q16). On object
# storage nothing exists at the relative path, and .url is a signed absolute URL.
def get_logo(self, obj):
    if not obj.logo:
        return None
    return obj.logo.url if settings.S3_BUCKET else obj.logo.name
```

Same for `brand_logo`. Update Q16 to describe both branches.

PDF rendering needs **no change**: `quotes/pdf.py:image_uri` already catches
`NotImplementedError` from a storage backend with no local files and falls back to `image.url`.

**Verify after deploying:** upload a logo, confirm it shows in Settings, then download a quote
PDF and confirm both logos appear. WeasyPrint fetches the signed URL over HTTPS at render time,
so failure looks like a PDF with missing images rather than an error.

### 3.4 `deploy/setup.sh` and an external database

`setup.sh` creates a *local* Postgres role and database. With a managed database that must not
run. The script skips it entirely when `backend/.env` already exists — see the
`[ ! -f "$ENV_FILE" ]` guard — so **write `.env` first**. That is what Part A does.

---

## Part A — Install on any Ubuntu host

Identical on every provider. Run as root on a fresh Ubuntu 24.04 host.

### A1. System packages

```bash
apt-get update && apt-get upgrade -y
apt-get install -y python3-venv python3-pip git nginx redis-server \
    libpango-1.0-0 libpangoft2-1.0-0 postgresql-client ufw
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt-get install -y nodejs
systemctl enable --now redis-server
```

Add `postgresql` to that list only for Shape 1. For Shape 2 the client alone is enough — it is
what `backup.sh` uses to dump a remote database.

### A2. Firewall

```bash
ufw allow 22/tcp && ufw allow 80/tcp && ufw allow 443/tcp
ufw --force enable
```

Skip port 22 if your provider gives you a console-based shell (AWS SSM, GCP IAP) and you would
rather not expose SSH at all.

### A3. Fetch the code

```bash
install -d /srv/cableerp
git clone https://github.com/Matutozi/CableERP.git /srv/cableerp
git config --global --add safe.directory /srv/cableerp
```

### A4. Write `.env` before anything else

This is the file that decides which shape you are running. Generate the secrets:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(64))'   # DJANGO_SECRET_KEY
openssl rand -hex 8                                             # DJANGO_ADMIN_URL
```

```bash
cat > /srv/cableerp/backend/.env <<'ENV'
# --- required everywhere ---
DATABASE_URL=postgres://USER:PASSWORD@HOST:5432/cable_erp
DJANGO_SECRET_KEY=PASTE_GENERATED_KEY
DJANGO_ALLOWED_HOSTS=erp.example.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://erp.example.com
DJANGO_BEHIND_PROXY=true
DJANGO_ADMIN_URL=PASTE_RANDOM_PATH
REDIS_URL=redis://127.0.0.1:6379/1

# --- object storage: omit this whole block for Shape 1 ---
S3_BUCKET=
S3_REGION=
S3_ENDPOINT_URL=          # leave blank on AWS; set it on every other provider
S3_ACCESS_KEY_ID=         # leave blank on AWS when using an instance role
S3_SECRET_ACCESS_KEY=

# SENTRY_DSN=
ENV
chmod 600 /srv/cableerp/backend/.env
```

For Shape 1, `DATABASE_URL` points at `localhost` and you create the database by hand:

```bash
sudo -u postgres psql -c "CREATE USER cableerp WITH PASSWORD 'CHOOSE_ONE'"
sudo -u postgres createdb -O cableerp cable_erp
```

`DJANGO_BEHIND_PROXY=true` is required whenever nginx terminates TLS, or Django redirects in a
loop.

### A5. Prove the database is reachable

```bash
psql "$(grep '^DATABASE_URL=' /srv/cableerp/backend/.env | cut -d= -f2-)" -c 'select version();'
```

A hang is a firewall or security-group problem. An auth error is the `.env`. **Fix it here** —
every later step assumes this works.

### A6. Backend

```bash
useradd --system --home /srv/cableerp --shell /usr/sbin/nologin cableerp || true
cd /srv/cableerp/backend
python3 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements.txt
venv/bin/python manage.py migrate
venv/bin/python manage.py collectstatic --noinput
venv/bin/python manage.py createsuperuser
```

Optional starter catalogue: `venv/bin/python manage.py seed_data`.

### A7. Frontend

```bash
cd /srv/cableerp/frontend
npm ci
npm run build
```

On a host with under 1 GB of RAM, stop gunicorn first and cap the heap:
`systemctl stop cableerp; NODE_OPTIONS=--max-old-space-size=768 npm run build`.

### A8. Services

```bash
cp /srv/cableerp/deploy/cableerp.service /etc/systemd/system/cableerp.service
install -d -o cableerp -g cableerp /srv/cableerp/.gunicorn
chown -R cableerp:cableerp /srv/cableerp/backend /srv/cableerp/frontend/dist
systemctl daemon-reload && systemctl enable --now cableerp
systemctl status cableerp --no-pager
```

`.gunicorn` must exist and belong to the service user, or gunicorn 26 logs a permission error
on every boot.

### A9. nginx and TLS

```bash
sed "s|__DOMAIN__|erp.example.com|g" /srv/cableerp/deploy/nginx.conf \
  > /etc/nginx/sites-available/cableerp
ln -sf /etc/nginx/sites-available/cableerp /etc/nginx/sites-enabled/cableerp
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

apt-get install -y certbot python3-certbot-nginx
certbot --nginx -d erp.example.com --redirect --agree-tos -m you@example.com --no-eff-email
systemctl list-timers | grep certbot
```

Point the domain's A record at the host's IP *before* running certbot, or issuance fails.

**Using object storage?** Delete the `/media/` alias block from the nginx config — it serves
nothing now, and leaving it implies local media still exists.

Once HTTPS is proven, raise HSTS to a year with `DJANGO_HSTS_SECONDS=31536000` in `.env`.
Browsers honour it for that long, so only do this when you are sure.

---

## Part B — Moving the database and uploads off the host

Three independent decisions. You can take any one without the others.

### B1. Managed PostgreSQL

What you need from any provider: **PostgreSQL 16, private networking, automated backups with
point-in-time recovery, and encryption at rest.** Then put its connection string in
`DATABASE_URL`. Nothing else changes.

| Provider | Product | Notes |
|---|---|---|
| AWS | RDS for PostgreSQL | 7-day PITR by default. See Part C |
| DigitalOcean | Managed Databases | Same VPC as the droplet; daily backups |
| Linode / Akamai | Managed Databases | |
| Vultr | Managed Databases | |
| Neon, Supabase, Crunchy | Serverless / hosted Postgres | Provider-independent; usable from any VPS |
| Hetzner | *(none)* | No managed Postgres — self-host, or use an external provider above |

**Insist on private networking.** A database with a public address is one leaked password from
being someone else's. Where the provider cannot do private networking, require TLS and restrict
by source IP.

### B2. Object storage

Any S3-compatible service. The only config difference is `S3_ENDPOINT_URL`:

| Provider | `S3_ENDPOINT_URL` | Credentials |
|---|---|---|
| AWS S3 | *(leave blank)* | Instance role — no keys on disk |
| DigitalOcean Spaces | `https://fra1.digitaloceanspaces.com` | Spaces key pair |
| Hetzner Object Storage | `https://fsn1.your-objectstorage.com` | S3 credentials |
| Backblaze B2 | `https://s3.eu-central-003.backblazeb2.com` | Application key |
| Cloudflare R2 | `https://<account>.r2.cloudflarestorage.com` | R2 token. No egress fees |
| MinIO (self-hosted) | `https://minio.example.com` | Root or service account |

Region strings vary; take the exact endpoint from the provider's console rather than guessing.

**Keep the bucket private.** Signed URLs cost nothing extra and close a known issue carried over
from the droplet: there, anyone can read `/media/` through nginx without signing in.

### B3. Redis

Leave it on the host until you run more than one app server. It holds throttle counters and
cached PDFs; losing it costs one slow render and a reset throttle window, which does not justify
a managed cache's monthly cost.

**The moment there are two app servers this becomes mandatory,** because a per-host cache means
the login throttle counts separately on each — halving its effectiveness silently.

---

## Part C — Worked example: AWS

Shape 2 on AWS: EC2 + RDS + S3, with an instance role so no credentials touch the disk, and SSM
Session Manager so port 22 stays shut. Skip to Part D if you are using another provider.

```bash
export AWS_REGION=eu-central-1 APP=cableerp DOMAIN=erp.example.com
export VPC_ID=$(aws ec2 describe-vpcs --filters Name=isDefault,Values=true \
  --query 'Vpcs[0].VpcId' --output text)
```

### C1. Security groups

Web accepts HTTP/HTTPS from anywhere; the database accepts 5432 **only from the web group** —
referencing the group rather than a CIDR, so it survives the instance changing address.

```bash
export SG_WEB=$(aws ec2 create-security-group --group-name "$APP-web" \
  --description "CableERP web" --vpc-id "$VPC_ID" --query GroupId --output text)
aws ec2 authorize-security-group-ingress --group-id "$SG_WEB" --protocol tcp --port 80 --cidr 0.0.0.0/0
aws ec2 authorize-security-group-ingress --group-id "$SG_WEB" --protocol tcp --port 443 --cidr 0.0.0.0/0

export SG_DB=$(aws ec2 create-security-group --group-name "$APP-db" \
  --description "CableERP database" --vpc-id "$VPC_ID" --query GroupId --output text)
aws ec2 authorize-security-group-ingress --group-id "$SG_DB" \
  --protocol tcp --port 5432 --source-group "$SG_WEB"
```

### C2. RDS

Save the password now; it is not recoverable later.

```bash
export DB_PASSWORD=$(openssl rand -base64 30 | tr -d '/+=' | head -c 32)
echo "DB password: $DB_PASSWORD"

aws rds create-db-instance \
  --db-instance-identifier "$APP-db" --db-instance-class db.t4g.micro \
  --engine postgres --engine-version 16 \
  --allocated-storage 20 --storage-type gp3 --storage-encrypted \
  --master-username cableerp --master-user-password "$DB_PASSWORD" --db-name cable_erp \
  --vpc-security-group-ids "$SG_DB" \
  --backup-retention-period 7 --preferred-backup-window 02:00-03:00 \
  --auto-minor-version-upgrade --no-publicly-accessible --no-multi-az

aws rds wait db-instance-available --db-instance-identifier "$APP-db"
aws rds describe-db-instances --db-instance-identifier "$APP-db" \
  --query 'DBInstances[0].Endpoint.Address' --output text
```

`--no-publicly-accessible` means no internet-routable address at all — which is why psql from
your laptop will not work, and is the point.

### C3. S3

```bash
export BUCKET="$APP-media-$(openssl rand -hex 4)"
aws s3api create-bucket --bucket "$BUCKET" --region "$AWS_REGION" \
  --create-bucket-configuration LocationConstraint="$AWS_REGION"
aws s3api put-bucket-versioning --bucket "$BUCKET" --versioning-configuration Status=Enabled
aws s3api put-bucket-encryption --bucket "$BUCKET" \
  --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
aws s3api put-public-access-block --bucket "$BUCKET" \
  --public-access-block-configuration \
  "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"
```

### C4. Instance role

```bash
cat > /tmp/trust.json <<'JSON'
{"Version":"2012-10-17","Statement":[{"Effect":"Allow",
 "Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}
JSON
aws iam create-role --role-name "$APP-instance" \
  --assume-role-policy-document file:///tmp/trust.json

cat > /tmp/s3policy.json <<JSON
{"Version":"2012-10-17","Statement":[
 {"Effect":"Allow","Action":["s3:GetObject","s3:PutObject","s3:DeleteObject"],
  "Resource":"arn:aws:s3:::$BUCKET/*"},
 {"Effect":"Allow","Action":["s3:ListBucket"],"Resource":"arn:aws:s3:::$BUCKET"}]}
JSON
aws iam put-role-policy --role-name "$APP-instance" \
  --policy-name s3-media --policy-document file:///tmp/s3policy.json
aws iam attach-role-policy --role-name "$APP-instance" \
  --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
aws iam create-instance-profile --instance-profile-name "$APP-instance"
aws iam add-role-to-instance-profile --instance-profile-name "$APP-instance" \
  --role-name "$APP-instance"
```

Object access is scoped to this bucket alone.

### C5. Instance

```bash
export AMI=$(aws ssm get-parameters \
  --names /aws/service/canonical/ubuntu/server/24.04/stable/current/arm64/hvm/ebs-gp3/ami-id \
  --query 'Parameters[0].Value' --output text)

aws ec2 run-instances --image-id "$AMI" --instance-type t4g.small \
  --security-group-ids "$SG_WEB" --iam-instance-profile Name="$APP-instance" \
  --block-device-mappings '[{"DeviceName":"/dev/sda1","Ebs":{"VolumeSize":20,"VolumeType":"gp3","Encrypted":true}}]' \
  --metadata-options 'HttpTokens=required' \
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$APP}]" --count 1
```

`t4g` is Graviton (ARM); every dependency here has aarch64 wheels. `HttpTokens=required`
forces IMDSv2, closing the SSRF path to instance credentials.

A **static address** matters — without it the public IP changes on stop/start and DNS breaks:

```bash
export ALLOC_ID=$(aws ec2 allocate-address --domain vpc --query AllocationId --output text)
aws ec2 associate-address --instance-id "$INSTANCE_ID" --allocation-id "$ALLOC_ID"
```

Then `aws ssm start-session --target "$INSTANCE_ID"`, `sudo -i`, and follow **Part A**, leaving
`S3_ENDPOINT_URL` and both key variables blank so boto3 uses the instance role.

### C6. Teardown

Dependency order matters, and an allocated-but-unassociated Elastic IP is billed:

```bash
aws ec2 terminate-instances --instance-ids "$INSTANCE_ID"
aws ec2 release-address --allocation-id "$ALLOC_ID"
aws rds delete-db-instance --db-instance-identifier "$APP-db" \
  --final-db-snapshot-identifier "$APP-db-final"
aws s3 rm "s3://$BUCKET" --recursive && aws s3api delete-bucket --bucket "$BUCKET"
aws iam remove-role-from-instance-profile --instance-profile-name "$APP-instance" --role-name "$APP-instance"
aws iam delete-instance-profile --instance-profile-name "$APP-instance"
aws iam delete-role-policy --role-name "$APP-instance" --policy-name s3-media
aws iam detach-role-policy --role-name "$APP-instance" \
  --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
aws iam delete-role --role-name "$APP-instance"
```

---

## Part D — Other providers

All of these are Part A plus a connection string. The provider-specific work is creating the
database and bucket in a console, which takes about ten minutes.

### DigitalOcean

The closest to what you already run. Create a droplet (2 GB), a Managed Database (PostgreSQL 16)
and a Space in the same region. Put the droplet and database in the same VPC, and add the
droplet as a trusted source on the database — DigitalOcean's equivalent of a security group.

```ini
DATABASE_URL=postgres://doadmin:PASS@private-db-xxx.db.ondigitalocean.com:25060/cable_erp?sslmode=require
S3_BUCKET=cableerp-media
S3_REGION=fra1
S3_ENDPOINT_URL=https://fra1.digitaloceanspaces.com
S3_ACCESS_KEY_ID=...
S3_SECRET_ACCESS_KEY=...
```

Note the non-standard port and the required `sslmode=require`.

### Hetzner

The cheapest credible option — a CX22 (2 vCPU, 4 GB) is a few euros a month, more machine than
a `t4g.small` for a third of the price. **There is no managed PostgreSQL**, so either run
Postgres on the host (Shape 1, with `backup.sh` doing the work) or point `DATABASE_URL` at an
external provider such as Neon. Object storage is S3-compatible.

### Linode / Vultr / Scaleway

All three offer managed Postgres and S3-compatible object storage. Follow Part A, fill in
`DATABASE_URL` and the `S3_*` block from their console, and use their firewall to restrict the
database to the app server.

### Any provider at all

The test for whether CableERP will run somewhere is short:

1. Can I get an Ubuntu 24.04 host with 2 GB of RAM and a public IP?
2. Can I reach a PostgreSQL 16 database from it?
3. Can I point a domain at it and get a certificate?

Three yeses means Part A works unchanged.

---

## Backups

**Managed database.** Turn on automated backups and point-in-time recovery, then **test the
restore**. An untested backup is not a backup. Restore to a scratch instance, count rows, delete
it. Once now, once a quarter.

**Logical dumps as well.** Snapshots restore an entire instance; a dump restores one table, which
is what a bad migration actually needs. `deploy/backup.sh` works unchanged against a remote
database — it is a normal client connection, just slower than a local socket. Copy the output
off the host:

```
0 2 * * * root DATABASE_URL="$(grep '^DATABASE_URL=' /srv/cableerp/backend/.env | cut -d= -f2-)" /srv/cableerp/deploy/backup.sh && aws s3 cp --recursive /var/backups/cableerp s3://BUCKET/backups/ --exclude '*' --include '*.sql.gz'
```

Replace the `aws s3` call with `rclone`, `s3cmd` or `scp` on other providers.

⚠️ **`chmod 600` that cron file.** Files in `/etc/cron.d` are world-readable by default and this
one contains the database password — a known issue carried over from the droplet.

**Uploads** need no backup of their own if the bucket has versioning on.

---

## Monitoring

Provider-independent and worth more than any dashboard:

- **`SENTRY_DSN`** in `.env` — application errors with tracebacks. Personal data is not sent.
- **Uptime check** against `https://DOMAIN/` from outside. UptimeRobot, Better Stack and most
  providers' own monitors all have free tiers.
- **Disk space alarm.** The failure that takes the app down with no warning is a full disk, on
  the host or the database.
- **Billing alert.** A surprise should arrive as a notification, not an invoice.

On AWS, add CloudWatch alarms for `FreeStorageSpace` on RDS and `CPUUtilization` on the
instance, both wired to an SNS topic you have confirmed by email.

---

## Deploying updates

`deploy/update.sh` is provider-neutral — it knows nothing about where the database or bucket
live:

```bash
sudo /srv/cableerp/deploy/update.sh
```

It backs up, fast-forwards `main`, installs dependencies, prints `migrate --plan` before
applying, rebuilds costs from the purchase ledger, stops gunicorn to build the frontend,
restarts and verifies the service came back — stopping at the first failure, and restarting on
the *old* bundle if the build fails rather than leaving the site down.

Two notes with a remote database: `backup.sh` crosses the network, so dumps are slower; and
migrations hold locks across the network, so the advice about batching large backfills matters
more than it did locally.

---

## Rollback

| Situation | Action |
|---|---|
| Bad code, schema unchanged | `git reset --hard <sha>`, rebuild the frontend, restart |
| Bad migration, data intact | `manage.py migrate <app> <previous>` — works only if the migration declared a reverse, and `RunPython.noop` counts |
| Bad migration, data damaged | Point-in-time restore to just before the deploy, then repoint `DATABASE_URL` |
| Host unrecoverable | Rebuild from Part A |

That last row is the payoff of Shape 2: **the app server is disposable.** The database and the
uploads are somewhere else, so losing the host costs twenty minutes, not data.

---

## Cost comparison

Rough monthly USD, for a 2 GB host plus managed database and object storage. **Verify with each
provider's calculator** — these age quickly.

| | Compute | Database | Storage | ~Total |
|---|---|---|---|---|
| **Current droplet** (Shape 1, 512 MB) | 6 | included | included | **6** |
| Hetzner (Shape 1, 4 GB) | 5 | on host | 1 | **6** |
| Hetzner + Neon (Shape 2) | 5 | 19 | 1 | **25** |
| DigitalOcean (Shape 2) | 12 | 15 | 5 | **32** |
| AWS (Shape 2) | 16* | 16 | 1 | **≈35–40** |

\* includes ~$4/month for the public IPv4 address, charged since February 2024.

**AWS is the most expensive option here and the most operationally capable.** If cost is the
deciding factor, Hetzner plus an external Postgres gives most of Shape 2's safety for roughly a
third of the price. If you expect to want managed queues, secrets or a load balancer later, AWS
is where that story is shortest. Both are defensible; the droplet at $6 is too, for as long as
losing a day of data would be survivable.
