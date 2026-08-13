"""ABSORPTION-06 / P3 — o plano é entrada hostil, e a ambiguidade é recusada.

Três classes de ataque, com defesas DIFERENTES. Mantidas separadas de propósito:
um teste que cobrisse as três de uma vez daria a impressão de que uma defesa
cobre as outras, e nenhuma cobre.

**1. Chave duplicada no JSON BRUTO.** `json.loads` aceita
`{"alvo":"A","alvo":"B"}` e devolve `{"alvo":"B"}` — a última vence, calada.
Depois que o `dict` existe, a ambiguidade já foi resolvida e é indetectável:
o campo tem um valor só. A defesa precisa rodar DURANTE a desserialização.

**2. Alias semântico.** `{"alvo":"A","target":"B"}` não é duplicata para o
JSON: são chaves distintas. É ambiguidade de significado, e normalizar
escolhendo uma faz o sistema decidir qual das duas o autor quis.

**3. Confusão de tipo.** `isinstance(True, int)` é verdadeiro em Python, então
`{"limite": true}` vira "1" num campo numérico. Booleano onde se espera número
é elevação silenciosa de domínio.

E os caminhos: containment tem de valer sobre o recurso RESOLVIDO, não sobre a
string — e `resolve()` cedo demais não basta se o caminho puder ser trocado
antes do efeito.
"""
from __future__ import annotations

import json
import threading

import pytest

from nomos.kernel.audit import AuditLog
from nomos.kernel.policy import PolicyEngine
from nomos.orquestracao.entrada import ErroEntrada, carregar_plano, validar_params
from nomos.runtime.governado import ErroRuntime, RuntimeGovernado


def _sim(_d):
    return True


@pytest.fixture()
def amb(tmp_path):
    home = tmp_path / "h"
    home.mkdir()
    ws = tmp_path / "ws"
    ws.mkdir()
    fora = tmp_path / "fora"
    fora.mkdir()
    (fora / "segredo.txt").write_text("SEGREDO-FORA-DA-RAIZ")
    ctx = {"home": home, "policy": PolicyEngine(home / "policy.json"),
           "audit": AuditLog(home / "logs" / "audit.jsonl")}
    rt = RuntimeGovernado(ctx, _sim, caminhos=(str(ws),), adapters=True)
    return rt, ws, fora, home


def _plano(rt, **params):
    return rt.rodar("p3", passos=[{"id": "p", "ferramenta": "fs-ler",
                                   "params": params}])


# ============================== 1. RAW_DUPLICATE_JSON_KEYS_ACCEPTED=FALSE

DUPLICATAS_RAIZ = [
    '{"alvo":"A","alvo":"B"}',
    '{"_sujeito":"A","_sujeito":"B"}',
    '{"capability":"x","capability":"y"}',
    '{"risk_class":"baixo","risk_class":"alto"}',
    '{"escopo_dados":["a"],"escopo_dados":["/"]}',
    '{"policy_version":"1","policy_version":"2"}',
    '{"approval_id":"A","approval_id":"B"}',
]


@pytest.mark.parametrize("bruto", DUPLICATAS_RAIZ)
def test_p3_duplicata_no_json_bruto_e_recusada(bruto):
    """A propriedade só é verificável ANTES do `dict` existir."""
    with pytest.raises(ErroEntrada, match="duplicada"):
        carregar_plano(bruto)


def test_p3_json_loads_puro_ACEITARIA_a_duplicata():
    """Prova de que a defesa não é redundante.

    Sem este teste, alguém poderia concluir que o `object_pairs_hook` é
    cerimônia — afinal "JSON não permite chave repetida". Permite: o parser do
    Python aceita e escolhe a última, calado.
    """
    assert json.loads('{"alvo":"A","alvo":"B"}') == {"alvo": "B"}


