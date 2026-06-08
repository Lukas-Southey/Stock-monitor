#!/usr/bin/env python3
"""
Ultra Advanced Grok NZX/ASX Portfolio Intelligence Monitor v5.0
- Parallel fetching (ThreadPoolExecutor)
- Robust retry logic with exponential backoff
- Daily PnL + Previous Close tracking
- Automatic sector allocation
- Physical gold/silver integration (full net worth)
- Professional HTML email + chunked Telegram
- NZST-aware timestamps
- Enhanced institutional AI prompt (structured output)
- Graceful degradation on any data failure

Designed for GitHub Actions (or local cron). Set all secrets as GitHub Secrets or .env
"""

import os
import time
import logging
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Any, Optional, Tuple

import yfinance as yf
import pandas as pd
import feedparser
import smtplib
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from openai import OpenAI

# ===================== CONFIGURATION (override via GitHub Secrets / env) =====================
XAI_API_KEY = os.getenv("XAI_API_KEY")
GMAIL_EMAIL = os.getenv("GMAIL_EMAIL")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# Portfolio (update these when you buy/sell)
PORTFOLIO_TICKERS: List[str] = ["PME.AX", "TLX.AX", "EBO.NZ", "FRW.NZ", "TNE.AX", "WTC.AX", "CSL.AX"]
SHARES: List[int] = [350, 1918, 619, 277, 400, 459, 271]

# XRO sale cash (already converted in previous runs)
XRO_SOLD_SHARES = 246
XRO_SELL_PRICE_AUD = 79.27

# Your physical precious metals (update via GitHub Secrets if you add/sell)
GOLD_OZ = float(os.getenv("GOLD_OZ", "0"))
SILVER_OZ = float(os.getenv("SILVER_OZ", "0"))
CASH_EXTRA_NZD = float(os.getenv("CASH_EXTRA_NZD", "0.0"))  # Additional bank cash to include in grand total

# Top lists for movers (capped for speed)
TOP_ASX = ["BHP.AX", "CBA.AX", "NEM.AX", "WBC.AX", "ANZ.AX", "MQG.AX", "WES.AX", "RIO.AX", "FMG.AX", "GMG.AX",
           "WDS.AX", "TLS.AX", "TCL.AX", "CSL.AX", "WOW.AX", "RMD.AX", "QBE.AX", "ALL.AX", "COL.AX", "NST.AX",
           "STO.AX", "BXB.AX", "REA.AX", "S32.AX", "CPU.AX", "SUN.AX", "ORG.AX", "IAG.AX", "PME.AX", "SGH.AX",
           "SOL.AX", "BSL.AX", "QAN.AX", "APA.AX", "WTC.AX", "MIN.AX", "MPL.AX", "ALQ.AX", "TLC.AX", "NXT.AX",
           "VCX.AX", "ORI.AX", "TNE.AX", "CAR.AX", "CHC.AX", "SHL.AX", "COH.AX", "XRO.AX", "EVN.AX"]

TOP_NZX = ["FPH.NZ", "IFT.NZ", "MEL.NZ", "AIA.NZ", "MCY.NZ", "CEN.NZ", "MFT.NZ", "POT.NZ", "EBO.NZ", "ATM.NZ",
           "CNU.NZ", "SPK.NZ", "FBU.NZ", "GNZ.NZ", "GNE.NZ", "FRW.NZ", "RYM.NZ", "SUM.NZ", "PCT.NZ", "VHP.NZ",
           "KPG.NZ", "AIR.NZ", "CHI.NZ", "WBC.NZ", "ANZ.NZ", "PFI.NZ", "HGH.NZ", "SKL.NZ", "BGP.NZ", "ARG.NZ",
           "SCL.NZ", "FSF.NZ", "NPH.NZ", "TRA.NZ", "SAN.NZ", "TWR.NZ", "SPG.NZ", "HLG.NZ", "SKC.NZ", "OCA.NZ",
           "THL.NZ", "NZX.NZ", "SKT.NZ", "GTK.NZ", "IPL.NZ", "SKO.NZ", "KMD.NZ", "VCT.NZ", "VSL.NZ", "VGL.NZ"]

TOP_MARKET = list(dict.fromkeys(TOP_ASX + TOP_NZX))[:80]  # cap for speed

