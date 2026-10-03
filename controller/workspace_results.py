"""Declared-field result queries and immutable companion comparisons.

Bounded file-scan fallback: full-corpus search stays disabled until an index is
available. No read query runs project code or writes an index.
"""
from __future__ import annotations

import base64
import collections
import copy
import json
from pathlib import Path
import statistics

from controller import workspace_store as store
from controller import workspace_artifacts as files
from controller.workspace_store import WorkspaceError, Conflict, Missing

SCAN_BYTES = 8 * 1024 * 1024
SCAN_RECORDS = 5000


def field(value, path, default=None):
    for part in path.split('.'):
        if not isinstance(value, dict) or part not in value:
            return default
        value = value[part]
    return value


def _mapping(slug, artifact):
    return artifact.get('result_schema', {})


def reference(artifact):
    return {'kind': 'artifact', 'id': artifact['id'], 'version': artifact.get('content_version', artifact.get('digest')),
            **{k: artifact.get(k) for k in ('execution_id', 'variant_id', 'stage_id', 'attempt_id', 'purpose')}}


def validate_references(slug, references):
    if not isinstance(references, list) or not references:
        raise WorkspaceError('Select exact evidence references')
    values = []
    for ref in references:
        if not isinstance(ref, dict):
            raise WorkspaceError('Each evidence reference must be an object')
        kind = ref.get('kind'); identity = ref.get('id')
        if kind == 'sample':
            value = sample(slug, identity)
            version = value['artifact_version']
            frozen = {'kind': kind, 'id': identity, 'version': version, 'artifact_id': value['artifact_id']}
        else:
            if kind not in ('artifact', 'comparison', 'plan', 'report'):
                raise WorkspaceError('Unsupported evidence reference kind')
            value = store.read(slug, 'plan' if kind == 'report' else kind, identity)
            version = value.get('content_version', value.get('digest', value.get('version', files.fingerprint(value))))
            frozen = reference(value) if kind == 'artifact' else {'kind': kind, 'id': identity, 'version': version}
        if ref.get('version') is not None and ref['version'] != version:
            raise Conflict('Evidence reference version changed: ' + str(identity), current_version=version, expected_version=ref['version'])
        values.append(frozen)
    return values



def project_currency(artifact, all_artifacts, executions, plans):
    """Pure indexed projection; Overview reads no corpus bytes."""
    execution = executions.get(artifact.get('execution_id'), {})
    plan = plans.get(execution.get('plan_id'), {})
    projection = {'analysis_activity': execution.get('state', 'unknown') if plan.get('kind') == 'analysis' else 'none',
                  'currency': 'unknown'}
    if plan.get('kind') != 'analysis':
        return projection
    projection.update(analysis_revision=plan.get('analysis_revision'), analysis_plan_id=plan['id'],
                      input_references=plan.get('artifact_ids', []), currency='current')
    for identity in plan.get('artifact_ids', []):
        selected = all_artifacts.get(identity)
        if not selected:
            projection['currency'] = 'unknown'; break
        if selected.get('integrity') in ('changed', 'mismatch') or selected.get('availability') == 'unavailable':
            projection['currency'] = 'input-changed'; break
        if any(a.get('supersedes') == identity for a in all_artifacts.values()):
            projection['currency'] = 'earlier-inputs'
    return projection

