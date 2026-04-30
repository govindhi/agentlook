from datetime import datetime, timedelta, timezone
import logging
from app.services.clients import get_cloudwatch_client
from app.services import agentcore_control as ctrl
from app.config import settings

logger = logging.getLogger(__name__)

_resolved_ns: str | None = None


def _get_namespace() -> str:
    global _resolved_ns
    if _resolved_ns:
        return _resolved_ns
    client = get_cloudwatch_client()
    for ns in [settings.cw_namespace, "AWS/Bedrock-AgentCore", "Bedrock-AgentCore", "Bedrock-Agentcore", "bedrock-agentcore"]:
        try:
            resp = client.list_metrics(Namespace=ns, MetricName="Invocations")
            if resp.get("Metrics"):
                _resolved_ns = ns
                logger.info("cloudwatch: resolved namespace %s", ns)
                return ns
        except Exception:
            pass
    _resolved_ns = settings.cw_namespace
    return _resolved_ns

RUNTIME_METRICS = [
    ("Invocations", "Sum"),
    ("Throttles", "Sum"),
    ("SystemErrors", "Sum"),
    ("UserErrors", "Sum"),
    ("Latency", "Average"),
    ("Sessions", "Sum"),
    ("CPUUsed-vCPUHours", "Sum"),
    ("MemoryUsed-GBHours", "Sum"),
]

GATEWAY_METRICS = [
    ("Invocations", "Sum"),
    ("Throttles", "Sum"),
    ("SystemErrors", "Sum"),
    ("UserErrors", "Sum"),
    ("Latency", "Average"),
    ("Duration", "Average"),
    ("TargetExecutionTime", "Average"),
]

MEMORY_METRICS = [
    ("Invocations", "Sum"),
    ("Latency", "Average"),
    ("SystemErrors", "Sum"),
    ("UserErrors", "Sum"),
    ("Throttles", "Sum"),
    ("CreationCount", "Sum"),
]


def _build_queries(metrics: list[tuple[str, str]], dimensions: list[dict] | None, prefix: str):
    queries = []
    ns = _get_namespace()
    for i, (name, stat) in enumerate(metrics):
        q = {
            "Id": f"{prefix}_{i}",
            "MetricStat": {
                "Metric": {
                    "Namespace": ns,
                    "MetricName": name,
                },
                "Period": 300,
                "Stat": stat,
            },
        }
        if dimensions:
            q["MetricStat"]["Metric"]["Dimensions"] = dimensions
        queries.append(q)
    return queries


def _fetch(queries, start: datetime, end: datetime, metrics_list):
    client = get_cloudwatch_client()
    resp = client.get_metric_data(
        MetricDataQueries=queries, StartTime=start, EndTime=end
    )
    results = {}
    for i, result in enumerate(resp.get("MetricDataResults", [])):
        name = metrics_list[i][0]
        timestamps = [t.isoformat() for t in result.get("Timestamps", [])]
        values = result.get("Values", [])
        # CloudWatch returns newest first, reverse for chronological
        results[name] = {
            "timestamps": list(reversed(timestamps)),
            "values": list(reversed(values)),
        }
    return results


def _parse_time_range(hours: int):
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=hours)
    return start, end


def get_runtime_metrics(hours: int = 24, resource_arn: str | None = None):
    start, end = _parse_time_range(hours)
    dims = [{"Name": "Resource", "Value": resource_arn}] if resource_arn else None
    queries = _build_queries(RUNTIME_METRICS, dims, "rt")
    return _fetch(queries, start, end, RUNTIME_METRICS)


def get_gateway_metrics(hours: int = 24, resource_arn: str | None = None):
    start, end = _parse_time_range(hours)
    dims = [{"Name": "Resource", "Value": resource_arn}] if resource_arn else None
    queries = _build_queries(GATEWAY_METRICS, dims, "gw")
    return _fetch(queries, start, end, GATEWAY_METRICS)


def get_memory_metrics(hours: int = 24, resource_arn: str | None = None):
    start, end = _parse_time_range(hours)
    dims = [{"Name": "Resource", "Value": resource_arn}] if resource_arn else None
    queries = _build_queries(MEMORY_METRICS, dims, "mem")
    return _fetch(queries, start, end, MEMORY_METRICS)


def _sum_values(values: list[float]) -> float:
    return sum(values)


