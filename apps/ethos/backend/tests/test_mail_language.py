import pytest

from app.mail.language import Locale, pick_locale


@pytest.mark.parametrize(
    ("user_locale", "expected"),
    [
        ("pt", Locale.PT),
        ("en", Locale.EN),
        ("pt-BR", Locale.PT),
        ("PT_br", Locale.PT),
        (" en-GB ", Locale.EN),
        # Nada reconhecido: en
        ("fr", Locale.EN),
        ("", Locale.EN),
        (None, Locale.EN),
        ("-", Locale.EN),
        ("xx-pt", Locale.EN),
    ],
)
def test_pick_locale(user_locale, expected):
    assert pick_locale(user_locale) is expected


def test_default_is_english():
    assert pick_locale() is Locale.EN
