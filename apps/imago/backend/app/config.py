"""Configuração do imago, lida das variáveis de ambiente e validada na subida.

Em produção, a unit app-imago lê /etc/infra/smtp.env (credenciais SMTP; é a única unit que lê esse
arquivo), /etc/infra/internal/imago.env (`IMAGO_APP_TOKENS`) e /etc/infra/apps/imago.env (o resto,
versionado em infra/apps/imago/app.env). Em dev, as variáveis vêm de um .env passado ao
`uv run --env-file .env` (modelo em .env.example). Domínio, caminhos e emails vêm sempre daqui,
nunca fixos no código.

Aplicações (`IMAGO_APPS` e `IMAGO_APP_TOKENS`):

- `IMAGO_APPS=ethos=http://127.0.0.1:3001,engrafi=http://127.0.0.1:3002`: as aplicações que usam
  o imago, na ordem em que aparecem na tela de conta. Nome com a regra do `infra/databases.txt`
  (`^[a-z][a-z0-9-]{1,26}$`, nunca `imago`), URL só `http://127.0.0.1:<porta>`, sem caminho. Pode
  ficar vazia (testes, ensaio);
- `IMAGO_APP_TOKENS=ethos:<token>,engrafi:<token>`: o token da API interna de cada aplicação
  (base64url, 32 a 512 caracteres), o mesmo nos dois sentidos. Toda aplicação do `IMAGO_APPS`
  precisa do seu, e dois nomes não podem ter o mesmo token (o token diz quem chamou). Token de um
  nome fora do `IMAGO_APPS` é aceito na subida, mas não autentica nada: só as aplicações do
  `IMAGO_APPS` existem para o imago.

Nenhuma mensagem de erro traz um valor recebido: os tokens e a senha do SMTP passam por aqui.
"""

import hmac
import os
import re
from collections.abc import Mapping
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


# Nome do próprio imago no `mail_log` e no remetente dos emails dele: nenhuma aplicação pode usá-lo
IMAGO_APP_NAME = "imago"

# Tetos de envio: inteiros positivos. Reservas para códigos: zero ou mais
Limit = Annotated[int, Field(ge=1)]
Reserve = Annotated[int, Field(ge=0)]

# Forma simples de endereço: sem espaço, sem os separadores de cabeçalho e com domínio com ponto.
# A validação completa é do provedor; aqui só barra erro de digitação e injeção de cabeçalho
_EMAIL_RE = re.compile(r"[^@\s<>()\[\],;:\"]+@[^@\s<>()\[\],;:\"]+\.[^@\s<>()\[\],;:\"]+")
EMAIL_MAX_LENGTH = 254
_SMTP_FIELDS = ("smtp_host", "smtp_port", "smtp_user", "smtp_password")

# Nome de aplicação: a mesma regra dos bancos do infra/databases.txt
APP_NAME_RE = re.compile(r"[a-z][a-z0-9-]{1,26}")
_APP_URL_RE = re.compile(r"http://127\.0\.0\.1:([1-9][0-9]{0,4})")
_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{32,512}")


def is_email(value: str) -> bool:
    """Endereço simples, só ASCII, até 254 caracteres. Usado também pelo login (app/auth).

    Só ASCII porque o email vai no header `X-User-Email` para as aplicações (domínio
    internacional entra em punycode).
    """
    return (
        len(value) <= EMAIL_MAX_LENGTH
        and value.isascii()
        and _EMAIL_RE.fullmatch(value) is not None
    )


class ImagoApp(BaseModel):
    """Uma aplicação do `IMAGO_APPS`: nome e URL da API interna dela."""

    model_config = ConfigDict(frozen=True)

    name: str
    url: str


class AppToken(BaseModel):
    """Token da API interna de uma aplicação (`IMAGO_APP_TOKENS`)."""

    model_config = ConfigDict(frozen=True)

    name: str
    token: SecretStr


def _items(value: str, variable: str) -> list[str]:
    items = [item.strip() for item in value.split(",")]
    for index, item in enumerate(items, start=1):
        if not item:
            raise ValueError(f"item {index} vazio (vírgula sobrando em {variable})")
    return items


def _check_app_name(name: str, index: int) -> str:
    # O nome só aparece na mensagem depois de passar na regex: nunca um valor qualquer
    if APP_NAME_RE.fullmatch(name) is None:
        raise ValueError(f"item {index}: nome inválido (regra ^[a-z][a-z0-9-]{{1,26}}$)")
    if name == IMAGO_APP_NAME:
        raise ValueError(f"item {index}: {IMAGO_APP_NAME} é o próprio imago, não uma aplicação")
    return name


def _parse_apps(value: str) -> list[dict[str, str]]:
    apps: list[dict[str, str]] = []
    for index, item in enumerate(_items(value, "IMAGO_APPS"), start=1):
        name, separator, url = item.partition("=")
        if not separator:
            raise ValueError(f"item {index} sem '=' (use nome=http://127.0.0.1:<porta>)")
        name = _check_app_name(name, index)
        match = _APP_URL_RE.fullmatch(url)
        if match is None or int(match.group(1)) > 65535:
            raise ValueError(f"{name}: a URL precisa ser http://127.0.0.1:<porta>, sem caminho")
        if any(app["name"] == name for app in apps):
            raise ValueError(f"{name} repetida")
        apps.append({"name": name, "url": url})
    return apps


