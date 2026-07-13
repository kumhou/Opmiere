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

type Marker = {
  id: string;
  frame?: number;
  label?: string;
  color?: string;
  time_seconds?: number;
};

type WorkInOut = {
  in_frame?: number | null;
  out_frame?: number | null;
  ready?: boolean;
  duration_frames?: number | null;
};

type TimelineView = {
  duration_frames?: number;
  duration_seconds?: number;
  fps?: number;
  proxy?: ProxyStatus;
  snap_frames?: number[];
  markers?: Marker[];
  work_in_out?: WorkInOut;
  dirty?: boolean;
  autosave?: boolean;
  can_undo?: boolean;
  can_redo?: boolean;
  notes?: string;
  bundle_path?: string;
  tracks?: Array<{
    id: string;
    kind: string;
    name?: string;
    muted?: boolean;
    solo?: boolean;
    locked?: boolean;
    clips?: Array<{
      id: string;
      start?: number;
      start_frame?: number;
      end_frame?: number;
      duration_frames?: number;
      name?: string;
      label?: string;
      muted?: boolean;
      link_group?: string | null;
      color?: string | null;
      speed?: number;
      gain_db?: number;
      opacity?: number;
      fade_in_frames?: number;
      fade_out_frames?: number;
      transition_in?: unknown;
    }>;
  }>;
};

type ClipInfo = {
  id: string;
  trackId: string;
  start: number;
  dur: number;
  label?: string;
  name?: string;
  color?: string | null;
  speed?: number;
  gain_db?: number;
  opacity?: number;
  muted?: boolean;
  link_group?: string | null;
  fade_in_frames?: number;
  fade_out_frames?: number;
};

const state = {
  projectOpen: false,
  durationSec: 0,
  durationFrames: 0,
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
  drag: null as null | {
    mode: "move" | "trim-left" | "trim-right";
    clipId: string;
    trackId: string;
    startFrame: number;
    durationFrames: number;
    originX: number;
    originY: number;
    laneWidth: number;
    block: HTMLElement;
    pendingStart: number;
    pendingDelta: number;
    pendingTrackId: string;
  },
  trackOrder: [] as string[], // video+audio lane track ids top→bottom
  tracks: [] as Array<{ id: string; kind: string }>,
  selected: new Set<string>(),
  markers: [] as Marker[],
  snapFrames: [] as number[],
  snapThr: 4,
  dirty: false,
  workIO: { in_frame: null, out_frame: null, ready: false } as WorkInOut,
  palette: [] as string[],
  clips: new Map<string, ClipInfo>(),
  notes: "",
  bundlePath: "",
  autosave: false,
  canUndo: false,
  canRedo: false,
  undoDepth: 0,
  redoDepth: 0,
  zoom: 1,
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

function applyTimelineView(view: TimelineView) {
  renderTimeline(view);
  setPlayheadUi();
}

function selectionList(): string[] {
  return Array.from(state.selected);
}

function setSelection(ids: string[], opts?: { additive?: boolean }) {
  if (!opts?.additive) state.selected.clear();
  for (const id of ids) {
    if (state.selected.has(id) && opts?.additive) state.selected.delete(id);
    else state.selected.add(id);
  }
  document.querySelectorAll<HTMLElement>(".clip-block").forEach((el) => {
    const id = el.dataset.clipId;
    el.classList.toggle("selected", !!id && state.selected.has(id));
  });
  const n = state.selected.size;
  $("sel-count").textContent = n ? String(n) : "0";
  updateSelectionCard();
}

function updateSelectionCard() {
  const el = document.getElementById("sel-card");
  if (!el) return;
  const ids = selectionList();
  if (!ids.length) {
    el.className = "sel-card muted";
    el.textContent = "No selection";
    void refreshEffectsList();
    return;
  }
  if (ids.length > 1) {
    el.className = "sel-card";
    el.innerHTML = `<div><b>${ids.length}</b> clips selected</div>`;
    void refreshEffectsList();
    return;
  }
  const c = state.clips.get(ids[0]);
  if (!c) {
    el.className = "sel-card muted";
    el.textContent = ids[0];
    void refreshEffectsList();
    return;
  }
  el.className = "sel-card";
  const name = c.name || c.label || c.id;
  el.innerHTML = [
    `<div class="sel-title">${escapeHtml(name)}</div>`,
    `<div class="kv">id <span>${escapeHtml(c.id)}</span></div>`,
    `<div class="kv">f${c.start} · ${c.dur}f · ${c.speed ?? 1}×</div>`,
    `<div class="kv">gain ${c.gain_db ?? 0} dB · opac ${c.opacity ?? 1}</div>`,
    c.muted ? `<div class="kv">muted</div>` : "",
    c.link_group ? `<div class="kv">link ${escapeHtml(c.link_group)}</div>` : "",
  ]
    .filter(Boolean)
    .join("");
  void refreshEffectsList();
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

async function moveClip(clipId: string, startFrame: number) {
  $("status-msg").textContent = `Moving ${clipId} → f${startFrame}…`;
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      clip?: { start?: number };
    }>("/api/clip/move", {
      clip_id: clipId,
      start_frame: startFrame,
      refresh_preview: true,
      quick_preview: true,
    });
    if (r.timeline) {
      applyTimelineView(r.timeline);
      state.proxyFresh = !!r.timeline.proxy?.fresh;
    }
    $("status-msg").textContent = `Moved ${clipId} → f${startFrame}`;
    void seekTo(state.t);
  } catch (e) {
    $("status-msg").textContent = `Move failed: ${e}`;
    await refresh();
  }
}

async function nudgeSelection(deltaFrames: number) {
  const ids = selectionList();
  if (!ids.length || deltaFrames === 0) return;
  $("status-msg").textContent = `Nudge ${ids.length} clip(s) Δ${deltaFrames}…`;
  try {
    const r = await postJson<{ timeline?: TimelineView }>("/api/clips/nudge", {
      clip_ids: ids,
      delta_frames: deltaFrames,
      follow_links: true,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    $("status-msg").textContent = `Nudged ${ids.length} · Δ${deltaFrames}`;
    void seekTo(state.t);
  } catch (e) {
    $("status-msg").textContent = `Nudge failed: ${e}`;
    await refresh();
  }
}

function rippleEnabled(): boolean {
  return ($("chk-ripple") as HTMLInputElement).checked;
}

function snapEnabled(): boolean {
  const el = document.getElementById("chk-snap") as HTMLInputElement | null;
  return el ? el.checked : true;
}

/** Snap frame to nearest edge/marker within threshold. */
function snapFrame(frame: number, exclude?: Set<number>): number {
  if (!snapEnabled() || !state.snapFrames.length) return frame;
  const thr = state.snapThr;
  let best = frame;
  let bestD = thr + 1;
  for (const p of state.snapFrames) {
    if (exclude?.has(p)) continue;
    const d = Math.abs(p - frame);
    if (d < bestD) {
      bestD = d;
      best = p;
    }
  }
  return bestD <= thr ? best : frame;
}

/**
 * Snap a move: prefer snapping start; if end is closer to a target, shift so end aligns.
 */
function snapMoveStart(start: number, dur: number, exclude: Set<number>): number {
  if (!snapEnabled()) return Math.max(0, start);
  const s0 = Math.max(0, start);
  const end = s0 + dur;
  const snapS = snapFrame(s0, exclude);
  const snapE = snapFrame(end, exclude);
  const dS = Math.abs(snapS - s0);
  const dE = Math.abs(snapE - end);
  if (dS <= state.snapThr && dS <= dE) return Math.max(0, snapS);
  if (dE <= state.snapThr) return Math.max(0, snapE - dur);
  return s0;
}

async function deleteSelection() {
  const ids = selectionList();
  if (!ids.length) return;
  const ripple = rippleEnabled();
  $("status-msg").textContent = `Delete ${ids.length} clip(s)${ripple ? " (ripple)" : ""}…`;
  try {
    const r = await postJson<{ timeline?: TimelineView }>("/api/clips/delete", {
      clip_ids: ids,
      ripple,
      follow_links: true,
    });
    state.selected.clear();
    if (r.timeline) applyTimelineView(r.timeline);
    $("sel-count").textContent = "0";
    $("status-msg").textContent = `Deleted ${ids.length}${ripple ? " ripple" : ""}`;
    void seekTo(state.t);
  } catch (e) {
    $("status-msg").textContent = `Delete failed: ${e}`;
    await refresh();
  }
}

type MediaBin = {
  count?: number;
  items?: Array<{
    id: string;
    kind?: string;
    path?: string;
    duration_frames?: number;
    label?: string;
  }>;
  // list_media_bin may use different shape
  media?: Array<Record<string, unknown>>;
};

function renderMediaBin(data: MediaBin | null) {
  const el = $("media-list");
  const items =
    data?.items ||
    (Array.isArray(data?.media) ? (data!.media as MediaBin["items"]) : null) ||
    [];
  if (!items?.length) {
    el.className = "media-list muted";
    el.textContent = state.projectOpen ? "Empty bin — Import files" : "No project";
    return;
  }
  el.className = "media-list";
  el.innerHTML = "";
  for (const m of items) {
    const row = document.createElement("div");
    row.className = "media-row";
    const name = document.createElement("div");
    name.textContent =
      m.label ||
      (m.path ? String(m.path).split(/[/\\]/).pop() : m.id) ||
      m.id;
    const kind = document.createElement("div");
    kind.className = "kind";
    const dur =
      typeof m.duration_frames === "number"
        ? ` · ${m.duration_frames}f`
        : "";
    kind.textContent = `${m.kind || "?"}${dur}`;
    row.appendChild(name);
    row.appendChild(kind);
    row.title = `${m.path || m.id} · double-click to place at playhead`;
    row.dataset.mediaId = m.id;
    if (m.kind) row.dataset.kind = m.kind;
    row.addEventListener("dblclick", () => {
      void placeMediaAtPlayhead(m.id, m.kind || "video");
    });
    el.appendChild(row);
  }
}

function playheadFrame(): number {
  return Math.max(0, Math.round(state.t * state.fps));
}

function trackForKind(kind: string): string | null {
  const want =
    kind === "audio" ? "audio" : "video"; // image → video
  const hit = state.tracks.find((t) => t.kind === want);
  return hit?.id ?? state.tracks[0]?.id ?? null;
}

async function placeMediaAtPlayhead(mediaId: string, kind: string) {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const trackId = trackForKind(kind);
  if (!trackId) {
    $("status-msg").textContent = "No track for this media kind";
    return;
  }
  const start = playheadFrame();
  $("status-msg").textContent = `Place ${mediaId} @ f${start}…`;
  try {
    const r = await postJson<{ timeline?: TimelineView; clip_id?: string }>(
      "/api/place_media",
      {
        media_id: mediaId,
        track_id: trackId,
        start,
        mode: "insert",
      },
    );
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    $("status-msg").textContent = `Placed ${r.clip_id || mediaId} @ f${start}`;
    void seekTo(state.t);
  } catch (e) {
    $("status-msg").textContent = `Place failed: ${e}`;
  }
}

async function razorAtPlayhead() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const at = playheadFrame();
  $("status-msg").textContent = `Razor @ f${at}…`;
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      split_count?: number;
    }>("/api/razor", { at_frame: at });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    $("status-msg").textContent = `Razor @ f${at}: ${r.split_count ?? 0} split(s)`;
    void seekTo(state.t);
  } catch (e) {
    $("status-msg").textContent = `Razor failed: ${e}`;
  }
}

async function saveProject() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  $("status-msg").textContent = "Saving…";
  try {
    await postJson<{ saved?: boolean }>("/api/save", {});
    $("status-msg").textContent = "Saved";
  } catch (e) {
    $("status-msg").textContent = `Save failed: ${e}`;
  }
}

async function refreshMarkers() {
  if (!state.projectOpen) {
    state.markers = [];
    renderMarkerList();
    return;
  }
  try {
    const data = await getJson<{ markers?: Marker[]; count?: number }>(
      "/api/markers",
    );
    state.markers = data.markers || [];
  } catch {
    state.markers = [];
  }
  renderMarkerList();
  const ruler = document.querySelector(
    ".marker-ruler",
  ) as HTMLElement | null;
  if (ruler) paintMarkerRuler(ruler);
}

function renderMarkerList() {
  const el = document.getElementById("marker-list");
  if (!el) return;
  if (!state.markers.length) {
    el.textContent = "No markers (M to add)";
    el.className = "marker-list muted";
    return;
  }
  el.className = "marker-list";
  el.innerHTML = "";
  for (const m of state.markers) {
    const row = document.createElement("div");
    row.className = "marker-row";
    const f = m.frame ?? 0;
    const lab = m.label || `M${f}`;
    row.textContent = `${lab} · f${f}`;
    row.title = "Click seek · Alt+click delete";
    row.style.borderLeftColor = m.color || "var(--color-primary)";
    row.addEventListener("click", (ev) => {
      if (ev.altKey) {
        void deleteMarker(m.id);
      } else {
        stopPlay();
        void seekTo(f / state.fps);
      }
    });
    el.appendChild(row);
  }
}

async function addMarkerAtPlayhead() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const frame = playheadFrame();
  $("status-msg").textContent = `Marker @ f${frame}…`;
  try {
    const r = await postJson<{ markers?: Marker[] }>("/api/markers", {
      frame,
      label: `M${frame}`,
    });
    state.markers = r.markers || [];
    renderMarkerList();
    // re-render timeline to paint ticks
    const body = $("timeline-body");
    if (body.querySelector(".marker-ruler")) {
      paintMarkerRuler(body.querySelector(".marker-ruler") as HTMLElement);
    }
    $("status-msg").textContent = `Marker @ f${frame}`;
  } catch (e) {
    $("status-msg").textContent = `Marker failed: ${e}`;
  }
}

async function deleteMarker(markerId: string) {
  try {
    const r = await postJson<{ markers?: Marker[] }>("/api/markers/delete", {
      marker_id: markerId,
    });
    state.markers = r.markers || [];
    renderMarkerList();
    const body = $("timeline-body");
    const ruler = body.querySelector(".marker-ruler") as HTMLElement | null;
    if (ruler) paintMarkerRuler(ruler);
    $("status-msg").textContent = `Deleted marker ${markerId}`;
  } catch (e) {
    $("status-msg").textContent = `Delete marker failed: ${e}`;
  }
}

