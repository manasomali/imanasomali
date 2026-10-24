"""Corpo e resposta da configuração de alerta (`GET/PUT /habits/{id}/alerts`).

- `goal_enabled` e `cost_enabled`: as duas chaves, independentes. Booleanos estritos.
- `hour`: hora cheia de 0 a 23, no fuso do usuário (`users.timezone`). Inteiro estrito: `"9"`,
  `9.0` e `9.5` são recusados.
- `frequency`: `daily` ou `weekly`.
- `weekday`: 0 = segunda ... 6 = domingo (semana ISO, como `date.weekday()`). Obrigatório no
  semanal e proibido no diário (422 com `field: "weekday"` nos dois casos).
- O PUT troca a configuração inteira: os quatro primeiros campos são obrigatórios; campo
  desconhecido é recusado (422).
"""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, Strict, ValidationInfo, field_validator

from app.models import AlertFrequency

Flag = Annotated[bool, Strict()]
Hour = Annotated[int, Strict(), Field(ge=0, le=23)]
Weekday = Annotated[int, Strict(), Field(ge=0, le=6)]


class AlertConfig(BaseModel):
    """Corpo do PUT. A ordem dos campos importa: `weekday` é conferido depois de `frequency`."""

    model_config = ConfigDict(extra="forbid")

    goal_enabled: Flag
    cost_enabled: Flag
    hour: Hour
    frequency: AlertFrequency
    # validate_default: o validador roda também quando o campo não vem (semanal sem dia)
    weekday: Weekday | None = Field(default=None, validate_default=True)

    @field_validator("weekday")
    @classmethod
    def _weekday_matches_frequency(cls, value: int | None, info: ValidationInfo) -> int | None:
        # Sem `frequency` em info.data, a frequência já foi recusada: um erro só basta
        frequency = info.data.get("frequency")
        if frequency is AlertFrequency.WEEKLY and value is None:
            raise ValueError("o alerta semanal precisa do dia da semana")
        if frequency is AlertFrequency.DAILY and value is not None:
            raise ValueError("o alerta diário não tem dia da semana")
        return value


class AlertOut(BaseModel):
    """A configuração do usuário no hábito; sem configuração salva, os valores padrão (tudo
    desligado). `last_sent_at`: o último email de alerta desse hábito para o usuário.

    Mesmos campos do PUT (o front pode mandar de volta o que leu, mudando só o que quiser), mais
    o `last_sent_at`. No diário, `weekday` sai sempre `null`.
    """

    goal_enabled: bool
    cost_enabled: bool
    hour: int
    frequency: AlertFrequency
    weekday: int | None
    last_sent_at: datetime | None
