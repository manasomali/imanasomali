"""Emails: só o imago fala com o SMTP, pelo próprio imago e pelas aplicações.

- `kinds`: `MailKind` (`code`, `account`, `notification`), como cada email conta no teto;
- `quota`: o teto compartilhado em janelas móveis, a reserva para códigos e o aviso ao suporte;
- `catalog`: os emails do próprio imago (`LoginCode`, `DeleteCode`, `AccountDeleted`...);
- `language`: `pick_locale(user_locale, accept_language)`;
- `templates`: `render(...)` e os textos em pt e en;
- `backends`: `SmtpBackend` (STARTTLS) e `ConsoleBackend` (só dev);
- `sender`: `Mailer`, `MailerDep`, `OutgoingEmail`, `Notification`, `schedule` e `build_backend`.
"""
