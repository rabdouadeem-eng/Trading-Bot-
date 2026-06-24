"""
🤖 بوت إشارات التداول
Binance API → RSI + EMA + MACD → Telegram
"""

import os
import time
import logging
import requests
import ta
import pandas_ta as ta
from datetime import datetime

# ─── إعداد اللوغ ──────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger(__name__)

# ─── إعدادات ──────────────────────────────────────────────
TELEGRAM_TOKEN  = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SYMBOL          = "BTCUSDT"
INTERVAL        = "15m"       # تايم فريم 15 دقيقة
CHECK_EVERY     = 60 * 15     # فحص كل 15 دقيقة

# ─── جلب بيانات الشارت من Binance ────────────────────────
def get_candles(symbol: str, interval: str, limit: int = 100) -> pd.DataFrame:
    url = "https://api.binance.com/api/v3/klines"
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit
    }
    try:
        res = requests.get(url, params=params, timeout=10)
        res.raise_for_status()
        data = res.json()

        df = pd.DataFrame(data, columns=[
            "timestamp", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "trades",
            "taker_buy_base", "taker_buy_quote", "ignore"
        ])
        df["close"] = df["close"].astype(float)
        df["high"]  = df["high"].astype(float)
        df["low"]   = df["low"].astype(float)
        df["open"]  = df["open"].astype(float)
        return df

    except Exception as e:
        logger.error(f"❌ خطأ في جلب البيانات: {e}")
        return pd.DataFrame()


# ─── تحليل المؤشرات ───────────────────────────────────────
def analyze(df: pd.DataFrame) -> dict:
    if df.empty or len(df) < 30:
        return {"signal": "انتظر", "reason": "بيانات غير كافية"}

    close = df["close"]

    # RSI
    rsi_series = ta.rsi(close, length=14)
    rsi = round(float(rsi_series.iloc[-1]), 2) if rsi_series is not None else None

    # EMA
    ema9  = ta.ema(close, length=9)
    ema21 = ta.ema(close, length=21)
    ema9_val  = float(ema9.iloc[-1])  if ema9  is not None else None
    ema21_val = float(ema21.iloc[-1]) if ema21 is not None else None
    ema9_prev  = float(ema9.iloc[-2])  if ema9  is not None else None
    ema21_prev = float(ema21.iloc[-2]) if ema21 is not None else None

    # MACD
    macd_df = ta.macd(close, fast=12, slow=26, signal=9)
    if macd_df is not None and not macd_df.empty:
        macd_val  = float(macd_df.iloc[-1, 0])   # MACD line
        macd_sig  = float(macd_df.iloc[-1, 2])   # Signal line
    else:
        macd_val = macd_sig = None

    current_price = round(float(close.iloc[-1]), 2)

    # ─── منطق الإشارات ────────────────────────────────────
    buy_signals  = 0
    sell_signals = 0
    reasons      = []

    # RSI
    if rsi is not None:
        if rsi < 35:
            buy_signals += 1
            reasons.append(f"RSI={rsi} (تشبع بيع)")
        elif rsi > 65:
            sell_signals += 1
            reasons.append(f"RSI={rsi} (تشبع شراء)")

    # EMA تقاطع
    if all(v is not None for v in [ema9_val, ema21_val, ema9_prev, ema21_prev]):
        if ema9_prev < ema21_prev and ema9_val > ema21_val:
            buy_signals += 1
            reasons.append("EMA9 تقطع EMA21 لفوق")
        elif ema9_prev > ema21_prev and ema9_val < ema21_val:
            sell_signals += 1
            reasons.append("EMA9 تقطع EMA21 لتحت")

    # MACD
    if macd_val is not None and macd_sig is not None:
        if macd_val > macd_sig:
            buy_signals += 1
            reasons.append("MACD إيجابي")
        elif macd_val < macd_sig:
            sell_signals += 1
            reasons.append("MACD سلبي")

    # ─── القرار النهائي ───────────────────────────────────
    sl_pct = 0.015   # Stop Loss 1.5%
    tp_pct = 0.030   # Take Profit 3.0%

    if buy_signals >= 2:
        sl = round(current_price * (1 - sl_pct), 2)
        tp = round(current_price * (1 + tp_pct), 2)
        return {
            "signal":   "شراء 🟢",
            "price":    current_price,
            "sl":       sl,
            "tp":       tp,
            "reasons":  reasons,
            "strength": buy_signals
        }
    elif sell_signals >= 2:
        sl = round(current_price * (1 + sl_pct), 2)
        tp = round(current_price * (1 - tp_pct), 2)
        return {
            "signal":   "بيع 🔴",
            "price":    current_price,
            "sl":       sl,
            "tp":       tp,
            "reasons":  reasons,
            "strength": sell_signals
        }
    else:
        return {
            "signal":  "انتظر ⏳",
            "price":   current_price,
            "reasons": reasons or ["السوق غير واضح"]
        }


# ─── إرسال إشارة على Telegram ────────────────────────────
def send_telegram(message: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("⚠️ TELEGRAM_TOKEN أو CHAT_ID مو مضبوط")
        print(message)  # للتجربة المحلية
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id":    TELEGRAM_CHAT_ID,
        "text":       message,
        "parse_mode": "HTML"
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
        logger.info("✅ إشارة أُرسلت على Telegram")
    except Exception as e:
        logger.error(f"❌ خطأ Telegram: {e}")


# ─── تنسيق الرسالة ────────────────────────────────────────
def format_message(result: dict) -> str:
    now = datetime.now().strftime("%H:%M | %d/%m/%Y")

    if result["signal"] == "انتظر ⏳":
        return (
            f"⏳ <b>BTC/USDT — انتظر</b>\n"
            f"💰 السعر: <b>${result['price']:,}</b>\n"
            f"📊 {' | '.join(result['reasons'])}\n"
            f"🕐 {now}"
        )

    stars = "⭐" * result.get("strength", 1)
    return (
        f"{'🟢' if 'شراء' in result['signal'] else '🔴'} "
        f"<b>إشارة {result['signal']} — BTC/USDT</b> {stars}\n\n"
        f"💰 سعر الدخول: <b>${result['price']:,}</b>\n"
        f"🛑 Stop Loss:  <b>${result['sl']:,}</b>\n"
        f"🎯 Take Profit: <b>${result['tp']:,}</b>\n\n"
        f"📊 الأسباب:\n"
        + "\n".join(f"  • {r}" for r in result['reasons']) +
        f"\n\n⚠️ نفّذ يدوياً على Pionex\n"
        f"🕐 {now}"
    )


# ─── الحلقة الرئيسية ──────────────────────────────────────
def run():
    logger.info("🚀 بوت الإشارات يعمل...")
    send_telegram("🤖 <b>بوت الإشارات شغّال!</b>\nسيراقب BTC/USDT كل 15 دقيقة.")

    last_signal = None

    while True:
        try:
            logger.info(f"🔍 تحليل {SYMBOL} على {INTERVAL}...")
            df     = get_candles(SYMBOL, INTERVAL)
            result = analyze(df)

            logger.info(f"📊 النتيجة: {result['signal']} | السعر: {result.get('price')}")

            # أرسل فقط إذا تغيرت الإشارة (تجنب الإزعاج)
            current_signal = result["signal"]
            if current_signal != last_signal:
                message = format_message(result)
                send_telegram(message)
                last_signal = current_signal

        except Exception as e:
            logger.error(f"❌ خطأ عام: {e}")

        time.sleep(CHECK_EVERY)


if __name__ == "__main__":
    run()
