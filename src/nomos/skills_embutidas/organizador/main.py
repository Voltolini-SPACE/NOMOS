"""Skill oficial: organizador — só olha (A0), nunca mexe."""
import json
import sys
from pathlib import Path


def executar(argumentos: dict) -> dict:
    pasta = Path(argumentos.get("pasta", "."))
    if not pasta.is_dir():
        return {"ok": False, "erro": f"pasta nao encontrada: {pasta}"}
    por_tipo, maiores = {}, []
    for f in pasta.iterdir():
        if f.is_file():
            ext = f.suffix.lower() or "(sem extensao)"
            por_tipo[ext] = por_tipo.get(ext, 0) + 1
            maiores.append((f.stat().st_size, f.name))
    maiores.sort(reverse=True)
    return {"ok": True, "pasta": str(pasta),
            "arquivos": sum(por_tipo.values()), "por_tipo": por_tipo,
            "maiores": [{"nome": n, "bytes": t} for t, n in maiores[:5]],
            "aviso": "so leitura: nada foi movido ou alterado"}


if __name__ == "__main__":
    args = {}
    if len(sys.argv) > 1:
        with open(sys.argv[1], encoding="utf-8") as fh:
            args = json.load(fh)
    print(json.dumps(executar(args), ensure_ascii=False))
