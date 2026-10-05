"""Shared projections for the additive workspace services (storage stays version 1)."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone


def version_token(entity):
    """Use explicit entity versions; legacy records use a stable content token."""
    if isinstance(entity.get('version'), int) and not isinstance(entity['version'], bool):
        return entity['version']
    value = {key: item for key, item in entity.items() if key != 'response_metadata'}
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def observation(source, observed_at, stale_after=60, availability='available'):
    """Polling never refreshes the timestamp of the underlying observation."""
    state = 'unavailable'
    if isinstance(stale_after, bool) or not isinstance(stale_after, (int, float)) or not 0 <= stale_after <= 365 * 86400 or not math.isfinite(stale_after):
        return dict(source=source, observed_at=observed_at, stale_after=None,
                    availability='unknown', state=state)
    if availability == 'available' and observed_at:
        try:
            stamp = datetime.fromisoformat(observed_at.replace('Z', '+00:00'))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            state = 'fresh' if (datetime.now(timezone.utc) - stamp).total_seconds() <= stale_after else 'stale'
        except (ValueError, TypeError, AttributeError):
            state = 'unavailable'
    return dict(source=source, observed_at=observed_at, stale_after=stale_after,
                availability=availability, state=state)


def capability(supported, reason=None, *, revision='1', scopes=(), fields=()):
    return dict(supported=bool(supported), reason=reason, revision=revision,
                scopes=list(scopes), fields=list(fields))


_OPAQUE_FIELDS = {'raw', 'structured', 'records', 'rows', 'provenance', 'parameters',
                  'config', 'manifest', 'definitions', 'metric_definitions', 'evidence',
                  'turns', 'recorded_fields', 'result_schema'}


def _response_digest(value):
    # Metadata must not reinterpret scientific payload values. Scientific parsers
    # separately enforce the browser JSON transport contract.
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _response_basis(value):
    """Exclude projection clocks, while retaining workload facts and identities."""
    if isinstance(value, list):
        return [_response_basis(item) for item in value]
    if not isinstance(value, dict):
        return value
    clock_keys = {'response_metadata', 'observed_at', 'checked_at', 'expires_at',
                  'stale_after', 'freshness', 'read_at', 'age_seconds'}
    is_observation = 'observed_at' in value and 'source' in value
    return {key: item if key in _OPAQUE_FIELDS else _response_basis(item) for key, item in value.items()
            if key not in clock_keys and not (is_observation and key == 'state')}


def response_metadata(payload, route, read_at):
    """Project only returned facts; do not probe, scan, or write on a read route.

    Entity metadata uses JSON pointers so repeated IDs in separate domains do
    not collide. Artifact schema versions remain distinct from entity versions.
    Unknown source observations stay unknown; the local read is a separate fact.
    """
    entities, observations, revisions = {}, {}, set()
    observations['local_read'] = observation('controller response projection', read_at)

    def source_revision(value):
        source = value.get('source')
        candidates = (value.get('source_revision'), value.get('source_digest'), value.get('declaration_digest'),
                      value.get('digest') if isinstance(value.get('manifest'), dict) else None,
                      source.get('digest') if isinstance(source, dict) else None)
        return next((candidate for candidate in candidates if isinstance(candidate, str) and candidate), 'unknown')

    def observe(key, value, source):
        stamp = value.get('observed_at') or value.get('checked_at')
        threshold = value.get('stale_after', 60)
        if stamp and value.get('expires_at'):
            try:
                threshold = max(0, (datetime.fromisoformat(value['expires_at'].replace('Z', '+00:00')) -
                                    datetime.fromisoformat(stamp.replace('Z', '+00:00'))).total_seconds())
            except (ValueError, TypeError, AttributeError):
                pass
        available = value.get('availability', 'available')
        if value.get('status') in ('unknown', 'unavailable', 'failed') or value.get('error'):
            available = 'unavailable'
        # Copy locations describe where bytes exist, not whether an observation exists.
        if available in ('local', 'remote', 'both'):
            available = 'available'
        if not stamp and available == 'available':
            available = 'unknown'
        observations[key] = observation(source, stamp, threshold, available)

    def visit(value, pointer=''):
        if isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, pointer + '/' + str(index))
            return
        if not isinstance(value, dict):
            return
        revision = source_revision(value)
        if revision != 'unknown':
            revisions.add(str(revision))
        if value.get('id'):
            artifact = 'schema' in value and ('files' in value or 'complete' in value)
            entity_version = (value.get('content_version') or value.get('digest')) if artifact else value.get('version')
            if entity_version is None:
                entity_version = _response_digest(_response_basis({k: v for k, v in value.items() if k != 'version'}))
            entities[pointer or '/'] = {'id': value['id'], 'version': entity_version,
                                       'source_revision': revision}
            if artifact:
                observe('artifacts' + pointer, value, 'artifact index')
        if 'observed_at' in value and isinstance(value.get('source'), str):
            observe(pointer or '/facts', value, value['source'])
        if 'scheduler_observation' in value:
            observe('scheduler' + pointer, value.get('scheduler_observation') or {}, 'scheduler')
        for key, item in value.items():
            if key == 'response_metadata' or key in _OPAQUE_FIELDS:
                continue
            escaped = str(key).replace('~', '~0').replace('/', '~1')
            visit(item, pointer + '/' + escaped)

    visit(payload)
    if route.split('/')[0] == 'files':
        observations['filesystem'] = observation('controller filesystem read', payload.get('observed_at') or read_at)
    if route.split('/')[0] in ('results', 'artifacts') and not any(k.startswith('artifacts') for k in observations):
        observations['artifacts'] = observation('artifact index', None, availability='unknown')
    if isinstance(payload.get('capabilities'), (list, dict)):
        observations['capabilities'] = observation('returned capability declaration', read_at)
    revision = source_revision(payload)
    if revision == 'unknown' and len(revisions) == 1:
        revision = next(iter(revisions))
    response_version = _response_digest(_response_basis(payload))
    return {'version': response_version, 'source_revision': revision,
            'source_revisions': sorted(revisions), 'read_at': read_at,
            'observations': observations, 'entities': entities}
