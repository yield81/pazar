"""Съхранение на данните: JSON файлове в папка (по подразбиране data/ до пакета)."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

FILES = {
    "stores": "stores.json",
    "products": "products.json",
    "offers": "offers.json",
    "lists": "lists.json",
    "purchases": "purchases.json",
    "settings": "settings.json",
}

DEFAULTS = {
    "stores": [],
    "products": [],
    "offers": [],
    "lists": [],
    "purchases": [],
    "settings": {},
}


def default_data_dir() -> Path:
    env = os.environ.get("PAZAR_DATA")
    path = Path(env) if env else Path(__file__).resolve().parent.parent / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def new_id(prefix: str = "") -> str:
    return prefix + uuid.uuid4().hex[:8]


class DB:
    def __init__(self, root=None):
        self.root = Path(root) if root is not None else default_data_dir()
        self.root.mkdir(parents=True, exist_ok=True)
        for key in FILES:
            setattr(self, key, self._load(key))

    def _load(self, key: str):
        path = self.root / FILES[key]
        if not path.exists():
            return dict(DEFAULTS[key]) if isinstance(DEFAULTS[key], dict) else list(DEFAULTS[key])
        try:
            with path.open(encoding="utf-8") as fh:
                data = json.load(fh)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"Повреден файл с данни: {path} ({exc})")
        if not isinstance(data, type(DEFAULTS[key])):
            raise SystemExit(f"Неочакван формат в {path}")
        return data

    def _dump(self, key: str, data) -> None:
        path = self.root / FILES[key]
        tmp = path.with_name(path.name + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(tmp, path)

    def save_all(self) -> None:
        for key in FILES:
            self._dump(key, getattr(self, key))

    def reset(self) -> None:
        """Изтрива всички данни (само по изрична команда на потребителя)."""
        for key in FILES:
            (self.root / FILES[key]).unlink(missing_ok=True)
            setattr(self, key, dict(DEFAULTS[key]) if isinstance(DEFAULTS[key], dict) else list(DEFAULTS[key]))
