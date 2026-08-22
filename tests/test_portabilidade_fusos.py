"""Portabilidade — a base de fusos IANA tem de existir em TODA plataforma.

Windows não traz base de fusos do sistema. O `zoneinfo` da stdlib procura
primeiro nos diretórios do SO (`/usr/share/zoneinfo` e vizinhos) e, só se não
achar, cai no pacote **tzdata** do PyPI. Em Linux e macOS o primeiro caminho
resolve e o pacote nunca faz falta; no Windows não existe primeiro caminho.

Sem `tzdata` declarado, portanto, NENHUMA timezone resolve no Windows — nem
`UTC`. E como `resolver_tz` é o portão de toda a agenda, o efeito não é um
teste frágil: é o scheduler inteiro do NOMOS indisponível na plataforma para a
qual o repositório publica `install.ps1` e o README promete suporte.

MEDIDO no CI (windows-latest · py3.12, run 32517699401): das 214 falhas com
bloco de rastro, **105** eram esta causa — a maior fatia isolada, quase o dobro
de todas as suposições de shell POSIX somadas.

Por que o teste roda em qualquer plataforma: `reset_tzpath([])` remove os
diretórios do SO da busca, que é exatamente a condição do Windows. Em macOS e
Linux isso reproduz a falha de verdade — não é simulação por mock, é a mesma
resolução de fuso do produto rodando sem a base do sistema.
"""
from __future__ import annotations

import re
import zoneinfo
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from nomos.adapters.agenda import resolver_tz

# Os três que aparecem literalmente na mensagem de erro de `resolver_tz` como
# exemplos válidos. Se a mensagem oferece o identificador, ele tem de resolver.
FUSOS_PROMETIDOS = ("UTC", "America/Sao_Paulo", "Europe/Madrid")

_PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


@pytest.fixture
def sem_base_de_fusos_do_sistema():
    """Deixa o `zoneinfo` sem os diretórios do SO — a condição do Windows.

    Restaura em `finally` e limpa o cache nos DOIS sentidos: o cache é global
    por nome e um fuso resolvido antes do teste continuaria resolvendo depois
    da troca do caminho, escondendo a falha que queremos medir.
    """
    ZoneInfo.clear_cache()
    zoneinfo.reset_tzpath([])
    try:
        yield
    finally:
        zoneinfo.reset_tzpath()
        ZoneInfo.clear_cache()


@pytest.mark.parametrize("nome", FUSOS_PROMETIDOS)
def test_fuso_resolve_sem_base_do_sistema(nome, sem_base_de_fusos_do_sistema):
    """Sem base do SO, `resolver_tz` ainda entrega o fuso — via pacote tzdata.

    Este é o teste que falha hoje: sem `tzdata` nas dependências, o
    `ZoneInfoNotFoundError` vira `ErroInvalido('timezone desconhecida')` e a
    agenda recusa qualquer job.
    """
    assert isinstance(resolver_tz(nome), ZoneInfo)


def test_fuso_inexistente_continua_recusado(sem_base_de_fusos_do_sistema):
    """Guarda contra a correção preguiçosa.

    Instalar `tzdata` não pode transformar `resolver_tz` num "aceita tudo": a
    recusa explícita de identificador desconhecido é a propriedade que o
    docstring do produto promete ("DENY explícito, nunca fallback silencioso").
    Sem esta asserção, trocar o corpo de `resolver_tz` por um `return UTC`
    deixaria os testes acima verdes.
    """
    from nomos.adapters.contrato import ErroInvalido

    with pytest.raises(ErroInvalido, match="timezone desconhecida"):
        resolver_tz("Marte/Olympus_Mons")


try:
    import tomllib
except ModuleNotFoundError:          # py3.10 — `tomllib` só entrou na 3.11
    tomllib = None


def _dependencias_declaradas() -> list[str]:
    """Array `dependencies` do pyproject, exato onde dá e adequado onde não dá.

    O projeto declara `requires-python = ">=3.10"` e `tomllib` só existe a
    partir da 3.11, então a versão mais antiga da matriz cai numa varredura das
    strings do array. Ela precisa aceitar os DOIS estilos de aspas do TOML: o
    marcador de plataforma contém aspas duplas (`sys_platform == "win32"`) e
    por isso a entrada é escrita com aspas simples — um regex que só enxergasse
    aspas duplas leria `win32` como se fosse o nome de um pacote.
    """
    texto = _PYPROJECT.read_text(encoding="utf-8")
    if tomllib is not None:
        return tomllib.loads(texto)["project"]["dependencies"]
    bloco = re.search(r"^dependencies\s*=\s*\[(.*?)\]", texto, re.S | re.M)
    assert bloco, "pyproject.toml sem array `dependencies`"
    return [simples or duplas for simples, duplas
            in re.findall(r"'([^']*)'|\"([^\"]*)\"", bloco.group(1))]


def test_tzdata_declarado_como_dependencia_de_windows():
    """Sentinela mecânica: a dependência não pode sumir sem alguém notar.

    O teste de comportamento acima só fica vermelho onde `tzdata` não está
    instalado. Numa máquina que o receba por tabela (outro pacote o arrasta),
    ele passaria por vácuo e a regressão chegaria ao usuário do Windows. Esta
    asserção olha a DECLARAÇÃO, que é o que de fato viaja no wheel.
    """
    tz = [d for d in _dependencias_declaradas() if d.split(";")[0].strip() == "tzdata"]
    assert tz, ("`tzdata` não está em [project].dependencies — sem ela o "
                "zoneinfo não tem base de fusos no Windows")
    assert 'sys_platform == "win32"' in tz[0], (
        f"`tzdata` deve ser condicionada ao Windows, não instalada em toda "
        f"plataforma (Linux e macOS já têm base do SO): {tz[0]!r}")
