"""NOMOS cognition.relay — o roteador OmniRoute como motor GOVERNADO.

O OmniRoute roda em `127.0.0.1:20128` e roteia para 160+ provedores, inclusive
gratuitos. Falar com ele parece local — mas é falar com a internet, com um salto
de disfarce no meio. Este módulo existe para que esse salto não engane ninguém.

Duas decisões que definem o desenho:

1. **O alvo do gate NÃO é o socket.** Se perguntássemos ao PDP por
   `127.0.0.1:20128`, o operador leria isso no prompt de aprovação e veria um
   endereço local. Perguntamos por `RELAY_TARGET`, que não é loopback nem para
   `kernel.localidade` nem para o olho humano — então o cadeado só-local o
   trata como remoto e a linha de auditoria diz a verdade.

2. **A chave vem do COFRE, nunca do `.env` do OmniRoute.** Aquele arquivo é
   global e foi encontrado legível por qualquer processo (corrigido em 23/08),
   e guarda a chave que cifra o próprio banco de credenciais. Credencial que o
   NOMOS usa sai da governança do NOMOS.

A ordem das barreiras é a mesma de `arbitragem.montar_runner_nuvem`, de
propósito: um leitor que conhece uma entende a outra.
"""
from __future__ import annotations

RELAY_TARGET = "omniroute-relay"
"""Alvo declarado ao PDP. NÃO é o endereço: é a fronteira de saída.

Deliberadamente sem `://` e sem host loopback — medido: um alvo como
`omniroute://127.0.0.1:20128` volta a ser classificado como local e cai em
REQUIRE_APPROVAL em vez de DENY sob cadeado.
"""

RELAY_KEY_NAME = "omniroute_api_key"
RELAY_BASE = "http://127.0.0.1:20128/v1"
MODELO_PADRAO = "auto/best-free"
"""Rota gratuita por padrão: o dono pediu explicitamente free tiers + modelos
locais. `auto/best-free` deixa o OmniRoute escolher entre os gratuitos."""


def montar_runner_omniroute(home, *, policy, vault, approver,
                            passphrase: str | None,
                            modelo: str = MODELO_PADRAO,
                            gate=None, factory=None):
    """Constrói o provedor OmniRoute SOMENTE se todas as barreiras passarem.

    Ordem, cada uma fail-closed:
      1) cadeado de localidade desligado;
      2) gate A2 (egresso) aprovado — com `RELAY_TARGET`, não com o socket;
      3) gate A3 (uso de credencial) aprovado;
      4) passphrase fornecida e chave presente no cofre.

    Devolve ``(provider, "")`` ou ``(None, motivo)``. Nunca levanta por falha
    de autorização — negar é resultado, não exceção.
    """
    from nomos.kernel import localidade
    from nomos.kernel.policy import Category
    from nomos.kernel.policy import gate as gate_padrao
    g = gate or gate_padrao

    if localidade.esta_ligado(home):
        return None, ("cadeado só-local LIGADO — o roteador OmniRoute SAI para "
                      "a internet; não participa (decisão consciente: "
                      "nomos local off)")

    d_net = policy.decide(Category.NET_EGRESS, target=RELAY_TARGET)
    if not g(d_net, approver):
        return None, "egresso negado no gate A2 (sem aprovação)"

    d_cred = policy.decide(Category.CRED_USE, target=f"vault:{RELAY_KEY_NAME}")
    if not g(d_cred, approver):
        return None, "uso de credencial negado no gate A3"

    if not passphrase:
        return None, "passphrase do cofre não fornecida"
    try:
        key = vault.get(RELAY_KEY_NAME, passphrase)
    except Exception as exc:
        return None, f"chave '{RELAY_KEY_NAME}' indisponível no cofre: {exc}"

    if factory is not None:
        return factory(api_key=key, modelo=modelo), ""
    from nomos.cognition.providers import OmniRouteProvider
    return OmniRouteProvider(api_key=key, base=RELAY_BASE, model=modelo), ""


# --------------------------------------------------------------- descoberta
TTL_DESCOBERTA_S = 300.0
"""5 min. Descoberta é conveniência, não caminho quente: consultar a cada
chamada tornaria o roteador um ponto de latência do NOMOS."""


def descobrir_rotas(api_key: str, base: str = RELAY_BASE,
                    timeout: float = 3.0) -> list[str]:
    """Rotas que o OmniRoute oferece AGORA, sem comando manual.

    O dono pediu que rotas novas apareçam sozinhas: se ele adicionar uma chave
    de provedor no painel, ou se o OmniRoute ganhar um gratuito novo, o NOMOS
    deve enxergar sem alguém rodar nada.

    FRONTEIRA QUE ESTA FUNÇÃO NÃO CRUZA: descobrir NÃO é autorizar. Ela só
    lista o que existe. Cada uso continua passando por
    `montar_runner_omniroute` — cadeado, A2, A3, cofre. Uma rota nova fica
    DISPONÍVEL para escolha, nunca ATIVA por conta própria; caso contrário um
    provedor novo no painel viraria um caminho de saída que ninguém aprovou.

    Falha (serviço fora, chave errada, rede) devolve lista vazia, sem exceção:
    descoberta indisponível não pode derrubar quem só queria conversar.
    """
    import json
    import urllib.request

    from nomos.cognition.motores import _abrir_http, _cacheado

    def probe():
        try:
            req = urllib.request.Request(
                f"{base.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {api_key}"})
            with _abrir_http(req, timeout) as r:   # guard: valida o esquema
                dados = json.loads(r.read().decode())
            return [m["id"] for m in dados.get("data", []) if m.get("id")]
        except Exception:
            return []

    return _cacheado(f"omniroute:rotas:{base}", TTL_DESCOBERTA_S, probe)


def rotas_gratuitas(api_key: str, base: str = RELAY_BASE) -> list[str]:
    """Só as rotas sem custo — o que o dono pediu para usar por padrão."""
    return [r for r in descobrir_rotas(api_key, base) if "free" in r.lower()]


def resumo_descoberta(api_key: str, base: str = RELAY_BASE) -> dict:
    """Retrato para o operador: quantas rotas, quantas grátis, e quais.

    Existe para responder "o que apareceu de novo?" sem ninguém precisar
    decorar endpoint nem montar curl com Bearer na mão.
    """
    todas = descobrir_rotas(api_key, base)
    gratis = [r for r in todas if "free" in r.lower()]
    return {"total": len(todas), "gratuitas": len(gratis),
            "rotas_gratuitas": sorted(gratis), "disponivel": bool(todas)}
