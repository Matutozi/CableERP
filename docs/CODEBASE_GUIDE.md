# CableERP — Codebase Guide (backend · frontend · devops)

## How to use this guide
This guide is for reviewing the codebase file by file and for debugging. Each part explains the code at two levels: **🧠 Senior** for the design decisions, **🌱 Junior** for plain-language explanations. It is split into backend, frontend and devops. Paths are relative to the repo root. Start with the file map below, or follow the suggested reading order in §0.

### File map
| Area | Files |
|---|---|
| Backend config | [settings.py](../backend/config/settings.py) · [urls.py](../backend/config/urls.py) |
| Accounts | [models.py](../backend/accounts/models.py) · [utils.py](../backend/accounts/utils.py) · [authentication.py](../backend/accounts/authentication.py) · [numbering.py](../backend/accounts/numbering.py) · [serializers.py](../backend/accounts/serializers.py) · [views.py](../backend/accounts/views.py) · [seed_data.py](../backend/accounts/management/commands/seed_data.py) |
| Catalogue | [models.py](../backend/catalogue/models.py) · [serializers.py](../backend/catalogue/serializers.py) · [views.py](../backend/catalogue/views.py) |
| Purchasing | [models.py](../backend/purchasing/models.py) · [costing.py](../backend/purchasing/costing.py) · [serializers.py](../backend/purchasing/serializers.py) · [views.py](../backend/purchasing/views.py) · [rebuild_costs.py](../backend/purchasing/management/commands/rebuild_costs.py) |
| Quotes | [models.py](../backend/quotes/models.py) · [serializers.py](../backend/quotes/serializers.py) · [views.py](../backend/quotes/views.py) · [pdf.py](../backend/quotes/pdf.py) · [quote_pdf.html](../backend/quotes/templates/quotes/quote_pdf.html) · [quote_format.py](../backend/quotes/templatetags/quote_format.py) |
| Waybills | [models.py](../backend/waybills/models.py) · [serializers.py](../backend/waybills/serializers.py) · [views.py](../backend/waybills/views.py) · [pdf.py](../backend/waybills/pdf.py) · [waybill_pdf.html](../backend/waybills/templates/waybills/waybill_pdf.html) |
| Frontend core | [main.jsx](../frontend/src/main.jsx) · [App.jsx](../frontend/src/App.jsx) · [AuthContext.jsx](../frontend/src/context/AuthContext.jsx) · [api.js](../frontend/src/services/api.js) · [format.js](../frontend/src/services/format.js) · [quoteMath.js](../frontend/src/services/quoteMath.js) · [pdf.js](../frontend/src/services/pdf.js) |
| Frontend pages | [QuoteEditor.jsx](../frontend/src/pages/QuoteEditor.jsx) · [LineItemCard.jsx](../frontend/src/components/LineItemCard.jsx) · [QuotePreview.jsx](../frontend/src/pages/QuotePreview.jsx) · [Purchases.jsx](../frontend/src/pages/Purchases.jsx) · [Catalogue.jsx](../frontend/src/pages/Catalogue.jsx) · [Settings.jsx](../frontend/src/pages/Settings.jsx) · [WaybillEditor.jsx](../frontend/src/pages/WaybillEditor.jsx) · [smoke.mjs](../frontend/e2e/smoke.mjs) |
| Devops | [setup.sh](../deploy/setup.sh) · [update.sh](../deploy/update.sh) · [nginx.conf](../deploy/nginx.conf) · [cableerp.service](../deploy/cableerp.service) · [gunicorn.conf.py](../deploy/gunicorn.conf.py) · [backup.sh](../deploy/backup.sh) · [ci.yml](../.github/workflows/ci.yml) · [vite.config.js](../frontend/vite.config.js) |
## 0. The big picture

**What the product is:** software for Nigerian cable sellers. A seller does four things with it:
1. Sets up a **catalogue**: cable types → sizes, plus accessories, each with a selling price.
2. Records **purchases** (deliveries). These give every catalogue item a **cost**, so the app can show a **margin**.
3. Builds a **quote** on a phone and sends it as a PDF over WhatsApp.
4. Turns a quote into a **waybill**, the delivery note the driver carries. A waybill shows no prices.

```
Browser (React SPA)  ──/api/*──►  nginx  ──►  gunicorn → Django + DRF  ──►  PostgreSQL
      ▲  static files from frontend/dist         │ WeasyPrint (PDF)   Redis (throttles + PDF cache)
```

- 🧠 **Senior:** A multi-tenant monolith. The tenant is `BusinessProfile`, which is one-to-one with the Django `User`. Every queryset is scoped through `accounts/utils.py:get_business()`. Auth uses a session cookie plus CSRF, and the API is served from the same origin as the app (the Vite proxy in dev, nginx in prod), so there is no CORS and there are no tokens. The code follows three rules throughout:
  - **Operational data is derived; document data is frozen.** This one rule explains the two that follow, and most of the codebase. A catalogue row is a live fact and must always reflect the ledger. A quote is a historical claim made to a customer on a date — if changing your bank details silently rewrote last month's PDF, that would be a forgery, not a feature. When you add a field, decide which kind it is *first*; almost every design question below is a consequence of that answer.
  - **Cost comes from a ledger.** Purchases are the source of truth, and the cost fields on catalogue rows are only a cache of them, rebuildable at any time with `manage.py rebuild_costs`. A bug in the cost write path is therefore something you fix and re-run, not something that loses data.
  - **Documents are snapshots.** Quotes copy names, prices, payment details and cost when they are written (`snapshot_costs`, and migrations `quotes/0003`+`0004` for payment details), so later catalogue or profile edits never change them.
  - **Unknown means `null`, never `0`.** A missing cost is not a free item, and a margin against an unknown cost is not zero — it is unknown, and the UI must say so.
