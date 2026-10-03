"""Strict composition feature v1, lowered into the existing workflow compiler."""
from __future__ import annotations

import copy
import re
from pathlib import PurePosixPath

from controller.workspace_connection import digest

FEATURE = 'composition'
VERSION = 1
WORKFLOW = '__composition__'
IDENTITY = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}$')


def feature_errors(manifest):
    features = manifest.get('required_features', {})
    if not isinstance(features, dict):
        return [{'field': 'required_features', 'message': 'Required features must map names to exact supported versions'}]
    return [{'field': 'required_features.' + key, 'message': 'Unsupported required feature version: ' + str(version)}
            for key, version in features.items() if key != FEATURE or version != VERSION]


def capability(manifest):
    enabled = manifest.get('required_features', {}).get(FEATURE) == VERSION if isinstance(manifest.get('required_features', {}), dict) else False
    return {'id': FEATURE, 'declared_version': VERSION if enabled else None, 'supported_version': VERSION,
            'availability': 'available' if enabled and not feature_errors(manifest) else 'unavailable',
            'reason': None if enabled else 'Declare required_features.composition=1 and versioned typed operation ports',
            'dependencies': ['typed operation ports', 'bounded isolated outputs'], 'scope': 'project'}


def prepare(manifest, draft, artifacts=None):
    """Validate a graph without changing the stored graph or any source bytes."""
    if draft.get('workflow') != WORKFLOW:
        return manifest, draft, []
    manifest, draft = copy.deepcopy(manifest), copy.deepcopy(draft)
    errors = feature_errors(manifest)
    def issue(field, message):
        errors.append({'field': 'graph.' + field, 'message': message})
    if capability(manifest)['availability'] != 'available':
        issue('capability', 'Composition requires the supported composition feature version 1')
    graph = draft.get('graph', {})
    nodes, edges = graph.get('nodes', []), graph.get('edges', [])
    if not isinstance(nodes, list) or not nodes or not isinstance(edges, list):
        issue('nodes', 'Add at least one declared operation and a list of explicit connections')
        return manifest, draft, errors
    ids = [n.get('id') for n in nodes if isinstance(n, dict)]
    if len(ids) != len(nodes) or any(not isinstance(i, str) or not IDENTITY.fullmatch(i) for i in ids) or len(set(ids)) != len(ids):
        issue('nodes', 'Node IDs must be unique stable identifiers')
        return manifest, draft, errors
    definitions, stages = {}, []
    for node in nodes:
        identity = node['id']
        operation = manifest.get('operations', {}).get(node.get('operation'))
        if not isinstance(operation, dict):
            issue(identity, 'Operation is no longer declared: ' + str(node.get('operation')))
            continue
        definitions[identity] = operation
        if node.get('location', operation.get('location')) not in operation.get('allowed_locations', [operation.get('location')]):
            issue(identity + '.location', 'Operation is not declared for this execution location')
        if node.get('operation_version') != operation.get('version'):
            issue(identity, 'Operation version is unavailable; retain this node and update its declaration')
        if node.get('scope', 'per_variant') not in ('per_variant', 'shared', 'reduce_selected'):
            issue(identity + '.scope', 'Select per_variant, shared, or reduce_selected scope')
        if node.get('purpose', 'experiment') not in ('experiment', 'smoke-test'):
            issue(identity + '.purpose', 'Select an explicit experiment or smoke-test purpose')
        if operation.get('write_scope') != 'output_dir':
            issue(identity + '.write_scope', 'Composable operations must declare write_scope=output_dir; shared mutable writes require a project adapter')
        if not isinstance(operation.get('timeout_seconds'), int) or not 1 <= operation['timeout_seconds'] <= 86400:
            issue(identity + '.timeout', 'Declare a bounded timeout_seconds from 1 to 86400')
        for direction in ('input_ports', 'output_ports'):
            if not isinstance(operation.get(direction, {}), dict):
                issue(identity + '.' + direction, 'Typed ports must be objects keyed by port IDs')
                continue
            for port_id, port in operation.get(direction, {}).items():
                if not isinstance(port, dict) or not all(port.get(key) for key in ('schema', 'version')) or port.get('cardinality', 'one') not in ('one', 'many'):
                    issue(identity + '.' + port_id, 'Port requires schema, version, and one or many cardinality')
        outputs = [{'id': port_id, **port} for port_id, port in operation.get('output_ports', {}).items()]
        if any(not port.get('path') or PurePosixPath(str(port.get('path'))).is_absolute() or '..' in PurePosixPath(str(port.get('path'))).parts for port in outputs):
            issue(identity + '.outputs', 'Output ports require a scoped relative path')
        from controller.workspace_planner import _typed
        for key, value in node.get('parameters', {}).items():
            spec = manifest.get('parameters', {}).get(key)
            problem = _typed(value, spec) if spec else 'Unknown parameter override'
            if problem:
                issue(identity + '.parameters.' + key, problem)
        stage = {key: copy.deepcopy(value) for key, value in node.items() if key in ('id', 'operation', 'purpose', 'scope', 'parameters', 'resources', 'location')}
        stage.update(depends_on=[], inputs=[], outputs=outputs)
        for key in ('fetch_operation', 'check_operation', 'completion'):
            if key in operation:
                stage[key] = operation[key]
        stages.append(stage)
    by_id = {s['id']: s for s in stages}
    incoming = {}
    artifact_map = {a['id']: a for a in artifacts or []}
    selected_artifacts = []
    for edge in edges:
        if not isinstance(edge, dict):
            issue('edges', 'Every connection must be a typed object')
            continue
        dest, port_id = edge.get('to_node'), edge.get('input')
        field = str(dest) + '.' + str(port_id)
        target = definitions.get(dest, {}).get('input_ports', {}).get(port_id)
        if not isinstance(target, dict) or dest not in by_id:
            issue(field, 'Target input port is missing')
            continue
        incoming.setdefault((dest, port_id), []).append(edge)
        if edge.get('absent'):
            if target.get('required', True):
                issue(field, 'Required port cannot bind absence')
            continue
        source_id = edge.get('from_node')
        output = definitions.get(source_id, {}).get('output_ports', {}).get(edge.get('output'))
        artifact = artifact_map.get(edge.get('artifact_id'))
        if artifact:
            output = artifact
            if not artifact.get('complete', artifact.get('completeness') == 'complete'):
                issue(field, 'Saved artifact lacks required completeness evidence')
            if not artifact.get('source_digest') or not artifact.get('execution_id'):
                issue(field, 'Saved artifact lacks source and execution provenance')
            if edge.get('artifact_version') not in (None, artifact.get('version')):
                issue(field, 'Saved artifact version changed')
            selected_artifacts.append(artifact['id'])
            by_id[dest].setdefault('artifact_inputs', []).append({'input': port_id, 'artifact_id': artifact['id']})
        elif source_id in by_id and output:
            if source_id == dest:
                issue(field, 'A node cannot depend on itself')
            by_id[dest]['depends_on'].append(source_id)
            by_id[dest]['inputs'].append({'from_stage': source_id, 'output': edge['output'], 'input_port': port_id, 'schema': output['schema'], 'version': output['version']})
            source_scope, target_scope = by_id[source_id].get('scope', 'per_variant'), by_id[dest].get('scope', 'per_variant')
            if target_scope == 'shared' and source_scope != 'shared':
                issue(field, 'Shared nodes cannot consume variant-dependent inputs')
            if target_scope == 'reduce_selected' and target.get('cardinality', 'one') != 'many':
                issue(field, 'Selected-input reduction requires a many-input port')
            if source_scope == 'reduce_selected' and target_scope == 'per_variant':
                issue(field, 'Cross-variant reducer outputs require a shared or reducer consumer')
        else:
            issue(field, 'Select an existing output port or indexed same-project artifact')
            continue
        if target.get('cardinality', 'one') == 'one' and output.get('cardinality', 'one') != 'one':
            issue(field, 'A many-output port cannot bind a one-input port')
        versions = target.get('compatible_versions', [target.get('version')])
        if output.get('schema') != target.get('schema') or output.get('version') not in versions:
            issue(field, 'Artifact schema/version is incompatible with the input port')
        if output.get('unit') != target.get('unit'):
            issue(field, 'Incompatible unit; add an explicit declared conversion operation')
        purpose = artifact.get('purpose') if artifact else by_id[source_id].get('purpose', 'experiment')
        if purpose not in target.get('purposes', ['experiment']):
            issue(field, 'Artifact purpose cannot satisfy this input; smoke evidence cannot replace a full corpus')
        for key in target.get('required_provenance', []):
            if artifact and not artifact.get(key):
                issue(field, 'Saved artifact lacks required provenance: ' + key)
    for identity, operation in definitions.items():
        for port_id, port in operation.get('input_ports', {}).items():
            bound = incoming.get((identity, port_id), [])
            if not bound:
                issue(identity + '.' + port_id, 'Input is unbound; explicitly connect an artifact or permitted absence')
            if port.get('cardinality', 'one') == 'one' and len(bound) > 1:
                issue(identity + '.' + port_id, 'One-input port cannot consume multiple bindings')
            if len(bound) > min(100, manifest.get('composition_limits', {}).get('artifacts_per_port', 100)):
                issue(identity + '.' + port_id, 'Input exceeds the reviewed artifact limit')
    pending = {s['id']: set(s['depends_on']) for s in stages}
    while pending:
        ready = [key for key, dependencies in pending.items() if not dependencies.intersection(pending)]
        if not ready:
            issue('edges', 'Graph contains a cycle')
            break
        for key in ready:
            del pending[key]
    used_parameters = {argument['param'] for operation in definitions.values() for argument in operation.get('argv', []) if isinstance(argument, dict) and 'param' in argument}
    used_parameters.update(draft.get('variant_parameters', {}))
    parameter_ids = [key for key in manifest.get('parameters', {}) if key in used_parameters]
    manifest.setdefault('workflows', {})[WORKFLOW] = {'parameters': parameter_ids, 'stages': stages, 'metrics': list(manifest.get('metrics', {}))}
    draft['parameters'] = {key: value for key, value in draft.get('parameters', {}).items() if key in used_parameters}
    draft['composition_digest'] = digest(graph)
    draft['stages'] = [s['id'] for s in stages]
    draft['existing_artifacts'] = {**draft.get('existing_artifacts', {}), **{'composition-' + str(i): identity for i, identity in enumerate(selected_artifacts)}}
    for measurement in draft.get('metrics', []):
        metric_id = measurement if isinstance(measurement, str) else measurement.get('id')
        metric = manifest.get('metrics', {}).get(metric_id, {})
        collector = metric.get('collector')
        if collector and collector not in [n.get('operation') for n in nodes]:
            issue('metrics.' + str(metric_id), 'Measurement requires an explicitly added collector stage: ' + str(collector))
    if not errors:
        from controller.workspace_planner import expand_variants
        variants, expansion_errors = expand_variants(manifest, draft)
        errors.extend(expansion_errors)
        count = len([v for v in variants if not v['excluded']])
        stage_count = sum(1 if s.get('scope') in ('shared', 'reduce_selected') else count for s in stages)
        limits = manifest.get('composition_limits', {})
        if count > min(1000, limits.get('variants', 1000)):
            issue('variants', 'Composition exceeds the included variant limit')
        if stage_count > min(5000, limits.get('stages', 5000)):
            issue('nodes', 'Composition exceeds the expanded stage limit')
        for stage in stages:
            incoming_counts = {}
            for binding in stage.get('artifact_inputs', []):
                incoming_counts[binding['input']] = incoming_counts.get(binding['input'], 0) + 1
            for binding in stage['inputs']:
                parent = by_id[binding['from_stage']]
                cardinality = count if stage.get('scope') == 'reduce_selected' and parent.get('scope', 'per_variant') == 'per_variant' else 1
                port = binding['input_port']
                incoming_counts[port] = incoming_counts.get(port, 0) + cardinality
            for port, cardinality in incoming_counts.items():
                if cardinality > min(100, limits.get('artifacts_per_port', 100)):
                    issue(stage['id'] + '.' + port, 'Expanded reducer input exceeds the artifact limit across all bindings')
    return manifest, draft, errors


def supported(manifest):
    return capability(manifest)["availability"] == "available"
