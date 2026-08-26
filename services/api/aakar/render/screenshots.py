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
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import urlencode

from playwright.sync_api import Page, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

DEFAULT_BASE_URL = "http://localhost:3000"

# Fixed viewport and scale factor: Phase 3 replays compare artifacts, so anything
# device-dependent would make a stable pipeline look unstable (3.7).
VIEWPORT_WIDTH = 1280
VIEWPORT_HEIGHT = 900
DEVICE_SCALE_FACTOR = 1

# Capture liveness (Phase 1 review, item 2).
#
# The viewer emits this node only when the spec compiled AND the scene graph was built
# and painted, and stamps it with what was actually rendered. Waiting on a bare "ready"
# flag was not enough: a stale client bundle photographs identically to a working one, so
# a broken route produced captures that looked fine. In Phase 3 the VLM critic consumes
# this exact path and gates entry into the library, and a critic scoring stale renders
# produces confident approvals of nothing.
READY_SELECTOR = "[data-scene-sentinel]"
READY_TIMEOUT_MS = 30_000


class CapturePreconditionFailed(RuntimeError):
    """A precondition failed. No capture is taken; nothing downstream sees a stale PNG."""


@dataclass(frozen=True)
class ShotRequest:
    """One capture. `shot=1` hides the control chrome so the frame is all model.

    `labels` splits the capture path in two (ruling 7), and the split is not cosmetic:

    * **unlabeled — the VLM critic's input.** The critic judges geometry, occlusion,
      spatial relationships and anatomical plausibility. Label collisions are the most
      visually wrong thing in a labeled frame, so a critic given one spends both of D3's
      repair rounds on typography while structural errors pass unexamined.
    * **labeled — the human curator's input.** Naming, coverage and alias correctness can
      only be judged with the labels on.
    """

    topic: str
    angle: int = 0
    # Tri-state. None means "do not say", so the viewer applies its geometry-derived
    # default (ruling 9). This is the same trap as the Phase 1 outage: a harness that
    # pins every option can never exercise the behaviour that only happens when one is
    # absent, and every capture silently showed the non-default path.
    cutaway: bool | None = None
    explode: float = 0.0
    explode_mode: str = "top-level"
    labels: bool = True

    @property
    def filename(self) -> str:
        parts = [self.topic, f"angle{self.angle}"]
        if self.cutaway is True:
            parts.append("cutaway")
        elif self.cutaway is False:
            parts.append("exterior")
        if self.explode > 0:
            parts.append(f"explode{self.explode:g}-{self.explode_mode}")
        # Always stated, never implied. Which variant a PNG is decides who it is for, and
        # an unlabelled filename would make a critic input indistinguishable from a
        # human one at a glance.
        parts.append("labeled" if self.labels else "unlabeled")
        return "-".join(parts) + ".png"

    def url(self, base_url: str) -> str:
        params: dict[str, str | int] = {
            "angle": self.angle,
            "shot": "1",
            "labels": "1" if self.labels else "0",
            "explode": f"{self.explode:g}",
            "mode": self.explode_mode,
        }
        if self.cutaway is not None:
            params["cutaway"] = "1" if self.cutaway else "0"
        query = urlencode(params)
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

            # Check the *default* route for each topic before capturing anything.
            #
            # This is not belt-and-braces. The capture URL over-specifies every option,
            # and the Phase 1 outage was reachable only when an option was ABSENT: the
            # server component fell back to a value off a "use client" module, which is a
            # client reference React cannot serialize. Supplying `cutaway` and `labels`
            # skipped that fallback entirely, so the harness URL returned 200 while
            # /render/{topic} — what readers and share links actually open — returned 500.
            # A harness that only ever visits its own over-specified URL cannot see that.
            for topic in dict.fromkeys(request.topic for request in requests):
                _assert_live(page, f"{base_url.rstrip('/')}/render/{topic}", topic)

            for request in requests:
                url = request.url(base_url)
                _assert_live(page, url, request.topic)
                target = out_dir / request.filename
                page.screenshot(path=str(target))
                written.append(target)
            context.close()
        finally:
            browser.close()

    return written


