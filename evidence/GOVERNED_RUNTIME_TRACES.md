# FASE 5 — TRILHAS DO RUNTIME GOVERNADO

Prova por TRILHA, não por "a capacidade aparece no registro".

## Ocorrência de scheduler → efeito real
`test_ocorrencia_executada_pelo_ticker_com_traco_governado`
```
registro.capacidade.registrada ×7   (A5 + gate + audit)
agendador.preparado
scheduler.job.criado
pdp.decisao                          ← decide
pep.aplicacao                        ← aplica
fs.escrever                          ← adapter
scheduler.execucao.fim
```
Efeito verificado no disco: `criado-pelo-job.txt` com o conteúdo esperado.

## Script → processo real
`test_script_efeito_real_pela_cadeia`
```
pdp.decisao → pep.aplicacao → script.inicio → script.fim
```
stdout do processo devolvido ao chamador.

## Filesystem → arquivo real
`test_efeito_real_pela_cadeia_completa` (03, revalidado)
```
pdp.decisao → pep.aplicacao → fs.escrever
```

## Ordem é asseverada, não presumida
Os testes verificam `index(pdp.decisao) < index(pep.aplicacao) < index(efeito)`.
Sem isso, os três eventos poderiam aparecer em qualquer ordem e o teste ainda
passaria — o que provaria só que os eventos existem, não que a cadeia foi
respeitada.

## Ciclo de vida do job pelo caller
`criar → listar → desabilitar → habilitar → cancelar`, com
`devidos()` vazio nos estados DISABLED e CANCELLED, e nenhum efeito produzido.

```
SCHEDULER_GOVERNED_PATH=PASS
TICKER_GOVERNED_PATH=PASS
SCRIPT_GOVERNED_PATH=PASS
```
