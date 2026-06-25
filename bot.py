"""
🤖 بوت إشارات التداول - النسخة العالمية
MEXC API → RSI دقيقة بدقيقة → تنبيه مسبق + شراء + بيع قبل الذروة
"""

import os
import time
import logging
import threading
import http.server
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
INTERVAL         = "1m"
CHECK_EVERY      = 60

# ─── حدود RSI ─────────────────────────────────────────────
RSI_BUY_ALERT  = 32   # ⚠️ جهز للشراء
RSI_BUY_NOW    = 28   # 🟢 اشري الآن (RSI نازل)
RSI_SELL_ALERT = 68   # ⚠️ جهز للبيع
RSI_SELL_NOW   = 72   # 🔴 بيع الآن (RSI صاعد، قبل الذروة)


# ─── Keep-alive لـ Render ──────────────────────────────────
def start_keep_alive():
    port = int(os.environ.get("PORT", 10000))

    class Silent(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("", port), Silent)
    logger.info(f"🌐 Keep-alive server على port {port}")
    threading.Thread(target=server.serve_forever, daemon=True).start()


# ─── حساب EMA ─────────────────────────────────────────────
def calc_ema(prices, period):
    if not prices:
        return 0
    k = 2 / (period + 1)
    ema = prices[0]
    for price in prices[1:]:
        ema = price * k + ema * (1 - k)
    return ema


# ─── حساب RSI ─────────────────────────────────────────────
def calc_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50
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


# ─── حساب MACD ────────────────────────────────────────────
def calc_macd(prices):
    if len(prices) < 26:
        return 0, 0
    ema12 = calc_ema(prices[-26:], 12)
    ema26 = calc_ema(prices[-26:], 26)
    macd_line = ema12 - ema26
    macd_values = [calc_ema(prices[:i], 12) - calc_ema(prices[:i], 26)
                   for i in range(20, len(prices))]
    signal_line = calc_ema(macd_values, 9) if macd_values else 0
    return macd_line, signal_line


# ─── جلب بيانات MEXC ──────────────────────────────────────
def get_candles():
    url = "https://api.mexc.com/api/v3/klines"
    params = {"symbol": SYMBOL, "interval": INTERVAL, "limit": 100}
    try:
        res = requests.get(url, params=params, timeout=10)
        res.raise_for_status()
        data = res.json()
        if not data or not isinstance(data, list):
            logger.warning("⚠️ MEXC رجع بيانات فارغة")
            return []
        closes = [float(c[4]) for c in data]
        logger.info(f"✅ MEXC: {len(closes)} شمعة | ${closes[-1]:,.2f}")
        return closes
    except Exception as e:
        logger.error(f"❌ خطأ في جلب البيانات: {e}")
        return []


# ─── تنسيق السعر ──────────────────────────────────────────
def fmt_price(value):
    if isinstance(value, (int, float)):
        return f"{value:,.2f}"
    return str(value)


# ─── تحليل RSI مع اتجاه ───────────────────────────────────
def analyze(closes):
    if len(closes) < 30:
        return None

    rsi_curr = round(calc_rsi(closes), 2)
    rsi_prev = round(calc_rsi(closes[:-1]), 2)
    price    = round(closes[-1], 2)
    macd, macd_s = calc_macd(closes)
    macd_ok  = macd > macd_s

    sl_pct = 0.015
    tp_pct = 0.030

    # ✅ الاتجاه
    rsi_rising  = rsi_curr > rsi_prev   # RSI صاعد
    rsi_falling = rsi_curr < rsi_prev   # RSI نازل

    # 🔴 بيع الآن — RSI وصل 72 وهو صاعد (قبل الذروة)
    if rsi_curr >= RSI_SELL_NOW and rsi_rising:
        return {
            "type":   "sell",
            "signal": "🔴 بيع الآن",
            "price":  price,
            "rsi":    rsi_curr,
            "rsi_prev": rsi_prev,
            "tp":     round(price * (1 - tp_pct), 2),
            "sl":     round(price * (1 + sl_pct), 2),
            "macd":   "إيجابي ✅" if macd_ok else "سلبي ⚠️"
        }

    # ⚠️ تنبيه مسبق للبيع — RSI بين 68 و72 وصاعد
    elif RSI_SELL_ALERT <= rsi_curr < RSI_SELL_NOW and rsi_rising:
        return {
            "type":   "sell_alert",
            "signal": "⚠️ جهز للبيع",
            "price":  price,
            "rsi":    rsi_curr,
            "rsi_prev": rsi_prev,
            "macd":   "إيجابي ✅" if macd_ok else "سلبي ⚠️"
        }

    # 🟢 شراء الآن — RSI وصل 28 وهو نازل
    elif rsi_curr <= RSI_BUY_NOW and rsi_falling:
        return {
            "type":   "buy",
            "signal": "🟢 اشري الآن",
            "price":  price,
            "rsi":    rsi_curr,
            "rsi_prev": rsi_prev,
            "sl":     round(price * (1 - sl_pct), 2),
            "tp":     round(price * (1 + tp_pct), 2),
            "macd":   "إيجابي ✅" if macd_ok else "سلبي ⚠️"
        }

    # ⚠️ تنبيه مسبق للشراء — RSI بين 28 و32 ونازل
    elif RSI_BUY_NOW < rsi_curr <= RSI_BUY_ALERT and rsi_falling:
        return {
            "type":   "buy_alert",
            "signal": "⚠️ جهز للشراء",
            "price":  price,
            "rsi":    rsi_curr,
            "rsi_prev": rsi_prev,
            "macd":   "إيجابي ✅" if macd_ok else "سلبي ⚠️"
        }

    return None  # صمت — لا شيء مهم


