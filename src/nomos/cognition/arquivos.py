"""NOMOS cognition.arquivos — ler, entender e resumir arquivos, 100% local.

Pipeline canônico (cada etapa pela política, via EnginePipeline):
  ler (A0) → extrair pontos (A0) → resumir com motor local (A0)
  → [opcional] salvar resumo (A1, com aprovação)

Honestidade:
- formato não suportado, arquivo grande demais ou PDF sem a dependência
  opcional => erro claro com o próximo passo, nunca meia-resposta;
- sem motor de texto => devolve os PONTOS EXTRAÍDOS (heurística transparente)
  e avisa que o resumo de verdade precisa do cérebro (`nomos cerebro baixar`).
"""
from __future__ import annotations

from pathlib import Path

from nomos.cognition.engine_pipeline import EnginePipeline, PipelineStep
from nomos.kernel.policy import Category

LIMITE_BYTES = 5 * 1024 * 1024          # 5 MB de texto é muito texto
FORMATOS_TEXTO = {".txt", ".md", ".markdown", ".rst", ".log", ".csv", ".json"}


class ArquivoError(Exception):
    pass


def extrair_texto(caminho: Path) -> tuple[str, str]:
    """(texto, formato). Erro honesto para o que não dá para ler."""
    p = Path(caminho)
    if not p.exists():
        raise ArquivoError(f"arquivo não encontrado: {p}")
    if p.stat().st_size > LIMITE_BYTES:
        raise ArquivoError(
            f"arquivo grande demais ({p.stat().st_size // (1024*1024)} MB; "
            f"limite {LIMITE_BYTES // (1024*1024)} MB) — divida em partes")
    ext = p.suffix.lower()
    if ext in FORMATOS_TEXTO:
        return p.read_text(encoding="utf-8", errors="replace"), ext.lstrip(".")
    if ext == ".pdf":
        try:
            from pypdf import PdfReader   # dependência opcional [arquivos]
        except ImportError:
            raise ArquivoError(
                "para ler PDF, instale o extra opcional: "
                "pip install 'nomos[arquivos]'") from None
        try:
            reader = PdfReader(str(p))
            paginas = [(pg.extract_text() or "") for pg in reader.pages[:200]]
        except Exception as exc:
            raise ArquivoError(f"PDF ilegível: {type(exc).__name__}") from None
        texto = "\n".join(paginas).strip()
        if not texto:
            raise ArquivoError("este PDF não tem texto extraível "
                               "(provavelmente é imagem escaneada)")
        return texto, "pdf"
    raise ArquivoError(f"formato '{ext or 'sem extensão'}' ainda não suportado "
                       f"(leio: {', '.join(sorted(FORMATOS_TEXTO))} e .pdf)")


def extrair_pontos(texto: str, maximo: int = 8) -> list[str]:
    """Heurística LOCAL e transparente: títulos, listas e frases densas."""
    pontos: list[str] = []
    for linha in texto.splitlines():
        t = linha.strip()
        if not t:
            continue
        if t.startswith("#") or (t.startswith(("-", "*", "•")) and len(t) > 8):
            pontos.append(t.lstrip("#-*• ").strip())
        elif t.endswith(":") and 10 < len(t) < 90:
            pontos.append(t.rstrip(":"))
        if len(pontos) >= maximo:
            return pontos
    if len(pontos) < 3:   # texto corrido: pega as primeiras frases relevantes
        import re
        frases = re.split(r"(?<=[.!?])\s+", " ".join(texto.split()))
        for f in frases:
            if 30 < len(f) < 300:
                pontos.append(f.strip())
            if len(pontos) >= maximo:
                break
    return pontos[:maximo]


def resumir_com_motor(texto: str, router, limite_contexto: int = 6000) -> str | None:
    """Resumo via motor local (Router existente). None = sem motor (honesto)."""
    if router is None:
        return None
    recorte = texto[:limite_contexto]
    try:
        out = router.chat([
            {"role": "system",
             "content": "Você resume documentos em português do Brasil. "
                        "Responda com 3 a 6 frases objetivas e fiéis ao texto. "
                        "Nunca invente o que não está no documento."},
            {"role": "user", "content": f"Resuma este documento:\n\n{recorte}"},
        ])
    except Exception:
        return None
    return out.text if getattr(out, "ok", False) else None


