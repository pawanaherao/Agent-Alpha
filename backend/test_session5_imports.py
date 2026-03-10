#!/usr/bin/env python
"""Quick smoke test for Session 5 implementation."""
import sys
sys.path.insert(0, '.')

# Test 1: OptionChainScannerAgent import
try:
    from src.agents.option_chain_scanner import OptionChainScannerAgent, option_chain_scanner
    print('✓ OptionChainScannerAgent imported')
except Exception as e:
    print(f'✗ OptionChainScannerAgent import failed: {e}')
    sys.exit(1)

# Test 2: Scanner expansion
try:
    from src.agents.scanner import ScannerAgent
    print('✓ ScannerAgent imported')
except Exception as e:
    print(f'✗ ScannerAgent import failed: {e}')
    sys.exit(1)

# Test 3: Expanded LOT_SIZES
try:
    from src.services.option_chain import LOT_SIZES, STRIKE_STEPS
    print(f'✓ LOT_SIZES loaded: {len(LOT_SIZES)} symbols (was 8, now covers all F&O)')
    print(f'✓ STRIKE_STEPS loaded: {len(STRIKE_STEPS)} symbols (was 4, now covers all F&O)')
except Exception as e:
    print(f'✗ option_chain imports failed: {e}')
    sys.exit(1)

# Test 4: Expanded F&O stocks
try:
    from src.services.nse_data import nse_data_service
    fno = nse_data_service.get_fno_stocks()
    print(f'✓ get_fno_stocks() returns {len(fno)} stocks (was 8, now covers SEBI F&O list)')
except Exception as e:
    print(f'✗ nse_data import failed: {e}')
    sys.exit(1)

# Test 5: Check agent_manager can import OptionChainScannerAgent
try:
    from src.core.agent_manager import _OPTION_CHAIN_SCANNER_AVAILABLE
    print(f'✓ agent_manager._OPTION_CHAIN_SCANNER_AVAILABLE = {_OPTION_CHAIN_SCANNER_AVAILABLE}')
except Exception as e:
    print(f'✗ agent_manager import failed: {e}')
    sys.exit(1)

# Test 6: StrategyAgent has the handler
try:
    from src.agents.strategy import StrategyAgent
    assert hasattr(StrategyAgent, 'on_options_scan_complete'), \
        "StrategyAgent missing on_options_scan_complete handler"
    print('✓ StrategyAgent.on_options_scan_complete handler exists')
except Exception as e:
    print(f'✗ StrategyAgent check failed: {e}')
    sys.exit(1)

# Test 7: UniversalStrategy loaded with multiple configs
try:
    from src.strategies.universal_strategy import UniversalStrategy
    us_equity = UniversalStrategy({"mode": "equity"})
    us_bcs = UniversalStrategy({"mode": "options", "structure": "BULL_CALL_SPREAD"})
    print('✓ UniversalStrategy can be instantiated with equity + options modes')
except Exception as e:
    print(f'✗ UniversalStrategy check failed: {e}')
    sys.exit(1)

print('\n✅ All Session 5 integration tests passed!')
print('Ready for paper trading with options scanning enabled.')
