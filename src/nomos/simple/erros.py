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


def fmt(codigo: str, mensagem: str) -> str:
    """'[NOMOS-E005] não importei: senha incorreta...' — validado em teste."""
    assert codigo in CODIGOS, f"código de erro não catalogado: {codigo}"
    return f"[NOMOS-{codigo}] {mensagem}"
