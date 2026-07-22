# Keybindings

The bottom of the screen shows two boxes: **Keys** (global) and **Browser** (file
navigation, visible only while the browser is open).

## Global

| Key | Action |
|-----|--------|
| `Ctrl+S` | Save |
| `Ctrl+Q` / `Ctrl+C Ctrl+C` | Quit (Ctrl+C twice) |
| `Ctrl+E` | Toggle the file browser |
| `Ctrl+P` | Command palette (theme, transparency, scroll sync, comment, insert markdown tag, ...) |
| `Ctrl+R` | Search (vim-like: type, then `n` / `p` / `Esc`) |
| `Ctrl+F` | View: split → editor → max editor → viewer → max viewer (the `max` modes drop the header and the hint bar for a clean full screen) |
| `Ctrl+B` | Rotate the split a quarter turn (editor left / top / right / bottom) |
| `Ctrl+W` | Width: 75/25 → 50/50 → 25/75 |
| `Ctrl+O` | Toggle conflict mode (auto / prompt) |

## Search

`Ctrl+R` opens a search bar in place of the **Keys** box (bottom-left). Type your query
(case-insensitive, matches highlight as you type), press `Enter` to browse the matches,
then `n` next, `p` previous, `Esc` to close. The bar shows the current position, e.g.
`/alpha   2/9`.

There is no header button: the command palette is `Ctrl+P`. It is ordered logically
(Insert markdown tag first in a markdown file, then Theme, Transparency, Scroll sync,
Toggle comment, Keys, ... Quit last) and hosts the options that are not on a key:
**insert markdown tag**, **theme**, **transparency**, **scroll sync**, and **toggle
comment** as a reliable fallback.

## Editor

| Key | Action |
|-----|--------|
| `Tab` / `Shift+Tab` | Indent / dedent every selected line |
| `Ctrl+/` (or `Ctrl+:` on AZERTY) | Comment / uncomment the selected lines |
| `Ctrl+K` | Delete the whole line (cursor lands on the line below, or above if last) |
| `Ctrl+C` (with a selection) | Copy the selection to the system clipboard (OSC 52) |
| `Ctrl+V` | Paste (or use the terminal's own paste, e.g. `Ctrl+Shift+V`) |
| `Ctrl+X` (with a selection) | Cut the selection |
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

## Insert markdown tag

In a markdown file, the `Ctrl+P` palette has an **Insert markdown tag** command. It
opens a picker for common snippets (unordered / ordered / task list, link, image,
horizontal rule, table, heading, bold, italic, code, blockquote, footnote) inserted at
the cursor.

Picking **Link** or **Image** opens a small file browser (Enter selects, Backspace goes
up, Esc cancels). The chosen path is written **relative to the markdown file**, never as
a hard-coded absolute path: a file in a subfolder becomes `./sub/img.png`, a file higher
up becomes `../img.png`.

Each row shows the syntax it inserts, and `...` at the top or bottom of the list marks
that there is more to scroll (there is no side scrollbar). If you have a **selection**,
the tag wraps it instead of a placeholder: bold on selected text gives `**text**`, a code
block wraps the selected lines, a list prefixes each line, and Link/Image use the
selection as the link text / image alt.

## File browser

| Key | Action |
|-----|--------|
| `Enter` | Enter the folder / open the file (`..` goes up) |
| `->` / `<-` | Expand / collapse (or step in / jump to parent) |
| `Del` | Go up a directory |
| `Ctrl+H` | Show / hide dotfiles |
| `n` / `d` | New file / new folder |
| `r` | Rename the selected entry |
| `i` | Info popup for the selected file or folder (type, size, lines, modified, permissions) |
| `Esc` | Close the browser |

## Modals

- **Conflict** (external change with unsaved edits): `R` reload disk, `K` keep buffer.
- **Unsaved on open** (open another file with a dirty buffer): `S` save & open,
  `O` open without saving, `C` cancel.
