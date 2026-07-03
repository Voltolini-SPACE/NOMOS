# Skills do NOMOS

Skills são habilidades extras que você instala no seu agente. Cada skill
declara o que precisa fazer — e **só faz o que declarou**, sempre passando
pelos gates de aprovação do NOMOS.

## Conceitos

- **Instalada** — está na sua máquina (`~/.nomos/skills`);
- **Disponível** — consta no catálogo local, mas ainda não foi instalada;
- **Confiável** — assinada (ed25519) por publicador presente no seu trust store;
- **Experimental** — não assinada ou de risco alto: exige confirmação extra
  (digitar `ACEITO O RISCO`), além da aprovação normal;
- **Ativa/Inativa** — você pode desativar sem desinstalar;
- **Quebrada** — manifesto inválido, arquivo faltando ou checksum divergente:
  não roda até ser reinstalada.

## Comandos amigáveis

```bash
nomos skills                  # menu (em terminal) ou lista
nomos skills menu             # menu guiado
nomos skills listar           # instaladas + disponíveis no catálogo
nomos skills instalar <pasta> # instala com validação + aprovação
nomos skills remover <nome>
nomos skills info <nome>      # permissões, risco, publicador, último uso
nomos skills ativar <nome> / desativar <nome>
nomos skills rodar <nome>     # executa de forma governada (sandbox)
nomos skills diagnostico      # segurança: quebradas, não assinadas, risco alto
```

Os comandos técnicos continuam existindo e idênticos: `nomos skill install|
list|remove|sign|keygen|trust add|trust revoke`.

## Manifesto (skill.json)

```json
{
  "name": "minha-skill",
  "version": "1.0.0",
  "description": "o que ela faz, em uma frase",
  "entrypoint": "main.py",
  "permissions": ["A0_READ_LOCAL", "A1_WRITE_LOCAL"],
  "risk_level": "medio",
  "requires_approval": true,
  "publisher": "voce@exemplo.com",
  "compatible_nomos_version": ">=0.11",
  "modalities": ["texto", "arquivo"],
  "local_only_capable": true,
  "cloud_required": false,
  "files": {"main.py": "<sha256 do arquivo>"}
}
```

Campos v1 (`name`, `version`, `permissions`, `entry`, `files`) continuam
aceitos; os campos novos têm padrões seguros. `risk_level` é **calculado**
das permissões quando ausente — e o manifesto não consegue "se declarar"
menos arriscado do que as permissões indicam: quem manda é o cálculo.

### Risco

- **baixo** — só leitura local (A0);
- **médio** — escrita local, dispositivos (A1/A4);
- **alto** — rede, credenciais, execução de código, destrutivo (A2/A3/A5/A6)
  ou qualquer permissão desconhecida.

## O que uma skill nunca consegue fazer

- instalar sem manifesto válido, sem checksum conferido ou sem sua aprovação;
- executar permissão que não declarou (a execução governada concede somente o
  que está no manifesto — e cada categoria passa pelo gate);
- acessar a internet com o modo só-local ligado (o gate A2 é negado pela
  própria política);
- rodar com risco alto sem aprovação humana explícita;
- ser aprovada automaticamente em CI/terminal não interativo (fail-closed).

## Catálogo local (registry)

O arquivo `~/.nomos/registry/catalogo.json` lista skills **disponíveis** —
um catálogo local, sem rede. Ferramentas e times podem distribuir catálogos;
instalar continua exigindo os mesmos gates de sempre.
