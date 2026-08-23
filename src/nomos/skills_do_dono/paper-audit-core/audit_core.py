"""Skill NOMOS: paper-audit-core.

Confere afirmacoes OBJETIVAS de um paper (hiperparametro/default, nome de
funcao/modulo, metrica com numero) contra o codigo de um repositorio JA
clonado, e classifica cada uma em ENCONTRADO / NAO_ENCONTRADO / DIVERGENTE.

Permissoes declaradas no manifesto: A0_READ_LOCAL e A1_WRITE_LOCAL.
Por isso este arquivo nao importa socket/urllib (A2_NET_EGRESS nao declarada),
nao chama subprocess nem git (A5_CODE_EXEC nao declarada) e nao apaga nada
(A6_DESTRUCTIVE nao declarada). O unico efeito colateral possivel e gravar o
relatorio no caminho que o proprio chamador pediu em 'saida'.

Regra de honestidade: tudo que a skill NAO conseguiu fazer sai declarado nos
campos 'problemas', 'avisos' e 'limites' — nunca em silencio.
"""
from __future__ import annotations

import bisect
import json
import math
import os
import re
import sys
from pathlib import Path

VERSAO = "1.0.0"

# ---------------------------------------------------------------- limites
# Tetos de varredura. Existem porque um repo grande faria a skill rodar por
# minutos e estourar memoria; quando um teto e atingido isso vai declarado em
# 'avisos' e derruba a confianca de todo NAO_ENCONTRADO daquela corrida.
MAX_ARQUIVOS = 4000
MAX_BYTES_TOTAL = 24 * 1024 * 1024
MAX_BYTES_ARQUIVO = 1500 * 1024
MAX_LINHAS_ARQUIVO = 20000
MAX_COLUNAS_LINHA = 2000          # linha maior que isso e arquivo minificado
MAX_OCORRENCIAS_POR_CHAVE = 40    # teto do INDICE por chave (memoria)
MAX_LINHAS_VERIFICADAS = 400      # teto de linhas inspecionadas por claim
MAX_CLAIMS = 80
MAX_EVIDENCIAS = 3
JANELA_DEPOIS = 80                # chars apos o nome onde o valor costuma estar
JANELA_ANTES = 34

DIRS_IGNORADOS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", ".tox", "venv", ".venv", "env",
    "site-packages", "dist", "build", "target", ".idea", ".vscode",
    ".next", ".cache", "vendor", "third_party", ".eggs", "htmlcov",
}
EXT_CODIGO = {
    ".py", ".js", ".mjs", ".ts", ".tsx", ".jsx", ".java", ".go", ".rs", ".c",
    ".h", ".cc", ".cpp", ".hpp", ".rb", ".scala", ".m", ".mm", ".jl", ".r",
    ".lua", ".sh", ".bash", ".zsh", ".swift", ".kt", ".pl", ".php", ".sql",
    ".ipynb",
}
EXT_CONFIG = {
    ".yaml", ".yml", ".json", ".toml", ".ini", ".cfg", ".conf", ".env",
    ".properties", ".gin", ".mk", ".make",
}
EXT_DOC = {".md", ".rst", ".txt", ".tex", ".adoc", ".org"}
EXT_LIDAS = EXT_CODIGO | EXT_CONFIG | EXT_DOC

# ---------------------------------------------------------------- numeros
# Aceita 10,000 (milhar), 0.5, 3e-4 e 92.3%. O sinal fica fora do grupo base
# porque em codigo o '-' quase sempre e operador, nao parte do literal.
NUM = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][-+]?\d+)?%?"
NUM_SIN = r"[-+]?" + NUM
# Numero dentro de uma linha de codigo: o olhar-para-tras evita capturar o "1"
# de f1_score e o "2" de v2.py como se fossem valores.
RE_NUM_LINHA = re.compile(r"(?<![A-Za-z0-9_.])(" + NUM_SIN + r")(?![A-Za-z_])")

# Ligacao entre o nome e o valor no texto do paper. E uma lista FECHADA de
# conectores em vez de um "qualquer coisa ate o numero": com gap livre,
# "batch size and learning rate of 3e-4" viraria batch_size=3e-4, que e falso.
_LIG = (r"(?:\s*(?:of|is|was|were|are|to|at|set|equal|fixed|about|"
        r"approximately|around|roughly|only|just)\b|\s*[=:~]|\s*\([^)\n]{0,20}\))*")
RE_LIGACAO_VALOR = re.compile(_LIG + r"\s*(" + NUM_SIN + r")")

# Papers escrevem tanto "dropout of 0.1" quanto "12 layers"/"92.3% accuracy".
# Sem o sentido inverso metade dos numeros do artigo passa batido.
RE_REF_TABELA = re.compile(
    r"(?:table|figure|fig|section|sec|equation|eq|appendix|algorithm)\s*\.?\s*$", re.I)
# 'seed' fica de fora do inverso: "3 seeds" quase sempre quer dizer TRES
# execucoes, nao a semente 3 — viraria DIVERGENTE falso contra seed=1337.
SEM_REVERSO = {"seed"}


def _reverso(texto: str, padrao: str):
    rx = re.compile(r"(?<![A-Za-z0-9_.])(" + NUM_SIN + r")[ \t-]{1,3}(?:" + padrao +
                    r")(?![A-Za-z])", re.IGNORECASE)
    for m in rx.finditer(texto):
        if RE_REF_TABELA.search(texto[max(0, m.start() - 24):m.start()].rstrip()):
            continue   # "Table 3 layers" e referencia cruzada, nao hiperparametro
        yield m

