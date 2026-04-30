from fastapi import APIRouter, Query
from app.services import cloudwatch as cw

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


@router.get("/runtime")
def runtime_metrics(hours: int = Query(24, ge=1, le=720), resource_arn: str | None = None):
    return cw.get_runtime_metrics(hours, resource_arn)


@router.get("/gateway")
def gateway_metrics(hours: int = Query(24, ge=1, le=720), resource_arn: str | None = None):
    return cw.get_gateway_metrics(hours, resource_arn)


@router.get("/memory")
def memory_metrics(hours: int = Query(24, ge=1, le=720), resource_arn: str | None = None):
    return cw.get_memory_metrics(hours, resource_arn)


@router.get("/leaderboard")
def agent_leaderboard(hours: int = Query(24, ge=1, le=720)):
    return cw.get_agent_leaderboard(hours)


@router.get("/tokens")
def token_usage(hours: int = Query(24, ge=1, le=720)):
    return cw.get_token_usage(hours)


@router.get("/debug/spans-sample")
def debug_spans_sample():
    """Sample recent spans from /aws/spans/default to check what fields are present."""
    import time
    from datetime import datetime, timedelta, timezone
    from app.services.clients import get_logs_client
    from app.config import settings

    client = get_logs_client()
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=24)

    # First check what fields exist in recent spans
    query = """fields @timestamp, @message
| sort @timestamp desc
| limit 3"""

    try:
        resp = client.start_query(
            logGroupName=settings.spans_log_group,
            startTime=int(start.timestamp()),
            endTime=int(end.timestamp()),
            queryString=query,
            limit=3,
        )
        qid = resp["queryId"]
        for _ in range(30):
            result = client.get_query_results(queryId=qid)
            if result["status"] in ("Complete", "Failed", "Cancelled"):
                break
            time.sleep(0.5)

        rows = []
        for entry in result.get("results", []):
            row = {f["field"]: f["value"] for f in entry}
            rows.append(row)

        # Also check for agent-specific fields
        query2 = """fields @timestamp, attributes.`aws.agent.id`, attributes.`gen_ai.usage.input_tokens`, attributes.`gen_ai.usage.output_tokens`, attributes.`session.id`
| filter ispresent(attributes.`aws.agent.id`) or ispresent(attributes.`gen_ai.usage.input_tokens`)
| sort @timestamp desc
| limit 5"""

        resp2 = client.start_query(
            logGroupName=settings.spans_log_group,
            startTime=int(start.timestamp()),
            endTime=int(end.timestamp()),
            queryString=query2,
            limit=5,
        )
        qid2 = resp2["queryId"]
        for _ in range(30):
            result2 = client.get_query_results(queryId=qid2)
            if result2["status"] in ("Complete", "Failed", "Cancelled"):
                break
            time.sleep(0.5)

        agent_rows = []
        for entry in result2.get("results", []):
            row = {f["field"]: f["value"] for f in entry}
            agent_rows.append(row)

        return {
            "log_group": settings.spans_log_group,
            "total_sample": len(rows),
            "sample_messages": rows,
            "agent_specific_rows": agent_rows,
            "has_agent_data": len(agent_rows) > 0,
        }
    except Exception as e:
        return {"error": str(e), "log_group": settings.spans_log_group}


@router.get("/debug/list-span-groups")
def debug_list_span_groups():
    """List all log groups starting with /aws/spans to find the correct name."""
    from app.services.clients import get_logs_client
    client = get_logs_client()
    try:
        resp = client.describe_log_groups(logGroupNamePrefix="/aws/spans", limit=10)
        return {"groups": [g["logGroupName"] for g in resp.get("logGroups", [])]}
    except Exception as e:
        return {"error": str(e)}


