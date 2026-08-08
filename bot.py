"""
🤖 بوت إشارات التداول - النسخة الموسّعة
BTC/USDT (MEXC) + الذهب والفوركس (Twelve Data) → RSI + MACD + تأكيد Pivot/ZigZag
تنبيه Telegram فقط — بلا تنفيذ تلقائي لأي صفقة.
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

TELEGRAM_TOKEN     = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID")
TWELVE_DATA_APIKEY = os.getenv("TWELVE_DATA_APIKEY")  # مجاني من twelvedata.com

CHECK_EVERY = 60  # ثانية بين كل دورة فحص

# ─── الأزواج المراقبة ──────────────────────────────────────
# type: "crypto" → عبر MEXC (بلا مفتاح)
# type: "twelvedata" → الذهب/الفوركس (يحتاج TWELVE_DATA_APIKEY مجاني)
SYMBOLS = [
    {"name": "BTC/USDT", "type": "crypto",     "symbol": "BTCUSDT", "interval": "1m"},
    {"name": "الذهب",     "type": "twelvedata", "symbol": "XAU/USD", "interval": "1min"},
    {"name": "يورو/دولار", "type": "twelvedata", "symbol": "EUR/USD", "interval": "1min"},
]

# ─── حدود RSI ─────────────────────────────────────────────
RSI_BUY_ALERT  = 32   # ⚠️ جهز للشراء
RSI_BUY_NOW    = 28   # 🟢 اشري الآن (RSI نازل)
RSI_SELL_ALERT = 68   # ⚠️ جهز للبيع
RSI_SELL_NOW   = 72   # 🔴 بيع الآن (RSI صاعد، قبل الذروة)

# ─── إعداد Pivot/ZigZag ────────────────────────────────────
PIVOT_DEVIATION_PCT = 0.3   # حساسية كشف القاع/الذروة (% من الحركة)

# حالة آخر إشارة لكل رمز (باش ما نكرروش نفس التنبيه)
_last_type = {}


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


# ─── حساب EMA / RSI / MACD ─────────────────────────────────
def calc_ema(prices, period):
    if not prices:
        return 0
    k = 2 / (period + 1)
    ema = prices[0]
    for price in prices[1:]:
        ema = price * k + ema * (1 - k)
    return ema


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


# ─── Pivot / ZigZag: كشف آخر قاع/ذروة مؤكدة ────────────────
def last_confirmed_pivot(closes, deviation_pct=PIVOT_DEVIATION_PCT):
    """
    كيدور من آخر السعر للوراء ويرجع ('قاع' أو 'ذروة', السعر, كم شمعة قبل)
    لآخر نقطة انعكاس مؤكدة (نفس منطق ZigZag فTradingView).
    """
    if len(closes) < 5:
        return None

    trend = None
    extreme_price = closes[0]
    extreme_idx = 0
    last_pivot = None

    for i in range(1, len(closes)):
        price = closes[i]
        if trend in (None, "up"):
            if price > extreme_price:
                extreme_price, extreme_idx = price, i
            drop = (extreme_price - price) / extreme_price * 100
            if drop >= deviation_pct:
                last_pivot = ("ذروة", extreme_price, len(closes) - 1 - extreme_idx)
                trend = "down"
                extreme_price, extreme_idx = price, i

        if trend in (None, "down"):
            if price < extreme_price:
                extreme_price, extreme_idx = price, i
            rise = (price - extreme_price) / extreme_price * 100
            if rise >= deviation_pct:
                last_pivot = ("قاع", extreme_price, len(closes) - 1 - extreme_idx)
                trend = "up"
                extreme_price, extreme_idx = price, i

    return last_pivot


# ─── جلب البيانات: كريبتو عبر MEXC ──────────────────────────
def get_candles_crypto(symbol, interval="1m"):
    url = "https://api.mexc.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": 100}
    try:
        res = requests.get(url, params=params, timeout=10)
        res.raise_for_status()
        data = res.json()
        if not data or not isinstance(data, list):
            logger.warning(f"⚠️ MEXC رجع بيانات فارغة ({symbol})")
            return []
        closes = [float(c[4]) for c in data]
        return closes
    except Exception as e:
        logger.error(f"❌ خطأ جلب MEXC ({symbol}): {e}")
        return []


# ─── جلب البيانات: الذهب/الفوركس عبر Twelve Data ────────────
def get_candles_twelvedata(symbol, interval="1min"):
    if not TWELVE_DATA_APIKEY:
        logger.warning("⚠️ TWELVE_DATA_APIKEY غير معرّف — تخطي الذهب/الفوركس")
        return []
    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": symbol, "interval": interval,
        "outputsize": 100, "apikey": TWELVE_DATA_APIKEY,
    }
    try:
        res = requests.get(url, params=params, timeout=10)
        res.raise_for_status()
        data = res.json()
        values = data.get("values")
        if not values:
            logger.warning(f"⚠️ Twelve Data رجع بلا بيانات ({symbol}): {data.get('message', data)}")
            return []
        closes = [float(v["close"]) for v in reversed(values)]  # ترتيب زمني تصاعدي
        return closes
    except Exception as e:
        logger.error(f"❌ خطأ جلب Twelve Data ({symbol}): {e}")
        return []


def get_candles(cfg):
    if cfg["type"] == "crypto":
        return get_candles_crypto(cfg["symbol"], cfg["interval"])
    return get_candles_twelvedata(cfg["symbol"], cfg["interval"])


# ─── تنسيق السعر ──────────────────────────────────────────
def fmt_price(value):
    if isinstance(value, (int, float)):
        return f"{value:,.4f}" if value < 10 else f"{value:,.2f}"
    return str(value)


# ─── تحليل: RSI + MACD + تأكيد Pivot ───────────────────────
def analyze(closes):
    if len(closes) < 30:
        return None

    rsi_curr = round(calc_rsi(closes), 2)
    rsi_prev = round(calc_rsi(closes[:-1]), 2)
    price    = round(closes[-1], 5)
    macd, macd_s = calc_macd(closes)
    macd_ok  = macd > macd_s

    sl_pct = 0.015
    tp_pct = 0.030

    rsi_rising  = rsi_curr > rsi_prev
    rsi_falling = rsi_curr < rsi_prev

    pivot = last_confirmed_pivot(closes)
    pivot_kind = pivot[0] if pivot else None
    pivot_note = f"✅ Pivot يأكد ({pivot_kind})" if pivot_kind else "— Pivot: بلا تأكيد واضح"

    base = {"price": price, "rsi": rsi_curr, "rsi_prev": rsi_prev,
            "macd": "إيجابي ✅" if macd_ok else "سلبي ⚠️", "pivot_note": pivot_note}

    # 🔴 بيع الآن
    if rsi_curr >= RSI_SELL_NOW and rsi_rising:
        strong = pivot_kind == "ذروة"
        return {**base, "type": "sell",
                "signal": "🔴 بيع الآن" + (" (مؤكد بـPivot)" if strong else ""),
                "tp": round(price * (1 - tp_pct), 5), "sl": round(price * (1 + sl_pct), 5)}

    elif RSI_SELL_ALERT <= rsi_curr < RSI_SELL_NOW and rsi_rising:
        return {**base, "type": "sell_alert", "signal": "⚠️ جهز للبيع"}

    # 🟢 شراء الآن
    elif rsi_curr <= RSI_BUY_NOW and rsi_falling:
        strong = pivot_kind == "قاع"
        return {**base, "type": "buy",
                "signal": "🟢 اشري الآن" + (" (مؤكد بـPivot)" if strong else ""),
                "sl": round(price * (1 - sl_pct), 5), "tp": round(price * (1 + tp_pct), 5)}

    elif RSI_BUY_NOW < rsi_curr <= RSI_BUY_ALERT and rsi_falling:
        return {**base, "type": "buy_alert", "signal": "⚠️ جهز للشراء"}

    return None  # صمت — لا شيء مهم


# ─── تنسيق الرسائل ────────────────────────────────────────
def format_message(name, result):
    now       = datetime.now().strftime("%H:%M | %d/%m/%Y")
    price_str = f"{fmt_price(result['price'])}"
    rsi_str   = f"RSI {result['rsi_prev']} ← {result['rsi']}"

    if result["type"] == "sell":
        return (
            f"🔴 <b>بيع الآن — {name}</b>\n\n"
            f"💰 سعر البيع: <b>{price_str}</b>\n"
            f"🎯 هدف الربح: <b>{fmt_price(result['tp'])}</b>\n"
            f"🛑 Stop Loss:  <b>{fmt_price(result['sl'])}</b>\n\n"
            f"📊 {rsi_str} 📈 صاعد نحو الذروة\n"
            f"MACD {result['macd']}\n"
            f"{result['pivot_note']}\n\n"
            f"⚡ خذ ربحك الآن قبل الانعكاس!\n"
            f"🕐 {now}"
        )
    elif result["type"] == "sell_alert":
        return (
            f"⚠️ <b>جهز للبيع — {name}</b>\n\n"
            f"💰 السعر: <b>{price_str}</b>\n"
            f"📊 {rsi_str} 📈 يتصاعد\n"
            f"MACD {result['macd']}\n"
            f"{result['pivot_note']}\n\n"
            f"👀 جهز أمر البيع — إشارة البيع قريباً!\n"
            f"🕐 {now}"
        )
    elif result["type"] == "buy":
        return (
            f"🟢 <b>اشري الآن — {name}</b>\n\n"
            f"💰 سعر الدخول: <b>{price_str}</b>\n"
            f"🎯 هدف الربح: <b>{fmt_price(result['tp'])}</b>\n"
            f"🛑 Stop Loss:  <b>{fmt_price(result['sl'])}</b>\n\n"
            f"📊 {rsi_str} 📉 نازل — تشبع بيع\n"
            f"MACD {result['macd']}\n"
            f"{result['pivot_note']}\n\n"
            f"⚡ راقب وقرر بنفسك — البوت للتنبيه فقط\n"
            f"🕐 {now}"
        )
    elif result["type"] == "buy_alert":
        return (
            f"⚠️ <b>جهز للشراء — {name}</b>\n\n"
            f"💰 السعر: <b>{price_str}</b>\n"
            f"📊 {rsi_str} 📉 ينزل\n"
            f"MACD {result['macd']}\n"
            f"{result['pivot_note']}\n\n"
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
            "chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"
        }, timeout=10)
        logger.info("✅ إشارة أُرسلت")
    except Exception as e:
        logger.error(f"❌ خطأ Telegram: {e}")


# ─── الحلقة الرئيسية ──────────────────────────────────────
def run():
    logger.info(f"🚀 البوت يعمل — يراقب {len(SYMBOLS)} أصول كل {CHECK_EVERY}s")

    while True:
        for cfg in SYMBOLS:
            name = cfg["name"]
            try:
                closes = get_candles(cfg)
                if not closes or len(closes) < 30:
                    logger.warning(f"⚠️ [{name}] بيانات ناقصة")
                    continue

                result = analyze(closes)
                if result is None:
                    rsi = round(calc_rsi(closes), 2)
                    logger.info(f"😴 [{name}] RSI={rsi} — منطقة عادية، صمت")
                else:
                    logger.info(f"📊 [{name}] {result['signal']} | RSI={result['rsi']} | {result['price']}")
                    if result["type"] != _last_type.get(name):
                        send_telegram(format_message(name, result))
                    _last_type[name] = result["type"]

            except Exception as e:
                logger.error(f"❌ خطأ فـ [{name}]: {e}")

            time.sleep(2)  # فاصل صغير بين كل رمز

        time.sleep(CHECK_EVERY)


if __name__ == "__main__":
    start_keep_alive()
    run()
            