# ------------------------------------------------- vocabulario dos claims
# (regex no paper, nome canonico, apelidos procurados no codigo).
# Vocabulario curado em vez de generico: prefiro perder claim (recall menor) a
# inventar claim que o paper nao fez (precisao alta). O recall parcial esta
# declarado em 'limites'.
VOCAB_HIPER = [
    (r"learning rates?", "learning_rate", ("learning_rate", "lr", "learningrate", "step_size", "eta")),
    (r"(?:mini-?)?batch sizes?", "batch_size", ("batch_size", "batchsize", "bs", "minibatch_size", "train_batch_size")),
    (r"dropout(?: rate| probability)?", "dropout", ("dropout", "dropout_rate", "drop_rate", "p_drop", "dropout_p")),
    (r"weight decay", "weight_decay", ("weight_decay", "wd", "l2", "l2_reg")),
    (r"momentum", "momentum", ("momentum", "beta1")),
    (r"temperature", "temperature", ("temperature", "temp")),
    (r"top-?p", "top_p", ("top_p", "nucleus", "topp")),
    (r"top-?k", "top_k", ("top_k", "topk")),
    (r"beam (?:size|width)", "beam_size", ("beam_size", "num_beams", "beam_width")),
    (r"hidden (?:size|dimension|dim|units)", "hidden_size", ("hidden_size", "hidden_dim", "d_model", "n_hidden", "hidden_units")),
    (r"embedding (?:size|dimension|dim)", "embedding_dim", ("embedding_dim", "embedding_size", "emb_dim", "embed_dim", "d_model")),
    (r"(?:number of |num\.? of |num )?layers", "num_layers", ("num_layers", "n_layers", "nlayers", "layers", "depth")),
    (r"(?:number of |num\.? of |num )?(?:attention )?heads", "num_heads", ("num_heads", "n_heads", "nheads", "heads")),
    (r"(?:number of |num\.? of |max )?epochs", "epochs", ("epochs", "num_epochs", "n_epochs", "max_epochs")),
    (r"(?:sequence|context|input|block) length", "seq_len", ("seq_len", "sequence_length", "max_len", "max_length", "context_length", "block_size")),
    (r"vocab(?:ulary)? size", "vocab_size", ("vocab_size", "vocabulary_size", "n_vocab")),
    (r"warm-?up steps?", "warmup_steps", ("warmup_steps", "warmup", "n_warmup_steps", "warmup_ratio")),
    (r"(?:random )?seeds?", "seed", ("seed", "random_seed", "rng_seed", "manual_seed")),
    (r"patience", "patience", ("patience", "early_stopping_patience")),
    (r"thresholds?", "threshold", ("threshold", "thresh", "cutoff", "limiar", "min_score")),
    (r"window sizes?", "window_size", ("window_size", "window", "win_size")),
    (r"kernel sizes?", "kernel_size", ("kernel_size", "k_size")),
    (r"strides?", "stride", ("stride", "strides")),
    (r"gradient clip(?:ping)?(?: norm)?", "grad_clip", ("grad_clip", "clip_grad", "max_grad_norm", "clip_norm")),
    (r"label smoothing", "label_smoothing", ("label_smoothing", "smoothing")),
    (r"(?:number of |num )workers", "num_workers", ("num_workers", "n_workers", "workers")),
    (r"chunk sizes?", "chunk_size", ("chunk_size", "chunksize")),
    (r"max(?:imum)? (?:new )?tokens?", "max_tokens", ("max_tokens", "max_new_tokens")),
    (r"(?:max(?:imum)? )?retries", "retries", ("retries", "max_retries", "n_retries")),
    (r"timeouts?", "timeout", ("timeout", "timeout_s", "timeout_seconds", "timeout_ms")),
    (r"tolerance", "tol", ("tol", "tolerance", "atol", "rtol")),
    (r"(?:number of |num )clusters", "n_clusters", ("n_clusters", "num_clusters")),
    (r"(?:number of |num )samples", "n_samples", ("n_samples", "num_samples")),
]
VOCAB_METRICA = [
    (r"top-?1 accuracy", "top1_accuracy", ("top1", "top_1", "top1_acc", "accuracy", "acc")),
    (r"top-?5 accuracy", "top5_accuracy", ("top5", "top_5", "top5_acc")),
    (r"accuracy", "accuracy", ("accuracy", "acc", "acuracia")),
    (r"precision(?:@\d+)?", "precision", ("precision", "prec", "precisao")),
    (r"recall(?:@\d+)?", "recall", ("recall", "revocacao")),
    (r"f1(?:[ -]?score)?|f-?measure", "f1", ("f1", "f1_score", "fscore", "f_measure")),
    (r"bleu(?:-\d+)?", "bleu", ("bleu", "bleu_score")),
    (r"rouge(?:-[lL\d])?", "rouge", ("rouge", "rouge_l", "rouge_score")),
    (r"meteor", "meteor", ("meteor",)),
    (r"perplexity|\bppl\b", "perplexity", ("perplexity", "ppl")),
    (r"n?dcg(?:@\d+)?", "ndcg", ("ndcg", "dcg", "ndcg_at_k")),
    (r"\bmrr\b", "mrr", ("mrr", "mean_reciprocal_rank")),
    (r"\bmap@\d+|\bmap\b", "map", ("map", "mean_average_precision")),
    (r"auroc|auc(?:-roc)?", "auc", ("auc", "auroc", "roc_auc")),
    (r"\bwer\b", "wer", ("wer", "word_error_rate")),
    (r"\bcer\b", "cer", ("cer",)),
    (r"exact match(?: score)?", "exact_match", ("exact_match", "em_score", "exact")),
    (r"\biou\b|intersection over union", "iou", ("iou", "jaccard")),
    (r"dice(?: score| coefficient)?", "dice", ("dice", "dice_score")),
    (r"\brmse\b", "rmse", ("rmse",)),
    (r"\bmae\b", "mae", ("mae",)),
    (r"\bmse\b", "mse", ("mse",)),
    (r"r\^?2\b|r-squared", "r2", ("r2", "r_squared")),
    (r"spearman(?:'s)?(?: correlation| rho)?", "spearman", ("spearman", "spearmanr")),
    (r"pearson(?:'s)?(?: correlation)?", "pearson", ("pearson", "pearsonr")),
    (r"speed-?ups?", "speedup", ("speedup", "speed_up")),
    (r"latency", "latency", ("latency", "latencia")),
    (r"throughput", "throughput", ("throughput",)),
    (r"coverage", "coverage", ("coverage", "cobertura")),
]

