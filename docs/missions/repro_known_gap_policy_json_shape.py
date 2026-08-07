#!/usr/bin/env python3
"""Reprodução standalone do KNOWN_GAP documentado em
docs/missions/H3_MISSAO_DEBITOS_ADENDO_COBERTURA_ORCHESTRATOR_E_KNOWN_GAP.md
(seção "Achado: policy.json sintaticamente válido mas de tipo errado
derruba PolicyEngine.decide(), e nomos doutor não detecta o problema").

Uso:
    python3 repro_known_gap_policy_json_shape.py

Não corrige nada — só demonstra, com um NOMOS_HOME temporário e descartável,
que:
  1. um policy.json contendo JSON sintaticamente válido mas do tipo errado
     (uma lista `[]` em vez de um objeto) faz `PolicyEngine.decide()`
     lançar `AttributeError` não tratado, em vez de negar de forma
     controlada (fail-closed "educado");
  2. `nomos doutor` (via `diagnosticar_consertos()`) NÃO detecta esse
     policy.json como corrompido, porque sua checagem só testa se o JSON
     faz parse (`json.loads()` sem exceção), não se tem o formato esperado
     — então o usuário não recebe nenhum aviso nem oferta de conserto.

Este script não faz parte da suíte de testes automatizada (não usa
pytest) deliberadamente: é só uma demonstração isolada e reproduzível
da falha, para acompanhar o registro em KNOWN_GAPS sem introduzir um
teste permanente sobre um comportamento que ainda não foi corrigido."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "src")

from nomos.kernel.policy import Category, PolicyEngine   # noqa: E402
from nomos.simple.doutor import diagnosticar_consertos    # noqa: E402


def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        home = Path(d)
        p = home / "policy.json"
        # JSON sintaticamente VÁLIDO, mas do tipo errado (lista, não dict) —
        # exatamente o tipo de corrupção que um editor de texto, um `echo`
        # errado, ou uma ferramenta externa mal-comportada produziria com
        # facilidade sem gerar um erro de parse.
        p.write_text("[]", encoding="utf-8")

        pe = PolicyEngine(p)
        print(f"1) PolicyEngine.rules() não lança exceção: {pe.rules()!r}")

        crashou = False
        try:
            pe.decide(Category.NET_EGRESS, "example.com")
        except AttributeError as exc:
            crashou = True
            print(f"2) PolicyEngine.decide() CRASHOU (não tratado): "
                  f"{type(exc).__name__}: {exc}")
        if not crashou:
            print("2) PolicyEngine.decide() NÃO crashou — bug pode já "
                  "estar corrigido; atualize KNOWN_GAPS.")

        achados = diagnosticar_consertos(home)
        flagged = any(a["id"] == "arquivo:policy.json" for a in achados)
        print(f"3) 'nomos doutor' detectou o policy.json como corrompido? "
              f"{flagged}")

        print()
        if crashou and not flagged:
            print("RESULTADO: falha reproduzida como documentado em "
                  "KNOWN_GAPS (crash não tratado + doutor não detecta).")
            return 1
        print("RESULTADO: comportamento diferente do documentado em "
              "KNOWN_GAPS — revisar o achado.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
