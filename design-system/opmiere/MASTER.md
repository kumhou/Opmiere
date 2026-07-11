# Design System Master File — Opmiere

> **LOGIC:** When building a specific page, first check `design-system/opmiere/pages/[page-name].md`.
> If that file exists, its rules **override** this Master file.
> If not, strictly follow the rules below.

**Source:** ui-ux-pro-max design intelligence + JH product decisions (agent-native NLE).  
**Generated base:** 2026-07-11 via `uipro` / `search.py --design-system`  
**Category:** Professional video editor (desktop web shell) — not a marketing landing page.  
**Design Dials:** Variance 3/10 (Centered / Minimal) | Motion 3/10 (Subtle) | Density 9/10 (Dense / Dashboard)

---

## Product positioning (design constraints)

- **Opmiere IS a video editor** (agent-native NLE). UI must feel like craft software (Premiere / Resolve class density), not a SaaS marketing site.
- **Dual surface:** human GUI + agent MCP share the same Editor. UI is a client of the Operation API — not a separate product identity.
- **Windows desktop first**, keyboard-first editing, timeline density over whitespace theater.
- **Anti-patterns (from skill + product):** AI purple/pink gradients as brand; pure `#000` OLED smear; emoji-as-icons; oversized fashion minimalism for the editor shell; autoplay hero video chrome.

---

## Global Rules

### Color Palette (pro NLE override)

ui-ux-pro-max matched "video" → pink brand. **Rejected for craft UI.**  
Tokens below keep dark cinematic base + blue selection language from the skill, replace pink with cool slate/cyan craft accents.

| Role | Hex | CSS Variable | Usage |
|------|-----|--------------|--------|
| Primary | `#7C9CFF` | `--color-primary` | Selection, links, focus ring |
| On Primary | `#0B0F14` | `--color-on-primary` | Text on primary chips |
| Secondary | `#5B6B8C` | `--color-secondary` | Secondary chrome, inactive |
| Accent / Playhead | `#F0B429` | `--color-accent` | Playhead, active marker, CTAs that need urgency |
| Background | `#0F1419` | `--color-background` | App chrome (not pure black) |
| Surface | `#1A222C` | `--color-surface` | Panels, tracks, cards |
| Surface Raised | `#243040` | `--color-surface-raised` | Hover / selected panel |
| Foreground | `#E8EEF4` | `--color-foreground` | Primary text |
| Muted | `#8B98A8` | `--color-muted` | Secondary labels, TC |
| Border | `rgba(255,255,255,0.08)` | `--color-border` | Dividers, track lines |
| Destructive | `#F07178` | `--color-destructive` | Ripple delete, purge |
| Success | `#3DD68C` | `--color-success` | Delivery ok, online media |
| Warning | `#E6A23C` | `--color-warning` | Offline media, validate warn |
| Ring | `#7C9CFF` | `--color-ring` | `:focus-visible` |
| Clip default | `#3D5A80` | `--color-clip` | Timeline clip fill |
| Track audio | `#2D6A4F` | `--color-track-audio` | Audio track tint |

**CSS variables (ship in web shell):**

```css
:root {
  --color-primary: #7C9CFF;
  --color-on-primary: #0B0F14;
  --color-secondary: #5B6B8C;
  --color-accent: #F0B429;
  --color-background: #0F1419;
  --color-surface: #1A222C;
  --color-surface-raised: #243040;
  --color-foreground: #E8EEF4;
  --color-muted: #8B98A8;
  --color-border: rgba(255, 255, 255, 0.08);
  --color-destructive: #F07178;
  --color-success: #3DD68C;
  --color-warning: #E6A23C;
  --color-ring: #7C9CFF;
  --color-clip: #3D5A80;
  --color-track-audio: #2D6A4F;
  --font-ui: "Inter", "Segoe UI", system-ui, sans-serif;
  --font-mono: "JetBrains Mono", "Cascadia Code", ui-monospace, Consolas, monospace;
  --radius-sm: 4px;
  --radius-md: 6px;
  --radius-lg: 10px;
  --space-xs: 2px;
  --space-sm: 4px;
  --space-md: 8px;
  --space-lg: 12px;
  --space-xl: 16px;
  --space-2xl: 24px;
  --space-3xl: 32px;
  --duration-fast: 120ms;
  --duration: 180ms;
  --ease: cubic-bezier(0.16, 1, 0.3, 1);
}
```

### Typography

- **UI / Heading / Body:** Inter (weights 400 / 500 / 600 / 700)
- **Timecode / frames / IDs:** JetBrains Mono or Cascadia Code (tabular figures)
- **Mood:** technical, precision, cinematic, dense utility (skill: developer / high-end utility)
- **Base size:** 12–13px UI chrome (dense editor); 11px track labels; 14px dialogs
- **Never** body text &lt; 11px for critical labels; TC can be 11px mono with strong contrast

```css
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
```

### Spacing (Density 9 — dashboard)

| Token | Value | Usage |
|-------|-------|-------|
| `--space-xs` | 2px | Clip edge handles, hairline |
| `--space-sm` | 4px | Icon gap, button pad tight |
| `--space-md` | 8px | Standard panel padding |
| `--space-lg` | 12px | Section gaps inside panel |
| `--space-xl` | 16px | Between major chrome regions |
| `--space-2xl` | 24px | Dialog padding |
| `--space-3xl` | 32px | Rare (empty states only) |

