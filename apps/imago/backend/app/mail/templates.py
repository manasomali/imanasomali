"""Textos dos emails do imago em pt e en, montados em texto puro e em HTML simples.

Cada email vira uma lista de blocos (parágrafo, código, link) e os dois formatos saem dos mesmos
blocos. Os textos daqui não têm HTML: o renderizador escapa tudo (`html.escape`), tanto o texto
fixo quanto os dados de quem chama (o email novo da troca de email). Os assuntos são fixos por tipo
e idioma, sem nenhum dado: nunca o código (aparece em notificação de tela bloqueada) nem email.

Links saem sempre do `APP_URL` (a tela de conta, `APP_URL/`).
"""

import html
from dataclasses import dataclass

from app.mail.catalog import (
    AccountDeleted,
    DeleteCode,
    Email,
    EmailChangedNew,
    EmailChangedOld,
    LoginCode,
    SendCapReached,
)
from app.mail.language import Locale

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


type Block = Paragraph | Code | Link


@dataclass(frozen=True, slots=True)
class RenderedEmail:
    subject: str
    text: str
    html: str


_PT: dict[str, str] = {
    "footer": (
        "Email automático da sua conta do manasomali.com ({app_url}). Dúvidas: {support_email}"
    ),
    "never_share": "Nunca compartilhe este código com ninguém.",
    "valid_for": "O código vale por {minutes} minutos e só pode ser usado uma vez.",
    "open_account": "Abrir a sua conta",
    "login_code.subject": "Seu código de acesso ao manasomali.com",
    "login_code.intro": "Use este código para entrar na sua conta do manasomali.com:",
    "login_code.ignore": "Se não foi você que pediu, ignore este email.",
    "delete_code.subject": "Código para excluir sua conta do manasomali.com",
    "delete_code.intro": (
        "Use este código para confirmar a exclusão da sua conta do manasomali.com:"
    ),
    "delete_code.warning": (
        "A exclusão apaga a sua conta e os seus dados em todas as aplicações do manasomali.com, "
        "e não pode ser desfeita."
    ),
    "delete_code.ignore": (
        "Se não foi você que pediu, ignore este email: a sua conta continua como está."
    ),
    "account_deleted.subject": "Sua conta do manasomali.com foi excluída",
    "account_deleted.body": (
        "A sua conta do manasomali.com foi excluída, junto com os seus dados em todas as "
        "aplicações."
    ),
    "account_deleted.backups": "Os dados somem também das cópias de segurança em até 8 dias.",
    "account_deleted.not_you": "Se não foi você que pediu, escreva para {support_email}.",
    "email_changed_old.subject": "O email da sua conta do manasomali.com foi trocado",
    "email_changed_old.body": (
        "A pedido feito ao suporte, o email da sua conta do manasomali.com foi trocado para "
        "{new_email}. Este endereço não entra mais na conta."
    ),
    "email_changed_old.not_you": (
        "Se não foi você que pediu, responda a este email ou escreva para {support_email}."
    ),
    "email_changed_new.subject": "Este é o novo email da sua conta do manasomali.com",
    "email_changed_new.body": (
        "A pedido feito ao suporte, este endereço passou a ser o email da sua conta do "
        "manasomali.com. Para entrar, peça um código com ele."
    ),
    "email_changed_new.not_you": "Se não reconhece este pedido, escreva para {support_email}.",
    "send_cap_reached.subject": "manasomali.com: teto de envio de email atingido",
    "send_cap_reached.body": (
        "O teto de envio de email ({limit} {window}) foi atingido. Pedidos de código recebem "
        "429 até a janela andar, e as notificações das aplicações já pararam antes, na reserva "
        "para códigos."
    ),
    "send_cap_reached.window.hour": "por hora",
    "send_cap_reached.window.day": "em 24 horas",
    "send_cap_reached.action": (
        "Se for abuso, confira os logs do imago e considere um captcha. Se for uso normal, "
        "revise MAX_EMAILS_PER_DAY, MAX_EMAILS_PER_HOUR e a cota do provedor."
    ),
    "send_cap_reached.once_an_hour": "Este aviso sai no máximo uma vez por hora.",
}

