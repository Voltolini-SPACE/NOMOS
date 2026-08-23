"""Skill oficial: lembrete — devolve JSON pronto para /memoria anotar."""
import json
import sys


def executar(argumentos: dict) -> dict:
    texto = str(argumentos.get("texto", "")).strip()
    quando = str(argumentos.get("quando", "")).strip()
    if not texto:
        return {"ok": False, "erro": "informe 'texto' do lembrete"}
    nota = f"tarefa: {texto}" + (f" (quando: {quando})" if quando else "")
    return {"ok": True, "nota": nota,
            "dica": "guarde com: /memoria anotar " + nota}


if __name__ == "__main__":
    args = {}
    if len(sys.argv) > 1:
        with open(sys.argv[1], encoding="utf-8") as fh:
            args = json.load(fh)
    print(json.dumps(executar(args), ensure_ascii=False))
