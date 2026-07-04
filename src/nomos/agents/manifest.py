"""NOMOS agents.manifest — o contrato declarativo de um agente (F3).

Ferramentas conhecidas são um conjunto FECHADO (allowlist): um agente não pode
inventar uma ferramenta nem ganhar acesso a algo fora desta lista.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from nomos.kernel.policy import Category

# Allowlist de ferramentas que um agente PODE declarar. Cada uma mapeia à
# categoria de política exigida (o gate decide na hora do uso).
FERRAMENTAS = {
    "memoria_buscar":   Category.READ_LOCAL,     # ler memórias/histórico (A0)
    "arquivo_ler":      Category.READ_LOCAL,     # ler arquivo local (A0)
    "arquivo_resumir":  Category.READ_LOCAL,     # resumir com motor local (A0)
    "arquivo_escrever": Category.WRITE_LOCAL,    # gravar arquivo (A1)
    "codigo_gerar":     Category.READ_LOCAL,     # gerar código (texto; A0)
    "doutor":           Category.READ_LOCAL,     # check-up (A0)
    "logs_verificar":   Category.READ_LOCAL,     # auditar (A0)
    "skill_rodar":      Category.SKILL_INSTALL,  # invocar skill (A5, cada uso no gate)
}

NOME_RE = re.compile(r"^[a-z][a-z0-9\-]{1,31}$")
RISCOS = ("A0", "A1", "A2", "A3", "A4", "A5", "A6")


@dataclass(frozen=True)
class AgentManifest:
    name: str
    objetivo: str
    ferramentas: tuple[str, ...]
    motores_preferidos: tuple[str, ...] = ()
    risco_max: str = "A0"
    memoria_scope: str = "compartilhada"      # compartilhada | isolada
    pode_chamar_agente: bool = False
    pode_executar_skill: bool = False
    exige_aprovacao: bool = False
    keywords: tuple[str, ...] = field(default_factory=tuple)

    @staticmethod
    def de_dict(d: dict) -> "AgentManifest":
        return AgentManifest(
            name=d.get("name", ""), objetivo=d.get("objetivo", ""),
            ferramentas=tuple(d.get("ferramentas", [])),
            motores_preferidos=tuple(d.get("motores_preferidos", [])),
            risco_max=d.get("risco_max", "A0"),
            memoria_scope=d.get("memoria_scope", "compartilhada"),
            pode_chamar_agente=bool(d.get("pode_chamar_agente", False)),
            pode_executar_skill=bool(d.get("pode_executar_skill", False)),
            exige_aprovacao=bool(d.get("exige_aprovacao", False)),
            keywords=tuple(d.get("keywords", [])))

    def dict(self) -> dict:
        return {"name": self.name, "objetivo": self.objetivo,
                "ferramentas": list(self.ferramentas),
                "motores_preferidos": list(self.motores_preferidos),
                "risco_max": self.risco_max, "memoria_scope": self.memoria_scope,
                "pode_chamar_agente": self.pode_chamar_agente,
                "pode_executar_skill": self.pode_executar_skill,
                "exige_aprovacao": self.exige_aprovacao,
                "keywords": list(self.keywords)}


def _ordem_risco(r: str) -> int:
    return RISCOS.index(r) if r in RISCOS else 99


def risco_exigido(ferramentas) -> str:
    """Maior risco (A0–A6) exigido pelas ferramentas declaradas."""
    pior = "A0"
    for f in ferramentas:
        cat = FERRAMENTAS.get(f)
        if cat is None:
            return "A6"                      # desconhecida => trata como o pior
        nivel = cat.value.split("_")[0]      # 'A1_WRITE_LOCAL' -> 'A1'
        if _ordem_risco(nivel) > _ordem_risco(pior):
            pior = nivel
    return pior


def validar(mf: AgentManifest) -> list[str]:
    """Lista de problemas (vazia = ok). Fail-closed em contradições."""
    p: list[str] = []
    if not NOME_RE.match(mf.name or ""):
        p.append("nome inválido (minúsculas, dígitos e hífen; 2–32)")
    if not mf.objetivo:
        p.append("objetivo obrigatório")
    for f in mf.ferramentas:
        if f not in FERRAMENTAS:
            p.append(f"ferramenta desconhecida (fora da allowlist): {f}")
    if mf.risco_max not in RISCOS:
        p.append(f"risco_max inválido: {mf.risco_max!r}")
    # o manifesto NÃO pode declarar risco menor do que suas ferramentas exigem
    exigido = risco_exigido(mf.ferramentas)
    if _ordem_risco(mf.risco_max) < _ordem_risco(exigido):
        p.append(f"risco_max {mf.risco_max} é MENOR que o exigido pelas "
                 f"ferramentas ({exigido}) — proibido afrouxar")
    if "skill_rodar" in mf.ferramentas and not mf.pode_executar_skill:
        p.append("declara skill_rodar mas pode_executar_skill=false (contradição)")
    return p
