# SECURITY AUDIT — NOMOS Kernel v1.2.0rc1

Auditoria independente do kernel sobre a tag `v1.2.0rc1-delivery-ready`
(baseline HEAD 37157c9). Uma falha explorável foi encontrada, **provada com
teste** e **corrigida** durante a auditoria (commit 201e536). O restante são
riscos residuais documentados, sem bloqueador aberto.

## 1. Status final

STATUS_FINAL=WARN_SECURITY_AUDIT_WITH_GAPS

O único achado explorável (path traversal / entry absoluto em skills) foi
corrigido nesta auditoria. Permanecem riscos residuais **não-bloqueadores**
(sobretudo o truncamento de cauda do audit log — limitação inerente de
hash-chain sem chave), descritos na seção 8.

## 2. Baseline

| Comando | Resultado |
|---|---|
| git status --short | CLEAN |
| git rev-parse HEAD | 37157c9 |
| git describe --tags | v1.2.0rc1-delivery-ready-1-g37157c9 |
| git fsck --full | PASS (sem corrupção) |
| ruff check | PASS |
| pytest | PASS (494 → **503** após os testes de segurança) |
| pytest --cov | 84% geral · vault 97% · policy/localidade 100% · approvals 97% · audit 93% |
| python -m build | PASS (wheel) |
| nomos doutor | PASS (rc=0) |
| python -m nomos doutor | PASS (rc=0) |
| nomos agentes listar | PASS (3 oficiais) |

## 3. Escopo auditado

vault · policy · audit · sandbox · approvals · locality · redaction ·
skills boundary · agent boundary · conversation privacy · cloud opt-in ·
panic · backup/export · logs verify.

## 4. Resultados por domínio

| Domínio | Status | Evidência | Gaps |
|---|---|---|---|
| vault | PASS | Fernet; Argon2id (PBKDF2 fallback); downgrade recusado fail-closed; lockout progressivo persistido; 0600; `names()` só nomes; segredo nunca em claro nem em erro | corrupção de JSON gera `JSONDecodeError` em vez de `VaultError` (cosmético; ainda fail-closed) |
| policy | PASS | default read-only (só A0 ALLOW); categoria desconhecida/política corrompida ⇒ DENY; A6 DESTRUCTIVE DENY; REQUIRE_APPROVAL sem aprovador ⇒ nega | — |
| audit | WARN | hash-chain detecta modificação, reordenação, remoção do MEIO e corrupção de JSON | **truncamento de cauda não detectado** (cadeia sem chave) — seção 8 |
| sandbox/skills | PASS (corrigido) | checksum por arquivo; assinatura ed25519; TOFU; gate; **path safety agora imposta** | era FAIL antes da correção (seção 6) |
| approvals | PASS | token single-use; TTL; `hmac.compare_digest`; expirada⇒negada; token nunca logado; limpo ao decidir; sem replay | — |
| locality | PASS | só-local LIGADO de fábrica; egress não-loopback ⇒ DENY antes do gate; ausência de arquivo ⇒ ligado | — |
| redaction | PASS | redige por nome de campo sensível + padrões (sk-, AKIA, gh*_, bearer, JWT); cobre stdout de skill | nomes de campo compostos sem padrão conhecido podem escapar (recomendação seção 8) |
| skills boundary | PASS (corrigido) | risco recalculado (não afrouxável pelo manifesto); experimental exige aceite; oferta não executa sem "sim"; injeção de arquivo não dispara skill | idem sandbox |
| agent boundary | PASS | allowlist fechada; mesmo `policy.gate`; sem herança entre agentes; A1 sem aprovação negado; auditoria por agente | — |
| conversation privacy | PASS | modo privado = SQLite `:memory:` (não toca disco, FS inspecionado); export exige senha; candidata não vira memória sem aprovação; esquecer/retention funcionam | — |
| cloud opt-in | PASS | nuvem exige DOIS gates (A2 egress + A3 credencial); cadeado bloqueia egress; chave só no header de auth, nunca no prompt; não-interativo ⇒ negado | — |
| panic | PASS | `panic()` revoga todos os consentimentos; `is_granted` fail-closed p/ desconhecido e expirado; auditado | — |
| backup/export | PASS | cifrado com senha (PBKDF2); vault permanece cifrado dentro do backup; export de conversas cifrado | — |
| logs verify | PASS* | `verify()` acha 1ª violação por modificação/reordenação | *mesma limitação de truncamento do audit |

## 5. Ataques simulados

