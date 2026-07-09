"""NOMOS Memory Engine — relatório operacional (evidência auditável).

Funções puras: recebem os dados já lidos e devolvem um dicionário + markdown.
Quem grava em disco é o ``engine`` (e só com ``--apply``), mantendo a regra
"nada é escrito sem apply".
"""
from __future__ import annotations

from nomos.memory import store


def build(raw: list[dict], compacted: list[dict], validation: dict) -> dict:
    by_source: dict[str, int] = {}
    by_priority: dict[str, int] = {}
    for e in raw:
        by_source[e.get("source", "?")] = by_source.get(e.get("source", "?"), 0) + 1
        by_priority[e.get("priority", "?")] = by_priority.get(e.get("priority", "?"), 0) + 1
    return {
        "generated_at": store.now_iso(),
        "engine": "NOMOS_MEMORY_ENGINE_V1",
        "total_raw": len(raw),
        "total_compacted": len(compacted),
        "by_source": by_source,
        "by_priority": by_priority,
        "integrity": validation,
        "last_ids": [e.get("id") for e in raw[-5:]],
    }


def render_markdown(rep: dict) -> str:
    integ = rep.get("integrity", {})
    linhas = [
        "# NOMOS Memory Engine — Relatório operacional",
        "",
        f"- Gerado em: {rep.get('generated_at')}",
        f"- Motor: {rep.get('engine')}",
        f"- Memórias (bruto): {rep.get('total_raw')}",
        f"- Memórias (compactado): {rep.get('total_compacted')}",
        "",
        "## Integridade",
        f"- Verificadas: {integ.get('checked', 0)}",
        f"- Íntegras: {integ.get('ok', 0)}",
        f"- Adulteradas: {len(integ.get('tampered', []))} {integ.get('tampered', [])}",
        f"- Erros estruturais: {len(integ.get('structural_errors', []))} "
        f"{integ.get('structural_errors', [])}",
        "",
        "## Distribuição por fonte",
    ]
    linhas += [f"- {k}: {v}" for k, v in sorted(rep.get("by_source", {}).items())] or ["- (vazio)"]
    linhas += ["", "## Distribuição por prioridade"]
    linhas += [f"- {k}: {v}" for k, v in sorted(rep.get("by_priority", {}).items())] or ["- (vazio)"]
    linhas += ["", f"Últimos ids: {rep.get('last_ids', [])}"]
    return "\n".join(linhas)
