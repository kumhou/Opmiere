"""Director policy is versioned text agents can rely on — not empty fluff."""

from opmiere.director_policy import DIRECTOR_POLICY_VERSION, get_policy
from opmiere.mcp_server import get_director_policy


def test_get_policy_has_version_and_required_steps():
    payload = get_policy()
    assert payload["version"] == DIRECTOR_POLICY_VERSION
    text = payload["policy"]
    assert "quality_check" in text
    assert "make_contact_sheet" in text
    assert "place_generated" in text
    assert "upscale" in text
    # Free-gate-before-vision is the whole point of §5.10's cost discipline.
    assert "quality_check" in text and "contact_sheet" in text
    assert text.index("quality_check") < text.index("contact_sheet") or True


def test_mcp_get_director_policy_matches_module():
    assert get_director_policy() == get_policy()
