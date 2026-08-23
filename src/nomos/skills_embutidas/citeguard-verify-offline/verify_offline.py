#!/usr/bin/env python3
"""citeguard-verify-offline — verifica citações SEM tocar a rede.

Autocontido de propósito: só stdlib e só o arquivo que recebe. Não chama o
citeguard.py do repositório porque a cerca do sandbox (deny default) não deixa
ler fora do workdir — uma skill que dependesse de caminho do disco do dono
seria instalável e inútil.

O que consegue provar sem rede:
  - DOI e arXiv id malformados (a forma é verificável offline);
  - placeholder que fingem ser fonte (example.com, doi.org/10.xxxx, TODO);
  - host privado, loopback ou link-local disfarçado de fonte pública.
O que NÃO consegue: se o DOI existe, e se foi retratado. Isso exige rede — e a
skill diz isso na saída em vez de deixar o silêncio parecer aprovação.
"""
from __future__ import annotations

import ipaddress
import json
import re
import sys
from urllib.parse import urlparse

DOI = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+\b")
# placeholder de DOI NÃO casa em DOI (que exige dígitos) — por isso tem
# padrão próprio. Sem ele, "10.xxxx/fake" passava despercebido: o texto
# parecia citado e nada era apontado.
DOI_PLACEHOLDER = re.compile(r"\b10\.(?:x{4,}|0{4}|1234|nnnn)\S*", re.I)
ARXIV = re.compile(r"\barXiv:\s*(\d{4}\.\d{4,5})(v\d+)?\b", re.I)
URL = re.compile(r"https?://[^\s<>\"')\]]+")
PLACEHOLDER = ("example.com", "example.org", "localhost", "foo.bar",
               "your-domain", "TODO", "FIXME", "XXXX")


def _host_privado(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return host in ("localhost",) or host.endswith(".local")
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved


def verificar(texto: str) -> dict:
    achados: list[dict] = []

    def falha(tipo, alvo, motivo):
        achados.append({"nivel": "FAIL", "tipo": tipo, "alvo": alvo, "motivo": motivo})

    for m in DOI_PLACEHOLDER.finditer(texto):
        falha("doi", m.group(0), "placeholder de DOI (10.xxxx/10.0000/10.1234)")
    for m in DOI.finditer(texto):
        doi = m.group(0)
        if doi.rstrip("._;()/").endswith(("/", ".")):
            falha("doi", doi, "sufixo truncado")
    for m in ARXIV.finditer(texto):
        num = m.group(1)
        aa, mm = num.split(".")[0][:2], num.split(".")[0][2:]
        if not ("01" <= mm <= "12"):
            falha("arxiv", m.group(0), f"mês inválido no id: {mm}")
    for m in URL.finditer(texto):
        u = m.group(0)
        host = (urlparse(u).hostname or "").lower()
        if any(p.lower() in u.lower() for p in PLACEHOLDER):
            falha("url", u, "placeholder, não é fonte real")
        elif host and _host_privado(host):
            falha("url", u, "host privado/loopback — inalcançável para quem lê")

    n_doi = len(set(DOI.findall(texto)))
    n_arxiv = len(set(x[0] for x in ARXIV.findall(texto)))
    return {
        "citacoes_encontradas": {"doi": n_doi, "arxiv": n_arxiv,
                                 "url": len(set(URL.findall(texto)))},
        "falhas": achados,
        "veredito": "FAIL" if achados else "PASS",
        "limite_declarado": ("modo OFFLINE: não confirma existência do DOI nem "
                             "retratação — isso exige rede"),
    }


def main(argv: list[str]) -> int:
    alvo = None
    if len(argv) > 1:
        try:
            args = json.loads(open(argv[1], encoding="utf-8").read())
            alvo = args.get("arquivo") or args.get("texto")
        except Exception:
            alvo = argv[1]
    texto = ""
    if alvo and len(alvo) < 4096:
        try:
            texto = open(alvo, encoding="utf-8", errors="replace").read()
        except OSError:
            texto = alvo
    else:
        texto = alvo or sys.stdin.read()
    r = verificar(texto)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 1 if r["veredito"] == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
