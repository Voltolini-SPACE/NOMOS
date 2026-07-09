"""NOMOS Memory Engine — orquestrador.

Une as camadas (``store`` · ``policy`` · ``compactor`` · ``context_builder`` ·
``report``) sob duas leis do contrato MC28:

- **DRY-RUN é o padrão absoluto.** Nenhum método escreve em disco sem ``apply=True``.
- **APPLY só grava depois da política aprovar.** Qualquer achado de risco →
  ``MEMORY_REJECTED_FAIL_CLOSED`` e nada é persistido.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from nomos.memory import compactor, context_builder, policy, report, store

VALID_SOURCES = {"manual", "session_summary", "mission_result", "handoff", "repo_audit"}
VALID_SCOPES = {"project", "repo", "module", "temporary"}
VALID_PRIORITIES = {"low", "medium", "high", "critical"}

_REQUIRED = ("id", "created_at", "source", "scope", "priority", "tags",
             "content", "links", "safety", "hash")


@dataclass
class AddResult:
    applied: bool
    dry_run: bool
    allowed: bool
    reason: str
    entry: Optional[dict] = None
    decision: Optional[policy.PolicyDecision] = None
    path: Optional[str] = None


@dataclass
class CompactResult:
    dry_run: bool
    applied: bool
    plan: compactor.CompactionPlan
    path: Optional[str] = None


@dataclass
class ValidationResult:
    checked: int = 0
    ok: int = 0
    tampered: list = field(default_factory=list)
    structural_errors: list = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.tampered and not self.structural_errors

    def as_dict(self) -> dict:
        return {
            "checked": self.checked,
            "ok": self.ok,
            "tampered": self.tampered,
            "structural_errors": self.structural_errors,
            "valid": self.valid,
        }


class MemoryEngine:
    def __init__(self, base_dir=None) -> None:
        self.store = store.MemoryStore(base_dir)

    # ---------- adicionar ----------
    def add(
        self,
        content: str,
        source: str = "manual",
        scope: str = "project",
        priority: str = "medium",
        tags=None,
        links=None,
        apply: bool = False,
    ) -> AddResult:
        # 1) validação de campos — fail-closed em enum inválido
        if source not in VALID_SOURCES:
            return AddResult(False, not apply, False, f"INVALID_SOURCE:{source}")
        if scope not in VALID_SCOPES:
            return AddResult(False, not apply, False, f"INVALID_SCOPE:{scope}")
        if priority not in VALID_PRIORITIES:
            return AddResult(False, not apply, False, f"INVALID_PRIORITY:{priority}")

        # 2) política de segurança (conservadora)
        decision = policy.evaluate(content)
        if not decision.allowed:
            # bloqueado mesmo com apply — nada é gravado
            return AddResult(False, not apply, False, decision.reason, None, decision)

        # 3) monta a entrada canônica (com hash)
        entry = self._build_entry(content, source, scope, priority, tags, links, decision)

        # 4) DRY-RUN por padrão — não grava
        if not apply:
            return AddResult(False, True, True, "DRY_RUN", entry, decision)

        # 5) APPLY — grava no histórico bruto (append-only) e reindexa
        self.store.append_raw(entry)
        self.store.write_index(self.store.build_index())
        return AddResult(True, False, True, "APPLIED", entry, decision,
                         path=str(self.store.paths.raw))

    def _build_entry(self, content, source, scope, priority, tags, links, decision) -> dict:
        created = store.now_iso()
        norm_tags = sorted({str(t) for t in (tags or [])})
        norm_links = [str(x) for x in (links or [])]
        entry = {
            "id": store.new_id(content, created),
            "created_at": created,
            "source": source,
            "scope": scope,
            "priority": priority,
            "tags": norm_tags,
            "content": content,
            "links": norm_links,
            "safety": decision.safety_block(),  # tudo False para entradas admitidas
        }
        return store.finalize_entry(entry)

    # ---------- leitura ----------
    def list_entries(self) -> list[dict]:
        return self.store.read_raw()

    def context(self, max_items: int = 12, max_chars: int = 1800) -> str:
        return context_builder.build(self.store.read_raw(), max_items, max_chars)

    # ---------- compactação ----------
    def compact(self, apply: bool = False) -> CompactResult:
        raw = self.store.read_raw()          # o bruto é SÓ lido
        plano = compactor.plan(raw)
        if not apply:
            return CompactResult(dry_run=True, applied=False, plan=plano)
        self.store.write_compacted(plano.derived)   # escreve só o derivado
        self.store.write_index(self.store.build_index())
        return CompactResult(dry_run=False, applied=True, plan=plano,
                             path=str(self.store.paths.compacted))

    # ---------- validação de integridade ----------
    def validate(self) -> ValidationResult:
        res = ValidationResult()
        for e in self.store.read_raw():
            res.checked += 1
            eid = e.get("id", "?")
            faltando = [k for k in _REQUIRED if k not in e]
            if faltando or not isinstance(e.get("safety"), dict):
                res.structural_errors.append(eid)
                continue
            if store.compute_hash(e) != e.get("hash"):
                res.tampered.append(eid)   # alteração manual detectada
                continue
            res.ok += 1
        return res

    # ---------- relatório ----------
    def report(self, apply: bool = False):
        raw = self.store.read_raw()
        compacted = self.store.read_compacted()
        validation = self.validate().as_dict()
        rep = report.build(raw, compacted, validation)
        md = report.render_markdown(rep)
        path = None
        if apply:
            nome = f"report_{store.now_iso().replace(':', '').replace('-', '')}.md"
            path = str(self.store.write_report(nome, md))
        return rep, md, path
