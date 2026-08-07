"""
Email Service — Transactional Email Dispatcher for NexOps
Dispatches categorized emails (Auth, Alerts, Deployments, Team Invites, Billing) via Resend API or SMTP.
"""

import smtplib
import asyncio
import logging
import httpx
from typing import Optional
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from app.core.config import settings

logger = logging.getLogger("nexops.email")


async def _send_resend_async(to_email: str, subject: str, html_content: str, text_content: str, from_email: Optional[str] = None) -> bool:
    """Send transactional email using Resend REST API."""
    url = "https://api.resend.com/emails"
    headers = {
        "Authorization": f"Bearer {settings.RESEND_API_KEY}",
        "Content-Type": "application/json",
    }
    sender = from_email or settings.RESEND_FROM_EMAIL
    payload = {
        "from": sender,
        "to": [to_email],
        "subject": subject,
        "html": html_content,
        "text": text_content,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(url, headers=headers, json=payload)
            if res.status_code in (200, 201):
                logger.info(f"Successfully sent email ({subject[:30]}...) to {to_email} via Resend API (from: {sender})")
                return True
            else:
                logger.error(f"Resend API error (HTTP {res.status_code}): {res.text}")
                return False
    except Exception as e:
        logger.error(f"Failed to send email to {to_email} via Resend API: {e}", exc_info=True)
        return False


def _send_smtp_sync(to_email: str, subject: str, html_content: str, text_content: str, from_email: Optional[str] = None) -> bool:
    """Synchronous SMTP email delivery function executed in a worker thread."""
    if not settings.SMTP_HOST or not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        logger.warning(
            f"SMTP configuration missing (SMTP_HOST/SMTP_USER). Cannot dispatch email to {to_email}."
        )
        return False

    sender = from_email or settings.SMTP_FROM_EMAIL
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = to_email

        msg.attach(MIMEText(text_content, "plain"))
        msg.attach(MIMEText(html_content, "html"))

        port = settings.SMTP_PORT
        if port == 465:
            with smtplib.SMTP_SSL(settings.SMTP_HOST, port, timeout=10) as server:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.sendmail(sender, [to_email], msg.as_string())
        else:
            with smtplib.SMTP(settings.SMTP_HOST, port, timeout=10) as server:
                if settings.SMTP_TLS:
                    server.starttls()
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.sendmail(sender, [to_email], msg.as_string())

        logger.info(f"Successfully sent email to {to_email} via SMTP ({settings.SMTP_HOST}:{port})")
        return True
    except Exception as e:
        logger.error(f"Failed to send email to {to_email} via SMTP: {e}", exc_info=True)
        return False


async def send_email(to_email: str, subject: str, html_content: str, text_content: str, from_email: Optional[str] = None) -> bool:
    """Central email dispatcher with Resend API priority and SMTP fallback."""
    if settings.RESEND_API_KEY:
        return await _send_resend_async(to_email, subject, html_content, text_content, from_email)

    if settings.SMTP_HOST and settings.SMTP_USER and settings.SMTP_PASSWORD:
        return await asyncio.to_thread(_send_smtp_sync, to_email, subject, html_content, text_content, from_email)

    logger.warning(
        f"Neither RESEND_API_KEY nor SMTP credentials configured. Cannot dispatch email to {to_email}."
    )
    return False


async def send_otp_email(to_email: str, otp_code: str) -> bool:
    """1. Auth Channel: Dispatches 6-digit OTP code (from: auth@yourdomain.com)."""
    subject = f"{otp_code} is your NexOps verification code"
    text_content = f"Your NexOps verification code is: {otp_code} (expires in 10m)."
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <body style="background-color: #090d16; font-family: sans-serif; color: #f3f4f6; padding: 40px;">
      <div style="max-width: 480px; margin: 0 auto; background-color: #111827; border: 1px solid #1f2937; border-radius: 12px; padding: 32px; text-align: center;">
        <h1 style="color: #3b82f6;">NexOps</h1>
        <p style="color: #9ca3af;">Use the 6-digit verification code below to complete sign-in.</p>
        <div style="background-color: #1f2937; border-radius: 8px; padding: 16px; margin: 20px 0;">
          <span style="font-family: monospace; font-size: 36px; font-weight: bold; letter-spacing: 8px; color: #60a5fa;">{otp_code}</span>
        </div>
        <p style="color: #6b7280; font-size: 12px;">This code expires in 10 minutes.</p>
      </div>
    </body>
    </html>
    """
    from_sender = getattr(settings, "EMAIL_AUTH_SENDER", settings.RESEND_FROM_EMAIL)
    return await send_email(to_email, subject, html_content, text_content, from_email=from_sender)


async def send_incident_alert_email(to_email: str, incident_title: str, root_cause_summary: str, severity: str = "P1") -> bool:
    """2. Alerts Channel: Dispatches P1 Incident & Root Cause Diagnosis (from: alerts@yourdomain.com)."""
    subject = f"[{severity} Alert] {incident_title}"
    text_content = f"Incident Alert: {incident_title}\nSeverity: {severity}\nRoot Cause: {root_cause_summary}"
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <body style="background-color: #090d16; font-family: sans-serif; color: #f3f4f6; padding: 40px;">
      <div style="max-width: 520px; margin: 0 auto; background-color: #111827; border: 1px solid #dc2626; border-radius: 12px; padding: 32px;">
        <span style="background-color: #7f1d1d; color: #fca5a5; font-size: 12px; font-weight: bold; padding: 4px 8px; border-radius: 4px;">{severity} CRITICAL INCIDENT</span>
        <h2 style="color: #ef4444; margin-top: 12px;">{incident_title}</h2>
        <p style="color: #9ca3af; font-size: 14px;"><strong>AI Diagnosis:</strong> {root_cause_summary}</p>
        <div style="margin-top: 24px; text-align: center;">
          <a href="{settings.FRONTEND_URL}/incidents" style="background-color: #ef4444; color: white; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-weight: bold;">View Incident Details</a>
        </div>
      </div>
    </body>
    </html>
    """
    from_sender = getattr(settings, "EMAIL_ALERTS_SENDER", "NexOps Alerts <alerts@nexops.dev>")
    return await send_email(to_email, subject, html_content, text_content, from_email=from_sender)


async def send_deployment_alert_email(to_email: str, repo_name: str, commit_sha: str, status_msg: str) -> bool:
    """3. Deployments Channel: Dispatches CI/CD Build & Deployment status (from: deployments@yourdomain.com)."""
    subject = f"[Deploy Notification] {repo_name} ({commit_sha[:7]})"
    text_content = f"Deployment notification for {repo_name} ({commit_sha}): {status_msg}"
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <body style="background-color: #090d16; font-family: sans-serif; color: #f3f4f6; padding: 40px;">
      <div style="max-width: 520px; margin: 0 auto; background-color: #111827; border: 1px solid #1f2937; border-radius: 12px; padding: 32px;">
        <h2 style="color: #3b82f6;">Deployment Event: {repo_name}</h2>
        <p style="color: #9ca3af;">Commit <code>{commit_sha[:7]}</code>: {status_msg}</p>
      </div>
    </body>
    </html>
    """
    from_sender = getattr(settings, "EMAIL_DEPLOYMENTS_SENDER", "NexOps Deployments <deployments@nexops.dev>")
    return await send_email(to_email, subject, html_content, text_content, from_email=from_sender)


async def send_workspace_invite_email(to_email: str, workspace_name: str, invite_url: str) -> bool:
    """4. Team Channel: Dispatches Team Invites (from: team@yourdomain.com)."""
    subject = f"You've been invited to join {workspace_name} on NexOps"
    text_content = f"You have been invited to join {workspace_name}. Click to accept: {invite_url}"
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <body style="background-color: #090d16; font-family: sans-serif; color: #f3f4f6; padding: 40px;">
      <div style="max-width: 480px; margin: 0 auto; background-color: #111827; border: 1px solid #1f2937; border-radius: 12px; padding: 32px; text-align: center;">
        <h2 style="color: #3b82f6;">Join {workspace_name}</h2>
        <p style="color: #9ca3af;">You've been invited to collaborate on the {workspace_name} workspace.</p>
        <a href="{invite_url}" style="display: inline-block; margin-top: 16px; background-color: #2563eb; color: white; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-weight: bold;">Accept Invite</a>
      </div>
    </body>
    </html>
    """
    from_sender = getattr(settings, "EMAIL_TEAM_SENDER", "NexOps Team <team@nexops.dev>")
    return await send_email(to_email, subject, html_content, text_content, from_email=from_sender)
