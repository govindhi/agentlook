"""
Aggregated dashboard service — single-pane view for leadership.
Pulls from control plane, CloudWatch metrics, and Cost Explorer.
"""
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone

from app.services.clients import (
    get_cloudwatch_client,
    get_ce_client,
)
from app.services import agentcore_control as ctrl
from app.config import settings

logger = logging.getLogger(__name__)

_resolved_namespace: str | None = None


def _get_namespace() -> str:
    """Auto-detect the correct CloudWatch namespace for AgentCore metrics."""
    global _resolved_namespace
    if _resolved_namespace:
        return _resolved_namespace

    client = get_cloudwatch_client()
    candidates = [settings.cw_namespace, "AWS/Bedrock-AgentCore", "Bedrock-AgentCore", "Bedrock-Agentcore", "bedrock-agentcore"]
    for ns in candidates:
        try:
            resp = client.list_metrics(Namespace=ns, Limit=1)
            if resp.get("Metrics"):
                _resolved_namespace = ns
                logger.info("Resolved AgentCore CloudWatch namespace: %s", ns)
                return ns
        except Exception:
            pass

    _resolved_namespace = settings.cw_namespace
    logger.warning("Could not detect AgentCore namespace, using default: %s", _resolved_namespace)
    return _resolved_namespace


def _safe(fn, default=None):
    """Call fn, return default on any exception."""
    try:
        return fn()
    except Exception as e:
        logger.warning("dashboard: %s failed: %s", fn.__name__ if hasattr(fn, '__name__') else fn, e)
        return default if default is not None else []


def _count_statuses(items):
    c = Counter()
    for item in items:
        c[item.get("status", "UNKNOWN")] += 1
    return dict(c)


def _parse_time_range(hours: int):
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=hours)
    return start, end


def _get_period(hours: int) -> int:
    if hours <= 6:
        return 300
    if hours <= 48:
        return 3600
    return 86400


def _sum(vals):
    return sum(vals)


def _avg(vals):
    return sum(vals) / len(vals) if vals else 0


# ── Resource inventory ──────────────────────────────────────────────

def _get_inventory():
    runtimes = _safe(ctrl.list_agent_runtimes, [])
    gateways = _safe(ctrl.list_gateways, [])
    memories = _safe(ctrl.list_memories, [])
    eval_configs = _safe(ctrl.list_online_evaluation_configs, [])

    endpoints = []
    for rt in runtimes:
        rid = rt.get("agentRuntimeId", "")
        if rid:
            endpoints.extend(_safe(lambda r=rid: ctrl.list_agent_runtime_endpoints(r), []))

    code_interpreters = _safe(ctrl.list_code_interpreters, [])
    browsers = _safe(ctrl.list_browsers, [])

    gateway_targets = []
    for gw in gateways:
        gid = gw.get("gatewayId", "")
        if gid:
            gateway_targets.extend(_safe(lambda g=gid: ctrl.list_gateway_targets(g), []))

    return {
        "runtimes": runtimes,
        "endpoints": endpoints,
        "gateways": gateways,
        "gateway_targets": gateway_targets,
        "memories": memories,
        "eval_configs": eval_configs,
        "code_interpreters": code_interpreters,
        "browsers": browsers,
    }


# ── CloudWatch per-agent metrics ────────────────────────────────────

