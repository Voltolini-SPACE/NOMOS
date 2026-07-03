"""NOMOS kernel.approvals — fila de aprovações single-use com TTL (R4/C6).

Garantias:
- cada solicitação carrega token aleatório SINGLE-USE e TTL (padrão 5 min);
- expirada = NEGADA (fail-closed) e registrada como 'expirada';
- decidir exige o token exato (comparação em tempo constante); reuso é
  recusado — a solicitação já não está pendente;
- estado em arquivos 0600 dentro de NOMOS_HOME/approvals;
- toda transição gera evento de auditoria; o token NUNCA vai ao log.
"""
from __future__ import annotations

from nomos.kernel.plataforma import chmod_privado

import hmac
import json
import secrets
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TTL_S = 300.0  # 5 minutos (R4)
PENDENTE, APROVADA, NEGADA, EXPIRADA = "pendente", "aprovada", "negada", "expirada"


class ApprovalError(Exception):
    pass


@dataclass(frozen=True)
class Approval:
    id: str
    category: str
    target: str
    reason: str
    created: float
    expires: float
    status: str


class ApprovalQueue:
    def __init__(self, dirpath: Path, audit=None, clock=time.time,
                 ttl: float = DEFAULT_TTL_S):
        self.dir = Path(dirpath)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.audit = audit
        self.clock = clock
        self.ttl = ttl

    # ---------- interno ----------
    def _path(self, rid: str) -> Path:
        if not rid.replace("-", "").isalnum():
            raise ApprovalError("id inválido")
        return self.dir / f"{rid}.json"

    def _load(self, rid: str) -> dict:
        p = self._path(rid)
        if not p.exists():
            raise ApprovalError(f"solicitação inexistente: {rid}")
        return json.loads(p.read_text())

    def _save(self, data: dict) -> None:
        p = self._path(data["id"])
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False))
        chmod_privado(tmp, 0o600)
        tmp.replace(p)
        chmod_privado(p, 0o600)

    def _expire_if_due(self, data: dict) -> dict:
        if data["status"] == PENDENTE and self.clock() >= data["expires"]:
            data["status"] = EXPIRADA
            self._save(data)
            if self.audit:
                self.audit.append("approval.expirada", id=data["id"],
                                  category=data["category"], target=data["target"])
        return data

    # ---------- API ----------
    def request(self, category: str, target: str, reason: str) -> tuple[str, str]:
        """Cria solicitação; devolve (id, token). O token só existe aqui e no
        arquivo 0600 — quem decide precisa apresentá-lo."""
        rid = str(uuid.uuid4())
        token = secrets.token_urlsafe(24)
        now = self.clock()
        data = {
            "id": rid, "token": token, "category": str(category),
            "target": target, "reason": reason,
            "created": now, "expires": now + self.ttl,
            "status": PENDENTE, "decided_at": None,
        }
        self._save(data)
        if self.audit:
            self.audit.append("approval.solicitada", id=rid,
                              category=str(category), target=target, reason=reason)
        return rid, token

    def get(self, rid: str) -> Approval:
        d = self._expire_if_due(self._load(rid))
        return Approval(d["id"], d["category"], d["target"], d["reason"],
                        d["created"], d["expires"], d["status"])

    def token_of(self, rid: str) -> str:
        """Token para o LADO APROVADOR (painel local). Consome-se ao decidir."""
        d = self._expire_if_due(self._load(rid))
        if d["status"] != PENDENTE:
            raise ApprovalError(f"solicitação não está pendente: {d['status']}")
        return d["token"]

    def pending(self) -> list[Approval]:
        out = []
        for p in sorted(self.dir.glob("*.json")):
            d = self._expire_if_due(json.loads(p.read_text()))
            if d["status"] == PENDENTE:
                out.append(self.get(d["id"]))
        return out

    def decide(self, rid: str, token: str, approve: bool) -> str:
        d = self._expire_if_due(self._load(rid))
        if d["status"] != PENDENTE:
            raise ApprovalError(
                f"decisão recusada: solicitação {d['status']} (single-use/TTL)")
        if not hmac.compare_digest(d["token"], token or ""):
            if self.audit:
                self.audit.append("approval.token_invalido", id=rid)
            raise ApprovalError("token inválido — decisão recusada")
        d["status"] = APROVADA if approve else NEGADA
        d["decided_at"] = self.clock()
        d["token"] = ""  # nosec B105 - limpa o token (single-use), não é senha
        self._save(d)
        if self.audit:
            self.audit.append(f"approval.{d['status']}", id=rid,
                              category=d["category"], target=d["target"])
        return d["status"]

    def wait(self, rid: str, poll_s: float = 0.2, sleep=time.sleep) -> str:
        """Bloqueia até decisão ou expiração; devolve status final."""
        while True:
            st = self.get(rid).status
            if st != PENDENTE:
                return st
            sleep(poll_s)


def panel_approver(queue: ApprovalQueue, announce=print):
    """Approver p/ gate(): enfileira e espera humano decidir no painel local.
    Aprovação continua 100% humana — não há autoaprovação nem bypass."""
    def approver(decision) -> bool:
        rid, _tok = queue.request(str(decision.category), decision.target, decision.reason)
        announce(f"aprovação pendente no painel local (id={rid}); aguardando decisão humana até o TTL…")
        return queue.wait(rid) == APROVADA
    return approver
