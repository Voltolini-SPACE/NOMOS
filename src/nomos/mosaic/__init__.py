"""NOMOS Mosaic — painel de telas ao vivo, isoladas, vistoriadas pelo agente.

Subsistema **consentido e separado** do núcleo egress-zero do NOMOS: aqui há
navegação real (rede) e sessões logadas por tela. Cada tela tem perfil próprio
(isolamento), o mosaico se auto-organiza, e o agente varre cada página para já
saber o conteúdo quando você pedir. Ações (marcar, arquivar, responder) são
**dry-run por padrão** e exigem aprovação humana.

Camadas: `layout` (grid) · `registry` (telas isoladas) · `knowledge` (vistoria) ·
`browser` (adaptador: demo agora, Playwright no go-live) · `engine` · `panel`
(HTML) · `cli`.
"""
from __future__ import annotations

from nomos.mosaic.engine import MosaicEngine
from nomos.mosaic.registry import MosaicRegistry, Screen

__all__ = ["MosaicEngine", "MosaicRegistry", "Screen", "__version__", "ENGINE_ID"]
__version__ = "0.1.0"
ENGINE_ID = "NOMOS_MOSAIC_V0"
