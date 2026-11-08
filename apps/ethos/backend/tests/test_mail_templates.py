import re
from html.parser import HTMLParser

import pytest

from app.mail.catalog import (
    AccessLost,
    Alert,
    CostAlert,
    EmailKind,
    GoalAlert,
    HabitDeleted,
    Invite,
)
from app.mail.language import Locale
from app.mail.templates import TEXTS, format_money, render

APP_URL = "https://ethos.example.com/ethos"
ACCOUNT_URL = "https://ethos.example.com/imago/"
SCRIPT = "<script>alert('x')</script>"

# Um exemplo de cada email do catálogo
SAMPLES = {
    EmailKind.INVITE: Invite(habit_name="Ler", inviter_email="dono@example.com", role="editor"),
    EmailKind.ALERT: Alert(
        habit_id=7,
        habit_name="Ler",
        goal=GoalAlert(status="behind", done=1, target=3, period="week"),
        cost=CostAlert(status="warning", spent_cents=8000, limit_cents=10000, period="month"),
    ),
    EmailKind.ACCESS_LOST: AccessLost(habit_names=("Ler", "Correr")),
    EmailKind.HABIT_DELETED: HabitDeleted(habit_name="Ler"),
}

# O dado de cada exemplo que precisa aparecer no corpo
EXPECTED_IN_BODY = {
    EmailKind.INVITE: ["Ler", "dono@example.com", f"{APP_URL}/"],
    EmailKind.ALERT: ["Ler", f"{APP_URL}/habits/7/alerts"],
    EmailKind.ACCESS_LOST: ["Ler", "Correr"],
    EmailKind.HABIT_DELETED: ["Ler"],
}


def build(email, locale):
    return render(email, locale, app_url=APP_URL, account_url=ACCOUNT_URL)


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
    footer = TEXTS[locale]["footer"].format(app_url=APP_URL, account_url=ACCOUNT_URL)
    assert rendered.text.endswith(f"\n\n-- \n{footer}\n")
    # O rodapé leva para a conta no imago (o suporte e o resto da conta ficam lá)
    assert ACCOUNT_URL in footer
    assert len(rendered.subject) <= 200
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
        account_url=ACCOUNT_URL,
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
        lambda: Invite(habit_name="Ler", inviter_email="a@b.c", role="owner"),
        lambda: Alert(habit_id=1, habit_name="Ler"),
        lambda: GoalAlert(status="late", done=1, target=2, period="week"),
        lambda: GoalAlert(status="behind", done=1, target=2, period="day"),
        lambda: CostAlert(status="ok", spent_cents=1, limit_cents=2, period="week"),
        lambda: CostAlert(status="warning", spent_cents=1, limit_cents=2, period="day"),
        lambda: AccessLost(habit_names=()),
    ],
)
def test_invalid_email_data_is_refused(factory):
    with pytest.raises(ValueError, match=r"\w"):
        factory()


def test_sensitive_fields_stay_out_of_repr():
    email = Invite(habit_name="Ler", inviter_email="dono@example.com", role="editor")
    assert "@example.com" not in repr(email)
