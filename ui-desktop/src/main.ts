/**
 * Opmiere desktop shell (Tauri) — product UI scaffold.
 *
 * Talks to the Python Editor HTTP API (opmiere-web). Design tokens from
 * design-system/opmiere. No agent chat panel (ADR).
 */

const API_BASE =
  (import.meta as unknown as { env?: { VITE_OPMIERE_API?: string } }).env
    ?.VITE_OPMIERE_API || "http://127.0.0.1:8787";

type Health = {
  status?: string;
  project_open?: boolean;
  phase?: string;
};

type Doctor = {
  ok?: boolean;
  version?: string;
  checks?: Array<{ id: string; ok?: boolean; detail?: string; active?: string }>;
};

type PreviewEngine = {
  active_backend?: string;
  state?: string;
  openshot_app_present?: boolean;
  agent_note?: string;
};

type TimelineView = {
  duration_frames?: number;
  duration_seconds?: number;
  tracks?: Array<{
    id: string;
    kind: string;
    name?: string;
    clips?: Array<{ id: string; start?: number; duration_frames?: number; name?: string }>;
  }>;
};

function $(id: string): HTMLElement {
  const el = document.getElementById(id);
  if (!el) throw new Error(`#${id} missing`);
  return el;
}

function setPill(id: string, cls: "ok" | "warn" | "err", text: string) {
  const el = $(id);
  el.className = `pill ${cls}`;
  el.textContent = text;
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { Accept: "application/json" },
  });
  if (!res.ok) {
    throw new Error(`${path} → HTTP ${res.status}`);
  }
  return (await res.json()) as T;
}

function framesToTc(frames: number, fps: number): string {
  const f = Math.max(0, Math.floor(frames));
  const ff = f % Math.round(fps || 30);
  const totalSec = Math.floor(f / (fps || 30));
  const ss = totalSec % 60;
  const mm = Math.floor(totalSec / 60) % 60;
  const hh = Math.floor(totalSec / 3600);
  const p = (n: number, w = 2) => String(n).padStart(w, "0");
  return `${p(hh)}:${p(mm)}:${p(ss)}:${p(ff)}`;
}

function renderTimeline(view: TimelineView | null) {
  const body = $("timeline-body");
  const meta = $("timeline-meta");
  if (!view || !view.tracks?.length) {
    body.textContent =
      "No timeline yet. Create/open a project on the core API, then Refresh.";
    meta.textContent = "empty";
    return;
  }
  const durF = view.duration_frames || 1;
  meta.textContent = `${view.tracks.length} tracks · ${view.duration_seconds?.toFixed?.(2) ?? "?"}s`;
  body.innerHTML = "";
  for (const tr of view.tracks) {
    const row = document.createElement("div");
    row.className = "track-row";
    const label = document.createElement("div");
    label.className = "track-label";
    label.textContent = tr.name || tr.kind || tr.id;
    const lane = document.createElement("div");
    lane.className = "track-lane";
    for (const c of tr.clips || []) {
      const start = c.start ?? 0;
      const dur = c.duration_frames ?? 1;
      const left = (start / durF) * 100;
      const width = Math.max(0.5, (dur / durF) * 100);
      const block = document.createElement("div");
      block.className = `clip-block${tr.kind === "audio" ? " audio" : ""}`;
      block.style.left = `${left}%`;
      block.style.width = `${width}%`;
      block.textContent = c.name || c.id;
      block.title = c.id;
      lane.appendChild(block);
    }
    row.appendChild(label);
    row.appendChild(lane);
    body.appendChild(row);
  }
  $("tc").textContent = framesToTc(0, 30);
}

async function refresh() {
  $("api-url").textContent = API_BASE;
  $("status-msg").textContent = "Refreshing…";
  try {
    const health = await getJson<Health>("/api/health");
    setPill("pill-api", "ok", "API up");
    $("project-state").textContent = health.project_open ? "open" : "none";
    $("core-version").textContent = `core ${health.phase || "?"} · product shell`;

    try {
      const doctor = await getJson<Doctor>("/api/doctor?check_comfy=false");
      $("doctor-ok").textContent = doctor.ok ? "ok" : "issues";
      $("doctor-ok").style.color = doctor.ok
        ? "var(--color-success)"
        : "var(--color-warning)";
    } catch {
      $("doctor-ok").textContent = "n/a";
    }

    let preview: PreviewEngine | null = null;
    try {
      preview = await getJson<PreviewEngine>("/api/preview/interactive");
    } catch {
      // endpoint only when project open — fall back
      preview = null;
    }
    if (preview) {
      const active = preview.active_backend || "none";
      $("engine-active").textContent = `${active} (${preview.state || "?"})`;
      $("openshot-app").textContent = preview.openshot_app_present
        ? "installed"
        : "missing";
      $("preview-backend").textContent = `preview: ${active}`;
      setPill(
        "pill-preview",
        active === "libopenshot" ? "ok" : "warn",
        `preview ${active}`,
      );
      if (preview.agent_note) {
        $("agent-note").textContent = preview.agent_note;
      }
    } else {
      $("engine-active").textContent = health.project_open
        ? "unknown"
        : "open a project";
      $("openshot-app").textContent = "—";
      $("preview-backend").textContent = "preview: idle";
      setPill("pill-preview", "warn", "preview idle");
    }

    if (health.project_open) {
      try {
        const tl = await getJson<TimelineView>("/api/project/timeline");
        renderTimeline(tl);
      } catch (e) {
        renderTimeline(null);
        $("timeline-body").textContent = String(e);
      }
    } else {
      renderTimeline(null);
    }

    $("status-msg").textContent = "Ready";
  } catch (e) {
    setPill("pill-api", "err", "API down");
    setPill("pill-preview", "err", "preview n/a");
    $("status-msg").textContent =
      `Core API unreachable at ${API_BASE}. Run: opmiere web  (or scripts/dev-desktop.ps1)`;
    $("project-state").textContent = "—";
    console.error(e);
  }
}

window.addEventListener("DOMContentLoaded", () => {
  $("btn-refresh").addEventListener("click", () => {
    void refresh();
  });
  $("btn-open-probe").addEventListener("click", () => {
    window.open(API_BASE + "/", "_blank");
  });
  void refresh();
});
