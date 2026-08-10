"""NOMOS adapters.retry — o que acontece com efeito que pode ter acontecido.

`FAILED` significa efeito DESCONHECIDO: o executor pode ter mudado o mundo
antes de cair. Repetir às cegas é duplicar; não repetir nunca é perder. A
resposta certa depende da capacidade, e precisa ser DECLARADA — "provavelmente
não acontece" não é estratégia, é uma aposta que alguém vai perder às três da
manhã.

Quatro categorias, exaustivas por construção (o teste prende a tabela ao
registro de capacidades, então capacidade nova sem categoria falha a suíte):

    IDEMPOTENT                        repetir é seguro; o resultado é o mesmo
    IDEMPOTENCY_KEY_PROTECTED         repetir é seguro porque uma chave impede
                                      o segundo efeito
    EXACTLY_ONCE_VIA_DURABLE_PROTOCOL a reivindicação durável precede o efeito;
                                      o restart encontra a marca e não repete
    NON_RETRYABLE_MANUAL_RECOVERY     ninguém repete sozinho; o operador decide

Só a primeira autoriza repetição automática. As outras três podem ser
recuperadas, mas não por um laço que tenta de novo sem saber o que aconteceu.

## Por que `EXACTLY_ONCE_VIA_DURABLE_PROTOCOL` não é a mesma coisa que retry

O scheduler grava a reivindicação (`ArmazemJobs.reservar`) ANTES do efeito, com
`INSERT` que falha se a chave já existe. Um processo que morre entre a reserva
e a conclusão deixa a marca no disco; o restart a encontra e recusa. Isso não
impede a PERDA (a ocorrência não roda), e é deliberado: perder uma execução é
um job atrasado, repetir uma é um efeito duplicado no mundo — e o mundo não
tem desfazer.

## Por que apagar é `NON_RETRYABLE_MANUAL_RECOVERY`

`fs-apagar` que falhou pode ter apagado. Repetir encontra "não existe" e pode
ser lido como sucesso — ou pode apagar algo que foi recriado no intervalo.
Nenhuma das duas leituras é confiável o bastante para automatizar.
"""
from __future__ import annotations

IDEMPOTENT = "IDEMPOTENT"
IDEMPOTENCY_KEY_PROTECTED = "IDEMPOTENCY_KEY_PROTECTED"
EXACTLY_ONCE_VIA_DURABLE_PROTOCOL = "EXACTLY_ONCE_VIA_DURABLE_PROTOCOL"
NON_RETRYABLE_MANUAL_RECOVERY = "NON_RETRYABLE_MANUAL_RECOVERY"


CATEGORIA_DE_RETRY: dict[str, str] = {
    # leitura: repetir devolve o mesmo, sem tocar em nada
    "fs-ler": IDEMPOTENT,
    "fs-listar": IDEMPOTENT,
    "fs-metadados": IDEMPOTENT,
    # escrita atômica: o conteúdo final é o mesmo, mas o arquivo é
    # RECRIADO — repetir sobrescreve uma edição concorrente que tenha
    # entrado no intervalo. Não é idempotente no sentido que importa.
    "fs-escrever": NON_RETRYABLE_MANUAL_RECOVERY,
    # edição por substituição única: se a primeira tentativa aplicou, o
    # trecho `de` não existe mais e a repetição falha por "não encontrado" —
    # falha que o operador leria como erro sem sê-lo.
    "fs-editar": NON_RETRYABLE_MANUAL_RECOVERY,
    # `mkdir(exist_ok=True)`: repetir é literalmente o mesmo estado
    "fs-criar-dir": IDEMPOTENT,
    # mover: a origem já não está lá na segunda tentativa
    "fs-mover": NON_RETRYABLE_MANUAL_RECOVERY,
    "fs-apagar": NON_RETRYABLE_MANUAL_RECOVERY,
    "fs-apagar-arvore": NON_RETRYABLE_MANUAL_RECOVERY,
    # git de LEITURA: repetir devolve o mesmo, sem tocar em nada
    "git-diff": IDEMPOTENT,
    "git-log": IDEMPOTENT,
    "git-show": IDEMPOTENT,
    # criar tag que já existe FALHA — repetir não é seguro nem inócuo
    "git-tag": NON_RETRYABLE_MANUAL_RECOVERY,
    # push que falhou pode ter publicado: o remoto pode ter aceitado e a
    # resposta ter se perdido. Repetir às cegas republica.
    "git-push": NON_RETRYABLE_MANUAL_RECOVERY,
    # scheduler: leitura é idempotente; mutação de estado é protegida pela
    # chave de ocorrência (dedup) ou pela unicidade do job_id
    "sched-listar": IDEMPOTENT,
    "sched-status": IDEMPOTENT,
    "sched-criar": IDEMPOTENCY_KEY_PROTECTED,      # job_id é PRIMARY KEY
    "sched-habilitar": EXACTLY_ONCE_VIA_DURABLE_PROTOCOL,
    "sched-desabilitar": EXACTLY_ONCE_VIA_DURABLE_PROTOCOL,
    "sched-cancelar": EXACTLY_ONCE_VIA_DURABLE_PROTOCOL,
    "sched-apagar": NON_RETRYABLE_MANUAL_RECOVERY,
}


def pode_repetir_sozinho(capacidade: str) -> bool:
    """Só `IDEMPOTENT` autoriza repetição AUTOMÁTICA.

    As demais categorias descrevem como recuperar — não autorizam um laço a
    tentar de novo sem saber o que aconteceu. Capacidade desconhecida devolve
    `False`: o default é não repetir.
    """
    return CATEGORIA_DE_RETRY.get(capacidade) == IDEMPOTENT
