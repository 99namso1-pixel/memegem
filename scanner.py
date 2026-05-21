"""
scanner.py v6 — Optimized cho TSG/AEON/WORLDCUP class gems
Target: bắt token ở $20-100K MC trước khi pump 10-100x
Calibrated từ: TSG (143x/3h), AEON (28x/6d), WORLDCUP (33x/3h)
"""

import requests, time, logging, urllib3
from dataclasses import dataclass, field
from typing import Optional

try:
    from gmgn import hunt_gmgn_new_tokens, analyze_token as gmgn_analyze, GMGNTokenData
    GMGN_AVAILABLE = True
except ImportError:
    GMGN_AVAILABLE = False

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger   = logging.getLogger(__name__)
DEX_BASE = "https://api.dexscreener.com"
SESSION  = requests.Session()
SESSION.verify = False
SESSION.headers.update({"User-Agent": "Mozilla/5.0"})

CHAIN_LABEL = {"solana":"SOL","ethereum":"ETH","base":"BASE","bsc":"BSC","arbitrum":"ARB"}

# ─────────────────────────────────────────────────────────────
# HISTORICAL PUMP DATA — calibrated từ TSG, AEON, WORLDCUP
# ─────────────────────────────────────────────────────────────
PUMP_DATA = {
    ("base",  "extreme"): {"median_peak":40.0,"p25":15.0,"p75":100.0,"days_tp1":0.05,"days_tp2":0.2,"days_tp3":0.5,"days_peak":1.0,"success_tp1":80,"success_tp2":60,"success_tp3":38},
    ("base",  "heavy"):   {"median_peak":20.0,"p25":8.0, "p75":50.0, "days_tp1":0.1, "days_tp2":0.4,"days_tp3":1.0,"days_peak":2.0,"success_tp1":72,"success_tp2":52,"success_tp3":30},
    ("base",  "moderate"):{"median_peak":8.0, "p25":3.0, "p75":20.0, "days_tp1":0.3, "days_tp2":1.0,"days_tp3":3.0,"days_peak":5.0,"success_tp1":58,"success_tp2":38,"success_tp3":18},
    ("eth",   "extreme"): {"median_peak":30.0,"p25":10.0,"p75":80.0, "days_tp1":0.1, "days_tp2":0.5,"days_tp3":2.0,"days_peak":5.0,"success_tp1":75,"success_tp2":55,"success_tp3":32},
    ("eth",   "heavy"):   {"median_peak":15.0,"p25":5.0, "p75":40.0, "days_tp1":0.2, "days_tp2":0.8,"days_tp3":3.0,"days_peak":7.0,"success_tp1":68,"success_tp2":48,"success_tp3":25},
    ("eth",   "moderate"):{"median_peak":6.0, "p25":2.5, "p75":15.0, "days_tp1":0.5, "days_tp2":2.0,"days_tp3":6.0,"days_peak":10.0,"success_tp1":55,"success_tp2":35,"success_tp3":16},
    ("sol",   "extreme"): {"median_peak":25.0,"p25":10.0,"p75":60.0, "days_tp1":0.05,"days_tp2":0.3,"days_tp3":1.0,"days_peak":3.0,"success_tp1":82,"success_tp2":62,"success_tp3":40},
    ("sol",   "heavy"):   {"median_peak":12.0,"p25":5.0, "p75":28.0, "days_tp1":0.1, "days_tp2":0.5,"days_tp3":1.5,"days_peak":4.0,"success_tp1":74,"success_tp2":54,"success_tp3":30},
    ("sol",   "moderate"):{"median_peak":5.0, "p25":2.0, "p75":12.0, "days_tp1":0.2, "days_tp2":1.0,"days_tp3":3.0,"days_peak":6.0,"success_tp1":60,"success_tp2":40,"success_tp3":18},
    ("sol",   "light"):   {"median_peak":2.5, "p25":1.3, "p75":6.0,  "days_tp1":0.5, "days_tp2":2.0,"days_tp3":5.0,"days_peak":8.0,"success_tp1":45,"success_tp2":22,"success_tp3":8},
    ("eth",   "light"):   {"median_peak":3.0, "p25":1.5, "p75":7.0,  "days_tp1":1.0, "days_tp2":3.0,"days_tp3":7.0,"days_peak":12.0,"success_tp1":42,"success_tp2":20,"success_tp3":7},
    ("base",  "light"):   {"median_peak":3.5, "p25":1.5, "p75":8.0,  "days_tp1":0.5, "days_tp2":1.5,"days_tp3":4.0,"days_peak":7.0,"success_tp1":44,"success_tp2":22,"success_tp3":8},
}

def get_pump_data(chain:str, al:str) -> dict:
    ct = "sol" if chain=="solana" else "base" if chain=="base" else "eth"
    return PUMP_DATA.get((ct,al), PUMP_DATA.get(("eth","moderate"),{}))

def fmt_usd(v:float) -> str:
    if v>=1_000_000: return f"${v/1_000_000:.2f}M"
    if v>=1_000:     return f"${v/1_000:.0f}K"
    return f"${v:.0f}"

def fmt_days(d:float) -> str:
    if d<0.1:  return f"~{d*60:.0f}phút"
    if d<1:    return f"~{d*24:.0f}h"
    return f"~{d:.0f} ngày"

