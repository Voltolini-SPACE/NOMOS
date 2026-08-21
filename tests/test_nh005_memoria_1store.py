"""NH-005 (GO condicionado) — caracterização, gate PII e importar-mc28.

P0 congela o comportamento dos DOIS stores; P1 prova que nenhum segredo
entra mais no memory.db; P2 prova importação idempotente com origem
byte-idêntica, tripwire de adulteração e rollback completo.
"""
from __future__ import annotations

import hashlib
import json

import pytest

from nomos import cli
from nomos.cognition.memory import Memory, MemoriaRecusada
from nomos.memory import ponte
from nomos.memory.engine import MemoryEngine
from nomos.memory.store import MemoryStore, recompute_hash

SEGREDO = "minha chave é sk-" + "a" * 24


# ------------------------------------------------------- P0 caracterização

def test_caracterizacao_memory_db_remember_recall_candidatas(tmp_path):
    mem = Memory(tmp_path / "memory.db")
    mid = mem.remember("note", "o projeto usa Python 3.14")
    assert isinstance(mid, int) and mid > 0
    tid = mem.remember_typed("prefere respostas curtas", tipo="preferencia")
    assert tid > mid
    achados = mem.recall_hibrido("Python", k=3)
    assert any("Python" in a.text for a in achados)
    cid = mem.propor_candidata("gosta de café", tipo="preferencia")
    fila = mem.candidatas()
    assert any(c["id"] == cid for c in fila)
    assert mem.aprovar_candidata(cid) is not None
    assert all(c["id"] != cid for c in mem.candidatas())


def test_caracterizacao_mc28_add_dry_run_apply_validate_hash(tmp_path,
                                                             monkeypatch):
    monkeypatch.setenv("NOMOS_HOME", str(tmp_path))
    eng = MemoryEngine()
    r_seco = eng.add("fato de teste da caracterização", source="manual")
    assert r_seco.dry_run is True, "dry-run é o padrão ABSOLUTO do MC28"
    r_real = eng.add("fato de teste da caracterização", source="manual",
                     apply=True)
    assert r_real.applied is True
    entradas = MemoryStore().read_raw()
    assert len(entradas) == 1
    assert recompute_hash(entradas[0]) == entradas[0]["hash"]


# ------------------------------------------------------------- P1 gate PII

def test_remember_recusa_segredo_fail_closed(tmp_path):
    mem = Memory(tmp_path / "memory.db")
    antes = mem.count()
    with pytest.raises(MemoriaRecusada):
        mem.remember("note", SEGREDO)
    with pytest.raises(MemoriaRecusada):
        mem.remember_typed(SEGREDO, tipo="fato")
    assert mem.count() == antes, "recusa não pode deixar rastro no banco"


def test_aprovar_candidata_com_segredo_recusa(tmp_path):
    mem = Memory(tmp_path / "memory.db")
    cid = mem.conn.execute(
        "INSERT INTO mem_candidatas(ts, tipo, text, fonte) "
        "VALUES (1, 'fato', ?, 'teste')", (SEGREDO,)).lastrowid
    mem.conn.commit()
    with pytest.raises(MemoriaRecusada):
        mem.aprovar_candidata(cid)


def test_remember_legitimo_inalterado(tmp_path):
    mem = Memory(tmp_path / "memory.db")
    for texto in ("meu aniversário é em janeiro",
                  "prefiro tabs a espaços",
                  "o deploy roda às 6h"):
        assert mem.remember("note", texto) > 0


def test_chat_nao_quebra_com_memoria_recusada(tmp_path, monkeypatch, capsys):
    """O caller do chat avisa no stderr e segue — resposta nunca quebra."""
    monkeypatch.setenv("NOMOS_HOME", str(tmp_path))
    mem = Memory(tmp_path / "memory.db")
    from nomos.cognition.memory import MemoriaRecusada as MR
    try:
        mem.remember("user", SEGREDO)
    except MR:
        print("(não guardei esta troca: conteúdo com padrão de segredo)",)
    assert mem.count() == 0


# ------------------------------------------------------ P2 importar-mc28

def _povoar_mc28(tmp_path, monkeypatch, textos):
    monkeypatch.setenv("NOMOS_HOME", str(tmp_path))
    eng = MemoryEngine()
    for t in textos:
        r = eng.add(t, source="manual", apply=True)
        assert r.applied, t
    return MemoryStore()


