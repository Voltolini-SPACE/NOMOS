"""A suíte é HERMÉTICA: teste unitário NÃO alcança o motor real da máquina.

Medido no hardening (24/08): antes do guard do conftest, dois testes "sem
motor" fizeram 6 conexões reais (4× 127.0.0.1:11434, 2× :1234) e só passavam
porque `llama3.2` não estava instalado no Ollama vivo — instalar um modelo
mudaria o veredito de testes unitários. Estes testes tentam ESCAPAR de
propósito e provam que o guard bloqueia no socket, antes do daemon:
REAL_OLLAMA_CALLS=0 por construção (o guard levanta em vez de conectar).
Integração de verdade é opt-in via @pytest.mark.motor_real.
"""
from __future__ import annotations

import pytest

from nomos import cli
from nomos.cognition.providers import OllamaProvider, ProviderUnavailable


def test_available_nao_alcanca_o_daemon_real(_sem_motor_real, monkeypatch):
    monkeypatch.setenv("NOMOS_OLLAMA_MODEL", "llama3.2")
    p = OllamaProvider(model="llama3.2")
    assert p.available() is False          # guard nega; nunca sondou de verdade
    assert _sem_motor_real and all(t[1] == 11434 for t in _sem_motor_real)
    _sem_motor_real.clear()                # tentativas eram o PONTO do teste


def test_chat_nao_alcanca_o_daemon_real(_sem_motor_real):
    p = OllamaProvider(model="qwen3.5:4b-q8_0")   # até um modelo que EXISTE
    with pytest.raises(ProviderUnavailable):      # guard vira "falha de conexão"
        p.chat([{"role": "user", "content": "oi"}])
    assert _sem_motor_real and all(t[1] == 11434 for t in _sem_motor_real)
    _sem_motor_real.clear()


def test_router_local_first_inteiro_nao_escapa(_sem_motor_real, monkeypatch,
                                               tmp_path):
    """O pior caso: cadeia local-first COMPLETA do CLI, com env adversarial
    apontando um modelo real. Nenhum socket chega às portas dos motores."""
    monkeypatch.setenv("NOMOS_HOME", str(tmp_path))
    monkeypatch.setenv("NOMOS_OLLAMA_MODEL", "llama3.2")
    router = cli._router(cli._paths())
    assert router.ollama.model == "llama3.2"       # o env valeu (sem perfil)
    outcome = router._try_local([{"role": "user", "content": "oi"}])
    assert outcome is None                          # nenhum motor "pronto"
    portas = {t[1] for t in _sem_motor_real}
    assert portas and portas <= {11434, 1234}       # tentou e foi bloqueado
    _sem_motor_real.clear()


def test_motores_ausentes_nem_tenta(_sem_motor_real, motores_ausentes,
                                    monkeypatch, tmp_path):
    """A fixture `motores_ausentes` declara indisponível NA CAMADA do provider:
    zero tentativas de socket — é o jeito certo de testar caminho degradado."""
    monkeypatch.setenv("NOMOS_HOME", str(tmp_path))
    router = cli._router(cli._paths())
    assert router._try_local([{"role": "user", "content": "oi"}]) is None
    assert _sem_motor_real == []                    # REAL_OLLAMA_CALLS=0
