"""NH-014 — serviço persistente governado: preflight fail-closed, uma
instância só (flock), batimento observável, instalar/remover gated.

Nenhum teste toca o launchd real: `executar` é injetável e o argv é
golden-testado. A prova viva (bootstrap de verdade, kill -9, KeepAlive)
é manual, por decisão de spec.
"""
from __future__ import annotations

import json
import plistlib
import stat
import sys

import pytest

from nomos.kernel import pausa
from nomos.kernel.audit import AuditLog
from nomos.kernel.policy import PolicyEngine
from nomos.runtime import servico as sv


class _AuditFake:
    def __init__(self):
        self.eventos = []

    def append(self, evento, **campos):
        self.eventos.append((evento, campos))


def _ctx(tmp_path, audit=None):
    home = tmp_path / "h"
    home.mkdir(exist_ok=True)
    return {"home": home,
            "policy": PolicyEngine(home / "policy.json"),
            "audit": audit if audit is not None
            else AuditLog(home / "logs" / "audit.jsonl")}


# --------------------------------------------------------------- preflight

def test_precondicoes_home_limpa_ok(tmp_path):
    assert sv.verificar_precondicoes(_ctx(tmp_path)) == []


@pytest.mark.parametrize("lixo", ["[]", "null", "{trunca", '{"rules": []}',
                                  '{"rules": {}}'])
def test_precondicoes_policy_corrompida(tmp_path, lixo):
    ctx = _ctx(tmp_path)
    (ctx["home"] / "policy.json").write_text(lixo)
    problemas = sv.verificar_precondicoes(ctx)
    assert problemas, f"policy {lixo!r} tinha de recusar"
    assert any("policy" in p for p in problemas)


def test_precondicoes_localidade_ilegivel(tmp_path):
    ctx = _ctx(tmp_path)
    (ctx["home"] / "localidade.json").write_text("{quebrado")
    assert any("localidade" in p for p in sv.verificar_precondicoes(ctx))


def test_precondicoes_pausa_ilegivel_nao_recusa(tmp_path):
    """pausa.json ilegível ⇒ sobe PAUSADO; não é motivo para não subir."""
    ctx = _ctx(tmp_path)
    (ctx["home"] / pausa.ARQUIVO).write_text("{lixo")
    assert sv.verificar_precondicoes(ctx) == []


def test_precondicoes_audit_quebrado_recusa(tmp_path):
    class _AuditQuebrado:
        def append(self, *a, **k):
            raise OSError("disco cheio")

    ctx = _ctx(tmp_path, audit=_AuditQuebrado())
    assert any("auditoria" in p for p in sv.verificar_precondicoes(ctx))


# ------------------------------------------------------------------- trava

def test_trava_segunda_instancia_falha(tmp_path):
    t1 = sv.TravaInstancia(tmp_path / "s.lock")
    t2 = sv.TravaInstancia(tmp_path / "s.lock")
    assert t1.adquirir() is True
    assert t2.adquirir() is False, "flock é exclusivo"
    dono = t2.dono()
    assert dono and dono["pid"] > 0
    t1.liberar()
    assert t2.adquirir() is True
    t2.liberar()


def test_trava_inode_trocado_recusa(tmp_path, monkeypatch):
    """Se o arquivo do path foi substituído entre open e flock, recusa."""
    import os as _os
    caminho = tmp_path / "s.lock"
    t = sv.TravaInstancia(caminho)
    stat_real = _os.stat

    def stat_trocado(p, *a, **k):
        r = stat_real(p, *a, **k)
        if str(p) == str(caminho):
            class _S:
                st_ino = r.st_ino + 1
            return _S()
        return r

    monkeypatch.setattr(sv.os, "stat", stat_trocado)
    assert t.adquirir() is False


# --------------------------------------------------------------- batimento

def test_batimento_roundtrip_0600_atomico(tmp_path):
    sv.escrever_batimento(tmp_path, ticks=3, pausado=False)
    b = sv.ler_batimento(tmp_path)
    assert b["ticks"] == 3 and b["ts"] and b["pid"]
    arq = tmp_path / sv.DIR_SERVICO / "batimento.json"
    assert stat.S_IMODE(arq.stat().st_mode) == 0o600
    assert not arq.with_suffix(".tmp").exists()


def test_batimento_ilegivel_e_none(tmp_path):
    d = tmp_path / sv.DIR_SERVICO
    d.mkdir()
    (d / "batimento.json").write_text("{quebrado")
    assert sv.ler_batimento(tmp_path) is None


