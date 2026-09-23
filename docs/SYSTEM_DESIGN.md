# CableERP — System Design Handbook

## What this file is

`CODEBASE_GUIDE.md` explains **what each file does**. This file explains **why it was built that way**.

Every entry is one question a reader might ask while reading the repo, answered by pointing at the
implementation and giving the reasoning — including the alternatives that were rejected and what
breaks if the decision is reversed.

## The rule

**No code change lands without its handbook entry.**

- **Before a build:** add the entry for the decision you are about to implement. Writing the reasoning
  down first is how you find out the decision is wrong while it is still cheap.
- **After a build:** correct the entry to match what was actually built. Plans drift; the handbook
  describes the code that exists, never the code that was intended.

Entry format:

```
### Q<n>. <The question, as a reader would ask it>
**Where:** file:line
**Decision:** one sentence.
**Reasoning:** why, including what was rejected.
**Breaks if changed:** the concrete failure.
```

An entry that cannot name a concrete failure under "Breaks if changed" is usually describing a
preference, not a design decision. Say so plainly rather than inventing a consequence.

---

## Part 1 — Tenancy and access

### Q1. Why is `BusinessProfile` the tenant instead of a dedicated `Tenant` model?
**Where:** `accounts/models.py:14`
**Decision:** The seller's business profile doubles as the tenant boundary.
**Reasoning:** The product launched for single-operator cable sellers. One business, one login, one
set of data — a separate tenant table would have been an empty layer of indirection.
**Breaks if changed:** Nothing today, but it is why `user` is a `OneToOneField`, which blocks
employees, multiple owners and a platform superadmin. This is the known cost of the original
simplification, and paying it down is the first phase of the platform work.

### Q2. Why does another business's record ID return 404 and not 403?
**Where:** `accounts/utils.py:get_business()`, every viewset's `get_queryset`
**Decision:** Tenant scoping happens in the queryset, so out-of-tenant rows are invisible rather than
forbidden.
**Reasoning:** A 403 confirms the record exists. That leaks the existence of other businesses'
quotes and lets an attacker enumerate IDs. Filtering in `get_queryset` makes the object genuinely
absent, and the 404 falls out naturally.
**Breaks if changed:** Checking ownership *after* fetching, and raising 403, turns every endpoint
into an existence oracle. Every app has a test asserting the 404 — see
`catalogue/tests.py:101`, `quotes/tests.py:278`, `waybills/tests.py:152`, `purchasing/tests.py:151`.

### Q3. Why sessions and CSRF rather than JWT?
**Where:** `config/settings.py` (`DEFAULT_AUTHENTICATION_CLASSES`), `accounts/authentication.py`
**Decision:** Session cookie plus CSRF token, served same-origin.
**Reasoning:** The SPA is served from the same origin as the API — the Vite proxy in development,
nginx in production. Same-origin means no CORS and no token storage, so there is no refresh-token
rotation to get wrong and nothing for XSS to steal from `localStorage`. Django's session handling is
already audited; a hand-rolled JWT flow would not be.
**Breaks if changed:** Serving the API from a different origin brings back CORS, preflight and
`SameSite` cookie problems that this design exists to avoid.

### Q4. Why does DRF answer 401 here when its default is 403?
**Where:** `accounts/authentication.py`
**Decision:** Override `authenticate_header` so unauthenticated requests get 401.
**Reasoning:** The frontend needs to tell "your session expired, sign in again" apart from "you are
signed in but may not do this". DRF conflates both as 403 when no `WWW-Authenticate` header is set.
**Breaks if changed:** `AuthContext` can no longer detect expiry, and users get a permission error
instead of a sign-in prompt.

### Q19. Why does `Membership` carry a stored permission set instead of a role the code looks up?
**Where:** `accounts/models.py:Membership` *(being built — D1)*
**Decision:** A role is a **preset that fills a permission set at write time**. The granted
permissions are stored on the membership row; the role name is a label recording which preset was
used, and is never consulted when deciding access.
**Reasoning:** PRD P6-F2 requires that changing a preset later must not retroactively grant access
to existing members. If `role == "manager"` were evaluated live, then widening the manager preset in
a future release would silently hand every existing manager the new capability — a privilege
escalation shipped as a feature. Storing the set means an existing member keeps exactly what they
were granted, and an owner who wants them to have more must grant it deliberately. It also satisfies
P6-F2a: per-feature access at invite time is just a different starting set, not a different
mechanism.
**Breaks if changed:** Resolving permissions from the role name at request time makes every preset
edit a retroactive, silent grant across every business on the platform, with no audit trail showing
who gained what.

