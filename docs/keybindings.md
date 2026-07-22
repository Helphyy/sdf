# Keybindings

The bottom of the screen shows two boxes: **Keys** (global) and **Browser** (file
navigation, visible only while the browser is open).

## Global

| Key | Action |
|-----|--------|
| `Ctrl+S` | Save |
| `Ctrl+Q` / `Ctrl+C Ctrl+C` | Quit (Ctrl+C twice) |
| `Ctrl+E` | Toggle the file browser |
| `Ctrl+P` | Command palette (theme, transparency, scroll sync, comment, ...) |
| `Ctrl+F` | View: split → full editor → full viewer (maximize a pane) |
| `Ctrl+B` | Rotate the split a quarter turn (editor left / top / right / bottom) |
| `Ctrl+W` | Width ratio 75/25 → 50/50 → 25/75 |
| `Ctrl+O` | Toggle conflict mode (auto / prompt) |

There is no header button: the command palette is `Ctrl+P`. It is ordered logically
(Theme, Transparency, Scroll sync, Toggle comment, Keys, ... Quit last) and hosts the
options that are not on a key: **theme**, **transparency**, **scroll sync**, and
**toggle comment** as a reliable fallback.

## Editor

| Key | Action |
|-----|--------|
| `Tab` / `Shift+Tab` | Indent / dedent every selected line |
| `Ctrl+/` (or `Ctrl+:` on AZERTY) | Comment / uncomment the selected lines |
| `Ctrl+K` | Delete the whole line (cursor lands on the line below, or above if last) |
| `Ctrl+Z` / `Ctrl+Shift+Z` | Undo / redo |
| `Del` (with a selection) | Delete the selection |
| type `*` `_` `~` `` ` `` with a selection | Wrap it; `*` cycles none → italic → bold → none |
| type `(` `[` `{` `<` `"` `'` (or their closing char) with a selection | Wrap in the pair (toggle) |

Comment syntax is chosen per language (`#`, `//`, `--`, `;`, `%`, `<!-- -->`, ...) and
the marker is placed at column 0. In a markdown file, a fenced code block is commented
with **its** language's syntax. If the language is unknown, sdf asks for the prefix and
remembers it for the session.

The editor is single-caret (no VSCode-style multi-cursor), but indent, comment and
delete-line all operate on the whole selection.

## Modals

- **Conflict** (external change with unsaved edits): `R` reload disk, `K` keep buffer.
- **Unsaved on open** (open another file with a dirty buffer): `S` save & open,
  `O` open without saving, `C` cancel.
