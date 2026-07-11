"""UI shell v3: key hint bar, details persistence, polish CSS."""
from __future__ import annotations

import re
from pathlib import Path

INDEX = Path(__file__).resolve().parents[1] / "src" / "opmiere" / "web" / "static" / "index.html"
CSS = Path(__file__).resolve().parents[1] / "scripts" / "_shell_style.css"

EXTRA_CSS = """
/* —— shell v3 —— */
#keyHint {
  display: flex; flex-wrap: wrap; gap: 6px 10px; align-items: center;
  padding: 3px 10px; font-size: 10px; color: var(--color-muted);
  border-top: 1px solid var(--color-border); background: var(--color-surface);
  font-family: var(--font-mono); flex-shrink: 0;
}
#keyHint kbd {
  display: inline-block; padding: 0 4px; border-radius: 3px;
  border: 1px solid var(--color-border); background: var(--color-background);
  color: var(--color-foreground); font-size: 9px; margin-right: 2px;
}
#tracks > p {
  display: flex; align-items: center; justify-content: center;
  min-height: 100px; color: var(--color-muted); font-size: 12px;
}
.panel-body::-webkit-scrollbar { width: 8px; height: 8px; }
.panel-body::-webkit-scrollbar-thumb {
  background: var(--color-surface-raised); border-radius: 4px;
}
.panel-body::-webkit-scrollbar-track { background: transparent; }
#topbar .brand > span:first-child {
  background: linear-gradient(135deg, var(--color-primary), #a8b8ff);
  -webkit-background-clip: text; background-clip: text; color: transparent;
}
.bin-item:hover { border-color: rgba(124, 156, 255, 0.45); }
"""

V3_JS = """
    // —— UI shell v3: inspector group memory ——
    (function shellV3() {
      const KEY = 'opmiere.shell.details.v1';
      function load() {
        try { return JSON.parse(localStorage.getItem(KEY) || '{}'); } catch { return {}; }
      }
      function save(m) {
        try { localStorage.setItem(KEY, JSON.stringify(m)); } catch (_) {}
      }
      const map = load();
      document.querySelectorAll('details.tool-group').forEach((d, i) => {
        const title = (d.querySelector('summary') || {}).textContent || ('g' + i);
        const k = String(title).trim();
        if (k in map) d.open = !!map[k];
        d.addEventListener('toggle', () => {
          map[k] = d.open;
          save(map);
        });
      });
    })();
"""

HINT = (
    '<div id="keyHint">'
    "<span><kbd>Space</kbd>play</span>"
    "<span><kbd>J</kbd><kbd>K</kbd><kbd>L</kbd>shuttle</span>"
    "<span><kbd>I</kbd><kbd>O</kbd>work</span>"
    "<span><kbd>Q</kbd><kbd>W</kbd>trim</span>"
    "<span><kbd>S</kbd>split</span>"
    "<span><kbd>C</kbd>razor</span>"
    "<span><kbd>[</kbd><kbd>]</kbd>undo/redo</span>"
    "<span><kbd>?</kbd>help</span>"
    "</div>"
)


def main() -> None:
    t = INDEX.read_text(encoding="utf-8")

    if "shell v3" not in t:
        if "</style>" not in t:
            raise SystemExit("no style")
        t = t.replace("</style>", EXTRA_CSS + "\n</style>", 1)

    if 'id="keyHint"' not in t:
        if 'id="statusBar"' in t:
            t = re.sub(
                r'(<div id="statusBar"[^>]*>.*?</div>)',
                r"\1\n" + HINT,
                t,
                count=1,
                flags=re.S,
            )
        else:
            t = t.replace("</body>", HINT + "\n</body>", 1)

    if "UI shell v3" not in t:
        if "  </script>" in t:
            t = t.replace("  </script>", V3_JS + "  </script>", 1)
        else:
            t = t.replace("</script>", V3_JS + "</script>", 1)

    # keep css file in sync
    css = CSS.read_text(encoding="utf-8") if CSS.exists() else ""
    if "shell v3" not in css:
        CSS.write_text(css.rstrip() + "\n" + EXTRA_CSS, encoding="utf-8")

    INDEX.write_text(t, encoding="utf-8")
    print("keyHint", 'id="keyHint"' in t)
    print("v3 js", "UI shell v3" in t)
    print("v3 css", "shell v3" in t)
    print("DOCTYPE", t.count("<!DOCTYPE"), "body", t.count("</body>"))


if __name__ == "__main__":
    main()
