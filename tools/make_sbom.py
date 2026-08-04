#!/usr/bin/env python3
"""Gera SBOM CycloneDX 1.5 (JSON) para o NOMOS a partir dos metadados instalados.

Uso:
    make_sbom.py <out_path> [<artefato>...]

Sem argumentos extras: SBOM com root + deps declaradas.
Com artefatos: adiciona `externalReferences[type=distribution]` com o sha256
de cada arquivo (wheel/sdist) — amarra o SBOM ao artefato distribuível.

Determinismo: quando `SOURCE_DATE_EPOCH` estiver no ambiente (padrão
reproducible-builds.org), timestamp e serialNumber são derivados dele em
vez de wall-clock/uuid4, de modo que dois builds do mesmo SHA produzem
SBOMs bit-a-bit idênticos.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

ROOT = "nomos"
DEPS = ["cryptography", "cffi", "pycparser", "argon2-cffi", "argon2-cffi-bindings"]  # árvore real

# Namespace UUID estável para derivação determinística do serialNumber via
# uuid5. Fixo (gerado uma única vez); nunca deve mudar entre releases sob
# risco de reidentificação errada de SBOMs históricos.
_NOMOS_SBOM_NAMESPACE = uuid.UUID("6b6f0f8e-1a2b-5c7d-8e9f-abcdef012345")


def component(name: str, ctype: str = "library") -> dict | None:
    try:
        dist = metadata.distribution(name)
    except metadata.PackageNotFoundError:
        return None
    version = dist.version
    return {
        "type": ctype,
        "bom-ref": f"pkg:pypi/{name}@{version}",
        "name": name,
        "version": version,
        "purl": f"pkg:pypi/{name}@{version}",
    }


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _deterministic_timestamp() -> str:
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch and epoch.isdigit():
        return datetime.fromtimestamp(int(epoch), tz=timezone.utc).isoformat()
    return datetime.now(timezone.utc).isoformat()


def _deterministic_serial(root_purl: str) -> str:
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch and epoch.isdigit():
        seed = f"{root_purl}@{epoch}"
        return f"urn:uuid:{uuid.uuid5(_NOMOS_SBOM_NAMESPACE, seed)}"
    return f"urn:uuid:{uuid.uuid4()}"


def _artifact_reference(path: Path) -> dict:
    digest = _sha256_file(path)
    return {
        "type": "distribution",
        "url": path.name,
        "comment": "Artefato distribuível verificável (sha256)",
        "hashes": [{"alg": "SHA-256", "content": digest}],
    }


def main(out_path: str, artifacts: list[str] | None = None) -> int:
    root = component(ROOT, "application")
    if root is None:
        print("FALHA: pacote nomos não está instalado.", file=sys.stderr)
        return 1
    comps = [c for c in (component(d) for d in DEPS) if c]
    metadata_component = dict(root)
    if artifacts:
        refs = []
        for a in artifacts:
            p = Path(a)
            if not p.is_file():
                print(f"FALHA: artefato inexistente: {a}", file=sys.stderr)
                return 2
            refs.append(_artifact_reference(p))
        metadata_component["externalReferences"] = refs
    bom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": _deterministic_serial(root["bom-ref"]),
        "version": 1,
        "metadata": {
            "timestamp": _deterministic_timestamp(),
            "component": metadata_component,
            "tools": [{"vendor": "NOMOS", "name": "make_sbom", "version": "0.2.0"}],
        },
        "components": comps,
        "dependencies": [
            {"ref": root["bom-ref"], "dependsOn": [c["bom-ref"] for c in comps]}
        ],
    }
    with open(out_path, "w") as fh:
        json.dump(bom, fh, indent=2, sort_keys=True)
    n_refs = len(metadata_component.get("externalReferences", []))
    print(
        f"SBOM gravado: {out_path} "
        f"({1 + len(comps)} componentes, {n_refs} artefato(s) referenciado(s))"
    )
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(main("sbom.cdx.json"))
    raise SystemExit(main(sys.argv[1], list(sys.argv[2:])))
