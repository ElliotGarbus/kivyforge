from kivyforge.lock.resolver import unresolved_requirement


def test_names_requirement_from_pip_output():
    out = (
        "ERROR: Could not find a version that satisfies the requirement kivy "
        "(from versions: none)\nERROR: No matching distribution found for kivy"
    )
    assert unresolved_requirement(out) == "kivy"


def test_matches_no_matching_distribution_alone():
    assert unresolved_requirement("ERROR: No matching distribution found for x==1") == (
        "x==1"
    )


def test_returns_none_when_pip_names_nothing():
    assert unresolved_requirement("something else went wrong") is None
    assert unresolved_requirement("") is None
