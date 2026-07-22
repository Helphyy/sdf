"""SDF (Simple Draft Frame) - terminal markdown editor/preview that reloads on external changes.

Core idea: the buffer reloads whenever an external process (e.g. an agent) edits
the open file on disk, without ever silently overwriting unsaved local changes.
Edits in place, creates no stray directory. User settings persist under
~/.config/sdf/ (Neovim-style).
"""

from __future__ import annotations

import os
import re
import stat as stat_mod
from datetime import datetime
from pathlib import Path

from markdown_it import MarkdownIt
from rich.markup import escape
from rich.text import Text
from textual.app import App, ComposeResult, SystemCommand
from textual.content import Content
from textual.binding import Binding
from textual.command import DiscoveryHit, Hits
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.system_commands import SystemCommandsProvider
from textual.widgets import (
    DirectoryTree, Header, Input, Label, ListItem, ListView, Markdown, Static, TextArea,
)
from textual.widgets._markdown import MarkdownFence
from textual.widgets.text_area import Selection, TextAreaTheme

from .config import Config


# Language -> (comment open, comment close). Close is "" for line comments.
COMMENTS = {
    "#": ("python", "ruby", "bash", "yaml", "toml", "perl", "r", "julia",
          "elixir", "nix", "dockerfile", "make", "cmake", "properties", "ini"),
    "//": ("javascript", "typescript", "tsx", "c", "cpp", "csharp", "java",
           "kotlin", "scala", "go", "rust", "php", "swift", "dart", "zig", "scss"),
    "--": ("sql", "lua", "haskell"),
    ";": ("clojure", "scheme", "commonlisp"),
    "%": ("latex",),
}
LINE_COMMENT = {lang: token for token, langs in COMMENTS.items() for lang in langs}
BLOCK_COMMENT = {  # (open, close) wrapped per line
    "html": ("<!--", "-->"), "xml": ("<!--", "-->"), "markdown": ("<!--", "-->"),
    "css": ("/*", "*/"), "ocaml": ("(*", "*)"),
}
# Comment prefixes the user typed for otherwise-unknown languages (session cache).
CUSTOM_COMMENTS: dict = {}

# Type one of these with text selected -> wrap the selection (bold/code/... or
# pairs). Typing the same marker again on an already-wrapped selection removes it.
SURROUND = {
    "*": ("*", "*"), "_": ("_", "_"), "~": ("~", "~"), "`": ("`", "`"),
    '"': ('"', '"'), "'": ("'", "'"),
    "(": ("(", ")"), ")": ("(", ")"),
    "[": ("[", "]"), "]": ("[", "]"),
    "{": ("{", "}"), "}": ("{", "}"),
    "<": ("<", ">"), ">": ("<", ">"),
}


class CodeEditor(TextArea):
    """TextArea with mass indent / dedent and comment toggle over a selection.

    Textual's editor is single-caret (no VSCode multi-cursor), so editing the
    start of many lines at once is done through indent/dedent (Tab / Shift+Tab)
    and the comment toggle (Ctrl+/)."""

    BINDINGS = [
        # Comment toggle. On AZERTY "/" needs Shift, so the ":" key (with and
        # without shift) and the usual slash/underscore codes are all bound.
        Binding("ctrl+underscore", "toggle_comment", "Comment", show=False),
        Binding("ctrl+slash", "toggle_comment", "Comment", show=False),
        Binding("ctrl+colon", "toggle_comment", "Comment", show=False),
        Binding("ctrl+shift+colon", "toggle_comment", "Comment", show=False),
        Binding("ctrl+k", "delete_whole_line", "Delete line", show=False),
        Binding("ctrl+shift+z", "redo", "Redo", show=False),  # undo is ctrl+z (native)
    ]

    def action_delete_whole_line(self) -> None:
        """Delete the current (or selected) lines; land on the line below, or the
        line above if there is none."""
        doc = self.document
        r0, r1 = self._selected_rows()
        last = doc.line_count - 1
        if r1 < last:
            self.replace("", (r0, 0), (r1 + 1, 0))
            target = r0
        elif r0 > 0:
            self.replace("", (r0 - 1, len(doc.get_line(r0 - 1))),
                         (last, len(doc.get_line(last))))
            target = r0 - 1
        else:
            self.replace("", (0, 0), (last, len(doc.get_line(last))))
            target = 0
        self.move_cursor((min(target, doc.line_count - 1), 0))

    def _effective_language(self, row: int) -> str:
        """Language for commenting at `row`. In markdown, a fenced code block uses
        its own language (so a python block comments with #, not <!-- -->)."""
        if (self.language or "") != "markdown":
            return self.language or ""
        fence_lang = None
        for i in range(row):
            s = self.document.get_line(i).lstrip()
            if s.startswith("```") or s.startswith("~~~"):
                if fence_lang is None:
                    info = s.lstrip("`~ ").strip()
                    fence_lang = (info.split()[0] if info else "text")
                else:
                    fence_lang = None
        return fence_lang or "markdown"

    def _comment_tokens(self, lang: str):
        if lang in CUSTOM_COMMENTS:
            return CUSTOM_COMMENTS[lang]
        if lang in LINE_COMMENT:
            return (LINE_COMMENT[lang], "")
        if lang in BLOCK_COMMENT:
            return BLOCK_COMMENT[lang]
        return (None, None)

    def action_toggle_comment(self) -> None:
        r0, r1 = self._selected_rows()
        lang = self._effective_language(r0)
        opener, closer = self._comment_tokens(lang)
        if opener is None:
            # Unknown language: ask for the comment prefix and remember it.
            def got(value: str) -> None:
                value = value.strip()
                if value:
                    CUSTOM_COMMENTS[lang or "?"] = (value, "")
                    self._toggle_comment(value, "", r0, r1)
            self.app.push_screen(
                PromptScreen(f"Comment prefix for '{lang or 'this file'}':"), got)
            return
        self._toggle_comment(opener, closer, r0, r1)

    def _toggle_comment(self, opener: str, closer: str, r0: int, r1: int) -> None:
        rows = [r for r in range(r0, r1 + 1) if self.document.get_line(r).strip()]
        if not rows:
            return
        # Marker always at column 0 (never after the indentation).
        commented = all(self.document.get_line(r).startswith(opener) for r in rows)
        for row in rows:
            line = self.document.get_line(row)
            if commented:
                cut = len(opener) + (1 if line[len(opener):len(opener) + 1] == " " else 0)
                self.replace("", (row, 0), (row, cut))
                if closer:
                    stripped = self.document.get_line(row).rstrip()
                    end = len(stripped)
                    if stripped.endswith(closer):
                        start = end - len(closer) - (1 if stripped[:end - len(closer)].endswith(" ") else 0)
                        self.replace("", (row, start), (row, end))
            else:
                self.insert(f"{opener} ", (row, 0))
                if closer:
                    self.insert(f" {closer}", (row, len(self.document.get_line(row))))
        self.selection = Selection((r0, 0), (r1, len(self.document.get_line(r1))))

    async def _on_key(self, event) -> None:
        # Auto-surround: typing a wrap char with a selection wraps it (** ~~ ` ...).
        if (not self.read_only and event.character in SURROUND
                and self.selection.start != self.selection.end):
            event.prevent_default()
            event.stop()
            self._surround(event.character)
            return
        if event.key in ("tab", "shift+tab"):
            r0, r1 = self._selected_rows()
            if event.key == "shift+tab":
                event.prevent_default()
                event.stop()
                self._reindent(r0, r1, dedent=True)
                return
            if r0 != r1:  # multi-line selection -> indent every line
                event.prevent_default()
                event.stop()
                self._reindent(r0, r1, dedent=False)
                return
        await super()._on_key(event)

    def _surround(self, char: str) -> None:
        """Wrap the selection. For doublable markers (* _ ~ `) it cycles
        none -> single (italic) -> double (bold) -> none; for pairs (), [] it
        toggles wrap/unwrap. Re-typing therefore also removes the formatting."""
        opener, closer = SURROUND[char]
        start, end = self.selection.start, self.selection.end
        if start > end:
            start, end = end, start
        (sr, sc), (er, ec) = start, end
        doublable = opener == closer

        def wrapped(n: int) -> bool:
            before = self.document.get_line(sr)[max(0, sc - n * len(opener)):sc]
            after = self.document.get_line(er)[ec:ec + n * len(closer)]
            return before == opener * n and after == closer * n

        def remove(n: int) -> None:
            self.replace("", (er, ec), (er, ec + n * len(closer)))
            self.replace("", (sr, sc - n * len(opener)), (sr, sc))
            new_ec = ec - n * len(opener) if er == sr else ec
            self.selection = Selection((sr, sc - n * len(opener)), (er, new_ec))

        def add() -> None:
            self.insert(closer, (er, ec))           # end first so start stays valid
            self.insert(opener, (sr, sc))
            new_ec = ec + len(opener) if er == sr else ec
            self.selection = Selection((sr, sc + len(opener)), (er, new_ec))

        if doublable and wrapped(2):
            remove(2)          # bold -> plain
        elif wrapped(1):
            add() if doublable else remove(1)  # italic -> bold, or pair -> plain
        else:
            add()              # plain -> wrapped

    def _selected_rows(self) -> tuple[int, int]:
        (r0, _), (r1, _) = self.selection
        return (min(r0, r1), max(r0, r1))

    def _reindent(self, r0: int, r1: int, dedent: bool) -> None:
        width = self.indent_width
        for row in range(r0, r1 + 1):
            line = self.document.get_line(row)
            if dedent:
                n = 0
                while n < width and n < len(line) and line[n] == " ":
                    n += 1
                if n:
                    self.replace("", (row, 0), (row, n))
            elif line:  # do not indent genuinely empty lines
                self.insert(" " * width, (row, 0))
        # keep the whole block selected
        self.selection = Selection((r0, 0), (r1, len(self.document.get_line(r1))))


