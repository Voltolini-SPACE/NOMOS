# NOMOS v1.3.0rc18

## Status

```text
PREPARED_ONLY=true
TAG_CREATED=false
BRANCH_PUSHED=false
RELEASE_PUBLISHED=false
PYPI_PUBLISHED=false
```

Este documento é preparado no commit de versão (`chore(nomos): bump
version to 1.3.0rc18`, `3733e1b`), antes de qualquer tag ou push. A
versão empacotada (`pyproject.toml` / `src/nomos/__init__.py`) já é
`1.3.0rc18` neste ponto da árvore local. Nenhuma tag, GitHub Release ou
publicação no PyPI foi criada por este documento — ver
`docs/missions/H4_6_PROMOCAO_1_3_0RC18_RELATORIO.md` para o estado real
de tag/push/CI no momento em que a missão H4.6 foi concluída.

## Resumo

Fecha, num único ponto de corte de versão, tudo que se acumulou em
`CHANGELOG.md` desde `1.3.0rc17` (2026-07-05): a rodada de higiene "Fase
0", os Horizontes 1–3 de auditoria e correção, a missão H3
("missão-débitos": zerar os 77 erros de mypy remanescentes e reproduzir
os gates de CI em Python 3.12 real), e as missões H4 e H4.5 de selagem
arquitetural. Nenhuma feature nova de produção — só correção,
endurecimento e prova.

## Corrigido

- `agent.json` corrompido não derruba mais o diagnóstico
  (`doutor.diagnostico_v011()` isola a leitura, HIGH-01/H4).
- O reparo (`doutor.consertar()`) preserva a evidência original: arquivo
  corrompido vai para quarentena (`.corrompido`, `.corrompido.N` sem
  sobrescrever), com hash SHA-256, modo 0600 e caminho registrados na
  resposta e na auditoria; falha durante o `os.replace()` atômico
  preserva o original e pára o reparo com diagnóstico verificável, sem
  catch genérico mudo (H4.5-B).
- `policy.json` de tipo incorreto (raiz `[]`, `null`, string) não derruba
  mais o motor de política — `PolicyEngine.rules()` valida o tipo raiz e
  cai para o padrão fail-closed restritivo em vez de propagar exceção
  (HIGH-02/H4).
- Política inválida nega execução governada de verdade: provado pelo
  caminho público real (`nomos agentes usar` → `AgentToolBoundary` →
  `PolicyEngine.decide()` → `gate()`), não por chamada direta a método
  privado — inclusive para ações com efeito externo, onde o callback de
  execução nunca chega a ser invocado quando a política é negada
  (H4.5-A).
- Fronteira `AgentToolBoundary` protegida por gate arquitetural AST:
  prova, por análise estática (stdlib apenas), que só os 2 caminhos de
  produção legítimos (`cli.py`, `simple/amigavel.py`) importam o
  executor concreto de ferramentas, que `nomos.agents.*` nunca chama
  subprocess/rede diretamente, e que todo o pacote `nomos.council` (16
  arquivos) segue livre de `nomos.agents` e de subprocess/rede — com
  fixtures sintéticas provando que o gate de fato detecta um bypass
  quando ele existe (H4.5-C).
- Contratos residuais do Council fortalecidos: timeout de um motor não
  derruba o conselho quando há outro candidato saudável; um parecer
  malformado (nota fora de 0–5, tipo inválido, alias vazio) é rejeitado
  na própria construção do objeto, fail-closed; quórum insuficiente não
  fabrica conteúdo nem elege vencedor (inclusive no sub-caso "zero
  juízes"); a decisão final sempre preserva o motivo de rejeição/dissenso
  quando bloqueada (H4.5-D).
- 77 erros de mypy remanescentes em 8 arquivos do `src/nomos` zerados,
  classificados individualmente antes de corrigir (nenhuma supressão
  genérica) — `mypy src/nomos` fecha em `Success: no issues found`
  (H3-missão-débitos, P2).

## Conhecido e não implementado

- O Council ainda é **single-pass**: não existe deliberação
  multi-rodada no código atual (`rg -i "round|rodada"` em todo
  `src/nomos/council/` não encontra nenhuma ocorrência).
- **Limite de rodadas** não existe no runtime atual — decorre
  diretamente do ponto acima; não há "rodadas" para limitar.
- **Orçamento deliberativo** do Council ainda não existe (`rg -i
  "budget|orcamento|orçamento"` em todo `src/nomos/council/` também não
  encontra nada). Nenhum dos dois itens acima é uma regressão: é o
  estado real e documentado da arquitetura nesta fase (MC1–MC8,
  dry-run), registrado como gap arquitetural em
  `tests/test_h4_5_d_council_contract_residuals.py` e no relatório H4.5.
- **Publicação depende da autenticação remota**: o ambiente de execução
  automatizada não tem credencial git funcional
  (`could not read Password for 'https://...@github.com'`); push de
  branch e tag dependem de o usuário publicar com sua própria credencial
  (local ou via GitHub Desktop).
- **Compatibilidade Python 3.12** foi reproduzida localmente com um
  interpretador 3.12 real (não simulada) na missão H3-missão-débitos,
  P4, e permanece com o estado real documentado naquele relatório —
  ver `docs/missions/H3_MISSAO_DEBITOS_P4_CI_GATES_PYTHON312.md` para o
  detalhe exato (não repetido aqui para não divergir de uma fonte única).

## Gates locais (evidência)

Ver `docs/missions/H4_6_PROMOCAO_1_3_0RC18_RELATORIO.md` para comandos,
retornos e resultados completos desta promoção (suíte completa, mypy,
ruff, cobertura geral/dirigida, gate AST, build/smoke do wheel,
`nomos_update_agent.py --check`, hash do artefato, tag local, tentativa
de push e verificação remota).

## Próximo passo recomendado

Publicar a branch e a tag `v1.3.0rc18` com credencial válida (usuário),
depois confirmar CI remoto real antes de qualquer promoção para
`1.3.0` estável.
