"""Idioma dos emails: `users.locale`, senão o `Accept-Language` do request, senão `en`."""

import math
from enum import StrEnum


class Locale(StrEnum):
    PT = "pt"
    EN = "en"


DEFAULT_LOCALE = Locale.EN

# O header pode ter qualquer tamanho que o servidor aceite; acima disso as preferências não
# mudam nada na prática e só custariam CPU
_MAX_ACCEPT_LANGUAGE_ITEMS = 32


def pick_locale(user_locale: str | None = None, accept_language: str | None = None) -> Locale:
    """Escolhe o idioma do email.

    `user_locale` é o `users.locale` (ex.: `pt`, `pt-BR`, `en-US`) e vence quando é um idioma
    suportado. Sem ele (primeiro acesso, por exemplo), vale o primeiro idioma suportado do
    `Accept-Language`, na ordem dos pesos `q`. Nada reconhecido: `en`.
    """
    if user_locale:
        found = _match(user_locale)
        if found is not None:
            return found
    if accept_language:
        for tag in _ranked_tags(accept_language):
            found = _match(tag)
            if found is not None:
                return found
    return DEFAULT_LOCALE


def _match(tag: str) -> Locale | None:
    # Só o idioma principal: pt-BR, pt_PT e PT viram pt
    primary = tag.strip().replace("_", "-").split("-", 1)[0].lower()
    try:
        return Locale(primary)
    except ValueError:
        return None


def _ranked_tags(header: str) -> list[str]:
    """Tags do Accept-Language do maior para o menor `q`; empate fica na ordem do header."""
    ranked: list[tuple[float, int, str]] = []
    for index, item in enumerate(header.split(",")[:_MAX_ACCEPT_LANGUAGE_ITEMS]):
        tag, _, params = item.partition(";")
        weight = 1.0
        for param in params.split(";"):
            name, _, value = param.partition("=")
            if name.strip().lower() == "q":
                try:
                    weight = float(value)
                except ValueError:
                    weight = 0.0
        # q=0 é "não aceito"; nan e inf são lixo
        if math.isfinite(weight) and weight > 0:
            ranked.append((-weight, index, tag.strip()))
    return [tag for _, _, tag in sorted(ranked)]
