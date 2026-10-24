"""Banners (ETH-28): avisos globais com texto em pt e en e uma janela de datas.

- Janela: `[starts_at, ends_at)`, em UTC, com `ends_at` depois de `starts_at` (senão 422
  `ends_at`). O banner aparece de `starts_at` (inclusive) até `ends_at` (exclusive).
- Um ativo por vez (`active_banner`): se mais de um está dentro da janela, vale o que começou
  por último (`starts_at` mais recente; empate, o de id maior, criado depois). É o aviso mais novo
  na tela: um banner agendado para começar amanhã passa na frente, amanhã, de um que já estava no
  ar.
- Texto puro: guardado como veio (só sem os espaços das pontas), sem interpretar HTML; quem
  mostra trata como texto. A validação de cada campo fica em `schemas.py`.
- Encerrar (`end_banner`): a janela fecha agora (`ends_at` = agora). Um banner agendado que ainda
  não começou não chega a aparecer: `starts_at` vira 1 µs antes do fim, porque o banco exige
  `ends_at` > `starts_at`; os horários de antes ficam na auditoria. Banner já encerrado: nada
  muda. Editar continua possível depois (inclusive para reabrir a janela).

Escritas só por admin (a rota usa `AdminUser`, e `ensure_admin` confere de novo dentro da
transação). Auditoria, com `user_id` = o admin: `banner_created` com `{banner_id, text_pt,
text_en, starts_at, ends_at}`; `banner_updated` e `banner_ended` com `{banner_id, changes:
[{field, old, new}]}` (datas em ISO 8601). Editar sem mudar nada não grava.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app import audit
from app.admin.accounts import ensure_admin
from app.audit import AuditEvent
from app.db import write_transaction
from app.errors import ApiError, ErrorCode
from app.models import Banner, utcnow
from app.pagination import decode_cursor, encode_cursor

# Campos que o admin define, na ordem da auditoria
BANNER_FIELDS = ("text_pt", "text_en", "starts_at", "ends_at")
_MICROSECOND = timedelta(microseconds=1)


@dataclass(frozen=True, slots=True)
class BannerPage:
    entries: list[Banner]
    # Cursor da próxima página; None na última
    next_cursor: str | None


def _audit_value(value: Any) -> Any:
    return value.isoformat() if isinstance(value, datetime) else value


def _check_window(starts_at: datetime, ends_at: datetime) -> None:
    if ends_at <= starts_at:
        raise ApiError(422, ErrorCode.VALIDATION_ERROR, field="ends_at")


def _banner(session: Session, banner_id: int) -> Banner:
    """O banner relido dentro da transação; 404 se não existe."""
    banner = session.scalar(
        select(Banner).where(Banner.id == banner_id).execution_options(populate_existing=True)
    )
    if banner is None:
        raise ApiError(404, ErrorCode.NOT_FOUND)
    return banner


def list_banners(session: Session, *, cursor: str | None, limit: int) -> BannerPage:
    """Todos os banners (passados, no ar e agendados), dos criados por último aos primeiros.

    `limit`: 1 a `MAX_PAGE_SIZE` (a rota confere). Cursor inválido: 422 `cursor`.
    """
    query = select(Banner)
    if cursor is not None:
        after_at, after_id = decode_cursor(cursor)
        query = query.where(
            or_(
                Banner.created_at < after_at,
                and_(Banner.created_at == after_at, Banner.id < after_id),
            )
        )
    banners = list(
        session.scalars(query.order_by(Banner.created_at.desc(), Banner.id.desc()).limit(limit + 1))
    )
    entries = banners[:limit]
    next_cursor = None
    if len(banners) > limit:
        next_cursor = encode_cursor(entries[-1].created_at, entries[-1].id)
    return BannerPage(entries, next_cursor)


def create_banner(
    session: Session,
    *,
    admin_id: int,
    ip: str | None,
    text_pt: str,
    text_en: str,
    starts_at: datetime,
    ends_at: datetime,
) -> Banner:
    """Cria o banner (textos já validados). `ends_at` não depois de `starts_at`: 422 `ends_at`."""
    _check_window(starts_at, ends_at)
    with write_transaction(session):
        ensure_admin(session, admin_id)
        banner = Banner(
            text_pt=text_pt,
            text_en=text_en,
            starts_at=starts_at,
            ends_at=ends_at,
            created_by=admin_id,
        )
        session.add(banner)
        session.flush()
        audit.record(
            session,
            AuditEvent.BANNER_CREATED,
            user_id=admin_id,
            ip=ip,
            details={
                "banner_id": banner.id,
                **{name: _audit_value(getattr(banner, name)) for name in BANNER_FIELDS},
            },
        )
    return banner


def _apply(banner: Banner, values: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Aplica os valores que mudaram e devolve as mudanças, no formato da auditoria."""
    changes = []
    for name in BANNER_FIELDS:
        if name not in values:
            continue
        old, new = getattr(banner, name), values[name]
        if new != old:
            changes.append({"field": name, "old": _audit_value(old), "new": _audit_value(new)})
            setattr(banner, name, new)
    return changes


def update_banner(
    session: Session,
    *,
    admin_id: int,
    banner_id: int,
    values: Mapping[str, Any],
    ip: str | None,
) -> Banner:
    """Muda os campos de `values` (os de `BANNER_FIELDS`, já validados; ausente não muda).

    404 se não existe; a janela resultante com o fim não depois do início: 422 `ends_at`.
    """
    with write_transaction(session):
        ensure_admin(session, admin_id)
        banner = _banner(session, banner_id)
        _check_window(
            values.get("starts_at", banner.starts_at), values.get("ends_at", banner.ends_at)
        )
        changes = _apply(banner, values)
        if changes:
            audit.record(
                session,
                AuditEvent.BANNER_UPDATED,
                user_id=admin_id,
                ip=ip,
                details={"banner_id": banner_id, "changes": changes},
            )
    return banner


def end_banner(session: Session, *, admin_id: int, banner_id: int, ip: str | None) -> Banner:
    """Fecha a janela agora (ver o docstring do módulo). 404 se não existe."""
    with write_transaction(session):
        ensure_admin(session, admin_id)
        banner = _banner(session, banner_id)
        now = utcnow()
        if banner.ends_at > now:
            values = {"ends_at": now}
            if banner.starts_at >= now:
                values["starts_at"] = now - _MICROSECOND
            audit.record(
                session,
                AuditEvent.BANNER_ENDED,
                user_id=admin_id,
                ip=ip,
                details={"banner_id": banner_id, "changes": _apply(banner, values)},
            )
    return banner


def active_banner(session: Session, now: datetime | None = None) -> Banner | None:
    """O banner no ar agora (ou em `now`), o que começou por último; None se não há."""
    now = utcnow() if now is None else now
    return session.scalar(
        select(Banner)
        .where(Banner.starts_at <= now, Banner.ends_at > now)
        .order_by(Banner.starts_at.desc(), Banner.id.desc())
        .limit(1)
    )
