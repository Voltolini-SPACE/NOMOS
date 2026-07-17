"""NOMOS Mosaic — CLI (dry-run por padrão, ações com aprovação).

    python -m nomos.mosaic.cli --add mail.google.com --label "Gmail" --apply
    python -m nomos.mosaic.cli --list
    python -m nomos.mosaic.cli --scan --apply            # vistoria todas as telas
    python -m nomos.mosaic.cli --panel --apply           # gera o painel HTML
    python -m nomos.mosaic.cli --context                 # o que o agente já sabe
    python -m nomos.mosaic.cli --act <id> --action reply --approve --apply
    python -m nomos.mosaic.cli --remove <id> --apply
"""
from __future__ import annotations

import argparse
import json

from nomos.mosaic import browser
from nomos.mosaic.engine import MosaicEngine

EXIT_OK, EXIT_USAGE, EXIT_REJECTED = 0, 2, 3


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="nomos.mosaic.cli",
                                description="NOMOS Mosaic — painel de telas ao vivo, isoladas.")
    a = p.add_mutually_exclusive_group(required=True)
    a.add_argument("--add", metavar="URL", help="adiciona uma tela (email/rede/marketplace)")
    a.add_argument("--list", action="store_true")
    a.add_argument("--remove", metavar="ID")
    a.add_argument("--scan", action="store_true", help="vistoria (todas ou --screen)")
    a.add_argument("--panel", action="store_true", help="gera o painel HTML do mosaico")
    a.add_argument("--act", metavar="ID", help="propõe/executa ação numa tela")
    a.add_argument("--context", action="store_true", help="resumo do que o agente já sabe")
    a.add_argument("--demo", action="store_true",
                   help="carrega telas SIMULADAS de apresentação (Gmail, BB, WhatsApp, TikTok…)")

    m = p.add_mutually_exclusive_group()
    m.add_argument("--apply", action="store_true", help="grava/age (sem isto = dry-run)")
    m.add_argument("--dry-run", action="store_true")

    p.add_argument("--label", default="")
    p.add_argument("--screen", default=None, help="alvo do --scan")
    p.add_argument("--action", default=None, help="monitor|mark_read|reply|archive (com --act)")
    p.add_argument("--approve", action="store_true", help="aprova a ação (com --act --apply)")
    p.add_argument("--adapter", default="demo", choices=["demo", "playwright"])
    p.add_argument("--base-dir", default=None)
    p.add_argument("--json", action="store_true")
    return p


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    eng = MosaicEngine(base_dir=args.base_dir, adapter=browser.get_adapter(args.adapter))
    apply = bool(args.apply)

    # Horizonte 3/missao de debitos, P2 (2026-07-17): cada bloco abaixo usa
    # um nome PRÓPRIO para o resultado (r_add/r_demo/r_remove/sr/r_act) em
    # vez de reaproveitar "r"/"res" entre blocos mutuamente exclusivos. Os
    # métodos de MosaicEngine devolvem tipos DIFERENTES (dict simples aqui;
    # dataclasses ScanResult/ActionResult mais abaixo) — mypy infere um
    # único tipo estático por nome de variável na função inteira, então
    # reusar o nome fazia o segundo uso "colidir" com o tipo do primeiro.
    # Renomear é puramente mecânico, nenhum comportamento muda.
    if args.add is not None:
        r_add = eng.add_screen(args.add, args.label, apply=apply)
        print(json.dumps(r_add, ensure_ascii=False, indent=2) if args.json else
              (f"OK tela: {r_add['screen']['id']} → {r_add['screen']['url']}" if r_add["applied"]
               else f"DRY-RUN: adicionaria {r_add['url']} (use --apply)"))
        return EXIT_OK

    if args.demo:
        r_demo = eng.seed_demo(apply=apply)
        if args.json:
            print(json.dumps(r_demo, ensure_ascii=False, indent=2))
        elif r_demo.get("applied"):
            print(f"telas de exemplo carregadas: {', '.join(r_demo['added']) or '(já existiam)'} "
                  f"· total {r_demo['total']}")
        else:
            print(f"DRY-RUN: carregaria {', '.join(r_demo['would_add'])} (use --apply)")
        return EXIT_OK

    if args.list:
        telas = eng.list_screens()
        if args.json:
            print(json.dumps([s.__dict__ for s in telas], ensure_ascii=False, indent=2))
        elif not telas:
            print("(sem telas)")
        else:
            for s in telas:
                print(f"{s.id}  {s.label}  [{s.url}]")
        return EXIT_OK

    if args.remove is not None:
        r_remove = eng.remove_screen(args.remove, apply=apply)
        print(json.dumps(r_remove, ensure_ascii=False) if args.json else
              (f"removida: {r_remove.get('removed')}" if apply else "DRY-RUN (use --apply)"))
        return EXIT_OK

    if args.scan:
        res = eng.scan(screen_id=args.screen, apply=apply)
        if args.json:
            print(json.dumps([{"screen": sr.screen_id, "ok": sr.ok, "saved": sr.saved,
                               "signals": sr.snapshot.signals} for sr in res],
                             ensure_ascii=False, indent=2))
        else:
            estado = "APLICADO" if apply else "DRY-RUN (não salvou)"
            print(f"Vistoria [{estado}]: {len(res)} tela(s)")
            for sr in res:
                print(f"  {sr.screen_id}: {sr.snapshot.title} · {sr.snapshot.signals}")
        return EXIT_OK

    if args.panel:
        html, path = eng.render_panel(apply=apply)
        if path:
            print(f"painel gravado: {path}")
        else:
            n_tiles = html.count('class="tile"')
            print(f"DRY-RUN: painel com {n_tiles} tela(s) ({len(html)} bytes). "
                  "Use --apply para gravar.")
        return EXIT_OK

    if args.act is not None:
        if not args.action:
            print("faltou --action")
            return EXIT_USAGE
        r_act = eng.act(args.act, args.action, approve=args.approve, apply=apply)
        if args.json:
            print(json.dumps(r_act.__dict__, ensure_ascii=False, indent=2))
        else:
            print(f"ação '{r_act.action}' em {r_act.screen_id}: {r_act.reason} "
                  f"(applied={r_act.applied}, approved={r_act.approved})")
        return EXIT_REJECTED if r_act.reason.endswith("FAIL_CLOSED") else EXIT_OK

    if args.context:
        print(eng.context())
        return EXIT_OK

    return EXIT_USAGE


if __name__ == "__main__":
    raise SystemExit(main())
