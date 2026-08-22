"""NH-019 — medição de uso de motor: SÓ metadados, nunca conteúdo.

Providers falsos, zero rede. As invariantes duras: o medidor jamais derruba
o chat; nenhum campo de conteúdo (CAMPOS_PROIBIDOS) aparece em disco; tokens
só quando o backend devolveu (nunca zero inventado).
"""
from __future__ import annotations

import json
import stat

from nomos import cli
from nomos.cognition import uso_motores as um
from nomos.cognition.providers import ChatReply, ProviderUnavailable
from nomos.cognition.router import Router
from nomos.kernel.audit import AuditLog
from nomos.kernel.policy import PolicyEngine, gate
from nomos.kernel.vault import Vault
import pytest

SENTINELA = "conteudo-secreto-do-prompt-9f8e7d"


class _OllamaVivo:
    host = "http://127.0.0.1:11434"

    def __init__(self, tokens=True, falhar=False):
        self.tokens = tokens
        self.falhar = falhar

    def available(self):
        return True

    def chat(self, messages):
        if self.falhar:
            raise ProviderUnavailable(f"eco perigoso: {messages[-1]['content']}")
        return ChatReply(text="resposta ok", provider="ollama", model="m1",
                         tokens_prompt=310 if self.tokens else None,
                         tokens_resposta=162 if self.tokens else None)


class _OllamaMorto:
    host = "http://127.0.0.1:11434"

    def available(self):
        return False

    def chat(self, messages):
        raise AssertionError("não deveria ser chamado")


def _router(home, ollama, uso):
    return Router(policy=PolicyEngine(home / "policy.json"), gate=gate,
                  approver=lambda d: False,
                  audit=AuditLog(home / "logs" / "audit.jsonl"),
                  vault=Vault(home / "vault.json"), ollama=ollama, uso=uso)


def _linhas(home):
    p = home / um.ARQUIVO
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text().splitlines()]


def _msgs():
    return [{"role": "user", "content": SENTINELA}]


# ------------------------------------------------------------------- rotas

def test_uso_registra_chat_local_com_duracao_e_chars(nomos_home):
    r = _router(nomos_home, _OllamaVivo(), um.MedidorUso(nomos_home))
    out = r.chat(_msgs())
    assert out.ok
    (ev,) = _linhas(nomos_home)
    assert ev["origem"] == "chat" and ev["rota"] == "local" and ev["ok"]
    assert ev["motor"] == "ollama" and ev["modelo"] == "m1"
    assert ev["dur_ms"] >= 0
    assert ev["chars_prompt"] == len(SENTINELA)
    assert ev["chars_resposta"] == len("resposta ok")


def test_uso_registra_tokens_quando_backend_devolve(nomos_home):
    r = _router(nomos_home, _OllamaVivo(tokens=True), um.MedidorUso(nomos_home))
    r.chat(_msgs())
    (ev,) = _linhas(nomos_home)
    assert ev["tokens_prompt"] == 310 and ev["tokens_resposta"] == 162


def test_uso_sem_tokens_quando_backend_nao_devolve(nomos_home):
    r = _router(nomos_home, _OllamaVivo(tokens=False), um.MedidorUso(nomos_home))
    r.chat(_msgs())
    (ev,) = _linhas(nomos_home)
    assert ev["tokens_prompt"] is None and ev["tokens_resposta"] is None, \
        "sem usage do backend = None, nunca zero inventado"


def test_uso_stream_registra_uma_linha_sem_tokens(nomos_home):
    r = _router(nomos_home, _OllamaVivo(), um.MedidorUso(nomos_home))
    pedacos = []
    out = r.chat_stream(_msgs(), pedacos.append)
    assert out.ok and pedacos
    (ev,) = _linhas(nomos_home)
    assert ev["origem"] == "chat_stream" and ev["tokens_prompt"] is None


def test_uso_registra_falha_com_classe_sem_mensagem(nomos_home):
    r = _router(nomos_home, _OllamaVivo(falhar=True), um.MedidorUso(nomos_home))
    r.chat(_msgs())
    eventos = _linhas(nomos_home)
    falha = next(e for e in eventos if not e["ok"] and e.get("erro"))
    assert falha["erro"] == "ProviderUnavailable"
    bruto = (nomos_home / um.ARQUIVO).read_text()
    assert SENTINELA not in bruto, \
        "mensagem de exceção pode ecoar prompt — só o NOME da classe entra"


