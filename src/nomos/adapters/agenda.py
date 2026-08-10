"""NOMOS adapters.agenda — cron real + timezone aplicada (ABSORPTION-04 / FASES 1-2).

O censo da ABSORPTION-03 foi direto: "intervalo em segundos NÃO é cron", e
"timezone armazenada não é timezone aplicada". Este módulo fecha os dois.

## Por que um parser próprio

Nenhuma implementação de cron está disponível no ambiente (`croniter`,
`cron_converter`, `crontab`, `apscheduler` — todas ausentes), e o NOMOS declara
DUAS dependências no total (`cryptography`, `argon2-cffi`). Puxar uma terceira
para uma gramática de 5 campos, num projeto cuja premissa é superfície mínima
auditável, seria o trade errado.

Então: parser completo da sintaxe padrão, não simplificado —
`*`, `*/n`, `a-b`, `a-b/n`, listas, nomes de mês e de dia da semana, `7`
e `0` ambos como domingo, e a semântica OR entre dia-do-mês e dia-da-semana
quando ambos são restritos (regra do cron POSIX que quase toda implementação
caseira erra).

## Timezone

O cálculo do próximo disparo acontece NO fuso declarado (`zoneinfo`, IANA), e
só então converte para UTC. Guardar a string e calcular em UTC — o que a versão
anterior fazia — dá o horário errado em qualquer fuso ≠ UTC, e erra duas vezes
por ano em fusos com DST.

Os dois casos difíceis de DST são tratados explicitamente:
- **horário inexistente** (o relógio pula para frente): o disparo vai para o
  primeiro instante real após a lacuna;
- **horário ambíguo** (o relógio volta): usamos a PRIMEIRA ocorrência
  (`fold=0`), para o job rodar uma vez só, e não duas.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from nomos.adapters.contrato import ErroInvalido


class TipoAgenda(str, Enum):
    """Distinção EXPLÍCITA — nunca inferir cron de string arbitrária."""
    ONE_SHOT = "ONE_SHOT"
    INTERVAL = "INTERVAL"
    CRON = "CRON"


MESES = {n: i for i, n in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
DIAS = {n: i for i, n in enumerate(
    ["sun", "mon", "tue", "wed", "thu", "fri", "sat"], start=0)}

# (mínimo, máximo, apelidos) por campo, na ordem do cron
_CAMPOS = (
    (0, 59, {}),        # minuto
    (0, 23, {}),        # hora
    (1, 31, {}),        # dia do mês
    (1, 12, MESES),     # mês
    (0, 7, DIAS),       # dia da semana (7 == 0 == domingo)
)

_ATALHOS = {
    "@yearly": "0 0 1 1 *", "@annually": "0 0 1 1 *",
    "@monthly": "0 0 1 * *", "@weekly": "0 0 * * 0",
    "@daily": "0 0 * * *", "@midnight": "0 0 * * *",
    "@hourly": "0 * * * *",
}

_TERMO = re.compile(r"^(?P<ini>[^-/]+)(?:-(?P<fim>[^/]+))?(?:/(?P<passo>\d+))?$")

# Teto de busca: 5 anos em minutos. Uma expressão como "0 0 30 2 *"
# (30 de fevereiro) nunca dispara — precisa terminar, não girar para sempre.
_LIMITE_MINUTOS = 5 * 366 * 24 * 60


class ErroCron(ErroInvalido):
    """Expressão cron inválida. Fail-closed: nada é persistido nem armado."""


def _valor(bruto: str, minimo: int, maximo: int, apelidos: dict) -> int:
    t = bruto.strip().lower()
    if t in apelidos:
        return apelidos[t]
    if not t.isdigit() and not (t.startswith("-") and t[1:].isdigit()):
        raise ErroCron(f"valor inválido: {bruto!r}")
    n = int(t)
    if not (minimo <= n <= maximo):
        raise ErroCron(f"valor {n} fora da faixa {minimo}-{maximo}")
    return n


def _campo(bruto: str, indice: int) -> frozenset[int]:
    """Um campo cron → conjunto de valores. Fail-closed em qualquer anomalia."""
    minimo, maximo, apelidos = _CAMPOS[indice]
    bruto = bruto.strip()
    if not bruto:
        raise ErroCron("campo vazio")
    valores: set[int] = set()
    for termo in bruto.split(","):
        termo = termo.strip()
        if not termo:
            raise ErroCron("termo vazio na lista")
        if termo.startswith("*"):
            resto = termo[1:]
            passo = 1
            if resto.startswith("/"):
                if not resto[1:].isdigit():
                    raise ErroCron(f"passo inválido em {termo!r}")
                passo = int(resto[1:])
            elif resto:
                raise ErroCron(f"termo inválido: {termo!r}")
            if passo < 1:
                raise ErroCron("passo precisa ser >= 1")
            valores.update(range(minimo, maximo + 1, passo))
            continue
        m = _TERMO.match(termo)
        if not m:
            raise ErroCron(f"termo inválido: {termo!r}")
        ini = _valor(m.group("ini"), minimo, maximo, apelidos)
        fim = (_valor(m.group("fim"), minimo, maximo, apelidos)
               if m.group("fim") is not None else ini)
        passo = int(m.group("passo")) if m.group("passo") else 1
        if passo < 1:
            raise ErroCron("passo precisa ser >= 1")
        if m.group("fim") is None and m.group("passo"):
            fim = maximo                       # "5/10" = de 5 até o fim
        if ini > fim:
            # cron padrão NÃO faz wrap em faixa; recusa é mais honesto que
            # adivinhar a intenção
            raise ErroCron(f"faixa invertida: {termo!r}")
        valores.update(range(ini, fim + 1, passo))
    if indice == 4 and 7 in valores:           # domingo é 0 e 7
        valores.discard(7)
        valores.add(0)
    if not valores:
        raise ErroCron(f"campo sem valores: {bruto!r}")
    return frozenset(valores)


@dataclass(frozen=True)
class ExpressaoCron:
    """Expressão compilada. `dom_restrito`/`dow_restrito` guardam a semântica OR."""
    minutos: frozenset[int]
    horas: frozenset[int]
    dias_mes: frozenset[int]
    meses: frozenset[int]
    dias_semana: frozenset[int]
    origem: str
    dom_restrito: bool
    dow_restrito: bool

    def casa(self, dt: datetime) -> bool:
        if dt.minute not in self.minutos or dt.hour not in self.horas:
            return False
        if dt.month not in self.meses:
            return False
        dom_ok = dt.day in self.dias_mes
        # Python: segunda=0…domingo=6. Cron: domingo=0…sábado=6.
        dow_ok = ((dt.weekday() + 1) % 7) in self.dias_semana
        if self.dom_restrito and self.dow_restrito:
            # Regra do cron POSIX: quando AMBOS são restritos, vale OR — não AND.
            # É o detalhe que quase toda implementação caseira erra.
            return dom_ok or dow_ok
        return dom_ok and dow_ok


def compilar_cron(expressao: str) -> ExpressaoCron:
    """Compila `m h dom mon dow`. Inválida ⇒ `ErroCron` (nada é persistido)."""
    if not isinstance(expressao, str):
        raise ErroCron("expressão precisa ser texto")
    texto = expressao.strip().lower()
    if not texto:
        raise ErroCron("expressão vazia")
    texto = _ATALHOS.get(texto, texto)
    campos = texto.split()
    if len(campos) != 5:
        raise ErroCron(
            f"cron precisa de exatamente 5 campos (m h dom mon dow), "
            f"recebi {len(campos)}: {expressao!r}")
    conjuntos = [_campo(c, i) for i, c in enumerate(campos)]
    return ExpressaoCron(
        minutos=conjuntos[0], horas=conjuntos[1], dias_mes=conjuntos[2],
        meses=conjuntos[3], dias_semana=conjuntos[4], origem=expressao.strip(),
        dom_restrito=campos[2] != "*", dow_restrito=campos[4] != "*")


def resolver_tz(nome: str) -> ZoneInfo:
    """Timezone IANA. Desconhecida ⇒ DENY explícito, nunca fallback silencioso."""
    if not isinstance(nome, str) or not nome.strip():
        raise ErroInvalido("timezone vazia")
    try:
        return ZoneInfo(nome.strip())
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        raise ErroInvalido(
            f"timezone desconhecida: {nome!r} — use identificador IANA "
            f"(ex.: America/Sao_Paulo, UTC, Europe/Madrid)") from None
    except Exception as exc:
        raise ErroInvalido(f"timezone inválida {nome!r}: {type(exc).__name__}") from None


def _normalizar_local(ingenuo: datetime, tz: ZoneInfo) -> datetime | None:
    """datetime ingênuo no fuso `tz` → aware, tratando os buracos de DST.

    - **inexistente** (relógio pulou para frente): devolve None, e quem chama
      avança o minuto — o disparo cai no primeiro instante real após a lacuna;
    - **ambíguo** (relógio voltou): usa `fold=0`, a PRIMEIRA ocorrência, para o
      job rodar UMA vez e não duas.
    """
    aware = ingenuo.replace(tzinfo=tz, fold=0)
    # Ida e volta: se o horário local não existe, a conversão não bate.
    de_volta = aware.astimezone(timezone.utc).astimezone(tz)
    if (de_volta.hour, de_volta.minute, de_volta.day) != (
            ingenuo.hour, ingenuo.minute, ingenuo.day):
        return None
    return aware


def proximo_disparo_cron(expr: ExpressaoCron, depois_de: datetime,
                         tz: ZoneInfo) -> datetime:
    """Próximo instante > `depois_de` que casa com a expressão, em UTC.

    A busca acontece NO FUSO declarado — é o que torna a timezone aplicada de
    verdade, e não decoração persistida.
    """
    if depois_de.tzinfo is None:
        raise ErroInvalido("`depois_de` precisa ser aware")
    local = depois_de.astimezone(tz).replace(second=0, microsecond=0)
    local += timedelta(minutes=1)                # estritamente depois
    ingenuo = local.replace(tzinfo=None)
    for _ in range(_LIMITE_MINUTOS):
        if expr.casa(ingenuo):
            aware = _normalizar_local(ingenuo, tz)
            if aware is not None:
                return aware.astimezone(timezone.utc)
        ingenuo += timedelta(minutes=1)
    raise ErroCron(
        f"expressão {expr.origem!r} não dispara nos próximos 5 anos "
        "(ex.: 30 de fevereiro) — recusada em vez de girar para sempre")


@dataclass(frozen=True)
class ScheduleSpec:
    """A intenção de agendamento, persistível e explícita.

    `kind` distingue ONE_SHOT / INTERVAL / CRON sem inferência: uma string de
    cron só é tratada como cron quando o chamador diz que é.
    """
    kind: TipoAgenda
    expression: str = ""            # cron quando CRON; vazio nos demais
    timezone: str = "UTC"
    intervalo_s: int | None = None  # só INTERVAL

    def __post_init__(self):
        # A timezone é validada em TODOS os tipos, não só em CRON. Antes só o
        # ramo CRON chamava `resolver_tz`, então um ONE_SHOT ou INTERVAL com
        # `tz="Mars/Olympus"` era aceito, persistido e exibido pelo `listar`
        # como se fosse uma zona real. INTERVAL não usa a tz para calcular o
        # próximo disparo — e é justamente por isso que o erro sobrevivia
        # calado até alguém converter o job para CRON ou ler o registro
        # acreditando nele. Identificador que não existe não é metadado: é
        # mentira persistida.
        resolver_tz(self.timezone)
        if self.kind is TipoAgenda.CRON:
            if not self.expression:
                raise ErroCron("agenda CRON exige `expression`")
            compilar_cron(self.expression)         # valida na construção
        elif self.kind is TipoAgenda.INTERVAL:
            if not isinstance(self.intervalo_s, int) or self.intervalo_s <= 0:
                raise ErroInvalido("agenda INTERVAL exige intervalo_s > 0")
        elif self.kind is not TipoAgenda.ONE_SHOT:
            raise ErroInvalido(f"tipo de agenda desconhecido: {self.kind!r}")

    def recorrente(self) -> bool:
        return self.kind in (TipoAgenda.INTERVAL, TipoAgenda.CRON)

    def proximo(self, depois_de: datetime) -> datetime | None:
        """Próximo disparo em UTC; None para ONE_SHOT (não se repete)."""
        if self.kind is TipoAgenda.ONE_SHOT:
            return None
        if self.kind is TipoAgenda.INTERVAL:
            return depois_de + timedelta(seconds=self.intervalo_s)
        return proximo_disparo_cron(compilar_cron(self.expression),
                                    depois_de, resolver_tz(self.timezone))

    def dict(self) -> dict:
        return {"kind": self.kind.value, "expression": self.expression,
                "timezone": self.timezone, "intervalo_s": self.intervalo_s}

    @staticmethod
    def de_dict(d: dict) -> "ScheduleSpec":
        try:
            kind = TipoAgenda(d.get("kind", ""))
        except ValueError:
            raise ErroInvalido(f"kind inválido: {d.get('kind')!r}") from None
        return ScheduleSpec(kind=kind, expression=d.get("expression", "") or "",
                            timezone=d.get("timezone", "UTC") or "UTC",
                            intervalo_s=d.get("intervalo_s"))
