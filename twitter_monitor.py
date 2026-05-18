"""
twitter_monitor.py — KOL Twitter Monitor (Nitter scraping, no API key)
Theo dõi tweets của top KOLs, detect token mentions, alert ngay
"""

import asyncio
import logging
import re
import time
import json
import hashlib
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# NITTER INSTANCES — fallback nếu 1 instance down
# ─────────────────────────────────────────────
NITTER_INSTANCES = [
    "https://nitter.poast.org",
    "https://nitter.privacydev.net",
    "https://nitter.net",
    "https://nitter.1d4.us",
    "https://nitter.kavin.rocks",
    "https://twiiit.com",
]

SESSION = requests.Session()
SESSION.verify  = False
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
})

# ─────────────────────────────────────────────
# KOL LIST — Twitter handles quan trọng nhất
# ─────────────────────────────────────────────
TOP_KOLS = {
    # Tier 1 — Cực kỳ market-moving
    "elonmusk":        {"name": "Elon Musk",        "tier": 1, "weight": 10},
    "VitalikButerin":  {"name": "Vitalik Buterin",  "tier": 1, "weight": 9},
    "cz_binance":      {"name": "CZ Binance",       "tier": 1, "weight": 8},
    "brian_armstrong": {"name": "Brian Armstrong",  "tier": 1, "weight": 8},

    # Tier 2 — Crypto influencers lớn
    "CryptoHayes":     {"name": "Arthur Hayes",     "tier": 2, "weight": 7},
    "inversebrah":     {"name": "Inversebrah",      "tier": 2, "weight": 6},
    "cobie":           {"name": "Cobie",            "tier": 2, "weight": 7},
    "lookonchain":     {"name": "LookOnChain",      "tier": 2, "weight": 6},
    "AltcoinGordon":   {"name": "Gordon",           "tier": 2, "weight": 5},
    "CryptoGodJohn":   {"name": "CryptoGodJohn",   "tier": 2, "weight": 5},
    "Murad_Mahuddin":  {"name": "Murad",            "tier": 2, "weight": 6},

    # Tier 3 — Meme coin focused
    "ansem":           {"name": "Ansem",            "tier": 3, "weight": 5},
    "dingalingts":     {"name": "Dingaling",        "tier": 3, "weight": 5},
    "blknoiz06":       {"name": "Blknoiz",          "tier": 3, "weight": 5},
    "KookCapitalLLC":  {"name": "Kook Capital",     "tier": 3, "weight": 4},
    "CryptoWizardd":   {"name": "CryptoWizard",     "tier": 3, "weight": 4},
    "yourfriendSOLO":  {"name": "SOLO",             "tier": 3, "weight": 4},
}

# ─────────────────────────────────────────────
# TOKEN PATTERN — detect ticker/contract trong tweet
# ─────────────────────────────────────────────
# Match: $TICKER, contract addresses ETH/SOL
TICKER_PATTERN   = re.compile(r'\$([A-Z]{2,10})\b')
ETH_ADDR_PATTERN = re.compile(r'0x[a-fA-F0-9]{40}')
SOL_ADDR_PATTERN = re.compile(r'\b[1-9A-HJ-NP-Za-km-z]{32,44}\b')

# Keywords cho thấy bullish intent
BULLISH_KEYWORDS = [
    "bought", "buying", "accumulating", "loading", "aping",
    "gem", "pump", "moon", "100x", "1000x", "send it",
    "wagmi", "ngmi", "bullish", "let's go", "letsgo",
    "to the moon", "lfg", "this is the one", "early",
    "just aped", "just bought", "adding more",
    "love this", "so bullish", "strong buy",
    "mua", "gom", "tăng", "pump", "x100",  # Vietnamese
]

# Keywords cần ignore (tin tức chung, không phải call)
IGNORE_KEYWORDS = [
    "bitcoin", "ethereum", "btc", "eth price",
    "macro", "fed", "interest rate", "inflation",
    "retweet", "follow", "giveaway", "airdrop",
]


