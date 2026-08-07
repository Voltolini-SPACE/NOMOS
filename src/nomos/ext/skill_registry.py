"""NOMOS ext.skill_registry — manifesto v2, risco, catálogo local e execução governada.

Conceitos (v0.11):
- skill INSTALADA: está em NOMOS_HOME/skills;
- skill DISPONÍVEL: consta no catálogo local (registry/catalogo.json), ainda não instalada;
- skill CONFIÁVEL: assinada por publicador presente no trust store;
- skill EXPERIMENTAL: não assinada ou de risco alto — exige confirmação extra.

Manifesto v2 (skill.json) — v1 continua aceito; campos novos são opcionais e
normalizados com padrões seguros:
  name, version, description, entrypoint (alias de entry), permissions,
  risk_level, requires_approval, publisher, signature?, compatible_nomos_version,
  modalities, local_only_capable, cloud_required.

Garantias:
- sem manifesto válido não instala (herdado de ext.skills + validação v2);
- permissão não declarada não executa: a execução governada só concede o que
  o manifesto declara, e cada categoria passa pelo gate da política;
- rede => gate A2_NET_EGRESS (cai no cadeado só-local); arquivo => A1; código => A5;
- risco alto => aprovação humana explícita; em CI/não-interativo o gate nega.
"""
from __future__ import annotations

import json
from pathlib import Path

from nomos.ext import skills as _skills
from nomos.kernel.policy import Category, PolicyEngine, gate

RISCOS = ("baixo", "medio", "alto")
_PERMS_ALTAS = {Category.NET_EGRESS.value, Category.CRED_USE.value,
                Category.CONNECTOR_USE.value, Category.CODE_EXEC.value,
                Category.DESTRUCTIVE.value}
_PERMS_MEDIAS = {Category.WRITE_LOCAL.value, Category.DEVICE_MIC.value,
                 Category.DEVICE_CAM.value, Category.DEVICE_SCREEN.value,
                 Category.SKILL_INSTALL.value}

MODALIDADES_SKILL = ("texto", "voz", "imagem", "arquivo", "web")


class RegistroError(Exception):
    pass


# ------------------------- risco e normalização -------------------------

def risco_de(permissions: list[str]) -> str:
    """Risco derivado das permissões declaradas (fail-closed: desconhecida = alto)."""
    conhecidas = {c.value for c in Category}
    if any(p not in conhecidas for p in permissions):
        return "alto"
    if any(p in _PERMS_ALTAS for p in permissions):
        return "alto"
    if any(p in _PERMS_MEDIAS for p in permissions):
        return "medio"
    return "baixo"


def normalizar_manifesto(mf: dict) -> dict:
    """Preenche os campos v2 com padrões seguros, sem alterar o arquivo original."""
    out = dict(mf)
    out.setdefault("description", "")
    out.setdefault("entrypoint", out.get("entry", ""))
    out.setdefault("entry", out.get("entrypoint", ""))
    perms = list(out.get("permissions", []))
    out.setdefault("risk_level", risco_de(perms))
    # requires_approval nunca pode ser "afrouxado" pelo manifesto: se o risco
    # calculado exigir aprovação, a declaração do autor não desliga isso.
    calculado = risco_de(perms) != "baixo"
    out["requires_approval"] = bool(out.get("requires_approval", False)) or calculado
    sig = out.get("signature")
    out.setdefault("publisher", (sig or {}).get("publisher", "desconhecido")
                   if isinstance(sig, dict) else "desconhecido")
    out.setdefault("compatible_nomos_version", ">=0.10")
    out.setdefault("modalities", ["texto"])
    out.setdefault("keywords", [])
    out.setdefault("local_only_capable", True)
    out.setdefault("cloud_required", False)
    return out


