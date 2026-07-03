#!/usr/bin/env python3
"""Gera SBOM CycloneDX 1.5 (JSON) para o NOMOS a partir dos metadados instalados."""
from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from importlib import metadata

ROOT = "nomos"
DEPS = ["cryptography", "cffi", "pycparser", "argon2-cffi", "argon2-cffi-bindings"]  # árvore real


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


def main(out_path: str) -> int:
    root = component(ROOT, "application")
    if root is None:
        print("FALHA: pacote nomos não está instalado.", file=sys.stderr)
        return 1
    comps = [c for c in (component(d) for d in DEPS) if c]
    bom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{uuid.uuid4()}",
        "version": 1,
        "metadata": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "component": root,
            "tools": [{"vendor": "NOMOS", "name": "make_sbom", "version": "0.1.0"}],
        },
        "components": comps,
        "dependencies": [
            {"ref": root["bom-ref"], "dependsOn": [c["bom-ref"] for c in comps]}
        ],
    }
    with open(out_path, "w") as fh:
        json.dump(bom, fh, indent=2)
    print(f"SBOM gravado: {out_path} ({1 + len(comps)} componentes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "sbom.cdx.json"))