client = OpenAI(api_key=XAI_API_KEY, base_url="https://api.x.ai/v1")

# ===================== UTILITIES =====================
def get_nz_time() -> datetime:
    """Return current NZST time (UTC+12, sufficient for June; adjust +13 in summer if needed)."""
    return datetime.utcnow() + timedelta(hours=12)

def robust_yf(func, max_retries: int = 3, base_delay: float = 1.2):
    """Exponential backoff wrapper for yfinance calls."""
    def wrapper(*args, **kwargs):
        last_exc = None
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_exc = e
                if attempt < max_retries - 1:
                    wait = base_delay * (2 ** attempt)
                    print(f"⚠️  {func.__name__} attempt {attempt+1}/{max_retries} failed: {str(e)[:80]}. Retrying in {wait:.1f}s...")
                    time.sleep(wait)
        print(f"❌ {func.__name__} failed after {max_retries} retries.")
        raise last_exc
    return wrapper

@robust_yf
def safe_ticker_info(ticker: str) -> Dict[str, Any]:
    return yf.Ticker(ticker).info

@robust_yf
def safe_history(ticker: str, period: str = "1mo") -> pd.DataFrame:
    return yf.Ticker(ticker).history(period=period)

# ===================== DATA FETCHERS =====================
def get_commodities_and_fx() -> Dict[str, float]:
    print("🔄 Fetching Gold, Silver & AUD/NZD FX...")
    gold_nzd = 7480.0
    silver_nzd = 117.0
    aud_nzd = 1.215

    try:
        gold_usd = safe_ticker_info("GC=F").get('regularMarketPrice') or safe_history("GC=F", "1d")['Close'].iloc[-1]
        silver_usd = safe_ticker_info("SI=F").get('regularMarketPrice') or safe_history("SI=F", "1d")['Close'].iloc[-1]
        aud_nzd_raw = safe_ticker_info("AUDNZD=X").get('regularMarketPrice') or safe_history("AUDNZD=X", "1d")['Close'].iloc[-1]
        aud_nzd = round(float(aud_nzd_raw), 4)
        gold_nzd = round(float(gold_usd) * aud_nzd, 2)
        silver_nzd = round(float(silver_usd) * aud_nzd, 2)
        print(f"✅ Live: Gold {gold_nzd} NZD/oz | Silver {silver_nzd} NZD/oz | 1 AUD = {aud_nzd} NZD")
    except Exception as e:
        print(f"⚠️ Using fallback commodity/FX prices. Error: {e}")

    return {'Gold_NZD': gold_nzd, 'Silver_NZD': silver_nzd, 'AUD_to_NZD': aud_nzd}

def fetch_single_holding(i: int, ticker: str, shares: int, aud_to_nzd: float) -> Dict[str, Any]:
    """Fetch one portfolio holding with daily PnL and sector."""
    try:
        info = safe_ticker_info(ticker)
        price = info.get('currentPrice') or info.get('regularMarketPrice') or info.get('previousClose', 0)
        change_pct = info.get('regularMarketChangePercent', 0)
        prev_close = info.get('previousClose', price)
        sector = info.get('sector', 'Unknown')

        if ticker.endswith('.AX'):
            price_nzd = round(float(price) * aud_to_nzd, 2)
            prev_nzd = round(float(prev_close) * aud_to_nzd, 2)
        else:
            price_nzd = round(float(price), 2)
            prev_nzd = round(float(prev_close), 2)

        value_nzd = round(shares * price_nzd, 2)
        prev_value_nzd = round(shares * prev_nzd, 2)
        daily_pnl = round(value_nzd - prev_value_nzd, 2)
        daily_pct = round(((price_nzd / prev_nzd) - 1) * 100, 2) if prev_nzd > 0 else 0.0

        return {
            'Ticker': ticker,
            'Shares': shares,
            'Price (NZD)': price_nzd,
            'Change %': round(float(change_pct), 2),
            'Value (NZD)': value_nzd,
            'Prev Value (NZD)': prev_value_nzd,
            'Daily PnL (NZD)': daily_pnl,
            'Daily %': daily_pct,
            'Sector': sector
        }
    except Exception as e:
        print(f"❌ Error on {ticker}: {e}")
        return {
            'Ticker': ticker, 'Shares': shares, 'Price (NZD)': 0, 'Change %': 0,
            'Value (NZD)': 0, 'Prev Value (NZD)': 0, 'Daily PnL (NZD)': 0, 'Daily %': 0, 'Sector': 'Error'
        }

