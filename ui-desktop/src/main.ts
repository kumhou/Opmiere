/**
 * Opmiere desktop shell (Tauri) — product UI.
 *
 * Python Editor is source of truth. Program monitor:
 *  - scrub / frame step via OpenShot or proxy/base stills
 *  - play: HTML5 proxy.mp4 when engine=proxy (or auto+fresh proxy);
 *          otherwise stepped stills (~8fps) for openshot/base
 * No agent chat (ADR).
 */

const API_BASE =
  (import.meta as unknown as { env?: { VITE_OPMIERE_API?: string } }).env
    ?.VITE_OPMIERE_API || "http://127.0.0.1:8787";

type Health = {
  status?: string;
  project_open?: boolean;
  phase?: string;
};

type Doctor = { ok?: boolean };

type PreviewEngine = {
  active_backend?: string;
  state?: string;
  openshot_app_present?: boolean;
  agent_note?: string;
};

type ProxyStatus = {
  fresh?: boolean;
  exists?: boolean;
  path?: string;
};

type TimelineView = {
  duration_frames?: number;
  duration_seconds?: number;
  fps?: number;
  proxy?: ProxyStatus;
  tracks?: Array<{
    id: string;
    kind: string;
    name?: string;
    clips?: Array<{
      id: string;
      start?: number;
      start_frame?: number;
      duration_frames?: number;
      name?: string;
      label?: string;
    }>;
  }>;
};

const state = {
  projectOpen: false,
  durationSec: 0,
  fps: 30,
  t: 0,
  engine: "auto" as string,
  seekToken: 0,
  seeking: false,
  playing: false,
  playMode: "stopped" as "stopped" | "proxy" | "step",
  proxyFresh: false,
  playTimer: 0 as number | ReturnType<typeof setTimeout>,
  lastFrameAt: 0,
  shuttle: 0, // -1 J, 0, +1 L
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
  if (!res.ok) throw new Error(`${path} → HTTP ${res.status}`);
  return (await res.json()) as T;
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${path} → HTTP ${res.status}: ${text.slice(0, 200)}`);
  }
  return (await res.json()) as T;
}

function framesToTc(frames: number, fps: number): string {
  const rate = Math.max(1, Math.round(fps || 30));
  const f = Math.max(0, Math.floor(frames));
  const ff = f % rate;
  const totalSec = Math.floor(f / rate);
  const ss = totalSec % 60;
  const mm = Math.floor(totalSec / 60) % 60;
  const hh = Math.floor(totalSec / 3600);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(hh)}:${p(mm)}:${p(ss)}:${p(ff)}`;
}

function setPlayheadUi() {
  const scrub = $("scrub") as HTMLInputElement;
  const max = Math.max(1, Math.round(state.durationSec * 1000));
  scrub.max = String(max);
  scrub.value = String(Math.round(state.t * 1000));
  scrub.disabled = !state.projectOpen || state.durationSec <= 0;
  const frames = Math.round(state.t * state.fps);
  $("tc").textContent = framesToTc(frames, state.fps);
  document.querySelectorAll<HTMLElement>(".timeline-playhead").forEach((el) => {
    const pct =
      state.durationSec > 0
        ? Math.min(100, Math.max(0, (state.t / state.durationSec) * 100))
        : 0;
    el.style.left = `${pct}%`;
  });
  $("play-mode").textContent = state.playing
    ? state.playMode
    : "stopped";
  const btn = $("btn-play");
  btn.textContent = state.playing ? "❚❚" : "▶";
}

function hideAllProgramSurfaces() {
  ($("program-img") as HTMLImageElement).hidden = true;
  ($("program-video") as HTMLVideoElement).hidden = true;
  $("program-empty").hidden = false;
}

function showProgramImage(url: string | null) {
  const img = $("program-img") as HTMLImageElement;
  const vid = $("program-video") as HTMLVideoElement;
  const empty = $("program-empty");
  if (!url) {
    img.hidden = true;
    if (!state.playing || state.playMode !== "proxy") {
      empty.hidden = false;
    }
    return;
  }
  empty.hidden = true;
  vid.hidden = true;
  vid.pause();
  img.hidden = false;
  img.src = url;
}