def _assert_live(page: Page, url: str, topic: str) -> None:
    """Refuse to photograph anything that is not demonstrably alive.

    Three checks, in the order they can fail:
      1. the route answered 200 — a 500 used to still produce a PNG
      2. the sentinel appeared — the scene graph was built and painted
      3. the sentinel describes *this* topic with a non-zero part count
    """
    response = page.goto(url, wait_until="domcontentloaded")
    if response is None:
        raise CapturePreconditionFailed(f"no response from {url}")
    if response.status != 200:
        raise CapturePreconditionFailed(f"route is not healthy: HTTP {response.status} for {url}")

    try:
        page.wait_for_selector(READY_SELECTOR, state="attached", timeout=READY_TIMEOUT_MS)
    except PlaywrightTimeoutError as exc:
        raise CapturePreconditionFailed(
            f"scene never became ready for {url}: no {READY_SELECTOR} after "
            f"{READY_TIMEOUT_MS} ms. The route answered 200, so the page loaded but the "
            f"viewer did not mount or the spec did not compile."
        ) from exc

    sentinel = page.locator(READY_SELECTOR).first
    rendered_topic = sentinel.get_attribute("data-topic")
    rendered_parts = sentinel.get_attribute("data-parts")

    if rendered_topic != topic:
        raise CapturePreconditionFailed(
            f"wrong topic rendered at {url}: sentinel says {rendered_topic!r}, expected {topic!r}"
        )
    if not rendered_parts or int(rendered_parts) <= 0:
        raise CapturePreconditionFailed(
            f"nothing to photograph at {url}: sentinel reports {rendered_parts!r} parts"
        )


def both_variants(requests: Iterable[ShotRequest]) -> list[ShotRequest]:
    """Expand each view into its unlabeled and labeled forms (ruling 7).

    Unlabeled first, so a directory listing pairs them predictably.
    """
    out: list[ShotRequest] = []
    for request in requests:
        out.append(replace(request, labels=False))
        out.append(replace(request, labels=True))
    return out


def gate_shots(topics: Sequence[str]) -> list[ShotRequest]:
    """The Phase 1 gate set: two angles per topic, in both label variants."""
    shots: list[ShotRequest] = []
    for topic in topics:
        shots.append(ShotRequest(topic=topic, angle=0))
        shots.append(ShotRequest(topic=topic, angle=1))
    return both_variants(shots)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("topics", nargs="+", help="topic slugs, e.g. human_eye")
    parser.add_argument("--out", type=Path, required=True, help="output directory")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--angle", type=int, action="append", help="repeatable; default 0 and 1")
    parser.add_argument(
        "--cutaway",
        choices=["default", "on", "off"],
        default="default",
        help="default (the viewer's geometry-derived choice), on, or off",
    )
    parser.add_argument("--explode", type=float, default=0.0)
    parser.add_argument("--explode-mode", default="top-level", choices=["top-level", "per-part"])
    parser.add_argument(
        "--labels",
        choices=["both", "on", "off"],
        default="both",
        help="both (default) emits the critic's unlabeled frame and the curator's labeled one",
    )
    args = parser.parse_args(argv)

    angles: list[int] = args.angle if args.angle else [0, 1]
    base = [
        ShotRequest(
            topic=topic,
            angle=angle,
            cutaway={"default": None, "on": True, "off": False}[args.cutaway],
            explode=args.explode,
            explode_mode=args.explode_mode,
            labels=args.labels != "off",
        )
        for topic in args.topics
        for angle in angles
    ]
    requests = both_variants(base) if args.labels == "both" else base

    try:
        for path in capture(requests, args.out, base_url=args.base_url):
            print(path)
    except CapturePreconditionFailed as failure:
        print(f"CAPTURE PRECONDITION FAILED: {failure}", file=sys.stderr)
        print("No screenshots were written.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
