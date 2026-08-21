"""NOMOS cognition.router — roteamento local-first com degradação transparente.

Regras (R11):
- local (Ollama) é o default quando presente; nenhum gate para inferência
  local (não há egress nem credencial — dados não saem da máquina);
- cloud é OPT-IN por chamada e exige DUAS decisões aprovadas no gate:
  A2 NET_EGRESS (alvo api.anthropic.com) e A3 CRED_USE (chave no cofre);
  contexto não interativo => negado fail-closed (comportamento do gate);
- sem local e sem cloud autorizada => resposta DEGRADADA transparente:
  ok=False, motivo exato, instrução de correção — NUNCA texto inventado;
- toda rota gera registro de auditoria; a chave jamais toca o log.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from nomos.cognition.providers import (
    AnthropicProvider, OllamaProvider, ProviderUnavailable,
)
from nomos.kernel.policy import Category
from nomos.kernel.vault import Vault, VaultError

CLOUD_KEY_NAME = "anthropic_api_key"
CLOUD_TARGET = "api.anthropic.com"


@dataclass(frozen=True)
class ChatOutcome:
    ok: bool
    route: str            # "local" | "cloud" | "degradada"
    text: str
    provider: str = ""
    model: str = ""
    reason: str = ""      # preenchido quando degradada


class Router:
    def __init__(self, policy, gate, approver, audit, vault: Vault,
                 ollama: OllamaProvider | None = None,
                 cloud_factory=AnthropicProvider, embutido=None,
                 openai_compat=None, uso=None):
        self.policy = policy
        self.gate = gate
        self.approver = approver
        self.audit = audit
        self.vault = vault
        self.ollama = ollama or OllamaProvider()
        self.cloud_factory = cloud_factory
        self.embutido = embutido   # cérebro leve do NOMOS (opcional)
        self.openai_compat = openai_compat  # LM Studio/llama.cpp local (MC31)
        # NH-019: medidor de uso (MedidorUso | None). None = no-op total —
        # a suíte existente é o teste de regressão do default.
        self.uso = uso

    # ---------- medição (NH-019) ----------

    @staticmethod
    def _chars(messages) -> int:
        try:
            return sum(len(str(m.get("content", ""))) for m in messages)
        except Exception:
            return 0

    def _medir(self, *, origem: str, rota: str, ok: bool, t0: float,
               messages, resposta: str = "", motor: str = "", modelo: str = "",
               tokens_prompt=None, tokens_resposta=None, erro: str = "") -> None:
        """Nunca levanta; só type(exc).__name__ chega ao campo `erro`."""
        if self.uso is None:
            return
        import time as _t
        from nomos.cognition.uso_motores import EventoUso
        self.uso.registrar(EventoUso(
            ts=_t.time(), origem=origem, motor=motor, modelo=modelo,
            modalidade="texto", rota=rota, ok=ok,
            dur_ms=int((_t.monotonic() - t0) * 1000),
            chars_prompt=self._chars(messages),
            chars_resposta=len(resposta),
            tokens_prompt=tokens_prompt, tokens_resposta=tokens_resposta,
            erro=erro))

    # ---------- rotas ----------
    def _try_local(self, messages) -> ChatOutcome | None:
        if self.embutido is not None and self.embutido.disponivel():
            t0 = time.monotonic()
            try:
                r = self.embutido.chat(messages)
                self.audit.append("chat.embutido", model=r.model, egress="nenhum")
                self._medir(origem="chat", rota="local", ok=True, t0=t0,
                            messages=messages, resposta=r.text,
                            motor=r.provider, modelo=r.model,
                            tokens_prompt=getattr(r, "tokens_prompt", None),
                            tokens_resposta=getattr(r, "tokens_resposta", None))
                return ChatOutcome(True, "local", r.text, r.provider, r.model)
            except Exception as exc:
                self.audit.append("chat.embutido.falhou", motivo=type(exc).__name__)
                self._medir(origem="chat", rota="local", ok=False, t0=t0,
                            messages=messages, motor="embutido",
                            erro=type(exc).__name__)
        if self.ollama.available():
            t0 = time.monotonic()
            try:
                # Horizonte 3/item 3: anotação explícita removida — `r` já
                # é inferido corretamente como ChatReply pelo retorno de
                # chat(); a anotação aqui colidia (mesmo escopo de função,
                # ramos mutuamente exclusivos que o mypy não funde) com o
                # `r` implícito da linha 56, sem mudar nenhum tipo real.
                r = self.ollama.chat(messages)
                self.audit.append("chat.local", model=r.model, egress="nenhum")
                self._medir(origem="chat", rota="local", ok=True, t0=t0,
                            messages=messages, resposta=r.text,
                            motor=r.provider, modelo=r.model,
                            tokens_prompt=r.tokens_prompt,
                            tokens_resposta=r.tokens_resposta)
                return ChatOutcome(True, "local", r.text, r.provider, r.model)
            except ProviderUnavailable as exc:
                self.audit.append("chat.local.falhou", motivo=str(exc))
                self._medir(origem="chat", rota="local", ok=False, t0=t0,
                            messages=messages, motor="ollama",
                            erro=type(exc).__name__)
        oc = self.openai_compat
        if oc is not None and oc.available():
            t0 = time.monotonic()
            try:
                r = oc.chat(messages)
                self.audit.append("chat.local.openai", model=r.model,
                                  egress="nenhum")
                self._medir(origem="chat", rota="local", ok=True, t0=t0,
                            messages=messages, resposta=r.text,
                            motor=r.provider, modelo=r.model,
                            tokens_prompt=r.tokens_prompt,
                            tokens_resposta=r.tokens_resposta)
                return ChatOutcome(True, "local", r.text, r.provider, r.model)
            except ProviderUnavailable as exc:
                self.audit.append("chat.local.openai.falhou", motivo=str(exc))
                self._medir(origem="chat", rota="local", ok=False, t0=t0,
                            messages=messages, motor="openai-compat",
                            erro=type(exc).__name__)
        return None

    def _try_cloud(self, messages, passphrase: str | None) -> ChatOutcome:
        t0 = time.monotonic()
        d_net = self.policy.decide(Category.NET_EGRESS, target=CLOUD_TARGET)
        if not self.gate(d_net, self.approver):
            self.audit.append("chat.cloud.negado", etapa="A2_NET_EGRESS", alvo=CLOUD_TARGET)
            self._medir(origem="chat", rota="degradada", ok=False, t0=t0,
                        messages=messages)
            return ChatOutcome(False, "degradada", "",
                               reason="egress negado no gate A2 (aprovação ausente)")
        d_cred = self.policy.decide(Category.CRED_USE, target=f"vault:{CLOUD_KEY_NAME}")
        if not self.gate(d_cred, self.approver):
            self.audit.append("chat.cloud.negado", etapa="A3_CRED_USE", alvo=CLOUD_KEY_NAME)
            return ChatOutcome(False, "degradada", "",
                               reason="uso de credencial negado no gate A3")
        if passphrase is None:
            return ChatOutcome(False, "degradada", "",
                               reason="passphrase do cofre não fornecida para ler a chave")
        try:
            key = self.vault.get(CLOUD_KEY_NAME, passphrase)
        except VaultError as exc:
            self.audit.append("chat.cloud.negado", etapa="cofre", motivo=str(exc))
            return ChatOutcome(False, "degradada", "",
                               reason=f"chave '{CLOUD_KEY_NAME}' indisponível no cofre: {exc}")
        except Exception as exc:   # cofre corrompido/ilegível: degrada, não quebra
            self.audit.append("chat.cloud.negado", etapa="cofre",
                              motivo=type(exc).__name__)
            return ChatOutcome(False, "degradada", "",
                               reason=f"cofre ilegível ({type(exc).__name__}) — "
                                      "rode: nomos doutor --consertar")
        t0 = time.monotonic()
        try:
            r = self.cloud_factory(api_key=key).chat(messages)
        except ProviderUnavailable as exc:
            self.audit.append("chat.cloud.falhou", motivo=str(exc))
            self._medir(origem="chat", rota="cloud", ok=False, t0=t0,
                        messages=messages, motor="cloud",
                        erro=type(exc).__name__)
            return ChatOutcome(False, "degradada", "", reason=f"API cloud indisponível: {exc}")
        self.audit.append("chat.cloud.aprovado", model=r.model,
                          egress=CLOUD_TARGET, credencial=CLOUD_KEY_NAME)
        self._medir(origem="chat", rota="cloud", ok=True, t0=t0,
                    messages=messages, resposta=r.text,
                    motor=r.provider, modelo=r.model,
                    tokens_prompt=r.tokens_prompt,
                    tokens_resposta=r.tokens_resposta)
        return ChatOutcome(True, "cloud", r.text, r.provider, r.model)

    # ---------- entrada única ----------
    def chat(self, messages: list[dict], prefer_cloud: bool = False,
             passphrase: str | None = None) -> ChatOutcome:
        if prefer_cloud:
            out = self._try_cloud(messages, passphrase)
            if out.ok:
                return out
            local = self._try_local(messages)
            if local:
                return ChatOutcome(True, "local", local.text, local.provider,
                                   local.model, reason=f"cloud indisponível ({out.reason})")
            return self._degraded(extra=out.reason)
        local = self._try_local(messages)
        if local:
            return local
        return self._degraded(extra="")

    def chat_stream(self, messages: list[dict], on_token) -> ChatOutcome:
        """Streaming local-first (v1.1). Cloud NÃO tem stream (segue opt-in
        pelo chat normal). Backend sem stream => resposta completa emitida de
        uma vez pelo mesmo callback (fallback honesto, nunca quebra)."""
        for backend, rotulo in ((self.embutido, "chat.embutido"),
                                (self.ollama, "chat.local"),
                                (self.openai_compat, "chat.local.openai")):
            if backend is None:
                continue
            pronto = backend.disponivel() if hasattr(backend, "disponivel") \
                else backend.available()
            if not pronto:
                continue
            t0 = time.monotonic()
            try:
                if hasattr(backend, "chat_stream"):
                    r = backend.chat_stream(messages, on_token)
                else:
                    r = backend.chat(messages)
                    on_token(r.text)
            except KeyboardInterrupt:
                raise                     # decisão do usuário sobe intacta
            except Exception as exc:
                self.audit.append(f"{rotulo}.falhou", motivo=type(exc).__name__)
                self._medir(origem="chat_stream", rota="local", ok=False,
                            t0=t0, messages=messages, motor=rotulo,
                            erro=type(exc).__name__)
                continue
            self.audit.append(rotulo, model=r.model, egress="nenhum",
                              stream=True)
            # stream não garante usage do backend ⇒ tokens None, honesto
            self._medir(origem="chat_stream", rota="local", ok=True, t0=t0,
                        messages=messages, resposta=r.text,
                        motor=r.provider, modelo=r.model)
            return ChatOutcome(True, "local", r.text, r.provider, r.model)
        return self._degraded(extra="", origem="chat_stream")

    def _degraded(self, extra: str, origem: str = "chat") -> ChatOutcome:
        reason = (
            "nenhum backend de modelo disponível: Ollama não respondeu em "
            f"{self.ollama.host} e a rota cloud não foi autorizada/configurada"
            + (f" ({extra})" if extra else "")
        )
        self.audit.append("chat.degradado", motivo=reason)
        self._medir(origem=origem, rota="degradada", ok=False,
                    t0=time.monotonic(), messages=[])
        text = (
            "[MODO DEGRADADO — sem capacidade de modelo]\n"
            f"Motivo: {reason}.\n"
            "Correções possíveis: (1) instale/inicie o Ollama local "
            "(`ollama serve` + `ollama pull <modelo>`); ou (2) grave sua chave "
            "no cofre (`nomos vault set anthropic_api_key`) e use `--cloud` em "
            "terminal interativo para aprovar A2+A3.\n"
            "Este agente NÃO simula respostas sem modelo."
        )
        return ChatOutcome(False, "degradada", text, reason=reason)
