"""ABSORPTION-06 / GATE C — autoridade não sobe por coerção de argumento.

O censo adversarial achou, e a verificação independente confirmou: um plano que
escrevia `{"recursivo": "nao"}` — querendo dizer **não** — apagava a árvore
inteira, porque `bool("nao")` é `True`. O efeito era irreversível e a aprovação
que o dono via dizia "A1 · escrever arquivos locais", já que a categoria de
risco vem da CAPACIDADE, não do argumento.

Duas correções, de naturezas diferentes:

1. **Validação estrita** (`adapters.estrito`): argumento de plano não é
   interpretado por verdade do Python. Ou está no contrato, ou é
   `VALIDATION_ERROR` — antes de qualquer efeito.
2. **Separação de autoridade**: apagar árvore virou `fs-apagar-arvore`, com
   `A6_DESTRUCTIVE`. Isso é mais forte que validar o booleano, porque remove o
   booleano: não existe campo capaz de elevar autoridade quando a autoridade
   está no NOME da capacidade que o dono aprovou.

Todos os testes daqui partem de PLANO (`rt.rodar`), não do adapter. Testar o
adapter direto responderia "a função se comporta?"; a pergunta que importa é
"o que um plano consegue fazer?".
"""
from __future__ import annotations

import json
import sys

import pytest

from nomos.kernel.audit import AuditLog
from nomos.kernel.policy import Category, PolicyEngine
from nomos.runtime.governado import RuntimeGovernado

# Tudo que um plano poderia escrever achando que diz "não", ou por engano.
# Todos são truthy em Python; nenhum pode virar autoridade.
NAO_BOOLEANOS = ["nao", "não", "false", "False", "0", "no", "off", "sim",
                 "yes", "1", 0, 1, [], {}, [1], {"a": 1}, 0.0, "true"]


def _sim(_d):
    return True


@pytest.fixture()
def amb(tmp_path):
    home = tmp_path / "h"
    home.mkdir()
    ws = tmp_path / "ws"
    ws.mkdir()
    ctx = {"home": home, "policy": PolicyEngine(home / "policy.json"),
           "audit": AuditLog(home / "logs" / "audit.jsonl")}
    rt = RuntimeGovernado(ctx, _sim, caminhos=(str(ws),), adapters=True,
                          executaveis=(sys.executable,))
    return rt, ws, ctx


def _arvore(ws, nome="arvore"):
    raiz = ws / nome
    (raiz / "sub").mkdir(parents=True)
    (raiz / "a.txt").write_text("conteudo A")
    (raiz / "sub" / "b.txt").write_text("conteudo B")
    return raiz


def _plano(rt, ferramenta, **params):
    return rt.rodar("gate-c", passos=[{"id": "p", "ferramenta": ferramenta,
                                       "params": params}])


# ============================================ C5.1-C5.2 — o defeito original

@pytest.mark.parametrize("valor", NAO_BOOLEANOS)
def test_c51_recursivo_nao_booleano_nunca_apaga_arvore(amb, valor):
    """VALIDATION_ERROR e MUTATION_OCCURRED=FALSE, para todo valor do contrato.

    Parametrizado sobre a lista inteira de propósito: o defeito não era
    `"nao"` especificamente, era QUALQUER coisa não-booleana virar verdade.
    Testar só `"nao"` deixaria `"false"` passando.
    """
    rt, ws, _ = amb
    raiz = _arvore(ws, f"t{abs(hash(str(valor))) % 9999}")
    res = _plano(rt, "fs-apagar", alvo=str(raiz), recursivo=valor)
    assert not res.ok, f"{valor!r} foi ACEITO em fs-apagar"
    assert raiz.exists(), f"TREE_PRESERVED=FALSE — {valor!r} apagou a árvore"
    assert (raiz / "sub" / "b.txt").exists()


def test_c53_booleano_falso_de_verdade_nao_apaga(amb):
    """`false` real: recusado por ser argumento inexistente nesta capacidade.

    Poderia ser aceito e ignorado, mas ignorar é o que faz o plano acreditar
    que pediu algo. `fs-apagar` não tem esse campo — dizer isso é mais honesto
    que aceitar em silêncio.
    """
    rt, ws, _ = amb
    raiz = _arvore(ws)
    res = _plano(rt, "fs-apagar", alvo=str(raiz), recursivo=False)
    assert not res.ok
    assert raiz.exists()


