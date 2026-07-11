# Opmiere design system

Design source of truth for the **UI shell** and any human-facing chrome.

| Path | Role |
|------|------|
| `opmiere/MASTER.md` | Global tokens, layout, a11y, component rules |
| `opmiere/pages/*.md` | Page overrides (e.g. `editor-shell`) |

## Tooling: UI/UX Pro Max

Installed via:

```powershell
npm install -g ui-ux-pro-max-cli@latest
cd G:\Development\Opmiere
uipro init --ai claude --force
```

Skill lives at `.claude/skills/ui-ux-pro-max/` (also global `~\.claude\skills\` and `~\.grok\skills\ui-ux-pro-max\` for Grok).

```powershell
# Re-run design intelligence
python .claude\skills\ui-ux-pro-max\scripts\search.py "professional video editor NLE dark dense" --design-system -p "Opmiere" -f markdown --persist --density 9 --motion 3

# Domain search
python .claude\skills\ui-ux-pro-max\scripts\search.py "keyboard focus density" --domain ux
python .claude\skills\ui-ux-pro-max\scripts\search.py "panel layout" --stack html-tailwind
```

**Note:** Auto “video” product matching often suggests pink brand colors. Opmiere **overrides** those in `MASTER.md` for craft-NLE identity (slate + blue selection + amber playhead).
