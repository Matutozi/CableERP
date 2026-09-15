# CableERP

A vertical ERP for cable distributors and sellers in Nigeria. **Phase 1 is the quote builder**: a seller sets up their business details and catalogue (cables and accessories) once, then builds a quotation on their phone in a minute and sends it to the customer as a PDF (WhatsApp, email, …). **Phase 2 adds cost and margin**: record what a delivery cost and every quote shows what it is worth making.

It is multi-tenant from the start — any cable seller can register, and every catalogue entry and quote is scoped to the signed-in business.

## Stack

- **Backend:** Django 5.2, Django REST Framework, PostgreSQL, WeasyPrint (PDFs)
- **Frontend:** React 19 + Vite, React Router. The visual design follows the CableERP Claude Design prototype (Inter, neutral greys, a single blue accent).
- **Auth:** Django session auth (cookie + CSRF), with the Vite dev server proxying `/api` so everything is same-origin

## Getting started

### 1. Database

Create a PostgreSQL database, then give the backend its connection string:

```bash
createdb cable_erp
```

Then create `backend/.env` — it is gitignored and must never be committed:

```ini
DATABASE_URL=postgres://USER:PASSWORD@localhost:5432/cable_erp
DJANGO_SECRET_KEY=paste-a-generated-key-here
DJANGO_DEBUG=true
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
DJANGO_CSRF_TRUSTED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
```

Generate the key with:

```bash
python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"
```

| Setting | Default | What it does |
|---|---|---|
| `DATABASE_URL` | — | PostgreSQL connection string. `sqlite:///db.sqlite3` works for a quick trial |
| `DJANGO_SECRET_KEY` | — | Required unless `DJANGO_DEBUG=true`; the app refuses to start without it |
| `DJANGO_DEBUG` | `false` | `true` for local work only. Off means HTTPS redirect, secure cookies and HSTS |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Hostnames the site answers on |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | the Vite dev ports | Origins allowed to post to the API |
| `DJANGO_BEHIND_PROXY` | `false` | `true` when nginx terminates TLS |
| `DJANGO_ADMIN_URL` | `admin` | Move the admin off the guessable path in production |
| `DJANGO_SESSION_DAYS` | `14` | How long "Keep me signed in" lasts |
| `REDIS_URL` | — | Shared cache for throttles and PDFs; needed with more than one worker |
| `SENTRY_DSN` | — | Error tracking. Blank sends nothing anywhere |

On a server, [`deploy/setup.sh`](deploy/setup.sh) writes this file for you with a generated key and database password.

### 2. Backend

WeasyPrint needs Pango installed on the system (`sudo apt install libpango-1.0-0 libpangoft2-1.0-0` on Ubuntu/Debian; see the [WeasyPrint docs](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html) for other platforms).

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_data      # Acme-Oaks Ventures account + cable catalogue; prints the login
python manage.py runserver
```

`seed_data` creates the user `acmeoaks` with a random password it prints once (or pass `--password ...`). It is safe to re-run: it won't overwrite prices you have edited unless you add `--reset-prices`. It seeds cables only; add accessories from the Catalogue → Accessories tab.

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 and sign in, or register a new business.

### Using it from your phone

On the same Wi-Fi, start Vite with `npm run dev -- --host`, add your computer's LAN IP to `DJANGO_ALLOWED_HOSTS` and `http://<ip>:5173` to `DJANGO_CSRF_TRUSTED_ORIGINS` in `backend/.env`, then open `http://<ip>:5173` on the phone. On a quote's preview, **Send on WhatsApp** opens the phone's share sheet with the PDF attached (and marks the quote as sent); on a computer it opens WhatsApp Web with a message and downloads the PDF to attach.

### Tests

```bash
cd backend
python manage.py test          # 92 tests
```

There is also a browser smoke test — sign in, build a quote, check the totals, download the PDF. It needs a seeded stack running on http://localhost:5173:

