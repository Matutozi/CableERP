# CableERP — Product Requirements

| | |
|---|---|
| **Product** | CableERP — a vertical ERP for cable distributors in Nigeria |
| **Version** | 1.0 |
| **Date** | 13 September 2026 |
| **Status** | Phase 1 shipped · Phase 2 built, not deployed · Phases 3–6 planned |
| **Owner** | Acme-Oaks Ventures Limited |
| **Repository** | `CableERP` (Django 5.2 + DRF, React 19 + Vite, PostgreSQL) |

---

## Table of contents

1. [Summary](#1-summary)
2. [The problem](#2-the-problem)
3. [Users](#3-users)
4. [Goals and non-goals](#4-goals-and-non-goals)
5. [Product principles](#5-product-principles)
6. [Domain glossary](#6-domain-glossary)
7. [Phase roadmap](#7-phase-roadmap)
8. [Phase 1 — Quote builder](#8-phase-1--quote-builder-shipped)
9. [Phase 2 — Cost and margin](#9-phase-2--cost-and-margin-built-not-deployed)
10. [Phase 3 — Sales and customers](#10-phase-3--sales-and-customers-planned)
11. [Phase 4 — Reporting](#11-phase-4--reporting-planned)
12. [Phase 5 — Inventory](#12-phase-5--inventory-planned)
13. [Phase 6 — Multi-user and SaaS](#13-phase-6--multi-user-and-saas-planned)
14. [Cross-cutting requirements](#14-cross-cutting-requirements)
15. [Architecture](#15-architecture)
16. [Operations](#16-operations)
17. [Known debt and open decisions](#17-known-debt-and-open-decisions)
18. [Appendices](#18-appendices)

---

## 1. Summary

CableERP is software for the specific business of selling electrical cable in Nigeria. It is not a
general ERP with a cable skin on it: it knows that cable is sold by the coil and the metre, that a
coil is 100 metres, that singles come in Red, Black and Yellow/Green, that a quotation is usually
written on a phone at a counter while the customer waits, and that the price of copper moves with
the naira.

It is built in six phases, each of which is useful on its own:

| Phase | What it lets the business do |
|---|---|
| 1 | Quote a customer in a minute and send a professional PDF |
| 2 | Know what the stock cost and what the quote is worth making |
| 3 | Turn accepted quotes into recorded sales, and know who the customers are |
| 4 | See revenue, profit and trends instead of guessing |
| 5 | Know what is in the warehouse without walking into it |
| 6 | Let staff use it, and let other businesses pay for it |

Phase 1 is live. Phase 2 is written and tested but has not been deployed. The rest are specified
here.

**Who this document is for:** whoever builds, maintains, or decides the direction of CableERP —
today that is one owner-developer, later it may be a small team. It assumes familiarity with the
business but not with the code.

---

## 2. The problem

A cable distributor's day is dominated by quoting. A customer walks in or calls, asks for a mix of
sizes and types, and expects a price immediately. The existing process across the industry is some
combination of:

- **A calculator and a paper pad.** Fast, but produces nothing the customer can act on, nothing the
  business can look back at, and arithmetic errors that are discovered at payment time.
- **A Word or Excel template.** Produces a document, but requires a laptop, takes fifteen minutes,
  and every quote is a copy of the last one, so an old price silently follows a new customer.
- **WhatsApp text.** What customers actually want to receive, but nothing is recorded anywhere.

Each of these fails the same three ways:

1. **Prices drift.** There is no single place that says what 2.5mm Flex costs today, so two staff
   quote two prices, or one staff member quotes last month's.
2. **Nobody knows the margin.** Copper is dollar-priced and the naira moves. A price that was 25%
   up on cost in June can be underwater in September, and the business finds out at restock.
3. **Nothing accumulates.** After a year of trading there is no record of what was sold, to whom,
   at what price, or what it cost.

CableERP addresses these in order: Phase 1 fixes the first, Phase 2 fixes the second, Phases 3–5
fix the third.

---

## 3. Users

### 3.1 Primary — the owner-operator

Runs the business, sets prices, chooses suppliers, and does most of the quoting personally. Works
from a **phone** more than a computer: standing in the shop, at a supplier's warehouse, in traffic.
Not a software user by inclination — the app has to be obvious, or it gets abandoned for the
calculator.

Needs: quote fast, look professional, never quote below cost, know where the money went.

### 3.2 Secondary — counter or sales staff *(Phase 6)*

Serves customers and raises quotes. Should see prices, **must not see cost or margin** — that is
the owner's negotiating floor. May not be trusted to change prices or bank details.

### 3.3 Tertiary — the customer

Never logs in. Their entire experience of CableERP is a PDF that arrives on WhatsApp. It must look
like it came from an established business: logo, full details, clear figures, correct arithmetic.

### 3.4 Operating context

These constrain every design decision in this document:

- **Phone-first.** Mobile-first layout is a requirement, not an enhancement. Target width 390px.
- **Patchy connectivity.** Mobile data, often slow. Minimise round trips; no third-party runtime
  dependencies (fonts are self-hosted for this reason).
- **Shared devices.** A shop phone may be handed around, so sessions must end with the browser
  unless "keep me signed in" is chosen.
- **WhatsApp is the delivery channel.** Not email. The share sheet is the intended send path, which
  requires HTTPS.
- **High inflation and FX volatility.** Replacement cost diverges from historic cost quickly. This
  is why Phase 2 tracks both.
- **Naira, kobo, `₦` (U+20A6).** The PDF font must carry the glyph.

---

## 4. Goals and non-goals

### 4.1 Product goals

| ID | Goal | How it is measured |
|---|---|---|
| G1 | A quote takes under a minute on a phone | Time from "New quote" to PDF, 3 line items |
| G2 | Quotes are never arithmetically wrong | Server computes all totals; the client's figures are advisory |
| G3 | The business can always answer "what did this cost me?" | Every catalogue item carries a cost or says plainly it has none |
| G4 | Nothing the customer sees can be wrong retroactively | Quotes are snapshots; sent quotes lock |
| G5 | The owner's cost data never reaches a customer or unauthorised staff | Enforced in code and asserted in tests |
| G6 | Any cable seller can sign up and use it | Multi-tenant from the first commit |

### 4.2 Non-goals

Deliberately out of scope for all six phases:

- **Accounting.** No general ledger, no trial balance, no tax filing. CableERP feeds an accountant;
  it does not replace one.
- **E-commerce.** No customer login, no online ordering, no payment gateway for customers.
- **Manufacturing or cutting optimisation.** No offcut tracking, no reel management.
- **Multi-currency trading.** Naira only. FX appears at most as a recorded rate on a purchase.
- **Logistics.** No route planning, no driver tracking.
- **Offline-first sync.** The app requires connectivity. Offline queues are explicitly not built.

---

## 5. Product principles

These are the rules the existing code follows. New work is expected to follow them, and deviating
from one is a decision to be justified in a pull request.

**P1 — Documents are snapshots.**
Anything a customer has seen is frozen. Quote line items copy the name, unit and price from the
catalogue rather than referencing it; payment details are copied onto the quote when written; costs
are frozen the moment a quote is sent. Editing the catalogue must never change history.

**P2 — The server owns the numbers.**
The frontend computes running totals for responsiveness. The server recomputes everything on save,
and the server's figures are what appear on the PDF. Where the two disagree, the server is right.

**P3 — Unknown is not zero.**
A missing cost produces a missing margin, not a 100% margin. A quote reports how much of itself its
margin figure actually covers. Silence is more honest than a confident wrong number.

**P4 — Fail closed.**
The app refuses to start in production without a secret key. Debug must be asked for explicitly.
Security settings default to the safe value and are relaxed only by explicit environment variables.

**P5 — Tenancy is a query filter, always.**
Every queryset is scoped through `get_business(request)`. Another business's data returns 404, not
403 — existence is not disclosed.

**P6 — Caches are disposable.**
Anything derived and stored (cached costs, rendered PDFs) must be rebuildable from source data by a
management command. A bug in a write path should be something you fix and re-run.

**P7 — Money is `Decimal`, rounded half-up, at the last moment.**
Line amounts are rounded to kobo before summing, so a printed subtotal always equals the sum of the
printed lines. Percentages are derived for display and never stored.

**P8 — The catalogue is a starting point, not a limit.**
Anything can be typed into a quote whether or not it exists in the catalogue, and offered for
addition afterwards. The app must never block a sale because the data isn't set up yet.

---

## 6. Domain glossary

| Term | Meaning |
|---|---|
| **Business** | A tenant. One `BusinessProfile`, owned by one user (Phase 1–5) or several (Phase 6). |
| **Cable type** | A family: Singles, Flat, Flex, Armoured, Retlin. Carries the sale unit and the colour options. |
| **Size** | A variant under a type: "2.5mm", "1.5mm x 3C", "RG6 Coaxial". Carries the price. |
| **Coil** | The standard packaged length, **100 metres**. The usual sale unit for building cable. |
| **Colour variants** | Singles are sold per colour — Red, Black, Yellow/Green — at one price, with a quantity per colour on a quote line. |
| **Generic type** | A catch-all type named Other/Misc, where the size label alone describes the item ("RG6 Coaxial" rather than "RG6 Coaxial Other"). |
| **Accessory** | A non-cable product: sockets, switches, breakers, conduit, tape. Sold per piece, pack, box, roll, length, set or metre. |
| **Quote** | A priced offer to a customer. `QT-YYYYMMDD-NNN`, numbered per business per day. Draft or sent. |
| **Revision** | A fresh draft copied from a sent quote, linked back through `revision_of`. |
| **Purchase / delivery** | A recorded receipt of stock: supplier, date, items, what was paid, plus transport and clearing. |
| **Landed cost** | What a unit actually cost, including its share of transport, expressed in the unit the item is **sold** in. |
| **Replacement cost** | The most recent landed cost — what a refill costs today. The figure quotes are measured against. |
| **Weighted average cost** | Quantity-weighted mean of landed costs. The basis for reporting profit. |
| **Margin** | Price minus cost, in naira and as a percentage of revenue. Always of the costed lines only. |
| **Sale** *(Phase 3)* | A quote the customer accepted, recorded as a transaction. |
| **Stock on hand** *(Phase 5)* | Quantity available, in sale units, per catalogue item. |

---

## 7. Phase roadmap

| Phase | Name | Status | Depends on | Core value |
|---|---|---|---|---|
| 1 | Quote builder | **Shipped** — live on a single droplet | — | Quote fast, look professional |
| 2 | Cost and margin | **Built, not deployed** — on branch `phase-2-cost-and-margin` | 1 | Never sell below cost |
| 3 | Sales and customers | Planned | 1 | Know what was actually sold, and to whom |
| 4 | Reporting | Planned | 2, 3 | Revenue, profit and trends |
| 5 | Inventory | Planned | 2, 3 | Know what is in the warehouse |
| 6 | Multi-user and SaaS | Planned | 1–5 | Staff logins, other businesses, revenue |

**Sequencing rationale.** Phase 2 precedes Phase 3 because cost is cheap to add and immediately
changes every pricing decision, while sales tracking only pays off once there is volume to look at.
Phase 4 must follow both, because there is nothing worth charting until sales are confirmed and
cost is known. Phase 5 is last of the operational phases because stock accuracy depends on both
purchases (in) and sales (out) being trustworthy first. Phase 6 is a data-model change to everything
before it, so it goes last.

---

## 8. Phase 1 — Quote builder *(shipped)*

### 8.1 Goal

A seller sets up their business details and catalogue once, then builds a quotation on their phone
in under a minute and sends it as a PDF.

### 8.2 User stories

- As an owner, I set my business name, address, phones, logo, bank details and standard terms once,
  so every quote carries them without retyping.
- As an owner, I keep a catalogue of what I sell with current prices, so a quote is a few taps.
- As a seller, I build a quote by picking a cable type and size, entering quantities — per colour
  where the cable has colour variants — and watching the total update.
- As a seller, I quote something not in my catalogue by typing it, and add it to the catalogue
  afterwards at the price I used.
- As a seller, I add transport and VAT and see the grand total before I commit.
- As a seller, I generate a PDF and send it on WhatsApp without leaving the app.
- As an owner, I mark a quote as sent and know it can never change afterwards.
- As an owner, I revise a sent quote into a new draft without losing what the customer received.

### 8.3 Functional requirements

| ID | Requirement |
|---|---|
| P1-F1 | Register a business with a username, password and business name; sign in with a session cookie |
| P1-F2 | Edit the business profile: name, address, phone numbers (comma-separated), email, VAT rate, disclaimer, payment terms, quote validity |
| P1-F3 | Upload and remove a logo (PNG/JPG, ≤2 MB), shown on every PDF |
| P1-F4 | Maintain bank details; changing them requires the account password and is written to history |
| P1-F5 | Maintain cable types (name, sale unit, colour variants and their options) and sizes (label, price) |
| P1-F6 | Maintain accessories (name, unit, price) |
| P1-F7 | Edit catalogue prices in place, saving on blur or Enter |
| P1-F8 | Build a quote: customer, date, prepared by, optional staff phone and manufacturer, notes |
| P1-F9 | Add cable lines by picking or typing a type and size; the price fills from the catalogue and stays editable |
| P1-F10 | Enter a quantity per colour where the type has colour variants; otherwise a single quantity |
| P1-F11 | Add accessory lines by picking or typing a name |
| P1-F12 | Offer to add a typed line to the catalogue at the price used |
| P1-F13 | Show a running subtotal, VAT, transport and grand total while editing |
| P1-F14 | Save as draft, or generate a PDF (which saves first) |
| P1-F15 | Assign `QT-YYYYMMDD-NNN`, unique per business per day, under a row lock |
| P1-F16 | Freeze the business's bank details onto the quote at write time |
| P1-F17 | Render a PDF with logo, business details, itemised table, totals, payment details and terms |
| P1-F18 | Preview the quote on screen, download the PDF, or share it to WhatsApp |
| P1-F19 | Mark a quote as sent; sent quotes become read-only and cannot be deleted |
| P1-F20 | Create a revision of a sent quote as a new draft linked back to the original |
| P1-F21 | List quotes with server-side search (`?search=`) and pagination |
| P1-F22 | Record price changes, bank changes and quote events to a per-business history, shown in Settings |
| P1-F23 | Sign out of every device at once |

### 8.4 Data model

```
BusinessProfile  user(1:1) business_name address phone_numbers email logo
                 bank_name account_name account_number
                 disclaimer payment_terms quote_validity vat_rate
CableType        business name unit{coil,metre} has_colour_variants colour_options[] order
CableSize        cable_type size_label default_price order
Accessory        business name unit{piece,pack,box,roll,length,set,metre} default_price order
Quote            business reference_number customer_name date staff_name staff_phone
                 product_manufacturer transport_cost vat_percentage notes
                 status{draft,sent} sent_at revision_of
                 payment_bank_name payment_account_name payment_account_number
QuoteLineItem    quote kind{cable,accessory} cable_size? accessory?
                 cable_type_name size_label item_name unit unit_price order
QuoteLineItemColour  line_item colour quantity
AuditLog         business user action summary reference created_at
```

### 8.5 Business rules

- **Reference numbering.** `QT-` + the quote date as `YYYYMMDD` + a three-digit sequence, per
  business per day. The business row is locked while numbering. Numbers continue past deleted
  quotes rather than being reused.
- **Units and fractions.** Only `metre` quantities may be fractional, to two decimal places.
  Everything else is whole numbers.
- **Rounding.** Each line amount is rounded to kobo (half-up) before summing.
- **Totals.** `grand_total = subtotal + VAT + transport`. VAT applies to the subtotal only, not to
  transport.
- **Generic types.** A type named Other/Others/Misc/Miscellaneous prints the size label alone.
- **Limits.** 200 line items per quote; ₦1bn per unit price; 100,000 per line quantity.
- **Sessions.** End with the browser unless "keep me signed in" is ticked (then 14 days).
- **Rate limits.** Sign-in 10/min per IP, sign-up 20/hour per IP, PDF render 60/hour per user.

### 8.6 Acceptance criteria

- [x] A three-line quote can be built and sent from a phone in under a minute
- [x] The PDF renders `₦` correctly and shows the logo
- [x] Two businesses can both hold `QT-20260911-001`
- [x] Editing a catalogue price does not change any existing quote
- [x] A sent quote returns 400 on edit and on delete
- [x] Another business's quote returns 404
- [x] Unauthenticated API requests return 401

### 8.7 Known gaps carried forward

- No password recovery. Accepted risk: most businesses leave the email field blank and an SMS or
  WhatsApp code needs a provider account. Workaround is `manage.py changepassword`. Resolved in
  Phase 6.
- Uploaded logos are on local disk, not object storage.

---

## 9. Phase 2 — Cost and margin *(built, not deployed)*

### 9.1 Goal

Record what stock cost, and show what every quote is worth making — so a price is never set below
what a refill will cost.

### 9.2 Why this phase, and why now

Cost is the smallest change that makes the app tell the owner something they do not already know.
Everything in Phase 1 is a faster version of what they already do by hand; margin is new
information. It is also cheap: the data model already links every quote line back to its catalogue
entry, precisely so cost could be attached later.

### 9.3 The central design question

*Whose cost, and at what moment?*

**Whose.** Two costs answer different questions, and both are kept:

- **Replacement cost** (`last_unit_cost`) — what a refill costs today. Under a moving naira this is
  what a seller must price against, and it is what quotes are measured on.
- **Weighted average cost** (`average_unit_cost`) — what the stock bought so far averaged out at.
  The honest basis for reporting profit, used from Phase 4.

**At what moment.** Margin computed at read time is a lie that changes on every restock. So cost is
**snapshotted onto the quote**, following principle P1 and the precedent already set by prices,
payment details and reference numbers.

### 9.4 Architecture: ledger plus projection

The purchase ledger is the source of truth. The cost columns on catalogue rows are a **cache** of
what the ledger says, so the quote builder can read a cost without aggregating on every keystroke.
The cache is fully rebuildable (`manage.py rebuild_costs`), satisfying P6.

```
Purchase ──┬── PurchaseItem ──> allocate_landed_cost()  ─┐
           │                                             │
           └── additional_cost (transport, clearing)      │
                                                          v
                              CableSize / Accessory: last_unit_cost, average_unit_cost
                                                          │
                                       snapshot_costs()   v
                              QuoteLineItem.unit_cost  (frozen)
```

### 9.5 Functional requirements

| ID | Requirement |
|---|---|
| P2-F1 | Record a delivery: supplier (free text), date, note, and one or more items |
| P2-F2 | Each item names a catalogue entry, a quantity, the unit it was bought in, and what was paid per that unit |
| P2-F3 | Where the purchase unit differs from the sale unit, capture the conversion (metres per coil) and show the resulting per-sale-unit cost before saving |
| P2-F4 | Remember an item's purchase unit and conversion, so a repeat delivery needs only quantity and price |
| P2-F5 | Capture transport and clearing for the delivery as a whole and allocate it across items by line value |
| P2-F6 | Store each item's landed cost per sale unit |
| P2-F7 | Maintain `last_unit_cost` and `average_unit_cost` on every catalogue row from the ledger |
| P2-F8 | Show cost and margin percentage on every catalogue row, or "no purchase recorded" |
| P2-F9 | List, open, edit and delete recorded deliveries; recalculate costs on every change, including for items removed from a delivery |
| P2-F10 | Snapshot cost onto each quote line on every draft save, and finally when the quote is marked sent |
| P2-F11 | Cost a revision at today's price rather than inheriting the original's |
| P2-F12 | Show margin per quote line and for the quote as a whole |
| P2-F13 | Where some lines have no cost, report coverage ("margin on 6 of 9 items") rather than assuming zero |
| P2-F14 | Record every price change as a point in an item's price history |
| P2-F15 | Chart an item's selling price against its cost over time, with recent changes listed |
| P2-F16 | Show the six most recently restocked items on the dashboard with a cost sparkline and the move since first purchase |
| P2-F17 | Write purchases to the business history |
| P2-F18 | Never expose cost on the quote PDF or preview |

### 9.6 Data model

```
Purchase       business supplier_name date additional_cost note created_by
PurchaseItem   purchase cable_size? accessory? item_name
               quantity entry_unit units_per_entry unit_cost landed_unit_cost order
PriceChange    cable_size? accessory? price changed_by changed_at
CableSize      + purchase_unit units_per_purchase last_unit_cost average_unit_cost
Accessory      + purchase_unit units_per_purchase last_unit_cost average_unit_cost
QuoteLineItem  + unit_cost cost_basis
```

### 9.7 Business rules

- **Unit normalisation.** Cost is always stored per **sale** unit. A coil bought at ₦76,500 and sold
  by the metre costs ₦765 a metre. This is the highest-risk arithmetic in the phase: a wrong
  conversion is wrong by 100×, not by a little.
- **Cost precision.** Four decimal places, because cost is derived rather than charged. A box of 12
  bought for ₦5,000 costs ₦416.6667 each; rounding to kobo would drift the margin on every line.
- **Transport allocation.** Pro-rata by line value, so a ₦300,000 coil carries more of the lorry
  than a ₦2,000 roll of tape. Falls back to allocation by quantity when the goods cost nothing.
- **Replacement cost** is the most recent delivery's landed cost, by purchase date.
- **Weighted average** is quantity-weighted across every recorded delivery. It should narrow to
  stock on hand in Phase 5.
- **Freeze point.** Draft saves re-cost; the save that marks a quote sent is the last one the API
  permits, so that is where figures stop moving.
- **Margin denominator** is the revenue of costed lines only. Percentages are never computed against
  revenue whose cost is unknown.
- **A purchase must name a catalogue entry.** Unlike a quote, free text is not accepted — cost has
  nowhere to live otherwise.

### 9.8 Screens

- **Catalogue → Purchases.** A list of deliveries; tapping one opens its items, transport and note,
  with Edit and Delete. "Record purchase" opens a multi-line form.
- **Catalogue → Cables / Accessories.** Each row gains a cost line and a margin chip; tapping it
  expands a price-versus-cost chart with the recent changes listed.
- **Quote builder.** Margin per line beside each total; margin and coverage in the charges panel.
- **Dashboard.** A "Price movements" panel above recent quotes.

### 9.9 Acceptance criteria

- [x] A coil bought at ₦76,500 and sold by the metre costs ₦765 a metre
- [x] Transport is shared by value, and the allocation sums back to what was paid within a kobo
- [x] Replacement cost tracks the newest delivery while the average reflects quantities
- [x] A sent quote keeps its margin after a restock at a different price
- [x] A draft is re-costed on every save; a revision is costed today
- [x] An uncosted line reports null margin and reduces the quote's coverage figure
- [x] Deleting or editing a delivery recalculates every item it used to touch
- [x] Rendering a quote's PDF produces bytes containing no cost figure
- [x] Another business's purchases, history and movements are unreachable

### 9.10 Out of scope for Phase 2

Suppliers as an entity (free text only), FIFO cost layers, stock quantities, per-colour cost,
role-gating of cost, multi-currency purchases, and reporting.

### 9.11 Deployment status

Phase 2 exists only on the branch `phase-2-cost-and-margin` and on the developer's machine. The
live droplet still serves Phase 1. Deploying requires a commit, a push, and the standard deploy
sequence — plus the two code fixes in §17.

---

## 10. Phase 3 — Sales and customers *(planned)*

### 10.1 Goal

Turn accepted quotes into recorded sales, and give customers an identity of their own. This is the
phase where CableERP stops being a quote builder and becomes a record of the business.

### 10.2 User stories

- As an owner, I mark a quote as accepted and record what was actually sold, which is often not
  exactly what was quoted.
- As an owner, I keep customers as real records with a phone number, so I can see everything one
  customer has ever bought.
- As an owner, I record part payments against a sale and see what is still owed.
- As an owner, I issue a receipt or delivery note as a PDF.
- As an owner, I see which quotes were accepted and which went cold.

### 10.3 Functional requirements

| ID | Requirement |
|---|---|
| P3-F1 | Maintain customers: name, phone numbers, address, email, notes |
| P3-F2 | Pick a customer on a quote, or type a new name and create the customer inline |
| P3-F3 | Migrate existing quotes by keeping their typed name; offer to match it to a customer |
| P3-F4 | Convert a sent quote into a sale, pre-filled from the quote's lines |
| P3-F5 | Edit a sale's lines before confirming — quantities down, prices negotiated, lines dropped |
| P3-F6 | Record the sale's own snapshot of prices and costs, independent of the quote |
| P3-F7 | Record payments against a sale: amount, date, method (cash, transfer, POS), reference |
| P3-F8 | Show outstanding balance per sale and per customer |
| P3-F9 | Sale states: `confirmed` → `part_paid` → `paid`, plus `delivered` and `cancelled` |
| P3-F10 | Produce a receipt PDF and a delivery note PDF |
| P3-F11 | Mark quotes as `accepted`, `declined` or `expired`, and report a conversion rate |
| P3-F12 | Show a customer page: contact details, quotes, sales, total bought, outstanding balance |
| P3-F13 | Compute realised margin per sale from the snapshotted costs |
| P3-F14 | Record sale events in the business history |

### 10.4 Data model

```
Customer   business name phone_numbers address email notes created_at
           (unique name per business, case-insensitive)
Sale       business reference_number{SL-YYYYMMDD-NNN} customer quote?
           date status{confirmed,part_paid,paid,delivered,cancelled}
           transport_cost vat_percentage notes
           payment_* snapshot  delivered_at  created_by
SaleLineItem  sale kind cable_size? accessory? names unit unit_price unit_cost order
SaleLineItemColour  line_item colour quantity
Payment    sale amount date method{cash,transfer,pos} reference note recorded_by
Quote      + customer(FK, null) outcome{open,accepted,declined,expired}
```

### 10.5 Business rules

- **A sale is not a quote.** It is created *from* one but is a separate record with its own lines,
  prices and cost snapshot. The quote remains exactly as the customer received it.
- **Sale references** use the same per-business-per-day scheme as quotes, prefixed `SL-`.
- **Overpayment** is rejected; a payment cannot exceed the outstanding balance.
- **A paid or delivered sale is locked.** Corrections are made by a credit note, not by editing.
  *(Credit notes are Phase 3 scope only if cancellation proves insufficient — see §10.7.)*
- **Cancelling** a sale requires a reason, is recorded in history, and — from Phase 5 — returns
  stock.
- **Customer deletion** is a soft archive; sales must never lose their customer.

### 10.6 Acceptance criteria

- [ ] A sent quote converts to a sale in one tap, with lines pre-filled and editable
- [ ] Changing a sale's quantities does not alter the originating quote
- [ ] Two part payments sum correctly and move the sale to `paid` at the exact balance
- [ ] A payment exceeding the balance is rejected with a clear message
- [ ] A customer page totals every sale and shows the correct outstanding balance
- [ ] Realised margin on a sale uses the sale's own cost snapshot
- [ ] Existing Phase 1 quotes keep their typed customer name after migration

### 10.7 Open questions

- Are **credit notes** needed in Phase 3, or is cancel-and-reissue enough for a business of this
  size? Default position: cancel-and-reissue, revisit if it proves painful.
- Should a sale be creatable **without** a quote (a walk-in who pays cash)? Likely yes — treat the
  quote as optional on `Sale`.
- Does a customer need a **credit limit**? Deferred until there is evidence of credit trading.

---

## 11. Phase 4 — Reporting *(planned)*

### 11.1 Goal

Replace guesswork with figures: revenue, profit, best sellers, trends and margins, over any period.

### 11.2 Functional requirements

| ID | Requirement |
|---|---|
| P4-F1 | Period selector: this week, this month, last month, this year, custom range |
| P4-F2 | Headline figures for the period: revenue, cost of goods, gross profit, margin %, number of sales, average sale value |
| P4-F3 | Revenue and profit over time as a chart, by day, week or month |
| P4-F4 | Top products by revenue, by quantity and by profit |
| P4-F5 | Top customers by revenue and by profit |
| P4-F6 | Margin by product, highlighting anything sold below cost |
| P4-F7 | Quote conversion rate and average time from quote to sale |
| P4-F8 | Outstanding receivables, aged (0–30, 31–60, 60+ days) |
| P4-F9 | Purchase spend by supplier over the period |
| P4-F10 | Export any report as CSV |
| P4-F11 | A compact version of the headline figures on the dashboard |

### 11.3 Technical requirements

Phase 1 and 2 compute `subtotal`, `grand_total`, `total_cost` and `total_margin` as Python
properties over prefetched line items. This is correct at 20 quotes a day and will not survive
aggregate queries over years of sales.

| ID | Requirement |
|---|---|
| P4-T1 | Denormalise `subtotal`, `total_cost`, `total_margin` and `grand_total` onto `Sale` (and `Quote`) at write time — legitimate because these figures are already frozen |
| P4-T2 | Compute every report with database aggregation, never in Python over a queryset |
| P4-T3 | Index `(business, date)` on `Sale` and `Purchase`, and `(business, status)` where filtered |
| P4-T4 | Report responses under 500 ms for a year of data at ten sales a day |
| P4-T5 | Use `average_unit_cost` as the cost basis for profit reporting, and say so on screen |

### 11.4 Acceptance criteria

- [ ] Headline figures reconcile exactly with the sum of the underlying sales
- [ ] A year of data returns in under 500 ms
- [ ] Reports are scoped to the business and never leak across tenants
- [ ] CSV export matches what is on screen, to the kobo
- [ ] Charts render legibly at 390px width

### 11.5 Out of scope

Forecasting, budgets, scheduled email reports, and any report requiring stock valuation (Phase 5).

---

## 12. Phase 5 — Inventory *(planned)*

### 12.1 Goal

Know what is in the warehouse, what it is worth, and what needs reordering — without walking in and
counting.

### 12.2 Why last of the operational phases

Stock is only as accurate as the movements feeding it. Purchases (in) arrive in Phase 2 and sales
(out) in Phase 3. Building stock before both would produce numbers nobody trusts, and an inventory
figure nobody trusts is worse than none.

### 12.3 Functional requirements

| ID | Requirement |
|---|---|
| P5-F1 | Track stock on hand per catalogue item, in sale units |
| P5-F2 | Record an opening stock count per item, with a date |
| P5-F3 | Increment stock on a recorded purchase; decrement on a confirmed sale |
| P5-F4 | Reverse the movement when a purchase or sale is edited, cancelled or deleted |
| P5-F5 | Record manual adjustments with a reason: recount, damage, theft, sample, return |
| P5-F6 | Keep an immutable stock movement ledger — every change, with its source document |
| P5-F7 | Set a reorder level per item and flag anything at or below it |
| P5-F8 | Show a low-stock panel on the dashboard |
| P5-F9 | Warn — but never block — when quoting more than is in stock |
| P5-F10 | Value stock on hand at weighted average cost, and report total stock value |
| P5-F11 | Narrow `average_unit_cost` to goods still on hand, resolving the Phase 2 approximation |
| P5-F12 | Support a stock-take: enter counted quantities, review variances, post adjustments in one action |

### 12.4 Data model

```
StockMovement   business cable_size? accessory? colour?
                quantity(+/-) reason{purchase,sale,adjustment,opening,cancellation}
                purchase? sale? adjustment_note created_by created_at
CableSize       + stock_on_hand reorder_level
Accessory       + stock_on_hand reorder_level
```

`stock_on_hand` is a cache of the movement ledger, rebuildable per P6.

### 12.5 Business rules

- **The ledger is the truth**, the balance is a projection. `manage.py rebuild_stock` replays it.
- **Negative stock is allowed** and surfaced as a warning. Refusing to record a real sale because
  the data is behind reality would break principle P8.
- **Movements are immutable.** A correction is a new, opposing movement, never an edit.

### 12.6 Open questions

- **Is stock tracked per colour?** Singles are physically separate coils per colour, so probably
  yes for colour-variant types and no for everything else. This is the main modelling decision of
  the phase and should be settled with a count of how the warehouse is actually organised.
- **Are coil and metre stocks the same pool?** If a coil is cut, 100 metres enter the metre pool.
  This needs an explicit "break a coil" movement or a rule that stock is always held in the smaller
  unit.

### 12.7 Acceptance criteria

- [ ] Recording a purchase increases stock by the sale-unit quantity
- [ ] Confirming a sale decreases it; cancelling restores it
- [ ] `rebuild_stock` reproduces every balance exactly from the ledger
- [ ] A stock-take posts one adjustment per varying item and leaves the rest untouched
- [ ] Weighted average cost reflects only goods on hand
- [ ] Quoting beyond stock warns and still saves

---

## 13. Phase 6 — Multi-user and SaaS *(planned)*

### 13.1 Goal

Let a business have staff, let those staff see only what they should, and let CableERP be sold to
other cable sellers.

### 13.2 Why it is last

It changes the data model of everything before it. `BusinessProfile` currently has a one-to-one
relationship with a user; multi-user makes it one-to-many through a membership with a role, and
every "who did this" field in the system starts meaning something. That is a migration across six
phases of data, and it is cheaper once the domain has stopped moving.

### 13.3 Functional requirements

#### Users and roles

| ID | Requirement |
|---|---|
| P6-F1 | Several users per business, via a membership record carrying a role |
| P6-F2 | Roles: **owner** (everything), **manager** (everything except bank details and user management), **sales** (quotes and customers only) |
| P6-F3 | Invite a user by phone or email; they set their own password |
| P6-F4 | Suspend or remove a member without deleting their history |
| P6-F5 | **Hide cost and margin from the sales role** everywhere: API payloads, catalogue, quote builder, dashboard, reports |
| P6-F6 | Restrict price changes to owner and manager |
| P6-F7 | Restrict bank detail changes to the owner |
| P6-F8 | Name the responsible person on every history entry |
| P6-F9 | Let a user belong to more than one business and switch between them |

#### Account recovery

| ID | Requirement |
|---|---|
| P6-F10 | Password reset by SMS or WhatsApp code — the channel Nigerian users actually have |
| P6-F11 | Email reset as a fallback where an address exists |
| P6-F12 | Rate-limit reset requests and expire codes after ten minutes |
| P6-F13 | Let an owner reset a staff member's password directly |

#### Onboarding and billing

| ID | Requirement |
|---|---|
| P6-F14 | Self-serve sign-up with a guided first-run: business details, then a starter catalogue |
| P6-F15 | Offer the standard Nigerian cable catalogue as a starting point, editable |
| P6-F16 | Free trial, then a subscription |
| P6-F17 | Take payment through a Nigerian processor (Paystack or Flutterwave) |
| P6-F18 | Plan tiers by user count and feature set; enforce limits |
| P6-F19 | Restrict to read-only on lapse rather than locking data away |
| P6-F20 | Export all of a business's data on request |

### 13.4 Data model

```
Membership   business user role{owner,manager,sales} status{active,suspended}
             invited_by joined_at
Invitation   business phone? email? role token expires_at accepted_at
Subscription business plan status trial_ends_at current_period_end
             processor_customer_id processor_subscription_id
PasswordReset user channel{sms,whatsapp,email} code_hash expires_at used_at
BusinessProfile  − user(1:1)          # replaced by Membership
AuditLog         user becomes meaningful rather than always the owner
```

### 13.5 Security requirements

| ID | Requirement |
|---|---|
| P6-S1 | Cost fields are gated in one place per serializer (`LINE_COST_FIELDS`, `QUOTE_COST_FIELDS`, `COST_FIELDS` already exist for this purpose) |
| P6-S2 | A test asserts a sales-role payload contains no cost key, on every endpoint that can carry one |
| P6-S3 | Role is checked server-side on every write; hiding a button is not a control |
| P6-S4 | A user removed from a business loses access immediately, including existing sessions |
| P6-S5 | Reset codes are stored hashed and are single-use |

### 13.6 Acceptance criteria

- [ ] A sales user can raise a quote and never sees a cost anywhere, including in raw API responses
- [ ] A manager can change prices but not bank details
- [ ] Removing a member ends their sessions
- [ ] A password can be recovered without administrator involvement
- [ ] A new business can sign up and produce its first quote without support
- [ ] A lapsed subscription restricts writes but never hides existing data

---

## 14. Cross-cutting requirements

These apply to every phase, and a phase is not done until it meets them.

### 14.1 Money

| ID | Requirement |
|---|---|
| X-M1 | All money is `Decimal`. Floats never touch a monetary value on the server |
| X-M2 | Rounding is half-up, to kobo, at the line, before summing |
| X-M3 | Cost carries four decimal places because it is derived, not charged |
| X-M4 | Percentages are derived for display and never stored |
| X-M5 | Every displayed total equals the sum of its displayed parts |
| X-M6 | Every stored monetary field has explicit bounds, **including derived ones** |

### 14.2 Security

| ID | Requirement |
|---|---|
| X-S1 | Session authentication with CSRF protection on every unsafe method, including sign-in |
| X-S2 | HTTPS in production, with secure cookies and HSTS. No exceptions once a domain exists |
| X-S3 | Every queryset scoped to the signed-in business; cross-tenant access returns 404 |
| X-S4 | Related-object fields resolve only within the business, so a forged id fails validation |
| X-S5 | Rate limits on authentication, on expensive reads, and on writes that cascade |
| X-S6 | Admin served from a non-default path |
| X-S7 | Secrets only from the environment; no secret in git, ever, including examples |
| X-S8 | Content-Security-Policy, `nosniff`, `Referrer-Policy` and `Permissions-Policy` on every response |
| X-S9 | No `dangerouslySetInnerHTML`, `eval`, or `innerHTML` assignment in the frontend |
| X-S10 | Dependency audit on every push (`pip-audit`, `npm audit`) |

### 14.3 Privacy

| ID | Requirement |
|---|---|
| X-P1 | Cost and margin never appear in any customer-facing artefact. Asserted against rendered PDF bytes, not just reviewed |
| X-P2 | Customer contact details are never sent to a third party |
| X-P3 | Error tracking sends no personal data (`send_default_pii=False`) |
| X-P4 | A business can export and delete its own data |

### 14.4 Performance

| ID | Requirement |
|---|---|
| X-F1 | Any screen usable within 2 seconds on 3G after first load |
| X-F2 | No N+1 queries on any list endpoint; verified with query counts, not by eye |
| X-F3 | A screen makes one request where one will do, rather than one per row |
| X-F4 | PDF rendering cached per version of the quote and the business profile |
| X-F5 | Frontend bundle under 400 kB before gzip |
| X-F6 | Reports aggregate in the database |

### 14.5 Mobile and accessibility

| ID | Requirement |
|---|---|
| X-A1 | Every screen works at 390px with no horizontal scroll |
| X-A2 | Touch targets at least 40px |
| X-A3 | Numeric fields use the right `inputMode`, so phones show the right keypad |
| X-A4 | Every control is reachable and operable by keyboard, with a visible focus state |
| X-A5 | Text contrast meets WCAG AA, including 12px hints — the app is used outdoors |
| X-A6 | Colour is never the only carrier of meaning; a margin shows a sign and a number, not just red |

### 14.6 Data integrity

| ID | Requirement |
|---|---|
| X-D1 | Anything the customer has seen is immutable |
| X-D2 | Every derived store is rebuildable by a management command |
| X-D3 | Every money-affecting change is written to the business history, naming the change |
| X-D4 | Dates that cannot be real are rejected at the boundary |
| X-D5 | Deleting a catalogue entry never deletes history; links become null |

### 14.7 Testing

| ID | Requirement |
|---|---|
| X-T1 | Every business rule in this document has a test asserting it |
| X-T2 | Every endpoint has a cross-tenant test |
| X-T3 | Every privacy invariant has a test against the rendered artefact |
| X-T4 | A browser smoke test covers the critical path end to end |
| X-T5 | CI runs tests, migration checks, `check --deploy`, dependency audits, a frontend build and the smoke test |

---

## 15. Architecture

### 15.1 Stack

- **Backend** — Django 5.2 (LTS), Django REST Framework, PostgreSQL, WeasyPrint for PDFs,
  Gunicorn behind nginx.
- **Frontend** — React 19, Vite, React Router. No state library, no data-fetching library, no
  TypeScript. One context, for the signed-in user.
- **Auth** — Django session cookies plus CSRF. Same-origin throughout: Vite proxies `/api` in
  development, nginx does it in production.

### 15.2 Why these choices

- **Session auth over JWT.** The client is a browser on the same origin. Sessions are revocable,
  which matters for "sign out everywhere" and for Phase 6 member removal. A JWT would have to be
  short-lived and refreshed to achieve the same thing, for no benefit.
- **Server-rendered PDFs.** The document is the product; it must look identical everywhere and must
  not depend on the phone's browser.
- **No frontend framework beyond React Router.** The app is nine screens. Every dependency is a
  thing to update and a thing that can break on a weak connection.
- **PostgreSQL.** Decimal arithmetic, row locking for reference numbering, and real constraint
  enforcement. SQLite is acceptable for local trials but silently accepts values Postgres rejects.

### 15.3 Backend layout

```
config/       settings (environment-driven, fail-closed), root URLs
accounts/     auth endpoints, BusinessProfile, AuditLog, seed_data
catalogue/    CableType, CableSize, Accessory, PriceChange, history endpoints
quotes/       Quote, QuoteLineItem, QuoteLineItemColour, PDF rendering
purchasing/   Purchase, PurchaseItem, costing.py, rebuild_costs
sales/        (Phase 3) Customer, Sale, Payment
inventory/    (Phase 5) StockMovement
```

### 15.4 Frontend layout

```
pages/        Login Register Dashboard QuoteList QuoteEditor QuotePreview
              Catalogue Accessories Purchases Settings
components/   Layout LineItemCard QuoteTable CatalogueHeader Combobox
              MoneyInput InlinePrice CostNote PriceTrend TrendPanel Sparkline Field Icon
services/     api.js (fetch + CSRF) format.js quoteMath.js pdf.js
context/      AuthContext
hooks/        useMediaQuery
```

### 15.5 Conventions

- One serializer per representation; list and detail serializers differ where payload size matters.
- Business scoping lives in `get_queryset`, never in a view body.
- Cross-app imports go one way: `purchasing` and `quotes` depend on `catalogue`, never the reverse.
  Where a reverse reference is unavoidable, it is a local import inside the function, with a comment.
- Every non-obvious decision carries a comment explaining **why**, not what.

---

## 16. Operations

### 16.1 Environments

| Environment | Where | Database | Purpose |
|---|---|---|---|
| Development | Developer machine | SQLite or local Postgres | Building |
| Production | DigitalOcean droplet, 512 MB | PostgreSQL | The live business |

A staging environment does not exist and is not currently justified for a single-business
deployment. It becomes necessary at Phase 6.

### 16.2 Configuration

Every environment-specific value is an environment variable, read from `backend/.env`, which is
never committed. `DJANGO_SECRET_KEY` is mandatory unless `DJANGO_DEBUG=true`; the app refuses to
start without it. Full table in `README.md`.

### 16.3 Deployment

`deploy/setup.sh` provisions a fresh Ubuntu droplet: system packages, PostgreSQL, the virtualenv,
nginx, systemd, swap, and certbot when a domain is supplied. Subsequent deploys are pull, install,
migrate, collectstatic, build, restart.

### 16.4 Operational requirements

| ID | Requirement | Status |
|---|---|---|
| X-O1 | Nightly database backup, verified and pruned | Script exists, **not scheduled** |
| X-O2 | Backups copied off the droplet | **Not done** |
| X-O3 | Restore drill performed monthly | **Never done** |
| X-O4 | Error tracking with no personal data | Supported, DSN unset |
| X-O5 | Shared cache (Redis) once more than one worker runs | Supported, unset |
| X-O6 | Uploaded media on durable storage | **Local disk only** |
| X-O7 | Certificate auto-renewal | Blocked on having a certificate |

### 16.5 Monitoring

Minimum viable, and currently absent: an uptime check against `/api/auth/me/`, disk usage alerting
(a full disk breaks PostgreSQL first and silently), and memory alerting (WeasyPrint is the largest
consumer on a 512 MB box, and an out-of-memory kill presents as a 502).

---

## 17. Known debt and open decisions

### 17.1 Must fix before Phase 2 is deployed

| ID | Issue | Severity |
|---|---|---|
| D1 | **No TLS on the live server.** Session cookies and bank details cross the network in the clear. Blocked on buying a domain | High |
| ~~D2~~ | ~~Derived cost is unbounded~~ — **fixed.** The delivery's arithmetic now runs in the serializer before anything is saved; an impossible cost per unit is refused by name, and the save and recalculation share one transaction | ~~High~~ |
| ~~D3~~ | ~~Purchase dates are not sanity-checked~~ — **fixed.** Future dates are refused on deliveries and on quotes | ~~Medium~~ |
| ~~D6~~ | ~~Changing a catalogue item's sale unit left recorded costs describing a different unit~~ — **fixed.** Refused while purchases exist | ~~Medium~~ |
| ~~D7~~ | ~~Editing a delivery silently dropped lines whose catalogue entry had been deleted~~ — **fixed.** The line is flagged and the save refused until it is replaced or removed | ~~Medium~~ |
| ~~D8~~ | ~~`PurchaseItem.item_name` could exceed its column (`DataError` on PostgreSQL)~~ — **fixed.** Widened to fit the longest name the catalogue can build | ~~Low~~ |
| ~~D9~~ | ~~The purchases list had no pagination, so deliveries past the first 50 were unreachable~~ — **fixed.** Load-more, matching the quote list | ~~Low~~ |
| D4 | **Editing a delivery logs as "Purchase recorded"** and keeps no before-and-after | Medium |
| D5 | **No rate limits on Phase 2 endpoints** | Medium |

### 17.2 Accepted, with reasons

| Issue | Why it is accepted | Resolved in |
|---|---|---|
| No password recovery | Needs a message provider; most businesses leave email blank | Phase 6 |
| Cost visible to every user of a business | There is one user today, and the gate is designed | Phase 6 |
| Weighted average covers all purchases, not stock on hand | Requires stock quantities | Phase 5 |
| Logos on local disk | Small, and backed up with the box once backups run | Phase 6 |
| Single droplet, single disk | Cost. The mitigation is off-box backups, not redundancy | — |

### 17.3 Open decisions

| # | Decision | Default position |
|---|---|---|
| 1 | Is stock tracked per colour, or per size? | Per colour for colour-variant types only. Confirm against the warehouse |
| 2 | Are coil and metre stock the same pool? | Hold stock in the smaller unit; add an explicit "break a coil" movement |
| 3 | Credit notes in Phase 3, or cancel-and-reissue? | Cancel-and-reissue until it proves painful |
| 4 | Can a sale exist without a quote? | Yes — `Sale.quote` is nullable |
| 5 | Record an FX rate on purchases? | Two columns, cheap, high value under a moving naira. Add when the first dollar purchase is recorded |
| 6 | Stay on Django 5.2 LTS or move to 6.x? | Stay on LTS; revisit at each LTS boundary as a decision, not drift |
| 7 | Is per-line margin shown in the quote builder, or totals only? | Per line. Revisit if cost is being read over the seller's shoulder at a counter |

---

## 18. Appendices

### A. Units

| Unit | Applies to | Fractional? | Notes |
|---|---|---|---|
| `coil` | Cable | No | 100 metres |
| `metre` | Cable, accessories | Yes, 2 dp | The only fractional unit |
| `piece` | Accessories | No | Default for accessories |
| `pack` `box` `roll` `length` `set` | Accessories | No | |

### B. Reference numbers

- Quotes: `QT-YYYYMMDD-NNN`
- Sales *(Phase 3)*: `SL-YYYYMMDD-NNN`

Numbered per business per day, assigned under a lock on the business row, using the document's own
date. Unique per business, not globally — two businesses may both hold `QT-20260911-001`. Numbers
continue past deleted documents rather than being reused.

### C. Seed catalogue

`manage.py seed_data` creates **Acme-Oaks Ventures Limited** (user `acmeoaks`) with Wema Bank
details, a 7.5% VAT rate, and six cable types:

| Type | Unit | Colours | Sizes |
|---|---|---|---|
| Singles | coil | Red, Black, Yellow/Green | 1mm – 35mm (9 sizes) |
| Flat | coil | — | 1mm x 2C – 2.5mm x 3C (4) |
| Flex | coil | — | 1.5mm x 3C – 6mm x 4C (7) |
| Other | coil | — | RG6 Coaxial, Cat6 Ethernet |
| Armoured | metre | — | 16mm |
| Retlin | metre | — | (none yet) |

Re-running is safe: edited prices are kept unless `--reset-prices` is passed. Accessories are not
seeded — they vary too much between sellers.

### D. HTTP status conventions

| Code | Meaning in CableERP |
|---|---|
| 200 / 201 / 204 | Success |
| 400 | Validation failure. Body carries field-level messages the UI surfaces verbatim |
| 401 | Not signed in, or the session expired. The app redirects to sign-in |
| 403 | CSRF failure. In practice a cookie or origin problem, not a permission one |
| 404 | Not found **or** belongs to another business. Deliberately indistinguishable |
| 429 | Rate limited |
| 500 | A bug. Traceback in `journalctl -u cableerp` |

### E. Change log

| Version | Date | Change |
|---|---|---|
| 1.0 | 13 Sep 2026 | First consolidated PRD. Phases 1–2 documented as built; 3–6 specified |