def test_c54_apagar_arvore_nem_EXISTE_por_padrao(amb):
    """Resultado mais forte do que eu tinha desenhado, por TRÊS travas.

    1. `A6_DESTRUCTIVE` é `DENY` na política padrão do kernel — não
       `REQUIRE_APPROVAL`;
    2. o manifesto do runtime declara teto `A5`, então o PDP recusaria com
       `risco_acima_do_autorizado` mesmo se a política liberasse;
    3. e por isso a capacidade nem é REGISTRADA sem opt-in: registrá-la
       assim produziria capacidade anunciada e inalcançável, que é o defeito
       que o censo achou no scheduler.

    Apagar árvore saiu de "aprovado sob o rótulo de escrever arquivo" para
    "não existe até o dono pedir, e mesmo então precisa da política".
    """
    rt, ws, _ = amb
    raiz = _arvore(ws)
    assert "fs-apagar-arvore" not in rt.capacidades_adapter
    res = _plano(rt, "fs-apagar-arvore", alvo=str(raiz))
    assert not res.ok, "A6 destrutiva executou sem decisão explícita do dono"
    assert raiz.exists(), "TREE_PRESERVED=FALSE sob configuração padrão"


def test_c54_teto_do_manifesto_barra_a6_mesmo_com_politica_liberada(amb):
    """A segunda trava, isolada: política liberada NÃO basta."""
    rt, ws, ctx = amb
    raiz = _arvore(ws)
    ctx["policy"] = _liberar_a6(ctx)
    # runtime SEM `destrutivas=True`: teto do manifesto continua A5
    rt2 = RuntimeGovernado(ctx, _sim, caminhos=(str(ws),), adapters=True,
                           destrutivas=False)
    assert "fs-apagar-arvore" not in rt2.executores
    assert rt2.manifesto.risco_max == "A5"
    assert raiz.exists()


def _liberar_a6(ctx):
    """O dono decide, explicitamente, permitir A6. É o único caminho."""
    import json as _json
    caminho = ctx["policy"].path
    dados = _json.loads(caminho.read_text())
    dados["rules"]["A6_DESTRUCTIVE"] = "REQUIRE_APPROVAL"
    caminho.write_text(_json.dumps(dados))
    from nomos.kernel.policy import PolicyEngine
    return PolicyEngine(caminho)


def test_c54b_com_decisao_explicita_do_dono_a_arvore_e_apagada(amb):
    """A capacidade FUNCIONA — mas só depois de o dono mudar a política."""
    rt, ws, ctx = amb
    raiz = _arvore(ws)
    ctx["policy"] = _liberar_a6(ctx)
    rt2 = RuntimeGovernado(ctx, _sim, caminhos=(str(ws),), adapters=True,
                           destrutivas=True)
    res = rt2.rodar("gate-c", passos=[{"id": "p",
                                       "ferramenta": "fs-apagar-arvore",
                                       "params": {"alvo": str(raiz)}}])
    assert res.ok, res.motivo
    assert not raiz.exists(), "a capacidade destrutiva não apagou"


def test_c55_sem_campo_o_padrao_e_seguro(amb):
    """DEFAULT_SAFE: sem `recursivo`, diretório não-vazio NÃO é apagado."""
    rt, ws, _ = amb
    raiz = _arvore(ws)
    res = _plano(rt, "fs-apagar", alvo=str(raiz))
    assert not res.ok, "diretório não-vazio foi apagado sem pedir árvore"
    assert raiz.exists()


def test_c55b_apagar_arquivo_e_dir_vazio_continua_funcionando(amb):
    """A separação não pode ter quebrado o uso legítimo de `fs-apagar`."""
    rt, ws, _ = amb
    arq = ws / "solto.txt"
    arq.write_text("x")
    vazio = ws / "vazio"
    vazio.mkdir()
    assert _plano(rt, "fs-apagar", alvo=str(arq)).ok
    assert not arq.exists()
    assert _plano(rt, "fs-apagar", alvo=str(vazio)).ok
    assert not vazio.exists()


# ============================================ C4 — autoridade separada

def test_c4_categorias_de_risco_sao_diferentes(amb):
    """`rmtree` e "criar um arquivo" não podem pedir a mesma autorização."""
    _rt0, ws, ctx = amb
    rt = RuntimeGovernado(ctx, _sim, caminhos=(str(ws),), adapters=True,
                          destrutivas=True)
    comum = rt.registro.categoria_de("fs-apagar")
    destrutiva = rt.registro.categoria_de("fs-apagar-arvore")
    assert comum is Category.WRITE_LOCAL
    assert destrutiva is Category.DESTRUCTIVE
    assert comum is not destrutiva


