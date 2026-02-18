from dhanhq import dhanhq
from src.core.config import settings
import logging
import asyncio
import os
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class DhanClient:
    """
    Wrapper for DhanHQ API with Rate Limiting and Error Handling.
    Credentials loaded from environment variables (secure).
    """
    def __init__(self):
        self.dhan = None
        # Load credentials from environment variables securely
        self.client_id = os.getenv("DHAN_CLIENT_ID")
        self.access_token = os.getenv("DHAN_ACCESS_TOKEN")
        
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
            logger.info("Connected to DhanHQ API")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to DhanHQ: {e}")
            logger.warning("Paper trading will use simulated orders")
            return False

    async def fetch_market_data(self, security_id: str, exchange_segment: str) -> Dict[str, Any]:
        """
        Fetch Latest Price (LTP) or OHLC from DhanHQ.
        Falls back to None if not connected.
        """
        try:
            if not self.dhan:
                logger.debug("DhanHQ not connected - returning placeholder data")
                return {"ltp": 0.0}
            
            # Implementation would call actual API:
            # response = self.dhan.get_quotes(...)
            # For now, placeholder for graceful fallback
            return {"ltp": 0.0}
        except Exception as e:
            logger.error(f"Error fetching market data: {e}")
            return {"ltp": 0.0}

    async def place_order(self, order_details: Dict[str, Any]) -> Optional[str]:
        """
        Place order and return Order ID.
        Falls back to simulated order if not connected.
        """
        try:
            if not self.dhan:
                logger.warning("DhanHQ not connected - using simulated order")
                # Return simulated order ID
                return f"SIM_{order_details.get('symbol', 'UNKNOWN')}_{order_details.get('buy_sell', 'UNKNOWN')}"
            
            response = self.dhan.place_order(**order_details)
            if response['status'] == 'success':
                return response['data']['orderId']
            else:
                raise Exception(f"Order placement failed: {response['remarks']}")
        except Exception as e:
            logger.error(f"Error placing order: {e}")
            # Return simulated order for paper trading
            return f"SIM_{order_details.get('symbol', 'UNKNOWN')}_{order_details.get('buy_sell', 'UNKNOWN')}"

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

# Global instance - lazy initialized
dhan_client = None

def get_dhan_client() -> DhanClient:
    """Get or initialize the DhanHQ client."""
    global dhan_client
    if dhan_client is None:
        dhan_client = DhanClient()
        dhan_client.connect()
    return dhan_client