def validar_manifesto(mf: dict) -> list[str]:
    """Valida um manifesto (v1 ou v2). Devolve lista de problemas (vazia = ok)."""
    problemas: list[str] = []
    for campo in ("name", "version", "permissions", "files"):
        if campo not in mf:
            problemas.append(f"campo obrigatório ausente: {campo}")
    if not mf.get("entry") and not mf.get("entrypoint"):
        problemas.append("campo obrigatório ausente: entry/entrypoint")
    conhecidas = {c.value for c in Category}
    for p in mf.get("permissions", []):
        if p not in conhecidas:
            problemas.append(f"permissão desconhecida: {p}")
    if "risk_level" in mf and mf["risk_level"] not in RISCOS:
        problemas.append(f"risk_level inválido: {mf['risk_level']!r} (use baixo/medio/alto)")
    if "modalities" in mf:
        for m in mf["modalities"]:
            if m not in MODALIDADES_SKILL:
                problemas.append(f"modalidade desconhecida: {m}")
    if "keywords" in mf:
        if not isinstance(mf["keywords"], list) or \
                any(not isinstance(k, str) for k in mf["keywords"]):
            problemas.append("keywords deve ser uma lista de textos")
    if mf.get("cloud_required") and mf.get("local_only_capable"):
        problemas.append("manifesto contraditório: cloud_required com local_only_capable")
    return problemas


# ------------------------- catálogo local -------------------------

def _caminho_catalogo(home: Path) -> Path:
    return Path(home) / "registry" / "catalogo.json"


def catalogo(home: Path) -> list[dict]:
    """Skills DISPONÍVEIS no catálogo local (lista vazia se não houver)."""
    return catalogo_info(home)[0]


def catalogo_info(home: Path, trust=None) -> tuple[list[dict], bool, str]:
    """(skills, assinado, publicador). Catálogo com assinatura INVÁLIDA é
    descartado inteiro (fail-closed) — melhor nada do que catálogo adulterado."""
    p = _caminho_catalogo(home)
    if not p.exists():
        return [], False, ""
    try:
        data = json.loads(p.read_text())
        itens = data.get("skills", [])
        skills = [normalizar_manifesto(i) for i in itens if isinstance(i, dict)]
    except Exception:
        return [], False, ""   # corrompido: fail-closed
    if "signature" in data:
        if trust is None:
            from nomos.ext.signing import TrustStore
            trust = TrustStore(Path(home) / "trust.json")
        try:
            from nomos.ext.signing import verify_signed_manifest
            publicador = verify_signed_manifest(data, trust)
            return skills, True, publicador
        except Exception:
            return [], False, ""   # assinatura ruim: catálogo inteiro fora
    return skills, False, ""


def atualizacoes_disponiveis(home: Path, skills_dir: Path) -> list[dict]:
    """Skills instaladas com versão mais nova no catálogo local.

    Só INFORMA — instalar continua sendo decisão manual, com gate."""
    from nomos.simple.atualizar import comparar_versoes
    instaladas = {i["name"]: i["version"]
                  for i in _skills.list_installed(Path(skills_dir))}
    novidades = []
    for entrada in catalogo(home):
        nome = entrada.get("name")
        if nome in instaladas and comparar_versoes(
                instaladas[nome], entrada.get("version", "0")) < 0:
            novidades.append({"name": nome, "instalada": instaladas[nome],
                              "disponivel": entrada.get("version"),
                              "risco": entrada.get("risk_level", "?")})
    return novidades


def adicionar_ao_catalogo(home: Path, entrada: dict) -> dict:
    """Registra uma skill como disponível no catálogo local (não instala)."""
    problemas = [p for p in validar_manifesto(entrada)
                 if "files" not in p]   # catálogo aceita entrada sem checksums
    if problemas:
        raise RegistroError("entrada inválida para o catálogo: " + "; ".join(problemas))
    p = _caminho_catalogo(home)
    p.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, list[dict]] = {"skills": []}
    if p.exists():
        try:
            data = json.loads(p.read_text())
        except Exception:
            data = {"skills": []}
    skills = [s for s in data.get("skills", []) if s.get("name") != entrada.get("name")]
    skills.append(entrada)
    data["skills"] = skills
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    return normalizar_manifesto(entrada)


