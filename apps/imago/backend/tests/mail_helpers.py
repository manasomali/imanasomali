"""Backend de email em memória dos testes (fixture `outbox` no conftest, já ligada ao `app`).

- `Outbox.messages`: tudo o que o app mandou, na ordem;
- `Outbox.to(endereço)`: só as mensagens para esse endereço.
"""

from email.message import EmailMessage


class Outbox:
    def __init__(self) -> None:
        self.messages: list[EmailMessage] = []

    def send(self, message: EmailMessage) -> None:
        self.messages.append(message)

    def to(self, address: str) -> list[EmailMessage]:
        return [message for message in self.messages if message["To"] == address]
