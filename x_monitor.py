"""
x_monitor.py — X/Twitter Social Score Engine
Đo lường độ nổi trội của token trên X:
- Nitter scraping (free, no API key)
- Đếm mentions từ KOL accounts
- Tính FOMO score
- Detect viral momentum
"""

import requests
import time
import re
import logging
import json
from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# NITTER INSTANCES
# ─────────────────────────────────────────────
NITTER_INSTANCES = [
    "https://nitter.poast.org",
    "https://nitter.privacydev.net",
    "https://nitter.net",
    "https://nitter.1d4.us",
    "https://nitter.kavin.rocks",
]

SESSION = requests.Session()
SESSION.verify = False
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.5",
})

# ─────────────────────────────────────────────
# KOL TIERS — theo dõi ai mention token
# ─────────────────────────────────────────────
KOL_TIERS = {
    # Tier 1 — Market moving (10 điểm/mention)
    "elonmusk":        {"name": "Elon Musk",       "tier": 1, "score": 10},
    "VitalikButerin":  {"name": "Vitalik",          "tier": 1, "score": 9},
    "cz_binance":      {"name": "CZ",               "tier": 1, "score": 8},
    "brian_armstrong": {"name": "Brian Armstrong",  "tier": 1, "score": 8},

    # Tier 2 — Crypto influencers (5-7 điểm)
    "cobie":           {"name": "Cobie",            "tier": 2, "score": 7},
    "CryptoHayes":     {"name": "Arthur Hayes",     "tier": 2, "score": 7},
    "Murad_Mahuddin":  {"name": "Murad",            "tier": 2, "score": 6},
    "lookonchain":     {"name": "LookOnChain",      "tier": 2, "score": 6},
    "inversebrah":     {"name": "Inversebrah",      "tier": 2, "score": 6},
    "RookieXBT":       {"name": "RookieXBT",        "tier": 2, "score": 5},

    # Tier 3 — Meme/degen focused (3-4 điểm)
    "ansem":           {"name": "Ansem",            "tier": 3, "score": 5},
    "dingalingts":     {"name": "Dingaling",        "tier": 3, "score": 4},
    "blknoiz06":       {"name": "Blknoiz",          "tier": 3, "score": 4},
    "KookCapitalLLC":  {"name": "Kook Capital",     "tier": 3, "score": 4},
    "yourfriendSOLO":  {"name": "SOLO",             "tier": 3, "score": 3},
    "CryptoGodJohn":   {"name": "CryptoGodJohn",   "tier": 3, "score": 3},
    "CryptoWizardd":   {"name": "CryptoWizard",    "tier": 3, "score": 3},
    "AltcoinGordon":   {"name": "Gordon",           "tier": 3, "score": 3},
}

# ─────────────────────────────────────────────
# SOCIAL SCORE DATACLASS
# ─────────────────────────────────────────────
@dataclass
class XSocialScore:
    ticker: str
    address: str

    # Raw counts
    total_mentions: int = 0
    kol_mentions: int = 0
    tier1_mentions: int = 0
    tier2_mentions: int = 0
    tier3_mentions: int = 0

    # KOL details
    mentioning_kols: list = field(default_factory=list)  # [(handle, name, tier, tweet)]

    # Scores
    kol_score: float = 0.0       # 0-10: weighted KOL score
    fomo_score: float = 0.0      # 0-10: FOMO momentum
    viral_score: float = 0.0     # 0-10: viral potential
    social_total: float = 0.0    # 0-10: tổng hợp

    # Signals
    signals: list = field(default_factory=list)
    is_viral: bool = False
    is_kol_backed: bool = False
    top_kol: str = ""
    top_tweet: str = ""


