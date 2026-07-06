# Códigos de erro do NOMOS

Toda falha importante vem com um código `[NOMOS-Exx]`. Procure o seu aqui —
cada um tem causa e correção. Os textos das mensagens continuam em português
claro; o código é só um endereço fixo para esta página.

## NOMOS-E001 — cofre
**Causa**: passphrase ausente/incorreta, ou o cofre ainda não existe.
**Correção**: crie com `nomos vault init`; para automação, use a variável
`NOMOS_PASSPHRASE` (uso restrito). Esqueceu a passphrase? Não há recuperação —
por projeto, o cofre é ilegível sem ela.

## NOMOS-E002 — ação negada (fail-closed)
**Causa**: você não está num terminal interativo, a aprovação não foi dada,
ou a política/cadeado só-local nega a ação. **Isto é proteção, não defeito.**
**Correção**: rode num terminal de verdade e aprove quando o NOMOS perguntar;
para egress, veja `nomos local status`. Em scripts/CI, ações sensíveis são
sempre negadas — não existe flag de bypass.

## NOMOS-E003 — arquivo
**Causa**: caminho não existe, arquivo maior que o limite (5 MB texto/20 MB
imagem) ou formato não suportado.
**Correção**: confira o caminho; formatos aceitos em `nomos arquivo --help`;
PDF exige o extra `pip install 'nomos[arquivos]'`.

## NOMOS-E004 — skill recusada
**Causa**: manifesto inválido, checksum divergente, assinatura não confiável
ou confirmação experimental ausente.
**Correção**: `nomos skills diagnostico` mostra o defeito exato; reinstale a
skill de uma fonte íntegra; skills experimentais exigem digitar
`ACEITO O RISCO` em terminal interativo.

## NOMOS-E005 — backup
**Causa**: senha incorreta, arquivo adulterado, malformado, ou o destino já
existe.
**Correção**: senha certa = restaura; nunca sobrescrevemos backup existente —
escolha outro nome. Arquivo adulterado é recusado inteiro (integridade HMAC).

## NOMOS-E006 — rotina
**Causa**: hora fora do formato HH:MM, ação desconhecida, skill não instalada
ou criação não aprovada.
**Correção**: `nomos rotinas criar "Nome" 08:00 briefing`; ações válidas:
briefing, doutor, consolidar-memoria, skill:<nome>. Criar exige aprovação em
terminal interativo.

## NOMOS-E007 — motor indisponível
**Causa**: o motor pedido não está instalado ou não respondeu.
**Correção**: `nomos motores diagnostico` mostra o que falta;
`nomos cerebro baixar` resolve texto/resumo; `nomos doutor` dá o próximo passo.

## NOMOS-E008 — atualização
**Causa**: sem internet, GitHub indisponível ou resposta inválida.
**Correção**: tente mais tarde ou veja manualmente
https://github.com/Voltolini-SPACE/NOMOS/releases. O NOMOS nunca se atualiza
sozinho.

## NOMOS-E009 — conserto não aplicado
**Causa**: `doutor --consertar` fora de terminal interativo, ou você não
digitou a confirmação.
**Correção**: rode num terminal e digite `CONSERTAR` quando pedido. A lista
do que seria consertado aparece mesmo sem TTY — nada é alterado sem seu sim.

## NOMOS-E010 — argumentos inválidos
**Causa**: JSON malformado em `--args`, opção desconhecida ou modalidade
inexistente.
**Correção**: valide o JSON (aspas duplas!); `--help` do comando lista as
opções aceitas.

## NOMOS-E011 — evidência não verificada
**Causa**: pacote adulterado (hash divergente), destino já existente na
criação, ou anexo inexistente.
**Correção**: `nomos evidencia listar` mostra o estado de cada pacote;
recrie o pacote se ele foi alterado — a violação é o aviso funcionando.

## NOMOS-E012 — nuvem não plugada (proteção)
**Causa**: opt-in de nuvem negado — cadeado só-local ligado, aprovação A2/A3
ausente, senha do cofre não fornecida ou execução sem terminal interativo.
**Correção**: é uma decisão humana: rode num terminal, destrave com
`nomos local off` (consciente), aprove quando o NOMOS perguntar e informe a
senha do cofre. Em scripts/CI a resposta é sempre "não" — por projeto.