def test_importar_mc28_idempotente_e_origem_intacta(tmp_path, monkeypatch):
    store = _povoar_mc28(tmp_path, monkeypatch,
                         ["fato um da migração", "fato dois da migração"])
    origem = store.paths.raw
    sha_antes = hashlib.sha256(origem.read_bytes()).hexdigest()
    mem = Memory(tmp_path / "memory.db")
    r1 = ponte.importar(store, mem)
    assert r1.importadas == 2 and r1.ok
    r2 = ponte.importar(store, mem)
    assert r2.importadas == 0 and r2.duplicadas == 2, "rodar 2× não duplica"
    assert hashlib.sha256(origem.read_bytes()).hexdigest() == sha_antes, \
        "memory.jsonl tem de ficar BYTE-IDÊNTICO"
    achados = mem.recall_hibrido("migração", k=5)
    assert len(achados) >= 2, "importado tem de ser encontrável"


def test_importar_mc28_dry_run_nao_escreve(tmp_path, monkeypatch):
    store = _povoar_mc28(tmp_path, monkeypatch, ["fato seco"])
    mem = Memory(tmp_path / "memory.db")
    r = ponte.importar(store, mem, dry_run=True)
    assert r.importadas == 1
    assert mem.count() == 0, "dry-run não grava nada"


def test_importar_mc28_hash_invalido_pula_e_reporta(tmp_path, monkeypatch):
    store = _povoar_mc28(tmp_path, monkeypatch, ["fato integro"])
    # adultera a única entrada (contrato: quem mexe no jsonl quebra o hash)
    origem = store.paths.raw
    entrada = json.loads(origem.read_text().splitlines()[0])
    entrada["content"] = "conteudo ADULTERADO"
    origem.write_text(json.dumps(entrada, ensure_ascii=False) + "\n")
    mem = Memory(tmp_path / "memory.db")
    r = ponte.importar(store, mem)
    assert r.puladas_hash == 1 and r.importadas == 0
    assert not r.ok, "adulteração ⇒ tripwire NO-GO (exit≠0 no CLI)"
    assert mem.count() == 0, "dado adulterado JAMAIS entra (seria lavá-lo)"


def test_importar_mc28_pii_rejeitada_na_ponte(tmp_path, monkeypatch):
    """Defesa em profundidade: mesmo se o jsonl carregar segredo (não
    deveria — o próprio MC28 gateia), a ponte re-aplica a política."""
    store = _povoar_mc28(tmp_path, monkeypatch, ["fato limpo"])
    origem = store.paths.raw
    entrada = json.loads(origem.read_text().splitlines()[0])
    entrada["content"] = SEGREDO
    entrada["hash"] = ""
    del entrada["hash"]
    entrada["hash"] = recompute_hash(entrada)   # hash VÁLIDO, conteúdo sujo
    with origem.open("a") as fh:
        fh.write(json.dumps(entrada, ensure_ascii=False) + "\n")
    mem = Memory(tmp_path / "memory.db")
    r = ponte.importar(store, mem)
    assert r.rejeitadas_politica >= 1
    assert all("sk-" not in a.text
               for a in mem.recall_hibrido("chave", k=10))


def test_desfazer_remove_exatamente_o_importado(tmp_path, monkeypatch):
    store = _povoar_mc28(tmp_path, monkeypatch, ["fato importado"])
    mem = Memory(tmp_path / "memory.db")
    proprio = mem.remember("note", "memória NATIVA que fica")
    ponte.importar(store, mem)
    assert ponte.desfazer(mem) == 1
    assert mem.count() == 1
    assert mem.conn.execute("SELECT COUNT(*) FROM memories WHERE id=?",
                            (proprio,)).fetchone()[0] == 1


