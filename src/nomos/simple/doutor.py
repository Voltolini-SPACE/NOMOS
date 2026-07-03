"""NOMOS simple.doutor — 'está tudo certo?' em português, para qualquer um.

Roda uma checagem rápida e devolve, em linguagem de gente, o que está pronto
e qual é o próximo passo. Não altera nada; só observa.
"""
from __future__ import annotations

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
