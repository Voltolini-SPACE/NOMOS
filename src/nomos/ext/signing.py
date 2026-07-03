"""NOMOS ext.signing — assinatura ed25519 de skills (R9/C6).

Modelo:
- o AUTOR assina o manifesto canônico (sem o bloco "signature") com sua
  chave privada ed25519; o bloco carrega pubkey, fingerprint e assinatura;
- a PLATAFORMA só aceita skill assinada se o publicador estiver no trust
  store do usuário (adicionado via gate) e NÃO revogado;
- PINAGEM TOFU: na 1ª instalação confiável, o nome da skill é pinado ao
  fingerprint; atualização assinada por OUTRO publicador = RECUSA;
- qualquer defeito (bloco malformado, assinatura inválida, chave estranha,
  revogada, pin divergente) = SkillError, mesmo com aprovação humana.
"""
from __future__ import annotations

from nomos.kernel.plataforma import chmod_privado

import base64
import hashlib
import json
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding, NoEncryption, PrivateFormat, load_pem_private_key,
)

ALGO = "ed25519"


class SigningError(Exception):
    pass


def _canonical(manifest: dict) -> bytes:
    mf = {k: v for k, v in manifest.items() if k != "signature"}
    return json.dumps(mf, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def fingerprint(pub_raw: bytes) -> str:
    return hashlib.sha256(pub_raw).hexdigest()[:16]


# ---------- lado do autor ----------
def keygen(dirpath: Path) -> tuple[Path, str]:
    """Gera par de chaves; privada PEM 0600; devolve (caminho, pubkey_b64)."""
    dirpath = Path(dirpath)
    dirpath.mkdir(parents=True, exist_ok=True)
    priv = Ed25519PrivateKey.generate()
    priv_path = dirpath / "skill_signing_ed25519.pem"
    priv_path.write_bytes(priv.private_bytes(
        Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
    chmod_privado(priv_path, 0o600)
    pub_raw = priv.public_key().public_bytes_raw()
    return priv_path, base64.b64encode(pub_raw).decode()


def sign_manifest(manifest: dict, priv_path: Path) -> dict:
    priv = load_pem_private_key(Path(priv_path).read_bytes(), password=None)
    if not isinstance(priv, Ed25519PrivateKey):
        raise SigningError("chave privada não é ed25519")
    pub_raw = priv.public_key().public_bytes_raw()
    sig = priv.sign(_canonical(manifest))
    out = dict(manifest)
    out["signature"] = {
        "algo": ALGO,
        "publisher": fingerprint(pub_raw),
        "pubkey": base64.b64encode(pub_raw).decode(),
        "sig": base64.b64encode(sig).decode(),
    }
    return out


# ---------- lado da plataforma ----------
class TrustStore:
    """Publicadores confiáveis + revogações + pins por skill (0600)."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def _load(self) -> dict:
        if not self.path.exists():
            return {"publishers": {}, "revoked": [], "pins": {}}
        try:
            d = json.loads(self.path.read_text())
        except Exception:
            raise SigningError("trust store corrompido — recusa fail-closed") from None
        if not (isinstance(d.get("publishers"), dict)
                and isinstance(d.get("revoked"), list)
                and isinstance(d.get("pins"), dict)):
            raise SigningError("trust store corrompido — recusa fail-closed")
        return d

    def _save(self, d: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, indent=2, ensure_ascii=False))
        chmod_privado(tmp, 0o600)
        tmp.replace(self.path)
        chmod_privado(self.path, 0o600)

    def add(self, pubkey_b64: str, label: str) -> str:
        raw = base64.b64decode(pubkey_b64)
        Ed25519PublicKey.from_public_bytes(raw)  # valida formato
        fp = fingerprint(raw)
        d = self._load()
        d["publishers"][fp] = {"pubkey": pubkey_b64, "label": label}
        d["revoked"] = [r for r in d["revoked"] if r != fp]
        self._save(d)
        return fp

    def revoke(self, fp: str) -> bool:
        d = self._load()
        if fp not in d["publishers"]:
            return False
        if fp not in d["revoked"]:
            d["revoked"].append(fp)
        self._save(d)
        return True

    def entry(self, fp: str) -> dict | None:
        d = self._load()
        if fp in d["revoked"]:
            return None
        return d["publishers"].get(fp)

    def is_revoked(self, fp: str) -> bool:
        return fp in self._load()["revoked"]

    def pin_of(self, skill_name: str) -> str | None:
        return self._load()["pins"].get(skill_name)

    def pin(self, skill_name: str, fp: str) -> None:
        d = self._load()
        d["pins"][skill_name] = fp
        self._save(d)


def verify_signed_manifest(manifest: dict, trust: TrustStore) -> str:
    """Valida bloco de assinatura; devolve fingerprint do publicador.
    Qualquer defeito => SigningError (fail-closed)."""
    sig_block = manifest.get("signature")
    if not isinstance(sig_block, dict):
        raise SigningError("bloco de assinatura malformado")
    if sig_block.get("algo") != ALGO:
        raise SigningError(f"algoritmo não suportado: {sig_block.get('algo')!r}")
    try:
        pub_raw = base64.b64decode(sig_block["pubkey"])
        sig = base64.b64decode(sig_block["sig"])
        fp_declared = sig_block["publisher"]
    except Exception:
        raise SigningError("bloco de assinatura malformado") from None
    if fingerprint(pub_raw) != fp_declared:
        raise SigningError("fingerprint não corresponde à pubkey")
    if trust.is_revoked(fp_declared):
        raise SigningError(f"publicador REVOGADO: {fp_declared}")
    entry = trust.entry(fp_declared)
    if entry is None or entry["pubkey"] != sig_block["pubkey"]:
        raise SigningError(
            f"publicador não confiável: {fp_declared} — adicione com "
            "'nomos skill trust add' antes de instalar")
    try:
        Ed25519PublicKey.from_public_bytes(pub_raw).verify(sig, _canonical(manifest))
    except InvalidSignature:
        raise SigningError("assinatura INVÁLIDA — manifesto adulterado ou chave errada") from None
    pinned = trust.pin_of(manifest["name"])
    if pinned is not None and pinned != fp_declared:
        raise SigningError(
            f"pin divergente: skill '{manifest['name']}' está pinada ao publicador "
            f"{pinned}, mas veio assinada por {fp_declared} — recusa (TOFU)")
    return fp_declared
