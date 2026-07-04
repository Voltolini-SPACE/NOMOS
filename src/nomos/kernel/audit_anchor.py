"""NOMOS kernel.audit_anchor — âncora HMAC da cadeia de auditoria (chave no cofre).

A hash-chain (audit.py) já detecta modificação, reordenação e remoção do MEIO,
mas — sendo SEM CHAVE — não detecta truncamento de cauda nem reescrita completa
por quem tem permissão de escrita. Esta âncora fecha essa lacuna com um
HMAC-SHA256 cuja chave vive no COFRE (Argon2id): quem não tem a passphrase não
forja a âncora, mesmo tendo escrita no NOMOS_HOME.

Não é defesa-teatro: um `tip.json` sem chave seria reescrito por quem altera o
log. Aqui o segredo é protegido pelo cofre.

Estados de verificação:
  LEGACY_UNANCHORED  — sem chave e sem âncora: cadeia ok, mas tail não provado (WARN)
  ANCHOR_UNVERIFIED  — âncora presente, mas sem passphrase p/ checar HMAC (WARN, não PASS)
  ANCHORED_VALID     — cadeia + count + tip + HMAC conferem (PASS)
  ANCHORED_INVALID   — âncora presente mas HMAC inválido (FAIL)
  TAIL_TRUNCATED     — menos entradas que o ancorado, ou tip do ponto ancorado diverge (FAIL)
  ANCHOR_MISSING     — chave existe no cofre mas o arquivo de âncora sumiu (FAIL)
  CHAIN_CORRUPTED    — a própria cadeia quebrou (FAIL)

Garantias da chave: gerada localmente (secrets), guardada no cofre (nunca em
claro, nunca logada, nunca impressa em erro), acessada fail-closed. Sem rede,
sem nuvem, sem telemetria.
"""
from __future__ import annotations

import base64
import contextlib
import hashlib
import hmac
import json
import secrets
import time
import uuid
from pathlib import Path

from nomos.kernel.plataforma import chmod_privado

SCHEMA = "nomos.audit.anchor.v1"
CHAVE_COFRE = "__audit_hmac_key__"   # nome da entrada da chave HMAC no cofre

LEGACY_UNANCHORED = "LOG_LEGACY_UNANCHORED"
ANCHOR_UNVERIFIED = "LOG_ANCHOR_UNVERIFIED"
ANCHORED_VALID = "LOG_ANCHORED_VALID"
ANCHORED_INVALID = "LOG_ANCHORED_INVALID"
TAIL_TRUNCATED = "LOG_TAIL_TRUNCATED"
ANCHOR_MISSING = "LOG_ANCHOR_MISSING"
CHAIN_CORRUPTED = "LOG_CHAIN_CORRUPTED"

PASS_STATES = {ANCHORED_VALID}
WARN_STATES = {LEGACY_UNANCHORED, ANCHOR_UNVERIFIED}
FAIL_STATES = {ANCHORED_INVALID, TAIL_TRUNCATED, ANCHOR_MISSING, CHAIN_CORRUPTED}


class AnchorError(Exception):
    pass


def anchor_path(log_path: Path) -> Path:
    return Path(str(log_path) + ".anchor")


def chave_estabelecida(vault) -> bool:
    """A chave HMAC já foi criada no cofre? (só checa NOME, sem passphrase)."""
    try:
        return CHAVE_COFRE in vault.names()
    except Exception:
        return False


def _obter_chave(vault, passphrase: str, criar: bool) -> bytes:
    nomes = vault.names()
    if CHAVE_COFRE in nomes:
        return base64.b64decode(vault.get(CHAVE_COFRE, passphrase))
    if not criar:
        raise AnchorError("chave HMAC de auditoria ausente no cofre (fail-closed)")
    chave = secrets.token_bytes(32)
    vault.set(CHAVE_COFRE, base64.b64encode(chave).decode(), passphrase)
    return chave