@pytest.mark.parametrize("bruto", [
    '{"passos":[{"params":{"alvo":"A","alvo":"B"}}]}',
    '{"a":{"b":{"c":{"_sujeito":"x","_sujeito":"y"}}}}',
    '[{"id":"p","params":{"capability":"a","capability":"b"}}]',
    '{"lista":[1,2,{"alvo":"A","alvo":"B"}]}',
])
def test_p3_duplicata_ANINHADA_tambem_e_recusada(bruto):
    """Checar só a raiz deixaria o caso realmente perigoso passar: `params`
    fica sempre aninhado dentro do passo."""
    with pytest.raises(ErroEntrada, match="duplicada"):
        carregar_plano(bruto)


def test_p3_json_valido_sem_duplicata_continua_passando():
    dados = carregar_plano('[{"id":"p","ferramenta":"fs-ler",'
                           '"params":{"alvo":"/ws/a.txt"}}]')
    assert dados[0]["params"]["alvo"] == "/ws/a.txt"


def test_p3_cli_recusa_plano_com_duplicata():
    """A defesa precisa estar no caminho de PRODUÇÃO, não só no módulo."""
    from nomos.cli import _passos_de_json
    assert _passos_de_json('[{"id":"p","params":{"alvo":"A","alvo":"B"}}]') is None
    assert _passos_de_json('[{"id":"p","params":{"alvo":"A"}}]') is not None


# ============================== 2. SEMANTIC_AUTHORITY_ALIASES_ACCEPTED=FALSE

ALIASES = [
    ("alvo + target", {"alvo": "/ws/a", "target": "/etc/passwd"}),
    ("_sujeito + subject", {"_sujeito": "a", "subject": "dono"}),
    ("cwd + raiz", {"cwd": "/ws", "raiz": "/"}),
    ("root + raiz", {"root": "/ws", "raiz": "/"}),
    ("capability + capability_id", {"capability": "fs-ler",
                                    "capability_id": "fs-apagar"}),
    ("executor + backend", {"executor": "a", "backend": "b"}),
    ("risco + risk_class", {"risco": "A0", "risk_class": "A5"}),
    ("policy + policy_version", {"policy": "1", "policy_version": "2"}),
    ("escopo_dados + data_scope", {"escopo_dados": ["/ws"],
                                   "data_scope": ["/"]}),
    ("timeout + timeout_s", {"timeout": 1, "timeout_s": 999}),
]


@pytest.mark.parametrize("rotulo,params", ALIASES, ids=[r for r, _ in ALIASES])
def test_p3_alias_de_autoridade_e_recusado(rotulo, params):
    """Não normalizar: recusar. Escolher uma faz o sistema decidir o que o
    autor quis, e a resposta errada é indistinguível da certa."""
    with pytest.raises(ErroEntrada, match="ambígua"):
        validar_params([{"id": "p", "params": params}])


def test_p3_alias_recusado_tambem_pela_cadeia_de_producao(amb):
    rt, ws, fora, _ = amb
    with pytest.raises(ErroRuntime, match="ambígua"):
        rt.rodar("p3", passos=[{"id": "p", "ferramenta": "fs-ler",
                                "params": {"alvo": str(ws / "a.txt"),
                                           "target": str(fora / "segredo.txt")}}])


def test_p3_um_membro_do_grupo_sozinho_continua_valido(amb):
    """A defesa não pode ter proibido o uso normal."""
    rt, ws, _fora, _ = amb
    alvo = ws / "a.txt"
    alvo.write_text("conteudo")
    assert _plano(rt, alvo=str(alvo)).ok


def test_p3_aliases_em_objetos_diferentes_nao_colidem():
    """`alvo` num passo e `target` noutro não é ambiguidade — são operações
    distintas. Recusar isso seria falso positivo."""
    validar_params([{"id": "a", "params": {"alvo": "/ws/x"}},
                    {"id": "b", "params": {"target": "/ws/y"}}])


# ============================== 3. TYPE_CONFUSION_ESCALATION=FALSE

HOSTIS = [None, True, False, 0, 1, "0", "1", [], {}, ["valor"], {"valor": "x"}]


