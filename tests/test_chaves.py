"""Ciclo Acolhedor — área de chaves: guiada + arquivo, sem expor valores."""

import pytest

from nomos.kernel import config
from nomos.simple import chaves


@pytest.fixture()
def home(nomos_home):
    config.ensure_home()
    return config.nomos_home()


SENHA = "minha-senha-mestra-123"


# ---------- guardar/listar/remover ----------
def test_guardar_cria_caixaforte_e_lista_so_nomes(home):
    assert chaves.caixa_forte_existe() is False
    chaves.guardar("anthropic_api_key", "sk-super-secreta-000111", SENHA)
    assert chaves.caixa_forte_existe() is True
    assert chaves.nomes_guardados() == ["anthropic_api_key"]
    # o VALOR nunca aparece em claro no disco
    bruto = (home / "vault.json").read_text()
    assert "sk-super-secreta-000111" not in bruto


def test_guardar_chave_vazia_recusa(home):
    with pytest.raises(chaves.ChaveError, match="vazia"):
        chaves.guardar("x", "   ", SENHA)


def test_remover(home):
    chaves.guardar("openai_api_key", "sk-abc-123456", SENHA)
    chaves.remover("openai_api_key", SENHA)
    assert chaves.nomes_guardados() == []


def test_remover_com_senha_errada_falha(home):
    chaves.guardar("k", "valor-123456", SENHA)
    with pytest.raises(chaves.ChaveError):
        chaves.remover("k", "senha-errada-999")


# ---------- arquivo "solte aqui" ----------
def test_absorver_arquivo_guarda_e_apaga_texto(home):
    p = chaves.criar_arquivo_modelo(home)
    assert p.exists()
    p.write_text(chaves.MODELO_ARQUIVO + "sk-do-arquivo-7777\n")
    chaves.absorver_arquivo(home, "anthropic_api_key", SENHA)
    assert not p.exists()                       # texto em claro apagado
    assert "anthropic_api_key" in chaves.nomes_guardados()


def test_absorver_ignora_comentarios_e_pega_primeira_chave(home):
    p = chaves.criar_arquivo_modelo(home)
    p.write_text("# comentário\n\nsk-primeira-9999\nsk-segunda-0000\n")
    chaves.absorver_arquivo(home, "k", SENHA)
    val = chaves._vault().get("k", SENHA)
    assert val == "sk-primeira-9999"


def test_absorver_arquivo_so_comentarios_recusa_e_apaga(home):
    chaves.criar_arquivo_modelo(home)          # só comentários
    with pytest.raises(chaves.ChaveError, match="sem chave"):
        chaves.absorver_arquivo(home, "k", SENHA)


def test_absorver_sem_arquivo_orienta(home):
    with pytest.raises(chaves.ChaveError, match="não encontrei"):
        chaves.absorver_arquivo(home, "k", SENHA)


def test_arquivo_modelo_0600(home):
    p = chaves.criar_arquivo_modelo(home)
    assert oct(p.stat().st_mode & 0o777) == "0o600"


# ---------- menu guiado (streams + ask_secret injetáveis) ----------
def test_menu_guardar_digitando_nao_ecoa(home):
    respostas = iter(["1", "1"])          # opção 1 (guardar), serviço 1 (Claude)
    segredos = iter(["senha-mestra-longa-1", "senha-mestra-longa-1", "sk-DIGITADA-321"])
    tela = []
    chaves.menu_chaves(home, ask=lambda _: next(respostas),
                       say=tela.append, ask_secret=lambda _: next(segredos))
    txt = "\n".join(tela)
    assert "guardei sua chave" in txt
    assert "sk-DIGITADA-321" not in txt   # o valor JAMAIS vai para a tela
    assert chaves.nomes_guardados() == ["anthropic_api_key"]


def test_menu_listar_mostra_so_nomes(home):
    chaves.guardar("anthropic_api_key", "sk-xyz-123456", SENHA)
    tela = []
    chaves.menu_chaves(home, ask=lambda _: "3", say=tela.append,
                       ask_secret=lambda _: SENHA)
    txt = "\n".join(tela)
    assert "anthropic_api_key" in txt and "sk-xyz" not in txt


def test_menu_arquivo_absorve(home):
    respostas = iter(["2", "1", ""])      # opção 2, serviço 1, Enter após colar
    segredos = iter(["senha-mestra-longa-9", "senha-mestra-longa-9"])
    tela = []
    # simula o usuário colando a chave entre a criação do arquivo e o Enter
    real_ask = respostas
    def ask(_):
        v = next(real_ask)
        if v == "":  # momento do "aperte Enter": injeta a chave no arquivo
            p = chaves.caminho_modelo(home)
            p.write_text(chaves.MODELO_ARQUIVO + "sk-colada-4242\n")
        return v
    chaves.menu_chaves(home, ask=ask, say=tela.append,
                       ask_secret=lambda _: next(segredos))
    txt = "\n".join(tela)
    assert "absorvi" in txt
    assert not chaves.caminho_modelo(home).exists()
    assert chaves._vault().get("anthropic_api_key", "senha-mestra-longa-9") == "sk-colada-4242"
