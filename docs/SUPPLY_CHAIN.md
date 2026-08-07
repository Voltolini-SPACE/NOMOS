# Cadeia de suprimentos — contrato do NOMOS

Este documento é o contrato normativo da cadeia de publicação do NOMOS
depois da missão H4.9. Vale para toda release a partir de `v1.3.0rc19+1`
(a `v1.3.0rc19` publicada em `2026-08-04` ainda foi produzida sob o
contrato H4.8, com wheel reproducible mas sdist não-normalizado — ver §7).

## 1. Objetivo

Garantir que uma release publicada seja:

1. **Íntegra** — nenhum byte alterado entre CI e usuário final.
2. **Descritível** — o inventário de dependências é auditável e amarrado
   por hash aos artefatos.
3. **Verificável** — proveniência criptográfica prova qual workflow, em
   qual commit, produziu quais bytes.
4. **Reprodutível bit-a-bit** — outro engenheiro, com o mesmo commit e
   o mesmo toolchain pinado, produz o mesmo `.whl` e o mesmo `.tar.gz`.

## 2. As quatro garantias por artefato

| Camada          | Arquivo                                         | Prova                                                                     |
| --------------- | ----------------------------------------------- | ------------------------------------------------------------------------- |
| Integridade     | `SHA256SUMS`                                    | `sha256sum -c` / `shasum -a 256 -c`                                       |
| Descrição       | `sbom.cdx.json` (CycloneDX 1.5)                 | SBOM referencia wheel + sdist por sha256 em `externalReferences`          |
| Proveniência    | GitHub Artifact Attestation (SLSA-provenance v1) | `gh attestation verify <artefato> -R Voltolini-SPACE/NOMOS`               |
| Reprodutibilidade | (implícita)                                   | `python tools/repro_check.py` (dois builds independentes → mesmo sha256)  |

## 3. Toolchain pinado

O pipeline de release usa versões exatas do toolchain de empacotamento,
documentadas em `.github/workflows/release.yml`:

```
pip==26.2.1
setuptools==83.0.0
wheel==0.45.1
build==1.5.0
packaging==26.3
pyproject_hooks==1.2.0
```

`python -m build --no-isolation` é obrigatório — sem `--no-isolation`,
`build` cria um venv temporário que puxa a versão MAIS RECENTE de
`setuptools` disponível a cada run, e a garantia de reprodutibilidade
desaparece.

Bump em qualquer versão exige rerodar o experimento forense:

```bash
python tools/repro_check.py
```

Deve terminar com `REPRO_WHEEL=PASS` e `REPRO_SDIST=PASS`. Se falhar,
o script imprime o primeiro membro/campo divergente — não fazer bump
até resolver.

## 4. Reprodutibilidade

### Wheel

Reproduzível bit-a-bit quando:
- toolchain pinado (§3);
- `SOURCE_DATE_EPOCH` = timestamp UTC do commit da tag;
- `PYTHONHASHSEED=0`;
- `TZ=UTC`, `LC_ALL=LANG=C.UTF-8`;
- `python -m build --no-isolation`.

Verificado empiricamente: `nomos-1.3.0rc19-py3-none-any.whl` construído
em macOS local produz `sha256=598ae56d471fd266137aa6f58b14cc15c3fc88e37b98b9a29ee1f9e00e37ecef`
— exatamente o mesmo hash publicado pelo runner Linux do CI.

### Sdist

