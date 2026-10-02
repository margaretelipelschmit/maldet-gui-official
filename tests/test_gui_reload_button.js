const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../gui/static/app.js'), 'utf8');
const instrumented = source.replace(
    "    document.addEventListener('DOMContentLoaded', function() {",
    "    window.testReload = { initButton: initReloadGuiButton, start: startGuiReloadCountdown, " +
    "resume: resumeGuiReloadCountdown, format: formatRebootCountdown, api: API, " +
    "state: function() { var card = _rebootCountdownOverlay ? _rebootCountdownOverlay.children[0] : null; " +
    "return { timer: _rebootCountdownTimerEl, text: _rebootCountdownTextEl, " +
    "title: card ? card.children[1].textContent : null, hint: card ? card.children[4].textContent : null, " +
    "deadline: _rebootCountdownDeadline, interval: _rebootCountdownInterval, pollTimer: _rebootPollTimer, " +
    "storageKey: _countdownStorageKey, countdownSeconds: GUI_RELOAD_COUNTDOWN_SECONDS }; } };\n" +
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
        timeouts: new Map(), nextTimerId: 0, nextId: 0, confirmed: true, clickHandler: null,
        toasts: [], posted: null,
        reloadBtn: { disabled: false, addEventListener(event, listener) {
            if (event === 'click') state.clickHandler = listener;
        } }
    };
    const context = {
        window: { location: { reload() {} } },
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
                if (id === 'reload-gui-btn') return state.reloadBtn;
                if (id === 'toast-container') return { appendChild(el) { state.toasts.push(el.textContent); } };
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
    assert.ok(context.window.testReload, 'app.js did not expose the reload test hook');
    return { reload: context.window.testReload, state };
}

// --- the countdown window is 10 seconds and formats as 00:10 ---
const baseApp = loadApp(1700000000000);
assert.equal(baseApp.reload.state().countdownSeconds, 10, 'reload countdown is 10s');
assert.equal(baseApp.reload.format(10), '00:10');

// --- start(10) renders the reload overlay, stores the deadline, ticks 1s ---
const startApp = loadApp(1700000000000);
startApp.reload.start(10);
let snapshot = startApp.reload.state();
assert.equal(snapshot.deadline, 1700000000000 + 10000, 'deadline is now + 10s');
assert.equal(snapshot.timer.textContent, '00:10', 'timer starts at 00:10');
assert.equal(snapshot.text.textContent, 'The WebGUI will restart in');
assert.equal(snapshot.title, 'WebGUI restart scheduled');
assert.equal(snapshot.storageKey, 'maldet.gui.reloadDeadline');
assert.equal(startApp.state.storage['maldet.gui.reloadDeadline'], String(1700000000000 + 10000));
assert.equal(startApp.state.body.length, 1, 'one overlay is appended to the body');
assert.equal(startApp.state.body[0].className, 'reboot-countdown-overlay');
assert.equal(startApp.state.body[0].id, 'reload-countdown');
assert.equal(startApp.state.intervals.get(snapshot.interval).ms, 1000, 'tick interval is one second');

// --- resume keeps the remaining time after a manual refresh ---
const resumeApp = loadApp(1700000000000, { 'maldet.gui.reloadDeadline': String(1700000000000 + 4000) });
resumeApp.reload.resume();
snapshot = resumeApp.reload.state();
assert.equal(snapshot.timer.textContent, '00:04', 'resume keeps the remaining time');
assert.equal(snapshot.text.textContent, 'The WebGUI will restart in');
assert.equal(resumeApp.state.body.length, 1, 'resume renders the overlay');

// --- a stale deadline is discarded instead of shown ---
const staleApp = loadApp(1700000000000, { 'maldet.gui.reloadDeadline': String(1700000000000 - 1000) });
staleApp.reload.resume();
assert.equal(staleApp.state.body.length, 0, 'past deadline does not render an overlay');
assert.ok(!('maldet.gui.reloadDeadline' in staleApp.state.storage), 'past deadline is cleared');

// --- nothing to resume ---
const idleApp = loadApp(1700000000000);
idleApp.reload.resume();
assert.equal(idleApp.state.body.length, 0, 'no deadline means no overlay');

// --- the actual button click wires confirm -> POST /system/reload -> countdown ---
(async () => {
    const clickApp = loadApp(1700000000000);
    clickApp.reload.initButton();
    assert.equal(typeof clickApp.state.clickHandler, 'function', 'click handler is attached');

    clickApp.reload.api.post = (requestPath, requestBody) => {
        clickApp.state.posted = { path: requestPath, body: requestBody };
        return Promise.resolve({ message: 'WebGUI reload scheduled in 10 seconds' });
    };
    clickApp.state.clickHandler();
    assert.equal(clickApp.state.reloadBtn.disabled, true, 'button is disabled while posting');
    assert.equal(clickApp.state.posted.path, '/system/reload');
    assert.equal(JSON.stringify(clickApp.state.posted.body), '{}');
    await new Promise(setImmediate);
    await new Promise(setImmediate);
    assert.equal(clickApp.state.body.length, 1, 'countdown overlay appears once the API accepts');
    assert.equal(clickApp.reload.state().timer.textContent, '00:10', 'countdown starts at 00:10');
    assert.equal(clickApp.reload.state().text.textContent, 'The WebGUI will restart in');
    assert.equal(clickApp.state.reloadBtn.disabled, false, 'button is re-enabled after success');

    // Declining the confirm must not call the API nor show the timer.
    const declineApp = loadApp(1700000000000);
    declineApp.state.confirmed = false;
    declineApp.reload.initButton();
    declineApp.reload.api.post = () => { declineApp.state.posted = { path: 'called' }; return Promise.resolve({}); };
    declineApp.state.clickHandler();
    await new Promise(setImmediate);
    assert.equal(declineApp.state.posted, null, 'declined confirm does not call the API');
    assert.equal(declineApp.state.body.length, 0, 'declined confirm does not show the timer');

    // A failed POST reports the error instead of starting the countdown.
    const failApp = loadApp(1700000000000);
    failApp.reload.initButton();
    failApp.reload.api.post = () => Promise.reject(new Error('Reload requires the WebGUI to run as root'));
    failApp.state.clickHandler();
    await new Promise(setImmediate);
    await new Promise(setImmediate);
    assert.equal(failApp.state.body.length, 0, 'failed POST does not show the timer');
    assert.equal(failApp.state.reloadBtn.disabled, false, 'button is re-enabled after failure');
    assert.deepEqual(failApp.state.toasts, ['Error: Reload requires the WebGUI to run as root']);

    console.log('Reload WebGUI posts /system/reload and shows a 00:10 countdown that resumes across a refresh');
})().catch(error => { console.error(error); process.exitCode = 1; });