- 🌱 **Junior:** Each seller gets their own private copy of everything. The React app asks Django for data, Django reads Postgres, and nginx sits in front of both. When a quote is saved, the app "photographs" the prices at that moment so the quote never changes later.

**Suggested reading order:** `backend/config/settings.py` → `accounts/` → `catalogue/models.py` → `purchasing/costing.py` → `quotes/models.py` + `serializers.py` → `waybills/` → `frontend/src/services/*` → `App.jsx` → `QuoteEditor.jsx` + `LineItemCard.jsx` → `deploy/*`.

---

## 0.5 Walkthrough — one quote, end to end

The reading order above covers the codebase by area. This covers it by *following a single
quote*, which is the faster way back in after time away, and the right path to walk someone
else down. Ten stops, each naming the file to have open.

| # | Stop | File | What to notice |
|---|---|---|---|
| 1 | The seller signs in | `accounts/authentication.py`, `context/AuthContext.jsx` | A session cookie, not a token. `MeView` must run to set the CSRF cookie before any write succeeds — this is the cause of most "403 CSRF" reports. |
| 2 | Every query is fenced | `accounts/utils.py:get_business()` | The tenant boundary. Every viewset scopes through it, which is why a valid id from another business returns **404, not 403** — the object is invisible, not forbidden. |
| 3 | The catalogue is read | `catalogue/models.py`, `catalogue/serializers.py` | `CableType` → `CableSize`, plus `Accessory`. Note `validate_unit` refusing to change a unit once costs exist: the ledger is denominated in it. |
| 4 | A delivery gave it a cost | `purchasing/costing.py` ⭐ | The heart of the app. `landed_unit_costs` is pure — the serializer runs the same arithmetic to validate a delivery *before* persisting it, so a bad conversion factor is rejected rather than half-written. Read the module docstring. |
| 5 | The seller builds the quote | `pages/QuoteEditor.jsx`, `components/LineItemCard.jsx` | Local React state, no store. Totals recompute per keystroke. |
| 6 | Totals appear instantly | `services/quoteMath.js` | A deliberate duplicate of the server's arithmetic, so the total moves without a round trip on a phone. **The server is authoritative** — if the two ever disagree, the PDF is right and this is wrong. |
| 7 | It is saved | `quotes/serializers.py`, `quotes/models.py` | The server recomputes every total from scratch; client figures are never trusted. `Decimal` throughout, never float. |
| 8 | Cost is frozen onto it | `quotes/models.py:snapshot_costs` | Rule 1 in action. Re-run on each draft save, once more on send, then `is_locked` stops it forever. A free-typed line has no catalogue row, so it keeps `unit_cost = None` — unknown, not zero. |
| 9 | The PDF is rendered | `quotes/pdf.py`, `templates/quotes/quote_pdf.html` | WeasyPrint, server-side, Redis-cached by a key that includes the quote's updated timestamp. The memory hog that sizes the whole droplet. |
| 10 | It becomes a waybill | `waybills/models.py`, `waybills/pdf.py` | Copies the lines and **drops every price**. A second frozen document, made from the first. |

**To walk it live** (needs the dev stack running, see §3.1): sign in → Catalogue → Purchases,
record a delivery → back to Catalogue, the item now shows a cost → new quote with that item,
the line shows a margin → send it → open the PDF → create the waybill and confirm the PDF has
no prices. That sequence touches all ten stops and every app in the backend.

**The question to keep asking at each stop:** is this value *derived* or *frozen*? Stops 3 and 4
are derived, 7 through 10 are frozen, and the boundary is stop 8.

---

## PART 1 — BACKEND (`backend/`, Django 5.2 + DRF)

### 1.1 `config/`
| File | What it does |
|---|---|
| `settings.py` | Configured entirely from environment variables (loads `backend/.env`). **It fails closed:** it refuses to start with no `DJANGO_SECRET_KEY` unless `DJANGO_DEBUG=true`. When not in debug it turns on the SSL redirect, secure cookies and HSTS (L147-158). `REDIS_URL` switches the cache to Redis, and Sentry is used only if `SENTRY_DSN` is set. Throttle rates are `auth` 10/min, `register` 20/h and `pdf` 60/h. The default authentication class is the custom one in `accounts/authentication.py`, and every endpoint requires sign-in by default. |
| `urls.py` | Mounts the admin at `ADMIN_URL`, which is random in prod, and includes every app's URLs under `/api/`. It serves `/media/` itself only when `DEBUG` is on. |

🌱 `TESTING = "test" in sys.argv` (L127) switches the HTTPS redirect off during tests. Without it, every test request would be answered with a 301.

