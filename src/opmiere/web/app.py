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
def join_clips_api(body: JoinClipsBody) -> dict[str, Any]:
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


@app.post("/api/markers/clear")
def clear_markers_api() -> dict[str, Any]:
    ed = _ed()
    r = ed.clear_markers()
    return {**r, "markers": []}


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
def preview_openshot_plan(height: int = 360) -> dict[str, Any]:
    return _ed().openshot_plan(height=height)


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


@app.post("/api/export/fcpxml")
def export_fcpxml_api(body: InterchangeExportBody | None = None) -> dict[str, Any]:
    body = body or InterchangeExportBody()
    ed = _ed()
    path = body.path or str(_desktop_export_dir() / "export.fcpxml")
    try:
        return ed.export_fcpxml(path, title=body.title)
    except Exception as e:
        raise HTTPException(500, f"export_fcpxml failed: {e}") from e


@app.post("/api/export/otio")
def export_otio_api(body: InterchangeExportBody | None = None) -> dict[str, Any]:
    body = body or InterchangeExportBody()
    ed = _ed()
    path = body.path or str(_desktop_export_dir() / "export.otio.json")
    try:
        return ed.export_otio_json(path, title=body.title)
    except Exception as e:
        raise HTTPException(500, f"export_otio failed: {e}") from e


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


if _STATIC.is_dir():
    app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")


def main() -> None:
    import uvicorn
    host = os.environ.get("OPMIERE_WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("OPMIERE_WEB_PORT", "8787"))
    uvicorn.run("opmiere.web.app:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