@dataclass
class Tweet:
    kol_handle: str
    kol_name: str
    kol_tier: int
    kol_weight: int
    tweet_id: str
    text: str
    timestamp: float
    tickers: list = field(default_factory=list)
    addresses: list = field(default_factory=list)
    is_bullish: bool = False
    urgency: str = "low"   # low / medium / high / critical
    alert_msg: str = ""


@dataclass
class TokenAlert:
    ticker: str
    address: Optional[str]
    kol_handle: str
    kol_name: str
    kol_tier: int
    tweet_text: str
    timestamp: float
    urgency: str
    chain_hint: str = "unknown"  # eth / sol / unknown


def get_nitter_url(handle: str, instance: str) -> str:
    return f"{instance}/{handle}"


def fetch_nitter(handle: str, timeout: int = 8) -> Optional[str]:
    """Fetch Nitter page, try multiple instances."""
    for instance in NITTER_INSTANCES:
        try:
            url = get_nitter_url(handle, instance)
            r = SESSION.get(url, timeout=timeout)
            if r.status_code == 200 and "timeline" in r.text.lower():
                return r.text
        except Exception as e:
            logger.debug(f"Nitter {instance} failed for {handle}: {e}")
            continue
    return None


def parse_tweets(html: str, kol_handle: str) -> list[dict]:
    """Parse tweet texts từ Nitter HTML."""
    tweets = []

    # Extract tweet items
    # Nitter HTML structure: <div class="tweet-content media-body">
    tweet_blocks = re.findall(
        r'<div class="tweet-content media-body"[^>]*>(.*?)</div>',
        html, re.DOTALL
    )

    # Extract tweet IDs
    tweet_ids = re.findall(
        r'/status/(\d+)',
        html
    )

    # Extract timestamps
    timestamps = re.findall(
        r'<span class="tweet-date"[^>]*><a[^>]*title="([^"]+)"',
        html
    )

    for i, block in enumerate(tweet_blocks[:10]):  # last 10 tweets
        # Clean HTML tags
        text = re.sub(r'<[^>]+>', ' ', block)
        text = re.sub(r'\s+', ' ', text).strip()
        text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')

        tweet_id = tweet_ids[i] if i < len(tweet_ids) else f"{kol_handle}_{i}"

        tweets.append({
            "id":   tweet_id,
            "text": text,
            "ts":   time.time() - (i * 300),  # approximate
        })

    return tweets


def analyze_tweet(text: str, kol_info: dict) -> dict:
    """Analyze tweet để tìm token mentions và bullish signals."""
    text_lower = text.lower()
    result = {
        "tickers":    [],
        "eth_addrs":  [],
        "sol_addrs":  [],
        "is_bullish": False,
        "urgency":    "low",
        "skip":       False,
    }

    # Skip nếu toàn tin tức macro
    ignore_count = sum(1 for kw in IGNORE_KEYWORDS if kw in text_lower)
    if ignore_count >= 2:
        result["skip"] = True
        return result

    # Find tickers
    tickers = TICKER_PATTERN.findall(text)
    # Filter common non-crypto words
    skip_tickers = {"I", "A", "THE", "AND", "OR", "FOR", "NOT", "IN", "ON",
                    "AT", "TO", "RT", "DM", "PM", "AM", "USD", "CEO", "AI",
                    "US", "EU", "UK", "UN", "NFT", "DAO", "DEX", "CEX"}
    tickers = [t for t in tickers if t not in skip_tickers]
    result["tickers"] = tickers

    # Find addresses
    eth_addrs = ETH_ADDR_PATTERN.findall(text)
    result["eth_addrs"] = eth_addrs

    # Bullish check
    bullish_count = sum(1 for kw in BULLISH_KEYWORDS if kw in text_lower)
    result["is_bullish"] = bullish_count >= 1

    # Urgency scoring
    urgency_score = 0

    # KOL tier impact
    tier = kol_info.get("tier", 3)
    if tier == 1:   urgency_score += 4
    elif tier == 2: urgency_score += 2
    else:           urgency_score += 1

    # Token signal
    if tickers:     urgency_score += 2
    if eth_addrs:   urgency_score += 3  # contract address = very specific
    if bullish_count >= 2: urgency_score += 2
    if bullish_count >= 1: urgency_score += 1

    # Tier 1 + ticker = critical
    if tier == 1 and (tickers or eth_addrs):
        urgency_score += 3

    if urgency_score >= 8:   result["urgency"] = "critical"
    elif urgency_score >= 6: result["urgency"] = "high"
    elif urgency_score >= 4: result["urgency"] = "medium"
    else:                    result["urgency"] = "low"

    return result


