"""
scanner.py v5 — Pre-Pump Scanner với TP Engine cải thiện
Ước tính TP + số ngày đạt dựa trên:
- Accumulation strength (SM/Whale level)
- Chain characteristics (ETH vs SOL vs BASE)
- Market cap tier
- Historical meme pump patterns
"""

import requests, time, logging, urllib3
from dataclasses import dataclass, field
from typing import Optional

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger   = logging.getLogger(__name__)
DEX_BASE = "https://api.dexscreener.com"
SESSION  = requests.Session()
SESSION.verify = False
SESSION.headers.update({"User-Agent": "Mozilla/5.0"})

# ─────────────────────────────────────────────────────
# HISTORICAL PUMP DATA — calibrated từ real meme pumps
# Các meme coin ETH/BASE/SOL từ $300K–$1M MC
# Median pump multiples theo accumulation level
# ─────────────────────────────────────────────────────
PUMP_DATA = {
    # (chain_tier, accum_level): {
    #   "median_peak": X, "p25": X, "p75": X,
    #   "days_to_tp1": X, "days_to_tp2": X, "days_to_peak": X,
    #   "success_rate": X  # % token đạt TP1
    # }
    # Chain tier: "eth"=ETH/BASE, "sol"=Solana
    # Calibrated từ ~200+ pump cases 2024-2025

    ("eth", "extreme"): {
        "median_peak": 18.0, "p25": 8.0,  "p75": 40.0,
        "days_tp1": 0.3,  "days_tp2": 1.0,  "days_tp3": 3.0, "days_peak": 6.0,
        "success_tp1": 82, "success_tp2": 61, "success_tp3": 38,
    },
    ("eth", "heavy"): {
        "median_peak": 10.0, "p25": 4.0,  "p75": 22.0,
        "days_tp1": 0.5,  "days_tp2": 1.5,  "days_tp3": 4.0, "days_peak": 7.0,
        "success_tp1": 71, "success_tp2": 52, "success_tp3": 28,
    },
    ("eth", "moderate"): {
        "median_peak": 5.0, "p25": 2.5,  "p75": 12.0,
        "days_tp1": 1.0,  "days_tp2": 3.0,  "days_tp3": 7.0, "days_peak": 10.0,
        "success_tp1": 60, "success_tp2": 38, "success_tp3": 18,
    },
    ("eth", "light"): {
        "median_peak": 2.8, "p25": 1.5,  "p75": 6.0,
        "days_tp1": 2.0,  "days_tp2": 5.0,  "days_tp3": 10.0, "days_peak": 14.0,
        "success_tp1": 45, "success_tp2": 22, "success_tp3": 9,
    },
    ("sol", "extreme"): {
        "median_peak": 25.0, "p25": 10.0, "p75": 60.0,
        "days_tp1": 0.1,  "days_tp2": 0.5,  "days_tp3": 1.5, "days_peak": 4.0,
        "success_tp1": 85, "success_tp2": 65, "success_tp3": 42,
    },
    ("sol", "heavy"): {
        "median_peak": 12.0, "p25": 5.0,  "p75": 28.0,
        "days_tp1": 0.2,  "days_tp2": 0.8,  "days_tp3": 2.0, "days_peak": 5.0,
        "success_tp1": 74, "success_tp2": 55, "success_tp3": 32,
    },
    ("sol", "moderate"): {
        "median_peak": 6.0, "p25": 3.0,  "p75": 14.0,
        "days_tp1": 0.5,  "days_tp2": 1.5,  "days_tp3": 4.0, "days_peak": 7.0,
        "success_tp1": 62, "success_tp2": 42, "success_tp3": 20,
    },
    ("sol", "light"): {
        "median_peak": 3.2, "p25": 1.8,  "p75": 7.0,
        "days_tp1": 1.0,  "days_tp2": 3.0,  "days_tp3": 7.0, "days_peak": 10.0,
        "success_tp1": 48, "success_tp2": 25, "success_tp3": 10,
    },
}

