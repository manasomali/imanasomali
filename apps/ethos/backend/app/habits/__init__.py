"""Hábitos: configuração (CRUD), acesso por papel e a ponte com a pontuação (`app/score.py`).

- `access.py`: o hábito com o papel do usuário, ou 404 (`get_habit_access`, `require_owner`).
- `scoring.py`: modelos do banco -> dataclasses do `score.py`, sem N+1 (`evaluate_habits`).
- `schemas.py`: corpos e respostas da API, com os tamanhos e formatos do plano.
- `service.py`: as regras de criar, editar, apagar e listar.
- `routes.py`: os endpoints de `/habits`.
"""
