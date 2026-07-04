"""NOMOS kernel.audit — trilha de evidências com cadeia de hash e redação.

Garantias:
- cada registro referencia o hash do anterior (adulteração quebra a cadeia);
- segredos nunca entram no log: redação por nome de campo e por padrão de valor;
- verify() detecta o primeiro ponto de violação.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

GENESIS = "0" * 64
REDACTED = "[REDIGIDO]"

# Campos cujo VALOR jamais pode ser registrado.
SENSITIVE_KEYS = {
    "secret", "segredo", "passphrase", "password", "senha",
    "token", "api_key", "apikey", "key", "authorization", "credential",
}

# Padrões de valores que denunciam segredos mesmo em campos "inocentes".
SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._-]{8,}"),
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}"),  # JWT
]


def _scrub_value(value):
    if isinstance(value, str):
        out = value
        for pat in SECRET_PATTERNS:
            out = pat.sub(REDACTED, out)
        return out
    if isinstance(value, dict):
        return redact(value)
    if isinstance(value, (list, tuple)):
        return [_scrub_value(v) for v in value]
    return value


def redact_text(text: str) -> str:
    """Redige padrões de segredo em texto livre (ex.: stdout de sandbox)."""
    out = text
    for pat in SECRET_PATTERNS:
        out = pat.sub(REDACTED, out)
    return out


def redact(fields: dict) -> dict:
    clean: dict = {}
    for k, v in fields.items():
        if k.lower() in SENSITIVE_KEYS:
            clean[k] = REDACTED
        else:
            clean[k] = _scrub_value(v)
    return clean


def _canonical(record: dict) -> str:
    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class AuditLog:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _last_hash(self) -> str:
        if not self.path.exists():
            return GENESIS
        last = None
        with self.path.open() as fh:
            for line in fh:
                if line.strip():
                    last = line
        if last is None:
            return GENESIS
        return json.loads(last).get("hash", GENESIS)

    def append(self, event: str, **fields) -> dict:
        record = {
            "ts": round(time.time(), 3),
            "event": event,
            **redact(fields),
            "prev": self._last_hash(),
        }
        record["hash"] = hashlib.sha256(
            (record["prev"] + _canonical({k: v for k, v in record.items() if k != "hash"}))
            .encode("utf-8")
        ).hexdigest()
        with self.path.open("a") as fh:
            fh.write(_canonical(record) + "\n")
        return record

    def estado(self) -> tuple[int, str]:
        """(nº de entradas, hash da última). Base para a âncora HMAC (audit_anchor)."""
        count, tip = 0, GENESIS
        if not self.path.exists():
            return 0, GENESIS
        with self.path.open() as fh:
            for line in fh:
                if line.strip():
                    count += 1
                    try:
                        tip = json.loads(line).get("hash", tip)
                    except json.JSONDecodeError:
                        return count, tip
        return count, tip

    def tip_em(self, n: int) -> str | None:
        """Hash da n-ésima entrada (1-based); GENESIS se n<=0; None se n além do fim."""
        if n <= 0:
            return GENESIS
        if not self.path.exists():
            return None
        i = 0
        with self.path.open() as fh:
            for line in fh:
                if not line.strip():
                    continue
                i += 1
                if i == n:
                    try:
                        return json.loads(line).get("hash", GENESIS)
                    except json.JSONDecodeError:
                        return None
        return None

    def verify(self) -> tuple[bool, int]:
        """Retorna (íntegro, índice_da_primeira_violação|-1)."""
        if not self.path.exists():
            return True, -1
        prev = GENESIS
        with self.path.open() as fh:
            for idx, line in enumerate(fh):
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    return False, idx
                if rec.get("prev") != prev:
                    return False, idx
                expected = hashlib.sha256(
                    (rec["prev"] + _canonical({k: v for k, v in rec.items() if k != "hash"}))
                    .encode("utf-8")
                ).hexdigest()
                if rec.get("hash") != expected:
                    return False, idx
                prev = rec["hash"]
        return True, -1
