# Preview & rendering

## Per file type

The live preview only makes sense for markdown, so sdf adapts:

- **Markdown** (`.md`, `.markdown`, ...): rendered preview, synced scrolling.
- **PDF** (`.pdf`): the extracted text is shown in the preview, read-only (via the
  pure-Python `pypdf`, no system dependency). Saving is disabled.
- **Anything else** (`.py`, `.rs`, ...): the preview is hidden and the editor takes the
  full width. The file is still syntax-highlighted and fully editable.

## Syntax highlighting

The editor detects the language from the file extension and highlights it using the
tree-sitter language pack (300+ languages, bundled, offline). The token colors keep the
editor's own background (gruvbox by default). The preview also highlights fenced code
blocks.

## Markdown rendering

The preview is styled natively (no external tools), so it stays a clean `pipx install`:

- Headings have a clear visual hierarchy (a terminal has a fixed font size, so "size"
  is conveyed by weight, colour and underline).
- Blockquotes get an accent bar, tables get styled headers, and each **code fence is
  labelled with its language**.
- **Task lists** render as real checkboxes: `- [x]` → ✔, `- [ ]` → ☐, with no redundant
  bullet, while ordinary lists and code blocks are left untouched.
- A **single newline becomes a real line break** in the preview (no need for the
  markdown two-trailing-spaces `<br>`); blank lines still separate paragraphs.

## Scroll sync

The editor and preview scroll together, in both directions and proportionally. Scroll
the editor and the preview follows; scroll the preview and the editor follows. Toggle it
from the command palette ("Scroll sync"); the setting is persisted.

The preview outline turns blue while the editor is the active pane.

## Layout

- `Ctrl+F` cycles split → full editor → full viewer (maximizing either pane).
- `Ctrl+B` rotates the split a quarter turn (editor left / top / right / bottom).
- `Ctrl+W` cycles the width 75/25 → 50/50 → 25/75.

The editor border shows a `[position] [width]` indicator.
