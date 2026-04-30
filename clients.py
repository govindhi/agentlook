import boto3
from functools import lru_cache
from app.config import settings


@lru_cache()
def get_agentcore_control_client():
    return boto3.client("bedrock-agentcore-control", region_name=settings.aws_region)


@lru_cache()
def get_agentcore_data_client():
    return boto3.client("bedrock-agentcore", region_name=settings.aws_region)


@lru_cache()
def get_cloudwatch_client():
    return boto3.client("cloudwatch", region_name=settings.aws_region)


@lru_cache()
def get_logs_client():
    return boto3.client("logs", region_name=settings.aws_region)


@lru_cache()
def get_ce_client():
    return boto3.client("ce", region_name="us-east-1")  # CE is global, always us-east-1
