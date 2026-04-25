"""Debug endpoints — only available when AGENTORBIT_DEBUG_ENDPOINTS=true."""
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter
from app.services.clients import get_cloudwatch_client, get_logs_client, get_ce_client
from app.config import settings

router = APIRouter(prefix="/api/debug", tags=["debug"])


@router.get("/namespaces")
def debug_namespaces():
    client = get_cloudwatch_client()
    results = {}
    for ns in ["Bedrock-AgentCore", "Bedrock-Agentcore", "AWS/Bedrock",
                "AWS/Bedrock-AgentCore", "AWS/BedrockAgentCore", "bedrock-agentcore"]:
        try:
            paginator = client.get_paginator("list_metrics")
            for page in paginator.paginate(Namespace=ns):
                for m in page.get("Metrics", []):
                    if ns not in results:
                        results[ns] = {"metrics": set(), "dimensions": set()}
                    results[ns]["metrics"].add(m["MetricName"])
                    for d in m.get("Dimensions", []):
                        results[ns]["dimensions"].add(f"{d['Name']}={d['Value'][:50]}")
        except Exception:
            pass
    return {ns: {"metrics": sorted(v["metrics"]), "dimensions": sorted(v["dimensions"])} for ns, v in results.items()}


@router.get("/namespace-detail")
def debug_namespace_detail(ns: str = "AWS/Bedrock-AgentCore"):
    client = get_cloudwatch_client()
    metrics_info = {}
    try:
        paginator = client.get_paginator("list_metrics")
        for page in paginator.paginate(Namespace=ns):
            for m in page.get("Metrics", []):
                name = m["MetricName"]
                if name not in metrics_info:
                    metrics_info[name] = {"dimensions": []}
                dims = {d["Name"]: d["Value"] for d in m.get("Dimensions", [])}
                if dims:
                    metrics_info[name]["dimensions"].append(dims)
    except Exception as e:
        return {"error": str(e)}
    return {"namespace": ns, "metrics": metrics_info}


@router.get("/cost")
def debug_cost():
    ce = get_ce_client()
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=7)
    try:
        resp = ce.get_cost_and_usage(
            TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
            Granularity="DAILY", Metrics=["UnblendedCost"],
        )
        total = 0.0
        days = []
        for period in resp.get("ResultsByTime", []):
            amt = float(period.get("Total", {}).get("UnblendedCost", {}).get("Amount", 0))
            days.append({"date": period["TimePeriod"]["Start"], "amount": amt})
            total += amt
        return {"status": "ok", "total_7d": round(total, 4), "days": days}
    except Exception as e:
        return {"status": "error", "error_type": type(e).__name__}


@router.get("/cost-services")
def debug_cost_services():
    ce = get_ce_client()
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=30)
    try:
        resp = ce.get_cost_and_usage(
            TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
            Granularity="MONTHLY", Metrics=["UnblendedCost"],
            GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
        )
        services = {}
        for period in resp.get("ResultsByTime", []):
            for group in period.get("Groups", []):
                svc = group["Keys"][0]
                amt = float(group["Metrics"]["UnblendedCost"]["Amount"])
                if amt > 0:
                    services[svc] = services.get(svc, 0) + amt
        bedrock_related = {k: round(v, 4) for k, v in services.items() if "edrock" in k.lower() or "agent" in k.lower()}
        return {"bedrock_related": bedrock_related}
    except Exception as e:
        return {"error_type": type(e).__name__}


@router.get("/observability")
def debug_observability():
    cw = get_cloudwatch_client()
    logs = get_logs_client()
    result = {"namespaces": [], "log_groups": {}}
    try:
        resp = cw.list_metrics(RecentlyActive="PT3H")
        seen = set()
        for m in resp.get("Metrics", []):
            ns = m["Namespace"]
            if any(kw in ns.lower() for kw in ["bedrock", "agent", "runtime"]):
                seen.add(ns)
        result["namespaces"] = sorted(seen)
    except Exception:
        pass
    for lg in [settings.spans_log_group, "/aws/vendedlogs/bedrock-agentcore"]:
        try:
            resp = logs.describe_log_groups(logGroupNamePrefix=lg, limit=5)
            groups = [g["logGroupName"] for g in resp.get("logGroups", [])]
            result["log_groups"][lg] = groups if groups else "not found"
        except Exception:
            result["log_groups"][lg] = "error"
    return result
