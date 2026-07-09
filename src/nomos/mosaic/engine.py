"""NOMOS Mosaic — orquestrador.

Une registro, vistoria (adapter), conhecimento e painel. Segue a mesma
disciplina do MC28: **dry-run é o padrão**; nada é escrito/agido sem `apply`.
Ações que mexem nas contas (marcar lido, responder, arquivar) só executam com
aprovação — o padrão é apenas PROPOR.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlparse

from nomos.mosaic import browser, panel
from nomos.mosaic.knowledge import Knowledge, KnowledgeStore
from nomos.mosaic.registry import MosaicRegistry

ACTIONS = {"monitor", "mark_read", "reply", "archive"}

# Conjunto SIMULADO para apresentação — o painel nunca abre vazio numa demo.
DEMO_SCREENS = [
    ("mail.google.com", "Gmail"),
    ("bb.com.br", "Banco do Brasil"),
    ("web.whatsapp.com", "WhatsApp Web"),
    ("tiktok.com", "TikTok"),
    ("instagram.com", "Instagram"),
    ("mercadolivre.com.br", "Mercado Livre"),
    ("outlook.office.com", "Outlook"),
    ("linkedin.com", "LinkedIn"),
]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class ScanResult:
    screen_id: str
    ok: bool
    saved: bool
    snapshot: browser.Snapshot


@dataclass
class ActionResult:
    screen_id: str
    action: str
    applied: bool
    approved: bool
    reason: str
    proposal: dict = field(default_factory=dict)


class MosaicEngine:
    def __init__(self, base_dir=None, adapter=None) -> None:
        self.registry = MosaicRegistry(base_dir)
        self.knowledge = KnowledgeStore(self.registry.base)
        self.adapter = adapter or browser.DemoAdapter()

    # ---------- telas ----------
    def add_screen(self, url: str, label: str = "", apply: bool = False) -> dict:
        norm = MosaicRegistry.normalize_url(url)
        if not apply:
            return {"applied": False, "dry_run": True, "url": norm,
                    "label": label or norm, "note": "DRY-RUN: nada gravado"}
        s = self.registry.add(norm, label)
        return {"applied": True, "dry_run": False, "screen": s.__dict__}

    def list_screens(self):
        return self.registry.list()

    def seed_demo(self, apply: bool = False) -> dict:
        """Popula telas SIMULADAS de apresentação (Gmail, BB, WhatsApp, TikTok…).
        Dry-run por padrão: só diz o que criaria. Com apply, cria as que faltam
        (sem duplicar) e vistoria tudo pelo adaptador demo (sem rede)."""
        existentes = {s.url for s in self.registry.list()}
        alvo = [(MosaicRegistry.normalize_url(u), lbl) for u, lbl in DEMO_SCREENS]
        faltando = [(u, lbl) for u, lbl in alvo if u not in existentes]
        if not apply:
            return {"applied": False, "dry_run": True,
                    "would_add": [lbl for _, lbl in faltando]}
        for u, lbl in faltando:
            self.registry.add(u, lbl)
        self.scan(apply=True)
        return {"applied": True, "added": [lbl for _, lbl in faltando],
                "total": len(self.registry.list())}

    def remove_screen(self, screen_id: str, apply: bool = False) -> dict:
        exists = self.registry.get(screen_id) is not None
        if not apply:
            return {"applied": False, "dry_run": True, "would_remove": exists}
        return {"applied": True, "removed": self.registry.remove(screen_id)}

    # ---------- vistoria ----------
    def scan(self, screen_id: str | None = None, apply: bool = False) -> list[ScanResult]:
        alvos = ([s for s in self.registry.list() if s.id == screen_id]
                 if screen_id else self.registry.list())
        out: list[ScanResult] = []
        for s in alvos:
            snap = self.adapter.scan(s.id, s.url, s.profile_dir)
            saved = False
            if apply and snap.ok:
                self.knowledge.save(Knowledge(
                    screen_id=s.id, url=s.url, scanned_at=_now(),
                    title=snap.title, summary=snap.text, text_excerpt=snap.text[:2000],
                    signals=snap.signals, image=snap.image_data_uri,
                ))
                saved = True
            out.append(ScanResult(s.id, snap.ok, saved, snap))
        return out

    # ---------- painel ----------
    def build_tiles(self) -> list[dict]:
        tiles = []
        for s in self.registry.list():
            k = self.knowledge.get(s.id)
            tiles.append({
                "id": s.id, "label": s.label,
                "host": (urlparse(s.url).hostname or s.url), "url": s.url,
                "image": (k.image if k else ""),
                "signals": (k.signals if k else {}),
                "summary": (k.summary if k else "sem vistoria ainda — rode --scan"),
            })
        return tiles

    def render_panel(self, apply: bool = False):
        html = panel.render(self.build_tiles(), _now())
        if not apply:
            return html, None
        self.registry.base.mkdir(parents=True, exist_ok=True)
        p = self.registry.base / "panel.html"
        p.write_text(html, encoding="utf-8")
        try:
            os.chmod(p, 0o600)
        except (OSError, NotImplementedError):
            pass
        return html, str(p)

    # ---------- monitorar + agir (com aprovação) ----------
    def act(self, screen_id: str, action: str, approve: bool = False,
            apply: bool = False) -> ActionResult:
        if action not in ACTIONS:
            return ActionResult(screen_id, action, False, False,
                                "ACTION_REJECTED_FAIL_CLOSED")
        if self.registry.get(screen_id) is None:
            return ActionResult(screen_id, action, False, False, "SCREEN_NOT_FOUND")
        proposal = {"screen_id": screen_id, "action": action, "proposed_at": _now()}
        # dry-run OU sem aprovação → apenas PROPÕE
        if not apply or not approve:
            return ActionResult(screen_id, action, False, approve, "PROPOSED", proposal)
        # aprovado + apply → registra a execução (demo). Go-live executa no browser.
        log = self.registry.base / "actions.jsonl"
        self.registry.base.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({**proposal, "executed_by": self.adapter.name},
                                ensure_ascii=False) + "\n")
        try:
            os.chmod(log, 0o600)
        except (OSError, NotImplementedError):
            pass
        return ActionResult(screen_id, action, True, True, "APPLIED", proposal)

    # ---------- o que o agente já sabe ----------
    def context(self) -> str:
        ks = self.knowledge.all()
        if not ks:
            return "NOMOS Mosaic: nenhuma vistoria ainda."
        linhas = [f"NOMOS Mosaic — {len(ks)} tela(s) vistoriada(s):"]
        for k in ks:
            sig = ", ".join(f"{a}={b}" for a, b in (k.signals or {}).items()) or "—"
            linhas.append(f"- {k.title} [{urlparse(k.url).hostname}] ({sig}) — {k.summary[:100]}")
        return "\n".join(linhas)
