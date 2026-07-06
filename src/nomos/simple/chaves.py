"""NOMOS simple.chaves — guardar chaves/senhas SEM digitar no chat.

Duas formas, ambas terminando na mesma caixa-forte cifrada (o Vault):
1. guiada: a chave é pedida sem aparecer na tela (getpass) — não entra no
   histórico do chat nem no scrollback;
2. arquivo "solte aqui": a pessoa cola a chave num arquivo txt na pasta; ao
   voltar, o NOMOS absorve para a caixa-forte e APAGA o texto em claro
   (sobrescreve antes de remover — best-effort contra recuperação trivial).

Nunca exibimos o valor de uma chave — só os nomes. A caixa-forte por baixo
é o mesmo Vault com Argon2id + bloqueio progressivo dos ciclos anteriores.
"""
from __future__ import annotations

from nomos.kernel.plataforma import chmod_privado

import os
from pathlib import Path

from nomos.kernel.vault import Vault, VaultError

# nomes amigáveis -> id interno guardado na caixa-forte
SERVICOS = {
    "1": ("Claude (nuvem, da Anthropic)", "anthropic_api_key"),
    "2": ("OpenAI", "openai_api_key"),
    "3": ("outro serviço (eu pergunto o nome)", None),
}
ARQUIVO_SOLTE = "COLE_SUA_CHAVE_AQUI.txt"
MODELO_ARQUIVO = (
    "# Cole a sua chave na linha de baixo (só a chave, nada mais) e salve o\n"
    "# arquivo. Depois volte ao NOMOS e escolha 'absorver'. Assim que eu\n"
    "# guardar na caixa-forte, este arquivo é apagado automaticamente.\n"
)


class ChaveError(Exception):
    pass


def _vault() -> Vault:
    from nomos.kernel import config
    return Vault(config.nomos_home() / "vault.json")


def caixa_forte_existe() -> bool:
    return _vault().exists()


def nomes_guardados() -> list[str]:
    """Só os NOMES — o valor nunca sai da caixa-forte em claro."""
    return _vault().names()


def garantir_caixa_forte(senha_mestra: str) -> None:
    v = _vault()
    if not v.exists():
        v.init(senha_mestra)


def guardar(nome_interno: str, valor: str, senha_mestra: str) -> None:
    if not valor or not valor.strip():
        raise ChaveError("a chave está vazia — nada foi guardado")
    v = _vault()
    if not v.exists():
        v.init(senha_mestra)
    try:
        v.set(nome_interno, valor.strip(), senha_mestra)
    except VaultError as exc:
        raise ChaveError(str(exc)) from None


def remover(nome_interno: str, senha_mestra: str) -> None:
    try:
        _vault().delete(nome_interno, senha_mestra)
    except VaultError as exc:
        raise ChaveError(str(exc)) from None


def caminho_modelo(home: Path) -> Path:
    return Path(home) / ARQUIVO_SOLTE


def criar_arquivo_modelo(home: Path) -> Path:
    p = caminho_modelo(home)
    p.write_text(MODELO_ARQUIVO, encoding="utf-8")
    chmod_privado(p, 0o600)
    return p


def _apagar_com_sobrescrita(p: Path) -> None:
    """Best-effort: sobrescreve o conteúdo antes de remover o arquivo."""
    try:
        tamanho = max(p.stat().st_size, 64)
        with open(p, "r+b", buffering=0) as fh:
            fh.write(os.urandom(tamanho))
            fh.flush()
            os.fsync(fh.fileno())
    except OSError:
        pass
    finally:
        p.unlink(missing_ok=True)


def absorver_arquivo(home: Path, nome_interno: str, senha_mestra: str) -> str:
    """Lê a chave do arquivo 'solte aqui', guarda e apaga o texto em claro."""
    p = caminho_modelo(home)
    if not p.exists():
        raise ChaveError(
            f"não encontrei o arquivo {ARQUIVO_SOLTE} na sua pasta — "
            "peça para eu criá-lo primeiro")
    linhas = [ln.strip() for ln in p.read_text(encoding="utf-8").splitlines()
              if ln.strip() and not ln.lstrip().startswith("#")]
    if not linhas:
        raise ChaveError(
            f"o arquivo {ARQUIVO_SOLTE} está sem chave (só comentários) — "
            "cole a chave e salve antes de absorver")
    valor = linhas[0]
    try:
        guardar(nome_interno, valor, senha_mestra)
    finally:
        _apagar_com_sobrescrita(p)   # apaga MESMO se guardar falhar
    return nome_interno


