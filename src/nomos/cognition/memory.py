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


# Heurística LOCAL e transparente (sem IA) para reconhecer fatos/preferências/
# tarefas duráveis numa fala do usuário. Compartilhada por dois consumidores
# com filosofias diferentes (P2-1, auditoria de 2026-07-17):
#   - Memory.consolidar(): varre o HISTÓRICO já salvo e grava direto (sem
#     revisão) — feature madura, contrato próprio, comportamento inalterado.
#   - Memory.propor_candidatas_do_texto(): aplica a MESMA heurística a uma
#     fala isolada, EM TEMPO REAL, mas propõe como candidata sujeita a
#     revisão humana em vez de gravar direto — é o produtor real que faltava
#     para a fila de candidatas (ISSUE-020), que antes só era alimentada
#     manualmente em teste.
# Cada padrão carrega (regex, prefixo-cosmético-para-nota, tipo-válido-para-
# remember_typed/propor_candidata — precisa bater com `tipos_ok` abaixo).
_PADROES_FATOS: tuple[tuple[re.Pattern, str, str], ...] = (
    (re.compile(r"\bprefiro\b(.{4,80})", re.I), "preferência:", "preferencia"),
    (re.compile(r"\bmeu aniversário\b(.{2,40})", re.I), "data:", "fato"),
    (re.compile(r"\bmeu (nome|email|telefone|endereço) (?:é|eh)(.{2,60})", re.I),
     "fato:", "fato"),
    (re.compile(r"\bminha (cor|comida|música|musica) favorita (?:é|eh)(.{2,60})",
                re.I), "preferência:", "preferencia"),
    (re.compile(r"\b(?:preciso|tenho que|não posso esquecer de)(.{4,90})",
                re.I), "tarefa:", "tarefa"),
)


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
        self._migrar_tipos()   # F4: colunas tipo/fonte/confianca (aditivo)
        self.conn.commit()
        if not existed:
            chmod_privado(self.path, 0o600)

    def _migrar_tipos(self) -> None:
        """F4/ISSUE-019: memória tipada. Colunas novas com padrão seguro; bancos
        antigos migram sem perder nada (turnos viram tipo 'conversa')."""
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(memories)")}
        for nome, ddl in (("tipo", "TEXT DEFAULT ''"),
                          ("fonte", "TEXT DEFAULT ''"),
                          ("confianca", "REAL DEFAULT 1.0")):
            if nome not in cols:
                self.conn.execute(f"ALTER TABLE memories ADD COLUMN {nome} {ddl}")
        # tabela de candidatas aguardando aprovação (ISSUE-020)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS mem_candidatas("
            "id INTEGER PRIMARY KEY, ts REAL NOT NULL, tipo TEXT NOT NULL, "
            "text TEXT NOT NULL, fonte TEXT DEFAULT '')")

    # ---------- escrita ----------
    def remember(self, role: str, text: str) -> int:
        if role not in {"user", "assistant", "system", "note"}:
            raise ValueError(f"role inválido: {role!r}")
        cur = self.conn.execute(
            "INSERT INTO memories(ts, role, text) VALUES (?, ?, ?)",
            (time.time(), role, text),
        )
        self.conn.commit()
        # Horizonte 3/item 3: lastrowid é `int | None` na assinatura do
        # sqlite3 (só None sem INSERT bem-sucedido — não é o caso logo
        # após um INSERT real); assert documenta a garantia para o mypy,
        # sem mudar o caminho feliz (int(None) já levantaria TypeError
        # antes desta mudança).
        assert cur.lastrowid is not None
        return int(cur.lastrowid)

    def remember_typed(self, text: str, tipo: str = "fato", fonte: str = "usuario",
                       confianca: float = 1.0) -> int:
        """F4: memória tipada (fato/preferencia/tarefa/projeto/contato/decisao/
        regra). Guardada como role='note' para compat total com a busca."""
        tipos_ok = {"fato", "preferencia", "tarefa", "projeto", "contato",
                    "decisao", "regra", "conversa"}
        if tipo not in tipos_ok:
            raise ValueError(f"tipo de memória inválido: {tipo!r}")
        cur = self.conn.execute(
            "INSERT INTO memories(ts, role, text, tipo, fonte, confianca) "
            "VALUES (?, 'note', ?, ?, ?, ?)",
            (time.time(), text, tipo, fonte, float(confianca)))
        self.conn.commit()
        assert cur.lastrowid is not None    # mesma garantia de remember(), acima
        return int(cur.lastrowid)

    def contradicoes(self, text: str, k: int = 3) -> list:
        """Memórias existentes muito parecidas — candidatas a contradição."""
        return [i for i in self.recall_hibrido(text, k=k)
                if i.role == "note" and i.text != text]

    # candidatas (ISSUE-020): "você quer que eu lembre disso?"
    def propor_candidata(self, text: str, tipo: str = "fato",
                         fonte: str = "conversa") -> int:
        cur = self.conn.execute(
            "INSERT INTO mem_candidatas(ts, tipo, text, fonte) VALUES (?, ?, ?, ?)",
            (time.time(), tipo, text, fonte))
        self.conn.commit()
        assert cur.lastrowid is not None    # mesma garantia de remember(), acima
        return int(cur.lastrowid)

    def propor_candidatas_do_texto(self, text: str, fonte: str = "chat") -> list[int]:
        """P2-1 (auditoria de 2026-07-17): produtor real para a fila de
        `propor_candidata()`. Antes desta função, NADA no NOMOS chamava
        `propor_candidata()` fora de teste — a fila de revisão (`nomos
        memoria candidatas`/`revisar`, badge do painel) existia e funcionava,
        mas ficava sempre vazia em uso real.

        Aplica a MESMA heurística local de `consolidar()` (mesmos padrões,
        `_PADROES_FATOS`) a uma única fala do usuário — pensada para ser
        chamada ao vivo, a cada turno de chat — mas em vez de gravar direto
        (como `consolidar()` faz em lote), propõe como candidata sujeita a
        revisão humana: preserva a intenção original do ISSUE-020 ("você
        quer que eu lembre disso?") em vez de decidir sozinha.

        Dedup: nunca repete uma candidata já pendente nem um fato já
        aprovado com o mesmo texto formatado — falar a mesma coisa em vários
        turnos não enche a fila de revisão de repetição. Devolve os ids das
        candidatas novas (lista vazia se nada bateu ou tudo já era conhecido).
        """
        ja_visto = {c["text"] for c in self.candidatas()}
        ja_visto |= {i.text for i in self.recent(10_000) if i.role == "note"}
        novas: list[int] = []
        for pat, prefixo, tipo in _PADROES_FATOS:
            m = pat.search(text)
            if not m:
                continue
            if (m.lastindex or 1) >= 2:
                trecho = f"{m.group(1).strip()}: {m.group(2).strip(' .,;')}"
            else:
                trecho = m.group(1).strip(" .,;")
            nota = f"{prefixo} {trecho}"[:160]
            if nota in ja_visto or len(trecho) <= 3:
                continue
            novas.append(self.propor_candidata(nota, tipo=tipo, fonte=fonte))
            ja_visto.add(nota)
        return novas

    def candidatas(self) -> list[dict]:
        return [{"id": r[0], "tipo": r[1], "text": r[2], "fonte": r[3]}
                for r in self.conn.execute(
                    "SELECT id, tipo, text, fonte FROM mem_candidatas ORDER BY ts")]

    def aprovar_candidata(self, cid: int) -> int | None:
        r = self.conn.execute(
            "SELECT tipo, text, fonte FROM mem_candidatas WHERE id=?", (cid,)
        ).fetchone()
        if not r:
            return None
        mid = self.remember_typed(r[1], tipo=r[0], fonte=r[2])
        self.conn.execute("DELETE FROM mem_candidatas WHERE id=?", (cid,))
        self.conn.commit()
        return mid

    def descartar_candidata(self, cid: int) -> bool:
        c = self.conn.execute("DELETE FROM mem_candidatas WHERE id=?", (cid,))
        self.conn.commit()
        return c.rowcount > 0

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
        else:  # fallback transparente: OR de termos (LIKE de frase inteira não
            # casaria "pagamento aluguel" com "pagamento do aluguel")
            terms = re.findall(r"\w+", query, flags=re.UNICODE) or [query]
            cond = " OR ".join("text LIKE ?" for _ in terms)
            rows = self.conn.execute(
                f"SELECT id, ts, role, text FROM memories WHERE {cond} "  # nosec B608 - placeholders
                "ORDER BY ts DESC LIMIT ?",
                (*[f"%{t}%" for t in terms], int(k)),
            ).fetchall()
        return [MemoryItem(*r) for r in rows]

    def recall_hibrido(self, query: str, k: int = 5,
                       janela_semantica: int = 500) -> list[MemoryItem]:
        """Busca híbrida (v0.14): palavras-chave (FTS/LIKE) + significado.

        1º os acertos por palavra-chave (comportamento clássico preservado,
        mas sem deixar palavrinhas vazias tipo "da/de/em" dominarem a busca);
        depois completa com os mais parecidos POR SIGNIFICADO (semântica local,
        sem rede) dentre as memórias recentes. Nunca devolve duplicado.
        """
        _stop = {"da", "de", "do", "das", "dos", "em", "no", "na", "nos", "nas",
                 "um", "uma", "o", "a", "os", "as", "e", "ou", "que", "com",
                 "por", "para", "pra", "pelo", "pela", "meu", "minha", "se"}
        relevantes = [w for w in re.findall(r"\w+", query, flags=re.UNICODE)
                      if w.lower() not in _stop]
        consulta_kw = " ".join(relevantes) if relevantes else query
        exatos = self.recall(consulta_kw, k)
        if len(exatos) >= k or not query.strip():
            return exatos[:k]
        vistos = {i.id for i in exatos}
        candidatos = [i for i in self.recent(janela_semantica)
                      if i.id not in vistos]
        if candidatos:
            from nomos.cognition import semantica
            ordem = semantica.ranquear(query, [c.text for c in candidatos],
                                       k=k - len(exatos))
            exatos += [candidatos[i] for i, _ in ordem]
        return exatos[:k]

    def consolidar(self, limite: int = 500) -> list[str]:
        """Extrai fatos/preferências/tarefas duráveis das conversas → notas.

        Heurística LOCAL e transparente (sem IA): padrões explícitos do
        usuário viram notas prefixadas, deduplicadas. Devolve as notas criadas.
        """
        ja_notado = {i.text for i in self.recent(10_000) if i.role == "note"}
        # P2-1: também não duplica o que já está PENDENTE de revisão humana
        # (mem_candidatas) — sem isso, uma fala capturada em tempo real por
        # propor_candidatas_do_texto() e ainda não revisada seria gravada de
        # novo aqui direto, sem passar pela revisão, na primeira rodada de
        # `nomos memoria consolidar`/rotina agendada.
        ja_notado |= {c["text"] for c in self.candidatas()}
        criadas: list[str] = []
        for item in self.recent(limite):
            if item.role != "user":
                continue
            for pat, prefixo, _tipo in _PADROES_FATOS:
                m = pat.search(item.text)
                if not m:
                    continue
                if (m.lastindex or 1) >= 2:
                    # padrões com qualificador: "meu email é X" → "email: X"
                    # (sem isso a nota vira só "fato: X", ambígua no recall)
                    trecho = f"{m.group(1).strip()}: {m.group(2).strip(' .,;')}"
                else:
                    trecho = m.group(1).strip(" .,;")
                nota = f"{prefixo} {trecho}"[:160]
                if nota not in ja_notado and len(trecho) > 3:
                    self.remember("note", nota)
                    ja_notado.add(nota)
                    criadas.append(nota)
        return criadas

    def close(self) -> None:
        self.conn.close()
