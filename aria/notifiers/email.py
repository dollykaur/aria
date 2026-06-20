# smtplib = Simple Mail Transfer Protocol library — Python's built-in email sender.
# No extra install needed, it ships with Python.
import smtplib
import logging

# email.mime.* = classes that help build a properly structured email message.
# MIMEMultipart = an email that can have multiple parts (subject, body, attachments).
# MIMEText = the actual text body of the email (plain text or HTML).
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from aria.models import Diagnosis, Severity
from aria.notifiers.base import BaseNotifier

logger = logging.getLogger(__name__)


class EmailNotifier(BaseNotifier):
    def __init__(self, config):
        self.smtp_host = config.smtp_host
        self.smtp_port = config.smtp_port
        self.sender = config.email_sender
        self.password = config.email_password
        self.recipient = config.email_recipient

    def post(self, diagnosis: Diagnosis) -> None:
        is_critical = any(a.severity == Severity.CRITICAL for a in diagnosis.anomalies)
        severity_label = "CRITICAL" if is_critical else "WARNING"

        subject = f"[ARIA {severity_label}] {diagnosis.anomalies[0].rule_name}"
        body = self._build_body(diagnosis)

        # MIMEMultipart("alternative") means the email has both plain text and HTML versions.
        # Email clients pick whichever they support.
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.sender
        msg["To"] = self.recipient

        # attach() adds the body text to the message.
        # "html" tells the email client to render it as HTML, not raw text.
        msg.attach(MIMEText(body, "html"))

        try:
            # smtplib.SMTP_SSL opens a secure TLS connection to the mail server.
            # Common SMTP hosts: smtp.gmail.com (port 465), smtp.office365.com (port 587)
            with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port) as server:
                server.login(self.sender, self.password)
                server.sendmail(self.sender, self.recipient, msg.as_string())
            logger.info("Email notification sent to %s", self.recipient)
        except Exception as e:
            logger.error("Failed to send email: %s", e)

    def _build_body(self, diagnosis: Diagnosis) -> str:
        anomaly_rows = "".join(
            f"<tr><td><b>[{a.severity.upper()}]</b></td><td>{a.rule_name}</td><td>{a.value:.4f}</td></tr>"
            for a in diagnosis.anomalies
        )
        recommendations = "".join(
            f"<li>{r}</li>" for r in diagnosis.recommendations
        ) or "<li>Continue monitoring</li>"

        return f"""
        <html><body style="font-family: sans-serif; padding: 20px;">
            <h2 style="color: #c0392b;">&#128680; ARIA Incident Report</h2>

            <h3>Anomalies Detected</h3>
            <table border="1" cellpadding="6" cellspacing="0">
                <tr><th>Severity</th><th>Rule</th><th>Value</th></tr>
                {anomaly_rows}
            </table>

            <h3>Root Cause</h3>
            <p>{diagnosis.root_cause}</p>

            <h3>Recommendations</h3>
            <ul>{recommendations}</ul>

            <h3>Action Taken</h3>
            <p><code>{diagnosis.action_taken.action_type}</code> — {diagnosis.action_taken.detail}</p>

            <hr/>
            <small>Investigation completed in {diagnosis.investigation_duration_seconds}s</small>
        </body></html>
        """
