"""NOMOS conversations.store — persistência local de conversas (F2).

SQLite ao lado do memory.db, arquivo 0600. Conversa PRIVADA nunca é persistida:
o modo privado usa um store em memória (`:memory:`) que some ao fechar — provado
por teste que inspeciona o disco.

Busca híbrida (palavra-chave FTS5 + significado via semantica.py, mesma stack da
memória). Título e tags são gerados LOCALMENTE (heurística), sem rede.
"""
from __future__ import annotations

import re
import sqlite3
import time
from pathlib import Path

from nomos.conversations.models import Conversation, Turn
from nomos.kernel.plataforma import chmod_privado

_STOP = {"o", "a", "os", "as", "de", "da", "do", "e", "que", "para", "com",
         "um", "uma", "no", "na", "em", "por", "meu", "minha", "se", "eu"}


class ConversationStore:
    def __init__(self, path: Path | str, privado: bool = False):
        self.privado = privado
        if privado:
            self.path = ":memory:"
            self.conn = sqlite3.connect(":memory:")
        else:
            self.path = Path(path)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            existia = self.path.exists()
            self.conn = sqlite3.connect(self.path)
            if not existia:
                chmod_privado(self.path, 0o600)
        self._migrar()

    # ---------- schema ----------
    def _migrar(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS conversas(
              id INTEGER PRIMARY KEY, criada_em REAL NOT NULL,
              titulo TEXT DEFAULT '', tags TEXT DEFAULT '',
              motor TEXT DEFAULT '', agente TEXT DEFAULT '',
              fixada INTEGER DEFAULT 0, usar_memoria INTEGER DEFAULT 1,
              ultima_ts REAL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS turnos(
              id INTEGER PRIMARY KEY, conversa_id INTEGER NOT NULL,
              ts REAL NOT NULL, role TEXT NOT NULL, text TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_turnos_conversa_id
              ON turnos(conversa_id);
            """
        )
        try:
            self.conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS turnos_fts USING fts5("
                "text, content='turnos', content_rowid='id')")
            # bases antigas não tinham o trigger de DELETE: o índice FTS
            # mantinha texto de turnos apagados (vazamento + rowid reusado).
            tinha_delete = self.conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='trigger' AND name='t_ad'"
            ).fetchone() is not None
            self.conn.executescript(
                """
                CREATE TRIGGER IF NOT EXISTS t_ai AFTER INSERT ON turnos BEGIN
                  INSERT INTO turnos_fts(rowid, text) VALUES (new.id, new.text);
                END;
                CREATE TRIGGER IF NOT EXISTS t_ad AFTER DELETE ON turnos BEGIN
                  INSERT INTO turnos_fts(turnos_fts, rowid, text)
                    VALUES ('delete', old.id, old.text);
                END;
                """)
            if not tinha_delete:
                # reconstrói o índice a partir do conteúdo real (remove órfãos)
                self.conn.execute(
                    "INSERT INTO turnos_fts(turnos_fts) VALUES('rebuild')")
            self.fts = True
        except sqlite3.OperationalError:
            self.fts = False
        self.conn.commit()

    # ---------- escrita ----------
    def nova_conversa(self, motor: str = "", agente: str = "") -> int:
        cur = self.conn.execute(
            "INSERT INTO conversas(criada_em, motor, agente, ultima_ts) "
            "VALUES (?, ?, ?, ?)", (time.time(), motor, agente, time.time()))
        self.conn.commit()
        return int(cur.lastrowid)

    def add_turno(self, conversa_id: int, role: str, text: str) -> int:
        if role not in {"user", "assistant", "system", "note"}:
            raise ValueError(f"role inválido: {role!r}")
        ts = time.time()
        cur = self.conn.execute(
            "INSERT INTO turnos(conversa_id, ts, role, text) VALUES (?, ?, ?, ?)",
            (conversa_id, ts, role, text))
        self.conn.execute("UPDATE conversas SET ultima_ts=? WHERE id=?",
                          (ts, conversa_id))
        self.conn.commit()
        # título automático local na 1ª fala do usuário
        if role == "user":
            atual = self.conn.execute(
                "SELECT titulo FROM conversas WHERE id=?", (conversa_id,)
            ).fetchone()
            if atual and not atual[0]:
                self._auto_titulo_tags(conversa_id, text)
        return int(cur.lastrowid)

    def _auto_titulo_tags(self, conversa_id: int, primeiro_texto: str) -> None:
        palavras = [w for w in re.findall(r"\w+", primeiro_texto.lower())
                    if w not in _STOP and len(w) > 2]
        titulo = " ".join(primeiro_texto.split()[:8])[:80] or "conversa"
        tags = ",".join(dict.fromkeys(palavras[:5]))
        self.conn.execute("UPDATE conversas SET titulo=?, tags=? WHERE id=?",
                          (titulo, tags, conversa_id))
        self.conn.commit()

    def fixar(self, conversa_id: int, fixada: bool = True) -> bool:
        cur = self.conn.execute("UPDATE conversas SET fixada=? WHERE id=?",
                                (1 if fixada else 0, conversa_id))
        self.conn.commit()
        return cur.rowcount > 0

    def definir_usar_memoria(self, conversa_id: int, usar: bool) -> bool:
        cur = self.conn.execute("UPDATE conversas SET usar_memoria=? WHERE id=?",
                                (1 if usar else 0, conversa_id))
        self.conn.commit()
        return cur.rowcount > 0

    def esquecer(self, conversa_id: int) -> bool:
        c = self.conn.execute("DELETE FROM conversas WHERE id=?", (conversa_id,))
        self.conn.execute("DELETE FROM turnos WHERE conversa_id=?", (conversa_id,))
        self.conn.commit()
        return c.rowcount > 0

    # ---------- leitura ----------
    # Achado P1-8 da auditoria de 2026-07-17: `_linha_conversa` disparava um
    # `SELECT COUNT(*) FROM turnos WHERE conversa_id=?` PRÓPRIO para cada
    # linha — um N+1 clássico (`listar(50)` = 51 statements, `buscar(k=10)`
    # ~31, medido via `sqlite3.set_trace_callback()` na Fase 6). Agora quem
    # chama já traz a contagem pronta (agregada num único GROUP BY, ou —
    # em `abrir()` — derivada do próprio `len(turnos)` que já foi buscado),
    # e este método só monta o objeto: nunca mais executa uma query.
    def _linha_conversa(self, r, n_turnos: int) -> Conversation:
        return Conversation(id=r[0], criada_em=r[1], titulo=r[2],
                            tags=[t for t in (r[3] or "").split(",") if t],
                            motor=r[4], agente=r[5], fixada=bool(r[6]),
                            usar_como_memoria=bool(r[7]), ultima_ts=r[8],
                            n_turnos=n_turnos)

    def listar(self, limite: int = 50) -> list[Conversation]:
        rows = self.conn.execute(
            "SELECT c.id,c.criada_em,c.titulo,c.tags,c.motor,c.agente,"
            "c.fixada,c.usar_memoria,c.ultima_ts,COUNT(t.id) FROM conversas c "
            "LEFT JOIN turnos t ON t.conversa_id=c.id "
            "GROUP BY c.id ORDER BY c.fixada DESC, c.ultima_ts DESC "
            "LIMIT ?", (int(limite),)).fetchall()
        return [self._linha_conversa(r[:9], r[9]) for r in rows]

    def abrir(self, conversa_id: int) -> tuple[Conversation | None, list[Turn]]:
        r = self.conn.execute(
            "SELECT id,criada_em,titulo,tags,motor,agente,fixada,usar_memoria,"
            "ultima_ts FROM conversas WHERE id=?", (conversa_id,)).fetchone()
        if not r:
            return None, []
        turnos = [Turn(*t) for t in self.conn.execute(
            "SELECT id,conversa_id,ts,role,text FROM turnos WHERE conversa_id=? "
            "ORDER BY ts, id", (conversa_id,)).fetchall()]
        return self._linha_conversa(r, len(turnos)), turnos

    def buscar(self, termo: str, k: int = 10) -> list[tuple[Conversation, str]]:
        """(conversa, trecho) por palavra-chave + significado, sem rede."""
        if not termo.strip():
            return []
        achados: dict[int, str] = {}
        if self.fts:
            termos = re.findall(r"\w+", termo, re.UNICODE)
            if termos:
                match = " OR ".join(f'"{t}"' for t in termos)
                for cid, text in self.conn.execute(
                    "SELECT t.conversa_id, t.text FROM turnos_fts f "
                    "JOIN turnos t ON t.id=f.rowid WHERE turnos_fts MATCH ? "
                    "ORDER BY bm25(turnos_fts) LIMIT ?", (match, k * 3)):
                    achados.setdefault(cid, text[:120])
        # completa por significado
        if len(achados) < k:
            from nomos.cognition import semantica
            todos = self.conn.execute(
                "SELECT conversa_id, text FROM turnos ORDER BY ts DESC LIMIT 500"
            ).fetchall()
            if todos:
                ordem = semantica.ranquear(termo, [t[1] for t in todos], k=k)
                for i, _ in ordem:
                    cid = todos[i][0]
                    achados.setdefault(cid, todos[i][1][:120])
        ids = list(achados)[:k]
        if not ids:
            return []
        # achado P1-8: um único SELECT com contagem agregada por id, em vez
        # de `abrir()` (2 queries cada) para cada um dos k achados.
        marcadores = ",".join("?" * len(ids))
        rows = self.conn.execute(
            "SELECT c.id,c.criada_em,c.titulo,c.tags,c.motor,c.agente,"
            "c.fixada,c.usar_memoria,c.ultima_ts,COUNT(t.id) FROM conversas c "
            f"LEFT JOIN turnos t ON t.conversa_id=c.id WHERE c.id IN "
            f"({marcadores}) GROUP BY c.id", ids).fetchall()
        por_id = {r[0]: self._linha_conversa(r[:9], r[9]) for r in rows}
        saida = []
        for cid in ids:
            conv = por_id.get(cid)
            if conv:
                saida.append((conv, achados[cid]))
        return saida

    def turnos_para_contexto(self, conversa_id: int, n: int = 6) -> list[dict]:
        """Últimos turnos de uma conversa como mensagens (para /continuar)."""
        _, turnos = self.abrir(conversa_id)
        return [{"role": t.role, "content": t.text}
                for t in turnos[-n:] if t.role in {"user", "assistant"}]

    def exportar_itens(self) -> list[dict]:
        """Dump serializável (para export cifrado)."""
        out = []
        for c in self.listar(limite=100000):
            _, turnos = self.abrir(c.id)
            out.append({"conversa": c.__dict__,
                        "turnos": [t.__dict__ for t in turnos]})
        return out

    def importar_itens(self, itens: list[dict]) -> int:
        n = 0
        for item in itens:
            c = item.get("conversa", {})
            cid = self.nova_conversa(c.get("motor", ""), c.get("agente", ""))
            self.conn.execute(
                "UPDATE conversas SET titulo=?, tags=?, fixada=?, usar_memoria=? "
                "WHERE id=?", (c.get("titulo", ""), ",".join(c.get("tags", [])),
                               1 if c.get("fixada") else 0,
                               1 if c.get("usar_como_memoria", True) else 0, cid))
            for t in item.get("turnos", []):
                self.add_turno(cid, t.get("role", "note"), t.get("text", ""))
            n += 1
        self.conn.commit()
        return n

    def count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM conversas").fetchone()[0])

    def close(self) -> None:
        self.conn.close()