def test_c4_mensagem_de_aprovacao_descreve_o_efeito_real(amb):
    """A frase que o dono lê tem de falar de destruição.

    Antes, apagar uma árvore pedia aprovação dizendo "A1 · escrever arquivos
    locais". Aprovação que descreve o efeito errado não é aprovação informada —
    é assinatura em papel em branco.
    """
    from nomos.kernel.policy import rotulo_categoria
    _rt0, ws, ctx = amb
    rt = RuntimeGovernado(ctx, _sim, caminhos=(str(ws),), adapters=True,
                          destrutivas=True)
    texto = rotulo_categoria(rt.registro.categoria_de("fs-apagar-arvore"))
    assert "destrutiva" in texto.lower(), texto
    comum = rotulo_categoria(rt.registro.categoria_de("fs-apagar"))
    assert "escrever arquivos locais" in comum.lower()
    assert texto != comum


def test_c4_arvore_destrutiva_esta_sob_pdp_e_pep(amb):
    """Categoria nova não pode ter nascido fora da cadeia."""
    rt0, ws, ctx = amb
    rt = RuntimeGovernado(ctx, _sim, caminhos=(str(ws),), adapters=True,
                          destrutivas=True)
    from nomos.pdp.pep import PontoDeAplicacao
    assert isinstance(rt.executores_protegidos["fs-apagar-arvore"],
                      PontoDeAplicacao)
    assert "fs-apagar-arvore" in rt.autorizacao.capacidades


def test_c4_efeito_destrutivo_deixa_pdp_pep_e_trilha(amb):
    rt, ws, ctx = amb
    raiz = _arvore(ws)
    ctx["policy"] = _liberar_a6(ctx)
    rt = RuntimeGovernado(ctx, _sim, caminhos=(str(ws),), adapters=True,
                          destrutivas=True)
    assert _plano(rt, "fs-apagar-arvore", alvo=str(raiz)).ok
    ev = [json.loads(x).get("event") for x in
          (ctx["home"] / "logs" / "audit.jsonl").read_text().splitlines()
          if x.strip()]
    assert ev.index("pdp.decisao") < ev.index("pep.aplicacao") < ev.index("fs.apagar")


def test_c4_arvore_fora_da_raiz_e_negada(amb, tmp_path):
    """Autoridade destrutiva não amplia ESCOPO."""
    rt0, ws, ctx = amb
    ctx["policy"] = _liberar_a6(ctx)
    rt = RuntimeGovernado(ctx, _sim, caminhos=(str(ws),), adapters=True,
                          destrutivas=True)
    fora = tmp_path / "fora"
    (fora / "sub").mkdir(parents=True)
    (fora / "sub" / "isca.txt").write_text("NAO PODE SUMIR")
    res = _plano(rt, "fs-apagar-arvore", alvo=str(fora))
    assert not res.ok
    assert (fora / "sub" / "isca.txt").exists(), "OUTSIDE_ROOT_MUTATION=TRUE"


def test_c4_apagar_arvore_recusa_arquivo_simples(amb):
    """Capacidade destrutiva não vira atalho para o caso comum."""
    rt0, ws, ctx = amb
    ctx["policy"] = _liberar_a6(ctx)
    rt = RuntimeGovernado(ctx, _sim, caminhos=(str(ws),), adapters=True,
                          destrutivas=True)
    arq = ws / "simples.txt"
    arq.write_text("x")
    res = _plano(rt, "fs-apagar-arvore", alvo=str(arq))
    assert not res.ok
    assert arq.exists()


# ============================================ C5.6 — outros tipos inválidos

@pytest.mark.parametrize("campo,valor", [
    ("offset", "abc"), ("offset", "1"), ("offset", True), ("offset", 1.5),
    ("limite", "xyz"), ("limite", True), ("limite", []), ("limite", -1),
])
def test_c56_offset_e_limite_recusam_tipo_invalido_com_erro_tipado(amb, campo,
                                                                   valor):
    """`int("abc")` deixava ValueError CRU escapar do adapter.

    Exceção não tipada atravessando a cadeia vira FAILED com efeito
    DESCONHECIDO — e, no scheduler, já foi causa de queda de ticker. O
    contrato do adapter promete erro tipado; agora ele cumpre.
    """
    rt, ws, _ = amb
    arq = ws / "leitura.txt"
    arq.write_text("l1\nl2\nl3\n")
    res = _plano(rt, "fs-ler", alvo=str(arq), **{campo: valor})
    assert not res.ok, f"{campo}={valor!r} foi aceito"
    no = res.missao.nos.get("p")
    assert "ValueError" not in (no.detalhe or ""), (
        f"exceção NÃO TIPADA escapou: {no.detalhe}")


