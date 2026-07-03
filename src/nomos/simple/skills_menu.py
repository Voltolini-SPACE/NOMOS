"""NOMOS simple.skills_menu — skills para gente, não para terminal.

Menu guiado (ask/say injetáveis, padrão da casa) + renderizações amigáveis.
Nenhuma decisão de segurança acontece aqui: instalar/executar continuam
passando pelo gate da política. Este módulo apresenta e coleta intenção.
"""
from __future__ import annotations

from pathlib import Path

from nomos.ext import skill_registry as reg
from nomos.ext import skill_status as st
from nomos.ext import skills as _skills
from nomos.ext.signing import TrustStore

_RISCO_ICONE = {"baixo": "🟢 baixo", "medio": "🟡 médio", "alto": "🔴 alto"}

MENU = """NOMOS Skills
1. Ver minhas skills
2. Instalar skill
3. Desativar skill
4. Ver permissões
5. Diagnóstico de segurança
6. Voltar"""


def _fmt_uso(ts) -> str:
    if not ts:
        return "nunca usada"
    import time
    dias = max(0, int((time.time() - ts) // 86400))
    return "usada hoje" if dias == 0 else f"último uso há {dias} dia(s)"


def _fmt_perms(perms: list) -> str:
    alem_de_a0 = [p for p in perms if p != "A0_READ_LOCAL"]
    if not alem_de_a0:
        return "apenas leitura local"
    return ", ".join(perms)


def linha_amigavel(item: dict) -> str:
    marca = {"ativa": "✓", "inativa": "·", "quebrada": "✗"}.get(
        item["estado"].split(" ")[0], "!")
    risco = _RISCO_ICONE.get(item["risco"], item["risco"])
    aprov = "pede sua aprovação" if item["requer_aprovacao"] else "roda sem pedir"
    return (f"[{marca}] {item['name']}@{item['version']} — {item['estado']}\n"
            f"      risco: {risco} · {aprov} · publicador: {item['publisher']}\n"
            f"      permissões: {_fmt_perms(item['permissions'])}\n"
            f"      {_fmt_uso(item['ultimo_uso'])} · {item['acao']}")


def render_lista(itens: list[dict], disponiveis: list[dict] | None = None) -> str:
    linhas = ["Suas skills", "=" * 40]
    if not itens:
        linhas.append("nenhuma skill instalada ainda.")
        linhas.append("instale com:  nomos skills instalar <caminho>")
    for it in itens:
        linhas.append(linha_amigavel(it))
    if disponiveis:
        linhas.append("-" * 40)
        linhas.append("Disponíveis no catálogo local (ainda não instaladas):")
        for d in disponiveis:
            linhas.append(f"  · {d['name']}@{d.get('version', '?')} — "
                          f"{d.get('description') or 'sem descrição'} "
                          f"(risco {d.get('risk_level', '?')})")
    return "\n".join(linhas)


def render_info(item: dict) -> str:
    linhas = [f"Skill: {item['name']}@{item['version']}",
              f"estado: {item['estado']}",
              f"risco: {_RISCO_ICONE.get(item['risco'], item['risco'])}",
              f"exige aprovação humana: {'sim' if item['requer_aprovacao'] else 'não'}",
              f"publicador: {item['publisher']} "
              f"({'confiável ✓' if item['confiavel'] else 'não verificado'})",
              f"permissões: {_fmt_perms(item['permissions'])}",
              f"modalidades: {', '.join(item['modalities']) or '—'}",
              f"uso: {_fmt_uso(item['ultimo_uso'])}"]
    if item.get("defeito"):
        linhas.append(f"defeito: {item['defeito']}")
    linhas.append(f"ação recomendada: {item['acao']}")
    return "\n".join(linhas)


def diagnostico_texto(home: Path, skills_dir: Path,
                      trust: TrustStore | None = None) -> str:
    itens = st.status_todas(home, skills_dir, trust)
    linhas = ["Diagnóstico de segurança das skills", "=" * 40]
    if not itens:
        linhas.append("nenhuma skill instalada — nada a diagnosticar.")
        return "\n".join(linhas)
    quebradas = [i for i in itens if i["estado"] == "quebrada"]
    nao_conf = [i for i in itens if not i["confiavel"] and i["estado"] != "quebrada"]
    alto = [i for i in itens if i["risco"] == "alto"]
    linhas.append(f"instaladas: {len(itens)} · quebradas: {len(quebradas)} · "
                  f"não assinadas: {len(nao_conf)} · risco alto: {len(alto)}")
    for i in quebradas:
        linhas.append(f"✗ {i['name']}: {i['defeito']} → {i['acao']}")
    for i in alto:
        linhas.append(f"🔴 {i['name']}: risco alto — só roda com sua aprovação explícita")
    for i in nao_conf:
        linhas.append(f"! {i['name']}: publicador não verificado (sem assinatura confiável)")
    if not (quebradas or nao_conf or alto):
        linhas.append("✓ tudo assinado, íntegro e de baixo risco.")
    return "\n".join(linhas)


def menu(ctx, ask=input, say=print, instalar_fn=None) -> int:
    """Menu interativo. `instalar_fn(caminho)` é injetado pela CLI (usa o gate real)."""
    home = ctx["home"]
    skills_dir = ctx["skills"]
    trust = TrustStore(Path(home) / "trust.json")
    while True:
        say("")
        say(MENU)
        op = ask("escolha> ").strip()
        if op in {"6", "", "voltar", "sair"}:
            return 0
        if op == "1":
            say(render_lista(st.status_todas(home, skills_dir, trust),
                             reg.disponiveis(home, skills_dir)))
        elif op == "2":
            caminho = ask("caminho da pasta da skill> ").strip()
            if not caminho:
                say("ok, nada instalado.")
                continue
            if instalar_fn is None:
                say("instalação indisponível neste modo.")
                continue
            say(instalar_fn(caminho))
        elif op == "3":
            nome = ask("qual skill desativar?> ").strip()
            if nome:
                st.ativar(home, nome, False)
                say(f"'{nome}' desativada. Reative com: nomos skills ativar {nome}")
        elif op == "4":
            for it in st.status_todas(home, skills_dir, trust):
                say(f"  {it['name']}: {', '.join(it['permissions']) or 'apenas leitura local'}")
        elif op == "5":
            say(diagnostico_texto(home, skills_dir, trust))
        else:
            say("opção desconhecida — digite um número de 1 a 6.")


def instalar_amigavel(ctx, caminho: str, approver, confirmar_experimental) -> str:
    """Fluxo de instalação usado pela CLI (mensagem amigável, gate real)."""
    trust = TrustStore(Path(ctx["home"]) / "trust.json")
    try:
        mf = reg.instalar(Path(caminho), ctx["skills"], ctx["policy"], approver,
                          trust=trust, confirmar_experimental=confirmar_experimental)
    except (reg.RegistroError, _skills.SkillError) as exc:
        ctx["audit"].append("skill.install.falhou", motivo=str(exc))
        return f"não instalei: {exc}"
    ctx["audit"].append("skill.instalada", name=mf["name"], version=mf["version"],
                        permissions=mf["permissions"], risco=mf["risk_level"])
    return (f"skill {mf['name']}@{mf['version']} instalada "
            f"(risco {mf['risk_level']}; "
            f"{'pede aprovação a cada uso sensível' if mf['requires_approval'] else 'baixo risco'}).")