# ─────────────────────────────────────────────────────────────
# GEM DATACLASS
# ─────────────────────────────────────────────────────────────
@dataclass
class Gem:
    id:str; ticker:str; name:str; chain:str
    address:str; pair_address:str; dex_id:str
    price:float; dex_url:str
    mc:float=0; liq:float=0; vol24:float=0; vol6:float=0; vol1:float=0
    p5m:float=0; p1h:float=0; p6h:float=0; p24h:float=0
    buys24:int=0; sells24:int=0; buys1h:int=0; sells1h:int=0
    bs_ratio24:float=1.0; bs_ratio1h:float=1.0
    vol_accel:float=0.0; vol_mc_ratio:float=0.0; liq_mc_ratio:float=0.0
    age_days:float=0.0; boost_amount:float=0
    has_website:bool=False; has_socials:bool=False
    pre_pump_score:float=0; rug_risk:float=5.0
    phase:str="unknown"
    flat_base:bool=False; flat_base_hours:int=0
    breakout_candle:bool=False; pre_ath:bool=True
    stealth_accum:bool=False; stealth_hours:int=0
    # GMGN
    gmgn_rug_score:float=0.0; gmgn_quality:float=0.0
    gmgn_insider_pct:float=0.0; gmgn_dev_pct:float=0.0
    gmgn_sniper_count:int=0; gmgn_sm_wallets:int=0
    gmgn_kol_count:int=0; gmgn_lp_burned:bool=False
    gmgn_renounced:bool=False; gmgn_honeypot:bool=False
    gmgn_signals:list=field(default_factory=list)
    gmgn_warnings:list=field(default_factory=list)
    # Dev Quality Score
    dev_score:float=0.0
    dev_verdict:str=""
    hold_quality:str=""
    dev_reasons:list=field(default_factory=list)
    dev_warnings:list=field(default_factory=list)
    # Trade plan
    accumulation_level:str="none"
    entry_now:bool=False; entry_zone:str=""
    entry_price_low:float=0; entry_price_high:float=0
    entry_mc_low:float=0; entry_mc_high:float=0
    dca_plan:str=""
    stop_loss:str=""; stop_loss_pct:float=0
    target1:str=""; target1_x:float=0; target1_mc:float=0; target1_days:str=""
    target2:str=""; target2_x:float=0; target2_mc:float=0; target2_days:str=""
    target3:str=""; target3_x:float=0; target3_mc:float=0; target3_days:str=""
    peak_estimate:str=""; peak_x:float=0; peak_days:str=""
    success_rate_tp1:int=0; success_rate_tp2:int=0; success_rate_tp3:int=0
    median_peak_x:float=0; best_case_x:float=0
    hold_period:str=""; risk_reward:str=""
    position_size:str=""; trade_verdict:str=""
    aeon_comparable:str=""
    signals:list=field(default_factory=list)
    warnings:list=field(default_factory=list)
    # X/Twitter Social Score
    x_fomo_score:float=0.0
    x_viral_score:float=0.0
    x_kol_score:float=0.0
    x_social_total:float=0.0
    x_mentions:int=0
    x_kol_mentions:int=0
    x_tier1:int=0; x_tier2:int=0; x_tier3:int=0
    x_top_kol:str=""
    x_signals:list=field(default_factory=list)
    x_is_viral:bool=False


def dex_get(path:str):
    try:
        r = SESSION.get(f"{DEX_BASE}{path}", timeout=12)
        if r.status_code == 200: return r.json()
    except Exception as e:
        logger.warning(f"dex_get {path}: {e}")
    return None


