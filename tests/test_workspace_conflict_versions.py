"""Conflict responses expose entity tokens without losing either editor's text."""
import copy

from controller import workspace_store as store
from controller.workspace_contracts import version_token
from test_workspace_api import project, call, create_plan  # noqa: F401


def assert_conflict(response, current, expected):
    status, body = response
    assert status == 409, body
    assert body['current_version'] == current
    assert body['expected_version'] == expected
    assert body['error'] and body['ok'] is False
    assert body['response_metadata']['observations']['local_read']['state'] == 'fresh'
    assert body['response_metadata']['source_revision'] == 'unknown'


def test_draft_and_review_conflicts_report_current_entity_version(project):
    experiment, plan = create_plan()
    route = 'experiments/' + experiment['id']
    saved = {**experiment['draft'], 'name': 'Saved scientific question'}
    assert call('PATCH', route, {'expected_version': 1, 'draft': saved})[0] == 200
    pending = {'expected_version': 1, 'draft': {**saved, 'name': 'Local unsaved question'}}
    original = copy.deepcopy(pending)
    assert_conflict(call('PATCH', route, pending), 2, 1)
    assert pending == original
    assert call('GET', route)[1]['draft'] == saved
    assert_conflict(call('POST', 'plans/' + plan['id'] + '/dispatch', {'idempotency_key': 'stale-review'}), 2, 1)
    assert store.listing('demo', 'execution') == []


def test_research_context_and_note_conflicts_preserve_saved_and_pending_text(project):
    assert call('PATCH', 'overview/context', {'expected_version': 0, 'question': 'Saved question'})[0] == 200
    pending = {'expected_version': 0, 'question': 'Pending local question'}
    assert_conflict(call('PATCH', 'overview/context', pending), 1, 0)
    assert pending['question'] == 'Pending local question'
    assert call('GET', 'overview')[1]['research_context']['question'] == 'Saved question'
    _, note = call('POST', 'overview/notes', {'expected_version': 0, 'text': 'Saved evidence note'})
    assert_conflict(call('PATCH', 'overview/notes/' + note['id'], {'expected_version': 0, 'text': 'Pending note'}), 1, 0)
    assert store.read('demo', 'evidence-note', note['id'])['text'] == 'Saved evidence note'


def test_settings_and_maintenance_preview_report_settings_revision(project):
    _, settings = call('GET', 'settings')
    body = {'action': 'defaults', 'patch': {'variant_concurrency': 2},
            'expected_version': settings['version'], 'declaration_digest': settings['declaration_digest']}
    status, preview = call('POST', 'connection/preview', body)
    assert status == 201, preview
    status, newer = call('POST', 'connection/preview', {**body, 'patch': {'variant_concurrency': 3}})
    assert status == 201, newer
    assert call('POST', 'maintenance/' + newer['id'] + '/activate', {'idempotency_key': 'new-settings'})[0] == 200
    assert_conflict(call('POST', 'connection/preview', body), settings['version'] + 1, settings['version'])
    assert_conflict(call('POST', 'maintenance/' + preview['id'] + '/activate', {'idempotency_key': 'stale-settings'}), settings['version'] + 1, settings['version'])


def test_adopting_defaults_reports_current_draft_version(project):
    _, experiment = call('POST', 'experiments', {'workflow': 'local'})
    route = 'experiments/' + experiment['id']
    _, preview = call('POST', route + '/defaults', {})
    assert call('PATCH', route, {'expected_version': 1, 'draft': {**experiment['draft'], 'name': 'Newer draft'}})[0] == 200
    assert_conflict(call('POST', route + '/defaults', {**preview, 'apply': True}), 2, 1)
    assert call('GET', route)[1]['name'] == 'Newer draft'


def test_state_conflict_does_not_invent_an_entity_version(project):
    experiment, plan = create_plan()
    assert call('POST', 'plans/' + plan['id'] + '/dispatch', {'idempotency_key': 'history'})[0] == 202
    status, body = call('DELETE', 'experiments/' + experiment['id'])
    assert status == 409
    assert body['current_version'] is None
    assert 'expected_version' not in body


def test_schedule_conflicts_report_frozen_plan_and_schedule_tokens(project):
    _, plan = create_plan()
    body = {'plan_id': plan['id'], 'expected_version': 'stale-plan', 'approved': True,
            'idempotency_key': 'future', 'timezone': 'UTC', 'earliest_dispatch': '2030-01-01T12:00:00+00:00'}
    assert_conflict(call('POST', 'schedules', body), version_token(plan), 'stale-plan')
    status, scheduled = call('POST', 'schedules', {**body, 'expected_version': version_token(plan)})
    assert status == 201, scheduled
    assert_conflict(call('POST', 'schedules/' + scheduled['id'] + '/cancel', {'expected_version': 0}), scheduled['version'], 0)
    assert store.read('demo', 'schedule', scheduled['id'])['state'] == 'scheduled'


def test_management_scope_conflict_reports_execution_token(project):
    _, plan = create_plan()
    _, execution = call('POST', 'plans/' + plan['id'] + '/dispatch', {'idempotency_key': 'management'})
    pending = {'kind': 'cancel', 'execution_id': execution['id'], 'expected_version': 'old-execution',
               'stage_ids': [execution['stages'][0]['id']]}
    assert_conflict(call('POST', 'management-plans', pending), version_token(execution), 'old-execution')
    assert store.listing('demo', 'operation') == []
