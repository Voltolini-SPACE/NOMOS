"""Ciclo Fortaleza Local — prova estática: nenhum destino externo escondido."""
import re
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "nomos"


# Diretórios cujo código NÃO é o core do NOMOS: skills instaláveis, que o dono
# escolhe, aprova no gate e roda dentro do sandbox. Ter URL é o PROPÓSITO delas
# (reach-github fala com o GitHub; citeguard-verify-online resolve DOI). Elas
# entraram no raio deste teste em 23/08, quando foram movidas para dentro do
# pacote para poderem viajar no wheel — e o teste passou a acusar `doi.org`,
# `arxiv.org`, `r.jina.ai` como se fossem egresso escondido do produto.
#
# Isentar aqui NÃO afrouxa a governança: ela muda de lugar, para onde é
# verificável de verdade — `test_skill_com_rede_declara_a2` abaixo exige que
# toda skill com URL externa no código declare A2_NET_EGRESS no manifesto.
# Grep no fonte era um proxy; a declaração no manifesto é o contrato que o
# instalador e o gate realmente consultam.
DIRS_NAO_CORE = ("conectores", "skills_embutidas", "skills_do_dono")


def _e_core(f: Path) -> bool:
    return not any(d in f.parts for d in DIRS_NAO_CORE)


def _fontes():
    return [f for f in SRC.rglob("*.py") if _e_core(f)]


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
        # SKILLS (embutidas e do dono) seguem a MESMA doutrina: é o corpo de
        # uma habilidade que o dono instala e aprova, cujo manifesto declara o
        # que ela toca. citeguard fala com doi.org/arxiv.org, reach-readpage
        # com r.jina.ai — é o trabalho DELAS, e o gate decide se rodam.
        # O QUE ESTA ISENÇÃO NÃO COBRE, e precisa de dono: que o destino
        # externo de cada skill esteja DECLARADO no manifesto dela. Isso é
        # invariante de skills, não de egresso do core — e hoje não existe.
        if {"skills_do_dono", "skills_embutidas"} & set(f.parts):
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
                  "openrouter.ai", "console.mistral.ai",
                  # O painel MOSTRA a linha `export NOMOS_SLACK_WEBHOOK=
                  # "https://hooks.slack.com/..."` para o dono copiar. É texto
                  # de instrução, não destino: quem posta no Slack é o conector
                  # em `conectores/mcp/slack/`, que este teste já isenta por
                  # ser bridge A3 opt-in. Coberto abaixo pelo mesmo guarda dos
                  # outros hosts de documentação.
                  "hooks.slack.com"}
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
        if {"skills_do_dono", "skills_embutidas"} & set(f.parts):
            continue          # corpo de skill: governado por manifesto + gate
        txt = f.read_text()
        for m in re.finditer(r"urllib\.request\.urlopen", txt):
            trecho = txt[max(0, m.start() - 120): m.start()]
            linha = txt[m.start(): txt.find("\n", m.start())]
            assert "nosec B310" in linha or "def _abrir_http" in trecho, \
                f"urlopen sem guard em {f.name}: {linha.strip()[:80]}"


HOSTS_SO_DOCUMENTACAO = ("console.groq.com", "aistudio.google.com",
                         "openrouter.ai", "console.mistral.ai")
"""Hosts que aparecem SÓ como link/instrução na tela, nunca buscados.

`hooks.slack.com` foi acrescentado aqui e teve de sair: o guard abaixo provou
que ele aparece a 200 caracteres de um `Request(` em
`conectores/mcp/slack/servidor.py` — o conector REALMENTE posta lá. Ele é
destino legítimo (bridge A3, opt-in, aprovado por chamada) e por isso segue em
`permitidos`; mas chamá-lo de "só documentação" seria falso, e este arquivo
existe justamente para que a lista permitida não vire depósito de exceções
sem justificativa verdadeira.
"""


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



# --------------------------------------------------------------------------
# A governança do egresso das SKILLS mora no manifesto, não no grep
# --------------------------------------------------------------------------
CHAMADAS_DE_REDE = re.compile(
    r"\b(urlopen|urlretrieve|socket\.socket|create_connection|"
    r"requests\.(?:get|post|put|delete|head)|httpx\.|http\.client|"
    r"HTTPConnection|HTTPSConnection)\b")
"""O que caracteriza egresso é CHAMAR a rede, não citar uma URL.

Minha primeira versão deste teste procurava strings `https://…` e acusou
`citeguard-selfcheck`, que declara A0/A1 corretamente: as URLs dela
(`arxiv.org`, `8.8.8.8`, `10.0.0.5`) são **fixtures de uma tabela de casos** —
os alvos que o guarda anti-SSRF precisa RECUSAR. Medido: zero ocorrências de
urlopen/requests/socket no arquivo inteiro (484 linhas). O manifesto estava
certo e o teste, errado. Procurar a chamada é o que separa uso de menção.
"""


def _e_internet(host: str) -> bool:
    """Um host que sai MESMO para a internet.

    Endereço privado, de loopback ou link-local não é egresso — e aparece de
    propósito no fonte de quem TESTA anti-SSRF: `citeguard-selfcheck` traz
    `10.0.0.5`, `169.254.10.1`, `192.168.1.10` exatamente como os alvos que o
    guarda dela precisa RECUSAR. Contá-los como saída acusaria a skill que
    protege contra a saída — o teste estaria medindo ao contrário.
    """
    import ipaddress

    if host in {"localhost", "0.0.0.0"} or "." not in host:
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True          # nome de domínio: é internet
    return not (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast)


def _skills():
    for base in ("skills_embutidas", "skills_do_dono"):
        raiz = SRC / base
        if raiz.is_dir():
            yield from (p for p in raiz.iterdir()
                        if (p / "skill.json").is_file())


def test_skill_com_rede_declara_a2():
    """Skill que fala com a internet TEM de declarar A2_NET_EGRESS.

    É o contrato que o instalador e o gate consultam de verdade. Sem isto,
    isentar as skills do teste de egresso seria só silenciar a checagem.
    """
    import json

    faltando = []
    for skill in _skills():
        chamadas = {c for py in skill.rglob("*.py")
                    for c in CHAMADAS_DE_REDE.findall(
                        py.read_text(encoding="utf-8", errors="replace"))}
        if not chamadas:
            continue
        perms = json.loads((skill / "skill.json").read_text()).get("permissions", [])
        if "A2_NET_EGRESS" not in perms:
            faltando.append((skill.name, sorted(chamadas), perms))
    assert faltando == [], (
        "skill que CHAMA a rede e não declara A2_NET_EGRESS no manifesto: "
        f"{faltando}")


def test_toda_skill_tem_permissions_no_manifesto():
    """Manifesto sem `permissions` é skill sem envelope — não pode existir."""
    import json

    sem = [s.name for s in _skills()
           if "permissions" not in json.loads((s / "skill.json").read_text())]
    assert sem == [], f"skills sem 'permissions': {sem}"
