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
            resp = client.list_metrics(Namespace=ns, MetricName="Invocations")
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

    # Enrich each runtime with protocol info from the detail API.
    # protocolConfiguration.serverProtocol is only present on the detail response.
    # HTTP is the default when the field is absent.
    for rt in runtimes:
        rid = rt.get("agentRuntimeId", "")
        if rid:
            detail = _safe(lambda r=rid: ctrl.get_agent_runtime(r), {})
            proto_cfg = detail.get("protocolConfiguration", {})
            rt["serverProtocol"] = proto_cfg.get("serverProtocol", "HTTP")

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
    ns = _get_namespace()

    inv_metrics = [
        ("Invocations", "Sum"),
        ("SystemErrors", "Sum"), ("UserErrors", "Sum"),
        ("Sessions", "Sum"), ("Throttles", "Sum"),
    ]
    res_metrics = [
        ("CPUUsed-vCPUHours", "Sum"), ("MemoryUsed-GBHours", "Sum"),
    ]

    # First, discover the actual dimension values for each runtime's Invocations metric.
    # The console uses (Resource, Operation, Name) but the Name value varies per endpoint.
    # We query CloudWatch list_metrics to find the exact dimension sets.
    arn_to_dims: dict[str, list[dict]] = {}
    for rt in runtimes:
        arn = rt.get("agentRuntimeArn", "")
        if not arn:
            continue
        try:
            resp = client.list_metrics(
                Namespace=ns,
                MetricName="Invocations",
                Dimensions=[{"Name": "Resource", "Value": arn}],
            )
            for m in resp.get("Metrics", []):
                dims = m.get("Dimensions", [])
                if dims:
                    arn_to_dims[arn] = dims
                    break
        except Exception:
            pass

    all_queries, query_map = [], []

    for ai, rt in enumerate(runtimes):
        arn = rt.get("agentRuntimeArn", "")
        rt_name = rt.get("agentRuntimeName", "")
        if not arn:
            continue

        # Use discovered dimensions if available, otherwise fall back to the
        # standard (Resource, Operation, Name) pattern.
        inv_dims = arn_to_dims.get(arn)
        if not inv_dims:
            endpoint_name = f"{rt_name}::DEFAULT"
            inv_dims = [
                {"Name": "Resource", "Value": arn},
                {"Name": "Operation", "Value": "InvokeAgentRuntime"},
                {"Name": "Name", "Value": endpoint_name},
            ]

        for mn, st in inv_metrics:
            qid = f"a{ai}_{mn.replace('-','_').lower()}_{st.lower()}"
            all_queries.append({
                "Id": qid,
                "MetricStat": {
                    "Metric": {"Namespace": ns, "MetricName": mn,
                               "Dimensions": inv_dims},
                    "Period": period, "Stat": st,
                },
            })
            query_map.append((ai, mn, st))
        # Query Latency with a single period spanning the entire time range.
        # This lets CloudWatch compute the true average across all datapoints
        # instead of us averaging daily averages (which is mathematically wrong).
        full_period = int((end - start).total_seconds())
        qid = f"a{ai}_latency_average"
        all_queries.append({
            "Id": qid,
            "MetricStat": {
                "Metric": {"Namespace": ns, "MetricName": "Latency",
                           "Dimensions": inv_dims},
                "Period": full_period, "Stat": "Average",
            },
        })
        query_map.append((ai, "Latency", "Average"))
        for mn, st in res_metrics:
            qid = f"a{ai}_{mn.replace('-','_').lower()}"
            all_queries.append({
                "Id": qid,
                "MetricStat": {
                    "Metric": {"Namespace": ns, "MetricName": mn,
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
        if st == "Sum":
            agents[ai][mn] = _sum(vals)
        else:
            # For Average with a single full-range period, there's only one value
            agents[ai][mn] = vals[0] if vals else 0

    agent_list = list(agents.values())
    for a in agent_list:
        a["Latency"] = round(a.get("Latency", 0), 1)
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
    full_period = int((end - start).total_seconds())
    client = get_cloudwatch_client()

    # Token counts and invocations use the regular period for timeline data.
    # Latency and TTFT use a single full-range period for correct averages.
    queries = [
        {"Id": "input_tokens", "MetricStat": {"Metric": {"Namespace": "AWS/Bedrock", "MetricName": "InputTokenCount"}, "Period": period, "Stat": "Sum"}},
        {"Id": "output_tokens", "MetricStat": {"Metric": {"Namespace": "AWS/Bedrock", "MetricName": "OutputTokenCount"}, "Period": period, "Stat": "Sum"}},
        {"Id": "bedrock_inv", "MetricStat": {"Metric": {"Namespace": "AWS/Bedrock", "MetricName": "Invocations"}, "Period": period, "Stat": "Sum"}},
        {"Id": "bedrock_lat", "MetricStat": {"Metric": {"Namespace": "AWS/Bedrock", "MetricName": "InvocationLatency"}, "Period": full_period, "Stat": "Average"}},
        {"Id": "ttft", "MetricStat": {"Metric": {"Namespace": "AWS/Bedrock", "MetricName": "TimeToFirstToken"}, "Period": full_period, "Stat": "Average"}},
        {"Id": "ttft_p90", "MetricStat": {"Metric": {"Namespace": "AWS/Bedrock", "MetricName": "TimeToFirstToken"}, "Period": full_period, "Stat": "p90"}},
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
        ("InvocationClientErrors", "Sum"),
        ("InvocationServerErrors", "Sum"),
    ]
    # Latency metrics use a full-range period for correct averages
    latency_metrics = [
        ("InvocationLatency", "Average"),
        ("TimeToFirstToken", "Average"),
    ]
    full_period = int((end - start).total_seconds())

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
        for mn, st in latency_metrics:
            qid = f"m{mi}_{mn.lower()}_fp"
            all_queries.append({
                "Id": qid,
                "MetricStat": {
                    "Metric": {
                        "Namespace": "AWS/Bedrock",
                        "MetricName": mn,
                        "Dimensions": [{"Name": "ModelId", "Value": model_id}],
                    },
                    "Period": full_period,
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
        if st == "Sum":
            models[model_id][mn] = _sum(vals)
        else:
            # Full-range period returns a single value
            models[model_id][mn] = vals[0] if vals else 0

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
    Returns {service_name: {input_tokens, output_tokens}}.
    Falls back to empty dict if spans log group doesn't exist.

    Uses only 'opentelemetry.instrumentation.botocore.bedrock-runtime' spans
    as the token source. Each of these spans represents one actual Bedrock API
    call, so there is no double-counting. This matches how the AWS console
    computes per-agent token totals.
    """
    from botocore.exceptions import ClientError
    from app.services.clients import get_logs_client

    client = get_logs_client()
    start, end = _parse_time_range(hours)

    query = """parse @message '"gen_ai.usage.input_tokens":*,' as in_tok
| parse @message '"gen_ai.usage.output_tokens":*,' as out_tok
| parse @message '"aws.local.service":"*"' as service_name
| parse @message '"name":"*"' as span_name
| filter ispresent(in_tok) and ispresent(service_name)
| filter span_name = "opentelemetry.instrumentation.botocore.bedrock-runtime"
| stats sum(in_tok) as input_tokens, sum(out_tok) as output_tokens by service_name"""

    try:
        resp = client.start_query(
            logGroupName=settings.spans_log_group,
            startTime=int(start.timestamp()),
            endTime=int(end.timestamp()),
            queryString=query,
            limit=10000,
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
        svc = row.get("service_name", "")
        if not svc:
            continue
        agent_name = svc.split(".")[0] if "." in svc else svc
        in_tok = int(float(row.get("input_tokens", 0)))
        out_tok = int(float(row.get("output_tokens", 0)))
        agents[agent_name] = {
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "avg_latency": 0,
        }
        if svc != agent_name:
            agents[svc] = agents[agent_name]

    logger.info("Per-agent tokens from spans (botocore only): %s",
                {k: v.get("input_tokens", 0) + v.get("output_tokens", 0) for k, v in agents.items()})
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
            key = "AgentCore"
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
    endpoints = inv["endpoints"]

    # Filter out MCP-only agents using the protocolConfiguration.serverProtocol
    # field from the runtime detail API. HTTP is the default when absent.
    allowed_protocols = {"HTTP", "A2A"}
    runtimes = [
        rt for rt in runtimes
        if rt.get("serverProtocol", "HTTP").upper() in allowed_protocols
    ]
    logger.info("Filtered runtimes (HTTP/A2A only): %d of %d",
                len(runtimes), len(inv["runtimes"]))

    agent_list, timeline = _get_agent_metrics(runtimes, hours)
    tokens = _get_token_metrics(hours)
    models = _get_per_model_metrics(hours)
    model_latency_timelines = _get_per_model_latency_timelines(hours)

    # Cost data is daily — Cost Explorer requires at least 1 day.
    # Use the actual time period, rounded up to whole days.
    cost_days = max((hours + 23) // 24, 1)
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
    # Weighted average latency: sum(latency * invocations) / sum(invocations)
    _lat_num = sum(a.get("Latency", 0) * a.get("Invocations", 0) for a in agent_list if a.get("Invocations", 0) > 0)
    _lat_den = sum(a.get("Invocations", 0) for a in agent_list if a.get("Invocations", 0) > 0)
    avg_latency = _lat_num / _lat_den if _lat_den > 0 else 0
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

    # Build a normalized lookup so span service names can match agent runtime names
    # even when they differ slightly (e.g. span has "pipelineops_PipelineMonitor"
    # but AgentCore API returns "pipelineops_PipelineMonitor" with different casing
    # or the span has a prefix/suffix the API name doesn't).
    _token_lookup_lower = {k.lower(): v for k, v in agent_tokens.items()}

    def _match_agent_tokens(agent_name: str) -> dict:
        """Find the best token match for an agent name."""
        # 1. Exact match
        if agent_name in agent_tokens:
            return agent_tokens[agent_name]
        # 2. Case-insensitive match
        lower = agent_name.lower()
        if lower in _token_lookup_lower:
            return _token_lookup_lower[lower]
        # 3. Substring match — span service name contains the agent name or vice versa
        for span_name, tok in agent_tokens.items():
            if agent_name in span_name or span_name in agent_name:
                return tok
            if lower in span_name.lower() or span_name.lower() in lower:
                return tok
        return {}

    for a in agent_list:
        agent_name = a.get("name", "")

        # Actual tokens from spans — keyed by agent name (from aws.local.service)
        at = _match_agent_tokens(agent_name)
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

    # Log token matching results for debugging
    if agent_tokens:
        matched = [a["name"] for a in agent_list if a.get("TotalTokens", 0) > 0]
        unmatched = [a["name"] for a in agent_list if a.get("TotalTokens", 0) == 0]
        if unmatched:
            logger.warning("Agents with 0 tokens (no span match): %s. Span keys: %s", unmatched, list(agent_tokens.keys()))

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
            "avg_model_latency_ms": round(tokens["bedrock_lat"]["values"][0] if tokens["bedrock_lat"]["values"] else 0, 1),
            "avg_ttft_ms": round(tokens["ttft"]["values"][0] if tokens["ttft"]["values"] else 0, 1),
            "p90_ttft_ms": round(tokens["ttft_p90"]["values"][0] if tokens["ttft_p90"]["values"] else 0, 1),
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
