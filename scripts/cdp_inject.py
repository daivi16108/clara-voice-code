"""CDP text injection into Claude Code chat.

Routes to correct VS Code window using parentId matching + iframe cache:
- Each VS Code window = one "page" target with workspace name in title
- Claude Code creates multiple iframes; only one has the chat input
- We cache the working iframe ID to skip probing on subsequent calls
- Cache auto-invalidates on miss (e.g. after window reload)
"""
import json, os, sys, tempfile, time, urllib.request
import websocket

# --- Args ---
text = None
port = 9222
workspace = None
no_submit = "--no-submit" in sys.argv
if "--text" in sys.argv:
    i = sys.argv.index("--text")
    if i + 1 < len(sys.argv):
        text = sys.argv[i + 1]
if "--port" in sys.argv:
    i = sys.argv.index("--port")
    if i + 1 < len(sys.argv):
        port = int(sys.argv[i + 1])
if "--workspace" in sys.argv:
    i = sys.argv.index("--workspace")
    if i + 1 < len(sys.argv):
        workspace = sys.argv[i + 1]
if not text:
    print("Usage: cdp_inject.py --text <text> [--port 9222] [--workspace name] [--no-submit]")
    sys.exit(1)

t0 = time.perf_counter()

# --- Cache helpers ---
CACHE_FILE = os.path.join(tempfile.gettempdir(), "voice-claude-cdp-cache.json")
CACHE_TTL = 3600  # 1 hour max

def load_cache():
    try:
        with open(CACHE_FILE, "r") as f:
            data = json.load(f)
        if time.time() - data.get("ts", 0) > CACHE_TTL:
            return None
        return data
    except Exception:
        return None

def save_cache(target_id, ws_url, context_id):
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump({"target_id": target_id, "ws_url": ws_url,
                        "context_id": context_id, "workspace": workspace or "",
                        "ts": time.time()}, f)
    except Exception:
        pass

# --- Build JS ---
escaped = text.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")
submit_js = """
    input.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter',code:'Enter',keyCode:13,which:13,bubbles:true}));
""" if not no_submit else ""

inject_js = f"""
(function() {{
    const input = document.querySelector('[aria-label="Message input"]');
    if (!input) return 'NOT_FOUND';
    input.focus();
    input.textContent = `{escaped}`;
    input.dispatchEvent(new InputEvent('input', {{bubbles: true}}));
    {submit_js}
    input.blur();
    return 'OK';
}})()
"""

def try_inject(ws_url, context_id=None):
    """Try injection on a specific iframe. Returns 'OK' or error string."""
    try:
        ws = websocket.create_connection(ws_url, timeout=5, suppress_origin=True)
    except Exception:
        return "CONNECT_FAIL"

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

    # If we have a cached context, try it first
    if context_id and context_id in contexts:
        contexts.remove(context_id)
        contexts.insert(0, context_id)

    val = ""
    hit_cid = None
    for cid in contexts:
        req_id = 100 + cid
        ws.send(json.dumps({
            "id": req_id,
            "method": "Runtime.evaluate",
            "params": {"expression": inject_js, "contextId": cid}
        }))
        ws.settimeout(2)
        try:
            while True:
                resp = json.loads(ws.recv())
                if resp.get("id") == req_id:
                    val = resp.get("result", {}).get("result", {}).get("value", "")
                    break
        except Exception:
            pass
        if val == "OK":
            hit_cid = cid
            break

    try:
        ws.send(json.dumps({"id": 998, "method": "Runtime.disable"}))
        ws.send(json.dumps({"id": 999, "method": "Inspector.disable"}))
        time.sleep(0.05)
        ws.close()
    except Exception:
        pass

    return val, hit_cid

# --- Fast path: try cached iframe first ---
cache = load_cache()
val = ""
if cache and cache.get("workspace", "") == (workspace or ""):
    cached_url = cache["ws_url"]
    cached_cid = cache.get("context_id")
    result = try_inject(cached_url, cached_cid)
    if isinstance(result, tuple):
        val, hit_cid = result
    if val == "OK":
        t_total = time.perf_counter() - t0
        print(f"OK: {t_total:.3f}s (cached)")
        sys.exit(0)

# --- Slow path: get targets, probe all iframes ---
try:
    targets = json.loads(urllib.request.urlopen(
        f"http://127.0.0.1:{port}/json", timeout=2
    ).read())
except Exception as e:
    print(f"ERROR: CDP not available on port {port}: {e}")
    sys.exit(2)

claude_targets = [t for t in targets if "extensionId=Anthropic.claude-code" in t.get("url", "")]
if not claude_targets:
    print("ERROR: Claude Code webview not found")
    sys.exit(3)

# Build target list: workspace-matched iframes first
candidates = []
if workspace:
    my_page_id = None
    for t in targets:
        if t.get("type") == "page" and workspace.lower() in t.get("title", "").lower():
            my_page_id = t["id"]
            break
    if my_page_id:
        for t in claude_targets:
            if t.get("parentId", "").startswith(my_page_id):
                candidates.append(t)

# Then remaining iframes as fallback
for t in claude_targets:
    if t not in candidates:
        candidates.append(t)

# Try each iframe
val = ""
for ct in candidates:
    ws_url = ct["webSocketDebuggerUrl"].replace("localhost", "127.0.0.1")
    result = try_inject(ws_url)
    if isinstance(result, tuple):
        val, hit_cid = result
    if val == "OK":
        save_cache(ct["id"], ws_url, hit_cid)
        break

t_total = time.perf_counter() - t0
if val == "OK":
    print(f"OK: {t_total:.3f}s")
else:
    print(f"ERROR: {val}")
    sys.exit(5)
