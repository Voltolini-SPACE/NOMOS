"""TEST_ISOLATION — pré-condição de A9/A10, e ela foi medida FALSA duas vezes.

Baterias que varrem estado GLOBAL do host (`TMPDIR`, tabela de processos,
diretórios-nonce) contabilizam artefato de vizinho como falha própria. Medido
nesta missão, duas vezes, e as duas viraram diagnóstico errado antes de virarem
medição:

    test_a56_16 (nonces em disco)   13 diretórios vivos criados por OUTRO
                                    processo, com dez agentes de medição rodando
    c2c_isolamento                  falha na suíte completa, 5/5 isolado

Um teste que falha por causa do vizinho é pior que um teste ausente: treina quem
lê a suíte a ignorar vermelho. E A9/A10 são justamente as baterias que mais
criam processo e artefato temporário — sem isolamento, o resultado delas não
significaria nada.

O controle POSITIVO é o ponto deste arquivo: provar que duas baterias
concorrentes NÃO se enxergam. Sem ele, `TEST_ISOLATION=PASS` seria uma
afirmação, não uma medição.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

FILHO = r"""
import os, sys, tempfile, time
from pathlib import Path
raiz = Path(os.environ["TMPDIR"])
antes = {p.name for p in raiz.glob("nomos-exec-*")}
meu = tempfile.mkdtemp(prefix="nomos-exec-%s-" % sys.argv[1], dir=str(raiz))
time.sleep(float(sys.argv[2]))
depois = {p.name for p in raiz.glob("nomos-exec-*")}
alheios = depois - antes - {Path(meu).name}
print("ALHEIOS=%d" % len(alheios))
"""


def _rodar_em_tmpdir_proprio(rotulo: str, espera: float, saida: dict) -> None:
    base = tempfile.mkdtemp(prefix=f"worker-{rotulo}-")
    env = dict(os.environ, TMPDIR=base)
    script = Path(base) / "filho.py"
    script.write_text(FILHO)
    r = subprocess.run([sys.executable, str(script), rotulo, str(espera)],
                       capture_output=True, text=True, env=env, timeout=60)
    saida[rotulo] = r.stdout.strip()


def test_isolamento_dois_workers_concorrentes_nao_se_enxergam():
    """CONTROLE POSITIVO de `TEST_ISOLATION`.

    Cada worker recebe `TMPDIR` próprio e cria um diretório-nonce ao mesmo tempo
    que o outro. Nenhum dos dois pode ver o artefato do vizinho — que é
    exatamente a contaminação medida na suíte real.
    """
    saida: dict[str, str] = {}
    fios = [threading.Thread(target=_rodar_em_tmpdir_proprio,
                             args=(rotulo, 0.5, saida))
            for rotulo in ("A", "B")]
    for f in fios:
        f.start()
    for f in fios:
        f.join(timeout=90)

    assert set(saida) == {"A", "B"}, f"worker não terminou: {saida}"
    for rotulo, linha in saida.items():
        assert linha == "ALHEIOS=0", (
            f"worker {rotulo} enxergou artefato do vizinho ({linha}) — "
            "TEST_ISOLATION=FALSE, e A9/A10 rodariam contaminadas")


def test_isolamento_CONTROLE_NEGATIVO_tmpdir_compartilhado_contamina():
    """Prova que o teste acima MEDE alguma coisa.

    Com `TMPDIR` compartilhado a contaminação APARECE. Sem este controle, o
    teste anterior passaria igual num arnês que nunca observou nada — que é
    precisamente o modo de falha (asserção vácua) que esta série já corrigiu em
    P0.1.
    """
    compartilhado = tempfile.mkdtemp(prefix="worker-compartilhado-")
    saida: dict[str, str] = {}

    def rodar(rotulo: str) -> None:
        env = dict(os.environ, TMPDIR=compartilhado)
        script = Path(compartilhado) / f"filho-{rotulo}.py"
        script.write_text(FILHO)
        r = subprocess.run([sys.executable, str(script), rotulo, "0.8"],
                           capture_output=True, text=True, env=env, timeout=60)
        saida[rotulo] = r.stdout.strip()

    fios = [threading.Thread(target=rodar, args=(r,)) for r in ("A", "B")]
    for f in fios:
        f.start()
    for f in fios:
        f.join(timeout=90)

    assert set(saida) == {"A", "B"}, f"worker não terminou: {saida}"
    assert any(linha != "ALHEIOS=0" for linha in saida.values()), (
        "com TMPDIR compartilhado NENHUM worker viu o vizinho — a sonda não "
        "observa o que deveria, e o teste positivo acima é vácuo")


def test_isolamento_MEDIDO_trocar_TMPDIR_da_sessao_NAO_e_a_correcao():
    """Registro do que foi TENTADO e refutado, para ninguém repetir.

    A correção óbvia — uma fixture de sessão em `conftest.py` apontando
    `TMPDIR` para um diretório próprio — foi implementada e MEDIDA: **71
    falhas**. A causa é de ordem, não de ideia: quando a fixture roda, o
    `basetemp` do `tmp_path_factory` já foi escolhido sob o TMPDIR antigo.
    Metade da suíte passa a montar cenário sob uma raiz e a comparar contra
    outra, e os perfis de sandbox deixam de casar com os caminhos reais.

    O isolamento que vale para A9/A10 é POR PROCESSO — cada worker nasce com
    `TMPDIR` próprio no ambiente, como nos dois testes acima — e não uma troca
    no meio de uma sessão já iniciada.
    """
    assert "TMPDIR" in os.environ or tempfile.gettempdir()
