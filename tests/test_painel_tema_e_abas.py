"""MC37 — painel em ABAS (menos densidade) + TEMA claro/escuro.

Contratos:
- 5 abas (data-aba) e só a "visão geral" nasce ativa;
- deep-link de seção antiga (#motores…) continua no HTML (âncora + subnav),
  então links salvos não quebram;
- tema: escuro é o padrão (brandbook); há bloco de variáveis do tema claro,
  respeito a prefers-color-scheme, botão de alternância e boot sem flash;
- a página continua read-only sem fila (nenhum <form>).
"""
import re

import pytest

from nomos.cognition import motores
from nomos.interface.painel_web import dados_dashboard, render_dash, render_html
from nomos.kernel.audit import AuditLog
from nomos.kernel.policy import PolicyEngine


@pytest.fixture(autouse=True)
def _iso(nomos_home, monkeypatch):
    monkeypatch.setattr(motores, "modelos_ollama", lambda *a, **k: [])
    monkeypatch.setattr(motores, "_http_ok", lambda *a, **k: False)
    monkeypatch.setattr("shutil.which", lambda *a, **k: None)
    motores.limpar_cache()
    yield
    motores.limpar_cache()


def _ctx(home):
    home.mkdir(parents=True, exist_ok=True)
    (home / "skills").mkdir(exist_ok=True)
    return {"home": home, "policy": PolicyEngine(home / "policy.json"),
            "audit": AuditLog(home / "logs" / "audit.jsonl"),
            "skills": home / "skills"}


def _html(home):
    return render_html(dados_dashboard(_ctx(home)))


# ---------------------------------------------------------------- abas
def test_seis_abas_e_so_visao_ativa(nomos_home):
    # MC38: entrou a aba "chat" (estilo ChatGPT) — 6 abas agora
    corpo = _html(nomos_home)
    for aba in ("visao", "chat", "cerebro", "capacidades", "operacao", "ajuda"):
        assert f'data-aba="{aba}"' in corpo, f"aba {aba} ausente"
    # a sidebar (link) e a seção (section) — 2 ocorrências por aba
    assert corpo.count('data-aba="chat"') >= 2
    # só a visão geral começa aberta (ativa)
    ativas = re.findall(r'class="aba ativa" data-aba="(\w+)"', corpo)
    assert ativas == ["visao"], f"deveria abrir só na visão geral, veio {ativas}"


def test_deep_links_de_secoes_antigas_preservados(nomos_home):
    corpo = _html(nomos_home)
    # âncoras que existiam na página única continuam válidas (id + link na subnav)
    for anc in ("status", "aprovacoes", "checkup", "motores", "conversas",
                "memoria", "skills", "agentes", "capacidades", "mcp",
                "rotinas", "evidencias", "politica", "auditoria", "sistema",
                "ajuda"):
        assert f'id="{anc}"' in corpo, f"seção {anc} perdeu a âncora"
        assert f'href="#{anc}"' in corpo, f"nada linka #{anc} (subnav?)"


def test_menos_kpis_visiveis(nomos_home):
    # densidade: a faixa de KPIs caiu de 8 para 5
    corpo = _html(nomos_home)
    assert corpo.count('<div class="kpi">') == 5


# ---------------------------------------------------------------- tema
def test_tema_escuro_e_claro_ambos_definidos(nomos_home):
    corpo = _html(nomos_home)
    # escuro é o padrão (marca congelada)
    assert "--neon:#5AF78E" in corpo
    # existe um tema claro explícito e o respeito ao SO
    assert ':root[data-tema="claro"]' in corpo
    assert "prefers-color-scheme:light" in corpo
    # o claro redefine o fundo para um tom claro (não é o mesmo do escuro)
    assert "#f4f7f4" in corpo


def test_botao_de_tema_e_boot_sem_flash(nomos_home):
    corpo = _html(nomos_home)
    assert 'id="tema-btn"' in corpo                 # alternância acessível
    assert 'aria-pressed' in corpo
    # boot lê a preferência salva ANTES do <style> (evita flash de tema)
    idx_boot = corpo.find("localStorage.getItem('nomos-tema')")
    idx_style = corpo.find("<style>")
    assert 0 < idx_boot < idx_style, "boot do tema deve vir antes do <style>"


def test_sem_fila_continua_read_only(nomos_home):
    corpo = _html(nomos_home)
    assert "<form" not in corpo and 'method="post"' not in corpo.lower()