def _canonical(corpo: dict) -> bytes:
    return json.dumps({k: v for k, v in corpo.items() if k != "hmac"},
                      sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def _hmac(chave: bytes, corpo: dict) -> str:
    return hmac.new(chave, _canonical(corpo), hashlib.sha256).hexdigest()


def criar_ancora(audit, vault, passphrase: str) -> dict:
    """Cria/atualiza a âncora HMAC sobre o estado ATUAL do log. Idempotente.

    Não ancora cadeia já corrompida (não mascara corrupção pré-existente)."""
    ok, bad = audit.verify()
    if not ok:
        raise AnchorError(
            f"cadeia já corrompida (linha {bad}); investigue antes de ancorar")
    count, tip = audit.estado()
    chave = _obter_chave(vault, passphrase, criar=True)
    ap = anchor_path(audit.path)
    log_id = uuid.uuid4().hex
    if ap.exists():                       # preserva log_id estável entre ancoragens
        with contextlib.suppress(Exception):
            log_id = json.loads(ap.read_text()).get("log_id", log_id)
    corpo = {
        "schema": SCHEMA,
        "entries_count": count,
        "chain_tip": tip,
        "log_id": log_id,
        "created_at": round(time.time(), 3),
    }
    corpo["hmac"] = _hmac(chave, corpo)
    ap.parent.mkdir(parents=True, exist_ok=True)
    tmp = ap.with_suffix(".tmp")
    tmp.write_text(json.dumps(corpo, ensure_ascii=False))
    chmod_privado(tmp, 0o600)
    tmp.replace(ap)
    chmod_privado(ap, 0o600)
    return corpo


def verificar(audit, vault=None, passphrase: str | None = None) -> tuple[str, str]:
    """(status, detalhe). Sempre checa a cadeia; checa a âncora se possível.

    Nunca imprime/loga a chave. Fail-closed: âncora que não pode ser provada NÃO
    vira PASS."""
    ok, bad = audit.verify()
    if not ok:
        return CHAIN_CORRUPTED, f"cadeia de auditoria quebrada na linha {bad}"

    ap = anchor_path(audit.path)
    tem_chave = vault is not None and chave_estabelecida(vault)

    if not ap.exists():
        if tem_chave:
            return (ANCHOR_MISSING,
                    "a chave de âncora existe no cofre, mas o arquivo de âncora "
                    "sumiu — possível remoção da prova de integridade")
        return (LEGACY_UNANCHORED,
                "sem âncora HMAC: a cadeia está íntegra, mas truncamento de cauda "
                "não é provado. Rode 'nomos logs anchor' para ancorar no cofre.")

    try:
        anc = json.loads(ap.read_text())
    except Exception:
        return ANCHORED_INVALID, "arquivo de âncora ilegível/corrompido"

    if vault is None or passphrase is None:
        return (ANCHOR_UNVERIFIED,
                "âncora presente; a verificação do HMAC exige o cofre (passphrase). "
                "Rode 'nomos logs verify --cofre'.")
    try:
        chave = _obter_chave(vault, passphrase, criar=False)
    except Exception:
        return (ANCHOR_MISSING,
                "chave HMAC ausente/inacessível no cofre (fail-closed)")

    if not hmac.compare_digest(str(anc.get("hmac", "")), _hmac(chave, anc)):
        return (ANCHORED_INVALID,
                "HMAC da âncora inválido — âncora adulterada ou chave incorreta")

    count, tip = audit.estado()
    ancorado = int(anc.get("entries_count", -1))
    if count < ancorado:
        return (TAIL_TRUNCATED,
                f"log tem {count} entradas, menos que as {ancorado} ancoradas "
                "(truncamento de cauda)")
    tip_no_ponto = audit.tip_em(ancorado)
    if tip_no_ponto != anc.get("chain_tip"):
        return (TAIL_TRUNCATED,
                "o tip no ponto ancorado diverge — cadeia reescrita ou truncada")
    if count > ancorado:
        return (ANCHORED_VALID,
                f"âncora válida; {count - ancorado} entrada(s) após a última "
                "âncora ainda não ancorada(s) — reancore para protegê-las")
    return (ANCHORED_VALID,
            "âncora válida: cadeia, contagem, tip e HMAC conferem")


def status_severidade(status: str) -> str:
    if status in PASS_STATES:
        return "PASS"
    if status in WARN_STATES:
        return "WARN"
    return "FAIL"
