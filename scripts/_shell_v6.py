"""UI shell v6: fix track-lane class, marquee select, track header polish, auto-wave."""
from __future__ import annotations

import re
from pathlib import Path

INDEX = Path(__file__).resolve().parents[1] / "src" / "opmiere" / "web" / "static" / "index.html"
CSS = Path(__file__).resolve().parents[1] / "scripts" / "_shell_style.css"

EXTRA_CSS = r"""
/* —— shell v6 —— */
.track-name {
  width: 88px;
  flex-direction: column;
  align-items: flex-start;
  justify-content: center;
  gap: 2px;
  padding: 4px 6px;
  border-right: 1px solid var(--color-border);
  background: var(--color-surface);
}
.track-name .tn-title {
  font-size: 10px; font-weight: 600; color: var(--color-foreground);
  max-width: 80px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.track-name .tn-meta {
  font-size: 9px; color: var(--color-muted);
}
.track-name .tn-btns { display: flex; gap: 2px; flex-wrap: wrap; }
.track-name button.trkM,
.track-name button.trkS,
.track-name button.trkL {
  width: 22px; min-width: 22px; height: 18px; margin: 0; padding: 0;
  font-size: 9px; font-weight: 700; line-height: 1;
}
.track-name button.on-m {
  background: rgba(240, 113, 120, 0.25);
  border-color: var(--color-destructive);
  color: var(--color-destructive);
}
.track-name button.on-s {
  background: rgba(240, 180, 41, 0.25);
  border-color: var(--color-accent);
  color: var(--color-accent);
}
.track-name button.on-l {
  background: rgba(124, 156, 255, 0.2);
  border-color: var(--color-primary);
  color: var(--color-primary);
}
#marquee {
  position: absolute; z-index: 7; pointer-events: none;
  border: 1px solid var(--color-primary);
  background: rgba(124, 156, 255, 0.12);
  display: none;
}
#marquee.on { display: block; }
.tclip canvas.wave { opacity: 0.75; }
.zoom-row {
  display: flex; align-items: center; gap: 6px; margin-top: 4px;
}
.zoom-row input[type=range] { flex: 1; }
.zoom-row button { width: 28px; min-width: 28px; margin: 0; padding: 2px 0; }
"""

