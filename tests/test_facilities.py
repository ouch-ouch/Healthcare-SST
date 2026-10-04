from sot.facilities import normalize_facility


def test_normalize_facility_matches_code_and_name():
    assert normalize_facility("BYS") == "Harborview Bayside"
    assert normalize_facility("Harborview Bayside") == "Harborview Bayside"
    assert normalize_facility("Unit 7") is None