def query(slug, filters):
    values = store.listing(slug, 'artifact')
    all_artifacts = {a['id']: a for a in values}
    executions = {e['id']: e for e in store.listing(slug, 'execution')}
    plans = {p['id']: p for p in store.listing(slug, 'plan')}
    if filters.get('analysis'):
        analysis = plans.get(filters['analysis'])
        if not analysis or analysis.get('kind') != 'analysis':
            raise Missing('Unknown analysis revision ' + str(filters['analysis']))
        execution_ids = {e['id'] for e in executions.values() if e.get('plan_id') == analysis['id']}
        values = [a for a in values if a.get('execution_id') in execution_ids]
    for key in ('execution', 'experiment', 'variant', 'stage', 'attempt', 'artifact'):
        target = filters.get(key)
        if target:
            values = [a for a in values if a.get('id' if key == 'artifact' else key + '_id') == target]
    if filters.get('campaign'):
        values = [a for a in values if a.get('campaign') or executions.get(a.get('execution_id'), {}).get('campaign')]
        values = [a for a in values if (a.get('campaign') or executions.get(a.get('execution_id'), {}).get('campaign')) == filters['campaign']]
    purpose = filters.get('purpose', 'experiment')
    if purpose != 'all':
        values = [a for a in values if a.get('purpose', 'unclassified') == purpose]
    if filters.get('superseded') != 'true':
        superseded = {a.get('supersedes') for a in values if a.get('supersedes')}
        values = [a for a in values if a['id'] not in superseded and not a.get('superseded_research_run')]
    rows = []
    for item in values:
        artifact = copy.deepcopy(item)
        mapping = _mapping(slug, artifact)
        family = field(artifact, mapping.get('family_path', 'provenance.parameters.family'))
        artifact['collection'] = family or 'unknown'
        if filters.get('collection') and artifact['collection'] != filters['collection']:
            continue
        local = bool(artifact.get('files'))
        artifact.setdefault('availability', 'local' if local else 'unknown')
        artifact.setdefault('integrity', 'unchecked')
        artifact.setdefault('completeness', 'complete' if artifact.get('complete') else 'partial')
        artifact['reference'] = reference(artifact)
        declared_coverage = artifact.get('evidence', {}).get('coverage', {}) if isinstance(artifact.get('evidence'), dict) else {}
        artifact['coverage'] = {'expected': declared_coverage.get('expected'), 'observed': declared_coverage.get('observed'),
                                'assessed': declared_coverage.get('assessed', field(artifact,'provenance.measurements.denominator')),
                                'duplicates': declared_coverage.get('duplicates'), 'exclusions': declared_coverage.get('exclusions'),
                                'missing_identities': declared_coverage.get('missing_identities')}
        artifact['derived_views'] = bool(mapping)
        artifact['derived_reason'] = None if mapping else 'This artifact schema has no declared sample field mapping; file inspection remains available.'
        artifact.update(project_currency(artifact, all_artifacts, executions, plans))
        if filters.get('completeness') and artifact['completeness'] != {'incomplete': 'partial'}.get(filters['completeness'], filters['completeness']):
            continue
        if filters.get('currency') and artifact['currency'] != {'newer-inputs': 'earlier-inputs'}.get(filters['currency'], filters['currency']):
            continue
        rows.append(artifact)
    token = files.fingerprint([reference(a) for a in rows])
    if filters.get('selection_fingerprint') and filters['selection_fingerprint'] != token:
        raise Conflict('Result selection changed; refresh before loading another page', current_version=token, expected_version=filters['selection_fingerprint'])
    offset = max(0, int(filters.get('offset') or 0)); limit = min(100, max(1, int(filters.get('limit') or 50)))
    return {'result_set_id': 'results-' + files.fingerprint({'references':[reference(a) for a in rows],'policy':{k:v for k,v in filters.items() if k not in ('offset','limit','selection_fingerprint')}}), 'index_version':'bounded-scan-v1',
            'provenance_status': 'known' if rows and all(a.get('source_digest') and a.get('provenance') for a in rows) else 'unknown',
            'artifacts': rows[offset:offset+limit], 'total': len(rows), 'selection_fingerprint': token,
            'next_offset': offset+limit if offset+limit < len(rows) else None,
            'coverage': {'artifacts': len(rows), 'complete': sum(bool(a.get('complete')) for a in rows), 'expected_items': None,
                         'observed_items': None, 'unknown': any(a['coverage']['expected'] is None or a['coverage']['observed'] is None for a in rows),
                         'by_artifact': [{'artifact_id':a['id'], **a['coverage']} for a in rows], 'count_scope':'per artifact; no cross-stage total'}, 'observed_at': store.now(),
            'search_scope': 'selected indexed artifact metadata', 'full_corpus_search': False,
            'analyses': [p for p in plans.values() if p.get('kind') == 'analysis' and (not any(filters.get(k) for k in ('artifact','execution','experiment','variant','stage','attempt','collection','campaign','analysis')) or p['id'] == filters.get('analysis') or p['id'] in {executions.get(a.get('execution_id'), {}).get('plan_id') for a in rows} or set(p.get('artifact_ids', [])) & {a['id'] for a in rows})]}


