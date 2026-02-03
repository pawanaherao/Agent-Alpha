from typing import Dict, Any, List, Optional
from datetime import datetime
import asyncio
import vertexai
from vertexai.generative_models import GenerativeModel

from src.agents.base import BaseAgent
from src.core.config import settings
from src.core.messages import AgentMessage
from src.services.dhan_client import dhan_client
from src.database.postgres import db

class ExecutionAgent(BaseAgent):
    """
    Agent responsible for Order Execution.
    Phase 4 of Orchestration Loop.
    Modes: MANUAL, AUTO, HYBRID.
    """
    def __init__(self, name: str = "ExecutionAgent", config: Dict[str, Any] = None):
        super().__init__(name, config)
        self.mode = "AUTO" # Default Mode for Testing (was HYBRID)
        self.model = None
        self.project_id = settings.GCP_PROJECT
        self.location = "us-central1"

    async def start(self):
        """Initialize Vertex AI."""
        await super().start()
        try:
            vertexai.init(project=self.project_id, location=self.location)
            self.model = GenerativeModel("gemini-1.5-pro-preview-0409")
            self.logger.info("Connected to Vertex AI for Trade Justification")
        except Exception as e:
            self.logger.error(f"Failed to initialize Vertex AI: {e}")

    async def execute_trade(self, order_package: Dict[str, Any]):
        """
        Execute approved trade based on mode.
        """
        signal = order_package['signal']
        decision = order_package['risk_decision']
        
        strength = signal.get('strength', 0.0)
        
        # Mode Logic
        should_auto_execute = False
        
        if self.mode == "AUTO":
            should_auto_execute = True
        elif self.mode == "HYBRID":
            if strength > 0.8:
                should_auto_execute = True
            else:
                should_auto_execute = False
        else: # MANUAL
            should_auto_execute = False
            
        if should_auto_execute:
            await self._place_market_order(signal, decision)
        else:
            await self._request_user_approval(signal, decision)

    async def _place_market_order(self, signal: Dict, decision: Dict):
        """Send order to DhanHQ."""
        try:
            order_id = await dhan_client.place_order({
                "transactionType": signal['signal_type'],
                "exchangeSegment": "NSE_FNO",
                "productType": "INTRADAY",
                "orderType": "MARKET",
                "validity": "DAY",
                "tradingSymbol": signal['symbol'],
                "securityId": "1333", # TODO: Lookup ID
                "quantity": decision['modifications'].get('quantity', 1)
            })
            self.logger.info(f"Order Placed. ID: {order_id}")
            
            # Publish Event
            await self.publish_event("ORDER_FILLED", {
                "order_id": order_id,
                "symbol": signal['symbol'],
                "status": "FILLED"
            })
            
            # Persist to DB
            await db.execute(
                "INSERT INTO trades (order_id, symbol, signal_type, quantity, status) VALUES ($1, $2, $3, $4, $5)",
                str(order_id),
                signal['symbol'],
                signal['signal_type'],
                decision['modifications'].get('quantity', 1),
                "FILLED"
            )
            
        except Exception as e:
            self.logger.error(f"Execution Failed: {e}")

    async def _request_user_approval(self, signal: Dict, decision: Dict):
        """
        Notify User for Manual Approval with AI-Generated Justification.
        """
        self.logger.info(f"Requesting User Validation for {signal['symbol']}")
        
        # 1. Generate "The Why"
        justification = await self._generate_justification(signal, decision)
        
        # 2. Create Approval Request (Mock)
        approval_request = {
            "signal": signal,
            "justification": justification,
            "decision": decision,
            "timestamp": datetime.now().isoformat()
        }
        
        # TODO: Send payload to Frontend/App via Firebase
        self.logger.info(f"APPROVAL REQUEST SENT: {justification}")

    async def _generate_justification(self, signal: Dict, decision: Dict) -> str:
        """
        Ask Gemini to explain the trade in plain English.
        """
        try:
            prompt = f"""
            You are an expert Senior Trader. Explain why this trade should be taken to a junior trader.
            Be concise, persuasive, and data-driven.
            
            Strategy: {signal['strategy_name']}
            Symbol: {signal['symbol']}
            Type: {signal['signal_type']}
            Strength: {signal['strength']}
            
            Context:
            Regime: {signal['market_regime_at_signal']}
            
            Output a 2-sentence justification.
            """
            
            if self.model:
                response = self.model.generate_content(prompt)
                return response.text.strip()
            return "Trade generated by algorithmic strategy."
            
        except Exception as e:
            self.logger.error(f"Failed to generate justification: {e}")
            return "Justification unavailable."
        
    async def on_orders_approved(self, payload: Dict[str, Any]):
        """
        Event Handler for SIGNALS_APPROVED.
        """
        orders = payload.get('orders', [])
        for order in orders:
            await self.execute_trade(order)