# Palavras que aparecem entre crases/parenteses num paper e NAO sao codigo.
PARADAS = {
    "the", "and", "for", "with", "this", "that", "from", "our", "we", "is",
    "are", "was", "were", "use", "used", "using", "see", "eg", "ie", "et", "al",
    "table", "figure", "fig", "section", "appendix", "equation", "eq", "note",
    "all", "any", "one", "two", "both", "each", "such", "then", "than", "also",
    "where", "which", "when", "what", "into", "over", "under", "same", "other",
    "paper", "papers", "code", "repo", "repository", "results", "result",
    "method", "methods", "approach", "however", "thus", "here", "there",
}


# ============================================================ utilitarios
def _limpar(txt: str, tamanho: int = 200) -> str:
    """Trecho de evidencia em uma linha: sem controle, sem sobra de espaco."""
    txt = "".join(c if c.isprintable() or c == " " else " " for c in txt)
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt[:tamanho]


def _para_num(txt: str):
    """('92.3%' | '10,000' | '3e-4') -> (valor float, era_percentual)."""
    t = txt.strip()
    pct = t.endswith("%")
    t = t.rstrip("%").replace(",", "")
    try:
        return float(t), pct
    except ValueError:
        return None


def _casas(txt: str) -> int:
    """Casas decimais do literal como o paper escreveu — usado para nao acusar
    divergencia quando a unica diferenca e o codigo ter mais precisao."""
    t = txt.rstrip("%").replace(",", "")
    if "e" in t.lower():
        return 12
    return len(t.split(".")[1]) if "." in t else 0


def _batem(a: float, b: float, casas: int) -> bool:
    if math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12):
        return True
    if casas < 12:
        return round(a, casas) == round(b, casas)
    return False


_RE_CAMELO = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def _partes(nome: str) -> list:
    """batchSize / batch-size / BATCH_SIZE -> ['batch','size'].
    Unifica as tres grafias num unico jeito de comparar."""
    s = _RE_CAMELO.sub("_", nome.strip("-_ "))
    return [p for p in re.split(r"[-_\s]+", s.lower()) if p]


def _chaves(nome: str) -> list:
    """Chaves de indice/consulta de um nome: forma com separador e forma colada
    (batch_size e batchsize sao o MESMO parametro para quem audita)."""
    p = _partes(nome)
    if not p:
        return []
    return list(dict.fromkeys(k for k in ("_".join(p), "".join(p)) if k))


def _regex_nome(nome: str):
    """Regex que acha o nome no texto cru em qualquer grafia usual."""
    p = [re.escape(x) for x in _partes(nome)]
    if not p:
        return None
    return re.compile(r"(?<![A-Za-z0-9_])" + r"[-_ ]?".join(p) + r"(?![A-Za-z0-9_])",
                      re.IGNORECASE)


# ====================================================== leitura do repo
def _tipo_arquivo(ext: str) -> str:
    if ext in EXT_CODIGO:
        return "codigo"
    if ext in EXT_CONFIG:
        return "config"
    return "doc"


