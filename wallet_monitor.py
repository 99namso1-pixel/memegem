"""
wallet_monitor.py — Smart Wallet Monitor cho EVM wallet
Theo dõi ví EVM; khi ví nhận/mua token mới, bot lấy pair DexScreener,
tính điểm bằng scanner.score_gem(), enrich GMGN + X social rồi gửi Telegram khuyến nghị.

Yêu cầu .env:
WALLET_MONITOR_ENABLED=true
WALLET_ADDRESSES=0xf703fd64093b50797abdc9e450632240fa2ba5d4
WALLET_CHAINS=base,ethereum,bsc
WALLET_CHECK_MINUTES=2
ETHERSCAN_API_KEY=your_key_here
"""

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
import urllib3
from telegram import Bot

from alerts import send_gem_alerts, send_message
from scanner import score_gem, dex_get

try:
    from gmgn import analyze_token as gmgn_analyze
    GMGN_AVAILABLE = True
except Exception:
    GMGN_AVAILABLE = False

try:
    from x_monitor import get_social_score
    X_AVAILABLE = True
except Exception:
    X_AVAILABLE = False

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger(__name__)

SESSION = requests.Session()
SESSION.verify = False
SESSION.headers.update({"User-Agent": "Mozilla/5.0"})

CHAIN_CFG = {
    "ethereum": {"chainid": 1, "dex": "ethereum", "label": "ETH"},
    "base":     {"chainid": 8453, "dex": "base", "label": "BASE"},
    "bsc":      {"chainid": 56, "dex": "bsc", "label": "BSC"},
    "arbitrum": {"chainid": 42161, "dex": "arbitrum", "label": "ARB"},
}

STABLE_OR_BLUECHIP = {
    # Common stables / wrapped majors — không alert copy-trade
    "usdt", "usdc", "dai", "fdusd", "busd", "usde", "weth", "wbtc", "cbeth",
    "wsteth", "reth", "ezeth", "weeth", "eth", "btc", "bnb",
}


def _norm_addr(a: str) -> str:
    return (a or "").strip().lower()


def _fmt_usd(v: float) -> str:
    try:
        v = float(v or 0)
    except Exception:
        v = 0
    if v >= 1_000_000:
        return f"${v/1_000_000:.2f}M"
    if v >= 1_000:
        return f"${v/1_000:.0f}K"
    return f"${v:.0f}"