@router.get("/debug/spans-token-detail")
def debug_spans_token_detail():
    """Show which span types have token data to diagnose double-counting.
    Groups by service_name AND op_name so you can see what each agent framework emits.
    """
    import time, json
    from datetime import datetime, timedelta, timezone
    from app.services.clients import get_logs_client
    from app.config import settings

    client = get_logs_client()
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=168)

    # Show ALL spans with tokens, grouped by service + op_name + span name
    # This reveals the exact structure so we can build the right dedup query
    query = """parse @message '"gen_ai.usage.input_tokens":*,' as in_tok
| parse @message '"gen_ai.usage.output_tokens":*,' as out_tok
| parse @message '"aws.local.service":"*"' as service_name
| parse @message '"gen_ai.operation.name":"*"' as op_name
| parse @message '"name":"*"' as span_name
| filter ispresent(in_tok) and ispresent(service_name)
| stats sum(in_tok) as total_input, sum(out_tok) as total_output, count(*) as span_count by service_name, op_name, span_name
| sort service_name, total_input desc"""

    try:
        resp = client.start_query(
            logGroupName=settings.spans_log_group,
            startTime=int(start.timestamp()),
            endTime=int(end.timestamp()),
            queryString=query,
            limit=20,
        )
        qid = resp["queryId"]
        for _ in range(30):
            result = client.get_query_results(queryId=qid)
            if result["status"] in ("Complete", "Failed", "Cancelled"):
                break
            time.sleep(0.5)
        rows = [{f["field"]: f["value"] for f in e} for e in result.get("results", [])]
        return {"rows": rows}
    except Exception as e:
        return {"error": str(e)}


@router.get("/debug/cw-dimensions")
def debug_cw_dimensions():
    """Show the actual CloudWatch dimension sets for each agent's Invocations metric."""
    from app.services.clients import get_cloudwatch_client
    from app.services import agentcore_control as ctrl
    from app.config import settings

    client = get_cloudwatch_client()

    # Resolve namespace
    ns = None
    for candidate in [settings.cw_namespace, "AWS/Bedrock-AgentCore", "Bedrock-AgentCore"]:
        try:
            resp = client.list_metrics(Namespace=candidate, MetricName="Invocations")
            if resp.get("Metrics"):
                ns = candidate
                break
        except Exception:
            pass
    if not ns:
        return {"error": "Could not resolve namespace"}

    runtimes = ctrl.list_agent_runtimes()
    result = []
    for rt in runtimes:
        arn = rt.get("agentRuntimeArn", "")
        name = rt.get("agentRuntimeName", "")
        if not arn:
            continue
        try:
            resp = client.list_metrics(
                Namespace=ns,
                MetricName="Invocations",
                Dimensions=[{"Name": "Resource", "Value": arn}],
            )
            dims_list = []
            for m in resp.get("Metrics", []):
                dims_list.append({d["Name"]: d["Value"] for d in m.get("Dimensions", [])})
            result.append({"name": name, "arn": arn, "dimension_sets": dims_list})
        except Exception as e:
            result.append({"name": name, "arn": arn, "error": str(e)})

    return {"namespace": ns, "agents": result}


@router.get("/debug/endpoint-protocols")
def debug_endpoint_protocols():
    """Show all endpoints and full runtime detail to find protocol info."""
    from app.services import agentcore_control as ctrl

    runtimes = ctrl.list_agent_runtimes()
    result = []
    for rt in runtimes:
        rid = rt.get("agentRuntimeId", "")
        name = rt.get("agentRuntimeName", "")
        if not rid:
            continue
        # Get full runtime detail — may have fields not in list response
        try:
            detail = ctrl.get_agent_runtime(rid)
            # Strip large/noisy fields
            detail.pop("ResponseMetadata", None)
        except Exception as e:
            detail = {"error": str(e)}
        try:
            endpoints = ctrl.list_agent_runtime_endpoints(rid)
            eps = []
            for ep in endpoints:
                ep.pop("ResponseMetadata", None)
                eps.append(ep)
        except Exception as e:
            eps = [{"error": str(e)}]
        result.append({"name": name, "runtimeId": rid, "runtime_detail_keys": list(detail.keys()) if isinstance(detail, dict) else [], "runtime_detail": detail, "endpoints": eps})
    return {"agents": result}


