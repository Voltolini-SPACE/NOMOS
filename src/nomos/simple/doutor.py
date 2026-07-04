"""NOMOS simple.doutor — 'está tudo certo?' em português, para qualquer um.

Roda uma checagem rápida e devolve, em linguagem de gente, o que está pronto
e qual é o próximo passo. Não altera nada; só observa.

v0.11: além dos itens, o relatório traz STATUS GERAL (PRONTO/PARCIAL/
BLOQUEADO), cobre auditoria, cofre, skills (inclusive quebradas), motores por
modalidade e recomenda UM próximo passo acionável.
"""
from __future__ import annotations

import sys

from nomos import __version__
from nomos.cognition import motores
from nomos.kernel import config, localidade, plataforma


def _linha(ok: bool, titulo: str, detalhe: str = "") -> dict:
    return {"ok": ok, "titulo": titulo, "detalhe": detalhe}


def diagnostico(home=None) -> list[dict]:
    home = home or config.nomos_home()
    itens: list[dict] = []

    itens.append(_linha(True, f"NOMOS {__version__} instalado",
                        f"rodando em {plataforma.nome_amigavel_so()}, "
                        f"Python {plataforma.resumo()['python']}"))

    agente = config.load_agent()
    if agente and agente.get("onboarding_completo"):
        itens.append(_linha(True, f"Agente '{agente.get('agent_name')}' configurado"))
    else:
        itens.append(_linha(False, "Ainda sem agente",
                            "rode  nomos start  para dar um nome e conhecer o seu"))

    so_local = localidade.esta_ligado(home)
    itens.append(_linha(True, "Modo só-local " + ("LIGADO 🔒" if so_local else "DESLIGADO 🔌"),
                        "tudo fica na sua máquina" if so_local
                        else "você plugou motores externos; cada uso pede permissão"))

    if config.nomos_home().joinpath("vault.json").exists():
        n = len(_nomes_seguro())
        itens.append(_linha(True, "Caixa-forte de chaves criada",
                            f"{n} chave(s) guardada(s)"))
    else:
        itens.append(_linha(True, "Caixa-forte ainda não criada",
                            "opcional — crie quando precisar guardar uma chave (/chaves)"))

    mapa = motores.detectar()
    from nomos.cognition import embutido as _emb
    texto = motores.ativo("texto", mapa)
    if texto and texto.get("local"):
        itens.append(_linha(True, "Cérebro local pronto", f"{texto['detalhe']}"))
    elif any(_emb.esta_baixado(config.nomos_home(), m) for m in _emb.CATALOGO):
        itens.append(_linha(False, "Cérebro baixado, falta o motor",
                            "rode uma vez: nomos cerebro instalar"))
    else:
        rec = _emb.recomendado()
        itens.append(_linha(False, "Sem cérebro de IA ainda (leve!)",
                            f"baixe o cérebro do NOMOS (~{rec.mb} MB, roda em qualquer PC): "
                            "nomos cerebro baixar — sem isso, funciono em modo demo"))

    extras = []
    for modal in ("imagem", "audio"):
        achou = [m["id"] for m in mapa[modal] if m.get("disponivel")]
        if achou:
            extras.append(f"{modal}: {', '.join(achou)}")
    if extras:
        itens.append(_linha(True, "Motores extras disponíveis", " · ".join(extras)))

    if not plataforma.execucao_isolada_disponivel():
        itens.append(_linha(True, "Execução isolada de código: indisponível neste sistema",
                            "normal no Mac/Windows — não afeta chat, memória nem chaves"))
    return itens


def _nomes_seguro() -> list[str]:
    try:
        from nomos.simple import chaves
        return chaves.nomes_guardados()
    except Exception:
        return []


