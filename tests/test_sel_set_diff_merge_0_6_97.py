"""diff_selection_sets + merge_selection_sets (0.6.97)."""

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
            "-f", "lavfi", "-i", f"color=c=olive:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=480:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_diff_and_merge_selection_sets():
    root = Path(tempfile.mkdtemp(prefix="opmiere_dm_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.4)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(v, "video", tr.id, 0, duration_frames=8)
        c2 = ed.place_from_file(v, "video", tr.id, 8, duration_frames=8)
        c3 = ed.place_from_file(v, "video", tr.id, 16, duration_frames=8)

        ed.save_selection_set("a", [c1.id, c2.id])
        ed.save_selection_set("b", [c2.id, c3.id])

        d = ed.diff_selection_sets("a", "b")
        assert d.get("ok") is True
        assert d.get("equal") is False
        assert set(d["only_a"]) == {c1.id}
        assert set(d["only_b"]) == {c3.id}
        assert set(d["both"]) == {c2.id}

        u = ed.merge_selection_sets(
            ["a", "b"], "all", mode="union", overwrite=True,
        )
        assert u.get("ok") is True
        assert set(u["clip_ids"]) == {c1.id, c2.id, c3.id}

        inter = ed.merge_selection_sets(
            ["a", "b"], "shared", mode="intersect", overwrite=True,
        )
        assert set(inter["clip_ids"]) == {c2.id}

        only = ed.merge_selection_sets(
            ["a", "b"], "a_only", mode="only_first", overwrite=True,
        )
        assert set(only["clip_ids"]) == {c1.id}

        listed = ed.list_selection_sets()
        names = {s["name"] for s in listed["sets"]}
        assert {"a", "b", "all", "shared", "a_only"} <= names
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_97():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/diff_selection_sets" in app
    assert "/api/edit/merge_selection_sets" in app
    assert "def diff_selection_sets" in mcp
    assert "def merge_selection_sets" in mcp
    assert 'id="btn-diff-sel-set"' in html
    assert 'id="btn-merge-sel-set"' in html
    assert "diffSelectionSetsUi" in ts
    assert "mergeSelectionSetsUi" in ts