def _sample_id(artifact, path, offset):
    return base64.urlsafe_b64encode(json.dumps([artifact, path, offset], separators=(',', ':')).encode()).decode().rstrip('=')


def _normalize(artifact, mapping, record, path, offset, size):
    fields = mapping.get('fields', {})
    value = {key: field(record, location) for key, location in fields.items()}
    value.update(id=_sample_id(artifact['id'], path, offset), artifact_id=artifact['id'],
                 artifact_version=artifact.get('content_version', artifact.get('digest')), locator={'path': path, 'offset': offset, 'bytes': size},
                 condition=reference(artifact), complete=artifact.get('complete', False))
    value['recorded_fields'] = {key: 'not-recorded' if field(record, location) is None else 'recorded-empty' if field(record, location) in ('', [], {}) else 'recorded'
                                for key, location in fields.items()}
    value['join_key'] = [value.get(key) for key in mapping.get('join_fields', ['dataset', 'item', 'sample_index', 'stage'])]
    # Text and scientific outcomes come from the project's explicit schema mapping.
    value['raw'] = record
    return value


def _scan(slug, artifact, *, limit=SCAN_RECORDS, offset=0, path_filter=None):
    mapping = _mapping(slug, artifact)
    if not mapping:
        return [], [{'artifact_id': artifact['id'], 'reason': 'Unsupported sample schema'}], False, None
    rows = []; errors = []; consumed = 0; next_cursor = None
    members = [m for m in artifact.get('files', []) if m['path'].endswith('.jsonl')]
    for file_index, member in enumerate(members):
        if not member['path'].endswith('.jsonl'):
            continue
        if path_filter and member['path'] != path_filter:
            continue
        path, _ = files.member_path(slug, artifact, member['path'])
        with path.open('rb') as stream:
            if path_filter:
                stream.seek(offset)
                path_filter = None
            while consumed < SCAN_BYTES and len(rows) < limit:
                position = stream.tell(); data = stream.readline(files.MAX_BYTES + 1)
                if not data:
                    break
                if consumed + len(data) > SCAN_BYTES:
                    return rows, errors, True, {'path': member['path'], 'offset': position}
                consumed += len(data)
                if len(data) > files.MAX_BYTES:
                    errors.append({'artifact_id': artifact['id'], 'path': member['path'], 'offset': position, 'reason': 'Record exceeds the 256 KiB inspection budget; use Files bounded pages'})
                    while not data.endswith(b'\n') and consumed < SCAN_BYTES:
                        data = stream.readline(min(files.MAX_BYTES + 1, SCAN_BYTES - consumed))
                        if not data: break
                        consumed += len(data)
                    following = {'path': member['path'], 'offset': stream.tell()} if data.endswith(b'\n') else None
                    return rows, errors, True, following
                try:
                    record = files.strict_json(data)
                    if not isinstance(record, dict):
                        raise ValueError('Sample record must be an object')
                    rows.append(_normalize(artifact, mapping, record, member['path'], position, len(data)))
                except (ValueError, UnicodeDecodeError) as error:
                    errors.append({'artifact_id': artifact['id'], 'path': member['path'], 'offset': position, 'reason': str(error)})
            if stream.tell() < path.stat().st_size:
                next_cursor = {'path': member['path'], 'offset': stream.tell()}
                break
            if (len(rows) >= limit or consumed >= SCAN_BYTES) and file_index + 1 < len(members):
                next_cursor = {'path': members[file_index + 1]['path'], 'offset': 0}
                break
    return rows, errors, bool(next_cursor), next_cursor


