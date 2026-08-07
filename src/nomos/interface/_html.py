"""NOMOS interface._html — escape de HTML único para o pacote `interface`.

Achado P2-7 da auditoria de 2026-07-17: `painel_web.py` e `panel.py`
(ambos em `nomos.interface`) tinham cada um sua própria convenção de
escape — `painel_web.py` usava o alias local `e = html.escape` (repetido
em 9 funções diferentes); `panel.py` chamava `html.escape(...)` inline.
As duas formas QUEBRAM (`AttributeError`/`TypeError`) se o valor não for
`str` — inclusive `None`, um caso realista para campos opcionais lidos de
JSON/objeto (ex.: uma razão de aprovação vazia). Esta função substitui as
duas cópias por uma versão null-safe: `None` vira string vazia, qualquer
outro tipo passa por `str()` antes de escapar — nunca lança exceção, e
para qualquer entrada que já fosse `str` o resultado é BYTE A BYTE
idêntico ao `html.escape(x, quote=True)` de antes (não muda nenhuma saída
já validada por teste).

`nomos.mosaic.panel` tem sua PRÓPRIA cópia (`_esc`) e permanece assim de
propósito: o pacote `mosaic` não importa nada de `nomos.*` — isolamento
deliberado (mesmo princípio já aplicado a `SECRET_PATTERNS` em
`kernel/audit.py`, duplicado ali para não importar `nomos.memory`). O
comportamento de `mosaic._esc` foi alinhado a este contrato (ver P2-7),
mas o código continua fisicamente duplicado, não importado.
"""
from __future__ import annotations

import html as _html


def esc(valor: object) -> str:
    """Escapa `valor` para HTML seguro. `None` vira `""`; qualquer outro
    tipo (int, bool, etc.) é convertido via `str()` antes de escapar —
    nunca lança exceção, ao contrário de `html.escape()` puro."""
    return _html.escape("" if valor is None else str(valor), quote=True)
