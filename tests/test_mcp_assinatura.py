"""Fase 5 (MC63) — assinatura OPCIONAL de autor em manifestos MCP.

Camada ACIMA do SHA-256 (que prova "não mudou"): a assinatura ed25519 prova
"QUEM assinou". Reutiliza a MESMA infra das skills (ext.signing + trust.json de
publicadores). Aqui provamos os 4 estados e que a assinatura NÃO mexe na
impressão de confiança-por-registro (SHA-256).
"""
import json

from nomos.ext import signing
from nomos.interface import mcp_catalogo as cat

_MANIFESTO = {
    "nome": "conector-teste",
    "descricao": "um conector qualquer para o teste de assinatura",
    "comando": ["python3", "servidor.py"],
    "nivel_padrao": "A3",
    "env": ["FOO"],
    "tools": {"faz_algo": "A3"},
}


def _assina(tmp_path):
    priv, pub_b64 = signing.keygen(tmp_path / "chaves")
    assinado = cat.assinar_manifesto(dict(_MANIFESTO), priv)
    return assinado, pub_b64


def test_sem_assinatura_e_estado_neutro(nomos_home):
    estado, _ = cat.verificar_assinatura(dict(_MANIFESTO), nomos_home)
    assert estado == "sem_assinatura"


def test_assinado_mas_autor_desconhecido(nomos_home, tmp_path):
    assinado, _pub = _assina(tmp_path)
    estado, detalhe = cat.verificar_assinatura(assinado, nomos_home)
    assert estado == "assinado_desconhecido"     # crypto OK, autor não pinado
    assert detalhe == assinado["signature"]["publisher"]


def test_assinado_e_confiavel_apos_pinar_o_autor(nomos_home, tmp_path):
    assinado, pub_b64 = _assina(tmp_path)
    trust = signing.TrustStore(nomos_home / "trust.json")
    trust.add(pub_b64, "Se7enpay")
    estado, detalhe = cat.verificar_assinatura(assinado, nomos_home)
    assert estado == "assinado_confiavel"
    assert detalhe == "Se7enpay"                 # o rótulo do autor confiável


def test_autor_revogado_vira_invalido(nomos_home, tmp_path):
    assinado, pub_b64 = _assina(tmp_path)
    trust = signing.TrustStore(nomos_home / "trust.json")
    fp = trust.add(pub_b64, "Se7enpay")
    trust.revoke(fp)
    estado, _ = cat.verificar_assinatura(assinado, nomos_home)
    assert estado == "assinatura_invalida"       # revogado = fail-closed


def test_manifesto_adulterado_apos_assinar_falha(nomos_home, tmp_path):
    assinado, pub_b64 = _assina(tmp_path)
    signing.TrustStore(nomos_home / "trust.json").add(pub_b64, "Se7enpay")
    # troca um campo DEPOIS de assinar: a assinatura não cobre mais o conteúdo
    assinado["tools"]["faz_algo"] = "A0"
    estado, _ = cat.verificar_assinatura(assinado, nomos_home)
    assert estado == "assinatura_invalida"


def test_bloco_malformado_nunca_lanca(nomos_home):
    for ruim in ({"signature": "nao-e-dict"},
                 {"signature": {"algo": "rsa"}},
                 {"signature": {"algo": "ed25519", "pubkey": "!!!",
                                "sig": "!!!", "publisher": "x"}}):
        m = dict(_MANIFESTO, **ruim)
        estado, _ = cat.verificar_assinatura(m, nomos_home)
        assert estado == "assinatura_invalida"


def test_pubkey_trocada_por_outra_do_atacante(nomos_home, tmp_path):
    """Autor pinado A; atacante assina com a própria chave B e embute B.pubkey.
    A crypto do bloco 'bate' (B assinou B), mas o autor B não é o pinado ⇒
    'desconhecido' (não 'confiável'). Sem pinagem, assinatura não é blindagem."""
    _assinado_a, pub_a = _assina(tmp_path)
    signing.TrustStore(nomos_home / "trust.json").add(pub_a, "Autor A")
    priv_b, _pub_b = signing.keygen(tmp_path / "chaves_b")
    forjado = cat.assinar_manifesto(dict(_MANIFESTO), priv_b)   # assinado por B
    estado, _ = cat.verificar_assinatura(forjado, nomos_home)
    assert estado == "assinado_desconhecido"     # B não é o autor confiável


