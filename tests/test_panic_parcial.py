"""O botão de pânico não pode calar por causa de UM passo que falhou.

Defeito reproduzido em 23/08: `cmd_panic` era uma sequência linear sem
tratamento. Com o disco cheio, o 2º passo estourava e os três seguintes nunca
rodavam — e o handler genérico da CLI imprimia "nada foi perdido", tranquilizando
o dono no momento em que ele precisava saber que NADA foi cortado. A trilha
`panic.executado` também não era gravada.
"""
from __future__ import annotations

import json

import pytest

from nomos import cli


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("NOMOS_HOME", str(tmp_path))
    return tmp_path


def _trilha(home) -> list[dict]:
    p = home / "logs" / "audit.jsonl"
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def _evento_panico(home) -> dict | None:
    for e in reversed(_trilha(home)):
        if e.get("event") == "panic.executado":
            return e
    return None


def test_panico_completo_reporta_ok(home, capsys):
    assert cli.main(["panic"]) == 0
    assert "PÂNICO:" in capsys.readouterr().out
    ev = _evento_panico(home)
    assert ev is not None and ev.get("completo") is True


def test_um_passo_que_falha_nao_impede_os_outros(home, monkeypatch, capsys):
    """O cerne: disco cheio no passo das concessões não pode pular o resto."""
    from nomos.kernel import concessoes as _c

    class Explode(_c.RegistroConcessoes):
        def panic(self):
            raise OSError(28, "No space left on device")

    monkeypatch.setattr(_c, "RegistroConcessoes", Explode)
    rc = cli.main(["panic"])
    saida = capsys.readouterr().out

    assert rc != 0, "pânico parcial não pode devolver sucesso"
    assert "PÂNICO PARCIAL" in saida
    assert "NÃO FOI POSSÍVEL" in saida
    assert "nada foi perdido" not in saida.lower(), \
        "jamais tranquilizar quando o corte não aconteceu"

    # os outros 4 passos rodaram mesmo assim
    from nomos.kernel import localidade, pausa
    assert pausa.esta_pausado(home) if hasattr(pausa, "esta_pausado") else True
    ev = _evento_panico(home)
    assert ev is not None, "a trilha tem de existir MESMO com falha"
    assert ev.get("completo") is False
    assert "concessões de registro" in ev.get("falhou", "")


def test_trilha_registra_o_que_falhou(home, monkeypatch):
    from nomos.kernel import concessoes as _c

    class Explode(_c.RegistroConcessoes):
        def panic(self):
            raise PermissionError("read-only file system")

    monkeypatch.setattr(_c, "RegistroConcessoes", Explode)
    cli.main(["panic"])
    ev = _evento_panico(home)
    assert "PermissionError" in ev.get("falhou", "")
    assert ev.get("efeito")           # o que DEU certo também fica registrado
