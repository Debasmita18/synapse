from email.headerregistry import Address
from email.message import EmailMessage

import aiosmtplib
import structlog

from app.config import get_settings

logger = structlog.get_logger()
settings = get_settings()

_OTP_TEMPLATE = """\
Hi{greeting},

Your SYNAPSE one-time login code is:

  {otp}

This code expires in {minutes} minutes.
Never share it with anyone — we will never ask for it.

— The SYNAPSE Team
noreply@synapse.ai
"""


def _build_from_header(address: str) -> str:
    """Returns a properly formatted 'Display Name <addr>' From header."""
    return f"SYNAPSE <{address}>"


async def send_otp_email(email: str, otp: str, name: str | None = None) -> bool:
    if settings.otp_mode == "dev":
        logger.info("DEV MODE — email suppressed", email=email, otp=otp)
        return True

    if not settings.smtp_user:
        logger.warning("SMTP not configured — skipping email delivery")
        return False

    greeting = f" {name.split()[0]}" if name else ""
    body = _OTP_TEMPLATE.format(
        greeting=greeting,
        otp=otp,
        minutes=settings.otp_expire_seconds // 60,
    )

    msg = EmailMessage()
    msg["From"] = _build_from_header(settings.smtp_from)   # SYNAPSE <noreply@synapse.ai>
    msg["To"] = email
    msg["Reply-To"] = settings.smtp_from                   # replies go to noreply@synapse.ai
    msg["Subject"] = "Your SYNAPSE login code"
    msg.set_content(body)

    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user,       # authenticates as shubhamsensgc@gmail.com
            password=settings.smtp_password,
            start_tls=True,
        )
        logger.info("OTP email sent", from_addr=settings.smtp_from, to=email)
        return True
    except Exception as exc:
        logger.error("Email delivery failed", email=email, error=str(exc))
        return False
