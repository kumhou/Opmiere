# Editor Shell Page Overrides

> **PROJECT:** Opmiere  
> **Page:** editor-shell (main NLE window)  
> **Overrides** `design-system/opmiere/MASTER.md`  
> **Status:** HTML probe **COMPLETE** as of **0.3.0** (`src/opmiere/web/static/index.html`).  
> **Product shell:** Tauri scaffold **0.4** (`ui-desktop/`) — same tokens/layout regions; craft stays in Python.

---

## Implemented checklist (0.3.0)

| Spec | Status |
|------|--------|
| Full-viewport app chrome (not marketing) | ✅ |
| Regions: topbar · media · program · inspector · timeline | ✅ |
| Timeline primary + resizable vs program (split drag) | ✅ |
| Collapse media / inspector + `localStorage` | ✅ |
| Column width resize (media / inspector) | ✅ |
| Design tokens (slate / blue / amber, Inter, mono TC) | ✅ |
| Dense controls, track heights V/A | ✅ |
| Keyboard-first (JKL, I/O, Q/W, S, Space, Del, [ ], …) | ✅ |
| Key hint strip | ✅ |
| Playhead accent + selection ring + I/O band | ✅ |
| Transport + proxy scrub | ✅ |
| Track header M/S/L with active states | ✅ |
| Clip labels; hide when narrow | ✅ |
| Context menu on clips | ✅ |
| Marquee multi-select | ✅ |
| Drag-drop / file picker import | ✅ |
| Fullscreen preview | ✅ |
| Auto waveforms | ✅ |
| Selection inspector card + toast + Ctrl+S | ✅ |
| Linked clip badge | ✅ |
| Log / doctor / agent plan in inspector groups | ✅ |

---

## Page-Specific Rules (still apply for future polish)

### Layout

- Timeline non-negotiable primary region
- Preview aspect follows project resolution (letterbox)

### Interaction

- Keyboard is primary; pointer is secondary
- No gesture-only critical actions

### Avoid

- Large hero video backgrounds
- Soft pink brand fills
- Card carousels / testimonial chrome
- Autoplay decorative motion
- Bottom-tab mobile nav as primary
