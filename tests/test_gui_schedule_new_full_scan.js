const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../gui/static/app.js'), 'utf8');
const instrumented = source.replace(
    '    function openScheduleModal(id) {',
    '    window.testOpenScheduleModal = openScheduleModal;\n' +
    '    function openScheduleModal(id) {'
);
assert.notEqual(instrumented, source);

const created = [];
const context = {
    window: {},
    document: {
        addEventListener() {},
        getElementById() { return null; },
        createElement() {
            const element = { addEventListener() {}, innerHTML: '', id: '', className: '' };
            created.push(element);
            return element;
            return modal;
        },
        body: { appendChild() {} }
    },
    localStorage: { getItem() { return 'en'; }, setItem() {} },
    setTimeout() { return 1; },
    setInterval() { return 1; },
    clearTimeout() {},
    clearInterval() {},
    console
};

vm.runInNewContext(instrumented, context);
context.window.testOpenScheduleModal(null);
const modal = created.find(element => element.id === 'schedule-modal');
assert.ok(modal);
assert.match(modal.innerHTML, /id="sch_scan_type" value="all"/);
assert.match(modal.innerHTML, /Full scan \(all files\)/);
assert.doesNotMatch(modal.innerHTML, /<option value="recent"/);

console.log('New schedules offer only full scans');
