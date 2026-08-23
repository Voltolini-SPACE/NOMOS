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
        # os conectores de exemplo (nomos/conectores/mcp) são bridges A3/opt-in
        # para as APIs OFICIAIS que o próprio usuário escolhe, confia e aprova a
        # cada chamada — não são o "core" do NOMOS. Continuam cobertos pelos
        # testes de telemetria e de guard de urlopen abaixo.
        if "conectores" in f.parts:
            continue
        for host in url_re.findall(f.read_text()):
            if host in {"127.0.0.1", "localhost", "0.0.0.0"} or "." not in host:
                continue                     # loopback ou placeholder de doc
            externos.add(host)
    permitidos = {"api.anthropic.com",   # nuvem opcional (atrás do cadeado)
                  "huggingface.co",      # baixar o cérebro embutido (opt-in consciente)
                  "api.github.com",      # v0.12: `nomos atualizar` (atrás do gate A2)
                  "github.com",          # v0.12: URL humana da página de releases
                  # --- LINKS DE DOCUMENTAÇÃO, não destinos de egresso ---
                  # A aba Chaves mostra onde obter uma chave gratuita. São
                  # href que o HUMANO clica no navegador dele; o processo do
                  # NOMOS nunca os busca — provado logo abaixo, em
                  # test_hosts_de_documentacao_nunca_sao_buscados.
                  "console.groq.com", "aistudio.google.com",
                  "openrouter.ai", "console.mistral.ai"}
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


HOSTS_SO_DOCUMENTACAO = ("console.groq.com", "aistudio.google.com",
                         "openrouter.ai", "console.mistral.ai")


def test_hosts_de_documentacao_nunca_sao_buscados():
    """Um link mostrado ao humano não pode virar uma conexão do programa.

    A permissão desses hosts na lista acima vale SÓ enquanto eles aparecerem
    apenas como href. Se alguém um dia passar um deles a urlopen/Request, este
    teste quebra — que é exatamente o momento em que a permissão deixaria de
    ser verdadeira.
    """
    for f in _fontes():
        txt = f.read_text()
        for host in HOSTS_SO_DOCUMENTACAO:
            for m in re.finditer(re.escape(host), txt):
                # janela ao redor da ocorrência: nenhuma chamada de rede perto
                ini, fim = max(0, m.start() - 200), m.end() + 200
                janela = txt[ini:fim]
                for proibido in ("urlopen", "Request(", "_abrir_http",
                                 "requests.get", "requests.post"):
                    assert proibido not in janela, (
                        f"{host} aparece perto de {proibido!r} em {f.name} — "
                        "deixou de ser só link de documentação")


def test_links_de_documentacao_sao_href_https():
    """E aparecem como link https de verdade (não como base de API)."""
    achados = 0
    for f in _fontes():
        txt = f.read_text()
        for host in HOSTS_SO_DOCUMENTACAO:
            for m in re.finditer(re.escape(host), txt):
                achados += 1
                antes = txt[max(0, m.start() - 12):m.start()]
                assert "https://" in antes, f"{host} sem https em {f.name}"
    assert achados >= len(HOSTS_SO_DOCUMENTACAO), "os links sumiram da aba Chaves"