def _get_agent_metrics(runtimes, hours: int):
    if not runtimes:
        return [], {}

    start, end = _parse_time_range(hours)
    period = _get_period(hours)
    client = get_cloudwatch_client()

    inv_metrics = [
        ("Invocations", "Sum"), ("Latency", "Average"),
        ("SystemErrors", "Sum"), ("UserErrors", "Sum"),
        ("Sessions", "Sum"), ("Throttles", "Sum"),
    ]
    res_metrics = [
        ("CPUUsed-vCPUHours", "Sum"), ("MemoryUsed-GBHours", "Sum"),
    ]

    all_queries, query_map = [], []

    for ai, rt in enumerate(runtimes):
        arn = rt.get("agentRuntimeArn", "")
        rt_name = rt.get("agentRuntimeName", "")
        if not arn:
            continue

        # Runtime invocation metrics need (Resource, Operation, Name) dimensions
        endpoint_name = f"{rt_name}::DEFAULT"
        inv_dims = [
            {"Name": "Resource", "Value": arn},
            {"Name": "Operation", "Value": "InvokeAgentRuntime"},
            {"Name": "Name", "Value": endpoint_name},
        ]

        for mn, st in inv_metrics:
            qid = f"a{ai}_{mn.replace('-','_').lower()}"
            all_queries.append({
                "Id": qid,
                "MetricStat": {
                    "Metric": {"Namespace": _get_namespace(), "MetricName": mn,
                               "Dimensions": inv_dims},
                    "Period": period, "Stat": st,
                },
            })
            query_map.append((ai, mn, st))
        for mn, st in res_metrics:
            qid = f"a{ai}_{mn.replace('-','_').lower()}"
            all_queries.append({
                "Id": qid,
                "MetricStat": {
                    "Metric": {"Namespace": _get_namespace(), "MetricName": mn,
                               "Dimensions": [
                                   {"Name": "Service", "Value": "AgentCore.Runtime"},
                                   {"Name": "Resource", "Value": arn},
                               ]},
                    "Period": period, "Stat": st,
                },
            })
            query_map.append((ai, mn, st))

    all_results = []
    for bs in range(0, len(all_queries), 500):
        batch = all_queries[bs:bs+500]
        try:
            resp = client.get_metric_data(MetricDataQueries=batch, StartTime=start, EndTime=end)
            all_results.extend(resp.get("MetricDataResults", []))
        except Exception:
            all_results.extend([{"Values": []}] * len(batch))

    agents = {}
    for ri, rt in enumerate(runtimes):
        agents[ri] = {
            "name": rt.get("agentRuntimeName", rt.get("agentRuntimeId", "unknown")),
            "arn": rt.get("agentRuntimeArn", ""),
            "agentRuntimeId": rt.get("agentRuntimeId", ""),
            "status": rt.get("status", "UNKNOWN"),
            "Invocations": 0, "Latency": 0, "SystemErrors": 0,
            "UserErrors": 0, "Sessions": 0, "Throttles": 0,
            "CPUUsed-vCPUHours": 0, "MemoryUsed-GBHours": 0,
        }

    for i, (ai, mn, st) in enumerate(query_map):
        vals = all_results[i].get("Values", []) if i < len(all_results) else []
        agents[ai][mn] = _sum(vals) if st == "Sum" else _avg(vals)

    agent_list = list(agents.values())
    for a in agent_list:
        a["TotalErrors"] = a.get("SystemErrors", 0) + a.get("UserErrors", 0)
        inv = a.get("Invocations", 0)
        a["ErrorRate"] = round((a["TotalErrors"] / inv * 100), 1) if inv > 0 else 0

    agent_list.sort(key=lambda a: a.get("Invocations", 0), reverse=True)

    # Also get aggregate invocation timeline (no dimension = account-wide)
    timeline = _get_invocation_timeline(hours)

    return agent_list, timeline


def _get_invocation_timeline(hours: int):
    """Account-wide invocation + error timeline."""
    start, end = _parse_time_range(hours)
    period = _get_period(hours)
    client = get_cloudwatch_client()

    ns = _get_namespace()
    queries = [
        {"Id": "inv", "MetricStat": {"Metric": {"Namespace": ns, "MetricName": "Invocations"}, "Period": period, "Stat": "Sum"}},
        {"Id": "err", "MetricStat": {"Metric": {"Namespace": ns, "MetricName": "SystemErrors"}, "Period": period, "Stat": "Sum"}},
        {"Id": "uerr", "MetricStat": {"Metric": {"Namespace": ns, "MetricName": "UserErrors"}, "Period": period, "Stat": "Sum"}},
        {"Id": "lat", "MetricStat": {"Metric": {"Namespace": ns, "MetricName": "Latency"}, "Period": period, "Stat": "Average"}},
        {"Id": "sess", "MetricStat": {"Metric": {"Namespace": ns, "MetricName": "Sessions"}, "Period": period, "Stat": "Sum"}},
        {"Id": "thr", "MetricStat": {"Metric": {"Namespace": ns, "MetricName": "Throttles"}, "Period": period, "Stat": "Sum"}},
    ]
    try:
        resp = client.get_metric_data(MetricDataQueries=queries, StartTime=start, EndTime=end)
    except Exception:
        return {}

    result = {}
    for r in resp.get("MetricDataResults", []):
        ts = [t.isoformat() for t in r.get("Timestamps", [])]
        vals = r.get("Values", [])
        result[r["Id"]] = {"timestamps": list(reversed(ts)), "values": list(reversed(vals)), "total": _sum(vals)}
    return result


