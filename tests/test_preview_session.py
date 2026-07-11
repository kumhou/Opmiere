"""PreviewSession contract (path C stub)."""

from __future__ import annotations

from opmiere.render.preview_session import (
    PreviewState,
    UnavailablePreviewSession,
    get_preview_session,
    preview_engine_status,
)


def test_unavailable_session_capabilities():
    s = UnavailablePreviewSession()
    assert s.state is PreviewState.UNAVAILABLE
    assert s.backend_name == "none"
    caps = s.capabilities()
    assert caps["composite_frame"] is False
    assert caps["preferred"] == "libopenshot"
    assert caps["fallback"] == "mlt"


def test_get_preview_session_default():
    s = get_preview_session()
    # libopenshot when OpenShot installed; else unavailable stub
    assert s.backend_name in ("libopenshot", "none")
    r = s.seek(1.0)
    assert "ok" in r


def test_preview_engine_status_shape():
    st = preview_engine_status()
    assert st["active_backend"] in ("libopenshot", "none")
    assert "spike" in st
    assert st["capabilities"]["interim_scrub"] == "ffmpeg_proxy"


def test_editor_preview_engine_status(tmp_path):
    from opmiere import Editor

    ed = Editor.create(tmp_path / "p.opm", fps=30, width=320, height=180)
    st = ed.preview_engine_status()
    assert st["active_backend"] in ("libopenshot", "none")
