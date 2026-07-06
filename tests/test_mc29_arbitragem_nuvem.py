"""MC29 — Nuvem opt-in na arbitragem: o runner de nuvem só nasce após os gates.

Barreiras provadas uma a uma (fail-closed): cadeado de localidade, gate A2
(egress), gate A3 (credencial), passphrase/cofre. E os invariantes: sem
opt-in a nuvem nunca participa; a chave jamais aparece em repr; CLI --nuvem
em ambiente não-interativo nega sem pedir nada.
"""
import subprocess
import sys
from pathlib import Path

from nomos.cognition import arbitragem as arb
from nomos.kernel import localidade
from nomos.kernel.policy import PolicyEngine

ROOT = Path(__file__).resolve().parent.parent
APROVA = lambda decision: True          # noqa: E731 — aprovador de teste


class _VaultFake:
    def __init__(self, chave=None, erro=None):
        self._chave, self._erro = chave, erro

    def get(self, nome, passphrase):
        if self._erro:
            raise self._erro
        return self._chave


class _ProviderFake:
    def __init__(self, api_key):
        self._k = api_key

    def chat(self, msgs):
        class R:
            text = "resposta real da nuvem"
        return R()


def _policy(tmp_path):
    return PolicyEngine(tmp_path / "policy.json")


# barreira 1: cadeado ligado (default) => nuvem nem começa
def test_cadeado_ligado_bloqueia_nuvem(tmp_path):
    runner, motivo = arb.montar_runner_nuvem(
        tmp_path, policy=_policy(tmp_path), vault=_VaultFake("k"),
        approver=APROVA, passphrase="x")
    assert runner is None and "só-local" in motivo


# barreira 2: sem aprovador, gate A2 nega (fail-closed de scripts/CI)
def test_gate_a2_sem_aprovador_nega(tmp_path):
    localidade.definir(tmp_path, False)
    runner, motivo = arb.montar_runner_nuvem(
        tmp_path, policy=_policy(tmp_path), vault=_VaultFake("k"),
        approver=None, passphrase="x")
    assert runner is None and "A2" in motivo


# barreira 3: aprovador que só aprova egress não basta — A3 é gate separado
def test_gate_a3_credencial_e_separado(tmp_path):
    localidade.definir(tmp_path, False)
    so_egress = lambda d: "EGRESS" in d.category          # noqa: E731
    runner, motivo = arb.montar_runner_nuvem(
        tmp_path, policy=_policy(tmp_path), vault=_VaultFake("k"),
        approver=so_egress, passphrase="x")
    assert runner is None and "A3" in motivo


# barreira 4: sem passphrase / cofre indisponível
def test_sem_passphrase_nega(tmp_path):
    localidade.definir(tmp_path, False)
    runner, motivo = arb.montar_runner_nuvem(
        tmp_path, policy=_policy(tmp_path), vault=_VaultFake("k"),
        approver=APROVA, passphrase="")
    assert runner is None and "passphrase" in motivo


def test_cofre_com_erro_nega(tmp_path):
    localidade.definir(tmp_path, False)
    runner, motivo = arb.montar_runner_nuvem(
        tmp_path, policy=_policy(tmp_path),
        vault=_VaultFake(erro=RuntimeError("trancado")),
        approver=APROVA, passphrase="x")
    assert runner is None and "indisponível" in motivo


# caminho feliz (tudo aprovado): runner nasce, roda via provider, sem vazar chave
def test_todas_barreiras_aprovadas_runner_funciona(tmp_path):
    localidade.definir(tmp_path, False)
    runner, motivo = arb.montar_runner_nuvem(
        tmp_path, policy=_policy(tmp_path), vault=_VaultFake("chave-secreta-123"),
        approver=APROVA, passphrase="x", factory=_ProviderFake)
    assert motivo == "" and runner is not None
    assert runner.local is False and runner.available() is True
    assert runner.run("pergunta") == "resposta real da nuvem"
    assert "chave-secreta-123" not in repr(runner)


# invariante: sem allow_cloud, runner de nuvem é EXCLUÍDO da arbitragem
def test_arbitrar_sem_opt_in_exclui_nuvem(tmp_path):
    nuvem = arb.CloudRunner(api_key="k", factory=_ProviderFake)
    out = arb.arbitrar("q", [nuvem])          # allow_cloud default: False
    assert out.status == "no_engine"
    assert out.decision.final_content == ""


def test_arbitrar_com_opt_in_usa_nuvem(tmp_path):
    nuvem = arb.CloudRunner(api_key="k", factory=_ProviderFake)
    out = arb.arbitrar("q", [nuvem], allow_cloud=True, min_candidatos=1)
    assert out.status != "no_engine"


# CLI: --nuvem em ambiente não-interativo nega fail-closed (exit 3), sem prompt
def test_cli_nuvem_nao_interativo_nega(tmp_path):
    proc = subprocess.run(
        [sys.executable, "-m", "nomos", "motores", "arbitrar", "oi", "--nuvem"],
        capture_output=True, text=True, timeout=60, cwd=str(ROOT),
        env={"NOMOS_HOME": str(tmp_path), "PATH": ""},
    )
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert "decisão humana" in proc.stderr
