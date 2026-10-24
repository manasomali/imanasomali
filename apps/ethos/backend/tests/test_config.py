import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import (
    ENV_VARS,
    AppEnv,
    ConfigError,
    EmailBackend,
    Settings,
    SettingsDep,
    load_settings,
)
from app.main import create_app

SMTP_PASSWORD = "senha-que-nao-pode-vazar"  # noqa: S105 (senha falsa do teste)


@pytest.fixture
def environ(tmp_path) -> dict[str, str]:
    """Ambiente mínimo válido, como o systemd entrega: tudo string."""
    return {
        "APP_ENV": "prod",
        "APP_URL": "https://exemplo.com/ethos",
        "DATABASE_PATH": str(tmp_path / "app.db"),
        "EMAIL_BACKEND": "smtp",
        "MAIL_FROM": "ethos <no-reply@exemplo.com>",
        "SUPPORT_EMAIL": "suporte@exemplo.com",
        "SMTP_HOST": "smtp.exemplo.com",
        "SMTP_PORT": "587",
        "SMTP_USER": "usuario",
        "SMTP_PASSWORD": SMTP_PASSWORD,
        "MAX_CODE_EMAILS_PER_HOUR": "50",
        "MAX_CODE_EMAILS_PER_DAY": "200",
    }


@pytest.fixture
def clean_env(monkeypatch) -> pytest.MonkeyPatch:
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def config_error(environ: dict[str, str]) -> str:
    with pytest.raises(ConfigError) as info:
        load_settings(environ)
    return str(info.value)


def test_loads_valid_environment(environ, tmp_path):
    settings = load_settings(environ)

    assert settings.app_env is AppEnv.PROD
    assert not settings.is_dev
    assert settings.app_url == "https://exemplo.com/ethos"
    assert settings.database_path == tmp_path / "app.db"
    assert settings.email_backend is EmailBackend.SMTP
    assert settings.smtp_port == 587
    assert settings.smtp_password is not None
    assert settings.smtp_password.get_secret_value() == SMTP_PASSWORD
    assert SMTP_PASSWORD not in repr(settings)


def test_limits_default_to_plan_values(environ):
    settings = load_settings(environ)

    assert settings.max_habits_per_user == 10
    assert settings.max_marks_per_day == 999
    assert settings.max_note_length == 140
    assert settings.max_guests_per_habit == 5
    assert settings.max_shared_habits_per_user == 20
    assert settings.max_invites_per_day == 20


def test_limits_come_from_environment(environ):
    environ |= {"MAX_HABITS_PER_USER": "3", "MAX_INVITES_PER_DAY": "7"}

    settings = load_settings(environ)

    assert settings.max_habits_per_user == 3
    assert settings.max_invites_per_day == 7


def test_reads_os_environ_by_default(environ, clean_env):
    for name, value in environ.items():
        clean_env.setenv(name, value)

    assert load_settings().app_url == "https://exemplo.com/ethos"


def test_lowercase_names_are_ignored(environ):
    environ["app_url"] = environ.pop("APP_URL")

    assert "APP_URL: obrigatória" in config_error(environ)


@pytest.mark.parametrize("name", ["APP_ENV", "APP_URL", "DATABASE_PATH", "MAIL_FROM"])
def test_missing_required_variable_names_it(environ, name):
    del environ[name]

    assert f"{name}: obrigatória" in config_error(environ)


def test_empty_value_counts_as_missing(environ):
    environ["SUPPORT_EMAIL"] = "  "

    assert "SUPPORT_EMAIL: obrigatória" in config_error(environ)


def test_lists_every_invalid_variable(environ):
    del environ["APP_URL"]
    environ["SMTP_PORT"] = "abc"

    message = config_error(environ)

    assert "APP_URL: obrigatória" in message
    assert "SMTP_PORT:" in message


def test_non_numeric_port_fails(environ):
    environ["SMTP_PORT"] = "porta"

    assert "SMTP_PORT: Input should be a valid integer" in config_error(environ)


@pytest.mark.parametrize("port", ["0", "65536", "-1"])
def test_out_of_range_port_fails(environ, port):
    environ["SMTP_PORT"] = port

    assert "SMTP_PORT:" in config_error(environ)


def test_error_never_shows_values(environ):
    environ["SMTP_PORT"] = "nao-e-porta"
    environ["MAX_HABITS_PER_USER"] = SMTP_PASSWORD

    with pytest.raises(ConfigError) as info:
        load_settings(environ)

    assert SMTP_PASSWORD not in str(info.value)
    assert "nao-e-porta" not in str(info.value)
    # O ValidationError original (que traz os valores) não vai junto no traceback
    assert info.value.__cause__ is None
    assert info.value.__suppress_context__


