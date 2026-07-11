"""UI shell complete (0.3.0): selection card, toast, Ctrl+S, link badge, docs."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "src" / "opmiere" / "web" / "static" / "index.html"
CSS = ROOT / "scripts" / "_shell_style.css"

EXTRA_CSS = r"""
/* —— shell complete 0.3.0 —— */
#selCard {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-background);
  padding: 8px 10px;
  margin-bottom: 8px;
  font-size: 11px;
}
#selCard.empty { color: var(--color-muted); }
#selCard .sc-name {
  font-weight: 600; font-size: 12px; color: var(--color-foreground);
  margin-bottom: 4px; word-break: break-all;
}
#selCard .sc-row {
  display: flex; flex-wrap: wrap; gap: 4px 10px;
  color: var(--color-muted); font-family: var(--font-mono); font-size: 10px;
}
#selCard .sc-row b { color: var(--color-primary); font-weight: 500; }
#selCard .sc-actions { display: flex; gap: 4px; margin-top: 6px; flex-wrap: wrap; }
#selCard .sc-actions button {
  width: auto; margin: 0; padding: 3px 8px; font-size: 10px;
}
#toastHost {
  position: fixed; right: 14px; bottom: 48px; z-index: 80;
  display: flex; flex-direction: column; gap: 6px; pointer-events: none;
}
.toast {
  min-width: 180px; max-width: 320px;
  padding: 8px 12px; border-radius: var(--radius-md);
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border);
  color: var(--color-foreground);
  font-size: 11px;
  box-shadow: 0 8px 24px rgba(0,0,0,0.45);
  opacity: 0; transform: translateY(8px);
  transition: opacity 160ms var(--ease), transform 160ms var(--ease);
  pointer-events: none;
}
.toast.show { opacity: 1; transform: translateY(0); }
.toast.ok { border-color: rgba(61, 214, 140, 0.45); }
.toast.err { border-color: rgba(240, 113, 120, 0.55); color: #ffc9cc; }
.toast.warn { border-color: rgba(230, 162, 60, 0.5); }
.tclip .linkBadge {
  position: absolute; top: 2px; right: 4px; z-index: 2;
  font-size: 8px; font-weight: 700; letter-spacing: 0.04em;
  color: var(--color-accent);
  text-shadow: 0 1px 2px rgba(0,0,0,0.6);
  pointer-events: none;
}
#dirtyPill.bad {
  background: rgba(240, 113, 120, 0.15);
  border-color: var(--color-destructive);
}
#statusBar .shell-ver { color: var(--color-primary); }
#panel-inspector > .panel-head h2::after {
  content: "";
}
"""

COMPLETE_JS = r"""
    // —— UI shell complete 0.3.0 ——
    (function shellComplete() {
      // Toast
      let host = document.getElementById('toastHost');
      if (!host) {
        host = document.createElement('div');
        host.id = 'toastHost';
        document.body.appendChild(host);
      }
      window.toast = function(msg, kind) {
        const el = document.createElement('div');
        el.className = 'toast' + (kind ? ' ' + kind : '');
        el.textContent = msg;
        host.appendChild(el);
        requestAnimationFrame(() => el.classList.add('show'));
        setTimeout(() => {
          el.classList.remove('show');
          setTimeout(() => el.remove(), 200);
        }, 2800);
      };

      // Selection card
      const inspBody = document.querySelector('#panel-inspector .panel-body');
      let card = document.getElementById('selCard');
      if (inspBody && !card) {
        card = document.createElement('div');
        card.id = 'selCard';
        card.className = 'empty';
        card.textContent = 'No clip selected';
        inspBody.insertBefore(card, inspBody.firstChild);
      }

      async function refreshSelCard() {
        const el = document.getElementById('selCard');
        if (!el) return;
        if (!selectedClipId) {
          el.className = 'empty';
          el.textContent = selectedIds.size > 1
            ? (selectedIds.size + ' clips selected')
            : 'No clip selected';
          return;
        }
        const dom = document.querySelector('.tclip[data-id="' + selectedClipId + '"]');
        const name = (dom && (dom.dataset.name || dom.dataset.label)) || selectedClipId;
        const start = dom ? +dom.dataset.start : 0;
        const sp = dom ? (+dom.dataset.speed || 1) : 1;
        const fps = (timeline && timeline.fps) || 30;
        const end = start + (dom ? Math.round(((+dom.style.width) || 0)) : 0);
        // prefer dataset duration via out-in if available
        let durF = 0;
        if (dom && dom.dataset.in != null && dom.dataset.out != null) {
          durF = Math.max(0, Math.round((+dom.dataset.out - +dom.dataset.in) / sp));
        }
        const endF = start + (durF || 0);
        const muted = dom && dom.dataset.muted === '1';
        const link = dom && dom.dataset.link;
        let html = '<div class="sc-name">' + escapeHtml(name) + '</div>';
        html += '<div class="sc-row">';
        html += '<span>id <b>' + selectedClipId.slice(0, 12) + '</b></span>';
        html += '<span>@ <b>' + start + 'f</b></span>';
        if (durF) html += '<span>dur <b>' + durF + 'f</b> (' + (durF / fps).toFixed(2) + 's)</span>';
        html += '<span>speed <b>' + sp.toFixed(2) + '×</b></span>';
        if (muted) html += '<span><b>MUTED</b></span>';
        if (link) html += '<span>link <b>' + link.slice(0, 8) + '</b></span>';
        if (selectedIds.size > 1) html += '<span>sel <b>' + selectedIds.size + '</b></span>';
        html += '</div>';
        html += '<div class="sc-actions">';
        html += '<button type="button" class="secondary" data-sc="info">Info</button>';
        html += '<button type="button" class="secondary" data-sc="mute">Mute</button>';
        html += '<button type="button" class="danger" data-sc="ripple">Ripple del</button>';
        html += '</div>';
        el.className = '';
        el.innerHTML = html;
        el.querySelectorAll('button[data-sc]').forEach((b) => {
          b.onclick = () => {
            const a = b.dataset.sc;
            if (a === 'info') document.getElementById('btnClipInfo')?.click();
            if (a === 'mute') document.getElementById('btnClipMute')?.click();
            if (a === 'ripple') document.getElementById('btnRippleDel')?.click();
          };
        });
        // enrich via describe API when possible
        try {
          const d = await api('/api/clip/' + encodeURIComponent(selectedClipId) + '/describe');
          if (d && d.clip && document.getElementById('selCard') && selectedClipId === d.clip.id) {
            const c = d.clip;
            const nm = c.name || (d.media && d.media.path) || c.id;
            let h = '<div class="sc-name">' + escapeHtml(String(nm).split(/[/\\\\]/).pop()) + '</div>';
            h += '<div class="sc-row">';
            h += '<span>tc <b>' + (c.start_tc || '') + '–' + (c.end_tc || '') + '</b></span>';
            h += '<span>dur <b>' + (c.duration_seconds != null ? c.duration_seconds + 's' : '') + '</b></span>';
            h += '<span>speed <b>' + (c.speed || 1) + '×</b></span>';
            if (d.track) h += '<span>trk <b>' + (d.track.name || d.track.kind) + '</b></span>';
            if (c.link_group) h += '<span>link <b>on</b></span>';
            if (c.muted) h += '<span><b>MUTED</b></span>';
            if (selectedIds.size > 1) h += '<span>sel <b>' + selectedIds.size + '</b></span>';
            h += '</div><div class="sc-actions">';
            h += '<button type="button" class="secondary" data-sc="info">Info</button>';
            h += '<button type="button" class="secondary" data-sc="mute">Mute</button>';
            h += '<button type="button" class="danger" data-sc="ripple">Ripple del</button></div>';
            el.innerHTML = h;
            el.querySelectorAll('button[data-sc]').forEach((btn) => {
              btn.onclick = () => {
                const a = btn.dataset.sc;
                if (a === 'info') document.getElementById('btnClipInfo')?.click();
                if (a === 'mute') document.getElementById('btnClipMute')?.click();
                if (a === 'ripple') document.getElementById('btnRippleDel')?.click();
              };
            });
          }
        } catch (_) {}
      }

      function escapeHtml(s) {
        return String(s).replace(/[&<>"']/g, (ch) => ({
          '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
        })[ch]);
      }

      const _apply = applySelectionStyles;
      applySelectionStyles = function() {
        _apply();
        refreshSelCard();
      };

      const _setDirty = setDirty;
      setDirty = function(on) {
        _setDirty(on);
        const p = document.getElementById('dirtyPill');
        if (p) p.title = on ? 'Unsaved changes — Ctrl+S to save' : 'All changes saved';
      };

      // Ctrl+S save
      window.addEventListener('keydown', async (ev) => {
        if ((ev.ctrlKey || ev.metaKey) && (ev.key === 's' || ev.key === 'S')) {
          const tag = (ev.target && ev.target.tagName) || '';
          // allow in inputs still to save project
          ev.preventDefault();
          const btn = document.getElementById('btnSave');
          if (btn) {
            btn.click();
            toast('Saved', 'ok');
          }
        }
      }, true);

      // Toast on export / finish
      const wrapClick = (id, okMsg) => {
        const b = document.getElementById(id);
        if (!b || b.dataset.toastBound) return;
        b.dataset.toastBound = '1';
        b.addEventListener('click', () => {
          // delayed success heuristic: observe log is noisy; fire after microtask if no throw
          setTimeout(() => {
            /* handlers are async; toast from dirty clear instead for save */
          }, 0);
        });
      };
      const saveBtn = document.getElementById('btnSave');
      if (saveBtn && !saveBtn.dataset.toastBound) {
        saveBtn.dataset.toastBound = '1';
        const prev = saveBtn.onclick;
        saveBtn.addEventListener('click', () => {
          setTimeout(() => {
            const p = document.getElementById('dirtyPill');
            if (p && p.textContent === 'saved') toast('Project saved', 'ok');
          }, 300);
        });
      }

      // Link badge on clips: patch renderTimeline HTML once
      if (typeof renderTimeline === 'function' && !renderTimeline._linkPatched) {
        // data-link on clips if timeline provides it — inject via string patch below in Python
        renderTimeline._linkPatched = true;
        const _rt = renderTimeline;
        renderTimeline = function(tv) {
          _rt(tv);
          document.querySelectorAll('.tclip[data-link]').forEach((el) => {
            if (el.dataset.link && !el.querySelector('.linkBadge')) {
              const b = document.createElement('span');
              b.className = 'linkBadge';
              b.textContent = 'L';
              b.title = 'Linked group ' + el.dataset.link;
              el.appendChild(b);
            }
          });
          refreshSelCard();
        };
      }

      // Status bar version
      const sb = document.getElementById('statusBar');
      if (sb) {
        const ver = sb.querySelector('.shell-ver') || document.createElement('span');
        ver.className = 'shell-ver';
        ver.textContent = 'shell 0.3.0 complete';
        if (!ver.parentElement) sb.insertBefore(ver, sb.firstChild);
        const hint = document.getElementById('shellHint');
        if (hint) hint.textContent = 'Ctrl+S save · right-click clip · marquee · FS preview';
      }

      // initial card
      refreshSelCard();
    })();
