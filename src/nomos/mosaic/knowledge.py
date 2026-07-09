"""NOMOS Mosaic — "vistoria" por tela (o que o agente já sabe de cada página).

Quando o agente varre uma tela, guarda aqui um resumo do que viu (título, trecho
de texto, contagem de itens). Assim, quando você pedir algo, ele **já sabe** —
sem reabrir tudo na hora.

Fronteira de segurança (importante): este armazém é LOCAL, 0600, por tela, e
pode conter conteúdo sensível de páginas (ex.: e-mails). Ele é um subsistema
**consentido e separado** — NUNCA é alimentado no motor de memória fail-closed
(`nomos.memory`), que permanece limpo de segredos/PII por contrato.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

KNOWLEDGE_DIR = "knowledge"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _chmod(caminho: Path, modo: int) -> None:
    try:
        os.chmod(caminho, modo)
    except (OSError, NotImplementedError):
        pass


@dataclass
class Knowledge:
    screen_id: str
    url: str
    scanned_at: str
    title: str = ""
    summary: str = ""
    text_excerpt: str = ""
    signals: dict = field(default_factory=dict)   # ex.: {"unread": 3, "alerts": 1}
    image: str = ""                               # data URI da última vistoria (thumb)


class KnowledgeStore:
    def __init__(self, base_dir: Path) -> None:
        self.dir = Path(base_dir) / KNOWLEDGE_DIR

    def _path(self, screen_id: str) -> Path:
        safe = "".join(c for c in screen_id if c.isalnum() or c in ("-", "_"))
        return self.dir / f"{safe}.json"

    def save(self, k: Knowledge) -> Path:
        self.dir.mkdir(parents=True, exist_ok=True)
        _chmod(self.dir, 0o700)
        p = self._path(k.screen_id)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(asdict(k), ensure_ascii=False, indent=2), encoding="utf-8")
        _chmod(tmp, 0o600)
        os.replace(tmp, p)
        _chmod(p, 0o600)
        return p

    def get(self, screen_id: str) -> Knowledge | None:
        p = self._path(screen_id)
        if not p.exists():
            return None
        return Knowledge(**json.loads(p.read_text(encoding="utf-8")))

    def all(self) -> list[Knowledge]:
        if not self.dir.exists():
            return []
        out = []
        for p in sorted(self.dir.glob("*.json")):
            try:
                out.append(Knowledge(**json.loads(p.read_text(encoding="utf-8"))))
            except (json.JSONDecodeError, TypeError):
                continue
        return out
