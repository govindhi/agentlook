from app.services.clients import get_agentcore_data_client


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


def list_actors(memory_id: str):
    client = get_agentcore_data_client()
    return _paginate(client.list_actors, "actorSummaries", memoryId=memory_id)


def list_sessions(memory_id: str, actor_id: str):
    client = get_agentcore_data_client()
    return _paginate(
        client.list_sessions, "sessionSummaries", memoryId=memory_id, actorId=actor_id
    )


def list_events(memory_id: str, session_id: str, actor_id: str, include_payloads: bool = True):
    client = get_agentcore_data_client()
    return _paginate(
        client.list_events,
        "events",
        memoryId=memory_id,
        sessionId=session_id,
        actorId=actor_id,
        includePayloads=include_payloads,
    )


def list_memory_extraction_jobs(memory_id: str):
    client = get_agentcore_data_client()
    return _paginate(
        client.list_memory_extraction_jobs, "memoryExtractionJobSummaries", memoryId=memory_id
    )
