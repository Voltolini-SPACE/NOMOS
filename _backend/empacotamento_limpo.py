"""Backend PEP 517 do NOMOS: setuptools.build_meta com faxina prévia.

Landmine real (24/08/2026): um `build/lib` obsoleto — invisível ao git, herdado
de um branch antigo — era MESCLADO pelo build_py do setuptools em cada wheel
novo. `pip install .` instalou 9 skills embutidas onde o fonte tinha 4, e só o
teste de contrato do venv pegou o estrago. O setuptools não oferece opção de
limpar o diretório de build; a correção de raiz é ESTE backend: todo build
(wheel, sdist, editable) nasce com `build/` e `src/*.egg-info` apagados.
O fluxo via sdist (`python -m build`) sempre foi imune por construir em
diretório temporário isolado; agora `pip install .` e `--wheel` também são.

Os dois caminhos são artefatos declarados no .gitignore ("nunca versionar") e
zero arquivos versionados vivem neles — apagar é sempre seguro (PEP 517 roda
os hooks com cwd na raiz da árvore fonte).
"""
from __future__ import annotations

import shutil
from pathlib import Path

from setuptools import build_meta as _setuptools

# hooks que não empacotam artefato: delegação direta, sem faxina
get_requires_for_build_wheel = _setuptools.get_requires_for_build_wheel
get_requires_for_build_sdist = _setuptools.get_requires_for_build_sdist
get_requires_for_build_editable = _setuptools.get_requires_for_build_editable
prepare_metadata_for_build_wheel = _setuptools.prepare_metadata_for_build_wheel
prepare_metadata_for_build_editable = (
    _setuptools.prepare_metadata_for_build_editable)


def _faxina() -> None:
    shutil.rmtree(Path("build"), ignore_errors=True)
    for sobra in Path("src").glob("*.egg-info"):
        shutil.rmtree(sobra, ignore_errors=True)


def build_wheel(wheel_directory, config_settings=None,
                metadata_directory=None):
    _faxina()
    return _setuptools.build_wheel(wheel_directory, config_settings,
                                   metadata_directory)


def build_sdist(sdist_directory, config_settings=None):
    _faxina()
    return _setuptools.build_sdist(sdist_directory, config_settings)


def build_editable(wheel_directory, config_settings=None,
                   metadata_directory=None):
    _faxina()
    return _setuptools.build_editable(wheel_directory, config_settings,
                                      metadata_directory)