function paintMarkerRuler(ruler: HTMLElement) {
  const durF = Math.max(1, state.durationFrames || 1);
  ruler.innerHTML = "";
  const lane = document.createElement("div");
  lane.className = "marker-lane";
  // work area range
  const inn = state.workIO.in_frame;
  const out = state.workIO.out_frame;
  if (inn != null || out != null) {
    const a = inn ?? 0;
    const b = out ?? durF;
    const left = (Math.min(a, b) / durF) * 100;
    const width = (Math.abs((out ?? durF) - (inn ?? 0)) / durF) * 100;
    const range = document.createElement("div");
    range.className = "work-range";
    range.style.left = `${left}%`;
    range.style.width = `${Math.max(0.3, width)}%`;
    range.title = `Work I/O ${inn ?? "—"}–${out ?? "—"}`;
    lane.appendChild(range);
  }
  if (inn != null) {
    const tick = document.createElement("div");
    tick.className = "io-tick in";
    tick.style.left = `${(inn / durF) * 100}%`;
    tick.title = `In f${inn}`;
    lane.appendChild(tick);
  }
  if (out != null) {
    const tick = document.createElement("div");
    tick.className = "io-tick out";
    tick.style.left = `${(out / durF) * 100}%`;
    tick.title = `Out f${out}`;
    lane.appendChild(tick);
  }
  for (const m of state.markers) {
    const f = m.frame ?? 0;
    const tick = document.createElement("div");
    tick.className = "marker-tick";
    tick.style.left = `${(f / durF) * 100}%`;
    tick.style.background = m.color || "var(--color-primary)";
    tick.title = `${m.label || m.id} · f${f} · click seek · Alt+click delete`;
    tick.addEventListener("click", (ev) => {
      ev.stopPropagation();
      if (ev.altKey) void deleteMarker(m.id);
      else {
        stopPlay();
        void seekTo(f / state.fps);
      }
    });
    lane.appendChild(tick);
  }
  ruler.appendChild(lane);
}

function applyWorkIO(io: WorkInOut | null | undefined) {
  state.workIO = {
    in_frame: io?.in_frame ?? null,
    out_frame: io?.out_frame ?? null,
    ready: !!io?.ready,
    duration_frames: io?.duration_frames ?? null,
  };
  const el = document.getElementById("io-display");
  if (el) {
    const a = state.workIO.in_frame;
    const b = state.workIO.out_frame;
    if (a == null && b == null) el.textContent = "I/O —";
    else el.textContent = `I ${a ?? "—"} · O ${b ?? "—"}`;
  }
  const ruler = document.querySelector(".marker-ruler") as HTMLElement | null;
  if (ruler) paintMarkerRuler(ruler);
}

async function setInPoint() {
  if (!state.projectOpen) return;
  const frame = playheadFrame();
  try {
    const r = await postJson<WorkInOut>("/api/in_out/in", { frame });
    applyWorkIO(r);
    $("status-msg").textContent = `In @ f${frame}`;
  } catch (e) {
    $("status-msg").textContent = `Set In failed: ${e}`;
  }
}

async function setOutPoint() {
  if (!state.projectOpen) return;
  const frame = playheadFrame();
  try {
    const r = await postJson<WorkInOut>("/api/in_out/out", { frame });
    applyWorkIO(r);
    $("status-msg").textContent = `Out @ f${frame}`;
  } catch (e) {
    $("status-msg").textContent = `Set Out failed: ${e}`;
  }
}

async function clearInOut() {
  if (!state.projectOpen) return;
  try {
    const r = await postJson<WorkInOut>("/api/in_out/clear", {});
    applyWorkIO(r);
    $("status-msg").textContent = "I/O cleared";
  } catch (e) {
    $("status-msg").textContent = `Clear I/O failed: ${e}`;
  }
}

async function goToInOut(which: "in" | "out") {
  const f =
    which === "in" ? state.workIO.in_frame : state.workIO.out_frame;
  if (f == null) {
    $("status-msg").textContent = `No ${which.toUpperCase()} point`;
    return;
  }
  stopPlay();
  void seekTo(f / state.fps);
}

async function muteSelection(force?: boolean) {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clip(s) to mute";
    return;
  }
  // toggle: if force undefined, mute if any unmuted
  let muted = force;
  if (muted === undefined) {
    const blocks = Array.from(
      document.querySelectorAll<HTMLElement>(".clip-block.selected"),
    );
    const anyLive = blocks.some((b) => !b.classList.contains("muted"));
    muted = anyLive;
  }
  $("status-msg").textContent = `${muted ? "Mute" : "Unmute"} ${ids.length}…`;
  try {
    const r = await postJson<{ timeline?: TimelineView }>("/api/clips/mute", {
      clip_ids: ids,
      muted,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    $("status-msg").textContent = `${muted ? "Muted" : "Unmuted"} ${ids.length}`;
  } catch (e) {
    $("status-msg").textContent = `Mute failed: ${e}`;
  }
}

async function setTrackFlag(
  trackId: string,
  flag: "mute" | "solo" | "lock",
  value: boolean,
) {
  const path =
    flag === "mute"
      ? "/api/track/mute"
      : flag === "solo"
        ? "/api/track/solo"
        : "/api/track/lock";
  try {
    const r = await postJson<{ timeline?: TimelineView }>(path, {
      track_id: trackId,
      value,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    $("status-msg").textContent = `Track ${flag} ${value ? "on" : "off"}`;
  } catch (e) {
    $("status-msg").textContent = `Track ${flag} failed: ${e}`;
  }
}

function goToMarker(dir: -1 | 1) {
  if (!state.markers.length) {
    $("status-msg").textContent = "No markers";
    return;
  }
  const sorted = [...state.markers].sort(
    (a, b) => (a.frame ?? 0) - (b.frame ?? 0),
  );
  const cur = playheadFrame();
  let target: Marker | undefined;
  if (dir > 0) {
    target = sorted.find((m) => (m.frame ?? 0) > cur);
    if (!target) target = sorted[0];
  } else {
    for (let i = sorted.length - 1; i >= 0; i--) {
      if ((sorted[i].frame ?? 0) < cur) {
        target = sorted[i];
        break;
      }
    }
    if (!target) target = sorted[sorted.length - 1];
  }
  if (!target) return;
  stopPlay();
  const f = target.frame ?? 0;
  $("status-msg").textContent = `Marker ${target.label || target.id} @ f${f}`;
  void seekTo(f / state.fps);
}

/** Jump playhead to prev/next snap point (clip edges + markers). */
function goToEditPoint(dir: -1 | 1) {
  const pts = state.snapFrames.length
    ? state.snapFrames
    : [0, state.durationFrames];
  const sorted = [...new Set(pts)].sort((a, b) => a - b);
  if (!sorted.length) return;
  const cur = playheadFrame();
  let target: number | undefined;
  if (dir > 0) {
    target = sorted.find((f) => f > cur);
    if (target === undefined) target = sorted[0];
  } else {
    for (let i = sorted.length - 1; i >= 0; i--) {
      if (sorted[i] < cur) {
        target = sorted[i];
        break;
      }
    }
    if (target === undefined) target = sorted[sorted.length - 1];
  }
  stopPlay();
  $("status-msg").textContent = `Edit point f${target}`;
  void seekTo(target / state.fps);
}

async function addTrack(kind: "video" | "audio") {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  try {
    await fetch(`${API_BASE}/api/track?kind=${kind}`, { method: "POST" });
    $("status-msg").textContent = `Added ${kind} track`;
    await refresh();
  } catch (e) {
    $("status-msg").textContent = `Add track failed: ${e}`;
  }
}

async function copySelection() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select a clip to copy";
    return;
  }
  const clipId = ids[0];
  try {
    await postJson("/api/clip/copy", { clip_id: clipId });
    $("status-msg").textContent = `Copied ${clipId}`;
  } catch (e) {
    $("status-msg").textContent = `Copy failed: ${e}`;
  }
}

async function pasteAtPlayhead() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const trackId = state.tracks[0]?.id;
  if (!trackId) {
    $("status-msg").textContent = "No track to paste onto";
    return;
  }
  const frame = playheadFrame();
  $("status-msg").textContent = `Paste @ f${frame}…`;
  try {
    const r = await postJson<{ timeline?: TimelineView; clip_id?: string }>(
      "/api/clip/paste",
      {
        track_id: trackId,
        playhead_frame: frame,
        mode: "insert",
      },
    );
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    $("status-msg").textContent = `Pasted ${r.clip_id || ""} @ f${frame}`;
    void seekTo(state.t);
  } catch (e) {
    $("status-msg").textContent = `Paste failed: ${e}`;
  }
}

async function duplicateSelection() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select a clip to duplicate";
    return;
  }
  try {
    const r = await postJson<{ timeline?: TimelineView }>(
      "/api/clip/duplicate",
      { clip_id: ids[0] },
    );
    if (r.timeline) applyTimelineView(r.timeline);
    $("status-msg").textContent = `Duplicated ${ids[0]}`;
  } catch (e) {
    $("status-msg").textContent = `Duplicate failed: ${e}`;
  }
}

async function refreshMediaBin() {
  if (!state.projectOpen) {
    renderMediaBin(null);
    return;
  }
  try {
    const data = await getJson<MediaBin>("/api/media");
    // normalize alternate shapes from list_media_bin
    if (!data.items && Array.isArray((data as { media?: unknown }).media)) {
      const raw = (data as { media: Array<Record<string, unknown>> }).media;
      data.items = raw.map((m) => ({
        id: String(m.id || m.media_id || ""),
        kind: m.kind as string | undefined,
        path: m.path as string | undefined,
        duration_frames: m.duration_frames as number | undefined,
        label: (m.label || m.name) as string | undefined,
      }));
    }
    // some APIs return {count, entries}
    if (!data.items && Array.isArray((data as { entries?: unknown }).entries)) {
      const raw = (data as { entries: Array<Record<string, unknown>> }).entries;
      data.items = raw.map((m) => ({
        id: String(m.id || ""),
        kind: m.kind as string | undefined,
        path: m.path as string | undefined,
        duration_frames: m.duration_frames as number | undefined,
      }));
    }
    renderMediaBin(data);
  } catch {
    $("media-list").textContent = "Media list unavailable";
  }
}

async function importFiles(fileList: FileList | null) {
  if (!fileList?.length) return;
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open or create a project first";
    return;
  }
  const fd = new FormData();
  for (const f of Array.from(fileList)) {
    fd.append("files", f, f.name);
  }
  $("status-msg").textContent = `Importing ${fileList.length} file(s)…`;
  try {
    const res = await fetch(`${API_BASE}/api/upload_place?build_proxy=false`, {
      method: "POST",
      body: fd,
    });
    if (!res.ok) {
      const t = await res.text();
      throw new Error(`HTTP ${res.status}: ${t.slice(0, 200)}`);
    }
    const body = (await res.json()) as {
      placed?: unknown[];
      errors?: unknown[];
      timeline?: TimelineView;
    };
    const n = body.placed?.length ?? 0;
    $("status-msg").textContent = `Imported ${n} clip(s)`;
    if (body.timeline) applyTimelineView(body.timeline);
    else await refresh();
    await refreshMediaBin();
    void seekTo(state.t);
  } catch (e) {
    $("status-msg").textContent = `Import failed: ${e}`;
  }
}

function selectedExportPreset(): string {
  const el = document.getElementById("export-preset") as HTMLSelectElement | null;
  return el?.value || "draft";
}

async function loadExportPresets() {
  const el = document.getElementById("export-preset") as HTMLSelectElement | null;
  if (!el) return;
  try {
    const r = await getJson<{
      presets?: Array<{ id: string; description?: string }>;
    }>("/api/export/presets");
    const presets = r.presets || [];
    if (!presets.length) return;
    const cur = el.value || "draft";
    el.innerHTML = "";
    for (const p of presets) {
      const opt = document.createElement("option");
      opt.value = p.id;
      opt.textContent = p.id;
      opt.title = p.description || p.id;
      el.appendChild(opt);
    }
    if ([...el.options].some((o) => o.value === cur)) el.value = cur;
    else if ([...el.options].some((o) => o.value === "draft")) el.value = "draft";
  } catch {
    /* keep static options */
  }
}

async function exportProject() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  stopPlay();
  const preset = selectedExportPreset();
  $("status-msg").textContent = `Exporting (${preset})…`;
  ($("btn-export") as HTMLButtonElement).disabled = true;
  try {
    const r = await postJson<{
      ok?: boolean;
      path?: string;
      error?: string;
      warning?: string;
      preset?: string;
    }>(`/api/desktop/export_preset?preset=${encodeURIComponent(preset)}`, {});
    if (!r.ok) {
      $("status-msg").textContent =
        `Export soft-fail: ${r.error || r.path || "see log"}`;
    } else {
      $("status-msg").textContent =
        `Exported [${r.preset || preset}]: ${r.path}${r.warning ? " (warn)" : ""}`;
    }
  } catch (e) {
    // fallback legacy full export
    try {
      const r = await postJson<{
        ok?: boolean;
        path?: string;
      }>("/api/desktop/export", {});
      $("status-msg").textContent = r.ok
        ? `Exported: ${r.path}`
        : `Export soft-fail: ${r.path || "see delivery"}`;
    } catch (e2) {
      $("status-msg").textContent = `Export failed: ${e2}`;
    }
  } finally {
    ($("btn-export") as HTMLButtonElement).disabled = false;
  }
}

async function refreshProjectStats() {
  const el = document.getElementById("project-stats");
  if (!el) return;
  if (!state.projectOpen) {
    el.className = "project-stats muted";
    el.textContent = "—";
    return;
  }
  try {
    const r = await getJson<{
      duration_seconds?: number;
      clip_count?: number;
      media_count?: number;
      unused_media_count?: number;
      track_count?: number;
      marker_count?: number;
      link_group_count?: number;
      dirty?: boolean;
      resolution?: { w?: number; h?: number };
      fps?: number;
    }>("/api/project/stats");
    el.className = "project-stats";
    const res =
      r.resolution?.w && r.resolution?.h
        ? `${r.resolution.w}×${r.resolution.h}`
        : "—";
    el.innerHTML = [
      `<div>${res} · ${r.fps ?? "—"}fps · ${(r.duration_seconds ?? 0).toFixed(2)}s</div>`,
      `<div class="kv">${r.clip_count ?? 0} clips · ${r.media_count ?? 0} media` +
        (r.unused_media_count ? ` (${r.unused_media_count} unused)` : "") +
        ` · ${r.track_count ?? 0} trk · ${r.marker_count ?? 0} mk</div>`,
      r.link_group_count
        ? `<div class="kv">${r.link_group_count} link group(s)</div>`
        : "",
    ]
      .filter(Boolean)
      .join("");
  } catch {
    el.className = "project-stats muted";
    el.textContent = "stats n/a";
  }
}

