"""Fase 7 — doutor v0.11: STATUS GERAL + próximo passo acionável."""
import io

import pytest

from nomos import cli
from nomos.cognition import motores
from nomos.kernel import config
from nomos.kernel.audit import AuditLog
from nomos.simple import doutor


@pytest.fixture(autouse=True)
def _iso(nomos_home, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    monkeypatch.setattr(motores, "modelos_ollama", lambda *a, **k: [])
    monkeypatch.setattr(motores, "_http_ok", lambda *a, **k: False)
    monkeypatch.setattr("shutil.which", lambda *a, **k: None)
    motores.limpar_cache()
    yield
    motores.limpar_cache()


def test_status_geral_pronto_mesmo_sem_cerebro(nomos_home):
    # achado P1-3 (auditoria 2026-07-17): antes desta correção, itens
    # opcionais ausentes (cérebro/skills/voz/imagem — nenhum vem instalado
    # por padrão) derrubavam o status para PARCIAL, tornando "PRONTO"
    # praticamente inalcançável numa instalação nova e saudável. Agora só
    # itens 'bloqueante' decidem BLOQUEADO/PRONTO; os opcionais continuam
    # listados individualmente no relatório, sem fingir que estão prontos.
    config.ensure_home()
    itens = doutor.diagnostico_v011(nomos_home)
    assert doutor.status_geral(itens) == "PRONTO"
    rel = doutor.texto_relatorio_v011(nomos_home)
    assert "STATUS GERAL: PRONTO" in rel
    assert "Sem cérebro de IA ainda" in rel          # honesto: ainda listado
    assert "Próximo passo recomendado:" in rel


def test_proximo_passo_prioriza_bloqueante():
    itens = [
        {"ok": False, "titulo": "a", "detalhe": "", "proximo": "passo-opcional",
         "bloqueante": False},
        {"ok": False, "titulo": "b", "detalhe": "", "proximo": "passo-urgente",
         "bloqueante": True},
    ]
    assert doutor.proximo_passo(itens) == "passo-urgente"
    assert doutor.status_geral(itens) == "BLOQUEADO"


def test_tudo_ok_fica_pronto():
    itens = [{"ok": True, "titulo": "x", "detalhe": "", "proximo": "",
              "bloqueante": False}]
    assert doutor.status_geral(itens) == "PRONTO"
    assert "nada pendente" in doutor.proximo_passo(itens)


def test_item_opcional_ausente_nao_derruba_status_geral():
    """Unidade do achado P1-3: item não-bloqueante com ok=False (ex.
    'nenhuma skill instalada', 'opcional') não pode, sozinho, impedir
    PRONTO. Só bloqueante=True e ok=False derruba (testado em
    test_proximo_passo_prioriza_bloqueante)."""
    itens = [
        {"ok": True, "titulo": "essencial", "detalhe": "", "proximo": "",
         "bloqueante": True},
        {"ok": False, "titulo": "cérebro", "detalhe": "opcional",
         "proximo": "", "bloqueante": False},
        {"ok": False, "titulo": "skills", "detalhe": "opcional",
         "proximo": "", "bloqueante": False},
    ]
    assert doutor.status_geral(itens) == "PRONTO"


def test_auditoria_violada_bloqueia(nomos_home):
    config.ensure_home()
    log = AuditLog(nomos_home / "logs" / "audit.jsonl")
    log.append("evento.um", x=1)
    log.append("evento.dois", x=2)
    caminho = nomos_home / "logs" / "audit.jsonl"
    adulterado = caminho.read_text().replace('"x":1', '"x":999')
    caminho.write_text(adulterado)
    itens = doutor.diagnostico_v011(nomos_home)
    assert doutor.status_geral(itens) == "BLOQUEADO"
    assert "VIOLADA" in doutor.texto_relatorio_v011(nomos_home)


def test_skill_quebrada_aparece_no_checkup(nomos_home):
    config.ensure_home()
    dest = nomos_home / "skills" / "zumbi"
    dest.mkdir(parents=True)
    (dest / "skill.json").write_text("{não é json")
    rel = doutor.texto_relatorio_v011(nomos_home)
    assert "Skill quebrada: zumbi" in rel


# ---------------- P2-6 (auditoria de 2026-07-17) ----------------
# AgentToolBoundary é real e testado, mas nenhum fluxo de produção o
# instancia — `nomos doutor` agora reporta esse estado (informativo, não
# bloqueante), em vez de ficar em silêncio sobre a lacuna.
def test_diagnostico_relata_estado_real_dos_agentes(nomos_home):
    """Achado P2-6 (Horizonte 2): item de diagnóstico existe e é honesto.

    Atualizado no Horizonte 3/item 1 — o wiring real de `nomos agentes usar`
    tornou a alegação antiga ("nenhum fluxo real de produção") falsa; o
    teste passou a checar a alegação NOVA (caller real existe, 5/8
    ferramentas ligadas), não o texto literal antigo. Ver
    tests/test_h3_item1_agente_boundary_wiring.py para a cobertura do
    wiring em si.
    """
    config.ensure_home()
    itens = doutor.diagnostico_v011(nomos_home)
    ag = [i for i in itens if "agente(s) especializado" in i["titulo"]
          or "agente especializado" in i["titulo"]]
    assert len(ag) == 1, itens
    item = ag[0]
    assert item["ok"] is True
    assert item["bloqueante"] is False        # não pode derrubar PRONTO
    assert "AgentToolBoundary" in item["detalhe"]
    assert "nomos agentes usar" in item["detalhe"]
    assert "5/8" in item["detalhe"]
    # os agentes oficiais empacotados aparecem pelo nome (catálogo real)
    assert "pesquisador-local" in item["detalhe"] or "programador" in item["detalhe"]
    # o item novo não pode, sozinho, tirar o status de PRONTO
    assert doutor.status_geral(itens) == "PRONTO"


def test_cli_doutor_usa_v011(capsys):
    assert cli.main(["init"]) == 0
    assert cli.main(["doutor"]) == 0
    out = capsys.readouterr().out
    assert "Check-up" in out                 # compat com expectativa antiga
    assert "STATUS GERAL:" in out
    assert "Próximo passo recomendado:" in out
    assert "cérebro" in out.lower()


def test_diagnostico_v010_continua_estavel(nomos_home):
    """A função antiga não muda de formato (compat)."""
    config.ensure_home()
    assert all(set(i) == {"ok", "titulo", "detalhe"}
               for i in doutor.diagnostico())
