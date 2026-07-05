"""MC24 — Contrato ÚNICO de flags proibidas do Conselho dry-run (CLI + chat).

Prova a reconciliação (decisão A): CLI e chat compartilham exatamente o MESMO
conjunto de 10 flags proibidas, servido por uma fonte única e testável
(`nomos.council.forbidden_flags`). Cobre: cada flag bloqueada nas duas
superfícies (parametrizado), combinações de flags proibidas, ausência de falso
positivo em flags parecidas, mensagens humanas sem jargão, JSON técnico com a
estrutura segura preservada, não-comando no chat continua `None`, CLI/chat não
executam nada, paridade CLI↔chat, e guardas AST contra (a) reintrodução da
divergência e (b) volta a serialização perigosa.
"""
import ast
import io
import json

import pytest

from nomos import cli
from nomos.council import chat_dry_run, cli_dry_run
from nomos.council import forbidden_flags as ff

_SENSIVEL = "PROMPT-SENSIVEL-mc24-909-nao-pode-vazar"

# As 10 flags proibidas do contrato reconciliado (decisão A).
_ESPERADAS_10 = (
    "--real", "--enable", "--ativar", "--force", "--unsafe", "--cloud",
    "--audit-real", "--policy-real", "--vault-real", "--engine-real",
)

# As 2 que a CLL NÃO listava antes da MC24 (divergência agora eliminada).
_NOVAS_NA_CLI = ("--vault-real", "--engine-real")

# Flags PARECIDAS, porém legítimas (não proibidas): não podem casar por
# prefixo/substring nem por caixa alta. Continuam recusadas como *desconhecidas*
# pelo parser de cada superfície — mas nunca como *proibidas*.
_PARECIDAS_NAO_PROIBIDAS = (
    "--realmente", "--reals", "--real-time", "--REAL", "--enabled", "--enables",
    "--cloudy", "--forcado", "--unsafely", "--vault", "--engine", "--policy",
    "--audit", "--ativado",
)

_JARGAO = ("orchestrator", "orquestrador", "envelope", "scalar", "payload",
           "safe output", "safe_output", "policy dry-run", "failure_code",
           "to_dict", "CouncilSafeOutput", "frozenset", "forbidden")