_EN: dict[str, str] = {
    "footer": (
        "Automatic email from your manasomali.com account ({app_url}). Questions: {support_email}"
    ),
    "never_share": "Never share this code with anyone.",
    "valid_for": "The code is valid for {minutes} minutes and can only be used once.",
    "open_account": "Open your account",
    "login_code.subject": "Your manasomali.com sign-in code",
    "login_code.intro": "Use this code to sign in to your manasomali.com account:",
    "login_code.ignore": "If you didn't request it, ignore this email.",
    "delete_code.subject": "Code to delete your manasomali.com account",
    "delete_code.intro": "Use this code to confirm the deletion of your manasomali.com account:",
    "delete_code.warning": (
        "Deleting removes your account and your data in every manasomali.com app, and it "
        "cannot be undone."
    ),
    "delete_code.ignore": "If you didn't request it, ignore this email: your account stays as is.",
    "account_deleted.subject": "Your manasomali.com account was deleted",
    "account_deleted.body": (
        "Your manasomali.com account was deleted, along with your data in every app."
    ),
    "account_deleted.backups": "The data is also gone from backups within 8 days.",
    "account_deleted.not_you": "If you didn't ask for this, write to {support_email}.",
    "email_changed_old.subject": "Your manasomali.com account email was changed",
    "email_changed_old.body": (
        "At a request made to support, the email of your manasomali.com account was changed to "
        "{new_email}. This address no longer signs in to the account."
    ),
    "email_changed_old.not_you": (
        "If you didn't ask for this, reply to this email or write to {support_email}."
    ),
    "email_changed_new.subject": "This is now your manasomali.com account email",
    "email_changed_new.body": (
        "At a request made to support, this address is now the email of your manasomali.com "
        "account. To sign in, request a code with it."
    ),
    "email_changed_new.not_you": "If you don't recognize this request, write to {support_email}.",
    "send_cap_reached.subject": "manasomali.com: email sending cap reached",
    "send_cap_reached.body": (
        "The email sending cap ({limit} {window}) was reached. Code requests get a 429 until "
        "the window moves on, and the apps' notifications had already stopped at the reserve "
        "for codes."
    ),
    "send_cap_reached.window.hour": "per hour",
    "send_cap_reached.window.day": "in 24 hours",
    "send_cap_reached.action": (
        "If it is abuse, check the imago logs and consider a captcha. If it is normal use, "
        "review MAX_EMAILS_PER_DAY, MAX_EMAILS_PER_HOUR and the provider's quota."
    ),
    "send_cap_reached.once_an_hour": "This notice goes out at most once an hour.",
}

TEXTS: dict[Locale, dict[str, str]] = {Locale.PT: _PT, Locale.EN: _EN}
_HTML_LANG = {Locale.PT: "pt-BR", Locale.EN: "en"}


class _Translator:
    def __init__(self, locale: Locale) -> None:
        self._texts = TEXTS[locale]

    def __call__(self, key: str, **values: object) -> str:
        # Só o texto fixo é molde: os valores entram como dados, nunca como formato
        return self._texts[key].format(**values)


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
        case AccountDeleted():
            return t("account_deleted.subject"), [
                Paragraph(t("account_deleted.body")),
                Paragraph(t("account_deleted.backups")),
                Paragraph(t("account_deleted.not_you", support_email=support_email)),
            ]
        case EmailChangedOld(new_email=new_email):
            return t("email_changed_old.subject"), [
                Paragraph(t("email_changed_old.body", new_email=new_email)),
                Paragraph(t("email_changed_old.not_you", support_email=support_email)),
            ]
        case EmailChangedNew():
            return t("email_changed_new.subject"), [
                Paragraph(t("email_changed_new.body")),
                Link(t("open_account"), f"{app_url}/"),
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
