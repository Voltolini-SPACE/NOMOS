"""NOMOS adapters.wiring — liga os adapters ao runtime governado (ABSORPTION-03).

Módulo existir não é capacidade existir. Enquanto os adapters não estiverem no
`RegistroCapacidades`, eles são camada pronta e nada mais: o planejador não os
conhece, o grafo os recusa, o PDP não tem o que autorizar. Este módulo é o elo
que os torna operacionais — pelo caminho governado, nunca por atalho.

## Por que capacidade DINÂMICA e não nativa

A allowlist de 8 ferramentas (`agents.manifest.FERRAMENTAS`) é invariante de
segurança do produto: "agente não é bypass". Dobrar essa lista mudaria um
contrato congelado e ampliaria a superfície nativa de uma vez.

O registro dinâmico (NH-001) existe exatamente para isto, e é ele próprio
governado: registrar é ato `A5_SKILL_INSTALL`, passa pelo `policy.gate`, exige
aprovador, é auditado, e nativa não pode ser sombreada. Uma capacidade nova
entra pela porta da frente, com aprovação — não por edição de constante.

## O que o executor registrado faz

Ele NÃO é o adapter cru. É uma ponte que:
1. monta `CapabilityContext` por `de_registro()` — risco e idempotência saem do
   registro, jamais do chamador;
2. propaga o escopo de caminho e o deadline do nó;
3. chama o adapter;
4. traduz `CapabilityResult` para o valor que o orquestrador espera, e
   `ErroCapacidade` para exceção (o orquestrador já trata falha de nó).

Nenhuma autoridade nova nasce aqui: quem decidiu se o nó podia executar foi o
gate do kernel + o PDP, antes.
"""
from __future__ import annotations

import time

from nomos.adapters.contrato import CapabilityContext, CapabilityRequest
from nomos.adapters.filesystem import FilesystemAdapter
from pathlib import Path

from nomos.adapters.contrato import ErroInvalido
from nomos.kernel.policy import Category

# Categoria de política de cada capacidade de filesystem. É AQUI que o risco é
# declarado — uma vez, no registro — e não no adapter nem no plano.
CATEGORIAS_FS: dict[str, Category] = {
    "fs-ler": Category.READ_LOCAL,
    "fs-listar": Category.READ_LOCAL,
    "fs-metadados": Category.READ_LOCAL,
    "fs-escrever": Category.WRITE_LOCAL,
    "fs-editar": Category.WRITE_LOCAL,
    "fs-criar-dir": Category.WRITE_LOCAL,
    "fs-mover": Category.WRITE_LOCAL,
    "fs-apagar": Category.WRITE_LOCAL,
}

# Repetir é seguro? Só para leitura. Escrita/edição/move/delete NÃO são
# idempotentes — repetir uma remoção às cegas é o tipo de "recuperação" que
# destrói dado. É esta tabela que autoriza retry, nunca o plano.
IDEMPOTENTES_FS = {"fs-ler", "fs-listar", "fs-metadados"}


def _ponte(adapter, nome: str, registro, *, raizes=(), audit=None,
           timeout_s: float | None = None):
    """Executor registrado: params do nó → adapter, com contexto derivado."""
    def _executar(**params):
        deadline = (time.monotonic() + timeout_s) if timeout_s else None
        ctx = CapabilityContext.de_registro(
            registro, nome, params.pop("_sujeito", "runtime-governado"),
            raizes=raizes, deadline_monotonic=deadline, audit=audit)
        pedido = CapabilityRequest(
            capacidade=nome,
            alvo=str(params.get("alvo", "") or ""),
            argumentos=dict(params))
        resultado = adapter.executar(pedido, ctx)
        return resultado.valor if resultado.valor is not None else resultado.detalhe
    _executar.__name__ = f"adapter_{nome}"
    _executar.__qualname__ = f"adapter_{nome}"
    return _executar