V6_JS = r"""
    // —— UI shell v6: marquee select, track header, auto waveforms ——
    (function shellV6() {
      // Fix paintWaveforms contrast if present
      if (typeof paintWaveforms === 'function') {
        const _pw = paintWaveforms;
        paintWaveforms = function() {
          _pw();
          document.querySelectorAll('.tclip canvas.wave').forEach((canvas) => {
            // slightly stronger stroke already drawn; ensure opacity via CSS
            canvas.style.opacity = '0.8';
          });
        };
      }

      // Auto-load waveforms after timeline render (only missing media, throttled)
      let waveTimer = null;
      let wavesLoading = false;
      if (typeof renderTimeline === 'function') {
        const _rt = renderTimeline;
        renderTimeline = function(tv) {
          _rt(tv);
          document.querySelectorAll('.trkM').forEach((b) => {
            b.classList.toggle('on-m', b.dataset.v === '0');
          });
          document.querySelectorAll('.trkS').forEach((b) => {
            b.classList.toggle('on-s', b.dataset.v === '0');
          });
          document.querySelectorAll('.trkL').forEach((b) => {
            b.classList.toggle('on-l', b.dataset.v === '0');
          });
          // re-attach marquee node (innerHTML wipe)
          ensureMarquee();
          clearTimeout(waveTimer);
          waveTimer = setTimeout(async () => {
            if (wavesLoading || !timeline) return;
            const need = [];
            document.querySelectorAll('.tclip').forEach((el) => {
              const mid = el.dataset.media;
              if (mid && !waveCache[mid] && el.dataset.ha === '1') need.push(mid);
            });
            if (!need.length) return;
            wavesLoading = true;
            try {
              for (const mid of [...new Set(need)].slice(0, 12)) {
                try {
                  const r = await api('/api/waveform', {
                    method: 'POST',
                    body: JSON.stringify({ media_id: mid, buckets: 200 }),
                  });
                  if (r.peaks && r.peaks.length) waveCache[mid] = r.peaks;
                } catch (_) {}
              }
              if (typeof paintWaveforms === 'function') paintWaveforms();
            } finally { wavesLoading = false; }
          }, 500);
        };
      }

      // Marquee selection on tracks container
      let marqueeDrag = null;
      function ensureMarquee() {
        const tracksEl = document.getElementById('tracks');
        if (!tracksEl) return null;
        tracksEl.style.position = 'relative';
        let mq = document.getElementById('marquee');
        if (!mq) {
          mq = document.createElement('div');
          mq.id = 'marquee';
          tracksEl.appendChild(mq);
        } else if (mq.parentElement !== tracksEl) {
          tracksEl.appendChild(mq);
        }
        return mq;
      }
      ensureMarquee();
      const tracksEl = document.getElementById('tracks');
      if (tracksEl) {
        tracksEl.addEventListener('pointerdown', (e) => {
          if (e.button !== 0) return;
          if (e.target.closest('.tclip') || e.target.closest('.track-name') || e.target.closest('button')) return;
          if (!e.target.closest('.track-lane') && e.target.id !== 'tracks' && !e.target.closest('#tracksInner')) return;
          const mq = ensureMarquee();
          if (!mq) return;
          const rect = tracksEl.getBoundingClientRect();
          marqueeDrag = {
            x0: e.clientX - rect.left + tracksEl.scrollLeft,
            y0: e.clientY - rect.top + tracksEl.scrollTop,
          };
          mq.classList.add('on');
          mq.style.left = marqueeDrag.x0 + 'px';
          mq.style.top = marqueeDrag.y0 + 'px';
          mq.style.width = '0px';
          mq.style.height = '0px';
          try { tracksEl.setPointerCapture(e.pointerId); } catch (_) {}
        });
        tracksEl.addEventListener('pointermove', (e) => {
          if (!marqueeDrag) return;
          const mq = document.getElementById('marquee');
          if (!mq) return;
          const rect = tracksEl.getBoundingClientRect();
          const x1 = e.clientX - rect.left + tracksEl.scrollLeft;
          const y1 = e.clientY - rect.top + tracksEl.scrollTop;
          const L = Math.min(marqueeDrag.x0, x1), T = Math.min(marqueeDrag.y0, y1);
          mq.style.left = L + 'px';
          mq.style.top = T + 'px';
          mq.style.width = Math.abs(x1 - marqueeDrag.x0) + 'px';
          mq.style.height = Math.abs(y1 - marqueeDrag.y0) + 'px';
        });
        tracksEl.addEventListener('pointerup', (e) => {
          if (!marqueeDrag) return;
          const mq = document.getElementById('marquee');
          const rect = tracksEl.getBoundingClientRect();
          const x1 = e.clientX - rect.left + tracksEl.scrollLeft;
          const y1 = e.clientY - rect.top + tracksEl.scrollTop;
          const L = Math.min(marqueeDrag.x0, x1), T = Math.min(marqueeDrag.y0, y1);
          const R = Math.max(marqueeDrag.x0, x1), B = Math.max(marqueeDrag.y0, y1);
          if (mq) mq.classList.remove('on');
          marqueeDrag = null;
          if (R - L < 4 && B - T < 4) return;
          const hit = new Set();
          const root = tracksEl.getBoundingClientRect();
          document.querySelectorAll('.tclip').forEach((el) => {
            const r = el.getBoundingClientRect();
            const elL = r.left - root.left + tracksEl.scrollLeft;
            const elT = r.top - root.top + tracksEl.scrollTop;
            const elR = elL + r.width, elB = elT + r.height;
            if (elL < R && elR > L && elT < B && elB > T) hit.add(el.dataset.id);
          });
          if (!hit.size) return;
          if (e.ctrlKey || e.metaKey) hit.forEach((id) => selectedIds.add(id));
          else selectedIds = hit;
          selectedClipId = [...selectedIds][0] || null;
          applySelectionStyles();
          log('marquee n=' + selectedIds.size);
        });
      }

      // Zoom +/- buttons
      const zoom = document.getElementById('zoom');
      const zoomLab = document.getElementById('zoomLab');
      if (zoom && !document.getElementById('btnZoomIn')) {
        const row = zoom.parentElement;
        if (row) {
          row.classList.add('zoom-row');
          const minus = document.createElement('button');
          minus.type = 'button';
          minus.className = 'secondary';
          minus.id = 'btnZoomOut';
          minus.textContent = '−';
          minus.title = 'Zoom out';
          const plus = document.createElement('button');
          plus.type = 'button';
          plus.className = 'secondary';
          plus.id = 'btnZoomIn';
          plus.textContent = '+';
          plus.title = 'Zoom in';
          zoom.insertAdjacentElement('beforebegin', minus);
          zoom.insertAdjacentElement('afterend', plus);
          minus.onclick = () => {
            zoom.value = Math.max(+zoom.min, +zoom.value - (+zoom.step || 0.5));
            zoom.dispatchEvent(new Event('input', { bubbles: true }));
            zoom.dispatchEvent(new Event('change', { bubbles: true }));
          };
          plus.onclick = () => {
            zoom.value = Math.min(+zoom.max, +zoom.value + (+zoom.step || 0.5));
            zoom.dispatchEvent(new Event('input', { bubbles: true }));
            zoom.dispatchEvent(new Event('change', { bubbles: true }));
          };
        }
      }
    })();
"""