def samples(slug, filters):
    if not filters.get('artifact'):
        raise WorkspaceError('Select one exact artifact for bounded sample inspection')
    artifact = store.read(slug, 'artifact', filters['artifact'])
    version = artifact.get('content_version', artifact.get('digest'))
    if filters.get('version') and filters['version'] != version:
        raise Conflict('Artifact version changed; restart sample inspection', current_version=version, expected_version=filters['version'])
    rows, errors, truncated, cursor = _scan(slug, artifact, limit=min(100, max(1, int(filters.get('limit') or 100))),
                                          offset=max(0, int(filters.get('offset') or 0)), path_filter=filters.get('path'))
    return {'samples': rows, 'errors': errors, 'excluded': len(errors), 'total': None if truncated else len(rows), 'truncated': truncated,
            'next_cursor': cursor, 'artifact_version': version, 'selection_fingerprint': files.fingerprint(reference(artifact)),
            'observed_at': store.now(), 'search_scope': 'loaded sample page', 'full_corpus_search': False}


def sample(slug, identity):
    try:
        artifact_id, relative, offset = json.loads(base64.urlsafe_b64decode(identity + '=' * (-len(identity) % 4)))
    except (ValueError, TypeError, UnicodeDecodeError):
        raise WorkspaceError('Invalid sample identity') from None
    artifact = store.read(slug, 'artifact', artifact_id)
    path, member = files.member_path(slug, artifact, relative)
    with path.open('rb') as stream:
        stream.seek(int(offset)); data = stream.readline(files.MAX_BYTES + 1)
    if len(data) > files.MAX_BYTES:
        raise WorkspaceError('Sample exceeds bounded preview; open its Files locator')
    try:
        record = files.strict_json(data)
    except ValueError:
        raise Conflict('Sample locator does not contain a valid record') from None
    return _normalize(artifact, _mapping(slug, artifact), record, relative, offset, len(data))


def metric_values(slug, artifact, rows):
    definitions = artifact.get('metric_definitions', {})
    output = []
    for identity, definition in definitions.items():
        if definition.get('type') not in ('number', 'integer'):
            continue
        location = definition.get('field', definition.get('source_field', ''))
        declared_denominator = None
        if definition.get('source', '').endswith('.json'):
            values = []
            member = next((m for m in artifact.get('files', []) if m['path'].endswith('/' + definition['source'])), None)
            if member:
                path, _ = files.member_path(slug, artifact, member['path'])
                if path.stat().st_size <= files.MAX_BYTES:
                    try: source = files.strict_json(path.read_text())
                    except ValueError: source = {}
                    v = field(source, location)
                    denominator_path = definition.get('denominator', '')
                    prefix = Path(definition['source']).stem + '.'
                    if isinstance(denominator_path, str) and denominator_path.startswith(prefix):
                        denominator_path = denominator_path[len(prefix):]
                    declared_denominator = field(source, denominator_path) if isinstance(denominator_path, str) else None
                    if isinstance(v, (int, float)) and not isinstance(v, bool): values = [v]
            missing = int(not values)
        else:
            candidates = [field(r['raw'], location) for r in rows]
            values = [v for v in candidates if isinstance(v, (int, float)) and not isinstance(v, bool)]
            missing = len(candidates) - len(values)
        aggregation = definition.get('aggregation', 'none')
        result = statistics.mean(values) if values and aggregation == 'mean' else sum(values) if values and aggregation == 'sum' else values[0] if len(values) == 1 else None
        if declared_denominator == 0:
            result = None
        output.append({'id': identity, 'definition': definition, 'version': files.fingerprint(definition), 'value': result,
                       'missing_reason': None if result is not None else 'No defined value for the declared aggregation',
                       'unit': definition.get('unit'), 'denominator': declared_denominator if isinstance(declared_denominator, (int, float)) else len(values),
                       'numerator': result * declared_denominator if definition.get('unit') == 'fraction' and result is not None and isinstance(declared_denominator, (int, float)) else None, 'excluded': missing,
                       'source_cohort': [r['id'] for r in rows]})
    return output


