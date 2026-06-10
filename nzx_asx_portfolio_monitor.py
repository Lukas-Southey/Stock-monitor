#!/usr/bin/env python3
"""
NZX & ASX Portfolio Monitor & Report Generator
SuperGrok Institutional-Style Daily Briefing (Data Layer) + Hourly Email Automation

Features:
- Fetches live prices via yfinance
- Full NZD valuation + P&L table
- Urgent alerts on big daily drops
- Top movers (NZX + ASX) for 24h / 7d / 1mo
- Recent news from holdings
- Complete structured Markdown report matching the exact SuperGrok prompt
- Trading hours guard (6am–6pm NZST, Mon–Fri)
- Optional email delivery (perfect for GitHub Actions)

Run locally: python nzx_asx_portfolio_monitor.py
For hourly email on trading days: Use the GitHub Actions workflow below.

Requirements:
    pip install yfinance pandas pytz
"""

import yfinance as yf
import pandas as pd
from datetime import datetime
import pytz
import warnings
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

warnings.filterwarnings("ignore")


# ============================================================
# CONFIG - UPDATE YOUR HOLDINGS HERE
# ============================================================
PORTFOLIO = [
    {"ticker": "PME.AX", "shares": 410,  "buy_price": 165.54, "name": "Pro Medicus Ltd"},
    {"ticker": "TLX.AX", "shares": 1918, "buy_price": 13.31,  "name": "Telix Pharmaceuticals Ltd"},
    {"ticker": "EBO.NZ", "shares": 619,  "buy_price": 19.52,  "name": "EBOS Group Ltd"},
    {"ticker": "TNE.AX", "shares": 400,  "buy_price": 32.33,  "name": "Technology One Ltd"},
    {"ticker": "WTC.AX", "shares": 459,  "buy_price": 36.01,  "name": "WiseTech Global Ltd"},
]

NZX_WATCHLIST = [
    "IFT.NZ", "FPH.NZ", "EBO.NZ", "AIA.NZ", "MEL.NZ", "CEN.NZ",
    "SPK.NZ", "WHS.NZ", "RYM.NZ", "VCT.NZ", "ANZ.NZ", "WBC.NZ",
    "KMD.NZ", "SKT.NZ", "THL.NZ"
]

ASX_WATCHLIST = [
    "BHP.AX", "CSL.AX", "RIO.AX", "CBA.AX", "WBC.AX", "ANZ.AX",
    "NAB.AX", "FMG.AX", "WTC.AX", "TNE.AX", "PME.AX", "TLX.AX",
    "JBH.AX", "WOW.AX", "COL.AX", "REA.AX", "SEK.AX", "CPU.AX",
    "XRO.AX", "SQ2.AX"
]

URGENT_THRESHOLD_PCT = -5.0


# ============================================================
# EMAIL & AUTOMATION CONFIG (GitHub Actions will override via env)
# ============================================================
EMAIL_ENABLED = os.getenv("SEND_EMAIL", "false").lower() == "true"
EMAIL_USER = os.getenv("EMAIL_USER", "")
EMAIL_PASS = os.getenv("EMAIL_PASS", "")
EMAIL_TO = os.getenv("EMAIL_TO", "")
EMAIL_SUBJECT_PREFIX = "📈 NZX/ASX Portfolio Report"


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def get_nz_timestamp():
    try:
        nz_tz = pytz.timezone('Pacific/Auckland')
        return datetime.now(nz_tz).strftime("%H:%M %d %b %Y NZST")
    except:
        return datetime.now().strftime("%H:%M %d %b %Y") + " (local)"


def get_aud_nzd_rate():
    try:
        fx = yf.Ticker("AUDNZD=X")
        rate = fx.fast_info.get('lastPrice') or fx.fast_info.get('regularMarketPrice', 1.105)
        return round(float(rate), 4)
    except:
        return 1.105


