"""UI shell v5: clip context menu, track height, empty CTA."""
from __future__ import annotations

from pathlib import Path

INDEX = Path(__file__).resolve().parents[1] / "src" / "opmiere" / "web" / "static" / "index.html"
CSS = Path(__file__).resolve().parents[1] / "scripts" / "_shell_style.css"

EXTRA_CSS = r"""
/* —— shell v5 —— */
.track-lane.video-lane { height: 44px; }
.track-lane.audio-lane { height: 32px; }
.track-row.video-row { min-height: 40px; }
.track-row.audio-row { min-height: 30px; }
.tclip .clipLab {
  font-size: 10px; pointer-events: none;
  text-shadow: 0 1px 2px rgba(0,0,0,0.55);
}
.tclip[data-narrow="1"] .clipLab { display: none; }
#ctxMenu {
  position: fixed; z-index: 60; min-width: 160px;
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  box-shadow: 0 12px 28px rgba(0,0,0,0.55);
  padding: 4px 0; display: none;
  font-size: 11px;
}
#ctxMenu.open { display: block; }
#ctxMenu button {
  display: block; width: 100%; margin: 0; border: none; border-radius: 0;
  background: transparent; color: var(--color-foreground);
  text-align: left; padding: 6px 12px; font-weight: 500;
}
#ctxMenu button:hover { background: rgba(124, 156, 255, 0.18); }
#ctxMenu button.danger { color: var(--color-destructive); }
#ctxMenu .sep {
  height: 1px; margin: 4px 0; background: var(--color-border);
}
#tracks .empty-cta {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 8px; min-height: 120px; color: var(--color-muted); font-size: 12px;
}
#tracks .empty-cta strong { color: var(--color-foreground); font-weight: 600; }
"""

CTX_HTML = """
<div id="ctxMenu" role="menu">
  <button type="button" data-act="mute">Mute / Unmute</button>
  <button type="button" data-act="detach">Detach audio</button>
  <button type="button" data-act="split">Split at playhead (S)</button>
  <button type="button" data-act="copy">Copy (Ctrl+C)</button>
  <button type="button" data-act="copyAttr">Copy attributes</button>
  <div class="sep"></div>
  <button type="button" data-act="info">Clip info</button>
  <button type="button" data-act="match">Match frame</button>
  <div class="sep"></div>
  <button type="button" class="danger" data-act="ripple">Ripple delete</button>
</div>
"""

