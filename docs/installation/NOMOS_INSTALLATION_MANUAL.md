# 📦 Manual de Instalação do NOMOS

**Versão:** 1.3.0rc16  
**Data:** 2026-07-05  
**Status:** Validado para MC25  

---

## Índice

1. [Pré-requisitos](#pré-requisitos)
2. [Instalação Rápida](#instalação-rápida)
3. [Instalação para Desenvolvimento](#instalação-para-desenvolvimento)
4. [Primeira Execução Segura](#primeira-execução-segura)
5. [Solução de Problemas](#solução-de-problemas)
6. [Desinstalação e Limpeza](#desinstalação-e-limpeza)
7. [Segurança](#segurança)
8. [Suporte e Contato](#suporte-e-contato)

---

## Pré-requisitos

Antes de instalar NOMOS, certifique-se de que você tem:

### Sistema Operacional
- ✅ **macOS** (Intel ou Apple Silicon, 10.14+)
- ✅ **Windows** (7 SP1 ou mais recente, PowerShell 5.0+)
- ✅ **Linux** (Ubuntu 18.04+, Debian 10+, Fedora 30+, ou equivalente)

### Python
- **Versão mínima:** Python 3.10 ou mais novo
- **Verificar versão:** `python3 --version` ou `python --version`
- Se não tiver: https://www.python.org/downloads/

### Git (Opcional, para instalação do código)
- Necessário apenas se clonar o repositório
- **Verificar:** `git --version`
- Se não tiver: https://git-scm.com/downloads

### Espaço em Disco
- **Mínimo:** ~500 MB (código + dependências base)
- **Com cérebro leve:** ~1 GB (+ modelo IA ~400 MB)
- **Recomendado:** 2 GB livres

### RAM Mínima
- **Mínimo:** 2 GB (consegue rodar)
- **Confortável:** 4 GB+ (sem travamentos)

### Requisitos Opcionais
- **GPU:** Não necessária (NOMOS roda em CPU)
- **Ollama:** Não necessário (cérebro leve embutido)
- **Docker:** Não necessário (roda nativamente)

---

## Instalação Rápida

Para começar em **menos de 2 minutos**, escolha uma das opções:

### Opção 1: Pip (Recomendado para Usuários)

```bash
# Instalar do PyPI
pip install nomos

# Executar (primeira vez: assistente guiado)
nomos
```

**O que acontece:**
1. `pip install` baixa e instala o pacote
2. `nomos` abre o assistente na primeira execução
3. Você configura nome, personalidade e cérebro

### Opção 2: Instalador de 1 Clique (Recomendado para Não-Devs)

1. Vá para [Releases do NOMOS](https://github.com/Voltolini-SPACE/NOMOS/releases)
2. Baixe na MESMA pasta:
   - Instalador do seu sistema (`install.sh` para Mac/Linux, `install.ps1` para Windows)
   - Arquivo `nomos-<versão>-py3-none-any.whl`
   - Arquivo `SHA256SUMS`

**Mac/Linux:**
```bash
cd ~/Downloads  # ou pasta onde baixou
bash install.sh
```

**Windows (PowerShell):**
```powershell
cd $env:USERPROFILE\Downloads  # ou pasta onde baixou
powershell -ExecutionPolicy Bypass -File install.ps1
```

**O instalador:**
- ✅ Confere integridade (SHA256SUMS — aborta se divergir)
- ✅ Verifica Python 3.10+
- ✅ Faz backup da instalação anterior
- ✅ Instala em ambiente isolado (`~/.nomos/venv`)
- ✅ Roda smoke test de verificação
- ✅ Seus dados em `~/.nomos` **nunca** são tocados

**Desinstalação:** Use `uninstall.sh` ou `uninstall.ps1` (mesmo local)

### Opção 3: Instalação do Código (Para Desenvolvedores)

```bash
# Clonar repositório
git clone https://github.com/Voltolini-SPACE/NOMOS
cd NOMOS/nomos

# Instalar
pip install .

# Executar
nomos
```

---

## Instalação para Desenvolvimento

Se você quer **contribuir** ou **modificar** NOMOS:

### 1. Clonar Repositório

```bash
git clone https://github.com/Voltolini-SPACE/NOMOS
cd NOMOS/nomos
```

### 2. Criar Ambiente Virtual (Recomendado)

```bash
# Criar venv
python3 -m venv venv

# Ativar
# Mac/Linux:
source venv/bin/activate

# Windows:
venv\Scripts\activate
```

### 3. Instalar Dependências de Desenvolvimento

```bash
# Instalar com dev extras (pytest, ruff, build)
pip install -e ".[dev]"
```

### 4. Rodar Testes Localmente

```bash
# Suíte completa
python -m pytest

# Com relatório de cobertura
python -m pytest --cov=src/nomos --cov-report=html

# Teste rápido (1º arquivo)
python -m pytest tests/ -x -v
```

### 5. Rodar Lint (Verificação de Código)

```bash
# Verificar estilo (ruff)
python -m ruff check src tests

# Corrigir automaticamente (se possível)
python -m ruff check --fix src tests
```

### 6. Build Local (Criar Distribuição)

```bash
# Construir wheel e sdist
python -m build

# Saída em dist/
ls dist/
```

### 7. Instalar Localmente (Editable Mode)

```bash
# Instalar código em desenvolvimento
pip install -e .

# Agora qualquer mudança em src/ é refletida
nomos
```

### 8. Criar Pull Request

Quando pronto para contribuir:

```bash
# Criar branch
git checkout -b feature/sua-feature

# Fazer commits
git add .
git commit -m "Descrição clara da mudança"

# Push
git push origin feature/sua-feature

# Ir para GitHub e abrir PR
```

---

## Primeira Execução Segura

### Passo 1: Verificar Instalação

```bash
# Confirmar que instalou corretamente
nomos doutor
```

Você deve ver:
- ✅ Python 3.10+
- ✅ Caminho de instalação
- ✅ Dados em `~/.nomos`
- ✅ Próximos passos

### Passo 2: Rodar Assistente Guiado

```bash
nomos
```

Primeira execução é automática assistente que:
1. Pede seu nome (nome do agente)
2. Pede tom/personalidade (formal, casual, técnico)
3. Oferece cores personalizadas (opcional)
4. Cria estrutura local em `~/.nomos`

### Passo 3: Verificar Estrutura Local

```bash
# Ver o que criou
ls -la ~/.nomos/

# Deve ter:
# - config/      (configuração)
# - memory/      (memórias)
# - vault/       (chaves, secrets)
# - audit/       (log de auditoria)
# - skills/      (habilidades instaladas)
```

### Passo 4: Fazer Teste Seguro (Dry-run)

```bash
# Testar sem executar nada real
nomos --dry-run "listar arquivos da pasta atual"
```

Você verá:
- Que agente faria se tivesse permissão
- Mas NÃO executa de verdade
- Você aprova antes de qualquer ação real

### Passo 5: Modo Menu Principal

```bash
# Menu interativo
nomos
```

Opções:
- 🎯 Executar comando
- 📚 Consultar docs
- 🧠 Baixar cérebro
- ⚙️ Configurar
- 🛠️ Manutenção

---

## Solução de Problemas

### "Python 3.10 não encontrado"

**Problema:** `nomos: command not found` ou versão errada de Python

**Solução:**
```bash
# Verificar versão
python3 --version

# Se < 3.10, baixar: https://www.python.org/downloads/

# Instalar com versão explícita
python3.10 -m pip install nomos

# Ou com alias
python3 -m pip install nomos
```

### "Permissão negada" em macOS/Linux

**Problema:** `PermissionError` ao tentar instalar ou acessar `~/.nomos`

**Solução:**
```bash
# Usar --user flag
pip install --user nomos

# Ou corrigir permissões
chmod 755 ~/.nomos
```

### "Módulo não encontrado"

**Problema:** `ModuleNotFoundError: No module named 'nomos'`

**Solução:**
```bash
# Reinstalar
pip uninstall nomos -y && pip install nomos

# Ou ativar venv se estiver usando
source venv/bin/activate  # Mac/Linux
venv\Scripts\activate     # Windows
```

### "Cérebro não baixado"

**Problema:** Agente avisa que cérebro não está disponível

**Solução:**
```bash
# Baixar cérebro leve (uma vez, ~400 MB)
nomos cerebro baixar

# Pede sua aprovação (internet requerida, uma vez)
```

### "Build com erro de symlink"

**Problema:** `RecursionError` ao tentar fazer `python -m build`

**Solução (Usuários):** Ignore — você não precisa fazer build  
**Solução (Devs):**
```bash
# Limpar build cache
rm -rf build/ dist/ *.egg-info .pytest_cache

# Tentar novamente
python -m build
```

### "Atualização falhou"

**Problema:** `nomos atualizar` trava ou falha

**Solução:**
```bash
# Verificar manualmente
pip install --upgrade nomos

# Ou desinstalar + reinstalar
pip uninstall nomos -y
pip install nomos
```

### "Dados perdidos após crash"

**Problema:** Memória ou configuração parece apagada

**Solução:**
```bash
# NOMOS nunca deleta dados; procure backup
ls -la ~/.nomos/backup/

# Se tiver backup
cp ~/.nomos/backup/memory_backup.json ~/.nomos/memory/

# Se sem backup, reconfigurar é necessário
nomos resetar-config  # (se existir) ou reinstalar
```

### "Sem internet, mas quer usar"

**Problema:** Quer usar NOMOS sem nenhuma conexão internet

**Solução:**
```bash
# Compatível! Mas:
# 1. Cérebro leve já deve estar baixado (nomos cerebro baixar)
# 2. Skills que precisam internet vão falhar
# 3. Usar --offline flag (se existir)

nomos --offline "sua tarefa local"
```

---

## Desinstalação e Limpeza

### Remover apenas a Aplicação

```bash
pip uninstall nomos -y
```

Deixa intactos: `~/.nomos` (dados, memória, vault, chaves)

### Remover Tudo (Aplicação + Dados Locais)

**⚠️ AVISO: Isso deleta TUDO — memória, chaves, vault, configuração. Irreversível!**

```bash
# Mac/Linux
pip uninstall nomos -y && rm -rf ~/.nomos

# Windows
pip uninstall nomos -y
rmdir /s "%USERPROFILE%\.nomos"
```

### Usar Instalador para Desinstalar

Se instalou com `install.sh` ou `install.ps1`:

**Mac/Linux:**
```bash
bash uninstall.sh
```

**Windows:**
```powershell
powershell -ExecutionPolicy Bypass -File uninstall.ps1
```

Pede confirmação antes de deletar.

### Limpar Cache e Temporários

```bash
# Sem remover dados
rm -rf ~/.nomos/cache/
rm -rf ~/.nomos/temp/

# Cache de pip
pip cache purge
```

---

## Segurança

### O que NÃO faça

❌ **Nunca:**
- Cole secrets em linhas de comando visíveis (use `--secret-from-file`)
- Compartilhe seu `~/.nomos/vault/` diretório
- Rode NOMOS com `sudo` sem motivo muito forte
- Instale skills de fonte desconhecida

### Dados Sensíveis

- **Vault:** Arquivo `~/.nomos/vault/secrets.enc` é criptografado (chave em memória)
- **Memória:** Arquivo `~/.nomos/memory/` contém histórico (sem dados sensíveis por padrão)
- **Audit:** Log `~/.nomos/audit/` rastreia TUDO que fez (retenção: 90 dias)
- **Backup:** Automático em `~/.nomos/backup/` (mantém 3 gerações)

### Aprovação Humana por Padrão

- Toda ação sensível pede seu OK
- Em scripts/CI, padrão é **não fazer nada** (fail-closed)
- Dry-run mostra exatamente o que faria
- `--no-confirm` só existe com flag de risco explícita

### Executar com Segurança

```bash
# Sempre com dry-run primeiro
nomos --dry-run "seu comando"

# Depois com confirmação
nomos "seu comando"

# Em scripts, sempre approve explicitamente
nomos --yes "seu comando"  # Use quando confiar
```

### Comunicação de Segurança

Se descobrir **vulnerabilidade ou risco de segurança:**

1. **Não** abra issue pública
2. Envie email para `security@se7enpay.com.br`
3. Inclua:
   - Descrição do risco
   - Como reproduzir (sem executar)
   - Seu nome/contato
4. Aguarde confirmação (48h máximo)

---

## Suporte e Contato

### Documentação Oficial

- 📖 [README.md](../../README.md) — Visão geral
- 🏗️ [docs/](../) — Toda documentação técnica
- 📋 [Brandbook](../brand/NOMOS_BRANDBOOK.md) — Identidade e mensagens
- 🔐 [PRIVACIDADE.md](../PRIVACIDADE.md) — Política de privacidade
- 🎯 [THREAT_MODEL.md](../THREAT_MODEL.md) — Modelo de ameaças

### Comunidade

- 💬 **GitHub Issues:** Reportar bugs → https://github.com/Voltolini-SPACE/NOMOS/issues
- 💡 **GitHub Discussions:** Sugerir features → https://github.com/Voltolini-SPACE/NOMOS/discussions
- 🔗 **GitHub:** Source + releases → https://github.com/Voltolini-SPACE/NOMOS

### Verificação de Integridade (SHA256)

Para verificar que download não foi corrompido:

```bash
# Mac/Linux
sha256sum nomos-1.3.0rc16-py3-none-any.whl > computed.txt
cat SHA256SUMS | grep "nomos-1.3.0rc16" >> expected.txt
diff computed.txt expected.txt  # Deve ser vazio

# Windows
certUtil -hashfile nomos-1.3.0rc16-py3-none-any.whl SHA256
# Compare com SHA256SUMS
```

---

## Versioning e Atualizações

### Verificar Versão Instalada

```bash
nomos --version
```

### Atualizar para Versão Nova

```bash
# Automático (com aprovação)
nomos atualizar

# Ou manual
pip install --upgrade nomos
```

**O que atualizar preserva:**
- ✅ Configuração pessoal (nome, cores)
- ✅ Memória (histórico)
- ✅ Vault (chaves e secrets)
- ✅ Skills instaladas
- ✅ Audit log

**O que atualizar NÃO toca:**
- Nenhum dados `~/.nomos` é deletado
- Rollback sempre possível com `rollback.sh`

---

## Resumo Rápido (Cheat Sheet)

```bash
# Instalar (mais simples)
pip install nomos
nomos

# Instalar (dev)
git clone https://github.com/Voltolini-SPACE/NOMOS && cd NOMOS/nomos
pip install -e ".[dev]"
python -m pytest

# Usar seguro
nomos --dry-run "seu comando"
nomos "seu comando"

# Verificar
nomos doutor
nomos --version

# Desinstalar
pip uninstall nomos -y

# Desinstalar tudo
pip uninstall nomos -y && rm -rf ~/.nomos
```

---

**Fim do Manual de Instalação. Para mais, veja [docs/](../) ou [GitHub](https://github.com/Voltolini-SPACE/NOMOS).**

