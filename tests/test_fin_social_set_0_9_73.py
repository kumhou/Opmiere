"""finish_selection_set_social + finish_selection_set_social_pack (0.9.73)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path, d: float = 0.5) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=dimgray:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=440:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_finish_social_and_pack_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_finsoc_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        ed.save_selection_set("hero", [c.id])

        # light path: skip reframe/prepare/review for speed
        soc = ed.finish_selection_set_social(
            "hero",
            variant="reels",
            reframe=False,
            prepare=False,
            run_review=False,
            filename="hero_reels_finish.mp4",
        )
        assert soc.get("selection_set") == "hero"
        assert soc.get("variant") == "reels"

        pack = ed.finish_selection_set_social_pack(
            "hero",
            variants=["reels"],
            reframe=False,
            prepare=False,
            name_prefix="hero",
        )
        assert pack.get("selection_set") == "hero"
        assert "pack" in pack or pack.get("ok") is not None
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_73():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/finish_selection_set_social" in app
    assert "/api/edit/finish_selection_set_social_pack" in app
    assert "def finish_selection_set_social" in mcp
    assert "def finish_selection_set_social_pack" in mcp
    assert 'id="btn-fin-social-set"' in html
    assert 'id="btn-fin-social-pack-set"' in html
    assert "finishSelectionSetSocialUi" in ts
    assert "finishSelectionSetSocialPackUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "finish_selection_set_social" in cat["tool_ids"]
    assert "finish_selection_set_social_pack" in cat["tool_ids"]
