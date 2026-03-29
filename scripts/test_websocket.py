"""Test MCP JSON-RPC methods on Claude Code WebSocket."""
import json, sys, time, glob, os
import websocket

lock_dir = os.path.expanduser("~/.claude/ide")
target = None
for lock_path in glob.glob(os.path.join(lock_dir, "*.lock")):
    with open(lock_path) as f:
        data = json.load(f)
    if any("clara-voice-code" in w for w in data.get("workspaceFolders", [])):
        port = os.path.basename(lock_path).replace(".lock", "")
        target = {"port": port, "auth": data["authToken"]}
        break

if not target:
    print("ERROR: No lock file"); sys.exit(1)

url = f"ws://127.0.0.1:{target['port']}"
headers = {"x-claude-code-ide-authorization": target["auth"]}

def call(ws, method, params=None, is_notification=False):
    msg = {"jsonrpc": "2.0", "method": method}
    if params:
        msg["params"] = params
    if not is_notification:
        msg["id"] = int(time.time() * 1000) % 100000
    payload = json.dumps(msg, ensure_ascii=False)
    print(f"\n→ {method}: {payload[:200]}")
    ws.send(payload)
    if is_notification:
        print("  (notification, no response expected)")
        time.sleep(0.5)
        return None
    ws.settimeout(3)
    try:
        r = ws.recv()
        parsed = json.loads(r)
        print(f"← {json.dumps(parsed, ensure_ascii=False)[:300]}")
        return parsed
    except:
        print("  (no response)")
        return None

ws = websocket.create_connection(url, header=headers, timeout=5)
print(f"Connected to {url}")

# 1. Ping
call(ws, "ping")

# 2. List tools
result = call(ws, "tools/list")
if result and "result" in result:
    tools = result["result"].get("tools", [])
    print(f"\n  Available tools ({len(tools)}):")
    for t in tools[:15]:
        print(f"    - {t['name']}: {t.get('description','')[:60]}")
    if len(tools) > 15:
        print(f"    ... and {len(tools)-15} more")

# 3. notifications/message
call(ws, "notifications/message", {
    "level": "info",
    "data": "[Voice] тест notification"
}, is_notification=True)

# 4. sampling/createMessage
call(ws, "sampling/createMessage", {
    "messages": [{"role": "user", "content": {"type": "text", "text": "[Voice] тест sampling"}}],
    "maxTokens": 100
})

# 5. Try at_mentioned
call(ws, "at_mentioned", {
    "text": "[Voice] тест at_mentioned"
}, is_notification=True)

ws.close()
print("\n\nCheck VS Code chat!")
