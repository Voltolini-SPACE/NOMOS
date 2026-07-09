"""NOMOS Memory Engine — reconstrução de contexto curto para reiniciar sessão.

Objetivo: dar ao agente (Claude Code/NOMOS) um bloco **curto e barato em tokens**
que ressuma o estado ao começar uma nova sessão. Puramente leitura — não grava
nada. Determinístico: prioridade desc, depois recência (ISO-8601 ordena bem).
"""
from __future__ import annotations

_PRIO_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def _rank(entry: dict) -> tuple[int, str]:
    return (_PRIO_ORDER.get(entry.get("priority", "low"), 0),
            entry.get("created_at", ""))


def build(
    raw_entries: list[dict],
    max_items: int = 12,
    max_chars: int = 1800,
) -> str:
    """Bloco de contexto curto. Sempre retorna algo utilizável (nunca vazio)."""
    total = len(raw_entries)
    if total == 0:
        return (
            "# NOMOS — Contexto de memória\n"
            "(memória local vazia — nenhuma memória registrada ainda)"
        )

    ordenadas = sorted(raw_entries, key=_rank, reverse=True)

    # Handoff mais recente ganha destaque (retomada de missão).
    handoffs = [e for e in raw_entries if e.get("source") == "handoff"]
    ultimo_handoff = max(handoffs, key=lambda e: e.get("created_at", ""), default=None)

    linhas: list[str] = ["# NOMOS — Contexto de memória"]
    linhas.append(f"Total de memórias: {total}. Itens mais relevantes primeiro.")
    if ultimo_handoff:
        conteudo = " ".join((ultimo_handoff.get("content", "")).split())
        linhas.append("")
        linhas.append(f"➤ Último handoff: {conteudo[:280]}")

    linhas.append("")
    usados = 0
    for e in ordenadas:
        if usados >= max_items:
            break
        prio = e.get("priority", "low")
        scope = e.get("scope", "project")
        source = e.get("source", "manual")
        conteudo = " ".join((e.get("content", "")).split())
        item = f"- [{prio}·{scope}/{source}] {conteudo[:180]}"
        # respeita o teto de caracteres
        if sum(len(x) + 1 for x in linhas) + len(item) > max_chars:
            linhas.append(f"- (… mais {total - usados} memória(s) — use --list)")
            break
        linhas.append(item)
        usados += 1

    return "\n".join(linhas)