def carregar_repo(raiz: Path) -> dict:
    """Le o repo uma unica vez e monta um indice token -> ocorrencias.

    Indice em vez de varrer por claim: com N claims a varredura ingenua seria N
    passadas sobre o disco; aqui e uma passada so e cada consulta e O(1)."""
    arquivos, indice, identidade, saturadas = [], {}, {}, set()
    stats = {"arquivos_lidos": 0, "arquivos_ignorados": 0, "bytes_lidos": 0,
             "linhas_lidas": 0, "truncado": False, "motivo_truncagem": "",
             "chaves_saturadas": 0}
    parcial = {"arquivos": arquivos, "indice": indice, "identidade": identidade,
               "saturadas": saturadas, "stats": stats, "raiz": raiz}
    for dirpath, dirnames, filenames in os.walk(raiz):
        dirnames[:] = sorted(d for d in dirnames
                             if d not in DIRS_IGNORADOS and not d.startswith("."))
        for nome in sorted(filenames):
            if stats["arquivos_lidos"] >= MAX_ARQUIVOS:
                stats["truncado"] = True
                stats["motivo_truncagem"] = "limite de arquivos"
                return parcial
            if stats["bytes_lidos"] >= MAX_BYTES_TOTAL:
                stats["truncado"] = True
                stats["motivo_truncagem"] = "limite de bytes"
                return parcial
            caminho = Path(dirpath) / nome
            ext = caminho.suffix.lower()
            if ext not in EXT_LIDAS:
                stats["arquivos_ignorados"] += 1
                continue
            try:
                if caminho.is_symlink() or not caminho.is_file():
                    stats["arquivos_ignorados"] += 1
                    continue
                if caminho.stat().st_size > MAX_BYTES_ARQUIVO:
                    stats["arquivos_ignorados"] += 1
                    continue
                bruto = caminho.read_bytes()
            except OSError:
                stats["arquivos_ignorados"] += 1
                continue
            if b"\x00" in bruto[:4096]:      # binario disfarcado de texto
                stats["arquivos_ignorados"] += 1
                continue
            linhas = bruto.decode("utf-8", errors="replace").splitlines()[:MAX_LINHAS_ARQUIVO]
            if linhas and (sum(len(x) for x in linhas) / len(linhas)) > MAX_COLUNAS_LINHA:
                stats["arquivos_ignorados"] += 1   # minificado: so faria ruido
                continue
            try:
                rel = str(caminho.relative_to(raiz))
            except ValueError:
                rel = str(caminho)
            fidx = len(arquivos)
            arquivos.append({"caminho": rel, "tipo": _tipo_arquivo(ext),
                             "linhas": linhas, "stem": caminho.stem})
            stats["arquivos_lidos"] += 1
            stats["bytes_lidos"] += len(bruto)
            stats["linhas_lidas"] += len(linhas)
            _indexar(indice, identidade, saturadas, fidx, linhas,
                     caminho.stem, rel)
    stats["chaves_saturadas"] = len(saturadas)
    return parcial


_RE_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_\-]*")


def _indexar(indice: dict, identidade: dict, saturadas: set, fidx: int,
             linhas: list, stem: str, rel: str) -> None:
    """Dois indices distintos, de proposito.

    'identidade' (nome e caminho do arquivo) NAO tem teto: e a evidencia mais
    forte que existe — train_loop.py responde pelo modulo `train_loop` mesmo
    que o identificador nunca apareca escrito. Perder isso por causa de um
    limite de memoria seria trocar a melhor prova pela pior.

    'indice' (tokens das linhas) tem teto por chave, senao um token banal como
    'timeout' guardaria milhares de posicoes. Quando o teto e atingido a chave
    entra em 'saturadas' e a consulta cai numa varredura exaustiva — sem isso a
    skill acusaria DIVERGENTE so porque o valor certo estava na ocorrencia 41.
    """
    # nome do arquivo e evidencia FORTE; pedaco do caminho e fraca. Sem separar
    # as duas, 'policy.py' seria respondido por cognition/engine_policy.py antes
    # de kernel/policy.py, que e o arquivo de que o paper fala.
    for chave in _chaves(stem):
        identidade.setdefault(chave, []).append(fidx)
    for chave in (x for x in _partes(rel) if len(x) > 2):
        identidade.setdefault("~" + chave, []).append(fidx)
    for n, linha in enumerate(linhas, start=1):
        if len(linha) > MAX_COLUNAS_LINHA:
            continue
        vistos = set()
        for tok in _RE_TOKEN.findall(linha):
            chaves = _chaves(tok)
            if "-" in tok or "_" in tok:
                # tambem indexo cada pedaco: em '--batch-size' o claim pode ser
                # so 'size'/'batch' e sem isso a ocorrencia sumiria
                chaves += [x for x in _partes(tok) if len(x) > 2]
            for chave in chaves:
                if chave in vistos:
                    continue
                vistos.add(chave)
                lista = indice.setdefault(chave, [])
                if len(lista) < MAX_OCORRENCIAS_POR_CHAVE:
                    lista.append((fidx, n))
                else:
                    saturadas.add(chave)


def buscar(repo: dict, nomes) -> tuple:
    """(ocorrencias, completo). 'completo' False significa que houve corte —
    quem le o veredito precisa saber que a busca foi por amostra."""
    achados, vistos = [], set()
    for nome in nomes:
        for chave in _chaves(nome):
            for fidx in repo["identidade"].get(chave, ()):
                if (fidx, 0) not in vistos:
                    vistos.add((fidx, 0))
                    achados.append((fidx, 0))
    fracas = [(fidx, 0) for nome in nomes for chave in _chaves(nome)
              for fidx in repo["identidade"].get("~" + chave, ())]
    for par in fracas:
        if par not in vistos:
            vistos.add(par)
            achados.append(par)
    saturou = any(c in repo["saturadas"] for n in nomes for c in _chaves(n))
    if saturou:
        pares = _varredura(repo, nomes)
    else:
        pares = [par for nome in nomes for chave in _chaves(nome)
                 for par in repo["indice"].get(chave, ())]
    for par in pares:
        if par not in vistos:
            vistos.add(par)
            achados.append(par)
    # codigo primeiro: evidencia em src vale mais do que evidencia em README
    ordem = {"codigo": 0, "config": 1, "doc": 2}
    chegada = {par: i for i, par in enumerate(achados)}
    achados.sort(key=lambda p: (ordem.get(repo["arquivos"][p[0]]["tipo"], 3),
                                chegada[p]))
    return achados[:MAX_LINHAS_VERIFICADAS], len(achados) <= MAX_LINHAS_VERIFICADAS


