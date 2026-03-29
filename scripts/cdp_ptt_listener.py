"""CDP console listener for inline PTT button signals.

Connects to Claude Code webview via CDP, enables console API,
and relays CLARA_PTT:* messages to the PTT command file.
Runs as a long-lived subprocess, killed when extension deactivates.
"""
import json, os, sys, tempfile, time
import websocket

port = 9222
workspace = ""
result_file = ""
if "--port" in sys.argv:
    i = sys.argv.index("--port")
    if i + 1 < len(sys.argv):
        port = int(sys.argv[i + 1])
if "--workspace" in sys.argv:
    i = sys.argv.index("--workspace")
    if i + 1 < len(sys.argv):
        workspace = sys.argv[i + 1]
if "--result-file" in sys.argv:
    i = sys.argv.index("--result-file")
    if i + 1 < len(sys.argv):
        result_file = sys.argv[i + 1]

PTT_CMD_FILE = os.path.join(tempfile.gettempdir(), "voice-claude-ptt.json")
CACHE_FILE = os.path.join(tempfile.gettempdir(), "voice-claude-cdp-cache.json")
LOG_FILE = os.path.join(tempfile.gettempdir(), "voice-claude-enter.log")

def log(msg):
    ts = time.strftime("%H:%M:%S")
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] PTT_LISTENER: {msg}\n")
    except:
        pass

def load_cache():
    try:
        with open(CACHE_FILE, "r") as f:
            data = json.load(f)
        if time.time() - data.get("ts", 0) > 3600:
            return None
        return data
    except:
        return None

def write_ptt_command(command):
    """Write PTT command to file for tray to pick up."""
    try:
        with open(PTT_CMD_FILE, "w") as f:
            json.dump({
                "command": command,
                "timestamp": int(time.time() * 1000),
                "workspace": workspace,
                "result_file": result_file,
            }, f)
        log(f"wrote {command}")
    except Exception as e:
        log(f"write error: {e}")

def main():
    # Wait up to 10s for cache to appear (inject_button writes it)
    cache = None
    for _ in range(20):
        cache = load_cache()
        if cache:
            break
        time.sleep(0.5)

    if not cache:
        log("no cache after 10s, exiting")
        sys.exit(1)

    ws_url = cache["ws_url"]
    context_id = cache.get("context_id")
    log(f"connecting to {ws_url}")

    try:
        ws = websocket.create_connection(ws_url, timeout=10, suppress_origin=True)
    except Exception as e:
        log(f"connect failed: {e}")
        sys.exit(2)

    # Enable Runtime to get console messages via consoleAPICalled
    ws.send(json.dumps({"id": 1, "method": "Runtime.enable"}))
    # Drain initial messages
    ws.settimeout(1)
    try:
        while True:
            ws.recv()
    except:
        pass

    log("listening for PTT signals...")
    sys.stdout.write("LISTENING\n")
    sys.stdout.flush()

    # Long poll for console messages
    ws.settimeout(None)  # blocking
    while True:
        try:
            raw = ws.recv()
            msg = json.loads(raw)

            # Runtime.consoleAPICalled fires on console.log
            if msg.get("method") == "Runtime.consoleAPICalled":
                args = msg.get("params", {}).get("args", [])
                for arg in args:
                    val = arg.get("value", "")
                    if isinstance(val, str) and val.startswith("CLARA_PTT:"):
                        command = val.split(":", 1)[1]
                        if command in ("ptt_start", "ptt_stop", "dictation_toggle", "tts_mute_toggle"):
                            write_ptt_command(command)

        except websocket.WebSocketConnectionClosedException:
            log("websocket closed, exiting")
            break
        except Exception as e:
            log(f"error: {e}")
            break

    try:
        ws.close()
    except:
        pass
    log("listener stopped")


if __name__ == "__main__":
    main()