def build_twitter_alert(tweet: Tweet) -> str:
    """Build Telegram message cho Twitter alert."""
    tier_emoji = {1: "🔴", 2: "🟠", 3: "🟡"}.get(tweet.kol_tier, "⚪")
    urgency_emoji = {
        "critical": "🚨🚨🚨",
        "high":     "🚨🚨",
        "medium":   "⚡",
        "low":      "📢",
    }.get(tweet.urgency, "📢")

    lines = [
        f"{'='*36}",
        f"{urgency_emoji} TWITTER KOL ALERT",
        f"{'='*36}",
        f"",
        f"{tier_emoji} @{tweet.kol_handle} — {tweet.kol_name}",
        f"   Tier {tweet.kol_tier} | Weight: {tweet.kol_weight}/10",
        f"",
        f"📝 TWEET:",
        f'"{tweet.text[:400]}"',
        f"",
    ]

    if tweet.tickers:
        lines += [
            f"🎯 TOKENS MENTIONED:",
            *[f"  ${t}" for t in tweet.tickers],
            f"",
        ]

    if tweet.addresses:
        lines += [
            f"📋 CONTRACT ADDRESSES:",
            *[f"  {a}" for a in tweet.addresses[:3]],
            f"",
        ]

    lines += [
        f"⚡ Urgency: {tweet.urgency.upper()}",
        f"🐂 Bullish signal: {'YES' if tweet.is_bullish else 'NO'}",
        f"",
        f"{'─'*36}",
        f"🔍 QUICK ACTIONS:",
    ]

    for ticker in tweet.tickers[:3]:
        lines.append(f"  Search: https://dexscreener.com/search?q={ticker}")

    for addr in tweet.addresses[:2]:
        lines += [
            f"  ETH: https://dexscreener.com/ethereum/{addr}",
            f"  BASE: https://dexscreener.com/base/{addr}",
        ]

    lines += [
        f"",
        f"  Twitter: https://twitter.com/{tweet.kol_handle}",
        f"",
        f"⚠️ DYOR | Act fast on tier 1 alerts | High risk",
    ]

    return "\n".join(lines)


# ─────────────────────────────────────────────
# SEEN TWEETS CACHE
# ─────────────────────────────────────────────
SEEN_TWEETS_FILE = Path("logs/seen_tweets.json")

def load_seen_tweets() -> set:
    if SEEN_TWEETS_FILE.exists():
        try:
            data = json.loads(SEEN_TWEETS_FILE.read_text())
            return set(data)
        except: pass
    return set()

def save_seen_tweets(seen: set):
    SEEN_TWEETS_FILE.parent.mkdir(exist_ok=True)
    # Keep only last 1000
    lst = list(seen)[-1000:]
    SEEN_TWEETS_FILE.write_text(json.dumps(lst))


