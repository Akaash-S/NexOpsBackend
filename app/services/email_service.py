"""
Email Service — Transactional Email Dispatcher for NexOps
Dispatches Amazon/AWS-style light-textured transactional emails (Auth, Alerts, Deployments, Team Invites) via Resend API or SMTP.
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


def _build_amazon_style_html(
    title: str,
    headline: str,
    body_html: str,
    cta_text: Optional[str] = None,
    cta_url: Optional[str] = None,
    accent_color: str = "#2563eb",
    header_bg: str = "#0f172a"
) -> str:
    """
    Builds an Amazon / AWS / Enterprise-class light-textured HTML email layout.
    Ensures maximum cross-client compatibility (Gmail, Outlook, Apple Mail, Mobile).
    """
    cta_button_html = ""
    if cta_text and cta_url:
        cta_button_html = f"""
        <table border="0" cellspacing="0" cellpadding="0" style="margin: 28px 0 12px 0;">
          <tr>
            <td align="center" bgcolor="{accent_color}" style="border-radius: 6px;">
              <a href="{cta_url}" target="_blank" style="font-size: 15px; font-weight: 600; color: #ffffff; text-decoration: none; padding: 12px 28px; border-radius: 6px; border: 1px solid {accent_color}; display: inline-block;">
                {cta_text}
              </a>
            </td>
          </tr>
        </table>
        """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
</head>
<body style="margin: 0; padding: 0; background-color: #f8fafc; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #1e293b; -webkit-font-smoothing: antialiased;">
  <table width="100%" border="0" cellspacing="0" cellpadding="0" style="background-color: #f8fafc; padding: 40px 16px;">
    <tr>
      <td align="center">
        <!-- Main Card Container -->
        <table width="100%" border="0" cellspacing="0" cellpadding="0" style="max-width: 560px; background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);">
          
          <!-- Top Header Bar -->
          <tr>
            <td style="background-color: {header_bg}; padding: 20px 32px; border-bottom: 3px solid {accent_color};">
              <table width="100%" border="0" cellspacing="0" cellpadding="0">
                <tr>
                  <td>
                    <span style="font-size: 22px; font-weight: 800; color: #ffffff; letter-spacing: -0.025em; font-family: sans-serif;">NexOps</span>
                    <span style="font-size: 12px; font-weight: 600; color: #94a3b8; margin-left: 8px; text-transform: uppercase; letter-spacing: 0.05em;">Enterprise Cloud</span>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Main Content Area -->
          <tr>
            <td style="padding: 32px 36px; background-color: #ffffff;">
              <h2 style="margin: 0 0 16px 0; font-size: 20px; font-weight: 700; color: #0f172a; line-height: 1.3;">
                {headline}
              </h2>
              
              <div style="font-size: 15px; line-height: 1.6; color: #334155;">
                {body_html}
              </div>

              {cta_button_html}

            </td>
          </tr>

          <!-- Footer Section -->
          <tr>
            <td style="padding: 24px 36px; background-color: #f1f5f9; border-top: 1px solid #e2e8f0; font-size: 12px; line-height: 1.5; color: #64748b;">
              <p style="margin: 0 0 8px 0; font-weight: 600; color: #475569;">
                NexOps Automated Notification Engine
              </p>
              <p style="margin: 0 0 12px 0;">
                This operational message was sent from an automated system. Please do not reply directly to this email.
              </p>
              <p style="margin: 0; color: #94a3b8; font-size: 11px;">
                &copy; 2026 NexOps Inc. &bull; asolvitra.tech &bull; All rights reserved.
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


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
    """1. Auth Channel: Dispatches Amazon-style 6-digit OTP verification code."""
    subject = f"{otp_code} is your NexOps verification code"
    text_content = f"Your NexOps verification code is: {otp_code} (expires in 10m)."

    body_html = f"""
    <p style="margin: 0 0 16px 0;">Use the 6-digit verification code below to sign in to your NexOps account.</p>
    
    <div style="background-color: #f1f5f9; border: 1px solid #cbd5e1; border-radius: 6px; padding: 20px; text-align: center; margin: 24px 0;">
      <span style="font-family: 'Courier New', Courier, monospace; font-size: 36px; font-weight: 800; letter-spacing: 8px; color: #0f172a;">{otp_code}</span>
    </div>

    <p style="margin: 16px 0 0 0; font-size: 13px; color: #64748b;">
      This code will expire in <strong>10 minutes</strong>. If you did not request this verification code, please ignore this email.
    </p>
    """

    html_content = _build_amazon_style_html(
        title="NexOps Verification Code",
        headline="Verify Your Email Address",
        body_html=body_html,
        accent_color="#2563eb",
        header_bg="#0f172a"
    )

    from_sender = settings.auth_sender
    return await send_email(to_email, subject, html_content, text_content, from_email=from_sender)


async def send_incident_alert_email(to_email: str, incident_title: str, root_cause_summary: str, severity: str = "P1") -> bool:
    """2. Alerts Channel: Dispatches Amazon/AWS-style Critical Incident Alert."""
    subject = f"[{severity} Alert] {incident_title}"
    text_content = f"Incident Alert: {incident_title}\nSeverity: {severity}\nRoot Cause: {root_cause_summary}"

    body_html = f"""
    <div style="background-color: #fef2f2; border-left: 4px solid #ef4444; border-radius: 4px; padding: 14px 18px; margin-bottom: 20px;">
      <span style="font-size: 12px; font-weight: 800; color: #dc2626; text-transform: uppercase; tracking-wider;">{severity} CRITICAL INCIDENT ALERT</span>
      <h3 style="margin: 6px 0 0 0; font-size: 17px; color: #991b1b;">{incident_title}</h3>
    </div>

    <p style="margin: 0 0 12px 0;">NexOps automated observability detected a operational alert requiring immediate attention:</p>
    
    <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 16px; margin-bottom: 16px;">
      <strong style="color: #0f172a; font-size: 13px; text-transform: uppercase;">Candidate Cause Diagnosis:</strong>
      <p style="margin: 6px 0 0 0; color: #334155; font-size: 14px;">{root_cause_summary}</p>
    </div>
    """

    html_content = _build_amazon_style_html(
        title=f"[{severity} Alert] {incident_title}",
        headline=f"Operational Alert Triggered ({severity})",
        body_html=body_html,
        cta_text="View Incident Details",
        cta_url=f"{settings.FRONTEND_URL}/incidents",
        accent_color="#dc2626",
        header_bg="#0f172a"
    )

    from_sender = settings.alerts_sender
    return await send_email(to_email, subject, html_content, text_content, from_email=from_sender)


async def send_deployment_alert_email(to_email: str, repo_name: str, commit_sha: str, status_msg: str) -> bool:
    """3. Deployments Channel: Dispatches Amazon/AWS-style CI/CD Build & Deployment Status."""
    subject = f"[Deploy Notification] {repo_name} ({commit_sha[:7]})"
    text_content = f"Deployment notification for {repo_name} ({commit_sha}): {status_msg}"

    body_html = f"""
    <p style="margin: 0 0 16px 0;">A deployment event occurred on repository <strong>{repo_name}</strong>.</p>
    
    <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 16px; margin-bottom: 16px;">
      <table border="0" cellspacing="0" cellpadding="4" style="width: 100%; font-size: 14px;">
        <tr>
          <td style="color: #64748b; width: 110px;">Repository:</td>
          <td style="color: #0f172a; font-weight: 600;">{repo_name}</td>
        </tr>
        <tr>
          <td style="color: #64748b;">Commit SHA:</td>
          <td style="color: #2563eb; font-family: monospace;">{commit_sha[:7]}</td>
        </tr>
        <tr>
          <td style="color: #64748b;">Status:</td>
          <td style="color: #059669; font-weight: 600;">{status_msg}</td>
        </tr>
      </table>
    </div>
    """

    html_content = _build_amazon_style_html(
        title=f"Deployment Notification: {repo_name}",
        headline=f"Deployment Event — {repo_name}",
        body_html=body_html,
        cta_text="View Repository Health",
        cta_url=f"{settings.FRONTEND_URL}/repositories",
        accent_color="#2563eb",
        header_bg="#0f172a"
    )

    from_sender = settings.deployments_sender
    return await send_email(to_email, subject, html_content, text_content, from_email=from_sender)


async def send_workspace_invite_email(to_email: str, workspace_name: str, invite_url: str) -> bool:
    """4. Team Channel: Dispatches Amazon/AWS-style Team Workspace Invitation."""
    subject = f"You've been invited to join {workspace_name} on NexOps"
    text_content = f"You have been invited to join {workspace_name}. Click to accept: {invite_url}"

    body_html = f"""
    <p style="margin: 0 0 16px 0;">You have been invited to join and collaborate on the <strong>{workspace_name}</strong> workspace on NexOps.</p>
    <p style="margin: 0 0 16px 0; color: #475569;">Click the button below to accept your invitation and access the team workspace dashboard:</p>
    """

    html_content = _build_amazon_style_html(
        title=f"Join {workspace_name} on NexOps",
        headline=f"Invitation to Join {workspace_name}",
        body_html=body_html,
        cta_text="Accept Invitation",
        cta_url=invite_url,
        accent_color="#2563eb",
        header_bg="#0f172a"
    )

    from_sender = settings.team_sender
    return await send_email(to_email, subject, html_content, text_content, from_email=from_sender)