# ─────────────────────────────────────────────
# NITTER SEARCH
# ─────────────────────────────────────────────
def nitter_search(query: str, instance: str, limit: int = 20) -> list:
    """Search tweets về một ticker/address trên Nitter."""
    tweets = []
    try:
        url = f"{instance}/search"
        params = {"q": query, "f": "tweets"}
        r = SESSION.get(url, params=params, timeout=8)
        if r.status_code != 200:
            return []

        html = r.text

        # Extract tweet content
        blocks = re.findall(
            r'<div class="tweet-content media-body"[^>]*>(.*?)</div>',
            html, re.DOTALL
        )
        usernames = re.findall(
            r'<a class="username"[^>]*>@([^<]+)</a>',
            html
        )
        tweet_ids = re.findall(r'/status/(\d+)', html)

        for i, block in enumerate(blocks[:limit]):
            text = re.sub(r'<[^>]+>', ' ', block)
            text = re.sub(r'\s+', ' ', text).strip()
            text = text.replace('&amp;','&').replace('&lt;','<').replace('&gt;','>')
            user = usernames[i] if i < len(usernames) else "unknown"
            tid  = tweet_ids[i]  if i < len(tweet_ids)  else f"{query}_{i}"
            tweets.append({
                "id": tid,
                "user": user.lower(),
                "text": text,
                "ts": time.time() - i * 300,
            })

    except Exception as e:
        logger.debug(f"Nitter search {query}@{instance}: {e}")
    return tweets


def search_twitter(query: str, limit: int = 30) -> list:
    """Try multiple Nitter instances."""
    for instance in NITTER_INSTANCES:
        tweets = nitter_search(query, instance, limit)
        if tweets:
            return tweets
        time.sleep(0.3)
    return []


def check_kol_timeline(handle: str, ticker: str, instance: str) -> Optional[dict]:
    """Check KOL timeline có mention ticker không."""
    try:
        url = f"{instance}/{handle}"
        r = SESSION.get(url, timeout=8)
        if r.status_code != 200:
            return None

        html = r.text
        ticker_lower = ticker.lower()
        ticker_dollar = f"${ticker.upper()}"

        # Check if ticker mentioned in page
        if ticker_lower not in html.lower() and ticker_dollar.lower() not in html.lower():
            return None

        # Extract the specific tweet mentioning ticker
        blocks = re.findall(
            r'<div class="tweet-content media-body"[^>]*>(.*?)</div>',
            html, re.DOTALL
        )
        for block in blocks:
            text = re.sub(r'<[^>]+>', ' ', block)
            text = re.sub(r'\s+', ' ', text).strip()
            if ticker_lower in text.lower() or ticker_dollar.lower() in text.lower():
                return {"text": text[:300], "ts": time.time()}

    except Exception as e:
        logger.debug(f"KOL check {handle}: {e}")
    return None


