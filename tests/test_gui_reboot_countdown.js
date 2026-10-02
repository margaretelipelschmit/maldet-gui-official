const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../gui/static/app.js'), 'utf8');
const instrumented = source.replace(
    "    document.addEventListener('DOMContentLoaded', function() {",
    "    window.testReboot = { start: startRebootCountdown, resume: resumeRebootCountdown, " +
    "update: updateRebootCountdown, format: formatRebootCountdown, initButton: initRebootButton, api: API, " +
    "state: function() { return { timer: _rebootCountdownTimerEl, text: _rebootCountdownTextEl, " +
    "deadline: _rebootCountdownDeadline, interval: _rebootCountdownInterval, " +
    "pollTimer: _rebootPollTimer, pollSawDown: _rebootPollSawDown, " +
    "pollIntervalMs: REBOOT_POLL_INTERVAL_SECONDS * 1000, pollGraceMs: REBOOT_POLL_GRACE_SECONDS * 1000, " +
    "pollMaxMs: REBOOT_POLL_MAX_SECONDS * 1000 }; } };\n" +
    "    document.addEventListener('DOMContentLoaded', function() {"
);
assert.notEqual(instrumented, source, 'app.js test hook marker not found');

function createElement() {
    return {
        className: '',
        id: '',
        textContent: '',
        attrs: {},
        children: [],
        setAttribute(name, value) { this.attrs[name] = value; },
        appendChild(child) { this.children.push(child); return child; },
        removeChild() {}
    };
}

// Loads app.js in a fresh sandbox with a controllable clock and storage.
function loadApp(now, seed) {
    const state = {
        now, storage: Object.assign({}, seed), body: [], intervals: new Map(), cleared: [],
        timeouts: new Map(), nextTimerId: 0, reloads: 0,
        nextId: 0, confirmed: true, clickHandler: null, toasts: [], posted: null,
        serverUp: true, requests: [],
        rebootBtn: { disabled: false, addEventListener(event, listener) {
            if (event === 'click') state.clickHandler = listener;
        } }
    };
    // Minimal XMLHttpRequest stub emulating the public health endpoint. `send`
    // resolves synchronously so the tests can drive one poll tick at a time.
    function FakeXHR() {
        this.readyState = 0;
        this.status = 0;
        this.responseText = '';
        this.url = '';
    }
    FakeXHR.prototype.open = function(method, url) { this.method = method; this.url = url; };
    FakeXHR.prototype.setRequestHeader = function() {};
    FakeXHR.prototype.abort = function() {};
    FakeXHR.prototype.send = function() {
        state.requests.push(this.url);
        this.readyState = 4;
        if (state.serverUp) {
            this.status = 200;
            this.responseText = '{}';
            if (this.onreadystatechange) this.onreadystatechange();
        } else if (this.onerror) {
            this.status = 0;
            this.onerror();
        }
    };
    const context = {
        XMLHttpRequest: FakeXHR,
        window: { location: { reload() { state.reloads += 1; } } },
        Date: { now: () => state.now },
        confirm() { return state.confirmed; },
        localStorage: { getItem() { return 'en'; } },
        sessionStorage: {
            getItem(key) { return key in state.storage ? state.storage[key] : null; },
            setItem(key, value) { state.storage[key] = String(value); },
            removeItem(key) { delete state.storage[key]; }
        },
        document: {
            addEventListener() {},
            getElementById(id) {
                if (id === 'system-reboot-btn') return state.rebootBtn;
                if (id === 'toast-container') return { appendChild(el) { state.toasts.push(el.textContent); } };
                if (['sidebar-nav', 'refresh-btn', 'content'].includes(id)) return { addEventListener() {} };
                return null;
            },
            createElement,
            body: { appendChild(el) { state.body.push(el); return el; } },
            documentElement: { appendChild(el) { state.body.push(el); return el; } }
        },
        setInterval(fn, ms) {
            state.nextId += 1;
            state.intervals.set(state.nextId, { fn, ms });
            return state.nextId;
        },
        clearInterval(id) { state.intervals.delete(id); state.cleared.push(id); },
        setTimeout(fn, ms) {
            state.nextTimerId += 1;
            state.timeouts.set(state.nextTimerId, { fn, ms });
            return state.nextTimerId;
        },
        clearTimeout(id) { state.timeouts.delete(id); },
        console
    };
    vm.runInNewContext(instrumented, context);
    assert.ok(context.window.testReboot, 'app.js did not expose the reboot test hook');
    return { reboot: context.window.testReboot, state };
}

// Drives exactly one tick of the reboot reload poller.
function runPoll(app) {
    const pollMs = app.reboot.state().pollIntervalMs;
    const entry = [...app.state.intervals.values()].find(i => i.ms === pollMs);
    assert.ok(entry, 'the reload poller is running');
    entry.fn();
}

