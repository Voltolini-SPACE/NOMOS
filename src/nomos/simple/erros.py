"""NOMOS simple.erros — códigos de erro pesquisáveis (v1.0.1).

Toda falha importante da CLI carrega um código `[NOMOS-Exx]` que o usuário
pode procurar em docs/ERROS.md (ou na busca do GitHub). O texto amigável
continua; o código só dá um endereço fixo para a solução.
"""
from __future__ import annotations

CODIGOS = {
    "E001": "cofre: passphrase ausente/incorreta ou cofre inexistente",
    "E002": "ação negada fail-closed (sem TTY, sem aprovação ou política nega)",
    "E003": "arquivo não encontrado, grande demais ou formato não suportado",
    "E004": "skill: manifesto inválido, checksum divergente ou não confirmada",
    "E005": "backup: senha incorreta, arquivo adulterado ou destino já existe",
    "E006": "rotina: hora/ação inválida ou não aprovada",
    "E007": "motor indisponível ou não instalado",
    "E008": "atualização: rede indisponível ou resposta inválida",
    "E009": "conserto do doutor não confirmado ou indisponível",
    "E010": "argumentos inválidos (JSON malformado, opção desconhecida)",
}


# F4/ISSUE-021: uma frase humana e um "próximo passo" por código, para o chat.
HUMANO = {
    "E001": ("O cofre precisa da sua senha-mestra — ou ainda não foi criado.",
             "crie/abra com: nomos vault init"),
    "E002": ("Isto é proteção, não erro: a ação foi negada porque exige sua "
             "aprovação num terminal de verdade.", "rode num terminal e aprove quando eu perguntar"),
    "E003": ("Não consegui usar esse arquivo — caminho errado, grande demais "
             "ou formato que não leio.", "confira o caminho; PDF precisa de: pip install 'nomos[arquivos]'"),
    "E004": ("A skill não passou nas verificações de segurança.",
             "veja o motivo com: nomos skills diagnostico"),
    "E005": ("Senha incorreta, arquivo adulterado, ou o destino já existe.",
             "confira a senha; para exportar, escolha um nome novo"),
    "E006": ("A rotina tem hora/ação inválida ou não foi aprovada.",
             'ex.: nomos rotinas criar "Briefing" 08:00 briefing'),
    "E007": ("O motor que eu precisava não está pronto.",
             "veja o que falta: nomos motores diagnostico"),
    "E008": ("Não consegui checar a internet (ou o cadeado está fechado).",
             "veja manualmente as releases no GitHub"),
    "E009": ("O conserto precisa da sua confirmação num terminal.",
             "rode: nomos doutor --consertar e digite CONSERTAR"),
    "E010": ("Os argumentos não são válidos (JSON malformado ou opção "
             "desconhecida).", "confira as aspas do JSON; use --help do comando"),
}


def fmt(codigo: str, mensagem: str) -> str:
    """'[NOMOS-E005] não importei: senha incorreta...' — validado em teste."""
    assert codigo in CODIGOS, f"código de erro não catalogado: {codigo}"
    return f"[NOMOS-{codigo}] {mensagem}"


def explicar(codigo: str) -> str:
    """Frase humana + próximo passo para o chat (F4). Todo código tem uma."""
    frase, passo = HUMANO.get(codigo, ("Algo não deu certo.", ""))
    return f"[{codigo}] {frase}" + (f" → {passo}" if passo else "")