@pytest.mark.parametrize("valor", HOSTIS, ids=[repr(v) for v in HOSTIS])
def test_p3_alvo_com_tipo_hostil_nao_executa(amb, valor):
    rt, _ws, _fora, _ = amb
    res = _plano(rt, alvo=valor)
    assert not res.ok, f"alvo={valor!r} foi aceito"


@pytest.mark.parametrize("valor", [True, False])
def test_p3_bool_nao_passa_por_inteiro(amb, valor):
    """BOOL_AS_INT_AUTHORITY_ACCEPTED=FALSE.

    `isinstance(True, int)` é verdadeiro: sem recusa explícita, `{"limite":
    true}` viraria "1 linha" e `{"offset": true}` viraria "pule 1".
    """
    from nomos.adapters.contrato import ErroInvalido
    from nomos.adapters.estrito import inteiro_estrito, numero_estrito
    with pytest.raises(ErroInvalido, match="inteiro"):
        inteiro_estrito(valor, "limite")
    with pytest.raises(ErroInvalido, match="número"):
        numero_estrito(valor, "timeout_s")


def test_p3_plano_nao_escolhe_executor(amb):
    """PLAN_CAN_SELECT_EXECUTOR=FALSE — o executor vem do REGISTRO."""
    rt, ws, _fora, _ = amb
    alvo = ws / "a.txt"
    alvo.write_text("x")
    res = rt.rodar("p3", passos=[{"id": "p", "ferramenta": "fs-ler",
                                  "params": {"alvo": str(alvo),
                                             "executor": "/bin/sh"}}])
    # o campo não é reconhecido como autoridade: é ignorado pelo adapter, e o
    # que importa é que não muda QUEM executa
    if res.ok:
        assert res.missao.nos["p"].resultado == "x"


def test_p3_plano_nao_baixa_a_classe_de_risco(amb):
    """PLAN_CAN_LOWER_RISK=FALSE — a categoria vem do registro, sempre."""
    from nomos.kernel.policy import Category
    rt, ws, _fora, _ = amb
    alvo = ws / "b.txt"
    plano = rt.planejar("p3", passos=[
        {"id": "p", "ferramenta": "fs-escrever",
         "params": {"alvo": str(alvo), "conteudo": "x"},
         "risco": "A0_READ_LOCAL"}])
    assert plano.risco != "A0_READ_LOCAL" or plano.risco == "A1_WRITE_LOCAL"
    assert rt.registro.categoria_de("fs-escrever") is Category.WRITE_LOCAL


def test_p3_plano_nao_expande_o_escopo(amb):
    """PLAN_CAN_EXPAND_SCOPE=FALSE."""
    rt, _ws, fora, _ = amb
    for campo in ("escopo_dados", "data_scope", "raiz", "root"):
        res = _plano(rt, alvo=str(fora / "segredo.txt"), **{campo: "/"})
        assert not res.ok, f"'{campo}' do plano expandiu o escopo"


def test_p3_plano_nao_sobrescreve_a_politica(amb):
    """PLAN_CAN_OVERRIDE_POLICY=FALSE."""
    rt, ws, _fora, home = amb
    alvo = ws / "c.txt"
    politica = (home / "policy.json").read_text()
    rt.rodar("p3", passos=[{"id": "p", "ferramenta": "fs-escrever",
                            "params": {"alvo": str(alvo), "conteudo": "x",
                                       "policy": '{"rules":{}}'}}])
    assert (home / "policy.json").read_text() == politica


def test_p3_plano_nao_forja_aprovacao(amb):
    """PLAN_CAN_FORGE_APPROVAL=FALSE — `approval_id` do plano não vale nada."""
    rt, ws, _fora, _ = amb
    alvo = ws / "d.txt"
    negador = {"n": 0}

    def aprovador(d):
        negador["n"] += 1
        return "registro:" in str(d.target)      # aprova registro, nega o nó

    rt2 = RuntimeGovernado(rt.ctx, aprovador, caminhos=(str(ws),), adapters=True)
    res = rt2.rodar("p3", passos=[{"id": "p", "ferramenta": "fs-escrever",
                                   "params": {"alvo": str(alvo), "conteudo": "x",
                                              "approval_id": "forjado-123"}}])
    assert not res.ok
    assert not alvo.exists()