def test_c56_offset_e_limite_validos_continuam_funcionando(amb):
    rt, ws, _ = amb
    arq = ws / "leitura.txt"
    arq.write_text("l1\nl2\nl3\nl4\n")
    res = _plano(rt, "fs-ler", alvo=str(arq), offset=1, limite=2)
    assert res.ok, res.motivo
    assert res.missao.nos["p"].resultado == "l2\nl3"


@pytest.mark.parametrize("valor", ["nao", "true", "0", 1, [], {}])
def test_c56_recursivo_do_listar_tambem_e_estrito(amb, valor):
    """Leitura não muda autoridade, mas `"nao"` faria `rglob` e devolveria a
    árvore a quem pediu um nível. Mesma coerção, consequência menor."""
    rt, ws, _ = amb
    _arvore(ws)
    res = _plano(rt, "fs-listar", alvo=str(ws), recursivo=valor)
    assert not res.ok, f"recursivo={valor!r} aceito no listar"


def test_c56_listar_recursivo_booleano_de_verdade_funciona(amb):
    rt, ws, _ = amb
    _arvore(ws)
    raso = _plano(rt, "fs-listar", alvo=str(ws), recursivo=False)
    fundo = _plano(rt, "fs-listar", alvo=str(ws), recursivo=True)
    assert raso.ok and fundo.ok
    assert len(fundo.missao.nos["p"].resultado) > len(raso.missao.nos["p"].resultado)


# ============================================ a camada estrita, isolada

@pytest.mark.parametrize("valor", NAO_BOOLEANOS)
def test_bool_estrito_recusa_tudo_que_nao_e_booleano(valor):
    from nomos.adapters.contrato import ErroInvalido
    from nomos.adapters.estrito import bool_estrito
    with pytest.raises(ErroInvalido, match="booleano"):
        bool_estrito(valor, "campo")


def test_bool_estrito_aceita_booleano_e_ausencia():
    from nomos.adapters.estrito import bool_estrito
    assert bool_estrito(True, "c") is True
    assert bool_estrito(False, "c") is False
    assert bool_estrito(None, "c") is False
    assert bool_estrito(None, "c", padrao=True) is True


def test_inteiro_estrito_recusa_bool_que_e_int_em_python():
    """`isinstance(True, int)` é verdadeiro: `{"limite": true}` viraria 1."""
    from nomos.adapters.contrato import ErroInvalido
    from nomos.adapters.estrito import inteiro_estrito
    with pytest.raises(ErroInvalido, match="inteiro"):
        inteiro_estrito(True, "limite")
    assert inteiro_estrito(3, "limite") == 3
    assert inteiro_estrito(None, "limite") is None


def test_numero_estrito_recusa_nan_e_bool():
    from nomos.adapters.contrato import ErroInvalido
    from nomos.adapters.estrito import numero_estrito
    with pytest.raises(ErroInvalido, match="NaN"):
        numero_estrito(float("nan"), "t")
    with pytest.raises(ErroInvalido, match="número"):
        numero_estrito(True, "t")
    assert numero_estrito(1.5, "t") == 1.5


def test_c53b_recursivo_e_recusado_mesmo_quando_o_alvo_e_ARQUIVO(amb):
    """O alvo importa para a prova ter dentes.

    Mutação achou: com árvore NÃO-VAZIA, remover a recusa de `recursivo` não
    muda o resultado observável — `rmdir()` falha sozinho por o diretório não
    estar vazio, e o teste passa pelo motivo errado. Num ARQUIVO, `unlink()`
    funcionaria, então só a recusa explícita impede o efeito. É esse alvo que
    separa "recusou porque a defesa existe" de "falhou por acidente".
    """
    rt, ws, _ = amb
    arq = ws / "com-argumento-errado.txt"
    arq.write_text("importante")
    res = _plano(rt, "fs-apagar", alvo=str(arq), recursivo=True)
    assert not res.ok, "argumento estranho foi ACEITO em fs-apagar"
    assert arq.exists(), "arquivo apagado apesar do argumento inválido"
    assert "recursivo" in (res.missao.nos["p"].detalhe or "")


def test_c53c_dir_vazio_com_recursivo_tambem_e_recusado(amb):
    """Mesma lógica: `rmdir()` de diretório vazio funcionaria."""
    rt, ws, _ = amb
    vazio = ws / "vazio-mas-com-argumento"
    vazio.mkdir()
    res = _plano(rt, "fs-apagar", alvo=str(vazio), recursivo=False)
    assert not res.ok
    assert vazio.exists()
