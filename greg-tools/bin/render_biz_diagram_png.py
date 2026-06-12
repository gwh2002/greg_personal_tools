#!/usr/bin/env python3
"""Render a business-facing three-lane process diagram to PNG with Pillow."""

from __future__ import annotations

import argparse
import json
import math
import sys
import textwrap
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont


CANVAS = (1600, 900)
DPI = (144, 144)
LANE_TOP = 128
LANE_HEIGHT = 546
LANE_GAP = 18
LANES = [
    {"x": 55, "w": 430, "border": "#c2410c", "fill": "#fff7ed", "box": "#fed7aa"},
    {"x": 503, "w": 430, "border": "#6d28d9", "fill": "#f5f3ff", "box": "#ddd6fe"},
    {"x": 951, "w": 500, "border": "#047857", "fill": "#f0fdf4", "box": "#bbf7d0"},
]
TEXT = "#374151"
MUTED = "#64748b"
TITLE = "#1e40af"
LOOP = "#dc2626"
SCOPE = "#2563eb"
SCOPE_FILL = "#eff6ff"

FONT_PATHS = [
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render a 1600x900 business-facing diagram PNG from JSON."
    )
    parser.add_argument("spec", type=Path, help="Path to the diagram spec JSON.")
    parser.add_argument("output", type=Path, help="Path to write the PNG.")
    return parser.parse_args()


