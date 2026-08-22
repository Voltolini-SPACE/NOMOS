"""ABSORPTION-03 / FASE 2 — filesystem amplo governado + suíte adversarial.

O critério não é "existe um módulo de filesystem". É: dado um escopo, NÃO EXISTE
alvo fora dele que produza leitura ou efeito. Cada teste abaixo é uma tentativa
de furo; quando o ataque funciona na vida real, o teste falha.

Os 14 ataques exigidos pela missão estão marcados com [Nx] no docstring.
"""
from __future__ import annotations

import dataclasses
import os
import time

import pytest

from nomos.adapters.caminho import dentro_do_escopo, resolver
from nomos.adapters.contrato import (
    CapabilityContext, CapabilityRequest, ErroEscopo, ErroInvalido, ErroLimite,
    ErroNaoEncontrado, ErroTimeout, versao_de_capacidade,
)
from nomos.adapters.filesystem import CAPACIDADES, FilesystemAdapter
from nomos.kernel.audit import AuditLog
from nomos.kernel.policy import Category, PolicyEngine
from nomos.orquestracao.registro import RegistroCapacidades


# ------------------------------------------------------------------ fixtures

class _RegistroFS:
    """Registro mínimo com as capacidades de FS — risco/idempotência daqui."""

    _RISCO = {
        "fs-ler": ("A0", True), "fs-listar": ("A0", True),
        "fs-metadados": ("A0", True),
        "fs-escrever": ("A1", False), "fs-editar": ("A1", False),
        "fs-criar-dir": ("A1", False), "fs-mover": ("A1", False),
        "fs-apagar": ("A1", False),
    }

    def conhecida(self, nome):
        return nome in self._RISCO

    def categoria_de(self, nome):
        if nome not in self._RISCO:
            return None
        return (Category.READ_LOCAL if self._RISCO[nome][0] == "A0"
                else Category.WRITE_LOCAL)

    def risco_de(self, nome):
        return self._RISCO.get(nome, ("A6", False))[0]

    def idempotente_de(self, nome):
        return self._RISCO.get(nome, ("A6", False))[1]

    def executor_de(self, nome):
        return None


@pytest.fixture()
def raiz(tmp_path):
    r = tmp_path / "raiz"
    r.mkdir()
    (r / "dentro.txt").write_text("linha1\nlinha2\nlinha3\n")
    (tmp_path / "fora.txt").write_text("SEGREDO")
    return r


@pytest.fixture()
def ctx_fabrica(tmp_path, raiz):
    audit = AuditLog(tmp_path / "logs" / "audit.jsonl")
    reg = _RegistroFS()

    def _fazer(cap="fs-ler", raizes=None, deadline=None):
        return CapabilityContext.de_registro(
            reg, cap, "teste",
            raizes=(str(raiz),) if raizes is None else raizes,
            home=str(tmp_path), deadline_monotonic=deadline, audit=audit)
    return _fazer


def _exec(cap, alvo="", ctx=None, **args):
    return FilesystemAdapter().executar(
        CapabilityRequest(capacidade=cap, alvo=alvo, argumentos=args), ctx)


# --------------------------------------------------- contrato (FASE 1)

def test_contexto_deriva_risco_e_idempotencia_do_registro(ctx_fabrica):
    ctx = ctx_fabrica("fs-escrever")
    assert ctx.risco == "A1"
    assert ctx.idempotente is False
    leitura = ctx_fabrica("fs-ler")
    assert leitura.risco == "A0"
    assert leitura.idempotente is True


def test_contexto_e_frozen_adapter_nao_reescreve_a_coleira(ctx_fabrica):
    ctx = ctx_fabrica("fs-escrever")
    for campo, valor in (("risco", "A0"), ("idempotente", True),
                         ("raizes", ("/",)), ("capacidade", "fs-ler")):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(ctx, campo, valor)


def test_capacidade_desconhecida_nao_gera_contexto():
    with pytest.raises(ErroInvalido):
        CapabilityContext.de_registro(_RegistroFS(), "shell_exec", "teste")