# ── Token usage from AWS/Bedrock ────────────────────────────────────

def _get_token_metrics(hours: int):
    start, end = _parse_time_range(hours)
    period = _get_period(hours)
    client = get_cloudwatch_client()

    queries = [
        {"Id": "input_tokens", "MetricStat": {"Metric": {"Namespace": "AWS/Bedrock", "MetricName": "InputTokenCount"}, "Period": period, "Stat": "Sum"}},
        {"Id": "output_tokens", "MetricStat": {"Metric": {"Namespace": "AWS/Bedrock", "MetricName": "OutputTokenCount"}, "Period": period, "Stat": "Sum"}},
        {"Id": "bedrock_inv", "MetricStat": {"Metric": {"Namespace": "AWS/Bedrock", "MetricName": "Invocations"}, "Period": period, "Stat": "Sum"}},
        {"Id": "bedrock_lat", "MetricStat": {"Metric": {"Namespace": "AWS/Bedrock", "MetricName": "InvocationLatency"}, "Period": period, "Stat": "Average"}},
        {"Id": "ttft", "MetricStat": {"Metric": {"Namespace": "AWS/Bedrock", "MetricName": "TimeToFirstToken"}, "Period": period, "Stat": "Average"}},
        {"Id": "ttft_p90", "MetricStat": {"Metric": {"Namespace": "AWS/Bedrock", "MetricName": "TimeToFirstToken"}, "Period": period, "Stat": "p90"}},
    ]
    try:
        resp = client.get_metric_data(MetricDataQueries=queries, StartTime=start, EndTime=end)
    except Exception:
        return {k: {"timestamps": [], "values": [], "total": 0} for k in ("input_tokens", "output_tokens", "bedrock_inv", "bedrock_lat", "ttft", "ttft_p90")}

    result = {}
    for r in resp.get("MetricDataResults", []):
        ts = [t.isoformat() for t in r.get("Timestamps", [])]
        vals = r.get("Values", [])
        result[r["Id"]] = {"timestamps": list(reversed(ts)), "values": list(reversed(vals)), "total": _sum(vals)}

    for k in ("input_tokens", "output_tokens", "bedrock_inv", "bedrock_lat", "ttft", "ttft_p90"):
        if k not in result:
            result[k] = {"timestamps": [], "values": [], "total": 0}
    return result


# ── Per-model latency timelines from AWS/Bedrock ────────────────────

def _get_per_model_latency_timelines(hours: int):
    """Fetch per-model TTFT and InvocationLatency timelines."""
    start, end = _parse_time_range(hours)
    period = _get_period(hours)
    client = get_cloudwatch_client()

    model_ids = set()
    try:
        paginator = client.get_paginator("list_metrics")
        for page in paginator.paginate(Namespace="AWS/Bedrock", MetricName="Invocations"):
            for m in page.get("Metrics", []):
                for d in m.get("Dimensions", []):
                    if d["Name"] == "ModelId":
                        model_ids.add(d["Value"])
    except Exception:
        return {}

    if not model_ids:
        return {}

    queries = []
    query_map = []

    for mi, model_id in enumerate(sorted(model_ids)):
        short = model_id.split("/")[-1] if "/" in model_id else model_id
        for prefix in ("us.", "global.", "eu.", "ap."):
            if short.startswith(prefix):
                short = short[len(prefix):]
                break

        queries.append({
            "Id": f"ttft_{mi}",
            "MetricStat": {
                "Metric": {"Namespace": "AWS/Bedrock", "MetricName": "TimeToFirstToken",
                           "Dimensions": [{"Name": "ModelId", "Value": model_id}]},
                "Period": period, "Stat": "Average",
            },
        })
        query_map.append((short, "ttft"))

        queries.append({
            "Id": f"lat_{mi}",
            "MetricStat": {
                "Metric": {"Namespace": "AWS/Bedrock", "MetricName": "InvocationLatency",
                           "Dimensions": [{"Name": "ModelId", "Value": model_id}]},
                "Period": period, "Stat": "Average",
            },
        })
        query_map.append((short, "latency"))

    try:
        resp = client.get_metric_data(MetricDataQueries=queries, StartTime=start, EndTime=end)
    except Exception:
        return {}

    result: dict[str, dict] = {}
    for i, r in enumerate(resp.get("MetricDataResults", [])):
        model_name, metric_key = query_map[i]
        ts = [t.isoformat() for t in r.get("Timestamps", [])]
        vals = r.get("Values", [])
        if model_name not in result:
            result[model_name] = {}
        result[model_name][metric_key] = {
            "timestamps": list(reversed(ts)),
            "values": list(reversed(vals)),
        }

    return result


