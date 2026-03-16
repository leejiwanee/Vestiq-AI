# scanner/email_utils.py
import os
import smtplib
from io import BytesIO
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
import typst
import tempfile
from django.template.loader import render_to_string
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

# ----------------------------
# Email Environment Variables
# ----------------------------
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER", "")
SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))

RECEIVERS = [addr.strip() for addr in EMAIL_RECEIVER.split(",") if addr.strip()]

# ----------------------------
# Font Setup (Korean)
# ----------------------------
FONT_PATH = os.path.join(os.path.dirname(__file__), "fonts", "NanumGothic.ttf")
FONT_DIR = os.path.dirname(FONT_PATH)


# ----------------------------
# Helper Functions
# ----------------------------
def _wrap_text(text, width):
    """
    아주 단순한 폭 기준 줄바꿈 유틸리티
    """
    text = text or ""
    lines = []
    while len(text) > width:
        lines.append(text[:width])
        text = text[width:]
    if text:
        lines.append(text)
    return lines


# ----------------------------
# Typst PDF Builder
# ----------------------------
def _build_typst_pdf_for_item(item, generated_at: datetime):
    """
    Generate PDF using Typst and Django template.
    """
    sym = item.get("symbol", "")
    company = item.get("company", "")
    stats = item.get("stats", {}) or {}
    ai_report = item.get("ai", {}) or {}

    # Context for the template
    context = {
        "symbol": sym,
        "company_name": company,
        "generated_at": generated_at,
        "stats": stats,
        "ai_report": ai_report,
    }

    # Render Typst source code
    typst_source = render_to_string("scanner/report_typst.html", context)

    # Compile to PDF
    # We pass the font directory so Typst can find NanumGothic
    try:
        with tempfile.NamedTemporaryFile(suffix=".typ", mode="w+", delete=True) as tmp:
            tmp.write(typst_source)
            tmp.flush()
            
            pdf_bytes = typst.compile(
                tmp.name, 
                font_paths=[FONT_DIR] if os.path.exists(FONT_DIR) else []
            )
        return pdf_bytes
    except Exception as e:
        print(f"❌ Typst compilation failed for {sym}: {e}")
        # Return empty bytes or handle error appropriately
        return b""


# ----------------------------
# Send Email with PDFs
# ----------------------------
def send_email_with_pdf(subject: str, body: str, report_items, generated_at, to_email=None):
    """
    여러 명 수신자에게 PDF 첨부 메일 발송
    to_email이 있으면 해당 이메일로만 발송. 없으면 기본 RECEIVERS 사용.
    """
    if not SMTP_SERVER:
        raise RuntimeError("SMTP_SERVER 환경변수가 비어 있습니다.")
    if not EMAIL_SENDER or not EMAIL_PASSWORD:
        raise RuntimeError("EMAIL 환경변수가 비어 있습니다.")

    receivers = [to_email] if to_email else RECEIVERS
    if not receivers:
        raise RuntimeError("수신자가 없습니다.")

    msg = MIMEMultipart()
    msg["From"] = EMAIL_SENDER
    msg["To"] = ", ".join(receivers)
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", _charset="utf-8"))

    # 종목별 PDF 첨부
    for item in report_items:
        # Use Typst builder
        pdf_bytes = _build_typst_pdf_for_item(item, generated_at)
        if not pdf_bytes:
            print(f"⚠️ PDF generation failed for {item.get('symbol')}, skipping attachment.")
            continue
        sym = item["symbol"]
        filename = f"{sym}_ai_report_{generated_at:%Y%m%d}.pdf"

        part = MIMEBase("application", "pdf")
        part.set_payload(pdf_bytes)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{filename}"')
        msg.attach(part)

    try:
        import ssl
        # Create unverified SSL context to bypass certificate errors
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls(context=context)
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_SENDER, receivers, msg.as_string())
        print(f"📧 이메일 전송 성공! 수신자: {receivers}")
    except Exception as e:
        print(f"❌ 이메일 전송 실패: {e}")
        raise