### Q20. Why does `get_business()` keep working during the membership migration?
**Where:** `accounts/utils.py:get_business()`
**Decision:** The helper resolves a membership first and falls back to the legacy
`user.business_profile` one-to-one while both exist.
**Reasoning:** Every viewset in every app scopes through this one function (Q2), which is what makes
the tenancy change cheap — but it also means a breaking change here breaks all of them at once. A
fallback lets the `Membership` rows be created and backfilled in one deploy, and the one-to-one
removed in a later one, with the app serving traffic throughout.
**Breaks if changed:** Cutting over in a single step means any user whose membership row failed to
backfill is locked out of their own data with a `PermissionDenied`, and the only way back is a
restore.

---

## Part 2 — The money rules

These three answer most questions about the data model. Read them together.

### Q5. Why is cost stored on the catalogue row when purchases are the source of truth?
**Where:** `catalogue/models.py:CostedItem`, written only by `purchasing/costing.py`
**Decision:** `last_unit_cost` and `average_unit_cost` are a **cache** of the purchase ledger.
**Reasoning:** Margin has to render in a list of fifty catalogue rows on a phone. Recomputing from
the ledger per row per request is too slow. The cache is safe because it is rebuildable —
`manage.py rebuild_costs` recomputes every value from the purchases.
**Breaks if changed:** Nothing, as long as the invariant holds: **only `costing.py` writes these
fields**. The moment anything else writes cost directly, the ledger stops being the source of truth
and a rebuild silently destroys data. A bug in the write path is a re-run, not a data loss — but
only while this holds.

### Q6. Why does a quote copy the bank details instead of reading them from the profile?
**Where:** `quotes/models.py:59-62`, migrations `quotes/0003` and `0004`
**Decision:** Payment details are snapshotted onto the quote when it is written.
**Reasoning:** A quote is a historical claim made to a customer on a date. If changing your bank
details silently rewrote last month's PDF, that is a forgery, not a feature. The same reasoning
covers prices, item names and cost.
**Breaks if changed:** Reading live profile data at render time means reprinting an old quote
produces a different document than the customer received. In a payment dispute, the business cannot
prove what it sent.

**The general rule this comes from:** operational data is *derived*, document data is *frozen*.
When adding a field, decide which kind it is before writing the migration. Catalogue rows and cost
are derived. Quotes and waybills are frozen.

### Q7. Why is an unknown cost `null` rather than `0`?
**Where:** `catalogue/models.py` (`margin_percentage` returns `None`), `quotes/models.py:snapshot_costs`
**Decision:** Missing cost is `null`, and margin against it is `null`.
**Reasoning:** A missing cost is not a free item. Zero would make a free-typed quote line show 100%
margin, which reads as the most profitable line on the quote. The UI must say "unknown" instead.
**Breaks if changed:** Defaulting to zero produces confidently wrong profit figures — worse than no
figure, because the seller acts on it.

### Q8. Why does `validate_unit` refuse to change a unit once costs exist?
**Where:** `catalogue/serializers.py` (`UNIT_CHANGE_REFUSED`)
**Decision:** A cable type's or accessory's unit is frozen once priced purchases exist.
**Reasoning:** Stored costs are denominated in that unit — "per coil" or "per metre". There is no
way to convert historical costs when the unit changes, because the conversion factor was a property
of each past delivery, not of the item.
**Breaks if changed:** Every historical cost silently becomes wrong by a factor of ~100, and there
is no way to detect it afterwards.

### Q9. Why does the frontend duplicate the server's arithmetic?
**Where:** `frontend/src/services/quoteMath.js` vs `quotes/serializers.py`
**Decision:** Deliberate duplication of total calculation on both sides.
**Reasoning:** Totals must move on every keystroke on a phone on a poor connection. A round trip per
keystroke is unusable in a market stall.
**Breaks if changed:** Nothing, provided the asymmetry is respected: **the server is authoritative**.
It recomputes every total from scratch and never trusts client figures. If the two disagree, the PDF
is right and the client is wrong.

---

## Part 3 — Documents and numbering

### Q10. Why are reference numbers not reused after a delete?
**Where:** `accounts/numbering.py:next_reference_number`
**Decision:** The next number is `highest for that day + 1`, not `count + 1`.
**Reasoning:** Reference numbers appear on documents sent to customers. Reissuing `QT-20260923-003`
to a second customer after deleting the first means two different documents share a reference.
**Breaks if changed:** Ambiguous references in a dispute, and a unique-constraint violation on the
second save.

