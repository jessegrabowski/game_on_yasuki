from yasuki_web import notifications

_SMTP_ENV = {
    "YASUKI_SMTP_HOST": "smtp.example.com",
    "YASUKI_ADMIN_EMAIL": "me@example.com",
    "YASUKI_SMTP_FROM": "bot@example.com",
}
_ALL_VARS = (
    "YASUKI_SMTP_HOST",
    "YASUKI_ADMIN_EMAIL",
    "YASUKI_SMTP_PORT",
    "YASUKI_SMTP_USER",
    "YASUKI_SMTP_PASSWORD",
    "YASUKI_SMTP_FROM",
)


def _set_env(monkeypatch, **env):
    for var in _ALL_VARS:
        monkeypatch.delenv(var, raising=False)
    for var, value in env.items():
        monkeypatch.setenv(var, value)


def test_no_op_when_email_is_not_configured(monkeypatch):
    _set_env(monkeypatch)  # no host, no recipient
    attempts = []
    monkeypatch.setattr(notifications, "_send", lambda *args: attempts.append(args))
    notifications.notify_new_signup("Ada")
    assert attempts == []  # nothing is sent


def test_sends_a_message_to_the_admin_when_configured(monkeypatch):
    _set_env(monkeypatch, **_SMTP_ENV)
    captured = {}

    def fake_send(config, message):
        captured.update(to=message["To"], subject=message["Subject"], body=message.get_content())

    monkeypatch.setattr(notifications, "_send", fake_send)
    notifications.notify_new_signup("StoicCrane204", "https://play.example/settings#admin")

    assert captured["to"] == "me@example.com"
    assert "approval" in captured["subject"].lower()
    assert "StoicCrane204" in captured["body"]
    assert "https://play.example/settings#admin" in captured["body"]  # clickable approve link


def test_a_send_failure_never_propagates(monkeypatch):
    _set_env(monkeypatch, **_SMTP_ENV)

    def boom(config, message):
        raise OSError("smtp unreachable")

    monkeypatch.setattr(notifications, "_send", boom)
    notifications.notify_new_signup("Ada")  # best-effort: must not raise