# ── Per-model metrics from AWS/Bedrock ──────────────────────────────

def _get_per_model_metrics(hours: int):
    """Fetch per-model invocations, tokens, latency, TTFT from AWS/Bedrock."""
    start, end = _parse_time_range(hours)
    period = _get_period(hours)
    client = get_cloudwatch_client()

    # First discover which models have metrics
    model_ids = set()
    try:
        paginator = client.get_paginator("list_metrics")
        for page in paginator.paginate(Namespace="AWS/Bedrock", MetricName="Invocations"):
            for m in page.get("Metrics", []):
                for d in m.get("Dimensions", []):
                    if d["Name"] == "ModelId":
                        model_ids.add(d["Value"])
    except Exception:
        return []

    if not model_ids:
        return []

    metrics_to_fetch = [
        ("Invocations", "Sum"),
        ("InputTokenCount", "Sum"),
        ("OutputTokenCount", "Sum"),
        ("InvocationLatency", "Average"),
        ("TimeToFirstToken", "Average"),
        ("InvocationClientErrors", "Sum"),
        ("InvocationServerErrors", "Sum"),
    ]

    all_queries = []
    query_map = []  # (model_id, metric_name, stat)

    for mi, model_id in enumerate(sorted(model_ids)):
        for mn, st in metrics_to_fetch:
            qid = f"m{mi}_{mn.lower()}"
            all_queries.append({
                "Id": qid,
                "MetricStat": {
                    "Metric": {
                        "Namespace": "AWS/Bedrock",
                        "MetricName": mn,
                        "Dimensions": [{"Name": "ModelId", "Value": model_id}],
                    },
                    "Period": period,
                    "Stat": st,
                },
            })
            query_map.append((model_id, mn, st))

    all_results = []
    for bs in range(0, len(all_queries), 500):
        batch = all_queries[bs:bs + 500]
        try:
            resp = client.get_metric_data(MetricDataQueries=batch, StartTime=start, EndTime=end)
            all_results.extend(resp.get("MetricDataResults", []))
        except Exception:
            all_results.extend([{"Values": []}] * len(batch))

    models: dict[str, dict] = {}
    for model_id in model_ids:
        short_name = model_id.split("/")[-1] if "/" in model_id else model_id
        # Trim region prefix like "us." or "global."
        for prefix in ("us.", "global.", "eu.", "ap."):
            if short_name.startswith(prefix):
                short_name = short_name[len(prefix):]
                break
        models[model_id] = {
            "modelId": model_id,
            "name": short_name,
            "Invocations": 0, "InputTokenCount": 0, "OutputTokenCount": 0,
            "InvocationLatency": 0, "TimeToFirstToken": 0,
            "InvocationClientErrors": 0, "InvocationServerErrors": 0,
        }

    for i, (model_id, mn, st) in enumerate(query_map):
        vals = all_results[i].get("Values", []) if i < len(all_results) else []
        models[model_id][mn] = _sum(vals) if st == "Sum" else _avg(vals)

    model_list = list(models.values())
    for m in model_list:
        m["TotalTokens"] = m["InputTokenCount"] + m["OutputTokenCount"]
        m["TotalErrors"] = m["InvocationClientErrors"] + m["InvocationServerErrors"]
        m["InvocationLatency"] = round(m["InvocationLatency"], 1)
        m["TimeToFirstToken"] = round(m["TimeToFirstToken"], 1)

    model_list.sort(key=lambda x: x.get("Invocations", 0), reverse=True)
    return model_list


