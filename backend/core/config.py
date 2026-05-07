from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gemini_api_key: str = ""
    gemini_api_keys: str = ""   # key phụ, phân cách bằng dấu phẩy
    gemini_model: str = "gemini-2.5-flash"
    coindesk_api_key: str = ""
    fred_api_key: str = ""
    app_env: str = "development"
    debug: bool = True
    db_url: str = "sqlite+aiosqlite:///./cryptsen.db"

    # Scheduler
    tier1_minutes: int = 30
    tier2_hours: int = 2
    tier3_hours: int = 6
    tier4_hours: int = 12
    macro_refresh_hours: int = 4
    binance_top_coins: int = 100

    # Sentiment model — HF hub id hoặc local path
    # Mặc định: model fine-tuned của project.
    sentiment_model: str = "sotunq/crypto-macro-sentiment"
    sentiment_max_concurrent_inference: int = 1

    # Reddit — anonymous RSS scrape. UA "compatible" bị WAF chặn,
    # phải dùng UA browser thật. KHÔNG set header Accept (cũng bị chặn).
    reddit_user_agent: str = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )


settings = Settings()