"""


def main() -> None:
    t = INDEX.read_text(encoding="utf-8")

    if "shell complete 0.3.0" not in t:
        t = t.replace("</style>", EXTRA_CSS + "\n</style>", 1)

    # Add link_group to clip template if missing
    if "data-link=" not in t:
        t = t.replace(
            'data-speed="${c.speed||1}"',
            'data-speed="${c.speed||1}" data-link="${c.link_group||\'\'}"',
            1,
        )
        print("added data-link")

    if "UI shell complete 0.3.0" not in t:
        if "  </script>" in t:
            t = t.replace("  </script>", COMPLETE_JS + "  </script>", 1)
        else:
            t = t.replace("</script>", COMPLETE_JS + "</script>", 1)

    css = CSS.read_text(encoding="utf-8") if CSS.exists() else ""
    if "shell complete 0.3.0" not in css:
        CSS.write_text(css.rstrip() + "\n" + EXTRA_CSS, encoding="utf-8")

    INDEX.write_text(t, encoding="utf-8")
    print("complete js", "UI shell complete 0.3.0" in t)
    print("selCard css", "#selCard" in t)
    print("data-link", "data-link=" in t)
    print("DOCTYPE", t.count("<!DOCTYPE"), "body", t.count("</body>"))


if __name__ == "__main__":
    main()
