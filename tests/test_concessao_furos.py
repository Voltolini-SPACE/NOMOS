"""Os furos que a revisão adversarial achou no mecanismo de concessão.

Todos foram CONFIRMADOS por medição antes de serem corrigidos. Cada teste
descreve o cenário concreto de falha — sem cenário, não é furo, é opinião.
"""
from __future__ import annotations

import json
import time

import pytest

from nomos.kernel.concessoes import ConcessaoError, RegistroConcessoes
from nomos.kernel.policy import Category, PolicyEngine
from nomos.orquestracao.registro import RegistroCapacidades
from nomos.pdp.aprovacao import OperacaoAprovavel

OP = OperacaoAprovavel(sujeito="registro", capacidade="fs-ler",
                       recurso="registro:fs-ler", classe_de_risco="A0")


# ------------------------------------------------------------------ TTL
@pytest.mark.parametrize("ttl", [float("inf"), float("nan"), -1, 0])
def test_ttl_nao_finito_e_recusado(tmp_path, ttl):
    """`--ttl-dias inf` gravava `expira_em: Infinity` — concessão PERPÉTUA.

    Pior: `capacidades listar` morria com OverflowError ao calcular os dias
    restantes, então as perpétuas ficavam invisíveis no único comando de
    inventário — o dono não conseguia nem ver o que revogar.
    """
    with pytest.raises(ConcessaoError):
        RegistroConcessoes(tmp_path / "c.json").conceder(OP, ttl_dias=ttl)


def test_expira_em_infinito_no_DISCO_nao_vale(tmp_path):
    """Defesa em profundidade: arquivo adulterado à mão não concede eternidade."""
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"versao": 1, "concessoes": {
        "d1": {"digest": "d1", "capacidade": "fs-ler", "expira_em": float("inf")}}}))
    assert RegistroConcessoes(p).vigente("d1") is False


# ------------------------------------------- vigente() não pode ESCREVER
def test_vigente_nao_escreve_no_caminho_de_leitura(tmp_path):
    """`vigente()` apagava+regravava ao expirar — no caminho de LEITURA.

    Cenário real: o dono roda `capacidades revogar --tudo` com o agendador no
    ar. A leitura concorrente do agendador regravava o arquivo com o conteúdo
    que ele tinha lido ANTES, ressuscitando concessões recém-revogadas. A CLI
    dizia "5 revogada(s)" e 4 voltavam. Revogação que mente é pior que
    revogação nenhuma.
    """
    relogio = {"t": 1000.0}
    p = tmp_path / "c.json"
    conc = RegistroConcessoes(p, clock=lambda: relogio["t"])
    conc.conceder(OP, ttl_dias=1)

    relogio["t"] += 2 * 86400                      # já expirou
    antes = p.stat().st_mtime_ns
    time.sleep(0.01)
    leitor = RegistroConcessoes(p, clock=lambda: relogio["t"])
    assert leitor.vigente(OP.digest()) is False     # a propriedade se mantém
    assert p.stat().st_mtime_ns == antes, "leitura NÃO pode escrever"


def test_expiradas_sao_varridas_por_quem_ja_escreve(tmp_path):
    relogio = {"t": 1000.0}
    conc = RegistroConcessoes(tmp_path / "c.json", clock=lambda: relogio["t"])
    conc.conceder(OP, ttl_dias=1)
    relogio["t"] += 2 * 86400
    outra = OperacaoAprovavel(sujeito="registro", capacidade="fs-listar",
                              recurso="registro:fs-listar", classe_de_risco="A0")
    conc.conceder(outra, ttl_dias=30)              # este escreve => varre
    vivas = {e["capacidade"] for e in conc.listar()}
    assert vivas == {"fs-listar"}


# ------------------------------------------------ temporário imprevisível
def test_temporario_nao_tem_nome_previsivel(tmp_path):
    """`concessoes.tmp` era nome fixo: quem o plantasse como symlink fazia o
    NOMOS sobrescrever arquivo arbitrário (`write_text` segue symlink), e dois
    processos concorrentes consumiam o tmp um do outro."""
    p = tmp_path / "concessoes.json"
    RegistroConcessoes(p).conceder(OP, ttl_dias=1)
    assert not (tmp_path / "concessoes.tmp").exists()
    assert not list(tmp_path.glob("*.tmp")), "nenhum lixo previsível pode sobrar"


# --------------------------------------------- o ESCOPO entra no digest
def test_raizes_diferentes_produzem_digests_diferentes(tmp_path):
    """A CLI imprime "raízes: <...>" para o dono ler ANTES de aprovar.

    Sem o escopo no digest, uma concessão dada lendo "raízes: ~/dados" era
    byte-idêntica à de um registro com `raizes=("/",)` — e como `fs-ler` é
    A0=ALLOW na execução, o resultado seria leitura de qualquer arquivo do
    disco sem uma única aprovação. É o "a UI mostra A e o sistema assina B".
    """
    pol = PolicyEngine(tmp_path / "policy.json")

    def digest_com(raizes):
        r = RegistroCapacidades(policy=pol, approver=lambda _d: True,
                                audit=None, escopo_dados=raizes)
        return r.operacao_de_registro("fs-ler", Category.READ_LOCAL,
                                      "adapters.filesystem", True).digest()

    estreito = digest_com((str(tmp_path / "dados"),))
    largo = digest_com(("/",))
    assert estreito != largo, "escopo tem de entrar no digest"
    assert digest_com((str(tmp_path / "dados"),)) == estreito   # determinístico
