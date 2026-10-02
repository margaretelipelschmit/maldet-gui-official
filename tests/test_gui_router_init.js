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

const documentListeners = {};
const elementListeners = {};
const elements = {
    'sidebar-nav': { addEventListener(type, listener) {
        (elementListeners['sidebar-nav:' + type] ||= []).push(listener);
    } },
    'refresh-btn': { addEventListener(type, listener) {
        (elementListeners['refresh-btn:' + type] ||= []).push(listener);
    } },
    'page-title': { textContent: '' },
    content: { innerHTML: '', addEventListener(type, listener) {
        (elementListeners['content:' + type] ||= []).push(listener);
    } }
};
const document = {
    addEventListener(type, listener) {
        (documentListeners[type] ||= []).push(listener);
    },
    getElementById(id) { return elements[id] || null; },
    querySelectorAll() { return []; },
    body: { querySelectorAll() { return []; } }
};

const context = {
    window: {},
    document,
    localStorage: { getItem() { return 'en'; }, setItem() {} },
    setTimeout() { return 1; },
    clearTimeout() {},
    setInterval() { return 1; },
    clearInterval() {},
    console
};
vm.runInNewContext(instrumented, context);
context.window.testRouter.routes.dashboard = null;
context.window.testRouter.init();
context.window.testRouter.init();

assert.equal(documentListeners.click.length, 2);
assert.equal(elementListeners['sidebar-nav:click'].length, 1);
assert.equal(elementListeners['refresh-btn:click'].length, 1);
assert.equal(elementListeners['content:click'], undefined);
console.log('Repeated Router.init() does not duplicate document click handlers');
