"""UI shell v2: clean markup + panel collapse + timeline resize + chrome polish."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "src" / "opmiere" / "web" / "static" / "index.html"
CSS = ROOT / "scripts" / "_shell_style.css"

SHELL_JS = r"""
    // —— UI shell v2 chrome (layout persistence) ——
    (function shellChrome() {
      const KEY = 'opmiere.shell.v2';
      const defaults = { media: true, inspector: true, timelineFrac: 0.38 };
      function load() {
        try { return { ...defaults, ...JSON.parse(localStorage.getItem(KEY) || '{}') }; }
        catch { return { ...defaults }; }
      }
      function save(s) {
        try { localStorage.setItem(KEY, JSON.stringify(s)); } catch (_) {}
      }
      let state = load();
      const app = document.getElementById('app');
      if (!app) return;

      function apply() {
        app.classList.toggle('hide-media', !state.media);
        app.classList.toggle('hide-inspector', !state.inspector);
        const tf = Math.min(0.7, Math.max(0.22, state.timelineFrac));
        const pf = 1 - tf;
        app.style.setProperty('--preview-row', pf.toFixed(3) + 'fr');
        app.style.setProperty('--timeline-row', tf.toFixed(3) + 'fr');
        const bm = document.getElementById('btnToggleMedia');
        const bi = document.getElementById('btnToggleInspector');
        if (bm) {
          bm.setAttribute('aria-pressed', state.media ? 'true' : 'false');
          bm.textContent = state.media ? 'Media' : 'Media+';
        }
        if (bi) {
          bi.setAttribute('aria-pressed', state.inspector ? 'true' : 'false');
          bi.textContent = state.inspector ? 'Insp' : 'Insp+';
        }
      }
      apply();

      const bm = document.getElementById('btnToggleMedia');
      const bi = document.getElementById('btnToggleInspector');
      if (bm) bm.onclick = () => { state.media = !state.media; save(state); apply(); };
      if (bi) bi.onclick = () => { state.inspector = !state.inspector; save(state); apply(); };

      // Timeline row resize via drag handle
      const handle = document.getElementById('splitHandle');
      if (handle) {
        let dragging = false;
        handle.addEventListener('pointerdown', (e) => {
          dragging = true;
          handle.setPointerCapture(e.pointerId);
          handle.classList.add('active');
          e.preventDefault();
        });
        handle.addEventListener('pointermove', (e) => {
          if (!dragging) return;
          const rect = app.getBoundingClientRect();
          const y = e.clientY - rect.top;
          const frac = 1 - (y / rect.height);
          state.timelineFrac = Math.min(0.7, Math.max(0.22, frac));
          apply();
        });
        const end = (e) => {
          if (!dragging) return;
          dragging = false;
          handle.classList.remove('active');
          try { handle.releasePointerCapture(e.pointerId); } catch (_) {}
          save(state);
        };
        handle.addEventListener('pointerup', end);
        handle.addEventListener('pointercancel', end);
      }

      // Transport label sync: Play/Pause
      const btnPlay = document.getElementById('btnPlay');
      const player = document.getElementById('player');
      if (btnPlay && player) {
        const syncPlayLabel = () => {
          btnPlay.textContent = player.paused ? 'Play' : 'Pause';
        };
        player.addEventListener('play', syncPlayLabel);
        player.addEventListener('pause', syncPlayLabel);
        const orig = btnPlay.onclick;
        // keep existing handler; just refresh label after click
        btnPlay.addEventListener('click', () => setTimeout(syncPlayLabel, 0));
      }
    })();
