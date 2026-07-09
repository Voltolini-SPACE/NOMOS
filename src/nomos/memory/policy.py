"""NOMOS Memory Engine — política fail-closed de admissão de memória.

Esta camada decide **se um conteúdo pode ser gravado**. A regra é conservadora:
na dúvida, bloqueia. Se qualquer detector dispara, a decisão é recusar com o
código exato ``MEMORY_REJECTED_FAIL_CLOSED`` e **nada é gravado**.

IMPORTANTE (auditoria de segurança)
-----------------------------------
Os padrões abaixo (``rm\\s+-rf``, ``curl``, ``sk-...`` etc.) são **assinaturas
de detecção** — strings/expressões regulares inertes usadas para RECONHECER
conteúdo perigoso e RECUSÁ-LO. Este módulo **não executa** nada: não há
``import subprocess``, ``os.system``, ``eval``, rede, nem qualquer efeito além
de ler o texto candidato e devolver um veredito. Um ``grep`` por "curl" ou
"rm" encontrará estas assinaturas — que provam o oposto de uso perigoso: elas
existem justamente para barrar esse uso.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

#: Código de recusa exigido pelo contrato da missão. Não alterar o texto.
REJECTION_CODE = "MEMORY_REJECTED_FAIL_CLOSED"

# Categorias agrupadas por qual flag de segurança elas acendem.
_SECRET_CATS = {
    "private_key", "ssh_key", "openai_key", "aws_key", "google_key",
    "github_token", "slack_token", "jwt", "generic_secret", "cookie",
    "authorization_bearer", "env_secret",
}
_PERSONAL_CATS = {"cpf", "cnpj", "credit_card", "iban", "seed_phrase"}
_DANGEROUS_CATS = {"dangerous_command"}

# (categoria, regex). Mantidos legíveis de propósito: são assinaturas inertes.
_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("private_key", re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----")),
    ("ssh_key", re.compile(r"\bssh-(?:rsa|ed25519|dss)\s+AAAA[0-9A-Za-z+/=]+")),
    ("openai_key", re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_\-]{16,}")),
    ("aws_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("google_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{20,}")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]+\.eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+")),
    ("authorization_bearer", re.compile(r"(?i)\bauthorization\b\s*[:=]\s*bearer\s+\S+")),
    ("cookie", re.compile(
        r"(?i)(?:\bset-cookie\b\s*[:=]|\bcookie\b\s*[:=]|"
        r"\b(?:sessionid|session_id|jsessionid|phpsessid|csrftoken|sid)\s*=\s*\S+)")),
    ("env_secret", re.compile(
        r"(?i)(?:process\.env\.[A-Z0-9_]*(?:KEY|SECRET|TOKEN|PASSWORD|PWD)"
        r"|os\.environ\[['\"][A-Z0-9_]*(?:KEY|SECRET|TOKEN|PASSWORD)"
        r"|export\s+[A-Z0-9_]*(?:KEY|SECRET|TOKEN|PASSWORD)\s*=)")),
    ("generic_secret", re.compile(
        r"(?i)\b(?:api[_\- ]?key|secret|client[_\- ]?secret|access[_\- ]?token"
        r"|auth[_\- ]?token|senha|password|passwd|pwd)\b\s*[:=]\s*['\"]?\S{6,}")),
    ("iban", re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")),
    ("seed_phrase", re.compile(
        r"(?i)(?:seed\s*phrase|mnemonic|recovery\s*phrase|frase\s*de\s*recupera"
        r"|frase\s*semente|palavras\s*de\s*recupera|(?:12|24)[\s\-]?word)")),
    # Comandos destrutivos — escritos como regex (ex.: rm\s+-rf) para detectar
    # sem serem, eles próprios, um comando literal executável.
    ("dangerous_command", re.compile(
        r"(?i)(?:\brm\s+-[a-z]*rf?[a-z]*\b|\bmkfs\b|\bdd\s+if=|\bchmod\s+777\b"
        r"|:\(\)\s*\{\s*:\|:&\s*\}\s*;:|(?:curl|wget)\b[^\n|]*\|\s*(?:ba)?sh\b"
        r"|>\s*/dev/sd[a-z]|\bsudo\s+rm\s+-)")),
]

# CPF/CNPJ formatados são sempre suspeitos; os "crus" passam por dígito
# verificador para evitar falso-positivo com números longos quaisquer.
_CPF_FMT = re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")
_CNPJ_FMT = re.compile(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b")
_DIGIT_RUN = re.compile(r"\d[\d .\-]{9,20}\d")


@dataclass(frozen=True)
class Finding:
    category: str
    #: rótulo humano — nunca ecoa o segredo detectado.
    detail: str = ""


@dataclass
class PolicyDecision:
    allowed: bool
    reason: str = "OK"
    findings: list[Finding] = field(default_factory=list)
    contains_secret: bool = False
    contains_personal_sensitive_data: bool = False
    human_review_required: bool = False

    def safety_block(self) -> dict:
        return {
            "contains_secret": self.contains_secret,
            "contains_personal_sensitive_data": self.contains_personal_sensitive_data,
            "human_review_required": self.human_review_required,
        }


def _only_digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def _luhn_ok(num: str) -> bool:
    if not num.isdigit() or len(num) < 12:
        return False
    total, parity = 0, len(num) % 2
    for i, ch in enumerate(num):
        d = int(ch)
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _cpf_ok(num: str) -> bool:
    if len(num) != 11 or num == num[0] * 11:
        return False

    def cd(base: str) -> str:
        w = len(base) + 1
        s = sum(int(c) * (w - i) for i, c in enumerate(base))
        r = 11 - (s % 11)
        return "0" if r >= 10 else str(r)

    d1 = cd(num[:9])
    d2 = cd(num[:9] + d1)
    return num[9] == d1 and num[10] == d2


def _cnpj_ok(num: str) -> bool:
    if len(num) != 14 or num == num[0] * 14:
        return False
    w1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    w2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]

    def cd(base: str, w: list[int]) -> str:
        s = sum(int(c) * ww for c, ww in zip(base, w, strict=False))
        r = s % 11
        return "0" if r < 2 else str(11 - r)

    d1 = cd(num[:12], w1)
    d2 = cd(num[:12] + d1, w2)
    return num[12] == d1 and num[13] == d2


def scan(text: str) -> list[Finding]:
    """Retorna TODOS os achados de risco no texto (lista vazia = limpo)."""
    if not isinstance(text, str):
        return [Finding("invalid_type", "conteúdo não textual")]
    found: list[Finding] = []
    seen: set[str] = set()

    def add(cat: str, detail: str = "") -> None:
        if cat not in seen:
            seen.add(cat)
            found.append(Finding(cat, detail))

    for cat, rx in _PATTERNS:
        if rx.search(text):
            add(cat, "assinatura detectada")

    if _CPF_FMT.search(text):
        add("cpf", "CPF formatado")
    if _CNPJ_FMT.search(text):
        add("cnpj", "CNPJ formatado")

    for run in _DIGIT_RUN.findall(text):
        digs = _only_digits(run)
        if len(digs) == 11 and _cpf_ok(digs):
            add("cpf", "CPF válido")
        elif len(digs) == 14 and _cnpj_ok(digs):
            add("cnpj", "CNPJ válido")
        elif 13 <= len(digs) <= 19 and _luhn_ok(digs):
            add("credit_card", "número passa Luhn")
    return found


def evaluate(text: str) -> PolicyDecision:
    """Veredito fail-closed. Bloqueia em qualquer achado ou conteúdo inválido."""
    if not isinstance(text, str) or not text.strip():
        return PolicyDecision(
            allowed=False, reason="EMPTY_OR_INVALID_CONTENT",
            human_review_required=True,
        )
    findings = scan(text)
    if not findings:
        return PolicyDecision(allowed=True, reason="OK")

    cats = {f.category for f in findings}
    return PolicyDecision(
        allowed=False,
        reason=REJECTION_CODE,
        findings=findings,
        contains_secret=bool(cats & _SECRET_CATS),
        contains_personal_sensitive_data=bool(cats & _PERSONAL_CATS),
        human_review_required=True,
    )