`setuptools.build_meta.build_sdist` (versão 83, e todas as anteriores)
NÃO respeita `SOURCE_DATE_EPOCH` — mtimes de arquivos/diretórios ficam
com o wall-clock do build, e o gzip header embute a hora da compactação
(bug conhecido [pypa/setuptools#2133](https://github.com/pypa/setuptools/issues/2133)).

Correção: `tools/reproducible_sdist.py` reescreve o `.tar.gz` in-place,
normalizando **apenas metadados de container**:

- `mtime` de cada membro → `SOURCE_DATE_EPOCH`
- `uid=0`, `gid=0`, `uname=""`, `gname=""`
- `mode` → `0o644` (arquivos) / `0o755` (diretórios)
- ordem alfabética por nome
- USTAR format (sem PAX headers)
- gzip: `mtime=0`, `filename=""`

Nomes, permissões executivas, bytes de arquivos e distinção
arquivo/diretório/symlink são **preservados**. O sdist normalizado
instala normalmente (`pip install nomos-*.tar.gz` produz o mesmo
comportamento).

O artefato NORMALIZADO é o sujeito de attestation, SBOM e SHA256SUMS.

### Gate contínuo

Um novo job `reprodutibilidade` no `.github/workflows/ci.yml` executa
`tools/repro_check.py` em cada push/PR: faz dois builds independentes
(diretórios separados, venvs separados, pip caches separados) e falha
se qualquer hash divergir.

## 5. Hardening das actions

Todas as actions críticas estão pinadas por SHA imutável de 40 caracteres,
formato:

```yaml
uses: owner/action@<SHA40> # vX.Y.Z
```

O comentário com a versão humana é o alvo do Dependabot
(`.github/dependabot.yml`): quando surge um bump, o PR chega já com o
novo SHA e o novo comentário — a revisão humana confirma release notes
e assinatura antes do merge.

Ganho: se um tag mutável (`@v7`) for silenciosamente re-apontado para
um commit malicioso (padrão observado em ataques a
`tj-actions/changed-files` etc.), este pipeline continua executando o
commit auditado.

## 6. Permissions

Mínimo privilégio por default, escopo por-job onde precisa mais:

| Workflow | Job | contents | id-token | attestations | pages |
| --- | --- | --- | --- | --- | --- |
| `ci.yml`      | (todos)     | read  | —     | —     | —     |
| `release.yml` | validar     | read  | —     | —     | —     |
| `release.yml` | publicar    | write | write | write | —     |
| `pages.yml`   | deploy      | read  | write | —     | write |

**Trust boundary residual** (registrado; refator postergado para próxima
missão de supply-chain): o job `publicar` executa código do repo
(`python -m build`, `tools/reproducible_sdist.py`, `tools/make_sbom.py`)
depois de receber `id-token: write` — necessário porque
`actions/attest-build-provenance` assina o próprio `dist/`. Mitigação
atual: os tools são stdlib-only, revisados no repo, sem I/O externa,
rodam contra saída controlada do próprio build.

## 7. Como o consumidor verifica

Baixe qualquer release em https://github.com/Voltolini-SPACE/NOMOS/releases,
para a mesma pasta. Depois:

```bash
# 1. Integridade
sha256sum -c SHA256SUMS       # Linux
shasum -a 256 -c SHA256SUMS   # macOS

# 2. Proveniência SLSA
gh attestation verify nomos-<versao>-py3-none-any.whl \
    -R Voltolini-SPACE/NOMOS
gh attestation verify nomos-<versao>.tar.gz \
    -R Voltolini-SPACE/NOMOS

# 3. Reprodutibilidade (opcional, requer clonar o repo)
git clone https://github.com/Voltolini-SPACE/NOMOS && cd NOMOS
git checkout v<versao>
python tools/repro_check.py     # imprime REPRO_WHEEL=PASS + REPRO_SDIST=PASS
```

## 8. Estado por versão

| Versão          | Wheel bit-a-bit | Sdist bit-a-bit | Attestation | SBOM sha256-bound | Actions pinadas por SHA |
| --------------- | :-------------: | :-------------: | :---------: | :---------------: | :---------------------: |
| `v1.3.0rc18`    | não             | não             | não         | não               | não                     |
| `v1.3.0rc19`    | sim (verificado) | não (bug setuptools) | sim | sim               | não                     |
| `>= v1.3.0rc19+1` | sim           | sim (via `reproducible_sdist.py`) | sim | sim               | sim                     |

`v1.3.0rc19` continua PUBLICADA sem alterações — retag ou substituição
de assets é PROIBIDA. A próxima release que sair depois de merge da
branch H4.9 herdará todas as garantias da última linha.
