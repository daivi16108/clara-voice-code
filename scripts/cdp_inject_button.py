"""Inject a Push-to-Talk mic button into Claude Code chat via CDP.

The button is placed next to the Send button in the chat footer.
A MutationObserver re-injects it if the DOM is re-rendered.
Communication back to the extension uses localStorage signals,
polled by a CDP listener or file-based IPC.
"""
import json, os, sys, tempfile, time, urllib.request
import websocket

port = 9222
workspace = None
if "--port" in sys.argv:
    i = sys.argv.index("--port")
    if i + 1 < len(sys.argv):
        port = int(sys.argv[i + 1])
if "--workspace" in sys.argv:
    i = sys.argv.index("--workspace")
    if i + 1 < len(sys.argv):
        workspace = sys.argv[i + 1]

t0 = time.perf_counter()

# --- Reuse cached target from cdp_inject.py ---
CACHE_FILE = os.path.join(tempfile.gettempdir(), "voice-claude-cdp-cache.json")
PTT_CMD_FILE = os.path.join(tempfile.gettempdir(), "voice-claude-ptt.json")

def load_cache():
    try:
        with open(CACHE_FILE, "r") as f:
            data = json.load(f)
        if time.time() - data.get("ts", 0) > 3600:
            return None
        return data
    except Exception:
        return None

def save_cache(ws_url, context_id):
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump({"ws_url": ws_url, "context_id": context_id,
                        "workspace": workspace or "", "ts": time.time()}, f)
    except Exception:
        pass

