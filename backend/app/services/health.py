from collections import Counter
from app.services import agentcore_control as ctrl


def _count_statuses(items, status_key="status"):
    counter = Counter()
    for item in items:
        counter[item.get(status_key, "UNKNOWN")] += 1
    return dict(counter)


def get_health_overview():
    runtimes = ctrl.list_agent_runtimes()
    gateways = ctrl.list_gateways()
    memories = ctrl.list_memories()

    # Collect endpoints for all runtimes
    all_endpoints = []
    for rt in runtimes:
        rid = rt.get("agentRuntimeId", "")
        if rid:
            try:
                all_endpoints.extend(ctrl.list_agent_runtime_endpoints(rid))
            except Exception:
                pass

    try:
        code_interpreters = ctrl.list_code_interpreters()
    except Exception:
        code_interpreters = []

    try:
        browsers = ctrl.list_browsers()
    except Exception:
        browsers = []

    return {
        "runtimes": {"total": len(runtimes), "byStatus": _count_statuses(runtimes), "items": runtimes},
        "endpoints": {"total": len(all_endpoints), "byStatus": _count_statuses(all_endpoints), "items": all_endpoints},
        "gateways": {"total": len(gateways), "byStatus": _count_statuses(gateways), "items": gateways},
        "memories": {"total": len(memories), "byStatus": _count_statuses(memories), "items": memories},
        "codeInterpreters": {"total": len(code_interpreters), "byStatus": _count_statuses(code_interpreters), "items": code_interpreters},
        "browsers": {"total": len(browsers), "byStatus": _count_statuses(browsers), "items": browsers},
    }
