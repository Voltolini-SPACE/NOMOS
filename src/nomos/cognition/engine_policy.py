"""NOMOS cognition.engine_policy — regras de elegibilidade de motor.

O roteador NUNCA decide sozinho o que a política proíbe. Este módulo traduz
o estado do kernel (localidade, política, cofre) em "este motor pode ser
considerado para esta tarefa?" — e devolve sempre um motivo honesto.

Regras (v0.11):
1. local_only ligado  => motor não-local NUNCA é elegível (nem com aprovação);
2. dados sensíveis    => motor não-local não é elegível (independe do cadeado);
3. motor cloud        => exige local off + chave configurada + aprovação humana
                         (A2+A3 continuam no gate na hora do uso — isto aqui é
                         só elegibilidade, não autorização);
4. motor não pronto   => não elegível, com instrução de próximo passo.
"""
from __future__ import annotations

from dataclasses import dataclass

from nomos.kernel import config, localidade

AUTO_CAMPO = "motores_auto"   # perfil (agent.json)


@dataclass(frozen=True)
class Elegibilidade:
    ok: bool
    motivo: str
    exige_aprovacao: bool = False


def nivel_privacidade(motor) -> str:
    return "total (não sai da máquina)" if motor.local else "dados saem da máquina"


def elegivel(motor, home=None, dados_sensiveis: bool = False,
             chave_configurada: bool | None = None) -> Elegibilidade:
    """Um motor pode ser considerado pelo roteador para esta tarefa?"""
    home = home or config.nomos_home()
    so_local = localidade.esta_ligado(home)

    if not motor.local:
        if so_local:
            return Elegibilidade(False,
                                 "modo só-local ligado: motores de nuvem estão "
                                 "desplugados (nomos local off para plugar)")
        if dados_sensiveis:
            return Elegibilidade(False,
                                 "a tarefa envolve dados sensíveis: não envio "
                                 "para fora da máquina, mesmo com a nuvem plugada")
        if motor.requer_chave and chave_configurada is False:
            return Elegibilidade(False,
                                 "falta a chave no cofre (nomos chaves) para "
                                 "usar este motor de nuvem")
        return Elegibilidade(True,
                             "nuvem plugada: uso ainda exige sua aprovação "
                             "A2+A3 na hora", exige_aprovacao=True)

    if not motor.pronto:
        return Elegibilidade(False, motor.status or "motor não está pronto")
    return Elegibilidade(True, "motor local pronto — nada sai da máquina",
                         exige_aprovacao=motor.requer_aprovacao)


def chave_cloud_configurada(vault) -> bool:
    """Só verifica EXISTÊNCIA do nome no cofre — nunca lê o valor."""
    try:
        return "anthropic_api_key" in set(vault.names())
    except Exception:
        return False


# ------------------- modo automático (liga/desliga) -------------------

def auto_ligado(perfil: dict | None = None) -> bool:
    perfil = perfil if perfil is not None else (config.load_agent() or {})
    return bool(perfil.get(AUTO_CAMPO, True))   # padrão: automático ligado


def definir_auto(ligado: bool) -> dict:
    from nomos.simple.onboarding import salvar_perfil
    return salvar_perfil({AUTO_CAMPO: bool(ligado)})