# ─────────────────────────────────────────────
# MAIN MONITOR CLASS
# ─────────────────────────────────────────────
class TwitterMonitor:
    def __init__(self, bot, chat_id: str,
                 kols: dict = None,
                 min_urgency: str = "medium",
                 check_interval: int = 60):
        self.bot          = bot
        self.chat_id      = chat_id
        self.kols         = kols or TOP_KOLS
        self.min_urgency  = min_urgency
        self.interval     = check_interval
        self.seen_tweets  = load_seen_tweets()
        self.urgency_rank = {"low":0, "medium":1, "high":2, "critical":3}

    def _meets_urgency(self, urgency: str) -> bool:
        return self.urgency_rank.get(urgency, 0) >= self.urgency_rank.get(self.min_urgency, 1)

    async def check_kol(self, handle: str, kol_info: dict) -> list[Tweet]:
        """Check một KOL, return new tweets đáng alert."""
        results = []
        try:
            html = await asyncio.get_event_loop().run_in_executor(
                None, fetch_nitter, handle
            )
            if not html:
                logger.debug(f"No HTML for @{handle}")
                return []

            raw_tweets = parse_tweets(html, handle)

            for raw in raw_tweets:
                tweet_id = str(raw["id"])
                # Skip seen
                seen_key = f"{handle}:{tweet_id}"
                if seen_key in self.seen_tweets:
                    continue

                analysis = analyze_tweet(raw["text"], kol_info)
                if analysis["skip"]:
                    continue

                # Only alert if has token mention OR is critical
                has_signal = (
                    analysis["tickers"] or
                    analysis["eth_addrs"] or
                    analysis["urgency"] in ("high", "critical")
                )
                if not has_signal:
                    self.seen_tweets.add(seen_key)
                    continue

                if not self._meets_urgency(analysis["urgency"]):
                    self.seen_tweets.add(seen_key)
                    continue

                # Chỉ alert KOL có weight >= 8 (Tier 1)
                if kol_info.get("weight", 0) < 8:
                    self.seen_tweets.add(seen_key)
                    continue

                tweet = Tweet(
                    kol_handle  = handle,
                    kol_name    = kol_info["name"],
                    kol_tier    = kol_info["tier"],
                    kol_weight  = kol_info["weight"],
                    tweet_id    = tweet_id,
                    text        = raw["text"],
                    timestamp   = raw["ts"],
                    tickers     = analysis["tickers"],
                    addresses   = analysis["eth_addrs"] + analysis["sol_addrs"],
                    is_bullish  = analysis["is_bullish"],
                    urgency     = analysis["urgency"],
                )
                tweet.alert_msg = build_twitter_alert(tweet)
                results.append(tweet)
                self.seen_tweets.add(seen_key)

        except Exception as e:
            logger.warning(f"check_kol @{handle}: {e}")

        return results

    async def run_once(self) -> int:
        """Check tất cả KOLs một lần. Return số alerts gửi."""
        all_tweets = []

        # Check theo tier — tier 1 trước
        sorted_kols = sorted(
            self.kols.items(),
            key=lambda x: (x[1]["tier"], -x[1]["weight"])
        )

        for handle, info in sorted_kols:
            tweets = await self.check_kol(handle, info)
            all_tweets.extend(tweets)
            await asyncio.sleep(1.5)  # tránh spam nitter

        # Sort by urgency + tier
        all_tweets.sort(
            key=lambda t: (
                -self.urgency_rank.get(t.urgency, 0),
                -t.kol_weight
            )
        )

        # Gửi alerts
        sent = 0
        for tweet in all_tweets[:5]:  # max 5 twitter alerts per scan
            try:
                await self.bot.send_message(
                    chat_id=self.chat_id,
                    text=tweet.alert_msg,
                    disable_web_page_preview=True,
                )
                sent += 1
                await asyncio.sleep(1.0)
            except Exception as e:
                logger.error(f"Send tweet alert: {e}")

        save_seen_tweets(self.seen_tweets)

        if all_tweets:
            logger.info(f"Twitter: {len(all_tweets)} new alerts, sent {sent}")

        return sent

    async def run_loop(self):
        """Chạy liên tục."""
        logger.info(f"Twitter monitor started | {len(self.kols)} KOLs | interval={self.interval}s")
        check_num = 0
        while True:
            check_num += 1
            t0 = time.time()
            try:
                await self.run_once()
            except Exception as e:
                logger.error(f"Twitter loop error: {e}")
            elapsed = time.time() - t0
            wait = max(10, self.interval - elapsed)
            logger.debug(f"Twitter check #{check_num} done in {elapsed:.1f}s, next in {wait:.0f}s")
            await asyncio.sleep(wait)