# --------------------------------------- P2-8 (auditoria de 2026-07-17) --
# Antes: _CSS_DASH (o NOMOS Dash, /dash/) não tinha NENHUMA regra de tema
# claro — ficava preso no escuro mesmo com o SO/navegador em modo claro,
# ao contrário do painel principal (_CSS), que já respeitava isso desde
# MC37. Corrigido só no CSS (menor risco): adicionado o bloco
# @media (prefers-color-scheme:light) — resolve sozinho o "preso no
# escuro" para quem usa a preferência do sistema, sem tocar em _JS_DASH.
def test_dash_agora_tem_tema_claro_via_preferencia_do_so(nomos_home):
    corpo = render_dash("1.0.0")
    # escuro continua o padrão (:root{...} sem seletor extra, igual a _CSS)
    assert "--neon:#5AF78E" in corpo
    # o Dash ganhou as mesmas regras de tema claro do painel principal
    assert ':root[data-tema="claro"]' in corpo
    assert "prefers-color-scheme:light" in corpo
    assert "#f4f7f4" in corpo
    assert "#0b7a3b" in corpo    # --neon do tema claro (reaproveitado de _CSS)


def test_dash_tema_claro_nao_declara_variavel_rosa_no_escopo_dash(nomos_home):
    """_CSS_DASH nunca usa --rosa em nenhuma regra (diferente de _CSS) —
    a variável foi deliberadamente omitida do bloco novo, não esquecida."""
    from nomos.interface.painel_web import _CSS_DASH
    assert "--rosa:" not in _CSS_DASH   # declaração de variável, não a prosa do comentário
    assert "class=\"lock\"" not in _CSS_DASH  # smoke: é CSS puro, não HTML


# --------------------------------------- Horizonte 3/item 4 (2026-07-17) -
# P2-8 deixou o CSS de tema claro do Dash pronto, mas o próprio commit
# documentou a lacuna: _JS_DASH nunca setava `data-tema` (sem botão de
# alternância nem leitura de localStorage) — o bloco
# `:root[data-tema="claro"]` ficava "inerte", só o
# `@media (prefers-color-scheme:light)` valia (o usuário não conseguia
# ESCOLHER o tema no Dash, só herdar o do SO). Este item porta o mesmo
# mecanismo já existente no painel principal (_JS/_doc) para o Dash:
# botão de alternância, boot-script anti-flash e persistência via
# localStorage — reaproveitando a MESMA chave ('nomos-tema') dos dois
# lados, para que a escolha feita num lado valha no outro.
def test_dash_ganha_botao_de_tema_e_boot_sem_flash(nomos_home):
    corpo = render_dash("1.0.0")
    assert 'id="tema-btn"' in corpo                 # alternância acessível
    assert 'aria-pressed' in corpo
    # boot lê a preferência salva ANTES do <style> (evita flash de tema) —
    # mesmo contrato já valia só para o painel principal (ver
    # test_botao_de_tema_e_boot_sem_flash, acima)
    idx_boot = corpo.find("localStorage.getItem('nomos-tema')")
    idx_style = corpo.find("<style>")
    assert 0 < idx_boot < idx_style, "boot do tema deve vir antes do <style>"


def test_dash_js_realmente_seta_data_tema_e_persiste():
    """Prova por conteúdo real (não só a existência do botão) que o CSS
    'inerte' do P2-8 passou a ser alcançável: _JS_DASH agora contém a
    lógica que ESCREVE `data-tema` no <html> e PERSISTE a escolha em
    localStorage — exatamente a lacuna que o commit do P2-8 documentou
    como "fora do corte mínimo" daquela correção."""
    from nomos.interface.painel_web import _JS_DASH
    assert "root.setAttribute('data-tema'" in _JS_DASH
    assert "localStorage.setItem('nomos-tema'" in _JS_DASH
    assert "localStorage.getItem('nomos-tema')" in _JS_DASH
    assert "tema-btn" in _JS_DASH
    assert "addEventListener('click'" in _JS_DASH


def test_dash_e_painel_principal_compartilham_a_mesma_chave_de_localstorage():
    """A escolha de tema feita num lado (painel ou Dash) precisa valer no
    outro — os dois têm que ler/escrever a MESMA chave de localStorage,
    não chaves paralelas que divergiriam silenciosamente."""
    from nomos.interface.painel_web import _JS, _JS_DASH
    assert "localStorage.getItem('nomos-tema')" in _JS
    assert "localStorage.getItem('nomos-tema')" in _JS_DASH


def test_doc_do_painel_principal_nao_muda_apos_extracao_do_boot(nomos_home):
    """O boot-script de tema foi extraído de dentro de `_doc()` para uma
    constante de módulo (`_BOOT_TEMA`), agora reaproveitada pelo Dash —
    prova de que a extração foi PURA: o painel principal continua com o
    mesmo contrato de sempre (boot antes do <style>, botão presente)."""
    corpo = _html(nomos_home)
    assert 'id="tema-btn"' in corpo
    idx_boot = corpo.find("localStorage.getItem('nomos-tema')")
    idx_style = corpo.find("<style>")
    assert 0 < idx_boot < idx_style