# --- Build JS to inject ---
INJECT_JS = """
(function() {
    // Don't inject twice — but if mute button is missing, re-inject all
    if (document.getElementById('clara-ptt-btn') && document.getElementById('clara-mute-btn')) return 'ALREADY_EXISTS';
    // Remove old buttons for clean re-inject
    ['clara-ptt-btn', 'clara-dictation-btn', 'clara-mute-btn'].forEach(function(id) {
        var el = document.getElementById(id);
        if (el) el.remove();
    });

    // Find send button by structure (resilient to class hash changes)
    function findSendButton() {
        var btn = document.querySelector('button[class*="sendButton"]');
        if (btn) return btn;
        var footer = document.querySelector('[class*="inputFooter"]');
        if (footer) {
            var buttons = footer.querySelectorAll('button');
            if (buttons.length > 0) return buttons[buttons.length - 1];
        }
        return null;
    }

    var sendBtn = findSendButton();
    if (!sendBtn) return 'NO_SEND_BUTTON';
    var footer = sendBtn.parentElement;
    if (!footer) return 'NO_FOOTER';

    var SIGNAL_KEY = 'clara-ptt-signal';
    var btnStyle = 'background:none; border:none; cursor:pointer; padding:4px;' +
        'display:flex; align-items:center; justify-content:center;' +
        'border-radius:4px; margin-right:2px; position:relative; transition:opacity 0.15s, color 0.15s;';

    var micSvg = '<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">' +
        '<rect x="9" y="1" width="6" height="13" rx="3"/>' +
        '<path d="M5 10a1 1 0 0 1 2 0 5 5 0 0 0 10 0 1 1 0 0 1 2 0 7 7 0 0 1-6 6.93V20h3a1 1 0 1 1 0 2H8a1 1 0 1 1 0-2h3v-3.07A7 7 0 0 1 5 10z"/></svg>';

    // --- Equalizer CSS ---
    if (!document.getElementById('clara-eq-style')) {
        var style = document.createElement('style');
        style.id = 'clara-eq-style';
        style.textContent =
            '@keyframes claraEq1{0%,100%{height:3px}50%{height:14px}}' +
            '@keyframes claraEq2{0%,100%{height:7px}50%{height:16px}}' +
            '@keyframes claraEq3{0%,100%{height:5px}50%{height:18px}}' +
            '@keyframes claraEq4{0%,100%{height:4px}50%{height:12px}}' +
            '@keyframes claraEq5{0%,100%{height:6px}50%{height:15px}}' +
            '.clara-eq-bar{width:2.5px;border-radius:2px;background:#ff5252;display:inline-block;}';
        document.head.appendChild(style);
    }

    var eqHtml = '<div style="display:flex;align-items:flex-end;justify-content:center;height:20px;width:20px;gap:1.5px;padding:1px 0;">' +
        '<span class="clara-eq-bar" style="animation:claraEq1 0.4s ease-in-out infinite;height:3px;"></span>' +
        '<span class="clara-eq-bar" style="animation:claraEq2 0.35s ease-in-out infinite 0.1s;height:7px;"></span>' +
        '<span class="clara-eq-bar" style="animation:claraEq3 0.45s ease-in-out infinite 0.05s;height:5px;"></span>' +
        '<span class="clara-eq-bar" style="animation:claraEq5 0.38s ease-in-out infinite 0.12s;height:6px;"></span>' +
        '<span class="clara-eq-bar" style="animation:claraEq4 0.5s ease-in-out infinite 0.08s;height:4px;"></span>' +
        '</div>';

    // ===================== DICTATION BUTTON =====================
    var dictBtn = document.createElement('button');
    dictBtn.id = 'clara-dictation-btn';
    dictBtn.type = 'button';
    dictBtn.title = 'Dictation mode (click to toggle)';
    dictBtn.setAttribute('style', btnStyle + 'color:#888; opacity:1;');

    var dictIconOff = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">' +
        '<circle cx="12" cy="12" r="10" stroke-opacity="0.4"/>' +
        '<path d="M5 12 Q7 7, 9 12 Q11 17, 12 12 Q13 7, 15 12 Q17 17, 19 12" stroke-width="2"/></svg>';

    var dictIconOn = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">' +
        '<circle cx="12" cy="12" r="10" fill="currentColor" fill-opacity="0.15" stroke-opacity="0.6"/>' +
        '<path d="M5 12 Q7 7, 9 12 Q11 17, 12 12 Q13 7, 15 12 Q17 17, 19 12" stroke-width="2.2"/></svg>';

    dictBtn.innerHTML = dictIconOff;
    var dictActive = false;

    dictBtn.addEventListener('click', function(e) {
        e.preventDefault(); e.stopPropagation();
        dictActive = !dictActive;
        if (dictActive) {
            dictBtn.style.color = '#ff9800';
            dictBtn.innerHTML = dictIconOn;
            dictBtn.title = 'Dictation ON (click to stop)';
        } else {
            dictBtn.style.color = '#888';
            dictBtn.innerHTML = dictIconOff;
            dictBtn.title = 'Dictation mode (click to toggle)';
        }
        localStorage.setItem(SIGNAL_KEY, JSON.stringify({command: 'dictation_toggle', ts: Date.now()}));
    });
    dictBtn.addEventListener('mouseenter', function() { if (!dictActive) dictBtn.style.color = '#aaa'; });
    dictBtn.addEventListener('mouseleave', function() { if (!dictActive) dictBtn.style.color = '#888'; });

    footer.insertBefore(dictBtn, sendBtn);

    // ===================== PTT MIC BUTTON =====================
    var btn = document.createElement('button');
    btn.id = 'clara-ptt-btn';
    btn.type = 'button';
    btn.title = 'Push to Talk (Clara Voice)';
    btn.setAttribute('style', btnStyle + 'color:#4caf50; opacity:1;');
    btn.innerHTML = micSvg;

    footer.insertBefore(btn, sendBtn);

    var recording = false;
    btn.onmousedown = function(e) {
        e.preventDefault(); e.stopPropagation();
        if (recording) return;
        recording = true;
        btn.innerHTML = eqHtml;
        btn.style.color = '#ff5252';
        btn.style.background = 'rgba(255,82,82,0.12)';
        btn.title = 'Recording...';
        localStorage.setItem(SIGNAL_KEY, JSON.stringify({command: 'ptt_start', ts: Date.now()}));
    };
    btn.onmouseup = function(e) {
        e.preventDefault(); e.stopPropagation();
        if (!recording) return;
        recording = false;
        btn.innerHTML = micSvg;
        btn.style.color = '#4caf50';
        btn.style.background = 'none';
        btn.title = 'Push to Talk (Clara Voice)';
        localStorage.setItem(SIGNAL_KEY, JSON.stringify({command: 'ptt_stop', ts: Date.now()}));
    };
    btn.onmouseleave = function() {
        if (recording) btn.onmouseup(new MouseEvent('mouseup'));
    };
    btn.addEventListener('mouseenter', function() { if (!recording) btn.style.color = '#66bb6a'; });
    btn.addEventListener('mouseleave', function() { if (!recording) btn.style.color = '#4caf50'; });

    // ===================== MUTE TTS BUTTON =====================
    var muteSvgOn = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' +
        '<path d="M11 5L6 9H2v6h4l5 4V5z"/>' +
        '<path d="M15.54 8.46a5 5 0 0 1 0 7.07"/>' +
        '<path d="M19.07 4.93a10 10 0 0 1 0 14.14"/></svg>';
    var muteSvgOff = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' +
        '<path d="M11 5L6 9H2v6h4l5 4V5z"/>' +
        '<line x1="23" y1="9" x2="17" y2="15"/>' +
        '<line x1="17" y1="9" x2="23" y2="15"/></svg>';
    var muteBtn = document.createElement('button');
    muteBtn.id = 'clara-mute-btn';
    muteBtn.type = 'button';
    muteBtn.title = 'Mute TTS';
    muteBtn.setAttribute('style', btnStyle + 'color:#888; opacity:1;');
    muteBtn.innerHTML = muteSvgOn;
    var ttsMuted = false;

    muteBtn.addEventListener('click', function(e) {
        e.preventDefault(); e.stopPropagation();
        ttsMuted = !ttsMuted;
        muteBtn.innerHTML = ttsMuted ? muteSvgOff : muteSvgOn;
        muteBtn.title = ttsMuted ? 'Unmute TTS' : 'Mute TTS';
        muteBtn.style.color = ttsMuted ? '#ff5252' : '#888';
        localStorage.setItem(SIGNAL_KEY, JSON.stringify({command: 'tts_mute_toggle', ts: Date.now()}));
    });
    muteBtn.addEventListener('mouseenter', function() { if (!ttsMuted) muteBtn.style.color = '#aaa'; });
    muteBtn.addEventListener('mouseleave', function() { if (!ttsMuted) muteBtn.style.color = '#888'; });

    footer.insertBefore(muteBtn, sendBtn);

    // --- MutationObserver: re-inject all buttons if removed ---
    var reinjecting = false;
    var observer = new MutationObserver(function() {
        if (reinjecting) return;
        if (!document.getElementById('clara-ptt-btn') || !document.getElementById('clara-dictation-btn') || !document.getElementById('clara-mute-btn')) {
            reinjecting = true;
            setTimeout(function() {
                var sb = findSendButton();
                if (sb && sb.parentElement) {
                    if (!document.getElementById('clara-dictation-btn')) {
                        sb.parentElement.insertBefore(dictBtn, sb);
                    }
                    if (!document.getElementById('clara-ptt-btn')) {
                        sb.parentElement.insertBefore(btn, sb);
                    }
                    if (!document.getElementById('clara-mute-btn')) {
                        sb.parentElement.insertBefore(muteBtn, sb);
                    }
                }
                reinjecting = false;
            }, 100);
        }
    });
    observer.observe(document.body, { childList: true, subtree: true });

    return 'OK';
})()
""".strip()

