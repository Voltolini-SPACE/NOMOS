# FASE 6 — RECENSO DE FILESYSTEM

**0 FULL / 8 PARTIAL / 1 MISSING / 2 FORA_DO_NUCLEO · 5 críticas em gap.**
Inalterado em relação à 04 — nenhum código de FS foi tocado nesta missão, que
era de wiring.

O que falta já não é caller (fechado na 03) nem confinamento (fechado na 03):
é **equivalência comportamental** específica.
- `FS-READ-BINARY` MISSING — sem equivalente ao `/api/fs/read-data-url`;
- `fs-editar` sem patch unificado/multi-arquivo nem diff auditável;
- nativas `arquivo_ler`/`arquivo_resumir` sem resolver próprio (protegidas
  apenas quando `--raiz` é usado).

```
FS_CRITICAL_GAPS_RECOUNTED = 5
FS_UNGOVERNED_RECOUNTED    = ver PARITY_MATRIX.json
```