V5_JS = r"""
    // —— UI shell v5: context menu + empty CTA + narrow labels ——
    (function shellV5() {
      const menu = document.getElementById('ctxMenu');
      if (!menu) return;
      let ctxId = null;

      function hideMenu() {
        menu.classList.remove('open');
        ctxId = null;
      }
      document.addEventListener('pointerdown', (e) => {
        if (!menu.classList.contains('open')) return;
        if (menu.contains(e.target)) return;
        hideMenu();
      });
      document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') hideMenu();
      });
      window.addEventListener('blur', hideMenu);
      window.addEventListener('scroll', hideMenu, true);

      function showMenu(x, y, clipId) {
        ctxId = clipId;
        selectedClipId = clipId;
        if (!selectedIds.has(clipId)) selectedIds = new Set([clipId]);
        applySelectionStyles();
        menu.classList.add('open');
        const pad = 6;
        const mw = menu.offsetWidth || 160;
        const mh = menu.offsetHeight || 200;
        let left = x, top = y;
        if (left + mw > window.innerWidth - pad) left = window.innerWidth - mw - pad;
        if (top + mh > window.innerHeight - pad) top = window.innerHeight - mh - pad;
        menu.style.left = Math.max(pad, left) + 'px';
        menu.style.top = Math.max(pad, top) + 'px';
      }

      menu.querySelectorAll('button[data-act]').forEach((btn) => {
        btn.addEventListener('click', async () => {
          const act = btn.dataset.act;
          hideMenu();
          if (!ctxId && !selectedClipId) return;
          const id = ctxId || selectedClipId;
          selectedClipId = id;
          try {
            if (act === 'mute') {
              const b = document.getElementById('btnClipMute');
              if (b && !b.disabled) b.click();
            } else if (act === 'detach') {
              const b = document.getElementById('btnDetach');
              if (b && !b.disabled) b.click();
            } else if (act === 'split') {
              // S key handler path
              if (typeof splitSelected === 'function') splitSelected();
              else {
                const ev = new KeyboardEvent('keydown', { key: 's', bubbles: true });
                document.dispatchEvent(ev);
              }
            } else if (act === 'copy') {
              await api('/api/clip/copy', { method: 'POST', body: JSON.stringify({ clip_id: id }) });
              log('copied ' + id);
            } else if (act === 'copyAttr') {
              const b = document.getElementById('btnCopyAttr');
              if (b && !b.disabled) b.click();
            } else if (act === 'info') {
              const b = document.getElementById('btnClipInfo');
              if (b && !b.disabled) b.click();
            } else if (act === 'match') {
              const b = document.getElementById('btnMatch');
              if (b && !b.disabled) b.click();
            } else if (act === 'ripple') {
              const b = document.getElementById('btnRippleDel');
              if (b && !b.disabled) b.click();
            }
          } catch (e) { log(String(e.message || e)); }
        });
      });

      // Patch wireClipInteractions to add contextmenu + dblclick
      const _wire = wireClipInteractions;
      wireClipInteractions = function(tracksEl, viewDurF, fps) {
        _wire(tracksEl, viewDurF, fps);
        tracksEl.querySelectorAll('.tclip').forEach((el) => {
          // hide label when too narrow
          const w = el.getBoundingClientRect().width;
          if (w < 48) el.dataset.narrow = '1';
          else delete el.dataset.narrow;

          el.addEventListener('contextmenu', (e) => {
            e.preventDefault();
            e.stopPropagation();
            showMenu(e.clientX, e.clientY, el.dataset.id);
          });
          el.addEventListener('dblclick', (e) => {
            e.preventDefault();
            selectedClipId = el.dataset.id;
            selectedIds = new Set([el.dataset.id]);
            applySelectionStyles();
            // open inspector + first clip tools group
            const app = document.getElementById('app');
            if (app && app.classList.contains('hide-inspector')) {
              const bi = document.getElementById('btnToggleInspector');
              if (bi) bi.click();
            }
            const groups = document.querySelectorAll('#panel-inspector details.tool-group');
            if (groups[0]) groups[0].open = true;
            log('inspect ' + el.dataset.id);
          });
        });
      };

      // Better empty timeline message
      const _rt = renderTimeline;
      renderTimeline = function(tv) {
        _rt(tv);
        const tracksEl = document.getElementById('tracks');
        if (tracksEl && tracksEl.querySelector('p') && !(tv.tracks && tv.tracks.some(t => (t.clips||[]).length))) {
          tracksEl.innerHTML = '<div class="empty-cta"><strong>Timeline empty</strong>'
            + '<span>Drop media in the left panel, or Place file</span></div>';
        }
        // mark video/audio lanes for height CSS
        if (tv && tv.tracks) {
          document.querySelectorAll('.track-row').forEach((row, i) => {
            const tr = tv.tracks[i];
            if (!tr) return;
            row.classList.add(tr.kind === 'audio' ? 'audio-row' : 'video-row');
            const lane = row.querySelector('.track-lane');
            if (lane) lane.classList.add(tr.kind === 'audio' ? 'audio-lane' : 'video-lane');
          });
        }
      };
    })();
"""


def main() -> None:
    t = INDEX.read_text(encoding="utf-8")

    if "shell v5" not in t:
        t = t.replace("</style>", EXTRA_CSS + "\n</style>", 1)

    if 'id="ctxMenu"' not in t:
        t = t.replace("</body>", CTX_HTML + "\n</body>", 1)

    if "UI shell v5" not in t:
        if "  </script>" in t:
            t = t.replace("  </script>", V5_JS + "  </script>", 1)
        else:
            t = t.replace("</script>", V5_JS + "</script>", 1)

    # Also add data-kind on track rows in renderTimeline via patch of template string
    old = 'class="track-row"'
    # may already use template - check renderTimeline generation
    if "track-row ${" not in t and "video-row" not in t[t.find("function renderTimeline") : t.find("function renderTimeline") + 2500]:
        # inject class in track row HTML if pattern found
        t2 = t.replace(
            'class="track-row"',
            'class="track-row ${tr.kind===\'audio\'?\'audio-row\':\'video-row\'}"',
            1,
        )
        # only if that string exists in JS template
        if 'class="track-row"' in t:
            # find tracks HTML build
            import re
            t = re.sub(
                r'(html \+= `<div class=")track-row(")',
                r"\1track-row ${tr.kind==='audio'?'audio-row':'video-row'}\2",
                t,
                count=1,
            )
            t = re.sub(
                r'(class="track-lane")',
                r'class="track-lane ${tr.kind===\'audio\'?\'audio-lane\':\'video-lane\'}"',
                t,
                count=1,
            )

    css = CSS.read_text(encoding="utf-8") if CSS.exists() else ""
    if "shell v5" not in css:
        CSS.write_text(css.rstrip() + "\n" + EXTRA_CSS, encoding="utf-8")

    INDEX.write_text(t, encoding="utf-8")
    print("ctxMenu", 'id="ctxMenu"' in t)
    print("v5js", "UI shell v5" in t)
    print("v5css", "shell v5" in t)
    print("track class inject", "audio-row" in t)


if __name__ == "__main__":
    main()