# --- Signal listener JS: polls localStorage and writes to console ---
LISTENER_JS = """
(function() {
    if (window._claraPttListener) return 'ALREADY_LISTENING';
    var lastTs = 0;
    window._claraPttListener = setInterval(function() {
        try {
            var raw = localStorage.getItem('clara-ptt-signal');
            if (!raw) return;
            var data = JSON.parse(raw);
            if (data.ts > lastTs) {
                lastTs = data.ts;
                console.log('CLARA_PTT:' + data.command);
            }
        } catch(e) {}
    }, 100);
    return 'OK';
})()
""".strip()


def find_target():
    """Find Claude Code webview target, using cache if available."""
    cache = load_cache()
    if cache and cache.get("workspace", "") == (workspace or ""):
        return cache["ws_url"], cache.get("context_id")

    targets = json.loads(urllib.request.urlopen(
        f"http://127.0.0.1:{port}/json", timeout=2
    ).read())

    claude_targets = [t for t in targets if "extensionId=Anthropic.claude-code" in t.get("url", "")]
    if not claude_targets:
        return None, None

    # Filter by workspace
    candidates = claude_targets
    if workspace:
        for t in targets:
            if t.get("type") == "page" and workspace.lower() in t.get("title", "").lower():
                page_id = t["id"]
                filtered = [ct for ct in claude_targets if ct.get("parentId", "").startswith(page_id)]
                if filtered:
                    candidates = filtered
                break

    # Probe each to find the one with Message input
    probe_js = '(function(){ return document.querySelector(\'[aria-label="Message input"]\') ? "HAS_INPUT" : "NO_INPUT"; })()'
    for ct in candidates:
        ws_url = ct["webSocketDebuggerUrl"].replace("localhost", "127.0.0.1")
        try:
            ws = websocket.create_connection(ws_url, timeout=3, suppress_origin=True)
            ws.send(json.dumps({"id": 1, "method": "Runtime.enable"}))
            ws.settimeout(0.5)
            contexts = []
            try:
                while True:
                    msg = json.loads(ws.recv())
                    if msg.get("method") == "Runtime.executionContextCreated":
                        contexts.append(msg["params"]["context"]["id"])
            except Exception:
                pass

            for cid in contexts:
                ws.send(json.dumps({"id": 50 + cid, "method": "Runtime.evaluate",
                                     "params": {"expression": probe_js, "contextId": cid}}))
                ws.settimeout(1)
                try:
                    while True:
                        resp = json.loads(ws.recv())
                        if resp.get("id") == 50 + cid:
                            if resp.get("result", {}).get("result", {}).get("value") == "HAS_INPUT":
                                ws.close()
                                save_cache(ws_url, cid)
                                return ws_url, cid
                            break
                except Exception:
                    pass
            ws.close()
        except Exception:
            pass

    return None, None


