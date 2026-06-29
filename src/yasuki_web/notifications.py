import logging
import os
import smtplib
import ssl
from email.message import EmailMessage

logger = logging.getLogger(__name__)

# Port 465 speaks TLS from the connect; any other (e.g. 587) upgrades with STARTTLS.
_IMPLICIT_TLS_PORT = 465


def _smtp_config() -> dict | None:
    """The SMTP settings, or None if email is not configured (host + recipient are the minimum)."""
    host = os.environ.get("YASUKI_SMTP_HOST")
    recipient = os.environ.get("YASUKI_ADMIN_EMAIL")
    if not (host and recipient):
        return None
    user = os.environ.get("YASUKI_SMTP_USER")
    return {
        "host": host,
        "port": int(os.environ.get("YASUKI_SMTP_PORT", "587")),
        "user": user,
        "password": os.environ.get("YASUKI_SMTP_PASSWORD"),
        "sender": os.environ.get("YASUKI_SMTP_FROM") or user or recipient,
        "recipient": recipient,
    }


def notify_new_signup(display_name: str, approve_url: str | None = None) -> None:
    """Email the admin that a new account is awaiting approval. Best-effort and silent if unset.

    A no-op when SMTP is not configured. Catches and logs every send failure rather than raising:
    notifying the admin is incidental, and must never break or block a user's sign-in.

    Parameters
    ----------
    display_name : str
        The new account's display name, shown in the email.
    approve_url : str, optional
        A direct link to the admin dashboard, included in the body when given. Default None.
    """
    config = _smtp_config()
    if config is None:
        return
    body = f"A new account, '{display_name}', signed up and is awaiting approval.\n\n"
    body += (
        f"Approve it here: {approve_url}" if approve_url else "Approve it under Settings → Admin."
    )
    message = EmailMessage()
    message["Subject"] = "Game on, Yasuki! — new account awaiting approval"
    message["From"] = config["sender"]
    message["To"] = config["recipient"]
    message.set_content(body)
    try:
        _send(config, message)
    except Exception:
        logger.exception("Failed to send the new-signup notification")


def _send(config: dict, message: EmailMessage) -> None:
    context = ssl.create_default_context()
    if config["port"] == _IMPLICIT_TLS_PORT:
        with smtplib.SMTP_SSL(config["host"], config["port"], timeout=10, context=context) as smtp:
            _authenticate_and_send(smtp, config, message)
    else:
        with smtplib.SMTP(config["host"], config["port"], timeout=10) as smtp:
            smtp.starttls(context=context)
            _authenticate_and_send(smtp, config, message)


def _authenticate_and_send(smtp: smtplib.SMTP, config: dict, message: EmailMessage) -> None:
    if config["user"] and config["password"]:
        smtp.login(config["user"], config["password"])
    smtp.send_message(message)