# ============================== caminhos: resolvido, não lexical

@pytest.mark.parametrize("molde", [
    "{fora}/segredo.txt",
    "{ws}/../fora/segredo.txt",
    "{ws}/./../../fora/segredo.txt",
    "{ws}/a/../../fora/segredo.txt",
])
def test_p3_escape_lexical_de_caminho_e_recusado(amb, molde):
    """LEXICAL_PATH_ESCAPE=FALSE."""
    rt, ws, fora, _ = amb
    alvo = molde.format(ws=ws, fora=fora)
    assert not _plano(rt, alvo=alvo).ok, f"escapou por {molde}"


def test_p3_escape_por_symlink_e_recusado(amb):
    """SYMLINK_PATH_ESCAPE=FALSE, incluindo cadeia."""
    rt, ws, fora, _ = amb
    (ws / "l1").symlink_to(fora / "segredo.txt")
    (ws / "l2").symlink_to(ws / "l1")
    assert not _plano(rt, alvo=str(ws / "l1")).ok
    assert not _plano(rt, alvo=str(ws / "l2")).ok


def test_p3_normalizacao_unicode_nao_escapa(amb):
    """NORMALIZATION_SCOPE_ESCAPE=FALSE.

    NFD e NFC do mesmo nome são bytes diferentes; o confinamento tem de valer
    para as duas formas, e nenhuma delas pode sair da raiz.
    """
    import unicodedata
    rt, ws, fora, _ = amb
    nome = "ação.txt"
    (fora / unicodedata.normalize("NFC", nome)).write_text("FORA")
    for forma in ("NFC", "NFD"):
        alvo = str(fora / unicodedata.normalize(forma, nome))
        assert not _plano(rt, alvo=alvo).ok, f"{forma} escapou"


def test_p3_troca_de_symlink_entre_resolucao_e_efeito(amb):
    """`resolve()` cedo demais não basta se o caminho for trocado depois.

    Corrida adversarial: uma thread troca o symlink de um alvo interno para um
    externo enquanto escritas acontecem. Nenhuma escrita pode cair fora.
    """
    rt, ws, fora, _ = amb
    dentro = ws / "interno.txt"
    dentro.write_text("dentro")
    externo = fora / "externo.txt"
    externo.write_text("ORIGINAL-EXTERNO")
    link = ws / "movel.txt"
    link.symlink_to(dentro)

    parar = threading.Event()

    def trocador():
        while not parar.is_set():
            try:
                link.unlink(missing_ok=True)
                link.symlink_to(externo)
                link.unlink(missing_ok=True)
                link.symlink_to(dentro)
            except OSError:
                pass

    t = threading.Thread(target=trocador, daemon=True)
    t.start()
    try:
        for _ in range(400):
            rt.rodar("p3", passos=[{"id": "p", "ferramenta": "fs-escrever",
                                    "params": {"alvo": str(link),
                                               "conteudo": "INVADIDO"}}])
    finally:
        parar.set()
        t.join(timeout=5)
    assert externo.read_text() == "ORIGINAL-EXTERNO", (
        "escrita caiu FORA da raiz por troca de symlink na janela")


def test_p3_campo_governado_desconhecido_nao_vira_autoridade(amb):
    """UNKNOWN_GOVERNED_FIELD_ACCEPTED=FALSE.

    Um campo inventado não pode virar autoridade por acidente — nem ser
    interpretado como sinônimo dos que existem.
    """
    rt, ws, fora, _ = amb
    alvo = ws / "e.txt"
    alvo.write_text("ok")
    res = _plano(rt, alvo=str(alvo), alvo_real=str(fora / "segredo.txt"),
                 __alvo__=str(fora / "segredo.txt"))
    if res.ok:
        assert res.missao.nos["p"].resultado == "ok", (
            "campo desconhecido mudou o alvo efetivo")
