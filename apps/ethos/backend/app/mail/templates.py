"""Textos dos emails em pt e en, montados em texto puro e em HTML simples.

Cada email vira uma lista de blocos (parágrafo, link, lista) e os dois formatos saem dos mesmos
blocos. Os textos daqui não têm HTML: o renderizador escapa tudo (`html.escape`), tanto o texto
fixo quanto os dados de quem chama (nome do hábito, email de quem convidou), então nome de hábito
com `<script>` sai como texto. Os assuntos são fixos por tipo e idioma, sem nenhum dado (nem nome
de hábito, nem email), e cabem no limite do imago (200 caracteres, uma linha).

Links saem sempre do `APP_URL` (o ethos) e do `account_url` da config (a tela de conta do imago,
`/imago/`, no rodapé). O caminho da tela de alertas (`ALERT_SETTINGS_PATH`) é contrato com as
rotas do front.
"""

import html
from dataclasses import dataclass

from app.mail.catalog import AccessLost, Alert, Email, HabitDeleted, Invite
from app.mail.language import Locale

# Tela de configuração do alerta de um hábito, relativa ao APP_URL
ALERT_SETTINGS_PATH = "/habits/{habit_id}/alerts"


_BODY_STYLE = (
    "margin:0;padding:24px 16px;background:#ffffff;color:#1f1f1f;"
    "font-family:system-ui,-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;"
    "font-size:16px;line-height:1.5"
)
_LINK_STYLE = "color:#0b57d0"
_FOOTER_STYLE = (
    "margin-top:32px;padding-top:16px;border-top:1px solid #dddddd;color:#5f5f5f;font-size:13px"
)


def _esc(value: str) -> str:
    return html.escape(value, quote=True)


@dataclass(frozen=True, slots=True)
class Paragraph:
    text: str

    def as_text(self) -> str:
        return self.text

    def as_html(self) -> str:
        return f"<p>{_esc(self.text)}</p>"


@dataclass(frozen=True, slots=True)
class Link:
    label: str
    url: str

    def as_text(self) -> str:
        return f"{self.label}: {self.url}"

    def as_html(self) -> str:
        return f'<p><a href="{_esc(self.url)}" style="{_LINK_STYLE}">{_esc(self.label)}</a></p>'


@dataclass(frozen=True, slots=True)
class Items:
    items: tuple[str, ...]

    def as_text(self) -> str:
        return "\n".join(f"- {item}" for item in self.items)

    def as_html(self) -> str:
        return "<ul>" + "".join(f"<li>{_esc(item)}</li>" for item in self.items) + "</ul>"


type Block = Paragraph | Link | Items


@dataclass(frozen=True, slots=True)
class RenderedEmail:
    subject: str
    text: str
    html: str


_PT: dict[str, str] = {
    "footer": "Email automático do ethos ({app_url}). Sua conta no manasomali.com: {account_url}",
    "period.week": "nesta semana",
    "period.month": "neste mês",
    "period.year": "neste ano",
    "role.editor": "edição",
    "role.viewer": "visualização",
    "open_app": "Abrir o ethos",
    "invite.subject": "Você recebeu um convite no ethos",
    "invite.intro": (
        "{inviter_email} convidou você para o hábito “{habit_name}” no ethos, com papel de {role}."
    ),
    "invite.action": "Para aceitar ou recusar, entre no ethos.",
    "invite.unknown": "Se não conhece quem convidou, é só recusar o convite.",
    "alert.subject": "Alerta de hábito no ethos",
    "alert.intro": "Alerta do hábito “{habit_name}”:",
    "alert.goal.behind": "Meta atrasada: {done} de {target} {period}, abaixo do ritmo.",
    "alert.goal.reached": "Máximo atingido: {done} de no máximo {target} {period}.",
    "alert.goal.exceeded": "Meta ultrapassada: {done} {period}, acima de {target}.",
    "alert.cost.warning": "Custo perto do limite: {spent} de {limit} {period}.",
    "alert.cost.exceeded": "Limite de custo ultrapassado: {spent} de {limit} {period}.",
    "alert.settings": "Configurar este alerta",
    "alert.once_a_day": "Você recebe no máximo um alerta por dia para cada hábito.",
    "access_lost.subject": "Aviso sobre hábitos compartilhados no ethos",
    "access_lost.body": (
        "A conta da pessoa dona destes hábitos foi excluída, e os hábitos foram apagados com "
        "todas as marcações. Você não tem mais acesso a:"
    ),
    "habit_deleted.subject": "Um hábito compartilhado foi apagado",
    "habit_deleted.body": (
        "O hábito “{habit_name}”, compartilhado com você, foi apagado pela pessoa dona, "
        "com todas as marcações."
    ),
}