# ─── تنسيق الرسائل ────────────────────────────────────────
def format_message(result):
    now       = datetime.now().strftime("%H:%M | %d/%m/%Y")
    price_str = f"${fmt_price(result['price'])}"
    rsi_str   = f"RSI {result['rsi_prev']} ← {result['rsi']}"

    if result["type"] == "sell":
        return (
            f"🔴 <b>بيع الآن — BTC/USDT</b>\n\n"
            f"💰 سعر البيع: <b>{price_str}</b>\n"
            f"🎯 هدف الربح: <b>${fmt_price(result['tp'])}</b>\n"
            f"🛑 Stop Loss:  <b>${fmt_price(result['sl'])}</b>\n\n"
            f"📊 {rsi_str} 📈 صاعد نحو الذروة\n"
            f"MACD {result['macd']}\n\n"
            f"⚡ خذ ربحك الآن قبل الانعكاس!\n"
            f"🕐 {now}"
        )

    elif result["type"] == "sell_alert":
        return (
            f"⚠️ <b>جهز للبيع — BTC/USDT</b>\n\n"
            f"💰 السعر: <b>{price_str}</b>\n"
            f"📊 {rsi_str} 📈 يتصاعد\n"
            f"MACD {result['macd']}\n\n"
            f"👀 جهز أمر البيع — إشارة البيع قريباً!\n"
            f"🕐 {now}"
        )

    elif result["type"] == "buy":
        return (
            f"🟢 <b>اشري الآن — BTC/USDT</b>\n\n"
            f"💰 سعر الدخول: <b>{price_str}</b>\n"
            f"🎯 هدف الربح: <b>${fmt_price(result['tp'])}</b>\n"
            f"🛑 Stop Loss:  <b>${fmt_price(result['sl'])}</b>\n\n"
            f"📊 {rsi_str} 📉 نازل — تشبع بيع\n"
            f"MACD {result['macd']}\n\n"
            f"⚡ نفّذ فوراً على Bybit!\n"
            f"🕐 {now}"
        )

    elif result["type"] == "buy_alert":
        return (
            f"⚠️ <b>جهز للشراء — BTC/USDT</b>\n\n"
            f"💰 السعر: <b>{price_str}</b>\n"
            f"📊 {rsi_str} 📉 ينزل\n"
            f"MACD {result['macd']}\n\n"
            f"👀 جهز رأس المال — إشارة الشراء قريباً!\n"
            f"🕐 {now}"
        )


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


# ─── الحلقة الرئيسية ──────────────────────────────────────
def run():
    logger.info("🚀 البوت العالمي يعمل — كل دقيقة")
    last_type         = None
    consecutive_fails = 0

    while True:
        try:
            closes = get_candles()

            if not closes or len(closes) < 30:
                consecutive_fails += 1
                logger.warning(f"⚠️ بيانات ناقصة ({consecutive_fails}x)")
                time.sleep(CHECK_EVERY)
                continue

            consecutive_fails = 0
            result = analyze(closes)

            if result is None:
                rsi = round(calc_rsi(closes), 2)
                logger.info(f"😴 RSI={rsi} — منطقة عادية، صمت")
            else:
                logger.info(f"📊 {result['signal']} | RSI={result['rsi']} | ${result['price']}")
                if result["type"] != last_type:
                    send_telegram(format_message(result))
                last_type = result["type"]

        except Exception as e:
            logger.error(f"❌ خطأ: {e}")

        time.sleep(CHECK_EVERY)


if __name__ == "__main__":
    start_keep_alive()
    run()
