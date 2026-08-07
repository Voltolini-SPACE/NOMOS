"""NOMOS ext.skills — instalação governada de skills.

Manifesto obrigatório (skill.json):
{
  "name": "...", "version": "x.y.z",
  "permissions": ["A1_WRITE_LOCAL", ...],   # categorias da política
  "entry": "main.py",
  "files": {"main.py": "<sha256>", ...}
}

Garantias:
- checksum SHA-256 verificado arquivo a arquivo antes da cópia;
- permissões declaradas exibidas ao aprovador; instalação passa pelo gate;
- assinatura ed25519 (C6): manifesto com "signature" só instala se o bloco
  for íntegro E o publicador estiver no trust store E não revogado E o pin
  TOFU da skill conferir; defeito em qualquer elo = recusa, mesmo aprovado;
- pinagem TOFU: 1ª instalação confiável registra o publicador da skill.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from nomos.kernel.policy import Category, PolicyEngine, gate
from nomos.ext.signing import SigningError, TrustStore, verify_signed_manifest


class SkillError(Exception):
    pass


def _rel_segura(rel: str) -> bool:
    """True só se `rel` é um caminho relativo seguro DENTRO da skill.

    Bloqueia o vetor de path traversal / caminho absoluto no manifesto: um
    `entry` ou chave de `files` como '/tmp/x', '../x' ou 'C:\\x' faria
    `dest / rel` escapar do diretório da skill (no caso de caminho absoluto,
    o pathlib descarta o lado esquerdo). Fail-closed: qualquer dúvida = inseguro.
    """
    from pathlib import PurePosixPath
    if not isinstance(rel, str) or not rel or rel != rel.strip():
        return False
    if "\\" in rel or ":" in rel:            # backslash/drive (Windows/UNC)
        return False
    p = PurePosixPath(rel)
    if p.is_absolute():
        return False
    return not any(part in ("..", "") for part in p.parts)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest(src: Path) -> dict:
    mf_path = src / "skill.json"
    if not mf_path.exists():
        raise SkillError("manifesto skill.json ausente")
    mf = json.loads(mf_path.read_text(encoding="utf-8"))
    # `entrypoint` é alias aceito de `entry` (v2). Usamos um entry EFETIVO
    # sem mutar `mf`: mutá-lo aqui invalidaria a assinatura, que é verificada
    # sobre o corpo original do manifesto.
    entry_efetivo = mf.get("entry") or mf.get("entrypoint")
    for field in ("name", "version", "permissions", "files"):
        if field not in mf:
            raise SkillError(f"manifesto inválido: campo obrigatório ausente: {field}")
    if not entry_efetivo:
        raise SkillError("manifesto inválido: campo obrigatório ausente: entry")
    known = {c.value for c in Category}
    for perm in mf["permissions"]:
        if perm not in known:
            raise SkillError(f"permissão desconhecida no manifesto: {perm}")
    # Anti path-traversal: entry e toda chave de files têm de ser caminhos
    # relativos seguros dentro da skill (nada de '..', absoluto ou drive).
    if not isinstance(mf["files"], dict) or not mf["files"]:
        raise SkillError("manifesto inválido: 'files' deve mapear arquivo->sha256")
    for rel in list(mf["files"].keys()) + [entry_efetivo]:
        if not _rel_segura(rel):
            raise SkillError(f"caminho inseguro no manifesto (traversal/absoluto): {rel!r}")
    # entry tem de ser um arquivo verificado por checksum (constar em files),
    # senão rodaria código sem integridade garantida.
    if entry_efetivo not in mf["files"]:
        raise SkillError(
            f"entry '{entry_efetivo}' precisa estar em 'files' (para ter checksum)")
    return mf


def verify_files(src: Path, manifest: dict) -> None:
    for rel, expected in manifest["files"].items():
        target = src / rel
        if not target.exists():
            raise SkillError(f"arquivo declarado ausente: {rel}")
        actual = _sha256(target)
        if actual != expected:
            raise SkillError(
                f"checksum divergente em {rel}: esperado {expected[:12]}..., "
                f"obtido {actual[:12]}..."
            )


def install(src: Path, skills_dir: Path, engine: PolicyEngine, approver,
            trust: TrustStore | None = None) -> dict:
    src = Path(src)
    manifest = load_manifest(src)

    publisher = None
    if "signature" in manifest:
        if trust is None:
            trust = TrustStore(Path(skills_dir).parent / "trust.json")
        try:
            publisher = verify_signed_manifest(manifest, trust)
        except SigningError as exc:
            raise SkillError(f"assinatura recusada: {exc}") from None

    verify_files(src, manifest)

    decision = engine.decide(
        Category.SKILL_INSTALL,
        target=(f"{manifest['name']}@{manifest['version']} "
                f"perms={manifest['permissions']} "
                + (f"publicador_verificado={publisher}" if publisher else "NAO_ASSINADA")),
    )
    if not gate(decision, approver):
        raise SkillError("instalação não aprovada pelo gate de aprovação")

    dest = skills_dir / manifest["name"]
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for rel in manifest["files"]:
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src / rel, target)
    shutil.copy2(src / "skill.json", dest / "skill.json")
    if publisher is not None and trust is not None and trust.pin_of(manifest["name"]) is None:
        trust.pin(manifest["name"], publisher)   # TOFU: pina no 1º sucesso
    return manifest


def list_installed(skills_dir: Path) -> list[dict]:
    out: list[dict] = []
    if not skills_dir.exists():
        return out
    for child in sorted(skills_dir.iterdir()):
        mf = child / "skill.json"
        if mf.exists():
            try:
                data = json.loads(mf.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue          # entrada ilegível não derruba a listagem toda
            out.append({"name": data.get("name", child.name),
                        "version": data.get("version", "?"),
                        "permissions": data.get("permissions", [])})
    return out


def remove(name: str, skills_dir: Path) -> bool:
    dest = skills_dir / name
    if dest.exists():
        shutil.rmtree(dest)
        return True
    return False
