# SDF

**SDF** (Simple Draft Frame) is a full-terminal markdown editor with a live, synced
preview, in the spirit of Splitmark but with the feature nobody else has: **the buffer
reloads by itself when another process edits the open file** (typically an AI agent
writing the `.md` while you watch it), and it never silently overwrites your unsaved
local changes.

It edits in place, creates no stray directory, and keeps your settings under
`~/.config/sdf/` Neovim-style.

![SDF editor and live preview](docs/img/editor.png)

## Why SDF

- **Live reload on external change.** Point it at a file an agent (or `git`, or another
  editor) is writing, and the preview and buffer follow along, with a safe conflict
  prompt when you have unsaved edits.
- **Split editor + rendered preview**, scrolling in sync both ways.
- **Syntax highlighting for 300+ languages**, bundled and offline.
- **Per-file-type preview**: markdown renders, PDF shows its extracted text, everything
  else hides the preview and goes full editor.
- **Real editing commands**: mass indent/comment, delete line, auto-surround, undo/redo.
- **Insert markdown tags** from the palette (wrapping the current selection when there is
  one), with a file picker for links/images that writes the path relative to the document
  (`./sub/img.png`, `../img.png`).
- **A file browser** with create / rename / navigate, an `i` info popup, and a command
  palette.
- **Themeable, persistent, transparent-capable**, entirely from the keyboard.

Pure `pipx` install, only pip dependencies, no external binaries.

## Install

```bash
pipx install git+https://github.com/Helphyy/sdf.git
```

`sdf` is then on your PATH. (Python 3.9+.)

## Quick start

```bash
sdf notes.md                    # open (or prepare) a file
sdf --example                   # open the bundled example to try the live preview
sdf --version                   # print the version
sdf notes.md --theme nord       # theme for this session
sdf notes.md --transparent      # transparent UI for this session
```

A non-existent file opens on an empty buffer and is created on first save.

## Highlights

- `Ctrl+R` search (vim-like: type, then `n` / `p` / `Esc`) · `Ctrl+E` file browser ·
  `Ctrl+F` view (split / editor / max editor / viewer / max viewer, where `max` hides the
  header and hint bar) ·
  `Ctrl+B` rotate the split · `Ctrl+W` width · `Ctrl+P` command palette.
- Select lines and `Tab` / `Shift+Tab` to indent / dedent them all; `Ctrl+/`
  (or `Ctrl+:` on AZERTY) to comment / uncomment per language.
- Select text and type `*`, `` ` ``, `~`, `(` ... to wrap it (`*` cycles
  none → italic → bold → none). `Ctrl+C` copies the selection, `Ctrl+V` pastes,
  `Ctrl+X` cuts.
- The preview turns a single newline into a real line break, labels each code fence
  with its language, and renders task lists with proper checkboxes.

## Documentation

Full reference in [`docs/`](docs/index.md):

- [Keybindings](docs/keybindings.md)
- [File browser](docs/file-browser.md)
- [Preview & rendering](docs/preview.md)
- [Configuration & persistence](docs/configuration.md)

## License

GNU Affero General Public License v3.0 (AGPL-3.0). See [LICENSE](LICENSE).