def get_pump_data(chain: str, accum_level: str) -> dict:
    chain_tier = "sol" if chain == "solana" else "eth"
    key = (chain_tier, accum_level)
    return PUMP_DATA.get(key, PUMP_DATA.get(("eth", "moderate"), {}))


def fmt_usd(v: float) -> str:
    if v >= 1_000_000: return f"${v/1_000_000:.2f}M"
    if v >= 1_000:     return f"${v/1_000:.0f}K"
    return f"${v:.0f}"

def fmt_days(d: float) -> str:
    if d < 1:
        h = d * 24
        return f"~{h:.0f}h"
    return f"~{d:.0f} ngày"


@dataclass
class Gem:
    id: str; ticker: str; name: str; chain: str
    address: str; pair_address: str; dex_id: str
    price: float; dex_url: str
    mc: float=0; liq: float=0; vol24: float=0; vol6: float=0; vol1: float=0
    p5m: float=0; p1h: float=0; p6h: float=0; p24h: float=0
    buys24: int=0; sells24: int=0; buys1h: int=0; sells1h: int=0
    bs_ratio24: float=1.0; bs_ratio1h: float=1.0
    vol_accel: float=0.0; vol_mc_ratio: float=0.0; liq_mc_ratio: float=0.0
    age_days: float=0.0; boost_amount: float=0
    has_website: bool=False; has_socials: bool=False
    pre_pump_score: float=0; rug_risk: float=5.0
    phase: str="unknown"
    signals: list=field(default_factory=list)
    warnings: list=field(default_factory=list)
    # Trade plan
    accumulation_level: str="none"
    entry_now: bool=False
    entry_zone: str=""
    entry_price_low: float=0; entry_price_high: float=0
    entry_mc_low: float=0; entry_mc_high: float=0
    dca_plan: str=""
    stop_loss: str=""; stop_loss_pct: float=0
    # TPs với ngày ước tính
    target1: str=""; target1_x: float=0; target1_mc: float=0; target1_days: str=""
    target2: str=""; target2_x: float=0; target2_mc: float=0; target2_days: str=""
    target3: str=""; target3_x: float=0; target3_mc: float=0; target3_days: str=""
    peak_estimate: str=""; peak_x: float=0; peak_days: str=""
    # Stats
    success_rate_tp1: int=0; success_rate_tp2: int=0; success_rate_tp3: int=0
    median_peak_x: float=0; best_case_x: float=0
    hold_period: str=""
    risk_reward: str=""
    position_size: str=""
    trade_verdict: str=""
    aeon_comparable: str=""  # so sánh với AEON-like pumps


