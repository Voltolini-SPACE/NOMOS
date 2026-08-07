"""NOMOS agents.execucao — execução real das ferramentas da allowlist (F3).

Missão de eliminação de débitos residuais do Horizonte 3 (auditoria de
2026-07-17), Prioridade 1: fecha o gap documentado no item 1
(`AgentToolBoundary` wired, mas só para 5 das 8 ferramentas). Este módulo
agora cobre as 8: `memoria_buscar`, `arquivo_ler`, `arquivo_resumir`,
`arquivo_escrever`, `codigo_gerar`, `doutor`, `logs_verificar`,
`skill_rodar` — todas com efeito real quando autorizadas, e fail-closed
apenas por entrada inválida, permissão ausente, política negada ou falha
real de execução (nunca "ainda não implementada").

As funções `exec_*` eram, até esta rodada, privadas dentro de `cli.py` (só
tinham um caller). Extraídas para cá porque agora têm DOIS callers de
produção — `cli.py::cmd_agente_usar` (`nomos agentes usar`) e
`simple/amigavel.py::iniciar_chat` (oferta de agente por intenção na
conversa) — e mover evita duplicar a lógica de execução em dois módulos
(risco de divergência). Nenhuma regra de autorização mora aqui: quem decide
ALLOW/DENY/REQUIRE_APPROVAL continua sendo exclusivamente
`agents.boundary.AgentToolBoundary` + `kernel.policy` (intocados por esta
mudança) — este módulo só roda DEPOIS de autorizado.

Reaproveita primitivas já testadas em produção, nenhuma lógica de negócio
nova foi inventada:
  memoria_buscar   -> Memory.recall_hibrido (+ redact_text)
  arquivo_ler      -> cognition.arquivos.extrair_texto/extrair_pontos
  arquivo_resumir  -> cognition.arquivos.processar (mesmo EnginePipeline)
  arquivo_escrever -> escrita direta, restrita a NOMOS_HOME/workspace
                       (proteção própria contra path traversal/escrita fora
                       do workspace — ver `_resolver_destino_seguro`)
  codigo_gerar     -> cognition.router.Router.chat (mesmo motor local-first
                       do chat; NUNCA grava em disco — categoria A0)
  doutor           -> simple.doutor.texto_relatorio_v011
  logs_verificar   -> kernel.audit.AuditLog.verify
  skill_rodar      -> ext.skill_registry.executar_json (mesma primitiva
                       usada por `nomos skills usar` e pela oferta de skill
                       no chat — inclui seu próprio gate por permissão
                       declarada, ALÉM do gate do AgentToolBoundary: duas
                       perguntas de autorização distintas, defesa em
                       profundidade, não redundância acidental)
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable


def exec_memoria_buscar(ctx, alvo: str) -> str:
    if not alvo:
        return "informe --alvo com o que buscar na memória."
    from nomos.cognition.memory import Memory
    from nomos.kernel.audit import redact_text
    mem = Memory(ctx["home"] / "memory.db")
    itens = mem.recall_hibrido(alvo, k=5)
    if not itens:
        return "nenhuma memória encontrada."
    return "\n".join(f"[{it.id}] ({it.role}) {redact_text(it.text)}" for it in itens)


def exec_arquivo_ler(ctx, alvo: str) -> str:
    if not alvo:
        return "informe --alvo com o caminho do arquivo."
    from nomos.cognition import arquivos as arq
    texto, formato = arq.extrair_texto(Path(alvo))
    pontos = arq.extrair_pontos(texto)
    linhas = [f"(formato: {formato} · {len(texto)} caractere(s) lidos)"]
    if pontos:
        linhas.append("pontos:")
        linhas += [f"  - {p}" for p in pontos]
    return "\n".join(linhas)


def exec_arquivo_resumir(ctx, alvo: str, *, sem_motor: bool = False,
                         aprovador=None, router=None) -> str:
    if not alvo:
        return "informe --alvo com o caminho do arquivo."
    from nomos.cognition import arquivos as arq
    motor = None if sem_motor else router
    resultado, estado = arq.processar(alvo, ctx, aprovador, router=motor, salvar=False)
    if not resultado.ok:
        return f"não consegui: {resultado.motivo}"
    return arq.render_resultado(Path(alvo), estado)


class DestinoInseguroError(Exception):
    """`arquivo_escrever` recusou um caminho fora do workspace (path
    traversal ou escrita fora de NOMOS_HOME/workspace).

    É uma classe própria (não um ValueError genérico) de propósito: quando
    propaga através de `AgentToolBoundary.usar_ferramenta` (que converte
    QUALQUER exceção em `ferramenta '<nome>' falhou: <NomeDaClasse>`, sem
    alterar `agents/boundary.py`), o nome da classe sozinho já comunica a
    causa ao usuário final — mesmo com o detalhe completo (motivo, caminho,
    workspace) só visível para quem captura a exceção diretamente (testes
    desta unidade)."""


def _resolver_destino_seguro(home: Path, alvo: str) -> Path:
    """Caminho absoluto dentro de NOMOS_HOME/workspace, ou levanta
    `DestinoInseguroError`.

    `arquivo_escrever` só grava dentro de NOMOS_HOME/workspace — nunca em
    caminho arbitrário do sistema. Duas defesas, propositalmente redundantes
    (nenhuma sozinha é suficiente):
    - `alvo` absoluto: só aceito se JÁ estiver dentro do workspace (não
      "acopla" um caminho absoluto por baixo do workspace — armadilha
      clássica do `Path.__truediv__`, que DESCARTA o lado esquerdo quando o
      direito é absoluto);
    - `alvo` relativo: resolvido dentro do workspace e checado com
      `relative_to` sobre o caminho JÁ resolvido (segue `..`/symlink) —
      mesma técnica de defesa em profundidade usada em
      `ext.skill_registry.executar()` para o entrypoint da skill.

    Tratado como falha real (exceção -> EXIT_DENIED via boundary), não como
    "faltou argumento" (que aqui devolveria só uma string com EXIT_OK) —
    uma tentativa de escapar do workspace é uma recusa de segurança, e
    scripts/automação precisam distinguir isso por código de saída, não só
    por texto de stderr.
    """
    workspace = Path(home) / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    ws_resolvido = workspace.resolve()
    bruto = Path(alvo)
    candidato = bruto if bruto.is_absolute() else (workspace / bruto)
    try:
        destino = candidato.resolve()
        destino.relative_to(ws_resolvido)
    except ValueError:
        raise DestinoInseguroError(
            f"caminho recusado: '{alvo}' cairia fora do workspace "
            f"({workspace}) — arquivo_escrever só grava dentro dele "
            "(proteção contra path traversal/escrita fora do workspace)"
        ) from None
    return destino


def exec_arquivo_escrever(ctx, alvo: str, conteudo: str = "") -> str:
    if not alvo:
        return "informe --alvo com o caminho do arquivo a gravar (relativo ao workspace)."
    from nomos.kernel.plataforma import chmod_privado
    destino = _resolver_destino_seguro(Path(ctx["home"]), alvo)
    destino.parent.mkdir(parents=True, exist_ok=True)
    corpo = conteudo or ""
    destino.write_text(corpo, encoding="utf-8")
    chmod_privado(destino, 0o600)
    return f"gravado: {destino} ({len(corpo)} caractere(s))"


def exec_codigo_gerar(ctx, alvo: str, router=None) -> str:
    if not alvo:
        return "informe --alvo com o pedido (o que o código deve fazer)."
    if router is None:
        return ("não consegui gerar código: nenhum motor configurado — "
                "instale/inicie o Ollama local (`ollama pull qwen2.5-coder`) "
                "ou configure um endpoint compatível com OpenAI "
                "(NOMOS_OPENAI_COMPAT_BASE). codigo_gerar nunca inventa "
                "código sem motor.")
    mensagens = [
        {"role": "system", "content": (
            "Você é um assistente de programação do NOMOS. Gere código "
            "correto para o pedido a seguir, com uma explicação breve. "
            "Responda em português do Brasil no texto livre. Nunca afirme "
            "ter executado o código — você só o escreve.")},
        {"role": "user", "content": alvo},
    ]
    outcome = router.chat(mensagens)
    if not outcome.ok:
        return f"não consegui gerar código: {outcome.reason}"
    return outcome.text


def exec_doutor(ctx) -> str:
    from nomos.simple import doutor as dt
    return dt.texto_relatorio_v011(ctx["home"], ctx)


def exec_logs_verificar(ctx) -> str:
    ok, idx = ctx["audit"].verify()
    if ok:
        return "log de auditoria íntegro (cadeia de hash verificada)."
    return f"log de auditoria comprometido a partir do registro {idx}."


def exec_skill_rodar(ctx, alvo: str, aprovador=None) -> str:
    if not alvo:
        return "informe --alvo com o nome da skill instalada."
    from nomos.ext import skill_intencao as intencao
    from nomos.ext import skill_registry as reg
    from nomos.ext import skill_status as st
    skills_dir = ctx.get("skills") or (Path(ctx["home"]) / "skills")
    rc, resultado, bruto = reg.executar_json(alvo, skills_dir, ctx["policy"],
                                             aprovador, argumentos=None,
                                             audit=ctx.get("audit"))
    if rc == 0:
        st.marcar_uso(ctx["home"], alvo)
        return intencao.render_resultado_skill(alvo, resultado, bruto)
    return bruto.strip() or f"a skill '{alvo}' falhou (rc={rc})"


def ferramentas_wired(ctx, *, alvo: str = "", conteudo: str = "",
                      sem_motor: bool = False, aprovador=None,
                      router=None) -> dict[str, Callable[[], str]]:
    """Dispatch das 8 ferramentas da allowlist — todas com execução real.

    `router` só é necessário para `arquivo_resumir` (quando não `sem_motor`)
    e `codigo_gerar`; passar `None` faz essas duas caírem no caminho
    fail-closed próprio (heurística local ou mensagem de motor ausente),
    nunca em exceção não tratada."""
    return {
        "memoria_buscar": lambda: exec_memoria_buscar(ctx, alvo),
        "arquivo_ler": lambda: exec_arquivo_ler(ctx, alvo),
        "arquivo_resumir": lambda: exec_arquivo_resumir(
            ctx, alvo, sem_motor=sem_motor, aprovador=aprovador, router=router),
        "arquivo_escrever": lambda: exec_arquivo_escrever(ctx, alvo, conteudo),
        "codigo_gerar": lambda: exec_codigo_gerar(ctx, alvo, router),
        "doutor": lambda: exec_doutor(ctx),
        "logs_verificar": lambda: exec_logs_verificar(ctx),
        "skill_rodar": lambda: exec_skill_rodar(ctx, alvo, aprovador),
    }
