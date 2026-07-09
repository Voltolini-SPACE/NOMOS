"""Fase 1.1 — os conectores de exemplo vão no wheel e ficam IDÊNTICOS à cópia do
repositório (``examples/mcp``).

Sem isso, quem instala por ``pip`` via ``nomos mcp exemplos`` vazio. A cópia
empacotada em ``src/nomos/conectores/mcp`` é o que vai no wheel (package-data);
este teste é a trava anti-drift entre as duas cópias.
"""
import filecmp
from pathlib import Path

from nomos.interface import mcp_catalogo as cat
from nomos.interface.mcp_client import carregar_manifesto

RAIZ = Path(__file__).resolve().parent.parent
EXEMPLOS = RAIZ / "examples" / "mcp"
PACOTE = RAIZ / "src" / "nomos" / "conectores" / "mcp"
_DIRS = ("telegram", "whatsapp-cloud", "email-smtp", "signal", "calendario")


def _fontes(base: Path) -> list[str]:
    return sorted(p.relative_to(base).as_posix() for p in base.rglob("*")
                  if p.is_file() and "__pycache__" not in p.parts)


def test_copia_empacotada_existe_e_e_identica_ao_repo():
    assert PACOTE.is_dir(), "a cópia empacotada nomos/conectores/mcp sumiu"
    a, b = _fontes(EXEMPLOS), _fontes(PACOTE)
    assert a == b, f"conjuntos de arquivos diferentes: {set(a) ^ set(b)}"
    _match, mismatch, errors = filecmp.cmpfiles(EXEMPLOS, PACOTE, a,
                                                shallow=False)
    assert not mismatch and not errors, f"drift entre as cópias: {mismatch or errors}"


def test_comando_e_portatil_nos_dois_lugares():
    # o comando NÃO pode conter caminho do repo (senão quebra no wheel):
    # é resolvido em runtime via cwd=base pelo ClienteMCP.
    for raiz in (EXEMPLOS, PACOTE):
        for d in _DIRS:
            m = carregar_manifesto(raiz / d / "manifesto.json")
            assert m["comando"] == ["python3", "servidor.py"], (raiz, d, m["comando"])


def test_descoberta_funciona_da_copia_empacotada(nomos_home):
    # simula o wheel: aponta a raiz para a cópia do pacote e descobre tudo
    conns = cat.conectores_exemplo(nomos_home, raiz=PACOTE)
    nomes = {c["nome"] for c in conns}
    assert {"telegram-bot", "whatsapp-cloud", "email-smtp", "signal-cli",
            "calendario-ics"} <= nomes


def test_pyproject_empacota_os_conectores():
    txt = (RAIZ / "pyproject.toml").read_text(encoding="utf-8")
    assert '"nomos.conectores"' in txt
    assert "mcp/*/servidor.py" in txt and "mcp/*/manifesto.json" in txt