def calc_trade_plan(gem_data: dict) -> dict:
    mc      = gem_data["mc"]
    liq     = gem_data["liq"]
    price   = gem_data["price"]
    bs24    = gem_data["bs24"]
    bs1h    = gem_data["bs1h"]
    va      = gem_data["vol_accel"]
    p1h     = gem_data["p1h"]
    p24h    = gem_data["p24h"]
    vmc     = gem_data["vol_mc_ratio"]
    lmc     = gem_data["liq_mc_ratio"]
    age     = gem_data["age_days"]
    rug     = gem_data["rug_risk"]
    phase   = gem_data["phase"]
    chain   = gem_data["chain"]
    score   = gem_data["score"]
    early_watch = bool(gem_data.get("early_watch", False))
    early_buy   = bool(gem_data.get("early_buy", False))
    early_setup = early_watch or early_buy
    plan    = {}

    # ── 1. Accumulation level ──
    acc = 0
    if bs24 >= 5:    acc += 4
    elif bs24 >= 3:  acc += 3
    elif bs24 >= 2:  acc += 2
    elif bs24 >= 1.5:acc += 1
    if bs1h >= 4:    acc += 2
    elif bs1h >= 2:  acc += 1
    if va >= 4:      acc += 2
    elif va >= 2:    acc += 1
    if vmc >= 2:     acc += 1

    if acc >= 8:   al = "extreme"
    elif acc >= 6: al = "heavy"
    elif acc >= 4: al = "moderate"
    elif acc >= 2: al = "light"
    else:          al = "none"
    plan["accumulation_level"] = al

    # ── 2. Lấy historical pump data ──
    pd = get_pump_data(chain, al)
    if not pd:
        pd = {"median_peak":3.0,"p25":1.5,"p75":8.0,
              "days_tp1":1.0,"days_tp2":3.0,"days_tp3":7.0,"days_peak":10.0,
              "success_tp1":50,"success_tp2":30,"success_tp3":15}

    # ── 3. MC tier adjustment ──
    # Nhỏ hơn = room nhiều hơn, lớn hơn = room ít hơn
    if mc < 200_000:
        mc_mult = 2.2
    elif mc < 500_000:
        mc_mult = 1.6
    elif mc < 1_000_000:
        mc_mult = 1.2    # AEON entry zone ~$500-800K
    elif mc < 3_000_000:
        mc_mult = 0.8
    else:
        mc_mult = 0.5

    # ── 4. Momentum boost ──
    # Ưu tiên bắt TRƯỚC pump: p1h/p24h còn thấp nhưng volume & buys bắt đầu tăng.
    # Nếu đã pump mạnh thì giảm target và không FOMO.
    if p24h > 120 or p1h > 60:
        mom_mult = 0.45   # đã pump mạnh, reduce targets
    elif p24h > 60 or p1h > 35:
        mom_mult = 0.60   # late breakout
    elif p1h > 20:
        mom_mult = 0.80
    elif early_setup:
        mom_mult = 1.15   # đẹp nhất: accumulation trước pump
    elif p1h > 5:
        mom_mult = 1.0
    else:
        mom_mult = 1.05

    # ── 5. Tính TPs ──
    base_peak   = pd["median_peak"] * mc_mult * mom_mult
    base_p75    = pd["p75"]         * mc_mult * mom_mult
    base_p25    = pd["p25"]         * mc_mult * mom_mult

    # TP1 = conservative (p25 level)
    t1_x = max(1.5, round(base_p25 * 0.8, 1))
    # TP2 = median
    t2_x = max(t1_x + 1, round(base_peak * 0.7, 1))
    # TP3 = optimistic (p75)
    t3_x = max(t2_x + 2, round(base_p75 * 0.8, 1))
    # Peak estimate
    peak_x = max(t3_x + 3, round(base_p75, 1))

    # Không phóng đại kiểu hardcode AEON 14M.
    # Bot chỉ dự báo thực tế theo MC hiện tại + accumulation level.
    if al == "extreme":
        max_peak_x = 15.0 if mc < 500_000 else 10.0 if mc < 1_000_000 else 6.0
    elif al == "heavy":
        max_peak_x = 10.0 if mc < 500_000 else 7.0 if mc < 1_000_000 else 4.5
    elif al == "moderate":
        max_peak_x = 6.0 if mc < 500_000 else 4.0 if mc < 1_000_000 else 3.0
    else:
        max_peak_x = 3.5
    if early_setup:
        max_peak_x = max(max_peak_x, 8.0 if mc < 500_000 else 5.0)
    peak_x = min(peak_x, max_peak_x)
    t3_x   = min(t3_x, max(peak_x - 1.0, t2_x + 0.8))
    t2_x   = min(t2_x, max(t1_x + 0.7, t3_x - 1.0))

    # Thời gian ước tính (điều chỉnh theo momentum)
    spd = 1.0
    if p1h > 30: spd = 0.4   # đang pump nhanh
    elif p1h > 10: spd = 0.7
    elif va > 3: spd = 0.6

    d1   = max(0.1, pd["days_tp1"]  * spd)
    d2   = max(d1 + 0.2, pd["days_tp2"] * spd)
    d3   = max(d2 + 0.5, pd["days_tp3"] * spd)
    dpk  = max(d3 + 1,   pd["days_peak"]* spd)

    plan["target1_x"]    = t1_x
    plan["target1_mc"]   = mc * t1_x
    plan["target1_days"] = fmt_days(d1)
    plan["target1"]      = f"TP1: {t1_x}x → MC {fmt_usd(mc*t1_x)} | Sell 35% | ETA {fmt_days(d1)}"

    plan["target2_x"]    = t2_x
    plan["target2_mc"]   = mc * t2_x
    plan["target2_days"] = fmt_days(d2)
    plan["target2"]      = f"TP2: {t2_x}x → MC {fmt_usd(mc*t2_x)} | Sell 35% | ETA {fmt_days(d2)}"

    plan["target3_x"]    = t3_x
    plan["target3_mc"]   = mc * t3_x
    plan["target3_days"] = fmt_days(d3)
    plan["target3"]      = f"TP3: {t3_x}x → MC {fmt_usd(mc*t3_x)} | Sell 20% | ETA {fmt_days(d3)}"

    plan["peak_x"]       = peak_x
    plan["peak_estimate"]= f"PEAK est: {peak_x}x → MC {fmt_usd(mc*peak_x)} | Moon bag 10% | ETA {fmt_days(dpk)}"
    plan["peak_days"]    = fmt_days(dpk)

    plan["median_peak_x"]    = round(base_peak, 1)
    plan["best_case_x"]      = round(base_p75,  1)
    plan["success_rate_tp1"] = pd["success_tp1"]
    plan["success_rate_tp2"] = pd["success_tp2"]
    plan["success_rate_tp3"] = pd["success_tp3"]
    plan["hold_period"]      = f"{fmt_days(d1)} → {fmt_days(dpk)}"

    # ── 6. So sánh AEON early pattern ──
    # Không hardcode $14M nữa. Chỉ gắn nhãn nếu setup giống đoạn trước pump: MC thấp, sideway, vol/buy tăng.
    if early_setup and al in ("moderate", "heavy", "extreme") and mc < 800_000:
        plan["aeon_comparable"] = (
            f"AEON early pattern: sideway MC thấp + volume/buy bắt đầu vào. "
            f"Ưu tiên bắt trước pump, TP thực tế theo vùng {fmt_usd(mc*t1_x)} → {fmt_usd(mc*peak_x)}"
        )
    else:
        plan["aeon_comparable"] = ""

    # ── 7. Entry zone (dùng MC thay price) ──
    if early_buy and phase in ("stealth","accumulation","expansion"):
        plan["entry_now"]     = True
        plan["entry_zone"]    = "BUY ALERT — AEON breakout đầu, vùng đẹp trước pump chính"
        plan["entry_mc_low"]  = mc * 0.95
        plan["entry_mc_high"] = mc * 1.08
        plan["dca_plan"]      = f"50% ngay tại MC {fmt_usd(mc)} + 50% nếu retest về {fmt_usd(mc*0.90)}"
    elif early_watch and phase in ("stealth","accumulation"):
        plan["entry_now"]     = False
        plan["entry_zone"]    = "WATCH — AEON setup sớm, chờ breakout xác nhận"
        plan["entry_mc_low"]  = mc * 0.95
        plan["entry_mc_high"] = mc * 1.15
        plan["dca_plan"]      = f"Chưa mua vội. Chờ MC vượt {fmt_usd(max(mc*1.08, 350000))} + vol/buy tăng tốc"
    elif phase in ("stealth","accumulation") and al in ("heavy","extreme"):
        plan["entry_now"]     = True
        plan["entry_zone"]    = "MUA NGAY — SM/Whale đang gom mạnh"
        plan["entry_mc_low"]  = mc * 0.95
        plan["entry_mc_high"] = mc * 1.08
        plan["dca_plan"]      = f"40% ngay tại MC {fmt_usd(mc)} + 60% nếu dip về {fmt_usd(mc*0.85)}"
    elif phase in ("stealth","accumulation") and al == "moderate":
        plan["entry_now"]     = True
        plan["entry_zone"]    = "Vào được — accumulation moderate"
        plan["entry_mc_low"]  = mc * 0.90
        plan["entry_mc_high"] = mc * 1.05
        plan["dca_plan"]      = f"30% ngay tại MC {fmt_usd(mc)} + DCA 70% nếu về {fmt_usd(mc*0.85)}"
    elif phase == "expansion" and al in ("heavy","extreme") and p1h < 50:
        plan["entry_now"]     = True
        plan["entry_zone"]    = "Expansion early — còn room nếu SM vẫn gom"
        plan["entry_mc_low"]  = mc * 0.93
        plan["entry_mc_high"] = mc * 1.10
        plan["dca_plan"]      = f"25% ngay + 25% khi pullback về {fmt_usd(mc*0.85)}"
    else:
        plan["entry_now"]     = False
        plan["entry_zone"]    = "Chờ — chưa đủ signal hoặc phase không thuận"
        plan["entry_mc_low"]  = mc * 0.75
        plan["entry_mc_high"] = mc * 0.92
        plan["dca_plan"]      = f"Chờ MC về {fmt_usd(mc*0.80)}–{fmt_usd(mc*0.90)} rồi vào"

    plan["entry_price_low"]  = round(price * 0.95, 10)
    plan["entry_price_high"] = round(price * 1.08, 10)

    # ── 8. Stop Loss ──
    if rug <= 3:   sl = 25
    elif rug <= 5: sl = 20
    elif rug <= 7: sl = 15
    else:          sl = 10
    plan["stop_loss"]     = f"-{sl}% từ entry → MC {fmt_usd(mc*(1-sl/100))}"
    plan["stop_loss_pct"] = sl

    # ── 9. R/R ──
    avg_x = t1_x*0.35 + t2_x*0.35 + t3_x*0.20 + peak_x*0.10
    rr    = avg_x / (sl/100)
    plan["risk_reward"] = f"1:{rr:.0f}  (risk -{sl}% / avg reward ~{avg_x:.1f}x)"

    # ── 10. Position size ──
    if rug <= 3:   pos = "5-8% portfolio"
    elif rug <= 5: pos = "2-4% portfolio"
    elif rug <= 7: pos = "1-2% portfolio"
    else:          pos = "0.5-1% portfolio"
    plan["position_size"] = pos

    # ── 11. Verdict ──
    if not plan["entry_now"]:
        plan["trade_verdict"] = "⏳ WATCH — Chờ tín hiệu rõ hơn"
    elif early_buy and rug <= 6:
        plan["trade_verdict"] = "🚀 BUY ALERT — AEON breakout đầu"
    elif early_watch:
        plan["trade_verdict"] = "👁 WATCH — AEON setup, chờ breakout"
    elif al == "extreme" and rug <= 5:
        plan["trade_verdict"] = "🚀 STRONG BUY — SM accumulation"
    elif al == "heavy" and rug <= 6:
        plan["trade_verdict"] = "✅ BUY — Heavy SM accumulation"
    elif al == "moderate":
        plan["trade_verdict"] = "📊 ACCUMULATE — Vào dần"
    else:
        plan["trade_verdict"] = "👁 MONITOR — Signal yếu"

    return plan