```bash
cd frontend
npx playwright install chromium   # once
npm run e2e
```

The tests run on PostgreSQL by default; to run them without it, use `DATABASE_URL=sqlite:///test.sqlite3 python manage.py test`. They need `backend/.env` (or a `DJANGO_SECRET_KEY` in the environment), because the settings refuse to start without a key unless `DJANGO_DEBUG=true`.

## How it fits together

```
backend/
  config/      settings (env-driven), root URLs
  accounts/    auth endpoints, BusinessProfile, seed_data command
  catalogue/   CableType, CableSize, Accessory, PriceChange (selling-price history)
  quotes/      Quote, QuoteLineItem, QuoteLineItemColour, PDF rendering (pdf.py + templates/quotes/quote_pdf.html)
  purchasing/  Purchase, PurchaseItem, costing.py (landed cost, unit conversion, moving average)
frontend/src/
  pages/       Login, Register, Dashboard, QuoteList, QuoteEditor, QuotePreview,
               Catalogue (cables), Accessories, Purchases, Settings
  components/  Layout (sidebar / mobile header, drawer, bottom tabs), LineItemCard, QuoteTable, CatalogueHeader,
               MoneyInput, InlinePrice, CostNote, PriceTrend, TrendPanel, Sparkline, Combobox, Field, Icon
  services/    api.js (fetch + CSRF), format.js (money, units), quoteMath.js (catalogue matching, running totals), pdf.js
```

### Screens

- **Quote builder** — items are edited in place on cards. Type or pick a cable type and size (the price fills in from the catalogue and stays editable); cables with colour variants take a quantity per colour. **Add accessory** adds a card for a non-cable product. Anything not in the catalogue is quoted exactly as typed. A sticky bar keeps subtotal, VAT, transport and the grand total in view. **Generate PDF** saves and opens the preview.
- **Quote preview** — an on-screen copy of the PDF with **Download** and **Send on WhatsApp**.
- **Catalogue** — three tabs: **Cables** (types → sizes, prices edited in place), **Accessories** (name, unit, price, all edited in place) and **Purchases**. Every catalogue row shows what it last cost and the margin the current price leaves, or says plainly that no purchase has been recorded.
- **Purchases** — record a delivery: supplier, date, what arrived and what was paid, plus transport and clearing for the load. Stock bought by the coil and sold by the metre is converted once and remembered. Tap a recorded delivery to see what was in it, correct it, or delete it — costs are recalculated either way.
- **Price trend** — tap any catalogue item's cost line to chart what you have charged against what you have paid, over time, with the last few changes listed underneath. Rising cost is shown in red, falling in green: on the cost line, up is the bad direction.
- **Dashboard** — recent quotes, and **Price movements**: the six items restocked most recently, each with a sparkline of its cost and the move since the first purchase. Tapping one opens the full trend in place. It comes from a single request rather than one per item, because a seller opening the app on mobile data pays for every round trip.

### API

| Area | Endpoints |
|---|---|
| Auth | `POST /api/auth/login/`, `POST /api/auth/register/`, `POST /api/auth/logout/`, `GET /api/auth/me/` |
| Profile | `GET/PUT /api/profile/`, `POST/DELETE /api/profile/logo/`, `GET /api/activity/` |
| Cables | `GET/POST /api/cable-types/`, `GET/PUT/PATCH/DELETE /api/cable-types/{id}/`, `GET/POST /api/cable-types/{id}/sizes/`, `GET/PUT/PATCH/DELETE /api/sizes/{id}/`, `GET /api/sizes/{id}/history/` |
| Accessories | `GET/POST /api/accessories/`, `GET/PUT/PATCH/DELETE /api/accessories/{id}/`, `GET /api/accessories/{id}/history/` |
| Trends | `GET /api/price-movements/` (the six items restocked most recently, with their series) |
| Purchases | `GET/POST /api/purchases/`, `GET/PUT/PATCH/DELETE /api/purchases/{id}/` |
| Quotes | `GET/POST /api/quotes/`, `GET/PUT/PATCH/DELETE /api/quotes/{id}/`, `POST /api/quotes/{id}/revise/`, `GET /api/quotes/{id}/pdf/` (`?inline=1` to view instead of download) |

