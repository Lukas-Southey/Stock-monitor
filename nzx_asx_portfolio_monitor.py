#!/usr/bin/env python3
"""
NZX & ASX Portfolio Monitor - SuperGrok Automated Report
Hourly email + Telegram during trading hours (6am-6pm NZST, Mon-Fri)

This version supports:
- Full data fetching (prices, movers, news, valuation)
- Email via Gmail
- Telegram notifications
- Optional enhancement using xAI Grok API for high-quality analysis sections

SECURITY WARNING:
Never commit real API keys, tokens or passwords to git.
All sensitive values are loaded from environment variables / GitHub Secrets.
"""

import yfinance as yf
import pandas as pd
from datetime import datetime
import pytz
import warnings
import os
import smtplib
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

warnings.filterwarnings("ignore")

# ============================================================
# PORTFOLIO CONFIG (update as needed)
# ============================================================
PORTFOLIO = [
    {"ticker": "PME.AX", "shares": 410,  "buy_price": 165.54, "name": "Pro Medicus Ltd"},
    {"ticker": "TLX.AX", "shares": 1918, "buy_price": 13.31,  "name": "Telix Pharmaceuticals Ltd"},
    {"ticker": "EBO.NZ", "shares": 619,  "buy_price": 19.52,  "name": "EBOS Group Ltd"},
    {"ticker": "TNE.AX", "shares": 400,  "buy_price": 32.33,  "name": "Technology One Ltd"},
    {"ticker": "WTC.AX", "shares": 459,  "buy_price": 36.01,  "name": "WiseTech Global Ltd"},
]

NZX_WATCHLIST = ["IFT.NZ", "FPH.NZ", "EBO.NZ", "AIA.NZ", "MEL.NZ", "CEN.NZ", "SPK.NZ", "WHS.NZ", "RYM.NZ", "VCT.NZ"]
ASX_WATCHLIST = ["BHP.AX", "CSL.AX", "RIO.AX", "CBA.AX", "WTC.AX", "TNE.AX", "PME.AX", "TLX.AX", "JBH.AX", "XRO.AX"]

URGENT_THRESHOLD_PCT = -5.0

# ============================================================
# SECRETS - LOADED FROM ENVIRONMENT VARIABLES (GitHub Secrets)
# ============================================================
XAI_API_KEY       = os.getenv("XAI_API_KEY", "")
TELEGRAM_TOKEN    = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID  = os.getenv("TELEGRAM_CHAT_ID", "")
EMAIL_USER        = os.getenv("EMAIL_USER", "maximuslucius01@gmail.com")
EMAIL_PASS        = os.getenv("EMAIL_PASS", "")
EMAIL_TO          = os.getenv("EMAIL_TO", "lukassouthey@outlook.co.nz")
SEND_EMAIL        = os.getenv("SEND_EMAIL", "true").lower() == "true"
SEND_TELEGRAM     = os.getenv("SEND_TELEGRAM", "true").lower() == "true"
USE_GROK_ANALYSIS = os.getenv("USE_GROK_ANALYSIS", "false").lower() == "true"

# ============================================================
# HELPER FUNCTIONS
# ============================================================

def get_nz_timestamp():
    try:
        nz_tz = pytz.timezone('Pacific/Auckland')
        return datetime.now(nz_tz).strftime("%H:%M %d %b %Y NZST")
    except:
        return datetime.now().strftime("%H:%M %d %b %Y")

def get_aud_nzd_rate():
    try:
        fx = yf.Ticker("AUDNZD=X")
        return round(float(fx.fast_info.get('lastPrice', 1.105)), 4)
    except:
        return 1.105

def fetch_ticker_snapshot(ticker_symbol):
    try:
        t = yf.Ticker(ticker_symbol)
        info = getattr(t, 'fast_info', {}) or getattr(t, 'info', {})
        current_price = info.get('lastPrice') or info.get('regularMarketPrice', 0.0)
        hist = t.history(period="2d", auto_adjust=True)
        daily_chg = ((hist['Close'].iloc[-1] / hist['Close'].iloc[-2] - 1) * 100) if len(hist) >= 2 else 0.0
        sector = info.get('sector', 'Unknown')
        news = [{"title": n.get('title',''), "publisher": n.get('publisher','')} for n in (t.news or [])[:3]]
        return {
            "current_price": round(float(current_price), 2),
            "daily_chg_pct": round(float(daily_chg), 2),
            "sector": sector,
            "news": news
        }
    except Exception as e:
        print(f"[WARN] {ticker_symbol}: {e}")
        return {"current_price": 0.0, "daily_chg_pct": 0.0, "sector": "Unknown", "news": []}