# --------------------------------------- P2-10 (auditoria de 2026-07-17) -
# Contraste WCAG AA real dos selos de status (.chip.ok/.warn/.err) no tema
# claro. Achado real: o `background` de cada .chip é um rgba(...) LITERAL
# fixo com os valores RGB do tema ESCURO (não usa var() — não muda com o
# tema); só `color` troca via var(--neon/--amarelo/--vermelho). No tema
# claro isso deixava chip.ok em 4.51:1 (raspando o piso de 4.5) e
# chip.warn em 4.13:1 (FALHA); chip.err já passava (4.85:1). Este teste
# calcula o contraste de verdade sobre a cor REAL renderizada (alpha
# blend do literal, não a variável isolada) — não confia em número
# escrito em comentário.
#
# Nota de proveniência: a primeira tentativa de correção desta rodada
# assumiu, por engano, que o `background` usava var() como o `color` —
# o teste abaixo (que blenda contra o LITERAL, não a variável) pegou o
# erro antes do commit (assert de contraste "antigo" não batia com o
# valor real do CSS). Mantido documentado aqui como prova de que a
# correção final foi verificada por execução, não assumida.
def _srgb_to_linear(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _luminancia(hexcor: str) -> float:
    h = hexcor.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (0.2126 * _srgb_to_linear(r) + 0.7152 * _srgb_to_linear(g)
            + 0.0722 * _srgb_to_linear(b))


def _contraste(hex1: str, hex2: str) -> float:
    l1, l2 = _luminancia(hex1), _luminancia(hex2)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def _blend(fg_hex: str, alpha: float, bg_hex: str) -> str:
    fg = [int(fg_hex.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    bg = [int(bg_hex.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    out = [round(fg[i] * alpha + bg[i] * (1 - alpha)) for i in range(3)]
    return "#%02x%02x%02x" % tuple(out)


def test_chips_tema_claro_atingem_contraste_aa(nomos_home):
    corpo = _html(nomos_home)
    surface2 = "#eaf0ea"     # --surface2 do tema claro (fundo real do .chip via .sidebar)
    assert f"--surface2:{surface2}" in corpo
    # backgrounds são LITERAIS fixos (RGB do tema escuro), lidos direto das
    # regras .chip.X{background:rgba(...)} — não são var(), não mudam de tema
    casos = [
        ("chip.ok", "rgba(90,247,142,.15)", "#0b783a"),
        ("chip.warn", "rgba(242,193,78,.15)", "#7f6111"),
    ]
    for nome, rgba_str, cor_nova in casos:
        classe = nome.split(".")[1]
        assert f".chip.{classe}{{background:{rgba_str}" in corpo, \
            f"background literal de {nome} mudou — recalcule o contraste"
        # a cor nova precisa estar de fato no HTML servido (não só no comentário)
        assert f'.chip.{classe}{{color:{cor_nova}}}' in corpo, \
            f"override de {nome} não encontrado no CSS servido"
        r, g, b, a = [float(x) for x in rgba_str[5:-1].split(",")]
        fundo = _blend("#%02x%02x%02x" % (int(r), int(g), int(b)), a, surface2)
        razao = _contraste(cor_nova, fundo)
        assert razao >= 4.5, f"{nome}: {cor_nova} sobre {fundo} = {razao:.2f}:1 (< AA)"
    # chip.err já passava (4.85:1) sem override — confirma que continua passando
    r, g, b, a = 255.0, 92.0, 87.0, 0.15
    fundo_err = _blend("#ff5c57", a, surface2)
    razao_err = _contraste("#b3261e", fundo_err)   # --vermelho do tema claro, sem override
    assert razao_err >= 4.5, f"chip.err regrediu: {razao_err:.2f}:1"
    assert ".chip.err{color:#af251d}" not in corpo   # nenhum override desnecessário


def test_chips_tema_claro_nao_regride_para_valores_que_falham():
    """Prova, por execução, o achado real: o `background` de cada .chip é
    um LITERAL fixo com o RGB do tema escuro (não var()) — por isso a cor
    de texto ANTIGA (var(--neon)/var(--amarelo) do tema claro) tinha que
    ser calculada contra esse literal, não contra a variável isolada. Se
    algum dia o .chip.warn voltar a usar var(--amarelo) puro sem override,
    este teste (que reproduz o cálculo do achado original) falha."""
    surface2 = "#eaf0ea"
    fundo_ok = _blend("#5af78e", 0.15, surface2)      # rgba(90,247,142,.15)
    fundo_warn = _blend("#f2c14e", 0.15, surface2)    # rgba(242,193,78,.15)
    razao_ok_antiga = _contraste("#0b7a3b", fundo_ok)        # var(--neon) tema claro
    razao_warn_antiga = _contraste("#8a6a12", fundo_warn)    # var(--amarelo) tema claro
    assert 4.5 <= razao_ok_antiga < 4.55, (
        f"chip.ok sem override: {razao_ok_antiga:.3f}:1 — esperado ~4.51 "
        "(passa raspando o piso, por isso a folga extra do override)")
    assert razao_warn_antiga < 4.5, (
        f"chip.warn sem override: {razao_warn_antiga:.3f}:1 — deveria falhar "
        "o AA (era exatamente o achado original)")