# ─────────────────────────────────────────────
# MAIN SOCIAL SCORE FUNCTION
# ─────────────────────────────────────────────
def get_social_score(
    ticker: str,
    address: str = "",
    chain: str = "base",
    fast_mode: bool = True,   # True = chỉ search, không check từng KOL
) -> XSocialScore:
    """
    Tính X/Twitter social score cho một token.
    fast_mode=True: chỉ search ticker → nhanh hơn
    fast_mode=False: check từng KOL timeline → chính xác hơn
    """
    result = XSocialScore(ticker=ticker, address=address)
    if not ticker or ticker == "???":
        return result

    ticker_upper = ticker.upper()
    queries = [
        f"${ticker_upper}",
        f"#{ticker_upper}",
        ticker_upper if len(ticker_upper) >= 4 else None,
    ]
    if address:
        queries.append(address[:8])  # first 8 chars of contract

    queries = [q for q in queries if q]

    # ── 1. Search Twitter mentions ──
    all_tweets = []
    for q in queries[:2]:  # max 2 queries
        tweets = search_twitter(q, limit=30)
        all_tweets.extend(tweets)
        time.sleep(0.5)

    # Dedupe by tweet id
    seen_ids = set()
    unique_tweets = []
    for t in all_tweets:
        if t["id"] not in seen_ids:
            seen_ids.add(t["id"])
            unique_tweets.append(t)

    result.total_mentions = len(unique_tweets)

    # ── 2. Check KOL mentions ──
    kol_weighted_score = 0.0
    mentioned_kols = set()

    for tweet in unique_tweets:
        user = tweet["user"].lower().strip("@")
        if user in KOL_TIERS:
            kol_info = KOL_TIERS[user]
            if user not in mentioned_kols:
                mentioned_kols.add(user)
                result.kol_mentions += 1
                kol_weighted_score += kol_info["score"]
                result.mentioning_kols.append((
                    user, kol_info["name"],
                    kol_info["tier"], tweet["text"][:150]
                ))
                if kol_info["tier"] == 1:
                    result.tier1_mentions += 1
                    if not result.top_kol:
                        result.top_kol = f"@{user} ({kol_info['name']})"
                        result.top_tweet = tweet["text"][:200]
                elif kol_info["tier"] == 2:
                    result.tier2_mentions += 1
                elif kol_info["tier"] == 3:
                    result.tier3_mentions += 1

    # ── 3. Fast KOL check (nếu không tìm thấy qua search) ──
    if not fast_mode and result.kol_mentions == 0:
        # Check tier 1+2 KOLs trực tiếp
        high_kols = [(h, i) for h, i in KOL_TIERS.items() if i["tier"] <= 2]
        for handle, info in high_kols[:8]:
            for instance in NITTER_INSTANCES[:2]:
                mention = check_kol_timeline(handle, ticker_upper, instance)
                if mention and handle not in mentioned_kols:
                    mentioned_kols.add(handle)
                    result.kol_mentions += 1
                    kol_weighted_score += info["score"]
                    result.mentioning_kols.append((
                        handle, info["name"], info["tier"], mention["text"]
                    ))
                    if info["tier"] == 1:
                        result.tier1_mentions += 1
                        result.top_kol = f"@{handle} ({info['name']})"
                        result.top_tweet = mention["text"]
                    elif info["tier"] == 2:
                        result.tier2_mentions += 1
                    break
            time.sleep(0.5)

    # ── 4. Compute scores ──

    # KOL Score (0-10)
    # Normalize: tier1 mention = 10, tier2 = 7, multiple KOLs stacks
    kol_score = min(10.0, kol_weighted_score / 2.5)
    result.kol_score = round(kol_score, 1)

    # FOMO Score (0-10)
    # Dựa trên total mentions volume
    if result.total_mentions >= 50:   fomo = 9.0
    elif result.total_mentions >= 30: fomo = 7.5
    elif result.total_mentions >= 15: fomo = 6.0
    elif result.total_mentions >= 8:  fomo = 4.5
    elif result.total_mentions >= 3:  fomo = 3.0
    elif result.total_mentions >= 1:  fomo = 1.5
    else:                              fomo = 0.0
    # Boost nếu có KOL
    if result.tier1_mentions >= 1: fomo = min(10, fomo + 3.0)
    if result.tier2_mentions >= 2: fomo = min(10, fomo + 1.5)
    if result.tier2_mentions >= 1: fomo = min(10, fomo + 0.8)
    result.fomo_score = round(fomo, 1)

    # Viral Score (0-10)
    viral = 0.0
    if result.tier1_mentions >= 1:   viral += 6.0
    if result.tier2_mentions >= 3:   viral += 4.0
    elif result.tier2_mentions >= 2: viral += 3.0
    elif result.tier2_mentions >= 1: viral += 2.0
    if result.tier3_mentions >= 5:   viral += 3.0
    elif result.tier3_mentions >= 3: viral += 2.0
    elif result.tier3_mentions >= 1: viral += 1.0
    if result.total_mentions >= 20:  viral += 2.0
    elif result.total_mentions >= 10:viral += 1.0
    result.viral_score = round(min(10.0, viral), 1)

    # Total Social Score
    result.social_total = round(
        result.kol_score * 0.4 +
        result.fomo_score * 0.35 +
        result.viral_score * 0.25,
        1
    )

    # Flags
    result.is_viral     = result.social_total >= 7.0
    result.is_kol_backed= result.kol_mentions >= 1

    # Signals
    if result.tier1_mentions >= 1:
        result.signals.append(f"🚨 TIER1 KOL: {result.top_kol} mentioned ${ticker_upper}")
    if result.tier2_mentions >= 2:
        result.signals.append(f"⭐ {result.tier2_mentions} Tier2 KOLs mentioned")
    elif result.tier2_mentions == 1:
        result.signals.append(f"⭐ 1 Tier2 KOL mentioned")
    if result.tier3_mentions >= 3:
        result.signals.append(f"📢 {result.tier3_mentions} Tier3 KOLs mentioned")
    if result.total_mentions >= 20:
        result.signals.append(f"🔥 {result.total_mentions} total X mentions — FOMO building")
    elif result.total_mentions >= 8:
        result.signals.append(f"📊 {result.total_mentions} X mentions — gaining attention")
    if result.is_viral:
        result.signals.append(f"🌐 VIRAL: Social score {result.social_total}/10")

    logger.info(
        f"${ticker_upper} social: mentions={result.total_mentions} "
        f"kols={result.kol_mentions}(t1={result.tier1_mentions},t2={result.tier2_mentions}) "
        f"fomo={result.fomo_score} viral={result.viral_score}"
    )
    return result


