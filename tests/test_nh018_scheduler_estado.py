"""NH-018 — notepad durável, continuidade e monitor-mode no scheduler.

As invariantes duras: posse da nota cravada na closure (job A jamais toca
nota do job B); chaves `__*` são do sistema; `salvar` com lista explícita
de colunas sobrevive à migração aditiva (achado do juiz); monitor suprime
por CONTEÚDO e nunca avança hash em falha.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from nomos.adapters.contrato import ErroInvalido
from nomos.adapters.monitor import (
    MONITOR_ARQUIVOS_MAX, SENTINELA_AUSENTE, hash_alvo,
)
from nomos.adapters.scheduler import ArmazemJobs, JobState, Scheduler
from nomos.kernel.audit import AuditLog
from nomos.kernel.policy import PolicyEngine
from nomos.runtime.agendador import AgendadorGovernado, ConfigAgendador

T0 = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)


def _amb(tmp_path):
    home = tmp_path / "h"
    home.mkdir(exist_ok=True)
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    ctx = {"home": home,
           "policy": PolicyEngine(home / "policy.json"),
           "audit": AuditLog(home / "logs" / "audit.jsonl")}
    return ctx, ws


def _eventos(ctx):
    p = ctx["home"] / "logs" / "audit.jsonl"
    return [json.loads(x).get("event")
            for x in p.read_text().splitlines() if x.strip()]


# ------------------------------------------------------------------ notepad

def test_nota_roundtrip_quotas_e_expurgo(tmp_path):
    az = ArmazemJobs(tmp_path / "j.db")
    az.nota_escrever("j1", "k", "valor")
    assert az.nota_ler("j1", "k") == "valor"
    assert az.notas_de("j1") == {"k": "valor"}
    with pytest.raises(ErroInvalido):
        az.nota_escrever("j1", "k" * 65, "x")          # chave 65 bytes
    with pytest.raises(ErroInvalido):
        az.nota_escrever("j1", "k2", "x" * 4097)       # valor 4097 bytes
    for i in range(31):
        az.nota_escrever("j1", f"c{i}", "v")
    with pytest.raises(ErroInvalido):
        az.nota_escrever("j1", "c-excedente", "v")     # 33ª chave
    az.nota_escrever("j1", "k", "atualizar existente ainda funciona")
    assert az.notas_apagar("j1") == 33 - 1             # 32 notas removidas
    assert az.notas_de("j1") == {}


def test_nota_valor_passa_por_redact_text(tmp_path):
    az = ArmazemJobs(tmp_path / "j.db")
    az.nota_escrever("j1", "k", "token sk-" + "a" * 24)
    assert "sk-" + "a" * 24 not in az.nota_ler("j1", "k"), \
        "segredo no valor tem de sair REDIGIDO"


def test_nota_expurgada_com_o_job(tmp_path):
    az = ArmazemJobs(tmp_path / "j.db")
    s = Scheduler(az, executor=lambda d, i, credencial=None: None,
                  agora_fn=lambda: T0)
    s.criar("j1", "suj", "fs-listar", primeiro_em=T0)
    az.nota_escrever("j1", "k", "v")
    s.cancelar("j1")
    s.apagar("j1")
    assert az.notas_de("j1") == {}, "nota órfã é vazamento de quota"


def test_migracao_aditiva_banco_antigo_salvar_explicito(tmp_path):
    """Achado do juiz: banco PRÉ-colunas migra, e `salvar` com lista
    explícita grava/lê sem quebrar no INSERT posicional."""
    caminho = tmp_path / "antigo.db"
    con = sqlite3.connect(caminho)
    con.execute("""CREATE TABLE jobs (
        job_id TEXT PRIMARY KEY, sujeito TEXT NOT NULL,
        capacidade TEXT NOT NULL, argumentos TEXT NOT NULL,
        alvo TEXT NOT NULL, intervalo_s INTEGER,
        proximo_em TEXT, estado TEXT NOT NULL,
        criado_em TEXT NOT NULL, tz TEXT NOT NULL)""")
    con.execute("INSERT INTO jobs VALUES ('legado','s','fs-listar','{}','',"
                "60,NULL,'SCHEDULED','2026-08-01T00:00:00+00:00','UTC')")
    con.commit()
    con.close()
    az = ArmazemJobs(caminho)                  # migra: schedule + NH-018
    legado = az.obter("legado")
    assert legado is not None
    assert legado.continuidade is False and legado.monitorar_alvo == ""
    az.salvar(legado)                          # INSERT explícito não quebra
    s = Scheduler(az, executor=lambda d, i, credencial=None: None,
                  agora_fn=lambda: T0)
    s.criar("novo", "s", "fs-listar", primeiro_em=T0,
            continuidade=True, monitorar_alvo="")
    relido = az.obter("novo")
    assert relido.continuidade is True


# ---------------------------------------------------- capacidade governada

def _agendador_com_job(tmp_path, capacidade, argumentos=None, **criar_kw):
    ctx, ws = _amb(tmp_path)
    ag = AgendadorGovernado(ctx, lambda d: True,
                            ConfigAgendador(raizes=(str(ws),)),
                            agora_fn=lambda: T0)
    ag.preparar()
    d = ag.scheduler.criar("j1", "suj", capacidade,
                           argumentos=argumentos or {},
                           primeiro_em=T0, **criar_kw)
    return ctx, ws, ag, d


def test_nota_capacidade_so_existe_dentro_da_execucao(tmp_path):
    ctx, ws, ag, d = _agendador_com_job(tmp_path, "job-nota-escrever",
                                        argumentos={"chave": "k",
                                                    "valor": "v"})
    # fora de execução: o runtime do operar() NÃO registra job-nota-*
    rt_fora = ag._runtime()
    assert "job-nota-escrever" not in rt_fora.executores
    # dentro da execução do job: o autorizador registra com o job_id cravado
    rt = ag.autorizador(d, None)
    assert rt is not None and "job-nota-escrever" in rt.executores
    ex = ag._executar_ocorrencia(d, type("I", (), {"ocorrencia": "o1"})(),
                                 credencial=rt)
    assert ag.armazem.nota_ler("j1", "k") == "v"
    assert ex is not None


def test_nota_closure_fixa_o_job_id(tmp_path):
    """O plano do job A não alcança nota do job B nem mandando job_id."""
    ctx, ws, ag, d = _agendador_com_job(
        tmp_path, "job-nota-escrever",
        argumentos={"chave": "k", "valor": "v", "job_id": "OUTRO"})
    rt = ag.autorizador(d, None)
    ag._executar_ocorrencia(d, type("I", (), {"ocorrencia": "o1"})(),
                            credencial=rt)
    assert ag.armazem.nota_ler("j1", "k") == "v", "grava no PRÓPRIO job"
    assert ag.armazem.nota_ler("OUTRO", "k") is None, \
        "job_id de params é ignorado — posse vem da closure"


def test_nota_chave_de_sistema_recusada_na_capacidade(tmp_path):
    from nomos.runtime.governado import ErroRuntime
    ctx, ws, ag, d = _agendador_com_job(
        tmp_path, "job-nota-escrever",
        argumentos={"chave": "__resumo_anterior", "valor": "forjado"})
    rt = ag.autorizador(d, None)
    with pytest.raises(ErroRuntime):
        ag._executar_ocorrencia(d, type("I", (), {"ocorrencia": "o1"})(),
                                credencial=rt)
    assert ag.armazem.nota_ler("j1", "__resumo_anterior") is None


# -------------------------------------------------------------- continuidade

def test_continuidade_resumo_no_encerrar_e_entrega_na_n1(tmp_path):
    ctx, ws = _amb(tmp_path)
    recebidos = []

    def executor(d, i, credencial=None):
        recebidos.append(dict(d.argumentos))
        return type("R", (), {"efeito_aplicado": True})()

    az = ArmazemJobs(ctx["home"] / "j.db")
    s = Scheduler(az, executor=executor, agora_fn=lambda: T0)
    d = s.criar("j1", "suj", "fs-listar", intervalo_s=60,
                primeiro_em=T0 - timedelta(seconds=60), continuidade=True)
    s.executar_job(d, T0)
    resumo = az.nota_ler("j1", "__resumo_anterior")
    assert resumo, "fim de ocorrência grava __resumo_anterior"
    corpo = json.loads(resumo)
    assert corpo["estado"] == JobState.SUCCEEDED.value
    assert set(corpo) == {"ocorrencia", "estado", "efeito", "detalhe",
                          "concluida_em"}, "campos FIXOS, determinístico"


def test_continuidade_resumo_tambem_em_falha_e_redigido(tmp_path):
    ctx, ws = _amb(tmp_path)

    def executor(d, i, credencial=None):
        raise RuntimeError("boom com segredo sk-" + "b" * 24)

    az = ArmazemJobs(ctx["home"] / "j.db")
    s = Scheduler(az, executor=executor, agora_fn=lambda: T0)
    d = s.criar("j1", "suj", "fs-listar", primeiro_em=T0, continuidade=True)
    s.executar_job(d, T0)
    corpo = json.loads(az.nota_ler("j1", "__resumo_anterior"))
    assert corpo["estado"] == JobState.FAILED.value
    assert "sk-" + "b" * 24 not in corpo["detalhe"], "detalhe é redigido"


def test_continuidade_injeta_resumo_na_proxima(tmp_path):
    import contextlib

    from nomos.runtime.governado import ErroRuntime
    ctx, ws = _amb(tmp_path)
    ag = AgendadorGovernado(ctx, lambda d: True,
                            ConfigAgendador(raizes=(str(ws),)),
                            agora_fn=lambda: T0)
    ag.preparar()
    d = ag.scheduler.criar("j1", "suj", "fs-listar", alvo=str(ws),
                           primeiro_em=T0, continuidade=True)
    # grava o resumo como o scheduler gravaria (chave de sistema é do dono)
    az = ag.armazem
    with az._lock, az._conn() as c:
        c.execute("INSERT OR REPLACE INTO job_notas VALUES (?,?,?,?)",
                  ("j1", "__resumo_anterior", '{"estado":"SUCCEEDED"}',
                   T0.isoformat()))
    capturado = {}
    rt = ag.autorizador(d, None)
    rodar_original = rt.rodar

    def rodar_espiao(obj, passos):
        capturado["params"] = dict(passos[0]["params"])
        return rodar_original(obj, passos=passos)

    rt.rodar = rodar_espiao
    with contextlib.suppress(ErroRuntime):
        # a capacidade pode recusar o kwarg extra — FAILED visível é
        # comportamento declarado; o que este teste fixa é a INJEÇÃO
        ag._executar_ocorrencia(d, type("I", (), {"ocorrencia": "o1"})(),
                                credencial=rt)
    assert capturado["params"].get("resumo_anterior") == \
        '{"estado":"SUCCEEDED"}'


def test_continuidade_off_nao_grava_nem_injeta(tmp_path):
    ctx, ws = _amb(tmp_path)
    az = ArmazemJobs(ctx["home"] / "j.db")
    s = Scheduler(az, executor=lambda d, i, credencial=None:
                  type("R", (), {"efeito_aplicado": True})(),
                  agora_fn=lambda: T0)
    d = s.criar("j1", "suj", "fs-listar", primeiro_em=T0)
    s.executar_job(d, T0)
    assert az.nota_ler("j1", "__resumo_anterior") is None, "default intacto"


# ------------------------------------------------------------------ monitor

def test_hash_alvo_arquivo_dir_e_sentinela(tmp_path):
    alvo = tmp_path / "a.txt"
    assert hash_alvo(alvo) == SENTINELA_AUSENTE, "ausente é estado, não erro"
    alvo.write_text("conteudo")
    h1 = hash_alvo(alvo)
    alvo.write_text("conteudo2")
    assert hash_alvo(alvo) != h1, "1 byte de mudança dispara"
    d = tmp_path / "dir"
    (d / "sub").mkdir(parents=True)
    (d / "sub" / "x").write_text("1")
    (d / "y").write_text("2")
    h_dir = hash_alvo(d)
    import os
    os.utime(d / "y", (0, 0))                  # mtime muda, conteúdo não
    assert hash_alvo(d) == h_dir, "mtime NÃO engana o hash de conteúdo"


def test_monitor_teto_de_arquivos_recusa(tmp_path, monkeypatch):
    import nomos.adapters.monitor as mon
    monkeypatch.setattr(mon, "MONITOR_ARQUIVOS_MAX", 3)
    d = tmp_path / "muitos"
    d.mkdir()
    for i in range(4):
        (d / f"f{i}").write_text("x")
    with pytest.raises(ErroInvalido):
        mon.hash_alvo(d)
    assert MONITOR_ARQUIVOS_MAX == 10_000      # constante pública intacta


def test_monitor_suprime_e_redispara_por_conteudo(tmp_path):
    ctx, ws = _amb(tmp_path)
    alvo = ws / "observado.txt"
    alvo.write_text("v1")
    ag = AgendadorGovernado(ctx, lambda d: True,
                            ConfigAgendador(raizes=(str(ws),)),
                            agora_fn=lambda: T0)
    ag.preparar()
    d = ag.scheduler.criar("j1", "suj", "fs-listar", alvo=str(ws),
                           primeiro_em=T0, monitorar_alvo=str(alvo))
    inst = type("I", (), {"ocorrencia": "o1"})()
    rt = ag.autorizador(d, inst)
    ag._executar_ocorrencia(d, inst, credencial=rt)          # 1ª: dispara
    h1 = ag.armazem.nota_ler("j1", "__monitor_hash")
    assert h1, "sucesso grava o hash pré-efeito"
    r2 = ag._executar_ocorrencia(d, inst, credencial=rt)     # 2ª: suprime
    assert r2.efeito_aplicado is False
    suprimidas = [e for e in _eventos(ctx)
                  if e == "scheduler.monitor.suprimida"]
    assert len(suprimidas) == 1
    alvo.write_text("v2")                                    # conteúdo mudou
    rt2 = ag.autorizador(d, inst)
    ag._executar_ocorrencia(d, inst, credencial=rt2)         # 3ª: re-dispara
    h3 = ag.armazem.nota_ler("j1", "__monitor_hash")
    assert h3 and h3 != h1, "re-disparo grava o hash NOVO"
    suprimidas = [e for e in _eventos(ctx)
                  if e == "scheduler.monitor.suprimida"]
    assert len(suprimidas) == 1, "a 3ª ocorrência EXECUTOU (não suprimiu)"


def test_monitor_falha_nao_avanca_hash(tmp_path):
    ctx, ws = _amb(tmp_path)
    alvo = ws / "obs.txt"
    alvo.write_text("v1")
    ag = AgendadorGovernado(ctx, lambda d: True,
                            ConfigAgendador(raizes=(str(ws),)),
                            agora_fn=lambda: T0)
    ag.preparar()
    d = ag.scheduler.criar("j1", "suj", "sched-status", primeiro_em=T0,
                           monitorar_alvo=str(alvo))
    inst = type("I", (), {"ocorrencia": "o1"})()

    from nomos.runtime.governado import ErroRuntime
    with pytest.raises(ErroRuntime):
        ag._executar_ocorrencia(d, inst, credencial=None)   # sem autoridade
    assert ag.armazem.nota_ler("j1", "__monitor_hash") is None, \
        "falha ANTES do sucesso não pode avançar o hash"


def test_monitor_fora_do_escopo_negado_na_criacao(tmp_path):
    ctx, ws = _amb(tmp_path)
    fora = tmp_path / "fora-do-escopo.txt"
    fora.write_text("x")
    ag = AgendadorGovernado(ctx, lambda d: True,
                            ConfigAgendador(raizes=(str(ws),)),
                            agora_fn=lambda: T0)
    ag.preparar()
    ok, valor, motivo = ag.operar("sched-criar", job_id="j1",
                                  capacidade="sched-status",
                                  monitorar_alvo=str(fora))
    assert ok is False and "monitorar_alvo" in str(motivo), \
        "PDP confere monitorar_alvo contra o escopo de DADOS na criação"


# ------------------ achados da revisão adversarial (Missão B, 21/08) --------

def test_monitor_nao_segue_symlink_do_alvo(tmp_path):
    """Escape de escopo: link plantado depois da criação tornaria o ticker
    leitor — e oráculo de mudança — de qualquer arquivo do sistema."""
    fora = tmp_path / "fora.txt"
    fora.write_text("segredo de fora")
    link = tmp_path / "link.txt"
    link.symlink_to(fora)
    with pytest.raises(ErroInvalido):
        hash_alvo(link)


def test_monitor_symlink_na_arvore_nao_le_destino(tmp_path):
    """Dentro do diretório monitorado, o link é hasheado pelo DESTINO
    TEXTUAL — mudar o arquivo externo não pode mexer no hash."""
    fora = tmp_path / "fora.txt"
    fora.write_text("v1")
    d = tmp_path / "obs"
    d.mkdir()
    (d / "normal.txt").write_text("conteudo")
    (d / "atalho").symlink_to(fora)
    h1 = hash_alvo(d)
    fora.write_text("v2 COMPLETAMENTE DIFERENTE")
    assert hash_alvo(d) == h1, "conteúdo FORA do escopo não pode mudar o hash"
    (d / "atalho").unlink()
    (d / "atalho").symlink_to(tmp_path / "outro-destino")
    assert hash_alvo(d) != h1, "trocar o DESTINO do link é mudança visível"


def test_monitor_hash_isento_da_quota_de_notas(tmp_path):
    """Quota cheia não pode impedir o scheduler de gravar `__monitor_hash`
    (senão: efeito aplicado + FAILED falso + re-execução para sempre)."""
    az = ArmazemJobs(tmp_path / "j.db")
    for i in range(az.NOTA_CHAVES_MAX):
        az.nota_escrever("j1", f"chave{i}", "v")
    with pytest.raises(ErroInvalido):
        az.nota_escrever("j1", "mais_uma_do_usuario", "v")
    az.nota_escrever("j1", "__monitor_hash", "abc123")     # não pode levantar
    assert az.nota_ler("j1", "__monitor_hash") == "abc123"


def test_monitor_falha_DO_EFEITO_nao_avanca_hash(tmp_path):
    """MUTANTE que sobreviveu: mover o persist do hash para ANTES do efeito
    passava 16/16 — nenhum teste cobria falha DO EFEITO com monitor ligado.
    Com a falha real, o hash TEM de continuar no valor antigo (a mudança
    não pode ser perdida em silêncio)."""
    from nomos.runtime.governado import ErroRuntime
    ctx, ws = _amb(tmp_path)
    alvo = ws / "obs.txt"
    alvo.write_text("v1")
    ag = AgendadorGovernado(ctx, lambda d: True,
                            ConfigAgendador(raizes=(str(ws),)),
                            agora_fn=lambda: T0)
    ag.preparar()
    d = ag.scheduler.criar("j1", "suj", "fs-listar", alvo=str(ws),
                           primeiro_em=T0, monitorar_alvo=str(alvo))
    inst = type("I", (), {"ocorrencia": "o1"})()
    rt = ag.autorizador(d, inst)

    class _Falha:
        ok = False
        motivo = "efeito falhou de propósito"
        missao = None

    rt.rodar = lambda obj, passos: _Falha()
    with pytest.raises(ErroRuntime):
        ag._executar_ocorrencia(d, inst, credencial=rt)
    assert ag.armazem.nota_ler("j1", "__monitor_hash") is None, \
        "falha DO EFEITO não pode avançar o hash — a mudança seria perdida"
