"""Test: inject equalizer animation into mic button."""
import json, os, tempfile, websocket

cache = json.load(open(os.path.join(tempfile.gettempdir(), "voice-claude-cdp-cache.json")))
ws = websocket.create_connection(cache["ws_url"], timeout=5, suppress_origin=True)
ws.send(json.dumps({"id": 1, "method": "Runtime.enable"}))
ws.settimeout(1)
try:
    while True:
        ws.recv()
except Exception:
    pass

js = r"""(function(){
    var btn = document.getElementById('clara-ptt-btn');
    if (!btn) return 'NO_BUTTON';

    // Add equalizer CSS
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

    // Save mic SVG
    var micSvg = '<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">' +
        '<rect x="9" y="1" width="6" height="13" rx="3"/>' +
        '<path d="M5 10a1 1 0 0 1 2 0 5 5 0 0 0 10 0 1 1 0 0 1 2 0 7 7 0 0 1-6 6.93V20h3a1 1 0 1 1 0 2H8a1 1 0 1 1 0-2h3v-3.07A7 7 0 0 1 5 10z"/>' +
        '</svg>';

    var eqHtml = '<div style="display:flex;align-items:flex-end;justify-content:center;height:20px;width:20px;gap:1.5px;padding:1px 0;">' +
        '<span class="clara-eq-bar" style="animation:claraEq1 0.4s ease-in-out infinite;height:3px;"></span>' +
        '<span class="clara-eq-bar" style="animation:claraEq2 0.35s ease-in-out infinite 0.1s;height:7px;"></span>' +
        '<span class="clara-eq-bar" style="animation:claraEq3 0.45s ease-in-out infinite 0.05s;height:5px;"></span>' +
        '<span class="clara-eq-bar" style="animation:claraEq5 0.38s ease-in-out infinite 0.12s;height:6px;"></span>' +
        '<span class="clara-eq-bar" style="animation:claraEq4 0.5s ease-in-out infinite 0.08s;height:4px;"></span>' +
        '</div>';

    btn.innerHTML = micSvg;

    var recording = false;
    btn.onmousedown = function(e) {
        e.preventDefault(); e.stopPropagation();
        if (recording) return;
        recording = true;
        btn.innerHTML = eqHtml;
        btn.style.color = '#ff5252';
        btn.style.background = 'rgba(255,82,82,0.12)';
        btn.title = 'Recording...';
        localStorage.setItem('clara-ptt-signal', JSON.stringify({command:'ptt_start', ts:Date.now()}));
    };
    btn.onmouseup = function(e) {
        e.preventDefault(); e.stopPropagation();
        if (!recording) return;
        recording = false;
        btn.innerHTML = micSvg;
        btn.style.color = '#4caf50';
        btn.style.background = 'none';
        btn.title = 'Push to Talk (Clara Voice)';
        localStorage.setItem('clara-ptt-signal', JSON.stringify({command:'ptt_stop', ts:Date.now()}));
    };
    btn.onmouseleave = function() {
        if (recording) btn.onmouseup(new MouseEvent('mouseup'));
    };

    return 'OK';
})()"""

ws.send(json.dumps({"id": 100, "method": "Runtime.evaluate",
                     "params": {"expression": js, "contextId": cache["context_id"]}}))
ws.settimeout(3)
try:
    while True:
        r = json.loads(ws.recv())
        if r.get("id") == 100:
            print(r.get("result", {}).get("result", {}).get("value", ""))
            break
except Exception:
    pass
ws.close()
