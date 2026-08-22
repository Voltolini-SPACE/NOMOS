import subprocess
import sys

from nomos.kernel import plataforma

_COD = '''
import builtins
_orig = builtins.__import__
def fake(n, *a, **k):
    if n == "resource":
        raise ImportError("simulando Windows")
    return _orig(n, *a, **k)
builtins.__import__ = fake
import nomos.cli
import nomos.runtime.sandbox as sb
assert sb.resource is None, "resource deveria ser None"
print("IMPORT_OK_SEM_RESOURCE")
'''


def test_helpers():
    # Igualdade, não `issubset`: o resumo é contrato lido pelo `nomos doutor`, e
    # afrouxar para "contém" deixaria uma chave sumir sem ninguém perceber.
    assert set(plataforma.resumo()) == {
        "sistema", "python", "execucao_isolada", "git_governado",
        "servico_persistente"}


def test_chmod_privado_nunca_levanta(tmp_path):
    f = tmp_path / "x"
    f.write_text("s")
    plataforma.chmod_privado(f, 0o600)
    plataforma.chmod_privado(tmp_path / "nao-existe", 0o600)


def test_isolada_falsa_fora_linux(monkeypatch):
    monkeypatch.setattr(plataforma, "EH_LINUX", False)
    assert plataforma.execucao_isolada_disponivel() is False


def test_git_governado_falso_fora_do_mac(monkeypatch):
    """A capacidade Git governada não existe fora do macOS — e a decisão não
    pode depender de `/usr/bin/git`, que existe em toda plataforma."""
    monkeypatch.setattr(plataforma, "EH_MAC", False)
    assert plataforma.capacidade_git_governada_disponivel() is False


def test_git_governado_falso_sem_sandbox_exec(monkeypatch):
    """Mac sem `sandbox-exec` também recusa: é o binário que confina, não o SO."""
    monkeypatch.setattr(plataforma, "EH_MAC", True)
    monkeypatch.setattr(plataforma.os.path, "exists", lambda _c: False)
    assert plataforma.capacidade_git_governada_disponivel() is False


def test_git_governado_verdadeiro_com_mac_e_sandbox(monkeypatch):
    """Controle positivo: sem ele os dois testes acima passariam por vácuo se a
    função passasse a devolver False sempre."""
    monkeypatch.setattr(plataforma, "EH_MAC", True)
    monkeypatch.setattr(plataforma.os.path, "exists", lambda _c: True)
    assert plataforma.capacidade_git_governada_disponivel() is True


def test_constante_do_sandbox_nao_diverge_do_supervisor():
    """`kernel.plataforma` duplica o caminho do `sandbox-exec` de propósito (o
    kernel não importa adapter). Duplicata sem trava vira divergência silenciosa
    — e aí a suíte gataria numa plataforma e o produto em outra."""
    from nomos.adapters import supervisor
    assert plataforma.SANDBOX_EXEC == supervisor.SANDBOX


def test_resumo_expoe_git_governado():
    """`nomos doutor` e o resumo de plataforma precisam dizer que a capacidade
    existe ou não — indisponibilidade por desenho só é honesta se for visível."""
    assert "git_governado" in plataforma.resumo()


def test_importa_sem_resource():
    r = subprocess.run([sys.executable, "-c", _COD], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "IMPORT_OK_SEM_RESOURCE" in r.stdout


# ------------------------------------- serviço persistente (NH-014, launchd)

def test_servico_falso_sem_fcntl(monkeypatch):
    """Windows: sem `fcntl` não há flock, e sem flock não há como saber que já
    existe uma instância rodando — PID não prova. A capacidade não existe ali.

    Simula pelo IMPORT, não por `platform.system()`: é o fato que a função
    consulta, e é o mesmo mecanismo do `_COD` acima para `resource`.
    """
    import builtins
    orig = builtins.__import__

    def sem_fcntl(nome, *a, **k):
        if nome == "fcntl":
            raise ImportError("simulando Windows")
        return orig(nome, *a, **k)

    monkeypatch.setattr(builtins, "__import__", sem_fcntl)
    assert plataforma.servico_persistente_disponivel() is False


def test_servico_falso_sem_launchctl(monkeypatch):
    """Linux tem `fcntl` e não tem `launchd` — e o NH-014 escreve um plist e
    fala com `launchctl`. Ter metade da capacidade não é ter a capacidade."""
    import shutil
    monkeypatch.setattr(shutil, "which", lambda _n: None)
    assert plataforma.servico_persistente_disponivel() is False


def test_servico_verdadeiro_com_fcntl_e_launchctl(monkeypatch):
    """Controle positivo: sem ele os dois acima passariam por vácuo se a função
    passasse a devolver False sempre — o mesmo cuidado do trio do git."""
    import shutil
    monkeypatch.setattr(shutil, "which", lambda _n: "/bin/launchctl")
    assert plataforma.servico_persistente_disponivel() is True


def test_resumo_expoe_servico_persistente():
    """`nomos doutor` precisa poder dizer que o serviço não existe NESTA
    plataforma — senão o usuário do Windows lê 'parado' e conclui defeito."""
    assert "servico_persistente" in plataforma.resumo()