# ─────────────────────────────────────────────
# BATCH SOCIAL SCAN
# ─────────────────────────────────────────────
def batch_social_scan(gems: list, top_n: int = 5) -> dict:
    """
    Scan social score cho top N gems.
    Return: {gem_id: XSocialScore}
    """
    results = {}
    # Chỉ scan top gems để tiết kiệm time
    for gem in gems[:top_n]:
        try:
            score = get_social_score(
                ticker=gem.ticker,
                address=gem.address,
                chain=gem.chain,
                fast_mode=True,
            )
            results[gem.id] = score
            time.sleep(1.0)  # tránh spam nitter
        except Exception as e:
            logger.warning(f"Social scan {gem.ticker}: {e}")
    return results


# ─────────────────────────────────────────────
# FORMAT FOR TELEGRAM
# ─────────────────────────────────────────────
def format_social_block(score: XSocialScore) -> str:
    """Format social score block cho Telegram alert."""
    if score.social_total == 0 and score.total_mentions == 0:
        return ""

    lines = [
        f"{'─'*36}",
        f"🐦 X/TWITTER SOCIAL SCORE",
        f"  FOMO:   {score.fomo_score}/10  {'🔥' if score.fomo_score>=7 else '📊' if score.fomo_score>=4 else '😴'}",
        f"  Viral:  {score.viral_score}/10  {'🌐' if score.viral_score>=7 else '📈' if score.viral_score>=4 else '—'}",
        f"  KOL:    {score.kol_score}/10   {'⭐' if score.kol_score>=5 else '—'}",
        f"  TOTAL:  {score.social_total}/10",
        f"",
        f"  Mentions: {score.total_mentions} tweets",
        f"  KOLs: T1={score.tier1_mentions} T2={score.tier2_mentions} T3={score.tier3_mentions}",
    ]

    if score.top_kol:
        lines += [
            f"",
            f"  🏆 TOP KOL: {score.top_kol}",
            f"  💬 \"{score.top_tweet[:120]}...\"" if len(score.top_tweet)>120
            else f"  💬 \"{score.top_tweet}\"",
        ]

    for sig in score.signals[:3]:
        lines.append(f"  {sig}")

    if score.mentioning_kols:
        lines.append(f"")
        lines.append(f"  Mentioned by:")
        for handle, name, tier, _ in score.mentioning_kols[:5]:
            tier_e = "🔴" if tier==1 else "🟠" if tier==2 else "🟡"
            lines.append(f"  {tier_e} @{handle} ({name})")

    return "\n".join(lines)
