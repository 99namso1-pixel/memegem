# 💎 Gem Hunter Telegram Bot

Bot Python tự động scan Dexscreener mỗi 5 phút và gửi alert về Telegram khi tìm thấy **pre-pump gem**.

---

## 🚀 Setup trong 10 phút

### BƯỚC 1 — Tạo Telegram Bot

1. Mở Telegram → tìm **@BotFather**
2. Gõ `/newbot`
3. Đặt tên: `Gem Hunter Bot`
4. Username: `gemhunterxxx_bot` (phải kết thúc bằng `_bot`)
5. BotFather sẽ trả về **token** dạng: `7123456789:AAHxxxxxxxxxxxxx`
6. **Copy token này lại**

---

### BƯỚC 2 — Lấy Chat ID của bạn

**Cách 1 (đơn giản nhất):**
1. Tìm **@userinfobot** trên Telegram
2. Gõ `/start`
3. Bot trả về ID của bạn (số dạng `123456789`)

**Cách 2:**
1. Nhắn `/start` cho bot vừa tạo
2. Mở link: `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
3. Tìm `"chat":{"id": 123456789}`

---

### BƯỚC 3 — Deploy lên Railway

1. Vào **https://railway.app** → Sign up (free)
2. Bấm **"New Project"** → **"Deploy from GitHub repo"**
   - Hoặc: **"New Project"** → **"Empty Project"** → drag-drop folder này

3. Sau khi deploy, vào tab **"Variables"** → Add:

```
TELEGRAM_BOT_TOKEN = 7123456789:AAHxxxxxxxxxxxxx
TELEGRAM_CHAT_ID   = 123456789
CHAINS             = solana,base,ethereum
SCAN_INTERVAL_MINUTES = 5
MIN_SCORE          = 6.5
MIN_MC             = 30000
MAX_MC             = 5000000
MIN_LIQUIDITY      = 20000
MIN_BS_RATIO       = 1.5
MIN_VOL_ACCEL      = 1.5
MAX_RUG_RISK       = 7.0
```

4. Railway tự deploy → Bot chạy 24/7 🎉

---

### BƯỚC 3 (Alternative) — Chạy local trên máy

```bash
# Cài Python 3.11+
pip install -r requirements.txt

# Tạo .env
cp .env.example .env
# Mở .env điền TELEGRAM_BOT_TOKEN và TELEGRAM_CHAT_ID

# Chạy
python main.py
```

---

## 📱 Alert sẽ trông như thế này

```
💎 GEM ALERT #1

$PEPEAI ◎ SOL  🐋 ACCUMULATION
📛 Pepe AI Token

━━━━━━━━━━━━━━━━━━━━
📊 METRICS
• MC:        $180K
• Liquidity: $45K
• Vol 24h:   $320K
• Vol 1h:    $85K

📈 PRICE ACTION
• 1h:  +12.5%
• 24h: +8.3%

🔄 ON-CHAIN
• B/S 24h: 🐋 4.2x  (Buys: 1240 | Sells: 295)
• Vol Accel: 3.8x
• Age: 1.2d

🤖 BOT SCORES
🟢 Pre-Pump: 8.5/10  ████████░░
🟢 Rug Risk: 3.5/10  ███░░░░░░░

✅ SIGNALS
  🐋 ACCUMULATION: giá flat, vol cao, buys > sells
  ⚡ Vol tăng 3.8x — tiền đột biến
  🎯 Micro cap <$500K — room 10x+
  🐋 Buy/Sell 24h=4.2x — whale gom

🔗 Dexscreener | 🦅 Birdeye | 🔍 Solscan
```

---

## ⚙️ Config thresholds

| Biến | Mặc định | Ý nghĩa |
|------|---------|---------|
| `MIN_SCORE` | 6.5 | Pre-pump score tối thiểu (1-10) |
| `MIN_MC` | $30K | Market cap tối thiểu |
| `MAX_MC` | $5M | Market cap tối đa |
| `MIN_LIQUIDITY` | $20K | Liquidity pool tối thiểu |
| `MIN_BS_RATIO` | 1.5x | Buy/Sell ratio tối thiểu |
| `MIN_VOL_ACCEL` | 1.5x | Volume acceleration tối thiểu |
| `MAX_RUG_RISK` | 7.0 | Rug risk tối đa cho phép |
| `SCAN_INTERVAL_MINUTES` | 5 | Scan mỗi bao nhiêu phút |

**Muốn ít noise hơn:** tăng `MIN_SCORE` lên 7.5, tăng `MIN_BS_RATIO` lên 2.0

**Muốn nhiều alert hơn:** giảm `MIN_SCORE` xuống 5.5

---

## 🏗 Project Structure

```
gem-hunter-telegram/
├── main.py          ← Entry point, scan loop, filters
├── src/
│   ├── scanner.py   ← Dexscreener fetch + pre-pump scoring
│   └── alerts.py    ← Telegram message formatter
├── logs/
│   └── seen_gems.json ← Tránh spam alert cùng 1 gem
├── requirements.txt
├── Procfile         ← Railway worker config
├── railway.toml
└── .env.example
```

---

## ⚠️ Disclaimer

NOT FINANCIAL ADVICE. Meme coins cực kỳ rủi ro. Bot chỉ là tool hỗ trợ, không đảm bảo lợi nhuận. DYOR.