function showProgramVideo(src: string, t: number) {
  const img = $("program-img") as HTMLImageElement;
  const vid = $("program-video") as HTMLVideoElement;
  const empty = $("program-empty");
  empty.hidden = true;
  img.hidden = true;
  vid.hidden = false;
  if (!vid.src.includes("proxy.mp4") || vid.dataset.base !== src) {
    vid.src = src;
    vid.dataset.base = src;
  }
  const apply = () => {
    try {
      if (Math.abs(vid.currentTime - t) > 0.04) {
        vid.currentTime = Math.min(t, Math.max(0, vid.duration || t));
      }
    } catch {
      /* seek before metadata */
    }
  };
  if (vid.readyState >= 1) apply();
  else vid.addEventListener("loadedmetadata", apply, { once: true });
}

async function seekTo(t: number, opts?: { fromPlay?: boolean }) {
  if (!state.projectOpen) return;
  state.t = Math.max(0, Math.min(state.durationSec || t, t));
  setPlayheadUi();
  const token = ++state.seekToken;
  state.seeking = true;
  if (!opts?.fromPlay) {
    $("transport-note").textContent = "seeking…";
  }
  const eng = (document.getElementById("engine-select") as HTMLSelectElement)
    .value;
  state.engine = eng;

  // While proxy-playing, keep video in sync without still fetch
  if (state.playing && state.playMode === "proxy") {
    const vid = $("program-video") as HTMLVideoElement;
    try {
      vid.currentTime = state.t;
    } catch {
      /* ignore */
    }
    state.seeking = false;
    return;
  }

  try {
    const q = new URLSearchParams({
      t: String(state.t),
      width: "640",
      engine: eng,
      _: String(Date.now()),
    });
    const url = `${API_BASE}/api/preview/frame.jpg?${q.toString()}`;
    const res = await fetch(url);
    if (!res.ok) throw new Error(`frame HTTP ${res.status}`);
    const blob = await res.blob();
    if (token !== state.seekToken) return;
    const objectUrl = URL.createObjectURL(blob);
    const img = $("program-img") as HTMLImageElement;
    const prev = img.dataset.objectUrl;
    if (prev) URL.revokeObjectURL(prev);
    img.dataset.objectUrl = objectUrl;
    showProgramImage(objectUrl);
    $("frame-mode").textContent = (res.headers.get("content-type") || "").includes(
      "png",
    )
      ? `${eng}/png`
      : `${eng}/jpg`;
    if (!opts?.fromPlay) {
      $("transport-note").textContent = "seek → frame";
    }
  } catch (e) {
    if (token === state.seekToken) {
      $("transport-note").textContent = String(e).slice(0, 80);
      $("status-msg").textContent = `Frame failed: ${e}`;
    }
  } finally {
    if (token === state.seekToken) state.seeking = false;
  }
}

function stopPlay() {
  state.playing = false;
  state.playMode = "stopped";
  state.shuttle = 0;
  if (state.playTimer) {
    clearTimeout(state.playTimer as number);
    state.playTimer = 0;
  }
  const vid = $("program-video") as HTMLVideoElement;
  vid.pause();
  setPlayheadUi();
  $("transport-note").textContent = "stopped";
}

async function ensureProxyFresh(): Promise<boolean> {
  try {
    const st = await getJson<ProxyStatus>("/api/preview/status");
    if (st.fresh) {
      state.proxyFresh = true;
      return true;
    }
    await postJson("/api/preview/ensure", { height: 360, fps: 12 });
    const st2 = await getJson<ProxyStatus>("/api/preview/status");
    state.proxyFresh = !!st2.fresh;
    return state.proxyFresh;
  } catch {
    state.proxyFresh = false;
    return false;
  }
}

function useProxyVideoForPlay(): boolean {
  const eng = (document.getElementById("engine-select") as HTMLSelectElement)
    .value;
  if (eng === "proxy") return true;
  if (eng === "openshot" || eng === "base") return false;
  // auto: prefer smooth proxy when available
  return state.proxyFresh;
}

