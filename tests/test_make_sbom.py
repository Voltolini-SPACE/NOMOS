"""Regressão para `tools/make_sbom.py` — determinismo e amarração ao artefato.

Cobre as duas garantias novas de H4.8 (v1.3.0rc19):

1. Com `SOURCE_DATE_EPOCH` no ambiente, dois runs consecutivos com os mesmos
   argumentos produzem SBOM bit-a-bit idêntico (timestamp derivado, uuid5
   determinístico, json com `sort_keys=True`).
2. Quando caminhos de artefato são passados como argumentos posicionais
   extras, cada um vira uma entrada em
   `metadata.component.externalReferences[type=distribution]` com hash
   `SHA-256` calculado a partir do conteúdo real do arquivo.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAKE_SBOM = ROOT / "tools" / "make_sbom.py"


# Variáveis essenciais em Windows — sem elas o interpretador Python filho
# morre no arranque com `_Py_HashRandomization_Init: failed to get random
# numbers`. Mesmo motivo documentado em `tests/_cli_env.py`.
_WIN_ESSENTIALS = (
    "SystemRoot", "SYSTEMROOT", "SystemDrive", "windir", "TEMP", "TMP",
    "PATHEXT", "COMSPEC", "APPDATA", "LOCALAPPDATA",
    "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "USERNAME",
    "PYTHONUTF8", "PYTHONIOENCODING",
)


def _run(out: Path, args: list[str], epoch: str | None) -> None:
    env = {"PATH": os.environ.get("PATH", "")}
    for k in _WIN_ESSENTIALS:
        v = os.environ.get(k)
        if v is not None:
            env[k] = v
    if epoch is not None:
        env["SOURCE_DATE_EPOCH"] = epoch
    subprocess.run(
        [sys.executable, str(MAKE_SBOM), str(out), *args],
        check=True,
        env=env,
        cwd=str(ROOT),
    )


def test_sbom_determinismo_com_source_date_epoch(tmp_path: Path) -> None:
    """Mesmo epoch, mesmos args ⇒ SBOM bit-a-bit idêntico."""
    a = tmp_path / "sbom_a.json"
    b = tmp_path / "sbom_b.json"
    _run(a, [], epoch="1728000000")
    _run(b, [], epoch="1728000000")
    assert a.read_bytes() == b.read_bytes(), (
        "SBOMs deveriam ser bit-a-bit idênticos com o mesmo SOURCE_DATE_EPOCH"
    )
    doc = json.loads(a.read_text())
    assert doc["metadata"]["timestamp"] == "2024-10-04T00:00:00+00:00"
    assert doc["serialNumber"].startswith("urn:uuid:")
    # Serial determinístico: mesmo bytes de saída ⇒ mesmo serial.
    doc_b = json.loads(b.read_text())
    assert doc["serialNumber"] == doc_b["serialNumber"]


def test_sbom_serial_muda_com_epoch(tmp_path: Path) -> None:
    """Epochs diferentes ⇒ serialNumbers diferentes (evita colisão de identidade)."""
    a = tmp_path / "sbom_a.json"
    b = tmp_path / "sbom_b.json"
    _run(a, [], epoch="1728000000")
    _run(b, [], epoch="1728000001")
    doc_a = json.loads(a.read_text())
    doc_b = json.loads(b.read_text())
    assert doc_a["serialNumber"] != doc_b["serialNumber"]


def test_sbom_referencia_artefatos_por_sha256(tmp_path: Path) -> None:
    """Argumentos extras viram externalReferences com sha256 real."""
    art1 = tmp_path / "fake.whl"
    art2 = tmp_path / "fake.tar.gz"
    art1.write_bytes(b"conteudo do wheel de teste")
    art2.write_bytes(b"conteudo do sdist de teste")
    expected_h1 = hashlib.sha256(art1.read_bytes()).hexdigest()
    expected_h2 = hashlib.sha256(art2.read_bytes()).hexdigest()

    out = tmp_path / "sbom.json"
    _run(out, [str(art1), str(art2)], epoch="1728000000")
    doc = json.loads(out.read_text())
    refs = doc["metadata"]["component"].get("externalReferences", [])
    assert len(refs) == 2
    by_name = {r["url"]: r for r in refs}
    assert by_name["fake.whl"]["type"] == "distribution"
    assert by_name["fake.whl"]["hashes"][0] == {"alg": "SHA-256", "content": expected_h1}
    assert by_name["fake.tar.gz"]["hashes"][0] == {"alg": "SHA-256", "content": expected_h2}


def test_sbom_sem_epoch_ainda_funciona(tmp_path: Path) -> None:
    """Sem SOURCE_DATE_EPOCH: fallback wall-clock/uuid4 continua produzindo SBOM válido."""
    out = tmp_path / "sbom.json"
    _run(out, [], epoch=None)
    doc = json.loads(out.read_text())
    assert doc["bomFormat"] == "CycloneDX"
    assert doc["specVersion"] == "1.5"
    assert doc["metadata"]["component"]["name"] == "nomos"
    assert doc["serialNumber"].startswith("urn:uuid:")