def _pedir_senha_mestra(ask_secret, say, confirmar: bool) -> str:
    if caixa_forte_existe():
        return ask_secret("sua senha-mestra: ")
    say("Vou criar sua caixa-forte agora. Escolha uma senha-mestra (10+")
    say("caracteres) — é ela que protege todas as chaves. Guarde-a bem:")
    s1 = ask_secret("nova senha-mestra: ")
    if confirmar:
        s2 = ask_secret("confirme a senha-mestra: ")
        if s1 != s2:
            raise ChaveError("as senhas não conferem — tente de novo")
    return s1


def _escolher_servico(ask, say):
    say("Qual serviço essa chave é?")
    for k, (rotulo, _) in SERVICOS.items():
        say(f"   {k}) {rotulo}")
    esc = (ask("número> ").strip() or "1")
    if esc not in SERVICOS:
        say(f"opção inválida: {esc!r} — não guardei nada (escolha um número da lista).")
        return None
    rotulo, interno = SERVICOS[esc]
    if interno is None:
        nome = ask("nome curto para essa chave (ex.: meu_servico)> ").strip()
        interno = "".join(c for c in nome.lower().replace(" ", "_")
                          if c.isalnum() or c == "_") or "chave_extra"
    return rotulo, interno


def menu_chaves(home, ask=input, say=print, ask_secret=None):
    """Menu guiado de chaves para o chat/CLI. ask_secret NÃO ecoa na tela."""
    import getpass as _gp
    ask_secret = ask_secret or _gp.getpass
    say("")
    say("🔑 Suas chaves ficam numa caixa-forte cifrada. Nunca aparecem na tela")
    say("   nem no nosso histórico. O que você quer fazer?")
    say("   1) guardar uma chave digitando (não aparece na tela)")
    say("   2) guardar por arquivo (colo num .txt e o NOMOS absorve)")
    say("   3) ver os nomes das chaves guardadas")
    say("   4) remover uma chave")
    say("   5) voltar")
    op = ask("opção> ").strip()

    if op == "1":
        escolha = _escolher_servico(ask, say)
        if escolha is None:
            return
        rotulo, interno = escolha
        try:
            senha = _pedir_senha_mestra(ask_secret, say, confirmar=not caixa_forte_existe())
            valor = ask_secret(f"cole a chave de {rotulo} (não vou mostrar): ")
            guardar(interno, valor, senha)
            say(f"✅ guardei sua chave de {rotulo} com segurança (nome: {interno}).")
        except ChaveError as exc:
            say(f"não deu certo: {exc}")
        return

    if op == "2":
        escolha = _escolher_servico(ask, say)
        if escolha is None:
            return
        rotulo, interno = escolha
        p = criar_arquivo_modelo(home)
        say(f"criei o arquivo: {p}")
        say("Abra, cole SÓ a chave na primeira linha livre, salve — e volte aqui.")
        ask("quando terminar, aperte Enter para eu absorver> ")
        try:
            senha = _pedir_senha_mestra(ask_secret, say, confirmar=not caixa_forte_existe())
            absorver_arquivo(home, interno, senha)
            say(f"✅ absorvi a chave de {rotulo} e apaguei o arquivo em claro.")
        except ChaveError as exc:
            say(f"não deu certo: {exc}")
        return

    if op == "3":
        nomes = nomes_guardados()
        if not nomes:
            say("você ainda não guardou nenhuma chave.")
        else:
            say("chaves guardadas (só os nomes):")
            for n in nomes:
                say(f"   · {n}")
        return

    if op == "4":
        nomes = nomes_guardados()
        if not nomes:
            say("não há chaves para remover.")
            return
        say("qual remover? " + ", ".join(nomes))
        alvo = ask("nome> ").strip()
        try:
            senha = ask_secret("sua senha-mestra: ")
            remover(alvo, senha)
            say(f"removi '{alvo}'.")
        except ChaveError as exc:
            say(f"não deu certo: {exc}")
        return
    say("ok, voltando.")
