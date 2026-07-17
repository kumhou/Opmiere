"""export_selection_set_clips_webm_pack + export_selection_set_clips_audio_pack (0.9.83)."""

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


def test_webm_and_audio_pack_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_wmau_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        ed.save_selection_set("hero", [c.id])

        webm = ed.export_selection_set_clips_webm_pack("hero", crf=40)
        assert webm.get("selection_set") == "hero"
        wout = webm.get("output_dir")
        assert wout and Path(str(wout)).is_dir()
        w_ok = [
            x for x in (webm.get("clips") or [])
            if x.get("ok") and x.get("path") and Path(str(x["path"])).is_file()
        ]
        assert webm.get("count", 0) >= 1 or len(w_ok) >= 1 or list(
            Path(str(wout)).glob("*.webm")
        )

        audio = ed.export_selection_set_clips_audio_pack("hero", ext="wav")
        assert audio.get("selection_set") == "hero"
        aout = audio.get("output_dir")
        assert aout and Path(str(aout)).is_dir()
        a_ok = [
            x for x in (audio.get("clips") or [])
            if x.get("ok") and x.get("path") and Path(str(x["path"])).is_file()
        ]
        assert audio.get("count", 0) >= 1 or len(a_ok) >= 1 or list(
            Path(str(aout)).glob("*.wav")
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_83():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/export_selection_set_clips_webm_pack" in app
    assert "/api/edit/export_selection_set_clips_audio_pack" in app
    assert "def export_selection_set_clips_webm_pack" in mcp
    assert "def export_selection_set_clips_audio_pack" in mcp
    assert 'id="btn-exp-clips-webm-set"' in html
    assert 'id="btn-exp-clips-audio-set"' in html
    assert "exportSelectionSetClipsWebmPackUi" in ts
    assert "exportSelectionSetClipsAudioPackUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "export_selection_set_clips_webm_pack" in cat["tool_ids"]
    assert "export_selection_set_clips_audio_pack" in cat["tool_ids"]