# ------------------------------------------------------------------- plist

def test_gerar_plist_campos(tmp_path):
    cfg = sv.ConfigServico(raizes=(str(tmp_path / "ws"),), intervalo_s=2.0,
                           painel=True)
    exe = "/opt/homebrew com espaço/bin/python3"
    texto = sv.gerar_plist(tmp_path, exe, cfg)
    dados = plistlib.loads(texto.encode())
    assert dados["Label"] == sv.ROTULO
    assert dados["KeepAlive"] is True and dados["RunAtLoad"] is True
    assert dados["ThrottleInterval"] == 30
    assert dados["EnvironmentVariables"]["NOMOS_HOME"] == str(tmp_path)
    argv = dados["ProgramArguments"]
    assert argv[0] == exe and "servico" in argv and "rodar" in argv
    assert "--raiz" in argv and str(tmp_path / "ws") in argv
    assert "--painel" in argv


def test_gerar_plist_egress_zero(tmp_path):
    texto = sv.gerar_plist(tmp_path, "/usr/bin/python3",
                           sv.ConfigServico(raizes=("/x",)))
    assert "DOCTYPE" not in texto, "precedente rotinas.exportar: sem DOCTYPE"
    assert "http" not in texto


# ------------------------------------------------------- instalar/remover

@pytest.fixture()
def home_falso(tmp_path, monkeypatch):
    """HOME isolado (Path.home() → tmp) + plataforma darwin p/ o fluxo real."""
    monkeypatch.setenv("HOME", str(tmp_path / "casa"))
    (tmp_path / "casa").mkdir()
    monkeypatch.setattr(sys, "platform", "darwin")
    return tmp_path


def test_instalar_simular_zero_efeito(home_falso, tmp_path, capsys):
    ctx = _ctx(tmp_path)
    chamadas = []
    rc = sv.instalar(ctx, sv.ConfigServico(raizes=("/x",)),
                     lambda d: (_ for _ in ()).throw(AssertionError(
                         "simular não pode chegar no gate")),
                     executar=lambda a: chamadas.append(a) or 0, simular=True)
    assert rc == sv.EXIT_OK
    assert chamadas == [], "simular não chama launchctl"
    assert not sv.caminho_plist().exists(), "simular não escreve"
    out = capsys.readouterr().out
    assert "SHA-256" in out and sv.ROTULO in out


def test_instalar_gate_negado_nada_escrito(home_falso, tmp_path, capsys):
    ctx = _ctx(tmp_path)
    chamadas = []
    rc = sv.instalar(ctx, sv.ConfigServico(raizes=("/x",)),
                     lambda d: False,
                     executar=lambda a: chamadas.append(a) or 0)
    assert rc == sv.EXIT_DENIED
    assert chamadas == [] and not sv.caminho_plist().exists()
    registro = ctx["home"] / sv.DIR_SERVICO / "instalado.json"
    assert not registro.exists()


def test_instalar_argv_golden_e_registro(home_falso, tmp_path):
    import os as _os
    ctx = _ctx(tmp_path)
    chamadas = []
    rc = sv.instalar(ctx, sv.ConfigServico(raizes=("/x",)), lambda d: True,
                     executar=lambda a: chamadas.append(list(a)) or 0)
    assert rc == sv.EXIT_OK
    assert chamadas == [["/bin/launchctl", "bootstrap",
                         f"gui/{_os.getuid()}", str(sv.caminho_plist())]]
    assert sv.caminho_plist().exists()
    registro = json.loads((ctx["home"] / sv.DIR_SERVICO /
                           "instalado.json").read_text())
    import hashlib
    assert registro["plist_sha256"] == hashlib.sha256(
        sv.caminho_plist().read_bytes()).hexdigest()


def test_instalar_launchctl_rc1_rollback(home_falso, tmp_path, capsys):
    ctx = _ctx(tmp_path)
    rc = sv.instalar(ctx, sv.ConfigServico(raizes=("/x",)), lambda d: True,
                     executar=lambda a: 1)
    assert rc == sv.EXIT_ERROR
    assert not sv.caminho_plist().exists(), "rollback tinha de remover o plist"
    assert not (ctx["home"] / sv.DIR_SERVICO / "instalado.json").exists()


