# Build log — platform work

A running record of what was built, in order, with the verification run at each
stage. Nothing here is committed: every stage below sits in the working tree so
it can be reviewed, tested and committed selectively.

**Branch:** `chore/tooling-baseline`
**Per-stage patches:** `docs/build/stage-NN-*.patch` — `git diff` captured at the
end of each stage, so a stage can be read on its own rather than as part of one
large working-tree diff.

## How to use this

```bash
git diff                                  # everything not yet committed
git diff --stat                           # which files each stage touched
git apply --check docs/build/stage-NN-*.patch   # verify a stage applies cleanly
```

To commit a stage, stage its files by hand from the file list below. The stages
are ordered by dependency: later ones assume earlier ones are present.

## Verification standard

Every stage runs, at minimum:

| Check | Command |
|---|---|
| Backend tests (108) | `DATABASE_URL="sqlite:///$PWD/t.sqlite3" DJANGO_DEBUG=true ./venv/bin/python manage.py test` |
| Deployment checklist | `manage.py check --deploy` |
| Backend lint | `./venv/bin/ruff check .` |
| Backend format | `./venv/bin/ruff format --check .` |
| Frontend lint | `npm run lint` |
| Frontend format | `npm run format:check` |
| Frontend build | `npm run build` |
| Dependency CVEs | `pip-audit`, `npm audit --omit=dev` |

Postgres is not reachable from this environment, so backend tests run against
SQLite via `DATABASE_URL`. CI runs the same suite against Postgres 16.

---

## Stage 00 — tooling configuration *(committed before the no-commit instruction)*

**Commit:** `fab6de9`
Ruff for backend lint and format; eslint flat config with react-hooks plus
prettier for the frontend. No code reformatted. Bandit (S) ruleset enabled and
reporting no findings.

Also committed: `0dcc34f`, the system design handbook and the PRD platform scope.

Both sit on this branch and can be soft-reset into the working tree if you would
rather review them alongside everything else.

---

## Stage 01 — mechanical reformat

**Patch:** `docs/build/stage-01-format.patch`
**Files:** 49 changed (+1946 / −639)

Ran `ruff format` across the backend and `prettier --write` across the frontend.
No logic changed. The only notable diffs are clarifying parentheses that prettier
adds around `??` when mixed with a ternary, which is semantically identical.

**Judgement call — `frontend/src/index.css` is exempted** in `.prettierignore`.
Prettier expands it from 573 to 2167 lines because the file is deliberately
written one rule per line as a token and component sheet. That is a 4x blowup
which makes every future CSS diff noisier for no correctness gain. Remove the
last line of `.prettierignore` to reverse this.

| Check | Result |
|---|---|
| Backend tests | 108 passed |
| Backend format check | clean |
| Frontend prettier check | clean, 59 files |
| Frontend build | succeeded, 356.80 kB / 108.67 kB gzip |

Backend lint is **not** clean yet — 8 real findings remain, fixed in stage 03.

---

## Stage 02 — resolve every lint finding

**Patch:** `docs/build/stage-02-lint-fixes.patch` *(cumulative: includes stage 01)*

Backend and frontend both reach zero findings. Nothing was suppressed to get
there except the two documented rule exclusions from stage 00.

### Backend — 8 findings

| File | Rule | Change |
|---|---|---|
| `accounts/serializers.py:10` | F401 | Dropped the unused `naira` import |
| `accounts/serializers.py:54` | B904 | `raise ... from error`, so a password-validation failure keeps its cause |
| `catalogue/urls.py:12` | RUF005 | `[path(...), *router.urls]` instead of list concatenation |
| `purchasing/costing.py:55` | B905 | `zip(..., strict=True)` |
| `purchasing/costing.py:82` | B905 | `zip(..., strict=True)` |
| `purchasing/serializers.py:142` | B905 | `zip(..., strict=True)` |
| `waybills/models.py` | DJ008 | `WaybillItemColour.__str__` added |
| `accounts/.../seed_data.py:82`, `purchasing/serializers.py:60` | E501 | Two strings split across lines |