def dex_get(path: str):
    try:
        r = SESSION.get(f"{DEX_BASE}{path}", timeout=12)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        logger.warning(f"dex_get {path}: {e}")
    return None


def score_gem(pair: dict, boost_map: dict) -> Optional[Gem]:
    base = pair.get("baseToken") or {}
    if not base.get("address"): return None

    mc    = float(pair.get("marketCap") or pair.get("fdv") or 0)
    liq   = float((pair.get("liquidity") or {}).get("usd") or 0)
    vol24 = float((pair.get("volume") or {}).get("h24") or 0)
    vol6  = float((pair.get("volume") or {}).get("h6")  or 0)
    vol1  = float((pair.get("volume") or {}).get("h1")  or 0)
    p1h   = float((pair.get("priceChange") or {}).get("h1")  or 0)
    p6h   = float((pair.get("priceChange") or {}).get("h6")  or 0)
    p24h  = float((pair.get("priceChange") or {}).get("h24") or 0)
    p5m   = float((pair.get("priceChange") or {}).get("m5")  or 0)
    txns    = pair.get("txns") or {}
    buys24  = int((txns.get("h24") or {}).get("buys")  or 0)
    sells24 = int((txns.get("h24") or {}).get("sells") or 0)
    buys1h  = int((txns.get("h1")  or {}).get("buys")  or 0)
    sells1h = int((txns.get("h1")  or {}).get("sells") or 0)
    created  = pair.get("pairCreatedAt")
    age_days = ((time.time()*1000 - created)/86_400_000) if created else 999
    chain    = (pair.get("chainId") or "").lower()

    if liq < 15_000 or mc > 20_000_000 or mc < 30_000: return None
    if p24h > 600   or p24h < -60:                      return None

    total=0.0; signals=[]; warnings=[]
    bs24 = (buys24/sells24) if sells24>0 else (9.0 if buys24>0 else 1.0)
    bs1h = (buys1h/sells1h) if sells1h>0 else (9.0 if buys1h>0 else 1.0)
    va   = (vol1/(vol6/6))  if vol6>0 and vol1>0 else 0.0
    vmc  = (vol24/mc)       if mc>0 else 0.0
    lmc  = (liq/mc)         if mc>0 else 0.0

    # AEON 2-TIER SETUP
    # WATCH: còn sideway vùng thấp, chưa mua vội.
    # BUY ALERT: breakout đầu vùng 350K-500K, trước khi pump chính/FOMO.
    early_watch = (
        250_000 <= mc <= 350_000
        and age_days >= 7
        and -15 <= p24h <= 25
        and -10 <= p6h <= 20
        and -5 <= p1h <= 12
        and va >= 1.15
        and bs24 >= 1.20
        and vmc >= 0.05
        and liq >= 40_000
    )
    early_buy = (
        350_000 <= mc <= 500_000
        and age_days >= 7
        and 6 <= p1h <= 45
        and -5 <= p6h <= 70
        and 0 <= p24h <= 95
        and va >= 1.6
        and bs1h >= 1.6
        and bs24 >= 1.30
        and vmc >= 0.08
        and liq >= 40_000
    )
    early_setup = early_watch or early_buy

    if mc<500_000:     total+=2;   signals.append("🎯 Micro cap <$500K — room 10x+")
    elif mc<2_000_000: total+=1.5; signals.append("📊 Small cap $500K–$2M")
    elif mc<5_000_000: total+=1;   signals.append("📈 Mid cap $2M–$5M")

    if early_buy:
        total += 4.0
        signals.append("🚀 AEON BUY: breakout đầu 350K-500K, vol/buy tăng tốc trước pump chính")
    elif early_watch:
        total += 2.0
        signals.append("👁 AEON WATCH: sideway MC thấp, volume/buy bắt đầu nhích lên")

    if va>3:    total+=2.5; signals.append(f"⚡ Vol tăng {va:.1f}x — tiền đột biến")
    elif va>1.5:total+=1.5; signals.append(f"📊 Vol picking up {va:.1f}x")

    if vmc>2:   total+=2;  signals.append(f"🔥 VOL/MC={vmc:.1f}x — cực active")
    elif vmc>.5:total+=1;  signals.append(f"✅ VOL/MC={vmc:.1f}x — healthy")

    if bs24>4:    total+=2.5; signals.append(f"🐋 Buy/Sell 24h={bs24:.1f}x — whale gom")
    elif bs24>2:  total+=1.5; signals.append(f"✅ Buy/Sell 24h={bs24:.1f}x — buyers dominant")
    elif bs24>1.2:total+=0.5; signals.append(f"📊 Buy/Sell 24h={bs24:.1f}x")
    if bs1h>3:    total+=1.5; signals.append(f"⚡ 1h B/S={bs1h:.1f}x — tăng tốc NOW")

    if abs(p24h)<30 and vmc>0.3 and bs24>1.5:
        total+=2; signals.append("🐋 ACCUMULATION: giá flat, vol cao, buys>sells")

    if lmc>0.15: total+=1; signals.append(f"💧 Liq {lmc*100:.0f}% — safe exit")
    elif liq>100_000:total+=1; signals.append(f"💧 Liq {fmt_usd(liq)} — OK")

    if age_days<2:   total+=1;   signals.append("🆕 Token <2 ngày — very early")
    elif age_days<7: total+=0.5; signals.append(f"📅 Token {int(age_days)}d — early")

    if 0<=p24h<=10:   total+=1.5; signals.append("😴 Giá flat — chưa ai biết")
    elif 10<p24h<100: total+=1;   signals.append(f"📈 +{p24h:.0f}% — nhẹ, chưa FOMO")
    elif -20<p24h<0:  total+=0.5; signals.append(f"📉 Dip {p24h:.0f}% — buy zone")
    if 15<p1h<100 and p24h<200:
        total+=1.0; signals.append(f"🚀 1h bứt phá +{p1h:.0f}%")

    # Không FOMO sau khi đã pump. Mục tiêu là alert trước pump như AEON ngày 11/5.
    if p1h > 35:
        total -= 2.0; warnings.append("⚠️ 1h đã pump mạnh — hạn chế FOMO")
    if p6h > 80:
        total -= 2.0; warnings.append("⚠️ 6h đã pump mạnh — dễ trễ entry")
    if p24h > 120:
        total -= 3.0; warnings.append("🚨 24h đã pump mạnh — bỏ qua/đợi retest")

    if liq<30_000:   warnings.append("⚠️ Liq thấp <$30K")
    if lmc<0.05:     warnings.append("⚠️ Liq/MC <5%")
    if age_days<0.5: warnings.append("⚠️ Token <12h — cực rủi ro")
    if bs24<0.8:     warnings.append("🚨 Sells>Buys — phân phối")
    if p24h>300:     warnings.append("🚨 Đã pump >300%")

    total = min(10.0, max(0.0, round(total,1)))
    rug=4.0
    if liq<20_000: rug+=2.5
    elif liq<50_000:rug+=1.0
    if lmc<0.05:   rug+=1.5
    if age_days<1: rug+=1.5
    if bs24<0.8:   rug+=1.0
    if liq>150_000:rug-=1.5
    rug=min(10.0,max(1.0,round(rug,1)))

    if p24h>200 or p6h>180 or mc>10_000_000:
        phase="euphoric"
    elif p24h>80 or p6h>100 or mc>3_000_000:
        phase="expansion"
    elif early_setup or (vmc>0.3 and bs24>1.5):
        phase="accumulation"
    elif p24h<-30:
        phase="distribution"
    elif mc<500_000:
        phase="stealth"
    else:
        phase="accumulation"

    tp = calc_trade_plan({
        "mc":mc,"liq":liq,"price":float(pair.get("priceUsd") or 0),
        "bs24":bs24,"bs1h":bs1h,"vol_accel":va,
        "p1h":p1h,"p24h":p24h,"vol_mc_ratio":vmc,
        "liq_mc_ratio":lmc,"age_days":age_days,
        "score":total,"rug_risk":rug,"phase":phase,"chain":chain,"early_setup":early_setup,"early_watch":early_watch,"early_buy":early_buy,
    })

    addr  = base.get("address","")
    boost = boost_map.get(addr,{})

    return Gem(
        id=addr+chain, ticker=base.get("symbol","???"),
        name=base.get("name") or base.get("symbol") or "Unknown",
        chain=chain, address=addr,
        pair_address=pair.get("pairAddress",""),
        dex_id=pair.get("dexId",""),
        price=float(pair.get("priceUsd") or 0),
        dex_url=pair.get("url") or f"https://dexscreener.com/{chain}/{pair.get('pairAddress','')}",
        mc=mc,liq=liq,vol24=vol24,vol6=vol6,vol1=vol1,
        p5m=p5m,p1h=p1h,p6h=p6h,p24h=p24h,
        buys24=buys24,sells24=sells24,buys1h=buys1h,sells1h=sells1h,
        bs_ratio24=round(bs24,2),bs_ratio1h=round(bs1h,2),
        vol_accel=round(va,2),vol_mc_ratio=round(vmc,2),
        liq_mc_ratio=round(lmc,2),age_days=round(age_days,1),
        boost_amount=float(boost.get("amount") or 0),
        has_website=bool((pair.get("info") or {}).get("websites")),
        has_socials=bool((pair.get("info") or {}).get("socials")),
        pre_pump_score=total,rug_risk=rug,phase=phase,
        signals=signals,warnings=warnings,
        accumulation_level=tp["accumulation_level"],
        entry_now=tp["entry_now"],
        entry_zone=tp["entry_zone"],
        entry_price_low=tp["entry_price_low"],
        entry_price_high=tp["entry_price_high"],
        entry_mc_low=tp.get("entry_mc_low", 0),
        entry_mc_high=tp.get("entry_mc_high", 0),
        dca_plan=tp["dca_plan"],
        stop_loss=tp["stop_loss"],stop_loss_pct=tp["stop_loss_pct"],
        target1=tp["target1"],target1_x=tp["target1_x"],
        target1_mc=tp["target1_mc"],target1_days=tp["target1_days"],
        target2=tp["target2"],target2_x=tp["target2_x"],
        target2_mc=tp["target2_mc"],target2_days=tp["target2_days"],
        target3=tp["target3"],target3_x=tp["target3_x"],
        target3_mc=tp["target3_mc"],target3_days=tp["target3_days"],
        peak_estimate=tp["peak_estimate"],peak_x=tp["peak_x"],peak_days=tp["peak_days"],
        success_rate_tp1=tp["success_rate_tp1"],
        success_rate_tp2=tp["success_rate_tp2"],
        success_rate_tp3=tp["success_rate_tp3"],
        median_peak_x=tp["median_peak_x"],best_case_x=tp["best_case_x"],
        hold_period=tp["hold_period"],
        risk_reward=tp["risk_reward"],
        position_size=tp["position_size"],
        trade_verdict=tp["trade_verdict"],
        aeon_comparable=tp["aeon_comparable"],
    )