def test_uso_registra_rota_degradada_ok_false(nomos_home):
    r = _router(nomos_home, _OllamaMorto(), um.MedidorUso(nomos_home))
    out = r.chat(_msgs())
    assert not out.ok
    eventos = _linhas(nomos_home)
    assert any(e["rota"] == "degradada" and not e["ok"] for e in eventos)


# --------------------------------------------------------------- higiene

def test_uso_zero_conteudo_de_prompt_sentinela(nomos_home):
    r = _router(nomos_home, _OllamaVivo(), um.MedidorUso(nomos_home))
    r.chat(_msgs())
    bruto = (nomos_home / um.ARQUIVO).read_text()
    assert SENTINELA not in bruto
    for ev in _linhas(nomos_home):
        for proibido in um.CAMPOS_PROIBIDOS:
            assert proibido not in ev, f"campo proibido em disco: {proibido}"


@pytest.mark.permissao_unix
def test_uso_arquivo_0600_e_rotaciona_por_tamanho(nomos_home, monkeypatch):
    monkeypatch.setattr(um, "TAMANHO_MAX", 120)
    medidor = um.MedidorUso(nomos_home)
    r = _router(nomos_home, _OllamaVivo(), medidor)
    for _ in range(4):
        r.chat(_msgs())
    arquivo = nomos_home / um.ARQUIVO
    assert stat.S_IMODE(arquivo.stat().st_mode) == 0o600
    assert arquivo.with_suffix(".jsonl.1").exists(), "rotação por tamanho"
    # `ler` cobre a geração rotacionada também
    assert len(medidor.ler(dias=1)) >= 2


def test_uso_medidor_quebrado_nao_derruba_chat(nomos_home, tmp_path):
    trava = tmp_path / "arquivo-nao-dir"
    trava.write_text("x")                     # 'home' que não aceita mkdir
    r = _router(nomos_home, _OllamaVivo(), um.MedidorUso(trava / "sub"))
    out = r.chat(_msgs())
    assert out.ok, "métrica quebrada JAMAIS derruba o chat"


def test_uso_none_desliga_medicao(nomos_home):
    r = _router(nomos_home, _OllamaVivo(), None)
    assert r.chat(_msgs()).ok
    assert not (nomos_home / um.ARQUIVO).exists()


def test_chatreply_campos_novos_tem_default():
    r = ChatReply(text="t", provider="p", model="m")
    assert r.tokens_prompt is None and r.tokens_resposta is None


# ------------------------------------------------------------ arbitragem

def test_uso_arbitragem_um_evento_por_runner_por_tentativa(nomos_home):
    from nomos.cognition.arbitragem import arbitrar

    class _Runner:
        def __init__(self, eid):
            self.engine_id = eid
            self.local = True

        def available(self):
            return True

        def run(self, prompt, system=""):
            return f"resposta determinística de {self.engine_id}"

    medidor = um.MedidorUso(nomos_home)
    arbitrar(SENTINELA, [_Runner("a"), _Runner("b")], rounds=1,
             min_candidatos=2, uso=medidor)
    eventos = [e for e in _linhas(nomos_home) if e["origem"] == "arbitragem"]
    assert {e["motor"] for e in eventos} == {"a", "b"}
    assert all(e["rota"] == "local" for e in eventos)
    assert SENTINELA not in (nomos_home / um.ARQUIVO).read_text()


# --------------------------------------------------------------------- CLI

def test_cli_motores_uso_agrega_por_dia_motor_modalidade(nomos_home,
                                                         monkeypatch, capsys):
    monkeypatch.setenv("NOMOS_HOME", str(nomos_home))
    medidor = um.MedidorUso(nomos_home)
    import time as _t
    agora = _t.time()
    for motor, ok in (("ollama", True), ("ollama", True), ("embutido", False)):
        medidor.registrar(um.EventoUso(
            ts=agora, origem="chat", motor=motor, modelo="m",
            modalidade="texto", rota="local", ok=ok, dur_ms=10,
            chars_prompt=5, chars_resposta=7,
            erro="" if ok else "ProviderUnavailable"))
    assert cli.main(["motores", "uso", "--json"]) == cli.EXIT_OK
    saida = json.loads(capsys.readouterr().out)
    dia = next(iter(saida))
    assert saida[dia]["ollama"]["texto"]["n"] == 2
    assert saida[dia]["ollama"]["texto"]["ok"] == 2
    assert saida[dia]["embutido"]["texto"]["erros"] == 1
    capsys.readouterr()
    assert cli.main(["motores", "uso"]) == cli.EXIT_OK
    assert "ollama" in capsys.readouterr().out
