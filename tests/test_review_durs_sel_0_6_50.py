"""review_selection + selection_clip_durations (0.6.50)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor
from opmiere.render.openshot_map import ADAPTER_VERSION


def _vid(path: Path, d: float = 1.0) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=navy:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_review_and_durations():
    root = Path(tempfile.mkdtemp(prefix="opmiere_rd_"))
    try:
        v = root / "v.mp4"
        _vid(v, 1.0)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        med = ed.import_media(v, "video")
        c1 = ed.add_clip(tr.id, med.id, 0, 0, 20)
        c2 = ed.add_clip(tr.id, med.id, 30, 0, 5)  # gap + short-ish

        durs = ed.selection_clip_durations([c1.id, c2.id])
        assert durs["count"] == 2
        assert durs["sum_timeline_frames"] == 25
        assert durs["union_span"]["duration_frames"] == 35

        rev = ed.review_selection([c1.id, c2.id], min_clip_seconds=0.4)
        assert rev["ok"] is True  # no offline/overlap/locked
        codes = {i["code"] for i in rev["issues"]}
        assert "gap" in codes
        assert "short_clip" in codes  # c2 is 5f @ 30fps
        assert int(rev["path_c"]["adapter_version"]) >= int(ADAPTER_VERSION)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_50():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/review_selection" in app
    assert "/api/edit/selection_clip_durations" in app
    assert "def review_selection" in mcp
    assert "def selection_clip_durations" in mcp
    assert 'id="btn-review-sel"' in html
    assert 'id="btn-durs-sel"' in html
    assert "reviewSelectionUi" in ts
    assert "selectionClipDurationsUi" in ts