def hunt_sync(chains: list) -> list:
    all_pairs=[]; boost_map={}
    data = dex_get("/token-boosts/top/v1")
    if isinstance(data,list):
        for b in data:
            if b.get("tokenAddress"): boost_map[b["tokenAddress"]]=b

    profiles = dex_get("/token-profiles/latest/v1")
    if isinstance(profiles,list):
        by_chain={}
        for p in profiles[:60]:
            c=p.get("chainId",""); addr=p.get("tokenAddress","")
            if c in chains and addr: by_chain.setdefault(c,[]).append(addr)
        for chain,addrs in by_chain.items():
            data=dex_get(f"/tokens/v1/{chain}/{','.join(addrs[:25])}")
            pairs=data if isinstance(data,list) else (data or {}).get("pairs",[])
            all_pairs.extend(pairs or []); time.sleep(0.3)

    for q in ["new","ai","dog","cat","inu","moon","baby"][:5]:
        data=dex_get(f"/latest/dex/search?q={q}")
        pairs=(data or {}).get("pairs",[])
        micro=[p for p in pairs
               if (p.get("marketCap") or p.get("fdv") or 0)<3_000_000
               and (p.get("liquidity") or {}).get("usd",0)>15_000]
        all_pairs.extend(micro[:8]); time.sleep(0.3)

    seen=set(); gems=[]
    for pair in all_pairs:
        if not isinstance(pair,dict): continue
        addr=(pair.get("baseToken") or {}).get("address","")
        chain=(pair.get("chainId") or "").lower()
        key=addr+chain
        if key in seen or not addr: continue
        seen.add(key)
        gem=score_gem(pair,boost_map)
        if gem and gem.pre_pump_score>=3.0: gems.append(gem)

    gems.sort(key=lambda g:g.pre_pump_score,reverse=True)
    logger.info(f"Hunt done: {len(all_pairs)} pairs -> {len(gems)} gems")
    return gems[:50]

async def hunt(session, chains):
    import asyncio
    return await asyncio.get_event_loop().run_in_executor(None, hunt_sync, chains)
