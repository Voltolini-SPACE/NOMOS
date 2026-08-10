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

import secrets
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from nomos.orquestracao.grafo import ErroGrafo, Orquestrador, ResultadoMissao
from nomos.orquestracao.planejador import PlanoTipado, planejar
from nomos.orquestracao.recuperacao import GerenciadorRecuperacao, PoliticaRecuperacao
from nomos.orquestracao.registro import RegistroCapacidades

if TYPE_CHECKING:                      # só para anotação; import real é tardio
    from nomos.agents.manifest import AgentManifest
    from nomos.pdp.pep import PontoDeAplicacao

# Audiência deste PEP. Uma autorização emitida para outro destino não vale
# aqui — é o que impede token de um plano virar autoridade noutro.
AUDIENCIA_RUNTIME = "nomos:runtime-governado"


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
                # negação do boundary é falha do nó, nunca "passa mesmo assim"
                raise ErroRuntime(str(resultado))
            return resultado
        _executar.__name__ = f"nativo_{nome}"
        return _executar

    return {nome: _fazer(nome) for nome in FERRAMENTAS if nome in mf.ferramentas}


def _versoes_de(registro, capacidades) -> tuple[tuple[str, str], ...]:
    """Impressão digital de cada descritor no instante da emissão (FASE 4).

    É isto que permite ao PDP recusar autorização cujo mundo mudou: se o risco,
    a idempotência ou o executor de uma capacidade forem alterados depois da
    emissão, a versão deixa de bater.
    """
    from nomos.adapters.contrato import versao_de_capacidade
    pares = []
    for cap in capacidades:
        try:
            v = versao_de_capacidade(registro, cap)
        except Exception:
            v = ""
        if v:
            pares.append((cap, v))
    return tuple(sorted(pares))


def sessao_pdp(registro, manifesto, audit=None, ttl_s: int = 3600,
               caminhos: tuple[str, ...] = (), extras: tuple[str, ...] = ()):
    """(decisor, autorização) de SESSÃO para um manifesto. **Fonte única.**

    Usada tanto pelo `RuntimeGovernado` quanto pelo caminho de ferramenta
    única (`usar_ferramenta_governada`). Existe uma só para que não apareça
    um `legacy_pdp`/`simple_policy` paralelo: quem quiser governar execução
    passa por aqui.

    A autorização é escopada pelo MANIFESTO — capacidades = as declaradas,
    teto de risco = `risco_max` do manifesto. Um agente que só declara
    `arquivo_ler` recebe autorização para exatamente isso.

    `caminhos` liga o ESCOPO POR CAMINHO do PDP. Achado do censo da
    ABSORPTION-02: o `Decisor` sempre soube validar `pedido.recurso` (e o
    contrabando por `argumentos.alvo/caminho/destino`) contra
    `autorizacao.caminhos`, mas a emissão nunca preenchia o campo — com tupla
    vazia o bloco inteiro é pulado, e o escopo ficava inalcançável na prática.
    Agora é parâmetro explícito.

    O default segue `()` = SEM restrição de caminho, e isso é decisão
    consciente, não esquecimento: `arquivo_ler`/`arquivo_resumir` leem alvo
    arbitrário por desenho (`exec_arquivo_ler` não passa por
    `_resolver_destino_seguro`, que confina só a ESCRITA no workspace).
    Ligar um escopo restritivo por padrão mudaria comportamento de leitura sem
    o dono pedir. Quem quiser confinar passa `caminhos` — e aí é enforçado de
    ponta a ponta (ver `test_escopo_por_caminho_e_enforcado_no_runtime`).
    """
    from datetime import timedelta

    from nomos.pdp.autorizacao import ArmazemNonce, Autorizacao, Chaveiro, agora_utc
    from nomos.pdp.decisor import Decisor

    chaveiro = Chaveiro({"sessao": secrets.token_bytes(32)})
    decisor = Decisor(chaveiro, registro, audiencia=AUDIENCIA_RUNTIME,
                      armazem_nonce=ArmazemNonce(), audit=audit)
    agora = agora_utc()
    autorizacao = chaveiro.assinar(Autorizacao(
        capacidades=tuple(manifesto.ferramentas) + tuple(extras),
        sujeito=manifesto.name,
        audiencia=AUDIENCIA_RUNTIME,
        emitida_em=agora,
        expira_em=agora + timedelta(seconds=ttl_s),
        risco_max=manifesto.risco_max,
        caminhos=tuple(caminhos),
        versoes=_versoes_de(registro,
                            tuple(manifesto.ferramentas) + tuple(extras)),
        jti=secrets.token_hex(8)), "sessao")
    return decisor, autorizacao