# ─────────────────────────────────────────────────────────────
# TRADE PLAN ENGINE
# ─────────────────────────────────────────────────────────────
def calc_trade_plan(gd:dict) -> dict:
    mc=gd["mc"]; liq=gd["liq"]; price=gd["price"]
    bs24=gd["bs24"]; bs1h=gd["bs1h"]; va=gd["vol_accel"]
    p1h=gd["p1h"]; p24h=gd["p24h"]; vmc=gd["vol_mc_ratio"]
    lmc=gd["liq_mc_ratio"]; age=gd["age_days"]
    rug=gd["rug_risk"]; phase=gd["phase"]; chain=gd["chain"]
    flat_base=gd.get("flat_base",False)
    vol_spike=gd.get("vol_spike_1h",False)
    breakout_c=gd.get("breakout_candle",False)
    plan={}

    # Accumulation level
    acc=0
    if bs24>=5: acc+=4
    elif bs24>=3: acc+=3
    elif bs24>=2: acc+=2
    elif bs24>=1.5: acc+=1
    if bs1h>=4: acc+=2
    elif bs1h>=2: acc+=1
    if va>=5: acc+=3
    elif va>=3: acc+=2
    elif va>=2: acc+=1
    if vmc>=3: acc+=2
    elif vmc>=1: acc+=1
    if breakout_c: acc+=2

    if acc>=9:   al="extreme"
    elif acc>=6: al="heavy"
    elif acc>=4: al="moderate"
    elif acc>=2: al="light"
    else:        al="none"
    plan["accumulation_level"]=al

    # Historical pump data
    pd=get_pump_data(chain,al)
    if not pd: pd={"median_peak":5.0,"p25":2.0,"p75":12.0,"days_tp1":0.5,"days_tp2":2.0,"days_tp3":5.0,"days_peak":8.0,"success_tp1":50,"success_tp2":30,"success_tp3":15}

    # MC tier multiplier (nhỏ hơn = room nhiều hơn)
    if mc < 50_000:    mc_mult=4.0   # TSG-class: $30-50K = 100x+ possible
    elif mc < 100_000: mc_mult=3.0   # $50-100K = 50x possible
    elif mc < 200_000: mc_mult=2.0   # $100-200K = 20x possible
    elif mc < 500_000: mc_mult=1.4
    elif mc < 1_000_000: mc_mult=1.0
    elif mc < 3_000_000: mc_mult=0.7
    else:              mc_mult=0.4

    # Speed multiplier (BASE chain = pump nhanh hơn SOL)
    chain_spd = 0.4 if chain=="base" else 0.5 if chain=="solana" else 0.6

    # Momentum
    if p1h>50: mom=0.6
    elif p1h>20: mom=0.8
    elif p1h>5: mom=1.0
    else: mom=1.2

    base_peak=pd["median_peak"]*mc_mult*mom
    base_p75 =pd["p75"]*mc_mult*mom
    base_p25 =pd["p25"]*mc_mult*mom

    t1_x=max(1.5, round(base_p25*0.8,1))
    t2_x=max(t1_x+2, round(base_peak*0.7,1))
    t3_x=max(t2_x+5, round(base_p75*0.8,1))
    pk_x=max(t3_x+5, round(base_p75,1))

    spd=1.0
    if p1h>30: spd=0.3
    elif p1h>10: spd=0.6
    elif va>4: spd=0.4
    d1=max(0.03,pd["days_tp1"]*chain_spd*spd)
    d2=max(d1+0.05,pd["days_tp2"]*chain_spd*spd)
    d3=max(d2+0.1,pd["days_tp3"]*chain_spd*spd)
    dpk=max(d3+0.2,pd["days_peak"]*chain_spd*spd)

    plan.update({
        "target1":f"TP1: {t1_x}x → MC {fmt_usd(mc*t1_x)} | Sell 35% | ETA {fmt_days(d1)}",
        "target1_x":t1_x,"target1_mc":mc*t1_x,"target1_days":fmt_days(d1),
        "target2":f"TP2: {t2_x}x → MC {fmt_usd(mc*t2_x)} | Sell 35% | ETA {fmt_days(d2)}",
        "target2_x":t2_x,"target2_mc":mc*t2_x,"target2_days":fmt_days(d2),
        "target3":f"TP3: {t3_x}x → MC {fmt_usd(mc*t3_x)} | Sell 20% | ETA {fmt_days(d3)}",
        "target3_x":t3_x,"target3_mc":mc*t3_x,"target3_days":fmt_days(d3),
        "peak_estimate":f"PEAK est: {pk_x}x → MC {fmt_usd(mc*pk_x)} | Moon bag 10% | ETA {fmt_days(dpk)}",
        "peak_x":pk_x,"peak_days":fmt_days(dpk),
        "median_peak_x":round(base_peak,1),"best_case_x":round(base_p75,1),
        "success_rate_tp1":pd["success_tp1"],"success_rate_tp2":pd["success_tp2"],
        "success_rate_tp3":pd["success_tp3"],
        "hold_period":f"{fmt_days(d1)} → {fmt_days(dpk)}",
    })

    # Entry zone
    stealth = gd.get("stealth_accum", False)

    if flat_base and breakout_c:
        plan["entry_now"]=True
        plan["entry_zone"]="🚨 VÀO NGAY — Breakout candle, tích lũy vừa vỡ"
        plan["entry_mc_low"]=mc*0.97; plan["entry_mc_high"]=mc*1.15
        plan["dca_plan"]=f"60% NGAY tại MC {fmt_usd(mc)} + 40% retest {fmt_usd(mc*0.88)}"
    elif stealth and not flat_base:
        plan["entry_now"]=True
        plan["entry_zone"]=f"🐋 TÍCH LŨY — Vào dần trong lúc whale đang gom"
        plan["entry_mc_low"]=mc*0.92; plan["entry_mc_high"]=mc*1.05
        plan["dca_plan"]=f"DCA 3 lần: 33% ngay + 33% dip {fmt_usd(mc*0.90)} + 33% dip {fmt_usd(mc*0.82)}"
    elif phase in ("stealth","accumulation") and al in ("heavy","extreme"):
        plan["entry_now"]=True
        plan["entry_zone"]="MUA NGAY — SM/Whale đang gom mạnh"
        plan["entry_mc_low"]=mc*0.95; plan["entry_mc_high"]=mc*1.08
        plan["dca_plan"]=f"40% ngay tại MC {fmt_usd(mc)} + 60% nếu dip về {fmt_usd(mc*0.85)}"
    elif phase=="expansion" and al in ("heavy","extreme") and p1h<50:
        plan["entry_now"]=True
        plan["entry_zone"]="Expansion early — SM vẫn gom"
        plan["entry_mc_low"]=mc*0.93; plan["entry_mc_high"]=mc*1.10
        plan["dca_plan"]=f"25% ngay + 25% pullback về {fmt_usd(mc*0.85)}"
    elif al=="moderate" and phase in ("stealth","accumulation"):
        plan["entry_now"]=True
        plan["entry_zone"]="Accumulate — signal moderate"
        plan["entry_mc_low"]=mc*0.90; plan["entry_mc_high"]=mc*1.05
        plan["dca_plan"]=f"30% ngay + DCA 70% về {fmt_usd(mc*0.85)}"
    else:
        plan["entry_now"]=False
        plan["entry_zone"]="Chờ — chưa đủ signal"
        plan["entry_mc_low"]=mc*0.75; plan["entry_mc_high"]=mc*0.92
        plan["dca_plan"]=f"Chờ MC về {fmt_usd(mc*0.80)}–{fmt_usd(mc*0.90)}"
    plan["entry_price_low"]=round(price*0.95,10)
    plan["entry_price_high"]=round(price*1.08,10)

    # Stop loss
    if rug<=3:   sl=25
    elif rug<=5: sl=20
    elif rug<=7: sl=15
    else:        sl=10
    plan["stop_loss"]=f"-{sl}% từ entry → MC {fmt_usd(mc*(1-sl/100))}"
    plan["stop_loss_pct"]=sl

    # R/R
    avg_x=t1_x*0.35+t2_x*0.35+t3_x*0.20+pk_x*0.10
    rr=avg_x/(sl/100)
    plan["risk_reward"]=f"1:{rr:.0f}  (risk -{sl}% / avg reward ~{avg_x:.1f}x)"

    # Position size — nhỏ hơn cho token micro
    if mc<100_000:
        pos="0.5-1% portfolio (ultra micro)"
    elif mc<500_000:
        pos="1-2% portfolio" if rug>5 else "2-3% portfolio"
    else:
        pos="2-4% portfolio" if rug<=5 else "1-2% portfolio"
    plan["position_size"]=pos

    # AEON/TSG comparison — chỉ cho token mới thực sự
    age_d = gd.get("age_days", 999)
    is_new = age_d < 7
    if is_new and mc<100_000 and al in ("heavy","extreme"):
        plan["aeon_comparable"]=(
            f"TSG-class setup: nếu theo TSG pattern "
            f"({fmt_usd(mc)} → $5M = {5_000_000/max(mc,1):.0f}x trong 3h)"
        )
    elif is_new and mc<500_000 and al in ("heavy","extreme"):
        plan["aeon_comparable"]=(
            f"AEON-class: nếu theo AEON pattern "
            f"({fmt_usd(mc)} → $14M = {14_000_000/max(mc,1):.0f}x trong 6 ngày)"
        )
    else:
        plan["aeon_comparable"]=""

    # Verdict
    if not plan["entry_now"]:
        plan["trade_verdict"]="⏳ WATCH"
    elif mc<100_000 and al in ("extreme","heavy") and breakout_c:
        plan["trade_verdict"]="🚨 TSG-CLASS — VÀO NGAY"
    elif al=="extreme" and rug<=5:
        plan["trade_verdict"]="🚀 STRONG BUY — Extreme accumulation"
    elif al=="heavy" and rug<=6:
        plan["trade_verdict"]="✅ BUY — Heavy SM accumulation"
    elif al=="moderate":
        plan["trade_verdict"]="📊 ACCUMULATE"
    else:
        plan["trade_verdict"]="👁 MONITOR"

    return plan