def _varredura(repo: dict, nomes) -> list:
    """Passada exaustiva para nome saturado. Uma unica alternancia de regex em
    vez de uma regex por apelido: e a diferenca entre 40 ms e meio segundo."""
    partes = [r.pattern for r in (_regex_nome(n) for n in nomes) if r]
    if not partes:
        return []
    rx = re.compile("|".join("(?:%s)" % x for x in partes), re.IGNORECASE)
    return [(fidx, n)
            for fidx, arq in enumerate(repo["arquivos"])
            for n, linha in enumerate(arq["linhas"], start=1)
            if rx.search(linha)]


# ================================================ extracao dos claims
def normalizar_paper(t: str) -> str:
    """PDF->txt estraga sinal e notacao cientifica; sem isto '3 x 10-4' nunca
    casaria com o 3e-4 do codigo e o menos unicode viraria lixo."""
    tab = {"−": "-", "–": "-", "—": "-", "×": "x",
           "’": "'", "‘": "'", "“": '"', "”": '"',
           "≈": "~", " ": " ", "ﬁ": "fi", "ﬂ": "fl"}
    for a, b in tab.items():
        t = t.replace(a, b)
    return re.sub(r"(\d+(?:\.\d+)?)\s*[x*]\s*10\s*\^?\s*\(?(-?\d+)\)?", r"\1e\2", t)


def _linha_de(offsets: list, pos: int) -> int:
    return bisect.bisect_right(offsets, pos)


def extrair_claims(texto: str) -> tuple:
    """Devolve (claims, descartados). Cada claim traz o trecho literal e a linha
    do paper — auditoria sem rastro de volta a fonte nao serve para nada."""
    offsets = [m.start() for m in re.finditer(r"\n", texto)]
    claims, descartados = [], 0
    vistos = set()

    def add(tipo, nome, apelidos, valor_txt, ini, fim):
        nonlocal descartados
        val = _para_num(valor_txt) if valor_txt is not None else None
        if valor_txt is not None and val is None:
            descartados += 1
            return
        chave = (tipo, "_".join(_partes(nome)), valor_txt)
        if chave in vistos:
            descartados += 1
            return
        vistos.add(chave)
        claims.append({
            "id": len(claims) + 1, "tipo": tipo, "nome": nome,
            "apelidos_procurados": list(apelidos),
            "valor": None if val is None else val[0],
            "valor_texto": valor_txt,
            "percentual": bool(val[1]) if val else False,
            "casas": _casas(valor_txt) if valor_txt else 0,
            "linha_paper": _linha_de(offsets, ini) + 1,
            "afirmacao": _limpar(texto[max(0, ini - 40):fim + 30], 160),
        })

    # --- familia 1: hiperparametro / default -----------------------------
    for padrao, canonico, apelidos in VOCAB_HIPER:
        for m in re.finditer(padrao, texto, re.IGNORECASE):
            lig = RE_LIGACAO_VALOR.match(texto, m.end())
            if lig:
                add("hiperparametro", canonico, apelidos, lig.group(1),
                    m.start(), lig.end())
        if canonico not in SEM_REVERSO:
            for m in _reverso(texto, padrao):
                add("hiperparametro", canonico, apelidos, m.group(1),
                    m.start(), m.end())
    # nome_de_codigo = 3e-4 escrito direto no corpo do paper
    for m in re.finditer(r"(?<![A-Za-z0-9_])([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\s*[=:]\s*("
                         + NUM_SIN + r")", texto):
        add("hiperparametro", m.group(1), (m.group(1),), m.group(2), m.start(), m.end())
    # flag de linha de comando: --batch-size 64
    for m in re.finditer(r"--([A-Za-z][A-Za-z0-9_\-]{1,30})[= ]\s*(" + NUM_SIN + r")", texto):
        add("hiperparametro", m.group(1), (m.group(1),), m.group(2), m.start(), m.end())

    # --- familia 2: nome de funcao / modulo / classe ----------------------
    def nome_ok(bruto: str) -> str:
        n = bruto.strip().strip("`").rstrip("()").strip(".,;:")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]{1,60}", n or ""):
            return ""
        base = n.split(".")[-1]
        if len(base) < 3 or base.lower() in PARADAS:
            return ""
        # so aceita o que PARECE identificador: tem _, tem ponto, tem digito ou
        # e CamelCase. Palavra minuscula solta e prosa do artigo, nao API.
        if not ("_" in n or "." in n or any(c.isdigit() for c in n)
                or _RE_CAMELO.search(n)):
            return ""
        return n

    for m in re.finditer(r"`([^`\n]{2,60})`", texto):
        n = nome_ok(m.group(1))
        if n:
            add("nome", n, (n.split(".")[-1], n), None, m.start(), m.end())
    for m in re.finditer(r"(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_.]*)\s*\(\s*\)", texto):
        n = nome_ok(m.group(1))
        if n:
            add("nome", n, (n.split(".")[-1], n), None, m.start(), m.end())
    for m in re.finditer(r"(?<![\w/.])([A-Za-z0-9_\-]{2,50}\.(?:py|js|ts|go|rs|java|rb|cpp|sh))(?![\w])", texto):
        n = m.group(1)
        add("nome", n, (n.rsplit(".", 1)[0], n), None, m.start(), m.end())
    for m in re.finditer(r"\b(?:class|function|module|package|method|routine)\s+`?"
                         r"([A-Za-z_][A-Za-z0-9_.]{2,50})`?", texto, re.IGNORECASE):
        n = nome_ok(m.group(1))
        if n:
            add("nome", n, (n.split(".")[-1], n), None, m.start(), m.end())

    # --- familia 3: metrica com numero -----------------------------------
    for padrao, canonico, apelidos in VOCAB_METRICA:
        for m in re.finditer(padrao + r"(?:\s+scores?)?", texto, re.IGNORECASE):
            lig = RE_LIGACAO_VALOR.match(texto, m.end())
            if lig:
                add("metrica", canonico, apelidos, lig.group(1), m.start(), lig.end())
        for m in _reverso(texto, padrao):
            add("metrica", canonico, apelidos, m.group(1), m.start(), m.end())

    claims.sort(key=lambda c: (c["linha_paper"], c["id"]))
    for i, c in enumerate(claims, start=1):
        c["id"] = i
    return claims, descartados


