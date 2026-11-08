"""Idioma dos emails: o do destinatário (`app_users.locale` ou o do `lookup`), senão `en`."""

from enum import StrEnum


class Locale(StrEnum):
    PT = "pt"
    EN = "en"


DEFAULT_LOCALE = Locale.EN


def pick_locale(user_locale: str | None = None) -> Locale:
    """Escolhe o idioma do email.

    `user_locale` é o idioma da pessoa (ex.: `pt`, `pt-BR`, `en-US`). Só o idioma principal conta
    (pt-BR, pt_PT e PT viram pt); sem ele ou fora dos suportados: `en`.
    """
    if not user_locale:
        return DEFAULT_LOCALE
    primary = user_locale.strip().replace("_", "-").split("-", 1)[0].lower()
    try:
        return Locale(primary)
    except ValueError:
        return DEFAULT_LOCALE
