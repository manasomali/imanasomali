import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import (
    ENV_VARS,
    AppEnv,
    ConfigError,
    EmailBackend,
    ImagoApp,
    Settings,
    SettingsDep,
    load_settings,
)
from app.main import create_app

SMTP_PASSWORD = "senha-que-nao-pode-vazar"  # noqa: S105 (senha falsa do teste)
ETHOS = "ethos-token-que-nao-pode-vazar-0000000000000"
ENGRAFI = "engrafi-token-que-nao-pode-vazar-00000000000"


@pytest.fixture
def environ(tmp_path) -> dict[str, str]:
    """Ambiente válido de produção, como o systemd entrega: tudo string."""
    return {
        "APP_ENV": "prod",
        "APP_URL": "https://manasomali.com/imago",
        "DATABASE_PATH": str(tmp_path / "app.db"),
        "SUPPORT_EMAIL": "suporte@manasomali.com",
        "MAIL_FROM_ADDRESS": "no-reply@manasomali.com",
        "EMAIL_BACKEND": "smtp",
        "IMAGO_APPS": "ethos=http://127.0.0.1:3001,engrafi=http://127.0.0.1:3002",
        "MAX_EMAILS_PER_DAY": "275",
        "MAX_EMAILS_PER_HOUR": "60",
        "MAIL_RESERVED_FOR_CODES_PER_DAY": "60",
        "MAIL_RESERVED_FOR_CODES_PER_HOUR": "15",
        "SMTP_HOST": "smtp.exemplo.com",
        "SMTP_PORT": "587",
        "SMTP_USER": "usuario",
        "SMTP_PASSWORD": SMTP_PASSWORD,
        "IMAGO_APP_TOKENS": f"engrafi:{ENGRAFI},ethos:{ETHOS}",
    }


def config_error(environ: dict[str, str]) -> str:
    with pytest.raises(ConfigError) as info:
        load_settings(environ)
    message = str(info.value)
    # Nenhum segredo na mensagem, qualquer que seja o erro
    for secret in (SMTP_PASSWORD, ETHOS, ENGRAFI):
        assert secret not in message
    return message


def test_loads_valid_environment(environ, tmp_path):
    settings = load_settings(environ)

    assert settings.app_env is AppEnv.PROD
    assert not settings.is_dev
    assert settings.app_url == "https://manasomali.com/imago"
    assert settings.app_origin == "https://manasomali.com"
    assert settings.database_path == tmp_path / "app.db"
    assert settings.email_backend is EmailBackend.SMTP
    assert settings.mail_from_address == "no-reply@manasomali.com"
    # Na ordem do IMAGO_APPS, não na dos tokens
    assert settings.imago_apps == (
        ImagoApp(name="ethos", url="http://127.0.0.1:3001"),
        ImagoApp(name="engrafi", url="http://127.0.0.1:3002"),
    )
    assert settings.app_names == ("ethos", "engrafi")
    assert settings.app_token("ethos").get_secret_value() == ETHOS
    assert (settings.max_emails_per_day, settings.max_emails_per_hour) == (275, 60)
    assert (
        settings.mail_reserved_for_codes_per_day,
        settings.mail_reserved_for_codes_per_hour,
    ) == (60, 15)
    for secret in (SMTP_PASSWORD, ETHOS, ENGRAFI):
        assert secret not in repr(settings)


def test_env_vars_are_the_contract_names():
    assert set(ENV_VARS) == {
        "APP_ENV",
        "APP_URL",
        "DATABASE_PATH",
        "SUPPORT_EMAIL",
        "MAIL_FROM_ADDRESS",
        "EMAIL_BACKEND",
        "IMAGO_APPS",
        "MAX_EMAILS_PER_DAY",
        "MAX_EMAILS_PER_HOUR",
        "MAIL_RESERVED_FOR_CODES_PER_DAY",
        "MAIL_RESERVED_FOR_CODES_PER_HOUR",
        "SMTP_HOST",
        "SMTP_PORT",
        "SMTP_USER",
        "SMTP_PASSWORD",
        "IMAGO_APP_TOKENS",
    }


def test_mail_limits_default_to_plan_values(environ):
    for name in [n for n in environ if n.startswith(("MAX_EMAILS", "MAIL_RESERVED"))]:
        del environ[name]

    settings = load_settings(environ)

    assert settings.max_emails_per_day == 275
    assert settings.max_emails_per_hour == 60
    assert settings.mail_reserved_for_codes_per_day == 60
    assert settings.mail_reserved_for_codes_per_hour == 15


def test_imago_apps_may_be_empty(environ):
    environ |= {"IMAGO_APPS": "", "IMAGO_APP_TOKENS": ""}

    settings = load_settings(environ)

    assert settings.imago_apps == ()
    assert settings.app_names == ()
    assert settings.app_for_token(ETHOS) is None


