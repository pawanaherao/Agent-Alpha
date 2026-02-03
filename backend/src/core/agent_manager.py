import asyncio
import logging
from typing import Dict, Any, List

from src.core.event_bus import EventBus
from src.core.config import settings

# Import Agents
from src.agents.sentiment import SentimentAgent
from src.agents.regime import RegimeAgent
from src.agents.scanner import ScannerAgent
from src.agents.strategy import StrategyAgent
from src.agents.risk import RiskAgent
from src.agents.execution import ExecutionAgent
from src.agents.portfolio import PortfolioAgent
from src.agents.init_agents import initialize_strategy_agent

logger = logging.getLogger(__name__)

class AgentManager:
    """
    Central Orchestrator for the Agentic System.
    Manages Agent Lifecycle and the 3-Minute Execution Loop.
    """
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self.agents: Dict[str, Any] = {}
        self.is_running = False

    async def initialize_agents(self):
        """Initialize and Wire all agents."""
        logger.info("Initializing Agents...")
        
        # 1. Sensing Agents
        self.agents["sentiment"] = SentimentAgent("SentimentAgent")
        self.agents["regime"] = RegimeAgent("RegimeAgent")
        self.agents["scanner"] = ScannerAgent("ScannerAgent")
        
        # 2. Decision Agent (Special Factory Init)
        self.agents["strategy"] = await initialize_strategy_agent({})
        
        # 3. Risk Agent
        self.agents["risk"] = RiskAgent("RiskAgent")
        
        # 4. Execution Agent
        self.agents["execution"] = ExecutionAgent("ExecutionAgent")
        
        # 5. Portfolio Agent
        self.agents["portfolio"] = PortfolioAgent("PortfolioAgent")
        
        # Set Event Bus for all
        for name, agent in self.agents.items():
            agent.event_bus = self.event_bus
            
        # Wire Event Subscriptions
        # Risk Agent listens to Signals
        self.event_bus.subscribe("SIGNALS_GENERATED", self.agents["risk"].on_signals_received)
        
        # Execution Agent listens to Approved Orders
        self.event_bus.subscribe("SIGNALS_APPROVED", self.agents["execution"].on_orders_approved)
        
        # Portfolio Agent listens to Fills
        self.event_bus.subscribe("ORDER_FILLED", self.agents["portfolio"].on_order_filled)
        
        logger.info("Agents Initialized and Wired.")

    async def start_all(self):
        """Start all agents."""
        tasks = [agent.start() for agent in self.agents.values()]
        await asyncio.gather(*tasks)
        self.is_running = True
        logger.info("All Agents Started.")

    async def stop_all(self):
        """Stop all agents."""
        logger.info("Stopping Agents...")
        tasks = [agent.stop() for agent in self.agents.values()]
        await asyncio.gather(*tasks)
        self.is_running = False
        logger.info("All Agents Stopped.")

    async def run_cycle(self):
        """
        Execute one full 3-minute orchestration cycle.
        Now uses REAL NSE data via nselib.
        """
        if not self.is_running:
            logger.warning("AgentManager not running. Skipping cycle.")
            return

        cycle_id = f"CYCLE_{asyncio.get_running_loop().time()}"
        logger.info(f"🔄 Starting Cycle: {cycle_id}")
        
        try:
            # === Phase 1: Sensing (Parallel) ===
            logger.info("--- Phase 1: Sensing ---")
            
            # Sentiment analysis (existing)
            sentiment_task = asyncio.create_task(self.agents["sentiment"].analyze())
            
            # Regime classification with REAL NSE data
            # The RegimeAgent now fetches real NIFTY 50 data via nse_data_service
            regime_task = asyncio.create_task(
                self.agents["regime"].analyze_with_real_data("NIFTY 50")
            )
            
            # Scanner scans the universe
            scanner_task = asyncio.create_task(self.agents["scanner"].scan_universe())
            
            sentiment_score, regime, opportunities = await asyncio.gather(
                sentiment_task, regime_task, scanner_task
            )
            
            logger.info(f"Sensing Complete. Regime: {regime}, Sentiment: {sentiment_score}, Opps: {len(opportunities)}")

            # === Phase 2: Decision (Sequential) ===
            logger.info("--- Phase 2: Decision ---")
            # Strategy Agent generates signals based on output of Phase 1
            await self.agents["strategy"].select_and_execute(
                regime=regime,
                sentiment=sentiment_score,
                opportunities=opportunities
            )
            
            # Note: Phase 3 (Risk) and Phase 4 (Execution) are event-driven 
            # triggered by 'SIGNALS_GENERATED' event published by StrategyAgent.
            # We don't await them here explicitly to allow async processing, 
            # or we could await a 'CYCLE_COMPLETE' event if we wanted strict blocking.
            
            # === Phase 5: Monitoring ===
            logger.info("--- Phase 5: Monitoring ---")
            await self.agents["portfolio"].update_portfolio()
            
            logger.info(f"✅ Cycle {cycle_id} Initiated Successfully.")

        except Exception as e:
            logger.error(f"❌ Cycle Failed: {e}", exc_info=True)
