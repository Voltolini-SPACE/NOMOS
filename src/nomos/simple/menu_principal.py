"""NOMOS simple.menu_principal — a porta de entrada para quem não é técnico.

`nomos` sem argumentos: 1ª vez => onboarding; depois => este menu. O usuário
não precisa saber o que é provider, router, manifest, policy gate, llama.cpp
ou pipeline — só escolher um número. Toda a governança continua por baixo.
"""
from __future__ import annotations

from nomos.kernel import localidade

OPCOES = """O que vamos fazer?
 1. Conversar com meu agente
 2. Ver status do NOMOS
 3. Instalar/gerenciar cérebro
 4. Gerenciar motores
 5. Gerenciar skills
 6. Guardar chaves
 7. Ver modo local
 8. Rodar doutor/check-up
 9. Personalizar tema
10. Sair"""


# F4/ISSUE-022: no modo iniciante o menu esconde o que é avançado.
OPCOES_INICIANTE = """O que vamos fazer?
 1. Conversar com meu agente
 2. Ver status do NOMOS
 3. Instalar/gerenciar cérebro
 8. Rodar doutor/check-up
10. Sair
 (modo iniciante — digite 'avancado' para ver tudo)"""


def cabecalho(perfil: dict, home) -> str:
    nome = perfil.get("agent_name", "seu agente")
    if localidade.esta_ligado(home):
        estado = "Seu NOMOS está 100% local. 🔒 Nada sai da sua máquina."
    else:
        estado = ("Motores externos plugados. 🔌 Cada uso ainda pede sua "
                  "permissão.")
    return f"NOMOS — {nome} por perto.\n{estado}"


def menu_principal(ctx, perfil: dict, acoes: dict, ask=input, say=print) -> int:
    """Loop do menu. `acoes` mapeia opção -> callable() (injetado pela CLI).

    Contrato: cada callable devolve int (exit code) ou None; exceções não
    derrubam o menu — mostram mensagem amigável e voltam ao menu.
    """
    say(cabecalho(perfil, ctx["home"]))
    iniciante = bool(perfil.get("modo_iniciante"))
    while True:
        say("")
        say(OPCOES_INICIANTE if iniciante else OPCOES)
        try:
            op = ask("escolha> ").strip()
        except (EOFError, KeyboardInterrupt):
            say("")
            return 0
        if op in {"10", "sair", "q", ""}:
            say("até logo! Suas memórias e chaves ficam guardadas aqui.")
            return 0
        if op == "avancado" and iniciante:
            iniciante = False
            say("modo avançado ligado — todas as opções à mostra.")
            continue
        if op == "iniciante" and not iniciante:
            iniciante = True
            say("modo iniciante ligado — só o essencial.")
            continue
        fn = acoes.get(op)
        if fn is None:
            say("opção desconhecida — digite um número de 1 a 10.")
            continue
        try:
            rc = fn()
            if op == "1" and rc is not None:
                # sair do chat volta para o menu, não encerra o NOMOS
                continue
        except KeyboardInterrupt:
            say("\n(ok, voltando ao menu)")
        except Exception as exc:   # menu nunca despeja traceback no iniciante
            say("Algo deu errado do meu lado, mas nada foi perdido. Rode "
                "'8' (doutor) se quiser saber o que fazer. "
                f"(detalhe técnico: {type(exc).__name__})")
