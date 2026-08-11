import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const HTML_PATH = path.join(REPO_ROOT, "consola_preview.html");
const HTML_SOURCE = fs.readFileSync(HTML_PATH, "utf8");
const START = "/* TASK3_READER_EDITOR_CONTROLLER_START */";
const END = "/* TASK3_READER_EDITOR_CONTROLLER_END */";

class FakeClassList {
    constructor() { this.values = new Set(); }
    add(name) { this.values.add(name); }
    remove(name) { this.values.delete(name); }
    toggle(name, force) {
        const next = force === undefined ? !this.values.has(name) : Boolean(force);
        if (next) this.values.add(name); else this.values.delete(name);
        return next;
    }
}

class FakeNode {
    constructor(tagName = "#text", text = "") {
        this.tagName = tagName.toUpperCase();
        this.children = [];
        this.dataset = {};
        this.classList = new FakeClassList();
        this.disabled = false;
        this.value = "";
        this._textContent = text;
    }

    get textContent() {
        return this._textContent || this.children.map((child) => child.textContent).join("");
    }

    set textContent(value) {
        this._textContent = String(value ?? "");
        this.children = [];
    }

    appendChild(child) {
        this.children.push(child);
        return child;
    }

    append(...children) {
        children.forEach((child) => this.appendChild(typeof child === "string" ? new FakeNode("#text", child) : child));
    }

    replaceChildren(...children) {
        this.children = [];
        children.forEach((child) => this.appendChild(child));
    }

    addEventListener() {}
    querySelector() { return null; }
}

function makeHarness() {
    const elements = new Map();
    [
        "reader-markdown-editor",
        "reader-markdown-save",
        "reader-markdown-cancel",
        "reader-edit-state",
        "reader-markdown-preview",
        "reader-editor-conflict",
    ].forEach((id) => elements.set(id, new FakeNode("div")));

    const document = {
        getElementById(id) { return elements.get(id) || null; },
        createElement(tagName) { return new FakeNode(tagName); },
        createTextNode(text) { return new FakeNode("#text", String(text ?? "")); },
        querySelectorAll() { return []; },
    };
    const reloads = [];
    const window = { pywebview: { api: {} } };
    const context = {
        document,
        window,
        console,
        loadNoteContent: (...args) => reloads.push(args),
        renderNoteDocument() {},
    };
    const start = HTML_SOURCE.indexOf(START);
    const end = HTML_SOURCE.indexOf(END);
    assert.ok(start >= 0 && end > start, "reader controller markers must be present");
    const controller = HTML_SOURCE.slice(start, end);
    const expose = `
        window.__readerEditorTest = {
            editor: document.getElementById('reader-markdown-editor'),
            saveButton: document.getElementById('reader-markdown-save'),
            stateElement: document.getElementById('reader-edit-state'),
            setLoaded(id, revision, body, projection) {
                currentSelectedDocumentId = id;
                readerEditorDocumentId = id;
                readerEditorRevision = revision;
                readerEditorBody = body;
                readerEditorOriginalBody = body;
                readerEditorProjection = projection;
                readerEditorState = { status: 'saved', dirty: false };
                readerEditorSession += 1;
                readerEditorSaveOperation = null;
                this.editor.value = body;
            },
            markDirty(body) {
                this.editor.value = body;
                readerEditorBody = body;
                readerEditorState = { status: 'dirty', dirty: true };
            },
            navigate(id) {
                invalidateReaderEditorForNavigation(id);
                currentSelectedDocumentId = id;
            },
            save() { saveReaderEdit(); },
            project(markdown) { return readerMarkdownToProjection(markdown); },
            render(projection) { return createNoteContent(readerProjectionToDocumentModel(projection)); },
            state() {
                return {
                    documentId: currentSelectedDocumentId,
                    editorDocumentId: readerEditorDocumentId,
                    body: readerEditorBody,
                    originalBody: readerEditorOriginalBody,
                    revision: readerEditorRevision,
                    status: readerEditorState.status,
                    dirty: readerEditorState.dirty,
                };
            },
        };
    `;
    vm.runInNewContext(`${controller}\n${expose}`, context);
    return {
        api: window.pywebview.api,
        editor: elements.get("reader-markdown-editor"),
        test: window.__readerEditorTest,
        reloads,
    };
}

function success(documentId, revision, body) {
    return {
        document_id: documentId,
        revision,
        body_markdown: body,
        projection: { body: { type: "doc", content: [] } },
    };
}

test("save preserves text typed after the request began", async () => {
    const harness = makeHarness();
    let resolveSave;
    harness.api.update_note_body = () => new Promise((resolve) => { resolveSave = resolve; });
    harness.test.setLoaded("opaque-a", 4, "# Original\n", { body: { type: "doc", content: [] } });
    harness.test.markDirty("# First draft\n");

    harness.test.save();
    harness.editor.value = "# Newer draft typed while saving\n";
    resolveSave(success("opaque-a", 5, "# First draft\n"));
    await Promise.resolve();
    await Promise.resolve();

    const state = harness.test.state();
    assert.equal(harness.editor.value, "# Newer draft typed while saving\n");
    assert.equal(state.body, "# Newer draft typed while saving\n");
    assert.equal(state.originalBody, "# First draft\n");
    assert.equal(state.revision, 5);
    assert.equal(state.dirty, true);
    assert.equal(state.status, "dirty");
    assert.equal(harness.reloads.length, 0);
});

test("save response is discarded after navigating to another opaque document", async () => {
    const harness = makeHarness();
    let resolveSave;
    harness.api.update_note_body = () => new Promise((resolve) => { resolveSave = resolve; });
    harness.test.setLoaded("opaque-a", 8, "# A\n", { body: { type: "doc", content: [] } });
    harness.test.markDirty("# A draft\n");

    harness.test.save();
    harness.test.navigate("opaque-b");
    resolveSave(success("opaque-a", 9, "# A draft\n"));
    await Promise.resolve();
    await Promise.resolve();

    const state = harness.test.state();
    assert.equal(state.documentId, "opaque-b");
    assert.equal(state.body, "# A draft\n");
    assert.equal(state.revision, 8);
    assert.equal(harness.reloads.length, 0);
});

test("representative Markdown uses the projection and safe renderer path", () => {
    const harness = makeHarness();
    const markdown = [
        "# Título",
        "",
        "- [[Destino]]",
        "- **negrita**",
        "",
        "```js",
        "<script>alert(1)</script>",
        "```",
        "",
        "| A | B |",
        "| --- | --- |",
        "| raw | <img src=x> |",
        "",
        "Línea \u003craw\u003e y $x$",
        "",
    ].join("\n");
    const projection = harness.test.project(markdown);
    const types = projection.content.map((block) => block.type);
    assert.deepEqual(Array.from(types), ["heading", "bullet_list", "code_block", "raw_block", "paragraph"]);
    assert.equal(projection.content[1].content[0].content[0].content[0].type, "raw_inline");

    const rendered = harness.test.render(projection);
    assert.equal(rendered.children.filter((node) => node.tagName === "PRE").length, 2);
    assert.match(rendered.textContent, /\[\[Destino\]\]/);
    assert.match(rendered.textContent, /<script>alert\(1\)<\/script>/);
    assert.match(rendered.textContent, /<img src=x>/);
    assert.match(rendered.textContent, /Línea <raw> y \$x\$/);
});
