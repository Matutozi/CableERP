"""Document reference numbers: PREFIX-YYYYMMDD-NNN, numbered per business per day."""


def next_reference_number(queryset, prefix, date):
    """The next free number for `prefix` on `date` among `queryset` (already scoped to one business).

    Callers must hold a lock on the business row, or two documents saved at once can take the
    same number. Numbers continue past deleted documents rather than reusing the highest one.
    """
    stem = f"{prefix}-{date:%Y%m%d}-"
    existing = queryset.filter(reference_number__startswith=stem).values_list("reference_number", flat=True)
    last = max((int(ref.removeprefix(stem)) for ref in existing), default=0)
    return f"{stem}{last + 1:03d}"
