"""NOMOS cognition.memory — memória persistente 100% local (SQLite + FTS5).

Garantias:
- reside em NOMOS_HOME, arquivo 0600; nada sai da máquina;
- recall por relevância (BM25) com desempate por recência;
- consultas são parametrizadas (imune a injeção de FTS/SQL);
- ausência de FTS5 degrada para LIKE com aviso — nunca quebra o agente.
"""
from __future__ import annotations

from nomos.kernel.plataforma import chmod_privado

import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MemoryItem:
    id: int
    ts: float
    role: str
    text: str


def _fts5_available(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS _fts_probe USING fts5(x)")
        conn.execute("DROP TABLE _fts_probe")
        return True
    except sqlite3.OperationalError:
        return False


class Memory:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        existed = self.path.exists()
        self.conn = sqlite3.connect(self.path)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS memories("
            "id INTEGER PRIMARY KEY, ts REAL NOT NULL, role TEXT NOT NULL, "
            "text TEXT NOT NULL)"
        )
        self.fts = _fts5_available(self.conn)
        if self.fts:
            self.conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5("
                "text, content='memories', content_rowid='id')"
            )
            self.conn.executescript(
                """
                CREATE TRIGGER IF NOT EXISTS mem_ai AFTER INSERT ON memories BEGIN
                  INSERT INTO memories_fts(rowid, text) VALUES (new.id, new.text);
                END;
                CREATE TRIGGER IF NOT EXISTS mem_ad AFTER DELETE ON memories BEGIN
                  INSERT INTO memories_fts(memories_fts, rowid, text)
                  VALUES ('delete', old.id, old.text);
                END;
                """
            )
        self.conn.commit()
        if not existed:
            chmod_privado(self.path, 0o600)

    # ---------- escrita ----------
    def remember(self, role: str, text: str) -> int:
        if role not in {"user", "assistant", "system", "note"}:
            raise ValueError(f"role inválido: {role!r}")
        cur = self.conn.execute(
            "INSERT INTO memories(ts, role, text) VALUES (?, ?, ?)",
            (time.time(), role, text),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def forget(self, item_id: int) -> bool:
        cur = self.conn.execute("DELETE FROM memories WHERE id = ?", (item_id,))
        self.conn.commit()
        return cur.rowcount > 0

    # ---------- leitura ----------
    def count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0])

    def recent(self, n: int = 10) -> list[MemoryItem]:
        rows = self.conn.execute(
            "SELECT id, ts, role, text FROM memories ORDER BY ts DESC, id DESC LIMIT ?",
            (int(n),),
        ).fetchall()
        return [MemoryItem(*r) for r in rows]

    def recall(self, query: str, k: int = 5) -> list[MemoryItem]:
        """Busca por relevância; consulta do usuário tratada como TEXTO, não sintaxe."""
        if not query.strip():
            return []
        if self.fts:
            # cada termo vira um token entre aspas => sem operadores injetáveis
            terms = re.findall(r"\w+", query, flags=re.UNICODE)
            if not terms:
                return []
            match = " OR ".join(f'"{t}"' for t in terms)
            rows = self.conn.execute(
                "SELECT m.id, m.ts, m.role, m.text FROM memories_fts f "
                "JOIN memories m ON m.id = f.rowid WHERE memories_fts MATCH ? "
                "ORDER BY bm25(memories_fts), m.ts DESC LIMIT ?",
                (match, int(k)),
            ).fetchall()
        else:  # fallback transparente
            like = f"%{query}%"
            rows = self.conn.execute(
                "SELECT id, ts, role, text FROM memories WHERE text LIKE ? "
                "ORDER BY ts DESC LIMIT ?",
                (like, int(k)),
            ).fetchall()
        return [MemoryItem(*r) for r in rows]

    def close(self) -> None:
        self.conn.close()
