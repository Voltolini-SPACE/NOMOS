"""Configuração raiz do pytest.

Ignora na coleção diretórios de extração de sdist/build (ex.: ``nomos-1.3.0rc16/``),
que contêm cópias dos testes com os mesmos nomes de módulo e causariam
"import file mismatch" no pytest. Esses diretórios são artefatos de build untracked
(também ignorados no .gitignore) e não fazem parte da suíte real.
"""

collect_ignore_glob = ["nomos-[0-9]*"]
