"""Corpos e respostas da API de marcações.

Aqui só a validação de cada campo isolado. O que depende do hábito (recurso ligado, nível do
custo, `MAX_NOTE_LENGTH` da config, data no futuro) fica em `app/marks/service.py`.

- Datas: ISO 8601 com fuso (`2026-03-25T15:00:00Z` ou `-03:00`); sem fuso, 422. Saem em UTC. Antes
  de `MIN_INSTANT` (1900) ou fora do que o Python representa em UTC, 422.
- Observação: espaços nas pontas saem, vazia vira `null`; aceita quebra de linha e tab, recusa
  outros caracteres de controle e os que invertem a direção do texto (como a descrição do hábito).
- Duração e custo: inteiros estritos, com os tetos do hábito (`DurationMinutes`, `Money`).
- Campo desconhecido é recusado (422). No PATCH, `marked_at` é um campo desconhecido: a data de
  uma marcação não muda; para mudar, apaga e cria outra.
"""

from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    field_validator,
)

from app.habits.schemas import DurationMinutes, Money, check_controls

# Data mais antiga aceita numa marcação ou num intervalo: longe o bastante para qualquer
# histórico, e longe dos limites do datetime (converter o ano 1 de fuso estoura)
MIN_INSTANT = datetime(1900, 1, 1, tzinfo=UTC)


def _text_only(value: Any) -> Any:
    # Sem isso, o pydantic aceitaria número (segundos desde 1970) como data
    if isinstance(value, int | float):
        raise ValueError("data em texto ISO 8601")
    return value


def _to_utc(value: datetime) -> datetime:
    try:
        value = value.astimezone(UTC)
    except OverflowError:
        raise ValueError("data fora do intervalo") from None
    if value < MIN_INSTANT:
        raise ValueError("data fora do intervalo")
    return value


def _note(value: str) -> str | None:
    value = value.strip()
    if not value:
        return None
    check_controls(value, multiline=True)
    return value


# Instante com fuso, convertido para UTC
Instant = Annotated[AwareDatetime, BeforeValidator(_text_only), AfterValidator(_to_utc)]
# Texto da observação; o tamanho máximo (MAX_NOTE_LENGTH) é conferido no service
Note = Annotated[str, AfterValidator(_note)]


class ToggleIn(BaseModel):
    """Clique no dia de um hábito toggle.

    `day_start` e `day_end`: início e fim do dia clicado no fuso de quem clicou, em UTC (o fim é
    o início do dia seguinte; de 23 h a 25 h). `marked_at`: o instante gravado se o clique criar
    a marcação, dentro do dia: agora, se o dia é hoje; 12:00 local, se é um dia passado.
    """

    model_config = ConfigDict(extra="forbid")

    day_start: Instant
    day_end: Instant
    marked_at: Instant


class MarkCreate(BaseModel):
    """Marcação num hábito com várias por dia. Ausente: o padrão do hábito (ver service)."""

    model_config = ConfigDict(extra="forbid")

    marked_at: Instant
    note: Note | None = None
    duration_minutes: DurationMinutes | None = None
    cost_cents: Money | None = None


class MarkUpdate(BaseModel):
    """Mudança parcial: campo ausente não muda. `null` apaga a observação ou o custo."""

    model_config = ConfigDict(extra="forbid")

    note: Note | None = None
    duration_minutes: DurationMinutes | None = None
    cost_cents: Money | None = None

    @field_validator("duration_minutes")
    @classmethod
    def _duration_not_null(cls, value: Any) -> Any:
        # Só roda quando o campo veio no corpo: com a duração ligada, minutos > 0
        if value is None:
            raise ValueError("não pode ser null")
        return value


class Author(BaseModel):
    """Quem criou a marcação. Na resposta, `author: null` é "usuário removido"."""

    id: int
    email: str


class MarkOut(BaseModel):
    id: int
    habit_id: int
    # null: a conta do autor foi apagada ("usuário removido")
    author: Author | None
    marked_at: datetime
    duration_minutes: int | None
    cost_cents: int | None
    note: str | None
    created_at: datetime
    updated_at: datetime


class ToggleOut(BaseModel):
    # true: o clique criou a marcação (`mark`); false: apagou as do dia (`mark` null)
    marked: bool
    mark: MarkOut | None


class MarkList(BaseModel):
    marks: list[MarkOut]
    # Passe em `?cursor=` para a próxima página; null na última
    next_cursor: str | None
