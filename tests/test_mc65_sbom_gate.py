"""MC65 — gate de licença do SBOM usa a MESMA regra do NOMOS Reversa.

Estes dois testes ficam no NOMOS porque exercitam `tools/make_sbom.py`, uma
ferramenta DESTE repositório. O mapeador em si vive no repositório próprio
`nomos-reversa` (nome de exibição «NOMOS Reversa») e é consumido como
dependência — para não haver duas verdades sobre licença.
"""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load_sbom():
    # O componente «NOMOS Reversa» vive em repositório próprio. Onde ele não
    # estiver instalado (ex.: CI antes da publicação do pacote), o gate é
    # pulado em vez de reprovar o SBOM por falta de régua.
    pytest.importorskip("nomos_reversa",
                        reason="componente «NOMOS Reversa» não instalado")
    spec = importlib.util.spec_from_file_location(
        "make_sbom_t", ROOT / "tools" / "make_sbom.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# o gate de licença do SBOM usa a MESMA regra do mapeador
def test_gate_de_licenca_do_sbom():
    sbom = _load_sbom()
    assert sbom.classificar_licenca is not None, "gate perdeu a regra do reversa"

    aprovadas = [
        {"name": "ok", "licenses": [{"license": {"id": "MIT"}}]},
        {"name": "apache", "licenses": [{"license": {"id": "Apache-2.0"}}]},
        {"name": "dupla",
         "licenses": [{"license": {"id": "Apache-2.0 OR BSD-3-Clause"}}]},
    ]
    assert sbom.problemas_de_licenca(aprovadas) == []

    reprovadas = [
        {"name": "agpl", "licenses": [{"license": {"id": "AGPL-3.0"}}]},
        {"name": "gpl", "licenses": [{"license": {"id": "GPL-3.0-only"}}]},
        {"name": "commons",
         "licenses": [{"license": {"id": "Apache-2.0 AND Commons-Clause"}}]},
    ]
    nomes = {p[0] for p in sbom.problemas_de_licenca(reprovadas)}
    assert nomes == {"agpl", "gpl", "commons"}


# o SBOM real do NOMOS passa no gate (dependências declaradas são MIT/BSD/Apache)
def test_gate_de_licenca_aprova_o_sbom_real(tmp_path):
    sbom = _load_sbom()
    destino = tmp_path / "sbom.json"
    assert sbom.main(str(destino), gate=True) == 0
    dados = json.loads(destino.read_text(encoding="utf-8"))
    assert dados["bomFormat"] == "CycloneDX"
    # o SBOM passou a declarar a licença de cada componente identificável
    assert any(c.get("licenses") for c in dados["components"])