def get_portfolio_data(comm_fx: Dict[str, float]) -> Tuple[pd.DataFrame, float, float, float, float, Dict[str, float]]:
    print("🔄 Fetching portfolio prices & daily PnL (parallel)...")
    aud_to_nzd = comm_fx['AUD_to_NZD']
    data: List[Dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [
            executor.submit(fetch_single_holding, i, ticker, SHARES[i], aud_to_nzd)
            for i, ticker in enumerate(PORTFOLIO_TICKERS)
        ]
        for future in as_completed(futures):
            data.append(future.result())

    df = pd.DataFrame(data)

    # Restore original ticker order
    order_map = {t: i for i, t in enumerate(PORTFOLIO_TICKERS)}
    df['order'] = df['Ticker'].map(order_map)
    df = df.sort_values('order').drop(columns=['order']).reset_index(drop=True)

    # Coerce numeric columns (handles any partial failures)
    for col in ['Price (NZD)', 'Value (NZD)', 'Prev Value (NZD)', 'Daily PnL (NZD)']:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    # XRO sale cash row
    xro_cash_nzd = round(XRO_SOLD_SHARES * XRO_SELL_PRICE_AUD * aud_to_nzd, 2)
    cash_row = pd.DataFrame([{
        'Ticker': 'CASH (XRO sale)', 'Shares': '-', 'Price (NZD)': xro_cash_nzd,
        'Change %': 0, 'Value (NZD)': xro_cash_nzd, 'Prev Value (NZD)': xro_cash_nzd,
        'Daily PnL (NZD)': 0, 'Daily %': 0, 'Sector': 'Cash'
    }])
    df = pd.concat([df, cash_row], ignore_index=True)

    total_value = round(df['Value (NZD)'].sum(), 2)
    total_prev = round(df['Prev Value (NZD)'].sum(), 2)
    daily_pnl_total = round(total_value - total_prev, 2)
    daily_portfolio_pct = round((daily_pnl_total / total_prev * 100), 2) if total_prev > 0 else 0.0

    df['Allocation %'] = round((df['Value (NZD)'] / total_value * 100), 2) if total_value > 0 else 0.0

    print(f"✅ Portfolio fetched. Total stocks+cash: {total_value:,.2f} NZD | Daily PnL: {daily_pnl_total:+,.2f} ({daily_portfolio_pct:+.2f}%)")
    return df, total_value, total_prev, daily_pnl_total, daily_portfolio_pct, comm_fx

def get_sector_allocation(df: pd.DataFrame) -> str:
    stock_df = df[~df['Ticker'].str.contains('CASH|TOTAL', case=False, na=False)].copy()
    if stock_df.empty or stock_df['Value (NZD)'].sum() == 0:
        return "Sector data unavailable"
    sector_sum = stock_df.groupby('Sector')['Value (NZD)'].sum().sort_values(ascending=False)
    total = sector_sum.sum()
    lines = [f"• {s}: {v:,.0f} NZD ({v/total*100:.1f}%)" for s, v in sector_sum.items()]
    return "\n".join(lines)

def get_metals_value(comm_fx: Dict[str, float]) -> Tuple[float, float, float]:
    gold_val = round(GOLD_OZ * comm_fx['Gold_NZD'], 2)
    silver_val = round(SILVER_OZ * comm_fx['Silver_NZD'], 2)
    return gold_val, silver_val, gold_val + silver_val

def get_top_movers() -> str:
    print("🔄 Calculating Top Movers (parallel, capped at 80)...")
    movers: List[Tuple[str, float, float]] = []

    def fetch_mover(t: str) -> Optional[Tuple[str, float, float]]:
        try:
            hist = safe_history(t, "1mo")
            if len(hist) >= 5:
                week = ((hist['Close'].iloc[-1] / hist['Close'].iloc[-5]) - 1) * 100
                month = ((hist['Close'].iloc[-1] / hist['Close'].iloc[0]) - 1) * 100
                return (t, round(week, 2), round(month, 2))
        except:
            return None
        return None

    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = {executor.submit(fetch_mover, t): t for t in TOP_MARKET}
        for fut in as_completed(futures):
            res = fut.result()
            if res:
                movers.append(res)

    week_top = sorted(movers, key=lambda x: x[1], reverse=True)[:10]
    month_top = sorted(movers, key=lambda x: x[2], reverse=True)[:10]

    week_str = "\n".join([f"{t}: {chg:+.2f}% (7d)" for t, chg, _ in week_top])
    month_str = "\n".join([f"{t}: {chg:+.2f}% (30d)" for t, _, chg in month_top])
    return f"**Top 10 Weekly Movers:**\n{week_str}\n\n**Top 10 Monthly Movers:**\n{month_str}"

def get_news_feed(url: str, limit: int = 6) -> str:
    try:
        feed = feedparser.parse(url)
        items = []
        for entry in feed.entries[:limit]:
            pub = entry.get('published', 'Recent')[:10] if 'published' in entry else 'Recent'
            items.append(f"• {entry.title} ({pub})")
        return "\n".join(items) if items else "No recent items."
    except Exception as e:
        return f"News feed error: {str(e)[:60]}"

def get_business_news() -> str:
    nz = get_news_feed("https://www.nzherald.co.nz/arc/outboundfeeds/rss/section/business/?outputType=xml", 5)
    au = get_news_feed("https://www.afr.com/rss/feed/business", 5)
    return f"**NZ Business News:**\n{nz}\n\n**Australian Business / ASX News:**\n{au}"

def get_nzx_announcements() -> str:
    try:
        feed = feedparser.parse("https://nzxplorer.co.nz/rss/announcements")
        check = [t.replace(".NZ", "").replace(".AX", "") for t in PORTFOLIO_TICKERS]
        recent = []
        for entry in feed.entries[:12]:
            title_upper = entry.title.upper()
            if any(t in title_upper for t in check):
                pub = entry.get('published', '')[:10]
                recent.append(f"• {entry.title} - {pub}")
        return "\n".join(recent) if recent else "No portfolio-relevant NZX announcements in last batch."
    except Exception as e:
        return f"NZX announcements error: {str(e)[:60]}"

def get_market_overview() -> str:
    try:
        indices = ["^AXJO", "^NZ50"]
        hist = yf.download(indices, period="5d", progress=False, group_by='ticker')
        lines = []
        for idx in indices:
            try:
                close = hist[idx]['Close'].iloc[-1]
                prev = hist[idx]['Close'].iloc[-2]
                chg = ((close / prev) - 1) * 100
                lines.append(f"{idx.replace('^','')}: {close:.2f} ({chg:+.2f}%)")
            except:
                pass
        return "\n".join(lines) if lines else "Market data limited."
    except Exception as e:
        return f"Market overview error: {str(e)[:60]}"

# ===================== AI ANALYSIS =====================
def get_ai_analysis(
    portfolio_df: pd.DataFrame,
    total_value: float,
    daily_pnl_total: float,
    daily_portfolio_pct: float,
    sector_alloc: str,
    gold_val: float,
    silver_val: float,
    metals_total: float,
    grand_total: float,
    announcements: str,
    market_overview: str,
    news: str,
    movers: str,
    comm_fx: Dict[str, float]
) -> str:
    nz_now = get_nz_time()
    prompt = f"""You are a senior institutional portfolio manager specializing in NZX and ASX equities with 20+ years experience.

Current NZ time: {nz_now.strftime('%d %b %Y %H:%M NZST')}

**PORTFOLIO SNAPSHOT (Total Stocks + Cash: {total_value:,.0f} NZD)**
{portfolio_df[['Ticker','Shares','Price (NZD)','Change %','Value (NZD)','Allocation %','Daily PnL (NZD)','Daily %']].to_string(index=False)}

**DAILY PERFORMANCE**
Portfolio Daily PnL: {daily_pnl_total:+,.2f} NZD ({daily_portfolio_pct:+.2f}%)

**SECTOR ALLOCATION (Stocks only)**
{sector_alloc}

**PRECIOUS METALS (Your Physical Holdings)**
Gold: {GOLD_OZ} oz @ {comm_fx['Gold_NZD']} NZD/oz = {gold_val:,.2f} NZD
Silver: {SILVER_OZ} oz @ {comm_fx['Silver_NZD']} NZD/oz = {silver_val:,.2f} NZD
Metals subtotal: {metals_total:,.2f} NZD
**GRAND TOTAL WEALTH (incl. metals + extra cash): {grand_total:,.0f} NZD**

**COMMODITIES & FX**
Gold: {comm_fx['Gold_NZD']} NZD/oz | Silver: {comm_fx['Silver_NZD']} NZD/oz | 1 AUD = {comm_fx['AUD_to_NZD']} NZD

**MARKET OVERVIEW**
{market_overview}

**LATEST BUSINESS NEWS (NZ + AU)**
{news}

**TOP MOVERS (ASX/NZX)**
{movers}

**NZX ANNOUNCEMENTS (relevant to holdings)**
{announcements}

Deliver a high-conviction, institutional-quality briefing. Use these exact section headings in Markdown:

## 1. Portfolio Snapshot & Daily Performance
## 2. Sector & Asset Allocation Review (incl. metals hedge %)
## 3. Market Regime & Key Macro Drivers (RBNZ/RBA, commodities, geopolitics)
## 4. Holdings Insights & Actionable Recommendations (Buy / Hold / Reduce / Watch for each major position or group)
## 5. 7-Day Outlook & Conviction Levels (directional bias + key levels)
## 6. Risk Management & Portfolio Health (concentration, volatility, hedge effectiveness)
## 7. Key Risks & Asymmetric Opportunities

Be direct, data-driven, and specific to the tickers shown. Mention gold/silver positioning where relevant. 
End exactly with: "This is not financial advice. Past performance is not indicative of future results."
"""
    try:
        response = client.chat.completions.create(
            model="grok-4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.55,
            max_tokens=2100
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"AI analysis failed: {e}\n\nPlease check xAI credits and API key."

# ===================== NOTIFICATIONS =====================
def send_email(subject: str, html_body: str) -> None:
    try:
        msg = MIMEMultipart('alternative')
        msg['From'] = GMAIL_EMAIL
        msg['To'] = RECIPIENT_EMAIL
        msg['Subject'] = subject

        # Plain text fallback (simple version)
        text_body = html_body.replace('<br>', '\n').replace('<b>', '').replace('</b>', '')[:3000]
        msg.attach(MIMEText(text_body, 'plain'))
        msg.attach(MIMEText(html_body, 'html'))

        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(GMAIL_EMAIL, GMAIL_APP_PASSWORD)
        server.send_message(msg)
        server.quit()
        print("✅ Email sent successfully!")
    except Exception as e:
        print(f"❌ Email failed: {e}")

def send_telegram(message: str, parse_mode: str = "HTML") -> None:
    """Send, with chunking for long messages."""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        max_len = 3800
        if len(message) <= max_len:
            requests.post(url, json={"chat_id": CHAT_ID, "text": message, "parse_mode": parse_mode}, timeout=15)
        else:
            parts = [message[i:i+max_len] for i in range(0, len(message), max_len)]
            for idx, part in enumerate(parts):
                chunk = f"<b>Part {idx+1}/{len(parts)}</b>\n{part}"
                requests.post(url, json={"chat_id": CHAT_ID, "text": chunk, "parse_mode": parse_mode}, timeout=15)
                time.sleep(0.8)
        print("✅ Telegram sent!")
    except Exception as e:
        print(f"❌ Telegram failed: {e}")

def generate_html_email(
    report_time: str,
    portfolio_df: pd.DataFrame,
    total_value: float,
    daily_pnl_total: float,
    daily_portfolio_pct: float,
    sector_alloc: str,
    gold_val: float,
    silver_val: float,
    metals_total: float,
    grand_total: float,
    market_overview: str,
    business_news: str,
    movers: str,
    announcements: str,
    analysis: str,
    comm_fx: Dict[str, float]
) -> str:
    """Professional HTML email with color-coded table."""

    def make_table_html(df: pd.DataFrame) -> str:
        display_cols = ['Ticker', 'Shares', 'Price (NZD)', 'Change %', 'Value (NZD)', 'Allocation %', 'Daily PnL (NZD)', 'Daily %']
        df2 = df[display_cols].copy()

        html = '<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse; width:100%; font-family:Arial, sans-serif; font-size:11px;">'
        html += '<tr style="background-color:#1a73e8; color:white;">'
        for col in display_cols:
            html += f'<th style="padding:6px 8px; text-align:left;">{col}</th>'
        html += '</tr>'

        for _, row in df2.iterrows():
            is_total = 'TOTAL' in str(row['Ticker']).upper() or 'CASH' in str(row['Ticker']).upper()
            bg = '#e8f0fe' if is_total else ('#f8f9fa' if _ % 2 == 0 else '#ffffff')
            html += f'<tr style="background-color:{bg};">'
            for col in display_cols:
                val = row[col]
                style = 'padding:5px 8px; border:1px solid #ddd;'
                if col in ['Change %', 'Daily %'] and isinstance(val, (int, float)):
                    color = '#0a7e3a' if val >= 0 else '#d32f2f'
                    style += f' color:{color}; font-weight:bold;'
                elif col == 'Daily PnL (NZD)' and isinstance(val, (int, float)):
                    color = '#0a7e3a' if val >= 0 else '#d32f2f'
                    style += f' color:{color};'
                html += f'<td style="{style}">{val}</td>'
            html += '</tr>'
        html += '</table>'
        return html

    portfolio_table = make_table_html(portfolio_df)

    daily_color = '#0a7e3a' if daily_pnl_total >= 0 else '#d32f2f'

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Grok Ultra Intelligence Report</title></head>
<body style="font-family:Arial, Helvetica, sans-serif; background:#f4f6f8; padding:20px; color:#222;">
<div style="max-width:980px; margin:auto; background:white; border-radius:8px; box-shadow:0 2px 8px rgba(0,0,0,0.08); overflow:hidden;">
  <div style="background:linear-gradient(90deg,#1a73e8,#0d47a1); color:white; padding:16px 24px;">
    <h1 style="margin:0; font-size:22px;">📈 Grok Ultra Intelligence Report</h1>
    <p style="margin:4px 0 0; opacity:0.95;">{report_time} NZST • NZX + ASX + Precious Metals</p>
  </div>

  <div style="padding:24px;">
    <h2 style="color:#1a73e8; border-bottom:2px solid #1a73e8; padding-bottom:6px;">Portfolio & Daily Performance</h2>
    {portfolio_table}

    <p style="font-size:15px; margin:16px 0 8px;">
      <b>💰 Stocks + Cash Total:</b> {total_value:,.2f} NZD &nbsp;&nbsp;
      <b style="color:{daily_color};">Daily PnL: {daily_pnl_total:+,.2f} NZD ({daily_portfolio_pct:+.2f}%)</b>
    </p>

    <h2 style="color:#1a73e8; border-bottom:2px solid #1a73e8; padding-bottom:6px; margin-top:28px;">Sector Allocation (Stocks)</h2>
    <pre style="background:#f8f9fa; padding:12px; border-radius:6px; font-size:12px; line-height:1.45;">{sector_alloc}</pre>

    <h2 style="color:#1a73e8; border-bottom:2px solid #1a73e8; padding-bottom:6px; margin-top:28px;">Precious Metals (Physical Holdings)</h2>
    <p style="font-size:14px; line-height:1.6;">
      🪙 <b>Gold:</b> {GOLD_OZ} oz × {comm_fx['Gold_NZD']} NZD/oz = <b>{gold_val:,.2f} NZD</b><br>
      🪙 <b>Silver:</b> {SILVER_OZ} oz × {comm_fx['Silver_NZD']} NZD/oz = <b>{silver_val:,.2f} NZD</b><br>
      <b>Metals Subtotal:</b> {metals_total:,.2f} NZD &nbsp;&nbsp; <b>Grand Total Wealth:</b> <span style="color:#1a73e8; font-size:16px;">{grand_total:,.2f} NZD</span>
    </p>

    <h2 style="color:#1a73e8; border-bottom:2px solid #1a73e8; padding-bottom:6px; margin-top:28px;">Commodities & FX</h2>
    <p>Gold: {comm_fx['Gold_NZD']} NZD/oz | Silver: {comm_fx['Silver_NZD']} NZD/oz | 1 AUD = {comm_fx['AUD_to_NZD']} NZD</p>

    <h2 style="color:#1a73e8; border-bottom:2px solid #1a73e8; padding-bottom:6px; margin-top:28px;">Market Overview</h2>
    <pre style="background:#f8f9fa; padding:12px; border-radius:6px;">{market_overview}</pre>

    <h2 style="color:#1a73e8; border-bottom:2px solid #1a73e8; padding-bottom:6px; margin-top:28px;">Latest Business News</h2>
    <pre style="background:#f8f9fa; padding:12px; border-radius:6px; font-size:12px;">{business_news}</pre>

    <h2 style="color:#1a73e8; border-bottom:2px solid #1a73e8; padding-bottom:6px; margin-top:28px;">Top Movers</h2>
    <pre style="background:#f8f9fa; padding:12px; border-radius:6px; font-size:12px;">{movers}</pre>

    <h2 style="color:#1a73e8; border-bottom:2px solid #1a73e8; padding-bottom:6px; margin-top:28px;">NZX Announcements (Portfolio Relevant)</h2>
    <pre style="background:#f8f9fa; padding:12px; border-radius:6px; font-size:12px;">{announcements}</pre>

    <h2 style="color:#1a73e8; border-bottom:2px solid #1a73e8; padding-bottom:6px; margin-top:28px;">Grok Deep Institutional Analysis</h2>
    <div style="background:#fafafa; padding:16px; border-left:4px solid #1a73e8; border-radius:4px; font-size:13.5px; line-height:1.55;">
      {analysis.replace(chr(10), '<br>')}
    </div>
  </div>

  <div style="background:#f4f6f8; padding:14px 24px; font-size:11px; color:#555; text-align:center;">
    Generated by Grok Ultra Monitor v5.0 • This is <b>NOT</b> financial advice. Data via yfinance + public feeds. Verify before trading.
  </div>
</div>
</body></html>"""
    return html

# ===================== MAIN =====================
def main():
    print("🚀 Starting Ultra Advanced Grok Institutional Monitor v5.0 on GitHub Actions...")
    nz_now = get_nz_time()
    report_time = nz_now.strftime('%d %b %Y %H:%M')

    # 1. Core data
    comm_fx = get_commodities_and_fx()
    portfolio_df, total_value, total_prev, daily_pnl_total, daily_portfolio_pct, comm_fx = get_portfolio_data(comm_fx)

    # 2. Enrichments
    sector_alloc = get_sector_allocation(portfolio_df)
    gold_val, silver_val, metals_total = get_metals_value(comm_fx)
    grand_total = round(total_value + metals_total + CASH_EXTRA_NZD, 2)

    announcements = get_nzx_announcements()
    market_overview = get_market_overview()
    business_news = get_business_news()
    movers = get_top_movers()

    # 3. AI
    print("\n🤖 Generating Deep Institutional Analysis with Grok-4...")
    analysis = get_ai_analysis(
        portfolio_df, total_value, daily_pnl_total, daily_portfolio_pct,
        sector_alloc, gold_val, silver_val, metals_total, grand_total,
        announcements, market_overview, business_news, movers, comm_fx
    )

    # 4. Notifications
    subject = f"📈 Grok Ultra Intelligence Report - {report_time} NZST"

    # HTML Email (rich)
    email_html = generate_html_email(
        report_time, portfolio_df, total_value, daily_pnl_total, daily_portfolio_pct,
        sector_alloc, gold_val, silver_val, metals_total, grand_total,
        market_overview, business_news, movers, announcements, analysis, comm_fx
    )
    send_email(subject, email_html)

    # Telegram (compact + full analysis, chunked)
    telegram_summary = f"""<b>📈 Grok Ultra Intelligence - {report_time} NZST</b>

<b>💰 Grand Total Wealth: {grand_total:,.0f} NZD</b>
Stocks+Cash: {total_value:,.0f} | Metals: {metals_total:,.0f} | Daily PnL: <b>{daily_pnl_total:+,.0f} ({daily_portfolio_pct:+.2f}%)</b>

<b>Top Changes:</b>
{portfolio_df.sort_values('Daily %', ascending=False).head(5)[['Ticker','Daily %']].to_string(index=False, header=False)}

<b>Market:</b> {market_overview.replace(chr(10),' | ')}

<b>Analysis:</b>
{analysis}"""

    send_telegram(telegram_summary)

    print("\n✅ Ultra Report Complete & Delivered!")
    print(f"   Grand Total: {grand_total:,.2f} NZD | Daily: {daily_pnl_total:+,.2f} NZD ({daily_portfolio_pct:+.2f}%)")

if __name__ == "__main__":
    main()
