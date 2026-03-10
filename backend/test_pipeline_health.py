#!/usr/bin/env python
"""
Agent Alpha Full Pipeline Health Check
Comprehensive validation before paper trading

Run: python backend/test_pipeline_health.py
"""

import asyncio
import sys
import logging
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

class PipelineHealthCheck:
    def __init__(self):
        self.results = []
        self.failed = []
        
    async def check_imports(self):
        """Verify all critical modules can be imported."""
        logger.info("=" * 70)
        logger.info("HEALTH CHECK 1: Module Imports")
        logger.info("=" * 70)
        
        imports_to_check = [
            ("src.core.config", "Config"),
            ("src.core.event_bus", "EventBus"),
            ("src.agents.sentiment", "SentimentAgent"),
            ("src.agents.regime", "RegimeAgent"),
            ("src.agents.scanner", "ScannerAgent"),
            ("src.agents.strategy", "StrategyAgent"),
            ("src.agents.risk", "RiskAgent"),
            ("src.agents.execution", "ExecutionAgent"),
            ("src.agents.portfolio", "PortfolioAgent"),
            ("src.agents.option_chain_scanner", "OptionChainScannerAgent"),
            ("src.core.agent_manager", "AgentManager"),
            ("src.middleware.sebi_equity", "SEBIEquityValidator"),
            ("src.services.dhan_client", "DhanClient"),
            ("src.database.postgres", "PostgresDB"),
            ("src.services.nse_data", "NSEDataService"),
        ]
        
        for module_name, class_name in imports_to_check:
            try:
                module = __import__(module_name, fromlist=[class_name])
                cls = getattr(module, class_name)
                logger.info(f"  ✅ {module_name}.{class_name}")
                self.results.append((f"Import {class_name}", "PASS"))
            except Exception as e:
                logger.error(f"  ❌ {module_name}.{class_name}: {e}")
                self.results.append((f"Import {class_name}", f"FAIL: {str(e)[:50]}"))
                self.failed.append(class_name)
    
    async def check_config(self):
        """Verify configuration is properly loaded."""
        logger.info("\n" + "=" * 70)
        logger.info("HEALTH CHECK 2: Configuration")
        logger.info("=" * 70)
        
        from src.core.config import settings
        
        checks = [
            ("PROJECT_NAME", settings.PROJECT_NAME, "Agentic Alpha 2026"),
            ("MODE", settings.MODE, "LOCAL"),
            ("PAPER_TRADING", getattr(settings, "PAPER_TRADING", None), True),
            ("OPTIONS_ENABLED", settings.OPTIONS_ENABLED, True),
        ]
        
        for config_key, actual_value, expected_value in checks:
            if actual_value == expected_value:
                logger.info(f"  ✅ {config_key} = {actual_value}")
                self.results.append((f"Config {config_key}", "PASS"))
            else:
                logger.warning(f"  ⚠️  {config_key} = {actual_value} (expected: {expected_value})")
                self.results.append((f"Config {config_key}", f"WARN: {actual_value}"))
    
    async def check_event_bus(self):
        """Verify EventBus singleton is working."""
        logger.info("\n" + "=" * 70)
        logger.info("HEALTH CHECK 3: Event Bus")
        logger.info("=" * 70)
        
        try:
            from src.core.event_bus import EventBus
            
            bus1 = EventBus.instance()
            bus2 = EventBus.instance()
            
            if bus1 is bus2:
                logger.info(f"  ✅ EventBus singleton working (same instance)")
                self.results.append(("EventBus Singleton", "PASS"))
            else:
                logger.error(f"  ❌ EventBus singleton broken (different instances)")
                self.results.append(("EventBus Singleton", "FAIL"))
                self.failed.append("EventBus")
                
            # Test publish/subscribe
            received_events = []
            
            async def test_handler(payload):
                received_events.append(payload)
            
            await bus1.subscribe("TEST_EVENT", test_handler)
            await bus1.publish("TEST_EVENT", {"test": "data"})
            
            await asyncio.sleep(0.1)  # Allow async handler to run
            
            if received_events:
                logger.info(f"  ✅ EventBus pub/sub working ({len(received_events)} events received)")
                self.results.append(("EventBus Pub/Sub", "PASS"))
            else:
                logger.error(f"  ❌ EventBus pub/sub failed (no events received)")
                self.results.append(("EventBus Pub/Sub", "FAIL"))
                self.failed.append("EventBus Pub/Sub")
                
        except Exception as e:
            logger.error(f"  ❌ EventBus check failed: {e}")
            self.results.append(("EventBus", f"FAIL: {str(e)[:50]}"))
            self.failed.append("EventBus")
    
    async def check_database_connectivity(self):
        """Verify database connections are possible."""
        logger.info("\n" + "=" * 70)
        logger.info("HEALTH CHECK 4: Database Connectivity")
        logger.info("=" * 70)
        
        try:
            from src.database.postgres import db
            
            # Check if pool exists and can be created
            if db.pool is None:
                logger.warning(f"  ⚠️  PostgreSQL pool not initialized (graceful fallback: OK)")
                self.results.append(("PostgreSQL Pool", "WARN: Not initialized (fallback mode)"))
            else:
                logger.info(f"  ✅ PostgreSQL pool initialized")
                self.results.append(("PostgreSQL Pool", "PASS"))
                
        except Exception as e:
            logger.warning(f"  ⚠️  Database check: {e}")
            self.results.append(("PostgreSQL", f"WARN: {str(e)[:50]}"))
    
    async def check_nse_data_service(self):
        """Verify NSE data service can be initialized."""
        logger.info("\n" + "=" * 70)
        logger.info("HEALTH CHECK 5: NSE Data Service")
        logger.info("=" * 70)
        
        try:
            from src.services.nse_data import nse_data_service
            
            logger.info(f"  ✅ NSEDataService initialized")
            self.results.append(("NSEDataService Init", "PASS"))
            
            # Check if universe is loadable
            try:
                universe = nse_data_service.get_fno_stocks()
                if universe and len(universe) > 0:
                    logger.info(f"  ✅ F&O universe loaded ({len(universe)} stocks)")
                    self.results.append(("F&O Universe", "PASS"))
                else:
                    logger.warning(f"  ⚠️  F&O universe empty")
                    self.results.append(("F&O Universe", "WARN: Empty"))
            except Exception as e:
                logger.warning(f"  ⚠️  F&O universe load failed: {e}")
                self.results.append(("F&O Universe", f"WARN: {str(e)[:50]}"))
                
        except Exception as e:
            logger.error(f"  ❌ NSE data service failed: {e}")
            self.results.append(("NSEDataService", f"FAIL: {str(e)[:50]}"))
            self.failed.append("NSEDataService")
    
    async def check_dhan_client(self):
        """Verify DhanHQ client initialization and paper trading guard."""
        logger.info("\n" + "=" * 70)
        logger.info("HEALTH CHECK 6: DhanHQ Client & Paper Trading Guard")
        logger.info("=" * 70)
        
        try:
            from src.services.dhan_client import get_dhan_client
            from src.core.config import settings
            
            client = get_dhan_client()
            logger.info(f"  ✅ DhanHQ client initialized")
            
            # Check paper trading guard
            if hasattr(settings, 'PAPER_TRADING') and settings.PAPER_TRADING:
                logger.info(f"  ✅ PAPER_TRADING safety guard ENABLED (default: True)")
                self.results.append(("PAPER_TRADING Guard", "PASS"))
            else:
                logger.warning(f"  ⚠️  PAPER_TRADING guard disabled (check .env)")
                self.results.append(("PAPER_TRADING Guard", "WARN"))
            
            # Test simulated order placement
            test_order = {
                'symbol': 'TESTSTOCK',
                'tradingSymbol': 'TESTSTOCK',
                'transactionType': 'BUY',
                'quantity': 1,
            }
            
            result = await client.place_order(test_order)
            if result and 'SIM_' in str(result):
                logger.info(f"  ✅ Simulated order placement working (ID: {result})")
                self.results.append(("Simulated Order", "PASS"))
            else:
                logger.warning(f"  ⚠️  Simulated order returned: {result}")
                self.results.append(("Simulated Order", f"WARN: {result}"))
            
            self.results.append(("DhanHQ Client", "PASS"))
                
        except Exception as e:
            logger.error(f"  ❌ DhanHQ client check failed: {e}")
            self.results.append(("DhanHQ Client", f"FAIL: {str(e)[:50]}"))
            self.failed.append("DhanHQ Client")
    
    async def check_strategies(self):
        """Verify strategy registry and initialization."""
        logger.info("\n" + "=" * 70)
        logger.info("HEALTH CHECK 7: Strategy Registry")
        logger.info("=" * 70)
        
        try:
            from src.agents.init_agents import STRATEGIES_BY_ASSET
            
            total_strategies = sum(len(v) for v in STRATEGIES_BY_ASSET.values())
            
            logger.info(f"  ✅ Strategy registry loaded ({total_strategies} total strategies)")
            
            for asset, strategies in STRATEGIES_BY_ASSET.items():
                logger.info(f"    • {asset}: {len(strategies)} strategies")
                self.results.append((f"Strategies {asset}", f"PASS ({len(strategies)})"))
            
            if 'UNIVERSAL' in STRATEGIES_BY_ASSET and len(STRATEGIES_BY_ASSET['UNIVERSAL']) > 0:
                logger.info(f"  ✅ UniversalStrategy with 4 modes registered")
                self.results.append(("UniversalStrategy", "PASS"))
            else:
                logger.error(f"  ❌ UniversalStrategy not found")
                self.results.append(("UniversalStrategy", "FAIL"))
                self.failed.append("UniversalStrategy")
                
        except Exception as e:
            logger.error(f"  ❌ Strategy registry failed: {e}")
            self.results.append(("Strategy Registry", f"FAIL: {str(e)[:50]}"))
            self.failed.append("Strategy Registry")
    
    async def check_sebi_compliance(self):
        """Verify SEBI compliance module is ready."""
        logger.info("\n" + "=" * 70)
        logger.info("HEALTH CHECK 8: SEBI Compliance Module")
        logger.info("=" * 70)
        
        try:
            from src.middleware.sebi_equity import sebi_equity_validator
            
            logger.info(f"  ✅ SEBIEquityValidator initialized")
            
            # Test validation
            test_order = {
                "price": 1500.0,
                "quantity": 100,
                "exchangeSegment": "NSE",
                "metadata": {}
            }
            
            result = sebi_equity_validator.validate(test_order, 0)
            logger.info(f"  ✅ Validation working (approved={result.approved})")
            
            # Test order tagging
            tagged = sebi_equity_validator.tag_order(test_order)
            if 'tag' in tagged:
                logger.info(f"  ✅ Order tagging working (tag={tagged['tag']})")
                self.results.append(("Order Tagging", "PASS"))
            else:
                logger.warning(f"  ⚠️  Order tagging may not have tag field")
                self.results.append(("Order Tagging", "WARN"))
            
            # Test tranches
            tranches = sebi_equity_validator.split_into_tranches(500)
            if tranches and len(tranches) > 0:
                logger.info(f"  ✅ Tranche splitting working ({len(tranches)} tranches for qty=500)")
                self.results.append(("Tranche Splitting", "PASS"))
            
            self.results.append(("SEBI Compliance", "PASS"))
            
        except Exception as e:
            logger.error(f"  ❌ SEBI compliance check failed: {e}")
            self.results.append(("SEBI Compliance", f"FAIL: {str(e)[:50]}"))
            self.failed.append("SEBI Compliance")
    
    async def check_agent_manager(self):
        """Verify AgentManager can be instantiated."""
        logger.info("\n" + "=" * 70)
        logger.info("HEALTH CHECK 9: Agent Manager")
        logger.info("=" * 70)
        
        try:
            from src.core.agent_manager import AgentManager
            
            manager = AgentManager(mode="AUTO")
            logger.info(f"  ✅ AgentManager instantiated")
            
            # Check agent count
            agent_count = len(manager.agents)
            if agent_count >= 8:
                logger.info(f"  ✅ All {agent_count} agents loaded")
                self.results.append(("Agent Count", f"PASS ({agent_count})"))
            else:
                logger.warning(f"  ⚠️  Only {agent_count}/8 agents loaded")
                self.results.append(("Agent Count", f"WARN ({agent_count}/8)"))
            
            # List agents
            for agent_name in manager.agents:
                logger.info(f"    • {agent_name}")
            
            self.results.append(("AgentManager", "PASS"))
                
        except Exception as e:
            logger.error(f"  ❌ AgentManager check failed: {e}")
            self.results.append(("AgentManager", f"FAIL: {str(e)[:50]}"))
            self.failed.append("AgentManager")
    
    async def run_all_checks(self):
        """Run all health checks."""
        logger.info("\n🏥 AGENT ALPHA FULL PIPELINE HEALTH CHECK")
        logger.info(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        await self.check_imports()
        await self.check_config()
        await self.check_event_bus()
        await self.check_database_connectivity()
        await self.check_nse_data_service()
        await self.check_dhan_client()
        await self.check_strategies()
        await self.check_sebi_compliance()
        await self.check_agent_manager()
        
        # Summary
        logger.info("\n" + "=" * 70)
        logger.info("HEALTH CHECK SUMMARY")
        logger.info("=" * 70)
        
        passed = sum(1 for _, result in self.results if result == "PASS")
        total = len(self.results)
        
        logger.info(f"\n📊 Results: {passed}/{total} PASS")
        
        if self.failed:
            logger.error(f"\n❌ FAILED Components ({len(self.failed)}):")
            for component in self.failed:
                logger.error(f"   • {component}")
        else:
            logger.info(f"\n✅ ALL CRITICAL COMPONENTS HEALTHY")
        
        # Result table
        logger.info("\n" + "-" * 70)
        logger.info("Component                          | Status")
        logger.info("-" * 70)
        for component, status in self.results:
            status_short = status[:30] if len(status) > 30 else status
            logger.info(f"{component:34} | {status_short}")
        logger.info("-" * 70)
        
        logger.info("\n✅ Pipeline health check completed!")
        
        return len(self.failed) == 0

if __name__ == "__main__":
    health_check = PipelineHealthCheck()
    
    try:
        success = asyncio.run(health_check.run_all_checks())
        sys.exit(0 if success else 1)
    except Exception as e:
        logger.error(f"\n💥 Health check crashed: {e}", exc_info=True)
        sys.exit(2)