**The concurrency requirement:** callers must hold `select_for_update()` on the `BusinessProfile`
row. Two saves in the same moment otherwise take the same number. The database unique constraint is
the backstop, not the mechanism — it turns a duplicate into an error rather than preventing it.

### Q11. Why does the PDF render on the server rather than in the browser?
**Where:** `quotes/pdf.py`, `waybills/pdf.py`
**Decision:** WeasyPrint renders server-side, cached in Redis for 24 hours.
**Reasoning:** The output must be identical for every recipient and must not depend on the phone's
fonts or browser. It is also the document of record.
**Breaks if changed:** Nothing functionally, but note the cost: WeasyPrint is the memory hog that
sizes the whole droplet, and the `pdf` throttle (60/hour/user) exists because a render is the most
expensive thing one request can ask for.

**Cache key design:** `quote-pdf:{pk}:{quote.updated_at}:{business.updated_at}`. Primary keys are
global across the shared table, so tenants cannot collide. But note the constraint: **those two
timestamps are the only invalidation inputs.** Anything else that changes what the document renders —
a per-tenant branding flag, a module that adds a template block — must be added to the key.

### Q12. Why does a waybill drop every price?
**Where:** `waybills/models.py`, `templates/waybills/waybill_pdf.html`
**Decision:** A waybill copies the quote's lines and carries no prices at all.
**Reasoning:** The driver carries it, and the customer's staff see it on delivery. Prices on a
delivery note expose the seller's pricing to whoever is in the yard.
**Breaks if changed:** Commercially damaging, not technically. This is a business rule expressed in
the schema, which is why prices are absent rather than merely hidden in the template.

---

### Q21. Why can a business not change its own store allowance?
**Where:** `accounts/models.py:BusinessProfile.store_limit` *(being built)*
**Decision:** `store_limit` is set by a platform operator through the Django admin. It is readable
through the API and writable nowhere in it, for any role — owner included.
**Reasoning:** A limit the limited party can raise is not a limit, it is a preference with extra
steps. The allowance is the shape a commercial lever takes (PRD P6-F18, plan tiers enforcing
limits), so it has to sit outside the customer's reach or it can never be priced. Setting it
per-business rather than deriving it from a plan is deliberate for now: `Subscription` does not
exist, and a plain integer on the profile is the smallest thing that is still enforceable. When
plans arrive, the plan supplies the default and this field becomes the per-customer override,
which is a widening rather than a rewrite.
**Breaks if changed:** Exposing it on `BusinessProfileSerializer` as writable lets any owner grant
themselves unlimited stores, and every downstream billing decision built on the allowance becomes
unenforceable — silently, because nothing errors.

### Q22. What happens when a business ends up over its store allowance?
**Where:** `accounts/models.py:BusinessProfile.is_over_store_limit`, enforced in the write path
**Decision:** Lowering the allowance below the number of active stores is **permitted**, and puts
the business into a restricted state: reads and PDFs continue, ordinary writes are refused, and the
only write still accepted is deactivating a store. It clears itself the moment active stores are
back within the allowance.
**Reasoning:** The operator has to be able to lower an allowance without first negotiating which
branch a customer gives up — a downgrade that the customer can block is not a downgrade. But the
system must not choose the branch either: deactivating the wrong store would strand quotes,
waybills and per-store costs belonging to a live part of the business. Restricting until the owner
picks puts the decision with the only party who knows which branch matters, while making it
impossible to ignore. Rejecting the change outright was considered and rejected for the first
reason; a soft cap that only blocks new stores was rejected because it lets a business sit over
quota indefinitely, which makes the allowance unenforceable in exactly the way Q21 guards against.
These are the same semantics as a lapsed subscription (D5), deliberately — one restricted state,
not two.
**Breaks if changed:** Auto-deactivating the newest or lowest-numbered store to fit silently
detaches a branch's documents and cost history, with no record of who decided it or why.

### Q23. How is a member's store access expressed, and why both a flag and a set?
**Where:** `accounts/models.py:Membership.all_stores` + `Membership.stores` *(being built)*
**Decision:** Two fields. `all_stores` is a stored boolean meaning every store in the business,
including ones created later. `stores` is a many-to-many holding an explicit subset, used when
`all_stores` is false. Both are filled from the role preset at invite time and then stored, exactly
as `permissions` is.
**Reasoning:** The requirement is that staff cannot see another branch's trade, because
cross-branch visibility is how a person builds a picture of a business they have no business
having. A single nullable FK was the first design and is wrong: a manager may cover Ikeja and
Surulere but not Aba, which is neither "one" nor "all". The owner picks stores the way you would
pick tags.
The boolean is not redundant with an empty set. "Every store" and "these three stores that happen
to be all of them today" behave differently the moment a fourth store opens: an owner must see it
without anyone editing their membership, and a regional manager must not. Encoding "all" as an
empty set would make new stores silently visible to everyone, which is the opposite of the
requirement.
Deriving scope from `role` at query time was rejected for the reason Q19 gives: changing what
"manager" implies later would silently rescope every existing manager.
**Breaks if changed:** Collapsing the two fields into one makes opening a new branch either invisible
to its owner or instantly visible to every member scoped to "all the stores that existed then".

