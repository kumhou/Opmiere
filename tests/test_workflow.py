"""Film workflow brief/plan — real module entry points, not re-implemented logic."""

from pathlib import Path

from opmiere.mcp_server import (
    get_film_workflow,
    make_director_brief,
    plan_director_session,
    validate_director_brief,
)
from opmiere.workflow import (
    DEFAULT_AESTHETIC,
    WORKFLOW_VERSION,
    get_workflow,
    make_brief,
    plan_session,
    validate_brief,
)


def test_make_brief_empty_intent_applies_defaults():
    brief = make_brief(intent="  ", assets=[])
    assert brief["no_opinion"] is True
    assert brief["intent"] is None
    assert brief["defaults_applied"] == DEFAULT_AESTHETIC
    assert brief["workflow_version"] == WORKFLOW_VERSION


def test_make_brief_with_intent_skips_defaults():
    brief = make_brief(intent="赛博朋克夜景旁白", assets=[])
    assert brief["no_opinion"] is False
    assert brief["intent"] == "赛博朋克夜景旁白"
    assert brief["defaults_applied"] is None


def test_validate_brief_requires_asset_path_and_role(tmp_path: Path):
    existing = tmp_path / "clip.mp4"
    existing.write_bytes(b"x")
    brief = make_brief(
        intent="x",
        assets=[
            {"path": str(existing), "role": "a_roll"},
            {"path": "", "role": "music"},
            {"path": str(tmp_path / "missing.mp4"), "role": "not_a_role"},
        ],
    )
    v = validate_brief(brief)
    assert v["ok"] is False
    assert any("path is required" in e for e in v["errors"])
    assert any("role must be one of" in e for e in v["errors"])
    assert any("does not exist" in w for w in v["warnings"])


def test_validate_brief_no_assets_and_no_generate_is_error():
    brief = make_brief(intent="x", assets=[], constraints={"no_generate": True})
    v = validate_brief(brief)
    assert v["ok"] is False
    assert any("no_generate" in e for e in v["errors"])


def test_plan_session_prefers_ingest_before_generate(tmp_path: Path):
    asset = tmp_path / "a.mp4"
    asset.write_bytes(b"x")
    brief = make_brief(
        intent="旅行 vlog",
        assets=[{"path": str(asset), "role": "a_roll"}],
        deliverable={"bundle_path": "out.opm", "export_path": "out.mp4"},
    )
    plan = plan_session(brief)
    assert plan["brief_ok"] is True
    tools = [s["tool"] for s in plan["steps"]]
    assert tools.index("apply_edit_plan") < tools.index("generate")
    assert "plan_edit" in tools
    assert "create_project" in tools
    assert "export" in tools
    assert "delivery_check" in tools
    assert "review_cut" in tools
    # a_roll present → speech/music may still be gaps
    gen_step = next(s for s in plan["steps"] if s["id"] == "generate_gaps")
    assert "speech" in gen_step["kinds"] or "music" in gen_step["kinds"]


def test_plan_session_no_opinion_includes_defaults():
    brief = make_brief(intent=None, assets=[])
    plan = plan_session(brief)
    assert plan["no_opinion"] is True
    assert plan["defaults"] == DEFAULT_AESTHETIC
    step_ids = [s["id"] for s in plan["steps"]]
    assert "generate_gaps" in step_ids or "no_assets" in step_ids


def test_mcp_wrappers_match_module():
    assert get_film_workflow()["version"] == get_workflow()["version"]
    b = make_director_brief(intent="test", assets=[])
    assert b == make_brief(intent="test", assets=[])
    assert validate_director_brief(b) == validate_brief(b)
    assert plan_director_session(b)["steps"][0]["tool"] == plan_session(b)["steps"][0]["tool"]


def test_workflow_markdown_orders_assets_before_generate():
    text = get_workflow()["workflow"]
    assert "place_from_file" in text or "Ingest user assets" in text
    assert text.index("Ingest user assets") < text.index("Generate only gaps")
