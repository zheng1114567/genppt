---
name: genppt-presentation
description: Generate professional editable PPTX from deck.json. Agent designs every slide individually using PptxGenJS, reading content from deck.json and applying brand colors from brand-style.md. No hardcoded templates — each slide is designed based on its content.
---

# GenPPT Agent Instructions

## Before anything: generate content

Run this first. It produces `outputs/manual-genppt/presentations/<slug>/deck.json`:

```bash
cd C:\Users\Administrator\Desktop\GenPPT
python generate_ppt.py "<topic>" -r "<requirements>" --brand <brand-path>
```

If content already exists and you just need to fix rendering, skip this and use the existing deck.json.

## Step 1: Load deck.json and brand

```python
import json
deck = json.load(open("outputs/manual-genppt/presentations/<slug>/deck.json", encoding="utf-8"))
slides = deck["slides"]
```

Brand colors come from the deck's theme_name (`product_modern`, `consulting_clean`, etc.) or from the `--brand` argument. The brand JSON for PptxGenJS is auto-generated as `dist/_brand.json` during export. Or use these defaults:

```javascript
const brand = {
  bg: "F8F9FB", surface: "F0F2F7", panel: "FFFFFF",
  ink: "111827", muted: "6B7280", line: "E5E7EB", lineStrong: "D1D5DB",
  accent: "2563EB", accentSoft: "DBEAFE",
  blue: "2563EB", blueSoft: "EFF6FF", green: "059669", greenSoft: "ECFDF5",
  onDark: "F9FAFB", onDarkSubtle: "9CA3AF",
  darkBg: "111827", darkSurface: "1F2937",
};
```

## Step 2: For each slide, pick a visual structure based on its INTENT

Do NOT use a fixed mapping. Read the slide's headline and body, then decide:

| If the slide has... | Use this structure |
|---|---|
| intent=cover | Full dark background, large headline centered or left-aligned, subtitle below, accent bar |
| intent=context | 3 metric cards in a row with big numbers, OR 2-3 evidence cards |
| intent=problem | Bold statement with supporting evidence cards below |
| intent=comparison | Two columns side by side: "Before" (left, muted) vs "After" (right, highlighted with accent) |
| intent=data | Large metric number + supporting body, OR 3-4 metric cards |
| intent=solution | Numbered steps (big circles with numbers) + description cards |
| intent=process | Vertical sequence: step number → step card, connected by thin lines |
| intent=roadmap | Horizontal timeline: phase dots on a line, phase cards below |
| intent=risk | Center "core principle" card surrounded by 4 risk cards at corners |
| intent=summary | Dark background, headline, action items with dots, next-step label |
| intent=insight | Large quote-style text with left accent bar, attribution below |

**Critical rule**: If two adjacent slides would use the same structure, vary them. Change card count (3→4), layout direction (horizontal→vertical), or accent placement (left bar→top bar→bottom strip).

## Step 3: Write PptxGenJS code for each slide

Use `scripts/render_pptx.cjs` as the base. Create a new render script or modify it. Each slide is a `pres.addSlide()` call.

Key PptxGenJS patterns:

**Card with left accent bar:**
```javascript
slide.addShape("rect", { x: 1, y: 1.5, w: 5.5, h: 1.2, fill: { color: brand.panel }, line: { color: brand.line, width: 0.5 }, rectRadius: 0.06 });
slide.addShape("rect", { x: 1, y: 1.5, w: 0.04, h: 1.2, fill: { color: brand.accent } });
slide.addText(bodyText, { x: 1.3, y: 1.6, w: 5, h: 1, fontSize: 12, fontFace: "Microsoft YaHei", color: brand.ink });
```

**Two-column comparison:**
```javascript
// Left column
slide.addShape("rect", { x: 0.6, y: 1.6, w: 5.7, h: 4.5, fill: { color: brand.panel }, line: { color: brand.line, width: 0.5 }, rectRadius: 0.06 });
// Right column
slide.addShape("rect", { x: 6.6, y: 1.6, w: 5.7, h: 4.5, fill: { color: brand.blueSoft }, line: { color: brand.blue, width: 0.5 }, rectRadius: 0.06 });
// Divider
slide.addShape("rect", { x: 6.45, y: 1.8, w: 0.02, h: 4.0, fill: { color: brand.accent } });
```

**Large metric + evidence:**
```javascript
slide.addText("78%", { x: 0.6, y: 1.5, w: 6, h: 2, fontSize: 72, fontFace: "Microsoft YaHei", color: brand.accent, bold: true });
slide.addText(headline, { x: 0.6, y: 3.5, w: 5, h: 0.8, fontSize: 22, color: brand.ink, bold: true });
```

**Dark cover/closing slide:**
```javascript
slide.background = { fill: brand.darkBg };
slide.addText(headline, { x: 0.6, y: 1.8, w: 11, h: 2, fontSize: 40, color: brand.onDark, bold: true });
slide.addShape("rect", { x: 0.6, y: 1.4, w: 1.5, h: 0.04, fill: { color: brand.accent } });
```

## Step 4: Run the render script

```bash
node scripts/render_pptx.cjs <deck.json> <brand.json> <output.pptx>
```

Or write a new render script and run it directly:
```bash
node scripts/my_deck.cjs
```

## Step 5: Review

Open the PPTX. Check:
- Are all 8 slides visually distinct from each other?
- Does each slide's visual structure match its content?
- Are brand colors applied consistently?
- Is there enough whitespace?

If issues found, modify the render script and re-run Step 4.

## Reference: slide dimensions

```
LAYOUT_WIDE: 13.333" × 7.5"
Safe zone: 0.6" margin on all sides
12-column grid: col_w ≈ 0.97", gutter = 0.2"
```

## Reference: PptxGenJS common shapes

```javascript
// Rect: x, y, w, h in inches
slide.addShape("rect", { x, y, w, h, fill: { color: "FF0000" }, line: { color: "000000", width: 0.5 }, rectRadius: 0.1 });

// Oval (circle when w==h):
slide.addShape("oval", { x, y, w, h, fill: { color: "0000FF" } });

// Text:
slide.addText("Hello", { x, y, w, h, fontSize: 14, fontFace: "Microsoft YaHei", color: "111827", bold: true, align: "left", valign: "middle" });

// Multi-line text:
slide.addText([
  { text: "Line 1", options: { fontSize: 14, breakLine: true } },
  { text: "Line 2", options: { fontSize: 14 } }
], { x, y, w, h, valign: "top" });
```
