"""O que o imago pede ao ethos pela API interna: atualizar `app_users` e apagar uma pessoa.

`refresh_app_user` (`POST /internal/users/{id}/refresh`): o imago manda o email, o idioma e o
fuso atuais da conta depois de uma troca (`PATCH /me` ou troca de email pelo admin). A linha só
muda se algum dos três mudou; id que o ethos não conhece não cria linha (ela nasce no primeiro
request da pessoa). O imago sempre manda os valores da hora da chamada, então uma tarefa atrasada
não desfaz uma mudança mais nova.

`delete_user_data` (`POST /internal/users/{id}/delete`): a exclusão da conta é pedida e coordenada
pelo imago (`imago-plan.md`, "exclusão de conta"); aqui sai a parte do ethos (`ethos-plan.md`,
"exclusão de conta e dados"), numa transação só (BEGIN IMMEDIATE): ou apaga tudo ou nada.

O que é apagado:

- os hábitos dos quais a pessoa é dona, antes da linha dela: o CASCADE leva as marcações (também
  as dos convidados), pausas, membros, convites enviados, alertas e a auditoria desses hábitos;
- os convites pendentes recebidos: os ligados ao id dela (`invited_user_id`, sem chave
  estrangeira: ela pode nunca ter aberto o ethos) e, se o ethos conhece o email dela, os feitos
  para esse email antes de a conta existir (`invited_user_id` vazio). Convite de outra conta para
  o mesmo email (a cópia em `app_users` pode estar velha) fica;
- os `habit_deleted` gravados por ela (os hábitos dela apagados antes; o id dela está no
  `user_id`);
- a linha em `app_users` e, pelo CASCADE, as participações em hábitos de outras pessoas
  (`habit_members`) e os alertas.

O que fica, sem identificar a pessoa:

- as marcações dela em hábitos de outras pessoas: `marks.user_id` vira NULL pelo `SET NULL`
  ("usuário removido");
- as linhas do `audit_log` com o `user_id` dela (eventos em hábitos de outras pessoas e as ações
  dela como admin): `user_id` vira NULL;
- nos eventos de hábitos de outras pessoas, os ids dela em `details` (`ACCOUNT_ID_KEYS`:
  `author_id` das marcações, `member_id` de remoção e troca de papel) viram `null`, porque o
  histórico os mostra aos membros;
- toda linha que sobra e cita a pessoa (pelo `user_id`, pelo email no `details` ou pelo
  `details.target_user_id` dos eventos de admin sobre ela) perde todo texto do `details` com "@";
- `banners.created_by` vira NULL pelo `SET NULL`.

Os avisos "você perdeu acesso" (um por membro dos hábitos dela, com todos os hábitos) são lidos
antes de apagar e devolvidos para quem chama mandar pelo imago depois do commit: uma exclusão que
falhou não avisa ninguém. Idempotente: chamar de novo, ou para um id que o ethos não conhece,
apaga o que sobrar (convites recebidos, no caso do id desconhecido) e não falha. O log recebe só
o id numérico.
"""

import json
import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, func, null, or_, select, update
from sqlalchemy.orm import Session

from app.audit import AuditEvent
from app.db import write_transaction
from app.mail.catalog import AccessLost
from app.mail.language import Locale, pick_locale
from app.models import AppUser, AuditLog, Habit, HabitInvite, HabitMember

logger = logging.getLogger(__name__)

# Chaves do `details` com o id de uma conta nos eventos de hábito: viram null na exclusão
ACCOUNT_ID_KEYS = ("author_id", "member_id")
# Chave do `details` com a conta alvo de um evento de admin: o id fica, os emails saem
TARGET_USER_KEY = "target_user_id"


@dataclass(frozen=True, slots=True)
class Notice:
    """Aviso a mandar pelo imago depois do commit."""

    user_id: int
    locale: Locale
    email: AccessLost


@dataclass(frozen=True, slots=True)
class UserDeletion:
    """Resultado de `delete_user_data`: se havia linha em `app_users` e os avisos a mandar."""

    user_id: int
    existed: bool
    notices: tuple[Notice, ...]


def refresh_app_user(
    session: Session, *, user_id: int, email: str, locale: Locale, timezone: str
) -> bool:
    """Atualiza a cópia da conta em `app_users`. Devolve se alguma coisa mudou.

    Os valores chegam validados (como os headers `X-User-*`). Id desconhecido: nada muda.
    """
    with write_transaction(session):
        user = session.get(AppUser, user_id, populate_existing=True)
        if user is None:
            return False
        wanted = (email, locale.value, timezone)
        if (user.email, user.locale, user.timezone) == wanted:
            return False
        user.email, user.locale, user.timezone = wanted
    return True


