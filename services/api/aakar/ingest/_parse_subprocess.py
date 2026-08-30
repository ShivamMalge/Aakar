"""Parse one PDF and print the raw JSON. Run as a subprocess so it can be killed.

`lightningparse.parse_pdf` is a single blocking call into Rust. It releases the GIL, so a
thread running it stays responsive — but a thread cannot be *killed*, so abandoning one
would leave the work running and the worker slot only nominally free. A subprocess can be
terminated, which is what "release the worker" actually requires (D-042).

Errors are reported by exit code and stderr rather than by exception type, because the
parent cannot unpickle an exception across a process boundary; `parser.py` maps them back.
"""

from __future__ import annotations

import sys

import lightningparse


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: _parse_subprocess <path>", file=sys.stderr)
        return 2
    try:
        sys.stdout.write(lightningparse.parse_pdf(argv[1]))
    except lightningparse.CorruptPdfError as exc:
        print(f"corrupt:{exc}", file=sys.stderr)
        return 10
    except lightningparse.UnsupportedPdfError as exc:
        print(f"unsupported:{exc}", file=sys.stderr)
        return 11
    except lightningparse.OcrMissingDependencyError as exc:
        print(f"ocr_missing:{exc}", file=sys.stderr)
        return 12
    except (lightningparse.OcrFailedError, lightningparse.OcrEngineError) as exc:
        print(f"ocr_failed:{exc}", file=sys.stderr)
        return 13
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
