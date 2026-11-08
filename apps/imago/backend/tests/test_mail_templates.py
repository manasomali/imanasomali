import re
import string
import typing

import pytest

from app.mail import catalog
from app.mail.catalog import (
    AccountDeleted,
    DeleteCode,
    EmailChangedNew,
    EmailChangedOld,
    EmailKind,
    LoginCode,
    SendCapReached,
)
from app.mail.kinds import MailKind
from app.mail.language import Locale
from app.mail.templates import TEXTS, render

APP_URL = "https://manasomali.com/imago"
SUPPORT = "suporte@manasomali.com"
CODE = "004217"

EXAMPLES = [
    LoginCode(code=CODE),
    DeleteCode(code=CODE),
    AccountDeleted(),
    EmailChangedOld(new_email="novo@example.com"),
    EmailChangedNew(),
    SendCapReached(window="day", limit=275),
]


def rendered(email, locale=Locale.PT):
    return render(email, locale, app_url=APP_URL, support_email=SUPPORT)


def test_examples_cover_the_whole_catalog():
    assert {type(email) for email in EXAMPLES} == set(typing.get_args(catalog.Email.__value__))
    assert {email.kind for email in EXAMPLES} == set(EmailKind)


def test_both_languages_have_the_same_keys_and_placeholders():
    def placeholders(text: str) -> set[str]:
        return {name for _, name, _, _ in string.Formatter().parse(text) if name}

    assert TEXTS[Locale.PT].keys() == TEXTS[Locale.EN].keys()
    for key, text in TEXTS[Locale.PT].items():
        assert placeholders(text) == placeholders(TEXTS[Locale.EN][key]), key


@pytest.mark.parametrize("locale", list(Locale))
@pytest.mark.parametrize("email", EXAMPLES, ids=lambda email: email.kind.value)
def test_every_email_renders(email, locale):
    result = rendered(email, locale)

    assert result.subject
    # Nenhum dado no assunto: nem código nem email
    assert CODE not in result.subject
    assert "@" not in result.subject
    assert result.text.endswith(
        f"-- \n{TEXTS[locale]['footer'].format(app_url=APP_URL, support_email=SUPPORT)}\n"
    )
    assert result.html.startswith("<!doctype html>")
    lang = "pt-BR" if locale is Locale.PT else "en"
    assert f'<html lang="{lang}">' in result.html
    # Nenhum molde sobrando
    assert not re.search(r"\{[a-z_]+\}", result.text)


@pytest.mark.parametrize("email", [LoginCode(code=CODE), DeleteCode(code=CODE)])
def test_codes_are_in_the_body_with_the_warnings(email):
    pt, en = rendered(email, Locale.PT), rendered(email, Locale.EN)

    assert f"\n\n{CODE}\n\n" in pt.text
    assert "Nunca compartilhe este código com ninguém." in pt.text
    assert "Se não foi você que pediu, ignore este email" in pt.text
    assert "O código vale por 10 minutos" in pt.text
    assert "Never share this code with anyone." in en.text
    assert "If you didn't request it, ignore this email" in en.text


def test_subjects():
    assert rendered(LoginCode(code=CODE)).subject == "Seu código de acesso ao manasomali.com"
    assert rendered(LoginCode(code=CODE), Locale.EN).subject == "Your manasomali.com sign-in code"
    assert rendered(SendCapReached(window="hour", limit=60)).subject == (
        "manasomali.com: teto de envio de email atingido"
    )


def test_user_data_is_escaped_in_html():
    email = EmailChangedOld(new_email='<script>alert("x")</script>@example.com')

    result = rendered(email)

    assert "<script>" not in result.html
    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;@example.com" in result.html
    assert '<script>alert("x")</script>@example.com' in result.text


def test_email_changed_new_links_to_the_account():
    result = rendered(EmailChangedNew(), Locale.EN)

    assert f"Open your account: {APP_URL}/" in result.text
    assert f'<a href="{APP_URL}/"' in result.html
    assert SUPPORT in result.text


def test_send_cap_reached_says_the_window_and_limit():
    assert "(275 em 24 horas)" in rendered(SendCapReached(window="day", limit=275)).text
    assert "(45 per hour)" in rendered(SendCapReached(window="hour", limit=45), Locale.EN).text


def test_mail_kinds():
    assert LoginCode.mail_kind is MailKind.CODE
    assert DeleteCode.mail_kind is MailKind.CODE
    assert AccountDeleted.mail_kind is MailKind.ACCOUNT
    assert EmailChangedOld.mail_kind is MailKind.ACCOUNT
    assert EmailChangedNew.mail_kind is MailKind.ACCOUNT
    # O aviso ao suporte fica fora do teto
    assert SendCapReached.mail_kind is None


@pytest.mark.parametrize("code", ["12345", "1234567", "abcdef", "12 456", "١٢٣٤٥٦"])
@pytest.mark.parametrize("kind", [LoginCode, DeleteCode])
def test_invalid_code_is_refused(kind, code):
    with pytest.raises(ValueError, match="6 dígitos"):
        kind(code=code)


@pytest.mark.parametrize("kind", [LoginCode, DeleteCode])
def test_validity_must_be_positive(kind):
    with pytest.raises(ValueError, match="pelo menos 1 minuto"):
        kind(code=CODE, valid_minutes=0)


def test_invalid_window_is_refused():
    with pytest.raises(ValueError, match="janela inválida"):
        SendCapReached(window="week", limit=1)  # type: ignore[arg-type]


def test_secrets_are_out_of_repr():
    assert CODE not in repr(LoginCode(code=CODE))
    assert CODE not in repr(DeleteCode(code=CODE))
    assert "novo@example.com" not in repr(EmailChangedOld(new_email="novo@example.com"))


def test_unknown_email_is_refused():
    with pytest.raises(TypeError, match="email fora do catálogo"):
        rendered(object())  # type: ignore[arg-type]
