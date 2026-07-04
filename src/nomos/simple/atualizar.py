"""NOMOS simple.atualizar — atualização manual e consciente. NUNCA automática.

Regras:
- checar versão é um egress (api.github.com): passa pelo gate A2 — com o
  cadeado só-local ligado, é NEGADO já na política, com explicação;
- sem terminal interativo não há aprovação => negado (fail-closed);
- ao encontrar versão nova, o NOMOS MOSTRA o caminho manual de atualização;
  jamais baixa ou instala sozinho — por projeto, sem exceção;
- nada além de versão/nota pública é trafegado; nenhum dado do usuário sai.
"""
from __future__ import annotations

import json
import re
import urllib.request
from urllib.parse import urlparse

from nomos import __version__
from nomos.kernel.policy import Category, gate

ALVO = "api.github.com"
URL_ULTIMA = "https://api.github.com/repos/Voltolini-SPACE/NOMOS/releases/latest"
URL_RELEASES_HUMANA = "https://github.com/Voltolini-SPACE/NOMOS/releases"


def comparar_versoes(a: str, b: str) -> int:
    """-1 se a<b, 0 se igual, 1 se a>b. Tolerante a 'v' e sufixos (rc, dev)."""
    def partes(v: str) -> tuple:
        v = (v or "").strip().lstrip("vV")
        nums = re.findall(r"\d+", v.split("-")[0].split("+")[0])[:3]
        base = tuple(int(n) for n in nums) + (0,) * (3 - len(nums))
        # versão com sufixo (rc/beta) ordena ANTES da final de mesmo número
        sufixo = 0 if re.search(r"(rc|a|b|dev)", v.lower()) else 1
        return base + (sufixo,)
    pa, pb = partes(a), partes(b)
    return (pa > pb) - (pa < pb)


def _fetch_padrao(timeout: float = 6.0) -> dict:
    """GET https-only na API pública do GitHub. Sem token, sem dados do usuário."""
    if urlparse(URL_ULTIMA).scheme != "https":
        raise ValueError("apenas https é permitido para checar versão")
    req = urllib.request.Request(URL_ULTIMA, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": f"nomos/{__version__}",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:  # nosec B310 - https validado acima
        data = json.loads(r.read().decode("utf-8", "replace"))
    return {
        "versao": str(data.get("tag_name", "")).lstrip("vV"),
        "nome": data.get("name") or data.get("tag_name", ""),
        "url": data.get("html_url", URL_RELEASES_HUMANA),
        "notas": (data.get("body") or "")[:800],
    }


def verificar(ctx, approver, fetcher=None, say=print) -> int:
    """Fluxo completo do `nomos atualizar`. Devolve exit code (0/1/3)."""
    original = ctx["policy"].decide(Category.NET_EGRESS, target=ALVO)
    # motivo amigável para o aprovador humano — sem apagar o motivo da política
    pedido = type(original)(category=original.category, target=original.target,
                            effect=original.effect,
                            reason="checar a última versão do NOMOS no GitHub "
                                   "(só versão e notas públicas; nada seu é enviado)")
    if not gate(pedido, approver):
        ctx["audit"].append("atualizar.negado", motivo=original.reason[:80])
        from nomos.simple.erros import fmt
        say(fmt("E002", "Não fui checar a internet — e isso é uma proteção, não um erro."))
        if "só-local" in original.reason:
            say("O cadeado só-local está LIGADO 🔒. Para permitir esta checagem "
                "pontual: nomos local off (e depois volte com nomos local on).")
        say(f"Checagem manual, quando quiser: {URL_RELEASES_HUMANA}")
        return 3

    fetcher = fetcher or _fetch_padrao
    try:
        info = fetcher()
    except Exception as exc:
        ctx["audit"].append("atualizar.falhou", motivo=type(exc).__name__)
        from nomos.simple.erros import fmt
        say(fmt("E008", f"Não consegui consultar a última versão ({type(exc).__name__}). ") +
            f"Tente de novo mais tarde ou veja manualmente: {URL_RELEASES_HUMANA}")
        return 1

    remota = info.get("versao", "")
    if not remota:
        say("A resposta do GitHub veio sem número de versão — nada a fazer. "
            f"Veja manualmente: {URL_RELEASES_HUMANA}")
        return 1
    ctx["audit"].append("atualizar.verificado", local=__version__, remota=remota)

    cmp = comparar_versoes(__version__, remota)
    if cmp >= 0:
        say(f"Você já está na versão mais nova (local {__version__} · "
            f"última publicada {remota}).")
        if cmp > 0:
            say("(a sua é mais nova que a release — build de desenvolvimento)")
        return 0

    say(f"Versão nova disponível: {remota} (você está na {__version__}).")
    if info.get("notas"):
        say("Novidades (resumo):")
        for linha in info["notas"].splitlines()[:8]:
            say(f"  {linha}")
    say("")
    say("Eu NUNCA me atualizo sozinho. Quando você quiser, o caminho manual é:")
    say(f"  1. Abra {info.get('url', URL_RELEASES_HUMANA)}")
    say("  2. Baixe o instalador do seu sistema (install.sh / install.ps1) e o .whl")
    say("  3. Rode o instalador — ele faz backup e dá rollback se algo falhar")
    say("Suas memórias, chaves e configurações ficam intactas (vivem em ~/.nomos).")
    return 0
