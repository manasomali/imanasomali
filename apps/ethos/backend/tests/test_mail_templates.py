import re
from html.parser import HTMLParser

import pytest

from app.mail.catalog import (
    AccessLost,
    AccountDeleted,
    Alert,
    CostAlert,
    DeleteCode,
    EmailChangedNew,
    EmailChangedOld,
    EmailKind,
    GoalAlert,
    HabitDeleted,
    Invite,
    LoginCode,
    SendCapReached,
)
from app.mail.language import Locale
from app.mail.templates import TEXTS, format_money, render

APP_URL = "https://ethos.example.com/ethos"
SUPPORT = "suporte@example.com"
CODE = "042917"
SCRIPT = "<script>alert('x')</script>"

# Um exemplo de cada email do catálogo
SAMPLES = {
    EmailKind.LOGIN_CODE: LoginCode(code=CODE),
    EmailKind.DELETE_CODE: DeleteCode(code=CODE),
    EmailKind.INVITE: Invite(habit_name="Ler", inviter_email="dono@example.com", role="editor"),
    EmailKind.ALERT: Alert(
        habit_id=7,
        habit_name="Ler",
        goal=GoalAlert(status="behind", done=1, target=3, period="week"),
        cost=CostAlert(status="warning", spent_cents=8000, limit_cents=10000, period="month"),
    ),
    EmailKind.ACCOUNT_DELETED: AccountDeleted(),
    EmailKind.ACCESS_LOST: AccessLost(habit_names=("Ler", "Correr")),
    EmailKind.HABIT_DELETED: HabitDeleted(habit_name="Ler"),
    EmailKind.EMAIL_CHANGED_OLD: EmailChangedOld(new_email="novo@example.com"),
    EmailKind.EMAIL_CHANGED_NEW: EmailChangedNew(),
    EmailKind.SEND_CAP_REACHED: SendCapReached(window="hour", limit=50),
}

# O dado de cada exemplo que precisa aparecer no corpo
EXPECTED_IN_BODY = {
    EmailKind.LOGIN_CODE: [CODE],
    EmailKind.DELETE_CODE: [CODE],
    EmailKind.INVITE: ["Ler", "dono@example.com", f"{APP_URL}/"],
    EmailKind.ALERT: ["Ler", f"{APP_URL}/habits/7/alerts"],
    EmailKind.ACCOUNT_DELETED: [SUPPORT],
    EmailKind.ACCESS_LOST: ["Ler", "Correr"],
    EmailKind.HABIT_DELETED: ["Ler"],
    EmailKind.EMAIL_CHANGED_OLD: ["novo@example.com", SUPPORT],
    EmailKind.EMAIL_CHANGED_NEW: [f"{APP_URL}/", SUPPORT],
    EmailKind.SEND_CAP_REACHED: ["50"],
}


def build(email, locale):
    return render(email, locale, app_url=APP_URL, support_email=SUPPORT)


class _TagCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[str] = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)


def html_tags(document: str) -> list[str]:
    parser = _TagCollector()
    parser.feed(document)
    parser.close()
    return parser.tags


def test_samples_cover_the_whole_catalog():
    assert set(SAMPLES) == set(EmailKind)
    assert all(SAMPLES[kind].kind is kind for kind in EmailKind)


def test_pt_and_en_have_the_same_texts():
    assert set(TEXTS) == set(Locale)
    assert TEXTS[Locale.PT].keys() == TEXTS[Locale.EN].keys()
    # Mesmos campos nos dois idiomas
    for key, pt in TEXTS[Locale.PT].items():
        assert set(re.findall(r"{(\w+)}", pt)) == set(re.findall(r"{(\w+)}", TEXTS[Locale.EN][key]))


def test_texts_have_no_html():
    for texts in TEXTS.values():
        for text in texts.values():
            assert "<" not in text
            assert ">" not in text
            assert "&" not in text


