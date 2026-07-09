"""NOMOS Mosaic — registro de telas, cada uma ISOLADA.

Cada "tela" do mosaico aponta para um site (email, rede social, marketplace…) e
recebe um **perfil de navegador próprio** (`profile_dir`) — cookies/login de uma
tela nunca vazam para outra. O registro é local (`~/.nomos/mosaic/screens.json`,
0600) e autocontido (stdlib apenas), para manter isolamento e rollback trivial.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

SCREENS_FILE = "screens.json"
PROFILES_DIR = "profiles"


def _default_base() -> Path:
    definido = os.environ.get("NOMOS_HOME")
    raiz = Path(definido) if definido else Path.home() / ".nomos"
    return raiz / "mosaic"


def _chmod(caminho: Path, modo: int) -> None:
    try:
        os.chmod(caminho, modo)
    except (OSError, NotImplementedError):
        pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_id(url: str) -> str:
    h = hashlib.sha256((url + uuid.uuid4().hex).encode("utf-8")).hexdigest()[:8]
    return f"scr_{h}"


@dataclass
class Screen:
    id: str
    url: str
    label: str
    profile_dir: str
    created_at: str
    active: bool = True
    tags: list[str] = field(default_factory=list)


class MosaicRegistry:
    def __init__(self, base_dir=None) -> None:
        self.base = Path(base_dir) if base_dir is not None else _default_base()

    @property
    def screens_path(self) -> Path:
        return self.base / SCREENS_FILE

    def profile_dir_for(self, screen_id: str) -> Path:
        # Isolamento: um user-data-dir por tela. NUNCA compartilhado.
        return self.base / PROFILES_DIR / screen_id

    # ---------- persistência ----------
    def _ensure(self) -> None:
        self.base.mkdir(parents=True, exist_ok=True)
        _chmod(self.base, 0o700)

    def _write(self, screens: list[Screen]) -> None:
        self._ensure()
        payload = {"schema": 1, "screens": [asdict(s) for s in screens]}
        tmp = self.screens_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        _chmod(tmp, 0o600)
        os.replace(tmp, self.screens_path)
        _chmod(self.screens_path, 0o600)

    def list(self) -> list[Screen]:
        if not self.screens_path.exists():
            return []
        data = json.loads(self.screens_path.read_text(encoding="utf-8"))
        return [Screen(**s) for s in data.get("screens", [])]

    def get(self, screen_id: str) -> Screen | None:
        return next((s for s in self.list() if s.id == screen_id), None)

    # ---------- mutação ----------
    @staticmethod
    def normalize_url(url: str) -> str:
        url = (url or "").strip()
        if not url:
            raise ValueError("url vazia")
        if not re.match(r"^https?://", url, re.I):
            url = "https://" + url
        return url

    def add(self, url: str, label: str = "") -> Screen:
        url = self.normalize_url(url)
        sid = _new_id(url)
        screen = Screen(
            id=sid,
            url=url,
            label=label.strip() or url,
            profile_dir=str(self.profile_dir_for(sid)),
            created_at=_now_iso(),
            active=True,
        )
        screens = self.list()
        screens.append(screen)
        self._write(screens)
        # cria a pasta de perfil isolada (vazia) — o login vive só aqui
        self.profile_dir_for(sid).mkdir(parents=True, exist_ok=True)
        _chmod(self.profile_dir_for(sid), 0o700)
        return screen

    def remove(self, screen_id: str) -> bool:
        screens = self.list()
        restantes = [s for s in screens if s.id != screen_id]
        if len(restantes) == len(screens):
            return False
        self._write(restantes)
        return True

    def profiles_isolated(self) -> bool:
        """Contrato de isolamento: todos os profile_dir são distintos."""
        dirs = [s.profile_dir for s in self.list()]
        return len(dirs) == len(set(dirs))
