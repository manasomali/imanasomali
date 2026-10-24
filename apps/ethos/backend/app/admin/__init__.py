"""Painel de admin (ETH-28): contas e banners.

- `accounts.py`: listar e buscar contas, ver o conteúdo dos hábitos de uma conta, bloquear,
  desbloquear e trocar o email (a exclusão é a de `app/auth/deletion.py`).
- `banners.py`: criar, editar e encerrar banners, e o banner ativo (público).
- `schemas.py`: corpos e respostas da API.
- `routes.py`: os endpoints `/admin/...` (todos com `AdminUser`) e o público `/banners/active`.
"""
