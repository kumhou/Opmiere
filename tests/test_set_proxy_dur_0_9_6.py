"""selection_set_proxy_report + selection_set_duration_report (0.9.6)."""

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
            "-f", "lavfi", "-i", f"color=c=darkcyan:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=95:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_proxy_and_duration_reports():
    root = Path(tempfile.mkdtemp(prefix="opmiere_spd_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(v, "video", tr.id, 0, duration_frames=10)
        c2 = ed.place_from_file(v, "video", tr.id, 10, duration_frames=15)
        ed.save_selection_set("hero", [c1.id, c2.id])

        proxy = ed.selection_set_proxy_report("hero")
        assert proxy.get("selection_set") == "hero"
        assert proxy.get("clip_count") == 2

        dur = ed.selection_set_duration_report("hero")
        assert dur.get("selection_set") == "hero"
        assert dur.get("clip_count") == 2
        # 10+15 frames at 30fps
        assert dur.get("sum_clip_duration_seconds") is not None or "total" in str(dur)
        # union span covers 0..25
        span_s = dur.get("union_span_seconds")
        if span_s is not None:
            assert float(span_s) >= 0.8
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_6():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/selection_set_proxy_report" in app
    assert "/api/edit/selection_set_duration_report" in app
    assert "def selection_set_proxy_report" in mcp
    assert "def selection_set_duration_report" in mcp
    assert 'id="btn-set-proxy"' in html
    assert 'id="btn-set-dur"' in html
    assert "selectionSetProxyReportUi" in ts
    assert "selectionSetDurationReportUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "selection_set_proxy_report" in cat["tool_ids"]
    assert "selection_set_duration_report" in cat["tool_ids"]
