"""sdf command-line entry point."""

from __future__ import annotations

import argparse
import tempfile
from importlib.resources import files
from pathlib import Path

from . import __version__
from .app import SdfApp


def _example_path() -> str:
    """Copy the bundled example next to the temp dir so the user can edit it
    freely without touching the installed package."""
    content = (files("sdf") / "example.md").read_text(encoding="utf-8")
    dest = Path(tempfile.gettempdir()) / "sdf-example.md"
    dest.write_text(content, encoding="utf-8")
    return str(dest)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="sdf",
        description="SDF (Simple Draft Frame): terminal markdown editor/preview "
                    "that reloads on external changes.",
    )
    parser.add_argument(
        "-v", "--version", action="version", version=f"SDF {__version__}",
    )
    parser.add_argument(
        "file", nargs="?",
        help="Markdown file to open (created on save if it does not exist).",
    )
    parser.add_argument(
        "--example", action="store_true",
        help="Open the bundled example file to try the live preview.",
    )
    parser.add_argument(
        "--conflict", choices=("auto", "prompt"), default=None,
        help="auto: reload silently when the buffer is clean, ask otherwise. "
             "prompt: ask on every external change. (default: from config)",
    )
    parser.add_argument(
        "--theme", default=None,
        help="Textual theme name for this session (e.g. gruvbox, nord, dracula).",
    )
    parser.add_argument(
        "--transparent", action="store_true",
        help="Make the whole UI transparent for this session.",
    )
    args = parser.parse_args()
    path = _example_path() if args.example else args.file
    SdfApp(
        path=path,
        conflict_mode=args.conflict,
        theme=args.theme,
        transparent=True if args.transparent else None,
    ).run()


if __name__ == "__main__":
    main()
