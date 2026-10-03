"""Immutable artifact copies, bounded read views, and reviewed member transfers.

The workspace record store remains authoritative. Reads never invoke an adapter.
"""
from __future__ import annotations

import copy
import base64
import struct
import csv
import hashlib
import io
import json
import mimetypes
import os
from pathlib import Path
import shutil
import stat
import subprocess
import time
import threading

from controller import workspace_store as store
from controller.workspace_store import WorkspaceError, Conflict, Missing

MAX_BYTES = 256 * 1024
MAX_LINES = 2000
MAX_RECORDS = 100
MAX_DOWNLOAD = 16 * 1024 * 1024
_SECRET = {'.git', '.env', '.ssh', '.aws', '.gnupg', 'id_rsa', 'id_ed25519', 'credentials', '__pycache__'}
_TRANSFER_THREADS = {}
_TRANSFER_LOCK = threading.Lock()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def strict_json(value):
    """Scientific JSON must remain valid in the browser response envelope."""
    import math
    def reject_constant(token):
        raise ValueError('Non-finite JSON constant is unsupported: ' + token)
    def finite_float(token):
        number = float(token)
        if not math.isfinite(number):
            raise ValueError('JSON number exceeds finite numeric range: ' + token)
        return number
    return json.loads(value, parse_constant=reject_constant, parse_float=finite_float)


def _root(slug):
    from controller.workspace import project
    return Path(project(slug)['path']).resolve()


def _manifest(slug):
    from controller.workspace_connection import load_connection
    return load_connection(_root(slug), resolve_choices=False).get('manifest') or {}


def _excluded(relative, manifest):
    path = Path(relative)
    protected = manifest.get('environment', {}).get('secret_paths', [])
    return (any(p in _SECRET or p.startswith('.env.') and p != '.env.example' or p.endswith(('.pem', '.key')) for p in path.parts)
            or any(str(path) == x or str(path).startswith(str(x).rstrip('/') + '/') for x in protected))


def authorize_resolved(slug, path):
    project_root = _root(slug)
    resolved = path.resolve()
    if not resolved.is_relative_to(project_root) or _excluded(resolved.relative_to(project_root), _manifest(slug)):
        raise WorkspaceError('Resolved path is excluded from project browsing')
    return resolved


def safe_path(root, relative, *, manifest=None):
    rel = Path(relative or '.')
    if rel.is_absolute() or '..' in rel.parts or _excluded(rel, manifest or {}):
        raise WorkspaceError('Path is excluded or outside the allowed root')
    path = (root / rel).resolve()
    if not path.is_relative_to(root.resolve()):
        raise WorkspaceError('Symbolic link escapes the allowed root')
    if _excluded(path.relative_to(root.resolve()), manifest or {}):
        raise WorkspaceError('Symbolic link resolves to an excluded path')
    if path.exists() and not (path.is_file() or path.is_dir()):
        raise WorkspaceError('Device files and sockets cannot be browsed')
    return path


