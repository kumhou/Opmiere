# Editor Shell Page Overrides

> **PROJECT:** Opmiere  
> **Page:** editor-shell (main NLE window)  
> **Overrides** `design-system/opmiere/MASTER.md`  
> **Implemented:** 0.2.29 UI shell v1 in `src/opmiere/web/static/index.html`

---

## Page-Specific Rules

### Layout

- **Not** a marketing hero layout. Full-viewport app chrome.
- Regions: **Top bar** · **Media bin** · **Preview** · **Inspector** · **Timeline**
- Timeline is non-negotiable primary: min ~220px height; user-resizable later
- Preview aspect follows project resolution (letterbox inside panel)
- Collapse media bin / inspector via toggle; remember last state in `localStorage` if easy

### Density

- Track height default ~36–44px (video), ~28–32px (audio)
- Clip label 10–11px; hide when clip width &lt; 48px
- Toolbar buttons group with 4px gaps; no 48px marketing CTAs in timeline chrome

### Color (shell)

- App bg `--color-background`; panels `--color-surface`
- Playhead: 2px `--color-accent` + drop shadow for readability on clips
- Selection: 1–2px `--color-primary` outline on clips / bin items
- Work In/Out: semi-transparent primary wash on ruler

### Interaction

- Keyboard is primary (JKL, I/O, Q/W, S, Space, Del, [ ] undo/redo)
- Pointer: click select, Ctrl multi, Shift range, drag move/trim edges
- Scrub: drag on ruler / preview; do not block Space play
- Context actions also in right panel + overflow menu (no gesture-only)

### Motion

- No page-transition overlays
- Clip drag: live position only (no spring bounce on timeline)
- Panel collapse: 150–180ms height/width ease

### Components unique to this page

| Component | Spec |
|-----------|------|
| Transport | Play/stop, TC display mono, In/Out buttons |
| Track header | Name, M/S/L, height grip later |
| Clip | Color fill, name, fade ticks, link badge |
| Marker lane | Diamonds on ruler; click seek |
| Log / agent | Monospace, muted, max 6–8 lines visible |

### Avoid on this page

- Large hero video backgrounds
- Soft pink brand fills
- Card carousels / testimonial chrome
- Autoplay decorative motion
- Bottom-tab mobile nav as primary (desktop editor)
