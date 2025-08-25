# ====== GRUP AYARLARI ======
GRUP_ID = -4916448425
GRUP_LINK = "https://t.me/+FRzLywk02FszNTQ0"
ILETISIM_MESAJI = "Ücretsiz Vip işlem kanalı, Robot kullanımı için https://t.me/emreguralxc ile iletişime geçebilirsiniz."

# -*- coding: utf-8 -*-
import os, re, time, math, logging, requests, sqlite3
from datetime import datetime, timezone, timedelta
from flask import Flask
from threading import Thread, Timer
import schedule

import telebot
import yfinance as yf
import pandas as pd
import numpy as np

# ====== AYARLAR ======
TOKEN = "8462579006:AAHrb9a3jg6o8aPGTdn0nWnKM3vypuOTsr4"
TR_TZ = timezone(timedelta(hours=3))
bot = telebot.TeleBot(TOKEN, parse_mode="Markdown")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

# ====== GRUP KONTROL FONKSİYONLARI ======
def grup_uye_mi(user_id):
    try:
        uyelik = bot.get_chat_member(GRUP_ID, user_id)
        return uyelik.status in ["member", "administrator", "creator"]
    except:
        return False

def gecikmeli_ozel_mesaj(user_id, kullanici_adi):
    def gonder():
        try:
            ozel_mesaj = f"✅ {kullanici_adi}, analizlerimde memnun kaldıysan\n{ILETISIM_MESAJI}"
            bot.send_message(user_id, ozel_mesaj)
        except:
            pass
    Timer(60, gonder).start()

