"""Additional execution HTTP routes; handlers never contact a scheduler directly."""
from controller import workspace_actions as actions, workspace_runs as runs, workspace_schedules as schedules
from controller import workspace_store as store


def route(method, slug, rest, req):
    from controller.http import _json, _read_json, _q
    parts = rest.strip('/').split('/')
    if len(parts) == 3 and parts[0] == 'plans' and parts[2] == 'schedule-review' and method == 'GET':
        from controller.workspace_contracts import version_token
        plan = store.read(slug, 'plan', parts[1])
        return _json(200, {'plan_id': plan['id'], 'expected_version': version_token(plan)})
    if rest == 'executions' and method == 'GET':
        return _json(200, runs.executions(slug, {'experiment_id': _q(req, 'experiment_id') or _q(req, 'experiment'), 'id': _q(req, 'id') or _q(req, 'execution'), 'summary': _q(req, 'summary') or _q(req, 'state'), 'purpose': _q(req, 'purpose'), 'attention': _q(req, 'attention'), **{k:_q(req,k) for k in ('campaign','collection','date','search','stage','variant','attempt')}}))
    if len(parts) == 2 and parts[0] == 'executions' and method == 'GET':
        return _json(200, runs.project_execution(slug, store.read(slug, 'execution', parts[1])))
    if rest == 'queue' and method == 'GET':
        return _json(200, runs.queue(slug, {k:_q(req,k) for k in ('execution','experiment','stage','variant','attempt','purpose','campaign','collection','state','date','search')}))
    if len(parts) == 3 and parts[0] == 'attempts' and parts[2] == 'logs' and method == 'GET':
        return _json(200, runs.logs(slug, parts[1], stream=_q(req, 'stream', 'stdout'), offset=_q(req, 'offset'), cursor=_q(req, 'cursor'), limit=_q(req, 'limit', '65536'), job_id=_q(req, 'job_id')))
    if len(parts) == 3 and parts[0] == 'attempts' and parts[2] == 'retrieve-log' and method == 'POST':
        return _json(200, runs.retrieve_log(slug, parts[1], _read_json(req)))
    if rest == 'management-plans' and method == 'POST':
        return _json(201, actions.prepare(slug, _read_json(req)))
    if len(parts) == 2 and parts[0] == 'management-plans' and method == 'GET':
        return _json(200, store.read(slug, 'management-plan', parts[1]))
    if len(parts) == 3 and parts[0] == 'management-plans' and parts[2] == 'apply' and method == 'POST':
        return _json(202, actions.apply(slug, parts[1], _read_json(req)))
    if len(parts) == 2 and parts[0] == 'operations' and method == 'GET':
        return _json(200, store.read(slug, 'operation', parts[1]))
    if len(parts) == 3 and parts[0] == 'operations' and parts[2] == 'reconcile' and method == 'POST':
        return _json(200, actions.reconcile(slug, parts[1]))
    if rest == 'schedules':
        if method == 'GET':
            return _json(200, {'schedules': store.listing(slug, 'schedule')})
        if method == 'POST':
            return _json(201, schedules.create(slug, _read_json(req)))
    if len(parts) == 2 and parts[0] == 'schedules':
        if method == 'GET':
            return _json(200, store.read(slug, 'schedule', parts[1]))
        if method == 'PATCH':
            return _json(200, schedules.update(slug, parts[1], _read_json(req)))
    if len(parts) == 3 and parts[0] == 'schedules' and parts[2] == 'cancel' and method == 'POST':
        return _json(200, schedules.update(slug, parts[1], _read_json(req), cancel=True))
    return None