class SdfCommands(SystemCommandsProvider):
    """Command palette provider ordered logically instead of alphabetically."""

    # (title prefix, rank); lower = higher in the list, Quit last.
    ORDER = [("Insert markdown", -1), ("Theme", 0), ("Transparency", 1), ("Scroll sync", 2),
             ("Toggle comment", 4), ("Keys", 5), ("Quit", 99)]

    @classmethod
    def rank(cls, title: str) -> int:
        for prefix, rank in cls.ORDER:
            if title.startswith(prefix):
                return rank
        return 50

    async def discover(self) -> Hits:
        commands = sorted(self.app.get_system_commands(self.screen),
                          key=lambda command: (self.rank(command[0]), command[0]))
        for name, help_text, callback, discover in commands:
            if discover:
                yield DiscoveryHit(name, callback, help=help_text)


try:
    import tree_sitter_language_pack as _tslp  # 300+ grammars, offline
except Exception:  # pragma: no cover - optional heavy dependency
    _tslp = None

try:
    import pypdf as _pypdf  # pure-Python PDF text extraction (pip, no system dep)
except Exception:  # pragma: no cover
    _pypdf = None

MARKDOWN_EXTS = {".md", ".markdown", ".mdown", ".mkd", ".mdwn"}

# Markdown snippets for the "Insert markdown tag" palette command. The value is the
# text inserted at the cursor; "@link" / "@image" first open a file picker and the
# chosen path is written relative to the markdown file.
MARKDOWN_TAGS = [
    ("Unordered List", "- item"),
    ("Ordered List", "1. item"),
    ("Link", "@link"),
    ("Image", "@image"),
    ("Horizontal Rule", "\n---\n"),
    ("Table", "| Column 1 | Column 2 |\n| --- | --- |\n| a | b |\n"),
    ("Task List", "- [ ] task"),
    ("Heading", "# Heading"),
    ("Bold", "**bold**"),
    ("Italic", "*italic*"),
    ("Inline Code", "`code`"),
    ("Code Block", "```\n\n```"),
    ("Blockquote", "> quote"),
    ("Footnote", "[^1]\n\n[^1]: note"),
]
_MD_TAG_MAP = dict(MARKDOWN_TAGS)
# One-line syntax preview shown next to each tag (we have the room).
_MD_TAG_PREVIEW = {
    "Unordered List": "- item",
    "Ordered List": "1. item",
    "Link": "[text](url)",
    "Image": "![alt](url)",
    "Horizontal Rule": "---",
    "Table": "| a | b |",
    "Task List": "- [ ] task",
    "Heading": "# Heading",
    "Bold": "**bold**",
    "Italic": "*italic*",
    "Inline Code": "`code`",
    "Code Block": "```lang```",
    "Blockquote": "> quote",
    "Footnote": "[^1]",
}


def _soft_as_hard(md: MarkdownIt) -> None:
    """Turn every soft line break into a hard one. Textual renders tokens (not
    HTML), so the parser's `breaks` option is ignored; converting softbreak tokens
    to hardbreak makes a single newline in the editor a real line break in the
    preview, without needing two trailing spaces."""
    def rule(state) -> None:
        for token in state.tokens:
            if token.type == "inline" and token.children:
                for child in token.children:
                    if child.type == "softbreak":
                        child.type = "hardbreak"
                        child.tag = "br"
    md.core.ruler.push("soft_as_hard", rule)


def _md_parser() -> MarkdownIt:
    return MarkdownIt("gfm-like").use(_soft_as_hard)

# Prettier task-list checkboxes in the preview (the editor keeps raw `- [ ]`).
# A list block that contains a task is rewritten as one line per item with the
# checkbox replacing the bullet (✔ / ☐), and a plain bullet (•) for its non-task
# siblings, so there is no redundant dot in front of the box.
_LIST_ITEM = re.compile(r"^(\s*)[-*+]\s+(\[[ xX]\]\s+)?(\S.*)$")


def _prettify_tasks(text: str) -> str:
    lines = text.split("\n")
    out: list[str] = []
    i, n, in_fence = 0, len(lines), False
    while i < n:
        stripped = lines[i].lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            out.append(lines[i]); i += 1; continue
        if in_fence:
            out.append(lines[i]); i += 1; continue
        block = []
        j = i
        while j < n and (m := _LIST_ITEM.match(lines[j])):
            block.append(m); j += 1
        if block and any(m.group(2) for m in block):  # at least one checkbox
            for m in block:
                indent, checkbox, content = m.group(1), m.group(2), m.group(3)
                mark = "•" if not checkbox else ("✔" if checkbox.strip()[1] in "xX" else "☐")
                out.append(f"{' ' * len(indent)}{mark} {content}  ")  # 2 spaces = hard break
            i = j
        else:
            out.append(lines[i]); i += 1
    return "\n".join(out)


class FlatTree(DirectoryTree):
    """DirectoryTree with flat icons, folder-entering navigation and file ops.

    The (shown) root node is rendered as '..' and acts as 'go up': it is
    selectable with the arrows and Enter on it goes to the parent folder. Enter on
    any other folder enters it (new root) instead of unfolding it; right/left
    expand/collapse in place.
    """

    ICON_NODE = "▸ "           # small right triangle
    ICON_NODE_EXPANDED = "▾ "  # small down triangle
    ICON_FILE = "  "               # no emoji, aligns under the folder triangles

    show_hidden = False  # dotfiles hidden by default (Ctrl+H toggles)

    BINDINGS = [
        Binding("enter", "go_or_open", "Open", priority=True),
        Binding("right", "expand_cursor", "Expand"),
        Binding("left", "collapse_cursor", "Collapse"),
        Binding("delete", "app.tree_go_up", "Up"),
        Binding("ctrl+h", "toggle_hidden", "Hidden"),
        Binding("escape", "app.close_tree", "Close"),
        Binding("n", "app.tree_new_file", "New file"),
        Binding("d", "app.tree_new_dir", "New dir"),
        Binding("r", "app.tree_rename", "Rename"),
        Binding("i", "app.tree_info", "Info"),
    ]

    def filter_paths(self, paths):
        if self.show_hidden:
            return list(paths)
        return [p for p in paths if not p.name.startswith(".")]

    def action_toggle_hidden(self) -> None:
        self.show_hidden = not self.show_hidden
        self.reload()
        self.app._persist_show_hidden(self.show_hidden)
        self.app.notify(f"Hidden files: {'shown' if self.show_hidden else 'hidden'}", timeout=1.5)

    def render_label(self, node, base_style, style):  # noqa: ANN001
        if node.parent is None:  # visible root repurposed as ".." (go up)
            return Text("..", style=style)
        return super().render_label(node, base_style, style)

    def action_go_or_open(self) -> None:
        node = self.cursor_node
        if node is None:
            return
        if node.parent is None:              # ".." -> go up
            self.app.action_tree_go_up()
            return
        if node.data is None:
            return
        path = Path(node.data.path)
        if path.is_dir():
            self.app.action_tree_go_here()   # enter the folder (new root)
        else:
            self.app._open_from_tree(path)    # open the file

    def action_expand_cursor(self) -> None:
        # Right: expand a collapsed folder, or step into an already-open one.
        node = self.cursor_node
        if node is None or not node.allow_expand:
            return
        if node.is_expanded:
            self.action_cursor_down()
        else:
            node.expand()

    def action_collapse_cursor(self) -> None:
        # Left: collapse an open folder, otherwise jump up to the parent folder
        # (so left works even on a file, which has nothing to collapse).
        node = self.cursor_node
        if node is not None and node.allow_expand and node.is_expanded:
            node.collapse()
        else:
            self.action_cursor_parent()


