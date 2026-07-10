"""P3 web GUI — thin HTTP shell over Editor (ARCHITECTURE §5.4).

Not a full NLE scrubber (libopenshot/MLT still open). Ships reachability:
create/place/export + doctor, review_cut, sequence sheet, delivery-aware export.

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

app = FastAPI(title="Opmiere", version="0.0.1-p3")
_editor: Editor | None = None
_STATIC = Path(__file__).resolve().parent / "static"
# last sequence sheet / export artifacts for UI
_last_sheet: str | None = None


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


class SheetBody(BaseModel):
    output_path: str | None = None
    max_tiles: int = 12
    cols: int | None = None


class PlanEditBody(BaseModel):
    paths: list[str] = Field(default_factory=list)
    b_roll_mode: str = "overlay"
    j_cut_seconds: float = 0.4
    apply: bool = True


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
        "phase": "p3",
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


if _STATIC.is_dir():
    app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")


def main() -> None:
    import uvicorn
    host = os.environ.get("OPMIERE_WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("OPMIERE_WEB_PORT", "8787"))
    uvicorn.run("opmiere.web.app:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