// --- format ---
const formatApp = loadApp(1700000000000);
assert.equal(formatApp.reboot.format(60), '01:00');
assert.equal(formatApp.reboot.format(59), '00:59');
assert.equal(formatApp.reboot.format(5), '00:05');
assert.equal(formatApp.reboot.format(0), '00:00');
assert.equal(formatApp.reboot.format(125), '02:05');

// --- start(60) renders overlay and ticks down ---
const app = loadApp(1700000000000);
const { reboot } = app;
reboot.start(60);
let snapshot = reboot.state();
assert.equal(snapshot.deadline, 1700000000000 + 60000, 'deadline is now + 60s');
assert.equal(snapshot.timer.textContent, '01:00', 'timer starts at 01:00');
assert.equal(snapshot.text.textContent, 'The server will restart in');
assert.equal(app.state.body.length, 1, 'one overlay is appended to the body');
assert.equal(app.state.body[0].className, 'reboot-countdown-overlay');
assert.equal(app.state.body[0].attrs.role, 'alertdialog');
assert.equal(app.state.body[0].children[0].className, 'reboot-countdown-card');
assert.equal(app.state.body[0].children[0].children[0].className, 'reboot-countdown-icon');
assert.ok(app.state.body[0].children[0].children.some(c => c.textContent === '01:00'),
    'card contains the 01:00 timer');
assert.equal(app.state.intervals.get(snapshot.interval).ms, 1000, 'tick interval is one second');
assert.equal(app.state.storage['maldet.gui.rebootDeadline'], String(1700000000000 + 60000),
    'deadline persisted for reload resume');

app.state.now += 5000;
reboot.update();
assert.equal(snapshot.timer.textContent, '00:55', 'timer counts down to 00:55 after 5s');

// --- double click restarts, does not stack overlays/interval ---
app.state.now += 10000;
reboot.start(60);
snapshot = reboot.state();
assert.equal(snapshot.deadline, app.state.now + 60000, 'second start resets the deadline');
assert.equal(snapshot.timer.textContent, '01:00');
assert.equal(app.state.body.length, 1, 'overlay is reused on a second start');
assert.deepEqual(app.state.cleared, [snapshot.interval - 1], 'previous interval cleared');

// --- reaches zero ---
app.state.now += 60000;
reboot.update();
snapshot = reboot.state();
assert.equal(snapshot.timer.textContent, '00:00');
assert.equal(snapshot.text.textContent, 'Restarting now...');
assert.equal(snapshot.interval, null, 'interval stops at zero');
assert.ok(!('maldet.gui.rebootDeadline' in app.state.storage), 'deadline cleared at zero');

// --- once the countdown ends, the page polls the public health endpoint so the
//     GUI reconnects to the restarted server on its own ---
assert.equal(snapshot.pollIntervalMs, 5000, 'the server is probed every 5 seconds after zero');
assert.ok(snapshot.pollTimer, 'a reload poller is scheduled at zero');
assert.equal(app.state.reloads, 0, 'no reload fires immediately at zero');

// Repeated ticks at zero must not stack pollers.
const pollerId = snapshot.pollTimer;
reboot.update();
reboot.update();
assert.equal(reboot.state().pollTimer, pollerId, 'ticks at zero do not reset the poller');
const pollers = [...app.state.intervals.values()].filter(i => i.ms === snapshot.pollIntervalMs);
assert.equal(pollers.length, 1, 'exactly one reload poller is running');

// The host stays reachable for the whole grace window: no reload until it ends.
assert.equal(app.state.serverUp, true);
app.state.now += 5000;
runPoll(app);
assert.equal(app.state.reloads, 0, 'an up server inside the grace window does not reload yet');
assert.equal(reboot.state().pollSawDown, false, 'no outage recorded while still up');

app.state.now += snapshot.pollGraceMs - 5000;
runPoll(app);
assert.equal(app.state.reloads, 1, 'reloads once the grace window elapses and the server is up');
assert.equal(reboot.state().pollTimer, null, 'the poller stops after reloading');
assert.ok(app.state.requests.length >= 2 &&
    app.state.requests.every(u => u === '/api/auth/status'),
    'probes the public /api/auth/status endpoint');

// --- reboot observed end to end: host drops, then answers again ---
const downApp = loadApp(1700000000000);
downApp.reboot.start(60);
downApp.state.now += 60000;
downApp.reboot.update();
assert.equal(downApp.state.reloads, 0, 'no reload at zero while the host is still up');

downApp.state.serverUp = false;
downApp.state.now += 5000;
runPoll(downApp);
assert.equal(downApp.state.reloads, 0, 'a down server does not reload');
assert.equal(downApp.reboot.state().pollSawDown, true, 'the outage is recorded');

