"""`watch-demo`: serve the watch demo on localhost:8100."""

import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "watch_demo.app:create_app",
        factory=True,
        host=os.environ.get("WATCH_DEMO_HOST", "127.0.0.1"),
        port=int(os.environ.get("WATCH_DEMO_PORT", "8100")),
    )


if __name__ == "__main__":
    main()
