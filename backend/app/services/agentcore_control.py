from app.services.clients import get_agentcore_control_client


def _paginate(method, key, **kwargs):
    items = []
    token = None
    while True:
        if token:
            kwargs["nextToken"] = token
        resp = method(**kwargs)
        items.extend(resp.get(key, []))
        token = resp.get("nextToken")
        if not token:
            break
    return items


def list_agent_runtimes():
    client = get_agentcore_control_client()
    return _paginate(client.list_agent_runtimes, "agentRuntimes")


def get_agent_runtime(runtime_id: str):
    client = get_agentcore_control_client()
    return client.get_agent_runtime(agentRuntimeId=runtime_id)


def list_agent_runtime_endpoints(runtime_id: str):
    client = get_agentcore_control_client()
    return _paginate(
        client.list_agent_runtime_endpoints,
        "runtimeEndpoints",
        agentRuntimeId=runtime_id,
    )


def list_gateways():
    client = get_agentcore_control_client()
    return _paginate(client.list_gateways, "items")


def list_gateway_targets(gateway_id: str):
    client = get_agentcore_control_client()
    return _paginate(
        client.list_gateway_targets, "items", gatewayIdentifier=gateway_id
    )


def list_memories():
    client = get_agentcore_control_client()
    return _paginate(client.list_memories, "memories")


def list_evaluators():
    client = get_agentcore_control_client()
    return _paginate(client.list_evaluators, "evaluators")


def list_online_evaluation_configs():
    client = get_agentcore_control_client()
    return _paginate(client.list_online_evaluation_configs, "onlineEvaluationConfigs")


def get_online_evaluation_config(config_id: str):
    client = get_agentcore_control_client()
    return client.get_online_evaluation_config(onlineEvaluationConfigId=config_id)


def list_code_interpreters():
    client = get_agentcore_control_client()
    return _paginate(client.list_code_interpreters, "codeInterpreterSummaries")


def list_browsers():
    client = get_agentcore_control_client()
    return _paginate(client.list_browsers, "browserSummaries")


def list_harnesses():
    client = get_agentcore_control_client()
    return _paginate(client.list_harnesses, "harnessSummaries")
