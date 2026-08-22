"""NOMOS runtime.inferencia — provedores de inferência (ABSORPTION-02 / FASE 4).

O runtime governado não pode depender estruturalmente de UM backend. Aqui fica
a abstração que ele usa; `cognition.providers` continua sendo quem fala HTTP
com cada backend concreto.

**A fronteira de autoridade é a razão de este módulo existir.**

    o modelo PROPÕE · o NOMOS GOVERNA

Um provedor devolve TEXTO. Nada além de texto. Ele não pode:
- atribuir risco (quem atribui é o registro de capacidades);
- declarar idempotência (idem);
- assinar autorização (só `runtime.governado.sessao_pdp`);
- pular o PDP, chamar adapter bruto ou ampliar escopo.

Isso não é promessa de docstring: `sugestao_como_dado()` remove qualquer campo
de autoridade que venha na resposta ANTES de o planejador olhar, e o
planejador já deriva categoria/idempotência do registro. Duas camadas, porque
a saída de um modelo é entrada hostil por definição.

STATUS (2026-08-21): fundação SEM caller de produção, por desenho — o caller
chega com o planejador-LLM (missão futura). Mantido porque a fronteira de
sanitização já está testada (test_absorption02_provider_security.py) e
removê-la agora significaria reauditar tudo ao reintroduzi-la.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable, Protocol, runtime_checkable

# Campos que um modelo pode tentar usar para comprar autoridade. Removidos da
# sugestão antes de qualquer processamento. A lista é CONSERVADORA: na dúvida,
# remova — o planejador só precisa de id/ferramenta/params/depende_de/motor.
CAMPOS_DE_AUTORIDADE = frozenset({
    "categoria", "risco", "risk", "risk_class", "nivel", "level",
    "idempotente", "idempotent", "retry", "retries",
    "aprovado", "approved", "approval", "autorizado", "authorized",
    "skip_pdp", "skip_pep", "bypass", "sem_gate", "no_gate", "force",
    "escopo", "scope", "caminhos", "paths", "capacidades", "capabilities",
    "assinatura", "signature", "token", "autorizacao", "authorization",
    "sujeito", "subject", "audiencia", "audience", "nonce", "jti",
    "policy", "politica", "privilegio", "privilege", "admin", "root",
})

CAMPOS_ACEITOS = frozenset({"id", "ferramenta", "params", "depende_de", "motor"})


class InferenciaIndisponivel(RuntimeError):
    """Nenhum provedor utilizável — o runtime segue governando sem LLM."""


@dataclass(frozen=True)
class RespostaInferencia:
    texto: str
    provedor: str
    modelo: str


@runtime_checkable
class ProvedorInferencia(Protocol):
    """Contrato mínimo. Note o que NÃO existe aqui: nada de política."""

    nome: str

    def disponivel(self) -> bool: ...

    def propor(self, objetivo: str) -> RespostaInferencia: ...


class ProvedorLocal:
    """Backend local (Ollama por padrão). Loopback é validado no provider."""

    nome = "local"

    def __init__(self, provider=None, modelo: str | None = None):
        if provider is None:
            from nomos.cognition.providers import OllamaProvider
            provider = (OllamaProvider(model=modelo) if modelo
                        else OllamaProvider())
        self._p = provider

    def disponivel(self) -> bool:
        try:
            return bool(self._p.available())
        except Exception:
            return False

    def propor(self, objetivo: str) -> RespostaInferencia:
        from nomos.cognition.providers import ProviderUnavailable
        try:
            r = self._p.chat([{"role": "user", "content": objetivo}])
        except ProviderUnavailable as exc:
            raise InferenciaIndisponivel(str(exc)) from None
        except Exception as exc:
            raise InferenciaIndisponivel(
                f"{type(exc).__name__} no provedor local") from None
        return RespostaInferencia(texto=getattr(r, "text", "") or "",
                                  provedor=self.nome,
                                  modelo=getattr(r, "model", "") or "")


class ProvedorTeste:
    """Respostas determinísticas. Não fala rede — usado em teste e em shadow."""

    nome = "teste"

    def __init__(self, respostas: list[str] | Callable[[str], str] | str = ""):
        self._respostas = respostas
        self._i = 0

    def disponivel(self) -> bool:
        return True

    def propor(self, objetivo: str) -> RespostaInferencia:
        r = self._respostas
        if callable(r):
            texto = r(objetivo)
        elif isinstance(r, list):
            texto = r[self._i] if self._i < len(r) else (r[-1] if r else "")
            self._i += 1
        else:
            texto = str(r)
        return RespostaInferencia(texto=texto, provedor=self.nome, modelo="teste")


class ProvedorIndisponivel:
    """Ausência explícita. Existe para que "sem motor" seja um estado nomeado,
    e não um `None` espalhado por condicionais."""

    nome = "nenhum"

    def disponivel(self) -> bool:
        return False

    def propor(self, objetivo: str) -> RespostaInferencia:
        raise InferenciaIndisponivel("nenhum provedor de inferência configurado")


def escolher_provedor(candidatos=None) -> ProvedorInferencia:
    """Primeiro provedor disponível; nenhum ⇒ `ProvedorIndisponivel`.

    Sem exceção e sem fallback silencioso para nuvem: a ausência de motor é um
    resultado legítimo, porque orquestração governada não depende de LLM.
    """
    for p in (candidatos if candidatos is not None else [ProvedorLocal()]):
        try:
            if p.disponivel():
                return p
        except Exception:
            continue
    return ProvedorIndisponivel()


# --------------------------------------------------------- fronteira de autoridade

def _limpar_passo(passo: dict) -> dict:
    """Mantém só os campos que o planejador consome. Tudo o mais cai."""
    return {k: v for k, v in passo.items() if k in CAMPOS_ACEITOS}


def sugestao_como_dado(texto: str) -> list | None:
    """Texto do modelo → lista de passos SEM campos de autoridade.

    Devolve None em qualquer anomalia (fail-closed no chamador). Um passo que
    não seja objeto é descartado; campos de autoridade são removidos mesmo que
    o modelo os aninhe dentro de `params`.
    """
    try:
        dados = json.loads(texto)
    except (TypeError, ValueError):
        return None
    if not isinstance(dados, list):
        return None
    limpos = []
    for passo in dados:
        if not isinstance(passo, dict):
            continue
        p = _limpar_passo(passo)
        params = p.get("params")
        if isinstance(params, dict):
            # autoridade escondida dentro de params também não passa
            p["params"] = {k: v for k, v in params.items()
                           if k.lower() not in CAMPOS_DE_AUTORIDADE}
        limpos.append(p)
    return limpos


def llm_para_planejador(provedor: ProvedorInferencia) -> Callable[[str], str]:
    """Adapta um provedor ao contrato `llm(objetivo) -> str` do planejador,
    já com a limpeza de autoridade aplicada.

    O planejador recebe JSON de passos — nunca o texto cru do modelo.
    """
    def _llm(objetivo: str) -> str:
        resposta = provedor.propor(objetivo)
        passos = sugestao_como_dado(resposta.texto)
        if passos is None:
            return "[]"                    # ilegível ⇒ plano vazio ⇒ fail-closed
        return json.dumps(passos)
    return _llm
