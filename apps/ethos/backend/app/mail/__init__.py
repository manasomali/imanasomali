"""Emails do ethos: catálogo, textos em pt e en, idioma e entrega pelo imago.

- `catalog`: um tipo por email (`Invite`, `Alert`, `AccessLost`, `HabitDeleted`);
- `language`: `Locale` e `pick_locale(user_locale)`;
- `templates`: `render(...)` e os textos;
- `sender`: `Mailer` (entrega pelo imago, `app/imago_client.py`), `MailerDep` e `schedule_email`.
"""
