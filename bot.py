"""
🤖 بوت إشارات التداول - بدون pandas
Binance API → RSI + EMA + MACD → Telegram
"""

import os
import time
import logging
import requests
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SYMBOL           = "BTCUSDT"
INTERVAL         = "15m"
CHECK_EVERY      = 60 * 15


# ─── حساب EMA يدوياً ──────────────────────────────────────
def calc_ema(prices, period):
    k = 2 / (period + 1)
    ema = prices[0]
    for price in prices[1:]:
        ema = price * k + ema * (1 - k)
    return ema


# ─── حساب RSI يدوياً ──────────────────────────────────────
def calc_rsi(prices, period=14):
    gains, losses = [], []
    for i in range(1, len(prices)):
        diff = prices[i] - prices[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


# ─── حساب MACD يدوياً ─────────────────────────────────────
def calc_macd(prices):
    ema12 = calc_ema(prices[-26:], 12)
    ema26 = calc_ema(prices[-26:], 26)
    macd_line = ema12 - ema26
    return macd_line


# ─── جلب بيانات Binance ───────────────────────────────────
def get_candles():
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": SYMBOL, "interval": INTERVAL, "limit": 100}
    try:
        res = requests.get(url, params=params, timeout=10)
        res.raise_for_status()
        data = res.json()
        closes = [float(c[4]) for c in data]
        return closes
    except Exception as e:
        logger.error(f"❌ خطأ في جلب البيانات: {e}")
        return []


# ─── تحليل المؤشرات ───────────────────────────────────────
def analyze(closes):
    if len(closes) < 30:
        return {"signal": "انتظر ⏳", "reasons": ["بيانات غير كافية"]}

    rsi      = calc_rsi(closes)
    ema9     = calc_ema(closes, 9)
    ema21    = calc_ema(closes, 21)
    ema9_p   = calc_ema(closes[:-1], 9)
    ema21_p  = calc_ema(closes[:-1], 21)
    macd     = calc_macd(closes)
    macd_sig = calc_ema([calc_macd(closes[:i]) for i in range(20, len(closes))], 9)

    price = round(closes[-1], 2)
    rsi   = round(rsi, 2)

    buy_signals  = 0
    sell_signals = 0
    reasons      = []

    if rsi < 35:
        buy_signals += 1
        reasons.append(f"RSI={rsi} تشبع بيع")
    elif rsi > 65:
        sell_signals += 1
        reasons.append(f"RSI={rsi} تشبع شراء")

    if ema9_p < ema21_p and ema9 > ema21:
        buy_signals += 1
        reasons.append("EMA9 تقطع EMA21 لفوق")
    elif ema9_p > ema21_p and ema9 < ema21:
        sell_signals += 1
        reasons.append("EMA9 تقطع EMA21 لتحت")

    if macd > macd_sig:
        buy_signals += 1
        reasons.append("MACD إيجابي")
    elif macd < macd_sig:
        sell_signals += 1
        reasons.append("MACD سلبي")

    sl_pct = 0.015
    tp_pct = 0.030

    if buy_signals >= 2:
        return {
            "signal":   "شراء 🟢",
            "price":    price,
            "sl":       round(price * (1 - sl_pct), 2),
            "tp":       round(price * (1 + tp_pct), 2),
            "reasons":  reasons,
            "strength": buy_signals
        }
    elif sell_signals >= 2:
        return {
            "signal":   "بيع 🔴",
            "price":    price,
            "sl":       round(price * (1 + sl_pct), 2),
            "tp":       round(price * (1 - tp_pct), 2),
            "reasons":  reasons,
            "strength": sell_signals
        }
    else:
        return {
            "signal":  "انتظر ⏳",
            "price":   price,
            "reasons": reasons or ["السوق غير واضح"]
        }


# ─── إرسال Telegram ───────────────────────────────────────
def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(message)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={
            "chat_id":    TELEGRAM_CHAT_ID,
            "text":       message,
            "parse_mode": "HTML"
        }, timeout=10)
        logger.info("✅ إشارة أُرسلت")
    except Exception as e:
        logger.error(f"❌ خطأ Telegram: {e}")


# ─── تنسيق الرسالة ────────────────────────────────────────
def format_message(result):
    now = datetime.now().strftime("%H:%M | %d/%m/%Y")
    if result["signal"] == "انتظر ⏳":
        return (
            f"⏳ <b>BTC/USDT — انتظر</b>\n"
            f"💰 ${result.get('price', '?'):,}\n"
            f"📊 {' | '.join(result['reasons'])}\n"
            f"🕐 {now}"
        )
    stars = "⭐" * result.get("strength", 1)
    return (
        f"{'🟢' if 'شراء' in result['signal'] else '🔴'} "
        f"<b>إشارة {result['signal']} — BTC/USDT</b> {stars}\n\n"
        f"💰 سعر الدخول: <b>${result['price']:,}</b>\n"
        f"🛑 Stop Loss:   <b>${result['sl']:,}</b>\n"
        f"🎯 Take Profit: <b>${result['tp']:,}</b>\n\n"
        f"📊 " + " | ".join(result['reasons']) +
        f"\n\n⚠️ نفّذ يدوياً على Pionex\n"
        f"🕐 {now}"
    )


# ─── الحلقة الرئيسية ──────────────────────────────────────
def run():
    logger.info("🚀 بوت الإشارات يعمل...")
    send_telegram("🤖 <b>بوت إشارات BTC شغّال!</b>\nيراقب كل 15 دقيقة.")
    last_signal = None

    while True:
        try:
            closes = get_candles()
            result = analyze(closes)
            logger.info(f"📊 {result['signal']} | ${result.get('price', '?')}")

            if result["signal"] != last_signal:
                send_telegram(format_message(result))
                last_signal = result["signal"]

        except Exception as e:
            logger.error(f"❌ خطأ: {e}")

        time.sleep(CHECK_EVERY)


if __name__ == "__main__":
    run()
