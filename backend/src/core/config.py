from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "Agentic Alpha 2026"
    MODE: str = "LOCAL"  # LOCAL, PROD
    
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
    
    class Config:
        env_file = ".env"

settings = Settings()
