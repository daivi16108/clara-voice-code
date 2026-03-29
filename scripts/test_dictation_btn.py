"""Remove test icons and update dictation button to Circle+Sine."""
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
    // Remove test buttons
    ['clara-dict-v1','clara-dict-v2','clara-dict-v3','clara-dict-v4','clara-dict-v5'].forEach(function(id){
        var el = document.getElementById(id);
        if (el) el.remove();
    });

    // Update existing dictation button
    var btn = document.getElementById('clara-dictation-btn');
    if (!btn) return 'NO_BUTTON';

    btn.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">' +
        '<circle cx="12" cy="12" r="10" stroke-opacity="0.4"/>' +
        '<path d="M5 12 Q7 7, 9 12 Q11 17, 12 12 Q13 7, 15 12 Q17 17, 19 12" stroke-width="2"/></svg>';

    return 'UPDATED';
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