def disponiveis(home: Path, skills_dir: Path) -> list[dict]:
    """Catálogo menos as já instaladas."""
    instaladas = {i["name"] for i in _skills.list_installed(Path(skills_dir))}
    return [c for c in catalogo(home) if c["name"] not in instaladas]


# ------------------------- instalação v2 -------------------------

def instalar(src: Path, skills_dir: Path, engine: PolicyEngine, approver,
             trust=None, confirmar_experimental=None) -> dict:
    """Instala com validação v2 + regras de risco. Delega a ext.skills.install
    (checksum, assinatura, gate) — nenhum caminho novo de autorização.

    - manifesto inválido => RegistroError (não instala);
    - risco ALTO ou não assinada (experimental) => exige `confirmar_experimental`
      verdadeiro além do gate normal; ausência de confirmador => nega (fail-closed).
    """
    src = Path(src)
    mf_path = src / "skill.json"
    if not mf_path.exists():
        raise RegistroError("manifesto skill.json ausente")
    try:
        bruto = json.loads(mf_path.read_text())
    except Exception as exc:
        raise RegistroError(f"manifesto ilegível: {exc}") from None
    problemas = validar_manifesto(bruto)
    if problemas:
        raise RegistroError("manifesto inválido: " + "; ".join(problemas))
    mf = normalizar_manifesto(bruto)

    experimental = mf["risk_level"] == "alto" or "signature" not in bruto
    if experimental:
        if confirmar_experimental is None:
            raise RegistroError(
                "skill experimental (risco alto ou não assinada) exige "
                "confirmação extra — negada por padrão")
        try:
            if not bool(confirmar_experimental(mf)):
                raise RegistroError("instalação experimental não confirmada")
        except RegistroError:
            raise
        except Exception:
            raise RegistroError("confirmador falhou — negado (fail-closed)") from None

    # NÃO reescrevemos o skill.json: `_skills.load_manifest` já aceita
    # `entrypoint` como alias de `entry`. Reescrever o arquivo invalidaria a
    # assinatura (verificada sobre o corpo original) e alteraria o diretório
    # de origem do autor.
    instalado = _skills.install(src, Path(skills_dir), engine, approver, trust=trust)
    return normalizar_manifesto(instalado)


# ------------------------- execução governada -------------------------

_CATEGORIAS_EXECUCAO = [c.value for c in Category if c is not Category.READ_LOCAL]


def preparar_execucao(mf: dict, engine: PolicyEngine, approver) -> tuple[bool, str]:
    """Passa cada permissão declarada (além de A0) pelo gate da política.

    Devolve (ok, motivo). Nenhuma permissão declarada além de A0 => ok direto,
    mas a skill não ganha NADA além de leitura local.
    """
    mf = normalizar_manifesto(mf)
    for perm in mf.get("permissions", []):
        if perm == Category.READ_LOCAL.value:
            continue
        if perm not in _CATEGORIAS_EXECUCAO:
            return False, f"permissão desconhecida: {perm}"
        decision = engine.decide(perm, target=f"skill:{mf.get('name')}")
        if not gate(decision, approver):
            return False, (f"permissão {perm} negada para a skill "
                           f"'{mf.get('name')}' ({decision.reason})")
    return True, "todas as permissões declaradas foram autorizadas"


