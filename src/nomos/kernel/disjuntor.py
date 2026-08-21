"""NOMOS kernel.disjuntor — anti-fadiga de aprovação (NH-017c).

O cenário: uma capacidade negada N vezes seguidas continua perguntando —
e humano cansado clica "sim" só para o pedido parar. O disjuntor corta a
PERGUNTA, nunca a resposta: aberto, devolve NEGADO sem incomodar o humano.

Invariantes:
- só converte PERGUNTAR→NEGAR, jamais →PERMITIR (True só vem do humano);
- estado em MEMÓRIA por processo, de propósito: persistir negação seria
  mudar política por efeito colateral — negação durável é decisão humana
  em `policy.json`;
- audita por BORDA (1 evento por abertura; total suprimido no rearme),
  mesma doutrina do freio do ticker;
- NÃO confundir com `orquestracao.recuperacao` (circuito de FALHA de nó —
  semântica distinta).
"""
from __future__ import annotations

import time
from typing import Callable


class DisjuntorAprovacoes:
    """Envolve um aprovador; chave = (categoria, alvo) da Decision."""

    def __init__(self, *, limite: int = 3, janela_s: float = 300.0,
                 audit=None, relogio=time.monotonic):
        self.limite = max(1, int(limite))
        self.janela_s = float(janela_s)
        self.audit = audit
        self._relogio = relogio
        # chave -> {"negacoes": [ts,...], "aberto_em": ts|None, "suprimidas": n}
        self._estado: dict[tuple[str, str], dict] = {}

    # ------------------------------------------------------------- interno

    def _auditar(self, evento: str, **campos) -> None:
        # trilha quebrada não muda o veredito do disjuntor
        import contextlib
        if self.audit is not None:
            with contextlib.suppress(Exception):
                self.audit.append(evento, **campos)

    def _chave(self, decision) -> tuple[str, str]:
        return (str(getattr(decision, "category", "")),
                str(getattr(decision, "target", "")))

    # ------------------------------------------------------------- público

    def envolver(self, aprovador) -> Callable:
        """Devolve um Approver compatível com `gate()` (policy.py)."""

        def _aprovador_com_disjuntor(decision) -> bool:
            chave = self._chave(decision)
            agora = self._relogio()
            est = self._estado.setdefault(
                chave, {"negacoes": [], "aberto_em": None, "suprimidas": 0})
            # expira negações fora da janela (meia-abertura automática)
            est["negacoes"] = [t for t in est["negacoes"]
                               if agora - t < self.janela_s]
            if est["aberto_em"] is not None:
                if agora - est["aberto_em"] < self.janela_s:
                    est["suprimidas"] += 1
                    return False          # aberto: nega SEM perguntar
                # janela venceu: rearma e volta a perguntar
                self._auditar("approvals.disjuntor.rearmado",
                              categoria=chave[0], alvo=chave[1],
                              suprimidas=est["suprimidas"])
                est.update(negacoes=[], aberto_em=None, suprimidas=0)

            resultado = bool(aprovador(decision))
            if resultado:
                est.update(negacoes=[], aberto_em=None, suprimidas=0)
                return True
            est["negacoes"].append(agora)
            if len(est["negacoes"]) >= self.limite:
                est["aberto_em"] = agora
                self._auditar("approvals.disjuntor.aberto",
                              categoria=chave[0], alvo=chave[1],
                              negacoes=len(est["negacoes"]),
                              janela_s=self.janela_s)
            return False

        return _aprovador_com_disjuntor

    def estado_de(self, categoria: str, alvo: str) -> dict:
        """Consulta p/ `approvals testar` — nunca muda estado."""
        est = self._estado.get((str(categoria), str(alvo)))
        if not est:
            return {"aberto": False, "negacoes_na_janela": 0}
        agora = self._relogio()
        aberto = (est["aberto_em"] is not None
                  and agora - est["aberto_em"] < self.janela_s)
        return {"aberto": aberto,
                "negacoes_na_janela": len([t for t in est["negacoes"]
                                           if agora - t < self.janela_s])}
