# Instalar o NOMOS

## O que você precisa

- **Python 3.10 ou mais novo** (verifique com `python3 --version`)
- Mac, Windows ou Linux — não precisa de GPU nem de PC potente

## Instalação a partir do código (estado atual do projeto)

```bash
git clone https://github.com/Voltolini-SPACE/NOMOS
cd NOMOS/nomos
pip install .
nomos            # abre o assistente na primeira vez
```

Para desenvolver:

```bash
pip install -e .
python -m pytest -q      # suíte de testes
ruff check src tests     # lint
```

## Instalação por wheel (quando houver release publicada)

Se você baixou um arquivo `nomos-<versão>-py3-none-any.whl` de uma release:

```bash
pip install nomos-0.11.0-py3-none-any.whl
nomos
```

> **Nota de maturidade**: o NOMOS está em desenvolvimento ativo. Enquanto uma
> release com instaladores de um clique não estiver publicada na página de
> releases do GitHub, o caminho suportado é a instalação a partir do código,
> acima. Os scripts em `installer/` são a base desses instaladores.

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
