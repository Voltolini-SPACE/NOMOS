"""NOMOS orquestracao.grafo — grafo de tarefas governado + orquestrador (NH-002).

O que o NOMOS não tinha: um motor que pega tarefas com dependências e as
conduz com decisão de política em CADA passo. Regras:

- validação estrutural fail-closed na construção (id duplicado, dependência
  desconhecida, ciclo, ferramenta fora do registro ⇒ ErroGrafo, nada executa);
- cada nó passa por `policy.decide()` + `policy.gate()` ANTES de executar —
  o MESMO gate do kernel, nenhuma autorização nova;
- DENY/negação não executa o nó e BLOQUEIA os dependentes transitivos;
- falha de executor ⇒ nó FALHOU e dependentes BLOQUEADOS; ramos independentes
  seguem (falha não é desculpa para abandonar o que ainda é seguro fazer);
- missão só é `ok=True` com todos os nós OK; cada transição é auditada.

A recuperação (retry/backoff/circuit-breaker) é plugável via `recuperacao`
(NH-004); o roteamento de motores via `rotear_motor` (NH-007).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from nomos.kernel.policy import gate
from nomos.orquestracao.registro import RegistroCapacidades

_ID_MAX = 64
STATUS_VALIDOS = ("OK", "NEGADO", "BLOQUEADO", "FALHOU", "PENDENTE")


class ErroGrafo(ValueError):
    """Grafo estruturalmente inválido — nada foi executado."""


@dataclass(frozen=True)
class No:
    id: str
    ferramenta: str
    params: dict = field(default_factory=dict)
    depende_de: tuple[str, ...] = ()
    motor: str = ""            # "" = sem LLM; "auto" = rotear via engine_router
    idempotente: bool = False  # só nós idempotentes podem sofrer retry (NH-004)
    alvo: str = ""             # contexto do target na decisão de política


@dataclass
class ResultadoNo:
    status: str = "PENDENTE"
    resultado: object = None
    detalhe: str = ""
    tentativas: int = 0


@dataclass
class ResultadoMissao:
    ok: bool
    nos: dict[str, ResultadoNo]
    ordem: tuple[str, ...]


class GrafoTarefas:
    """Constrói e valida (fail-closed). A construção NUNCA executa nada."""

    def __init__(self, nos: list[No], registro: RegistroCapacidades):
        vistos: dict[str, No] = {}
        for no in nos:
            if not no.id or not isinstance(no.id, str) or len(no.id) > _ID_MAX:
                raise ErroGrafo(f"id de nó inválido: {no.id!r}")
            if no.id in vistos:
                raise ErroGrafo(f"id duplicado: {no.id}")
            vistos[no.id] = no
        for no in nos:
            for dep in no.depende_de:
                if dep == no.id:
                    raise ErroGrafo(f"nó '{no.id}' depende de si mesmo")
                if dep not in vistos:
                    raise ErroGrafo(f"nó '{no.id}' depende de desconhecido '{dep}'")
            if not registro.conhecida(no.ferramenta):
                raise ErroGrafo(
                    f"nó '{no.id}': ferramenta fora do registro: '{no.ferramenta}'")
            # ABSORPTION-01: idempotência é atributo da CAPACIDADE (registro),
            # nunca do nó. `planejar()` já deriva do registro, mas um grafo
            # montado à mão (sem passar pelo planejador) podia declarar
            # `idempotente=True` numa capacidade mutante e ganhar retry —
            # transformando 1 aprovação em N efeitos reais. Reivindicar MAIS
            # do que a capacidade tem é erro estrutural: nada executa.
            # Reivindicar MENOS (False onde o registro diz True) é
            # conservador e permitido.
            if no.idempotente and not registro.idempotente_de(no.ferramenta):
                raise ErroGrafo(
                    f"nó '{no.id}': declara idempotente=True, mas a capacidade "
                    f"'{no.ferramenta}' não é idempotente no registro "
                    "(plano não define o próprio risco)")
        self.nos = vistos
        self.registro = registro
        self._ordem = self._topologica()

    def _topologica(self) -> tuple[str, ...]:
        """Kahn; sobra nó com grau > 0 ⇒ ciclo ⇒ ErroGrafo."""
        grau = {i: len(n.depende_de) for i, n in self.nos.items()}
        dependentes: dict[str, list[str]] = {i: [] for i in self.nos}
        for i, n in self.nos.items():
            for dep in n.depende_de:
                dependentes[dep].append(i)
        fila = sorted(i for i, g in grau.items() if g == 0)
        ordem: list[str] = []
        while fila:
            atual = fila.pop(0)
            ordem.append(atual)
            for filho in sorted(dependentes[atual]):
                grau[filho] -= 1
                if grau[filho] == 0:
                    fila.append(filho)
        if len(ordem) != len(self.nos):
            presos = sorted(set(self.nos) - set(ordem))
            raise ErroGrafo(f"ciclo de dependências envolvendo: {', '.join(presos)}")
        return tuple(ordem)

    def ordem_topologica(self) -> tuple[str, ...]:
        return self._ordem

    def dependentes_transitivos(self, raiz: str) -> set[str]:
        diretos: dict[str, list[str]] = {i: [] for i in self.nos}
        for i, n in self.nos.items():
            for dep in n.depende_de:
                diretos[dep].append(i)
        alcancados: set[str] = set()
        fila = list(diretos[raiz])
        while fila:
            atual = fila.pop()
            if atual in alcancados:
                continue
            alcancados.add(atual)
            fila.extend(diretos[atual])
        return alcancados


class Orquestrador:
    """Executa o grafo em ordem topológica com o gate do kernel em cada nó.

    `executores` é o wiring explícito para ferramentas nativas (como o CLI
    faz com `agents/execucao`); dinâmicas usam o executor do registro.
    `recuperacao` (NH-004) e `rotear_motor` (NH-007) são plugáveis.
    """

    def __init__(self, registro: RegistroCapacidades, policy, approver=None,
                 audit=None, executores: dict[str, Callable] | None = None,
                 recuperacao=None, rotear_motor: Callable | None = None,
                 estrito: bool = False, contexto_aprovacao=None):
        self.registro = registro
        self.policy = policy
        self.approver = approver
        self.audit = audit
        self.executores = dict(executores or {})
        self.recuperacao = recuperacao
        self.rotear_motor = rotear_motor
        # ABSORPTION-06: modo ESTRITO desliga o fallback para
        # `registro.executor_de()`. Quem opera sob PEP (o RuntimeGovernado)
        # entrega o mapa protegido inteiro; qualquer capacidade fora dele é,
        # por definição, um caminho não governado. Sem isto, registrar uma
        # capacidade mutante direto no registro a torna executável CRUA — foi
        # o que o invariante da ETAPA 2 encontrou ainda aberto depois da
        # correção pontual da ABSORPTION-05.
        self.estrito = bool(estrito)
        # P1: o que o humano precisa VER e o que o digest precisa COBRIR.
        # `contexto_aprovacao()` devolve (sujeito, escopo_dados, escopo_controle,
        # registro_de_aprovacoes). Sem ele o gate continua sendo o do kernel,
        # mas sem vínculo criptográfico — modo herdado, usado pelos callers que
        # não passam pelo RuntimeGovernado.
        self.contexto_aprovacao = contexto_aprovacao

    def _auditar(self, evento: str, **campos) -> None:
        if self.audit is not None:
            self.audit.append(evento, **campos)

    def _registro_aprovacoes(self):
        return self.contexto_aprovacao()[3]

    def _operacao(self, no: No, no_id: str, categoria):
        """A operação EFETIVA, montada dos mesmos dados que vão executar.

        Montada duas vezes de propósito — antes de perguntar ao humano e de
        novo antes do efeito. Se as duas divergirem, alguma coisa mudou no
        meio, e é exatamente isso que precisa ser recusado.
        """
        if self.contexto_aprovacao is None:
            return None
        from nomos.pdp.aprovacao import OperacaoAprovavel, versao_da_politica
        sujeito, dados, controle, _reg = self.contexto_aprovacao()
        params = dict(no.params)
        recurso = str(params.get("alvo", "") or params.get("alvo_job", "")
                      or params.get("cwd", "") or "")
        return OperacaoAprovavel(
            sujeito=sujeito, capacidade=no.ferramenta, recurso=recurso,
            classe_de_risco=getattr(categoria, "value", str(categoria)),
            argumentos=params, escopo_dados=tuple(dados),
            escopo_controle=tuple(controle),
            versao_da_politica=versao_da_politica(self.policy),
            digest_do_plano=no_id)

    def _gate_vinculado(self, decisao, operacao) -> bool:
        """Gate do kernel + registro da aprovação para ESTE digest."""
        if not gate(decisao, self.approver):
            return False
        if operacao is None:
            return True
        from nomos.kernel.policy import Effect
        if decisao.effect is Effect.ALLOW:
            return True                 # ALLOW não consulta humano
        self._registro_aprovacoes().conceder(operacao)
        return True

    def _executor_para(self, no: No) -> Callable | None:
        if no.ferramenta in self.executores:
            return self.executores[no.ferramenta]
        if self.estrito:
            return None          # sem ponte crua: fora do mapa ⇒ não executa
        return self.registro.executor_de(no.ferramenta)

    def _bloquear_dependentes(self, grafo: GrafoTarefas, raiz: str,
                              nos: dict[str, ResultadoNo]) -> None:
        for dep_id in grafo.dependentes_transitivos(raiz):
            if nos[dep_id].status == "PENDENTE":
                nos[dep_id] = ResultadoNo(
                    status="BLOQUEADO",
                    detalhe=f"dependência '{raiz}' não concluiu")
                self._auditar("orquestracao.no.bloqueado", no=dep_id, causa=raiz)

    def executar(self, grafo: GrafoTarefas) -> ResultadoMissao:
        nos: dict[str, ResultadoNo] = {i: ResultadoNo() for i in grafo.nos}
        self._auditar("orquestracao.missao.inicio",
                      nos=len(nos), ordem=",".join(grafo.ordem_topologica()))
        for no_id in grafo.ordem_topologica():
            if nos[no_id].status != "PENDENTE":
                continue                      # já bloqueado por dependência
            no = grafo.nos[no_id]
            categoria = self.registro.categoria_de(no.ferramenta)
            if categoria is None:
                nos[no_id] = ResultadoNo(status="NEGADO",
                                         detalhe="capacidade desconhecida")
                self._auditar("orquestracao.no.negado", no=no_id,
                              ferramenta=no.ferramenta, motivo="desconhecida")
                self._bloquear_dependentes(grafo, no_id, nos)
                continue
            # P1 — APROVAÇÃO NÃO-CEGA.
            # `target` era `orquestracao:{id}:{ferramenta}:{alvo}` com `alvo`
            # SEMPRE vazio — `No.alvo` não tinha nenhum escritor. O prompt de
            # um plano benigno e o de um plano que exfiltrava chave privada
            # eram byte-idênticos, variando só pelo id do nó, que o autor do
            # plano escolhe. Agora o operador lê os campos REAIS, e o digest
            # deles é recalculado imediatamente antes do efeito.
            operacao = self._operacao(no, no_id, categoria)
            decisao = self.policy.decide(
                categoria,
                target=(operacao.descrever() if operacao is not None
                        else f"orquestracao:{no_id}:{no.ferramenta}:{no.alvo}"))
            if not self._gate_vinculado(decisao, operacao):
                nos[no_id] = ResultadoNo(status="NEGADO", detalhe=decisao.reason)
                self._auditar("orquestracao.no.negado", no=no_id,
                              ferramenta=no.ferramenta,
                              categoria=categoria.value, motivo=decisao.reason)
                self._bloquear_dependentes(grafo, no_id, nos)
                continue
            executor = self._executor_para(no)
            if executor is None:
                nos[no_id] = ResultadoNo(
                    status="FALHOU",
                    detalhe=(f"sem executor governado para '{no.ferramenta}' "
                             "(modo estrito: capacidade fora do mapa protegido "
                             "por PEP não executa)") if self.estrito else
                            (f"sem executor para '{no.ferramenta}' "
                             "(nativas exigem wiring explícito)"))
                self._auditar("orquestracao.no.falhou", no=no_id,
                              ferramenta=no.ferramenta, motivo="sem executor")
                self._bloquear_dependentes(grafo, no_id, nos)
                continue
            params = dict(no.params)
            # RECÁLCULO imediatamente antes do efeito: entre o "APROVO" e esta
            # linha, nada pode ter mudado alvo, argumento, capacidade, sujeito,
            # escopo ou política. Se mudou, o digest não bate e nada executa.
            from nomos.kernel.policy import Effect as _Ef
            if operacao is not None and decisao.effect is not _Ef.ALLOW:
                try:
                    self._registro_aprovacoes().consumir(
                        self._operacao(no, no_id, categoria))
                except Exception as exc:
                    nos[no_id] = ResultadoNo(status="NEGADO", detalhe=str(exc))
                    self._auditar("orquestracao.no.negado", no=no_id,
                                  ferramenta=no.ferramenta,
                                  motivo="aprovacao_divergente")
                    self._bloquear_dependentes(grafo, no_id, nos)
                    continue
            if no.motor == "auto" and self.rotear_motor is not None:
                rota = self.rotear_motor(no)
                params["rota_motor"] = rota
                self._auditar("orquestracao.no.rota_motor", no=no_id,
                              **_resumo_rota(rota))
            ok, resultado, tentativas = self._rodar(no, executor, params)
            if ok:
                nos[no_id] = ResultadoNo(status="OK", resultado=resultado,
                                         tentativas=tentativas)
                self._auditar("orquestracao.no.ok", no=no_id,
                              ferramenta=no.ferramenta, tentativas=tentativas)
            else:
                nos[no_id] = ResultadoNo(status="FALHOU", detalhe=str(resultado),
                                         tentativas=tentativas)
                self._auditar("orquestracao.no.falhou", no=no_id,
                              ferramenta=no.ferramenta, motivo=str(resultado),
                              tentativas=tentativas)
                self._bloquear_dependentes(grafo, no_id, nos)
        ok_geral = all(r.status == "OK" for r in nos.values())
        self._auditar("orquestracao.missao.fim", ok=ok_geral)
        return ResultadoMissao(ok=ok_geral, nos=nos,
                               ordem=grafo.ordem_topologica())

    def _rodar(self, no: No, executor: Callable, params: dict):
        """(ok, resultado|motivo, tentativas). Com NH-004 plugado, delega.

        A idempotência entregue à recuperação vem SEMPRE do registro
        (ABSORPTION-01), nunca de `no.idempotente` — defesa em profundidade:
        mesmo que um grafo chegasse aqui sem a validação de `GrafoTarefas`,
        o nó não consegue comprar o próprio direito de retry.
        """
        if self.recuperacao is not None:
            return self.recuperacao.executar(
                no, executor, params,
                idempotente=self.registro.idempotente_de(no.ferramenta))
        try:
            return True, executor(**params), 1
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}", 1


def _resumo_rota(rota) -> dict:
    """Campos auditáveis da decisão de rota (nunca o conteúdo da tarefa)."""
    try:
        return {"motor": getattr(rota, "selected_engine", None) or "nenhum",
                "fallback": getattr(rota, "fallback_engine", None) or "nenhum",
                "local_preservado": getattr(rota, "local_only_preserved", True)}
    except Exception:                                    # rota opaca: não quebrar audit
        return {"motor": "desconhecido", "fallback": "desconhecido",
                "local_preservado": True}
