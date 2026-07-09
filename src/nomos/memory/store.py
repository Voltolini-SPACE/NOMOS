"""NOMOS Memory Engine — camada de armazenamento local-first.

Responsabilidade única: **onde** e **como** a memória vive no disco. Não decide
o que pode entrar (isso é da ``policy``) nem como compactar (isso é do
``compactor``). Aqui só existe leitura/escrita auditável.

Garantias desta camada
----------------------
- 100% local: tudo dentro de ``NOMOS_HOME/memory`` (padrão ``~/.nomos/memory``);
  nenhuma rede, nenhum subprocesso, apenas biblioteca padrão do Python.
- Histórico bruto é **append-only**: ``memory.jsonl`` nunca é reescrito nem
  apagado por esta camada — só recebe novas linhas.
- Cada entrada carrega um ``hash`` SHA-256 sobre seu conteúdo canônico; a
  adulteração manual de qualquer campo é detectável (ver ``recompute_hash``).
- Arquivos nascem com permissão 0600 e o diretório 0700 (quando o SO suporta).
- Escritas de arquivos derivados (compactado, índice, relatórios) são atômicas
  (grava em ``.tmp`` e faz ``os.replace``) para nunca deixar arquivo pela metade.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# Nomes de arquivo fixos — contrato público do formato local.
RAW_NAME = "memory.jsonl"            # histórico bruto, append-only
COMPACTED_NAME = "memory.compacted.jsonl"  # derivado da compactação
INDEX_NAME = "memory.index.json"     # índice/estatística (derivado)
REPORTS_DIR = "reports"              # evidências operacionais

# Campos que compõem o "núcleo" de uma entrada — o hash cobre exatamente estes.
CORE_FIELDS = (
    "id",
    "created_at",
    "source",
    "scope",
    "priority",
    "tags",
    "content",
    "links",
    "safety",
)


def _default_base() -> Path:
    """Base de dados da memória. Espelha ``nomos.kernel.config.nomos_home()``
    sem importar o resto do pacote (mantém este módulo isolado e testável):
    respeita ``NOMOS_HOME`` para isolamento em testes, senão ``~/.nomos``."""
    definido = os.environ.get("NOMOS_HOME")
    raiz = Path(definido) if definido else Path.home() / ".nomos"
    return raiz / "memory"


def _chmod(caminho: Path, modo: int) -> None:
    """Restringe permissões; ignora onde o SO não suporta (ex.: Windows)."""
    try:
        os.chmod(caminho, modo)
    except (OSError, NotImplementedError):
        pass


def now_iso() -> str:
    """Instante atual em ISO-8601 UTC com sufixo Z (sem dependências externas)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_id(content: str, created_at: str | None = None) -> str:
    """ID no formato ``mem_YYYYMMDDHHMMSS_<hash8>``. O nonce (uuid4) evita
    colisão quando dois conteúdos iguais entram no mesmo segundo."""
    created_at = created_at or now_iso()
    stamp = re.sub(r"[^0-9]", "", created_at)[:14]
    h = hashlib.sha256((content + created_at + uuid.uuid4().hex).encode("utf-8")).hexdigest()[:8]
    return f"mem_{stamp}_{h}"


def finalize_entry(entry: dict) -> dict:
    """Devolve a entrada com o campo ``hash`` preenchido sobre o núcleo."""
    entry = dict(entry)
    entry["hash"] = compute_hash(entry)
    return entry