**The three `strict=True` changes are the ones worth reviewing.** They sit on the
cost path. All three pairs are equal-length by construction today — `weights` is
built from `lines`, and `landed_unit_costs` returns exactly one value per input
line — so behaviour is unchanged. What they add is a guard: if anyone later makes
`landed_unit_costs` filter or short-circuit, the mismatch raises instead of
silently pairing the wrong cost to the wrong item. That is the failure mode worth
being loud about, given cost is the number every margin depends on.

Import sorting was applied by `ruff check --fix` across four files, and a
`__str__`/`Meta` ordering fix (DJ012) followed the Django style guide.

### Frontend — 3 findings

Two were `react-hooks/set-state-in-effect` in `InlinePrice.jsx` and
`Accessories.jsx`, both the same pattern: an effect resyncing local edit state
when a prop changed. Replaced with React's documented approach — adjust during
render against a remembered previous value. Same visible behaviour, one render
pass instead of two.

The third was `react-refresh/only-export-components` on `AuthContext.jsx`
exporting `useAuth` beside the provider. Left in place with a disable comment and
a reason: splitting the hook into its own module would satisfy fast refresh but
scatter one small concern across two files. The lint script now runs with
`--max-warnings 0`, so this is the only warning in the tree and any new one fails.

### Verification

| Check | Result |
|---|---|
| Backend tests | **108 passed** |
| Backend lint | All checks passed |
| Backend format | clean, 59 files |
| Frontend lint | clean, zero warnings |
| Frontend format | clean |
| Frontend build | succeeded |
| `pip-audit` | No known vulnerabilities |
| `npm audit --omit=dev` | 0 vulnerabilities |
| **End-to-end smoke** | **passed** — line amount, editor total, server total and PDF filename all correct |

The e2e run matters most here: it is the only check that exercises the two React
render-adjust changes against a real browser, and it confirms the quote editor
still computes ₦1,064,250.00 in the browser and on the server.

**Note on `manage.py check --deploy`:** it cannot be run meaningfully on this
machine because `backend/.env` sets `DJANGO_DEBUG=true`, which trips six warnings
that are artefacts of local configuration rather than findings. CI runs it with a
production-shaped environment.

---

## Stage 03 — CI gates, hooks and the working agreement

**Patch:** `docs/build/stage-03-ci-and-hooks.patch` *(tracked files only — see the
new-file list below, which `git diff` cannot capture)*

### New files

| File | Purpose |
|---|---|
| `CONTRIBUTING.md` | Setup, the five standing rules, branch and commit conventions, how to run the checks |
| `.pre-commit-config.yaml` | 11 hooks: hygiene, ruff lint + format, prettier, eslint |
| `.git-blame-ignore-revs` | Placeholder — needs the format commit's SHA once stage 01 is committed |
| `.github/pull_request_template.md` | Checklist, including the handbook requirement |
| `backend/.coveragerc` | Coverage config with the measured floor |

### CI now gates on

Added to `.github/workflows/ci.yml`, in front of the existing steps:

- `ruff check .` and `ruff format --check .` on the backend
- `npm run lint` and `npm run format:check` on the frontend
- Tests run under `coverage`, which reports and enforces the floor

The backend job now installs `requirements-dev.txt`, so `pip-audit` no longer
needs installing inline.

### Coverage baseline

**97% over 1625 statements, 43 missed**, with 33 files at complete coverage. The
floor is set to `fail_under = 95` — two points of headroom so ordinary churn does
not trip it, while any real drop fails the build. The thinnest areas are
`purchasing/costing.py` at 92% and `purchasing/serializers.py` at 93%, which is
worth knowing given that is the cost path.

### The lint script gates on warnings

`npm run lint` is `eslint . --max-warnings 0`. Without it the one justified
warning would sit there permanently and every new warning would hide behind it.

### Verification

