"""Skill oficial: sistema-info — diagnostico local, zero rede."""
import json
import platform
import shutil
import sys


def executar(argumentos: dict) -> dict:
    uso = shutil.disk_usage("/")
    return {"ok": True,
            "python": platform.python_version(),
            "sistema": f"{platform.system()} {platform.release()}",
            "maquina": platform.machine(),
            "disco_livre_gb": round(uso.free / 2**30, 1),
            "disco_total_gb": round(uso.total / 2**30, 1)}


if __name__ == "__main__":
    args = {}
    if len(sys.argv) > 1:
        with open(sys.argv[1], encoding="utf-8") as fh:
            args = json.load(fh)
    print(json.dumps(executar(args), ensure_ascii=False))