Unauthenticated requests get `401`; requests for another business's data get `404`.

### Design notes

- **Quotes are snapshots.** Line items copy names, unit and price, so editing or deleting catalogue entries never changes an existing quote. Each line also keeps an optional link (`cable_size` or `accessory`, set to null if the entry is deleted) back to where it came from, for Phase 2 cost/margin and Phase 5 stock tracking.
- **Two kinds of line.** `kind="cable"` lines are described by type and size ("1.5mm Singles"; catch-all types named Other/Misc print the size alone, e.g. "RG6 Coaxial"). `kind="accessory"` lines use `item_name`.
- **Units.** Cables are sold per coil (100m) or metre; accessories per piece, pack, box, roll, length, set or metre. Only metre quantities may be fractional (up to two decimal places); everything else is whole numbers.
- **Colour quantities.** Every line has one or more `QuoteLineItemColour` rows. Lines without colours use a single row with an empty colour.
- **Totals are computed, not stored.** Line amounts are rounded to kobo (half-up) before summing, so the subtotal always equals the sum of the printed amounts. The frontend shows a running total while editing; the server's figures are what go on the PDF.
- **Reference numbers** are `QT-YYYYMMDD-NNN`, numbered per business per day (unique per business, not globally, so two sellers can both have `QT-20260911-001`). The date part is the quote date. The business row is locked while numbering so concurrent saves can't collide, and numbers continue past deleted quotes rather than reusing the latest.
- **Payment details are frozen onto each quote** when it is written, so editing the business profile later can never change the account an issued quote tells a customer to pay into. Changing bank details asks for the account password again and is logged. The disclaimer, payment terms and validity still come from the current profile.
- **Price history is stored, not reconstructed.** `PriceChange` records the selling price whenever it is set or changed, so the trend is real data rather than something parsed back out of the audit log's prose. Existing items were given one opening point when the table was added, timestamped then — we know today's price, not when it was set. The cost series comes from the purchase ledger, which already carries dates.
- **Cost comes from a ledger, not a field.** Each delivery is a `Purchase` with its items; the `last_unit_cost` and `average_unit_cost` on a catalogue row are a cache of what that ledger says, so the quote builder can read a cost without aggregating it on every keystroke. The cache is always rebuildable with `python manage.py rebuild_costs`.
- **Two costs, for two questions.** `last_unit_cost` is what a refill costs today — the figure to price against while the naira moves — and is what quotes are measured on. `average_unit_cost` is the quantity-weighted average of everything bought so far, kept for reporting profit in Phase 4. Once Phase 5 tracks stock on hand, the average should narrow to goods still unsold.
- **Cost is normalised to the sale unit** and carries four decimal places, because it is derived rather than charged: a coil bought at ₦76,500 and sold by the metre costs ₦765 a metre, and a box of 12 at ₦5,000 costs ₦416.6667 each.
- **Transport is allocated by line value**, so a ₦300,000 coil carries more of the lorry than a ₦2,000 roll of tape. Leaving it out would overstate every margin by the same silent percentage.
- **Margin is snapshotted with the quote.** `QuoteLineItem.unit_cost` is frozen on every save while the quote is a draft and for the last time as it is marked sent, so restocking next month cannot rewrite the margin on a quote the customer already has. A revision is costed at today's price, not the original's.
- **An unknown cost stays unknown.** Items with no purchase recorded have a null cost and no margin, and the quote reports how many of its lines the margin figure actually speaks for. Treating a missing cost as zero would show 100% margin on everything nobody has costed yet.
- **Cost never reaches the customer.** It is absent from the PDF template and the quote preview, and a test renders a quote's PDF and asserts the cost does not appear in the bytes. The cost fields are listed in one constant per serializer so Phase 6 can hide them from staff who aren't the owner in a single edit.
- **Amounts are bounded**: ₦1bn per unit price and 100,000 per line quantity, so a number too large for the totals can never be saved. Landed cost is *derived* rather than entered, so the delivery's arithmetic is run before anything is written and a line that works out to an impossible cost per unit is refused by name — a mistyped conversion factor is wrong by 100×, not by a little.
- **A sale unit cannot change once costs exist.** Recorded costs are held per sale unit, and nothing in the ledger says how many metres are in a coil bought as a coil — so switching a type from coils to metres is refused rather than silently leaving every cost describing a different thing. Add a separate catalogue entry instead.
- **Dates cannot be in the future.** A delivery dated next year would otherwise win "most recent" forever and silently become the cost every quote is priced against; the same check applies to quote dates, which drive reference numbers.
- **Sign-in, sign-up and PDF rendering are rate limited** (10/min, 20/hour and 60/hour). Throttle counters live in Django's cache, so give the deployment a shared cache such as Redis once it runs more than one worker.
- **A quote holds up to 200 items**, and its PDF is rendered once per version of the quote and of the business profile — repeat downloads come from the cache.
- **Sent quotes are read-only.** Marking a quote as sent records `sent_at` and locks it; `POST /api/quotes/{id}/revise/` copies it into a fresh draft that links back through `revision_of`, so what the customer received stays on record.
- **Changes are recorded.** Price changes, bank-detail changes, purchases and quote events (created, edited, sent, revised, deleted) are written to a per-business history, shown under Settings → Recent activity and served by `GET /api/activity/`. Each entry keeps the user who made it, ready for per-person logins in Phase 6.
- **Quote lists are paged and searched on the server** (`?search=`, `?page=`, `?page_size=`), so a long history stays fast.
- **Sessions end with the browser** unless "Keep me signed in" is ticked, and **Settings → Security** signs out every device at once.
- **Inter is self-hosted** from `frontend/public/fonts`, so the app contacts no third party at run time and still works on a weak connection.
- **No password recovery yet**, by decision: most businesses leave the email field blank, and an SMS or WhatsApp code needs a provider account. Until one is chosen, reset a locked-out account with `python manage.py changepassword <username>`.

