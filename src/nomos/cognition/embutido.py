"""NOMOS cognition.embutido — o cérebro LEVE que vem com o NOMOS.

Filosofia: nada de exigir Ollama nem um super-PC. O NOMOS traz um modelo
pequeno (GGUF) que roda em CPU via llama.cpp e cabe em qualquer laptop. Ele
baixa sozinho UMA vez (egress consciente, atrás do gate A2) e depois é 100%
local para sempre.

- escolha do modelo conforme a RAM da máquina (mais fraco = menor);
- download com verificação de tamanho e gravação atômica;
- inferência via llama-cpp-python (import tardio: ausente => mensagem clara,
  nunca quebra o resto do NOMOS).
"""
from __future__ import annotations

import os
import shutil
import subprocess  # nosec B404 - só para ler a RAM no macOS (sysctl), sem shell
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from nomos.kernel.plataforma import chmod_privado


@dataclass(frozen=True)
class ModeloGGUF:
    id: str
    rotulo: str
    mb: int
    ram_min_gb: float
    url: str
    arquivo: str


# Catálogo do mais leve ao mais forte. Todos rodam em CPU, sem GPU.
# (URLs de repositórios públicos de GGUF; o download é opt-in e consciente.)
CATALOGO = [
    ModeloGGUF(
        "nomos-mini", "NOMOS Mini (Qwen2.5 0.5B) — o mais leve, roda em tudo",
        400, 2.0,
        "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/"
        "qwen2.5-0.5b-instruct-q4_k_m.gguf",
        "nomos-mini-q4.gguf",
    ),
    ModeloGGUF(
        "nomos-base", "NOMOS Base (Qwen2.5 1.5B) — equilíbrio",
        1100, 4.0,
        "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/"
        "qwen2.5-1.5b-instruct-q4_k_m.gguf",
        "nomos-base-q4.gguf",
    ),
    ModeloGGUF(
        "nomos-plus", "NOMOS Plus (Qwen2.5 3B) — mais esperto, pede mais RAM",
        2100, 8.0,
        "https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/"
        "qwen2.5-3b-instruct-q4_k_m.gguf",
        "nomos-plus-q4.gguf",
    ),
    # v0.18: modelos maiores para máquinas com mais RAM (mesmo fluxo opt-in)
    ModeloGGUF(
        "nomos-pro", "NOMOS Pro (Qwen2.5 7B) — raciocínio forte, PCs com 16 GB",
        4700, 16.0,
        "https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-GGUF/resolve/main/"
        "qwen2.5-7b-instruct-q4_k_m.gguf",
        "nomos-pro-q4.gguf",
    ),
    ModeloGGUF(
        "nomos-max", "NOMOS Max (Llama 3.1 8B) — o mais capaz, PCs com 16+ GB",
        4900, 16.0,
        "https://huggingface.co/bartowski/Meta-Llama-3.1-8B-Instruct-GGUF/resolve/main/"
        "Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf",
        "nomos-max-q4.gguf",
    ),
]
PADRAO = "nomos-mini"


class CerebroIndisponivel(Exception):
    pass


def ram_gb() -> float:
    """RAM total em GB, multiplataforma (Linux/Mac/Windows), sem dependências."""
    try:  # Linux
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1e9
    except (ValueError, OSError, AttributeError):
        pass
    try:  # macOS
        out = subprocess.run(["sysctl", "-n", "hw.memsize"],  # nosec B603 B607
                             capture_output=True, text=True, timeout=3)
        if out.returncode == 0:
            return int(out.stdout.strip()) / 1e9
    except Exception:  # noqa: S110  # nosec B110 - RAM é heurística; cai no próximo método
        pass
    try:  # Windows
        import ctypes

        class MS(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        m = MS()
        m.dwLength = ctypes.sizeof(MS)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))  # type: ignore
        return m.ullTotalPhys / 1e9
    except Exception:
        return 4.0  # default seguro => recomenda o modelo pequeno


def por_id(mid: str) -> ModeloGGUF:
    for m in CATALOGO:
        if m.id == mid:
            return m
    raise CerebroIndisponivel(f"cérebro desconhecido: {mid!r}")


def recomendado(ram: float | None = None) -> ModeloGGUF:
    """O maior modelo que roda confortavelmente na RAM detectada."""
    ram = ram if ram is not None else ram_gb()
    escolha = CATALOGO[0]
    for m in CATALOGO:
        if ram >= m.ram_min_gb:
            escolha = m
    return escolha


def pasta_modelos(home: Path) -> Path:
    d = Path(home) / "cerebros"
    d.mkdir(parents=True, exist_ok=True)
    return d


def caminho_modelo(home: Path, modelo: ModeloGGUF) -> Path:
    return pasta_modelos(home) / modelo.arquivo


def esta_baixado(home: Path, modelo: ModeloGGUF) -> bool:
    p = caminho_modelo(home, modelo)
    # baixado e com tamanho plausível (>= 60% do esperado, tolerando quantização)
    return p.exists() and p.stat().st_size >= modelo.mb * 1024 * 1024 * 0.6