def usar_ferramenta_governada(ctx, manifesto, ferramenta: str, *, alvo: str = "",
                              conteudo: str = "", aprovador=None, router=None,
                              sem_motor: bool = False,
                              decisor=None, autorizacao=None,
                              caminhos: tuple[str, ...] = ()) -> tuple[bool, object]:
    """UMA ferramenta pela cadeia governada completa (ABSORPTION-02 / FASE 1).

        caller → registry → PDP → PEP → AgentToolBoundary → adapter → efeito

    Este é o caminho que `nomos agentes usar` e a conversa amigável passaram a
    usar. Antes eles chamavam o boundary direto: gate A0–A6 sim, mas sem token
    assinado, escopo, TTL, nonce ou anti-replay. Nenhuma política nova foi
    criada aqui — é a MESMA `sessao_pdp` do runtime.

    Devolve `(ok, resultado|motivo)`, no mesmo contrato que o boundary já
    entregava, para os chamadores não precisarem mudar de forma.
    """
    from nomos.agents.boundary import AgentToolBoundary
    from nomos.pdp.decisor import Pedido
    from nomos.pdp.pep import NegadoPeloPEP

    # 1. identidade/contexto ANTES do PDP: a ferramenta pertence a este agente?
    #    Quem responde continua sendo o boundary, com a mensagem e o evento de
    #    auditoria (`agente.ferramenta.negada`) que já existiam — o caminho
    #    governado não pode piorar o diagnóstico de "não é sua ferramenta".
    boundary = AgentToolBoundary(manifesto, ctx["policy"], aprovador,
                                 audit=ctx.get("audit"))
    if not boundary.permitido(ferramenta):
        def _nunca_executa():                      # não é chamado: fora do manifesto
            raise ErroRuntime("executor inalcançável")
        return boundary.usar_ferramenta(ferramenta, _nunca_executa, alvo=alvo or "")

    registro = RegistroCapacidades(policy=ctx["policy"], approver=aprovador,
                                   audit=ctx.get("audit"))
    if decisor is None or autorizacao is None:
        d, a = sessao_pdp(registro, manifesto, audit=ctx.get("audit"),
                          caminhos=tuple(caminhos))
        decisor = decisor or d
        autorizacao = autorizacao or a

    brutos = executores_nativos(ctx, aprovador=aprovador, router=router,
                                sem_motor=sem_motor, manifesto=manifesto)
    if ferramenta not in brutos:
        # está no manifesto mas sem wiring nesta versão ⇒ falha fechada
        return False, (f"'{ferramenta}' está no manifesto de "
                       f"'{manifesto.name}' mas não tem execução ligada "
                       "nesta versão")
    peps = proteger_executores(brutos, decisor, audit=ctx.get("audit"))
    pedido = Pedido(capacidade=ferramenta, sujeito=manifesto.name,
                    recurso=alvo or "",
                    argumentos={"alvo": alvo or "", "conteudo": conteudo or ""},
                    nonce=secrets.token_hex(16))
    try:
        return True, peps[ferramenta](pedido, autorizacao,
                                      alvo=alvo or "", conteudo=conteudo or "")
    except NegadoPeloPEP as exc:
        return False, str(exc)
    except ErroRuntime as exc:
        # negação do boundary chega embrulhada — continua sendo negação
        return False, str(exc)


def proteger_executores(executores: dict[str, Callable], decisor,
                        audit=None) -> dict[str, "PontoDeAplicacao"]:
    """Embrulha cada executor num PEP. Devolve capacidade → PontoDeAplicacao.

    Depois disto, o executor bruto só existe dentro da closure do PEP: não há
    atributo público que devolva o callable original.
    """
    from nomos.pdp.pep import proteger
    return {nome: proteger(nome, fn, decisor, audit=audit)
            for nome, fn in executores.items()}


