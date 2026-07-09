"""MC28 — NOMOS Memory Engine: política fail-closed (policy).

Cobre os bloqueios obrigatórios: segredo sk-, CPF, CNPJ, chave privada, cookie,
password, além de comando perigoso e conteúdo limpo/ vazio. Verifica o código
exato de recusa e as flags de segurança.
"""
from nomos.memory import policy


def _rejeita(texto, categoria=None):
    d = policy.evaluate(texto)
    assert d.allowed is False
    assert d.reason == policy.REJECTION_CODE
    if categoria:
        assert categoria in {f.category for f in d.findings}
    return d


def test_segredo_sk_rejeitado():
    d = _rejeita("minha chave OPENAI sk-ABCDEFGHIJKLMNOP1234567890xyz", "openai_key")
    assert d.contains_secret is True


def test_cpf_rejeitado():
    _rejeita("meu CPF é 529.982.247-25, anota aí", "cpf")


def test_cpf_cru_valido_rejeitado():
    # CPF válido sem formatação também é barrado (dígito verificador confere)
    _rejeita("documento 52998224725 do cadastro", "cpf")


def test_cnpj_rejeitado():
    _rejeita("CNPJ 11.222.333/0001-81 da empresa", "cnpj")


def test_private_key_rejeitada():
    _rejeita("segredo:\n-----BEGIN RSA PRIVATE KEY-----\nMIIEnope", "private_key")


def test_cookie_rejeitado():
    _rejeita("guarde isto: Cookie: sessionid=abc123def456ghi789", "cookie")


def test_password_rejeitado():
    d = _rejeita("o password = hunter2secreto do painel admin", "generic_secret")
    assert d.contains_secret is True


def test_comando_perigoso_rejeitado():
    d = _rejeita("roda no terminal: rm -rf / --no-preserve-root", "dangerous_command")
    assert d.human_review_required is True


def test_ssh_e_jwt_rejeitados():
    assert policy.evaluate("chave ssh-ed25519 AAAAC3NzaC1lZDI1 host").allowed is False
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.abcDEF123"
    assert policy.evaluate(f"token {jwt}").allowed is False


def test_conteudo_limpo_aprovado():
    d = policy.evaluate("Prefiro relatórios em português com evidência objetiva.")
    assert d.allowed is True
    assert d.reason == "OK"
    assert policy.scan("texto totalmente inócuo sobre café") == []


def test_vazio_bloqueado_fail_closed():
    assert policy.evaluate("").allowed is False
    assert policy.evaluate("   ").allowed is False
    assert policy.evaluate(None).allowed is False       # type: ignore[arg-type]


def test_flags_de_seguranca_por_categoria():
    seg = policy.evaluate("credencial AKIAIOSFODNN7EXAMPLE exposta")
    assert seg.contains_secret is True
    pes = policy.evaluate("CPF 529.982.247-25")
    assert pes.contains_personal_sensitive_data is True
