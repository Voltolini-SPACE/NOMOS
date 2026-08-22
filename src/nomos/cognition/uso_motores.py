"""NOMOS cognition.uso_motores — medição LOCAL de uso de motor (NH-019).

Paridade com o `model-usage` do OpenClaw aposentado, do jeito NOMOS: só
METADADOS (motor, rota, duração, contagens) — NUNCA conteúdo de prompt ou
resposta. O arquivo vive no home do dono, 0600, e nenhuma decisão o lê:
é relatório para humano (`nomos motores uso`), não insumo de política.

Invariantes:
- métrica JAMAIS derruba o chat: `registrar()` engole a própria exceção;
- `erro` guarda SÓ `type(exc).__name__` — mensagem de exceção pode ecoar
  pedaço de prompt;
- rotação por tamanho (5 MiB → uma geração `.1`) — crescimento sem teto é
  dívida, não feature.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from nomos.kernel.plataforma import chmod_privado

ARQUIVO = "logs/uso_motores.jsonl"
TAMANHO_MAX = 5 * 1024 * 1024
# Guarda de regressão (testada): nomes que NUNCA podem virar campo da linha.
CAMPOS_PROIBIDOS = ("prompt", "resposta", "text", "messages", "content")


@dataclass(frozen=True)
class EventoUso:
    ts: float
    origem: str                  # "chat" | "chat_stream" | "arbitragem"
    motor: str                   # provider/engine ("" na degradação total)
    modelo: str
    modalidade: str              # "texto" (único hoje; paridade model-usage)
    rota: str                    # "local" | "cloud" | "degradada"
    ok: bool
    dur_ms: int
    chars_prompt: int
    chars_resposta: int
    tokens_prompt: int | None = None
    tokens_resposta: int | None = None
    erro: str = ""               # SÓ type(exc).__name__ — nunca a mensagem


class MedidorUso:
    """Append-only em NOMOS_HOME/logs/uso_motores.jsonl (0600)."""

    def __init__(self, home: Path):
        self.caminho = Path(home) / ARQUIVO

    def registrar(self, ev: EventoUso) -> None:
        """Nunca levanta: métrica quebrada não pode derrubar o chat."""
        import contextlib
        with contextlib.suppress(Exception):
            self.caminho.parent.mkdir(parents=True, exist_ok=True)
            if (self.caminho.exists()
                    and self.caminho.stat().st_size >= TAMANHO_MAX):
                self.caminho.replace(self.caminho.with_suffix(".jsonl.1"))
            dia = datetime.fromtimestamp(ev.ts, tz=timezone.utc).date()
            linha = {
                "ts": ev.ts, "dia": dia.isoformat(), "origem": ev.origem,
                "motor": ev.motor, "modelo": ev.modelo,
                "modalidade": ev.modalidade, "rota": ev.rota, "ok": ev.ok,
                "dur_ms": ev.dur_ms, "chars_prompt": ev.chars_prompt,
                "chars_resposta": ev.chars_resposta,
                "tokens_prompt": ev.tokens_prompt,
                "tokens_resposta": ev.tokens_resposta,
            }
            if ev.erro:
                linha["erro"] = ev.erro
            novo = not self.caminho.exists()
            with self.caminho.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(linha, ensure_ascii=False) + "\n")
            if novo:
                chmod_privado(self.caminho, 0o600)

    def ler(self, dias: int = 7) -> list[dict]:
        corte = time.time() - dias * 86400
        eventos: list[dict] = []
        for caminho in (self.caminho.with_suffix(".jsonl.1"), self.caminho):
            if not caminho.exists():
                continue
            try:
                for bruta in caminho.read_text(encoding="utf-8").splitlines():
                    try:
                        ev = json.loads(bruta)
                    except ValueError:
                        continue          # linha rasgada não derruba relatório
                    if isinstance(ev, dict) and ev.get("ts", 0) >= corte:
                        eventos.append(ev)
            except OSError:
                continue
        return eventos


def agregar(eventos: list[dict]) -> dict:
    """dia → motor → modalidade → contadores. Determinístico (ordenado)."""
    ag: dict = {}
    for ev in eventos:
        chave = ag.setdefault(ev.get("dia", "?"), {}) \
                  .setdefault(ev.get("motor") or "(degradada)", {}) \
                  .setdefault(ev.get("modalidade", "texto"), {
                      "n": 0, "ok": 0, "erros": 0, "degradadas": 0,
                      "dur_ms_total": 0, "chars": 0,
                      "tokens": 0, "tokens_conhecidos": False})
        chave["n"] += 1
        chave["ok"] += 1 if ev.get("ok") else 0
        chave["erros"] += 0 if ev.get("ok") else 1
        chave["degradadas"] += 1 if ev.get("rota") == "degradada" else 0
        chave["dur_ms_total"] += int(ev.get("dur_ms", 0))
        chave["chars"] += int(ev.get("chars_prompt", 0)) \
            + int(ev.get("chars_resposta", 0))
        for campo in ("tokens_prompt", "tokens_resposta"):
            if ev.get(campo) is not None:
                chave["tokens"] += int(ev[campo])
                chave["tokens_conhecidos"] = True
    return ag


def tabela(agregado: dict) -> str:
    if not agregado:
        return "nenhum uso de motor registrado no período."
    linhas = [f"{'dia':<12} {'motor':<16} {'modal.':<8} {'n':>4} {'ok':>4} "
              f"{'erro':>4} {'ms médio':>9} {'chars':>9} {'tokens':>8}"]
    for dia in sorted(agregado):
        for motor in sorted(agregado[dia]):
            for modal in sorted(agregado[dia][motor]):
                c = agregado[dia][motor][modal]
                media = c["dur_ms_total"] // max(1, c["n"])
                tok = str(c["tokens"]) if c["tokens_conhecidos"] else "—"
                linhas.append(
                    f"{dia:<12} {motor:<16} {modal:<8} {c['n']:>4} "
                    f"{c['ok']:>4} {c['erros']:>4} {media:>9} "
                    f"{c['chars']:>9} {tok:>8}")
    return "\n".join(linhas)
