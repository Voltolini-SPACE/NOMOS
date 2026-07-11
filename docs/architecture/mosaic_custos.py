#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Modelo de unit economics do NOMOS · MOSAIC (SaaS).
Preços unitários = pesquisa 09/07/2026 (fontes no doc). Uso = ESTIMATIVA (validar em piloto).
Cenários: 'otim' / 'esp' (esperado, COM disciplina) / 'risco' (sem controle).

v2: modela a ARQUITETURA EM CASCATA da decisão do agente —
    a maioria das ações é resolvida por API oficial / regras / modelo pequeno local
    (custo ~0 na nuvem); só uma fração chama o LLM caro da nuvem (geração/entendimento).
    Compara com o baseline 'LLM em tudo'.
"""

USD_BRL = 5.16  # 09/07/2026

# ---- CUSTOS UNITÁRIOS (USD): otim / esp / risco -----------------------------
gpu_parse    = {"otim": 0.00025, "esp": 0.0005, "risco": 0.0011}
brain_cloud  = {"otim": 0.0006,  "esp": 0.0015, "risco": 0.005}   # custo de 1 ação NO LLM da nuvem
local_action = 0.00015                                             # ação resolvida por modelo pequeno local (GPU compartilhada)
# fração das ações que REALMENTE precisam do LLM da nuvem (resto = API/regras/local):
cloud_frac   = {"otim": 0.10, "esp": 0.20, "risco": 0.55}
browser_hr   = {"otim": 0.008, "esp": 0.015, "risco": 0.10}
voice_rt_min = {"otim": 0.06,  "esp": 0.12,  "risco": 0.25}
voice_async_min = 0.003
stream_th    = {"otim": 0.01,  "esp": 0.032, "risco": 0.08}
fixed_cust   = {"otim": 0.30,  "esp": 0.75,  "risco": 2.00}

def brain_eff(s):   # custo efetivo por ação COM cascata
    return cloud_frac[s] * brain_cloud[s] + (1 - cloud_frac[s]) * local_action

# ---- USO POR TIER (mensal, ESTIMATIVA = cotas) ------------------------------
tiers = {
    "Base (Essencial)": dict(parses=1500,  actions=1500,  bhr=15,  rt=0,   asy=30,  watch=8),
    "Pro":              dict(parses=5000,  actions=5000,  bhr=60,  rt=30,  asy=60,  watch=30),
    "Business":         dict(parses=15000, actions=15000, bhr=200, rt=120, asy=120, watch=100),
}
preco_brl = {"Base (Essencial)": 97, "Pro": 347, "Business": 797}

def cogs(t, s, cascata=True):
    u = tiers[t]
    ba = brain_eff(s) if cascata else brain_cloud[s]
    return {
        "Cérebro (LLM/local)": u["actions"] * ba,
        "GPU (visão)":         u["parses"]  * gpu_parse[s],
        "Voz tempo real":      u["rt"]      * voice_rt_min[s],
        "Streaming ao vivo":   u["watch"]   * stream_th[s],
        "Browsers":            u["bhr"]     * browser_hr[s],
        "Voz áudio/transcr.":  u["asy"]     * voice_async_min,
        "Infra fixa":          fixed_cust[s],
    }

print("=" * 80)
print("NOMOS · MOSAIC — CUSTO POR CLIENTE / MÊS  (câmbio %.2f)  [v2: cascata]" % USD_BRL)
print("=" * 80)
print("Fração de ações que chamam o LLM da nuvem: otim %.0f%% / esp %.0f%% / risco %.0f%%"
      % (cloud_frac["otim"]*100, cloud_frac["esp"]*100, cloud_frac["risco"]*100))

for t in tiers:
    print("\n" + "-" * 80)
    print("TIER: %-18s  preço: R$ %d/mês" % (t, preco_brl[t]))
    print("-" * 80)
    print("%-22s %9s %9s %9s" % ("Componente (USD)", "otim", "esperado", "risco"))
    tot = {"otim": 0.0, "esp": 0.0, "risco": 0.0}
    cc = {s: cogs(t, s) for s in tot}
    for k in cc["esp"]:
        print("%-22s %9.2f %9.2f %9.2f" % (k, cc["otim"][k], cc["esp"][k], cc["risco"][k]))
        for s in tot:
            tot[s] += cc[s][k]
    print("%-22s %9.2f %9.2f %9.2f" % ("TOTAL COGS (USD)", tot["otim"], tot["esp"], tot["risco"]))
    print("%-22s %9.0f %9.0f %9.0f" % ("TOTAL COGS (BRL)", tot["otim"]*USD_BRL, tot["esp"]*USD_BRL, tot["risco"]*USD_BRL))
    receita_liq = preco_brl[t] * 0.88
    for lbl, s in (("esperado", "esp"), ("risco", "risco")):
        m = (receita_liq - tot[s]*USD_BRL) / receita_liq * 100
        print("  margem %-10s = %+.0f%%" % (lbl, m))

# ---- Comparação: COM cascata x SEM (LLM em tudo), caso esperado -------------
print("\n" + "=" * 80)
print("IMPACTO DA CASCATA (caso esperado) — só a linha do cérebro muda")
print("=" * 80)
print("%-20s %14s %14s %10s" % ("Tier", "SEM cascata", "COM cascata", "economia"))
for t in tiers:
    sem = sum(cogs(t, "esp", cascata=False).values()) * USD_BRL
    com = sum(cogs(t, "esp", cascata=True).values()) * USD_BRL
    print("%-20s R$ %9.0f R$ %9.0f %8.0f%%" % (t, sem, com, (sem-com)/sem*100))

print("\nCusto por ação — cérebro:")
print("  LLM nuvem (esperado):   R$ %.4f/ação" % (brain_cloud["esp"]*USD_BRL))
print("  Cascata (esperado):     R$ %.4f/ação  (%.0f%% nuvem, resto API/regras/local)"
      % (brain_eff("esp")*USD_BRL, cloud_frac["esp"]*100))
