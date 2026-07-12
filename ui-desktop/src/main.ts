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
    muted?: boolean;
    solo?: boolean;
    locked?: boolean;
    clips?: Array<{
      id: string;
      start?: number;
      start_frame?: number;
      duration_frames?: number;
      name?: string;
      label?: string;
      muted?: boolean;
    }>;
  }>;
};

type Marker = {
  id: string;
  frame?: number;
  label?: string;
  color?: string;
  time_seconds?: number;
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

async function exportProject() {
  if (!state.projectOpen) {
    $("status-msg").textContent = "Open a project first";
    return;
  }
  stopPlay();
  $("status-msg").textContent = "Exporting (finish_delivery)…";
  ($("btn-export") as HTMLButtonElement).disabled = true;
  try {
    const r = await postJson<{
      ok?: boolean;
      path?: string;
      delivery?: { ok?: boolean; delivery_ok?: boolean };
    }>("/api/desktop/export", {});
    if (!r.ok) {
      $("status-msg").textContent = `Export soft-fail: ${r.path || "see delivery"}`;
    } else {
      $("status-msg").textContent = `Exported: ${r.path}`;
    }
  } catch (e) {
    $("status-msg").textContent = `Export failed: ${e}`;
  } finally {
    ($("btn-export") as HTMLButtonElement).disabled = false;
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
      const newStart = Math.max(0, d.startFrame + dFrames);
      d.pendingStart = newStart;
      d.pendingDelta = dFrames;
      block.style.left = `${(newStart / durF) * 100}%`;
      const over = trackIdAtClientY(ev.clientY);
      if (over) d.pendingTrackId = over;
      block.classList.toggle("cross-track", d.pendingTrackId !== d.trackId);
    } else if (d.mode === "trim-left") {
      // positive delta = head later (shorter) when dragging right
      d.pendingDelta = dFrames;
      const visualStart = Math.max(0, d.startFrame + dFrames);
      const visualDur = Math.max(1, d.durationFrames - dFrames);
      block.style.left = `${(visualStart / durF) * 100}%`;
      block.style.width = `${(visualDur / durF) * 100}%`;
    } else {
      // trim-right: drag right → longer (positive delta)
      d.pendingDelta = dFrames;
      const visualDur = Math.max(1, d.durationFrames + dFrames);
      block.style.width = `${(visualDur / durF) * 100}%`;
    }
  };

  const onUp = async (ev: PointerEvent) => {
    const d = state.drag;
    if (!d || d.clipId !== c.id) return;
    block.classList.remove("dragging", "cross-track");
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
    block.classList.remove("dragging", "cross-track");
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
  if (state.selected.has(c.id)) block.classList.add("selected");
  block.appendChild(leftH);
  block.appendChild(label);
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
    return;
  }
  const durF = Math.max(1, view.duration_frames || 1);
  state.durationFrames = durF;
  state.durationSec = view.duration_seconds || durF / (view.fps || state.fps);
  state.fps = view.fps || state.fps || 30;
  if (view.proxy) state.proxyFresh = !!view.proxy.fresh;
  state.trackOrder = view.tracks.map((t) => t.id);
  state.tracks = view.tracks.map((t) => ({ id: t.id, kind: t.kind }));
  meta.textContent = `${view.tracks.length} tracks · ${state.durationSec.toFixed(2)}s · M mark · Shift+M mute · S razor`;
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
      block.title = `${c.id}${c.muted ? " [muted]" : ""} · drag · edges · Shift+M mute`;
      bindClipInteractions(
        block,
        { id: c.id, start, dur, trackId: tr.id },
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
  setPlayheadUi();
  $("sel-count").textContent = String(state.selected.size);
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

async function openProjectPath() {
  stopPlay();
  const path = promptPath(
    "Open project bundle path (.opm folder or path):",
    "",
  );
  if (!path) return;
  $("status-msg").textContent = `Opening ${path}…`;
  try {
    await postJson("/api/project/open", { bundle_path: path });
    $("status-msg").textContent = `Opened: ${path}`;
    state.t = 0;
    await refresh();
    void seekTo(0);
  } catch (e) {
    $("status-msg").textContent = `Open failed: ${e}`;
  }
}

async function newProjectPath() {
  stopPlay();
  const path = promptPath(
    "New project path (will create .opm bundle):",
    "G:\\tmp\\opmiere_new.opm",
  );
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
    } else {
      state.durationSec = 0;
      state.durationFrames = 0;
      state.markers = [];
      renderTimeline(null);
      hideAllProgramSurfaces();
      setPlayheadUi();
      renderMediaBin(null);
      renderMarkerList();
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
    return;
  }
  if ((ev.ctrlKey || ev.metaKey) && k === "z") {
    ev.preventDefault();
    stopPlay();
    void undoEdit();
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
  $("btn-save").addEventListener("click", () => {
    void saveProject();
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
  void refresh();
});