def _avg_values(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0


def _get_period(hours: int) -> int:
    """Pick a period that keeps datapoints reasonable."""
    if hours <= 6:
        return 300
    if hours <= 48:
        return 3600
    return 86400


def get_agent_leaderboard(hours: int = 24):
    """Fetch per-agent invocation, latency, error, and resource metrics."""
    start, end = _parse_time_range(hours)
    period = _get_period(hours)
    client = get_cloudwatch_client()

    runtimes = ctrl.list_agent_runtimes()
    if not runtimes:
        return []

    # Invocation-level metrics use Resource dimension only
    invocation_metrics = [
        ("Invocations", "Sum"),
        ("Latency", "Average"),
        ("SystemErrors", "Sum"),
        ("UserErrors", "Sum"),
        ("Sessions", "Sum"),
    ]
    # Resource usage metrics require Service + Resource dimensions
    resource_metrics = [
        ("CPUUsed-vCPUHours", "Sum"),
        ("MemoryUsed-GBHours", "Sum"),
    ]

    all_queries = []
    query_map = []  # (agent_index, metric_name, stat)
    ns = _get_namespace()

    for ai, rt in enumerate(runtimes):
        arn = rt.get("agentRuntimeArn", "")
        if not arn:
            continue

        for metric_name, stat in invocation_metrics:
            qid = f"a{ai}_{metric_name.replace('-', '_').lower()}"
            all_queries.append({
                "Id": qid,
                "MetricStat": {
                    "Metric": {
                        "Namespace": ns,
                        "MetricName": metric_name,
                        "Dimensions": [{"Name": "Resource", "Value": arn}],
                    },
                    "Period": period,
                    "Stat": stat,
                },
            })
            query_map.append((ai, metric_name, stat))

        for metric_name, stat in resource_metrics:
            qid = f"a{ai}_{metric_name.replace('-', '_').lower()}"
            all_queries.append({
                "Id": qid,
                "MetricStat": {
                    "Metric": {
                        "Namespace": ns,
                        "MetricName": metric_name,
                        "Dimensions": [
                            {"Name": "Service", "Value": "AgentCore.Runtime"},
                            {"Name": "Resource", "Value": arn},
                        ],
                    },
                    "Period": period,
                    "Stat": stat,
                },
            })
            query_map.append((ai, metric_name, stat))

    # CloudWatch allows max 500 queries per call; batch if needed
    all_results = []
    for batch_start in range(0, len(all_queries), 500):
        batch = all_queries[batch_start:batch_start + 500]
        try:
            resp = client.get_metric_data(
                MetricDataQueries=batch, StartTime=start, EndTime=end
            )
            all_results.extend(resp.get("MetricDataResults", []))
        except Exception:
            all_results.extend([{"Values": []}] * len(batch))

    # Build agent data
    agents_data: dict[int, dict] = {}
    for rt_i, rt in enumerate(runtimes):
        agents_data[rt_i] = {
            "name": rt.get("agentRuntimeName", rt.get("agentRuntimeId", "unknown")),
            "arn": rt.get("agentRuntimeArn", ""),
            "agentRuntimeId": rt.get("agentRuntimeId", ""),
            "status": rt.get("status", "UNKNOWN"),
            "Invocations": 0, "Latency": 0, "SystemErrors": 0,
            "UserErrors": 0, "Sessions": 0,
            "CPUUsed-vCPUHours": 0, "MemoryUsed-GBHours": 0,
        }

    for i, (ai, metric_name, stat) in enumerate(query_map):
        vals = all_results[i].get("Values", []) if i < len(all_results) else []
        if stat == "Sum":
            agents_data[ai][metric_name] = _sum_values(vals)
        else:
            agents_data[ai][metric_name] = _avg_values(vals)

    agents = list(agents_data.values())
    for a in agents:
        a["TotalErrors"] = a.get("SystemErrors", 0) + a.get("UserErrors", 0)

    agents.sort(key=lambda a: a.get("Invocations", 0), reverse=True)
    return agents


def get_token_usage(hours: int = 24):
    """Fetch InputTokenCount and OutputTokenCount from AWS/Bedrock namespace."""
    start, end = _parse_time_range(hours)
    period = _get_period(hours)
    client = get_cloudwatch_client()

    queries = [
        {
            "Id": "input_tokens",
            "MetricStat": {
                "Metric": {
                    "Namespace": "AWS/Bedrock",
                    "MetricName": "InputTokenCount",
                },
                "Period": period,
                "Stat": "Sum",
            },
        },
        {
            "Id": "output_tokens",
            "MetricStat": {
                "Metric": {
                    "Namespace": "AWS/Bedrock",
                    "MetricName": "OutputTokenCount",
                },
                "Period": period,
                "Stat": "Sum",
            },
        },
        {
            "Id": "invocations",
            "MetricStat": {
                "Metric": {
                    "Namespace": "AWS/Bedrock",
                    "MetricName": "Invocations",
                },
                "Period": period,
                "Stat": "Sum",
            },
        },
    ]

    try:
        resp = client.get_metric_data(
            MetricDataQueries=queries, StartTime=start, EndTime=end
        )
    except Exception:
        return {
            "input_tokens": {"timestamps": [], "values": [], "total": 0},
            "output_tokens": {"timestamps": [], "values": [], "total": 0},
            "invocations": {"timestamps": [], "values": [], "total": 0},
        }

    result = {}
    for r in resp.get("MetricDataResults", []):
        timestamps = [t.isoformat() for t in r.get("Timestamps", [])]
        values = r.get("Values", [])
        result[r["Id"]] = {
            "timestamps": list(reversed(timestamps)),
            "values": list(reversed(values)),
            "total": _sum_values(values),
        }

    # Ensure all keys exist
    for key in ("input_tokens", "output_tokens", "invocations"):
        if key not in result:
            result[key] = {"timestamps": [], "values": [], "total": 0}

    return result