# ── Per-agent token usage from OTEL spans ───────────────────────────

def _get_per_agent_tokens(hours: int) -> dict:
    """Query OTEL spans for actual per-agent token usage.
    Returns {agent_id: {input_tokens, output_tokens, avg_latency}}.
    Falls back to empty dict if spans log group doesn't exist.
    """
    from botocore.exceptions import ClientError
    from app.services.clients import get_logs_client

    client = get_logs_client()
    start, end = _parse_time_range(hours)

    query = """fields attributes.`aws.agent.id` as agent_id,
       attributes.`gen_ai.usage.input_tokens` as in_tok,
       attributes.`gen_ai.usage.output_tokens` as out_tok,
       attributes.`latency_ms` as lat
| filter ispresent(agent_id)
| stats sum(in_tok) as input_tokens,
        sum(out_tok) as output_tokens,
        avg(lat) as avg_latency
  by agent_id"""

    try:
        resp = client.start_query(
            logGroupName=settings.spans_log_group,
            startTime=int(start.timestamp()),
            endTime=int(end.timestamp()),
            queryString=query,
            limit=200,
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            logger.info("Spans log group not found — skipping per-agent token query")
            return {}
        raise
    except Exception as e:
        logger.warning("Per-agent token query failed: %s", e)
        return {}

    import time
    query_id = resp["queryId"]
    for _ in range(30):
        result = client.get_query_results(queryId=query_id)
        if result["status"] in ("Complete", "Failed", "Cancelled"):
            break
        time.sleep(0.5)

    agents = {}
    for entry in result.get("results", []):
        row = {f["field"]: f["value"] for f in entry}
        aid = row.get("agent_id", "")
        if aid:
            agents[aid] = {
                "input_tokens": int(float(row.get("input_tokens", 0))),
                "output_tokens": int(float(row.get("output_tokens", 0))),
                "avg_latency": round(float(row.get("avg_latency", 0)), 1),
            }
    return agents


# ── Cost from Cost Explorer ─────────────────────────────────────────

def _get_cost(days: int = 30):
    """Get Bedrock + AgentCore cost from Cost Explorer, with service breakdown."""
    ce = get_ce_client()
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=days)

    # Daily cost by service
    daily = []
    total = 0.0
    by_service: dict[str, float] = {}

    try:
        resp = ce.get_cost_and_usage(
            TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
            Granularity="DAILY",
            Metrics=["UnblendedCost"],
            Filter={
                "Dimensions": {
                    "Key": "SERVICE",
                    "Values": ["Amazon Bedrock", "Amazon Bedrock Service", "Amazon Bedrock AgentCore"],
                }
            },
            GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
        )
        for period in resp.get("ResultsByTime", []):
            day_total = 0.0
            day_bedrock = 0.0
            day_agentcore = 0.0
            for group in period.get("Groups", []):
                svc = group["Keys"][0]
                amount = float(group["Metrics"]["UnblendedCost"]["Amount"])
                by_service[svc] = by_service.get(svc, 0) + amount
                if "AgentCore" in svc:
                    day_agentcore += amount
                else:
                    day_bedrock += amount
                day_total += amount
            daily.append({
                "date": period["TimePeriod"]["Start"],
                "total": round(day_total, 4),
                "bedrock": round(day_bedrock, 4),
                "agentcore": round(day_agentcore, 4),
            })
            total += day_total
    except Exception as e:
        logger.warning("Cost Explorer failed: %s", e)
        return {"daily": [], "total": 0, "by_service": {}, "error": str(e)}

    # Consolidate service names for display
    consolidated: dict[str, float] = {}
    for svc, amt in by_service.items():
        if "AgentCore" in svc:
            key = "AgentCore Runtime"
        else:
            key = "Bedrock Models"
        consolidated[key] = consolidated.get(key, 0) + amt

    logger.info("Cost data: %d days, total=$%.4f, services=%s", len(daily), total, consolidated)

    return {
        "daily": daily,
        "total": round(total, 2),
        "by_service": {k: round(v, 4) for k, v in consolidated.items()},
        "currency": "USD",
    }


