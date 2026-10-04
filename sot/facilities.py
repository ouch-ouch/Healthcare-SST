"""Facility name/code normalization shared by Combined-B and Combined-C resolvers."""

_CODE_TO_NAME = {
    "BYS": "Harborview Bayside",
    "RVD": "Harborview Riverdale",
}

_CANONICAL_NAMES = {name.lower(): name for name in _CODE_TO_NAME.values()}


def normalize_facility(raw: str) -> str | None:
    """Map a facility code or raw name text to its canonical facility name.

    Returns None if raw is unrecognized.
    """
    if not raw:
        return None

    if raw in _CODE_TO_NAME:
        return _CODE_TO_NAME[raw]

    return _CANONICAL_NAMES.get(raw.strip().lower())
