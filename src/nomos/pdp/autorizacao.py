"""NOMOS pdp.autorizacao — o contrato de autorização (ABSORPTION-01 / FASE 2).

Uma `Autorizacao` é a prova portátil de que ALGUÉM concedeu ALGO, com escopo e
prazo. Ela não decide nada: quem decide é o `Decisor` (PDP). Aqui ficam só as
peças que tornam a decisão comprovável — canonicalização estável, assinatura
HMAC, chaveiro com rotação e armazém de nonce anti-replay.

Portado da mecânica provada em NOMOS-HERMES-ARCHITECTURE (FULL-02), adaptado
às convenções do NOMOS: pt-BR, fail-closed e sem inventar política própria —
a classificação de risco continua vindo de `kernel.policy`.

Propriedades:
- assinatura cobre o contrato inteiro MENOS o próprio campo de assinatura;
- comparação de assinatura em tempo constante (`hmac.compare_digest`);
- `hash_contrato` é identidade estável do conteúdo (não muda com o signatário);
- nonce é de uso único, com expiração e coleta de lixo;
- atenuação: um filho só é válido se for subconjunto do pai em TODOS os eixos.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import threading
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

RISCOS = ("A0", "A1", "A2", "A3", "A4", "A5", "A6")


def _ordem_risco(r: str) -> int:
    return RISCOS.index(r) if r in RISCOS else 99


def agora_utc() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Autorizacao:
    """Concessão assinada. Imutável de propósito: atenuar cria outra."""
    capacidades: tuple[str, ...]
    sujeito: str
    audiencia: str                      # qual PEP pode consumir
    emitida_em: datetime
    expira_em: datetime
    risco_max: str = "A0"
    caminhos: tuple[str, ...] = ()      # prefixos de recurso permitidos ("" = nenhum)
    nonce: str = ""
    id_chave: str = ""
    assinatura: str = ""
    emissor: str = "nomos"
    jti: str = ""

    def dict_canonico(self) -> dict:
        """Forma serializável e ordenável — SEM a assinatura."""
        return {
            "capacidades": sorted(self.capacidades),
            "sujeito": self.sujeito,
            "audiencia": self.audiencia,
            "emitida_em": self.emitida_em.astimezone(timezone.utc).isoformat(),
            "expira_em": self.expira_em.astimezone(timezone.utc).isoformat(),
            "risco_max": self.risco_max,
            "caminhos": sorted(self.caminhos),
            "nonce": self.nonce,
            "id_chave": self.id_chave,
            "emissor": self.emissor,
            "jti": self.jti,
        }


def carga_canonica(auth: Autorizacao) -> bytes:
    """Serialização determinística — a base da assinatura e do hash."""
    return json.dumps(auth.dict_canonico(), sort_keys=True,
                      separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def hash_contrato(auth: Autorizacao) -> str:
    return hashlib.sha256(carga_canonica(auth)).hexdigest()


class ErroChaveiro(ValueError):
    """Chave desconhecida ou chaveiro vazio — sempre fail-closed."""


class Chaveiro:
    """id_chave → chave. Pronto para rotação: adiciona a nova, mantém a antiga
    durante a sobreposição, remove depois."""

    def __init__(self, chaves: dict[str, bytes]):
        if not chaves:
            raise ErroChaveiro("chaveiro vazio — nada pode ser verificado")
        for cid, k in chaves.items():
            if not isinstance(cid, str) or not cid:
                raise ErroChaveiro("id_chave inválido")
            if not isinstance(k, (bytes, bytearray)) or len(k) < 16:
                raise ErroChaveiro(f"chave de '{cid}' curta demais (mín. 16 bytes)")
        self._chaves = {c: bytes(k) for c, k in chaves.items()}

    def obter(self, id_chave: str) -> bytes | None:
        if not isinstance(id_chave, str):
            return None
        return self._chaves.get(id_chave)

    def assinar(self, auth: Autorizacao, id_chave: str) -> Autorizacao:
        chave = self.obter(id_chave)
        if chave is None:
            raise ErroChaveiro(f"id_chave desconhecido: {id_chave!r}")
        base = replace(auth, id_chave=id_chave, assinatura="")
        sig = hmac.new(chave, carga_canonica(base), hashlib.sha256).hexdigest()
        return replace(base, assinatura=sig)

    def verificar(self, auth: Autorizacao) -> bool:
        """Assinatura confere? Qualquer anomalia ⇒ False (nunca exceção)."""
        try:
            chave = self.obter(auth.id_chave)
            if chave is None:
                return False
            sig = auth.assinatura
            if not isinstance(sig, str) or len(sig) != 64:
                return False
            base = replace(auth, assinatura="")
            esperada = hmac.new(chave, carga_canonica(base), hashlib.sha256).hexdigest()
            return hmac.compare_digest(esperada, sig)
        except Exception:
            return False


class ErroArmazem(RuntimeError):
    """Armazém de nonce indisponível — o PDP trata como DENY."""


class ArmazemNonce:
    """Nonces já consumidos, com expiração. Thread-safe.

    `indisponivel=True` simula/propaga falha de armazenamento: o PDP precisa
    NEGAR quando não consegue provar que não houve replay.
    """

    def __init__(self, indisponivel: bool = False):
        self._vistos: dict[str, datetime] = {}
        self._lock = threading.Lock()
        self.indisponivel = indisponivel

    def consumir(self, nonce: str, agora: datetime, ttl_s: int = 300) -> bool:
        if self.indisponivel:
            raise ErroArmazem("armazém de nonce indisponível")
        if not nonce or not isinstance(nonce, str):
            return False
        with self._lock:
            self._coletar(agora)
            if nonce in self._vistos:
                return False                     # replay
            self._vistos[nonce] = agora + timedelta(seconds=ttl_s)
            return True

    def _coletar(self, agora: datetime) -> None:
        mortos = [n for n, exp in self._vistos.items() if exp <= agora]
        for n in mortos:
            del self._vistos[n]


# ------------------------------------------------------------------ atenuação

def _caminhos_subconjunto(filho: tuple[str, ...], pai: tuple[str, ...]) -> bool:
    """Todo caminho do filho tem de estar coberto por algum prefixo do pai."""
    if not filho:
        return True
    if not pai:
        return False
    return all(any(c == p or c.startswith(p.rstrip("/") + "/") for p in pai)
               for c in filho)


def e_atenuacao(filho: Autorizacao, pai: Autorizacao) -> bool:
    """True SÓ se o filho for ⊆ pai em TODOS os eixos.

    Fail-closed por construção: se não der para PROVAR que é atenuação, não é.
    """
    try:
        if not set(filho.capacidades).issubset(set(pai.capacidades)):
            return False
        if filho.sujeito != pai.sujeito or filho.audiencia != pai.audiencia:
            return False
        if _ordem_risco(filho.risco_max) > _ordem_risco(pai.risco_max):
            return False
        if filho.expira_em > pai.expira_em:
            return False
        if filho.emitida_em < pai.emitida_em:
            return False
        return _caminhos_subconjunto(filho.caminhos, pai.caminhos)
    except Exception:
        return False


def atenuar(pai: Autorizacao, chaveiro: Chaveiro, id_chave: str, *,
            capacidades=None, caminhos=None, expira_em=None,
            risco_max=None, nonce: str = "", jti: str = "") -> Autorizacao:
    """Deriva um filho comprovadamente ⊆ pai, reassinado.

    Qualquer tentativa de ALARGAR é intersectada de volta ao pai — nunca para
    cima. Assim, nem quem chama esta função consegue produzir um filho maior.
    """
    caps = tuple(sorted(set(capacidades) & set(pai.capacidades))) if capacidades is not None \
        else pai.capacidades
    if not caps:
        raise ValueError("atenuação vazia: filho ficaria sem capacidade alguma")
    if caminhos is None:
        novos_caminhos = pai.caminhos
    else:
        novos_caminhos = tuple(c for c in caminhos
                               if _caminhos_subconjunto((c,), pai.caminhos))
    exp = min(expira_em, pai.expira_em) if expira_em is not None else pai.expira_em
    risco = risco_max if risco_max is not None else pai.risco_max
    if _ordem_risco(risco) > _ordem_risco(pai.risco_max):
        risco = pai.risco_max
    filho = Autorizacao(
        capacidades=caps, sujeito=pai.sujeito, audiencia=pai.audiencia,
        emitida_em=pai.emitida_em, expira_em=exp, risco_max=risco,
        caminhos=novos_caminhos, nonce=nonce, emissor=pai.emissor, jti=jti)
    return chaveiro.assinar(filho, id_chave)
