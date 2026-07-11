"""UI shell v4: column resize, drag-drop upload, preview fullscreen."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "src" / "opmiere" / "web" / "static" / "index.html"
CSS = ROOT / "scripts" / "_shell_style.css"

EXTRA_CSS = r"""
/* —— shell v4 —— */
#app {
  grid-template-columns: var(--media-w, 260px) minmax(0, 1fr) var(--insp-w, 300px);
}
#app.hide-media { grid-template-columns: 0px minmax(0, 1fr) var(--insp-w, 300px); }
#app.hide-inspector { grid-template-columns: var(--media-w, 260px) minmax(0, 1fr) 0px; }
#app.hide-media.hide-inspector { grid-template-columns: 0px minmax(0, 1fr) 0px; }

.col-resizer {
  position: absolute; top: 0; bottom: 0; width: 5px; cursor: col-resize;
  z-index: 8; background: transparent;
}
.col-resizer:hover, .col-resizer.active { background: rgba(124, 156, 255, 0.35); }
#panel-media { position: relative; }
#panel-inspector { position: relative; }
#resizeMedia { right: 0; }
#resizeInsp { left: 0; }

#dropZone {
  border: 1px dashed var(--color-border);
  border-radius: var(--radius-md);
  padding: 10px 8px;
  text-align: center;
  color: var(--color-muted);
  font-size: 11px;
  margin: 6px 0 8px;
  background: var(--color-background);
  transition: border-color var(--duration-fast) var(--ease), background var(--duration-fast) var(--ease);
  cursor: pointer;
}
#dropZone.dragover {
  border-color: var(--color-primary);
  background: rgba(124, 156, 255, 0.08);
  color: var(--color-foreground);
}
#dropZone input[type=file] { display: none; }

#panel-preview.fullscreen {
  position: fixed !important;
  inset: 0 !important;
  z-index: 40;
  grid-area: unset !important;
  background: #000;
}
#panel-preview.fullscreen #previewStack { height: 100%; }
#panel-preview.fullscreen #playerWrap { flex: 1; max-height: none; border: none; border-radius: 0; }
#panel-preview.fullscreen .panel-head { background: rgba(15,20,25,0.9); }

#btnFullscreen[aria-pressed="true"] {
  border-color: var(--color-accent);
  color: var(--color-accent);
}
"""

V4_JS = r"""
    // —— UI shell v4: column resize, drag-drop, fullscreen ——
    (function shellV4() {
      const KEY = 'opmiere.shell.v4';
      const defaults = { mediaW: 260, inspW: 300 };
      function load() {
        try { return { ...defaults, ...JSON.parse(localStorage.getItem(KEY) || '{}') }; }
        catch { return { ...defaults }; }
      }
      function save(s) {
        try { localStorage.setItem(KEY, JSON.stringify(s)); } catch (_) {}
      }
      let st = load();
      const app = document.getElementById('app');
      if (!app) return;
      function applyCols() {
        app.style.setProperty('--media-w', Math.round(st.mediaW) + 'px');
        app.style.setProperty('--insp-w', Math.round(st.inspW) + 'px');
      }
      applyCols();

      function bindColResize(handleId, which) {
        const h = document.getElementById(handleId);
        if (!h) return;
        let drag = false, startX = 0, startW = 0;
        h.addEventListener('pointerdown', (e) => {
          drag = true; startX = e.clientX;
          startW = which === 'media' ? st.mediaW : st.inspW;
          h.setPointerCapture(e.pointerId);
          h.classList.add('active');
          e.preventDefault();
        });
        h.addEventListener('pointermove', (e) => {
          if (!drag) return;
          const dx = e.clientX - startX;
          if (which === 'media') {
            st.mediaW = Math.min(420, Math.max(180, startW + dx));
          } else {
            st.inspW = Math.min(460, Math.max(220, startW - dx));
          }
          applyCols();
        });
        const end = (e) => {
          if (!drag) return;
          drag = false; h.classList.remove('active');
          try { h.releasePointerCapture(e.pointerId); } catch (_) {}
          save(st);
        };
        h.addEventListener('pointerup', end);
        h.addEventListener('pointercancel', end);
      }
      bindColResize('resizeMedia', 'media');
      bindColResize('resizeInsp', 'insp');

      // Fullscreen preview
      const btnFs = document.getElementById('btnFullscreen');
      const prev = document.getElementById('panel-preview');
      if (btnFs && prev) {
        btnFs.onclick = () => {
          const on = !prev.classList.contains('fullscreen');
          prev.classList.toggle('fullscreen', on);
          btnFs.setAttribute('aria-pressed', on ? 'true' : 'false');
          btnFs.textContent = on ? 'Exit FS' : 'FS';
        };
        document.addEventListener('keydown', (e) => {
          if (e.key === 'Escape' && prev.classList.contains('fullscreen')) {
            prev.classList.remove('fullscreen');
            btnFs.setAttribute('aria-pressed', 'false');
            btnFs.textContent = 'FS';
          }
        });
      }

      // Drag-drop + file picker upload
      const zone = document.getElementById('dropZone');
      const fileIn = document.getElementById('filePick');
      async function uploadFiles(fileList) {
        if (!fileList || !fileList.length) return;
        const fd = new FormData();
        for (const f of fileList) fd.append('files', f);
        const buildProxy = !!(document.getElementById('buildProxy') || {}).checked;
        try {
          if (typeof log === 'function') log('uploading ' + fileList.length + ' file(s)…');
          const r = await fetch('/api/upload_place?build_proxy=' + (buildProxy ? 'true' : 'false'), {
            method: 'POST', body: fd,
          });
          const text = await r.text();
          let data; try { data = JSON.parse(text); } catch { data = { raw: text }; }
          if (!r.ok) throw new Error(data.detail || data.raw || r.statusText);
          if (data.timeline && typeof renderTimeline === 'function') renderTimeline(data.timeline);
          if (typeof setDirty === 'function') setDirty(true);
          if (typeof refreshBin === 'function') {
            try { await refreshBin(); } catch (_) {}
          } else if (document.getElementById('btnBin')) {
            document.getElementById('btnBin').click();
          }
          if (typeof log === 'function') {
            log('placed ' + (data.count || 0) + (data.errors && data.errors.length ? ' err=' + data.errors.length : ''));
          }
          // auto proxy after place
          if (document.getElementById('btnProxy')) {
            try { document.getElementById('btnProxy').click(); } catch (_) {}
          }
        } catch (e) {
          if (typeof log === 'function') log(String(e.message || e));
          else alert(String(e.message || e));
        }
      }
      if (zone) {
        zone.addEventListener('click', () => fileIn && fileIn.click());
        zone.addEventListener('dragover', (e) => {
          e.preventDefault(); zone.classList.add('dragover');
        });
        zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
        zone.addEventListener('drop', (e) => {
          e.preventDefault(); zone.classList.remove('dragover');
          if (e.dataTransfer && e.dataTransfer.files) uploadFiles(e.dataTransfer.files);
        });
      }
      if (fileIn) {
        fileIn.addEventListener('change', () => {
          if (fileIn.files) uploadFiles(fileIn.files);
          fileIn.value = '';
        });
      }
    })();
