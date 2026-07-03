"""NOMOS simple.traducao — governança A0–A6 em português de gente.

O gate continua idêntico por baixo (fail-closed, TTY obrigatório, confirmação
digitada); só a APRESENTAÇÃO muda. Contrato do aprovador leigo: digitar
exatamente "sim" (ignorando maiúsculas/espaços) aprova; QUALQUER outra coisa
nega; fora de terminal interativo, nega sem perguntar.
"""
from __future__ import annotations

import sys

from nomos.kernel.policy import Category

AMIGAVEL = {
    Category.READ_LOCAL.value: "ler um arquivo do seu computador",
    Category.WRITE_LOCAL.value: "criar ou alterar um arquivo no seu computador",
    Category.NET_EGRESS.value: "acessar a internet",
    Category.CRED_USE.value: "usar uma senha/chave guardada no cofre",
    Category.CONNECTOR_USE.value: "usar uma conta conectada sua",
    Category.DEVICE_MIC.value: "ouvir pelo seu microfone",
    Category.DEVICE_CAM.value: "ver pela sua câmera",
    Category.DEVICE_SCREEN.value: "ver a sua tela",
    Category.CODE_EXEC.value: "executar um programa em ambiente isolado",
    Category.SKILL_INSTALL.value: "instalar uma nova habilidade",
    Category.DESTRUCTIVE.value: "fazer algo IRREVERSÍVEL (apagar/destruir)",
}

CORES = {"reset": "\033[0m", "negrito": "\033[1m", "fraco": "\033[2m",
         "ciano": "\033[36m", "amarelo": "\033[33m", "verde": "\033[32m",
         "vermelho": "\033[31m"}


def cor(nome: str, texto: str, ativo: bool = True) -> str:
    if not ativo:
        return texto
    return f"{CORES[nome]}{texto}{CORES['reset']}"


def explicar_decisao(decision, nome_agente: str = "Seu agente") -> str:
    acao = AMIGAVEL.get(str(decision.category), f"fazer uma ação de tipo {decision.category}")
    linhas = [f"{nome_agente} está pedindo permissão para {acao}."]
    if decision.target:
        linhas.append(f"  alvo: {decision.target}")
    if getattr(decision, "reason", ""):
        linhas.append(f"  por quê: {decision.reason}")
    linhas.append('Digite "sim" para permitir, ou qualquer outra coisa para negar.')
    return "\n".join(linhas)


def aprovador_amigavel(nome_agente: str = "Seu agente", ask=input, say=print,
                       entrada=None, saida=None):
    """Approver compatível com gate(): humano, explícito, fail-closed."""
    stdin = entrada or sys.stdin
    stdout = saida or sys.stdout

    def approver(decision) -> bool:
        if not (stdin.isatty() and stdout.isatty()):
            say("(pedido de permissão negado automaticamente: não estou num "
                "terminal interativo — proteção padrão)")
            return False
        say("")
        say(cor("amarelo", "🔒 PERMISSÃO NECESSÁRIA"))
        say(explicar_decisao(decision, nome_agente))
        resp = ask("> ")
        ok = resp.strip().casefold() == "sim"
        say(cor("verde", "permitido.") if ok else cor("vermelho", "negado."))
        return ok

    return approver
