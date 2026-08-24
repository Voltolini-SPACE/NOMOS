"""O serviço que reiniciou a cada 5 minutos por um dia e meio: o digest
CONCEDIDO não era o CONSULTADO.

`capacidades conceder` (cli.py) monta a sonda `RegistroCapacidades` SEM
`escopo_dados`; o runtime do serviço (governado.py) monta o registro COM
`escopo_dados=raízes` — desde 9f768ea, que pôs o escopo no digest (conserto
adversarial legítimo: sem ele, concessão lida para `~/dados` valia para `/`).
A sonda ficou para trás: o dono lê "raízes: X" impresso pelo conceder, mas a
concessão é assinada com escopo VAZIO. No arranque seguinte, registrar
`fs-apagar` consulta o digest COM escopo, não encontra, cai no gate ao vivo
do painel, o TTL de 300 s expira, `preparar` levanta ErroRegistro, o serviço
sai com EXIT_DENIED=3 e o KeepAlive recomeça — para sempre.

Medido em produção (24/08/2026): concessão `99b51112…` (escopo=[]) VIGENTE e
ignorada; serviço consultando `006f0282…` (escopo=('/Users/AI/.nomos',)).
Janela silenciosa de 24 h entre a concessão (22/08 21:11) e a chegada do
9f768ea ao venv (23/08 20:33) prova que a paridade de digest é exatamente o
que mantém o serviço de pé.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import nomos.cli as cli
from nomos.kernel.audit import AuditLog
from nomos.kernel.policy import PolicyEngine
from nomos.runtime.agendador import AgendadorGovernado, ConfigAgendador
from nomos.runtime.servico import ConfigServico, rodar_servico

# O serviço persistente exige a TravaInstancia (flock POSIX) — no Windows a
# capacidade NÃO existe (doutrina NH-014/plataforma: gate pelo fato medido,
# como servico_persistente_disponivel). Medido no CI de 24/08: os dois E2E
# morriam em ModuleNotFoundError('fcntl') cru.
so_flock = pytest.mark.skipif(
    importlib.util.find_spec("fcntl") is None,
    reason="TravaInstancia é flock (POSIX); nesta plataforma a capacidade não existe")

POLICY = {
    "version": 1,
    "mode": "read_only_default",
    "fail_closed": True,
    "rules": {
        "A0_READ_LOCAL": "ALLOW",
        "A1_WRITE_LOCAL": "REQUIRE_APPROVAL",
        "A2_NET_EGRESS": "REQUIRE_APPROVAL",
        "A3_CRED_USE": "REQUIRE_APPROVAL",
        "A3_CONNECTOR_USE": "REQUIRE_APPROVAL",
        "A4_DEVICE_MIC": "REQUIRE_APPROVAL",
        "A4_DEVICE_CAM": "REQUIRE_APPROVAL",
        "A4_DEVICE_SCREEN": "REQUIRE_APPROVAL",
        "A5_CODE_EXEC": "REQUIRE_APPROVAL",
        "A5_SKILL_INSTALL": "REQUIRE_APPROVAL",
        "A6_DESTRUCTIVE": "DENY",
    },
}


def _home_com_politica(tmp_path):
    home = tmp_path / "nomos-home"
    home.mkdir()
    (home / "policy.json").write_text(json.dumps(POLICY), encoding="utf-8")
    ctx = {
        "home": home,
        "policy": PolicyEngine(home / "policy.json"),
        "audit": AuditLog(home / "logs" / "audit.jsonl"),
    }
    raiz = tmp_path / "dados"
    raiz.mkdir()
    return home, ctx, str(raiz)


def _conceder_pela_cli(ctx, raiz, monkeypatch):
    """O caminho REAL do dono: `nomos capacidades conceder --raiz <raiz>`.

    Só a decisão humana é simulada (teclado do teste). Se este helper desviar
    do código da CLI, o teste perde o valor — por isso chama `cmd_capacidades`,
    não uma reimplementação.
    """
    monkeypatch.setattr(cli, "interactive_approver", lambda _d: True)
    args = SimpleNamespace(cap_cmd="conceder", raiz=[raiz], ttl_dias=30.0,
                           motivo="fixture do teste", apenas_leitura=False,
                           destrutivas=False, sem_scheduler=False)
    assert cli.cmd_capacidades(ctx, args) == cli.EXIT_OK


def test_concessao_da_cli_cobre_o_registro_do_servico(tmp_path, monkeypatch):
    """Depois de `conceder --raiz X`, `preparar()` com as MESMAS raízes não
    pode precisar de humano nenhum: a concessão existe para isso.

    RED no estado com o defeito: a sonda assina escopo=[] e o serviço consulta
    escopo=(X,) — o approver é chamado, nega (ninguém no painel), e `preparar`
    morre com ErroRegistro.
    """
    _home, ctx, raiz = _home_com_politica(tmp_path)
    _conceder_pela_cli(ctx, raiz, monkeypatch)

    pedidos_ao_vivo: list[str] = []

    def painel_vazio(decisao):
        # o serviço de verdade: pedido entra na fila, ninguém decide, TTL
        # expira ⇒ False. Registrar o alvo prova QUEM pediu aprovação.
        pedidos_ao_vivo.append(getattr(decisao, "target", "?"))
        return False

    ag = AgendadorGovernado(ctx, painel_vazio,
                            ConfigAgendador(raizes=(raiz,)))
    capacidades = ag.preparar()          # com o defeito: ErroRegistro aqui

    assert capacidades, "preparar() sem capacidade alguma"
    assert pedidos_ao_vivo == [], (
        "o arranque pediu aprovação AO VIVO apesar da concessão vigente: "
        f"{pedidos_ao_vivo}")


@so_flock
def test_servico_sobe_e_encerra_ok_sem_humano_no_painel(tmp_path, monkeypatch):
    """E2E do laço observado em produção: com concessão dada pela CLI e
    NINGUÉM no painel, `rodar_servico` tem de subir e devolver EXIT_OK —
    não EXIT_DENIED=3, que é o que o launchd via a cada 5 minutos.
    """
    _home, ctx, raiz = _home_com_politica(tmp_path)
    _conceder_pela_cli(ctx, raiz, monkeypatch)

    rc = rodar_servico(ctx, ConfigServico(raizes=(raiz,), intervalo_s=0.01),
                       max_ticks=1, dormir=lambda _s: None,
                       aprovador=lambda _d: False)
    assert rc == cli.EXIT_OK, (
        f"serviço saiu com rc={rc} (3 = o exit do laço fs-apagar)")


# ===================================================================
# Bateria adversarial (missão NOMOS-FS-APAGAR-GOVERNANCE-LOOP-01).
# A concessão só pode cobrir o ATO DE REGISTRAR — nada aqui pode
# afrouxar execução, escopo, ou a fronteira A6.
# ===================================================================


def _runtime(ctx, raiz, aprovador):
    from nomos.runtime.governado import RuntimeGovernado
    return RuntimeGovernado(ctx, aprovador, caminhos=(raiz,), adapters=True)


def _apagar(rt, alvo):
    return rt.rodar("adversarial: fs-apagar",
                    passos=[{"id": "op", "ferramenta": "fs-apagar",
                             "params": {"alvo": str(alvo)}}])


@so_flock
def test_adversarial_A_boot_sem_pedido_espontaneo(tmp_path, monkeypatch):
    """A: subir o serviço com o aprovador PADRÃO (painel real) e nenhuma
    intenção destrutiva não pode gerar pedido algum na fila.

    (Sem a correção este teste também travaria ~300 s no TTL do painel —
    o tempo de execução é parte da prova.)
    """
    home, ctx, raiz = _home_com_politica(tmp_path)
    _conceder_pela_cli(ctx, raiz, monkeypatch)

    rc = rodar_servico(ctx, ConfigServico(raizes=(raiz,), intervalo_s=0.01),
                       max_ticks=1, dormir=lambda _s: None)   # aprovador padrão
    assert rc == cli.EXIT_OK
    fila = home / "approvals"
    pedidos = list(fila.glob("*.json")) if fila.exists() else []
    assert pedidos == [], f"boot benigno criou pedido(s): {pedidos}"


def test_adversarial_B_negado_ou_expirado_preserva_o_alvo(tmp_path, monkeypatch):
    """B: sem aprovação de EXECUÇÃO (negada, ou expirada — o gate devolve
    False nos dois casos), o arquivo fica intacto e o runtime segue vivo."""
    _home, ctx, raiz = _home_com_politica(tmp_path)
    _conceder_pela_cli(ctx, raiz, monkeypatch)
    vitima = Path(raiz) / "vitima.txt"
    vitima.write_text("intacto")

    rt = _runtime(ctx, raiz, lambda _d: False)     # ninguém aprova execução
    res = _apagar(rt, vitima)
    assert not res.ok
    assert vitima.exists() and vitima.read_text() == "intacto"

    # o runtime NÃO morreu: uma leitura A0 (ALLOW) continua operando
    res2 = rt.rodar("adversarial: fs-ler",
                    passos=[{"id": "op", "ferramenta": "fs-ler",
                             "params": {"alvo": str(vitima)}}])
    assert res2.ok, f"runtime morto após negação: {res2.motivo}"


def test_adversarial_C_aprovacao_valida_apaga_so_o_alvo(tmp_path, monkeypatch):
    """C: com aprovação explícita, SÓ o alvo aprovado é removido."""
    _home, ctx, raiz = _home_com_politica(tmp_path)
    _conceder_pela_cli(ctx, raiz, monkeypatch)
    alvo = Path(raiz) / "alvo.txt"
    vizinho = Path(raiz) / "vizinho.txt"
    alvo.write_text("x")
    vizinho.write_text("y")

    rt = _runtime(ctx, raiz, lambda _d: True)      # dono aprova a execução
    res = _apagar(rt, alvo)
    assert res.ok, f"execução aprovada falhou: {res.motivo}"
    assert not alvo.exists()
    assert vizinho.exists() and vizinho.read_text() == "y"


def test_adversarial_D_concessao_nao_atravessa_escopo(tmp_path, monkeypatch):
    """D: concessão dada para a raiz X NÃO cobre um serviço com raiz Y —
    o gate volta ao vivo (e sem humano, o registro é negado)."""
    _home, ctx, raiz_x = _home_com_politica(tmp_path)
    _conceder_pela_cli(ctx, raiz_x, monkeypatch)
    raiz_y = tmp_path / "outros-dados"
    raiz_y.mkdir()

    ao_vivo: list[str] = []

    def painel_vazio(decisao):
        ao_vivo.append(getattr(decisao, "target", "?"))
        return False

    from nomos.orquestracao.registro import ErroRegistro
    ag = AgendadorGovernado(ctx, painel_vazio,
                            ConfigAgendador(raizes=(str(raiz_y),)))
    with pytest.raises(ErroRegistro):
        ag.preparar()
    assert ao_vivo, "escopo diferente não voltou ao gate ao vivo"


def test_adversarial_D2_mudanca_de_politica_invalida_concessao(tmp_path,
                                                               monkeypatch):
    """D2: editar policy.json invalida as concessões (o digest cobre
    `versao_da_politica`) — regra herdada de 9f768ea que a correção
    não pode afrouxar."""
    home, ctx, raiz = _home_com_politica(tmp_path)
    _conceder_pela_cli(ctx, raiz, monkeypatch)

    mudada = dict(POLICY, rules=dict(POLICY["rules"], A4_DEVICE_CAM="DENY"))
    (home / "policy.json").write_text(json.dumps(mudada), encoding="utf-8")
    ctx["policy"] = PolicyEngine(home / "policy.json")

    ao_vivo: list[str] = []

    def painel_vazio(decisao):
        ao_vivo.append(getattr(decisao, "target", "?"))
        return False

    from nomos.orquestracao.registro import ErroRegistro
    ag = AgendadorGovernado(ctx, painel_vazio,
                            ConfigAgendador(raizes=(raiz,)))
    with pytest.raises(ErroRegistro):
        ag.preparar()
    assert ao_vivo, "política mudou e a concessão antiga continuou valendo"


def test_adversarial_E_traversal_symlink_absoluto(tmp_path, monkeypatch):
    """E: nem `..`, nem caminho absoluto de fora, nem symlink levam o
    `fs-apagar` a tocar dados reais fora da raiz — mesmo com o dono
    aprovando a execução."""
    _home, ctx, raiz = _home_com_politica(tmp_path)
    _conceder_pela_cli(ctx, raiz, monkeypatch)
    fora = tmp_path / "fora.txt"
    fora.write_text("dados reais")

    rt = _runtime(ctx, raiz, lambda _d: True)      # aprovação NÃO basta

    res = _apagar(rt, Path(raiz) / ".." / "fora.txt")
    assert not res.ok and fora.exists()

    res = _apagar(rt, fora)                        # absoluto, fora da raiz
    assert not res.ok and fora.exists()

    link = Path(raiz) / "link-para-fora"
    link.symlink_to(fora)
    res = _apagar(rt, link)                        # apagar o LINK é A1 e ok…
    assert not link.exists() or not res.ok
    assert fora.exists() and fora.read_text() == "dados reais"  # …o ALVO nunca