# ─────────────────────────────────────────────────────────────
# SCORING ENGINE — Optimized for TSG/AEON/WORLDCUP patterns
# ─────────────────────────────────────────────────────────────
def score_gem(pair:dict, boost_map:dict) -> Optional[Gem]:
    base=pair.get("baseToken") or {}
    if not base.get("address"): return None

    mc   =float(pair.get("fdv") or pair.get("marketCap") or 0)
    liq  =float((pair.get("liquidity") or {}).get("usd") or 0)
    vol24=float((pair.get("volume") or {}).get("h24") or 0)
    vol6 =float((pair.get("volume") or {}).get("h6")  or 0)
    vol1 =float((pair.get("volume") or {}).get("h1")  or 0)
    p1h  =float((pair.get("priceChange") or {}).get("h1")  or 0)
    p6h  =float((pair.get("priceChange") or {}).get("h6")  or 0)
    p24h =float((pair.get("priceChange") or {}).get("h24") or 0)
    p5m  =float((pair.get("priceChange") or {}).get("m5")  or 0)
    txns =pair.get("txns") or {}
    buys24 =int((txns.get("h24") or {}).get("buys")  or 0)
    sells24=int((txns.get("h24") or {}).get("sells") or 0)
    buys1h =int((txns.get("h1")  or {}).get("buys")  or 0)
    sells1h=int((txns.get("h1")  or {}).get("sells") or 0)
    created=pair.get("pairCreatedAt")
    age_days=((time.time()*1000-created)/86_400_000) if created else 999
    chain=(pair.get("chainId") or "").lower()

    # ── Hard filters ──
    if mc > 15_000_000: return None
    if mc < 10_000:     return None
    if p24h > 900:      return None
    if p24h < -80:      return None
    # Liq filter theo chain
    if chain == "solana":
        # PumpSwap/PumpFun: liq thấp hơn nhiều vì pool SOL nhỏ
        min_liq = 3_000  if mc < 50_000   else                   5_000  if mc < 200_000  else                   8_000  if mc < 500_000  else 15_000
    elif chain == "base":
        min_liq = 10_000 if mc < 100_000  else                   20_000 if mc < 500_000  else 30_000
    else:  # ethereum
        min_liq = 8_000  if mc < 100_000  else                   15_000 if mc < 500_000  else 25_000
    if liq < min_liq:   return None

    total=0.0; signals=[]; warnings=[]
    bs24=(buys24/sells24) if sells24>0 else (9.0 if buys24>0 else 1.0)
    bs1h=(buys1h/sells1h) if sells1h>0 else (9.0 if buys1h>0 else 1.0)
    va  =(vol1/(vol6/6))  if vol6>0 and vol1>0 else 0.0
    vmc =(vol24/mc)       if mc>0 else 0.0
    lmc =(liq/mc)         if mc>0 else 0.0

    # ── FLAT BASE + BREAKOUT + STEALTH ACCUMULATION DETECTION ──
    flat_base=False; flat_base_score=0.0; flat_base_hours=0
    breakout_candle=False; pre_ath=True; vol_spike_1h=va>2.0
    stealth_accum=False; stealth_score=0.0  # whale gom âm thầm

    age_ok = age_days >= 0.08   # >= 2h

    # Pre-ATH detection — chính xác hơn
    # Token đã từng pump cao rồi dump = KHÔNG phải pre-ATH
    # Dấu hiệu đã có ATH cao:
    #   1. Token > 30 ngày tuổi + MC hiện tại thấp = đã dump từ ATH
    #   2. p24h âm nhiều + mc nhỏ = distribution/dead
    #   3. Age > 60d + mc < 500K = gần như chắc chắn đã có ATH cao hơn

    # Token mới thực sự (< 7 ngày) = chưa có ATH cao
    truly_new = age_days < 7

    # Token cũ mà MC nhỏ = ĐÃ pump rồi dump
    old_and_small = age_days > 30 and mc < 2_000_000

    # Đang dump mạnh = đang distribute từ ATH
    dumping = p24h < -30 and mc < 1_000_000

    # Pre-ATH = token mới, chưa từng pump
    pre_ath = truly_new and not dumping and mc < 5_000_000

    # Penalize token cũ mà MC nhỏ (đã từng pump)
    post_ath_dump = old_and_small or (age_days > 14 and mc < 300_000 and p24h < -10)

    # Flat base conditions
    price_flat_6h =(abs(p6h) < 20)
    price_flat_24h=(abs(p24h) < 60)
    vol_quiet_6h  =(vol6/max(vol24,1)) < 0.45

    # Breakout candle — TSG pattern: vol tăng mạnh + giá bứt
    breakout_candle=(
        va > 3.0 and
        p1h > 8 and
        p1h < 200 and
        abs(p6h) < 50
    )

    if price_flat_6h and price_flat_24h and vol_quiet_6h:
        flat_base=True; flat_base_hours=12; flat_base_score+=2.5
        if vol_spike_1h: flat_base_score+=1.5; flat_base_hours=8
        if breakout_candle: flat_base_score+=2.5
    elif abs(p6h)<30 and (vol6/max(vol24,1))<0.50 and bs24>1.5:
        flat_base=True; flat_base_hours=6; flat_base_score+=1.5
        if vol_spike_1h: flat_base_score+=1.0
        if breakout_candle: flat_base_score+=2.0

    # ── STEALTH ACCUMULATION DETECTION ──
    # Pattern: MANIFEST ngày 17 May — whale gom âm thầm
    # Vol 24h cao hơn vol 6h bất thường = tiền vào đều đặn không spike
    # Giá không tăng nhiều dù có buying = whale absorb selling pressure
    #
    # Signals:
    # 1. MC sideways (|p24h| < 20%) nhưng vol24 cao relative to liq
    # 2. Buys > Sells đều đặn (bs24 > 1.3x) nhưng giá không bứt
    # 3. Vol đang build up: vol6 > vol24/4 (nghĩa là 6h sau nhiều hơn avg)
    # 4. Age > 12h (không phải token quá mới)
    # 5. Liq tốt (whale cần liq để gom)

    vol_building   = vol6 > (vol24 / 4) * 0.8   # vol 6h gần bằng avg = đang build
    price_suppress = abs(p24h) < 25              # giá bị kìm, không pump dù có buy
    whale_buying   = bs24 >= 1.1 and buys24 >= 30  # mua đều đặn (1.1x đủ nếu kéo dài)
    mature_token   = age_days >= 0.5             # token đủ tuổi
    good_liq       = liq >= 50_000               # liq tốt = có whale gom được
    vol_vs_liq     = vmc >= 0.2                  # vol đủ lớn so với MC (0.2 = $200K vol / $1M MC)

    # Dead Vol Accumulation — AGENT pattern
    # Vol cực thấp nhiều ngày + giá flat + liq tốt = whale hold, chờ catalyst
    dead_vol_accum = (
        age_days >= 1.0 and          # token đủ tuổi (giảm từ 2d)
        abs(p24h) < 30 and           # giá không bứt mạnh
        vmc < 0.3 and                # vol thấp-trung bình
        liq >= 30_000 and            # liq tốt
        bs24 >= 1.0 and
        lmc >= 0.03
    )

    if dead_vol_accum and not stealth_accum and not flat_base:
        stealth_accum = True
        stealth_score = 2.5          # base score
        if liq >= 100_000: stealth_score += 1.0   # liq rất tốt
        if age_days >= 3:  stealth_score += 0.5   # hold 3+ ngày
        if age_days >= 5:  stealth_score += 0.5   # hold 5+ ngày = conviction
        flat_base_hours = int(age_days * 24)       # estimate hours holding
        signals.append(f"😴 DEAD VOL ACCUM: {int(age_days)}d vol flat — whale đang hold, chờ catalyst")
        if liq >= 100_000:
            signals.append(f"💧 Liq ${fmt_usd(liq)} với vol thấp = không ai bán = strong hands")

    # MANIFEST pattern: token 2d tuổi, vol24 cao, giá flat, bs > 1.3
    if (mature_token and price_suppress and whale_buying
            and vol_building and vol_vs_liq and not flat_base):
        stealth_accum = True
        stealth_score = 2.0

        # Bonus nếu liq tốt và token đủ mature
        if good_liq:          stealth_score += 1.0
        if bs24 >= 2.0:       stealth_score += 1.0  # mua mạnh hơn
        if vmc >= 0.5:        stealth_score += 0.5  # vol mạnh
        if age_days >= 1.0:   stealth_score += 0.5  # 1+ ngày tuổi = ổn định hơn
        if age_days >= 2.0:   stealth_score += 0.5  # 2+ ngày = whale đã gom lâu
        if age_days >= 1.0 and vmc >= 0.3: stealth_score += 0.5  # vol lớn kéo dài = SM gom
        # TOLYBOT/MANIFEST pattern: B/S thấp nhưng đều + vol cao = whale absorb sells
        if bs24 >= 1.1 and vmc >= 0.2 and age_days >= 1.0:
            stealth_score += 1.0
            flat_base_hours = max(flat_base_hours, int(age_days * 12))  # estimate hours

        # Estimate thời gian đã tích lũy
        if age_days >= 2:     flat_base_hours = 15  # như MANIFEST
        elif age_days >= 1:   flat_base_hours = 8
        else:                 flat_base_hours = 4

    # ── SCORING ──

    # Stealth accumulation bonus (phát hiện TRONG lúc tích lũy)
    if stealth_accum:
        total += stealth_score
        if bs24 >= 2.0 and good_liq:
            signals.append(f"🐋 STEALTH ACCUM: {flat_base_hours}h whale gom âm thầm — giá flat + vol cao")
        else:
            signals.append(f"👁 STEALTH ACCUM: {flat_base_hours}h tích lũy — buys>{bs24:.1f}x sells, giá không tăng")

    # Flat base bonus (cao nhất)
    if flat_base and breakout_candle and pre_ath:
        total+=flat_base_score
        signals.append(f"🚨 BREAKOUT: {flat_base_hours}h tích lũy VỪA VỠ — VÀO NGAY")
    elif flat_base and breakout_candle:
        total+=flat_base_score*0.85
        signals.append(f"🚀 BREAKOUT CANDLE: {flat_base_hours}h base bị phá")
    elif flat_base and vol_spike_1h and pre_ath:
        total+=flat_base_score*0.8
        signals.append(f"⚡ FLAT BASE + Vol tăng: {flat_base_hours}h tích lũy, sắp bứt")
    elif flat_base and pre_ath:
        total+=flat_base_score*0.6
        signals.append(f"📦 FLAT BASE {flat_base_hours}h — chờ breakout candle")

    # MC tier (TSG-class ultra micro được điểm cao nhất)
    if mc < 50_000:
        total+=3.5; signals.append(f"🚨 ULTRA MICRO ${fmt_usd(mc)} — TSG-class 100x+ room")
    elif mc < 100_000:
        total+=3.0; signals.append(f"🎯 Micro ${fmt_usd(mc)} — sweet spot 50x room")
    elif mc < 200_000:
        total+=2.5; signals.append(f"🎯 Micro ${fmt_usd(mc)} — 20-50x room")
    elif mc < 500_000:
        total+=2.0; signals.append(f"📊 Small ${fmt_usd(mc)} — 10x+ room")
    elif mc < 2_000_000:
        total+=1.5; signals.append(f"📈 Mid ${fmt_usd(mc)} — 5x+ room")
    else:
        total+=0.5

    # Volume acceleration
    if va>=5:    total+=3.0; signals.append(f"🔥 Vol tăng {va:.1f}x — tiền ào vào")
    elif va>=3:  total+=2.5; signals.append(f"⚡ Vol tăng {va:.1f}x — đột biến")
    elif va>=2:  total+=1.5; signals.append(f"📊 Vol picking up {va:.1f}x")
    elif va>=1.5:total+=0.8

    # VOL/MC ratio
    if vmc>=3:   total+=2.0; signals.append(f"🔥 VOL/MC={vmc:.1f}x — cực active")
    elif vmc>=1: total+=1.5; signals.append(f"✅ VOL/MC={vmc:.1f}x — healthy")
    elif vmc>=.5:total+=0.8; signals.append(f"📊 VOL/MC={vmc:.1f}x")

    # Buy pressure
    if bs24>=5:   total+=2.5; signals.append(f"🐋 B/S 24h={bs24:.1f}x — whale gom")
    elif bs24>=3: total+=2.0; signals.append(f"✅ B/S 24h={bs24:.1f}x — buyers dom")
    elif bs24>=2: total+=1.0; signals.append(f"📊 B/S 24h={bs24:.1f}x")
    elif bs24>=1.5:total+=0.5
    if bs1h>=4:   total+=1.5; signals.append(f"⚡ B/S 1h={bs1h:.1f}x — tăng tốc NOW")
    elif bs1h>=2: total+=0.8; signals.append(f"📊 B/S 1h={bs1h:.1f}x")

    # Accumulation pattern
    if abs(p24h)<40 and vmc>0.3 and bs24>1.5:
        total+=2.0; signals.append("🐋 ACCUMULATION: giá flat, vol cao, buys>sells")

    # Liquidity (đủ để exit)
    if lmc>=0.3:  total+=1.5; signals.append(f"💧 Liq {lmc*100:.0f}% MC — excellent")
    elif lmc>=0.1:total+=1.0; signals.append(f"💧 Liq {lmc*100:.0f}% MC — OK")
    elif liq>=100_000: total+=0.5

    # Age scoring — ưu tiên 1-5 ngày (VIRL/MANIFEST/TOLYBOT pattern)
    if 1.0 <= age_days <= 5.0:
        total+=2.0; signals.append(f"🎯 Token {age_days:.1f}d — SWEET SPOT 1-5d, pump potential cao nhất")
    elif 5.0 < age_days <= 14.0:
        total+=1.0; signals.append(f"📅 Token {int(age_days)}d — mature, still ok")
    elif 0.5 <= age_days < 1.0:
        total+=0.0  # neutral — chưa đủ 1 ngày
        signals.append(f"⏳ Token {age_days*24:.0f}h — chưa đủ 1d, chờ thêm")
    elif age_days < 0.5:
        total-=1.5  # penalize < 12h
        warnings.append(f"⚠️ Token {age_days*24:.0f}h — quá mới, rủi ro cao")
    elif age_days > 30:
        total-=0.5  # token quá cũ mà MC vẫn thấp = suspect

    # Price action
    if 0<=p24h<=15:    total+=1.5; signals.append("😴 Giá flat — chưa ai biết")
    elif 15<p24h<100:  total+=1.0; signals.append(f"📈 +{p24h:.0f}% — pumping nhẹ")
    elif -20<p24h<0:   total+=0.5; signals.append(f"📉 Dip {p24h:.0f}%")
    if 10<p1h<150 and p24h<300:
        total+=1.5; signals.append(f"🚀 1h +{p1h:.0f}% — momentum!")

    # Pre-ATH vs Post-ATH
    if pre_ath and mc < 200_000:
        total += 0.5; signals.append("🎯 Pre-ATH — token mới, chưa từng pump")
    elif post_ath_dump:
        total -= 1.5
        warnings.append(f"🚨 Post-ATH dump: token {int(age_days)}d tuổi, MC thấp bất thường — đã có ATH cao hơn")
    elif age_days > 30 and mc < 500_000:
        total -= 0.5
        warnings.append(f"⚠️ Token {int(age_days)}d tuổi + MC thấp — có thể đã pump/dump rồi")

    # Chain priority bonus — BASE > ETH > SOL
    if chain == "base":
        if mc < 500_000:
            total += 1.5; signals.append("🔵 BASE micro — TSG/MOLT class, highest priority")
        else:
            total += 1.0; signals.append("🔵 BASE chain — high pump potential")
    elif chain == "ethereum":
        if mc < 500_000:
            total += 1.0; signals.append("Ξ ETH micro — AEON/JUNO class")
        else:
            total += 0.5; signals.append("Ξ ETH chain")
    elif chain == "solana":
        total += 0.3; signals.append("◎ SOL chain")
    # BSC/others không bonus

    # ── WARNINGS ──
    if liq<20_000:   warnings.append(f"⚠️ Liq thấp ${fmt_usd(liq)}")
    if lmc<0.05:     warnings.append("⚠️ Liq/MC <5%")
    if age_days<0.08:warnings.append("⚠️ Token <2h — quá mới")
    if bs24<0.8:     warnings.append("🚨 Sells>Buys")
    if p24h>400:     warnings.append("🚨 Đã pump >400%")
    if mc<100_000 and liq<15_000: warnings.append("🚨 Ultra micro + liq thấp = rug risk cao")

    total=min(10.0,max(0.0,round(total,1)))

    # Rug risk
    rug=3.5
    if liq<15_000: rug+=2.5
    elif liq<30_000:rug+=1.5
    elif liq<50_000:rug+=0.8
    if lmc<0.05:   rug+=1.5
    if age_days<0.2:rug+=1.0
    if bs24<0.8:   rug+=1.0
    if liq>200_000:rug-=1.5
    if liq>500_000:rug-=0.5
    rug=min(10.0,max(1.0,round(rug,1)))

    # Phase
    if p24h>300 or mc>10_000_000:          phase="euphoric"
    elif post_ath_dump:                    phase="distribution"
    elif flat_base and breakout_candle:    phase="expansion"
    elif stealth_accum:                    phase="accumulation"  # MANIFEST pattern
    elif flat_base and vol_spike_1h:       phase="accumulation"
    elif flat_base:                         phase="accumulation"
    elif p24h>80 or mc>3_000_000:          phase="expansion"
    elif vmc>0.3 and bs24>1.5:             phase="accumulation"
    elif p24h<-40:                          phase="distribution"
    elif mc<200_000 and truly_new:          phase="stealth"
    else:                                   phase="accumulation"

    tp=calc_trade_plan({
        "mc":mc,"liq":liq,"price":float(pair.get("priceUsd") or 0),
        "bs24":bs24,"bs1h":bs1h,"vol_accel":va,
        "p1h":p1h,"p24h":p24h,"vol_mc_ratio":vmc,
        "liq_mc_ratio":lmc,"age_days":age_days,
        "score":total,"rug_risk":rug,"phase":phase,"chain":chain,
        "flat_base":flat_base,"vol_spike_1h":vol_spike_1h,
        "breakout_candle":breakout_candle,
        "stealth_accum":stealth_accum,
        "age_days":age_days,
    })

    addr =(base.get("address",""))
    boost=boost_map.get(addr,{})

    return Gem(
        id=addr+chain,ticker=base.get("symbol","???"),
        name=base.get("name") or base.get("symbol") or "Unknown",
        chain=chain,address=addr,
        pair_address=pair.get("pairAddress",""),
        dex_id=pair.get("dexId",""),
        price=float(pair.get("priceUsd") or 0),
        dex_url=pair.get("url") or f"https://dexscreener.com/{chain}/{pair.get('pairAddress','')}",
        mc=mc,liq=liq,vol24=vol24,vol6=vol6,vol1=vol1,
        p5m=p5m,p1h=p1h,p6h=p6h,p24h=p24h,
        buys24=buys24,sells24=sells24,buys1h=buys1h,sells1h=sells1h,
        bs_ratio24=round(bs24,2),bs_ratio1h=round(bs1h,2),
        vol_accel=round(va,2),vol_mc_ratio=round(vmc,2),
        liq_mc_ratio=round(lmc,2),age_days=round(age_days,3),
        boost_amount=float(boost.get("amount") or 0),
        has_website=bool((pair.get("info") or {}).get("websites")),
        has_socials=bool((pair.get("info") or {}).get("socials")),
        pre_pump_score=total,rug_risk=rug,phase=phase,
        flat_base=flat_base,flat_base_hours=flat_base_hours,
        breakout_candle=breakout_candle,pre_ath=pre_ath,
        stealth_accum=stealth_accum,stealth_hours=flat_base_hours,
        signals=signals,warnings=warnings,
        accumulation_level=tp["accumulation_level"],
        entry_now=tp["entry_now"],entry_zone=tp["entry_zone"],
        entry_price_low=tp["entry_price_low"],entry_price_high=tp["entry_price_high"],
        entry_mc_low=tp.get("entry_mc_low",0),entry_mc_high=tp.get("entry_mc_high",0),
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
        hold_period=tp["hold_period"],risk_reward=tp["risk_reward"],
        position_size=tp["position_size"],trade_verdict=tp["trade_verdict"],
        aeon_comparable=tp["aeon_comparable"],
    )


