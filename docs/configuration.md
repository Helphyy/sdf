# Configuration & persistence

Settings you change at runtime are written to `~/.config/sdf/config.json` (honoring
`XDG_CONFIG_HOME`) and restored on the next launch. A malformed or hand-edited config
never crashes sdf: unknown or invalid values fall back to their defaults.

## Settings

| Setting | Default | Changed with |
|---------|---------|--------------|
| `theme` | `gruvbox` | Command palette → Theme (`Ctrl+P`) |
| `conflict_mode` | `auto` | `Ctrl+O` |
| `transparent` | `false` | Command palette → Transparency |
| `scroll_sync` | `true` | Command palette → Scroll sync |
| `rotation` | `0` | `Ctrl+B` |
| `ratio_idx` | `0` | `Ctrl+W` |
| `show_hidden` | `false` | `Ctrl+H` (in the browser) |

Example `~/.config/sdf/config.json`:

```json
{
  "theme": "gruvbox",
  "conflict_mode": "auto",
  "transparent": false,
  "scroll_sync": true,
  "rotation": 0,
  "ratio_idx": 0,
  "show_hidden": false
}
```

## Themes

Any Textual theme works: `gruvbox` (default), `nord`, `dracula`, `tokyo-night`,
`catppuccin-mocha`, `monokai`, `solarized-dark`, ... Pick one from the command palette
(`Ctrl+P` → Theme) and it is remembered, or pass `--theme NAME` for one session.

## Transparency

Toggle from the command palette (Transparency). When on, the whole UI becomes
transparent so your terminal's own background shows through. `--transparent` enables it
for one session.

## Notes

- **Encoding**: sdf reads/writes UTF-8. A non-UTF8 file still opens without crashing,
  but invalid bytes show as `?` (U+FFFD); only edit UTF-8 files.
- **External-change detection**: an `(mtime_ns, size)` signature polled every 0.5 s.
