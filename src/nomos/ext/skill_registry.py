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


def semear_catalogo(home: Path, origem: Path) -> dict:
    """Popula o catálogo local a partir de uma PASTA de skills no disco.

    Por que isto existe: `catalogo_info` foi desenhado para consumir um catálogo
    que chega de fora, ASSINADO por um publicador do trust store — por isso
    `adicionar_ao_catalogo` nunca teve chamador de produção. O efeito colateral
    é que, sem nenhum catálogo distribuído, a lista de "skills disponíveis para
    instalar" nasce VAZIA e não há caminho para enchê-la.

    Esta função é esse caminho, e não afrouxa nada:
      * as entradas entram NÃO ASSINADAS — `catalogo_info` continua reportando
        "catálogo local NÃO assinado", que já é um estado de primeira classe;
      * constar no catálogo é só ficar VISÍVEL. Instalar continua passando pelas
        duas barreiras de sempre: confirmação de experimental e o gate
        A5_SKILL_INSTALL;
      * manifesto inválido não entra e não derruba o resto — vai para `erros`.

    Devolve {"adicionadas": [...], "erros": [(pasta, motivo)], "origem": str}.
    """
    origem = Path(origem)
    if not origem.is_dir():
        raise RegistroError(f"origem não é uma pasta: {origem}")
    adicionadas: list[str] = []
    erros: list[tuple[str, str]] = []
    for filho in sorted(origem.iterdir()):
        mf_path = filho / "skill.json"
        if not mf_path.is_file():
            continue
        try:
            bruto = json.loads(mf_path.read_text(encoding="utf-8"))
        except Exception as exc:
            erros.append((filho.name, f"manifesto ilegível: {exc}"))
            continue
        try:
            adicionar_ao_catalogo(home, bruto)
        except RegistroError as exc:
            erros.append((filho.name, str(exc)))
            continue
        adicionadas.append(str(bruto.get("name", filho.name)))
    return {"adicionadas": adicionadas, "erros": erros, "origem": str(origem)}


def disponiveis(home: Path, skills_dir: Path) -> list[dict]:
    """Catálogo menos as já instaladas."""
    instaladas = {i["name"] for i in _skills.list_installed(Path(skills_dir))}
    return [c for c in catalogo(home) if c["name"] not in instaladas]


# ------------------------- instalação v2 -------------------------

TIPOS_REQUISITO = ("binario", "modulo_python", "chave", "servidor_mcp",
                   "credencial_externa")
"""Os três tipos que um manifesto pode declarar em `requires`."""


