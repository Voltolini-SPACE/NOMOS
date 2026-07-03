"""Ciclo Fortaleza Local — prova estática: nenhum destino externo escondido."""
import re
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "nomos"


def _fontes():
    return list(SRC.rglob("*.py"))


def test_unico_destino_externo_e_a_nuvem_opcional():
    """Toda URL http(s) hardcoded no código ou é loopback ou é o motor de
    nuvem opcional (api.anthropic.com) — que fica atrás do cadeado só-local."""
    url_re = re.compile(r"https?://([A-Za-z0-9.\-]+)")
    externos = set()
    for f in _fontes():
        for host in url_re.findall(f.read_text()):
            if host in {"127.0.0.1", "localhost", "0.0.0.0"} or "." not in host:
                continue                     # loopback ou placeholder de doc
            externos.add(host)
    permitidos = {"api.anthropic.com",   # nuvem opcional (atrás do cadeado)
                  "huggingface.co",      # baixar o cérebro embutido (opt-in consciente)
                  "api.github.com",      # v0.12: `nomos atualizar` (atrás do gate A2)
                  "github.com"}          # v0.12: URL humana da página de releases
    assert externos <= permitidos, f"destino externo inesperado: {externos}"


def test_sem_telemetria_nem_trackers():
    proibidos = ("telemetry", "analytics", "sentry", "mixpanel", "segment.io",
                 "google-analytics", "posthog")
    for f in _fontes():
        txt = f.read_text().lower()
        for termo in proibidos:
            assert termo not in txt, f"possível telemetria '{termo}' em {f.name}"


def test_todo_urlopen_passa_pelo_guard_ou_e_local():
    """Nenhum urllib.request.urlopen cru: ou usa o guard _abrir_http, ou é o
    probe localhost anotado. (Evita egress fora do controle da política.)"""
    for f in _fontes():
        txt = f.read_text()
        for m in re.finditer(r"urllib\.request\.urlopen", txt):
            trecho = txt[max(0, m.start() - 120): m.start()]
            linha = txt[m.start(): txt.find("\n", m.start())]
            assert "nosec B310" in linha or "def _abrir_http" in trecho, \
                f"urlopen sem guard em {f.name}: {linha.strip()[:80]}"