def preserve_artifact(slug, artifact):
    """Keep each content version and return its stable reference to the worker."""
    value = copy.deepcopy(artifact)
    root = _root(slug)
    logical = value.get('logical_id', value['id'])
    content = value.get('digest') or fingerprint(value.get('files', []))
    previous = [a for a in store.listing(slug, 'artifact') if a.get('logical_id', a['id']) == logical]
    matching = next((a for a in previous if a.get('content_version', a.get('digest')) == content and a.get('frozen_path') and all(f.get('frozen_path') for f in a.get('files', []))), None)
    if matching:
        observed = {'observed_at': store.now(), 'complete': bool(value.get('complete')), 'evidence': value.get('evidence'), 'errors': value.get('errors', [])}
        matching.setdefault('completeness_history', [{'observed_at': matching.get('observed_at', matching.get('created_at')), 'complete': bool(matching.get('complete')), 'evidence': matching.get('evidence'), 'errors': matching.get('errors', [])}]).append(observed)
        matching.update(complete=observed['complete'], completeness='complete' if observed['complete'] else 'partial', evidence=observed['evidence'], errors=observed['errors'], observed_at=observed['observed_at'])
        with store.transaction(slug) as con:
            store.put(con, 'artifact', matching)
        return matching
    same = next((a for a in previous if a.get('content_version', a.get('digest')) == content), None)
    identity = same['id'] if same else logical if not previous else logical[:80] + '-' + content[:16]
    value.update(id=identity, logical_id=logical, content_version=content, project=slug,
                 integrity='checked', availability='local' if value.get('files') else 'unavailable',
                 completeness='complete' if value.get('complete') else 'partial',
                 observed_at=store.now(), supersedes=previous[0]['id'] if previous else None)
    original = safe_path(root, value['path'])
    destination = safe_path(root, str(Path('.unity-workspace/artifacts') / identity / content))
    destination.mkdir(parents=True, exist_ok=True)
    is_directory = original.is_dir() or any(Path(f['path']) != Path(value['path']) for f in value.get('files', []))
    base = original if is_directory else original.parent
    frozen_files = []
    for member in value.get('files', []):
        source = safe_path(root, member.get('frozen_path', member['path']))
        original_member = safe_path(root, member['path'])
        if not source.is_file() or not original_member.is_relative_to(base):
            raise Conflict('Indexed artifact member is missing or outside its declared output')
        target = safe_path(destination, str(original_member.relative_to(base)))
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + '.tmp-' + store.new_id('copy'))
        shutil.copyfile(source, temporary)
        if digest(temporary) != member['sha256']:
            temporary.unlink(missing_ok=True)
            raise Conflict('Artifact changed while creating its immutable version')
        os.replace(temporary, target)
        st = target.stat()
        original_stat = original_member.stat() if original_member.exists() else None
        frozen_files.append({**member, 'frozen_path': str(target.relative_to(root)), 'checked_stat': [st.st_ino, st.st_size, st.st_mtime_ns],
                             'source_stat': [original_stat.st_ino, original_stat.st_size, original_stat.st_mtime_ns] if original_stat else None})
    value['files'] = frozen_files
    definition = _manifest(slug)
    plan_id = value.get('plan_id')
    if not plan_id and value.get('execution_id'):
        try:
            plan_id = store.read(slug, 'execution', value['execution_id']).get('plan_id')
        except Missing:
            pass
    frozen_manifest = root / '.unity-workspace/plans' / str(plan_id) / 'source/unityHPC/project.json'
    if frozen_manifest.is_file():
        definition = json.loads(frozen_manifest.read_text())
    value['result_schema'] = definition.get('result_schemas', {}).get(value.get('schema'), {})
    value['metric_definitions'] = definition.get('metrics', {})
    value['frozen_path'] = str((destination if is_directory else destination / original.name).relative_to(root))
    value['locations'] = [{'host': 'controller', 'path': value['frozen_path'], 'availability': value['availability'],
                           'version': content, 'observed_at': value['observed_at']}]
    with store.transaction(slug) as con:
        store.put(con, 'artifact', value)
    return value


def freeze_inputs(slug, identities):
    values = []
    for identity in identities:
        value = store.read(slug, 'artifact', identity)
        if value.get('remote_files') and len(value.get('files', [])) != len(value['remote_files']):
            raise Conflict('Required input bytes are only partly available; retrieve remaining members first')
        if not value.get('complete') or value.get('purpose') != 'experiment':
            raise Conflict('New analysis requires complete research artifacts')
        if not value.get('frozen_path') or any(not f.get('frozen_path') for f in value.get('files', [])):
            value.pop('frozen_path', None)
            value = preserve_artifact(slug, value)
        for member in value.get('files', []):
            path = safe_path(_root(slug), member['frozen_path'])
            if not path.is_file() or digest(path) != member['sha256']:
                raise Conflict('Saved input bytes changed or are unavailable: ' + identity)
        values.append(value)
    return values


def member_path(slug, artifact, relative):
    member = next((f for f in artifact.get('files', []) if f['path'] == relative or f.get('frozen_path') == relative), None)
    if member is None:
        raise Missing('This file is not indexed for the selected artifact version')
    path = authorize_resolved(slug, safe_path(_root(slug), member.get('frozen_path', member['path'])))
    if not path.is_file():
        raise Missing('Artifact version is unavailable on the controller host')
    st = path.stat()
    checked = member.get('checked_stat')
    if checked:
        if checked != [st.st_ino, st.st_size, st.st_mtime_ns]:
            raise Conflict('Artifact input changed since indexing')
    elif st.st_size > MAX_DOWNLOAD:
        raise WorkspaceError('Legacy file exceeds the checked-read budget; freeze and validate it before bounded browsing')
    elif digest(path) != member['sha256']:
        raise Conflict('Artifact input changed since indexing')
    return path, member