### 1.2 `accounts/` — users, tenant, audit log, numbering
- **`models.py`**
  - `BusinessProfile` holds the business name, contact details, two logos (`logo` and `brand_logo`, the manufacturer's logo), bank details, disclaimer, payment terms, quote validity and `vat_rate` (default 7.5).
  - `AuditLog` plus `record()` write one line of human-readable history per business action: price changed, bank details changed, quote created/sent/revised/deleted, purchase recorded/deleted, waybill created/edited/deleted.
  - `naira()` formats `₦1,234.00`.
- **`utils.py:get_business(request)`** is the **tenant gate**. It returns 403 if the user has no profile. Every viewset's `get_queryset` filters through it, which is why another business's ID returns **404**, not 403.
- **`authentication.py`** changes the `WWW-Authenticate` header so DRF answers unauthenticated requests with **401 instead of 403**. The frontend relies on this to tell "session expired" apart from "you may not do that".
- **`numbering.py:next_reference_number(qs, prefix, date)`** builds references as `PREFIX-YYYYMMDD-NNN`. It takes the highest existing number for that day and adds 1, so numbers are never reused after a delete. **The caller must hold `select_for_update()` on the BusinessProfile row**, or two saves at the same moment can get the same number (the DB unique constraint is the backstop).
- **`serializers.py`**
  - `RegisterSerializer` checks the username case-insensitively, runs Django's password validators, and creates the User and BusinessProfile in one transaction.
  - `LoginSerializer` authenticates and reads the `remember` flag.
  - `BusinessProfileSerializer` has two important behaviours:
    - It returns logo **paths, not absolute URLs**, because an absolute URL built by Django would be `127.0.0.1` and would break on a phone.
    - **Changing any of the `BANK_FIELDS` requires `current_password`** (validated in `validate`). The change is written to the log and to `AuditLog`, so money can't be silently redirected.
  - `image_upload_serializer(field)` is a factory that builds the upload serializer for either logo and enforces a 2 MB limit.
- **`views.py`**
  - `MeView` answers "who am I?" and **plants the CSRF cookie** (`ensure_csrf_cookie`).
  - `LoginView` and `RegisterView` are CSRF-protected and throttled. With "remember me" unticked, `set_expiry(0)` makes the session last only until the browser closes.
  - `LogoutEverywhereView` scans *every* live session and deletes the ones belonging to this user (Django has no per-user session index).
  - `ProfileView` handles GET and PUT for the profile. `ActivityView` returns the latest 50 audit entries. `ProfileLogoView` / `ProfileBrandLogoView` upload a logo (deleting the old file) or remove it.
- **`management/commands/seed_data.py`** is idempotent. It creates the `acmeoaks` user (and prints the password), the profile and the cable catalogue. It calls `record_price()` so a fresh install already has price history. `--reset-prices` overwrites prices that were edited.

### 1.3 `catalogue/` — what the seller sells
- **`models.py`**
  - `MAX_PRICE = ₦1bn` and `MAX_QUANTITY = 100,000` cap values so totals can never overflow their columns.
  - `COST_DECIMAL_PLACES = 4`: cost is *derived* by division, so it keeps 4 decimal places (for example ₦5,000 / 12 = 416.6667).
  - `CostedItem` (abstract) holds `purchase_unit`, `units_per_purchase`, `last_unit_cost` and `average_unit_cost`. **The cost fields are a cache written only by `purchasing/costing.py`.** `margin_percentage = (price − last_cost) / price × 100`, or `None` when the cost is unknown.
  - `CableType` has a unit (coil = 100 m, or metre), `has_colour_variants` and `colour_options` (a JSON list). Names are unique per business.
  - `CableSize(CostedItem)` has `size_label` and `default_price`. `sale_unit` is its type's unit.
  - `Accessory(CostedItem)` has seven possible units.
  - `QUOTE_UNITS` is the union of all units. `FRACTIONAL_UNITS = {"metre"}` means **only metre quantities may have decimals.**
  - `PriceChange` + `record_price(row, user)` form the selling-price history. A new row is written only if the price actually changed.
- **`serializers.py`**
  - `COST_FIELDS` is a single list of the cost fields, all read-only. It is kept in one place so a later phase can hide cost from staff with one edit.
  - `BusinessCableSizeField` / `BusinessAccessoryField` are **tenant-safe foreign-key fields**: their querysets are filtered to the current business, so you can't point a quote line at another seller's item.
  - Name uniqueness is checked case-insensitively in `validate_name` / `validate_size_label`; the default validators are switched off.
  - **Unit-change guard:** `validate_unit` refuses to change a type's or accessory's unit once purchases with a cost exist (`UNIT_CHANGE_REFUSED`). Stored costs are "per coil" or "per metre", and there is no way to convert the old ones.
  - `validate_colour_options` trims names and removes case-insensitive duplicates. `validate` requires at least one colour when `has_colour_variants` is on.
- **`views.py`**
  - `BusinessCatalogueMixin` passes `business` into the serializer context and gives a new row `order = max + 1`.
  - `CableTypeViewSet` provides CRUD plus the nested `GET/POST /cable-types/{id}/sizes/`; creating a size records its opening price.
  - `CableSizeViewSet` supports retrieve, update and destroy (there is no list). When the price changes, `perform_update` calls `record_price` and writes an `AuditLog` entry.
  - `AccessoryViewSet` is full CRUD with the same price logging.
  - `item_history(row)` returns `{price: [...PriceChange], cost: [...PurchaseItem landed costs by purchase date]}` and is exposed as `/{id}/history/`.
  - `PriceMovementsView` (`/price-movements/`) finds the latest purchase date for each item, takes the 6 most recent, and returns them with their histories in **one request**. This keeps round trips down for sellers on mobile data.
  - 🌱 The imports from `purchasing` sit *inside* functions on purpose: `purchasing` depends on `catalogue`, and an import at the top of the file would create a circular import.

### 1.4 `purchasing/` — cost engine ⭐ (the most important business logic)
- **`models.py`**
  - `Purchase` is one delivery: supplier, date, `additional_cost` (transport, clearing, loading) and a note. `goods_total` and `total_cost` are computed properties.
  - `PurchaseItem` must link to a CableSize **or** an Accessory. Both links use SET_NULL, so deleting a catalogue item keeps the purchase history.
  - Its fields: `quantity` is counted in `entry_unit`; `units_per_entry` is how many sale units one entry unit holds (a coil sold by the metre gives 100); `unit_cost` is the price per entry unit; `landed_unit_cost` is computed, **per sale unit, including a share of transport**.
  - `line_cost = qty × unit_cost` and `sale_quantity = qty × units_per_entry`.
- **`costing.py`** — read this slowly:
  1. `landed_unit_costs(lines, additional_cost)` is **pure maths** with no database access. Transport is split across lines **in proportion to each line's value**; if every line's value is 0, it is split by quantity instead. Each line's result is `landed = (line_cost + share) / sale_quantity`, rounded to 4 decimal places.
     *Example:* a coil costs ₦76,500 and is sold per metre (100 m); the delivery also cost ₦0 in transport. The landed cost is ₦765.0000 per metre.
  2. `allocate_landed_cost(purchase)` applies step 1 to the saved items and raises `CostOutOfRange` if any result is above ₦1bn (almost always a mistyped conversion factor).
  3. `recalculate(row)` rebuilds one catalogue row's cache:
     - `last_unit_cost` comes from the purchase with the **latest date**, with ties broken by highest purchase id and then highest item id.
     - `average_unit_cost` is a **quantity-weighted average over every purchase ever recorded**.
     - With no purchases, both are `None`.
  4. `recalculate_rows(rows)` calls `select_for_update()` on the rows, always locking them in pk order so two requests can't deadlock.
  5. `refresh(purchase, also=rows_before_edit)` runs steps 2 and 4. `also` covers lines that an edit *removed*, so their items' costs get corrected too.
- **`serializers.py`**
  - `PurchaseItemSerializer.validate` enforces these rules:
    - The line must link to a catalogue row, and not to both kinds.
    - `item_name` is set from the row.
    - **`entry_unit` and `units_per_entry` default to how this item was bought last time.**
    - Only metre quantities may be fractional.
    - If the entry unit equals the sale unit, the factor must be 1.
  - `PurchaseSerializer`:
    - Rejects **dates in the future**, because a future date would win "latest purchase" forever.
    - Allows 1–200 items.
    - `validate` **runs the landed-cost maths before anything is saved** and names the offending line if a result is out of range.
    - `update` deletes all items and recreates them; items have no identity worth keeping.
    - `_save_items` remembers the purchase unit and factor on the catalogue row, so the next delivery pre-fills them.
- **`views.py`** — `PurchaseViewSet`: `perform_create`, `perform_update` and `perform_destroy` are each `@transaction.atomic`. Each one saves, then recalculates costs, then writes an audit entry. Saving and cost recalculation succeed or fail together.
- **`management/commands/rebuild_costs.py`** replays the whole ledger and rebuilds every cache from scratch. **This is the recovery tool whenever cost figures look wrong.**

### 1.5 `quotes/` — the core document
- **`models.py`**
  - `money()` rounds half-up to kobo (2 decimal places).
  - `Quote` fields:
    - `reference_number` is unique per business.
    - `status` is either draft or sent, and `sent_at` records when it was sent.
    - `revision_of` points at the sent quote this one replaces.
    - `payment_*` holds the **frozen bank details**.
    - `vat_percentage` and `transport_cost`.
  - Totals are **computed, never stored**:
    - `subtotal` is the sum of the line amounts, each already rounded.
    - `vat_amount = money(subtotal × vat%)`.
    - `grand_total = subtotal + VAT + transport`.
  - Margin properties (`costed_subtotal`, `total_cost`, `total_margin`, `margin_percentage`, `margin_coverage`) **include only lines with a known cost**. `margin_coverage` reports what share of the quote the margin actually covers.
  - `is_locked` is true when the quote is sent. `create_revision()` copies the quote into a new draft dated today, with a new reference number, **the current bank details, and today's costs**. `payment_details` falls back to the profile for quotes older than the snapshot fields.
  - `QuoteLineItem` has `kind` (cable or accessory). A cable line is described by `cable_type_name` + `size_label`; an accessory line by `item_name`. Its `cable_size` / `accessory` link uses SET_NULL. `unit_price` is a snapshot, and `unit_cost` + `cost_basis` hold the **frozen cost**. `description` prints only the size when the type name is generic ("Other", "Misc").
  - `QuoteLineItemColour` holds one quantity per colour. A line without colours has a single row whose colour is `""`.
  - `snapshot_costs(quote)` copies `last_unit_cost` from each linked catalogue row onto its line. Lines typed free-hand keep `None`.
- **`serializers.py`**
  - The line serializer blanks the fields that don't belong to the line's kind (so a stale link can't survive) and applies these rules:
    - Colour names must be unique.
    - Quantities must be greater than 0.
    - Whole numbers are required unless the unit is metre.
  - `QuoteSerializer`:
    - Rejects future dates and allows 1–200 lines.
    - `create`:
      1. **locks** the BusinessProfile;
      2. defaults VAT from the profile;
      3. assigns the reference number;
      4. freezes the bank details;
      5. saves the lines;
      6. calls `snapshot_costs`.
    - `update`:
      1. **raises an error if the quote is locked**;
      2. sets `sent_at` when the status changes to sent;
      3. replaces all lines;
      4. calls `snapshot_costs` again. Because the save that marks a quote sent is the last save allowed, the cost freezes at that point.
  - `LINE_COST_FIELDS` / `QUOTE_COST_FIELDS` list the fields that must never reach the customer.
- **`views.py`** — `QuoteViewSet`:
  - Adds `?search=` over customer name and reference number, and pages 50 at a time.
  - Writes audit entries. `perform_update` logs "sent" only on the draft → sent transition.
  - `perform_destroy` refuses to delete a sent quote.
  - `revise` takes the same lock as `create`, then calls `create_revision`.
  - `pdf` is throttled 60/h and serves the file for download (or inline with `?inline=1`).
- **`pdf.py`** — `quote_pdf_bytes` caches each PDF for 24 hours under the key `quote.pk + quote.updated_at + business.updated_at`. Editing the quote or the profile therefore produces a new render. `image_uri` gives WeasyPrint a `file://` path, or a URL on remote storage.
- **`templates/quotes/quote_pdf.html`** + **`templatetags/quote_format.py`** — the printed document. The template filters are `naira`, `naira_or_dash`, `quantity` (which handles plurals), `percent` and `colour_quantity`. **No cost fields appear in the template, and a test checks that.**

### 1.6 `waybills/` — the delivery note
- **`models.py`**
  - `Waybill` is its own record. It uses the `WB-` prefix with independent numbering. Its `quote` link uses SET_NULL, so deleting the quote keeps the waybill. It holds no prices.
  - `from_quote(quote, user)` locks the business, then copies every line and colour quantity. The invoice number defaults to the quote's reference number.
  - `colour_columns` lists every colour in the order it first appears. `totals` sums quantities **per unit**, because coils and metres can't be added together.
  - `WaybillItem.quantity_for(colour)` returns `None` for items that aren't sold by colour; the PDF prints "NA" for those.
- **`serializers.py`** — same line validation as quotes (minus price). A future date is rejected. **Create takes only `{quote: id}`** through `WaybillCreateSerializer`, whose `BusinessQuoteField` is tenant-safe. Update replaces all items; this is how a part delivery is recorded.
- **`views.py`** — the viewset supports a `?quote=` filter. `create` calls `from_quote`. `pdf` reuses the quote module's `PdfRateThrottle`. **`pdf.py`** follows the same caching pattern as quotes, and `templates/waybills/waybill_pdf.html` is a landscape layout with signature lines.

### 1.7 Tests (108 in total; the README count matches)
| File | Test classes |
|---|---|
| `accounts/tests.py` | Auth, Profile (password check on bank changes), Activity, Throttle, SeedData |
| `catalogue/tests.py` | Catalogue, PriceHistory, PriceMovement, UnitChange |
| `purchasing/tests.py` | Costing, PurchaseApi, CostBounds, PurchaseDate, LongName |
| `quotes/tests.py` | QuoteApi, QuoteModel, FormatFilter, QuoteDate, QuoteMargin |
| `waybills/tests.py` | WaybillFromQuote, BrandLogo |

When you want the intended behaviour of a rule, find the test named after it. **Run the tests locally with** `cd backend && DATABASE_URL=sqlite:///test.sqlite3 python manage.py test` (Postgres needs a password this environment doesn't have).

---

## PART 2 — FRONTEND (`frontend/`, React 19 + Vite + React Router 7, no state library)

### 2.1 Boot and routing
- `main.jsx` nests the providers as `BrowserRouter` → `AuthProvider` → `App`.
- `context/AuthContext.jsx` tracks `user` in three states: `undefined` while loading, `null` when signed out, or the user object. On mount it calls `api.me()`, which also sets the CSRF cookie. It listens for the `AUTH_EXPIRED_EVENT` event (fired on any 401) and signs the user out when it arrives. It exposes `login`, `register`, `logout` and `signOutEverywhere`.
- `App.jsx` shows "Loading…" while `user` is undefined. Signed-out users are redirected to `/login`. Signed-in users get `Layout` with these routes: `/`, `/quotes`, `/quotes/new`, `/quotes/:id`, `/quotes/:id/preview`, `/quotes/waybills`, `/quotes/waybills/:id`, `/catalogue`, `/catalogue/accessories`, `/catalogue/purchases` and `/settings`.
  - 🌱 `quotes/waybills` is declared **before** `quotes/:id` so the word "waybills" isn't read as a quote id.
- `components/Layout.jsx` renders a sidebar on desktop, and a hamburger drawer plus a bottom tab bar on phones. `<Outlet/>` is where each page is rendered.

### 2.2 Services (pure logic — the place to start when a number looks wrong)
- **`services/api.js`** — the only place that calls `fetch`.
  - Every non-GET request sends the `X-CSRFToken` header, read from the cookie, and uses `credentials: "same-origin"`.
  - A 401 fires `AUTH_EXPIRED_EVENT`.
  - `firstError()` walks DRF's nested error JSON and returns a message like `"line items › #2 › colours: …"`; `ApiError` carries it.
  - The `api` object has one method per endpoint. `raw: true` returns the `Response` itself, which the PDF code needs.
- **`services/format.js`** — number and date formatting with the `en-NG` locale, plus the unit lists, which **mirror the backend's `QUOTE_UNITS`** (keep both in sync). `round2` rounds to 2 decimal places. `todayIso()` returns today's date in the browser's local time zone.
- **`services/quoteMath.js`** — the quote builder's own live copy of the maths:
  - `findCableType` / `findSize` / `findAccessory` match catalogue entries by name, case-insensitively.
  - `colourNamesFor` returns the colour rows to show: the catalogue type's colours, or the default set for a free-typed cable quoted by colour, plus any extra colours that already hold a quantity.
  - `coloursFor` builds the payload rows and drops zero quantities.
  - `lineTotals`, `quoteTotals`, `unitCostFor` and `marginTotals` give the running figures. **These figures are only a preview; the server's figures are the ones printed.** They round the way the server does (each line to 2 dp, then VAT on the subtotal).
- **`services/pdf.js`** — fetches a PDF as a `File`. `saveFile` downloads it through a temporary `<a download>` link. `canShareFiles()` / `share()` use `navigator.share` (the phone's share sheet) and fall back to a download.
- `hooks/useMediaQuery.js` — the desktop breakpoint is `min-width: 768px`, the same as in `index.css`.

### 2.3 Pages
| Page | What it does |
|---|---|
| `Login.jsx` / `Register.jsx` | Forms that call `useAuth().login` / `register`. |
| `Dashboard.jsx` | Loads the 5 latest quotes, the profile and `priceMovements` in parallel, and shows a sparkline plus the cost movement since the first purchase for each item. |
| `QuoteList.jsx` | Server-side search and "load more" paging, rendered through `QuoteTable`. |
| **`QuoteEditor.jsx`** ⭐ | See 2.4. |
| `QuotePreview.jsx` | An on-screen copy of the PDF, built from **server** figures. It has **Create waybill**, **Download** and **Send on WhatsApp** buttons. On a phone, a successful share PATCHes `status: "sent"`, which locks the quote. On desktop it opens `wa.me` with a message and downloads the PDF, and does **not** mark the quote sent. The payment details fall back to the profile for old quotes. |
| `WaybillList.jsx` / `WaybillEditor.jsx` | The waybill list, and the editor for header fields and per-colour quantities; saving PUTs all items. Also delete, download and share. |
| `Catalogue.jsx` | Cable type cards containing sizes. Prices are edited in place with `InlinePrice`. Includes add/edit/delete for types and sizes, and the `CostNote` and `TrendPanel` components. |
| `Accessories.jsx` | The same idea as a flat list. Its add form stays open so several accessories can be entered in a row. |
| `Purchases.jsx` | `buildOptions` flattens cable sizes and accessories into one pickable list. `PurchaseForm` lets you enter lines (quantity, unit, conversion factor, price) and transport. `linesFrom` turns a saved purchase back into editable lines. `PurchaseRow` expands to show the detail, or to edit or delete. |
| `Settings.jsx` | The profile form. If a bank field changed, it asks for the password and sends it as `current_password`. Also the two `LogoField` uploads, recent activity, and sign out everywhere. |

### 2.4 `QuoteEditor.jsx` + `LineItemCard.jsx` — how the quote builder works
- **State:**
  - `fields` holds the header fields.
  - `items` holds the cards. Each card has a local `key`, `kind`, the catalogue link ids, the names, `unit`, `unit_price` (a string), `quoteByColour`, and `quantities`, a map from colour to a quantity string.
  - `saved` holds the last response from the server.
- **Each render** derives `resolved` from `items`: each item gets its `colours` and `unitCost` added, and `quoteTotals` / `marginTotals` are computed from the result. `locked` is true when `saved.status === "sent"`, and then the whole `<fieldset>` is disabled.
- **Card behaviour:**
  - Picking a cable type fills in the unit and the first matching size, **fills in the price**, and drops colour quantities if the new type isn't sold by colour.
  - Picking a size or an accessory fills in its price.
  - Text that doesn't match the catalogue is marked "custom". The card then shows a unit picker and a "Quote by colour" checkbox, and offers **Add to catalogue**. That calls `addToCatalogue`, which creates the type (if needed) and the size, or the accessory, and links the card to the new row.
- **Save:**
  1. `itemProblem` validates each card on the client.
  2. The payload is built. Prices are sent as `toFixed(2)` strings, never as floats.
  3. The editor POSTs a new quote or PUTs an existing one.
  4. `applySaved` reloads the editor state from the server's response.
  - **Generate PDF** saves first and then navigates to the preview.
  - **Create revision** is offered when the quote is locked.
- 🌱 `QuoteEditorPage` gives the editor `key={id ?? "new"}`, so moving from an existing quote to "New quote" throws away the old state completely.

### 2.5 Components (each is small)
- `Combobox` — a dropdown that also accepts free text.
- `MoneyInput` — shows `₦76,500.00` at rest and the raw number while you type.
- `InlinePrice` — saves on blur or Enter.
- `CostNote` — the last cost and the margin, or "no purchase recorded".
- `TrendPanel` — loads an item's history the first time it is opened, and renders `PriceTrend` (an SVG chart of price against cost; a rising cost is red).
- `Sparkline`, `QuoteTable` (with `StatusBadge`), `DocumentTabs`, `CatalogueHeader`, `Field` and `Icon` (inline SVG paths).
- `index.css` holds all the styling. `fonts.css` loads the self-hosted Inter font from `public/fonts`.

### 2.6 E2E test — `e2e/smoke.mjs`
A Playwright test at phone size. It signs in, builds a quote for 30 red coils of 1.5mm Singles, checks the line total and grand total in the editor and again on the server-rendered preview, and checks the downloaded PDF's filename matches `QT-YYYYMMDD-NNN.pdf`.

---

## PART 3 — DEVOPS / HOSTING (`deploy/`, `.github/workflows/ci.yml`)

### 3.1 Local development
- Run Django on `:8000` and Vite on `:5173`. `vite.config.js` proxies `/api` and `/media` to Django, so the browser sees a single origin and cookies and CSRF just work.
- The backend's system dependency is Pango, which WeasyPrint needs.

### 3.2 Production topology (one Ubuntu 24.04 droplet)
```
:80/:443 nginx ─┬─ /            → frontend/dist (SPA; try_files → index.html)
                ├─ /assets,/fonts → cached for 1 year (hashed filenames)
                ├─ /api/        → 127.0.0.1:8000 gunicorn (systemd: cableerp.service)
                ├─ /static/     → backend/staticfiles
                └─ /media/      → backend/media (uploaded logos)
Postgres (local) · Redis db 1 (throttles + PDF cache) · certbot TLS · ufw · cron backups
```
| File | Key points |
|---|---|
| `setup.sh` | Idempotent, run with sudo. Steps, in order: 1. installs system packages, and Node 20 if missing; 2. adds 2 GB of swap if RAM is under 1 GB; 3. creates the system user `cableerp`; 4. **only if `.env` is missing**, creates the DB role and database and writes `.env` (random DB password, secret key and admin path, `REDIS_URL`, `BEHIND_PROXY=true`); 5. with no `EMAIL` set, adds `SECURE_SSL_REDIRECT=false` and `SECURE_COOKIES=false` so sign-in works over plain HTTP, and removes those lines again once `EMAIL` is given; 6. creates the venv, runs pip, `migrate` and `collectstatic`; 7. seeds the data if there are no users; 8. `npm ci` + build, with the heap capped on small machines (`SKIP_BUILD=1` reuses an existing `dist`); 9. installs the systemd unit and the nginx site (with `sed` substitutions); 10. configures ufw; 11. installs the backup cron job; 12. runs certbot `--redirect`; 13. prints the site URL, admin URL and login. |
| `update.sh` | Deploys to a droplet `setup.sh` already provisioned. Backs up → fast-forwards `main` → pip → prints `migrate --plan` then migrates → `collectstatic` → `rebuild_costs` → stops gunicorn, builds the frontend, restarts → fixes ownership → verifies the service came back. `set -euo pipefail`, so it stops at the first failure; a failed build restarts the service on the old bundle rather than leaving the site down. |
| `cableerp.service` | Runs gunicorn as `cableerp` with `EnvironmentFile=.env`, `Restart=always`, and hardening (`NoNewPrivileges`, `ProtectSystem=full`, `ProtectHome`, `PrivateTmp`). |
| `gunicorn.conf.py` | Binds to localhost only. Runs one worker per 700 MB of RAM (1–3 workers; override with `WEB_WORKERS`), because WeasyPrint uses a lot of memory. The timeout is 120 s, and `max_requests=500` plus jitter recycles workers to release leaked memory. |
| `nginx.conf` | Sets a strict CSP (`script-src 'self'`; `unsafe-inline` for styles only, needed for the colour dots), `nosniff`, `Referrer-Policy` and `Permissions-Policy`. Limits request bodies to 4 m, turns on gzip, and gives `/api` a 120 s read timeout for slow PDFs. HTTPS is required because the phone share sheet only works on secure origins. |
| `backup.sh` | Runs `pg_dump \| gzip`, checks the archive with `gzip -t`, fails if the file is under 1 KB, and deletes backups older than 14 days. The monthly restore drill is written in the file's header. |
| `ci.yml` | **backend:** Postgres 16 → `makemigrations --check` → tests → `check --deploy` → `pip-audit`. **frontend:** `npm ci` → `npm audit` → build. **e2e:** runs after both, seeds the data, starts runserver and Vite, then `npm run e2e`. |

**Operating it:** `journalctl -u cableerp -f` for logs · `systemctl restart cableerp` · `manage.py changepassword <user>` (there is no password reset yet) · `manage.py rebuild_costs`.

**Updating a running droplet:** `sudo /srv/cableerp/deploy/update.sh`. Use `setup.sh` only to
provision a new machine — it is idempotent and will not harm an existing install, but it re-does
swap, packages, nginx and certbot to no purpose.

### 3.3 Deployment failure modes seen in practice
| Symptom | Cause | Fix |
|---|---|---|
| "I pushed but nothing changed" | **There is no CD.** `ci.yml` runs tests only — no deploy job, no webhook. Pushing moves code to GitHub, not to the droplet. | Run `update.sh` on the server. |
| Backend updated, UI unchanged | The frontend build was skipped. The API serves new data while nginx still serves the old bundle — the most confusing failure of the lot, because everything *looks* deployed. | Rebuild `frontend/dist`; hard-reload (`index.html` itself can be cached, the hashed assets cannot). |
| Build dies silently, or `Killed` | OOM. A 512 MB droplet cannot build while gunicorn holds ~130 MB, and `NODE_OPTIONS` above actual RAM makes it worse, not better — Node defers GC it cannot afford. | `update.sh` stops the service and caps the heap at 768 MB under 1 GB of RAM. Confirm with `dmesg -T \| tail`. Fallback: build locally and `rsync dist/` up. |
| `Control server error: Permission denied: '.gunicorn'` | gunicorn 26 wants a dot-directory under the app root; a manual deploy chowns `backend` and `frontend/dist` but not `$APP_DIR` itself. Non-fatal — the worker still boots. | `install -d -o cableerp -g cableerp /srv/cableerp/.gunicorn`. `update.sh` does this. |
| `detected dubious ownership` on `git pull` | Files belong to `cableerp`, git runs as root. | `git config --global --add safe.directory /srv/cableerp`. |
| Assets owned by `root` after a deploy | A typo'd or skipped `chown`. nginx reads them anyway (644/755), so it is silent until the next build. | The `chown -R` in `update.sh`. |

---

## 4. Debugging guide — where to look for each symptom
| Symptom | Look at |
|---|---|
| Totals differ between editor and PDF | `quoteMath.js` vs `quotes/models.py` (`money`, `amount`, `subtotal`) — server wins |
| Margin wrong / missing | `purchasing/costing.py` → run `rebuild_costs`; check `PurchaseItem.landed_unit_cost`; `snapshot_costs` only fills lines linked to a catalogue row |
| "Can't change unit" | `catalogue/serializers.py:validate_unit` (by design) |
| Quote won't save after sending | `QuoteSerializer.update` lock → use `/revise/` |
| 401 loops / signed out | `accounts/authentication.py`, `AUTH_EXPIRED_EVENT`, cookie `Secure` flag over plain HTTP (`DJANGO_SECURE_COOKIES`) |
| 403 CSRF | `DJANGO_CSRF_TRUSTED_ORIGINS` must include exact scheme+host; `MeView` must have run to set cookie |
| 404 on an existing id | Tenant scoping — the object belongs to another business |
| PDF stale / slow / 429 | `pdf.py` cache key, Redis, `pdf` throttle 60/h, gunicorn timeout |
| Logo missing in PDF | `image_uri` (file must exist on disk), 2 MB cap, nginx `/media/` alias |
| Duplicate reference number (IntegrityError) | Missing `select_for_update` on BusinessProfile before `next_reference_number` |
| Deploy: sign-in fails on IP | `.env` plain-HTTP flags; `ALLOWED_HOSTS` |

## 5. Known issues found during review (not yet fixed)
1. **A new quote created as "Sent" has no `sent_at`.** `QuoteSerializer.create` never sets `sent_at`, but the editor's "More details → Status" lets you choose Sent before the first save. The result is a locked quote with no sent date and no "quote sent" audit entry.
2. **Re-running `setup.sh` after deleting `.env`:** the DB role already exists, so `CREATE USER` is skipped, but a **new** random password is written to `.env`. The app then can't connect to the database.
3. **`/etc/cron.d/cableerp-backup` contains `DATABASE_URL`, password included.** Files in `cron.d` are usually world-readable (0644), and the script doesn't `chmod` it.
4. **Anyone can read `/media/` through nginx** without signing in. Only logos live there today, but anything added there later would be public too.
5. **`todayIso()` uses the browser's time zone** while the server uses Africa/Lagos. A browser set to another time zone near midnight could send a date the server rejects as "in the future".
6. `LogoutEverywhereView` checks every live session, so its cost grows with the total number of sessions. That is fine at the current scale.
7. `TESTING = "test" in sys.argv` is fragile: any command with "test" among its arguments turns the production security settings off. This is the one on this list worth fixing first — it is a security control that disables itself on an argument string, and the fix is to key off an explicit environment variable instead.
8. **`average_unit_cost` is computed, stored and never read.** `snapshot_costs` only ever uses `last_unit_cost`, so `cost_basis` has exactly one value in practice (`COST_BASIS_LAST`). Either weighted-average margin is planned — in which case this is scaffolding and the discriminator earns its place — or it is a column and a rebuild path being maintained for nothing. Decide before Phase 4 reporting is built on top of it.