@pytest.mark.parametrize("locale", list(Locale))
@pytest.mark.parametrize("kind", list(EmailKind))
def test_every_email_renders(kind, locale):
    rendered = build(SAMPLES[kind], locale)

    assert rendered.subject.strip()
    assert "\n" not in rendered.subject
    assert rendered.subject == TEXTS[locale][f"{kind}.subject"]
    footer = TEXTS[locale]["footer"].format(app_url=APP_URL, support_email=SUPPORT)
    assert rendered.text.endswith(f"\n\n-- \n{footer}\n")
    assert footer in rendered.html
    for value in EXPECTED_IN_BODY[kind]:
        assert value in rendered.text
        assert value in rendered.html
    lang = "pt-BR" if locale is Locale.PT else "en"
    assert rendered.html.startswith(f'<!doctype html>\n<html lang="{lang}">')
    tags = html_tags(rendered.html)
    assert {"html", "head", "title", "body", "p"} <= set(tags)
    assert "script" not in tags


@pytest.mark.parametrize("locale", list(Locale))
@pytest.mark.parametrize("email", [LoginCode(code=CODE), DeleteCode(code=CODE)])
def test_code_is_in_the_body_and_never_in_the_subject(email, locale):
    rendered = build(email, locale)

    assert CODE not in rendered.subject
    assert not re.search(r"\d", rendered.subject)
    assert CODE in rendered.text
    assert f">{CODE}</p>" in rendered.html
    assert "10" in rendered.text


def test_login_code_texts():
    pt = build(LoginCode(code=CODE, valid_minutes=15), Locale.PT)
    en = build(LoginCode(code=CODE), Locale.EN)

    assert "Nunca compartilhe este código" in pt.text
    assert "Se não foi você que pediu, ignore este email." in pt.text
    assert "15 minutos" in pt.text
    assert "Never share this code" in en.text
    assert "If you didn't request it, ignore this email." in en.text
    assert "10 minutes" in en.text


@pytest.mark.parametrize("locale", list(Locale))
@pytest.mark.parametrize(
    "email",
    [
        Invite(habit_name=SCRIPT, inviter_email="dono@example.com", role="viewer"),
        Invite(habit_name="Ler", inviter_email=f"{SCRIPT}@example.com", role="viewer"),
        Alert(
            habit_id=1,
            habit_name=SCRIPT,
            goal=GoalAlert(status="reached", done=2, target=2, period="year"),
        ),
        AccessLost(habit_names=("Ler", SCRIPT)),
        HabitDeleted(habit_name=SCRIPT),
        EmailChangedOld(new_email=f'"{SCRIPT}"@example.com'),
    ],
)
def test_user_text_is_escaped_in_html(email, locale):
    rendered = build(email, locale)

    assert "<script>" not in rendered.html
    assert "&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;" in rendered.html
    assert "script" not in html_tags(rendered.html)
    # No texto puro não há o que escapar
    assert SCRIPT in rendered.text
    # O assunto nunca leva dado de quem chama
    assert "script" not in rendered.subject


def test_link_and_app_url_are_escaped_in_html():
    rendered = render(
        Alert(
            habit_id=3,
            habit_name="Ler",
            cost=CostAlert(status="exceeded", spent_cents=1, limit_cents=0, period="week"),
        ),
        Locale.EN,
        app_url='https://example.com/a"b',
        support_email=SUPPORT,
    )

    assert 'href="https://example.com/a&quot;b/habits/3/alerts"' in rendered.html


@pytest.mark.parametrize(
    ("goal", "pt", "en"),
    [
        (
            GoalAlert(status="behind", done=1, target=3, period="week"),
            "Meta atrasada: 1 de 3 nesta semana",
            "Goal behind pace: 1 of 3 this week.",
        ),
        (
            GoalAlert(status="reached", done=4, target=4, period="month"),
            "Máximo atingido: 4 de no máximo 4 neste mês.",
            "Maximum reached: 4 of at most 4 this month.",
        ),
        (
            GoalAlert(status="exceeded", done=13, target=12, period="year"),
            "Meta ultrapassada: 13 neste ano, acima de 12.",
            "Goal exceeded: 13 this year, above 12.",
        ),
    ],
)
def test_alert_goal_texts(goal, pt, en):
    email = Alert(habit_id=1, habit_name="Ler", goal=goal)

    assert pt in build(email, Locale.PT).text
    assert en in build(email, Locale.EN).text
    # Só a meta: nada de custo
    assert "Custo" not in build(email, Locale.PT).text


