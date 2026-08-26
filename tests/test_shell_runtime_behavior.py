from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "consola_preview.html").read_text(encoding="utf-8")


def _extract_function(name: str) -> str:
    start = HTML.index(f"function {name}(")
    brace = HTML.index("{", start)
    depth = 0
    for index in range(brace, len(HTML)):
        character = HTML[index]
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return HTML[start : index + 1]
    raise AssertionError(f"unterminated JavaScript function: {name}")


def test_reader_context_reopens_after_escape_executes_real_javascript():
    node = shutil.which("node")
    assert node is not None, "Node is required to execute the shell behavior contract"
    functions = "\n".join(
        _extract_function(name)
        for name in (
            "setReaderContextVisibility",
            "closeDrawer",
            "toggleReaderContext",
            "handleShellKeydown",
        )
    )
    program = f"""
const assert = require('node:assert/strict');

function makeClassList(initial) {{
    const values = new Set(initial);
    return {{
        contains(name) {{ return values.has(name); }},
        toggle(name, force) {{
            const enabled = force === undefined ? !values.has(name) : Boolean(force);
            if (enabled) values.add(name);
            else values.delete(name);
            return enabled;
        }},
    }};
}}

const workspace = {{ classList: makeClassList(['is-context-hidden']) }};
const buttonAttributes = new Map([['aria-pressed', 'false']]);
const button = {{
    setAttribute(name, value) {{ buttonAttributes.set(name, String(value)); }},
    getAttribute(name) {{ return buttonAttributes.get(name); }},
}};
const drawerAttributes = new Map([['aria-hidden', 'true']]);
const drawer = {{
    id: 'source-context-drawer',
    hidden: true,
    setAttribute(name, value) {{ drawerAttributes.set(name, String(value)); }},
    getAttribute(name) {{ return drawerAttributes.get(name); }},
}};

global.document = {{
    activeElement: button,
    getElementById(id) {{
        if (id === 'btn-reader-context') return button;
        if (id === 'source-context-drawer') return drawer;
        return null;
    }},
    querySelector(selector) {{
        if (selector === '#modal-reader .reader-context-grid') return workspace;
        if (selector === '.ui-drawer:not([hidden])[aria-hidden="false"]') {{
            return !drawer.hidden && drawer.getAttribute('aria-hidden') === 'false'
                ? drawer
                : null;
        }}
        if (selector === '.modal-overlay.is-open') return null;
        return null;
    }},
    querySelectorAll(selector) {{
        if (selector === '.modal-overlay.is-open') return [];
        return [];
    }},
}};
global.getFocusableElements = function() {{ return []; }};
global.persistUiState = function() {{ return Promise.resolve(); }};
let lastDrawerTrigger = null;

{functions}

toggleReaderContext();
assert.equal(drawer.hidden, false);
assert.equal(drawer.getAttribute('aria-hidden'), 'false');
assert.equal(button.getAttribute('aria-pressed'), 'true');
assert.equal(workspace.classList.contains('is-context-hidden'), false);

let prevented = false;
handleShellKeydown({{
    key: 'Escape',
    shiftKey: false,
    preventDefault() {{ prevented = true; }},
}});
assert.equal(prevented, true);
assert.equal(drawer.hidden, true);
assert.equal(drawer.getAttribute('aria-hidden'), 'true');
assert.equal(button.getAttribute('aria-pressed'), 'false');
assert.equal(workspace.classList.contains('is-context-hidden'), true);

toggleReaderContext();
assert.equal(drawer.hidden, false);
assert.equal(drawer.getAttribute('aria-hidden'), 'false');
assert.equal(button.getAttribute('aria-pressed'), 'true');
assert.equal(workspace.classList.contains('is-context-hidden'), false);
"""
    result = subprocess.run(
        [node, "-"],
        input=program,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_restore_loads_filter_and_sort_before_workspace_and_reapplies_filter():
    node = shutil.which("node")
    assert node is not None, "Node is required to execute the shell behavior contract"
    functions = "\n".join(
        _extract_function(name) for name in ("setReaderSort", "restoreUiState")
    )
    render = _extract_function("renderNoteList")
    assert render.index("ul.appendChild(group)") < render.rindex("filterReaderNotes(false)")
    program = f"""
const assert = require('node:assert/strict');
const WORKSPACE_IDS = ['home', 'source', 'flow'];
const FUENTE_STYLES = new Set(['nord', 'gruvbox']);
let readerSort = {{field: 'title', direction: 'asc'}};
let queueCursor = null;
let queueCursorHistory = [];
const search = {{value: ''}};
const observations = [];
global.document = {{
    getElementById(id) {{ return id === 'reader-search' ? search : null; }},
}};
global.persistUiState = function() {{ return Promise.resolve(); }};
global.filterReaderNotes = function() {{ observations.push(['filter', search.value]); }};
global.switchWorkspace = function(value) {{ observations.push(['workspace', value, search.value, readerSort.direction]); }};
global.applyVisualStyle = function() {{}};
global.setReaderContextVisibility = function() {{}};
global.switchWorkspaceTab = function() {{}};
global.readUiState = function(owner, key) {{
    if (owner === 'main-window' && key === 'workspace') return Promise.resolve('source');
    if (owner === 'reader' && key === 'filters') return new Promise(resolve => setTimeout(() => resolve({{search: 'persistida'}}), 20));
    if (owner === 'reader' && key === 'sort') return Promise.resolve({{field: 'title', direction: 'desc'}});
    return Promise.resolve(null);
}};
{functions}
restoreUiState();
setTimeout(function() {{
    assert.deepEqual(observations[0], ['workspace', 'source', 'persistida', 'desc']);
}}, 40);
"""
    result = subprocess.run(
        [node, "-"], input=program, text=True, capture_output=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_failed_ui_state_write_is_visible_and_remains_queued():
    node = shutil.which("node")
    assert node is not None, "Node is required to execute the shell behavior contract"
    functions = "\n".join(
        _extract_function(name)
        for name in (
            "reportUiStateFailure",
            "scheduleUiStateRetry",
            "notifyNativeUiStatePending",
            "persistUiState",
        )
    )
    program = """
const assert = require('node:assert/strict');
const pendingUiState = new Map();
const UI_STATE_RETRY_DELAY_MS = 1500;
let uiStateRetryTimer = null;
let nativeCloseRequested = false;
const status = {textContent: ''};
global.setTimeout = function() { return 1; };
global.window = {pywebview: {api: {set_ui_state() { return Promise.reject(new Error('disk full')); }}}};
global.document = {getElementById() { return status; }};
global.log = function() {};
console.error = function() {};
__FUNCTIONS__
persistUiState('reader', 'drafts', {workspaceChat: 'sin perder'}).then(function(result) {
    assert.equal(result.error, 'ui_state_persistence_failed');
    assert.equal(pendingUiState.size, 1);
    assert.match(status.textContent, /disk full/);
});
""".replace("__FUNCTIONS__", functions)
    result = subprocess.run(
        [node, "-"], input=program, text=True, capture_output=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_ui_state_write_failure_after_ready_retries_and_recovers():
    node = shutil.which("node")
    assert node is not None, "Node is required to execute the shell behavior contract"
    functions = "\n".join(
        _extract_function(name)
        for name in (
            "reportUiStateFailure",
            "scheduleUiStateRetry",
            "notifyNativeUiStatePending",
            "notifyNativeCloseWhenReady",
            "flushPendingUiState",
            "persistUiState",
        )
    )
    program = """
const assert = require('node:assert/strict');
const pendingUiState = new Map();
const UI_STATE_RETRY_DELAY_MS = 1500;
let uiStateRetryTimer = null;
let nativeCloseRequested = false;
let retry = null;
let calls = 0;
const status = {textContent: ''};
global.setTimeout = function(callback) { retry = callback; return 1; };
global.window = {pywebview: {api: {set_ui_state() {
    calls += 1;
    return calls === 1
        ? Promise.reject(new Error('database temporarily locked'))
        : Promise.resolve({status: 'saved'});
}}}};
global.document = {getElementById() { return status; }};
global.log = function() {};
console.error = function() {};
__FUNCTIONS__
persistUiState('reader', 'filters', {search: 'no perder'}).then(function(first) {
    assert.equal(first.error, 'ui_state_persistence_failed');
    assert.equal(pendingUiState.size, 1);
    assert.equal(typeof retry, 'function');
    retry();
    setImmediate(function() {
        assert.equal(calls, 2);
        assert.equal(pendingUiState.size, 0);
        assert.match(status.textContent, /database temporarily locked/);
    });
});
""".replace("__FUNCTIONS__", functions)
    result = subprocess.run(
        [node, "-"], input=program, text=True, capture_output=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_native_close_drain_completes_only_after_sqlite_write_recovers():
    node = shutil.which("node")
    assert node is not None, "Node is required to execute the shell behavior contract"
    functions = "\n".join(
        _extract_function(name)
        for name in (
            "reportUiStateFailure",
            "scheduleUiStateRetry",
            "notifyNativeUiStatePending",
            "notifyNativeCloseWhenReady",
            "flushPendingUiState",
            "persistUiState",
            "prepareUiStateForNativeClose",
        )
    )
    program = """
const assert = require('node:assert/strict');
const pendingUiState = new Map();
const UI_STATE_RETRY_DELAY_MS = 1500;
let uiStateRetryTimer = null;
let nativeCloseRequested = false;
let retry = null;
let writes = 0;
let canWrite = false;
let closeCompletions = 0;
const status = {textContent: ''};
global.setTimeout = function(callback) { retry = callback; return 1; };
global.window = {pywebview: {api: {
    set_ui_state() {
        writes += 1;
        return canWrite
            ? Promise.resolve({status: 'saved'})
            : Promise.reject(new Error('database temporarily locked'));
    },
    ui_state_pending_changed() { return Promise.resolve({status: 'recorded'}); },
    complete_pending_close() {
        closeCompletions += 1;
        return Promise.resolve({status: 'closing'});
    },
}}};
global.document = {getElementById() { return status; }};
global.log = function() {};
console.error = function() {};
__FUNCTIONS__
persistUiState('reader', 'drafts', {text: 'conservar'}).then(function() {
    const close = prepareUiStateForNativeClose();
    assert.equal(close.ready, false);
    assert.equal(closeCompletions, 0);
    setImmediate(function() {
        assert.equal(pendingUiState.size, 1);
        canWrite = true;
        retry();
        setImmediate(function() {
            assert.equal(pendingUiState.size, 0);
            assert.equal(closeCompletions, 1);
        });
    });
});
""".replace("__FUNCTIONS__", functions)
    result = subprocess.run(
        [node, "-"], input=program, text=True, capture_output=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_ui_write_after_native_action_is_scheduled_stays_queued_and_retries():
    node = shutil.which("node")
    assert node is not None, "Node is required to execute the shell behavior contract"
    functions = "\n".join(
        _extract_function(name)
        for name in (
            "reportUiStateFailure",
            "scheduleUiStateRetry",
            "notifyNativeUiStatePending",
            "notifyNativeCloseWhenReady",
            "flushPendingUiState",
            "persistUiState",
        )
    )
    program = """
const assert = require('node:assert/strict');
const pendingUiState = new Map();
const UI_STATE_RETRY_DELAY_MS = 1500;
let uiStateRetryTimer = null;
let nativeCloseRequested = true;
let retry = null;
let nativeActionScheduled = true;
let actionExecutions = 0;
let sqliteValue = null;
const notifications = [];
const status = {textContent: ''};
global.setTimeout = function(callback) { retry = callback; return 1; };
global.window = {pywebview: {api: {
    ui_state_pending_changed(count) {
        notifications.push(count);
        if (nativeActionScheduled && count > 0) {
            nativeActionScheduled = false;
            return Promise.resolve({
                error: 'ui_state_closing',
                message: 'scheduled action invalidated',
            });
        }
        return Promise.resolve({pending: count});
    },
    set_ui_state(_scope, _owner, _key, value) {
        sqliteValue = value;
        return Promise.resolve({status: 'saved'});
    },
    complete_pending_close() {
        actionExecutions += 1;
        return Promise.resolve({status: 'restarting'});
    },
}}};
global.document = {getElementById() { return status; }};
global.log = function() {};
console.error = function() {};
__FUNCTIONS__
persistUiState('reader', 'filters', {search: 'late-write'}).then(function(first) {
    assert.equal(first.error, 'ui_state_persistence_failed');
    assert.equal(pendingUiState.size, 1);
    assert.equal(sqliteValue, null);
    assert.equal(actionExecutions, 0);
    assert.equal(typeof retry, 'function');
    retry();
    setImmediate(function() {
        assert.deepEqual(sqliteValue, {search: 'late-write'});
        assert.equal(pendingUiState.size, 0);
        assert.equal(actionExecutions, 1);
        assert.deepEqual(notifications, [1, 1, 0]);
    });
});
""".replace("__FUNCTIONS__", functions)
    result = subprocess.run(
        [node, "-"], input=program, text=True, capture_output=True, check=False
    )
    assert result.returncode == 0, result.stderr