def inject(ws_url, context_id):
    """Inject button and listener into the webview."""
    ws = websocket.create_connection(ws_url, timeout=5, suppress_origin=True)
    ws.send(json.dumps({"id": 1, "method": "Runtime.enable"}))
    ws.settimeout(0.5)
    try:
        while True:
            ws.recv()
    except Exception:
        pass

    results = {}
    for label, js, rid in [("button", INJECT_JS, 100), ("listener", LISTENER_JS, 101)]:
        ws.send(json.dumps({
            "id": rid, "method": "Runtime.evaluate",
            "params": {"expression": js, "contextId": context_id}
        }))
        ws.settimeout(3)
        try:
            while True:
                resp = json.loads(ws.recv())
                if resp.get("id") == rid:
                    results[label] = resp.get("result", {}).get("result", {}).get("value", "ERROR")
                    break
        except Exception:
            results[label] = "TIMEOUT"

    try:
        ws.send(json.dumps({"id": 998, "method": "Runtime.disable"}))
        time.sleep(0.05)
        ws.close()
    except Exception:
        pass

    return results


def find_target_fresh():
    """Find target without cache — always probes CDP."""
    # Invalidate cache
    try:
        os.remove(CACHE_FILE)
    except Exception:
        pass
    return find_target()


def main():
    ws_url, context_id = find_target()
    if not ws_url:
        print("ERROR: Claude Code webview not found")
        sys.exit(1)

    try:
        results = inject(ws_url, context_id)
    except Exception:
        # Cache was stale — retry with fresh probe
        ws_url, context_id = find_target_fresh()
        if not ws_url:
            print("ERROR: Claude Code webview not found on retry")
            sys.exit(1)
        results = inject(ws_url, context_id)

    elapsed = time.perf_counter() - t0

    btn_result = results.get("button", "ERROR")
    if btn_result in ("OK", "ALREADY_EXISTS"):
        print(f"{btn_result}: {elapsed:.3f}s")
    else:
        print(f"ERROR: button={btn_result}")
        sys.exit(2)


if __name__ == "__main__":
    main()
