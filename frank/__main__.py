import sys
import time
import traceback

from frank.cli import main
from frank.colors import c

POLL_INTERVAL = 30

if __name__ == "__main__":
    print(c("cyan", f"[frank] Starting polling loop (every {POLL_INTERVAL}s). Press Ctrl+C to stop."))
    while True:
        try:
            main()
        except KeyboardInterrupt:
            raise
        except Exception:
            print(c("red", "[frank] Fatal error in main loop:"))
            traceback.print_exc()
            sys.exit(1)

        try:
            time.sleep(POLL_INTERVAL)
        except KeyboardInterrupt:
            print(c("cyan", "\n[frank] Stopped."))
            break
