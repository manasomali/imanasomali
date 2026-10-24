"""Configuração do ethos, lida das variáveis de ambiente e validada na subida.

Em produção, a unit app-ethos lê /etc/infra/smtp.env (credenciais SMTP) e
/etc/infra/apps/ethos.env (o resto, versionado em infra/apps/ethos/app.env). Em dev, as variáveis
vêm de um .env passado ao `uv run --env-file .env` (modelo em .env.example). Domínio, caminhos e
emails vêm sempre daqui, nunca fixos no código.
"""

import os
import re
from collections.abc import Mapping
from email.utils import parseaddr
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Self
from urllib.parse import urlsplit

from fastapi import Depends, Request
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)


class AppEnv(StrEnum):
    DEV = "dev"
    PROD = "prod"


class EmailBackend(StrEnum):
    SMTP = "smtp"
    # Só imprime o email no log; proibido fora de dev
    CONSOLE = "console"


class ConfigError(RuntimeError):
    """Configuração ausente ou inválida. A mensagem lista as variáveis, nunca os valores."""


# Limites das decisões de produto: inteiros positivos
Limit = Annotated[int, Field(ge=1)]

# Forma simples de endereço: sem espaço, sem os separadores de cabeçalho e com domínio com ponto.
# A validação completa é do provedor; aqui só barra erro de digitação e injeção de cabeçalho
_EMAIL_RE = re.compile(r"[^@\s<>()\[\],;:\"]+@[^@\s<>()\[\],;:\"]+\.[^@\s<>()\[\],;:\"]+")
_EMAIL_MAX_LENGTH = 254
_SMTP_FIELDS = ("smtp_host", "smtp_port", "smtp_user", "smtp_password")


def _is_email(value: str) -> bool:
    return len(value) <= _EMAIL_MAX_LENGTH and _EMAIL_RE.fullmatch(value) is not None


class Settings(BaseModel):
    """Toda a configuração do app. Cada campo é a variável de mesmo nome em maiúsculas."""

    model_config = ConfigDict(
        frozen=True,
        extra="ignore",
        alias_generator=str.upper,
        validate_by_alias=True,
        validate_by_name=True,
    )

    app_env: AppEnv
    # URL pública do front, ex.: https://manasomali.com/ethos (sem barra no fim)
    app_url: str
    database_path: Path
    email_backend: EmailBackend
    mail_from: str
    support_email: str

    # Credenciais SMTP (/etc/infra/smtp.env): obrigatórias com EMAIL_BACKEND=smtp
    smtp_host: str | None = None
    smtp_port: Annotated[int, Field(ge=1, le=65535)] | None = None
    smtp_user: str | None = None
    smtp_password: SecretStr | None = None

    # Teto global de envio de códigos, definido pela cota do provedor (sem valor padrão no plano)
    max_code_emails_per_hour: Limit
    max_code_emails_per_day: Limit

    # Limites das decisões de produto, com os valores padrão do plano
    max_habits_per_user: Limit = 10
    max_marks_per_day: Limit = 999
    max_note_length: Limit = 140
    max_guests_per_habit: Limit = 5
    max_shared_habits_per_user: Limit = 20
    max_invites_per_day: Limit = 20

    @model_validator(mode="before")
    @classmethod
    def _empty_is_missing(cls, data: Any) -> Any:
        # No .env e no EnvironmentFile=, "VAR=" é o mesmo que não definir a variável
        if isinstance(data, Mapping):
            return {
                key: value
                for key, value in data.items()
                if not (isinstance(value, str) and not value.strip())
            }
        return data

    @field_validator("app_url")
    @classmethod
    def _check_app_url(cls, value: str) -> str:
        if any(char.isspace() for char in value):
            raise ValueError("não pode ter espaços")
        parts = urlsplit(value)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError("precisa ser uma URL completa, ex.: https://manasomali.com/ethos")
        if parts.query or parts.fragment or parts.username or parts.password:
            raise ValueError("não pode ter usuário, query nem fragmento")
        # Acessar a porta valida o número (ValueError se não for)
        _ = parts.port
        return value.rstrip("/")

    @field_validator("database_path")
    @classmethod
    def _check_database_path(cls, value: Path) -> Path:
        # Banco em memória não serve: cada conexão do pool teria um banco diferente
        if str(value) == ":memory:":
            raise ValueError("precisa ser um arquivo")
        return value

    @field_validator("mail_from")
    @classmethod
    def _check_mail_from(cls, value: str) -> str:
        _, address = parseaddr(value)
        if "\r" in value or "\n" in value or not _is_email(address):
            raise ValueError('precisa ser um remetente, ex.: "ethos <no-reply@exemplo.com>"')
        return value

    @field_validator("support_email")
    @classmethod
    def _check_support_email(cls, value: str) -> str:
        if not _is_email(value):
            raise ValueError("precisa ser um endereço de email")
        return value

    @model_validator(mode="after")
    def _check_combinations(self) -> Self:
        if self.app_env is AppEnv.PROD:
            if self.email_backend is EmailBackend.CONSOLE:
                raise ValueError("EMAIL_BACKEND=console só é permitido com APP_ENV=dev")
            if urlsplit(self.app_url).scheme != "https":
                raise ValueError("APP_URL precisa ser https com APP_ENV=prod")
        if self.email_backend is EmailBackend.SMTP:
            missing = [name.upper() for name in _SMTP_FIELDS if getattr(self, name) is None]
            if missing:
                raise ValueError(f"EMAIL_BACKEND=smtp exige {', '.join(missing)}")
        if self.max_code_emails_per_hour > self.max_code_emails_per_day:
            raise ValueError("MAX_CODE_EMAILS_PER_HOUR não pode passar de MAX_CODE_EMAILS_PER_DAY")
        return self

    @property
    def is_dev(self) -> bool:
        return self.app_env is AppEnv.DEV

    @property
    def app_origin(self) -> str:
        """Esquema + host (+ porta, se não for a padrão) do APP_URL, como no header Origin."""
        parts = urlsplit(self.app_url)
        host = parts.hostname or ""
        if ":" in host:
            host = f"[{host}]"
        default_port = 443 if parts.scheme == "https" else 80
        if parts.port is not None and parts.port != default_port:
            host = f"{host}:{parts.port}"
        return f"{parts.scheme}://{host}"


# Nomes das variáveis de ambiente lidas, na ordem dos campos
ENV_VARS = tuple(name.upper() for name in Settings.model_fields)


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    """Lê e valida a configuração (por padrão, de os.environ).

    Levanta ConfigError com uma linha por variável problemática. A mensagem nunca traz o valor
    recebido (pode ser a senha do SMTP), e o ValidationError original não vai junto.
    """
    source = os.environ if environ is None else environ
    # Só os nomes em maiúsculas: "smtp_password" no ambiente não vira SMTP_PASSWORD
    data = {name: source[name] for name in ENV_VARS if name in source}
    try:
        return Settings.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(_describe(exc)) from None


def _describe(exc: ValidationError) -> str:
    lines = ["configuração inválida nas variáveis de ambiente:"]
    for error in exc.errors(include_url=False, include_input=False, include_context=False):
        if error["type"] == "missing":
            message = "obrigatória"
        else:
            message = error["msg"].removeprefix("Value error, ")
        name = ".".join(str(part) for part in error["loc"])
        lines.append(f"  {name}: {message}" if name else f"  {message}")
    return "\n".join(lines)


def get_settings(request: Request) -> Settings:
    """Dependência do FastAPI: a configuração carregada na subida do app."""
    return request.app.state.settings


SettingsDep = Annotated[Settings, Depends(get_settings)]
