import pytest

from app.mail.language import Locale, pick_locale


@pytest.mark.parametrize(
    ("user_locale", "accept_language", "expected"),
    [
        # users.locale vence o Accept-Language
        ("pt", "en-US,en;q=0.9", Locale.PT),
        ("en", "pt-BR", Locale.EN),
        ("pt-BR", None, Locale.PT),
        ("PT_br", None, Locale.PT),
        (" en-GB ", None, Locale.EN),
        # Idioma da conta sem template: vale o Accept-Language
        ("fr", "pt-BR,pt;q=0.9", Locale.PT),
        (None, "pt-BR,pt;q=0.9,en;q=0.8", Locale.PT),
        ("", "pt", Locale.PT),
        # Ordem pelo q, não pela posição
        (None, "en;q=0.5, pt;q=0.8", Locale.PT),
        (None, "fr-FR, de;q=0.9, en;q=0.1, pt;q=0.05", Locale.EN),
        # Empate no q: vale a ordem do header
        (None, "pt;q=0.7, en;q=0.7", Locale.PT),
        # q=0 é "não aceito"; q inválido, nan e inf são ignorados
        (None, "pt;q=0, en", Locale.EN),
        (None, "pt;q=abc, en;q=0.1", Locale.EN),
        (None, "pt;q=nan, pt;q=inf, en;q=0.2", Locale.EN),
        (None, "pt; Q=0.9", Locale.PT),
        # Nada reconhecido: en
        (None, None, Locale.EN),
        (None, "", Locale.EN),
        (None, "*", Locale.EN),
        (None, "fr, de", Locale.EN),
        (None, ",,;;q=;", Locale.EN),
        ("xx", "zz", Locale.EN),
    ],
)
def test_pick_locale(user_locale, accept_language, expected):
    assert pick_locale(user_locale, accept_language) is expected


def test_huge_accept_language_only_reads_the_first_items():
    header = ", ".join(["fr"] * 10_000 + ["pt"])

    assert pick_locale(None, header) is Locale.EN