def registrar_filesystem(registro, *, raizes=(), audit=None,
                         timeout_s: float | None = 30.0,
                         apenas_leitura: bool = False) -> list[str]:
    """Registra as capacidades de filesystem. Devolve os nomes registrados.

    `apenas_leitura=True` registra só as três de leitura — atenuação legítima
    para contextos que não devem mutar nada.

    Cada `registrar()` passa pelo gate A5 do kernel; sem política ou sem
    aprovador, nada é registrado (fail-closed). Um `ErroRegistro` de "já
    registrada" é tratado como idempotência do próprio wiring, não como falha.
    """
    from nomos.orquestracao.registro import ErroRegistro

    # FAIL-CLOSED: sem raiz declarada, `resolver()` não restringe nada — e
    # registrar fs-apagar/fs-mover/fs-escrever nesse estado seria ENTREGAR
    # menos confinamento que o legado que eles substituem (`arquivo_escrever`
    # SEMPRE confina em NOMOS_HOME/workspace). Um censo adversarial apontou
    # exatamente isso: `adapters=True` sem `caminhos` daria delete recursivo de
    # caminho arbitrário. Leitura sem raiz continua permitida — é o
    # comportamento herdado e consciente das missões anteriores.
    if not raizes and not apenas_leitura:
        raise ValueError(
            "registrar capacidades MUTANTES de filesystem exige `raizes` "
            "explícitas — sem escopo elas seriam menos confinadas que as "
            "ferramentas nativas que substituem (use apenas_leitura=True "
            "para registrar só leitura)")

    adapter = FilesystemAdapter()
    nomes = sorted(IDEMPOTENTES_FS) if apenas_leitura else sorted(CATEGORIAS_FS)
    registrados = []
    for nome in nomes:
        try:
            registro.registrar(
                nome, CATEGORIAS_FS[nome],
                _ponte(adapter, nome, registro, raizes=raizes, audit=audit,
                       timeout_s=timeout_s),
                origem="adapters.filesystem",
                idempotente=nome in IDEMPOTENTES_FS)
            registrados.append(nome)
        except ErroRegistro as exc:
            if "já registrada" in str(exc):
                registrados.append(nome)
                continue
            raise
    return registrados


# ---------------------------------------------------------------- scheduler

# Risco das operações de scheduler, pela DIREÇÃO da autoridade.
#
# ARMAR execução futura (criar, habilitar) é o ato sensível: um job persistido
# age depois, possivelmente sem ninguém olhando. Classificado como
# A5_CODE_EXEC, porque é exatamente isso — arranjar execução.
#
# DESARMAR (desabilitar, cancelar, apagar) REDUZ autoridade. Exigir aprovação
# forte para desligar algo perigoso seria pedir que a saída de emergência
# tivesse fechadura: A1_WRITE_LOCAL basta, e a direção segura da falha é
# conseguir desligar.
CATEGORIAS_SCHED: dict[str, Category] = {
    "sched-listar": Category.READ_LOCAL,
    "sched-status": Category.READ_LOCAL,
    "sched-criar": Category.CODE_EXEC,
    "sched-habilitar": Category.CODE_EXEC,
    "sched-desabilitar": Category.WRITE_LOCAL,
    "sched-cancelar": Category.WRITE_LOCAL,
    "sched-apagar": Category.WRITE_LOCAL,
}

IDEMPOTENTES_SCHED = {"sched-listar", "sched-status"}


