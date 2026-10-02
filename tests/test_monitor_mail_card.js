const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../gui/static/app.js'), 'utf8');
const instrumented = source.replace(
    "    document.addEventListener('DOMContentLoaded', function() {",
    "    window.testMail = { render: renderMonitoring, save: saveMonitorMail, api: API };\n" +
    "    document.addEventListener('DOMContentLoaded', function() {"
);
assert.notEqual(instrumented, source, 'app.js test hook marker not found');

// Loads app.js with a stubbed API so renderMonitoring() can be driven directly.
function loadApp(options) {
    options = options || {};
    const mail = 'mail' in options ? options.mail : {
        detected: true,
        servers: ['postfix', 'dovecot'],
        maildirs: ['/var/mail', '/var/vmail/example.com'],
        autodetect: '1'
    };
    const posted = [];
    const toasts = [];
    const context = {
        window: {},
        document: {
            addEventListener() {},
            getElementById(id) {
                if (id === 'monitor-maildir-toggle') {
                    return options.toggle === undefined ? null :
                        { checked: options.toggle, disabled: !!options.toggleDisabled };
                }
                if (id === 'toast-container') return { appendChild(el) { toasts.push(el.textContent); } };
                return null;
            },
            // escapeHtml() relies on the DOM textContent -> innerHTML round-trip, so
        // emulate the escaping that a real element performs.
        createElement() {
            const el = { style: {}, classList: { add() {}, remove() {} }, setAttribute() {}, appendChild() {}, _text: '' };
            Object.defineProperty(el, 'textContent', {
                get() { return this._text; },
                set(value) {
                    this._text = String(value);
                    this.innerHTML = this._text
                        .replace(/&/g, '&amp;').replace(/</g, '&lt;')
                        .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
                }
            });
            return el;
        }
        },
        XMLHttpRequest: function() {},
        localStorage: { getItem() { return 'en'; } },
        sessionStorage: { getItem() { return null; }, setItem() {}, removeItem() {} },
        setInterval() { return 1; },
        clearInterval() {},
        setTimeout() { return 1; },
        clearTimeout() {},
        console
    };
    vm.runInNewContext(instrumented, context);
    assert.ok(context.window.testMail, 'app.js did not expose the mail test hook');
    const api = context.window.testMail.api;
    api.get = function(requestPath) {
        const table = {
            '/system': { system: { is_root: true, monitor_running: true } },
            '/monitor/users': { users: [] },
            '/monitor/webserver': { detected: false, servers: [], docroots: [], autodetect: '0' },
            '/monitor/mail': mail,
            '/monitor/activity': { running: false, entries: [] },
            '/monitor/scope': { scope: options.scope || 'users' },
            '/monitor/paths': { paths: [] }
        };
        if (!(requestPath in table)) return Promise.reject(new Error('unexpected GET ' + requestPath));
        return Promise.resolve(table[requestPath]);
    };
    api.post = function(requestPath, body) {
        posted.push({ path: requestPath, enabled: body.enabled });
        return Promise.resolve({ message: 'Monitoring of detected email folders ' + (body.enabled ? 'enabled' : 'disabled') });
    };
    return { mail: context.window.testMail, posted, toasts };
}

(async () => {
    // --- detected mail server: folders are listed and the toggle is checked ---
    const detected = loadApp();
    const detectedHtml = await detected.mail.render();
    assert.ok(detectedHtml.includes('monitor-mail-card'), 'email detection card is rendered');
    assert.ok(detectedHtml.includes('Email folder detection'), 'card is titled');
    assert.ok(detectedHtml.includes('postfix, dovecot'), 'detected servers are listed');
    assert.ok(detectedHtml.includes('/var/mail'), 'detected maildir is listed');
    assert.ok(detectedHtml.includes('/var/vmail/example.com'), 'detected vmail maildir is listed');
    assert.ok(detectedHtml.includes('id="monitor-maildir-toggle"'), 'the monitor toggle is present');
    assert.ok(detectedHtml.includes('data-action="monitor-save-mail"'), 'the save button is present');
    assert.ok(detectedHtml.includes('checked'), 'the toggle reflects autodetect=1');

    // --- autodetect=0 leaves the toggle unchecked ---
    const disabled = loadApp({ mail: { detected: true, servers: ['postfix'], maildirs: ['/var/mail'], autodetect: '0' } });
    const disabledHtml = await disabled.mail.render();
    assert.ok(disabledHtml.includes('id="monitor-maildir-toggle"'), 'toggle still rendered');
    assert.ok(!/monitor-maildir-toggle[^>]*checked/.test(disabledHtml), 'autodetect=0 renders an unchecked toggle');

    // --- no mail server detected ---
    const none = loadApp({ mail: { detected: false, servers: [], maildirs: [], autodetect: '0' } });
    const noneHtml = await none.mail.render();
    assert.ok(noneHtml.includes('No running mail server detected.'), 'reports no mail server');
    assert.ok(!noneHtml.includes('monitor-maildir-toggle'), 'no toggle without a detected server');

    // --- detection unavailable (endpoint failed) ---
    const unavailable = loadApp({ mail: {} });
    const unavailableHtml = await unavailable.mail.render();
    assert.ok(unavailableHtml.includes('Email folder detection is unavailable.'), 'reports unavailable detection');
    assert.ok(!unavailableHtml.includes('monitor-maildir-toggle'), 'no toggle when detection is unavailable');

    // --- webroot-only scope disables the toggle and the save button ---
    const webroots = loadApp({ scope: 'webroots' });
    const webrootsHtml = await webroots.mail.render();
    assert.ok(/monitor-maildir-toggle[^>]*disabled/.test(webrootsHtml), 'toggle is disabled in webroot-only mode');
    assert.ok(/data-action="monitor-save-mail"[^>]*disabled/.test(webrootsHtml), 'save is disabled in webroot-only mode');

    // --- clicking Save posts the toggle state ---
    const enabled = loadApp({ toggle: true });
    enabled.mail.save();
    await new Promise(setImmediate);
    await new Promise(setImmediate);
    assert.deepEqual(enabled.posted, [{ path: '/monitor/mail', enabled: true }]);
    assert.deepEqual(enabled.toasts, ['Monitoring of detected email folders enabled']);

    const off = loadApp({ toggle: false });
    off.mail.save();
    await new Promise(setImmediate);
    await new Promise(setImmediate);
    assert.deepEqual(off.posted, [{ path: '/monitor/mail', enabled: false }]);
    assert.deepEqual(off.toasts, ['Monitoring of detected email folders disabled']);

    // --- a disabled toggle is ignored ---
    const locked = loadApp({ toggle: true, toggleDisabled: true });
    locked.mail.save();
    await new Promise(setImmediate);
    assert.deepEqual(locked.posted, [], 'a disabled toggle does not dispatch a request');

    console.log('Monitoring email card renders detected mail servers and folders and posts the monitor toggle to /api/monitor/mail');

})().catch(error => { console.error(error); process.exitCode = 1; });
