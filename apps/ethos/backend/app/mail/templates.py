"""Textos dos emails em pt e en, montados em texto puro e em HTML simples.

Cada email vira uma lista de blocos (parágrafo, código, link, lista) e os dois formatos saem dos
mesmos blocos. Os textos daqui não têm HTML: o renderizador escapa tudo (`html.escape`), tanto o
texto fixo quanto os dados de quem chama (nome do hábito, emails), então nome de hábito com
`<script>` sai como texto. Os assuntos são fixos por tipo e idioma, sem nenhum dado: nunca o
código (aparece em notificação de tela bloqueada), nem nome de hábito ou email.

Links saem sempre do `APP_URL`. O caminho da tela de alertas (`ALERT_SETTINGS_PATH`) é contrato
com as rotas do front.
"""

import html
from dataclasses import dataclass

from app.mail.catalog import (
    AccessLost,
    AccountDeleted,
    Alert,
    DeleteCode,
    Email,
    EmailChangedNew,
    EmailChangedOld,
    HabitDeleted,
    Invite,
    LoginCode,
    SendCapReached,
)
from app.mail.language import Locale

# Tela de configuração do alerta de um hábito, relativa ao APP_URL
ALERT_SETTINGS_PATH = "/habits/{habit_id}/alerts"


_BODY_STYLE = (
    "margin:0;padding:24px 16px;background:#ffffff;color:#1f1f1f;"
    "font-family:system-ui,-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;"
    "font-size:16px;line-height:1.5"
)
_CODE_STYLE = (
    "margin:24px 0;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:32px;"
    "font-weight:700;letter-spacing:8px"
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
class Code:
    value: str

    def as_text(self) -> str:
        return self.value

    def as_html(self) -> str:
        return f'<p style="{_CODE_STYLE}">{_esc(self.value)}</p>'


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


type Block = Paragraph | Code | Link | Items


@dataclass(frozen=True, slots=True)
class RenderedEmail:
    subject: str
    text: str
    html: str


_PT: dict[str, str] = {
    "footer": "Email automático do ethos ({app_url}). Dúvidas: {support_email}",
    "never_share": "Nunca compartilhe este código com ninguém.",
    "valid_for": "O código vale por {minutes} minutos e só pode ser usado uma vez.",
    "period.week": "nesta semana",
    "period.month": "neste mês",
    "period.year": "neste ano",
    "role.editor": "edição",
    "role.viewer": "visualização",
    "open_app": "Abrir o ethos",
    "login_code.subject": "Seu código de acesso ao ethos",
    "login_code.intro": "Use este código para entrar no ethos:",
    "login_code.ignore": "Se não foi você que pediu, ignore este email.",
    "delete_code.subject": "Código para excluir sua conta do ethos",
    "delete_code.intro": "Use este código para confirmar a exclusão da sua conta do ethos:",
    "delete_code.warning": (
        "A exclusão apaga a sua conta e os hábitos dos quais você é dono, e não pode ser desfeita."
    ),
    "delete_code.ignore": (
        "Se não foi você que pediu, ignore este email: a sua conta continua como está."
    ),
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
    "account_deleted.subject": "Sua conta do ethos foi excluída",
    "account_deleted.body": (
        "A sua conta do ethos foi excluída, junto com os hábitos dos quais você era dono."
    ),
    "account_deleted.backups": "Os dados somem também das cópias de segurança em até 8 dias.",
    "account_deleted.not_you": "Se não foi você que pediu, escreva para {support_email}.",
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
    "email_changed_old.subject": "O email da sua conta do ethos foi trocado",
    "email_changed_old.body": (
        "A pedido feito ao suporte, o email da sua conta do ethos foi trocado para "
        "{new_email}. Este endereço não entra mais na conta."
    ),
    "email_changed_old.not_you": (
        "Se não foi você que pediu, responda a este email ou escreva para {support_email}."
    ),
    "email_changed_new.subject": "Este é o novo email da sua conta do ethos",
    "email_changed_new.body": (
        "A pedido feito ao suporte, este endereço passou a ser o email da sua conta do ethos. "
        "Para entrar, peça um código com ele."
    ),
    "email_changed_new.not_you": "Se não reconhece este pedido, escreva para {support_email}.",
    "send_cap_reached.subject": "ethos: teto de envio de códigos atingido",
    "send_cap_reached.body": (
        "O teto global de envio de códigos ({limit} {window}) foi atingido. Novos pedidos de "
        "código recebem 429 até a janela passar."
    ),
    "send_cap_reached.window.hour": "por hora",
    "send_cap_reached.window.day": "por dia",
    "send_cap_reached.action": (
        "Se for abuso, confira os logs e considere um captcha. Se for uso normal, revise "
        "MAX_CODE_EMAILS_PER_HOUR, MAX_CODE_EMAILS_PER_DAY e a cota do provedor."
    ),
    "send_cap_reached.once_an_hour": "Este aviso sai no máximo uma vez por hora.",
}

_EN: dict[str, str] = {
    "footer": "Automatic email from ethos ({app_url}). Questions: {support_email}",
    "never_share": "Never share this code with anyone.",
    "valid_for": "The code is valid for {minutes} minutes and can only be used once.",
    "period.week": "this week",
    "period.month": "this month",
    "period.year": "this year",
    "role.editor": "editor",
    "role.viewer": "viewer",
    "open_app": "Open ethos",
    "login_code.subject": "Your ethos sign-in code",
    "login_code.intro": "Use this code to sign in to ethos:",
    "login_code.ignore": "If you didn't request it, ignore this email.",
    "delete_code.subject": "Code to delete your ethos account",
    "delete_code.intro": "Use this code to confirm the deletion of your ethos account:",
    "delete_code.warning": (
        "Deleting removes your account and the habits you own, and it cannot be undone."
    ),
    "delete_code.ignore": "If you didn't request it, ignore this email: your account stays as is.",
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
    "account_deleted.subject": "Your ethos account was deleted",
    "account_deleted.body": "Your ethos account was deleted, along with the habits you owned.",
    "account_deleted.backups": "The data is also gone from backups within 8 days.",
    "account_deleted.not_you": "If you didn't ask for this, write to {support_email}.",
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
    "email_changed_old.subject": "Your ethos account email was changed",
    "email_changed_old.body": (
        "At a request made to support, the email of your ethos account was changed to "
        "{new_email}. This address no longer signs in to the account."
    ),
    "email_changed_old.not_you": (
        "If you didn't ask for this, reply to this email or write to {support_email}."
    ),
    "email_changed_new.subject": "This is now your ethos account email",
    "email_changed_new.body": (
        "At a request made to support, this address is now the email of your ethos account. "
        "To sign in, request a code with it."
    ),
    "email_changed_new.not_you": "If you don't recognize this request, write to {support_email}.",
    "send_cap_reached.subject": "ethos: code email cap reached",
    "send_cap_reached.body": (
        "The global cap on code emails ({limit} {window}) was reached. New code requests get "
        "a 429 until the window passes."
    ),
    "send_cap_reached.window.hour": "per hour",
    "send_cap_reached.window.day": "per day",
    "send_cap_reached.action": (
        "If it is abuse, check the logs and consider a captcha. If it is normal use, review "
        "MAX_CODE_EMAILS_PER_HOUR, MAX_CODE_EMAILS_PER_DAY and the provider's quota."
    ),
    "send_cap_reached.once_an_hour": "This notice goes out at most once an hour.",
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


def render(email: Email, locale: Locale, *, app_url: str, support_email: str) -> RenderedEmail:
    """Monta assunto, texto e HTML de um email do catálogo no idioma pedido."""
    t = _Translator(locale)
    subject, blocks = _content(email, t, app_url=app_url, support_email=support_email)
    footer = t("footer", app_url=app_url, support_email=support_email)
    return RenderedEmail(
        subject=subject,
        text=_render_text(blocks, footer),
        html=_render_html(blocks, footer, subject=subject, lang=_HTML_LANG[locale]),
    )


def _content(
    email: Email, t: _Translator, *, app_url: str, support_email: str
) -> tuple[str, list[Block]]:
    match email:
        case LoginCode(code=code, valid_minutes=minutes):
            return t("login_code.subject"), [
                Paragraph(t("login_code.intro")),
                Code(code),
                Paragraph(t("valid_for", minutes=minutes)),
                Paragraph(t("never_share")),
                Paragraph(t("login_code.ignore")),
            ]
        case DeleteCode(code=code, valid_minutes=minutes):
            return t("delete_code.subject"), [
                Paragraph(t("delete_code.intro")),
                Code(code),
                Paragraph(t("delete_code.warning")),
                Paragraph(t("valid_for", minutes=minutes)),
                Paragraph(t("never_share")),
                Paragraph(t("delete_code.ignore")),
            ]
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
        case AccountDeleted():
            return t("account_deleted.subject"), [
                Paragraph(t("account_deleted.body")),
                Paragraph(t("account_deleted.backups")),
                Paragraph(t("account_deleted.not_you", support_email=support_email)),
            ]
        case AccessLost(habit_names=habit_names):
            return t("access_lost.subject"), [
                Paragraph(t("access_lost.body")),
                Items(habit_names),
            ]
        case HabitDeleted(habit_name=habit_name):
            return t("habit_deleted.subject"), [
                Paragraph(t("habit_deleted.body", habit_name=habit_name)),
            ]
        case EmailChangedOld(new_email=new_email):
            return t("email_changed_old.subject"), [
                Paragraph(t("email_changed_old.body", new_email=new_email)),
                Paragraph(t("email_changed_old.not_you", support_email=support_email)),
            ]
        case EmailChangedNew():
            return t("email_changed_new.subject"), [
                Paragraph(t("email_changed_new.body")),
                Link(t("open_app"), f"{app_url}/"),
                Paragraph(t("email_changed_new.not_you", support_email=support_email)),
            ]
        case SendCapReached(window=window, limit=limit):
            return t("send_cap_reached.subject"), [
                Paragraph(
                    t(
                        "send_cap_reached.body",
                        limit=limit,
                        window=t(f"send_cap_reached.window.{window}"),
                    )
                ),
                Paragraph(t("send_cap_reached.action")),
                Paragraph(t("send_cap_reached.once_an_hour")),
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