class RuntimeGovernado:
    """Runtime de orquestração do NOMOS. Um por missão (o orçamento é da missão).

    Construção barata e sem efeito: nada executa até `executar()`.
    """

    def __init__(self, ctx, aprovador=None, *, router=None,
                 sem_motor: bool = False, manifesto=None,
                 politica_recuperacao: PoliticaRecuperacao | None = None,
                 executores: dict[str, Callable] | None = None,
                 autorizacao=None, decisor=None, ttl_s: int = 3600,
                 caminhos: tuple[str, ...] = (), adapters: bool = False,
                 adapters_apenas_leitura: bool = False,
                 executaveis: tuple[str, ...] = (), scheduler=None):
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
        # ABSORPTION-03: adapters entram como capacidades DINÂMICAS, pelo
        # caminho governado (registrar é A5 + gate + audit). A allowlist
        # nativa de 8 ferramentas continua intocada.
        self.capacidades_adapter: list[str] = []
        if adapters:
            from nomos.adapters.wiring import registrar_filesystem
            self.capacidades_adapter = registrar_filesystem(
                self.registro, raizes=tuple(caminhos), audit=self.audit,
                apenas_leitura=adapters_apenas_leitura)
            if executaveis:
                # `script-rodar` só entra com allowlist de binário explícita —
                # A5 sem fronteira é shell com outro nome.
                from nomos.adapters.wiring import registrar_script
                self.capacidades_adapter += registrar_script(
                    self.registro, raizes=tuple(caminhos),
                    executaveis=tuple(executaveis), audit=self.audit)

        # ABSORPTION-05: o scheduler tem de ser registrado AQUI, junto com os
        # demais adapters, e não depois pelo chamador. Registrar depois foi o
        # bypass que o censo independente encontrou: `self.executores` (mapa
        # protegido por PEP) e `self.autorizacao` já estariam montados, então a
        # capacidade caía no fallback `registro.executor_de()` do Orquestrador
        # e executava pela ponte CRUA — sem PDP, sem PEP, sem escopo.
        if scheduler is not None:
            from nomos.adapters.wiring import registrar_scheduler
            self.capacidades_adapter += registrar_scheduler(
                self.registro, scheduler)
            # capacidades de CONTROLE tocam o armazém dentro do NOMOS_HOME, não
            # dado do usuário — o escopo precisa incluí-lo explicitamente, e só
            # quando o scheduler é ligado.
            caminhos = tuple(caminhos) + (str(ctx["home"]),)

        brutos = dict(executores if executores is not None
                      else executores_nativos(ctx, aprovador=aprovador,
                                              router=router, sem_motor=sem_motor,
                                              manifesto=self.manifesto))
        # FASE 2: o PDP não é opcional. Sem decisor entregue, o runtime emite
        # a própria autorização de SESSÃO — escopo = manifesto, teto de risco =
        # o do manifesto, prazo = ttl_s. A raiz de confiança é o dono que
        # abriu o CLI; o gate humano continua acontecendo no boundary.
        self.decisor, self.autorizacao = self._preparar_pdp(
            decisor, autorizacao, ttl_s, tuple(caminhos),
            extras=tuple(self.capacidades_adapter))
        # ABSORPTION-03: capacidades DINÂMICAS também precisam do PEP.
        # Sem isto o `Orquestrador._executor_para` cai em
        # `registro.executor_de()` e chama a ponte CRUA — um bypass do PDP
        # aberto pelo próprio wiring. Foi o teste de trilha que pegou:
        # `pdp.decisao` não aparecia na execução de uma capacidade de adapter.
        for nome in self.capacidades_adapter:
            bruto = self.registro.executor_de(nome)
            if bruto is not None and nome not in brutos:
                brutos[nome] = bruto

        self.executores_protegidos = proteger_executores(brutos, self.decisor,
                                                         audit=self.audit)
        self.executores = {nome: self._adaptar(nome, pep)
                           for nome, pep in self.executores_protegidos.items()}
        self.recuperacao = GerenciadorRecuperacao(
            politica=politica_recuperacao, audit=self.audit)
        self.rotear_motor = None
        self._router = router
        # Recurso padrão para capacidades de CONTROLE (sem alvo de dado). Sem
        # ele o PDP nega com "recurso vazio" — negação pelo motivo errado.
        self._recurso_padrao = str(ctx["home"]) if caminhos else ""

    # ---------------- PDP/PEP ----------------

    def _preparar_pdp(self, decisor, autorizacao, ttl_s: int, caminhos=(),
                      extras=()):
        """Decisor + autorização de sessão. Ambos obrigatórios para executar."""
        if decisor is not None and autorizacao is not None:
            return decisor, autorizacao
        d, a = sessao_pdp(self.registro, self.manifesto, audit=self.audit,
                          ttl_s=ttl_s, caminhos=caminhos, extras=extras)
        return (decisor or d), (autorizacao or a)

    def _adaptar(self, nome: str, pep) -> Callable:
        """Converte o PEP ao contrato `executor(**params)` do Orquestrador.

        Cada execução monta o próprio `Pedido` com nonce fresco (uso único) —
        é o adapter que carrega a identidade, nunca o nó.
        """
        from nomos.pdp.decisor import Pedido

        def _executar(**params):
            # O RECURSO de uma capacidade é o que ela toca. Para as de arquivo
            # é o `alvo`; para um processo é o `cwd` — é ali que ele lê e
            # escreve. Sem esta equivalência o PDP nega `script-rodar` com
            # "recurso vazio", que seria negar pelo motivo errado.
            # O RECURSO é o que a capacidade toca. Arquivo → `alvo`;
            # processo → `cwd`; operação de scheduler → o alvo do JOB que ela
            # agenda (`alvo_job`), ou o próprio armazém para as de controle
            # puro (listar/status/cancelar), que não tocam dado do usuário.
            recurso = str(params.get("alvo", "") or params.get("cwd", "")
                          or params.get("alvo_job", "") or self._recurso_padrao
                          or "")
            pedido = Pedido(capacidade=nome, sujeito=self.manifesto.name,
                            recurso=recurso,
                            argumentos=dict(params),
                            nonce=secrets.token_hex(16))
            return pep(pedido, self.autorizacao, **params)
        _executar.__name__ = f"pep_{nome}"
        return _executar

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
                           rotear_motor=self.rotear_motor,
                           estrito=True)
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
