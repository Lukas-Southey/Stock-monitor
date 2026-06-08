import os
import time
import logging
from datetime import datetime, timedelta, timezone
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

# ===================== YOUR KEYS =====================
XAI_API_KEY = "xai-m87kSm3RRahN6DVxxBoHw3qSd64qxELzwW9jApUl8heor7fMnB5p1rIMthihCohVC5wkJ0ihXzkHwMQu"

GMAIL_EMAIL = "maximuslucius01@gmail.com"
GMAIL_APP_PASSWORD = "kvku biww qozn jcfo"
RECIPIENT_EMAIL = "lukassouthey@outlook.co.nz"

TELEGRAM_TOKEN = "8879289893:AAEMYMdY5E6vcQB-sDG-lt2EwSlovZYorDY"
CHAT_ID = "126949119"
# ====================================================

# ===================== PORTFOLIO =====================
PORTFOLIO_TICKERS: List[str] = ["PME.AX", "TLX.AX", "EBO.NZ", "TNE.AX", "WTC.AX"]
SHARES: List[int] = [410, 1918, 619, 400, 459]

# ===================== CASH TRACKING =====================
STARTING_CASH_NZD = 250000.0
XRO_SOLD_SHARES = 246
XRO_SELL_PRICE_AUD = 79.27
CASH_EXTRA_NZD = 0.0

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

TOP_MARKET = list(dict.fromkeys(TOP_ASX + TOP_NZX))[:80]

client = OpenAI(api_key=XAI_API_KEY, base_url="https://api.x.ai/v1")

# ===================== UTILITIES =====================
def get_nz_time() -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=12)

def robust_yf(func, max_retries: int = 3, base_delay: float = 1.2):
    def wrapper(*args, **kwargs):
        last_exc = None
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_exc = e
                if attempt < max_retries - 1:
                    wait = base_delay * (2 ** attempt)
                    print(f"⚠️ {func.__name__} attempt {attempt+1} failed. Retrying in {wait:.1f}s...")
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
    print("🔄 Fetching AUD/NZD FX...")
    aud_nzd = 1.215
    try:
        aud_nzd_raw = safe_ticker_info("AUDNZD=X").get('regularMarketPrice') or safe_history("AUDNZD=X", "1d")['Close'].iloc[-1]
        aud_nzd = round(float(aud_nzd_raw), 4)
        print(f"✅ 1 AUD = {aud_nzd} NZD")
    except Exception as e:
        print(f"⚠️ Using fallback FX. Error: {e}")
    return {'AUD_to_NZD': aud_nzd}

def fetch_single_holding(i: int, ticker: str, shares: int, aud_to_nzd: float) -> Dict[str, Any]:
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

def get_portfolio_data(comm_fx: Dict[str, float]) -> Tuple[pd.DataFrame, float, float, float, float]:
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
    order_map = {t: i for i, t in enumerate(PORTFOLIO_TICKERS)}
    df['order'] = df['Ticker'].map(order_map)
    df = df.sort_values('order').drop(columns=['order']).reset_index(drop=True)

    for col in ['Price (NZD)', 'Value (NZD)', 'Prev Value (NZD)', 'Daily PnL (NZD)']:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    # ===================== CASH CALCULATION =====================
    total_stocks_value = df['Value (NZD)'].sum()
    xro_proceeds_nzd = round(XRO_SOLD_SHARES * XRO_SELL_PRICE_AUD * aud_to_nzd, 2)
    current_cash_nzd = round(STARTING_CASH_NZD - total_stocks_value + xro_proceeds_nzd + CASH_EXTRA_NZD, 2)

    cash_row = pd.DataFrame([{
        'Ticker': 'CASH',
        'Shares': '-',
        'Price (NZD)': current_cash_nzd,
        'Change %': 0,
        'Value (NZD)': current_cash_nzd,
        'Prev Value (NZD)': current_cash_nzd,
        'Daily PnL (NZD)': 0,
        'Daily %': 0,
        'Sector': 'Cash'
    }])
    df = pd.concat([df, cash_row], ignore_index=True)

    total_value = round(df['Value (NZD)'].sum(), 2)
    total_prev = round(df['Prev Value (NZD)'].sum(), 2)
    daily_pnl_total = round(total_value - total_prev, 2)
    daily_portfolio_pct = round((daily_pnl_total / total_prev * 100), 2) if total_prev > 0 else 0.0
    df['Allocation %'] = round((df['Value (NZD)'] / total_value * 100), 2) if total_value > 0 else 0.0

    print(f"✅ Portfolio fetched. Total (Stocks + Cash): {total_value:,.2f} NZD | Daily PnL: {daily_pnl_total:+,.2f} ({daily_portfolio_pct:+.2f}%)")
    return df, total_value, total_prev, daily_pnl_total, daily_portfolio_pct