def load_font(size: int) -> ImageFont.ImageFont:
    for font_path in FONT_PATHS:
        path = Path(font_path)
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def assert_ascii(value: object, path: str = "spec") -> None:
    if isinstance(value, str):
        try:
            value.encode("ascii")
        except UnicodeEncodeError as exc:
            raise ValueError(f"{path} contains non-ASCII text: {value!r}") from exc
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            assert_ascii(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            assert_ascii(item, f"{path}.{key}")


def require_shape(spec: dict) -> None:
    steps = spec.get("steps")
    if not isinstance(steps, list) or len(steps) != 3:
        raise ValueError("spec.steps must contain exactly 3 step objects")
    for index, step in enumerate(steps, start=1):
        for key in ("label", "title", "bullets"):
            if key not in step:
                raise ValueError(f"step {index} is missing required key {key!r}")
        if not isinstance(step["bullets"], list) or not step["bullets"]:
            raise ValueError(f"step {index} must include at least one bullet")


def draw_wrapped(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: str,
    width_chars: int,
    line_spacing: int = 6,
) -> int:
    x, y = xy
    lines: list[str] = []
    for raw_line in text.splitlines() or [""]:
        wrapped = textwrap.wrap(raw_line, width=width_chars) or [""]
        lines.extend(wrapped)
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        bbox = draw.textbbox((x, y), line or "Ag", font=font)
        y += bbox[3] - bbox[1] + line_spacing
    return y


def draw_rounded_rect(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    outline: str,
    fill: str,
    width: int = 3,
    radius: int = 8,
) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def draw_diamond(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    outline: str,
    fill: str,
    width: int = 3,
) -> None:
    x1, y1, x2, y2 = box
    points = [
        ((x1 + x2) // 2, y1),
        (x2, (y1 + y2) // 2),
        ((x1 + x2) // 2, y2),
        (x1, (y1 + y2) // 2),
    ]
    draw.polygon(points, fill=fill, outline=outline)
    for index in range(width - 1):
        inset = index + 1
        inner = (x1 + inset, y1 + inset, x2 - inset, y2 - inset)
        ix1, iy1, ix2, iy2 = inner
        inner_points = [
            ((ix1 + ix2) // 2, iy1),
            (ix2, (iy1 + iy2) // 2),
            ((ix1 + ix2) // 2, iy2),
            (ix1, (iy1 + iy2) // 2),
        ]
        draw.line(inner_points + [inner_points[0]], fill=outline)


def draw_arrow(
    draw: ImageDraw.ImageDraw,
    start: tuple[int, int],
    end: tuple[int, int],
    fill: str,
    width: int = 4,
    dashed: bool = False,
) -> None:
    if dashed:
        draw_dashed_line(draw, start, end, fill, width)
    else:
        draw.line([start, end], fill=fill, width=width)
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    length = 16
    spread = 0.45
    p1 = (
        end[0] - length * math.cos(angle - spread),
        end[1] - length * math.sin(angle - spread),
    )
    p2 = (
        end[0] - length * math.cos(angle + spread),
        end[1] - length * math.sin(angle + spread),
    )
    draw.polygon([end, p1, p2], fill=fill)


def draw_dashed_line(
    draw: ImageDraw.ImageDraw,
    start: tuple[int, int],
    end: tuple[int, int],
    fill: str,
    width: int = 3,
    dash: int = 14,
    gap: int = 10,
) -> None:
    x1, y1 = start
    x2, y2 = end
    distance = math.hypot(x2 - x1, y2 - y1)
    if distance == 0:
        return
    steps = int(distance // (dash + gap)) + 1
    for step in range(steps):
        start_dist = step * (dash + gap)
        end_dist = min(start_dist + dash, distance)
        if start_dist >= distance:
            break
        sx = x1 + (x2 - x1) * start_dist / distance
        sy = y1 + (y2 - y1) * start_dist / distance
        ex = x1 + (x2 - x1) * end_dist / distance
        ey = y1 + (y2 - y1) * end_dist / distance
        draw.line([(sx, sy), (ex, ey)], fill=fill, width=width)


def bullet_text(bullets: Iterable[str]) -> str:
    return "\n".join(f"- {bullet}" for bullet in bullets)


def render(spec: dict, output: Path) -> None:
    assert_ascii(spec)
    require_shape(spec)

    image = Image.new("RGB", CANVAS, "white")
    draw = ImageDraw.Draw(image)

    title_font = load_font(34)
    subtitle_font = load_font(21)
    badge_font = load_font(24)
    lane_title_font = load_font(30)
    body_font = load_font(22)
    small_font = load_font(18)

    draw.rectangle((0, 0, CANVAS[0] - 1, CANVAS[1] - 1), outline="#dbeafe", width=3)
    draw.text((60, 34), spec.get("title", "Business process overview"), font=title_font, fill=TITLE)
    draw.text((62, 88), spec.get("subtitle", ""), font=subtitle_font, fill=MUTED)

    steps = spec["steps"]
    for index, step in enumerate(steps):
        lane = LANES[index]
        x = lane["x"]
        w = lane["w"]
        draw_rounded_rect(
            draw,
            (x, LANE_TOP, x + w, LANE_TOP + LANE_HEIGHT),
            outline=lane["border"],
            fill=lane["fill"],
        )
        draw.text(
            (x + 25, LANE_TOP + 24),
            f"STEP {index + 1} -- {step['label'].upper()}",
            font=badge_font,
            fill=lane["border"],
        )
        draw_wrapped(
            draw,
            (x + 25, LANE_TOP + 58),
            step["title"],
            lane_title_font,
            TEXT,
            width_chars=22 if w <= 430 else 28,
            line_spacing=4,
        )

        box_top = LANE_TOP + 155
        box_height = 220 if index == 0 else 285
        draw_rounded_rect(
            draw,
            (x + 25, box_top, x + w - 25, box_top + box_height),
            outline=lane["border"],
            fill=lane["box"],
            width=2,
        )
        draw_wrapped(
            draw,
            (x + 45, box_top + 24),
            bullet_text(step["bullets"]),
            body_font,
            TEXT,
            width_chars=30 if w <= 430 else 38,
            line_spacing=8,
        )

        if index == 0:
            gate = step.get("gate", {})
            gate_box = (x + 112, LANE_TOP + 392, x + 312, LANE_TOP + 492)
            draw_diamond(draw, gate_box, outline="#b45309", fill="#fef3c7")
            draw_wrapped(
                draw,
                (x + 145, LANE_TOP + 428),
                gate.get("text", "Source complete?"),
                small_font,
                TEXT,
                width_chars=17,
                line_spacing=4,
            )
            fallback = gate.get("fallback", "No --> fix source set")
            draw.text((x + 95, LANE_TOP + 508), fallback, font=small_font, fill="#b45309")

    arrow_labels = spec.get("arrow_labels", ["complete", "ready for review"])
    arrow_y = LANE_TOP + 270
    draw_arrow(draw, (485, arrow_y), (503, arrow_y), fill="#475569")
    draw.text((491, arrow_y - 34), arrow_labels[0], font=small_font, fill=MUTED)
    draw_arrow(draw, (933, arrow_y), (951, arrow_y), fill="#475569")
    draw.text((903, arrow_y - 34), arrow_labels[1], font=small_font, fill=MUTED)

    loop_y = 704
    draw_arrow(draw, (1210, loop_y), (730, loop_y), fill=LOOP, width=4, dashed=True)
    draw.text((786, loop_y + 16), spec.get("correction_loop", "Corrections go back to Step 2"), font=small_font, fill=LOOP)

    scope = spec.get("scope", {})
    scope_box = (55, 746, 1451, 846)
    draw.rounded_rectangle(scope_box, radius=8, fill=SCOPE_FILL, outline=SCOPE, width=3)
    draw_dashed_line(draw, (66, 756), (1440, 756), SCOPE, width=2, dash=10, gap=7)
    draw_dashed_line(draw, (66, 836), (1440, 836), SCOPE, width=2, dash=10, gap=7)
    included = "; ".join(scope.get("included", []))
    excluded = "; ".join(scope.get("excluded", []))
    scope_text = (
        f"{scope.get('title', 'What this contains')}: "
        f"[+] {included}    [-] {excluded}"
    )
    draw_wrapped(draw, (82, 779), scope_text, body_font, TEXT, width_chars=118, line_spacing=6)

    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, dpi=DPI)


def main() -> int:
    args = parse_args()
    try:
        spec = json.loads(args.spec.read_text(encoding="utf-8"))
        render(spec, args.output)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
