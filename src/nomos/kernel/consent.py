"""NOMOS kernel.consent — consentimento explícito para microfone, câmera e tela.

Garantias:
- todos os dispositivos DESLIGADOS por padrão;
- concessão sempre com TTL (sessão), nunca perpétua por omissão;
- expiração automática persiste o estado revogado;
- panic() revoga tudo imediatamente.
"""
from __future__ import annotations

from nomos.kernel.plataforma import chmod_privado

import json
import time
from pathlib import Path

DEVICES = ("microfone", "camera", "tela")
DEFAULT_TTL_MIN = 15


class ConsentError(Exception):
    pass


class ConsentRegistry:
    def __init__(self, path: Path):
        self.path = Path(path)
        if not self.path.exists():
            self._write({d: {"granted": False, "expires_at": None} for d in DEVICES})

    def _read(self) -> dict:
        # registro corrompido/truncado ⇒ tudo revogado (fail-closed), sem
        # estourar JSONDecodeError em is_granted/status
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {d: {"granted": False, "expires_at": None} for d in DEVICES}
        if not isinstance(data, dict):
            return {d: {"granted": False, "expires_at": None} for d in DEVICES}
        return data

    def _write(self, data: dict) -> None:
        # escrita atômica (tmp + replace): crash no meio não corrompe o registro
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        chmod_privado(tmp, 0o600)
        tmp.replace(self.path)
        chmod_privado(self.path, 0o600)

    def grant(self, device: str, ttl_minutes: int = DEFAULT_TTL_MIN) -> dict:
        if device not in DEVICES:
            raise ConsentError(f"dispositivo desconhecido: {device}")
        if ttl_minutes <= 0:
            raise ConsentError("TTL deve ser positivo")
        data = self._read()
        data[device] = {
            "granted": True,
            "expires_at": round(time.time() + ttl_minutes * 60, 3),
        }
        self._write(data)
        return data[device]

    def revoke(self, device: str) -> None:
        if device not in DEVICES:
            raise ConsentError(f"dispositivo desconhecido: {device}")
        data = self._read()
        data[device] = {"granted": False, "expires_at": None}
        self._write(data)

    def panic(self) -> None:
        """Revogação imediata de todos os consentimentos."""
        self._write({d: {"granted": False, "expires_at": None} for d in DEVICES})

    def is_granted(self, device: str) -> bool:
        if device not in DEVICES:
            return False  # fail-closed
        data = self._read()
        entry = data.get(device, {"granted": False, "expires_at": None})
        if not entry.get("granted"):
            return False
        exp = entry.get("expires_at")
        if exp is not None and time.time() >= exp:
            self.revoke(device)  # expiração persiste o estado revogado
            return False
        return True

    def status(self) -> dict:
        return {d: self.is_granted(d) for d in DEVICES}