def calculate_full_portfolio(portfolio_list, fx_rate):
    rows, total_value, total_cost, urgent = [], 0.0, 0.0, []
    sector_breakdown = {}

    for h in portfolio_list:
        ticker, shares, buy_price = h["ticker"], int(h["shares"]), float(h["buy_price"])
        is_aud = ticker.endswith(".AX")
        fx = fx_rate if is_aud else 1.0
        snap = fetch_ticker_snapshot(ticker)

        curr_val = shares * snap["current_price"] * fx
        cost_val = shares * buy_price * fx
        pnl_pct = ((snap["current_price"] / buy_price - 1) * 100) if buy_price > 0 else 0

        total_value += curr_val
        total_cost += cost_val
        sector_breakdown[snap["sector"]] = sector_breakdown.get(snap["sector"], 0) + curr_val

        rows.append({
            "Ticker": ticker, "Name": h.get("name", ticker), "Shares": shares,
            "Buy Price": buy_price, "Current Price": snap["current_price"],
            "Current Value (NZD)": round(curr_val, 2),
            "P&L (NZD)": round(curr_val - cost_val, 2),
            "P&L %": round(pnl_pct, 2),
            "Daily Chg %": snap["daily_chg_pct"],
            "Sector": snap["sector"]
        })

        if snap["daily_chg_pct"] <= URGENT_THRESHOLD_PCT:
            urgent.append(f"**URGENT** {ticker} down {snap['daily_chg_pct']:.1f}% today")

    df = pd.DataFrame(rows)
    total_pnl = total_value - total_cost
    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0
    return df, total_value, total_pnl, total_pnl_pct, urgent, dict(sorted(sector_breakdown.items(), key=lambda x: -x[1]))

def get_top_movers(tickers, period="1d", top_n=10):
    try:
        data = yf.download(tickers, period=period, progress=False, auto_adjust=True, threads=True)["Close"]
        if data.empty or len(data) < 2: return pd.DataFrame()
        pct = ((data.iloc[-1] / data.iloc[0] - 1) * 100).sort_values(ascending=False).head(top_n)
        return pd.DataFrame({"Ticker": pct.index, "% Change": pct.values.round(2)})
    except:
        return pd.DataFrame()

def is_trading_day_nz():
    try:
        return datetime.now(pytz.timezone('Pacific/Auckland')).weekday() < 5
    except:
        return datetime.now().weekday() < 5

def is_within_trading_hours_nz(start=6, end=18):
    try:
        return start <= datetime.now(pytz.timezone('Pacific/Auckland')).hour <= end
    except:
        return start <= datetime.now().hour <= end

# ============================================================
# TELEGRAM
# ============================================================
def send_telegram(text):
    if not SEND_TELEGRAM or not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[INFO] Telegram disabled or credentials missing")
        return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text[:4096], "parse_mode": "Markdown"}
        r = requests.post(url, json=payload, timeout=15)
        if r.status_code == 200:
            print("[SUCCESS] Sent to Telegram")
            return True
        print(f"[ERROR] Telegram: {r.text}")
        return False
    except Exception as e:
        print(f"[ERROR] Telegram failed: {e}")
        return False

# ============================================================
# EMAIL (Gmail)
# ============================================================
def send_email_report(subject, markdown_body, to_email=None):
    if not SEND_EMAIL or not EMAIL_USER or not EMAIL_PASS:
        print("[INFO] Email disabled or credentials missing")
        return False
    recipient = to_email or EMAIL_TO
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = EMAIL_USER
        msg["To"] = recipient

        html = f"""<html><body style="font-family:system-ui;max-width:980px;margin:auto;padding:20px;background:#f8f9fa">
<div style="background:white;border-radius:12px;box-shadow:0 4px 20px rgba(0,0,0,0.08);padding:30px">
<h1 style="color:#1a73e8">📈 NZX & ASX Portfolio Report</h1>
<pre style="white-space:pre-wrap;background:#f1f3f4;padding:20px;border-radius:8px;font-size:0.9rem;line-height:1.5">{markdown_body}</pre>
</div></body></html>"""

        msg.attach(MIMEText("See HTML version", "plain"))
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as server:
            server.login(EMAIL_USER, EMAIL_PASS)
            server.sendmail(EMAIL_USER, recipient.split(","), msg.as_string())
        print(f"[SUCCESS] Email sent to {recipient}")
        return True
    except Exception as e:
        print(f"[ERROR] Email failed: {e}")
        return False