def texto_relatorio(home=None) -> str:
    itens = diagnostico(home)
    linhas = ["Check-up do NOMOS", "=" * 40]
    faltam = 0
    for it in itens:
        marca = "✓" if it["ok"] else "!"
        if not it["ok"]:
            faltam += 1
        linhas.append(f"[{marca}] {it['titulo']}")
        if it["detalhe"]:
            linhas.append(f"      {it['detalhe']}")
    linhas.append("=" * 40)
    if faltam == 0:
        linhas.append("Tudo pronto! Rode  nomos  e comece a conversar.")
    else:
        linhas.append(f"{faltam} passo(s) opcional(is) acima para deixar ainda melhor.")
        linhas.append("Nada te impede de usar agora:  nomos")
    return "\n".join(linhas)


# ------------------------- check-up v0.11 -------------------------

def _item(ok: bool, titulo: str, detalhe: str = "", proximo: str = "",
          bloqueante: bool = False) -> dict:
    return {"ok": ok, "titulo": titulo, "detalhe": detalhe,
            "proximo": proximo, "bloqueante": bloqueante}


def diagnostico_v011(home=None, ctx: dict | None = None) -> list[dict]:
    """Checagem completa v0.11. Itens com 'proximo' (passo acionável) e
    'bloqueante' (impede o uso básico). Só observa; não altera nada."""
    home = home or config.nomos_home()
    itens: list[dict] = []

    # Python e home
    py_ok = sys.version_info >= (3, 10)
    itens.append(_item(py_ok, f"Python {plataforma.resumo()['python']}",
                       "compatível" if py_ok else "o NOMOS precisa de Python 3.10+",
                       "" if py_ok else "instale Python 3.10 ou mais novo",
                       bloqueante=not py_ok))
    itens.append(_item(home.exists(), f"Pasta do NOMOS: {home}",
                       "criada" if home.exists() else "ainda não existe",
                       "" if home.exists() else "rode: nomos init"))

    # agente / onboarding
    agente = config.load_agent()
    if agente and agente.get("onboarding_completo"):
        itens.append(_item(True, f"Agente '{agente.get('agent_name')}' configurado"))
    else:
        itens.append(_item(False, "Ainda sem agente",
                           "dê um nome e conheça o seu",
                           "rode: nomos start"))

    # localidade
    so_local = localidade.esta_ligado(home)
    itens.append(_item(True, "Modo só-local " + ("LIGADO 🔒" if so_local else "DESLIGADO 🔌"),
                       "tudo fica na sua máquina" if so_local
                       else "motores externos plugados; cada uso pede permissão"))

    # cofre
    cofre = home.joinpath("vault.json").exists()
    n_chaves = len(_nomes_seguro()) if cofre else 0
    itens.append(_item(True, "Caixa-forte " + ("criada" if cofre else "ainda não criada"),
                       f"{n_chaves} chave(s) guardada(s)" if cofre
                       else "opcional — crie quando precisar guardar uma chave",
                       "" if cofre else "quando quiser: nomos chaves"))
    if not so_local and cofre and n_chaves == 0:
        itens.append(_item(False, "Nuvem plugada, mas sem chave guardada",
                           "sem chave, a nuvem não funciona",
                           "guarde a chave: nomos chaves"))

    # auditoria
    try:
        if ctx and "audit" in ctx:
            intacta, linha_ruim = ctx["audit"].verify()
        else:
            from nomos.kernel.audit import AuditLog
            intacta, linha_ruim = AuditLog(home / "logs" / "audit.jsonl").verify()
        itens.append(_item(intacta, "Auditoria " + ("íntegra" if intacta
                                                    else f"VIOLADA na linha {linha_ruim}"),
                           "cadeia de hash conferida",
                           "" if intacta else "investigue o arquivo de auditoria",
                           bloqueante=not intacta))
    except Exception:
        itens.append(_item(True, "Auditoria ainda vazia", "nada registrado até agora"))

    # cérebro e motores por modalidade
    from nomos.cognition import embutido as _emb
    from nomos.cognition import engine_catalog as _cat
    mapa = motores.detectar()
    cat = _cat.construir(home, mapa)
    texto_ok = bool(cat.prontos("texto"))
    if texto_ok:
        m = _cat.recomendar("texto", cat)
        itens.append(_item(True, "Cérebro pronto (texto)", m.rotulo if m else ""))
    elif any(_emb.esta_baixado(home, m) for m in _emb.CATALOGO):
        itens.append(_item(False, "Cérebro baixado, falta o motor",
                           "", "rode uma vez: nomos cerebro instalar"))
    else:
        rec = _emb.recomendado()
        itens.append(_item(False, "Sem cérebro de IA ainda",
                           f"leve (~{rec.mb} MB), roda em qualquer PC",
                           "nomos cerebro baixar"))
    for modal, nome_humano in (("voz_stt", "ouvir (transcrever áudio)"),
                               ("voz_tts", "falar (voz alta)"),
                               ("imagem", "gerar imagens"),
                               ("codigo", "programar")):
        prontos = cat.prontos(modal)
        if prontos:
            itens.append(_item(True, f"Motor de {nome_humano}",
                               ", ".join(m.id for m in prontos)))
        else:
            itens.append(_item(False, f"Nenhum motor de {nome_humano}",
                               "opcional", _dica_modal(modal)))

    # skills
    try:
        from nomos.ext import skill_status as _st
        st_itens = _st.status_todas(home, home / "skills")
        quebradas = [i for i in st_itens if i["estado"] == "quebrada"]
        if not st_itens:
            itens.append(_item(False, "Nenhuma skill instalada", "opcional",
                               "veja: nomos skills"))
        else:
            itens.append(_item(True, f"{len(st_itens)} skill(s) instalada(s)",
                               ", ".join(i["name"] for i in st_itens)))
        for q in quebradas:
            itens.append(_item(False, f"Skill quebrada: {q['name']}",
                               q.get("defeito") or "", q["acao"]))
    except Exception:
        itens.append(_item(True, "Skills: não foi possível checar agora",
                           "sem impacto no uso básico"))

    return itens


