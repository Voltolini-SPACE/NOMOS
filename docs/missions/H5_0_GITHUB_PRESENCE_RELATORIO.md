# H5.0 — NOMOS GitHub Presence: visual + marketing + copy

**Data:** 2026-08-07 · **Método:** implementation-loop-100 · **Branch:** `feat/h5.0-github-presence` (base: `0791af1` = v1.3.0rc20)

## 1. Status

STATUS_FINAL=PASS_100_DELIVERY_READY (pendente apenas de revisão humana + merge, por regra do projeto)

## 2. Objetivo

Elevar a presença pública do NOMOS no GitHub — README, site (Pages), social
preview e metadados do repo — transformando as garantias técnicas já provadas
(H4.8–H4.10B: SLSA, SBOM sha256-bound, builds bit-a-bit reproduzíveis,
1.821 testes) em copy de marketing verificável, sem tocar em runtime.

## 3. Escopo executado

| Superfície | Mudança |
|---|---|
| `README.md` | +3 badges (Release/SLSA/reproduzível); parágrafo de supply chain no hero; bullet "Cadeia de suprimentos provada"; seção nova **"Verifique, não confie"** (3 comandos); Maturidade rc18→rc20, 1.600→1.800+ testes |
| `site/index.html` | #prova: +2 pcards (bit-a-bit, SLSA) + terminal `gh attestation verify` real; hero 1.500+→1.800+; release rc17→rc20 |
| `docs/brand/social-preview.svg` | **novo** — 1280×640, Brandbook v1.0 congelado, SVG puro sem dependência externa |
| `CHANGELOG.md` | entrada `[Unreleased]` H5.0 |
| Metadados do repo | description/homepage/topics via `gh api` (ver §6) |

## 4. Restrições respeitadas

- Zero mudança em `src/`, `tests/` de runtime, workflows, versão, assets rc20.
- Observation window (fecha 2026-08-14T14:48:35Z) intocada: nenhum release/tag alterado.
- Brandbook congelado respeitado: só #5AF78E/#0A0F0D + tagline/assinatura canônicas.
- Anti-overclaim: número anunciado (1.800+) ≤ real (1.821 `def test_`), garantido por teste.

## 5. Evidências

| Validação | Comando | Resultado |
|---|---|---|
| Consistência marca×docs×site | `tools/nomos_update_agent.py --check --json` | 13/13 PASS |
| Site (incl. anti-overclaim) | `pytest tests/test_site_prova.py` | verde |
| Docs/brand sync | `pytest tests/test_cobertura_docs.py tests/test_mc26* tests/test_mc29_brand_sync.py` | 35/35 |
| Visual site | screenshot da seção #prova no browser | cards novos renderizando |
| Visual social preview | screenshot do SVG no browser | identidade correta |

## 6. Passo manual restante (Cowork/humano)

1. **Social preview**: Settings → General → Social preview → upload do
   `docs/brand/social-preview.svg` exportado como PNG 1280×640
   (`qlmanage`/browser print, ou qualquer conversor local). GitHub não expõe
   API para isso — é o único passo fora do terminal.
2. **Merge do PR** após CI verde (regra: push/merge são humanos).

## 7. Fora de escopo registrado

- Release notes/body do release.yml: congelado até a janela fechar (H4.11).
- GIF/screencast do painel no README: candidato a H5.1 (requer gravação real).
