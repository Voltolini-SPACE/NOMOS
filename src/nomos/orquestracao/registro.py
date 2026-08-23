"""NOMOS orquestracao.registro — registro dinâmico governado de capacidades (NH-001).

A allowlist de 8 ferramentas do manifesto (`agents.manifest.FERRAMENTAS`)
continua sendo a base imutável ("nativas"). Este módulo adiciona o que o
modelo fechado não permitia — registrar capacidades novas em runtime — sem
abrir mão do espírito fail-closed:

- registrar é ato sensível (A5_SKILL_INSTALL) e passa pelo MESMO `policy.gate`
  do kernel; sem política ou sem aprovador => negado;
- capacidade desconhecida => categoria None / risco A6 (pior caso);
- nativa não pode ser sombreada nem removida (anti-hijack);
- nativas não ganham executor implícito: execução delas continua no wiring
  explícito (`agents/execucao`); o registro responde identidade + categoria;
- toda mutação do registro é auditada.

O registro vive em memória por processo. Persistência exigiria assinatura de
capacidade (fora do escopo NH-001; ver docs/missions da missão NH).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from nomos.agents.manifest import FERRAMENTAS, NOME_RE
from nomos.kernel.policy import Category, gate


class ErroRegistro(ValueError):
    """Registro negado ou inválido — sempre fail-closed."""


@dataclass(frozen=True)
class Capacidade:
    nome: str
    categoria: Category
    executor: Callable | None
    origem: str
    nativa: bool
    idempotente: bool = False   # repetir é seguro? default conservador


def _risco(categoria: Category | None) -> str:
    """Nível A0–A6 da categoria; desconhecida => A6 (pior caso)."""
    if categoria is None:
        return "A6"
    return categoria.value.split("_")[0]


class RegistroCapacidades:
    """Fonte única de verdade sobre QUAIS capacidades existem e QUAL risco têm."""

    def __init__(self, policy=None, approver=None, audit=None, concessoes=None,
                 escopo_dados: tuple = ()):
        self.policy = policy
        self.approver = approver
        self.audit = audit
        # `concessoes` (kernel.concessoes.RegistroConcessoes) é OPCIONAL: com
        # None o comportamento é byte-idêntico ao anterior — toda autorização
        # vem do gate ao vivo. Ver `_autorizar`.
        self.concessoes = concessoes
        # As RAÍZES autorizadas. Entram no digest: a CLI imprime
        # "raízes: <...>" para o dono ler antes de aprovar, e sem isto o digest
        # de um registro confinado a ~/dados era BYTE-IDÊNTICO ao de um com
        # raizes=("/",). A concessão dada lendo uma coisa valia para a outra —
        # exatamente o "a UI mostra A e o sistema assina B" que
        # `pdp/aprovacao.py` existe para impedir.
        self.escopo_dados = tuple(escopo_dados or ())
        self._dinamicas: dict[str, Capacidade] = {}

    # ---------- consulta (nunca levanta; desconhecida => fail-closed) ----------

    def conhecida(self, nome: str) -> bool:
        return nome in FERRAMENTAS or nome in self._dinamicas

    def categoria_de(self, nome: str) -> Category | None:
        if nome in FERRAMENTAS:
            return FERRAMENTAS[nome]
        cap = self._dinamicas.get(nome)
        return cap.categoria if cap else None

    def risco_de(self, nome: str) -> str:
        return _risco(self.categoria_de(nome))

    def idempotente_de(self, nome: str) -> bool:
        """Repetir esta capacidade é seguro? Propriedade da CAPACIDADE, nunca
        do plano — é o que autoriza retry (NH-004).

        Nativas: derivado da categoria — A0 (leitura local) é seguro repetir
        por definição (não muta nada); qualquer outra ⇒ False. Dinâmicas:
        só o que foi declarado no registro. Desconhecida ⇒ False (repetir
        efeito colateral às cegas é pior que falhar)."""
        if nome in FERRAMENTAS:
            return FERRAMENTAS[nome] is Category.READ_LOCAL
        cap = self._dinamicas.get(nome)
        return bool(cap.idempotente) if cap else False

    def executor_de(self, nome: str) -> Callable | None:
        """Executor de capacidade DINÂMICA. Nativas devolvem None de propósito:
        a execução delas continua no wiring explícito (`agents/execucao`)."""
        cap = self._dinamicas.get(nome)
        return cap.executor if cap else None

    def listar(self) -> dict[str, dict]:
        saida: dict[str, dict] = {}
        for nome, categoria in FERRAMENTAS.items():
            saida[nome] = {"categoria": categoria.value, "risco": _risco(categoria),
                           "origem": "manifesto", "nativa": True}
        for nome, cap in self._dinamicas.items():
            saida[nome] = {"categoria": cap.categoria.value, "risco": _risco(cap.categoria),
                           "origem": cap.origem, "nativa": False}
        return saida

    # ---------- mutação (governada, auditada) ----------

    def _negar(self, nome: str, motivo: str) -> ErroRegistro:
        """A negação já é o resultado seguro; audit que falha não pode
        transformá-la noutra exceção — mas também não é engolida em silêncio:
        vai anexada ao motivo."""
        extra = ""
        if self.audit is not None:
            try:
                self.audit.append("registro.capacidade.negada", capacidade=nome,
                                  motivo=motivo)
            except Exception as exc:
                extra = f" (audit indisponível: {type(exc).__name__})"
        return ErroRegistro(f"registro de '{nome}' negado: {motivo}{extra}")

    def operacao_de_registro(self, nome: str, categoria: Category,
                             origem: str, idempotente: bool):
        """A operação que o humano lê e que o digest cobre.

        Fica aqui — e não na CLI — para que o digest CONCEDIDO e o digest
        CONSULTADO nasçam do mesmo código. Se divergirem, o dono aprova A e o
        sistema consulta B: exatamente o defeito que `pdp/aprovacao.py` existe
        para fechar (ver `descrever()` lá).
        """
        from nomos.pdp.aprovacao import OperacaoAprovavel, versao_da_politica
        return OperacaoAprovavel(
            sujeito="registro",
            capacidade=nome,
            recurso=f"registro:{nome}",
            classe_de_risco=categoria.value,
            argumentos={"origem": origem, "idempotente": bool(idempotente)},
            escopo_dados=self.escopo_dados,
            versao_da_politica=versao_da_politica(self.policy),
        )

    def operacao_registrada(self, nome: str):
        """A operação de uma capacidade JÁ registrada nesta instância.

        Existe para que quem CONCEDE (a CLI) não precise adivinhar categoria e
        origem: elas vêm do wiring que registrou, fonte única. Adivinhar aqui
        produziria um digest que nunca casa com o consultado no registrar().
        """
        cap = self._dinamicas.get(nome)
        if cap is None:
            raise self._negar(nome, "não é capacidade dinâmica desta instância")
        return self.operacao_de_registro(cap.nome, cap.categoria, cap.origem,
                                         cap.idempotente)

    def _autorizar(self, decisao, nome: str, categoria: Category,
                   origem: str, idempotente: bool) -> bool:
        """Gate ao vivo OU concessão durável — nesta ordem de prioridade.

        Invariantes que esta função NÃO pode quebrar:
        - DENY continua DENY. Concessão jamais converte proibição em permissão:
          só se consulta concessão quando o efeito é REQUIRE_APPROVAL.
        - ALLOW não consulta nada (o gate já devolve True sem aprovador).
        - Sem `concessoes` configurado, o caminho é o antigo, intocado.
        - Consumir concessão é auditado como USO (`registro.concessao.consumida`),
          nunca como uma nova decisão humana — a trilha não pode fabricar
          aprovações que ninguém deu.
        """
        from nomos.kernel.policy import Effect
        if self.concessoes is not None and decisao.effect is Effect.REQUIRE_APPROVAL:
            try:
                op = self.operacao_de_registro(nome, categoria, origem, idempotente)
                if self.concessoes.vigente(op.digest()):
                    if self.audit is not None:
                        self.audit.append("registro.concessao.consumida",
                                          capacidade=nome,
                                          digest=op.digest()[:16],
                                          origem=origem)
                    return True
            except Exception:  # noqa: S110 — concessão indisponível NUNCA
                pass           # autoriza: cai no gate logo abaixo, fail-closed.
        return gate(decisao, self.approver)

    def registrar(self, nome: str, categoria: Category | str,
                  executor: Callable, origem: str,
                  idempotente: bool = False) -> Capacidade:
        if not isinstance(nome, str) or not NOME_RE.match(nome or ""):
            raise self._negar(str(nome), "nome inválido (minúsculas, dígitos e hífen; 2–32)")
        if nome in FERRAMENTAS:
            raise self._negar(nome, "sombrear ferramenta nativa é proibido")
        if nome in self._dinamicas:
            raise self._negar(nome, "capacidade já registrada (remova antes)")
        if not isinstance(categoria, Category):
            try:
                categoria = Category(str(categoria))
            except ValueError:
                raise self._negar(nome, f"categoria desconhecida: {categoria!r}") from None
        if not callable(executor):
            raise self._negar(nome, "executor precisa ser chamável")
        if not origem or not isinstance(origem, str):
            raise self._negar(nome, "origem obrigatória")
        if self.policy is None:
            raise self._negar(nome, "sem política carregada — fail-closed")
        decisao = self.policy.decide(Category.SKILL_INSTALL, target=f"registro:{nome}")
        if not self._autorizar(decisao, nome, categoria, origem, idempotente):
            raise self._negar(nome, f"gate negou ({decisao.reason})")
        cap = Capacidade(nome=nome, categoria=categoria, executor=executor,
                         origem=origem, nativa=False,
                         idempotente=bool(idempotente))
        # auditar ANTES de mutar: se não dá para registrar a trilha, não se
        # registra a capacidade (senão sobraria capacidade ativa e invisível)
        if self.audit is not None:
            try:
                self.audit.append("registro.capacidade.registrada", capacidade=nome,
                                  categoria=categoria.value, origem=origem,
                                  idempotente=bool(idempotente))
            except Exception as exc:
                raise ErroRegistro(
                    f"registro de '{nome}' negado: audit indisponível "
                    f"({type(exc).__name__})") from None
        self._dinamicas[nome] = cap
        return cap

    def desregistrar(self, nome: str) -> None:
        if nome in FERRAMENTAS:
            raise self._negar(nome, "remover ferramenta nativa é proibido")
        if nome not in self._dinamicas:
            raise self._negar(nome, "capacidade desconhecida")
        # Revogar REDUZ autoridade: a direção segura da falha é remover.
        # Por isso, ao contrário de registrar(), aqui a remoção acontece
        # mesmo se o audit falhar — mas o chamador é avisado (a trilha ficou
        # incompleta), nunca enganado.
        del self._dinamicas[nome]
        if self.audit is not None:
            try:
                self.audit.append("registro.capacidade.removida", capacidade=nome)
            except Exception as exc:
                raise ErroRegistro(
                    f"'{nome}' foi REMOVIDA, mas o audit falhou "
                    f"({type(exc).__name__}): trilha incompleta") from None
