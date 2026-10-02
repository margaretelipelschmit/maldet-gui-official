const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../gui/static/app.js'), 'utf8');
const instrumented = source.replace(
    "    document.addEventListener('DOMContentLoaded', function() {",
    "    window.testRouter = Router;\n" +
    "    document.addEventListener('DOMContentLoaded', function() {"
);
assert.notEqual(instrumented, source);

const listeners = {};
const requests = [];
const notifications = [];
const navigation = [];
const input = { value: '', focus() {} };
const listEl = { innerHTML: '' };

class Request {
    open(method, url) { this.method = method; this.url = url; }
    setRequestHeader() {}
    send(body) {
        requests.push({ method: this.method, url: this.url, body: JSON.parse(body) });
        this.status = 200;
        this.responseText = '{"message":"Monitored folders saved"}';
        this.readyState = 4;
        this.onreadystatechange();
    }
}
const context = {
    window: {},
    document: {
        addEventListener(event, listener) { (listeners[event] ||= []).push(listener); },
        getElementById(id) {
            if (id === 'monitor-path-input') return input;
            if (id === 'monitor-path-list') return listEl;
            if (id === 'toast-container') return { appendChild(el) { notifications.push(el.textContent); } };
            if (['sidebar-nav', 'refresh-btn', 'content'].includes(id)) {
                return { addEventListener() {} };
            }
            return null;
        },
        // Minimal element stub: escapeHtml() sets textContent and reads
        // innerHTML, while toast() sets textContent and it is read back.
        createElement() {
            const el = { innerHTML: '' };
            let text = '';
            Object.defineProperty(el, 'textContent', {
                get() { return text; },
                set(value) { text = String(value); this.innerHTML = text; }
            });
            return el;
        }
    },
    XMLHttpRequest: Request,
    localStorage: { getItem() { return null; } },
    setTimeout() { return 1; },
    clearTimeout() {},
    console
};
vm.runInNewContext(instrumented, context);
context.window.testRouter.navigate = page => navigation.push(page);
context.window.testRouter.init();
navigation.length = 0;

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
function pressEnter() {
    listeners.keydown.at(-1)({ key: 'Enter', target: { id: 'monitor-path-input' }, preventDefault() {} });
}

(async () => {
    // Enter in the field adds the folder to the pending list and clears it.
    input.value = '/var/www/html';
    pressEnter();
    assert.match(listEl.innerHTML, /\/var\/www\/html/);
    assert.equal(input.value, '');

    // Trailing slashes are trimmed and duplicates are rejected.
    input.value = '/srv/data/';
    clickAction('monitor-add-path');
    assert.match(listEl.innerHTML, /\/srv\/data</);
    assert.doesNotMatch(listEl.innerHTML, /\/srv\/data\//);
    input.value = '/srv/data';
    clickAction('monitor-add-path');
    assert.deepEqual(notifications, ['Folder already in the list.']);

    // Relative paths are rejected client-side.
    input.value = 'var/log';
    clickAction('monitor-add-path');
    assert.equal(notifications.at(-1), 'Absolute path required (e.g. /var/www).');

    // Removing a row drops it from the pending list.
    clickAction('monitor-remove-path', { 'data-path': '/var/www/html' });
    assert.doesNotMatch(listEl.innerHTML, /\/var\/www\/html/);
    assert.match(listEl.innerHTML, /\/srv\/data</);

    // Saving dispatches a single PUT with the remaining paths.
    clickAction('monitor-save-paths');
    await new Promise(setImmediate);
    assert.deepEqual(requests, [{
        method: 'PUT', url: '/api/monitor/paths', body: { paths: ['/srv/data'] }
    }]);
    assert.deepEqual(navigation, ['monitoring']);
    assert.equal(notifications.at(-1), 'Monitored folders saved');
    console.log('Monitor folders click flow adds, removes and saves PUT /api/monitor/paths');
})().catch(error => { console.error(error); process.exitCode = 1; });
