const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../gui/static/app.js'), 'utf8');
const hook = '    function restoreAllQuarantineFiles() {';
const instrumented = source.replace(
    hook,
    '    window.testRestoreAllQuarantineFiles = restoreAllQuarantineFiles;\n' +
    '    window.testRouter = Router;\n' + hook
);
assert.notEqual(instrumented, source);

const filenames = Array.from({ length: 83 }, (_, i) => `quarantine.${i}`);
const allButton = { disabled: false, textContent: 'Restore all' };
const toasts = [];
const requests = [];
const timeouts = [];
let navigation = '';

class Request {
    open(method, url) {
        this.method = method;
        this.url = url;
    }
    setRequestHeader() {}
    send(body) {
        const request = { method: this.method, url: this.url, body: JSON.parse(body) };
        requests.push(request);
        const failed = Number(request.body.file.split('.').at(-1)) % 13 === 0;
        this.status = failed ? 400 : 200;
        this.responseText = failed
            ? JSON.stringify({ error: 'restore failed' })
            : JSON.stringify({ returncode: 0 });
        this.readyState = 4;
        this.onreadystatechange();
    }
}

const context = {
    window: {},
    confirm: () => true,
    document: {
        addEventListener() {},
        querySelectorAll(selector) {
            if (selector === '[data-action="quarantine-restore-all"]') return [allButton];
            if (selector === '[data-action="quarantine-restore"]') {
                return filenames.map(name => ({
                    getAttribute: () => name
                }));
            }
            return [];
        },
        getElementById(id) {
            if (id === 'toast-container') {
                return { appendChild(el) { toasts.push(el.textContent); } };
            }
            return null;
        },
        createElement() { return {}; }
    },
    XMLHttpRequest: Request,
    localStorage: { getItem() { return null; }, setItem() {} },
    setTimeout(callback, timeout) { timeouts.push(timeout); return 1; },
    clearTimeout() {},
    console
};

vm.runInNewContext(instrumented, context);
context.window.testRouter.navigate = page => { navigation = page; };
context.window.testRestoreAllQuarantineFiles();

setImmediate(() => {
    const failedCount = filenames.filter((_, i) => i % 13 === 0).length;
    assert.equal(requests.length, filenames.length);
    assert.ok(requests.every(request =>
        request.method === 'POST' && request.url === '/api/quarantine/restore'));
    assert.deepEqual(requests.map(request => request.body.file), filenames);
    assert.equal(timeouts.filter(timeout => timeout === 40000).length, filenames.length);
    assert.match(toasts[0], new RegExp(`Restored ${filenames.length - failedCount}; failed: ${failedCount}`));
    assert.equal(navigation, 'quarantine');
    console.log(`Restore-all processes ${filenames.length} files individually and continues after failures`);
});