def download(slug, identity, relative):
    artifact = store.read(slug, 'artifact', identity)
    path, _ = member_path(slug, artifact, relative)
    if path.stat().st_size > MAX_DOWNLOAD:
        raise WorkspaceError('Browser download is limited to 16 MiB; use the known controller path')
    return path.read_bytes(), path.suffix


def roots(slug):
    root = _root(slug)
    result = []
    for identity, kind, relative in [('source', 'Project source', '.'), ('bundles', 'Execution bundles', '.unity-workspace/plans'),
                                    ('outputs', 'Outputs', '.unity-workspace/outputs'), ('versions', 'Saved artifact versions', '.unity-workspace/artifacts'),
                                    ('reports', 'Reports and plots', '.unity-workspace/artifacts'),
                                    ('logs', 'Scheduler logs', '_results'), ('controller-logs', 'Controller activity logs', '.unity-workspace/receipts')]:
        result.append(dict(id=identity, project=slug, kind=kind, host='controller', ownership='project' if identity == 'source' else 'workspace',
                           path=str(root / relative), relative_path=relative, actions=['browse', 'preview', 'download']))
    return {'roots': result, 'observed_at': store.now(), 'source': 'controller filesystem', 'version': 1}


def _browse_root(slug, identity):
    entry = next((r for r in roots(slug)['roots'] if r['id'] == identity), None)
    if entry is None:
        raise Missing('Unknown browse root')
    return safe_path(_root(slug), entry['relative_path']), entry


