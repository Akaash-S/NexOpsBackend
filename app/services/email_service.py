"""
Email Service — Transactional Email Dispatcher for NexOps
Dispatches OTP verification codes via Resend API (preferred) or SMTP (TLS/SSL fallback).
"""

import smtplib
import asyncio
import logging
import httpx
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from app.core.config import settings

logger = logging.getLogger("nexops.email")


async def _send_resend_async(to_email: str, subject: str, html_content: str, text_content: str) -> bool:
    """Send transactional email using Resend REST API."""
    url = "https://api.resend.com/emails"
    headers = {
        "Authorization": f"Bearer {settings.RESEND_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "from": settings.RESEND_FROM_EMAIL,
        "to": [to_email],
        "subject": subject,
        "html": html_content,
        "text": text_content,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(url, headers=headers, json=payload)
            if res.status_code in (200, 201):
                logger.info(f"Successfully sent OTP email to {to_email} via Resend API")
                return True
            else:
                logger.error(f"Resend API error (HTTP {res.status_code}): {res.text}")
                return False
    except Exception as e:
        logger.error(f"Failed to send email to {to_email} via Resend API: {e}", exc_info=True)
        return False


def _send_smtp_sync(to_email: str, subject: str, html_content: str, text_content: str) -> bool:
    """Synchronous SMTP email delivery function executed in a worker thread."""
    if not settings.SMTP_HOST or not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        logger.warning(
            f"SMTP configuration missing (SMTP_HOST/SMTP_USER). Cannot dispatch email to {to_email}."
        )
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.SMTP_FROM_EMAIL
        msg["To"] = to_email

        msg.attach(MIMEText(text_content, "plain"))
        msg.attach(MIMEText(html_content, "html"))

        port = settings.SMTP_PORT
        if port == 465:
            with smtplib.SMTP_SSL(settings.SMTP_HOST, port, timeout=10) as server:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.sendmail(settings.SMTP_FROM_EMAIL, [to_email], msg.as_string())
        else:
            with smtplib.SMTP(settings.SMTP_HOST, port, timeout=10) as server:
                if settings.SMTP_TLS:
                    server.starttls()
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.sendmail(settings.SMTP_FROM_EMAIL, [to_email], msg.as_string())

        logger.info(f"Successfully sent OTP email to {to_email} via SMTP ({settings.SMTP_HOST}:{port})")
        return True
    except Exception as e:
        logger.error(f"Failed to send email to {to_email} via SMTP: {e}", exc_info=True)
        return False


async def send_otp_email(to_email: str, otp_code: str) -> bool:
    """
    Asynchronously dispatch a 6-digit OTP verification code to the target email address.
    Uses Resend API if RESEND_API_KEY is configured, falling back to SMTP.
    """
    subject = f"{otp_code} is your NexOps verification code"

    text_content = (
        f"Your NexOps 6-digit verification code is: {otp_code}\n\n"
        f"This code will expire in 10 minutes.\n"
        f"If you did not request this code, please ignore this email."
    )

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <title>NexOps Verification Code</title>
    </head>
    <body style="margin: 0; padding: 0; background-color: #090d16; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;">
      <table width="100%" border="0" cellspacing="0" cellpadding="0" style="background-color: #090d16; padding: 40px 20px;">
        <tr>
          <td align="center">
            <table width="100%" max-width="480" border="0" cellspacing="0" cellpadding="0" style="max-width: 480px; background-color: #111827; border: 1px solid #1f2937; border-radius: 12px; padding: 32px; text-align: center; color: #f3f4f6;">
              <tr>
                <td align="center" style="padding-bottom: 16px;">
                  <h1 style="margin: 0; color: #3b82f6; font-size: 24px; font-weight: 700; tracking-tight: -0.025em;">NexOps</h1>
                </td>
              </tr>
              <tr>
                <td style="padding-bottom: 24px; color: #9ca3af; font-size: 14px; line-height: 1.5;">
                  Use the 6-digit verification code below to complete your sign-in to NexOps.
                </td>
              </tr>
              <tr>
                <td align="center" style="padding: 16px 0 24px 0;">
                  <div style="background-color: #1f2937; border: 1px solid #374151; border-radius: 8px; padding: 18px 24px; display: inline-block;">
                    <span style="font-family: 'Courier New', Courier, monospace; font-size: 36px; font-weight: 700; letter-spacing: 8px; color: #60a5fa;">{otp_code}</span>
                  </div>
                </td>
              </tr>
              <tr>
                <td style="color: #6b7280; font-size: 12px; line-height: 1.5;">
                  This code expires in <strong>10 minutes</strong>.<br>
                  If you did not request this verification code, no further action is required.
                </td>
              </tr>
            </table>
          </td>
        </tr>
      </table>
    </body>
    </html>
    """

    if settings.RESEND_API_KEY:
        return await _send_resend_async(to_email, subject, html_content, text_content)

    if settings.SMTP_HOST and settings.SMTP_USER and settings.SMTP_PASSWORD:
        return await asyncio.to_thread(_send_smtp_sync, to_email, subject, html_content, text_content)

    logger.warning(
        f"Neither RESEND_API_KEY nor SMTP credentials configured. Cannot dispatch email to {to_email}. "
        f"Set RESEND_API_KEY in backend/.env to enable live email delivery."
    )
    return False