def test_adapter_recusa_pedido_incoerente_com_o_contexto(ctx_fabrica, raiz):
    ctx = ctx_fabrica("fs-ler")
    pedido = CapabilityRequest(capacidade="fs-apagar", alvo=str(raiz / "dentro.txt"))
    with pytest.raises(ErroEscopo, match="não corresponde"):
        FilesystemAdapter().executar(pedido, ctx)


def test_adapter_nao_serve_capacidade_fora_da_sua_lista(ctx_fabrica):
    ad = FilesystemAdapter()
    assert set(ad.capacidades) == set(CAPACIDADES)
    assert "shell_exec" not in ad.capacidades


# --------------------------------------------------- leitura útil (gap do censo)

def test_leitura_devolve_conteudo_de_verdade(ctx_fabrica, raiz):
    r = _exec("fs-ler", str(raiz / "dentro.txt"), ctx=ctx_fabrica("fs-ler"))
    assert r.ok
    assert "linha1" in r.valor and "linha3" in r.valor
    assert r.metadados["linhas_totais"] == 3
    assert r.efeito_aplicado is False


def test_leitura_com_offset_e_limite(ctx_fabrica, raiz):
    r = _exec("fs-ler", str(raiz / "dentro.txt"), ctx=ctx_fabrica("fs-ler"),
              offset=1, limite=1)
    assert r.valor == "linha2"


def test_leitura_de_binario_nao_finge_texto(ctx_fabrica, raiz):
    (raiz / "bin.dat").write_bytes(b"\x00\x01\x02binario")
    r = _exec("fs-ler", str(raiz / "bin.dat"), ctx=ctx_fabrica("fs-ler"))
    assert r.ok and r.valor is None
    assert r.metadados["binario"] is True


# --------------------------------------------------- ATAQUES 1-14

def test_n1_traversal_com_dotdot(ctx_fabrica, raiz, tmp_path):
    """[N1] `../`"""
    with pytest.raises(ErroEscopo):
        _exec("fs-ler", str(raiz / ".." / "fora.txt"), ctx=ctx_fabrica("fs-ler"))


def test_n2_absoluto_fora_do_root(ctx_fabrica, tmp_path):
    """[N2] caminho absoluto fora do root"""
    with pytest.raises(ErroEscopo):
        _exec("fs-ler", str(tmp_path / "fora.txt"), ctx=ctx_fabrica("fs-ler"))
    with pytest.raises(ErroEscopo):
        _exec("fs-ler", "/etc/passwd", ctx=ctx_fabrica("fs-ler"))


def test_n3_symlink_interno_apontando_para_fora(ctx_fabrica, raiz, tmp_path):
    """[N3] symlink interno → fora: o realpath cai fora, então é escape."""
    link = raiz / "link.txt"
    link.symlink_to(tmp_path / "fora.txt")
    with pytest.raises(ErroEscopo):
        _exec("fs-ler", str(link), ctx=ctx_fabrica("fs-ler"))


def test_n3b_diretorio_symlinkado_para_fora_nao_recebe_escrita(ctx_fabrica, raiz, tmp_path):
    """Variante: o LINK é um diretório e o arquivo ainda não existe.

    Assevera o MOTIVO: quem barra aqui é a checagem principal de escopo
    (`realpath` resolve o link intermediário), NÃO um guard de cadeia. Foi a
    bateria de mutação que revelou isso — a checagem de cadeia original era
    código morto e foi removida.
    """
    externo = tmp_path / "externo"
    externo.mkdir()
    (raiz / "dir").symlink_to(externo)
    with pytest.raises(ErroEscopo, match="fora do escopo autorizado"):
        _exec("fs-escrever", str(raiz / "dir" / "novo.txt"),
              ctx=ctx_fabrica("fs-escrever"), conteudo="x")
    assert not (externo / "novo.txt").exists()


def test_escrita_atraves_de_symlink_interno_e_recusada(ctx_fabrica, raiz):
    """Guard que substituiu o código morto — e este SIM é exercitado.

    O link fica DENTRO do escopo, então a checagem principal não barra. Mesmo
    assim recusamos: escrever em `atalho.txt` mudaria `real.txt`, um alvo que
    o chamador não nomeou.
    """
    real = raiz / "real.txt"
    real.write_text("original")
    atalho = raiz / "atalho.txt"
    atalho.symlink_to(real)
    with pytest.raises(ErroEscopo, match="symlink"):
        _exec("fs-escrever", str(atalho), ctx=ctx_fabrica("fs-escrever"),
              conteudo="invadido")
    assert real.read_text() == "original"