def _parse_tokens(value: str) -> list[dict[str, str]]:
    tokens: list[dict[str, str]] = []
    for index, item in enumerate(_items(value, "IMAGO_APP_TOKENS"), start=1):
        name, separator, token = item.partition(":")
        if not separator:
            raise ValueError(f"item {index} sem ':' (use nome:token)")
        name = _check_app_name(name, index)
        if _TOKEN_RE.fullmatch(token) is None:
            raise ValueError(f"{name}: o token precisa ser base64url, com 32 a 512 caracteres")
        if any(entry["name"] == name for entry in tokens):
            raise ValueError(f"{name} repetida")
        tokens.append({"name": name, "token": token})
    return tokens


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
    # URL pública do front, ex.: https://manasomali.com/imago (sem barra no fim). A origem dela é
    # a única aceita no header Origin
    app_url: str
    database_path: Path
    # Contato mostrado na tela de conta e nos emails; recebe o aviso de teto de envio
    support_email: str
    # Endereço do remetente de todos os emails, ex.: no-reply@manasomali.com. O nome que aparece
    # é "manasomali.com" (emails do imago) ou o da aplicação que pediu o envio
    mail_from_address: str
    email_backend: EmailBackend
    # Aplicações que usam o imago, na ordem do IMAGO_APPS (ver o docstring do módulo)
    imago_apps: tuple[ImagoApp, ...] = ()

    # Teto de envio de email, um só para o imago e todas as aplicações, em janelas móveis de
    # 24 h e de 1 h. O fim de cada janela fica só para códigos e emails de conta
    max_emails_per_day: Limit = 275
    max_emails_per_hour: Limit = 60
    mail_reserved_for_codes_per_day: Reserve = 60
    mail_reserved_for_codes_per_hour: Reserve = 15

    # Credenciais SMTP (/etc/infra/smtp.env): obrigatórias com EMAIL_BACKEND=smtp
    smtp_host: str | None = None
    smtp_port: Annotated[int, Field(ge=1, le=65535)] | None = None
    smtp_user: str | None = None
    smtp_password: SecretStr | None = None

    # Token da API interna de cada aplicação (/etc/infra/internal/imago.env)
    imago_app_tokens: tuple[AppToken, ...] = ()

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
            raise ValueError("precisa ser uma URL completa, ex.: https://manasomali.com/imago")
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

    @field_validator("support_email", "mail_from_address")
    @classmethod
    def _check_address(cls, value: str) -> str:
        if not is_email(value):
            raise ValueError("precisa ser um endereço de email, ex.: no-reply@exemplo.com")
        return value

    @field_validator("imago_apps", mode="before")
    @classmethod
    def _parse_imago_apps(cls, value: Any) -> Any:
        return _parse_apps(value) if isinstance(value, str) else value

    @field_validator("imago_app_tokens", mode="before")
    @classmethod
    def _parse_imago_app_tokens(cls, value: Any) -> Any:
        return _parse_tokens(value) if isinstance(value, str) else value

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
        self._check_mail_limits()
        self._check_app_tokens()
        return self

    def _check_mail_limits(self) -> None:
        if self.max_emails_per_hour > self.max_emails_per_day:
            raise ValueError("MAX_EMAILS_PER_HOUR não pode passar de MAX_EMAILS_PER_DAY")
        if self.mail_reserved_for_codes_per_day > self.max_emails_per_day:
            raise ValueError(
                "MAIL_RESERVED_FOR_CODES_PER_DAY não pode passar de MAX_EMAILS_PER_DAY"
            )
        if self.mail_reserved_for_codes_per_hour > self.max_emails_per_hour:
            raise ValueError(
                "MAIL_RESERVED_FOR_CODES_PER_HOUR não pode passar de MAX_EMAILS_PER_HOUR"
            )

    def _check_app_tokens(self) -> None:
        names = {entry.name for entry in self.imago_app_tokens}
        missing = [app.name for app in self.imago_apps if app.name not in names]
        if missing:
            raise ValueError(f"IMAGO_APP_TOKENS sem o token de {', '.join(missing)}")
        values = [entry.token.get_secret_value() for entry in self.imago_app_tokens]
        if len(set(values)) != len(values):
            raise ValueError("IMAGO_APP_TOKENS com o mesmo token em duas aplicações")

    @property
    def is_dev(self) -> bool:
        return self.app_env is AppEnv.DEV

    @property
    def app_names(self) -> tuple[str, ...]:
        """Nomes das aplicações do `IMAGO_APPS`, na ordem dele."""
        return tuple(app.name for app in self.imago_apps)

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

    def app_token(self, name: str) -> SecretStr | None:
        """Token da aplicação `name` do `IMAGO_APPS`, ou None se ela não está lá."""
        if name not in self.app_names:
            return None
        # _check_app_tokens garante o token de toda aplicação do IMAGO_APPS
        return next(entry.token for entry in self.imago_app_tokens if entry.name == name)

    def app_for_token(self, token: str) -> str | None:
        """Nome da aplicação do `IMAGO_APPS` dona de `token`, ou None.

        Compara com o token de todas as aplicações, sempre até o fim e com `hmac.compare_digest`,
        para o tempo de resposta não dizer quanto do token estava certo nem de qual aplicação era.
        """
        received = token.encode("utf-8", "surrogatepass")
        apps = set(self.app_names)
        found: str | None = None
        for entry in self.imago_app_tokens:
            expected = entry.token.get_secret_value().encode("ascii")
            if hmac.compare_digest(received, expected) and entry.name in apps:
                found = entry.name
        return found


# Nomes das variáveis de ambiente lidas, na ordem dos campos
ENV_VARS = tuple(name.upper() for name in Settings.model_fields)


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    """Lê e valida a configuração (por padrão, de os.environ).

    Levanta ConfigError com uma linha por variável problemática. A mensagem nunca traz o valor
    recebido (pode ser a senha do SMTP ou um token), e o ValidationError original não vai junto.
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
