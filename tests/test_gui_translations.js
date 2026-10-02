const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../gui/static/app.js'), 'utf8');
const instrumented = source.replace(
    '    function translateDom(root) {',
    '    window.testTranslate = tr;\n    function translateDom(root) {'
);
assert.notEqual(instrumented, source);

const context = {
    window: {},
    document: {
        addEventListener() {},
        documentElement: { lang: 'en' },
        querySelectorAll() { return []; },
        body: { querySelectorAll() { return []; } }
    },
    localStorage: { getItem() { return 'pt-BR'; }, setItem() {} },
    setTimeout() { return 1; },
    setInterval() { return 1; },
    clearTimeout() {},
    clearInterval() {},
    console
};

vm.runInNewContext(instrumented, context);
const tr = context.window.testTranslate;
assert.equal(tr('Restore failed: permission denied'), 'Falha ao restaurar: permission denied');
assert.equal(
    tr('Discard the checkpoint for scan ') + '123' +
        tr('? This cannot be undone and the scan will no longer be resumable.'),
    'Descartar o ponto de retomada do scan 123? Esta ação não pode ser desfeita e o scan não poderá mais ser retomado.'
);
assert.equal(tr('A message without a catalog entry'), 'A message without a catalog entry');

console.log('pt-BR translation lookup covers exact messages and translated dynamic prefixes');