def executar(name: str, skills_dir: Path, engine: PolicyEngine, approver,
             audit=None, timeout: int = 30, sandbox_run=None,
             argumentos: dict | None = None) -> tuple[int, str]:
    """Executa a skill instalada de forma governada.

    Regras:
    - manifesto da skill instalada é revalidado (quebrada não roda);
    - permissões declaradas passam pelo gate uma a uma (rede => A2 cai no
      cadeado só-local; nada de permissão implícita);
    - o entry roda no sandbox; rede só é liberada se A2 foi declarada E aprovada.
    Devolve (rc, saida). rc=3 quando negado.
    """
    dest = Path(skills_dir) / name
    mf_path = dest / "skill.json"
    if not mf_path.exists():
        return 3, f"skill '{name}' não está instalada"
    try:
        mf = json.loads(mf_path.read_text())
        problemas = validar_manifesto(mf)
    except Exception:
        problemas = ["manifesto ilegível"]
    if problemas:
        return 3, f"skill '{name}' quebrada: " + "; ".join(problemas)
    mfn = normalizar_manifesto(mf)

    ok, motivo = preparar_execucao(mfn, engine, approver)
    if not ok:
        if audit is not None:
            audit.append("skill.execucao.negada", name=name, motivo=motivo)
        return 3, motivo

    entry = dest / mfn["entry"]
    # Defesa em profundidade: mesmo que o skill.json instalado seja editado
    # depois, o entry NUNCA pode escapar do diretório da skill (traversal/absoluto).
    try:
        entry.resolve().relative_to(dest.resolve())
    except ValueError:
        if audit is not None:
            audit.append("skill.execucao.negada", name=name, motivo="entry fora do diretório")
        return 3, f"entry inseguro (fora do diretório da skill): {mfn['entry']!r}"
    if not entry.exists():
        return 3, f"entry ausente: {mfn['entry']}"
    quer_rede = Category.NET_EGRESS.value in mfn.get("permissions", [])
    if sandbox_run is None:
        from nomos.runtime import sandbox as _sb
        sandbox_run = lambda cmd, **kw: _sb.run(cmd, **kw)

    # argv como LISTA (sem shell): elimina injeção via aspas/`;`/`$` num nome
    # de entry que passe em _rel_segura mas contenha metacaracteres de shell
    cmd = ["python3", str(entry)]
    args_path = None
    if argumentos is not None:
        import os
        import time as _t
        args_dir = Path(skills_dir).parent / "sandbox"
        args_dir.mkdir(parents=True, exist_ok=True)
        args_path = args_dir / f"skill-args-{name}-{os.getpid()}-{int(_t.time())}.json"
        args_path.write_text(json.dumps(argumentos, ensure_ascii=False),
                             encoding="utf-8")
        cmd = ["python3", str(entry), str(args_path)]
    try:
        r = sandbox_run(cmd, timeout=timeout, allow_network=quer_rede)
    except Exception as exc:
        if audit is not None:
            audit.append("skill.execucao.falhou", name=name, motivo=type(exc).__name__)
        return 1, f"execução indisponível: {exc}"
    finally:
        if args_path is not None:
            try:
                args_path.unlink()
            except OSError:
                pass   # arquivo de args é efêmero; sobra é inofensiva e local
    if audit is not None:
        audit.append("skill.executada", name=name, rc=r.rc,
                     permissions=mfn.get("permissions", []),
                     com_argumentos=argumentos is not None)
    return r.rc, r.stdout


def executar_json(name: str, skills_dir: Path, engine: PolicyEngine, approver,
                  argumentos: dict | None = None, **kw) -> tuple[int, dict | None, str]:
    """Executa e tenta interpretar a ÚLTIMA linha JSON do stdout.

    Devolve (rc, resultado|None, saida_bruta). JSON ausente/ilegível não é
    erro fatal: resultado=None e a saída bruta fica disponível."""
    rc, saida = executar(name, skills_dir, engine, approver,
                         argumentos=argumentos, **kw)
    resultado = None
    for linha in reversed([ln for ln in saida.splitlines() if ln.strip()]):
        try:
            candidato = json.loads(linha)
            if isinstance(candidato, dict):
                resultado = candidato
            break
        except ValueError:
            break
    return rc, resultado, saida