# ============================================================
# xAI GROK ENHANCEMENT (Optional)
# ============================================================
def enhance_with_grok(portfolio_df, total_value, total_pnl_pct):
    if not XAI_API_KEY:
        return "Grok analysis disabled (no XAI_API_KEY)."

    prompt = f"""You are SuperGrok, elite NZ/AU stock trader.
Portfolio Value: ${total_value:,.0f} NZD | Total P&L: {total_pnl_pct:+.2f}%

Holdings:
{portfolio_df[['Ticker','P&L %','Daily Chg %']].to_string(index=False)}

Write a concise institutional update with these headings:
## Holdings Insights & Recommendations
## 7-Day Outlook & Conviction Levels
## Key Risks & Opportunities
## High-Conviction Buy Ideas (NZX/ASX)

Be direct and actionable. Max 550 words."""

    try:
        headers = {"Authorization": f"Bearer {XAI_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": "grok-3-latest",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 1100,
            "temperature": 0.3
        }
        r = requests.post("https://api.x.ai/v1/chat/completions", headers=headers, json=payload, timeout=50)
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"]
        return f"Grok error: {r.text}"
    except Exception as e:
        return f"Grok failed: {e}"

# ============================================================
# MAIN REPORT
# ============================================================
def build_report():
    print("Fetching market data...")
    fx = get_aud_nzd_rate()
    df, total_val, total_pnl, total_pnl_pct, alerts, sectors = calculate_full_portfolio(PORTFOLIO, fx)

    movers_24h = get_top_movers(ASX_WATCHLIST + NZX_WATCHLIST, "1d", 8)

    md = f"""# NZX & ASX Portfolio Report — {get_nz_timestamp()}

**Total Value:** ${total_val:,.0f} NZD   |   **P&L:** {total_pnl_pct:+.2f}%
**FX AUD/NZD:** {fx}

## Portfolio Snapshot
{df.to_markdown(index=False)}
"""

    if alerts:
        md += "\n## URGENT ALERTS\n" + "\n".join([f"- {a}" for a in alerts]) + "\n"

    if USE_GROK_ANALYSIS and XAI_API_KEY:
        print("Calling Grok for analysis...")
        grok_text = enhance_with_grok(df, total_val, total_pnl_pct)
        md += "\n" + grok_text
    else:
        md += """
## Holdings Insights & Recommendations
( Set USE_GROK_ANALYSIS=true + XAI_API_KEY to enable AI analysis )

## 7-Day Outlook
Medium-High conviction. Watch economic data and company updates.

## Key Risks & Opportunities
- Risks: Sector concentration, macro moves.
- Opportunities: Quality dips in current holdings.

## Action Items
Review positions down >5% today.
"""

    md += "\n---\n*Automated • Data: Yahoo Finance*"
    return md, df, total_val, total_pnl_pct

# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    if not is_trading_day_nz() or not is_within_trading_hours_nz(6, 18):
        print("Outside trading hours (6am-6pm NZST Mon-Fri). Exiting.")
        exit(0)

    print("=== Generating NZX/ASX Portfolio Report ===")
    report_md, df, total_val, pnl_pct = build_report()

    os.makedirs("artifacts", exist_ok=True)
    with open("artifacts/portfolio_report.md", "w", encoding="utf-8") as f:
        f.write(report_md)
    df.to_csv("artifacts/portfolio_valuation.csv", index=False)

    subject = f"NZX/ASX Portfolio • {datetime.now().strftime('%d %b')} | P&L {pnl_pct:+.1f}%"

    if SEND_EMAIL:
        send_email_report(subject, report_md)

    if SEND_TELEGRAM:
        short_text = f"📈 *Portfolio Update*\nValue: ${total_val:,.0f} NZD\nP&L: {pnl_pct:+.2f}%\n\n{report_md[:2200]}"
        send_telegram(short_text)

    print("\n✅ Report complete. Notifications sent where enabled.")