def verificar_requisitos(mf: dict, home: Path | None = None) -> list[dict]:
    """O que o manifesto declara em `requires` e NÃO existe nesta máquina.

    Por que na INSTALAÇÃO e não no uso: sem isto, uma skill que depende de um
    binário ausente instala com sucesso e só quebra quando a pessoa tenta usá-la
    — "plug-and-play" vira promessa falsa. Medido nos manifestos reais: 7 de 12
    declaram binário que não existe nesta máquina.

    Cada item devolvido é o requisito original acrescido de `motivo`. Só isso:
    quem decide recusar é `instalar`, e só para os `obrigatorio: true`.

    Limites que esta função NÃO finge cobrir:
      * `chave` é verificada por NOME no cofre (`Vault.names()`), sem passphrase
        e sem ler valor — presença do nome não prova que o valor serve;
      * `servidor_mcp` confere registro no catálogo MCP, não que o servidor suba;
      * requisito de tipo desconhecido conta como AUSENTE (fail-closed): melhor
        recusar do que instalar prometendo algo que ninguém checou.
    """
    import shutil

    faltando: list[dict] = []
    for req in (mf.get("requires") or []):
        if not isinstance(req, dict):
            faltando.append({"tipo": "?", "nome": str(req), "obrigatorio": True,
                             "motivo": "requisito malformado no manifesto"})
            continue
        tipo, nome = str(req.get("tipo", "")), str(req.get("nome", ""))
        obrig = bool(req.get("obrigatorio", True))
        motivo, verificado = None, True
        if tipo == "binario":
            # `nome` pode vir como linha de comando ("python3 -m feedparser");
            # o executável é o PRIMEIRO token. Verificar a linha inteira com
            # `which` reprovaria sempre — recusa inventada, não medida.
            exe = nome.split()[0] if nome.split() else ""
            if not exe:
                motivo, verificado = "requisito 'binario' sem nome", False
            elif not shutil.which(exe):
                motivo = f"binário '{exe}' não está no PATH"
        elif tipo == "modulo_python":
            verificado = False   # só confirma presença; ausência não é provável
            # `feedparser` é módulo, não executável: `which feedparser` falha e
            # `which python3` PASSA — verificação falsa, o pior tipo, porque
            # parece cobertura e não é. Aqui se mede o que importa: o import.
            motivo = _modulo_ausente(nome)
        elif tipo == "chave":
            if not _IDENT.fullmatch(nome):
                # nome em prosa ("token do gh (host, nao do cofre)") não é
                # consultável no cofre. Não invento ausência a partir disso.
                motivo, verificado = (
                    f"chave '{nome}': não é um nome consultável no cofre", False)
            else:
                motivo = _chave_ausente(nome, home)
        elif tipo == "servidor_mcp":
            motivo = _mcp_ausente(nome, home)
        elif tipo == "credencial_externa":
            # Credencial que MORA FORA do cofre por desenho — token do `gh` em
            # ~/.config/gh, sessão de navegador, login de app. O NOMOS não a
            # governa e NÃO vai lê-la para "verificar": sondar credencial
            # alheia seria exatamente o comportamento que o A3 existe para
            # controlar. Declarar aqui é informação ao dono, nunca checagem.
            # Antes disto, `reach-github` declarava o token como tipo "chave"
            # e era BLOQUEADO por "não está no cofre" — recusa falsa: o token
            # nunca deveria estar lá.
            motivo, verificado = (
                f"credencial externa '{nome}': o NOMOS não a governa nem "
                "verifica — confira você mesmo", False)
        else:
            motivo, verificado = f"tipo de requisito desconhecido: {tipo!r}", False
        if motivo:
            faltando.append({**req, "tipo": tipo, "nome": nome,
                             "obrigatorio": obrig, "motivo": motivo,
                             "verificado": verificado})
    return faltando


def _modulo_ausente(nome: str) -> str | None:
    """Módulo Python: confirma PRESENÇA; não consegue provar ausência.

    A assimetria é real e vale escrita, porque ela decide o comportamento:
    binário se acha por caminho (`shutil.which`), então ausência de binário é
    EVIDÊNCIA e bloqueia. Módulo não: descobrir se `feedparser` existe no
    interpretador que a cerca vai usar exigiria RODAR aquele interpretador.

    Duas saídas foram descartadas, e o motivo importa:

    * `find_spec` no processo atual, que foi minha primeira versão — mede o
      interpretador ERRADO. Medido: `feedparser` está em
      `/opt/homebrew/bin/python3` (6.0.12) e não no venv onde o NOMOS roda; a
      checagem recusava `reach-rss` com o módulo presente onde importa. Recusa
      FALSA, o oposto de "bloqueia por evidência";
    * `subprocess` sondando o outro interpretador — mede certo, mas acrescenta
      geração de processo no NÚCLEO, fora do supervisor. O guard
      `test_p1_o_legado_com_subprocess_nao_cresceu` pegou isso em mim, e ele
      está certo: o supervisor ser o gargalo único é garantia estrutural do
      produto inteiro. Não se abre exceção nela por conveniência de uma
      verificação de dependência.

    Então: achou no processo atual => PRESENTE (evidência, não bloqueia).
    Não achou => NÃO VERIFICÁVEL (`verificado: False`), some do bloqueio e
    aparece ao dono como aviso. Nunca bloqueia por ignorância.
    """
    import importlib.util

    if not _IDENT.fullmatch(nome):
        return f"módulo '{nome}': nome não é um identificador de módulo"
    try:
        if importlib.util.find_spec(nome):
            return None
    except Exception:  # noqa: S110 — find_spec estoura em pacote quebrado;
        pass           # isso não é evidência de ausência, cai em não-verificável.
    return (f"módulo Python '{nome}': não verificável daqui — quem roda a skill "
            "é outro interpretador (o da cerca)")


def _chave_ausente(nome: str, home: Path | None) -> str | None:
    """Confere só o NOME no cofre. Nunca pede passphrase, nunca lê valor."""
    if home is None:
        return f"chave '{nome}': não sei onde procurar (home não informada)"
    try:
        from nomos.kernel.vault import Vault
        v = Vault(Path(home) / "vault.json")
        if not v.exists():
            return f"chave '{nome}': cofre não existe (nomos vault init)"
        return None if nome in v.names() else f"chave '{nome}' não está no cofre"
    except Exception as exc:
        return f"chave '{nome}': não consegui verificar ({type(exc).__name__})"


