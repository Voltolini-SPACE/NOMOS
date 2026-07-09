# NOMOS Memory Engine V1

Memória persistente **local-first**, **auditável** e **fail-closed** para o
NOMOS e para o Claude Code. Inspirada na auditoria do `claude-mem`
([EXTERNAL_MEMORY_REPO_AUDIT_MC28.md](EXTERNAL_MEMORY_REPO_AUDIT_MC28.md)),
porém **sem depender dele**: motor próprio, só biblioteca padrão do Python.

```
NOMOS_MEMORY_ENGINE_V1 · LOCAL_FIRST · AUDITABLE · DRY_RUN_DEFAULT ·
FAIL_CLOSED · NO_NETWORK_RUNTIME · NO_SECRET_STORAGE · ROLLBACK_READY
```

## 1. Objetivo

Dar ao agente uma memória que **atravessa sessões** sem abrir mão de segurança:
nada sai da máquina, nada é gravado sem revisão (`--apply`), segredos e dados
sensíveis são **recusados** antes de tocar o disco, e cada entrada carrega um
hash de integridade que denuncia adulteração manual.

## 2. Arquitetura

Pacote `nomos.memory` (em `src/nomos/memory/`), **autocontido** — não importa o
resto do NOMOS nem qualquer plugin externo:

| Módulo | Responsabilidade |
|---|---|
| `store.py` | Persistência local (JSONL append-only), hash SHA-256, escrita atômica, permissões 0600, índice, identidade (`new_id`, `now_iso`). |
| `policy.py` | Política **fail-closed**: detecta segredos, CPF/CNPJ, chaves, cookies, comandos perigosos → recusa com `MEMORY_REJECTED_FAIL_CLOSED`. |
| `compactor.py` | Compactação **determinística** (sem LLM), preservando o histórico bruto. |
| `context_builder.py` | Contexto curto e barato em tokens para reiniciar sessão. |
| `report.py` | Relatório operacional (evidência auditável). |
| `engine.py` | Orquestra tudo. Dry-run é o padrão; apply só grava se a política aprovar. |
| `cli.py` / `__main__.py` | Interface de linha de comando. |

Isolamento é intencional: **apagar `src/nomos/memory/` remove o recurso inteiro**
sem efeito colateral (rollback trivial). Nada no NOMOS importa este pacote.

## 3. Formato dos arquivos

Base padrão: `~/.nomos/memory/` (respeita `NOMOS_HOME`; sobrescreva com
`--base-dir` para isolamento/testes).

```
~/.nomos/memory/
  memory.jsonl            # histórico BRUTO, append-only (fonte da verdade)
  memory.compacted.jsonl  # derivado da compactação (nunca substitui o bruto)
  memory.index.json       # índice/estatística (derivado)
  reports/                # relatórios operacionais (evidência)
```

Entrada (uma por linha em `memory.jsonl`):

```json
{
  "id": "mem_20260709T161038_000974e7",
  "created_at": "2026-07-09T16:10:38Z",
  "source": "manual|session_summary|mission_result|handoff|repo_audit",
  "scope": "project|repo|module|temporary",
  "priority": "low|medium|high|critical",
  "tags": ["nomos", "memoria"],
  "content": "memória objetiva",
  "links": [],
  "safety": {
    "contains_secret": false,
    "contains_personal_sensitive_data": false,
    "human_review_required": false
  },
  "hash": "sha256-hex"
}
```

O `hash` cobre o **núcleo canônico** da entrada (todos os campos acima exceto o
próprio `hash`), serializado de forma determinística (chaves ordenadas). Editar
qualquer campo à mão sem recomputar o hash é detectado por `--validate`.

## 4. Política de segurança (fail-closed)