| # | Ataque | Resultado | Teste | Observação |
|---|---|---|---|---|
| 1 | Prompt injection em arquivo | BLOQUEADO | test_prompt_injection | conteúdo envelopado como DADO |
| 2 | Skill com manifesto falso | BLOQUEADO | test_skill_registry/sandbox | campos/perm validados |
| 3 | Skill com checksum adulterado | BLOQUEADO | test_sandbox_skills | verify_files recusa |
| 4 | Troca de assinatura | BLOQUEADO | test_skill_signing | pin TOFU + trust store |
| 5 | Cloud com cadeado ligado | NEGADO | test_seguranca_auditoria::egress | DENY antes do gate |
| 6 | Aprovação em CI (sem TTY) | NEGADO | test_seguranca_auditoria::ci | gate sem aprovador ⇒ False |
| 7 | Ler segredo via /contexto | IMPOSSÍVEL | análise: cognição não importa vault; chave só no header | estrutural |
| 8 | Logar segredo | REDIGIDO | test_no_secret_leak / test_redaction_pipe | nome+padrão |
| 9 | Agente chamar skill sensível | GOVERNADO | test_v14_agentes | mesmo gate, sem herança |
| 10 | Rotina executar ação sensível | NEGADO | test_rotinas_v016 | A0-only; --simular sem efeito |
| 11 | Backup/export sem aprovação | PROTEGIDO | test_v13_historico (export cifrado) | senha obrigatória; vault cifrado |
| 12 | Symlink escape | MITIGADO | test_seguranca_auditoria | checksum-first + path safety |
| 13 | Path traversal | **CORRIGIDO** | test_seguranca_auditoria (3) | ver seção 6 |
| 14 | Reusar token/approval | NEGADO | test_approvals | single-use/TTL |
| 15 | Corromper audit log | DETECTADO* | test_seguranca_auditoria::audit | *exceto truncamento de cauda |
| 16 | Mutar trust store | RECUSA | test_skill_signing | corrompido ⇒ fail-closed |
| 17 | Injeção virar memória durável | NEGADO | test_v15_ux (candidatas) | candidata exige aprovação |
| 18 | Cloud via fallback | NEGADO | test_cloud_opt_in_regression | fallback não aciona nuvem |
| 19 | Skill acessar conversa privada | IMPOSSÍVEL | privada em `:memory:` nunca persiste | estrutural |
| 20 | Agente acessar memória privada | IMPOSSÍVEL | idem; `memoria_buscar` só lê store persistido | estrutural |

## 6. Falhas encontradas

| Falha | Severidade | Evidência | Correção |
|---|---|---|---|
| **Path traversal / entry absoluto em skills** | MÉDIA-ALTA | `load_manifest` não validava chaves de `files` nem `entry`. Prova empírica: instalar com `entry="/tmp/evil"` teve sucesso e, na execução, `dest / entry` escaparia para `/tmp/evil` (arquivo externo, **sem checksum**). `..` já era barrado por `verify_files`, mas sem guarda explícita. | commit 201e536: `_rel_segura()` recusa absoluto/`..`/drive; `entry` deve constar em `files` (checksummado); defesa em profundidade na execução (`entry.resolve()` tem de ficar dentro do diretório) |

## 7. Correções aplicadas

| Commit | Tipo | Descrição |
|---|---|---|
| 201e536 | fix(security) + test(security) | rejeita path traversal/entry absoluto em skills; 3 testes de ataque (vermelhos antes, verdes depois) + caracterização do audit; 503 testes; ruff limpo; build ok |

## 8. Riscos remanescentes

1. **Audit log — truncamento de cauda (BAIXA-MÉDIA).** A cadeia de hash é
   **sem chave**: remover as últimas N linhas mantém a cadeia interna válida e
   `verify()` não detecta. Remoção do meio, reordenação e modificação SÃO
   detectadas. Como a cadeia não usa segredo, um atacante com escrita no
   arquivo pode reescrevê-la por inteiro — limitação inerente a hash-chain
   local. Mitigação real exigiria MAC com chave protegida ou ancoragem externa
   (fora do escopo local-first mínimo). **Não** foi adicionado um "tip" sem
   chave por ser defesa-teatro (o atacante reescreveria os dois arquivos).
   Recomenda-se HMAC com chave derivada do cofre num próximo ciclo.
2. **Redação por nome de campo exato (BAIXA).** Um segredo logado sob um nome
   de campo incomum e sem padrão conhecido (ex.: `detalhe="hunter2"`) pode
   escapar. Os chamadores atuais logam apenas metadados. Recomendação:
   casamento por substring nos nomes de campo sensíveis (aceitando
   falso-positivo no log, que é o lado seguro).
3. **Vault: corrupção de JSON (COSMÉTICO).** Arquivo do cofre corrompido gera
   `JSONDecodeError` em vez de `VaultError`; ainda é fail-closed (aborta, não
   revela segredo). Recomenda-se envelopar em `VaultError` para mensagem clara.

Nenhum destes é bloqueador para release candidate.

## 9. Não escopo (explicitamente NÃO feito nesta missão)

- Conselho de Motores — não implementado.
- PyPI — não publicado.
- GitHub Release — não criado.
- Painel read-write — não iniciado.
- Integração Obsidian — não iniciada.
- Nenhuma feature nova; apenas auditoria + 1 correção de segurança + testes.

## 10. Recomendação

O único achado explorável foi corrigido e provado por teste durante esta
auditoria; os itens restantes são riscos residuais não-bloqueadores,
documentados acima. Recomendação: **release candidate final liberada com
divulgação dos riscos residuais** — o item mais relevante (truncamento de cauda
do audit) deve ser resolvido com um MAC com chave num ciclo posterior, mas não
bloqueia a RC.

Próximo passo recomendado: preparar o GitHub Release técnico da v1.2.0rc1
delivery-ready, divulgando na nota o risco residual do audit log (truncamento
de cauda) e o plano de mitigação por HMAC.