def compare(slug, body, *, save=True):
    ids = body.get('artifact_ids', [])
    if not isinstance(ids, list) or not 2 <= len(ids) <= 4 or len(set(ids)) != len(ids):
        raise WorkspaceError('Choose two to four distinct conditions')
    baseline = body.get('baseline')
    if baseline not in ids:
        raise WorkspaceError('Choose an explicit baseline condition')
    artifacts = [store.read(slug, 'artifact', i) for i in ids]
    if any(a.get('purpose') != 'experiment' for a in artifacts):
        raise Conflict('Smoke tests and unclassified evidence cannot enter research comparisons')
    exploratory = bool(body.get('exploratory'))
    if not exploratory and any(not a.get('complete') for a in artifacts):
        raise Conflict('Default comparisons require complete evidence; explicitly select exploratory inspection for partial evidence')
    conditions = []; maps = {}; ambiguous = False; incomplete_scan = False; invalid_join = False; malformed = False
    for artifact in artifacts:
        rows, errors, truncated, _ = _scan(slug, artifact)
        mapping = _mapping(slug, artifact)
        groups = collections.defaultdict(list)
        for row in rows:
            if any(part is None for part in row['join_key']):
                invalid_join = True
                continue
            groups[json.dumps(row['join_key'], sort_keys=True)].append(row)
        malformed |= bool(errors)
        duplicates = sum(len(v)-1 for v in groups.values() if len(v)>1)
        ambiguous |= bool(duplicates)
        incomplete_scan |= truncated
        maps[artifact['id']] = groups
        provenance_fields = mapping.get('compatibility_fields', ['dataset_revision', 'evaluator_version'])
        compatibility = {key: field(artifact, path) for key, path in mapping.get('compatibility', {}).items() if key in provenance_fields}
        conditions.append({'id': artifact['id'], 'reference': reference(artifact), 'parameters': artifact.get('parameters', {}),
                           'provenance': compatibility, 'metrics': metric_values(slug, artifact, rows), 'observed': len(rows),
                           'excluded': len(errors), 'errors': errors, 'duplicates': duplicates, 'truncated': truncated})
    provenance = [c['provenance'] for c in conditions]
    unknown = any(not p or any(v is None for v in p.values()) for p in provenance)
    metric_sets = [{m['id']: m['version'] for m in c['metrics']} for c in conditions]
    metric_compatible = bool(metric_sets[0]) and all(m == metric_sets[0] for m in metric_sets)
    compatible = not unknown and all(p == provenance[0] for p in provenance) and metric_compatible
    keys = [set(maps[i]) for i in ids]; intersection = set.intersection(*keys); union = set.union(*keys)
    policy = body.get('join_policy', 'available')
    if policy not in ('available', 'intersection'):
        raise WorkspaceError('Unknown comparison cohort policy')
    paired = []
    for key in sorted(intersection):
        paired.append({'join_key': json.loads(key), 'samples': {i: maps[i][key][0]['id'] for i in ids}})
    result = dict(id=store.new_id('comparison'), version=1, created_at=store.now(), conditions=conditions, baseline=baseline, join_policy=policy,
                  exploratory=exploratory, compatibility='unknown' if unknown else 'compatible' if compatible else 'different',
                  paired_deltas_enabled=compatible and not ambiguous and not incomplete_scan and not exploratory and not invalid_join and not malformed,
                  paired_delta_reason='Undefined sample identity' if invalid_join else 'Malformed samples excluded' if malformed else 'Metric definitions or units differ' if not metric_compatible else 'Ambiguous sample join' if ambiguous else 'Bounded scan incomplete' if incomplete_scan else 'Unknown or different scientific provenance' if not compatible else 'Exploratory partial evidence' if exploratory else None,
                  coverage={'matched': len(intersection), 'unmatched': {i: len(maps[i])-len(intersection) for i in ids}, 'union': len(union),
                            'excluded': sum(c['excluded'] for c in conditions), 'unknown': incomplete_scan}, samples=paired,
                  selected_metrics=body.get('metrics', []), filters=body.get('filters', {}))
    # Deltas use only the displayed matched cohort, never each condition's unpaired totals.
    if result['paired_deltas_enabled']:
        paired_metrics = {a['id']: metric_values(slug, a, [maps[a['id']][k][0] for k in sorted(intersection)]) for a in artifacts}
        base = {m['id']: m for m in paired_metrics[baseline]}
        result['deltas'] = {identity: [{'metric': m['id'], 'value': m['value']-base[m['id']]['value'] if m['value'] is not None and base[m['id']]['value'] is not None else None,
                                       'matched': len(intersection)} for m in values if m['id'] in base] for identity, values in paired_metrics.items() if identity != baseline}
    if save:
        with store.transaction(slug) as con:
            store.put(con, 'comparison', result)
    return result