Recusa a gravação (retorna `MEMORY_REJECTED_FAIL_CLOSED`, **nada é gravado**) ao
detectar: API keys (`sk-…`, `AKIA…`, `AIza…`, `ghp_…`, `xox…`), tokens/JWT,
`password`/`secret`/`token` atribuídos, chave privada (`-----BEGIN … PRIVATE
KEY-----`), chaves SSH, cookies/sessão, **CPF**, **CNPJ**, cartão (Luhn), IBAN,
frases-semente (mnemônicos), variáveis de ambiente sensíveis e comandos
destrutivos (`rm -rf`, fork bomb, `mkfs`, `dd if=`, `curl … | sh`). A política é
**conservadora**: na dúvida, bloqueia. Entradas admitidas têm as três flags de
`safety` em `false` por construção — **segredo nunca é armazenado**.

> As assinaturas de detecção são expressões regulares **inertes**. O módulo não
> executa nada: sem `subprocess`, `os.system`, `eval`/`exec`, rede ou qualquer
> efeito além de ler o texto e devolver um veredito.

## 5. Comandos

```bash
python -m nomos.memory.cli --add "texto"                # DRY-RUN (não grava)
python -m nomos.memory.cli --add "texto" --apply        # grava se a política aprovar
python -m nomos.memory.cli --add "texto" --apply \
    --source handoff --scope project --priority high --tags "mc28,memoria"
python -m nomos.memory.cli --list                       # lista o histórico bruto
python -m nomos.memory.cli --context                    # contexto curto p/ nova sessão
python -m nomos.memory.cli --compact                    # planeja (dry-run)
python -m nomos.memory.cli --compact --apply            # grava só o derivado
python -m nomos.memory.cli --validate                   # verifica hashes e estrutura
python -m nomos.memory.cli --report --apply             # gera evidência em reports/
```

Regras: `--dry-run` é o padrão; **nada é escrito sem `--apply`** (vale para add,
compact e report). `--base-dir PATH` isola o armazenamento. `--json` dá saída de
máquina. Uso inválido ou campo inválido **falha fechado** (saídas 2/5).

Códigos de saída: `0` ok · `2` uso inválido · `3` recusa de política · `4`
integridade falhou · `5` campo inválido.

## 6. Exemplo

```bash
$ python -m nomos.memory.cli --add "chave sk-ABCDEF...1234" --apply
MEMORY_REJECTED_FAIL_CLOSED
  motivo: risco detectado -> openai_key
  nada foi gravado.        # exit code 3

$ python -m nomos.memory.cli --add "prefiro entregas com evidência" --apply --priority high
OK gravado: mem_20260709T161038_000974e7
  arquivo: ~/.nomos/memory/memory.jsonl
```

## 7. Rollback

- **Remover o recurso**: apagar `src/nomos/memory/`, os 6 arquivos
  `tests/test_memory_*.py`, os 3 docs (`NOMOS_MEMORY_ENGINE.md`,
  `CLAUDE_MEMORY_USAGE.md`, `EXTERNAL_MEMORY_REPO_AUDIT_MC28.md`) e reverter a
  entrada MC28 no `CHANGELOG.md`. Nada mais depende deste pacote.
- **Zerar dados do usuário**: apagar `~/.nomos/memory/` (ou o `--base-dir` usado).
  O histórico bruto é a única fonte da verdade; o compactado é derivado.
- Via git: `git checkout -- src/nomos/memory tests/test_memory_*.py docs CHANGELOG.md`
  (nenhum arquivo pré-existente foi modificado por esta missão).

## 8. Limitações (V1)

- Busca é por listagem/índice simples (sem FTS/vetorial) — decisão consciente
  para manter stdlib-only e egress zero. A `nomos.cognition.memory` (SQLite/FTS5)
  continua existindo e **não foi alterada**.
- Compactação é determinística (agrupa por escopo+fonte); não faz sumarização
  semântica por LLM (evita rede/custo de tokens).
- Detecção de PII é conservadora e focada em BR (CPF/CNPJ) + segredos comuns;
  pode gerar falso-positivo — por design, prefere bloquear.

## 9. Próximos passos (sugeridos, fora do escopo MC28)

- Subcomando opcional `nomos memory …` no CLI principal (hoje o motor é
  standalone via `python -m nomos.memory.cli`, para máximo isolamento/rollback).
- Recall por relevância opcional reutilizando a infra FTS5 já existente.
- Handoff automático ao fim de missão (proposta em dry-run para revisão humana).
