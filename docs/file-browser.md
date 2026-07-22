# File browser

Open and close the sidebar with `Ctrl+E` (or `Esc` from inside it). It is a bordered
panel titled with the current folder; its outline turns yellow while it is focused.

The top entry `..` is a real, selectable node: arrow to it and press `Enter` to go up.

## Navigation

| Key | Action |
|-----|--------|
| `Enter` | Enter the folder (make it the new root), or open the file; on `..`, go up |
| `Right` / `Left` | Expand / collapse the folder in place (Left on a file jumps to its folder) |
| `Del` | Go up to the parent folder |
| `Ctrl+H` | Show / hide dotfiles (persisted) |
| `Esc` | Close the browser |

`Enter` on a folder navigates *into* it rather than unfolding it, keeping the tree
uncluttered. Use `Right` when you just want to peek inside without changing the root.

## File operations

| Key | Action |
|-----|--------|
| `n` | New file (in the selected folder, or the current directory) |
| `d` | New folder |
| `r` | Rename the selected file or folder |
| `i` | Info popup: type, size, line count, last modified, permissions |

`i` opens a read-only popup about the highlighted entry (on the `..` root it describes
the current folder); close it with `Esc`, `Enter` or `i`.

New file / folder and rename open a small prompt. Renaming the file you currently have
open updates the editor to follow it.

## Opening files

Selecting a file opens it. If the current buffer has unsaved changes, a modal asks:
`S` save & open, `O` open without saving, `C` cancel.
