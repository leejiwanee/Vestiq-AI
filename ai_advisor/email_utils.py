
import os
import smtplib
from io import BytesIO
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from django.conf import settings
from datetime import datetime

# ----------------------------
# Font Setup (Korean)
# ----------------------------
# Use the font from the scanner app to avoid duplication
FONT_PATH = os.path.join(settings.BASE_DIR, "scanner", "fonts", "NanumGothic.ttf")
FONT_NAME = "NanumGothic"

try:
    if os.path.exists(FONT_PATH):
        pdfmetrics.registerFont(TTFont(FONT_NAME, FONT_PATH))
    else:
        print(f"[WARN] Korean font not found at {FONT_PATH}. Fallback to Helvetica.")
        FONT_NAME = "Helvetica"
except Exception as e:
    print(f"[WARN] Failed to register Korean font: {e}")
    FONT_NAME = "Helvetica"

def _wrap_text(text, width):
    """Simple text wrapper"""
    text = text or ""
    lines = []
    for paragraph in text.split('\n'):
        while len(paragraph) > width:
            lines.append(paragraph[:width])
            paragraph = paragraph[width:]
        if paragraph:
            lines.append(paragraph)
    return lines

def generate_portfolio_pdf(profile, report_data):
    """
    Generates a PDF for the Investment Portfolio.
    """
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    
    # Margins
    left, right, bottom = 40, width - 40, 60
    y = height - 50
    
    def new_line(delta=14):
        nonlocal y
        y -= delta
        if y < bottom:
            c.showPage()
            y = height - 50
            c.setFont(FONT_NAME, 10)
            c.setFillColor(colors.black)

    # --- Header ---
    c.setFont(FONT_NAME, 18)
    c.setFillColor(colors.HexColor("#1e3a8a")) # Dark Blue
    c.drawString(left, y, "AI Personalized Investment Strategy")
    new_line(25)
    
    c.setFont(FONT_NAME, 14)
    c.setFillColor(colors.black)
    c.drawString(left, y, report_data.get('strategy_name', 'Portfolio Report'))
    new_line(30)
    
    # --- Profile Summary ---
    c.setFont(FONT_NAME, 12)
    c.setFillColor(colors.HexColor("#2563eb")) # Blue
    c.drawString(left, y, "📌 Investment Profile")
    new_line(20)
    
    c.setFont(FONT_NAME, 10)
    c.setFillColor(colors.black)
    c.drawString(left + 10, y, f"Total Investment: ${profile.total_amount:,}")
    new_line(15)
    c.drawString(left + 10, y, f"Monthly Contribution: ${profile.monthly_contribution:,}")
    new_line(15)
    c.drawString(left + 10, y, f"Risk Tolerance: {profile.get_risk_tolerance_display()}")
    new_line(15)
    c.drawString(left + 10, y, f"Goal: {profile.get_investment_goal_display()}")
    new_line(15)
    c.drawString(left + 10, y, f"Target Return: {profile.target_return}% / year")
    new_line(15)
    c.drawString(left + 10, y, f"Duration: {profile.duration_months} months")
    new_line(30)
    
    # --- Asset Allocation ---
    c.setFont(FONT_NAME, 12)
    c.setFillColor(colors.HexColor("#2563eb"))
    c.drawString(left, y, "📊 Asset Allocation")
    new_line(20)
    
    c.setFont(FONT_NAME, 10)
    c.setFillColor(colors.black)
    allocation = report_data.get('allocation', {})
    for asset, weight in allocation.items():
        c.drawString(left + 10, y, f"- {asset}: {weight}%")
        new_line(15)
    new_line(20)
    
    # --- Portfolio Holdings ---
    c.setFont(FONT_NAME, 12)
    c.setFillColor(colors.HexColor("#2563eb"))
    c.drawString(left, y, "💼 Portfolio Holdings")
    new_line(20)
    
    # Table Header
    c.setFont(FONT_NAME, 10)
    c.setFillColor(colors.grey)
    c.drawString(left + 10, y, "Ticker")
    c.drawString(left + 80, y, "Name")
    c.drawString(left + 300, y, "Asset Class")
    c.drawString(left + 450, y, "Weight")
    new_line(15)
    
    c.setStrokeColor(colors.lightgrey)
    c.line(left, y + 10, right, y + 10)
    new_line(5)
    
    c.setFont(FONT_NAME, 10)
    c.setFillColor(colors.black)
    
    holdings = report_data.get('portfolio', [])
    for item in holdings:
        ticker = item.get('ticker', '')
        name = item.get('name', '')
        asset_class = item.get('asset_class', '')
        weight = item.get('weight', 0)
        
        # Truncate long names
        if len(name) > 35: name = name[:32] + "..."
        
        c.drawString(left + 10, y, ticker)
        c.drawString(left + 80, y, name)
        c.drawString(left + 300, y, asset_class)
        c.drawString(left + 450, y, f"{weight}%")
        new_line(15)
        
        # Rationale (small text below)
        rationale = item.get('rationale', '')
        if rationale:
            c.setFont(FONT_NAME, 8)
            c.setFillColor(colors.darkgrey)
            c.drawString(left + 80, y, f"↳ {rationale}")
            new_line(15)
            c.setFont(FONT_NAME, 10)
            c.setFillColor(colors.black)
            
    new_line(20)
    
    # --- Analysis & Rationale ---
    c.setFont(FONT_NAME, 12)
    c.setFillColor(colors.HexColor("#2563eb"))
    c.drawString(left, y, "💡 Strategy Analysis")
    new_line(20)
    
    c.setFont(FONT_NAME, 10)
    c.setFillColor(colors.black)
    analysis = report_data.get('analysis_report', '')
    for line in _wrap_text(analysis, 85):
        c.drawString(left + 10, y, line)
        new_line(14)
        
    # Footer
    c.save()
    return buf.getvalue()

def send_email_with_pdf(to_email, subject, body, pdf_bytes, filename):
    """
    Sends an email with a PDF attachment using smtplib.
    """
    # SMTP Settings
    smtp_server = os.getenv("SMTP_SERVER") or getattr(settings, 'EMAIL_HOST', 'smtp.gmail.com')
    smtp_port = int(os.getenv("SMTP_PORT") or getattr(settings, 'EMAIL_PORT', 587))
    sender_email = os.getenv("EMAIL_SENDER") or getattr(settings, 'EMAIL_HOST_USER', '')
    sender_password = os.getenv("EMAIL_PASSWORD") or getattr(settings, 'EMAIL_HOST_PASSWORD', '')
    
    if not sender_email or not sender_password:
        raise ValueError("Email configuration missing")

    msg = MIMEMultipart()
    msg["From"] = sender_email
    msg["To"] = to_email
    msg["Subject"] = subject
    
    msg.attach(MIMEText(body, "plain", _charset="utf-8"))
    
    # Attach PDF
    part = MIMEBase("application", "pdf")
    part.set_payload(pdf_bytes)
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f'attachment; filename="{filename}"')
    msg.attach(part)
    
    # Send
    with smtplib.SMTP(smtp_server, smtp_port) as server:
        server.starttls()
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, [to_email], msg.as_string())