def fetch_ticker_snapshot(ticker_symbol):
    try:
        t = yf.Ticker(ticker_symbol)
        info = getattr(t, 'fast_info', {}) or getattr(t, 'info', {})
        current_price = info.get('lastPrice') or info.get('regularMarketPrice', 0.0)

        hist = t.history(period="2d", auto_adjust=True)
        if len(hist) >= 2:
            daily_chg = (hist['Close'].iloc[-1] / hist['Close'].iloc[-2] - 1) * 100
        else:
            daily_chg = info.get('regularMarketChangePercent', 0.0)

        sector = info.get('sector', 'Unknown')

        news_items = []
        if hasattr(t, 'news') and t.news:
            for item in t.news[:3]:
                news_items.append({
                    "title": item.get('title', ''),
                    "publisher": item.get('publisher', '')
                })

        return {
            "current_price": round(float(current_price), 2) if current_price else 0.0,
            "daily_chg_pct": round(float(daily_chg), 2) if daily_chg else 0.0,
            "sector": sector,
            "news": news_items
        }
    except Exception as e:
        print(f"[WARN] {ticker_symbol}: {e}")
        return {"current_price": 0.0, "daily_chg_pct": 0.0, "sector": "Unknown", "news": []}


def calculate_full_portfolio(portfolio_list, fx_rate):
    rows = []
    total_value_nzd = 0.0
    total_cost_nzd = 0.0
    urgent_alerts = []
    sector_breakdown = {}

    for h in portfolio_list:
        ticker = h["ticker"]
        shares = int(h["shares"])
        buy_price = float(h["buy_price"])
        name = h.get("name", ticker)
        is_aud = ticker.endswith(".AX")
        fx = fx_rate if is_aud else 1.0

        snap = fetch_ticker_snapshot(ticker)
        curr_price = snap["current_price"]
        daily_chg = snap["daily_chg_pct"]
        sector = snap["sector"]

        current_value_nzd = shares * curr_price * fx
        cost_basis_nzd = shares * buy_price * fx
        pnl_nzd = current_value_nzd - cost_basis_nzd
        pnl_pct = ((curr_price / buy_price) - 1) * 100 if buy_price > 0 else 0.0

        total_value_nzd += current_value_nzd
        total_cost_nzd += cost_basis_nzd

        if sector not in sector_breakdown:
            sector_breakdown[sector] = 0.0
        sector_breakdown[sector] += current_value_nzd

        rows.append({
            "Ticker": ticker,
            "Name": name,
            "Shares": shares,
            "Buy Price": round(buy_price, 2),
            "Current Price": curr_price,
            "Current Value (NZD)": round(current_value_nzd, 2),
            "P&L (NZD)": round(pnl_nzd, 2),
            "P&L %": round(pnl_pct, 2),
            "Daily Chg %": daily_chg,
            "Sector": sector
        })

        if daily_chg <= URGENT_THRESHOLD_PCT:
            urgent_alerts.append(
                f"**URGENT ALERT** — {ticker} ({name}) down {daily_chg:.2f}% today. "
                "Review immediately or consider reducing/tightening stops."
            )

    df = pd.DataFrame(rows)
    total_pnl_nzd = total_value_nzd - total_cost_nzd
    total_pnl_pct = (total_pnl_nzd / total_cost_nzd * 100) if total_cost_nzd > 0 else 0.0
    sector_breakdown = dict(sorted(sector_breakdown.items(), key=lambda x: x[1], reverse=True))

    return df, total_value_nzd, total_pnl_nzd, total_pnl_pct, urgent_alerts, sector_breakdown, total_cost_nzd


def get_top_movers(ticker_list, period="1d", top_n=15):
    try:
        data = yf.download(ticker_list, period=period, progress=False, auto_adjust=True, threads=True)["Close"]
        if data.empty or len(data) < 2:
            return pd.DataFrame(columns=["Ticker", "% Change"])
        pct = ((data.iloc[-1] / data.iloc[0]) - 1) * 100
        top = pct.sort_values(ascending=False).head(top_n)
        return pd.DataFrame({"Ticker": top.index, "% Change": top.values.round(2)})
    except Exception as e:
        print(f"[WARN] Movers {period}: {e}")
        return pd.DataFrame(columns=["Ticker", "% Change"])


def is_trading_day_nz():
    try:
        nz_tz = pytz.timezone('Pacific/Auckland')
        now = datetime.now(nz_tz)
        return now.weekday() < 5
    except:
        return datetime.now().weekday() < 5


def is_within_trading_hours_nz(start_hour=6, end_hour=18):
    try:
        nz_tz = pytz.timezone('Pacific/Auckland')
        now = datetime.now(nz_tz)
        return start_hour <= now.hour <= end_hour
    except:
        now = datetime.now()
        return start_hour <= now.hour <= end_hour


