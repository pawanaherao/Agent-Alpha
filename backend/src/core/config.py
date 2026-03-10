from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "Agentic Alpha 2026"
    MODE: str = "LOCAL"  # LOCAL, PROD
    PAPER_TRADING: bool = True  # Safety guard: when True, forces simulated orders even if broker credentials are set

    # GCP Config
    GCP_PROJECT: str = "agentic-alpha-local"
    
    # Database Config
    POSTGRES_USER: str = "user"
    POSTGRES_PASSWORD: str = "password"
    POSTGRES_DB: str = "agentic_alpha"
    POSTGRES_HOST: str = "localhost"
    FIRESTORE_PROJECT_ID: str = "agentic-alpha-local"
    
    # Redis Config
    REDIS_HOST: str = "localhost"
    
    # Trading Universe
    TRADING_UNIVERSE: list = ["NIFTY 50", "BANKNIFTY", "RELIANCE", "HDFCBANK", "INFY", "TCS", "SBIN"]

    # Options Module
    OPTIONS_ENABLED: bool = True
    OPTIONS_DEFAULT_EXPIRY: str = "WEEKLY"          # WEEKLY | MONTHLY
    OPTIONS_MAX_OPEN_STRUCTURES: int = 10
    OPTIONS_MONITOR_INTERVAL_MIN: int = 3             # leg monitor frequency
    OPTIONS_MAX_LOSS_PCT: float = 2.0                 # per-structure max loss %
    OPTIONS_PROFIT_TARGET_PCT: float = 50.0            # take-profit at 50 %
    OPTIONS_DELTA_BREACH: float = 0.30
    OPTIONS_GAMMA_RISK: float = 0.05
    OPTIONS_DTE_AUTO_CLOSE: int = 0                    # auto-close on expiry day
    OPTIONS_TIME_EXIT: str = "15:10"                  # force-close by this IST time

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
