"""NOMOS Memory Engine — CLI local-first, dry-run por padrão.

Uso:
    python -m nomos.memory.cli --add "texto"            # DRY-RUN (não grava)
    python -m nomos.memory.cli --add "texto" --apply    # grava se a política aprovar
    python -m nomos.memory.cli --list
    python -m nomos.memory.cli --context
    python -m nomos.memory.cli --compact [--apply]
    python -m nomos.memory.cli --validate
    python -m nomos.memory.cli --report [--apply]

Códigos de saída (fail-closed):
    0 sucesso · 2 uso inválido · 3 recusa de política · 4 integridade falhou ·
    5 campo inválido
"""
from __future__ import annotations

import argparse
import json

from nomos.memory import policy
from nomos.memory.engine import MemoryEngine

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_REJECTED = 3
EXIT_INTEGRITY = 4
EXIT_INVALID_FIELD = 5


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="nomos.memory.cli",
        description="NOMOS Memory Engine — memória local, auditável, fail-closed.",
    )
    acao = p.add_mutually_exclusive_group(required=True)
    acao.add_argument("--add", metavar="TEXTO", help="propõe uma memória (dry-run por padrão)")
    acao.add_argument("--list", action="store_true", help="lista memórias do histórico bruto")
    acao.add_argument("--context", action="store_true", help="gera contexto curto p/ reiniciar sessão")
    acao.add_argument("--compact", action="store_true", help="planeja/aplica compactação")
    acao.add_argument("--validate", action="store_true", help="verifica hashes e estrutura")
    acao.add_argument("--report", action="store_true", help="gera relatório operacional")

    modo = p.add_mutually_exclusive_group()
    modo.add_argument("--apply", action="store_true", help="grava (sem isto, é dry-run)")
    modo.add_argument("--dry-run", action="store_true", help="padrão: não grava nada")

    p.add_argument("--source", default="manual",
                   help="manual|session_summary|mission_result|handoff|repo_audit")
    p.add_argument("--scope", default="project", help="project|repo|module|temporary")
    p.add_argument("--priority", default="medium", help="low|medium|high|critical")
    p.add_argument("--tags", default="", help="tags separadas por vírgula")
    p.add_argument("--links", default="", help="ids/links separados por vírgula")
    p.add_argument("--base-dir", default=None, help="diretório isolado (testes/uso avançado)")
    p.add_argument("--json", action="store_true", help="saída em JSON")
    return p


def _split(csv: str) -> list[str]:
    return [x.strip() for x in (csv or "").split(",") if x.strip()]


