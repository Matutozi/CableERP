## What this changes

<!-- One or two sentences. What behaviour is different afterwards? -->

## Why

<!-- The problem, not the solution. Link the issue if there is one. -->

## Handbook

<!-- Required. Which docs/SYSTEM_DESIGN.md entry did you add or correct? -->

- [ ] `docs/SYSTEM_DESIGN.md` updated, or: not a design decision because …

## Checks

- [ ] Derived vs frozen decided for any new field
- [ ] Unknown values are `null`, not `0`
- [ ] New endpoints scope through `get_business()` and have a cross-tenant 404 test
- [ ] Cost fields, if touched, are written only by `purchasing/costing.py`
- [ ] Mechanical changes are in their own commit

## Verification

<!-- What you ran, and what it said. -->
