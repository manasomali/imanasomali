import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import (
    ENV_VARS,
    AppEnv,
    ConfigError,
    Settings,
    SettingsDep,
    load_settings,
)
from app.main import create_app

TOKEN = "token-que-nao-pode-vazar-0123456789abcdefgh"  # noqa: S105 (token falso do teste)
# As variáveis do login próprio de antes do imago, que o app.env só perde no PR de infra B
LEGACY = {
    "EMAIL_BACKEND": "smtp",
    "MAIL_FROM": "ethos <no-reply@exemplo.com>",
    "SUPPORT_EMAIL": "suporte@exemplo.com",
    "MAX_CODE_EMAILS_PER_HOUR": "50",
    "MAX_CODE_EMAILS_PER_DAY": "200",
    "SMTP_HOST": "smtp.exemplo.com",
    "SMTP_PORT": "porta-invalida",
    "SMTP_USER": "usuario",
    "SMTP_PASSWORD": "senha",
}


@pytest.fixture
def environ(tmp_path) -> dict[str, str]:
    """Ambiente mínimo válido, como o systemd entrega: tudo string."""
    return {
        "APP_ENV": "prod",
        "APP_URL": "https://exemplo.com/ethos",
        "DATABASE_PATH": str(tmp_path / "app.db"),
        "IMAGO_INTERNAL_URL": "http://127.0.0.1:3003",
        "INTERNAL_API_TOKEN": TOKEN,
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
    assert settings.imago_internal_url == "http://127.0.0.1:3003"
    assert settings.internal_api_token.get_secret_value() == TOKEN
    assert TOKEN not in repr(settings)
    assert settings.account_url == "https://exemplo.com/imago/"


def test_env_vars_are_the_fields():
    assert ENV_VARS == (
        "APP_ENV",
        "APP_URL",
        "DATABASE_PATH",
        "IMAGO_INTERNAL_URL",
        "INTERNAL_API_TOKEN",
        "MAX_HABITS_PER_USER",
        "MAX_MARKS_PER_DAY",
        "MAX_NOTE_LENGTH",
        "MAX_GUESTS_PER_HABIT",
        "MAX_SHARED_HABITS_PER_USER",
        "MAX_INVITES_PER_DAY",
    )


def test_legacy_variables_are_ignored(environ):
    # Até o PR de infra B, o app.env ainda traz as do login próprio (e o smtp.env pode sobrar)
    assert load_settings(environ | LEGACY) == load_settings(environ)


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


@pytest.mark.parametrize(
    "name", ["APP_ENV", "APP_URL", "DATABASE_PATH", "IMAGO_INTERNAL_URL", "INTERNAL_API_TOKEN"]
)
def test_missing_required_variable_names_it(environ, name):
    del environ[name]

    assert f"{name}: obrigatória" in config_error(environ)


def test_empty_value_counts_as_missing(environ):
    environ["INTERNAL_API_TOKEN"] = "  "  # noqa: S105 (valor vazio do teste)

    assert "INTERNAL_API_TOKEN: obrigatória" in config_error(environ)


def test_lists_every_invalid_variable(environ):
    del environ["APP_URL"]
    environ["IMAGO_INTERNAL_URL"] = "nao-e-url"

    message = config_error(environ)

    assert "APP_URL: obrigatória" in message
    assert "IMAGO_INTERNAL_URL:" in message


def test_error_never_shows_values(environ):
    environ["INTERNAL_API_TOKEN"] = "curto-" + TOKEN[:10]
    environ["MAX_HABITS_PER_USER"] = TOKEN

    with pytest.raises(ConfigError) as info:
        load_settings(environ)

    assert TOKEN[:10] not in str(info.value)
    # O ValidationError original (que traz os valores) não vai junto no traceback
    assert info.value.__cause__ is None
    assert info.value.__suppress_context__


@pytest.mark.parametrize(
    "token",
    [
        "a" * 31,
        "a" * 257,
        "a" * 31 + "+",
        "a" * 31 + "=",
        "a" * 31 + "/",
        "a" * 31 + " ",
        "ã" * 40,
    ],
)
def test_invalid_internal_api_token_fails(environ, token):
    environ["INTERNAL_API_TOKEN"] = token

    message = config_error(environ)

    assert "INTERNAL_API_TOKEN: precisa ter de 32 a 256 caracteres base64url" in message
    assert token not in message


@pytest.mark.parametrize("token", ["a" * 32, "A-z_0" * 9, "a" * 256])
def test_valid_internal_api_token(environ, token):
    environ["INTERNAL_API_TOKEN"] = token

    assert load_settings(environ).internal_api_token.get_secret_value() == token


@pytest.mark.parametrize(
    "url",
    [
        "127.0.0.1:3003",
        "ftp://127.0.0.1:3003",
        "http://",
        "http://127.0.0.1:3003/api/imago",
        "http://127.0.0.1:3003?x=1",
        "http://127.0.0.1:3003#x",
        "http://user:senha@127.0.0.1:3003",
        "http://127.0.0.1:porta",
        "http://127.0.0.1: 3003",
    ],
)
def test_invalid_imago_internal_url_fails(environ, url):
    environ["IMAGO_INTERNAL_URL"] = url

    assert "IMAGO_INTERNAL_URL:" in config_error(environ)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://127.0.0.1:3003/", "http://127.0.0.1:3003"),
        ("http://localhost:3003", "http://localhost:3003"),
        ("https://imago.interno", "https://imago.interno"),
    ],
)
def test_valid_imago_internal_url(environ, url, expected):
    environ["IMAGO_INTERNAL_URL"] = url

    assert load_settings(environ).imago_internal_url == expected


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
    settings = make_settings(app_url=url)
    assert settings.app_origin == origin
    assert settings.account_url == f"{origin}/imago/"


def test_prod_requires_https(environ):
    environ["APP_URL"] = "http://exemplo.com/ethos"

    assert "APP_URL precisa ser https com APP_ENV=prod" in config_error(environ)


def test_dev_accepts_http(environ):
    environ |= {"APP_ENV": "dev", "APP_URL": "http://localhost:5174/ethos"}

    assert load_settings(environ).is_dev


def test_unknown_app_env_fails(environ):
    environ["APP_ENV"] = "staging"

    assert "APP_ENV:" in config_error(environ)


@pytest.mark.parametrize("value", ["0", "-5", "dez", "1.5"])
def test_limits_must_be_positive_integers(environ, value):
    environ["MAX_NOTE_LENGTH"] = value

    assert "MAX_NOTE_LENGTH:" in config_error(environ)


def test_in_memory_database_fails(environ):
    environ["DATABASE_PATH"] = ":memory:"

    assert "DATABASE_PATH: precisa ser um arquivo" in config_error(environ)


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
