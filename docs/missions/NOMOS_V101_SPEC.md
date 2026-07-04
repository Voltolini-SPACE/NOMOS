# SPEC — Missão v1.0.1 "Ajustes que se sentem no primeiro minuto"

(fase v1.0.1 do ROADMAP_2; versão de pacote: 1.0.0rc2, já que 1.0.0 final não saiu)

## Objetivo
Cinco melhorias imediatas: CLI leve no boot, `doutor --consertar`, backup
completo cifrado do NOMOS_HOME, códigos de erro pesquisáveis e instalação do
motor sem compilador quando houver wheel.

## Escopo incluído
1. **Lazy imports**: `import nomos.cli` não carrega cryptography/argon2/
   cognition; ctx (`_paths`) construído só quando um comando precisa.
2. **`nomos doutor --consertar`**: corrige APENAS itens seguros — pastas do
   home ausentes, `localidade.json`/`skills_estado.json`/`rotinas.json`
   corrompidos (recriados com padrão seguro; original vira `.corrompido`),
   `policy.json` ilegível (idem). Em TTY: lista e pede UMA confirmação
   digitada ("CONSERTAR"); sem TTY: só lista e sai com 3. Tudo auditado.
3. **`nomos backup criar <arquivo>` / `restaurar <arquivo>`**: NOMOS_HOME
   inteiro (exceto `modelos/` e `sandbox/`, avisado) → tar → Fernet+PBKDF2
   600k (sal por arquivo, 0600). Restaurar em home NÃO-vazio exige digitar
   "RESTAURAR" em TTY (sem TTY nega); original preservado em `.antes-restauro/`.
4. **Códigos de erro** (`[NOMOS-Exx]`) nos caminhos de erro principais da CLI
   + `docs/ERROS.md` com causa e correção.
5. **Motor sem compilador**: `instalar_motor` usa `--prefer-binary` e, ao
   falhar, mensagem honesta sobre compilador + link da doc.

## Fora de escopo
Construir/anexar wheels próprias de llama-cpp-python à release (infra pesada
de build; fica para quando houver runners dedicados). Streaming/RAG (v1.1).

## Arquivos que poderei alterar
`src/nomos/cli.py`, `src/nomos/simple/doutor.py` (aditivo),
`src/nomos/simple/erros.py` (novo), `src/nomos/simple/backup_total.py` (novo),
`src/nomos/cognition/embutido.py` (só instalar_motor), `pyproject.toml`/
`__init__.py` (1.0.0rc2), `README/CHANGELOG/docs/ERROS.md/INSTALL.md`,
`tests/test_v101.py` (novo), `.github/workflows/ci.yml` (teste de import leve
já entra pela suíte).

## Arquivos proibidos
Kernel (`kernel/*`, `runtime/*`, `ext/signing.py`, `ext/skills.py`); testes
existentes (somente adições).

## Critérios de aceite
| # | Critério | Verificação |
|---|---|---|
| 1 | `import nomos.cli` não carrega cryptography/argon2/cognition | teste com sys.modules em subprocesso |
| 2 | `nomos --version` < 1 s (folga p/ CI; local ~<150 ms) | teste subprocess + medição manual |
| 3 | consertar: corrompidos viram padrão seguro; sem TTY nega; nada destrutivo | testes com arquivos sabotados |
| 4 | backup roundtrip completo; senha errada nada restaura; home não-vazio protegido | testes |
| 5 | caminhos de erro principais com [NOMOS-Exx]; docs/ERROS.md cobre todos os códigos | teste varre códigos usados × documentados |
| 6 | instalar_motor chama pip com --prefer-binary | teste com subprocess capturado |
| 7 | suíte 100% + ruff + compat total | pytest/ruff |

## Riscos
Reordenar imports da CLI pode quebrar comando com NameError — mitigado pela
suíte (que exercita todos os comandos) + smoke manual dos principais.

## Rollback
Git (1 commit por missão); backup do usuário não é tocado por padrão.