def canonical_core(entry: dict) -> str:
    """Serialização determinística do núcleo da entrada (sem o campo ``hash``).

    Chaves ordenadas e separadores compactos garantem que o mesmo conteúdo
    produza sempre a mesma string — base de um hash reprodutível.
    """
    core = {k: entry[k] for k in CORE_FIELDS if k in entry}
    return json.dumps(core, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def compute_hash(entry: dict) -> str:
    """SHA-256 (hex) sobre o núcleo canônico da entrada."""
    return hashlib.sha256(canonical_core(entry).encode("utf-8")).hexdigest()


def recompute_hash(entry: dict) -> str:
    """Alias explícito usado pela validação de integridade."""
    return compute_hash(entry)


@dataclass(frozen=True)
class StorePaths:
    base: Path
    raw: Path
    compacted: Path
    index: Path
    reports: Path


class MemoryStore:
    """Acesso auditável aos arquivos da memória local. Sem efeitos colaterais
    na importação: nada é criado até uma escrita explícita."""

    def __init__(self, base_dir: str | os.PathLike | None = None) -> None:
        base = Path(base_dir) if base_dir is not None else _default_base()
        self.paths = StorePaths(
            base=base,
            raw=base / RAW_NAME,
            compacted=base / COMPACTED_NAME,
            index=base / INDEX_NAME,
            reports=base / REPORTS_DIR,
        )

    # ---------- infraestrutura ----------
    def ensure_dirs(self) -> None:
        self.paths.base.mkdir(parents=True, exist_ok=True)
        _chmod(self.paths.base, 0o700)
        self.paths.reports.mkdir(parents=True, exist_ok=True)
        _chmod(self.paths.reports, 0o700)

    def _atomic_write(self, path: Path, text: str) -> None:
        self.paths.base.mkdir(parents=True, exist_ok=True)
        _chmod(self.paths.base, 0o700)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        _chmod(tmp, 0o600)
        os.replace(tmp, path)
        _chmod(path, 0o600)

    # ---------- histórico bruto (append-only) ----------
    def append_raw(self, entry: dict) -> None:
        """Anexa UMA entrada ao histórico bruto. Nunca reescreve o arquivo."""
        self.ensure_dirs()
        existed = self.paths.raw.exists()
        line = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
        with self.paths.raw.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        if not existed:
            _chmod(self.paths.raw, 0o600)

    def read_raw(self) -> list[dict]:
        return self._read_jsonl(self.paths.raw)

    def read_compacted(self) -> list[dict]:
        return self._read_jsonl(self.paths.compacted)

    @staticmethod
    def _read_jsonl(path: Path) -> list[dict]:
        if not path.exists():
            return []
        out: list[dict] = []
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            s = raw_line.strip()
            if not s:
                continue
            out.append(json.loads(s))
        return out

    # ---------- arquivos derivados ----------
    def write_compacted(self, entries: list[dict]) -> None:
        """Grava o arquivo DERIVADO da compactação. O bruto nunca é tocado."""
        text = "".join(
            json.dumps(e, ensure_ascii=False, separators=(",", ":")) + "\n"
            for e in entries
        )
        self._atomic_write(self.paths.compacted, text)

    def write_index(self, index: dict) -> None:
        self._atomic_write(
            self.paths.index,
            json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True),
        )

    def read_index(self) -> dict:
        if not self.paths.index.exists():
            return {}
        return json.loads(self.paths.index.read_text(encoding="utf-8"))

    def write_report(self, name: str, text: str) -> Path:
        self.ensure_dirs()
        # sanitiza o nome para nunca escapar da pasta de relatórios
        safe = "".join(c for c in name if c.isalnum() or c in ("-", "_", "."))
        if not safe:
            safe = "report.md"
        path = self.paths.reports / safe
        self._atomic_write(path, text)
        return path

    # ---------- índice ----------
    def build_index(self) -> dict:
        raw = self.read_raw()
        by_source: dict[str, int] = {}
        by_priority: dict[str, int] = {}
        tags: dict[str, int] = {}
        for e in raw:
            by_source[e.get("source", "?")] = by_source.get(e.get("source", "?"), 0) + 1
            by_priority[e.get("priority", "?")] = by_priority.get(e.get("priority", "?"), 0) + 1
            for t in e.get("tags", []) or []:
                tags[t] = tags.get(t, 0) + 1
        return {
            "schema": 1,
            "total_raw": len(raw),
            "total_compacted": len(self.read_compacted()),
            "by_source": by_source,
            "by_priority": by_priority,
            "tags": tags,
            "ids": [e.get("id") for e in raw],
        }
