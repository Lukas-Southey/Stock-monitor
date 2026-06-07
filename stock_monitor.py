import yfinance as yf
import pandas as pd
from datetime import datetime
import feedparser
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from openai import OpenAI
import os
import requests
from bs4 import BeautifulSoup

print("✅ Script started successfully on GitHub Actions")

# ===================== YOUR KEYS (Loaded from GitHub Secrets) =====================
XAI_API_KEY = os.getenv("XAI_API_KEY")
GMAIL_EMAIL = os.getenv("GMAIL_EMAIL")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
# ====================================================

# ===================== PORTFOLIO =====================
PORTFOLIO_TICKERS = ["HUB.AX", "TLX.AX", "SUM.NZ", "FRW.NZ", "MCY.NZ", "WTC.AX", "CSL.AX", "EBO.NZ"]
SHARES = [238, 1268, 2493, 1177, 2302, 459, 171, 819]

GOLD_OZ = 2.51
SILVER_OZ = 149

XRO_SOLD_SHARES = 246
XRO_SELL_PRICE_AUD = 79.27
# ====================================================

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

TOP_MARKET = list(dict.fromkeys(TOP_ASX + TOP_NZX))

client = OpenAI(api_key=XAI_API_KEY, base_url="https://api.x.ai/v1")

def get_commodities_and_fx():
    print("🔄 Fetching Gold & Silver from gogold.co.nz...")
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        response = requests.get("https://gogold.co.nz/pricing/", headers=headers, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        text = soup.get_text()

        import re
        gold_match = re.search(r'Gold[^0-9]*?(\d{1,5}(?:\.\d{1,2})?)', text, re.IGNORECASE)
        silver_match = re.search(r'Silver[^0-9]*?(\d{1,5}(?:\.\d{1,2})?)', text, re.IGNORECASE)

        gold_nzd = float(gold_match.group(1)) if gold_match else 7480.0
        silver_nzd = float(silver_match.group(1)) if silver_match else 117.0
    except Exception as e:
        print(f"⚠️ Scraping failed: {e}. Using fallback prices.")
        gold_nzd = 7480.0
        silver_nzd = 117.0

    aud_nzd = 1.215
    print(f"✅ Gold: {gold_nzd} NZD/oz | Silver: {silver_nzd} NZD/oz")
    return {'Gold_NZD': gold_nzd, 'Silver_NZD': silver_nzd, 'AUD_to_NZD': aud_nzd}

def get_portfolio_data(comm_fx):
    data = []
    aud_to_nzd = comm_fx['AUD_to_NZD']

    for i, ticker in enumerate(PORTFOLIO_TICKERS):
        try:
            stock = yf.Ticker(ticker)
            info = stock.info
            price = info.get('currentPrice') or info.get('regularMarketPrice') or info.get('previousClose') or 0
            change_pct = info.get('regularMarketChangePercent') or 0

            price_nzd = round(price * aud_to_nzd, 2) if ticker.endswith('.AX') else round(price, 2)
            value_nzd = round(SHARES[i] * price_nzd, 2)

            data.append({
                'Ticker': ticker,
                'Shares': SHARES[i],
                'Price (NZD)': price_nzd,
                'Change %': round(change_pct, 2),
                'Value (NZD)': value_nzd
            })
        except:
            data.append({'Ticker': ticker, 'Shares': SHARES[i], 'Price (NZD)': "N/A", 'Change %': "N/A", 'Value (NZD)': "N/A"})

    # Metals
    gold_value = round(GOLD_OZ * comm_fx['Gold_NZD'], 2)
    silver_value = round(SILVER_OZ * comm_fx['Silver_NZD'], 2)
    data.append({'Ticker': 'GOLD', 'Shares': GOLD_OZ, 'Price (NZD)': comm_fx['Gold_NZD'], 'Change %': "N/A", 'Value (NZD)': gold_value})
    data.append({'Ticker': 'SILVER', 'Shares': SILVER_OZ, 'Price (NZD)': comm_fx['Silver_NZD'], 'Change %': "N/A", 'Value (NZD)': silver_value})

    # Cash from XRO sale
    xro_cash_nzd = round(XRO_SOLD_SHARES * XRO_SELL_PRICE_AUD * aud_to_nzd, 2)
    data.append({'Ticker': 'CASH (NZD)', 'Shares': '-', 'Price (NZD)': xro_cash_nzd, 'Change %': "N/A", 'Value (NZD)': xro_cash_nzd})

    df = pd.DataFrame(data)
    total_value = round(df['Value (NZD)'].sum(), 2)

    df['Allocation %'] = round((df['Value (NZD)'] / total_value) * 100, 2)
    df = df[['Ticker', 'Shares', 'Price (NZD)', 'Change %', 'Value (NZD)', 'Allocation %']]

    total_row = pd.DataFrame([['**TOTAL**', '', '', '', total_value, 100.00]], columns=df.columns)
    df = pd.concat([df, total_row], ignore_index=True)

    return df, total_value, comm_fx

def get_news_feed(url, limit=6):
    try:
        feed = feedparser.parse(url)
        items = [f"• {entry.title} ({entry.published[:10] if 'published' in entry else 'Recent'})" for entry in feed.entries[:limit]]
        return "\n".join(items) if items else "No recent news."
    except:
        return "Could not fetch news."

def get_business_news():
    nz_news = get_news_feed("https://www.nzherald.co.nz/arc/outboundfeeds/rss/section/business/?outputType=xml", 6)
    au_news = get_news_feed("https://www.afr.com/rss/feed/business", 6)
    return f"""**NZ Business News:**\n{nz_news}\n\n**Australian Business / ASX News:**\n{au_news}"""

def get_nzx_announcements():
    try:
        feed = feedparser.parse("https://nzxplorer.co.nz/rss/announcements")
        recent = []
        check = [t.replace(".NZ","").replace(".AX","") for t in PORTFOLIO_TICKERS]
        for entry in feed.entries[:15]:
            if any(t in entry.title.upper() for t in check):
                recent.append(f"• {entry.title} - {entry.published[:10]}")
        return "\n".join(recent) if recent else "No major announcements."
    except:
        return "Could not fetch NZX announcements."

def get_market_overview():
    overview = []
    for idx in ["^AXJO", "^NZ50"]:
        try:
            data = yf.Ticker(idx).history(period="5d")
            if not data.empty:
                change = ((data['Close'].iloc[-1] / data['Close'].iloc[-2]) - 1) * 100
                overview.append(f"{idx.replace('^','')}: {data['Close'].iloc[-1]:.2f} ({change:+.2f}%)")
        except:
            pass
    return "\n".join(overview) if overview else "Market data limited."

def get_ai_analysis(portfolio_df, total_value, announcements, market_overview, news, comm_fx):
    prompt = f"""You are a top institutional portfolio manager for NZX and ASX markets.

Current date: {datetime.now().strftime('%d %b %Y %H:%M NZST')}

**Portfolio (Total: {total_value:,} NZD):**
{portfolio_df.to_string(index=False)}

**Commodities & FX:**
Gold: {comm_fx['Gold_NZD']} NZD/oz | Silver: {comm_fx['Silver_NZD']} NZD/oz | 1 AUD = {comm_fx['AUD_to_NZD']} NZD

**Market Overview:**
{market_overview}

**Latest Business News:**
{news}

**Recent NZX Announcements:**
{announcements}

Deliver a high-conviction briefing with portfolio review, market regime, 7-day outlook, Buy/Sell/Hold recommendations, and risk management.
End with 'This is not financial advice.'"""

    response = client.chat.completions.create(
        model="grok-4",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.6,
        max_tokens=1600
    )
    return response.choices[0].message.content

def send_email(subject, body):
    try:
        msg = MIMEMultipart()
        msg['From'] = GMAIL_EMAIL
        msg['To'] = RECIPIENT_EMAIL
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(GMAIL_EMAIL, GMAIL_APP_PASSWORD)
        server.send_message(msg)
        server.quit()
        print("✅ Email sent successfully!")
    except Exception as e:
        print(f"❌ Email failed: {e}")

def send_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"})
        print("✅ Telegram sent!")
    except:
        pass

def main():
    print("🚀 Starting Ultra Advanced Grok Institutional Monitor v3.6...")
    comm_fx = get_commodities_and_fx()
    portfolio_df, total_value, comm_fx = get_portfolio_data(comm_fx)
    announcements = get_nzx_announcements()
    market_overview = get_market_overview()
    business_news = get_business_news()

    print("\n📊 Your Full Portfolio (All in NZD):")
    print(portfolio_df)
    print(f"\n💰 **Total Portfolio Value: {total_value:,} NZD**")

    print("\n🪙 Commodities & FX:")
    print(f"Gold: {comm_fx['Gold_NZD']} NZD/oz")
    print(f"Silver: {comm_fx['Silver_NZD']} NZD/oz")
    print(f"1 AUD = {comm_fx['AUD_to_NZD']} NZD")

    print("\n📰 Fetching Latest Business News...")
    print("\n🤖 Generating Deep Institutional Analysis...")
    analysis = get_ai_analysis(portfolio_df, total_value, announcements, market_overview, business_news, comm_fx)

    report_time = datetime.now().strftime('%d %b %Y %H:%M')
    subject = f"📈 Grok Ultra Intelligence Report - {report_time}"

    email_body = f"""Grok NZX/ASX Ultra Intelligence Report - {report_time}

YOUR FULL PORTFOLIO (All in NZD):
{portfolio_df.to_string(index=False)}

🪙 COMMODITIES:
Gold: {comm_fx['Gold_NZD']} NZD/oz | Silver: {comm_fx['Silver_NZD']} NZD/oz | 1 AUD = {comm_fx['AUD_to_NZD']} NZD

MARKET OVERVIEW:
{market_overview}

LATEST BUSINESS NEWS:
{business_news}

NZX ANNOUNCEMENTS:
{announcements}

GROK DEEP ANALYSIS & RECOMMENDATIONS:
{analysis}
"""

    send_email(subject, email_body)
    send_telegram(f"<b>📈 Grok Ultra Intelligence - {report_time}</b>\n\n<pre>Total: {total_value:,} NZD\n{portfolio_df.to_string(index=False)}</pre>\n\n{analysis}")

    print("✅ Report Sent Successfully!")

if __name__ == "__main__":
    main()
