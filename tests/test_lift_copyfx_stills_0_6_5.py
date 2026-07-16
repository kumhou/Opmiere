"""lift_clip + copy_effects + export_clips_stills_pack (0.6.5)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path, d: float = 0.4) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=navy:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_lift_copy_effects_stills():
    root = Path(tempfile.mkdtemp(prefix="opmiere_lcs_"))
    try:
        v = root / "v.mp4"
        _vid(v)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(v, "video", tr.id, 0)
        c2 = ed.place_from_file(v, "video", tr.id, int(c1.end))
        c3 = ed.place_from_file(v, "video", tr.id, int(c2.end))

        ed.apply_vignette(c1.id, strength=0.4)
        ed.apply_film_grain(c1.id, amount=10)
        cp = ed.copy_effects(c1.id, [c2.id, c3.id], replace=True)
        assert cp["count"] == 2
        for cid in (c2.id, c3.id):
            types = {e.get("type") for e in (ed._find_clip(cid).effects or [])}
            assert "vignette" in types
            assert "film_grain" in types

        pack = ed.export_clips_stills_pack(
            [c1.id, c2.id], root / "stills", at="mid", width=80,
        )
        assert pack["count"] == 2
        assert pack["ok"]

        gap_start = c2.start
        lifted = ed.lift_clip(c2.id)
        assert lifted["deleted_id"] == c2.id
        assert lifted["ripple"] is False
        # c3 should still be at same start (no ripple)
        assert ed._find_clip(c3.id).start == c3.start
        # gap where c2 was
        assert lifted["start"] == gap_start

        # ripple multi-delete c1 then remaining - use c3 only after lift
        before = ed._find_clip(c3.id).start
        rip = ed.ripple_delete_selection([c1.id])
        assert rip["count"] == 1
        # after deleting c1 with ripple, c3 should move left
        assert ed._find_clip(c3.id).start < before
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_5():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/lift_clip" in app
    assert "/api/edit/ripple_delete_selection" in app
    assert "/api/clip/copy_effects" in app
    assert "/api/export/clips_stills_pack" in app
    assert "def lift_clip" in mcp
    assert "def ripple_delete_selection" in mcp
    assert "def copy_effects" in mcp
    assert "def export_clips_stills_pack" in mcp
    assert 'id="btn-lift-clip"' in html
    assert 'id="btn-rip-sel"' in html
    assert 'id="btn-copy-fx"' in html
    assert 'id="btn-stills-pack"' in html
    assert "liftClipUi" in ts
    assert "rippleDeleteSelectionUi" in ts
    assert "copyEffectsUi" in ts
    assert "exportClipsStillsPackUi" in ts
