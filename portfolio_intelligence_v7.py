#!/usr/bin/env python3
"""
================================================================================
NZ + ASX + US PORTFOLIO INTELLIGENCE SYSTEM v7
Ultra Advanced Institutional Portfolio Monitor with Grok-4.3 Analysis
================================================================================
Single-file version - ready for GitHub.

Features:
- Real-time prices & P&L in NZD (AUD/NZD handling)
- Top movers across NZX, ASX, and US markets
- Precious metals (Gold & Silver) in USD + NZD
- Ruthless high-conviction Grok-4.3 analysis
- Email + Telegram notifications
- Robust error handling

Quick Start:
1. pip install yfinance pandas pytz requests python-dotenv
2. Create a .env file with your keys (see bottom of this file)
3. python portfolio_intelligence_v7.py

Report saved to: artifacts/portfolio_report.md
================================================================================
"""

import os
import time
import warnings
from datetime import datetime
from typing import Dict, List, Tuple

import pandas as pd
import pytz
import requests
import yfinance as yf
from dotenv import load_dotenv
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import smtplib

warnings.filterwarnings("ignore")
load_dotenv()

# ============================================================
# CONFIGURATION
# ============================================================
PORTFOLIO = [
    {"ticker": "BHP.AX", "shares": 0.82711896, "buy_price": 59.205, "name": "BHP Group Limited"},
    {"ticker": "FPH.NZ", "shares": 0.83761801, "buy_price": 38.780, "name": "Fisher & Paykel Healthcare Corporation Limited"},
]

CORE_WATCHLIST = [
    "BHP.AX", "RIO.AX", "FMG.AX", "JHX.AX", "CSL.AX", "RMD.AX", "COH.AX",
    "CBA.AX", "WBC.AX", "ANZ.AX", "NAB.AX", "MQG.AX", "WES.AX", "WOW.AX", "COL.AX",
    "TLS.AX", "FPH.NZ", "AIA.NZ", "MEL.NZ", "SPK.NZ", "CEN.NZ", "EBO.NZ",
    "VCT.NZ", "NZX.NZ", "AIR.NZ", "THL.NZ", "CAR.AX", "RHC.AX", "A2M.AX",
    "TWE.AX", "SGP.AX", "GMG.AX", "SCG.AX", "MFG.AX", "PME.AX", "XRO.AX"
]

US_WATCHLIST = [
    "NVDA", "MSFT", "AAPL", "GOOGL", "AMZN", "META", "AVGO", "TSLA", "AMD", "ORCL",
    "JPM", "BAC", "WFC", "GS", "MS", "C", "V", "MA", "BRK-B",
    "UNH", "LLY", "JNJ", "ABBV", "MRK", "PFE",
    "XOM", "CVX", "COP",
    "PG", "KO", "PEP", "COST", "WMT", "HD", "MCD",
    "TSM", "QCOM", "INTC", "MU", "AMAT", "LRCX",
    "NFLX", "ADBE", "CRM", "NOW", "SNOW",
    "PLTR", "ARM", "UBER", "ABNB"
]

# Feature flags
SEND_EMAIL = os.getenv("SEND_EMAIL", "True").lower() == "true"
SEND_TELEGRAM = os.getenv("SEND_TELEGRAM", "True").lower() == "true"
USE_GROK_ANALYSIS = os.getenv("USE_GROK_ANALYSIS", "True").lower() == "true"