## Operations

- **Backups.** [`deploy/backup.sh`](deploy/backup.sh) dumps, compresses, verifies and prunes. Run it nightly from cron, and do the restore drill it documents monthly — an untested backup is not a backup.
- **Error tracking.** Set `SENTRY_DSN` and errors are reported (personal data is not sent). Leave it blank and nothing leaves the server.
- **CI.** [`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs the test suite against PostgreSQL, checks for missing migrations, runs `check --deploy`, audits both dependency trees, builds the frontend, and runs the browser smoke test against a seeded stack.
- **Admin.** Set `DJANGO_ADMIN_URL` to something unguessable in production; it defaults to `admin/`.
- **Sessions.** `DJANGO_SESSION_DAYS` (default 14) controls how long "Keep me signed in" lasts.

## Before going to production

Settings now fail closed: with `DJANGO_DEBUG` unset the app will not start without a `DJANGO_SECRET_KEY`, and it turns on the HTTPS redirect, secure cookies and HSTS by itself. Set `DJANGO_BEHIND_PROXY=true` when a reverse proxy terminates TLS.

[`deploy/nginx.conf`](deploy/nginx.conf) serves `frontend/dist` and proxies the API from one origin, with a Content-Security-Policy and the other security headers already set. Run Django behind it with `DJANGO_BEHIND_PROXY=true`.

Still to do for a real deployment: use a shared cache (Redis) for throttling and PDF caching, serve uploaded logos from proper media storage, and take automated database backups. The [Phase 1 audit](https://claude.ai/code/artifact/7f7a7aa0-8f0c-4f5a-ad0a-10ef439d694a) lists what remains, ranked.