def test_spaces_around_items_are_ignored(environ):
    environ |= {
        "IMAGO_APPS": " ethos=http://127.0.0.1:3001 , engrafi=http://127.0.0.1:3002 ",
        "IMAGO_APP_TOKENS": f" ethos:{ETHOS} ,engrafi:{ENGRAFI}",
    }

    assert load_settings(environ).app_names == ("ethos", "engrafi")


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("ethos=http://localhost:3001", "ethos: a URL precisa ser http://127.0.0.1:<porta>"),
        ("ethos=http://10.0.0.5:3001", "ethos: a URL precisa ser"),
        ("ethos=https://127.0.0.1:3001", "ethos: a URL precisa ser"),
        ("ethos=http://127.0.0.1:3001/", "ethos: a URL precisa ser"),
        ("ethos=http://127.0.0.1:3001/api", "ethos: a URL precisa ser"),
        ("ethos=http://127.0.0.1", "ethos: a URL precisa ser"),
        ("ethos=http://127.0.0.1:0", "ethos: a URL precisa ser"),
        ("ethos=http://127.0.0.1:65536", "ethos: a URL precisa ser"),
        ("ethos=http://127.0.0.1:03001", "ethos: a URL precisa ser"),
        ("ethos=http://user@127.0.0.1:3001", "ethos: a URL precisa ser"),
        ("ethos", "item 1 sem '='"),
        ("ethos=http://127.0.0.1:3001,", "item 2 vazio"),
        ("Ethos=http://127.0.0.1:3001", "item 1: nome inválido"),
        ("e=http://127.0.0.1:3001", "item 1: nome inválido"),
        ("imago=http://127.0.0.1:3003", "item 1: imago é o próprio imago"),
        (
            "ethos=http://127.0.0.1:3001,ethos=http://127.0.0.1:3002",
            "ethos repetida",
        ),
    ],
)
def test_invalid_imago_apps_stop_the_startup(environ, value, message):
    environ["IMAGO_APPS"] = value

    assert message in config_error(environ)


def test_app_without_token_stops_the_startup(environ):
    environ["IMAGO_APP_TOKENS"] = f"ethos:{ETHOS}"

    assert "IMAGO_APP_TOKENS sem o token de engrafi" in config_error(environ)


def test_missing_tokens_stop_the_startup(environ):
    del environ["IMAGO_APP_TOKENS"]

    assert "IMAGO_APP_TOKENS sem o token de ethos, engrafi" in config_error(environ)


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (f"ethos:{ETHOS[:31]},engrafi:{ENGRAFI}", "ethos: o token precisa ser base64url"),
        (f"ethos:{ETHOS}=,engrafi:{ENGRAFI}", "ethos: o token precisa ser base64url"),
        (f"ethos:{'a' * 513},engrafi:{ENGRAFI}", "ethos: o token precisa ser base64url"),
        (f"ethos {ETHOS},engrafi:{ENGRAFI}", "item 1 sem ':'"),
        (f"{ETHOS}", "item 1 sem ':'"),
        (f"ethos:{ETHOS},ethos:{ENGRAFI}", "ethos repetida"),
        (f"ethos:{ETHOS},engrafi:{ETHOS}", "o mesmo token em duas aplicações"),
        (f"ETHOS:{ETHOS},engrafi:{ENGRAFI}", "item 1: nome inválido"),
    ],
)
def test_invalid_tokens_stop_the_startup(environ, value, message):
    environ["IMAGO_APP_TOKENS"] = value

    assert message in config_error(environ)


def test_token_of_an_app_outside_imago_apps_authenticates_nothing(environ):
    environ |= {"IMAGO_APPS": "ethos=http://127.0.0.1:3001"}

    settings = load_settings(environ)

    assert settings.app_for_token(ETHOS) == "ethos"
    assert settings.app_for_token(ENGRAFI) is None
    assert settings.app_token("engrafi") is None


@pytest.mark.parametrize("token", ["", ETHOS[:-1], ETHOS + "x", ETHOS.upper(), "token-ção"])
def test_app_for_token_refuses_anything_else(environ, token):
    assert load_settings(environ).app_for_token(token) is None


def test_console_backend_is_refused_outside_dev(environ):
    environ["EMAIL_BACKEND"] = "console"

    assert "EMAIL_BACKEND=console só é permitido com APP_ENV=dev" in config_error(environ)


def test_prod_requires_https(environ):
    environ["APP_URL"] = "http://manasomali.com/imago"

    assert "APP_URL precisa ser https com APP_ENV=prod" in config_error(environ)


def test_smtp_backend_requires_credentials(environ):
    del environ["SMTP_HOST"]
    environ["SMTP_PASSWORD"] = ""

    assert "EMAIL_BACKEND=smtp exige SMTP_HOST, SMTP_PASSWORD" in config_error(environ)


