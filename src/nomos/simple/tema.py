"""NOMOS simple.tema — deixe o NOMOS com a SUA cara (cores personalizáveis).

Cada usuário escolhe uma paleta e uma cor de destaque. Guardado no perfil,
persiste entre sessões. Tudo em cores ANSI padrão de terminal (sem
dependências), com opção de desligar (acessibilidade / terminais sem cor).
"""
from __future__ import annotations

from nomos.simple.onboarding import salvar_perfil

RESET = "\033[0m"

# cores base ANSI (nome amigável -> código de texto)
CORES_ANSI = {
    "vermelho": "31", "verde": "32", "amarelo": "33", "azul": "34",
    "magenta": "35", "ciano": "36", "branco": "37",
    "cinza": "90", "vermelho-claro": "91", "verde-claro": "92",
    "amarelo-claro": "93", "azul-claro": "94", "rosa": "95", "ciano-claro": "96",
}

# paletas prontas: (destaque, titulo, sucesso, aviso, fraco)
PALETAS = {
    "oceano":   {"destaque": "ciano",   "titulo": "azul-claro",   "rotulo": "Oceano (azul e ciano)"},
    "floresta": {"destaque": "verde",   "titulo": "verde-claro",  "rotulo": "Floresta (verdes)"},
    "por-do-sol": {"destaque": "amarelo", "titulo": "rosa",       "rotulo": "Pôr do sol (laranja e rosa)"},
    "roxo":     {"destaque": "magenta", "titulo": "rosa",         "rotulo": "Ametista (roxos)"},
    "mono":     {"destaque": "branco",  "titulo": "branco",       "rotulo": "Monocromático (sem cor de destaque)"},
}
PALETA_PADRAO = "oceano"


def _codigo(nome_cor: str) -> str:
    return CORES_ANSI.get(nome_cor, "36")


class Tema:
    """Resolve nomes de estilo em códigos ANSI, respeitando a escolha e o
    liga/desliga de cor. Uso: t.c('destaque', 'texto')."""

    def __init__(self, perfil: dict | None = None):
        perfil = perfil or {}
        cfg = perfil.get("tema") or {}
        self.ativo = cfg.get("cor_ligada", True)
        paleta = PALETAS.get(cfg.get("paleta", PALETA_PADRAO), PALETAS[PALETA_PADRAO])
        # cor de destaque escolhida sobrepõe a da paleta, se houver
        self.destaque = cfg.get("destaque") or paleta["destaque"]
        self.titulo = paleta["titulo"]

    def _pinta(self, cor_nome: str, texto: str, negrito: bool = False) -> str:
        if not self.ativo:
            return texto
        b = "1;" if negrito else ""
        return f"\033[{b}{_codigo(cor_nome)}m{texto}{RESET}"

    def c(self, papel: str, texto: str) -> str:
        if papel == "destaque":
            return self._pinta(self.destaque, texto, negrito=True)
        if papel == "titulo":
            return self._pinta(self.titulo, texto, negrito=True)
        if papel == "sucesso":
            return self._pinta("verde", texto)
        if papel == "aviso":
            return self._pinta("amarelo", texto)
        if papel == "erro":
            return self._pinta("vermelho", texto)
        if papel == "fraco":
            return self._pinta("cinza", texto)
        return texto


def carregar(perfil: dict | None = None) -> Tema:
    return Tema(perfil)


def aplicar(paleta: str | None = None, destaque: str | None = None,
            cor_ligada: bool | None = None, perfil: dict | None = None) -> dict:
    """Salva a escolha de tema no perfil e devolve o perfil atualizado."""
    from nomos.kernel import config
    perfil = perfil if perfil is not None else (config.load_agent() or {})
    cfg = dict(perfil.get("tema") or {})
    if paleta is not None:
        if paleta not in PALETAS:
            raise ValueError(f"paleta desconhecida: {paleta!r} "
                             f"(opções: {', '.join(PALETAS)})")
        cfg["paleta"] = paleta
        cfg.pop("destaque", None)          # paleta redefine o destaque
    if destaque is not None:
        if destaque not in CORES_ANSI:
            raise ValueError(f"cor desconhecida: {destaque!r} "
                             f"(opções: {', '.join(CORES_ANSI)})")
        cfg["destaque"] = destaque
    if cor_ligada is not None:
        cfg["cor_ligada"] = bool(cor_ligada)
    return salvar_perfil({"tema": cfg})


def amostra(perfil: dict | None = None) -> str:
    """Mostra como as cores atuais ficam."""
    t = carregar(perfil)
    linhas = [
        t.c("titulo", "  Título e nome do agente"),
        t.c("destaque", "  Destaque (o que salta aos olhos)"),
        t.c("sucesso", "  ✓ sucesso") + "   " + t.c("aviso", "! aviso") + "   "
        + t.c("erro", "✗ erro"),
        t.c("fraco", "  texto secundário"),
    ]
    return "\n".join(linhas)


def menu_tema(ask=input, say=print, perfil: dict | None = None) -> dict:
    from nomos.kernel import config
    perfil = perfil if perfil is not None else (config.load_agent() or {})
    say("")
    say("🎨 Deixe o NOMOS com a sua cara. Paletas prontas:")
    chaves = list(PALETAS)
    for i, k in enumerate(chaves, 1):
        say(f"   {i}) {PALETAS[k]['rotulo']}")
    say(f"   {len(chaves)+1}) escolher só a cor de destaque")
    say(f"   {len(chaves)+2}) desligar as cores")
    esc = ask("opção> ").strip()
    try:
        if esc == str(len(chaves) + 1):
            say("cores de destaque: " + ", ".join(CORES_ANSI))
            cor = ask("cor> ").strip()
            perfil = aplicar(destaque=cor, perfil=perfil)
        elif esc == str(len(chaves) + 2):
            perfil = aplicar(cor_ligada=False, perfil=perfil)
            say("cores desligadas.")
            return perfil
        elif esc.isdigit() and 1 <= int(esc) <= len(chaves):
            perfil = aplicar(paleta=chaves[int(esc) - 1], cor_ligada=True, perfil=perfil)
        else:
            say("não entendi; mantive o tema atual.")
            return perfil
    except ValueError as exc:
        say(f"ops: {exc}")
        return perfil
    say("ficou assim:")
    say(amostra(perfil))
    return perfil
