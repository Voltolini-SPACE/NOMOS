"""ORQUESTRA-02 — o fio: NH-015/NH-009 alcançáveis por `nomos orquestrar`.

A lição do FIX-02, aplicada de ofício desta vez: capacidade que nenhum caller
de produção alcança é falso fechamento — a suíte fica verde e o usuário não
tem nada. `max_paralelo`, `checkpoint` e a transcrição ao vivo nasceram no
Orquestrador; este arquivo fixa que existe PORTA até eles.

(NH-021 não precisa de porta: a guarda é default-on por construção.)
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


class OrquestradorEspiao:
    """Captura os kwargs com que o runtime constrói o Orquestrador."""

    vistos: dict = {}

    def __init__(self, *a, **kw):
        type(self).vistos = dict(kw)
        self._real = governado.Orquestrador  # não usado; só marca a captura

    def executar(self, grafo, checkpoint=None):
        type(self).vistos["_checkpoint_recebido"] = checkpoint
        from nomos.orquestracao.grafo import ResultadoMissao
        return ResultadoMissao(ok=True, nos={}, ordem=())


# ------------------------------------------------- as flags têm porta

@pytest.mark.parametrize("flag", ["--paralelo", "--checkpoint"])
def test_flag_e_reconhecida_pelo_parser(home, tmp_path, capsys, flag):
    """Antes do fio: 'unrecognized arguments' (SystemExit 2)."""
    argv = ["orquestrar", "objetivo", flag,
            "2" if flag == "--paralelo" else str(tmp_path / "m.ckpt")]
    try:
        cli.main(argv)
    except SystemExit as saida:
        assert saida.code != 2, f"{flag} não é reconhecida pelo parser"
    err = capsys.readouterr().err
    assert "unrecognized arguments" not in err


# --------------------------------------- os valores chegam ao Orquestrador

def _rodar_espiao(monkeypatch, tmp_path, *argv_extra):
    import json

    monkeypatch.setattr(governado, "Orquestrador", OrquestradorEspiao)
    OrquestradorEspiao.vistos = {}
    passos = json.dumps([{"id": "a", "ferramenta": "arquivo_ler",
                          "params": {"alvo": str(tmp_path / "x.txt")},
                          "depende_de": []}])
    (tmp_path / "x.txt").write_text("oi", encoding="utf-8")
    return cli.main(["orquestrar", "ler arquivo", "--passos", passos,
                     "--executar", *argv_extra])


def test_paralelo_chega_ao_orquestrador(home, tmp_path, monkeypatch):
    _rodar_espiao(monkeypatch, tmp_path, "--paralelo", "3")
    assert OrquestradorEspiao.vistos.get("max_paralelo") == 3, (
        f"kwargs vistos: {sorted(OrquestradorEspiao.vistos)}")


def test_checkpoint_chega_ao_executar(home, tmp_path, monkeypatch):
    caminho = tmp_path / "missao.ckpt"
    _rodar_espiao(monkeypatch, tmp_path, "--checkpoint", str(caminho))
    ck = OrquestradorEspiao.vistos.get("_checkpoint_recebido")
    assert ck is not None, "checkpoint não chegou ao executar()"
    from nomos.orquestracao.checkpoint import CheckpointMissao
    assert isinstance(ck, CheckpointMissao)
    assert ck.caminho == caminho


def test_sem_flags_o_padrao_continua_serial_e_sem_checkpoint(home, tmp_path,
                                                             monkeypatch):
    """Anti-regressão do fio: quem não pediu nada recebe o de sempre."""
    _rodar_espiao(monkeypatch, tmp_path)
    assert OrquestradorEspiao.vistos.get("max_paralelo", 1) == 1
    assert OrquestradorEspiao.vistos.get("_checkpoint_recebido") is None


def test_transcricao_ao_vivo_liga_com_executar(home, tmp_path, monkeypatch):
    """Com `--executar`, o runtime entrega um `ao_evento` de verdade ao
    Orquestrador — é o que faz a transcrição existir para o usuário."""
    _rodar_espiao(monkeypatch, tmp_path)
    assert callable(OrquestradorEspiao.vistos.get("ao_evento")), (
        "ao_evento não chegou ao Orquestrador — transcrição inalcançável")


# ----------------------------------------------------- validação na porta

def test_paralelo_invalido_nega_na_porta(home, capsys):
    rc = cli.main(["orquestrar", "objetivo", "--paralelo", "0"])
    err = capsys.readouterr().err
    assert rc == cli.EXIT_ERROR
    assert "paralelo" in err.lower()
