"""Testes reais da arbitragem entre motores (nomos.cognition.arbitragem).

Usa dublês determinísticos de motor (EngineRunner) — eles SÃO o motor no teste e
retornam conteúdo conhecido, então a lógica de debate/convergência é exercitada de
verdade. Provam as invariantes de honestidade: sem motor ⇒ bloqueia sem inventar;
falha ⇒ sem conteúdo; final_content vem sempre de um candidato real.
"""
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from nomos.cognition import arbitragem as arb
from nomos.council.models import CouncilConfidence, CouncilDisagreementLevel, CouncilFailureCode
from _cli_env import cli_env


def _ollama_ativo() -> bool:
    """True se houver um Ollama respondendo na máquina (ex.: dev com Ollama
    aberto). Os testes de 'sandbox sem motor' não podem depender disso."""
    try:
        from nomos.cognition import motores
        return bool(motores._http_ok(motores.OLLAMA))
    except Exception:
        return False


@dataclass
class FakeRunner:
    """Dublê de motor: devolve textos pré-definidos (um por chamada de run)."""
    engine_id: str
    respostas: list
    local: bool = True
    _ready: bool = True
    calls: list = field(default_factory=list)

    def available(self) -> bool:
        return self._ready

    def run(self, prompt: str, *, system: str = "") -> str:
        self.calls.append(prompt)
        i = min(len(self.calls) - 1, len(self.respostas) - 1)
        r = self.respostas[i]
        if isinstance(r, Exception):
            raise r
        return r


TXT_A = "Local-first significa que os dados ficam na sua máquina por padrão."
TXT_B = "Local-first quer dizer que os dados ficam na sua máquina por padrão."
TXT_C = "A capital da Lua é feita de queijo azul e fica em Marte."  # destoa (alucina)


# 1. Sem motor pronto ⇒ bloqueia, sem inventar
def test_sem_motor_bloqueia_sem_inventar():
    r = FakeRunner("x", [TXT_A], _ready=False)
    out = arb.arbitrar("pergunta", [r], rounds=1)
    assert out.status == "no_engine"
    assert out.decision.blocked is True
    assert out.decision.final_content == ""
    assert out.failure_code is CouncilFailureCode.NO_ELIGIBLE_LOCAL_ENGINE
    assert r.calls == []          # nem tentou gerar (não estava pronto)


# 2. Dois motores prontos e concordantes ⇒ converge, escolhe candidato REAL
def test_convergencia_escolhe_candidato_real():
    a = FakeRunner("motor-a", [TXT_A])
    b = FakeRunner("motor-b", [TXT_B])
    out = arb.arbitrar("o que é local-first?", [a, b], rounds=1)
    assert out.status == "ok"
    assert out.decision.blocked is False
    # final_content é EXATAMENTE o de um dos candidatos reais (nunca sintetizado)
    assert out.decision.final_content in {TXT_A, TXT_B}
    assert out.decision.selected_candidate_alias is not None
    assert set(out.engines_ready) == {"motor-a", "motor-b"}


# 3. final_content nunca é inventado — sempre igual a um candidato executado
def test_final_content_vem_de_candidato_real():
    a = FakeRunner("a", [TXT_A])
    b = FakeRunner("b", [TXT_B])
    out = arb.arbitrar("q", [a, b], rounds=1)
    conteudos_reais = {c.content for c in out.candidates if c.content}
    assert out.decision.final_content in conteudos_reais


# 4. Um motor falha ⇒ candidato com failure_code e SEM conteúdo; o outro decide
def test_motor_que_falha_nao_gera_conteudo():
    bom = FakeRunner("bom", [TXT_A])
    ruim = FakeRunner("ruim", [RuntimeError("timeout"), RuntimeError("timeout")])
    out = arb.arbitrar("q", [bom, ruim], rounds=1, min_candidatos=1, max_retries=1)
    falhos = [c for c in out.candidates if c.failure_code is not None]
    assert falhos, "o motor que falhou deve virar candidato com failure_code"
    assert all(c.content == "" for c in falhos)
    assert out.decision.final_content == TXT_A     # o bom venceu, conteúdo real


# 5. Todos falham ⇒ bloqueia, sem conteúdo
def test_todos_falham_bloqueia():
    a = FakeRunner("a", [RuntimeError("x"), RuntimeError("x")])
    b = FakeRunner("b", [ValueError("y"), ValueError("y")])
    out = arb.arbitrar("q", [a, b], rounds=1, max_retries=1)
    assert out.decision.blocked is True
    assert out.decision.final_content == ""
    assert out.failure_code in {CouncilFailureCode.INSUFFICIENT_JUDGES,
                                CouncilFailureCode.ARBITER_UNSAFE_OUTPUT}


# 6. Nuvem só entra com opt-in explícito (local-first)
def test_cloud_excluida_sem_opt_in():
    local = FakeRunner("ollama", [TXT_A], local=True)
    cloud = FakeRunner("claude", [TXT_B], local=False)
    out = arb.arbitrar("q", [local, cloud], rounds=1, min_candidatos=1)
    assert out.engines_ready == ["ollama"]         # cloud fora sem opt-in
    assert cloud.calls == []


def test_cloud_entra_com_opt_in():
    local = FakeRunner("ollama", [TXT_A], local=True)
    cloud = FakeRunner("claude", [TXT_B], local=False)
    out = arb.arbitrar("q", [local, cloud], rounds=1, allow_cloud=True)
    assert set(out.engines_ready) == {"ollama", "claude"}