def browse(slug, query):
    root, entry = _browse_root(slug, query.get('root', 'source'))
    relative = query.get('path', '')
    manifest = _manifest(slug)
    project_rel = str(Path(entry['relative_path']) / relative)
    if _excluded(project_rel, manifest):
        raise WorkspaceError('Path is excluded from project browsing')
    directory = authorize_resolved(slug, safe_path(root, relative, manifest=manifest))
    if not directory.is_dir() and entry['id'] != 'outputs':
        raise Missing('Directory is unavailable')
    values = []
    artifact_records = store.listing(slug, 'artifact')
    executions = store.listing(slug, 'execution') if entry['id'] in ('logs', 'controller-logs') else []
    for path in sorted(directory.iterdir() if directory.is_dir() else [], key=lambda p: (not p.is_dir(), p.name.lower())):
        rel = str(path.relative_to(root))
        if _excluded(str(Path(entry['relative_path']) / rel), manifest):
            continue
        try:
            resolved = authorize_resolved(slug, safe_path(root, rel, manifest=manifest))
            st = resolved.stat()
        except (WorkspaceError, OSError):
            values.append(dict(path=rel, name=path.name, kind='symlink' if path.is_symlink() else 'unavailable', availability='unavailable', reason='Target is outside the allowed root or unavailable'))
            continue
        if query.get('name') and query['name'].lower() not in path.name.lower():
            continue
        project_relative = str(resolved.relative_to(_root(slug)))
        linked = [a for a in artifact_records if any(str(f.get('frozen_path', f['path'])) == project_relative or str(f.get('frozen_path', f['path'])).startswith(project_relative.rstrip('/') + '/') or f['path'] == project_relative or f['path'].startswith(project_relative.rstrip('/') + '/') for f in a.get('files', []))]
        producer = linked[0] if len(linked) == 1 else {}
        row = dict(path=rel, name=path.name, kind='directory' if resolved.is_dir() else 'file', size=st.st_size if resolved.is_file() else None,
                   modified_at=st.st_mtime, version=fingerprint([st.st_ino, st.st_size, st.st_mtime_ns]), availability='local', integrity=producer.get('integrity', 'unchecked'),
                   execution_ids=sorted({a['execution_id'] for a in linked if a.get('execution_id')}), variant_ids=sorted({a['variant_id'] for a in linked if a.get('variant_id')}),
                   stage_ids=sorted({a['stage_id'] for a in linked if a.get('stage_id')}), purposes=sorted({a.get('purpose', 'unclassified') for a in linked}), artifact_ids=[a['id'] for a in linked])
        for execution in executions:
            for stage in execution.get('stages', []):
                if (entry['id'] == 'logs' and rel.startswith(execution.get('campaign', '') + '/') and any(('-' + str(job) + '.') in path.name for job in stage.get('job_ids', []))) or (entry['id'] == 'controller-logs' and any(path.name.startswith(a['id'] + '.') for a in stage.get('attempts', []))):
                    row.update(execution_ids=[execution['id']],variant_ids=[stage.get('variant_id')],stage_ids=[stage['id']],purposes=[stage.get('purpose','unclassified')])
        changed = any((f.get('checked_stat') and f.get('frozen_path') == project_relative and f['checked_stat'] != [st.st_ino,st.st_size,st.st_mtime_ns]) or (f.get('source_stat') and f['path'] == project_relative and f['source_stat'] != [st.st_ino,st.st_size,st.st_mtime_ns]) for a in linked for f in a.get('files', []))
        if changed: row['integrity'] = 'changed'
        if query.get('kind') and row['kind'] != query['kind']: continue
        if query.get('location') and query['location'] not in ('all', row['availability']): continue
        if query.get('integrity') and row['integrity'] != query['integrity']: continue
        if query.get('changed') == 'true' and not changed: continue
        if any(query.get(k) and query[k] not in row.get(k + '_ids', []) for k in ('execution','variant','stage')): continue
        if query.get('purpose') and query['purpose'] not in row['purposes']: continue
        if entry['id'] == 'reports' and not resolved.is_dir() and path.suffix.lower() not in ('.md','.html','.svg','.png','.pdf','.json','.csv','.tsv'): continue
        values.append(row)
    if entry['id'] == 'outputs':
        existing_paths = {row['path'] for row in values}
        for artifact in artifact_records:
            if artifact.get('availability') not in ('remote','both'):
                continue
            for member in artifact.get('remote_files', []):
                remote = Path(member['path'])
                try: scoped = remote.relative_to(Path(entry['relative_path']))
                except ValueError: continue
                if '..' in scoped.parts: continue
                try: rest = scoped.relative_to(Path(relative or '.'))
                except ValueError: continue
                if not rest.parts: continue
                virtual = str(Path(relative) / rest.parts[0])
                if virtual in existing_paths: continue
                kind = 'directory' if len(rest.parts)>1 else 'file'
                row = dict(path=virtual,name=rest.parts[0],kind=kind,size=member.get('size') if kind=='file' else None,availability='remote',integrity='unchecked',
                           execution_ids=[artifact.get('execution_id')] if artifact.get('execution_id') else [],variant_ids=[artifact.get('variant_id')] if artifact.get('variant_id') else [],
                           stage_ids=[artifact.get('stage_id')] if artifact.get('stage_id') else [],purposes=[artifact.get('purpose','unclassified')],artifact_ids=[artifact['id']])
                if query.get('name') and query['name'].lower() not in row['name'].lower(): continue
                if query.get('kind') and query['kind']!=kind: continue
                if query.get('location') and query['location'] not in ('all','remote'): continue
                if query.get('integrity') and query['integrity']!='unchecked': continue
                if query.get('changed')=='true': continue
                if any(query.get(k) and query[k] not in row[k+'_ids'] for k in ('execution','variant','stage')): continue
                if query.get('purpose') and query['purpose'] not in row['purposes']: continue
                values.append(row);existing_paths.add(virtual)
        values.sort(key=lambda row:(row['kind']!='directory',row['name'].lower()))
    token = fingerprint(values)
    if query.get('version') and query['version'] != token:
        raise Conflict('Directory changed; refresh the listing before continuing', current_version=token, expected_version=query['version'])
    offset = max(0, int(query.get('offset') or 0)); limit = min(200, max(1, int(query.get('limit') or 100)))
    return dict(root=entry, path=relative, entries=values[offset:offset+limit], version=token, total=len(values),
                next_offset=offset+limit if offset+limit < len(values) else None, observed_at=store.now(), source='controller filesystem')


