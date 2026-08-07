#!/usr/bin/env python3
"""Reprodução standalone do KNOWN_GAP sinalizado no commit `75c6132`
("H3-missao-debitos P2 (6/8) — interface/painel_web.py") mas nunca
efetivamente registrado no relatório final da missão até este adendo:

    "ao escrever o teste de 'perfil corrompido', descobri que
    dados_dashboard() já crasha antes de chegar neste bloco corrigido,
    porque chama doutor_mod.diagnostico_v011(home, ctx) mais cedo na mesma
    função (fora de qualquer try/except), que por sua vez chama
    config.load_agent() SEM proteção contra JSON inválido. Fragilidade
    PRÉ-EXISTENTE e INDEPENDENTE, em outro arquivo (doutor.py/config.py)
    — fora do escopo desta correção [...] sinalizada para o relatório
    final da missão como um KNOWN_GAP a considerar depois do P2."

Uso:
    python3 repro_known_gap_agent_json_crashes_doutor.py

Não corrige nada — só demonstra, com um NOMOS_HOME temporário e
descartável, que:
  1. `config.load_agent()` (kernel/config.py) chama `json.loads()` SEM
     nenhum try/except ao redor — qualquer exceção de parse propaga crua;
  2. `doutor.diagnostico_v011()` chama `config.load_agent()` na primeira
     dúzia de linhas da função, também sem proteção — então um
     `agent.json` corrompido faz a função INTEIRA (não só o item que
     checaria o agente) lançar `json.JSONDecodeError` não tratada;
  3. isso derruba tanto `nomos doutor` quanto `dados_dashboard()` do
     painel web (que chama `diagnostico_v011()` internamente) — ou seja,
     a MESMA ferramenta cujo propósito é diagnosticar e oferecer conserto
     para corrupção de dados (`nomos doutor consertar`) fica inutilizável
     justamente quando `agent.json` (não coberto por
     `diagnosticar_consertos()`, que só olha localidade.json/policy.json/
     skills_estado.json/rotinas.json) está corrompido.

Este script não faz parte da suíte de testes automatizada (não usa
pytest) deliberadamente: é só uma demonstração isolada e reproduzível
da falha, para acompanhar o registro em KNOWN_GAPS sem introduzir um
teste permanente sobre um comportamento que ainda não foi corrigido."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "src")


def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        home = Path(d)
        os.environ["NOMOS_HOME"] = str(home)
        home.mkdir(parents=True, exist_ok=True)
        # agent.json corrompido — JSON sintaticamente inválido, o tipo de
        # corrupção mais comum (escrita interrompida, edição manual malfeita)
        (home / "agent.json").write_text(
            "{corrompido: sem aspas, json invalido", encoding="utf-8")

        from nomos.kernel import config
        crashou_config = False
        try:
            config.load_agent()
        except Exception as exc:
            crashou_config = True
            print(f"1) config.load_agent() CRASHA sem try/except: "
                  f"{type(exc).__name__}: {exc}")
        if not crashou_config:
            print("1) config.load_agent() não crashou — bug pode já "
                  "estar corrigido; atualize KNOWN_GAPS.")

        from nomos.simple import doutor
        crashou_doutor = False
        try:
            doutor.diagnostico_v011(home)
        except Exception as exc:
            crashou_doutor = True
            print(f"2) doutor.diagnostico_v011() CRASHA (não é um item "
                  f"'bloqueante' reportado — a função inteira aborta): "
                  f"{type(exc).__name__}: {exc}")
        if not crashou_doutor:
            print("2) diagnostico_v011() não crashou — bug pode já estar "
                  "corrigido; atualize KNOWN_GAPS.")

        # agent.json NÃO está entre os 4 arquivos que o próprio doutor
        # sabe diagnosticar/consertar (diagnosticar_consertos): ou seja,
        # a ferramenta de auto-conserto nem OFERECE reparo para este caso.
        achados = doutor.diagnosticar_consertos(home)
        cobre_agent_json = any("agent.json" in a["id"] for a in achados)
        print(f"3) 'nomos doutor consertar' sabe reparar agent.json "
              f"corrompido? {cobre_agent_json}")

        print()
        if crashou_config and crashou_doutor and not cobre_agent_json:
            print("RESULTADO: falha reproduzida como documentado no commit "
                  "75c6132 e neste KNOWN_GAP (crash sem try/except em "
                  "config.load_agent(), propagado por diagnostico_v011(), "
                  "e agent.json fora da cobertura de diagnosticar_consertos()).")
            return 1
        print("RESULTADO: comportamento diferente do documentado em "
              "KNOWN_GAPS — revisar o achado.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