# 7. Saída perigosa (segredo/comando destrutivo) é bloqueada pelo árbitro
def test_saida_perigosa_bloqueada():
    perigo = "rode isto: rm -rf / agora"
    a = FakeRunner("a", [perigo])
    b = FakeRunner("b", [perigo])
    out = arb.arbitrar("q", [a, b], rounds=1)
    assert out.decision.blocked is True
    assert out.failure_code is CouncilFailureCode.ARBITER_UNSAFE_OUTPUT


# 8. Desacordo alto ⇒ confiança baixa e clarificação exigida (nunca finge certeza)
def test_desacordo_alto_exige_clarificacao():
    a = FakeRunner("a", [TXT_A])
    b = FakeRunner("b", [TXT_A])           # concordam
    c = FakeRunner("c", [TXT_C])           # destoa totalmente (alucina)
    out = arb.arbitrar("q", [a, b, c], rounds=1)
    assert out.status == "ok"
    # há divergência entre o consenso (A/B) e o destoante (C)
    assert out.disagreement.level in {CouncilDisagreementLevel.MEDIUM,
                                      CouncilDisagreementLevel.HIGH}
    if out.disagreement.level is CouncilDisagreementLevel.HIGH:
        assert out.disagreement.requires_clarification is True
        assert out.decision.confidence is CouncilConfidence.LOW
    # o vencedor é do consenso, não o destoante
    assert out.decision.final_content == TXT_A


# 9. Esforço máximo: log registra available + run de cada motor (+retries)
def test_log_de_esforco_real():
    a = FakeRunner("a", [TXT_A])
    b = FakeRunner("b", [RuntimeError("e"), RuntimeError("e")])
    out = arb.arbitrar("q", [a, b], rounds=1, min_candidatos=1, max_retries=2)
    assert "a#available" in out.engines_tried
    assert "b#available" in out.engines_tried
    # o motor 'b' foi tentado 1+2 vezes (retries reais)
    assert out.engines_tried.count("b#run1") == 1
    assert "b#run3" in out.engines_tried          # max_retries=2 ⇒ 3 tentativas


# 10. Debate multi-rodada: motor revisa vendo os pares (re-execução real)
def test_debate_revisa_em_rodadas():
    # 'a' começa fraco e melhora na revisão; 'b' estável
    a = FakeRunner("a", ["curto", TXT_A])          # 2ª resposta usada na revisão
    b = FakeRunner("b", [TXT_B, TXT_B])
    out = arb.arbitrar("q", [a, b], rounds=2)
    assert out.rounds_run >= 2
    assert len(a.calls) >= 2                        # 'a' foi re-executado (revisão real)


# 11. Runner só participa se available()=True
def test_selecao_so_de_prontos():
    on = FakeRunner("on", [TXT_A], _ready=True)
    off = FakeRunner("off", [TXT_B], _ready=False)
    out = arb.arbitrar("q", [on, off], rounds=1, min_candidatos=1)
    assert out.engines_ready == ["on"]
    assert off.calls == []


# 12. Determinismo: mesma entrada ⇒ mesma decisão (auditável)
def test_deterministico():
    def novo():
        return [FakeRunner("a", [TXT_A]), FakeRunner("b", [TXT_B])]
    o1 = arb.arbitrar("q", novo(), rounds=1)
    o2 = arb.arbitrar("q", novo(), rounds=1)
    assert o1.decision.final_content == o2.decision.final_content
    assert o1.to_dict()["selected"] == o2.to_dict()["selected"]


# 13. Runners de produção existem e reportam indisponível no sandbox (sem inventar)
def test_runners_producao_indisponiveis_no_sandbox(tmp_path, monkeypatch):
    # força "sem Ollama" de forma determinística: o teste prova a HONESTIDADE
    # (indisponível ⇒ no_engine), e não pode depender de um Ollama aberto na
    # máquina do dev (na CI não há Ollama; localmente pode haver).
    from nomos.cognition import providers
    monkeypatch.setattr(providers.OllamaProvider, "available", lambda self: False)
    ol = arb.OllamaRunner()
    em = arb.EmbeddedRunner(home=tmp_path)
    # sem Ollama rodando e sem cérebro baixado, ambos indisponíveis — honesto
    assert ol.available() is False
    assert em.available() is False
    out = arb.arbitrar("q", [ol, em], rounds=1)
    assert out.status == "no_engine" and out.decision.final_content == ""


# 14. montar_runners_producao devolve motores locais reais
def test_montar_runners_producao(tmp_path):
    runners = arb.montar_runners_producao(tmp_path)
    ids = {r.engine_id for r in runners}
    assert ids == {"embutido", "ollama"}
    assert all(r.local for r in runners)      # local-first: nenhum cloud aqui


# 15. CLI: `nomos motores arbitrar` é honesto no sandbox (sem motor ⇒ exit 1, sem inventar)
@pytest.mark.skipif(_ollama_ativo(), reason="Ollama local ativo — este teste "
                    "prova o fail-closed SEM motor; sem sentido com um motor real")
def test_cli_arbitrar_honesto_no_sandbox(tmp_path):
    import subprocess
    import sys
    proc = subprocess.run(
        [sys.executable, "-m", "nomos", "motores", "arbitrar", "o que é local-first?"],
        capture_output=True, text=True, env=cli_env(tmp_path),
        cwd=str(Path(arb.__file__).resolve().parents[3]), timeout=60,
    )
    assert proc.returncode == 1                      # fail-closed: sem motor pronto
    assert "nada foi inventado" in proc.stdout
    assert "melhor resposta" not in proc.stdout      # jamais fabrica resposta