def get_sector_allocation(df: pd.DataFrame) -> str:
    stock_df = df[~df['Ticker'].str.contains('CASH', case=False, na=False)].copy()
    if stock_df.empty or stock_df['Value (NZD)'].sum() == 0:
        return "Sector data unavailable"
    sector_sum = stock_df.groupby('Sector')['Value (NZD)'].sum().sort_values(ascending=False)
    total = sector_sum.sum()
    return "\n".join([f"• {s}: {v:,.0f} NZD ({v/total*100:.1f}%)" for s, v in sector_sum.items()])

def get_top_movers() -> str:
    print("🔄 Calculating Top Movers...")
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

def get_business_news() -> str:
    try:
        nz = feedparser.parse("https://www.nzherald.co.nz/arc/outboundfeeds/rss/section/business/?outputType=xml")
        au = feedparser.parse("https://www.afr.com/rss/feed/business")
        nz_items = [f"• {e.title}" for e in nz.entries[:5]]
        au_items = [f"• {e.title}" for e in au.entries[:5]]
        return f"**NZ Business News:**\n" + "\n".join(nz_items) + "\n\n**Australian Business News:**\n" + "\n".join(au_items)
    except:
        return "Business news temporarily unavailable."

def get_nzx_announcements() -> str:
    try:
        feed = feedparser.parse("https://nzxplorer.co.nz/rss/announcements")
        check = [t.replace(".NZ", "").replace(".AX", "") for t in PORTFOLIO_TICKERS]
        recent = [f"• {entry.title}" for entry in feed.entries[:12] if any(t in entry.title.upper() for t in check)]
        return "\n".join(recent) if recent else "No relevant NZX announcements."
    except:
        return "NZX announcements error."

def get_market_overview() -> str:
    try:
        indices = ["^AXJO", "^NZ50"]
        hist = yf.download(indices, period="5d", progress=False, group_by='ticker')
        lines = []
        for idx in indices:
            close = hist[idx]['Close'].iloc[-1]
            prev = hist[idx]['Close'].iloc[-2]
            chg = ((close / prev) - 1) * 100
            lines.append(f"{idx.replace('^','')}: {close:.2f} ({chg:+.2f}%)")
        return "\n".join(lines)
    except:
        return "Market overview limited."