def _ponte_sched(scheduler, nome: str, registro):
    """Executor registrado para uma operação de scheduler.

    Cada operação é uma capacidade separada de propósito: assim o gate A0–A6
    e o PDP decidem por OPERAÇÃO — listar não carrega a autoridade de cancelar.
    """
    def _executar(**params):
        job_id = str(params.get("job_id", "") or params.get("alvo", "") or "")
        if nome == "sched-listar":
            # Devolve o registro DESCRITO, não só o id. Devolver id opaco
            # obrigava quem lista a ou fazer N chamadas extras ou ler o
            # armazém direto — e ler direto é exatamente o desvio que tirou a
            # CLI da cadeia governada. A leitura é A0: descrever não amplia
            # autoridade nenhuma, só remove o incentivo de contornar.
            saida = []
            for d in scheduler.listar():
                a = d.agenda()
                saida.append({"job_id": d.job_id, "capacidade": d.capacidade,
                              "estado": d.estado.value, "kind": a.kind.value,
                              "expression": a.expression, "tz": a.timezone,
                              "intervalo_s": a.intervalo_s,
                              "proximo_em": (d.proximo_em.isoformat()
                                             if d.proximo_em else "")})
            return saida
        if nome == "sched-status":
            return scheduler.status(job_id).estado.value
        if nome == "sched-criar":
            # ACHADO DO CENSO: esta ponte não aceitava agenda, então um job
            # criado pela capacidade governada virava ONE_SHOT em SILÊNCIO —
            # `expression` e `tz` eram ignorados e o motor de cron ficava
            # inalcançável por caller de produção. É o mesmo rebaixamento
            # silencioso CRON→ONE_SHOT que a 04 corrigiu na persistência,
            # reintroduzido na camada do caller.
            from nomos.adapters.agenda import ScheduleSpec, TipoAgenda
            alvo_capacidade = str(params.get("capacidade", ""))
            # Agendar capacidade que o registro não conhece é agendar nada: o
            # job fica SCHEDULED, o operador lê "criado", e a descoberta vem
            # ocorrência a ocorrência, quando o autorizador recusa. Job morto
            # que se anuncia vivo é pior que job recusado.
            if not registro.conhecida(alvo_capacidade):
                raise ErroInvalido(
                    f"capacidade desconhecida: {alvo_capacidade!r} — o job "
                    "nunca executaria; registre a capacidade (as mesmas flags "
                    "que o ticker usará) antes de agendá-la")
            # Scheduler que se opera sozinho no relógio é laço de controle sem
            # operador dentro. Gerir jobs é ato do operador, não de um job.
            if alvo_capacidade.startswith("sched-"):
                raise ErroInvalido(
                    f"job não pode ter capacidade de scheduler ({alvo_capacidade}): "
                    "agendar a própria gestão de agendamentos tira o operador "
                    "do laço")
            tz = str(params.get("tz", "UTC"))
            expressao = params.get("cron") or params.get("expression")
            intervalo = params.get("intervalo_s")
            # Duas agendas no mesmo pedido é intenção AMBÍGUA, não uma com
            # precedência sobre a outra. Antes a ponte escolhia cron e ainda
            # repassava `intervalo_s`, gravando um registro que dizia CRON num
            # campo e 60s no outro — e cada leitor (`recorrente()`, `proximo()`,
            # a linha do `listar`) consultava um campo diferente. Quem pediu
            # duas coisas incompatíveis recebe recusa, não sorteio.
            # `is not None`, não truthiness: `intervalo_s=0` é entrada inválida
            # e precisa CHEGAR à validação que a recusa. Testar por verdade
            # faria o zero desaparecer no caminho e o job virar ONE_SHOT em
            # silêncio — o mesmo defeito que o censo achou em `--intervalo 0`.
            if expressao and intervalo is not None:
                raise ErroInvalido(
                    "agenda ambígua: `cron` e `intervalo_s` juntos — escolha "
                    "uma; agendar não pode depender de qual campo o leitor olha")
            schedule = None
            if expressao:
                # `kind` continua EXPLÍCITO: só vira cron porque veio `cron=`,
                # nunca por adivinhação sobre o formato da string.
                schedule = ScheduleSpec(kind=TipoAgenda.CRON,
                                        expression=str(expressao), timezone=tz)
            elif intervalo is not None:
                schedule = ScheduleSpec(kind=TipoAgenda.INTERVAL,
                                        intervalo_s=int(intervalo), timezone=tz)
            else:
                # ONE_SHOT explícito: assim a tz é validada aqui também, em vez
                # de só quando `Scheduler.criar` monta o spec padrão.
                schedule = ScheduleSpec(kind=TipoAgenda.ONE_SHOT, timezone=tz)
            d = scheduler.criar(
                job_id, str(params.get("sujeito", "runtime-governado")),
                str(params.get("capacidade", "")),
                argumentos=params.get("argumentos") or {},
                alvo=str(params.get("alvo_job", "") or ""),
                intervalo_s=intervalo, tz=tz, schedule=schedule)
            return d.job_id
        if nome == "sched-habilitar":
            return scheduler.habilitar(job_id).estado.value
        if nome == "sched-desabilitar":
            return scheduler.desabilitar(job_id).estado.value
        if nome == "sched-cancelar":
            return scheduler.cancelar(job_id).estado.value
        if nome == "sched-apagar":
            scheduler.apagar(job_id)
            return job_id
        raise ErroInvalido(f"operação de scheduler desconhecida: {nome}")
    _executar.__name__ = f"adapter_{nome.replace('-', '_')}"
    _executar.__qualname__ = _executar.__name__
    return _executar


def registrar_scheduler(registro, scheduler, *, apenas_leitura: bool = False) -> list[str]:
    """Registra as operações de scheduler como capacidades governadas."""
    from nomos.orquestracao.registro import ErroRegistro

    nomes = sorted(IDEMPOTENTES_SCHED) if apenas_leitura else sorted(CATEGORIAS_SCHED)
    registrados = []
    for nome in nomes:
        try:
            registro.registrar(nome, CATEGORIAS_SCHED[nome],
                               _ponte_sched(scheduler, nome, registro),
                               origem="adapters.scheduler",
                               idempotente=nome in IDEMPOTENTES_SCHED)
            registrados.append(nome)
        except ErroRegistro as exc:
            if "já registrada" in str(exc):
                registrados.append(nome)
                continue
            raise
    return registrados


# ------------------------------------------------------------------ script

CATEGORIAS_SCRIPT: dict[str, Category] = {
    # Rodar processo é o segundo maior risco da escala. Não existe versão
    # "leve" disto: quem autoriza `script-rodar` autoriza execução.
    "script-rodar": Category.CODE_EXEC,
}