def _get_agentcore_cost_breakdown(days: int = 30):
    """Get AgentCore cost broken down by category (Runtime, Memory, Gateway, etc.)."""
    ce = get_ce_client()
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=days)

    category_map = {
        "Runtime": ["Runtime:Consumption-based:vCPU", "Runtime:Consumption-based:Memory"],
        "Memory": ["Memory:Consumption-based:Short-Term-Memory", "Memory:Consumption-based:Long-Term-Memory-Storage", "Memory:Consumption-based:Long-Term-Memory-Retrieval"],
        "Evaluations": ["Evaluations:Consumption-based"],
        "Gateway": ["Gateway:Consumption-based"],
        "Policy": ["Policy:Consumption-based"],
    }

    try:
        resp = ce.get_cost_and_usage(
            TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
            Granularity="DAILY",
            Metrics=["UnblendedCost"],
            Filter={"Dimensions": {"Key": "SERVICE", "Values": ["Amazon Bedrock AgentCore"]}},
            GroupBy=[{"Type": "DIMENSION", "Key": "USAGE_TYPE"}],
        )
    except Exception as e:
        logger.warning("AgentCore cost breakdown failed: %s", e)
        return {"categories": {}, "daily": []}

    # Aggregate by category
    categories: dict[str, float] = {}
    daily: list[dict] = []

    for period in resp.get("ResultsByTime", []):
        day_data: dict[str, float | str] = {"date": period["TimePeriod"]["Start"]}
        for cat in category_map:
            day_data[cat] = 0.0

        for group in period.get("Groups", []):
            ut = group["Keys"][0]
            amount = float(group["Metrics"]["UnblendedCost"]["Amount"])

            matched = False
            for cat, patterns in category_map.items():
                if any(p in ut for p in patterns):
                    categories[cat] = categories.get(cat, 0) + amount
                    day_data[cat] = float(day_data[cat]) + amount
                    matched = True
                    break
            if not matched and amount > 0.0001:
                categories["Other"] = categories.get("Other", 0) + amount
                day_data["Other"] = float(day_data.get("Other", 0)) + amount

        # Round daily values
        for k in day_data:
            if k != "date":
                day_data[k] = round(float(day_data[k]), 6)
        daily.append(day_data)

    return {
        "categories": {k: round(v, 4) for k, v in sorted(categories.items(), key=lambda x: -x[1])},
        "daily": daily,
    }


# ── Main aggregator ─────────────────────────────────────────────────

