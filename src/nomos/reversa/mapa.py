"""NOMOS Reversa — mapeamento e engenharia reversa de ferramentas de terceiros (MC65).

Contrato de segurança (verificado por testes):

- **Somente leitura.** O componente nunca executa, importa, instala nem altera o
  alvo. Ele descreve; não roda.
- **Nunca segue link simbólico** para fora da raiz do alvo, e nunca lê o alvo em
  modo de escrita.
- **Git é consultado por allowlist de verbos de LEITURA**, com `core.hooksPath` e
  `core.fsmonitor` neutralizados por `-c`, para que um repositório hostil não
  ganhe execução só por ser mapeado.
- **Saída determinística** (listas ordenadas), própria para gate de CI.

O mapa responde às perguntas da regra Voltolini de validação — origem,
integridade, autoria, superfície, permissões, licença — e termina num blueprint
de reimplementação, porque a preferência é **construir o nosso**.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

VERSAO = "MC65.0"

#: Tetos de leitura. Um alvo hostil pode ser gigante; o mapa não pode travar.
TETO_ARQUIVOS = 20_000
TETO_BYTES_ARQUIVO = 256 * 1024
TETO_ACHADOS = 500

#: Diretórios que não interessam ao mapa (dependências, caches, builds).
_PODA = frozenset({
    "node_modules", ".venv", "venv", "__pycache__", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", ".tox", "dist", "build", ".eggs",
    ".terraform", "target", "vendor",
})

#: Verbos git permitidos. Qualquer outro é recusado fail-closed.
_GIT_LEITURA = frozenset({"rev-parse", "remote", "log", "describe", "symbolic-ref"})

#: Extensões tratadas como texto. O resto é contado, não lido.
_TEXTO = frozenset({
    ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".sh", ".bash", ".zsh",
    ".fish", ".ps1", ".bat", ".cmd", ".rb", ".go", ".rs", ".java", ".kt", ".c",
    ".h", ".cpp", ".hpp", ".cs", ".php", ".pl", ".lua", ".r", ".sql", ".md",
    ".markdown", ".txt", ".rst", ".json", ".jsonl", ".yaml", ".yml", ".toml",
    ".ini", ".cfg", ".conf", ".env", ".example", ".dockerfile", ".mk", ".cmake",
})

#: Categorias de achado, na ordem em que aparecem no relatório.
CATEGORIAS = ("execucao", "rede", "credencial", "injecao", "empacotamento",
              "licenca", "git", "skill")

_GRAVIDADE_ORDEM = {"alto": 3, "medio": 2, "baixo": 1, "info": 0}


@dataclass(frozen=True)
class Achado:
    """Um fato relevante sobre o alvo, com onde foi visto e por que importa."""

    categoria: str
    gravidade: str
    regra: str
    caminho: str
    linha: int | None
    trecho: str
    porque: str


@dataclass
class Mapa:
    """Retrato de um alvo de terceiros, produzido sem executá-lo."""

    alvo: str
    versao: str = VERSAO
    origem: dict = field(default_factory=dict)
    inventario: dict = field(default_factory=dict)
    pontos_de_entrada: list = field(default_factory=list)
    dependencias: list = field(default_factory=list)
    licenca: str | None = None
    #: Cada arquivo de licença encontrado, com escopo e restrições próprias.
    #: Um alvo pode ter mais de uma: código sob uma licença e documentação sob
    #: outra (é o caso do vectorbt, cuja doc é AGPL sobre código Apache).
    licencas: list = field(default_factory=list)
    #: Restrições que mudam o que se pode fazer com o alvo (vender, uso
    #: comercial, cláusula de rede). Separadas do rótulo para não se perderem.
    restricoes: list = field(default_factory=list)
    assinatura: list = field(default_factory=list)
    achados: list = field(default_factory=list)
    risco: str = "limpo"
    blueprint: list = field(default_factory=list)
    # Contrato de segurança — sempre falso, e o teste exige que continue falso.
    read_only: bool = True
    executed_target: bool = False
    mutations_enabled: bool = False
    human_approval_required: bool = True


# --------------------------------------------------------------------------
# Catálogo de padrões
# --------------------------------------------------------------------------

_PADROES = (
    ("execucao", "alto", "pipe-para-shell",
     re.compile(r"\b(?:curl|wget)\b[^\n|]{0,200}\|\s*(?:sudo\s+)?(?:ba|z|k)?sh\b", re.I),
     "Baixa e executa código remoto sem etapa de verificação."),
    ("execucao", "alto", "shell-verdadeiro",
     re.compile(r"\b(?:os\.system|subprocess\.\w+|child_process\.\w+)\b[^\n]{0,140}"
                r"shell\s*=\s*True", re.I),
     "Executa shell construído em tempo de execução: injeção de comando."),
    ("execucao", "alto", "shell-reverso",
     re.compile(r"/dev/tcp/|(?:^|\W)nc\s+-e\s|(?:^|\W)bash\s+-i\s|socket\.socket\([^)]*\)"
                r"[^\n]{0,120}\.connect\(", re.I),
     "Padrão típico de shell reverso (canal de entrada remoto)."),
    ("execucao", "medio", "avaliacao-dinamica",
     re.compile(r"(?<![\w.])(?:eval|exec)\s*\(|new\s+Function\s*\(", re.I),
     "Avalia código em tempo de execução; esconde o que realmente roda."),
    ("execucao", "medio", "ofuscacao",
     re.compile(r"base64\s+(?:-d|--decode)|atob\s*\(|codecs\.decode\([^)]*base64", re.I),
     "Decodifica conteúdo em tempo de execução — payload ofuscado."),
    ("execucao", "baixo", "privilegio",
     re.compile(r"(?:^|\W)sudo\s+(?:-S\s+)?[a-z/]|chmod\s+777|setcap\s", re.I),
     "Pede ou amplia privilégio administrativo."),
    ("rede", "info", "url-externa",
     re.compile(r"https?://[a-zA-Z0-9._~:/?#\[\]@!$&'()*+,;=%-]+", re.I),
     "Destino de rede: é para onde o alvo pode enviar dados."),
    ("credencial", "medio", "variavel-de-segredo",
     re.compile(r"\b[A-Z][A-Z0-9_]*(?:API_KEY|TOKEN|SECRET|PASSWORD|PASSWD|"
                r"CREDENTIAL|PRIVATE_KEY)[A-Z0-9_]*\b"),
     "Lê ou exige credencial: mapeie o que ele faz com ela."),
    ("credencial", "alto", "chave-privada",
     re.compile(r"-----BEGIN\s+(?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----"),
     "Chave privada embutida no material distribuído."),
    ("empacotamento", "medio", "gancho-de-instalacao",
     re.compile(r"postinstall|preinstall|\"install\"\s*:|cmdclass\s*=|"
                r"\[project\.scripts\]|entry_points", re.I),
     "Executa algo no momento da instalação, antes de você revisar."),
)

#: Padrões que só valem em arquivos de instrução (skill/markdown).
_PADROES_INJECAO = (
    ("injecao", "alto", "injecao-de-prompt",
     re.compile(r"ignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions|"
                r"desconsidere\s+(?:as\s+)?instru|ignore\s+as\s+instru", re.I),
     "Texto que tenta subordinar o agente que lê a skill."),
    ("injecao", "alto", "ocultacao-do-dono",
     re.compile(r"do\s+not\s+(?:tell|inform|mention)\s+the\s+user|"
                r"n[ãa]o\s+(?:diga|informe|avise)\s+ao\s+usu[áa]rio", re.I),
     "Instrução para esconder ação do dono do sistema."),
    ("injecao", "medio", "exfiltracao",
     re.compile(r"exfiltrat|send\s+(?:the\s+)?(?:contents|file|keys|env)|"
                r"envie\s+(?:o\s+)?(?:conte[úu]do|arquivo|chaves)", re.I),
     "Pede envio de conteúdo local para fora."),
)


# --------------------------------------------------------------------------
# Caminhada segura
# --------------------------------------------------------------------------

def _texto(caminho: Path) -> str | None:
    """Devolve o conteúdo textual do arquivo, ou None se não for texto legível."""
    if caminho.suffix.lower() not in _TEXTO and caminho.name not in (
        "Makefile", "Dockerfile", "LICENSE", "NOTICE", "setup.py",
    ):
        return None
    try:
        if caminho.stat().st_size > TETO_BYTES_ARQUIVO:
            return None
        bruto = caminho.read_bytes()
    except OSError:
        return None
    if b"\x00" in bruto[:4096]:
        return None
    return bruto.decode("utf-8", errors="replace")


def _arquivos(alvo: Path):
    """Itera arquivos do alvo sem seguir links e sem entrar em `.git`/deps."""
    total = 0
    for raiz, dirs, nomes in os.walk(alvo, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in _PODA and d != ".git")
        for nome in sorted(nomes):
            caminho = Path(raiz) / nome
            if caminho.is_symlink():
                continue
            total += 1
            if total > TETO_ARQUIVOS:
                return
            yield caminho


def _trecho(linha: str, limite: int = 160) -> str:
    """Trecho redigido e curto — o relatório não copia segredo para o arquivo."""
    limpo = " ".join(linha.split())
    return limpo[:limite] + ("…" if len(limpo) > limite else "")


# --------------------------------------------------------------------------
# Git — só leitura, com hooks neutralizados
# --------------------------------------------------------------------------

def _git(repo: Path, *args: str) -> str | None:
    """Roda um verbo de LEITURA do git. Qualquer outro verbo é recusado."""
    if not args or args[0] not in _GIT_LEITURA:
        return None
    comando = [
        "git",
        "-c", "core.hooksPath=" + os.devnull,
        "-c", "core.fsmonitor=false",
        "-c", "core.pager=cat",
        "-C", str(repo),
        *args,
    ]
    try:
        proc = subprocess.run(
            comando, capture_output=True, text=True, timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def _mapear_git(alvo: Path, achados: list) -> dict:
    """Mapeia o repositório: origem, hooks (que SÃO código) e submódulos."""
    git_dir = alvo / ".git"
    info: dict = {}

    if git_dir.is_dir():
        info["repo"] = True
        info["remote"] = _git(alvo, "remote", "-v") or ""
        info["head"] = _git(alvo, "rev-parse", "HEAD")
        info["branch"] = _git(alvo, "symbolic-ref", "--short", "HEAD")

        # Hooks não-exemplo executam código: são código, não configuração.
        hooks_dir = git_dir / "hooks"
        hooks = []
        if hooks_dir.is_dir():
            for item in sorted(hooks_dir.iterdir()):
                if item.is_file() and not item.name.endswith(".sample"):
                    hooks.append(item.name)
        if hooks:
            info["hooks"] = hooks
            achados.append(Achado(
                "git", "alto", "hooks-ativos", ".git/hooks", None,
                ", ".join(hooks),
                "Hooks executam automaticamente em eventos do git: leia antes.",
            ))

        # `hooksPath` e filtros redirecionam execução para fora do padrão.
        config = git_dir / "config"
        if config.is_file():
            try:
                texto = config.read_text(encoding="utf-8", errors="replace")
            except OSError:
                texto = ""
            if re.search(r"^\s*hooksPath\s*=", texto, re.M | re.I):
                achados.append(Achado(
                    "git", "alto", "hookspath-customizado", ".git/config", None,
                    _trecho(next((ln for ln in texto.splitlines()
                                  if "hookspath" in ln.lower()), "")),
                    "Redireciona os hooks para outro diretório: revise o destino.",
                ))
            if re.search(r"^\s*(?:clean|smudge)\s*=", texto, re.M | re.I):
                achados.append(Achado(
                    "git", "alto", "filtro-de-conteudo", ".git/config", None,
                    _trecho(next((ln for ln in texto.splitlines()
                                  if "clean =" in ln or "smudge =" in ln), "")),
                    "Filtros git executam comandos ao manipular arquivos.",
                ))

        if (alvo / ".gitmodules").is_file():
            info["submodulos"] = True
            achados.append(Achado(
                "git", "medio", "submodulos", ".gitmodules", None,
                "presente",
                "Submódulos trazem código de outra origem, não coberta por este mapa.",
            ))
    else:
        info["repo"] = False

    return info


# --------------------------------------------------------------------------
# Skill — manifesto e assinatura
# --------------------------------------------------------------------------

def _raizes_de_skill(alvo: Path) -> list:
    """Descobre cada skill do alvo: diretório com `skill.json` ou `SKILL.md`.

    Uma pasta de skills contém VÁRIAS skills — olhar só a raiz perderia a
    assinatura de todas menos uma.
    """
    raizes = set()
    if (alvo / "skill.json").is_file() or (alvo / "SKILL.md").is_file():
        raizes.add(alvo)
    for raiz, dirs, nomes in os.walk(alvo, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in _PODA and d != ".git")
        atual = Path(raiz)
        if atual == alvo:
            continue
        if "skill.json" in nomes or "SKILL.md" in nomes:
            raizes.add(atual)
    return sorted(raizes)


def _mapear_skill(alvo: Path, achados: list) -> list:
    """Mapeia cada skill do alvo: manifesto, permissões e assinatura."""
    resultado = []
    for raiz in _raizes_de_skill(alvo):
        rel = str(raiz.relative_to(alvo)) or "."
        info: dict = {"caminho": rel}
        manifesto = raiz / "skill.json"

        if manifesto.is_file():
            try:
                dados = json.loads(manifesto.read_text(encoding="utf-8", errors="replace"))
            except (OSError, ValueError) as erro:
                achados.append(Achado(
                    "skill", "alto", "manifesto-invalido", f"{rel}/skill.json", None,
                    str(erro)[:120],
                    "Manifesto ilegível: a skill não pode ser validada.",
                ))
                resultado.append({**info, "nome": raiz.name, "manifesto": "invalido"})
                continue
            info.update({
                "nome": dados.get("name"),
                "versao": dados.get("version"),
                "permissoes": dados.get("permissions") or [],
                "risco_declarado": dados.get("risk_level"),
                "publicador": dados.get("publisher"),
                "entrypoint": dados.get("entrypoint") or dados.get("entry"),
            })
            if not dados.get("publisher"):
                achados.append(Achado(
                    "skill", "medio", "sem-publicador", f"{rel}/skill.json", None,
                    "publisher ausente",
                    "Sem publicador não há como atribuir a skill a alguém.",
                ))
        else:
            info["nome"] = raiz.name
            info["formato"] = "SKILL.md"

        assinaturas = sorted(
            p.name for p in raiz.iterdir()
            if p.is_file() and (p.suffix in (".sig", ".asc", ".minisig")
                                or p.name.endswith((".sig", ".sigstore")))
        )
        info["assinaturas"] = assinaturas
        if not assinaturas:
            achados.append(Achado(
                "skill", "medio", "skill-sem-assinatura", rel, None,
                "nenhum arquivo de assinatura",
                "Skill sem assinatura: sem autoria verificável — registre o achado.",
            ))
        resultado.append(info)

    return resultado


# --------------------------------------------------------------------------
# Varredura de conteúdo
# --------------------------------------------------------------------------

def _varrer(alvo: Path, achados: list) -> tuple[dict, list]:
    """Percorre o conteúdo textual em busca dos padrões do catálogo."""
    por_extensao: dict = {}
    entradas: list = []
    total_bytes = 0
    arquivos = 0

    for caminho in _arquivos(alvo):
        arquivos += 1
        ext = caminho.suffix.lower() or "(sem extensão)"
        por_extensao[ext] = por_extensao.get(ext, 0) + 1
        try:
            total_bytes += caminho.stat().st_size
        except OSError:
            pass

        texto = _texto(caminho)
        if texto is None:
            continue
        rel = str(caminho.relative_to(alvo))
        linhas = texto.splitlines()

        # Pontos de entrada são arquivos que o mundo executa.
        if caminho.name in ("setup.py", "pyproject.toml", "package.json", "Makefile",
                            "Dockerfile", "install.sh", "main.py", "__main__.py") \
                or os.access(caminho, os.X_OK):
            entradas.append(rel)

        if len(achados) < TETO_ACHADOS:
            for numero, linha in enumerate(linhas, start=1):
                for categoria, gravidade, regra, regex, porque in _PADROES:
                    if regex.search(linha):
                        achados.append(Achado(
                            categoria, gravidade, regra, rel, numero,
                            _trecho(linha), porque,
                        ))
                if caminho.suffix.lower() in (".md", ".markdown", ".txt") or \
                        caminho.name == "SKILL.md":
                    for categoria, gravidade, regra, regex, porque in _PADROES_INJECAO:
                        if regex.search(linha):
                            achados.append(Achado(
                                categoria, gravidade, regra, rel, numero,
                                _trecho(linha), porque,
                            ))

    inventario = {
        "arquivos": arquivos,
        "bytes": total_bytes,
        "por_extensao": dict(sorted(por_extensao.items(),
                                    key=lambda kv: (-kv[1], kv[0]))[:15]),
    }
    return inventario, sorted(set(entradas))


def _dependencias(alvo: Path) -> list:
    """Extrai dependências declaradas, sem instalar nada."""
    deps: set = set()
    pyproject = alvo / "pyproject.toml"
    if pyproject.is_file():
        try:
            texto = pyproject.read_text(encoding="utf-8", errors="replace")
        except OSError:
            texto = ""
        for bloco in re.findall(r"dependencies\s*=\s*\[(.*?)\]", texto, re.S):
            deps.update(re.findall(r"[\"']([^\"'<>=\[\]]+)", bloco))
    package = alvo / "package.json"
    if package.is_file():
        try:
            dados = json.loads(package.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            dados = {}
        for chave in ("dependencies", "devDependencies"):
            deps.update((dados.get(chave) or {}).keys())
    req = alvo / "requirements.txt"
    if req.is_file():
        try:
            for linha in req.read_text(encoding="utf-8", errors="replace").splitlines():
                limpo = linha.split("#")[0].strip()
                if limpo:
                    deps.add(re.split(r"[<>=!\[;]", limpo)[0].strip())
        except OSError:
            pass
    return sorted(d for d in deps if d)


#: Nomes de arquivo que carregam licença, na ordem de precedência do rótulo.
_ARQUIVOS_LICENCA = ("LICENSE", "LICENSE.md", "LICENSE.txt", "LICENSE.rst",
                     "COPYING", "COPYING.md", "COPYING.LESSER", "NOTICE")

#: Diretórios onde a documentação costuma trazer licença PRÓPRIA, diferente da
#: do código. Ignorar isso produz falso negativo comprovado: o `vectorbt` tem
#: `LICENSE.md` (Apache + Commons Clause) e `docs/LICENSE.md` (AGPL).
_DIRS_LICENCA = ("docs", "doc", "licenses", "LICENSES", "legal")

#: Catálogo de licenças, do mais restritivo para o mais permissivo.
#: (id, trecho procurado no texto, copyleft, restrições)
#: `CC-BY-NC` NÃO entra aqui de propósito: a palavra "noncommercially" aparece
#: no corpo da própria GPL/AGPL ("convey ... noncommercially") e casaria como
#: falso positivo. Ela é detectada à parte, exigindo também "creative commons".
_LICENCAS = (
    ("Commons Clause", "commons clause", "", ("proibe-venda",)),
    ("AGPL-3.0", "gnu affero general public license", "forte", ("clausula-de-rede",)),
    ("LGPL-3.0", "gnu lesser general public license", "fraca", ()),
    ("GPL-3.0", "gnu general public license", "forte", ()),
    ("Apache-2.0", "apache license", "", ()),
    ("MPL-2.0", "mozilla public license", "fraca", ()),
    ("BSD-3-Clause", "redistribution and use in source and binary forms", "", ()),
    ("MIT", "mit license", "", ()),
    ("ISC", "isc license", "", ()),
    ("Unlicense", "this is free and unencumbered software", "", ()),
)

#: Ids que são restrição, não licença: não servem de rótulo principal.
_RESTRITIVAS = frozenset({"Commons Clause", "CC-BY-NC"})

#: Arquivos de manifesto e onde cada um declara a licença.
_MANIFESTOS = (
    ("package.json", r'"license"\s*:\s*"([^"]+)"'),
    ("pyproject.toml", r'^license\s*=\s*\{?\s*(?:text\s*=\s*)?"([^"]+)"'),
    ("Cargo.toml", r'^license\s*=\s*"([^"]+)"'),
    ("setup.py", r'license\s*=\s*["\']([^"\']+)["\']'),
)


#: Identificadores SPDX/curtos, comuns em metadados de pacote (`License:` do
#: PyPI, classifiers, `package.json`), onde não há o texto integral da licença.
_SPDX_DIRETO = (
    ("Commons Clause", re.compile(r"commons[ _-]?clause", re.I)),
    ("CC-BY-NC", re.compile(r"\bCC[ _-]BY[ _-]NC", re.I)),
    ("AGPL-3.0", re.compile(r"\bAGPL-?3(?:\.0)?\b", re.I)),
    ("LGPL-3.0", re.compile(r"\bLGPL-?3(?:\.0)?\b", re.I)),
    ("GPL-3.0", re.compile(r"\bGPL-?3(?:\.0)?\b", re.I)),
    ("Apache-2.0", re.compile(r"\bApache-?2(?:\.0)?\b|\bApache Software License\b", re.I)),
    ("MPL-2.0", re.compile(r"\bMPL-?2(?:\.0)?\b", re.I)),
    ("BSD-3-Clause", re.compile(r"\bBSD-?3-Clause\b", re.I)),
    ("ISC", re.compile(r"\bISC\b")),
    ("MIT", re.compile(r"\bMIT\b")),
)


def _classificar_simples(texto: str) -> tuple[str | None, str, tuple]:
    """Classifica UMA licença (ou uma conjunção `A AND B` delas)."""
    baixo = texto.lower()
    ids = [ident for ident, trecho, _, _ in _LICENCAS if trecho in baixo]
    for ident, padrao in _SPDX_DIRETO:
        if ident not in ids and padrao.search(texto):
            ids.append(ident)
    if "creative commons" in baixo and "noncommercial" in baixo:
        ids.append("CC-BY-NC")
    if not ids:
        return None, "", ()
    copyleft = ""
    restricoes: list = []
    for ident, _, forca, rest in _LICENCAS:
        if ident not in ids:
            continue
        if forca == "forte" or (forca == "fraca" and copyleft != "forte"):
            copyleft = forca
        restricoes.extend(rest)
    if "CC-BY-NC" in ids:
        restricoes.append("nao-comercial")
    principal = next((i for i in ids if i not in _RESTRITIVAS), ids[0])
    if principal == "GPL-3.0":
        # "GPLv3" e "GPL-3.0-only" não são a mesma coisa que "or later".
        principal = ("GPL-3.0-or-later" if "any later version" in baixo
                     else "GPL-3.0-only")
    return principal, copyleft, tuple(sorted(set(restricoes)))


def classificar_licenca(texto: str) -> tuple[str | None, str, tuple]:
    """Classifica um texto de licença: (id principal, copyleft, restrições).

    Entende expressões SPDX compostas, que é o que os pacotes modernos trazem
    em `License-Expression` (PEP 639):

    - `A OR B` → vale a **menos restritiva** (dá para adotar sob a permissiva);
    - `A AND B` → valem **todas** (a mais restritiva manda).

    Pública de propósito: o gate de licença do SBOM (`tools/make_sbom.py`) usa
    esta MESMA regra, para não existirem duas verdades sobre licença no NOMOS.
    """
    # Expressão SPDX (`A OR B`) é curta e de uma linha só. O " or " de um texto
    # corrido de licença ("either version 3 ... or (at your option) any later
    # version") NÃO é alternativa de licença — dividir ali inverteria o
    # resultado de GPL "or later" para GPL "only".
    if "\n" in texto.strip() or len(texto) > 200:
        return _classificar_simples(texto)
    partes = re.split(r"\s+OR\s+", texto, flags=re.I)
    resultados = [r for r in (_classificar_simples(p) for p in partes) if r[0]]
    if not resultados:
        return None, "", ()
    if len(resultados) > 1:
        peso = {"": 0, "fraca": 1, "forte": 2}
        resultados.sort(key=lambda r: (len(r[2]), peso.get(r[1], 3)))
    return resultados[0]


def _familia(rotulo: str) -> str:
    """Reduz um rótulo de licença à sua família, para comparar manifesto × arquivo."""
    baixo = rotulo.lower()
    for chave in ("agpl", "lgpl", "gpl", "apache", "mit", "bsd", "mpl", "isc",
                  "unlicense", "commons", "cc-by"):
        if chave in baixo:
            return chave
    return baixo.strip()


def _declarado_no_manifesto(alvo: Path) -> str | None:
    """Licença declarada no manifesto do pacote, quando houver."""
    for nome, padrao in _MANIFESTOS:
        caminho = alvo / nome
        if not caminho.is_file():
            continue
        try:
            texto = caminho.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        achado = re.search(padrao, texto, re.M)
        if achado:
            return f"{nome}: {achado.group(1)}"
    return None


def _licencas(alvo: Path, achados: list) -> tuple[str | None, list]:
    """Mapeia TODA licença do alvo: código, documentação e manifesto.

    Um único arquivo não basta. Caso que motivou esta função, medido em alvo
    real: um projeto com `LICENSE.md` "Apache + Commons Clause" e
    `docs/LICENSE.md` AGPL era resumido como "Apache-2.0, risco médio, zero
    achados de licença" — falso negativo que esconde duas restrições graves.
    """
    encontradas: list = []
    vistos: set = set()

    candidatos = [alvo / nome for nome in _ARQUIVOS_LICENCA]
    for pasta in _DIRS_LICENCA:
        base = alvo / pasta
        if not base.is_dir():
            continue
        candidatos.extend(base / nome for nome in _ARQUIVOS_LICENCA)
        lic_dir = base / "licenses"          # padrão REUSE
        if lic_dir.is_dir():
            candidatos.extend(sorted(p for p in lic_dir.iterdir() if p.is_file()))

    for caminho in candidatos:
        if caminho in vistos or not caminho.is_file() or caminho.is_symlink():
            continue
        vistos.add(caminho)
        try:
            texto = caminho.read_text(encoding="utf-8", errors="replace")[:20000]
        except OSError:
            continue
        ident, copyleft, restricoes = classificar_licenca(texto)
        encontradas.append({
            "arquivo": str(caminho.relative_to(alvo)),
            "id": ident,
            "escopo": "codigo" if caminho.parent == alvo else "documentacao",
            "copyleft": copyleft,
            "restricoes": list(restricoes),
        })

    principal = next((e["id"] for e in encontradas
                      if e["escopo"] == "codigo" and e["id"]), None)
    if principal is None:
        principal = next((e["id"] for e in encontradas if e["id"]), None)

    declarado = _declarado_no_manifesto(alvo)

    if not encontradas:
        achados.append(Achado(
            "licenca", "alto", "licenca-ausente", "LICENSE", None,
            declarado or "nenhum arquivo de licença no material distribuído",
            "Sem licença não há permissão de uso: todos os direitos reservados. "
            "Cópia ou incorporação não é autorizada.",
        ))
        return None, encontradas

    for entrada in encontradas:
        local = entrada["arquivo"]
        if "proibe-venda" in entrada["restricoes"]:
            achados.append(Achado(
                "licenca", "alto", "licenca-clausula-restritiva", local, None,
                entrada["id"] or "restrição declarada",
                "Cláusula que remove o direito de vender: não pode ser embutida "
                "em produto comercial, mesmo sendo 'open source'.",
            ))
        if "nao-comercial" in entrada["restricoes"]:
            achados.append(Achado(
                "licenca", "alto", "licenca-uso-nao-comercial", local, None,
                entrada["id"] or "restrição declarada",
                "Uso comercial proibido: não serve a produto vendido.",
            ))
        if entrada["copyleft"] == "forte":
            achados.append(Achado(
                "licenca", "alto", "licenca-copyleft-forte", local, None,
                entrada["id"] or "copyleft",
                "Copyleft forte: linkar contamina o produto MIT. A regra "
                "inviolável nº 6 do NOMOS só admite processo externo.",
            ))
        elif entrada["copyleft"] == "fraca":
            achados.append(Achado(
                "licenca", "medio", "licenca-copyleft-fraca", local, None,
                entrada["id"] or "copyleft fraco",
                "Copyleft fraco: permitido como biblioteca separada, com aviso "
                "e sem embutir no binário.",
            ))

    codigo = next((e for e in encontradas if e["escopo"] == "codigo" and e["id"]), None)
    doc = next((e for e in encontradas if e["escopo"] == "documentacao" and e["id"]), None)
    if codigo and doc and _familia(doc["id"]) != _familia(codigo["id"]):
        achados.append(Achado(
            "licenca", "alto", "licenca-da-documentacao-divergente",
            doc["arquivo"], None,
            f"codigo={codigo['id']} documentacao={doc['id']}",
            "A documentação tem licença própria: reimplementar a partir dela "
            "NÃO é clean-room seguro.",
        ))

    if declarado:
        rotulo = declarado.split(": ", 1)[1]
        if principal and _familia(rotulo) != _familia(principal):
            achados.append(Achado(
                "licenca", "alto", "licenca-conflitante", "manifesto", None,
                f"manifesto={declarado} · arquivo={principal}",
                "Duas licenças declaradas e diferentes: a autoria não é "
                "verificável — trate como não validado.",
            ))

    return principal, encontradas


def _risco(achados: list) -> str:
    """Gravidade máxima observada — o pior achado manda."""
    if not achados:
        return "limpo"
    pior = max(_GRAVIDADE_ORDEM.get(a.gravidade, 0) for a in achados)
    for nome, valor in _GRAVIDADE_ORDEM.items():
        if valor == pior:
            return nome
    return "info"


def _blueprint(inventario: dict, entradas: list, deps: list,
               achados: list) -> list:
    """Passos de reimplementação — a razão de existir do mapa."""
    passos = []
    langs = [e for e in inventario.get("por_extensao", {}) if e in (
        ".py", ".js", ".ts", ".rs", ".go", ".rb", ".java", ".sh",
    )]
    if langs:
        passos.append("Linguagem principal: " + ", ".join(langs[:3])
                      + " — reimplemente na stack do NOMOS (Python 3.10+).")
    if entradas:
        passos.append("Contratos a reproduzir (pontos de entrada): "
                      + ", ".join(entradas[:6]) + ".")
    if deps:
        passos.append(f"{len(deps)} dependência(s) declarada(s): reimplemente só o "
                      "necessário e prefira a biblioteca padrão.")
    cats = sorted({a.categoria for a in achados})
    if "rede" in cats:
        passos.append("Há saída de rede: no componente nosso, egresso passa pela "
                      "política de localidade do NOMOS (A0–A6), não direto.")
    if "execucao" in cats:
        passos.append("Há execução de código: no componente nosso, execução é "
                      "explícita, allowlistada e aprovada — nunca implícita.")
    if "git" in cats:
        passos.append("Há superfície git: use o verbo de leitura allowlistado "
                      "(tools/nomos_git_agent.py) e neutralize hooks.")
    passos.append("Escreva o teste ANTES: o comportamento observado aqui vira o "
                  "critério de aceite da reimplementação.")
    return passos


# --------------------------------------------------------------------------
# API pública
# --------------------------------------------------------------------------

def mapear(alvo: str | Path) -> Mapa:
    """Mapeia `alvo` sem executá-lo. Nunca levanta por alvo inválido."""
    caminho = Path(alvo).expanduser()
    mapa = Mapa(alvo=str(caminho))

    if not caminho.exists():
        mapa.achados.append(Achado(
            "empacotamento", "alto", "alvo-inexistente", str(caminho), None,
            "caminho não existe", "Não há o que mapear.",
        ))
        mapa.risco = "alto"
        return mapa

    if caminho.is_file():
        texto = _texto(caminho)
        mapa.inventario = {"arquivos": 1, "bytes": caminho.stat().st_size,
                           "por_extensao": {caminho.suffix or "(sem extensão)": 1}}
        mapa.origem = {"tipo": "arquivo"}
        if texto:
            for numero, linha in enumerate(texto.splitlines(), start=1):
                for categoria, gravidade, regra, regex, porque in _PADROES:
                    if regex.search(linha):
                        mapa.achados.append(Achado(
                            categoria, gravidade, regra, caminho.name, numero,
                            _trecho(linha), porque,
                        ))
        mapa.risco = _risco(mapa.achados)
        mapa.blueprint = _blueprint(mapa.inventario, [], [], mapa.achados)
        return mapa

    if caminho.is_symlink():
        mapa.achados.append(Achado(
            "empacotamento", "alto", "alvo-e-link", str(caminho), None,
            os.readlink(caminho),
            "Alvo é link simbólico: aponte a raiz real para mapear.",
        ))
        mapa.risco = "alto"
        return mapa

    mapa.origem = {"tipo": "diretorio", **_mapear_git(caminho, mapa.achados)}
    mapa.inventario, mapa.pontos_de_entrada = _varrer(caminho, mapa.achados)
    mapa.dependencias = _dependencias(caminho)
    mapa.licenca, mapa.licencas = _licencas(caminho, mapa.achados)
    mapa.restricoes = sorted({r for e in mapa.licencas for r in e["restricoes"]})
    mapa.assinatura = _mapear_skill(caminho, mapa.achados)

    ordem = {c: i for i, c in enumerate(CATEGORIAS)}
    mapa.achados.sort(key=lambda a: (ordem.get(a.categoria, 99), a.caminho,
                                     a.linha or 0, a.regra))
    mapa.risco = _risco(mapa.achados)
    mapa.blueprint = _blueprint(mapa.inventario, mapa.pontos_de_entrada,
                                mapa.dependencias, mapa.achados)
    return mapa


def para_dict(mapa: Mapa) -> dict:
    """Converte o mapa em estrutura JSON-serializável e determinística."""
    dados = asdict(mapa)
    dados["achados_por_categoria"] = {
        c: sum(1 for a in mapa.achados if a.categoria == c) for c in CATEGORIAS
    }
    dados["total_achados"] = len(mapa.achados)
    return dados


def relatorio(mapa: Mapa) -> str:
    """Relatório em Markdown, legível por humano e por agente."""
    linhas = [
        f"# Mapa de `{mapa.alvo}`",
        "",
        f"- Versão do mapeador: `{mapa.versao}`",
        f"- Risco observado: **{mapa.risco}**",
        f"- Achados: {len(mapa.achados)}",
        f"- Somente leitura: {mapa.read_only} · Alvo executado: {mapa.executed_target}",
        "",
    ]

    if mapa.origem:
        linhas += ["## Origem", ""]
        linhas += [f"- {k}: {v}" for k, v in mapa.origem.items() if v not in ("", None, [])]
        linhas.append("")

    if mapa.inventario:
        linhas += ["## Inventário", ""]
        linhas.append(f"- Arquivos: {mapa.inventario.get('arquivos')}")
        linhas.append(f"- Bytes: {mapa.inventario.get('bytes')}")
        for ext, qtd in (mapa.inventario.get("por_extensao") or {}).items():
            linhas.append(f"  - `{ext}`: {qtd}")
        linhas.append("")

    if mapa.pontos_de_entrada:
        linhas += ["## Pontos de entrada", ""]
        linhas += [f"- `{p}`" for p in mapa.pontos_de_entrada[:20]]
        linhas.append("")

    if mapa.dependencias:
        linhas += ["## Dependências", ""]
        linhas += [f"- `{d}`" for d in mapa.dependencias[:30]]
        linhas.append("")

    if mapa.assinatura:
        linhas += ["## Skills encontradas", ""]
        for s in mapa.assinatura:
            assinaturas = s.get("assinaturas") or []
            linhas.append(
                f"- `{s.get('caminho')}` — nome: {s.get('nome')}; "
                f"publicador: {s.get('publicador') or 'AUSENTE'}; "
                f"assinatura: {', '.join(assinaturas) if assinaturas else 'AUSENTE'}"
            )
        linhas.append("")

    linhas += ["## Achados", ""]
    if not mapa.achados:
        linhas.append("Nenhum padrão do catálogo foi encontrado.")
    else:
        for a in mapa.achados[:80]:
            local = f"{a.caminho}:{a.linha}" if a.linha else a.caminho
            linhas.append(f"- **[{a.gravidade}] {a.regra}** — `{local}`")
            linhas.append(f"  - {a.porque}")
            if a.trecho:
                linhas.append(f"  - trecho: `{a.trecho}`")
    linhas.append("")

    if mapa.blueprint:
        linhas += ["## Blueprint de reimplementação", ""]
        linhas += [f"{i}. {p}" for i, p in enumerate(mapa.blueprint, start=1)]
        linhas.append("")

    linhas += [
        "## Licença",
        "",
        f"- Rótulo principal: {mapa.licenca or '**não declarada** (todos os direitos reservados)'}",
    ]
    if mapa.restricoes:
        linhas.append(f"- **Restrições: {', '.join(mapa.restricoes)}**")
    for entrada in mapa.licencas:
        detalhe = entrada["id"] or "não identificada"
        extras = []
        if entrada["copyleft"]:
            extras.append(f"copyleft {entrada['copyleft']}")
        if entrada["restricoes"]:
            extras.append("restrições: " + ", ".join(entrada["restricoes"]))
        sufixo = f" ({'; '.join(extras)})" if extras else ""
        linhas.append(f"  - `{entrada['arquivo']}` [{entrada['escopo']}]: {detalhe}{sufixo}")
    if not mapa.licencas and mapa.licenca is None:
        linhas.append("  - nenhum arquivo de licença encontrado")
    linhas.append("")
    return "\n".join(linhas)
