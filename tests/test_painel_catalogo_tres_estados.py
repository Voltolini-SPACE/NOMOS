"""O catálogo do painel mostra o que veio na caixa — sem dizer que está ativo.

Medido antes: `capacidades(home, skills_dir)` sem `incluir_do_pacote` devolve
0 numa instalação nova, e a tela dizia "catálogo vazio" com 33 skills dentro
do próprio wheel. Exigir `--semear` só para ENXERGAR o que já veio era o
oposto de plug-and-play.

A fronteira que este arquivo defende: **mostrar não é registrar nem
autorizar**. "vem no NOMOS" não pode ser lido como "está ativa".
"""
from __future__ import annotations



from nomos.interface import painel_web as pw


def _pagina(caps):
    return caps


def test_contrato_traz_as_empacotadas(tmp_path):
    """Sem o parâmetro: 0. Com ele: as que vieram no pacote."""
    from nomos.ext import skill_catalogo as sc
    sem = sc.capacidades(tmp_path, tmp_path / "skills")
    com = sc.capacidades(tmp_path, tmp_path / "skills", incluir_do_pacote=True)
    assert sem == [], "home vazia devia ser vazia sem o parâmetro"
    assert len(com) > 0, "o pacote traz skills e elas têm de aparecer"
    # ANTES afirmava um status unico. Virou falso quando as skills sem codigo
    # publicado ganharam "em preparacao" — o teste congelava um fato vencido.
    assert all("vem no NOMOS" in str(c["status"]) for c in com)
    assert len({c["status"] for c in com}) >= 1


def test_painel_pede_as_empacotadas(tmp_path):
    """A tela tem de passar o parâmetro — senão nasce vazia mentindo."""
    d = pw.dados_dashboard({"home": tmp_path, "skills": tmp_path / "skills"})
    assert d["capacidades"], "o painel continua chamando sem incluir_do_pacote"


def test_mostrar_nao_e_autorizar(tmp_path):
    """A garantia que sustenta a decisão de mostrar: nada foi registrado."""
    pw.dados_dashboard({"home": tmp_path, "skills": tmp_path / "skills"})
    assert not (tmp_path / "registry" / "catalogo.json").exists()
    assert not (tmp_path / "skills").exists() or \
        list((tmp_path / "skills").glob("*")) == []


def test_cada_estado_diz_o_que_significa(tmp_path):
    d = pw.dados_dashboard({"home": tmp_path, "skills": tmp_path / "skills"})
    html = pw.render_html(d)
    assert "vem no NOMOS" in html
    # a frase que impede a leitura errada
    assert "ainda NÃO estão instaladas" in html
    assert "não porque estejam ativas" in html


def test_mostra_o_que_a_skill_toca(tmp_path):
    """Risco sem permissões é rótulo; com permissões é informação."""
    d = pw.dados_dashboard({"home": tmp_path, "skills": tmp_path / "skills"})
    html = pw.render_html(d)
    assert "toca:" in html


def test_estado_desconhecido_nao_some_da_tela(tmp_path):
    """Se o contrato ganhar um estado novo, ele aparece em vez de sumir —
    lista que filtra por lista fixa esconde o que não previu."""
    d = pw.dados_dashboard({"home": tmp_path, "skills": tmp_path / "skills"})
    d["capacidades"] = list(d["capacidades"]) + [
        {"nome": "z", "status": "estado-do-futuro", "risco": "baixo",
         "descricao": "", "entrada": "", "saida": "", "permissoes": []}]
    html = pw.render_html(d)
    assert "estado-do-futuro" in html
    assert ">z <span" in html          # card completo, nao nome nu
    assert "risco" in html


def test_contrato_antigo_nao_derruba_o_painel(tmp_path, monkeypatch):
    """Instalação sem o parâmetro novo: degrada, não quebra."""
    from nomos.ext import skill_catalogo as sc

    def so_antigo(home, skills_dir, **kw):
        if kw:
            raise TypeError("incluir_do_pacote não existe nesta versão")
        return []

    monkeypatch.setattr(sc, "capacidades", so_antigo)
    d = pw.dados_dashboard({"home": tmp_path, "skills": tmp_path / "skills"})
    assert d["capacidades"] == []


# --------------------------------------------------------------------------
# Permissão em código é honesta e ilegível — o que na prática é meia-honestidade
# --------------------------------------------------------------------------
def test_permissao_ganha_texto_em_portugues():
    html = pw._permissoes_legiveis(["A2_NET_EGRESS", "A5_CODE_EXEC"])
    assert "fala com a internet" in html
    assert "inicia outros programas" in html
    assert "A2_NET_EGRESS" in html      # o código continua, para quem o usa


def test_permissao_desconhecida_nao_some():
    """Sumir esconderia justamente a permissão que o vocabulário não previu."""
    html = pw._permissoes_legiveis(["A9_ALGO_NOVO"])
    assert "A9_ALGO_NOVO" in html


def test_sem_permissao_diz_travessao():
    assert pw._permissoes_legiveis([]) == "—"
    assert pw._permissoes_legiveis(None) == "—"


