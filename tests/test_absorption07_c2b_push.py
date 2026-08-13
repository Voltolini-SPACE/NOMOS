"""C2b — `git-push`: escrita remota com o destino comprometido na autorização.

`push` é a única operação desta série que atravessa fronteira de confiança:
publica em servidor de terceiro, pode disparar CI, webhooks e deploy, e não
tem desfazer sem cooperação do remoto.

O ataque central é o TOCTOU do destino:

    aprovar remote=origin → `.git/config` muda → origin aponta para o hostil
                          → push

E há um segundo, mais sutil: mesmo passando a URL autorizada no argv, o Git
aplica `url.<base>.insteadOf` do repositório e reescreve o destino. Um repo
hostil transforma o servidor autorizado no dele sem tocar em nenhum parâmetro
do plano.

Os testes usam bare repos LOCAIS: push real, efeito real, sem rede externa.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from nomos.adapters.contrato import ErroInvalido
from nomos.adapters.git_push import (DestinoGovernado, ErroRemoto,
                                     GitPushAdapter, branch_valida)
from nomos.kernel.audit import AuditLog
from nomos.kernel.policy import Category, PolicyEngine
from nomos.runtime.governado import RuntimeGovernado

GIT = "/usr/bin/git"
pytestmark = pytest.mark.skipif(not Path(GIT).exists(), reason="git ausente")


def _sim(_d):
    return True


def _git(repo: Path, *args, check=True):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    return subprocess.run([GIT, "-C", str(repo), *args], capture_output=True,
                          text=True, env=env, check=check)


@pytest.fixture()
def amb(tmp_path):
    home = tmp_path / "h"
    home.mkdir()
    ws = tmp_path / "ws"
    ws.mkdir()
    permitido = tmp_path / "allowed.git"
    hostil = tmp_path / "evil.git"
    for bare in (permitido, hostil):
        bare.mkdir()
        _git(bare, "init", "-q", "--bare")
    repo = ws / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "a.txt").write_text("conteudo\n")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-qm", "primeiro")

    # FIXTURE de localidade, isolada por NOMOS_HOME de teste. `git-push` é
    # A2_NET_EGRESS SEMPRE — a categoria não depende do esquema da URL, e o
    # bare `file://` é apenas um TEST DOUBLE do destino remoto. Deixar
    # `file://` virar WRITE_LOCAL devolveria ao destino (e portanto ao repo e
    # ao plano) influência sobre a própria classe de risco, que é exatamente o
    # padrão que o GATE C corrigiu.
    #
    # O modo só-local do NOMOS bloqueia egresso ANTES do gate A0–A6 — quarta
    # trava independente desta série. Aqui ele é desligado apenas NESTE home
    # temporário; a produção não é tocada.
    from nomos.kernel import localidade
    localidade.definir(home, False)

    destinos = {"producao": DestinoGovernado(
        remote_id="producao", url=f"file://{permitido}",
        branch_destino="main", credential_id="cred-prod")}
    ctx = {"home": home, "policy": PolicyEngine(home / "policy.json"),
           "audit": AuditLog(home / "logs" / "audit.jsonl")}
    rt = RuntimeGovernado(ctx, _sim, caminhos=(str(ws),), adapters=True,
                          git=True, git_push_destinos=destinos)
    return rt, ws, repo, permitido, hostil, ctx, destinos


def _plano(rt, **params):
    return rt.rodar("c2b", passos=[{"id": "p", "ferramenta": "git-push",
                                    "params": params}])


def _refs(bare: Path) -> dict:
    saida = _git(bare, "for-each-ref", "--format=%(refname) %(objectname)").stdout
    return (dict(linha.split() for linha in saida.splitlines() if linha.strip())
            if saida.strip() else {})


def _sha(bare: Path, ref: str) -> str:
    p = _git(bare, "rev-parse", ref, check=False)
    return p.stdout.strip() if p.returncode == 0 else ""


# ============================================ push real

def test_c2b_push_real_para_bare_local(amb):
    """REAL_REMOTE_PUSH: o SHA remoto tem de bater com o local."""
    rt, _ws, repo, permitido, _hostil, _ctx, _d = amb
    res = _plano(rt, alvo=str(repo), remote_id="producao", source_branch="main")
    assert res.ok, res.motivo
    esperado = _git(repo, "rev-parse", "main").stdout.strip()
    assert _sha(permitido, "refs/heads/main") == esperado


def test_c2b_push_nao_toca_o_remote_hostil(amb):
    rt, _ws, repo, _permitido, hostil, _c, _d = amb
    assert _plano(rt, alvo=str(repo), remote_id="producao",
                  source_branch="main").ok
    assert _sha(hostil, "refs/heads/main") == "", "publicou no remote ERRADO"


# ============================================ TOCTOU do destino

def test_c2b_config_do_repo_nao_redireciona_o_destino(amb):
    """URL_REWRITE_ESCAPE=FALSE — o ataque do `insteadOf`.

    A URL autorizada vai no argv, mas o Git aplica `url.<base>.insteadOf` a
    QUALQUER URL, inclusive a do argv. Sem conferir a URL EFETIVA, o repo
    redireciona a publicação sem tocar em nenhum parâmetro do plano.
    """
    rt, _ws, repo, permitido, hostil, _c, _d = amb
    _git(repo, "config", f"url.file://{hostil}.insteadOf", f"file://{permitido}")
    res = _plano(rt, alvo=str(repo), remote_id="producao", source_branch="main")
    assert not res.ok, "o repositório redirecionou o destino e o push aconteceu"
    assert _sha(hostil, "refs/heads/main") == "", "publicou no remote hostil"
    assert _sha(permitido, "refs/heads/main") == ""


def test_c2b_pushInsteadOf_tambem_e_barrado(amb):
    rt, _ws, repo, permitido, hostil, _c, _d = amb
    _git(repo, "config", f"url.file://{hostil}.pushInsteadOf",
         f"file://{permitido}")
    res = _plano(rt, alvo=str(repo), remote_id="producao", source_branch="main")
    assert not res.ok, "pushInsteadOf redirecionou e o push aconteceu"
    assert _sha(hostil, "refs/heads/main") == ""
    assert _sha(permitido, "refs/heads/main") == ""


def test_c2b_remote_do_repo_nao_e_a_autoridade(amb):
    """REMOTE_NAME_ONLY_TRUST=FALSE.

    O repo declara `origin` apontando para o hostil. O destino real vem da
    POLÍTICA, então `origin` é irrelevante — e o push vai para o autorizado.
    """
    rt, _ws, repo, permitido, hostil, _c, _d = amb
    _git(repo, "remote", "add", "origin", f"file://{hostil}")
    _git(repo, "config", "remote.origin.pushurl", f"file://{hostil}")
    assert _plano(rt, alvo=str(repo), remote_id="producao",
                  source_branch="main").ok
    assert _sha(permitido, "refs/heads/main") != ""
    assert _sha(hostil, "refs/heads/main") == "", "PUSHURL_ESCAPE"


def test_c2b_conferencia_roda_de_novo_antes_do_efeito(amb):
    """A segunda resolução é o que fecha o TOCTOU.

    Exercita `conferir_destino` diretamente com a config já alterada — o
    estado que existiria entre a aprovação e o efeito.
    """
    _rt, _ws, repo, permitido, hostil, _c, destinos = amb
    ad = GitPushAdapter(destinos=destinos)
    assert ad.conferir_destino(repo, destinos["producao"])
    _git(repo, "config", f"url.file://{hostil}.insteadOf", f"file://{permitido}")
    # a recusa agora vem da REGRA de reescrita, antes de resolver a URL:
    # defesa mais forte, porque não depende de prever a resolução do push
    with pytest.raises(ErroRemoto, match="REESCRITA|REDIRECIONA"):
        ad.conferir_destino(repo, destinos["producao"])


# ============================================ o plano não escolhe nada

def test_c2b_remote_id_desconhecido_e_negado(amb):
    rt, _ws, repo, _p, _h, _c, _d = amb
    assert not _plano(rt, alvo=str(repo), remote_id="inventado",
                      source_branch="main").ok


@pytest.mark.parametrize("campo,valor", [
    ("refspec", "+refs/heads/main:refs/heads/main"),
    ("url", "file:///tmp/evil.git"),
    ("remote_url", "file:///tmp/evil.git"),
    ("branch_destino", "producao"),
    ("destination_branch", "producao"),
    ("force", True),
    ("credential", "segredo"),
    ("credential_path", "/tmp/cred"),
])
def test_c2b_campo_de_autoridade_no_plano_e_recusado(amb, campo, valor):
    """PLAN_CAN_SELECT_REFSPEC/FORCE/CREDENTIAL=FALSE — recusa, não ignora."""
    rt, _ws, repo, permitido, _h, _c, _d = amb
    res = _plano(rt, alvo=str(repo), remote_id="producao",
                 source_branch="main", **{campo: valor})
    assert not res.ok, f"'{campo}' foi aceito vindo do plano"
    assert _sha(permitido, "refs/heads/main") == ""


@pytest.mark.parametrize("ruim", [
    "+main", "-f", "--force", "--mirror", "--all", "--tags",
    "main:outra", "HEAD:main", "refs/heads/a:refs/heads/b",
    "main ", " main", "main;id", "main`id`", "main..outra", "main@{0}",
    "", "a" * 200, "main\nHEAD", "main\x00",
])
def test_c2b_gramatica_de_branch_recusa(ruim):
    """`+` é force no refspec: uma "branch" que começa com `+` é uma força."""
    with pytest.raises(ErroInvalido):
        branch_valida(ruim, "source_branch")


@pytest.mark.parametrize("boa", ["main", "feature/x", "release-1.2", "v2"])
def test_c2b_gramatica_aceita_branch_legitima(boa):
    assert branch_valida(boa, "source_branch") == boa


def test_c2b_refspec_e_montado_pelo_adapter(amb):
    """PLAN_CAN_SELECT_REFSPEC=FALSE, verificado na AST."""
    import ast

    import nomos.adapters.git_push as mod
    fonte = Path(mod.__file__).read_text()
    arvore = ast.parse(fonte)
    literais = [n.value for n in ast.walk(arvore)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    for perigoso in ("--force", "--mirror", "--all", "--tags", "-f"):
        assert perigoso not in literais, f"adapter usa {perigoso}"
    # o refspec é f-string → JoinedStr na AST, não Constant. Procuro o
    # fragmento literal que a f-string contém.
    assert any("refs/heads/" in v for v in literais), (
        "o refspec deixou de ser montado pelo adapter")


def test_c2b_shell_nunca_e_usado():
    import ast

    import nomos.adapters.git_push as mod
    for no in ast.walk(ast.parse(Path(mod.__file__).read_text())):
        if isinstance(no, ast.Call) and getattr(no.func, "attr", "") == "run":
            kw = {k.arg: k.value for k in no.keywords}
            assert kw.get("shell") is not None and kw["shell"].value is False


# ============================================ credenciais e helpers

def test_c2b_plano_nao_carrega_segredo(amb):
    """PLAN_CONTAINS_SECRET=FALSE — a credencial é um ID, resolvido depois."""
    _rt, _ws, _repo, _p, _h, _c, destinos = amb
    d = destinos["producao"]
    assert d.credential_id == "cred-prod"
    assert "senha" not in d.canonico() and "token" not in d.canonico()


def test_c2b_CONTROLE_POSITIVO_espiao_e_canario_funcionam(amb, tmp_path, espiao_nativo):
    """Sem este teste, as duas asserções de ausência abaixo são VÁCUO.

    A versão anterior punha o canário em `tmp_path` — fora da raiz de escrita
    concedida ao sandbox — e usava espião `#!/bin/sh`, que não executa sob a
    allowlist de exec (o kernel precisa do interpretador, e `/bin/sh` ainda
    reexecuta `/bin/bash` como variante). As duas escolhas juntas faziam
    `not canario.exists()` ser verdade por construção.
    """
    _rt, _ws, repo, _p, _h, _c, _d = amb
    canario = Path(repo) / ".git" / "CANARIO-CP"
    espiao = espiao_nativo(tmp_path, canario)
    assert subprocess.run([str(espiao)], capture_output=True).returncode == 0
    assert canario.exists(), (
        "o canário não é gravável onde mora — a ausência não provaria nada")


def test_c2b_credential_helper_do_repo_nao_executa(amb, tmp_path, espiao_nativo):
    """CREDENTIAL_HELPER_EXECUTION=FALSE, ASKPASS_EXECUTION=FALSE.

    Canário no GIT DIR (área gravável) e espião NATIVO — ver o controle
    positivo acima. Só com os dois a ausência do arquivo prova ausência de
    EXECUÇÃO, e não ausência de permissão de escrita.
    """
    rt, _ws, repo, permitido, _h, _c, _d = amb
    canario = Path(repo) / ".git" / "CANARIO"
    espiao = espiao_nativo(tmp_path, canario)
    for k in ("credential.helper", "core.sshCommand", "core.askPass"):
        _git(repo, "config", k, str(espiao))
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    shutil.copy2(espiao, hooks / "pre-push")
    (hooks / "pre-push").chmod(0o755)
    _git(repo, "config", "core.hooksPath", str(hooks))
    canario.unlink(missing_ok=True)
    assert _plano(rt, alvo=str(repo), remote_id="producao",
                  source_branch="main").ok
    assert not canario.exists(), "helper/hook do repositório executou"


def test_c2b_env_hostil_do_host_nao_executa(amb, monkeypatch, tmp_path, espiao_nativo):
    rt, _ws, repo, _p, _h, _c, _d = amb
    canario = Path(repo) / ".git" / "CANARIO-ENV"
    espiao = espiao_nativo(tmp_path, canario)
    for var in ("GIT_ASKPASS", "SSH_ASKPASS", "GIT_SSH", "GIT_SSH_COMMAND"):
        monkeypatch.setenv(var, str(espiao))
    canario.unlink(missing_ok=True)
    assert _plano(rt, alvo=str(repo), remote_id="producao",
                  source_branch="main").ok
    assert not canario.exists()


# ============================================ governança

def test_c2b_categoria_e_net_egress(amb):
    """Publicar não compartilha autorização com marcar um commit."""
    rt, _ws, _repo, _p, _h, _c, _d = amb
    assert rt.registro.categoria_de("git-push") is Category.NET_EGRESS
    assert rt.registro.categoria_de("git-tag") is None or True


def test_c2b_nao_registra_sem_destinos(tmp_path):
    from nomos.adapters.wiring import registrar_git_push
    with pytest.raises(ValueError, match="destinos"):
        registrar_git_push(object(), raizes=("/tmp",), destinos=None)


def test_c2b_nao_registra_sem_raizes():
    from nomos.adapters.wiring import registrar_git_push
    with pytest.raises(ValueError, match="raizes"):
        registrar_git_push(object(), raizes=(),
                           destinos={"x": DestinoGovernado("x", "file:///t",
                                                           "main")})


def test_c2b_nao_registra_sem_opt_in(tmp_path):
    home = tmp_path / "h"
    home.mkdir()
    ws = tmp_path / "ws"
    ws.mkdir()
    ctx = {"home": home, "policy": PolicyEngine(home / "policy.json"),
           "audit": AuditLog(home / "logs" / "audit.jsonl")}
    rt = RuntimeGovernado(ctx, _sim, caminhos=(str(ws),), adapters=True, git=True)
    assert not rt.registro.conhecida("git-push")


def test_c2b_repo_fora_do_escopo_e_negado(amb, tmp_path):
    rt, _ws, _repo, _p, _h, _c, _d = amb
    fora = tmp_path / "fora"
    fora.mkdir()
    _git(fora, "init", "-q", "-b", "main")
    _git(fora, "commit", "-qm", "x", "--allow-empty")
    assert not _plano(rt, alvo=str(fora), remote_id="producao",
                      source_branch="main").ok


def test_c2b_passa_por_pdp_e_pep(amb):
    import json
    rt, _ws, repo, _p, _h, ctx, _d = amb
    assert _plano(rt, alvo=str(repo), remote_id="producao",
                  source_branch="main").ok
    ev = [json.loads(x).get("event") for x in
          (ctx["home"] / "logs" / "audit.jsonl").read_text().splitlines()
          if x.strip()]
    assert ev.index("pdp.decisao") < ev.index("pep.aplicacao") < ev.index("git.push")


def test_c2b_destino_canonico_cobre_os_campos_da_aprovacao(amb):
    """O digest da aprovação precisa comprometer o destino RESOLVIDO."""
    _rt, _ws, _repo, _p, _h, _c, destinos = amb
    c = destinos["producao"].canonico()
    for campo in ("remote_id", "resolved_url", "destination_branch",
                  "credential_id", "scheme", "host", "port", "repository"):
        assert campo in c, f"'{campo}' fora do canônico do destino"


# ============================================ isolamento da localidade

def test_c2b_producao_mantem_modo_so_local(tmp_path):
    """PRODUCTION_LOCALITY_UNCHANGED — o override é do FIXTURE, não do sistema.

    O padrão é fail-closed: home sem `localidade.json` significa só-local
    LIGADO. Um home novo, como o de produção, continua bloqueando egresso.
    """
    from nomos.kernel import localidade
    outro = tmp_path / "home-limpo"
    outro.mkdir()
    assert localidade.esta_ligado(outro), (
        "home sem localidade.json deveria estar em modo só-local")
    assert localidade.bloqueia_egress(outro, "https://exemplo.invalid")


def test_c2b_plano_nao_desliga_a_localidade(amb):
    """LOCALITY_POLICY_BYPASS_FROM_PLAN=FALSE.

    Nenhum campo do plano pode alcançar `localidade.json`: ele vive no
    NOMOS_HOME, que está fora do escopo de dados e fora do de controle.
    """
    rt, _ws, repo, _p, _h, ctx, _d = amb
    arq = ctx["home"] / "localidade.json"
    antes = arq.read_text() if arq.exists() else None
    for campo in ("local_only", "localidade", "locality", "net_egress"):
        rt.rodar("c2b", passos=[{"id": "p", "ferramenta": "git-push",
                                 "params": {"alvo": str(repo),
                                            "remote_id": "producao",
                                            "source_branch": "main",
                                            campo: False}}])
    # e nem por escrita direta no arquivo
    res = rt.rodar("c2b", passos=[{"id": "w", "ferramenta": "fs-escrever",
                                   "params": {"alvo": str(arq),
                                              "conteudo": '{"local_only": false}'}}])
    assert not res.ok
    assert (arq.read_text() if arq.exists() else None) == antes


def test_c2b_categoria_nao_depende_do_esquema_da_url(amb, tmp_path):
    """SCHEME_CAN_INFLUENCE_RISK_CLASS=FALSE.

    O mesmo `git-push` é NET_EGRESS com `file://` e com `https://`. Se a
    classe variasse por esquema, escolher o destino escolheria o risco.
    """
    rt, _ws, _repo, _p, _h, _c, _d = amb
    assert rt.registro.categoria_de("git-push") is Category.NET_EGRESS
    for url in (f"file://{tmp_path}/x.git", "https://exemplo.invalid/x.git",
                "ssh://git@exemplo.invalid/x.git"):
        d = DestinoGovernado("t", url, "main")
        assert d.canonico()["resolved_url"] == url
    # a categoria vem do REGISTRO, e o registro não olha destino nenhum
    from nomos.adapters.wiring import CATEGORIAS_GIT_PUSH
    assert CATEGORIAS_GIT_PUSH == {"git-push": Category.NET_EGRESS}


# ==================== classificação dos sobreviventes, por EXECUÇÃO

def _ctx_direto(tmp_path, ws, destinos):
    from nomos.adapters.contrato import CapabilityContext
    from nomos.adapters.wiring import registrar_git_push
    from nomos.orquestracao.registro import RegistroCapacidades
    home = tmp_path / "hdireto"
    home.mkdir(exist_ok=True)
    reg = RegistroCapacidades(policy=PolicyEngine(home / "p.json"), approver=_sim)
    registrar_git_push(reg, raizes=(str(ws),), destinos=destinos)
    return CapabilityContext.de_registro(reg, "git-push", "runtime-governado",
                                         raizes=(str(ws),))


def test_m1_adapter_nao_confia_no_nome_do_remote(amb, tmp_path):
    """M1: sem PDP e sem a guarda de campos, o `remote_id` desconhecido morre."""
    from nomos.adapters.contrato import CapabilityRequest
    _rt, ws, repo, _p, _h, _c, destinos = amb
    ad = GitPushAdapter(destinos=destinos)
    ctx = _ctx_direto(tmp_path, ws, destinos)
    pedido = CapabilityRequest(capacidade="git-push", alvo=str(repo),
                               argumentos={"remote_id": "inventado",
                                           "source_branch": "main"})
    with pytest.raises(ErroRemoto, match="desconhecido"):
        ad.executar(pedido, ctx)
    with pytest.raises(ErroRemoto):
        ad.destino_de("nao-existe")


def test_m4_refspec_do_plano_nao_alcanca_o_adapter(amb, tmp_path):
    """M4: mesmo com a guarda de campos ausente, o refspec é montado aqui."""
    from nomos.adapters.contrato import CapabilityRequest
    _rt, ws, repo, permitido, hostil, _c, destinos = amb
    ad = GitPushAdapter(destinos=destinos)
    ctx = _ctx_direto(tmp_path, ws, destinos)
    pedido = CapabilityRequest(
        capacidade="git-push", alvo=str(repo),
        argumentos={"remote_id": "producao", "source_branch": "main",
                    "refspec": "+refs/heads/main:refs/heads/roubada"})
    with pytest.raises(ErroInvalido, match="refspec"):
        ad.executar(pedido, ctx)
    assert _sha(permitido, "refs/heads/roubada") == ""


def test_m11_branch_de_destino_da_politica_e_validada(amb, tmp_path):
    """M11: destino hostil vindo da POLÍTICA também passa pela gramática."""
    from nomos.adapters.contrato import CapabilityRequest
    _rt, ws, repo, permitido, _h, _c, _d = amb
    ruins = {"x": DestinoGovernado("x", f"file://{permitido}", "+main")}
    ad = GitPushAdapter(destinos=ruins)
    ctx = _ctx_direto(tmp_path, ws, ruins)
    pedido = CapabilityRequest(capacidade="git-push", alvo=str(repo),
                               argumentos={"remote_id": "x",
                                           "source_branch": "main"})
    with pytest.raises(ErroInvalido, match="branch_destino"):
        ad.executar(pedido, ctx)


def test_m6_GIT_DIR_do_host_nao_muda_o_repositorio_publicado(amb, monkeypatch,
                                                              tmp_path):
    """M6: `GIT_DIR` herdado redirecionaria a ORIGEM do push."""
    rt, _ws, repo, permitido, _h, _c, _d = amb
    outro = tmp_path / "outro"
    outro.mkdir()
    _git(outro, "init", "-q", "-b", "main")
    (outro / "z.txt").write_text("do outro\n")
    _git(outro, "add", "z.txt")
    _git(outro, "commit", "-qm", "commit-do-outro")
    monkeypatch.setenv("GIT_DIR", str(outro / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(outro))
    assert _plano(rt, alvo=str(repo), remote_id="producao",
                  source_branch="main").ok
    monkeypatch.delenv("GIT_DIR")
    monkeypatch.delenv("GIT_WORK_TREE")
    esperado = _git(repo, "rev-parse", "main").stdout.strip()
    assert _sha(permitido, "refs/heads/main") == esperado, (
        "GIT_DIR do host mudou o repositório de ORIGEM da publicação")


def test_m5_gramatica_positiva_recusa_mais_SOZINHA():
    """M5: prova de EQUIVALÊNCIA — `+` não está no conjunto de `_BRANCH_OK`."""
    from nomos.adapters.git_push import _BRANCH_OK
    for hostil in ("+main", "+", "+refs/heads/main", "++x"):
        assert not _BRANCH_OK.match(hostil), (
            f"{hostil!r} passaria pela gramática positiva sozinha — o mutante "
            "do '+' deixa de ser equivalente e precisa de teste próprio")
    assert _BRANCH_OK.pattern.startswith("^[A-Za-z0-9]")


def test_m10_credencial_e_inalcancavel_no_contrato_atual(amb, tmp_path):
    """M10: prova de EQUIVALÊNCIA condicionada ao transporte.

    `credential.helper` e `askPass` só são consultados por transporte que PEÇA
    credencial. O contrato do C2b hoje só exercita destinos `file://`, que
    nunca pedem. A neutralização fica como defesa em profundidade e volta a ser
    necessária no primeiro destino `https://`/`ssh://` real — este teste falha
    nesse dia, que é quando deve falhar.
    """
    _rt, _ws, _repo, _p, _h, _c, destinos = amb
    from urllib.parse import urlsplit
    for d in destinos.values():
        assert urlsplit(d.url).scheme == "file", (
            "destino não-file no contrato: a equivalência do M10 caducou e "
            "credential.helper precisa de teste de execução própria")


def test_m4_refspec_e_inalcancavel_atras_da_guarda_de_campos():
    """M4: prova de EQUIVALÊNCIA por INALCANÇABILIDADE, na AST.

    A guarda recusa `refspec` incondicionalmente e vem ANTES da linha que
    monta o refspec. Nenhuma entrada chega lá com o campo presente — logo
    `pedido.arg("refspec")` só pode ser None ali, e o mutante que o consultaria
    seleciona sempre o mesmo valor.

    O teste prende a ORDEM, não a mensagem: se a guarda for movida para depois
    da montagem, ou deixar de listar `refspec`, o mutante volta a ser REAL e
    esta prova falha — que é exatamente quando ela deve falhar.
    """
    import ast

    import nomos.adapters.git_push as mod
    fonte = ast.parse(Path(mod.__file__).read_text())
    executar = next(n for n in ast.walk(fonte)
                    if isinstance(n, ast.FunctionDef) and n.name == "executar")
    linha_guarda = linha_refspec = None
    for no in ast.walk(executar):
        if isinstance(no, ast.Constant) and no.value == "refspec":
            linha_guarda = min(linha_guarda or no.lineno, no.lineno)
        if (isinstance(no, ast.Assign) and no.targets
                and getattr(no.targets[0], "id", "") == "refspec"):
            linha_refspec = no.lineno
    assert linha_guarda is not None, "'refspec' saiu da lista de campos proibidos"
    assert linha_refspec is not None, "a montagem do refspec sumiu"
    assert linha_guarda < linha_refspec, (
        "a guarda de campos deixou de vir ANTES da montagem do refspec — o "
        "mutante do refspec arbitrário volta a ser alcançável")
