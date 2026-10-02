const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../gui/static/app.js'), 'utf8');
const instrumented = source.replace(
    "    document.addEventListener('DOMContentLoaded', function() {",
    "    window.testSystem = { render: renderSystemInfo, api: API };\n" +
    "    document.addEventListener('DOMContentLoaded', function() {"
);
assert.notEqual(source, instrumented);
const context = {
    window: {},
    localStorage: { getItem() { return 'en'; } },
    document: {
        addEventListener() {},
        createElement() {
            let value = '';
            return {
                set textContent(text) { value = String(text); },
                get innerHTML() {
                    return value.replace(/&/g, '&amp;').replace(/</g, '&lt;')
                        .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
                }
            };
        }
    },
    console
};
vm.runInNewContext(instrumented, context);
const system = context.window.testSystem;
const info = {
    hostname: '<host>', system: 'Linux', release: '6.0', machine: 'x86_64',
    cpu: 'Test CPU', cpu_cores: 4, mem_total_mb: 1000, mem_available_mb: 250,
    disk_total_gb: 200, disk_free_gb: 50, monitor_running: true, active_scans: [],
    binaries: { clamscan: '/usr/bin/clamscan', yara: '' }, version: '2.0'
};
system.api.get = endpoint => Promise.resolve(endpoint === '/system'
    ? { system: info }
    : { cpu_percent: 42, mem_total_mb: 1000, mem_available_mb: 250 });

(async () => {
    let html = await system.render();
    assert.match(html, /&lt;host&gt;/);
    assert.doesNotMatch(html, /<host>/);
    assert.match(html, /aria-label="CPU"[^>]*aria-valuenow="42"/);
    assert.match(html, /aria-label="RAM"[^>]*aria-valuenow="75"/);
    assert.match(html, /aria-label="Disk"[^>]*aria-valuenow="75"/);
    assert.match(html, /Active Scans: 0/);
    assert.match(html, /\/usr\/bin\/clamscan/);
    assert.match(html, /not found/);

    system.api.get = endpoint => endpoint === '/system'
        ? Promise.resolve({ system: { ...info, disk_total_gb: 0, mem_total_mb: 0 } })
        : Promise.reject(new Error('usage unavailable'));
    html = await system.render();
    for (const metric of ['CPU', 'RAM', 'Disk']) {
        assert.match(html, new RegExp('aria-label="' + metric + '"[^>]*aria-valuemax="100"(?![^>]*aria-valuenow)'));
    }
    assert.doesNotMatch(html, /NaN%|Infinity%/);
    console.log('System Info layout renders resource bars, escaped details and unavailable metrics');
})().catch(error => { console.error(error); process.exitCode = 1; });