| Check | Result |
|---|---|
| `pre-commit run --all-files` | **11 hooks, all passed** |
| Backend lint / format | All checks passed / 59 files clean |
| Frontend lint / format | clean, zero warnings / clean |
| Frontend build | succeeded in 1.67s |
| Backend tests under coverage | 108 passed, 97% |
| YAML validity | `ci.yml` and `.pre-commit-config.yaml` both parse |

Two hook bugs were found and fixed by running them rather than assuming: the
prettier hook originally did `cd frontend` and then received repo-root-relative
paths, so it matched nothing; and `- id: ruff` is a legacy alias for
`ruff-check`. Both would have shipped broken if the config had only been written
and not executed.

---

## Stage 04 — security findings A1 and A3

**Patch:** `docs/build/stage-04-security-fixes.patch`
**Handbook:** `docs/SYSTEM_DESIGN.md` Q17 and Q18 added.

### A1 — login was throttled per IP only

New `accounts/throttling.py:LoginUsernameThrottle` keys on the lowercased username
being attempted, at 5/min, running alongside the existing per-IP limit of 10/min.
The two stop opposite attacks: per-IP caps one address guessing fast, per-username
caps one account being guessed at from many addresses.

**A lockout was considered and rejected**, and the reasoning is recorded in Q18.
Disabling an account after N failures hands an attacker a denial-of-service
primitive — anyone knowing a username could keep its owner out. A throttle costs
the attacker far more than the real user and cannot be turned against them.

The key is lowercased because registration already matches usernames
case-insensitively; without that, `ADA` would be a second free bucket for `ada`.

### A3 — logo uploads capped bytes but not pixels

`MAX_LOGO_DIMENSION = 3000` per side, checked with `Image.open()`, which reads the
header without decoding pixels — so probing a decompression bomb is itself cheap.
The file is rewound afterwards so a valid upload still saves.

The reason this matters here specifically: WeasyPrint decodes the logo in full on
every uncached PDF render, and PDF rendering is already the memory ceiling that
sizes the server.

### Tests added — 7

| Test | What it pins down |
|---|---|
| `test_one_account_cannot_be_guessed_from_many_addresses` | Six attempts from six addresses; the sixth is 429 |
| `test_the_real_password_is_blocked_too` | Past the limit, a correct password is not an oracle |
| `test_throttling_one_account_does_not_block_another` | One account's limit does not spill onto another |
| `test_the_username_key_is_case_insensitive` | `ADA` shares `ada`'s bucket |
| `test_a_request_without_a_username_is_not_thrown_away` | No username to key on degrades to the IP limit, no error |
| `test_logo_with_too_many_pixels_is_refused` | 3200x10 rejected with a message naming pixels |
| `test_logo_at_the_pixel_limit_is_accepted` | Exactly 3000 still works |

**Both tests are self-proving rather than trusting the implementation.** The
throttle tests use a distinct `REMOTE_ADDR` per request, so the per-IP limit
cannot be what fires within six attempts. The pixel test asserts its own fixture
is under `MAX_LOGO_BYTES` before uploading, so the byte check cannot be what
rejects it.

### Verification

| Check | Result |
|---|---|
| Backend tests | **115 passed** (108 before, +7) |
| Coverage | **97%**, 1645 statements, 45 missed — above the 95 floor |
| Backend lint / format | All checks passed / clean |
| Frontend lint / format / build | clean / clean / built in 1.69s |
| **End-to-end smoke** | **passed** — sign-in still works with the new throttle in front of it |

---

## What is not done yet

1. **`.git-blame-ignore-revs`** — needs the format commit's SHA, which does not
   exist while stage 01 is uncommitted.
2. **Finding A5** — no Content-Security-Policy header. Small, not yet done.
3. **Finding A2** — password reset. Deliberately deferred: it depends on the
   membership model and belongs inside the spine, not before it.
4. **The spine** — `Membership`, then `Store`, then the feature gates.
5. **Frontend unit tests** — still only the e2e smoke script.