def save_view(slug, body):
    references = validate_references(slug, body.get('references'))
    form = body.get('form', 'table')
    if form not in ('table', 'bar', 'histogram', 'scatter', 'line'):
        raise WorkspaceError('Unsupported fixed plot form')
    if form == 'line' and not body.get('step_field'):
        raise WorkspaceError('Line plots require an explicit declared step or time field')
    selection = {'artifact_ids': [r['id'] for r in references if r['kind'] == 'artifact'], 'metrics': body.get('metrics', [])}
    frozen = (metrics(slug, selection) if form in ('table', 'bar') else points(slug, selection)) if body.get('metrics') else None
    if form == 'scatter' and len(body.get('metrics', [])) != 2:
        raise WorkspaceError('Scatter requires exactly two declared numeric coordinates')
    if form == 'histogram' and len(body.get('metrics', [])) != 1:
        raise WorkspaceError('Histogram requires one declared numeric coordinate')
    if form == 'line' and (len(body.get('metrics', [])) != 2 or not frozen or frozen['definitions'].get(body['step_field'], {}).get('axis') not in ('step', 'time')):
        raise WorkspaceError('Line axis must be a declared step or time metric')
    if form == 'line':
        coordinates = [(p['artifact_id'],p[body['step_field']]) for p in frozen['points']]
        if len(set(coordinates)) != len(coordinates):
            raise Conflict('Line plot has multiple observations per condition and step; select a declared repeat aggregation first')
    value = dict(id=store.new_id('view'), data=frozen, version=1, references=references, form=form, filters=body.get('filters', {}),
                 metrics=body.get('metrics', []), step_field=body.get('step_field'), created_at=store.now())
    with store.transaction(slug) as con:
        store.put(con, 'saved_view', value)
    return value


def export_comparison(slug, identity):
    comparison = store.read(slug, 'comparison', identity)
    # The companion manifest is self-contained and retains the displayed cohort.
    return {'schema': 'unity.workspace.comparison-export', 'version': 1, 'comparison': comparison,
            'definitions': {m['id']: m['definition'] for c in comparison['conditions'] for m in c['metrics']},
            'artifact_references': [c['reference'] for c in comparison['conditions']]}


def metrics(slug, body):
    ids = body.get('artifact_ids', [])
    if not isinstance(ids, list) or not ids or len(ids) > 100:
        raise WorkspaceError('Select 1–100 exact artifact identities')
    output = []
    for identity in ids:
        artifact = store.read(slug, 'artifact', identity)
        if artifact.get('purpose') != 'experiment':
            raise Conflict('Research plots exclude Smoke test and unclassified evidence')
        rows, errors, truncated, _ = _scan(slug, artifact)
        for metric in metric_values(slug, artifact, rows):
            if body.get('metrics') and metric['id'] not in body['metrics']:
                continue
            output.append(dict(metric, artifact_id=identity, bounded=truncated, malformed=len(errors)))
    return {'metrics': output, 'observed_at': store.now()}