def preview(slug, query):
    if query.get('artifact'):
        artifact = store.read(slug, 'artifact', query['artifact'])
        path, member = member_path(slug, artifact, query.get('path'))
        token = member['sha256']
    else:
        root, entry = _browse_root(slug, query.get('root', 'source'))
        if _excluded(str(Path(entry['relative_path']) / query.get('path', '')), _manifest(slug)):
            raise WorkspaceError('Path is excluded from project browsing')
        path = authorize_resolved(slug, safe_path(root, query.get('path'), manifest=_manifest(slug)))
        if not path.is_file():
            raise Missing('Preview file is unavailable')
        st = path.stat(); token = fingerprint([st.st_ino, st.st_size, st.st_mtime_ns])
    if query.get('version') and token != query['version']:
        raise Conflict('File changed; refresh to inspect its new version', current_version=token, expected_version=query['version'])
    start = path.stat(); offset = max(0, int(query.get('offset') or 0)); budget = min(MAX_BYTES, max(1, int(query.get('limit') or MAX_BYTES)))
    with path.open('rb') as stream:
        stream.seek(offset); data = stream.read(budget)
    final = path.stat()
    if (start.st_ino, start.st_size, start.st_mtime_ns) != (final.st_ino, final.st_size, final.st_mtime_ns):
        raise Conflict('File changed during preview')
    if path.suffix.lower() in ('.jpg','.jpeg','.gif','.webp','.bmp','.pdf'):
        return {'version':token,'kind':'binary','reason':'This format has no bounded rich-preview capability. Download remains available.','text':'','size':start.st_size,'offset':offset,'loaded_bytes':0,'truncated':False}
    if path.suffix.lower() == '.png':
        if start.st_size > 4 * 1024 * 1024:
            return {'version':token,'kind':'binary','reason':'PNG exceeds the 4 MiB image preview budget. Download remains available.','text':'','size':start.st_size,'offset':0,'loaded_bytes':0,'truncated':False}
        with path.open('rb') as stream: png = stream.read(4 * 1024 * 1024 + 1)
        if png[:8] != b'\x89PNG\r\n\x1a\n' or len(png) < 24:
            raise WorkspaceError('PNG header is invalid')
        width,height = struct.unpack('>II',png[16:24])
        if not 0 < width <= 4096 or not 0 < height <= 4096 or width * height > 16000000:
            return {'version':token,'kind':'binary','reason':'PNG dimensions exceed bounded preview limits. Download remains available.','text':'','size':start.st_size,'offset':0,'loaded_bytes':0,'truncated':False}
        if path.stat().st_mtime_ns != start.st_mtime_ns:
            raise Conflict('Image changed during preview')
        return {'version':token,'kind':'image','image':'data:image/png;base64,'+base64.b64encode(png).decode(),'width':width,'height':height,'text':'','size':start.st_size,'offset':0,'loaded_bytes':len(png),'truncated':False}
    lines = data.splitlines(keepends=True)[:MAX_LINES]
    if path.suffix.lower() in ('.jsonl', '.csv', '.tsv'):
        lines = lines[:MAX_RECORDS + (path.suffix.lower() != '.jsonl')]
    data = b''.join(lines)
    binary = b'\0' in data
    text = '' if binary else data.decode('utf-8', errors='replace')
    result = dict(version=token, path=query.get('path'), offset=offset, loaded_bytes=len(data), size=start.st_size,
                  text=text, encoding='utf-8', mime=mimetypes.guess_type(path.name)[0] or 'application/octet-stream',
                  truncated=offset+len(data)<start.st_size, next_offset=offset+len(data) if data and offset+len(data)<start.st_size else None,
                  kind='binary' if binary else 'text', observed_at=store.now(), search_scope='loaded page')
    if binary:
        result['reason'] = 'Binary content: use metadata or download'
    elif path.suffix == '.json' and offset == 0 and not result['truncated']:
        try:
            result['structured'] = strict_json(text)
        except (ValueError, UnicodeDecodeError) as error:
            result['parse_error'] = {'message': getattr(error, 'msg', str(error)), 'offset': getattr(error, 'pos', None)}
    elif path.suffix == '.jsonl':
        result['records'] = []; position = offset
        for line in lines:
            item = {'offset': position, 'bytes': len(line)}
            try:
                item['value'] = strict_json(line)
            except (ValueError, UnicodeDecodeError) as error:
                item['error'] = str(error)
            result['records'].append(item); position += len(line)
    elif path.suffix in ('.csv', '.tsv'):
        # Byte/physical-line pages need not end at a logical CSV record. A
        # continuation can start inside a quoted multiline cell: never invent
        # table rows from it. Raw pages retain their exact byte locators.
        if offset or result['truncated']:
            result['reason'] = 'Partial delimited source: logical record boundaries are unknown. Inspect raw bounded pages or download the complete file.'
        else:
            try:
                result['rows'] = list(csv.reader(io.StringIO(data.decode('utf-8')), delimiter='\t' if path.suffix == '.tsv' else ',', strict=True))[:MAX_RECORDS+1]
            except (csv.Error, UnicodeDecodeError) as error:
                result['reason'] = f'Delimited source cannot be parsed safely: {error}. Raw source remains available.'
    return result


def transfer_capability(slug):
    declaration = _manifest(slug).get('retrieval', {})
    if declaration.get('version') != 1 or declaration.get('adapter') not in ('local-copy', 'rsync-files'):
        return {'supported': False, 'reason': 'Exact member retrieval requires a declared retrieval v1 local-copy or rsync-files adapter; the legacy corpus hook has broader scope.'}
    return {'supported': True, 'declaration': declaration, 'revision': fingerprint(declaration)}