def _dica_modal(modal: str) -> str:
    return {"voz_stt": "instale o whisper e deixe no PATH",
            "voz_tts": "instale o piper (github.com/rhasspy/piper)",
            "imagem": "instale o Stable Diffusion WebUI (porta 7860)",
            "codigo": "rode: ollama pull qwen2.5-coder"}.get(modal, "")


def status_geral(itens: list[dict]) -> str:
    if any(i.get("bloqueante") and not i["ok"] for i in itens):
        return "BLOQUEADO"
    if any(not i["ok"] for i in itens):
        return "PARCIAL"
    return "PRONTO"


def proximo_passo(itens: list[dict]) -> str:
    """UM próximo passo: primeiro bloqueante, senão o primeiro pendente."""
    for i in itens:
        if i.get("bloqueante") and not i["ok"] and i.get("proximo"):
            return i["proximo"]
    for i in itens:
        if not i["ok"] and i.get("proximo"):
            return i["proximo"]
    return "nada pendente — rode  nomos  e aproveite"


# ------------------------- consertar (v1.0.1) -------------------------

def diagnosticar_consertos(home) -> list[dict]:
    """SOMENTE consertos seguros: nada aqui apaga dado do usuário.

    Cada item: {id, problema, acao} — arquivo corrompido é RENOMEADO para
    .corrompido (preservado) e recriado com o padrão mais seguro."""
    import json as _json
    from pathlib import Path
    home = Path(home)
    achados: list[dict] = []

    for sub in ("logs", "skills", "sandbox", "backups"):
        if not (home / sub).is_dir():
            achados.append({"id": f"pasta:{sub}",
                            "problema": f"pasta '{sub}/' ausente no NOMOS home",
                            "acao": f"criar {sub}/ (vazia, 0700)"})

    def _ilegivel(nome: str) -> bool:
        p = home / nome
        if not p.exists():
            return False
        try:
            _json.loads(p.read_text())
            return False
        except Exception:
            return True

    if _ilegivel("localidade.json"):
        achados.append({"id": "arquivo:localidade.json",
                        "problema": "localidade.json corrompido (hoje ele já "
                                    "falha-seguro como LIGADO)",
                        "acao": "preservar como .corrompido e recriar LIGADO 🔒"})
    if _ilegivel("policy.json"):
        achados.append({"id": "arquivo:policy.json",
                        "problema": "policy.json ilegível (hoje nega tudo)",
                        "acao": "preservar como .corrompido e recriar padrão "
                                "read-only/fail-closed"})
    for nome, oque in (("skills_estado.json", "estado das skills"),
                       ("rotinas.json", "rotinas")):
        if _ilegivel(nome):
            achados.append({"id": f"arquivo:{nome}",
                            "problema": f"{nome} corrompido ({oque} não carrega)",
                            "acao": "preservar como .corrompido e recriar vazio"})
    return achados