def test_credencial_nao_promete_cofre_que_nao_governa():
    """A frase era "usam credencial DO COFRE" e prometia governanca que o
    NOMOS nao da. Medido: o cofre tem 1 chave (omniroute_api_key) e a
    intersecao com as 9 que as skills pedem e VAZIA — elas moram no `gh`, em
    sessao de navegador, no login da Higgsfield. O numero nao muda; o que
    muda e o dono descobrir que instalar nao basta."""
    caps = [{"permissoes": ["A3_CRED_USE"]} for _ in range(19)]
    html = pw._resumo_permissoes(caps, (9, 0, 0))
    # O guard proibe a AFIRMACAO falsa, nao a palavra: "usam credencial do
    # cofre" alega que ELAS ESTAO la. Dizer "seriam do cofre — nenhuma esta
    # la" usa as mesmas palavras para dizer o oposto, e e util. Banir o
    # vocabulario me faria reprovar o texto certo.
    assert "usam credencial do cofre" not in html
    assert "está lá" in html or "está(ão)" in html
    assert "pedem credencial" in html
    assert "nenhuma está lá" in html


def test_credencial_conta_as_que_ESTAO_no_cofre():
    """Se o dono guardar algumas, a frase acompanha — o numero e amarrado ao
    fato, nao a uma constante que envelhece."""
    caps = [{"permissoes": ["A3_CRED_USE"]} for _ in range(19)]
    html = pw._resumo_permissoes(caps, (9, 3, 0))
    assert "3 já está(ão)" in html
    assert "nenhuma está lá" not in html


def test_sem_dado_de_cofre_nao_inventa():
    """Sem a medicao, diz so o que sabe — nao chuta 'nenhuma'."""
    caps = [{"permissoes": ["A3_CRED_USE"]}]
    html = pw._resumo_permissoes(caps, None)
    assert "pedem credencial" in html
    assert "cofre" not in html


def test_contagem_separa_chave_de_credencial_externa(tmp_path):
    """Os manifestos distinguem `chave` (API key — o cofre E o lugar dela) de
    `credencial_externa` (login de app, sessao de navegador — o NOMOS nao tem
    onde guardar). Somar num numero so esconderia que metade nao tem conserto
    pelo cofre. Este teste ja pegou uma reclassificacao real: 13 requisitos
    mudaram de `chave` para `credencial_externa` e a minha contagem caiu
    sozinha, revelando que eu media a coisa errada."""
    chaves, no_cofre, externas = pw._credenciais_pedidas(tmp_path)
    assert chaves >= 1, "nenhuma chave contada — provavelmente ignorou os cruas"
    assert externas >= 1, "nenhuma credencial externa contada"
    assert no_cofre == 0, "home de teste nao tem cofre"


def test_texto_nao_promete_cofre_para_login_de_app(tmp_path):
    """Login de app nao vai para o cofre; dizer o contrario seria a mesma
    meia-verdade do 'credencial do cofre' original."""
    caps = [{"permissoes": ["A3_CRED_USE"]} for _ in range(17)]
    html = pw._resumo_permissoes(caps, (3, 0, 5))
    assert "3 seria(m) do cofre" in html
    assert "nenhuma está lá" in html
    assert "5 são login/sessão, que o NOMOS não guarda" in html


def test_resumo_da_a_forma_antes_da_lista():
    """33 fichas em sequência não respondem 'o que entrou em casa?'."""
    caps = [{"permissoes": ["A2_NET_EGRESS"]} for _ in range(26)]
    caps += [{"permissoes": ["A5_CODE_EXEC"]} for _ in range(3)]
    caps += [{"permissoes": ["A3_CRED_USE"]}]
    html = pw._resumo_permissoes(caps, (9, 0, 0))
    assert "26</b> falam com a internet" in html
    assert "3</b> iniciam outros programas" in html
    # este teste guardava "1 usam credencial DO COFRE" — a frase que prometia
    # governança inexistente. Um teste que congela texto vencido defende o
    # erro com a autoridade de uma suíte verde.
    assert "1</b> pedem credencial" in html
    assert "usam credencial do cofre" not in html
    # a garantia junto do número, senão o número assusta sem contexto
    assert "nada disso acontece sem você instalar e aprovar" in html


def test_resumo_omite_o_que_e_zero():
    html = pw._resumo_permissoes([{"permissoes": ["A2_NET_EGRESS"]}])
    assert "falam com a internet" in html
    assert "iniciam outros programas" not in html


def test_resumo_vazio_nao_polui():
    assert pw._resumo_permissoes([]) == ""
    assert pw._resumo_permissoes([{"permissoes": []}]) == ""


def test_a5_e_a4_contam_juntos():
    """Duas grafias para a mesma ideia; o dono lê UMA contagem."""
    caps = [{"permissoes": ["A4_PROC_SPAWN"]}, {"permissoes": ["A5_CODE_EXEC"]}]
    assert "2</b> iniciam outros programas" in pw._resumo_permissoes(caps)
