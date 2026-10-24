"""Compartilhamento de hábitos (ETH-24): convites, membros e papéis.

- `quota.py`: a contagem do `MAX_INVITES_PER_DAY` pelo `audit_log`.
- `service.py`: as regras de convidar, cancelar, aceitar, recusar, sair, trocar papel e remover.
- `schemas.py`: corpos e respostas da API.
- `routes.py`: os endpoints `/habits/{id}/invites`, `/habits/{id}/members`, `/habits/{id}/leave`
  e `/invites`.
"""