def test_leitura_atraves_de_symlink_interno_e_permitida(ctx_fabrica, raiz):
    """Simetria proposital: LER via link interno é inócuo e continua valendo —
    a recusa é só para mutação."""
    real = raiz / "r2.txt"
    real.write_text("conteudo")
    link = raiz / "l2.txt"
    link.symlink_to(real)
    assert _exec("fs-ler", str(link), ctx=ctx_fabrica("fs-ler")).valor == "conteudo"


def test_n4_symlink_trocado_apos_validacao(ctx_fabrica, raiz, tmp_path):
    """[N4] symlink race reproduzível: valida um alvo, troca o link, relê.
    A segunda resolução tem de barrar — não há cache de decisão."""
    alvo = raiz / "movel.txt"
    alvo.write_text("interno")
    ctx = ctx_fabrica("fs-ler")
    assert _exec("fs-ler", str(alvo), ctx=ctx).ok
    alvo.unlink()
    alvo.symlink_to(tmp_path / "fora.txt")
    with pytest.raises(ErroEscopo):
        _exec("fs-ler", str(alvo), ctx=ctx)


def test_n5_rename_para_fora(ctx_fabrica, raiz, tmp_path):
    """[N5] mover para fora do escopo"""
    with pytest.raises(ErroEscopo):
        _exec("fs-mover", str(raiz / "dentro.txt"), ctx=ctx_fabrica("fs-mover"),
              destino=str(tmp_path / "roubado.txt"))
    assert not (tmp_path / "roubado.txt").exists()


def test_n6_delete_fora(ctx_fabrica, tmp_path):
    """[N6] apagar fora do escopo"""
    with pytest.raises(ErroEscopo):
        _exec("fs-apagar", str(tmp_path / "fora.txt"), ctx=ctx_fabrica("fs-apagar"))
    assert (tmp_path / "fora.txt").exists()


def test_n7_glob_escapando_root(ctx_fabrica, raiz, tmp_path):
    """[N7] glob com padrão de escape não vaza nada de fora."""
    r = _exec("fs-listar", str(raiz), ctx=ctx_fabrica("fs-listar"),
              padrao="../*")
    caminhos = [i["caminho"] for i in r.valor]
    assert not any("fora.txt" in c for c in caminhos), caminhos


def test_n8_arquivo_gigante(ctx_fabrica, raiz, monkeypatch):
    """[N8] arquivo acima do teto ⇒ ErroLimite, não OOM."""
    grande = raiz / "grande.bin"
    grande.write_bytes(b"x" * 1024)
    monkeypatch.setattr("nomos.adapters.filesystem.LIMITE_LEITURA_BYTES", 100)
    with pytest.raises(ErroLimite):
        _exec("fs-ler", str(grande), ctx=ctx_fabrica("fs-ler"))


def test_n9_arquivo_inexistente(ctx_fabrica, raiz):
    """[N9]"""
    with pytest.raises(ErroNaoEncontrado):
        _exec("fs-ler", str(raiz / "nao-existe.txt"), ctx=ctx_fabrica("fs-ler"))


# `os.geteuid` é POSIX-only: chamá-lo no DECORATOR (nível de módulo) fazia a
# coleta inteira do pytest abortar no Windows com AttributeError — 1 módulo
# derrubava a suíte toda do runner. `getattr` mantém a intenção (root ignora
# permissão) e degrada para "não é root" onde a função não existe.
@pytest.mark.skipif(getattr(os, "geteuid", lambda: 1)() == 0,
                    reason="root ignora permissões")
