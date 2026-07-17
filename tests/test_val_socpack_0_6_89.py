"""validate_selection + finish_selection_social_pack (0.6.89)."""

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
            "-f", "lavfi", "-i", f"color=c=teal:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=600:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_validate_and_social_pack_finish():
    root = Path(tempfile.mkdtemp(prefix="opmiere_vs_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.4)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=10)

        val = ed.validate_selection([c.id], set_work_area=False)
        assert val.get("ok") is True
        assert int(val.get("hard_count") or 0) == 0
        assert "preflight" in val
        assert "health" in val

        # square is lightest social canvas
        fin = ed.finish_selection_social_pack(
            [c.id],
            variants=["square"],
            reframe=False,
            prepare=False,
            normalize_preset=None,
            name_prefix="t",
        )
        assert fin.get("ok") is True
        pack = fin.get("pack") or {}
        assert int(pack.get("count") or 0) >= 1
        out = Path(pack.get("out_dir") or fin.get("out_dir") or "")
        assert out.is_dir()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_89():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/validate_selection" in app
    assert "/api/edit/finish_selection_social_pack" in app
    assert "def validate_selection" in mcp
    assert "def finish_selection_social_pack" in mcp
    assert 'id="btn-val-sel"' in html
    assert 'id="btn-soc-pack-fin"' in html
    assert "validateSelectionUi" in ts
    assert "finishSelectionSocialPackUi" in ts