### Q26. Why are roles per-business templates instead of three fixed values?
**Where:** `accounts/models.py:RoleTemplate`, seeded by `provision_business()`
**Decision:** `Role` is no longer an enum. Each business owns a set of named `RoleTemplate` rows,
seeded with Owner, Manager and Sales, which it may rename, edit and extend — "Cashier",
"Storekeeper", whatever its org chart is. Choosing one at invite time **copies** its permissions
onto the membership; the template is never consulted afterwards.
**Reasoning:** Three hard-coded roles imposed one org chart on every business on the platform. A
market trader with two nephews on the counter and a distributor with a warehouse manager, cashiers
and drivers do not share a structure, and a product that makes them pick the nearest of three words
is wrong for most of them. Making templates per-business also keeps the Q19 property intact and
scopes it properly: editing the "Cashier" template next month changes what *new* cashiers start
with, never what existing ones can do.
`is_owner` became a stored boolean at the same time, because "owner" can no longer be recognised
from the role name once the name is the business's to choose.
Two guards exist because this is the one area where a business can lock itself out: the Owner
template must keep `manage_members`, and system templates cannot be deleted.
**Breaks if changed:** Reverting to a global enum forces every business onto one vocabulary.
Consulting the template at access time instead of copying makes every template edit a retroactive
grant across everyone who ever held it — Q19's failure, re-introduced one level up.

### Q25. Why does an invitation hold the intended access rather than creating the membership up front?
**Where:** `accounts/models.py:Invitation` *(being built)*
**Decision:** An invitation stores the business, the role, the permission set, the store scope and a
hashed single-use token. The `Membership` is created only when the person accepts and sets a
password. The staff list a business owner sees merges active memberships with pending invitations.
**Reasoning:** A membership points at a `User`, and the invited person has no account until they
accept, so a membership created up front would need a null user — which breaks the one-membership-
per-user constraint and puts a half-real row in the table every permission check has to skip.
Keeping the intended access on the invitation means the owner still configures everything at invite
time, as they asked; the record just lives somewhere honest until there is a person to attach it to.
The token is stored hashed, matching the `PasswordReset.code_hash` pattern the PRD already uses: an
invitation link grants access to a business's data, so a database leak should not be a set of
working keys. Resending therefore issues a new token rather than re-sending the old one.
**Breaks if changed:** A nullable `Membership.user` makes every access check carry a "and the user
exists" clause, and the unique constraint stops protecting against duplicate memberships.

### Q24. Why is discounting a per-business policy instead of one rule?
**Where:** `accounts/models.py:BusinessProfile.discount_policy` *(being built)*, enforced in
`quotes/serializers.py`
**Decision:** Four modes — `free` (default), `logged`, `capped` (with `max_discount_percent`),
`none` — chosen by the business owner. The policy binds only members without `CATALOGUE_EDIT`.
**Reasoning:** `unit_price` is per-line and client-supplied, so hiding cost stops a salesperson
knowing the floor but not selling beneath it. That is the actual fraud route, and the right control
for it differs by business: a trader with two family members on the counter wants nothing in the
way, a distributor with salaried staff wants a hard cap. Picking one would make the product wrong
for the other half of the market. `free` is the default because it is the current behaviour, so the
migration changes nothing for anyone already trading — a stricter default would start rejecting
quotes that worked yesterday. Owners and managers are exempt because they can edit the catalogue
price itself; enforcing a discount cap on someone who can raise the list price is theatre.
**Breaks if changed:** Making the policy global forces every business onto one risk appetite.
Defaulting to anything but `free` silently rejects legitimate quotes on the day of the upgrade,
with no one having asked for the change.

## Part 4 — Configuration and safety

### Q13. Why does `settings.py` refuse to start without a secret key?
**Where:** `config/settings.py:29-34`
**Decision:** Fail closed. No `DJANGO_SECRET_KEY` and no `DJANGO_DEBUG=true` means the process will
not boot.
**Reasoning:** The common failure mode is deploying to production with a development fallback key
still in place, which makes every session cookie forgeable. A refusal to start is loud; a weak
default is silent.
**Breaks if changed:** A default key in production means session forgery, and nothing in the logs
to indicate it.