def points(slug, body):
    identities = body.get('artifact_ids', [])
    metric_ids = body.get('metrics', [])
    if not identities or len(identities) > 20 or not metric_ids or len(metric_ids) > 2:
        raise WorkspaceError('Select up to twenty conditions and one or two declared numeric metrics')
    result = []; definitions = {}; exclusions = 0; truncated = False
    for identity in identities:
        if len(result) >= SCAN_RECORDS:
            truncated = True
            break
        artifact = store.read(slug, 'artifact', identity)
        if artifact.get('purpose') != 'experiment':
            raise Conflict('Research plots exclude Smoke test and unclassified evidence')
        rows, errors, partial, _ = _scan(slug, artifact, limit=SCAN_RECORDS-len(result))
        exclusions += len(errors); truncated |= partial
        for metric in metric_ids:
            definition = artifact.get('metric_definitions', {}).get(metric)
            if not definition or definition.get('type') not in ('number', 'integer') or not definition.get('source', '').endswith('.jsonl'):
                raise WorkspaceError('Plot coordinates require declared numeric JSONL sample fields: ' + str(metric))
            prior = definitions.get(metric)
            if prior and prior != definition:
                raise Conflict('Plot metric definitions differ across selected conditions')
            definitions[metric] = definition
        for row in rows:
            values = {metric: field(row['raw'], definitions[metric].get('field', definitions[metric].get('source_field', ''))) for metric in metric_ids}
            if any(not isinstance(v, (int, float)) or isinstance(v, bool) for v in values.values()):
                exclusions += 1
                continue
            result.append({'sample_id': row['id'], 'artifact_id': identity, 'item': row.get('item'), **values})
    return {'points': result, 'definitions': definitions, 'excluded': exclusions, 'bounded': truncated,
            'coverage': {'observed': len(result), 'excluded': exclusions, 'unknown': truncated},
            'references': validate_references(slug, [{'kind':'artifact','id':i} for i in identities])}


def parent(slug, identity):
    child = sample(slug, identity)
    artifact = store.read(slug, 'artifact', child['artifact_id'])
    parent_id = child.get('parent_record_id')
    lineage = artifact.get('provenance', {}).get('parent') or {}
    if not parent_id or not lineage.get('execution_id') or not lineage.get('variant_id'):
        return {'available': False, 'parent_record_id': parent_id, 'reason': 'Exact parent execution and variant provenance is not recorded'}
    candidates = [a for a in store.listing(slug, 'artifact') if a.get('execution_id') == lineage['execution_id'] and a.get('variant_id') == lineage['variant_id']]
    matches = []
    for candidate in candidates:
        rows, _, truncated, _ = _scan(slug, candidate)
        matches.extend(r for r in rows if r.get('record_id') == parent_id)
    if len(matches) != 1:
        return {'available': False, 'parent_record_id': parent_id, 'reason': 'Exact parent is unavailable or ambiguous within its producing scope', 'candidate_artifacts': [reference(a) for a in candidates]}
    return {'available': True, 'parent_record_id': parent_id, 'sample': matches[0]}


def _field_values(value, path):
    parts = path.split('.')
    head = parts[0]; many = head.endswith('[]'); head = head[:-2] if many else head
    current = value.get(head) if isinstance(value, dict) else None
    if current is None:
        return []
    values = current if many and isinstance(current, list) else [current]
    if len(parts) == 1:
        return values
    return [v for item in values for v in _field_values(item, '.'.join(parts[1:]))]


def check_analysis_metrics(slug, artifacts, metric_ids, definitions=None):
    """Reject absent collector fields before a reviewed analysis can dispatch."""
    import fnmatch
    for artifact in artifacts:
        declared = definitions if definitions is not None else artifact.get('metric_definitions', {})
        for identity in metric_ids:
            definition = declared.get(identity)
            if not definition:
                raise WorkspaceError('Metric is not declared: ' + str(identity))
            path = definition.get('field', definition.get('source_field'))
            source = definition.get('source')
            if not path or not source:
                continue  # Non-file collectors are checked by the plan compiler.
            observed = 0; missing = 0; scanned = 0
            for member in artifact.get('files', []):
                if not fnmatch.fnmatch(member['path'], '*/' + source) and not fnmatch.fnmatch(member['path'], source):
                    continue
                filename, _ = files.member_path(slug, artifact, member['path'])
                scanned += filename.stat().st_size
                if scanned > SCAN_BYTES:
                    raise WorkspaceError('Metric input check exceeds bounded scan; provide a declared project completeness/field check before analysis')
                with filename.open('rb') as stream:
                    records = stream if filename.suffix == '.jsonl' else [stream.read()]
                    for raw in records:
                        try:
                            values = _field_values(files.strict_json(raw), path)
                        except (ValueError, TypeError):
                            values = []
                        observed += len(values); missing += int(not values)
            if not observed or missing and definition.get('missing') == 'error':
                raise Conflict('Metric ' + str(identity) + ' requires collector field ' + str(path) + ' in artifact ' + artifact['id'] + '. Create an explicit collection plan for the missing requirement.')
