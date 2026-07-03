"""NOMOS ext.skill_sdk — criar uma skill de verdade em um comando.

`nomos skills criar <nome>` gera um esqueleto completo e VÁLIDO:
- main.py com I/O estruturado (JSON entra por arquivo, JSON sai no stdout);
- skill.json v2 com checksums corretos e risco calculado;
- README.md explicando permissões, assinatura e publicação.

O esqueleto nasce com A0 (só leitura local) — o autor adiciona permissões
conscientemente, sabendo que cada uma passa pelo gate do usuário.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from nomos.ext import skill_registry as reg

NOME_RE = re.compile(r"^[a-z][a-z0-9\-]{1,31}$")


class SdkError(Exception):
    pass


_MAIN_TEMPLATE = '''"""Skill NOMOS: {nome} — edite a função executar()."""
import json
import sys


def executar(argumentos: dict) -> dict:
    """Recebe argumentos (JSON) e devolve um resultado (JSON-serializável).

    Regras da casa:
    - só faça o que as permissões do skill.json declaram;
    - nunca finja sucesso: erro honesto é melhor que resultado inventado.
    """
    return {{
        "ok": True,
        "skill": "{nome}",
        "mensagem": "olá! edite executar() em main.py",
        "eco": argumentos,
    }}


if __name__ == "__main__":
    args = {{}}
    if len(sys.argv) > 1:
        try:
            with open(sys.argv[1], encoding="utf-8") as fh:
                args = json.load(fh)
        except Exception as exc:
            print(json.dumps({{"ok": False, "erro": f"argumentos ilegíveis: {{exc}}"}}))
            raise SystemExit(1)
    print(json.dumps(executar(args), ensure_ascii=False))
'''

_README_TEMPLATE = """# Skill: {nome}

Criada com `nomos skills criar`. Edite `main.py` e ajuste o `skill.json`.

## Como funciona
- entrada: um arquivo JSON é passado como 1º argumento (`sys.argv[1]`);
- saída: imprima UM JSON no stdout (`{{"ok": true, ...}}`);
- a skill roda no sandbox do NOMOS: sem rede e sem variáveis do host, a menos
  que declare (e o usuário aprove) as permissões correspondentes.

## Permissões (skill.json)
- `A0_READ_LOCAL` — ler arquivos (padrão do esqueleto)
- `A1_WRITE_LOCAL` — criar/alterar arquivos (risco médio)
- `A2_NET_EGRESS` — internet (risco alto; bloqueada pelo modo só-local)
- `A5_CODE_EXEC` — executar programas (risco alto)
Cada permissão passa pelo gate de aprovação do usuário a cada execução.

## Atualizar checksums após editar
```bash
python3 -c "import hashlib,json,pathlib; p=pathlib.Path('.');\\
mf=json.loads((p/'skill.json').read_text());\\
mf['files']={{f: hashlib.sha256((p/f).read_bytes()).hexdigest() for f in mf['files']}};\\
(p/'skill.json').write_text(json.dumps(mf, indent=2, ensure_ascii=False))"
```

## Assinar e publicar
```bash
nomos skill keygen                       # uma vez, gera seu par de chaves
nomos skill sign . --key <chave.pem>     # assina o manifesto
# distribua a pasta; quem instala decide confiar: nomos skill trust add <pubkey>
```

## Testar localmente
```bash
nomos skills instalar .
nomos skills rodar {nome} --args '{{"exemplo": 123}}'
```
"""


def criar_skill(nome: str, pasta: Path) -> Path:
    if not NOME_RE.match(nome or ""):
        raise SdkError("nome inválido: use minúsculas, dígitos e hífen "
                       "(2–32 caracteres, começando por letra)")
    destino = Path(pasta) / nome
    if destino.exists():
        raise SdkError(f"já existe uma pasta '{destino}' — não vou sobrescrever")
    destino.mkdir(parents=True)
    corpo = _MAIN_TEMPLATE.format(nome=nome)
    (destino / "main.py").write_text(corpo)
    manifesto = {
        "name": nome,
        "version": "0.1.0",
        "description": "descreva em uma frase o que esta skill faz",
        "entrypoint": "main.py",
        "entry": "main.py",
        "permissions": ["A0_READ_LOCAL"],
        "risk_level": "baixo",
        "requires_approval": False,
        "publisher": "voce (assine com: nomos skill sign)",
        "compatible_nomos_version": ">=0.11",
        "modalities": ["texto"],
        "local_only_capable": True,
        "cloud_required": False,
        "files": {"main.py": hashlib.sha256(corpo.encode()).hexdigest()},
    }
    problemas = reg.validar_manifesto(manifesto)
    if problemas:   # nunca deve acontecer; proteção contra template quebrado
        raise SdkError("template gerou manifesto inválido: " + "; ".join(problemas))
    (destino / "skill.json").write_text(
        json.dumps(manifesto, indent=2, ensure_ascii=False))
    (destino / "README.md").write_text(_README_TEMPLATE.format(nome=nome))
    return destino