def test_dev_with_console_needs_no_smtp(environ):
    environ |= {
        "APP_ENV": "dev",
        "EMAIL_BACKEND": "console",
        "APP_URL": "http://localhost:8080/imago",
    }
    for name in ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD"):
        del environ[name]

    settings = load_settings(environ)

    assert settings.is_dev
    assert settings.app_origin == "http://localhost:8080"


@pytest.mark.parametrize(
    ("values", "message"),
    [
        (
            {"MAX_EMAILS_PER_HOUR": "300"},
            "MAX_EMAILS_PER_HOUR não pode passar de MAX_EMAILS_PER_DAY",
        ),
        (
            {"MAIL_RESERVED_FOR_CODES_PER_DAY": "276"},
            "MAIL_RESERVED_FOR_CODES_PER_DAY não pode passar de MAX_EMAILS_PER_DAY",
        ),
        (
            {"MAIL_RESERVED_FOR_CODES_PER_HOUR": "61"},
            "MAIL_RESERVED_FOR_CODES_PER_HOUR não pode passar de MAX_EMAILS_PER_HOUR",
        ),
        ({"MAX_EMAILS_PER_DAY": "0"}, "MAX_EMAILS_PER_DAY"),
        ({"MAIL_RESERVED_FOR_CODES_PER_DAY": "-1"}, "MAIL_RESERVED_FOR_CODES_PER_DAY"),
        ({"MAX_EMAILS_PER_HOUR": "muitos"}, "MAX_EMAILS_PER_HOUR"),
    ],
)
def test_mail_limits_are_validated(environ, values, message):
    environ |= values

    assert message in config_error(environ)


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("APP_URL", "manasomali.com/imago", "precisa ser uma URL completa"),
        ("APP_URL", "https://manasomali.com/imago?x=1", "não pode ter usuário, query"),
        ("APP_URL", "https://manasomali.com/ imago", "não pode ter espaços"),
        ("APP_URL", "https://manasomali.com:99999/imago", "APP_URL"),
        ("DATABASE_PATH", ":memory:", "precisa ser um arquivo"),
        ("SUPPORT_EMAIL", "suporte", "precisa ser um endereço de email"),
        ("SUPPORT_EMAIL", "suporte@manasomalí.com", "precisa ser um endereço de email"),
        ("MAIL_FROM_ADDRESS", "manasomali.com <no-reply@manasomali.com>", "endereço de email"),
        ("MAIL_FROM_ADDRESS", "no-reply@manasomali.com\nBcc: x@y.com", "endereço de email"),
        ("APP_ENV", "staging", "APP_ENV"),
        ("SMTP_PORT", "70000", "SMTP_PORT"),
    ],
)
def test_invalid_values_are_reported_without_the_value(environ, name, value, message):
    environ[name] = value

    error = config_error(environ)

    assert message in error
    assert name in error


def test_missing_required_variables_are_listed(environ):
    for name in ("APP_ENV", "APP_URL", "DATABASE_PATH", "SUPPORT_EMAIL", "MAIL_FROM_ADDRESS"):
        environ[name] = "  "

    error = config_error(environ)

    for name in ("APP_ENV", "APP_URL", "DATABASE_PATH", "SUPPORT_EMAIL", "MAIL_FROM_ADDRESS"):
        assert f"{name}: obrigatória" in error


def test_lowercase_names_are_ignored(environ):
    environ["smtp_password"] = environ.pop("SMTP_PASSWORD")

    assert "SMTP_PASSWORD" in config_error(environ)


def test_reads_os_environ_by_default(environ, monkeypatch):
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    for name, value in environ.items():
        monkeypatch.setenv(name, value)

    assert load_settings().app_names == ("ethos", "engrafi")


def test_invalid_config_stops_the_server_at_startup(environ, monkeypatch):
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    environ["IMAGO_APPS"] = "ethos=http://192.168.0.2:3001"
    for name, value in environ.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(ConfigError, match="IMAGO_APPS"), TestClient(create_app()):
        pass  # pragma: no cover


def test_app_origin_with_ipv6_and_port(environ):
    environ |= {"APP_ENV": "dev", "APP_URL": "http://[::1]:8080/imago"}

    assert load_settings(environ).app_origin == "http://[::1]:8080"


def test_only_mappings_are_settings():
    with pytest.raises(ValidationError):
        Settings.model_validate(["APP_ENV=dev"])


def test_settings_dependency_is_the_loaded_config(app, make_client):
    @app.get("/test/settings")
    def read(settings: SettingsDep) -> dict[str, str]:
        return {"origin": settings.app_origin}

    assert make_client(app).get("/test/settings").json() == {"origin": "http://localhost:8080"}