def _ponte_script(adapter, registro, *, raizes, executaveis, audit, timeout_s):
    """Executor registrado para `script-rodar`.

    A allowlist de executáveis é FIXADA no registro, não vem do chamador. Se
    viesse por parâmetro, um plano hostil a ampliaria — exatamente o padrão que
    o NOMOS recusa desde a ABSORPTION-01: quem executa não define o próprio
    limite.
    """
    import time

    from nomos.adapters.contrato import CapabilityContext, CapabilityRequest

    def _executar(**params):
        deadline = (time.monotonic() + timeout_s) if timeout_s else None
        ctx = CapabilityContext.de_registro(
            registro, "script-rodar",
            params.pop("_sujeito", "runtime-governado"),
            raizes=raizes, deadline_monotonic=deadline, audit=audit)
        argumentos = dict(params)
        argumentos["executaveis"] = list(executaveis)   # não negociável
        pedido = CapabilityRequest(capacidade="script-rodar",
                                   alvo=str(params.get("alvo", "") or ""),
                                   argumentos=argumentos)
        resultado = adapter.executar(pedido, ctx)
        valor = resultado.valor
        return {"codigo": valor.codigo, "stdout": valor.stdout,
                "stderr": valor.stderr, "truncado": valor.truncado}
    _executar.__name__ = "adapter_script_rodar"
    _executar.__qualname__ = "adapter_script_rodar"
    return _executar


def validar_executaveis(brutos) -> tuple[str, ...]:
    """Canonicaliza e valida a allowlist. Qualquer anomalia ⇒ recusa.

    Uma allowlist só vale se cada entrada for provada AGORA: existe, é arquivo,
    tem bit de execução, e é o caminho REAL (realpath). Guardar o caminho
    lógico deixaria a porta aberta para troca de symlink entre o registro e o
    uso — o mesmo TOCTOU que `adapters/caminho.py` fecha para dados.

    Duplicatas são normalizadas: dois caminhos que resolvem para o mesmo
    binário são uma entrada só.
    """
    import os

    if not brutos:
        raise ValueError("allowlist de executáveis vazia")
    reais: list[str] = []
    for bruto in brutos:
        if not isinstance(bruto, str) or not bruto.strip():
            raise ValueError(f"caminho de executável inválido: {bruto!r}")
        caminho = Path(os.path.realpath(os.path.abspath(bruto.strip())))
        if not caminho.exists():
            raise ValueError(f"executável não existe: {bruto!r} → {caminho}")
        if caminho.is_dir():
            raise ValueError(f"é diretório, não executável: {caminho}")
        if not caminho.is_file():
            raise ValueError(f"não é arquivo regular: {caminho}")
        if not os.access(caminho, os.X_OK):
            raise ValueError(f"sem bit de execução: {caminho}")
        nome = caminho.name.lower()
        from nomos.adapters.script import INTERPRETADORES_DE_SHELL
        if nome in INTERPRETADORES_DE_SHELL:
            raise ValueError(
                f"'{bruto}' é interpretador de shell — não entra em allowlist "
                "de script; rodar shell é outra capacidade")
        if str(caminho) not in reais:
            reais.append(str(caminho))
    return tuple(reais)


def registrar_script(registro, *, raizes, executaveis, audit=None,
                     timeout_s: float | None = 30.0) -> list[str]:
    """Registra `script-rodar`. Exige raízes E allowlist de executáveis.

    Fail-closed nos dois eixos, pelo mesmo motivo do filesystem mutante: sem
    escopo de dados o processo lê e escreve onde quiser, e sem allowlist de
    binário ele roda o que quiser. Registrar assim seria entregar A5 sem
    fronteira — e A5 sem fronteira é shell com outro nome.
    """
    from nomos.adapters.script import ScriptAdapter
    from nomos.orquestracao.registro import ErroRegistro

    if not raizes:
        raise ValueError(
            "registrar `script-rodar` exige `raizes` explícitas (escopo de "
            "dados do processo)")
    if not executaveis:
        raise ValueError(
            "registrar `script-rodar` exige `executaveis` explícitos — A5 sem "
            "allowlist de binário é shell com outro nome")
    executaveis = validar_executaveis(executaveis)   # canonicaliza e prova
    try:
        registro.registrar(
            "script-rodar", Category.CODE_EXEC,
            _ponte_script(ScriptAdapter(), registro, raizes=tuple(raizes),
                          executaveis=tuple(executaveis), audit=audit,
                          timeout_s=timeout_s),
            origem="adapters.script", idempotente=False)
    except ErroRegistro as exc:
        if "já registrada" not in str(exc):
            raise
    return ["script-rodar"]
