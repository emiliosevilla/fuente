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
