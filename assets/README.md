# Style assets (optional)

Hand-tuned LUTs and audio beds. **Missing files are skipped** — styles still
apply grade effects without inventing pixels.

```
assets/
  luts/
    cold_terror.cube    # referenced by horror style when present
  audio/
    low_drone.wav       # optional horror bed
```

Also searched (in order):

1. `$OPMIERE_STYLE_ASSETS` env
2. package `opmiere/assets`
3. this repo `assets/`
4. process cwd `assets/`
5. open project bundle `assets/`

List at runtime: MCP `list_style_assets` or `GET /api/style_assets`.