async function startPlay() {
  if (!state.projectOpen || state.durationSec <= 0) return;
  if (state.playing) {
    stopPlay();
    // leave still at current t
    void seekTo(state.t);
    return;
  }

  const wantProxy = useProxyVideoForPlay();
  if (wantProxy) {
    const ok = await ensureProxyFresh();
    if (ok) {
      state.playing = true;
      state.playMode = "proxy";
      setPlayheadUi();
      $("transport-note").textContent = "playing (proxy)";
      const src = `${API_BASE}/api/preview/proxy.mp4?_=${Date.now()}`;
      showProgramVideo(src, state.t);
      const vid = $("program-video") as HTMLVideoElement;
      const onTime = () => {
        if (!state.playing || state.playMode !== "proxy") return;
        state.t = vid.currentTime;
        if (state.t >= state.durationSec - 0.02) {
          stopPlay();
          void seekTo(state.durationSec);
          return;
        }
        setPlayheadUi();
      };
      vid.ontimeupdate = onTime;
      vid.onended = () => {
        stopPlay();
        void seekTo(state.durationSec);
      };
      try {
        vid.currentTime = state.t;
        await vid.play();
      } catch (e) {
        stopPlay();
        $("status-msg").textContent = `Proxy play failed: ${e}`;
        void startStepPlay();
      }
      return;
    }
  }
  await startStepPlay();
}

async function startStepPlay() {
  state.playing = true;
  state.playMode = "step";
  setPlayheadUi();
  $("transport-note").textContent = "playing (step ~8fps)";
  const stepSec = 1 / 8;
  const tick = async () => {
    if (!state.playing || state.playMode !== "step") return;
    const dir = state.shuttle === 0 ? 1 : state.shuttle;
    const next = state.t + stepSec * dir;
    if (next >= state.durationSec || next < 0) {
      stopPlay();
      await seekTo(Math.max(0, Math.min(state.durationSec, next)));
      return;
    }
    await seekTo(next, { fromPlay: true });
    if (state.playing && state.playMode === "step") {
      state.playTimer = setTimeout(() => {
        void tick();
      }, 1000 / 8);
    }
  };
  void tick();
}

function renderTimeline(view: TimelineView | null) {
  const body = $("timeline-body");
  const meta = $("timeline-meta");
  if (!view || !view.tracks?.length) {
    body.textContent =
      "No timeline yet. Use Demo project or open via core API.";
    meta.textContent = "empty";
    return;
  }
  const durF = Math.max(1, view.duration_frames || 1);
  state.durationSec = view.duration_seconds || durF / (view.fps || state.fps);
  state.fps = view.fps || state.fps || 30;
  if (view.proxy) state.proxyFresh = !!view.proxy.fresh;
  meta.textContent = `${view.tracks.length} tracks · ${state.durationSec.toFixed(2)}s`;
  body.innerHTML = "";
  for (const tr of view.tracks) {
    const row = document.createElement("div");
    row.className = "track-row";
    const label = document.createElement("div");
    label.className = "track-label";
    label.textContent = tr.name || tr.kind || tr.id;
    const lane = document.createElement("div");
    lane.className = "track-lane";
    const ph = document.createElement("div");
    ph.className = "timeline-playhead";
    lane.appendChild(ph);
    for (const c of tr.clips || []) {
      const start = c.start_frame ?? c.start ?? 0;
      const dur = c.duration_frames ?? 1;
      const left = (start / durF) * 100;
      const width = Math.max(0.5, (dur / durF) * 100);
      const block = document.createElement("div");
      block.className = `clip-block${tr.kind === "audio" ? " audio" : ""}`;
      block.style.left = `${left}%`;
      block.style.width = `${width}%`;
      block.textContent = c.label || c.name || c.id;
      block.title = c.id;
      lane.appendChild(block);
    }
    lane.addEventListener("click", (ev) => {
      stopPlay();
      const rect = lane.getBoundingClientRect();
      const x = (ev.clientX - rect.left) / Math.max(1, rect.width);
      void seekTo(x * state.durationSec);
    });
    row.appendChild(label);
    row.appendChild(lane);
    body.appendChild(row);
  }
  setPlayheadUi();
}

async function createDemoProject() {
  stopPlay();
  $("status-msg").textContent = "Creating demo project…";
  try {
    const r = await postJson<{ ok?: boolean; path?: string; error?: string }>(
      "/api/desktop/demo_project",
      {},
    );
    if (!r.ok) throw new Error(r.error || "demo failed");
    $("status-msg").textContent = `Demo open: ${r.path || "ok"}`;
    await refresh();
    await seekTo(0.1);
  } catch (e) {
    $("status-msg").textContent = `Demo failed: ${e}`;
  }
}