# Credentials from .env
XAI_API_KEY = os.getenv("XAI_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
EMAIL_TO = os.getenv("EMAIL_TO")


# ============================================================
# DATA FETCHING
# ============================================================
def get_nz_timestamp() -> str:
    try:
        return datetime.now(pytz.timezone('Pacific/Auckland')).strftime("%H:%M %d %b %Y NZST")
    except:
        return datetime.now().strftime("%H:%M %d %b %Y")


def get_aud_nzd_rate() -> float:
    try:
        return round(float(yf.Ticker("AUDNZD=X").fast_info.get('lastPrice', 1.105)), 4)
    except:
        return 1.105


def get_usd_nzd_rate() -> float:
    for symbol in ["NZDUSD=X", "USDNZD=X"]:
        try:
            rate = yf.Ticker(symbol).fast_info.get('lastPrice')
            if rate:
                return round(float(rate), 4)
        except:
            continue
    return 1.65


def fetch_ticker_data(ticker: str) -> Dict[str, float]:
    try:
        t = yf.Ticker(ticker)
        info = getattr(t, 'fast_info', {}) or getattr(t, 'info', {})
        price = info.get('lastPrice') or info.get('regularMarketPrice', 0)
        hist = t.history(period="2d", auto_adjust=True)
        chg = ((hist['Close'].iloc[-1] / hist['Close'].iloc[-2] - 1) * 100) if len(hist) >= 2 else 0
        return {"price": round(float(price), 2), "daily_chg": round(float(chg), 2)}
    except:
        return {"price": 0, "daily_chg": 0}


def get_precious_metals_robust(usd_nzd: float) -> Dict[str, Dict[str, float]]:
    metals: Dict[str, Dict[str, float]] = {}

    # Gold
    gold_price, gold_chg = None, 0.0
    for symbol in ["GC=F", "XAUUSD=X"]:
        try:
            t = yf.Ticker(symbol)
            price = t.fast_info.get('lastPrice')
            if price:
                gold_price = round(float(price), 2)
                hist = t.history(period="2d", auto_adjust=True)
                if len(hist) >= 2:
                    gold_chg = round(((hist['Close'].iloc[-1] / hist['Close'].iloc[-2] - 1) * 100), 2)
                break
        except:
            time.sleep(0.7)
            continue
    if gold_price is None:
        gold_price, gold_chg = 2650.0, 0.0
    metals["gold"] = {"usd": gold_price, "nzd": round(gold_price * usd_nzd, 2), "daily_chg": gold_chg}

    # Silver
    silver_price, silver_chg = None, 0.0
    for symbol in ["SI=F", "XAGUSD=X"]:
        try:
            t = yf.Ticker(symbol)
            price = t.fast_info.get('lastPrice')
            if price:
                silver_price = round(float(price), 2)
                hist = t.history(period="2d", auto_adjust=True)
                if len(hist) >= 2:
                    silver_chg = round(((hist['Close'].iloc[-1] / hist['Close'].iloc[-2] - 1) * 100), 2)
                break
        except:
            time.sleep(0.7)
            continue
    if silver_price is None:
        silver_price, silver_chg = 31.5, 0.0
    metals["silver"] = {"usd": silver_price, "nzd": round(silver_price * usd_nzd, 2), "daily_chg": silver_chg}

    return metals


def get_top_movers(tickers: List[str], period: str = "1d", top_n: int = 10) -> pd.DataFrame:
    try:
        data = yf.download(tickers, period=period, progress=False, auto_adjust=True, threads=True)["Close"]
        data = data.dropna(how="all")
        if data.empty or len(data) < 2:
            return pd.DataFrame()
        pct = ((data.iloc[-1] / data.iloc[0]) - 1) * 100
        top = pct.sort_values(ascending=False).head(top_n)
        return pd.DataFrame({"Ticker": top.index, "% Change": top.values.round(2)})
    except:
        return pd.DataFrame()


# ============================================================
# PORTFOLIO CALCULATION
# ============================================================
def calculate_portfolio(fx: float) -> Tuple[pd.DataFrame, float, float, float, float, float]:
    rows, total_val, total_cost = [], 0.0, 0.0

    for h in PORTFOLIO:
        data = fetch_ticker_data(h["ticker"])
        is_aud = h["ticker"].endswith(".AX")
        fx_rate = fx if is_aud else 1.0

        value_nzd = round(h["shares"] * data["price"] * fx_rate, 2)
        cost_nzd = round(h["shares"] * h["buy_price"] * fx_rate, 2)
        pnl_nzd = round(value_nzd - cost_nzd, 2)
        pnl_pct = round(((data["price"] / h["buy_price"] - 1) * 100), 2) if h["buy_price"] > 0 else 0

        total_val += value_nzd
        total_cost += cost_nzd

        rows.append({
            "Ticker": h["ticker"],
            "Name": h.get("name", ""),
            "Shares": round(h["shares"], 6),
            "Buy Price": h["buy_price"],
            "Current Price": data["price"],
            "Value (NZD)": value_nzd,
            "Cost Basis (NZD)": cost_nzd,
            "Unrealized P&L (NZD)": pnl_nzd,
            "P&L %": pnl_pct,
            "Daily Chg %": data["daily_chg"]
        })

    df = pd.DataFrame(rows)
    if total_val > 0:
        df["% of Portfolio"] = (df["Value (NZD)"] / total_val * 100).round(1)
    else:
        df["% of Portfolio"] = 0.0

    total_pnl_nzd = round(total_val - total_cost, 2)
    total_pnl_pct = round((total_pnl_nzd / total_cost * 100), 2) if total_cost > 0 else 0
    max_conc = df["% of Portfolio"].max() if not df.empty else 0

    return df, round(total_val, 2), round(total_cost, 2), total_pnl_nzd, total_pnl_pct, round(max_conc, 1)


# ============================================================
# GROK ANALYSIS
# ============================================================
def enhance_with_grok(
    df: pd.DataFrame, total_value: float, total_cost: float,
    total_pnl_nzd: float, total_pnl_pct: float, max_concentration: float,
    movers_1d: pd.DataFrame, movers_5d: pd.DataFrame, movers_30d: pd.DataFrame,
    movers_1y: pd.DataFrame, movers_us_1d: pd.DataFrame, movers_us_5d: pd.DataFrame,
    movers_us_30d: pd.DataFrame, metals: Dict[str, Dict[str, float]],
    fx: float, usd_nzd: float
) -> str:

    if not USE_GROK_ANALYSIS or not XAI_API_KEY:
        return "Grok analysis disabled."

    gold = metals.get("gold", {})
    silver = metals.get("silver", {})

    prompt = f"""You are one of the sharpest, most ruthless, and highest-conviction institutional portfolio managers in Australasia and global markets. You have managed multi-hundred-million-dollar books. You optimise for asymmetric returns, regime-aware positioning, and rapid compounding. You hate mediocrity, over-diversification in small books, and slow decision-making.

CURRENT PORTFOLIO (NZD reporting):
{df.to_string(index=False)}

KEY METRICS:
Value: ${total_value:,.2f} NZD | Unrealized P&L: ${total_pnl_nzd:,.2f} NZD ({total_pnl_pct:+.2f}%)
Largest Position Concentration: {max_concentration:.1f}%
AUD/NZD: {fx} | USD/NZD: {usd_nzd}

PRECIOUS METALS:
Gold: ${gold.get('usd',0):,.2f} USD/oz (${gold.get('nzd',0):,.2f} NZD) | Daily {gold.get('daily_chg',0):+.2f}%
Silver: ${silver.get('usd',0):,.2f} USD/oz (${silver.get('nzd',0):,.2f} NZD) | Daily {silver.get('daily_chg',0):+.2f}%

NZX + ASX TOP MOVERS (from liquid watchlist):
24h: {movers_1d.to_string(index=False) if not movers_1d.empty else "No data"}
5d: {movers_5d.to_string(index=False) if not movers_5d.empty else "No data"}
30d: {movers_30d.to_string(index=False) if not movers_30d.empty else "No data"}
12m: {movers_1y.to_string(index=False) if not movers_1y.empty else "No data"}

US EQUITY TOP MOVERS (NYSE + NASDAQ):
24h: {movers_us_1d.to_string(index=False) if not movers_us_1d.empty else "No data"}
5d: {movers_us_5d.to_string(index=False) if not movers_us_5d.empty else "No data"}
30d: {movers_us_30d.to_string(index=False) if not movers_us_30d.empty else "No data"}

TASK:
Produce a **ruthlessly optimised, high-alpha institutional report** that identifies the strongest positive movers and themes across **all three markets** (US, NZX, ASX) and gives a clear, aggressive but realistic pathway to meaningfully grow this small portfolio.

Use these exact headings:
## Portfolio Construction & Risk Diagnosis
## Market Regime & Leadership Analysis (US + NZX + ASX)
## Precious Metals & Macro Signal Interpretation
## Highest-Conviction Positive Movers & Themes Right Now
## 7-Day & 30-Day Projections with Specific Price Levels & Conviction
## Ruthless Optimisation Plan – How to Boost This Portfolio Aggressively
## Immediate Recommended Actions (Prioritised & Sized)

Strict quality rules:
- Be extremely direct and decisive. No hedging language whatsoever.
- Explicitly analyse the strongest positive movers and sector leadership themes across US, NZX and ASX.
- Ruthlessly recommend whether to double down on current winners, cut underperformers faster, or add 1-2 high-quality ideas.
- Give precise price levels for entries, adds, trims and stops with rationale and conviction percentages.
- End with a short, numbered, immediately actionable list for the next 48-72 hours.
- Prioritise asymmetric upside while respecting the small size of the current book."""

    headers = {"Authorization": f"Bearer {XAI_API_KEY}", "Content-Type": "application/json"}
    try:
        payload = {
            "model": "grok-4.3",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 1850,
            "temperature": 0.21
        }
        r = requests.post("https://api.x.ai/v1/chat/completions", headers=headers, json=payload, timeout=85)
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"]
        return f"Grok error: {r.status_code}"
    except Exception as e:
        return f"Grok failed: {e}"


# ============================================================
# REPORT GENERATION
# ============================================================
def build_report() -> Tuple[str, float, float]:
    fx = get_aud_nzd_rate()
    usd_nzd = get_usd_nzd_rate()
    metals = get_precious_metals_robust(usd_nzd)

    df, total_val, total_cost, total_pnl_nzd, total_pnl_pct, max_conc = calculate_portfolio(fx)

    print("[INFO] Fetching movers across NZX, ASX and US markets...")
    movers_1d = get_top_movers(CORE_WATCHLIST, "1d", 10)
    movers_5d = get_top_movers(CORE_WATCHLIST, "5d", 10)
    movers_30d = get_top_movers(CORE_WATCHLIST, "30d", 10)
    movers_1y = get_top_movers(CORE_WATCHLIST, "1y", 10)
    movers_us_1d = get_top_movers(US_WATCHLIST, "1d", 10)
    movers_us_5d = get_top_movers(US_WATCHLIST, "5d", 10)
    movers_us_30d = get_top_movers(US_WATCHLIST, "30d", 10)

    gold = metals.get("gold", {})
    silver = metals.get("silver", {})

    md = f"""# NZX + ASX + US Portfolio Intelligence Report v7
**{get_nz_timestamp()}**

**Portfolio Value:** ${total_val:,.2f} NZD | **P&L:** ${total_pnl_nzd:,.2f} NZD ({total_pnl_pct:+.2f}%)
**Largest Position:** {max_conc:.1f}% | **AUD/NZD:** {fx} | **USD/NZD:** {usd_nzd}
"""

    md += "## Precious Metals Snapshot\n\n"
    md += f"**Gold** — ${gold.get('usd', 0):,.2f} USD/oz (${gold.get('nzd', 0):,.2f} NZD/oz) Daily: {gold.get('daily_chg', 0):+.2f}%\n\n"
    md += f"**Silver** — ${silver.get('usd', 0):,.2f} USD/oz (${silver.get('nzd', 0):,.2f} NZD/oz) Daily: {silver.get('daily_chg', 0):+.2f}%\n\n"

    md += "## My Portfolio\n\n"
    md += df.to_markdown(index=False) + "\n\n"

    md += "## Top 10 Movers – NZX & ASX – Last 24 Hours\n\n"
    md += (movers_1d.to_markdown(index=False) if not movers_1d.empty else "_No data_") + "\n\n"
    md += "## Top 10 Movers – NZX & ASX – Last 5 Trading Days\n\n"
    md += (movers_5d.to_markdown(index=False) if not movers_5d.empty else "_No data_") + "\n\n"
    md += "## Top 10 Movers – NZX & ASX – Last 30 Days\n\n"
    md += (movers_30d.to_markdown(index=False) if not movers_30d.empty else "_No data_") + "\n\n"
    md += "## Top 10 Movers – NZX & ASX – Last 12 Months\n\n"
    md += (movers_1y.to_markdown(index=False) if not movers_1y.empty else "_No data_") + "\n\n"

    md += "## Top 10 Movers – United States (NYSE + NASDAQ) – Last 24 Hours\n\n"
    md += (movers_us_1d.to_markdown(index=False) if not movers_us_1d.empty else "_No data_") + "\n\n"
    md += "## Top 10 Movers – United States (NYSE + NASDAQ) – Last 5 Trading Days\n\n"
    md += (movers_us_5d.to_markdown(index=False) if not movers_us_5d.empty else "_No data_") + "\n\n"
    md += "## Top 10 Movers – United States (NYSE + NASDAQ) – Last 30 Days\n\n"
    md += (movers_us_30d.to_markdown(index=False) if not movers_us_30d.empty else "_No data_") + "\n\n"

    if USE_GROK_ANALYSIS:
        print("[INFO] Generating high-alpha, ruthless optimisation analysis...")
        analysis = enhance_with_grok(
            df, total_val, total_cost, total_pnl_nzd, total_pnl_pct, max_conc,
            movers_1d, movers_5d, movers_30d, movers_1y,
            movers_us_1d, movers_us_5d, movers_us_30d,
            metals, fx, usd_nzd
        )
        md += analysis + "\n"

    md += "\n---\n*Institutional Portfolio Intelligence System v7 • Maximum Alpha Focus*"
    return md, total_val, total_pnl_pct


# ============================================================
# NOTIFICATIONS
# ============================================================
def send_email(report_md: str, pnl_pct: float):
    if not SEND_EMAIL or not all([EMAIL_USER, EMAIL_PASS, EMAIL_TO]):
        print("⚠️ Email notifications disabled or misconfigured.")
        return
    try:
        msg = MIMEMultipart()
        msg["Subject"] = f"Portfolio Intelligence v7 • {datetime.now().strftime('%d %b %Y')} | P&L {pnl_pct:+.2f}%"
        msg["From"] = EMAIL_USER
        msg["To"] = EMAIL_TO
        msg.attach(MIMEText(report_md, "plain"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_USER, EMAIL_PASS)
            server.sendmail(EMAIL_USER, EMAIL_TO, msg.as_string())
        print("✅ Email sent")
    except Exception as e:
        print(f"⚠️ Email error: {e}")


def send_telegram(total_val: float, pnl_pct: float):
    if not SEND_TELEGRAM or not all([TELEGRAM_TOKEN, TELEGRAM_CHAT_ID]):
        return
    try:
        short = f"📈 Portfolio v7\nValue: ${total_val:,.0f} NZD\nP&L: {pnl_pct:+.2f}%"
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": short}
        )
        print("✅ Telegram sent")
    except Exception:
        pass


# ============================================================
# MAIN EXECUTION
# ============================================================
if __name__ == "__main__":
    print("=== INSTITUTIONAL PORTFOLIO INTELLIGENCE SYSTEM v7 (Maximum Alpha) ===")

    report_md, total_val, pnl_pct = build_report()

    os.makedirs("artifacts", exist_ok=True)
    with open("artifacts/portfolio_report.md", "w", encoding="utf-8") as f:
        f.write(report_md)
    print("✅ Report saved → artifacts/portfolio_report.md")

    send_email(report_md, pnl_pct)
    send_telegram(total_val, pnl_pct)

    print("\n🚀 Portfolio Intelligence complete. Check artifacts/ and your notifications.")


USE_GROK_ANALYSIS=True
"""