# ================================================ verificacao no codigo
def _valores_perto(linha: str, rx) -> list:
    """Numeros na vizinhanca do nome, em ordem de confianca.
    Olha para a FRENTE (default=32, lr: 3e-4) e, so quando nao acha nada la,
    para tras (0.1  # dropout) — por isso o achado de tras vem marcado."""
    frente, tras = [], []
    for m in rx.finditer(linha):
        depois = linha[m.end():m.end() + JANELA_DEPOIS]
        for i, mv in enumerate(RE_NUM_LINHA.finditer(depois)):
            if i >= 3:
                break
            v = _para_num(mv.group(1))
            if v:
                frente.append((v[0], mv.group(1), "depois" if i == 0 else "depois_2a"))
        antes = list(RE_NUM_LINHA.finditer(linha[max(0, m.start() - JANELA_ANTES):m.start()]))
        if antes:
            v = _para_num(antes[-1].group(1))
            if v:
                tras.append((v[0], antes[-1].group(1), "antes"))
    return frente if frente else tras


def _evidencia(repo: dict, fidx: int, nlin: int, valor=None, nota="") -> dict:
    arq = repo["arquivos"][fidx]
    trecho = ("(nome do proprio arquivo/caminho)" if nlin == 0
              else _limpar(arq["linhas"][nlin - 1]))
    ev = {"arquivo": arq["caminho"], "linha": nlin, "tipo_arquivo": arq["tipo"],
          "trecho": trecho}
    if valor is not None:
        ev["valor_no_codigo"] = valor
    if nota:
        ev["nota"] = nota
    return ev


def _verificar_valor(repo: dict, claim: dict) -> dict:
    """Hiperparametro e metrica: so e ENCONTRADO se o VALOR bater. Nome achado
    com outro numero e DIVERGENTE — e esse o achado que interessa a auditoria."""
    nomes = [claim["nome"]] + list(claim["apelidos_procurados"])
    ocorrencias, completo = buscar(repo, nomes)
    corte = ("" if completo else
             " (busca por AMOSTRA: o nome ocorre em mais linhas do que o teto)")
    if not ocorrencias:
        return {"status": "NAO_ENCONTRADO", "confianca": "alta",
                "nota": "nenhuma grafia do nome aparece no repositorio",
                "evidencias": []}
    rxs = [r for r in (_regex_nome(n) for n in nomes) if r]
    batem, divergem, so_nome = [], [], []
    alvo, casas = claim["valor"], claim["casas"]
    for fidx, nlin in ocorrencias:
        if nlin == 0:
            continue
        linha = repo["arquivos"][fidx]["linhas"][nlin - 1]
        vals = []
        for rx in rxs:
            vals.extend(_valores_perto(linha, rx))
        if not vals:
            so_nome.append((fidx, nlin))
            continue
        casou = False
        for v, _txt, origem in vals:
            if _batem(alvo, v, casas):
                batem.append((fidx, nlin, v, origem, ""))
                casou = True
                break
            # o paper as vezes escreve 92.3% para o 0.923 do codigo: aceito,
            # mas com nota, porque a escala e uma diferenca real de leitura
            if claim["percentual"] and _batem(alvo / 100.0, v, max(casas + 2, 4)):
                batem.append((fidx, nlin, v, origem, "mesmo valor em escala 0-1"))
                casou = True
                break
        if not casou:
            divergem.append((fidx, nlin, vals[0][0], vals[0][2]))
    if batem:
        conf, notas = "alta", []
        if all(repo["arquivos"][f]["tipo"] == "doc" for f, _, _, _, _ in batem):
            conf = "baixa"
            notas.append("valor confere so em documentacao, nao em codigo")
        elif all(o != "depois" for _, _, _, o, _ in batem):
            conf = "media"
            notas.append("valor lido na mesma linha, mas nao logo apos o nome")
        notas += [n for *_, n in batem if n]
        return {"status": "ENCONTRADO", "confianca": conf, "nota": "; ".join(notas),
                "evidencias": [_evidencia(repo, f, l, v, n)
                               for f, l, v, _, n in batem[:MAX_EVIDENCIAS]]}
    if divergem:
        return {"status": "DIVERGENTE", "confianca": "alta" if completo else "media",
                "nota": "nome existe no repositorio com valor diferente do paper" + corte,
                "evidencias": [_evidencia(repo, f, l, v)
                               for f, l, v, _ in divergem[:MAX_EVIDENCIAS]]}
    return {"status": "NAO_ENCONTRADO", "confianca": "baixa",
            "nota": ("nome aparece em %d linha(s), mas sem numero legivel ao lado"
                     " — o VALOR do paper nao pode ser confirmado nem negado"
                     % len(so_nome)) + corte,
            "evidencias": [_evidencia(repo, f, l) for f, l in so_nome[:MAX_EVIDENCIAS]]}


_RE_DEF = r"(?:def|class|fn|func|function|struct|impl|type|interface|procedure|sub)"