_IDENT = __import__("re").compile(r"[A-Za-z0-9_.-]{1,64}")


def _mcp_ausente(nome: str, home: Path | None) -> str | None:
    if home is None:
        return f"servidor MCP '{nome}': não sei onde procurar"
    try:
        from nomos.interface import mcp_catalogo as cat
        # `listar` devolve DICT {"confiaveis": [...], "revogadas": N} — iterar o
        # retorno direto percorreria as CHAVES e falharia em silêncio.
        snap = cat.listar(Path(home)) or {}
        registrados = {str(c.get("nome")) for c in snap.get("confiaveis", [])}
        return None if nome in registrados else f"servidor MCP '{nome}' não é confiável/registrado"
    except Exception as exc:
        return f"servidor MCP '{nome}': não consegui verificar ({type(exc).__name__})"


def pode_executar_aqui(mf: dict, home: Path | None = None) -> tuple[bool, str]:
    """Esta skill CONSEGUE rodar nesta máquina? Devolve (pode, motivo).

    Existe para o instalador dizer a verdade na hora certa. Sem isto, a pessoa
    instala com sucesso e só descobre no primeiro uso que nada roda — que é o
    pior momento possível para a promessa de "plug-and-play" quebrar.

    Medido neste Mac, e o resultado é contraintuitivo:
      * skill SEM A2_NET_EGRESS -> rc=1 "user namespaces indisponíveis": o
        confinamento S0 é só-Linux por desenho, e sem ele o NOMOS RECUSA em vez
        de rodar sem cerca. A postura é correta; o efeito é que a skill mais
        segura é justamente a que não executa;
      * skill COM A2 -> executa, MAS só se o cadeado só-local estiver desligado.
        Numa instalação padrão (cadeado ligado) ela cai em A2 negado.
    Ou seja, no macOS com cadeado ligado NENHUMA das duas roda — e isso precisa
    ser dito, não descoberto.
    """
    from nomos.kernel import localidade
    from nomos.runtime.sandbox import isolamento_sem_rede_disponivel

    perms = mf.get("permissions") or []
    quer_rede = Category.NET_EGRESS.value in perms
    if not quer_rede:
        # Desde 23/08 o macOS também executa o ramo sem rede: o seatbelt com o
        # perfil BASE nega network-* por (deny default) — mesma garantia que o
        # unshare dá no Linux, com cerca de arquivos junto. O critério vem do
        # PRÓPRIO sandbox para previsor e executor nunca divergirem.
        if not isolamento_sem_rede_disponivel():
            return False, ("instala, mas NÃO executa nesta máquina: não há como "
                           "garantir rede negada aqui (sem unshare/seatbelt), e "
                           "o NOMOS recusa em vez de rodar sem cerca")
        return True, ""
    if home is not None and localidade.esta_ligado(home):
        return False, ("instala, mas NÃO executa enquanto o modo só-local "
                       "estiver ligado: ela declara saída para a internet "
                       "(A2). Para permitir: nomos local off")
    return True, ""


def instalar(src: Path, skills_dir: Path, engine: PolicyEngine, approver,
             trust=None, confirmar_experimental=None, home: Path | None = None) -> dict:
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

    # Dependência declarada e ausente RECUSA aqui, antes de copiar arquivo: é a
    # diferença entre "instalou e quebra no uso" e uma promessa honesta.
    # Opcional ausente não bloqueia — só o `obrigatorio: true`.
    # Bloqueia só com EVIDÊNCIA de ausência (`verificado`). O que não deu para
    # verificar — nome em prosa, credencial fora do cofre, tipo desconhecido —
    # NÃO vira recusa: recusar por ignorância inventa impedimento e empurra o
    # autor a apagar o `requires`, que é o oposto do que queremos.
    faltam = [f for f in verificar_requisitos(mf, home)
              if f["obrigatorio"] and f.get("verificado", True)]
    if faltam:
        detalhe = "; ".join(f["motivo"] for f in faltam)
        raise RegistroError(
            f"'{mf['name']}' precisa do que não existe nesta máquina: {detalhe}")

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