class WalletMonitor:
    def __init__(
        self,
        bot: Bot,
        chat_id: str,
        wallets: List[str],
        chains: List[str],
        check_interval: int = 120,
        min_score: float = 5.0,
        etherscan_api_key: str = "",
        seen_file: str = "logs/seen_wallet_tokens.json",
    ):
        self.bot = bot
        self.chat_id = chat_id
        self.wallets = [_norm_addr(w) for w in wallets if _norm_addr(w)]
        self.chains = [c.strip().lower() for c in chains if c.strip().lower() in CHAIN_CFG]
        self.check_interval = max(30, int(check_interval))
        self.min_score = float(min_score)
        self.etherscan_api_key = etherscan_api_key.strip()
        self.seen_path = Path(seen_file)
        self.seen_path.parent.mkdir(exist_ok=True)
        self.seen = self._load_seen()

    def _load_seen(self) -> Dict[str, float]:
        if self.seen_path.exists():
            try:
                return json.loads(self.seen_path.read_text())
            except Exception:
                return {}
        return {}

    def _save_seen(self):
        try:
            self.seen_path.write_text(json.dumps(self.seen, indent=2))
        except Exception as e:
            logger.warning(f"Cannot save wallet seen file: {e}")

    def _seen_key(self, wallet: str, chain: str, token: str) -> str:
        return f"{wallet}:{chain}:{_norm_addr(token)}"

    def fetch_token_transfers(self, wallet: str, chain: str, limit: int = 60) -> List[dict]:
        """Lấy token transfers mới nhất bằng Etherscan API V2. Cần ETHERSCAN_API_KEY."""
        if not self.etherscan_api_key:
            logger.warning("ETHERSCAN_API_KEY missing — wallet monitor cannot fetch transfers")
            return []

        cfg = CHAIN_CFG[chain]
        params = {
            "chainid": cfg["chainid"],
            "module": "account",
            "action": "tokentx",
            "address": wallet,
            "page": 1,
            "offset": limit,
            "sort": "desc",
            "apikey": self.etherscan_api_key,
        }
        try:
            r = SESSION.get("https://api.etherscan.io/v2/api", params=params, timeout=15)
            if r.status_code != 200:
                logger.warning(f"Etherscan HTTP {r.status_code} {chain} {wallet}")
                return []
            data = r.json()
            if str(data.get("status")) != "1":
                msg = data.get("message") or data.get("result")
                logger.debug(f"Etherscan no result {chain}: {msg}")
                return []
            return data.get("result") or []
        except Exception as e:
            logger.warning(f"fetch_token_transfers {chain} {wallet}: {e}")
            return []

    def detect_new_incoming_tokens(self, wallet: str, chain: str) -> List[dict]:
        transfers = self.fetch_token_transfers(wallet, chain)
        events = []
        now = time.time()
        boot_key = f"__bootstrapped__:{wallet}:{chain}"
        first_run = boot_key not in self.seen
        for tx in transfers:
            token = _norm_addr(tx.get("contractAddress"))
            if not token:
                continue
            symbol = (tx.get("tokenSymbol") or "").lower()
            if symbol in STABLE_OR_BLUECHIP:
                continue
            # Chỉ xét token chuyển vào ví. Đây là proxy gần đúng cho "ví vừa mua".
            if _norm_addr(tx.get("to")) != wallet:
                continue
            key = self._seen_key(wallet, chain, token)
            if key in self.seen:
                continue
            self.seen[key] = now
            if not first_run:
                events.append(tx)
        if first_run:
            self.seen[boot_key] = now
            logger.info(f"Wallet monitor bootstrapped {wallet} {chain}: marked current transfers as seen")
        if events or first_run:
            self._save_seen()
        return events

    def fetch_best_pair(self, token_address: str, chain: str) -> Optional[dict]:
        data = dex_get(f"/latest/dex/tokens/{token_address}")
        pairs = (data or {}).get("pairs") or []
        dex_chain = CHAIN_CFG[chain]["dex"]
        pairs = [p for p in pairs if (p.get("chainId") or "").lower() == dex_chain]
        if not pairs:
            return None
        def liq_usd(p):
            try: return float((p.get("liquidity") or {}).get("usd") or 0)
            except Exception: return 0
        pairs.sort(key=liq_usd, reverse=True)
        return pairs[0]

    def build_wallet_note(self, wallet: str, chain: str, tx: dict, gem) -> str:
        tx_hash = tx.get("hash", "")
        amount_raw = float(tx.get("value") or 0)
        decimals = int(tx.get("tokenDecimal") or 18)
        amount = amount_raw / (10 ** decimals) if decimals >= 0 else 0
        label = CHAIN_CFG[chain]["label"]
        verdict = "✅ CÓ THỂ COPY NHẸ" if gem.pre_pump_score >= 8 else "👀 THEO DÕI / DCA NHỎ" if gem.pre_pump_score >= self.min_score else "⛔ CHƯA NÊN COPY"
        return (
            f"\n\n{'─'*36}\n"
            f"👛 SMART WALLET BUY DETECTED\n"
            f"Ví: {wallet}\n"
            f"Chain: {label}\n"
            f"Amount nhận: {amount:,.4f} {tx.get('tokenSymbol','')}\n"
            f"Bot verdict: {verdict}\n"
            f"Score sau khi quét: {gem.pre_pump_score}/10\n"
            f"MC/Liq: {_fmt_usd(gem.mc)} / {_fmt_usd(gem.liq)}\n"
            f"Tx: {tx_hash[:10]}...{tx_hash[-8:]}"
        )

    async def analyze_wallet_token(self, wallet: str, chain: str, tx: dict):
        token = tx.get("contractAddress")
        pair = self.fetch_best_pair(token, chain)
        if not pair:
            await send_message(
                self.bot,
                self.chat_id,
                f"👛 Ví mua token mới nhưng chưa thấy pair DexScreener\n"
                f"Wallet: {wallet}\nChain: {chain}\n"
                f"Token: {token}",
            )
            return

        gem = score_gem(pair, boost_map={})
        if not gem:
            await send_message(
                self.bot,
                self.chat_id,
                f"👛 Ví mua token mới nhưng token không qua bước score cơ bản\n"
                f"Wallet: {wallet}\nChain: {chain}\n"
                f"Token: {token}\n"
                f"Symbol: ${tx.get('tokenSymbol','?')}",
            )
            return

        # Bonus vì ví smart wallet vừa mua
        gem.pre_pump_score = min(10, gem.pre_pump_score + 1.0)
        gem.signals.append("👛 Smart wallet vừa mua/nhận token")

        loop = asyncio.get_event_loop()
        if GMGN_AVAILABLE:
            try:
                gd = await loop.run_in_executor(None, gmgn_analyze, gem.address, gem.chain)
                gem.gmgn_rug_score    = gd.rug_score
                gem.gmgn_quality      = gd.quality_score
                gem.gmgn_insider_pct  = gd.insider_pct
                gem.gmgn_dev_pct      = gd.dev_holding_pct
                gem.gmgn_sniper_count = gd.sniper_count
                gem.gmgn_sm_wallets   = gd.smart_money_wallets
                gem.gmgn_kol_count    = gd.kol_count
                gem.gmgn_lp_burned    = gd.lp_burned
                gem.gmgn_renounced    = gd.renounced
                gem.gmgn_honeypot     = gd.is_honeypot
                gem.gmgn_signals      = gd.signals
                gem.gmgn_warnings     = gd.warnings
                if gd.is_honeypot:
                    gem.pre_pump_score = min(gem.pre_pump_score, 3.0)
                    gem.trade_verdict = "⛔ SKIP — HONEYPOT RISK"
            except Exception as e:
                logger.debug(f"GMGN wallet enrich {gem.ticker}: {e}")

        if X_AVAILABLE:
            try:
                ss = await loop.run_in_executor(None, get_social_score, gem.ticker, gem.address, gem.chain, True)
                gem.x_fomo_score   = ss.fomo_score
                gem.x_viral_score  = ss.viral_score
                gem.x_kol_score    = ss.kol_score
                gem.x_social_total = ss.social_total
                gem.x_mentions     = ss.total_mentions
                gem.x_kol_mentions = ss.kol_mentions
                gem.x_tier1        = ss.tier1_mentions
                gem.x_tier2        = ss.tier2_mentions
                gem.x_tier3        = ss.tier3_mentions
                gem.x_top_kol      = ss.top_kol
                gem.x_signals      = ss.signals
                gem.x_is_viral     = ss.is_viral
                if ss.kol_mentions >= 1:
                    gem.pre_pump_score = min(10, gem.pre_pump_score + 0.5)
            except Exception as e:
                logger.debug(f"X wallet scan {gem.ticker}: {e}")

        # Gửi alert dùng template sẵn; thêm note riêng của ví vào warning để hiện trong alert nếu template có block warnings.
        gem.warnings.append(self.build_wallet_note(wallet, chain, tx, gem))
        await send_gem_alerts(self.bot, self.chat_id, [gem])

    async def run_once(self):
        for wallet in self.wallets:
            for chain in self.chains:
                events = self.detect_new_incoming_tokens(wallet, chain)
                if events:
                    logger.info(f"Wallet {wallet} {chain}: {len(events)} new token events")
                for tx in events[:5]:
                    try:
                        await self.analyze_wallet_token(wallet, chain, tx)
                    except Exception as e:
                        logger.error(f"wallet analyze error: {e}", exc_info=True)
                    await asyncio.sleep(1.0)

    async def run_loop(self):
        logger.info(f"Wallet monitor enabled: {len(self.wallets)} wallets, chains={self.chains}, interval={self.check_interval}s")
        while True:
            try:
                await self.run_once()
            except Exception as e:
                logger.error(f"Wallet monitor loop error: {e}", exc_info=True)
            await asyncio.sleep(self.check_interval)
