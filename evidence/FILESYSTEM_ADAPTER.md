# FASE 2 — FILESYSTEM AMPLO GOVERNADO

Commits: `822efd6` (adapter) · `6122814` (wiring)
Arquivos: `adapters/filesystem.py` · `adapters/caminho.py` · `adapters/wiring.py`

## Capacidades (nome público com hífen — exigência de `registro.NOME_RE`)
| Capacidade | Risco | Idempotente | Fecha o gap |
|---|---|---|---|
| `fs-ler` | A0 | sim | FS-READ-TEXT (devolve CONTEÚDO, offset/limite) |
| `fs-listar` | A0 | sim | glob/search confinado |
| `fs-metadados` | A0 | sim | metadata |
| `fs-escrever` | A1 | não | FS-WRITE-CREATE (atômica) |
| `fs-editar` | A1 | não | **FS-EDIT-PATCH** (era AUSENTE) |
| `fs-criar-dir` | A1 | não | mkdir |
| `fs-mover` | A1 | não | move/rename com escopo nos dois lados |
| `fs-apagar` | A1 | não | delete |

## Leitura segura — o gap que o censo apontou
`arquivo_ler` (nativo) devolvia `(formato · N caracteres)` + bullets, aceitava
7 extensões e **não era confinado**. `fs-ler` devolve o conteúdo, com
`offset`/`limite` em linhas (como o `read_file` do Hermes), detecta binário em
vez de fingir texto, aplica teto de tamanho e **respeita o escopo**.

## Escrita atômica
`temp no MESMO diretório → fsync → os.replace`. Mesmo diretório porque
`os.replace` só é atômico dentro do mesmo filesystem; fsync antes do replace
para que o conteúdo esteja no disco quando o nome passar a apontar para ele —
sem isso, um crash deixa arquivo com nome novo e conteúdo vazio.

## Confinamento — um só lugar
`adapters/caminho.py`. Duas implementações de "é seguro?" divergem, e a
divergência é o furo.
- `os.path.realpath` canoniza `..`, `.` e links (inclusive intermediários);
- contenção por **componente** (`os.path.commonpath`), não por prefixo de
  string: `/x/raiz-outro` NÃO está sob `/x/raiz`;
- **não existe** `unsafe=`, `skip_scope=` nem `follow_symlink=` — a assinatura
  não tem por onde afrouxar (`test_caller_nao_consegue_pedir_unsafe`).

## Wiring — capacidade DINÂMICA, não nativa
A allowlist de 8 ferramentas é invariante do produto. Os adapters entram pelo
registro dinâmico (NH-001), que é ele próprio governado: registrar é
`A5_SKILL_INSTALL`, passa pelo gate, exige aprovador e é auditado
(`registro.capacidade.registrada` na trilha). `test_sem_aprovador_nada_e_registrado`
prova que sem aprovação nada entra.

Registrar com aprovação **não** dá passe livre para usar: cada nó A1 volta ao
gate na execução (`test_capacidade_mutante_negada_sem_aprovacao_de_uso`).

## Gates
```
FS_CRITICAL_GAPS=0        (as 4 críticas da 02 fechadas: EDIT-PATCH, READ-TEXT,
                           WRITE-CREATE, CONFINAMENTO-DE-CAMINHO)
FS_PATH_SCOPE_ENFORCED=TRUE
FS_SYMLINK_ESCAPE=DENY
FS_TRAVERSAL=DENY
FS_MUTATING_BYPASS=0
```