# ─────────────────────────────────────────────────────────────
# HUNT ENGINE — Multi-source scanning
# ─────────────────────────────────────────────────────────────
def hunt_sync(chains:list) -> list:
    all_pairs=[]; boost_map={}

    # 1. Boost map
    data=dex_get("/token-boosts/top/v1")
    if isinstance(data,list):
        for b in data:
            if b.get("tokenAddress"): boost_map[b["tokenAddress"]]=b

    # 2. NEW PAIRS — bắt token mới nhất
    # Scan nhiều DEX endpoints: default + uniswap-v4 + pumpswap + aerodrome
    for chain in chains:
        # Standard new pairs
        data=dex_get(f"/latest/dex/pairs/{chain}")
        new_pairs=(data.get("pairs",[]) if isinstance(data,dict) else data) or []

        # Uniswap V4 specifically (BASEMAXXING deploy ở đây)
        if chain in ("base","ethereum"):
            v4_data=dex_get(f"/latest/dex/pairs/{chain}/uniswap-v4")
            if v4_data:
                v4_pairs=(v4_data.get("pairs",[]) if isinstance(v4_data,dict) else v4_data) or []
                new_pairs.extend(v4_pairs)
                logger.debug(f"Uniswap V4 {chain}: {len(v4_pairs)} pairs")

        # Aerodrome (BASE native DEX — nhiều gem)
        if chain == "base":
            aero_data=dex_get(f"/latest/dex/pairs/base/aerodrome")
            if aero_data:
                aero_pairs=(aero_data.get("pairs",[]) if isinstance(aero_data,dict) else aero_data) or []
                new_pairs.extend(aero_pairs)

        # Filter: liq > $30K = đủ chặt để loại rug
        early=[p for p in new_pairs
               if (p.get("fdv") or p.get("marketCap") or 0) >= 15_000
               and (p.get("liquidity") or {}).get("usd",0) >= 30_000]
        all_pairs.extend(early[:50])
        logger.debug(f"New pairs {chain}: {len(early)} (liq>$30K)")
        time.sleep(0.15)

    # 3. BASE/ETH Gainers — BASE trước, ETH sau
    chain_order = [c for c in ["base","ethereum"] if c in chains]
    for chain in chain_order:
        endpoints = [
            f"/latest/dex/tokens/{chain}/gainers",
            f"/latest/dex/pairs/{chain}/new",
        ]
        # Thêm Uniswap V4 gainers riêng
        if chain in ("base","ethereum"):
            endpoints.append(f"/latest/dex/tokens/{chain}/trending")

        for endpoint in endpoints:
            data=dex_get(endpoint)
            pairs=(data.get("pairs",[]) if isinstance(data,dict)
                   else data if isinstance(data,list) else []) or []
            # Filter chặt: liq > $30K để loại rug
            filtered=[p for p in pairs
                      if 15_000<=(p.get("fdv") or p.get("marketCap") or 0)<=5_000_000
                      and (p.get("liquidity") or {}).get("usd",0)>=30_000]
            all_pairs.extend(filtered[:30])
            time.sleep(0.15)

    # 4. Token profiles (boosted)
    profiles=dex_get("/token-profiles/latest/v1")
    if isinstance(profiles,list):
        by_chain={}
        for p in profiles[:60]:
            c=p.get("chainId",""); addr=p.get("tokenAddress","")
            if c in chains and addr: by_chain.setdefault(c,[]).append(addr)
        for chain,addrs in by_chain.items():
            data=dex_get(f"/tokens/v1/{chain}/{','.join(addrs[:25])}")
            pairs=data if isinstance(data,list) else (data or {}).get("pairs",[])
            all_pairs.extend(pairs or []); time.sleep(0.2)

    # 5. SOL — PumpSwap + PumpFun + Trending
    if "solana" in chains:
        # PumpSwap new pairs (TOESCOIN-class)
        for dex_id in ["pumpswap","pump-fun","raydium","orca"]:
            data=dex_get(f"/latest/dex/pairs/solana/{dex_id}")
            if data:
                pairs=(data.get("pairs",[]) if isinstance(data,dict) else data) or []
                fresh=[p for p in pairs
                       if (p.get("fdv") or p.get("marketCap") or 0) >= 5_000
                       and (p.get("liquidity") or {}).get("usd",0) >= 8_000]
                all_pairs.extend(fresh[:40])
                logger.debug(f"SOL {dex_id}: {len(fresh)} pairs")
                time.sleep(0.15)

        # SOL trending h1/h6/h24
        for tf in ["h1","h6"]:
            data=dex_get(f"/latest/dex/tokens/solana/trending/{tf}")
            pairs=(data or {}).get("pairs",[])
            sol=[p for p in pairs
                 if 5_000<=(p.get("fdv") or p.get("marketCap") or 0)<=5_000_000
                 and (p.get("liquidity") or {}).get("usd",0)>=8_000]
            all_pairs.extend(sol[:25]); time.sleep(0.15)

        # SOL gainers
        data=dex_get("/latest/dex/tokens/solana/gainers")
        if data:
            pairs=(data.get("pairs",[]) if isinstance(data,dict) else [])
            gainers=[p for p in pairs
                     if 5_000<=(p.get("fdv") or p.get("marketCap") or 0)<=10_000_000
                     and (p.get("liquidity") or {}).get("usd",0)>=8_000]
            all_pairs.extend(gainers[:25])
            time.sleep(0.15)

        # SOL top volume — bắt VIRL-class (token 6d+ đang có vol tăng)
        for ep in ["/latest/dex/tokens/solana/trending",
                   "/latest/dex/tokens/solana/top"]:
            data=dex_get(ep)
            if data:
                pairs=(data.get("pairs",[]) if isinstance(data,dict) else [])
                top_vol=[p for p in pairs
                         if 100_000<=(p.get("fdv") or p.get("marketCap") or 0)<=10_000_000
                         and (p.get("liquidity") or {}).get("usd",0)>=50_000
                         and float((p.get("priceChange") or {}).get("h1",0) or 0)>5]
                all_pairs.extend(top_vol[:20])
                time.sleep(0.15)

    # 6. Keyword search — expanded để bắt TSG-class
    keywords=["new","pump","ai","dog","cat","inu","moon","pepe","based",
              "giant","sleep","world","trump","elon","baby","doge",
              "shib","chad","wagmi","the","coin","token","eth","sol",
              "base","frog","bird","fish","meme","gem","100x","1000x",
              "grok","meta","agent","game","nft","dao","defi","swap"]
    for q in keywords[:20]:
        data=dex_get(f"/latest/dex/search?q={q}")
        pairs=(data or {}).get("pairs",[])
        micro=[p for p in pairs
               if 8_000<=(p.get("fdv") or p.get("marketCap") or 0)<=3_000_000
               and (p.get("liquidity") or {}).get("usd",0)>=5_000]
        all_pairs.extend(micro[:15]); time.sleep(0.15)

    # 7. GMGN tokens — SOL new pairs qua GMGN (bắt PumpFun/PumpSwap gems)
    gmgn_tokens=[]
    if GMGN_AVAILABLE:
        try:
            gmgn_raw=hunt_gmgn_new_tokens([c for c in chains if c in ("solana","ethereum","base")])
            gmgn_tokens=gmgn_raw
            logger.info(f"GMGN: {len(gmgn_tokens)} tokens")
        except Exception as e:
            logger.warning(f"GMGN: {e}")

    # Score + dedupe
    seen=set(); gems=[]

    # Score Dexscreener pairs
    for pair in all_pairs:
        if not isinstance(pair,dict): continue
        addr=(pair.get("baseToken") or {}).get("address","")
        chain=(pair.get("chainId") or "").lower()
        key=addr+chain
        if key in seen or not addr: continue
        seen.add(key)
        gem=score_gem(pair,boost_map)
        if gem and gem.pre_pump_score>=3.5: gems.append(gem)

    # Score GMGN tokens
    for gt in gmgn_tokens:
        addr=gt.get("address",""); chain=gt.get("chain","solana")
        key=addr+chain
        if key in seen or not addr: continue
        seen.add(key)
        fake_pair={
            "baseToken":{"address":addr,"symbol":gt.get("ticker","???"),"name":gt.get("name","")},
            "chainId":chain,"pairAddress":addr,"dexId":"gmgn",
            "priceUsd":str(gt.get("price",0)),
            "fdv":gt.get("mc",0),"marketCap":gt.get("mc",0),
            "liquidity":{"usd":gt.get("liq",0)},
            "volume":{"h24":gt.get("vol24",0),"h6":gt.get("vol6",0),"h1":gt.get("vol1",0)},
            "priceChange":{"h1":gt.get("p1h",0),"h6":gt.get("p6h",0),"h24":gt.get("p24h",0),"m5":0},
            "txns":{"h24":{"buys":gt.get("buys24",0),"sells":gt.get("sells24",0)},"h1":{"buys":0,"sells":0}},
            "pairCreatedAt":(time.time()-gt.get("age_days",1)*86400)*1000,
            "url":gt.get("dex_url",""),"info":{},
        }
        gem=score_gem(fake_pair,boost_map)
        if gem and gem.pre_pump_score>=2.5:
            if gt.get("trending_1m"):
                gem.signals.insert(0,"🔥 GMGN Trending 1m")
                gem.pre_pump_score=min(10,gem.pre_pump_score+1.0)
            if gt.get("pumping_5m"):
                gem.signals.insert(0,"⚡ GMGN Pump 5m")
                gem.pre_pump_score=min(10,gem.pre_pump_score+0.5)
            gems.append(gem)

    # Sort: BASE > ETH > SOL + age 1-5d ưu tiên + breakout + score
    chain_rank = {"base": 0, "ethereum": 1, "solana": 2}

    def age_rank(g):
        # 1-5d = 0 (tốt nhất), <1d = 1, 5-14d = 2, >14d = 3
        if 1.0 <= g.age_days <= 5.0:  return 0
        if 0.5 <= g.age_days < 1.0:   return 1
        if 5.0 < g.age_days <= 14.0:  return 2
        return 3

    gems.sort(key=lambda g:(
        chain_rank.get(g.chain, 3),                              # BASE trước
        age_rank(g),                                             # 1-5d ưu tiên
        -(3 if g.breakout_candle else 1 if g.flat_base else 0),  # breakout
        -g.pre_pump_score,                                        # score cao
        g.mc,                                                     # MC nhỏ
    ))

    bc=sum(1 for g in gems if g.breakout_candle)
    fb=sum(1 for g in gems if g.flat_base)
    logger.info(
        f"Hunt: {len(all_pairs)} dex + {len(gmgn_tokens)} gmgn "
        f"-> {len(gems)} gems (🚨breakout:{bc} 📦flat:{fb})"
    )
    return gems[:150]


async def hunt(session,chains):
    import asyncio
    return await asyncio.get_event_loop().run_in_executor(None,hunt_sync,chains)
