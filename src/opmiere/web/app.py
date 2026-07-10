"""Web GUI shell over Editor — dual surface with MCP (ARCHITECTURE §5.4).

Product is the NLE; this is a thin HTTP viewport: proportional timeline,
HTML5 proxy scrub, media bin, style/filler helpers. Not libopenshot realtime.

Run:  python -m opmiere.web.app  |  opmiere web  |  opmiere-web
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..generation import ComfyUIProvider
from ..ops import Editor

app = FastAPI(title="Opmiere", version="0.2.1")
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
        "phase": "0.2.1",
        "product": "video_editor",
        "project_open": _editor is not None,
    }


@app.get("/api/doctor")
def doctor(check_comfy: bool = False) -> dict[str, Any]:
    from ..doctor import run_doctor
    return run_doctor(check_comfy=check_comfy)


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
    return _ed().ripple_delete(body.clip_id)


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


@app.post("/api/markers/delete")
def markers_delete(body: MarkerDeleteBody) -> dict[str, Any]:
    ed = _ed()
    r = ed.delete_marker(body.marker_id)
    return {**r, "markers": ed.list_markers()["markers"]}


@app.post("/api/split")
def split_at(body: SplitBody) -> dict[str, Any]:
    ed = _ed()
    a, b = ed.split_clip(body.clip_id, body.at_frame)
    return {
        "first": a.to_dict(),
        "second": b.to_dict(),
        "timeline": ed.timeline_view(),
    }


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


@app.post("/api/preview/frame")
def preview_frame(body: FrameBody) -> dict[str, Any]:
    global _last_frame
    ed = _ed()
    out = ed.bundle.root / "review" / f"frame_{body.time_seconds:.2f}.jpg"
    result = ed.frame_at(
        body.time_seconds,
        out,
        width=body.width,
        prefer_proxy=body.prefer_proxy,
    )
    _last_frame = result.get("path")
    return result


@app.get("/api/preview/frame.jpg")
def preview_frame_jpg(t: float = 0.0, width: int = 640) -> FileResponse:
    """GET convenience for <img src> scrubbing."""
    global _last_frame
    ed = _ed()
    out = ed.bundle.root / "review" / "scrub_frame.jpg"
    result = ed.frame_at(t, out, width=width, prefer_proxy=True)
    _last_frame = result.get("path")
    if not _last_frame or not Path(_last_frame).exists():
        raise HTTPException(500, "frame extract failed")
    return FileResponse(_last_frame, media_type="image/jpeg")


@app.post("/api/preview/keyframes")
def preview_keyframes(count: int = 5, width: int = 480) -> dict[str, Any]:
    ed = _ed()
    out = ed.bundle.root / "review" / "keyframes"
    return ed.review_keyframes(out, count=count, width=width, ensure_proxy=True)


if _STATIC.is_dir():
    app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")


def main() -> None:
    import uvicorn
    host = os.environ.get("OPMIERE_WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("OPMIERE_WEB_PORT", "8787"))
    uvicorn.run("opmiere.web.app:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
