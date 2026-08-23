"""O painel recusa Host forjado (DNS rebinding) e POST de origem cruzada.

Medido antes do conserto: `curl -H "Host: evil.example.com"` na URL secreta
devolvia 200, idêntico ao Host legítimo — e nenhuma linha do painel lia
Host, Origin ou Referer.
"""
from __future__ import annotations

import pytest

from nomos.interface import painel_web as pw


@pytest.mark.parametrize("host", [
    "127.0.0.1", "127.0.0.1:8795", "localhost", "localhost:8795",
    "[::1]", "[::1]:8795", "::1",
])
def test_hosts_de_loopback_passam(host):
    assert pw._host_aceito(host) is True


@pytest.mark.parametrize("host", [
    "evil.example.com", "attacker.test", "evil.example.com:8795",
    "nomos.local", "192.168.68.81:8795", "127.0.0.1.evil.com", "",
    None, "  ", "localhost.evil.com",
])
def test_hosts_forjados_recusados(host):
    assert pw._host_aceito(host) is False, f"aceitou {host!r}"


def test_host_ausente_e_recusado():
    """HTTP/1.1 sem Host é malformado — e é o jeito mais fácil de escapar
    de uma checagem escrita com descuido."""
    assert pw._host_aceito(None) is False


@pytest.mark.parametrize("origin", [
    None, "", "null",                              # cliente não-navegador
    "http://127.0.0.1:8795", "http://localhost:8795", "http://[::1]:8795",
])
def test_origens_aceitas(origin):
    assert pw._origem_aceita(origin, None) is True


@pytest.mark.parametrize("origin", [
    "https://evil.example.com", "http://evil.example.com:8795",
    "https://127.0.0.1.evil.com", "http://192.168.68.81:8795",
])
def test_origens_cruzadas_recusadas(origin):
    assert pw._origem_aceita(origin, None) is False, f"aceitou {origin}"


def test_referer_serve_de_reserva_quando_nao_ha_origin():
    assert pw._origem_aceita(None, "https://evil.example.com/x") is False
    assert pw._origem_aceita(None, "http://127.0.0.1:8795/d/x/") is True


def test_origin_vence_o_referer():
    """Se os dois vierem, o Origin é o que vale (é o não-forjável)."""
    assert pw._origem_aceita("https://evil.com", "http://127.0.0.1:8795/") is False


def test_ausencia_de_origin_e_deliberada():
    """Documenta a decisão: curl/script do dono não é vetor de CSRF, porque
    uma página hostil não consegue OMITIR o Origin do navegador."""
    assert pw._origem_aceita(None, None) is True
