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

from dataclasses import dataclass

from nomos.cognition.providers import (
    AnthropicProvider, ChatReply, OllamaProvider, ProviderUnavailable,
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
                 openai_compat=None):
        self.policy = policy
        self.gate = gate
        self.approver = approver
        self.audit = audit
        self.vault = vault
        self.ollama = ollama or OllamaProvider()
        self.cloud_factory = cloud_factory
        self.embutido = embutido   # cérebro leve do NOMOS (opcional)
        self.openai_compat = openai_compat  # LM Studio/llama.cpp local (MC31)

    # ---------- rotas ----------
    def _try_local(self, messages) -> ChatOutcome | None:
        if self.embutido is not None and self.embutido.disponivel():
            try:
                r = self.embutido.chat(messages)
                self.audit.append("chat.embutido", model=r.model, egress="nenhum")
                return ChatOutcome(True, "local", r.text, r.provider, r.model)
            except Exception as exc:
                self.audit.append("chat.embutido.falhou", motivo=type(exc).__name__)
        if self.ollama.available():
            try:
                r: ChatReply = self.ollama.chat(messages)
                self.audit.append("chat.local", model=r.model, egress="nenhum")
                return ChatOutcome(True, "local", r.text, r.provider, r.model)
            except ProviderUnavailable as exc:
                self.audit.append("chat.local.falhou", motivo=str(exc))
        oc = self.openai_compat
        if oc is not None and oc.available():
            try:
                r = oc.chat(messages)
                self.audit.append("chat.local.openai", model=r.model,
                                  egress="nenhum")
                return ChatOutcome(True, "local", r.text, r.provider, r.model)
            except ProviderUnavailable as exc:
                self.audit.append("chat.local.openai.falhou", motivo=str(exc))
        return None

    def _try_cloud(self, messages, passphrase: str | None) -> ChatOutcome:
        d_net = self.policy.decide(Category.NET_EGRESS, target=CLOUD_TARGET)
        if not self.gate(d_net, self.approver):
            self.audit.append("chat.cloud.negado", etapa="A2_NET_EGRESS", alvo=CLOUD_TARGET)
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
        try:
            r = self.cloud_factory(api_key=key).chat(messages)
        except ProviderUnavailable as exc:
            self.audit.append("chat.cloud.falhou", motivo=str(exc))
            return ChatOutcome(False, "degradada", "", reason=f"API cloud indisponível: {exc}")
        self.audit.append("chat.cloud.aprovado", model=r.model,
                          egress=CLOUD_TARGET, credencial=CLOUD_KEY_NAME)
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
                continue
            self.audit.append(rotulo, model=r.model, egress="nenhum",
                              stream=True)
            return ChatOutcome(True, "local", r.text, r.provider, r.model)
        return self._degraded(extra="")

    def _degraded(self, extra: str) -> ChatOutcome:
        reason = (
            "nenhum backend de modelo disponível: Ollama não respondeu em "
            f"{self.ollama.host} e a rota cloud não foi autorizada/configurada"
            + (f" ({extra})" if extra else "")
        )
        self.audit.append("chat.degradado", motivo=reason)
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
