"""Fixed synthetic subprocess used only to prove the P11 process boundary."""

from __future__ import annotations

import json
import sys
import time

MAX_INPUT_BYTES = 65_536


def main() -> int:
    data = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    if len(data) > MAX_INPUT_BYTES:
        print("input exceeds fixture bound", file=sys.stderr)
        return 2
    value = json.loads(data)
    delay_ms = int(value.get("delay_ms", 0))
    if delay_ms < 0 or delay_ms > 2_000:
        print("delay is outside fixture bound", file=sys.stderr)
        return 2
    if delay_ms:
        time.sleep(delay_ms / 1_000)
    parameters = value["parameters"]
    payload = value["payload"]
    gain = float(parameters["gain"])
    output = {
        "engine": "qste_fixture_process/0.1",
        "mode": parameters["mode"],
        "output": [float(item) * gain for item in payload],
    }
    sys.stdout.write(json.dumps(output, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
