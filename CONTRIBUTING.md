# Contributing to CableERP

## Before you start

Read `docs/CODEBASE_GUIDE.md` for what each file does, and `docs/SYSTEM_DESIGN.md`
for why it is that way. The second one is the shorter read and answers most
"why is this like this?" questions.

## Setup

```bash
# Backend
cd backend
python3 -m venv venv && ./venv/bin/pip install -r requirements-dev.txt
cp .env.example .env          # then set DJANGO_SECRET_KEY and DATABASE_URL
./venv/bin/python manage.py migrate
./venv/bin/python manage.py seed_data

# Frontend
cd frontend && npm install

# Hooks — do this once, it saves a CI round trip
pip install pre-commit && pre-commit install
git config blame.ignoreRevsFile .git-blame-ignore-revs
```

## The rules

**1. Every change updates `docs/SYSTEM_DESIGN.md`.** Write the entry *before* you
start — recording the reasoning is how you find out the decision is wrong while it
is still cheap — and correct it after the work lands so it describes what was
actually built. An entry is: the question a reader would ask, where the code is,
the decision, the reasoning including what you rejected, and what breaks if it is
reversed.

**2. Decide derived or frozen before you write the migration.** Operational data
is derived and must always reflect its source. Document data is frozen at write
time and must never change afterwards. Almost every design question in this
codebase is a consequence of that answer. See `docs/SYSTEM_DESIGN.md` Q5–Q7.

**3. Unknown is `null`, never `0`.** A missing cost is not a free item, and a
margin against an unknown cost is unknown, not zero. The UI must say so.

**4. Tenant scoping lives in `get_queryset`, never in a view body.** Every
queryset goes through `accounts/utils.py:get_business()`. A record belonging to
another business must return 404, not 403 — it is invisible, not forbidden. Any
new endpoint needs a test asserting that.

**5. Only `purchasing/costing.py` writes cost fields.** They are a cache of the
purchase ledger, rebuildable with `manage.py rebuild_costs`. Writing them from
anywhere else breaks that guarantee silently.

## Branches and commits

- Branch from `main`: `feat/…`, `fix/…`, `chore/…`, `docs/…`.
- Keep mechanical changes (formatting, renames) in their own commit, separate from
  logic. Add any pure-reformat commit's SHA to `.git-blame-ignore-revs`.
- A PR needs a green CI run. CI gates on lint, format, migrations, the test suite,
  the deployment checklist, dependency audits and an end-to-end run.

## Running the checks locally

```bash
cd backend
./venv/bin/ruff check . && ./venv/bin/ruff format --check .
DATABASE_URL="sqlite:///$PWD/t.sqlite3" DJANGO_DEBUG=true ./venv/bin/python manage.py test

cd ../frontend
npm run lint && npm run format:check && npm run build
```

For the end-to-end test you need the stack running and seeded; see
`docs/BUILD_LOG.md` for the exact sequence used in this environment.

## Tests

- A bug fix comes with a test that fails without it.
- A new endpoint comes with a cross-tenant test asserting 404.
- Anything touching cost or totals comes with a test using `Decimal`, never float.
