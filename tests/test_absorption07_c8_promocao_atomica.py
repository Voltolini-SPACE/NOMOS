"""C8 — a promoção da quarentena é TUDO OU NADA.

A0.3 pôs os objetos numa quarentena e só os promove ao store permanente no
ponto de commit da transação. A promoção em si, porém, era um laço de
`os.replace`: cada movimento atômico sozinho, o CONJUNTO não.

MEDIDO, com `ENOSPC` injetado no sexto de doze objetos:

    operação RECUSADA (OSError), índice restaurado byte a byte
    5 blobs com `AWS_SECRET_ACCESS_KEY=...` LEGÍVEIS no store permanente
    `git fsck` os confirma como `dangling blob`

O rollback do índice funcionava — e mascarava o vazamento. Objeto inalcançável
não é objeto ausente: continua legível por `git cat-file` até um `gc`, e é
exatamente o resíduo que A0.3 existe para impedir.

## Por que COPIAR, e o invariante que decidiu isso

A promoção CRIA o destino sem destruir a origem — assim desfazer é apagar os
destinos criados, e a quarentena segue intacta para o `rmtree` do chamador.
Mover exigiria mover de volta, e um segundo erro durante o desfazer deixaria o
estado pior que o inicial.

`os.link` faria isso de graça, e foi a PRIMEIRA implementação desta correção.
`test_c6_nenhuma_capacidade_governada_cria_hardlink` a reprovou — e estava
certo: aquele invariante é a premissa que torna aceitável a leitura por hardlink
dentro da raiz (`test_c6_hardlink_dentro_da_raiz_e_lido`). Enfraquecê-lo para
economizar uma cópia trocaria garantia de fronteira por I/O de objeto solto.

Cada objeto é publicado atomicamente: copia para temporário no MESMO diretório,
depois `os.replace` para o nome final. Sem isso, um destino parcialmente escrito
ficaria visível com nome de objeto válido — e objeto truncado é corrupção
silenciosa do store.

Atomicidade real entre N arquivos não existe no POSIX. O que se garante é que
nenhum objeto fica VISÍVEL no store permanente quando a promoção não completa.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from nomos.adapters import git_tree, supervisor
from nomos.adapters.contrato import CapabilityContext, CapabilityRequest
from nomos.adapters.git import diretorio_git
from nomos.adapters.wiring import registrar_git_tree
from nomos.kernel.policy import PolicyEngine
from nomos.orquestracao.registro import RegistroCapacidades

GIT = "/usr/bin/git"
SEGREDO = b"AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI"
N = 12

pytestmark = pytest.mark.skipif(
    not os.path.exists(supervisor.SANDBOX),
    reason="sem sandbox-exec não há execução supervisionada neste host")


@pytest.fixture
def cen(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run([GIT, "init", "-q", "-b", "main", str(repo)], check=True,
                   capture_output=True)
    # VÁRIOS arquivos: com um só, "parcial" não existe como estado, e o teste
    # não conseguiria distinguir tudo-ou-nada de sorte.
    for i in range(N):
        (repo / f"f{i}.txt").write_bytes(SEGREDO + b"\n" + str(i).encode())

    class Cen:
        def __init__(self):
            self.repo, self.tmp = repo, tmp_path
            self.caminhos = [f"f{i}.txt" for i in range(N)]

        def ctx(self):
            rc = RegistroCapacidades(policy=PolicyEngine(tmp_path / "pol.json"),
                                     approver=lambda *a, **k: True)
            registrar_git_tree(rc, raizes=(str(tmp_path),))
            return CapabilityContext.de_registro(rc, "git-add",
                                                 "runtime-governado",
                                                 raizes=(str(tmp_path),))

        def add(self, *caminhos):
            return git_tree.GitTreeAdapter().executar(
                CapabilityRequest(capacidade="git-add", alvo=str(repo),
                                  argumentos={"caminhos": list(caminhos)}),
                self.ctx())

        def indice(self):
            alvo = Path(diretorio_git(repo)[0]) / "index"
            return alvo.read_bytes() if alvo.exists() else None

        def objetos_com_segredo(self) -> int:
            return subprocess.run(
                [GIT, "-C", str(repo), "cat-file", "--batch-all-objects",
                 "--batch"], capture_output=True).stdout.count(SEGREDO)

        def pendurados(self) -> int:
            r = subprocess.run([GIT, "-C", str(repo), "fsck", "--no-progress"],
                               capture_output=True, text=True)
            return r.stdout.count("dangling")

    return Cen()


# ═══════ 01 — CONTROLE POSITIVO: a promoção REALMENTE promove ═══════════════

def test_c8_01_CONTROLE_POSITIVO_o_sucesso_promove_tudo(cen):
    """Sem isto, "nada vazou" nas falhas pode ser ausência de efeito nenhum."""
    r = cen.add(*cen.caminhos)
    assert r.efeito_aplicado
    assert cen.objetos_com_segredo() == N, (
        f"o caminho feliz promoveu {cen.objetos_com_segredo()} de {N} — sem "
        "promoção real, os testes de falha não medem contenção")


# ═══════ 02-04 — falha NO MEIO não deixa objeto no store ════════════════════

@pytest.mark.parametrize("falhar_no", [1, 5, N - 1])
def test_c8_02a04_falha_no_MEIO_da_promocao_nao_deixa_nada(cen, monkeypatch,
                                                           falhar_no):
    """O caso que a bateria A5.8 não cobria: promoção PARCIAL.

    A5.8 injetava falha ANTES da promoção inteira (`_promover_quarentena`
    levantando na entrada), o que nunca produzia estado parcial. Aqui a falha
    acontece com objetos JÁ promovidos.
    """
    antes = cen.indice()
    real = os.replace
    feitos = {"n": 0}

    def replace_que_falha(origem, destino, *a, **kw):
        if ".promovendo-" not in str(origem):
            return real(origem, destino, *a, **kw)
        feitos["n"] += 1
        if feitos["n"] > falhar_no:
            raise OSError(28, "No space left on device")
        return real(origem, destino, *a, **kw)

    monkeypatch.setattr(os, "replace", replace_que_falha)
    with pytest.raises(OSError):
        cen.add(*cen.caminhos)
    monkeypatch.undo()

    assert feitos["n"] > falhar_no, "a falha não chegou a ser exercida"
    assert cen.indice() == antes, "INDEX_DRIFT depois da recusa"
    assert cen.objetos_com_segredo() == 0, (
        f"PARTIAL_PROMOTION: {cen.objetos_com_segredo()} objeto(s) com o "
        "segredo ficaram no store permanente numa operação RECUSADA")
    assert cen.pendurados() == 0, "sobrou objeto pendurado (dangling)"


def test_c8_05_a_proxima_operacao_continua_sadia(cen, monkeypatch):
    """Desfazer não pode deixar o store num estado que impeça o próximo add."""
    real = os.replace
    feitos = {"n": 0}

    def replace_que_falha(origem, destino, *a, **kw):
        if ".promovendo-" not in str(origem):
            return real(origem, destino, *a, **kw)
        feitos["n"] += 1
        if feitos["n"] > 3:
            raise OSError(28, "cheio")
        return real(origem, destino, *a, **kw)

    monkeypatch.setattr(os, "replace", replace_que_falha)
    with pytest.raises(OSError):
        cen.add(*cen.caminhos)
    monkeypatch.undo()

    r = cen.add(*cen.caminhos)
    assert r.efeito_aplicado, "a operação seguinte não funcionou"
    assert cen.objetos_com_segredo() == N
    assert cen.pendurados() == 0


# ═══════ 06-08 — o destino e os nomes não são escolhidos pelo repo ══════════

def test_c8_06_objects_como_SYMLINK_para_fora_e_recusado(cen):
    """`.git/objects` apontando para fora faria a promoção escrever lá.

    A escrita acontece no processo do SUPERVISOR, fora do sandbox — o
    confinamento não a vê. Quem tem de recusar é esta função.
    """
    fora = cen.tmp / "store-alheio"
    fora.mkdir()
    objetos = Path(diretorio_git(cen.repo)[0]) / "objects"
    with pytest.raises(supervisor.ErroSeguranca, match="fora da raiz do store"):
        git_tree._promover_quarentena(cen.tmp / "q", fora,
                                      raiz_do_store=str(objetos.parent))


def test_c8_07_nome_fora_da_forma_de_objeto_e_recusado(cen):
    """Nome arbitrário na quarentena viraria caminho escolhido pelo repo."""
    q = cen.tmp / "q"
    (q / "sub").mkdir(parents=True)
    (q / "sub" / "config").write_text("[core]\n")
    reais = Path(diretorio_git(cen.repo)[0]) / "objects"
    with pytest.raises(supervisor.ErroSeguranca, match="forma de objeto"):
        git_tree._promover_quarentena(q, reais,
                                      raiz_do_store=diretorio_git(cen.repo)[1])


def test_c8_08_symlink_na_quarentena_e_recusado(cen):
    """`is_file()` SEGUE o link; `lstat` não. Sem isso, o destino do link seria
    promovido para dentro do store."""
    q = cen.tmp / "q2"
    (q / "ab").mkdir(parents=True)
    (q / "ab" / ("c" * 38)).symlink_to("/etc/passwd")
    reais = Path(diretorio_git(cen.repo)[0]) / "objects"
    with pytest.raises(supervisor.ErroSeguranca, match="não é arquivo regular"):
        git_tree._promover_quarentena(q, reais,
                                      raiz_do_store=diretorio_git(cen.repo)[1])


def test_c8_09_deduplicacao_nao_conta_como_criado(cen):
    """Objeto que JÁ era do store não pode ser apagado por um desfazer.

    Endereçado por conteúdo: mesmo sha, mesmos bytes. Se a dedup entrasse na
    lista de "criados", uma falha posterior removeria do store um objeto
    legítimo que não veio desta operação — corrupção causada pelo rollback.
    """
    assert cen.add(*cen.caminhos).efeito_aplicado
    antes = cen.objetos_com_segredo()

    def sempre_falha(origem, destino, *a, **kw):
        if ".promovendo-" in str(origem):
            raise OSError(28, "cheio")
        return os.replace.__wrapped__(origem, destino, *a, **kw)

    # Segundo `add` dos MESMOS arquivos: tudo é dedup, nada é criado, então a
    # promoção nem chega a copiar — e o store não pode encolher.
    real = os.replace
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(os, "replace",
                   lambda o, d, *a, **k: (_ for _ in ()).throw(OSError(28, "x"))
                   if ".promovendo-" in str(o) else real(o, d, *a, **k))
        cen.add(*cen.caminhos)
    assert cen.objetos_com_segredo() == antes, (
        "a dedup foi tratada como criação e o rollback apagou objeto do store")