async function splitAtMarkers() {
  if (!state.projectOpen) return;
  $("status-msg").textContent = "Split at markers…";
  try {
    const r = await postJson<{ timeline?: TimelineView; count?: number }>(
      "/api/split_at_markers",
      {},
    );
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    $("status-msg").textContent = `Split at markers: ${r.count ?? "ok"}`;
    void seekTo(state.t);
  } catch (e) {
    $("status-msg").textContent = `Split@markers failed: ${e}`;
  }
}

async function nameSelectionFromMedia() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clip(s) to name from media";
    return;
  }
  try {
    const r = await postJson<{ timeline?: TimelineView }>(
      "/api/clips/name_from_media",
      { clip_ids: ids, strip_ext: true },
    );
    if (r.timeline) applyTimelineView(r.timeline);
    $("status-msg").textContent = `Named ${ids.length} from media`;
  } catch (e) {
    $("status-msg").textContent = `Name from media failed: ${e}`;
  }
}

async function duplicateSelectedTrack() {
  if (!state.projectOpen) return;
  // prefer track of first selected clip, else first track
  let trackId: string | null = null;
  const ids = selectionList();
  if (ids.length) {
    trackId = state.clips.get(ids[0])?.trackId || null;
  }
  if (!trackId) trackId = state.tracks[0]?.id || null;
  if (!trackId) {
    $("status-msg").textContent = "No track to duplicate";
    return;
  }
  $("status-msg").textContent = `Duplicate track ${trackId}…`;
  try {
    const r = await postJson<{ timeline?: TimelineView }>(
      "/api/track/duplicate",
      { track_id: trackId, copy_clips: true },
    );
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    $("status-msg").textContent = `Duplicated track ${trackId}`;
  } catch (e) {
    $("status-msg").textContent = `Dup track failed: ${e}`;
  }
}

async function purgeUnusedMedia() {
  if (!state.projectOpen) return;
  $("status-msg").textContent = "Purging unused media…";
  try {
    const unused = await getJson<{ count?: number; media?: unknown[] }>(
      "/api/media/unused",
    );
    const n = unused.count ?? (unused.media?.length ?? 0);
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
      removed?: unknown[];
    }>("/api/media/purge_unused", { delete_files: false });
    if (r.timeline) applyTimelineView(r.timeline);
    await refreshMediaBin();
    await refreshProjectStats();
    $("status-msg").textContent = `Purged ${r.count ?? n} unused media`;
  } catch (e) {
    $("status-msg").textContent = `Purge failed: ${e}`;
  }
}

async function soloSelection(exclusive = true) {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select a clip to solo";
    return;
  }
  try {
    const r = await postJson<{ timeline?: TimelineView }>("/api/clip/solo", {
      clip_id: ids[0],
      exclusive,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    $("status-msg").textContent = `Solo ${ids[0]}`;
  } catch (e) {
    $("status-msg").textContent = `Solo failed: ${e}`;
  }
}

async function unmuteAllClips() {
  if (!state.projectOpen) return;
  try {
    const r = await postJson<{ timeline?: TimelineView }>(
      "/api/clips/unmute_all",
      {},
    );
    if (r.timeline) applyTimelineView(r.timeline);
    $("status-msg").textContent = "Unmuted all clips";
  } catch (e) {
    // endpoint may be query-only
    try {
      const res = await fetch(`${API_BASE}/api/clips/unmute_all`, {
        method: "POST",
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const body = (await res.json()) as { timeline?: TimelineView };
      if (body.timeline) applyTimelineView(body.timeline);
      $("status-msg").textContent = "Unmuted all clips";
    } catch (e2) {
      $("status-msg").textContent = `Unmute all failed: ${e2}`;
    }
  }
}

async function jlCutSelection(kind: "j" | "l", frames = 12) {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = `Select a linked clip for ${kind.toUpperCase()}-cut`;
    return;
  }
  const path = kind === "j" ? "/api/clip/j_cut" : "/api/clip/l_cut";
  try {
    const r = await postJson<{ timeline?: TimelineView }>(path, {
      clip_id: ids[0],
      frames,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    $("status-msg").textContent = `${kind.toUpperCase()}-cut ${frames}f`;
  } catch (e) {
    $("status-msg").textContent = `${kind.toUpperCase()}-cut failed: ${e}`;
  }
}

async function snapSelection(to: "prev_end" | "next_start" | "zero" = "prev_end") {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clip(s) to snap";
    return;
  }
  try {
    let last: TimelineView | undefined;
    for (const clipId of ids) {
      const r = await postJson<{ timeline?: TimelineView }>("/api/clip/snap", {
        clip_id: clipId,
        to,
      });
      if (r.timeline) last = r.timeline;
    }
    if (last) applyTimelineView(last);
    $("status-msg").textContent = `Snap → ${to} (${ids.length})`;
  } catch (e) {
    $("status-msg").textContent = `Snap failed: ${e}`;
  }
}

async function quantizeSelection(grid = 10) {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clip(s) to quantize";
    return;
  }
  try {
    const r = await postJson<{ timeline?: TimelineView }>(
      "/api/clips/quantize",
      { clip_ids: ids, grid_frames: grid, edge: "start" },
    );
    if (r.timeline) applyTimelineView(r.timeline);
    $("status-msg").textContent = `Quantize ${grid}f grid (${ids.length})`;
  } catch (e) {
    $("status-msg").textContent = `Quantize failed: ${e}`;
  }
}

async function alignSelectionToPlayhead() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clip(s) to align";
    return;
  }
  const frame = playheadFrame();
  try {
    const r = await postJson<{ timeline?: TimelineView }>("/api/clips/align", {
      clip_ids: ids,
      to_frame: frame,
      mode: "start",
    });
    if (r.timeline) applyTimelineView(r.timeline);
    $("status-msg").textContent = `Align start → f${frame}`;
  } catch (e) {
    $("status-msg").textContent = `Align failed: ${e}`;
  }
}

async function slipSelection(delta: number) {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clip(s) to slip";
    return;
  }
  try {
    let last: TimelineView | undefined;
    for (const clipId of ids) {
      const r = await postJson<{ timeline?: TimelineView }>("/api/clip/slip", {
        clip_id: clipId,
        delta_src_frames: delta,
      });
      if (r.timeline) last = r.timeline;
    }
    if (last) applyTimelineView(last);
    $("status-msg").textContent = `Slip ${delta > 0 ? "+" : ""}${delta}f`;
    void seekTo(state.t);
  } catch (e) {
    $("status-msg").textContent = `Slip failed: ${e}`;
  }
}

async function rollSelection(delta: number) {
  const ids = selectionList();
  if (ids.length !== 2) {
    $("status-msg").textContent = "Select 2 adjacent clips to roll";
    return;
  }
  const infos = ids
    .map((id) => state.clips.get(id))
    .filter((c): c is ClipInfo => !!c)
    .sort((a, b) => a.start - b.start);
  if (infos.length !== 2) {
    $("status-msg").textContent = "Roll needs two known clips";
    return;
  }
  try {
    const r = await postJson<{ timeline?: TimelineView }>("/api/clip/roll", {
      left_clip_id: infos[0].id,
      right_clip_id: infos[1].id,
      delta_frames: delta,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    $("status-msg").textContent = `Roll ${delta > 0 ? "+" : ""}${delta}f`;
  } catch (e) {
    $("status-msg").textContent = `Roll failed: ${e}`;
  }
}

async function loadStyles() {
  const el = document.getElementById("style-select") as HTMLSelectElement | null;
  if (!el) return;
  try {
    const r = await getJson<{ names?: string[]; styles?: Record<string, unknown> }>(
      "/api/styles",
    );
    const names = r.names || Object.keys(r.styles || {});
    if (!names.length) return;
    const cur = el.value;
    el.innerHTML = "";
    for (const n of names) {
      const opt = document.createElement("option");
      opt.value = n;
      opt.textContent = n;
      el.appendChild(opt);
    }
    if ([...el.options].some((o) => o.value === cur)) el.value = cur;
  } catch {
    /* keep static */
  }
}

async function applySelectedStyle() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const el = document.getElementById("style-select") as HTMLSelectElement | null;
  const name = el?.value || "documentary";
  const ids = selectionList();
  $("status-msg").textContent = `Apply style ${name}…`;
  try {
    await postJson("/api/style", {
      styles: name,
      clip_ids: ids.length ? ids : null,
      video_only: true,
      apply_motion: true,
    });
    await refresh();
    $("status-msg").textContent = `Style ${name} applied`;
  } catch (e) {
    $("status-msg").textContent = `Style failed: ${e}`;
  }
}

async function copyEffectsFromSelection() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select a clip to copy effects";
    return;
  }
  try {
    const r = await postJson<{ count?: number; types?: string[] }>(
      "/api/clip/copy_effects",
      { clip_id: ids[0] },
    );
    $("status-msg").textContent =
      `Copied ${r.count ?? 0} fx: ${(r.types || []).join(",") || "—"}`;
  } catch (e) {
    $("status-msg").textContent = `Copy FX failed: ${e}`;
  }
}

async function pasteEffectsToSelection() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clip(s) to paste effects";
    return;
  }
  try {
    let last: TimelineView | undefined;
    for (const clipId of ids) {
      const r = await postJson<{ timeline?: TimelineView }>(
        "/api/clip/paste_effects",
        { clip_id: clipId, replace: true },
      );
      if (r.timeline) last = r.timeline;
    }
    if (last) applyTimelineView(last);
    $("status-msg").textContent = `Pasted FX → ${ids.length}`;
  } catch (e) {
    $("status-msg").textContent = `Paste FX failed: ${e}`;
  }
}

async function copyAttributesFromSelection() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select a clip to copy attributes";
    return;
  }
  try {
    await postJson("/api/clip/copy_attributes", { clip_id: ids[0] });
    $("status-msg").textContent = `Copied attributes from ${ids[0]}`;
  } catch (e) {
    $("status-msg").textContent = `Copy attrs failed: ${e}`;
  }
}

async function pasteAttributesToSelection() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clip(s) to paste attributes";
    return;
  }
  try {
    let last: TimelineView | undefined;
    for (const clipId of ids) {
      const r = await postJson<{ timeline?: TimelineView }>(
        "/api/clip/paste_attributes",
        {
          clip_id: clipId,
          speed: true,
          position: true,
          gain: true,
          opacity: true,
          fades: true,
        },
      );
      if (r.timeline) last = r.timeline;
    }
    if (last) applyTimelineView(last);
    $("status-msg").textContent = `Pasted attrs → ${ids.length}`;
  } catch (e) {
    $("status-msg").textContent = `Paste attrs failed: ${e}`;
  }
}

async function refreshEffectsList() {
  const el = document.getElementById("effects-list");
  if (!el) return;
  const ids = selectionList();
  if (ids.length !== 1) {
    el.className = "effects-list muted";
    el.textContent = ids.length ? "Select 1 clip for FX list" : "No selection";
    return;
  }
  try {
    const r = await getJson<{
      count?: number;
      effects?: Array<{ type?: string }>;
    }>(`/api/clip/effects/${encodeURIComponent(ids[0])}`);
    const fx = r.effects || [];
    if (!fx.length) {
      el.className = "effects-list muted";
      el.textContent = "No effects";
      return;
    }
    el.className = "effects-list";
    el.innerHTML = "";
    for (const e of fx) {
      const row = document.createElement("div");
      row.className = "effects-row";
      row.textContent = e.type || "?";
      el.appendChild(row);
    }
  } catch {
    el.className = "effects-list muted";
    el.textContent = "FX list n/a";
  }
}

async function runReview() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  $("status-msg").textContent = "Running review…";
  try {
    const r = await postJson<Record<string, unknown>>("/api/review", {});
    const el = document.getElementById("review-out");
    if (el) {
      el.className = "review-out";
      el.textContent = JSON.stringify(r, null, 0).slice(0, 400);
    }
    $("status-msg").textContent = "Review complete";
  } catch (e) {
    $("status-msg").textContent = `Review failed: ${e}`;
  }
}

async function makeSequenceSheet() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  $("status-msg").textContent = "Building sequence sheet…";
  try {
    const r = await postJson<{ path?: string; output_path?: string }>(
      "/api/sequence_sheet",
      { max_tiles: 12 },
    );
    const path = r.path || r.output_path;
    $("status-msg").textContent = path
      ? `Sheet: ${path}`
      : "Sequence sheet done";
    // try open image via API
    try {
      const img = document.getElementById("sheet-preview") as HTMLImageElement | null;
      if (img) {
        img.src = `${API_BASE}/api/sequence_sheet/image?t=${Date.now()}`;
        img.hidden = false;
      }
    } catch {
      /* optional */
    }
  } catch (e) {
    $("status-msg").textContent = `Sheet failed: ${e}`;
  }
}

