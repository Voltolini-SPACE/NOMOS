"""NOMOS adapters.filesystem — filesystem amplo governado (ABSORPTION-03 / FASE 2).

Fecha as capacidades críticas de FS que o censo da ABSORPTION-02 apontou:
leitura que devolve CONTEÚDO, edição/patch, e confinamento transversal — o
censo mostrou que `arquivo_ler` aceitava caminho absoluto arbitrário e devolvia
só metadado, enquanto `arquivo_escrever` era o único confinado.

Todas as capacidades daqui:
- resolvem caminho por `adapters.caminho` (canonicaliza, barra `..`, barra
  escape por symlink, compara por componente);
- respeitam `ctx.raizes` — o escopo vem do PDP, não do adapter;
- falham com erro TIPADO;
- respeitam o deadline do nó;
- auditam o alvo CANÔNICO (não o que o caller digitou);
- e, quando mutantes, escrevem de forma atômica.

O adapter não decide risco nem idempotência: os dois vêm carimbados no
`CapabilityContext`, derivados do registro.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from nomos.adapters.caminho import resolver
from nomos.adapters.contrato import (
    Adapter, CapabilityContext, CapabilityRequest, CapabilityResult,
    ErroInvalido, ErroLimite, ErroNaoEncontrado, ErroPermissao,
)

LIMITE_LEITURA_BYTES = 8 * 1024 * 1024      # 8 MB
LIMITE_ESCRITA_BYTES = 8 * 1024 * 1024
LIMITE_ITENS_LISTAGEM = 5000

# Nome PÚBLICO com hífen: é o que o registro dinâmico aceita
# (`registro.NOME_RE` = ^[a-z][a-z0-9-]{1,31}$ — sem underscore). O método
# Python correspondente continua com underscore, então o despacho é por tabela
# em vez de getattr — mais explícito e sem construir nome de atributo.
CAPACIDADES = (
    "fs-ler", "fs-escrever", "fs-editar", "fs-criar-dir",
    "fs-mover", "fs-apagar", "fs-listar", "fs-metadados",
)


def _texto(valor, nome: str) -> str:
    if not isinstance(valor, str):
        raise ErroInvalido(f"'{nome}' precisa ser texto")
    return valor


class FilesystemAdapter(Adapter):
    """As 8 capacidades de filesystem, todas confinadas pelo escopo do contexto."""

    capacidades = CAPACIDADES

    def executar(self, pedido: CapabilityRequest,
                 ctx: CapabilityContext) -> CapabilityResult:
        self._coerente(pedido, ctx)
        return self._DESPACHO[pedido.capacidade](self, pedido, ctx)

    # ------------------------------------------------------------- leitura

    def _fs_ler(self, pedido, ctx) -> CapabilityResult:
        """Devolve CONTEÚDO — a lacuna que o censo apontou em `arquivo_ler`.

        `offset`/`limite` em LINHAS, como o `read_file` do Hermes, para que ler
        arquivo grande não signifique carregar tudo.
        """
        caminho = resolver(_texto(pedido.alvo, "alvo"), ctx.raizes)
        if not caminho.exists():
            raise ErroNaoEncontrado(f"arquivo não encontrado: {caminho}")
        if caminho.is_dir():
            raise ErroInvalido(f"é diretório, não arquivo: {caminho}")
        try:
            tamanho = caminho.stat().st_size
        except OSError as exc:
            raise ErroPermissao(f"não consegui inspecionar: {exc}") from None
        if tamanho > LIMITE_LEITURA_BYTES:
            raise ErroLimite(
                f"arquivo de {tamanho} bytes acima do teto de "
                f"{LIMITE_LEITURA_BYTES} — use offset/limite")
        try:
            bruto = caminho.read_bytes()
        except PermissionError as exc:
            raise ErroPermissao(f"sem permissão de leitura: {exc}") from None
        except OSError as exc:
            raise ErroInvalido(f"falha ao ler: {exc}") from None

        binario = b"\x00" in bruto[:8192]
        if binario:
            self._auditar(ctx, "fs.ler", alvo=str(caminho), bytes=len(bruto),
                          binario=True)
            return CapabilityResult.sucesso(
                None, bytes=len(bruto), binario=True,
                detalhe="conteúdo binário não é devolvido como texto")

        texto = bruto.decode("utf-8", errors="replace")
        linhas = texto.splitlines()
        offset = int(pedido.arg("offset", 0) or 0)
        limite = pedido.arg("limite")
        if offset < 0:
            raise ErroInvalido("offset negativo")
        fatia = linhas[offset:offset + int(limite)] if limite else linhas[offset:]
        self._auditar(ctx, "fs.ler", alvo=str(caminho), bytes=len(bruto),
                      linhas=len(fatia))
        return CapabilityResult.sucesso(
            "\n".join(fatia), bytes=len(bruto), linhas_totais=len(linhas),
            offset=offset, binario=False)

    # ------------------------------------------------------------- escrita

    def _fs_escrever(self, pedido, ctx) -> CapabilityResult:
        conteudo = _texto(pedido.arg("conteudo", ""), "conteudo")
        if len(conteudo.encode("utf-8")) > LIMITE_ESCRITA_BYTES:
            raise ErroLimite("conteúdo acima do teto de escrita")
        caminho = resolver(_texto(pedido.alvo, "alvo"), ctx.raizes,
                           para_escrita=True)
        _escrever_atomico(caminho, conteudo)
        self._auditar(ctx, "fs.escrever", alvo=str(caminho),
                      bytes=len(conteudo.encode("utf-8")))
        return CapabilityResult.sucesso(str(caminho), efeito_aplicado=True)

    def _fs_editar(self, pedido, ctx) -> CapabilityResult:
        """Substituição literal única — a edição cirúrgica que faltava.

        `de` precisa ocorrer EXATAMENTE uma vez: zero ocorrências é engano do
        chamador, várias é ambiguidade. Nos dois casos falha fechada em vez de
        adivinhar.
        """
        de = _texto(pedido.arg("de", ""), "de")
        para = _texto(pedido.arg("para", ""), "para")
        if not de:
            raise ErroInvalido("'de' vazio")
        caminho = resolver(_texto(pedido.alvo, "alvo"), ctx.raizes,
                           para_escrita=True)
        if not caminho.exists():
            raise ErroNaoEncontrado(f"arquivo não encontrado: {caminho}")
        try:
            atual = caminho.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as exc:
            raise ErroInvalido(f"não é texto editável: {exc}") from None
        n = atual.count(de)
        if n == 0:
            raise ErroInvalido("trecho 'de' não encontrado no arquivo")
        if n > 1:
            raise ErroInvalido(
                f"trecho 'de' aparece {n} vezes — edição ambígua, recusada")
        _escrever_atomico(caminho, atual.replace(de, para, 1))
        self._auditar(ctx, "fs.editar", alvo=str(caminho))
        return CapabilityResult.sucesso(str(caminho), efeito_aplicado=True)

    # ------------------------------------------------------------- estrutura

    def _fs_criar_dir(self, pedido, ctx) -> CapabilityResult:
        caminho = resolver(_texto(pedido.alvo, "alvo"), ctx.raizes,
                           para_escrita=True)
        ja_existia = caminho.exists()
        try:
            caminho.mkdir(parents=True, exist_ok=True)
        except PermissionError as exc:
            raise ErroPermissao(str(exc)) from None
        except OSError as exc:
            raise ErroInvalido(f"falha ao criar diretório: {exc}") from None
        self._auditar(ctx, "fs.criar_dir", alvo=str(caminho))
        return CapabilityResult.sucesso(str(caminho),
                                        efeito_aplicado=not ja_existia)

    def _fs_mover(self, pedido, ctx) -> CapabilityResult:
        """Origem E destino precisam estar no escopo — mover para fora é escape."""
        origem = resolver(_texto(pedido.alvo, "alvo"), ctx.raizes,
                          para_escrita=True)
        destino = resolver(_texto(pedido.arg("destino", ""), "destino"),
                           ctx.raizes, para_escrita=True)
        if not origem.exists():
            raise ErroNaoEncontrado(f"origem não encontrada: {origem}")
        if destino.exists():
            raise ErroInvalido(f"destino já existe: {destino}")
        destino.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.replace(origem, destino)
        except OSError as exc:
            raise ErroInvalido(f"falha ao mover: {exc}") from None
        self._auditar(ctx, "fs.mover", alvo=str(origem), destino=str(destino))
        return CapabilityResult.sucesso(str(destino), efeito_aplicado=True)

    def _fs_apagar(self, pedido, ctx) -> CapabilityResult:
        caminho = resolver(_texto(pedido.alvo, "alvo"), ctx.raizes,
                           para_escrita=True)
        if not caminho.exists() and not caminho.is_symlink():
            raise ErroNaoEncontrado(f"não encontrado: {caminho}")
        recursivo = bool(pedido.arg("recursivo", False))
        try:
            if caminho.is_dir() and not caminho.is_symlink():
                if recursivo:
                    shutil.rmtree(caminho)
                else:
                    caminho.rmdir()             # vazio apenas
            else:
                caminho.unlink()
        except OSError as exc:
            raise ErroInvalido(f"falha ao apagar: {exc}") from None
        self._auditar(ctx, "fs.apagar", alvo=str(caminho), recursivo=recursivo)
        return CapabilityResult.sucesso(str(caminho), efeito_aplicado=True)

    # ------------------------------------------------------------- consulta

    def _fs_listar(self, pedido, ctx) -> CapabilityResult:
        """Listagem/glob. Resultado é FILTRADO pelo escopo — um padrão como
        `../*` não vira vazamento, só devolve menos."""
        base = resolver(_texto(pedido.alvo, "alvo"), ctx.raizes)
        if not base.exists():
            raise ErroNaoEncontrado(f"não encontrado: {base}")
        padrao = pedido.arg("padrao") or "*"
        if not isinstance(padrao, str):
            raise ErroInvalido("'padrao' precisa ser texto")
        # padrão absoluto faz `Path.glob` levantar NotImplementedError CRUA —
        # exceção não tipada escapando do adapter viola o contrato. Recusa
        # explícita: o escopo já é o `alvo`, o padrão é relativo a ele.
        if padrao.startswith("/") or padrao.startswith("~"):
            raise ErroInvalido(
                f"'padrao' precisa ser relativo ao alvo (recebido: {padrao!r})")
        recursivo = bool(pedido.arg("recursivo", False))
        it = base.rglob(padrao) if recursivo else base.glob(padrao)
        itens, truncado = [], False
        for i, p in enumerate(it):
            if i >= LIMITE_ITENS_LISTAGEM:
                truncado = True
                break
            try:
                resolver(str(p), ctx.raizes)     # o glob não escapa o escopo
            except Exception:
                continue
            itens.append({"caminho": str(p), "dir": p.is_dir()})
        self._auditar(ctx, "fs.listar", alvo=str(base), itens=len(itens))
        return CapabilityResult.sucesso(itens, truncado=truncado)

    def _fs_metadados(self, pedido, ctx) -> CapabilityResult:
        caminho = resolver(_texto(pedido.alvo, "alvo"), ctx.raizes)
        if not caminho.exists() and not caminho.is_symlink():
            raise ErroNaoEncontrado(f"não encontrado: {caminho}")
        st = caminho.lstat()
        dados = {
            "caminho": str(caminho),
            "bytes": st.st_size,
            "dir": caminho.is_dir(),
            "symlink": caminho.is_symlink(),
            "modo": oct(st.st_mode & 0o777),
            "mtime": int(st.st_mtime),
        }
        self._auditar(ctx, "fs.metadados", alvo=str(caminho))
        return CapabilityResult.sucesso(dados)

    _DESPACHO = {
        "fs-ler": _fs_ler, "fs-escrever": _fs_escrever, "fs-editar": _fs_editar,
        "fs-criar-dir": _fs_criar_dir, "fs-mover": _fs_mover,
        "fs-apagar": _fs_apagar, "fs-listar": _fs_listar,
        "fs-metadados": _fs_metadados,
    }


def _escrever_atomico(caminho: Path, conteudo: str) -> None:
    """temp no MESMO diretório → fsync → os.replace.

    Mesmo diretório porque `os.replace` só é atômico dentro do mesmo
    filesystem. fsync antes do replace para o conteúdo estar no disco quando o
    nome passar a apontar para ele — sem isso, um crash deixa arquivo com nome
    novo e conteúdo vazio.
    """
    caminho.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(caminho.parent), prefix=".nomos-tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(conteudo)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, caminho)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
