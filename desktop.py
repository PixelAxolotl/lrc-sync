"""Launch lrc-sync in a single native desktop window."""
import argparse
import threading
import time

import uvicorn
import webview

import server

server.CHARACTER_LEVEL = True
app = server.app


def main() -> None:
    parser = argparse.ArgumentParser(description="lrc-sync desktop application")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--port", type=int, default=0,
        help="Local port (0 selects an available port)",
    )
    args = parser.parse_args()

    config = uvicorn.Config(app, host=args.host, port=args.port, log_level="info")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.monotonic() + 30
    while not server.started and not server.should_exit and time.monotonic() < deadline:
        time.sleep(0.1)
    if not server.started:
        server.should_exit = True
        thread.join(timeout=5)
        raise RuntimeError("Unable to start the lrc-sync server")

    port = server.servers[0].sockets[0].getsockname()[1]
    url = f"http://{args.host}:{port}"
    window = webview.create_window("LRC Sync", url, width=960, height=800)

    def close_server() -> None:
        server.should_exit = True

    window.events.closed += close_server
    try:
        webview.start()
    finally:
        server.should_exit = True
        thread.join(timeout=5)


if __name__ == "__main__":
    main()