### Q14. Why `TESTING = "test" in sys.argv`?
**Where:** `config/settings.py:127`
**Decision:** Detect the test runner and skip the HTTPS redirect.
**Reasoning:** The Django test client speaks plain HTTP. With `SECURE_SSL_REDIRECT` on, every test
request would be answered with a 301 and no test would reach a view.
**Breaks if changed:** The entire suite fails with 301s, which is a confusing symptom for a
configuration cause. This is a pragmatic hack; it is written down so the next reader does not
"fix" it.

### Q15. Why does changing bank details require the current password?
**Where:** `accounts/serializers.py` (`BANK_FIELDS`, `validate`)
**Decision:** The one profile edit that re-prompts for the password, and writes to `AuditLog`.
**Reasoning:** These fields decide where customers send money. An attacker with a hijacked session,
or a disgruntled employee, redirects payment by editing one field. The password check plus the audit
entry make it neither silent nor deniable.
**Breaks if changed:** Silent payment redirection with no trail.

### Q16. Why does `BusinessProfileSerializer` return logo paths instead of absolute URLs?
**Where:** `accounts/serializers.py`
**Decision:** Return relative paths; let the browser resolve them.
**Reasoning:** An absolute URL built by Django in development is `127.0.0.1`, which is the phone
itself when the page is opened on a phone. The image silently fails to load.
**Breaks if changed:** Logos break on every device that is not the machine running the server.

### Q17. Why throttle logins per username as well as per IP, and why not lock accounts?
**Where:** `accounts/throttling.py:LoginUsernameThrottle`, `accounts/views.py:LoginView`,
`config/settings.py` (`login_username`, 5/min)
**Decision:** Two throttles on the sign-in endpoint. `ScopedRateThrottle` keys on the
address, `LoginUsernameThrottle` keys on the lowercased username being attempted.
**Reasoning:** The two limits stop opposite attacks. Per-IP caps one address guessing
quickly; it does nothing about credential stuffing spread thin across many addresses
against one account, which is the shape an attacker with a botnet actually uses.
Keying on the username closes that.

A lockout was considered and rejected. Disabling an account after N failures hands an
attacker a denial-of-service primitive: anyone who knows a username can keep its owner
out indefinitely. A throttle costs the attacker far more than the real user and cannot
be turned against them.

The key is lowercased because registration matches usernames case-insensitively —
otherwise `ADA` would be a second free bucket for the same account.
**Breaks if changed:** Dropping the per-username limit reopens distributed guessing.
Note also that throttle counters live in Django's cache, so a multi-worker deployment
without `REDIS_URL` multiplies every limit by the worker count.

### Q18. Why cap logo pixel dimensions when there is already a 2 MB byte limit?
**Where:** `accounts/serializers.py` (`MAX_LOGO_DIMENSION`, `image_upload_serializer`)
**Decision:** Reject uploads longer than 3000 pixels on either side, in addition to the
byte cap.
**Reasoning:** File size tells you nothing about decoded size. A single-colour PNG at
30000x30000 compresses to a few hundred kilobytes and passes a 2 MB check comfortably,
then becomes gigabytes of pixels in memory. WeasyPrint decodes the logo in full on every
uncached PDF render, and PDF rendering is already the memory ceiling that sizes the
server — so the pixel count, not the byte count, is the figure that matters.

`Image.open()` reads the header without decoding pixels, so probing the dimensions of a
decompression bomb is itself cheap. The file is rewound afterwards so the upload still
saves normally.
**Breaks if changed:** Removing the cap lets one upload exhaust memory on the next PDF
render, taking the whole instance down for every tenant on it.

---

## Open decisions

Decisions identified but not yet implemented. Move each into the numbered sections above as it
lands, and delete it from here.

| # | Question | Status |
|---|---|---|
| D1 | Tenant membership: how do multiple owners and employees attach to a business? | Designed, not built |
| D2 | Feature registry: one registry, two gates (module enabled × permission granted) | Designed, not built |
| D3 | Stores: is cost shared across branches or held per store? | Decision pending — per-store recommended |
| D4 | Product verticals: does a non-cable catalogue import existing models or define new ones? | Blocked on an answer |
| D5 | Suspension semantics: what exactly can a restricted business still do? | Reads yes, writes no, PDFs yes — proposed |
| D6 | Deployment: uploads move to S3-compatible object storage, so `BusinessProfileSerializer` must return absolute signed URLs there while keeping relative paths locally (amends Q16) | Designed, not built — see `DEPLOYMENT.md` §3–4 |