### Elevation / shadow

Keep shadows **subtle** on dark UI (skill: consistent elevation scale).

| Level | Value | Usage |
|-------|-------|-------|
| sm | `0 1px 2px rgba(0,0,0,0.35)` | Buttons, chips |
| md | `0 4px 12px rgba(0,0,0,0.45)` | Menus, popovers |
| lg | `0 12px 28px rgba(0,0,0,0.55)` | Modals |

### Motion (Subtle 3/10)

- Micro: **120–180ms**, `var(--ease)`
- Panel open/close: **≤220ms**
- No decorative ambient blobs in the editor shell
- Respect `prefers-reduced-motion: reduce` → snap, no transform thrash
- Playhead / scrub: no CSS animation lag; update via rAF or direct style

---

## Layout architecture (editor)

```
┌─────────────────────────────────────────────────────────────┐
│ Top bar: project · transport · export · agent status        │
├──────────┬──────────────────────────────┬───────────────────┤
│ Media    │ Program / Preview            │ Inspector         │
│ bin      │ (proxy scrub)                │ (clip / effects)  │
├──────────┴──────────────────────────────┴───────────────────┤
│ Timeline (tracks + clips + markers + work I/O)              │
│ + transport bar (JKL, I/O, TC)                              │
└─────────────────────────────────────────────────────────────┘
```

- **Primary workspace:** timeline + preview (60–70% vertical)
- **Secondary:** media bin + inspector (collapsible)
- **Keyboard-first:** every primary craft action has a shortcut (see `get_keymap_help`)
- **Adaptive:** ≥1280px three-column; &lt;1024px stack inspector under preview

---

## Component rules

### Buttons

- Primary: `--color-primary` fill, dark text; hover raised surface
- Danger: `--color-destructive` outline or fill for destructive confirm
- Ghost/secondary: border `var(--color-border)`, hover `--color-surface-raised`
- **All clickable:** `cursor: pointer`; disabled opacity 0.45 + `cursor: not-allowed`
- Min hit target **28×28** dense chrome; **preferred 32×32**; transport **36×36**
- `focus-visible: outline 2px solid var(--color-ring); outline-offset: 2px`

### Timeline clips

- Fill `--color-clip` / audio `--color-track-audio`; selected: ring `--color-primary`
- Muted: opacity 0.45 + MUTE badge
- Linked group: shared left border accent
- Handles: 6px edge hit zones (skill touch/target discipline)
- No emoji icons — use Lucide/Phosphor SVG (scissors, play, link, etc.)

### Panels

- Background `--color-surface`; header 28–32px, muted label 11px uppercase tracking
- Dividers 1px `var(--color-border)`
- Scroll regions: thin scrollbar, dark thumb

### Forms / inspector

- Visible labels (not placeholder-only)
- Errors under field; `aria-live` for export failures
- Numeric TC fields: mono font, tabular nums

### Feedback

- Toast 3–5s, `aria-live="polite"`, never steals focus
- Destructive: confirm dialog with explicit verb
- Export/long job: progress + cancel path

---

## Stack notes (current Opmiere web shell)

- **Now:** FastAPI + static `index.html` / vanilla JS (no React yet)
- **Tokens:** CSS variables in `:root` first; no hard-coded pink/AI purple
- **Icons:** SVG sprite or Lucide CDN; never emoji for structure
- **Future P3 shell:** may move to React + Tailwind; keep the same tokens

---

## Accessibility (CRITICAL — from ui-ux-pro-max)

- Text contrast ≥ 4.5:1 on surfaces (verify muted text ≥ 3:1 for large UI chrome only)
- Keyboard: Tab order = visual order; no traps in modals
- `focus-visible` rings always
- Color not sole meaning (mute uses icon + opacity)
- Skip link to timeline / preview when chrome is tall
- Reduced motion respected

---

## Pre-delivery checklist (editor UI)

- [ ] No emojis as icons (SVG only)
- [ ] `cursor: pointer` on all clickable elements
- [ ] Hover/focus states 120–180ms
- [ ] Dark text contrast checked on surface + muted
- [ ] Focus visible for keyboard
- [ ] `prefers-reduced-motion` respected
- [ ] Timeline usable at 1280×720 and 1920×1080
- [ ] Transport + Q/W/S/I/O still work after chrome restyle
- [ ] Dirty / offline media / validate errors readable at a glance

---

## How to use with ui-ux-pro-max

```powershell
# From repo root
python .claude\skills\ui-ux-pro-max\scripts\search.py "query" --design-system -p "Opmiere"
python .claude\skills\ui-ux-pro-max\scripts\search.py "keyboard dense panel" --domain ux
python .claude\skills\ui-ux-pro-max\scripts\search.py "focus truncation flex" --stack html-tailwind

# Page override
python .claude\skills\ui-ux-pro-max\scripts\search.py "..." --design-system --persist --page "timeline" -p "Opmiere"
```

**Retrieval rule for agents:**

1. Read `design-system/opmiere/MASTER.md`
2. If `design-system/opmiere/pages/<page>.md` exists, its rules win
3. Then implement
