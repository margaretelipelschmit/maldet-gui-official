const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../gui/static/app.js'), 'utf8');
const instrumented = source.replace(
    '    function startScan() {',
    '    window.testStartScan = startScan;\n    function startScan() {'
);
assert.notEqual(instrumented, source);

const delays = [];
let sentUrl = '';
class Request {
    open(method, url) { sentUrl = `${method} ${url}`; }
    setRequestHeader() {}
    send() {}
    abort() {}
}

const elements = {
    scan_type: { value: 'all' },
    scan_path: { value: '/tmp', focus() {} },
    scan_days: { value: '2' },
    scan_engine: { value: 'native' },
    scan_co: { value: '' },
    scan_inc: { value: '' },
    scan_exc: { value: '' },
    scan_bg: { checked: true },
    'start-scan-btn': { disabled: false, textContent: '' },
    'toast-container': { appendChild() {} }
};
const context = {
    window: {},
    document: {
        addEventListener() {},
        getElementById(id) { return elements[id] || null; },
        createElement() { return { className: '', textContent: '' }; }
    },
    XMLHttpRequest: Request,
    localStorage: { getItem() { return 'en'; }, setItem() {} },
    setTimeout(callback, delay) { delays.push(delay); return delays.length; },
    setInterval() { return 1; },
    clearTimeout() {},
    clearInterval() {},
    console
};

vm.runInNewContext(instrumented, context);
context.window.testStartScan();

assert.equal(sentUrl, 'POST /api/scan');
assert.ok(delays.includes(70000), `expected 70-second timeout, got ${delays}`);
console.log('Scan start request timeout exceeds backend startup limit');
