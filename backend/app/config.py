from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    aws_region: str = "us-east-1"
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]  # Override for production
    cache_ttl_seconds: int = 60
    cw_namespace: str = "AWS/Bedrock-AgentCore"
    spans_log_group: str = "/aws/spans/default"
    debug_endpoints: bool = False

    class Config:
        env_prefix = "AGENTLOOK_"


settings = Settings()
