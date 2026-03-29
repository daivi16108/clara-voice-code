"""Inject 5 mic icon variants into Claude Code chat for visual comparison."""
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
    // Remove old buttons
    document.querySelectorAll('[id^="clara-ptt"]').forEach(function(b){ b.remove(); });

    var sendBtn = document.querySelector('button[class*="sendButton"]');
    if (!sendBtn) return 'NO_SEND';
    var footer = sendBtn.parentElement;

    var baseStyle = 'background:none; border:none; cursor:pointer; padding:5px;' +
        'display:flex; align-items:center; justify-content:center;' +
        'border-radius:4px; margin-right:2px; color:#4caf50; opacity:0.85;';

    // --- Variant 1: Filled mic (Google Meet style) ---
    var b1 = document.createElement('button');
    b1.id = 'clara-ptt-v1';
    b1.title = '1: Filled Mic';
    b1.setAttribute('style', baseStyle);
    b1.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><rect x="9" y="1" width="6" height="13" rx="3"/><path d="M5 10a1 1 0 0 1 2 0 5 5 0 0 0 10 0 1 1 0 0 1 2 0 7 7 0 0 1-6 6.93V20h3a1 1 0 1 1 0 2H8a1 1 0 1 1 0-2h3v-3.07A7 7 0 0 1 5 10z"/></svg>';
    footer.insertBefore(b1, sendBtn);

    // --- Variant 2: Mic with sound waves ---
    var b2 = document.createElement('button');
    b2.id = 'clara-ptt-v2';
    b2.title = '2: Mic + Waves';
    b2.setAttribute('style', baseStyle);
    b2.innerHTML = '<svg width="22" height="20" viewBox="0 0 28 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><rect x="11" y="2" width="6" height="12" rx="3" fill="currentColor" stroke="none"/><path d="M8 11v1a6 6 0 0 0 12 0v-1"/><line x1="14" y1="18" x2="14" y2="22"/><line x1="10" y1="22" x2="18" y2="22"/><path d="M4 7c0 3 1.5 5.5 3.5 7.5" stroke-opacity="0.5"/><path d="M24 7c0 3-1.5 5.5-3.5 7.5" stroke-opacity="0.5"/><path d="M1.5 5c0 4 2.5 8 5.5 10.5" stroke-opacity="0.25"/><path d="M26.5 5c0 4-2.5 8-5.5 10.5" stroke-opacity="0.25"/></svg>';
    footer.insertBefore(b2, sendBtn);

    // --- Variant 3: Material Design mic ---
    var b3 = document.createElement('button');
    b3.id = 'clara-ptt-v3';
    b3.title = '3: Material Design';
    b3.setAttribute('style', baseStyle);
    b3.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M12 1C10.34 1 9 2.34 9 4v8c0 1.66 1.34 3 3 3s3-1.34 3-3V4c0-1.66-1.34-3-3-3z"/><path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z"/></svg>';
    footer.insertBefore(b3, sendBtn);

    // --- Variant 4: Outlined with glow dot ---
    var b4 = document.createElement('button');
    b4.id = 'clara-ptt-v4';
    b4.title = '4: Outlined + Dot';
    b4.setAttribute('style', baseStyle);
    b4.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z" fill="currentColor" fill-opacity="0.15"/><path d="M19 10v1a7 7 0 0 1-14 0v-1"/><line x1="12" y1="18" x2="12" y2="22"/><circle cx="12" cy="22" r="1.2" fill="currentColor" stroke="none"/></svg>';
    footer.insertBefore(b4, sendBtn);

    // --- Variant 5: Bold studio mic ---
    var b5 = document.createElement('button');
    b5.id = 'clara-ptt-v5';
    b5.title = '5: Bold Studio';
    b5.setAttribute('style', baseStyle);
    b5.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M12 1a4 4 0 0 0-4 4v7a4 4 0 0 0 8 0V5a4 4 0 0 0-4-4z" opacity="0.85"/><path d="M19 10a1 1 0 0 0-2 0 5 5 0 0 1-10 0 1 1 0 0 0-2 0 7 7 0 0 0 6 6.93V21H8.5a1 1 0 1 0 0 2h7a1 1 0 1 0 0-2H13v-4.07A7 7 0 0 0 19 10z"/></svg>';
    footer.insertBefore(b5, sendBtn);

    return 'OK: 5 variants';
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