async function refresh() {
  stopPlay();
  $("api-url").textContent = API_BASE;
  $("status-msg").textContent = "Refreshing…";
  try {
    const health = await getJson<Health>("/api/health");
    setPill("pill-api", "ok", "API up");
    state.projectOpen = !!health.project_open;
    $("project-state").textContent = state.projectOpen ? "open" : "none";
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
    if (state.projectOpen) {
      try {
        preview = await getJson<PreviewEngine>("/api/preview/interactive");
      } catch {
        preview = null;
      }
      try {
        const st = await getJson<ProxyStatus>("/api/preview/status");
        state.proxyFresh = !!st.fresh;
      } catch {
        state.proxyFresh = false;
      }
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
      $("engine-active").textContent = state.projectOpen
        ? "unknown"
        : "open a project";
      $("openshot-app").textContent = "—";
      $("preview-backend").textContent = "preview: idle";
      setPill("pill-preview", "warn", "preview idle");
    }

    if (state.projectOpen) {
      try {
        const tl = await getJson<TimelineView>("/api/project/timeline");
        renderTimeline(tl);
        if (state.durationSec > 0) {
          await seekTo(Math.min(state.t, state.durationSec));
        }
      } catch (e) {
        renderTimeline(null);
        $("timeline-body").textContent = String(e);
      }
    } else {
      state.durationSec = 0;
      renderTimeline(null);
      hideAllProgramSurfaces();
      setPlayheadUi();
    }

    $("status-msg").textContent = "Ready";
  } catch (e) {
    setPill("pill-api", "err", "API down");
    setPill("pill-preview", "err", "preview n/a");
    $("status-msg").textContent =
      `Core API unreachable at ${API_BASE}. Run scripts/dev-desktop.ps1 or opmiere web`;
    $("project-state").textContent = "—";
    state.projectOpen = false;
    console.error(e);
  }
}

function onKey(ev: KeyboardEvent) {
  if (
    ev.target instanceof HTMLInputElement ||
    ev.target instanceof HTMLSelectElement ||
    ev.target instanceof HTMLTextAreaElement
  ) {
    return;
  }
  const k = ev.key.toLowerCase();
  if (k === " " || k === "k") {
    ev.preventDefault();
    void startPlay();
    return;
  }
  if (k === "j") {
    ev.preventDefault();
    stopPlay();
    void seekTo(state.t - 5 / state.fps);
    return;
  }
  if (k === "l") {
    ev.preventDefault();
    stopPlay();
    void seekTo(state.t + 5 / state.fps);
    return;
  }
  if (ev.key === "ArrowLeft") {
    ev.preventDefault();
    stopPlay();
    void seekTo(state.t - 1 / state.fps);
    return;
  }
  if (ev.key === "ArrowRight") {
    ev.preventDefault();
    stopPlay();
    void seekTo(state.t + 1 / state.fps);
  }
}

window.addEventListener("DOMContentLoaded", () => {
  $("btn-refresh").addEventListener("click", () => {
    void refresh();
  });
  $("btn-open-probe").addEventListener("click", () => {
    window.open(API_BASE + "/", "_blank");
  });
  $("btn-demo").addEventListener("click", () => {
    void createDemoProject();
  });
  $("btn-frame-back").addEventListener("click", () => {
    stopPlay();
    void seekTo(state.t - 1 / state.fps);
  });
  $("btn-frame-fwd").addEventListener("click", () => {
    stopPlay();
    void seekTo(state.t + 1 / state.fps);
  });
  $("btn-play").addEventListener("click", () => {
    void startPlay();
  });
  const scrub = $("scrub") as HTMLInputElement;
  scrub.addEventListener("input", () => {
    stopPlay();
    const t = Number(scrub.value) / 1000;
    state.t = t;
    setPlayheadUi();
  });
  scrub.addEventListener("change", () => {
    stopPlay();
    void seekTo(Number(scrub.value) / 1000);
  });
  ($("engine-select") as HTMLSelectElement).addEventListener("change", () => {
    stopPlay();
    void seekTo(state.t);
  });
  window.addEventListener("keydown", onKey);
  void refresh();
});