def consertar(home, confirmar, say=print, audit=None) -> tuple[int, list[str]]:
    """Aplica os consertos seguros. `confirmar()` deve devolver True (humano).

    Devolve (exit_code, lista_do_que_foi_feito). Sem confirmação => nada muda
    (fail-closed). Originais corrompidos são preservados, nunca apagados."""
    from pathlib import Path
    home = Path(home)
    achados = diagnosticar_consertos(home)
    if not achados:
        say("nada para consertar — está tudo íntegro. ✓")
        return 0, []
    say(f"Encontrei {len(achados)} conserto(s) seguro(s):")
    for a in achados:
        say(f"  · {a['problema']}\n    → {a['acao']}")
    say("Nenhum dado seu é apagado: arquivos corrompidos viram '.corrompido'.")
    try:
        ok = bool(confirmar())
    except Exception:
        ok = False
    if not ok:
        say("ok, não mexi em nada.")
        return 3, []

    feitos: list[str] = []
    from nomos.kernel.plataforma import chmod_privado
    for a in achados:
        tipo, _, alvo = a["id"].partition(":")
        if tipo == "pasta":
            (home / alvo).mkdir(parents=True, exist_ok=True)
            chmod_privado(home / alvo, 0o700)
            feitos.append(f"pasta {alvo}/ criada")
        elif tipo == "arquivo":
            p = home / alvo
            p.rename(p.with_suffix(p.suffix + ".corrompido"))
            if alvo == "localidade.json":
                localidade.definir(home, True)          # o padrão mais seguro
            elif alvo == "policy.json":
                from nomos.kernel.policy import PolicyEngine as _PE
                _PE(p)                                   # recria default fail-closed
            else:
                p.write_text('{"rotinas": []}' if alvo == "rotinas.json" else "{}")
                chmod_privado(p, 0o600)
            feitos.append(f"{alvo} recriado com padrão seguro (original preservado)")
        if audit is not None:
            audit.append("doutor.consertado", item=a["id"])
    say(f"pronto: {len(feitos)} conserto(s) aplicado(s).")
    for f in feitos:
        say(f"  ✓ {f}")
    return 0, feitos


def texto_relatorio_v011(home=None, ctx: dict | None = None) -> str:
    itens = diagnostico_v011(home, ctx)
    geral = status_geral(itens)
    icone = {"PRONTO": "✅", "PARCIAL": "⚠️", "BLOQUEADO": "❌"}[geral]
    linhas = ["Check-up do NOMOS",
              f"STATUS GERAL: {geral} {icone}", "=" * 44]
    for it in itens:
        marca = "✅" if it["ok"] else ("❌" if it.get("bloqueante") else "⚠️")
        linhas.append(f"{marca} {it['titulo']}")
        if it["detalhe"]:
            linhas.append(f"    {it['detalhe']}")
    linhas.append("=" * 44)
    linhas.append(f"Próximo passo recomendado: {proximo_passo(itens)}")
    return "\n".join(linhas)