def get_dashboard(hours: int = 24):
    """Single aggregated response for the executive dashboard."""
    inv = _get_inventory()
    runtimes = inv["runtimes"]

    agent_list, timeline = _get_agent_metrics(runtimes, hours)
    tokens = _get_token_metrics(hours)
    models = _get_per_model_metrics(hours)
    model_latency_timelines = _get_per_model_latency_timelines(hours)

    # Cost data is daily — always fetch at least 7 days for meaningful charts
    cost_days = max(hours // 24, 7)
    cost = _get_cost(cost_days)
    agentcore_breakdown = _get_agentcore_cost_breakdown(cost_days)

    # Resource summary
    resource_counts = {
        "runtimes": len(inv["runtimes"]),
        "endpoints": len(inv["endpoints"]),
        "gateways": len(inv["gateways"]),
        "gateway_targets": len(inv["gateway_targets"]),
        "memories": len(inv["memories"]),
        "eval_configs": len(inv["eval_configs"]),
        "code_interpreters": len(inv["code_interpreters"]),
        "browsers": len(inv["browsers"]),
    }

    # Status distribution across all runtimes
    runtime_statuses = _count_statuses(inv["runtimes"])
    endpoint_statuses = _count_statuses(inv["endpoints"])
    gateway_statuses = _count_statuses(inv["gateways"])

    # Aggregate totals — prefer AgentCore metrics, fall back to AWS/Bedrock
    total_invocations = sum(a.get("Invocations", 0) for a in agent_list)
    total_sessions = sum(a.get("Sessions", 0) for a in agent_list)
    total_errors = sum(a.get("TotalErrors", 0) for a in agent_list)
    total_throttles = sum(a.get("Throttles", 0) for a in agent_list)
    avg_latency = _avg([a.get("Latency", 0) for a in agent_list if a.get("Invocations", 0) > 0])
    total_cpu = sum(a.get("CPUUsed-vCPUHours", 0) for a in agent_list)
    total_mem = sum(a.get("MemoryUsed-GBHours", 0) for a in agent_list)
    has_agentcore_metrics = total_invocations > 0

    # If no AgentCore metrics, use AWS/Bedrock model-level totals
    if not has_agentcore_metrics and models:
        total_invocations = sum(m.get("Invocations", 0) for m in models)
        total_errors = sum(m.get("TotalErrors", 0) for m in models)
        avg_latency = _avg([m.get("InvocationLatency", 0) for m in models if m.get("Invocations", 0) > 0])

    error_rate = round((total_errors / total_invocations * 100), 1) if total_invocations > 0 else 0

    # Per-agent cost: calculate from actual CPU/Memory usage at published rates
    # AgentCore pricing: $0.0895/vCPU-hour, $0.00945/GB-hour
    VCPU_RATE = 0.0895
    GBHR_RATE = 0.00945

    # Try to get actual per-agent token usage from OTEL spans
    agent_tokens = _get_per_agent_tokens(hours)

    for a in agent_list:
        agent_id = a.get("agentRuntimeId", "")

        # Actual tokens from spans (if available)
        at = agent_tokens.get(agent_id, {})
        a["InputTokens"] = at.get("input_tokens", 0)
        a["OutputTokens"] = at.get("output_tokens", 0)
        a["TotalTokens"] = a["InputTokens"] + a["OutputTokens"]
        a["AvgLatencySpan"] = at.get("avg_latency", 0)

        # Compute cost from actual CPU/Memory usage at published rates
        cpu_hours = a.get("CPUUsed-vCPUHours", 0)
        mem_hours = a.get("MemoryUsed-GBHours", 0)
        a["ComputeCost"] = round(cpu_hours * VCPU_RATE + mem_hours * GBHR_RATE, 4)
        a["CpuCost"] = round(cpu_hours * VCPU_RATE, 4)
        a["MemCost"] = round(mem_hours * GBHR_RATE, 4)
        a["EstimatedCost"] = a["ComputeCost"]

    has_span_tokens = any(a.get("TotalTokens", 0) > 0 for a in agent_list)

    return {
        "summary": {
            "total_invocations": total_invocations,
            "total_sessions": total_sessions,
            "total_errors": total_errors,
            "total_throttles": total_throttles,
            "avg_latency_ms": round(avg_latency, 1),
            "error_rate_pct": error_rate,
            "total_cpu_vcpu_hours": round(total_cpu, 4),
            "total_mem_gb_hours": round(total_mem, 4),
            "input_tokens": tokens["input_tokens"]["total"],
            "output_tokens": tokens["output_tokens"]["total"],
            "total_tokens": tokens["input_tokens"]["total"] + tokens["output_tokens"]["total"],
            "bedrock_invocations": tokens["bedrock_inv"]["total"],
            "avg_model_latency_ms": round(_avg(tokens["bedrock_lat"]["values"]), 1),
            "avg_ttft_ms": round(_avg(tokens["ttft"]["values"]), 1),
            "p90_ttft_ms": round(_avg(tokens["ttft_p90"]["values"]), 1),
            "cost_total_usd": cost.get("total", 0),
            "cost_by_service": cost.get("by_service", {}),
        },
        "resource_counts": resource_counts,
        "status_distribution": {
            "runtimes": runtime_statuses,
            "endpoints": endpoint_statuses,
            "gateways": gateway_statuses,
        },
        "agents": agent_list,
        "models": models,
        "model_latency": model_latency_timelines,
        "has_agentcore_metrics": has_agentcore_metrics,
        "has_span_tokens": has_span_tokens,
        "eval_configs": inv["eval_configs"],
        "timeline": timeline,
        "tokens": tokens,
        "cost": cost,
        "agentcore_breakdown": agentcore_breakdown,
    }
