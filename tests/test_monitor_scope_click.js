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

let scope = 'webroots';
const listeners = {};
const requests = [];
const notifications = [];
const navigation = [];
class Request {
    open(method, url) { this.method = method; this.url = url; }
    setRequestHeader() {}
    send(body) {
        requests.push({ method: this.method, url: this.url, body: JSON.parse(body) });
        this.status = 200;
        this.responseText = '{"message":"Monitor scope saved"}';
        this.readyState = 4;
        this.onreadystatechange();
    }
}
const context = {
    window: {},
    document: {
        addEventListener(event, listener) { (listeners[event] ||= []).push(listener); },
        getElementById(id) {
            if (id === 'monitor-scope') return { value: scope };
            if (id === 'toast-container') return { appendChild(el) { notifications.push(el.textContent); } };
            if (['sidebar-nav', 'refresh-btn', 'content'].includes(id)) {
                return { addEventListener() {} };
            }
            return null;
        },
        createElement() { return {}; }
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
function clickSave() {
    listeners.click.at(-1)({
        target: { closest() { return { getAttribute() { return 'monitor-save-scope'; } }; } }
    });
}

(async () => {
    clickSave();
    await new Promise(setImmediate);
    assert.deepEqual(requests, [{
        method: 'PUT', url: '/api/monitor/scope', body: { scope: 'webroots' }
    }]);
    assert.deepEqual(navigation, ['monitoring']);
    assert.deepEqual(notifications, ['Monitor scope saved']);

    scope = 'custom';
    clickSave();
    assert.equal(requests.length, 1);
    console.log('Monitor scope click dispatches PUT and ignores unsupported custom scope');
})().catch(error => { console.error(error); process.exitCode = 1; });