def prepare_transfer(slug, body):
    capability = transfer_capability(slug)
    if not capability['supported']:
        raise WorkspaceError(capability['reason'])
    ids = body.get('artifact_ids')
    if not isinstance(ids, list) or not ids or len(ids) > 100:
        raise WorkspaceError('Select 1–100 exact artifact identities')
    artifacts = [store.read(slug, 'artifact', identity) for identity in dict.fromkeys(ids)]
    members = []
    completed_members = set()
    prior_id = body.get('prior_transfer_id')
    if prior_id:
        prior = store.read(slug, 'transfer', prior_id)
        if prior['state'] in ('queued', 'running', 'uncertain'):
            raise Conflict('Reconcile the earlier transfer before reviewing its remaining members')
        if set(ids) != set(prior['artifact_versions']):
            raise Conflict('A transfer retry must retain the earlier artifact scope')
        completed_members = {(m['artifact_id'], m['path'], m['sha256']) for m in prior['members'] if m['state'] == 'succeeded'}
    for artifact in artifacts:
        for member in artifact.get('remote_files', artifact.get('files', [])):
            relative = member['path']
            if (artifact['id'], relative, member.get('sha256')) in completed_members:
                continue
            if not relative.startswith('.unity-workspace/outputs/') or '..' in Path(relative).parts or not member.get('sha256'):
                raise WorkspaceError('Transfer members require declared output paths and content digests')
            members.append(dict(id=fingerprint([artifact['id'], relative])[:32], artifact_id=artifact['id'], path=relative,
                                sha256=member['sha256'], size=member.get('size'), state='queued'))
    if not members:
        raise WorkspaceError('The selected artifacts have no exact remote member inventory')
    from controller.workspace import project
    runtime = {k: project(slug).get(k) for k in ('path','remote_dir','unity_host','overrides')}
    preview = dict(connection_revision=fingerprint(runtime), id=store.new_id('transfer-preview'), kind='retrieval', version=1, state='reviewed', created_at=store.now(),
                   capability_revision=capability['revision'], artifact_versions={a['id']: a.get('content_version', a.get('digest')) for a in artifacts},
                   members=members, bytes_known=sum(m['size'] or 0 for m in members), unknown_sizes=sum(m['size'] is None for m in members),
                   destination='.unity-workspace/transfers/<receipt-id>/files', prior_transfer_id=body.get('prior_transfer_id'))
    preview['selection_fingerprint'] = fingerprint(members)
    with store.transaction(slug) as con:
        store.put(con, 'transfer_preview', preview)
    return preview


def _copy_member(slug, transfer, member, temporary):
    declaration = transfer['adapter']
    relative = member['path']
    temporary.parent.mkdir(parents=True, exist_ok=True)
    if declaration['adapter'] == 'local-copy':
        # The source root is project-declared, never supplied by a browser request.
        source_root = Path(declaration['source_root']).resolve()
        source = safe_path(source_root, relative)
        if not source.is_file():
            raise Missing('Remote member is unavailable')
        with source.open('rb') as incoming, temporary.open('wb') as outgoing:
            for chunk in iter(lambda: incoming.read(1024 * 1024), b''):
                if store.read(slug, 'transfer', transfer['id']).get('cancel_requested'):
                    raise WorkspaceError('Transfer cancelled; partial bytes retained')
                outgoing.write(chunk)
    else:
        from controller.workspace import project
        import re
        project_record = project(slug)
        host = project_record.get('unity_host') or declaration.get('host', '')
        remote = project_record.get('remote_dir', '')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.@-]*', host) or not remote.startswith('/'):
            raise WorkspaceError('Retrieval host or remote root is not configured')
        command = ['rsync', '-a', '--protect-args', '--timeout=30', '-e', 'ssh -o BatchMode=yes -o ConnectTimeout=10',
                   f'{host}:{remote.rstrip("/")}/{relative}', str(temporary)]
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        deadline = time.monotonic() + 60
        try:
            while process.poll() is None:
                if time.monotonic() >= deadline or store.read(slug, 'transfer', transfer['id']).get('cancel_requested'):
                    import signal
                    os.killpg(process.pid, signal.SIGTERM)
                    try: process.wait(timeout=2)
                    except subprocess.TimeoutExpired: os.killpg(process.pid, signal.SIGKILL); process.wait(timeout=2)
                    raise WorkspaceError('Transfer cancelled or timed out; partial bytes retained')
                time.sleep(.1)
            if process.returncode:
                raise WorkspaceError('Scoped remote member transfer failed')
        finally:
            if process.poll() is None:
                process.kill(); process.wait(timeout=2)


