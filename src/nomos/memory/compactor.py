"""NOMOS Memory Engine — compactação determinística.

Compactar = derivar um resumo enxuto do histórico bruto para reduzir custo de
contexto/tokens. Duas invariantes absolutas:

1. **Nunca apaga nem reescreve o histórico bruto.** A compactação só produz um
   arquivo DERIVADO (``memory.compacted.jsonl``). O bruto é a fonte da verdade.
2. **Determinística.** Sem LLM, sem rede: mesma entrada → mesmo resultado. O
   resumo agrupa por (escopo, fonte) e preserva a proveniência (ids de origem
   em ``links``), então nada de auditável se perde.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from nomos.memory import store

# Ordem de prioridade para escolher a "prioridade do resumo" (a maior do grupo).
_PRIO_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}
_MAX_SNIPPET = 140      # chars por item resumido
_MAX_ITEMS_INLINE = 8   # itens citados antes de "(+N mais)"


@dataclass
class CompactionPlan:
    groups: int = 0
    raw_count: int = 0
    derived: list[dict] = field(default_factory=list)

    @property
    def reduction(self) -> str:
        if self.raw_count == 0:
            return "0 → 0"
        return f"{self.raw_count} → {len(self.derived)}"


def _short(text: str) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= _MAX_SNIPPET else text[: _MAX_SNIPPET - 1] + "…"


def _group_key(entry: dict) -> tuple[str, str]:
    return (entry.get("scope", "project"), entry.get("source", "manual"))


def plan(raw_entries: list[dict]) -> CompactionPlan:
    """Monta o plano de compactação SEM tocar em disco. Ordena os grupos de
    forma estável para ser reprodutível."""
    buckets: dict[tuple[str, str], list[dict]] = {}
    for e in raw_entries:
        buckets.setdefault(_group_key(e), []).append(e)

    derived: list[dict] = []
    for (scope, source) in sorted(buckets):
        items = buckets[(scope, source)]
        prio = max((i.get("priority", "low") for i in items),
                   key=lambda p: _PRIO_ORDER.get(p, 0))
        tags = sorted({t for i in items for t in (i.get("tags") or [])} | {"compactado"})
        origem_ids = [i.get("id") for i in items if i.get("id")]

        linhas = [f"- {_short(i.get('content', ''))}" for i in items[:_MAX_ITEMS_INLINE]]
        if len(items) > _MAX_ITEMS_INLINE:
            linhas.append(f"- (+{len(items) - _MAX_ITEMS_INLINE} memórias mais)")
        corpo = "\n".join(linhas)
        content = (
            f"Resumo compactado de {len(items)} memória(s) "
            f"[escopo={scope}, fonte={source}]:\n{corpo}"
        )

        created = store.now_iso()
        entry = {
            "id": store.new_id(content, created),
            "created_at": created,
            "source": "compaction",
            "scope": scope,
            "priority": prio,
            "tags": tags,
            "content": content,
            "links": origem_ids,
            "safety": {
                "contains_secret": False,
                "contains_personal_sensitive_data": False,
                "human_review_required": False,
            },
        }
        derived.append(store.finalize_entry(entry))

    return CompactionPlan(groups=len(buckets), raw_count=len(raw_entries), derived=derived)
