"""NOMOS cognition.engine_router — roteador automático de motores, local-first.

Dado uma tarefa (tipo, modalidade, sensibilidade, tamanho), escolhe o melhor
motor respeitando, nesta ordem: privacidade > disponibilidade > qualidade >
custo. Regras invioláveis:

1. local_only=True  => nunca escolhe nuvem (nem como fallback);
2. texto simples    => motor leve local serve;
3. raciocínio complexo => tenta local forte; sem ele, explica (não inventa);
4. nuvem            => exige local off + chave + aprovação (gate na hora do uso);
5. skill sensível   => passa pelo policy gate (fora deste módulo, no executor);
6. nenhum motor serve => decisão vazia com diagnóstico acionável;
7. tarefa decomponível => steps de pipeline (contexto grande => resumir antes).

A saída é um EngineRouteDecision — dados, não ação: quem executa continua
passando pelo gate. O roteador não tem poder de autorizar nada.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

from nomos.cognition import engine_catalog as cat_mod
from nomos.cognition import engine_policy as pol
from nomos.kernel import config, localidade

# limiar (chars) a partir do qual vale resumir o contexto antes de responder
CONTEXTO_GRANDE = 8000


@dataclass(frozen=True)
class Tarefa:
    tipo: str = "conversa"           # conversa | codigo | resumo | raciocinio | transcricao | leitura_arquivo
    modalidade: str = "texto"        # uma de engine_catalog.MODALIDADES_V011
    dados_sensiveis: bool = False
    tamanho_contexto: int = 0        # aproximação em caracteres
    precisa_ferramenta: bool = False
    precisa_memoria: bool = False


@dataclass(frozen=True)
class EngineRouteDecision:
    selected_engine: str | None
    fallback_engine: str | None
    reason: str
    privacy_level: str
    approval_required: bool
    estimated_cost: str
    local_only_preserved: bool
    confidence: float
    steps: tuple = ()

    def dict(self) -> dict:
        return asdict(self)


_PALAVRAS_CODIGO = ("código", "codigo", "programa", "função", "funcao", "script",
                    "bug", "python", "javascript", "classe", "compilar")
_PALAVRAS_RESUMO = ("resuma", "resumo", "resumir", "sintetiza", "sintetize", "tl;dr")
_PALAVRAS_RACIOCINIO = ("planeje", "plano detalhado", "passo a passo", "analise",
                        "análise", "compare", "estratégia", "estrategia", "prove")
_PALAVRAS_SENSIVEIS = ("senha", "chave", "cpf", "cartão", "cartao", "banco",
                       "salário", "salario", "médico", "medico", "diagnóstico",
                       "diagnostico", "api_key", "token", "segredo")


def classificar(texto: str, tamanho_contexto: int | None = None) -> Tarefa:
    """Heurística local e transparente — nada de IA para decidir a rota."""
    t = (texto or "").lower()
    sensivel = any(p in t for p in _PALAVRAS_SENSIVEIS)
    tam = tamanho_contexto if tamanho_contexto is not None else len(texto or "")
    if any(p in t for p in _PALAVRAS_CODIGO):
        return Tarefa("codigo", "codigo", sensivel, tam)
    if any(p in t for p in _PALAVRAS_RESUMO):
        return Tarefa("resumo", "resumo", sensivel, tam)
    if any(p in t for p in _PALAVRAS_RACIOCINIO) or tam > CONTEXTO_GRANDE:
        return Tarefa("raciocinio", "raciocinio", sensivel, tam)
    return Tarefa("conversa", "texto", sensivel, tam)


def _custo(motor) -> str:
    return motor.custo if motor else "zero"


def rotear(tarefa: Tarefa, home=None, catalogo: cat_mod.Catalogo | None = None,
           chave_configurada: bool | None = None) -> EngineRouteDecision:
    home = home or config.nomos_home()
    so_local = localidade.esta_ligado(home)
    catalogo = catalogo or cat_mod.construir(home)

    candidatos = catalogo.por_modalidade(tarefa.modalidade)
    if not candidatos:
        return EngineRouteDecision(
            None, None,
            f"nenhum motor conhece a modalidade '{tarefa.modalidade}'",
            "total (não sai da máquina)", False, "zero", so_local, 1.0)

    elegiveis: list[tuple] = []
    motivos: list[str] = []
    for m in candidatos:
        e = pol.elegivel(m, home, tarefa.dados_sensiveis, chave_configurada)
        if e.ok:
            elegiveis.append((m, e))
        else:
            motivos.append(f"{m.id}: {e.motivo}")

    # locais primeiro, depois SEU feedback local (v0.18), depois qualidade
    # (regra: privacidade > sua experiência > qualidade > custo)
    from nomos.cognition import feedback as fb
    ordem_q = {"alta": 0, "boa": 1, "básica": 2}

    def _voto(m):
        t = fb.taxa(home, m.id)
        if t is None:
            return 1          # sem sinal: neutro
        return 0 if t >= 0.5 else 2   # bem avaliado sobe; mal avaliado desce

    elegiveis.sort(key=lambda pair: (not pair[0].local,
                                     _voto(pair[0]),
                                     ordem_q.get(pair[0].qualidade, 3)))

    if not elegiveis:
        # Regra 6: não inventa — diagnóstico acionável
        dica = _proximo_passo(tarefa, so_local)
        return EngineRouteDecision(
            None, None,
            "nenhum motor disponível para esta tarefa — "
            + "; ".join(motivos[:3]) + f". Próximo passo: {dica}",
            "total (não sai da máquina)", False, "zero", so_local, 1.0)

    # Regra 2: texto simples prefere motor leve local pronto
    if tarefa.tipo == "conversa" and tarefa.tamanho_contexto <= CONTEXTO_GRANDE:
        leves = [p for p in elegiveis if p[0].local and p[0].tipo == "embutido"]
        if leves and not any(p[0].local and p[0].qualidade == "alta" for p in elegiveis):
            elegiveis = leves + [p for p in elegiveis if p not in leves]

    escolhido, eleg = elegiveis[0]
    fallback = elegiveis[1][0] if len(elegiveis) > 1 else None

    # Regra 1 (reforço): com cadeado ligado, nuvem jamais aparece — nem fallback
    if so_local:
        assert escolhido.local, "invariante violada: nuvem escolhida com só-local ligado"
        if fallback is not None and not fallback.local:
            fallback = None

    # Regra 3: raciocínio complexo sem local forte => explica em vez de fingir
    if (tarefa.tipo == "raciocinio" and escolhido.local
            and escolhido.qualidade == "básica"):
        aviso = (" · aviso: só encontrei um motor local leve; para raciocínio "
                 "pesado, instale um modelo forte (ollama pull hermes3) — vou "
                 "tentar, mas sem inventar certeza")
    else:
        aviso = ""

    # Regra 7: pipeline quando dá para quebrar a tarefa
    steps: tuple = ()
    if tarefa.tamanho_contexto > CONTEXTO_GRANDE:
        steps = (f"resumir contexto com {escolhido.id}",
                 f"responder com {escolhido.id}")
    if tarefa.precisa_memoria:
        steps = steps + ("guardar resultado na memória local",)
    if tarefa.precisa_ferramenta:
        steps = ("verificar permissões da skill no gate",) + steps

    taxa_votos = fb.taxa(home, escolhido.id)
    confianca = 0.9 if escolhido.local and escolhido.pronto else 0.6
    nota_fb = ""
    if taxa_votos is not None:
        confianca = round(min(0.99, max(0.3, confianca * (0.6 + 0.4 * taxa_votos))), 2)
        nota_fb = f" · seu feedback local: {int(taxa_votos * 100)}% positivo"

    return EngineRouteDecision(
        selected_engine=escolhido.id,
        fallback_engine=fallback.id if fallback else None,
        reason=(f"{'local-first' if escolhido.local else 'nuvem (opt-in)'}: "
                f"{eleg.motivo}{aviso}{nota_fb}"),
        privacy_level=pol.nivel_privacidade(escolhido),
        approval_required=eleg.exige_aprovacao or escolhido.requer_aprovacao,
        estimated_cost=_custo(escolhido),
        local_only_preserved=escolhido.local,
        confidence=confianca,
        steps=steps)


def _proximo_passo(tarefa: Tarefa, so_local: bool) -> str:
    if tarefa.modalidade in {"texto", "resumo", "raciocinio", "codigo"}:
        return "nomos cerebro baixar (motor local leve, uma vez)"
    if tarefa.modalidade == "voz_stt":
        return "instale o whisper e deixe no PATH"
    if tarefa.modalidade == "voz_tts":
        return "instale o piper (github.com/rhasspy/piper)"
    if tarefa.modalidade in {"imagem", "visao"}:
        return "instale o Stable Diffusion WebUI (porta 7860) ou um modelo de visão"
    return "rode: nomos motores diagnostico"


def explicar(decisao: EngineRouteDecision) -> str:
    """Explicação em uma linha, para gente."""
    if not decisao.selected_engine:
        return f"não encontrei motor pronto: {decisao.reason}"
    onde = ("tudo na sua máquina — nada saiu dela"
            if decisao.local_only_preserved else
            "usei a nuvem com sua permissão explícita")
    extra = f" (plano: {' → '.join(decisao.steps)})" if decisao.steps else ""
    return (f"Escolhi '{decisao.selected_engine}' — {onde}."
            f"{extra}")