@pytest.mark.permissao_unix
def test_n10_permissao_negada(ctx_fabrica, raiz):
    """[N10] erro TIPADO, não vazamento de stacktrace."""
    p = raiz / "sem-permissao.txt"
    p.write_text("x")
    p.chmod(0o000)
    try:
        with pytest.raises((ErroInvalido, Exception)) as exc:
            _exec("fs-ler", str(p), ctx=ctx_fabrica("fs-ler"))
        assert "Permissao" in type(exc.value).__name__ or "Erro" in type(exc.value).__name__
    finally:
        p.chmod(0o600)


def test_n11_escopo_expirado_pelo_deadline(ctx_fabrica, raiz):
    """[N11] prazo do nó estourado ⇒ nem começa."""
    ctx = ctx_fabrica("fs-ler", deadline=time.monotonic() - 1)
    with pytest.raises(ErroTimeout):
        _exec("fs-ler", str(raiz / "dentro.txt"), ctx=ctx)


def test_n12_autorizacao_valida_para_outro_caminho(ctx_fabrica, raiz, tmp_path):
    """[N12] escopo é de OUTRA raiz ⇒ alvo legítimo aqui é negado lá."""
    outra = tmp_path / "outra"
    outra.mkdir()
    ctx = ctx_fabrica("fs-ler", raizes=(str(outra),))
    with pytest.raises(ErroEscopo):
        _exec("fs-ler", str(raiz / "dentro.txt"), ctx=ctx)


def test_n13_replay_de_leitura_nao_produz_efeito(ctx_fabrica, raiz):
    """[N13] replay: reexecutar leitura é inócuo, e escrita repetida é
    idempotente no conteúdo — mas nenhuma delas ganha autoridade nova."""
    ctx = ctx_fabrica("fs-ler")
    a = _exec("fs-ler", str(raiz / "dentro.txt"), ctx=ctx)
    b = _exec("fs-ler", str(raiz / "dentro.txt"), ctx=ctx)
    assert a.valor == b.valor
    assert a.efeito_aplicado is False and b.efeito_aplicado is False


def test_n14_capacidade_trocada_apos_assinatura(ctx_fabrica, raiz):
    """[N14] contexto assinado para fs_ler não serve para fs_apagar."""
    ctx = ctx_fabrica("fs-ler")
    with pytest.raises(ErroEscopo):
        FilesystemAdapter().executar(
            CapabilityRequest(capacidade="fs-apagar", alvo=str(raiz / "dentro.txt")),
            ctx)
    assert (raiz / "dentro.txt").exists()


# --------------------------------------------------- caller não afrouxa escopo

def test_caller_nao_consegue_pedir_unsafe(ctx_fabrica, raiz, tmp_path):
    """Não existe unsafe=/skip_scope=/follow_symlink= — passar não muda nada."""
    for truque in ({"unsafe": True}, {"skip_scope": True},
                   {"follow_symlink": True}, {"raizes": ("/",)}):
        with pytest.raises(ErroEscopo):
            _exec("fs-ler", str(tmp_path / "fora.txt"),
                  ctx=ctx_fabrica("fs-ler"), **truque)


def test_resolver_recusa_alvo_vazio_ou_nulo():
    for ruim in ("", "   ", "a\x00b"):
        with pytest.raises(ErroInvalido):
            resolver(ruim, ("/tmp",))


def test_prefixo_parecido_nao_e_contencao(tmp_path):
    """`/x/raiz-outro` NÃO está sob `/x/raiz` — comparação por componente."""
    raiz = tmp_path / "raiz"
    raiz.mkdir()
    vizinho = tmp_path / "raiz-outro"
    vizinho.mkdir()
    (vizinho / "f.txt").write_text("x")
    assert not dentro_do_escopo(str(vizinho / "f.txt"), (str(raiz),))


def test_escopo_vazio_nao_restringe(tmp_path):
    """Herdado da 02: raízes vazias = sem restrição (decisão consciente)."""
    p = tmp_path / "qualquer.txt"
    p.write_text("x")
    assert resolver(str(p), ()) == p.resolve()


# --------------------------------------------------- mutação/atomicidade

