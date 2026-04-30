import re
import time
import logging
from datetime import datetime, timedelta, timezone
from botocore.exceptions import ClientError
from app.services.clients import get_logs_client
from app.config import settings

logger = logging.getLogger(__name__)

# Strict pattern for IDs: alphanumeric, hyphens, underscores, colons, dots
_SAFE_ID = re.compile(r"^[a-zA-Z0-9._:/-]{1,256}$")


class LogGroupNotFoundError(Exception):
    """Raised when the configured spans log group does not exist."""
    pass


def _sanitize_id(value: str, field_name: str) -> str:
    """Validate and sanitize an ID value for use in CloudWatch Logs Insights queries."""
    if not _SAFE_ID.match(value):
        raise ValueError(f"Invalid {field_name}: contains disallowed characters")
    # Escape double quotes and backslashes
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _run_query(query: str, start: datetime, end: datetime, limit: int = 100):
    client = get_logs_client()
    try:
        resp = client.start_query(
            logGroupName=settings.spans_log_group,
            startTime=int(start.timestamp()),
            endTime=int(end.timestamp()),
            queryString=query,
            limit=limit,
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            raise LogGroupNotFoundError(
                f"Log group '{settings.spans_log_group}' does not exist"
            )
        raise
    query_id = resp["queryId"]
    while True:
        result = client.get_query_results(queryId=query_id)
        if result["status"] in ("Complete", "Failed", "Cancelled"):
            break
        time.sleep(0.5)
    rows = []
    for entry in result.get("results", []):
        row = {field["field"]: field["value"] for field in entry}
        rows.append(row)
    return rows


def search_traces(
    hours: int = 24,
    agent_id: str | None = None,
    session_id: str | None = None,
    error_only: bool = False,
):
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=hours)
    filters = []
    if agent_id:
        safe_id = _sanitize_id(agent_id, "agent_id")
        filters.append(f'| filter attributes.`aws.agent.id` = "{safe_id}"')
    if session_id:
        safe_id = _sanitize_id(session_id, "session_id")
        filters.append(f'| filter attributes.`session.id` = "{safe_id}"')
    if error_only:
        filters.append("| filter ispresent(attributes.`error_type`)")
    filter_str = "\n".join(filters)
    query = f"""fields @timestamp, traceId, spanId, parentSpanId, name,
       attributes.`aws.operation.name` as operation,
       attributes.`aws.agent.id` as agent_id,
       attributes.`session.id` as session_id,
       attributes.`latency_ms` as latency_ms,
       attributes.`error_type` as error_type,
       attributes.`aws.resource.arn` as resource_arn,
       duration
{filter_str}
| sort @timestamp desc"""
    return _run_query(query, start, end)


def get_trace(trace_id: str, hours: int = 72):
    safe_id = _sanitize_id(trace_id, "trace_id")
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=hours)
    query = f"""fields @timestamp, traceId, spanId, parentSpanId, name, kind, duration,
       attributes.`aws.operation.name` as operation,
       attributes.`aws.agent.id` as agent_id,
       attributes.`session.id` as session_id,
       attributes.`latency_ms` as latency_ms,
       attributes.`error_type` as error_type,
       attributes.`aws.resource.arn` as resource_arn,
       attributes.`tool.name` as tool_name
| filter traceId = "{safe_id}"
| sort @timestamp asc"""
    spans = _run_query(query, start, end, limit=500)
    span_map = {s.get("spanId", ""): {**s, "children": []} for s in spans}
    roots = []
    for s in span_map.values():
        parent = s.get("parentSpanId")
        if parent and parent in span_map:
            span_map[parent]["children"].append(s)
        else:
            roots.append(s)
    return {"traceId": trace_id, "spans": roots}
