"""NOMOS orquestracao.planejador — plano tipado governado (NH-003).

Transforma objetivo + passos sugeridos (do usuário, de heurística ou de LLM)
em um `PlanoTipado` que o orquestrador (NH-002) consegue executar. Regras
(anti-escalação e anti-injeção; o espírito do guard v2 do planner Hermes,
reimplementado à moda NOMOS — o guard congelado do Hermes permanece intocado
como defesa em profundidade do lado dele):

- a categoria de CADA passo vem SEMPRE do registro (NH-001); o plano não
  pode declarar nem rebaixar o próprio risco;
- ferramenta desconhecida ⇒ passo rejeitado; dependentes transitivos do
  rejeitado caem junto; nenhum passo válido ⇒ plano ok=False (fail-closed);
- params com padrão perigoso ⇒ passo rejeitado (REGEX_PERIGO congelada:
  mudança exige nova missão com evidência, não edição casual);
- sugestão de LLM é DATA, nunca autoridade: parse defensivo, JSON malformado
  ou de tipo errado ⇒ plano falha fechado; ids inválidos ⇒ passo rejeitado;
- risco agregado do plano = pior categoria; `exige_aprovacao=True` se > A0
  (a aprovação em si continua no gate do kernel na hora de EXECUTAR).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable

from nomos.kernel.policy import Category
from nomos.orquestracao.grafo import GrafoTarefas, No
from nomos.orquestracao.registro import RegistroCapacidades

_ID_RE = re.compile(r"^[a-z][a-z0-9\-]{0,63}$")

# CONGELADA (NH-003): padrões que nenhum param de passo pode conter.
# Deliberadamente pequena e de alta precisão — falso positivo em texto
# benigno é aceitável só quando o padrão é inequivocamente operacional.
REGEX_PERIGO = tuple(re.compile(p, re.IGNORECASE) for p in (
    r"\brm\s+-[a-z]*r[a-z]*f",          # rm -rf e variantes
    r"\bsudo\b",
    r"\bmkfs\.",
    r"\bdd\s+if=",
    r"curl[^|;]*\|\s*(ba)?sh",           # curl ... | sh
    r"wget[^|;]*\|\s*(ba)?sh",
    r"\bchmod\s+777\b",
    r"\bDROP\s+TABLE\b",
    r"\bDELETE\s+FROM\b.*\bWHERE\s+1=1",
    r":\(\)\s*\{.*\};\s*:",              # forkbomb
    r"\bshutdown\b|\breboot\b",
    r">\s*/dev/sd[a-z]",
))


@dataclass(frozen=True)
class PassoTipado:
    id: str
    ferramenta: str
    categoria: Category
    params: dict = field(default_factory=dict)
    depende_de: tuple[str, ...] = ()
    motor: str = ""
    idempotente: bool = False


@dataclass(frozen=True)
class PlanoTipado:
    ok: bool
    objetivo: str
    passos: tuple[PassoTipado, ...] = ()
    rejeitados: tuple[dict, ...] = ()
    risco: str = "A0"
    exige_aprovacao: bool = False
    motivo: str = ""

    def para_grafo(self, registro: RegistroCapacidades) -> GrafoTarefas:
        """Plano aprovado vira grafo executável (validação NH-002 re-checa tudo)."""
        nos = [No(id=p.id, ferramenta=p.ferramenta, params=dict(p.params),
                  depende_de=p.depende_de, motor=p.motor,
                  idempotente=p.idempotente) for p in self.passos]
        return GrafoTarefas(nos, registro)


def _param_perigoso(params: dict) -> str:
    """Nome do 1º padrão perigoso encontrado nos valores (ou '')."""
    for valor in params.values():
        texto = valor if isinstance(valor, str) else json.dumps(valor, default=str)
        for rx in REGEX_PERIGO:
            if rx.search(texto):
                return rx.pattern
    return ""


def _ordem_risco(nivel: str) -> int:
    ordem = ("A0", "A1", "A2", "A3", "A4", "A5", "A6")
    return ordem.index(nivel) if nivel in ordem else 99


def _sugestoes_do_llm(objetivo: str, llm: Callable) -> list | None:
    """Parse defensivo: qualquer anomalia ⇒ None (fail-closed no chamador)."""
    try:
        bruto = llm(objetivo)
    except Exception:
        return None
    try:
        dados = json.loads(bruto)
    except (TypeError, ValueError):
        return None
    return dados if isinstance(dados, list) else None


def planejar(objetivo: str, registro: RegistroCapacidades,
             passos: list | None = None, llm: Callable | None = None,
             audit=None) -> PlanoTipado:
    """Monta o plano tipado. `passos` explícitos têm precedência; sem eles,
    consulta o `llm` (opcional, injetável — ex.: via cognition.Router)."""

    def _auditar(evento: str, **campos) -> None:
        if audit is not None:
            audit.append(evento, **campos)

    if passos is None and llm is not None:
        passos = _sugestoes_do_llm(objetivo, llm)
        if passos is None:
            _auditar("planejador.plano.falhou", motivo="sugestão ilegível")
            return PlanoTipado(ok=False, objetivo=objetivo,
                               motivo="sugestão ilegível do modelo (fail-closed)")
    if not passos:
        _auditar("planejador.plano.falhou", motivo="sem passos")
        return PlanoTipado(ok=False, objetivo=objetivo,
                           motivo="nenhum passo para planejar")

    aceitos: dict[str, PassoTipado] = {}
    rejeitados: list[dict] = []

    def _rejeitar(pid: str, motivo: str) -> None:
        rejeitados.append({"id": pid, "motivo": motivo})
        _auditar("planejador.passo.rejeitado", passo=pid, motivo=motivo)

    for bruto in passos:
        if not isinstance(bruto, dict):
            _rejeitar(str(bruto)[:40], "passo malformado (não é objeto)")
            continue
        pid = str(bruto.get("id", ""))
        if not _ID_RE.match(pid):
            _rejeitar(pid or "<sem-id>", "id inválido")
            continue
        if pid in aceitos:
            _rejeitar(pid, "id duplicado")
            continue
        ferramenta = str(bruto.get("ferramenta", ""))
        categoria = registro.categoria_de(ferramenta)   # NUNCA do plano
        if categoria is None:
            _rejeitar(pid, f"ferramenta fora do registro: '{ferramenta}'")
            continue
        params = bruto.get("params") or {}
        if not isinstance(params, dict):
            _rejeitar(pid, "params malformados")
            continue
        padrao = _param_perigoso(params)
        if padrao:
            _rejeitar(pid, f"param perigoso (padrão {padrao!r})")
            continue
        depende_de = tuple(str(d) for d in (bruto.get("depende_de") or ()))
        aceitos[pid] = PassoTipado(
            id=pid, ferramenta=ferramenta, categoria=categoria, params=params,
            depende_de=depende_de, motor=str(bruto.get("motor", "")),
            idempotente=bool(bruto.get("idempotente", False)))

    # dependente de passo rejeitado/ausente cai junto (transitivo, até fixar)
    mudou = True
    while mudou:
        mudou = False
        for pid, passo in list(aceitos.items()):
            faltando = [d for d in passo.depende_de if d not in aceitos]
            if faltando:
                del aceitos[pid]
                _rejeitar(pid, f"dependência rejeitada/ausente: {', '.join(faltando)}")
                mudou = True

    if not aceitos:
        _auditar("planejador.plano.falhou", motivo="nenhum passo válido")
        return PlanoTipado(ok=False, objetivo=objetivo,
                           rejeitados=tuple(rejeitados),
                           motivo="nenhum passo válido sobrou (fail-closed)")

    risco = "A0"
    for passo in aceitos.values():
        nivel = passo.categoria.value.split("_")[0]
        if _ordem_risco(nivel) > _ordem_risco(risco):
            risco = nivel
    plano = PlanoTipado(ok=True, objetivo=objetivo,
                        passos=tuple(aceitos.values()),
                        rejeitados=tuple(rejeitados), risco=risco,
                        exige_aprovacao=risco != "A0")
    _auditar("planejador.plano.ok", passos=len(plano.passos),
             rejeitados=len(rejeitados), risco=risco)
    return plano