@router.get("/debug/validate")
def debug_validate(hours: int = Query(168, ge=1, le=720)):
    """Validate dashboard data against raw CloudWatch queries.
    Shows the exact queries, dimensions, time range, and raw values
    so you can compare with the AWS console.
    """
    from datetime import datetime, timedelta, timezone
    from app.services.clients import get_cloudwatch_client, get_logs_client
    from app.services import agentcore_control as ctrl
    from app.config import settings

    client = get_cloudwatch_client()
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=hours)

    # Resolve namespace — try all known candidates
    ns = None
    ns_tried = []
    for candidate in [settings.cw_namespace, "AWS/Bedrock-AgentCore", "Bedrock-AgentCore",
                      "Bedrock-Agentcore", "bedrock-agentcore", "AWS/BedrockAgentCore"]:
        try:
            resp = client.list_metrics(Namespace=candidate, MetricName="Invocations")
            ns_tried.append({"ns": candidate, "metrics_found": len(resp.get("Metrics", []))})
            if resp.get("Metrics"):
                ns = candidate
                break
        except Exception as e:
            ns_tried.append({"ns": candidate, "error": str(e)})

    # If no namespace found, also try listing ALL namespaces to find the right one
    all_namespaces = []
    if not ns:
        try:
            paginator = client.get_paginator("list_metrics")
            seen = set()
            for page in paginator.paginate(PaginationConfig={"MaxItems": 500}):
                for m in page.get("Metrics", []):
                    n = m.get("Namespace", "")
                    if n and n not in seen and ("bedrock" in n.lower() or "agent" in n.lower()):
                        seen.add(n)
                        all_namespaces.append(n)
        except Exception as e:
            all_namespaces = [f"error: {e}"]

    # Period selection (same logic as dashboard)
    if hours <= 6:
        period = 300
    elif hours <= 48:
        period = 3600
    else:
        period = 86400

    runtimes = ctrl.list_agent_runtimes()
    agents_validation = []

    for rt in runtimes:
        arn = rt.get("agentRuntimeArn", "")
        name = rt.get("agentRuntimeName", "")
        rid = rt.get("agentRuntimeId", "")
        if not arn:
            continue

        # Get protocol
        try:
            detail = ctrl.get_agent_runtime(rid)
            proto = detail.get("protocolConfiguration", {}).get("serverProtocol", "HTTP")
        except Exception:
            proto = "UNKNOWN"

        if not ns:
            agents_validation.append({
                "name": name, "protocol": proto, "arn": arn,
                "metrics": "NO_NAMESPACE_FOUND",
            })
            continue

        # Discover ALL dimension sets for this agent's Invocations metric
        all_dim_sets = []
        try:
            resp = client.list_metrics(
                Namespace=ns,
                MetricName="Invocations",
                Dimensions=[{"Name": "Resource", "Value": arn}],
            )
            for m in resp.get("Metrics", []):
                dim_set = {d["Name"]: d["Value"] for d in m.get("Dimensions", [])}
                all_dim_sets.append(dim_set)
        except Exception as e:
            all_dim_sets = [{"error": str(e)}]

        # Query metrics using EACH discovered dimension set and show results
        per_dimset_results = []
        for dim_set in all_dim_sets:
            if "error" in dim_set:
                per_dimset_results.append({"dims": dim_set, "metrics": "ERROR"})
                continue

            dims_list = [{"Name": k, "Value": v} for k, v in dim_set.items()]
            metrics_result = {}
            for metric_name, stat in [("Invocations", "Sum"), ("Sessions", "Sum"),
                                       ("Latency", "Average"), ("SystemErrors", "Sum"),
                                       ("UserErrors", "Sum"), ("Throttles", "Sum")]:
                try:
                    qid = metric_name.lower().replace("-", "_")
                    r = client.get_metric_data(
                        MetricDataQueries=[{
                            "Id": qid,
                            "MetricStat": {
                                "Metric": {"Namespace": ns, "MetricName": metric_name,
                                           "Dimensions": dims_list},
                                "Period": period, "Stat": stat,
                            },
                        }],
                        StartTime=start, EndTime=end,
                    )
                    vals = r.get("MetricDataResults", [{}])[0].get("Values", [])
                    total = sum(vals)
                    metrics_result[metric_name] = {
                        "total": total,
                        "datapoints": len(vals),
                    }
                except Exception as e:
                    metrics_result[metric_name] = {"error": str(e)}

            per_dimset_results.append({"dims": dim_set, "metrics": metrics_result})

        agents_validation.append({
            "name": name,
            "protocol": proto,
            "arn": arn,
            "dimension_sets_found": len(all_dim_sets),
            "results_per_dimension_set": per_dimset_results,
        })

    # Also validate span tokens
    span_tokens = {}
    try:
        logs = get_logs_client()
        import time as _time
        query = """parse @message '"gen_ai.usage.input_tokens":*,' as in_tok
| parse @message '"gen_ai.usage.output_tokens":*,' as out_tok
| parse @message '"aws.local.service":"*"' as service_name
| parse @message '"gen_ai.operation.name":"*"' as op_name
| parse @message '"spanId":"*"' as span_id
| filter ispresent(in_tok) and ispresent(service_name) and ispresent(span_id)
| filter op_name = "invoke_agent" or op_name = "chat"
| stats sum(in_tok) as input_tokens, sum(out_tok) as output_tokens by service_name, op_name
| sort input_tokens desc"""
        resp = logs.start_query(
            logGroupName=settings.spans_log_group,
            startTime=int(start.timestamp()),
            endTime=int(end.timestamp()),
            queryString=query, limit=10000,
        )
        qid = resp["queryId"]
        for _ in range(30):
            result = logs.get_query_results(queryId=qid)
            if result["status"] in ("Complete", "Failed", "Cancelled"):
                break
            _time.sleep(0.5)
        for entry in result.get("results", []):
            row = {f["field"]: f["value"] for f in entry}
            svc = row.get("service_name", "")
            if svc:
                agent_name = svc.split(".")[0] if "." in svc else svc
                in_tok = int(float(row.get("input_tokens", 0)))
                out_tok = int(float(row.get("output_tokens", 0)))
                op = row.get("op_name", "unknown")
                total = in_tok + out_tok
                existing = span_tokens.get(agent_name)
                if not existing or total > existing.get("total", 0):
                    span_tokens[agent_name] = {
                        "op_name": op,
                        "input_tokens": in_tok,
                        "output_tokens": out_tok,
                        "total": total,
                    }
    except Exception as e:
        span_tokens = {"error": str(e)}

    return {
        "time_range": {"start": start.isoformat(), "end": end.isoformat(), "hours": hours},
        "namespace_resolved": ns,
        "namespace_candidates_tried": ns_tried,
        "other_bedrock_namespaces_found": all_namespaces if not ns else "N/A (resolved)",
        "period_seconds": period,
        "agents": agents_validation,
        "span_tokens": span_tokens,
    }