def main(argv=None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    eng = MemoryEngine(base_dir=args.base_dir)
    apply = bool(args.apply)

    # ---- add ----
    if args.add is not None:
        res = eng.add(
            content=args.add, source=args.source, scope=args.scope,
            priority=args.priority, tags=_split(args.tags), links=_split(args.links),
            apply=apply,
        )
        cats = [f.category for f in (res.decision.findings if res.decision else [])]
        if args.json:
            print(json.dumps({
                "applied": res.applied, "dry_run": res.dry_run, "allowed": res.allowed,
                "reason": res.reason, "findings": cats, "entry": res.entry,
            }, ensure_ascii=False, indent=2))
        if res.reason == policy.REJECTION_CODE:
            if not args.json:
                print(policy.REJECTION_CODE)
                print(f"  motivo: risco detectado -> {', '.join(cats) or 'sensível'}")
                print("  nada foi gravado.")
            return EXIT_REJECTED
        if res.reason.startswith("INVALID_"):
            if not args.json:
                print(f"campo inválido: {res.reason}")
            return EXIT_INVALID_FIELD
        if res.reason.startswith("EMPTY"):
            if not args.json:
                print("conteúdo vazio/ inválido — nada a gravar.")
            return EXIT_USAGE
        # Horizonte 3/missao de debitos, P2 (2026-07-17): `AddResult.entry`
        # e Optional[dict] no dataclass (memory/engine.py), mas os 3 `return`
        # acima ja eliminaram TODOS os motivos que MemoryEngine.add() produz
        # com entry=None (REJECTION_CODE, INVALID_*, EMPTY*) -- por
        # eliminacao, chegar aqui so e possivel com reason in {"DRY_RUN",
        # "APPLIED"}, os dois unicos casos em que add() de fato constroi e
        # devolve `entry`. O assert documenta essa invariante (que ja
        # valia, so nao era visivel ao mypy) e falharia alto, nao
        # silenciosamente, se um motivo novo violar essa correlacao no
        # futuro -- mais seguro que suprimir o erro de tipo.
        assert res.entry is not None, (
            f"invariante violada: reason={res.reason!r} chegou sem entry")
        if not args.json:
            if res.applied:
                print(f"OK gravado: {res.entry['id']}")
                print(f"  arquivo: {res.path}")
            else:
                print("DRY-RUN (nada gravado). Reveja e rode com --apply para gravar.")
                print(f"  id proposto: {res.entry['id']}")
                print(f"  conteúdo: {res.entry['content'][:120]}")
        return EXIT_OK

    # ---- list ----
    if args.list:
        entradas = eng.list_entries()
        if args.json:
            print(json.dumps(entradas, ensure_ascii=False, indent=2))
        else:
            if not entradas:
                print("(memória vazia)")
            for e in entradas:
                print(f"{e.get('id')}  [{e.get('priority')}·{e.get('scope')}/{e.get('source')}]  "
                      f"{' '.join((e.get('content','')).split())[:100]}")
        return EXIT_OK

    # ---- context ----
    if args.context:
        print(eng.context())
        return EXIT_OK

    # ---- compact ----
    if args.compact:
        # Horizonte 3/missao de debitos, P2: nome proprio (nao "res") --
        # eng.compact() devolve CompactResult, um dataclass DIFERENTE do
        # AddResult usado no bloco `--add` acima. Ambos os ramos sao
        # mutuamente exclusivos em runtime (cada `if args.*` so roda um),
        # mas mypy infere um unico tipo estatico por nome de variavel na
        # funcao inteira -- reusar "res" para os dois fazia o segundo
        # assignment "estreitar" para o tipo do primeiro. Renomear elimina
        # o conflito sem mudar nenhum comportamento.
        res_compact = eng.compact(apply=apply)
        if args.json:
            print(json.dumps({
                "dry_run": res_compact.dry_run, "applied": res_compact.applied,
                "groups": res_compact.plan.groups, "reduction": res_compact.plan.reduction,
                "path": res_compact.path,
            }, ensure_ascii=False, indent=2))
        else:
            estado = "APLICADO" if res_compact.applied else "DRY-RUN (nada gravado)"
            print(f"Compactação [{estado}]: {res_compact.plan.reduction} "
                  f"({res_compact.plan.groups} grupo(s)). Histórico bruto preservado.")
            if res_compact.path:
                print(f"  derivado: {res_compact.path}")
        return EXIT_OK

    # ---- validate ----
    if args.validate:
        v = eng.validate()
        if args.json:
            print(json.dumps(v.as_dict(), ensure_ascii=False, indent=2))
        else:
            print(f"Integridade: {v.ok}/{v.checked} íntegras · "
                  f"adulteradas={v.tampered} · estruturais={v.structural_errors}")
        return EXIT_OK if v.valid else EXIT_INTEGRITY

    # ---- report ----
    if args.report:
        rep, md, path = eng.report(apply=apply)
        if args.json:
            print(json.dumps({"report": rep, "path": path}, ensure_ascii=False, indent=2))
        else:
            print(md)
            if path:
                print(f"\n(relatório salvo em {path})")
            else:
                print("\n(DRY-RUN: relatório não salvo. Use --apply para gravar em reports/.)")
        return EXIT_OK

    parser.error("nenhuma ação escolhida")  # fail-closed; nunca alcançado
    return EXIT_USAGE


if __name__ == "__main__":
    raise SystemExit(main())