def _save_transfer(slug, transfer):
    transfer['updated_at'] = store.now()
    with store.transaction(slug) as con:
        current = store.get(con, 'transfer', transfer['id'])
        transfer['cancel_requested'] = current.get('cancel_requested', False)
        transfer['version'] = current.get('version', 1) + 1
        store.put(con, 'transfer', transfer)


def run_transfer(slug, identity):
    transfer = store.read(slug, 'transfer', identity)
    transfer['state'] = 'running'; _save_transfer(slug, transfer)
    folder = safe_path(_root(slug), str(Path('.unity-workspace/transfers') / identity))
    for member in transfer['members']:
        if store.read(slug, 'transfer', identity).get('cancel_requested'):
            break
        if member['state'] == 'succeeded':
            continue
        temporary = safe_path(folder, str(Path('partial') / member['id']))
        final = safe_path(folder, str(Path('files') / member['path']))
        member['state'] = 'running'; _save_transfer(slug, transfer)
        try:
            _copy_member(slug, transfer, member, temporary)
            if digest(temporary) != member['sha256'] or member.get('size') is not None and temporary.stat().st_size != member['size']:
                raise Conflict('Retrieved bytes do not match the reviewed content version; bytes quarantined')
            final.parent.mkdir(parents=True, exist_ok=True)
            os.replace(temporary, final)
            member.update(state='succeeded', local_path=str(final.relative_to(_root(slug))), transferred=final.stat().st_size)
        except (OSError, WorkspaceError, subprocess.SubprocessError) as error:
            member.update(state='failed', error=str(error))
        _save_transfer(slug, transfer)
    successes = sum(m['state'] == 'succeeded' for m in transfer['members'])
    transfer['state'] = 'cancelled' if transfer.get('cancel_requested') else ('succeeded' if successes == len(transfer['members']) else 'partial' if successes else 'failed')
    transfer['targets'] = [{'id': m['id'], 'state': 'accepted' if m['state'] == 'succeeded' else 'skipped' if m['state'] == 'queued' else 'rejected', 'reason': m.get('error')} for m in transfer['members']]
    _save_transfer(slug, transfer)
    _register_transfer_members(slug, transfer)
    return transfer



def _register_transfer_members(slug, transfer):
    # Transport never promotes scientific completeness. Each checked member survives partial receipts.
    for artifact_id in transfer['artifact_versions']:
        selected = [m for m in transfer['members'] if m['artifact_id'] == artifact_id and m['state'] == 'succeeded']
        if not selected:
            continue
        with store.transaction(slug) as con:
            artifact = store.get(con, 'artifact', artifact_id)
            members = {m['path']: m for m in artifact.get('files', [])}
            for member in selected:
                path = _root(slug) / member['local_path']; st = path.stat()
                members[member['path']] = {'path': member['path'], 'sha256': member['sha256'], 'size': member.get('size'),
                    'frozen_path': member['local_path'], 'checked_stat': [st.st_ino, st.st_size, st.st_mtime_ns]}
            expected = artifact.get('remote_files', artifact.get('files', []))
            available = all(m['path'] in members and members[m['path']]['sha256'] == m['sha256'] for m in expected)
            artifact.update(availability='both' if available else 'remote', integrity='checked' if available else 'unchecked',
                            observed_at=store.now(), files=list(members.values()), retrieval='complete' if available else 'partial')
            store.put(con, 'artifact', artifact)

def commit_transfer(slug, preview_id, key, *, background=True):
    from controller.workspace_worker import project_lock
    with project_lock(slug) as acquired:
        if not acquired:
            raise Conflict('Project activity or maintenance is busy; retry this exact reviewed retrieval')
        return _commit_transfer(slug, preview_id, key, background=background)


