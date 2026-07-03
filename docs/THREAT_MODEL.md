# NOMOS — Modelo de Ameaças (v1.0-rc1)

Formato: ameaça → mitigação (mecanismo) → **prova** (teste automatizado que
falha se a mitigação regredir). O que não tem teste, não é considerado
mitigado — está listado como residual.

## Ativos protegidos

Chaves/segredos do usuário (cofre), memórias/conversas, arquivos locais,
trilha de auditoria, a própria política, e a promessa central: **nada sai da
máquina sem opt-in explícito**.

## Ameaças e mitigações

### S — Spoofing (falsidade de identidade/origem)
| Ameaça | Mitigação | Prova |
|---|---|---|
| Skill se passando por publicador confiável | assinatura ed25519 + trust store + pin TOFU (troca de publicador ⇒ recusa) | `test_skill_signing.py` |
| Catálogo de skills forjado/adulterado | catálogo assinado; assinatura inválida descarta TUDO | `test_skill_sdk_v015.py::test_catalogo_adulterado_descartado_inteiro` |
| Página falsa do painel | URL com segmento secreto aleatório; sem ele 404 | `test_panel.py`, `test_painel_v017.py` |

### T — Tampering (adulteração)
| Ameaça | Mitigação | Prova |
|---|---|---|
| Alterar trilha de auditoria | cadeia de hash; `verify()` aponta a linha | `test_audit_consent.py`, `test_doutor_v011.py::test_auditoria_violada_bloqueia` |
| Trocar arquivos de uma skill instalada | checksum SHA-256 por arquivo; divergência ⇒ "quebrada", não roda | `test_sandbox_skills.py`, `test_skills_menu.py::test_quebrada_*` |
| Adulterar backup de memórias | Fernet (HMAC) ⇒ token inválido, nada importado | `test_memoria_v014.py::test_arquivo_adulterado_recusado` |
| Corromper política/localidade/rotinas | fail-closed: política ilegível nega tudo; localidade corrompida ⇒ LIGADO; rotinas corrompidas ⇒ nada roda | `test_policy.py`, `test_local_first_regression.py`, `test_rotinas_v016.py` |

### R — Repudiation (negação de ações)
| Ameaça | Mitigação | Prova |
|---|---|---|
| "Não fui eu que aprovei" | toda decisão sensível auditada com categoria/alvo/efeito | `test_audit_consent.py`, eventos em todos os fluxos novos |

### I — Information disclosure (vazamento)
| Ameaça | Mitigação | Prova |
|---|---|---|
| Segredo em log/stdout | redação por nome de campo E padrão de valor; pipeline/skill auditam só metadados | `test_no_secret_leak_regression.py` (6 cenários) |
| Egress escondido no código | teste estático: allowlist justificada de hosts | `test_egress_zero.py` |
| Dados sensíveis para a nuvem | classificador veta nuvem p/ dado sensível mesmo com cadeado aberto | `test_engine_router_auto.py::test_dados_sensiveis_nunca_vao_para_nuvem` |
| Painel exposto na rede | bind exclusivo 127.0.0.1 (outro host ⇒ exceção) | `test_painel_v017.py::test_bind_fora_do_loopback_recusado` |
| Skill lê além do declarado | sandbox sem env do host; permissões só as declaradas, cada uma no gate | `test_sandbox_skills.py::test_ambiente_nao_herda_segredos`, `test_skill_registry.py` |
| Backup legível sem senha | PBKDF2 600k + Fernet; senha curta recusada | `test_memoria_v014.py` |

### D — Denial of service (indisponibilidade)
| Ameaça | Mitigação | Prova |
|---|---|---|
| Skill trava o sistema | timeout com kill de grupo de processos; limites de recursos | `test_sandbox_skills.py::test_timeout_mata_processo` |
| Arquivo gigante engole memória | limite 5 MB (arquivos) / 20 MB (imagens) com erro claro | `test_arquivos.py`, `test_cognicao_v018.py` |
| Painel derruba o agente | handler captura exceção ⇒ 500 sem detalhes | `test_painel_v017.py::test_painel_nunca_derruba_*` |

### E — Elevation of privilege (escalada)
| Ameaça | Mitigação | Prova |
|---|---|---|
| Bypass de aprovação em CI/script | gate sem TTY nega; sem flag de bypass POR PROJETO | `test_cli.py`, `test_cloud_opt_in_regression.py` |
| Rotina executando ação sensível sozinha | rotinas rodam com approver=None ⇒ só A0 passa | `test_rotinas_v016.py::test_skill_sensivel_nao_roda_em_rotina` |
| Manifesto "se declarando" seguro | risco calculado das permissões; declaração não afrouxa | `test_skill_registry.py::test_manifesto_nao_afrouxa_aprovacao` |
| Roteador escolhendo nuvem com cadeado | invariante + DENY na política antes do gate | `test_local_first_regression.py` (assert de invariante em `engine_router`) |
| Aprovador com erro autoriza | exceção no approver ⇒ nega | `test_engine_pipeline.py::test_nada_pula_aprovacao_nem_com_erro_no_aprovador` |

## Riscos residuais (declarados, não mascarados)

1. **Host comprometido**: se o SO/usuário local já está comprometido (malware
   com os mesmos privilégios), o NOMOS não se defende — os arquivos 0600 e o
   cofre cifrado limitam, mas não eliminam. Fora do modelo.
2. **Isolamento de sandbox no Mac/Windows**: sem namespaces, execução com
   rede proibida é RECUSADA (fail-closed) — funcionalidade reduzida, não
   segurança reduzida. Prova: `test_rede_negada_por_padrao_ou_recusa_fail_closed`.
3. **Semântica local é aproximada** (hashing de n-gramas): resultado de busca
   pode errar — impacto é de qualidade, nunca de privacidade.
4. **Dependências de terceiros** (cryptography, argon2-cffi, pypdf opcional):
   supply chain mitigada por lockless-minimal (2 deps obrigatórias) — revisão
   externa recomendada antes do 1.0.0 final.

## Cobertura de testes (medida em 2026-07-03)

Kernel: policy 100% · localidade 100% · vault 97% · approvals 97% · config
98% · consent 94% · audit 93% · plataforma 92% (**meta ≥90% atingida**).
Geral: **83%** (meta ≥80% atingida). Suíte: 410 testes.

## Pendências para o 1.0.0 final (fora do alcance do código)

Auditoria de segurança independente do kernel; CI verde nos 3 SOs no GitHub
(pós-push); release pública com artefatos assinados; publicação Homebrew/winget
(templates prontos em `packaging/`).
