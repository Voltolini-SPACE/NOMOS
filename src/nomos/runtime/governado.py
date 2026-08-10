"""NOMOS runtime.governado — o runtime de orquestração governada (ABSORPTION-01).

Este módulo é o CALLER REAL do pacote `orquestracao`. Antes dele, o pacote
existia testado e sem ninguém em produção o chamando: capacidade validada,
não operacional. Aqui ele vira caminho de execução de verdade.

A cadeia é sempre a mesma e não tem atalho:

    intenção
      → planejador (categoria SEMPRE do registro)
      → grafo (validação estrutural fail-closed)
      → orquestrador (policy.decide + policy.gate A0–A6 em CADA nó)
      → adapter nativo (as 8 ferramentas já wired em agents/execucao)
      → evidência/auditoria

Invariantes que este módulo NÃO pode quebrar (e que os testes cobrem):

- não existe executor genérico: o dicionário de executores é montado a partir
  de `agents.execucao.ferramentas_wired`, a MESMA allowlist de 8 ferramentas
  usada por `nomos agentes usar`. Nenhum shell, subprocess, git ou HTTP novo;
- capacidade fora do registro ⇒ o grafo nem constrói;
- risco/idempotência vêm do registro, nunca do plano;
- negação bloqueia dependentes transitivos — recuperação não reexecuta nó
  NEGADO (ela só é consultada para nó que chegou a executar e falhou);
- o registro dinâmico é opcional e continua governado por A5_SKILL_INSTALL.

O motor de inferência é OPCIONAL: sem motor, `planejar` exige passos
explícitos e o runtime segue operando (é orquestração governada, não LLM).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from nomos.orquestracao.grafo import ErroGrafo, Orquestrador, ResultadoMissao
from nomos.orquestracao.planejador import PlanoTipado, planejar
from nomos.orquestracao.recuperacao import GerenciadorRecuperacao, PoliticaRecuperacao
from nomos.orquestracao.registro import RegistroCapacidades

if TYPE_CHECKING:                      # só para anotação; import real é tardio
    from nomos.agents.manifest import AgentManifest


class ErroRuntime(RuntimeError):
    """Falha de runtime governado — sempre fail-closed."""


@dataclass(frozen=True)
class ResultadoExecucao:
    """O que o chamador recebe. `plano` vem junto para a evidência ser legível."""
    ok: bool
    plano: PlanoTipado
    missao: ResultadoMissao | None
    motivo: str = ""

    def resumo(self) -> dict:
        """Resumo auditável — nunca inclui conteúdo de params (só metadados)."""
        nos = {}
        if self.missao is not None:
            nos = {i: {"status": r.status, "tentativas": r.tentativas,
                       "detalhe": r.detalhe[:200]}
                   for i, r in self.missao.nos.items()}
        return {
            "ok": self.ok,
            "objetivo": self.plano.objetivo,
            "risco": self.plano.risco,
            "exige_aprovacao": self.plano.exige_aprovacao,
            "passos": len(self.plano.passos),
            "rejeitados": [dict(r) for r in self.plano.rejeitados],
            "nos": nos,
            "motivo": self.motivo,
        }


def manifesto_do_runtime(ferramentas=None) -> "AgentManifest":
    """Identidade do runtime como agente — para o boundary ter o que checar.

    O runtime não é um "super-usuário sem manifesto": ele opera sob um
    manifesto explícito, exatamente como qualquer agente. Por padrão declara
    a allowlist inteira, mas o chamador pode entregar um manifesto MENOR
    (atenuação) — nunca maior: `validar()` recusa ferramenta fora da
    allowlist e risco_max menor que o exigido.
    """
    from nomos.agents.manifest import FERRAMENTAS, AgentManifest, risco_exigido, validar
    ferramentas = tuple(ferramentas if ferramentas is not None else FERRAMENTAS)
    mf = AgentManifest(
        name="runtime-governado",
        objetivo="orquestração governada de tarefas (ABSORPTION-01)",
        ferramentas=ferramentas,
        risco_max=risco_exigido(ferramentas),
        pode_executar_skill="skill_rodar" in ferramentas,
        exige_aprovacao=True)
    problemas = validar(mf)
    if problemas:
        raise ErroRuntime(f"manifesto do runtime inválido: {'; '.join(problemas)}")
    return mf


def executores_nativos(ctx, aprovador=None, router=None,
                       sem_motor: bool = False, manifesto=None) -> dict[str, Callable]:
    """Adapta as 8 ferramentas nativas ao contrato do Orquestrador.

    `ferramentas_wired` devolve closures de ZERO argumentos ligadas a um
    `alvo`/`conteudo` fixos, porque foi feita para o caminho de uma ferramenta
    só (`nomos agentes usar`). O orquestrador chama `executor(**params)` com os
    params DAQUELE nó. A ponte é reconstruir o wiring por chamada.

    O ponto crítico: este adapter NÃO chama o executor diretamente. Ele passa
    pelo MESMO `AgentToolBoundary` que governa `nomos agentes usar` — fora do
    manifesto ⇒ negado; dentro ⇒ `policy.gate` de novo. Com isso o boundary é
    o PEP nativo e o runtime não vira um caminho paralelo de autorização
    (invariante protegido por `test_h4_5_c_agent_tool_boundary_gate`).

    Params desconhecidos são descartados: um nó não amplia a superfície de uma
    ferramenta inventando argumento.
    """
    from nomos.agents.boundary import AgentToolBoundary
    from nomos.agents.execucao import ferramentas_wired
    from nomos.agents.manifest import FERRAMENTAS

    mf = manifesto if manifesto is not None else manifesto_do_runtime()

    def _fazer(nome: str) -> Callable:
        def _executar(**params):
            alvo = params.get("alvo", "") or ""
            conteudo = params.get("conteudo", "") or ""
            if not isinstance(alvo, str) or not isinstance(conteudo, str):
                raise ErroRuntime(
                    f"'{nome}': 'alvo' e 'conteudo' precisam ser texto")
            wired = ferramentas_wired(
                ctx, alvo=alvo, conteudo=conteudo, sem_motor=sem_motor,
                aprovador=aprovador, router=router)
            fn = wired.get(nome)
            if fn is None:
                # allowlist futura que cresça sem wiring ⇒ falha fechada
                raise ErroRuntime(f"'{nome}' não tem execução ligada nesta versão")
            boundary = AgentToolBoundary(mf, ctx["policy"], aprovador,
                                         audit=ctx.get("audit"))
            ok, resultado = boundary.usar_ferramenta(nome, fn, alvo=alvo)
            if not ok:
                # negação do PEP é falha do nó, nunca "passa mesmo assim"
                raise ErroRuntime(str(resultado))
            return resultado
        _executar.__name__ = f"nativo_{nome}"
        return _executar

    return {nome: _fazer(nome) for nome in FERRAMENTAS if nome in mf.ferramentas}


class RuntimeGovernado:
    """Runtime de orquestração do NOMOS. Um por missão (o orçamento é da missão).

    Construção barata e sem efeito: nada executa até `executar()`.
    """

    def __init__(self, ctx, aprovador=None, *, router=None,
                 sem_motor: bool = False, manifesto=None,
                 politica_recuperacao: PoliticaRecuperacao | None = None,
                 executores: dict[str, Callable] | None = None):
        if ctx is None or "policy" not in ctx:
            raise ErroRuntime("contexto sem política carregada — fail-closed")
        self.ctx = ctx
        self.policy = ctx["policy"]
        self.audit = ctx.get("audit")
        self.aprovador = aprovador
        self.manifesto = manifesto if manifesto is not None else manifesto_do_runtime()
        self.registro = RegistroCapacidades(policy=self.policy,
                                            approver=aprovador,
                                            audit=self.audit)
        self.executores = (executores if executores is not None
                           else executores_nativos(ctx, aprovador=aprovador,
                                                   router=router,
                                                   sem_motor=sem_motor,
                                                   manifesto=self.manifesto))
        self.recuperacao = GerenciadorRecuperacao(
            politica=politica_recuperacao, audit=self.audit)
        self.rotear_motor = None
        self._router = router

    # ---------------- planejamento ----------------

    def planejar(self, objetivo: str, passos: list | None = None,
                 llm: Callable | None = None) -> PlanoTipado:
        """Objetivo + passos ⇒ plano tipado. Categoria SEMPRE do registro."""
        return planejar(objetivo, self.registro, passos=passos, llm=llm,
                        audit=self.audit)

    def habilitar_roteamento_de_motor(self, chave_configurada: bool | None = None) -> bool:
        """Liga NH-007 (rota de motor por nó, com `motor="auto"`).

        Import tardio de propósito: `roteamento` puxa `cognition.engine_router`
        (catálogo/política/localidade), bem mais pesado que o resto — e o
        runtime governado precisa funcionar sem motor nenhum. Ausência ou
        falha de roteamento NÃO é erro: devolve False e a execução segue
        governada, apenas sem seleção de LLM.
        """
        try:
            from nomos.orquestracao.roteamento import roteador_de_no
            self.rotear_motor = roteador_de_no(
                home=self.ctx.get("home"), chave_configurada=chave_configurada)
        except Exception:
            self.rotear_motor = None
        return self.rotear_motor is not None

    # ---------------- execução ----------------

    def executar(self, plano: PlanoTipado) -> ResultadoExecucao:
        """Plano ⇒ grafo ⇒ execução governada. Nunca levanta por causa do
        conteúdo do plano: plano inválido vira resultado fail-closed."""
        if not isinstance(plano, PlanoTipado):
            raise ErroRuntime("plano inválido (tipo inesperado)")
        if not plano.ok:
            self._auditar("runtime.execucao.recusada",
                          motivo=plano.motivo or "plano não aprovado")
            return ResultadoExecucao(ok=False, plano=plano, missao=None,
                                     motivo=plano.motivo or "plano não aprovado")
        try:
            grafo = plano.para_grafo(self.registro)
        except ErroGrafo as exc:
            self._auditar("runtime.grafo.invalido", motivo=str(exc))
            return ResultadoExecucao(ok=False, plano=plano, missao=None,
                                     motivo=f"grafo inválido: {exc}")
        orq = Orquestrador(self.registro, self.policy, approver=self.aprovador,
                           audit=self.audit, executores=self.executores,
                           recuperacao=self.recuperacao,
                           rotear_motor=self.rotear_motor)
        self._auditar("runtime.execucao.inicio", objetivo=plano.objetivo[:120],
                      passos=len(plano.passos), risco=plano.risco)
        missao = orq.executar(grafo)
        self._auditar("runtime.execucao.fim", ok=missao.ok)
        return ResultadoExecucao(ok=missao.ok, plano=plano, missao=missao,
                                 motivo="" if missao.ok else "um ou mais nós não concluíram")

    def rodar(self, objetivo: str, passos: list | None = None,
              llm: Callable | None = None) -> ResultadoExecucao:
        """Atalho intenção→resultado. Continua passando por TODA a cadeia."""
        return self.executar(self.planejar(objetivo, passos=passos, llm=llm))

    def _auditar(self, evento: str, **campos) -> None:
        """Mesma convenção do Orquestrador: falha de auditoria PROPAGA.

        Engolir seria pior do que falhar — sobraria execução real sem trilha,
        exatamente o que `registro.registrar` já recusa a permitir.
        """
        if self.audit is not None:
            self.audit.append(evento, **campos)