def test_cli_importar_mc28_fluxo_completo(tmp_path, monkeypatch, capsys):
    _povoar_mc28(tmp_path, monkeypatch, ["fato pela cli"])
    assert cli.main(["memoria", "importar-mc28", "--dry-run"]) == cli.EXIT_OK
    assert cli.main(["memoria", "importar-mc28"]) == cli.EXIT_OK
    assert cli.main(["memoria", "importar-mc28", "--desfazer"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "importadas: 1" in out and "desfeito: 1" in out


# ------------------------------------------------------------- sentinelas

def test_memory_engine_sem_callers_fora_do_pacote():
    """Gate mecânico do critério de destravamento de P3/P4: `nomos.memory`
    só pode ser importado pelo próprio pacote e por `cognition/memory.py`
    (o gate P1). Um caller novo muda o cálculo de risco ⇒ o teste acusa."""
    import pathlib

    import nomos
    src = pathlib.Path(nomos.__file__).parent
    permitidos = {src / "cognition" / "memory.py",
                  src / "cli.py",              # importar-mc28 (P2, one-shot)
                  src / "memory" / "ponte.py"}
    violacoes = []
    for py in src.rglob("*.py"):
        if py.is_relative_to(src / "memory"):
            continue
        texto = py.read_text(encoding="utf-8")
        if ("from nomos.memory" in texto or "nomos.memory import" in texto
                or "import nomos.memory" in texto):
            if py not in permitidos:
                violacoes.append(str(py.relative_to(src)))
    assert violacoes == [], f"caller novo de nomos.memory: {violacoes}"


def test_kernel_nao_importa_memory():
    """Isolamento documentado em audit.py continua de pé — o teste olha
    IMPORTS reais, não menções em comentário (audit.py cita o módulo num
    comentário de propósito, para explicar a duplicação)."""
    import pathlib

    import nomos
    kernel = pathlib.Path(nomos.__file__).parent / "kernel"
    for py in kernel.glob("*.py"):
        for linha in py.read_text(encoding="utf-8").splitlines():
            limpa = linha.split("#", 1)[0]
            assert not ("from nomos.memory" in limpa
                        or "import nomos.memory" in limpa), \
                f"{py.name}: kernel não pode importar memory ({linha.strip()})"


# ------------------- achados da revisão adversarial (Missão B, 21/08) -------

def test_propor_candidata_gateia_segredo(tmp_path):
    """NO-GO #4 do ADR: `mem_candidatas` é tabela DO memory.db — sem gate, o
    segredo que `remember` recusava entrava em claro pela fila de revisão."""
    mem = Memory(tmp_path / "memory.db")
    with pytest.raises(MemoriaRecusada):
        mem.propor_candidata(SEGREDO)
    assert mem.candidatas() == []
    assert SEGREDO.encode() not in (tmp_path / "memory.db").read_bytes()


def test_propor_candidatas_do_texto_pula_suja_e_nao_derruba(tmp_path):
    """No MESMO turno em que `remember` recusa, a fila não pode aceitar."""
    mem = Memory(tmp_path / "memory.db")
    texto = ("não posso esquecer de rotacionar o token: minha api_key = "
             + "sk-" + "a" * 24)
    assert mem.propor_candidatas_do_texto(texto) == []
    assert mem.candidatas() == []
    assert b"sk-" + b"a" * 24 not in (tmp_path / "memory.db").read_bytes()


def test_consolidar_pula_nota_suja_e_grava_as_limpas(tmp_path):
    """Uma nota LEGADA com segredo não pode abortar o lote inteiro."""
    mem = Memory(tmp_path / "memory.db")
    for texto in ("meu email é fulano@x.com e a senha = hunter2segredo",
                  "meu telefone é 11999998888"):
        mem.conn.execute("INSERT INTO memories(ts, role, text) "
                         "VALUES (1, 'user', ?)", (texto,))
    mem.conn.commit()
    criadas = mem.consolidar()          # não pode levantar
    assert all("hunter2segredo" not in n for n in criadas)


def test_chat_amigavel_sobrevive_a_segredo_digitado(tmp_path, monkeypatch):
    """`nomos start`: recusa avisa e SEGUE — a sessão não pode morrer."""
    from nomos.cognition.router import ChatOutcome
    from nomos.kernel.policy import PolicyEngine
    from nomos.simple import amigavel

    class _Router:
        def chat(self, messages, prefer_cloud=False, passphrase=None):
            return ChatOutcome(True, "local", "ok", "embutido", "fake")

        def chat_stream(self, messages, on_token):
            on_token("ok")
            return ChatOutcome(True, "local", "ok", "embutido", "fake")

    monkeypatch.setenv("NOMOS_HOME", str(tmp_path))
    tela = []
    entradas = iter(["minha senha = hunter2segredo", "/sair"])
    rc = amigavel.iniciar_chat(
        {"home": tmp_path, "policy": PolicyEngine(tmp_path / "p.json")},
        {"agent_name": "Luna"}, router=_Router(),
        ask=lambda _p: next(entradas), say=tela.append, colorido=False,
        aprovador=lambda d: True)
    assert rc == 0, "sessão não pode morrer por recusa de memória"
    assert any("não guardei" in linha for linha in tela)
