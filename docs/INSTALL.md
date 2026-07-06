# Instalar o NOMOS

## O que você precisa

- **Python 3.10 ou mais novo** (verifique com `python3 --version`)
- Mac, Windows ou Linux — não precisa de GPU nem de PC potente

## Instalação a partir do código (estado atual do projeto)

```bash
git clone https://github.com/Voltolini-SPACE/NOMOS
cd NOMOS
pip install .
nomos            # abre o assistente na primeira vez
```

Para desenvolver:

```bash
pip install -e .
python -m pytest -q      # suíte de testes
ruff check src tests     # lint
```

## Instalação pela release (recomendado para quem não é dev)

Na página de releases (https://github.com/Voltolini-SPACE/NOMOS/releases),
baixe para a MESMA pasta: o instalador do seu sistema, o arquivo
`nomos-<versão>-py3-none-any.whl` e o `SHA256SUMS`.

**Mac/Linux:**
```bash
bash install.sh
```

**Windows (PowerShell):**
```powershell
powershell -ExecutionPolicy Bypass -File install.ps1
```

O instalador confere a integridade (SHA256SUMS — aborta se divergir), exige
Python 3.10+, faz backup da instalação anterior (com `rollback.sh` para
voltar), instala num ambiente isolado e roda um smoke final. Seus dados em
`~/.nomos` nunca são tocados; `uninstall.sh --purge` é o único caminho que os
remove, e só com confirmação digitada.

Ou, se preferir só o pip:
```bash
pip install nomos-<versão>-py3-none-any.whl  # use o arquivo baixado da release
nomos
```

## Atualizar

```bash
nomos atualizar
```

Checa (com a sua aprovação — é uma saída à internet) se existe versão nova e
mostra o caminho manual. O NOMOS **nunca se atualiza sozinho**: baixar e rodar
o instalador é sempre uma ação sua. Atualizar preserva memórias, chaves e
configurações.

## Primeiros passos depois de instalar

```bash
nomos            # 1ª vez: onboarding guiado; depois: menu principal
nomos doutor     # check-up honesto: o que está pronto e o próximo passo
nomos cerebro baixar   # baixa o cérebro leve (uma vez; pede sua aprovação)
```

## Onde ficam meus dados?

Tudo em `~/.nomos` (ou no caminho da variável `NOMOS_HOME`): perfil, memórias,
cofre de chaves, política, auditoria e skills. Nada disso sai da sua máquina —
veja [PRIVACIDADE.md](PRIVACIDADE.md).

## Desinstalar

```bash
pip uninstall nomos
rm -rf ~/.nomos    # opcional: apaga também seus dados locais
```
