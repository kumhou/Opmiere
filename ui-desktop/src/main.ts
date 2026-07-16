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

type Doctor = {
  ok?: boolean;
  checks?: Array<{ id?: string; ok?: boolean; detail?: string }>;
};

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
      media_id?: string;
      media_kind?: string;
      has_audio_media?: boolean;
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
  mediaId?: string;
  hasAudio?: boolean;
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

/** media_id → peak envelope (0..1) */
const waveCache = new Map<string, number[]>();
let wavesLoading = false;
let waveTimer: ReturnType<typeof setTimeout> | 0 = 0;

type MarqueeDrag = {
  x0: number;
  y0: number;
  additive: boolean;
  moved: boolean;
};
let marqueeDrag: MarqueeDrag | null = null;
/** Suppress lane click-seek after a marquee gesture. */
let marqueeSuppressClick = false;

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
  /** Session: only auto-open the most recent project once after API is up. */
  didAutoOpenRecent: false,
  /** Place mode for bin → timeline / dbl-click place. */
  editMode: "insert" as "insert" | "overwrite",
  /** Single-select media in bin (for relink). */
  binMediaId: "" as string,
  /** Last generation job (desktop Generate panel). */
  genJobId: "" as string,
  genResultPath: "" as string,
  genStatus: "" as string,
};

function currentEditMode(): "insert" | "overwrite" {
  const el = document.getElementById("chk-overwrite") as HTMLInputElement | null;
  if (el) state.editMode = el.checked ? "overwrite" : "insert";
  return state.editMode;
}

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

/** Parse HH:MM:SS:FF, HH:MM:SS.mmm, or seconds → seconds. */
function parseTcToSeconds(raw: string, fps: number): number | null {
  const s = raw.trim().replace(/;/g, ":");
  if (!s) return null;
  const rate = Math.max(1, Math.round(fps || 30));
  const colonParts = s.split(":");
  if (colonParts.length === 4 && colonParts.every((p) => /^\d+$/.test(p))) {
    const [hh, mm, ss, ff] = colonParts.map((p) => parseInt(p, 10));
    const frames = ((hh * 3600 + mm * 60 + ss) * rate) + ff;
    return frames / rate;
  }
  if (colonParts.length === 3) {
    const [hms0, hms1, rest] = colonParts;
    if (!/^\d+$/.test(hms0) || !/^\d+$/.test(hms1)) return null;
    const secParts = rest.split(".");
    if (!/^\d+$/.test(secParts[0])) return null;
    const hh = parseInt(hms0, 10);
    const mm = parseInt(hms1, 10);
    const ss = parseInt(secParts[0], 10);
    const frac = secParts[1] ? parseFloat(`0.${secParts[1]}`) : 0;
    return hh * 3600 + mm * 60 + ss + frac;
  }
  const n = Number(s);
  if (Number.isFinite(n) && n >= 0) return n;
  return null;
}

async function jumpToTimecode() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  stopPlay();
  const cur = framesToTc(Math.round(state.t * state.fps), state.fps);
  const raw = window.prompt("Go to timecode (HH:MM:SS:FF or seconds)", cur);
  if (raw == null) return;
  // Prefer core /api/tc/parse for project fps parity; local fallback offline.
  try {
    const r = await postJson<{
      frame?: number;
      fps?: number;
      seconds?: number;
      tc?: string;
    }>("/api/tc/parse", { tc: raw.trim() });
    const fps = Number(r.fps) || state.fps;
    const sec =
      typeof r.seconds === "number"
        ? r.seconds
        : typeof r.frame === "number"
          ? r.frame / Math.max(1, fps)
          : null;
    if (sec == null || !Number.isFinite(sec)) throw new Error("no frame");
    await seekTo(Math.max(0, sec));
    let label = framesToTc(Math.round(state.t * state.fps), state.fps);
    try {
      const fmt = await postJson<{ tc?: string }>("/api/tc/format", {
        frame: Math.round(state.t * state.fps),
      });
      if (fmt.tc) label = fmt.tc;
    } catch {
      /* local label ok */
    }
    $("status-msg").textContent = `Playhead → ${label}`;
    return;
  } catch {
    /* fall through local */
  }
  const sec = parseTcToSeconds(raw, state.fps);
  if (sec == null) {
    $("status-msg").textContent = `Bad timecode: ${raw}`;
    return;
  }
  await seekTo(sec);
  $("status-msg").textContent = `Playhead → ${framesToTc(Math.round(state.t * state.fps), state.fps)}`;
}

/** Return false if user aborts a destructive project switch. */
async function confirmLeaveDirty(action: string): Promise<boolean> {
  if (!state.projectOpen || !state.dirty) return true;
  return window.confirm(
    `Unsaved changes — ${action}?\nOK = continue (discard if not saved), Cancel = stay`,
  );
}

async function closeProject() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "No project open";
    return;
  }
  stopPlay();
  let save = false;
  if (state.dirty) {
    if (
      !window.confirm(
        "Close project with unsaved changes?\nOK = continue, Cancel = stay open",
      )
    ) {
      return;
    }
    save = window.confirm("Save before closing?\nOK = Save & Close, Cancel = Close without saving");
  }
  try {
    await postJson("/api/project/close", { save });
    state.projectOpen = false;
    state.dirty = false;
    state.bundlePath = "";
    state.t = 0;
    state.durationSec = 0;
    state.durationFrames = 0;
    state.markers = [];
    state.selected.clear();
    state.clips.clear();
    waveCache.clear();
    renderTimeline(null);
    hideAllProgramSurfaces();
    setPlayheadUi();
    renderMediaBin(null);
    renderMarkerList();
    applyNotesUi("");
    $("project-state").textContent = "none";
    void setShellTitle(null);
    $("status-msg").textContent = save ? "Saved & closed" : "Project closed";
    await refreshRecent();
    await refresh();
  } catch (e) {
    $("status-msg").textContent = `Close failed: ${e}`;
  }
}

function setPlayheadUi() {
  const scrub = $("scrub") as HTMLInputElement;
  const max = Math.max(1, Math.round(state.durationSec * 1000));
  scrub.max = String(max);
  scrub.value = String(Math.round(state.t * 1000));
  scrub.disabled = !state.projectOpen || state.durationSec <= 0;
  const frames = Math.round(state.t * state.fps);
  $("tc").textContent = framesToTc(frames, state.fps);
  updatePlayheadTcFloat();
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

let proxyRefreshTimer: ReturnType<typeof setTimeout> | 0 = 0;

/** Debounced proxy rebuild after timeline structure changes (import/place/razor…). */
function scheduleProxyRefresh() {
  const el = document.getElementById("chk-auto-proxy") as HTMLInputElement | null;
  if (el && !el.checked) return;
  if (!state.projectOpen) return;
  if (proxyRefreshTimer) clearTimeout(proxyRefreshTimer);
  proxyRefreshTimer = setTimeout(() => {
    void (async () => {
      const ok = await ensureProxyFresh();
      if (ok) {
        const note = $("status-msg").textContent || "";
        if (!note.includes("Proxy")) {
          $("status-msg").textContent = `${note} · proxy ready`.replace(/^ · /, "");
        }
      }
    })();
  }, 900);
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
  if (view.dirty) bumpSessionStats("edit");
  const dirtyPill = document.getElementById("pill-dirty");
  if (dirtyPill && view.dirty) {
    dirtyPill.classList.add("pulse");
  } else if (dirtyPill) {
    dirtyPill.classList.remove("pulse");
  }
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
  const fadeIn = c.fade_in_frames ?? 0;
  const fadeOut = c.fade_out_frames ?? 0;
  el.innerHTML = [
    `<div class="sel-title" title="Double-click to rename">${escapeHtml(name)}</div>`,
    `<div class="kv">id <span>${escapeHtml(c.id)}</span></div>`,
    `<div class="kv">f${c.start} · ${c.dur}f · ${c.speed ?? 1}×</div>`,
    `<div class="kv">gain ${c.gain_db ?? 0} dB · opac ${c.opacity ?? 1}</div>`,
    `<div class="kv" id="sel-fades">fade in ${fadeIn}f · out ${fadeOut}f</div>`,
    c.muted ? `<div class="kv">muted</div>` : "",
    c.link_group ? `<div class="kv">link ${escapeHtml(c.link_group)}</div>` : "",
  ]
    .filter(Boolean)
    .join("");
  const title = el.querySelector(".sel-title");
  if (title) {
    title.addEventListener("dblclick", () => {
      void renameSelection();
    });
  }
  void enrichSelectionFades(ids[0]);
  void enrichClipGainOpacity(ids[0]);
  void refreshEffectsList();
}

/** Refresh fade line from GET /api/clip/fades/{id} (source of truth). */
async function enrichSelectionFades(clipId: string) {
  const line = document.getElementById("sel-fades");
  if (!line || !state.selected.has(clipId) || state.selected.size !== 1) return;
  try {
    const r = await getJson<{
      fade_in_frames?: number;
      fade_out_frames?: number;
      clip_id?: string;
    }>(`/api/clip/fades/${encodeURIComponent(clipId)}`);
    const fi = r.fade_in_frames ?? 0;
    const fo = r.fade_out_frames ?? 0;
    line.textContent = `fade in ${fi}f · out ${fo}f`;
    const c = state.clips.get(clipId);
    if (c) {
      c.fade_in_frames = fi;
      c.fade_out_frames = fo;
    }
  } catch {
    /* keep timeline-derived fades */
  }
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
    // Atomic layout write (one undo) + optional quick proxy refresh.
    const r = await postJson<{
      timeline?: TimelineView;
      layout?: { start?: number };
      preview?: { fresh?: boolean };
    }>("/api/clip/layout", {
      clip_id: clipId,
      start_frame: startFrame,
      refresh_preview: true,
      quick_preview: true,
    });
    if (r.timeline) {
      applyTimelineView(r.timeline);
      state.proxyFresh = !!(
        r.preview?.fresh ?? r.timeline.proxy?.fresh
      );
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

/** Magnetic: move earliest selected clip on each track + everything after it. */
async function rippleNudgeSelection(deltaFrames: number) {
  const ids = selectionList();
  if (!ids.length || deltaFrames === 0) {
    $("status-msg").textContent = "Select clip(s) for ripple nudge";
    return;
  }
  // One representative per track: leftmost selected
  const byTrack = new Map<string, string>();
  for (const id of ids) {
    const c = state.clips.get(id);
    if (!c) continue;
    const prev = byTrack.get(c.trackId);
    if (!prev) {
      byTrack.set(c.trackId, id);
      continue;
    }
    const p = state.clips.get(prev);
    if (p && c.start < p.start) byTrack.set(c.trackId, id);
  }
  $("status-msg").textContent = `Ripple nudge Δ${deltaFrames}…`;
  try {
    let last: TimelineView | undefined;
    for (const clipId of byTrack.values()) {
      const r = await postJson<{ timeline?: TimelineView }>("/api/ripple_nudge", {
        clip_id: clipId,
        delta_frames: deltaFrames,
        include_self: true,
      });
      if (r.timeline) last = r.timeline;
    }
    if (last) applyTimelineView(last);
    else await refresh();
    $("status-msg").textContent =
      `Ripple nudge Δ${deltaFrames} · ${byTrack.size} track(s)`;
    void seekTo(state.t);
  } catch (e) {
    $("status-msg").textContent = `Ripple nudge failed: ${e}`;
    await refresh();
  }
}

/** Open a hole at playhead on all tracks (keeps A/V aligned). */
async function insertTimeAtPlayhead(frames: number) {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  if (!Number.isFinite(frames) || frames <= 0) return;
  const at = playheadFrame();
  const tracks = state.tracks.length
    ? state.tracks
    : [{ id: "", kind: "video" }];
  $("status-msg").textContent = `Insert ${frames}f @ f${at}…`;
  try {
    let last: TimelineView | undefined;
    if (!state.tracks.length) {
      const r = await postJson<{ timeline?: TimelineView }>("/api/insert_time", {
        at_frame: at,
        frames,
      });
      last = r.timeline;
    } else {
      for (const t of tracks) {
        const r = await postJson<{ timeline?: TimelineView }>("/api/insert_time", {
          track_id: t.id,
          at_frame: at,
          frames,
        });
        if (r.timeline) last = r.timeline;
      }
    }
    if (last) applyTimelineView(last);
    else await refresh();
    $("status-msg").textContent = `Inserted ${frames}f @ f${at}`;
    void seekTo(state.t);
  } catch (e) {
    $("status-msg").textContent = `Insert time failed: ${e}`;
    await refresh();
  }
}

/** Extract [In,Out) on all tracks (ripple) — magnetic cut. */
async function extractTimeIO() {
  if (!state.projectOpen) return;
  if (!state.workIO.ready) {
    $("status-msg").textContent = "Set In and Out first (I / O)";
    return;
  }
  const start = state.workIO.in_frame!;
  const end = state.workIO.out_frame!;
  if (end <= start) {
    $("status-msg").textContent = "Invalid I/O range";
    return;
  }
  $("status-msg").textContent = `Extract time [${start},${end})…`;
  try {
    let last: TimelineView | undefined;
    const tracks = state.tracks.length ? state.tracks : [{ id: "" }];
    for (const t of tracks) {
      const body: Record<string, unknown> = {
        start_frame: start,
        end_frame: end,
        ripple: true,
      };
      if (t.id) body.track_id = t.id;
      const r = await postJson<{ timeline?: TimelineView }>(
        "/api/extract_time",
        body,
      );
      if (r.timeline) last = r.timeline;
    }
    if (last) applyTimelineView(last);
    else await refresh();
    $("status-msg").textContent = `Extracted time [${start},${end})`;
    void seekTo(Math.min(state.t, start / state.fps));
  } catch (e) {
    $("status-msg").textContent = `Extract time failed: ${e}`;
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
    let last: TimelineView | undefined;
    // Single + ripple → dedicated /api/ripple_delete (track-local magnetic hole close)
    if (ripple && ids.length === 1) {
      const r = await postJson<{
        timeline?: TimelineView;
        deleted_id?: string;
        frames_closed?: number;
      }>("/api/ripple_delete", { clip_id: ids[0] });
      if (r.timeline) last = r.timeline;
    } else {
      const r = await postJson<{ timeline?: TimelineView }>(
        "/api/clips/delete",
        {
          clip_ids: ids,
          ripple,
          follow_links: true,
        },
      );
      if (r.timeline) last = r.timeline;
    }
    state.selected.clear();
    if (last) applyTimelineView(last);
    else await refresh();
    $("sel-count").textContent = "0";
    updateSelectionCard();
    $("status-msg").textContent = `Deleted ${ids.length}${ripple ? " ripple" : ""}`;
    void seekTo(state.t);
    scheduleProxyRefresh();
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
    has_audio?: boolean;
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
    const kind = (m.kind || "video").toLowerCase();
    if (kind === "video" || kind === "image") {
      const thumb = document.createElement("img");
      thumb.className = "media-thumb";
      thumb.alt = "";
      thumb.loading = "lazy";
      thumb.decoding = "async";
      thumb.src = `${API_BASE}/api/media/${encodeURIComponent(m.id)}/thumb.jpg?t=0.1&width=96`;
      thumb.addEventListener("error", () => {
        thumb.classList.add("missing");
        thumb.removeAttribute("src");
      });
      row.appendChild(thumb);
    } else {
      const ph = document.createElement("div");
      ph.className = "media-thumb audio-ph";
      ph.textContent = "♪";
      row.appendChild(ph);
    }
    const meta = document.createElement("div");
    meta.className = "media-meta";
    const name = document.createElement("div");
    name.className = "media-name";
    name.textContent =
      m.label ||
      (m.path ? String(m.path).split(/[/\\]/).pop() : m.id) ||
      m.id;
    const kindEl = document.createElement("div");
    kindEl.className = "kind";
    const dur =
      typeof m.duration_frames === "number"
        ? ` · ${m.duration_frames}f`
        : "";
    kindEl.textContent = `${m.kind || "?"}${dur}`;
    meta.appendChild(name);
    meta.appendChild(kindEl);
    row.appendChild(meta);
    row.title = `${m.path || m.id} · drag to timeline or double-click @ playhead`;
    row.dataset.mediaId = m.id;
    if (m.kind) row.dataset.kind = m.kind;
    row.draggable = true;
    row.addEventListener("dragstart", (ev) => {
      if (!ev.dataTransfer) return;
      ev.dataTransfer.setData(
        "application/x-opmiere-media",
        JSON.stringify({ id: m.id, kind: m.kind || "video" }),
      );
      ev.dataTransfer.setData("text/plain", m.id);
      ev.dataTransfer.effectAllowed = "copy";
      row.classList.add("dragging-bin");
    });
    row.addEventListener("dragend", () => {
      row.classList.remove("dragging-bin");
    });
    row.addEventListener("click", (ev) => {
      if ((ev.target as HTMLElement).closest("button")) return;
      state.binMediaId = m.id;
      el.querySelectorAll(".media-row").forEach((r) => {
        r.classList.toggle("selected", (r as HTMLElement).dataset.mediaId === m.id);
      });
    });
    row.addEventListener("dblclick", () => {
      void placeMediaAtPlayhead(m.id, m.kind || "video");
    });
    if (state.binMediaId === m.id) row.classList.add("selected");
    el.appendChild(row);
  }
}

async function placeMediaOnTrack(
  mediaId: string,
  _kind: string,
  trackId: string,
  startFrame: number,
) {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const mode = currentEditMode();
  const start = Math.max(0, Math.floor(startFrame));
  $("status-msg").textContent = `Place ${mediaId} @ f${start} (${mode})…`;
  try {
    const r = await postJson<{ timeline?: TimelineView; clip_id?: string }>(
      "/api/place_media",
      {
        media_id: mediaId,
        track_id: trackId,
        start,
        mode,
      },
    );
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    $("status-msg").textContent =
      `Placed ${r.clip_id || mediaId} @ f${start} (${mode})`;
    void seekTo(state.t);
    scheduleProxyRefresh();
  } catch (e) {
    $("status-msg").textContent = `Place failed: ${e}`;
  }
}

function wireLaneMediaDrop(lane: HTMLElement, trackId: string, trackKind: string) {
  lane.addEventListener("dragover", (ev) => {
    const types = ev.dataTransfer?.types;
    if (!types) return;
    const ok =
      [...types].includes("application/x-opmiere-media") ||
      [...types].includes("text/plain");
    if (!ok) return;
    ev.preventDefault();
    if (ev.dataTransfer) ev.dataTransfer.dropEffect = "copy";
    lane.classList.add("drop-media");
  });
  lane.addEventListener("dragleave", (ev) => {
    if (ev.target === lane) lane.classList.remove("drop-media");
  });
  lane.addEventListener("drop", (ev) => {
    ev.preventDefault();
    lane.classList.remove("drop-media");
    const raw =
      ev.dataTransfer?.getData("application/x-opmiere-media") ||
      ev.dataTransfer?.getData("text/plain") ||
      "";
    if (!raw) return;
    let mediaId = raw;
    let kind = trackKind === "audio" ? "audio" : "video";
    try {
      const parsed = JSON.parse(raw) as { id?: string; kind?: string };
      if (parsed.id) {
        mediaId = parsed.id;
        if (parsed.kind) kind = parsed.kind;
      }
    } catch {
      /* plain media id */
    }
    const rect = lane.getBoundingClientRect();
    const x = (ev.clientX - rect.left) / Math.max(1, rect.width);
    const startFrame = Math.round(x * state.durationFrames);
    // Prefer track matching media kind when dropping on wrong lane kind
    let tid = trackId;
    if (kind === "audio" && trackKind !== "audio") {
      const a = trackForKind("audio");
      if (a) tid = a;
    } else if (kind !== "audio" && trackKind === "audio") {
      const v = trackForKind("video");
      if (v) tid = v;
    }
    void placeMediaOnTrack(mediaId, kind, tid, startFrame);
  });
}

function paintWaveOnCanvas(canvas: HTMLCanvasElement, peaks: number[]) {
  const w = Math.max(1, canvas.clientWidth || canvas.width || 1);
  const h = Math.max(1, canvas.clientHeight || canvas.height || 1);
  if (canvas.width !== w) canvas.width = w;
  if (canvas.height !== h) canvas.height = h;
  const ctx = canvas.getContext("2d");
  if (!ctx || !peaks.length) return;
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = "rgba(120, 200, 255, 0.55)";
  const mid = h / 2;
  const n = peaks.length;
  for (let i = 0; i < n; i++) {
    const p = Math.max(0, Math.min(1, peaks[i] ?? 0));
    const x0 = (i / n) * w;
    const x1 = ((i + 1) / n) * w;
    const amp = p * (mid - 1);
    ctx.fillRect(x0, mid - amp, Math.max(1, x1 - x0), amp * 2);
  }
}

function paintAllWaveforms() {
  document.querySelectorAll<HTMLCanvasElement>("canvas.clip-wave").forEach((cv) => {
    const mid = cv.dataset.mediaId;
    if (!mid) return;
    const peaks = waveCache.get(mid);
    if (peaks?.length) paintWaveOnCanvas(cv, peaks);
  });
}

function scheduleWaveformLoad() {
  if (waveTimer) clearTimeout(waveTimer);
  waveTimer = setTimeout(() => {
    void loadMissingWaveforms();
  }, 400);
}

async function loadMissingWaveforms() {
  if (wavesLoading || !state.projectOpen) return;
  const need: string[] = [];
  document.querySelectorAll<HTMLElement>(".clip-block[data-media-id]").forEach((el) => {
    if (el.dataset.hasAudio !== "1") return;
    const mid = el.dataset.mediaId;
    if (mid && !waveCache.has(mid)) need.push(mid);
  });
  const unique = [...new Set(need)].slice(0, 16);
  if (!unique.length) {
    paintAllWaveforms();
    return;
  }
  wavesLoading = true;
  try {
    for (const mediaId of unique) {
      try {
        const r = await postJson<{ peaks?: number[] }>("/api/waveform", {
          media_id: mediaId,
          num_peaks: 160,
        });
        if (r.peaks?.length) waveCache.set(mediaId, r.peaks);
      } catch {
        /* skip missing audio */
      }
    }
    paintAllWaveforms();
  } finally {
    wavesLoading = false;
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
  const mode = currentEditMode();
  $("status-msg").textContent = `Place ${mediaId} @ f${start} (${mode})…`;
  try {
    const r = await postJson<{ timeline?: TimelineView; clip_id?: string }>(
      "/api/place_media",
      {
        media_id: mediaId,
        track_id: trackId,
        start,
        mode,
      },
    );
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    $("status-msg").textContent =
      `Placed ${r.clip_id || mediaId} @ f${start} (${mode})`;
    void seekTo(state.t);
    scheduleProxyRefresh();
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
    scheduleProxyRefresh();
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
    state.dirty = false;
    const dirtyPill = document.getElementById("pill-dirty");
    if (dirtyPill) {
      dirtyPill.className = "pill ok";
      dirtyPill.textContent = "clean";
    }
    bumpSessionStats("save");
    void refreshValidate();
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
    row.title = "Click seek · double-click rename · Alt+click delete";
    row.style.borderLeftColor = m.color || "var(--color-primary)";
    row.addEventListener("click", (ev) => {
      if (ev.altKey) {
        void deleteMarker(m.id);
      } else {
        stopPlay();
        void seekTo(f / state.fps);
      }
    });
    row.addEventListener("dblclick", (ev) => {
      ev.preventDefault();
      void renameMarker(m.id, m.label || "");
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
  // TC major ticks (~every 1s, capped)
  const fps = Math.max(1, state.fps || 30);
  const step = Math.max(1, Math.round(fps)); // 1 second
  const maxTicks = 48;
  const totalSteps = Math.floor(durF / step);
  const stride = Math.max(1, Math.ceil(totalSteps / maxTicks));
  for (let i = 0; i <= totalSteps; i += stride) {
    const f = Math.min(durF, i * step);
    const tick = document.createElement("div");
    tick.className = "tc-tick";
    tick.style.left = `${(f / durF) * 100}%`;
    tick.title = framesToTc(f, fps);
    if (i % (stride * 2) === 0 || i === 0) {
      const lab = document.createElement("span");
      lab.className = "tc-tick-lab";
      lab.textContent = framesToTc(f, fps).replace(/^00:/, "");
      tick.appendChild(lab);
    }
    lane.appendChild(tick);
  }
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
    let last: TimelineView | undefined;
    if (ids.length === 1) {
      const r = await postJson<{ timeline?: TimelineView }>("/api/clip/mute", {
        clip_id: ids[0],
        muted,
      });
      if (r.timeline) last = r.timeline;
    } else {
      const r = await postJson<{ timeline?: TimelineView }>("/api/clips/mute", {
        clip_ids: ids,
        muted,
      });
      if (r.timeline) last = r.timeline;
    }
    if (last) applyTimelineView(last);
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
  void (async () => {
    try {
      await jumpNearMarker(dir > 0 ? "next" : "prev");
      return;
    } catch {
      /* local fallback */
    }
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
      target = sorted.find((m) => (m.frame ?? 0) > cur) || sorted[0];
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
  })();
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

/** Browser multipart upload (no reliable local paths). */
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
    scheduleProxyRefresh();
  } catch (e) {
    $("status-msg").textContent = `Import failed: ${e}`;
  }
}

/** Desktop: place existing local paths via place_batch (no re-upload copy). */
async function importLocalPaths(paths: string[]) {
  if (!paths.length) return;
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open or create a project first";
    return;
  }
  $("status-msg").textContent = `Importing ${paths.length} path(s)…`;
  try {
    const r = await postJson<{
      result?: {
        placed_count?: number;
        error_count?: number;
        errors?: Array<{ path?: string; error?: string }>;
      };
      timeline?: TimelineView;
    }>("/api/place_batch", {
      paths,
      sequential: true,
      build_proxy: false,
    });
    const n = r.result?.placed_count ?? 0;
    const errs = r.result?.error_count ?? 0;
    $("status-msg").textContent =
      errs > 0 ? `Imported ${n} clip(s), ${errs} error(s)` : `Imported ${n} clip(s)`;
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    await refreshMediaBin();
    void seekTo(state.t);
    scheduleProxyRefresh();
  } catch (e) {
    $("status-msg").textContent = `Import failed: ${e}`;
  }
}

/** Native multi-file picker (Tauri); returns absolute paths. */
async function pickMediaFiles(): Promise<string[] | null> {
  if (!isTauri()) return null;
  try {
    const { open } = await import("@tauri-apps/plugin-dialog");
    const selected = await open({
      multiple: true,
      directory: false,
      title: "Import media",
      filters: [
        {
          name: "Media",
          extensions: [
            "mp4",
            "mov",
            "mkv",
            "webm",
            "avi",
            "m4v",
            "mp3",
            "wav",
            "m4a",
            "aac",
            "flac",
            "ogg",
            "opus",
            "png",
            "jpg",
            "jpeg",
            "webp",
            "bmp",
            "gif",
            "tif",
            "tiff",
          ],
        },
        { name: "All", extensions: ["*"] },
      ],
    });
    if (selected == null) return [];
    if (Array.isArray(selected)) return selected.map(String).filter(Boolean);
    return selected ? [String(selected)] : [];
  } catch (e) {
    console.warn("Tauri media dialog failed", e);
    return null;
  }
}

async function startImport() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open or create a project first";
    return;
  }
  if (isTauri()) {
    const paths = await pickMediaFiles();
    if (paths === null) {
      // dialog plugin failed — browser-style file input
      $("file-import").click();
      return;
    }
    if (!paths.length) return; // cancelled
    await importLocalPaths(paths);
    return;
  }
  $("file-import").click();
}

const MEDIA_DROP_EXTS = new Set([
  ".mp4",
  ".mov",
  ".mkv",
  ".webm",
  ".avi",
  ".m4v",
  ".mp3",
  ".wav",
  ".m4a",
  ".aac",
  ".flac",
  ".ogg",
  ".opus",
  ".png",
  ".jpg",
  ".jpeg",
  ".webp",
  ".bmp",
  ".gif",
  ".tif",
  ".tiff",
]);

function isLikelyMediaPath(p: string): boolean {
  const lower = p.toLowerCase();
  const dot = lower.lastIndexOf(".");
  if (dot < 0) return false;
  return MEDIA_DROP_EXTS.has(lower.slice(dot));
}

function setDropTargetActive(on: boolean) {
  const el = document.getElementById("media-panel");
  if (el) el.classList.toggle("drop-active", on);
}

/** Browser HTML5 drop → upload_place. */
function wireBrowserFileDrop() {
  const panel = document.getElementById("media-panel");
  if (!panel) return;
  panel.addEventListener("dragover", (ev) => {
    ev.preventDefault();
    if (ev.dataTransfer) ev.dataTransfer.dropEffect = "copy";
    setDropTargetActive(true);
  });
  panel.addEventListener("dragleave", (ev) => {
    if (ev.target === panel) setDropTargetActive(false);
  });
  panel.addEventListener("drop", (ev) => {
    ev.preventDefault();
    setDropTargetActive(false);
    const files = ev.dataTransfer?.files;
    if (files?.length) void importFiles(files);
  });
}

/** Tauri OS file drop → place_batch with absolute paths. */
async function wireTauriFileDrop() {
  if (!isTauri()) return;
  try {
    const { getCurrentWebview } = await import("@tauri-apps/api/webview");
    await getCurrentWebview().onDragDropEvent((event) => {
      const payload = event.payload;
      if (payload.type === "enter" || payload.type === "over") {
        setDropTargetActive(true);
        return;
      }
      if (payload.type === "leave") {
        setDropTargetActive(false);
        return;
      }
      if (payload.type === "drop") {
        setDropTargetActive(false);
        const paths = (payload.paths || [])
          .map(String)
          .filter((p) => isLikelyMediaPath(p));
        if (!paths.length) {
          $("status-msg").textContent = "Drop ignored — no media files";
          return;
        }
        void importLocalPaths(paths);
      }
    });
  } catch (e) {
    console.warn("Tauri drag-drop wire failed", e);
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

async function exportDirPath(): Promise<string> {
  const r = await getJson<{ path?: string }>("/api/desktop/export_dir");
  if (!r.path) throw new Error("export dir unavailable");
  return r.path;
}

function joinExportPath(dir: string, name: string): string {
  const sep = dir.includes("\\") ? "\\" : "/";
  const base = dir.endsWith("\\") || dir.endsWith("/") ? dir.slice(0, -1) : dir;
  return `${base}${sep}${name}`;
}

function exportStamp(): string {
  return new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
}

/** CMX-style EDL of base video track → export dir. */
async function exportEdl() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  $("status-msg").textContent = "Exporting EDL…";
  try {
    const dir = await exportDirPath();
    const path = joinExportPath(dir, `opmiere_${exportStamp()}.edl`);
    const title = state.bundlePath
      ? projectLabelFromPath(state.bundlePath)
      : "Opmiere";
    const r = await postJson<{ path?: string; count?: number; body?: string }>(
      "/api/export/edl",
      { path, title },
    );
    $("status-msg").textContent =
      `EDL: ${r.path || path} (${r.count ?? "?"} events)`;
  } catch (e) {
    $("status-msg").textContent = `EDL failed: ${e}`;
  }
}

/** CSV/JSON cutlist → export dir. */
async function exportCutlist(format: "csv" | "json" = "csv") {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  $("status-msg").textContent = `Exporting cutlist (${format})…`;
  try {
    const dir = await exportDirPath();
    const path = joinExportPath(dir, `opmiere_${exportStamp()}.${format}`);
    const r = await postJson<{ path?: string; count?: number }>(
      "/api/export/cutlist",
      { path, format },
    );
    $("status-msg").textContent =
      `Cutlist: ${r.path || path} (${r.count ?? "?"} rows)`;
  } catch (e) {
    $("status-msg").textContent = `Cutlist failed: ${e}`;
  }
}

async function rotateSelection(degrees: number) {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clip(s) to rotate";
    return;
  }
  $("status-msg").textContent = `Rotate ${degrees}° ×${ids.length}…`;
  try {
    let last: TimelineView | undefined;
    for (const id of ids) {
      const r = await postJson<{ timeline?: TimelineView }>("/api/clip/rotate", {
        clip_id: id,
        degrees,
      });
      if (r.timeline) last = r.timeline;
    }
    if (last) applyTimelineView(last);
    else await refresh();
    $("status-msg").textContent = `Rotated ${degrees}° ×${ids.length}`;
    void seekTo(state.t);
    scheduleProxyRefresh();
  } catch (e) {
    $("status-msg").textContent = `Rotate failed: ${e}`;
  }
}

async function flipSelection(axis: "h" | "v") {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clip(s) to flip";
    return;
  }
  $("status-msg").textContent = `Flip${axis.toUpperCase()} ×${ids.length}…`;
  try {
    let last: TimelineView | undefined;
    for (const id of ids) {
      const r = await postJson<{ timeline?: TimelineView }>("/api/clip/flip", {
        clip_id: id,
        toggle_h: axis === "h",
        toggle_v: axis === "v",
      });
      if (r.timeline) last = r.timeline;
    }
    if (last) applyTimelineView(last);
    else await refresh();
    $("status-msg").textContent = `Flip${axis.toUpperCase()} ×${ids.length}`;
    void seekTo(state.t);
    scheduleProxyRefresh();
  } catch (e) {
    $("status-msg").textContent = `Flip failed: ${e}`;
  }
}

async function exportClipMediaUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const dir = await pickProjectFolder({ title: "Export clip media files to…" });
  if (!dir) return;
  const ids = selectionList();
  $("status-msg").textContent = ids.length
    ? `Exporting ${ids.length} clip(s)…`
    : "Exporting all clips…";
  try {
    const r = await postJson<{
      count?: number;
      error_count?: number;
      path?: string;
    }>("/api/export/clip_media", {
      out_dir: dir,
      clip_ids: ids.length ? ids : null,
      include_audio: true,
      container: "mp4",
    });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `ExpClips · ${r.count ?? 0}` +
      (r.error_count ? ` · err ${r.error_count}` : "") +
      ` → ${r.path ?? dir}`;
  } catch (e) {
    setProOut(`ExpClips failed: ${e}`);
    $("status-msg").textContent = `ExpClips failed: ${e}`;
  }
}

async function bakeSelectionUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clip(s) to bake";
    return;
  }
  $("status-msg").textContent = `Baking ${ids.length} clip(s)…`;
  try {
    let last: TimelineView | undefined;
    let n = 0;
    for (const id of ids) {
      const r = await postJson<{ timeline?: TimelineView; replaced?: boolean }>(
        "/api/clip/bake",
        {
          clip_id: id,
          replace: true,
          clear_effects: true,
          include_audio: true,
        },
      );
      if (r.timeline) last = r.timeline;
      if (r.replaced) n += 1;
    }
    if (last) applyTimelineView(last);
    else await refresh();
    await refreshMediaBin();
    $("status-msg").textContent = `Bake · ${n}/${ids.length}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`Bake failed: ${e}`);
    $("status-msg").textContent = `Bake failed: ${e}`;
  }
}

async function projectHealthUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  $("status-msg").textContent = "Health report…";
  try {
    const r = await getJson<{
      ready?: boolean;
      gaps?: { total_gaps?: number };
      unused?: { count?: number };
      path_c?: { path_c_ready?: boolean };
    }>("/api/project/health");
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `Health · ready=${r.ready ? "yes" : "no"}` +
      ` · gaps ${r.gaps?.total_gaps ?? "?"}` +
      ` · unused ${r.unused?.count ?? "?"}` +
      ` · pathC ${r.path_c?.path_c_ready === true ? "ok" : "…"}`;
  } catch (e) {
    setProOut(`Health failed: ${e}`);
    $("status-msg").textContent = `Health failed: ${e}`;
  }
}

async function insertEditAtPlayhead() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  if (!state.binMediaId) {
    $("status-msg").textContent = "Select media in bin first";
    return;
  }
  const trackId = trackForKind("video");
  if (!trackId) {
    $("status-msg").textContent = "No video track";
    return;
  }
  const at = playheadFrame();
  $("status-msg").textContent = `Insert ${state.binMediaId} @ f${at}…`;
  try {
    const r = await postJson<{ timeline?: TimelineView; clip_id?: string }>(
      "/api/edit/insert",
      {
        media_id: state.binMediaId,
        track_id: trackId,
        at_frame: at,
        ripple: true,
      },
    );
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    $("status-msg").textContent = `Insert · ${r.clip_id || "ok"} @ f${at}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`Insert failed: ${e}`);
    $("status-msg").textContent = `Insert failed: ${e}`;
  }
}

async function overwriteEditAtPlayhead() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  if (!state.binMediaId) {
    $("status-msg").textContent = "Select media in bin first";
    return;
  }
  const trackId = trackForKind("video");
  if (!trackId) {
    $("status-msg").textContent = "No video track";
    return;
  }
  const at = playheadFrame();
  $("status-msg").textContent = `Overwrite ${state.binMediaId} @ f${at}…`;
  try {
    const r = await postJson<{ timeline?: TimelineView; clip_id?: string }>(
      "/api/edit/overwrite",
      {
        media_id: state.binMediaId,
        track_id: trackId,
        at_frame: at,
      },
    );
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    $("status-msg").textContent = `Overwr · ${r.clip_id || "ok"} @ f${at}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`Overwr failed: ${e}`);
    $("status-msg").textContent = `Overwr failed: ${e}`;
  }
}

async function gradeLayerUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  $("status-msg").textContent = "Adding grade layer…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      clip_id?: string;
      track_id?: string;
    }>("/api/edit/grade_layer", {
      effects: [
        { type: "color", brightness: 0.05, contrast: 1.05, saturation: 1.05 },
      ],
      start: 0,
      end: null,
      opacity: 1.0,
      name: "Grade",
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `GradeL · ${r.clip_id || "ok"}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`GradeL failed: ${e}`);
    $("status-msg").textContent = `GradeL failed: ${e}`;
  }
}

async function threePointEditUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  if (!state.binMediaId) {
    $("status-msg").textContent = "Select media in bin first";
    return;
  }
  if (!state.workIO.ready) {
    $("status-msg").textContent = "Set In/Out (work area) first";
    return;
  }
  const trackId = trackForKind("video");
  if (!trackId) {
    $("status-msg").textContent = "No video track";
    return;
  }
  $("status-msg").textContent = "Three-point edit…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      clip_id?: string;
      speed?: number;
      dest_duration?: number;
    }>("/api/edit/three_point", {
      media_id: state.binMediaId,
      track_id: trackId,
      mode: "overwrite",
      fit: "stretch",
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `3-pt · ${r.clip_id || "ok"} · ${r.dest_duration ?? "?"}f @ ${r.speed?.toFixed?.(2) ?? r.speed ?? "?"}x`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`3-pt failed: ${e}`);
    $("status-msg").textContent = `3-pt failed: ${e}`;
  }
}

async function mediaUsageUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  $("status-msg").textContent = "Media usage…";
  try {
    const r = await getJson<{
      used_count?: number;
      unused_count?: number;
      count?: number;
    }>("/api/media/usage");
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `Usage · used ${r.used_count ?? "?"} · unused ${r.unused_count ?? "?"} / ${r.count ?? "?"}`;
  } catch (e) {
    setProOut(`Usage failed: ${e}`);
    $("status-msg").textContent = `Usage failed: ${e}`;
  }
}

async function applyEffectsTrackUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const trackId = trackForKind("video");
  if (!trackId) {
    $("status-msg").textContent = "No video track";
    return;
  }
  $("status-msg").textContent = "Applying track effects…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
      types?: string[];
    }>("/api/track/apply_effects", {
      track_id: trackId,
      replace_types: true,
      effects: [
        { type: "color", brightness: 0.03, contrast: 1.06, saturation: 1.04 },
      ],
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `FxTrk · ${r.count ?? 0} clips · ${(r.types || []).join(",") || "fx"}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`FxTrk failed: ${e}`);
    $("status-msg").textContent = `FxTrk failed: ${e}`;
  }
}

async function clearEffectsUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const ids = selectionList();
  const body: { clip_ids?: string[] | null; track_id?: string | null } = {};
  if (ids.length) {
    body.clip_ids = ids;
  } else {
    body.track_id = trackForKind("video");
    if (!body.track_id) {
      $("status-msg").textContent = "Select clips or open a video track";
      return;
    }
  }
  $("status-msg").textContent = "Clearing effects…";
  try {
    const r = await postJson<{ timeline?: TimelineView; count?: number }>(
      "/api/effects/clear",
      body,
    );
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `ClrFx · ${r.count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`ClrFx failed: ${e}`);
    $("status-msg").textContent = `ClrFx failed: ${e}`;
  }
}

async function exportStoryboardUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const dir = await pickProjectFolder({ title: "Storyboard output folder" });
  if (!dir) return;
  $("status-msg").textContent = "Exporting storyboard…";
  try {
    const r = await postJson<{
      still_count?: number;
      path?: string;
      count?: number;
    }>("/api/export/storyboard", {
      out_dir: dir,
      include_markers: true,
      include_clip_mids: true,
      include_contact: true,
      include_chapters: true,
      width: 640,
      max_stills: 48,
    });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `Story · ${r.still_count ?? 0} stills · ${r.count ?? 0} files → ${r.path ?? dir}`;
  } catch (e) {
    setProOut(`Story failed: ${e}`);
    $("status-msg").textContent = `Story failed: ${e}`;
  }
}

async function exportSocialPackUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const dir = await pickProjectFolder({ title: "Social pack output folder" });
  if (!dir) return;
  $("status-msg").textContent = "Exporting social pack (full renders)…";
  try {
    const r = await postJson<{
      count?: number;
      error_count?: number;
      path?: string;
    }>("/api/export/social_pack", {
      out_dir: dir,
      variants: ["youtube", "reels", "square"],
      name_prefix: "export",
    });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `Social · ${r.count ?? 0}` +
      (r.error_count ? ` · err ${r.error_count}` : "") +
      ` → ${r.path ?? dir}`;
  } catch (e) {
    setProOut(`Social failed: ${e}`);
    $("status-msg").textContent = `Social failed: ${e}`;
  }
}

async function reframeSelectionUi(aspect = "9:16") {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clip(s) to reframe";
    return;
  }
  $("status-msg").textContent = `Reframe ${aspect} ×${ids.length}…`;
  try {
    let last: TimelineView | undefined;
    for (const id of ids) {
      const r = await postJson<{ timeline?: TimelineView }>("/api/clip/reframe", {
        clip_id: id,
        aspect,
        anchor: "center",
      });
      if (r.timeline) last = r.timeline;
    }
    if (last) applyTimelineView(last);
    else await refresh();
    $("status-msg").textContent = `Reframe ${aspect} ×${ids.length}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`Reframe failed: ${e}`);
    $("status-msg").textContent = `Reframe failed: ${e}`;
  }
}

async function timecodeSelectionUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clip(s) for timecode";
    return;
  }
  $("status-msg").textContent = `Timecode ×${ids.length}…`;
  try {
    let last: TimelineView | undefined;
    for (const id of ids) {
      const r = await postJson<{ timeline?: TimelineView }>("/api/clip/timecode", {
        clip_id: id,
        enabled: true,
        position: "bottom",
        size: 28,
      });
      if (r.timeline) last = r.timeline;
    }
    if (last) applyTimelineView(last);
    else await refresh();
    $("status-msg").textContent = `TC · ${ids.length}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`TC failed: ${e}`);
    $("status-msg").textContent = `TC failed: ${e}`;
  }
}

async function markersFromClipsUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  $("status-msg").textContent = "Markers from clips…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/markers/from_clips", {
      track_id: trackForKind("video"),
      at: "start",
      clear_existing: false,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    await refreshMarkers();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `Mkr←Clips · ${r.count ?? 0}`;
  } catch (e) {
    setProOut(`Mkr←Clips failed: ${e}`);
    $("status-msg").textContent = `Mkr←Clips failed: ${e}`;
  }
}

async function watermarkSelectionUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clip(s) for watermark";
    return;
  }
  $("status-msg").textContent = `Watermark ×${ids.length}…`;
  try {
    let last: TimelineView | undefined;
    for (const id of ids) {
      const r = await postJson<{ timeline?: TimelineView }>("/api/clip/watermark", {
        clip_id: id,
        content: "© Opmiere",
        position: "bottom",
        size: 22,
        alpha: 0.55,
        enabled: true,
      });
      if (r.timeline) last = r.timeline;
    }
    if (last) applyTimelineView(last);
    else await refresh();
    $("status-msg").textContent = `© · ${ids.length}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`Watermark failed: ${e}`);
    $("status-msg").textContent = `Watermark failed: ${e}`;
  }
}

async function listCutsUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  $("status-msg").textContent = "Listing cuts…";
  try {
    const tid = trackForKind("video");
    const r = await getJson<{
      count?: number;
      hard_cut_count?: number;
    }>(
      tid
        ? `/api/edit/cuts?track_id=${encodeURIComponent(tid)}&kind=video`
        : "/api/edit/cuts?kind=video",
    );
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `Cuts? · ${r.count ?? 0} · hard ${r.hard_cut_count ?? 0}`;
  } catch (e) {
    setProOut(`Cuts failed: ${e}`);
    $("status-msg").textContent = `Cuts failed: ${e}`;
  }
}

async function watermarkTrackUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const trackId = trackForKind("video");
  if (!trackId) {
    $("status-msg").textContent = "No video track";
    return;
  }
  $("status-msg").textContent = "Watermark track…";
  try {
    const r = await postJson<{ timeline?: TimelineView; count?: number }>(
      "/api/track/watermark",
      {
        track_id: trackId,
        content: "© Opmiere",
        position: "bottom",
        size: 22,
        alpha: 0.55,
      },
    );
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `©Trk · ${r.count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`©Trk failed: ${e}`);
    $("status-msg").textContent = `©Trk failed: ${e}`;
  }
}

async function exportReviewPackageUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const dir = await pickProjectFolder({ title: "Review package output folder" });
  if (!dir) return;
  $("status-msg").textContent = "Exporting review package…";
  try {
    const r = await postJson<{ path?: string; meta?: string }>(
      "/api/export/review_package",
      {
        out_dir: dir,
        include_handoff: true,
        include_storyboard: true,
        include_social: false,
      },
    );
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `Review · → ${r.path ?? dir}`;
  } catch (e) {
    setProOut(`Review failed: ${e}`);
    $("status-msg").textContent = `Review failed: ${e}`;
  }
}

async function safeAreaSelectionUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clip(s) for safe area";
    return;
  }
  $("status-msg").textContent = `Safe area ×${ids.length}…`;
  try {
    let last: TimelineView | undefined;
    for (const id of ids) {
      const r = await postJson<{ timeline?: TimelineView }>("/api/clip/safe_area", {
        clip_id: id,
        enabled: true,
        action: 0.9,
        title: 0.8,
      });
      if (r.timeline) last = r.timeline;
    }
    if (last) applyTimelineView(last);
    else await refresh();
    $("status-msg").textContent = `Safe · ${ids.length}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`Safe failed: ${e}`);
    $("status-msg").textContent = `Safe failed: ${e}`;
  }
}

async function safeAreaTrackUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const trackId = trackForKind("video");
  if (!trackId) {
    $("status-msg").textContent = "No video track";
    return;
  }
  $("status-msg").textContent = "Safe area track…";
  try {
    const r = await postJson<{ timeline?: TimelineView; count?: number }>(
      "/api/track/safe_area",
      { track_id: trackId, action: 0.9, title: 0.8 },
    );
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    $("status-msg").textContent = `SafeT · ${r.count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`SafeT failed: ${e}`);
    $("status-msg").textContent = `SafeT failed: ${e}`;
  }
}

async function exportCutsReportUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const dir = await pickProjectFolder({ title: "Cuts report folder" });
  if (!dir) return;
  $("status-msg").textContent = "Exporting cuts report…";
  try {
    const tid = trackForKind("video");
    const r = await postJson<{
      path?: string;
      count?: number;
      hard_cut_count?: number;
    }>("/api/export/cuts_report", {
      path: `${dir.replace(/[\\/]+$/, "")}/cuts_report.json`,
      track_id: tid,
      kind: "video",
      format: "json",
    });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `CutsOut · ${r.count ?? 0} · hard ${r.hard_cut_count ?? 0} → ${r.path ?? dir}`;
  } catch (e) {
    setProOut(`CutsOut failed: ${e}`);
    $("status-msg").textContent = `CutsOut failed: ${e}`;
  }
}

async function exportBurninsUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const dir = await pickProjectFolder({ title: "Burn-in master output folder" });
  if (!dir) return;
  $("status-msg").textContent = "Exporting burn-in master…";
  try {
    const r = await postJson<{ path?: string }>("/api/export/burnins", {
      path: `${dir.replace(/[\\/]+$/, "")}/review_burnin.mp4`,
      timecode: true,
      safe_area: true,
      watermark: "© Opmiere REVIEW",
    });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `BurnIn · → ${r.path ?? dir}`;
  } catch (e) {
    setProOut(`BurnIn failed: ${e}`);
    $("status-msg").textContent = `BurnIn failed: ${e}`;
  }
}

async function renameClipsSeqUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const trackId = trackForKind("video");
  if (!trackId) {
    $("status-msg").textContent = "No video track";
    return;
  }
  $("status-msg").textContent = "Renaming clips…";
  try {
    const r = await postJson<{ timeline?: TimelineView; count?: number }>(
      "/api/track/rename_clips",
      { track_id: trackId, pattern: "Shot {n:03d}", start: 1 },
    );
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `Rename# · ${r.count ?? 0}`;
  } catch (e) {
    setProOut(`Rename# failed: ${e}`);
    $("status-msg").textContent = `Rename# failed: ${e}`;
  }
}

async function isolateSelectionUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clip(s) to isolate";
    return;
  }
  $("status-msg").textContent = `Isolate ×${ids.length}…`;
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      muted_count?: number;
      unmuted_count?: number;
    }>("/api/clips/isolate", {
      clip_ids: ids,
      follow_links: true,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `Isolate · keep ${r.unmuted_count ?? ids.length} · mute ${r.muted_count ?? "?"}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`Isolate failed: ${e}`);
    $("status-msg").textContent = `Isolate failed: ${e}`;
  }
}

async function crossfadesTrackUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const trackId = trackForKind("video");
  if (!trackId) {
    $("status-msg").textContent = "No video track";
    return;
  }
  $("status-msg").textContent = "Applying crossfades…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
      applied?: unknown;
    }>("/api/track/crossfades", {
      track_id: trackId,
      duration_frames: 12,
      transition_type: "cross_dissolve",
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    const n = r.count ?? (Array.isArray(r.applied) ? r.applied.length : "?");
    $("status-msg").textContent = `Xfade · ${n}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`Xfade failed: ${e}`);
    $("status-msg").textContent = `Xfade failed: ${e}`;
  }
}

async function markersFromHardCutsUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  $("status-msg").textContent = "Markers at hard cuts…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/markers/from_hard_cuts", {
      track_id: trackForKind("video"),
      prefix: "Cut ",
      clear_existing: false,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    await refreshMarkers();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `MkrCuts · ${r.count ?? 0}`;
  } catch (e) {
    setProOut(`MkrCuts failed: ${e}`);
    $("status-msg").textContent = `MkrCuts failed: ${e}`;
  }
}

async function blackdetectUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select a clip for blackdetect";
    return;
  }
  $("status-msg").textContent = "Blackdetect…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
      detected?: number;
    }>("/api/markers/from_blackdetect", {
      clip_id: ids[0],
      min_duration: 0.12,
      clear_existing: false,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    await refreshMarkers();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `Black? · ${r.count ?? 0} mkr · det ${r.detected ?? "?"}`;
  } catch (e) {
    setProOut(`Black? failed: ${e}`);
    $("status-msg").textContent = `Black? failed: ${e}`;
  }
}

async function setResolutionUi(w: number, h: number) {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  $("status-msg").textContent = `Set canvas ${w}×${h}…`;
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      to?: { w?: number; h?: number };
    }>("/api/project/resolution", { width: w, height: h });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `Canvas · ${r.to?.w ?? w}×${r.to?.h ?? h}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`Resolution failed: ${e}`);
    $("status-msg").textContent = `Resolution failed: ${e}`;
  }
}

async function silencedetectUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select a clip for silencedetect";
    return;
  }
  $("status-msg").textContent = "Silencedetect…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
      detected?: number;
    }>("/api/markers/from_silencedetect", {
      clip_id: ids[0],
      noise_db: -30,
      min_duration: 0.2,
      mark: "start",
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    await refreshMarkers();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `Sil? · ${r.count ?? 0} mkr · det ${r.detected ?? "?"}`;
  } catch (e) {
    setProOut(`Sil? failed: ${e}`);
    $("status-msg").textContent = `Sil? failed: ${e}`;
  }
}

async function splitAtSilencesUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select a clip to razor at silence";
    return;
  }
  $("status-msg").textContent = "Razor at silences…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/edit/split_at_silences", {
      clip_id: ids[0],
      noise_db: -30,
      min_duration: 0.2,
      mark: "start",
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `RzrSil · ${r.count ?? 0} splits`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`RzrSil failed: ${e}`);
    $("status-msg").textContent = `RzrSil failed: ${e}`;
  }
}

async function tightenSilencesUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select a clip to tighten";
    return;
  }
  $("status-msg").textContent = "Tightening silences…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/edit/tighten_silences", {
      clip_id: ids[0],
      noise_db: -30,
      min_duration: 0.35,
      pad_frames: 4,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `Tighten · removed ${r.count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`Tighten failed: ${e}`);
    $("status-msg").textContent = `Tighten failed: ${e}`;
  }
}

async function gainTrackUi(db: number) {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const trackId = trackForKind("audio") || trackForKind("video");
  if (!trackId) {
    $("status-msg").textContent = "No track";
    return;
  }
  $("status-msg").textContent = `Track gain ${db} dB…`;
  try {
    const r = await postJson<{ timeline?: TimelineView; count?: number }>(
      "/api/track/gain",
      { track_id: trackId, db },
    );
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    $("status-msg").textContent = `Gain · ${db} dB ×${r.count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`Gain failed: ${e}`);
    $("status-msg").textContent = `Gain failed: ${e}`;
  }
}

async function noiseReductionTrackUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const trackId = trackForKind("audio") || trackForKind("video");
  if (!trackId) {
    $("status-msg").textContent = "No track";
    return;
  }
  $("status-msg").textContent = "Noise reduction…";
  try {
    const r = await postJson<{ timeline?: TimelineView; count?: number }>(
      "/api/track/noise_reduction",
      { track_id: trackId, amount: 12 },
    );
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `NR · ×${r.count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`NR failed: ${e}`);
    $("status-msg").textContent = `NR failed: ${e}`;
  }
}

async function silenceMapUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select a clip for silence map";
    return;
  }
  $("status-msg").textContent = "Mapping silences…";
  try {
    const r = await postJson<{
      count?: number;
      total_silence_frames?: number;
    }>("/api/analyze/silence_ranges", {
      clip_id: ids[0],
      noise_db: -30,
      min_duration: 0.25,
    });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `SilMap · ${r.count ?? 0} ranges · ${r.total_silence_frames ?? 0}f`;
  } catch (e) {
    setProOut(`SilMap failed: ${e}`);
    $("status-msg").textContent = `SilMap failed: ${e}`;
  }
}

async function projectSnapshotUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const dir = await pickProjectFolder({ title: "Snapshot JSON folder" });
  if (!dir) return;
  $("status-msg").textContent = "Writing snapshot…";
  try {
    const r = await postJson<{ path?: string; clip_count?: number }>(
      "/api/export/project_snapshot",
      {
        path: `${dir.replace(/[\\/]+$/, "")}/project_snapshot.json`,
        include_media_status: true,
        include_preflight: true,
        include_cuts: true,
      },
    );
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `SnapJSON · clips ${r.clip_count ?? "?"} → ${r.path ?? dir}`;
  } catch (e) {
    setProOut(`SnapJSON failed: ${e}`);
    $("status-msg").textContent = `SnapJSON failed: ${e}`;
  }
}

async function exportPresetsPackUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const dir = await pickProjectFolder({ title: "Presets pack output folder" });
  if (!dir) return;
  $("status-msg").textContent = "Exporting presets pack…";
  try {
    const r = await postJson<{
      count?: number;
      error_count?: number;
      path?: string;
    }>("/api/export/presets_pack", {
      out_dir: dir,
      presets: ["draft", "streaming"],
      name_prefix: "export",
    });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `Presets · ${r.count ?? 0}` +
      (r.error_count ? ` · err ${r.error_count}` : "") +
      ` → ${r.path ?? dir}`;
  } catch (e) {
    setProOut(`Presets failed: ${e}`);
    $("status-msg").textContent = `Presets failed: ${e}`;
  }
}

async function matchDurationUi() {
  const ids = selectionList();
  if (ids.length < 2) {
    $("status-msg").textContent = "Select 2 clips: source then target duration";
    return;
  }
  $("status-msg").textContent = "Match duration…";
  try {
    const r = await postJson<{ timeline?: TimelineView }>(
      "/api/clip/match_duration",
      {
        clip_id: ids[0],
        target_clip_id: ids[1],
        clamp: true,
      },
    );
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `MatchD · ${ids[0]} → ${ids[1]}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`MatchD failed: ${e}`);
    $("status-msg").textContent = `MatchD failed: ${e}`;
  }
}

async function placePipUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  if (!state.binMediaId) {
    $("status-msg").textContent = "Select media in bin first";
    return;
  }
  $("status-msg").textContent = "Placing PiP…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      clip_id?: string;
      track_id?: string;
    }>("/api/edit/place_pip", {
      media_id: state.binMediaId,
      corner: "bottom_right",
      scale: 0.28,
      start: playheadFrame(),
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `PiP · ${r.clip_id || "ok"}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`PiP failed: ${e}`);
    $("status-msg").textContent = `PiP failed: ${e}`;
  }
}

async function lowerThirdUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const text = window.prompt("Lower-third text", "Speaker Name");
  if (text == null || !text.trim()) return;
  $("status-msg").textContent = "Adding lower-third…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      clip_id?: string;
    }>("/api/edit/lower_third", {
      content: text.trim(),
      start_frame: playheadFrame(),
      duration_frames: 90,
      size: 42,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `L3 · ${r.clip_id || "ok"}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`L3 failed: ${e}`);
    $("status-msg").textContent = `L3 failed: ${e}`;
  }
}

async function endCardUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const text = window.prompt("End-card text", "Thanks for watching");
  if (text == null) return;
  $("status-msg").textContent = "Adding end card…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      clip_id?: string;
    }>("/api/edit/end_card", {
      content: (text || "Thanks for watching").trim() || "Thanks for watching",
      duration_frames: 90,
      size: 56,
      fade_in_frames: 12,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `EndCard · ${r.clip_id || "ok"}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`EndCard failed: ${e}`);
    $("status-msg").textContent = `EndCard failed: ${e}`;
  }
}

async function splitScreenUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  if (!state.binMediaId) {
    $("status-msg").textContent = "Select left media in bin first";
    return;
  }
  const rightId = window.prompt(
    "Right media_id (bin id). Leave empty to cancel.",
    "",
  );
  if (rightId == null || !rightId.trim()) return;
  const orient =
    window.prompt("Orientation: lr or tb", "lr")?.trim().toLowerCase() || "lr";
  $("status-msg").textContent = "Placing split-screen…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      left_clip_id?: string;
      right_clip_id?: string;
    }>("/api/edit/split_screen", {
      media_left_id: state.binMediaId,
      media_right_id: rightId.trim(),
      start: playheadFrame(),
      orientation: orient === "tb" || orient === "top_bottom" ? "tb" : "lr",
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `Split · ${r.left_clip_id || "?"} / ${r.right_clip_id || "?"}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`Split failed: ${e}`);
    $("status-msg").textContent = `Split failed: ${e}`;
  }
}

async function introCardUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const text = window.prompt("Intro title", "Title");
  if (text == null) return;
  $("status-msg").textContent = "Adding intro card…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      clip_id?: string;
    }>("/api/edit/intro_card", {
      content: (text || "Title").trim() || "Title",
      duration_frames: 90,
      size: 56,
      fade_out_frames: 12,
      ripple_all_tracks: true,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `Intro · ${r.clip_id || "ok"}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`Intro failed: ${e}`);
    $("status-msg").textContent = `Intro failed: ${e}`;
  }
}

async function quadScreenUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  if (!state.binMediaId) {
    $("status-msg").textContent = "Select TL media in bin first";
    return;
  }
  const rest = window.prompt(
    "Three more media_ids (comma-separated: TR,BL,BR)",
    "",
  );
  if (rest == null || !rest.trim()) return;
  const parts = rest
    .split(/[,\s]+/)
    .map((s) => s.trim())
    .filter(Boolean);
  if (parts.length < 3) {
    $("status-msg").textContent = "Need 3 more media ids";
    return;
  }
  const mediaIds = [state.binMediaId, parts[0], parts[1], parts[2]];
  $("status-msg").textContent = "Placing quad grid…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/edit/quad_screen", {
      media_ids: mediaIds,
      start: playheadFrame(),
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `Quad · ${r.count ?? 4} clips`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`Quad failed: ${e}`);
    $("status-msg").textContent = `Quad failed: ${e}`;
  }
}

async function resetTransformSelection() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clip(s) to reset transform";
    return;
  }
  $("status-msg").textContent = `Reset transform ×${ids.length}…`;
  try {
    let last: TimelineView | undefined;
    for (const id of ids) {
      const r = await postJson<{ timeline?: TimelineView }>(
        "/api/clip/reset_transform",
        {
          clip_id: id,
          position: true,
          crop: true,
          rotate: true,
          opacity: false,
        },
      );
      if (r.timeline) last = r.timeline;
    }
    if (last) applyTimelineView(last);
    else await refresh();
    $("status-msg").textContent = `Transform reset ×${ids.length}`;
    void seekTo(state.t);
    scheduleProxyRefresh();
  } catch (e) {
    $("status-msg").textContent = `Reset transform failed: ${e}`;
  }
}

/** Center crop to width×height (project-relative defaults for 1080p). */
async function cropSelection(width: number, height: number) {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clip(s) to crop";
    return;
  }
  $("status-msg").textContent = `Crop ${width}×${height} ×${ids.length}…`;
  try {
    let last: TimelineView | undefined;
    for (const id of ids) {
      const r = await postJson<{ timeline?: TimelineView }>("/api/clip/crop", {
        clip_id: id,
        width,
        height,
      });
      if (r.timeline) last = r.timeline;
    }
    if (last) applyTimelineView(last);
    else await refresh();
    $("status-msg").textContent = `Crop ${width}×${height} ×${ids.length}`;
    void seekTo(state.t);
    scheduleProxyRefresh();
  } catch (e) {
    $("status-msg").textContent = `Crop failed: ${e}`;
  }
}

/** PiP / overlay position (normalized x,y + scale). */
async function positionSelection(x: number, y: number, scale: number) {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clip(s) for PiP position";
    return;
  }
  $("status-msg").textContent = `Position scale=${scale} ×${ids.length}…`;
  try {
    let last: TimelineView | undefined;
    for (const id of ids) {
      const r = await postJson<{ timeline?: TimelineView }>("/api/clip/position", {
        clip_id: id,
        x,
        y,
        scale,
      });
      if (r.timeline) last = r.timeline;
    }
    if (last) applyTimelineView(last);
    else await refresh();
    $("status-msg").textContent = `PiP ${scale} @ (${x},${y}) ×${ids.length}`;
    void seekTo(state.t);
    scheduleProxyRefresh();
  } catch (e) {
    $("status-msg").textContent = `Position failed: ${e}`;
  }
}

async function clearPositionSelection() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clip(s) to clear PiP";
    return;
  }
  try {
    let last: TimelineView | undefined;
    for (const id of ids) {
      const r = await postJson<{ timeline?: TimelineView }>(
        "/api/clip/position/clear",
        { clip_id: id },
      );
      if (r.timeline) last = r.timeline;
    }
    if (last) applyTimelineView(last);
    else await refresh();
    $("status-msg").textContent = `Cleared PiP ×${ids.length}`;
    scheduleProxyRefresh();
  } catch (e) {
    $("status-msg").textContent = `Clear PiP failed: ${e}`;
  }
}

/** Relink selected clip(s) to the media currently selected in the bin. */
async function relinkSelectionToBin() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select timeline clip(s) to relink";
    return;
  }
  if (!state.binMediaId) {
    $("status-msg").textContent = "Click a media row in the bin first";
    return;
  }
  $("status-msg").textContent = `Relink ×${ids.length} → ${state.binMediaId}…`;
  try {
    let last: TimelineView | undefined;
    for (const id of ids) {
      const r = await postJson<{ timeline?: TimelineView }>("/api/clip/relink", {
        clip_id: id,
        media_id: state.binMediaId,
        keep_source_range: true,
      });
      if (r.timeline) last = r.timeline;
    }
    if (last) applyTimelineView(last);
    else await refresh();
    await refreshMediaBin();
    $("status-msg").textContent = `Relinked ×${ids.length}`;
    void seekTo(state.t);
    scheduleProxyRefresh();
  } catch (e) {
    $("status-msg").textContent = `Relink failed: ${e}`;
  }
}

/** Pick .edl/.csv for import: Tauri native path, else FileReader text. */
async function pickImportFile(opts: {
  title: string;
  extensions: string[];
}): Promise<{ path?: string; text?: string } | null> {
  if (isTauri()) {
    try {
      const { open } = await import("@tauri-apps/plugin-dialog");
      const selected = await open({
        multiple: false,
        directory: false,
        title: opts.title,
        filters: [
          { name: "Interchange", extensions: opts.extensions },
          { name: "All", extensions: ["*"] },
        ],
      });
      if (selected == null) return null;
      const path = Array.isArray(selected) ? selected[0] : selected;
      return path ? { path: String(path) } : null;
    } catch (e) {
      console.warn("import dialog failed", e);
    }
  }
  return new Promise((resolve) => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = opts.extensions.map((e) => `.${e}`).join(",");
    input.addEventListener("change", () => {
      const f = input.files?.[0];
      if (!f) {
        resolve(null);
        return;
      }
      const reader = new FileReader();
      reader.onload = () => {
        resolve({ text: String(reader.result || "") });
      };
      reader.onerror = () => resolve(null);
      reader.readAsText(f);
    });
    input.click();
  });
}

async function importEdlFile() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const picked = await pickImportFile({
    title: "Import CMX EDL",
    extensions: ["edl", "txt"],
  });
  if (!picked) return;
  $("status-msg").textContent = "Importing EDL…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
      events?: number;
      agent_note?: string;
    }>("/api/import/edl", {
      path: picked.path || null,
      text: picked.text || null,
      replace_track: false,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    await refreshMediaBin();
    $("status-msg").textContent =
      `EDL imported (${r.count ?? r.events ?? "?"} events)`;
    scheduleProxyRefresh();
  } catch (e) {
    $("status-msg").textContent = `EDL import failed: ${e}`;
  }
}

async function importCutlistFile() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const picked = await pickImportFile({
    title: "Import cutlist CSV/JSON",
    extensions: ["csv", "json", "txt"],
  });
  if (!picked) return;
  $("status-msg").textContent = "Importing cutlist…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
      agent_note?: string;
    }>("/api/import/cutlist", {
      path: picked.path || null,
      text: picked.text || null,
      replace_track: false,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    await refreshMediaBin();
    $("status-msg").textContent = `Cutlist imported (${r.count ?? "?"} rows)`;
    scheduleProxyRefresh();
  } catch (e) {
    $("status-msg").textContent = `Cutlist import failed: ${e}`;
  }
}

/** Transcribe bin selection or media of selected clips. */
async function transcribeSelection() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const mediaIds = new Set<string>();
  if (state.binMediaId) mediaIds.add(state.binMediaId);
  for (const id of selectionList()) {
    const c = state.clips.get(id);
    if (c?.mediaId) mediaIds.add(c.mediaId);
  }
  if (!mediaIds.size) {
    $("status-msg").textContent = "Select bin media or timeline clips first";
    return;
  }
  $("status-msg").textContent = `Transcribing ×${mediaIds.size}…`;
  try {
    let last: Record<string, unknown> | null = null;
    for (const mid of mediaIds) {
      last = await postJson<Record<string, unknown>>("/api/media/transcribe", {
        media_id: mid,
        model_size: "base",
      });
    }
    await refreshMediaBin();
    const segs =
      (last?.segments as unknown[] | undefined)?.length ??
      (last?.segment_count as number | undefined) ??
      "?";
    $("status-msg").textContent = `Transcribed ×${mediaIds.size} (${segs} segs)`;
    const out = document.getElementById("review-out");
    if (out && last) {
      out.className = "review-out";
      out.textContent = JSON.stringify(last, null, 2).slice(0, 2000);
    }
  } catch (e) {
    $("status-msg").textContent =
      `Transcribe failed: ${e} (needs pip install -e ".[transcribe]")`;
  }
}

async function refreshMediaStatus() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  try {
    const r = await getJson<{
      media?: Array<{
        id?: string;
        online?: boolean;
        path?: string;
        missing?: boolean;
      }>;
      offline_count?: number;
      count?: number;
      items?: Array<Record<string, unknown>>;
    }>("/api/media/status");
    const items = r.media || r.items || [];
    const offline = items.filter(
      (m) => m.online === false || m.missing === true,
    );
    const nOff = r.offline_count ?? offline.length;
    $("status-msg").textContent =
      `Media status: ${items.length} assets, ${nOff} offline`;
    const out = document.getElementById("review-out");
    if (out) {
      out.className = "review-out";
      out.textContent =
        nOff > 0
          ? JSON.stringify(offline.slice(0, 20), null, 2)
          : JSON.stringify({ online: items.length, offline: 0 }, null, 2);
    }
  } catch (e) {
    $("status-msg").textContent = `Media status failed: ${e}`;
  }
}

/**
 * Duck first selected audio track under second (or first A under second A).
 * Selection order: music track clip then VO clip — uses their tracks.
 */
async function duckSelection() {
  if (!state.projectOpen) return;
  const ids = selectionList();
  const audioTracks = state.tracks.filter((t) => t.kind === "audio");
  let musicId: string | null = null;
  let voId: string | null = null;
  if (ids.length >= 2) {
    const a = state.clips.get(ids[0]);
    const b = state.clips.get(ids[1]);
    if (a && b) {
      musicId = a.trackId;
      voId = b.trackId;
    }
  } else if (audioTracks.length >= 2) {
    musicId = audioTracks[0].id;
    voId = audioTracks[1].id;
  }
  if (!musicId || !voId || musicId === voId) {
    $("status-msg").textContent =
      "Duck needs 2 audio tracks (select music then VO clips, or have ≥2 A tracks)";
    return;
  }
  $("status-msg").textContent = `Duck ${musicId} under ${voId}…`;
  try {
    const r = await postJson<{ timeline?: TimelineView }>("/api/duck", {
      track_id: musicId,
      against_track_id: voId,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    $("status-msg").textContent = `Ducking on ${musicId} ← ${voId}`;
  } catch (e) {
    $("status-msg").textContent = `Duck failed: ${e}`;
  }
}

async function clearDuckSelection() {
  if (!state.projectOpen) return;
  const ids = selectionList();
  const trackIds = new Set<string>();
  for (const id of ids) {
    const c = state.clips.get(id);
    if (c) trackIds.add(c.trackId);
  }
  if (!trackIds.size) {
    for (const t of state.tracks.filter((x) => x.kind === "audio")) {
      trackIds.add(t.id);
    }
  }
  if (!trackIds.size) {
    $("status-msg").textContent = "No audio tracks to clear duck";
    return;
  }
  try {
    let last: TimelineView | undefined;
    for (const tid of trackIds) {
      const r = await postJson<{ timeline?: TimelineView }>("/api/duck/clear", {
        track_id: tid,
      });
      if (r.timeline) last = r.timeline;
    }
    if (last) applyTimelineView(last);
    else await refresh();
    $("status-msg").textContent = `Cleared duck ×${trackIds.size}`;
  } catch (e) {
    $("status-msg").textContent = `Clear duck failed: ${e}`;
  }
}

/** ASR filler plan (dry_run) then optional apply on selection. Needs [transcribe] extra. */
async function fillerCutsSelection(apply: boolean) {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clip(s) for filler cut";
    return;
  }
  $("status-msg").textContent = apply
    ? `Applying filler cuts ×${ids.length}…`
    : `Planning filler cuts ×${ids.length}…`;
  try {
    let lastPlan: Record<string, unknown> | null = null;
    let applied = 0;
    for (const id of ids) {
      const r = await postJson<Record<string, unknown>>("/api/filler", {
        clip_id: id,
        dry_run: !apply,
        pad_seconds: 0.02,
      });
      lastPlan = r;
      if (apply && r.applied) applied += 1;
    }
    if (apply) {
      await refresh();
      scheduleProxyRefresh();
      $("status-msg").textContent = `Filler applied ×${applied}/${ids.length}`;
      void seekTo(state.t);
    } else {
      const cuts =
        (lastPlan?.cut_count as number | undefined) ??
        (lastPlan?.ranges as unknown[] | undefined)?.length ??
        (lastPlan?.filler_count as number | undefined) ??
        "?";
      const note = String(lastPlan?.agent_note || "").slice(0, 120);
      $("status-msg").textContent = `Filler plan: ${cuts} cut(s)${note ? " — " + note : ""}`;
      const out = document.getElementById("review-out");
      if (out) {
        out.className = "review-out";
        out.textContent = JSON.stringify(lastPlan, null, 2).slice(0, 2000);
      }
    }
  } catch (e) {
    $("status-msg").textContent =
      `Filler failed: ${e} (needs pip install -e ".[transcribe]")`;
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

async function snapSelectionToMarkers() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clip(s) to snap to markers";
    return;
  }
  $("status-msg").textContent = `Snap ${ids.length} → markers…`;
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
      skipped_count?: number;
    }>("/api/clips/snap_to_markers", {
      clip_ids: ids,
      edge: "start",
      prefer: "nearest",
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    $("status-msg").textContent =
      `Snapped ${r.count ?? 0} to markers` +
      (r.skipped_count ? ` · skip ${r.skipped_count}` : "");
    scheduleProxyRefresh();
  } catch (e) {
    $("status-msg").textContent = `Snap to markers failed: ${e}`;
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

/** Detach embedded audio of selected video clips onto an audio track. */
async function detachAudioSelection() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select video clip(s) to detach audio";
    return;
  }
  $("status-msg").textContent = `Detach audio ×${ids.length}…`;
  try {
    let last: TimelineView | undefined;
    let n = 0;
    for (const id of ids) {
      const info = state.clips.get(id);
      // skip pure audio tracks
      const tr = state.tracks.find((t) => t.id === info?.trackId);
      if (tr?.kind === "audio") continue;
      const r = await postJson<{ timeline?: TimelineView }>("/api/clip/detach_audio", {
        clip_id: id,
        link: true,
      });
      if (r.timeline) last = r.timeline;
      n += 1;
    }
    if (!n) {
      $("status-msg").textContent = "No video clips in selection";
      return;
    }
    if (last) applyTimelineView(last);
    else await refresh();
    $("status-msg").textContent = `Detached audio ×${n}`;
    void seekTo(state.t);
  } catch (e) {
    $("status-msg").textContent = `Detach audio failed: ${e}`;
    await refresh();
  }
}

async function autoLinkAV() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  $("status-msg").textContent = "Auto-link V/A…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      linked_count?: number;
      count?: number;
      pairs?: unknown[];
    }>("/api/auto_link_av", { tolerance_frames: 0 });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    const n = r.linked_count ?? r.count ?? r.pairs?.length ?? 0;
    $("status-msg").textContent = `Auto-link: ${n} pair(s)`;
  } catch (e) {
    $("status-msg").textContent = `Auto-link failed: ${e}`;
  }
}

/** Rate-stretch selected clips to meet next clip (or playhead if alone). */
async function fitToFillSelection() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clip(s) to fit-to-fill";
    return;
  }
  $("status-msg").textContent = `Fit-to-fill ×${ids.length}…`;
  try {
    let last: TimelineView | undefined;
    for (const id of ids) {
      const r = await postJson<{ timeline?: TimelineView }>("/api/clip/fit_to_fill", {
        clip_id: id,
        end_frame: null,
        clamp: true,
      });
      if (r.timeline) last = r.timeline;
    }
    if (last) applyTimelineView(last);
    else await refresh();
    $("status-msg").textContent = `Fit-to-fill ×${ids.length}`;
    void seekTo(state.t);
  } catch (e) {
    $("status-msg").textContent = `Fit-to-fill failed: ${e}`;
    await refresh();
  }
}

async function swapSelection() {
  const ids = selectionList();
  if (ids.length !== 2) {
    $("status-msg").textContent = "Select exactly 2 clips to swap";
    return;
  }
  $("status-msg").textContent = "Swap starts…";
  try {
    const r = await postJson<{ timeline?: TimelineView }>("/api/clips/swap", {
      clip_a: ids[0],
      clip_b: ids[1],
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    $("status-msg").textContent = "Swapped clip starts";
    void seekTo(state.t);
  } catch (e) {
    $("status-msg").textContent = `Swap failed: ${e}`;
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

async function loadTemplates() {
  const el = document.getElementById("template-select") as HTMLSelectElement | null;
  if (!el) return;
  try {
    const r = await getJson<{
      names?: string[];
      templates?: Record<string, { label?: string; description?: string }>;
    }>("/api/templates");
    const names = r.names || Object.keys(r.templates || {});
    if (!names.length) return;
    const cur = el.value;
    el.innerHTML = "";
    for (const n of names) {
      const opt = document.createElement("option");
      opt.value = n;
      const meta = r.templates?.[n];
      opt.textContent = meta?.label || n;
      opt.title = meta?.description || n;
      el.appendChild(opt);
    }
    if ([...el.options].some((o) => o.value === cur)) el.value = cur;
  } catch {
    /* keep static */
  }
}

/** Apply cut template using absolute paths of video media currently in the bin. */
async function applyCutTemplate() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const el = document.getElementById("template-select") as HTMLSelectElement | null;
  const template = el?.value || "talking_head";
  $("status-msg").textContent = `Apply template ${template}…`;
  try {
    const media = await getJson<{
      media?: Array<{ kind?: string; abs_path?: string; path?: string }>;
    }>("/api/media");
    const paths = (media.media || [])
      .filter((m) => (m.kind || "video") !== "audio")
      .map((m) => m.abs_path || m.path || "")
      .filter(Boolean);
    if (!paths.length) {
      $("status-msg").textContent = "Bin has no video media for template";
      return;
    }
    const styleEl = document.getElementById(
      "style-select",
    ) as HTMLSelectElement | null;
    const r = await postJson<Record<string, unknown>>("/api/templates/apply", {
      template,
      paths,
      style_override: styleEl?.value || null,
      dry_run: false,
      build_proxy: true,
      apply_silence: false,
    });
    await refresh();
    await refreshMediaBin();
    scheduleProxyRefresh();
    const note = String(r.agent_note || r.next_steps || "").slice(0, 160);
    $("status-msg").textContent = `Template ${template}${note ? " — " + note : ""}`;
    const out = document.getElementById("review-out");
    if (out) {
      out.className = "review-out";
      out.textContent = JSON.stringify(r, null, 2).slice(0, 2500);
    }
  } catch (e) {
    $("status-msg").textContent = `Template failed: ${e}`;
  }
}

/** Agent-style finish: prepare + export + delivery check → export dir. */
async function finishDelivery() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  stopPlay();
  const preset = selectedExportPreset();
  $("status-msg").textContent = `Finish delivery (${preset})…`;
  try {
    const dir = await exportDirPath();
    const output_path = joinExportPath(
      dir,
      `finish_${preset}_${exportStamp()}.mp4`,
    );
    const r = await postJson<Record<string, unknown>>("/api/finish", {
      output_path,
      normalize_preset: preset === "draft" ? "streaming" : preset,
      delivery_preset: preset === "draft" ? "streaming" : preset,
      run_review: true,
      run_sequence_sheet: false,
    });
    const ok = r.ok !== false;
    const path = String(r.output_path || output_path);
    $("status-msg").textContent = ok
      ? `Finish ok: ${path}`
      : `Finish soft-fail: ${path} (check delivery)`;
    const out = document.getElementById("review-out");
    if (out) {
      out.className = "review-out";
      out.textContent = JSON.stringify(r, null, 2).slice(0, 2500);
    }
  } catch (e) {
    $("status-msg").textContent = `Finish failed: ${e}`;
  }
}

async function searchTranscriptsUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const q = window.prompt("Search transcripts (cached ASR)", "");
  if (q == null || !q.trim()) return;
  $("status-msg").textContent = `Search ASR: ${q}…`;
  try {
    const r = await postJson<{
      hits?: Array<{
        media_id?: string;
        start?: number;
        end?: number;
        text?: string;
        time_seconds?: number;
      }>;
      count?: number;
    }>("/api/search_transcripts", {
      query: q.trim(),
      media_id: state.binMediaId || null,
      max_hits: 30,
    });
    const hits = r.hits || [];
    $("status-msg").textContent = `ASR hits: ${hits.length}`;
    const out = document.getElementById("review-out");
    if (out) {
      out.className = "review-out";
      out.innerHTML = "";
      if (!hits.length) {
        out.textContent = "No hits (run ASR first)";
        return;
      }
      for (const h of hits) {
        const row = document.createElement("div");
        row.className = "export-dir-row";
        const t = h.time_seconds ?? h.start ?? 0;
        row.textContent = `${Number(t).toFixed(1)}s  ${h.text || ""}`;
        row.title = h.media_id || "";
        row.addEventListener("click", () => {
          void seekTo(Number(t) || 0);
        });
        out.appendChild(row);
      }
    }
  } catch (e) {
    $("status-msg").textContent = `ASR search failed: ${e}`;
  }
}

/** Replace selected clip media with bin media (stretch to keep duration). */
async function replaceEditSelection() {
  const ids = selectionList();
  if (ids.length !== 1) {
    $("status-msg").textContent = "Select exactly 1 clip to replace";
    return;
  }
  if (!state.binMediaId) {
    $("status-msg").textContent = "Click a media row in the bin first";
    return;
  }
  $("status-msg").textContent = `Replace edit → ${state.binMediaId}…`;
  try {
    const r = await postJson<{ timeline?: TimelineView }>(
      "/api/clip/replace_edit",
      {
        clip_id: ids[0],
        media_id: state.binMediaId,
        mode: "stretch",
      },
    );
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    $("status-msg").textContent = "Replace edit done";
    void seekTo(state.t);
    scheduleProxyRefresh();
  } catch (e) {
    $("status-msg").textContent = `Replace failed: ${e}`;
  }
}

/** Copy each selected clip onto a new same-kind track. */
async function copySelectionToNewTrack() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clip(s) to copy to a new track";
    return;
  }
  $("status-msg").textContent = `Copy → new track ×${ids.length}…`;
  try {
    let last: TimelineView | undefined;
    const byKind = new Map<string, string[]>();
    for (const id of ids) {
      const c = state.clips.get(id);
      const tr = state.tracks.find((t) => t.id === c?.trackId);
      const kind = tr?.kind || "video";
      if (!byKind.has(kind)) byKind.set(kind, []);
      byKind.get(kind)!.push(id);
    }
    for (const [kind, clipIds] of byKind) {
      // POST /api/track?kind= returns track dict with id
      const res = await fetch(
        `${API_BASE}/api/track?kind=${encodeURIComponent(kind)}`,
        {
          method: "POST",
          headers: { Accept: "application/json" },
        },
      );
      if (!res.ok) {
        throw new Error(`create track HTTP ${res.status}`);
      }
      const created = (await res.json()) as { id?: string };
      let destId = created.id;
      if (!destId) {
        await refresh();
        const same = state.tracks.filter((t) => t.kind === kind);
        destId = same[same.length - 1]?.id;
      }
      if (!destId) throw new Error(`could not create ${kind} track`);
      for (const cid of clipIds) {
        const r = await postJson<{ timeline?: TimelineView }>(
          "/api/clip/copy_to_track",
          {
            clip_id: cid,
            track_id: destId,
            start: null,
            copy_effects: true,
            copy_link: false,
          },
        );
        if (r.timeline) last = r.timeline;
      }
    }
    if (last) applyTimelineView(last);
    else await refresh();
    $("status-msg").textContent = `Copied ×${ids.length} to new track(s)`;
    scheduleProxyRefresh();
  } catch (e) {
    $("status-msg").textContent = `Copy→track failed: ${e}`;
    await refresh();
  }
}

async function importMarkersText() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const text = window.prompt(
    "Paste YouTube chapters / marker text\n(e.g. 0:00 Intro\\n1:30 Hook)",
    "",
  );
  if (text == null || !text.trim()) return;
  $("status-msg").textContent = "Importing markers…";
  try {
    const r = await postJson<{ markers?: Marker[]; count?: number }>(
      "/api/markers/import",
      {
        text,
        format: "youtube",
        replace: false,
      },
    );
    state.markers = r.markers || [];
    renderMarkerList();
    $("status-msg").textContent = `Markers imported (${r.count ?? state.markers.length})`;
  } catch (e) {
    $("status-msg").textContent = `Marker import failed: ${e}`;
  }
}

async function refreshMixConsole() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  try {
    const r = await getJson<{
      audio_tracks?: Array<{
        id?: string;
        name?: string;
        clip_count?: number;
        duck?: unknown;
      }>;
      duck_edges?: unknown[];
      audio_track_count?: number;
      agent_note?: string;
    }>("/api/mix");
    const el = document.getElementById("mix-out");
    const n = r.audio_track_count ?? r.audio_tracks?.length ?? 0;
    const ducks = r.duck_edges?.length ?? 0;
    $("status-msg").textContent = `Mix: ${n} A-track(s), ${ducks} duck edge(s)`;
    if (el) {
      el.className = "review-out";
      const lines = (r.audio_tracks || []).map((t) => {
        const duck = t.duck ? " [duck]" : "";
        return `${t.name || t.id}: ${t.clip_count ?? "?"} clips${duck}`;
      });
      el.textContent =
        (lines.length ? lines.join("\n") : "(no audio tracks)") +
        (r.agent_note ? `\n— ${r.agent_note}` : "");
    }
  } catch (e) {
    $("status-msg").textContent = `Mix failed: ${e}`;
  }
}

async function findGapsUi() {
  if (!state.projectOpen) return;
  try {
    const vids = state.tracks.filter((t) => t.kind === "video");
    const body: Record<string, unknown> = {
      from_frame: 0,
      min_gap_frames: 1,
    };
    if (vids[0]?.id) body.track_id = vids[0].id;
    const r = await postJson<{
      gaps?: Array<{ start?: number; end?: number; frames?: number }>;
      count?: number;
    }>("/api/gaps/find", body);
    const gaps = r.gaps || [];
    $("status-msg").textContent = `Gaps: ${r.count ?? gaps.length}`;
    const out = document.getElementById("mix-out");
    if (out) {
      out.className = "review-out";
      if (!gaps.length) {
        out.textContent = "No gaps";
      } else {
        out.innerHTML = "";
        for (const g of gaps.slice(0, 40)) {
          const row = document.createElement("div");
          row.className = "export-dir-row";
          const s = g.start ?? 0;
          const e = g.end ?? s;
          row.textContent = `f${s}–${e} (${g.frames ?? e - s}f)`;
          row.addEventListener("click", () => {
            void seekTo(s / Math.max(1, state.fps));
          });
          out.appendChild(row);
        }
        void seekTo((gaps[0].start ?? 0) / Math.max(1, state.fps));
      }
    }
  } catch (e) {
    $("status-msg").textContent = `Find gaps failed: ${e}`;
  }
}

async function closeAllGapsUi() {
  if (!state.projectOpen) return;
  stopPlay();
  $("status-msg").textContent = "Closing all gaps…";
  try {
    const r = await postJson<{ timeline?: TimelineView }>(
      "/api/gaps/close_all",
      { from_frame: 0 },
    );
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    $("status-msg").textContent = "Closed gaps on all tracks";
    scheduleProxyRefresh();
  } catch (e) {
    $("status-msg").textContent = `Close-all gaps failed: ${e}`;
  }
}

async function selectClipsInIO() {
  if (!state.projectOpen) return;
  if (!state.workIO.ready) {
    $("status-msg").textContent = "Set In and Out first (I / O)";
    return;
  }
  const start = state.workIO.in_frame!;
  const end = state.workIO.out_frame!;
  try {
    const r = await postJson<{
      clip_ids?: string[];
      clips?: Array<{ id?: string; clip_id?: string }>;
      count?: number;
    }>("/api/clips/in_range", {
      start_frame: start,
      end_frame: end,
      partial: true,
    });
    const ids =
      r.clip_ids ||
      (r.clips || [])
        .map((c) => c.id || c.clip_id || "")
        .filter(Boolean);
    setSelection(ids);
    $("status-msg").textContent = `Selected ${ids.length} in I/O [${start},${end})`;
  } catch (e) {
    $("status-msg").textContent = `Sel I/O failed: ${e}`;
  }
}

async function selectByColorOfSelection() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select a colored clip first";
    return;
  }
  const color = state.clips.get(ids[0])?.color;
  if (!color) {
    $("status-msg").textContent = "First selection has no color";
    return;
  }
  try {
    const r = await postJson<{
      clip_ids?: string[];
      clips?: Array<{ id?: string; clip_id?: string }>;
    }>("/api/clips/by_color", { color });
    const found =
      r.clip_ids ||
      (r.clips || [])
        .map((c) => c.id || c.clip_id || "")
        .filter(Boolean);
    setSelection(found);
    $("status-msg").textContent = `Selected ${found.length} with color ${color}`;
  } catch (e) {
    $("status-msg").textContent = `Sel color failed: ${e}`;
  }
}

async function selectLinkedGroup() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select a linked clip first";
    return;
  }
  try {
    const r = await postJson<{
      clip_ids?: string[];
      members?: string[];
      group_id?: string;
    }>("/api/clips/linked", { clip_id: ids[0] });
    const members = r.clip_ids || r.members || [];
    if (!members.length) {
      $("status-msg").textContent = "No link group";
      return;
    }
    setSelection(members);
    $("status-msg").textContent =
      `Link group ${r.group_id || ""}: ${members.length} clip(s)`;
  } catch (e) {
    $("status-msg").textContent = `Sel link failed: ${e}`;
  }
}

async function renameSelectionPattern() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clip(s) to rename";
    return;
  }
  const pattern =
    window.prompt("Rename pattern ({nn} = 01,02…)", "Shot{nn}") || "";
  if (!pattern.trim()) return;
  $("status-msg").textContent = `Rename ${ids.length}…`;
  try {
    const r = await postJson<{ timeline?: TimelineView }>("/api/clips/rename", {
      pattern: pattern.trim(),
      clip_ids: ids,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    $("status-msg").textContent = `Renamed ×${ids.length} as ${pattern}`;
  } catch (e) {
    $("status-msg").textContent = `Rename failed: ${e}`;
  }
}

async function moveBlockToPlayhead() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clip(s) to move as a block";
    return;
  }
  const to = playheadFrame();
  stopPlay();
  $("status-msg").textContent = `Move block → f${to}…`;
  try {
    const r = await postJson<{ timeline?: TimelineView }>(
      "/api/clips/move_block",
      {
        clip_ids: ids,
        to_frame: to,
        follow_links: true,
      },
    );
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    $("status-msg").textContent = `Block @ f${to} (${ids.length} clips)`;
    void seekTo(state.t);
    scheduleProxyRefresh();
  } catch (e) {
    $("status-msg").textContent = `Move block failed: ${e}`;
  }
}

async function moveTrackOfSelection(delta: number) {
  const ids = selectionList();
  let trackId: string | null = null;
  if (ids.length) {
    trackId = state.clips.get(ids[0])?.trackId || null;
  } else if (state.tracks[0]) {
    trackId = state.tracks[0].id;
  }
  if (!trackId) {
    $("status-msg").textContent = "Select a clip (or have tracks) to reorder";
    return;
  }
  try {
    const r = await postJson<{ timeline?: TimelineView }>("/api/track/move", {
      track_id: trackId,
      delta,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    $("status-msg").textContent = `Track ${delta < 0 ? "up" : "down"}`;
  } catch (e) {
    $("status-msg").textContent = `Track move failed: ${e}`;
  }
}

async function shiftMarkersUi(delta: number) {
  if (!state.projectOpen) return;
  try {
    const r = await postJson<{ markers?: Marker[] }>("/api/markers/shift", {
      delta_frames: delta,
    });
    state.markers = r.markers || [];
    renderMarkerList();
    // repaint ruler if timeline open
    const ruler = document.querySelector(".marker-ruler") as HTMLElement | null;
    if (ruler) {
      // trigger via refresh markers path
      await refreshMarkers();
    }
    $("status-msg").textContent = `Markers Δ${delta}f`;
  } catch (e) {
    $("status-msg").textContent = `Marker shift failed: ${e}`;
  }
}

function trackIdOfSelection(): string | null {
  const ids = selectionList();
  if (ids.length) {
    return state.clips.get(ids[0])?.trackId || null;
  }
  const v = state.tracks.find((t) => t.kind === "video");
  return v?.id || state.tracks[0]?.id || null;
}

/** Cross-dissolve on every cut of the track of selection. */
async function xfadeAllOnTrack(durationFrames = 12) {
  if (!state.projectOpen) return;
  const trackId = trackIdOfSelection();
  if (!trackId) {
    $("status-msg").textContent = "No track for xfade";
    return;
  }
  stopPlay();
  $("status-msg").textContent = `Xfade all cuts on ${trackId}…`;
  try {
    const r = await postJson<{ timeline?: TimelineView; count?: number }>(
      "/api/transitions/apply_on_cuts",
      {
        track_id: trackId,
        transition_type: "cross_dissolve",
        duration_frames: durationFrames,
      },
    );
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    $("status-msg").textContent =
      `Xfade applied (${r.count ?? "?"} cuts, ${durationFrames}f)`;
    scheduleProxyRefresh();
  } catch (e) {
    $("status-msg").textContent = `Xfade all failed: ${e}`;
  }
}

async function clearTransitionsOnTrack() {
  if (!state.projectOpen) return;
  const trackId = trackIdOfSelection();
  const ids = selectionList();
  stopPlay();
  try {
    const body: Record<string, unknown> = {};
    if (ids.length) body.clip_ids = ids;
    else if (trackId) body.track_id = trackId;
    const r = await postJson<{ timeline?: TimelineView }>(
      "/api/transitions/clear",
      body,
    );
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    $("status-msg").textContent = "Transitions cleared";
    scheduleProxyRefresh();
  } catch (e) {
    $("status-msg").textContent = `Clear xfade failed: ${e}`;
  }
}

async function removeEmptyTracksUi() {
  if (!state.projectOpen) return;
  stopPlay();
  try {
    const r = await postJson<{ timeline?: TimelineView; removed?: unknown[] }>(
      "/api/tracks/remove_empty",
      { keep_one_per_kind: true },
    );
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    const n = Array.isArray(r.removed) ? r.removed.length : "?";
    $("status-msg").textContent = `Removed empty tracks (${n})`;
  } catch (e) {
    $("status-msg").textContent = `Rm empty failed: ${e}`;
  }
}

async function renameTrackOfSelection() {
  if (!state.projectOpen) return;
  const trackId = trackIdOfSelection();
  if (!trackId) {
    $("status-msg").textContent = "Select a clip (or have a track)";
    return;
  }
  const tr = state.tracks.find((t) => t.id === trackId);
  const cur = (tr as { name?: string } | undefined)?.name || "";
  // track name not always on state.tracks — use prompt default
  const name = window.prompt("Track name", cur || "V1");
  if (name == null) return;
  try {
    const r = await postJson<{ timeline?: TimelineView }>("/api/track/name", {
      track_id: trackId,
      name: name.trim() || null,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    $("status-msg").textContent = `Track renamed → ${name.trim() || "(cleared)"}`;
  } catch (e) {
    $("status-msg").textContent = `Track name failed: ${e}`;
  }
}

/** Append selected bin media to end of matching track. */
async function appendBinMedia() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  if (!state.binMediaId) {
    $("status-msg").textContent = "Click a media row in the bin first";
    return;
  }
  // guess kind from first selected track or video default
  let trackId = trackIdOfSelection();
  if (!trackId) {
    trackId = state.tracks.find((t) => t.kind === "video")?.id || null;
  }
  if (!trackId) {
    $("status-msg").textContent = "No track to append onto";
    return;
  }
  stopPlay();
  $("status-msg").textContent = `Append ${state.binMediaId}…`;
  try {
    const r = await postJson<{ timeline?: TimelineView }>("/api/append_media", {
      media_id: state.binMediaId,
      track_id: trackId,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    $("status-msg").textContent = `Appended ${state.binMediaId}`;
    void seekTo(state.t);
    scheduleProxyRefresh();
  } catch (e) {
    $("status-msg").textContent = `Append failed: ${e}`;
  }
}

/** Plan (and apply) multi-clip edit from bin media absolute paths. */
async function planEditFromBin(apply = true) {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  $("status-msg").textContent = apply ? "Plan+apply edit…" : "Plan edit…";
  try {
    const media = await getJson<{
      media?: Array<{ kind?: string; abs_path?: string; path?: string }>;
    }>("/api/media");
    const paths = (media.media || [])
      .map((m) => m.abs_path || m.path || "")
      .filter(Boolean);
    if (!paths.length) {
      $("status-msg").textContent = "Bin empty — import media first";
      return;
    }
    const r = await postJson<Record<string, unknown>>("/api/plan_edit", {
      paths,
      b_roll_mode: "overlay",
      j_cut_seconds: 0.4,
      apply,
    });
    if (apply) await refresh();
    scheduleProxyRefresh();
    $("status-msg").textContent = apply ? "Plan edit applied" : "Plan ready";
    const out = document.getElementById("review-out");
    if (out) {
      out.className = "review-out";
      out.textContent = JSON.stringify(r, null, 2).slice(0, 2500);
    }
  } catch (e) {
    $("status-msg").textContent = `Plan edit failed: ${e}`;
  }
}

async function applyProjectLook() {
  if (!state.projectOpen) return;
  const el = document.getElementById("style-select") as HTMLSelectElement | null;
  const look = el?.value || "documentary";
  $("status-msg").textContent = `Apply look ${look}…`;
  try {
    await postJson("/api/look", { look });
    await refresh();
    $("status-msg").textContent = `Look: ${look}`;
    scheduleProxyRefresh();
  } catch (e) {
    $("status-msg").textContent = `Look failed: ${e}`;
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
    // Prefer desktop temp path; fall back to core /api/export_work with explicit path.
    try {
      const r = await postJson<{
        ok?: boolean;
        path?: string;
        error?: string;
        warning?: string;
      }>("/api/desktop/export_work", {});
      if (r.ok && r.path) {
        $("status-msg").textContent =
          `Work export: ${r.path}${r.warning ? " (warn)" : ""}`;
        return;
      }
      if (r.error && !r.path) {
        // continue to core fallback
        $("status-msg").textContent = `Desktop export: ${r.error} — trying core…`;
      }
    } catch {
      /* core fallback */
    }
    let outDir = "";
    try {
      const d = await getJson<{ path?: string }>("/api/desktop/export_dir");
      outDir = d.path || "";
    } catch {
      outDir = "";
    }
    const defaultPath = outDir
      ? `${outDir.replace(/[\\/]+$/, "")}/export_work.mp4`
      : "export_work.mp4";
    const outputPath =
      window.prompt("Export work area to path", defaultPath) || "";
    if (!outputPath.trim()) {
      $("status-msg").textContent = "Export work cancelled";
      return;
    }
    const r2 = await postJson<{
      path?: string;
      output_path?: string;
      written?: string;
    }>("/api/export_work", {
      output_path: outputPath.trim(),
      normalize_preset: null,
      run_delivery_check: false,
    });
    $("status-msg").textContent =
      `Work export: ${r2.path || r2.output_path || r2.written || outputPath.trim()}`;
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
    let last: TimelineView | undefined;
    if (ids.length === 1) {
      const r = await postJson<{ timeline?: TimelineView }>("/api/clip/speed", {
        clip_id: ids[0],
        speed,
      });
      if (r.timeline) last = r.timeline;
    } else {
      const r = await postJson<{ timeline?: TimelineView }>("/api/clips/speed", {
        clip_ids: ids,
        speed,
      });
      if (r.timeline) last = r.timeline;
    }
    if (last) applyTimelineView(last);
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
  if (!(await confirmLeaveDirty("open this project"))) return;
  $("status-msg").textContent = `Opening ${path}…`;
  try {
    await postJson("/api/project/open", { bundle_path: path });
    $("status-msg").textContent = `Opened: ${path}`;
    state.t = 0;
    state.didAutoOpenRecent = true; // user/path open counts as settled
    await refresh();
    await refreshRecent();
    void seekTo(0);
    void setShellTitle(projectLabelFromPath(path));
    scheduleProxyRefresh();
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
  const c0 = state.clips.get(ids[0]);
  const current =
    c0?.name ||
    c0?.label ||
    document.querySelector<HTMLElement>(
      `.clip-block.selected[data-clip-id="${ids[0]}"]`,
    )?.dataset.label ||
    "";
  const name = window.prompt(
    ids.length === 1 ? "Clip name:" : `Name for ${ids.length} clips:`,
    current,
  );
  if (name == null) return;
  const trimmed = name.trim();
  try {
    let last: TimelineView | undefined;
    if (ids.length === 1) {
      // Single-clip path uses /api/clip/meta
      const r = await postJson<{ timeline?: TimelineView }>("/api/clip/meta", {
        clip_id: ids[0],
        name: trimmed || null,
        clear_name: !trimmed,
      });
      if (r.timeline) last = r.timeline;
    } else {
      const r = await postJson<{ timeline?: TimelineView }>("/api/clips/meta", {
        clip_ids: ids,
        name: trimmed || null,
        clear_name: !trimmed,
      });
      if (r.timeline) last = r.timeline;
    }
    if (last) applyTimelineView(last);
    else await refresh();
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
    let last: TimelineView | undefined;
    if (ids.length === 1) {
      const r = await postJson<{ timeline?: TimelineView }>("/api/clip/gain", {
        clip_id: ids[0],
        db,
        refresh_preview: false,
      });
      if (r.timeline) last = r.timeline;
    } else {
      const r = await postJson<{ timeline?: TimelineView }>("/api/clips/gain", {
        clip_ids: ids,
        db,
      });
      if (r.timeline) last = r.timeline;
    }
    if (last) applyTimelineView(last);
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
    let last: TimelineView | undefined;
    if (ids.length === 1) {
      const r = await postJson<{ timeline?: TimelineView }>("/api/clip/fades", {
        clip_id: ids[0],
        fade_in_frames: fadeIn,
        fade_out_frames: fadeOut,
      });
      if (r.timeline) last = r.timeline;
    } else {
      const r = await postJson<{ timeline?: TimelineView }>("/api/clips/fades", {
        clip_ids: ids,
        fade_in_frames: fadeIn,
        fade_out_frames: fadeOut,
      });
      if (r.timeline) last = r.timeline;
    }
    if (last) applyTimelineView(last);
    if (ids.length === 1) void enrichSelectionFades(ids[0]);
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
    let last: TimelineView | undefined;
    if (ids.length === 1) {
      const r = await postJson<{ timeline?: TimelineView }>(
        "/api/clip/opacity",
        { clip_id: ids[0], amount },
      );
      if (r.timeline) last = r.timeline;
    } else {
      const r = await postJson<{ timeline?: TimelineView }>(
        "/api/clips/opacity",
        { clip_ids: ids, amount },
      );
      if (r.timeline) last = r.timeline;
    }
    if (last) applyTimelineView(last);
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

/** Quick rebuild scrub proxy when stale (post-drag snappiness). */
async function refreshPreviewProxy(quick = true) {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  stopPlay();
  $("status-msg").textContent = quick
    ? "Quick proxy refresh…"
    : "Full proxy refresh…";
  try {
    const r = await postJson<{
      fresh?: boolean;
      path?: string;
      rebuilt?: boolean;
      cache_hit?: boolean;
    }>("/api/preview/refresh", { quick, force: false });
    state.proxyFresh = !!r.fresh;
    $("status-msg").textContent = r.fresh
      ? `Proxy ${quick ? "quick" : "full"} ready`
      : `Proxy refresh: ${JSON.stringify(r).slice(0, 100)}`;
    void seekTo(state.t);
  } catch (e) {
    $("status-msg").textContent = `Proxy refresh failed: ${e}`;
  }
}

/** Dump core project.describe() into Review panel. */
async function showProjectState() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  try {
    const r = await getJson<Record<string, unknown>>("/api/project/state");
    const out = document.getElementById("review-out");
    if (out) {
      out.className = "review-out";
      out.textContent = JSON.stringify(r, null, 2).slice(0, 6000);
    }
    const tracks = Array.isArray(r.tracks) ? r.tracks.length : "?";
    $("status-msg").textContent = `Project state · tracks=${tracks}`;
  } catch (e) {
    $("status-msg").textContent = `Project state failed: ${e}`;
  }
}

/** Append a known effect to selection via /api/clips/effect. */
async function applyFxPreset(kind: string) {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clip(s) for grade FX";
    return;
  }
  const effects: Record<string, Record<string, unknown>> = {
    bright: {
      type: "color",
      brightness: 0.08,
      contrast: 1.0,
      saturation: 1.0,
    },
    contrast: {
      type: "color",
      brightness: 0.0,
      contrast: 1.12,
      saturation: 1.0,
    },
    sat: {
      type: "color",
      brightness: 0.0,
      contrast: 1.0,
      saturation: 1.15,
    },
    vignette: { type: "vignette", strength: 0.55 },
    blur: { type: "blur", amount: 2.5 },
    grain: { type: "film_grain", amount: 18 },
    vintage: { type: "curves", preset: "vintage" },
    sharpen: { type: "sharpen", amount: 1.2 },
    warm: { type: "white_balance", temperature: 5600, mix: 0.65 },
    cool: { type: "white_balance", temperature: 7500, mix: 0.55 },
    glow: { type: "glow", amount: 10, intensity: 0.55 },
    ken: {
      type: "ken_burns",
      zoom_start: 1.0,
      zoom_end: 1.15,
      x_start: 0.5,
      y_start: 0.5,
      x_end: 0.48,
      y_end: 0.45,
    },
  };
  let effect = effects[kind];
  if (kind === "text") {
    const content = window.prompt("Title text (bottom lower-third)", "Opmiere");
    if (content == null) return;
    const trimmed = content.trim();
    if (!trimmed) {
      $("status-msg").textContent = "Empty title text";
      return;
    }
    effect = {
      type: "text",
      content: trimmed,
      position: "bottom",
      size: 48,
      border_width: 2,
    };
  }
  if (!effect) {
    $("status-msg").textContent = `Unknown FX preset: ${kind}`;
    return;
  }
  $("status-msg").textContent = `FX ${kind} ×${ids.length}…`;
  try {
    const r = await postJson<{ timeline?: TimelineView; count?: number }>(
      "/api/clips/effect",
      { clip_ids: ids, effect },
    );
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    void refreshEffectsList();
    // Dual-surface: tell editor whether path-C still preview can approximate this FX.
    let pathNote = "";
    try {
      const cat = await getJson<{
        mapped?: string[];
        unmapped?: string[];
        adapter_version?: number;
      }>("/api/preview/openshot_effects");
      const et = String(effect.type || "");
      if (et && Array.isArray(cat.mapped) && cat.mapped.includes(et)) {
        pathNote = ` · path-C v${cat.adapter_version ?? "?"} maps ${et}`;
      } else if (et && Array.isArray(cat.unmapped) && cat.unmapped.includes(et)) {
        pathNote = ` · path-C skips ${et} (export/ffmpeg still applies)`;
      }
    } catch {
      /* catalog optional */
    }
    $("status-msg").textContent = `FX ${kind} on ${ids.length} clip(s)${pathNote}`;
    void seekTo(state.t);
    scheduleProxyRefresh();
  } catch (e) {
    $("status-msg").textContent = `FX ${kind} failed: ${e}`;
  }
}

function setGenOut(text: string, muted = false) {
  const el = document.getElementById("gen-out");
  if (!el) return;
  el.className = muted ? "review-out muted" : "review-out";
  el.textContent = text.slice(0, 4000);
}

function collectGenParams(kind: string): Record<string, unknown> {
  const stepsEl = document.getElementById("gen-steps") as HTMLInputElement | null;
  const wEl = document.getElementById("gen-w") as HTMLInputElement | null;
  const hEl = document.getElementById("gen-h") as HTMLInputElement | null;
  const steps = Math.max(1, Math.min(80, Number(stepsEl?.value) || 20));
  const width = Math.max(256, Math.min(2048, Number(wEl?.value) || 512));
  const height = Math.max(256, Math.min(2048, Number(hEl?.value) || 512));
  const params: Record<string, unknown> = { steps };
  if (kind === "image" || kind === "video") {
    params.width = width;
    params.height = height;
  }
  return params;
}

async function submitGeneration() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const kindEl = document.getElementById("gen-kind") as HTMLSelectElement | null;
  const promptEl = document.getElementById("gen-prompt") as HTMLTextAreaElement | null;
  const kind = kindEl?.value || "image";
  const prompt = (promptEl?.value || "").trim();
  if (!prompt) {
    $("status-msg").textContent = "Enter a generation prompt";
    return;
  }
  $("status-msg").textContent = `Generate ${kind}…`;
  setGenOut(`Submitting ${kind}…`);
  try {
    const r = await postJson<{
      job_id?: string;
      kind?: string;
      prompt?: string;
      agent_note?: string;
    }>("/api/generate", { kind, prompt, params: collectGenParams(kind) });
    state.genJobId = r.job_id || "";
    state.genResultPath = "";
    state.genStatus = "queued";
    setGenOut(
      [
        `job ${state.genJobId}`,
        `kind ${r.kind || kind}`,
        r.agent_note || "Poll until done",
      ].join("\n"),
    );
    $("status-msg").textContent = `Job ${state.genJobId.slice(0, 8)}…`;
    bumpSessionStats("gen");
    void pollGeneration(true);
  } catch (e) {
    setGenOut(`Generate failed: ${e}`);
    $("status-msg").textContent = `Generate failed: ${e}`;
  }
}

async function pollGeneration(silent = false) {
  if (!state.genJobId) {
    if (!silent) $("status-msg").textContent = "No generation job yet";
    return;
  }
  try {
    let r: {
      job_id?: string;
      status?: string;
      kind?: string;
      prompt?: string;
      result_path?: string | null;
      error?: string | null;
      license?: Record<string, string>;
    };
    try {
      r = await getJson(`/api/generate/job/${encodeURIComponent(state.genJobId)}`);
    } catch {
      r = await postJson("/api/generate/status", { job_id: state.genJobId });
    }
    state.genStatus = r.status || "";
    state.genResultPath = r.result_path || "";
    const lines = [
      `job ${r.job_id || state.genJobId}`,
      `status ${r.status || "?"}`,
      `kind ${r.kind || "?"}`,
      r.result_path ? `path ${r.result_path}` : "",
      r.error ? `error ${r.error}` : "",
      r.license
        ? `license ${r.license.name || "?"} commercial=${r.license.commercial_use || "?"}`
        : "",
    ].filter(Boolean);
    setGenOut(lines.join("\n"));
    if (!silent) {
      $("status-msg").textContent = `Job ${r.status || "?"}`;
    }
    if (r.status === "queued" || r.status === "running") {
      window.setTimeout(() => void pollGeneration(true), 2000);
    }
  } catch (e) {
    setGenOut(`Poll failed: ${e}`);
    if (!silent) $("status-msg").textContent = `Poll failed: ${e}`;
  }
}

async function placeGeneratedAtPlayhead() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  if (!state.genJobId) {
    $("status-msg").textContent = "No generation job to place";
    return;
  }
  if (state.genStatus && state.genStatus !== "done") {
    $("status-msg").textContent = `Job not done (${state.genStatus}) — Poll first`;
    return;
  }
  const start = playheadFrame();
  // prefer selected track if any, else API defaults to first video
  let trackId: string | null = null;
  const ids = selectionList();
  if (ids.length) {
    const c = state.clips.get(ids[0]);
    if (c?.trackId) trackId = c.trackId;
  }
  $("status-msg").textContent = `Place gen @ f${start}…`;
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      clip?: { id?: string };
      track_id?: string;
    }>("/api/place_generated", {
      job_id: state.genJobId,
      track_id: trackId,
      start,
      duration_frames: null,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    await refreshMediaBin();
    setGenOut(
      `Placed ${r.clip?.id || "clip"} on ${r.track_id || "?"} @ f${start}`,
    );
    $("status-msg").textContent = `Placed gen @ f${start}`;
    scheduleProxyRefresh();
  } catch (e) {
    setGenOut(`Place failed: ${e}`);
    $("status-msg").textContent = `Place gen failed: ${e}`;
  }
}

async function qualityCheckLastGen() {
  let path = state.genResultPath;
  if (!path) {
    // try poll once
    if (state.genJobId) await pollGeneration(true);
    path = state.genResultPath;
  }
  if (!path) {
    $("status-msg").textContent = "No result path — finish a job first";
    return;
  }
  try {
    const r = await postJson<Record<string, unknown>>("/api/quality_check", {
      path,
    });
    setGenOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = "Quality check done";
  } catch (e) {
    setGenOut(`QC failed: ${e}`);
    $("status-msg").textContent = `QC failed: ${e}`;
  }
}

async function showLicenseReport() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  try {
    const r = await getJson<Record<string, unknown>>("/api/license_report");
    setGenOut(JSON.stringify(r, null, 2));
    const safe = r.safe_for_commercial_use;
    $("status-msg").textContent =
      safe === true
        ? "Licenses OK for commercial"
        : safe === false
          ? "Licenses flagged — review"
          : "License report";
  } catch (e) {
    setGenOut(`License report failed: ${e}`);
    $("status-msg").textContent = `Licenses failed: ${e}`;
  }
}

function setProOut(text: string, muted = false) {
  const el = document.getElementById("pro-out");
  if (!el) return;
  el.className = muted ? "review-out muted" : "review-out";
  el.textContent = text.slice(0, 5000);
  el.title = "Double-click to copy";
}

async function copyProOut() {
  const el = document.getElementById("pro-out");
  const t = el?.textContent || "";
  if (!t || t === "Pro —") {
    $("status-msg").textContent = "Nothing to copy";
    return;
  }
  try {
    await navigator.clipboard.writeText(t);
    $("status-msg").textContent = "Pro output copied";
  } catch {
    window.prompt("Pro output", t.slice(0, 2000));
  }
}

async function runAgentPreflight() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  $("status-msg").textContent = "Preflight…";
  try {
    const r = await getJson<Record<string, unknown>>("/api/agent/preflight");
    setProOut(JSON.stringify(r, null, 2));
    const ready = r.ready === true;
    $("status-msg").textContent = ready
      ? "Preflight OK"
      : `Preflight: ${(r.next_steps as string[] | undefined)?.[0] || "issues"}`;
  } catch (e) {
    setProOut(`Preflight failed: ${e}`);
    $("status-msg").textContent = `Preflight failed: ${e}`;
  }
}

async function runAgentFinish() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  if (
    !window.confirm(
      "Agent finish session? prepare → proxy → export → delivery check (to export dir).",
    )
  ) {
    return;
  }
  stopPlay();
  $("status-msg").textContent = "Agent finish…";
  try {
    const r = await postJson<Record<string, unknown>>("/api/agent/finish", {
      prepare: true,
      ensure_proxy: true,
      run_review: true,
      normalize_preset: null,
      delivery_preset: "streaming",
      run_delivery_check: true,
    });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = r.ok
      ? `Agent finish OK → ${r.export_path || "export"}`
      : `Agent finish: ${JSON.stringify(r).slice(0, 120)}`;
  } catch (e) {
    setProOut(`Agent finish failed: ${e}`);
    $("status-msg").textContent = `Agent finish failed: ${e}`;
  }
}

async function runAnalyzeTimeline() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  $("status-msg").textContent = "Analyze timeline…";
  try {
    const r = await postJson<Record<string, unknown>>("/api/analyze/timeline", {
      silence_threshold_db: -40,
      min_silence_seconds: 0.5,
    });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = "Timeline analysis done";
  } catch (e) {
    setProOut(`Analyze failed: ${e}`);
    $("status-msg").textContent = `Analyze failed: ${e}`;
  }
}

async function runAnalyzeBinAudio() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  if (!state.binMediaId) {
    $("status-msg").textContent = "Select media in bin";
    return;
  }
  try {
    const media = await getJson<{
      media?: Array<{ id?: string; abs_path?: string; path?: string }>;
    }>("/api/media");
    const m = (media.media || []).find((x) => x.id === state.binMediaId);
    const path = m?.abs_path || m?.path;
    if (!path) throw new Error("no path for bin media");
    $("status-msg").textContent = "Analyze audio…";
    const r = await postJson<Record<string, unknown>>("/api/analyze/audio", {
      path,
    });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = "Audio analysis done";
  } catch (e) {
    setProOut(`Analyze audio failed: ${e}`);
    $("status-msg").textContent = `Analyze audio failed: ${e}`;
  }
}

async function runSilenceCutsPlan() {
  if (!state.binMediaId) {
    $("status-msg").textContent = "Select media in bin for silence cuts";
    return;
  }
  try {
    const media = await getJson<{
      media?: Array<{ id?: string; abs_path?: string; path?: string }>;
    }>("/api/media");
    const m = (media.media || []).find((x) => x.id === state.binMediaId);
    const path = m?.abs_path || m?.path;
    if (!path) throw new Error("no path");
    const r = await postJson<Record<string, unknown>>(
      "/api/suggest/silence_cuts",
      { path },
    );
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = "Silence cuts plan ready";
  } catch (e) {
    setProOut(`Silence cuts failed: ${e}`);
    $("status-msg").textContent = `Silence cuts failed: ${e}`;
  }
}

async function runDetectScenes() {
  if (!state.binMediaId) {
    $("status-msg").textContent = "Select media in bin for scene detect";
    return;
  }
  try {
    const media = await getJson<{
      media?: Array<{ id?: string; abs_path?: string; path?: string }>;
    }>("/api/media");
    const m = (media.media || []).find((x) => x.id === state.binMediaId);
    const path = m?.abs_path || m?.path;
    if (!path) throw new Error("no path");
    const r = await postJson<Record<string, unknown>>("/api/detect/scenes", {
      path,
    });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = "Scene detect done";
  } catch (e) {
    setProOut(`Scenes failed: ${e}`);
    $("status-msg").textContent = `Scenes failed: ${e}`;
  }
}

async function exportFcpxmlUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  try {
    const r = await postJson<Record<string, unknown>>("/api/export/fcpxml", {});
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `FCPXML → ${r.path || "ok"}`;
  } catch (e) {
    $("status-msg").textContent = `FCPXML failed: ${e}`;
  }
}

async function exportMarkerSegmentsUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  $("status-msg").textContent = "Exporting marker segments (full encode)…";
  try {
    const r = await postJson<{
      count?: number;
      segment_count?: number;
      output_dir?: string;
      ok?: boolean;
    }>("/api/export/marker_segments", {
      name_prefix: "seg",
      include_tail: true,
    });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `MkrSeg · ${r.count ?? 0}/${r.segment_count ?? "?"} → ${r.output_dir || "export"}`;
  } catch (e) {
    setProOut(`MkrSeg failed: ${e}`);
    $("status-msg").textContent = `MkrSeg failed: ${e}`;
  }
}

async function exportTrackStemsUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  $("status-msg").textContent = "Exporting track stems (solo each track)…";
  try {
    const r = await postJson<{
      count?: number;
      stem_count?: number;
      output_dir?: string;
      ok?: boolean;
    }>("/api/export/track_stems", {
      name_prefix: "stem",
      audio_only: false,
    });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `Stems · ${r.count ?? 0}/${r.stem_count ?? "?"} → ${r.output_dir || "export"}`;
  } catch (e) {
    setProOut(`Stems failed: ${e}`);
    $("status-msg").textContent = `Stems failed: ${e}`;
  }
}

async function balanceGainsUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips to balance gains";
    return;
  }
  $("status-msg").textContent = `Balancing gains ×${ids.length}…`;
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/clips/balance_gains", {
      clip_ids: ids,
      target_db: 0,
      relative: true,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `BalG · ${r.count ?? ids.length} clips → avg 0 dB`;
  } catch (e) {
    setProOut(`BalG failed: ${e}`);
    $("status-msg").textContent = `BalG failed: ${e}`;
  }
}

async function matchGradeUi() {
  const ids = selectionList();
  if (ids.length < 2) {
    $("status-msg").textContent = "Select source + targets (first = grade source)";
    return;
  }
  const source = ids[0];
  const targets = ids.slice(1);
  $("status-msg").textContent = `Match grade → ${targets.length} clips…`;
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
      types?: string[];
    }>("/api/clips/match_grade", {
      source_clip_id: source,
      target_clip_ids: targets,
      replace: true,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `MatchG · ${r.count ?? targets.length} · ${(r.types || []).join(",") || "fx"}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`MatchG failed: ${e}`);
    $("status-msg").textContent = `MatchG failed: ${e}`;
  }
}

async function sequenceFromMediaUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  if (!state.binMediaId) {
    $("status-msg").textContent = "Select media in the bin (first piece)";
    return;
  }
  const ids = selectionList();
  let trackId = ids.length ? state.clips.get(ids[0])?.trackId : "";
  if (!trackId) {
    const tracks = (state as { tracks?: { id: string; kind?: string }[] }).tracks;
    const vt = Array.isArray(tracks)
      ? tracks.find((t) => t.kind === "video") || tracks[0]
      : null;
    trackId = vt?.id || "";
  }
  if (!trackId) {
    $("status-msg").textContent = "Need a target track (select a clip)";
    return;
  }
  // Gather all bin media ids from DOM if multi-select not available — use selected only
  const mediaIds = [state.binMediaId];
  $("status-msg").textContent = "Assembling sequence from bin media…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
      end_frame?: number;
    }>("/api/sequence/from_media", {
      media_ids: mediaIds,
      track_id: trackId,
      start_frame: playheadFrame(),
      clear_track: false,
      transition: null,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `Seq · ${r.count ?? "?"} clips · end f${r.end_frame ?? "?"}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`Seq failed: ${e}`);
    $("status-msg").textContent = `Seq failed: ${e}`;
  }
}

async function titleCardUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const content = window.prompt("Title text", "Opmiere");
  if (content == null) return;
  const trimmed = content.trim();
  if (!trimmed) {
    $("status-msg").textContent = "Empty title";
    return;
  }
  const ids = selectionList();
  let trackId = ids.length ? state.clips.get(ids[0])?.trackId : "";
  if (!trackId) {
    const tracks = (state as { tracks?: { id: string; kind?: string }[] }).tracks;
    const vt = Array.isArray(tracks)
      ? tracks.find((t) => t.kind === "video") || tracks[0]
      : null;
    trackId = vt?.id || "";
  }
  if (!trackId) {
    $("status-msg").textContent = "Need a video track";
    return;
  }
  $("status-msg").textContent = "Creating title card…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      clip_id?: string;
    }>("/api/title_card", {
      content: trimmed,
      track_id: trackId,
      start_frame: playheadFrame(),
      duration_frames: 90,
      position: "center",
      size: 64,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `Title · ${r.clip_id || "ok"} @ PH`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`Title failed: ${e}`);
    $("status-msg").textContent = `Title failed: ${e}`;
  }
}

function firstVideoTrackId(): string {
  const ids = selectionList();
  let trackId = ids.length ? state.clips.get(ids[0])?.trackId || "" : "";
  if (!trackId) {
    const tracks = (state as { tracks?: { id: string; kind?: string }[] }).tracks;
    const vt = Array.isArray(tracks)
      ? tracks.find((t) => t.kind === "video") || tracks[0]
      : null;
    trackId = vt?.id || "";
  }
  return trackId;
}

async function assembleUnusedUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const trackId = firstVideoTrackId();
  if (!trackId) {
    $("status-msg").textContent = "Need a video track";
    return;
  }
  $("status-msg").textContent = "Assembling unused bin media…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/sequence/assemble_unused", {
      track_id: trackId,
      kind: "video",
      start_frame: playheadFrame(),
      clear_track: false,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    await refreshMediaBin();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `Asm · ${r.count ?? 0} unused clips`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`Asm failed: ${e}`);
    $("status-msg").textContent = `Asm failed: ${e}`;
  }
}

async function roughCutUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const trackId = firstVideoTrackId();
  if (!trackId) {
    $("status-msg").textContent = "Need a video track";
    return;
  }
  $("status-msg").textContent = "Rough cut (assemble + dissolves + fades)…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      sequence?: { count?: number };
      fades?: { count?: number };
    }>("/api/edit/rough_cut", {
      track_id: trackId,
      use_unused: true,
      kind: "video",
      start_frame: playheadFrame(),
      clear_track: false,
      transition: "cross_dissolve",
      transition_frames: 10,
      apply_edge_fades: true,
      fade_frames: 6,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    await refreshMediaBin();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `Rough · seq ${r.sequence?.count ?? "?"} · fades ${r.fades?.count ?? "?"}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`Rough failed: ${e}`);
    $("status-msg").textContent = `Rough failed: ${e}`;
  }
}

async function edgeFadesUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const ids = selectionList();
  const body: Record<string, unknown> = {
    fade_in_frames: 6,
    fade_out_frames: 6,
    replace: true,
  };
  if (ids.length) {
    body.clip_ids = ids;
  } else {
    const trackId = firstVideoTrackId();
    if (!trackId) {
      $("status-msg").textContent = "Select clips or a track";
      return;
    }
    body.track_id = trackId;
  }
  $("status-msg").textContent = "Applying edge fades…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/clips/edge_fades", body);
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `Fades · ${r.count ?? 0} clips`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`Fades failed: ${e}`);
    $("status-msg").textContent = `Fades failed: ${e}`;
  }
}

async function voMusicDuckUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  $("status-msg").textContent = "Setting up VO/music duck…";
  try {
    const r = await postJson<{
      vo_track_id?: string;
      music_track_id?: string;
      agent_note?: string;
    }>("/api/mix/vo_music_duck", {
      music_gain_db: -6,
      ratio: 8,
      threshold_db: -30,
    });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `DuckVO · music ${r.music_track_id || "?"} under VO ${r.vo_track_id || "?"}`;
  } catch (e) {
    setProOut(`DuckVO failed: ${e}`);
    $("status-msg").textContent = `DuckVO failed: ${e}`;
  }
}

async function freezeAtMarkersUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const trackId = firstVideoTrackId();
  if (!trackId) {
    $("status-msg").textContent = "Select a clip on the source track";
    return;
  }
  $("status-msg").textContent = "Freezing at markers…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
      skipped_count?: number;
    }>("/api/freeze/at_markers", {
      track_id: trackId,
      duration_frames: 24,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `FrzM · ${r.count ?? 0}` +
      (r.skipped_count ? ` · skip ${r.skipped_count}` : "");
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`FrzM failed: ${e}`);
    $("status-msg").textContent = `FrzM failed: ${e}`;
  }
}

async function stillsAtMarkersUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  $("status-msg").textContent = "Exporting stills at markers…";
  try {
    const r = await postJson<{
      count?: number;
      output_dir?: string;
      ok?: boolean;
    }>("/api/export/stills_at_markers", {
      width: 1280,
      name_prefix: "still",
    });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `StillsM · ${r.count ?? 0} → ${r.output_dir || "export"}`;
  } catch (e) {
    setProOut(`StillsM failed: ${e}`);
    $("status-msg").textContent = `StillsM failed: ${e}`;
  }
}

async function importFcpxmlFile() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const picked = await pickImportFile({
    title: "Import FCPXML",
    extensions: ["fcpxml", "xml"],
  });
  if (!picked) return;
  $("status-msg").textContent = "Importing FCPXML…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
      skipped_count?: number;
      imported_media_count?: number;
    }>("/api/import/fcpxml", {
      path: picked.path || null,
      text: picked.text || null,
      clear_track: false,
      import_missing_media: true,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    await refreshMediaBin();
    $("status-msg").textContent =
      `FCPXML in · ${r.count ?? "?"} clips` +
      (r.imported_media_count ? ` · +${r.imported_media_count} media` : "") +
      (r.skipped_count ? ` · skip ${r.skipped_count}` : "");
    scheduleProxyRefresh();
  } catch (e) {
    $("status-msg").textContent = `FCPXML import failed: ${e}`;
  }
}

async function exportOtioUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  try {
    const r = await postJson<Record<string, unknown>>("/api/export/otio", {});
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `OTIO → ${r.path || "ok"}`;
  } catch (e) {
    $("status-msg").textContent = `OTIO failed: ${e}`;
  }
}

async function exportManifestUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  try {
    const r = await postJson<{
      path?: string;
      clip_count?: number;
      marker_count?: number;
    }>("/api/export/manifest", {});
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `Manifest · ${r.clip_count ?? "?"} clips · ${r.marker_count ?? "?"} mkr → ${r.path || "ok"}`;
  } catch (e) {
    $("status-msg").textContent = `Manifest failed: ${e}`;
  }
}

async function importManifestUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const picked = await pickImportFile({
    title: "Import edit manifest",
    extensions: ["json"],
  });
  if (!picked) return;
  $("status-msg").textContent = "Importing manifest…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
      markers_imported?: number;
      skipped_count?: number;
    }>("/api/import/manifest", {
      path: picked.path || null,
      text: picked.text || null,
      clear: true,
      import_missing_media: true,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    await refreshMediaBin();
    await refreshMarkers();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `ImpMan · ${r.count ?? "?"} clips · ${r.markers_imported ?? 0} mkr` +
      (r.skipped_count ? ` · skip ${r.skipped_count}` : "");
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`ImpMan failed: ${e}`);
    $("status-msg").textContent = `ImpMan failed: ${e}`;
  }
}

async function ensureAllProxiesUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  $("status-msg").textContent = "Building all media proxies…";
  try {
    const r = await postJson<{
      count?: number;
      skipped_count?: number;
    }>("/api/media/proxies_all", {
      height: 480,
      force: false,
    });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `PxAll · ${r.count ?? 0}` +
      (r.skipped_count ? ` · skip ${r.skipped_count}` : "");
  } catch (e) {
    setProOut(`PxAll failed: ${e}`);
    $("status-msg").textContent = `PxAll failed: ${e}`;
  }
}

async function relinkOfflineUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const dir = await pickProjectFolder({ title: "Folder containing offline media files" });
  if (!dir) return;
  $("status-msg").textContent = "Relinking offline media…";
  try {
    const r = await postJson<{
      count?: number;
      still_offline_count?: number;
    }>("/api/media/relink_offline", {
      search_dirs: [dir],
      recursive: true,
      re_probe: true,
    });
    setProOut(JSON.stringify(r, null, 2));
    await refreshMediaBin();
    $("status-msg").textContent =
      `Relink · ${r.count ?? 0}` +
      (r.still_offline_count ? ` · still ${r.still_offline_count}` : "");
  } catch (e) {
    setProOut(`Relink failed: ${e}`);
    $("status-msg").textContent = `Relink failed: ${e}`;
  }
}

async function exportHandoffUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const dir = await pickProjectFolder({ title: "Handoff package output folder" });
  if (!dir) return;
  $("status-msg").textContent = "Writing handoff package…";
  try {
    const r = await postJson<{
      path?: string;
      count?: number;
    }>("/api/export/handoff", {
      out_dir: dir,
      include_manifest: true,
      include_chapters: true,
      include_preflight: true,
      include_otio: false,
      include_media_status: true,
    });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `Handoff · ${r.count ?? 0} files → ${r.path ?? dir}`;
  } catch (e) {
    setProOut(`Handoff failed: ${e}`);
    $("status-msg").textContent = `Handoff failed: ${e}`;
  }
}

async function collectBundleUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const dest = await pickNewProjectPath({
    title: "Collect Files — new .opm path",
    defaultPath: "collected.opm",
  });
  if (!dest) return;
  $("status-msg").textContent = "Collecting media into new bundle…";
  try {
    const r = await postJson<{
      path?: string;
      clip_count?: number;
      imported_media_count?: number;
      skipped_count?: number;
    }>("/api/export/collect_bundle", {
      dest_path: dest,
      used_only: true,
      conform: true,
    });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `Collect · ${r.clip_count ?? "?"} clips · med ${r.imported_media_count ?? "?"}` +
      (r.skipped_count ? ` · skip ${r.skipped_count}` : "") +
      ` → ${r.path ?? dest}`;
  } catch (e) {
    setProOut(`Collect failed: ${e}`);
    $("status-msg").textContent = `Collect failed: ${e}`;
  }
}

async function importImageSequenceUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const dir = await pickProjectFolder({ title: "Image sequence folder" });
  if (!dir) return;
  $("status-msg").textContent = "Encoding image sequence…";
  try {
    const placeTrack = trackForKind("video");
    const r = await postJson<{
      media_id?: string;
      clip_id?: string;
      duration_frames?: number;
      frame_count?: number;
      timeline?: TimelineView;
    }>("/api/import/image_sequence", {
      path: dir,
      fps: null,
      place_track_id: placeTrack,
      start: playheadFrame(),
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    await refreshMediaBin();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `ImgSeq · ${r.frame_count ?? "?"} frames · ${r.duration_frames ?? "?"}f` +
      (r.clip_id ? " · placed" : "");
  } catch (e) {
    setProOut(`ImgSeq failed: ${e}`);
    $("status-msg").textContent = `ImgSeq failed: ${e}`;
  }
}

async function importFolderUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const dir = await pickProjectFolder({ title: "Import media folder" });
  if (!dir) return;
  $("status-msg").textContent = "Importing folder…";
  try {
    const r = await postJson<{
      count?: number;
      error_count?: number;
      timeline?: TimelineView;
    }>("/api/import/folder", {
      folder: dir,
      recursive: false,
      place: true,
      rough_cut: false,
      max_files: 100,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    await refreshMediaBin();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `ImpDir · ${r.count ?? 0}` +
      (r.error_count ? ` · err ${r.error_count}` : "");
  } catch (e) {
    setProOut(`ImpDir failed: ${e}`);
    $("status-msg").textContent = `ImpDir failed: ${e}`;
  }
}

async function exportFrameSequenceUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const dir = await pickProjectFolder({ title: "Frame sequence output folder" });
  if (!dir) return;
  $("status-msg").textContent = "Exporting frame sequence…";
  try {
    const r = await postJson<{
      count?: number;
      path?: string;
      span_frames?: number;
    }>("/api/export/frame_sequence", {
      out_dir: dir,
      use_work_area: false,
      pattern: "frame_%06d.png",
      max_frames: 90,
      height: 360,
    });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `Frames · ${r.count ?? 0} png · span ${r.span_frames ?? "?"} → ${r.path ?? dir}`;
  } catch (e) {
    setProOut(`Frames failed: ${e}`);
    $("status-msg").textContent = `Frames failed: ${e}`;
  }
}

async function detachAudioAllUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  $("status-msg").textContent = "Detaching audio on video clips…";
  try {
    const r = await postJson<{
      count?: number;
      skipped_count?: number;
      timeline?: TimelineView;
    }>("/api/edit/detach_audio_all", {
      track_id: trackForKind("video"),
      link: true,
      only_with_audio: true,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `DetAll · ${r.count ?? 0}` +
      (r.skipped_count ? ` · skip ${r.skipped_count}` : "");
  } catch (e) {
    setProOut(`DetAll failed: ${e}`);
    $("status-msg").textContent = `DetAll failed: ${e}`;
  }
}

async function jlOffsetUi(offset: number) {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const clipId = [...state.selected][0];
  if (!clipId) {
    $("status-msg").textContent = "Select a video clip first";
    return;
  }
  $("status-msg").textContent = `J/L offset ${offset}f…`;
  try {
    const r = await postJson<{
      count?: number;
      timeline?: TimelineView;
    }>("/api/edit/j_l_offset", {
      video_clip_id: clipId,
      offset_frames: offset,
      relative: false,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `JL · offset ${offset}f · peers ${r.count ?? 0}`;
  } catch (e) {
    setProOut(`JL failed: ${e}`);
    $("status-msg").textContent = `JL failed: ${e}`;
  }
}

async function importOtioFile() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const picked = await pickImportFile({
    title: "Import OTIO JSON",
    extensions: ["json", "otio"],
  });
  if (!picked) return;
  $("status-msg").textContent = "Importing OTIO…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
      skipped_count?: number;
      imported_media_count?: number;
    }>("/api/import/otio", {
      path: picked.path || null,
      text: picked.text || null,
      clear_tracks: false,
      import_missing_media: true,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    await refreshMediaBin();
    $("status-msg").textContent =
      `OTIO in · ${r.count ?? "?"} clips` +
      (r.imported_media_count ? ` · +${r.imported_media_count} media` : "") +
      (r.skipped_count ? ` · skip ${r.skipped_count}` : "");
    scheduleProxyRefresh();
  } catch (e) {
    $("status-msg").textContent = `OTIO import failed: ${e}`;
  }
}

async function interchangeCatalogUi() {
  try {
    const r = await getJson<Record<string, unknown>>("/api/interchange");
    setProOut(JSON.stringify(r, null, 2));
    const exp = Array.isArray(r.export) ? r.export.length : "?";
    const imp = Array.isArray(r.import) ? r.import.length : "?";
    $("status-msg").textContent = `Interchange · export ${exp} · import ${imp}`;
  } catch (e) {
    $("status-msg").textContent = `Interchange catalog failed: ${e}`;
  }
}

async function exportStillUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const frame = playheadFrame();
  try {
    const r = await postJson<Record<string, unknown>>("/api/export/still", {
      frame,
      width: 1280,
    });
    setProOut(JSON.stringify(r, null, 2));
    const p = String(r.path || r.output_path || "");
    // also refresh program still via frame API
    try {
      const q = new URLSearchParams({
        t: String(frame / Math.max(1, state.fps)),
        width: "640",
        engine: "auto",
        _: String(Date.now()),
      });
      const img = $("program-img") as HTMLImageElement;
      img.src = `${API_BASE}/api/preview/frame.jpg?${q.toString()}`;
      showProgramImage(img.src);
    } catch {
      /* ignore */
    }
    $("status-msg").textContent = `Still f${frame} → ${p || "ok"}`;
  } catch (e) {
    $("status-msg").textContent = `Still failed: ${e}`;
  }
}

async function exportGifUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const start = playheadFrame() / Math.max(1, state.fps);
  $("status-msg").textContent = "Exporting GIF…";
  try {
    const r = await postJson<Record<string, unknown>>("/api/export/gif", {
      start_seconds: start,
      end_seconds: start + 3,
      fps: 12,
      width: 480,
      max_duration_seconds: 6,
    });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `GIF → ${String(r.path || "ok")}`;
  } catch (e) {
    setProOut(`GIF failed: ${e}`);
    $("status-msg").textContent = `GIF failed: ${e}`;
  }
}

async function exportWorkAreaGifUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  $("status-msg").textContent = "Exporting work-area GIF…";
  try {
    const r = await postJson<Record<string, unknown>>("/api/export/work_area_gif", {
      fps: 12,
      width: 480,
      max_duration_seconds: 12,
    });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `WA-GIF → ${String(r.path || "ok")}`;
  } catch (e) {
    setProOut(`WA-GIF failed: ${e}`);
    $("status-msg").textContent = `WA-GIF failed: ${e}`;
  }
}

async function solidUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const color = window.prompt("Solid color (#hex or name)", "#000000");
  if (color == null || !color.trim()) return;
  const durRaw = window.prompt("Duration frames", "30");
  if (durRaw == null) return;
  const duration_frames = Math.max(1, parseInt(durRaw, 10) || 30);
  $("status-msg").textContent = "Adding solid…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      clip_id?: string;
    }>("/api/edit/solid", {
      color: color.trim(),
      duration_frames,
      append: true,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `Solid · ${r.clip_id || "ok"}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`Solid failed: ${e}`);
    $("status-msg").textContent = `Solid failed: ${e}`;
  }
}

async function kenBurnsUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select a clip for Ken Burns";
    return;
  }
  $("status-msg").textContent = "Applying Ken Burns…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      clip_id?: string;
    }>("/api/clip/ken_burns", {
      clip_id: ids[0],
      zoom_start: 1.0,
      zoom_end: 1.15,
      replace: true,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `KB · ${r.clip_id || ids[0]}`;
  } catch (e) {
    setProOut(`KB failed: ${e}`);
    $("status-msg").textContent = `KB failed: ${e}`;
  }
}

async function kenBurnsImagesUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  $("status-msg").textContent = "Ken Burns on stills…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/edit/ken_burns_images", {
      zoom_end: 1.12,
      replace: true,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `KB-img · ${r.count ?? 0} stills`;
  } catch (e) {
    setProOut(`KB-img failed: ${e}`);
    $("status-msg").textContent = `KB-img failed: ${e}`;
  }
}

async function vignetteUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select a clip for vignette";
    return;
  }
  $("status-msg").textContent = "Applying vignette…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      clip_id?: string;
    }>("/api/clip/vignette", {
      clip_id: ids[0],
      strength: 0.45,
      replace: true,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `Vig · ${r.clip_id || ids[0]}`;
  } catch (e) {
    setProOut(`Vig failed: ${e}`);
    $("status-msg").textContent = `Vig failed: ${e}`;
  }
}

async function exportClipGifUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select a clip for ClipGIF";
    return;
  }
  $("status-msg").textContent = "Exporting clip GIF…";
  try {
    const r = await postJson<Record<string, unknown>>("/api/export/clip_gif", {
      clip_id: ids[0],
      fps: 12,
      width: 480,
      max_duration_seconds: 10,
    });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `ClipGIF → ${String(r.path || "ok")}`;
  } catch (e) {
    setProOut(`ClipGIF failed: ${e}`);
    $("status-msg").textContent = `ClipGIF failed: ${e}`;
  }
}

async function filmGrainUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select a clip for film grain";
    return;
  }
  $("status-msg").textContent = "Applying film grain…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      clip_id?: string;
    }>("/api/clip/film_grain", {
      clip_id: ids[0],
      amount: 12,
      replace: true,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `Grain · ${r.clip_id || ids[0]}`;
  } catch (e) {
    setProOut(`Grain failed: ${e}`);
    $("status-msg").textContent = `Grain failed: ${e}`;
  }
}

async function blurUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select a clip for blur";
    return;
  }
  $("status-msg").textContent = "Applying blur…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      clip_id?: string;
    }>("/api/clip/blur", {
      clip_id: ids[0],
      amount: 5,
      replace: true,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `Blur · ${r.clip_id || ids[0]}`;
  } catch (e) {
    setProOut(`Blur failed: ${e}`);
    $("status-msg").textContent = `Blur failed: ${e}`;
  }
}

async function sharpenUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select a clip for sharpen";
    return;
  }
  $("status-msg").textContent = "Applying sharpen…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      clip_id?: string;
    }>("/api/clip/sharpen", {
      clip_id: ids[0],
      amount: 1.0,
      replace: true,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `Sharp · ${r.clip_id || ids[0]}`;
  } catch (e) {
    setProOut(`Sharp failed: ${e}`);
    $("status-msg").textContent = `Sharp failed: ${e}`;
  }
}

async function glowUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select a clip for glow";
    return;
  }
  $("status-msg").textContent = "Applying glow…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      clip_id?: string;
    }>("/api/clip/glow", {
      clip_id: ids[0],
      amount: 8,
      intensity: 0.4,
      replace: true,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `Glow · ${r.clip_id || ids[0]}`;
  } catch (e) {
    setProOut(`Glow failed: ${e}`);
    $("status-msg").textContent = `Glow failed: ${e}`;
  }
}

async function chromaKeyUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select overlay clip for chroma key";
    return;
  }
  $("status-msg").textContent = "Applying chroma key…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      clip_id?: string;
    }>("/api/clip/chroma_key", {
      clip_id: ids[0],
      color: "green",
      similarity: 0.15,
      blend: 0.05,
      replace: true,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `CKey · ${r.clip_id || ids[0]}`;
  } catch (e) {
    setProOut(`CKey failed: ${e}`);
    $("status-msg").textContent = `CKey failed: ${e}`;
  }
}

async function lumaKeyUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clip for luma key";
    return;
  }
  $("status-msg").textContent = "Applying luma key…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      clip_id?: string;
    }>("/api/clip/luma_key", {
      clip_id: ids[0],
      threshold: 0.1,
      tolerance: 0.1,
      replace: true,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `LKey · ${r.clip_id || ids[0]}`;
  } catch (e) {
    setProOut(`LKey failed: ${e}`);
    $("status-msg").textContent = `LKey failed: ${e}`;
  }
}

async function whiteBalanceUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clip for white balance";
    return;
  }
  $("status-msg").textContent = "Applying white balance…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      clip_id?: string;
    }>("/api/clip/white_balance", {
      clip_id: ids[0],
      temperature: 5600,
      mix: 1.0,
      replace: true,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `WB · ${r.clip_id || ids[0]}`;
  } catch (e) {
    setProOut(`WB failed: ${e}`);
    $("status-msg").textContent = `WB failed: ${e}`;
  }
}

async function exportWorkAreaWebmUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  $("status-msg").textContent = "Exporting work-area WebM…";
  try {
    const r = await postJson<Record<string, unknown>>("/api/export/work_area_webm", {
      crf: 32,
      width: 720,
    });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `WA-WebM → ${String(r.path || "ok")}`;
  } catch (e) {
    setProOut(`WA-WebM failed: ${e}`);
    $("status-msg").textContent = `WA-WebM failed: ${e}`;
  }
}

async function shapeMaskUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clip for shape mask";
    return;
  }
  $("status-msg").textContent = "Applying shape mask…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      clip_id?: string;
    }>("/api/clip/shape_mask", {
      clip_id: ids[0],
      shape: "circle",
      size: 0.55,
      feather: 0.08,
      replace: true,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `Mask · ${r.clip_id || ids[0]}`;
  } catch (e) {
    setProOut(`Mask failed: ${e}`);
    $("status-msg").textContent = `Mask failed: ${e}`;
  }
}

async function curvesUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clip for curves";
    return;
  }
  $("status-msg").textContent = "Applying curves…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      clip_id?: string;
    }>("/api/clip/curves", {
      clip_id: ids[0],
      preset: "increase_contrast",
      replace: true,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `Curves · ${r.clip_id || ids[0]}`;
  } catch (e) {
    setProOut(`Curves failed: ${e}`);
    $("status-msg").textContent = `Curves failed: ${e}`;
  }
}

async function exportClipWebmUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select a clip for ClipWebM";
    return;
  }
  $("status-msg").textContent = "Exporting clip WebM…";
  try {
    const r = await postJson<Record<string, unknown>>("/api/export/clip_webm", {
      clip_id: ids[0],
      crf: 32,
      width: 720,
    });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `ClipWebM → ${String(r.path || "ok")}`;
  } catch (e) {
    setProOut(`ClipWebM failed: ${e}`);
    $("status-msg").textContent = `ClipWebM failed: ${e}`;
  }
}

async function compressionUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select a clip for compression";
    return;
  }
  $("status-msg").textContent = "Applying compression…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      clip_id?: string;
    }>("/api/clip/compression", {
      clip_id: ids[0],
      ratio: 4,
      threshold_db: -18,
      replace: true,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `Comp · ${r.clip_id || ids[0]}`;
  } catch (e) {
    setProOut(`Comp failed: ${e}`);
    $("status-msg").textContent = `Comp failed: ${e}`;
  }
}

async function audioEqUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select a clip for EQ";
    return;
  }
  $("status-msg").textContent = "Applying EQ…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      clip_id?: string;
    }>("/api/clip/audio_eq", {
      clip_id: ids[0],
      frequency_hz: 1000,
      gain_db: 3,
      q: 1,
      replace: false,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `EQ · ${r.clip_id || ids[0]}`;
  } catch (e) {
    setProOut(`EQ failed: ${e}`);
    $("status-msg").textContent = `EQ failed: ${e}`;
  }
}

async function exportClipAudioUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select a clip for ClipAud";
    return;
  }
  $("status-msg").textContent = "Exporting clip audio…";
  try {
    const r = await postJson<Record<string, unknown>>("/api/export/clip_audio", {
      clip_id: ids[0],
    });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `ClipAud → ${String(r.path || "ok")}`;
  } catch (e) {
    setProOut(`ClipAud failed: ${e}`);
    $("status-msg").textContent = `ClipAud failed: ${e}`;
  }
}

async function noiseReductionUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select a clip for NR";
    return;
  }
  $("status-msg").textContent = "Applying noise reduction…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      clip_id?: string;
    }>("/api/clip/noise_reduction", {
      clip_id: ids[0],
      amount: 12,
      replace: true,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `NR-c · ${r.clip_id || ids[0]}`;
  } catch (e) {
    setProOut(`NR failed: ${e}`);
    $("status-msg").textContent = `NR failed: ${e}`;
  }
}

async function exportClipMp4Ui() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select a clip for ClipMP4";
    return;
  }
  $("status-msg").textContent = "Exporting clip MP4…";
  try {
    const r = await postJson<Record<string, unknown>>("/api/export/clip_mp4", {
      clip_id: ids[0],
    });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `ClipMP4 → ${String(r.path || "ok")}`;
  } catch (e) {
    setProOut(`ClipMP4 failed: ${e}`);
    $("status-msg").textContent = `ClipMP4 failed: ${e}`;
  }
}

async function countdownUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  $("status-msg").textContent = "Adding countdown…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      total_frames?: number;
      cards?: unknown[];
    }>("/api/edit/countdown", {
      seconds: 3,
      ripple_all_tracks: true,
      size: 96,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `3-2-1 · ${r.total_frames ?? "?"}f`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`Countdown failed: ${e}`);
    $("status-msg").textContent = `Countdown failed: ${e}`;
  }
}

async function speedRippleUi(speed: number) {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select a clip for speed ripple";
    return;
  }
  $("status-msg").textContent = `Speed ${speed}× + ripple…`;
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      clip_id?: string;
      delta_frames?: number;
    }>("/api/clip/speed_ripple", {
      clip_id: ids[0],
      speed,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `${speed}×R · Δ${r.delta_frames ?? "?"}f · ${r.clip_id || ids[0]}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`SpeedR failed: ${e}`);
    $("status-msg").textContent = `SpeedR failed: ${e}`;
  }
}

async function exportClipStillUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select a clip for ClipStill";
    return;
  }
  $("status-msg").textContent = "Exporting clip still…";
  try {
    const r = await postJson<Record<string, unknown>>("/api/export/clip_still", {
      clip_id: ids[0],
      at: "mid",
      width: 1280,
    });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `ClipStill → ${String(r.path || "ok")}`;
  } catch (e) {
    setProOut(`ClipStill failed: ${e}`);
    $("status-msg").textContent = `ClipStill failed: ${e}`;
  }
}

async function freezeClipMidUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select a clip for FrzMid";
    return;
  }
  $("status-msg").textContent = "Freezing mid-frame…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      clip_id?: string;
    }>("/api/clip/freeze_mid", {
      clip_id: ids[0],
      duration_frames: 30,
      insert: true,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `FrzMid · ${r.clip_id || "ok"}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`FrzMid failed: ${e}`);
    $("status-msg").textContent = `FrzMid failed: ${e}`;
  }
}

async function exportClipsPackUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips for Pack export";
    return;
  }
  $("status-msg").textContent = "Exporting clips pack…";
  try {
    const r = await postJson<Record<string, unknown>>("/api/export/clips_pack", {
      clip_ids: ids,
      prefix: "clip",
    });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `Pack · ${String(r.count ?? 0)}/${String(r.total ?? ids.length)}`;
  } catch (e) {
    setProOut(`Pack failed: ${e}`);
    $("status-msg").textContent = `Pack failed: ${e}`;
  }
}

async function slateUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const title = window.prompt("Slate title", "SLATE");
  if (title == null) return;
  const subtitle = window.prompt("Subtitle (optional)", "") ?? "";
  $("status-msg").textContent = "Adding slate…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      clip_id?: string;
    }>("/api/edit/slate", {
      title: title.trim() || "SLATE",
      subtitle: subtitle.trim() || null,
      duration_frames: 90,
      ripple_all_tracks: true,
      append: false,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `Slate · ${r.clip_id || "ok"}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`Slate failed: ${e}`);
    $("status-msg").textContent = `Slate failed: ${e}`;
  }
}

async function closeGapsAllUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  $("status-msg").textContent = "Closing gaps on all tracks…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/edit/close_gaps_all", {
      from_frame: 0,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `CloseAll · ${r.count ?? 0} tracks`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`CloseAll failed: ${e}`);
    $("status-msg").textContent = `CloseAll failed: ${e}`;
  }
}

async function exportTrackOnlyUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select a clip (uses its track)";
    return;
  }
  $("status-msg").textContent = "Exporting track only…";
  try {
    const r = await postJson<Record<string, unknown>>("/api/export/track_only", {
      clip_id: ids[0],
    });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `TrkOnly → ${String(r.path || "ok")}`;
  } catch (e) {
    setProOut(`TrkOnly failed: ${e}`);
    $("status-msg").textContent = `TrkOnly failed: ${e}`;
  }
}

async function exportSelectionMp4Ui() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips for SelMP4";
    return;
  }
  $("status-msg").textContent = "Exporting selection MP4…";
  try {
    const r = await postJson<Record<string, unknown>>("/api/export/selection_mp4", {
      clip_ids: ids,
    });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `SelMP4 → ${String(r.path || "ok")}`;
  } catch (e) {
    setProOut(`SelMP4 failed: ${e}`);
    $("status-msg").textContent = `SelMP4 failed: ${e}`;
  }
}

async function exportWorkAreaMp4Ui() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  $("status-msg").textContent = "Exporting work-area MP4…";
  try {
    const r = await postJson<Record<string, unknown>>("/api/export/work_area_mp4", {});
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `WA-MP4 → ${String(r.path || "ok")}`;
  } catch (e) {
    setProOut(`WA-MP4 failed: ${e}`);
    $("status-msg").textContent = `WA-MP4 failed: ${e}`;
  }
}

async function liftClipUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select a clip to lift";
    return;
  }
  $("status-msg").textContent = "Lifting clip…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      deleted_id?: string;
    }>("/api/edit/lift_clip", { clip_id: ids[0] });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `LiftC · ${r.deleted_id || ids[0]}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`LiftC failed: ${e}`);
    $("status-msg").textContent = `LiftC failed: ${e}`;
  }
}

async function rippleDeleteSelectionUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips to ripple-delete";
    return;
  }
  $("status-msg").textContent = "Ripple-deleting selection…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/edit/ripple_delete_selection", { clip_ids: ids });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `RipSel · ${r.count ?? ids.length}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`RipSel failed: ${e}`);
    $("status-msg").textContent = `RipSel failed: ${e}`;
  }
}

async function copyEffectsUi() {
  const ids = selectionList();
  if (ids.length < 2) {
    $("status-msg").textContent = "Select source + target clips (source first)";
    return;
  }
  $("status-msg").textContent = "Copying effects…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/clip/copy_effects", {
      source_clip_id: ids[0],
      target_clip_ids: ids.slice(1),
      replace: true,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `CopyFX · ${r.count ?? 0} targets`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`CopyFX failed: ${e}`);
    $("status-msg").textContent = `CopyFX failed: ${e}`;
  }
}

async function exportClipsStillsPackUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips for stills pack";
    return;
  }
  $("status-msg").textContent = "Exporting stills pack…";
  try {
    const r = await postJson<Record<string, unknown>>("/api/export/clips_stills_pack", {
      clip_ids: ids,
      at: "mid",
      width: 1280,
    });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `StillsP · ${String(r.count ?? 0)}/${String(r.total ?? ids.length)}`;
  } catch (e) {
    setProOut(`StillsP failed: ${e}`);
    $("status-msg").textContent = `StillsP failed: ${e}`;
  }
}

async function joinClipsUi() {
  const ids = selectionList();
  if (ids.length < 2) {
    $("status-msg").textContent = "Select two adjacent clips to join";
    return;
  }
  $("status-msg").textContent = "Joining clips…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      clip_id?: string;
    }>("/api/clips/join", {
      clip_id_a: ids[0],
      clip_id_b: ids[1],
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `Join · ${r.clip_id || "ok"}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`Join failed: ${e}`);
    $("status-msg").textContent = `Join failed: ${e}`;
  }
}

async function pastePositionUi() {
  const ids = selectionList();
  if (ids.length < 2) {
    $("status-msg").textContent = "Select source + targets (source first)";
    return;
  }
  $("status-msg").textContent = "Pasting position…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/clip/paste_position", {
      source_clip_id: ids[0],
      target_clip_ids: ids.slice(1),
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `PastePos · ${r.count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`PastePos failed: ${e}`);
    $("status-msg").textContent = `PastePos failed: ${e}`;
  }
}

async function flipHSelectionUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips to flip";
    return;
  }
  $("status-msg").textContent = "Flipping…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/clip/set_clips_flip", {
      clip_ids: ids,
      horizontal: true,
      vertical: null,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `FlipH · ${r.count ?? ids.length}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`FlipH failed: ${e}`);
    $("status-msg").textContent = `FlipH failed: ${e}`;
  }
}

async function pasteCropUi() {
  const ids = selectionList();
  if (ids.length < 2) {
    $("status-msg").textContent = "Select source + targets (source first)";
    return;
  }
  $("status-msg").textContent = "Pasting crop…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/clip/paste_crop", {
      source_clip_id: ids[0],
      target_clip_ids: ids.slice(1),
      replace: true,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `PasteCrop · ${r.count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`PasteCrop failed: ${e}`);
    $("status-msg").textContent = `PasteCrop failed: ${e}`;
  }
}

async function pasteFromClipUi() {
  const ids = selectionList();
  if (ids.length < 2) {
    $("status-msg").textContent = "Select source + targets (source first)";
    return;
  }
  $("status-msg").textContent = "Pasting from source clip…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/clip/paste_from_clip", {
      source_clip_id: ids[0],
      target_clip_ids: ids.slice(1),
      effects: true,
      attributes: true,
      color: true,
      replace_effects: true,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `PasteFrom · ${r.count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`PasteFrom failed: ${e}`);
    $("status-msg").textContent = `PasteFrom failed: ${e}`;
  }
}

async function duplicateSelectionUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips to duplicate";
    return;
  }
  $("status-msg").textContent = "Duplicating selection…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/edit/duplicate_selection", {
      clip_ids: ids,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `DupSel · ${r.count ?? ids.length}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`DupSel failed: ${e}`);
    $("status-msg").textContent = `DupSel failed: ${e}`;
  }
}

async function exportSelectionAudioUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips for SelAud";
    return;
  }
  $("status-msg").textContent = "Exporting selection audio…";
  try {
    const r = await postJson<Record<string, unknown>>("/api/export/selection_audio", {
      clip_ids: ids,
    });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `SelAud → ${String(r.path || "ok")}`;
  } catch (e) {
    setProOut(`SelAud failed: ${e}`);
    $("status-msg").textContent = `SelAud failed: ${e}`;
  }
}

async function splitSelectionUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips to razor";
    return;
  }
  const at = playheadFrame();
  $("status-msg").textContent = `Splitting selection @ f${at}…`;
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/edit/split_selection", {
      clip_ids: ids,
      at_frame: at,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `SplitSel · ${r.count ?? 0} @ f${at}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`SplitSel failed: ${e}`);
    $("status-msg").textContent = `SplitSel failed: ${e}`;
  }
}

async function markersFromSelectionUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips for markers";
    return;
  }
  $("status-msg").textContent = "Adding selection markers…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/markers/from_selection", {
      clip_ids: ids,
      edge: "start",
      prefix: "Sel ",
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `MkrSel · ${r.count ?? 0}`;
  } catch (e) {
    setProOut(`MkrSel failed: ${e}`);
    $("status-msg").textContent = `MkrSel failed: ${e}`;
  }
}

async function selectionSpanUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips for span";
    return;
  }
  try {
    const r = await postJson<Record<string, unknown>>("/api/edit/selection_span", {
      clip_ids: ids,
    });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `Span f${String(r.start_frame ?? "?")}–${String(r.end_frame ?? "?")} (${String(r.duration_frames ?? "?")}f)`;
  } catch (e) {
    setProOut(`Span failed: ${e}`);
    $("status-msg").textContent = `Span failed: ${e}`;
  }
}

async function exportSelectionGifUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips for SelGIF";
    return;
  }
  $("status-msg").textContent = "Exporting selection GIF…";
  try {
    const r = await postJson<Record<string, unknown>>("/api/export/selection_gif", {
      clip_ids: ids,
      fps: 12,
      width: 480,
      max_duration_seconds: 10,
    });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `SelGIF → ${String(r.path || "ok")}`;
  } catch (e) {
    setProOut(`SelGIF failed: ${e}`);
    $("status-msg").textContent = `SelGIF failed: ${e}`;
  }
}

async function exportSelectionWebmUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips for SelWebM";
    return;
  }
  $("status-msg").textContent = "Exporting selection WebM…";
  try {
    const r = await postJson<Record<string, unknown>>("/api/export/selection_webm", {
      clip_ids: ids,
      crf: 32,
      width: 720,
    });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `SelWebM → ${String(r.path || "ok")}`;
  } catch (e) {
    setProOut(`SelWebM failed: ${e}`);
    $("status-msg").textContent = `SelWebM failed: ${e}`;
  }
}

async function trimSelectionPlayheadUi(edge: "head" | "tail") {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips to trim";
    return;
  }
  const ph = playheadFrame();
  $("status-msg").textContent = `Trimming ${edge} @ f${ph}…`;
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/edit/trim_selection_playhead", {
      clip_ids: ids,
      playhead_frame: ph,
      edge,
      mode: "ripple",
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `Trim${edge === "head" ? "Q" : "W"} · ${r.count ?? 0} @ f${ph}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`Trim failed: ${e}`);
    $("status-msg").textContent = `Trim failed: ${e}`;
  }
}

async function workAreaFromSelectionExportUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips for WA←Sel";
    return;
  }
  $("status-msg").textContent = "Work area from selection + export…";
  try {
    const r = await postJson<Record<string, unknown>>(
      "/api/export/work_area_from_selection",
      { clip_ids: ids },
    );
    if ((r as { timeline?: TimelineView }).timeline) {
      applyTimelineView((r as { timeline: TimelineView }).timeline);
    } else {
      await refresh();
    }
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `WA←Sel → ${String(r.path || "ok")}`;
  } catch (e) {
    setProOut(`WA←Sel failed: ${e}`);
    $("status-msg").textContent = `WA←Sel failed: ${e}`;
  }
}

async function extendToNextUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select a clip to extend";
    return;
  }
  $("status-msg").textContent = "Extending to next…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      extended_frames?: number;
    }>("/api/clip/extend_to_next", { clip_id: ids[0] });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `Ext→ · +${r.extended_frames ?? 0}f`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`Ext→ failed: ${e}`);
    $("status-msg").textContent = `Ext→ failed: ${e}`;
  }
}

async function reverseSelectionUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips to reverse";
    return;
  }
  $("status-msg").textContent = "Reversing selection…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/edit/reverse_selection", {
      clip_ids: ids,
      replace: true,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `RevSel · ${r.count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`RevSel failed: ${e}`);
    $("status-msg").textContent = `RevSel failed: ${e}`;
  }
}

async function selectionSpeedRippleUi(speed: number) {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips for speed ripple";
    return;
  }
  $("status-msg").textContent = `Speed ${speed}× + ripple selection…`;
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/edit/selection_speed_ripple", {
      clip_ids: ids,
      speed,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `${speed}×Sel · ${r.count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`SpeedSel failed: ${e}`);
    $("status-msg").textContent = `SpeedSel failed: ${e}`;
  }
}

async function transitionsSelectionUi() {
  const ids = selectionList();
  if (ids.length < 2) {
    $("status-msg").textContent = "Select 2+ adjacent clips for xfade";
    return;
  }
  $("status-msg").textContent = "Adding selection transitions…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/edit/transitions_selection", {
      clip_ids: ids,
      transition_type: "cross_dissolve",
      duration_frames: 12,
      require_both_selected: true,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `XfadeSel · ${r.count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`XfadeSel failed: ${e}`);
    $("status-msg").textContent = `XfadeSel failed: ${e}`;
  }
}

async function removeTransitionsSelectionUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips to hard-cut";
    return;
  }
  $("status-msg").textContent = "Removing transitions…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/edit/remove_transitions_selection", {
      clip_ids: ids,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `HardSel · ${r.count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`HardSel failed: ${e}`);
    $("status-msg").textContent = `HardSel failed: ${e}`;
  }
}

async function staggerSelectionUi() {
  const ids = selectionList();
  if (ids.length < 2) {
    $("status-msg").textContent = "Select 2+ clips to stagger";
    return;
  }
  $("status-msg").textContent = "Staggering selection…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/edit/stagger_selection", {
      clip_ids: ids,
      offset_frames: 10,
      from_earliest: true,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `Stagger · ${r.count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`Stagger failed: ${e}`);
    $("status-msg").textContent = `Stagger failed: ${e}`;
  }
}

async function splitSelectionEvenlyUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips to split evenly";
    return;
  }
  $("status-msg").textContent = "Splitting evenly…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/edit/split_selection_evenly", {
      clip_ids: ids,
      parts: 2,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `Split½ · ${r.count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`Split½ failed: ${e}`);
    $("status-msg").textContent = `Split½ failed: ${e}`;
  }
}

async function markersSelectionMidsUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips for mid markers";
    return;
  }
  $("status-msg").textContent = "Adding mid markers…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/markers/selection_mids", {
      clip_ids: ids,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `MidMkr · ${r.count ?? 0}`;
  } catch (e) {
    setProOut(`MidMkr failed: ${e}`);
    $("status-msg").textContent = `MidMkr failed: ${e}`;
  }
}

async function edgeFadesSelectionUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips for edge fades";
    return;
  }
  $("status-msg").textContent = "Applying edge fades…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/edit/edge_fades_selection", {
      clip_ids: ids,
      fade_in_frames: 6,
      fade_out_frames: 6,
      replace: true,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `FadeSel · ${r.count ?? ids.length}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`FadeSel failed: ${e}`);
    $("status-msg").textContent = `FadeSel failed: ${e}`;
  }
}

async function detachAudioSelectionUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select video clips to detach audio";
    return;
  }
  $("status-msg").textContent = "Detaching audio…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/edit/detach_audio_selection", {
      clip_ids: ids,
      audio_start_offset_frames: 0,
      link: true,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `DetSel · ${r.count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`DetSel failed: ${e}`);
    $("status-msg").textContent = `DetSel failed: ${e}`;
  }
}

async function matchSelectionDurationUi() {
  const ids = selectionList();
  if (ids.length < 2) {
    $("status-msg").textContent = "Select 2+ clips (first is target)";
    return;
  }
  $("status-msg").textContent = "Matching selection duration…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/edit/match_selection_duration", {
      clip_ids: ids,
      target_clip_id: ids[0],
      clamp: true,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `MatchSel · ${r.count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`MatchSel failed: ${e}`);
    $("status-msg").textContent = `MatchSel failed: ${e}`;
  }
}

async function selectionJlCutUi(style: "j" | "l") {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select video clips for J/L cut";
    return;
  }
  $("status-msg").textContent = `${style.toUpperCase()}-cut…`;
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/edit/selection_jl_cut", {
      clip_ids: ids,
      style,
      frames: 15,
      link: true,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `${style === "j" ? "JCut" : "LCut"} · ${r.count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`JL cut failed: ${e}`);
    $("status-msg").textContent = `JL cut failed: ${e}`;
  }
}

async function expandSelectionLinksUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips to expand links";
    return;
  }
  try {
    const r = await postJson<{
      clip_ids?: string[];
      count?: number;
      added_count?: number;
    }>("/api/edit/expand_selection_links", { clip_ids: ids });
    setProOut(JSON.stringify(r, null, 2));
    const expanded = r.clip_ids || ids;
    // best-effort: if selection API exists use it; else status only
    if (typeof (globalThis as { setSelection?: (x: string[]) => void }).setSelection === "function") {
      (globalThis as { setSelection: (x: string[]) => void }).setSelection(expanded);
    }
    $("status-msg").textContent =
      `ExpLink · ${r.count ?? expanded.length} (+${r.added_count ?? 0})`;
  } catch (e) {
    setProOut(`ExpLink failed: ${e}`);
    $("status-msg").textContent = `ExpLink failed: ${e}`;
  }
}

async function closeGapsSelectionTracksUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips (tracks to pack)";
    return;
  }
  $("status-msg").textContent = "Closing gaps on selection tracks…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/edit/close_gaps_selection_tracks", {
      clip_ids: ids,
      from_frame: 0,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `GapSel · ${r.count ?? 0} tracks`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`GapSel failed: ${e}`);
    $("status-msg").textContent = `GapSel failed: ${e}`;
  }
}

async function freezeSelectionMidsUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips to freeze";
    return;
  }
  $("status-msg").textContent = "Freezing selection mids…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/edit/freeze_selection_mids", {
      clip_ids: ids,
      duration_frames: 30,
      insert: true,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `FrzSel · ${r.count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`FrzSel failed: ${e}`);
    $("status-msg").textContent = `FrzSel failed: ${e}`;
  }
}

async function isolateSelectionUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips to isolate";
    return;
  }
  $("status-msg").textContent = "Isolating selection…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      muted_count?: number;
      unmuted_count?: number;
    }>("/api/edit/isolate_selection", {
      clip_ids: ids,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `IsoSel · keep ${r.unmuted_count ?? ids.length} mute ${r.muted_count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`IsoSel failed: ${e}`);
    $("status-msg").textContent = `IsoSel failed: ${e}`;
  }
}

async function selectionGainUi(db: number) {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips for gain";
    return;
  }
  $("status-msg").textContent = `Setting gain ${db} dB…`;
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/edit/selection_gain", {
      clip_ids: ids,
      db,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `Gain · ${db} dB · ${r.count ?? ids.length}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`Gain failed: ${e}`);
    $("status-msg").textContent = `Gain failed: ${e}`;
  }
}

async function selectionOpacityUi(amount: number) {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips for opacity";
    return;
  }
  $("status-msg").textContent = `Setting opacity ${amount}…`;
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/edit/selection_opacity", {
      clip_ids: ids,
      amount,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `Opac · ${amount} · ${r.count ?? ids.length}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`Opac failed: ${e}`);
    $("status-msg").textContent = `Opac failed: ${e}`;
  }
}

async function selectionToNewTrackUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips for new track";
    return;
  }
  $("status-msg").textContent = "Moving selection to new track…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      new_track_id?: string;
      count?: number;
    }>("/api/edit/selection_to_new_track", {
      clip_ids: ids,
      preserve_starts: true,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `NewTrk · ${r.new_track_id || "ok"} · ${r.count ?? ids.length}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`NewTrk failed: ${e}`);
    $("status-msg").textContent = `NewTrk failed: ${e}`;
  }
}

async function duplicateSelectionToNewTrackUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips to duplicate to track";
    return;
  }
  $("status-msg").textContent = "Duplicating to new track…";
  try {
    // create new track by moving a temp approach: selection_to_new_track then
    // better: add track via API if exists — use selection_to_new_track on
    // a duplicate first... simplest: call selection_to_new_track after
    // duplicate_selection. Two steps for reliability.
    const dup = await postJson<{
      timeline?: TimelineView;
      count?: number;
      duplicates?: { clip_id?: string }[];
    }>("/api/edit/duplicate_selection", { clip_ids: ids });
    const newIds = (dup.duplicates || [])
      .map((d) => d.clip_id)
      .filter((x): x is string => Boolean(x));
    if (!newIds.length) {
      // fallback: new track from original (moves)
      await selectionToNewTrackUi();
      return;
    }
    const r = await postJson<{
      timeline?: TimelineView;
      new_track_id?: string;
      count?: number;
    }>("/api/edit/selection_to_new_track", {
      clip_ids: newIds,
      preserve_starts: true,
      name: "Dup",
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify({ dup, move: r }, null, 2));
    $("status-msg").textContent =
      `DupTrk · ${r.new_track_id || "ok"} · ${r.count ?? newIds.length}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`DupTrk failed: ${e}`);
    $("status-msg").textContent = `DupTrk failed: ${e}`;
  }
}

async function bakeSelectionUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips to bake";
    return;
  }
  $("status-msg").textContent = "Baking selection…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
      error_count?: number;
    }>("/api/edit/bake_selection", {
      clip_ids: ids,
      replace: true,
      clear_effects: true,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `BakeSel · ${r.count ?? 0} err ${r.error_count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`BakeSel failed: ${e}`);
    $("status-msg").textContent = `BakeSel failed: ${e}`;
  }
}

async function exportSelectionCutlistUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips for cutlist";
    return;
  }
  $("status-msg").textContent = "Exporting selection cutlist…";
  try {
    const r = await postJson<Record<string, unknown>>("/api/export/selection_cutlist", {
      clip_ids: ids,
      format: "csv",
    });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `Cutlist · ${String(r.count ?? 0)} → ${String(r.path || "ok")}`;
  } catch (e) {
    setProOut(`Cutlist failed: ${e}`);
    $("status-msg").textContent = `Cutlist failed: ${e}`;
  }
}

async function exportSelectionEdlUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips for EDL";
    return;
  }
  $("status-msg").textContent = "Exporting selection EDL…";
  try {
    const r = await postJson<Record<string, unknown>>("/api/export/selection_edl", {
      clip_ids: ids,
    });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `EDL · ${String(r.count ?? 0)} → ${String(r.path || "ok")}`;
  } catch (e) {
    setProOut(`EDL failed: ${e}`);
    $("status-msg").textContent = `EDL failed: ${e}`;
  }
}

async function renameSelectionUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips to rename";
    return;
  }
  $("status-msg").textContent = "Renaming selection…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/edit/rename_selection", {
      clip_ids: ids,
      pattern: "Clip {n:03d}",
      start: 1,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `Rename · ${r.count ?? ids.length}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`Rename failed: ${e}`);
    $("status-msg").textContent = `Rename failed: ${e}`;
  }
}

async function colorSelectionUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips to color";
    return;
  }
  $("status-msg").textContent = "Coloring selection…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/edit/color_selection", {
      clip_ids: ids,
      color: "#4cc9f0",
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `Color · ${r.count ?? ids.length}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`Color failed: ${e}`);
    $("status-msg").textContent = `Color failed: ${e}`;
  }
}

async function selectionDiagnosticsUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips for diagnostics";
    return;
  }
  try {
    const r = await postJson<Record<string, unknown>>(
      "/api/edit/selection_diagnostics",
      { clip_ids: ids },
    );
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `Diag · ${String(r.count ?? 0)} offline ${String(r.offline_count ?? 0)} fx ${String(r.effect_instances ?? 0)}`;
  } catch (e) {
    setProOut(`Diag failed: ${e}`);
    $("status-msg").textContent = `Diag failed: ${e}`;
  }
}

async function selectionPathCUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips for path-C report";
    return;
  }
  try {
    const r = await postJson<Record<string, unknown>>("/api/edit/selection_path_c", {
      clip_ids: ids,
    });
    setProOut(JSON.stringify(r, null, 2));
    const ready = r.path_c_ready ? "ready" : "gaps";
    $("status-msg").textContent =
      `PathC? · ${ready} · not_ready ${String(r.not_ready_count ?? 0)} · v${String(r.adapter_version ?? "?")}`;
  } catch (e) {
    setProOut(`PathC? failed: ${e}`);
    $("status-msg").textContent = `PathC? failed: ${e}`;
  }
}

async function lookSelectionUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips for look";
    return;
  }
  $("status-msg").textContent = "Applying look…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      clip_count?: number;
      applied_count?: number;
    }>("/api/edit/look_selection", {
      clip_ids: ids,
      look: "cinematic",
      video_only: true,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `Look · clips ${r.clip_count ?? ids.length} fx ${r.applied_count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`Look failed: ${e}`);
    $("status-msg").textContent = `Look failed: ${e}`;
  }
}

async function styleSelectionUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips for style";
    return;
  }
  $("status-msg").textContent = "Applying style…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
    }>("/api/edit/style_selection", {
      clip_ids: ids,
      styles: "cinematic",
      apply_motion: true,
      place_audio_assets: false,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `Style · ${ids.length} clips`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`Style failed: ${e}`);
    $("status-msg").textContent = `Style failed: ${e}`;
  }
}

async function slipSelectionBatchUi(delta: number) {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips to slip";
    return;
  }
  $("status-msg").textContent = `Slipping selection ${delta}f…`;
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
      error_count?: number;
    }>("/api/edit/slip_selection", {
      clip_ids: ids,
      delta_src_frames: delta,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `SlipSel · ${r.count ?? 0} err ${r.error_count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`SlipSel failed: ${e}`);
    $("status-msg").textContent = `SlipSel failed: ${e}`;
  }
}

async function slideSelectionBatchUi(delta: number) {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips to slide";
    return;
  }
  $("status-msg").textContent = `Sliding selection ${delta}f…`;
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
      error_count?: number;
    }>("/api/edit/slide_selection", {
      clip_ids: ids,
      delta_frames: delta,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `SlideSel · ${r.count ?? 0} err ${r.error_count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`SlideSel failed: ${e}`);
    $("status-msg").textContent = `SlideSel failed: ${e}`;
  }
}

async function snapSelectionPlayheadUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips to snap";
    return;
  }
  const ph = playheadFrame();
  $("status-msg").textContent = `Snapping selection to f${ph}…`;
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/edit/snap_selection_playhead", {
      clip_ids: ids,
      playhead_frame: ph,
      edge: "start",
      mode: "relative",
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `Snap@ · f${ph}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`Snap@ failed: ${e}`);
    $("status-msg").textContent = `Snap@ failed: ${e}`;
  }
}

async function liftSelectionUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips to lift";
    return;
  }
  $("status-msg").textContent = "Lifting selection…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
      error_count?: number;
    }>("/api/edit/lift_selection", { clip_ids: ids });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `LiftSel · ${r.count ?? 0} err ${r.error_count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`LiftSel failed: ${e}`);
    $("status-msg").textContent = `LiftSel failed: ${e}`;
  }
}

async function packSelectionUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips to pack";
    return;
  }
  $("status-msg").textContent = "Packing selection…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/edit/pack_selection", { clip_ids: ids, gap_frames: 0 });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `PackSel · moved ${r.count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`PackSel failed: ${e}`);
    $("status-msg").textContent = `PackSel failed: ${e}`;
  }
}

async function muteSelectionUi(muted: boolean) {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = muted ? "Select clips to mute" : "Select clips to unmute";
    return;
  }
  $("status-msg").textContent = muted ? "Muting selection…" : "Unmuting selection…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/edit/mute_selection", { clip_ids: ids, muted });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `${muted ? "MuteSel" : "UnmuteSel"} · ${r.count ?? ids.length}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`MuteSel failed: ${e}`);
    $("status-msg").textContent = `MuteSel failed: ${e}`;
  }
}

async function extractSelectionUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips to extract";
    return;
  }
  $("status-msg").textContent = "Extracting selection…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/edit/extract_selection", { clip_ids: ids });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `ExtractSel · ${r.count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`ExtractSel failed: ${e}`);
    $("status-msg").textContent = `ExtractSel failed: ${e}`;
  }
}

async function joinSelectionUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select adjacent clips to join";
    return;
  }
  $("status-msg").textContent = "Joining selection…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
      error_count?: number;
    }>("/api/edit/join_selection", { clip_ids: ids });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `JoinSel · ${r.count ?? 0} err ${r.error_count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`JoinSel failed: ${e}`);
    $("status-msg").textContent = `JoinSel failed: ${e}`;
  }
}

async function pipSelectionUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips for PiP";
    return;
  }
  $("status-msg").textContent = "Setting PiP on selection…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/edit/selection_position", {
      clip_ids: ids,
      x: 1.0,
      y: 1.0,
      scale: 0.35,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `PiPSel · ${r.count ?? ids.length}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`PiPSel failed: ${e}`);
    $("status-msg").textContent = `PiPSel failed: ${e}`;
  }
}

async function clearPipSelectionUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips to clear PiP";
    return;
  }
  $("status-msg").textContent = "Clearing PiP…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/edit/clear_selection_position", { clip_ids: ids });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `ClrPiP · ${r.count ?? ids.length}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`ClrPiP failed: ${e}`);
    $("status-msg").textContent = `ClrPiP failed: ${e}`;
  }
}

async function reverseSelectionOrderUi() {
  const ids = selectionList();
  if (ids.length < 2) {
    $("status-msg").textContent = "Select ≥2 clips to reverse order";
    return;
  }
  $("status-msg").textContent = "Reversing selection order…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/edit/reverse_selection_order", { clip_ids: ids });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `RevOrd · moved ${r.count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`RevOrd failed: ${e}`);
    $("status-msg").textContent = `RevOrd failed: ${e}`;
  }
}

async function linkSelectionUi() {
  const ids = selectionList();
  if (ids.length < 2) {
    $("status-msg").textContent = "Select ≥2 clips to link";
    return;
  }
  $("status-msg").textContent = "Linking selection…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
      link_group?: string;
    }>("/api/edit/link_selection", { clip_ids: ids });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `LinkSel · ${r.count ?? ids.length}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`LinkSel failed: ${e}`);
    $("status-msg").textContent = `LinkSel failed: ${e}`;
  }
}

async function unlinkSelectionUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips to unlink";
    return;
  }
  $("status-msg").textContent = "Unlinking selection…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/edit/unlink_selection", { clip_ids: ids });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `UnlinkSel · ${r.count ?? ids.length}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`UnlinkSel failed: ${e}`);
    $("status-msg").textContent = `UnlinkSel failed: ${e}`;
  }
}

async function rateStretchSelectionUi(target: number) {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips to rate-stretch";
    return;
  }
  $("status-msg").textContent = `Rate-stretch to ${target}f…`;
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
      error_count?: number;
    }>("/api/edit/rate_stretch_selection", {
      clip_ids: ids,
      target_duration_frames: target,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `Stretch${target} · ${r.count ?? 0} err ${r.error_count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`Stretch failed: ${e}`);
    $("status-msg").textContent = `Stretch failed: ${e}`;
  }
}

async function trimSelectionEdgesUi(head: number, tail: number) {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips to trim";
    return;
  }
  $("status-msg").textContent = "Trimming selection edges…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
      error_count?: number;
    }>("/api/edit/trim_selection_edges", {
      clip_ids: ids,
      head_frames: head,
      tail_frames: tail,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `Trim · ${r.count ?? 0} err ${r.error_count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`Trim edges failed: ${e}`);
    $("status-msg").textContent = `Trim edges failed: ${e}`;
  }
}

async function selectionGapsUi() {
  const ids = selectionList();
  if (ids.length < 2) {
    $("status-msg").textContent = "Select ≥2 clips for gap report";
    return;
  }
  $("status-msg").textContent = "Selection gaps…";
  try {
    const r = await postJson<{
      count?: number;
      gaps?: unknown[];
    }>("/api/edit/selection_gaps", { clip_ids: ids });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `Gaps? · ${r.count ?? 0}`;
  } catch (e) {
    setProOut(`Gaps? failed: ${e}`);
    $("status-msg").textContent = `Gaps? failed: ${e}`;
  }
}

async function extendSelectionNextUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips to extend";
    return;
  }
  $("status-msg").textContent = "Extending selection to next…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
      error_count?: number;
    }>("/api/edit/extend_selection_next", { clip_ids: ids });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `ExtNext · ${r.count ?? 0} err ${r.error_count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`ExtNext failed: ${e}`);
    $("status-msg").textContent = `ExtNext failed: ${e}`;
  }
}

async function selectionSpeedUi(speed: number) {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips for speed";
    return;
  }
  $("status-msg").textContent = `Setting speed ${speed}…`;
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/edit/selection_speed", { clip_ids: ids, speed });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `Spd${speed} · ${r.count ?? ids.length}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`Spd failed: ${e}`);
    $("status-msg").textContent = `Spd failed: ${e}`;
  }
}

async function selectionPathCPlanUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips for path-C plan";
    return;
  }
  $("status-msg").textContent = "Building path-C plan…";
  try {
    const r = await postJson<{
      clips?: unknown[];
      adapter_version?: number;
    }>("/api/edit/selection_path_c_plan", {
      clip_ids: ids,
      height: 360,
      include_audio: false,
    });
    setProOut(JSON.stringify(r, null, 2));
    const n = Array.isArray(r.clips) ? r.clips.length : 0;
    $("status-msg").textContent =
      `PathCPlan · ${n} clips adapter≥${r.adapter_version ?? "?"}`;
  } catch (e) {
    setProOut(`PathCPlan failed: ${e}`);
    $("status-msg").textContent = `PathCPlan failed: ${e}`;
  }
}

async function matchFrameSelectionUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips for match frame";
    return;
  }
  const ph = playheadFrame();
  $("status-msg").textContent = "Match frame selection…";
  try {
    const r = await postJson<{
      count?: number;
      error_count?: number;
    }>("/api/edit/match_frame_selection", {
      clip_ids: ids,
      timeline_frame: ph,
    });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `MatchSel · ${r.count ?? 0} err ${r.error_count ?? 0}`;
  } catch (e) {
    setProOut(`MatchSel failed: ${e}`);
    $("status-msg").textContent = `MatchSel failed: ${e}`;
  }
}

async function rippleTrimSelectionEdgesUi(head: number, tail: number) {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips to ripple-trim";
    return;
  }
  $("status-msg").textContent = "Ripple-trimming selection…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
      error_count?: number;
    }>("/api/edit/ripple_trim_selection_edges", {
      clip_ids: ids,
      head_src_frames: head,
      tail_src_frames: tail,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `RTrim · ${r.count ?? 0} err ${r.error_count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`RTrim failed: ${e}`);
    $("status-msg").textContent = `RTrim failed: ${e}`;
  }
}

async function exportSelectionPathCPlanUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips to export path-C plan";
    return;
  }
  $("status-msg").textContent = "Exporting path-C plan JSON…";
  try {
    const r = await postJson<{
      output_path?: string;
      clip_count?: number;
      adapter_version?: number;
    }>("/api/edit/export_selection_path_c_plan", {
      clip_ids: ids,
      height: 360,
    });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `PathC.json · ${r.clip_count ?? 0} → ${r.output_path ?? "?"}`;
  } catch (e) {
    setProOut(`PathC.json failed: ${e}`);
    $("status-msg").textContent = `PathC.json failed: ${e}`;
  }
}

async function fillSelectionGapsUi() {
  const ids = selectionList();
  if (ids.length < 2) {
    $("status-msg").textContent = "Select ≥2 clips to fill gaps";
    return;
  }
  $("status-msg").textContent = "Filling selection gaps…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/edit/fill_selection_gaps", {
      clip_ids: ids,
      mode: "slug",
      color: "#000000",
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `FillGaps · ${r.count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`FillGaps failed: ${e}`);
    $("status-msg").textContent = `FillGaps failed: ${e}`;
  }
}

async function swapSelectionPairUi() {
  const ids = selectionList();
  if (ids.length < 2) {
    $("status-msg").textContent = "Select ≥2 clips to swap first two";
    return;
  }
  $("status-msg").textContent = "Swapping pair…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
    }>("/api/edit/swap_selection_pair", {
      clip_id_a: ids[0],
      clip_id_b: ids[1],
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = "Swap2 · done";
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`Swap2 failed: ${e}`);
    $("status-msg").textContent = `Swap2 failed: ${e}`;
  }
}

async function duplicateSelectionBlockUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips to duplicate block";
    return;
  }
  $("status-msg").textContent = "Duplicating selection block…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
      error_count?: number;
    }>("/api/edit/duplicate_selection_block", {
      clip_ids: ids,
      gap_frames: 0,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `DupBlock · ${r.count ?? 0} err ${r.error_count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`DupBlock failed: ${e}`);
    $("status-msg").textContent = `DupBlock failed: ${e}`;
  }
}

async function alignSelectionEndsUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips to align ends";
    return;
  }
  $("status-msg").textContent = "Aligning ends…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
      to_frame?: number;
    }>("/api/edit/align_selection_ends", { clip_ids: ids });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `AlignEnds · moved ${r.count ?? 0} @${r.to_frame ?? "?"}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`AlignEnds failed: ${e}`);
    $("status-msg").textContent = `AlignEnds failed: ${e}`;
  }
}

async function selectionMediaReportUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips for media report";
    return;
  }
  $("status-msg").textContent = "Selection media…";
  try {
    const r = await postJson<{
      count?: number;
      media_count?: number;
    }>("/api/edit/selection_media_report", { clip_ids: ids });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `Media? · ${r.count ?? 0} clips / ${r.media_count ?? 0} media`;
  } catch (e) {
    setProOut(`Media? failed: ${e}`);
    $("status-msg").textContent = `Media? failed: ${e}`;
  }
}

async function renameSelectionFromMediaUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips to rename from media";
    return;
  }
  $("status-msg").textContent = "Renaming from media…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/edit/rename_selection_from_media", {
      clip_ids: ids,
      suffix_index: false,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `NameMedia · ${r.count ?? ids.length}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`NameMedia failed: ${e}`);
    $("status-msg").textContent = `NameMedia failed: ${e}`;
  }
}

async function nudgeSelectionUi(delta: number) {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips to nudge";
    return;
  }
  $("status-msg").textContent = `Nudging ${delta}f…`;
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/edit/nudge_selection", {
      clip_ids: ids,
      delta_frames: delta,
      follow_links: false,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `Nudge · ${r.count ?? ids.length}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`Nudge failed: ${e}`);
    $("status-msg").textContent = `Nudge failed: ${e}`;
  }
}

async function moveSelectionToPlayheadUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips to move";
    return;
  }
  const ph = playheadFrame();
  $("status-msg").textContent = `Moving selection to f${ph}…`;
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/edit/move_selection_to_frame", {
      clip_ids: ids,
      to_frame: ph,
      follow_links: false,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `Move@ · f${ph}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`Move@ failed: ${e}`);
    $("status-msg").textContent = `Move@ failed: ${e}`;
  }
}

async function insertTimeBeforeSelectionUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips for insert time";
    return;
  }
  $("status-msg").textContent = "Inserting time before selection…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
      frames?: number;
    }>("/api/edit/insert_time_before_selection", {
      clip_ids: ids,
      frames: 15,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `InsTime · +${r.frames ?? 15}f moved ${r.count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`InsTime failed: ${e}`);
    $("status-msg").textContent = `InsTime failed: ${e}`;
  }
}

async function removeTimeBeforeSelectionUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips for remove time";
    return;
  }
  $("status-msg").textContent = "Removing time before selection…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
      frames_requested?: number;
    }>("/api/edit/remove_time_before_selection", {
      clip_ids: ids,
      frames: 15,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `RmTime · −${r.frames_requested ?? 15}f moved ${r.count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`RmTime failed: ${e}`);
    $("status-msg").textContent = `RmTime failed: ${e}`;
  }
}

async function rippleNudgeSelectionUi(delta: number) {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips to ripple-nudge";
    return;
  }
  $("status-msg").textContent = `Ripple nudge ${delta}f…`;
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/edit/ripple_nudge_selection", {
      clip_ids: ids,
      delta_frames: delta,
      include_self: true,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `RNudge · tracks ${r.count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`RNudge failed: ${e}`);
    $("status-msg").textContent = `RNudge failed: ${e}`;
  }
}

async function razorSelectionAtUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips to razor";
    return;
  }
  const ph = playheadFrame();
  $("status-msg").textContent = `Razor selection @ f${ph}…`;
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/edit/razor_selection_at", {
      clip_ids: ids,
      at_frame: ph,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `RazorSel@ · ${r.count ?? 0} @f${ph}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`RazorSel@ failed: ${e}`);
    $("status-msg").textContent = `RazorSel@ failed: ${e}`;
  }
}

async function flipSelectionHUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips to flip";
    return;
  }
  $("status-msg").textContent = "Flipping selection H…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/edit/flip_selection", {
      clip_ids: ids,
      horizontal: true,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `FlipH · ${r.count ?? ids.length}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`FlipH failed: ${e}`);
    $("status-msg").textContent = `FlipH failed: ${e}`;
  }
}

async function rotateSelectionUi(degrees: number) {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips to rotate";
    return;
  }
  $("status-msg").textContent = `Rotating ${degrees}°…`;
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
      error_count?: number;
    }>("/api/edit/rotate_selection", {
      clip_ids: ids,
      degrees,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `Rot${degrees} · ${r.count ?? 0} err ${r.error_count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`Rot failed: ${e}`);
    $("status-msg").textContent = `Rot failed: ${e}`;
  }
}

async function selectionCutReportUi() {
  const ids = selectionList();
  if (ids.length < 2) {
    $("status-msg").textContent = "Select ≥2 clips for cut report";
    return;
  }
  $("status-msg").textContent = "Selection cuts…";
  try {
    const r = await postJson<{
      count?: number;
      by_kind?: Record<string, number>;
    }>("/api/edit/selection_cut_report", { clip_ids: ids });
    setProOut(JSON.stringify(r, null, 2));
    const bk = r.by_kind || {};
    $("status-msg").textContent =
      `Cuts? · ${r.count ?? 0} (${Object.entries(bk).map(([k, v]) => `${k}:${v}`).join(" ")})`;
  } catch (e) {
    setProOut(`Cuts? failed: ${e}`);
    $("status-msg").textContent = `Cuts? failed: ${e}`;
  }
}

async function cropSelectionCenterUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips to crop";
    return;
  }
  $("status-msg").textContent = "Center-cropping selection…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
      error_count?: number;
    }>("/api/edit/crop_selection_center", {
      clip_ids: ids,
      scale: 0.85,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `CropC · ${r.count ?? 0} err ${r.error_count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`CropC failed: ${e}`);
    $("status-msg").textContent = `CropC failed: ${e}`;
  }
}

async function vignetteSelectionUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips for vignette";
    return;
  }
  $("status-msg").textContent = "Applying vignette…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
      error_count?: number;
    }>("/api/edit/vignette_selection", {
      clip_ids: ids,
      strength: 0.4,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `VigSel · ${r.count ?? 0} err ${r.error_count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`VigSel failed: ${e}`);
    $("status-msg").textContent = `VigSel failed: ${e}`;
  }
}

async function selectionEffectsReportUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips for FX report";
    return;
  }
  $("status-msg").textContent = "Selection FX…";
  try {
    const r = await postJson<{
      count?: number;
      unmapped_total?: number;
      adapter_version?: number;
      histogram?: Record<string, number>;
    }>("/api/edit/selection_effects_report", { clip_ids: ids });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `FX? · ${r.count ?? 0} unmapped ${r.unmapped_total ?? 0} adapter≥${r.adapter_version ?? "?"}`;
  } catch (e) {
    setProOut(`FX? failed: ${e}`);
    $("status-msg").textContent = `FX? failed: ${e}`;
  }
}

async function blurSelectionUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips to blur";
    return;
  }
  $("status-msg").textContent = "Blurring selection…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
      error_count?: number;
    }>("/api/edit/blur_selection", { clip_ids: ids, amount: 5.0 });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `BlurSel · ${r.count ?? 0} err ${r.error_count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`BlurSel failed: ${e}`);
    $("status-msg").textContent = `BlurSel failed: ${e}`;
  }
}

async function sharpenSelectionUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips to sharpen";
    return;
  }
  $("status-msg").textContent = "Sharpening selection…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
      error_count?: number;
    }>("/api/edit/sharpen_selection", { clip_ids: ids, amount: 1.0 });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `SharpSel · ${r.count ?? 0} err ${r.error_count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`SharpSel failed: ${e}`);
    $("status-msg").textContent = `SharpSel failed: ${e}`;
  }
}

async function filmGrainSelectionUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips for film grain";
    return;
  }
  $("status-msg").textContent = "Applying film grain…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
      error_count?: number;
    }>("/api/edit/film_grain_selection", { clip_ids: ids, amount: 12.0 });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `GrainSel · ${r.count ?? 0} err ${r.error_count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`GrainSel failed: ${e}`);
    $("status-msg").textContent = `GrainSel failed: ${e}`;
  }
}

async function glowSelectionUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips for glow";
    return;
  }
  $("status-msg").textContent = "Applying glow…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
      error_count?: number;
    }>("/api/edit/glow_selection", {
      clip_ids: ids,
      amount: 8.0,
      intensity: 0.4,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `GlowSel · ${r.count ?? 0} err ${r.error_count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`GlowSel failed: ${e}`);
    $("status-msg").textContent = `GlowSel failed: ${e}`;
  }
}

async function curvesSelectionUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips for curves";
    return;
  }
  $("status-msg").textContent = "Applying curves…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
      error_count?: number;
    }>("/api/edit/curves_selection", {
      clip_ids: ids,
      preset: "increase_contrast",
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `CurvesSel · ${r.count ?? 0} err ${r.error_count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`CurvesSel failed: ${e}`);
    $("status-msg").textContent = `CurvesSel failed: ${e}`;
  }
}

async function chromaKeySelectionUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips for chroma key";
    return;
  }
  $("status-msg").textContent = "Applying chroma key…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
      error_count?: number;
    }>("/api/edit/chroma_key_selection", {
      clip_ids: ids,
      color: "green",
      similarity: 0.15,
      blend: 0.05,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `ChromaSel · ${r.count ?? 0} err ${r.error_count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`ChromaSel failed: ${e}`);
    $("status-msg").textContent = `ChromaSel failed: ${e}`;
  }
}

async function whiteBalanceSelectionUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips for white balance";
    return;
  }
  $("status-msg").textContent = "Applying white balance…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
      error_count?: number;
    }>("/api/edit/white_balance_selection", {
      clip_ids: ids,
      temperature: 5600,
      mix: 1.0,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `WBSel · ${r.count ?? 0} err ${r.error_count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`WBSel failed: ${e}`);
    $("status-msg").textContent = `WBSel failed: ${e}`;
  }
}

async function clearSelectionEffectsUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips to clear FX";
    return;
  }
  $("status-msg").textContent = "Clearing selection FX…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/edit/clear_selection_effects", { clip_ids: ids });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `ClrFxSel · ${r.count ?? ids.length}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`ClrFxSel failed: ${e}`);
    $("status-msg").textContent = `ClrFxSel failed: ${e}`;
  }
}

async function stripSelectionPathCUnmappedUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips to strip unmapped FX";
    return;
  }
  $("status-msg").textContent = "Stripping path-C unmapped…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
      adapter_version?: number;
    }>("/api/edit/strip_selection_path_c_unmapped", { clip_ids: ids });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `StripUC · ${r.count ?? 0} adapter≥${r.adapter_version ?? "?"}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`StripUC failed: ${e}`);
    $("status-msg").textContent = `StripUC failed: ${e}`;
  }
}

async function compressionSelectionUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips for compression";
    return;
  }
  $("status-msg").textContent = "Applying compression…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
      error_count?: number;
    }>("/api/edit/compression_selection", {
      clip_ids: ids,
      ratio: 4.0,
      threshold_db: -18.0,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `CompSel · ${r.count ?? 0} err ${r.error_count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`CompSel failed: ${e}`);
    $("status-msg").textContent = `CompSel failed: ${e}`;
  }
}

async function noiseReductionSelectionUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips for noise reduction";
    return;
  }
  $("status-msg").textContent = "Applying noise reduction…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
      error_count?: number;
    }>("/api/edit/noise_reduction_selection", {
      clip_ids: ids,
      amount: 12.0,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `NRSel · ${r.count ?? 0} err ${r.error_count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`NRSel failed: ${e}`);
    $("status-msg").textContent = `NRSel failed: ${e}`;
  }
}

async function audioEqSelectionUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips for EQ";
    return;
  }
  $("status-msg").textContent = "Applying EQ…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
      error_count?: number;
    }>("/api/edit/audio_eq_selection", {
      clip_ids: ids,
      frequency_hz: 1000,
      gain_db: 3.0,
      q: 1.0,
      replace: false,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `EQSel · ${r.count ?? 0} err ${r.error_count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`EQSel failed: ${e}`);
    $("status-msg").textContent = `EQSel failed: ${e}`;
  }
}

async function razorSelectionAtMarkersUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips to razor at markers";
    return;
  }
  $("status-msg").textContent = "Razor selection @ markers…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
      skipped_count?: number;
    }>("/api/edit/razor_selection_at_markers", { clip_ids: ids });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `Razor@Mkr · ${r.count ?? 0} skip ${r.skipped_count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`Razor@Mkr failed: ${e}`);
    $("status-msg").textContent = `Razor@Mkr failed: ${e}`;
  }
}

async function freezeSelectionAtPlayheadUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips to freeze";
    return;
  }
  const ph = playheadFrame();
  $("status-msg").textContent = `Freeze selection @ f${ph}…`;
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
      error_count?: number;
    }>("/api/edit/freeze_selection_at", {
      clip_ids: ids,
      timeline_frame: ph,
      duration_frames: 30,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `Frz@ · ${r.count ?? 0} err ${r.error_count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`Frz@ failed: ${e}`);
    $("status-msg").textContent = `Frz@ failed: ${e}`;
  }
}

async function exportSelectionAudioDefaultUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips for audio export";
    return;
  }
  $("status-msg").textContent = "Exporting selection audio…";
  try {
    const r = await postJson<{
      path?: string;
      output_path?: string;
      start_frame?: number;
      end_frame?: number;
    }>("/api/edit/export_selection_audio_default", {
      clip_ids: ids,
      filename: "selection_mix.wav",
    });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `AudSel · ${String(r.path || r.output_path || "ok")}`;
  } catch (e) {
    setProOut(`AudSel failed: ${e}`);
    $("status-msg").textContent = `AudSel failed: ${e}`;
  }
}

async function selectionProxyReportUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips for proxy report";
    return;
  }
  $("status-msg").textContent = "Selection proxies…";
  try {
    const r = await postJson<{
      count?: number;
      proxy_ready_count?: number;
      proxy_missing_count?: number;
    }>("/api/edit/selection_proxy_report", { clip_ids: ids });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `Proxy? · ready ${r.proxy_ready_count ?? 0}/${r.count ?? 0} miss ${r.proxy_missing_count ?? 0}`;
  } catch (e) {
    setProOut(`Proxy? failed: ${e}`);
    $("status-msg").textContent = `Proxy? failed: ${e}`;
  }
}

async function ensureSelectionMediaProxiesUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips to build proxies";
    return;
  }
  $("status-msg").textContent = "Building selection media proxies…";
  try {
    const r = await postJson<{
      count?: number;
      error_count?: number;
    }>("/api/edit/ensure_selection_media_proxies", {
      clip_ids: ids,
      height: 480,
      force: false,
    });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `MkProxy · ${r.count ?? 0} err ${r.error_count ?? 0}`;
  } catch (e) {
    setProOut(`MkProxy failed: ${e}`);
    $("status-msg").textContent = `MkProxy failed: ${e}`;
  }
}

async function exportSelectionMp4DefaultUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips for MP4 export";
    return;
  }
  $("status-msg").textContent = "Exporting selection MP4…";
  try {
    const r = await postJson<{
      path?: string;
      output_path?: string;
    }>("/api/edit/export_selection_mp4_default", {
      clip_ids: ids,
      filename: "selection.mp4",
    });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `Mp4Sel · ${String(r.path || r.output_path || "ok")}`;
  } catch (e) {
    setProOut(`Mp4Sel failed: ${e}`);
    $("status-msg").textContent = `Mp4Sel failed: ${e}`;
  }
}

async function exportSelectionWebmDefaultUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips for WebM export";
    return;
  }
  $("status-msg").textContent = "Exporting selection WebM…";
  try {
    const r = await postJson<{
      path?: string;
      output_path?: string;
    }>("/api/edit/export_selection_webm_default", {
      clip_ids: ids,
      filename: "selection.webm",
      crf: 32,
      width: 720,
    });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `WebmSel · ${String(r.path || r.output_path || "ok")}`;
  } catch (e) {
    setProOut(`WebmSel failed: ${e}`);
    $("status-msg").textContent = `WebmSel failed: ${e}`;
  }
}

async function exportSelectionGifDefaultUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips for GIF export";
    return;
  }
  $("status-msg").textContent = "Exporting selection GIF…";
  try {
    const r = await postJson<{
      path?: string;
      output_path?: string;
    }>("/api/edit/export_selection_gif_default", {
      clip_ids: ids,
      filename: "selection.gif",
      fps: 12,
      width: 480,
    });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `GifSel · ${String(r.path || r.output_path || "ok")}`;
  } catch (e) {
    setProOut(`GifSel failed: ${e}`);
    $("status-msg").textContent = `GifSel failed: ${e}`;
  }
}

async function workAreaFromSelectionUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips for work area";
    return;
  }
  $("status-msg").textContent = "Setting work area from selection…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      in_frame?: number;
      out_frame?: number;
      start_frame?: number;
      end_frame?: number;
    }>("/api/edit/work_area_from_selection", { clip_ids: ids });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = "WA←Sel2 · work area set";
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`WA←Sel2 failed: ${e}`);
    $("status-msg").textContent = `WA←Sel2 failed: ${e}`;
  }
}

async function copySelectionUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips to copy";
    return;
  }
  $("status-msg").textContent = "Copying selection…";
  try {
    const r = await postJson<{
      count?: number;
      span_frames?: number;
    }>("/api/edit/copy_selection", { clip_ids: ids });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `CopySel · ${r.count ?? ids.length} span ${r.span_frames ?? "?"}`;
  } catch (e) {
    setProOut(`CopySel failed: ${e}`);
    $("status-msg").textContent = `CopySel failed: ${e}`;
  }
}

async function pasteSelectionAtPlayheadUi() {
  const ph = playheadFrame();
  $("status-msg").textContent = `Pasting selection @ f${ph}…`;
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
      error_count?: number;
    }>("/api/edit/paste_selection", {
      at_playhead: true,
      playhead_frame: ph,
      prefer_source_tracks: true,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `PasteSel@ · ${r.count ?? 0} err ${r.error_count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`PasteSel@ failed: ${e}`);
    $("status-msg").textContent = `PasteSel@ failed: ${e}`;
  }
}

async function selectionClipboardStatusUi() {
  $("status-msg").textContent = "Clipboard status…";
  try {
    const r = await getJson<{
      has_selection_clipboard?: boolean;
      selection_count?: number;
      has_clipboard?: boolean;
    }>("/api/edit/selection_clipboard_status");
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `Clip? · multi ${r.selection_count ?? 0} single ${r.has_clipboard ? "y" : "n"}`;
  } catch (e) {
    setProOut(`Clip? failed: ${e}`);
    $("status-msg").textContent = `Clip? failed: ${e}`;
  }
}

async function markersInSelectionSpanUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips for marker list";
    return;
  }
  $("status-msg").textContent = "Markers in selection…";
  try {
    const r = await postJson<{
      count?: number;
    }>("/api/edit/markers_in_selection_span", { clip_ids: ids });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `MkrIn? · ${r.count ?? 0}`;
  } catch (e) {
    setProOut(`MkrIn? failed: ${e}`);
    $("status-msg").textContent = `MkrIn? failed: ${e}`;
  }
}

async function clearMarkersInSelectionSpanUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips to clear markers in span";
    return;
  }
  $("status-msg").textContent = "Clearing markers in selection…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/edit/clear_markers_in_selection_span", { clip_ids: ids });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `ClrMkrSel · ${r.count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`ClrMkrSel failed: ${e}`);
    $("status-msg").textContent = `ClrMkrSel failed: ${e}`;
  }
}

async function exportSelectionOtioUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips for OTIO export";
    return;
  }
  $("status-msg").textContent = "Exporting selection OTIO…";
  try {
    const r = await postJson<{
      path?: string;
      clip_count?: number;
      track_count?: number;
    }>("/api/edit/export_selection_otio", { clip_ids: ids });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `OTIOSel · clips ${r.clip_count ?? 0} → ${r.path ?? "?"}`;
  } catch (e) {
    setProOut(`OTIOSel failed: ${e}`);
    $("status-msg").textContent = `OTIOSel failed: ${e}`;
  }
}

async function exportSelectionEdlDefaultUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips for EDL export";
    return;
  }
  $("status-msg").textContent = "Exporting selection EDL…";
  try {
    const r = await postJson<{
      path?: string;
      count?: number;
    }>("/api/edit/export_selection_edl_default", {
      clip_ids: ids,
      filename: "selection.edl",
    });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `EdlSel · ${r.count ?? 0} → ${r.path ?? "?"}`;
  } catch (e) {
    setProOut(`EdlSel failed: ${e}`);
    $("status-msg").textContent = `EdlSel failed: ${e}`;
  }
}

async function exportSelectionCutlistDefaultUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips for cutlist export";
    return;
  }
  $("status-msg").textContent = "Exporting selection cutlist…";
  try {
    const r = await postJson<{
      path?: string;
      count?: number;
    }>("/api/edit/export_selection_cutlist_default", {
      clip_ids: ids,
      filename: "selection_cutlist.csv",
      format: "csv",
    });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `CutSel · ${r.count ?? 0} → ${r.path ?? "?"}`;
  } catch (e) {
    setProOut(`CutSel failed: ${e}`);
    $("status-msg").textContent = `CutSel failed: ${e}`;
  }
}

async function exportSelectionFcpxmlUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips for FCPXML export";
    return;
  }
  $("status-msg").textContent = "Exporting selection FCPXML…";
  try {
    const r = await postJson<{
      path?: string;
      count?: number;
    }>("/api/edit/export_selection_fcpxml", { clip_ids: ids });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `FCPSel · ${r.count ?? 0} → ${r.path ?? "?"}`;
  } catch (e) {
    setProOut(`FCPSel failed: ${e}`);
    $("status-msg").textContent = `FCPSel failed: ${e}`;
  }
}

async function selectionExportPreflightUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips for preflight";
    return;
  }
  $("status-msg").textContent = "Selection preflight…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      soft_ready?: boolean;
      path_c_ready?: boolean;
      offline_count?: number;
      gap_count?: number;
    }>("/api/edit/selection_export_preflight", {
      clip_ids: ids,
      set_work_area: true,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `Preflight · soft ${r.soft_ready ? "ok" : "no"} pathC ${r.path_c_ready ? "ok" : "warn"} off ${r.offline_count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`Preflight failed: ${e}`);
    $("status-msg").textContent = `Preflight failed: ${e}`;
  }
}

async function selectionOfflineMediaUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips for offline check";
    return;
  }
  $("status-msg").textContent = "Checking offline media…";
  try {
    const r = await postJson<{
      offline_count?: number;
      ok?: boolean;
    }>("/api/edit/selection_offline_media", { clip_ids: ids });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `Offline? · ${r.offline_count ?? 0} ${r.ok ? "ok" : "MISSING"}`;
  } catch (e) {
    setProOut(`Offline? failed: ${e}`);
    $("status-msg").textContent = `Offline? failed: ${e}`;
  }
}

async function selectionLockedTracksUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips for lock check";
    return;
  }
  $("status-msg").textContent = "Checking locked tracks…";
  try {
    const r = await postJson<{
      locked_count?: number;
      ok?: boolean;
    }>("/api/edit/selection_locked_tracks", { clip_ids: ids });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `Locked? · ${r.locked_count ?? 0} ${r.ok ? "ok" : "LOCKED"}`;
  } catch (e) {
    setProOut(`Locked? failed: ${e}`);
    $("status-msg").textContent = `Locked? failed: ${e}`;
  }
}

async function unlockSelectionTracksUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips to unlock tracks";
    return;
  }
  $("status-msg").textContent = "Unlocking selection tracks…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/edit/unlock_selection_tracks", { clip_ids: ids });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `UnlkTrk · ${r.count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`UnlkTrk failed: ${e}`);
    $("status-msg").textContent = `UnlkTrk failed: ${e}`;
  }
}

async function lockSelectionTracksUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips to lock tracks";
    return;
  }
  $("status-msg").textContent = "Locking selection tracks…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/edit/lock_selection_tracks", { clip_ids: ids });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `LockTrk · ${r.count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`LockTrk failed: ${e}`);
    $("status-msg").textContent = `LockTrk failed: ${e}`;
  }
}

async function muteSelectionTracksUi(muted: boolean) {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = muted
      ? "Select clips to mute tracks"
      : "Select clips to unmute tracks";
    return;
  }
  $("status-msg").textContent = muted
    ? "Muting selection tracks…"
    : "Unmuting selection tracks…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/edit/mute_selection_tracks", { clip_ids: ids, muted });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `${muted ? "MuteTrk" : "UnmuteTrk"} · ${r.count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`MuteTrk failed: ${e}`);
    $("status-msg").textContent = `MuteTrk failed: ${e}`;
  }
}

async function soloSelectionTracksUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips to solo tracks";
    return;
  }
  $("status-msg").textContent = "Soloing selection tracks…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/edit/solo_selection_tracks", {
      clip_ids: ids,
      exclusive: true,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `SoloTrk · ${r.count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`SoloTrk failed: ${e}`);
    $("status-msg").textContent = `SoloTrk failed: ${e}`;
  }
}

async function unsoloSelectionTracksUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips to unsolo tracks";
    return;
  }
  $("status-msg").textContent = "Unsoloing selection tracks…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/edit/unsolo_selection_tracks", { clip_ids: ids });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `UnsoloTrk · ${r.count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`UnsoloTrk failed: ${e}`);
    $("status-msg").textContent = `UnsoloTrk failed: ${e}`;
  }
}

async function selectionTrackStatesUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips for track state";
    return;
  }
  $("status-msg").textContent = "Selection track states…";
  try {
    const r = await postJson<{
      count?: number;
      tracks?: Array<{ muted?: boolean; solo?: boolean; locked?: boolean }>;
    }>("/api/edit/selection_track_states", { clip_ids: ids });
    setProOut(JSON.stringify(r, null, 2));
    const n = r.count ?? 0;
    const m = (r.tracks || []).filter((t) => t.muted).length;
    const s = (r.tracks || []).filter((t) => t.solo).length;
    const l = (r.tracks || []).filter((t) => t.locked).length;
    $("status-msg").textContent =
      `Trk? · ${n} mute ${m} solo ${s} lock ${l}`;
  } catch (e) {
    setProOut(`Trk? failed: ${e}`);
    $("status-msg").textContent = `Trk? failed: ${e}`;
  }
}

async function raiseSelectionTracksUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips to raise tracks";
    return;
  }
  $("status-msg").textContent = "Raising selection tracks…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/edit/raise_selection_tracks", { clip_ids: ids, steps: 1 });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `RaiseTrk · moves ${r.count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`RaiseTrk failed: ${e}`);
    $("status-msg").textContent = `RaiseTrk failed: ${e}`;
  }
}

async function lowerSelectionTracksUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips to lower tracks";
    return;
  }
  $("status-msg").textContent = "Lowering selection tracks…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/edit/lower_selection_tracks", { clip_ids: ids, steps: 1 });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `LowerTrk · moves ${r.count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`LowerTrk failed: ${e}`);
    $("status-msg").textContent = `LowerTrk failed: ${e}`;
  }
}

async function renameSelectionTracksUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clips to rename tracks";
    return;
  }
  $("status-msg").textContent = "Renaming selection tracks…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
    }>("/api/edit/rename_selection_tracks", {
      clip_ids: ids,
      prefix: "Sel-",
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `NameTrk · ${r.count ?? 0}`;
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`NameTrk failed: ${e}`);
    $("status-msg").textContent = `NameTrk failed: ${e}`;
  }
}

async function exportWebmUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  $("status-msg").textContent = "Exporting WebM…";
  try {
    const r = await postJson<Record<string, unknown>>("/api/export/webm", {
      crf: 32,
      width: 720,
    });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `WebM → ${String(r.path || "ok")}`;
  } catch (e) {
    setProOut(`WebM failed: ${e}`);
    $("status-msg").textContent = `WebM failed: ${e}`;
  }
}

async function exportAudioUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  try {
    const r = await postJson<Record<string, unknown>>("/api/export/audio", {});
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `Audio mix → ${r.path || r.output_path || "ok"}`;
  } catch (e) {
    $("status-msg").textContent = `Audio export failed: ${e}`;
  }
}

async function deleteTrackOfSelection() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select a clip on the track to delete";
    return;
  }
  const c = state.clips.get(ids[0]);
  if (!c?.trackId) {
    $("status-msg").textContent = "No track for selection";
    return;
  }
  if (!window.confirm(`Delete track ${c.trackId}?`)) return;
  try {
    const r = await postJson<{ timeline?: TimelineView }>("/api/track/delete", {
      track_id: c.trackId,
    });
    state.selected.clear();
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    $("status-msg").textContent = `Deleted track ${c.trackId}`;
  } catch (e) {
    $("status-msg").textContent = `Delete track failed: ${e}`;
  }
}

async function hardCutAllUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const ids = selectionList();
  const trackId = ids.length
    ? state.clips.get(ids[0])?.trackId || null
    : null;
  try {
    const r = await postJson<{ timeline?: TimelineView }>("/api/hard_cut_all", {
      track_id: trackId,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    $("status-msg").textContent = "Hard-cut all transitions";
  } catch (e) {
    $("status-msg").textContent = `Hard cut failed: ${e}`;
  }
}

async function splitAtBeatsUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clip on track for beat splits";
    return;
  }
  const c = state.clips.get(ids[0]);
  if (!c?.trackId) {
    $("status-msg").textContent = "No track";
    return;
  }
  try {
    const r = await postJson<{ timeline?: TimelineView }>(
      "/api/split_at_beats",
      {
        track_id: c.trackId,
        media_id: c.mediaId || state.binMediaId || null,
        max_splits: 64,
      },
    );
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = "Split at beats done";
  } catch (e) {
    setProOut(`Beats failed: ${e}`);
    $("status-msg").textContent = `Beats failed: ${e}`;
  }
}

async function markersFromBeatsUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const ids = selectionList();
  const c = ids.length ? state.clips.get(ids[0]) : null;
  $("status-msg").textContent = "Placing beat markers…";
  try {
    const r = await postJson<{
      count?: number;
      bpm_estimate?: number;
      agent_note?: string;
    }>("/api/markers/from_beats", {
      media_id: c?.mediaId || state.binMediaId || null,
      max_markers: 128,
      label_prefix: "Beat",
      clear_existing_prefix: false,
    });
    setProOut(JSON.stringify(r, null, 2));
    await refreshMarkers();
    $("status-msg").textContent =
      `Beat markers · ${r.count ?? 0}` +
      (r.bpm_estimate != null ? ` · ~${Math.round(Number(r.bpm_estimate))} bpm` : "");
  } catch (e) {
    setProOut(`Beat markers failed: ${e}`);
    $("status-msg").textContent = `Beat markers failed: ${e}`;
  }
}

async function beatGridUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const ids = selectionList();
  const c = ids.length ? state.clips.get(ids[0]) : null;
  if (!c?.trackId) {
    $("status-msg").textContent = "Select a clip on the track to beat-grid";
    return;
  }
  $("status-msg").textContent = "Beat grid (markers + razor)…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      bpm_estimate?: number;
      markers?: { count?: number };
      split?: { count?: number };
    }>("/api/edit/beat_grid", {
      track_id: c.trackId,
      media_id: c.mediaId || state.binMediaId || null,
      mode: "both",
      max_beats: 128,
      clear_existing_prefix: true,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    await refreshMarkers();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `BeatGrid · mkr ${r.markers?.count ?? "?"} · cuts ${r.split?.count ?? "?"}` +
      (r.bpm_estimate != null ? ` · ~${Math.round(Number(r.bpm_estimate))} bpm` : "");
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`BeatGrid failed: ${e}`);
    $("status-msg").textContent = `BeatGrid failed: ${e}`;
  }
}

async function sceneGridUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const ids = selectionList();
  const c = ids.length ? state.clips.get(ids[0]) : null;
  if (!c?.trackId) {
    $("status-msg").textContent = "Select a clip on the track to scene-grid";
    return;
  }
  $("status-msg").textContent = "Scene grid (markers + razor)…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      backend?: string;
      markers?: { count?: number };
      split?: { count?: number };
    }>("/api/edit/scene_grid", {
      track_id: c.trackId,
      media_id: c.mediaId || state.binMediaId || null,
      mode: "both",
      max_scenes: 128,
      clear_existing_prefix: true,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    await refreshMarkers();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `SceneGrid · mkr ${r.markers?.count ?? "?"} · cuts ${r.split?.count ?? "?"}` +
      (r.backend ? ` · ${r.backend}` : "");
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`SceneGrid failed: ${e}`);
    $("status-msg").textContent = `SceneGrid failed: ${e}`;
  }
}

async function transitionsNearMarkersUi() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select a clip on the track for X@Mkr";
    return;
  }
  const c = state.clips.get(ids[0]);
  if (!c?.trackId) {
    $("status-msg").textContent = "No track";
    return;
  }
  $("status-msg").textContent = "Dissolves near markers…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
      skipped_count?: number;
    }>("/api/transitions/near_markers", {
      track_id: c.trackId,
      transition_type: "cross_dissolve",
      duration_frames: 12,
      max_delta_frames: 2,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `X@Mkr · ${r.count ?? 0} dissolves` +
      (r.skipped_count ? ` · skip ${r.skipped_count}` : "");
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`X@Mkr failed: ${e}`);
    $("status-msg").textContent = `X@Mkr failed: ${e}`;
  }
}

async function placeAtMarkersUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  if (!state.binMediaId) {
    $("status-msg").textContent = "Select media in the bin first";
    return;
  }
  const ids = selectionList();
  let trackId = ids.length ? state.clips.get(ids[0])?.trackId : "";
  if (!trackId) {
    // first video track from timeline state if available
    const tracks = (state as { tracks?: { id: string; kind?: string }[] }).tracks;
    const vt = Array.isArray(tracks)
      ? tracks.find((t) => t.kind === "video") || tracks[0]
      : null;
    trackId = vt?.id || "";
  }
  if (!trackId) {
    $("status-msg").textContent = "Select a clip on target track (or open project with tracks)";
    return;
  }
  $("status-msg").textContent = "Placing bin media @ markers…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
      skipped_count?: number;
      marker_count?: number;
    }>("/api/place/at_markers", {
      media_ids: [state.binMediaId],
      track_id: trackId,
      mode: "overwrite",
      cycle: true,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `@Mkr · placed ${r.count ?? 0}/${r.marker_count ?? "?"}` +
      (r.skipped_count ? ` · skip ${r.skipped_count}` : "");
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`@Mkr failed: ${e}`);
    $("status-msg").textContent = `@Mkr failed: ${e}`;
  }
}

async function fitToMarkersUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const ids = selectionList();
  const body: Record<string, unknown> = {
    method: "speed",
    max_start_delta: 8,
    clamp: true,
  };
  if (ids.length) {
    body.clip_ids = ids;
  } else {
    const c0 = [...state.clips.values()][0];
    if (!c0?.trackId) {
      $("status-msg").textContent = "Select clips or have clips on a track";
      return;
    }
    body.track_id = c0.trackId;
  }
  $("status-msg").textContent = "Fitting clips to marker slots…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      count?: number;
      skipped_count?: number;
    }>("/api/clips/fit_to_markers", body);
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `FitM · ${r.count ?? 0}` +
      (r.skipped_count ? ` · skip ${r.skipped_count}` : "");
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`FitM failed: ${e}`);
    $("status-msg").textContent = `FitM failed: ${e}`;
  }
}

async function musicBrollUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  if (!state.binMediaId) {
    $("status-msg").textContent = "Select B-roll media in the bin";
    return;
  }
  const ids = selectionList();
  let trackId = ids.length ? state.clips.get(ids[0])?.trackId : "";
  if (!trackId) {
    const tracks = (state as { tracks?: { id: string; kind?: string }[] }).tracks;
    const vt = Array.isArray(tracks)
      ? tracks.find((t) => t.kind === "video") || tracks[0]
      : null;
    trackId = vt?.id || "";
  }
  if (!trackId) {
    $("status-msg").textContent = "Select a clip on the B-roll track";
    return;
  }
  $("status-msg").textContent = "Music B-roll pipeline…";
  try {
    const r = await postJson<{
      timeline?: TimelineView;
      bpm_estimate?: number;
      place?: { count?: number };
      fit?: { count?: number };
      transitions?: { count?: number };
    }>("/api/edit/music_broll", {
      track_id: trackId,
      media_ids: [state.binMediaId],
      max_beats: 64,
      fit_method: "speed",
      transition: "cross_dissolve",
      transition_frames: 8,
      clear_beat_markers: true,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    await refreshMarkers();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `Broll · place ${r.place?.count ?? "?"} · fit ${r.fit?.count ?? "?"}` +
      (r.bpm_estimate != null ? ` · ~${Math.round(Number(r.bpm_estimate))} bpm` : "");
    scheduleProxyRefresh();
  } catch (e) {
    setProOut(`Broll failed: ${e}`);
    $("status-msg").textContent = `Broll failed: ${e}`;
  }
}

async function markerSlotsUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  try {
    const r = await getJson<{
      count?: number;
      slots?: unknown[];
    }>("/api/markers/slots");
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `Slots? · ${r.count ?? 0} marker ranges`;
  } catch (e) {
    $("status-msg").textContent = `Slots failed: ${e}`;
  }
}

async function importSrtMarkersUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const picked = await pickImportFile({
    title: "Import SRT as markers",
    extensions: ["srt"],
  });
  if (!picked) return;
  $("status-msg").textContent = "Importing SRT markers…";
  try {
    const r = await postJson<{
      count?: number;
      cue_count?: number;
    }>("/api/markers/from_srt", {
      path: picked.path || null,
      text: picked.text || null,
      label_from_text: true,
      clear_existing: false,
    });
    await refreshMarkers();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `ImpSRT · ${r.count ?? 0} markers (of ${r.cue_count ?? "?"} cues)`;
  } catch (e) {
    setProOut(`ImpSRT failed: ${e}`);
    $("status-msg").textContent = `ImpSRT failed: ${e}`;
  }
}

async function showSnapPoints() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  try {
    const r = await getJson<Record<string, unknown>>(
      "/api/snap_points?include_markers=true",
    );
    setProOut(JSON.stringify(r, null, 2));
    const n = Array.isArray(r.frames)
      ? r.frames.length
      : Array.isArray(r.snap_frames)
        ? r.snap_frames.length
        : "?";
    $("status-msg").textContent = `Snap points ×${n}`;
  } catch (e) {
    $("status-msg").textContent = `Snap points failed: ${e}`;
  }
}

async function invalidatePreviewUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  try {
    const r = await postJson<Record<string, unknown>>(
      "/api/preview/invalidate",
      {},
    );
    state.proxyFresh = false;
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = "Preview proxy invalidated";
  } catch (e) {
    $("status-msg").textContent = `Invalidate failed: ${e}`;
  }
}

async function clearRecentUi() {
  if (!window.confirm("Clear recent projects list?")) return;
  try {
    const r = await postJson<Record<string, unknown>>("/api/recent/clear", {});
    await refreshRecent();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = "Recent cleared";
  } catch (e) {
    $("status-msg").textContent = `Clear recent failed: ${e}`;
  }
}

async function writeSrtFromMarkersUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  try {
    const r = await postJson<Record<string, unknown>>("/api/write_srt", {
      from_markers: true,
      segments: [],
    });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `SRT → ${r.path || "ok"} (${r.count ?? "?"} cues)`;
  } catch (e) {
    $("status-msg").textContent = `SRT failed: ${e}`;
  }
}

async function binMediaPath(): Promise<string | null> {
  if (!state.binMediaId) return null;
  try {
    const media = await getJson<{
      media?: Array<{ id?: string; abs_path?: string; path?: string }>;
    }>("/api/media");
    const m = (media.media || []).find((x) => x.id === state.binMediaId);
    return m?.abs_path || m?.path || null;
  } catch {
    return null;
  }
}

async function showLooksUi() {
  try {
    const r = await getJson<Record<string, unknown>>("/api/looks");
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = "Look presets";
  } catch (e) {
    $("status-msg").textContent = `Looks failed: ${e}`;
  }
}

async function showEncodeStatusUi() {
  try {
    const r = await getJson<Record<string, unknown>>("/api/encode_status");
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = r.nvenc
      ? "NVENC ready"
      : "Software encode (libx264)";
  } catch (e) {
    $("status-msg").textContent = `Encode status failed: ${e}`;
  }
}

async function detectBeatsUi() {
  const path = await binMediaPath();
  if (!path) {
    $("status-msg").textContent = "Select bin media for beats";
    return;
  }
  try {
    const r = await postJson<Record<string, unknown>>("/api/detect/beats", {
      path,
    });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = "Beats detected";
  } catch (e) {
    setProOut(`Beats failed: ${e}`);
    $("status-msg").textContent = `Beats failed: ${e}`;
  }
}

async function suggestMixUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  try {
    const r = await postJson<Record<string, unknown>>("/api/suggest/mix", {});
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = "Mix plan ready";
  } catch (e) {
    setProOut(`Mix plan failed: ${e}`);
    $("status-msg").textContent = `Mix plan failed: ${e}`;
  }
}

async function colorMatchUi() {
  const ids = selectionList();
  if (ids.length < 1) {
    $("status-msg").textContent = "Select reference clip first (then others)";
    return;
  }
  const ref = ids[0];
  const others = ids.length > 1 ? ids.slice(1) : null;
  try {
    const r = await postJson<{ timeline?: TimelineView }>(
      "/api/clips/color_match",
      {
        reference_clip_id: ref,
        clip_ids: others,
        strength: 0.65,
      },
    );
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `Color match → ${ref}`;
  } catch (e) {
    $("status-msg").textContent = `Color match failed: ${e}`;
  }
}

async function applySilenceUi(dryRun: boolean) {
  const ids = selectionList();
  if (ids.length !== 1) {
    $("status-msg").textContent = "Select one clip for silence cut";
    return;
  }
  if (
    !dryRun &&
    !window.confirm("Apply silence keep-ranges to selection? (undoable)")
  ) {
    return;
  }
  try {
    const r = await postJson<{ timeline?: TimelineView }>(
      "/api/clip/apply_silence",
      { clip_id: ids[0], dry_run: dryRun },
    );
    if (r.timeline) applyTimelineView(r.timeline);
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = dryRun
      ? "Silence plan (dry-run)"
      : "Silence applied";
  } catch (e) {
    $("status-msg").textContent = `Silence failed: ${e}`;
  }
}

async function clipsSharingMediaUi() {
  if (!state.binMediaId) {
    $("status-msg").textContent = "Select bin media";
    return;
  }
  try {
    const r = await getJson<Record<string, unknown>>(
      `/api/media/${encodeURIComponent(state.binMediaId)}/clips`,
    );
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = "Clips sharing media";
  } catch (e) {
    $("status-msg").textContent = `Sharing media failed: ${e}`;
  }
}

async function placeAfterUi() {
  const ids = selectionList();
  if (ids.length !== 1) {
    $("status-msg").textContent = "Select one clip to place after";
    return;
  }
  if (!state.binMediaId) {
    $("status-msg").textContent = "Select bin media to place";
    return;
  }
  try {
    const r = await postJson<{ timeline?: TimelineView }>("/api/place_after", {
      after_clip_id: ids[0],
      media_id: state.binMediaId,
    });
    if (r.timeline) applyTimelineView(r.timeline);
    else await refresh();
    $("status-msg").textContent = "Placed after selection";
    scheduleProxyRefresh();
  } catch (e) {
    $("status-msg").textContent = `Place after failed: ${e}`;
  }
}

async function suggestFpsResUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  try {
    let paths: string[] = [];
    try {
      const media = await getJson<{
        media?: Array<{ abs_path?: string; path?: string }>;
      }>("/api/media");
      paths = (media.media || [])
        .map((m) => m.abs_path || m.path || "")
        .filter(Boolean);
    } catch {
      /* empty */
    }
    const fps = await postJson<Record<string, unknown>>("/api/suggest/fps", {
      paths,
      preference: "auto",
    });
    const res = await postJson<Record<string, unknown>>(
      "/api/suggest/resolution",
      { paths, preference: "auto" },
    );
    setProOut(JSON.stringify({ fps, resolution: res }, null, 2));
    $("status-msg").textContent = "FPS / resolution suggestion";
  } catch (e) {
    $("status-msg").textContent = `Suggest failed: ${e}`;
  }
}

async function deliveryLimitsUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  try {
    const r = await postJson<Record<string, unknown>>("/api/delivery/limits", {
      fps: state.fps,
    });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = "Delivery limits check";
  } catch (e) {
    $("status-msg").textContent = `Delivery limits failed: ${e}`;
  }
}

async function loadTranscriptUi() {
  if (!state.binMediaId) {
    $("status-msg").textContent = "Select bin media";
    return;
  }
  try {
    const r = await getJson<Record<string, unknown>>(
      `/api/media/${encodeURIComponent(state.binMediaId)}/transcript`,
    );
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = r.cached
      ? "Cached transcript"
      : "No cached transcript";
  } catch (e) {
    $("status-msg").textContent = `Transcript failed: ${e}`;
  }
}

async function captionClipUi() {
  const ids = selectionList();
  if (ids.length !== 1) {
    $("status-msg").textContent = "Select one clip for caption";
    return;
  }
  $("status-msg").textContent = "Caption (ASR)…";
  try {
    const r = await postJson<{ timeline?: TimelineView }>("/api/clip/caption", {
      clip_id: ids[0],
      model_size: "base",
    });
    if (r.timeline) applyTimelineView(r.timeline);
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = "Caption applied";
  } catch (e) {
    setProOut(`Caption failed: ${e}`);
    $("status-msg").textContent = `Caption failed: ${e}`;
  }
}

async function exportRangeIoUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const a = state.workIO.in_frame;
  const b = state.workIO.out_frame;
  if (a == null || b == null || b <= a) {
    $("status-msg").textContent = "Set I/O for range export";
    return;
  }
  const fps = Math.max(1, state.fps);
  const start = a / fps;
  const end = b / fps;
  try {
    const r = await postJson<Record<string, unknown>>("/api/export/range", {
      start_seconds: start,
      end_seconds: end,
      normalize_preset: null,
      run_delivery_check: false,
    });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `Range export ${start.toFixed(2)}–${end.toFixed(2)}s`;
  } catch (e) {
    $("status-msg").textContent = `Range export failed: ${e}`;
  }
}

async function previewRangeIoUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const a = state.workIO.in_frame;
  const b = state.workIO.out_frame;
  if (a == null || b == null || b <= a) {
    $("status-msg").textContent = "Set I/O for preview range";
    return;
  }
  const fps = Math.max(1, state.fps);
  try {
    const r = await postJson<Record<string, unknown>>("/api/preview/range", {
      start_seconds: a / fps,
      end_seconds: b / fps,
      height: 360,
      fps: 12,
    });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = "Preview range ready";
  } catch (e) {
    $("status-msg").textContent = `Preview range failed: ${e}`;
  }
}

async function offsetLinkedUi(delta: number) {
  const ids = selectionList();
  if (ids.length !== 1) {
    $("status-msg").textContent = "Select one clip for linked offset";
    return;
  }
  try {
    const r = await postJson<{ timeline?: TimelineView }>(
      "/api/clip/offset_linked",
      { clip_id: ids[0], delta_frames: delta, kinds: ["audio"] },
    );
    if (r.timeline) applyTimelineView(r.timeline);
    $("status-msg").textContent = `Linked offset Δ${delta}`;
  } catch (e) {
    $("status-msg").textContent = `Offset linked failed: ${e}`;
  }
}

async function analyzeAssetUi() {
  const path = await binMediaPath();
  if (!path) {
    $("status-msg").textContent = "Select bin media for asset card";
    return;
  }
  $("status-msg").textContent = "Analyze asset…";
  try {
    const r = await postJson<Record<string, unknown>>("/api/analyze/asset", {
      path,
      do_scenes: true,
      do_silence: true,
      do_motion: true,
      do_transcribe: false,
    });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = "Asset card ready";
  } catch (e) {
    setProOut(`Asset analyze failed: ${e}`);
    $("status-msg").textContent = `Asset analyze failed: ${e}`;
  }
}

async function enrichClipGainOpacity(clipId: string) {
  try {
    const g = await getJson<{ db?: number }>(
      `/api/clip/${encodeURIComponent(clipId)}/gain`,
    );
    const o = await getJson<{ amount?: number }>(
      `/api/clip/${encodeURIComponent(clipId)}/opacity`,
    );
    const card = document.getElementById("sel-card");
    if (card && !card.classList.contains("muted")) {
      let el = document.getElementById("sel-gain-op");
      if (!el) {
        el = document.createElement("div");
        el.id = "sel-gain-op";
        el.className = "kv";
        card.appendChild(el);
      }
      el.textContent = `gain ${g.db ?? "?"} dB · opac ${o.amount ?? "?"}`;
    }
  } catch {
    /* ignore */
  }
}

async function trimClipToIoUi() {
  const ids = selectionList();
  if (ids.length !== 1) {
    $("status-msg").textContent = "Select one clip for source trim";
    return;
  }
  const c = state.clips.get(ids[0]);
  if (!c) {
    $("status-msg").textContent = "Clip not found";
    return;
  }
  // prompt source frames
  const raw = window.prompt(
    "src_in,src_out (source frames)",
    `0,${Math.max(1, c.dur)}`,
  );
  if (raw == null) return;
  const parts = raw.split(",").map((s) => parseInt(s.trim(), 10));
  if (parts.length !== 2 || !parts.every((n) => Number.isFinite(n))) {
    $("status-msg").textContent = "Bad src_in,src_out";
    return;
  }
  try {
    const r = await postJson<{ timeline?: TimelineView }>("/api/clip/trim", {
      clip_id: ids[0],
      src_in: parts[0],
      src_out: parts[1],
    });
    if (r.timeline) applyTimelineView(r.timeline);
    $("status-msg").textContent = `Trim src ${parts[0]}–${parts[1]}`;
  } catch (e) {
    $("status-msg").textContent = `Trim failed: ${e}`;
  }
}

async function slugMediaUi(place: boolean) {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  try {
    const r = await postJson<{ timeline?: TimelineView; media?: { id?: string } }>(
      "/api/media/slug",
      { kind: "video", place, start: place ? playheadFrame() : null },
    );
    if (r.timeline) applyTimelineView(r.timeline);
    await refreshMediaBin();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = place
      ? `Slug placed ${r.media?.id || ""}`
      : `Slug media ${r.media?.id || ""}`;
  } catch (e) {
    $("status-msg").textContent = `Slug failed: ${e}`;
  }
}

async function clipTransitionUi(clear: boolean) {
  const ids = selectionList();
  if (ids.length !== 1) {
    $("status-msg").textContent = "Select one clip for transition";
    return;
  }
  try {
    const r = clear
      ? await postJson<{ timeline?: TimelineView }>(
          "/api/clip/transition/clear",
          { clip_id: ids[0] },
        )
      : await postJson<{ timeline?: TimelineView }>("/api/clip/transition", {
          clip_id: ids[0],
          transition_type: "cross_dissolve",
          duration_frames: 12,
        });
    if (r.timeline) applyTimelineView(r.timeline);
    $("status-msg").textContent = clear ? "Transition cleared" : "Transition +12f";
  } catch (e) {
    $("status-msg").textContent = `Transition failed: ${e}`;
  }
}

async function rippleDeleteRangeIoUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const a = state.workIO.in_frame;
  const b = state.workIO.out_frame;
  if (a == null || b == null || b <= a) {
    $("status-msg").textContent = "Set I/O for ripple delete range";
    return;
  }
  if (!window.confirm(`Ripple delete f${a}–${b}?`)) return;
  try {
    const r = await postJson<{ timeline?: TimelineView }>(
      "/api/ripple_delete_range",
      { start_frame: a, end_frame: b },
    );
    if (r.timeline) applyTimelineView(r.timeline);
    $("status-msg").textContent = `Ripple deleted f${a}–${b}`;
  } catch (e) {
    $("status-msg").textContent = `Ripple range failed: ${e}`;
  }
}

async function markersColorBatchUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  const color = window.prompt("Marker color (#hex)", "#7c9cff");
  if (color == null || !color.trim()) return;
  try {
    const r = await postJson<Record<string, unknown>>(
      "/api/markers/color_batch",
      { color: color.trim() },
    );
    await refreshMarkers();
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `Markers → ${color.trim()}`;
  } catch (e) {
    $("status-msg").textContent = `Marker color failed: ${e}`;
  }
}

async function mediaContactSheetUi() {
  const path = await binMediaPath();
  if (!path) {
    $("status-msg").textContent = "Select bin media for contact sheet";
    return;
  }
  try {
    const r = await postJson<Record<string, unknown>>(
      "/api/media/contact_sheet",
      { path, cols: 3, rows: 3 },
    );
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `Contact sheet → ${r.path || "ok"}`;
  } catch (e) {
    $("status-msg").textContent = `Contact sheet failed: ${e}`;
  }
}

async function loadCachedAssetAnalysisUi() {
  const path = await binMediaPath();
  if (!path) {
    $("status-msg").textContent = "Select bin media";
    return;
  }
  try {
    const r = await postJson<Record<string, unknown>>("/api/asset/analysis", {
      path,
    });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = r.cached
      ? "Cached asset analysis"
      : "No cached analysis — run Asset first";
  } catch (e) {
    $("status-msg").textContent = `Analysis load failed: ${e}`;
  }
}

async function roomToneSuggestUi() {
  const path = await binMediaPath();
  if (!path) {
    $("status-msg").textContent = "Select bin media for room tone";
    return;
  }
  try {
    const r = await postJson<Record<string, unknown>>(
      "/api/room_tone/suggest",
      { path },
    );
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = "Room tone suggest";
  } catch (e) {
    $("status-msg").textContent = `Room tone failed: ${e}`;
  }
}

async function roomToneExtractUi() {
  const path = await binMediaPath();
  if (!path) {
    $("status-msg").textContent = "Select bin media";
    return;
  }
  try {
    const r = await postJson<Record<string, unknown>>(
      "/api/room_tone/extract",
      { path },
    );
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `Room tone extract → ${r.path || r.output_path || "ok"}`;
  } catch (e) {
    $("status-msg").textContent = `Extract room tone failed: ${e}`;
  }
}

async function roomTonePlaceUi() {
  const path = await binMediaPath();
  if (!path) {
    $("status-msg").textContent = "Select bin media (room tone source)";
    return;
  }
  try {
    const r = await postJson<{ timeline?: TimelineView }>(
      "/api/room_tone/place",
      { source_path: path, start_frame: playheadFrame(), gain_db: -8 },
    );
    if (r.timeline) applyTimelineView(r.timeline);
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = "Room tone placed";
  } catch (e) {
    $("status-msg").textContent = `Place room tone failed: ${e}`;
  }
}

async function separateStemsUi() {
  const path = await binMediaPath();
  if (!path) {
    $("status-msg").textContent = "Select bin media for stems";
    return;
  }
  $("status-msg").textContent = "Separating stems (may take a while)…";
  try {
    const r = await postJson<Record<string, unknown>>("/api/stems/separate", {
      path,
      two_stems: "vocals",
      device: "cpu",
    });
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = "Stems separated";
  } catch (e) {
    setProOut(`Stems failed: ${e}`);
    $("status-msg").textContent = `Stems failed: ${e}`;
  }
}

async function extractFrameBinUi() {
  const path = await binMediaPath();
  if (!path) {
    $("status-msg").textContent = "Select bin media";
    return;
  }
  try {
    const r = await postJson<Record<string, unknown>>(
      "/api/media/extract_frame",
      { path, time_seconds: state.t, width: 640 },
    );
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = `Frame → ${r.path || "ok"}`;
  } catch (e) {
    $("status-msg").textContent = `Extract frame failed: ${e}`;
  }
}

async function prepareForExportUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  try {
    const r = await postJson<{ timeline?: TimelineView }>(
      "/api/prepare_for_export",
      { fill_video: true, fill_audio: false, clear_empty_tracks: true },
    );
    if (r.timeline) applyTimelineView(r.timeline);
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = "Prepared for export";
  } catch (e) {
    $("status-msg").textContent = `Prepare failed: ${e}`;
  }
}

async function suggestFillerUi() {
  const ids = selectionList();
  const body: Record<string, unknown> = { use_cache: true, model_size: "base" };
  if (ids.length === 1) body.clip_id = ids[0];
  else if (state.binMediaId) body.media_id = state.binMediaId;
  else {
    $("status-msg").textContent = "Select clip or bin media for filler suggest";
    return;
  }
  try {
    const r = await postJson<Record<string, unknown>>(
      "/api/suggest/filler",
      body,
    );
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = "Filler suggest ready";
  } catch (e) {
    setProOut(`Filler suggest failed: ${e}`);
    $("status-msg").textContent = `Filler suggest failed: ${e}`;
  }
}

async function sessionSummaryUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  try {
    const r = await getJson<Record<string, unknown>>("/api/session/summary");
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent =
      `Session · tracks=${r.track_count ?? "?"} media=${r.media_count ?? "?"}`;
  } catch (e) {
    $("status-msg").textContent = `Session summary failed: ${e}`;
  }
}

async function pathCReportUi() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  try {
    const r = await getJson<{
      path_c_ready?: boolean;
      not_ready_count?: number;
      clips_with_effects?: number;
      adapter_version?: number;
    }>("/api/project/path_c");
    setProOut(JSON.stringify(r, null, 2));
    const ready = r.path_c_ready ? "ready" : `${r.not_ready_count ?? "?"} export-only`;
    $("status-msg").textContent =
      `path-C v${r.adapter_version ?? "?"} · ${r.clips_with_effects ?? 0} FX clips · ${ready}`;
  } catch (e) {
    $("status-msg").textContent = `path-C report failed: ${e}`;
  }
}

async function copyBundlePath() {
  const p = state.bundlePath;
  if (!p) {
    $("status-msg").textContent = "No bundle path";
    return;
  }
  try {
    await navigator.clipboard.writeText(p);
    $("status-msg").textContent = "Bundle path copied";
  } catch {
    window.prompt("Bundle path", p);
  }
}

let healthTimer: ReturnType<typeof setInterval> | 0 = 0;

function startHealthHeartbeat() {
  if (healthTimer) return;
  healthTimer = setInterval(() => {
    if (document.hidden) return;
    void (async () => {
      try {
        const h = await getJson<{ status?: string; project_open?: boolean }>(
          "/api/health",
        );
        setPill(
          "pill-api",
          h.status === "ok" || h.project_open != null ? "ok" : "warn",
          h.project_open ? "API · project" : "API",
        );
      } catch {
        setPill("pill-api", "err", "API down");
      }
    })();
  }, 15000);
}

function updatePlayheadTcFloat() {
  const el = document.getElementById("ph-tc-float");
  if (!el) return;
  el.textContent = framesToTc(playheadFrame(), state.fps);
}

async function showDoctorFull() {
  try {
    const r = await getJson<Record<string, unknown>>(
      "/api/doctor?check_comfy=true",
    );
    setProOut(JSON.stringify(r, null, 2));
    $("status-msg").textContent = r.ok ? "Doctor OK" : "Doctor issues";
  } catch (e) {
    $("status-msg").textContent = `Doctor failed: ${e}`;
  }
}

async function selectSharingMedia() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select a clip first";
    return;
  }
  const c = state.clips.get(ids[0]);
  const mid = c?.mediaId;
  if (!mid) {
    $("status-msg").textContent = "Selection has no media_id";
    return;
  }
  try {
    const r = await getJson<{
      clip_ids?: string[];
      clips?: Array<{ id?: string }>;
    }>(`/api/media/${encodeURIComponent(mid)}/clips`);
    const list =
      r.clip_ids ||
      (r.clips || []).map((x) => x.id || "").filter(Boolean);
    if (!list.length) {
      // local fallback: all clips with same media
      const local: string[] = [];
      state.clips.forEach((info, id) => {
        if (info.mediaId === mid) local.push(id);
      });
      setSelection(local);
      $("status-msg").textContent = `Selected ${local.length} sharing media`;
      return;
    }
    setSelection(list);
    $("status-msg").textContent = `Selected ${list.length} sharing media`;
  } catch (e) {
    $("status-msg").textContent = `Select share failed: ${e}`;
  }
}

function toggleLaneCompact() {
  document.querySelectorAll(".track-lane").forEach((el) => {
    el.classList.toggle("compact");
  });
  const on = document.querySelector(".track-lane.compact") != null;
  $("status-msg").textContent = on ? "Lanes compact" : "Lanes normal";
}

function bumpSessionStats(kind: "edit" | "save" | "gen") {
  const key = `opmiere_sess_${kind}`;
  const n = Number(sessionStorage.getItem(key) || "0") + 1;
  sessionStorage.setItem(key, String(n));
  const el = document.getElementById("session-stats");
  if (!el) return;
  const edits = Number(sessionStorage.getItem("opmiere_sess_edit") || "0");
  const saves = Number(sessionStorage.getItem("opmiere_sess_save") || "0");
  const gens = Number(sessionStorage.getItem("opmiere_sess_gen") || "0");
  el.textContent = `e${edits}/s${saves}/g${gens}`;
}

/** Dump OpenShot multi-clip plan (path-C diagnostics, no render). */
async function showOpenshotPlan() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  try {
    const r = await getJson<Record<string, unknown>>(
      "/api/preview/openshot_plan?height=360",
    );
    const out = document.getElementById("review-out");
    if (out) {
      out.className = "review-out";
      const mapped = Array.isArray(r.mapped) ? r.mapped.join(",") : "—";
      const unsup = Array.isArray(r.unsupported) ? r.unsupported.join(",") : "—";
      const head =
        `adapter v${r.adapter_version ?? "?"} · clips=${r.clip_count ?? "?"} · ` +
        `mapped=[${mapped}] · unsupported=[${unsup}]\n\n`;
      out.textContent = (head + JSON.stringify(r, null, 2)).slice(0, 6000);
    }
    const n =
      (Array.isArray(r.clips) && r.clips.length) ||
      (Array.isArray(r.layers) && r.layers.length) ||
      r.clip_count ||
      "?";
    $("status-msg").textContent =
      `OpenShot plan · clips=${n} · mapped=${(r.mapped as string[] | undefined)?.length ?? 0}`;
  } catch (e) {
    $("status-msg").textContent = `OpenShot plan failed: ${e}`;
  }
}

function hideClipMenu() {
  const menu = document.getElementById("clip-menu");
  if (menu) menu.hidden = true;
}

function openClipMenu(x: number, y: number) {
  const menu = document.getElementById("clip-menu");
  if (!menu) return;
  menu.hidden = false;
  const pad = 8;
  const mw = menu.offsetWidth || 160;
  const mh = menu.offsetHeight || 180;
  const left = Math.min(x, window.innerWidth - mw - pad);
  const top = Math.min(y, window.innerHeight - mh - pad);
  menu.style.left = `${Math.max(pad, left)}px`;
  menu.style.top = `${Math.max(pad, top)}px`;
}

async function runClipMenuAction(act: string) {
  hideClipMenu();
  const ids = selectionList();
  if (!ids.length && act !== "razor") {
    $("status-msg").textContent = "No clip selected";
    return;
  }
  switch (act) {
    case "rename":
      void renameSelection();
      break;
    case "mute":
      void muteSelection();
      break;
    case "razor":
      stopPlay();
      void razorAtPlayhead();
      break;
    case "copy":
      void copySelection();
      break;
    case "duplicate":
      void duplicateSelection();
      break;
    case "match":
      void matchFrameAtPlayhead();
      break;
    case "delete":
      stopPlay();
      void deleteSelection();
      break;
    default:
      break;
  }
}

/** Grab path-C OpenShot frame at playhead into Review status (if installed). */
async function grabOpenshotFrame() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  stopPlay();
  $("status-msg").textContent = "OpenShot frame…";
  try {
    const r = await postJson<{
      ok?: boolean;
      path?: string;
      error?: string;
      mode?: string;
    }>("/api/preview/openshot_frame", {
      time_seconds: state.t,
      height: 360,
      use_timeline: true,
    });
    const out = document.getElementById("review-out");
    if (out) {
      out.className = "review-out";
      out.textContent = JSON.stringify(r, null, 2).slice(0, 2000);
    }
    if (r.path) {
      // Prefer program still via proxy/openshot engine select when available
      const q = new URLSearchParams({
        t: String(state.t),
        width: "640",
        engine: "openshot",
        _: String(Date.now()),
      });
      const img = $("program-img") as HTMLImageElement;
      img.src = `${API_BASE}/api/preview/frame.jpg?${q.toString()}`;
      showProgramImage(img.src);
      $("frame-mode").textContent = "openshot/frame";
      $("status-msg").textContent = `OpenShot frame @ ${state.t.toFixed(2)}s`;
    } else {
      $("status-msg").textContent =
        r.error || `OpenShot frame: ${JSON.stringify(r).slice(0, 80)}`;
    }
  } catch (e) {
    $("status-msg").textContent = `OpenShot frame failed: ${e}`;
  }
}

async function ensureProxy(force = false) {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  stopPlay();
  $("status-msg").textContent = force
    ? "Force-building preview proxy…"
    : "Building preview proxy…";
  const btn = document.getElementById("btn-proxy") as HTMLButtonElement | null;
  if (btn) btn.disabled = true;
  try {
    if (force) {
      // Full export_preview path (rebuild graph even if cache looks fresh).
      const r = await postJson<{
        path?: string;
        output_path?: string;
        height?: number;
        fps?: number;
      }>("/api/preview/build", {
        height: 360,
        fps: 12,
        force: true,
      });
      state.proxyFresh = true;
      $("status-msg").textContent =
        `Proxy rebuilt: ${r.path || r.output_path || "ok"}`;
    } else {
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
    }
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

/** Fit full sequence into visible timeline body width. */
function zoomFitSequence() {
  if (!state.projectOpen || state.durationFrames <= 0) {
    setZoom(1);
    return;
  }
  setZoom(1);
  $("status-msg").textContent = "Zoom fit sequence (1×)";
}

/** Zoom so selection spans ~70% of viewport; scroll playhead into view. */
function zoomToSelection() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clip(s) to zoom";
    return;
  }
  let minF = Infinity;
  let maxF = 0;
  for (const id of ids) {
    const c = state.clips.get(id);
    if (!c) continue;
    minF = Math.min(minF, c.start);
    maxF = Math.max(maxF, c.start + c.dur);
  }
  if (!Number.isFinite(minF) || maxF <= minF) {
    $("status-msg").textContent = "Selection has no duration";
    return;
  }
  const span = maxF - minF;
  const total = Math.max(1, state.durationFrames);
  // Want selection ~70% of view → zoom = 0.7 * total / span
  const z = Math.max(0.5, Math.min(8, (0.7 * total) / span));
  setZoom(z);
  // Seek to selection start so it's on-screen
  void seekTo(minF / Math.max(1, state.fps));
  // scroll timeline body horizontally toward selection
  const body = document.getElementById("timeline-body");
  if (body) {
    const ratio = minF / total;
    body.scrollLeft = Math.max(0, ratio * body.scrollWidth * state.zoom - body.clientWidth * 0.15);
  }
  $("status-msg").textContent = `Zoom ${state.zoom.toFixed(1)}× → selection`;
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
  if (open) void enrichHelpFromKeymap();
}

/** Merge server keymap into help grid (once per open if empty server section). */
async function enrichHelpFromKeymap() {
  const grid = document.querySelector(".help-grid");
  if (!grid || grid.querySelector("[data-from-api]")) return;
  try {
    const r = await getJson<{
      shortcuts?: Array<{ keys?: string; action?: string }>;
    }>("/api/help/keymap");
    const list = r.shortcuts || [];
    if (!list.length) return;
    const sep = document.createElement("div");
    sep.dataset.fromApi = "1";
    sep.style.gridColumn = "1 / -1";
    sep.style.marginTop = "8px";
    sep.style.opacity = "0.7";
    sep.textContent = "— core keymap —";
    grid.appendChild(sep);
    for (const s of list.slice(0, 24)) {
      const row = document.createElement("div");
      row.dataset.fromApi = "1";
      row.innerHTML = `<kbd>${escapeHtml(s.keys || "?")}</kbd> ${escapeHtml(s.action || "")}`;
      grid.appendChild(row);
    }
  } catch {
    /* offline */
  }
}

async function ensureAllMediaProxies(force = false) {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  $("status-msg").textContent = "Building media proxies…";
  try {
    const res = await fetch(
      `${API_BASE}/api/media/proxies?height=480&force=${force}`,
      { method: "POST", headers: { Accept: "application/json" } },
    );
    if (!res.ok) {
      const t = await res.text();
      throw new Error(`HTTP ${res.status}: ${t.slice(0, 160)}`);
    }
    const body = (await res.json()) as {
      count?: number;
      ready?: number;
      results?: unknown[];
      built?: number;
    };
    await refreshMediaBin();
    $("status-msg").textContent =
      `Media proxies: ${body.count ?? body.built ?? body.ready ?? body.results?.length ?? "ok"}`;
  } catch (e) {
    $("status-msg").textContent = `Media proxies failed: ${e}`;
  }
}

/** Build proxy for the single media selected in the bin. */
async function ensureBinMediaProxy(force = false) {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  if (!state.binMediaId) {
    $("status-msg").textContent = "Select media in bin first";
    return;
  }
  $("status-msg").textContent = `Proxy ${state.binMediaId}…`;
  try {
    const r = await postJson<{
      media_id?: string;
      path?: string;
      ready?: boolean;
      built?: boolean;
      height?: number;
    }>("/api/media/proxy", {
      media_id: state.binMediaId,
      height: 480,
      force,
    });
    await refreshMediaBin();
    $("status-msg").textContent =
      `Proxy ${r.media_id || state.binMediaId}: ${r.path ? "ready" : JSON.stringify(r).slice(0, 80)}`;
  } catch (e) {
    $("status-msg").textContent = `Media proxy failed: ${e}`;
  }
}

/** Inventory LUTs / audio beds on style asset search path. */
async function showStyleAssets() {
  try {
    const r = await getJson<{
      search_dirs?: string[];
      luts?: string[];
      audio?: string[];
    }>("/api/style_assets");
    const out = document.getElementById("review-out");
    if (out) {
      out.className = "review-out";
      const luts = r.luts || [];
      const audio = r.audio || [];
      const dirs = r.search_dirs || [];
      const lines = [
        `dirs (${dirs.length}):`,
        ...dirs.map((d) => `  ${d}`),
        `luts (${luts.length}):`,
        ...luts.slice(0, 24).map((p) => `  ${p.split(/[/\\]/).pop() || p}`),
        `audio (${audio.length}):`,
        ...audio.slice(0, 24).map((p) => `  ${p.split(/[/\\]/).pop() || p}`),
      ];
      out.textContent = lines.join("\n").slice(0, 4000);
    }
    $("status-msg").textContent =
      `Style assets: ${(r.luts || []).length} LUT · ${(r.audio || []).length} audio`;
  } catch (e) {
    $("status-msg").textContent = `Style assets failed: ${e}`;
  }
}

/** Evenly spaced review keyframes — agent API + visual strip via frame.jpg. */
async function reviewKeyframesUi(count = 5) {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  if (state.durationSec <= 0) {
    $("status-msg").textContent = "Empty timeline — nothing to review";
    return;
  }
  stopPlay();
  $("status-msg").textContent = "Building keyframes…";
  try {
    const res = await fetch(
      `${API_BASE}/api/preview/keyframes?count=${count}&width=320`,
      { method: "POST", headers: { Accept: "application/json" } },
    );
    if (!res.ok) {
      const t = await res.text();
      throw new Error(`HTTP ${res.status}: ${t.slice(0, 160)}`);
    }
    const body = (await res.json()) as {
      count?: number;
      duration_seconds?: number;
      frames?: Array<{ index?: number; time_seconds?: number; path?: string }>;
      agent_note?: string;
    };
    const frames = body.frames || [];
    const out = document.getElementById("review-out");
    if (out) {
      out.className = "review-out";
      out.textContent = [
        `keyframes ×${body.count ?? frames.length} · ${body.duration_seconds ?? "?"}s`,
        ...frames.map(
          (f) =>
            `  #${f.index ?? "?"}  t=${f.time_seconds ?? "?"}s  ${f.path || ""}`,
        ),
        body.agent_note || "",
      ]
        .join("\n")
        .slice(0, 4000);
    }
    const strip = document.getElementById("keyframe-strip");
    if (strip) {
      strip.hidden = false;
      strip.className = "keyframe-strip";
      strip.innerHTML = "";
      for (const f of frames) {
        const t = Number(f.time_seconds ?? 0);
        const cell = document.createElement("div");
        cell.className = "kf-cell";
        const img = document.createElement("img");
        img.alt = `t=${t}`;
        img.loading = "lazy";
        const q = new URLSearchParams({
          t: String(t),
          width: "160",
          engine: "proxy",
          _: String(Date.now()),
        });
        img.src = `${API_BASE}/api/preview/frame.jpg?${q.toString()}`;
        img.title = `Seek ${t.toFixed(2)}s`;
        img.addEventListener("click", () => {
          stopPlay();
          void seekTo(t);
        });
        const lab = document.createElement("div");
        lab.className = "kf-t";
        lab.textContent = `${t.toFixed(2)}s`;
        cell.appendChild(img);
        cell.appendChild(lab);
        strip.appendChild(cell);
      }
      if (!frames.length) {
        strip.className = "keyframe-strip muted";
        strip.textContent = "No frames";
      }
    }
    $("status-msg").textContent =
      `Keyframes ×${body.count ?? frames.length} (click strip to seek)`;
  } catch (e) {
    $("status-msg").textContent = `Keyframes failed: ${e}`;
  }
}

/** Trim each selected clip to the current I/O range on the timeline. */
async function trimSelectionToIO() {
  const ids = selectionList();
  if (!ids.length) {
    $("status-msg").textContent = "Select clip(s) for Trim I/O";
    return;
  }
  const a = state.workIO.in_frame;
  const b = state.workIO.out_frame;
  if (a == null || b == null || b <= a) {
    $("status-msg").textContent = "Set I and O first (I/O range)";
    return;
  }
  const mode = rippleEnabled() ? "ripple" : "normal";
  $("status-msg").textContent = `Trim I/O f${a}–${b} (${mode})…`;
  try {
    let last: TimelineView | undefined;
    for (const clipId of ids) {
      const r = await postJson<{ timeline?: TimelineView }>(
        "/api/clip/trim_range",
        {
          clip_id: clipId,
          start_frame: a,
          end_frame: b,
          mode,
        },
      );
      if (r.timeline) last = r.timeline;
    }
    if (last) applyTimelineView(last);
    else await refresh();
    $("status-msg").textContent =
      `Trim I/O f${a}–${b} ×${ids.length} (${mode})`;
    void seekTo(state.t);
  } catch (e) {
    $("status-msg").textContent = `Trim I/O failed: ${e}`;
  }
}

async function showWorkflow() {
  try {
    const r = await getJson<Record<string, unknown>>("/api/workflow");
    const out = document.getElementById("review-out");
    if (out) {
      out.className = "review-out";
      const wf = r.workflow;
      out.textContent =
        typeof wf === "string"
          ? wf.slice(0, 4000)
          : JSON.stringify(r, null, 2).slice(0, 4000);
    }
    $("status-msg").textContent = `Workflow v${r.version ?? "?"}`;
  } catch (e) {
    $("status-msg").textContent = `Workflow failed: ${e}`;
  }
}

async function makeBriefUi() {
  const intent = window.prompt(
    "Creative intent for director brief (empty = defaults)",
    "",
  );
  if (intent == null) return;
  $("status-msg").textContent = "Building brief…";
  try {
    // assets from bin abs paths
    let assets: Array<{ path: string; role?: string }> = [];
    try {
      const media = await getJson<{
        media?: Array<{ abs_path?: string; path?: string; kind?: string }>;
      }>("/api/media");
      assets = (media.media || [])
        .map((m) => ({
          path: m.abs_path || m.path || "",
          role: m.kind === "audio" ? "music" : "a_roll",
        }))
        .filter((a) => a.path);
    } catch {
      /* no project */
    }
    const r = await postJson<Record<string, unknown>>("/api/brief", {
      intent: intent.trim() || null,
      assets,
      constraints: {},
      deliverable: {},
    });
    const out = document.getElementById("review-out");
    if (out) {
      out.className = "review-out";
      out.textContent = JSON.stringify(r, null, 2).slice(0, 4000);
    }
    $("status-msg").textContent = "Brief + plan ready (see Review)";
  } catch (e) {
    $("status-msg").textContent = `Brief failed: ${e}`;
  }
}

async function renameMarker(markerId: string, current: string) {
  const label = window.prompt("Marker label", current);
  if (label == null) return;
  try {
    const r = await postJson<{ markers?: Marker[] }>("/api/markers/update", {
      marker_id: markerId,
      label: label.trim(),
    });
    state.markers = r.markers || state.markers;
    renderMarkerList();
    $("status-msg").textContent = `Marker → ${label.trim() || "(empty)"}`;
  } catch (e) {
    $("status-msg").textContent = `Marker update failed: ${e}`;
  }
}

async function syncDirtyFromApi() {
  if (!state.projectOpen) return;
  try {
    const r = await getJson<{ dirty?: boolean; autosave?: boolean }>(
      "/api/dirty",
    );
    if (typeof r.dirty === "boolean") {
      state.dirty = r.dirty;
      const dirtyPill = document.getElementById("pill-dirty");
      if (dirtyPill) {
        dirtyPill.className = `pill ${state.dirty ? "warn" : "ok"}`;
        dirtyPill.textContent = state.dirty ? "dirty" : "clean";
      }
    }
    if (typeof r.autosave === "boolean") syncAutosaveUi(r.autosave);
  } catch {
    /* ignore */
  }
}

async function jumpNearMarker(direction: "next" | "prev") {
  if (!state.projectOpen) return;
  try {
    const r = await postJson<{
      marker?: Marker | null;
      frame?: number;
      found?: boolean;
    }>("/api/markers/near", {
      frame: playheadFrame(),
      direction,
      wrap: true,
    });
    const f = r.marker?.frame ?? r.frame;
    if (f == null || r.found === false) {
      $("status-msg").textContent = `No ${direction} marker`;
      return;
    }
    stopPlay();
    void seekTo(Number(f) / Math.max(1, state.fps));
    $("status-msg").textContent =
      `Marker ${r.marker?.label || f} (${direction})`;
  } catch (e) {
    $("status-msg").textContent = `Near marker failed: ${e}`;
  }
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
  block.addEventListener("contextmenu", (ev) => {
    ev.preventDefault();
    ev.stopPropagation();
    if (!state.selected.has(c.id) || state.selected.size === 0) {
      setSelection([c.id]);
    } else if (!state.selected.has(c.id)) {
      setSelection([c.id]);
    }
    openClipMenu(ev.clientX, ev.clientY);
  });

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
        mediaId: c.media_id,
        hasAudio: !!c.has_audio_media || tr.kind === "audio",
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
    wireLaneMediaDrop(lane, tr.id, tr.kind);
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
      if (c.media_id) block.dataset.mediaId = c.media_id;
      const hasAudio = !!c.has_audio_media || tr.kind === "audio";
      if (hasAudio) block.dataset.hasAudio = "1";
      {
        const t0 = framesToTc(start, state.fps);
        const t1 = framesToTc(start + dur, state.fps);
        const nm = c.name || c.label || c.id;
        block.title = [
          nm,
          `${t0} → ${t1} (${dur}f)`,
          `spd ${c.speed ?? 1}× · gain ${c.gain_db ?? 0}dB · α ${c.opacity ?? 1}`,
          c.muted ? "muted" : "",
          c.link_group ? `link ${c.link_group}` : "",
          "drag · edges · right-click menu",
        ]
          .filter(Boolean)
          .join("\n");
      }
      if (hasAudio && c.media_id) {
        const wave = document.createElement("canvas");
        wave.className = "clip-wave";
        wave.dataset.mediaId = c.media_id;
        block.appendChild(wave);
      }
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
      if (marqueeSuppressClick) return;
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
  // marquee node is wiped by innerHTML — re-create shell only
  ensureMarqueeEl(body);
  applyZoomToLanes();
  setPlayheadUi();
  $("sel-count").textContent = String(state.selected.size);
  updateSelectionCard();
  scheduleWaveformLoad();
}

function ensureMarqueeEl(body: HTMLElement): HTMLElement {
  let mq = body.querySelector("#marquee") as HTMLElement | null;
  if (!mq) {
    mq = document.createElement("div");
    mq.id = "marquee";
    body.appendChild(mq);
  }
  return mq;
}

/** Drag empty lane space to rubber-band select clips. Wire once on #timeline-body. */
function wireTimelineMarquee(body: HTMLElement) {
  if (body.dataset.marqueeWired === "1") return;
  body.dataset.marqueeWired = "1";
  body.style.position = "relative";
  ensureMarqueeEl(body);

  body.addEventListener("pointerdown", (ev) => {
    if (ev.button !== 0) return;
    if (state.drag) return;
    const t = ev.target as HTMLElement;
    if (
      t.closest(".clip-block") ||
      t.closest("button") ||
      t.closest(".track-flags") ||
      t.closest(".track-label")
    ) {
      return;
    }
    if (!t.closest(".track-lane") && !t.closest(".marker-ruler")) return;
    const rect = body.getBoundingClientRect();
    marqueeDrag = {
      x0: ev.clientX - rect.left + body.scrollLeft,
      y0: ev.clientY - rect.top + body.scrollTop,
      additive: ev.shiftKey || ev.ctrlKey || ev.metaKey,
      moved: false,
    };
    const mq = ensureMarqueeEl(body);
    mq.classList.add("on");
    mq.style.left = `${marqueeDrag.x0}px`;
    mq.style.top = `${marqueeDrag.y0}px`;
    mq.style.width = "0px";
    mq.style.height = "0px";
    try {
      body.setPointerCapture(ev.pointerId);
    } catch {
      /* ignore */
    }
  });

  body.addEventListener("pointermove", (ev) => {
    if (!marqueeDrag) return;
    const rect = body.getBoundingClientRect();
    const x1 = ev.clientX - rect.left + body.scrollLeft;
    const y1 = ev.clientY - rect.top + body.scrollTop;
    const L = Math.min(marqueeDrag.x0, x1);
    const T = Math.min(marqueeDrag.y0, y1);
    const W = Math.abs(x1 - marqueeDrag.x0);
    const H = Math.abs(y1 - marqueeDrag.y0);
    if (W > 4 || H > 4) marqueeDrag.moved = true;
    const mq = ensureMarqueeEl(body);
    mq.style.left = `${L}px`;
    mq.style.top = `${T}px`;
    mq.style.width = `${W}px`;
    mq.style.height = `${H}px`;
  });

  const endMarquee = (ev: PointerEvent) => {
    if (!marqueeDrag) return;
    const drag = marqueeDrag;
    marqueeDrag = null;
    const mq = body.querySelector("#marquee") as HTMLElement | null;
    mq?.classList.remove("on");
    try {
      body.releasePointerCapture(ev.pointerId);
    } catch {
      /* ignore */
    }
    if (!drag.moved) return;
    marqueeSuppressClick = true;
    setTimeout(() => {
      marqueeSuppressClick = false;
    }, 0);

    const rect = body.getBoundingClientRect();
    const x1 = ev.clientX - rect.left + body.scrollLeft;
    const y1 = ev.clientY - rect.top + body.scrollTop;
    const L = Math.min(drag.x0, x1);
    const T = Math.min(drag.y0, y1);
    const R = Math.max(drag.x0, x1);
    const B = Math.max(drag.y0, y1);

    const hits: string[] = [];
    body.querySelectorAll<HTMLElement>(".clip-block[data-clip-id]").forEach((el) => {
      const r = el.getBoundingClientRect();
      const elL = r.left - rect.left + body.scrollLeft;
      const elT = r.top - rect.top + body.scrollTop;
      const elR = elL + r.width;
      const elB = elT + r.height;
      if (elL < R && elR > L && elT < B && elB > T && el.dataset.clipId) {
        hits.push(el.dataset.clipId);
      }
    });
    if (!hits.length) {
      if (!drag.additive) setSelection([]);
      $("status-msg").textContent = "Marquee: 0 clips";
      return;
    }
    if (drag.additive) {
      const merged = new Set(state.selected);
      for (const id of hits) merged.add(id);
      setSelection([...merged]);
    } else {
      setSelection(hits);
    }
    $("status-msg").textContent = `Marquee: ${state.selected.size} clip(s)`;
  };

  body.addEventListener("pointerup", endMarquee);
  body.addEventListener("pointercancel", () => {
    marqueeDrag = null;
    body.querySelector("#marquee")?.classList.remove("on");
  });
}

function toggleProgramFullscreen() {
  const frame = document.querySelector(".program-frame") as HTMLElement | null;
  if (!frame) return;
  if (!document.fullscreenElement) {
    void frame.requestFullscreen?.().catch((e) => {
      $("status-msg").textContent = `Fullscreen failed: ${e}`;
    });
  } else {
    void document.exitFullscreen?.();
  }
}

async function createDemoProject() {
  stopPlay();
  if (!(await confirmLeaveDirty("open demo"))) return;
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
    scheduleProxyRefresh();
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
  if (!(await confirmLeaveDirty("open another project"))) return;
  const path = await pickProjectFolder({
    title: "Open Opmiere project folder (.opm)",
  });
  if (!path) return;
  await openProjectAt(path);
}

async function newProjectPath() {
  stopPlay();
  if (!(await confirmLeaveDirty("create a new project"))) return;
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

type EnsureCoreResult = {
  ok: boolean;
  started: boolean;
  alreadyUp: boolean;
  message: string;
  pid?: number | null;
  python?: string | null;
};

/** Tauri: spawn python -m opmiere.web.app when :8787 is down. */
async function tryEnsureCoreApi(): Promise<EnsureCoreResult | null> {
  if (!isTauri()) return null;
  try {
    const { invoke } = await import("@tauri-apps/api/core");
    return await invoke<EnsureCoreResult>("ensure_core_api");
  } catch (e) {
    console.warn("ensure_core_api invoke failed", e);
    return {
      ok: false,
      started: false,
      alreadyUp: false,
      message: String(e),
    };
  }
}

async function setShellTitle(projectLabel?: string | null) {
  const title = projectLabel?.trim()
    ? `Opmiere — ${projectLabel.trim()}`
    : "Opmiere";
  document.title = title;
  if (!isTauri()) return;
  try {
    const { getCurrentWindow } = await import("@tauri-apps/api/window");
    await getCurrentWindow().setTitle(title);
  } catch (e) {
    console.warn("setTitle failed", e);
  }
}

function projectLabelFromPath(path: string): string {
  const parts = path.split(/[/\\]/).filter(Boolean);
  if (!parts.length) return "project";
  const last = parts[parts.length - 1];
  // .opm is often a folder named foo.opm
  return last || parts[parts.length - 2] || path;
}

async function maybeAutoOpenRecent() {
  if (state.didAutoOpenRecent || state.projectOpen) return;
  state.didAutoOpenRecent = true;
  try {
    const r = await getJson<{
      projects?: Array<{ path?: string; label?: string }>;
    }>("/api/recent?limit=8");
    const candidates = (r.projects || [])
      .map((p) => p.path || "")
      .filter(Boolean);
    for (const path of candidates) {
      try {
        $("status-msg").textContent = `Reopening ${projectLabelFromPath(path)}…`;
        await postJson("/api/project/open", { bundle_path: path });
        state.t = 0;
        await refresh();
        return;
      } catch {
        // skip missing/stale recent entries
      }
    }
  } catch {
    // recent n/a
  }
}

async function refresh() {
  stopPlay();
  $("api-url").textContent = API_BASE;
  $("status-msg").textContent = "Refreshing…";
  try {
    let health: Health;
    try {
      health = await getJson<Health>("/api/health");
    } catch (first) {
      // Desktop product path: try to start local core once, then retry.
      $("status-msg").textContent = "Core API down — starting…";
      const ensured = await tryEnsureCoreApi();
      if (ensured?.ok || ensured?.started) {
        $("status-msg").textContent = ensured.message;
        health = await getJson<Health>("/api/health");
      } else {
        throw first;
      }
    }
    setPill("pill-api", "ok", "API up");
    state.projectOpen = !!health.project_open;
    $("project-state").textContent = state.projectOpen ? "open" : "none";
    $("core-version").textContent = `core ${health.phase || "?"} · product shell`;

    try {
      // check_comfy=true so generation pill reflects live ComfyUI reachability
      const doctor = await getJson<Doctor>("/api/doctor?check_comfy=true");
      $("doctor-ok").textContent = doctor.ok ? "ok" : "issues";
      $("doctor-ok").style.color = doctor.ok
        ? "var(--color-success)"
        : "var(--color-warning)";
      const comfy = (doctor.checks || []).find((c) => c.id === "comfyui");
      const pill = document.getElementById("pill-comfy");
      if (pill) {
        if (!comfy) {
          pill.className = "pill";
          pill.textContent = "comfy —";
          pill.title = "ComfyUI check missing";
        } else if (comfy.ok) {
          pill.className = "pill ok";
          pill.textContent = "comfy up";
          pill.title = comfy.detail || "ComfyUI reachable";
        } else {
          pill.className = "pill warn";
          pill.textContent = "comfy off";
          pill.title =
            comfy.detail || "ComfyUI not listening — generation disabled";
        }
      }
    } catch {
      $("doctor-ok").textContent = "n/a";
      const pill = document.getElementById("pill-comfy");
      if (pill) {
        pill.className = "pill";
        pill.textContent = "comfy —";
      }
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
    // path-C effect adapter version (maps grade FX for still program monitor)
    try {
      const cat = await getJson<{
        adapter_version?: number;
        mapped?: string[];
        unmapped?: string[];
      }>("/api/preview/openshot_effects");
      const ver = cat.adapter_version ?? "?";
      const nMap = Array.isArray(cat.mapped) ? cat.mapped.length : 0;
      const nSkip = Array.isArray(cat.unmapped) ? cat.unmapped.length : 0;
      const pathcOk =
        preview?.active_backend === "libopenshot" ||
        preview?.openshot_app_present === true;
      setPill(
        "pill-pathc",
        pathcOk ? "ok" : "warn",
        `path-C v${ver}`,
      );
      const pathcEl = document.getElementById("pill-pathc");
      if (pathcEl) {
        pathcEl.title = `OpenShot path-C adapter v${ver} · ${nMap} mapped · ${nSkip} export-only`;
      }
    } catch {
      setPill("pill-pathc", "warn", "path-C —");
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
      void setShellTitle(
        state.bundlePath
          ? projectLabelFromPath(state.bundlePath)
          : "project",
      );
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
      void setShellTitle(null);
      // First connect with empty editor: reopen last good recent once.
      await maybeAutoOpenRecent();
      if (!state.projectOpen) $("status-msg").textContent = "Ready";
      return;
    }

    $("status-msg").textContent = "Ready";
    void syncDirtyFromApi();
  } catch (e) {
    setPill("pill-api", "err", "API down");
    setPill("pill-preview", "err", "preview n/a");
    $("status-msg").textContent =
      `Core API unreachable at ${API_BASE}. Install Opmiere or run opmiere web / scripts/dev-desktop.ps1`;
    $("project-state").textContent = "—";
    state.projectOpen = false;
    void setShellTitle(null);
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
    if (ev.altKey) {
      const d = ev.shiftKey ? -5 : -1;
      if (ev.ctrlKey || ev.metaKey) void rippleNudgeSelection(d);
      else void nudgeSelection(d);
      return;
    }
    if (ev.shiftKey) goToMarker(-1);
    else void seekTo(state.t - 1 / state.fps);
    return;
  }
  if (ev.key === "ArrowRight") {
    ev.preventDefault();
    stopPlay();
    if (ev.altKey) {
      const d = ev.shiftKey ? 5 : 1;
      if (ev.ctrlKey || ev.metaKey) void rippleNudgeSelection(d);
      else void nudgeSelection(d);
      return;
    }
    if (ev.shiftKey) goToMarker(1);
    else void seekTo(state.t + 1 / state.fps);
    return;
  }
  // [ ] insert 15f / 1s at playhead
  if (k === "[" && !ev.ctrlKey && !ev.metaKey && !ev.altKey) {
    ev.preventDefault();
    stopPlay();
    void insertTimeAtPlayhead(ev.shiftKey ? Math.max(1, Math.round(state.fps)) : 15);
    return;
  }
  if (k === "]" && !ev.ctrlKey && !ev.metaKey && !ev.altKey && !ev.shiftKey) {
    ev.preventDefault();
    stopPlay();
    void insertTimeAtPlayhead(Math.max(1, Math.round(state.fps)));
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
  if ((ev.ctrlKey || ev.metaKey) && ev.shiftKey && k === "p") {
    ev.preventDefault();
    void runAgentPreflight();
    return;
  }
  if ((ev.ctrlKey || ev.metaKey) && ev.shiftKey && k === "d") {
    ev.preventDefault();
    void showDoctorFull();
    return;
  }
  if ((ev.ctrlKey || ev.metaKey) && k === "w") {
    ev.preventDefault();
    void closeProject();
    return;
  }
  if ((ev.ctrlKey || ev.metaKey) && k === "g") {
    ev.preventDefault();
    void jumpToTimecode();
    return;
  }
  if ((ev.ctrlKey || ev.metaKey) && k === "i") {
    ev.preventDefault();
    void startImport();
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
  if (k === "f" && !ev.ctrlKey && !ev.metaKey && !ev.altKey && ev.shiftKey) {
    ev.preventDefault();
    toggleProgramFullscreen();
    return;
  }
  if (k === "f" && !ev.ctrlKey && !ev.metaKey && !ev.altKey && !ev.shiftKey) {
    ev.preventDefault();
    void matchFrameAtPlayhead();
    return;
  }
  if (ev.key === "Home" && !ev.ctrlKey && !ev.metaKey) {
    ev.preventDefault();
    stopPlay();
    void seekTo(0);
    return;
  }
  if (ev.key === "End" && !ev.ctrlKey && !ev.metaKey) {
    ev.preventDefault();
    stopPlay();
    void seekTo(Math.max(0, state.durationSec));
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
  if (k === "z" && !ev.ctrlKey && !ev.metaKey && !ev.altKey) {
    ev.preventDefault();
    if (ev.shiftKey) zoomFitSequence();
    else zoomToSelection();
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
  // Plain `.` toggles insert/overwrite place mode (NLE three-point habit)
  if (k === "." && !ev.ctrlKey && !ev.metaKey && !ev.altKey && !ev.shiftKey) {
    ev.preventDefault();
    const el = document.getElementById("chk-overwrite") as HTMLInputElement | null;
    if (el) {
      el.checked = !el.checked;
      state.editMode = el.checked ? "overwrite" : "insert";
      $("status-msg").textContent = `Place mode: ${state.editMode}`;
    }
    return;
  }
  if (ev.key === "Escape") {
    const menu = document.getElementById("clip-menu");
    if (menu && !menu.hidden) {
      hideClipMenu();
      return;
    }
    const help = document.getElementById("help-overlay");
    if (help?.classList.contains("open")) {
      help.classList.remove("open");
      help.setAttribute("aria-hidden", "true");
      return;
    }
    if (document.fullscreenElement) {
      void document.exitFullscreen?.();
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
  const clipMenu = document.getElementById("clip-menu");
  if (clipMenu) {
    clipMenu.addEventListener("click", (ev) => {
      const btn = (ev.target as HTMLElement).closest("button[data-act]") as
        | HTMLButtonElement
        | null;
      if (!btn?.dataset.act) return;
      void runClipMenuAction(btn.dataset.act);
    });
  }
  document.addEventListener("pointerdown", (ev) => {
    const menu = document.getElementById("clip-menu");
    if (!menu || menu.hidden) return;
    if (menu.contains(ev.target as Node)) return;
    hideClipMenu();
  });
  window.addEventListener("blur", () => hideClipMenu());
  window.addEventListener("resize", () => hideClipMenu());
  $("btn-demo").addEventListener("click", () => {
    void createDemoProject();
  });
  $("btn-open").addEventListener("click", () => {
    void openProjectPath();
  });
  $("btn-close").addEventListener("click", () => {
    void closeProject();
  });
  $("tc").addEventListener("click", () => {
    void jumpToTimecode();
  });
  $("btn-new").addEventListener("click", () => {
    void newProjectPath();
  });
  wireTimelineMarquee($("timeline-body"));
  $("btn-fs").addEventListener("click", () => {
    toggleProgramFullscreen();
  });
  const chkOw = document.getElementById("chk-overwrite") as HTMLInputElement | null;
  chkOw?.addEventListener("change", () => {
    state.editMode = chkOw.checked ? "overwrite" : "insert";
    $("status-msg").textContent = `Place mode: ${state.editMode}`;
  });
  const chkProxy = document.getElementById(
    "chk-auto-proxy",
  ) as HTMLInputElement | null;
  chkProxy?.addEventListener("change", () => {
    $("status-msg").textContent = chkProxy.checked
      ? "Auto-proxy on"
      : "Auto-proxy off";
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
  $("btn-export-edl").addEventListener("click", () => {
    void exportEdl();
  });
  $("btn-export-cutlist").addEventListener("click", () => {
    void exportCutlist("csv");
  });
  $("btn-import-edl").addEventListener("click", () => {
    stopPlay();
    void importEdlFile();
  });
  $("btn-import-cutlist").addEventListener("click", () => {
    stopPlay();
    void importCutlistFile();
  });
  $("btn-transcribe").addEventListener("click", () => {
    stopPlay();
    void transcribeSelection();
  });
  $("btn-media-status").addEventListener("click", () => {
    void refreshMediaStatus();
  });
  $("btn-duck").addEventListener("click", () => {
    stopPlay();
    void duckSelection();
  });
  $("btn-duck-clear").addEventListener("click", () => {
    stopPlay();
    void clearDuckSelection();
  });
  $("btn-proxies-all").addEventListener("click", () => {
    void ensureAllMediaProxies(false);
  });
  $("btn-proxy-one").addEventListener("click", () => {
    void ensureBinMediaProxy(false);
  });
  $("btn-style-assets").addEventListener("click", () => {
    void showStyleAssets();
  });
  $("btn-trim-io").addEventListener("click", () => {
    stopPlay();
    void trimSelectionToIO();
  });
  $("btn-keyframes").addEventListener("click", () => {
    void reviewKeyframesUi(5);
  });
  $("btn-workflow").addEventListener("click", () => {
    void showWorkflow();
  });
  $("btn-brief").addEventListener("click", () => {
    void makeBriefUi();
  });
  $("btn-rot-m90").addEventListener("click", () => {
    stopPlay();
    void rotateSelection(-90);
  });
  $("btn-rot-p90").addEventListener("click", () => {
    stopPlay();
    void rotateSelection(90);
  });
  $("btn-rot-180").addEventListener("click", () => {
    stopPlay();
    void rotateSelection(180);
  });
  $("btn-reset-xf").addEventListener("click", () => {
    stopPlay();
    void resetTransformSelection();
  });
  $("btn-crop-sq").addEventListener("click", () => {
    stopPlay();
    void cropSelection(1080, 1080);
  });
  $("btn-crop-916").addEventListener("click", () => {
    stopPlay();
    void cropSelection(608, 1080);
  });
  $("btn-crop-43").addEventListener("click", () => {
    stopPlay();
    void cropSelection(1440, 1080);
  });
  $("btn-pip-tr").addEventListener("click", () => {
    stopPlay();
    void positionSelection(0.62, 0.05, 0.35);
  });
  $("btn-pip-bl").addEventListener("click", () => {
    stopPlay();
    void positionSelection(0.05, 0.6, 0.35);
  });
  $("btn-pip-full").addEventListener("click", () => {
    stopPlay();
    void clearPositionSelection();
  });
  $("btn-relink").addEventListener("click", () => {
    stopPlay();
    void relinkSelectionToBin();
  });
  $("btn-filler-plan").addEventListener("click", () => {
    stopPlay();
    void fillerCutsSelection(false);
  });
  $("btn-filler-go").addEventListener("click", () => {
    stopPlay();
    if (
      !window.confirm(
        "Apply filler cuts to selection? This razor-keeps speech ranges (undoable).",
      )
    ) {
      return;
    }
    void fillerCutsSelection(true);
  });
  $("btn-export-work").addEventListener("click", () => {
    void exportWorkArea();
  });
  $("btn-proxy").addEventListener("click", (ev) => {
    const force = (ev as MouseEvent).shiftKey;
    void ensureProxy(force);
  });
  $("btn-proxy-refresh").addEventListener("click", (ev) => {
    const full = (ev as MouseEvent).shiftKey;
    void refreshPreviewProxy(!full);
  });
  $("btn-project-state").addEventListener("click", () => {
    void showProjectState();
  });
  $("btn-os-plan").addEventListener("click", () => {
    void showOpenshotPlan();
  });
  $("btn-os-frame").addEventListener("click", () => {
    void grabOpenshotFrame();
  });
  $("btn-gen-go").addEventListener("click", () => {
    void submitGeneration();
  });
  $("btn-gen-poll").addEventListener("click", () => {
    void pollGeneration(false);
  });
  $("btn-gen-place").addEventListener("click", () => {
    stopPlay();
    void placeGeneratedAtPlayhead();
  });
  $("btn-gen-qc").addEventListener("click", () => {
    void qualityCheckLastGen();
  });
  $("btn-gen-license").addEventListener("click", () => {
    void showLicenseReport();
  });
  $("btn-preflight").addEventListener("click", () => {
    void runAgentPreflight();
  });
  $("btn-agent-finish").addEventListener("click", () => {
    void runAgentFinish();
  });
  // Pro buttons added in later 0.4.6x slices (guard missing ids)
  const proBind = (id: string, fn: () => void) => {
    const el = document.getElementById(id);
    if (el) el.addEventListener("click", fn);
  };
  proBind("btn-analyze-tl", () => void runAnalyzeTimeline());
  proBind("btn-analyze-aud", () => void runAnalyzeBinAudio());
  proBind("btn-silence", () => void runSilenceCutsPlan());
  proBind("btn-scenes", () => void runDetectScenes());
  proBind("btn-fcpxml", () => void exportFcpxmlUi());
  proBind("btn-import-fcpxml", () => void importFcpxmlFile());
  proBind("btn-exp-mkr-seg", () => void exportMarkerSegmentsUi());
  proBind("btn-track-stems", () => void exportTrackStemsUi());
  proBind("btn-bal-gain", () => void balanceGainsUi());
  proBind("btn-match-grade", () => void matchGradeUi());
  proBind("btn-seq-media", () => void sequenceFromMediaUi());
  proBind("btn-asm-unused", () => void assembleUnusedUi());
  proBind("btn-rough-cut", () => void roughCutUi());
  proBind("btn-edge-fades", () => void edgeFadesUi());
  proBind("btn-vo-duck", () => void voMusicDuckUi());
  proBind("btn-title-card", () => void titleCardUi());
  proBind("btn-freeze-mkr", () => void freezeAtMarkersUi());
  proBind("btn-stills-mkr", () => void stillsAtMarkersUi());
  proBind("btn-otio", () => void exportOtioUi());
  proBind("btn-import-otio", () => void importOtioFile());
  proBind("btn-manifest", () => void exportManifestUi());
  proBind("btn-imp-manifest", () => void importManifestUi());
  proBind("btn-proxies-all2", () => void ensureAllProxiesUi());
  proBind("btn-relink-off", () => void relinkOfflineUi());
  proBind("btn-handoff", () => void exportHandoffUi());
  proBind("btn-collect", () => void collectBundleUi());
  proBind("btn-imgseq", () => void importImageSequenceUi());
  proBind("btn-imp-folder", () => void importFolderUi());
  proBind("btn-frameseq", () => void exportFrameSequenceUi());
  proBind("btn-detach-all", () => void detachAudioAllUi());
  proBind("btn-jl-cut", () => void jlOffsetUi(-15));
  proBind("btn-ll-cut", () => void jlOffsetUi(15));
  proBind("btn-interchange", () => void interchangeCatalogUi());
  proBind("btn-still", () => void exportStillUi());
  proBind("btn-gif", () => void exportGifUi());
  proBind("btn-wa-gif", () => void exportWorkAreaGifUi());
  proBind("btn-solid", () => void solidUi());
  proBind("btn-kb", () => void kenBurnsUi());
  proBind("btn-kb-img", () => void kenBurnsImagesUi());
  proBind("btn-vig", () => void vignetteUi());
  proBind("btn-grain", () => void filmGrainUi());
  proBind("btn-blur", () => void blurUi());
  proBind("btn-sharp", () => void sharpenUi());
  proBind("btn-glow", () => void glowUi());
  proBind("btn-ckey", () => void chromaKeyUi());
  proBind("btn-lkey", () => void lumaKeyUi());
  proBind("btn-wb", () => void whiteBalanceUi());
  proBind("btn-mask", () => void shapeMaskUi());
  proBind("btn-curves", () => void curvesUi());
  proBind("btn-clip-gif", () => void exportClipGifUi());
  proBind("btn-clip-webm", () => void exportClipWebmUi());
  proBind("btn-comp", () => void compressionUi());
  proBind("btn-eq", () => void audioEqUi());
  proBind("btn-clip-aud", () => void exportClipAudioUi());
  proBind("btn-nr", () => void noiseReductionUi());
  proBind("btn-clip-mp4", () => void exportClipMp4Ui());
  proBind("btn-countdown", () => void countdownUi());
  proBind("btn-spd05", () => void speedRippleUi(0.5));
  proBind("btn-spd2", () => void speedRippleUi(2.0));
  proBind("btn-clip-still", () => void exportClipStillUi());
  proBind("btn-freeze-mid", () => void freezeClipMidUi());
  proBind("btn-clips-pack", () => void exportClipsPackUi());
  proBind("btn-slate", () => void slateUi());
  proBind("btn-close-all", () => void closeGapsAllUi());
  proBind("btn-trk-only", () => void exportTrackOnlyUi());
  proBind("btn-sel-mp4", () => void exportSelectionMp4Ui());
  proBind("btn-wa-mp4", () => void exportWorkAreaMp4Ui());
  proBind("btn-lift-clip", () => void liftClipUi());
  proBind("btn-rip-sel", () => void rippleDeleteSelectionUi());
  proBind("btn-copy-fx", () => void copyEffectsUi());
  proBind("btn-stills-pack", () => void exportClipsStillsPackUi());
  proBind("btn-join", () => void joinClipsUi());
  proBind("btn-paste-pos", () => void pastePositionUi());
  proBind("btn-flip-h", () => void flipHSelectionUi());
  proBind("btn-paste-crop", () => void pasteCropUi());
  proBind("btn-paste-from", () => void pasteFromClipUi());
  proBind("btn-dup-sel", () => void duplicateSelectionUi());
  proBind("btn-sel-aud", () => void exportSelectionAudioUi());
  proBind("btn-split-sel", () => void splitSelectionUi());
  proBind("btn-mkr-sel", () => void markersFromSelectionUi());
  proBind("btn-span-sel", () => void selectionSpanUi());
  proBind("btn-sel-gif", () => void exportSelectionGifUi());
  proBind("btn-sel-webm", () => void exportSelectionWebmUi());
  proBind("btn-trim-q", () => void trimSelectionPlayheadUi("head"));
  proBind("btn-trim-w", () => void trimSelectionPlayheadUi("tail"));
  proBind("btn-wa-sel", () => void workAreaFromSelectionExportUi());
  proBind("btn-ext-next", () => void extendToNextUi());
  proBind("btn-rev-sel", () => void reverseSelectionUi());
  proBind("btn-spd2-sel", () => void selectionSpeedRippleUi(2.0));
  proBind("btn-xfade-sel", () => void transitionsSelectionUi());
  proBind("btn-hard-sel", () => void removeTransitionsSelectionUi());
  proBind("btn-stagger", () => void staggerSelectionUi());
  proBind("btn-split-even", () => void splitSelectionEvenlyUi());
  proBind("btn-mkr-mid", () => void markersSelectionMidsUi());
  proBind("btn-fade-sel", () => void edgeFadesSelectionUi());
  proBind("btn-detach-sel", () => void detachAudioSelectionUi());
  proBind("btn-match-sel", () => void matchSelectionDurationUi());
  proBind("btn-jcut-sel", () => void selectionJlCutUi("j"));
  proBind("btn-lcut-sel", () => void selectionJlCutUi("l"));
  proBind("btn-exp-link", () => void expandSelectionLinksUi());
  proBind("btn-gap-sel", () => void closeGapsSelectionTracksUi());
  proBind("btn-frz-sel", () => void freezeSelectionMidsUi());
  proBind("btn-iso-sel", () => void isolateSelectionUi());
  proBind("btn-gain-sel", () => void selectionGainUi(-3));
  proBind("btn-opac-sel", () => void selectionOpacityUi(0.7));
  proBind("btn-new-trk", () => void selectionToNewTrackUi());
  proBind("btn-dup-trk", () => void duplicateSelectionToNewTrackUi());
  proBind("btn-bake-sel", () => void bakeSelectionUi());
  proBind("btn-cutlist-sel", () => void exportSelectionCutlistUi());
  proBind("btn-edl-sel", () => void exportSelectionEdlUi());
  proBind("btn-rename-sel", () => void renameSelectionUi());
  proBind("btn-color-sel", () => void colorSelectionUi());
  proBind("btn-diag-sel", () => void selectionDiagnosticsUi());
  proBind("btn-pathc-sel", () => void selectionPathCUi());
  proBind("btn-look-sel", () => void lookSelectionUi());
  proBind("btn-style-sel", () => void styleSelectionUi());
  proBind("btn-slip-sel-m", () => void slipSelectionBatchUi(-5));
  proBind("btn-slip-sel-p", () => void slipSelectionBatchUi(5));
  proBind("btn-slide-sel-m", () => void slideSelectionBatchUi(-5));
  proBind("btn-snap-sel", () => void snapSelectionPlayheadUi());
  proBind("btn-lift-sel", () => void liftSelectionUi());
  proBind("btn-pack-sel", () => void packSelectionUi());
  proBind("btn-mute-sel", () => void muteSelectionUi(true));
  proBind("btn-unmute-sel", () => void muteSelectionUi(false));
  proBind("btn-extract-sel", () => void extractSelectionUi());
  proBind("btn-join-sel", () => void joinSelectionUi());
  proBind("btn-pip-sel", () => void pipSelectionUi());
  proBind("btn-clear-pip-sel", () => void clearPipSelectionUi());
  proBind("btn-rev-ord-sel", () => void reverseSelectionOrderUi());
  proBind("btn-link-sel", () => void linkSelectionUi());
  proBind("btn-unlink-sel", () => void unlinkSelectionUi());
  proBind("btn-stretch-sel", () => void rateStretchSelectionUi(30));
  proBind("btn-trim-h-sel", () => void trimSelectionEdgesUi(5, 0));
  proBind("btn-trim-t-sel", () => void trimSelectionEdgesUi(0, 5));
  proBind("btn-gaps-sel", () => void selectionGapsUi());
  proBind("btn-ext-next-sel", () => void extendSelectionNextUi());
  proBind("btn-speed1-sel", () => void selectionSpeedUi(1.0));
  proBind("btn-speed2-sel", () => void selectionSpeedUi(2.0));
  proBind("btn-pathc-plan-sel", () => void selectionPathCPlanUi());
  proBind("btn-match-sel", () => void matchFrameSelectionUi());
  proBind("btn-rtrim-h-sel", () => void rippleTrimSelectionEdgesUi(3, 0));
  proBind("btn-rtrim-t-sel", () => void rippleTrimSelectionEdgesUi(0, 3));
  proBind("btn-export-pathc-sel", () => void exportSelectionPathCPlanUi());
  proBind("btn-fill-gaps-sel", () => void fillSelectionGapsUi());
  proBind("btn-swap-sel", () => void swapSelectionPairUi());
  proBind("btn-dup-block-sel", () => void duplicateSelectionBlockUi());
  proBind("btn-align-ends-sel", () => void alignSelectionEndsUi());
  proBind("btn-media-sel", () => void selectionMediaReportUi());
  proBind("btn-rename-media-sel", () => void renameSelectionFromMediaUi());
  proBind("btn-nudge-sel-m", () => void nudgeSelectionUi(-5));
  proBind("btn-nudge-sel-p", () => void nudgeSelectionUi(5));
  proBind("btn-move-ph-sel", () => void moveSelectionToPlayheadUi());
  proBind("btn-ins-time-sel", () => void insertTimeBeforeSelectionUi());
  proBind("btn-rm-time-sel", () => void removeTimeBeforeSelectionUi());
  proBind("btn-rnudge-sel-m", () => void rippleNudgeSelectionUi(-5));
  proBind("btn-rnudge-sel-p", () => void rippleNudgeSelectionUi(5));
  proBind("btn-razor-sel-at", () => void razorSelectionAtUi());
  proBind("btn-flip-h-sel", () => void flipSelectionHUi());
  proBind("btn-rot90-sel", () => void rotateSelectionUi(90));
  proBind("btn-cuts-sel", () => void selectionCutReportUi());
  proBind("btn-crop-sel", () => void cropSelectionCenterUi());
  proBind("btn-vig-sel", () => void vignetteSelectionUi());
  proBind("btn-fx-sel", () => void selectionEffectsReportUi());
  proBind("btn-blur-sel", () => void blurSelectionUi());
  proBind("btn-sharp-sel", () => void sharpenSelectionUi());
  proBind("btn-grain-sel", () => void filmGrainSelectionUi());
  proBind("btn-glow-sel", () => void glowSelectionUi());
  proBind("btn-curves-sel", () => void curvesSelectionUi());
  proBind("btn-chroma-sel", () => void chromaKeySelectionUi());
  proBind("btn-wb-sel", () => void whiteBalanceSelectionUi());
  proBind("btn-clr-fx-sel", () => void clearSelectionEffectsUi());
  proBind("btn-strip-pathc-sel", () => void stripSelectionPathCUnmappedUi());
  proBind("btn-comp-sel", () => void compressionSelectionUi());
  proBind("btn-nr-sel", () => void noiseReductionSelectionUi());
  proBind("btn-eq-sel", () => void audioEqSelectionUi());
  proBind("btn-razor-mkr-sel", () => void razorSelectionAtMarkersUi());
  proBind("btn-freeze-ph-sel", () => void freezeSelectionAtPlayheadUi());
  proBind("btn-aud-sel", () => void exportSelectionAudioDefaultUi());
  proBind("btn-proxy-sel", () => void selectionProxyReportUi());
  proBind("btn-mk-proxy-sel", () => void ensureSelectionMediaProxiesUi());
  proBind("btn-mp4-sel", () => void exportSelectionMp4DefaultUi());
  proBind("btn-webm-sel", () => void exportSelectionWebmDefaultUi());
  proBind("btn-gif-sel", () => void exportSelectionGifDefaultUi());
  proBind("btn-wa-from-sel", () => void workAreaFromSelectionUi());
  proBind("btn-copy-sel", () => void copySelectionUi());
  proBind("btn-paste-sel", () => void pasteSelectionAtPlayheadUi());
  proBind("btn-clip-status", () => void selectionClipboardStatusUi());
  proBind("btn-mkr-in-sel", () => void markersInSelectionSpanUi());
  proBind("btn-clr-mkr-sel", () => void clearMarkersInSelectionSpanUi());
  proBind("btn-otio-sel", () => void exportSelectionOtioUi());
  proBind("btn-edl-def-sel", () => void exportSelectionEdlDefaultUi());
  proBind("btn-cutlist-def-sel", () => void exportSelectionCutlistDefaultUi());
  proBind("btn-fcpxml-sel", () => void exportSelectionFcpxmlUi());
  proBind("btn-preflight-sel", () => void selectionExportPreflightUi());
  proBind("btn-offline-sel", () => void selectionOfflineMediaUi());
  proBind("btn-locked-sel", () => void selectionLockedTracksUi());
  proBind("btn-unlock-trk-sel", () => void unlockSelectionTracksUi());
  proBind("btn-lock-trk-sel", () => void lockSelectionTracksUi());
  proBind("btn-mute-trk-sel", () => void muteSelectionTracksUi(true));
  proBind("btn-unmute-trk-sel", () => void muteSelectionTracksUi(false));
  proBind("btn-solo-trk-sel", () => void soloSelectionTracksUi());
  proBind("btn-unsolo-trk-sel", () => void unsoloSelectionTracksUi());
  proBind("btn-trk-state-sel", () => void selectionTrackStatesUi());
  proBind("btn-raise-trk-sel", () => void raiseSelectionTracksUi());
  proBind("btn-lower-trk-sel", () => void lowerSelectionTracksUi());
  proBind("btn-rename-trk-sel", () => void renameSelectionTracksUi());
  proBind("btn-webm", () => void exportWebmUi());
  proBind("btn-wa-webm", () => void exportWorkAreaWebmUi());
  proBind("btn-audio-out", () => void exportAudioUi());
  proBind("btn-del-trk", () => void deleteTrackOfSelection());
  proBind("btn-hard-cut", () => void hardCutAllUi());
  proBind("btn-beats", () => void splitAtBeatsUi());
  proBind("btn-beat-mkr", () => void markersFromBeatsUi());
  proBind("btn-beat-grid", () => void beatGridUi());
  proBind("btn-scene-grid", () => void sceneGridUi());
  proBind("btn-x-near-mkr", () => void transitionsNearMarkersUi());
  proBind("btn-place-mkr", () => void placeAtMarkersUi());
  proBind("btn-fit-mkr", () => void fitToMarkersUi());
  proBind("btn-music-broll", () => void musicBrollUi());
  proBind("btn-mkr-slots", () => void markerSlotsUi());
  proBind("btn-srt-mkr", () => void importSrtMarkersUi());
  proBind("btn-snaps", () => void showSnapPoints());
  proBind("btn-px-inval", () => void invalidatePreviewUi());
  proBind("btn-recent-clr", () => void clearRecentUi());
  proBind("btn-srt", () => void writeSrtFromMarkersUi());
  proBind("btn-looks", () => void showLooksUi());
  proBind("btn-enc", () => void showEncodeStatusUi());
  proBind("btn-det-beats", () => void detectBeatsUi());
  proBind("btn-mix-plan", () => void suggestMixUi());
  proBind("btn-color-match", () => void colorMatchUi());
  proBind("btn-sil-plan", () => void applySilenceUi(true));
  proBind("btn-sil-go", () => void applySilenceUi(false));
  proBind("btn-share-media", () => void clipsSharingMediaUi());
  proBind("btn-place-after", () => void placeAfterUi());
  proBind("btn-suggest-fmt", () => void suggestFpsResUi());
  proBind("btn-deliv-lim", () => void deliveryLimitsUi());
  proBind("btn-transcript", () => void loadTranscriptUi());
  proBind("btn-caption", () => void captionClipUi());
  proBind("btn-exp-range", () => void exportRangeIoUi());
  proBind("btn-px-range", () => void previewRangeIoUi());
  proBind("btn-off-link-m", () => void offsetLinkedUi(-6));
  proBind("btn-off-link-p", () => void offsetLinkedUi(6));
  proBind("btn-asset-card", () => void analyzeAssetUi());
  proBind("btn-clip-gain-op", () => {
    const ids = selectionList();
    if (ids.length === 1) void enrichClipGainOpacity(ids[0]);
  });
  proBind("btn-trim-src", () => void trimClipToIoUi());
  proBind("btn-slug", () => void slugMediaUi(false));
  proBind("btn-slug-place", () => void slugMediaUi(true));
  proBind("btn-xfade-1", () => void clipTransitionUi(false));
  proBind("btn-xfade-clr-1", () => void clipTransitionUi(true));
  proBind("btn-rip-range", () => void rippleDeleteRangeIoUi());
  proBind("btn-mk-color", () => void markersColorBatchUi());
  proBind("btn-media-sheet", () => void mediaContactSheetUi());
  proBind("btn-asset-load", () => void loadCachedAssetAnalysisUi());
  proBind("btn-rt-suggest", () => void roomToneSuggestUi());
  proBind("btn-rt-extract", () => void roomToneExtractUi());
  proBind("btn-rt-place", () => void roomTonePlaceUi());
  proBind("btn-stems", () => void separateStemsUi());
  proBind("btn-frame-bin", () => void extractFrameBinUi());
  proBind("btn-prep-exp2", () => void prepareForExportUi());
  proBind("btn-filler-sug", () => void suggestFillerUi());
  proBind("btn-sess-sum", () => void sessionSummaryUi());
  proBind("btn-pathc-report", () => void pathCReportUi());
  proBind("btn-copy-bundle", () => void copyBundlePath());
  proBind("btn-pro-toggle", () => {
    const body = document.getElementById("pro-body");
    const btn = document.getElementById("btn-pro-toggle");
    if (!body) return;
    body.classList.toggle("collapsed");
    if (btn) btn.textContent = body.classList.contains("collapsed") ? "▸" : "▾";
  });
  proBind("btn-doctor-full", () => void showDoctorFull());
  proBind("btn-sel-share", () => void selectSharingMedia());
  proBind("btn-lane-compact", () => toggleLaneCompact());
  document.querySelectorAll<HTMLButtonElement>("[data-fx]").forEach((b) => {
    b.addEventListener("click", () => {
      const kind = b.dataset.fx || "";
      if (kind) {
        stopPlay();
        void applyFxPreset(kind);
      }
    });
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
  $("btn-detach-a").addEventListener("click", () => {
    stopPlay();
    void detachAudioSelection();
  });
  $("btn-auto-link").addEventListener("click", () => {
    stopPlay();
    void autoLinkAV();
  });
  $("btn-fit-fill").addEventListener("click", () => {
    stopPlay();
    void fitToFillSelection();
  });
  $("btn-swap").addEventListener("click", () => {
    stopPlay();
    void swapSelection();
  });
  const btnFlipH = document.getElementById("btn-fliph");
  if (btnFlipH) {
    btnFlipH.addEventListener("click", () => {
      stopPlay();
      void flipSelection("h");
    });
  }
  const btnFlipV = document.getElementById("btn-flipv");
  if (btnFlipV) {
    btnFlipV.addEventListener("click", () => {
      stopPlay();
      void flipSelection("v");
    });
  }
  const btnExpClips = document.getElementById("btn-exp-clips");
  if (btnExpClips) {
    btnExpClips.addEventListener("click", () => {
      stopPlay();
      void exportClipMediaUi();
    });
  }
  const btnBake = document.getElementById("btn-bake");
  if (btnBake) {
    btnBake.addEventListener("click", () => {
      stopPlay();
      void bakeSelectionUi();
    });
  }
  const btnHealth = document.getElementById("btn-health");
  if (btnHealth) {
    btnHealth.addEventListener("click", () => {
      void projectHealthUi();
    });
  }
  const btnInsertEd = document.getElementById("btn-insert-ed");
  if (btnInsertEd) {
    btnInsertEd.addEventListener("click", () => {
      stopPlay();
      void insertEditAtPlayhead();
    });
  }
  const btnOverEd = document.getElementById("btn-over-ed");
  if (btnOverEd) {
    btnOverEd.addEventListener("click", () => {
      stopPlay();
      void overwriteEditAtPlayhead();
    });
  }
  const btnGradeL = document.getElementById("btn-grade-layer");
  if (btnGradeL) {
    btnGradeL.addEventListener("click", () => {
      stopPlay();
      void gradeLayerUi();
    });
  }
  const btn3pt = document.getElementById("btn-3pt");
  if (btn3pt) {
    btn3pt.addEventListener("click", () => {
      stopPlay();
      void threePointEditUi();
    });
  }
  const btnUsage = document.getElementById("btn-usage");
  if (btnUsage) {
    btnUsage.addEventListener("click", () => {
      void mediaUsageUi();
    });
  }
  const btnFxTrk = document.getElementById("btn-fx-track");
  if (btnFxTrk) {
    btnFxTrk.addEventListener("click", () => {
      stopPlay();
      void applyEffectsTrackUi();
    });
  }
  const btnClrFx = document.getElementById("btn-clr-fx");
  if (btnClrFx) {
    btnClrFx.addEventListener("click", () => {
      stopPlay();
      void clearEffectsUi();
    });
  }
  const btnStory = document.getElementById("btn-storyboard");
  if (btnStory) {
    btnStory.addEventListener("click", () => {
      stopPlay();
      void exportStoryboardUi();
    });
  }
  const btnSocial = document.getElementById("btn-social");
  if (btnSocial) {
    btnSocial.addEventListener("click", () => {
      stopPlay();
      void exportSocialPackUi();
    });
  }
  const btnReframe = document.getElementById("btn-reframe");
  if (btnReframe) {
    btnReframe.addEventListener("click", () => {
      stopPlay();
      void reframeSelectionUi("9:16");
    });
  }
  const btnTc = document.getElementById("btn-tc");
  if (btnTc) {
    btnTc.addEventListener("click", () => {
      stopPlay();
      void timecodeSelectionUi();
    });
  }
  const btnMkrClips = document.getElementById("btn-mkr-clips");
  if (btnMkrClips) {
    btnMkrClips.addEventListener("click", () => {
      stopPlay();
      void markersFromClipsUi();
    });
  }
  const btnWm = document.getElementById("btn-wm");
  if (btnWm) {
    btnWm.addEventListener("click", () => {
      stopPlay();
      void watermarkSelectionUi();
    });
  }
  const btnCuts = document.getElementById("btn-cuts");
  if (btnCuts) {
    btnCuts.addEventListener("click", () => {
      void listCutsUi();
    });
  }
  const btnWmTrk = document.getElementById("btn-wm-trk");
  if (btnWmTrk) {
    btnWmTrk.addEventListener("click", () => {
      stopPlay();
      void watermarkTrackUi();
    });
  }
  const btnReviewPkg = document.getElementById("btn-review-pkg");
  if (btnReviewPkg) {
    btnReviewPkg.addEventListener("click", () => {
      stopPlay();
      void exportReviewPackageUi();
    });
  }
  const btnSafe = document.getElementById("btn-safe");
  if (btnSafe) {
    btnSafe.addEventListener("click", () => {
      stopPlay();
      void safeAreaSelectionUi();
    });
  }
  const btnSafeT = document.getElementById("btn-safe-trk");
  if (btnSafeT) {
    btnSafeT.addEventListener("click", () => {
      stopPlay();
      void safeAreaTrackUi();
    });
  }
  const btnCutsExp = document.getElementById("btn-cuts-exp");
  if (btnCutsExp) {
    btnCutsExp.addEventListener("click", () => {
      stopPlay();
      void exportCutsReportUi();
    });
  }
  const btnBurnin = document.getElementById("btn-burnin");
  if (btnBurnin) {
    btnBurnin.addEventListener("click", () => {
      stopPlay();
      void exportBurninsUi();
    });
  }
  const btnRenameSeq = document.getElementById("btn-rename-seq");
  if (btnRenameSeq) {
    btnRenameSeq.addEventListener("click", () => {
      stopPlay();
      void renameClipsSeqUi();
    });
  }
  const btnIsolate = document.getElementById("btn-isolate");
  if (btnIsolate) {
    btnIsolate.addEventListener("click", () => {
      stopPlay();
      void isolateSelectionUi();
    });
  }
  const btnXfade = document.getElementById("btn-xfade");
  if (btnXfade) {
    btnXfade.addEventListener("click", () => {
      stopPlay();
      void crossfadesTrackUi();
    });
  }
  const btnMkrCuts = document.getElementById("btn-mkr-cuts");
  if (btnMkrCuts) {
    btnMkrCuts.addEventListener("click", () => {
      stopPlay();
      void markersFromHardCutsUi();
    });
  }
  const btnBlack = document.getElementById("btn-black");
  if (btnBlack) {
    btnBlack.addEventListener("click", () => {
      stopPlay();
      void blackdetectUi();
    });
  }
  const btnResVert = document.getElementById("btn-res-vert");
  if (btnResVert) {
    btnResVert.addEventListener("click", () => {
      stopPlay();
      void setResolutionUi(1080, 1920);
    });
  }
  const btnSilence = document.getElementById("btn-silence");
  if (btnSilence) {
    btnSilence.addEventListener("click", () => {
      stopPlay();
      void silencedetectUi();
    });
  }
  const btnSplitSil = document.getElementById("btn-split-sil");
  if (btnSplitSil) {
    btnSplitSil.addEventListener("click", () => {
      stopPlay();
      void splitAtSilencesUi();
    });
  }
  const btnTighten = document.getElementById("btn-tighten");
  if (btnTighten) {
    btnTighten.addEventListener("click", () => {
      stopPlay();
      void tightenSilencesUi();
    });
  }
  const btnGainTrk = document.getElementById("btn-gain-trk");
  if (btnGainTrk) {
    btnGainTrk.addEventListener("click", () => {
      stopPlay();
      void gainTrackUi(-3);
    });
  }
  const btnNrTrk = document.getElementById("btn-nr-trk");
  if (btnNrTrk) {
    btnNrTrk.addEventListener("click", () => {
      stopPlay();
      void noiseReductionTrackUi();
    });
  }
  const btnSilMap = document.getElementById("btn-sil-map");
  if (btnSilMap) {
    btnSilMap.addEventListener("click", () => {
      void silenceMapUi();
    });
  }
  const btnSnapshot = document.getElementById("btn-snapshot");
  if (btnSnapshot) {
    btnSnapshot.addEventListener("click", () => {
      stopPlay();
      void projectSnapshotUi();
    });
  }
  const btnPresetsPack = document.getElementById("btn-presets-pack");
  if (btnPresetsPack) {
    btnPresetsPack.addEventListener("click", () => {
      stopPlay();
      void exportPresetsPackUi();
    });
  }
  const btnMatchDur = document.getElementById("btn-match-dur");
  if (btnMatchDur) {
    btnMatchDur.addEventListener("click", () => {
      stopPlay();
      void matchDurationUi();
    });
  }
  const btnPip = document.getElementById("btn-pip");
  if (btnPip) {
    btnPip.addEventListener("click", () => {
      stopPlay();
      void placePipUi();
    });
  }
  const btnL3 = document.getElementById("btn-l3");
  if (btnL3) {
    btnL3.addEventListener("click", () => {
      stopPlay();
      void lowerThirdUi();
    });
  }
  const btnEndCard = document.getElementById("btn-endcard");
  if (btnEndCard) {
    btnEndCard.addEventListener("click", () => {
      stopPlay();
      void endCardUi();
    });
  }
  const btnSplit = document.getElementById("btn-split");
  if (btnSplit) {
    btnSplit.addEventListener("click", () => {
      stopPlay();
      void splitScreenUi();
    });
  }
  const btnIntro = document.getElementById("btn-intro");
  if (btnIntro) {
    btnIntro.addEventListener("click", () => {
      stopPlay();
      void introCardUi();
    });
  }
  const btnQuad = document.getElementById("btn-quad");
  if (btnQuad) {
    btnQuad.addEventListener("click", () => {
      stopPlay();
      void quadScreenUi();
    });
  }
  $("btn-snap-prev").addEventListener("click", () => {
    void snapSelection("prev_end");
  });
  $("btn-snap-next").addEventListener("click", () => {
    void snapSelection("next_start");
  });
  $("btn-quantize").addEventListener("click", () => {
    void quantizeSelection(10);
  });
  const btnSnapM = document.getElementById("btn-snap-mkr");
  if (btnSnapM) {
    btnSnapM.addEventListener("click", () => {
      void snapSelectionToMarkers();
    });
  }
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
  $("btn-template").addEventListener("click", () => {
    stopPlay();
    void applyCutTemplate();
  });
  $("btn-finish").addEventListener("click", () => {
    void finishDelivery();
  });
  $("btn-search-asr").addEventListener("click", () => {
    void searchTranscriptsUi();
  });
  $("btn-replace-edit").addEventListener("click", () => {
    stopPlay();
    void replaceEditSelection();
  });
  $("btn-copy-track").addEventListener("click", () => {
    stopPlay();
    void copySelectionToNewTrack();
  });
  $("btn-mk-import").addEventListener("click", () => {
    void importMarkersText();
  });
  $("btn-mix").addEventListener("click", () => {
    void refreshMixConsole();
  });
  $("btn-find-gaps").addEventListener("click", () => {
    void findGapsUi();
  });
  $("btn-close-all-gaps").addEventListener("click", () => {
    void closeAllGapsUi();
  });
  $("btn-sel-io").addEventListener("click", () => {
    void selectClipsInIO();
  });
  $("btn-sel-color").addEventListener("click", () => {
    void selectByColorOfSelection();
  });
  $("btn-sel-link").addEventListener("click", () => {
    void selectLinkedGroup();
  });
  $("btn-rename-pat").addEventListener("click", () => {
    void renameSelectionPattern();
  });
  $("btn-block-ph").addEventListener("click", () => {
    void moveBlockToPlayhead();
  });
  $("btn-trk-up").addEventListener("click", () => {
    void moveTrackOfSelection(-1);
  });
  $("btn-trk-dn").addEventListener("click", () => {
    void moveTrackOfSelection(1);
  });
  $("btn-mk-shift-m").addEventListener("click", () => {
    void shiftMarkersUi(-15);
  });
  $("btn-mk-shift-p").addEventListener("click", () => {
    void shiftMarkersUi(15);
  });
  $("btn-xfade-all").addEventListener("click", () => {
    void xfadeAllOnTrack(12);
  });
  $("btn-xfade-clr").addEventListener("click", () => {
    void clearTransitionsOnTrack();
  });
  $("btn-rm-empty").addEventListener("click", () => {
    void removeEmptyTracksUi();
  });
  $("btn-trk-name").addEventListener("click", () => {
    void renameTrackOfSelection();
  });
  $("btn-append-bin").addEventListener("click", () => {
    void appendBinMedia();
  });
  $("btn-plan-edit").addEventListener("click", () => {
    stopPlay();
    void planEditFromBin(true);
  });
  $("btn-look").addEventListener("click", () => {
    void applyProjectLook();
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
  $("btn-insert-15").addEventListener("click", () => {
    stopPlay();
    void insertTimeAtPlayhead(15);
  });
  $("btn-insert-1s").addEventListener("click", () => {
    stopPlay();
    void insertTimeAtPlayhead(Math.max(1, Math.round(state.fps || 30)));
  });
  $("btn-ripple-m").addEventListener("click", () => {
    stopPlay();
    void rippleNudgeSelection(-1);
  });
  $("btn-ripple-p").addEventListener("click", () => {
    stopPlay();
    void rippleNudgeSelection(1);
  });
  $("btn-lift").addEventListener("click", () => {
    stopPlay();
    void liftWorkArea(false);
  });
  $("btn-extract").addEventListener("click", () => {
    stopPlay();
    void liftWorkArea(true);
  });
  $("btn-extract-time").addEventListener("click", () => {
    stopPlay();
    void extractTimeIO();
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
  $("btn-zoom-fit").addEventListener("click", () => {
    zoomFitSequence();
  });
  $("btn-zoom-sel").addEventListener("click", () => {
    zoomToSelection();
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
  $("btn-import").addEventListener("click", () => {
    void startImport();
  });
  $("file-import").addEventListener("change", (ev) => {
    const input = ev.target as HTMLInputElement;
    void importFiles(input.files);
    input.value = "";
  });
  if (isTauri()) {
    void wireTauriFileDrop();
  } else {
    wireBrowserFileDrop();
  }
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
  void loadTemplates();
  void refreshRecent();
  void refresh();
  startHealthHeartbeat();
  sessionStorage.setItem("opmiere_sess_edit", "0");
  sessionStorage.setItem("opmiere_sess_save", "0");
  sessionStorage.setItem("opmiere_sess_gen", "0");
  const ss = document.getElementById("session-stats");
  if (ss) ss.textContent = "e0/s0/g0";
  const proOut = document.getElementById("pro-out");
  if (proOut) {
    proOut.addEventListener("dblclick", () => {
      void copyProOut();
    });
  }
  const genOut = document.getElementById("gen-out");
  if (genOut) {
    genOut.addEventListener("dblclick", () => {
      const t = genOut.textContent || "";
      if (t) void navigator.clipboard.writeText(t).then(
        () => {
          $("status-msg").textContent = "Gen output copied";
        },
        () => undefined,
      );
    });
    genOut.title = "Double-click to copy";
  }
});