def delete_user_data(session: Session, *, user_id: int) -> UserDeletion:
    """Apaga e anonimiza os dados do usuário `user_id` no ethos (ver o docstring do módulo)."""
    with write_transaction(session):
        user = session.get(AppUser, user_id, populate_existing=True)
        email = None if user is None else user.email
        # Lidos antes de apagar; saem depois do commit
        notices = _access_lost(session, user_id)
        _execute(session, delete(Habit).where(Habit.owner_id == user_id))
        received = [HabitInvite.invited_user_id == user_id]
        if email is not None:
            received.append((HabitInvite.email == email) & HabitInvite.invited_user_id.is_(None))
        _execute(session, delete(HabitInvite).where(or_(*received)))
        _clean_audit(session, user_id, email)
        if user is not None:
            _execute(session, delete(AppUser).where(AppUser.id == user_id))
            session.expunge(user)
    if user is not None:
        # Só o id numérico
        logger.info("dados da conta %d apagados", user_id)
    return UserDeletion(user_id=user_id, existed=user is not None, notices=notices)


def _execute(session: Session, statement: Any) -> None:
    session.execute(statement, execution_options={"synchronize_session": False})


def _access_lost(session: Session, owner_id: int) -> tuple[Notice, ...]:
    """Um aviso por membro dos hábitos do dono, com os nomes de todos os hábitos que ele perde."""
    rows = session.execute(
        select(AppUser.id, AppUser.locale, Habit.name)
        .join(HabitMember, HabitMember.user_id == AppUser.id)
        .join(Habit, Habit.id == HabitMember.habit_id)
        .where(Habit.owner_id == owner_id)
        .order_by(AppUser.id, Habit.id)
    ).all()
    members: dict[int, tuple[str, list[str]]] = {}
    for member_id, locale, habit_name in rows:
        members.setdefault(member_id, (locale, []))[1].append(habit_name)
    return tuple(
        Notice(member_id, pick_locale(locale), AccessLost(habit_names=tuple(names)))
        for member_id, (locale, names) in members.items()
    )


def _clean_audit(session: Session, user_id: int, email: str | None) -> None:
    """Apaga a auditoria que é só da pessoa e anonimiza a que fica.

    Roda antes de apagar a linha em `app_users`, cujo `SET NULL` levaria o `user_id` que diz
    quais linhas eram dela.
    """
    _execute(
        session,
        delete(AuditLog).where(
            AuditLog.user_id == user_id, AuditLog.event == AuditEvent.HABIT_DELETED.value
        ),
    )
    _scrub_emails(session, user_id, email)
    for key in ACCOUNT_ID_KEYS:
        path = f"$.{key}"
        _execute(
            session,
            update(AuditLog)
            .where(func.json_extract(AuditLog.details, path) == user_id)
            .values(details=func.json_set(AuditLog.details, path, null())),
        )
    # Explícito, além do SET NULL: vale também para quem não tem linha em app_users
    _execute(session, update(AuditLog).where(AuditLog.user_id == user_id).values(user_id=None))


def _scrub_emails(session: Session, user_id: int, email: str | None) -> None:
    """Tira os emails do `details` das linhas que citam a pessoa e têm algum "@"."""
    cites = [
        AuditLog.user_id == user_id,
        func.json_extract(AuditLog.details, f"$.{TARGET_USER_KEY}") == user_id,
    ]
    if email is not None:
        # O email como fica no JSON gravado (ensure_ascii; o do imago já é ASCII)
        needle = json.dumps(email)[1:-1]
        cites.append(func.instr(func.lower(AuditLog.details), needle) > 0)
    rows = session.execute(
        select(AuditLog.id, AuditLog.details).where(
            func.instr(AuditLog.details, "@") > 0, or_(*cites)
        )
    ).all()
    if rows:
        # UPDATE por chave primária, em lote
        session.execute(
            update(AuditLog),
            [{"id": row_id, "details": without_emails(details)} for row_id, details in rows],
        )


def without_emails(value: Any) -> Any:
    """Cópia de um valor JSON com todo texto que contém "@" trocado por None."""
    if isinstance(value, dict):
        return {key: without_emails(item) for key, item in value.items()}
    if isinstance(value, list):
        return [without_emails(item) for item in value]
    if isinstance(value, str) and "@" in value:
        return None
    return value
