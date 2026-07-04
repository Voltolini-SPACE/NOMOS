"""NOMOS ext.skill_intencao — a skill certa se OFERECE; quem decide é você.

Heurística LOCAL e determinística (nenhuma IA decide nada aqui):
- cada skill pode declarar `keywords` no manifesto (v1.2);
- o texto do usuário é normalizado (minúsculas, sem acentos) e as keywords
  declaradas são procuradas como substrings;
- só skills ATIVAS e ÍNTEGRAS concorrem; vence a que casar mais keywords
  (empate: ordem alfabética, estável);
- devolve no máximo UMA sugestão — o chat pergunta, o gate governa, o "não"
  do usuário encerra o assunto.
"""
from __future__ import annotations

import json
import unicodedata
from pathlib import Path


def _normalizar(texto: str) -> str:
    t = unicodedata.normalize("NFKD", (texto or "").lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def sugerir_skill(texto: str, home: Path, skills_dir: Path) -> dict | None:
    """{name, keywords_casadas, description} da melhor skill, ou None."""
    t = _normalizar(texto)
    if len(t) < 8:                       # frases curtíssimas não são intenção
        return None
    from nomos.ext import skill_registry as reg
    from nomos.ext import skill_status as st
    skills_dir = Path(skills_dir)
    if not skills_dir.exists():
        return None
    melhor: dict | None = None
    for pasta in sorted(skills_dir.iterdir()):
        mf_path = pasta / "skill.json"
        if not (pasta.is_dir() and mf_path.exists()):
            continue
        try:
            mf = reg.normalizar_manifesto(json.loads(mf_path.read_text()))
        except Exception:
            continue                     # manifesto ilegível: fora
        if not st.esta_ativa(home, mf["name"]):
            continue                     # desativada: nunca oferecida
        estado = st.status_skill(home, pasta)
        if estado["estado"] == "quebrada":
            continue                     # quebrada: nunca oferecida
        gatilhos = [_normalizar(k) for k in mf.get("keywords", []) if k]
        gatilhos.append(_normalizar(mf["name"]).replace("-", " "))
        casadas = [g for g in set(gatilhos) if g and g in t]
        if not casadas:
            continue
        candidato = {"name": mf["name"], "keywords_casadas": sorted(casadas),
                     "description": mf.get("description", "")}
        if melhor is None or (len(candidato["keywords_casadas"]),
                              ) > (len(melhor["keywords_casadas"]),):
            melhor = candidato
    return melhor


def render_resultado_skill(nome: str, resultado: dict | None, bruto: str) -> str:
    """Resposta legível a partir do JSON da skill — sem inventar nada."""
    if resultado is None:
        return (f"a skill '{nome}' respondeu, mas não em JSON — saída bruta:\n"
                + bruto.strip()[:800])
    if resultado.get("ok") is False:
        return (f"a skill '{nome}' não conseguiu: "
                f"{resultado.get('erro', 'sem detalhe')}")
    linhas = [f"resultado da skill '{nome}':"]
    for chave, valor in resultado.items():
        if chave == "ok":
            continue
        if isinstance(valor, list):
            linhas.append(f"  {chave}:")
            for item in valor[:10]:
                linhas.append(f"    · {json.dumps(item, ensure_ascii=False) if isinstance(item, (dict, list)) else item}")
            if len(valor) > 10:
                linhas.append(f"    … e mais {len(valor) - 10}")
        else:
            linhas.append(f"  {chave}: {valor}")
    return "\n".join(linhas)
