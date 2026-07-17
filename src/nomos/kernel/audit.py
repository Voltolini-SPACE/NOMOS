"""NOMOS kernel.audit — trilha de evidências com cadeia de hash e redação.

Garantias:
- cada registro referencia o hash do anterior (adulteração quebra a cadeia);
- segredos nunca entram no log: redação por nome de campo e por padrão de valor;
- verify() detecta o primeiro ponto de violação.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import re
import threading
import time
from pathlib import Path

GENESIS = "0" * 64
REDACTED = "[REDIGIDO]"

# Campos cujo VALOR jamais pode ser registrado.
SENSITIVE_KEYS = {
    "secret", "segredo", "passphrase", "password", "senha",
    "token", "api_key", "apikey", "key", "authorization", "credential",
    "chave", "credencial",
}

# Padrões de valores que denunciam segredos mesmo em campos "inocentes".
# Fase 0 (higiene pós-validação): a auditoria original só reconhecia 5 formas
# fixas de segredo — qualquer coisa fora desse formato (senha genérica, token
# de webhook, chave do Slack/Google) em um campo de nome inesperado passava
# direto pela redação por nome (SENSITIVE_KEYS) e chegava ilegível ao log. Os
# 4 padrões novos abaixo fecham esse buraco; cada um foi escolhido porque o
# próprio MATCH cobre rótulo+valor (seguro para .sub() — substituição
# parcial), diferente de assinaturas "só cabeçalho" (ex.: bloco
# "-----BEGIN PRIVATE KEY-----", que só marca o início de um segredo
# multi-linha): essas ficam de fora de propósito, porque uma substituição por
# padrão não apagaria o corpo da chave que vem nas linhas seguintes — exigem
# redação por CAMPO inteiro, não por substring, e ficam para uma missão
# própria (ver docs/missions da Fase 0). Mesmas assinaturas usadas em
# nomos.memory.policy, duplicadas aqui de propósito: kernel/ não importa
# memory/ para preservar o isolamento stdlib-only do Memory Engine.
SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._-]{8,}"),
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}"),  # JWT
    re.compile(r"AIza[0-9A-Za-z_-]{20,}"),                    # Google API key
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),               # Slack token
    re.compile(
        r"(?i)(?:process\.env\.[A-Z0-9_]*(?:KEY|SECRET|TOKEN|PASSWORD|PWD)"
        r"\s*[:=]\s*['\"]?\S+"
        r"|os\.environ\[['\"][A-Z0-9_]*(?:KEY|SECRET|TOKEN|PASSWORD)['\"]\]"
        r"\s*[:=]\s*['\"]?\S+"
        r"|export\s+[A-Z0-9_]*(?:KEY|SECRET|TOKEN|PASSWORD)\s*=\s*\S+)"
    ),
    re.compile(
        r"(?i)\b(?:api[_\- ]?key|secret|client[_\- ]?secret|access[_\- ]?token"
        r"|auth[_\- ]?token|senha|password|passwd|pwd)\b\s*[:=]\s*['\"]?\S{6,}"
    ),
]


def _scrub_value(value):
    if isinstance(value, str):
        out = value
        for pat in SECRET_PATTERNS:
            out = pat.sub(REDACTED, out)
        return out
    if isinstance(value, dict):
        return redact(value)
    if isinstance(value, (list, tuple)):
        return [_scrub_value(v) for v in value]
    return value


def redact_text(text: str) -> str:
    """Redige padrões de segredo em texto livre (ex.: stdout de sandbox)."""
    out = text
    for pat in SECRET_PATTERNS:
        out = pat.sub(REDACTED, out)
    return out


def redact(fields: dict) -> dict:
    clean: dict = {}
    for k, v in fields.items():
        if k.lower() in SENSITIVE_KEYS:
            clean[k] = REDACTED
        else:
            clean[k] = _scrub_value(v)
    return clean


def _canonical(record: dict) -> str:
    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


# um lock por arquivo de trilha: appends concorrentes (painel em
# ThreadingHTTPServer + CLI) não podem bifurcar a cadeia de hash
_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_de(path: Path) -> threading.Lock:
    key = str(path)
    with _LOCKS_GUARD:
        lk = _LOCKS.get(key)
        if lk is None:
            lk = _LOCKS[key] = threading.Lock()
        return lk


class AuditLog:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = _lock_de(self.path.resolve())
        # cache de (tip, valid_end, size) — achado P1-9 da auditoria de
        # 2026-07-17: append() chamava _tail_scan() (relê o arquivo
        # inteiro) a cada gravação — O(n) por chamada, O(n²) agregado para
        # N gravações sequenciais (medido: 0.21ms/chamada com 100 linhas
        # -> 15.46ms/chamada com 10.000). Ver _tail_scan_cached().
        self._cache: tuple[str, int, int] | None = None

    @contextlib.contextmanager
    def _flock(self):
        """Trava de arquivo best-effort para escritores em OUTRO processo
        (painel + CLI ao mesmo tempo). POSIX: fcntl.flock; sem suporte
        (ex.: Windows), degrada para o lock in-process apenas."""
        try:
            import fcntl
        except ImportError:
            yield
            return
        lockfile = self.path.with_suffix(self.path.suffix + ".lock")
        with lockfile.open("a") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                yield
            finally:
                with contextlib.suppress(OSError):
                    fcntl.flock(fh, fcntl.LOCK_UN)

    def _tail_scan(self) -> tuple[str, int, int]:
        """Um passo só: (hash do último registro VÁLIDO, offset em bytes do
        fim da última linha válida, tamanho do arquivo).

        Linhas inválidas no MEIO (legado) não são tocadas — mas uma CAUDA
        ilegível (crash/disco cheio a meio-append) é detectável: offset
        válido < tamanho. append() repara truncando a cauda — sem isso o
        lixo ficaria no meio do arquivo e verify() acusaria violação para
        sempre, mesmo a trilha nunca tendo sido adulterada."""
        tip, valid_end, pos = GENESIS, 0, 0
        if not self.path.exists():
            return tip, 0, 0
        with self.path.open("rb") as fh:
            for raw in fh:
                pos += len(raw)
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    if raw.endswith(b"\n"):
                        valid_end = pos
                    continue
                if not raw.endswith(b"\n"):
                    continue   # cauda sem \n = escrita parcial (inválida)
                try:
                    tip = json.loads(line).get("hash", tip)
                    valid_end = pos
                except json.JSONDecodeError:
                    continue
        return tip, valid_end, pos

    def _last_hash(self) -> str:
        # tolerante a linha final parcial (crash/disco cheio no meio de um
        # append): usa o ÚLTIMO registro válido — sem isso, json.loads
        # estouraria aqui e travaria TODA auditoria futura
        tip, _, _ = self._tail_scan()
        return tip

    def _tail_scan_cached(self) -> tuple[str, int, int]:
        """Como `_tail_scan()`, mas evita reler o arquivo inteiro quando o
        cache em memória desta instância ainda bate com o tamanho REAL do
        arquivo no disco (checagem O(1) via `stat()`).

        Continua seguro sob qualquer cenário que mudaria o arquivo por fora
        do cache: outro processo/instância escreveu (painel + CLI ao mesmo
        tempo — cada `AuditLog` tem seu próprio `_cache`, mas todos que
        apontam para o mesmo caminho competem pelo mesmo lock, e o `stat()`
        aqui sempre reflete a escrita mais recente de QUALQUER um deles);
        crash/disco cheio deixou cauda parcial; alguém truncou/corrompeu o
        arquivo manualmente. Em qualquer divergência de tamanho, cai para o
        scan completo — a otimização nunca troca correção por velocidade."""
        try:
            tamanho_real = self.path.stat().st_size
        except FileNotFoundError:
            tamanho_real = 0
        if self._cache is not None and self._cache[2] == tamanho_real:
            return self._cache
        estado = self._tail_scan()
        self._cache = estado
        return estado

    def append(self, event: str, **fields) -> dict:
        with self._lock, self._flock():
            tip, valid_end, size = self._tail_scan_cached()
            if valid_end < size:
                # cauda ilegível: repara ANTES de anexar, para o lixo nunca
                # ficar no meio da cadeia (recuperação alinhada com verify)
                with self.path.open("rb+") as fh:
                    fh.truncate(valid_end)
            record = {
                "ts": round(time.time(), 3),
                "event": event,
                **redact(fields),
                "prev": tip,
            }
            record["hash"] = hashlib.sha256(
                (record["prev"] + _canonical({k: v for k, v in record.items() if k != "hash"}))
                .encode("utf-8")
            ).hexdigest()
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(_canonical(record) + "\n")
            # atualiza o cache com o tamanho REAL pós-escrita (stat() é
            # O(1) e evita qualquer suposição sobre bytes/newlines — no
            # Windows, texto em modo "a" pode traduzir "\n" para "\r\n"; sem
            # o stat(), o tamanho calculado na mão divergiria do disco).
            tamanho_novo = self.path.stat().st_size
            self._cache = (record["hash"], tamanho_novo, tamanho_novo)
        return record

    def estado(self) -> tuple[int, str]:
        """(nº de entradas, hash da última). Base para a âncora HMAC (audit_anchor)."""
        count, tip = 0, GENESIS
        if not self.path.exists():
            return 0, GENESIS
        with self.path.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    count += 1
                    try:
                        tip = json.loads(line).get("hash", tip)
                    except json.JSONDecodeError:
                        return count, tip
        return count, tip

    def tip_em(self, n: int) -> str | None:
        """Hash da n-ésima entrada (1-based); GENESIS se n<=0; None se n além do fim."""
        if n <= 0:
            return GENESIS
        if not self.path.exists():
            return None
        i = 0
        with self.path.open(encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                i += 1
                if i == n:
                    try:
                        return json.loads(line).get("hash", GENESIS)
                    except json.JSONDecodeError:
                        return None
        return None

    def verify(self) -> tuple[bool, int]:
        """Retorna (íntegro, índice_da_primeira_violação|-1)."""
        if not self.path.exists():
            return True, -1
        prev = GENESIS
        with self.path.open(encoding="utf-8") as fh:
            for idx, line in enumerate(fh):
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    return False, idx
                if rec.get("prev") != prev:
                    return False, idx
                expected = hashlib.sha256(
                    (rec["prev"] + _canonical({k: v for k, v in rec.items() if k != "hash"}))
                    .encode("utf-8")
                ).hexdigest()
                if rec.get("hash") != expected:
                    return False, idx
                prev = rec["hash"]
        return True, -1
