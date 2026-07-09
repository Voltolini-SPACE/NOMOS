# Automação de propagação — uma fonte, todos os lugares

Objetivo: **toda capacidade nova aparece sozinha em todos os lugares** — README,
site e painel — e a CI **quebra** se algo ficar dessincronizado. Sem marketing
derivando do produto em silêncio.

## A fonte única

`docs/CAPACIDADES.json` é a **única** lista de capacidades do NOMOS. Cada item:

```json
{"id": "mosaic", "nome": "Mosaic — telas ao vivo no painel",
 "resumo": "Várias telas isoladas em mosaico dentro do painel...",
 "area": "painel", "comando": "python -m nomos.mosaic.cli"}
```

## O fluxo (1 minuto)

1. Adicione/edite a capacidade em `docs/CAPACIDADES.json`.
2. Propague para README e site:

   ```bash
   python tools/propagar.py --apply
   ```

   Isso regenera o bloco entre os marcadores
   `<!-- NOMOS:CAPS:START -->…<!-- NOMOS:CAPS:END -->` no `README.md` e no
   `site/index.html`. Idempotente: rodar de novo sem mudança não altera nada.
3. Revise, commit e envie (o push é **seu** — governança):

   ```bash
   git add docs/CAPACIDADES.json README.md site/index.html
   git commit -m "feat: nova capacidade X (propagada)"
   git push origin main
   ```

   Atalho opcional: `python tools/propagar.py --apply --commit` faz o commit
   **local** dos arquivos gerados (nunca faz push).

## O cadeado (por que é "automático de verdade")

- `python tools/propagar.py --check` sai com **código 1** se o README ou o site
  estiverem fora de sincronia com o JSON.
- `tests/test_propagar.py::test_repo_sincronizado` roda esse check na **suíte**.
  Como a CI roda os testes, **esquecer de propagar deixa o CI vermelho** — do
  mesmo jeito que os invariantes `SEC-01…12` e o gate `brand:site_atualizado`.
- O **painel** já reflete o código sozinho (é gerado a partir do próprio NOMOS),
  então capacidades ligadas a comandos aparecem lá automaticamente.

## Comandos

```bash
python tools/propagar.py --check     # gate: 0 em dia, 1 dessincronizado
python tools/propagar.py --apply     # regenera README + site
python tools/propagar.py --report    # tabela do registro
python tools/propagar.py --apply --commit   # + commit LOCAL (sem push)
```

## Fronteira de governança (o que NÃO é automático)

Commit e **push nunca acontecem sozinhos** — seria contra a lei do NOMOS
("nunca se atualiza sozinho / pede licença"). A automação garante que o
**conteúdo** propaga e que a **consistência é forçada** pela CI; a decisão de
publicar continua sua, num comando.

## Limitações / próximos passos

- Hoje o bloco do site é um índice compacto (dentro de "recursos"); os cards
  ricos continuam à mão para não perder o capricho visual — o gate garante que
  toda capacidade do registro está listada.
- Próximo: gerar também os cards ricos do site a partir do JSON (com uma flag),
  e um `nomos capacidades` no CLI que lê a mesma fonte.
