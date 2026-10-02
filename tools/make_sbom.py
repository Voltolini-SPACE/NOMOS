#!/usr/bin/env python3
"""Gera SBOM CycloneDX 1.5 (JSON) para o NOMOS a partir dos metadados instalados.

Uso:
    make_sbom.py <out_path> [<artefato>...] [--gate-licenca]

Sem argumentos extras: SBOM com root + deps declaradas.
Com artefatos: adiciona `externalReferences[type=distribution]` com o sha256
de cada arquivo (wheel/sdist) — amarra o SBOM ao artefato distribuível.
Com `--gate-licenca`: além de gravar o SBOM, REPROVA (saída 3) se alguma
dependência tiver copyleft forte (AGPL/GPL) ou cláusula restritiva — o NOMOS é
MIT e a regra inviolável nº 6 proíbe linkar AGPL. A classificação é a MESMA do
`nomos.reversa` (`classificar_licenca`), para não haver duas verdades.

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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
try:
    from nomos.reversa import classificar_licenca  # noqa: E402
except ImportError:  # o SBOM continua útil sem o gate
    classificar_licenca = None  # type: ignore[assignment]

ROOT = "nomos"
DEPS = ["cryptography", "cffi", "pycparser", "argon2-cffi", "argon2-cffi-bindings"]  # árvore real

# Namespace UUID estável para derivação determinística do serialNumber via
# uuid5. Fixo (gerado uma única vez); nunca deve mudar entre releases sob
# risco de reidentificação errada de SBOMs históricos.
_NOMOS_SBOM_NAMESPACE = uuid.UUID("6b6f0f8e-1a2b-5c7d-8e9f-abcdef012345")


def licenca_do_componente(dist) -> str | None:
    """Licença declarada no metadado da dependência instalada."""
    if classificar_licenca is None:
        return None
    meta = dist.metadata
    texto = " ".join(filter(None, [
        meta.get("License") or "",
        meta.get("License-Expression") or "",   # PEP 639 (pacotes modernos)
        " ".join(meta.get_all("Classifier") or []),
    ]))
    if not texto.strip():
        return None
    ident, _, _ = classificar_licenca(texto)
    return ident


def problemas_de_licenca(comps: list) -> list:
    """Componentes cuja licença impede distribuir o NOMOS sob MIT."""
    problemas = []
    if classificar_licenca is None:
        return problemas
    for c in comps:
        ident = ((c.get("licenses") or [{}])[0].get("license") or {}).get("id")
        if not ident:
            continue
        _, copyleft, restricoes = classificar_licenca(ident)
        if copyleft == "forte" or restricoes:
            problemas.append((c["name"], ident, copyleft, list(restricoes)))
    return problemas


def component(name: str, ctype: str = "library") -> dict | None:
    try:
        dist = metadata.distribution(name)
    except metadata.PackageNotFoundError:
        return None
    version = dist.version
    comp = {
        "type": ctype,
        "bom-ref": f"pkg:pypi/{name}@{version}",
        "name": name,
        "version": version,
        "purl": f"pkg:pypi/{name}@{version}",
    }
    licenca = licenca_do_componente(dist)
    if licenca:
        comp["licenses"] = [{"license": {"id": licenca}}]
    return comp


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


def main(out_path: str, artifacts: list[str] | None = None,
         gate: bool = False) -> int:
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

    if gate:
        problemas = problemas_de_licenca(comps)
        for nome, ident, copyleft, restricoes in problemas:
            detalhe = ", ".join(filter(None, [
                f"copyleft {copyleft}" if copyleft else "",
                "restrições: " + ", ".join(restricoes) if restricoes else "",
            ]))
            print(f"REPROVADO: {nome} — {ident} ({detalhe})", file=sys.stderr)
        if problemas:
            print(f"GATE DE LICENÇA: reprovado ({len(problemas)} de {len(comps)})",
                  file=sys.stderr)
            return 3
        print(f"GATE DE LICENÇA: aprovado ({len(comps)} dependências, "
              "nenhum copyleft forte ou cláusula restritiva)")
    return 0


if __name__ == "__main__":
    argv = sys.argv[1:]
    gate = "--gate-licenca" in argv
    argv = [a for a in argv if a != "--gate-licenca"]
    if not argv:
        raise SystemExit(main("sbom.cdx.json", gate=gate))
    raise SystemExit(main(argv[0], list(argv[1:]), gate=gate))
