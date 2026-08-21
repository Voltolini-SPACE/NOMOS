"""NOMOS runtime.agendador — o caller de produção do scheduler (ABSORPTION-05).

A ABSORPTION-04 construiu `Scheduler`, `Ticker` e `script-rodar` e não ligou o
fio: o censo independente encontrou **zero callers em `src/`** para
`registrar_scheduler()` e para `Ticker`. Módulo existir não é capacidade
existir — e a lição já tinha sido dada na 03.

Este módulo é o fio.

    CLI
      → AgendadorGovernado
      → Scheduler (store em NOMOS_HOME/scheduler/jobs.db)
      → registrar_scheduler()  → registro de capacidades (A5 + gate + audit)
      → Ticker (autorizador OBRIGATÓRIO)
      → ocorrência devida → reserva persistente
      → autorização POR OCORRÊNCIA (fresca)
      → PDP → PEP → boundary → adapter → efeito → audit

## Uma só autoridade

Não existe `scheduler_registry`, `scheduler_policy` nem `scheduler_executor`
paralelo. O scheduler usa o MESMO `RegistroCapacidades` que o planner e o PDP
consultam, e a execução de uma ocorrência é a MESMA
`RuntimeGovernado.executar()` de qualquer outra coisa. Um segundo caminho de
execução seria um segundo modelo de segurança — e o segundo sempre é o mais
fraco.

## Autoridade por ocorrência, de verdade

O `autorizador` que este módulo entrega ao ticker constrói um
`RuntimeGovernado` NOVO a cada ocorrência. Isso não é desperdício: é o que faz
a política, o registro e o escopo valerem no instante T2 da execução, e não no
T0 da criação do job. Um `RuntimeGovernado` reaproveitado carregaria a
autorização de sessão emitida lá atrás — autorização eterna com outro nome.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from nomos.adapters.alertas import AuditAlertSink
from nomos.adapters.scheduler import ArmazemJobs, JobDefinition, Scheduler
from nomos.adapters.ticker import CatchUp, Ticker


def caminho_do_armazem(home) -> Path:
    """`NOMOS_HOME/scheduler/jobs.db` — um só lugar, previsível e auditável."""
    return Path(home) / "scheduler" / "jobs.db"


@dataclass(frozen=True)
class ConfigAgendador:
    """O que o operador escolheu. Tudo explícito, nada inferido."""
    raizes: tuple[str, ...] = ()
    executaveis: tuple[str, ...] = ()
    catchup: CatchUp = CatchUp.RUN_ONCE
    catchup_max: int = 10
    intervalo_s: float = 1.0


class AgendadorGovernado:
    """Scheduler + Ticker ligados ao runtime governado.

    Construção não executa nada e não regista nada: `preparar()` é o passo
    intencional. Ativação de capacidade nunca acontece por import.
    """

    def __init__(self, ctx, aprovador, config: ConfigAgendador | None = None,
                 *, agora_fn=lambda: datetime.now(timezone.utc)):
        if ctx is None or "policy" not in ctx:
            from nomos.runtime.governado import ErroRuntime
            raise ErroRuntime("contexto sem política carregada — fail-closed")
        if aprovador is None:
            from nomos.runtime.governado import ErroRuntime
            raise ErroRuntime(
                "agendador exige aprovador: registrar capacidade é ato "
                "sensível (A5) e não pode acontecer sem gate")
        self.ctx = ctx
        # NH-017c: o disjuntor vive AQUI (uma instância por agendador) e
        # atravessa as ocorrências do processo do ticker — o cenário real de
        # fadiga. Envolver no RuntimeGovernado não funcionaria: o agendador
        # constrói um runtime NOVO por ocorrência, memória zero.
        from nomos.kernel.disjuntor import DisjuntorAprovacoes
        self.aprovador = DisjuntorAprovacoes(
            audit=ctx.get("audit")).envolver(aprovador)
        self.config = config or ConfigAgendador()
        self._agora = agora_fn
        self.audit = ctx.get("audit")
        self.armazem = ArmazemJobs(caminho_do_armazem(ctx["home"]))
        self.scheduler = Scheduler(
            self.armazem, executor=self._executar_ocorrencia,
            audit=self.audit, agora_fn=agora_fn,
            alert_sink=AuditAlertSink(self.audit) if self.audit else None)
        self.capacidades: list[str] = []
        self._preparado = False

    # ------------------------------------------------------------- preparação

    def preparar(self) -> list[str]:
        """Confirma que as capacidades de scheduler estão ALCANÇÁVEIS.

        Antes este método chamava `registrar_scheduler(rt.registro, …)` num
        `RuntimeGovernado` que ele descartava na linha seguinte. O registro
        acontecia mesmo — num registro que ninguém mais consultava. O operador
        via as sete capacidades anunciadas na saída da CLI e nenhuma delas era
        executável: `_runtime()` construía um runtime NOVO, sem scheduler, e
        `sched-criar` caía em `CAPACIDADE_DESCONHECIDA`. Falhava fechado, o que
        evitou o pior, mas o efeito prático era um scheduler que só podia ser
        operado por chamada CRUA ao adapter — precisamente o desvio que esta
        cadeia existe para impedir.

        Agora quem registra é o construtor do `RuntimeGovernado` (junto com os
        demais adapters, dentro do mapa protegido por PEP e da autorização
        assinada), e este método apenas CONFERE — e recusa se a conferência
        falhar. Anunciar capacidade inalcançável é pior que não ter nenhuma.
        """
        rt = self._runtime()
        nomes = sorted(n for n in rt.capacidades_adapter if n.startswith("sched-"))
        if not nomes:
            raise RuntimeError(
                "nenhuma capacidade de scheduler registrada no runtime — "
                "fail-closed em vez de anunciar um scheduler que não opera")
        inalcancaveis = [n for n in nomes
                         if n not in rt.executores
                         or n not in rt.autorizacao.capacidades]
        if inalcancaveis:
            raise RuntimeError(
                f"capacidades registradas mas INALCANÇÁVEIS: {inalcancaveis} — "
                "fora do mapa protegido por PEP ou fora da autorização")
        self.capacidades = nomes
        self._preparado = True
        if self.audit is not None:
            self.audit.append("agendador.preparado",
                              capacidades=",".join(self.capacidades),
                              armazem=str(self.armazem.caminho))
        return list(self.capacidades)

    def _runtime(self):
        """Um `RuntimeGovernado` NOVO — autoridade fresca, sempre.

        Construir de novo a cada ocorrência é o que faz política, registro e
        escopo valerem no instante da EXECUÇÃO, não no da criação do job.

        `scheduler=` entra AQUI, no construtor, para que as capacidades
        `sched-*` nasçam dentro de `executores` (mapa protegido por PEP) e
        dentro da autorização assinada. Registrar depois da construção foi o
        bypass da ABSORPTION-05; registrar num runtime descartado foi o buraco
        que o sucedeu.
        """
        from nomos.runtime.governado import RuntimeGovernado
        return RuntimeGovernado(
            self.ctx, self.aprovador,
            caminhos=self.config.raizes,
            adapters=bool(self.config.raizes),
            executaveis=self.config.executaveis,
            scheduler=self.scheduler)

    # ------------------------------------------------------------- operação

    def operar(self, operacao: str, /, **params):
        """Executa UMA operação de scheduler pela cadeia governada completa.

        É o que a CLI usa. Sem este método, todo chamador que quisesse criar ou
        listar job teria de falar com `self.scheduler` direto — sem PDP, sem
        PEP, sem trilha. Devolve `(ok, valor, motivo)`.

        `operacao` é POSICIONAL-ONLY: os jobs têm um parâmetro chamado
        `capacidade`, e um argumento nomeado aqui roubaria o do outro calado.
        """
        rt = self._runtime()
        if operacao not in rt.executores:
            return False, None, f"capacidade indisponível: {operacao}"
        res = rt.rodar(f"scheduler:{operacao}",
                       passos=[{"id": "op", "ferramenta": operacao,
                                "params": dict(params)}])
        no = (res.missao.nos.get("op") if res.missao is not None else None)
        if not res.ok:
            motivo = (no.detalhe if no is not None and no.detalhe
                      else (res.motivo or "sem detalhe"))
            return False, None, motivo
        return True, (no.resultado if no is not None else None), ""

    # ------------------------------------------------------------- execução

    def autorizador(self, definicao: JobDefinition, instancia):
        """Autoridade POR OCORRÊNCIA. `None` ⇒ o ticker recusa a ocorrência.

        Constrói runtime novo (autorização fresca, registro revalidado) e
        confere que a capacidade do job ainda existe e ainda é executável. Se o
        registro mudou desde a criação do job, isto é onde se descobre.
        """
        try:
            rt = self._runtime()
        except Exception:
            return None                       # sem runtime não há autoridade
        if not rt.registro.conhecida(definicao.capacidade):
            if self.audit is not None:
                self.audit.append("agendador.capacidade.sumiu",
                                  job=definicao.job_id,
                                  capacidade=definicao.capacidade)
            return None
        if definicao.capacidade not in rt.executores:
            if self.audit is not None:
                self.audit.append("agendador.capacidade.sem_executor",
                                  job=definicao.job_id,
                                  capacidade=definicao.capacidade)
            return None
        return rt

    def _executar_ocorrencia(self, definicao: JobDefinition, instancia,
                             credencial=None):
        """Executa a capacidade do job pela cadeia governada COMPLETA.

        `credencial` é o `RuntimeGovernado` fresco vindo do autorizador. Sem
        ele, não executa — o scheduler não tem caminho próprio até o adapter.
        """
        from nomos.runtime.governado import ErroRuntime
        rt = credencial
        if rt is None:
            raise ErroRuntime(
                "ocorrência sem autoridade: o agendador não executa sem "
                "runtime governado (fail-closed)")
        passos = [{
            "id": "job",
            "ferramenta": definicao.capacidade,
            "params": dict(definicao.argumentos or {}),
        }]
        if definicao.alvo:
            passos[0]["params"].setdefault("alvo", definicao.alvo)
        resultado = rt.rodar(f"job:{definicao.job_id}", passos=passos)
        if not resultado.ok:
            no = (resultado.missao.nos.get("job")
                  if resultado.missao is not None else None)
            motivo = (no.detalhe if no is not None else resultado.motivo) or "sem detalhe"
            raise ErroRuntime(f"ocorrência falhou: {motivo}")
        # O efeito é DERIVADO do registro, não afirmado. Antes esta linha era
        # `efeito_aplicado: True` literal, então um job `fs-listar` — leitura
        # A0, idempotente, que comprovadamente não muda nada — gravava efeito=1
        # e saía como EXECUTED_EFFECT/EFFECT_APPLIED, com `autoriza_retry=False`.
        # Isso contradiz a premissa da fonte única da ETAPA 3: só se afirma
        # efeito quando se SABE. E a informação estava aqui o tempo todo — o
        # registro é a autoridade sobre risco desde a ABSORPTION-03, e leitura
        # não é mutação. Quem não observou o efeito não o declara.
        from nomos.kernel.policy import Category
        categoria = rt.registro.categoria_de(definicao.capacidade)
        muta = categoria is not Category.READ_LOCAL
        return type("R", (), {"efeito_aplicado": muta})()

    # ------------------------------------------------------------- ticker

    def ticker(self, *, dormir=None) -> Ticker:
        """Ticker com autorizador OBRIGATÓRIO — o nosso, nunca `None`."""
        if not self._preparado:
            raise RuntimeError("chame `preparar()` antes de montar o ticker")
        extra = {} if dormir is None else {"dormir": dormir}
        from nomos.kernel import pausa
        return Ticker(self.scheduler, self.autorizador, audit=self.audit,
                      alert_sink=AuditAlertSink(self.audit) if self.audit else None,
                      catchup=self.config.catchup,
                      catchup_max=self.config.catchup_max,
                      intervalo_s=self.config.intervalo_s,
                      agora_fn=self._agora,
                      pausado_fn=lambda: pausa.esta_pausado(self.ctx["home"]),
                      **extra)
