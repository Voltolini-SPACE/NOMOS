"""NOMOS adapters.ticker — o loop que transforma job em ocorrência (FASE 3-4).

    CLOCK → STORE → DUE → RESERVATION → AUTHORIZATION → PDP → PEP
          → BOUNDARY → CAPABILITY → AUDIT → FINALIZE

Componente **foreground e testável**, não daemon. A ABSORPTION-04 proíbe
instalar serviço; o ticker é a peça que um daemon futuro embrulha, e que aqui
já roda sob teste com relógio injetável.

## Autorização é POR OCORRÊNCIA

Um job criado em T0 e executado em T2 não pode usar autoridade de T0. O ticker
não guarda token: para CADA ocorrência ele chama o `autorizador`, que devolve
`(decisor, autorizacao)` frescos. Se a política, o registro ou o escopo mudaram
entre T0 e T2, a decisão em T2 reflete T2 — e o `versoes` do descritor
(ABSORPTION-03) faz o PDP recusar metadata obsoleta.

## Catch-up é explícito

Máquina desligada por 5 horas com um job de 5 em 5 minutos: rodar 60 vezes?
uma? nenhuma? Não deixo isso implícito.

    SKIP             ignora o atrasado, reagenda para a próxima ocorrência
    RUN_ONCE         roda UMA vez (default) e reagenda
    RUN_ALL_BOUNDED  roda as perdidas até um teto explícito

## Sem busy-loop

`rodar_ate` dorme entre passadas com um `dormir` injetável. O teste usa um
relógio falso e não espera de verdade; a produção usa `time.sleep`. Em nenhum
dos dois o loop gira sem pausa.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from nomos.adapters.alertas import AuditAlertSink, EventoFalha
from nomos.adapters.scheduler import JobDefinition, JobInstance, JobState


# Sentinela para "rodar sem autoridade", que só existe para teste. É preciso
# NOMEAR essa escolha: um `None` esquecido não pode significar a mesma coisa.
SEM_AUTORIZACAO = object()


class CatchUp(str, Enum):
    SKIP = "SKIP"
    RUN_ONCE = "RUN_ONCE"
    RUN_ALL_BOUNDED = "RUN_ALL_BOUNDED"


@dataclass(frozen=True)
class ResultadoTick:
    """O que uma passada fez. `executadas` conta EFEITOS, não tentativas."""
    examinados: int = 0
    executadas: int = 0
    puladas: int = 0
    falhas: int = 0
    negadas: int = 0


class Ticker:
    """Uma passada = `tick()`. Um loop com pausa = `rodar_ate()`."""

    def __init__(self, scheduler, autorizador, *, audit=None,
                 alert_sink=None, catchup: CatchUp = CatchUp.RUN_ONCE,
                 catchup_max: int = 10, intervalo_s: float = 1.0,
                 agora_fn=lambda: datetime.now(timezone.utc),
                 dormir=time.sleep):
        # FAIL-CLOSED (achado do censo independente): `autorizador` era
        # opcional e o default `None` fazia o ticker executar o efeito com
        # `credencial=None`. "Autorização por ocorrência" virava opt-in — e
        # invariante que se pode desligar por omissão não é invariante.
        # Agora é posicional e obrigatório; quem realmente não quer autoridade
        # tem de dizer isso em voz alta com `SEM_AUTORIZACAO`.
        if autorizador is None:
            raise ValueError(
                "Ticker exige `autorizador`. Para rodar sem autoridade "
                "(apenas em teste) passe `ticker.SEM_AUTORIZACAO` "
                "explicitamente — o default não pode ser fail-open")
        self.scheduler = scheduler
        self.autorizador = None if autorizador is SEM_AUTORIZACAO else autorizador
        self.audit = audit
        self.alertas = alert_sink or (AuditAlertSink(audit) if audit else None)
        self.catchup = catchup
        self.catchup_max = max(1, int(catchup_max))
        self.intervalo_s = max(0.0, float(intervalo_s))
        self._agora = agora_fn
        self._dormir = dormir
        self._parar = False

    # ---------------------------------------------------------------- loop

    def parar(self) -> None:
        """Shutdown limpo: a passada corrente termina, e não começa outra."""
        self._parar = True

    def tick(self) -> ResultadoTick:
        agora = self._agora()
        devidos = self.scheduler.devidos(agora)
        r = ResultadoTick(examinados=len(devidos))
        for d in devidos:
            if self._parar:
                break
            r = self._processar(d, agora, r)
        return r

    def rodar_ate(self, condicao=None, max_ticks: int | None = None) -> list[ResultadoTick]:
        """Roda até `parar()`, até `condicao()` virar False, ou `max_ticks`.

        Sempre dorme entre passadas — inclusive quando não houve trabalho. É o
        que impede o busy-loop, e é observável: o teste conta as pausas.
        """
        self._parar = False
        resultados: list[ResultadoTick] = []
        n = 0
        while not self._parar:
            if max_ticks is not None and n >= max_ticks:
                break
            if condicao is not None and not condicao():
                break
            resultados.append(self.tick())
            n += 1
            if self._parar:
                break
            self._dormir(self.intervalo_s)
        return resultados

    # ------------------------------------------------------------ execução

    def _processar(self, d: JobDefinition, agora: datetime,
                   r: ResultadoTick) -> ResultadoTick:
        atrasadas, descartadas = self._ocorrencias_pendentes(d, agora)
        if not atrasadas:
            return r
        if self.catchup is CatchUp.SKIP:
            # SKIP roda SÓ a mais recente. Sempre — não "quando a lista foi
            # truncada". A versão anterior colapsava a lista apenas se
            # `recente != atrasadas[-1]`, condição que só é verdadeira quando
            # `catchup_max` TRUNCA a lista. Com poucas ocorrências vencidas —
            # o restart curto, que é o caso comum — a condição era falsa e o
            # laço abaixo executava TODAS: SKIP virava RUN_ALL_BOUNDED sem
            # avisar. Os três testes que cobriam SKIP usavam 5h de downtime, o
            # único regime em que o teto trunca e o acerto acontecia por
            # acidente. Havia ainda um `if False and …` logo abaixo — a lógica
            # geral, desativada. Um ramo morto é uma defesa que o leitor conta
            # como presente e que nunca roda.
            recente = self.scheduler.mais_recente_ate(d, agora)
            alvo = recente if recente is not None else atrasadas[-1]
            puladas = max(0, len(atrasadas) - 1)
            if puladas:
                self._auditar("ticker.catchup.pulou", job=d.job_id,
                              politica=self.catchup.value, puladas=puladas)
                r = ResultadoTick(r.examinados, r.executadas,
                                  r.puladas + puladas, r.falhas, r.negadas)
            atrasadas = [alvo]
        elif descartadas:
            # RUN_ALL_BOUNDED com o teto batendo: as ocorrências além do teto
            # são DESCARTADAS de propósito (sem teto, o daemon acorda de uma
            # parada longa e martela o mundo). Descartar é legítimo; descartar
            # em SILÊNCIO não é — o operador precisa conseguir responder
            # "quantas execuções eu perdi na queda de ontem?". O número é
            # reportado como PISO (`>=`) porque contá-las exatamente exigiria
            # enumerar a agenda inteira a cada tick, que é o custo que o teto
            # existe para evitar.
            self._auditar("ticker.catchup.descartou", job=d.job_id,
                          politica=self.catchup.value,
                          descartadas_no_minimo=descartadas)
            self._alertar_descarte(d, atrasadas[0], descartadas)
            r = ResultadoTick(r.examinados, r.executadas,
                              r.puladas + descartadas, r.falhas, r.negadas)
        for quando in atrasadas:
            ex = self._executar_ocorrencia(d, quando, agora)
            if ex is None:
                r = ResultadoTick(r.examinados, r.executadas, r.puladas + 1,
                                  r.falhas, r.negadas)
            elif ex.estado_final is JobState.DENIED:
                # NEGADA não é PULADA. Antes tudo virava `puladas` e `negadas`
                # nunca era incrementado — a CLI imprimia "executadas: 0 ·
                # falhas: 0" e saía EXIT_OK com 100% das ocorrências recusadas.
                # O único sinal que o operador tinha mentia.
                r = ResultadoTick(r.examinados, r.executadas, r.puladas,
                                  r.falhas, r.negadas + 1)
            elif ex.estado_final is JobState.SUCCEEDED:
                r = ResultadoTick(r.examinados, r.executadas + 1, r.puladas,
                                  r.falhas, r.negadas)
            else:
                r = ResultadoTick(r.examinados, r.executadas, r.puladas,
                                  r.falhas + 1, r.negadas)
        return r

    # Teto da SONDA que conta ocorrências descartadas. Contar exatamente
    # exigiria enumerar a agenda inteira a cada tick — o custo que
    # `catchup_max` existe para evitar. Contar até aqui e reportar o número
    # como PISO dá ao operador uma grandeza verdadeira sem reintroduzir o
    # problema: "perdi pelo menos 1000" já responde a pergunta que importa.
    SONDA_MAX = 1000

    def _ocorrencias_pendentes(self, d: JobDefinition,
                               agora: datetime) -> tuple[list[datetime], int]:
        """`(instantes a executar, quantas ficaram de fora)`.

        A contagem de descartadas passou a sair DAQUI porque era o único lugar
        que sabia o número: `_processar` só via a lista já cortada e reportava
        `puladas=0` para 51 ocorrências perdidas.
        """
        base = d.proximo_em
        if base is None or base > agora:
            return [], 0
        if self.catchup is CatchUp.RUN_ONCE or not d.recorrente():
            return [base], 0

        if self.catchup is CatchUp.SKIP:
            # SKIP quer UMA: a mais recente vencida. Não precisa da lista, e
            # montá-la era trabalho jogado fora — o laço daqui era cópia do
            # RUN_ALL_BOUNDED e ficou sem função quando o colapso virou
            # incondicional.
            recente = self.scheduler.mais_recente_ate(d, agora) or base
            return [recente], self._contar_entre(d, base, recente)

        pendentes = [base]
        proximo = base
        while len(pendentes) < self.catchup_max:
            seguinte = self.scheduler.proximo_apos(d, proximo)
            if seguinte is None or seguinte > agora:
                return pendentes, 0
            pendentes.append(seguinte)
            proximo = seguinte
        return pendentes, self._contar_entre(d, proximo, agora)

    def _contar_entre(self, d: JobDefinition, depois_de: datetime,
                      ate: datetime) -> int:
        """Quantas ocorrências existem em `(depois_de, ate]`, com teto."""
        n, proximo = 0, depois_de
        while n < self.SONDA_MAX:
            seguinte = self.scheduler.proximo_apos(d, proximo)
            if seguinte is None or seguinte > ate:
                break
            n += 1
            proximo = seguinte
        return n

    def _alertar_descarte(self, d: JobDefinition, quando: datetime,
                          quantas: int) -> None:
        """Emite `MISSED` — o estado que existia na taxonomia sem emissor.

        A ETAPA 3 criou `MISSED` e `RECOVERED` e não ligou nenhum dos dois.
        Estado de taxonomia sem emissor é vocabulário, não observabilidade: dá
        a impressão de que o sistema distingue casos que ele nunca reporta.
        """
        if self.alertas is None:
            return
        from nomos.adapters.resultado import ResultadoOcorrencia, canonico
        estado = canonico(ResultadoOcorrencia.MISSED,
                          error_class="CatchUpExcedido",
                          detalhe=f"pelo menos {quantas} ocorrência(s) "
                                  f"além do teto de {self.catchup_max}")
        self.alertas.emitir(EventoFalha(
            job_id=d.job_id,
            occurrence_id=f"{d.job_id}@{quando.isoformat()}",
            capability=d.capacidade, error_class=estado.error_class,
            effect_state=estado.effect_state, detalhe=estado.mensagem,
            timestamp=self._agora()))

    def _executar_ocorrencia(self, d: JobDefinition, quando: datetime,
                             agora: datetime):
        """Uma ocorrência: autoridade FRESCA, reserva, execução, finalização."""
        inst = JobInstance(job_id=d.job_id, ocorrencia=quando.isoformat())

        # AUTORIZAÇÃO POR OCORRÊNCIA — nada guardado do momento da criação.
        credencial = None
        if self.autorizador is not None:
            try:
                credencial = self.autorizador(d, inst)
            except Exception as exc:
                self._auditar("ticker.autorizacao.falhou", job=d.job_id,
                              ocorrencia=inst.ocorrencia,
                              erro=type(exc).__name__)
                self._alertar_fato(d, inst, negado=True,
                                   classe=type(exc).__name__, detalhe=str(exc))
                return self.scheduler.negar_ocorrencia(
                    d, inst, agora, f"autorizador falhou: {type(exc).__name__}")
            if credencial is None:
                self._auditar("ticker.autorizacao.negada", job=d.job_id,
                              ocorrencia=inst.ocorrencia)
                self._alertar_fato(d, inst, negado=True,
                                   classe="AutorizacaoNegada",
                                   detalhe="autorizador recusou a ocorrência")
                return self.scheduler.negar_ocorrencia(
                    d, inst, agora, "autorizador recusou a ocorrência")

        execucao = self.scheduler.executar_ocorrencia(d, inst, agora,
                                                      credencial=credencial)
        if execucao.estado_final is JobState.FAILED:
            # O ticker NÃO adivinha o efeito: informa que houve exceção e
            # deixa a fonte única classificar. Antes ele mandava "NO_EFFECT"
            # quando `efeito_aplicado` era False — mas execução que levantou
            # tem efeito DESCONHECIDO, não ausente. Era essa a origem da
            # contradição com o Scheduler.
            self._alertar_fato(d, inst, negado=False, classe="ExecucaoFalhou",
                               detalhe=execucao.detalhe)
        return execucao

    # ---------------------------------------------------------------- util

    def _auditar(self, evento: str, **campos) -> None:
        if self.audit is not None:
            self.audit.append(evento, **campos)

    def _alertar_fato(self, d: JobDefinition, inst: JobInstance, *,
                      negado: bool, classe: str, detalhe: str) -> None:
        """Relata o FATO; quem classifica é `adapters.resultado`.

        A assinatura só aceita fatos observáveis (foi negado? qual a classe do
        erro?) — não existe parâmetro para o chamador declarar `effect_state`.
        É o que impede a contradição de voltar: os dois emissores mandam a
        mesma pergunta para o mesmo juiz.
        """
        if self.alertas is None:
            return
        from nomos.adapters.resultado import de_execucao
        estado = de_execucao(houve_excecao=not negado, efeito_aplicado=False,
                             negado=negado, error_class=classe,
                             detalhe=detalhe or "")
        if not estado.alerta:
            return
        self.alertas.emitir(EventoFalha(
            job_id=d.job_id, occurrence_id=inst.chave, capability=d.capacidade,
            error_class=estado.error_class or classe,
            effect_state=estado.effect_state, detalhe=estado.mensagem,
            timestamp=self._agora()))
