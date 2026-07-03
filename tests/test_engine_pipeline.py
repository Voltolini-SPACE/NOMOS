"""Fase 5 — pipeline de motores: política em cada etapa, falha honesta."""
from nomos.cognition.engine_pipeline import (EnginePipeline, PipelineAudit,
                                             PipelineStep)
from nomos.kernel.policy import Category, PolicyEngine


def _engine(nomos_home):
    return PolicyEngine(nomos_home / "policy.json")


def test_pipeline_feliz_todo_local(nomos_home):
    passos = [
        PipelineStep("transcrever", "whisper", Category.READ_LOCAL,
                     executar=lambda x: f"[transcrito]{x}"),
        PipelineStep("resumir", "embutido", Category.READ_LOCAL,
                     executar=lambda x: f"[resumo]{x}"),
    ]
    r = EnginePipeline(passos, _engine(nomos_home), approver=None).run("audio")
    assert r.ok and r.saida == "[resumo][transcrito]audio"
    assert len(r.etapas_executadas) == 2
    assert "Nada saiu da sua máquina" in r.explicacao


def test_para_no_primeiro_bloqueio_sem_executar_o_resto(nomos_home):
    executadas = []
    passos = [
        PipelineStep("ler", "memoria-local", Category.READ_LOCAL,
                     executar=lambda x: executadas.append("ler") or x),
        PipelineStep("gravar", "memoria-local", Category.WRITE_LOCAL,
                     executar=lambda x: executadas.append("gravar") or x),
        PipelineStep("depois", "embutido", Category.READ_LOCAL,
                     executar=lambda x: executadas.append("depois") or x),
    ]
    # sem aprovador: A1 exige aprovação => nega => pipeline PARA na etapa 2
    r = EnginePipeline(passos, _engine(nomos_home), approver=None).run("x")
    assert r.ok is False and r.etapa_falhou == "gravar"
    assert executadas == ["ler"]          # a etapa 3 nunca rodou
    assert "negada" in r.motivo


def test_aprovacao_humana_libera_etapa_sensivel(nomos_home):
    passos = [PipelineStep("gravar", "memoria-local", Category.WRITE_LOCAL,
                           executar=lambda x: x + "!")]
    r = EnginePipeline(passos, _engine(nomos_home),
                       approver=lambda d: True).run("ok")
    assert r.ok and r.saida == "ok!"


def test_nada_pula_aprovacao_nem_com_erro_no_aprovador(nomos_home):
    def aprovador_bugado(decision):
        raise RuntimeError("aprovador quebrou")
    passos = [PipelineStep("gravar", "m", Category.WRITE_LOCAL, lambda x: x)]
    r = EnginePipeline(passos, _engine(nomos_home), aprovador_bugado).run("x")
    assert r.ok is False   # erro no aprovador NUNCA autoriza


def test_egress_bloqueado_pelo_cadeado_mesmo_aprovando(nomos_home):
    passos = [PipelineStep("chamar-nuvem", "anthropic", Category.NET_EGRESS,
                           executar=lambda x: x, local=False)]
    r = EnginePipeline(passos, _engine(nomos_home),
                       approver=lambda d: True).run("x")
    assert r.ok is False and "negada" in r.motivo   # DENY da política, sem apelação


def test_erro_na_etapa_e_falha_honesta(nomos_home):
    def explode(x):
        raise ValueError("motor caiu")
    passos = [PipelineStep("processar", "embutido", Category.READ_LOCAL, explode)]
    r = EnginePipeline(passos, _engine(nomos_home), None).run("x")
    assert r.ok is False and r.etapa_falhou == "processar"
    assert "interrompi" in r.explicacao


def test_auditoria_guarda_metadados_nunca_conteudo(nomos_home):
    aud = PipelineAudit()
    aud.registrar("etapa.concluida", etapa="resumir", motor="embutido",
                  conteudo="SEGREDO-DO-USUARIO", texto="privado", rc=0)
    ev = aud.eventos[0]
    assert ev["etapa"] == "resumir" and ev["rc"] == 0
    assert "conteudo" not in ev and "texto" not in ev
    assert "SEGREDO-DO-USUARIO" not in str(aud.eventos)


def test_pipeline_registra_decisoes_na_auditoria(nomos_home):
    passos = [PipelineStep("ler", "memoria-local", Category.READ_LOCAL,
                           lambda x: x)]
    p = EnginePipeline(passos, _engine(nomos_home), None)
    p.run("dados-privados-do-usuario")
    eventos = [e["evento"] for e in p.audit.eventos]
    assert "etapa.decidida" in eventos and "concluido" in eventos
    assert "dados-privados-do-usuario" not in str(p.audit.eventos)