def _abrir(url: str, timeout: float):
    from urllib.parse import urlparse
    if urlparse(url).scheme not in {"http", "https"}:
        raise ValueError("esquema de URL não permitido")
    return urllib.request.urlopen(url, timeout=timeout)  # nosec B310 - esquema validado


def baixar(home: Path, modelo: ModeloGGUF, progresso=None, timeout: float = 60.0) -> Path:
    """Baixa o GGUF (gravação atômica). progresso(recebidos, total) opcional."""
    destino = caminho_modelo(home, modelo)
    tmp = destino.with_suffix(".parte")
    try:
        with _abrir(modelo.url, timeout) as r:
            total = int(r.headers.get("Content-Length") or 0)
            recebidos = 0
            with open(tmp, "wb") as fh:
                while True:
                    bloco = r.read(1 << 20)
                    if not bloco:
                        break
                    fh.write(bloco)
                    recebidos += len(bloco)
                    if progresso:
                        progresso(recebidos, total)
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        raise CerebroIndisponivel(
            f"não consegui baixar o cérebro ({type(exc).__name__}). "
            "Verifique a internet e tente de novo.") from None
    if total and recebidos < total:
        # conexão caiu antes do fim: read() devolve b"" sem levantar erro.
        # Sem esta checagem, um GGUF truncado viraria "cérebro pronto".
        tmp.unlink(missing_ok=True)
        raise CerebroIndisponivel(
            f"download incompleto ({recebidos // (1 << 20)} de "
            f"{total // (1 << 20)} MB) — verifique a internet e tente de novo.")
    tmp.replace(destino)
    chmod_privado(destino, 0o600)
    return destino


def llama_disponivel() -> bool:
    try:
        import llama_cpp  # noqa: F401
        return True
    except Exception:
        return False


class EmbeddedProvider:
    """Fala com o cérebro embutido via llama-cpp-python (import tardio)."""

    name = "embutido"

    def __init__(self, home: Path, modelo_id: str = PADRAO, n_ctx: int = 2048):
        self.home = Path(home)
        self.modelo = por_id(modelo_id)
        self.n_ctx = n_ctx
        self._llm = None

    def disponivel(self) -> bool:
        return llama_disponivel() and esta_baixado(self.home, self.modelo)

    def _carregar(self):
        if self._llm is not None:
            return
        if not llama_disponivel():
            raise CerebroIndisponivel(
                "o motor do cérebro (llama-cpp-python) não está instalado. "
                "Rode: nomos cerebro instalar")
        if not esta_baixado(self.home, self.modelo):
            raise CerebroIndisponivel(
                "o cérebro ainda não foi baixado. Rode: nomos cerebro baixar")
        from llama_cpp import Llama
        self._llm = Llama(model_path=str(caminho_modelo(self.home, self.modelo)),
                          n_ctx=self.n_ctx, verbose=False)

    def chat(self, messages: list[dict]):
        from nomos.cognition.providers import ChatReply
        self._carregar()
        out = self._llm.create_chat_completion(messages=messages, max_tokens=512)
        texto = out["choices"][0]["message"]["content"]
        return ChatReply(text=texto, provider=self.name, model=self.modelo.id)

    def chat_stream(self, messages: list[dict], on_token):
        """Streaming do cérebro embutido (v1.1): token a token, tudo local."""
        from nomos.cognition.providers import ChatReply
        self._carregar()
        pedacos: list[str] = []
        for evento in self._llm.create_chat_completion(messages=messages,
                                                       max_tokens=512, stream=True):
            delta = (evento.get("choices") or [{}])[0].get("delta") or {}
            tok = delta.get("content", "")
            if tok:
                pedacos.append(tok)
                on_token(tok)
        return ChatReply(text="".join(pedacos), provider=self.name,
                         model=self.modelo.id)


def instalar_motor() -> tuple[bool, str]:
    """Instala o llama-cpp-python via pip (roda na máquina do usuário)."""
    if llama_disponivel():
        return True, "o motor do cérebro já está instalado."
    # sys.executable: instala no MESMO interpretador que roda o NOMOS
    # (which("python3") acharia o Python do sistema em venv/pipx — o pacote
    # iria para outro ambiente e o cérebro continuaria "não instalado")
    py = sys.executable or shutil.which("python3") or shutil.which("python")
    if not py:
        return False, "não achei o Python para instalar o motor."
    try:
        # --prefer-binary: usa wheel pré-compilada quando existir para o seu
        # sistema — sem exigir compilador (v1.0.1)
        r = subprocess.run([py, "-m", "pip", "install", "--prefer-binary",
                           "llama-cpp-python"],  # nosec B603
                          capture_output=True, text=True, timeout=1800)
    except Exception as exc:
        return False, f"falha ao instalar: {type(exc).__name__}"
    if r.returncode == 0:
        return True, "motor do cérebro instalado."
    return False, ("não consegui instalar o motor (llama-cpp-python). "
                   "Provável causa: não há wheel pronta para o seu sistema e "
                   "falta um compilador C. Caminhos: instale as ferramentas de "
                   "build do seu SO, ou use o Ollama (ollama.com) que dispensa "
                   "compilação — o NOMOS detecta sozinho.")
