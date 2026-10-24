"""Emails do ethos: catálogo, textos em pt e en, idioma, envio por SMTP ou console.

- `catalog`: um tipo por email (`LoginCode`, `Invite`, `Alert` etc.);
- `language`: `pick_locale(user_locale, accept_language)`;
- `templates`: `render(...)` e os textos;
- `backends`: `SmtpBackend` (STARTTLS) e `ConsoleBackend` (só dev);
- `sender`: `Mailer`, `MailerDep`, `schedule_email` e `build_backend`.
"""
