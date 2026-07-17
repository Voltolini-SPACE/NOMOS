"""NOMOS kernel.evidencia — pacote de evidências auditável por missão (MC29).

Padroniza o que antes era feito à mão (ex.: handoffs com SHA256SUMS): toda
missão/operação relevante pode gerar um **pacote de evidências** verificável
offline, com relatório humano, manifesto estruturado e hashes.

Formato do pacote (diretório):

    EVIDENCIA_<slug>_<UTC>/
      RELATORIO.md      relatório humano (redigido: segredos nunca aparecem)
      manifest.json     manifesto determinístico (titulo, status, comandos,
                        anexos com sha256, versão do formato)
      anexos/…          cópias dos arquivos de evidência (opcional)
      SHA256SUMS        hashes de tudo acima (compatível com `sha256sum -c`)

Princípios (alinhados à SECURITY_POLICY):
- fail-closed: destino existente ou anexo ausente ⇒ erro, nada meio-escrito;
- redação: todo texto humano passa por ``kernel.audit.redact_text`` — chaves e
  segredos viram ``[REDACTED]`` antes de tocar o disco;
- verificação offline: ``verificar_pacote`` reconfere todos os hashes sem rede;
- stdlib-only; nenhuma execução de processo externo.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping

from nomos.kernel.audit import redact_text

PACOTE_VERSAO = 1
PREFIXO = "EVIDENCIA"


def _slug(texto: str) -> str:
    limpo = re.sub(r"[^A-Za-z0-9]+", "-", texto.strip()).strip("-").lower()
    return (limpo or "missao")[:48]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for bloco in iter(lambda: f.read(65536), b""):
            h.update(bloco)
    return h.hexdigest()


def _agora_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def gerar_pacote(
    destino: Path,
    titulo: str,
    *,
    status: str,
    comandos: Iterable[Mapping] = (),
    anexos: Iterable[Path] = (),
    notas: str = "",
) -> Path:
    """Gera um pacote de evidências em ``destino`` e devolve o caminho criado.

    ``comandos``: mapeamentos com chaves ``comando``, ``retorno``, ``resultado``.
    ``anexos``: arquivos existentes, copiados para dentro do pacote.
    Levanta ``FileExistsError``/``FileNotFoundError`` fail-closed.
    """
    destino = Path(destino)
    anexos = [Path(a) for a in anexos]
    for a in anexos:
        if not a.is_file():
            raise FileNotFoundError(f"anexo de evidência ausente: {a}")

    nome = f"{PREFIXO}_{_slug(titulo)}_{_agora_utc()}"
    pacote = destino / nome
    if pacote.exists():
        raise FileExistsError(f"pacote já existe (não sobrescrevo): {pacote}")
    (pacote / "anexos").mkdir(parents=True)

    cmds = [{
        "comando": redact_text(str(c.get("comando", ""))),
        "retorno": int(c.get("retorno", 0)),
        "resultado": redact_text(str(c.get("resultado", ""))),
    } for c in comandos]

    infos_anexos = []
    for a in anexos:
        alvo = pacote / "anexos" / a.name
        shutil.copyfile(a, alvo)
        infos_anexos.append({
            "nome": a.name,
            "sha256": _sha256(alvo),
            "bytes": alvo.stat().st_size,
        })

    manifesto = {
        "formato": PACOTE_VERSAO,
        "titulo": redact_text(titulo),
        "status": redact_text(status),
        "notas": redact_text(notas),
        "timestamp_utc": nome.rsplit("_", 1)[-1],
        "comandos": cmds,
        "anexos": infos_anexos,
        "redigido": True,
        "verificacao": "sha256sum -c SHA256SUMS (offline)",
    }
    (pacote / "manifest.json").write_text(
        json.dumps(manifesto, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8")

    linhas = [
        f"# Evidência — {manifesto['titulo']}",
        "",
        f"- **Status:** {manifesto['status']}",
        f"- **Quando (UTC):** {manifesto['timestamp_utc']}",
        f"- **Formato:** v{PACOTE_VERSAO} · redigido (segredos nunca aparecem)",
        "",
    ]
    if manifesto["notas"]:
        # P2-11 da auditoria de 2026-07-17: `manifesto` tem valores
        # heterogêneos (int/str/list/bool) — sem anotação explícita, mypy
        # infere dict[str, object], então manifesto["notas"] é estaticamente
        # `object` mesmo sendo sempre str (vem de redact_text(str)->str).
        # str() aqui é uma no-op no caso real (já é str) e resolve o
        # falso-positivo do mypy sem exigir type:ignore.
        linhas += [str(manifesto["notas"]), ""]
    if cmds:
        linhas += ["## Comandos executados", "",
                   "| Comando | Retorno | Resultado |", "|---|---:|---|"]
        linhas += [f"| `{c['comando']}` | {c['retorno']} | {c['resultado']} |"
                   for c in cmds]
        linhas.append("")
    if infos_anexos:
        linhas += ["## Anexos", "", "| Arquivo | SHA-256 | Bytes |", "|---|---|---:|"]
        linhas += [f"| anexos/{i['nome']} | `{i['sha256']}` | {i['bytes']} |"
                   for i in infos_anexos]
        linhas.append("")
    linhas += ["## Como verificar (offline)", "",
               "```bash", f"cd {nome}", "sha256sum -c SHA256SUMS", "```", ""]
    (pacote / "RELATORIO.md").write_text("\n".join(linhas), encoding="utf-8")

    sums = []
    for rel in ["manifest.json", "RELATORIO.md"] + [
            f"anexos/{i['nome']}" for i in infos_anexos]:
        sums.append(f"{_sha256(pacote / rel)}  {rel}")
    (pacote / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="utf-8")
    return pacote


def verificar_pacote(pacote: Path) -> tuple[bool, list[str]]:
    """Reconfere todos os hashes do pacote, offline. Devolve (ok, problemas)."""
    pacote = Path(pacote)
    problemas: list[str] = []
    sums = pacote / "SHA256SUMS"
    if not sums.is_file():
        return False, ["SHA256SUMS ausente"]
    for linha in sums.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha:
            continue
        try:
            esperado, rel = linha.split(maxsplit=1)
        except ValueError:
            problemas.append(f"linha inválida: {linha!r}")
            continue
        alvo = pacote / rel.strip()
        if not alvo.is_file():
            problemas.append(f"arquivo listado ausente: {rel}")
        elif _sha256(alvo) != esperado:
            problemas.append(f"hash divergente: {rel}")
    try:
        manifesto = json.loads((pacote / "manifest.json").read_text(encoding="utf-8"))
        if manifesto.get("formato") != PACOTE_VERSAO:
            problemas.append("formato de manifesto desconhecido")
        for i in manifesto.get("anexos", []):
            alvo = pacote / "anexos" / i["nome"]
            if not alvo.is_file() or _sha256(alvo) != i["sha256"]:
                problemas.append(f"anexo divergente do manifesto: {i['nome']}")
    except Exception:
        problemas.append("manifest.json ausente/ilegível")
    return (not problemas), problemas