"""


def main() -> None:
    t = INDEX.read_text(encoding="utf-8")

    if "shell v4" not in t:
        t = t.replace("</style>", EXTRA_CSS + "\n</style>", 1)

    # drop zone in media panel after Place batch button area — insert after btnBatch if present
    if 'id="dropZone"' not in t:
        drop = (
            '<div id="dropZone" title="Drop media files or click to browse">'
            "Drop media here · click to browse"
            '<input id="filePick" type="file" multiple '
            'accept="video/*,audio/*,image/*"/>'
            "</div>"
        )
        if 'id="btnBatch"' in t:
            t = t.replace(
                'id="btnBatch"',
                'id="btnBatch"',
                1,
            )
            # after the button that contains btnBatch
            t = re.sub(
                r'(<button[^>]*id="btnBatch"[^>]*>.*?</button>)',
                r"\1" + drop,
                t,
                count=1,
                flags=re.S,
            )
        else:
            # fallback: after panel-media body open
            t = t.replace(
                'id="panel-media"',
                'id="panel-media"',
                1,
            )
            t = re.sub(
                r'(id="panel-media"[^>]*>.*?<div class="panel-body"[^>]*>)',
                r"\1" + drop,
                t,
                count=1,
                flags=re.S,
            )

    # column resizers
    if 'id="resizeMedia"' not in t:
        t = t.replace(
            'id="panel-media"',
            'id="panel-media"',
            1,
        )
        t = re.sub(
            r'(<section class="panel" id="panel-media">)',
            r'\1<div class="col-resizer" id="resizeMedia" title="Drag to resize"></div>',
            t,
            count=1,
        )
    if 'id="resizeInsp"' not in t:
        t = re.sub(
            r'(<section class="panel" id="panel-inspector">)',
            r'\1<div class="col-resizer" id="resizeInsp" title="Drag to resize"></div>',
            t,
            count=1,
        )

    # fullscreen button in preview head
    if 'id="btnFullscreen"' not in t:
        t = re.sub(
            r'(id="panel-preview"[^>]*>\s*<div class="panel-head"><h2>Program</h2>)',
            r'\1<div class="tools">'
            r'<button type="button" class="secondary icon-btn" id="btnFullscreen" '
            r'aria-pressed="false" title="Fullscreen preview">FS</button></div>',
            t,
            count=1,
        )

    if "UI shell v4" not in t:
        if "  </script>" in t:
            t = t.replace("  </script>", V4_JS + "  </script>", 1)
        else:
            t = t.replace("</script>", V4_JS + "</script>", 1)

    css = CSS.read_text(encoding="utf-8") if CSS.exists() else ""
    if "shell v4" not in css:
        CSS.write_text(css.rstrip() + "\n" + EXTRA_CSS, encoding="utf-8")

    INDEX.write_text(t, encoding="utf-8")
    print("dropZone", 'id="dropZone"' in t)
    print("resize", 'resizeMedia' in t and "resizeInsp" in t)
    print("fs", "btnFullscreen" in t)
    print("v4js", "UI shell v4" in t)
    print("DOCTYPE", t.count("<!DOCTYPE"), "body", t.count("</body>"))


if __name__ == "__main__":
    main()