# ===================== AI ANALYSIS =====================
def get_ai_analysis(portfolio_df, total_value, daily_pnl_total, daily_portfolio_pct,
                    sector_alloc, announcements, market_overview, news, movers) -> str:
    nz_now = get_nz_time()
    prompt = f"""You are a senior institutional portfolio manager specializing in NZX and ASX equities with 20+ years experience.

Current NZ time: {nz_now.strftime('%d %b %Y %H:%M NZST')}

**PORTFOLIO SNAPSHOT (Total Stocks + Cash: {total_value:,.0f} NZD)**
{portfolio_df[['Ticker','Shares','Price (NZD)','Change %','Value (NZD)','Allocation %','Daily PnL (NZD)','Daily %']].to_string(index=False)}

**DAILY PERFORMANCE**
Portfolio Daily PnL: {daily_pnl_total:+,.2f} NZD ({daily_portfolio_pct:+.2f}%)

**SECTOR ALLOCATION**
{sector_alloc}

**MARKET OVERVIEW**
{market_overview}

**LATEST BUSINESS NEWS**
{news}

**TOP MOVERS**
{movers}

**NZX ANNOUNCEMENTS**
{announcements}

Deliver a high-conviction institutional briefing using these exact headings:

## 1. Portfolio Snapshot & Daily Performance
## 2. Sector Allocation Review
## 3. Market Regime & Key Drivers
## 4. Holdings Insights & Recommendations (Buy / Hold / Reduce / Watch)
## 5. 7-Day Outlook & Conviction Levels
## 6. Risk Management & Portfolio Health
## 7. Key Risks & Opportunities

Be direct, data-driven, and specific to these tickers.
End with: "This is not financial advice."
"""

    try:
        response = client.chat.completions.create(
            model="grok-4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.55,
            max_tokens=2000
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"AI analysis failed: {e}"

# ===================== NOTIFICATIONS =====================
def send_email(subject: str, html_body: str) -> None:
    try:
        msg = MIMEMultipart('alternative')
        msg['From'] = GMAIL_EMAIL
        msg['To'] = RECIPIENT_EMAIL
        msg['Subject'] = subject
        msg.attach(MIMEText(html_body.replace('<br>', '\n')[:3000], 'plain'))
        msg.attach(MIMEText(html_body, 'html'))
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(GMAIL_EMAIL, GMAIL_APP_PASSWORD)
        server.send_message(msg)
        server.quit()
        print("✅ Email sent!")
    except Exception as e:
        print(f"❌ Email failed: {e}")

def send_telegram(message: str) -> None:
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        max_len = 3800
        if len(message) <= max_len:
            requests.post(url, json={"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}, timeout=15)
        else:
            for i, part in enumerate([message[i:i+max_len] for i in range(0, len(message), max_len)]):
                requests.post(url, json={"chat_id": CHAT_ID, "text": f"<b>Part {i+1}</b>\n{part}", "parse_mode": "HTML"}, timeout=15)
                time.sleep(0.7)
        print("✅ Telegram sent!")
    except Exception as e:
        print(f"❌ Telegram failed: {e}")

# ===================== MAIN =====================
def main():
    print("🚀 Starting Ultra Advanced Grok NZX/ASX Monitor...")
    nz_now = get_nz_time()
    report_time = nz_now.strftime('%d %b %Y %H:%M')

    comm_fx = get_commodities_and_fx()
    portfolio_df, total_value, total_prev, daily_pnl_total, daily_portfolio_pct = get_portfolio_data(comm_fx)

    sector_alloc = get_sector_allocation(portfolio_df)
    announcements = get_nzx_announcements()
    market_overview = get_market_overview()
    business_news = get_business_news()
    movers = get_top_movers()

    print("\n🤖 Generating Deep Institutional Analysis with Grok-4...")
    analysis = get_ai_analysis(
        portfolio_df, total_value, daily_pnl_total, daily_portfolio_pct,
        sector_alloc, announcements, market_overview, business_news, movers
    )

    subject = f"📈 Grok Ultra Intelligence Report - {report_time} NZST"

    email_html = f"""<h2>📈 Grok Ultra Intelligence Report - {report_time} NZST</h2>
<b>Portfolio Total (Stocks + Cash):</b> {total_value:,.2f} NZD<br>
<b>Daily PnL:</b> {daily_pnl_total:+,.2f} NZD ({daily_portfolio_pct:+.2f}%)<br><br>
{portfolio_df.to_html(index=False)}<br><br>
<b>Sector Allocation:</b><br><pre>{sector_alloc}</pre><br>
<b>Market Overview:</b><br><pre>{market_overview}</pre><br>
<b>Analysis:</b><br>{analysis.replace(chr(10), '<br>')}
"""

    send_email(subject, email_html)

    telegram_msg = f"""<b>📈 Grok Ultra Report - {report_time} NZST</b>
<b>Total:</b> {total_value:,.0f} NZD | Daily PnL: {daily_pnl_total:+,.0f} ({daily_portfolio_pct:+.2f}%)
{analysis}"""
    send_telegram(telegram_msg)

    print("✅ Ultra Advanced Report Complete!")

if __name__ == "__main__":
    main()