"""

EXTRA_CSS = r"""
/* —— shell v2 —— */
#app {
  grid-template-rows: minmax(120px, var(--preview-row, 1fr)) 6px minmax(160px, var(--timeline-row, 1.1fr));
  grid-template-areas:
    "media preview inspector"
    "media split inspector"
    "media timeline inspector";
}
#splitHandle {
  grid-area: split;
  cursor: row-resize;
  background: var(--color-border);
  position: relative;
  z-index: 6;
  transition: background var(--duration-fast) var(--ease);
}
#splitHandle:hover, #splitHandle.active {
  background: var(--color-primary);
}
#splitHandle::after {
  content: "";
  position: absolute;
  left: 50%;
  top: 50%;
  width: 36px;
  height: 2px;
  transform: translate(-50%, -50%);
  background: rgba(255,255,255,0.25);
  border-radius: 1px;
}
#app.hide-media {
  grid-template-columns: 0px minmax(0, 1fr) 300px;
}
#app.hide-media #panel-media {
  display: none;
}
#app.hide-inspector {
  grid-template-columns: 260px minmax(0, 1fr) 0px;
}
#app.hide-media.hide-inspector {
  grid-template-columns: 0px minmax(0, 1fr) 0px;
}
#app.hide-inspector #panel-inspector {
  display: none;
}
.panel-head .tools { display: flex; gap: 4px; align-items: center; }
.panel-head button.icon-btn {
  width: 26px; height: 22px; padding: 0;
  display: inline-flex; align-items: center; justify-content: center;
  font-size: 11px; line-height: 1;
  border-radius: var(--radius-sm);
}
.panel-head button.icon-btn[aria-pressed="false"] {
  opacity: 0.7;
  border-color: var(--color-warning);
  color: var(--color-warning);
}
#topbar .top-actions button.icon-btn {
  width: auto; min-width: 28px; height: 26px; padding: 0 8px;
}
.transport #btnPlay {
  background: var(--color-primary);
  color: var(--color-on-primary);
  border: none;
  font-weight: 700;
  min-width: 64px;
}
.transport #btnJ, .transport #btnK, .transport #btnL {
  min-width: 32px;
  font-family: var(--font-mono);
  font-weight: 600;
}
#statusBar {
  display: flex; gap: 8px; align-items: center; flex-wrap: wrap;
  padding: 4px 10px;
  border-top: 1px solid var(--color-border);
  background: var(--color-surface);
  font-size: 10px; color: var(--color-muted);
  flex-shrink: 0;
}
#statusBar .mono { font-family: var(--font-mono); color: var(--color-primary); }
@media (max-width: 1100px) {
  #app.hide-inspector { grid-template-columns: 220px minmax(0,1fr); }
  #app.hide-media { grid-template-columns: minmax(0,1fr) 0; }
}
"""


def main() -> None:
    raw = INDEX.read_text(encoding="utf-8")

    # Extract script once
    m = re.search(r"<script>([\s\S]*)</script>\s*</body>", raw)
    if not m:
        raise SystemExit("script not found")
    script_body = m.group(1)
    # strip trailing auto-doctor click noise is fine to keep

    # Parse only HTML portion before first script
    html_part = raw[: raw.find("<script>")]
    # Fix multiple doctype
    html_part = re.sub(r"(<!DOCTYPE html>\s*)+", "<!DOCTYPE html>\n", html_part, count=1)
    soup_html = html_part
    # remove extra trailing body/html if present in html_part
    soup_html = re.sub(r"</body>\s*</html>\s*$", "", soup_html, flags=re.I)

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(soup_html, "html.parser")

    # Merge CSS
    style = soup.find("style")
    css = (CSS.read_text(encoding="utf-8") if CSS.exists() else "") + "\n" + EXTRA_CSS
    # de-dupe extra if re-run
    if "shell v2" not in (style.string or ""):
        style.clear()
        style.append(css)
        CSS.write_text(css, encoding="utf-8")
    else:
        style.clear()
        style.append(css)

    app = soup.find(id="app")
    if not app:
        raise SystemExit("no #app")

    # Insert split handle after preview panel if missing
    if not soup.find(id="splitHandle"):
        handle = soup.new_tag("div", id="splitHandle", **{"role": "separator", "aria-orientation": "horizontal", "title": "Drag to resize timeline"})
        # place before timeline
        tl = soup.find(id="panel-timeline")
        if tl:
            tl.insert_before(handle)

    # Panel head toggles
    def ensure_toggle(panel_id: str, btn_id: str, title: str, label: str):
        panel = soup.find(id=panel_id)
        if not panel:
            return
        head = panel.find(class_="panel-head")
        if not head:
            return
        if soup.find(id=btn_id):
            return
        tools = head.find(class_="tools")
        if not tools:
            tools = soup.new_tag("div", **{"class": "tools"})
            head.append(tools)
        # For media/inspector panels, toggle is on topbar or opposite; put collapse on head
        btn = soup.new_tag(
            "button",
            type="button",
            id=btn_id,
            **{"class": "secondary icon-btn", "title": title, "aria-pressed": "true"},
        )
        btn.string = label
        tools.append(btn)

    # Toggles live on topbar for global reach + panel heads
    topbar = soup.find(id="topbar")
    actions = topbar.find(class_="top-actions") if topbar else None
    if actions is None and topbar:
        actions = soup.new_tag("div", **{"class": "top-actions"})
        topbar.append(actions)

    def top_btn(bid, title, label):
        if soup.find(id=bid):
            return
        b = soup.new_tag(
            "button",
            type="button",
            id=bid,
            **{"class": "secondary icon-btn", "title": title, "aria-pressed": "true"},
        )
        b.string = label
        actions.insert(0, b)

    top_btn("btnToggleMedia", "Toggle media panel", "Media")
    top_btn("btnToggleInspector", "Toggle inspector", "Insp")

    # Status bar under app if missing
    if not soup.find(id="statusBar"):
        bar = soup.new_tag("div", id="statusBar")
        s1 = soup.new_tag("span")
        s1.string = "UI shell v2"
        s2 = soup.new_tag("span", **{"class": "mono", "id": "shellHint"})
        s2.string = "drag split · Media/Insp toggles · localStorage"
        bar.append(s1)
        bar.append(s2)
        # after app
        app.insert_after(bar)

    # Inject shell JS before end of script (avoid double inject)
    if "UI shell v2 chrome" not in script_body:
        script_body = script_body.rstrip() + "\n" + SHELL_JS + "\n"

    # Serialize clean document
    # BeautifulSoup may wrap; build carefully
    out_html = str(soup)
    out_html = re.sub(r"(<!DOCTYPE html>\s*)+", "<!DOCTYPE html>\n", out_html, count=1)
    # strip accidental double wrappers
    out_html = re.sub(r"</body>\s*</html>\s*</body>\s*</html>", "</body></html>", out_html, flags=re.I)

    if "</body>" in out_html:
        final = out_html.replace("</body>", f"<script>\n{script_body}\n</script>\n</body>", 1)
    else:
        final = out_html + f"\n<script>\n{script_body}\n</script>\n</body></html>\n"

    # Final cleanup of multiple body/html closings
    final = re.sub(r"(</body>\s*</html>\s*)+$", "</body>\n</html>\n", final, flags=re.I)
    final = re.sub(r"(<!DOCTYPE html>\s*){2,}", "<!DOCTYPE html>\n", final)

    INDEX.write_text(final, encoding="utf-8")
    print("OK", INDEX)
    print("DOCTYPE", final.count("<!DOCTYPE"))
    print("body close", final.count("</body>"))
    print("html close", final.count("</html>"))
    print("shell js", "UI shell v2 chrome" in final)
    print("splitHandle", 'id="splitHandle"' in final)


if __name__ == "__main__":
    main()
