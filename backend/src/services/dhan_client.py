from dhanhq import dhanhq
from src.core.config import settings
from src.services.broker_interface import BrokerInterface
import logging
import asyncio
import os
import json
import requests
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
import pandas as pd

logger = logging.getLogger(__name__)

class DhanClient(BrokerInterface):
    """
    Wrapper for DhanHQ API with Rate Limiting and Error Handling.
    Credentials loaded from environment variables (secure).
    Implements BrokerInterface — use get_broker_client() for broker-agnostic access.
    """
    def __init__(self):
        self.dhan = None
        # Load credentials from environment variables securely
        self.client_id = os.getenv("DHAN_CLIENT_ID")
        self.access_token = os.getenv("DHAN_ACCESS_TOKEN")
        self.security_master: Optional[pd.DataFrame] = None
        self.security_master_loaded_at: Optional[datetime] = None
        self.security_master_ttl_hours = int(os.getenv("DHAN_SECURITY_MASTER_TTL_HOURS", "12"))
        # ── Token auto-refresh tracking (Medallion CEO Fix #4) ──────────────────
        # Proactively renew the DhanHQ access token every 4 hours so live
        # sessions never hit mid-session token expiry during trading hours.
        self._token_created_at: Optional[datetime] = None
        self._token_refresh_interval_h: int = 4  # proactive renewal window (hours)
        # ── End token refresh tracking ───────────────────────────────────────────
        self.security_master_file = os.getenv(
            "DHAN_SECURITY_MASTER_FILE",
            os.path.abspath(
                os.path.join(
                    os.path.dirname(__file__),
                    "..",
                    "..",
                    "dhan_security_compact.csv"
                )
            )
        )
        
        if not self.client_id or not self.access_token:
            logger.warning("DhanHQ credentials not configured. Paper trading disabled.")
            logger.info("Set DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN environment variables to enable.")

    def connect(self):
        """Initialize DhanHQ client."""
        try:
            if not self.client_id or not self.access_token:
                logger.warning("Skipping DhanHQ connection - credentials not configured")
                return False
            
            self.dhan = dhanhq(self.client_id, self.access_token)
            self._token_created_at = datetime.now()  # Track token age for auto-refresh
            logger.info("Connected to DhanHQ API")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to DhanHQ: {e}")
            logger.warning("Paper trading will use simulated orders")
            return False

    # ------------------------------------------------------------------
    # BrokerInterface overrides
    # ------------------------------------------------------------------

    def is_connected(self) -> bool:
        """Return True only when the DhanHQ SDK object is initialised AND credentials are set."""
        return bool(self.dhan and self.client_id and self.access_token)

    def broker_name(self) -> str:
        return "DhanHQ"

    async def fetch_market_data(self, security_id: str, exchange_segment: str = "NSE_EQ") -> Dict[str, Any]:
        """
        Fetch Latest Price (LTP) + OHLC from DhanHQ via ohlc_data().
        Returns real data when connected; {"ltp": 0.0, "connected": False} when offline.
        """
        try:
            if not self.dhan:
                logger.debug("DhanHQ not connected — market data unavailable")
                return {"ltp": 0.0, "connected": False}

            seg_key = str(exchange_segment).upper().replace("-", "_")
            try:
                sec_id_int = int(security_id)
            except (ValueError, TypeError):
                sec_id_int = security_id  # type: ignore

            response = self.dhan.ohlc_data(securities={seg_key: [sec_id_int]})

            if response and response.get("status") == "success":
                data = response.get("data", {})
                seg_data = data.get(seg_key, {})
                # SDK may key by int or string
                item = seg_data.get(str(security_id)) or seg_data.get(sec_id_int, {})
                ltp = float(item.get("last_price") or item.get("ltp") or 0.0)
                ohlc = item.get("ohlc", {})
                return {
                    "ltp":    ltp,
                    "open":   float(ohlc.get("open",  0)),
                    "high":   float(ohlc.get("high",  0)),
                    "low":    float(ohlc.get("low",   0)),
                    "close":  float(ohlc.get("close", 0)),
                    "volume": int(item.get("volume",  0)),
                    "connected": True,
                }
            logger.warning(f"ohlc_data returned non-success for {security_id}: {response.get('remarks', '')}")
            return {"ltp": 0.0, "connected": True, "error": response.get("remarks", "")}
        except Exception as e:
            logger.error(f"fetch_market_data error for {security_id}: {e}")
            return {"ltp": 0.0, "connected": bool(self.dhan)}

    def _is_security_master_fresh(self) -> bool:
        if self.security_master is None or self.security_master_loaded_at is None:
            return False
        return datetime.now() - self.security_master_loaded_at < timedelta(hours=self.security_master_ttl_hours)

    def _load_security_master(self, force_refresh: bool = False) -> bool:
        """Load/cached Dhan security master for symbol -> securityId resolution."""
        try:
            if not force_refresh and self._is_security_master_fresh():
                return True

            if os.path.exists(self.security_master_file) and not force_refresh:
                self.security_master = pd.read_csv(self.security_master_file, low_memory=False)
                self.security_master_loaded_at = datetime.now()
                return True

            if not self.dhan:
                # Cannot fetch remote list without a connected client.
                return False

            folder = os.path.dirname(self.security_master_file)
            if folder:
                os.makedirs(folder, exist_ok=True)

            df = self.dhan.fetch_security_list(mode='compact', filename=self.security_master_file)
            if df is None or df.empty:
                return False

            self.security_master = df
            self.security_master_loaded_at = datetime.now()
            logger.info(f"Security master loaded with {len(df)} instruments")
            return True
        except Exception as e:
            logger.warning(f"Failed to load security master: {e}")
            return False

    def resolve_security_details(
        self,
        symbol: str,
        signal_type: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """Resolve security details from signal metadata + Dhan security master.
        
        Supports both NSE and BSE exchange segments.  When metadata contains
        an explicit exchange_segment (e.g. \"BSE\", \"BSE_FNO\") the lookup
        targets that exchange.  Otherwise defaults to NSE.
        """
        metadata = metadata or {}

        explicit_security_id = metadata.get("security_id") or metadata.get("securityId")
        explicit_trading_symbol = metadata.get("trading_symbol") or metadata.get("tradingSymbol")
        explicit_exchange_segment = metadata.get("exchange_segment") or metadata.get("exchangeSegment")
        explicit_product_type = metadata.get("product_type") or metadata.get("productType")

        if explicit_security_id:
            return {
                "security_id": str(explicit_security_id),
                "trading_symbol": explicit_trading_symbol or symbol,
                "exchange_segment": explicit_exchange_segment or "NSE_FNO",
                "product_type": explicit_product_type or "INTRA"
            }

        if not self._load_security_master():
            return None

        df = self.security_master
        if df is None or df.empty:
            return None

        symbol_upper = str(symbol).upper().strip()
        signal_upper = str(signal_type).upper().strip()
        instrument_hint = str(metadata.get("instrument", "")).upper()
        option_hint = str(metadata.get("instrument_type") or metadata.get("option_type") or "").upper()
        strike_hint = metadata.get("suggested_strike") or metadata.get("strike")

        # Determine target exchange from explicit segment or universe hint
        seg_hint = (explicit_exchange_segment or "").upper()
        is_bse = seg_hint.startswith("BSE") or seg_hint == "BFO"
        target_exchange = "BSE" if is_bse else "NSE"

        is_option = (
            "OPTION" in instrument_hint
            or "FNO" in instrument_hint
            or option_hint in {"CALL", "PUT", "CE", "PE"}
            or strike_hint is not None
            or symbol_upper in {"NIFTY", "BANKNIFTY", "FINNIFTY", "BANKEX", "SENSEX"}
        )

        if is_option:
            option_type = option_hint
            if option_type == "CALL":
                option_type = "CE"
            elif option_type == "PUT":
                option_type = "PE"
            elif option_type not in {"CE", "PE"}:
                # Fallback convention currently used by strategies
                option_type = "CE" if signal_upper == "BUY" else "PE"

            fno_segment = "BSE_FNO" if is_bse else "NSE_FNO"

            candidates = df[
                (df["SEM_EXM_EXCH_ID"].astype(str).str.upper() == target_exchange)
                & (df["SEM_INSTRUMENT_NAME"].astype(str).str.upper().isin(["OPTIDX", "OPTSTK"]))
                & (df["SEM_TRADING_SYMBOL"].astype(str).str.upper().str.startswith(symbol_upper, na=False))
            ].copy()

            # Fallback: try the other exchange if no results on primary
            if candidates.empty and is_bse:
                candidates = df[
                    (df["SEM_EXM_EXCH_ID"].astype(str).str.upper() == "NSE")
                    & (df["SEM_INSTRUMENT_NAME"].astype(str).str.upper().isin(["OPTIDX", "OPTSTK"]))
                    & (df["SEM_TRADING_SYMBOL"].astype(str).str.upper().str.startswith(symbol_upper, na=False))
                ].copy()
                if not candidates.empty:
                    fno_segment = "NSE_FNO"  # fell back to NSE

            if candidates.empty:
                return None

            if option_type in {"CE", "PE"}:
                candidates = candidates[
                    candidates["SEM_OPTION_TYPE"].astype(str).str.upper() == option_type
                ]

            if candidates.empty:
                return None

            candidates["_expiry"] = pd.to_datetime(candidates["SEM_EXPIRY_DATE"], errors="coerce")
            candidates = candidates.sort_values(by=["_expiry"], na_position="last")

            now = datetime.now()
            future = candidates[candidates["_expiry"] >= now]
            if not future.empty:
                candidates = future

            if strike_hint is not None:
                try:
                    strike_value = float(strike_hint)
                    candidates["_strike_diff"] = (
                        pd.to_numeric(candidates["SEM_STRIKE_PRICE"], errors="coerce") - strike_value
                    ).abs()
                    candidates = candidates.sort_values(by=["_strike_diff", "_expiry"], na_position="last")
                except Exception:
                    pass

            row = candidates.iloc[0]
            return {
                "security_id": str(row["SEM_SMST_SECURITY_ID"]),
                "trading_symbol": str(row["SEM_TRADING_SYMBOL"]),
                "exchange_segment": fno_segment,
                "product_type": "INTRA",
                "lot_size": int(float(row.get("SEM_LOT_UNITS", 1) or 1))
            }

        # Equity/Cash lookup — try target exchange first, fallback to other
        equity_segment = "BSE" if is_bse else "NSE"
        candidates = df[
            (df["SEM_EXM_EXCH_ID"].astype(str).str.upper() == target_exchange)
            & (df["SEM_SEGMENT"].astype(str).str.upper() == "E")
            & (df["SEM_TRADING_SYMBOL"].astype(str).str.upper() == symbol_upper)
        ].copy()

        if candidates.empty:
            # Partial match on target exchange
            candidates = df[
                (df["SEM_EXM_EXCH_ID"].astype(str).str.upper() == target_exchange)
                & (df["SEM_SEGMENT"].astype(str).str.upper() == "E")
                & (df["SEM_TRADING_SYMBOL"].astype(str).str.upper().str.contains(symbol_upper, na=False))
            ].copy()

        if candidates.empty and is_bse:
            # BSE stock not found on BSE segment — try NSE (dual-listed)
            equity_segment = "NSE"
            candidates = df[
                (df["SEM_EXM_EXCH_ID"].astype(str).str.upper() == "NSE")
                & (df["SEM_SEGMENT"].astype(str).str.upper() == "E")
                & (df["SEM_TRADING_SYMBOL"].astype(str).str.upper() == symbol_upper)
            ].copy()

        if candidates.empty:
            return None

        eq_pref = candidates[candidates["SEM_SERIES"].astype(str).str.upper() == "EQ"]
        if not eq_pref.empty:
            candidates = eq_pref

        row = candidates.iloc[0]
        return {
            "security_id": str(row["SEM_SMST_SECURITY_ID"]),
            "trading_symbol": str(row["SEM_TRADING_SYMBOL"]),
            "exchange_segment": equity_segment,
            "product_type": "CNC"
        }

    async def place_order(self, order_details: Dict[str, Any]) -> Optional[str]:
        """
        Place order and return Order ID.
        Falls back to simulated order if not connected or in PAPER_TRADING mode.
        Uses order_type_router for intelligent product_type selection:
          - Trading style (INTRADAY → INTRA, SWING → CNC)
          - Module (Equity, Options, FNO)
          - Strategy type (some require BO, CO, etc.)
        """
        try:
            # Safety guard: force simulation when PAPER_TRADING is enabled
            if settings.PAPER_TRADING or not self.dhan:
                if settings.PAPER_TRADING and self.dhan:
                    logger.info("PAPER_TRADING=True — blocking real order, using simulation")
                else:
                    logger.warning("DhanHQ not connected - using simulated order")
                # Return simulated order ID
                sim_symbol = order_details.get('tradingSymbol') or order_details.get('symbol', 'UNKNOWN')
                sim_side = order_details.get('transactionType') or order_details.get('buy_sell', 'UNKNOWN')
                return f"SIM_{sim_symbol}_{sim_side}"

            # ── Proactive token refresh before every live order ────────────────
            # Ensures no mid-session token expiry during live trading hours.
            try:
                await self._ensure_token_fresh()
            except Exception as _tre:
                logger.warning(f"Token freshness check failed (continuing): {_tre}")

            symbol = order_details.get("tradingSymbol") or order_details.get("symbol") or "UNKNOWN"
            signal_type = order_details.get("transactionType") or order_details.get("buy_sell") or order_details.get("signal_type") or "BUY"
            metadata = order_details.get("metadata", {})

            resolved = self.resolve_security_details(symbol, signal_type, metadata)

            security_id = (
                order_details.get("securityId")
                or order_details.get("security_id")
                or (resolved or {}).get("security_id")
            )
            exchange_segment = order_details.get("exchangeSegment") or (resolved or {}).get("exchange_segment") or "NSE"
            quantity = int(order_details.get("quantity", 1))
            order_type = order_details.get("orderType", "MARKET")
            price = float(order_details.get("price", 0.0))
            trigger_price = float(order_details.get("triggerPrice", 0.0))
            validity = order_details.get("validity", "DAY")
            tag = order_details.get("correlationId") or order_details.get("tag")
            strategy_name = metadata.get("strategy") or metadata.get("strategy_name") or "UNKNOWN"

            # Use order_type_router for intelligent product type selection
            try:
                from src.services.order_type_router import get_order_type
                product_type = await get_order_type(
                    strategy_name=strategy_name,
                    trading_style=None,  # Will fetch from Redis
                    module=metadata.get("module"),
                    instrument_type=metadata.get("instrument_type"),
                    metadata=metadata,
                    broker="dhan"
                )
                logger.debug(f"Order type router: {strategy_name} => product_type={product_type}")
            except Exception as e:
                logger.warning(f"Order type router failed, using defaults: {e}")
                # Fallback to basic product_type from order or resolved
                product_type = order_details.get("productType") or (resolved or {}).get("product_type") or "INTRA"

            if not security_id:
                raise ValueError(f"Could not resolve securityId for symbol={symbol}")

            response = self.dhan.place_order(
                security_id=str(security_id),
                exchange_segment=str(exchange_segment),
                transaction_type=str(signal_type),
                quantity=quantity,
                order_type=str(order_type),
                product_type=str(product_type),
                price=price,
                trigger_price=trigger_price,
                validity=str(validity),
                tag=tag
            )
            if response['status'] == 'success':
                data = response.get('data')
                if isinstance(data, dict):
                    return str(data.get('orderId') or data.get('order_id') or data.get('id') or '')
                if data:
                    return str(data)
                return "UNKNOWN_ORDER_ID"
            else:
                raise Exception(f"Order placement failed: {response['remarks']}")
        except Exception as e:
            logger.error(f"Error placing order: {e}")
            # Return simulated order for paper trading
            sim_symbol = order_details.get('tradingSymbol') or order_details.get('symbol', 'UNKNOWN')
            sim_side = order_details.get('transactionType') or order_details.get('buy_sell', 'UNKNOWN')
            return f"SIM_{sim_symbol}_{sim_side}"

    async def get_order_status(self, order_id: str) -> Dict[str, Any]:
        """Get order status from DhanHQ."""
        try:
            if not self.dhan:
                return {"status": "PENDING", "order_id": order_id}
            
            response = self.dhan.get_order_status(order_id)
            return response.get('data', {})
        except Exception as e:
            logger.error(f"Error getting order status: {e}")
            return {"status": "UNKNOWN", "order_id": order_id}

    async def modify_order(
        self,
        order_id: str,
        quantity: Optional[int] = None,
        price: Optional[float] = None,
        order_type: str = "LIMIT",
        leg_name: str = "",
        validity: str = "DAY"
    ) -> Optional[str]:
        """Modify an existing open order (price / quantity)."""
        try:
            if not self.dhan:
                logger.warning(f"DhanHQ not connected - simulating modify for {order_id}")
                return f"SIM_MOD_{order_id}"

            kwargs: Dict[str, Any] = dict(
                order_id=str(order_id),
                order_type=str(order_type),
                leg_name=str(leg_name),
                validity=str(validity),
            )
            if quantity is not None:
                kwargs["quantity"] = int(quantity)
            if price is not None:
                kwargs["price"] = float(price)

            response = self.dhan.modify_order(**kwargs)
            if response.get('status') == 'success':
                data = response.get('data', {})
                return str(data.get('orderId') or order_id)
            else:
                raise Exception(f"Modify failed: {response.get('remarks')}")
        except Exception as e:
            logger.error(f"Error modifying order {order_id}: {e}")
            return None

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order. Returns True on success."""
        try:
            if not self.dhan:
                logger.warning(f"DhanHQ not connected - simulating cancel for {order_id}")
                return True

            response = self.dhan.cancel_order(order_id=str(order_id))
            success = response.get('status') == 'success'
            if not success:
                logger.warning(f"Cancel order {order_id} failed: {response.get('remarks')}")
            return success
        except Exception as e:
            logger.error(f"Error cancelling order {order_id}: {e}")
            return False

    async def get_market_depth(self, symbol: str, exchange_segment: str = "NSE_EQ") -> Dict[str, Any]:
        """
        Fetch 3-5 level market depth (order book) from DhanHQ Data API.

        Returns a dict with keys:
          buy  : list of {"price": float, "quantity": int, "orders": int}  (bid levels)
          sell : list of {"price": float, "quantity": int, "orders": int}  (ask levels)

        DhanHQ provides up to 5 levels. OrderFlowStrategy uses the top 3.
        Falls back to an empty depth dict when not connected (paper trading / test env)
        or when the SDK version does not expose the method (market must be live).
        """
        _empty = {"buy": [], "sell": []}
        try:
            if not self.dhan:
                logger.debug(f"DhanHQ not connected — market depth unavailable for {symbol}")
                return _empty

            # SDK version check — cache once to avoid repeated AttributeError
            if not hasattr(self.dhan, "get_market_depth"):
                if not getattr(self, "_depth_sdk_warned", False):
                    logger.info("DhanHQ SDK does not expose get_market_depth — market depth requires live market")
                    self._depth_sdk_warned = True
                return _empty

            # Resolve security_id from master
            resolved = self.resolve_security_details(symbol, "BUY", {})
            if not resolved:
                logger.warning(f"get_market_depth: cannot resolve security_id for {symbol}")
                return _empty

            security_id = resolved["security_id"]
            seg = resolved.get("exchange_segment", exchange_segment)

            response = self.dhan.get_market_depth(
                security_id=security_id,
                exchange_segment=seg,
            )

            if response.get("status") != "success":
                logger.warning(f"get_market_depth failed for {symbol}: {response.get('remarks')}")
                return _empty

            data = response.get("data", {})
            buy_levels = [
                {
                    "price": float(lvl.get("price", 0)),
                    "quantity": int(lvl.get("quantity", 0)),
                    "orders": int(lvl.get("orders", 0)),
                }
                for lvl in data.get("buy", [])
            ]
            sell_levels = [
                {
                    "price": float(lvl.get("price", 0)),
                    "quantity": int(lvl.get("quantity", 0)),
                    "orders": int(lvl.get("orders", 0)),
                }
                for lvl in data.get("sell", [])
            ]
            logger.debug(
                f"Market depth {symbol}: {len(buy_levels)} bid levels, {len(sell_levels)} ask levels"
            )
            return {"buy": buy_levels, "sell": sell_levels}
        except Exception as e:
            logger.debug(f"get_market_depth unavailable for {symbol}: {e}")
            return _empty

    async def get_positions(self) -> list:
        """
        Fetch current open positions from DhanHQ.

        Returns list of dicts with keys:
          symbol, security_id, exchange_segment, product_type, quantity,
          buy_avg, sell_avg, net_qty, unrealized_pnl, realized_pnl
        """
        try:
            if not self.dhan:
                logger.debug("DhanHQ not connected - returning empty positions")
                return []

            response = self.dhan.get_positions()
            if response.get('status') != 'success':
                logger.warning(f"get_positions failed: {response.get('remarks')}")
                return []

            raw = response.get('data', []) or []
            positions = []
            for p in raw:
                positions.append({
                    "symbol": p.get("tradingSymbol") or p.get("symbol", ""),
                    "security_id": str(p.get("securityId") or p.get("security_id", "")),
                    "exchange_segment": p.get("exchangeSegment", ""),
                    "product_type": p.get("productType", ""),
                    "quantity": int(p.get("netQty") or p.get("quantity", 0)),
                    "buy_avg": float(p.get("buyAvg") or p.get("costPrice", 0)),
                    "sell_avg": float(p.get("sellAvg") or 0),
                    "net_qty": int(p.get("netQty", 0)),
                    "ltp": float(p.get("ltp") or p.get("lastPrice", 0)),
                    "unrealized_pnl": float(p.get("unrealizedProfit") or p.get("unrealizedPnl", 0)),
                    "realized_pnl": float(p.get("realizedProfit") or p.get("realizedPnl", 0)),
                })
            return positions
        except Exception as e:
            logger.error(f"Error fetching positions: {e}")
            return []

    async def get_trades(self, order_id: Optional[str] = None) -> list:
        """
        Fetch trade book (filled orders) from DhanHQ.
        Optionally filter by order_id.

        Returns list of dicts with keys:
          order_id, symbol, security_id, transaction_type, quantity,
          traded_price, trade_time, product_type, exchange_segment
        """
        try:
            if not self.dhan:
                logger.debug("DhanHQ not connected - returning empty trade book")
                return []

            response = self.dhan.get_trade_book()
            if response.get('status') != 'success':
                logger.warning(f"get_trades failed: {response.get('remarks')}")
                return []

            raw = response.get('data', []) or []
            trades = []
            for t in raw:
                oid = str(t.get("orderId") or t.get("order_id", ""))
                if order_id and oid != str(order_id):
                    continue
                trades.append({
                    "order_id": oid,
                    "symbol": t.get("tradingSymbol") or t.get("symbol", ""),
                    "security_id": str(t.get("securityId") or ""),
                    "transaction_type": t.get("transactionType", ""),
                    "quantity": int(t.get("tradedQuantity") or t.get("quantity", 0)),
                    "traded_price": float(t.get("tradedPrice") or t.get("price", 0)),
                    "trade_time": t.get("createTime") or t.get("exchangeTime") or "",
                    "product_type": t.get("productType", ""),
                    "exchange_segment": t.get("exchangeSegment", ""),
                })
            return trades
        except Exception as e:
            logger.error(f"Error fetching trades: {e}")
            return []

    # ------------------------------------------------------------------
    # Underlying security mappings for Option Chain API
    # ------------------------------------------------------------------
    # DhanHQ Option Chain endpoint uses underlying security_id + segment
    # Segment for indices: "IDX_I", for stocks: "NSE_EQ"
    UNDERLYING_MAP = {
        "NIFTY": (13, "IDX_I"),
        "NIFTY50": (13, "IDX_I"),
        "NIFTY 50": (13, "IDX_I"),
        "BANKNIFTY": (25, "IDX_I"),
        "NIFTYBANK": (25, "IDX_I"),
        "FINNIFTY": (27, "IDX_I"),
        "NIFTYFIN": (27, "IDX_I"),
        "MIDCPNIFTY": (442, "IDX_I"),
        "SENSEX": (51, "IDX_I"),
        "BANKEX": (790, "IDX_I"),
        # Major F&O stocks — security_id from security master
        "RELIANCE": (2885, "NSE_EQ"),
        "TCS": (11536, "NSE_EQ"),
        "INFY": (1594, "NSE_EQ"),
        "HDFCBANK": (1333, "NSE_EQ"),
        "ICICIBANK": (4963, "NSE_EQ"),
        "SBIN": (3045, "NSE_EQ"),
        "BHARTIARTL": (10604, "NSE_EQ"),
        "ITC": (1660, "NSE_EQ"),
        "KOTAKBANK": (1922, "NSE_EQ"),
        "LT": (11483, "NSE_EQ"),
        "AXISBANK": (5900, "NSE_EQ"),
        "MARUTI": (10999, "NSE_EQ"),
        "TATAMOTORS": (3456, "NSE_EQ"),
        "TATASTEEL": (3499, "NSE_EQ"),
        "WIPRO": (3787, "NSE_EQ"),
        "HCLTECH": (7229, "NSE_EQ"),
        "BAJFINANCE": (317, "NSE_EQ"),
        "BAJAJFINSV": (16669, "NSE_EQ"),
        "SUNPHARMA": (3351, "NSE_EQ"),
        "TECHM": (13538, "NSE_EQ"),
        "ADANIENT": (25, "NSE_EQ"),
        "HINDUNILVR": (1394, "NSE_EQ"),
        "POWERGRID": (14977, "NSE_EQ"),
        "NTPC": (11630, "NSE_EQ"),
        "ONGC": (2475, "NSE_EQ"),
        "COALINDIA": (20374, "NSE_EQ"),
        "M&M": (2031, "NSE_EQ"),
        "DRREDDY": (881, "NSE_EQ"),
        "GRASIM": (1232, "NSE_EQ"),
    }

    def resolve_underlying(self, symbol: str) -> tuple:
        """
        Resolve symbol to (security_id, exchange_segment) for DhanHQ Option Chain API.
        Falls back to security master lookup if not in static map.
        
        Returns (security_id, exchange_segment) or (None, None) if not found.
        """
        sym = symbol.upper().strip()
        if sym in self.UNDERLYING_MAP:
            return self.UNDERLYING_MAP[sym]
        
        # Fallback: search security master for equity instrument
        if self._load_security_master() and self.security_master is not None:
            df = self.security_master
            try:
                equity = df[
                    (df["SEM_TRADING_SYMBOL"].astype(str).str.upper() == sym)
                    & (df["SEM_INSTRUMENT_NAME"].astype(str).str.upper().isin(["EQUITY", "INDEX"]))
                    & (df["SEM_EXM_EXCH_ID"].astype(str).str.upper() == "NSE")
                ]
                if not equity.empty:
                    sec_id = int(equity.iloc[0]["SEM_SMST_SECURITY_ID"])
                    instrument = str(equity.iloc[0]["SEM_INSTRUMENT_NAME"]).upper()
                    seg = "IDX_I" if instrument == "INDEX" else "NSE_EQ"
                    return (sec_id, seg)
            except Exception as ex:
                logger.debug(f"Security master lookup failed for {sym}: {ex}")
        
        return (None, None)

    async def get_expiry_list(self, symbol: str) -> list:
        """
        Get all active option expiry dates for an underlying.
        Uses DhanHQ native /optionchain/expirylist endpoint.
        
        Returns list of expiry date strings (YYYY-MM-DD format) or empty list.
        """
        try:
            if not self.dhan:
                return []
            sec_id, seg = self.resolve_underlying(symbol)
            if sec_id is None:
                logger.warning(f"Cannot resolve underlying {symbol} for expiry list")
                return []
            
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(None, self.dhan.expiry_list, sec_id, seg)
            
            if response.get("status") == "success":
                data = response.get("data", {})
                # SDK 2.0.2 double-nests: {data: {data: [...], status: ...}}
                if isinstance(data, dict):
                    data = data.get("data", data)
                if isinstance(data, list):
                    return sorted(data)
            
            logger.debug(f"Expiry list for {symbol}: {response.get('remarks', 'unknown error')}")
            return []
        except Exception as e:
            logger.error(f"Error fetching expiry list for {symbol}: {e}")
            return []

    async def get_option_chain_native(self, symbol: str, expiry: str) -> dict:
        """
        Fetch real-time option chain from DhanHQ native /optionchain endpoint.
        
        Returns full response dict with:
          - data.last_price: float (underlying LTP)
          - data.oc: dict keyed by strike price string, each with 'ce' and 'pe' sub-dicts
            - Each ce/pe has: greeks{delta,gamma,theta,vega}, implied_volatility, 
              last_price, oi, volume, security_id, top_bid_price, top_bid_quantity,
              top_ask_price, top_ask_quantity, average_price, previous_close_price,
              previous_oi, previous_volume
        
        Returns empty dict on failure.
        """
        try:
            if not self.dhan:
                return {}
            sec_id, seg = self.resolve_underlying(symbol)
            if sec_id is None:
                logger.warning(f"Cannot resolve underlying {symbol} for option chain")
                return {}
            
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, self.dhan.option_chain, sec_id, seg, expiry
            )
            
            if response.get("status") == "success":
                # SDK 2.0.2 wraps: {data: {data: {last_price, oc}, status}}
                outer = response.get("data", {})
                return outer.get("data", outer) if isinstance(outer, dict) else {}
            
            logger.debug(f"Option chain for {symbol}/{expiry}: {response.get('remarks', 'unknown error')}")
            return {}
        except Exception as e:
            logger.error(f"Error fetching native option chain for {symbol}: {e}")
            return {}

    async def place_slice_order_async(
        self,
        security_id: str,
        exchange_segment: str,
        transaction_type: str,
        quantity: int,
        order_type: str = "MARKET",
        product_type: str = "INTRADAY",
        price: float = 0.0,
        trigger_price: float = 0.0,
        validity: str = "DAY",
        tag: str = None,
    ) -> dict:
        """
        Place a slice order via DhanHQ native /orders/slicing endpoint.
        DhanHQ automatically handles lot-size compliant slicing for large orders.
        
        Returns dict with order status and order_id(s).
        """
        try:
            if not self.dhan:
                return {"status": "failure", "remarks": "DhanHQ not connected"}
            
            paper_mode = os.getenv("PAPER_TRADING", "true").lower() == "true"
            if paper_mode:
                import uuid
                logger.info(f"[PAPER] Slice order: {transaction_type} {quantity}x {security_id} on {exchange_segment}")
                return {
                    "status": "success",
                    "data": {"orderId": f"SIM-SLICE-{uuid.uuid4().hex[:8]}"},
                    "remarks": "paper_trade"
                }
            
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.dhan.place_slice_order(
                    security_id=security_id,
                    exchange_segment=exchange_segment,
                    transaction_type=transaction_type,
                    quantity=quantity,
                    order_type=order_type,
                    product_type=product_type,
                    price=price,
                    trigger_price=trigger_price,
                    validity=validity,
                    tag=tag,
                ),
            )
            return response
        except Exception as e:
            logger.error(f"Slice order failed: {e}")
            return {"status": "failure", "remarks": str(e)}

    # ------------------------------------------------------------------
    # DhanHQ historical & intraday data (SDK v2)
    # ------------------------------------------------------------------

    async def get_intraday_minute_data(
        self,
        security_id: str,
        exchange_segment: str = "NSE_EQ",
        instrument_type: str = "EQUITY",
        from_date: str = "",
        to_date: str = "",
    ) -> list:
        """
        Fetch intraday minute-level OHLCV from DhanHQ.
        Returns list of candles: [{open,high,low,close,volume,timestamp}, ...]
        SDK: dhan.intraday_minute_data(security_id, exchange_segment, instrument_type, from_date, to_date)
        """
        try:
            if not self.dhan:
                return []
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(
                None,
                lambda: self.dhan.intraday_minute_data(
                    security_id=str(security_id),
                    exchange_segment=exchange_segment,
                    instrument_type=instrument_type,
                    from_date=from_date,
                    to_date=to_date,
                )
            )
            data = resp.get("data", {}) if isinstance(resp, dict) else {}
            opens  = data.get("open",   [])
            highs  = data.get("high",   [])
            lows   = data.get("low",    [])
            closes = data.get("close",  [])
            vols   = data.get("volume", [])
            times  = data.get("timestamp", [])
            candles = []
            for i in range(min(len(opens), len(closes))):
                candles.append({
                    "time":   times[i]  if i < len(times)  else 0,
                    "open":   opens[i]  if i < len(opens)  else 0,
                    "high":   highs[i]  if i < len(highs)  else 0,
                    "low":    lows[i]   if i < len(lows)   else 0,
                    "close":  closes[i] if i < len(closes) else 0,
                    "volume": vols[i]   if i < len(vols)   else 0,
                })
            return candles
        except Exception as e:
            logger.error(f"DhanHQ intraday_minute_data error: {e}")
            return []

    async def get_historical_daily_data(
        self,
        security_id: str,
        exchange_segment: str = "NSE_EQ",
        instrument_type: str = "EQUITY",
        expiry_code: int = 0,
        from_date: str = "",
        to_date: str = "",
    ) -> list:
        """
        Fetch historical daily OHLCV from DhanHQ.
        SDK: dhan.historical_daily_data(security_id, exchange_segment, instrument_type, expiry_code, from_date, to_date)
        """
        try:
            if not self.dhan:
                return []
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(
                None,
                lambda: self.dhan.historical_daily_data(
                    security_id=str(security_id),
                    exchange_segment=exchange_segment,
                    instrument_type=instrument_type,
                    expiry_code=expiry_code,
                    from_date=from_date,
                    to_date=to_date,
                )
            )
            data = resp.get("data", {}) if isinstance(resp, dict) else {}
            opens  = data.get("open",   [])
            highs  = data.get("high",   [])
            lows   = data.get("low",    [])
            closes = data.get("close",  [])
            vols   = data.get("volume", [])
            times  = data.get("timestamp", [])
            candles = []
            for i in range(min(len(opens), len(closes))):
                candles.append({
                    "time":   times[i]  if i < len(times)  else 0,
                    "open":   opens[i]  if i < len(opens)  else 0,
                    "high":   highs[i]  if i < len(highs)  else 0,
                    "low":    lows[i]   if i < len(lows)   else 0,
                    "close":  closes[i] if i < len(closes) else 0,
                    "volume": vols[i]   if i < len(vols)   else 0,
                })
            return candles
        except Exception as e:
            logger.error(f"DhanHQ historical_daily_data error: {e}")
            return []

    async def get_ticker_quote(
        self,
        securities: dict,
        mode: str = "ohlc",
    ) -> dict:
        """
        Fetch LTP/OHLC/full quote via DhanHQ REST.
        mode: 'ticker' → ticker_data (LTP only)
              'ohlc'   → ohlc_data (LTP + OHLC)
              'full'   → quote_data (full market snapshot)
        securities: {"NSE_EQ": ["1333", "2885"]} — segment → list of security IDs
        """
        try:
            if not self.dhan:
                return {}
            loop = asyncio.get_event_loop()
            if mode == "ticker":
                fn = lambda: self.dhan.ticker_data(securities=securities)
            elif mode == "full":
                fn = lambda: self.dhan.quote_data(securities=securities)
            else:
                fn = lambda: self.dhan.ohlc_data(securities=securities)
            resp = await loop.run_in_executor(None, fn)
            if not isinstance(resp, dict) or resp.get("status") not in ("success", True, 1):
                return {}
            # SDK 2.0.2: response wraps data in an extra layer {data: {data: {...}, status:...}}
            outer = resp.get("data", {})
            return outer.get("data", outer) if isinstance(outer, dict) else {}
        except Exception as e:
            logger.error(f"DhanHQ {mode} quote error: {e}")
            return {}

    async def get_fund_limits_data(self) -> dict:
        """Fetch account fund limits (margins, available cash) from DhanHQ."""
        try:
            if not self.dhan:
                return {}
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(None, self.dhan.get_fund_limits)
            return resp.get("data", resp) if isinstance(resp, dict) else {}
        except Exception as e:
            logger.error(f"DhanHQ get_fund_limits error: {e}")
            return {}

    async def get_batch_quotes(
        self,
        symbols: list,
        mode: str = "ohlc",
    ) -> Dict[str, Any]:
        """
        Fetch LTP + OHLC for up to 1000 instruments in a SINGLE REST call.

        Uses DhanHQ Market Quote API — far faster than per-symbol calls.
        Resolves NSE symbols → security IDs automatically via security master.

        Args:
            symbols: List of NSE symbol strings e.g. ["RELIANCE", "NIFTY 50"]
            mode:    "ticker" → LTP only  |  "ohlc" → LTP + OHLC  |  "full" → full snapshot

        Returns:
            Dict keyed by symbol with {ltp, open, high, low, close, volume, oi, ...}
            Empty dict on failure or if DhanHQ is not connected.

        Example:
            quotes = await dhan_client.get_batch_quotes(["NIFTY 50", "RELIANCE", "HDFCBANK"])
            nifty_ltp = quotes["NIFTY 50"]["ltp"]
        """
        if not self.dhan:
            return {}

        # Build {segment: [security_ids]} mapping (max 1000 per call)
        seg_ids: Dict[str, list] = {}
        id_to_sym: Dict[str, str] = {}  # "SEG:id" → symbol name for result mapping

        # Normalize segment names: resolve_security_details returns 'NSE'/'BSE'
        # but Market Quote API requires 'NSE_EQ'/'BSE_EQ' (full enum names)
        _SEG_NORM = {"NSE": "NSE_EQ", "BSE": "BSE_EQ",
                     "NFO": "NSE_FNO", "MCX": "MCX_COMM",
                     "CDS": "NSE_CURRENCY", "BFO": "BSE_FNO"}

        for sym in symbols:
            resolved = self.resolve_security_details(sym, "BUY", {})
            if resolved:
                sec_id   = int(resolved["security_id"])
                raw_seg  = resolved.get("exchange_segment", "NSE_EQ").upper().replace("-", "_")
                seg      = _SEG_NORM.get(raw_seg, raw_seg)
                seg_ids.setdefault(seg, []).append(sec_id)
                id_to_sym[f"{seg}:{sec_id}"] = sym
            else:
                # Try direct resolution for indices via UNDERLYING_MAP
                underlying = self.resolve_underlying(sym)
                if underlying[0] is not None:
                    sec_id = underlying[0]
                    seg = "IDX_I"
                    seg_ids.setdefault(seg, []).append(sec_id)
                    id_to_sym[f"{seg}:{sec_id}"] = sym

        if not seg_ids:
            logger.debug("get_batch_quotes: no resolvable symbols")
            return {}

        try:
            loop = asyncio.get_event_loop()

            if mode == "ticker":
                fn = lambda: self.dhan.ticker_data(securities=seg_ids)
            elif mode == "full":
                fn = lambda: self.dhan.quote_data(securities=seg_ids)
            else:
                fn = lambda: self.dhan.ohlc_data(securities=seg_ids)

            resp = await loop.run_in_executor(None, fn)
            if not isinstance(resp, dict) or resp.get("status") != "success":
                logger.warning(f"get_batch_quotes non-success: {resp.get('remarks', '')}")
                return {}

            # SDK 2.0.2: {status, data: {data: {SEG: {id: {...}}}, status}}
            outer = resp.get("data", {})
            raw_data = outer.get("data", outer) if isinstance(outer, dict) else outer
            results: Dict[str, Any] = {}

            for seg, items in raw_data.items():
                if not isinstance(items, dict):
                    continue
                for sec_id_key, item in items.items():
                    sym = id_to_sym.get(f"{seg}:{sec_id_key}") or id_to_sym.get(
                        f"{seg}:{int(sec_id_key)}" if str(sec_id_key).isdigit() else f"{seg}:{sec_id_key}"
                    )
                    if not sym:
                        continue
                    ohlc = item.get("ohlc", {})
                    results[sym] = {
                        "ltp":    float(item.get("last_price") or item.get("ltp") or 0),
                        "open":   float(ohlc.get("open",  item.get("open",  0))),
                        "high":   float(ohlc.get("high",  item.get("high",  0))),
                        "low":    float(ohlc.get("low",   item.get("low",   0))),
                        "close":  float(ohlc.get("close", item.get("close", 0))),
                        "volume": int(item.get("volume", 0)),
                        "oi":     int(item.get("oi", 0)),
                        "source": "dhan_quote",
                    }

            logger.info(
                f"get_batch_quotes({mode}): {len(results)}/{len(symbols)} symbols resolved in 1 API call"
            )
            return results

        except Exception as e:
            logger.error(f"get_batch_quotes error: {e}")
            return {}


    # ------------------------------------------------------------------
    # Direct REST API helper — for v2.4/v2.5 endpoints not yet in SDK 2.0.2
    # ------------------------------------------------------------------
    DHAN_BASE_URL = "https://api.dhan.co/v2"
    DHAN_AUTH_URL = "https://auth.dhan.co"

    def _dhan_rest(self, method: str, path: str, payload: dict = None) -> dict:
        """
        Make a direct REST call to DhanHQ API v2.
        Used for endpoints not yet exposed in SDK 2.0.2 (v2.4/v2.5 features).
        """
        if not self.client_id or not self.access_token:
            return {"status": "failure", "remarks": "Credentials not configured"}
        headers = {
            "access-token": self.access_token,
            "client-id": self.client_id,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        url = f"{self.DHAN_BASE_URL}{path}"
        try:
            if method.upper() == "GET":
                r = requests.get(url, headers=headers, timeout=10)
            elif method.upper() == "POST":
                r = requests.post(url, headers=headers, json=payload or {}, timeout=10)
            elif method.upper() == "PUT":
                r = requests.put(url, headers=headers, json=payload or {}, timeout=10)
            elif method.upper() == "DELETE":
                r = requests.delete(url, headers=headers, timeout=10)
            else:
                return {"status": "failure", "remarks": f"Unknown method {method}"}
            try:
                data = r.json()
            except Exception:
                data = {"raw": r.text, "http_status": r.status_code}
            if r.status_code in (200, 201, 202):
                if isinstance(data, dict) and "status" not in data:
                    data["status"] = "success"
            else:
                if isinstance(data, dict) and "status" not in data:
                    data["status"] = "failure"
                    data["remarks"] = data.get("message", r.text)
            return data
        except Exception as e:
            logger.error(f"DhanHQ REST {method} {path} error: {e}")
            return {"status": "failure", "remarks": str(e)}

    # ------------------------------------------------------------------
    # Authentication & Token Management
    # ------------------------------------------------------------------

    async def get_profile(self) -> dict:
        """
        GET /v2/profile — Validate token and check account setup.
        Returns: dhanClientId, tokenValidity, activeSegment, dataPlan, dataValidity
        """
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, lambda: self._dhan_rest("GET", "/profile"))
        except Exception as e:
            logger.error(f"get_profile error: {e}")
            return {}

    async def renew_token(self) -> dict:
        """
        GET /v2/RenewToken — Renew active access token for another 24 hours.
        Note: Only works for tokens generated from Dhan Web (not TOTP-generated).
        Returns new accessToken + expiryTime on success.
        """
        try:
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(None, lambda: self._dhan_rest("GET", "/RenewToken"))
            if resp.get("status") == "success" and resp.get("accessToken"):
                # Update in-memory token
                self.access_token = resp["accessToken"]
                self._token_created_at = datetime.now()
                logger.info(f"DhanHQ token renewed. Expires: {resp.get('expiryTime')}")
            return resp
        except Exception as e:
            logger.error(f"renew_token error: {e}")
            return {}

    async def _ensure_token_fresh(self) -> None:
        """
        Proactive token refresh (Medallion CEO Fix #4).

        Called before order placement and market-data fetches.
        Renews the token when it has been alive for ≥ 4 hours so we never
        hit mid-session expiry during live trading.  Safe to call frequently
        — skips the network call when the token is still fresh.

        Panel Fix R4: TOTP-generated tokens cannot be renewed via the REST API.
        After the first failed renewal attempt we set `_renewal_not_supported=True`
        and skip all subsequent calls, preventing a retry storm that could trigger
        DhanHQ IP-level rate-limiting.
        """
        if not self.dhan or not self._token_created_at:
            return  # Not connected or token age unknown — skip
        # Suppress retries once we know renewal is not supported (e.g. TOTP token)
        if getattr(self, '_renewal_not_supported', False):
            return
        elapsed_h = (datetime.now() - self._token_created_at).total_seconds() / 3600
        if elapsed_h >= self._token_refresh_interval_h:
            logger.info(
                f"DhanHQ token is {elapsed_h:.1f}h old — proactively refreshing "
                f"(threshold={self._token_refresh_interval_h}h)"
            )
            result = await self.renew_token()
            if not (result or {}).get('accessToken'):
                self._renewal_not_supported = True
                logger.info(
                    "Token renewal returned no accessToken — likely a TOTP-scoped token. "
                    "Suppressing further renewal attempts for this session."
                )

    @staticmethod
    def generate_totp_token(client_id: str, pin: str, totp: str) -> dict:
        """
        POST https://auth.dhan.co/app/generateAccessToken
        Generate a new 24-hour access token using TOTP (no existing token needed).

        Args:
            client_id: Dhan client ID
            pin:       6-digit Dhan PIN
            totp:      Current TOTP code from authenticator app

        Returns dict with accessToken + expiryTime on success.
        """
        try:
            url = (
                f"https://auth.dhan.co/app/generateAccessToken"
                f"?dhanClientId={client_id}&pin={pin}&totp={totp}"
            )
            r = requests.post(url, timeout=15)
            try:
                return r.json()
            except Exception:
                return {"status": "failure", "raw": r.text}
        except Exception as e:
            logger.error(f"generate_totp_token error: {e}")
            return {"status": "failure", "remarks": str(e)}

    # ------------------------------------------------------------------
    # Static IP Management (MANDATORY for Order APIs as of v2.4)
    # ------------------------------------------------------------------

    async def get_ip_config(self) -> dict:
        """
        GET /v2/ip/getIP — Get currently whitelisted primary/secondary static IPs.
        Returns: primaryIP, secondaryIP, modifyDatePrimary, modifyDateSecondary
        """
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, lambda: self._dhan_rest("GET", "/ip/getIP"))
        except Exception as e:
            logger.error(f"get_ip_config error: {e}")
            return {}

    async def set_static_ip(self, ip: str, ip_flag: str = "PRIMARY") -> dict:
        """
        POST /v2/ip/setIP — Whitelist a static IP for Order APIs.
        ip_flag: 'PRIMARY' or 'SECONDARY'
        Note: IP cannot be changed for 7 days after setting.
        """
        try:
            payload = {
                "dhanClientId": self.client_id,
                "ip": ip,
                "ipFlag": ip_flag.upper()
            }
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, lambda: self._dhan_rest("POST", "/ip/setIP", payload))
        except Exception as e:
            logger.error(f"set_static_ip error: {e}")
            return {}

    async def modify_static_ip(self, ip: str, ip_flag: str = "PRIMARY") -> dict:
        """PUT /v2/ip/modifyIP — Modify whitelisted IP (once every 7 days)."""
        try:
            payload = {
                "dhanClientId": self.client_id,
                "ip": ip,
                "ipFlag": ip_flag.upper()
            }
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, lambda: self._dhan_rest("PUT", "/ip/modifyIP", payload))
        except Exception as e:
            logger.error(f"modify_static_ip error: {e}")
            return {}

    # ------------------------------------------------------------------
    # Holdings & Order Book
    # ------------------------------------------------------------------

    async def get_holdings(self) -> list:
        """
        GET /v2/holdings — All positions held in demat account (CNC delivery).
        Returns list of: exchange, tradingSymbol, securityId, isin, totalQty,
                    dpQty, t1Qty, availableQty, collateralQty, avgCostPrice
        """
        try:
            if not self.dhan:
                return []
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(None, self.dhan.get_holdings)
            if isinstance(resp, dict) and resp.get("status") == "success":
                return resp.get("data", []) or []
            # Some SDK versions return list directly
            if isinstance(resp, list):
                return resp
            logger.warning(f"get_holdings: {resp.get('remarks', 'unknown')}")
            return []
        except Exception as e:
            logger.error(f"get_holdings error: {e}")
            return []

    async def get_order_book(self) -> list:
        """
        GET /v2/orders — Full order book for the day.
        Returns list of all orders with status, price, qty, timestamps, OMS errors.
        """
        try:
            if not self.dhan:
                return []
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(None, self.dhan.get_order_list)
            if isinstance(resp, dict) and resp.get("status") == "success":
                return resp.get("data", []) or []
            if isinstance(resp, list):
                return resp
            return []
        except Exception as e:
            logger.error(f"get_order_book error: {e}")
            return []

    async def get_order_by_correlation_id(self, correlation_id: str) -> dict:
        """GET /v2/orders/external/{correlation-id} — Retrieve order by user-set tag."""
        try:
            if not self.dhan:
                return {}
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(
                None, lambda: self.dhan.get_order_by_correlationID(correlation_id)
            )
            return resp.get("data", {}) if isinstance(resp, dict) else {}
        except Exception as e:
            logger.error(f"get_order_by_correlation_id error: {e}")
            return {}

    # ------------------------------------------------------------------
    # Trader's Control — Kill Switch
    # ------------------------------------------------------------------

    async def activate_kill_switch(self) -> dict:
        """
        POST /v2/killswitch?killSwitchStatus=ACTIVATE
        Disable all trading for the current day.
        ⚠ Ensure all positions are closed and no pending orders before calling.
        """
        try:
            if not self.dhan:
                return {"status": "failure", "remarks": "Not connected"}
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(None, lambda: self.dhan.kill_switch("ACTIVATE"))
            if resp.get("status") == "success":
                logger.warning("🚨 KILL SWITCH ACTIVATED — Trading disabled for today")
            return resp
        except Exception as e:
            logger.error(f"activate_kill_switch error: {e}")
            return {"status": "failure", "remarks": str(e)}

    async def deactivate_kill_switch(self) -> dict:
        """POST /v2/killswitch?killSwitchStatus=DEACTIVATE — Re-enable trading."""
        try:
            if not self.dhan:
                return {"status": "failure", "remarks": "Not connected"}
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, lambda: self.dhan.kill_switch("DEACTIVATE"))
        except Exception as e:
            logger.error(f"deactivate_kill_switch error: {e}")
            return {"status": "failure", "remarks": str(e)}

    async def get_kill_switch_status(self) -> dict:
        """GET /v2/killswitch — Check if kill switch is currently ACTIVE or DEACTIVE."""
        try:
            # SDK 2.0.2 does not have status_kill_switch() — use REST directly
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(None, lambda: self._dhan_rest("GET", "/killswitch"))
            return resp
        except Exception as e:
            logger.error(f"get_kill_switch_status error: {e}")
            return {}

    # ------------------------------------------------------------------
    # Trader's Control — P&L Based Auto-Exit (v2.5)
    # ------------------------------------------------------------------

    async def configure_pnl_exit(
        self,
        profit_value: float,
        loss_value: float,
        product_types: List[str] = None,
        enable_kill_switch: bool = True,
    ) -> dict:
        """
        POST /v2/pnlExit — Set automatic exit when P&L thresholds are breached.

        Args:
            profit_value:       Auto-exit when cumulative profit ≥ this value (INR)
            loss_value:         Auto-exit when cumulative loss ≥ this value (INR)
            product_types:      ["INTRADAY", "DELIVERY"] — which positions to monitor
            enable_kill_switch: Also activate kill switch when exit triggers

        ⚠ If profitValue is below current P&L or lossValue above current loss,
          exit triggers IMMEDIATELY.
        """
        try:
            payload = {
                "profitValue": str(round(float(profit_value), 2)),
                "lossValue": str(round(float(loss_value), 2)),
                "productType": product_types or ["INTRADAY", "DELIVERY"],
                "enableKillSwitch": bool(enable_kill_switch),
            }
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(None, lambda: self._dhan_rest("POST", "/pnlExit", payload))
            if resp.get("pnlExitStatus") == "ACTIVE":
                resp["status"] = "success"
                logger.info(f"P&L exit configured: profit={profit_value}, loss={loss_value}")
            return resp
        except Exception as e:
            logger.error(f"configure_pnl_exit error: {e}")
            return {"status": "failure", "remarks": str(e)}

    async def stop_pnl_exit(self) -> dict:
        """DELETE /v2/pnlExit — Disable the active P&L based exit configuration."""
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, lambda: self._dhan_rest("DELETE", "/pnlExit"))
        except Exception as e:
            logger.error(f"stop_pnl_exit error: {e}")
            return {"status": "failure", "remarks": str(e)}

    async def get_pnl_exit_config(self) -> dict:
        """GET /v2/pnlExit — Fetch current active P&L exit configuration."""
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, lambda: self._dhan_rest("GET", "/pnlExit"))
        except Exception as e:
            logger.error(f"get_pnl_exit_config error: {e}")
            return {}

    # ------------------------------------------------------------------
    # Super Orders — Entry + Target + Stop Loss in one bundle
    # ------------------------------------------------------------------

    async def place_super_order(
        self,
        security_id: str,
        exchange_segment: str,
        transaction_type: str,
        quantity: int,
        order_type: str,
        product_type: str,
        price: float,
        target_price: float,
        stop_loss_price: float,
        trailing_jump: float = 0.0,
        tag: str = None,
    ) -> dict:
        """
        POST /v2/super/orders — Place entry + target + stop-loss as one order.
        Requires Static IP whitelisting.

        Args:
            trailing_jump: Amount (INR) by which SL trails the price (0 = no trail)
        Returns dict with orderId + orderStatus.
        """
        try:
            if not self.dhan:
                return {"status": "failure", "remarks": "Not connected"}
            paper_mode = os.getenv("PAPER_TRADING", "true").lower() == "true"
            if paper_mode or settings.PAPER_TRADING:
                import uuid
                oid = f"SIM-SUPER-{uuid.uuid4().hex[:8]}"
                logger.info(f"[PAPER] Super order: {transaction_type} {quantity}x {security_id} entry={price} target={target_price} sl={stop_loss_price}")
                return {"status": "success", "data": {"orderId": oid, "orderStatus": "PENDING"}}
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(
                None,
                lambda: self.dhan.place_super_order(
                    security_id=str(security_id),
                    exchange_segment=str(exchange_segment),
                    transaction_type=str(transaction_type),
                    quantity=int(quantity),
                    order_type=str(order_type),
                    product_type=str(product_type),
                    price=float(price),
                    targetPrice=float(target_price),
                    stopLossPrice=float(stop_loss_price),
                    trailingJump=float(trailing_jump),
                    tag=tag,
                ),
            )
            return resp
        except Exception as e:
            logger.error(f"place_super_order error: {e}")
            return {"status": "failure", "remarks": str(e)}

    async def modify_super_order(
        self,
        order_id: str,
        leg_name: str,
        order_type: str = "LIMIT",
        quantity: int = 0,
        price: float = 0.0,
        target_price: float = 0.0,
        stop_loss_price: float = 0.0,
        trailing_jump: float = 0.0,
    ) -> dict:
        """
        PUT /v2/super/orders/{order-id}
        leg_name: ENTRY_LEG | TARGET_LEG | STOP_LOSS_LEG
        - ENTRY_LEG: can modify all fields (only while PENDING/PART_TRADED)
        - TARGET_LEG: only targetPrice
        - STOP_LOSS_LEG: only stopLossPrice + trailingJump
        """
        try:
            if not self.dhan:
                return {"status": "failure", "remarks": "Not connected"}
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None,
                lambda: self.dhan.modify_super_order(
                    order_id=str(order_id),
                    order_type=str(order_type),
                    leg_name=str(leg_name),
                    quantity=int(quantity),
                    price=float(price),
                    targetPrice=float(target_price),
                    stopLossPrice=float(stop_loss_price),
                    trailingJump=float(trailing_jump),
                ),
            )
        except Exception as e:
            logger.error(f"modify_super_order error: {e}")
            return {"status": "failure", "remarks": str(e)}

    async def cancel_super_order(self, order_id: str, order_leg: str = "ENTRY_LEG") -> dict:
        """
        DELETE /v2/super/orders/{order-id}/{order-leg}
        Cancelling ENTRY_LEG cancels all legs. TARGET_LEG / STOP_LOSS_LEG cannot be re-added.
        """
        try:
            if not self.dhan:
                return {"status": "failure", "remarks": "Not connected"}
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None,
                lambda: self.dhan.cancel_super_order(
                    order_id=str(order_id),
                    order_leg=str(order_leg),
                ),
            )
        except Exception as e:
            logger.error(f"cancel_super_order error: {e}")
            return {"status": "failure", "remarks": str(e)}

    async def get_super_orders(self) -> list:
        """GET /v2/super/orders — Full super-order book with nested legs."""
        try:
            if not self.dhan:
                return []
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(None, self.dhan.get_super_order_list)
            if isinstance(resp, dict) and resp.get("status") == "success":
                return resp.get("data", []) or []
            if isinstance(resp, list):
                return resp
            return []
        except Exception as e:
            logger.error(f"get_super_orders error: {e}")
            return []

    # ------------------------------------------------------------------
    # Forever Orders — GTC/GTT (Good Till Triggered)
    # ------------------------------------------------------------------

    async def place_forever_order(
        self,
        security_id: str,
        exchange_segment: str,
        transaction_type: str,
        product_type: str,
        order_type: str,
        quantity: int,
        price: float,
        trigger_price: float,
        order_flag: str = "SINGLE",
        disclosed_quantity: int = 0,
        validity: str = "DAY",
        price1: float = 0.0,
        trigger_price1: float = 0.0,
        quantity1: int = 0,
        tag: str = None,
        symbol: str = "",
    ) -> dict:
        """
        POST /v2/forever/orders — Place Good-Till-Triggered (GTT) order.

        Args:
            order_flag: 'SINGLE' (single trigger) or 'OCO' (one-cancels-other)
            price1, trigger_price1, quantity1: OCO second-leg params (if order_flag=OCO)
        """
        try:
            if not self.dhan:
                return {"status": "failure", "remarks": "Not connected"}
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None,
                lambda: self.dhan.place_forever(
                    security_id=str(security_id),
                    exchange_segment=str(exchange_segment),
                    transaction_type=str(transaction_type),
                    product_type=str(product_type),
                    order_type=str(order_type),
                    quantity=int(quantity),
                    price=float(price),
                    trigger_Price=float(trigger_price),
                    order_flag=str(order_flag),
                    disclosed_quantity=int(disclosed_quantity),
                    validity=str(validity),
                    price1=float(price1),
                    trigger_Price1=float(trigger_price1),
                    quantity1=int(quantity1),
                    tag=tag,
                    symbol=str(symbol),
                ),
            )
        except Exception as e:
            logger.error(f"place_forever_order error: {e}")
            return {"status": "failure", "remarks": str(e)}

    async def modify_forever_order(
        self,
        order_id: str,
        order_flag: str,
        order_type: str,
        leg_name: str,
        quantity: int,
        price: float,
        trigger_price: float,
        disclosed_quantity: int = 0,
        validity: str = "DAY",
    ) -> dict:
        """PUT /v2/forever/orders/{order-id} — Modify an existing forever order."""
        try:
            if not self.dhan:
                return {"status": "failure", "remarks": "Not connected"}
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None,
                lambda: self.dhan.modify_forever(
                    order_id=str(order_id),
                    order_flag=str(order_flag),
                    order_type=str(order_type),
                    leg_name=str(leg_name),
                    quantity=int(quantity),
                    price=float(price),
                    trigger_price=float(trigger_price),
                    disclosed_quantity=int(disclosed_quantity),
                    validity=str(validity),
                ),
            )
        except Exception as e:
            logger.error(f"modify_forever_order error: {e}")
            return {"status": "failure", "remarks": str(e)}

    async def cancel_forever_order(self, order_id: str) -> dict:
        """DELETE /v2/forever/orders/{order-id} — Cancel a pending forever order."""
        try:
            if not self.dhan:
                return {"status": "failure", "remarks": "Not connected"}
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None, lambda: self.dhan.cancel_forever(order_id=str(order_id))
            )
        except Exception as e:
            logger.error(f"cancel_forever_order error: {e}")
            return {"status": "failure", "remarks": str(e)}

    async def get_forever_orders(self) -> list:
        """GET /v2/forever/orders — List all active forever orders."""
        try:
            if not self.dhan:
                return []
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(None, self.dhan.get_forever)
            if isinstance(resp, dict) and resp.get("status") == "success":
                return resp.get("data", []) or []
            if isinstance(resp, list):
                return resp
            return []
        except Exception as e:
            logger.error(f"get_forever_orders error: {e}")
            return []

    # ------------------------------------------------------------------
    # Funds & Margin
    # ------------------------------------------------------------------

    async def calculate_margin(
        self,
        security_id: str,
        exchange_segment: str,
        transaction_type: str,
        quantity: int,
        product_type: str,
        price: float,
        trigger_price: float = 0.0,
    ) -> dict:
        """
        POST /v2/margincalculator — Margin requirement for a single order.
        Returns: totalMargin, spanMargin, exposureMargin, variableMargin,
                 availableBalance, insufficientBalance, brokerage, leverage
        """
        try:
            if not self.dhan:
                return {}
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(
                None,
                lambda: self.dhan.margin_calculator(
                    security_id=str(security_id),
                    exchange_segment=str(exchange_segment),
                    transaction_type=str(transaction_type),
                    quantity=int(quantity),
                    product_type=str(product_type),
                    price=float(price),
                    trigger_price=float(trigger_price),
                ),
            )
            return resp.get("data", resp) if isinstance(resp, dict) else {}
        except Exception as e:
            logger.error(f"calculate_margin error: {e}")
            return {}

    async def calculate_multi_margin(
        self,
        scripts: List[dict],
        include_positions: bool = True,
        include_orders: bool = True,
    ) -> dict:
        """
        POST /v2/margincalculator/multi — Portfolio-level margin for multiple orders.

        Args:
            scripts: list of dicts, each with:
                     {exchangeSegment, transactionType, quantity, productType, securityId, price}
            include_positions: include existing open positions in calculation
            include_orders:    include pending orders in calculation

        Returns: total_margin, span_margin, exposure_margin, equity_margin,
                 fo_margin, commodity_margin, currency (always INR), hedge_benefit
        """
        try:
            payload = {
                "dhanClientId": self.client_id,
                "includePosition": include_positions,
                "includeOrders": include_orders,
                "scripList": scripts,
            }
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None, lambda: self._dhan_rest("POST", "/margincalculator/multi", payload)
            )
        except Exception as e:
            logger.error(f"calculate_multi_margin error: {e}")
            return {}

    # ------------------------------------------------------------------
    # Exit All Positions (v2.5 — DELETE /v2/positions)
    # ------------------------------------------------------------------

    async def exit_all_positions(self) -> dict:
        """
        DELETE /v2/positions — Nuclear option: close ALL open positions and
        cancel ALL pending orders in a single API call.

        ⛔ IRREVERSIBLE — Use only for emergency stop / end-of-day flatten.
        Returns: {status, message}
        """
        try:
            logger.warning("🚨 EXIT ALL POSITIONS called — closing all open positions and orders")
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, lambda: self._dhan_rest("DELETE", "/positions"))
        except Exception as e:
            logger.error(f"exit_all_positions error: {e}")
            return {"status": "failure", "remarks": str(e)}

    # ------------------------------------------------------------------
    # Conditional Triggers (v2.5 — POST /v2/alerts/orders)
    # Trigger orders automatically based on price or technical indicators
    # ------------------------------------------------------------------

    async def place_conditional_trigger(
        self,
        security_id: str,
        exchange_segment: str,
        comparison_type: str,
        operator: str,
        timeframe: str = "DAY",
        indicator_name: str = None,
        comparing_value: float = None,
        comparing_indicator: str = None,
        exp_date: str = None,
        frequency: str = "ONCE",
        user_note: str = "",
        orders: List[dict] = None,
    ) -> dict:
        """
        POST /v2/alerts/orders — Place a conditional trigger order.

        Triggers one or more orders automatically when a condition is met.
        NOTE: Currently supported only for Equities and Indices (not F&O).

        Args:
            comparison_type: PRICE_WITH_VALUE | TECHNICAL_WITH_VALUE |
                             TECHNICAL_WITH_INDICATOR | TECHNICAL_WITH_CLOSE
            operator:        CROSSING_UP | CROSSING_DOWN | GREATER_THAN |
                             LESS_THAN | GREATER_THAN_EQUAL | LESS_THAN_EQUAL |
                             EQUAL | NOT_EQUAL | CROSSING_ANY_SIDE
            timeframe:       DAY | ONE_MIN | FIVE_MIN | FIFTEEN_MIN
            indicator_name:  SMA_5/10/20/50/100/200, EMA_5-200, BB_UPPER/LOWER,
                             RSI_14, ATR_14, STOCHASTIC, STOCHRSI_14, MACD_26/12/HIST
            comparing_value: Fixed numeric value to compare against (PRICE_WITH_VALUE
                             or TECHNICAL_WITH_VALUE)
            comparing_indicator: Second indicator name (TECHNICAL_WITH_INDICATOR)
            exp_date:        Alert expiry date YYYY-MM-DD (default: 1 year from now)
            frequency:       ONCE — trigger once and deactivate
            orders:          List of order dicts to place when condition is met:
                             [{transactionType, exchangeSegment, productType, orderType,
                               securityId, quantity, validity, price, discQuantity, triggerPrice}]

        Returns: {alertId, alertStatus}
        """
        try:
            if exp_date is None:
                exp_date = (datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d")

            condition: dict = {
                "comparisonType": comparison_type,
                "exchangeSegment": exchange_segment,
                "securityId": str(security_id),
                "operator": operator,
                "timeFrame": timeframe,
                "expDate": exp_date,
                "frequency": frequency,
                "userNote": user_note,
            }
            if indicator_name:
                condition["indicatorName"] = indicator_name
            if comparing_value is not None:
                condition["comparingValue"] = comparing_value
            if comparing_indicator:
                condition["comparingIndicatorName"] = comparing_indicator

            payload = {
                "dhanClientId": self.client_id,
                "condition": condition,
                "orders": orders or [],
            }
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(
                None, lambda: self._dhan_rest("POST", "/alerts/orders", payload)
            )
            if resp.get("alertId"):
                resp["status"] = "success"
                logger.info(f"Conditional trigger placed: alertId={resp['alertId']} note={user_note}")
            return resp
        except Exception as e:
            logger.error(f"place_conditional_trigger error: {e}")
            return {"status": "failure", "remarks": str(e)}

    async def get_conditional_triggers(self) -> list:
        """GET /v2/alerts/orders — Get all active conditional triggers."""
        try:
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(None, lambda: self._dhan_rest("GET", "/alerts/orders"))
            if isinstance(resp, list):
                return resp
            if isinstance(resp, dict) and isinstance(resp.get("data"), list):
                return resp["data"]
            return []
        except Exception as e:
            logger.error(f"get_conditional_triggers error: {e}")
            return []

    async def get_conditional_trigger_by_id(self, alert_id: str) -> dict:
        """GET /v2/alerts/orders/{alertId} — Get a specific trigger by ID."""
        try:
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(
                None, lambda: self._dhan_rest("GET", f"/alerts/orders/{alert_id}")
            )
            return resp
        except Exception as e:
            logger.error(f"get_conditional_trigger_by_id error: {e}")
            return {}

    async def modify_conditional_trigger(
        self,
        alert_id: str,
        security_id: str,
        exchange_segment: str,
        comparison_type: str,
        operator: str,
        timeframe: str = "DAY",
        indicator_name: str = None,
        comparing_value: float = None,
        comparing_indicator: str = None,
        exp_date: str = None,
        frequency: str = "ONCE",
        user_note: str = "",
        orders: List[dict] = None,
    ) -> dict:
        """PUT /v2/alerts/orders/{alertId} — Modify an existing conditional trigger."""
        try:
            if exp_date is None:
                exp_date = (datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d")
            condition: dict = {
                "comparisonType": comparison_type,
                "exchangeSegment": exchange_segment,
                "securityId": str(security_id),
                "operator": operator,
                "timeFrame": timeframe,
                "expDate": exp_date,
                "frequency": frequency,
                "userNote": user_note,
            }
            if indicator_name:
                condition["indicatorName"] = indicator_name
            if comparing_value is not None:
                condition["comparingValue"] = comparing_value
            if comparing_indicator:
                condition["comparingIndicatorName"] = comparing_indicator
            payload = {
                "dhanClientId": self.client_id,
                "alertId": str(alert_id),
                "condition": condition,
                "orders": orders or [],
            }
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None, lambda: self._dhan_rest("PUT", f"/alerts/orders/{alert_id}", payload)
            )
        except Exception as e:
            logger.error(f"modify_conditional_trigger error: {e}")
            return {"status": "failure", "remarks": str(e)}

    async def delete_conditional_trigger(self, alert_id: str) -> dict:
        """DELETE /v2/alerts/orders/{alertId} — Cancel a conditional trigger."""
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None, lambda: self._dhan_rest("DELETE", f"/alerts/orders/{alert_id}")
            )
        except Exception as e:
            logger.error(f"delete_conditional_trigger error: {e}")
            return {"status": "failure", "remarks": str(e)}

    # ------------------------------------------------------------------
    # Expired Options Rolling Data (5-year ATM±10 minute-level data)
    # ------------------------------------------------------------------

    async def get_expired_options_rolling(
        self,
        security_id: int,
        exchange_segment: str = "NSE_FNO",
        instrument: str = "OPTIDX",
        interval: int = 1,
        expiry_code: int = 0,
        expiry_flag: str = "MONTH",
        strike: str = "ATM",
        option_type: str = "CALL",
        from_date: str = "",
        to_date: str = "",
        fields: List[str] = None,
    ) -> dict:
        """
        POST /v2/charts/rollingoption — Historical expired options data on rolling basis.

        Fetch up to 5 years of minute-level option data relative to spot (ATM±10).
        Max 30 days per call. Includes IV, OI, OHLCV, spot info.

        Args:
            security_id:    Underlying security ID (e.g. 13 for NIFTY)
            instrument:     OPTIDX | OPTSTK | OPTFUT | OPTCUR
            interval:       1 | 5 | 15 | 25 | 60 (minutes)
            expiry_code:    0=current, 1=next, 2=far
            expiry_flag:    WEEK | MONTH
            strike:         ATM | ATM+1...ATM+10 | ATM-1...ATM-10 (index near-expiry)
                            ATM±3 for all other contracts
            option_type:    CALL | PUT
            from_date:      YYYY-MM-DD
            to_date:        YYYY-MM-DD (max 30 days from from_date)
            fields:         list of: ['open','high','low','close','iv','volume','oi','strike','spot']

        Returns: {data: {ce: {open[], high[], low[], close[], iv[], oi[], timestamp[]}, pe: null}}
        """
        try:
            payload = {
                "exchangeSegment": exchange_segment,
                "interval": str(interval),
                "securityId": int(security_id),
                "instrument": instrument,
                "expiryCode": int(expiry_code),
                "expiryFlag": expiry_flag,
                "strike": strike,
                "drvOptionType": option_type,
                "requiredData": fields or ["open", "high", "low", "close", "volume", "oi", "iv", "spot"],
                "fromDate": from_date,
                "toDate": to_date,
            }
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None, lambda: self._dhan_rest("POST", "/charts/rollingoption", payload)
            )
        except Exception as e:
            logger.error(f"get_expired_options_rolling error: {e}")
            return {}

    # ------------------------------------------------------------------
    # Postback / Webhook helper (informational)
    # ------------------------------------------------------------------

    def get_postback_instructions(self) -> str:
        """
        DhanHQ Postback sends order updates to a Webhook URL you register while
        generating your Access Token on web.dhan.co.

        Setup steps:
          1. Go to web.dhan.co > Profile > Access DhanHQ APIs
          2. While generating Access Token, enter your Webhook URL
          3. DhanHQ will POST order update JSON to your URL for every order event

        Webhook payload structure mirrors the Live Order Update WebSocket payload:
          {"Data": {"OrderNo", "Status", "TradedPrice", "TradedQty", ...}, "Type": "order_alert"}

        Alternatively, in Live Order Update WebSocket:
          - Connect to wss://api-order-update.dhan.co
          - Send auth: {"LoginReq": {"MsgCode": 42, "ClientId": "...", "Token": "JWT"}, "UserType": "SELF"}
        """
        return (
            "Register Webhook URL in web.dhan.co > Profile > Access DhanHQ APIs when generating token. "
            "Or use Live Order Update WebSocket at wss://api-order-update.dhan.co"
        )


# Global instance - lazy initialized
dhan_client = None


def reset_dhan_client() -> None:
    """Reset the DhanClient singleton so the next get_dhan_client() call
    creates a fresh instance reading the latest os.environ credentials.
    Call this after saving new DHAN_CLIENT_ID / DHAN_ACCESS_TOKEN.
    """
    global dhan_client
    dhan_client = None


def get_dhan_client() -> DhanClient:
    """Get or create the DhanHQ client singleton.
    Prefer get_broker_client() from broker_factory for broker-agnostic code.
    """
    global dhan_client
    if dhan_client is None:
        dhan_client = DhanClient()
        dhan_client.connect()
    return dhan_client

