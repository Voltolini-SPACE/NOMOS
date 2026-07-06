"""NOMOS kernel.policy — motor de decisão fail-closed com gate de aprovação.

Taxonomia de ações (spec NOMOS v1.1):
  A0 leitura local | A1 escrita local | A2 egress de rede | A3 uso de credencial/
  conector | A4 dispositivos (mic/câmera/tela) | A5 execução de código/instalação
  de skill | A6 ação destrutiva/irreversível.

Regras invioláveis:
- padrão read-only: somente A0 é ALLOW por default;
- categoria desconhecida ou política corrompida => DENY (fail-closed);
- REQUIRE_APPROVAL nunca possui flag de bypass: sem aprovador, nega.
"""
from __future__ import annotations

from nomos.kernel.plataforma import chmod_privado

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable


class Category(str, Enum):
    READ_LOCAL = "A0_READ_LOCAL"
    WRITE_LOCAL = "A1_WRITE_LOCAL"
    NET_EGRESS = "A2_NET_EGRESS"
    CRED_USE = "A3_CRED_USE"
    CONNECTOR_USE = "A3_CONNECTOR_USE"
    DEVICE_MIC = "A4_DEVICE_MIC"
    DEVICE_CAM = "A4_DEVICE_CAM"
    DEVICE_SCREEN = "A4_DEVICE_SCREEN"
    CODE_EXEC = "A5_CODE_EXEC"
    SKILL_INSTALL = "A5_SKILL_INSTALL"
    DESTRUCTIVE = "A6_DESTRUCTIVE"


# rótulos humanos das categorias — quem decide APROVAR/NEGAR não deveria
# precisar decifrar um identificador técnico (painel e terminal usam isto)
ROTULOS_CATEGORIA = {
    "A0_READ_LOCAL": "A0 · ler arquivos locais",
    "A1_WRITE_LOCAL": "A1 · escrever arquivos locais",
    "A2_NET_EGRESS": "A2 · sair para a rede",
    "A3_CRED_USE": "A3 · usar credencial",
    "A3_CONNECTOR_USE": "A3 · usar conector",
    "A4_DEVICE_MIC": "A4 · usar microfone",
    "A4_DEVICE_CAM": "A4 · usar câmera",
    "A4_DEVICE_SCREEN": "A4 · capturar tela",
    "A5_CODE_EXEC": "A5 · executar código",
    "A5_SKILL_INSTALL": "A5 · instalar skill",
    "A6_DESTRUCTIVE": "A6 · ação destrutiva",
}


def rotulo_categoria(categoria) -> str:
    """Rótulo humano ('A2 · sair para a rede') para qualquer forma da
    categoria: Category, 'A2_NET_EGRESS' ou 'Category.NET_EGRESS'.
    Desconhecida ⇒ devolve como veio (nunca esconde informação)."""
    s = str(categoria)
    if s.startswith("Category."):
        try:
            s = Category[s.split(".", 1)[1]].value
        except KeyError:
            pass
    return ROTULOS_CATEGORIA.get(s, s)


class Effect(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"


@dataclass(frozen=True)
class Decision:
    effect: Effect
    category: str
    target: str
    reason: str


DEFAULT_RULES: dict[str, str] = {
    Category.READ_LOCAL.value: Effect.ALLOW.value,
    Category.WRITE_LOCAL.value: Effect.REQUIRE_APPROVAL.value,
    Category.NET_EGRESS.value: Effect.REQUIRE_APPROVAL.value,
    Category.CRED_USE.value: Effect.REQUIRE_APPROVAL.value,
    Category.CONNECTOR_USE.value: Effect.REQUIRE_APPROVAL.value,
    Category.DEVICE_MIC.value: Effect.REQUIRE_APPROVAL.value,
    Category.DEVICE_CAM.value: Effect.REQUIRE_APPROVAL.value,
    Category.DEVICE_SCREEN.value: Effect.REQUIRE_APPROVAL.value,
    Category.CODE_EXEC.value: Effect.REQUIRE_APPROVAL.value,
    Category.SKILL_INSTALL.value: Effect.REQUIRE_APPROVAL.value,
    Category.DESTRUCTIVE.value: Effect.DENY.value,
}

POLICY_FILE = "policy.json"


class PolicyEngine:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.home = self.path.parent   # localidade.json vive ao lado da política
        if not self.path.exists():
            self._write_default()

    def _write_default(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "mode": "read_only_default",
            "fail_closed": True,
            "rules": DEFAULT_RULES,
        }
        self.path.write_text(json.dumps(payload, indent=2))
        chmod_privado(self.path, 0o600)

    def rules(self) -> dict:
        try:
            return json.loads(self.path.read_text())
        except Exception:
            # Política ilegível => nenhum trust: tudo negado.
            return {"version": 0, "fail_closed": True, "rules": {}}

    def decide(self, category: Category | str, target: str = "") -> Decision:
        cat = category.value if isinstance(category, Category) else str(category)
        known = {c.value for c in Category}
        if cat not in known:
            return Decision(Effect.DENY, cat, target, "fail-closed: categoria desconhecida")
        effect_raw = self.rules().get("rules", {}).get(cat)
        if effect_raw not in {e.value for e in Effect}:
            return Decision(Effect.DENY, cat, target, "fail-closed: regra ausente/ inválida")
        if cat == Category.NET_EGRESS.value:
            from nomos.kernel import localidade
            if localidade.bloqueia_egress(self.home, target):
                return Decision(
                    Effect.DENY, cat, target,
                    "modo só-local ligado: saída para a internet bloqueada "
                    "(a nuvem é um motor opcional; use 'nomos local off' para plugá-la)")
        effect = Effect(effect_raw)
        reason = {
            Effect.ALLOW: "permitido pela política",
            Effect.DENY: "negado pela política",
            Effect.REQUIRE_APPROVAL: "ação sensível: exige aprovação explícita",
        }[effect]
        return Decision(effect, cat, target, reason)


Approver = Callable[[Decision], bool]


def gate(decision: Decision, approver: Approver | None) -> bool:
    """Gate de aprovação obrigatório. Retorna True somente se a ação pode prosseguir.

    - ALLOW  => True
    - DENY   => False
    - REQUIRE_APPROVAL => True apenas se um aprovador existir E confirmar.
      Sem aprovador (ex.: contexto não interativo) => False (fail-closed).
    """
    if decision.effect is Effect.ALLOW:
        return True
    if decision.effect is Effect.DENY:
        return False
    if approver is None:
        return False
    try:
        return bool(approver(decision))
    except Exception:
        return False  # aprovador com erro nunca autoriza
