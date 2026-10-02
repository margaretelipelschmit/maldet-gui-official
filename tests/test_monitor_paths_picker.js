const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../gui/static/app.js'), 'utf8');

// The Monitored folders card must offer the same folder picker as the scanner,
// wired to the monitor-path field.
assert.match(
    source,
    /data-action="folder-picker" data-target="monitor-path-input" data-title="Choose folder"/,
    'Monitored folders card exposes a Browse button targeting the monitor-path field'
);

const instrumented = source.replace(
    "    document.addEventListener('DOMContentLoaded', function() {",
    "    window.testRouter = Router;\n" +
    "    document.addEventListener('DOMContentLoaded', function() {"
);
assert.notEqual(instrumented, source);

const listeners = {};
const directories = [];
const input = {
    value: '',
    focus() {},
    dispatchEvent(event) { this.lastEvent = event; }
};
const listEl = { innerHTML: '' };
const elements = {};
const bodyChildren = [];

function makeElement(tag) {
    return {
        tag,
        id: '',
        className: '',
        style: {},
        _html: '',
        _attrs: {},
        _listeners: {},
        children: [],
        parentNode: null,
        set innerHTML(value) { this._html = String(value); },
        get innerHTML() { return this._html; },
        set textContent(value) { this._html = String(value); },
        get textContent() { return this._html; },
        setAttribute(name, value) { this._attrs[name] = value; },
        getAttribute(name) { return this._attrs[name]; },
        appendChild(child) { this.children.push(child); return child; },
        remove() { this._removed = true; },
        addEventListener(event, listener) { (this._listeners[event] ||= []).push(listener); },
        focus() {},
        dispatchEvent() {},
        querySelector() { return null; }
    };
}

class Request {
    open(method, url) { this.method = method; this.url = url; }
    setRequestHeader() {}
    abort() {}
    send() {
        directories.push({ method: this.method, url: this.url });
        this.status = 200;
        this.responseText = JSON.stringify({
            path: '/',
            parent: null,
            directories: [{ name: 'opt', path: '/opt' }, { name: 'srv', path: '/srv' }]
        });
        this.readyState = 4;
        this.onreadystatechange();
    }
}

const context = {
    window: {},
    document: {
        addEventListener(event, listener) { (listeners[event] ||= []).push(listener); },
        body: {
            appendChild(el) {
                bodyChildren.push(el);
                el.parentNode = this;
                if (el.id) elements[el.id] = el;
                return el;
            }
        },
        createElement(tag) { return makeElement(tag); },
        getElementById(id) {
            if (id === 'monitor-path-input') return input;
            if (id === 'monitor-path-list') return listEl;
            if (id === 'toast-container') return { appendChild() {} };
            if (elements[id]) return elements[id];
            if (['sidebar-nav', 'refresh-btn', 'content'].includes(id)) {
                return { addEventListener() {} };
            }
            return null;
        }
    },
    XMLHttpRequest: Request,
    localStorage: { getItem() { return 'en'; } },
    setTimeout() { return 1; },
    clearTimeout() {},
    Event: function Event(type) { this.type = type; },
    console
};
vm.runInNewContext(instrumented, context);
context.window.testRouter.navigate = () => {};
context.window.testRouter.init();

function clickAction(action, attributes) {
    listeners.click.at(-1)({
        target: {
            closest() {
                return {
                    getAttribute(name) {
                        if (name === 'data-action') return action;
                        return (attributes || {})[name];
                    }
                };
            }
        }
    });
}

(async () => {
    // The Browse button opens the picker with the monitor-path field as target.
    clickAction('folder-picker', {
        'data-target': 'monitor-path-input', 'data-title': 'Choose folder'
    });
    const modal = elements['folder-picker-modal'];
    assert.ok(modal, 'folder picker modal is appended to the page');
    assert.match(modal.innerHTML, /Choose folder/);
    assert.match(modal.innerHTML, /Select this folder/);

    // An empty field makes the picker start at the filesystem root.
    await new Promise(setImmediate);
    assert.deepEqual(directories, [
        { method: 'GET', url: '/api/directories?path=%2F' }
    ]);

    // Selecting a folder queues it in the monitored list and closes the dialog.
    modal._listeners.click.at(-1)({
        target: {
            closest() {
                return {
                    getAttribute(name) {
                        if (name === 'data-action') return 'folder-select';
                        if (name === 'data-path') return '/opt/app';
                        return null;
                    }
                };
            }
        }
    });
    assert.match(listEl.innerHTML, /\/opt\/app/);
    assert.equal(input.value, '');
    assert.equal(modal._removed, true, 'picker closed after selection');
    console.log('Monitored folders picker opens, browses and queues the chosen folder');
})().catch(error => { console.error(error); process.exitCode = 1; });
