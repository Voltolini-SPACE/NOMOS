"""FIX-02 — as capacidades Git governadas ganham porta no CLI.

MEDIDO antes desta correção: `RuntimeGovernado.__init__` aceita `git=`,
`git_write=`, `git_tree=` e `git_push_destinos=`, e NENHUM dos dois callers de
produção passava qualquer um deles — `cli.py` (comando `orquestrar`) e
`runtime/agendador.py`. As quatro famílias (C1 leitura, C2a tag, C2b push,
C2c add/commit) existiam como biblioteca testada e eram inalcançáveis por quem
usa o produto.

É o defeito que o próprio comentário de `governado.py` nomeia: "a forma mais
silenciosa de falso fechamento desta série, porque a suíte ficava verde o
tempo todo".

## Por que `--git-push` NÃO liga a capacidade

`DestinoGovernado` é explícito — "o destino que a POLÍTICA autoriza; não vem do
repositório nem do plano" — e `registrar_git_push` recusa sem `destinos`. Mas o
`policy.json` de hoje só conhece a chave `rules`: não existe lugar governado
onde declarar destino de push. Aceitar URL no argv moveria a decisão da
política para a linha de comando, que é o inverso exato do contrato. Então a
flag existe e NEGA na porta com a verdade — mesmo padrão do `--executavel`
selado (FIX-03), e pelo mesmo motivo: erro tardio vestido de defeito interno é
UX enganosa.
"""
from __future__ import annotations

import pytest

from nomos import cli
from nomos.runtime import governado


@pytest.fixture()
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("NOMOS_HOME", str(h))
    return h


# ------------------------------------------------ a porta existe no parser

@pytest.mark.parametrize("flag", ["--git", "--git-tag", "--git-tree", "--git-push"])
def test_flag_git_e_reconhecida_pelo_parser(home, tmp_path, capsys, flag):
    """Antes desta correção o argparse morria com 'unrecognized arguments'.

    Não afirma que a capacidade funciona — afirma que existe PORTA. É o que
    separa "capacidade que o usuário consegue pedir" de código inalcançável.
    O SystemExit(2) do argparse é o vermelho que esta correção elimina.
    """
    try:
        cli.main(["orquestrar", "objetivo", "--raiz", str(tmp_path), flag])
    except SystemExit as saida:                       # argparse aborta com 2
        assert saida.code != 2, f"{flag} não é reconhecida pelo parser"
    err = capsys.readouterr().err
    assert "unrecognized arguments" not in err


# ------------------------------------------ confinamento: exigem --raiz

@pytest.mark.parametrize("flag", ["--git", "--git-tag", "--git-tree"])
def test_capacidade_git_sem_raiz_e_recusada(home, capsys, flag):
    """Sem escopo de caminho a capacidade seria MENOS confinada que o git nu.

    Mesmo contrato de `--adapters` e `--scheduler`: raiz é o escopo do PDP.
    """
    rc = cli.main(["orquestrar", "objetivo", flag])
    err = capsys.readouterr().err
    assert rc == cli.EXIT_ERROR
    assert "--raiz" in err


# ------------------------------------- push nega na porta, com a verdade

def test_git_push_nega_na_porta_e_nomeia_a_politica(home, tmp_path, capsys):
    """A flag não pode ligar a capacidade nem fingir que não existe.

    A mensagem tem de nomear a POLÍTICA: um "indisponível" seco mandaria o
    usuário procurar defeito no lugar errado — no repositório ou no plano,
    que são exatamente as duas fontes que o contrato proíbe.
    """
    rc = cli.main(["orquestrar", "objetivo", "--raiz", str(tmp_path), "--git-push"])
    err = capsys.readouterr().err
    assert rc == cli.EXIT_DENIED
    assert "polít" in err.lower()


def test_git_push_nega_antes_de_qualquer_outra_validacao(home, capsys):
    """Sem `--raiz` a negação do push ainda é a primeira verdade.

    Espelha `test_orquestrar_executavel_nega_mesmo_sem_adapters`: a porta
    fechada vem antes da combinação de flags, não depois.
    """
    rc = cli.main(["orquestrar", "objetivo", "--git-push"])
    assert rc == cli.EXIT_DENIED


# ---------------------------------- as três alcançáveis chegam ao runtime

@pytest.mark.parametrize("flag,parametro", [
    ("--git", "git"),
    ("--git-tag", "git_write"),
    ("--git-tree", "git_tree"),
])
def test_flag_chega_ao_RuntimeGovernado(home, tmp_path, monkeypatch, flag, parametro):
    """O que este teste protege é o FIO, não a capacidade.

    A capacidade em si já tem bateria própria (absorption07). O que nunca teve
    teste — e por isso apodreceu — é o trecho entre a flag e o construtor.
    Intercepta `RuntimeGovernado` para ler os kwargs recebidos e não depende de
    `sandbox-exec`: assim vale nos 3 SO da matriz, inclusive onde a capacidade
    é indisponível por desenho.
    """
    vistos = {}

    class RuntimeEspiao:
        capacidades_adapter = ()

        def __init__(self, *a, **kw):
            vistos.update(kw)

        def planejar(self, *a, **kw):
            raise SystemExit(0)                       # corta antes do efeito

    # No módulo de ORIGEM: `cmd_orquestrar` faz o import dentro da função, então
    # o nome é resolvido a cada chamada e trocá-lo em `cli` não teria efeito.
    monkeypatch.setattr(governado, "RuntimeGovernado", RuntimeEspiao)
    with pytest.raises(SystemExit):
        cli.main(["orquestrar", "objetivo", "--raiz", str(tmp_path), flag])

    assert vistos.get(parametro) is True, (
        f"{flag} não chegou ao RuntimeGovernado como {parametro}=True; "
        f"recebidos: {sorted(k for k, v in vistos.items() if v)}")


def test_sem_flag_nenhuma_capacidade_git_e_ligada(home, tmp_path, monkeypatch):
    """Fail-closed: o padrão continua sendo NADA de Git.

    Sem esta asserção, ligar as quatro por engano passaria despercebido — o
    teste acima só olha o caminho positivo.
    """
    vistos = {}

    class RuntimeEspiao:
        capacidades_adapter = ()

        def __init__(self, *a, **kw):
            vistos.update(kw)

        def planejar(self, *a, **kw):
            raise SystemExit(0)

    # No módulo de ORIGEM: `cmd_orquestrar` faz o import dentro da função, então
    # o nome é resolvido a cada chamada e trocá-lo em `cli` não teria efeito.
    monkeypatch.setattr(governado, "RuntimeGovernado", RuntimeEspiao)
    with pytest.raises(SystemExit):
        cli.main(["orquestrar", "objetivo", "--raiz", str(tmp_path)])

    for parametro in ("git", "git_write", "git_tree"):
        assert not vistos.get(parametro), f"{parametro} ligada sem flag"
    assert not vistos.get("git_push_destinos")