def test_remover_label_alheio_nao_apaga(home_falso, tmp_path, capsys):
    ctx = _ctx(tmp_path)
    alheio = {"Label": "com.exemplo.outro", "ProgramArguments": ["/bin/true"]}
    sv.caminho_plist().parent.mkdir(parents=True, exist_ok=True)
    sv.caminho_plist().write_bytes(plistlib.dumps(alheio))
    rc = sv.remover(ctx, lambda d: True, executar=lambda a: 0)
    assert rc == sv.EXIT_OK
    assert sv.caminho_plist().exists(), "plist de Label alheio NÃO se apaga"


# ------------------------------------------------------------------ rodar

def _config_ws(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    return sv.ConfigServico(raizes=(str(ws),), intervalo_s=0.01,
                            batimento_s=0.0)


def test_rodar_recusa_policy_corrompida(tmp_path):
    ctx = _ctx(tmp_path)
    (ctx["home"] / "policy.json").write_text("{quebrada")
    rc = sv.rodar_servico(ctx, _config_ws(tmp_path), max_ticks=1,
                          dormir=lambda s: None, aprovador=lambda d: True)
    assert rc == sv.EXIT_DENIED
    bat = sv.ler_batimento(ctx["home"])
    assert bat and bat.get("recusado_subir"), \
        "a recusa tem de ficar visível no batimento (KeepAlive recicla)"


def test_rodar_plist_adulterado_recusa(tmp_path):
    ctx = _ctx(tmp_path)
    d = ctx["home"] / sv.DIR_SERVICO
    d.mkdir(parents=True)
    plist = tmp_path / "s.plist"
    plist.write_text("original")
    (d / "instalado.json").write_text(json.dumps(
        {"plist": str(plist), "plist_sha256": "0" * 64}))
    rc = sv.rodar_servico(ctx, _config_ws(tmp_path), max_ticks=1,
                          dormir=lambda s: None, aprovador=lambda d: True)
    assert rc == sv.EXIT_DENIED


def test_rodar_instancia_duplicada(tmp_path):
    ctx = _ctx(tmp_path)
    trava = sv.TravaInstancia(sv._dir(ctx["home"]) / "servico.lock")
    assert trava.adquirir()
    try:
        rc = sv.rodar_servico(ctx, _config_ws(tmp_path), max_ticks=1,
                              dormir=lambda s: None, aprovador=lambda d: True)
        assert rc == sv.EXIT_ERROR
    finally:
        trava.liberar()


def test_rodar_smoke_batimento_e_audit(tmp_path):
    ctx = _ctx(tmp_path)
    rc = sv.rodar_servico(ctx, _config_ws(tmp_path), max_ticks=3,
                          dormir=lambda s: None, aprovador=lambda d: True)
    assert rc == sv.EXIT_OK
    bat = sv.ler_batimento(ctx["home"])
    assert bat and bat.get("encerrado") is True and bat["ticks"] == 3
    eventos = [json.loads(x).get("event") for x in
               (ctx["home"] / "logs" / "audit.jsonl").read_text().splitlines()]
    assert "servico.iniciado" in eventos and "servico.encerrado" in eventos
    # a trava foi liberada no fim: dá para readquirir
    t = sv.TravaInstancia(ctx["home"] / sv.DIR_SERVICO / "servico.lock")
    assert t.adquirir()
    t.liberar()


def test_rodar_nasce_pausado_e_nao_executa(tmp_path):
    """Restart com pausa.json presente: o serviço sobe, mas PAUSADO."""
    ctx = _ctx(tmp_path)
    pausa.pausar(ctx["home"], motivo="antes do restart")
    rc = sv.rodar_servico(ctx, _config_ws(tmp_path), max_ticks=2,
                          dormir=lambda s: None, aprovador=lambda d: True)
    assert rc == sv.EXIT_OK
    bat = sv.ler_batimento(ctx["home"])
    assert bat["pausado"] is True and bat["executadas"] == 0


# ------------------------------------------------------------------ status

def test_diagnostico_parado_e_sem_instalacao(tmp_path):
    ctx = _ctx(tmp_path)
    d = sv.diagnostico(ctx)
    assert d["instalado"] is False and d["rodando"] is False
    assert d["problemas"] == []


def test_diagnostico_batimento_forjado_nao_prova_vida(tmp_path):
    """Batimento fresco SEM flock ⇒ não está rodando (verdade = flock)."""
    ctx = _ctx(tmp_path)
    sv.escrever_batimento(ctx["home"], ticks=1, intervalo_s=999.0)
    d = sv.diagnostico(ctx)
    assert d["batimento_fresco"] is True
    assert d["rodando"] is False