@router.get("/debug/agentcore-metrics-list")
def debug_agentcore_metrics_list():
    """List ALL metric names available in the AgentCore namespace to find token metrics."""
    from app.services.clients import get_cloudwatch_client
    from app.config import settings

    client = get_cloudwatch_client()

    # Resolve namespace
    ns = None
    for candidate in [settings.cw_namespace, "AWS/Bedrock-AgentCore", "Bedrock-AgentCore"]:
        try:
            resp = client.list_metrics(Namespace=candidate, MetricName="Invocations")
            if resp.get("Metrics"):
                ns = candidate
                break
        except Exception:
            pass

    if not ns:
        return {"error": "No namespace found"}

    # List ALL unique metric names in this namespace
    metric_names = set()
    try:
        paginator = client.get_paginator("list_metrics")
        for page in paginator.paginate(Namespace=ns):
            for m in page.get("Metrics", []):
                metric_names.add(m.get("MetricName", ""))
    except Exception as e:
        return {"error": str(e), "namespace": ns}

    # For each metric, show a sample of its dimensions
    metrics_detail = []
    for mn in sorted(metric_names):
        try:
            resp = client.list_metrics(Namespace=ns, MetricName=mn)
            sample_dims = []
            for m in resp.get("Metrics", [])[:3]:
                sample_dims.append({d["Name"]: d["Value"] for d in m.get("Dimensions", [])})
            metrics_detail.append({"metric": mn, "sample_dimensions": sample_dims})
        except Exception:
            metrics_detail.append({"metric": mn, "error": "failed"})

    return {"namespace": ns, "total_metric_names": len(metric_names), "metrics": metrics_detail}