def test_escrita_e_atomica_e_nao_deixa_temp(ctx_fabrica, raiz):
    r = _exec("fs-escrever", str(raiz / "novo.txt"),
              ctx=ctx_fabrica("fs-escrever"), conteudo="conteudo")
    assert r.ok and r.efeito_aplicado
    assert (raiz / "novo.txt").read_text() == "conteudo"
    assert not [p for p in raiz.iterdir() if p.name.startswith(".nomos-tmp-")]


def test_edicao_ambigua_e_recusada(ctx_fabrica, raiz):
    p = raiz / "amb.txt"
    p.write_text("alvo\nalvo\n")
    with pytest.raises(ErroInvalido, match="ambígua"):
        _exec("fs-editar", str(p), ctx=ctx_fabrica("fs-editar"),
              de="alvo", para="novo")
    assert p.read_text() == "alvo\nalvo\n"          # intacto


def test_edicao_sem_ocorrencia_falha_fechada(ctx_fabrica, raiz):
    p = raiz / "sem.txt"
    p.write_text("abc")
    with pytest.raises(ErroInvalido, match="não encontrado"):
        _exec("fs-editar", str(p), ctx=ctx_fabrica("fs-editar"),
              de="xyz", para="w")


def test_edicao_cirurgica_funciona(ctx_fabrica, raiz):
    p = raiz / "ed.txt"
    p.write_text("antes MARCA depois")
    r = _exec("fs-editar", str(p), ctx=ctx_fabrica("fs-editar"),
              de="MARCA", para="TROCADO")
    assert r.efeito_aplicado
    assert p.read_text() == "antes TROCADO depois"


def test_mover_e_apagar_dentro_do_escopo_funcionam(ctx_fabrica, raiz):
    origem = raiz / "m.txt"
    origem.write_text("x")
    _exec("fs-mover", str(origem), ctx=ctx_fabrica("fs-mover"),
          destino=str(raiz / "sub" / "m2.txt"))
    assert (raiz / "sub" / "m2.txt").exists() and not origem.exists()
    _exec("fs-apagar", str(raiz / "sub" / "m2.txt"), ctx=ctx_fabrica("fs-apagar"))
    assert not (raiz / "sub" / "m2.txt").exists()


def test_auditoria_registra_alvo_canonico(ctx_fabrica, raiz, tmp_path):
    """A trilha guarda o caminho RESOLVIDO, não o que o caller digitou.

    Compara o VALOR desserializado, e não substring do arquivo cru: a trilha é
    JSONL, e onde o separador de caminho é `\\` o JSON o escapa para `\\\\` —
    `str(raiz / "dentro.txt") in trilha` nunca casaria, por um detalhe de
    serialização e não pela propriedade sob teste. A propriedade (caminho
    canônico, sem `..`) é portável; a técnica de medir é que não era.
    """
    import json as _json

    sinuoso = str(raiz / "sub" / ".." / "dentro.txt")
    (raiz / "sub").mkdir(exist_ok=True)
    _exec("fs-ler", sinuoso, ctx=ctx_fabrica("fs-ler"))
    linhas = (tmp_path / "logs" / "audit.jsonl").read_text().splitlines()
    eventos = [_json.loads(x) for x in linhas if x.strip()]

    def _valores(obj):
        if isinstance(obj, dict):
            for v in obj.values():
                yield from _valores(v)
        elif isinstance(obj, list):
            for v in obj:
                yield from _valores(v)
        elif isinstance(obj, str):
            yield obj

    alvos = [v for e in eventos for v in _valores(e)]
    assert str(raiz / "dentro.txt") in alvos, (
        f"caminho canônico ausente da trilha; valores: {alvos[:12]}")
    assert not any(".." in v for v in alvos), (
        f"trilha guardou caminho não resolvido: "
        f"{[v for v in alvos if '..' in v]}")


# --------------------------------------------------- versão de capacidade

def test_versao_muda_quando_metadata_muda(tmp_path):
    home = tmp_path / "h"
    home.mkdir()
    reg = RegistroCapacidades(policy=PolicyEngine(home / "policy.json"))
    v1 = versao_de_capacidade(reg, "arquivo_ler")
    assert v1 and len(v1) == 16
    assert versao_de_capacidade(reg, "arquivo_escrever") != v1
    assert versao_de_capacidade(reg, "inexistente") == ""