def _verificar_nome(repo: dict, claim: dict) -> dict:
    """Nome de funcao/modulo: DIVERGENTE aqui significa 'existe no repositorio,
    mas so fora do codigo' — o paper cita implementacao que so consta em texto."""
    nomes = [claim["nome"]] + list(claim["apelidos_procurados"])
    ocorrencias, completo = buscar(repo, nomes)
    corte = ("" if completo else
             " (busca por AMOSTRA: o nome ocorre em mais linhas do que o teto)")
    if not ocorrencias:
        return {"status": "NAO_ENCONTRADO", "confianca": "alta",
                "nota": "nome nao aparece em nenhum arquivo lido",
                "evidencias": []}
    base = claim["nome"].split(".")[-1].rsplit("/", 1)[-1]
    if base.endswith((".py", ".js", ".ts", ".go", ".rs", ".java", ".rb", ".cpp", ".sh")):
        base = base.rsplit(".", 1)[0]
    rx_def = re.compile(r"(?<![A-Za-z0-9_])" + _RE_DEF + r"\s+" +
                        r"[-_ ]?".join(re.escape(p) for p in _partes(base)) +
                        r"(?![A-Za-z0-9_])", re.IGNORECASE)
    defs, usos_codigo, fora = [], [], []
    for fidx, nlin in ocorrencias:
        arq = repo["arquivos"][fidx]
        if arq["tipo"] != "codigo":
            fora.append((fidx, nlin))
        elif nlin == 0:
            defs.append((fidx, nlin, "nome do arquivo bate com o nome citado"))
        elif rx_def.search(arq["linhas"][nlin - 1]):
            defs.append((fidx, nlin, "definicao"))
        else:
            usos_codigo.append((fidx, nlin))
    if defs:
        return {"status": "ENCONTRADO", "confianca": "alta",
                "nota": "definicao localizada no codigo",
                "evidencias": [_evidencia(repo, f, l, None, n)
                               for f, l, n in defs[:MAX_EVIDENCIAS]]}
    if usos_codigo:
        return {"status": "ENCONTRADO", "confianca": "media",
                "nota": ("aparece em codigo apenas como uso/mencao; nao achei "
                         "def/class com esse nome (pode ser import de terceiro)"),
                "evidencias": [_evidencia(repo, f, l)
                               for f, l in usos_codigo[:MAX_EVIDENCIAS]]}
    return {"status": "DIVERGENTE", "confianca": "alta" if completo else "media",
            "nota": ("citado como codigo no paper, mas no repo so aparece em "
                     "documentacao/config — nao ha implementacao com esse nome") + corte,
            "evidencias": [_evidencia(repo, f, l) for f, l in fora[:MAX_EVIDENCIAS]]}


# ================================================== entrada e relatorio
def _ler_argumentos(argumentos: dict) -> dict:
    def pega(*chaves, **kw):
        for k in chaves:
            if argumentos.get(k) not in (None, ""):
                return argumentos[k]
        return kw.get("padrao")
    try:
        teto = int(pega("max_claims", padrao=MAX_CLAIMS))
    except (TypeError, ValueError):
        teto = MAX_CLAIMS
    return {
        "repo": pega("repo", "repositorio", "codigo", "repo_dir"),
        "paper": pega("paper", "paper_txt", "arquivo_paper"),
        "paper_texto": pega("paper_texto", "texto"),
        "saida": pega("saida", "relatorio", "output"),
        "max_claims": max(1, teto),
    }


