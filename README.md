# تحديث بوت الإشارات — إضافة الذهب/الفوركس + تأكيد Pivot

## شنو تبدل عن النسخة القديمة

- زدنا **الذهب (XAU/USD)** و**يورو/دولار** جنب BTC/USDT.
- كل إشارة RSI/MACD دابا كتتفحص مقابل **Pivot/ZigZag** (نفس منطق
  القاع الأخضر/الذروة الحمراء اللي شفنا فTradingView) — إلا توافقو
  الاثنين، الرسالة كتبين "✅ مؤكد بـPivot" (ثقة أكبر).
- البوت **مازال بلا تنفيذ تلقائي** — تنبيه Telegram فقط، كيف كان.

## الخطوات

### 1) احصل على مفتاح Twelve Data (مجاني)

الذهب والفوركس محتاجين مصدر بيانات مختلف عن MEXC (اللي كريبتو فقط):

1. روح لـ [twelvedata.com](https://twelvedata.com) → **Get free API key**
2. سجل بالإيميل، خد المفتاح (API Key) من الـ Dashboard
3. الخطة المجانية كافية (800 طلب/يوم — البوت كيستهلك أقل من هادشي بزاف)

### 2) بدل الملفات فـ GitHub

فـ repo `Trading-Bot-` ديالك، بدل هاد الثلاث ملفات بالنسخة الجديدة:
- `bot.py`
- `render.yaml`
- `requirements.txt`

(من واجهة GitHub: دخل للملف → قلم التعديل (✏️) → امسح القديم → دبج الجديد → Commit)

### 3) زيد المتغير الجديد فـ Render

1. دخل لخدمة `trading-signal-bot` فـ Render
2. **Environment** → **Add Environment Variable**
3. Key: `TWELVE_DATA_APIKEY` | Value: المفتاح اللي خدتي من Twelve Data
4. Save — Render غادي يعاود ينشر (redeploy) تلقائيا

### 4) تأكد

راقب الـ **Logs** فRender، خاصك تشوف سطر كيف:
```
🚀 البوت يعمل — يراقب 3 أصول كل 60s
```
وبعد شوية، بيانات لـBTC، الذهب، واليورو/دولار الثلاثة.

## بغيتي نزيد أزواج أخرى؟

زيد سطر فـ `SYMBOLS` جوه `bot.py`:
```python
{"name": "DOGE/USDT", "type": "crypto", "symbol": "DOGEUSDT", "interval": "1m"},
{"name": "جنيه/دولار", "type": "twelvedata", "symbol": "GBP/USD", "interval": "1min"},
```