def test_assinatura_nao_muda_a_impressao_sha256(tmp_path):
    """A SHA-256 de confiança-por-registro é sobre nome/comando/nivel/tools —
    assinar (que só ADICIONA o bloco 'signature') não muda a impressão. Prova
    que as duas camadas são ortogonais."""
    assinado, _ = _assina(tmp_path)

    def reduz(m):
        return {k: m[k] for k in ("nome", "comando", "nivel_padrao", "tools")}

    assert cat.impressao(reduz(_MANIFESTO)) == cat.impressao(reduz(assinado))
    assert "signature" in assinado and "signature" not in reduz(assinado)


# --- CLI -------------------------------------------------------------------
def _ctx(nomos_home):
    from nomos.kernel.audit import AuditLog
    from nomos.kernel.policy import PolicyEngine
    nomos_home.mkdir(parents=True, exist_ok=True)
    return {"home": nomos_home,
            "policy": PolicyEngine(nomos_home / "policy.json"),
            "audit": AuditLog(nomos_home / "logs" / "audit.jsonl"),
            "skills": nomos_home / "skills"}


def _manifesto_em(tmp_path):
    p = tmp_path / "manifesto.json"
    p.write_text(json.dumps(_MANIFESTO), encoding="utf-8")
    return p


def test_cli_assinar_grava_bloco_e_assinatura_le(nomos_home, tmp_path, capsys):
    from nomos.cli import cmd_mcp
    priv, _pub = signing.keygen(tmp_path / "k")
    mani = _manifesto_em(tmp_path)
    ctx = _ctx(nomos_home)

    class _Assinar:
        mcp_cmd = "assinar"
        manifesto = str(mani)
        chave = str(priv)

    assert cmd_mcp(ctx, _Assinar()) == 0
    assert "signature" in json.loads(mani.read_text())     # bloco gravado

    class _Ver:
        mcp_cmd = "assinatura"
        manifesto = str(mani)
        json = False

    assert cmd_mcp(ctx, _Ver()) == 0
    assert "não está pinado" in capsys.readouterr().out.lower()


def test_cli_confiar_recusa_assinatura_invalida(nomos_home, tmp_path, capsys):
    from nomos.cli import cmd_mcp
    priv, _pub = signing.keygen(tmp_path / "k")
    mani = _manifesto_em(tmp_path)
    ctx = _ctx(nomos_home)

    class _Assinar:
        mcp_cmd = "assinar"
        manifesto = str(mani)
        chave = str(priv)

    cmd_mcp(ctx, _Assinar())
    # adultera DEPOIS de assinar
    d = json.loads(mani.read_text())
    d["nivel_padrao"] = "A0"
    mani.write_text(json.dumps(d), encoding="utf-8")

    class _Confiar:
        mcp_cmd = "confiar"
        manifesto = str(mani)

    rc = cmd_mcp(ctx, _Confiar())
    assert rc != 0                                         # fail-closed
    assert "INVÁLIDA" in capsys.readouterr().err
    trilha = (nomos_home / "logs" / "audit.jsonl").read_text()
    assert "mcp.confiar.assinatura_invalida" in trilha


def test_parser_tem_assinatura_e_assinar():
    from nomos.cli import build_parser
    a = build_parser().parse_args(["mcp", "assinatura", "telegram", "--json"])
    assert a.mcp_cmd == "assinatura" and a.manifesto == "telegram" and a.json
    b = build_parser().parse_args(["mcp", "assinar", "telegram", "/tmp/k.pem"])
    assert b.mcp_cmd == "assinar" and b.chave == "/tmp/k.pem"


def test_conectores_exemplo_reporta_estado_da_assinatura(nomos_home, tmp_path):
    """A descoberta (nomos mcp exemplos) traz o estado da assinatura por conector."""
    raiz = tmp_path / "mcp"
    (raiz / "assinado").mkdir(parents=True)
    (raiz / "cru").mkdir(parents=True)
    priv, pub = signing.keygen(tmp_path / "k")
    (raiz / "assinado" / "manifesto.json").write_text(
        json.dumps(cat.assinar_manifesto(dict(_MANIFESTO, nome="assinado"), priv)),
        encoding="utf-8")
    (raiz / "cru" / "manifesto.json").write_text(
        json.dumps(dict(_MANIFESTO, nome="cru")), encoding="utf-8")
    signing.TrustStore(nomos_home / "trust.json").add(pub, "Autor")
    por_nome = {c["nome"]: c
                for c in cat.conectores_exemplo(nomos_home, raiz=raiz)}
    assert por_nome["assinado"]["assinatura"] == "assinado_confiavel"
    assert por_nome["cru"]["assinatura"] == "sem_assinatura"
