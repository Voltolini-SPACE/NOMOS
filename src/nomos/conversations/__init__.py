"""NOMOS conversations — histórico de conversas local, governado (F2).

Preenche a lacuna confirmada na validação: até a v1.2 o `memory.db` guardava
turnos soltos, sem agrupar em conversas, título, tags ou reabertura. Aqui as
conversas viram cidadãs de primeira classe — SEMPRE locais.

Governança (inegociável):
- conversa PRIVADA não toca o disco (nem metadados);
- retenção apaga sozinha após N dias, com aviso; nunca envia nada para fora;
- export/import cifrado (mesma stack do backup: Fernet + PBKDF2 600k);
- logs guardam só metadados (id, contagem), jamais o texto;
- "não usar como memória" impede a conversa de entrar no contexto de outra.
"""
from nomos.conversations.store import ConversationStore
from nomos.conversations.models import Conversation, Turn

__all__ = ["ConversationStore", "Conversation", "Turn"]