# ====== SQLITE VERITABANI ======
def init_db():
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, date_added TEXT)''')
    conn.commit()
    conn.close()

def log_user(user_id, username, first_name):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        c.execute("INSERT OR IGNORE INTO users (user_id, username, first_name, date_added) VALUES (?, ?, ?, ?)", 
                  (user_id, username, first_name, today))
        conn.commit()
    except Exception as e:
        logging.error(f"Kullanıcı kaydetme hatası: {e}")
    finally:
        conn.close()

# ====== ORJINAL BOT FONKSİYONLARI ======
def now_tr():
    return datetime.now(TR_TZ).strftime("%Y-%m-%d %H:%M")

def fmt(x, d=2):
    try:
        return f"{float(x):,.{d}f}".replace(",", "_").replace(".", ",").replace("_", ".")
    except Exception:
        return "-"

# ====== SEMBOL EŞLEMELERİ ======
IDX = {
    "us100":"^NDX", "nas100":"^NDX", "nasdaq100":"^NDX", "nq100":"^NDX",
    "spx500":"^GSPC", "us500":"^GSPC", "sp500":"^GSPC",
    "dax40":"^GDAXI", "de40":"^GDAXI",
    "ftse100":"^FTSE", "uk100":"^FTSE",
    "cac40":"^FCHI", "fr40":"^FCHI",
    "hsi50":"^HSI", "hk50":"^HSI",
}
CMD = {
    "xauusd":"GC=F", "altın":"GC=F", "altin":"GC=F", "xau":"GC=F", "gold":"GC=F",
    "xagusd":"SI=F", "gumus":"SI=F", "gümüş":"SI=F", "xag":"SI=F", "silver":"SI=F",
    "wti":"CL=F", "usoil":"CL=F", "petrol":"CL=F",
    "brent":"BZ=F", "ukoil":"BZ=F",
    "natgas":"NG=F", "doğalgaz":"NG=F", "dogalgaz":"NG=F", "ng":"NG=F",
    "copper":"HG=F", "bakir":"HG=F", "bakır":"HG=F",
}
FX_ALIAS = {
    "eurusd":"EURUSD=X","gbpusd":"GBPUSD=X","usdtry":"USDTRY=X","eurtry":"EURTRY=X",
    "usdjpy":"USDJPY=X","audusd":"AUDUSD=X","nzdusd":"NZDUSD=X","usdcad":"USDCAD=X",
    "usdchf":"USDCHF=X"
}

def bist(symbol_text):
    s = symbol_text.upper()
    if s.endswith(".IS"): return s
    if re.fullmatch(r"[A-Z]{4,5}", s): return s + ".IS"
    return None

def resolve(t):
    q = t.strip().lower()
    q2 = q.replace(" ", "")
    if q in {"gram altın","gram altin","gramaltin","gramaltın","gram","ga"}:
        return "GRAMALTIN_TL"
    m = re.match(r"^([a-z]{3})\s*/\s*([a-z]{3})$", q)
    if m:
        return f"{m.group(1).upper()}{m.group(2).upper()}=X"
    if q2 in FX_ALIAS: return FX_ALIAS[q2]
    if q2 in IDX: return IDX[q2]
    if q2 in CMD: return CMD[q2]
    if q2 in {"btc","eth","bnb","sol","xrp","ada","doge","matic","dot","avax","link","trx","ltc","shib"}:
        return q.upper()+"-USD"
    b = bist(q2)
    if b: return b
    return t.strip()

# ====== TEKNİK ANALİZ FONKSİYONLARI ======
def ema(series, n): return series.ewm(span=n, adjust=False).mean()

def rsi(series, n=14):
    delta = series.diff()
    up = (delta.clip(lower=0)).ewm(alpha=1/n, adjust=False).mean()
    down = (-delta.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    rs = up / down
    return 100 - (100 / (1 + rs))

def pivots_daily(df_day):
    H = float(df_day["High"].iloc[-1]); L = float(df_day["Low"].iloc[-1]); C = float(df_day["Close"].iloc[-1])
    P = (H + L + C) / 3.0
    R1 = 2*P - L; S1 = 2*P - H
    R2 = P + (H - L); S2 = P - (H - L)
    return (S1,S2), (R1,R2), P

def trend_pack(df, label):
    c = df["Close"]
    e20 = ema(c, 20); e50 = ema(c, 50)
    e20_last = float(e20.iloc[-1]); e50_last = float(e50.iloc[-1])
    sig = "BUY" if e20_last > e50_last else ("SELL" if e20_last < e50_last else "NEUTRAL")
    r = float(rsi(c).iloc[-1])
    return {"tf":label, "sig":sig, "rsi":r}

def yahoo_hist(sym, interval, period):
    for _ in range(2):
        try:
            df = yf.download(sym, interval=interval, period=period, progress=False, auto_adjust=True)
            if isinstance(df, pd.DataFrame) and not df.empty:
                return df
        except Exception as e:
            logging.warning(f"Yahoo hist hatası {sym}: {e}")
        time.sleep(0.6)
    return None

def get_economic_calendar():
    try:
        url = "https://economic-calendar.tradingview.com/events"
        response = requests.get(url, timeout=10)
        events = response.json()
        today = datetime.now().strftime("%Y-%m-%d")
        important_events = []
        for event in events:
            if event['date'].startswith(today) and event['importance'] in ['high', 'medium']:
                important_events.append(event)
        return important_events[:3]
    except Exception as e:
        logging.error(f"Economic calendar error: {e}")
        return None

def build_advanced_advice(t15, t1h, t4h, rsi_d, symbol):
    trends = [t15, t1h, t4h]
    buy_count = sum(1 for t in trends if t["sig"] == "BUY")
    sell_count = sum(1 for t in trends if t["sig"] == "SELL")
    
    if rsi_d >= 70: rsi_text = "aşırı alım bölgesinde ⚠️"
    elif rsi_d <= 30: rsi_text = "aşürü satım bölgesinde 📉"
    else: rsi_text = "denge bölgesinde ↔️"
    
    symbol_comment = ""
    if 'USD' in symbol or 'EUR' in symbol: symbol_comment = "Döviz çiftlerinde Merkez Bankası açıklamalarına dikkat."
    elif 'XAU' in symbol or 'ALTIN' in symbol: symbol_comment = "Altın, enflasyon verilerinden ve Fed açıklamalarından etkilenir."
    elif 'BTC' in symbol or 'ETH' in symbol: symbol_comment = "Kripto paralar global risk iştahından yoğun etkilenir."
    
    economic_events = get_economic_calendar()
    economic_comment = ""
    if economic_events:
        economic_comment = "\n📅 **Önemli Ekonomik Etkinlikler Bugün:**\n"
        for event in economic_events:
            economic_comment += f"• {event['country']} - {event['title']} ({event['importance'].upper()})\n"
    else:
        economic_comment = "\n📅 Ekonomik takvimde bugün önemli bir etkinlik bulunmuyor.\n"
    
    if sell_count >= 2 and rsi_d <= 40:
        trading_advice = "• Mevcut pozisyonları destek seviyelerine yakın kapatmayı düşünebilirsiniz\n• Yeni short pozisyonlar için direnç seviyelerini bekleyin\n• Stop-loss seviyelerini unutmayın"
    elif buy_count >= 2 and rsi_d >= 60:
        trading_advice = "• Geri çekilmelerde kademeli alım yapılabilir\n• Yeni long pozisyonlar için destek seviyelerini bekleyin\n• Take-profit seviyelerini önceden belirleyin"
    else:
        trading_advice = "• Yan bant hareketi devam ediyor, pozisyon boyutunu sınırlı tutun\n• Breakout durumunda trend yönünde hareket edin\n• Risk yönetimini asla unutmayın"
    
    return f"""
📊 **Teknik Analiz**:
• 15dk: {t15['sig']} (RSI {t15['rsi']:.0f})
• 1sa: {t1h['sig']} (RSI {t1h['rsi']:.0f})
• 4sa: {t4h['sig']} (RSI {t4h['rsi']:.0f})

📈 **Genel Görünüm**: RSI {rsi_text}. {symbol_comment}

{economic_comment}

🎯 **Trading Önerileri**:
{trading_advice}

💡 _Yatırım tavsiyesi değildir. Kendi araştırmanızı yapın._"
"""

def gram_altin_tl():
    px_ons = last_price("^XAU") or last_price("GC=F")
    usdtry = last_price("USDTRY=X")
    if px_ons and usdtry: return (px_ons * usdtry) / 31.1035
    return None

def last_price(sym):
    df = yahoo_hist(sym, "1d", "5d")
    if df is None or df.empty: return None
    return float(df["Close"].iloc[-1])

def analyze_symbol(user_text):
    sym = resolve(user_text)
    if sym == "GRAMALTIN_TL":
        p = gram_altin_tl()
        if p: 
            return {
                "title":"Gram Altın (TL) – model",
                "price": p, "chg": None,
                "pivots": None,
                "trends": None,
                "advice": "Model: XAU(ons)*USDTRY/31.1035. Piyasa sapmaları gerçek kapalıçarşıdan farklı olabilir."
            }
        else: return None

    day = yahoo_hist(sym, "1d", "6mo")
    if day is None or day.empty: 
        if not sym.upper().endswith(".IS"):
            bis = bist(sym)
            if bis:
                sym = bis
                day = yahoo_hist(sym, "1d", "6mo")
        if day is None or day.empty: return None

    last = float(day["Close"].iloc[-1])
    prev = float(day["Close"].iloc[-2]) if len(day) >= 2 else last
    chg = (last - prev) / prev * 100 if prev != 0 else None

    m15 = yahoo_hist(sym, "15m", "7d")
    if m15 is None or m15.empty: m15 = yahoo_hist(sym, "30m", "30d")
    h1 = yahoo_hist(sym, "60m", "60d")
    h4 = yahoo_hist(sym, "60m", "60d")
    if h4 is not None and not h4.empty:
        try: h4 = h4.resample("4H").agg({"Open":"first","High":"max","Low":"min","Close":"last","Volume":"sum"}).dropna()
        except: h4 = None

    t15 = trend_pack(m15, "15dk") if (m15 is not None and not m15.empty) else {"tf":"15dk","sig":"NEUTRAL","rsi":50.0}
    t1h = trend_pack(h1, "1s") if (h1 is not None and not h1.empty) else {"tf":"1s","sig":"NEUTRAL","rsi":50.0}
    t4h = trend_pack(h4, "4s") if (h4 is not None and not h4.empty) else {"tf":"4s","sig":"NEUTRAL","rsi":50.0}

    rsi_d = float(rsi(day["Close"]).iloc[-1])
    S, R, P = pivots_daily(day)

    return {
        "title": sym,
        "price": last,
        "chg": chg,
        "pivots": {"PP": P, "S1": S[0], "S2": S[1], "R1": R[0], "R2": R[1]},
        "trends": {"t15": t15, "t1h": t1h, "t4h": t4h, "rsi_d": rsi_d}
    }

def render(msg_user, res):
    if res is None: return "Veri alınamadı. Yazım örnekleri: us100, spx500, dax40, eur/usd, thy ao, altın, gram altın, xauusd…"

    if "advice" in res and res["advice"]:
        return f"_{now_tr()}_\n{msg_user}\n\n*{res['title']}*\nFiyat: {fmt(res['price'])} TL\n\n{res['advice']}\n\n— Manivest Global"

    t15 = res["trends"]["t15"]; t1h = res["trends"]["t1h"]; t4h = res["trends"]["t4h"]; rsi_d = res["trends"]["rsi_d"]
    
    degisim_metni = f"{res['chg']:+.2f}%" if res['chg'] is not None else 'Veri Yok'
    
    message = f"""
💰 *{res['title']}* - Detaylı Analiz
📅 _{now_tr()}_
👤 {msg_user}

💵 **Güncel Fiyat**: {fmt(res['price'])} {'USD' if 'USD' in res['title'] else 'TL'}
📊 **24s Değişim**: {degisim_metni}
"""
    
    if res["pivots"]:
        P = res["pivots"]
        message += f"""
🎯 **Pivot Noktaları**:
• Pivot: {fmt(P['PP'])}
        
📉 **Destek Seviyeleri**:
  - S1: {fmt(P['S1'])}
  - S2: {fmt(P['S2'])}
  
📈 **Direnç Seviyeleri**:
  - R1: {fmt(P['R1'])}
  - R2: {fmt(P['R2'])}
"""
    
    message += build_advanced_advice(t15, t1h, t4h, rsi_d, res['title'])
    message += "\n\n— Manivest Global Analiz Ekibi"
    return message

# ====== BOT KOMUTLARI ======
@bot.message_handler(commands=["start","help"])
def start_cmd(msg):
    bot.reply_to(msg, """
🎯 *MANİVEST FİNANS BOTU* - Sorgu Kılavuzu

*📈 ENDEKSLER:*
• `us100` / `nas100` - Nasdaq 100
• `spx500` / `us500` - S&P 500  
• `dax40` / `de40` - Alman DAX
• `ftse100` / `uk100` - İngiltere FTSE
• `cac40` / `fr40` - Fransa CAC 40
• `hsi50` / `hk50` - Hong Kong Hang Seng

*🥇 EMTİALAR:*
• `altın` / `xauusd` - Altın (ONS)
• `gümüş` / `xagusd` - Gümüş
• `gram altın` - Gram Altın (TL)
• `wti` / `petrol` - Petrol
• `brent` - Brent Petrol
• `bakır` - Bakır
• `doğalgaz` - Doğalgaz

*💱 DÖVİZ ÇİFTLERİ:*
• `eur/usd` - Euro/Dolar
• `gbp/usd` - Sterlin/Dolar  
• `usd/try` - Dolar/TL
• `eur/try` - Euro/TL
• `usd/jpy` - Dolar/Yen
• `usd/chf` - Dolar/İsviçre Frangı

*📊 HİSSELER:*
• `THYAO` - Türk Hava Yolları
• `SISE` - Şişe Cam
• `AKBNK` - Akbank
• `GARAN` - Garanti Bankası
• `ASELS` - Aselsan
• `BİMAS` - BIM Mağazaları
• *Diğer BIST hisseleri için sadece kod yazın*

*₿ KRİPTO PARALAR:*
• `btc` - Bitcoin
• `eth` - Ethereum
• `xrp` - Ripple
• `ada` - Cardano
• `sol` - Solana
• `bnb` - Binance Coin
• `doge` - Dogecoin

*📍 ÖRNEK SORGULAR:*
`us100`, `altın`, `eur/usd`, `THYAO`, `btc`, `gram altın`

*⚡ ÖZELLİKLER:*
• 15dk/1sa/4sa trend analizi
• RSI göstergesi + Ekonomik takvim
• Destek/direnç seviyeleri
• Gerçek zamanlı fiyatlar

_Bot yatırım tavsiyesi değildir. YTD._
""")

@bot.message_handler(func=lambda m: True, content_types=["text"])
def handle_msg(msg):
    # Grup kontrolü
    if not grup_uye_mi(msg.from_user.id):
        bot.reply_to(msg, f"❌ Botu kullanabilmek için grubumuza katılmalısınız: {GRUP_LINK}")
        return
    
    # Kullanıcıyı kaydet
    if msg.from_user:
        log_user(msg.from_user.id, 
                 msg.from_user.username, 
                 msg.from_user.first_name)
    
    user_tag = f"@{msg.from_user.username}" if (msg.from_user and msg.from_user.username) else (msg.from_user.first_name or "Kullanıcı")
    q = msg.text.strip()
    try:
        res = analyze_symbol(q)
        txt = render(user_tag, res)
        bot.reply_to(msg, txt)
        
        # 1 dakika sonra özel mesaj gönder
        kullanici_adi = msg.from_user.first_name or "Değerli üyemiz"
        gecikmeli_ozel_mesaj(msg.from_user.id, kullanici_adi)
        
    except Exception as e:
        logging.exception("Hata: %s", e)
        bot.reply_to(msg, "Beklenmeyen bir hata oldu. Birazdan tekrar dener misin?")

# ====== ANA ÇALIŞTIRMA ======
if __name__ == "__main__":
    # Veritabanını başlat
    init_db()
    print("Veritabanı hazır...")
    
    print("Bot çalışıyor… (Yahoo Finance tabanlı TA + Ekonomik takvim)")
    bot.infinity_polling(timeout=20, long_polling_timeout=10)