downApp.state.serverUp = false;
downApp.state.now += 5000;
runPoll(downApp);
assert.equal(downApp.state.reloads, 0, 'a server that is still down does not reload');

downApp.state.serverUp = true;
downApp.state.now += 5000;
runPoll(downApp);
assert.equal(downApp.state.reloads, 1, 'reloads as soon as the server answers again');
assert.equal(downApp.reboot.state().pollTimer, null, 'the poller stops after the reconnect reload');

// --- a server that never comes back stops probing without a reload ---
const deadApp = loadApp(1700000000000);
deadApp.reboot.start(60);
deadApp.state.now += 60000;
deadApp.reboot.update();
deadApp.state.serverUp = false;
deadApp.state.now += deadApp.reboot.state().pollMaxMs;
runPoll(deadApp);
assert.equal(deadApp.state.reloads, 0, 'a server that never recovers does not reload');
assert.equal(deadApp.reboot.state().pollTimer, null, 'the poller gives up after the max window');

// --- resume after reload continues the countdown ---
const resumeApp = loadApp(1700000000000, { 'maldet.gui.rebootDeadline': String(1700000000000 + 30000) });
resumeApp.reboot.resume();
snapshot = resumeApp.reboot.state();
assert.equal(resumeApp.state.body.length, 1, 'resume renders the overlay');
assert.equal(snapshot.timer.textContent, '00:30', 'resume keeps the remaining time');
assert.equal(snapshot.text.textContent, 'The server will restart in');
assert.equal(snapshot.interval, 1, 'resume restarts the ticker');

// --- stale deadline is discarded instead of shown ---
const staleApp = loadApp(1700000000000, { 'maldet.gui.rebootDeadline': String(1700000000000 - 1000) });
staleApp.reboot.resume();
assert.equal(staleApp.state.body.length, 0, 'past deadline does not render an overlay');
assert.ok(!('maldet.gui.rebootDeadline' in staleApp.state.storage), 'past deadline is cleared');

// --- nothing to resume ---
const idleApp = loadApp(1700000000000);
idleApp.reboot.resume();
assert.equal(idleApp.state.body.length, 0, 'no deadline means no overlay');

// --- the actual button click wires confirm -> POST -> countdown ---
(async () => {
    const clickApp = loadApp(1700000000000);
    clickApp.reboot.initButton();
    assert.equal(typeof clickApp.state.clickHandler, 'function', 'click handler is attached');

    clickApp.reboot.api.post = (requestPath, requestBody) => {
        clickApp.state.posted = { path: requestPath, body: requestBody };
        return Promise.resolve({ message: 'System reboot scheduled in one minute' });
    };
    clickApp.state.clickHandler();
    assert.equal(clickApp.state.rebootBtn.disabled, true, 'button is disabled while posting');
    assert.equal(clickApp.state.posted.path, '/system/reboot');
    // requestBody comes from the vm realm, so compare it structurally.
    assert.equal(JSON.stringify(clickApp.state.posted.body), '{}');
    await new Promise(setImmediate);
    await new Promise(setImmediate);
    assert.equal(clickApp.state.body.length, 1, 'countdown overlay appears once the API accepts');
    assert.equal(clickApp.reboot.state().timer.textContent, '01:00', 'countdown starts at 01:00');
    assert.equal(clickApp.state.rebootBtn.disabled, false, 'button is re-enabled after success');

    // Declining the confirm must not call the API nor show the timer.
    const declineApp = loadApp(1700000000000);
    declineApp.state.confirmed = false;
    declineApp.reboot.initButton();
    declineApp.reboot.api.post = () => { declineApp.state.posted = { path: 'called' }; return Promise.resolve({}); };
    declineApp.state.clickHandler();
    await new Promise(setImmediate);
    assert.equal(declineApp.state.posted, null, 'declined confirm does not call the API');
    assert.equal(declineApp.state.body.length, 0, 'declined confirm does not show the timer');

    // A failed POST reports the error instead of starting the countdown.
    const failApp = loadApp(1700000000000);
    failApp.reboot.initButton();
    failApp.reboot.api.post = () => Promise.reject(new Error('Reboot requires the WebGUI to run as root'));
    failApp.state.clickHandler();
    await new Promise(setImmediate);
    await new Promise(setImmediate);
    assert.equal(failApp.state.body.length, 0, 'failed POST does not show the timer');
    assert.equal(failApp.state.rebootBtn.disabled, false, 'button is re-enabled after failure');
    assert.deepEqual(failApp.state.toasts, ['Error: Reboot requires the WebGUI to run as root']);

    console.log('Reboot click renders a regressive 01:00 timer, ticks down, resumes after reload, clears at zero and polls the server until it is back to refresh automatically');
})().catch(error => { console.error(error); process.exitCode = 1; });