_EN: dict[str, str] = {
    "footer": "Automatic email from ethos ({app_url}). Your manasomali.com account: {account_url}",
    "period.week": "this week",
    "period.month": "this month",
    "period.year": "this year",
    "role.editor": "editor",
    "role.viewer": "viewer",
    "open_app": "Open ethos",
    "invite.subject": "You've been invited on ethos",
    "invite.intro": (
        "{inviter_email} invited you to the habit “{habit_name}” on ethos, with the {role} role."
    ),
    "invite.action": "To accept or decline, sign in to ethos.",
    "invite.unknown": "If you don't know who invited you, just decline the invitation.",
    "alert.subject": "Habit alert from ethos",
    "alert.intro": "Alert for the habit “{habit_name}”:",
    "alert.goal.behind": "Goal behind pace: {done} of {target} {period}.",
    "alert.goal.reached": "Maximum reached: {done} of at most {target} {period}.",
    "alert.goal.exceeded": "Goal exceeded: {done} {period}, above {target}.",
    "alert.cost.warning": "Cost close to the limit: {spent} of {limit} {period}.",
    "alert.cost.exceeded": "Cost limit exceeded: {spent} of {limit} {period}.",
    "alert.settings": "Alert settings",
    "alert.once_a_day": "You get at most one alert per day for each habit.",
    "access_lost.subject": "Notice about shared habits on ethos",
    "access_lost.body": (
        "The account that owned these habits was deleted, and the habits were deleted with all "
        "their marks. You no longer have access to:"
    ),
    "habit_deleted.subject": "A shared habit was deleted",
    "habit_deleted.body": (
        "The habit “{habit_name}”, shared with you, was deleted by its owner, along with all "
        "its marks."
    ),
}

TEXTS: dict[Locale, dict[str, str]] = {Locale.PT: _PT, Locale.EN: _EN}
_HTML_LANG = {Locale.PT: "pt-BR", Locale.EN: "en"}


class _Translator:
    def __init__(self, locale: Locale) -> None:
        self.locale = locale
        self._texts = TEXTS[locale]

    def __call__(self, key: str, **values: object) -> str:
        # Só o texto fixo é molde: os valores entram como dados, nunca como formato
        return self._texts[key].format(**values)


def format_money(cents: int, locale: Locale) -> str:
    """Valor em centavos com 2 casas, no formato do idioma (1.234,50 / 1,234.50), sem moeda."""
    sign = "-" if cents < 0 else ""
    units, rest = divmod(abs(cents), 100)
    thousands, decimal = (".", ",") if locale is Locale.PT else (",", ".")
    grouped = f"{units:,}".replace(",", thousands)
    return f"{sign}{grouped}{decimal}{rest:02d}"


def render(email: Email, locale: Locale, *, app_url: str, account_url: str) -> RenderedEmail:
    """Monta assunto, texto e HTML de um email do catálogo no idioma pedido."""
    t = _Translator(locale)
    subject, blocks = _content(email, t, app_url=app_url)
    footer = t("footer", app_url=app_url, account_url=account_url)
    return RenderedEmail(
        subject=subject,
        text=_render_text(blocks, footer),
        html=_render_html(blocks, footer, subject=subject, lang=_HTML_LANG[locale]),
    )


def _content(email: Email, t: _Translator, *, app_url: str) -> tuple[str, list[Block]]:
    match email:
        case Invite(habit_name=habit_name, inviter_email=inviter_email, role=role):
            intro = t(
                "invite.intro",
                inviter_email=inviter_email,
                habit_name=habit_name,
                role=t(f"role.{role}"),
            )
            return t("invite.subject"), [
                Paragraph(intro),
                Paragraph(t("invite.action")),
                Link(t("open_app"), f"{app_url}/"),
                Paragraph(t("invite.unknown")),
            ]
        case Alert():
            return t("alert.subject"), _alert_blocks(email, t, app_url)
        case AccessLost(habit_names=habit_names):
            return t("access_lost.subject"), [
                Paragraph(t("access_lost.body")),
                Items(habit_names),
            ]
        case HabitDeleted(habit_name=habit_name):
            return t("habit_deleted.subject"), [
                Paragraph(t("habit_deleted.body", habit_name=habit_name)),
            ]
        case _:
            raise TypeError(f"email fora do catálogo: {type(email).__name__}")


def _alert_blocks(alert: Alert, t: _Translator, app_url: str) -> list[Block]:
    blocks: list[Block] = [Paragraph(t("alert.intro", habit_name=alert.habit_name))]
    if alert.goal is not None:
        goal = alert.goal
        blocks.append(
            Paragraph(
                t(
                    f"alert.goal.{goal.status}",
                    done=goal.done,
                    target=goal.target,
                    period=t(f"period.{goal.period}"),
                )
            )
        )
    if alert.cost is not None:
        cost = alert.cost
        blocks.append(
            Paragraph(
                t(
                    f"alert.cost.{cost.status}",
                    spent=format_money(cost.spent_cents, t.locale),
                    limit=format_money(cost.limit_cents, t.locale),
                    period=t(f"period.{cost.period}"),
                )
            )
        )
    # int() garante que só um número entra no caminho
    path = ALERT_SETTINGS_PATH.format(habit_id=int(alert.habit_id))
    blocks.append(Link(t("alert.settings"), f"{app_url}{path}"))
    blocks.append(Paragraph(t("alert.once_a_day")))
    return blocks


def _render_text(blocks: list[Block], footer: str) -> str:
    # "-- " separa a assinatura nos clientes de email
    return "\n\n".join(block.as_text() for block in blocks) + f"\n\n-- \n{footer}\n"


def _render_html(blocks: list[Block], footer: str, *, subject: str, lang: str) -> str:
    content = "\n".join(block.as_html() for block in blocks)
    return (
        "<!doctype html>\n"
        f'<html lang="{lang}">\n'
        '<head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{_esc(subject)}</title></head>\n"
        f'<body style="{_BODY_STYLE}">\n'
        '<div style="max-width:560px;margin:0 auto">\n'
        f"{content}\n"
        f'<p style="{_FOOTER_STYLE}">{_esc(footer)}</p>\n'
        "</div>\n</body>\n</html>\n"
    )
