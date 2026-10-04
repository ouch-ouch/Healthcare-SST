from sot.facilities import normalize_facility


def test_normalize_facility_matches_code_and_name():
    assert normalize_facility("BYS") == "Harborview Bayside"
    assert normalize_facility("Harborview Bayside") == "Harborview Bayside"
    assert normalize_facility("Unit 7") is None


def test_normalize_facility_substring_match():
    """M11: close-but-not-exact text should still resolve via case-insensitive substring match."""
    assert normalize_facility("bayside") == "Harborview Bayside"
    assert normalize_facility("RIVERDALE") == "Harborview Riverdale"
    assert normalize_facility("Harborview Bayside - Unit 3") == "Harborview Bayside"