def send_portfolio_email(report_markdown, to_email=None):
    if not EMAIL_ENABLED or not EMAIL_USER or not EMAIL_PASS:
        print("[INFO] Email disabled or credentials missing.")
        return False

    recipient = to_email or EMAIL_TO
    if not recipient:
        print("[WARN] No recipient email.")
        return False

    try:
        msg = MIMEMultipart("alternative")
        today_str = datetime.now().strftime("%d %b %Y")
        msg["Subject"] = f"{EMAIL_SUBJECT_PREFIX} — {today_str}"
        msg["From"] = EMAIL_USER
        msg["To"] = recipient

        text = "Your portfolio report is ready (see HTML version below)."

        html = f"""<!DOCTYPE html>
<html><body style="font-family: system-ui, -apple-system, sans-serif; max-width: 980px; margin: auto; padding: 20px; background:#f8f9fa;">
<div style="background:white; border-radius:12px; box-shadow:0 4px 20px rgba(0,0,0,0.08); padding:30px;">
<h1 style="color:#1a73e8; margin-top:0;">📈 NZX & ASX Portfolio Report</h1>
<p style="color:#5f6368;">{today_str} NZST • Automated hourly during trading hours</p>
<div style="background:#f1f3f4; border-radius:8px; padding:20px; margin:20px 0; font-family:ui-monospace,monospace; white-space:pre-wrap; font-size:0.875rem; line-height:1.5; overflow-x:auto;">
{report_markdown}
</div>
<p style="font-size:0.85rem; color:#70757a;">Generated by your NZX/ASX Portfolio Monitor • SuperGrok</p>
</div></body></html>"""

        msg.attach(MIMEText(text, "plain"))
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as server:
            server.login(EMAIL_USER, EMAIL_PASS)
            server.sendmail(EMAIL_USER, recipient.split(","), msg.as_string())

        print(f"[SUCCESS] Email sent to {recipient}")
        return True
    except Exception as e:
        print(f"[ERROR] Email failed: {e}")
        return False


def collect_recent_news(portfolio_list):
    all_news = []
    for h in portfolio_list:
        snap = fetch_ticker_snapshot(h["ticker"])
        for n in snap.get("news", []):
            all_news.append({"ticker": h["ticker"], "title": n.get("title", ""), "publisher": n.get("publisher", "")})

    seen = set()
    unique = []
    for item in all_news:
        if item["title"] and item["title"] not in seen:
            seen.add(item["title"])
            unique.append(item)
    return unique[:6]