class PromptScreen(ModalScreen[str]):
    """Single-line text prompt (new file/dir name, rename)."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, prompt: str, value: str = "") -> None:
        super().__init__()
        self._prompt = prompt
        self._value = value

    def compose(self) -> ComposeResult:
        with Container(id="dialog"):
            yield Label(self._prompt, classes="dtitle")
            yield Input(value=self._value, id="prompt-input")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip())

    def action_cancel(self) -> None:
        self.dismiss("")


def _human_size(n: int) -> str:
    """Human-readable byte count (B, KB, MB, ...)."""
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _file_info_lines(path: Path):
    """Build (is_dir, [(label, value), ...]) about a file or folder for InfoScreen."""
    rows = [("Name", path.name or str(path)), ("Path", str(path))]
    try:
        st = path.stat()
    except OSError as exc:
        rows.append(("Error", str(exc)))
        return path.is_dir(), rows
    is_dir = path.is_dir()
    if is_dir:
        rows.append(("Type", "Folder"))
        try:
            rows.append(("Items", str(sum(1 for _ in path.iterdir()))))
        except OSError:
            pass
    else:
        suffix = path.suffix.lower()
        lang = EXT_LANG.get(suffix) or NAME_LANG.get(path.name)
        rows.append(("Type", f"File ({lang})" if lang else "File"))
        rows.append(("Size", _human_size(st.st_size)))
        if 0 < st.st_size <= 5_000_000:      # count lines for reasonably-sized text files
            try:
                text = path.read_bytes().decode("utf-8", errors="strict")
                rows.append(("Lines", str(text.count("\n") + (0 if text.endswith("\n") or not text else 1))))
            except (OSError, UnicodeDecodeError):
                rows.append(("Lines", "binary"))
    rows.append(("Modified", datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")))
    rows.append(("Perms", f"{stat_mod.filemode(st.st_mode)}  ({oct(st.st_mode & 0o777)[2:]})"))
    return is_dir, rows


class InfoScreen(ModalScreen[None]):
    """Read-only popup with details about the selected file or folder."""

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("i", "close", "Close"),
        Binding("enter", "close", "Close"),
    ]

    def __init__(self, path: Path) -> None:
        super().__init__()
        self._path = path

    def compose(self) -> ComposeResult:
        is_dir, rows = _file_info_lines(self._path)
        width = max((len(label) for label, _ in rows), default=0)
        body = "\n".join(
            f"[b]{(label + ':').ljust(width + 1)}[/b]  {escape(str(value))}" for label, value in rows
        )
        dialog = Container(id="dialog")
        dialog.border_title = "Folder info" if is_dir else "File info"
        with dialog:
            yield Static(body, classes="info")
            yield Label("[b]Esc[/b] close", classes="dhint")

    def action_close(self) -> None:
        self.dismiss(None)


class MarkdownTagScreen(ModalScreen[str]):
    """Pick a markdown snippet to insert (list, link, image, table, ...)."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        dialog = Container(id="dialog")
        dialog.border_title = "Insert markdown tag"
        items = []
        for i, (label, _) in enumerate(MARKDOWN_TAGS):
            preview = escape(_MD_TAG_PREVIEW.get(label, ""))
            items.append(ListItem(Label(f"{label.ljust(16)}[dim]{preview}[/dim]"), id=f"mdtag-{i}"))
        with dialog:
            yield Static("...", id="tag-more-top")
            yield ListView(*items, id="tag-list")
            yield Static("...", id="tag-more-bottom")
            yield Label("[b]Enter[/b] insert     [b]Esc[/b] cancel", classes="dhint")

    def on_mount(self) -> None:
        lv = self.query_one(ListView)
        lv.focus()
        self.watch(lv, "scroll_y", self._update_scroll_hint, init=False)
        self.call_after_refresh(self._update_scroll_hint)

    def _update_scroll_hint(self, *_) -> None:
        """Replace the side scrollbar with '...' at the top/bottom to show more rows."""
        lv = self.query_one(ListView)
        self.query_one("#tag-more-top").display = lv.scroll_y > 0.5
        self.query_one("#tag-more-bottom").display = lv.scroll_y < lv.max_scroll_y - 0.5

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        idx = event.list_view.index
        if idx is not None:
            self.dismiss(MARKDOWN_TAGS[idx][0])

    def action_cancel(self) -> None:
        self.dismiss("")