def main() -> None:
    t = INDEX.read_text(encoding="utf-8")

    # Fix broken track-lane template escapes
    # Pattern produced earlier: class="track-lane ${tr.kind===\'audio\'?\'audio-lane\':\'video-lane\'}"
    t2 = t
    # various escape forms
    patterns = [
        (
            r'class="track-lane \$\{tr\.kind===\\\'audio\\\'\?\\\'audio-lane\\\'\\:\\\'video-lane\\\'\}"',
            'class="track-lane ${tr.kind===\'audio\'?\'audio-lane\':\'video-lane\'}"',
        ),
        (
            'class="track-lane ${tr.kind===\\\'audio\\\'?\\\'audio-lane\\\':\\\'video-lane\\\'}"',
            'class="track-lane ${tr.kind===\'audio\'?\'audio-lane\':\'video-lane\'}"',
        ),
    ]
    for bad, good in patterns:
        if bad in t2:
            t2 = t2.replace(bad, good)
            print("fixed track-lane escapes")
            break
    else:
        # regex looser
        m = re.search(r'class="track-lane \$\{tr\.kind===.*?\}"', t2)
        if m and "\\\\" in m.group(0) or (m and "\\'" in m.group(0)):
            t2 = t2[: m.start()] + 'class="track-lane ${tr.kind===\'audio\'?\'audio-lane\':\'video-lane\'}"' + t2[m.end() :]
            print("fixed track-lane via regex")
        else:
            print("track-lane ok or not found", bool(m), repr(m.group(0)[:80]) if m else None)

    # Improve track-name HTML template
    old_tn = """          <div class="track-name" data-tid="${tr.id}">
            ${tLab}${flags ? ' ·' + flags : ''}<br/>
            <span style="font-size:9px">${tr.kind} · ${tr.id.slice(0,8)}</span><br/>
            <button type="button" class="secondary trkM" data-tid="${tr.id}" data-v="${tr.muted?0:1}" style="margin:1px;padding:1px 4px;width:auto;font-size:9px">M</button>
            <button type="button" class="secondary trkS" data-tid="${tr.id}" data-v="${tr.solo?0:1}" style="margin:1px;padding:1px 4px;width:auto;font-size:9px">S</button>
            <button type="button" class="secondary trkL" data-tid="${tr.id}" data-v="${tr.locked?0:1}" style="margin:1px;padding:1px 4px;width:auto;font-size:9px">L</button>
          </div>"""
    new_tn = """          <div class="track-name" data-tid="${tr.id}">
            <div class="tn-title" title="${tLab}">${tLab}</div>
            <div class="tn-meta">${tr.kind}${flags ? ' ·' + flags : ''}</div>
            <div class="tn-btns">
            <button type="button" class="secondary trkM" data-tid="${tr.id}" data-v="${tr.muted?0:1}">M</button>
            <button type="button" class="secondary trkS" data-tid="${tr.id}" data-v="${tr.solo?0:1}">S</button>
            <button type="button" class="secondary trkL" data-tid="${tr.id}" data-v="${tr.locked?0:1}">L</button>
            </div>
          </div>"""
    if old_tn in t2:
        t2 = t2.replace(old_tn, new_tn, 1)
        print("track header template updated")
    else:
        print("track header template not exact match — skip structural replace")

    if "shell v6" not in t2:
        t2 = t2.replace("</style>", EXTRA_CSS + "\n</style>", 1)

    if "UI shell v6" not in t2:
        if "  </script>" in t2:
            t2 = t2.replace("  </script>", V6_JS + "  </script>", 1)
        else:
            t2 = t2.replace("</script>", V6_JS + "</script>", 1)

    css = CSS.read_text(encoding="utf-8") if CSS.exists() else ""
    if "shell v6" not in css:
        CSS.write_text(css.rstrip() + "\n" + EXTRA_CSS, encoding="utf-8")

    INDEX.write_text(t2, encoding="utf-8")
    print("v6js", "UI shell v6" in t2)
    print("v6css", "shell v6" in t2)
    print("marquee css", "#marquee" in t2)
    print("DOCTYPE", t2.count("<!DOCTYPE"), "body", t2.count("</body>"))


if __name__ == "__main__":
    main()
