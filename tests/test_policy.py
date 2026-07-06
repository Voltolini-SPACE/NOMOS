from nomos.kernel.policy import Category, Effect, PolicyEngine, gate


def _engine(tmp_path):
    return PolicyEngine(tmp_path / "policy.json")


def test_leitura_local_permitida_por_padrao(tmp_path):
    d = _engine(tmp_path).decide(Category.READ_LOCAL, "arquivo.txt")
    assert d.effect is Effect.ALLOW


def test_acoes_sensiveis_exigem_aprovacao(tmp_path):
    e = _engine(tmp_path)
    for cat in (Category.WRITE_LOCAL, Category.CRED_USE,
                Category.DEVICE_MIC, Category.DEVICE_CAM, Category.DEVICE_SCREEN,
                Category.CODE_EXEC, Category.SKILL_INSTALL):
        assert e.decide(cat).effect is Effect.REQUIRE_APPROVAL, cat
    # NET_EGRESS com alvo LOCAL segue na regra de aprovação…
    d = e.decide(Category.NET_EGRESS, "http://127.0.0.1:11434")
    assert d.effect is Effect.REQUIRE_APPROVAL
    # …mas com alvo vazio/desconhecido e cadeado ligado (padrão), NEGA já na
    # política (MC36: não-parseável ≠ loopback — fail-closed de verdade)
    d = e.decide(Category.NET_EGRESS)
    assert d.effect is Effect.DENY
    assert "só-local" in d.reason


def test_destrutiva_negada_por_padrao(tmp_path):
    assert _engine(tmp_path).decide(Category.DESTRUCTIVE).effect is Effect.DENY


def test_categoria_desconhecida_negada_fail_closed(tmp_path):
    d = _engine(tmp_path).decide("Z9_INVENTADA")
    assert d.effect is Effect.DENY
    assert "fail-closed" in d.reason


def test_politica_corrompida_nega_tudo(tmp_path):
    path = tmp_path / "policy.json"
    e = PolicyEngine(path)
    path.write_text("{ corrompido ::: }")
    assert e.decide(Category.READ_LOCAL).effect is Effect.DENY
    assert e.decide(Category.CODE_EXEC).effect is Effect.DENY


def test_gate_sem_aprovador_nega(tmp_path):
    d = _engine(tmp_path).decide(Category.CODE_EXEC)
    assert gate(d, None) is False


def test_gate_aprovador_recusa(tmp_path):
    d = _engine(tmp_path).decide(Category.CODE_EXEC)
    assert gate(d, lambda dec: False) is False


def test_gate_aprovador_confirma(tmp_path):
    d = _engine(tmp_path).decide(Category.CODE_EXEC)
    assert gate(d, lambda dec: True) is True


def test_gate_aprovador_com_erro_nunca_autoriza(tmp_path):
    d = _engine(tmp_path).decide(Category.CODE_EXEC)

    def quebrado(dec):
        raise RuntimeError("falha no aprovador")

    assert gate(d, quebrado) is False


def test_gate_deny_ignora_aprovador(tmp_path):
    d = _engine(tmp_path).decide(Category.DESTRUCTIVE)
    assert gate(d, lambda dec: True) is False