def executar(argumentos: dict) -> dict:
    a = _ler_argumentos(argumentos)
    problemas, avisos = [], []
    saida = {"ok": False, "skill": "paper-audit-core", "versao": VERSAO,
             "rede_usada": False, "problemas": problemas, "avisos": avisos}
    if not a["repo"]:
        problemas.append("faltou 'repo': caminho do repositorio JA clonado")
    if not a["paper"] and not a["paper_texto"]:
        problemas.append("faltou 'paper' (arquivo de texto) ou 'paper_texto'")
    if problemas:
        saida["erro"] = "argumentos insuficientes"
        return saida
    raiz = Path(str(a["repo"])).expanduser()
    if not raiz.is_dir():
        problemas.append("repo nao e um diretorio existente: %s" % raiz)
        saida["erro"] = "repo inacessivel"
        return saida

    # --- paper ---
    if a["paper_texto"]:
        texto, origem_paper = str(a["paper_texto"]), "(texto inline)"
    else:
        pp = Path(str(a["paper"])).expanduser()
        origem_paper = str(pp)
        if not pp.is_file():
            problemas.append("paper nao encontrado: %s" % pp)
            saida["erro"] = "paper inacessivel"
            return saida
        try:
            bruto = pp.read_bytes()
        except OSError as e:
            problemas.append("nao consegui ler o paper: %s" % e)
            saida["erro"] = "paper ilegivel"
            return saida
        if bruto[:5] == b"%PDF-":
            # Honestidade: sem dependencia externa nao ha como extrair texto de
            # PDF, e adivinhar o conteudo seria pior do que recusar.
            problemas.append("o arquivo e PDF binario; esta skill le TEXTO puro "
                             "(stdlib, sem parser de PDF). Extraia o texto antes "
                             "e passe o .txt")
            saida["erro"] = "formato nao suportado: PDF"
            return saida
        texto = bruto.decode("utf-8", errors="replace")
    texto = normalizar_paper(texto)
    if len(texto.strip()) < 40:
        problemas.append("texto do paper tem menos de 40 caracteres uteis")
        saida["erro"] = "paper vazio"
        return saida

    claims, descartados = extrair_claims(texto)
    truncou_claims = len(claims) > a["max_claims"]
    if truncou_claims:
        avisos.append("paper rendeu %d claims; analisei os %d primeiros (max_claims)"
                      % (len(claims), a["max_claims"]))
        claims = claims[:a["max_claims"]]

    # --- repo ---
    repo = carregar_repo(raiz)
    st = repo["stats"]
    if st["arquivos_lidos"] == 0:
        problemas.append("nenhum arquivo de texto/codigo legivel em %s" % raiz)
        saida["erro"] = "repo sem material analisavel"
        return saida
    if st["truncado"]:
        avisos.append("varredura TRUNCADA (%s): nesta corrida NAO_ENCONTRADO nao "
                      "e conclusivo" % st["motivo_truncagem"])
    if not claims:
        avisos.append("nenhuma afirmacao verificavel foi extraida do paper — "
                      "o texto pode nao trazer hiperparametro, nome de codigo "
                      "nem metrica com numero nos padroes cobertos")

    achados = []
    for c in claims:
        r = _verificar_nome(repo, c) if c["tipo"] == "nome" else _verificar_valor(repo, c)
        achados.append({
            "id": c["id"], "tipo": c["tipo"], "nome": c["nome"],
            "valor_no_paper": c["valor_texto"], "linha_paper": c["linha_paper"],
            "afirmacao": c["afirmacao"], "status": r["status"],
            "confianca": r["confianca"], "nota": r["nota"],
            "evidencias": r["evidencias"],
        })

    por_status = {"ENCONTRADO": 0, "NAO_ENCONTRADO": 0, "DIVERGENTE": 0}
    por_tipo = {}
    for x in achados:
        por_status[x["status"]] = por_status.get(x["status"], 0) + 1
        d = por_tipo.setdefault(x["tipo"], {"ENCONTRADO": 0, "NAO_ENCONTRADO": 0,
                                            "DIVERGENTE": 0})
        d[x["status"]] += 1

    limites = [
        "so leitura local: nenhuma rede foi tocada; o repo precisa estar clonado",
        "claims saem de padrao lexico sobre vocabulario curado — afirmacao fora "
        "desses padroes nao vira claim (recall parcial, proposital)",
        "a comparacao de valor olha a MESMA linha do nome; valor montado em "
        "runtime, herdado de classe-mae ou vindo de config externa nao e visto",
        "NAO_ENCONTRADO nao prova erro do paper: metrica de resultado quase "
        "nunca esta no codigo-fonte",
        "para tipo 'nome', DIVERGENTE significa: existe no repositorio, porem "
        "fora de arquivo de codigo (so doc/config)",
        "PDF nao e lido (stdlib pura): passe o texto ja extraido",
    ]
    if st["truncado"]:
        limites.append("VARREDURA INCOMPLETA nesta corrida (%s)" % st["motivo_truncagem"])

    saida.update({
        "ok": True,
        "repo": str(raiz),
        "paper": origem_paper,
        "repo_stats": st,
        "paper_stats": {"caracteres": len(texto), "claims_extraidos": len(claims),
                        "trechos_descartados": descartados,
                        "truncado_por_max_claims": truncou_claims},
        "resumo": {"claims": len(achados), "por_status": por_status,
                   "por_tipo": por_tipo},
        "achados": achados,
        "limites": limites,
    })

    if a["saida"]:
        alvo = Path(str(a["saida"])).expanduser()
        if not alvo.parent.is_dir():
            # nao crio arvore de diretorio por conta propria: A1 autoriza
            # escrever arquivo, nao autoriza inventar layout no disco do dono
            problemas.append("nao gravei o relatorio: a pasta %s nao existe" % alvo.parent)
            saida["saida_escrita"] = False
            # Auditoria adversarial 23/08: o entregavel PEDIDO nao existe e o
            # processo dizia sucesso total. Quem chama testa `ok` e rc — os dois
            # mentiam. Escrita pedida que falha derruba o veredito.
            saida["ok"] = False
        else:
            try:
                alvo.write_text(json.dumps(saida, ensure_ascii=False, indent=2),
                                encoding="utf-8")
                saida["saida_escrita"] = True
                saida["saida"] = str(alvo)
            except OSError as e:
                problemas.append("falha ao gravar relatorio em %s: %s" % (alvo, e))
                saida["saida_escrita"] = False
                saida["ok"] = False   # idem: escrita pedida que falha nao e sucesso
    return saida


def _imprimir(obj: dict) -> None:
    # Sandbox costuma rodar com locale POSIX; sem isto um acento vindo de um
    # trecho de codigo derrubaria a skill inteira na hora do print.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    try:
        print(json.dumps(obj, ensure_ascii=False))
    except UnicodeEncodeError:
        print(json.dumps(obj, ensure_ascii=True))


if __name__ == "__main__":
    args = {}
    try:
        if len(sys.argv) > 1:
            with open(sys.argv[1], encoding="utf-8") as fh:
                args = json.load(fh)
        elif not sys.stdin.isatty():
            bruto = sys.stdin.read().strip()
            if bruto:
                args = json.loads(bruto)
    except (OSError, ValueError) as e:
        _imprimir({"ok": False, "skill": "paper-audit-core", "versao": VERSAO,
                   "erro": "argumentos ilegiveis: %s" % e,
                   "problemas": ["esperado: python3 audit_core.py args.json"]})
        sys.exit(2)
    resultado = executar(args if isinstance(args, dict) else {})
    _imprimir(resultado)
    sys.exit(0 if resultado.get("ok") else 1)
