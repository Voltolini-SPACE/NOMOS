"""NOMOS cognition.engine_pipeline — junção de motores em etapas, com política.

Um pipeline é uma sequência de PipelineStep. Regras invioláveis:
- CADA etapa passa pela política (gate) antes de executar — nada "pula" aprovação;
- a primeira etapa negada ou com erro PARA o pipeline (falha honesta, sem
  resultado parcial fingindo sucesso);
- a auditoria guarda decisão e metadados (motor, categoria, rc) — NUNCA o
  conteúdo processado;
- o resultado carrega uma explicação simples para o usuário.

Exemplo: transcrever áudio (whisper local) → resumir (texto local) → guardar
na memória local. Se o usuário está em modo só-local, nada disso sai da máquina.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from nomos.kernel.policy import Category, Decision, Effect, gate as _gate


@dataclass(frozen=True)
class PipelineStep:
    nome: str                        # "transcrever", "resumir", "memorizar"...
    motor_id: str                    # motor do catálogo que executa a etapa
    categoria: Category | str = Category.READ_LOCAL   # categoria de política
    executar: Callable | None = None # fn(entrada) -> saida; None = passthrough
    local: bool = True


@dataclass
class PipelineAudit:
    """Coletor de eventos de auditoria — metadados apenas, nunca conteúdo."""
    eventos: list[dict] = field(default_factory=list)
    audit_log: object = None

    def registrar(self, evento: str, **meta):
        proibidas = {"conteudo", "content", "texto", "text", "entrada", "saida"}
        meta = {k: v for k, v in meta.items() if k not in proibidas}
        self.eventos.append({"evento": evento, **meta})
        if self.audit_log is None:
            return
        try:
            # Horizonte 3/item 3: `audit_log: object` é proposital (duck
            # typing deliberado — este módulo não quer acoplamento com o
            # tipo concreto AuditLog). O try/except abaixo já existe
            # exatamente para tolerar um objeto que não tenha .append (ou
            # que falhe por qualquer outro motivo); um Protocol tornaria a
            # garantia mais forte do que o código realmente promete, e um
            # assert quebraria o próprio propósito do except. A supressão
            # abaixo documenta a lacuna real para o mypy, sem fingir uma
            # garantia que não existe — comportamento em runtime inalterado.
            self.audit_log.append(f"pipeline.{evento}", **meta)  # type: ignore[attr-defined]
        except Exception:
            # auditoria externa indisponível não derruba o pipeline; o coletor
            # local (self.eventos) preserva o rastro da decisão
            self.eventos.append({"evento": "auditoria_externa_indisponivel"})


@dataclass(frozen=True)
class PipelineResult:
    ok: bool
    etapas_executadas: tuple
    etapa_falhou: str | None
    motivo: str
    saida: object = None
    explicacao: str = ""


class EnginePipeline:
    def __init__(self, steps: list[PipelineStep], policy, approver,
                 audit=None, home=None):
        self.steps = list(steps)
        self.policy = policy
        self.approver = approver
        self.audit = PipelineAudit()
        self.audit.audit_log = audit
        self.home = home

    def _explicacao(self, executadas: list[str], tudo_local: bool) -> str:
        if not executadas:
            return "nenhuma etapa foi executada."
        resumo = " → ".join(executadas)
        priv = ("Nada saiu da sua máquina." if tudo_local
                else "Uma etapa usou a nuvem, com sua permissão explícita.")
        return f"Usei: {resumo}. {priv}"

    def run(self, entrada=None) -> PipelineResult:
        executadas: list[str] = []
        tudo_local = True
        valor = entrada
        for step in self.steps:
            cat = step.categoria if isinstance(step.categoria, Category) \
                else str(step.categoria)
            decision: Decision = self.policy.decide(cat, target=f"pipeline:{step.nome}")
            self.audit.registrar("etapa.decidida", etapa=step.nome,
                                 motor=step.motor_id,
                                 categoria=str(getattr(cat, "value", cat)),
                                 efeito=decision.effect.value)
            if decision.effect is not Effect.ALLOW and not _gate(decision, self.approver):
                self.audit.registrar("etapa.negada", etapa=step.nome,
                                     motor=step.motor_id,
                                     motivo=decision.reason)
                return PipelineResult(
                    False, tuple(executadas), step.nome,
                    f"etapa '{step.nome}' negada: {decision.reason}",
                    saida=None,
                    explicacao=(f"Parei na etapa '{step.nome}' porque a permissão "
                                f"foi negada. Nada além do já aprovado aconteceu."))
            if decision.effect is Effect.ALLOW:
                # ALLOW puro também passa pelo gate (contrato único)
                if not _gate(decision, self.approver):
                    return PipelineResult(False, tuple(executadas), step.nome,
                                          "gate recusou etapa permitida (inconsistência)",
                                          explicacao="parei por segurança.")
            tudo_local = tudo_local and step.local
            try:
                if step.executar is not None:
                    valor = step.executar(valor)
            except Exception as exc:
                self.audit.registrar("etapa.falhou", etapa=step.nome,
                                     motor=step.motor_id, erro=type(exc).__name__)
                return PipelineResult(
                    False, tuple(executadas), step.nome,
                    f"etapa '{step.nome}' falhou: {type(exc).__name__}",
                    saida=None,
                    explicacao=(f"A etapa '{step.nome}' deu erro; interrompi o "
                                "resto para não entregar resultado pela metade."))
            executadas.append(f"{step.nome} ({step.motor_id}"
                              f"{', local' if step.local else ', NUVEM'})")
            self.audit.registrar("etapa.concluida", etapa=step.nome,
                                 motor=step.motor_id)
        self.audit.registrar("concluido", etapas=len(executadas))
        return PipelineResult(True, tuple(executadas), None, "pipeline concluído",
                              saida=valor,
                              explicacao=self._explicacao(executadas, tudo_local))

    def run_parallel(self, entrada=None) -> PipelineResult:
        """Etapas INDEPENDENTES em paralelo (v0.18) — gates primeiro, sempre.

        1) todos os gates são decididos em sequência, fail-closed: UMA negação
           aborta o lote inteiro ANTES de qualquer execução (nada parcial);
        2) só então as etapas executam em threads, cada uma sobre a MESMA
           entrada (por isso 'independentes');
        3) qualquer exceção => resultado falho honesto, com as demais saídas
           descartadas.
        """
        for step in self.steps:
            cat = step.categoria if isinstance(step.categoria, Category) \
                else str(step.categoria)
            decision = self.policy.decide(cat, target=f"pipeline:{step.nome}")
            self.audit.registrar("etapa.decidida", etapa=step.nome,
                                 motor=step.motor_id,
                                 categoria=str(getattr(cat, "value", cat)),
                                 efeito=decision.effect.value, paralelo=True)
            if not _gate(decision, self.approver):
                self.audit.registrar("etapa.negada", etapa=step.nome,
                                     motor=step.motor_id, motivo=decision.reason)
                return PipelineResult(
                    False, (), step.nome,
                    f"etapa '{step.nome}' negada antes do lote paralelo: "
                    f"{decision.reason}",
                    explicacao=("Nada executou: no modo paralelo, uma negação "
                                "cancela o lote inteiro antes de começar."))

        import concurrent.futures as cf
        resultados: dict[str, object] = {}
        erro: list[tuple[str, str]] = []
        with cf.ThreadPoolExecutor(max_workers=min(4, len(self.steps) or 1)) as ex:
            futuros = {ex.submit(s.executar or (lambda x: x), entrada): s
                       for s in self.steps}
            for fut in cf.as_completed(futuros):
                s = futuros[fut]
                try:
                    resultados[s.nome] = fut.result()
                    self.audit.registrar("etapa.concluida", etapa=s.nome,
                                         motor=s.motor_id, paralelo=True)
                except Exception as exc:
                    erro.append((s.nome, type(exc).__name__))
                    self.audit.registrar("etapa.falhou", etapa=s.nome,
                                         motor=s.motor_id,
                                         erro=type(exc).__name__, paralelo=True)
        if erro:
            nome_falha, tipo = erro[0]
            return PipelineResult(False, tuple(sorted(resultados)), nome_falha,
                                  f"etapa '{nome_falha}' falhou: {tipo}",
                                  explicacao="Uma etapa paralela falhou; "
                                             "descartei o lote para não entregar "
                                             "resultado pela metade.")
        executadas = [f"{s.nome} ({s.motor_id}{', local' if s.local else ', NUVEM'})"
                      for s in self.steps]
        tudo_local = all(s.local for s in self.steps)
        self.audit.registrar("concluido", etapas=len(executadas), paralelo=True)
        return PipelineResult(True, tuple(executadas), None,
                              "lote paralelo concluído", saida=resultados,
                              explicacao=self._explicacao(executadas, tudo_local))
