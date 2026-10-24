"""Corpos e respostas da API do admin (ETH-28).

Aqui só a validação de cada campo isolado; o que depende de mais de um campo ou do banco (janela
do banner, email que já tem conta) fica em `accounts.py` e `banners.py`.

- Texto do banner (`text_pt`, `text_en`): espaços nas pontas saem; de 1 a 280 caracteres; uma
  linha só (caracteres de controle, inclusive quebra de linha, e os que invertem a direção do
  texto são recusados, como no nome do hábito). HTML não é interpretado: `<b>` fica como está.
- Datas: ISO 8601 com fuso, convertidas para UTC (as mesmas regras das marcações, `Instant`).
- Campo desconhecido é recusado (422); no PATCH do banner, campo ausente não muda e `null` é
  recusado.
"""

from datetime import datetime
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, field_validator

from app.auth.routes import Email
from app.habits.schemas import HabitOut, check_controls
from app.mail.language import Locale
from app.marks.schemas import Instant, MarkOut
from app.models import BANNER_TEXT_MAX_LENGTH


def _banner_text(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("não pode ser vazio")
    if len(value) > BANNER_TEXT_MAX_LENGTH:
        raise ValueError(f"no máximo {BANNER_TEXT_MAX_LENGTH} caracteres")
    check_controls(value, multiline=False)
    return value


BannerText = Annotated[str, AfterValidator(_banner_text)]


# --- contas ---


class AccountOut(BaseModel):
    id: int
    email: str
    # false: bloqueada pelo admin
    is_active: bool
    is_admin: bool
    timezone: str
    locale: Locale
    created_at: datetime
    # null: nunca entrou pelo código
    last_login_at: datetime | None
    # Hábitos de que é dona (qualquer status) e marcações que fez (em qualquer hábito)
    habit_count: int
    mark_count: int


class AccountList(BaseModel):
    users: list[AccountOut]
    # Passe em `?cursor=` (com os mesmos filtros) para a próxima página; null na última
    next_cursor: str | None


class AccountHabits(BaseModel):
    user: AccountOut
    # Os hábitos de que a conta é dona (`role` = owner, sem `score`)
    habits: list[HabitOut]
    # Uma página das marcações desses hábitos, das mais recentes para as mais antigas
    marks: list[MarkOut]
    next_cursor: str | None


class EmailChangeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Normalizado (strip + lower) e validado como no login
    new_email: Email


# --- banners ---


class BannerCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text_pt: BannerText
    text_en: BannerText
    starts_at: Instant
    ends_at: Instant


class BannerUpdate(BaseModel):
    """Mudança parcial: campo ausente não muda; `null` é recusado."""

    model_config = ConfigDict(extra="forbid")

    text_pt: BannerText | None = None
    text_en: BannerText | None = None
    starts_at: Instant | None = None
    ends_at: Instant | None = None

    @field_validator("text_pt", "text_en", "starts_at", "ends_at")
    @classmethod
    def _not_null(cls, value: Any) -> Any:
        # Só roda quando o campo veio no corpo: o padrão (ausente) não é validado
        if value is None:
            raise ValueError("não pode ser null")
        return value


class BannerOut(BaseModel):
    id: int
    text_pt: str
    text_en: str
    starts_at: datetime
    ends_at: datetime
    # Admin que criou; null se a conta dele foi apagada
    created_by: int | None
    created_at: datetime
    updated_at: datetime


class BannerList(BaseModel):
    banners: list[BannerOut]
    next_cursor: str | None


class PublicBanner(BaseModel):
    """O banner como sai no endpoint público: sem quem criou."""

    id: int
    text_pt: str
    text_en: str
    starts_at: datetime
    ends_at: datetime


class ActiveBanner(BaseModel):
    # null: nenhum banner no ar
    banner: PublicBanner | None
