# NOMOS v1.2.0rc2 — Security Audited

## Status

STATUS_FINAL=RC2_SECURITY_AUDITED_WITH_KNOWN_GAPS

## Base

A tag `v1.2.0rc1-delivery-ready` foi validada anteriormente, mas a auditoria
independente encontrou uma falha real de segurança em skills. Portanto, a
release pública deve usar esta nova tag pós-auditoria
(`v1.2.0rc2-security-audited`), que aponta para o commit com o fix e CI verde.
A tag antiga **não é movida nem apagada** — permanece como registro histórico.

## Correção de segurança

Foi corrigida uma falha em manifests de skills onde `entry` absoluto ou inseguro
podia apontar para arquivo externo fora do diretório da skill e fora do conjunto
de arquivos checksummados. Prova empírica na auditoria: instalar com
`entry="/tmp/evil"` tinha sucesso e, na execução, `dest / entry` escaparia para
o arquivo externo — código sem verificação de integridade. Correção no commit
`201e536`.

### Mitigação aplicada

- caminhos absolutos recusados
- `..` recusado
- drive path Windows recusado
- `entry` deve estar em `files`
- `entry` deve ser coberto por checksum
- defesa em profundidade na execução (`entry` resolvido tem de ficar dentro do
  diretório da skill, mesmo se o `skill.json` instalado for editado depois)

## Testes

- Total: 503
- Segurança nova: 9 testes (3 de path traversal/entry, vermelhos antes do fix)
- CI: PASS nos 3 sistemas operacionais (Linux, macOS, Windows)
- Smoke pós-install: PASS
- Cobertura: 84% geral (vault 97%, policy/localidade 100%, approvals 97%)

## Riscos residuais

### Audit log tail truncation

A hash-chain detecta modificação, reordenação e remoção do meio, mas não detecta
remoção das últimas linhas. Como a cadeia atual é sem chave, um atacante com
escrita poderia reescrever a cadeia.

Mitigação futura recomendada:

- HMAC da cadeia usando chave do cofre
- checkpoint assinado
- contador monotônico quando disponível
- export/verificação com âncora externa opcional

## Não escopo

Não foram implementados:

- Conselho de Motores
- PyPI
- painel read-write
- Obsidian
- novas features

## Recomendação

Usar esta tag (`v1.2.0rc2-security-audited`) como base para GitHub Release
técnico.