def build_markdown_report():
    print("Fetching live prices and market data...")
    fx = get_aud_nzd_rate()
    ts = get_nz_timestamp()

    df, total_val, total_pnl, total_pnl_pct, alerts, sector_dict, total_cost = calculate_full_portfolio(PORTFOLIO, fx)

    print("Calculating top movers...")
    movers_24h_nzx = get_top_movers(NZX_WATCHLIST, "1d")
    movers_24h_asx = get_top_movers(ASX_WATCHLIST, "1d")
    movers_7d_nzx  = get_top_movers(NZX_WATCHLIST, "7d")
    movers_7d_asx  = get_top_movers(ASX_WATCHLIST, "7d")
    movers_1m_nzx  = get_top_movers(NZX_WATCHLIST, "1mo")
    movers_1m_asx  = get_top_movers(ASX_WATCHLIST, "1mo")

    recent_news = collect_recent_news(PORTFOLIO)

    # Build the full report (same structure as before)
    md = f"""# NZX & ASX Portfolio Report — SuperGrok Institutional Briefing
**Generated:** {ts}  
**Data:** Latest available (Yahoo Finance) | **AUD/NZD:** {fx}

"""

    # 1. Valuation + Alerts
    md += "## 1. Live Prices, Valuation & Urgent Alerts\n\n"
    md += df.to_markdown(index=False) + "\n\n"
    md += f"**Total Portfolio Value (NZD):** ${total_val:,.2f}\n"
    md += f"**Total Unrealized P&L (NZD):** ${total_pnl:,.2f} ({total_pnl_pct:+.2f}%)\n\n"

    if alerts:
        md += "### URGENT ALERTS\n" + "\n".join([f"- {a}" for a in alerts]) + "\n\n"
    else:
        md += "No urgent alerts triggered.\n\n"

    # 2. News
    md += "## 2. Key NZX & ASX News & Events\n\n"
    if recent_news:
        for n in recent_news:
            md += f"- **{n['ticker']}**: {n['title']} ({n['publisher']})\n"
    else:
        md += "No recent news for holdings.\n"
    md += "\n"

    # 3. Top Movers
    md += "## 3. Top Movers Reports\n\n"
    for title, mdf in [
        ("NZX Top Movers – Last 24 Hours", movers_24h_nzx),
        ("ASX Top Movers – Last 24 Hours", movers_24h_asx),
        ("NZX Top Movers – Past 7 Days", movers_7d_nzx),
        ("ASX Top Movers – Past 7 Days", movers_7d_asx),
        ("NZX Top Movers – Past 1 Month", movers_1m_nzx),
        ("ASX Top Movers – Past 1 Month", movers_1m_asx),
    ]:
        md += f"### {title}\n"
        md += mdf.to_markdown(index=False) if not mdf.empty else "Data unavailable.\n"
        md += "\n"

    # 4-8. Institutional Briefing (abbreviated but complete structure)
    md += "## 4. Ultra-Advanced Institutional Portfolio Briefing\n\n"
    md += "### 1. Portfolio Snapshot & Daily Performance\n"
    md += f"- **Total Value:** ${total_val:,.2f} NZD | **P&L:** ${total_pnl:,.2f} ({total_pnl_pct:+.2f}%)\n\n"

    md += "### 2. Sector Allocation Review\n"
    for sec, val in sector_dict.items():
        pct = (val / total_val * 100) if total_val > 0 else 0
        md += f"- {sec}: ${val:,.0f} ({pct:.1f}%)\n"
    md += "\n"

    md += "### 3. Market Regime & Key Drivers\n"
    md += "RBA/RBNZ policy, China demand, commodity prices, and AUD/NZD cross remain the dominant macro drivers. Earnings season and company-specific catalysts are the main stock-level movers.\n\n"

    md += "### 4. Holdings Insights & Recommendations\n"
    for _, r in df.iterrows():
        rec = "Hold"
        if r["P&L %"] > 25: rec = "Reduce / Trim on strength"
        elif r["Daily Chg %"] < -4: rec = "Watch closely"
        md += f"**{r['Ticker']}**: {r['P&L %']:+.1f}% | Daily {r['Daily Chg %']:+.1f}% → **{rec}**\n"
    md += "\n"

    md += "### 5. 7-Day Outlook & Conviction Levels\n"
    md += "**Overall Conviction: Medium-High**. Watch for follow-through on recent movers and any company updates.\n\n"

    md += "### 6. Risk Management & Portfolio Health\n"
    md += f"- {len(df)} holdings across multiple sectors. Good liquidity. Monitor concentration in any single name >25-30%.\n\n"

    md += "### 7. Key Risks & Opportunities\n"
    md += "- Risks: Sector concentration, AUD strength, global growth slowdown.\n"
    md += "- Opportunities: Quality dips in current holdings or new high-conviction ideas (see Section 8).\n\n"

    md += "### 8. Insights and Recommendations on which to BUY\n"
    md += "Run full SuperGrok analysis with this data for specific 3-5 high-conviction ideas with entry/target/stop levels.\n\n"

    md += "## 5. Broader Market Projections\n"
    md += "Focus on liquid healthcare, technology, logistics and infrastructure names with strong moats and visible catalysts.\n\n"

    md += "## 6. Strategic 7-Day Action Plan\n"
    md += "**Daily**: Check for >4-5% moves. Review announcements.\n"
    md += "**This week**: Watch economic data releases and earnings updates. Rebalance only if allocation rules breached.\n\n"

    md += "---\n**Key Items to Watch**: Price action on big movers today + any company-specific news.\n"
    md += "*For deeper analysis paste this report into SuperGrok.*"

    return md, df


# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    # Trading hours guard (used by GitHub Actions)
    if not is_trading_day_nz():
        print("Weekend in NZ time. Exiting.")
        exit(0)

    if not is_within_trading_hours_nz(6, 18):
        print("Outside 6am–6pm NZST. Exiting.")
        exit(0)

    print("=== NZX/ASX Trading Hours — Generating Hourly Report ===")
    report_md, valuation_df = build_markdown_report()

    print("\n" + "="*70)
    print(report_md)
    print("="*70 + "\n")

    os.makedirs("/home/workdir/artifacts", exist_ok=True)
    with open("/home/workdir/artifacts/portfolio_report.md", "w", encoding="utf-8") as f:
        f.write(report_md)
    valuation_df.to_csv("/home/workdir/artifacts/portfolio_valuation.csv", index=False)

    if EMAIL_ENABLED:
        send_portfolio_email(report_md)

    print("\n✅ Done. Report saved to artifacts/ folder.")
    if EMAIL_ENABLED:
        print("   Email delivery attempted.")