def processar(caminho, ctx, approver, router=None, salvar: bool = False):
    """Pipeline completo. Devolve (PipelineResult, dict com texto/pontos/resumo).

    A leitura (A0, sempre permitida) acontece ANTES do pipeline para que erros
    de arquivo cheguem ao usuário com a mensagem honesta (ArquivoError). As
    etapas governadas — extração, resumo e salvamento (A1) — ficam no pipeline.
    """
    texto0, formato = extrair_texto(Path(caminho))   # erro honesto sobe daqui
    estado: dict = {"texto": texto0, "formato": formato}

    def _pontos(texto):
        estado["pontos"] = extrair_pontos(texto)
        return texto

    def _resumir(texto):
        estado["resumo"] = resumir_com_motor(texto, router)
        return texto

    passos = [
        PipelineStep("extrair-pontos", "heuristica-local", Category.READ_LOCAL, _pontos),
        PipelineStep("resumir", "texto-local", Category.READ_LOCAL, _resumir),
    ]
    if salvar:
        def _salvar(texto):
            destino = Path(caminho).with_suffix(Path(caminho).suffix + ".resumo.md")
            corpo = render_resultado(Path(caminho), estado)
            destino.write_text(corpo, encoding="utf-8")
            estado["salvo_em"] = str(destino)
            return texto
        passos.append(PipelineStep("salvar-resumo", "arquivo-local",
                                   Category.WRITE_LOCAL, _salvar))

    pipe = EnginePipeline(passos, ctx["policy"], approver, audit=ctx.get("audit"))
    resultado = pipe.run(texto0)
    return resultado, estado


def render_resultado(caminho: Path, estado: dict) -> str:
    linhas = [f"# Resumo de {Path(caminho).name}",
              f"(formato: {estado.get('formato', '?')} · gerado localmente pelo NOMOS)",
              ""]
    if estado.get("resumo"):
        linhas += ["## Resumo", estado["resumo"], ""]
    else:
        linhas += ["## Resumo",
                   "(ainda sem cérebro de IA para resumir de verdade — abaixo "
                   "vão os pontos extraídos por heurística local; para resumo "
                   "completo: nomos cerebro baixar)", ""]
    if estado.get("pontos"):
        linhas.append("## Pontos do documento")
        linhas += [f"- {p}" for p in estado["pontos"]]
    return "\n".join(linhas)


# ------------------------- voz (ouvir) -------------------------

def transcrever(caminho, transcritor=None, timeout: int = 300) -> str:
    """Transcreve áudio com whisper LOCAL. Sem whisper => erro honesto."""
    p = Path(caminho)
    if not p.exists():
        raise ArquivoError(f"áudio não encontrado: {p}")
    if transcritor is not None:
        return transcritor(p)
    import shutil
    import subprocess  # nosec B404 - executa apenas o whisper local do usuário
    bin_whisper = shutil.which("whisper") or shutil.which("whisper-cpp")
    if not bin_whisper:
        raise ArquivoError("nenhum transcritor local encontrado — instale o "
                           "whisper e deixe no PATH (o áudio nunca sai da máquina)")
    # flags diferem por binário: openai-whisper usa --output_format/--output_dir;
    # whisper.cpp (whisper-cpp) usa -f/-otxt/-of — as flags erradas fariam o
    # whisper-cpp falhar (ou devolver vazio "com sucesso")
    if "whisper-cpp" in Path(bin_whisper).name:
        argv = [bin_whisper, "-f", str(p), "-otxt", "-of", str(p.with_suffix(""))]
    else:
        argv = [bin_whisper, str(p), "--output_format", "txt",
                "--output_dir", str(p.parent)]
    try:
        r = subprocess.run(argv, capture_output=True, text=True,
                           timeout=timeout)  # nosec B603
    except subprocess.TimeoutExpired:
        raise ArquivoError("transcrição demorou demais e foi interrompida") from None
    if r.returncode != 0:
        raise ArquivoError(f"whisper falhou (rc={r.returncode})")
    gerado = p.with_suffix(".txt")
    texto = ""
    if gerado.exists():
        texto = gerado.read_text(encoding="utf-8", errors="replace").strip()
    else:
        texto = (r.stdout or "").strip()
    if not texto:
        raise ArquivoError("a transcrição saiu vazia — o whisper não produziu "
                           "texto para este áudio")
    return texto
