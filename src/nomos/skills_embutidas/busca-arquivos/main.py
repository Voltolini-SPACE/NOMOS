"""Skill oficial: busca-arquivos — acha arquivos por nome e conteudo (A0)."""
import json
import sys
from pathlib import Path

LIMITE_ARQUIVOS = 500
LIMITE_MATCHES = 20
LER_CONTEUDO = {".txt", ".md", ".log", ".csv"}
MAX_BYTES_CONTEUDO = 256 * 1024


def executar(argumentos: dict) -> dict:
    pasta = Path(argumentos.get("pasta", ".")).expanduser()
    termo = str(argumentos.get("termo", "")).strip().lower()
    if not termo:
        return {"ok": False, "erro": "informe 'termo' para procurar"}
    if not pasta.is_dir():
        return {"ok": False, "erro": f"pasta nao encontrada: {pasta}"}
    matches, vistos = [], 0
    for f in sorted(pasta.rglob("*")):
        if vistos >= LIMITE_ARQUIVOS or len(matches) >= LIMITE_MATCHES:
            break
        if not f.is_file():
            continue
        vistos += 1
        onde = None
        if termo in f.name.lower():
            onde = "nome"
        elif f.suffix.lower() in LER_CONTEUDO and f.stat().st_size <= MAX_BYTES_CONTEUDO:
            try:
                if termo in f.read_text(errors="replace").lower():
                    onde = "conteudo"
            except OSError:
                continue
        if onde:
            matches.append({"arquivo": str(f), "onde": onde})
    return {"ok": True, "termo": termo, "pasta": str(pasta),
            "arquivos_olhados": vistos, "encontrados": matches,
            "aviso": "so leitura: nada foi aberto para escrita"}


if __name__ == "__main__":
    args = {}
    if len(sys.argv) > 1:
        with open(sys.argv[1], encoding="utf-8") as fh:
            args = json.load(fh)
    print(json.dumps(executar(args), ensure_ascii=False))
