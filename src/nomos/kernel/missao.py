"""NOMOS kernel.missao — executor de missões: plano → aprovação → evidência (MC32/P1).

O NOMOS que FAZ, sem abrir mão da governança:

1. ``planejar_organizacao(dir)`` produz um PLANO legível e determinístico —
   nenhum byte muda no disco ao planejar (dry-run é o estado natural);
2. executar exige aprovação humana explícita (o chamador gateia por A1 e pede
   a palavra de confirmação num TTY);
3. a execução para no primeiro erro (fail-closed) e NUNCA sobrescreve nada
   (colisão de destino invalida o plano ainda na fase de planejamento);
4. toda execução fecha com **pacote de evidências** (via kernel.evidencia)
   contendo o manifesto de movimentos e o arquivo de DESFAZER — reversível
   por construção.

Missão embutida v1: ``organizar`` — arquivos soltos no topo de uma pasta são
movidos para subpastas por categoria (documentos, imagens, áudio, vídeo,
planilhas, apresentações, compactados, outros). Sem recursão; ocultos e
subpastas ficam intocados.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

CATEGORIAS = {
    "documentos": {".pdf", ".doc", ".docx", ".txt", ".md", ".rtf", ".odt"},
    "imagens": {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".heic"},
    "audio": {".mp3", ".wav", ".m4a", ".flac", ".ogg"},
    "video": {".mp4", ".mov", ".mkv", ".avi", ".webm"},
    "planilhas": {".xlsx", ".xls", ".csv", ".ods"},
    "apresentacoes": {".pptx", ".ppt", ".key", ".odp"},
    "compactados": {".zip", ".tar", ".gz", ".rar", ".7z", ".bz2"},
}
DESFAZER_ARQ = "DESFAZER.jsonl"


class MissaoErro(Exception):
    pass


@dataclass(frozen=True)
class Passo:
    origem: str          # relativo ao dir da missão
    destino: str
    nivel: str = "A1"


@dataclass
class Plano:
    missao: str
    dir: Path
    passos: list[Passo] = field(default_factory=list)
    conflitos: list[str] = field(default_factory=list)

    @property
    def executavel(self) -> bool:
        return bool(self.passos) and not self.conflitos

    def resumo(self) -> str:
        linhas = [f"missão: {self.missao} · pasta: {self.dir}",
                  f"passos: {len(self.passos)} (todos nível A1 — escrita local)"]
        por_cat: dict[str, int] = {}
        for p in self.passos:
            por_cat[p.destino.split("/")[0]] = \
                por_cat.get(p.destino.split("/")[0], 0) + 1
        linhas += [f"  → {cat}/: {n} arquivo(s)"
                   for cat, n in sorted(por_cat.items())]
        if self.conflitos:
            linhas.append(f"⚠ CONFLITOS (plano NÃO executável): {self.conflitos}")
        return "\n".join(linhas)


def _categoria(sufixo: str) -> str:
    s = sufixo.lower()
    for cat, exts in CATEGORIAS.items():
        if s in exts:
            return cat
    return "outros"


def planejar_organizacao(dir_alvo: Path) -> Plano:
    """Plano determinístico. NÃO toca o disco. Colisão ⇒ plano não executável."""
    dir_alvo = Path(dir_alvo)
    if not dir_alvo.is_dir():
        raise MissaoErro(f"pasta não encontrada: {dir_alvo}")
    plano = Plano(missao="organizar", dir=dir_alvo)
    for item in sorted(dir_alvo.iterdir()):
        if not item.is_file() or item.name.startswith("."):
            continue
        destino = f"{_categoria(item.suffix)}/{item.name}"
        if (dir_alvo / destino).exists():
            plano.conflitos.append(destino)
            continue
        plano.passos.append(Passo(origem=item.name, destino=destino))
    return plano


def executar(plano: Plano, *, aprovado: bool, evidencias_dir: Path,
             audit=None) -> Path:
    """Executa o plano APROVADO, passo a passo, e devolve o pacote de evidências.

    - ``aprovado`` DEVE ser True — este módulo não aprova nada sozinho;
    - para no primeiro erro (o que já moveu fica registrado no DESFAZER);
    - nunca sobrescreve (re-checagem de colisão na hora de cada passo).
    """
    from nomos.kernel import evidencia as ev
    if not aprovado:
        raise MissaoErro("execução sem aprovação humana — fail-closed")
    if not plano.executavel:
        raise MissaoErro("plano não executável (vazio ou com conflitos)")
    feitos: list[dict] = []
    erro: str | None = None
    for passo in plano.passos:
        origem = plano.dir / passo.origem
        destino = plano.dir / passo.destino
        try:
            if destino.exists():
                raise FileExistsError(f"destino já existe: {passo.destino}")
            destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(origem), str(destino))
            feitos.append({"de": passo.origem, "para": passo.destino})
        except Exception as exc:
            erro = f"{passo.origem}: {type(exc).__name__}: {exc}"
            break
    status = "PASS" if erro is None else "PARCIAL_INTERROMPIDA"
    pacote = ev.gerar_pacote(
        evidencias_dir, f"missao-{plano.missao}", status=status,
        comandos=[{"comando": f"nomos missao executar {plano.missao} "
                              f"{plano.dir}", "retorno": 0 if not erro else 1,
                   "resultado": f"{len(feitos)}/{len(plano.passos)} passos"
                               + (f" · PAROU: {erro}" if erro else "")}],
        notas=f"pasta {plano.dir} · desfazer com: nomos missao desfazer <pacote>")
    (pacote / DESFAZER_ARQ).write_text(
        "".join(json.dumps({"de": f["para"], "para": f["de"]},
                           ensure_ascii=False) + "\n" for f in reversed(feitos)),
        encoding="utf-8")
    # o DESFAZER entra no SHA256SUMS para o pacote seguir verificável
    import hashlib
    h = hashlib.sha256((pacote / DESFAZER_ARQ).read_bytes()).hexdigest()
    with (pacote / "SHA256SUMS").open("a", encoding="utf-8") as f:
        f.write(f"{h}  {DESFAZER_ARQ}\n")
    if audit is not None:
        audit.append("missao.executada", missao=plano.missao,
                     passos=len(feitos), status=status)
    if erro is not None:
        raise MissaoErro(f"missão interrompida (evidência em {pacote.name}): {erro}")
    return pacote


def desfazer(pacote: Path, dir_alvo: Path, *, aprovado: bool,
             audit=None) -> int:
    """Reverte os movimentos registrados no pacote. Também exige aprovação."""
    if not aprovado:
        raise MissaoErro("desfazer sem aprovação humana — fail-closed")
    manifesto = Path(pacote) / DESFAZER_ARQ
    if not manifesto.is_file():
        raise MissaoErro(f"pacote sem {DESFAZER_ARQ}: {pacote}")
    revertidos = 0
    for linha in manifesto.read_text(encoding="utf-8").splitlines():
        mov = json.loads(linha)
        origem = Path(dir_alvo) / mov["de"]
        destino = Path(dir_alvo) / mov["para"]
        if destino.exists():
            raise MissaoErro(f"não sobrescrevo ao desfazer: {mov['para']}")
        if origem.exists():
            destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(origem), str(destino))
            revertidos += 1
    if audit is not None:
        audit.append("missao.desfeita", revertidos=revertidos)
    return revertidos