def _commit_transfer(slug, preview_id, key, *, background=True):
    if not isinstance(key, str) or not key or len(key) > 200:
        raise WorkspaceError('An idempotency key is required')
    capability = transfer_capability(slug)
    with store.transaction(slug) as con:
        existing = next((t for t in store.list_records(con, 'transfer') if t['idempotency_key'] == key), None)
        if existing:
            if existing['preview_id'] != preview_id:
                raise Conflict('Idempotency key belongs to another transfer')
            return existing
        preview = store.get(con, 'transfer_preview', preview_id)
        from controller.workspace import project
        runtime = {k: project(slug).get(k) for k in ('path','remote_dir','unity_host','overrides')}
        if preview.get('connection_revision') != fingerprint(runtime):
            raise Conflict('Retrieval connection changed; review exact source and destination again')
        if any(a.get('state') in ('applying','checking','recovery_required') for a in store.list_records(con,'maintenance-action')):
            raise Conflict('Reconcile project maintenance before starting a transfer')
        if not capability['supported'] or preview['capability_revision'] != capability['revision']:
            raise Conflict('Retrieval capability changed; review again')
        for identity, version in preview['artifact_versions'].items():
            artifact = store.get(con, 'artifact', identity)
            if artifact.get('content_version', artifact.get('digest')) != version:
                raise Conflict('Artifact selection changed; review again', current_version=artifact.get('content_version', artifact.get('digest')), expected_version=version)
        for old in store.list_records(con, 'transfer'):
            if old['state'] in ('queued', 'running', 'uncertain') and set(old['artifact_versions']) & set(preview['artifact_versions']):
                raise Conflict('An active or uncertain transfer covers this selection; reconcile it first')
        transfer = dict(preview, id=store.new_id('transfer'), preview_id=preview_id, idempotency_key=key, state='queued', version=1,
                        adapter=capability['declaration'], targets=[{'id': m['id'], 'state': 'accepted'} for m in preview['members']], updated_at=store.now())
        store.put(con, 'transfer', transfer)
    if background:
        thread = threading.Thread(target=run_transfer, args=(slug, transfer['id']), daemon=True)
        with _TRANSFER_LOCK:
            _TRANSFER_THREADS[(slug, transfer['id'])] = thread
        thread.start()
        return transfer
    return run_transfer(slug, transfer['id'])


def cancel_transfer(slug, identity):
    with store.transaction(slug) as con:
        transfer = store.get(con, 'transfer', identity)
        transfer['cancel_requested'] = True
        transfer['version'] += 1
        store.put(con, 'transfer', transfer)
    return transfer


def reconcile_transfer(slug, identity):
    transfer = store.read(slug, 'transfer', identity)
    with _TRANSFER_LOCK:
        active = _TRANSFER_THREADS.get((slug, identity))
    if active and active.is_alive():
        return transfer
    folder = safe_path(_root(slug), str(Path('.unity-workspace/transfers') / identity))
    for member in transfer['members']:
        final = folder / 'files' / member['path']
        if final.is_file() and digest(final) == member['sha256']:
            member.update(state='succeeded', local_path=str(final.relative_to(_root(slug))))
        elif member['state'] in ('running', 'succeeded'):
            member.update(state='failed', error='Interrupted transfer; partial bytes retained for inspection')
    n = sum(m['state'] == 'succeeded' for m in transfer['members'])
    transfer['state'] = 'succeeded' if n == len(transfer['members']) else 'partial' if n else 'failed'
    _save_transfer(slug, transfer)
    _register_transfer_members(slug, transfer)
    return transfer


def download_source(slug, query):
    root, entry = _browse_root(slug, query.get('root', 'source'))
    relative = query.get('path', '')
    if _excluded(str(Path(entry['relative_path']) / relative), _manifest(slug)):
        raise WorkspaceError('Path is excluded from project browsing')
    path = authorize_resolved(slug, safe_path(root, relative, manifest=_manifest(slug)))
    if not path.is_file():
        raise Missing('Download file is unavailable')
    st = path.stat()
    token = fingerprint([st.st_ino, st.st_size, st.st_mtime_ns])
    if query.get('version') and query['version'] != token:
        raise Conflict('Source changed; refresh before downloading', current_version=token, expected_version=query['version'])
    if st.st_size > MAX_DOWNLOAD:
        raise WorkspaceError('Browser download exceeds 16 MiB; use the known controller path')
    data = path.read_bytes(); after = path.stat()
    if (st.st_ino, st.st_size, st.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
        raise Conflict('File changed while downloading')
    return data, path.name


def transfer_projection(slug, transfer):
    value = copy.deepcopy(transfer)
    with _TRANSFER_LOCK:
        thread = _TRANSFER_THREADS.get((slug, transfer['id']))
    if value['state'] in ('queued', 'running') and (not thread or not thread.is_alive()):
        value.update(state='uncertain', reason='Controller transfer activity is no longer present. Reconcile installed and partial bytes before retry.')
    return value
