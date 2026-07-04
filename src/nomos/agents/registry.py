"""NOMOS agents.registry — instalar/listar agentes + roteamento por intenção (F3).

Agentes oficiais vivem em `examples/agents/`; o usuário pode instalar os seus em
NOMOS_HOME/agents/. Instalar valida o manifesto (mesma severidade das skills).
O roteamento por intenção é determinístico (keywords), como skill_intencao.
"""
from __future__ import annotations

import json
import unicodedata
from pathlib import Path

from nomos.agents.manifest import AgentManifest, validar


class AgentError(Exception):
    pass


def _normalizar(t: str) -> str:
    t = unicodedata.normalize("NFKD", (t or "").lower())
    return "".join(c for c in t if not unicodedata.combining(c))


class AgentRegistry:
    def __init__(self, home: Path, extras_dir: Path | None = None):
        self.home = Path(home)
        self.dir = self.home / "agents"
        self.extras_dir = Path(extras_dir) if extras_dir else None

    def _fontes(self):
        dirs = []
        if self.dir.exists():
            dirs.append(self.dir)
        if self.extras_dir and self.extras_dir.exists():
            dirs.append(self.extras_dir)
        for d in dirs:
            for f in sorted(d.glob("*.json")):
                yield f

    def instalar(self, manifesto: AgentManifest) -> AgentManifest:
        problemas = validar(manifesto)
        if problemas:
            raise AgentError("manifesto inválido: " + "; ".join(problemas))
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / f"{manifesto.name}.json").write_text(
            json.dumps(manifesto.dict(), ensure_ascii=False, indent=2))
        return manifesto

    def listar(self) -> list[AgentManifest]:
        vistos, out = set(), []
        for f in self._fontes():
            try:
                mf = AgentManifest.de_dict(json.loads(f.read_text()))
            except Exception:
                continue
            if mf.name in vistos or validar(mf):
                continue                    # ignora inválido/duplicado (fail-closed)
            vistos.add(mf.name)
            out.append(mf)
        return out

    def obter(self, nome: str) -> AgentManifest | None:
        return next((m for m in self.listar() if m.name == nome), None)

    def ativo(self, nome: str) -> bool:
        from nomos.ext import skill_status as st
        return st.esta_ativa(self.home, f"agent:{nome}")

    def definir_ativo(self, nome: str, ativo: bool) -> None:
        from nomos.ext import skill_status as st
        st.ativar(self.home, f"agent:{nome}", ativo)

    def sugerir(self, texto: str) -> AgentManifest | None:
        """Agente cuja keyword casa o texto DIGITADO. No máximo um (mais casadas)."""
        t = _normalizar(texto)
        if len(t) < 8:
            return None
        melhor, melhor_n = None, 0
        for mf in self.listar():
            if not self.ativo(mf.name):
                continue
            gatilhos = {_normalizar(k) for k in mf.keywords}
            gatilhos.add(_normalizar(mf.name).replace("-", " "))
            n = sum(1 for g in gatilhos if g and g in t)
            if n > melhor_n:
                melhor, melhor_n = mf, n
        return melhor
