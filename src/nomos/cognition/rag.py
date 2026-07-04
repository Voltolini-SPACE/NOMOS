"""NOMOS cognition.rag — o agente USA o que lembra, com transparência (v1.1).

Duas peças pequenas e auditáveis:
- `contexto_relevante`: antes de responder, busca híbrida puxa até K memórias
  relevantes para um bloco de sistema — e devolve a contagem, para o chat
  mostrar o rodapé honesto "(usei N lembrança(s) suas)";
- `encolher_contexto`: conversa maior que o limite vira resumo heurístico
  LOCAL (pontos) das mensagens antigas + as recentes inteiras — janela
  adaptativa sem custo de inferência e sem inventar nada.

Nada aqui sai da máquina: é preparação de contexto para o motor local.
"""
from __future__ import annotations

MAX_LEMBRANCAS = 3
CHARS_POR_LEMBRANCA = 240
LIMITE_CONTEXTO = 8000          # chars; alinhado ao engine_router.CONTEXTO_GRANDE
MANTER_RECENTES = 4             # mensagens finais que nunca são resumidas


def contexto_relevante(mem, pergunta: str, k: int = MAX_LEMBRANCAS) -> tuple[str, int]:
    """(bloco_de_sistema, quantidade). Vazio quando não há nada relevante."""
    if not (pergunta or "").strip():
        return "", 0
    try:
        achados = mem.recall_hibrido(pergunta, k=k)
    except Exception:
        return "", 0
    itens = [i for i in achados if i.role in {"note", "user"}][:k]
    if not itens:
        return "", 0
    from nomos.cognition.prompt_guard import envelopar
    corpo = "\n".join(f"- {i.text[:CHARS_POR_LEMBRANCA]}" for i in itens)
    # F1/ISSUE-001: memória recuperada é DADO, nunca instrução
    bloco = envelopar(corpo, rotulo="lembrancas")
    return bloco, len(itens)


def encolher_contexto(mensagens: list[dict], limite: int = LIMITE_CONTEXTO) -> list[dict]:
    """Mantém system + recentes; o miolo antigo vira UM resumo de pontos.

    Determinístico e local (usa a heurística de extrair_pontos). Se já cabe,
    devolve como veio — sem custo nenhum."""
    total = sum(len(m.get("content", "")) for m in mensagens)
    if total <= limite:
        return mensagens
    sistemas = [m for m in mensagens if m.get("role") == "system"]
    conversa = [m for m in mensagens if m.get("role") != "system"]
    if len(conversa) <= MANTER_RECENTES:
        return mensagens          # não há "antigo" para resumir
    antigas, recentes = conversa[:-MANTER_RECENTES], conversa[-MANTER_RECENTES:]
    from nomos.cognition.arquivos import extrair_pontos
    corpo = "\n".join(f"{m.get('role')}: {m.get('content', '')}" for m in antigas)
    pontos = extrair_pontos(corpo, maximo=6)
    resumo = {"role": "system",
              "content": ("Resumo local do início desta conversa "
                          f"({len(antigas)} mensagens encolhidas): "
                          + " · ".join(pontos))}
    return sistemas + [resumo] + recentes