@pytest.mark.parametrize(
    ("cost", "pt", "en"),
    [
        (
            CostAlert(status="warning", spent_cents=812_050, limit_cents=1_000_000, period="month"),
            "Custo perto do limite: 8.120,50 de 10.000,00 neste mês.",
            "Cost close to the limit: 8,120.50 of 10,000.00 this month.",
        ),
        (
            CostAlert(status="exceeded", spent_cents=1005, limit_cents=1000, period="week"),
            "Limite de custo ultrapassado: 10,05 de 10,00 nesta semana.",
            "Cost limit exceeded: 10.05 of 10.00 this week.",
        ),
    ],
)
def test_alert_cost_texts(cost, pt, en):
    email = Alert(habit_id=1, habit_name="Ler", cost=cost)

    assert pt in build(email, Locale.PT).text
    assert en in build(email, Locale.EN).text
    assert "Meta" not in build(email, Locale.PT).text


def test_alert_with_goal_and_cost_is_one_email():
    rendered = build(SAMPLES[EmailKind.ALERT], Locale.PT)

    assert "Meta atrasada" in rendered.text
    assert "Custo perto do limite" in rendered.text
    assert rendered.text.index("Meta atrasada") < rendered.text.index("Custo perto do limite")


@pytest.mark.parametrize(
    ("cents", "pt", "en"),
    [
        (0, "0,00", "0.00"),
        (5, "0,05", "0.05"),
        (123_450, "1.234,50", "1,234.50"),
        (123_456_789, "1.234.567,89", "1,234,567.89"),
        (-150, "-1,50", "-1.50"),
    ],
)
def test_format_money(cents, pt, en):
    assert format_money(cents, Locale.PT) == pt
    assert format_money(cents, Locale.EN) == en


def test_send_cap_window_text():
    assert "(200 por dia)" in build(SendCapReached(window="day", limit=200), Locale.PT).text
    assert "(50 per hour)" in build(SendCapReached(window="hour", limit=50), Locale.EN).text


def test_text_body_lists_items_and_links():
    access = build(AccessLost(habit_names=("Ler", "Correr")), Locale.EN)
    invite = build(SAMPLES[EmailKind.INVITE], Locale.PT)

    assert "- Ler\n- Correr" in access.text
    assert "<li>Ler</li><li>Correr</li>" in access.html
    assert f"Abrir o ethos: {APP_URL}/" in invite.text
    assert "papel de edição" in invite.text


def test_unknown_email_type_is_refused():
    with pytest.raises(TypeError, match="fora do catálogo"):
        build(object(), Locale.EN)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "factory",
    [
        lambda: LoginCode(code="12345"),
        lambda: LoginCode(code="1234567"),
        lambda: LoginCode(code="12345a"),
        # Dígitos de largura total passam no str.isdigit(), mas não são o código
        lambda: LoginCode(code=chr(0xFF11) * 6),
        lambda: LoginCode(code="123456\n"),
        lambda: LoginCode(code="123456", valid_minutes=0),
        lambda: DeleteCode(code="hash"),
        lambda: DeleteCode(code="123456", valid_minutes=-1),
        lambda: Invite(habit_name="Ler", inviter_email="a@b.c", role="owner"),
        lambda: Alert(habit_id=1, habit_name="Ler"),
        lambda: GoalAlert(status="late", done=1, target=2, period="week"),
        lambda: GoalAlert(status="behind", done=1, target=2, period="day"),
        lambda: CostAlert(status="ok", spent_cents=1, limit_cents=2, period="week"),
        lambda: CostAlert(status="warning", spent_cents=1, limit_cents=2, period="day"),
        lambda: AccessLost(habit_names=()),
        lambda: SendCapReached(window="minute", limit=1),
    ],
)
def test_invalid_email_data_is_refused(factory):
    with pytest.raises(ValueError, match=r"\w"):
        factory()


def test_sensitive_fields_stay_out_of_repr():
    for email in (
        LoginCode(code=CODE),
        DeleteCode(code=CODE),
        Invite(habit_name="Ler", inviter_email="dono@example.com", role="editor"),
        EmailChangedOld(new_email="novo@example.com"),
    ):
        text = repr(email)
        assert CODE not in text
        assert "@example.com" not in text