@pytest.mark.parametrize(
    "url",
    [
        "exemplo.com/ethos",
        "localhost:5174/ethos",
        "//exemplo.com/ethos",
        "ftp://exemplo.com/ethos",
        "https:///ethos",
        "https://exemplo.com/ethos?x=1",
        "https://exemplo.com/ethos#x",
        "https://usuario:senha@exemplo.com/ethos",
        "https://exemplo.com/eth os",
        "https://exemplo.com:porta/ethos",
    ],
)
def test_invalid_app_url_fails(environ, url):
    environ["APP_URL"] = url

    assert "APP_URL:" in config_error(environ)


def test_app_url_loses_trailing_slash(environ):
    environ["APP_URL"] = "https://exemplo.com/ethos/"

    assert load_settings(environ).app_url == "https://exemplo.com/ethos"


@pytest.mark.parametrize(
    ("url", "origin"),
    [
        ("https://manasomali.com/ethos", "https://manasomali.com"),
        ("https://Exemplo.COM:443/ethos", "https://exemplo.com"),
        ("https://exemplo.com:8443/ethos", "https://exemplo.com:8443"),
        ("http://localhost:5174/ethos", "http://localhost:5174"),
        ("http://localhost:80", "http://localhost"),
        ("http://[::1]:8000/ethos", "http://[::1]:8000"),
    ],
)
def test_app_origin(make_settings, url, origin):
    assert make_settings(app_url=url).app_origin == origin


def test_prod_requires_https(environ):
    environ["APP_URL"] = "http://exemplo.com/ethos"

    assert "APP_URL precisa ser https com APP_ENV=prod" in config_error(environ)


def test_console_email_refused_outside_dev(environ):
    environ["EMAIL_BACKEND"] = "console"

    assert "EMAIL_BACKEND=console só é permitido com APP_ENV=dev" in config_error(environ)


def test_console_email_in_dev_needs_no_smtp(environ):
    environ |= {"APP_ENV": "dev", "EMAIL_BACKEND": "console", "APP_URL": "http://localhost:5174"}
    for name in ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD"):
        environ[name] = ""

    settings = load_settings(environ)

    assert settings.is_dev
    assert settings.smtp_host is None
    assert settings.smtp_password is None


def test_smtp_backend_requires_credentials(environ):
    del environ["SMTP_HOST"]
    environ["SMTP_PASSWORD"] = ""

    assert "EMAIL_BACKEND=smtp exige SMTP_HOST, SMTP_PASSWORD" in config_error(environ)


@pytest.mark.parametrize("name", ["APP_ENV", "EMAIL_BACKEND"])
def test_unknown_choice_fails(environ, name):
    environ[name] = "staging"

    assert f"{name}:" in config_error(environ)


@pytest.mark.parametrize("value", ["0", "-5", "dez", "1.5"])
def test_limits_must_be_positive_integers(environ, value):
    environ["MAX_NOTE_LENGTH"] = value

    assert "MAX_NOTE_LENGTH:" in config_error(environ)


def test_hourly_cap_cannot_exceed_daily(environ):
    environ["MAX_CODE_EMAILS_PER_HOUR"] = "201"

    assert "MAX_CODE_EMAILS_PER_HOUR não pode passar" in config_error(environ)


def test_in_memory_database_fails(environ):
    environ["DATABASE_PATH"] = ":memory:"

    assert "DATABASE_PATH: precisa ser um arquivo" in config_error(environ)


@pytest.mark.parametrize(
    "value",
    [
        "no-reply",
        "ethos <no-reply>",
        "ethos <no-reply@exemplo>",
        "ethos <no-reply@exemplo.com>\r\nBcc: x@exemplo.com",
    ],
)
def test_invalid_mail_from_fails(environ, value):
    environ["MAIL_FROM"] = value

    assert "MAIL_FROM:" in config_error(environ)


def test_plain_mail_from_is_accepted(environ):
    environ["MAIL_FROM"] = "no-reply@exemplo.com"

    assert load_settings(environ).mail_from == "no-reply@exemplo.com"


@pytest.mark.parametrize(
    "value",
    ["suporte", "suporte@exemplo", "a b@exemplo.com", "<suporte@exemplo.com>", "x" * 250 + "@a.co"],
)
def test_invalid_support_email_fails(environ, value):
    environ["SUPPORT_EMAIL"] = value

    assert "SUPPORT_EMAIL:" in config_error(environ)


def test_app_fails_at_startup_without_config(clean_env):
    app = create_app()

    with pytest.raises(ConfigError, match="APP_URL: obrigatória"), TestClient(app):
        pass


def test_app_starts_with_config_from_environment(environ, clean_env):
    for name, value in environ.items():
        clean_env.setenv(name, value)

    with TestClient(create_app()) as client:
        assert client.app.state.settings.app_url == "https://exemplo.com/ethos"


def test_non_mapping_input_is_left_to_pydantic():
    with pytest.raises(ValidationError, match="model_type"):
        Settings.model_validate("APP_ENV=dev")


def test_settings_dependency(app, make_client, settings):
    @app.get("/test/settings")
    def read(current: SettingsDep) -> dict[str, str]:
        return {"app_url": current.app_url}

    response = make_client(app).get("/test/settings")

    assert response.json() == {"app_url": settings.app_url}
