"""import_edit_manifest round-trip + ensure_all_media_proxies + quick assembly."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

from opmiere import Editor


def _vid(path: Path, d: float = 0.6, color: str = "navy") -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c={color}:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_manifest_export_import_roundtrip():
    root = Path(tempfile.mkdtemp(prefix="opmiere_mrt_"))
    try:
        a = root / "a.mp4"
        b = root / "b.mp4"
        _vid(a, 0.6, "navy")
        _vid(b, 0.6, "maroon")
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(a, "video", tr.id, 0)
        c2 = ed.place_from_file(b, "video", tr.id, c1.end)
        ed.apply_effect(c1.id, {"type": "blur", "amount": 2.0})
        ed.add_marker(frame=5, label="hit")
        body = ed.export_edit_manifest()["body"]

        ed2 = Editor.create(root / "p2.opm", fps=30, width=320, height=180)
        r = ed2.import_edit_manifest(text=body, import_missing_media=True)
        assert r["count"] == 2
        assert r["markers_imported"] == 1
        assert len(ed2.project.tracks[0].clips) == 2
        assert any(
            e.get("type") == "blur"
            for e in ed2.project.tracks[0].clips_in_order()[0].effects
        )
        assert any(m.label == "hit" for m in ed2.project.markers)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ensure_all_media_proxies_mocked():
    root = Path(tempfile.mkdtemp(prefix="opmiere_px_"))
    try:
        v = root / "v.mp4"
        _vid(v)
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        ed.import_media(v, "video")
        with mock.patch.object(
            ed,
            "ensure_media_proxy",
            return_value={"media_id": "x", "cache_hit": False, "path": "p"},
        ) as m:
            r = ed.ensure_all_media_proxies(height=360)
        assert r["count"] == 1
        assert m.called
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_agent_quick_assembly():
    root = Path(tempfile.mkdtemp(prefix="opmiere_qa_"))
    try:
        a = root / "a.mp4"
        b = root / "b.mp4"
        _vid(a, 0.5, "teal")
        _vid(b, 0.5, "orange")
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        r = ed.agent_quick_assembly(
            [a, b], rough_cut=True, title="End card", transition="cross_dissolve",
        )
        assert len(r["imported"]) == 2
        assert r["rough_cut"]["sequence"]["count"] == 2
        assert r.get("title", {}).get("clip_id")
        assert len(ed.project.tracks[0].clips) >= 3  # 2 + title
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_5_63():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/import/manifest" in app
    assert "/api/media/proxies_all" in app
    assert "/api/edit/quick_assembly" in app
    assert "def import_edit_manifest" in mcp
    assert "def agent_quick_assembly" in mcp
    assert 'id="btn-imp-manifest"' in html
    assert "importManifestUi" in ts
