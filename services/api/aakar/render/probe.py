"""Interaction probe for the Phase 1 gate: does clicking a part actually select it?

The screenshot harness proves the compiler renders. It cannot prove the viewer's
raycast selection works, because a selected part looks almost the same in a still. This
drives a real browser, clicks the canvas, and reads back what the panel says — so the
gate's "click/hover works" line is a transcript rather than an assurance.

Like `screenshots`, this talks to a browser and never to a model.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import sync_playwright

from .screenshots import (
    DEFAULT_BASE_URL,
    DEVICE_SCALE_FACTOR,
    VIEWPORT_HEIGHT,
    VIEWPORT_WIDTH,
    CapturePreconditionFailed,
    _assert_live,
)

CANVAS = "canvas"
SELECTION = ".viewer-selection dd"
EMPTY = ".viewer-selection .viewer-empty"


@dataclass(frozen=True)
class ProbeResult:
    topic: str
    before: str
    hovered_cursor: str
    after: list[str]

    @property
    def selected_a_part(self) -> bool:
        return len(self.after) > 0


def probe(topic: str, *, base_url: str = DEFAULT_BASE_URL) -> ProbeResult:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            context = browser.new_context(
                viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
                device_scale_factor=DEVICE_SCALE_FACTOR,
            )
            page = context.new_page()
            _assert_live(page, f"{base_url.rstrip('/')}/render/{topic}", topic)

            before = page.locator(EMPTY).inner_text() if page.locator(EMPTY).count() else ""

            canvas = page.locator(CANVAS)
            box = canvas.bounding_box()
            assert box is not None, "canvas has no layout box"
            centre_x = box["x"] + box["width"] / 2
            centre_y = box["y"] + box["height"] / 2

            page.mouse.move(centre_x, centre_y)
            page.wait_for_timeout(250)
            cursor = page.evaluate("() => getComputedStyle(document.body).cursor")

            page.mouse.click(centre_x, centre_y)
            page.wait_for_timeout(250)
            after = page.locator(SELECTION).all_inner_texts()

            context.close()
            return ProbeResult(topic=topic, before=before, hovered_cursor=str(cursor), after=after)
        finally:
            browser.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("topics", nargs="+")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--out", type=Path, help="write the transcript here as well as stdout")
    args = parser.parse_args(argv)

    lines: list[str] = ["=== VIEWER INTERACTION PROBE (Phase 1 gate, task 1.2) ==="]
    failures = 0

    for topic in args.topics:
        try:
            result = probe(topic, base_url=args.base_url)
        except CapturePreconditionFailed as failure:
            print(f"CAPTURE PRECONDITION FAILED: {failure}", file=sys.stderr)
            return 2
        lines.append("")
        lines.append(f"/render/{topic}")
        lines.append(f"    before any click   -> {result.before or '(panel already populated)'}")
        lines.append(f"    cursor over canvas -> {result.hovered_cursor}")
        if result.selected_a_part:
            fields = " | ".join(value.replace("\n", " ") for value in result.after)
            lines.append(f"    click at centre    -> selected: {fields}")
        else:
            lines.append("    click at centre    -> NOTHING SELECTED")
            failures += 1

    lines.append("")
    lines.append(
        "Raycast selection works: a click resolves to a part id and the panel reads it back."
        if failures == 0
        else f"{failures} topic(s) did not select a part on click."
    )

    text = "\n".join(lines)
    print(text)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
