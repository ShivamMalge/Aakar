"""Playwright screenshot harness (task 1.6, D-009).

The generation pipeline drives Playwright from `services/api` against a running web
app: the consumer is Python, and a Python-driven harness avoids serializing a
screenshot request across a second interface.

This module *is* the code path — the Phase 1 CLI below and the Phase 3 VLM critic both
call `capture`, so gate captures and critic captures cannot drift apart. If the critic
ever needs a different camera or a different wait condition, it changes here and the
gate captures change with it.

Phase 0/1 make no model call: this file talks to a browser, never to a provider.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode

from playwright.sync_api import sync_playwright

DEFAULT_BASE_URL = "http://localhost:3000"

# Fixed viewport and scale factor: Phase 3 replays compare artifacts, so anything
# device-dependent would make a stable pipeline look unstable (3.7).
VIEWPORT_WIDTH = 1280
VIEWPORT_HEIGHT = 900
DEVICE_SCALE_FACTOR = 1

# The viewer sets this once three.js has painted a settled frame; without it the
# harness races the first render and captures an empty canvas.
READY_SELECTOR = "body[data-scene-ready='true']"
READY_TIMEOUT_MS = 30_000


@dataclass(frozen=True)
class ShotRequest:
    """One capture. `shot=1` hides the control chrome so the frame is all model."""

    topic: str
    angle: int = 0
    cutaway: bool = False
    explode: float = 0.0
    explode_mode: str = "top-level"
    labels: bool = True

    @property
    def filename(self) -> str:
        parts = [self.topic, f"angle{self.angle}"]
        if self.cutaway:
            parts.append("cutaway")
        if self.explode > 0:
            parts.append(f"explode{self.explode:g}-{self.explode_mode}")
        if not self.labels:
            parts.append("nolabels")
        return "-".join(parts) + ".png"

    def url(self, base_url: str) -> str:
        query = urlencode(
            {
                "angle": self.angle,
                "shot": "1",
                "cutaway": "1" if self.cutaway else "0",
                "labels": "1" if self.labels else "0",
                "explode": f"{self.explode:g}",
                "mode": self.explode_mode,
            }
        )
        return f"{base_url.rstrip('/')}/render/{self.topic}?{query}"


def capture(
    requests: Iterable[ShotRequest],
    out_dir: Path,
    *,
    base_url: str = DEFAULT_BASE_URL,
) -> list[Path]:
    """Render each request and write a PNG. Returns the paths written, in order."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            context = browser.new_context(
                viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
                device_scale_factor=DEVICE_SCALE_FACTOR,
                # A caret or a hover transition mid-capture is enough to break a
                # byte-comparison in Phase 3.
                reduced_motion="reduce",
            )
            page = context.new_page()
            for request in requests:
                page.goto(request.url(base_url), wait_until="domcontentloaded")
                page.wait_for_selector(READY_SELECTOR, timeout=READY_TIMEOUT_MS)
                target = out_dir / request.filename
                page.screenshot(path=str(target))
                written.append(target)
            context.close()
        finally:
            browser.close()

    return written


def gate_shots(topics: Sequence[str]) -> list[ShotRequest]:
    """The Phase 1 gate set: two angles per topic, plus cutaway and exploded captures."""
    shots: list[ShotRequest] = []
    for topic in topics:
        shots.append(ShotRequest(topic=topic, angle=0))
        shots.append(ShotRequest(topic=topic, angle=1))
    return shots


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("topics", nargs="+", help="topic slugs, e.g. human_eye")
    parser.add_argument("--out", type=Path, required=True, help="output directory")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--angle", type=int, action="append", help="repeatable; default 0 and 1")
    parser.add_argument("--cutaway", action="store_true")
    parser.add_argument("--explode", type=float, default=0.0)
    parser.add_argument("--explode-mode", default="top-level", choices=["top-level", "per-part"])
    parser.add_argument("--no-labels", action="store_true")
    args = parser.parse_args(argv)

    angles: list[int] = args.angle if args.angle else [0, 1]
    requests = [
        ShotRequest(
            topic=topic,
            angle=angle,
            cutaway=args.cutaway,
            explode=args.explode,
            explode_mode=args.explode_mode,
            labels=not args.no_labels,
        )
        for topic in args.topics
        for angle in angles
    ]

    for path in capture(requests, args.out, base_url=args.base_url):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
