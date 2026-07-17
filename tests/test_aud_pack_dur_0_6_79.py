"""export_selection_clips_audio_pack + selection_duration_report (0.6.79)."""

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
            "-f", "lavfi", "-i", f"color=c=orange:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=500:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_audio_pack_and_duration_report():
    root = Path(tempfile.mkdtemp(prefix="opmiere_ad_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.4)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(v, "video", tr.id, 0, duration_frames=10)
        c2 = ed.place_from_file(v, "video", tr.id, 10, duration_frames=10)

        rep = ed.selection_duration_report([c1.id, c2.id])
        assert int(rep.get("clip_count") or 0) == 2
        assert int(rep.get("sum_clip_duration_frames") or 0) == 20
        assert int(rep.get("union_span_frames") or 0) == 20
        assert rep.get("overlap_or_gaps") is False

        pack = ed.export_selection_clips_audio_pack(
            [c1.id], ext="wav", prefix="a",
        )
        assert int(pack.get("count") or 0) >= 1
        assert pack.get("ok") is True
        assert list(Path(pack["output_dir"]).glob("*.wav"))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_79():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/export_selection_clips_audio_pack" in app
    assert "/api/edit/selection_duration_report" in app
    assert "def export_selection_clips_audio_pack" in mcp
    assert "def selection_duration_report" in mcp
    assert 'id="btn-aud-pack-sel"' in html
    assert 'id="btn-dur-sel"' in html
    assert "exportSelectionClipsAudioPackUi" in ts
    assert "selectionDurationReportUi" in ts