class FilePickScreen(ModalScreen[Path]):
    """Modal file browser: navigate and pick a file (for a link/image path)."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("backspace", "go_up", "Up"),
        Binding("delete", "go_up", "Up"),
    ]

    def __init__(self, start_dir: Path) -> None:
        super().__init__()
        self._start = start_dir if start_dir.is_dir() else start_dir.parent

    def compose(self) -> ComposeResult:
        dialog = Container(id="dialog")
        dialog.border_title = "Pick a file"
        with dialog:
            yield Label("Enter open/select, Backspace up, Esc cancel", classes="dhint")
            yield DirectoryTree(str(self._start), id="pick-tree")

    def on_mount(self) -> None:
        self.query_one(DirectoryTree).focus()

    def action_go_up(self) -> None:
        tree = self.query_one(DirectoryTree)
        parent = Path(tree.path).parent
        if parent != Path(tree.path):
            tree.path = str(parent)

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        self.dismiss(Path(event.path))

    def action_cancel(self) -> None:
        self.dismiss(None)


class SearchNav(Static, can_focus=True):
    """Search-status line that holds focus during navigation so n / p / Esc work
    (bare letters would otherwise just type in the editor)."""

    BINDINGS = [
        Binding("n", "app.search_next", "Next", show=False),
        Binding("p", "app.search_prev", "Prev", show=False),
        Binding("escape", "app.search_close", "Close", show=False),
    ]


# Editor / preview width ratios, cycled Splitmark-style.
RATIOS = [(3, 1), (1, 1), (1, 3)]
RATIO_LABELS = ["75/25", "50/50", "25/75"]
# split, full editor, full viewer, then maximized (no header/hints) variants.
VIEW_MODES = ["split", "editor", "max-editor", "preview", "max-preview"]
# Split rotations (Ctrl+B): (layout orientation, editor placed last). Cycles the
# split a quarter turn each press: editor left -> top -> right -> bottom.
ROTATIONS = [("horizontal", False), ("vertical", False),
             ("horizontal", True), ("vertical", True)]
ROTATION_LABELS = ["left", "top", "right", "bottom"]  # where the editor sits

# Shortcut hint boxes (rendered with console markup).
# Split so the preview-only shortcuts (view/rotate/ratio) can be dropped for files
# with no preview (anything other than markdown or PDF).
_HINTS_HEAD = ("[b]^s[/b] Save  [b]^c/^v/^x[/b] Copy/Paste/Cut  [b]^k[/b] Del-line  "
               "[b]^r[/b] Search  [b]^e[/b] Files  [b]^g[/b] Focus  ")
_HINTS_PREVIEW = "[b]^f[/b] View  [b]^b[/b] Rotate  [b]^w[/b] Width  "
_HINTS_TAIL = "[b]^o[/b] Mode  [b]^p[/b] Palette  [b]^q[/b] Quit"
GENERAL_HINTS = _HINTS_HEAD + _HINTS_PREVIEW + _HINTS_TAIL
GENERAL_HINTS_NO_PREVIEW = _HINTS_HEAD + _HINTS_TAIL
BROWSER_HINTS = ("[b]Enter[/b] Open  [b]->/<-[/b] Expand  [b]Del[/b] Up  [b]^h[/b] Hidden  "
                 "[b]n[/b] New  [b]d[/b] Dir  [b]r[/b] Rename  [b]i[/b] Info  [b]Esc[/b] Close")

# File extension -> tree-sitter language name (built-in Textual set + language pack).
EXT_LANG = {
    ".md": "markdown", ".markdown": "markdown", ".txt": "markdown",
    ".py": "python", ".pyi": "python", ".pyw": "python",
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript", ".jsx": "javascript",
    ".ts": "typescript", ".mts": "typescript", ".tsx": "tsx",
    ".json": "json", ".jsonc": "json", ".geojson": "json",
    ".yaml": "yaml", ".yml": "yaml", ".toml": "toml", ".ini": "ini", ".cfg": "ini", ".conf": "ini",
    ".xml": "xml", ".svg": "xml", ".html": "html", ".htm": "html", ".xhtml": "html",
    ".css": "css", ".scss": "scss", ".sass": "scss", ".less": "css",
    ".sh": "bash", ".bash": "bash", ".zsh": "bash", ".fish": "fish", ".env": "bash",
    ".c": "c", ".h": "c", ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".hh": "cpp",
    ".cs": "csharp", ".java": "java", ".kt": "kotlin", ".kts": "kotlin", ".scala": "scala",
    ".go": "go", ".rs": "rust", ".rb": "ruby", ".php": "php", ".pl": "perl", ".pm": "perl",
    ".lua": "lua", ".swift": "swift", ".dart": "dart", ".r": "r", ".jl": "julia",
    ".hs": "haskell", ".ml": "ocaml", ".mli": "ocaml", ".ex": "elixir", ".exs": "elixir",
    ".erl": "erlang", ".clj": "clojure", ".cljs": "clojure", ".sql": "sql",
    ".vim": "vim", ".nix": "nix", ".zig": "zig", ".proto": "proto",
    ".graphql": "graphql", ".gql": "graphql", ".tf": "hcl", ".hcl": "hcl",
    ".vue": "vue", ".svelte": "svelte", ".tex": "latex", ".cmake": "cmake",
    ".gradle": "groovy", ".groovy": "groovy", ".ps1": "powershell",
    ".f": "fortran", ".f90": "fortran", ".nim": "nim", ".cr": "crystal",
    ".scm": "scheme", ".rst": "rst", ".diff": "diff", ".patch": "diff", ".dockerfile": "dockerfile",
}
NAME_LANG = {"Dockerfile": "dockerfile", "Makefile": "make", "makefile": "make", "CMakeLists.txt": "cmake"}
POLL_INTERVAL = 0.5        # seconds, disk-change polling
PREVIEW_DEBOUNCE = 0.15    # seconds before re-rendering the preview
DEFAULT_THEME = "gruvbox"


class ConflictScreen(ModalScreen[str]):
    """External change while the local buffer is dirty: ask the human."""

    BINDINGS = [
        Binding("r", "choose('reload')", "Reload"),
        Binding("k", "choose('keep')", "Keep buffer"),
        Binding("escape", "choose('keep')", "Cancel"),
    ]

    def __init__(self, filename: str) -> None:
        super().__init__()
        self._filename = filename

    def compose(self) -> ComposeResult:
        with Container(id="dialog"):
            yield Label(f"{self._filename} changed on disk", classes="dtitle")
            yield Label("You have unsaved changes in this buffer.")
            yield Label("[b]R[/b] reload disk (drop my edits)     "
                        "[b]K[/b] keep my buffer (ignore disk)", classes="dhint")

    def action_choose(self, value: str) -> None:
        self.dismiss(value)


class UnsavedScreen(ModalScreen[str]):
    """Opening another file while the current buffer is dirty."""

    BINDINGS = [
        Binding("s", "choose('save')", "Save & open"),
        Binding("o", "choose('discard')", "Open anyway"),
        Binding("c", "choose('cancel')", "Cancel"),
        Binding("escape", "choose('cancel')", "Cancel"),
    ]

    def __init__(self, filename: str) -> None:
        super().__init__()
        self._filename = filename

    def compose(self) -> ComposeResult:
        with Container(id="dialog"):
            yield Label(f"Unsaved changes in {self._filename}", classes="dtitle")
            yield Label("[b]S[/b] save & open     [b]O[/b] open without saving     "
                        "[b]C[/b] cancel", classes="dhint")

    def action_choose(self, value: str) -> None:
        self.dismiss(value)


class SdfApp(App):
    """Main application."""

    COMMANDS = {SdfCommands}  # logically-ordered command palette (not alphabetical)

    CSS = """
    Screen { background: $surface; }

    #body { height: 1fr; }

    /* File browser: a bordered panel like the editor/preview (no double line). */
    #sidebar {
        width: 32;
        border: round $primary;
        border-title-color: $success;
        border-title-style: bold;
        margin-right: 1;
        background: $surface;
        display: none;
    }
    #sidebar:focus-within {
        border: round $accent;
        border-title-color: $accent;
    }
    /* Hide all scrollbars (still scrollable with keys/wheel). */
    #tree, #editor, #preview { scrollbar-size: 0 0; }
    #tree {
        height: 1fr;
        padding: 0 1;
        background: $surface;
    }
    #tree > .directory-tree--folder { text-style: bold; }
    #tree > .tree--guides { color: $primary-darken-3; }
    #tree > .tree--guides-hover { color: $primary-darken-2; }

    #panes { width: 1fr; height: 1fr; }

    /* Splitmark-style bordered panes with titles. */
    #editor {
        width: 3fr; height: 1fr;
        border: round $primary;
        border-title-color: $success;
        border-title-style: bold;
        border-subtitle-color: $text-muted;
        padding: 0 1;
        background: $surface;
    }
    #editor:focus, #editor:focus-within {
        border: round $accent;
    }

    #preview {
        width: 1fr; height: 1fr;
        margin-left: 1;
        border: round $primary;
        border-title-color: $accent;
        border-title-style: bold;
        padding: 0 1;
        background: $surface;
    }
    /* Focused pane gets a bright accent outline (like the editor). */
    #preview:focus, #preview:focus-within {
        border: round $accent;
    }
    #preview-md { height: auto; background: $surface; }

    /* Polished markdown preview (native, no external tool). A terminal has a fixed
       font size, so heading "sizes" are conveyed by weight / colour / decoration. */
    #preview-md MarkdownH1 {
        color: $accent; background: $accent 15%; text-style: bold;
        border: none; border-bottom: heavy $accent;
        padding: 1 1 0 1; margin: 1 0;
    }
    #preview-md MarkdownH2 {
        color: $accent; text-style: bold;
        border: none; border-bottom: solid $accent-darken-1; margin: 1 0 0 0;
    }
    #preview-md MarkdownH3 { color: $success; text-style: bold underline; margin: 1 0 0 0; }
    #preview-md MarkdownH4 { color: $secondary; text-style: bold; margin: 1 0 0 0; }
    #preview-md MarkdownH5 { color: $text-muted; text-style: bold; }
    #preview-md MarkdownH6 { color: $text-muted; text-style: italic; }
    #preview-md MarkdownBlockQuote {
        background: $panel; border-left: thick $accent;
        padding: 0 1; margin: 1 0;
    }
    #preview-md MarkdownFence {
        background: $boost; border: round $primary-darken-2;
        border-title-color: $accent; border-title-align: right;
        margin: 1 0;
    }
    #preview-md MarkdownHorizontalRule { border-bottom: heavy $primary-darken-1; }
    #preview-md MarkdownBullet { color: $accent; }
    #preview-md MarkdownOrderedListItem { color: $accent; }
    #preview-md MarkdownTH { text-style: bold; color: $accent; }

    /* Shortcut hint boxes (bordered like the panes): general + browser. */
    #hints { height: 3; }
    #hints-general, #hints-files {
        height: 3;
        border: round $primary-darken-1;
        border-title-style: bold;
        padding: 0 1;
        color: $text-muted;
        background: $surface;
        text-wrap: nowrap;         /* keep the hints on a single line ... */
        text-overflow: ellipsis;   /* ... and trail off with an ellipsis when too narrow */
    }
    #hints-general { width: 1fr; border-title-color: $accent; }
    #hints-files {
        width: 1fr;
        margin-left: 1;
        border-title-color: $success;
        display: none;
    }
    /* Search bar: takes the place of the Keys box (bottom-left) while searching. */
    #search-box {
        width: 1fr;
        height: 3;
        border: round $accent;
        border-title-style: bold;
        border-title-color: $accent;
        padding: 0 1;
        background: $surface;
        display: none;
    }
    #search-input {
        height: 1;
        border: none;
        padding: 0;
        background: transparent;
    }
    #search-status { height: 1; color: $text-muted; }

    /* Remove the clickable header icon; the command palette stays on ctrl+p. */
    HeaderIcon { display: none; }

    /* Per-region transparency (id/type + class beats the base background rule). */
    #editor.transparent,
    #preview.transparent,
    #preview-md.transparent,
    #sidebar.transparent,
    #tree.transparent,
    #hints-general.transparent,
    #hints-files.transparent,
    Header.transparent,
    Screen.transparent { background: transparent; }

    /* Command palette: no search bar (few commands), just a bordered list. The
       hidden input keeps focus so arrow/enter navigation still works. */
    CommandPalette > #--container {
        margin-top: 4;
        width: 84;
        max-width: 90%;
    }
    CommandPalette #--input { display: none; }
    CommandList {
        border: round $accent;
        background: $surface;
    }

    /* Modal dialogs: always centered, with a dimmed backdrop behind. */
    PromptScreen, InfoScreen, ConflictScreen, UnsavedScreen,
    MarkdownTagScreen, FilePickScreen {
        align: center middle;
        background: $background 55%;
    }

    #dialog {
        width: auto;
        min-width: 56;
        max-width: 80%;
        height: auto;
        padding: 1 3;
        border: round $accent;
        border-title-color: $accent;
        border-title-style: bold;
        background: $surface;
    }

    #dialog > Label {
        width: 100%;
        text-align: center;
        margin-bottom: 1;
    }

    #dialog > .dtitle {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }

    #dialog > .dhint {
        width: 100%;
        text-align: center;
        margin-top: 1;
        margin-bottom: 0;
        color: $text-muted;
    }
    #dialog > .info {
        width: 100%;
        text-align: left;
        color: $text;
        margin-bottom: 0;
    }
    #dialog Input {
        margin-top: 1;
        border: round $primary;
    }
    #dialog Input:focus { border: round $accent; }

    /* Markdown-tag picker + modal file browser. */
    #tag-list {
        height: auto;
        max-height: 12;
        border: round $primary;
        background: $surface;
        scrollbar-size: 0 0;      /* no side slider; '...' shows there is more */
    }
    #tag-list:focus { border: round $accent; }
    #tag-list > ListItem { padding: 0 1; }
    #tag-more-top, #tag-more-bottom {
        width: 100%;
        height: 1;
        text-align: center;
        color: $text-muted;
    }
    #pick-tree {
        height: 18;
        min-width: 60;
        border: round $primary;
        background: $surface;
        scrollbar-size: 0 0;
    }
    #pick-tree:focus { border: round $accent; }
    """

    # priority=True: these global-chrome shortcuts must win over the focused
    # widget's bindings (otherwise TextArea swallows ctrl+w -> delete_word_left
    # and ctrl+e -> cursor_line_end). ctrl+p is deliberately left unbound so it
    # opens Textual's command palette. Grouped: file, panels, layout, behavior.
    BINDINGS = [
        # File
        Binding("ctrl+s", "save", "Save", priority=True),
        Binding("ctrl+q", "quit", "Quit", priority=True),
        Binding("ctrl+c", "request_quit", "Quit", priority=True, show=False),
        Binding("ctrl+shift+c", "copy_selection", "Copy", priority=True, show=False),
        Binding("ctrl+shift+v", "paste_clipboard", "Paste", priority=True, show=False),
        # Panels
        Binding("ctrl+e", "toggle_tree", "Files", priority=True),
        # Ctrl+Tab is indistinguishable from Tab in a terminal, so use Ctrl+G / F6.
        Binding("ctrl+g", "cycle_focus", "Focus", priority=True),
        Binding("f6", "cycle_focus", "Focus", priority=True, show=False),
        Binding("escape", "focus_editor", "Editor", show=False),
        # Search (vim-like: type, then n / p / Esc). Ctrl+F is the view cycle, so
        # search is Ctrl+R (as in Recherche). n / p navigation is handled by the
        # focused search-status widget, so bare letters still type in the editor.
        Binding("ctrl+r", "search", "Search", priority=True),
        # Layout / appearance
        Binding("ctrl+f", "cycle_view", "View", priority=True),
        Binding("ctrl+b", "rotate", "Rotate", priority=True),
        Binding("ctrl+w", "cycle_ratio", "Width", priority=True),
        # Behavior
        Binding("ctrl+o", "toggle_conflict_mode", "Mode", priority=True),
        # (transparency lives in the command palette, ctrl+p)
    ]

    def __init__(self, path: str | None = None, conflict_mode: str | None = None,
                 theme: str | None = None, transparent: bool | None = None) -> None:
        super().__init__()
        self._config = Config.load()
        self._config_loaded = False
        self._cli_theme = theme
        self._path: Path | None = Path(path).expanduser().resolve() if path else None
        # CLI overrides win for the session; otherwise fall back to persisted config.
        self.conflict_mode = conflict_mode if conflict_mode in ("auto", "prompt") \
            else self._config.get("conflict_mode")
        self._transparent = transparent if transparent is not None \
            else bool(self._config.get("transparent"))
        self._rotation = int(self._config.get("rotation")) % len(ROTATIONS)
        self._ratio_idx = int(self._config.get("ratio_idx")) % len(RATIOS)
        self._scroll_sync = bool(self._config.get("scroll_sync"))
        self._syncing = False  # guard against editor<->preview scroll feedback
        self._view_mode = "split"  # transient, not persisted
        self._preview_kind = "markdown"  # "markdown" | "pdf" | None (no preview)
        self._pdf_text = ""
        # Disk sync baseline.
        self._saved_text = ""
        self._last_disk_sig: tuple | None = None
        self._ignored_disk_text: str | None = None
        # Misc runtime state.
        self._conflict_open = False
        self._preview_timer = None
        self._ui_ready = False  # ignore tree events until the mount completes
        self._quit_armed = False  # double ctrl+c to quit
        # Search state (vim-like: type, then n / p / Esc).
        self._search_active = False   # search bar shown (replaces the Keys box)
        self._search_nav = False      # confirmed: n / p navigate matches
        self._search_query = ""
        self._search_offsets: list[int] = []   # char offsets of each match
        self._search_idx = -1
        self._registered_langs: set[str] = set()  # tree-sitter languages already registered

    # ------------------------------------------------------------------ UI
    def _tree_root(self) -> str:
        """Nearest existing directory (the tree misbehaves on a missing dir)."""
        base = self._path.parent if self._path else Path.cwd()
        while not base.exists() and base != base.parent:
            base = base.parent
        return str(base) if base.exists() else "."

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal(id="body"):
            with Vertical(id="sidebar"):
                yield FlatTree(self._tree_root(), id="tree")
            with Container(id="panes"):
                yield CodeEditor("", id="editor", soft_wrap=True,
                                 tab_behavior="indent", show_line_numbers=True)
                with VerticalScroll(id="preview"):
                    yield Markdown("", id="preview-md", parser_factory=_md_parser)
        with Horizontal(id="hints"):
            yield Static(GENERAL_HINTS, id="hints-general")
            with Container(id="search-box"):
                yield Input(placeholder="type to search, Enter to browse", id="search-input")
                yield SearchNav("", id="search-status")
            yield Static(BROWSER_HINTS, id="hints-files")

    def on_mount(self) -> None:
        self.editor = self.query_one("#editor", CodeEditor)
        self.preview = self.query_one("#preview-md", Markdown)
        self.preview_scroll = self.query_one("#preview", VerticalScroll)
        self.preview_scroll.can_focus = True   # so focus can cycle into the preview
        self.filetree = self.query_one("#tree", FlatTree)
        self.filetree.show_root = True   # the root node is our selectable ".."
        self.filetree.guide_depth = 2
        self.filetree.show_hidden = bool(self._config.get("show_hidden"))
        if self.filetree.show_hidden:
            self.filetree.reload()
        self.sidebar = self.query_one("#sidebar", Vertical)
        self.sidebar.border_title = f"Files: {Path(self._tree_root()).name or '/'}"
        self.panes = self.query_one("#panes", Container)
        self._header = self.query_one(Header)
        self._hints = self.query_one("#hints", Horizontal)
        self._hints_general = self.query_one("#hints-general", Static)
        self._hints_files = self.query_one("#hints-files", Static)
        self._hints_general.border_title = "Keys"
        self._hints_files.border_title = "Browser"
        self._search_box = self.query_one("#search-box", Container)
        self._search_input = self.query_one("#search-input", Input)
        self._search_status = self.query_one("#search-status", SearchNav)
        self._search_box.border_title = "Search"
        self._base_screen = self.screen
        # Theme: CLI override, else config, else the gruvbox default.
        theme = self._cli_theme if self._cli_theme in self.available_themes \
            else self._config.get("theme")
        self.theme = theme if theme in self.available_themes else DEFAULT_THEME
        # Syntax colors that keep the editor's own (gruvbox) background: reuse
        # monokai's token colors but no base style, so the CSS bg shows through.
        self.editor.register_theme(
            TextAreaTheme(name="sdf",
                          syntax_styles=TextAreaTheme.get_builtin_theme("monokai").syntax_styles))
        self.editor.theme = "sdf"
        self.preview_scroll.border_title = "Preview"
        self._load_file(self._path, initial=True)
        self._apply_layout()
        self._apply_transparency()
        self.set_interval(POLL_INTERVAL, self._check_file)
        self.editor.focus()
        self.watch(self, "theme", self._on_theme_change, init=False)
        # bidirectional scroll sync (guarded against feedback)
        self.watch(self.editor, "scroll_y", self._sync_from_editor, init=False)
        self.watch(self.preview_scroll, "scroll_y", self._sync_from_preview, init=False)
        self._config_loaded = True
        self._ui_ready = True

    def _sync_scroll(self, src, dst) -> None:
        if not self._scroll_sync or self._syncing or self._preview_kind is None:
            return
        self._syncing = True
        frac = (src.scroll_y / src.max_scroll_y) if src.max_scroll_y > 0 else 0.0
        dst.scroll_to(y=frac * dst.max_scroll_y, animate=False)
        self.call_after_refresh(self._clear_syncing)

    def _clear_syncing(self) -> None:
        self._syncing = False

    def _sync_from_editor(self, *_) -> None:
        self._sync_scroll(self.editor, self.preview_scroll)

    def _sync_from_preview(self, *_) -> None:
        self._sync_scroll(self.preview_scroll, self.editor)

    def get_system_commands(self, screen: Screen):
        """Palette commands: drop Screenshot and Maximize/Minimize (the View cycle
        Ctrl+F already maximizes the editor or the preview); add Transparency."""
        for command in super().get_system_commands(screen):
            if command.title in ("Screenshot", "Maximize", "Minimize"):
                continue
            yield command
        yield SystemCommand("Transparency", "Toggle terminal transparency on/off",
                            self.action_toggle_transparency)
        sync = "on" if self._scroll_sync else "off"
        yield SystemCommand(f"Scroll sync ({sync})",
                            "Toggle synced scrolling between editor and preview",
                            self.action_toggle_scroll_sync)
        yield SystemCommand("Toggle comment", "Comment / uncomment the selected lines (Ctrl+/)",
                            self.editor.action_toggle_comment)
        if self._preview_kind == "markdown" and not self.editor.read_only:
            yield SystemCommand("Insert markdown tag",
                                "Insert a markdown snippet: list, link, image, table, ...",
                                self.action_markdown_tag)

    def format_title(self, title: str, sub_title: str) -> Content:
        """Header title joined with spaces instead of the default em dash."""
        if sub_title:
            return Content.assemble(Content(title), ("    ", ""),
                                    Content(sub_title).stylize("dim"))
        return Content(title)

    # -------------------------------------------------------------- settings
    def _persist(self) -> None:
        if not self._config_loaded:
            return
        self._config.update(
            theme=self.theme,
            conflict_mode=self.conflict_mode,
            transparent=self._transparent,
            rotation=self._rotation,
            ratio_idx=self._ratio_idx,
            scroll_sync=self._scroll_sync,
            show_hidden=self.filetree.show_hidden,
        )
        self._config.save()

    def _persist_show_hidden(self, _value: bool) -> None:
        self._persist()

    def _on_theme_change(self, _theme: str) -> None:
        self._persist()

    # -------------------------------------------------------------- helpers
    @property
    def _dirty(self) -> bool:
        return self.editor.text != self._saved_text

    def _refresh_status(self) -> None:
        name = self._path.name if self._path else "untitled"
        flag = " *" if self._dirty else ""
        self.title = "SDF"
        self.sub_title = f"{name}{flag}    {self.conflict_mode}"
        self._refresh_titles()

    def _refresh_titles(self) -> None:
        """Splitmark-style pane titles: 'Editor: <path>' and a bottom-right
        '[<editor side>] [ratio]' indicator on the editor border."""
        location = escape(str(self._path) if self._path else "untitled")
        self.editor.border_title = f"Editor: {location}"
        layout = ROTATION_LABELS[self._rotation % len(ROTATIONS)]
        ratio = RATIO_LABELS[self._ratio_idx % len(RATIOS)]
        # escape() keeps the brackets literal (Textual titles parse console markup).
        self.editor.border_subtitle = escape(f"[{layout}]  [{ratio}]")

    def _read_disk(self) -> str | None:
        if not self._path or not self._path.exists():
            return None
        try:
            # decode(errors="replace"): non-UTF8 content (latin-1 file, binary, or a
            # partial "torn read" while a third party is writing) must never surface
            # UnicodeDecodeError (a ValueError subclass, not caught by OSError) and
            # crash the app or the watch timer.
            return self._path.read_bytes().decode("utf-8", errors="replace")
        except OSError:
            return None

    def _current_sig(self) -> tuple | None:
        """Change signature: (mtime_ns, size). More robust than mtime alone
        (coarse-granularity filesystems like FAT/USB/network, or tools that
        preserve/restore mtime such as cp -p / rsync --times)."""
        try:
            if not (self._path and self._path.exists()):
                return None
            st = self._path.stat()
            return (st.st_mtime_ns, st.st_size)
        except OSError:
            return None

    def _load_file(self, path: Path | None, initial: bool = False) -> None:
        """Load a file into the buffer and realign the disk baseline.

        The preview is only meaningful for markdown; for a PDF it shows the
        extracted text (read-only); for anything else it is hidden and the editor
        goes full width."""
        self._path = path.expanduser().resolve() if path else None
        suffix = self._path.suffix.lower() if self._path else ""
        if suffix == ".pdf":
            self._preview_kind = "pdf"
            self._pdf_text = self._extract_pdf()
            self.editor.read_only = True
            self.editor.load_text(self._pdf_text)
        else:
            self._preview_kind = "markdown" if (suffix in MARKDOWN_EXTS or not suffix) else None
            self.editor.read_only = False
            self.editor.load_text(self._read_disk() or "")
        self.editor.language = self._detect_language()
        self._saved_text = self.editor.text
        self._last_disk_sig = self._current_sig()
        self._ignored_disk_text = None
        self._apply_layout()   # hide/show preview for this file type
        self._render_preview()
        self._refresh_status()
        if not initial and self._path:
            self.notify(f"Opened: {self._path.name}", timeout=2)

    def _extract_pdf(self) -> str:
        if _pypdf is None:
            return "# PDF preview unavailable\n\nInstall `pypdf` to extract PDF text."
        try:
            reader = _pypdf.PdfReader(str(self._path))
            pages = [(p.extract_text() or "").strip() for p in reader.pages]
            body = "\n\n".join(f"### Page {i}\n\n{t}" for i, t in enumerate(pages, 1) if t)
            return body or "*(no extractable text in this PDF)*"
        except Exception as exc:  # corrupt/encrypted PDF, etc.
            return f"# Could not read PDF\n\n{exc}"

    # --------------------------------------------------------- syntax highlight
    def _detect_language(self) -> str | None:
        """Language name for the current file (by name/extension), registering it
        from the tree-sitter language pack on demand. None disables highlighting."""
        if self._path is None:
            return self._ensure_language("markdown")
        name = NAME_LANG.get(self._path.name) or EXT_LANG.get(self._path.suffix.lower())
        return self._ensure_language(name)

    def _ensure_language(self, name: str | None) -> str | None:
        if not name:
            return None
        if name in self.editor.available_languages or name in self._registered_langs:
            return name
        if _tslp is None:
            return None
        try:
            query = _tslp.get_highlights_query(name)
            if isinstance(query, bytes):
                query = query.decode("utf-8")
            self.editor.register_language(name, _tslp.get_language(name), query)
            self._registered_langs.add(name)
            return name
        except Exception:
            return None  # unknown/incompatible language: fall back to plain text

    # ------------------------------------------------------------- preview
    def on_text_area_changed(self, _event: TextArea.Changed) -> None:
        self._refresh_status()
        if self._preview_timer is not None:
            self._preview_timer.stop()
        self._preview_timer = self.set_timer(PREVIEW_DEBOUNCE, self._render_preview)

    def _render_preview(self) -> None:
        if self._preview_kind is None:
            return  # non-markdown file: no preview
        if self._preview_kind == "pdf":
            text = self._pdf_text
        else:
            text = _prettify_tasks(self.editor.text)
        self.preview.update(text)
        # label fences once mounted (call_after_refresh can race the first paint)
        self.call_after_refresh(self._label_fences)
        self.set_timer(0.1, self._label_fences)

    def _label_fences(self) -> None:
        """Show each code block's language as a title on its box."""
        for fence in self.preview.query(MarkdownFence):
            lang = (fence.lexer or "").strip()
            fence.border_title = lang or None

    # -------------------------------------------------------- external watch
    def _check_file(self) -> None:
        if self._conflict_open or self._path is None or self.editor.read_only:
            return  # read-only (PDF): the buffer isn't the raw file, skip conflict logic
        sig = self._current_sig()
        if sig is None or sig == self._last_disk_sig:
            return
        disk_text = self._read_disk()
        if disk_text is None:
            return
        self._last_disk_sig = sig

        if disk_text == self.editor.text:
            # Already in sync (typically our own save).
            self._saved_text = disk_text
            self._ignored_disk_text = None
            self._refresh_status()
            return

        # Version the human already declined: never re-propose it (prompt) nor
        # re-adopt it (auto), regardless of the buffer's dirty state.
        if self._ignored_disk_text is not None and disk_text == self._ignored_disk_text:
            return

        if not self._dirty:
            # Clean buffer: no possible data loss.
            if self.conflict_mode == "auto":
                self._adopt_disk(disk_text, "reloaded (external change)")
            else:  # prompt: warn anyway
                self._prompt_conflict(disk_text)
            return

        # Dirty buffer: real conflict.
        self._prompt_conflict(disk_text)

    def _adopt_disk(self, disk_text: str, message: str) -> None:
        self.editor.load_text(disk_text)
        self._saved_text = disk_text
        self._ignored_disk_text = None
        self._render_preview()
        self._refresh_status()
        self.notify(message, timeout=2)

    def _prompt_conflict(self, disk_text: str) -> None:
        self._conflict_open = True
        name = self._path.name if self._path else "file"

        def resolved(choice: str | None) -> None:
            self._conflict_open = False
            if choice == "reload":
                self._adopt_disk(disk_text, "reloaded from disk")
            else:  # keep / escape
                self._ignored_disk_text = disk_text
                self.notify("Kept local buffer", timeout=2)
                self._refresh_status()

        self.push_screen(ConflictScreen(name), resolved)

    # ----------------------------------------------------------- file browser
    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        if not self._ui_ready:
            return
        self._open_from_tree(Path(event.path))

    def _open_from_tree(self, path: Path) -> None:
        if self._path is not None and path.resolve() == self._path:
            return  # already open
        self._open_path(path)

    def _open_path(self, path: Path) -> None:
        if not self._dirty:
            self._load_file(path)
            return
        name = self._path.name if self._path else "buffer"

        def resolved(choice: str | None) -> None:
            if choice == "save":
                # Only open the new file if the save actually succeeded, otherwise
                # we would drop the unsaved buffer while the write failed.
                if self.action_save():
                    self._load_file(path)
                else:
                    self.notify("Open cancelled: save failed, buffer kept",
                                severity="warning")
            elif choice == "discard":
                self._load_file(path)
            # cancel/escape: do nothing

        self.push_screen(UnsavedScreen(name), resolved)

    # ------------------------------------------------------- tree navigation
    def _set_tree_root(self, path: Path) -> None:
        self.filetree.path = str(path)
        self.sidebar.border_title = f"Files: {path.name or '/'}"
        self.notify(f"-> {path.name or path}", timeout=1.5)

    def action_tree_go_here(self) -> None:
        """Enter the selected folder: make it the tree root."""
        node = self.filetree.cursor_node
        if node is not None and node.data is not None:
            target = Path(node.data.path)
            if target.is_dir():
                self._set_tree_root(target)
                return
        self.notify("Select a folder to enter", severity="warning")

    def action_tree_go_up(self) -> None:
        """Go to the parent of the current tree root."""
        current = Path(self.filetree.path)
        if current.parent != current:
            self._set_tree_root(current.parent)

    def action_tree_info(self) -> None:
        """Popup with details about the selected node (the '..' root shows the folder)."""
        node = self.filetree.cursor_node
        if node is not None and node.parent is not None and node.data is not None:
            target = Path(node.data.path)
        else:
            target = Path(self.filetree.path)   # '..' root or nothing selected: the current folder
        self.push_screen(InfoScreen(target))

    # --------------------------------------------------- markdown snippets
    def action_markdown_tag(self) -> None:
        """Open the markdown-tag picker (palette command, markdown files only)."""
        if self._preview_kind != "markdown":
            self.notify("Markdown tags are only for markdown files", severity="warning", timeout=2)
            return
        if self.editor.read_only:
            return
        self.push_screen(MarkdownTagScreen(), self._on_markdown_tag)

    def _on_markdown_tag(self, label: str) -> None:
        if not label:
            self.editor.focus()
            return
        snippet = _MD_TAG_MAP.get(label, "")
        selection = self.editor.selected_text
        if snippet in ("@link", "@image"):
            kind = "image" if snippet == "@image" else "link"
            start = self._path.parent if self._path else Path.cwd()
            self.push_screen(FilePickScreen(start),
                             lambda p: self._insert_file_link(kind, p, selection))
            return
        self._insert_markdown(self._build_snippet(label, selection))

    def _build_snippet(self, label: str, sel: str) -> str:
        """Wrap the current selection when there is one, else the placeholder snippet."""
        if not sel:
            return _MD_TAG_MAP.get(label, "")
        lines = sel.split("\n")
        wrappers = {
            "Bold": f"**{sel}**",
            "Italic": f"*{sel}*",
            "Inline Code": f"`{sel}`",
            "Code Block": f"```\n{sel}\n```",
            "Heading": f"# {sel}",
            "Blockquote": "\n".join(f"> {ln}" for ln in lines),
            "Unordered List": "\n".join(f"- {ln}" for ln in lines),
            "Ordered List": "\n".join(f"{i + 1}. {ln}" for i, ln in enumerate(lines)),
            "Task List": "\n".join(f"- [ ] {ln}" for ln in lines),
        }
        # Link/Image handled via the file picker; others (Table, HR, Footnote) ignore the
        # selection and fall back to their default snippet.
        return wrappers.get(label, _MD_TAG_MAP.get(label, ""))

    def _insert_file_link(self, kind: str, path: Path | None, text: str = "") -> None:
        if path is None:
            self.editor.focus()
            return
        rel = self._md_relpath(path)
        label = text or ("alt" if kind == "image" else "text")
        self._insert_markdown(f"![{label}]({rel})" if kind == "image" else f"[{label}]({rel})")

    def _md_relpath(self, target: Path) -> str:
        """Path of `target` relative to the markdown file's folder (./sub, ../up)."""
        base = (self._path.parent if self._path else Path.cwd()).resolve()
        try:
            rel = os.path.relpath(target.resolve(), base)
        except ValueError:            # different drive on Windows: keep absolute
            return str(target)
        rel = rel.replace(os.sep, "/")
        if rel != ".." and not rel.startswith("../"):
            rel = "./" + rel
        return rel

    def _insert_markdown(self, text: str) -> None:
        if not text:
            return
        ed = self.editor
        ed.focus()
        sel = ed.selection
        if sel.start != sel.end:                       # replace the selection in place
            lo, hi = sorted((sel.start, sel.end))
            ed.replace(text, lo, hi)
        else:
            ed.insert(text)

    # ------------------------------------------------------- tree file ops
    def _tree_base_dir(self) -> Path:
        """Directory to create into: the selected folder, or the parent of the
        selected file, else the tree root."""
        node = self.filetree.cursor_node
        if node is not None and node.data is not None:
            p = Path(node.data.path)
            return p if p.is_dir() else p.parent
        return Path(self.filetree.path)

    def action_tree_new_file(self) -> None:
        base = self._tree_base_dir()

        def done(name: str) -> None:
            if not name:
                return
            target = base / name
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.touch(exist_ok=False)
            except OSError as exc:
                self.notify(f"Create failed: {exc}", severity="error")
                return
            self.filetree.reload()
            self.notify(f"Created {name}", timeout=2)

        self.push_screen(PromptScreen(f"New file in {base.name}/", ""), done)

    def action_tree_new_dir(self) -> None:
        base = self._tree_base_dir()

        def done(name: str) -> None:
            if not name:
                return
            try:
                (base / name).mkdir(parents=True, exist_ok=False)
            except OSError as exc:
                self.notify(f"Create failed: {exc}", severity="error")
                return
            self.filetree.reload()
            self.notify(f"Created {name}/", timeout=2)

        self.push_screen(PromptScreen(f"New folder in {base.name}/", ""), done)

    def action_tree_rename(self) -> None:
        node = self.filetree.cursor_node
        if node is None or node.data is None:
            self.notify("Select a file or folder first", severity="warning")
            return
        src = Path(node.data.path)

        def done(name: str) -> None:
            if not name or name == src.name:
                return
            dst = src.with_name(name)
            try:
                src.rename(dst)
            except OSError as exc:
                self.notify(f"Rename failed: {exc}", severity="error")
                return
            if self._path == src:  # renamed the file we have open
                self._path = dst
                self._last_disk_sig = self._current_sig()
                self._refresh_status()
            self.filetree.reload()
            self.notify(f"Renamed to {name}", timeout=2)

        self.push_screen(PromptScreen("Rename to", src.name), done)

    # -------------------------------------------------------------- actions
    def action_request_quit(self) -> None:
        """Ctrl+C copies the editor selection; with no selection, double-press quits."""
        if self.editor.has_focus and self.editor.selected_text:
            self.action_copy_selection()
            return
        if self._quit_armed:
            self.exit()
            return
        self._quit_armed = True
        self.notify("Press Ctrl+C again to quit", timeout=2)
        self.set_timer(2.0, self._disarm_quit)

    def _disarm_quit(self) -> None:
        self._quit_armed = False

    def action_copy_selection(self) -> None:
        """Copy the editor's selection to the system clipboard (OSC 52)."""
        text = self.editor.selected_text
        if text:
            self.copy_to_clipboard(text)
            self.notify("Copied", timeout=1)

    def action_paste_clipboard(self) -> None:
        """Paste into the editor (also reachable via the terminal's own paste)."""
        if not self.editor.read_only:
            self.editor.focus()
            self.editor.action_paste()

    def action_save(self) -> bool:
        """Return True if the disk write succeeded. (A Textual action may return
        a value without breaking binding dispatch.)"""
        if self._path is None:
            self.notify("No file path (launch sdf with a file)", severity="warning")
            return False
        if self.editor.read_only:
            self.notify("Read-only file (PDF)", severity="warning")
            return False
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(self.editor.text, encoding="utf-8")
        except OSError as exc:
            self.notify(f"Save failed: {exc}", severity="error")
            return False
        self._saved_text = self.editor.text
        self._last_disk_sig = self._current_sig()  # avoid a false external alert
        self._ignored_disk_text = None
        self._refresh_status()
        self.notify(f"Saved: {self._path.name}", timeout=2)
        return True

    def action_cycle_view(self) -> None:
        self._view_mode = VIEW_MODES[(VIEW_MODES.index(self._view_mode) + 1) % len(VIEW_MODES)]
        self._apply_layout()
        if self._view_mode in ("preview", "max-preview") and self.preview_scroll.display:
            self.preview_scroll.focus()
        else:
            self.editor.focus()
        self.notify(f"View: {self._view_mode}", timeout=1.5)

    def action_rotate(self) -> None:
        """Rotate the split a quarter turn: editor left -> top -> right -> bottom."""
        self._rotation = (self._rotation + 1) % len(ROTATIONS)
        self._apply_layout()
        self._persist()
        self.notify(f"Editor: {ROTATION_LABELS[self._rotation]}", timeout=1.2)

    def action_toggle_scroll_sync(self) -> None:
        self._scroll_sync = not self._scroll_sync
        self._persist()
        self.notify(f"Scroll sync: {'on' if self._scroll_sync else 'off'}", timeout=1.5)

    def action_cycle_ratio(self) -> None:
        self._ratio_idx = (self._ratio_idx + 1) % len(RATIOS)
        self._apply_layout()
        self._persist()

    def action_toggle_tree(self) -> None:
        show = not self.sidebar.display
        self.sidebar.display = show
        self._hints_files.display = show  # browser hints only while the tree is open
        if show:
            self.filetree.focus()
        else:
            self.editor.focus()

    def action_close_tree(self) -> None:
        """Close the file browser (Esc from inside it)."""
        if self.sidebar.display:
            self.action_toggle_tree()

    def action_focus_editor(self) -> None:
        """Escape closes the search bar first, else returns from the preview to the editor."""
        if self._search_active:
            self._close_search()
            return
        if self.focused is not None and self.preview_scroll in self.focused.ancestors_with_self:
            if self.editor.display:
                self.editor.focus()
            else:
                self.action_cycle_view()  # preview-only: bring the editor back

    # ---------------------------------------------------------- search
    def action_search(self) -> None:
        """Open the vim-like search bar (replaces the Keys box, bottom-left)."""
        self._search_active = True
        self._search_nav = False
        self._hints_general.display = False
        self._search_box.display = True
        self._search_status.display = False
        self._search_input.display = True
        self._search_input.value = self._search_query
        self._search_input.focus()
        if self._search_query:
            self._run_search(self._search_query)

    def action_search_close(self) -> None:
        self._close_search()

    def _close_search(self) -> None:
        self._search_active = False
        self._search_nav = False
        self._search_box.display = False
        self._hints_general.display = True
        self.editor.focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search-input":
            self._run_search(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "search-input":
            return
        if not self._search_offsets:
            self.bell()
            return
        # Confirm: focus the status line so n / p / Esc navigate (bare letters would
        # otherwise type in the editor). The editor keeps the current match selected.
        self._search_nav = True
        self._search_input.display = False
        self._search_status.display = True
        self._update_search_status()
        self._search_status.focus()
        self._highlight_current()

    def _run_search(self, query: str) -> None:
        self._search_query = query
        text = self.editor.text
        offsets: list[int] = []
        if query:
            low, q, i = text.lower(), query.lower(), 0
            while (j := low.find(q, i)) >= 0:
                offsets.append(j)
                i = j + len(q)
        self._search_offsets = offsets
        self._search_idx = 0 if offsets else -1
        self._highlight_current()
        self._update_search_status()

    def _offset_to_loc(self, off: int) -> tuple[int, int]:
        text = self.editor.text
        row = text.count("\n", 0, off)
        col = off - (text.rfind("\n", 0, off) + 1)
        return (row, col)

    def _highlight_current(self) -> None:
        if self._search_idx < 0 or not self._search_offsets:
            return
        off = self._search_offsets[self._search_idx]
        start = self._offset_to_loc(off)
        end = self._offset_to_loc(off + len(self._search_query))
        self.editor.selection = Selection(start, end)
        try:
            self.editor.scroll_cursor_visible(center=True)
        except Exception:
            pass

    def _update_search_status(self) -> None:
        q = escape(self._search_query)
        if not self._search_offsets:
            self._search_status.update(f"/{q}   [dim]no match[/dim]" if q else "[dim]type to search[/dim]")
            return
        pos = f"{self._search_idx + 1}/{len(self._search_offsets)}"
        self._search_status.update(f"/{q}   [b]{pos}[/b]   [dim]n next  p prev  Esc close[/dim]")

    def action_search_next(self) -> None:
        if self._search_offsets:
            self._search_idx = (self._search_idx + 1) % len(self._search_offsets)
            self._highlight_current()
            self._update_search_status()

    def action_search_prev(self) -> None:
        if self._search_offsets:
            self._search_idx = (self._search_idx - 1) % len(self._search_offsets)
            self._highlight_current()
            self._update_search_status()

    def action_cycle_focus(self) -> None:
        """Move focus to the next visible panel (browser -> editor -> preview)."""
        panels = []
        if self.sidebar.display:
            panels.append(self.filetree)
        if self.editor.display:
            panels.append(self.editor)
        if self.preview_scroll.display:
            panels.append(self.preview_scroll)
        if not panels:
            return
        focused = self.focused
        current = -1
        for i, panel in enumerate(panels):
            if focused is not None and panel in focused.ancestors_with_self:
                current = i
                break
        panels[(current + 1) % len(panels)].focus()

    def action_toggle_conflict_mode(self) -> None:
        self.conflict_mode = "prompt" if self.conflict_mode == "auto" else "auto"
        self._refresh_status()
        self._persist()
        self.notify(f"Conflict mode: {self.conflict_mode}", timeout=2)

    def action_toggle_transparency(self) -> None:
        self._transparent = not self._transparent
        self._apply_transparency()
        self._persist()
        self.notify(f"Transparency: {'on' if self._transparent else 'off'}", timeout=1.5)

    # --------------------------------------------------------------- layout
    def _refresh_hints(self) -> None:
        """Drop the view/rotate/ratio hints for files that have no preview."""
        if hasattr(self, "_hints_general"):
            has_preview = self._preview_kind is not None
            self._hints_general.update(GENERAL_HINTS if has_preview else GENERAL_HINTS_NO_PREVIEW)

    def _apply_layout(self) -> None:
        pv = self.preview_scroll
        mode = self._view_mode
        self._refresh_hints()
        # maximized modes drop the header and the hint bar for a clean full screen
        maximized = mode in ("max-editor", "max-preview")
        self._header.display = not maximized
        self._hints.display = not maximized
        if self._preview_kind is None:
            # non-markdown file: no preview, editor takes the whole area
            pv.display = False
            self.editor.display = True
            self.editor.styles.width = "1fr"
            self.editor.styles.height = "1fr"
            self._refresh_titles()
            return
        self.editor.display = mode in ("split", "editor", "max-editor")
        pv.display = mode in ("split", "preview", "max-preview")
        if mode in ("editor", "max-editor"):
            self.editor.styles.width = "1fr"
            self.editor.styles.height = "1fr"
            self._refresh_titles()
            return
        if mode in ("preview", "max-preview"):
            pv.styles.width = "1fr"
            pv.styles.height = "1fr"
            self._refresh_titles()
            return
        # split: honor rotation (orientation + editor placement) and ratio
        orient, editor_last = ROTATIONS[self._rotation % len(ROTATIONS)]
        try:
            if editor_last:
                self.panes.move_child(self.editor, after=pv)
            else:
                self.panes.move_child(self.editor, before=pv)
        except Exception:
            pass  # already in position
        self.panes.styles.layout = orient
        we, wp = RATIOS[self._ratio_idx % len(RATIOS)]
        if orient == "vertical":
            self.editor.styles.width = "1fr"
            pv.styles.width = "1fr"
            self.editor.styles.height = f"{we}fr"
            pv.styles.height = f"{wp}fr"
        else:
            self.editor.styles.height = "1fr"
            pv.styles.height = "1fr"
            self.editor.styles.width = f"{we}fr"
            pv.styles.width = f"{wp}fr"
        self._refresh_titles()

    # ----------------------------------------------------------- transparency
    def _apply_transparency(self) -> None:
        """Simple on/off: everything transparent, or nothing."""
        managed = [self._base_screen, self.editor, self.preview_scroll, self.preview,
                   self.sidebar, self.filetree, self._header,
                   self._hints_general, self._hints_files]
        for widget in managed:
            widget.set_class(self._transparent, "transparent")
