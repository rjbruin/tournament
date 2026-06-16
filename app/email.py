"""
Email sending helper. Uses the local SMTP server (localhost:25 — Postfix,
sendmail, etc.). All functions are best-effort: they swallow errors so a
missing or misconfigured mail server never breaks the user-facing flow.
"""

import smtplib
from email.message import EmailMessage


_FROM = "wc2026@localhost"


def _send(to: str, subject: str, body: str) -> bool:
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = _FROM
        msg["To"] = to
        msg.set_content(body)
        with smtplib.SMTP("localhost", 25, timeout=5) as s:
            s.send_message(msg)
        return True
    except Exception:
        return False


def send_verification_email(to: str, verify_url: str) -> bool:
    return _send(
        to,
        "[WC 2026] Verify your email address",
        f"Welcome to WC 2026 Simulator!\n\n"
        f"Click the link below to verify your email address and activate your account:\n\n"
        f"  {verify_url}\n\n"
        f"This link expires in 24 hours. If you did not register, ignore this email.",
    )


def send_magic_link_email(to: str, login_url: str) -> bool:
    return _send(
        to,
        "[WC 2026] Your sign-in link",
        f"Here is your one-time sign-in link for WC 2026 Simulator:\n\n"
        f"  {login_url}\n\n"
        f"This link expires in 1 hour and can only be used once. "
        f"If you did not request this, you can safely ignore this email.",
    )


def send_registration_notification(admin_email: str, username: str, user_email: str, invite_label: str | None) -> bool:
    via = f"invite '{invite_label}'" if invite_label else "open registration"
    return _send(
        admin_email,
        f"[WC 2026] New registration: {username}",
        f"A new account has been created via {via}.\n\n"
        f"  Username: {username}\n"
        f"  Email: {user_email}\n\n"
        f"The account is active (approved via invite link).",
    )