async function slideSelection(delta: number) {
  const ids = selectionList();
  if (ids.length !== 1) {
    $("status-msg").textContent = "Select 1 middle clip to slide";
    return;
  }
  try {
    const r = await postJson<{ timeline?: TimelineView }>("/api/clip/slide", {
      clip_id: ids[0],
      delta_frames: delta,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    $("status-msg").textContent = `Slide ${delta > 0 ? "+" : ""}${delta}f`;
  } catch (e) {
    $("status-msg").textContent = `Slide failed: ${e}`;
  }
}

async function stretchSelection(factor: number) {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clip(s) to stretch";
    return;
  }
  try {
    let last: TimelineView | undefined;
    for (const id of ids) {
      const info = state.clips.get(id);
      if (!info) continue;
      const target = Math.max(1, Math.round(info.dur * factor));
      const r = await postJson<{ timeline?: TimelineView }>("/api/clip/stretch", {
        clip_id: id,
        target_duration_frames: target,
        clamp: true,
      });
      if (r.timeline) last = r.timeline;
    }
    if (last) applyTimelineView(last);
    $("status-msg").textContent = `Stretch ×${factor} (${ids.length})`;
  } catch (e) {
    $("status-msg").textContent = `Stretch failed: ${e}`;
  }
}

async function staggerSelection(offset = 6) {
  const ids = selectionList();
  if (ids.length < 2) {
    $("status-msg").textContent = "Select ≥2 clips to stagger";
    return;
  }
  // order by start
  const ordered = ids
    .map((id) => state.clips.get(id))
    .filter((c): c is ClipInfo => !!c)
    .sort((a, b) => a.start - b.start)
    .map((c) => c.id);
  try {
    const r = await postJson<{ timeline?: TimelineView }>("/api/clips/stagger", {
      clip_ids: ordered,
      offset_frames: offset,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    $("status-msg").textContent = `Stagger +${offset}f ×${ordered.length}`;
  } catch (e) {
    $("status-msg").textContent = `Stagger failed: ${e}`;
  }
}

async function reverseTrackOrder() {
  if (!state.projectOpen) return;
  let trackId: string | null = null;
  const ids = selectionList();
  if (ids.length) trackId = state.clips.get(ids[0])?.trackId || null;
  if (!trackId) trackId = state.tracks[0]?.id || null;
  if (!trackId) {
    $("status-msg").textContent = "No track to reverse";
    return;
  }
  try {
    const r = await postJson<{ timeline?: TimelineView }>(
      "/api/track/reverse_order",
      { track_id: trackId, pack_from: 0 },
    );
    if (r.timeline) applyTimelineView(r.timeline);
    $("status-msg").textContent = `Reversed track order ${trackId}`;
  } catch (e) {
    $("status-msg").textContent = `Reverse track failed: ${e}`;
  }
}

async function reverseSelectionClip() {
  const ids = selectionList();
  if (ids.length !== 1) {
    $("status-msg").textContent = "Select 1 clip to reverse";
    return;
  }
  try {
    const r = await postJson<{ timeline?: TimelineView }>("/api/clip/reverse", {
      clip_id: ids[0],
      replace: true,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    $("status-msg").textContent = `Reversed ${ids[0]}`;
  } catch (e) {
    $("status-msg").textContent = `Reverse clip failed: ${e}`;
  }
}

async function fillGapsOnTracks() {
  if (!state.projectOpen) return;
  $("status-msg").textContent = "Fill gaps…";
  try {
    let last: TimelineView | undefined;
    for (const t of state.tracks) {
      try {
        const r = await postJson<{ timeline?: TimelineView }>("/api/fill_gaps", {
          track_id: t.id,
          mode: "slug",
        });
        if (r.timeline) last = r.timeline;
      } catch {
        /* track may not support */
      }
    }
    if (last) applyTimelineView(last);
    else await refresh();
    $("status-msg").textContent = "Fill gaps done";
  } catch (e) {
    $("status-msg").textContent = `Fill gaps failed: ${e}`;
  }
}

async function freezeAtPlayhead(durationFrames = 15) {
  const ids = selectionList();
  if (ids.length !== 1) {
    $("status-msg").textContent = "Select 1 clip for freeze frame";
    return;
  }
  const ph = playheadFrame();
  $("status-msg").textContent = `Freeze @ f${ph}…`;
  try {
    const r = await postJson<{ timeline?: TimelineView; clip_id?: string }>(
      "/api/clip/freeze",
      {
        clip_id: ids[0],
        at_timeline_frame: ph,
        duration_frames: durationFrames,
      },
    );
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    $("status-msg").textContent = `Freeze ${durationFrames}f @ f${ph}`;
  } catch (e) {
    $("status-msg").textContent = `Freeze failed: ${e}`;
  }
}

async function matchDurationSelection() {
  const ids = selectionList();
  if (ids.length !== 2) {
    $("status-msg").textContent = "Select 2 clips: target then reference order (start order)";
    return;
  }
  const ordered = ids
    .map((id) => state.clips.get(id))
    .filter((c): c is ClipInfo => !!c)
    .sort((a, b) => a.start - b.start);
  if (ordered.length !== 2) {
    $("status-msg").textContent = "Match duration needs 2 known clips";
    return;
  }
  // stretch first to match second's duration (reference = later by default)
  // UX: selected[0] is target, selected[1] is reference if we use selection order
  const target = ids[0];
  const reference = ids[1];
  try {
    const r = await postJson<{ timeline?: TimelineView }>(
      "/api/clip/match_duration",
      { clip_id: target, reference_clip_id: reference, clamp: true },
    );
    if (r.timeline) applyTimelineView(r.timeline);
    $("status-msg").textContent = `Match duration ${target} ← ${reference}`;
  } catch (e) {
    $("status-msg").textContent = `Match duration failed: ${e}`;
  }
}

async function duplicateWorkArea() {
  if (!state.projectOpen) return;
  if (!state.workIO.ready) {
    $("status-msg").textContent = "Set In/Out for range duplicate";
    return;
  }
  const start = state.workIO.in_frame!;
  const end = state.workIO.out_frame!;
  let trackId =
    selectionList()
      .map((id) => state.clips.get(id)?.trackId)
      .find(Boolean) || state.tracks[0]?.id;
  if (!trackId) {
    $("status-msg").textContent = "No track for duplicate range";
    return;
  }
  // place after sequence end
  const destStart = Math.max(state.durationFrames, end);
  $("status-msg").textContent = `Dup range [${start},${end})…`;
  try {
    const r = await postJson<{ timeline?: TimelineView }>(
      "/api/duplicate_range",
      {
        start_frame: start,
        end_frame: end,
        track_id: trackId,
        dest_start: destStart,
      },
    );
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    $("status-msg").textContent = `Duplicated range → f${destStart}`;
  } catch (e) {
    $("status-msg").textContent = `Dup range failed: ${e}`;
  }
}

async function prepareExport() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  $("status-msg").textContent = "Prepare export…";
  try {
    const r = await postJson<{ timeline?: TimelineView; result?: unknown }>(
      "/api/prepare_export",
      {},
    );
    if (r.timeline) applyTimelineView(r.timeline);
    $("status-msg").textContent = "Export prepared";
  } catch (e) {
    $("status-msg").textContent = `Prepare failed: ${e}`;
  }
}

async function searchAndSelectClips() {
  if (!state.projectOpen) return;
  const input = document.getElementById("clip-search") as HTMLInputElement | null;
  const q = (input?.value || "").trim();
  if (!q) {
    $("status-msg").textContent = "Enter search text";
    return;
  }
  try {
    const r = await postJson<{
      count?: number;
      hits?: Array<{ clip_id: string }>;
    }>("/api/clips/search", { query: q });
    const ids = (r.hits || []).map((h) => h.clip_id).filter(Boolean);
    setSelection(ids);
    $("status-msg").textContent = `Search "${q}": ${ids.length} hit(s)`;
  } catch (e) {
    $("status-msg").textContent = `Search failed: ${e}`;
  }
}

async function stabilizeSelection() {
  const ids = selectionList();
  if (ids.length !== 1) {
    $("status-msg").textContent = "Select 1 clip to stabilize";
    return;
  }
  $("status-msg").textContent = "Stabilizing (may take a bit)…";
  try {
    const r = await postJson<{ timeline?: TimelineView }>(
      "/api/clip/stabilize",
      { clip_id: ids[0], replace: true, strength: 1.0 },
    );
    if (r.timeline) applyTimelineView(r.timeline);
    $("status-msg").textContent = `Stabilized ${ids[0]}`;
  } catch (e) {
    $("status-msg").textContent = `Stabilize failed: ${e}`;
  }
}

async function exportMarkersYoutube() {
  if (!state.projectOpen) return;
  try {
    const r = await postJson<{ path?: string; count?: number; text?: string }>(
      "/api/markers/export",
      { format: "youtube" },
    );
    const el = document.getElementById("review-out");
    if (el && r.text) {
      el.className = "review-out";
      el.textContent = String(r.text).slice(0, 500);
    }
    $("status-msg").textContent = r.path
      ? `Markers exported: ${r.path}`
      : `Markers export (${r.count ?? "ok"})`;
  } catch (e) {
    $("status-msg").textContent = `Export markers failed: ${e}`;
  }
}

async function openExportDir() {
  try {
    const r = await getJson<{
      path?: string;
      count?: number;
      files?: Array<{ name: string; path: string }>;
    }>("/api/desktop/export_dir");
    const el = document.getElementById("export-dir-list");
    if (el) {
      el.className = "export-dir-list";
      if (!r.files?.length) {
        el.className = "export-dir-list muted";
        el.textContent = r.path ? `Empty: ${r.path}` : "No exports yet";
      } else {
        el.innerHTML = "";
        const head = document.createElement("div");
        head.className = "kv";
        head.textContent = r.path || "";
        head.title = r.path || "";
        el.appendChild(head);
        for (const f of r.files.slice(-8)) {
          const row = document.createElement("div");
          row.className = "export-dir-row";
          row.textContent = f.name;
          row.title = f.path;
          el.appendChild(row);
        }
      }
    }
    $("status-msg").textContent = `Export dir: ${r.path} (${r.count ?? 0} files)`;
    // try open folder via opener plugin when under Tauri
    if (r.path && isTauri()) {
      try {
        const { openPath } = await import("@tauri-apps/plugin-opener");
        await openPath(r.path);
      } catch {
        /* list only in browser/dev */
      }
    }
  } catch (e) {
    $("status-msg").textContent = `Export dir failed: ${e}`;
  }
}

async function describeSelectedClip() {
  const ids = selectionList();
  if (ids.length !== 1) {
    $("status-msg").textContent = "Select 1 clip to describe";
    return;
  }
  try {
    const r = await getJson<Record<string, unknown>>(
      `/api/clip/${encodeURIComponent(ids[0])}/describe`,
    );
    const el = document.getElementById("review-out");
    if (el) {
      el.className = "review-out";
      el.textContent = JSON.stringify(r).slice(0, 500);
    }
    $("status-msg").textContent = `Described ${ids[0]}`;
  } catch (e) {
    $("status-msg").textContent = `Describe failed: ${e}`;
  }
}

async function exportWorkArea() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  if (!state.workIO.ready) {
    $("status-msg").textContent = "Set In and Out first (I / O)";
    return;
  }
  stopPlay();
  $("status-msg").textContent = "Exporting work area…";
  const btn = document.getElementById("btn-export-work") as HTMLButtonElement | null;
  if (btn) btn.disabled = true;
  try {
    const r = await postJson<{
      ok?: boolean;
      path?: string;
      error?: string;
      warning?: string;
    }>("/api/desktop/export_work", {});
    if (!r.ok) {
      $("status-msg").textContent = `Export work failed: ${r.error || "see log"}`;
    } else {
      $("status-msg").textContent = `Work export: ${r.path}${r.warning ? " (warn)" : ""}`;
    }
  } catch (e) {
    $("status-msg").textContent = `Export work failed: ${e}`;
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function linkSelection() {
  const ids = selectionList();
  if (ids.length < 2) {
    $("status-msg").textContent = "Select ≥2 clips to link";
    return;
  }
  try {
    const r = await postJson<{ timeline?: TimelineView }>("/api/clips/link", {
      clip_ids: ids,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    $("status-msg").textContent = `Linked ${ids.length} clips`;
  } catch (e) {
    $("status-msg").textContent = `Link failed: ${e}`;
  }
}

async function unlinkSelection() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clip(s) to unlink";
    return;
  }
  try {
    const r = await postJson<{ timeline?: TimelineView }>("/api/clips/unlink", {
      clip_ids: ids,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    $("status-msg").textContent = `Unlinked ${ids.length}`;
  } catch (e) {
    $("status-msg").textContent = `Unlink failed: ${e}`;
  }
}

async function redoEdit() {
  try {
    const r = await postJson<{ timeline?: TimelineView }>("/api/redo", {});
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    await refreshHistory();
    void seekTo(state.t);
    $("status-msg").textContent = "Redo";
  } catch (e) {
    $("status-msg").textContent = `Redo: ${e}`;
  }
}

async function loadPalette() {
  try {
    const r = await getJson<{ colors?: string[] }>("/api/clip/colors");
    state.palette = r.colors || [];
    renderPalette();
  } catch {
    state.palette = [
      "#3d5a80",
      "#2d6a4f",
      "#9b2226",
      "#bb3e03",
      "#0a9396",
      "#8338ec",
      "#ffb703",
      "#6c757d",
    ];
    renderPalette();
  }
}

function renderPalette() {
  const el = document.getElementById("color-palette");
  if (!el) return;
  el.innerHTML = "";
  for (const hex of state.palette) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "swatch";
    b.style.background = hex;
    b.title = hex;
    b.addEventListener("click", () => {
      void setSelectionColor(hex);
    });
    el.appendChild(b);
  }
}

async function setSelectionColor(color: string) {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clip(s) to color";
    return;
  }
  try {
    const r = await postJson<{ timeline?: TimelineView }>("/api/clips/color", {
      clip_ids: ids,
      color,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    $("status-msg").textContent = `Color ${color} → ${ids.length}`;
  } catch (e) {
    $("status-msg").textContent = `Color failed: ${e}`;
  }
}

async function cycleSelectionColor() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clip(s) to cycle color";
    return;
  }
  try {
    const r = await postJson<{ timeline?: TimelineView }>(
      "/api/clips/color_cycle",
      { clip_ids: ids },
    );
    if (r.timeline) applyTimelineView(r.timeline);
    $("status-msg").textContent = `Cycled color on ${ids.length}`;
  } catch (e) {
    $("status-msg").textContent = `Color cycle failed: ${e}`;
  }
}

async function setSelectionSpeed(speed: number) {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clip(s) for speed";
    return;
  }
  try {
    const r = await postJson<{ timeline?: TimelineView }>("/api/clips/speed", {
      clip_ids: ids,
      speed,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    $("status-msg").textContent = `Speed ${speed}x → ${ids.length}`;
    void seekTo(state.t);
  } catch (e) {
    $("status-msg").textContent = `Speed failed: ${e}`;
  }
}

async function refreshRecent() {
  const el = document.getElementById("recent-list");
  if (!el) return;
  try {
    const r = await getJson<{
      projects?: Array<{ path?: string; label?: string }>;
    }>("/api/recent?limit=8");
    const list = r.projects || [];
    if (!list.length) {
      el.className = "recent-list muted";
      el.textContent = "No recent projects";
      return;
    }
    el.className = "recent-list";
    el.innerHTML = "";
    for (const p of list) {
      const path = p.path || "";
      if (!path) continue;
      const row = document.createElement("div");
      row.className = "recent-row";
      row.textContent = p.label || path.split(/[/\\]/).pop() || path;
      row.title = path;
      row.addEventListener("click", () => {
        void openProjectAt(path);
      });
      el.appendChild(row);
    }
  } catch {
    el.className = "recent-list muted";
    el.textContent = "Recent list n/a";
  }
}

async function openProjectAt(path: string) {
  stopPlay();
  $("status-msg").textContent = `Opening ${path}…`;
  try {
    await postJson("/api/project/open", { bundle_path: path });
    $("status-msg").textContent = `Opened: ${path}`;
    state.t = 0;
    await refresh();
    await refreshRecent();
    void seekTo(0);
  } catch (e) {
    $("status-msg").textContent = `Open failed: ${e}`;
  }
}

async function renameSelection() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clip(s) to rename";
    return;
  }
  const current =
    document.querySelector<HTMLElement>(
      `.clip-block.selected[data-clip-id="${ids[0]}"]`,
    )?.dataset.label || "";
  const name = window.prompt("Clip name:", current);
  if (name == null) return;
  const trimmed = name.trim();
  try {
    const r = await postJson<{ timeline?: TimelineView }>("/api/clips/meta", {
      clip_ids: ids,
      name: trimmed || null,
      clear_name: !trimmed,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    $("status-msg").textContent = trimmed
      ? `Renamed ${ids.length} → ${trimmed}`
      : `Cleared name on ${ids.length}`;
  } catch (e) {
    $("status-msg").textContent = `Rename failed: ${e}`;
  }
}

async function setSelectionGain(db: number) {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clip(s) for gain";
    return;
  }
  try {
    const r = await postJson<{ timeline?: TimelineView }>("/api/clips/gain", {
      clip_ids: ids,
      db,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    $("status-msg").textContent = `Gain ${db} dB → ${ids.length}`;
  } catch (e) {
    $("status-msg").textContent = `Gain failed: ${e}`;
  }
}

async function setSelectionFades(fadeIn: number, fadeOut: number) {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clip(s) for fades";
    return;
  }
  try {
    const r = await postJson<{ timeline?: TimelineView }>("/api/clips/fades", {
      clip_ids: ids,
      fade_in_frames: fadeIn,
      fade_out_frames: fadeOut,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    $("status-msg").textContent = `Fades in=${fadeIn} out=${fadeOut} → ${ids.length}`;
  } catch (e) {
    $("status-msg").textContent = `Fades failed: ${e}`;
  }
}

async function setSelectionOpacity(amount: number) {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clip(s) for opacity";
    return;
  }
  try {
    const r = await postJson<{ timeline?: TimelineView }>(
      "/api/clips/opacity",
      { clip_ids: ids, amount },
    );
    if (r.timeline) applyTimelineView(r.timeline);
    $("status-msg").textContent = `Opacity ${amount} → ${ids.length}`;
  } catch (e) {
    $("status-msg").textContent = `Opacity failed: ${e}`;
  }
}

async function joinSelection() {
  const ids = selectionList();
  if (ids.length !== 2) {
    $("status-msg").textContent = "Select exactly 2 adjacent clips to join";
    return;
  }
  // order by start frame
  const infos = ids
    .map((id) => state.clips.get(id))
    .filter((c): c is ClipInfo => !!c)
    .sort((a, b) => a.start - b.start);
  if (infos.length !== 2) {
    $("status-msg").textContent = "Join needs two known clips";
    return;
  }
  try {
    const r = await postJson<{ timeline?: TimelineView }>("/api/clips/join", {
      clip_id_a: infos[0].id,
      clip_id_b: infos[1].id,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    state.selected.clear();
    updateSelectionCard();
    $("status-msg").textContent = `Joined ${infos[0].id} + ${infos[1].id}`;
  } catch (e) {
    $("status-msg").textContent = `Join failed: ${e}`;
  }
}

async function transitionSelection(durationFrames = 12) {
  const ids = selectionList();
  if (ids.length !== 2) {
    $("status-msg").textContent = "Select 2 clips (left→right) for transition";
    return;
  }
  const infos = ids
    .map((id) => state.clips.get(id))
    .filter((c): c is ClipInfo => !!c)
    .sort((a, b) => a.start - b.start);
  if (infos.length !== 2) {
    $("status-msg").textContent = "Transition needs two known clips";
    return;
  }
  try {
    const r = await postJson<{ timeline?: TimelineView }>("/api/transition", {
      left_clip_id: infos[0].id,
      right_clip_id: infos[1].id,
      transition_type: "cross_dissolve",
      duration_frames: durationFrames,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    $("status-msg").textContent = `Cross-dissolve ${durationFrames}f`;
  } catch (e) {
    $("status-msg").textContent = `Transition failed: ${e}`;
  }
}

async function refreshValidate() {
  const pill = document.getElementById("pill-validate");
  const list = document.getElementById("validate-list");
  if (!state.projectOpen) {
    if (pill) {
      pill.className = "pill";
      pill.textContent = "valid —";
    }
    if (list) {
      list.className = "validate-list muted";
      list.textContent = "No project";
    }
    return;
  }
  try {
    const r = await getJson<{
      ok?: boolean;
      error_count?: number;
      warn_count?: number;
      issue_count?: number;
      issues?: Array<{
        severity?: string;
        code?: string;
        message?: string;
        track_id?: string;
      }>;
    }>("/api/validate");
    const err = r.error_count ?? 0;
    const warn = r.warn_count ?? 0;
    if (pill) {
      if (!r.ok || err > 0) {
        pill.className = "pill err";
        pill.textContent = `valid ${err}e`;
      } else if (warn > 0) {
        pill.className = "pill warn";
        pill.textContent = `valid ${warn}w`;
      } else {
        pill.className = "pill ok";
        pill.textContent = "valid ok";
      }
    }
    if (list) {
      const issues = r.issues || [];
      if (!issues.length) {
        list.className = "validate-list muted";
        list.textContent = "No issues";
      } else {
        list.className = "validate-list";
        list.innerHTML = "";
        for (const it of issues.slice(0, 12)) {
          const row = document.createElement("div");
          row.className = `validate-row sev-${it.severity || "info"}`;
          row.textContent = `${it.severity || "info"}: ${it.message || it.code || "?"}`;
          list.appendChild(row);
        }
      }
    }
  } catch (e) {
    if (pill) {
      pill.className = "pill warn";
      pill.textContent = "valid n/a";
    }
    if (list) {
      list.className = "validate-list muted";
      list.textContent = String(e);
    }
  }
}

function applyNotesUi(notes: string, bundlePath?: string) {
  state.notes = notes || "";
  if (bundlePath) state.bundlePath = bundlePath;
  const ta = document.getElementById("notes-area") as HTMLTextAreaElement | null;
  if (ta && ta !== document.activeElement) ta.value = state.notes;
  const bp = document.getElementById("bundle-path");
  if (bp) {
    bp.textContent = state.bundlePath
      ? state.bundlePath.split(/[/\\]/).slice(-2).join("/")
      : "—";
    bp.title = state.bundlePath || "";
  }
}

async function saveNotes() {
  if (!state.projectOpen) return;
  const ta = document.getElementById("notes-area") as HTMLTextAreaElement | null;
  if (!ta) return;
  const notes = ta.value;
  try {
    await postJson("/api/notes", { notes });
    state.notes = notes;
    $("status-msg").textContent = "Notes saved";
  } catch (e) {
    $("status-msg").textContent = `Notes failed: ${e}`;
  }
}

function syncAutosaveUi(enabled: boolean) {
  state.autosave = !!enabled;
  const el = document.getElementById("chk-autosave") as HTMLInputElement | null;
  if (el && el !== document.activeElement) el.checked = state.autosave;
}

async function setAutosave(enabled: boolean) {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    const el = document.getElementById("chk-autosave") as HTMLInputElement | null;
    if (el) el.checked = state.autosave;
    return;
  }
  try {
    const r = await postJson<{ autosave?: boolean }>("/api/autosave", {
      enabled,
    });
    syncAutosaveUi(!!r.autosave);
    $("status-msg").textContent = state.autosave ? "Autosave on" : "Autosave off";
  } catch (e) {
    const el = document.getElementById("chk-autosave") as HTMLInputElement | null;
    if (el) el.checked = state.autosave;
    $("status-msg").textContent = `Autosave failed: ${e}`;
  }
}

/** NLE Q/W: trim selection head/tail to playhead. */
async function trimSelectionToPlayhead(edge: "head" | "tail") {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clip(s) for Q/W trim";
    return;
  }
  const ph = playheadFrame();
  const mode = rippleEnabled() ? "ripple" : "normal";
  $("status-msg").textContent = `Trim ${edge} @ f${ph} (${mode})…`;
  try {
    let last: TimelineView | undefined;
    for (const clipId of ids) {
      const r = await postJson<{ timeline?: TimelineView }>(
        "/api/clip/trim_playhead",
        {
          clip_id: clipId,
          playhead_frame: ph,
          edge,
          mode,
          follow_links: true,
        },
      );
      if (r.timeline) last = r.timeline;
    }
    if (last) applyTimelineView(last);
    else await refresh();
    $("status-msg").textContent = `Trim ${edge} @ f${ph} (${ids.length})`;
    void seekTo(state.t);
  } catch (e) {
    $("status-msg").textContent = `Trim ${edge} failed: ${e}`;
  }
}

async function workAreaFromSelection() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clip(s) for work area";
    return;
  }
  try {
    let io: WorkInOut;
    if (ids.length === 1) {
      io = await postJson<WorkInOut>("/api/work_area/from_clip", {
        clip_id: ids[0],
      });
    } else {
      io = await postJson<WorkInOut>("/api/work_area/from_selection", {
        clip_ids: ids,
      });
    }
    applyWorkIO(io);
    $("status-msg").textContent = `I/O from selection → f${io.in_frame ?? "—"}–${io.out_frame ?? "—"}`;
  } catch (e) {
    $("status-msg").textContent = `Work area failed: ${e}`;
  }
}

async function ensureProxy() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  stopPlay();
  $("status-msg").textContent = "Building preview proxy…";
  const btn = document.getElementById("btn-proxy") as HTMLButtonElement | null;
  if (btn) btn.disabled = true;
  try {
    const r = await postJson<{
      path?: string;
      fresh?: boolean;
      cache_hit?: boolean;
      height?: number;
      fps?: number;
    }>("/api/preview/ensure", { height: 360, fps: 12, force: false });
    state.proxyFresh = !!r.fresh || !!r.cache_hit;
    $("status-msg").textContent = r.cache_hit
      ? `Proxy cache hit (${r.height}p @ ${r.fps}fps)`
      : `Proxy ready: ${r.path || "ok"}`;
    await refresh();
    void seekTo(state.t);
  } catch (e) {
    $("status-msg").textContent = `Proxy failed: ${e}`;
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function clearSelectionEffects() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clip(s) to clear effects";
    return;
  }
  try {
    let last: TimelineView | undefined;
    for (const clipId of ids) {
      const r = await postJson<{ timeline?: TimelineView }>(
        "/api/clip/clear_effects",
        { clip_id: clipId },
      );
      if (r.timeline) last = r.timeline;
    }
    if (last) applyTimelineView(last);
    $("status-msg").textContent = `Cleared effects on ${ids.length}`;
  } catch (e) {
    $("status-msg").textContent = `Clear effects failed: ${e}`;
  }
}

function syncHistoryUi(opts?: {
  can_undo?: boolean;
  can_redo?: boolean;
  undo_depth?: number;
  redo_depth?: number;
}) {
  if (typeof opts?.can_undo === "boolean") state.canUndo = opts.can_undo;
  if (typeof opts?.can_redo === "boolean") state.canRedo = opts.can_redo;
  if (typeof opts?.undo_depth === "number") state.undoDepth = opts.undo_depth;
  if (typeof opts?.redo_depth === "number") state.redoDepth = opts.redo_depth;
  const u = document.getElementById("btn-undo") as HTMLButtonElement | null;
  const r = document.getElementById("btn-redo") as HTMLButtonElement | null;
  if (u) {
    u.disabled = !state.canUndo;
    u.title = `Undo (Ctrl+Z)${state.undoDepth ? ` · ${state.undoDepth}` : ""}`;
  }
  if (r) {
    r.disabled = !state.canRedo;
    r.title = `Redo (Ctrl+Y)${state.redoDepth ? ` · ${state.redoDepth}` : ""}`;
  }
  const pill = document.getElementById("pill-history");
  if (pill) {
    pill.textContent = `↕ ${state.undoDepth}/${state.redoDepth}`;
    pill.className = `pill ${state.canUndo || state.canRedo ? "ok" : ""}`;
    pill.title = `undo ${state.undoDepth} · redo ${state.redoDepth}`;
  }
}

async function refreshHistory() {
  if (!state.projectOpen) {
    syncHistoryUi({
      can_undo: false,
      can_redo: false,
      undo_depth: 0,
      redo_depth: 0,
    });
    return;
  }
  try {
    const h = await getJson<{
      can_undo?: boolean;
      can_redo?: boolean;
      undo_depth?: number;
      redo_depth?: number;
    }>("/api/history");
    syncHistoryUi(h);
  } catch {
    /* keep last */
  }
}

async function refreshDurationReport() {
  const el = document.getElementById("duration-report");
  if (!el) return;
  if (!state.projectOpen) {
    el.className = "duration-report muted";
    el.textContent = "—";
    return;
  }
  try {
    const r = await getJson<{
      duration_seconds?: number;
      duration_frames?: number;
      track_count?: number;
      media_count?: number;
      marker_count?: number;
    }>("/api/duration_report");
    el.className = "duration-report";
    el.innerHTML = [
      `<div>${(r.duration_seconds ?? 0).toFixed(2)}s · ${r.duration_frames ?? 0}f</div>`,
      `<div class="kv">${r.track_count ?? 0} tracks · ${r.media_count ?? 0} media · ${r.marker_count ?? 0} mk</div>`,
    ].join("");
  } catch {
    el.className = "duration-report muted";
    el.textContent = "report n/a";
  }
}

async function selectAtPlayhead() {
  if (!state.projectOpen) return;
  const frame = playheadFrame();
  try {
    const r = await postJson<{
      hits?: Array<{ clip_id: string; track_id?: string }>;
      count?: number;
    }>("/api/clips/at", { timeline_frame: frame });
    const hits = r.hits || [];
    if (!hits.length) {
      setSelection([]);
      $("status-msg").textContent = `No clip @ f${frame}`;
      return;
    }
    setSelection(hits.map((h) => h.clip_id));
    $("status-msg").textContent = `Selected ${hits.length} @ f${frame}`;
  } catch (e) {
    $("status-msg").textContent = `Select@playhead failed: ${e}`;
  }
}

async function matchFrameAtPlayhead() {
  if (!state.projectOpen) return;
  const frame = playheadFrame();
  const ids = selectionList();
  const body: { timeline_frame: number; clip_id?: string } = {
    timeline_frame: frame,
  };
  if (ids.length === 1) body.clip_id = ids[0];
  try {
    const r = await postJson<{
      clip_id?: string;
      src_frame?: number;
      src_time_seconds?: number;
      path?: string;
      media_id?: string;
      start?: number;
      end?: number;
    }>("/api/clip/match_frame", body);
    if (r.clip_id) setSelection([r.clip_id]);
    const el = document.getElementById("match-frame-info");
    if (el) {
      el.className = "match-frame-info";
      el.innerHTML = [
        `<div class="sel-title">Match frame</div>`,
        `<div class="kv">tl f${frame} → src f${r.src_frame ?? "—"} (${(r.src_time_seconds ?? 0).toFixed(3)}s)</div>`,
        `<div class="kv">${escapeHtml(String(r.path || r.media_id || r.clip_id || ""))}</div>`,
      ].join("");
    }
    $("status-msg").textContent = `Match: src f${r.src_frame ?? "—"} · ${r.path || r.clip_id || ""}`;
  } catch (e) {
    $("status-msg").textContent = `Match frame failed: ${e}`;
  }
}

async function subclipSelection() {
  const ids = selectionList();
  if (ids.length !== 1) {
    $("status-msg").textContent = "Select one clip for subclip";
    return;
  }
  const clipId = ids[0];
  const useIO = !!state.workIO.ready;
  $("status-msg").textContent = useIO
    ? "Subclip from work area…"
    : "Subclip (middle half)…";
  try {
    const payload: Record<string, unknown> = {
      clip_id: clipId,
      place: "after",
      name: "subclip",
    };
    if (useIO) {
      payload.use_work_area = true;
    } else {
      const c = state.clips.get(clipId);
      if (!c) throw new Error("clip not found");
      const a = c.start + Math.floor(c.dur * 0.25);
      const b = c.start + Math.floor(c.dur * 0.75);
      if (b <= a + 1) throw new Error("clip too short for auto subclip");
      payload.timeline_start = a;
      payload.timeline_end = b;
    }
    const r = await postJson<{ timeline?: TimelineView; clip_id?: string }>(
      "/api/clip/subclip",
      payload,
    );
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    if (r.clip_id) setSelection([r.clip_id]);
    $("status-msg").textContent = `Subclip ${r.clip_id || "ok"}`;
  } catch (e) {
    $("status-msg").textContent = `Subclip failed: ${e}`;
  }
}

async function markersFromCuts() {
  if (!state.projectOpen) return;
  // prefer first video track with clips
  const tid =
    state.tracks.find((t) => t.kind === "video")?.id || state.tracks[0]?.id;
  if (!tid) {
    $("status-msg").textContent = "No track for cut markers";
    return;
  }
  try {
    const r = await postJson<{ count?: number; markers?: Marker[] }>(
      "/api/markers/from_cuts",
      { track_id: tid, label_prefix: "Cut", color: "#ffb703" },
    );
    await refreshMarkers();
    $("status-msg").textContent = `Cut markers: +${r.count ?? 0}`;
  } catch (e) {
    $("status-msg").textContent = `Cut markers failed: ${e}`;
  }
}

async function clearAllMarkers() {
  if (!state.projectOpen) return;
  try {
    await postJson("/api/markers/clear", {});
    state.markers = [];
    renderMarkerList();
    const ruler = document.querySelector(".marker-ruler") as HTMLElement | null;
    if (ruler) paintMarkerRuler(ruler);
    $("status-msg").textContent = "Markers cleared";
  } catch (e) {
    $("status-msg").textContent = `Clear markers failed: ${e}`;
  }
}

async function closeGapsOnTracks() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  $("status-msg").textContent = "Closing gaps…";
  try {
    // close on every video/audio track that has clips
    let last: TimelineView | undefined;
    const tids = state.tracks.map((t) => t.id);
    if (!tids.length) {
      const r = await postJson<{ timeline?: TimelineView }>("/api/close_gaps", {
        track_id: null,
        from_frame: 0,
      });
      last = r.timeline;
    } else {
      for (const trackId of tids) {
        const r = await postJson<{ timeline?: TimelineView }>("/api/close_gaps", {
          track_id: trackId,
          from_frame: 0,
        });
        if (r.timeline) last = r.timeline;
      }
    }
    if (last) applyTimelineView(last);
    else await refresh();
    $("status-msg").textContent = "Gaps closed";
    void seekTo(state.t);
  } catch (e) {
    $("status-msg").textContent = `Close gaps failed: ${e}`;
  }
}

async function liftWorkArea(ripple: boolean) {
  if (!state.projectOpen) return;
  if (!state.workIO.ready) {
    $("status-msg").textContent = "Set In and Out first (I / O)";
    return;
  }
  const start = state.workIO.in_frame!;
  const end = state.workIO.out_frame!;
  const path = ripple ? "/api/extract_range" : "/api/lift";
  $("status-msg").textContent = ripple
    ? `Extract [${start},${end})…`
    : `Lift [${start},${end})…`;
  try {
    const r = await postJson<{ timeline?: TimelineView }>(path, {
      start_frame: start,
      end_frame: end,
      ripple: true,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    $("status-msg").textContent = ripple
      ? `Extracted [${start},${end})`
      : `Lifted [${start},${end})`;
    void seekTo(state.t);
  } catch (e) {
    $("status-msg").textContent = `${ripple ? "Extract" : "Lift"} failed: ${e}`;
  }
}

function setZoom(z: number) {
  state.zoom = Math.max(0.5, Math.min(8, Math.round(z * 100) / 100));
  const el = document.getElementById("zoom-label");
  if (el) el.textContent = `${state.zoom.toFixed(1)}×`;
  applyZoomToLanes();
}

function applyZoomToLanes() {
  const pct = `${100 * state.zoom}%`;
  document.querySelectorAll<HTMLElement>(".track-lane").forEach((lane) => {
    lane.style.width = pct;
    lane.style.minWidth = pct;
  });
  document.querySelectorAll<HTMLElement>(".marker-ruler").forEach((r) => {
    r.style.width = pct;
    r.style.minWidth = pct;
  });
}

function toggleHelp() {
  const el = document.getElementById("help-overlay");
  if (!el) return;
  const open = el.classList.toggle("open");
  el.setAttribute("aria-hidden", open ? "false" : "true");
}

async function edgeTrim(
  clipId: string,
  edge: "left" | "right",
  deltaFrames: number,
) {
  if (deltaFrames === 0) return;
  const mode = rippleEnabled() ? "ripple" : "normal";
  $("status-msg").textContent = `Trim ${edge} ${clipId} Δ${deltaFrames} (${mode})…`;
  try {
    const r = await postJson<{ timeline?: TimelineView }>("/api/clip/edge_trim", {
      clip_id: clipId,
      edge,
      delta_frames: deltaFrames,
      mode,
      refresh_preview: true,
      quick_preview: true,
    });
    if (r.timeline) {
      applyTimelineView(r.timeline);
      state.proxyFresh = !!r.timeline.proxy?.fresh;
    }
    $("status-msg").textContent = `Trimmed ${edge} Δ${deltaFrames} (${mode})`;
    void seekTo(state.t);
  } catch (e) {
    $("status-msg").textContent = `Trim failed: ${e}`;
    await refresh();
  }
}

async function moveClipToTrack(
  clipId: string,
  trackId: string,
  start: number | null,
) {
  $("status-msg").textContent = `Reparent ${clipId} → ${trackId}…`;
  try {
    const r = await postJson<{ timeline?: TimelineView }>(
      "/api/clip/move_to_track",
      {
        clip_id: clipId,
        track_id: trackId,
        start,
      },
    );
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    $("status-msg").textContent = `Moved to track ${trackId}`;
    void seekTo(state.t);
  } catch (e) {
    $("status-msg").textContent = `Cross-track failed: ${e}`;
    await refresh();
  }
}

async function undoEdit() {
  try {
    const r = await postJson<{ timeline?: TimelineView }>("/api/undo", {});
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    await refreshHistory();
    void seekTo(state.t);
    $("status-msg").textContent = "Undo";
  } catch (e) {
    $("status-msg").textContent = `Undo: ${e}`;
  }
}

function trackIdAtClientY(y: number): string | null {
  const lanes = document.querySelectorAll<HTMLElement>(".track-lane[data-track-id]");
  for (const lane of lanes) {
    const r = lane.getBoundingClientRect();
    if (y >= r.top && y <= r.bottom) {
      return lane.dataset.trackId || null;
    }
  }
  return null;
}

function bindClipInteractions(
  block: HTMLElement,
  c: {
    id: string;
    start: number;
    dur: number;
    trackId: string;
    linkGroup?: string | null;
    color?: string | null;
    speed?: number;
  },
  lane: HTMLElement,
  durF: number,
) {
  const begin = (
    ev: PointerEvent,
    mode: "move" | "trim-left" | "trim-right",
  ) => {
    if (ev.button !== 0) return;
    ev.preventDefault();
    ev.stopPropagation();
    stopPlay();
    const laneRect = lane.getBoundingClientRect();
    state.drag = {
      mode,
      clipId: c.id,
      trackId: c.trackId,
      startFrame: c.start,
      durationFrames: c.dur,
      originX: ev.clientX,
      originY: ev.clientY,
      laneWidth: Math.max(1, laneRect.width),
      block,
      pendingStart: c.start,
      pendingDelta: 0,
      pendingTrackId: c.trackId,
    };
    block.classList.add("dragging");
    (ev.target as HTMLElement).setPointerCapture?.(ev.pointerId);
    block.setPointerCapture(ev.pointerId);
  };

  const onMove = (ev: PointerEvent) => {
    const d = state.drag;
    if (!d || d.clipId !== c.id) return;
    const dx = ev.clientX - d.originX;
    const dFrames = Math.round((dx / d.laneWidth) * durF);
    if (d.mode === "move") {
      const raw = Math.max(0, d.startFrame + dFrames);
      const exclude = new Set([
        d.startFrame,
        d.startFrame + d.durationFrames,
      ]);
      const newStart = snapMoveStart(raw, d.durationFrames, exclude);
      d.pendingStart = newStart;
      d.pendingDelta = newStart - d.startFrame;
      block.style.left = `${(newStart / durF) * 100}%`;
      block.classList.toggle("snapped", newStart !== raw && snapEnabled());
      const over = trackIdAtClientY(ev.clientY);
      if (over) d.pendingTrackId = over;
      block.classList.toggle("cross-track", d.pendingTrackId !== d.trackId);
    } else if (d.mode === "trim-left") {
      // positive delta = head later (shorter) when dragging right
      let visualStart = Math.max(0, d.startFrame + dFrames);
      const rightEdge = d.startFrame + d.durationFrames;
      visualStart = Math.min(visualStart, rightEdge - 1);
      const snapped = snapFrame(visualStart, new Set([rightEdge]));
      visualStart = Math.max(0, Math.min(snapped, rightEdge - 1));
      d.pendingDelta = visualStart - d.startFrame;
      const visualDur = Math.max(1, d.durationFrames - d.pendingDelta);
      block.style.left = `${(visualStart / durF) * 100}%`;
      block.style.width = `${(visualDur / durF) * 100}%`;
      block.classList.toggle("snapped", snapped !== d.startFrame + dFrames && snapEnabled());
    } else {
      // trim-right: drag right → longer (positive delta)
      let right = d.startFrame + d.durationFrames + dFrames;
      right = Math.max(d.startFrame + 1, right);
      const snapped = snapFrame(right, new Set([d.startFrame]));
      right = Math.max(d.startFrame + 1, snapped);
      d.pendingDelta = right - (d.startFrame + d.durationFrames);
      const visualDur = Math.max(1, d.durationFrames + d.pendingDelta);
      block.style.width = `${(visualDur / durF) * 100}%`;
      block.classList.toggle(
        "snapped",
        snapped !== d.startFrame + d.durationFrames + dFrames && snapEnabled(),
      );
    }
  };

  const onUp = async (ev: PointerEvent) => {
    const d = state.drag;
    if (!d || d.clipId !== c.id) return;
    block.classList.remove("dragging", "cross-track", "snapped");
    const mode = d.mode;
    const pendingStart = d.pendingStart;
    const pendingDelta = d.pendingDelta;
    const pendingTrack = d.pendingTrackId;
    const origTrack = d.trackId;
    const origStart = d.startFrame;
    state.drag = null;
    try {
      block.releasePointerCapture(ev.pointerId);
    } catch {
      /* ignore */
    }
    // Click without movement → selection (shift toggles)
    if (mode === "move" && pendingDelta === 0 && pendingStart === origStart) {
      setSelection([c.id], { additive: ev.shiftKey });
      return;
    }
    if (mode === "move") {
      const multi =
        state.selected.size > 1 && state.selected.has(c.id) && pendingTrack === origTrack;
      if (multi) {
        await nudgeSelection(pendingDelta);
      } else if (pendingTrack !== origTrack) {
        setSelection([c.id]);
        await moveClipToTrack(c.id, pendingTrack, pendingStart);
      } else if (pendingStart !== origStart) {
        setSelection([c.id]);
        await moveClip(c.id, pendingStart);
      } else {
        block.style.left = `${(origStart / durF) * 100}%`;
      }
    } else if (pendingDelta !== 0) {
      setSelection([c.id]);
      await edgeTrim(c.id, mode === "trim-left" ? "left" : "right", pendingDelta);
    } else {
      block.style.left = `${(origStart / durF) * 100}%`;
      block.style.width = `${(c.dur / durF) * 100}%`;
    }
  };

  const onCancel = () => {
    block.classList.remove("dragging", "cross-track", "snapped");
    state.drag = null;
    block.style.left = `${(c.start / durF) * 100}%`;
    block.style.width = `${(c.dur / durF) * 100}%`;
  };

  const leftH = document.createElement("div");
  leftH.className = "clip-handle left";
  leftH.title = "Trim in";
  const rightH = document.createElement("div");
  rightH.className = "clip-handle right";
  rightH.title = "Trim out";
  const label = document.createElement("span");
  label.className = "clip-label";
  label.textContent = block.dataset.label || c.id;

  leftH.addEventListener("pointerdown", (ev) => begin(ev, "trim-left"));
  rightH.addEventListener("pointerdown", (ev) => begin(ev, "trim-right"));
  block.addEventListener("pointerdown", (ev) => {
    if ((ev.target as HTMLElement).classList.contains("clip-handle")) return;
    begin(ev, "move");
  });
  block.addEventListener("pointermove", onMove);
  block.addEventListener("pointerup", (ev) => {
    void onUp(ev);
  });
  block.addEventListener("pointercancel", onCancel);

  block.dataset.clipId = c.id;
  if (c.color) {
    block.style.background = c.color;
  }
  if (c.linkGroup) {
    block.dataset.link = c.linkGroup;
    block.classList.add("linked");
  }
  if (state.selected.has(c.id)) block.classList.add("selected");
  block.appendChild(leftH);
  block.appendChild(label);
  if (c.speed != null && c.speed !== 1) {
    const sp = document.createElement("span");
    sp.className = "speed-badge";
    sp.textContent = `${c.speed}x`;
    sp.title = `speed ${c.speed}`;
    block.appendChild(sp);
  }
  if (c.linkGroup) {
    const badge = document.createElement("span");
    badge.className = "link-badge";
    badge.textContent = "🔗";
    badge.title = `link ${c.linkGroup}`;
    block.appendChild(badge);
  }
  block.appendChild(rightH);
}

function renderTimeline(view: TimelineView | null) {
  const body = $("timeline-body");
  const meta = $("timeline-meta");
  if (!view || !view.tracks?.length) {
    body.textContent =
      "No timeline yet. Use Demo project or open via core API.";
    meta.textContent = "empty";
    state.tracks = [];
    state.trackOrder = [];
    state.clips.clear();
    updateSelectionCard();
    return;
  }
  const durF = Math.max(1, view.duration_frames || 1);
  state.durationFrames = durF;
  state.durationSec = view.duration_seconds || durF / (view.fps || state.fps);
  state.fps = view.fps || state.fps || 30;
  if (view.proxy) state.proxyFresh = !!view.proxy.fresh;
  state.trackOrder = view.tracks.map((t) => t.id);
  state.tracks = view.tracks.map((t) => ({ id: t.id, kind: t.kind }));
  state.clips.clear();
  for (const tr of view.tracks) {
    for (const c of tr.clips || []) {
      const start = c.start_frame ?? c.start ?? 0;
      const dur = c.duration_frames ?? 1;
      state.clips.set(c.id, {
        id: c.id,
        trackId: tr.id,
        start,
        dur,
        label: c.label,
        name: c.name,
        color: c.color,
        speed: c.speed,
        gain_db: c.gain_db,
        opacity: c.opacity,
        muted: c.muted,
        link_group: c.link_group,
        fade_in_frames: c.fade_in_frames,
        fade_out_frames: c.fade_out_frames,
      });
    }
  }
  state.snapFrames = view.snap_frames || [];
  if (view.markers) {
    state.markers = view.markers;
    renderMarkerList();
  }
  if (view.work_in_out) applyWorkIO(view.work_in_out);
  applyNotesUi(view.notes || "", view.bundle_path);
  if (typeof view.autosave === "boolean") syncAutosaveUi(view.autosave);
  state.dirty = !!view.dirty;
  if (typeof view.can_undo === "boolean" || typeof view.can_redo === "boolean") {
    syncHistoryUi({
      can_undo: view.can_undo,
      can_redo: view.can_redo,
    });
  }
  const dirty = state.dirty ? " · dirty" : "";
  meta.textContent = `${view.tracks.length} tracks · ${state.durationSec.toFixed(2)}s · snap±${state.snapThr}f${dirty}`;
  const dirtyPill = document.getElementById("pill-dirty");
  if (dirtyPill) {
    dirtyPill.className = `pill ${state.dirty ? "warn" : "ok"}`;
    dirtyPill.textContent = state.dirty ? "dirty" : "clean";
  }
  body.innerHTML = "";

  // marker ruler
  const rulerRow = document.createElement("div");
  rulerRow.className = "track-row marker-ruler-row";
  const rulerLab = document.createElement("div");
  rulerLab.className = "track-label muted";
  rulerLab.textContent = "Mk";
  const ruler = document.createElement("div");
  ruler.className = "marker-ruler";
  paintMarkerRuler(ruler);
  rulerRow.appendChild(rulerLab);
  rulerRow.appendChild(ruler);
  body.appendChild(rulerRow);

  for (const tr of view.tracks) {
    const row = document.createElement("div");
    row.className = "track-row";
    if (tr.muted) row.classList.add("track-muted");
    if (tr.solo) row.classList.add("track-solo");
    if (tr.locked) row.classList.add("track-locked");
    const label = document.createElement("div");
    label.className = "track-label";
    const name = document.createElement("div");
    name.className = "track-name";
    name.textContent = tr.name || tr.kind || tr.id;
    const flags = document.createElement("div");
    flags.className = "track-flags";
    const mkBtn = (txt: string, on: boolean, title: string, fn: () => void) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = `tflag${on ? " on" : ""}`;
      b.textContent = txt;
      b.title = title;
      b.addEventListener("click", (ev) => {
        ev.stopPropagation();
        fn();
      });
      return b;
    };
    flags.appendChild(
      mkBtn("M", !!tr.muted, "Mute track", () => {
        void setTrackFlag(tr.id, "mute", !tr.muted);
      }),
    );
    flags.appendChild(
      mkBtn("S", !!tr.solo, "Solo track", () => {
        void setTrackFlag(tr.id, "solo", !tr.solo);
      }),
    );
    flags.appendChild(
      mkBtn("L", !!tr.locked, "Lock track", () => {
        void setTrackFlag(tr.id, "lock", !tr.locked);
      }),
    );
    label.appendChild(name);
    label.appendChild(flags);
    const lane = document.createElement("div");
    lane.className = "track-lane";
    lane.dataset.trackId = tr.id;
    lane.dataset.trackKind = tr.kind;
    const ph = document.createElement("div");
    ph.className = "timeline-playhead";
    lane.appendChild(ph);
    for (const c of tr.clips || []) {
      const start = c.start_frame ?? c.start ?? 0;
      const dur = c.duration_frames ?? 1;
      const left = (start / durF) * 100;
      const width = Math.max(0.5, (dur / durF) * 100);
      const block = document.createElement("div");
      block.className = `clip-block${tr.kind === "audio" ? " audio" : ""}${c.muted ? " muted" : ""}`;
      block.style.left = `${left}%`;
      block.style.width = `${width}%`;
      block.dataset.label = c.label || c.name || c.id;
      block.title = `${c.id}${c.muted ? " [muted]" : ""}${c.link_group ? " [linked]" : ""} · drag · edges · Shift+M mute`;
      bindClipInteractions(
        block,
        {
          id: c.id,
          start,
          dur,
          trackId: tr.id,
          linkGroup: c.link_group,
          color: c.color,
          speed: c.speed,
        },
        lane,
        durF,
      );
      lane.appendChild(block);
    }
    lane.addEventListener("click", (ev) => {
      if (state.drag) return;
      if ((ev.target as HTMLElement).closest(".clip-block")) return;
      stopPlay();
      if (!ev.shiftKey) setSelection([]);
      const rect = lane.getBoundingClientRect();
      const x = (ev.clientX - rect.left) / Math.max(1, rect.width);
      void seekTo(x * state.durationSec);
    });
    row.appendChild(label);
    row.appendChild(lane);
    body.appendChild(row);
  }
  applyZoomToLanes();
  setPlayheadUi();
  $("sel-count").textContent = String(state.selected.size);
  updateSelectionCard();
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

function promptPath(message: string, fallback = ""): string | null {
  const raw = window.prompt(message, fallback);
  if (raw == null) return null;
  const p = raw.trim().replace(/^["']|["']$/g, "");
  return p || null;
}

function isTauri(): boolean {
  return typeof window !== "undefined" && !!(window as unknown as { __TAURI__?: unknown }).__TAURI__;
}

/** Native folder picker when running under Tauri; else window.prompt. */
async function pickProjectFolder(opts: {
  title: string;
  defaultPath?: string;
}): Promise<string | null> {
  if (isTauri()) {
    try {
      const { open } = await import("@tauri-apps/plugin-dialog");
      const selected = await open({
        directory: true,
        multiple: false,
        title: opts.title,
        defaultPath: opts.defaultPath,
      });
      if (selected == null) return null;
      const path = Array.isArray(selected) ? selected[0] : selected;
      return path ? String(path) : null;
    } catch (e) {
      console.warn("Tauri dialog open failed, falling back to prompt", e);
    }
  }
  return promptPath(opts.title, opts.defaultPath || "");
}

/** Save-as path for new .opm bundle (folder name). */
async function pickNewProjectPath(opts: {
  title: string;
  defaultPath?: string;
}): Promise<string | null> {
  if (isTauri()) {
    try {
      const { save } = await import("@tauri-apps/plugin-dialog");
      const path = await save({
        title: opts.title,
        defaultPath: opts.defaultPath || "project.opm",
        filters: [{ name: "Opmiere project", extensions: ["opm"] }],
      });
      return path ? String(path) : null;
    } catch (e) {
      console.warn("Tauri dialog save failed, falling back to prompt", e);
    }
  }
  return promptPath(opts.title, opts.defaultPath || "G:\\tmp\\opmiere_new.opm");
}

async function openProjectPath() {
  stopPlay();
  const path = await pickProjectFolder({
    title: "Open Opmiere project folder (.opm)",
  });
  if (!path) return;
  await openProjectAt(path);
}

async function newProjectPath() {
  stopPlay();
  const path = await pickNewProjectPath({
    title: "Create new Opmiere project",
    defaultPath: "opmiere_new.opm",
  });
  if (!path) return;
  $("status-msg").textContent = `Creating ${path}…`;
  try {
    await postJson("/api/project/create", {
      bundle_path: path,
      fps: 30,
      width: 1920,
      height: 1080,
    });
    // empty project has no tracks — seed V1 + A1 for editing
    await fetch(`${API_BASE}/api/track?kind=video`, { method: "POST" });
    await fetch(`${API_BASE}/api/track?kind=audio`, { method: "POST" });
    $("status-msg").textContent = `Created: ${path}`;
    state.t = 0;
    await refresh();
    await refreshRecent();
  } catch (e) {
    $("status-msg").textContent = `Create failed: ${e}`;
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
        applyTimelineView(tl);
        if (state.durationSec > 0) {
          await seekTo(Math.min(state.t, state.durationSec));
        }
      } catch (e) {
        renderTimeline(null);
        $("timeline-body").textContent = String(e);
      }
      await refreshMediaBin();
      await refreshMarkers();
      await refreshValidate();
      await refreshHistory();
      await refreshDurationReport();
      await refreshProjectStats();
    } else {
      state.durationSec = 0;
      state.durationFrames = 0;
      state.markers = [];
      state.notes = "";
      state.bundlePath = "";
      renderTimeline(null);
      hideAllProgramSurfaces();
      setPlayheadUi();
      renderMediaBin(null);
      renderMarkerList();
      applyNotesUi("");
      await refreshValidate();
      await refreshHistory();
      await refreshDurationReport();
      await refreshProjectStats();
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
  if (k === "j" && !ev.ctrlKey && !ev.metaKey) {
    ev.preventDefault();
    stopPlay();
    void seekTo(state.t - 5 / state.fps);
    return;
  }
  if (k === "l" && !ev.ctrlKey && !ev.metaKey) {
    ev.preventDefault();
    stopPlay();
    void seekTo(state.t + 5 / state.fps);
    return;
  }
  if (ev.key === "ArrowLeft") {
    ev.preventDefault();
    stopPlay();
    if (ev.shiftKey) goToMarker(-1);
    else void seekTo(state.t - 1 / state.fps);
    return;
  }
  if (ev.key === "ArrowRight") {
    ev.preventDefault();
    stopPlay();
    if (ev.shiftKey) goToMarker(1);
    else void seekTo(state.t + 1 / state.fps);
    return;
  }
  if (ev.key === "Home") {
    ev.preventDefault();
    stopPlay();
    void seekTo(0);
    return;
  }
  if (ev.key === "End") {
    ev.preventDefault();
    stopPlay();
    void seekTo(Math.max(0, state.durationSec - 1 / state.fps));
    return;
  }
  if (ev.key === "ArrowUp") {
    ev.preventDefault();
    goToEditPoint(-1);
    return;
  }
  if (ev.key === "ArrowDown") {
    ev.preventDefault();
    goToEditPoint(1);
    return;
  }
  if (k === ";" && !ev.ctrlKey && !ev.metaKey) {
    ev.preventDefault();
    goToEditPoint(-1);
    return;
  }
  if (k === "'" && !ev.ctrlKey && !ev.metaKey) {
    ev.preventDefault();
    goToEditPoint(1);
    return;
  }
  if ((ev.ctrlKey || ev.metaKey) && k === "z") {
    ev.preventDefault();
    stopPlay();
    if (ev.shiftKey) void redoEdit();
    else void undoEdit();
    return;
  }
  if ((ev.ctrlKey || ev.metaKey) && k === "y") {
    ev.preventDefault();
    stopPlay();
    void redoEdit();
    return;
  }
  if ((ev.ctrlKey || ev.metaKey) && k === "l") {
    ev.preventDefault();
    stopPlay();
    if (ev.shiftKey) void unlinkSelection();
    else void linkSelection();
    return;
  }
  if ((ev.ctrlKey || ev.metaKey) && k === "s") {
    ev.preventDefault();
    void saveProject();
    return;
  }
  if ((ev.ctrlKey || ev.metaKey) && k === "o") {
    ev.preventDefault();
    void openProjectPath();
    return;
  }
  if ((ev.ctrlKey || ev.metaKey) && k === "n") {
    ev.preventDefault();
    void newProjectPath();
    return;
  }
  if ((ev.ctrlKey || ev.metaKey) && k === "c") {
    ev.preventDefault();
    void copySelection();
    return;
  }
  if ((ev.ctrlKey || ev.metaKey) && k === "v") {
    ev.preventDefault();
    stopPlay();
    void pasteAtPlayhead();
    return;
  }
  if ((ev.ctrlKey || ev.metaKey) && k === "d") {
    ev.preventDefault();
    stopPlay();
    void duplicateSelection();
    return;
  }
  if (k === "s" && !ev.ctrlKey && !ev.metaKey && !ev.altKey) {
    ev.preventDefault();
    stopPlay();
    void razorAtPlayhead();
    return;
  }
  if (k === "m" && !ev.ctrlKey && !ev.metaKey && !ev.altKey && ev.shiftKey) {
    ev.preventDefault();
    stopPlay();
    void muteSelection();
    return;
  }
  if (k === "m" && !ev.ctrlKey && !ev.metaKey && !ev.altKey && !ev.shiftKey) {
    ev.preventDefault();
    stopPlay();
    void addMarkerAtPlayhead();
    return;
  }
  if (k === "i" && !ev.ctrlKey && !ev.metaKey && !ev.altKey) {
    ev.preventDefault();
    if (ev.shiftKey) goToInOut("in");
    else void setInPoint();
    return;
  }
  if (k === "o" && !ev.ctrlKey && !ev.metaKey && !ev.altKey) {
    ev.preventDefault();
    if (ev.shiftKey) goToInOut("out");
    else void setOutPoint();
    return;
  }
  if (k === "x" && !ev.ctrlKey && !ev.metaKey && !ev.altKey && !ev.shiftKey) {
    ev.preventDefault();
    void clearInOut();
    return;
  }
  if (k === "c" && !ev.ctrlKey && !ev.metaKey && !ev.altKey && !ev.shiftKey) {
    ev.preventDefault();
    void cycleSelectionColor();
    return;
  }
  if (k === "r" && !ev.ctrlKey && !ev.metaKey && !ev.altKey && !ev.shiftKey) {
    ev.preventDefault();
    void renameSelection();
    return;
  }
  if (k === "q" && !ev.ctrlKey && !ev.metaKey && !ev.altKey) {
    ev.preventDefault();
    stopPlay();
    void trimSelectionToPlayhead("head");
    return;
  }
  if (k === "w" && !ev.ctrlKey && !ev.metaKey && !ev.altKey) {
    ev.preventDefault();
    stopPlay();
    void trimSelectionToPlayhead("tail");
    return;
  }
  if (k === "d" && !ev.ctrlKey && !ev.metaKey && !ev.altKey && !ev.shiftKey) {
    // plain D: select under playhead (Ctrl+D remains duplicate)
    ev.preventDefault();
    void selectAtPlayhead();
    return;
  }
  if (k === "f" && !ev.ctrlKey && !ev.metaKey && !ev.altKey && !ev.shiftKey) {
    ev.preventDefault();
    void matchFrameAtPlayhead();
    return;
  }
  if (k === "u" && !ev.ctrlKey && !ev.metaKey && !ev.altKey && !ev.shiftKey) {
    ev.preventDefault();
    stopPlay();
    void subclipSelection();
    return;
  }
  if (k === "g" && !ev.ctrlKey && !ev.metaKey && !ev.altKey && !ev.shiftKey) {
    ev.preventDefault();
    stopPlay();
    void closeGapsOnTracks();
    return;
  }
  if ((k === "=" || k === "+") && !ev.ctrlKey && !ev.metaKey) {
    ev.preventDefault();
    setZoom(state.zoom * 1.25);
    return;
  }
  if (k === "-" && !ev.ctrlKey && !ev.metaKey) {
    ev.preventDefault();
    setZoom(state.zoom / 1.25);
    return;
  }
  if (k === "0" && !ev.ctrlKey && !ev.metaKey && !ev.altKey) {
    ev.preventDefault();
    setZoom(1);
    return;
  }
  if (k === "?" || (ev.shiftKey && k === "/")) {
    ev.preventDefault();
    toggleHelp();
    return;
  }
  if (ev.key === "Delete" || ev.key === "Backspace") {
    ev.preventDefault();
    stopPlay();
    void deleteSelection();
    return;
  }
  if ((ev.ctrlKey || ev.metaKey) && k === "a") {
    ev.preventDefault();
    const all: string[] = [];
    document.querySelectorAll<HTMLElement>(".clip-block[data-clip-id]").forEach((el) => {
      if (el.dataset.clipId) all.push(el.dataset.clipId);
    });
    setSelection(all);
    return;
  }
  if (ev.key === "Escape") {
    const help = document.getElementById("help-overlay");
    if (help?.classList.contains("open")) {
      help.classList.remove("open");
      help.setAttribute("aria-hidden", "true");
      return;
    }
    setSelection([]);
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
  $("btn-open").addEventListener("click", () => {
    void openProjectPath();
  });
  $("btn-new").addEventListener("click", () => {
    void newProjectPath();
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
  $("btn-export").addEventListener("click", () => {
    void exportProject();
  });
  $("btn-export-work").addEventListener("click", () => {
    void exportWorkArea();
  });
  $("btn-proxy").addEventListener("click", () => {
    void ensureProxy();
  });
  $("btn-link").addEventListener("click", () => {
    void linkSelection();
  });
  $("btn-unlink").addEventListener("click", () => {
    void unlinkSelection();
  });
  $("btn-save").addEventListener("click", () => {
    void saveProject();
  });
  $("btn-undo").addEventListener("click", () => {
    stopPlay();
    void undoEdit();
  });
  $("btn-redo").addEventListener("click", () => {
    stopPlay();
    void redoEdit();
  });
  $("btn-select-at").addEventListener("click", () => {
    void selectAtPlayhead();
  });
  $("btn-match-frame").addEventListener("click", () => {
    void matchFrameAtPlayhead();
  });
  $("btn-subclip").addEventListener("click", () => {
    stopPlay();
    void subclipSelection();
  });
  $("btn-marks-cuts").addEventListener("click", () => {
    void markersFromCuts();
  });
  $("btn-marks-clear").addEventListener("click", () => {
    void clearAllMarkers();
  });
  $("btn-split-markers").addEventListener("click", () => {
    stopPlay();
    void splitAtMarkers();
  });
  $("btn-name-media").addEventListener("click", () => {
    void nameSelectionFromMedia();
  });
  $("btn-dup-track").addEventListener("click", () => {
    stopPlay();
    void duplicateSelectedTrack();
  });
  $("btn-purge").addEventListener("click", () => {
    void purgeUnusedMedia();
  });
  $("btn-solo").addEventListener("click", () => {
    void soloSelection(true);
  });
  $("btn-unmute-all").addEventListener("click", () => {
    void unmuteAllClips();
  });
  $("btn-jcut").addEventListener("click", () => {
    void jlCutSelection("j", 12);
  });
  $("btn-lcut").addEventListener("click", () => {
    void jlCutSelection("l", 12);
  });
  $("btn-snap-prev").addEventListener("click", () => {
    void snapSelection("prev_end");
  });
  $("btn-snap-next").addEventListener("click", () => {
    void snapSelection("next_start");
  });
  $("btn-quantize").addEventListener("click", () => {
    void quantizeSelection(10);
  });
  $("btn-align-ph").addEventListener("click", () => {
    void alignSelectionToPlayhead();
  });
  $("btn-slip-m").addEventListener("click", () => {
    void slipSelection(-5);
  });
  $("btn-slip-p").addEventListener("click", () => {
    void slipSelection(5);
  });
  $("btn-roll-m").addEventListener("click", () => {
    void rollSelection(-5);
  });
  $("btn-roll-p").addEventListener("click", () => {
    void rollSelection(5);
  });
  $("btn-style").addEventListener("click", () => {
    void applySelectedStyle();
  });
  $("btn-copy-fx").addEventListener("click", () => {
    void copyEffectsFromSelection();
  });
  $("btn-paste-fx").addEventListener("click", () => {
    void pasteEffectsToSelection();
  });
  $("btn-copy-attr").addEventListener("click", () => {
    void copyAttributesFromSelection();
  });
  $("btn-paste-attr").addEventListener("click", () => {
    void pasteAttributesToSelection();
  });
  $("btn-review").addEventListener("click", () => {
    void runReview();
  });
  $("btn-sheet").addEventListener("click", () => {
    void makeSequenceSheet();
  });
  $("btn-slide-m").addEventListener("click", () => {
    void slideSelection(-5);
  });
  $("btn-slide-p").addEventListener("click", () => {
    void slideSelection(5);
  });
  $("btn-stretch-half").addEventListener("click", () => {
    void stretchSelection(0.5);
  });
  $("btn-stretch-dbl").addEventListener("click", () => {
    void stretchSelection(2);
  });
  $("btn-stagger").addEventListener("click", () => {
    void staggerSelection(6);
  });
  $("btn-rev-track").addEventListener("click", () => {
    void reverseTrackOrder();
  });
  $("btn-rev-clip").addEventListener("click", () => {
    void reverseSelectionClip();
  });
  $("btn-fill-gaps").addEventListener("click", () => {
    void fillGapsOnTracks();
  });
  $("btn-freeze").addEventListener("click", () => {
    stopPlay();
    void freezeAtPlayhead(15);
  });
  $("btn-match-dur").addEventListener("click", () => {
    void matchDurationSelection();
  });
  $("btn-dup-range").addEventListener("click", () => {
    stopPlay();
    void duplicateWorkArea();
  });
  $("btn-prep-export").addEventListener("click", () => {
    void prepareExport();
  });
  $("btn-clip-search").addEventListener("click", () => {
    void searchAndSelectClips();
  });
  $("clip-search").addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") {
      ev.preventDefault();
      void searchAndSelectClips();
    }
  });
  $("btn-stabilize").addEventListener("click", () => {
    void stabilizeSelection();
  });
  $("btn-export-markers").addEventListener("click", () => {
    void exportMarkersYoutube();
  });
  $("btn-export-dir").addEventListener("click", () => {
    void openExportDir();
  });
  $("btn-describe").addEventListener("click", () => {
    void describeSelectedClip();
  });
  $("btn-close-gaps").addEventListener("click", () => {
    stopPlay();
    void closeGapsOnTracks();
  });
  $("btn-lift").addEventListener("click", () => {
    stopPlay();
    void liftWorkArea(false);
  });
  $("btn-extract").addEventListener("click", () => {
    stopPlay();
    void liftWorkArea(true);
  });
  $("btn-zoom-in").addEventListener("click", () => {
    setZoom(state.zoom * 1.25);
  });
  $("btn-zoom-out").addEventListener("click", () => {
    setZoom(state.zoom / 1.25);
  });
  $("btn-zoom-reset").addEventListener("click", () => {
    setZoom(1);
  });
  $("btn-help").addEventListener("click", () => {
    toggleHelp();
  });
  $("help-overlay").addEventListener("click", (ev) => {
    if (ev.target === $("help-overlay")) toggleHelp();
  });
  $("btn-razor").addEventListener("click", () => {
    stopPlay();
    void razorAtPlayhead();
  });
  $("btn-marker").addEventListener("click", () => {
    stopPlay();
    void addMarkerAtPlayhead();
  });
  $("btn-mute").addEventListener("click", () => {
    stopPlay();
    void muteSelection();
  });
  $("btn-trim-q").addEventListener("click", () => {
    stopPlay();
    void trimSelectionToPlayhead("head");
  });
  $("btn-trim-w").addEventListener("click", () => {
    stopPlay();
    void trimSelectionToPlayhead("tail");
  });
  $("btn-io-sel").addEventListener("click", () => {
    void workAreaFromSelection();
  });
  $("btn-clear-fx").addEventListener("click", () => {
    void clearSelectionEffects();
  });
  $("btn-add-v").addEventListener("click", () => {
    void addTrack("video");
  });
  $("btn-add-a").addEventListener("click", () => {
    void addTrack("audio");
  });
  $("btn-prev-marker").addEventListener("click", () => {
    goToMarker(-1);
  });
  $("btn-next-marker").addEventListener("click", () => {
    goToMarker(1);
  });
  $("btn-prev-cut").addEventListener("click", () => {
    goToEditPoint(-1);
  });
  $("btn-next-cut").addEventListener("click", () => {
    goToEditPoint(1);
  });
  $("btn-set-in").addEventListener("click", () => {
    void setInPoint();
  });
  $("btn-set-out").addEventListener("click", () => {
    void setOutPoint();
  });
  $("btn-clear-io").addEventListener("click", () => {
    void clearInOut();
  });
  document.querySelectorAll<HTMLButtonElement>("[data-speed]").forEach((b) => {
    b.addEventListener("click", () => {
      const sp = Number(b.dataset.speed);
      if (Number.isFinite(sp)) void setSelectionSpeed(sp);
    });
  });
  $("btn-color-cycle").addEventListener("click", () => {
    void cycleSelectionColor();
  });
  $("btn-rename").addEventListener("click", () => {
    void renameSelection();
  });
  document.querySelectorAll<HTMLButtonElement>("[data-gain]").forEach((b) => {
    b.addEventListener("click", () => {
      const db = Number(b.dataset.gain);
      if (Number.isFinite(db)) void setSelectionGain(db);
    });
  });
  document.querySelectorAll<HTMLButtonElement>("[data-fade]").forEach((b) => {
    b.addEventListener("click", () => {
      const n = Number(b.dataset.fade);
      if (Number.isFinite(n)) void setSelectionFades(n, n);
    });
  });
  document.querySelectorAll<HTMLButtonElement>("[data-opacity]").forEach((b) => {
    b.addEventListener("click", () => {
      const a = Number(b.dataset.opacity);
      if (Number.isFinite(a)) void setSelectionOpacity(a);
    });
  });
  $("btn-join").addEventListener("click", () => {
    void joinSelection();
  });
  $("btn-transition").addEventListener("click", () => {
    void transitionSelection(12);
  });
  $("btn-validate").addEventListener("click", () => {
    void refreshValidate();
  });
  $("btn-notes-save").addEventListener("click", () => {
    void saveNotes();
  });
  $("chk-autosave").addEventListener("change", (ev) => {
    const on = (ev.target as HTMLInputElement).checked;
    void setAutosave(on);
  });
  $("file-import").addEventListener("change", (ev) => {
    const input = ev.target as HTMLInputElement;
    void importFiles(input.files);
    input.value = "";
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
  void loadPalette();
  void loadExportPresets();
  void loadStyles();
  void refreshRecent();
  void refresh();
});
