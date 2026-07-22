"""Persistent user settings, Neovim-style, stored under ~/.config/sdf/.

Settings the user changes at runtime (theme, conflict mode, transparency, split
orientation, width ratio) are written back so they survive across sessions.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULTS = {
    "theme": "gruvbox",
    "conflict_mode": "auto",
    "transparent": False,
    "rotation": 0,
    "ratio_idx": 0,
    "scroll_sync": True,
    "show_hidden": False,
}

# Enumerated fields validated on load so a hand-edited config can never crash us.
ENUMS = {
    "conflict_mode": {"auto", "prompt"},
}


def config_dir() -> Path:
    """Honor XDG_CONFIG_HOME, fall back to ~/.config (resolved at call time so
    tests can redirect it)."""
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / "sdf"


def config_path() -> Path:
    return config_dir() / "config.json"


class Config:
    def __init__(self, data: dict | None = None) -> None:
        self.data = dict(DEFAULTS)
        if data:
            self.data.update({k: v for k, v in data.items() if k in DEFAULTS})
        self._sanitize()

    def _sanitize(self) -> None:
        for key, allowed in ENUMS.items():
            if self.data.get(key) not in allowed:
                self.data[key] = DEFAULTS[key]
        for flag in ("transparent", "scroll_sync", "show_hidden"):
            if not isinstance(self.data.get(flag), bool):
                self.data[flag] = DEFAULTS[flag]
        for num in ("ratio_idx", "rotation"):
            if not isinstance(self.data.get(num), int) or self.data.get(num) < 0:
                self.data[num] = DEFAULTS[num]
        # theme is validated at apply time against the app's available themes.

    @classmethod
    def load(cls) -> "Config":
        try:
            raw = json.loads(config_path().read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return cls(raw)
        except (OSError, ValueError):
            pass
        return cls()

    def save(self) -> None:
        try:
            path = config_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(self.data, indent=2) + "\n", encoding="utf-8")
        except OSError:
            pass  # persistence must never crash the editor

    def get(self, key: str):
        return self.data.get(key, DEFAULTS.get(key))

    def update(self, **kwargs) -> None:
        self.data.update({k: v for k, v in kwargs.items() if k in DEFAULTS})