@pytest.fixture(autouse=True)
def _nao_interativo(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    yield


def _run(capsys, *argv):
    rc = cli.main(list(argv))
    out = capsys.readouterr().out
    return rc, out


def _h(msg):
    return chat_dry_run.handle_chat_dry_run(msg)


# --------------------------------------------------------------------------
# 1. Contrato — fonte única (`forbidden_flags`)
# --------------------------------------------------------------------------

def test_contract_has_exactly_the_ten_flags():
    assert ff.FORBIDDEN_FLAGS == frozenset(_ESPERADAS_10)
    assert len(ff.FORBIDDEN_FLAGS) == 10


def test_contract_is_immutable_frozenset():
    assert isinstance(ff.FORBIDDEN_FLAGS, frozenset)
    with pytest.raises(AttributeError):
        ff.FORBIDDEN_FLAGS.add("--nova")  # frozenset não tem .add


@pytest.mark.parametrize("flag", _ESPERADAS_10)
def test_is_forbidden_flag_true_for_each(flag):
    assert ff.is_forbidden_flag(flag) is True


@pytest.mark.parametrize("flag", _PARECIDAS_NAO_PROIBIDAS)
def test_is_forbidden_flag_no_false_positive(flag):
    assert ff.is_forbidden_flag(flag) is False


def test_is_forbidden_flag_ignores_non_strings_safely():
    for valor in (None, 42, "", "texto", "--"):
        assert ff.is_forbidden_flag(valor) is False


def test_find_forbidden_returns_first_in_combo():
    assert ff.find_forbidden(["texto", "--force", "--real"]) == "--force"
    assert ff.find_forbidden(["--engine-real", "--vault-real"]) == "--engine-real"


def test_find_forbidden_returns_none_when_clean():
    assert ff.find_forbidden(["texto", "--json", "--privado"]) is None
    assert ff.find_forbidden([]) is None
    assert ff.find_forbidden(None) is None


# --------------------------------------------------------------------------
# 2. Paridade CLI ↔ chat (decisão A) + guarda anti-divergência
# --------------------------------------------------------------------------

def test_parity_same_shared_object_identity():
    # A prova mais forte da decisão A: as duas superfícies apontam para o MESMO
    # objeto do contrato (não cópias que poderiam divergir de novo).
    assert cli_dry_run.FORBIDDEN_FLAGS is ff.FORBIDDEN_FLAGS
    assert chat_dry_run.FORBIDDEN_FLAGS is ff.FORBIDDEN_FLAGS
    assert cli_dry_run._FORBIDDEN_FLAGS is chat_dry_run._FORBIDDEN_FLAGS


def test_parity_cli_and_chat_sets_are_equal_and_ten():
    assert set(cli_dry_run._FORBIDDEN_FLAGS) == set(chat_dry_run._FORBIDDEN_FLAGS)
    assert set(cli_dry_run._FORBIDDEN_FLAGS) == frozenset(_ESPERADAS_10)


def test_parity_cli_gained_the_two_previously_chat_only_flags():
    for flag in _NOVAS_NA_CLI:
        assert flag in cli_dry_run._FORBIDDEN_FLAGS, flag


# --------------------------------------------------------------------------
# 3. CLI — cada flag proibida bloqueia fail-closed (parametrizado)
# --------------------------------------------------------------------------

@pytest.mark.parametrize("flag", _ESPERADAS_10)
def test_cli_each_forbidden_flag_denied(capsys, flag):
    rc, out = _run(capsys, "conselho", "simular", _SENSIVEL, flag)
    assert cli_dry_run.DENIED_CODE in out, flag
    assert rc == cli_dry_run.DENIED_EXIT_CODE, flag
    assert _SENSIVEL not in out, flag
    assert flag not in out, flag  # a flag nunca é ecoada de volta


def test_cli_forbidden_flag_before_prompt_also_denied(capsys):
    rc, out = _run(capsys, "conselho", "simular", "--vault-real", _SENSIVEL)
    assert cli_dry_run.DENIED_CODE in out
    assert rc == cli_dry_run.DENIED_EXIT_CODE
    assert _SENSIVEL not in out


def test_cli_combination_of_forbidden_flags_denied(capsys):
    rc, out = _run(capsys, "conselho", "simular", _SENSIVEL, "--real", "--force", "--cloud")
    assert cli_dry_run.DENIED_CODE in out
    assert rc == cli_dry_run.DENIED_EXIT_CODE
    assert _SENSIVEL not in out
    for flag in ("--real", "--force", "--cloud"):
        assert flag not in out


def test_cli_similar_flag_denied_as_unknown_not_forbidden(capsys):
    # Falso positivo proibido: uma flag PARECIDA é recusada como *desconhecida*
    # (mensagem "não existe"), nunca como *proibida* ("não pode ser usado").
    rc, out = _run(capsys, "conselho", "simular", _SENSIVEL, "--realmente")
    assert cli_dry_run.DENIED_CODE in out
    assert "não existe" in out
    assert "não pode ser usado" not in out
    assert rc == cli_dry_run.DENIED_EXIT_CODE
    assert _SENSIVEL not in out


def test_cli_forbidden_flag_does_not_execute_or_build_paths(capsys, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("_paths/execução real não pode ser tocado por flag proibida")

    monkeypatch.setattr(cli, "_paths", boom)
    rc, out = _run(capsys, "conselho", "simular", _SENSIVEL, "--engine-real")
    assert cli_dry_run.DENIED_CODE in out
    assert rc == cli_dry_run.DENIED_EXIT_CODE


def test_cli_forbidden_flag_message_has_no_jargon(capsys):
    rc, out = _run(capsys, "conselho", "simular", _SENSIVEL, "--vault-real")
    baixo = out.lower()
    for termo in _JARGAO:
        assert termo.lower() not in baixo, termo


def test_cli_forbidden_flag_emits_no_json_keys(capsys):
    # A recusa é uma mensagem humana simples; não vaza a estrutura técnica.
    rc, out = _run(capsys, "conselho", "simular", _SENSIVEL, "--policy-real", "--json")
    for chave in ("would_execute", "persist_allowed", "failure_code", "interface"):
        assert chave not in out, chave


# --------------------------------------------------------------------------
# 4. Chat — cada flag proibida bloqueia fail-closed (parametrizado)
# --------------------------------------------------------------------------

@pytest.mark.parametrize("flag", _ESPERADAS_10)
def test_chat_each_forbidden_flag_denied(flag):
    out = _h(f"/conselho simular {_SENSIVEL} {flag}")
    assert chat_dry_run.DENIED_CODE in out, flag
    assert _SENSIVEL not in out, flag
    assert flag not in out, flag


def test_chat_combination_of_forbidden_flags_denied():
    out = _h(f"/conselho simular {_SENSIVEL} --engine-real --vault-real")
    assert chat_dry_run.DENIED_CODE in out
    assert _SENSIVEL not in out
    assert "--engine-real" not in out
    assert "--vault-real" not in out


def test_chat_similar_flag_denied_as_unknown_not_forbidden():
    out = _h(f"/conselho simular {_SENSIVEL} --cloudy")
    assert chat_dry_run.DENIED_CODE in out
    assert "não existe" in out
    assert "não pode ser usado" not in out
    assert _SENSIVEL not in out


def test_chat_forbidden_flag_message_has_no_jargon():
    baixo = _h(f"/conselho simular {_SENSIVEL} --engine-real").lower()
    for termo in _JARGAO:
        assert termo.lower() not in baixo, termo


def test_chat_non_command_still_returns_none_after_reconciliation():
    for msg in ("oi", "/ajuda", "/conselhoxyz", "conselho sem barra", "",
                "   ", 42, None):
        assert chat_dry_run.handle_chat_dry_run(msg) is None


def test_chat_forbidden_flag_does_not_call_orchestrator(monkeypatch):
    from nomos.council import orchestrator as orch

    def boom(self, entrada):
        raise AssertionError("orquestrador não pode rodar sob flag proibida")

    monkeypatch.setattr(orch.CouncilOrchestratorDryRun, "run", boom)
    out = _h(f"/conselho simular {_SENSIVEL} --real")
    assert chat_dry_run.DENIED_CODE in out
    assert _SENSIVEL not in out


# --------------------------------------------------------------------------
# 5. JSON técnico (estrutura segura) preservado no caminho permitido
# --------------------------------------------------------------------------

def test_cli_allowed_json_keeps_safe_shape():
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cli.main(["conselho", "simular", "texto", "--json"])
    payload = json.loads(buf.getvalue().strip())
    assert set(payload.keys()) == {
        "interface", "dry_run", "allowed", "blocked", "would_execute",
        "would_write_audit", "private_mode", "persist_allowed", "failure_code",
        "mode",
    }
    assert payload["interface"] == "cli"


def test_chat_allowed_json_keeps_safe_shape():
    payload = json.loads(_h("/conselho simular texto --json"))
    assert set(payload.keys()) == {
        "interface", "dry_run", "allowed", "blocked", "would_execute",
        "would_write_audit", "private_mode", "persist_allowed", "failure_code",
        "mode",
    }
    assert payload["interface"] == "chat"


# --------------------------------------------------------------------------
# 6. Pureza/segurança por AST do módulo de contrato
# --------------------------------------------------------------------------

def _imports_of(module):
    src = open(module.__file__, encoding="utf-8").read()
    nomes = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            nomes.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            nomes.add(node.module)
    return nomes


def _src_of(module):
    return open(module.__file__, encoding="utf-8").read()


def test_contract_module_does_not_import_network_subprocess_cloud_kernel():
    usados = _imports_of(ff)
    proibidos = {"socket", "ssl", "http", "http.client", "urllib",
                 "urllib.request", "requests", "httpx", "aiohttp",
                 "subprocess", "threading", "multiprocessing", "asyncio",
                 "concurrent.futures", "signal", "os", "sys", "json"}
    assert not (usados & proibidos), usados & proibidos
    prefixos = ("openai", "anthropic", "google", "boto3", "azure", "ollama",
                "nomos.kernel", "nomos.council.local_harness", "nomos.cognition",
                "nomos.runtime", "nomos.agents", "nomos.ext")
    ruins = [m for m in usados if any(m == p or m.startswith(p + ".") for p in prefixos)]
    assert not ruins, ruins


def test_contract_module_does_not_touch_fs_env_time_random():
    src = _src_of(ff)
    for proibido in ("open(", "environ", "getenv", "write_text", "write_bytes",
                     ".now(", "random.", "time."):
        assert proibido not in src, proibido


def test_contract_module_has_no_dangerous_serialization():
    src = _src_of(ff)
    for proibido in (".to_dict(", "repr(", "vars(", "asdict", "json.dumps("):
        assert proibido not in src, proibido


# --------------------------------------------------------------------------
# 7. Guarda AST — CLI/chat consomem a fonte única e NÃO hardcodam a lista
# --------------------------------------------------------------------------

@pytest.mark.parametrize("module", [cli_dry_run, chat_dry_run])
def test_surface_imports_the_shared_contract(module):
    assert "nomos.council.forbidden_flags" in _imports_of(module)


def _string_constants(module):
    """Todos os literais str no AST do módulo (ignora comentários `#`)."""
    valores = set()
    for node in ast.walk(ast.parse(_src_of(module))):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            valores.add(node.value)
    return valores


@pytest.mark.parametrize("module", [cli_dry_run, chat_dry_run])
def test_surface_does_not_hardcode_flag_literals(module):
    # Nenhuma das superfícies pode reintroduzir a divergência hardcodando as
    # flags: o literal de nenhuma flag do contrato pode existir como constante de
    # código (só a fonte única `forbidden_flags` as declara). Comentários que
    # citam as flags para documentar a mudança são ignorados (não estão no AST).
    hardcoded = _string_constants(module) & ff.FORBIDDEN_FLAGS
    assert not hardcoded, f"{module.__name__} hardcoda {sorted(hardcoded)}"
