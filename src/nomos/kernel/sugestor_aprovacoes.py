"""NOMOS kernel.sugestor_aprovacoes — minera a trilha, PROPÕE política (NH-017a).

`nomos approvals sugerir` lê o audit hash-chain e produz uma PROPOSTA
auditável — nunca aplica nada, por construção dupla: (1) este módulo só
escreve um arquivo de proposta; (2) o `PolicyEngine` decide POR CATEGORIA
(`rules[cat]`) — não existe caminho de código para regra por alvo, então a
proposta não teria nem ONDE ser aplicada automaticamente.

Regras duras (não configuráveis):
- A5/A6 (`CODE_EXEC`, `SKILL_INSTALL`, `DESTRUCTIVE`) fora do espaço de
  sugestão — nunca se propõe afrouxar execução/instalação/destruição;
- ALLOW_POR_ALVO exige histórico LIMPO (≥ N aprovadas, 0 negadas,
  0 expiradas na janela); uma negação sequer ⇒ MANTER;
- negações dominantes ⇒ REVISAR_NEGACOES (candidato a DENY explícito —
  anti-fadiga pela raiz).
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from nomos.kernel.plataforma import chmod_privado

CATEGORIAS_INTOCAVEIS = frozenset({
    "A5_CODE_EXEC", "A5_SKILL_INSTALL", "A6_DESTRUCTIVE",
})


@dataclass(frozen=True)
class EstatisticaAlvo:
    categoria: str
    alvo: str
    aprovadas: int
    negadas: int
    expiradas: int
    primeira_ts: float
    ultima_ts: float


@dataclass(frozen=True)
class Sugestao:
    categoria: str
    alvo: str
    acao: str            # "ALLOW_POR_ALVO" | "MANTER" | "REVISAR_NEGACOES"
    evidencia: EstatisticaAlvo
    explicacao: str


def minerar(caminho_audit: Path, janela_dias: int = 30) -> list[EstatisticaAlvo]:
    """Estatística por (categoria, alvo) dos eventos de aprovação da fila.

    Linha inválida é pulada (mesma tolerância do `estado()` do audit) —
    trilha meio-rasgada produz estatística PARCIAL, nunca crash.
    """
    corte = time.time() - janela_dias * 86400
    porta: dict[tuple[str, str], dict] = {}
    caminho = Path(caminho_audit)
    if not caminho.exists():
        return []
    solicitadas: dict[str, tuple[str, str]] = {}
    for bruta in caminho.read_text(encoding="utf-8").splitlines():
        try:
            ev = json.loads(bruta)
        except ValueError:
            continue
        if not isinstance(ev, dict):
            continue
        nome = ev.get("event", "")
        ts = float(ev.get("ts", 0) or 0)
        if nome == "approval.solicitada":
            rid = str(ev.get("id", ""))
            chave = (str(ev.get("category", "")), str(ev.get("target", "")))
            if rid:
                solicitadas[rid] = chave
            continue
        if nome not in ("approval.aprovada", "approval.negada",
                        "approval.expirada") or ts < corte:
            continue
        rid = str(ev.get("id", ""))
        achada = solicitadas.get(rid)
        if achada is None:
            # decisão sem solicitação rastreável: categoria/alvo do próprio
            # evento quando existirem; sem eles não há o que agregar
            achada = (str(ev.get("category", "")), str(ev.get("target", "")))
            if achada == ("", ""):
                continue
        chave = achada
        st = porta.setdefault(chave, {
            "aprovadas": 0, "negadas": 0, "expiradas": 0,
            "primeira": ts, "ultima": ts})
        campo = {"approval.aprovada": "aprovadas",
                 "approval.negada": "negadas",
                 "approval.expirada": "expiradas"}[nome]
        st[campo] += 1
        st["primeira"] = min(st["primeira"], ts)
        st["ultima"] = max(st["ultima"], ts)
    return [EstatisticaAlvo(categoria=c, alvo=a, aprovadas=s["aprovadas"],
                            negadas=s["negadas"], expiradas=s["expiradas"],
                            primeira_ts=s["primeira"], ultima_ts=s["ultima"])
            for (c, a), s in sorted(porta.items())]


def sugerir(stats: list[EstatisticaAlvo], *,
            minimo_aprovacoes: int = 5) -> list[Sugestao]:
    sugestoes: list[Sugestao] = []
    for st in stats:
        if st.categoria in CATEGORIAS_INTOCAVEIS:
            continue                      # nunca propõe afrouxar A5/A6
        total_ruim = st.negadas + st.expiradas
        if (st.aprovadas >= minimo_aprovacoes and total_ruim == 0):
            acao = "ALLOW_POR_ALVO"
            expl = (f"{st.aprovadas} aprovações, 0 negadas/expiradas na "
                    "janela — candidato a permissão explícita deste alvo")
        elif st.negadas > st.aprovadas:
            acao = "REVISAR_NEGACOES"
            expl = (f"{st.negadas} negações contra {st.aprovadas} aprovações "
                    "— candidato a DENY explícito (anti-fadiga pela raiz)")
        else:
            acao = "MANTER"
            expl = (f"histórico misto ({st.aprovadas} sim / {st.negadas} não "
                    f"/ {st.expiradas} expiradas) — manter o gate")
        sugestoes.append(Sugestao(categoria=st.categoria, alvo=st.alvo,
                                  acao=acao, evidencia=st, explicacao=expl))
    return sugestoes


def gravar_proposta(home: Path, sugestoes: list[Sugestao], audit) -> Path:
    """Escreve a PROPOSTA (0600) com âncora da trilha. Nunca toca policy.json."""
    destino = Path(home) / "approvals" / "propostas"
    destino.mkdir(parents=True, exist_ok=True)
    agora = datetime.now(timezone.utc)
    caminho = destino / f"proposta-{agora.strftime('%Y%m%d-%H%M%S')}.json"
    try:
        entradas, tip = audit.estado()    # tupla (nº de entradas, hash tip)
        ancora = {"entradas": entradas, "tip": tip}
    except Exception:
        ancora = {"erro": "trilha ilegível no momento da proposta"}
    corpo = {
        "gerada_em": agora.isoformat(),
        "aplicacao_automatica": "IMPOSSÍVEL POR CONSTRUÇÃO — o PolicyEngine "
                                "decide por categoria; isto é leitura para "
                                "decisão humana",
        "ancora_da_trilha": ancora,
        "sugestoes": [
            {**asdict(s), "evidencia": asdict(s.evidencia)} for s in sugestoes
        ],
    }
    texto = json.dumps(corpo, ensure_ascii=False, indent=2, sort_keys=True)
    tmp = caminho.with_suffix(".tmp")
    tmp.write_text(texto)
    chmod_privado(tmp, 0o600)
    tmp.replace(caminho)
    chmod_privado(caminho, 0o600)
    if audit is not None:
        audit.append("approvals.sugestao.gerada",
                     sugestoes=len(sugestoes),
                     digest=hashlib.sha256(texto.encode()).hexdigest())
    return caminho
