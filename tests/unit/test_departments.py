from email_classifier.departments import FALLBACK_DEPARTMENT, Department

# The exact list of target addresses from the assignment brief.
BRIEF_ADDRESSES = {
    "human-resources@example.com",
    "help-desk@example.com",
    "it@example.com",
    "kadry@example.com",
    "other@example.com",
}


def test_addresses_match_the_brief_exactly() -> None:
    assert {department.address for department in Department} == BRIEF_ADDRESSES


def test_every_department_has_its_own_address() -> None:
    addresses = [department.address for department in Department]

    assert len(addresses) == len(set(addresses))


def test_fallback_is_other() -> None:
    assert FALLBACK_DEPARTMENT is Department.OTHER
    assert FALLBACK_DEPARTMENT.address == "other@example.com"


def test_department_is_a_plain_string_in_json() -> None:
    assert str(Department.HELP_DESK) == "help_desk"
    assert Department("kadry") is Department.PERSONNEL
