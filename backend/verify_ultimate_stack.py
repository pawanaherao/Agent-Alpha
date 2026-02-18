import sys
import importlib
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("VERIFIER")

def verify_module(name):
    try:
        module = importlib.import_module(name)
        version = getattr(module, '__version__', 'unknown')
        logger.info(f"✅ {name:25} | Version: {version}")
        return True
    except ImportError:
        logger.error(f"❌ {name:25} | FAILED TO IMPORT")
        return False

# Categories of "World's Best" Algo Stack
COLLECTIONS = {
    "CORE_ENGINE": ["numpy", "pandas", "numba", "scipy", "polars", "bottleneck", "numexpr"],
    "MARKET_DATA": ["dhanhq", "nselib", "nsepython", "yfinance", "nsepy"],
    "TECHNICAL_ANALYSIS": ["pandas_ta", "ta", "tapy"],
    "AUTOMATION": ["selenium", "urllib3", "requests", "aiohttp", "websockets", "websocket"],
    "EXCEL_REPORTING": ["xlwings", "xlsxwriter", "openpyxl", "xlrd"],
    "LOGGING_MONITORING": ["loguru", "structlog"],
    "BACKTESTING_SUITE": ["vectorbt", "backtesting", "nautilus_trader", "backtrader", "bt"]
}

print(f"\n=== Python {sys.version.split()[0]} Environment Verification ===\n")

results = {}
for category, modules in COLLECTIONS.items():
    print(f"--- {category} ---")
    for mod in modules:
        results[mod] = verify_module(mod)
    print()

# Special check for TA-Lib
print("--- SPECIAL CHECKS ---")
try:
    import talib
    print(f"✅ {'TA-Lib':25} | Version: {talib.__version__}")
except ImportError:
    print(f"⚠️ {'TA-Lib':25} | NOT INSTALLED (Standard on Windows, requires manual binary)")

print("\n=== Verification Complete ===\n")
