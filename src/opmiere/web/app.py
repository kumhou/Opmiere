"""Web GUI shell over Editor — dual surface with MCP (ARCHITECTURE §5.4).

Product is the NLE; this is a thin HTTP viewport: proportional timeline,
HTML5 proxy scrub, media bin, style/filler helpers. Not libopenshot realtime.

Run:  python -m opmiere.web.app  |  opmiere web  |  opmiere-web
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import __version__
from ..generation import ComfyUIProvider
from ..ops import Editor

app = FastAPI(title="Opmiere", version=__version__)
# Tauri / Vite product shell (ui-desktop) talks to this API from another origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:1420",
        "http://127.0.0.1:1420",
        "tauri://localhost",
        "http://tauri.localhost",
        "https://tauri.localhost",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
_editor: Editor | None = None
_STATIC = Path(__file__).resolve().parent / "static"
_last_sheet: str | None = None
_last_frame: str | None = None


def _ed() -> Editor:
    if _editor is None:
        raise HTTPException(400, "no project open — POST /api/project/create or /open")
    return _editor


def _provider() -> ComfyUIProvider:
    return ComfyUIProvider()


class CreateBody(BaseModel):
    bundle_path: str
    fps: float = 30.0
    width: int = 1920
    height: int = 1080


class OpenBody(BaseModel):
    bundle_path: str


class PlaceBody(BaseModel):
    path: str
    kind: str = "video"
    track_id: str | None = None
    start: int = 0
    build_proxy: bool = False


class ExportBody(BaseModel):
    output_path: str
    normalize_preset: str | None = "streaming"
    run_delivery_check: bool = True
    delivery_preset: str = "streaming"


class BriefBody(BaseModel):
    intent: str | None = None
    assets: list[dict[str, Any]] = Field(default_factory=list)
    constraints: dict[str, Any] = Field(default_factory=dict)
    deliverable: dict[str, Any] = Field(default_factory=dict)


class LookBody(BaseModel):
    look: str = "cinematic"


class StyleBody(BaseModel):
    styles: str = "cinematic"
    clip_ids: list[str] | None = None
    video_only: bool = True
    apply_motion: bool = True


class SheetBody(BaseModel):
    output_path: str | None = None
    max_tiles: int = 12
    cols: int | None = None


class PlanEditBody(BaseModel):
    paths: list[str] = Field(default_factory=list)
    b_roll_mode: str = "overlay"
    j_cut_seconds: float = 0.4
    apply: bool = True


class PreviewBody(BaseModel):
    output_path: str | None = None
    height: int = 360
    fps: float = 12.0
    force: bool = False


class FrameBody(BaseModel):
    time_seconds: float = 0.0
    width: int = 640
    prefer_proxy: bool = True
    engine: str = "auto"  # auto | proxy | openshot | base


class OpenShotFrameBody(BaseModel):
    time_seconds: float = 0.0
    height: int = 360
    use_timeline: bool = True


class MediaProxyBody(BaseModel):
    media_id: str
    height: int = 480
    force: bool = False


class SearchBody(BaseModel):
    query: str
    media_id: str | None = None
    max_hits: int = 20


class FillerBody(BaseModel):
    clip_id: str
    dry_run: bool = True
    extra_words: list[str] | None = None
    pad_seconds: float = 0.02


class RippleDeleteBody(BaseModel):
    clip_id: str


class ClipLayoutBody(BaseModel):
    clip_id: str
    start_frame: int | None = None
    src_in: int | None = None
    src_out: int | None = None
    refresh_preview: bool = True
    quick_preview: bool = True


class EdgeTrimBody(BaseModel):
    clip_id: str
    edge: str  # left | right
    delta_frames: int
    mode: str = "normal"
    refresh_preview: bool = True
    quick_preview: bool = True


class PreviewRefreshBody(BaseModel):
    quick: bool = True
    force: bool | None = None
    height: int | None = None
    fps: float | None = None


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    html = _STATIC / "index.html"
    if not html.exists():
        return HTMLResponse("<h1>Opmiere</h1><p>static/index.html missing</p>")
    return HTMLResponse(html.read_text(encoding="utf-8"))


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "phase": __version__,
        "product": "video_editor",
        "project_open": _editor is not None,
        "surfaces": ["mcp", "web_probe", "tauri_desktop"],
    }



@app.get("/api/doctor")
def doctor(check_comfy: bool = False) -> dict[str, Any]:
    from ..doctor import run_doctor
    return run_doctor(check_comfy=check_comfy)


@app.post("/api/desktop/demo_project")
def desktop_demo_project() -> dict[str, Any]:
    """Create a short lavfi demo bundle and open it (desktop shell bootstrap)."""
    global _editor
    import shutil
    import subprocess
    import tempfile

    root = Path(tempfile.gettempdir()) / "opmiere_desktop_demo"
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    src = root / "src"
    src.mkdir()
    fps, w, h = 30, 640, 360
    clips = [
        (src / "a.mp4", "0x1a3a5a"),
        (src / "b.mp4", "0x5a3a1a"),
    ]
    for path, color in clips:
        proc = subprocess.run(
            [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi",
                "-i", f"color=c={color}:size={w}x{h}:duration=0.8:rate={fps}",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                str(path),
            ],
            capture_output=True, text=True,
        )
        if proc.returncode != 0 or not path.exists():
            return {
                "ok": False,
                "error": f"ffmpeg demo failed: {(proc.stderr or '')[-400:]}",
            }
    bundle = root / "demo.opm"
    ed = Editor.create(bundle, fps=fps, width=w, height=h)
    tr = ed.add_track("video")
    tr2 = ed.add_track("video")  # second V track for cross-track drag tests
    c0 = ed.place_from_file(clips[0][0], "video", tr.id, 0)
    ed.place_from_file(clips[1][0], "video", tr.id, c0.end)
    _ = tr2  # empty destination lane
    try:
        ed.ensure_preview_proxy(height=180, fps=8)
    except Exception:
        pass
    ed.save()
    _editor = ed
    return {
        "ok": True,
        "path": str(bundle.resolve()),
        "duration_frames": ed.duration_frames(),
        "preview": ed.preview_proxy_status(),
        "engine": ed.preview_engine_status(),
        "tracks": [t.id for t in ed.project.tracks if t.kind == "video"],
    }


@app.post("/api/desktop/export")
def desktop_export(
    normalize_preset: str | None = None,
    delivery_preset: str = "streaming",
    run_review: bool = False,
) -> dict[str, Any]:
    """Export current project to a temp file (desktop shell export button).

    Default normalize_preset=None so video-only lavfi demos still export;
    pass normalize_preset=streaming when the cut has real audio.
    """
    import tempfile

    ed = _ed()
    out_dir = Path(tempfile.gettempdir()) / "opmiere_desktop_export"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "export.mp4"
    try:
        result = ed.finish_delivery(
            out,
            normalize_preset=normalize_preset,
            delivery_preset=delivery_preset,
            run_review=run_review,
            run_sequence_sheet=False,
            prepare=True,
        )
    except ValueError as e:
        # e.g. no audio stream for loudnorm — plain export fallback
        try:
            written = ed.export(out, normalize_preset=None)
            return {
                "ok": Path(written).exists(),
                "path": str(Path(written).resolve()),
                "warning": str(e)[:300],
                "delivery": None,
            }
        except Exception as e2:
            return {"ok": False, "error": f"{e}; fallback: {e2}", "path": None}
    return {
        "ok": bool(result.get("ok")),
        "path": str(out.resolve()) if out.exists() else None,
        "delivery": result,
    }


@app.get("/api/desktop/export_dir")
def desktop_export_dir() -> dict[str, Any]:
    """Temp directory used by desktop Export buttons (mp4/edl/csv/json)."""
    import tempfile

    out_dir = Path(tempfile.gettempdir()) / "opmiere_desktop_export"
    out_dir.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, Any]] = []
    for pat in ("*.mp4", "*.edl", "*.csv", "*.json"):
        for p in out_dir.glob(pat):
            if p.is_file():
                entries.append(
                    {
                        "name": p.name,
                        "path": str(p.resolve()),
                        "size": p.stat().st_size,
                    }
                )
    files = sorted(entries, key=lambda x: x["name"])
    return {
        "path": str(out_dir.resolve()),
        "count": len(files),
        "files": files[-30:],
    }


@app.post("/api/desktop/export_preset")
def desktop_export_preset(preset: str = "draft") -> dict[str, Any]:
    """Export with a named preset to a temp file (desktop shell)."""
    import tempfile

    ed = _ed()
    out_dir = Path(tempfile.gettempdir()) / "opmiere_desktop_export"
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in (preset or "draft"))
    out = out_dir / f"export_{safe}.mp4"
    try:
        result = ed.export_with_preset(out, preset=preset or "draft")
        path = result.get("path") or str(out)
        ok = Path(path).exists()
        return {
            "ok": ok,
            "path": str(Path(path).resolve()) if ok else None,
            "preset": preset,
            "result": result,
        }
    except Exception as e:
        # video-only demos: fall back to plain export
        try:
            written = ed.export(out, normalize_preset=None)
            return {
                "ok": Path(written).exists(),
                "path": str(Path(written).resolve()),
                "preset": preset,
                "warning": str(e)[:300],
                "result": None,
            }
        except Exception as e2:
            return {
                "ok": False,
                "error": f"{e}; fallback: {e2}",
                "path": None,
                "preset": preset,
            }


@app.post("/api/desktop/export_work")
def desktop_export_work(
    normalize_preset: str | None = None,
    delivery_preset: str = "streaming",
) -> dict[str, Any]:
    """Export work area [in, out) to temp file (desktop shell)."""
    import tempfile

    ed = _ed()
    io = ed.get_in_out()
    if not io.get("ready"):
        return {
            "ok": False,
            "error": "set In and Out points first (I / O keys)",
            "path": None,
            "work_in_out": io,
        }
    out_dir = Path(tempfile.gettempdir()) / "opmiere_desktop_export"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "export_work.mp4"
    try:
        result = ed.export_work_area(
            out,
            normalize_preset=normalize_preset,
            run_delivery_check=True,
            delivery_preset=delivery_preset,
        )
    except Exception as e:
        try:
            result = ed.export_work_area(
                out,
                normalize_preset=None,
                run_delivery_check=False,
            )
            return {
                "ok": Path(out).exists(),
                "path": str(Path(out).resolve()) if out.exists() else None,
                "warning": str(e)[:300],
                "work_in_out": io,
                "result": result,
            }
        except Exception as e2:
            return {
                "ok": False,
                "error": f"{e}; fallback: {e2}",
                "path": None,
                "work_in_out": io,
            }
    return {
        "ok": out.exists(),
        "path": str(out.resolve()) if out.exists() else None,
        "work_in_out": io,
        "result": result,
    }


@app.post("/api/project/create")
def project_create(body: CreateBody) -> dict[str, Any]:
    global _editor
    _editor = Editor.create(
        Path(body.bundle_path),
        fps=body.fps,
        width=body.width,
        height=body.height,
        generation_provider=_provider(),
    )
    return _editor.describe()


@app.post("/api/project/open")
def project_open(body: OpenBody) -> dict[str, Any]:
    global _editor
    _editor = Editor.open(Path(body.bundle_path), generation_provider=_provider())
    return _editor.describe()


class CloseBody(BaseModel):
    """Close the in-memory project. Optional save first."""

    save: bool = False


@app.post("/api/project/close")
def project_close(body: CloseBody | None = None) -> dict[str, Any]:
    """Release the open Editor (desktop Close / New without process restart)."""
    global _editor
    body = body or CloseBody()
    if _editor is None:
        return {
            "closed": True,
            "was_open": False,
            "saved": False,
            "project_open": False,
        }
    saved = False
    dirty = bool(_editor.is_dirty())
    path = str(_editor.bundle.root)
    if body.save:
        _editor.save()
        saved = True
        dirty = False
    _editor = None
    return {
        "closed": True,
        "was_open": True,
        "saved": saved,
        "was_dirty": dirty and not saved,
        "path": path,
        "project_open": False,
    }


@app.get("/api/project/state")
def project_state() -> dict[str, Any]:
    return _ed().describe()


@app.get("/api/project/timeline")
def project_timeline() -> dict[str, Any]:
    """Proportional timeline + proxy status for the scrub UI."""
    return _ed().timeline_view()


@app.post("/api/track")
def add_track(kind: str = "video") -> dict[str, Any]:
    if kind not in ("video", "audio"):
        raise HTTPException(400, "kind must be video or audio")
    return _ed().add_track(kind).to_dict()  # type: ignore[arg-type]


@app.post("/api/place")
def place_file(body: PlaceBody) -> dict[str, Any]:
    ed = _ed()
    track_id = body.track_id
    if not track_id:
        kind = body.kind if body.kind in ("video", "audio", "image") else "video"
        track_kind = "audio" if kind == "audio" else "video"
        existing = [t for t in ed.project.tracks if t.kind == track_kind]
        if existing:
            track_id = existing[0].id
        else:
            track_id = ed.add_track(track_kind).id  # type: ignore[arg-type]
    if body.build_proxy and body.kind == "video":
        media = ed.import_media(
            Path(body.path), body.kind, build_proxy=True,  # type: ignore[arg-type]
        )
        clip = ed.add_clip(track_id, media.id, body.start, 0, media.duration_frames)
        return clip.to_dict()
    clip = ed.place_from_file(
        Path(body.path), body.kind, track_id, start=body.start,  # type: ignore[arg-type]
    )
    return clip.to_dict()


@app.post("/api/upload_place")
async def upload_place(
    files: list[UploadFile] = File(...),
    build_proxy: bool = False,
) -> dict[str, Any]:
    """Browser drag-drop / file picker: save uploads then place_from_file.

    Writes into the open project bundle under media/_uploads/ then places
    each file (kind guessed by suffix). Returns placed clips + timeline.
    """
    import shutil

    ed = _ed()
    if not files:
        raise HTTPException(400, "no files")
    upload_dir = ed.bundle.root / "media" / "_uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    placed: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for uf in files:
        name = Path(uf.filename or "upload.bin").name
        # avoid collisions
        dest = upload_dir / name
        n = 1
        while dest.exists():
            dest = upload_dir / f"{dest.stem}_{n}{dest.suffix}"
            n += 1
        try:
            with dest.open("wb") as out:
                shutil.copyfileobj(uf.file, out)
            kind = ed.guess_media_kind(dest)
            track_kind = "audio" if kind == "audio" else "video"
            existing = [t for t in ed.project.tracks if t.kind == track_kind]
            if existing:
                track_id = existing[0].id
            else:
                track_id = ed.add_track(track_kind).id  # type: ignore[arg-type]
            track = ed.project.track_by_id(track_id)
            ordered = track.clips_in_order()
            start = 0 if not ordered else ordered[-1].end
            if build_proxy and kind == "video":
                media = ed.import_media(dest, kind, build_proxy=True)
                clip = ed.add_clip(
                    track_id, media.id, start, 0, media.duration_frames,
                )
            else:
                kwargs: dict[str, Any] = {}
                if kind == "image":
                    kwargs["duration_frames"] = max(1, int(ed.project.timebase.fps or 30) * 3)
                clip = ed.place_from_file(
                    dest, kind, track_id, start=start, **kwargs,  # type: ignore[arg-type]
                )
            placed.append(clip.to_dict() if hasattr(clip, "to_dict") else {"id": clip.id})
        except Exception as e:
            errors.append({"file": name, "error": str(e)[:300]})
        finally:
            try:
                uf.file.close()
            except Exception:
                pass
    return {
        "placed": placed,
        "count": len(placed),
        "errors": errors,
        "timeline": ed.timeline_view(),
        "state": ed.describe(),
    }


@app.post("/api/export")
def export_project(body: ExportBody) -> dict[str, Any]:
    ed = _ed()
    written = ed.export(
        Path(body.output_path),
        normalize_preset=body.normalize_preset,
    )
    payload: dict[str, Any] = {
        "output_path": str(written),
        "exists": written.exists(),
        "normalize_preset": body.normalize_preset,
    }
    if body.run_delivery_check:
        payload["delivery_check"] = ed.delivery_check(
            written, preset=body.delivery_preset,
        )
    return payload


@app.post("/api/review")
def review() -> dict[str, Any]:
    return _ed().review_cut()


@app.post("/api/sequence_sheet")
def sequence_sheet(body: SheetBody) -> dict[str, Any]:
    global _last_sheet
    ed = _ed()
    out = body.output_path
    if not out:
        out = str(ed.bundle.root / "review" / "sequence_sheet.png")
    result = ed.make_sequence_contact_sheet(
        out, max_tiles=body.max_tiles, cols=body.cols,
    )
    _last_sheet = result.get("path")
    return result


@app.get("/api/sequence_sheet/image")
def sequence_sheet_image() -> FileResponse:
    if not _last_sheet or not Path(_last_sheet).exists():
        raise HTTPException(404, "no sequence sheet yet — POST /api/sequence_sheet")
    return FileResponse(_last_sheet, media_type="image/png")


@app.post("/api/look")
def apply_look(body: LookBody) -> dict[str, Any]:
    return _ed().apply_project_look(body.look)


@app.get("/api/styles")
def list_styles() -> dict[str, Any]:
    return _ed().list_style_presets()


@app.post("/api/style")
def apply_style(body: StyleBody) -> dict[str, Any]:
    return _ed().apply_style_preset(
        body.styles,
        clip_ids=body.clip_ids,
        video_only=body.video_only,
        apply_motion=body.apply_motion,
    )


@app.get("/api/media")
def media_bin() -> dict[str, Any]:
    return _ed().list_media_bin()


@app.post("/api/media/proxy")
def media_proxy(body: MediaProxyBody) -> dict[str, Any]:
    return _ed().ensure_media_proxy(
        body.media_id, height=body.height, force=body.force,
    )


@app.post("/api/media/proxies")
def media_proxies_all(height: int = 480, force: bool = False) -> dict[str, Any]:
    return _ed().ensure_all_media_proxies(height=height, force=force)


@app.post("/api/search_transcripts")
def search_transcripts(body: SearchBody) -> dict[str, Any]:
    return _ed().search_transcripts(
        body.query, media_id=body.media_id, max_hits=body.max_hits,
    )


@app.post("/api/filler")
def filler_cuts(body: FillerBody) -> dict[str, Any]:
    return _ed().apply_filler_cuts(
        body.clip_id,
        dry_run=body.dry_run,
        extra_words=body.extra_words,
        pad_seconds=body.pad_seconds,
    )


@app.post("/api/ripple_delete")
def ripple_delete(body: RippleDeleteBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.ripple_delete(body.clip_id)
    return {**r, "timeline": ed.timeline_view()}


def _maybe_refresh(ed: Editor, *, enabled: bool, quick: bool) -> dict[str, Any] | None:
    """Best-effort proxy rebuild; layout must not fail if export is invalid mid-edit."""
    if not enabled:
        return None
    try:
        return ed.refresh_preview_proxy(quick=quick)
    except Exception as e:
        st = ed.preview_proxy_status()
        return {
            "error": str(e)[:500],
            "fresh": False,
            "exists": st.get("exists"),
            "path": st.get("path"),
            "agent_note": (
                "Layout saved; preview rebuild failed (base track may need "
                "start=0 + contiguity). Fix gaps or close_gaps then refresh."
            ),
        }


@app.post("/api/clip/layout")
def clip_layout(body: ClipLayoutBody) -> dict[str, Any]:
    """Atomic move/trim for timeline drag. Optionally quick-refresh scrub proxy."""
    ed = _ed()
    layout = ed.set_clip_layout(
        body.clip_id,
        start=body.start_frame,
        src_in=body.src_in,
        src_out=body.src_out,
    )
    return {
        "layout": layout,
        "timeline": ed.timeline_view(),
        "preview": _maybe_refresh(
            ed, enabled=body.refresh_preview, quick=body.quick_preview,
        ),
    }


@app.post("/api/clip/edge_trim")
def clip_edge_trim(body: EdgeTrimBody) -> dict[str, Any]:
    ed = _ed()
    result = ed.edge_trim(
        body.clip_id,
        body.edge,
        body.delta_frames,
        mode=body.mode,
    )
    return {
        "trim": result,
        "timeline": ed.timeline_view(),
        "preview": _maybe_refresh(
            ed, enabled=body.refresh_preview, quick=body.quick_preview,
        ),
    }


class MoveClipBody(BaseModel):
    clip_id: str
    start_frame: int
    refresh_preview: bool = True
    quick_preview: bool = True


@app.post("/api/clip/move")
def clip_move(body: MoveClipBody) -> dict[str, Any]:
    ed = _ed()
    clip = ed.move_clip(body.clip_id, body.start_frame)
    return {
        "clip": clip.to_dict(),
        "timeline": ed.timeline_view(),
        "preview": _maybe_refresh(
            ed, enabled=body.refresh_preview, quick=body.quick_preview,
        ),
    }


class MoveToTrackBody(BaseModel):
    clip_id: str
    track_id: str
    start: int | None = None


class AlignClipsBody(BaseModel):
    clip_ids: list[str]
    to_frame: int = 0
    mode: str = "relative"


class EffectsClipBody(BaseModel):
    clip_id: str


class PasteEffectsBody(BaseModel):
    clip_id: str
    replace: bool = True


class SlipBody(BaseModel):
    clip_id: str
    delta_src_frames: int


class RollBody(BaseModel):
    left_clip_id: str
    right_clip_id: str
    delta_frames: int


@app.post("/api/clip/move_to_track")
def clip_move_to_track(body: MoveToTrackBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.move_to_track(body.clip_id, body.track_id, start=body.start)
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/clips/align")
def clips_align(body: AlignClipsBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.align_clips(body.clip_ids, to_frame=body.to_frame, mode=body.mode)
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/clip/copy_effects")
def clip_copy_effects(body: EffectsClipBody) -> dict[str, Any]:
    return _ed().copy_effects(body.clip_id)


@app.post("/api/clip/paste_effects")
def clip_paste_effects(body: PasteEffectsBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.paste_effects(body.clip_id, replace=body.replace)
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/clip/slip")
def clip_slip(body: SlipBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.slip_clip(body.clip_id, body.delta_src_frames)
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/clip/roll")
def clip_roll(body: RollBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.roll_edit(body.left_clip_id, body.right_clip_id, body.delta_frames)
    return {**r, "timeline": ed.timeline_view()}


class SlideBody(BaseModel):
    clip_id: str
    delta_frames: int


class StretchBody(BaseModel):
    clip_id: str
    target_duration_frames: int
    clamp: bool = True


class MarkerNearBody(BaseModel):
    frame: int
    direction: str = "next"
    wrap: bool = False


@app.post("/api/clip/slide")
def clip_slide(body: SlideBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.slide_clip(body.clip_id, body.delta_frames)
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/clip/stretch")
def clip_stretch(body: StretchBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.stretch_to(
        body.clip_id,
        body.target_duration_frames,
        clamp=body.clamp,
    )
    return {**r, "timeline": ed.timeline_view()}


@app.get("/api/track/{track_id}/clips")
def track_clips(track_id: str) -> dict[str, Any]:
    return _ed().clips_on_track(track_id)


@app.post("/api/markers/near")
def markers_near(body: MarkerNearBody) -> dict[str, Any]:
    return _ed().marker_near(
        body.frame, direction=body.direction, wrap=body.wrap,
    )


class BatchEffectBody(BaseModel):
    clip_ids: list[str]
    effect: dict[str, Any]


class CropBody(BaseModel):
    clip_id: str
    width: int
    height: int
    x: int | str | None = None
    y: int | str | None = None


class FindGapsBody(BaseModel):
    track_id: str | None = None
    from_frame: int = 0
    min_gap_frames: int = 1


class CloseAllGapsBody(BaseModel):
    from_frame: int = 0


class RemoveEmptyTracksBody(BaseModel):
    keep_one_per_kind: bool = True


@app.post("/api/clips/effect")
def clips_effect(body: BatchEffectBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.apply_effect_to_clips(body.clip_ids, body.effect)
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/clip/crop")
def clip_crop(body: CropBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.set_clip_crop(
        body.clip_id, body.width, body.height, x=body.x, y=body.y,
    )
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/gaps/find")
def gaps_find(body: FindGapsBody) -> dict[str, Any]:
    return _ed().find_gaps(
        body.track_id,
        from_frame=body.from_frame,
        min_gap_frames=body.min_gap_frames,
    )


@app.post("/api/gaps/close_all")
def gaps_close_all(body: CloseAllGapsBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.close_all_gaps(from_frame=body.from_frame)
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/tracks/remove_empty")
def tracks_remove_empty(body: RemoveEmptyTracksBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.remove_empty_tracks(keep_one_per_kind=body.keep_one_per_kind)
    return {**r, "timeline": ed.timeline_view()}


@app.get("/api/tracks")
def tracks_list() -> dict[str, Any]:
    return _ed().list_tracks()


class RotateBody(BaseModel):
    clip_id: str
    degrees: float = 0.0


class ResetTransformBody(BaseModel):
    clip_id: str
    position: bool = True
    crop: bool = True
    rotate: bool = True
    opacity: bool = True


class SwapClipsBody(BaseModel):
    clip_a: str
    clip_b: str


class MoveTrackBody(BaseModel):
    track_id: str
    index: int | None = None
    delta: int | None = None


class TrackNameBody(BaseModel):
    track_id: str
    name: str | None = None


@app.post("/api/clip/rotate")
def clip_rotate(body: RotateBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.set_clip_rotate(body.clip_id, body.degrees)
    return {**r, "timeline": ed.timeline_view()}


class FlipBody(BaseModel):
    clip_id: str
    horizontal: bool | None = None
    vertical: bool | None = None
    toggle_h: bool = False
    toggle_v: bool = False


@app.post("/api/clip/flip")
def clip_flip(body: FlipBody) -> dict[str, Any]:
    ed = _ed()
    try:
        r = ed.set_clip_flip(
            body.clip_id,
            horizontal=body.horizontal,
            vertical=body.vertical,
            toggle_h=body.toggle_h,
            toggle_v=body.toggle_v,
        )
    except Exception as e:
        raise HTTPException(400, f"flip failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class ExportClipMediaBody(BaseModel):
    out_dir: str
    clip_ids: list[str] | None = None
    track_id: str | None = None
    include_audio: bool = True
    container: str = "mp4"


@app.post("/api/export/clip_media")
def export_clip_media_api(body: ExportClipMediaBody) -> dict[str, Any]:
    """Export each clip source range as standalone file."""
    ed = _ed()
    try:
        return ed.export_clip_media(
            body.out_dir,
            body.clip_ids,
            track_id=body.track_id,
            include_audio=body.include_audio,
            container=body.container,
        )
    except Exception as e:
        raise HTTPException(400, f"export_clip_media failed: {e}") from e


class BakeClipBody(BaseModel):
    clip_id: str
    replace: bool = True
    clear_effects: bool = True
    include_audio: bool = True


@app.post("/api/clip/bake")
def bake_clip_api(body: BakeClipBody) -> dict[str, Any]:
    """Render-and-replace: bake clip effects into new media."""
    ed = _ed()
    try:
        r = ed.bake_clip(
            body.clip_id,
            replace=body.replace,
            clear_effects=body.clear_effects,
            include_audio=body.include_audio,
        )
    except Exception as e:
        raise HTTPException(400, f"bake_clip failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class GradeLayerBody(BaseModel):
    effects: list[dict[str, Any]] | None = None
    start: int = 0
    end: int | None = None
    track_id: str | None = None
    opacity: float = 1.0
    name: str = "Grade"


@app.post("/api/edit/grade_layer")
def grade_layer_api(body: GradeLayerBody | None = None) -> dict[str, Any]:
    """Add overlay grade layer (black slug + effects)."""
    body = body or GradeLayerBody()
    ed = _ed()
    try:
        r = ed.add_grade_layer(
            body.effects,
            start=body.start,
            end=body.end,
            track_id=body.track_id,
            opacity=body.opacity,
            name=body.name,
        )
    except Exception as e:
        raise HTTPException(400, f"grade_layer failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


@app.get("/api/project/health")
def project_health_api() -> dict[str, Any]:
    """Read-only project health: preflight + gaps + unused + path-C."""
    return _ed().project_health_report()


@app.post("/api/clip/reset_transform")
def clip_reset_transform(body: ResetTransformBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.reset_clip_transform(
        body.clip_id,
        position=body.position,
        crop=body.crop,
        rotate=body.rotate,
        opacity=body.opacity,
    )
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/clips/swap")
def clips_swap(body: SwapClipsBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.swap_clips(body.clip_a, body.clip_b)
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/track/move")
def track_move(body: MoveTrackBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.move_track(body.track_id, index=body.index, delta=body.delta)
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/track/name")
def track_name(body: TrackNameBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.set_track_name(body.track_id, body.name)
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/preview/refresh")
def preview_refresh(body: PreviewRefreshBody) -> dict[str, Any]:
    """Rebuild scrub proxy if stale (quick=true for post-drag snappiness)."""
    return _ed().refresh_preview_proxy(
        quick=body.quick,
        force=body.force,
        height=body.height,
        fps=body.fps,
    )


class GainBody(BaseModel):
    clip_id: str
    db: float
    refresh_preview: bool = False


class WaveformBody(BaseModel):
    clip_id: str | None = None
    media_id: str | None = None
    num_peaks: int = 120


class CloseGapsBody(BaseModel):
    track_id: str | None = None
    from_frame: int = 0


@app.post("/api/clip/gain")
def clip_gain(body: GainBody) -> dict[str, Any]:
    ed = _ed()
    result = ed.set_clip_gain(body.clip_id, body.db)
    preview = _maybe_refresh(ed, enabled=body.refresh_preview, quick=True)
    return {
        "gain": result,
        "timeline": ed.timeline_view(),
        "preview": preview,
    }


@app.post("/api/waveform")
def waveform(body: WaveformBody) -> dict[str, Any]:
    return _ed().waveform_peaks(
        clip_id=body.clip_id,
        media_id=body.media_id,
        num_peaks=body.num_peaks,
    )


@app.get("/api/media/{media_id}/thumb.jpg")
def media_thumb_jpg(media_id: str, t: float = 0.1, width: int = 120) -> FileResponse:
    ed = _ed()
    try:
        r = ed.media_thumbnail(media_id, time_seconds=t, width=width)
    except Exception as e:
        raise HTTPException(400, str(e)[:300]) from e
    path = r.get("path")
    if not path or not Path(path).exists():
        raise HTTPException(404, "thumbnail missing")
    return FileResponse(path, media_type="image/jpeg")


class TranscribeMediaBody(BaseModel):
    media_id: str
    model_size: str = "base"
    language: str | None = None


@app.post("/api/media/transcribe")
def media_transcribe(body: TranscribeMediaBody) -> dict[str, Any]:
    """Transcribe media and cache (needs faster-whisper)."""
    return _ed().transcribe_media(
        body.media_id,
        model_size=body.model_size,
        language=body.language,
        cache=True,
    )


@app.post("/api/close_gaps")
def close_gaps_api(body: CloseGapsBody) -> dict[str, Any]:
    ed = _ed()
    track_id = body.track_id
    if not track_id:
        vids = [t for t in ed.project.tracks if t.kind == "video"]
        if not vids:
            raise HTTPException(400, "no video track")
        track_id = vids[0].id
    result = ed.close_gaps(track_id, from_frame=body.from_frame)
    return {"result": result, "timeline": ed.timeline_view()}


class PlaceBatchBody(BaseModel):
    paths: list[str] = Field(default_factory=list)
    kind: str | None = None
    sequential: bool = True
    build_proxy: bool = False
    conform: bool = True
    fit: str = "none"
    image_duration_frames: int = 90


class DuckBody(BaseModel):
    track_id: str
    against_track_id: str
    threshold_db: float = -30.0
    ratio: float = 8.0
    attack_ms: float = 20.0
    release_ms: float = 300.0
    makeup_db: float = 0.0


class ClearDuckBody(BaseModel):
    track_id: str


@app.post("/api/place_batch")
def place_batch_api(body: PlaceBatchBody) -> dict[str, Any]:
    ed = _ed()
    if not body.paths:
        raise HTTPException(400, "paths required")
    result = ed.place_batch(
        body.paths,
        kind=body.kind,  # type: ignore[arg-type]
        sequential=body.sequential,
        build_proxy=body.build_proxy,
        conform=body.conform,
        fit=body.fit,
        image_duration_frames=body.image_duration_frames,
    )
    return {"result": result, "timeline": ed.timeline_view()}


@app.get("/api/mix")
def mix_api() -> dict[str, Any]:
    return _ed().mix_view()


@app.post("/api/duck")
def duck_api(body: DuckBody) -> dict[str, Any]:
    ed = _ed()
    track = ed.set_ducking(
        body.track_id,
        body.against_track_id,
        threshold_db=body.threshold_db,
        ratio=body.ratio,
        attack_ms=body.attack_ms,
        release_ms=body.release_ms,
        makeup_db=body.makeup_db,
    )
    return {"track": track.to_dict(), "mix": ed.mix_view(), "timeline": ed.timeline_view()}


@app.post("/api/duck/clear")
def duck_clear_api(body: ClearDuckBody) -> dict[str, Any]:
    ed = _ed()
    track = ed.clear_ducking(body.track_id)
    return {"track": track.to_dict(), "mix": ed.mix_view(), "timeline": ed.timeline_view()}


class CutTemplateBody(BaseModel):
    template: str = "talking_head"
    paths: list[str] = Field(default_factory=list)
    music: str | None = None
    vo: str | None = None
    style_override: str | None = None
    dry_run: bool = False
    build_proxy: bool = False
    apply_silence: bool = False


class FinishBody(BaseModel):
    output_path: str
    normalize_preset: str | None = "streaming"
    delivery_preset: str = "streaming"
    run_review: bool = True
    run_sequence_sheet: bool = False


@app.get("/api/templates")
def templates_list() -> dict[str, Any]:
    return _ed().list_cut_templates() if _editor else {
        # allow listing without project
        **__import__("opmiere.render.cut_templates", fromlist=["list_templates"]).list_templates()
    }


@app.post("/api/templates/apply")
def templates_apply(body: CutTemplateBody) -> dict[str, Any]:
    ed = _ed()
    result = ed.apply_cut_template(
        body.template,
        paths=body.paths or None,
        music=body.music,
        vo=body.vo,
        style_override=body.style_override,
        dry_run=body.dry_run,
        build_proxy=body.build_proxy,
        apply_silence=body.apply_silence,
    )
    return result


@app.post("/api/finish")
def finish_api(body: FinishBody) -> dict[str, Any]:
    return _ed().finish_delivery(
        body.output_path,
        normalize_preset=body.normalize_preset,
        delivery_preset=body.delivery_preset,
        run_review=body.run_review,
        run_sequence_sheet=body.run_sequence_sheet,
        prepare=True,
    )


class FillGapsBody(BaseModel):
    track_id: str | None = None
    mode: str = "slug"


class MarkerBody(BaseModel):
    frame: int | None = None
    time_seconds: float | None = None
    label: str = ""
    color: str = "#7c9cff"


@app.post("/api/fill_gaps")
def fill_gaps_api(body: FillGapsBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.fill_track_gaps(body.track_id, mode=body.mode)
    return {"result": r, "timeline": ed.timeline_view()}


@app.post("/api/prepare_export")
def prepare_export_api() -> dict[str, Any]:
    ed = _ed()
    r = ed.prepare_export()
    return {"result": r, "timeline": ed.timeline_view()}


@app.get("/api/markers")
def markers_list() -> dict[str, Any]:
    return _ed().list_markers()


@app.post("/api/markers")
def markers_add(body: MarkerBody) -> dict[str, Any]:
    ed = _ed()
    m = ed.add_marker(
        body.frame, time_seconds=body.time_seconds,
        label=body.label, color=body.color,
    )
    return {"marker": m, "markers": ed.list_markers()["markers"]}


class MarkerDeleteBody(BaseModel):
    marker_id: str


class SplitBody(BaseModel):
    clip_id: str
    at_frame: int
    follow_links: bool = True


@app.post("/api/markers/delete")
def markers_delete(body: MarkerDeleteBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.delete_marker(body.marker_id)
    return {**r, "markers": ed.list_markers()["markers"]}


class MarkerUpdateBody(BaseModel):
    marker_id: str
    label: str | None = None
    color: str | None = None
    frame: int | None = None
    time_seconds: float | None = None


@app.post("/api/markers/update")
def markers_update(body: MarkerUpdateBody) -> dict[str, Any]:
    ed = _ed()
    m = ed.update_marker(
        body.marker_id,
        label=body.label,
        color=body.color,
        frame=body.frame,
        time_seconds=body.time_seconds,
    )
    return {"marker": m, "markers": ed.list_markers()["markers"]}


@app.post("/api/split")
def split_at(body: SplitBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.split_clip(
        body.clip_id, body.at_frame, follow_links=body.follow_links,
    )
    if isinstance(r, tuple):
        a, b = r
        return {
            "first": a.to_dict(),
            "second": b.to_dict(),
            "timeline": ed.timeline_view(),
        }
    return {**r, "timeline": ed.timeline_view()}


class JLCutBody(BaseModel):
    clip_id: str
    frames: int = 15


class DupTrackBody(BaseModel):
    track_id: str
    copy_clips: bool = True
    name: str | None = None


class PurgeMediaBody(BaseModel):
    delete_files: bool = False


@app.post("/api/clip/j_cut")
def clip_j_cut(body: JLCutBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.j_cut(body.clip_id, body.frames)
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/clip/l_cut")
def clip_l_cut(body: JLCutBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.l_cut(body.clip_id, body.frames)
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/track/duplicate")
def track_duplicate(body: DupTrackBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.duplicate_track(
        body.track_id, copy_clips=body.copy_clips, name=body.name,
    )
    return {**r, "timeline": ed.timeline_view()}


@app.get("/api/media/unused")
def media_unused() -> dict[str, Any]:
    return _ed().list_unused_media()


@app.post("/api/media/purge_unused")
def media_purge_unused(body: PurgeMediaBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.purge_unused_media(delete_files=body.delete_files)
    return {**r, "timeline": ed.timeline_view()}


@app.get("/api/project/stats")
def project_stats_api() -> dict[str, Any]:
    return _ed().project_stats()


class RazorBody(BaseModel):
    at_frame: int
    track_ids: list[str] | None = None


class TransitionBody(BaseModel):
    right_clip_id: str
    transition_type: str = "cross_dissolve"
    duration_frames: int = 12
    left_clip_id: str | None = None


@app.post("/api/razor")
def razor_api(body: RazorBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.split_all_at(body.at_frame, track_ids=body.track_ids)
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/transition")
def transition_api(body: TransitionBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.link_transition(
        body.right_clip_id,
        transition_type=body.transition_type,
        duration_frames=body.duration_frames,
        left_clip_id=body.left_clip_id,
    )
    return {**r, "timeline": ed.timeline_view()}


class PasteBody(BaseModel):
    track_id: str | None = None
    start: int | None = None
    playhead_frame: int | None = None
    mode: str = "insert"


class InOutBody(BaseModel):
    frame: int | None = None
    time_seconds: float | None = None


class ExportWorkBody(BaseModel):
    output_path: str
    normalize_preset: str | None = "streaming"
    run_delivery_check: bool = True


class ClipIdBody(BaseModel):
    clip_id: str


@app.post("/api/clip/copy")
def clip_copy(body: ClipIdBody) -> dict[str, Any]:
    return _ed().copy_clip(body.clip_id)


@app.post("/api/clip/paste")
def clip_paste(body: PasteBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.paste_clip(
        track_id=body.track_id,
        start=body.start,
        at_playhead=body.playhead_frame is not None,
        playhead_frame=body.playhead_frame,
        mode=body.mode or "insert",
    )
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/clip/duplicate")
def clip_duplicate(body: ClipIdBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.duplicate_clip(body.clip_id)
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/in_out/in")
def set_in_api(body: InOutBody) -> dict[str, Any]:
    return _ed().set_in_point(body.frame, time_seconds=body.time_seconds)


@app.post("/api/in_out/out")
def set_out_api(body: InOutBody) -> dict[str, Any]:
    return _ed().set_out_point(body.frame, time_seconds=body.time_seconds)


@app.post("/api/in_out/clear")
def clear_in_out_api() -> dict[str, Any]:
    return _ed().clear_in_out()


@app.get("/api/in_out")
def get_in_out_api() -> dict[str, Any]:
    return _ed().get_in_out()


@app.post("/api/export_work")
def export_work_api(body: ExportWorkBody) -> dict[str, Any]:
    return _ed().export_work_area(
        body.output_path,
        normalize_preset=body.normalize_preset,
        run_delivery_check=body.run_delivery_check,
    )


class TrackFlagBody(BaseModel):
    track_id: str
    value: bool = True
    exclusive: bool = False


class ClipMuteBody(BaseModel):
    clip_id: str
    muted: bool = True


@app.post("/api/track/mute")
def track_mute(body: TrackFlagBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.set_track_muted(body.track_id, body.value)
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/track/solo")
def track_solo(body: TrackFlagBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.set_track_solo(
        body.track_id, body.value, exclusive=body.exclusive,
    )
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/track/lock")
def track_lock(body: TrackFlagBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.set_track_locked(body.track_id, body.value)
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/clip/mute")
def clip_mute(body: ClipMuteBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.set_clip_muted(body.clip_id, body.muted)
    return {**r, "timeline": ed.timeline_view()}


class MultiClipsBody(BaseModel):
    clip_ids: list[str] = Field(default_factory=list)
    delta_frames: int = 0
    muted: bool = True
    ripple: bool = False
    follow_links: bool = True


@app.post("/api/clips/nudge")
def clips_nudge(body: MultiClipsBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.nudge_clips(
        body.clip_ids, body.delta_frames, follow_links=body.follow_links,
    )
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/clips/mute")
def clips_mute(body: MultiClipsBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.set_clips_muted(body.clip_ids, body.muted)
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/clips/delete")
def clips_delete(body: MultiClipsBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.delete_clips(
        body.clip_ids, ripple=body.ripple, follow_links=body.follow_links,
    )
    return {**r, "timeline": ed.timeline_view()}


class LinkClipsBody(BaseModel):
    clip_ids: list[str]
    group_id: str | None = None


class UnlinkClipsBody(BaseModel):
    clip_ids: list[str] | None = None


class LinkedGroupBody(BaseModel):
    clip_id: str


class TcBody(BaseModel):
    frame: int | None = None
    tc: str | None = None


@app.post("/api/clips/link")
def clips_link(body: LinkClipsBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.link_clips(body.clip_ids, group_id=body.group_id)
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/clips/unlink")
def clips_unlink(body: UnlinkClipsBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.unlink_clips(body.clip_ids)
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/clips/linked")
def clips_linked(body: LinkedGroupBody) -> dict[str, Any]:
    return _ed().linked_group(body.clip_id)


@app.post("/api/tc/format")
def tc_format(body: TcBody) -> dict[str, Any]:
    if body.frame is None:
        raise HTTPException(400, "frame required")
    return _ed().frames_to_tc(body.frame)


@app.post("/api/tc/parse")
def tc_parse(body: TcBody) -> dict[str, Any]:
    if not body.tc:
        raise HTTPException(400, "tc required")
    return _ed().tc_to_frames(body.tc)


class RippleNudgeBody(BaseModel):
    clip_id: str
    delta_frames: int
    include_self: bool = True


class InsertTimeBody(BaseModel):
    track_id: str | None = None
    at_frame: int
    frames: int = 15


class ExtractTimeBody(BaseModel):
    track_id: str | None = None
    start_frame: int
    end_frame: int
    ripple: bool = True


@app.post("/api/ripple_nudge")
def ripple_nudge_api(body: RippleNudgeBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.ripple_nudge(
        body.clip_id, body.delta_frames, include_self=body.include_self,
    )
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/insert_time")
def insert_time_api(body: InsertTimeBody) -> dict[str, Any]:
    ed = _ed()
    tid = body.track_id
    if not tid:
        vids = [t for t in ed.project.tracks if t.kind == "video"]
        if not vids:
            raise HTTPException(400, "no video track")
        tid = vids[0].id
    r = ed.insert_time(tid, body.at_frame, body.frames)
    return {**r, "timeline": ed.timeline_view()}


class InsertEditBody(BaseModel):
    media_id: str
    track_id: str | None = None
    at_frame: int
    src_in: int = 0
    src_out: int | None = None
    ripple: bool = True
    name: str | None = None


@app.post("/api/edit/insert")
def insert_edit_api(body: InsertEditBody) -> dict[str, Any]:
    """Classic insert edit (ripple place)."""
    ed = _ed()
    tid = body.track_id
    if not tid:
        vids = [t for t in ed.project.tracks if t.kind == "video"]
        if not vids:
            raise HTTPException(400, "no video track")
        tid = vids[0].id
    try:
        r = ed.insert_edit(
            body.media_id,
            tid,
            body.at_frame,
            src_in=body.src_in,
            src_out=body.src_out,
            ripple=body.ripple,
            name=body.name,
        )
    except Exception as e:
        raise HTTPException(400, f"insert_edit failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class OverwriteEditBody(BaseModel):
    media_id: str
    track_id: str | None = None
    at_frame: int
    src_in: int = 0
    src_out: int | None = None
    name: str | None = None


@app.post("/api/edit/overwrite")
def overwrite_edit_api(body: OverwriteEditBody) -> dict[str, Any]:
    """Classic overwrite edit (lift window then place)."""
    ed = _ed()
    tid = body.track_id
    if not tid:
        vids = [t for t in ed.project.tracks if t.kind == "video"]
        if not vids:
            raise HTTPException(400, "no video track")
        tid = vids[0].id
    try:
        r = ed.overwrite_edit(
            body.media_id,
            tid,
            body.at_frame,
            src_in=body.src_in,
            src_out=body.src_out,
            name=body.name,
        )
    except Exception as e:
        raise HTTPException(400, f"overwrite_edit failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class ThreePointBody(BaseModel):
    media_id: str
    track_id: str | None = None
    mode: str = "overwrite"
    fit: str = "stretch"
    src_in: int = 0
    src_out: int | None = None
    name: str | None = None


@app.post("/api/edit/three_point")
def three_point_edit_api(body: ThreePointBody) -> dict[str, Any]:
    """Three-point edit into work area [in, out)."""
    ed = _ed()
    tid = body.track_id
    if not tid:
        vids = [t for t in ed.project.tracks if t.kind == "video"]
        if not vids:
            raise HTTPException(400, "no video track")
        tid = vids[0].id
    try:
        r = ed.three_point_edit(
            body.media_id,
            tid,
            mode=body.mode,
            fit=body.fit,
            src_in=body.src_in,
            src_out=body.src_out,
            name=body.name,
        )
    except Exception as e:
        raise HTTPException(400, f"three_point_edit failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


@app.get("/api/media/usage")
def media_usage_api() -> dict[str, Any]:
    """Per-media timeline usage report."""
    return _ed().media_usage_report()


class ApplyEffectsTrackBody(BaseModel):
    track_id: str
    effects: list[dict[str, Any]]
    replace_types: bool = True


@app.post("/api/track/apply_effects")
def apply_effects_track_api(body: ApplyEffectsTrackBody) -> dict[str, Any]:
    """Apply effects to every clip on a track."""
    ed = _ed()
    try:
        r = ed.apply_effects_to_track(
            body.track_id,
            body.effects,
            replace_types=body.replace_types,
        )
    except Exception as e:
        raise HTTPException(400, f"apply_effects_to_track failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class ClearEffectsBody(BaseModel):
    clip_ids: list[str] | None = None
    track_id: str | None = None
    types: list[str] | None = None


@app.post("/api/effects/clear")
def clear_effects_api(body: ClearEffectsBody) -> dict[str, Any]:
    """Clear effects on selection or track."""
    ed = _ed()
    try:
        r = ed.clear_effects(
            body.clip_ids,
            track_id=body.track_id,
            types=body.types,
        )
    except Exception as e:
        raise HTTPException(400, f"clear_effects failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/extract_time")
def extract_time_api(body: ExtractTimeBody) -> dict[str, Any]:
    ed = _ed()
    tid = body.track_id
    if not tid:
        vids = [t for t in ed.project.tracks if t.kind == "video"]
        if not vids:
            raise HTTPException(400, "no video track")
        tid = vids[0].id
    r = ed.extract_time(
        tid, body.start_frame, body.end_frame, ripple=body.ripple,
    )
    return {**r, "timeline": ed.timeline_view()}


class ClipMetaBody(BaseModel):
    clip_id: str
    name: str | None = None
    color: str | None = None
    clear_name: bool = False
    clear_color: bool = False


class AutosaveBody(BaseModel):
    enabled: bool = True


@app.post("/api/clip/meta")
def clip_meta(body: ClipMetaBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.set_clip_meta(
        body.clip_id,
        name=body.name,
        color=body.color,
        clear_name=body.clear_name,
        clear_color=body.clear_color,
    )
    return {**r, "timeline": ed.timeline_view()}


@app.get("/api/clip/colors")
def clip_colors() -> dict[str, Any]:
    from ..recent import CLIP_COLORS
    return {"colors": list(CLIP_COLORS)}


@app.get("/api/recent")
def recent_projects(limit: int = 12) -> dict[str, Any]:
    from ..recent import list_recent
    return list_recent(limit=limit)


@app.post("/api/autosave")
def autosave_api(body: AutosaveBody) -> dict[str, Any]:
    return _ed().set_autosave(body.enabled)


@app.get("/api/dirty")
def dirty_api() -> dict[str, Any]:
    ed = _ed()
    return {
        "dirty": ed.is_dirty(),
        "autosave": ed._autosave,
        "bundle_path": str(ed.bundle.root),
    }


class SpeedBody(BaseModel):
    clip_id: str
    speed: float = 1.0


class PositionBody(BaseModel):
    clip_id: str
    x: float = 0.05
    y: float = 0.05
    scale: float = 0.35


class NotesBody(BaseModel):
    notes: str = ""


@app.post("/api/clip/speed")
def clip_speed(body: SpeedBody) -> dict[str, Any]:
    ed = _ed()
    clip = ed.set_speed(body.clip_id, body.speed)
    return {"clip": clip.to_dict(), "timeline": ed.timeline_view()}


@app.post("/api/clip/position")
def clip_position(body: PositionBody) -> dict[str, Any]:
    ed = _ed()
    clip = ed.set_position(body.clip_id, body.x, body.y, body.scale)
    return {"clip": clip.to_dict(), "timeline": ed.timeline_view()}


@app.post("/api/clip/position/clear")
def clip_position_clear(body: ClipIdBody) -> dict[str, Any]:
    ed = _ed()
    clip = ed.clear_position(body.clip_id)
    return {"clip": clip.to_dict(), "timeline": ed.timeline_view()}


@app.get("/api/notes")
def notes_get() -> dict[str, Any]:
    return _ed().get_project_notes()


@app.post("/api/notes")
def notes_set(body: NotesBody) -> dict[str, Any]:
    return _ed().set_project_notes(body.notes)


@app.get("/api/help/keymap")
def keymap_help() -> dict[str, Any]:
    return Editor.get_keymap_help()


class FreezeBody(BaseModel):
    clip_id: str
    at_timeline_frame: int | None = None
    duration_frames: int = 30


class ReverseBody(BaseModel):
    clip_id: str
    replace: bool = True


@app.post("/api/clip/freeze")
def clip_freeze(body: FreezeBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.freeze_frame(
        body.clip_id,
        at_timeline_frame=body.at_timeline_frame,
        duration_frames=body.duration_frames,
    )
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/clip/reverse")
def clip_reverse(body: ReverseBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.reverse_clip(body.clip_id, replace=body.replace)
    return {**r, "timeline": ed.timeline_view()}


class StabilizeBody(BaseModel):
    clip_id: str
    replace: bool = True
    strength: float = 1.0


class ExportMarkersBody(BaseModel):
    path: str | None = None
    format: str = "youtube"


class AttrClipBody(BaseModel):
    clip_id: str


class PasteAttrBody(BaseModel):
    clip_id: str
    speed: bool = True
    position: bool = True
    gain: bool = True
    opacity: bool = True
    fades: bool = True


@app.post("/api/clip/stabilize")
def clip_stabilize(body: StabilizeBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.stabilize_clip(
        body.clip_id, replace=body.replace, strength=body.strength,
    )
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/markers/export")
def markers_export(body: ExportMarkersBody) -> dict[str, Any]:
    return _ed().export_markers(body.path, format=body.format)


class ImportMarkersBody(BaseModel):
    text: str
    format: str = "youtube"
    replace: bool = False
    default_color: str = "#7c9cff"


class ExportEdlBody(BaseModel):
    path: str | None = None
    title: str | None = None


class SearchClipsBody(BaseModel):
    query: str
    track_id: str | None = None
    kind: str | None = None


@app.post("/api/markers/import")
def markers_import(body: ImportMarkersBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.import_markers(
        body.text,
        format=body.format,
        replace=body.replace,
        default_color=body.default_color,
    )
    return {**r, "markers": ed.list_markers()["markers"]}


@app.post("/api/export/edl")
def export_edl_api(body: ExportEdlBody) -> dict[str, Any]:
    return _ed().export_edl(body.path, title=body.title)


@app.get("/api/clip/{clip_id}/describe")
def clip_describe(clip_id: str) -> dict[str, Any]:
    return _ed().describe_clip(clip_id)


@app.post("/api/clips/search")
def clips_search(body: SearchClipsBody) -> dict[str, Any]:
    return _ed().search_clips(
        body.query, track_id=body.track_id, kind=body.kind,
    )


class ClipsInRangeBody(BaseModel):
    start_frame: int
    end_frame: int
    track_id: str | None = None
    kind: str | None = None
    partial: bool = True


class FitToFillBody(BaseModel):
    clip_id: str
    end_frame: int | None = None
    clamp: bool = True


class ReplaceEditBody(BaseModel):
    clip_id: str
    media_id: str
    mode: str = "stretch"


class CopyToTrackBody(BaseModel):
    clip_id: str
    track_id: str
    start: int | None = None
    copy_effects: bool = True
    copy_link: bool = False


class RenameClipsBody(BaseModel):
    pattern: str
    clip_ids: list[str] | None = None
    track_id: str | None = None


class ImportEdlBody(BaseModel):
    text: str | None = None
    path: str | None = None
    track_id: str | None = None
    replace_track: bool = False
    media_map: dict[str, str] | None = None


@app.post("/api/clips/in_range")
def clips_in_range_api(body: ClipsInRangeBody) -> dict[str, Any]:
    return _ed().clips_in_range(
        body.start_frame,
        body.end_frame,
        track_id=body.track_id,
        kind=body.kind,
        partial=body.partial,
    )


@app.post("/api/clip/fit_to_fill")
def clip_fit_to_fill(body: FitToFillBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.fit_to_fill(body.clip_id, end_frame=body.end_frame, clamp=body.clamp)
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/clip/replace_edit")
def clip_replace_edit(body: ReplaceEditBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.replace_edit(body.clip_id, body.media_id, mode=body.mode)
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/clip/copy_to_track")
def clip_copy_to_track(body: CopyToTrackBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.copy_to_track(
        body.clip_id,
        body.track_id,
        start=body.start,
        copy_effects=body.copy_effects,
        copy_link=body.copy_link,
    )
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/clips/rename")
def clips_rename(body: RenameClipsBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.rename_clips(
        body.pattern, clip_ids=body.clip_ids, track_id=body.track_id,
    )
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/import/edl")
def import_edl_api(body: ImportEdlBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.import_edl(
        body.text,
        path=body.path,
        track_id=body.track_id,
        replace_track=body.replace_track,
        media_map=body.media_map,
    )
    return {**r, "timeline": ed.timeline_view()}


class LiftBody(BaseModel):
    start_frame: int
    end_frame: int
    track_id: str | None = None
    track_ids: list[str] | None = None
    kind: str | None = None


class SplitMarkersBody(BaseModel):
    track_ids: list[str] | None = None
    marker_ids: list[str] | None = None


class MatchDurBody(BaseModel):
    clip_id: str
    reference_clip_id: str
    clamp: bool = True


class SetClipsColorBody(BaseModel):
    clip_ids: list[str]
    color: str | None = None


class ClipsByColorBody(BaseModel):
    color: str
    track_id: str | None = None
    kind: str | None = None


class ExportCutlistBody(BaseModel):
    path: str | None = None
    format: str = "csv"
    track_id: str | None = None


class PlaceMediaBody(BaseModel):
    media_id: str
    track_id: str
    start: int
    src_in: int | None = None
    src_out: int | None = None
    mode: str = "insert"
    name: str | None = None


@app.post("/api/lift")
def lift_api(body: LiftBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.lift(
        body.start_frame,
        body.end_frame,
        track_id=body.track_id,
        track_ids=body.track_ids,
        kind=body.kind,
    )
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/split_at_markers")
def split_at_markers_api(body: SplitMarkersBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.split_at_markers(
        track_ids=body.track_ids, marker_ids=body.marker_ids,
    )
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/clip/match_duration")
def match_duration_api(body: MatchDurBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.match_duration(
        body.clip_id, body.reference_clip_id, clamp=body.clamp,
    )
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/clips/color")
def set_clips_color_api(body: SetClipsColorBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.set_clips_color(body.clip_ids, body.color)
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/clips/by_color")
def clips_by_color_api(body: ClipsByColorBody) -> dict[str, Any]:
    return _ed().clips_by_color(
        body.color, track_id=body.track_id, kind=body.kind,
    )


@app.post("/api/export/cutlist")
def export_cutlist_api(body: ExportCutlistBody) -> dict[str, Any]:
    return _ed().export_cutlist(
        body.path, format=body.format, track_id=body.track_id,
    )


@app.post("/api/place_media")
def place_media_api(body: PlaceMediaBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.place_media(
        body.media_id,
        body.track_id,
        body.start,
        src_in=body.src_in,
        src_out=body.src_out,
        mode=body.mode,
        name=body.name,
    )
    return {**r, "timeline": ed.timeline_view()}


class JoinClipsBody(BaseModel):
    clip_id_a: str
    clip_id_b: str


class SetClipsSpeedBody(BaseModel):
    clip_ids: list[str]
    speed: float


class TrimRangeBody(BaseModel):
    clip_id: str
    start_frame: int
    end_frame: int
    mode: str = "normal"


class AutoLinkBody(BaseModel):
    tolerance_frames: int = 0
    track_id_video: str | None = None
    track_id_audio: str | None = None


class SetClipsMetaBody(BaseModel):
    clip_ids: list[str]
    name: str | None = None
    color: str | None = None
    clear_name: bool = False
    clear_color: bool = False


@app.post("/api/clips/join")
@app.post("/api/edit/join_clips")
def join_clips_api(body: JoinClipsBody) -> dict[str, Any]:
    """Join two adjacent hard-cut clips (same media). Alias: /api/edit/join_clips."""
    ed = _ed()
    r = ed.join_clips(body.clip_id_a, body.clip_id_b)
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/clips/speed")
def set_clips_speed_api(body: SetClipsSpeedBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.set_clips_speed(body.clip_ids, body.speed)
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/clip/trim_range")
def trim_range_api(body: TrimRangeBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.trim_to_range(
        body.clip_id, body.start_frame, body.end_frame, mode=body.mode,
    )
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/auto_link_av")
def auto_link_av_api(body: AutoLinkBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.auto_link_av(
        tolerance_frames=body.tolerance_frames,
        track_id_video=body.track_id_video,
        track_id_audio=body.track_id_audio,
    )
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/clips/meta")
def set_clips_meta_api(body: SetClipsMetaBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.set_clips_meta(
        body.clip_ids,
        name=body.name,
        color=body.color,
        clear_name=body.clear_name,
        clear_color=body.clear_color,
    )
    return {**r, "timeline": ed.timeline_view()}


class StaggerBody(BaseModel):
    clip_ids: list[str]
    offset_frames: int


class ReverseTrackBody(BaseModel):
    track_id: str
    pack_from: int = 0


class ClearTransitionsBody(BaseModel):
    track_id: str | None = None
    clip_ids: list[str] | None = None


class SetClipsFadesBody(BaseModel):
    clip_ids: list[str]
    fade_in_frames: int | None = None
    fade_out_frames: int | None = None


class AppendMediaBody(BaseModel):
    media_id: str
    track_id: str
    src_in: int | None = None
    src_out: int | None = None
    name: str | None = None


class DuplicateRangeBody(BaseModel):
    start_frame: int
    end_frame: int
    track_id: str
    dest_start: int | None = None
    dest_track_id: str | None = None


@app.post("/api/clips/stagger")
def stagger_api(body: StaggerBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.stagger_clips(body.clip_ids, body.offset_frames)
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/track/reverse_order")
def reverse_track_api(body: ReverseTrackBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.reverse_track_order(body.track_id, pack_from=body.pack_from)
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/transitions/clear")
def clear_transitions_api(body: ClearTransitionsBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.clear_transitions(track_id=body.track_id, clip_ids=body.clip_ids)
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/clips/fades")
def set_clips_fades_api(body: SetClipsFadesBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.set_clips_fades(
        body.clip_ids,
        fade_in_frames=body.fade_in_frames,
        fade_out_frames=body.fade_out_frames,
    )
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/append_media")
def append_media_api(body: AppendMediaBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.append_media(
        body.media_id, body.track_id,
        src_in=body.src_in, src_out=body.src_out, name=body.name,
    )
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/duplicate_range")
def duplicate_range_api(body: DuplicateRangeBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.duplicate_range(
        body.start_frame,
        body.end_frame,
        track_id=body.track_id,
        dest_start=body.dest_start,
        dest_track_id=body.dest_track_id,
    )
    return {**r, "timeline": ed.timeline_view()}


class MoveBlockBody(BaseModel):
    clip_ids: list[str]
    to_frame: int
    follow_links: bool = False


class SetClipsGainBody(BaseModel):
    clip_ids: list[str]
    db: float


class SetClipsOpacityBody(BaseModel):
    clip_ids: list[str]
    amount: float


class ValidateBody(BaseModel):
    track_id: str | None = None


class ExtractRangeBody(BaseModel):
    start_frame: int
    end_frame: int
    track_id: str | None = None
    track_ids: list[str] | None = None
    kind: str | None = None
    ripple: bool = True


class ApplyXfadeBody(BaseModel):
    track_id: str
    transition_type: str = "cross_dissolve"
    duration_frames: int = 15
    max_count: int | None = None


class SnapClipBody(BaseModel):
    clip_id: str
    to: str = "prev_end"


class QuantizeBody(BaseModel):
    clip_ids: list[str]
    grid_frames: int
    edge: str = "start"


class ImportCutlistBody(BaseModel):
    text: str | None = None
    path: str | None = None
    track_id: str | None = None
    replace_track: bool = False


class NameFromMediaBody(BaseModel):
    clip_ids: list[str] | None = None
    track_id: str | None = None
    strip_ext: bool = True


@app.post("/api/clips/move_block")
def move_block_api(body: MoveBlockBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.move_block(
        body.clip_ids, body.to_frame, follow_links=body.follow_links,
    )
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/clips/gain")
def set_clips_gain_api(body: SetClipsGainBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.set_clips_gain(body.clip_ids, body.db)
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/clips/opacity")
def set_clips_opacity_api(body: SetClipsOpacityBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.set_clips_opacity(body.clip_ids, body.amount)
    return {**r, "timeline": ed.timeline_view()}


@app.get("/api/validate")
def validate_api(track_id: str | None = None) -> dict[str, Any]:
    return _ed().validate_timeline(track_id=track_id)


@app.post("/api/extract_range")
def extract_range_api(body: ExtractRangeBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.extract_range(
        body.start_frame,
        body.end_frame,
        track_id=body.track_id,
        track_ids=body.track_ids,
        kind=body.kind,
        ripple=body.ripple,
    )
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/transitions/apply_on_cuts")
def apply_xfade_api(body: ApplyXfadeBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.apply_transitions_on_cuts(
        body.track_id,
        transition_type=body.transition_type,
        duration_frames=body.duration_frames,
        max_count=body.max_count,
    )
    return {**r, "timeline": ed.timeline_view()}


@app.get("/api/media/status")
def media_status_api() -> dict[str, Any]:
    return _ed().list_media_status()


@app.post("/api/clips/name_from_media")
def name_from_media_api(body: NameFromMediaBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.name_clips_from_media(
        body.clip_ids, track_id=body.track_id, strip_ext=body.strip_ext,
    )
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/clip/snap")
def snap_clip_api(body: SnapClipBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.snap_clip(body.clip_id, to=body.to)
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/clips/quantize")
def quantize_api(body: QuantizeBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.quantize_clips(body.clip_ids, body.grid_frames, edge=body.edge)
    return {**r, "timeline": ed.timeline_view()}


class SnapToMarkersBody(BaseModel):
    clip_ids: list[str]
    edge: str = "start"
    max_delta_frames: int | None = None
    prefer: str = "nearest"


@app.post("/api/clips/snap_to_markers")
def snap_to_markers_api(body: SnapToMarkersBody) -> dict[str, Any]:
    """Snap clip starts/ends to nearest timeline markers."""
    ed = _ed()
    try:
        r = ed.snap_clips_to_markers(
            body.clip_ids,
            edge=body.edge,
            max_delta_frames=body.max_delta_frames,
            prefer=body.prefer,
        )
    except Exception as e:
        raise HTTPException(400, f"snap_to_markers failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/import/cutlist")
def import_cutlist_api(body: ImportCutlistBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.import_cutlist(
        body.text,
        path=body.path,
        track_id=body.track_id,
        replace_track=body.replace_track,
    )
    return {**r, "timeline": ed.timeline_view()}


class WorkAreaClipBody(BaseModel):
    clip_id: str


class WorkAreaSelBody(BaseModel):
    clip_ids: list[str]


class MarkersFromCutsBody(BaseModel):
    track_id: str
    label_prefix: str = "Cut"
    color: str = "#ffb703"
    include_start: bool = False


class ShiftMarkersBody(BaseModel):
    delta_frames: int
    marker_ids: list[str] | None = None


class SoloClipBody(BaseModel):
    clip_id: str
    exclusive: bool = True


class ColorCycleBody(BaseModel):
    clip_ids: list[str] | None = None
    track_id: str | None = None


@app.post("/api/work_area/from_clip")
def work_area_from_clip(body: WorkAreaClipBody) -> dict[str, Any]:
    return _ed().set_work_area_from_clip(body.clip_id)


@app.post("/api/work_area/from_selection")
def work_area_from_sel(body: WorkAreaSelBody) -> dict[str, Any]:
    return _ed().set_work_area_from_selection(body.clip_ids)


@app.post("/api/markers/from_cuts")
def markers_from_cuts_api(body: MarkersFromCutsBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.markers_from_cuts(
        body.track_id,
        label_prefix=body.label_prefix,
        color=body.color,
        include_start=body.include_start,
    )
    return {**r, "markers": ed.list_markers()["markers"]}


@app.post("/api/markers/shift")
def shift_markers_api(body: ShiftMarkersBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.shift_markers(body.delta_frames, marker_ids=body.marker_ids)
    return {**r, "markers": ed.list_markers()["markers"]}


class ClearMarkersBody(BaseModel):
    prefix: str | None = None
    marker_ids: list[str] | None = None


@app.post("/api/markers/clear")
def clear_markers_api(body: ClearMarkersBody | None = None) -> dict[str, Any]:
    """Clear markers (all / prefix / ids). Empty body clears all."""
    body = body or ClearMarkersBody()
    ed = _ed()
    r = ed.clear_markers(prefix=body.prefix, marker_ids=body.marker_ids)
    return {**r, "markers": ed.list_markers()["markers"] if r.get("remaining") else []}


@app.post("/api/clip/solo")
def solo_clip_api(body: SoloClipBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.solo_clip(body.clip_id, exclusive=body.exclusive)
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/clips/unmute_all")
def unmute_all_api(track_id: str | None = None) -> dict[str, Any]:
    ed = _ed()
    r = ed.unmute_all_clips(track_id=track_id)
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/clips/color_cycle")
def color_cycle_api(body: ColorCycleBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.set_clips_color_cycle(body.clip_ids, track_id=body.track_id)
    return {**r, "timeline": ed.timeline_view()}


@app.get("/api/duration_report")
def duration_report_api() -> dict[str, Any]:
    return _ed().duration_report()


@app.post("/api/clip/copy_attributes")
def clip_copy_attributes(body: AttrClipBody) -> dict[str, Any]:
    return _ed().copy_attributes(body.clip_id)


@app.post("/api/clip/paste_attributes")
def clip_paste_attributes(body: PasteAttrBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.paste_attributes(
        body.clip_id,
        speed=body.speed,
        position=body.position,
        gain=body.gain,
        opacity=body.opacity,
        fades=body.fades,
    )
    return {**r, "timeline": ed.timeline_view()}


class ClipsAtBody(BaseModel):
    timeline_frame: int
    track_id: str | None = None
    kind: str | None = None


class MatchFrameBody(BaseModel):
    timeline_frame: int | None = None
    clip_id: str | None = None


class FadesBody(BaseModel):
    clip_id: str
    fade_in_frames: int = 0
    fade_out_frames: int = 0


class RelinkBody(BaseModel):
    clip_id: str
    media_id: str
    keep_source_range: bool = True


class DetachAudioBody(BaseModel):
    clip_id: str
    audio_track_id: str | None = None
    audio_start_offset_frames: int = 0
    link: bool = True


@app.post("/api/clips/at")
def clips_at_api(body: ClipsAtBody) -> dict[str, Any]:
    return _ed().clips_at(
        body.timeline_frame, track_id=body.track_id, kind=body.kind,
    )


@app.post("/api/clip/match_frame")
def match_frame_api(body: MatchFrameBody) -> dict[str, Any]:
    return _ed().match_frame(
        timeline_frame=body.timeline_frame, clip_id=body.clip_id,
    )


@app.post("/api/clip/fades")
def clip_fades_set(body: FadesBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.set_clip_fades(
        body.clip_id,
        fade_in_frames=body.fade_in_frames,
        fade_out_frames=body.fade_out_frames,
    )
    return {**r, "timeline": ed.timeline_view()}


@app.get("/api/clip/fades/{clip_id}")
def clip_fades_get(clip_id: str) -> dict[str, Any]:
    return _ed().get_clip_fades(clip_id)


@app.post("/api/clip/relink")
def clip_relink(body: RelinkBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.relink_clip(
        body.clip_id, body.media_id, keep_source_range=body.keep_source_range,
    )
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/clip/detach_audio")
def clip_detach_audio(body: DetachAudioBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.detach_audio(
        body.clip_id,
        body.audio_track_id,
        audio_start_offset_frames=body.audio_start_offset_frames,
        link=body.link,
    )
    return {**r, "timeline": ed.timeline_view()}


class OpacityBody(BaseModel):
    clip_id: str
    amount: float = 1.0


class SubclipBody(BaseModel):
    clip_id: str
    timeline_start: int | None = None
    timeline_end: int | None = None
    use_work_area: bool = False
    place: str = "after"
    name: str | None = None


@app.post("/api/clip/opacity")
def clip_opacity(body: OpacityBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.set_clip_opacity(body.clip_id, body.amount)
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/clip/subclip")
def clip_subclip(body: SubclipBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.make_subclip(
        body.clip_id,
        timeline_start=body.timeline_start,
        timeline_end=body.timeline_end,
        use_work_area=body.use_work_area,
        place=body.place,
        name=body.name,
    )
    out: dict[str, Any] = {**r}
    if r.get("placed"):
        out["timeline"] = ed.timeline_view()
    return out


class TrimPlayheadBody(BaseModel):
    clip_id: str
    playhead_frame: int
    edge: str = "head"
    mode: str = "ripple"
    follow_links: bool = True


class ClearEffectsBody(BaseModel):
    clip_id: str
    types: list[str] | None = None


class ExportPresetBody(BaseModel):
    output_path: str
    preset: str = "streaming"
    prepare: bool | None = None


@app.post("/api/clip/trim_playhead")
def clip_trim_playhead(body: TrimPlayheadBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.trim_to_playhead(
        body.clip_id,
        body.playhead_frame,
        edge=body.edge,
        mode=body.mode,
        follow_links=body.follow_links,
    )
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/clip/clear_effects")
def clip_clear_effects(body: ClearEffectsBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.clear_clip_effects(body.clip_id, types=body.types)
    return {**r, "timeline": ed.timeline_view()}


@app.get("/api/clip/effects/{clip_id}")
def clip_list_effects(clip_id: str) -> dict[str, Any]:
    return _ed().list_clip_effects(clip_id)


@app.get("/api/export/presets")
def export_presets_api() -> dict[str, Any]:
    return _ed().list_export_presets()


@app.post("/api/export/preset")
def export_with_preset_api(body: ExportPresetBody) -> dict[str, Any]:
    return _ed().export_with_preset(
        body.output_path, preset=body.preset, prepare=body.prepare,
    )


@app.get("/api/history")
def history_api() -> dict[str, Any]:
    return _ed().history_status()


@app.get("/api/style_assets")
def style_assets_api() -> dict[str, Any]:
    if _editor is None:
        from ..render.style_presets import list_style_assets
        return list_style_assets()
    return _ed().list_style_assets()


@app.post("/api/undo")
def undo() -> dict[str, Any]:
    ok = _ed().undo()
    return {"ok": ok, "timeline": _ed().timeline_view() if ok else None}


@app.post("/api/redo")
def redo() -> dict[str, Any]:
    ok = _ed().redo()
    return {"ok": ok, "timeline": _ed().timeline_view() if ok else None}


@app.post("/api/plan_edit")
def plan_edit_api(body: PlanEditBody) -> dict[str, Any]:
    ed = _ed()
    if not body.paths:
        raise HTTPException(400, "paths required")
    plan = ed.plan_edit(
        paths=body.paths,
        b_roll_mode=body.b_roll_mode,
        j_cut_seconds=body.j_cut_seconds,
    )
    result: dict[str, Any] = {"plan": plan}
    if body.apply:
        result["apply"] = ed.apply_edit_plan(plan)
        result["state"] = ed.describe()
    return result


@app.get("/api/workflow")
def film_workflow() -> dict[str, Any]:
    from ..workflow import get_workflow
    return get_workflow()


@app.post("/api/brief")
def make_brief(body: BriefBody) -> dict[str, Any]:
    from ..workflow import make_brief, plan_session
    brief = make_brief(
        intent=body.intent,
        assets=body.assets,
        constraints=body.constraints,
        deliverable=body.deliverable,
    )
    plan = plan_session(brief)
    return {"brief": brief, "plan": plan}


@app.post("/api/save")
def save_project() -> dict[str, bool]:
    _ed().save()
    return {"saved": True}


@app.post("/api/preview/build")
def preview_build(body: PreviewBody) -> dict[str, Any]:
    ed = _ed()
    return ed.export_preview(
        body.output_path,
        height=body.height,
        fps=body.fps,
        force=body.force,
    )


@app.post("/api/preview/ensure")
def preview_ensure(body: PreviewBody) -> dict[str, Any]:
    return _ed().ensure_preview_proxy(
        body.output_path, height=body.height, fps=body.fps,
    )


@app.get("/api/preview/status")
def preview_status() -> dict[str, Any]:
    return _ed().preview_proxy_status()


@app.get("/api/preview/proxy.mp4")
def preview_proxy_mp4() -> FileResponse:
    """Stream the timeline scrub proxy for HTML5 <video> playback."""
    ed = _ed()
    st = ed.preview_proxy_status()
    path = st.get("path")
    if not path or not Path(path).exists():
        raise HTTPException(
            404,
            "no preview proxy — POST /api/preview/ensure first",
        )
    # Allow browsers to re-fetch after rebuild via query cache bust on client
    return FileResponse(
        path,
        media_type="video/mp4",
        filename="preview_proxy.mp4",
    )


@app.get("/api/preview/interactive")
def preview_interactive() -> dict[str, Any]:
    """Path-C engine status (libopenshot when OpenShot installed)."""
    return _ed().preview_engine_status()


@app.get("/api/preview/openshot_plan")
def preview_openshot_plan(
    height: int = 360, include_audio: bool = False
) -> dict[str, Any]:
    return _ed().openshot_plan(height=height, include_audio=include_audio)


@app.get("/api/preview/openshot_effects")
def preview_openshot_effects() -> dict[str, Any]:
    """Path-C effect catalog: what adapter maps vs intentionally skips."""
    from opmiere.render.openshot_map import path_c_effect_catalog

    return path_c_effect_catalog()


@app.get("/api/clip/{clip_id}/path_c")
def clip_path_c(clip_id: str) -> dict[str, Any]:
    """Per-clip path-C support for current effect stack (agents + desktop)."""
    from opmiere.render.openshot_map import clip_path_c_support

    ed = _ed()
    clip = ed._find_clip(clip_id)  # noqa: SLF001 — same pattern as other clip GETs
    return clip_path_c_support(clip)


@app.get("/api/project/path_c")
def project_path_c() -> dict[str, Any]:
    """Project-wide path-C readiness report (which clips skip still-preview FX)."""
    from opmiere.render.openshot_map import project_path_c_report

    return project_path_c_report(_ed().project)


@app.post("/api/preview/openshot_frame")
def preview_openshot_frame(body: OpenShotFrameBody) -> dict[str, Any]:
    """Path-C multi-clip frame via OpenShot sidecar."""
    global _last_frame
    ed = _ed()
    out = ed.bundle.root / "review" / "openshot_frame.png"
    result = ed.openshot_frame_at(
        body.time_seconds,
        out,
        height=body.height,
        use_timeline=body.use_timeline,
    )
    if result.get("path"):
        _last_frame = result["path"]
    return result


@app.post("/api/preview/frame")
def preview_frame(body: FrameBody) -> dict[str, Any]:
    global _last_frame
    ed = _ed()
    engine = (body.engine or "auto").lower()
    if engine in ("openshot", "auto"):
        out = ed.bundle.root / "review" / "program_frame.png"
        if engine == "openshot":
            result = ed.openshot_frame_at(body.time_seconds, out, height=max(72, body.width * 9 // 16))
            if result.get("ok") and result.get("path"):
                _last_frame = result["path"]
                return result
            if engine == "openshot":
                return result
        # auto: try openshot then fall through
        try:
            result = ed.openshot_frame_at(
                body.time_seconds, out, height=max(72, int(body.width * 9 / 16)),
            )
            if result.get("ok") and result.get("path"):
                _last_frame = result["path"]
                return result
        except Exception:
            pass
    out = ed.bundle.root / "review" / f"frame_{body.time_seconds:.2f}.jpg"
    prefer = body.prefer_proxy if engine != "base" else False
    result = ed.frame_at(
        body.time_seconds,
        out,
        width=body.width,
        prefer_proxy=prefer,
    )
    _last_frame = result.get("path")
    return result


@app.get("/api/preview/frame.jpg")
def preview_frame_jpg(
    t: float = 0.0,
    width: int = 640,
    engine: str = "auto",
) -> FileResponse:
    """GET convenience for <img src> scrubbing.

    engine=auto tries OpenShot then proxy/base; openshot|proxy|base force path.
    """
    global _last_frame
    ed = _ed()
    eng = (engine or "auto").lower()
    out_png = ed.bundle.root / "review" / "program_scrub.png"
    out_jpg = ed.bundle.root / "review" / "scrub_frame.jpg"
    path: str | None = None
    if eng in ("openshot", "auto"):
        try:
            r = ed.openshot_frame_at(t, out_png, height=max(72, int(width * 9 / 16)))
            if r.get("ok") and r.get("path") and Path(str(r["path"])).exists():
                path = str(r["path"])
        except Exception:
            path = None
        if eng == "openshot" and not path:
            raise HTTPException(503, "openshot frame failed — is OpenShot installed?")
    if path is None:
        prefer = eng != "base"
        result = ed.frame_at(t, out_jpg, width=width, prefer_proxy=prefer)
        path = result.get("path")
    _last_frame = path
    if not path or not Path(path).exists():
        raise HTTPException(500, "frame extract failed")
    media = "image/png" if path.lower().endswith(".png") else "image/jpeg"
    return FileResponse(path, media_type=media)


@app.post("/api/preview/keyframes")
def preview_keyframes(count: int = 5, width: int = 480) -> dict[str, Any]:
    ed = _ed()
    out = ed.bundle.root / "review" / "keyframes"
    return ed.review_keyframes(out, count=count, width=width, ensure_proxy=True)


# --- Generation (ComfyUI) — dual surface with MCP generate / job_status ---


class GenerateBody(BaseModel):
    kind: str = "image"
    prompt: str
    params: dict[str, Any] = Field(default_factory=dict)


class JobStatusBody(BaseModel):
    job_id: str


class PlaceGeneratedBody(BaseModel):
    job_id: str
    track_id: str | None = None
    start: int | None = None
    duration_frames: int | None = None


class QualityCheckBody(BaseModel):
    path: str


def _job_to_dict(job: Any) -> dict[str, Any]:
    status = job.status.value if hasattr(job.status, "value") else str(job.status)
    out: dict[str, Any] = {
        "job_id": job.id,
        "status": status,
        "kind": job.kind,
        "prompt": job.prompt,
        "result_path": str(job.result_path) if job.result_path else None,
        "error": job.error,
    }
    if job.license is not None:
        out["license"] = (
            job.license.to_dict()
            if hasattr(job.license, "to_dict")
            else job.license
        )
    return out


@app.post("/api/generate")
def generate_api(body: GenerateBody) -> dict[str, Any]:
    """Submit async generation (ComfyUI). Poll GET /api/generate/job/{id}."""
    ed = _ed()
    prompt = (body.prompt or "").strip()
    if not prompt:
        raise HTTPException(400, "prompt required")
    kind = (body.kind or "image").strip().lower()
    try:
        job_id = ed.generate(kind, prompt, body.params or {})
    except Exception as e:
        raise HTTPException(503, f"generate failed: {e}") from e
    return {
        "job_id": job_id,
        "kind": kind,
        "prompt": prompt,
        "agent_note": "Poll GET /api/generate/job/{job_id} until status=done|error",
    }


@app.get("/api/generate/job/{job_id}")
def generate_job_get(job_id: str) -> dict[str, Any]:
    ed = _ed()
    try:
        job = ed.job_status(job_id)
    except Exception as e:
        raise HTTPException(404, f"job status failed: {e}") from e
    return _job_to_dict(job)


@app.post("/api/generate/status")
def generate_status_post(body: JobStatusBody) -> dict[str, Any]:
    """POST twin of GET job status (for agents that prefer JSON body)."""
    return generate_job_get(body.job_id)


@app.post("/api/place_generated")
def place_generated_api(body: PlaceGeneratedBody) -> dict[str, Any]:
    ed = _ed()
    track_id = body.track_id
    if not track_id:
        # default: first video track, else first track
        tracks = ed.project.tracks
        if not tracks:
            raise HTTPException(400, "no tracks — add a track first")
        vid = next((t for t in tracks if t.kind == "video"), None)
        track_id = (vid or tracks[0]).id
    start = body.start if body.start is not None else ed.duration_frames()
    try:
        clip = ed.place_generated(
            body.job_id,
            track_id,
            int(start),
            duration_frames=body.duration_frames,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        raise HTTPException(500, f"place_generated failed: {e}") from e
    return {
        "clip": clip.to_dict() if hasattr(clip, "to_dict") else {"id": clip.id},
        "timeline": ed.timeline_view(),
        "track_id": track_id,
        "start": start,
    }


@app.post("/api/quality_check")
def quality_check_api(body: QualityCheckBody) -> dict[str, Any]:
    if not body.path or not str(body.path).strip():
        raise HTTPException(400, "path required")
    try:
        return _ed().quality_check(body.path)
    except Exception as e:
        raise HTTPException(400, f"quality_check failed: {e}") from e


@app.get("/api/license_report")
def license_report_api() -> dict[str, Any]:
    return _ed().get_license_report()


# --- Agent session / pro analysis / interchange (0.4.61+) ---


class AgentFinishBody(BaseModel):
    export_path: str | None = None
    prepare: bool = True
    ensure_proxy: bool = True
    run_review: bool = True
    normalize_preset: str | None = None
    delivery_preset: str = "streaming"
    run_delivery_check: bool = True


class AnalyzeTimelineBody(BaseModel):
    silence_threshold_db: float = -40.0
    min_silence_seconds: float = 0.5


class AnalyzeAudioBody(BaseModel):
    path: str
    silence_threshold_db: float = -40.0
    min_silence_seconds: float = 0.5


class SilenceCutsBody(BaseModel):
    path: str
    silence_threshold_db: float = -40.0
    min_silence_seconds: float = 0.4
    pad_seconds: float = 0.08
    min_keep_seconds: float = 0.2


class DetectScenesBody(BaseModel):
    path: str
    threshold: float = 27.0
    min_scene_len: int = 15
    backend: str = "auto"


class InterchangeExportBody(BaseModel):
    path: str | None = None
    title: str | None = None


class ImportOtioBody(BaseModel):
    path: str | None = None
    text: str | None = None
    clear_tracks: bool = False
    import_missing_media: bool = True
    conform: bool = True


class ImportFcpxmlBody(BaseModel):
    path: str | None = None
    text: str | None = None
    clear_track: bool = False
    import_missing_media: bool = True
    conform: bool = True


class ExportStillBody(BaseModel):
    output_path: str | None = None
    frame: int | None = None
    width: int = 1280


class ExportAudioBody(BaseModel):
    output_path: str | None = None
    start_frame: int | None = None
    end_frame: int | None = None


class DeleteTrackBody(BaseModel):
    track_id: str


class HardCutAllBody(BaseModel):
    track_id: str | None = None


class BatchRelinkBody(BaseModel):
    mapping: dict[str, str] = Field(default_factory=dict)
    keep_source_range: bool = True


class SplitAtBeatsBody(BaseModel):
    track_id: str
    media_id: str | None = None
    path: str | None = None
    max_splits: int = 64


class WriteSrtBody(BaseModel):
    path: str | None = None
    segments: list[dict[str, Any]] = Field(default_factory=list)
    from_markers: bool = False


class NormalizeFileBody(BaseModel):
    path: str
    output_path: str | None = None
    preset: str = "streaming"


def _desktop_export_dir() -> Path:
    import tempfile

    out_dir = Path(tempfile.gettempdir()) / "opmiere_desktop_export"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


@app.get("/api/agent/preflight")
def agent_preflight_api() -> dict[str, Any]:
    return _ed().agent_preflight()


@app.post("/api/agent/finish")
def agent_finish_api(body: AgentFinishBody) -> dict[str, Any]:
    ed = _ed()
    export_path = body.export_path
    if not export_path:
        export_path = str(_desktop_export_dir() / "agent_finish.mp4")
    try:
        return ed.agent_finish_session(
            export_path,
            prepare=body.prepare,
            ensure_proxy=body.ensure_proxy,
            run_review=body.run_review,
            normalize_preset=body.normalize_preset,
            delivery_preset=body.delivery_preset,
            run_delivery_check=body.run_delivery_check,
        )
    except Exception as e:
        raise HTTPException(500, f"agent_finish failed: {e}") from e


@app.post("/api/analyze/timeline")
def analyze_timeline_api(body: AnalyzeTimelineBody | None = None) -> dict[str, Any]:
    body = body or AnalyzeTimelineBody()
    try:
        return _ed().analyze_timeline(
            silence_threshold_db=body.silence_threshold_db,
            min_silence_seconds=body.min_silence_seconds,
        )
    except Exception as e:
        raise HTTPException(400, f"analyze_timeline failed: {e}") from e


@app.post("/api/analyze/audio")
def analyze_audio_api(body: AnalyzeAudioBody) -> dict[str, Any]:
    try:
        return _ed().analyze_audio(
            body.path,
            silence_threshold_db=body.silence_threshold_db,
            min_silence_seconds=body.min_silence_seconds,
        )
    except Exception as e:
        raise HTTPException(400, f"analyze_audio failed: {e}") from e


@app.post("/api/suggest/silence_cuts")
def silence_cuts_api(body: SilenceCutsBody) -> dict[str, Any]:
    try:
        return _ed().suggest_silence_cuts(
            body.path,
            silence_threshold_db=body.silence_threshold_db,
            min_silence_seconds=body.min_silence_seconds,
            pad_seconds=body.pad_seconds,
            min_keep_seconds=body.min_keep_seconds,
        )
    except Exception as e:
        raise HTTPException(400, f"silence_cuts failed: {e}") from e


@app.post("/api/detect/scenes")
def detect_scenes_api(body: DetectScenesBody) -> dict[str, Any]:
    try:
        return _ed().detect_scenes(
            body.path,
            threshold=body.threshold,
            min_scene_len=body.min_scene_len,
            backend=body.backend,
        )
    except Exception as e:
        raise HTTPException(400, f"detect_scenes failed: {e}") from e


@app.get("/api/interchange")
def interchange_catalog() -> dict[str, Any]:
    """Import/export format catalog for agents and desktop Pro panel."""
    return _ed().interchange_formats()


@app.post("/api/export/fcpxml")
def export_fcpxml_api(body: InterchangeExportBody | None = None) -> dict[str, Any]:
    body = body or InterchangeExportBody()
    ed = _ed()
    path = body.path or str(_desktop_export_dir() / "export.fcpxml")
    try:
        return ed.export_fcpxml(path, title=body.title)
    except Exception as e:
        raise HTTPException(500, f"export_fcpxml failed: {e}") from e


@app.post("/api/import/fcpxml")
def import_fcpxml_api(body: ImportFcpxmlBody) -> dict[str, Any]:
    """Import minimal FCPXML 1.9 (pair of export_fcpxml)."""
    ed = _ed()
    try:
        r = ed.import_fcpxml(
            body.path,
            text=body.text,
            clear_track=body.clear_track,
            import_missing_media=body.import_missing_media,
            conform=body.conform,
        )
        return {**r, "timeline": ed.timeline_view()}
    except Exception as e:
        raise HTTPException(400, f"import_fcpxml failed: {e}") from e


@app.post("/api/export/otio")
def export_otio_api(body: InterchangeExportBody | None = None) -> dict[str, Any]:
    body = body or InterchangeExportBody()
    ed = _ed()
    path = body.path or str(_desktop_export_dir() / "export.otio.json")
    try:
        return ed.export_otio_json(path, title=body.title)
    except Exception as e:
        raise HTTPException(500, f"export_otio failed: {e}") from e


class ExportManifestBody(BaseModel):
    path: str | None = None


@app.post("/api/export/manifest")
def export_manifest_api(body: ExportManifestBody | None = None) -> dict[str, Any]:
    """Export compact JSON edit manifest (tracks/clips/effects/markers)."""
    body = body or ExportManifestBody()
    ed = _ed()
    path = body.path or str(_desktop_export_dir() / "edit_manifest.json")
    try:
        return ed.export_edit_manifest(path)
    except Exception as e:
        raise HTTPException(500, f"export_manifest failed: {e}") from e


class ImportManifestBody(BaseModel):
    path: str | None = None
    text: str | None = None
    clear: bool = True
    import_missing_media: bool = True
    conform: bool = True


@app.post("/api/import/manifest")
def import_manifest_api(body: ImportManifestBody) -> dict[str, Any]:
    """Import edit manifest JSON (pair of export_manifest)."""
    ed = _ed()
    try:
        r = ed.import_edit_manifest(
            body.path,
            text=body.text,
            clear=body.clear,
            import_missing_media=body.import_missing_media,
            conform=body.conform,
        )
    except Exception as e:
        raise HTTPException(400, f"import_manifest failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class EnsureProxiesBody(BaseModel):
    height: int = 480
    force: bool = False
    kinds: list[str] | None = None


@app.post("/api/media/proxies_all")
def ensure_all_proxies_api(body: EnsureProxiesBody | None = None) -> dict[str, Any]:
    """Build proxies for all video media in the bin."""
    body = body or EnsureProxiesBody()
    ed = _ed()
    try:
        return ed.ensure_all_media_proxies(
            height=body.height, force=body.force, kinds=body.kinds,
        )
    except Exception as e:
        raise HTTPException(400, f"ensure_all_proxies failed: {e}") from e


class QuickAssemblyBody(BaseModel):
    media_paths: list[str]
    track_id: str | None = None
    rough_cut: bool = True
    title: str | None = None
    transition: str | None = "cross_dissolve"
    build_proxies: bool = False


@app.post("/api/edit/quick_assembly")
def quick_assembly_api(body: QuickAssemblyBody) -> dict[str, Any]:
    """Import paths → rough_cut → optional end title (agent bootstrap)."""
    ed = _ed()
    try:
        r = ed.agent_quick_assembly(
            body.media_paths,
            track_id=body.track_id,
            rough_cut=body.rough_cut,
            title=body.title,
            transition=body.transition,
            build_proxies=body.build_proxies,
        )
    except Exception as e:
        raise HTTPException(400, f"quick_assembly failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class RelinkOfflineBody(BaseModel):
    search_dirs: list[str]
    recursive: bool = True
    re_probe: bool = True


@app.post("/api/media/relink_offline")
def relink_offline_api(body: RelinkOfflineBody) -> dict[str, Any]:
    """Relink offline media by basename under search_dirs."""
    ed = _ed()
    try:
        r = ed.relink_offline_media(
            body.search_dirs,
            recursive=body.recursive,
            re_probe=body.re_probe,
        )
    except Exception as e:
        raise HTTPException(400, f"relink_offline failed: {e}") from e
    return r


class HandoffPackageBody(BaseModel):
    out_dir: str
    include_manifest: bool = True
    include_chapters: bool = True
    include_preflight: bool = True
    include_otio: bool = False
    include_media_status: bool = True


@app.post("/api/export/handoff")
def export_handoff_api(body: HandoffPackageBody) -> dict[str, Any]:
    """Write agent handoff package (manifest + chapters + preflight)."""
    ed = _ed()
    try:
        return ed.export_handoff_package(
            body.out_dir,
            include_manifest=body.include_manifest,
            include_chapters=body.include_chapters,
            include_preflight=body.include_preflight,
            include_otio=body.include_otio,
            include_media_status=body.include_media_status,
        )
    except Exception as e:
        raise HTTPException(400, f"export_handoff failed: {e}") from e


class ReviewPackageBody(BaseModel):
    out_dir: str
    include_handoff: bool = True
    include_storyboard: bool = True
    include_social: bool = False
    social_variants: list[str] | None = None
    watermark: str | None = None


@app.post("/api/export/review_package")
def export_review_package_api(body: ReviewPackageBody) -> dict[str, Any]:
    """Handoff + storyboard (+ optional social) in one folder."""
    ed = _ed()
    try:
        return ed.export_review_package(
            body.out_dir,
            include_handoff=body.include_handoff,
            include_storyboard=body.include_storyboard,
            include_social=body.include_social,
            social_variants=body.social_variants,
            watermark=body.watermark,
        )
    except Exception as e:
        raise HTTPException(400, f"export_review_package failed: {e}") from e


class WatermarkTrackBody(BaseModel):
    track_id: str
    content: str = "© Opmiere"
    position: str = "bottom"
    size: int = 22
    alpha: float = 0.55
    color: str = "white"


@app.post("/api/track/watermark")
def watermark_track_api(body: WatermarkTrackBody) -> dict[str, Any]:
    """Apply watermark to every clip on a track."""
    ed = _ed()
    try:
        r = ed.apply_watermark_to_track(
            body.track_id,
            body.content,
            position=body.position,
            size=body.size,
            alpha=body.alpha,
            color=body.color,
        )
    except Exception as e:
        raise HTTPException(400, f"watermark_track failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class CollectBundleBody(BaseModel):
    dest_path: str
    used_only: bool = True
    conform: bool = True


@app.post("/api/export/collect_bundle")
def collect_bundle_api(body: CollectBundleBody) -> dict[str, Any]:
    """NLE Collect Files: new self-contained .opm with media re-imported."""
    ed = _ed()
    try:
        return ed.collect_to_bundle(
            body.dest_path,
            used_only=body.used_only,
            conform=body.conform,
        )
    except Exception as e:
        raise HTTPException(400, f"collect_bundle failed: {e}") from e


class FrameSequenceBody(BaseModel):
    out_dir: str
    start_frame: int | None = None
    end_frame: int | None = None
    use_work_area: bool = False
    pattern: str = "frame_%06d.png"
    max_frames: int | None = None
    height: int | None = None


@app.post("/api/export/frame_sequence")
def export_frame_sequence_api(body: FrameSequenceBody) -> dict[str, Any]:
    """Export timeline/range as image sequence (VFX handoff)."""
    ed = _ed()
    try:
        return ed.export_frame_sequence(
            body.out_dir,
            start_frame=body.start_frame,
            end_frame=body.end_frame,
            use_work_area=body.use_work_area,
            pattern=body.pattern,
            max_frames=body.max_frames,
            height=body.height,
        )
    except Exception as e:
        raise HTTPException(400, f"export_frame_sequence failed: {e}") from e


class StoryboardBody(BaseModel):
    out_dir: str
    include_markers: bool = True
    include_clip_mids: bool = True
    include_contact: bool = True
    include_chapters: bool = True
    width: int = 640
    max_stills: int = 64


@app.post("/api/export/storyboard")
def export_storyboard_api(body: StoryboardBody) -> dict[str, Any]:
    """Export review storyboard (stills + contact + chapters)."""
    ed = _ed()
    try:
        return ed.export_storyboard(
            body.out_dir,
            include_markers=body.include_markers,
            include_clip_mids=body.include_clip_mids,
            include_contact=body.include_contact,
            include_chapters=body.include_chapters,
            width=body.width,
            max_stills=body.max_stills,
        )
    except Exception as e:
        raise HTTPException(400, f"export_storyboard failed: {e}") from e


class ExportToSizeBody(BaseModel):
    path: str
    width: int
    height: int
    fit: str = "cover"
    normalize_preset: str | None = None


@app.post("/api/export/to_size")
def export_to_size_api(body: ExportToSizeBody) -> dict[str, Any]:
    """Export then scale to width×height (cover/contain/stretch)."""
    ed = _ed()
    try:
        return ed.export_to_size(
            body.path,
            body.width,
            body.height,
            fit=body.fit,
            normalize_preset=body.normalize_preset,
        )
    except Exception as e:
        raise HTTPException(400, f"export_to_size failed: {e}") from e


class ExportBurninsBody(BaseModel):
    path: str
    timecode: bool = True
    safe_area: bool = True
    watermark: str | None = None
    timecode_start: str = "00:00:00:00"
    normalize_preset: str | None = None


@app.post("/api/export/burnins")
def export_burnins_api(body: ExportBurninsBody) -> dict[str, Any]:
    """Export review master with TC/safe/watermark burn-ins (no timeline mutate)."""
    ed = _ed()
    try:
        return ed.export_with_burnins(
            body.path,
            timecode=body.timecode,
            safe_area=body.safe_area,
            watermark=body.watermark,
            timecode_start=body.timecode_start,
            normalize_preset=body.normalize_preset,
        )
    except Exception as e:
        raise HTTPException(400, f"export_burnins failed: {e}") from e


class RenameClipsBody(BaseModel):
    track_id: str
    pattern: str = "Shot {n:03d}"
    start: int = 1


@app.post("/api/track/rename_clips")
def rename_clips_api(body: RenameClipsBody) -> dict[str, Any]:
    """Sequential rename clips on a track."""
    ed = _ed()
    try:
        r = ed.rename_clips_sequential(
            body.track_id, pattern=body.pattern, start=body.start,
        )
    except Exception as e:
        raise HTTPException(400, f"rename_clips failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class SocialPackBody(BaseModel):
    out_dir: str
    variants: list[str] | None = None
    normalize_preset: str | None = None
    name_prefix: str = "export"


@app.post("/api/export/social_pack")
def export_social_pack_api(body: SocialPackBody) -> dict[str, Any]:
    """Export youtube/reels/square (etc.) from one timeline."""
    ed = _ed()
    try:
        return ed.export_social_pack(
            body.out_dir,
            variants=body.variants,
            normalize_preset=body.normalize_preset,
            name_prefix=body.name_prefix,
        )
    except Exception as e:
        raise HTTPException(400, f"export_social_pack failed: {e}") from e


class ReframeBody(BaseModel):
    clip_id: str
    aspect: str = "9:16"
    anchor: str = "center"


@app.post("/api/clip/reframe")
def reframe_clip_api(body: ReframeBody) -> dict[str, Any]:
    """Center-crop clip to aspect ratio."""
    ed = _ed()
    try:
        r = ed.reframe_clip(body.clip_id, body.aspect, anchor=body.anchor)
    except Exception as e:
        raise HTTPException(400, f"reframe failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class TimecodeBody(BaseModel):
    clip_id: str
    enabled: bool = True
    position: str = "bottom"
    size: int = 28
    start: str = "00:00:00:00"


@app.post("/api/clip/timecode")
def clip_timecode_api(body: TimecodeBody) -> dict[str, Any]:
    """Burn running timecode overlay on a clip."""
    ed = _ed()
    try:
        r = ed.set_clip_timecode(
            body.clip_id,
            enabled=body.enabled,
            position=body.position,
            size=body.size,
            start=body.start,
        )
    except Exception as e:
        raise HTTPException(400, f"timecode failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class MarkersFromClipsBody(BaseModel):
    track_id: str | None = None
    at: str = "start"
    prefix: str = ""
    clear_existing: bool = False
    color: str = "#7c9cff"


@app.post("/api/markers/from_clips")
def markers_from_clips_api(body: MarkersFromClipsBody | None = None) -> dict[str, Any]:
    """Create markers at each clip edge on a track."""
    body = body or MarkersFromClipsBody()
    ed = _ed()
    try:
        r = ed.markers_from_clips(
            body.track_id,
            at=body.at,
            prefix=body.prefix,
            clear_existing=body.clear_existing,
            color=body.color,
        )
    except Exception as e:
        raise HTTPException(400, f"markers_from_clips failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class WatermarkBody(BaseModel):
    clip_id: str
    content: str = "© Opmiere"
    position: str = "bottom"
    size: int = 22
    alpha: float = 0.55
    color: str = "white"
    enabled: bool = True


@app.post("/api/clip/watermark")
def clip_watermark_api(body: WatermarkBody) -> dict[str, Any]:
    """Set text watermark on a clip."""
    ed = _ed()
    try:
        r = ed.set_clip_watermark(
            body.clip_id,
            body.content,
            position=body.position,
            size=body.size,
            alpha=body.alpha,
            color=body.color,
            enabled=body.enabled,
        )
    except Exception as e:
        raise HTTPException(400, f"watermark failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class ListCutsBody(BaseModel):
    track_id: str | None = None
    kind: str | None = "video"


@app.get("/api/edit/cuts")
def list_cuts_api(track_id: str | None = None, kind: str | None = "video") -> dict[str, Any]:
    """List hard-cut edit points on track(s)."""
    return _ed().list_cuts(track_id, kind=kind)


@app.post("/api/edit/cuts")
def list_cuts_post_api(body: ListCutsBody | None = None) -> dict[str, Any]:
    body = body or ListCutsBody()
    return _ed().list_cuts(body.track_id, kind=body.kind)


class SafeAreaBody(BaseModel):
    clip_id: str
    enabled: bool = True
    action: float = 0.90
    title: float = 0.80
    thickness: int = 2


@app.post("/api/clip/safe_area")
def clip_safe_area_api(body: SafeAreaBody) -> dict[str, Any]:
    """Burn action/title safe rectangles on a clip."""
    ed = _ed()
    try:
        r = ed.set_clip_safe_area(
            body.clip_id,
            enabled=body.enabled,
            action=body.action,
            title=body.title,
            thickness=body.thickness,
        )
    except Exception as e:
        raise HTTPException(400, f"safe_area failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class SafeAreaTrackBody(BaseModel):
    track_id: str
    action: float = 0.90
    title: float = 0.80
    thickness: int = 2


@app.post("/api/track/safe_area")
def track_safe_area_api(body: SafeAreaTrackBody) -> dict[str, Any]:
    """Apply safe_area to every clip on a track."""
    ed = _ed()
    try:
        r = ed.apply_safe_area_to_track(
            body.track_id,
            action=body.action,
            title=body.title,
            thickness=body.thickness,
        )
    except Exception as e:
        raise HTTPException(400, f"safe_area track failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class ExportCutsReportBody(BaseModel):
    path: str | None = None
    track_id: str | None = None
    kind: str | None = "video"
    format: str = "json"


@app.post("/api/export/cuts_report")
def export_cuts_report_api(body: ExportCutsReportBody | None = None) -> dict[str, Any]:
    """Export cut list as JSON/CSV."""
    body = body or ExportCutsReportBody()
    ed = _ed()
    try:
        return ed.export_cuts_report(
            body.path,
            track_id=body.track_id,
            kind=body.kind,
            format=body.format,
        )
    except Exception as e:
        raise HTTPException(400, f"export_cuts_report failed: {e}") from e


class FindClipsBody(BaseModel):
    name_contains: str | None = None
    media_id: str | None = None
    color: str | None = None
    track_id: str | None = None
    kind: str | None = None
    has_effect: str | None = None
    muted: bool | None = None


@app.post("/api/clips/find")
def find_clips_api(body: FindClipsBody | None = None) -> dict[str, Any]:
    """Search clips by name/media/color/effect."""
    body = body or FindClipsBody()
    return _ed().find_clips(
        name_contains=body.name_contains,
        media_id=body.media_id,
        color=body.color,
        track_id=body.track_id,
        kind=body.kind,
        has_effect=body.has_effect,
        muted=body.muted,
    )


class IsolateClipsBody(BaseModel):
    clip_ids: list[str]
    track_id: str | None = None
    follow_links: bool = True


@app.post("/api/clips/isolate")
def isolate_clips_api(body: IsolateClipsBody) -> dict[str, Any]:
    """Unmute selection; mute all other clips."""
    ed = _ed()
    try:
        r = ed.isolate_clips(
            body.clip_ids,
            track_id=body.track_id,
            follow_links=body.follow_links,
        )
    except Exception as e:
        raise HTTPException(400, f"isolate_clips failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class CrossfadesBody(BaseModel):
    track_id: str
    duration_frames: int = 12
    transition_type: str = "cross_dissolve"
    max_count: int | None = None


@app.post("/api/track/crossfades")
def crossfades_api(body: CrossfadesBody) -> dict[str, Any]:
    """Apply crossfades on every hard cut of a track."""
    ed = _ed()
    try:
        r = ed.apply_crossfades_on_track(
            body.track_id,
            duration_frames=body.duration_frames,
            transition_type=body.transition_type,
            max_count=body.max_count,
        )
    except Exception as e:
        raise HTTPException(400, f"crossfades failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class MarkersFromCutsBody(BaseModel):
    track_id: str | None = None
    prefix: str = "Cut "
    clear_existing: bool = False
    color: str = "#ff9f43"


@app.post("/api/markers/from_hard_cuts")
def markers_from_hard_cuts_api(body: MarkersFromCutsBody | None = None) -> dict[str, Any]:
    """Markers at each hard cut."""
    body = body or MarkersFromCutsBody()
    ed = _ed()
    try:
        r = ed.markers_from_hard_cuts(
            body.track_id,
            prefix=body.prefix,
            clear_existing=body.clear_existing,
            color=body.color,
        )
    except Exception as e:
        raise HTTPException(400, f"markers_from_hard_cuts failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class ProjectResolutionBody(BaseModel):
    width: int
    height: int


@app.post("/api/project/resolution")
def project_resolution_api(body: ProjectResolutionBody) -> dict[str, Any]:
    """Change project canvas resolution."""
    ed = _ed()
    try:
        r = ed.set_project_resolution(body.width, body.height)
    except Exception as e:
        raise HTTPException(400, f"set_project_resolution failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class BlackdetectBody(BaseModel):
    media_id: str | None = None
    path: str | None = None
    clip_id: str | None = None
    pic_th: float = 0.98
    pix_th: float = 0.10
    min_duration: float = 0.15
    prefix: str = "Black "
    clear_existing: bool = False
    color: str = "#111111"
    max_markers: int = 64


@app.post("/api/markers/from_blackdetect")
def markers_from_blackdetect_api(body: BlackdetectBody) -> dict[str, Any]:
    """Detect black segments; mark starts."""
    ed = _ed()
    try:
        r = ed.markers_from_blackdetect(
            body.media_id,
            path=body.path,
            clip_id=body.clip_id,
            pic_th=body.pic_th,
            pix_th=body.pix_th,
            min_duration=body.min_duration,
            prefix=body.prefix,
            clear_existing=body.clear_existing,
            color=body.color,
            max_markers=body.max_markers,
        )
    except Exception as e:
        raise HTTPException(400, f"blackdetect failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class SilencedetectBody(BaseModel):
    media_id: str | None = None
    path: str | None = None
    clip_id: str | None = None
    noise_db: float = -30.0
    min_duration: float = 0.25
    mark: str = "start"
    prefix: str = "Silence "
    clear_existing: bool = False
    color: str = "#5c7cfa"
    max_markers: int = 80


@app.post("/api/markers/from_silencedetect")
def markers_from_silencedetect_api(body: SilencedetectBody) -> dict[str, Any]:
    """Detect silence; mark starts/ends."""
    ed = _ed()
    try:
        r = ed.markers_from_silencedetect(
            body.media_id,
            path=body.path,
            clip_id=body.clip_id,
            noise_db=body.noise_db,
            min_duration=body.min_duration,
            mark=body.mark,
            prefix=body.prefix,
            clear_existing=body.clear_existing,
            color=body.color,
            max_markers=body.max_markers,
        )
    except Exception as e:
        raise HTTPException(400, f"silencedetect failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class SplitAtSilencesBody(BaseModel):
    clip_id: str
    noise_db: float = -30.0
    min_duration: float = 0.25
    max_splits: int = 40
    mark: str = "start"


@app.post("/api/edit/split_at_silences")
def split_at_silences_api(body: SplitAtSilencesBody) -> dict[str, Any]:
    """Razor clip at silence edges."""
    ed = _ed()
    try:
        r = ed.split_at_silences(
            body.clip_id,
            noise_db=body.noise_db,
            min_duration=body.min_duration,
            max_splits=body.max_splits,
            mark=body.mark,
        )
    except Exception as e:
        raise HTTPException(400, f"split_at_silences failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class TightenSilencesBody(BaseModel):
    clip_id: str
    noise_db: float = -30.0
    min_duration: float = 0.35
    pad_frames: int = 4
    max_ranges: int = 40


@app.post("/api/edit/tighten_silences")
def tighten_silences_api(body: TightenSilencesBody) -> dict[str, Any]:
    """Ripple-remove interior silence ranges (dialogue tighten)."""
    ed = _ed()
    try:
        r = ed.tighten_silences(
            body.clip_id,
            noise_db=body.noise_db,
            min_duration=body.min_duration,
            pad_frames=body.pad_frames,
            max_ranges=body.max_ranges,
        )
    except Exception as e:
        raise HTTPException(400, f"tighten_silences failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class ProjectFpsBody(BaseModel):
    fps: float


@app.post("/api/project/fps")
def project_fps_api(body: ProjectFpsBody) -> dict[str, Any]:
    """Change project timebase fps."""
    ed = _ed()
    try:
        r = ed.set_project_fps(body.fps)
    except Exception as e:
        raise HTTPException(400, f"set_project_fps failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class GainTrackBody(BaseModel):
    track_id: str
    db: float


@app.post("/api/track/gain")
def track_gain_api(body: GainTrackBody) -> dict[str, Any]:
    """Set gain on every clip of a track."""
    ed = _ed()
    try:
        r = ed.apply_gain_to_track(body.track_id, body.db)
    except Exception as e:
        raise HTTPException(400, f"track_gain failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class NoiseReductionTrackBody(BaseModel):
    track_id: str
    amount: float = 12.0


@app.post("/api/track/noise_reduction")
def track_nr_api(body: NoiseReductionTrackBody) -> dict[str, Any]:
    """Apply noise_reduction to every clip on a track."""
    ed = _ed()
    try:
        r = ed.apply_noise_reduction_to_track(body.track_id, body.amount)
    except Exception as e:
        raise HTTPException(400, f"noise_reduction track failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class SilenceRangesBody(BaseModel):
    media_id: str | None = None
    path: str | None = None
    clip_id: str | None = None
    noise_db: float = -30.0
    min_duration: float = 0.25
    pad_frames: int = 0
    max_ranges: int = 80


@app.post("/api/analyze/silence_ranges")
def silence_ranges_api(body: SilenceRangesBody) -> dict[str, Any]:
    """Read-only silence range map (dry-run for tighten)."""
    ed = _ed()
    try:
        return ed.list_silence_ranges(
            body.media_id,
            path=body.path,
            clip_id=body.clip_id,
            noise_db=body.noise_db,
            min_duration=body.min_duration,
            pad_frames=body.pad_frames,
            max_ranges=body.max_ranges,
        )
    except Exception as e:
        raise HTTPException(400, f"silence_ranges failed: {e}") from e


class ProjectSnapshotBody(BaseModel):
    path: str
    include_media_status: bool = True
    include_preflight: bool = True
    include_cuts: bool = True


@app.post("/api/export/project_snapshot")
def project_snapshot_api(body: ProjectSnapshotBody) -> dict[str, Any]:
    """Write project snapshot JSON (no media files)."""
    ed = _ed()
    try:
        return ed.export_project_snapshot(
            body.path,
            include_media_status=body.include_media_status,
            include_preflight=body.include_preflight,
            include_cuts=body.include_cuts,
        )
    except Exception as e:
        raise HTTPException(400, f"project_snapshot failed: {e}") from e


class PresetsPackBody(BaseModel):
    out_dir: str
    presets: list[str] | None = None
    name_prefix: str = "export"
    prepare: bool | None = None


@app.post("/api/export/presets_pack")
def export_presets_pack_api(body: PresetsPackBody) -> dict[str, Any]:
    """Export multiple named presets into a folder."""
    ed = _ed()
    try:
        return ed.export_presets_pack(
            body.out_dir,
            presets=body.presets,
            name_prefix=body.name_prefix,
            prepare=body.prepare,
        )
    except Exception as e:
        raise HTTPException(400, f"presets_pack failed: {e}") from e


class MatchDurationBody(BaseModel):
    clip_id: str
    target_clip_id: str | None = None
    target_frames: int | None = None
    clamp: bool = True


@app.post("/api/clip/match_duration")
def match_duration_api(body: MatchDurationBody) -> dict[str, Any]:
    """Rate-stretch clip to match another clip or frame count."""
    ed = _ed()
    try:
        r = ed.match_clip_duration(
            body.clip_id,
            target_clip_id=body.target_clip_id,
            target_frames=body.target_frames,
            clamp=body.clamp,
        )
    except Exception as e:
        raise HTTPException(400, f"match_duration failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class PipCornerBody(BaseModel):
    clip_id: str
    corner: str = "bottom_right"
    scale: float = 0.28


@app.post("/api/clip/pip_corner")
def pip_corner_api(body: PipCornerBody) -> dict[str, Any]:
    """Set PiP corner position on overlay clip."""
    ed = _ed()
    try:
        r = ed.set_pip_corner(body.clip_id, body.corner, scale=body.scale)
    except Exception as e:
        raise HTTPException(400, f"pip_corner failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class PlacePipBody(BaseModel):
    media_id: str
    corner: str = "bottom_right"
    scale: float = 0.28
    start: int | None = None
    duration_frames: int | None = None
    track_id: str | None = None
    name: str | None = None


@app.post("/api/edit/place_pip")
def place_pip_api(body: PlacePipBody) -> dict[str, Any]:
    """Place media as picture-in-picture overlay."""
    ed = _ed()
    try:
        r = ed.place_pip(
            body.media_id,
            corner=body.corner,
            scale=body.scale,
            start=body.start,
            duration_frames=body.duration_frames,
            track_id=body.track_id,
            name=body.name,
        )
    except Exception as e:
        raise HTTPException(400, f"place_pip failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class LowerThirdBody(BaseModel):
    content: str
    start_frame: int | None = None
    duration_frames: int = 90
    track_id: str | None = None
    size: int = 42
    color: str = "#ffd60a"


@app.post("/api/edit/lower_third")
def lower_third_api(body: LowerThirdBody) -> dict[str, Any]:
    """Add lower-third title card."""
    ed = _ed()
    try:
        r = ed.add_lower_third(
            body.content,
            start_frame=body.start_frame,
            duration_frames=body.duration_frames,
            track_id=body.track_id,
            size=body.size,
            color=body.color,
        )
    except Exception as e:
        raise HTTPException(400, f"lower_third failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class EndCardBody(BaseModel):
    content: str = "Thanks for watching"
    duration_frames: int = 90
    track_id: str | None = None
    size: int = 56
    fade_in_frames: int = 12


@app.post("/api/edit/end_card")
def end_card_api(body: EndCardBody) -> dict[str, Any]:
    """Append end-card title after sequence end."""
    ed = _ed()
    try:
        r = ed.add_end_card(
            body.content,
            duration_frames=body.duration_frames,
            track_id=body.track_id,
            size=body.size,
            fade_in_frames=body.fade_in_frames,
        )
    except Exception as e:
        raise HTTPException(400, f"end_card failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class SplitScreenBody(BaseModel):
    media_left_id: str
    media_right_id: str
    start: int = 0
    duration_frames: int | None = None
    orientation: str = "lr"


@app.post("/api/edit/split_screen")
def split_screen_api(body: SplitScreenBody) -> dict[str, Any]:
    """Place two media as left-right or top-bottom split-screen."""
    ed = _ed()
    try:
        r = ed.place_split_screen(
            body.media_left_id,
            body.media_right_id,
            start=body.start,
            duration_frames=body.duration_frames,
            orientation=body.orientation,
        )
    except Exception as e:
        raise HTTPException(400, f"split_screen failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class IntroCardBody(BaseModel):
    content: str = "Title"
    duration_frames: int = 90
    track_id: str | None = None
    size: int = 56
    fade_out_frames: int = 12
    ripple_all_tracks: bool = True


@app.post("/api/edit/intro_card")
def intro_card_api(body: IntroCardBody) -> dict[str, Any]:
    """Prepend intro title card at frame 0 (ripple optional)."""
    ed = _ed()
    try:
        r = ed.add_intro_card(
            body.content,
            duration_frames=body.duration_frames,
            track_id=body.track_id,
            size=body.size,
            fade_out_frames=body.fade_out_frames,
            ripple_all_tracks=body.ripple_all_tracks,
        )
    except Exception as e:
        raise HTTPException(400, f"intro_card failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class QuadScreenBody(BaseModel):
    media_ids: list[str]
    start: int = 0
    duration_frames: int | None = None


@app.post("/api/edit/quad_screen")
def quad_screen_api(body: QuadScreenBody) -> dict[str, Any]:
    """Place four media in a 2×2 grid."""
    ed = _ed()
    try:
        r = ed.place_quad_screen(
            body.media_ids,
            start=body.start,
            duration_frames=body.duration_frames,
        )
    except Exception as e:
        raise HTTPException(400, f"quad_screen failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class ReplaceMediaEverywhereBody(BaseModel):
    old_media_id: str
    new_media_id: str
    keep_source_range: bool = True
    track_id: str | None = None


@app.post("/api/media/replace_everywhere")
def replace_media_everywhere_api(body: ReplaceMediaEverywhereBody) -> dict[str, Any]:
    """Retarget all clips using old media → new media."""
    ed = _ed()
    try:
        r = ed.replace_media_everywhere(
            body.old_media_id,
            body.new_media_id,
            keep_source_range=body.keep_source_range,
            track_id=body.track_id,
        )
    except Exception as e:
        raise HTTPException(400, f"replace_everywhere failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class ImportImageSequenceBody(BaseModel):
    path: str
    fps: float | None = None
    glob: str = "*"
    start_number: int | None = None
    max_frames: int | None = None
    place_track_id: str | None = None
    start: int = 0
    build_proxy: bool = False


@app.post("/api/import/image_sequence")
def import_image_sequence_api(body: ImportImageSequenceBody) -> dict[str, Any]:
    """Encode still sequence to video and import (optional place)."""
    ed = _ed()
    try:
        r = ed.import_image_sequence(
            body.path,
            fps=body.fps,
            glob=body.glob,
            start_number=body.start_number,
            max_frames=body.max_frames,
            place_track_id=body.place_track_id,
            start=body.start,
            build_proxy=body.build_proxy,
        )
    except Exception as e:
        raise HTTPException(400, f"import_image_sequence failed: {e}") from e
    out = {**r}
    if r.get("clip_id"):
        out["timeline"] = ed.timeline_view()
    return out


class ImportFolderBody(BaseModel):
    folder: str
    recursive: bool = False
    kinds: list[str] | None = None
    place: bool = False
    track_id: str | None = None
    rough_cut: bool = False
    transition: str | None = "cross_dissolve"
    max_files: int = 200
    conform: bool = True


@app.post("/api/import/folder")
def import_folder_api(body: ImportFolderBody) -> dict[str, Any]:
    """Import all media from a folder; optional place / rough_cut."""
    ed = _ed()
    try:
        r = ed.import_folder(
            body.folder,
            recursive=body.recursive,
            kinds=body.kinds,
            place=body.place,
            track_id=body.track_id,
            rough_cut=body.rough_cut,
            transition=body.transition,
            max_files=body.max_files,
            conform=body.conform,
        )
    except Exception as e:
        raise HTTPException(400, f"import_folder failed: {e}") from e
    out = {**r, "timeline": ed.timeline_view()}
    return out


class DetachAudioAllBody(BaseModel):
    track_id: str | None = None
    audio_track_id: str | None = None
    audio_start_offset_frames: int = 0
    link: bool = True
    only_with_audio: bool = True


@app.post("/api/edit/detach_audio_all")
def detach_audio_all_api(body: DetachAudioAllBody | None = None) -> dict[str, Any]:
    """Detach audio for all video clips on a track (or all video tracks)."""
    body = body or DetachAudioAllBody()
    ed = _ed()
    try:
        r = ed.detach_audio_all(
            body.track_id,
            audio_track_id=body.audio_track_id,
            audio_start_offset_frames=body.audio_start_offset_frames,
            link=body.link,
            only_with_audio=body.only_with_audio,
        )
    except Exception as e:
        raise HTTPException(400, f"detach_audio_all failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class JLOffsetBody(BaseModel):
    video_clip_id: str
    offset_frames: int
    relative: bool = False


@app.post("/api/edit/j_l_offset")
def j_l_offset_api(body: JLOffsetBody) -> dict[str, Any]:
    """Shift linked audio for J/L cut (negative = J lead)."""
    ed = _ed()
    try:
        r = ed.set_j_l_offset(
            body.video_clip_id,
            body.offset_frames,
            relative=body.relative,
        )
    except Exception as e:
        raise HTTPException(400, f"j_l_offset failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/import/otio")
def import_otio_api(body: ImportOtioBody) -> dict[str, Any]:
    """Import simplified OTIO-like JSON (pair of export_otio)."""
    ed = _ed()
    try:
        r = ed.import_otio_json(
            body.path,
            text=body.text,
            clear_tracks=body.clear_tracks,
            import_missing_media=body.import_missing_media,
            conform=body.conform,
        )
        return {**r, "timeline": ed.timeline_view()}
    except Exception as e:
        raise HTTPException(400, f"import_otio failed: {e}") from e


@app.post("/api/export/still")
def export_still_api(body: ExportStillBody) -> dict[str, Any]:
    ed = _ed()
    frame = body.frame if body.frame is not None else 0
    out = body.output_path or str(
        _desktop_export_dir() / f"still_f{frame}.jpg"
    )
    try:
        return ed.export_still(out, frame, width=body.width)
    except Exception as e:
        raise HTTPException(500, f"export_still failed: {e}") from e


@app.post("/api/export/audio")
def export_audio_api(body: ExportAudioBody | None = None) -> dict[str, Any]:
    body = body or ExportAudioBody()
    ed = _ed()
    out = body.output_path or str(_desktop_export_dir() / "mix.wav")
    try:
        return ed.export_audio(
            out,
            start_frame=body.start_frame,
            end_frame=body.end_frame,
        )
    except Exception as e:
        raise HTTPException(500, f"export_audio failed: {e}") from e


@app.post("/api/track/delete")
def delete_track_api(body: DeleteTrackBody) -> dict[str, Any]:
    ed = _ed()
    try:
        tr = ed.delete_track(body.track_id)
    except Exception as e:
        raise HTTPException(400, f"delete_track failed: {e}") from e
    return {
        "track": tr.to_dict() if hasattr(tr, "to_dict") else {"id": body.track_id},
        "timeline": ed.timeline_view(),
    }


@app.post("/api/hard_cut_all")
def hard_cut_all_api(body: HardCutAllBody | None = None) -> dict[str, Any]:
    body = body or HardCutAllBody()
    ed = _ed()
    try:
        r = ed.hard_cut_all(track_id=body.track_id)
    except Exception as e:
        raise HTTPException(400, f"hard_cut_all failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/media/batch_relink")
def batch_relink_api(body: BatchRelinkBody) -> dict[str, Any]:
    if not body.mapping:
        raise HTTPException(400, "mapping required {old_media_id: new_media_id}")
    ed = _ed()
    try:
        r = ed.batch_relink(body.mapping, keep_source_range=body.keep_source_range)
    except Exception as e:
        raise HTTPException(400, f"batch_relink failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/split_at_beats")
def split_at_beats_api(body: SplitAtBeatsBody) -> dict[str, Any]:
    ed = _ed()
    try:
        r = ed.split_at_beats(
            body.track_id,
            media_id=body.media_id,
            path=body.path,
            max_splits=body.max_splits,
        )
    except Exception as e:
        raise HTTPException(400, f"split_at_beats failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class MarkersFromBeatsBody(BaseModel):
    media_id: str | None = None
    path: str | None = None
    max_markers: int = 128
    label_prefix: str = "Beat"
    color: str = "#e91e63"
    clear_existing_prefix: bool = False


@app.post("/api/markers/from_beats")
def markers_from_beats_api(body: MarkersFromBeatsBody | None = None) -> dict[str, Any]:
    """Place timeline markers on detected music beats (no razor)."""
    body = body or MarkersFromBeatsBody()
    ed = _ed()
    try:
        return ed.markers_from_beats(
            body.media_id,
            path=body.path,
            max_markers=body.max_markers,
            label_prefix=body.label_prefix,
            color=body.color,
            clear_existing_prefix=body.clear_existing_prefix,
        )
    except Exception as e:
        raise HTTPException(400, f"markers_from_beats failed: {e}") from e


class BeatGridBody(BaseModel):
    track_id: str | None = None
    media_id: str | None = None
    path: str | None = None
    mode: str = "markers"
    max_beats: int = 128
    label_prefix: str = "Beat"
    color: str = "#e91e63"
    clear_existing_prefix: bool = True
    snap_clip_ids: list[str] | None = None


@app.post("/api/edit/beat_grid")
def beat_grid_api(body: BeatGridBody) -> dict[str, Any]:
    """One-shot music grid: markers / split / both / markers_snap."""
    ed = _ed()
    try:
        r = ed.beat_grid(
            body.track_id,
            body.media_id,
            path=body.path,
            mode=body.mode,
            max_beats=body.max_beats,
            label_prefix=body.label_prefix,
            color=body.color,
            clear_existing_prefix=body.clear_existing_prefix,
            snap_clip_ids=body.snap_clip_ids,
        )
    except Exception as e:
        raise HTTPException(400, f"beat_grid failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class MarkersFromScenesBody(BaseModel):
    media_id: str | None = None
    path: str | None = None
    threshold: float = 27.0
    min_scene_len: int = 15
    backend: str = "auto"
    max_markers: int = 128
    label_prefix: str = "Scene"
    color: str = "#ff9800"
    clear_existing_prefix: bool = False
    include_start: bool = False


@app.post("/api/markers/from_scenes")
def markers_from_scenes_api(body: MarkersFromScenesBody | None = None) -> dict[str, Any]:
    body = body or MarkersFromScenesBody()
    ed = _ed()
    try:
        return ed.markers_from_scenes(
            body.media_id,
            path=body.path,
            threshold=body.threshold,
            min_scene_len=body.min_scene_len,
            backend=body.backend,
            max_markers=body.max_markers,
            label_prefix=body.label_prefix,
            color=body.color,
            clear_existing_prefix=body.clear_existing_prefix,
            include_start=body.include_start,
        )
    except Exception as e:
        raise HTTPException(400, f"markers_from_scenes failed: {e}") from e


class SceneGridBody(BaseModel):
    track_id: str | None = None
    media_id: str | None = None
    path: str | None = None
    mode: str = "markers"
    threshold: float = 27.0
    min_scene_len: int = 15
    backend: str = "auto"
    max_scenes: int = 128
    label_prefix: str = "Scene"
    color: str = "#ff9800"
    clear_existing_prefix: bool = True


@app.post("/api/edit/scene_grid")
def scene_grid_api(body: SceneGridBody) -> dict[str, Any]:
    """One-shot scene grid: markers / split / both."""
    ed = _ed()
    try:
        r = ed.scene_grid(
            body.track_id,
            body.media_id,
            path=body.path,
            mode=body.mode,
            threshold=body.threshold,
            min_scene_len=body.min_scene_len,
            backend=body.backend,
            max_scenes=body.max_scenes,
            label_prefix=body.label_prefix,
            color=body.color,
            clear_existing_prefix=body.clear_existing_prefix,
        )
    except Exception as e:
        raise HTTPException(400, f"scene_grid failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class TransitionsNearMarkersBody(BaseModel):
    track_id: str
    transition_type: str = "cross_dissolve"
    duration_frames: int = 12
    max_delta_frames: int = 2
    max_count: int | None = None
    marker_ids: list[str] | None = None


@app.post("/api/transitions/near_markers")
def transitions_near_markers_api(body: TransitionsNearMarkersBody) -> dict[str, Any]:
    """Dissolve only hard cuts that land near markers."""
    ed = _ed()
    try:
        r = ed.apply_transitions_near_markers(
            body.track_id,
            transition_type=body.transition_type,
            duration_frames=body.duration_frames,
            max_delta_frames=body.max_delta_frames,
            max_count=body.max_count,
            marker_ids=body.marker_ids,
        )
    except Exception as e:
        raise HTTPException(400, f"transitions near markers failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class PlaceAtMarkersBody(BaseModel):
    media_ids: list[str]
    track_id: str
    marker_ids: list[str] | None = None
    duration_frames: int | None = None
    mode: str = "overwrite"
    cycle: bool = True


@app.post("/api/place/at_markers")
def place_at_markers_api(body: PlaceAtMarkersBody) -> dict[str, Any]:
    """Lay bin media onto track at each timeline marker (B-roll grid)."""
    ed = _ed()
    try:
        r = ed.place_media_at_markers(
            body.media_ids,
            body.track_id,
            marker_ids=body.marker_ids,
            duration_frames=body.duration_frames,
            mode=body.mode,
            cycle=body.cycle,
        )
    except Exception as e:
        raise HTTPException(400, f"place_at_markers failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class FitToMarkersBody(BaseModel):
    clip_ids: list[str] | None = None
    track_id: str | None = None
    method: str = "speed"
    max_start_delta: int = 8
    clamp: bool = True
    marker_ids: list[str] | None = None


@app.post("/api/clips/fit_to_markers")
def fit_to_markers_api(body: FitToMarkersBody) -> dict[str, Any]:
    """Stretch/trim clips to fill marker slots."""
    ed = _ed()
    try:
        r = ed.fit_clips_to_markers(
            body.clip_ids,
            body.track_id,
            method=body.method,
            max_start_delta=body.max_start_delta,
            clamp=body.clamp,
            marker_ids=body.marker_ids,
        )
    except Exception as e:
        raise HTTPException(400, f"fit_to_markers failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class MusicBrollBody(BaseModel):
    track_id: str
    media_ids: list[str]
    beat_media_id: str | None = None
    beat_path: str | None = None
    max_beats: int = 64
    place_duration_frames: int | None = None
    fit_method: str = "speed"
    transition: str | None = "cross_dissolve"
    transition_frames: int = 8
    clear_beat_markers: bool = True


@app.post("/api/edit/music_broll")
def music_broll_api(body: MusicBrollBody) -> dict[str, Any]:
    """One-shot: beat markers → place media → fit → optional dissolves."""
    ed = _ed()
    try:
        r = ed.music_broll(
            body.track_id,
            body.media_ids,
            beat_media_id=body.beat_media_id,
            beat_path=body.beat_path,
            max_beats=body.max_beats,
            place_duration_frames=body.place_duration_frames,
            fit_method=body.fit_method,
            transition=body.transition,
            transition_frames=body.transition_frames,
            clear_beat_markers=body.clear_beat_markers,
        )
    except Exception as e:
        raise HTTPException(400, f"music_broll failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


@app.get("/api/markers/slots")
def marker_slots_api(
    include_tail: bool = True,
    min_duration_frames: int = 1,
) -> dict[str, Any]:
    """List marker-to-marker timeline slots."""
    return _ed().list_marker_slots(
        include_tail=include_tail,
        min_duration_frames=min_duration_frames,
    )


class MarkersFromSrtBody(BaseModel):
    path: str | None = None
    text: str | None = None
    label_from_text: bool = True
    max_label_len: int = 48
    color: str = "#4caf50"
    clear_existing: bool = False
    prefix: str = ""


@app.post("/api/markers/from_srt")
def markers_from_srt_api(body: MarkersFromSrtBody) -> dict[str, Any]:
    """Import SRT cue starts as timeline markers."""
    ed = _ed()
    try:
        return ed.markers_from_srt(
            body.path,
            text=body.text,
            label_from_text=body.label_from_text,
            max_label_len=body.max_label_len,
            color=body.color,
            clear_existing=body.clear_existing,
            prefix=body.prefix,
        )
    except Exception as e:
        raise HTTPException(400, f"markers_from_srt failed: {e}") from e


class ExportMarkerSegmentsBody(BaseModel):
    output_dir: str | None = None
    name_prefix: str = "seg"
    include_tail: bool = True
    min_duration_frames: int = 3
    marker_ids: list[str] | None = None
    filename_from_label: bool = True


@app.post("/api/export/marker_segments")
def export_marker_segments_api(body: ExportMarkerSegmentsBody | None = None) -> dict[str, Any]:
    """Export one MP4 per marker range (social/chapter cuts)."""
    body = body or ExportMarkerSegmentsBody()
    ed = _ed()
    out_dir = body.output_dir or str(_desktop_export_dir() / "marker_segments")
    try:
        return ed.export_marker_segments(
            out_dir,
            name_prefix=body.name_prefix,
            include_tail=body.include_tail,
            min_duration_frames=body.min_duration_frames,
            marker_ids=body.marker_ids,
            filename_from_label=body.filename_from_label,
        )
    except Exception as e:
        raise HTTPException(400, f"export_marker_segments failed: {e}") from e


class ExportTrackStemsBody(BaseModel):
    output_dir: str | None = None
    track_ids: list[str] | None = None
    kind: str | None = None
    name_prefix: str = "stem"
    audio_only: bool = False


@app.post("/api/export/track_stems")
def export_track_stems_api(body: ExportTrackStemsBody | None = None) -> dict[str, Any]:
    """Export each track soloed as a separate file (mute state restored)."""
    body = body or ExportTrackStemsBody()
    ed = _ed()
    out_dir = body.output_dir or str(_desktop_export_dir() / "track_stems")
    try:
        return ed.export_track_stems(
            out_dir,
            track_ids=body.track_ids,
            kind=body.kind,
            name_prefix=body.name_prefix,
            audio_only=body.audio_only,
        )
    except Exception as e:
        raise HTTPException(400, f"export_track_stems failed: {e}") from e


class BalanceGainsBody(BaseModel):
    clip_ids: list[str]
    target_db: float = 0.0
    relative: bool = True


@app.post("/api/clips/balance_gains")
def balance_gains_api(body: BalanceGainsBody) -> dict[str, Any]:
    """Balance clip gains to a shared average or absolute target."""
    ed = _ed()
    try:
        r = ed.balance_clip_gains(
            body.clip_ids, target_db=body.target_db, relative=body.relative,
        )
    except Exception as e:
        raise HTTPException(400, f"balance_gains failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class MatchGradeBody(BaseModel):
    source_clip_id: str
    target_clip_ids: list[str]
    replace: bool = True
    effect_types: list[str] | None = None


@app.post("/api/clips/match_grade")
def match_grade_api(body: MatchGradeBody) -> dict[str, Any]:
    """Copy grade FX from source clip onto targets."""
    ed = _ed()
    try:
        r = ed.match_grade_to_clip(
            body.source_clip_id,
            body.target_clip_ids,
            replace=body.replace,
            effect_types=body.effect_types,
        )
    except Exception as e:
        raise HTTPException(400, f"match_grade failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class SequenceFromMediaBody(BaseModel):
    media_ids: list[str]
    track_id: str
    start_frame: int = 0
    clear_track: bool = False
    transition: str | None = None
    transition_frames: int = 12
    name_from_media: bool = True


@app.post("/api/sequence/from_media")
def sequence_from_media_api(body: SequenceFromMediaBody) -> dict[str, Any]:
    """Assemble bin media end-to-end on a track."""
    ed = _ed()
    try:
        r = ed.sequence_from_media(
            body.media_ids,
            body.track_id,
            start_frame=body.start_frame,
            clear_track=body.clear_track,
            transition=body.transition,
            transition_frames=body.transition_frames,
            name_from_media=body.name_from_media,
        )
    except Exception as e:
        raise HTTPException(400, f"sequence_from_media failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class AssembleUnusedBody(BaseModel):
    track_id: str
    kind: str = "video"
    start_frame: int = 0
    clear_track: bool = False
    transition: str | None = None
    transition_frames: int = 12


@app.post("/api/sequence/assemble_unused")
def assemble_unused_api(body: AssembleUnusedBody) -> dict[str, Any]:
    """Place all unused bin media of a kind as an assembly cut."""
    ed = _ed()
    try:
        r = ed.assemble_unused_media(
            body.track_id,
            kind=body.kind,
            start_frame=body.start_frame,
            clear_track=body.clear_track,
            transition=body.transition,
            transition_frames=body.transition_frames,
        )
    except Exception as e:
        raise HTTPException(400, f"assemble_unused failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class RoughCutBody(BaseModel):
    track_id: str
    media_ids: list[str] | None = None
    use_unused: bool = True
    kind: str = "video"
    start_frame: int = 0
    clear_track: bool = False
    transition: str | None = "cross_dissolve"
    transition_frames: int = 10
    apply_edge_fades: bool = True
    fade_frames: int = 6


@app.post("/api/edit/rough_cut")
def rough_cut_api(body: RoughCutBody) -> dict[str, Any]:
    """One-shot rough cut: sequence + dissolves + edge fades."""
    ed = _ed()
    try:
        r = ed.rough_cut(
            body.track_id,
            media_ids=body.media_ids,
            use_unused=body.use_unused,
            kind=body.kind,
            start_frame=body.start_frame,
            clear_track=body.clear_track,
            transition=body.transition,
            transition_frames=body.transition_frames,
            apply_edge_fades=body.apply_edge_fades,
            fade_frames=body.fade_frames,
        )
    except Exception as e:
        raise HTTPException(400, f"rough_cut failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class EdgeFadesBody(BaseModel):
    clip_ids: list[str] | None = None
    track_id: str | None = None
    fade_in_frames: int = 6
    fade_out_frames: int = 6
    replace: bool = True


@app.post("/api/clips/edge_fades")
def edge_fades_api(body: EdgeFadesBody) -> dict[str, Any]:
    """Apply fade-in/out to selection or track."""
    ed = _ed()
    try:
        r = ed.apply_edge_fades(
            clip_ids=body.clip_ids,
            track_id=body.track_id,
            fade_in_frames=body.fade_in_frames,
            fade_out_frames=body.fade_out_frames,
            replace=body.replace,
        )
    except Exception as e:
        raise HTTPException(400, f"edge_fades failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class VoMusicDuckBody(BaseModel):
    vo_track_id: str | None = None
    music_track_id: str | None = None
    threshold_db: float = -30.0
    ratio: float = 8.0
    attack_ms: float = 20.0
    release_ms: float = 300.0
    makeup_db: float = 0.0
    music_gain_db: float | None = -6.0


@app.post("/api/mix/vo_music_duck")
def vo_music_duck_api(body: VoMusicDuckBody | None = None) -> dict[str, Any]:
    """Auto-wire music-under-VO ducking."""
    body = body or VoMusicDuckBody()
    ed = _ed()
    try:
        return ed.setup_vo_music_duck(
            vo_track_id=body.vo_track_id,
            music_track_id=body.music_track_id,
            threshold_db=body.threshold_db,
            ratio=body.ratio,
            attack_ms=body.attack_ms,
            release_ms=body.release_ms,
            makeup_db=body.makeup_db,
            music_gain_db=body.music_gain_db,
        )
    except Exception as e:
        raise HTTPException(400, f"vo_music_duck failed: {e}") from e


class FreezeAtMarkersBody(BaseModel):
    track_id: str
    duration_frames: int = 24
    marker_ids: list[str] | None = None
    place_track_id: str | None = None


@app.post("/api/freeze/at_markers")
def freeze_at_markers_api(body: FreezeAtMarkersBody) -> dict[str, Any]:
    """Freeze frame under each marker on a track."""
    ed = _ed()
    try:
        r = ed.freeze_at_markers(
            body.track_id,
            duration_frames=body.duration_frames,
            marker_ids=body.marker_ids,
            place_track_id=body.place_track_id,
        )
    except Exception as e:
        raise HTTPException(400, f"freeze_at_markers failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class StillsAtMarkersBody(BaseModel):
    output_dir: str | None = None
    width: int = 1280
    marker_ids: list[str] | None = None
    name_prefix: str = "still"


@app.post("/api/export/stills_at_markers")
def stills_at_markers_api(body: StillsAtMarkersBody | None = None) -> dict[str, Any]:
    """Export JPG stills at each marker."""
    body = body or StillsAtMarkersBody()
    ed = _ed()
    out = body.output_dir or str(_desktop_export_dir() / "marker_stills")
    try:
        return ed.stills_at_markers(
            out,
            width=body.width,
            marker_ids=body.marker_ids,
            name_prefix=body.name_prefix,
        )
    except Exception as e:
        raise HTTPException(400, f"stills_at_markers failed: {e}") from e


class TitleCardBody(BaseModel):
    content: str
    track_id: str
    start_frame: int = 0
    duration_frames: int = 90
    position: str = "center"
    size: int = 64
    border_width: int = 2
    color: str | None = "#ffd60a"


@app.post("/api/title_card")
def title_card_api(body: TitleCardBody) -> dict[str, Any]:
    """Place black slug + text title on a video track."""
    ed = _ed()
    try:
        r = ed.create_title_card(
            body.content,
            body.track_id,
            body.start_frame,
            body.duration_frames,
            position=body.position,
            size=body.size,
            border_width=body.border_width,
            color=body.color,
        )
    except Exception as e:
        raise HTTPException(400, f"title_card failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class PasteAttributesBatchBody(BaseModel):
    clip_ids: list[str]
    speed: bool = True
    position: bool = True
    gain: bool = True
    opacity: bool = True
    fades: bool = True


@app.post("/api/clips/paste_attributes")
def paste_attributes_batch_api(body: PasteAttributesBatchBody) -> dict[str, Any]:
    """Paste attributes clipboard onto many clips."""
    ed = _ed()
    try:
        r = ed.paste_attributes_to_clips(
            body.clip_ids,
            speed=body.speed,
            position=body.position,
            gain=body.gain,
            opacity=body.opacity,
            fades=body.fades,
        )
    except Exception as e:
        raise HTTPException(400, f"paste_attributes batch failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


@app.get("/api/snap_points")
def snap_points_api(include_markers: bool = True) -> dict[str, Any]:
    return _ed().snap_points(include_markers=include_markers)


@app.post("/api/preview/invalidate")
def preview_invalidate_api() -> dict[str, Any]:
    ed = _ed()
    ed.invalidate_preview_proxy()
    return {"ok": True, "proxy": ed.preview_proxy_status()}


@app.post("/api/recent/clear")
def recent_clear_api() -> dict[str, Any]:
    return _ed().clear_recent_projects()


@app.post("/api/write_srt")
def write_srt_api(body: WriteSrtBody) -> dict[str, Any]:
    ed = _ed()
    segs = list(body.segments or [])
    if body.from_markers and not segs:
        # markers → crude SRT segments (1s each)
        fps = float(ed.project.timebase.fps or 30.0)
        markers = sorted(
            ed.project.markers or [],
            key=lambda m: int(getattr(m, "frame", 0) or 0),
        )
        for i, m in enumerate(markers):
            f0 = int(getattr(m, "frame", 0) or 0)
            f1 = f0 + max(1, int(round(fps)))
            if i + 1 < len(markers):
                f1 = max(f0 + 1, int(getattr(markers[i + 1], "frame", f1) or f1))
            segs.append({
                "start": f0 / fps,
                "end": f1 / fps,
                "text": getattr(m, "label", None) or f"M{f0}",
            })
    if not segs:
        raise HTTPException(400, "segments required (or from_markers with markers)")
    out = body.path or str(_desktop_export_dir() / "markers.srt")
    try:
        written = ed.write_srt(out, segs)
    except Exception as e:
        raise HTTPException(400, f"write_srt failed: {e}") from e
    return {"path": str(written), "count": len(segs)}


@app.post("/api/normalize_file")
def normalize_file_api(body: NormalizeFileBody) -> dict[str, Any]:
    ed = _ed()
    out = body.output_path or str(
        _desktop_export_dir() / (Path(body.path).stem + "_norm.wav")
    )
    try:
        return ed.normalize_loudness(body.path, out, preset=body.preset)
    except Exception as e:
        raise HTTPException(400, f"normalize failed: {e}") from e


# --- Craft / mix / delivery helpers (0.4.71+) ---


class PathOnlyBody(BaseModel):
    path: str


class DetectBeatsBody(BaseModel):
    path: str
    max_seconds: float | None = 180.0
    sensitivity: float = 1.15


class SuggestMixBody(BaseModel):
    vo_path: str | None = None
    music_path: str | None = None
    sfx_path: str | None = None
    vo_track_id: str | None = None
    music_track_id: str | None = None


class ColorMatchBody(BaseModel):
    reference_clip_id: str
    clip_ids: list[str] | None = None
    strength: float = 0.65


class ApplySilenceBody(BaseModel):
    clip_id: str
    silence_threshold_db: float = -40.0
    min_silence_seconds: float = 0.4
    pad_seconds: float = 0.08
    min_keep_seconds: float = 0.2
    dry_run: bool = True


class PlaceAfterBody(BaseModel):
    after_clip_id: str
    media_id: str
    src_in: int = 0
    src_out: int | None = None


class SuggestProjectBody(BaseModel):
    paths: list[str] | None = None
    preference: str = "auto"


class DeliveryLimitsBody(BaseModel):
    paths: list[str] | None = None
    fps: float | None = None
    width: int | None = None
    height: int | None = None


class CaptionClipBody(BaseModel):
    clip_id: str
    srt_path: str | None = None
    model_size: str = "base"
    language: str | None = None


class ExportRangeBody(BaseModel):
    output_path: str | None = None
    start_seconds: float
    end_seconds: float
    normalize_preset: str | None = None
    run_delivery_check: bool = False


class ExportGifBody(BaseModel):
    output_path: str | None = None
    start_seconds: float = 0.0
    end_seconds: float | None = None
    fps: float = 12.0
    width: int = 480
    max_duration_seconds: float = 15.0


class KenBurnsBody(BaseModel):
    clip_id: str
    zoom_start: float = 1.0
    zoom_end: float = 1.15
    x_start: float = 0.5
    y_start: float = 0.5
    x_end: float = 0.5
    y_end: float = 0.5
    replace: bool = True


class KenBurnsImagesBody(BaseModel):
    track_id: str | None = None
    zoom_end: float = 1.12
    replace: bool = True


class PreviewRangeBody(BaseModel):
    output_path: str | None = None
    start_seconds: float
    end_seconds: float
    height: int = 360
    fps: float = 12.0
    ensure_proxy: bool = True


class OffsetLinkedBody(BaseModel):
    clip_id: str
    delta_frames: int
    kinds: list[str] | None = None


class RippleTrimBody(BaseModel):
    clip_id: str
    new_src_in: int | None = None
    new_src_out: int | None = None


class AnalyzeAssetBody(BaseModel):
    path: str
    do_scenes: bool = True
    do_silence: bool = True
    do_motion: bool = True
    do_transcribe: bool = False


class ApplyMixPlanBody(BaseModel):
    plan: dict[str, Any]
    role_clip_ids: dict[str, list[str]] | None = None
    music_track_id: str | None = None
    vo_track_id: str | None = None


@app.get("/api/looks")
def list_looks_api() -> dict[str, Any]:
    return _ed().list_look_presets()


@app.get("/api/encode_status")
def encode_status_api() -> dict[str, Any]:
    return _ed().encode_status()


@app.post("/api/detect/beats")
def detect_beats_api(body: DetectBeatsBody) -> dict[str, Any]:
    try:
        return _ed().detect_beats(
            body.path,
            max_seconds=body.max_seconds,
            sensitivity=body.sensitivity,
        )
    except Exception as e:
        raise HTTPException(400, f"detect_beats failed: {e}") from e


@app.post("/api/suggest/mix")
def suggest_mix_api(body: SuggestMixBody | None = None) -> dict[str, Any]:
    body = body or SuggestMixBody()
    try:
        return _ed().suggest_mix(
            vo_path=body.vo_path,
            music_path=body.music_path,
            sfx_path=body.sfx_path,
            vo_track_id=body.vo_track_id,
            music_track_id=body.music_track_id,
        )
    except Exception as e:
        raise HTTPException(400, f"suggest_mix failed: {e}") from e


@app.post("/api/clips/color_match")
def color_match_api(body: ColorMatchBody) -> dict[str, Any]:
    ed = _ed()
    try:
        r = ed.color_match_to_clip(
            body.reference_clip_id,
            clip_ids=body.clip_ids,
            strength=body.strength,
        )
    except Exception as e:
        raise HTTPException(400, f"color_match failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/clip/apply_silence")
def apply_silence_api(body: ApplySilenceBody) -> dict[str, Any]:
    ed = _ed()
    try:
        r = ed.apply_silence_to_clip(
            body.clip_id,
            silence_threshold_db=body.silence_threshold_db,
            min_silence_seconds=body.min_silence_seconds,
            pad_seconds=body.pad_seconds,
            min_keep_seconds=body.min_keep_seconds,
            dry_run=body.dry_run,
        )
    except Exception as e:
        raise HTTPException(400, f"apply_silence failed: {e}") from e
    out: dict[str, Any] = {**r}
    if not body.dry_run:
        out["timeline"] = ed.timeline_view()
    return out


@app.get("/api/media/{media_id}/clips")
def clips_sharing_media_api(media_id: str) -> dict[str, Any]:
    return _ed().clips_sharing_media(media_id)


@app.post("/api/place_after")
def place_after_api(body: PlaceAfterBody) -> dict[str, Any]:
    ed = _ed()
    try:
        clip = ed.place_after(
            body.after_clip_id,
            body.media_id,
            src_in=body.src_in,
            src_out=body.src_out,
        )
    except Exception as e:
        raise HTTPException(400, f"place_after failed: {e}") from e
    return {
        "clip": clip.to_dict() if hasattr(clip, "to_dict") else {"id": clip.id},
        "timeline": ed.timeline_view(),
    }


@app.post("/api/suggest/fps")
def suggest_fps_api(body: SuggestProjectBody | None = None) -> dict[str, Any]:
    body = body or SuggestProjectBody()
    try:
        return _ed().suggest_project_fps(paths=body.paths, preference=body.preference)
    except Exception as e:
        raise HTTPException(400, f"suggest_fps failed: {e}") from e


@app.post("/api/suggest/resolution")
def suggest_resolution_api(body: SuggestProjectBody | None = None) -> dict[str, Any]:
    body = body or SuggestProjectBody()
    try:
        return _ed().suggest_project_resolution(
            paths=body.paths, preference=body.preference,
        )
    except Exception as e:
        raise HTTPException(400, f"suggest_resolution failed: {e}") from e


@app.post("/api/delivery/limits")
def delivery_limits_api(body: DeliveryLimitsBody | None = None) -> dict[str, Any]:
    body = body or DeliveryLimitsBody()
    try:
        return _ed().check_delivery_limits(
            paths=body.paths,
            fps=body.fps,
            width=body.width,
            height=body.height,
        )
    except Exception as e:
        raise HTTPException(400, f"delivery_limits failed: {e}") from e


@app.get("/api/media/{media_id}/transcript")
def load_transcript_api(media_id: str) -> dict[str, Any]:
    r = _ed().load_cached_transcript(media_id)
    if r is None:
        return {"media_id": media_id, "transcript": None, "cached": False}
    return {"media_id": media_id, "transcript": r, "cached": True}


@app.post("/api/clip/caption")
def caption_clip_api(body: CaptionClipBody) -> dict[str, Any]:
    ed = _ed()
    try:
        r = ed.caption_clip(
            body.clip_id,
            srt_path=body.srt_path,
            model_size=body.model_size,
            language=body.language,
        )
    except Exception as e:
        raise HTTPException(400, f"caption_clip failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/export/range")
def export_range_api(body: ExportRangeBody) -> dict[str, Any]:
    ed = _ed()
    out = body.output_path or str(_desktop_export_dir() / "range.mp4")
    try:
        return ed.export_range(
            out,
            body.start_seconds,
            body.end_seconds,
            normalize_preset=body.normalize_preset,
            run_delivery_check=body.run_delivery_check,
        )
    except Exception as e:
        raise HTTPException(500, f"export_range failed: {e}") from e


@app.post("/api/export/gif")
def export_gif_api(body: ExportGifBody) -> dict[str, Any]:
    """Export timeline range as animated GIF."""
    ed = _ed()
    out = body.output_path or str(_desktop_export_dir() / "clip.gif")
    try:
        return ed.export_gif(
            out,
            start_seconds=body.start_seconds,
            end_seconds=body.end_seconds,
            fps=body.fps,
            width=body.width,
            max_duration_seconds=body.max_duration_seconds,
        )
    except Exception as e:
        raise HTTPException(500, f"export_gif failed: {e}") from e


class ExportWorkAreaGifBody(BaseModel):
    output_path: str | None = None
    fps: float = 12.0
    width: int = 480
    max_duration_seconds: float = 15.0


@app.post("/api/export/work_area_gif")
def export_work_area_gif_api(body: ExportWorkAreaGifBody) -> dict[str, Any]:
    """Export in/out work area as GIF."""
    ed = _ed()
    out = body.output_path or str(_desktop_export_dir() / "work_area.gif")
    try:
        return ed.export_work_area_gif(
            out,
            fps=body.fps,
            width=body.width,
            max_duration_seconds=body.max_duration_seconds,
        )
    except Exception as e:
        raise HTTPException(400, f"work_area_gif failed: {e}") from e


class SolidBody(BaseModel):
    color: str = "#000000"
    duration_frames: int = 30
    start: int | None = None
    track_id: str | None = None
    name: str | None = None
    append: bool = True


@app.post("/api/edit/solid")
def solid_api(body: SolidBody) -> dict[str, Any]:
    """Place a solid color matte clip."""
    ed = _ed()
    try:
        r = ed.add_solid(
            body.color,
            duration_frames=body.duration_frames,
            start=body.start,
            track_id=body.track_id,
            name=body.name,
            append=body.append,
        )
    except Exception as e:
        raise HTTPException(400, f"solid failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/clip/ken_burns")
def ken_burns_api(body: KenBurnsBody) -> dict[str, Any]:
    """Apply Ken Burns zoom/pan to a clip."""
    ed = _ed()
    try:
        r = ed.apply_ken_burns(
            body.clip_id,
            zoom_start=body.zoom_start,
            zoom_end=body.zoom_end,
            x_start=body.x_start,
            y_start=body.y_start,
            x_end=body.x_end,
            y_end=body.y_end,
            replace=body.replace,
        )
    except Exception as e:
        raise HTTPException(400, f"ken_burns failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class VignetteBody(BaseModel):
    clip_id: str
    strength: float = 0.45
    replace: bool = True


@app.post("/api/clip/vignette")
def vignette_api(body: VignetteBody) -> dict[str, Any]:
    """Apply vignette to a clip."""
    ed = _ed()
    try:
        r = ed.apply_vignette(
            body.clip_id, strength=body.strength, replace=body.replace,
        )
    except Exception as e:
        raise HTTPException(400, f"vignette failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class FilmGrainBody(BaseModel):
    clip_id: str
    amount: float = 12.0
    replace: bool = True


@app.post("/api/clip/film_grain")
def film_grain_api(body: FilmGrainBody) -> dict[str, Any]:
    """Apply film grain to a clip."""
    ed = _ed()
    try:
        r = ed.apply_film_grain(
            body.clip_id, amount=body.amount, replace=body.replace,
        )
    except Exception as e:
        raise HTTPException(400, f"film_grain failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class BlurBody(BaseModel):
    clip_id: str
    amount: float = 5.0
    replace: bool = True


@app.post("/api/clip/blur")
def blur_api(body: BlurBody) -> dict[str, Any]:
    """Apply blur to a clip."""
    ed = _ed()
    try:
        r = ed.apply_blur(body.clip_id, amount=body.amount, replace=body.replace)
    except Exception as e:
        raise HTTPException(400, f"blur failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class SharpenBody(BaseModel):
    clip_id: str
    amount: float = 1.0
    replace: bool = True


@app.post("/api/clip/sharpen")
def sharpen_api(body: SharpenBody) -> dict[str, Any]:
    """Apply sharpen to a clip."""
    ed = _ed()
    try:
        r = ed.apply_sharpen(
            body.clip_id, amount=body.amount, replace=body.replace,
        )
    except Exception as e:
        raise HTTPException(400, f"sharpen failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class GlowBody(BaseModel):
    clip_id: str
    amount: float = 8.0
    intensity: float = 0.4
    replace: bool = True


@app.post("/api/clip/glow")
def glow_api(body: GlowBody) -> dict[str, Any]:
    """Apply glow to a clip."""
    ed = _ed()
    try:
        r = ed.apply_glow(
            body.clip_id,
            amount=body.amount,
            intensity=body.intensity,
            replace=body.replace,
        )
    except Exception as e:
        raise HTTPException(400, f"glow failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class ChromaKeyBody(BaseModel):
    clip_id: str
    color: str = "green"
    similarity: float = 0.15
    blend: float = 0.05
    replace: bool = True


@app.post("/api/clip/chroma_key")
def chroma_key_api(body: ChromaKeyBody) -> dict[str, Any]:
    """Apply chroma key (green/blue screen) to a clip."""
    ed = _ed()
    try:
        r = ed.apply_chroma_key(
            body.clip_id,
            color=body.color,
            similarity=body.similarity,
            blend=body.blend,
            replace=body.replace,
        )
    except Exception as e:
        raise HTTPException(400, f"chroma_key failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class LumaKeyBody(BaseModel):
    clip_id: str
    threshold: float = 0.1
    tolerance: float = 0.1
    replace: bool = True


@app.post("/api/clip/luma_key")
def luma_key_api(body: LumaKeyBody) -> dict[str, Any]:
    """Apply luma key to a clip."""
    ed = _ed()
    try:
        r = ed.apply_luma_key(
            body.clip_id,
            threshold=body.threshold,
            tolerance=body.tolerance,
            replace=body.replace,
        )
    except Exception as e:
        raise HTTPException(400, f"luma_key failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class WhiteBalanceBody(BaseModel):
    clip_id: str
    temperature: float = 6500.0
    mix: float = 1.0
    replace: bool = True


@app.post("/api/clip/white_balance")
def white_balance_api(body: WhiteBalanceBody) -> dict[str, Any]:
    """Apply white balance to a clip."""
    ed = _ed()
    try:
        r = ed.apply_white_balance(
            body.clip_id,
            temperature=body.temperature,
            mix=body.mix,
            replace=body.replace,
        )
    except Exception as e:
        raise HTTPException(400, f"white_balance failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class ExportWorkAreaWebmBody(BaseModel):
    output_path: str | None = None
    crf: int = 32
    width: int | None = None


@app.post("/api/export/work_area_webm")
def export_work_area_webm_api(body: ExportWorkAreaWebmBody) -> dict[str, Any]:
    """Export in/out work area as WebM."""
    ed = _ed()
    out = body.output_path or str(_desktop_export_dir() / "work_area.webm")
    try:
        return ed.export_work_area_webm(
            out, crf=body.crf, width=body.width,
        )
    except Exception as e:
        raise HTTPException(400, f"work_area_webm failed: {e}") from e


class ShapeMaskBody(BaseModel):
    clip_id: str
    shape: str = "circle"
    cx: float = 0.5
    cy: float = 0.5
    size: float = 0.5
    feather: float = 0.05
    width: float = 0.5
    height: float = 0.5
    invert: bool = False
    replace: bool = True


@app.post("/api/clip/shape_mask")
def shape_mask_api(body: ShapeMaskBody) -> dict[str, Any]:
    """Apply shape mask to a clip."""
    ed = _ed()
    try:
        r = ed.apply_shape_mask(
            body.clip_id,
            shape=body.shape,
            cx=body.cx,
            cy=body.cy,
            size=body.size,
            feather=body.feather,
            width=body.width,
            height=body.height,
            invert=body.invert,
            replace=body.replace,
        )
    except Exception as e:
        raise HTTPException(400, f"shape_mask failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class CurvesBody(BaseModel):
    clip_id: str
    preset: str = "increase_contrast"
    replace: bool = True


@app.post("/api/clip/curves")
def curves_api(body: CurvesBody) -> dict[str, Any]:
    """Apply curves grade preset to a clip."""
    ed = _ed()
    try:
        r = ed.apply_curves(
            body.clip_id, preset=body.preset, replace=body.replace,
        )
    except Exception as e:
        raise HTTPException(400, f"curves failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class ExportClipWebmBody(BaseModel):
    clip_id: str
    output_path: str | None = None
    crf: int = 32
    width: int | None = None


@app.post("/api/export/clip_webm")
def export_clip_webm_api(body: ExportClipWebmBody) -> dict[str, Any]:
    """Export one clip span as WebM."""
    ed = _ed()
    out = body.output_path or str(_desktop_export_dir() / "clip.webm")
    try:
        return ed.export_clip_webm(
            body.clip_id, out, crf=body.crf, width=body.width,
        )
    except Exception as e:
        raise HTTPException(400, f"clip_webm failed: {e}") from e


class CompressionBody(BaseModel):
    clip_id: str
    ratio: float = 4.0
    threshold_db: float = -18.0
    attack_ms: float = 20.0
    release_ms: float = 250.0
    makeup_db: float = 0.0
    replace: bool = True


@app.post("/api/clip/compression")
def compression_api(body: CompressionBody) -> dict[str, Any]:
    """Apply audio compression to a clip."""
    ed = _ed()
    try:
        r = ed.apply_compression(
            body.clip_id,
            ratio=body.ratio,
            threshold_db=body.threshold_db,
            attack_ms=body.attack_ms,
            release_ms=body.release_ms,
            makeup_db=body.makeup_db,
            replace=body.replace,
        )
    except Exception as e:
        raise HTTPException(400, f"compression failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class AudioEqBody(BaseModel):
    clip_id: str
    frequency_hz: float = 1000.0
    gain_db: float = 0.0
    q: float = 1.0
    replace: bool = False


@app.post("/api/clip/audio_eq")
def audio_eq_api(body: AudioEqBody) -> dict[str, Any]:
    """Apply parametric EQ band to a clip."""
    ed = _ed()
    try:
        r = ed.apply_audio_eq(
            body.clip_id,
            frequency_hz=body.frequency_hz,
            gain_db=body.gain_db,
            q=body.q,
            replace=body.replace,
        )
    except Exception as e:
        raise HTTPException(400, f"audio_eq failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class ExportClipAudioBody(BaseModel):
    clip_id: str
    output_path: str | None = None
    sample_rate: int | None = None


@app.post("/api/export/clip_audio")
def export_clip_audio_api(body: ExportClipAudioBody) -> dict[str, Any]:
    """Export mixdown audio for a clip's timeline span."""
    ed = _ed()
    out = body.output_path or str(_desktop_export_dir() / "clip.wav")
    try:
        return ed.export_clip_audio(
            body.clip_id, out, sample_rate=body.sample_rate,
        )
    except Exception as e:
        raise HTTPException(400, f"clip_audio failed: {e}") from e


class NoiseReductionBody(BaseModel):
    clip_id: str
    amount: float = 12.0
    replace: bool = True


@app.post("/api/clip/noise_reduction")
def noise_reduction_api(body: NoiseReductionBody) -> dict[str, Any]:
    """Apply noise reduction to a clip."""
    ed = _ed()
    try:
        r = ed.apply_noise_reduction(
            body.clip_id, amount=body.amount, replace=body.replace,
        )
    except Exception as e:
        raise HTTPException(400, f"noise_reduction failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class ExportClipMp4Body(BaseModel):
    clip_id: str
    output_path: str | None = None
    normalize_preset: str | None = None


@app.post("/api/export/clip_mp4")
def export_clip_mp4_api(body: ExportClipMp4Body) -> dict[str, Any]:
    """Export one clip span as MP4."""
    ed = _ed()
    out = body.output_path or str(_desktop_export_dir() / "clip.mp4")
    try:
        return ed.export_clip_mp4(
            body.clip_id, out, normalize_preset=body.normalize_preset,
        )
    except Exception as e:
        raise HTTPException(400, f"clip_mp4 failed: {e}") from e


class CountdownBody(BaseModel):
    seconds: int = 3
    frames_per_digit: int | None = None
    track_id: str | None = None
    size: int = 96
    ripple_all_tracks: bool = True


@app.post("/api/edit/countdown")
def countdown_api(body: CountdownBody) -> dict[str, Any]:
    """Prepend 3-2-1 countdown title cards."""
    ed = _ed()
    try:
        r = ed.add_countdown(
            seconds=body.seconds,
            frames_per_digit=body.frames_per_digit,
            track_id=body.track_id,
            size=body.size,
            ripple_all_tracks=body.ripple_all_tracks,
        )
    except Exception as e:
        raise HTTPException(400, f"countdown failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class SpeedRippleBody(BaseModel):
    clip_id: str
    speed: float


@app.post("/api/clip/speed_ripple")
def speed_ripple_api(body: SpeedRippleBody) -> dict[str, Any]:
    """Set speed and ripple later clips on the same track."""
    ed = _ed()
    try:
        r = ed.set_speed_ripple(body.clip_id, body.speed)
    except Exception as e:
        raise HTTPException(400, f"speed_ripple failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class ExportClipStillBody(BaseModel):
    clip_id: str
    output_path: str | None = None
    at: str = "mid"
    width: int = 1280


@app.post("/api/export/clip_still")
def export_clip_still_api(body: ExportClipStillBody) -> dict[str, Any]:
    """Export still from clip mid/start/end."""
    ed = _ed()
    out = body.output_path or str(_desktop_export_dir() / "clip_still.jpg")
    try:
        return ed.export_clip_still(
            body.clip_id, out, at=body.at, width=body.width,
        )
    except Exception as e:
        raise HTTPException(400, f"clip_still failed: {e}") from e


class FreezeClipMidBody(BaseModel):
    clip_id: str
    duration_frames: int = 30
    insert: bool = True


@app.post("/api/clip/freeze_mid")
def freeze_clip_mid_api(body: FreezeClipMidBody) -> dict[str, Any]:
    """Freeze mid-frame of a clip and place still after it."""
    ed = _ed()
    try:
        r = ed.freeze_clip_mid(
            body.clip_id,
            duration_frames=body.duration_frames,
            insert=body.insert,
        )
    except Exception as e:
        raise HTTPException(400, f"freeze_mid failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class ExportClipsPackBody(BaseModel):
    clip_ids: list[str]
    output_dir: str | None = None
    prefix: str = "clip"


@app.post("/api/export/clips_pack")
def export_clips_pack_api(body: ExportClipsPackBody) -> dict[str, Any]:
    """Export each clip as MP4 into a folder."""
    ed = _ed()
    out = body.output_dir or str(_desktop_export_dir() / "clips_pack")
    try:
        return ed.export_clips_pack(
            body.clip_ids, out, prefix=body.prefix,
        )
    except Exception as e:
        raise HTTPException(400, f"clips_pack failed: {e}") from e


class SlateBody(BaseModel):
    title: str = "SLATE"
    subtitle: str | None = None
    duration_frames: int = 90
    track_id: str | None = None
    size: int = 64
    ripple_all_tracks: bool = True
    append: bool = False


@app.post("/api/edit/slate")
def slate_api(body: SlateBody) -> dict[str, Any]:
    """Add production slate title card."""
    ed = _ed()
    try:
        r = ed.add_slate(
            body.title,
            subtitle=body.subtitle,
            duration_frames=body.duration_frames,
            track_id=body.track_id,
            size=body.size,
            ripple_all_tracks=body.ripple_all_tracks,
            append=body.append,
        )
    except Exception as e:
        raise HTTPException(400, f"slate failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class CloseGapsAllBody(BaseModel):
    from_frame: int = 0
    kind: str | None = None


@app.post("/api/edit/close_gaps_all")
def close_gaps_all_api(body: CloseGapsAllBody) -> dict[str, Any]:
    """Close gaps on all unlocked tracks."""
    ed = _ed()
    try:
        r = ed.close_gaps_all_tracks(
            from_frame=body.from_frame, kind=body.kind,
        )
    except Exception as e:
        raise HTTPException(400, f"close_gaps_all failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class ExportTrackOnlyBody(BaseModel):
    track_id: str | None = None
    clip_id: str | None = None
    output_path: str | None = None
    normalize_preset: str | None = None


@app.post("/api/export/track_only")
def export_track_only_api(body: ExportTrackOnlyBody) -> dict[str, Any]:
    """Export with only one track unmuted (track_id or clip_id)."""
    ed = _ed()
    out = body.output_path or str(_desktop_export_dir() / "track_only.mp4")
    if not body.track_id and not body.clip_id:
        raise HTTPException(400, "track_id or clip_id required")
    try:
        tid = body.track_id or ""
        return ed.export_track_only(
            tid,
            out,
            normalize_preset=body.normalize_preset,
            clip_id=body.clip_id,
        )
    except Exception as e:
        raise HTTPException(400, f"track_only failed: {e}") from e


class ExportSelectionMp4Body(BaseModel):
    clip_ids: list[str]
    output_path: str | None = None
    normalize_preset: str | None = None


@app.post("/api/export/selection_mp4")
def export_selection_mp4_api(body: ExportSelectionMp4Body) -> dict[str, Any]:
    """Export union span of selected clips as MP4."""
    ed = _ed()
    out = body.output_path or str(_desktop_export_dir() / "selection.mp4")
    try:
        return ed.export_selection_mp4(
            body.clip_ids, out, normalize_preset=body.normalize_preset,
        )
    except Exception as e:
        raise HTTPException(400, f"selection_mp4 failed: {e}") from e


class ExportWorkAreaMp4Body(BaseModel):
    output_path: str | None = None
    normalize_preset: str | None = None


@app.post("/api/export/work_area_mp4")
def export_work_area_mp4_api(body: ExportWorkAreaMp4Body) -> dict[str, Any]:
    """Export in/out work area as MP4."""
    ed = _ed()
    out = body.output_path or str(_desktop_export_dir() / "work_area.mp4")
    try:
        return ed.export_work_area_mp4(
            out, normalize_preset=body.normalize_preset,
        )
    except Exception as e:
        raise HTTPException(400, f"work_area_mp4 failed: {e}") from e


class LiftClipBody(BaseModel):
    clip_id: str


@app.post("/api/edit/lift_clip")
def lift_clip_api(body: LiftClipBody) -> dict[str, Any]:
    """Lift clip leaving a gap (no ripple)."""
    ed = _ed()
    try:
        r = ed.lift_clip(body.clip_id)
    except Exception as e:
        raise HTTPException(400, f"lift_clip failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class RippleDeleteSelectionBody(BaseModel):
    clip_ids: list[str]


@app.post("/api/edit/ripple_delete_selection")
def ripple_delete_selection_api(body: RippleDeleteSelectionBody) -> dict[str, Any]:
    """Ripple-delete multiple clips."""
    ed = _ed()
    try:
        r = ed.ripple_delete_selection(body.clip_ids)
    except Exception as e:
        raise HTTPException(400, f"ripple_delete_selection failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class CopyEffectsBody(BaseModel):
    source_clip_id: str
    target_clip_ids: list[str]
    replace: bool = True
    types: list[str] | None = None


@app.post("/api/clip/copy_effects_to")
def copy_effects_to_api(body: CopyEffectsBody) -> dict[str, Any]:
    """Copy effects from source clip onto target clips (batch).

    Distinct path from /api/clip/copy_effects (clipboard mode) so both coexist.
    """
    ed = _ed()
    try:
        r = ed.copy_effects(
            body.source_clip_id,
            body.target_clip_ids,
            replace=body.replace,
            types=body.types,
        )
    except Exception as e:
        raise HTTPException(400, f"copy_effects failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class ExportClipsStillsPackBody(BaseModel):
    clip_ids: list[str]
    output_dir: str | None = None
    at: str = "mid"
    width: int = 1280
    prefix: str = "still"


@app.post("/api/export/clips_stills_pack")
def export_clips_stills_pack_api(body: ExportClipsStillsPackBody) -> dict[str, Any]:
    """Export stills for many clips into a folder."""
    ed = _ed()
    out = body.output_dir or str(_desktop_export_dir() / "stills_pack")
    try:
        return ed.export_clips_stills_pack(
            body.clip_ids,
            out,
            at=body.at,
            width=body.width,
            prefix=body.prefix,
        )
    except Exception as e:
        raise HTTPException(400, f"clips_stills_pack failed: {e}") from e


class PastePositionBody(BaseModel):
    source_clip_id: str
    target_clip_ids: list[str]


@app.post("/api/clip/paste_position")
def paste_position_api(body: PastePositionBody) -> dict[str, Any]:
    """Paste PiP position from source to targets."""
    ed = _ed()
    try:
        r = ed.paste_position(body.source_clip_id, body.target_clip_ids)
    except Exception as e:
        raise HTTPException(400, f"paste_position failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class ClipsFlipBody(BaseModel):
    clip_ids: list[str]
    horizontal: bool | None = True
    vertical: bool | None = None
    toggle_h: bool = False
    toggle_v: bool = False


@app.post("/api/clip/set_clips_flip")
def set_clips_flip_api(body: ClipsFlipBody) -> dict[str, Any]:
    """Batch hflip/vflip on clips."""
    ed = _ed()
    try:
        r = ed.set_clips_flip(
            body.clip_ids,
            horizontal=body.horizontal,
            vertical=body.vertical,
            toggle_h=body.toggle_h,
            toggle_v=body.toggle_v,
        )
    except Exception as e:
        raise HTTPException(400, f"set_clips_flip failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class PasteCropBody(BaseModel):
    source_clip_id: str
    target_clip_ids: list[str]
    replace: bool = True


@app.post("/api/clip/paste_crop")
def paste_crop_api(body: PasteCropBody) -> dict[str, Any]:
    """Paste crop effect from source to targets."""
    ed = _ed()
    try:
        r = ed.paste_crop(
            body.source_clip_id,
            body.target_clip_ids,
            replace=body.replace,
        )
    except Exception as e:
        raise HTTPException(400, f"paste_crop failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class LutClipsBody(BaseModel):
    clip_ids: list[str]
    path: str
    replace: bool = True


@app.post("/api/clip/apply_lut")
def apply_lut_to_clips_api(body: LutClipsBody) -> dict[str, Any]:
    """Apply 3D LUT to many clips."""
    ed = _ed()
    try:
        r = ed.apply_lut_to_clips(
            body.clip_ids, body.path, replace=body.replace,
        )
    except Exception as e:
        raise HTTPException(400, f"apply_lut failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class PasteFromClipBody(BaseModel):
    source_clip_id: str
    target_clip_ids: list[str]
    effects: bool = True
    attributes: bool = True
    color: bool = True
    replace_effects: bool = True


@app.post("/api/clip/paste_from_clip")
def paste_from_clip_api(body: PasteFromClipBody) -> dict[str, Any]:
    """One-shot paste source attrs+effects onto targets."""
    ed = _ed()
    try:
        r = ed.paste_from_clip(
            body.source_clip_id,
            body.target_clip_ids,
            effects=body.effects,
            attributes=body.attributes,
            color=body.color,
            replace_effects=body.replace_effects,
        )
    except Exception as e:
        raise HTTPException(400, f"paste_from_clip failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class DuplicateSelectionBody(BaseModel):
    clip_ids: list[str]
    offset_frames: int | None = None
    gap_frames: int = 0


@app.post("/api/edit/duplicate_selection")
def duplicate_selection_api(body: DuplicateSelectionBody) -> dict[str, Any]:
    """Duplicate many clips."""
    ed = _ed()
    try:
        r = ed.duplicate_selection(
            body.clip_ids,
            offset_frames=body.offset_frames,
            gap_frames=body.gap_frames,
        )
    except Exception as e:
        raise HTTPException(400, f"duplicate_selection failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class ExportSelectionAudioBody(BaseModel):
    clip_ids: list[str]
    output_path: str | None = None
    sample_rate: int | None = None


@app.post("/api/export/selection_audio")
def export_selection_audio_api(body: ExportSelectionAudioBody) -> dict[str, Any]:
    """Export mixdown audio for selection span."""
    ed = _ed()
    out = body.output_path or str(_desktop_export_dir() / "selection.wav")
    try:
        return ed.export_selection_audio(
            body.clip_ids, out, sample_rate=body.sample_rate,
        )
    except Exception as e:
        raise HTTPException(400, f"selection_audio failed: {e}") from e


class SplitSelectionBody(BaseModel):
    clip_ids: list[str]
    at_frame: int


@app.post("/api/edit/split_selection")
def split_selection_api(body: SplitSelectionBody) -> dict[str, Any]:
    """Razor selected clips at frame."""
    ed = _ed()
    try:
        r = ed.split_selection_at(body.clip_ids, body.at_frame)
    except Exception as e:
        raise HTTPException(400, f"split_selection failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class MarkersFromSelectionBody(BaseModel):
    clip_ids: list[str]
    edge: str = "start"
    prefix: str = "Sel "
    color: str = "#4cc9f0"
    clear_matching_prefix: bool = False


@app.post("/api/markers/from_selection")
def markers_from_selection_api(body: MarkersFromSelectionBody) -> dict[str, Any]:
    """Markers at selection clip edges."""
    ed = _ed()
    try:
        r = ed.markers_from_selection(
            body.clip_ids,
            edge=body.edge,
            prefix=body.prefix,
            color=body.color,
            clear_matching_prefix=body.clear_matching_prefix,
        )
    except Exception as e:
        raise HTTPException(400, f"markers_from_selection failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class SelectionSpanBody(BaseModel):
    clip_ids: list[str]


@app.post("/api/edit/selection_span")
def selection_span_api(body: SelectionSpanBody) -> dict[str, Any]:
    """Read-only union span of clips."""
    ed = _ed()
    try:
        return ed.selection_span(body.clip_ids)
    except Exception as e:
        raise HTTPException(400, f"selection_span failed: {e}") from e


class ExportSelectionGifBody(BaseModel):
    clip_ids: list[str]
    output_path: str | None = None
    fps: float = 12.0
    width: int = 480
    max_duration_seconds: float = 12.0


@app.post("/api/export/selection_gif")
def export_selection_gif_api(body: ExportSelectionGifBody) -> dict[str, Any]:
    """Export selection span as GIF."""
    ed = _ed()
    out = body.output_path or str(_desktop_export_dir() / "selection.gif")
    try:
        return ed.export_selection_gif(
            body.clip_ids,
            out,
            fps=body.fps,
            width=body.width,
            max_duration_seconds=body.max_duration_seconds,
        )
    except Exception as e:
        raise HTTPException(400, f"selection_gif failed: {e}") from e


class ExportSelectionWebmBody(BaseModel):
    clip_ids: list[str]
    output_path: str | None = None
    crf: int = 32
    width: int | None = None


@app.post("/api/export/selection_webm")
def export_selection_webm_api(body: ExportSelectionWebmBody) -> dict[str, Any]:
    """Export selection span as WebM."""
    ed = _ed()
    out = body.output_path or str(_desktop_export_dir() / "selection.webm")
    try:
        return ed.export_selection_webm(
            body.clip_ids, out, crf=body.crf, width=body.width,
        )
    except Exception as e:
        raise HTTPException(400, f"selection_webm failed: {e}") from e


class TrimSelectionPlayheadBody(BaseModel):
    clip_ids: list[str]
    playhead_frame: int
    edge: str = "head"
    mode: str = "ripple"


@app.post("/api/edit/trim_selection_playhead")
def trim_selection_playhead_api(body: TrimSelectionPlayheadBody) -> dict[str, Any]:
    """Batch trim selection to playhead (Q/W)."""
    ed = _ed()
    try:
        r = ed.trim_selection_to_playhead(
            body.clip_ids,
            body.playhead_frame,
            edge=body.edge,
            mode=body.mode,
        )
    except Exception as e:
        raise HTTPException(400, f"trim_selection_playhead failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class WorkAreaSelectionExportBody(BaseModel):
    clip_ids: list[str]
    output_path: str | None = None
    normalize_preset: str | None = None


@app.post("/api/export/work_area_from_selection")
def work_area_from_selection_export_api(body: WorkAreaSelectionExportBody) -> dict[str, Any]:
    """Set work area from selection and export MP4."""
    ed = _ed()
    out = body.output_path or str(_desktop_export_dir() / "selection_wa.mp4")
    try:
        r = ed.set_work_area_from_selection_export(
            body.clip_ids, out, normalize_preset=body.normalize_preset,
        )
    except Exception as e:
        raise HTTPException(400, f"work_area_from_selection failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class ExtendToNextBody(BaseModel):
    clip_id: str


@app.post("/api/clip/extend_to_next")
def extend_to_next_api(body: ExtendToNextBody) -> dict[str, Any]:
    """Extend clip into gap before next clip."""
    ed = _ed()
    try:
        r = ed.extend_to_next_clip(body.clip_id)
    except Exception as e:
        raise HTTPException(400, f"extend_to_next failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class ReverseSelectionBody(BaseModel):
    clip_ids: list[str]
    replace: bool = True


@app.post("/api/edit/reverse_selection")
def reverse_selection_api(body: ReverseSelectionBody) -> dict[str, Any]:
    """Reverse media for selection."""
    ed = _ed()
    try:
        r = ed.reverse_selection(body.clip_ids, replace=body.replace)
    except Exception as e:
        raise HTTPException(400, f"reverse_selection failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class SelectionSpeedRippleBody(BaseModel):
    clip_ids: list[str]
    speed: float


@app.post("/api/edit/selection_speed_ripple")
def selection_speed_ripple_api(body: SelectionSpeedRippleBody) -> dict[str, Any]:
    """Speed+ripple each selected clip."""
    ed = _ed()
    try:
        r = ed.set_selection_speed_ripple(body.clip_ids, body.speed)
    except Exception as e:
        raise HTTPException(400, f"selection_speed_ripple failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class TransitionsSelectionBody(BaseModel):
    clip_ids: list[str]
    transition_type: str = "cross_dissolve"
    duration_frames: int = 12
    require_both_selected: bool = True


@app.post("/api/edit/transitions_selection")
def transitions_selection_api(body: TransitionsSelectionBody) -> dict[str, Any]:
    """Add transitions on hard cuts within selection."""
    ed = _ed()
    try:
        r = ed.add_transitions_to_selection(
            body.clip_ids,
            transition_type=body.transition_type,
            duration_frames=body.duration_frames,
            require_both_selected=body.require_both_selected,
        )
    except Exception as e:
        raise HTTPException(400, f"transitions_selection failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class RemoveTransitionsSelectionBody(BaseModel):
    clip_ids: list[str]


@app.post("/api/edit/remove_transitions_selection")
def remove_transitions_selection_api(body: RemoveTransitionsSelectionBody) -> dict[str, Any]:
    """Strip transition_in from selection."""
    ed = _ed()
    try:
        r = ed.remove_transitions_from_selection(body.clip_ids)
    except Exception as e:
        raise HTTPException(400, f"remove_transitions_selection failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class StaggerSelectionBody(BaseModel):
    clip_ids: list[str]
    offset_frames: int = 10
    from_earliest: bool = True


@app.post("/api/edit/stagger_selection")
def stagger_selection_api(body: StaggerSelectionBody) -> dict[str, Any]:
    """Stair-step offset selection starts."""
    ed = _ed()
    try:
        r = ed.stagger_selection(
            body.clip_ids,
            body.offset_frames,
            from_earliest=body.from_earliest,
        )
    except Exception as e:
        raise HTTPException(400, f"stagger_selection failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class SplitEvenBody(BaseModel):
    clip_ids: list[str]
    parts: int = 2


@app.post("/api/edit/split_selection_evenly")
def split_selection_evenly_api(body: SplitEvenBody) -> dict[str, Any]:
    """Split each selected clip into equal parts."""
    ed = _ed()
    try:
        r = ed.split_selection_evenly(body.clip_ids, parts=body.parts)
    except Exception as e:
        raise HTTPException(400, f"split_selection_evenly failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class MarkersMidsBody(BaseModel):
    clip_ids: list[str]
    prefix: str = "Mid "
    color: str = "#90be6d"


@app.post("/api/markers/selection_mids")
def markers_selection_mids_api(body: MarkersMidsBody) -> dict[str, Any]:
    """Markers at midpoints of selection."""
    ed = _ed()
    try:
        r = ed.markers_at_selection_mids(
            body.clip_ids, prefix=body.prefix, color=body.color,
        )
    except Exception as e:
        raise HTTPException(400, f"selection_mids failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class EdgeFadesSelectionBody(BaseModel):
    clip_ids: list[str]
    fade_in_frames: int = 6
    fade_out_frames: int = 6
    replace: bool = True


@app.post("/api/edit/edge_fades_selection")
def edge_fades_selection_api(body: EdgeFadesSelectionBody) -> dict[str, Any]:
    """Edge fades on selection."""
    ed = _ed()
    try:
        r = ed.apply_edge_fades_to_selection(
            body.clip_ids,
            fade_in_frames=body.fade_in_frames,
            fade_out_frames=body.fade_out_frames,
            replace=body.replace,
        )
    except Exception as e:
        raise HTTPException(400, f"edge_fades_selection failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class DetachAudioSelectionBody(BaseModel):
    clip_ids: list[str]
    audio_track_id: str | None = None
    audio_start_offset_frames: int = 0
    link: bool = True


@app.post("/api/edit/detach_audio_selection")
def detach_audio_selection_api(body: DetachAudioSelectionBody) -> dict[str, Any]:
    """Batch detach audio from selected video clips."""
    ed = _ed()
    try:
        r = ed.detach_audio_selection(
            body.clip_ids,
            audio_track_id=body.audio_track_id,
            audio_start_offset_frames=body.audio_start_offset_frames,
            link=body.link,
        )
    except Exception as e:
        raise HTTPException(400, f"detach_audio_selection failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class MatchSelectionDurationBody(BaseModel):
    clip_ids: list[str]
    target_clip_id: str | None = None
    target_frames: int | None = None
    clamp: bool = True


@app.post("/api/edit/match_selection_duration")
def match_selection_duration_api(body: MatchSelectionDurationBody) -> dict[str, Any]:
    """Match all selected clips' duration to target (default first)."""
    ed = _ed()
    try:
        r = ed.match_selection_duration(
            body.clip_ids,
            target_clip_id=body.target_clip_id,
            target_frames=body.target_frames,
            clamp=body.clamp,
        )
    except Exception as e:
        raise HTTPException(400, f"match_selection_duration failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class SelectionJlCutBody(BaseModel):
    clip_ids: list[str]
    style: str = "j"
    frames: int = 15
    link: bool = True


@app.post("/api/edit/selection_jl_cut")
def selection_jl_cut_api(body: SelectionJlCutBody) -> dict[str, Any]:
    """J-cut or L-cut selection via audio detach offset."""
    ed = _ed()
    try:
        r = ed.selection_jl_cut(
            body.clip_ids,
            style=body.style,
            frames=body.frames,
            link=body.link,
        )
    except Exception as e:
        raise HTTPException(400, f"selection_jl_cut failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class ExpandLinksBody(BaseModel):
    clip_ids: list[str]


@app.post("/api/edit/expand_selection_links")
def expand_selection_links_api(body: ExpandLinksBody) -> dict[str, Any]:
    """Expand selection to linked peers."""
    ed = _ed()
    try:
        return ed.expand_selection_links(body.clip_ids)
    except Exception as e:
        raise HTTPException(400, f"expand_selection_links failed: {e}") from e


class CloseGapsSelectionTracksBody(BaseModel):
    clip_ids: list[str]
    from_frame: int = 0


@app.post("/api/edit/close_gaps_selection_tracks")
def close_gaps_selection_tracks_api(body: CloseGapsSelectionTracksBody) -> dict[str, Any]:
    """Close gaps on tracks that hold selection."""
    ed = _ed()
    try:
        r = ed.close_gaps_on_selection_tracks(
            body.clip_ids, from_frame=body.from_frame,
        )
    except Exception as e:
        raise HTTPException(400, f"close_gaps_selection_tracks failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class FreezeSelectionMidsBody(BaseModel):
    clip_ids: list[str]
    duration_frames: int = 30
    insert: bool = True


@app.post("/api/edit/freeze_selection_mids")
def freeze_selection_mids_api(body: FreezeSelectionMidsBody) -> dict[str, Any]:
    """Freeze mid-frame for each selected clip."""
    ed = _ed()
    try:
        r = ed.freeze_selection_mids(
            body.clip_ids,
            duration_frames=body.duration_frames,
            insert=body.insert,
        )
    except Exception as e:
        raise HTTPException(400, f"freeze_selection_mids failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class IsolateSelectionBody(BaseModel):
    clip_ids: list[str]
    kind: str | None = None


@app.post("/api/edit/isolate_selection")
def isolate_selection_api(body: IsolateSelectionBody) -> dict[str, Any]:
    """Mute all clips not in selection."""
    ed = _ed()
    try:
        r = ed.isolate_selection(body.clip_ids, kind=body.kind)
    except Exception as e:
        raise HTTPException(400, f"isolate_selection failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class MoveSelectionTrackBody(BaseModel):
    clip_ids: list[str]
    track_id: str
    preserve_starts: bool = True
    stack_start: int | None = None


@app.post("/api/edit/move_selection_to_track")
def move_selection_to_track_api(body: MoveSelectionTrackBody) -> dict[str, Any]:
    """Move selection onto a track."""
    ed = _ed()
    try:
        r = ed.move_selection_to_track(
            body.clip_ids,
            body.track_id,
            preserve_starts=body.preserve_starts,
            stack_start=body.stack_start,
        )
    except Exception as e:
        raise HTTPException(400, f"move_selection_to_track failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class SelectionGainBody(BaseModel):
    clip_ids: list[str]
    db: float


@app.post("/api/edit/selection_gain")
def selection_gain_api(body: SelectionGainBody) -> dict[str, Any]:
    """Set gain on selection."""
    ed = _ed()
    try:
        r = ed.set_selection_gain(body.clip_ids, body.db)
    except Exception as e:
        raise HTTPException(400, f"selection_gain failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class SelectionOpacityBody(BaseModel):
    clip_ids: list[str]
    amount: float


@app.post("/api/edit/selection_opacity")
def selection_opacity_api(body: SelectionOpacityBody) -> dict[str, Any]:
    """Set opacity on selection."""
    ed = _ed()
    try:
        r = ed.set_selection_opacity(body.clip_ids, body.amount)
    except Exception as e:
        raise HTTPException(400, f"selection_opacity failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class SelectionToNewTrackBody(BaseModel):
    clip_ids: list[str]
    name: str | None = None
    preserve_starts: bool = True
    stack_start: int | None = None


@app.post("/api/edit/selection_to_new_track")
def selection_to_new_track_api(body: SelectionToNewTrackBody) -> dict[str, Any]:
    """Create track and move selection onto it."""
    ed = _ed()
    try:
        r = ed.selection_to_new_track(
            body.clip_ids,
            name=body.name,
            preserve_starts=body.preserve_starts,
            stack_start=body.stack_start,
        )
    except Exception as e:
        raise HTTPException(400, f"selection_to_new_track failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class DuplicateSelectionTrackBody(BaseModel):
    clip_ids: list[str]
    track_id: str
    preserve_starts: bool = True
    start_offset: int = 0


@app.post("/api/edit/duplicate_selection_to_track")
def duplicate_selection_to_track_api(body: DuplicateSelectionTrackBody) -> dict[str, Any]:
    """Copy selection onto another track."""
    ed = _ed()
    try:
        r = ed.duplicate_selection_to_track(
            body.clip_ids,
            body.track_id,
            preserve_starts=body.preserve_starts,
            start_offset=body.start_offset,
        )
    except Exception as e:
        raise HTTPException(400, f"duplicate_selection_to_track failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class BakeSelectionBody(BaseModel):
    clip_ids: list[str]
    replace: bool = True
    clear_effects: bool = True
    include_audio: bool = True


@app.post("/api/edit/bake_selection")
def bake_selection_api(body: BakeSelectionBody) -> dict[str, Any]:
    """Bake FX for each selected clip."""
    ed = _ed()
    try:
        r = ed.bake_selection(
            body.clip_ids,
            replace=body.replace,
            clear_effects=body.clear_effects,
            include_audio=body.include_audio,
        )
    except Exception as e:
        raise HTTPException(400, f"bake_selection failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class ExportSelectionCutlistBody(BaseModel):
    clip_ids: list[str]
    output_path: str | None = None
    format: str = "csv"


@app.post("/api/export/selection_cutlist")
def export_selection_cutlist_api(body: ExportSelectionCutlistBody) -> dict[str, Any]:
    """Export cutlist for selected clips only."""
    ed = _ed()
    out = body.output_path or str(
        _desktop_export_dir() / f"selection_cutlist.{body.format}"
    )
    try:
        return ed.export_selection_cutlist(
            body.clip_ids, out, format=body.format,
        )
    except Exception as e:
        raise HTTPException(400, f"selection_cutlist failed: {e}") from e


class ExportSelectionEdlBody(BaseModel):
    clip_ids: list[str]
    output_path: str | None = None
    title: str | None = None


@app.post("/api/export/selection_edl")
def export_selection_edl_api(body: ExportSelectionEdlBody) -> dict[str, Any]:
    """Export CMX EDL for selected clips."""
    ed = _ed()
    out = body.output_path or str(_desktop_export_dir() / "selection.edl")
    try:
        return ed.export_selection_edl(
            body.clip_ids, out, title=body.title,
        )
    except Exception as e:
        raise HTTPException(400, f"selection_edl failed: {e}") from e


class RenameSelectionBody(BaseModel):
    clip_ids: list[str]
    pattern: str = "Clip {n:03d}"
    start: int = 1


@app.post("/api/edit/rename_selection")
def rename_selection_api(body: RenameSelectionBody) -> dict[str, Any]:
    """Rename selected clips with pattern."""
    ed = _ed()
    try:
        r = ed.rename_selection(
            body.clip_ids, body.pattern, start=body.start,
        )
    except Exception as e:
        raise HTTPException(400, f"rename_selection failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class ColorSelectionBody(BaseModel):
    clip_ids: list[str]
    color: str | None = "#4cc9f0"


@app.post("/api/edit/color_selection")
def color_selection_api(body: ColorSelectionBody) -> dict[str, Any]:
    """Set color chip on selection."""
    ed = _ed()
    try:
        r = ed.color_selection(body.clip_ids, body.color)
    except Exception as e:
        raise HTTPException(400, f"color_selection failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class SelectionDiagnosticsBody(BaseModel):
    clip_ids: list[str]


@app.post("/api/edit/selection_diagnostics")
def selection_diagnostics_api(body: SelectionDiagnosticsBody) -> dict[str, Any]:
    """Read-only selection diagnostics for agents."""
    ed = _ed()
    try:
        return ed.selection_diagnostics(body.clip_ids)
    except Exception as e:
        raise HTTPException(400, f"selection_diagnostics failed: {e}") from e


class SelectionPathCBody(BaseModel):
    clip_ids: list[str]


@app.post("/api/edit/selection_path_c")
def selection_path_c_api(body: SelectionPathCBody) -> dict[str, Any]:
    """path-C readiness report for selection."""
    ed = _ed()
    try:
        return ed.selection_path_c_report(body.clip_ids)
    except Exception as e:
        raise HTTPException(400, f"selection_path_c failed: {e}") from e


class LookSelectionBody(BaseModel):
    clip_ids: list[str]
    look: str = "cinematic"
    video_only: bool = True


@app.post("/api/edit/look_selection")
def look_selection_api(body: LookSelectionBody) -> dict[str, Any]:
    """Apply look preset to selection."""
    ed = _ed()
    try:
        r = ed.apply_look_to_selection(
            body.clip_ids, body.look, video_only=body.video_only,
        )
    except Exception as e:
        raise HTTPException(400, f"look_selection failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class StyleSelectionBody(BaseModel):
    clip_ids: list[str]
    styles: str
    apply_motion: bool = True
    place_audio_assets: bool = False


@app.post("/api/edit/style_selection")
def style_selection_api(body: StyleSelectionBody) -> dict[str, Any]:
    """Apply film style preset(s) to selection."""
    ed = _ed()
    try:
        r = ed.apply_style_to_selection(
            body.clip_ids,
            body.styles,
            apply_motion=body.apply_motion,
            place_audio_assets=body.place_audio_assets,
        )
    except Exception as e:
        raise HTTPException(400, f"style_selection failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class RetargetSelectionBody(BaseModel):
    clip_ids: list[str]
    media_id: str
    keep_source_range: bool = True


@app.post("/api/edit/retarget_selection_media")
def retarget_selection_media_api(body: RetargetSelectionBody) -> dict[str, Any]:
    """Retarget selection clips to a media_id."""
    ed = _ed()
    try:
        r = ed.retarget_selection_media(
            body.clip_ids,
            body.media_id,
            keep_source_range=body.keep_source_range,
        )
    except Exception as e:
        raise HTTPException(400, f"retarget_selection_media failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class SlipSelectionBody(BaseModel):
    clip_ids: list[str]
    delta_src_frames: int


@app.post("/api/edit/slip_selection")
def slip_selection_api(body: SlipSelectionBody) -> dict[str, Any]:
    """Slip source window on selection."""
    ed = _ed()
    try:
        r = ed.slip_selection(body.clip_ids, body.delta_src_frames)
    except Exception as e:
        raise HTTPException(400, f"slip_selection failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class SlideSelectionBody(BaseModel):
    clip_ids: list[str]
    delta_frames: int


@app.post("/api/edit/slide_selection")
def slide_selection_api(body: SlideSelectionBody) -> dict[str, Any]:
    """Slide/roll selection clips."""
    ed = _ed()
    try:
        r = ed.slide_selection(body.clip_ids, body.delta_frames)
    except Exception as e:
        raise HTTPException(400, f"slide_selection failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class SnapSelectionPlayheadBody(BaseModel):
    clip_ids: list[str]
    playhead_frame: int
    edge: str = "start"
    mode: str = "relative"


@app.post("/api/edit/snap_selection_playhead")
def snap_selection_playhead_api(body: SnapSelectionPlayheadBody) -> dict[str, Any]:
    """Snap selection group to playhead."""
    ed = _ed()
    try:
        r = ed.snap_selection_to_playhead(
            body.clip_ids,
            body.playhead_frame,
            edge=body.edge,
            mode=body.mode,
        )
    except Exception as e:
        raise HTTPException(400, f"snap_selection_playhead failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class LiftSelectionBody(BaseModel):
    clip_ids: list[str]
    follow_links: bool = False


@app.post("/api/edit/lift_selection")
def lift_selection_api(body: LiftSelectionBody) -> dict[str, Any]:
    """Lift selection (remove, leave gaps)."""
    ed = _ed()
    try:
        r = ed.lift_selection(body.clip_ids, follow_links=body.follow_links)
    except Exception as e:
        raise HTTPException(400, f"lift_selection failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class PackSelectionBody(BaseModel):
    clip_ids: list[str]
    gap_frames: int = 0


@app.post("/api/edit/pack_selection")
def pack_selection_api(body: PackSelectionBody) -> dict[str, Any]:
    """Pack selected clips tight per track."""
    ed = _ed()
    try:
        r = ed.pack_selection(body.clip_ids, gap_frames=body.gap_frames)
    except Exception as e:
        raise HTTPException(400, f"pack_selection failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class MuteSelectionBody(BaseModel):
    clip_ids: list[str]
    muted: bool = True


@app.post("/api/edit/mute_selection")
def mute_selection_api(body: MuteSelectionBody) -> dict[str, Any]:
    """Mute or unmute selection."""
    ed = _ed()
    try:
        r = ed.mute_selection(body.clip_ids, muted=body.muted)
    except Exception as e:
        raise HTTPException(400, f"mute_selection failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class ExtractSelectionBody(BaseModel):
    clip_ids: list[str]


@app.post("/api/edit/extract_selection")
def extract_selection_api(body: ExtractSelectionBody) -> dict[str, Any]:
    """Extract selection (ripple remove)."""
    ed = _ed()
    try:
        r = ed.extract_selection(body.clip_ids)
    except Exception as e:
        raise HTTPException(400, f"extract_selection failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class JoinSelectionBody(BaseModel):
    clip_ids: list[str]


@app.post("/api/edit/join_selection")
def join_selection_api(body: JoinSelectionBody) -> dict[str, Any]:
    """Join adjacent joinable pairs in selection."""
    ed = _ed()
    try:
        r = ed.join_selection(body.clip_ids)
    except Exception as e:
        raise HTTPException(400, f"join_selection failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class SelectionPositionBody(BaseModel):
    clip_ids: list[str]
    x: float = 1.0
    y: float = 1.0
    scale: float = 0.35


@app.post("/api/edit/selection_position")
def selection_position_api(body: SelectionPositionBody) -> dict[str, Any]:
    """Set PiP position/scale on selection."""
    ed = _ed()
    try:
        r = ed.set_selection_position(
            body.clip_ids, body.x, body.y, body.scale,
        )
    except Exception as e:
        raise HTTPException(400, f"selection_position failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class ClearSelectionPositionBody(BaseModel):
    clip_ids: list[str]


@app.post("/api/edit/clear_selection_position")
def clear_selection_position_api(body: ClearSelectionPositionBody) -> dict[str, Any]:
    """Clear PiP on selection."""
    ed = _ed()
    try:
        r = ed.clear_selection_position(body.clip_ids)
    except Exception as e:
        raise HTTPException(400, f"clear_selection_position failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class ReverseSelectionOrderBody(BaseModel):
    clip_ids: list[str]


@app.post("/api/edit/reverse_selection_order")
def reverse_selection_order_api(body: ReverseSelectionOrderBody) -> dict[str, Any]:
    """Reverse order of selected clips per track."""
    ed = _ed()
    try:
        r = ed.reverse_selection_order(body.clip_ids)
    except Exception as e:
        raise HTTPException(400, f"reverse_selection_order failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class LinkSelectionBody(BaseModel):
    clip_ids: list[str]
    group_id: str | None = None


@app.post("/api/edit/link_selection")
def link_selection_api(body: LinkSelectionBody) -> dict[str, Any]:
    """Link selection into one group."""
    ed = _ed()
    try:
        r = ed.link_selection(body.clip_ids, group_id=body.group_id)
    except Exception as e:
        raise HTTPException(400, f"link_selection failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class UnlinkSelectionBody(BaseModel):
    clip_ids: list[str]


@app.post("/api/edit/unlink_selection")
def unlink_selection_api(body: UnlinkSelectionBody) -> dict[str, Any]:
    """Unlink selection."""
    ed = _ed()
    try:
        r = ed.unlink_selection(body.clip_ids)
    except Exception as e:
        raise HTTPException(400, f"unlink_selection failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class RateStretchSelectionBody(BaseModel):
    clip_ids: list[str]
    target_duration_frames: int


@app.post("/api/edit/rate_stretch_selection")
def rate_stretch_selection_api(body: RateStretchSelectionBody) -> dict[str, Any]:
    """Rate-stretch selection to target timeline duration."""
    ed = _ed()
    try:
        r = ed.rate_stretch_selection(
            body.clip_ids, body.target_duration_frames,
        )
    except Exception as e:
        raise HTTPException(400, f"rate_stretch_selection failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class TrimSelectionEdgesBody(BaseModel):
    clip_ids: list[str]
    head_frames: int = 0
    tail_frames: int = 0


@app.post("/api/edit/trim_selection_edges")
def trim_selection_edges_api(body: TrimSelectionEdgesBody) -> dict[str, Any]:
    """Trim head/tail of selection."""
    ed = _ed()
    try:
        r = ed.trim_selection_edges(
            body.clip_ids,
            head_frames=body.head_frames,
            tail_frames=body.tail_frames,
        )
    except Exception as e:
        raise HTTPException(400, f"trim_selection_edges failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class SelectionGapsBody(BaseModel):
    clip_ids: list[str]


@app.post("/api/edit/selection_gaps")
def selection_gaps_api(body: SelectionGapsBody) -> dict[str, Any]:
    """Report gaps/overlaps between selected clips."""
    ed = _ed()
    try:
        r = ed.selection_gaps(body.clip_ids)
    except Exception as e:
        raise HTTPException(400, f"selection_gaps failed: {e}") from e
    return r


class ExtendSelectionNextBody(BaseModel):
    clip_ids: list[str]


@app.post("/api/edit/extend_selection_next")
def extend_selection_next_api(body: ExtendSelectionNextBody) -> dict[str, Any]:
    """Extend selection clips to next neighbor."""
    ed = _ed()
    try:
        r = ed.extend_selection_to_next(body.clip_ids)
    except Exception as e:
        raise HTTPException(400, f"extend_selection_next failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class SelectionSpeedBody(BaseModel):
    clip_ids: list[str]
    speed: float = 1.0


@app.post("/api/edit/selection_speed")
def selection_speed_api(body: SelectionSpeedBody) -> dict[str, Any]:
    """Set speed on selection (no ripple)."""
    ed = _ed()
    try:
        r = ed.set_selection_speed(body.clip_ids, body.speed)
    except Exception as e:
        raise HTTPException(400, f"selection_speed failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class SelectionPathCPlanBody(BaseModel):
    clip_ids: list[str]
    height: int = 360
    include_audio: bool = False


@app.post("/api/edit/selection_path_c_plan")
def selection_path_c_plan_api(body: SelectionPathCPlanBody) -> dict[str, Any]:
    """path-C OpenShot plan for selection."""
    ed = _ed()
    try:
        return ed.selection_path_c_plan(
            body.clip_ids,
            height=body.height,
            include_audio=body.include_audio,
        )
    except Exception as e:
        raise HTTPException(400, f"selection_path_c_plan failed: {e}") from e


class MatchFrameSelectionBody(BaseModel):
    clip_ids: list[str]
    timeline_frame: int | None = None


@app.post("/api/edit/match_frame_selection")
def match_frame_selection_api(body: MatchFrameSelectionBody) -> dict[str, Any]:
    """Batch match_frame on selection."""
    ed = _ed()
    try:
        return ed.match_frame_selection(
            body.clip_ids, timeline_frame=body.timeline_frame,
        )
    except Exception as e:
        raise HTTPException(400, f"match_frame_selection failed: {e}") from e


class RippleTrimSelectionEdgesBody(BaseModel):
    clip_ids: list[str]
    head_src_frames: int = 0
    tail_src_frames: int = 0


@app.post("/api/edit/ripple_trim_selection_edges")
def ripple_trim_selection_edges_api(
    body: RippleTrimSelectionEdgesBody,
) -> dict[str, Any]:
    """Ripple-trim head/tail of selection."""
    ed = _ed()
    try:
        r = ed.ripple_trim_selection_edges(
            body.clip_ids,
            head_src_frames=body.head_src_frames,
            tail_src_frames=body.tail_src_frames,
        )
    except Exception as e:
        raise HTTPException(400, f"ripple_trim_selection_edges failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class ExportSelectionPathCPlanBody(BaseModel):
    clip_ids: list[str]
    output_path: str | None = None
    height: int = 360
    include_audio: bool = False


@app.post("/api/edit/export_selection_path_c_plan")
def export_selection_path_c_plan_api(
    body: ExportSelectionPathCPlanBody,
) -> dict[str, Any]:
    """Write path-C selection plan JSON to disk."""
    ed = _ed()
    out = body.output_path or str(_desktop_export_dir() / "selection_path_c_plan.json")
    try:
        return ed.export_selection_path_c_plan(
            body.clip_ids,
            out,
            height=body.height,
            include_audio=body.include_audio,
        )
    except Exception as e:
        raise HTTPException(400, f"export_selection_path_c_plan failed: {e}") from e


class FillSelectionGapsBody(BaseModel):
    clip_ids: list[str]
    mode: str = "slug"
    color: str = "#000000"


@app.post("/api/edit/fill_selection_gaps")
def fill_selection_gaps_api(body: FillSelectionGapsBody) -> dict[str, Any]:
    """Fill gaps between selected clips (slug or pack)."""
    ed = _ed()
    try:
        r = ed.fill_selection_gaps(
            body.clip_ids, mode=body.mode, color=body.color,
        )
    except Exception as e:
        raise HTTPException(400, f"fill_selection_gaps failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class SwapSelectionPairBody(BaseModel):
    clip_id_a: str
    clip_id_b: str


@app.post("/api/edit/swap_selection_pair")
def swap_selection_pair_api(body: SwapSelectionPairBody) -> dict[str, Any]:
    """Swap starts of two clips."""
    ed = _ed()
    try:
        r = ed.swap_selection_pair(body.clip_id_a, body.clip_id_b)
    except Exception as e:
        raise HTTPException(400, f"swap_selection_pair failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class DuplicateSelectionBlockBody(BaseModel):
    clip_ids: list[str]
    gap_frames: int = 0


@app.post("/api/edit/duplicate_selection_block")
def duplicate_selection_block_api(
    body: DuplicateSelectionBlockBody,
) -> dict[str, Any]:
    """Duplicate selection as rigid block after union end."""
    ed = _ed()
    try:
        r = ed.duplicate_selection_block(
            body.clip_ids, gap_frames=body.gap_frames,
        )
    except Exception as e:
        raise HTTPException(400, f"duplicate_selection_block failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class AlignSelectionEndsBody(BaseModel):
    clip_ids: list[str]
    to_frame: int | None = None


@app.post("/api/edit/align_selection_ends")
def align_selection_ends_api(body: AlignSelectionEndsBody) -> dict[str, Any]:
    """Align ends of selected clips."""
    ed = _ed()
    try:
        r = ed.align_selection_ends(body.clip_ids, to_frame=body.to_frame)
    except Exception as e:
        raise HTTPException(400, f"align_selection_ends failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class SelectionMediaReportBody(BaseModel):
    clip_ids: list[str]


@app.post("/api/edit/selection_media_report")
def selection_media_report_api(body: SelectionMediaReportBody) -> dict[str, Any]:
    """Media inventory for selection."""
    ed = _ed()
    try:
        return ed.selection_media_report(body.clip_ids)
    except Exception as e:
        raise HTTPException(400, f"selection_media_report failed: {e}") from e


class RenameSelectionFromMediaBody(BaseModel):
    clip_ids: list[str]
    suffix_index: bool = False


@app.post("/api/edit/rename_selection_from_media")
def rename_selection_from_media_api(
    body: RenameSelectionFromMediaBody,
) -> dict[str, Any]:
    """Rename selection from media stems."""
    ed = _ed()
    try:
        r = ed.rename_selection_from_media(
            body.clip_ids, suffix_index=body.suffix_index,
        )
    except Exception as e:
        raise HTTPException(400, f"rename_selection_from_media failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class NudgeSelectionBody(BaseModel):
    clip_ids: list[str]
    delta_frames: int
    follow_links: bool = False


@app.post("/api/edit/nudge_selection")
def nudge_selection_api(body: NudgeSelectionBody) -> dict[str, Any]:
    """Nudge selection by delta frames."""
    ed = _ed()
    try:
        r = ed.nudge_selection(
            body.clip_ids, body.delta_frames, follow_links=body.follow_links,
        )
    except Exception as e:
        raise HTTPException(400, f"nudge_selection failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class MoveSelectionToFrameBody(BaseModel):
    clip_ids: list[str]
    to_frame: int
    follow_links: bool = False


@app.post("/api/edit/move_selection_to_frame")
def move_selection_to_frame_api(body: MoveSelectionToFrameBody) -> dict[str, Any]:
    """Move selection block so earliest start = to_frame."""
    ed = _ed()
    try:
        r = ed.move_selection_to_frame(
            body.clip_ids, body.to_frame, follow_links=body.follow_links,
        )
    except Exception as e:
        raise HTTPException(400, f"move_selection_to_frame failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class InsertTimeBeforeSelectionBody(BaseModel):
    clip_ids: list[str]
    frames: int


@app.post("/api/edit/insert_time_before_selection")
def insert_time_before_selection_api(
    body: InsertTimeBeforeSelectionBody,
) -> dict[str, Any]:
    """Ripple-insert empty time before selection."""
    ed = _ed()
    try:
        r = ed.insert_time_before_selection(body.clip_ids, body.frames)
    except Exception as e:
        raise HTTPException(400, f"insert_time_before_selection failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class RemoveTimeBeforeSelectionBody(BaseModel):
    clip_ids: list[str]
    frames: int


@app.post("/api/edit/remove_time_before_selection")
def remove_time_before_selection_api(
    body: RemoveTimeBeforeSelectionBody,
) -> dict[str, Any]:
    """Ripple-remove empty time before selection."""
    ed = _ed()
    try:
        r = ed.remove_time_before_selection(body.clip_ids, body.frames)
    except Exception as e:
        raise HTTPException(400, f"remove_time_before_selection failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class RippleNudgeSelectionBody(BaseModel):
    clip_ids: list[str]
    delta_frames: int
    include_self: bool = True


@app.post("/api/edit/ripple_nudge_selection")
def ripple_nudge_selection_api(body: RippleNudgeSelectionBody) -> dict[str, Any]:
    """Ripple-nudge from earliest selected per track."""
    ed = _ed()
    try:
        r = ed.ripple_nudge_selection(
            body.clip_ids,
            body.delta_frames,
            include_self=body.include_self,
        )
    except Exception as e:
        raise HTTPException(400, f"ripple_nudge_selection failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class RazorSelectionAtBody(BaseModel):
    clip_ids: list[str]
    at_frame: int


@app.post("/api/edit/razor_selection_at")
def razor_selection_at_api(body: RazorSelectionAtBody) -> dict[str, Any]:
    """Razor selection at frame."""
    ed = _ed()
    try:
        r = ed.razor_selection_at(body.clip_ids, body.at_frame)
    except Exception as e:
        raise HTTPException(400, f"razor_selection_at failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class FlipSelectionBody(BaseModel):
    clip_ids: list[str]
    horizontal: bool | None = None
    vertical: bool | None = None
    toggle_h: bool = False
    toggle_v: bool = False


@app.post("/api/edit/flip_selection")
def flip_selection_api(body: FlipSelectionBody) -> dict[str, Any]:
    """Flip selection H/V."""
    ed = _ed()
    try:
        r = ed.flip_selection(
            body.clip_ids,
            horizontal=body.horizontal,
            vertical=body.vertical,
            toggle_h=body.toggle_h,
            toggle_v=body.toggle_v,
        )
    except Exception as e:
        raise HTTPException(400, f"flip_selection failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class RotateSelectionBody(BaseModel):
    clip_ids: list[str]
    degrees: float = 90.0


@app.post("/api/edit/rotate_selection")
def rotate_selection_api(body: RotateSelectionBody) -> dict[str, Any]:
    """Rotate selection by degrees."""
    ed = _ed()
    try:
        r = ed.rotate_selection(body.clip_ids, body.degrees)
    except Exception as e:
        raise HTTPException(400, f"rotate_selection failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class SelectionCutReportBody(BaseModel):
    clip_ids: list[str]


@app.post("/api/edit/selection_cut_report")
def selection_cut_report_api(body: SelectionCutReportBody) -> dict[str, Any]:
    """Adjacent cut/gap report for selection."""
    ed = _ed()
    try:
        return ed.selection_cut_report(body.clip_ids)
    except Exception as e:
        raise HTTPException(400, f"selection_cut_report failed: {e}") from e


class CropSelectionCenterBody(BaseModel):
    clip_ids: list[str]
    scale: float = 0.85


@app.post("/api/edit/crop_selection_center")
def crop_selection_center_api(body: CropSelectionCenterBody) -> dict[str, Any]:
    """Center-crop selection to scale of project frame."""
    ed = _ed()
    try:
        r = ed.crop_selection_center(body.clip_ids, scale=body.scale)
    except Exception as e:
        raise HTTPException(400, f"crop_selection_center failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class VignetteSelectionBody(BaseModel):
    clip_ids: list[str]
    strength: float = 0.4


@app.post("/api/edit/vignette_selection")
def vignette_selection_api(body: VignetteSelectionBody) -> dict[str, Any]:
    """Apply vignette to selection."""
    ed = _ed()
    try:
        r = ed.vignette_selection(body.clip_ids, strength=body.strength)
    except Exception as e:
        raise HTTPException(400, f"vignette_selection failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class SelectionEffectsReportBody(BaseModel):
    clip_ids: list[str]


@app.post("/api/edit/selection_effects_report")
def selection_effects_report_api(body: SelectionEffectsReportBody) -> dict[str, Any]:
    """FX histogram + path-C mapped/unmapped for selection."""
    ed = _ed()
    try:
        return ed.selection_effects_report(body.clip_ids)
    except Exception as e:
        raise HTTPException(400, f"selection_effects_report failed: {e}") from e


class BlurSelectionBody(BaseModel):
    clip_ids: list[str]
    amount: float = 5.0


@app.post("/api/edit/blur_selection")
def blur_selection_api(body: BlurSelectionBody) -> dict[str, Any]:
    """Blur selection."""
    ed = _ed()
    try:
        r = ed.blur_selection(body.clip_ids, amount=body.amount)
    except Exception as e:
        raise HTTPException(400, f"blur_selection failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class SharpenSelectionBody(BaseModel):
    clip_ids: list[str]
    amount: float = 1.0


@app.post("/api/edit/sharpen_selection")
def sharpen_selection_api(body: SharpenSelectionBody) -> dict[str, Any]:
    """Sharpen selection."""
    ed = _ed()
    try:
        r = ed.sharpen_selection(body.clip_ids, amount=body.amount)
    except Exception as e:
        raise HTTPException(400, f"sharpen_selection failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class FilmGrainSelectionBody(BaseModel):
    clip_ids: list[str]
    amount: float = 12.0


@app.post("/api/edit/film_grain_selection")
def film_grain_selection_api(body: FilmGrainSelectionBody) -> dict[str, Any]:
    """Film grain on selection."""
    ed = _ed()
    try:
        r = ed.film_grain_selection(body.clip_ids, amount=body.amount)
    except Exception as e:
        raise HTTPException(400, f"film_grain_selection failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class GlowSelectionBody(BaseModel):
    clip_ids: list[str]
    amount: float = 8.0
    intensity: float = 0.4


@app.post("/api/edit/glow_selection")
def glow_selection_api(body: GlowSelectionBody) -> dict[str, Any]:
    """Glow on selection."""
    ed = _ed()
    try:
        r = ed.glow_selection(
            body.clip_ids, amount=body.amount, intensity=body.intensity,
        )
    except Exception as e:
        raise HTTPException(400, f"glow_selection failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class CurvesSelectionBody(BaseModel):
    clip_ids: list[str]
    preset: str = "increase_contrast"


@app.post("/api/edit/curves_selection")
def curves_selection_api(body: CurvesSelectionBody) -> dict[str, Any]:
    """Curves preset on selection."""
    ed = _ed()
    try:
        r = ed.curves_selection(body.clip_ids, preset=body.preset)
    except Exception as e:
        raise HTTPException(400, f"curves_selection failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class ChromaKeySelectionBody(BaseModel):
    clip_ids: list[str]
    color: str = "green"
    similarity: float = 0.15
    blend: float = 0.05


@app.post("/api/edit/chroma_key_selection")
def chroma_key_selection_api(body: ChromaKeySelectionBody) -> dict[str, Any]:
    """Chroma key on selection."""
    ed = _ed()
    try:
        r = ed.chroma_key_selection(
            body.clip_ids,
            color=body.color,
            similarity=body.similarity,
            blend=body.blend,
        )
    except Exception as e:
        raise HTTPException(400, f"chroma_key_selection failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class WhiteBalanceSelectionBody(BaseModel):
    clip_ids: list[str]
    temperature: float = 5600.0
    mix: float = 1.0


@app.post("/api/edit/white_balance_selection")
def white_balance_selection_api(body: WhiteBalanceSelectionBody) -> dict[str, Any]:
    """White balance on selection."""
    ed = _ed()
    try:
        r = ed.white_balance_selection(
            body.clip_ids,
            temperature=body.temperature,
            mix=body.mix,
        )
    except Exception as e:
        raise HTTPException(400, f"white_balance_selection failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class ClearSelectionEffectsBody(BaseModel):
    clip_ids: list[str]
    types: list[str] | None = None


@app.post("/api/edit/clear_selection_effects")
def clear_selection_effects_api(body: ClearSelectionEffectsBody) -> dict[str, Any]:
    """Clear effects on selection."""
    ed = _ed()
    try:
        r = ed.clear_selection_effects(body.clip_ids, types=body.types)
    except Exception as e:
        raise HTTPException(400, f"clear_selection_effects failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class StripSelectionPathCUnmappedBody(BaseModel):
    clip_ids: list[str]


@app.post("/api/edit/strip_selection_path_c_unmapped")
def strip_selection_path_c_unmapped_api(
    body: StripSelectionPathCUnmappedBody,
) -> dict[str, Any]:
    """Strip path-C unmapped FX from selection."""
    ed = _ed()
    try:
        r = ed.strip_selection_path_c_unmapped(body.clip_ids)
    except Exception as e:
        raise HTTPException(400, f"strip_selection_path_c_unmapped failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class CompressionSelectionBody(BaseModel):
    clip_ids: list[str]
    ratio: float = 4.0
    threshold_db: float = -18.0
    attack_ms: float = 20.0
    release_ms: float = 250.0
    makeup_db: float = 0.0


@app.post("/api/edit/compression_selection")
def compression_selection_api(body: CompressionSelectionBody) -> dict[str, Any]:
    """Audio compression on selection."""
    ed = _ed()
    try:
        r = ed.compression_selection(
            body.clip_ids,
            ratio=body.ratio,
            threshold_db=body.threshold_db,
            attack_ms=body.attack_ms,
            release_ms=body.release_ms,
            makeup_db=body.makeup_db,
        )
    except Exception as e:
        raise HTTPException(400, f"compression_selection failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class NoiseReductionSelectionBody(BaseModel):
    clip_ids: list[str]
    amount: float = 12.0


@app.post("/api/edit/noise_reduction_selection")
def noise_reduction_selection_api(body: NoiseReductionSelectionBody) -> dict[str, Any]:
    """Noise reduction on selection."""
    ed = _ed()
    try:
        r = ed.noise_reduction_selection(body.clip_ids, amount=body.amount)
    except Exception as e:
        raise HTTPException(400, f"noise_reduction_selection failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class AudioEqSelectionBody(BaseModel):
    clip_ids: list[str]
    frequency_hz: float = 1000.0
    gain_db: float = 0.0
    q: float = 1.0
    replace: bool = False


@app.post("/api/edit/audio_eq_selection")
def audio_eq_selection_api(body: AudioEqSelectionBody) -> dict[str, Any]:
    """Parametric EQ band on selection."""
    ed = _ed()
    try:
        r = ed.audio_eq_selection(
            body.clip_ids,
            frequency_hz=body.frequency_hz,
            gain_db=body.gain_db,
            q=body.q,
            replace=body.replace,
        )
    except Exception as e:
        raise HTTPException(400, f"audio_eq_selection failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class RazorSelectionMarkersBody(BaseModel):
    clip_ids: list[str]
    marker_ids: list[str] | None = None


@app.post("/api/edit/razor_selection_at_markers")
def razor_selection_at_markers_api(
    body: RazorSelectionMarkersBody,
) -> dict[str, Any]:
    """Razor selection at marker frames."""
    ed = _ed()
    try:
        r = ed.razor_selection_at_markers(
            body.clip_ids, marker_ids=body.marker_ids,
        )
    except Exception as e:
        raise HTTPException(400, f"razor_selection_at_markers failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class FreezeSelectionAtBody(BaseModel):
    clip_ids: list[str]
    timeline_frame: int
    duration_frames: int = 30


@app.post("/api/edit/freeze_selection_at")
def freeze_selection_at_api(body: FreezeSelectionAtBody) -> dict[str, Any]:
    """Freeze stills from selection at timeline frame."""
    ed = _ed()
    try:
        r = ed.freeze_selection_at(
            body.clip_ids,
            body.timeline_frame,
            duration_frames=body.duration_frames,
        )
    except Exception as e:
        raise HTTPException(400, f"freeze_selection_at failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class ExportSelectionAudioDefaultBody(BaseModel):
    clip_ids: list[str]
    filename: str = "selection_mix.wav"
    sample_rate: int | None = None


@app.post("/api/edit/export_selection_audio_default")
def export_selection_audio_default_api(
    body: ExportSelectionAudioDefaultBody,
) -> dict[str, Any]:
    """Export selection mix audio to exports/."""
    ed = _ed()
    try:
        return ed.export_selection_audio_default(
            body.clip_ids,
            filename=body.filename,
            sample_rate=body.sample_rate,
        )
    except Exception as e:
        raise HTTPException(400, f"export_selection_audio_default failed: {e}") from e


class SelectionProxyReportBody(BaseModel):
    clip_ids: list[str]


@app.post("/api/edit/selection_proxy_report")
def selection_proxy_report_api(body: SelectionProxyReportBody) -> dict[str, Any]:
    """Proxy readiness for selection media."""
    ed = _ed()
    try:
        return ed.selection_proxy_report(body.clip_ids)
    except Exception as e:
        raise HTTPException(400, f"selection_proxy_report failed: {e}") from e


class EnsureSelectionProxiesBody(BaseModel):
    clip_ids: list[str]
    height: int = 480
    force: bool = False


@app.post("/api/edit/ensure_selection_media_proxies")
def ensure_selection_media_proxies_api(
    body: EnsureSelectionProxiesBody,
) -> dict[str, Any]:
    """Build asset proxies for selection media."""
    ed = _ed()
    try:
        return ed.ensure_selection_media_proxies(
            body.clip_ids, height=body.height, force=body.force,
        )
    except Exception as e:
        raise HTTPException(400, f"ensure_selection_media_proxies failed: {e}") from e


class ExportSelectionMp4DefaultBody(BaseModel):
    clip_ids: list[str]
    filename: str = "selection.mp4"
    normalize_preset: str | None = None


@app.post("/api/edit/export_selection_mp4_default")
def export_selection_mp4_default_api(
    body: ExportSelectionMp4DefaultBody,
) -> dict[str, Any]:
    """Export selection span MP4 to exports/."""
    ed = _ed()
    try:
        return ed.export_selection_mp4_default(
            body.clip_ids,
            filename=body.filename,
            normalize_preset=body.normalize_preset,
        )
    except Exception as e:
        raise HTTPException(400, f"export_selection_mp4_default failed: {e}") from e


class ExportSelectionWebmDefaultBody(BaseModel):
    clip_ids: list[str]
    filename: str = "selection.webm"
    crf: int = 32
    width: int | None = None


@app.post("/api/edit/export_selection_webm_default")
def export_selection_webm_default_api(
    body: ExportSelectionWebmDefaultBody,
) -> dict[str, Any]:
    """Export selection span WebM to exports/."""
    ed = _ed()
    try:
        return ed.export_selection_webm_default(
            body.clip_ids,
            filename=body.filename,
            crf=body.crf,
            width=body.width,
        )
    except Exception as e:
        raise HTTPException(400, f"export_selection_webm_default failed: {e}") from e


class ExportSelectionGifDefaultBody(BaseModel):
    clip_ids: list[str]
    filename: str = "selection.gif"
    fps: float = 12.0
    width: int = 480
    max_duration_seconds: float = 12.0


@app.post("/api/edit/export_selection_gif_default")
def export_selection_gif_default_api(
    body: ExportSelectionGifDefaultBody,
) -> dict[str, Any]:
    """Export selection span GIF to exports/."""
    ed = _ed()
    try:
        return ed.export_selection_gif_default(
            body.clip_ids,
            filename=body.filename,
            fps=body.fps,
            width=body.width,
            max_duration_seconds=body.max_duration_seconds,
        )
    except Exception as e:
        raise HTTPException(400, f"export_selection_gif_default failed: {e}") from e


class WorkAreaFromSelectionBody(BaseModel):
    clip_ids: list[str]


@app.post("/api/edit/work_area_from_selection")
def work_area_from_selection_api(body: WorkAreaFromSelectionBody) -> dict[str, Any]:
    """Set work area In/Out from selection union."""
    ed = _ed()
    try:
        r = ed.work_area_from_selection(body.clip_ids)
    except Exception as e:
        raise HTTPException(400, f"work_area_from_selection failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class CopySelectionBody(BaseModel):
    clip_ids: list[str]


@app.post("/api/edit/copy_selection")
def copy_selection_api(body: CopySelectionBody) -> dict[str, Any]:
    """Copy selection to multi-clip clipboard."""
    ed = _ed()
    try:
        return ed.copy_selection(body.clip_ids)
    except Exception as e:
        raise HTTPException(400, f"copy_selection failed: {e}") from e


class PasteSelectionBody(BaseModel):
    start: int | None = None
    at_playhead: bool = False
    playhead_frame: int | None = None
    prefer_source_tracks: bool = True


@app.post("/api/edit/paste_selection")
def paste_selection_api(body: PasteSelectionBody) -> dict[str, Any]:
    """Paste multi-clip clipboard as rigid block."""
    ed = _ed()
    try:
        r = ed.paste_selection(
            start=body.start,
            at_playhead=body.at_playhead,
            playhead_frame=body.playhead_frame,
            prefer_source_tracks=body.prefer_source_tracks,
        )
    except Exception as e:
        raise HTTPException(400, f"paste_selection failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


@app.get("/api/edit/selection_clipboard_status")
def selection_clipboard_status_api() -> dict[str, Any]:
    """Multi-clip clipboard status."""
    return _ed().selection_clipboard_status()


class MarkersInSelectionSpanBody(BaseModel):
    clip_ids: list[str]


@app.post("/api/edit/markers_in_selection_span")
def markers_in_selection_span_api(body: MarkersInSelectionSpanBody) -> dict[str, Any]:
    """List markers inside selection span."""
    ed = _ed()
    try:
        return ed.markers_in_selection_span(body.clip_ids)
    except Exception as e:
        raise HTTPException(400, f"markers_in_selection_span failed: {e}") from e


class ClearMarkersInSelectionSpanBody(BaseModel):
    clip_ids: list[str]


@app.post("/api/edit/clear_markers_in_selection_span")
def clear_markers_in_selection_span_api(
    body: ClearMarkersInSelectionSpanBody,
) -> dict[str, Any]:
    """Remove markers inside selection span."""
    ed = _ed()
    try:
        r = ed.clear_markers_in_selection_span(body.clip_ids)
    except Exception as e:
        raise HTTPException(400, f"clear_markers_in_selection_span failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class ExportSelectionOtioBody(BaseModel):
    clip_ids: list[str]
    output_path: str | None = None
    title: str | None = None


@app.post("/api/edit/export_selection_otio")
def export_selection_otio_api(body: ExportSelectionOtioBody) -> dict[str, Any]:
    """Export selection as OTIO-like JSON."""
    ed = _ed()
    out = body.output_path
    if out is None:
        out = str(_desktop_export_dir() / "selection.otio.json")
    try:
        return ed.export_selection_otio_json(
            body.clip_ids, path=out, title=body.title,
        )
    except Exception as e:
        raise HTTPException(400, f"export_selection_otio failed: {e}") from e


class ExportSelectionEdlDefaultBody(BaseModel):
    clip_ids: list[str]
    filename: str = "selection.edl"
    title: str | None = None


@app.post("/api/edit/export_selection_edl_default")
def export_selection_edl_default_api(
    body: ExportSelectionEdlDefaultBody,
) -> dict[str, Any]:
    """Export selection EDL to exports/."""
    ed = _ed()
    try:
        return ed.export_selection_edl_default(
            body.clip_ids, filename=body.filename, title=body.title,
        )
    except Exception as e:
        raise HTTPException(400, f"export_selection_edl_default failed: {e}") from e


class ExportSelectionCutlistDefaultBody(BaseModel):
    clip_ids: list[str]
    filename: str = "selection_cutlist.csv"
    format: str = "csv"


@app.post("/api/edit/export_selection_cutlist_default")
def export_selection_cutlist_default_api(
    body: ExportSelectionCutlistDefaultBody,
) -> dict[str, Any]:
    """Export selection cutlist to exports/."""
    ed = _ed()
    try:
        return ed.export_selection_cutlist_default(
            body.clip_ids, filename=body.filename, format=body.format,
        )
    except Exception as e:
        raise HTTPException(400, f"export_selection_cutlist_default failed: {e}") from e


class ExportSelectionFcpxmlBody(BaseModel):
    clip_ids: list[str]
    output_path: str | None = None
    title: str | None = None


@app.post("/api/edit/export_selection_fcpxml")
def export_selection_fcpxml_api(body: ExportSelectionFcpxmlBody) -> dict[str, Any]:
    """Export selection FCPXML to exports/ by default."""
    ed = _ed()
    out = body.output_path
    if out is None:
        try:
            return ed.export_selection_fcpxml_default(
                body.clip_ids, title=body.title,
            )
        except Exception as e:
            raise HTTPException(400, f"export_selection_fcpxml failed: {e}") from e
    try:
        return ed.export_selection_fcpxml(
            body.clip_ids, path=out, title=body.title,
        )
    except Exception as e:
        raise HTTPException(400, f"export_selection_fcpxml failed: {e}") from e


class SelectionExportPreflightBody(BaseModel):
    clip_ids: list[str]
    set_work_area: bool = True


@app.post("/api/edit/selection_export_preflight")
def selection_export_preflight_api(
    body: SelectionExportPreflightBody,
) -> dict[str, Any]:
    """Preflight selection before export."""
    ed = _ed()
    try:
        r = ed.selection_export_preflight(
            body.clip_ids, set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(400, f"selection_export_preflight failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class SelectionOfflineMediaBody(BaseModel):
    clip_ids: list[str]


@app.post("/api/edit/selection_offline_media")
def selection_offline_media_api(body: SelectionOfflineMediaBody) -> dict[str, Any]:
    """List offline media in selection."""
    ed = _ed()
    try:
        return ed.selection_offline_media(body.clip_ids)
    except Exception as e:
        raise HTTPException(400, f"selection_offline_media failed: {e}") from e


class SelectionLockedTracksBody(BaseModel):
    clip_ids: list[str]


@app.post("/api/edit/selection_locked_tracks")
def selection_locked_tracks_api(body: SelectionLockedTracksBody) -> dict[str, Any]:
    """List locked tracks touched by selection."""
    ed = _ed()
    try:
        return ed.selection_locked_tracks(body.clip_ids)
    except Exception as e:
        raise HTTPException(400, f"selection_locked_tracks failed: {e}") from e


class UnlockSelectionTracksBody(BaseModel):
    clip_ids: list[str]


@app.post("/api/edit/unlock_selection_tracks")
def unlock_selection_tracks_api(body: UnlockSelectionTracksBody) -> dict[str, Any]:
    """Unlock tracks touched by selection."""
    ed = _ed()
    try:
        r = ed.unlock_selection_tracks(body.clip_ids)
    except Exception as e:
        raise HTTPException(400, f"unlock_selection_tracks failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class LockSelectionTracksBody(BaseModel):
    clip_ids: list[str]


@app.post("/api/edit/lock_selection_tracks")
def lock_selection_tracks_api(body: LockSelectionTracksBody) -> dict[str, Any]:
    """Lock tracks touched by selection."""
    ed = _ed()
    try:
        r = ed.lock_selection_tracks(body.clip_ids)
    except Exception as e:
        raise HTTPException(400, f"lock_selection_tracks failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class MuteSelectionTracksBody(BaseModel):
    clip_ids: list[str]
    muted: bool = True


@app.post("/api/edit/mute_selection_tracks")
def mute_selection_tracks_api(body: MuteSelectionTracksBody) -> dict[str, Any]:
    """Mute/unmute tracks touched by selection."""
    ed = _ed()
    try:
        r = ed.mute_selection_tracks(body.clip_ids, muted=body.muted)
    except Exception as e:
        raise HTTPException(400, f"mute_selection_tracks failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class SoloSelectionTracksBody(BaseModel):
    clip_ids: list[str]
    exclusive: bool = True


@app.post("/api/edit/solo_selection_tracks")
def solo_selection_tracks_api(body: SoloSelectionTracksBody) -> dict[str, Any]:
    """Solo tracks touched by selection."""
    ed = _ed()
    try:
        r = ed.solo_selection_tracks(
            body.clip_ids, exclusive=body.exclusive,
        )
    except Exception as e:
        raise HTTPException(400, f"solo_selection_tracks failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class UnsoloSelectionTracksBody(BaseModel):
    clip_ids: list[str]


@app.post("/api/edit/unsolo_selection_tracks")
def unsolo_selection_tracks_api(body: UnsoloSelectionTracksBody) -> dict[str, Any]:
    """Clear solo on selection tracks."""
    ed = _ed()
    try:
        r = ed.unsolo_selection_tracks(body.clip_ids)
    except Exception as e:
        raise HTTPException(400, f"unsolo_selection_tracks failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class SelectionTrackStatesBody(BaseModel):
    clip_ids: list[str]


@app.post("/api/edit/selection_track_states")
def selection_track_states_api(body: SelectionTrackStatesBody) -> dict[str, Any]:
    """Track mute/solo/lock for selection lanes."""
    ed = _ed()
    try:
        return ed.selection_track_states(body.clip_ids)
    except Exception as e:
        raise HTTPException(400, f"selection_track_states failed: {e}") from e


class RaiseSelectionTracksBody(BaseModel):
    clip_ids: list[str]
    steps: int = 1


@app.post("/api/edit/raise_selection_tracks")
def raise_selection_tracks_api(body: RaiseSelectionTracksBody) -> dict[str, Any]:
    """Raise selection tracks in z-order."""
    ed = _ed()
    try:
        r = ed.raise_selection_tracks(body.clip_ids, steps=body.steps)
    except Exception as e:
        raise HTTPException(400, f"raise_selection_tracks failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class LowerSelectionTracksBody(BaseModel):
    clip_ids: list[str]
    steps: int = 1


@app.post("/api/edit/lower_selection_tracks")
def lower_selection_tracks_api(body: LowerSelectionTracksBody) -> dict[str, Any]:
    """Lower selection tracks in z-order."""
    ed = _ed()
    try:
        r = ed.lower_selection_tracks(body.clip_ids, steps=body.steps)
    except Exception as e:
        raise HTTPException(400, f"lower_selection_tracks failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class RenameSelectionTracksBody(BaseModel):
    clip_ids: list[str]
    name: str | None = None
    prefix: str | None = None
    suffix: str | None = None


@app.post("/api/edit/rename_selection_tracks")
def rename_selection_tracks_api(body: RenameSelectionTracksBody) -> dict[str, Any]:
    """Rename tracks touched by selection."""
    ed = _ed()
    try:
        r = ed.rename_selection_tracks(
            body.clip_ids,
            name=body.name,
            prefix=body.prefix,
            suffix=body.suffix,
        )
    except Exception as e:
        raise HTTPException(400, f"rename_selection_tracks failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class ExportSelectionStillsBody(BaseModel):
    clip_ids: list[str]
    output_dir: str | None = None
    edge: str = "mid"
    width: int = 640
    ext: str = "jpg"


@app.post("/api/edit/export_selection_stills")
def export_selection_stills_api(body: ExportSelectionStillsBody) -> dict[str, Any]:
    """Export stills from each selected clip."""
    ed = _ed()
    try:
        return ed.export_selection_stills(
            body.clip_ids,
            output_dir=body.output_dir,
            edge=body.edge,
            width=body.width,
            ext=body.ext,
        )
    except Exception as e:
        raise HTTPException(400, f"export_selection_stills failed: {e}") from e


class SelectionPathCStillsPlanBody(BaseModel):
    clip_ids: list[str]
    height: int = 360


@app.post("/api/edit/selection_path_c_stills_plan")
def selection_path_c_stills_plan_api(
    body: SelectionPathCStillsPlanBody,
) -> dict[str, Any]:
    """path-C plan summary for selection stills workflow."""
    ed = _ed()
    try:
        return ed.selection_path_c_stills_plan(
            body.clip_ids, height=body.height,
        )
    except Exception as e:
        raise HTTPException(400, f"selection_path_c_stills_plan failed: {e}") from e


class SelectionContactSheetBody(BaseModel):
    clip_ids: list[str]
    output_path: str | None = None
    max_tiles: int = 12
    tile_width: int = 160
    tile_height: int = 90
    cols: int | None = None


@app.post("/api/edit/make_selection_contact_sheet")
def make_selection_contact_sheet_api(
    body: SelectionContactSheetBody,
) -> dict[str, Any]:
    """Contact sheet grid from selection mid-frames."""
    ed = _ed()
    try:
        return ed.make_selection_contact_sheet(
            body.clip_ids,
            output_path=body.output_path,
            max_tiles=body.max_tiles,
            tile_width=body.tile_width,
            tile_height=body.tile_height,
            cols=body.cols,
        )
    except Exception as e:
        raise HTTPException(400, f"make_selection_contact_sheet failed: {e}") from e


class AnalyzeSelectionAudioBody(BaseModel):
    clip_ids: list[str]
    image_path: str | None = None
    silence_threshold_db: float = -40.0
    min_silence_seconds: float = 0.5
    filename: str = "selection_mix_analyze.wav"


@app.post("/api/edit/analyze_selection_audio")
def analyze_selection_audio_api(body: AnalyzeSelectionAudioBody) -> dict[str, Any]:
    """Meter selection union mix audio."""
    ed = _ed()
    try:
        return ed.analyze_selection_audio(
            body.clip_ids,
            image_path=body.image_path,
            silence_threshold_db=body.silence_threshold_db,
            min_silence_seconds=body.min_silence_seconds,
            filename=body.filename,
        )
    except Exception as e:
        raise HTTPException(400, f"analyze_selection_audio failed: {e}") from e


class ReviewSelectionBody(BaseModel):
    clip_ids: list[str]
    min_clip_seconds: float = 0.4


@app.post("/api/edit/review_selection")
def review_selection_api(body: ReviewSelectionBody) -> dict[str, Any]:
    """Craft review scoped to selection."""
    ed = _ed()
    try:
        return ed.review_selection(
            body.clip_ids, min_clip_seconds=body.min_clip_seconds,
        )
    except Exception as e:
        raise HTTPException(400, f"review_selection failed: {e}") from e


class SelectionClipDurationsBody(BaseModel):
    clip_ids: list[str]


@app.post("/api/edit/selection_clip_durations")
def selection_clip_durations_api(body: SelectionClipDurationsBody) -> dict[str, Any]:
    """Per-clip durations for selection."""
    ed = _ed()
    try:
        return ed.selection_clip_durations(body.clip_ids)
    except Exception as e:
        raise HTTPException(400, f"selection_clip_durations failed: {e}") from e


class ExportSelectionPreviewBody(BaseModel):
    clip_ids: list[str]
    output_path: str | None = None
    height: int = 360
    fps: float = 12.0


@app.post("/api/edit/export_selection_preview")
def export_selection_preview_api(body: ExportSelectionPreviewBody) -> dict[str, Any]:
    """Low-res selection span preview."""
    ed = _ed()
    try:
        return ed.export_selection_preview(
            body.clip_ids,
            output_path=body.output_path,
            height=body.height,
            fps=body.fps,
        )
    except Exception as e:
        raise HTTPException(400, f"export_selection_preview failed: {e}") from e


class PrepareSelectionExportBody(BaseModel):
    clip_ids: list[str]
    unlock_tracks: bool = True
    set_work_area: bool = True
    pack_gaps: bool = False
    gap_frames: int = 0


@app.post("/api/edit/prepare_selection_export")
def prepare_selection_export_api(body: PrepareSelectionExportBody) -> dict[str, Any]:
    """Unlock/pack/work-area + preflight for selection export."""
    ed = _ed()
    try:
        r = ed.prepare_selection_export(
            body.clip_ids,
            unlock_tracks=body.unlock_tracks,
            set_work_area=body.set_work_area,
            pack_gaps=body.pack_gaps,
            gap_frames=body.gap_frames,
        )
    except Exception as e:
        raise HTTPException(400, f"prepare_selection_export failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class SelectionWaveformsBody(BaseModel):
    clip_ids: list[str]
    num_peaks: int = 200
    use_cache: bool = True


@app.post("/api/edit/selection_waveforms")
def selection_waveforms_api(body: SelectionWaveformsBody) -> dict[str, Any]:
    """Waveform peaks for selection clips with audio."""
    ed = _ed()
    try:
        return ed.selection_waveforms(
            body.clip_ids,
            num_peaks=body.num_peaks,
            use_cache=body.use_cache,
        )
    except Exception as e:
        raise HTTPException(400, f"selection_waveforms failed: {e}") from e


class ExportSelectionManifestBody(BaseModel):
    clip_ids: list[str]
    output_path: str | None = None


@app.post("/api/edit/export_selection_manifest")
def export_selection_manifest_api(
    body: ExportSelectionManifestBody,
) -> dict[str, Any]:
    """Export selection agent manifest JSON."""
    ed = _ed()
    try:
        return ed.export_selection_manifest(
            body.clip_ids, path=body.output_path,
        )
    except Exception as e:
        raise HTTPException(400, f"export_selection_manifest failed: {e}") from e


class SplitSelectionSilencesBody(BaseModel):
    clip_ids: list[str]
    noise_db: float = -30.0
    min_duration: float = 0.25
    max_splits: int = 40
    mark: str = "start"


@app.post("/api/edit/split_selection_at_silences")
def split_selection_at_silences_api(
    body: SplitSelectionSilencesBody,
) -> dict[str, Any]:
    """Razor selection at silence edges."""
    ed = _ed()
    try:
        r = ed.split_selection_at_silences(
            body.clip_ids,
            noise_db=body.noise_db,
            min_duration=body.min_duration,
            max_splits=body.max_splits,
            mark=body.mark,
        )
    except Exception as e:
        raise HTTPException(400, f"split_selection_at_silences failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class SuggestSilenceCutsSelectionBody(BaseModel):
    clip_ids: list[str]
    silence_threshold_db: float = -40.0
    min_silence_seconds: float = 0.4
    pad_seconds: float = 0.08
    min_keep_seconds: float = 0.2


@app.post("/api/edit/suggest_silence_cuts_selection")
def suggest_silence_cuts_selection_api(
    body: SuggestSilenceCutsSelectionBody,
) -> dict[str, Any]:
    """Suggest silence keep_ranges for selection media."""
    ed = _ed()
    try:
        return ed.suggest_silence_cuts_selection(
            body.clip_ids,
            silence_threshold_db=body.silence_threshold_db,
            min_silence_seconds=body.min_silence_seconds,
            pad_seconds=body.pad_seconds,
            min_keep_seconds=body.min_keep_seconds,
        )
    except Exception as e:
        raise HTTPException(400, f"suggest_silence_cuts_selection failed: {e}") from e


class ApplySilenceSelectionBody(BaseModel):
    clip_ids: list[str]
    silence_threshold_db: float = -40.0
    min_silence_seconds: float = 0.4
    pad_seconds: float = 0.08
    min_keep_seconds: float = 0.2
    dry_run: bool = True


@app.post("/api/edit/apply_silence_to_selection")
def apply_silence_to_selection_api(
    body: ApplySilenceSelectionBody,
) -> dict[str, Any]:
    """Suggest or apply silence trims on selection."""
    ed = _ed()
    try:
        r = ed.apply_silence_to_selection(
            body.clip_ids,
            silence_threshold_db=body.silence_threshold_db,
            min_silence_seconds=body.min_silence_seconds,
            pad_seconds=body.pad_seconds,
            min_keep_seconds=body.min_keep_seconds,
            dry_run=body.dry_run,
        )
    except Exception as e:
        raise HTTPException(400, f"apply_silence_to_selection failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class DeliveryCheckSelectionBody(BaseModel):
    clip_ids: list[str]
    filename: str = "selection_delivery.mp4"
    preset: str = "streaming"
    normalize_preset: str | None = None


@app.post("/api/edit/delivery_check_selection")
def delivery_check_selection_api(body: DeliveryCheckSelectionBody) -> dict[str, Any]:
    """Export selection then delivery_check."""
    ed = _ed()
    try:
        return ed.delivery_check_selection(
            body.clip_ids,
            filename=body.filename,
            preset=body.preset,
            normalize_preset=body.normalize_preset,
        )
    except Exception as e:
        raise HTTPException(400, f"delivery_check_selection failed: {e}") from e


class ExportSelectionPathCPlanDefaultBody(BaseModel):
    clip_ids: list[str]
    filename: str = "selection_path_c_plan.json"
    height: int = 360
    include_audio: bool = False


@app.post("/api/edit/export_selection_path_c_plan_default")
def export_selection_path_c_plan_default_api(
    body: ExportSelectionPathCPlanDefaultBody,
) -> dict[str, Any]:
    """Write path-C selection plan JSON under exports/."""
    ed = _ed()
    try:
        return ed.export_selection_path_c_plan_default(
            body.clip_ids,
            filename=body.filename,
            height=body.height,
            include_audio=body.include_audio,
        )
    except Exception as e:
        raise HTTPException(
            400, f"export_selection_path_c_plan_default failed: {e}",
        ) from e


class FinishSelectionDeliveryBody(BaseModel):
    clip_ids: list[str]
    filename: str = "selection_delivery.mp4"
    prepare: bool = True
    unlock_tracks: bool = True
    set_work_area: bool = True
    pack_gaps: bool = False
    run_review: bool = True
    write_manifest: bool = True
    normalize_preset: str | None = "streaming"
    delivery_preset: str = "streaming"


@app.post("/api/edit/finish_selection_delivery")
def finish_selection_delivery_api(
    body: FinishSelectionDeliveryBody,
) -> dict[str, Any]:
    """Prepare + review + export selection with delivery gates."""
    ed = _ed()
    try:
        return ed.finish_selection_delivery(
            body.clip_ids,
            filename=body.filename,
            prepare=body.prepare,
            unlock_tracks=body.unlock_tracks,
            set_work_area=body.set_work_area,
            pack_gaps=body.pack_gaps,
            run_review=body.run_review,
            write_manifest=body.write_manifest,
            normalize_preset=body.normalize_preset,
            delivery_preset=body.delivery_preset,
        )
    except Exception as e:
        raise HTTPException(
            400, f"finish_selection_delivery failed: {e}",
        ) from e


class ExportSelectionOtioDefaultBody(BaseModel):
    clip_ids: list[str]
    filename: str = "selection.otio.json"
    title: str | None = None


@app.post("/api/edit/export_selection_otio_default")
def export_selection_otio_default_api(
    body: ExportSelectionOtioDefaultBody,
) -> dict[str, Any]:
    """Write selection OTIO-like JSON under exports/."""
    ed = _ed()
    try:
        return ed.export_selection_otio_default(
            body.clip_ids,
            filename=body.filename,
            title=body.title,
        )
    except Exception as e:
        raise HTTPException(
            400, f"export_selection_otio_default failed: {e}",
        ) from e


class SelectionAgentPreflightBody(BaseModel):
    clip_ids: list[str]
    set_work_area: bool = False
    min_clip_seconds: float = 0.4


@app.post("/api/edit/selection_agent_preflight")
def selection_agent_preflight_api(
    body: SelectionAgentPreflightBody,
) -> dict[str, Any]:
    """Agent preflight for selection (read-only by default)."""
    ed = _ed()
    try:
        return ed.selection_agent_preflight(
            body.clip_ids,
            set_work_area=body.set_work_area,
            min_clip_seconds=body.min_clip_seconds,
        )
    except Exception as e:
        raise HTTPException(
            400, f"selection_agent_preflight failed: {e}",
        ) from e


class ExportSelectionManifestDefaultBody(BaseModel):
    clip_ids: list[str]
    filename: str = "selection_manifest.json"


@app.post("/api/edit/export_selection_manifest_default")
def export_selection_manifest_default_api(
    body: ExportSelectionManifestDefaultBody,
) -> dict[str, Any]:
    """Write selection agent manifest under exports/."""
    ed = _ed()
    try:
        return ed.export_selection_manifest_default(
            body.clip_ids,
            filename=body.filename,
        )
    except Exception as e:
        raise HTTPException(
            400, f"export_selection_manifest_default failed: {e}",
        ) from e


class ExportSelectionMarkersDefaultBody(BaseModel):
    clip_ids: list[str]
    filename: str | None = None
    format: str = "json"


@app.post("/api/edit/export_selection_markers_default")
def export_selection_markers_default_api(
    body: ExportSelectionMarkersDefaultBody,
) -> dict[str, Any]:
    """Export markers inside selection span under exports/."""
    ed = _ed()
    try:
        return ed.export_selection_markers_default(
            body.clip_ids,
            filename=body.filename,
            format=body.format,
        )
    except Exception as e:
        raise HTTPException(
            400, f"export_selection_markers_default failed: {e}",
        ) from e


class ExportWorkAreaMp4DefaultBody(BaseModel):
    filename: str = "work_area.mp4"
    normalize_preset: str | None = "streaming"
    run_delivery_check: bool = True
    delivery_preset: str = "streaming"


@app.post("/api/edit/export_work_area_mp4_default")
def export_work_area_mp4_default_api(
    body: ExportWorkAreaMp4DefaultBody,
) -> dict[str, Any]:
    """Export in/out work area MP4 under exports/."""
    ed = _ed()
    try:
        return ed.export_work_area_mp4_default(
            filename=body.filename,
            normalize_preset=body.normalize_preset,
            run_delivery_check=body.run_delivery_check,
            delivery_preset=body.delivery_preset,
        )
    except Exception as e:
        raise HTTPException(
            400, f"export_work_area_mp4_default failed: {e}",
        ) from e


class ExportSelectionPathCStillsPlanDefaultBody(BaseModel):
    clip_ids: list[str]
    filename: str = "selection_path_c_stills_plan.json"
    height: int = 360


@app.post("/api/edit/export_selection_path_c_stills_plan_default")
def export_selection_path_c_stills_plan_default_api(
    body: ExportSelectionPathCStillsPlanDefaultBody,
) -> dict[str, Any]:
    """Write path-C stills plan for selection under exports/."""
    ed = _ed()
    try:
        return ed.export_selection_path_c_stills_plan_default(
            body.clip_ids,
            filename=body.filename,
            height=body.height,
        )
    except Exception as e:
        raise HTTPException(
            400, f"export_selection_path_c_stills_plan_default failed: {e}",
        ) from e


class ExportWorkAreaWebmDefaultBody(BaseModel):
    filename: str = "work_area.webm"
    crf: int = 32
    width: int | None = 720


@app.post("/api/edit/export_work_area_webm_default")
def export_work_area_webm_default_api(
    body: ExportWorkAreaWebmDefaultBody,
) -> dict[str, Any]:
    """Export in/out work area WebM under exports/."""
    ed = _ed()
    try:
        return ed.export_work_area_webm_default(
            filename=body.filename,
            crf=body.crf,
            width=body.width,
        )
    except Exception as e:
        raise HTTPException(
            400, f"export_work_area_webm_default failed: {e}",
        ) from e


class ExportWorkAreaGifDefaultBody(BaseModel):
    filename: str = "work_area.gif"
    fps: float = 12.0
    width: int = 480
    max_duration_seconds: float = 15.0


@app.post("/api/edit/export_work_area_gif_default")
def export_work_area_gif_default_api(
    body: ExportWorkAreaGifDefaultBody,
) -> dict[str, Any]:
    """Export in/out work area GIF under exports/."""
    ed = _ed()
    try:
        return ed.export_work_area_gif_default(
            filename=body.filename,
            fps=body.fps,
            width=body.width,
            max_duration_seconds=body.max_duration_seconds,
        )
    except Exception as e:
        raise HTTPException(
            400, f"export_work_area_gif_default failed: {e}",
        ) from e


class FinishWorkAreaDeliveryBody(BaseModel):
    filename: str = "work_area_delivery.mp4"
    prepare: bool = True
    fill_video: bool = True
    fill_audio: bool = False
    run_review: bool = True
    normalize_preset: str | None = "streaming"
    delivery_preset: str = "streaming"


@app.post("/api/edit/finish_work_area_delivery")
def finish_work_area_delivery_api(
    body: FinishWorkAreaDeliveryBody,
) -> dict[str, Any]:
    """Prepare + export work area with delivery gates."""
    ed = _ed()
    try:
        return ed.finish_work_area_delivery(
            filename=body.filename,
            prepare=body.prepare,
            fill_video=body.fill_video,
            fill_audio=body.fill_audio,
            run_review=body.run_review,
            normalize_preset=body.normalize_preset,
            delivery_preset=body.delivery_preset,
        )
    except Exception as e:
        raise HTTPException(
            400, f"finish_work_area_delivery failed: {e}",
        ) from e


class StabilizeSelectionBody(BaseModel):
    clip_ids: list[str]
    replace: bool = True
    strength: float = 1.0
    video_only: bool = True


@app.post("/api/edit/stabilize_selection")
def stabilize_selection_api(body: StabilizeSelectionBody) -> dict[str, Any]:
    """Batch deshake stabilize on selection video clips."""
    ed = _ed()
    try:
        r = ed.stabilize_selection(
            body.clip_ids,
            replace=body.replace,
            strength=body.strength,
            video_only=body.video_only,
        )
    except Exception as e:
        raise HTTPException(400, f"stabilize_selection failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class ExportSelectionMarkersSrtBody(BaseModel):
    clip_ids: list[str]
    filename: str = "selection_markers.srt"
    cue_seconds: float = 2.0
    relative: bool = True


@app.post("/api/edit/export_selection_markers_srt")
def export_selection_markers_srt_api(
    body: ExportSelectionMarkersSrtBody,
) -> dict[str, Any]:
    """Export selection-span markers as SRT under exports/."""
    ed = _ed()
    try:
        return ed.export_selection_markers_srt(
            body.clip_ids,
            filename=body.filename,
            cue_seconds=body.cue_seconds,
            relative=body.relative,
        )
    except Exception as e:
        raise HTTPException(
            400, f"export_selection_markers_srt failed: {e}",
        ) from e


class EnsureSelectionProxiesBody(BaseModel):
    clip_ids: list[str]
    height: int = 360
    force: bool = False


@app.post("/api/edit/ensure_selection_proxies")
def ensure_selection_proxies_api(
    body: EnsureSelectionProxiesBody,
) -> dict[str, Any]:
    """Build media proxies for assets used by selection."""
    ed = _ed()
    try:
        return ed.ensure_selection_proxies(
            body.clip_ids,
            height=body.height,
            force=body.force,
        )
    except Exception as e:
        raise HTTPException(
            400, f"ensure_selection_proxies failed: {e}",
        ) from e


class ExportSelectionContactSheetDefaultBody(BaseModel):
    clip_ids: list[str]
    filename: str = "selection_contact.jpg"
    max_tiles: int = 12
    tile_width: int = 160
    tile_height: int = 90
    cols: int | None = None


@app.post("/api/edit/export_selection_contact_sheet_default")
def export_selection_contact_sheet_default_api(
    body: ExportSelectionContactSheetDefaultBody,
) -> dict[str, Any]:
    """Write selection contact sheet under exports/."""
    ed = _ed()
    try:
        return ed.export_selection_contact_sheet_default(
            body.clip_ids,
            filename=body.filename,
            max_tiles=body.max_tiles,
            tile_width=body.tile_width,
            tile_height=body.tile_height,
            cols=body.cols,
        )
    except Exception as e:
        raise HTTPException(
            400, f"export_selection_contact_sheet_default failed: {e}",
        ) from e


class ExportSelectionToSizeBody(BaseModel):
    clip_ids: list[str]
    output_path: str | None = None
    width: int = 1080
    height: int = 1920
    fit: str = "cover"
    normalize_preset: str | None = None
    filename: str = "selection_sized.mp4"


@app.post("/api/edit/export_selection_to_size")
def export_selection_to_size_api(
    body: ExportSelectionToSizeBody,
) -> dict[str, Any]:
    """Export selection then scale to a social canvas size."""
    ed = _ed()
    try:
        return ed.export_selection_to_size(
            body.clip_ids,
            body.output_path,
            width=body.width,
            height=body.height,
            fit=body.fit,
            normalize_preset=body.normalize_preset,
            filename=body.filename,
        )
    except Exception as e:
        raise HTTPException(
            400, f"export_selection_to_size failed: {e}",
        ) from e


class ExportSelectionSocialPackBody(BaseModel):
    clip_ids: list[str]
    out_dir: str | None = None
    variants: list[str] | None = None
    normalize_preset: str | None = None
    name_prefix: str = "selection"


@app.post("/api/edit/export_selection_social_pack")
def export_selection_social_pack_api(
    body: ExportSelectionSocialPackBody,
) -> dict[str, Any]:
    """Export selection to youtube/reels/square (or custom) pack."""
    ed = _ed()
    try:
        return ed.export_selection_social_pack(
            body.clip_ids,
            out_dir=body.out_dir,
            variants=body.variants,
            normalize_preset=body.normalize_preset,
            name_prefix=body.name_prefix,
        )
    except Exception as e:
        raise HTTPException(
            400, f"export_selection_social_pack failed: {e}",
        ) from e


class ReframeSelectionBody(BaseModel):
    clip_ids: list[str]
    aspect: str = "9:16"
    anchor: str = "center"
    video_only: bool = True


@app.post("/api/edit/reframe_selection")
def reframe_selection_api(body: ReframeSelectionBody) -> dict[str, Any]:
    """Crop-reframe selection clips to a target aspect."""
    ed = _ed()
    try:
        r = ed.reframe_selection(
            body.clip_ids,
            aspect=body.aspect,
            anchor=body.anchor,
            video_only=body.video_only,
        )
    except Exception as e:
        raise HTTPException(400, f"reframe_selection failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class ExportSelectionSocialBody(BaseModel):
    clip_ids: list[str]
    variant: str = "reels"
    filename: str | None = None
    normalize_preset: str | None = None


@app.post("/api/edit/export_selection_social")
def export_selection_social_api(
    body: ExportSelectionSocialBody,
) -> dict[str, Any]:
    """Export selection to one named social canvas under exports/."""
    ed = _ed()
    try:
        return ed.export_selection_social(
            body.clip_ids,
            variant=body.variant,
            filename=body.filename,
            normalize_preset=body.normalize_preset,
        )
    except Exception as e:
        raise HTTPException(
            400, f"export_selection_social failed: {e}",
        ) from e


class ExportSelectionWithPresetBody(BaseModel):
    clip_ids: list[str]
    preset: str = "streaming"
    filename: str | None = None
    prepare: bool | None = None


@app.post("/api/edit/export_selection_with_preset")
def export_selection_with_preset_api(
    body: ExportSelectionWithPresetBody,
) -> dict[str, Any]:
    """Export selection with a named EXPORT_PRESETS recipe."""
    ed = _ed()
    try:
        return ed.export_selection_with_preset(
            body.clip_ids,
            preset=body.preset,
            filename=body.filename,
            prepare=body.prepare,
        )
    except Exception as e:
        raise HTTPException(
            400, f"export_selection_with_preset failed: {e}",
        ) from e


class ExportSelectionWithBurninsBody(BaseModel):
    clip_ids: list[str]
    filename: str = "selection_review.mp4"
    timecode: bool = True
    safe_area: bool = True
    watermark: str | None = None
    timecode_start: str = "00:00:00:00"
    normalize_preset: str | None = None


@app.post("/api/edit/export_selection_with_burnins")
def export_selection_with_burnins_api(
    body: ExportSelectionWithBurninsBody,
) -> dict[str, Any]:
    """Export selection review master with burn-in overlays."""
    ed = _ed()
    try:
        return ed.export_selection_with_burnins(
            body.clip_ids,
            filename=body.filename,
            timecode=body.timecode,
            safe_area=body.safe_area,
            watermark=body.watermark,
            timecode_start=body.timecode_start,
            normalize_preset=body.normalize_preset,
        )
    except Exception as e:
        raise HTTPException(
            400, f"export_selection_with_burnins failed: {e}",
        ) from e


class ExportSelectionPresetsPackBody(BaseModel):
    clip_ids: list[str]
    out_dir: str | None = None
    presets: list[str] | None = None
    name_prefix: str = "selection"
    prepare: bool | None = False


@app.post("/api/edit/export_selection_presets_pack")
def export_selection_presets_pack_api(
    body: ExportSelectionPresetsPackBody,
) -> dict[str, Any]:
    """Export selection with multiple named presets into a folder."""
    ed = _ed()
    try:
        return ed.export_selection_presets_pack(
            body.clip_ids,
            out_dir=body.out_dir,
            presets=body.presets,
            name_prefix=body.name_prefix,
            prepare=body.prepare,
        )
    except Exception as e:
        raise HTTPException(
            400, f"export_selection_presets_pack failed: {e}",
        ) from e


class FinishSelectionSocialBody(BaseModel):
    clip_ids: list[str]
    variant: str = "reels"
    reframe: bool = True
    aspect: str | None = None
    anchor: str = "center"
    prepare: bool = True
    unlock_tracks: bool = True
    set_work_area: bool = True
    pack_gaps: bool = False
    run_review: bool = True
    normalize_preset: str | None = "streaming"
    delivery_preset: str = "streaming"
    filename: str | None = None


@app.post("/api/edit/finish_selection_social")
def finish_selection_social_api(
    body: FinishSelectionSocialBody,
) -> dict[str, Any]:
    """Selection social finish pipeline."""
    ed = _ed()
    try:
        r = ed.finish_selection_social(
            body.clip_ids,
            variant=body.variant,
            reframe=body.reframe,
            aspect=body.aspect,
            anchor=body.anchor,
            prepare=body.prepare,
            unlock_tracks=body.unlock_tracks,
            set_work_area=body.set_work_area,
            pack_gaps=body.pack_gaps,
            run_review=body.run_review,
            normalize_preset=body.normalize_preset,
            delivery_preset=body.delivery_preset,
            filename=body.filename,
        )
    except Exception as e:
        raise HTTPException(
            400, f"finish_selection_social failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ColorMatchSelectionBody(BaseModel):
    clip_ids: list[str]
    reference_clip_id: str | None = None
    strength: float = 0.65
    video_only: bool = True


@app.post("/api/edit/color_match_selection")
def color_match_selection_api(body: ColorMatchSelectionBody) -> dict[str, Any]:
    """Color-match selection toward a reference clip."""
    ed = _ed()
    try:
        r = ed.color_match_selection(
            body.clip_ids,
            reference_clip_id=body.reference_clip_id,
            strength=body.strength,
            video_only=body.video_only,
        )
    except Exception as e:
        raise HTTPException(
            400, f"color_match_selection failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ExportSelectionMarkerSegmentsBody(BaseModel):
    clip_ids: list[str]
    out_dir: str | None = None
    name_prefix: str = "sel_seg"
    include_tail: bool = True
    min_duration_frames: int = 3
    filename_from_label: bool = True
    normalize_preset: str | None = None


@app.post("/api/edit/export_selection_marker_segments")
def export_selection_marker_segments_api(
    body: ExportSelectionMarkerSegmentsBody,
) -> dict[str, Any]:
    """Export marker segments within selection span."""
    ed = _ed()
    try:
        return ed.export_selection_marker_segments(
            body.clip_ids,
            out_dir=body.out_dir,
            name_prefix=body.name_prefix,
            include_tail=body.include_tail,
            min_duration_frames=body.min_duration_frames,
            filename_from_label=body.filename_from_label,
            normalize_preset=body.normalize_preset,
        )
    except Exception as e:
        raise HTTPException(
            400, f"export_selection_marker_segments failed: {e}",
        ) from e


class ExportSelectionStoryboardBody(BaseModel):
    clip_ids: list[str]
    out_dir: str | None = None
    include_markers: bool = True
    include_clip_mids: bool = True
    include_contact: bool = True
    width: int = 640
    max_stills: int = 64


@app.post("/api/edit/export_selection_storyboard")
def export_selection_storyboard_api(
    body: ExportSelectionStoryboardBody,
) -> dict[str, Any]:
    """Storyboard folder for selection."""
    ed = _ed()
    try:
        return ed.export_selection_storyboard(
            body.clip_ids,
            out_dir=body.out_dir,
            include_markers=body.include_markers,
            include_clip_mids=body.include_clip_mids,
            include_contact=body.include_contact,
            width=body.width,
            max_stills=body.max_stills,
        )
    except Exception as e:
        raise HTTPException(
            400, f"export_selection_storyboard failed: {e}",
        ) from e


class ExportSelectionFrameSequenceBody(BaseModel):
    clip_ids: list[str]
    out_dir: str | None = None
    pattern: str = "frame_%06d.png"
    max_frames: int | None = None
    height: int | None = None


@app.post("/api/edit/export_selection_frame_sequence")
def export_selection_frame_sequence_api(
    body: ExportSelectionFrameSequenceBody,
) -> dict[str, Any]:
    """Image sequence for selection span."""
    ed = _ed()
    try:
        return ed.export_selection_frame_sequence(
            body.clip_ids,
            out_dir=body.out_dir,
            pattern=body.pattern,
            max_frames=body.max_frames,
            height=body.height,
        )
    except Exception as e:
        raise HTTPException(
            400, f"export_selection_frame_sequence failed: {e}",
        ) from e


class ExportSelectionHandoffBody(BaseModel):
    clip_ids: list[str]
    out_dir: str | None = None
    include_manifest: bool = True
    include_preflight: bool = True
    include_otio: bool = False
    include_markers: bool = True
    include_review: bool = True
    include_media: bool = True


@app.post("/api/edit/export_selection_handoff")
def export_selection_handoff_api(
    body: ExportSelectionHandoffBody,
) -> dict[str, Any]:
    """Selection-scoped agent handoff folder."""
    ed = _ed()
    try:
        return ed.export_selection_handoff(
            body.clip_ids,
            out_dir=body.out_dir,
            include_manifest=body.include_manifest,
            include_preflight=body.include_preflight,
            include_otio=body.include_otio,
            include_markers=body.include_markers,
            include_review=body.include_review,
            include_media=body.include_media,
        )
    except Exception as e:
        raise HTTPException(
            400, f"export_selection_handoff failed: {e}",
        ) from e


class ExportSelectionReviewPackageBody(BaseModel):
    clip_ids: list[str]
    out_dir: str | None = None
    include_handoff: bool = True
    include_storyboard: bool = True
    include_export: bool = True
    include_social: bool = False
    social_variants: list[str] | None = None
    normalize_preset: str | None = None
    export_filename: str = "selection_review.mp4"


@app.post("/api/edit/export_selection_review_package")
def export_selection_review_package_api(
    body: ExportSelectionReviewPackageBody,
) -> dict[str, Any]:
    """Selection review package (handoff + storyboard + export)."""
    ed = _ed()
    try:
        return ed.export_selection_review_package(
            body.clip_ids,
            out_dir=body.out_dir,
            include_handoff=body.include_handoff,
            include_storyboard=body.include_storyboard,
            include_export=body.include_export,
            include_social=body.include_social,
            social_variants=body.social_variants,
            normalize_preset=body.normalize_preset,
            export_filename=body.export_filename,
        )
    except Exception as e:
        raise HTTPException(
            400, f"export_selection_review_package failed: {e}",
        ) from e


class WatermarkSelectionBody(BaseModel):
    clip_ids: list[str]
    content: str = "REVIEW"
    position: str = "bottom"
    size: int = 22
    alpha: float = 0.55
    color: str = "white"
    video_only: bool = True


@app.post("/api/edit/watermark_selection")
def watermark_selection_api(body: WatermarkSelectionBody) -> dict[str, Any]:
    """Batch text watermark on selection."""
    ed = _ed()
    try:
        r = ed.watermark_selection(
            body.clip_ids,
            body.content,
            position=body.position,
            size=body.size,
            alpha=body.alpha,
            color=body.color,
            video_only=body.video_only,
        )
    except Exception as e:
        raise HTTPException(400, f"watermark_selection failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class ClearSelectionWatermarksBody(BaseModel):
    clip_ids: list[str]
    video_only: bool = True


@app.post("/api/edit/clear_selection_watermarks")
def clear_selection_watermarks_api(
    body: ClearSelectionWatermarksBody,
) -> dict[str, Any]:
    """Strip watermark FX from selection."""
    ed = _ed()
    try:
        r = ed.clear_selection_watermarks(
            body.clip_ids, video_only=body.video_only,
        )
    except Exception as e:
        raise HTTPException(
            400, f"clear_selection_watermarks failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class SafeAreaSelectionBody(BaseModel):
    clip_ids: list[str]
    action: float = 0.90
    title: float = 0.80
    thickness: int = 2
    video_only: bool = True


@app.post("/api/edit/safe_area_selection")
def safe_area_selection_api(body: SafeAreaSelectionBody) -> dict[str, Any]:
    """Safe-area overlays on selection."""
    ed = _ed()
    try:
        r = ed.safe_area_selection(
            body.clip_ids,
            action=body.action,
            title=body.title,
            thickness=body.thickness,
            video_only=body.video_only,
        )
    except Exception as e:
        raise HTTPException(400, f"safe_area_selection failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class ClearSelectionSafeAreasBody(BaseModel):
    clip_ids: list[str]
    video_only: bool = True


@app.post("/api/edit/clear_selection_safe_areas")
def clear_selection_safe_areas_api(
    body: ClearSelectionSafeAreasBody,
) -> dict[str, Any]:
    """Strip safe_area FX from selection."""
    ed = _ed()
    try:
        r = ed.clear_selection_safe_areas(
            body.clip_ids, video_only=body.video_only,
        )
    except Exception as e:
        raise HTTPException(
            400, f"clear_selection_safe_areas failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class TimecodeSelectionBody(BaseModel):
    clip_ids: list[str]
    position: str = "bottom"
    size: int = 28
    start: str = "00:00:00:00"
    video_only: bool = True


@app.post("/api/edit/timecode_selection")
def timecode_selection_api(body: TimecodeSelectionBody) -> dict[str, Any]:
    """Timecode burn-in on selection."""
    ed = _ed()
    try:
        r = ed.timecode_selection(
            body.clip_ids,
            position=body.position,
            size=body.size,
            start=body.start,
            video_only=body.video_only,
        )
    except Exception as e:
        raise HTTPException(400, f"timecode_selection failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class ClearSelectionTimecodesBody(BaseModel):
    clip_ids: list[str]
    video_only: bool = True


@app.post("/api/edit/clear_selection_timecodes")
def clear_selection_timecodes_api(
    body: ClearSelectionTimecodesBody,
) -> dict[str, Any]:
    """Strip timecode FX from selection."""
    ed = _ed()
    try:
        r = ed.clear_selection_timecodes(
            body.clip_ids, video_only=body.video_only,
        )
    except Exception as e:
        raise HTTPException(
            400, f"clear_selection_timecodes failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ApplySelectionReviewOverlaysBody(BaseModel):
    clip_ids: list[str]
    watermark: str | None = "REVIEW"
    safe_area: bool = True
    timecode: bool = True
    watermark_position: str = "bottom"
    timecode_position: str = "bottom"
    video_only: bool = True


@app.post("/api/edit/apply_selection_review_overlays")
def apply_selection_review_overlays_api(
    body: ApplySelectionReviewOverlaysBody,
) -> dict[str, Any]:
    """One-shot review overlays on selection."""
    ed = _ed()
    try:
        r = ed.apply_selection_review_overlays(
            body.clip_ids,
            watermark=body.watermark,
            safe_area=body.safe_area,
            timecode=body.timecode,
            watermark_position=body.watermark_position,
            timecode_position=body.timecode_position,
            video_only=body.video_only,
        )
    except Exception as e:
        raise HTTPException(
            400, f"apply_selection_review_overlays failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ClearSelectionReviewOverlaysBody(BaseModel):
    clip_ids: list[str]
    watermark: bool = True
    safe_area: bool = True
    timecode: bool = True
    video_only: bool = True


@app.post("/api/edit/clear_selection_review_overlays")
def clear_selection_review_overlays_api(
    body: ClearSelectionReviewOverlaysBody,
) -> dict[str, Any]:
    """Strip all review overlays from selection."""
    ed = _ed()
    try:
        r = ed.clear_selection_review_overlays(
            body.clip_ids,
            watermark=body.watermark,
            safe_area=body.safe_area,
            timecode=body.timecode,
            video_only=body.video_only,
        )
    except Exception as e:
        raise HTTPException(
            400, f"clear_selection_review_overlays failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class KenBurnsSelectionBody(BaseModel):
    clip_ids: list[str]
    zoom_start: float = 1.0
    zoom_end: float = 1.15
    x_start: float = 0.5
    y_start: float = 0.5
    x_end: float = 0.5
    y_end: float = 0.5
    replace: bool = True
    video_only: bool = True


@app.post("/api/edit/ken_burns_selection")
def ken_burns_selection_api(body: KenBurnsSelectionBody) -> dict[str, Any]:
    """Ken Burns on selection."""
    ed = _ed()
    try:
        r = ed.ken_burns_selection(
            body.clip_ids,
            zoom_start=body.zoom_start,
            zoom_end=body.zoom_end,
            x_start=body.x_start,
            y_start=body.y_start,
            x_end=body.x_end,
            y_end=body.y_end,
            replace=body.replace,
            video_only=body.video_only,
        )
    except Exception as e:
        raise HTTPException(400, f"ken_burns_selection failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class LumaKeySelectionBody(BaseModel):
    clip_ids: list[str]
    threshold: float = 0.1
    tolerance: float = 0.1
    replace: bool = True
    video_only: bool = True


@app.post("/api/edit/luma_key_selection")
def luma_key_selection_api(body: LumaKeySelectionBody) -> dict[str, Any]:
    """Luma key on selection."""
    ed = _ed()
    try:
        r = ed.luma_key_selection(
            body.clip_ids,
            threshold=body.threshold,
            tolerance=body.tolerance,
            replace=body.replace,
            video_only=body.video_only,
        )
    except Exception as e:
        raise HTTPException(400, f"luma_key_selection failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class ShapeMaskSelectionBody(BaseModel):
    clip_ids: list[str]
    shape: str = "circle"
    cx: float = 0.5
    cy: float = 0.5
    size: float = 0.5
    feather: float = 0.05
    width: float = 0.5
    height: float = 0.5
    invert: bool = False
    replace: bool = True
    video_only: bool = True


@app.post("/api/edit/shape_mask_selection")
def shape_mask_selection_api(body: ShapeMaskSelectionBody) -> dict[str, Any]:
    """Shape mask on selection."""
    ed = _ed()
    try:
        r = ed.shape_mask_selection(
            body.clip_ids,
            shape=body.shape,
            cx=body.cx,
            cy=body.cy,
            size=body.size,
            feather=body.feather,
            width=body.width,
            height=body.height,
            invert=body.invert,
            replace=body.replace,
            video_only=body.video_only,
        )
    except Exception as e:
        raise HTTPException(400, f"shape_mask_selection failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class ClearSelectionShapeMasksBody(BaseModel):
    clip_ids: list[str]
    video_only: bool = True


@app.post("/api/edit/clear_selection_shape_masks")
def clear_selection_shape_masks_api(
    body: ClearSelectionShapeMasksBody,
) -> dict[str, Any]:
    """Strip shape_mask FX from selection."""
    ed = _ed()
    try:
        r = ed.clear_selection_shape_masks(
            body.clip_ids, video_only=body.video_only,
        )
    except Exception as e:
        raise HTTPException(
            400, f"clear_selection_shape_masks failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ExportSelectionClipsPackBody(BaseModel):
    clip_ids: list[str]
    out_dir: str | None = None
    prefix: str = "clip"


@app.post("/api/edit/export_selection_clips_pack")
def export_selection_clips_pack_api(
    body: ExportSelectionClipsPackBody,
) -> dict[str, Any]:
    """Per-clip MP4 pack for selection."""
    ed = _ed()
    try:
        return ed.export_selection_clips_pack(
            body.clip_ids, out_dir=body.out_dir, prefix=body.prefix,
        )
    except Exception as e:
        raise HTTPException(
            400, f"export_selection_clips_pack failed: {e}",
        ) from e


class ClearSelectionLutsBody(BaseModel):
    clip_ids: list[str]
    video_only: bool = True


@app.post("/api/edit/clear_selection_luts")
def clear_selection_luts_api(body: ClearSelectionLutsBody) -> dict[str, Any]:
    """Strip lut3d from selection."""
    ed = _ed()
    try:
        r = ed.clear_selection_luts(
            body.clip_ids, video_only=body.video_only,
        )
    except Exception as e:
        raise HTTPException(400, f"clear_selection_luts failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class ExportSelectionClipsGifPackBody(BaseModel):
    clip_ids: list[str]
    out_dir: str | None = None
    prefix: str = "clip"
    fps: float = 12.0
    width: int = 480
    max_duration_seconds: float = 12.0


@app.post("/api/edit/export_selection_clips_gif_pack")
def export_selection_clips_gif_pack_api(
    body: ExportSelectionClipsGifPackBody,
) -> dict[str, Any]:
    """Per-clip GIF pack for selection."""
    ed = _ed()
    try:
        return ed.export_selection_clips_gif_pack(
            body.clip_ids,
            out_dir=body.out_dir,
            prefix=body.prefix,
            fps=body.fps,
            width=body.width,
            max_duration_seconds=body.max_duration_seconds,
        )
    except Exception as e:
        raise HTTPException(
            400, f"export_selection_clips_gif_pack failed: {e}",
        ) from e


class ExportSelectionClipsWebmPackBody(BaseModel):
    clip_ids: list[str]
    out_dir: str | None = None
    prefix: str = "clip"
    crf: int = 32
    width: int | None = None


@app.post("/api/edit/export_selection_clips_webm_pack")
def export_selection_clips_webm_pack_api(
    body: ExportSelectionClipsWebmPackBody,
) -> dict[str, Any]:
    """Per-clip WebM pack for selection."""
    ed = _ed()
    try:
        return ed.export_selection_clips_webm_pack(
            body.clip_ids,
            out_dir=body.out_dir,
            prefix=body.prefix,
            crf=body.crf,
            width=body.width,
        )
    except Exception as e:
        raise HTTPException(
            400, f"export_selection_clips_webm_pack failed: {e}",
        ) from e


class ExportSelectionClipsAudioPackBody(BaseModel):
    clip_ids: list[str]
    out_dir: str | None = None
    prefix: str = "clip"
    ext: str = "wav"
    sample_rate: int | None = None


@app.post("/api/edit/export_selection_clips_audio_pack")
def export_selection_clips_audio_pack_api(
    body: ExportSelectionClipsAudioPackBody,
) -> dict[str, Any]:
    """Per-clip audio pack for selection."""
    ed = _ed()
    try:
        return ed.export_selection_clips_audio_pack(
            body.clip_ids,
            out_dir=body.out_dir,
            prefix=body.prefix,
            ext=body.ext,
            sample_rate=body.sample_rate,
        )
    except Exception as e:
        raise HTTPException(
            400, f"export_selection_clips_audio_pack failed: {e}",
        ) from e


class SelectionDurationReportBody(BaseModel):
    clip_ids: list[str]


@app.post("/api/edit/selection_duration_report")
def selection_duration_report_api(
    body: SelectionDurationReportBody,
) -> dict[str, Any]:
    """Duration census for selection."""
    ed = _ed()
    try:
        return ed.selection_duration_report(body.clip_ids)
    except Exception as e:
        raise HTTPException(
            400, f"selection_duration_report failed: {e}",
        ) from e


class SetSelectionMetaBody(BaseModel):
    clip_ids: list[str]
    name: str | None = None
    color: str | None = None
    clear_name: bool = False
    clear_color: bool = False


@app.post("/api/edit/set_selection_meta")
def set_selection_meta_api(body: SetSelectionMetaBody) -> dict[str, Any]:
    """Batch name/color on selection."""
    ed = _ed()
    try:
        r = ed.set_selection_meta(
            body.clip_ids,
            name=body.name,
            color=body.color,
            clear_name=body.clear_name,
            clear_color=body.clear_color,
        )
    except Exception as e:
        raise HTTPException(400, f"set_selection_meta failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class ClearSelectionSubtitlesBody(BaseModel):
    clip_ids: list[str]
    video_only: bool = True


@app.post("/api/edit/clear_selection_subtitles")
def clear_selection_subtitles_api(
    body: ClearSelectionSubtitlesBody,
) -> dict[str, Any]:
    """Strip subtitles FX from selection."""
    ed = _ed()
    try:
        r = ed.clear_selection_subtitles(
            body.clip_ids, video_only=body.video_only,
        )
    except Exception as e:
        raise HTTPException(
            400, f"clear_selection_subtitles failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class SelectionMediaHealthBody(BaseModel):
    clip_ids: list[str]


@app.post("/api/edit/selection_media_health")
def selection_media_health_api(body: SelectionMediaHealthBody) -> dict[str, Any]:
    """Selection media health card."""
    ed = _ed()
    try:
        return ed.selection_media_health(body.clip_ids)
    except Exception as e:
        raise HTTPException(
            400, f"selection_media_health failed: {e}",
        ) from e


class ApplyLutSelectionBody(BaseModel):
    clip_ids: list[str]
    path: str
    replace: bool = True


@app.post("/api/edit/apply_lut_selection")
def apply_lut_selection_api(body: ApplyLutSelectionBody) -> dict[str, Any]:
    """Apply LUT file to selection."""
    ed = _ed()
    try:
        r = ed.apply_lut_selection(
            body.clip_ids, body.path, replace=body.replace,
        )
    except Exception as e:
        raise HTTPException(400, f"apply_lut_selection failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class SetSelectionFadesBody(BaseModel):
    clip_ids: list[str]
    fade_in_frames: int | None = None
    fade_out_frames: int | None = None


@app.post("/api/edit/set_selection_fades")
def set_selection_fades_api(body: SetSelectionFadesBody) -> dict[str, Any]:
    """Batch edge fades on selection."""
    ed = _ed()
    try:
        r = ed.set_selection_fades(
            body.clip_ids,
            fade_in_frames=body.fade_in_frames,
            fade_out_frames=body.fade_out_frames,
        )
    except Exception as e:
        raise HTTPException(400, f"set_selection_fades failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class ClearSelectionFadesBody(BaseModel):
    clip_ids: list[str]
    video_only: bool = False


@app.post("/api/edit/clear_selection_fades")
def clear_selection_fades_api(body: ClearSelectionFadesBody) -> dict[str, Any]:
    """Strip fade FX from selection."""
    ed = _ed()
    try:
        r = ed.clear_selection_fades(
            body.clip_ids, video_only=body.video_only,
        )
    except Exception as e:
        raise HTTPException(400, f"clear_selection_fades failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class SelectionFadesReportBody(BaseModel):
    clip_ids: list[str]


@app.post("/api/edit/selection_fades_report")
def selection_fades_report_api(body: SelectionFadesReportBody) -> dict[str, Any]:
    """Fade report for selection."""
    ed = _ed()
    try:
        return ed.selection_fades_report(body.clip_ids)
    except Exception as e:
        raise HTTPException(
            400, f"selection_fades_report failed: {e}",
        ) from e


class SelectionTransitionReportBody(BaseModel):
    clip_ids: list[str]


@app.post("/api/edit/selection_transition_report")
def selection_transition_report_api(
    body: SelectionTransitionReportBody,
) -> dict[str, Any]:
    """Transition report for selection."""
    ed = _ed()
    try:
        return ed.selection_transition_report(body.clip_ids)
    except Exception as e:
        raise HTTPException(
            400, f"selection_transition_report failed: {e}",
        ) from e


class SelectionLevelsReportBody(BaseModel):
    clip_ids: list[str]


@app.post("/api/edit/selection_levels_report")
def selection_levels_report_api(
    body: SelectionLevelsReportBody,
) -> dict[str, Any]:
    """Gain/opacity/speed report for selection."""
    ed = _ed()
    try:
        return ed.selection_levels_report(body.clip_ids)
    except Exception as e:
        raise HTTPException(
            400, f"selection_levels_report failed: {e}",
        ) from e


class SelectionLinkReportBody(BaseModel):
    clip_ids: list[str]


@app.post("/api/edit/selection_link_report")
def selection_link_report_api(
    body: SelectionLinkReportBody,
) -> dict[str, Any]:
    """Link-group report for selection."""
    ed = _ed()
    try:
        return ed.selection_link_report(body.clip_ids)
    except Exception as e:
        raise HTTPException(
            400, f"selection_link_report failed: {e}",
        ) from e


class SelectionPositionReportBody(BaseModel):
    clip_ids: list[str]


@app.post("/api/edit/selection_position_report")
def selection_position_report_api(
    body: SelectionPositionReportBody,
) -> dict[str, Any]:
    """Layout position report for selection."""
    ed = _ed()
    try:
        return ed.selection_position_report(body.clip_ids)
    except Exception as e:
        raise HTTPException(
            400, f"selection_position_report failed: {e}",
        ) from e


class SelectionMetaReportBody(BaseModel):
    clip_ids: list[str]


@app.post("/api/edit/selection_meta_report")
def selection_meta_report_api(
    body: SelectionMetaReportBody,
) -> dict[str, Any]:
    """Name/color meta report for selection."""
    ed = _ed()
    try:
        return ed.selection_meta_report(body.clip_ids)
    except Exception as e:
        raise HTTPException(
            400, f"selection_meta_report failed: {e}",
        ) from e


class SelectionAgentCardBody(BaseModel):
    clip_ids: list[str]


@app.post("/api/edit/selection_agent_card")
def selection_agent_card_api(body: SelectionAgentCardBody) -> dict[str, Any]:
    """One-shot selection agent card."""
    ed = _ed()
    try:
        return ed.selection_agent_card(body.clip_ids)
    except Exception as e:
        raise HTTPException(
            400, f"selection_agent_card failed: {e}",
        ) from e


class ExportSelectionAgentCardBody(BaseModel):
    clip_ids: list[str]
    filename: str = "selection_agent_card.json"
    path: str | None = None


@app.post("/api/edit/export_selection_agent_card")
def export_selection_agent_card_api(
    body: ExportSelectionAgentCardBody,
) -> dict[str, Any]:
    """Write selection agent card JSON."""
    ed = _ed()
    try:
        return ed.export_selection_agent_card(
            body.clip_ids, filename=body.filename, path=body.path,
        )
    except Exception as e:
        raise HTTPException(
            400, f"export_selection_agent_card failed: {e}",
        ) from e


class SelectionMutedReportBody(BaseModel):
    clip_ids: list[str]


@app.post("/api/edit/selection_muted_report")
def selection_muted_report_api(
    body: SelectionMutedReportBody,
) -> dict[str, Any]:
    """Muted report for selection."""
    ed = _ed()
    try:
        return ed.selection_muted_report(body.clip_ids)
    except Exception as e:
        raise HTTPException(
            400, f"selection_muted_report failed: {e}",
        ) from e


class SelectionTrackReportBody(BaseModel):
    clip_ids: list[str]


@app.post("/api/edit/selection_track_report")
def selection_track_report_api(
    body: SelectionTrackReportBody,
) -> dict[str, Any]:
    """Track M/S/L report for selection."""
    ed = _ed()
    try:
        return ed.selection_track_report(body.clip_ids)
    except Exception as e:
        raise HTTPException(
            400, f"selection_track_report failed: {e}",
        ) from e


class FinishSelectionReviewExportBody(BaseModel):
    clip_ids: list[str]
    filename: str = "selection_client_review.mp4"
    watermark: str | None = "REVIEW"
    safe_area: bool = True
    timecode: bool = True
    clear_overlays: bool = True
    normalize_preset: str | None = None


@app.post("/api/edit/finish_selection_review_export")
def finish_selection_review_export_api(
    body: FinishSelectionReviewExportBody,
) -> dict[str, Any]:
    """Review overlays → export → optional clear."""
    ed = _ed()
    try:
        r = ed.finish_selection_review_export(
            body.clip_ids,
            filename=body.filename,
            watermark=body.watermark,
            safe_area=body.safe_area,
            timecode=body.timecode,
            clear_overlays=body.clear_overlays,
            normalize_preset=body.normalize_preset,
        )
    except Exception as e:
        raise HTTPException(
            400, f"finish_selection_review_export failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ExportSelectionClientPackBody(BaseModel):
    clip_ids: list[str]
    out_dir: str | None = None
    include_card: bool = True
    include_stills: bool = True
    include_export: bool = True
    include_review_export: bool = False
    normalize_preset: str | None = None
    stills_width: int = 640


@app.post("/api/edit/export_selection_client_pack")
def export_selection_client_pack_api(
    body: ExportSelectionClientPackBody,
) -> dict[str, Any]:
    """Client handoff pack for selection."""
    ed = _ed()
    try:
        r = ed.export_selection_client_pack(
            body.clip_ids,
            out_dir=body.out_dir,
            include_card=body.include_card,
            include_stills=body.include_stills,
            include_export=body.include_export,
            include_review_export=body.include_review_export,
            normalize_preset=body.normalize_preset,
            stills_width=body.stills_width,
        )
    except Exception as e:
        raise HTTPException(
            400, f"export_selection_client_pack failed: {e}",
        ) from e
    # may have mutated timeline if include_review_export
    return {**r, "timeline": ed.timeline_view()}


class ValidateSelectionBody(BaseModel):
    clip_ids: list[str]
    min_clip_seconds: float = 0.4
    set_work_area: bool = False


@app.post("/api/edit/validate_selection")
def validate_selection_api(body: ValidateSelectionBody) -> dict[str, Any]:
    """Validate selection export readiness."""
    ed = _ed()
    try:
        r = ed.validate_selection(
            body.clip_ids,
            min_clip_seconds=body.min_clip_seconds,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(400, f"validate_selection failed: {e}") from e
    if body.set_work_area:
        return {**r, "timeline": ed.timeline_view()}
    return r


class FinishSelectionSocialPackBody(BaseModel):
    clip_ids: list[str]
    variants: list[str] | None = None
    reframe: bool = False
    aspect: str = "9:16"
    prepare: bool = False
    normalize_preset: str | None = None
    name_prefix: str = "selection"
    out_dir: str | None = None


@app.post("/api/edit/finish_selection_social_pack")
def finish_selection_social_pack_api(
    body: FinishSelectionSocialPackBody,
) -> dict[str, Any]:
    """Social pack finish pipeline."""
    ed = _ed()
    try:
        r = ed.finish_selection_social_pack(
            body.clip_ids,
            variants=body.variants,
            reframe=body.reframe,
            aspect=body.aspect,
            prepare=body.prepare,
            normalize_preset=body.normalize_preset,
            name_prefix=body.name_prefix,
            out_dir=body.out_dir,
        )
    except Exception as e:
        raise HTTPException(
            400, f"finish_selection_social_pack failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class SelectionChecklistBody(BaseModel):
    clip_ids: list[str]
    min_clip_seconds: float = 0.4


@app.post("/api/edit/selection_checklist")
def selection_checklist_api(body: SelectionChecklistBody) -> dict[str, Any]:
    """Agent checklist for selection."""
    ed = _ed()
    try:
        return ed.selection_checklist(
            body.clip_ids, min_clip_seconds=body.min_clip_seconds,
        )
    except Exception as e:
        raise HTTPException(400, f"selection_checklist failed: {e}") from e


class ExportSelectionChecklistBody(BaseModel):
    clip_ids: list[str]
    filename: str = "selection_checklist.md"
    path: str | None = None
    min_clip_seconds: float = 0.4
    format: str = "md"


@app.post("/api/edit/export_selection_checklist")
def export_selection_checklist_api(
    body: ExportSelectionChecklistBody,
) -> dict[str, Any]:
    """Write selection checklist to disk."""
    ed = _ed()
    try:
        return ed.export_selection_checklist(
            body.clip_ids,
            filename=body.filename,
            path=body.path,
            min_clip_seconds=body.min_clip_seconds,
            format=body.format,
        )
    except Exception as e:
        raise HTTPException(
            400, f"export_selection_checklist failed: {e}",
        ) from e


class RepairSelectionBody(BaseModel):
    clip_ids: list[str]
    unlock: bool = True
    ensure_proxies: bool = True
    pack_gaps: bool = False
    gap_frames: int = 0
    strip_path_c_unmapped: bool = False
    set_work_area: bool = False
    proxy_height: int = 360


@app.post("/api/edit/repair_selection")
def repair_selection_api(body: RepairSelectionBody) -> dict[str, Any]:
    """Best-effort selection repair."""
    ed = _ed()
    try:
        r = ed.repair_selection(
            body.clip_ids,
            unlock=body.unlock,
            ensure_proxies=body.ensure_proxies,
            pack_gaps=body.pack_gaps,
            gap_frames=body.gap_frames,
            strip_path_c_unmapped=body.strip_path_c_unmapped,
            set_work_area=body.set_work_area,
            proxy_height=body.proxy_height,
        )
    except Exception as e:
        raise HTTPException(400, f"repair_selection failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class ExportSelectionStillsDefaultBody(BaseModel):
    clip_ids: list[str]
    edge: str = "mid"
    width: int = 640
    ext: str = "jpg"
    subdir: str = "selection_stills"


@app.post("/api/edit/export_selection_stills_default")
def export_selection_stills_default_api(
    body: ExportSelectionStillsDefaultBody,
) -> dict[str, Any]:
    """Export selection stills to exports/selection_stills."""
    ed = _ed()
    try:
        return ed.export_selection_stills_default(
            body.clip_ids,
            edge=body.edge,
            width=body.width,
            ext=body.ext,
            subdir=body.subdir,
        )
    except Exception as e:
        raise HTTPException(
            400, f"export_selection_stills_default failed: {e}",
        ) from e


class RepairAndExportSelectionBody(BaseModel):
    clip_ids: list[str]
    filename: str = "selection_repaired.mp4"
    unlock: bool = True
    ensure_proxies: bool = True
    pack_gaps: bool = False
    force: bool = False
    normalize_preset: str | None = None
    proxy_height: int = 360


@app.post("/api/edit/repair_and_export_selection")
def repair_and_export_selection_api(
    body: RepairAndExportSelectionBody,
) -> dict[str, Any]:
    """Repair then export selection."""
    ed = _ed()
    try:
        r = ed.repair_and_export_selection(
            body.clip_ids,
            filename=body.filename,
            unlock=body.unlock,
            ensure_proxies=body.ensure_proxies,
            pack_gaps=body.pack_gaps,
            force=body.force,
            normalize_preset=body.normalize_preset,
            proxy_height=body.proxy_height,
        )
    except Exception as e:
        raise HTTPException(
            400, f"repair_and_export_selection failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ExportSelectionReportPackBody(BaseModel):
    clip_ids: list[str]
    out_dir: str | None = None
    include_checklist: bool = True
    include_agent_card: bool = True
    include_validate: bool = True
    include_muted: bool = True
    include_tracks: bool = True


@app.post("/api/edit/export_selection_report_pack")
def export_selection_report_pack_api(
    body: ExportSelectionReportPackBody,
) -> dict[str, Any]:
    """Selection QA report pack folder."""
    ed = _ed()
    try:
        return ed.export_selection_report_pack(
            body.clip_ids,
            out_dir=body.out_dir,
            include_checklist=body.include_checklist,
            include_agent_card=body.include_agent_card,
            include_validate=body.include_validate,
            include_muted=body.include_muted,
            include_tracks=body.include_tracks,
        )
    except Exception as e:
        raise HTTPException(
            400, f"export_selection_report_pack failed: {e}",
        ) from e


class SelectionExportSummaryBody(BaseModel):
    clip_ids: list[str]


@app.post("/api/edit/selection_export_summary")
def selection_export_summary_api(
    body: SelectionExportSummaryBody,
) -> dict[str, Any]:
    """Export briefing for selection."""
    ed = _ed()
    try:
        return ed.selection_export_summary(body.clip_ids)
    except Exception as e:
        raise HTTPException(
            400, f"selection_export_summary failed: {e}",
        ) from e


class ExportSelectionFormatsPackBody(BaseModel):
    clip_ids: list[str]
    out_dir: str | None = None
    include_mp4: bool = True
    include_webm: bool = True
    include_gif: bool = True
    include_audio: bool = True
    webm_crf: int = 32
    webm_width: int | None = 720
    gif_fps: float = 12.0
    gif_width: int = 480
    gif_max_duration_seconds: float = 12.0
    normalize_preset: str | None = None
    name_prefix: str = "selection"


@app.post("/api/edit/export_selection_formats_pack")
def export_selection_formats_pack_api(
    body: ExportSelectionFormatsPackBody,
) -> dict[str, Any]:
    """Multi-format union export pack."""
    ed = _ed()
    try:
        return ed.export_selection_formats_pack(
            body.clip_ids,
            out_dir=body.out_dir,
            include_mp4=body.include_mp4,
            include_webm=body.include_webm,
            include_gif=body.include_gif,
            include_audio=body.include_audio,
            webm_crf=body.webm_crf,
            webm_width=body.webm_width,
            gif_fps=body.gif_fps,
            gif_width=body.gif_width,
            gif_max_duration_seconds=body.gif_max_duration_seconds,
            normalize_preset=body.normalize_preset,
            name_prefix=body.name_prefix,
        )
    except Exception as e:
        raise HTTPException(
            400, f"export_selection_formats_pack failed: {e}",
        ) from e


class AgentFinishSelectionBody(BaseModel):
    clip_ids: list[str]
    repair: bool = True
    export: bool = True
    filename: str = "selection_agent_finish.mp4"
    write_checklist: bool = True
    write_card: bool = True
    force_export: bool = False
    normalize_preset: str | None = None
    ensure_proxies: bool = False


@app.post("/api/edit/agent_finish_selection")
def agent_finish_selection_api(body: AgentFinishSelectionBody) -> dict[str, Any]:
    """Canonical agent finish for selection."""
    ed = _ed()
    try:
        r = ed.agent_finish_selection(
            body.clip_ids,
            repair=body.repair,
            export=body.export,
            filename=body.filename,
            write_checklist=body.write_checklist,
            write_card=body.write_card,
            force_export=body.force_export,
            normalize_preset=body.normalize_preset,
            ensure_proxies=body.ensure_proxies,
        )
    except Exception as e:
        raise HTTPException(
            400, f"agent_finish_selection failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class RunSelectionPipelineBody(BaseModel):
    clip_ids: list[str]
    steps: list[str] | None = None
    normalize_preset: str | None = None
    social_variants: list[str] | None = None


@app.post("/api/edit/run_selection_pipeline")
def run_selection_pipeline_api(body: RunSelectionPipelineBody) -> dict[str, Any]:
    """Named step pipeline for selection."""
    ed = _ed()
    try:
        r = ed.run_selection_pipeline(
            body.clip_ids,
            steps=body.steps,
            normalize_preset=body.normalize_preset,
            social_variants=body.social_variants,
        )
    except Exception as e:
        raise HTTPException(
            400, f"run_selection_pipeline failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


@app.get("/api/edit/selection_pipeline_catalog")
def selection_pipeline_catalog_api() -> dict[str, Any]:
    """List known selection pipeline steps."""
    ed = _ed()
    try:
        return ed.selection_pipeline_catalog()
    except Exception as e:
        raise HTTPException(
            400, f"selection_pipeline_catalog failed: {e}",
        ) from e


class DryRunSelectionPipelineBody(BaseModel):
    clip_ids: list[str]
    steps: list[str] | None = None
    execute_read_only: bool = True


@app.post("/api/edit/dry_run_selection_pipeline")
def dry_run_selection_pipeline_api(
    body: DryRunSelectionPipelineBody,
) -> dict[str, Any]:
    """Preview selection pipeline without side effects."""
    ed = _ed()
    try:
        r = ed.dry_run_selection_pipeline(
            body.clip_ids,
            steps=body.steps,
            execute_read_only=body.execute_read_only,
        )
    except Exception as e:
        raise HTTPException(
            400, f"dry_run_selection_pipeline failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class SelectionSetStatusBody(BaseModel):
    name: str
    validate: bool = True
    set_work_area: bool = False


@app.post("/api/edit/selection_set_status")
def selection_set_status_api(body: SelectionSetStatusBody) -> dict[str, Any]:
    """Status for a named selection set."""
    ed = _ed()
    try:
        r = ed.selection_set_status(
            body.name,
            validate=body.validate,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"selection_set_status failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class DryRunSelectionSetPipelineBody(BaseModel):
    name: str
    steps: list[str] | None = None
    execute_read_only: bool = True
    set_work_area: bool = False


@app.post("/api/edit/dry_run_selection_set_pipeline")
def dry_run_selection_set_pipeline_api(
    body: DryRunSelectionSetPipelineBody,
) -> dict[str, Any]:
    """Dry-run pipeline for a named selection set."""
    ed = _ed()
    try:
        r = ed.dry_run_selection_set_pipeline(
            body.name,
            steps=body.steps,
            execute_read_only=body.execute_read_only,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"dry_run_selection_set_pipeline failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class BatchSelectionSetsStatusBody(BaseModel):
    names: list[str] | None = None
    validate: bool = True


@app.post("/api/edit/batch_selection_sets_status")
def batch_selection_sets_status_api(
    body: BatchSelectionSetsStatusBody,
) -> dict[str, Any]:
    """Status for many named selection sets."""
    ed = _ed()
    try:
        r = ed.batch_selection_sets_status(
            body.names,
            validate=body.validate,
        )
    except Exception as e:
        raise HTTPException(
            400, f"batch_selection_sets_status failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class BatchRunSelectionPipelinePresetBody(BaseModel):
    preset: str
    selection_sets: list[str] | None = None
    dry_run: bool = True
    execute_read_only: bool = True
    stop_on_error: bool = False
    normalize_preset: str | None = None
    social_variants: list[str] | None = None


@app.post("/api/edit/batch_run_selection_pipeline_preset")
def batch_run_selection_pipeline_preset_api(
    body: BatchRunSelectionPipelinePresetBody,
) -> dict[str, Any]:
    """Run/dry-run a pipeline preset on many selection sets."""
    ed = _ed()
    try:
        r = ed.batch_run_selection_pipeline_preset(
            body.preset,
            selection_sets=body.selection_sets,
            dry_run=body.dry_run,
            execute_read_only=body.execute_read_only,
            stop_on_error=body.stop_on_error,
            normalize_preset=body.normalize_preset,
            social_variants=body.social_variants,
        )
    except Exception as e:
        raise HTTPException(
            400, f"batch_run_selection_pipeline_preset failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ValidateSelectionSetBody(BaseModel):
    name: str
    min_clip_seconds: float = 0.4
    set_work_area: bool = False


@app.post("/api/edit/validate_selection_set")
def validate_selection_set_api(body: ValidateSelectionSetBody) -> dict[str, Any]:
    """Validate a named selection set."""
    ed = _ed()
    try:
        r = ed.validate_selection_set(
            body.name,
            min_clip_seconds=body.min_clip_seconds,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"validate_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class RepairSelectionSetBody(BaseModel):
    name: str
    unlock: bool = True
    ensure_proxies: bool = False
    pack_gaps: bool = False
    gap_frames: int = 0
    strip_path_c_unmapped: bool = False
    set_work_area: bool = False
    proxy_height: int = 360


@app.post("/api/edit/repair_selection_set")
def repair_selection_set_api(body: RepairSelectionSetBody) -> dict[str, Any]:
    """Repair a named selection set."""
    ed = _ed()
    try:
        r = ed.repair_selection_set(
            body.name,
            unlock=body.unlock,
            ensure_proxies=body.ensure_proxies,
            pack_gaps=body.pack_gaps,
            gap_frames=body.gap_frames,
            strip_path_c_unmapped=body.strip_path_c_unmapped,
            set_work_area=body.set_work_area,
            proxy_height=body.proxy_height,
        )
    except Exception as e:
        raise HTTPException(
            400, f"repair_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class BatchValidateSelectionSetsBody(BaseModel):
    names: list[str] | None = None
    min_clip_seconds: float = 0.4
    stop_on_error: bool = False


@app.post("/api/edit/batch_validate_selection_sets")
def batch_validate_selection_sets_api(
    body: BatchValidateSelectionSetsBody,
) -> dict[str, Any]:
    """Validate many named selection sets."""
    ed = _ed()
    try:
        r = ed.batch_validate_selection_sets(
            body.names,
            min_clip_seconds=body.min_clip_seconds,
            stop_on_error=body.stop_on_error,
        )
    except Exception as e:
        raise HTTPException(
            400, f"batch_validate_selection_sets failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class BatchRepairSelectionSetsBody(BaseModel):
    names: list[str] | None = None
    unlock: bool = True
    ensure_proxies: bool = False
    pack_gaps: bool = False
    gap_frames: int = 0
    strip_path_c_unmapped: bool = False
    proxy_height: int = 360
    stop_on_error: bool = False


@app.post("/api/edit/batch_repair_selection_sets")
def batch_repair_selection_sets_api(
    body: BatchRepairSelectionSetsBody,
) -> dict[str, Any]:
    """Repair many named selection sets."""
    ed = _ed()
    try:
        r = ed.batch_repair_selection_sets(
            body.names,
            unlock=body.unlock,
            ensure_proxies=body.ensure_proxies,
            pack_gaps=body.pack_gaps,
            gap_frames=body.gap_frames,
            strip_path_c_unmapped=body.strip_path_c_unmapped,
            proxy_height=body.proxy_height,
            stop_on_error=body.stop_on_error,
        )
    except Exception as e:
        raise HTTPException(
            400, f"batch_repair_selection_sets failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ExportSelectionSetsStatusReportBody(BaseModel):
    names: list[str] | None = None
    validate: bool = True
    path: str | None = None
    write_markdown: bool = True
    filename: str = "selection_sets_status_report.json"


@app.post("/api/edit/export_selection_sets_status_report")
def export_selection_sets_status_report_api(
    body: ExportSelectionSetsStatusReportBody,
) -> dict[str, Any]:
    """Export batch selection-sets status report."""
    ed = _ed()
    try:
        r = ed.export_selection_sets_status_report(
            body.names,
            validate=body.validate,
            path=body.path,
            write_markdown=body.write_markdown,
            filename=body.filename,
        )
    except Exception as e:
        raise HTTPException(
            400, f"export_selection_sets_status_report failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ExportSelectionSetsValidateReportBody(BaseModel):
    names: list[str] | None = None
    min_clip_seconds: float = 0.4
    path: str | None = None
    write_markdown: bool = True
    filename: str = "selection_sets_validate_report.json"


@app.post("/api/edit/export_selection_sets_validate_report")
def export_selection_sets_validate_report_api(
    body: ExportSelectionSetsValidateReportBody,
) -> dict[str, Any]:
    """Export batch selection-sets validate report."""
    ed = _ed()
    try:
        r = ed.export_selection_sets_validate_report(
            body.names,
            min_clip_seconds=body.min_clip_seconds,
            path=body.path,
            write_markdown=body.write_markdown,
            filename=body.filename,
        )
    except Exception as e:
        raise HTTPException(
            400, f"export_selection_sets_validate_report failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class SelectionSetToMarkersBody(BaseModel):
    name: str
    at: str = "start"
    label_prefix: str | None = None
    color: str = "#7c9cff"
    include_end: bool = False


@app.post("/api/edit/selection_set_to_markers")
def selection_set_to_markers_api(
    body: SelectionSetToMarkersBody,
) -> dict[str, Any]:
    """Place markers from a named selection set."""
    ed = _ed()
    try:
        r = ed.selection_set_to_markers(
            body.name,
            at=body.at,
            label_prefix=body.label_prefix,
            color=body.color,
            include_end=body.include_end,
        )
    except Exception as e:
        raise HTTPException(
            400, f"selection_set_to_markers failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ExportSelectionSetEdlBody(BaseModel):
    name: str
    path: str | None = None
    filename: str | None = None
    title: str | None = None


@app.post("/api/edit/export_selection_set_edl")
def export_selection_set_edl_api(
    body: ExportSelectionSetEdlBody,
) -> dict[str, Any]:
    """Export EDL for a named selection set."""
    ed = _ed()
    try:
        r = ed.export_selection_set_edl(
            body.name,
            path=body.path,
            filename=body.filename,
            title=body.title,
        )
    except Exception as e:
        raise HTTPException(
            400, f"export_selection_set_edl failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class MarkersToSelectionSetBody(BaseModel):
    name: str
    marker_ids: list[str] | None = None
    label_prefix: str | None = None
    kind: str | None = None
    track_id: str | None = None
    note: str = ""
    overwrite: bool = True


@app.post("/api/edit/markers_to_selection_set")
def markers_to_selection_set_api(
    body: MarkersToSelectionSetBody,
) -> dict[str, Any]:
    """Build a named selection set from marker hit-tests."""
    ed = _ed()
    try:
        r = ed.markers_to_selection_set(
            body.name,
            marker_ids=body.marker_ids,
            label_prefix=body.label_prefix,
            kind=body.kind,
            track_id=body.track_id,
            note=body.note,
            overwrite=body.overwrite,
        )
    except Exception as e:
        raise HTTPException(
            400, f"markers_to_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ExportSelectionSetCutlistBody(BaseModel):
    name: str
    path: str | None = None
    filename: str | None = None
    format: str = "csv"


@app.post("/api/edit/export_selection_set_cutlist")
def export_selection_set_cutlist_api(
    body: ExportSelectionSetCutlistBody,
) -> dict[str, Any]:
    """Export cutlist for a named selection set."""
    ed = _ed()
    try:
        r = ed.export_selection_set_cutlist(
            body.name,
            path=body.path,
            filename=body.filename,
            format=body.format,
        )
    except Exception as e:
        raise HTTPException(
            400, f"export_selection_set_cutlist failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ExportSelectionSetFcpxmlBody(BaseModel):
    name: str
    path: str | None = None
    filename: str | None = None
    title: str | None = None


@app.post("/api/edit/export_selection_set_fcpxml")
def export_selection_set_fcpxml_api(
    body: ExportSelectionSetFcpxmlBody,
) -> dict[str, Any]:
    """Export FCPXML for a named selection set."""
    ed = _ed()
    try:
        r = ed.export_selection_set_fcpxml(
            body.name,
            path=body.path,
            filename=body.filename,
            title=body.title,
        )
    except Exception as e:
        raise HTTPException(
            400, f"export_selection_set_fcpxml failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ExportSelectionSetOtioBody(BaseModel):
    name: str
    path: str | None = None
    filename: str | None = None
    title: str | None = None


@app.post("/api/edit/export_selection_set_otio")
def export_selection_set_otio_api(
    body: ExportSelectionSetOtioBody,
) -> dict[str, Any]:
    """Export OTIO-like JSON for a named selection set."""
    ed = _ed()
    try:
        r = ed.export_selection_set_otio(
            body.name,
            path=body.path,
            filename=body.filename,
            title=body.title,
        )
    except Exception as e:
        raise HTTPException(
            400, f"export_selection_set_otio failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ExportSelectionSetManifestBody(BaseModel):
    name: str
    path: str | None = None
    filename: str | None = None


@app.post("/api/edit/export_selection_set_manifest")
def export_selection_set_manifest_api(
    body: ExportSelectionSetManifestBody,
) -> dict[str, Any]:
    """Export manifest for a named selection set."""
    ed = _ed()
    try:
        r = ed.export_selection_set_manifest(
            body.name,
            path=body.path,
            filename=body.filename,
        )
    except Exception as e:
        raise HTTPException(
            400, f"export_selection_set_manifest failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ExportSelectionSetInterchangePackBody(BaseModel):
    name: str
    out_dir: str | None = None
    include_edl: bool = True
    include_cutlist: bool = True
    include_fcpxml: bool = True
    include_otio: bool = True
    include_manifest: bool = True
    cutlist_format: str = "csv"


@app.post("/api/edit/export_selection_set_interchange_pack")
def export_selection_set_interchange_pack_api(
    body: ExportSelectionSetInterchangePackBody,
) -> dict[str, Any]:
    """Export multi-format interchange pack for a named set."""
    ed = _ed()
    try:
        r = ed.export_selection_set_interchange_pack(
            body.name,
            out_dir=body.out_dir,
            include_edl=body.include_edl,
            include_cutlist=body.include_cutlist,
            include_fcpxml=body.include_fcpxml,
            include_otio=body.include_otio,
            include_manifest=body.include_manifest,
            cutlist_format=body.cutlist_format,
        )
    except Exception as e:
        raise HTTPException(
            400, f"export_selection_set_interchange_pack failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class SelectionSetToNewTrackBody(BaseModel):
    name: str
    track_name: str | None = None
    preserve_starts: bool = True
    stack_start: int | None = None
    set_work_area: bool = False


@app.post("/api/edit/selection_set_to_new_track")
def selection_set_to_new_track_api(
    body: SelectionSetToNewTrackBody,
) -> dict[str, Any]:
    """Move named selection set onto a new track."""
    ed = _ed()
    try:
        r = ed.selection_set_to_new_track(
            body.name,
            track_name=body.track_name,
            preserve_starts=body.preserve_starts,
            stack_start=body.stack_start,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"selection_set_to_new_track failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ExportSelectionSetHandoffBody(BaseModel):
    name: str
    out_dir: str | None = None
    include_manifest: bool = True
    include_preflight: bool = True
    include_otio: bool = True
    include_markers: bool = True
    include_review: bool = True
    include_media: bool = True
    include_interchange: bool = False


@app.post("/api/edit/export_selection_set_handoff")
def export_selection_set_handoff_api(
    body: ExportSelectionSetHandoffBody,
) -> dict[str, Any]:
    """Export agent handoff folder for a named selection set."""
    ed = _ed()
    try:
        r = ed.export_selection_set_handoff(
            body.name,
            out_dir=body.out_dir,
            include_manifest=body.include_manifest,
            include_preflight=body.include_preflight,
            include_otio=body.include_otio,
            include_markers=body.include_markers,
            include_review=body.include_review,
            include_media=body.include_media,
            include_interchange=body.include_interchange,
        )
    except Exception as e:
        raise HTTPException(
            400, f"export_selection_set_handoff failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ExportSelectionSetMp4Body(BaseModel):
    name: str
    filename: str | None = None
    normalize_preset: str | None = None
    set_work_area: bool = False


@app.post("/api/edit/export_selection_set_mp4")
def export_selection_set_mp4_api(
    body: ExportSelectionSetMp4Body,
) -> dict[str, Any]:
    """Export named selection set as MP4."""
    ed = _ed()
    try:
        r = ed.export_selection_set_mp4(
            body.name,
            filename=body.filename,
            normalize_preset=body.normalize_preset,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"export_selection_set_mp4 failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class FinishSelectionSetDeliveryBody(BaseModel):
    name: str
    filename: str | None = None
    prepare: bool = True
    unlock_tracks: bool = True
    set_work_area: bool = True
    pack_gaps: bool = False
    run_review: bool = True
    write_manifest: bool = True
    normalize_preset: str | None = "streaming"
    delivery_preset: str = "streaming"


@app.post("/api/edit/finish_selection_set_delivery")
def finish_selection_set_delivery_api(
    body: FinishSelectionSetDeliveryBody,
) -> dict[str, Any]:
    """Finish delivery for a named selection set."""
    ed = _ed()
    try:
        r = ed.finish_selection_set_delivery(
            body.name,
            filename=body.filename,
            prepare=body.prepare,
            unlock_tracks=body.unlock_tracks,
            set_work_area=body.set_work_area,
            pack_gaps=body.pack_gaps,
            run_review=body.run_review,
            write_manifest=body.write_manifest,
            normalize_preset=body.normalize_preset,
            delivery_preset=body.delivery_preset,
        )
    except Exception as e:
        raise HTTPException(
            400, f"finish_selection_set_delivery failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ExportSelectionSetWebmBody(BaseModel):
    name: str
    filename: str | None = None
    crf: int = 32
    width: int | None = 720
    set_work_area: bool = False


@app.post("/api/edit/export_selection_set_webm")
def export_selection_set_webm_api(
    body: ExportSelectionSetWebmBody,
) -> dict[str, Any]:
    """Export named selection set as WebM."""
    ed = _ed()
    try:
        r = ed.export_selection_set_webm(
            body.name,
            filename=body.filename,
            crf=body.crf,
            width=body.width,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"export_selection_set_webm failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ExportSelectionSetGifBody(BaseModel):
    name: str
    filename: str | None = None
    fps: float = 12.0
    width: int = 480
    max_duration_seconds: float = 12.0
    set_work_area: bool = False


@app.post("/api/edit/export_selection_set_gif")
def export_selection_set_gif_api(
    body: ExportSelectionSetGifBody,
) -> dict[str, Any]:
    """Export named selection set as GIF."""
    ed = _ed()
    try:
        r = ed.export_selection_set_gif(
            body.name,
            filename=body.filename,
            fps=body.fps,
            width=body.width,
            max_duration_seconds=body.max_duration_seconds,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"export_selection_set_gif failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ExportSelectionSetAudioBody(BaseModel):
    name: str
    filename: str | None = None
    sample_rate: int | None = None
    set_work_area: bool = False


@app.post("/api/edit/export_selection_set_audio")
def export_selection_set_audio_api(
    body: ExportSelectionSetAudioBody,
) -> dict[str, Any]:
    """Export named selection set audio mix."""
    ed = _ed()
    try:
        r = ed.export_selection_set_audio(
            body.name,
            filename=body.filename,
            sample_rate=body.sample_rate,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"export_selection_set_audio failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ExportSelectionSetFormatsPackBody(BaseModel):
    name: str
    out_dir: str | None = None
    include_mp4: bool = True
    include_webm: bool = True
    include_gif: bool = True
    include_audio: bool = True
    webm_crf: int = 32
    webm_width: int | None = 720
    gif_fps: float = 12.0
    gif_width: int = 480
    gif_max_duration_seconds: float = 12.0
    normalize_preset: str | None = None
    name_prefix: str | None = None
    set_work_area: bool = False


@app.post("/api/edit/export_selection_set_formats_pack")
def export_selection_set_formats_pack_api(
    body: ExportSelectionSetFormatsPackBody,
) -> dict[str, Any]:
    """Export multi-format media pack for a named selection set."""
    ed = _ed()
    try:
        r = ed.export_selection_set_formats_pack(
            body.name,
            out_dir=body.out_dir,
            include_mp4=body.include_mp4,
            include_webm=body.include_webm,
            include_gif=body.include_gif,
            include_audio=body.include_audio,
            webm_crf=body.webm_crf,
            webm_width=body.webm_width,
            gif_fps=body.gif_fps,
            gif_width=body.gif_width,
            gif_max_duration_seconds=body.gif_max_duration_seconds,
            normalize_preset=body.normalize_preset,
            name_prefix=body.name_prefix,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"export_selection_set_formats_pack failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ExportSelectionSetStillsBody(BaseModel):
    name: str
    edge: str = "mid"
    width: int = 640
    ext: str = "jpg"
    subdir: str | None = None
    set_work_area: bool = False


@app.post("/api/edit/export_selection_set_stills")
def export_selection_set_stills_api(
    body: ExportSelectionSetStillsBody,
) -> dict[str, Any]:
    """Export stills for a named selection set."""
    ed = _ed()
    try:
        r = ed.export_selection_set_stills(
            body.name,
            edge=body.edge,
            width=body.width,
            ext=body.ext,
            subdir=body.subdir,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"export_selection_set_stills failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ExportSelectionSetContactSheetBody(BaseModel):
    name: str
    filename: str | None = None
    max_tiles: int = 12
    tile_width: int = 160
    tile_height: int = 90
    cols: int | None = None
    set_work_area: bool = False


@app.post("/api/edit/export_selection_set_contact_sheet")
def export_selection_set_contact_sheet_api(
    body: ExportSelectionSetContactSheetBody,
) -> dict[str, Any]:
    """Export contact sheet for a named selection set."""
    ed = _ed()
    try:
        r = ed.export_selection_set_contact_sheet(
            body.name,
            filename=body.filename,
            max_tiles=body.max_tiles,
            tile_width=body.tile_width,
            tile_height=body.tile_height,
            cols=body.cols,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"export_selection_set_contact_sheet failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ExportSelectionSetClientPackBody(BaseModel):
    name: str
    out_dir: str | None = None
    include_card: bool = True
    include_stills: bool = True
    include_export: bool = True
    include_review_export: bool = False
    normalize_preset: str | None = None
    stills_width: int = 640
    set_work_area: bool = False


@app.post("/api/edit/export_selection_set_client_pack")
def export_selection_set_client_pack_api(
    body: ExportSelectionSetClientPackBody,
) -> dict[str, Any]:
    """Export client pack for a named selection set."""
    ed = _ed()
    try:
        r = ed.export_selection_set_client_pack(
            body.name,
            out_dir=body.out_dir,
            include_card=body.include_card,
            include_stills=body.include_stills,
            include_export=body.include_export,
            include_review_export=body.include_review_export,
            normalize_preset=body.normalize_preset,
            stills_width=body.stills_width,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"export_selection_set_client_pack failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ExportSelectionSetSocialPackBody(BaseModel):
    name: str
    out_dir: str | None = None
    variants: list[str] | None = None
    normalize_preset: str | None = None
    name_prefix: str | None = None
    set_work_area: bool = False


@app.post("/api/edit/export_selection_set_social_pack")
def export_selection_set_social_pack_api(
    body: ExportSelectionSetSocialPackBody,
) -> dict[str, Any]:
    """Export social pack for a named selection set."""
    ed = _ed()
    try:
        r = ed.export_selection_set_social_pack(
            body.name,
            out_dir=body.out_dir,
            variants=body.variants,
            normalize_preset=body.normalize_preset,
            name_prefix=body.name_prefix,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"export_selection_set_social_pack failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ExportSelectionSetReportPackBody(BaseModel):
    name: str
    out_dir: str | None = None
    include_checklist: bool = True
    include_agent_card: bool = True
    include_validate: bool = True
    include_muted: bool = True
    include_tracks: bool = True
    set_work_area: bool = False


@app.post("/api/edit/export_selection_set_report_pack")
def export_selection_set_report_pack_api(
    body: ExportSelectionSetReportPackBody,
) -> dict[str, Any]:
    """Export report pack for a named selection set."""
    ed = _ed()
    try:
        r = ed.export_selection_set_report_pack(
            body.name,
            out_dir=body.out_dir,
            include_checklist=body.include_checklist,
            include_agent_card=body.include_agent_card,
            include_validate=body.include_validate,
            include_muted=body.include_muted,
            include_tracks=body.include_tracks,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"export_selection_set_report_pack failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ExportSelectionSetReviewPackageBody(BaseModel):
    name: str
    out_dir: str | None = None
    include_handoff: bool = True
    include_storyboard: bool = True
    include_export: bool = True
    include_social: bool = False
    social_variants: list[str] | None = None
    normalize_preset: str | None = None
    export_filename: str | None = None
    set_work_area: bool = False


@app.post("/api/edit/export_selection_set_review_package")
def export_selection_set_review_package_api(
    body: ExportSelectionSetReviewPackageBody,
) -> dict[str, Any]:
    """Export review package for a named selection set."""
    ed = _ed()
    try:
        r = ed.export_selection_set_review_package(
            body.name,
            out_dir=body.out_dir,
            include_handoff=body.include_handoff,
            include_storyboard=body.include_storyboard,
            include_export=body.include_export,
            include_social=body.include_social,
            social_variants=body.social_variants,
            normalize_preset=body.normalize_preset,
            export_filename=body.export_filename,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"export_selection_set_review_package failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ExportSelectionSetStoryboardBody(BaseModel):
    name: str
    out_dir: str | None = None
    include_markers: bool = True
    include_clip_mids: bool = True
    include_contact: bool = True
    width: int = 640
    max_stills: int = 64
    set_work_area: bool = False


@app.post("/api/edit/export_selection_set_storyboard")
def export_selection_set_storyboard_api(
    body: ExportSelectionSetStoryboardBody,
) -> dict[str, Any]:
    """Export storyboard for a named selection set."""
    ed = _ed()
    try:
        r = ed.export_selection_set_storyboard(
            body.name,
            out_dir=body.out_dir,
            include_markers=body.include_markers,
            include_clip_mids=body.include_clip_mids,
            include_contact=body.include_contact,
            width=body.width,
            max_stills=body.max_stills,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"export_selection_set_storyboard failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ExportSelectionSetAgentCardBody(BaseModel):
    name: str
    filename: str | None = None
    path: str | None = None
    set_work_area: bool = False


@app.post("/api/edit/export_selection_set_agent_card")
def export_selection_set_agent_card_api(
    body: ExportSelectionSetAgentCardBody,
) -> dict[str, Any]:
    """Export agent card for a named selection set."""
    ed = _ed()
    try:
        r = ed.export_selection_set_agent_card(
            body.name,
            filename=body.filename,
            path=body.path,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"export_selection_set_agent_card failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ExportSelectionSetChecklistBody(BaseModel):
    name: str
    filename: str | None = None
    path: str | None = None
    min_clip_seconds: float = 0.4
    format: str = "md"
    set_work_area: bool = False


@app.post("/api/edit/export_selection_set_checklist")
def export_selection_set_checklist_api(
    body: ExportSelectionSetChecklistBody,
) -> dict[str, Any]:
    """Export checklist for a named selection set."""
    ed = _ed()
    try:
        r = ed.export_selection_set_checklist(
            body.name,
            filename=body.filename,
            path=body.path,
            min_clip_seconds=body.min_clip_seconds,
            format=body.format,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"export_selection_set_checklist failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class SelectionSetExportSummaryBody(BaseModel):
    name: str
    set_work_area: bool = False


@app.post("/api/edit/selection_set_export_summary")
def selection_set_export_summary_api(
    body: SelectionSetExportSummaryBody,
) -> dict[str, Any]:
    """Export briefing for a named selection set."""
    ed = _ed()
    try:
        r = ed.selection_set_export_summary(
            body.name,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"selection_set_export_summary failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class SelectionSetAgentPreflightBody(BaseModel):
    name: str
    set_work_area: bool = False
    min_clip_seconds: float = 0.4


@app.post("/api/edit/selection_set_agent_preflight")
def selection_set_agent_preflight_api(
    body: SelectionSetAgentPreflightBody,
) -> dict[str, Any]:
    """Agent preflight for a named selection set."""
    ed = _ed()
    try:
        r = ed.selection_set_agent_preflight(
            body.name,
            set_work_area=body.set_work_area,
            min_clip_seconds=body.min_clip_seconds,
        )
    except Exception as e:
        raise HTTPException(
            400, f"selection_set_agent_preflight failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class SelectionSetChecklistBody(BaseModel):
    name: str
    min_clip_seconds: float = 0.4
    set_work_area: bool = False


@app.post("/api/edit/selection_set_checklist")
def selection_set_checklist_api(
    body: SelectionSetChecklistBody,
) -> dict[str, Any]:
    """In-memory checklist for a named selection set."""
    ed = _ed()
    try:
        r = ed.selection_set_checklist(
            body.name,
            min_clip_seconds=body.min_clip_seconds,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"selection_set_checklist failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class SelectionSetToWorkAreaBody(BaseModel):
    name: str
    drop_missing: bool = True


@app.post("/api/edit/selection_set_to_work_area")
def selection_set_to_work_area_api(
    body: SelectionSetToWorkAreaBody,
) -> dict[str, Any]:
    """Set work In/Out from a named selection set."""
    ed = _ed()
    try:
        r = ed.selection_set_to_work_area(
            body.name,
            drop_missing=body.drop_missing,
        )
    except Exception as e:
        raise HTTPException(
            400, f"selection_set_to_work_area failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class WorkAreaToSelectionSetBody(BaseModel):
    name: str
    kind: str | None = None
    track_id: str | None = None
    mode: str = "overlap"
    note: str = ""
    overwrite: bool = True


@app.post("/api/edit/work_area_to_selection_set")
def work_area_to_selection_set_api(
    body: WorkAreaToSelectionSetBody,
) -> dict[str, Any]:
    """Build named selection set from work In/Out."""
    ed = _ed()
    try:
        r = ed.work_area_to_selection_set(
            body.name,
            kind=body.kind,
            track_id=body.track_id,
            mode=body.mode,
            note=body.note,
            overwrite=body.overwrite,
        )
    except Exception as e:
        raise HTTPException(
            400, f"work_area_to_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class SelectionSetMediaHealthBody(BaseModel):
    name: str
    set_work_area: bool = False


@app.post("/api/edit/selection_set_media_health")
def selection_set_media_health_api(
    body: SelectionSetMediaHealthBody,
) -> dict[str, Any]:
    """Media health for a named selection set."""
    ed = _ed()
    try:
        r = ed.selection_set_media_health(
            body.name,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"selection_set_media_health failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class SelectionSetOfflineMediaBody(BaseModel):
    name: str
    set_work_area: bool = False


@app.post("/api/edit/selection_set_offline_media")
def selection_set_offline_media_api(
    body: SelectionSetOfflineMediaBody,
) -> dict[str, Any]:
    """Offline media for a named selection set."""
    ed = _ed()
    try:
        r = ed.selection_set_offline_media(
            body.name,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"selection_set_offline_media failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class SelectionSetProxyReportBody(BaseModel):
    name: str
    set_work_area: bool = False


@app.post("/api/edit/selection_set_proxy_report")
def selection_set_proxy_report_api(
    body: SelectionSetProxyReportBody,
) -> dict[str, Any]:
    """Proxy report for a named selection set."""
    ed = _ed()
    try:
        r = ed.selection_set_proxy_report(
            body.name,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"selection_set_proxy_report failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class SelectionSetDurationReportBody(BaseModel):
    name: str
    set_work_area: bool = False


@app.post("/api/edit/selection_set_duration_report")
def selection_set_duration_report_api(
    body: SelectionSetDurationReportBody,
) -> dict[str, Any]:
    """Duration report for a named selection set."""
    ed = _ed()
    try:
        r = ed.selection_set_duration_report(
            body.name,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"selection_set_duration_report failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class SelectionSetPathCReportBody(BaseModel):
    name: str
    set_work_area: bool = False


@app.post("/api/edit/selection_set_path_c_report")
def selection_set_path_c_report_api(
    body: SelectionSetPathCReportBody,
) -> dict[str, Any]:
    """path-C report for a named selection set."""
    ed = _ed()
    try:
        r = ed.selection_set_path_c_report(
            body.name,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"selection_set_path_c_report failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class SelectionSetLockedTracksBody(BaseModel):
    name: str
    set_work_area: bool = False


@app.post("/api/edit/selection_set_locked_tracks")
def selection_set_locked_tracks_api(
    body: SelectionSetLockedTracksBody,
) -> dict[str, Any]:
    """Locked tracks for a named selection set."""
    ed = _ed()
    try:
        r = ed.selection_set_locked_tracks(
            body.name,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"selection_set_locked_tracks failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class SelectionSetEffectsReportBody(BaseModel):
    name: str
    set_work_area: bool = False


@app.post("/api/edit/selection_set_effects_report")
def selection_set_effects_report_api(
    body: SelectionSetEffectsReportBody,
) -> dict[str, Any]:
    """Effects report for a named selection set."""
    ed = _ed()
    try:
        r = ed.selection_set_effects_report(
            body.name,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"selection_set_effects_report failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class SelectionSetMutedReportBody(BaseModel):
    name: str
    set_work_area: bool = False


@app.post("/api/edit/selection_set_muted_report")
def selection_set_muted_report_api(
    body: SelectionSetMutedReportBody,
) -> dict[str, Any]:
    """Muted report for a named selection set."""
    ed = _ed()
    try:
        r = ed.selection_set_muted_report(
            body.name,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"selection_set_muted_report failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class SelectionSetFadesReportBody(BaseModel):
    name: str
    set_work_area: bool = False


@app.post("/api/edit/selection_set_fades_report")
def selection_set_fades_report_api(
    body: SelectionSetFadesReportBody,
) -> dict[str, Any]:
    """Fades report for a named selection set."""
    ed = _ed()
    try:
        r = ed.selection_set_fades_report(
            body.name,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"selection_set_fades_report failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class SelectionSetTransitionReportBody(BaseModel):
    name: str
    set_work_area: bool = False


@app.post("/api/edit/selection_set_transition_report")
def selection_set_transition_report_api(
    body: SelectionSetTransitionReportBody,
) -> dict[str, Any]:
    """Transition report for a named selection set."""
    ed = _ed()
    try:
        r = ed.selection_set_transition_report(
            body.name,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"selection_set_transition_report failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class SelectionSetLevelsReportBody(BaseModel):
    name: str
    set_work_area: bool = False


@app.post("/api/edit/selection_set_levels_report")
def selection_set_levels_report_api(
    body: SelectionSetLevelsReportBody,
) -> dict[str, Any]:
    """Levels report for a named selection set."""
    ed = _ed()
    try:
        r = ed.selection_set_levels_report(
            body.name,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"selection_set_levels_report failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class SelectionSetLinkReportBody(BaseModel):
    name: str
    set_work_area: bool = False


@app.post("/api/edit/selection_set_link_report")
def selection_set_link_report_api(
    body: SelectionSetLinkReportBody,
) -> dict[str, Any]:
    """Link report for a named selection set."""
    ed = _ed()
    try:
        r = ed.selection_set_link_report(
            body.name,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"selection_set_link_report failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class SelectionSetPositionReportBody(BaseModel):
    name: str
    set_work_area: bool = False


@app.post("/api/edit/selection_set_position_report")
def selection_set_position_report_api(
    body: SelectionSetPositionReportBody,
) -> dict[str, Any]:
    """Position report for a named selection set."""
    ed = _ed()
    try:
        r = ed.selection_set_position_report(
            body.name,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"selection_set_position_report failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class SelectionSetMetaReportBody(BaseModel):
    name: str
    set_work_area: bool = False


@app.post("/api/edit/selection_set_meta_report")
def selection_set_meta_report_api(
    body: SelectionSetMetaReportBody,
) -> dict[str, Any]:
    """Meta report for a named selection set."""
    ed = _ed()
    try:
        r = ed.selection_set_meta_report(
            body.name,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"selection_set_meta_report failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class SelectionSetCutReportBody(BaseModel):
    name: str
    set_work_area: bool = False


@app.post("/api/edit/selection_set_cut_report")
def selection_set_cut_report_api(
    body: SelectionSetCutReportBody,
) -> dict[str, Any]:
    """Cut/adjacency report for a named selection set."""
    ed = _ed()
    try:
        r = ed.selection_set_cut_report(
            body.name,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"selection_set_cut_report failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class SelectionSetTrackReportBody(BaseModel):
    name: str
    set_work_area: bool = False


@app.post("/api/edit/selection_set_track_report")
def selection_set_track_report_api(
    body: SelectionSetTrackReportBody,
) -> dict[str, Any]:
    """Track report for a named selection set."""
    ed = _ed()
    try:
        r = ed.selection_set_track_report(
            body.name,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"selection_set_track_report failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class SelectionSetMediaReportBody(BaseModel):
    name: str
    set_work_area: bool = False


@app.post("/api/edit/selection_set_media_report")
def selection_set_media_report_api(
    body: SelectionSetMediaReportBody,
) -> dict[str, Any]:
    """Media inventory for a named selection set."""
    ed = _ed()
    try:
        r = ed.selection_set_media_report(
            body.name,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"selection_set_media_report failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class SelectionSetAgentCardBody(BaseModel):
    name: str
    set_work_area: bool = False


@app.post("/api/edit/selection_set_agent_card")
def selection_set_agent_card_api(
    body: SelectionSetAgentCardBody,
) -> dict[str, Any]:
    """In-memory agent card for a named selection set."""
    ed = _ed()
    try:
        r = ed.selection_set_agent_card(
            body.name,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"selection_set_agent_card failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class MuteSelectionSetBody(BaseModel):
    name: str
    muted: bool = True
    set_work_area: bool = False


@app.post("/api/edit/mute_selection_set")
def mute_selection_set_api(
    body: MuteSelectionSetBody,
) -> dict[str, Any]:
    """Mute/unmute clips in a named selection set."""
    ed = _ed()
    try:
        r = ed.mute_selection_set(
            body.name,
            muted=body.muted,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"mute_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class SetSelectionSetFadesBody(BaseModel):
    name: str
    fade_in_frames: int | None = None
    fade_out_frames: int | None = None
    set_work_area: bool = False


@app.post("/api/edit/set_selection_set_fades")
def set_selection_set_fades_api(
    body: SetSelectionSetFadesBody,
) -> dict[str, Any]:
    """Set edge fades on a named selection set."""
    ed = _ed()
    try:
        r = ed.set_selection_set_fades(
            body.name,
            fade_in_frames=body.fade_in_frames,
            fade_out_frames=body.fade_out_frames,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"set_selection_set_fades failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class SetSelectionSetGainBody(BaseModel):
    name: str
    db: float
    set_work_area: bool = False


@app.post("/api/edit/set_selection_set_gain")
def set_selection_set_gain_api(
    body: SetSelectionSetGainBody,
) -> dict[str, Any]:
    """Set gain on a named selection set."""
    ed = _ed()
    try:
        r = ed.set_selection_set_gain(
            body.name,
            body.db,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"set_selection_set_gain failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class SetSelectionSetMetaBody(BaseModel):
    name: str
    clip_name: str | None = None
    color: str | None = None
    clear_name: bool = False
    clear_color: bool = False
    set_work_area: bool = False


@app.post("/api/edit/set_selection_set_meta")
def set_selection_set_meta_api(
    body: SetSelectionSetMetaBody,
) -> dict[str, Any]:
    """Set clip name/color on a named selection set."""
    ed = _ed()
    try:
        r = ed.set_selection_set_meta(
            body.name,
            clip_name=body.clip_name,
            color=body.color,
            clear_name=body.clear_name,
            clear_color=body.clear_color,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"set_selection_set_meta failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class SetSelectionSetOpacityBody(BaseModel):
    name: str
    amount: float
    set_work_area: bool = False


@app.post("/api/edit/set_selection_set_opacity")
def set_selection_set_opacity_api(
    body: SetSelectionSetOpacityBody,
) -> dict[str, Any]:
    """Set opacity on a named selection set."""
    ed = _ed()
    try:
        r = ed.set_selection_set_opacity(
            body.name,
            body.amount,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"set_selection_set_opacity failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class SetSelectionSetSpeedBody(BaseModel):
    name: str
    speed: float
    set_work_area: bool = False


@app.post("/api/edit/set_selection_set_speed")
def set_selection_set_speed_api(
    body: SetSelectionSetSpeedBody,
) -> dict[str, Any]:
    """Set speed on a named selection set (no ripple)."""
    ed = _ed()
    try:
        r = ed.set_selection_set_speed(
            body.name,
            body.speed,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"set_selection_set_speed failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class LinkSelectionSetBody(BaseModel):
    name: str
    group_id: str | None = None
    set_work_area: bool = False


@app.post("/api/edit/link_selection_set")
def link_selection_set_api(
    body: LinkSelectionSetBody,
) -> dict[str, Any]:
    """Link clips in a named selection set."""
    ed = _ed()
    try:
        r = ed.link_selection_set(
            body.name,
            group_id=body.group_id,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"link_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class SetSelectionSetPositionBody(BaseModel):
    name: str
    x: float
    y: float
    scale: float
    set_work_area: bool = False


@app.post("/api/edit/set_selection_set_position")
def set_selection_set_position_api(
    body: SetSelectionSetPositionBody,
) -> dict[str, Any]:
    """Set PiP position on a named selection set."""
    ed = _ed()
    try:
        r = ed.set_selection_set_position(
            body.name,
            body.x,
            body.y,
            body.scale,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"set_selection_set_position failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class UnlinkSelectionSetBody(BaseModel):
    name: str
    set_work_area: bool = False


@app.post("/api/edit/unlink_selection_set")
def unlink_selection_set_api(
    body: UnlinkSelectionSetBody,
) -> dict[str, Any]:
    """Unlink clips in a named selection set."""
    ed = _ed()
    try:
        r = ed.unlink_selection_set(
            body.name,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"unlink_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class LockSelectionSetTracksBody(BaseModel):
    name: str
    set_work_area: bool = False


@app.post("/api/edit/lock_selection_set_tracks")
def lock_selection_set_tracks_api(
    body: LockSelectionSetTracksBody,
) -> dict[str, Any]:
    """Lock tracks touched by a named selection set."""
    ed = _ed()
    try:
        r = ed.lock_selection_set_tracks(
            body.name,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"lock_selection_set_tracks failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class MuteSelectionSetTracksBody(BaseModel):
    name: str
    muted: bool = True
    set_work_area: bool = False


@app.post("/api/edit/mute_selection_set_tracks")
def mute_selection_set_tracks_api(
    body: MuteSelectionSetTracksBody,
) -> dict[str, Any]:
    """Mute/unmute tracks touched by a named selection set."""
    ed = _ed()
    try:
        r = ed.mute_selection_set_tracks(
            body.name,
            muted=body.muted,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"mute_selection_set_tracks failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class UnlockSelectionSetTracksBody(BaseModel):
    name: str
    set_work_area: bool = False


@app.post("/api/edit/unlock_selection_set_tracks")
def unlock_selection_set_tracks_api(
    body: UnlockSelectionSetTracksBody,
) -> dict[str, Any]:
    """Unlock tracks touched by a named selection set."""
    ed = _ed()
    try:
        r = ed.unlock_selection_set_tracks(
            body.name,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"unlock_selection_set_tracks failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ClearSelectionSetFadesBody(BaseModel):
    name: str
    video_only: bool = False
    set_work_area: bool = False


@app.post("/api/edit/clear_selection_set_fades")
def clear_selection_set_fades_api(
    body: ClearSelectionSetFadesBody,
) -> dict[str, Any]:
    """Clear fades on a named selection set."""
    ed = _ed()
    try:
        r = ed.clear_selection_set_fades(
            body.name,
            video_only=body.video_only,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"clear_selection_set_fades failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ClearSelectionSetPositionBody(BaseModel):
    name: str
    set_work_area: bool = False


@app.post("/api/edit/clear_selection_set_position")
def clear_selection_set_position_api(
    body: ClearSelectionSetPositionBody,
) -> dict[str, Any]:
    """Clear PiP position on a named selection set."""
    ed = _ed()
    try:
        r = ed.clear_selection_set_position(
            body.name,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"clear_selection_set_position failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class SoloSelectionSetTracksBody(BaseModel):
    name: str
    exclusive: bool = True
    set_work_area: bool = False


@app.post("/api/edit/solo_selection_set_tracks")
def solo_selection_set_tracks_api(
    body: SoloSelectionSetTracksBody,
) -> dict[str, Any]:
    """Solo tracks touched by a named selection set."""
    ed = _ed()
    try:
        r = ed.solo_selection_set_tracks(
            body.name,
            exclusive=body.exclusive,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"solo_selection_set_tracks failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ClearSelectionSetEffectsBody(BaseModel):
    name: str
    types: list[str] | None = None
    set_work_area: bool = False


@app.post("/api/edit/clear_selection_set_effects")
def clear_selection_set_effects_api(
    body: ClearSelectionSetEffectsBody,
) -> dict[str, Any]:
    """Clear effects on a named selection set."""
    ed = _ed()
    try:
        r = ed.clear_selection_set_effects(
            body.name,
            types=body.types,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"clear_selection_set_effects failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class UnsoloSelectionSetTracksBody(BaseModel):
    name: str
    set_work_area: bool = False


@app.post("/api/edit/unsolo_selection_set_tracks")
def unsolo_selection_set_tracks_api(
    body: UnsoloSelectionSetTracksBody,
) -> dict[str, Any]:
    """Unsolo tracks touched by a named selection set."""
    ed = _ed()
    try:
        r = ed.unsolo_selection_set_tracks(
            body.name,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"unsolo_selection_set_tracks failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class JoinSelectionSetBody(BaseModel):
    name: str
    set_work_area: bool = False


@app.post("/api/edit/join_selection_set")
def join_selection_set_api(
    body: JoinSelectionSetBody,
) -> dict[str, Any]:
    """Join adjacent hard-cuts in a named selection set."""
    ed = _ed()
    try:
        r = ed.join_selection_set(
            body.name,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"join_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ExtractSelectionSetBody(BaseModel):
    name: str
    set_work_area: bool = False


@app.post("/api/edit/extract_selection_set")
def extract_selection_set_api(
    body: ExtractSelectionSetBody,
) -> dict[str, Any]:
    """Extract (ripple delete) a named selection set."""
    ed = _ed()
    try:
        r = ed.extract_selection_set(
            body.name,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"extract_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class RateStretchSelectionSetBody(BaseModel):
    name: str
    target_duration_frames: int
    set_work_area: bool = False


@app.post("/api/edit/rate_stretch_selection_set")
def rate_stretch_selection_set_api(
    body: RateStretchSelectionSetBody,
) -> dict[str, Any]:
    """Rate-stretch a named selection set to fixed duration."""
    ed = _ed()
    try:
        r = ed.rate_stretch_selection_set(
            body.name,
            body.target_duration_frames,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"rate_stretch_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class AddTransitionsToSelectionSetBody(BaseModel):
    name: str
    transition_type: str = "cross_dissolve"
    duration_frames: int = 12
    require_both_selected: bool = True
    set_work_area: bool = False


@app.post("/api/edit/add_transitions_to_selection_set")
def add_transitions_to_selection_set_api(
    body: AddTransitionsToSelectionSetBody,
) -> dict[str, Any]:
    """Add transitions on hard-cuts in a named selection set."""
    ed = _ed()
    try:
        r = ed.add_transitions_to_selection_set(
            body.name,
            transition_type=body.transition_type,
            duration_frames=body.duration_frames,
            require_both_selected=body.require_both_selected,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"add_transitions_to_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class RemoveTransitionsFromSelectionSetBody(BaseModel):
    name: str
    set_work_area: bool = False


@app.post("/api/edit/remove_transitions_from_selection_set")
def remove_transitions_from_selection_set_api(
    body: RemoveTransitionsFromSelectionSetBody,
) -> dict[str, Any]:
    """Remove transitions from a named selection set."""
    ed = _ed()
    try:
        r = ed.remove_transitions_from_selection_set(
            body.name,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"remove_transitions_from_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class RenameSelectionSetFromMediaBody(BaseModel):
    name: str
    suffix_index: bool = False
    set_work_area: bool = False


@app.post("/api/edit/rename_selection_set_from_media")
def rename_selection_set_from_media_api(
    body: RenameSelectionSetFromMediaBody,
) -> dict[str, Any]:
    """Rename clips in a named selection set from media stems."""
    ed = _ed()
    try:
        r = ed.rename_selection_set_from_media(
            body.name,
            suffix_index=body.suffix_index,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"rename_selection_set_from_media failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class StripSelectionSetPathCUnmappedBody(BaseModel):
    name: str
    set_work_area: bool = False


@app.post("/api/edit/strip_selection_set_path_c_unmapped")
def strip_selection_set_path_c_unmapped_api(
    body: StripSelectionSetPathCUnmappedBody,
) -> dict[str, Any]:
    """Strip path-C unmapped effects from a named selection set."""
    ed = _ed()
    try:
        r = ed.strip_selection_set_path_c_unmapped(
            body.name,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"strip_selection_set_path_c_unmapped failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class NudgeSelectionSetBody(BaseModel):
    name: str
    delta_frames: int
    follow_links: bool = False
    set_work_area: bool = False


@app.post("/api/edit/nudge_selection_set")
def nudge_selection_set_api(
    body: NudgeSelectionSetBody,
) -> dict[str, Any]:
    """Nudge clips in a named selection set."""
    ed = _ed()
    try:
        r = ed.nudge_selection_set(
            body.name,
            body.delta_frames,
            follow_links=body.follow_links,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"nudge_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ApplyEdgeFadesToSelectionSetBody(BaseModel):
    name: str
    fade_in_frames: int = 6
    fade_out_frames: int = 6
    replace: bool = True
    set_work_area: bool = False


@app.post("/api/edit/apply_edge_fades_to_selection_set")
def apply_edge_fades_to_selection_set_api(
    body: ApplyEdgeFadesToSelectionSetBody,
) -> dict[str, Any]:
    """Apply edge fades to a named selection set."""
    ed = _ed()
    try:
        r = ed.apply_edge_fades_to_selection_set(
            body.name,
            fade_in_frames=body.fade_in_frames,
            fade_out_frames=body.fade_out_frames,
            replace=body.replace,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"apply_edge_fades_to_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class MoveSelectionSetToFrameBody(BaseModel):
    name: str
    to_frame: int
    follow_links: bool = False
    set_work_area: bool = False


@app.post("/api/edit/move_selection_set_to_frame")
def move_selection_set_to_frame_api(
    body: MoveSelectionSetToFrameBody,
) -> dict[str, Any]:
    """Rigid-move a named selection set to to_frame."""
    ed = _ed()
    try:
        r = ed.move_selection_set_to_frame(
            body.name,
            body.to_frame,
            follow_links=body.follow_links,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"move_selection_set_to_frame failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class RenameClipsInSelectionSetBody(BaseModel):
    name: str
    pattern: str = "Clip {n:03d}"
    start: int = 1
    set_work_area: bool = False


@app.post("/api/edit/rename_clips_in_selection_set")
def rename_clips_in_selection_set_api(
    body: RenameClipsInSelectionSetBody,
) -> dict[str, Any]:
    """Pattern-rename clips in a named selection set."""
    ed = _ed()
    try:
        r = ed.rename_clips_in_selection_set(
            body.name,
            body.pattern,
            start=body.start,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"rename_clips_in_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class InsertTimeBeforeSelectionSetBody(BaseModel):
    name: str
    frames: int
    set_work_area: bool = False


@app.post("/api/edit/insert_time_before_selection_set")
def insert_time_before_selection_set_api(
    body: InsertTimeBeforeSelectionSetBody,
) -> dict[str, Any]:
    """Ripple-insert empty time before a named selection set."""
    ed = _ed()
    try:
        r = ed.insert_time_before_selection_set(
            body.name,
            body.frames,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"insert_time_before_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class RemoveTimeBeforeSelectionSetBody(BaseModel):
    name: str
    frames: int
    set_work_area: bool = False


@app.post("/api/edit/remove_time_before_selection_set")
def remove_time_before_selection_set_api(
    body: RemoveTimeBeforeSelectionSetBody,
) -> dict[str, Any]:
    """Ripple-remove empty time before a named selection set."""
    ed = _ed()
    try:
        r = ed.remove_time_before_selection_set(
            body.name,
            body.frames,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"remove_time_before_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class LiftSelectionSetBody(BaseModel):
    name: str
    follow_links: bool = False
    set_work_area: bool = False


@app.post("/api/edit/lift_selection_set")
def lift_selection_set_api(
    body: LiftSelectionSetBody,
) -> dict[str, Any]:
    """Premiere Lift on a named selection set."""
    ed = _ed()
    try:
        r = ed.lift_selection_set(
            body.name,
            follow_links=body.follow_links,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"lift_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class DuplicateSelectionSetBody(BaseModel):
    name: str
    offset_frames: int | None = None
    gap_frames: int = 0
    set_work_area: bool = False


@app.post("/api/edit/duplicate_selection_set")
def duplicate_selection_set_api(
    body: DuplicateSelectionSetBody,
) -> dict[str, Any]:
    """Duplicate clips in a named selection set."""
    ed = _ed()
    try:
        r = ed.duplicate_selection_set(
            body.name,
            offset_frames=body.offset_frames,
            gap_frames=body.gap_frames,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"duplicate_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class SlipSelectionSetBody(BaseModel):
    name: str
    delta_src_frames: int
    set_work_area: bool = False


@app.post("/api/edit/slip_selection_set")
def slip_selection_set_api(
    body: SlipSelectionSetBody,
) -> dict[str, Any]:
    """Slip source window on a named selection set."""
    ed = _ed()
    try:
        r = ed.slip_selection_set(
            body.name,
            body.delta_src_frames,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"slip_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class SlideSelectionSetBody(BaseModel):
    name: str
    delta_frames: int
    set_work_area: bool = False


@app.post("/api/edit/slide_selection_set")
def slide_selection_set_api(
    body: SlideSelectionSetBody,
) -> dict[str, Any]:
    """Slide/roll clips in a named selection set."""
    ed = _ed()
    try:
        r = ed.slide_selection_set(
            body.name,
            body.delta_frames,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"slide_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class SplitSelectionSetAtBody(BaseModel):
    name: str
    at_frame: int
    set_work_area: bool = False


@app.post("/api/edit/split_selection_set_at")
def split_selection_set_at_api(
    body: SplitSelectionSetAtBody,
) -> dict[str, Any]:
    """Razor a named selection set at at_frame."""
    ed = _ed()
    try:
        r = ed.split_selection_set_at(
            body.name,
            body.at_frame,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"split_selection_set_at failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class SplitSelectionSetEvenlyBody(BaseModel):
    name: str
    parts: int = 2
    set_work_area: bool = False


@app.post("/api/edit/split_selection_set_evenly")
def split_selection_set_evenly_api(
    body: SplitSelectionSetEvenlyBody,
) -> dict[str, Any]:
    """Even-split clips in a named selection set."""
    ed = _ed()
    try:
        r = ed.split_selection_set_evenly(
            body.name,
            parts=body.parts,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"split_selection_set_evenly failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class SnapSelectionSetToPlayheadBody(BaseModel):
    name: str
    playhead_frame: int
    edge: str = "start"
    mode: str = "relative"
    set_work_area: bool = False


@app.post("/api/edit/snap_selection_set_to_playhead")
def snap_selection_set_to_playhead_api(
    body: SnapSelectionSetToPlayheadBody,
) -> dict[str, Any]:
    """Snap a named selection set to playhead."""
    ed = _ed()
    try:
        r = ed.snap_selection_set_to_playhead(
            body.name,
            body.playhead_frame,
            edge=body.edge,
            mode=body.mode,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"snap_selection_set_to_playhead failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class SplitSelectionSetAtSilencesBody(BaseModel):
    name: str
    noise_db: float = -30.0
    min_duration: float = 0.25
    max_splits: int = 40
    mark: str = "start"
    set_work_area: bool = False


@app.post("/api/edit/split_selection_set_at_silences")
def split_selection_set_at_silences_api(
    body: SplitSelectionSetAtSilencesBody,
) -> dict[str, Any]:
    """Split a named selection set at silences."""
    ed = _ed()
    try:
        r = ed.split_selection_set_at_silences(
            body.name,
            noise_db=body.noise_db,
            min_duration=body.min_duration,
            max_splits=body.max_splits,
            mark=body.mark,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"split_selection_set_at_silences failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class SuggestSilenceCutsSelectionSetBody(BaseModel):
    name: str
    silence_threshold_db: float = -40.0
    min_silence_seconds: float = 0.4
    pad_seconds: float = 0.08
    min_keep_seconds: float = 0.2
    set_work_area: bool = False


@app.post("/api/edit/suggest_silence_cuts_selection_set")
def suggest_silence_cuts_selection_set_api(
    body: SuggestSilenceCutsSelectionSetBody,
) -> dict[str, Any]:
    """Dry silence-cut plans for a named selection set."""
    ed = _ed()
    try:
        r = ed.suggest_silence_cuts_selection_set(
            body.name,
            silence_threshold_db=body.silence_threshold_db,
            min_silence_seconds=body.min_silence_seconds,
            pad_seconds=body.pad_seconds,
            min_keep_seconds=body.min_keep_seconds,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"suggest_silence_cuts_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ApplySilenceToSelectionSetBody(BaseModel):
    name: str
    silence_threshold_db: float = -40.0
    min_silence_seconds: float = 0.4
    pad_seconds: float = 0.08
    min_keep_seconds: float = 0.2
    dry_run: bool = True
    set_work_area: bool = False


@app.post("/api/edit/apply_silence_to_selection_set")
def apply_silence_to_selection_set_api(
    body: ApplySilenceToSelectionSetBody,
) -> dict[str, Any]:
    """Apply silence plan to a named selection set."""
    ed = _ed()
    try:
        r = ed.apply_silence_to_selection_set(
            body.name,
            silence_threshold_db=body.silence_threshold_db,
            min_silence_seconds=body.min_silence_seconds,
            pad_seconds=body.pad_seconds,
            min_keep_seconds=body.min_keep_seconds,
            dry_run=body.dry_run,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"apply_silence_to_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class DuplicateSelectionSetToTrackBody(BaseModel):
    name: str
    track_id: str
    preserve_starts: bool = True
    start_offset: int = 0
    set_work_area: bool = False


@app.post("/api/edit/duplicate_selection_set_to_track")
def duplicate_selection_set_to_track_api(
    body: DuplicateSelectionSetToTrackBody,
) -> dict[str, Any]:
    """Copy a named selection set onto another track."""
    ed = _ed()
    try:
        r = ed.duplicate_selection_set_to_track(
            body.name,
            body.track_id,
            preserve_starts=body.preserve_starts,
            start_offset=body.start_offset,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"duplicate_selection_set_to_track failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class SetSelectionSetFlipBody(BaseModel):
    name: str
    horizontal: bool | None = None
    vertical: bool | None = None
    toggle_h: bool = False
    toggle_v: bool = False
    set_work_area: bool = False


@app.post("/api/edit/set_selection_set_flip")
def set_selection_set_flip_api(
    body: SetSelectionSetFlipBody,
) -> dict[str, Any]:
    """Flip clips in a named selection set."""
    ed = _ed()
    try:
        r = ed.set_selection_set_flip(
            body.name,
            horizontal=body.horizontal,
            vertical=body.vertical,
            toggle_h=body.toggle_h,
            toggle_v=body.toggle_v,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"set_selection_set_flip failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class SetSelectionSetSpeedRippleBody(BaseModel):
    name: str
    speed: float
    set_work_area: bool = False


@app.post("/api/edit/set_selection_set_speed_ripple")
def set_selection_set_speed_ripple_api(
    body: SetSelectionSetSpeedRippleBody,
) -> dict[str, Any]:
    """Set speed with ripple on a named selection set."""
    ed = _ed()
    try:
        r = ed.set_selection_set_speed_ripple(
            body.name,
            body.speed,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"set_selection_set_speed_ripple failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class CropSelectionSetCenterBody(BaseModel):
    name: str
    scale: float = 0.85
    set_work_area: bool = False


@app.post("/api/edit/crop_selection_set_center")
def crop_selection_set_center_api(
    body: CropSelectionSetCenterBody,
) -> dict[str, Any]:
    """Center-crop a named selection set."""
    ed = _ed()
    try:
        r = ed.crop_selection_set_center(
            body.name,
            scale=body.scale,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"crop_selection_set_center failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class VignetteSelectionSetBody(BaseModel):
    name: str
    strength: float = 0.4
    set_work_area: bool = False


@app.post("/api/edit/vignette_selection_set")
def vignette_selection_set_api(
    body: VignetteSelectionSetBody,
) -> dict[str, Any]:
    """Apply vignette to a named selection set."""
    ed = _ed()
    try:
        r = ed.vignette_selection_set(
            body.name,
            strength=body.strength,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"vignette_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class BlurSelectionSetBody(BaseModel):
    name: str
    amount: float = 5.0
    set_work_area: bool = False


@app.post("/api/edit/blur_selection_set")
def blur_selection_set_api(
    body: BlurSelectionSetBody,
) -> dict[str, Any]:
    """Apply blur to a named selection set."""
    ed = _ed()
    try:
        r = ed.blur_selection_set(
            body.name,
            amount=body.amount,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"blur_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class SharpenSelectionSetBody(BaseModel):
    name: str
    amount: float = 1.0
    set_work_area: bool = False


@app.post("/api/edit/sharpen_selection_set")
def sharpen_selection_set_api(
    body: SharpenSelectionSetBody,
) -> dict[str, Any]:
    """Apply sharpen to a named selection set."""
    ed = _ed()
    try:
        r = ed.sharpen_selection_set(
            body.name,
            amount=body.amount,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"sharpen_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class FilmGrainSelectionSetBody(BaseModel):
    name: str
    amount: float = 12.0
    set_work_area: bool = False


@app.post("/api/edit/film_grain_selection_set")
def film_grain_selection_set_api(
    body: FilmGrainSelectionSetBody,
) -> dict[str, Any]:
    """Apply film grain to a named selection set."""
    ed = _ed()
    try:
        r = ed.film_grain_selection_set(
            body.name,
            amount=body.amount,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"film_grain_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class GlowSelectionSetBody(BaseModel):
    name: str
    amount: float = 8.0
    intensity: float = 0.4
    set_work_area: bool = False


@app.post("/api/edit/glow_selection_set")
def glow_selection_set_api(
    body: GlowSelectionSetBody,
) -> dict[str, Any]:
    """Apply glow to a named selection set."""
    ed = _ed()
    try:
        r = ed.glow_selection_set(
            body.name,
            amount=body.amount,
            intensity=body.intensity,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"glow_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class RotateSelectionSetBody(BaseModel):
    name: str
    degrees: float
    set_work_area: bool = False


@app.post("/api/edit/rotate_selection_set")
def rotate_selection_set_api(
    body: RotateSelectionSetBody,
) -> dict[str, Any]:
    """Rotate clips in a named selection set."""
    ed = _ed()
    try:
        r = ed.rotate_selection_set(
            body.name,
            body.degrees,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"rotate_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class CurvesSelectionSetBody(BaseModel):
    name: str
    preset: str = "increase_contrast"
    set_work_area: bool = False


@app.post("/api/edit/curves_selection_set")
def curves_selection_set_api(
    body: CurvesSelectionSetBody,
) -> dict[str, Any]:
    """Apply curves to a named selection set."""
    ed = _ed()
    try:
        r = ed.curves_selection_set(
            body.name,
            preset=body.preset,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"curves_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class WhiteBalanceSelectionSetBody(BaseModel):
    name: str
    temperature: float = 5600.0
    mix: float = 1.0
    set_work_area: bool = False


@app.post("/api/edit/white_balance_selection_set")
def white_balance_selection_set_api(
    body: WhiteBalanceSelectionSetBody,
) -> dict[str, Any]:
    """Apply white balance to a named selection set."""
    ed = _ed()
    try:
        r = ed.white_balance_selection_set(
            body.name,
            temperature=body.temperature,
            mix=body.mix,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"white_balance_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ChromaKeySelectionSetBody(BaseModel):
    name: str
    color: str = "green"
    similarity: float = 0.15
    blend: float = 0.05
    set_work_area: bool = False


@app.post("/api/edit/chroma_key_selection_set")
def chroma_key_selection_set_api(
    body: ChromaKeySelectionSetBody,
) -> dict[str, Any]:
    """Apply chroma key to a named selection set."""
    ed = _ed()
    try:
        r = ed.chroma_key_selection_set(
            body.name,
            color=body.color,
            similarity=body.similarity,
            blend=body.blend,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"chroma_key_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ColorSelectionSetBody(BaseModel):
    name: str
    color: str | None = None
    set_work_area: bool = False


@app.post("/api/edit/color_selection_set")
def color_selection_set_api(
    body: ColorSelectionSetBody,
) -> dict[str, Any]:
    """Set/clear color chip on a named selection set."""
    ed = _ed()
    try:
        r = ed.color_selection_set(
            body.name,
            body.color,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"color_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class PackSelectionSetBody(BaseModel):
    name: str
    gap_frames: int = 0
    set_work_area: bool = False


@app.post("/api/edit/pack_selection_set")
def pack_selection_set_api(
    body: PackSelectionSetBody,
) -> dict[str, Any]:
    """Pack clips in a named selection set left."""
    ed = _ed()
    try:
        r = ed.pack_selection_set(
            body.name,
            gap_frames=body.gap_frames,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"pack_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class DetachAudioSelectionSetBody(BaseModel):
    name: str
    audio_track_id: str | None = None
    audio_start_offset_frames: int = 0
    link: bool = True
    set_work_area: bool = False


@app.post("/api/edit/detach_audio_selection_set")
def detach_audio_selection_set_api(
    body: DetachAudioSelectionSetBody,
) -> dict[str, Any]:
    """Detach audio from video in a named selection set."""
    ed = _ed()
    try:
        r = ed.detach_audio_selection_set(
            body.name,
            audio_track_id=body.audio_track_id,
            audio_start_offset_frames=body.audio_start_offset_frames,
            link=body.link,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"detach_audio_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class StaggerSelectionSetBody(BaseModel):
    name: str
    offset_frames: int
    from_earliest: bool = True
    set_work_area: bool = False


@app.post("/api/edit/stagger_selection_set")
def stagger_selection_set_api(
    body: StaggerSelectionSetBody,
) -> dict[str, Any]:
    """Stagger clips in a named selection set."""
    ed = _ed()
    try:
        r = ed.stagger_selection_set(
            body.name,
            body.offset_frames,
            from_earliest=body.from_earliest,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"stagger_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class MatchSelectionDurationSetBody(BaseModel):
    name: str
    target_clip_id: str | None = None
    target_frames: int | None = None
    clamp: bool = True
    set_work_area: bool = False


@app.post("/api/edit/match_selection_duration_set")
def match_selection_duration_set_api(
    body: MatchSelectionDurationSetBody,
) -> dict[str, Any]:
    """Match duration of clips in a named selection set."""
    ed = _ed()
    try:
        r = ed.match_selection_duration_set(
            body.name,
            target_clip_id=body.target_clip_id,
            target_frames=body.target_frames,
            clamp=body.clamp,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"match_selection_duration_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class IsolateSelectionSetBody(BaseModel):
    name: str
    kind: str | None = None
    set_work_area: bool = False


@app.post("/api/edit/isolate_selection_set")
def isolate_selection_set_api(
    body: IsolateSelectionSetBody,
) -> dict[str, Any]:
    """Isolate a named selection set (mute others)."""
    ed = _ed()
    try:
        r = ed.isolate_selection_set(
            body.name,
            kind=body.kind,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"isolate_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class SelectionJlCutSetBody(BaseModel):
    name: str
    style: str = "j"
    frames: int = 15
    link: bool = True
    set_work_area: bool = False


@app.post("/api/edit/selection_jl_cut_set")
def selection_jl_cut_set_api(
    body: SelectionJlCutSetBody,
) -> dict[str, Any]:
    """J/L cut on a named selection set."""
    ed = _ed()
    try:
        r = ed.selection_jl_cut_set(
            body.name,
            style=body.style,
            frames=body.frames,
            link=body.link,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"selection_jl_cut_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class RippleNudgeSelectionSetBody(BaseModel):
    name: str
    delta_frames: int
    include_self: bool = True
    set_work_area: bool = False


@app.post("/api/edit/ripple_nudge_selection_set")
def ripple_nudge_selection_set_api(
    body: RippleNudgeSelectionSetBody,
) -> dict[str, Any]:
    """Ripple-nudge a named selection set."""
    ed = _ed()
    try:
        r = ed.ripple_nudge_selection_set(
            body.name,
            body.delta_frames,
            include_self=body.include_self,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"ripple_nudge_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class CloseGapsOnSelectionSetTracksBody(BaseModel):
    name: str
    from_frame: int = 0
    set_work_area: bool = False


@app.post("/api/edit/close_gaps_on_selection_set_tracks")
def close_gaps_on_selection_set_tracks_api(
    body: CloseGapsOnSelectionSetTracksBody,
) -> dict[str, Any]:
    """Close gaps on tracks touched by a named selection set."""
    ed = _ed()
    try:
        r = ed.close_gaps_on_selection_set_tracks(
            body.name,
            from_frame=body.from_frame,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"close_gaps_on_selection_set_tracks failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class MoveSelectionSetToTrackBody(BaseModel):
    name: str
    track_id: str
    preserve_starts: bool = True
    stack_start: int | None = None
    set_work_area: bool = False


@app.post("/api/edit/move_selection_set_to_track")
def move_selection_set_to_track_api(
    body: MoveSelectionSetToTrackBody,
) -> dict[str, Any]:
    """Move a named selection set onto another track."""
    ed = _ed()
    try:
        r = ed.move_selection_set_to_track(
            body.name,
            body.track_id,
            preserve_starts=body.preserve_starts,
            stack_start=body.stack_start,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"move_selection_set_to_track failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ExpandSelectionSetLinksBody(BaseModel):
    name: str
    set_work_area: bool = False
    resave: bool = False


@app.post("/api/edit/expand_selection_set_links")
def expand_selection_set_links_api(
    body: ExpandSelectionSetLinksBody,
) -> dict[str, Any]:
    """Expand a named selection set to include link peers."""
    ed = _ed()
    try:
        r = ed.expand_selection_set_links(
            body.name,
            set_work_area=body.set_work_area,
            resave=body.resave,
        )
    except Exception as e:
        raise HTTPException(
            400, f"expand_selection_set_links failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ClipboardCopySelectionSetBody(BaseModel):
    name: str
    set_work_area: bool = False


@app.post("/api/edit/clipboard_copy_selection_set")
def clipboard_copy_selection_set_api(
    body: ClipboardCopySelectionSetBody,
) -> dict[str, Any]:
    """Copy a named selection set to session multi-clip clipboard."""
    ed = _ed()
    try:
        r = ed.clipboard_copy_selection_set(
            body.name,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"clipboard_copy_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class SelectionSetDiagnosticsBody(BaseModel):
    name: str
    set_work_area: bool = False


@app.post("/api/edit/selection_set_diagnostics")
def selection_set_diagnostics_api(
    body: SelectionSetDiagnosticsBody,
) -> dict[str, Any]:
    """Diagnostics for a named selection set."""
    ed = _ed()
    try:
        r = ed.selection_set_diagnostics(
            body.name,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"selection_set_diagnostics failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ApplyLookToSelectionSetBody(BaseModel):
    name: str
    look: str = "cinematic"
    video_only: bool = True
    set_work_area: bool = False


@app.post("/api/edit/apply_look_to_selection_set")
def apply_look_to_selection_set_api(
    body: ApplyLookToSelectionSetBody,
) -> dict[str, Any]:
    """Apply look preset to a named selection set."""
    ed = _ed()
    try:
        r = ed.apply_look_to_selection_set(
            body.name,
            body.look,
            video_only=body.video_only,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"apply_look_to_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ApplyStyleToSelectionSetBody(BaseModel):
    name: str
    styles: str | list[str]
    apply_motion: bool = True
    place_audio_assets: bool = False
    set_work_area: bool = False


@app.post("/api/edit/apply_style_to_selection_set")
def apply_style_to_selection_set_api(
    body: ApplyStyleToSelectionSetBody,
) -> dict[str, Any]:
    """Apply film style preset(s) to a named selection set."""
    ed = _ed()
    try:
        r = ed.apply_style_to_selection_set(
            body.name,
            body.styles,
            apply_motion=body.apply_motion,
            place_audio_assets=body.place_audio_assets,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"apply_style_to_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class CompressionSelectionSetBody(BaseModel):
    name: str
    ratio: float = 4.0
    threshold_db: float = -18.0
    attack_ms: float = 20.0
    release_ms: float = 250.0
    makeup_db: float = 0.0
    set_work_area: bool = False


@app.post("/api/edit/compression_selection_set")
def compression_selection_set_api(
    body: CompressionSelectionSetBody,
) -> dict[str, Any]:
    """Apply compression to a named selection set."""
    ed = _ed()
    try:
        r = ed.compression_selection_set(
            body.name,
            ratio=body.ratio,
            threshold_db=body.threshold_db,
            attack_ms=body.attack_ms,
            release_ms=body.release_ms,
            makeup_db=body.makeup_db,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"compression_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class NoiseReductionSelectionSetBody(BaseModel):
    name: str
    amount: float = 12.0
    set_work_area: bool = False


@app.post("/api/edit/noise_reduction_selection_set")
def noise_reduction_selection_set_api(
    body: NoiseReductionSelectionSetBody,
) -> dict[str, Any]:
    """Apply noise reduction to a named selection set."""
    ed = _ed()
    try:
        r = ed.noise_reduction_selection_set(
            body.name,
            amount=body.amount,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"noise_reduction_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class AudioEqSelectionSetBody(BaseModel):
    name: str
    frequency_hz: float = 1000.0
    gain_db: float = 0.0
    q: float = 1.0
    replace: bool = False
    set_work_area: bool = False


@app.post("/api/edit/audio_eq_selection_set")
def audio_eq_selection_set_api(
    body: AudioEqSelectionSetBody,
) -> dict[str, Any]:
    """Apply parametric EQ band to a named selection set."""
    ed = _ed()
    try:
        r = ed.audio_eq_selection_set(
            body.name,
            frequency_hz=body.frequency_hz,
            gain_db=body.gain_db,
            q=body.q,
            replace=body.replace,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"audio_eq_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ReverseSelectionSetBody(BaseModel):
    name: str
    replace: bool = True
    set_work_area: bool = False


@app.post("/api/edit/reverse_selection_set")
def reverse_selection_set_api(
    body: ReverseSelectionSetBody,
) -> dict[str, Any]:
    """Reverse media for a named selection set (re-encode)."""
    ed = _ed()
    try:
        r = ed.reverse_selection_set(
            body.name,
            replace=body.replace,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"reverse_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class StabilizeSelectionSetBody(BaseModel):
    name: str
    replace: bool = True
    strength: float = 1.0
    video_only: bool = True
    set_work_area: bool = False


@app.post("/api/edit/stabilize_selection_set")
def stabilize_selection_set_api(
    body: StabilizeSelectionSetBody,
) -> dict[str, Any]:
    """Deshake-stabilize a named selection set."""
    ed = _ed()
    try:
        r = ed.stabilize_selection_set(
            body.name,
            replace=body.replace,
            strength=body.strength,
            video_only=body.video_only,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"stabilize_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ReframeSelectionSetBody(BaseModel):
    name: str
    aspect: str = "9:16"
    anchor: str = "center"
    video_only: bool = True
    set_work_area: bool = False


@app.post("/api/edit/reframe_selection_set")
def reframe_selection_set_api(
    body: ReframeSelectionSetBody,
) -> dict[str, Any]:
    """Crop-reframe a named selection set to a target aspect."""
    ed = _ed()
    try:
        r = ed.reframe_selection_set(
            body.name,
            aspect=body.aspect,
            anchor=body.anchor,
            video_only=body.video_only,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"reframe_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class WatermarkSelectionSetBody(BaseModel):
    name: str
    content: str
    position: str = "bottom"
    size: int = 22
    alpha: float = 0.55
    color: str = "white"
    video_only: bool = True
    set_work_area: bool = False


@app.post("/api/edit/watermark_selection_set")
def watermark_selection_set_api(
    body: WatermarkSelectionSetBody,
) -> dict[str, Any]:
    """Apply text watermark to a named selection set."""
    ed = _ed()
    try:
        r = ed.watermark_selection_set(
            body.name,
            body.content,
            position=body.position,
            size=body.size,
            alpha=body.alpha,
            color=body.color,
            video_only=body.video_only,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"watermark_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ApplyLutSelectionSetBody(BaseModel):
    name: str
    path: str
    replace: bool = True
    set_work_area: bool = False


@app.post("/api/edit/apply_lut_selection_set")
def apply_lut_selection_set_api(
    body: ApplyLutSelectionSetBody,
) -> dict[str, Any]:
    """Apply a LUT file to a named selection set."""
    ed = _ed()
    try:
        r = ed.apply_lut_selection_set(
            body.name,
            body.path,
            replace=body.replace,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"apply_lut_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ColorMatchSelectionSetBody(BaseModel):
    name: str
    reference_clip_id: str | None = None
    strength: float = 0.65
    video_only: bool = True
    set_work_area: bool = False


@app.post("/api/edit/color_match_selection_set")
def color_match_selection_set_api(
    body: ColorMatchSelectionSetBody,
) -> dict[str, Any]:
    """Color-match a named selection set toward a reference clip."""
    ed = _ed()
    try:
        r = ed.color_match_selection_set(
            body.name,
            reference_clip_id=body.reference_clip_id,
            strength=body.strength,
            video_only=body.video_only,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"color_match_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class SafeAreaSelectionSetBody(BaseModel):
    name: str
    action: float = 0.90
    title: float = 0.80
    thickness: int = 2
    video_only: bool = True
    set_work_area: bool = False


@app.post("/api/edit/safe_area_selection_set")
def safe_area_selection_set_api(
    body: SafeAreaSelectionSetBody,
) -> dict[str, Any]:
    """Burn safe-area overlays on a named selection set."""
    ed = _ed()
    try:
        r = ed.safe_area_selection_set(
            body.name,
            action=body.action,
            title=body.title,
            thickness=body.thickness,
            video_only=body.video_only,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"safe_area_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class TimecodeSelectionSetBody(BaseModel):
    name: str
    position: str = "bottom"
    size: int = 28
    start: str = "00:00:00:00"
    video_only: bool = True
    set_work_area: bool = False


@app.post("/api/edit/timecode_selection_set")
def timecode_selection_set_api(
    body: TimecodeSelectionSetBody,
) -> dict[str, Any]:
    """Burn timecode overlay on a named selection set."""
    ed = _ed()
    try:
        r = ed.timecode_selection_set(
            body.name,
            position=body.position,
            size=body.size,
            start=body.start,
            video_only=body.video_only,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"timecode_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class KenBurnsSelectionSetBody(BaseModel):
    name: str
    zoom_start: float = 1.0
    zoom_end: float = 1.15
    x_start: float = 0.5
    y_start: float = 0.5
    x_end: float = 0.5
    y_end: float = 0.5
    replace: bool = True
    video_only: bool = True
    set_work_area: bool = False


@app.post("/api/edit/ken_burns_selection_set")
def ken_burns_selection_set_api(
    body: KenBurnsSelectionSetBody,
) -> dict[str, Any]:
    """Apply Ken Burns zoom/pan to a named selection set."""
    ed = _ed()
    try:
        r = ed.ken_burns_selection_set(
            body.name,
            zoom_start=body.zoom_start,
            zoom_end=body.zoom_end,
            x_start=body.x_start,
            y_start=body.y_start,
            x_end=body.x_end,
            y_end=body.y_end,
            replace=body.replace,
            video_only=body.video_only,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"ken_burns_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class LumaKeySelectionSetBody(BaseModel):
    name: str
    threshold: float = 0.1
    tolerance: float = 0.1
    replace: bool = True
    video_only: bool = True
    set_work_area: bool = False


@app.post("/api/edit/luma_key_selection_set")
def luma_key_selection_set_api(
    body: LumaKeySelectionSetBody,
) -> dict[str, Any]:
    """Apply luma key to a named selection set."""
    ed = _ed()
    try:
        r = ed.luma_key_selection_set(
            body.name,
            threshold=body.threshold,
            tolerance=body.tolerance,
            replace=body.replace,
            video_only=body.video_only,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"luma_key_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ShapeMaskSelectionSetBody(BaseModel):
    name: str
    shape: str = "circle"
    cx: float = 0.5
    cy: float = 0.5
    size: float = 0.5
    feather: float = 0.05
    width: float = 0.5
    height: float = 0.5
    invert: bool = False
    replace: bool = True
    video_only: bool = True
    set_work_area: bool = False


@app.post("/api/edit/shape_mask_selection_set")
def shape_mask_selection_set_api(
    body: ShapeMaskSelectionSetBody,
) -> dict[str, Any]:
    """Apply shape mask to a named selection set."""
    ed = _ed()
    try:
        r = ed.shape_mask_selection_set(
            body.name,
            shape=body.shape,
            cx=body.cx,
            cy=body.cy,
            size=body.size,
            feather=body.feather,
            width=body.width,
            height=body.height,
            invert=body.invert,
            replace=body.replace,
            video_only=body.video_only,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"shape_mask_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ApplyReviewOverlaysSelectionSetBody(BaseModel):
    name: str
    watermark: str | None = "REVIEW"
    safe_area: bool = True
    timecode: bool = True
    watermark_position: str = "bottom"
    timecode_position: str = "bottom"
    video_only: bool = True
    set_work_area: bool = False


@app.post("/api/edit/apply_review_overlays_selection_set")
def apply_review_overlays_selection_set_api(
    body: ApplyReviewOverlaysSelectionSetBody,
) -> dict[str, Any]:
    """Apply review overlays to a named selection set."""
    ed = _ed()
    try:
        r = ed.apply_review_overlays_selection_set(
            body.name,
            watermark=body.watermark,
            safe_area=body.safe_area,
            timecode=body.timecode,
            watermark_position=body.watermark_position,
            timecode_position=body.timecode_position,
            video_only=body.video_only,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"apply_review_overlays_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ClearReviewOverlaysSelectionSetBody(BaseModel):
    name: str
    watermark: bool = True
    safe_area: bool = True
    timecode: bool = True
    video_only: bool = True
    set_work_area: bool = False


@app.post("/api/edit/clear_review_overlays_selection_set")
def clear_review_overlays_selection_set_api(
    body: ClearReviewOverlaysSelectionSetBody,
) -> dict[str, Any]:
    """Clear review overlays from a named selection set."""
    ed = _ed()
    try:
        r = ed.clear_review_overlays_selection_set(
            body.name,
            watermark=body.watermark,
            safe_area=body.safe_area,
            timecode=body.timecode,
            video_only=body.video_only,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"clear_review_overlays_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class BakeSelectionSetBody(BaseModel):
    name: str
    replace: bool = True
    clear_effects: bool = True
    include_audio: bool = True
    set_work_area: bool = False


@app.post("/api/edit/bake_selection_set")
def bake_selection_set_api(
    body: BakeSelectionSetBody,
) -> dict[str, Any]:
    """Bake FX into media for a named selection set."""
    ed = _ed()
    try:
        r = ed.bake_selection_set(
            body.name,
            replace=body.replace,
            clear_effects=body.clear_effects,
            include_audio=body.include_audio,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"bake_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class RazorSelectionSetAtMarkersBody(BaseModel):
    name: str
    marker_ids: list[str] | None = None
    set_work_area: bool = False


@app.post("/api/edit/razor_selection_set_at_markers")
def razor_selection_set_at_markers_api(
    body: RazorSelectionSetAtMarkersBody,
) -> dict[str, Any]:
    """Razor a named selection set at marker frames."""
    ed = _ed()
    try:
        r = ed.razor_selection_set_at_markers(
            body.name,
            marker_ids=body.marker_ids,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"razor_selection_set_at_markers failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class FreezeSelectionSetAtBody(BaseModel):
    name: str
    timeline_frame: int
    duration_frames: int = 30
    set_work_area: bool = False


@app.post("/api/edit/freeze_selection_set_at")
def freeze_selection_set_at_api(
    body: FreezeSelectionSetAtBody,
) -> dict[str, Any]:
    """Freeze stills on a named selection set at a timeline frame."""
    ed = _ed()
    try:
        r = ed.freeze_selection_set_at(
            body.name,
            body.timeline_frame,
            duration_frames=body.duration_frames,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"freeze_selection_set_at failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class MarkersFromSelectionSetBody(BaseModel):
    name: str
    edge: str = "start"
    prefix: str = "Sel "
    color: str = "#4cc9f0"
    clear_matching_prefix: bool = False
    set_work_area: bool = False


@app.post("/api/edit/markers_from_selection_set")
def markers_from_selection_set_api(
    body: MarkersFromSelectionSetBody,
) -> dict[str, Any]:
    """Add markers at clip edges of a named selection set."""
    ed = _ed()
    try:
        r = ed.markers_from_selection_set(
            body.name,
            edge=body.edge,
            prefix=body.prefix,
            color=body.color,
            clear_matching_prefix=body.clear_matching_prefix,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"markers_from_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class MatchFrameSelectionSetBody(BaseModel):
    name: str
    timeline_frame: int | None = None
    set_work_area: bool = False


@app.post("/api/edit/match_frame_selection_set")
def match_frame_selection_set_api(
    body: MatchFrameSelectionSetBody,
) -> dict[str, Any]:
    """Batch match_frame for a named selection set."""
    ed = _ed()
    try:
        r = ed.match_frame_selection_set(
            body.name,
            timeline_frame=body.timeline_frame,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"match_frame_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class RippleTrimSelectionSetEdgesBody(BaseModel):
    name: str
    head_src_frames: int = 0
    tail_src_frames: int = 0
    set_work_area: bool = False


@app.post("/api/edit/ripple_trim_selection_set_edges")
def ripple_trim_selection_set_edges_api(
    body: RippleTrimSelectionSetEdgesBody,
) -> dict[str, Any]:
    """Ripple-trim head/tail on a named selection set."""
    ed = _ed()
    try:
        r = ed.ripple_trim_selection_set_edges(
            body.name,
            head_src_frames=body.head_src_frames,
            tail_src_frames=body.tail_src_frames,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"ripple_trim_selection_set_edges failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class DuplicateSelectionSetBlockBody(BaseModel):
    name: str
    gap_frames: int = 0
    set_work_area: bool = False


@app.post("/api/edit/duplicate_selection_set_block")
def duplicate_selection_set_block_api(
    body: DuplicateSelectionSetBlockBody,
) -> dict[str, Any]:
    """Duplicate a named selection set as a rigid block."""
    ed = _ed()
    try:
        r = ed.duplicate_selection_set_block(
            body.name,
            gap_frames=body.gap_frames,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"duplicate_selection_set_block failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class AlignSelectionSetEndsBody(BaseModel):
    name: str
    to_frame: int | None = None
    set_work_area: bool = False


@app.post("/api/edit/align_selection_set_ends")
def align_selection_set_ends_api(
    body: AlignSelectionSetEndsBody,
) -> dict[str, Any]:
    """Align named selection set clip ends to a frame."""
    ed = _ed()
    try:
        r = ed.align_selection_set_ends(
            body.name,
            to_frame=body.to_frame,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"align_selection_set_ends failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class EnsureSelectionSetProxiesBody(BaseModel):
    name: str
    height: int = 360
    force: bool = False
    set_work_area: bool = False


@app.post("/api/edit/ensure_selection_set_proxies")
def ensure_selection_set_proxies_api(
    body: EnsureSelectionSetProxiesBody,
) -> dict[str, Any]:
    """Ensure media proxies for a named selection set."""
    ed = _ed()
    try:
        r = ed.ensure_selection_set_proxies(
            body.name,
            height=body.height,
            force=body.force,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"ensure_selection_set_proxies failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ClearSelectionSetLutsBody(BaseModel):
    name: str
    video_only: bool = True
    set_work_area: bool = False


@app.post("/api/edit/clear_selection_set_luts")
def clear_selection_set_luts_api(
    body: ClearSelectionSetLutsBody,
) -> dict[str, Any]:
    """Clear lut3d effects on a named selection set."""
    ed = _ed()
    try:
        r = ed.clear_selection_set_luts(
            body.name,
            video_only=body.video_only,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"clear_selection_set_luts failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class RaiseSelectionSetTracksBody(BaseModel):
    name: str
    steps: int = 1
    set_work_area: bool = False


@app.post("/api/edit/raise_selection_set_tracks")
def raise_selection_set_tracks_api(
    body: RaiseSelectionSetTracksBody,
) -> dict[str, Any]:
    """Raise tracks touched by a named selection set."""
    ed = _ed()
    try:
        r = ed.raise_selection_set_tracks(
            body.name,
            steps=body.steps,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"raise_selection_set_tracks failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class LowerSelectionSetTracksBody(BaseModel):
    name: str
    steps: int = 1
    set_work_area: bool = False


@app.post("/api/edit/lower_selection_set_tracks")
def lower_selection_set_tracks_api(
    body: LowerSelectionSetTracksBody,
) -> dict[str, Any]:
    """Lower tracks touched by a named selection set."""
    ed = _ed()
    try:
        r = ed.lower_selection_set_tracks(
            body.name,
            steps=body.steps,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"lower_selection_set_tracks failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ClearSelectionSetShapeMasksBody(BaseModel):
    name: str
    video_only: bool = True
    set_work_area: bool = False


@app.post("/api/edit/clear_selection_set_shape_masks")
def clear_selection_set_shape_masks_api(
    body: ClearSelectionSetShapeMasksBody,
) -> dict[str, Any]:
    """Clear shape_mask effects on a named selection set."""
    ed = _ed()
    try:
        r = ed.clear_selection_set_shape_masks(
            body.name,
            video_only=body.video_only,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"clear_selection_set_shape_masks failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class RenameSelectionSetTracksBody(BaseModel):
    name: str
    track_name: str | None = None
    prefix: str | None = None
    suffix: str | None = None
    set_work_area: bool = False


@app.post("/api/edit/rename_selection_set_tracks")
def rename_selection_set_tracks_api(
    body: RenameSelectionSetTracksBody,
) -> dict[str, Any]:
    """Rename tracks touched by a named selection set."""
    ed = _ed()
    try:
        r = ed.rename_selection_set_tracks(
            body.name,
            track_name=body.track_name,
            prefix=body.prefix,
            suffix=body.suffix,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"rename_selection_set_tracks failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ClearSelectionSetSafeAreasBody(BaseModel):
    name: str
    video_only: bool = True
    set_work_area: bool = False


@app.post("/api/edit/clear_selection_set_safe_areas")
def clear_selection_set_safe_areas_api(
    body: ClearSelectionSetSafeAreasBody,
) -> dict[str, Any]:
    """Clear safe_area effects on a named selection set."""
    ed = _ed()
    try:
        r = ed.clear_selection_set_safe_areas(
            body.name,
            video_only=body.video_only,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"clear_selection_set_safe_areas failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ClearSelectionSetTimecodesBody(BaseModel):
    name: str
    video_only: bool = True
    set_work_area: bool = False


@app.post("/api/edit/clear_selection_set_timecodes")
def clear_selection_set_timecodes_api(
    body: ClearSelectionSetTimecodesBody,
) -> dict[str, Any]:
    """Clear timecode effects on a named selection set."""
    ed = _ed()
    try:
        r = ed.clear_selection_set_timecodes(
            body.name,
            video_only=body.video_only,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"clear_selection_set_timecodes failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ClearSelectionSetWatermarksBody(BaseModel):
    name: str
    video_only: bool = True
    set_work_area: bool = False


@app.post("/api/edit/clear_selection_set_watermarks")
def clear_selection_set_watermarks_api(
    body: ClearSelectionSetWatermarksBody,
) -> dict[str, Any]:
    """Clear watermark effects on a named selection set."""
    ed = _ed()
    try:
        r = ed.clear_selection_set_watermarks(
            body.name,
            video_only=body.video_only,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"clear_selection_set_watermarks failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class TrimSelectionSetEdgesBody(BaseModel):
    name: str
    head_frames: int = 0
    tail_frames: int = 0
    set_work_area: bool = False


@app.post("/api/edit/trim_selection_set_edges")
def trim_selection_set_edges_api(
    body: TrimSelectionSetEdgesBody,
) -> dict[str, Any]:
    """Trim head/tail timeline frames on a named selection set."""
    ed = _ed()
    try:
        r = ed.trim_selection_set_edges(
            body.name,
            head_frames=body.head_frames,
            tail_frames=body.tail_frames,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"trim_selection_set_edges failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ExtendSelectionSetToNextBody(BaseModel):
    name: str
    set_work_area: bool = False


@app.post("/api/edit/extend_selection_set_to_next")
def extend_selection_set_to_next_api(
    body: ExtendSelectionSetToNextBody,
) -> dict[str, Any]:
    """Extend named-set clips to the next neighbor."""
    ed = _ed()
    try:
        r = ed.extend_selection_set_to_next(
            body.name,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"extend_selection_set_to_next failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ReverseSelectionSetOrderBody(BaseModel):
    name: str
    set_work_area: bool = False


@app.post("/api/edit/reverse_selection_set_order")
def reverse_selection_set_order_api(
    body: ReverseSelectionSetOrderBody,
) -> dict[str, Any]:
    """Reverse timeline order of named-set clips per track."""
    ed = _ed()
    try:
        r = ed.reverse_selection_set_order(
            body.name,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"reverse_selection_set_order failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class FillSelectionSetGapsBody(BaseModel):
    name: str
    mode: str = "slug"
    color: str = "#000000"
    set_work_area: bool = False


@app.post("/api/edit/fill_selection_set_gaps")
def fill_selection_set_gaps_api(
    body: FillSelectionSetGapsBody,
) -> dict[str, Any]:
    """Fill holes between named-set clips."""
    ed = _ed()
    try:
        r = ed.fill_selection_set_gaps(
            body.name,
            mode=body.mode,
            color=body.color,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"fill_selection_set_gaps failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class RetargetSelectionSetMediaBody(BaseModel):
    name: str
    media_id: str
    keep_source_range: bool = True
    set_work_area: bool = False


@app.post("/api/edit/retarget_selection_set_media")
def retarget_selection_set_media_api(
    body: RetargetSelectionSetMediaBody,
) -> dict[str, Any]:
    """Retarget named-set clips to a media_id."""
    ed = _ed()
    try:
        r = ed.retarget_selection_set_media(
            body.name,
            body.media_id,
            keep_source_range=body.keep_source_range,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"retarget_selection_set_media failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class MarkersAtSelectionSetMidsBody(BaseModel):
    name: str
    prefix: str = "Mid "
    color: str = "#90be6d"
    set_work_area: bool = False


@app.post("/api/edit/markers_at_selection_set_mids")
def markers_at_selection_set_mids_api(
    body: MarkersAtSelectionSetMidsBody,
) -> dict[str, Any]:
    """Place mid-clip markers for a named selection set."""
    ed = _ed()
    try:
        r = ed.markers_at_selection_set_mids(
            body.name,
            prefix=body.prefix,
            color=body.color,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"markers_at_selection_set_mids failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ClearSelectionSetSubtitlesBody(BaseModel):
    name: str
    video_only: bool = True
    set_work_area: bool = False


@app.post("/api/edit/clear_selection_set_subtitles")
def clear_selection_set_subtitles_api(
    body: ClearSelectionSetSubtitlesBody,
) -> dict[str, Any]:
    """Clear subtitles burn-in on a named selection set."""
    ed = _ed()
    try:
        r = ed.clear_selection_set_subtitles(
            body.name,
            video_only=body.video_only,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"clear_selection_set_subtitles failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class FreezeSelectionSetMidsBody(BaseModel):
    name: str
    duration_frames: int = 30
    insert: bool = True
    set_work_area: bool = False


@app.post("/api/edit/freeze_selection_set_mids")
def freeze_selection_set_mids_api(
    body: FreezeSelectionSetMidsBody,
) -> dict[str, Any]:
    """Freeze mid-frame stills for a named selection set."""
    ed = _ed()
    try:
        r = ed.freeze_selection_set_mids(
            body.name,
            duration_frames=body.duration_frames,
            insert=body.insert,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"freeze_selection_set_mids failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class TrimSelectionSetToPlayheadBody(BaseModel):
    name: str
    playhead_frame: int
    edge: str = "head"
    mode: str = "ripple"
    set_work_area: bool = False


@app.post("/api/edit/trim_selection_set_to_playhead")
def trim_selection_set_to_playhead_api(
    body: TrimSelectionSetToPlayheadBody,
) -> dict[str, Any]:
    """Trim named-set clips at playhead (Q/W batch)."""
    ed = _ed()
    try:
        r = ed.trim_selection_set_to_playhead(
            body.name,
            body.playhead_frame,
            edge=body.edge,
            mode=body.mode,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"trim_selection_set_to_playhead failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ReviewSelectionSetBody(BaseModel):
    name: str
    min_clip_seconds: float = 0.4
    set_work_area: bool = False


@app.post("/api/edit/review_selection_set")
def review_selection_set_api(
    body: ReviewSelectionSetBody,
) -> dict[str, Any]:
    """Craft review for a named selection set."""
    ed = _ed()
    try:
        r = ed.review_selection_set(
            body.name,
            min_clip_seconds=body.min_clip_seconds,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"review_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class SwapSelectionSetPairBody(BaseModel):
    name: str
    clip_id_a: str | None = None
    clip_id_b: str | None = None
    set_work_area: bool = False


@app.post("/api/edit/swap_selection_set_pair")
def swap_selection_set_pair_api(
    body: SwapSelectionSetPairBody,
) -> dict[str, Any]:
    """Swap starts of two clips in a named selection set."""
    ed = _ed()
    try:
        r = ed.swap_selection_set_pair(
            body.name,
            clip_id_a=body.clip_id_a,
            clip_id_b=body.clip_id_b,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"swap_selection_set_pair failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class PrepareSelectionSetExportBody(BaseModel):
    name: str
    unlock_tracks: bool = True
    export_set_work_area: bool = True
    pack_gaps: bool = False
    gap_frames: int = 0
    set_work_area: bool = False


@app.post("/api/edit/prepare_selection_set_export")
def prepare_selection_set_export_api(
    body: PrepareSelectionSetExportBody,
) -> dict[str, Any]:
    """Prepare a named selection set for export."""
    ed = _ed()
    try:
        r = ed.prepare_selection_set_export(
            body.name,
            unlock_tracks=body.unlock_tracks,
            export_set_work_area=body.export_set_work_area,
            pack_gaps=body.pack_gaps,
            gap_frames=body.gap_frames,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"prepare_selection_set_export failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class RippleDeleteSelectionSetBody(BaseModel):
    name: str
    set_work_area: bool = False


@app.post("/api/edit/ripple_delete_selection_set")
def ripple_delete_selection_set_api(
    body: RippleDeleteSelectionSetBody,
) -> dict[str, Any]:
    """Ripple-delete all clips in a named selection set."""
    ed = _ed()
    try:
        r = ed.ripple_delete_selection_set(
            body.name,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"ripple_delete_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class AnalyzeSelectionSetAudioBody(BaseModel):
    name: str
    image_path: str | None = None
    silence_threshold_db: float = -40.0
    min_silence_seconds: float = 0.5
    filename: str = "selection_set_mix_analyze.wav"
    set_work_area: bool = False


@app.post("/api/edit/analyze_selection_set_audio")
def analyze_selection_set_audio_api(
    body: AnalyzeSelectionSetAudioBody,
) -> dict[str, Any]:
    """Analyze loudness/silence for a named selection set mix."""
    ed = _ed()
    try:
        r = ed.analyze_selection_set_audio(
            body.name,
            image_path=body.image_path,
            silence_threshold_db=body.silence_threshold_db,
            min_silence_seconds=body.min_silence_seconds,
            filename=body.filename,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"analyze_selection_set_audio failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class DeliveryCheckSelectionSetBody(BaseModel):
    name: str
    filename: str = "selection_set_delivery.mp4"
    preset: str = "streaming"
    normalize_preset: str | None = None
    set_work_area: bool = False


@app.post("/api/edit/delivery_check_selection_set")
def delivery_check_selection_set_api(
    body: DeliveryCheckSelectionSetBody,
) -> dict[str, Any]:
    """Export named set then run delivery_check gates."""
    ed = _ed()
    try:
        r = ed.delivery_check_selection_set(
            body.name,
            filename=body.filename,
            preset=body.preset,
            normalize_preset=body.normalize_preset,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"delivery_check_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class MakeSelectionSetContactSheetBody(BaseModel):
    name: str
    output_path: str | None = None
    max_tiles: int = 12
    tile_width: int = 160
    tile_height: int = 90
    cols: int | None = None
    set_work_area: bool = False


@app.post("/api/edit/make_selection_set_contact_sheet")
def make_selection_set_contact_sheet_api(
    body: MakeSelectionSetContactSheetBody,
) -> dict[str, Any]:
    """Build contact sheet for a named selection set."""
    ed = _ed()
    try:
        r = ed.make_selection_set_contact_sheet(
            body.name,
            output_path=body.output_path,
            max_tiles=body.max_tiles,
            tile_width=body.tile_width,
            tile_height=body.tile_height,
            cols=body.cols,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"make_selection_set_contact_sheet failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class FinishSelectionSetReviewExportBody(BaseModel):
    name: str
    filename: str = "selection_set_client_review.mp4"
    watermark: str | None = "REVIEW"
    safe_area: bool = True
    timecode: bool = True
    clear_overlays: bool = True
    normalize_preset: str | None = None
    set_work_area: bool = False


@app.post("/api/edit/finish_selection_set_review_export")
def finish_selection_set_review_export_api(
    body: FinishSelectionSetReviewExportBody,
) -> dict[str, Any]:
    """Client review one-shot for a named selection set."""
    ed = _ed()
    try:
        r = ed.finish_selection_set_review_export(
            body.name,
            filename=body.filename,
            watermark=body.watermark,
            safe_area=body.safe_area,
            timecode=body.timecode,
            clear_overlays=body.clear_overlays,
            normalize_preset=body.normalize_preset,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"finish_selection_set_review_export failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


@app.get("/api/edit/selection_set_tool_catalog")
def selection_set_tool_catalog_api() -> dict[str, Any]:
    """List named selection-set tools by category."""
    ed = _ed()
    try:
        return ed.selection_set_tool_catalog()
    except Exception as e:
        raise HTTPException(
            400, f"selection_set_tool_catalog failed: {e}",
        ) from e


class ExportSelectionSetToolCatalogBody(BaseModel):
    path: str | None = None
    write_markdown: bool = True
    filename: str = "selection_set_tool_catalog.json"


@app.post("/api/edit/export_selection_set_tool_catalog")
def export_selection_set_tool_catalog_api(
    body: ExportSelectionSetToolCatalogBody,
) -> dict[str, Any]:
    """Export selection-set tool catalog to disk."""
    ed = _ed()
    try:
        r = ed.export_selection_set_tool_catalog(
            path=body.path,
            write_markdown=body.write_markdown,
            filename=body.filename,
        )
    except Exception as e:
        raise HTTPException(
            400, f"export_selection_set_tool_catalog failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class SaveSelectionPipelinePresetBody(BaseModel):
    name: str
    steps: list[str]
    note: str = ""
    overwrite: bool = True


@app.post("/api/edit/save_selection_pipeline_preset")
def save_selection_pipeline_preset_api(
    body: SaveSelectionPipelinePresetBody,
) -> dict[str, Any]:
    """Save a named selection pipeline preset."""
    ed = _ed()
    try:
        r = ed.save_selection_pipeline_preset(
            body.name,
            body.steps,
            note=body.note,
            overwrite=body.overwrite,
        )
    except Exception as e:
        raise HTTPException(
            400, f"save_selection_pipeline_preset failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


@app.get("/api/edit/list_selection_pipeline_presets")
def list_selection_pipeline_presets_api() -> dict[str, Any]:
    """List selection pipeline presets."""
    ed = _ed()
    try:
        return ed.list_selection_pipeline_presets()
    except Exception as e:
        raise HTTPException(
            400, f"list_selection_pipeline_presets failed: {e}",
        ) from e


class DeleteSelectionPipelinePresetBody(BaseModel):
    name: str


@app.post("/api/edit/delete_selection_pipeline_preset")
def delete_selection_pipeline_preset_api(
    body: DeleteSelectionPipelinePresetBody,
) -> dict[str, Any]:
    """Delete a selection pipeline preset."""
    ed = _ed()
    try:
        r = ed.delete_selection_pipeline_preset(body.name)
    except Exception as e:
        raise HTTPException(
            400, f"delete_selection_pipeline_preset failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class RenameSelectionPipelinePresetBody(BaseModel):
    old_name: str
    new_name: str
    overwrite: bool = False


@app.post("/api/edit/rename_selection_pipeline_preset")
def rename_selection_pipeline_preset_api(
    body: RenameSelectionPipelinePresetBody,
) -> dict[str, Any]:
    """Rename a selection pipeline preset."""
    ed = _ed()
    try:
        r = ed.rename_selection_pipeline_preset(
            body.old_name,
            body.new_name,
            overwrite=body.overwrite,
        )
    except Exception as e:
        raise HTTPException(
            400, f"rename_selection_pipeline_preset failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class CopySelectionPipelinePresetBody(BaseModel):
    source: str
    dest: str
    overwrite: bool = True
    note: str | None = None


@app.post("/api/edit/copy_selection_pipeline_preset")
def copy_selection_pipeline_preset_api(
    body: CopySelectionPipelinePresetBody,
) -> dict[str, Any]:
    """Copy a selection pipeline preset."""
    ed = _ed()
    try:
        r = ed.copy_selection_pipeline_preset(
            body.source,
            body.dest,
            overwrite=body.overwrite,
            note=body.note,
        )
    except Exception as e:
        raise HTTPException(
            400, f"copy_selection_pipeline_preset failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class RunSelectionPipelinePresetBody(BaseModel):
    name: str
    clip_ids: list[str] | None = None
    selection_set: str | None = None
    dry_run: bool = False
    execute_read_only: bool = True
    normalize_preset: str | None = None
    social_variants: list[str] | None = None
    set_work_area: bool = False


@app.post("/api/edit/run_selection_pipeline_preset")
def run_selection_pipeline_preset_api(
    body: RunSelectionPipelinePresetBody,
) -> dict[str, Any]:
    """Run or dry-run a saved pipeline preset."""
    ed = _ed()
    try:
        r = ed.run_selection_pipeline_preset(
            body.name,
            clip_ids=body.clip_ids,
            selection_set=body.selection_set,
            dry_run=body.dry_run,
            execute_read_only=body.execute_read_only,
            normalize_preset=body.normalize_preset,
            social_variants=body.social_variants,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"run_selection_pipeline_preset failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ExportSelectionPipelinePresetsBody(BaseModel):
    path: str | None = None
    names: list[str] | None = None
    filename: str = "selection_pipeline_presets_export.json"


@app.post("/api/edit/export_selection_pipeline_presets")
def export_selection_pipeline_presets_api(
    body: ExportSelectionPipelinePresetsBody,
) -> dict[str, Any]:
    """Export pipeline presets to JSON."""
    ed = _ed()
    try:
        r = ed.export_selection_pipeline_presets(
            path=body.path,
            names=body.names,
            filename=body.filename,
        )
    except Exception as e:
        raise HTTPException(
            400, f"export_selection_pipeline_presets failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class ImportSelectionPipelinePresetsBody(BaseModel):
    path: str
    mode: str = "merge"
    overwrite: bool = True
    names: list[str] | None = None
    validate_steps: bool = True


@app.post("/api/edit/import_selection_pipeline_presets")
def import_selection_pipeline_presets_api(
    body: ImportSelectionPipelinePresetsBody,
) -> dict[str, Any]:
    """Import pipeline presets from JSON."""
    ed = _ed()
    try:
        r = ed.import_selection_pipeline_presets(
            body.path,
            mode=body.mode,
            overwrite=body.overwrite,
            names=body.names,
            validate_steps=body.validate_steps,
        )
    except Exception as e:
        raise HTTPException(
            400, f"import_selection_pipeline_presets failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class SaveSelectionSetBody(BaseModel):
    name: str
    clip_ids: list[str]
    note: str = ""
    overwrite: bool = True


@app.post("/api/edit/save_selection_set")
def save_selection_set_api(body: SaveSelectionSetBody) -> dict[str, Any]:
    """Persist a named selection set on the project bundle."""
    ed = _ed()
    try:
        r = ed.save_selection_set(
            body.name,
            body.clip_ids,
            note=body.note,
            overwrite=body.overwrite,
        )
    except Exception as e:
        raise HTTPException(400, f"save_selection_set failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


@app.get("/api/edit/list_selection_sets")
def list_selection_sets_api() -> dict[str, Any]:
    """List named selection sets."""
    ed = _ed()
    try:
        return ed.list_selection_sets()
    except Exception as e:
        raise HTTPException(400, f"list_selection_sets failed: {e}") from e


class LoadSelectionSetBody(BaseModel):
    name: str
    set_work_area: bool = True
    drop_missing: bool = True


@app.post("/api/edit/load_selection_set")
def load_selection_set_api(body: LoadSelectionSetBody) -> dict[str, Any]:
    """Load a named selection set; optionally set work In/Out."""
    ed = _ed()
    try:
        r = ed.load_selection_set(
            body.name,
            set_work_area=body.set_work_area,
            drop_missing=body.drop_missing,
        )
    except Exception as e:
        raise HTTPException(400, f"load_selection_set failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class DeleteSelectionSetBody(BaseModel):
    name: str


@app.post("/api/edit/delete_selection_set")
def delete_selection_set_api(body: DeleteSelectionSetBody) -> dict[str, Any]:
    """Delete a named selection set."""
    ed = _ed()
    try:
        r = ed.delete_selection_set(body.name)
    except Exception as e:
        raise HTTPException(400, f"delete_selection_set failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class AgentFinishSelectionSetBody(BaseModel):
    name: str
    repair: bool = True
    export: bool = True
    filename: str | None = None
    write_checklist: bool = True
    write_card: bool = True
    force_export: bool = False
    normalize_preset: str | None = None
    ensure_proxies: bool = False
    set_work_area: bool = True


@app.post("/api/edit/agent_finish_selection_set")
def agent_finish_selection_set_api(
    body: AgentFinishSelectionSetBody,
) -> dict[str, Any]:
    """Load named selection set then agent_finish_selection."""
    ed = _ed()
    try:
        r = ed.agent_finish_selection_set(
            body.name,
            repair=body.repair,
            export=body.export,
            filename=body.filename,
            write_checklist=body.write_checklist,
            write_card=body.write_card,
            force_export=body.force_export,
            normalize_preset=body.normalize_preset,
            ensure_proxies=body.ensure_proxies,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"agent_finish_selection_set failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class RunSelectionSetPipelineBody(BaseModel):
    name: str
    steps: list[str] | None = None
    normalize_preset: str | None = None
    social_variants: list[str] | None = None
    set_work_area: bool = True


@app.post("/api/edit/run_selection_set_pipeline")
def run_selection_set_pipeline_api(
    body: RunSelectionSetPipelineBody,
) -> dict[str, Any]:
    """Load named selection set then run_selection_pipeline."""
    ed = _ed()
    try:
        r = ed.run_selection_set_pipeline(
            body.name,
            steps=body.steps,
            normalize_preset=body.normalize_preset,
            social_variants=body.social_variants,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(
            400, f"run_selection_set_pipeline failed: {e}",
        ) from e
    return {**r, "timeline": ed.timeline_view()}


class DiffSelectionSetsBody(BaseModel):
    name_a: str
    name_b: str
    resolve_live: bool = True


@app.post("/api/edit/diff_selection_sets")
def diff_selection_sets_api(body: DiffSelectionSetsBody) -> dict[str, Any]:
    """Compare two named selection sets."""
    ed = _ed()
    try:
        r = ed.diff_selection_sets(
            body.name_a,
            body.name_b,
            resolve_live=body.resolve_live,
        )
    except Exception as e:
        raise HTTPException(400, f"diff_selection_sets failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class MergeSelectionSetsBody(BaseModel):
    names: list[str]
    out_name: str
    mode: str = "union"
    note: str = ""
    overwrite: bool = True
    set_work_area: bool = False


@app.post("/api/edit/merge_selection_sets")
def merge_selection_sets_api(body: MergeSelectionSetsBody) -> dict[str, Any]:
    """Merge named selection sets into out_name."""
    ed = _ed()
    try:
        r = ed.merge_selection_sets(
            body.names,
            body.out_name,
            mode=body.mode,
            note=body.note,
            overwrite=body.overwrite,
            set_work_area=body.set_work_area,
        )
    except Exception as e:
        raise HTTPException(400, f"merge_selection_sets failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class RenameSelectionSetBody(BaseModel):
    old_name: str
    new_name: str
    overwrite: bool = False


@app.post("/api/edit/rename_selection_set")
def rename_selection_set_api(body: RenameSelectionSetBody) -> dict[str, Any]:
    """Rename a named selection set."""
    ed = _ed()
    try:
        r = ed.rename_selection_set(
            body.old_name,
            body.new_name,
            overwrite=body.overwrite,
        )
    except Exception as e:
        raise HTTPException(400, f"rename_selection_set failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class CopySelectionSetBody(BaseModel):
    source: str
    dest: str
    overwrite: bool = True
    note: str | None = None
    resolve_live: bool = True


@app.post("/api/edit/copy_selection_set")
def copy_selection_set_api(body: CopySelectionSetBody) -> dict[str, Any]:
    """Copy a named selection set to a new name."""
    ed = _ed()
    try:
        r = ed.copy_selection_set(
            body.source,
            body.dest,
            overwrite=body.overwrite,
            note=body.note,
            resolve_live=body.resolve_live,
        )
    except Exception as e:
        raise HTTPException(400, f"copy_selection_set failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class ExportSelectionSetsBody(BaseModel):
    path: str | None = None
    names: list[str] | None = None
    resolve_live: bool = False
    filename: str = "selection_sets_export.json"


@app.post("/api/edit/export_selection_sets")
def export_selection_sets_api(body: ExportSelectionSetsBody) -> dict[str, Any]:
    """Export named selection sets to JSON."""
    ed = _ed()
    try:
        r = ed.export_selection_sets(
            path=body.path,
            names=body.names,
            resolve_live=body.resolve_live,
            filename=body.filename,
        )
    except Exception as e:
        raise HTTPException(400, f"export_selection_sets failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class ImportSelectionSetsBody(BaseModel):
    path: str
    mode: str = "merge"
    overwrite: bool = True
    names: list[str] | None = None
    resolve_live: bool = True


@app.post("/api/edit/import_selection_sets")
def import_selection_sets_api(body: ImportSelectionSetsBody) -> dict[str, Any]:
    """Import selection sets from JSON."""
    ed = _ed()
    try:
        r = ed.import_selection_sets(
            body.path,
            mode=body.mode,
            overwrite=body.overwrite,
            names=body.names,
            resolve_live=body.resolve_live,
        )
    except Exception as e:
        raise HTTPException(400, f"import_selection_sets failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class ExportWebmBody(BaseModel):
    output_path: str | None = None
    start_seconds: float = 0.0
    end_seconds: float | None = None
    crf: int = 32
    width: int | None = None


@app.post("/api/export/webm")
def export_webm_api(body: ExportWebmBody) -> dict[str, Any]:
    """Export timeline range as WebM (VP9+Opus)."""
    ed = _ed()
    out = body.output_path or str(_desktop_export_dir() / "out.webm")
    try:
        return ed.export_webm(
            out,
            start_seconds=body.start_seconds,
            end_seconds=body.end_seconds,
            crf=body.crf,
            width=body.width,
        )
    except Exception as e:
        raise HTTPException(500, f"export_webm failed: {e}") from e


class ExportClipGifBody(BaseModel):
    clip_id: str
    output_path: str | None = None
    fps: float = 12.0
    width: int = 480
    max_duration_seconds: float = 12.0


@app.post("/api/export/clip_gif")
def export_clip_gif_api(body: ExportClipGifBody) -> dict[str, Any]:
    """Export one clip span as GIF."""
    ed = _ed()
    out = body.output_path or str(_desktop_export_dir() / "clip.gif")
    try:
        return ed.export_clip_gif(
            body.clip_id,
            out,
            fps=body.fps,
            width=body.width,
            max_duration_seconds=body.max_duration_seconds,
        )
    except Exception as e:
        raise HTTPException(400, f"clip_gif failed: {e}") from e


@app.post("/api/edit/ken_burns_images")
def ken_burns_images_api(body: KenBurnsImagesBody) -> dict[str, Any]:
    """Apply Ken Burns to all image stills."""
    ed = _ed()
    try:
        r = ed.apply_ken_burns_to_images(
            track_id=body.track_id,
            zoom_end=body.zoom_end,
            replace=body.replace,
        )
    except Exception as e:
        raise HTTPException(400, f"ken_burns_images failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/preview/range")
def preview_range_api(body: PreviewRangeBody) -> dict[str, Any]:
    ed = _ed()
    out = body.output_path or str(_desktop_export_dir() / "preview_range.mp4")
    try:
        return ed.preview_range(
            out,
            body.start_seconds,
            body.end_seconds,
            ensure_proxy=body.ensure_proxy,
            height=body.height,
            fps=body.fps,
        )
    except Exception as e:
        raise HTTPException(400, f"preview_range failed: {e}") from e


@app.post("/api/clip/offset_linked")
def offset_linked_api(body: OffsetLinkedBody) -> dict[str, Any]:
    ed = _ed()
    try:
        r = ed.offset_linked(
            body.clip_id, body.delta_frames, kinds=body.kinds,
        )
    except Exception as e:
        raise HTTPException(400, f"offset_linked failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/clip/ripple_trim")
def ripple_trim_api(body: RippleTrimBody) -> dict[str, Any]:
    ed = _ed()
    try:
        r = ed.ripple_trim(
            body.clip_id,
            new_src_in=body.new_src_in,
            new_src_out=body.new_src_out,
        )
    except Exception as e:
        raise HTTPException(400, f"ripple_trim failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/analyze/asset")
def analyze_asset_api(body: AnalyzeAssetBody) -> dict[str, Any]:
    try:
        return _ed().analyze_asset(
            body.path,
            do_scenes=body.do_scenes,
            do_silence=body.do_silence,
            do_motion=body.do_motion,
            do_transcribe=body.do_transcribe,
        )
    except Exception as e:
        raise HTTPException(400, f"analyze_asset failed: {e}") from e


@app.post("/api/mix/apply_plan")
def apply_mix_plan_api(body: ApplyMixPlanBody) -> dict[str, Any]:
    ed = _ed()
    try:
        r = ed.apply_mix_plan(
            body.plan,
            role_clip_ids=body.role_clip_ids,
            music_track_id=body.music_track_id,
            vo_track_id=body.vo_track_id,
        )
    except Exception as e:
        raise HTTPException(400, f"apply_mix_plan failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/suggest/dialogue_chain")
def dialogue_chain_api(body: PathOnlyBody) -> dict[str, Any]:
    try:
        return _ed().suggest_dialogue_chain(body.path)
    except Exception as e:
        raise HTTPException(400, f"dialogue_chain failed: {e}") from e


# --- Deep craft (0.4.81+) ---


class TrimClipBody(BaseModel):
    clip_id: str
    src_in: int
    src_out: int


class SlugMediaBody(BaseModel):
    kind: str = "video"
    place: bool = False
    track_id: str | None = None
    start: int | None = None


class ClipTransitionBody(BaseModel):
    clip_id: str
    transition_type: str = "cross_dissolve"
    duration_frames: int = 12


class ClipIdOnlyBody(BaseModel):
    clip_id: str


class RippleDeleteRangeBody(BaseModel):
    start_frame: int
    end_frame: int
    track_id: str | None = None
    kind: str | None = None


class MarkerColorBatchBody(BaseModel):
    color: str
    marker_ids: list[str] | None = None


class MediaContactSheetBody(BaseModel):
    path: str
    output_path: str | None = None
    cols: int = 3
    rows: int = 3


class KeepRangesBody(BaseModel):
    clip_id: str
    keep_ranges: list[dict[str, Any]]
    time_unit: str = "seconds"


class RoomToneSuggestBody(BaseModel):
    path: str


class RoomToneExtractBody(BaseModel):
    path: str
    output_path: str | None = None


class RoomTonePlaceBody(BaseModel):
    source_path: str
    track_id: str | None = None
    start_frame: int = 0
    loop_to_seconds: float | None = None
    gain_db: float = -8.0


class SeparateStemsBody(BaseModel):
    path: str
    output_dir: str | None = None
    model: str = "htdemucs"
    two_stems: str | None = "vocals"
    device: str = "cpu"


class ExtractFrameFileBody(BaseModel):
    path: str
    time_seconds: float = 0.0
    output_path: str | None = None
    width: int = 640


class CacheTranscriptBody(BaseModel):
    media_id: str
    transcript: dict[str, Any]


class PrepareForExportBody(BaseModel):
    fill_video: bool = True
    fill_audio: bool = False
    clear_empty_tracks: bool = True


@app.get("/api/clip/{clip_id}/gain")
def get_clip_gain_api(clip_id: str) -> dict[str, Any]:
    return {"clip_id": clip_id, "db": _ed().get_clip_gain_db(clip_id)}


@app.get("/api/clip/{clip_id}/opacity")
def get_clip_opacity_api(clip_id: str) -> dict[str, Any]:
    return {"clip_id": clip_id, "amount": _ed().get_clip_opacity(clip_id)}


@app.post("/api/clip/trim")
def trim_clip_api(body: TrimClipBody) -> dict[str, Any]:
    ed = _ed()
    try:
        clip = ed.trim_clip(body.clip_id, body.src_in, body.src_out)
    except Exception as e:
        raise HTTPException(400, f"trim_clip failed: {e}") from e
    return {
        "clip": clip.to_dict() if hasattr(clip, "to_dict") else {"id": body.clip_id},
        "timeline": ed.timeline_view(),
    }


@app.post("/api/media/slug")
def ensure_slug_media_api(body: SlugMediaBody | None = None) -> dict[str, Any]:
    body = body or SlugMediaBody()
    kind = body.kind if body.kind in ("video", "audio", "image") else "video"
    ed = _ed()
    try:
        media = ed.ensure_slug_media(kind=kind)  # type: ignore[arg-type]
    except Exception as e:
        raise HTTPException(400, f"ensure_slug_media failed: {e}") from e
    out: dict[str, Any] = {
        "media": media.to_dict() if hasattr(media, "to_dict") else {"id": media.id},
    }
    if body.place:
        tracks = ed.project.tracks
        tid = body.track_id
        if not tid:
            match = next((t for t in tracks if t.kind == kind), None)
            if match is None:
                match = ed.add_track(kind)  # type: ignore[arg-type]
            tid = match.id
        start = body.start if body.start is not None else ed.duration_frames()
        placed = ed.place_media(media.id, tid, start)
        out["place"] = placed if isinstance(placed, dict) else {"result": placed}
        out["timeline"] = ed.timeline_view()
    return out


@app.post("/api/clip/transition")
def add_clip_transition_api(body: ClipTransitionBody) -> dict[str, Any]:
    ed = _ed()
    try:
        clip = ed.add_transition(
            body.clip_id, body.transition_type, body.duration_frames,
        )
    except Exception as e:
        raise HTTPException(400, f"add_transition failed: {e}") from e
    return {
        "clip": clip.to_dict() if hasattr(clip, "to_dict") else {"id": body.clip_id},
        "timeline": ed.timeline_view(),
    }


@app.post("/api/clip/transition/clear")
def remove_clip_transition_api(body: ClipIdOnlyBody) -> dict[str, Any]:
    ed = _ed()
    try:
        clip = ed.remove_transition(body.clip_id)
    except Exception as e:
        raise HTTPException(400, f"remove_transition failed: {e}") from e
    return {
        "clip": clip.to_dict() if hasattr(clip, "to_dict") else {"id": body.clip_id},
        "timeline": ed.timeline_view(),
    }


@app.post("/api/ripple_delete_range")
def ripple_delete_range_api(body: RippleDeleteRangeBody) -> dict[str, Any]:
    ed = _ed()
    try:
        r = ed.ripple_delete_range(
            body.start_frame,
            body.end_frame,
            track_id=body.track_id,
            kind=body.kind,
        )
    except Exception as e:
        raise HTTPException(400, f"ripple_delete_range failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/markers/color_batch")
def markers_color_batch_api(body: MarkerColorBatchBody) -> dict[str, Any]:
    ed = _ed()
    try:
        return ed.set_marker_color_batch(body.color, marker_ids=body.marker_ids)
    except Exception as e:
        raise HTTPException(400, f"marker color batch failed: {e}") from e


@app.post("/api/media/contact_sheet")
def media_contact_sheet_api(body: MediaContactSheetBody) -> dict[str, Any]:
    ed = _ed()
    out = body.output_path or str(_desktop_export_dir() / "media_contact.jpg")
    try:
        path = ed.make_contact_sheet(body.path, out, cols=body.cols, rows=body.rows)
    except Exception as e:
        raise HTTPException(400, f"contact_sheet failed: {e}") from e
    return {"path": str(path), "cols": body.cols, "rows": body.rows}


@app.post("/api/clip/keep_ranges")
def apply_keep_ranges_api(body: KeepRangesBody) -> dict[str, Any]:
    ed = _ed()
    try:
        r = ed.apply_keep_ranges(
            body.clip_id, body.keep_ranges, time_unit=body.time_unit,
        )
    except Exception as e:
        raise HTTPException(400, f"apply_keep_ranges failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/asset/analysis")
def load_asset_analysis_api(body: PathOnlyBody) -> dict[str, Any]:
    r = _ed().load_asset_analysis(body.path)
    return {"path": body.path, "analysis": r, "cached": r is not None}


@app.post("/api/room_tone/suggest")
def room_tone_suggest_api(body: RoomToneSuggestBody) -> dict[str, Any]:
    try:
        return _ed().suggest_room_tone(body.path)
    except Exception as e:
        raise HTTPException(400, f"suggest_room_tone failed: {e}") from e


@app.post("/api/room_tone/extract")
def room_tone_extract_api(body: RoomToneExtractBody) -> dict[str, Any]:
    out = body.output_path or str(_desktop_export_dir() / "room_tone.wav")
    try:
        return _ed().extract_room_tone(body.path, out)
    except Exception as e:
        raise HTTPException(400, f"extract_room_tone failed: {e}") from e


@app.post("/api/room_tone/place")
def room_tone_place_api(body: RoomTonePlaceBody) -> dict[str, Any]:
    ed = _ed()
    try:
        r = ed.place_room_tone(
            body.source_path,
            track_id=body.track_id,
            start_frame=body.start_frame,
            loop_to_seconds=body.loop_to_seconds,
            gain_db=body.gain_db,
        )
    except Exception as e:
        raise HTTPException(400, f"place_room_tone failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


@app.post("/api/stems/separate")
def separate_stems_api(body: SeparateStemsBody) -> dict[str, Any]:
    out_dir = body.output_dir or str(_desktop_export_dir() / "stems")
    try:
        return _ed().separate_stems(
            body.path, out_dir, model=body.model,
            two_stems=body.two_stems, device=body.device,
        )
    except Exception as e:
        raise HTTPException(400, f"separate_stems failed: {e}") from e


@app.post("/api/media/extract_frame")
def extract_frame_file_api(body: ExtractFrameFileBody) -> dict[str, Any]:
    out = body.output_path or str(
        _desktop_export_dir() / f"frame_{body.time_seconds:.2f}s.jpg"
    )
    try:
        return _ed().extract_frame(
            body.path, body.time_seconds, out, width=body.width,
        )
    except Exception as e:
        raise HTTPException(400, f"extract_frame failed: {e}") from e


@app.post("/api/media/cache_transcript")
def cache_transcript_api(body: CacheTranscriptBody) -> dict[str, Any]:
    try:
        return _ed().cache_transcript(body.media_id, body.transcript)
    except Exception as e:
        raise HTTPException(400, f"cache_transcript failed: {e}") from e


@app.post("/api/prepare_for_export")
def prepare_for_export_api(body: PrepareForExportBody | None = None) -> dict[str, Any]:
    body = body or PrepareForExportBody()
    ed = _ed()
    try:
        r = ed.prepare_for_export(
            fill_video=body.fill_video,
            fill_audio=body.fill_audio,
            clear_empty_tracks=body.clear_empty_tracks,
        )
    except Exception as e:
        raise HTTPException(400, f"prepare_for_export failed: {e}") from e
    return {**r, "timeline": ed.timeline_view()}


class FillerSuggestBody(BaseModel):
    path: str | None = None
    clip_id: str | None = None
    media_id: str | None = None
    pad_seconds: float = 0.02
    model_size: str = "base"
    language: str | None = None
    use_cache: bool = True


@app.post("/api/suggest/filler")
def suggest_filler_api(body: FillerSuggestBody | None = None) -> dict[str, Any]:
    """Word-level filler plan (um/uh/…) — does not edit timeline."""
    body = body or FillerSuggestBody()
    try:
        return _ed().suggest_filler_cuts(
            path=body.path,
            clip_id=body.clip_id,
            media_id=body.media_id,
            pad_seconds=body.pad_seconds,
            model_size=body.model_size,
            language=body.language,
            use_cache=body.use_cache,
        )
    except Exception as e:
        raise HTTPException(400, f"suggest_filler failed: {e}") from e


@app.get("/api/project/colors")
def project_colors_alias() -> dict[str, Any]:
    """Alias of clip color palette for agents."""
    return _ed().list_clip_colors()


@app.get("/api/project/recent")
def project_recent_alias(limit: int = 12) -> dict[str, Any]:
    """Alias of list_recent_projects."""
    return _ed().list_recent_projects(limit=limit)


@app.get("/api/session/summary")
def session_summary_api() -> dict[str, Any]:
    """Compact session snapshot for desktop status / agents."""
    ed = _ed()
    try:
        pre = ed.agent_preflight()
    except Exception as e:
        pre = {"ok": False, "error": str(e)}
    try:
        enc = ed.encode_status()
    except Exception:
        enc = {}
    try:
        from opmiere.render.openshot_map import path_c_effect_catalog

        path_c = path_c_effect_catalog()
    except Exception:
        path_c = {}
    return {
        "version": __version__,
        "preflight": pre,
        "encode": enc,
        "duration_frames": ed.duration_frames(),
        "track_count": len(ed.project.tracks),
        "media_count": len(ed.project.media),
        "marker_count": len(getattr(ed.project, "markers", None) or []),
        "path_c": path_c,
    }


if _STATIC.is_dir():
    app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")


def main() -> None:
    import uvicorn
    host = os.environ.get("OPMIERE_WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("OPMIERE_WEB_PORT", "8787"))
    uvicorn.run("opmiere.web.app:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
