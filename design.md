# The Lenny Growth Assistant — UI/UX Design

This document is the design contract for the frontend. It defines the layout system, design
tokens, component specifications, and interaction states. Phase 4 implements exactly what is
described here; any deviation is a bug in the implementation, not a liberty.

---

## Table of Contents

1. [Design Philosophy](#design-philosophy)
2. [Layout System](#layout-system)
3. [Wireframes](#wireframes)
4. [Design Tokens](#design-tokens)
5. [Typography](#typography)
6. [Component Specifications](#component-specifications)
7. [The Artifact Viewer](#the-artifact-viewer)
8. [Streaming and Motion](#streaming-and-motion)
9. [State Coverage](#state-coverage)
10. [Responsive Behaviour](#responsive-behaviour)
11. [Accessibility](#accessibility)
12. [Dark Mode](#dark-mode)
13. [Design QA Checklist](#design-qa-checklist)

---

## Design Philosophy

The specification points at `Impeccable.style` as the reference for a clean, considered interface.
The principles below are our reading of that brief — the rules this UI is actually held to.

**1. The content is the interface.**
A conversation about product strategy is dense text. Chrome competes with it. Every border, shadow,
and icon must justify its existence; when in doubt it is removed. There is no toolbar of features
the user did not ask for.

**2. Restraint over decoration.**
One accent colour, used only for the primary action and the active state. Everything else is a
warm neutral. A UI that uses six colours to signal six things teaches the user nothing; a UI that
uses one colour in one meaning is learned instantly.

**3. Hierarchy through space and weight, not lines.**
Separation is achieved with whitespace and type weight first, a hairline border second, a shadow
almost never. Borders are 1px and low-contrast. Nothing floats without reason.

**4. Optical calm.**
A single 4px spacing grid. A single type scale. Three corner radii. Consistency is what makes an
interface feel expensive — not novelty.

**5. Motion explains, it does not perform.**
Animation exists to show where something came from: the artifact pane slides in from the right
because that is where it lives. 120–240ms, one easing curve, and fully disabled under
`prefers-reduced-motion`.

**6. Readable long-form.**
This app generates 1250-word essays. Measure is capped at ~68 characters, line-height is generous,
and rendered Markdown uses a serif — because a Ship30for30 essay should read like an essay, not
like a chat log.

**7. Honest states.**
Every asynchronous operation has a visible, specific state. "Warming up the local model" beats a
spinner. "This isn't covered in the transcripts I have" beats a confident hallucination. The UI
never implies a capability that is unavailable — it disables it and says why.

---

## Layout System

Three vertical zones on one horizontal axis. The user's attention moves left → right as work
progresses: pick a conversation, have it, inspect what it produced.

```
┌──────────────┬────────────────────────────────┬─────────────────────────────┐
│              │                                │                             │
│  ZONE 1      │  ZONE 2                        │  ZONE 3                     │
│  Sessions    │  Conversation                  │  Artifact Viewer            │
│              │                                │                             │
│  264px       │  flexible, min 480px           │  44% default, 30–70% drag   │
│  collapsible │  content column max 720px      │  hidden until an artifact   │
│  to 0        │  centred                       │  exists                     │
│              │                                │                             │
└──────────────┴────────────────────────────────┴─────────────────────────────┘
```

| Property | Value | Rationale |
| :------- | :---- | :-------- |
| Sidebar width | `264px` | Fits ~34 characters of a session title before truncation — enough to distinguish conversations. |
| Sidebar collapsed | `0px` (icon rail at `56px` on medium screens) | Full collapse gives long essays maximum room. |
| Chat min width | `480px` | Below this, prose measure degrades badly; the artifact pane yields first. |
| Chat content column | `max-width: 720px`, centred | ~68 characters at 15px body. The pane can be wide; the text column stays readable. |
| Artifact default | `44%` of the remaining width | Slightly under half. The conversation stays primary. |
| Artifact drag range | `30%–70%` | Persisted to `localStorage` per user. |
| Vertical rhythm | 4px grid, sections at 24px | One grid, no exceptions. |
| Chrome height | Composer auto-grows to `200px` then scrolls | Long prompts stay editable without swallowing the transcript. |

**Zone 3 is conditional.** It does not exist until a message contains an artifact. It never
appears empty, and it never displaces the conversation without cause — the chat column reflows with
a 240ms transition, and the pane can be dismissed at any time without losing the artifact (it stays
reachable from a chip on the message that produced it).

---

## Wireframes

### Default — conversation, no artifact

```
┌────────────────────┬──────────────────────────────────────────────────────────┐
│  Lenny Growth      │                                            ☾  ⚙          │
│  Assistant         │                                                          │
│                    │        ┌──────────────────────────────────────┐          │
│  ┌──────────────┐  │        │  How do great PMs decide what not    │          │
│  │  + New chat  │  │        │  to build?                           │ ● You    │
│  └──────────────┘  │        └──────────────────────────────────────┘          │
│                    │                                                          │
│  TODAY             │   ◆  Skill A · Grounded Q&A                              │
│  ▸ Retention loops │                                                          │
│  ▸ PMF signals     │   Across the transcripts, three filters come up          │
│                    │   repeatedly.                                            │
│  PREVIOUS 7 DAYS   │                                                          │
│  ▸ Ship30 draft…   │   **Strategic fit.** If it doesn't ladder to the one     │
│  ▸ Pricing tiers   │   metric the team owns this quarter, it's a distraction.  │
│  ▸ Onboarding…     │                                                          │
│                    │   • Does it compound, or is it a one-off lift?           │
│                    │   • Who is the single owner?                             │
│                    │                                                          │
│                    │   ┌────────────────────────────────────────────┐         │
│                    │   │ Sources                                    │         │
│                    │   │ 1  Ep. 214 · Shreyas Doshi                 │         │
│                    │   │ 2  Ep. 178 · Melissa Perri                 │         │
│                    │   └────────────────────────────────────────────┘         │
│                    │                                                          │
│                    │   ⧉ Copy    ↻ Regenerate    ⚑ Cloud · Sonnet 4.6         │
│  ─────────────     │                                                          │
│  ◐ Cloud   Local   │   ┌──────────────────────────────────────────────────┐   │
│  ⌄ collapse        │   │  Ask about growth, retention, PMF…          ↑    │   │
└────────────────────┴───┴──────────────────────────────────────────────────┴───┘
```

### Artifact open — three panes

```
┌──────────┬────────────────────────────────┬───────────────────────────────────┐
│ + New    │                                │  Retention Dashboard        ⤢  ✕  │
│          │  ● You                         │  ┌─────────────┬──────────────┐   │
│ TODAY    │  Build me a dashboard mockup    │  │  Preview    │  Code        │   │
│ ▸ Reten… │  for weekly retention          │  └─────────────┴──────────────┘   │
│ ▸ PMF…   │                                │  ┌─────────────────────────────┐  │
│          │  ◆ Skill C · Artifact          │  │                             │  │
│ 7 DAYS   │                                │  │   ▁▃▅▇▅▃▁  W1 → W8          │  │
│ ▸ Ship3… │  Here's a self-contained        │  │                             │  │
│ ▸ Prici… │  mockup. Cohort rows are on    │  │   [ sandboxed iframe —      │  │
│          │  the y-axis, weeks on the x.    │  │     live HTML + CSS ]       │  │
│          │                                │  │                             │  │
│          │  ┌──────────────────────────┐  │  │                             │  │
│          │  │ ◧ Retention Dashboard    │  │  │                             │  │
│          │  │   html · 3.1 KB      →   │  │  └─────────────────────────────┘  │
│          │  └──────────────────────────┘  │                                   │
│          │                                │  ⧉ Copy   ⬇ Download   ↻ Reload   │
│ ─────    │  ┌──────────────────────────┐  │                                   │
│ ◐ Cloud  │  │ Ask a follow-up…    ↑   │  │                                   │
└──────────┴──┴──────────────────────────┴──┴───────────────────────────────────┘
```

### Empty state — new chat

```
┌────────────────────┬──────────────────────────────────────────────────────────┐
│  + New chat        │                                                          │
│                    │                        ◆                                 │
│  No conversations  │                                                          │
│  yet               │           The Lenny Growth Assistant                     │
│                    │                                                          │
│                    │      Grounded in Lenny's Podcast transcripts.            │
│                    │                                                          │
│                    │   ┌──────────────────┐  ┌──────────────────┐             │
│                    │   │ Ask a question   │  │ Write a          │             │
│                    │   │ about retention  │  │ Ship30for30      │             │
│                    │   │ loops            │  │ essay on PMF     │             │
│                    │   └──────────────────┘  └──────────────────┘             │
│                    │   ┌──────────────────┐  ┌──────────────────┐             │
│                    │   │ Build a metrics  │  │ Compare B2B and  │             │
│                    │   │ dashboard mockup │  │ B2C growth loops │             │
│                    │   └──────────────────┘  └──────────────────┘             │
│  ─────────────     │                                                          │
│  ◐ Cloud   Local   │   ┌──────────────────────────────────────────────────┐   │
│                    │   │  Ask about growth, retention, PMF…          ↑    │   │
└────────────────────┴───┴──────────────────────────────────────────────────┴───┘
```

The four starter cards are not decoration — each one maps to a distinct skill path (A, B, C, and a
comparative Q&A), so the first interaction teaches the user what the system can do.

---

## Design Tokens

Implemented as CSS custom properties on `:root` and `[data-theme="dark"]`. No component hardcodes a
colour, radius, or duration.

### Colour — Light

| Token | Value | Use |
| :---- | :---- | :-- |
| `--bg-canvas` | `#FFFFFF` | Chat pane background |
| `--bg-subtle` | `#F7F7F5` | Sidebar, artifact chrome, assistant message ground |
| `--bg-elevated` | `#FFFFFF` | Cards, composer, popovers |
| `--bg-inset` | `#F1F1EE` | Code blocks, source list, inputs |
| `--bg-hover` | `rgba(0,0,0,0.04)` | Row and button hover |
| `--bg-active` | `rgba(0,0,0,0.07)` | Pressed state |
| `--border-subtle` | `#E8E8E3` | Default hairline |
| `--border-strong` | `#D4D4CD` | Focused input, drag handle |
| `--text-primary` | `#1A1A18` | Body and headings |
| `--text-secondary` | `#6B6B63` | Metadata, timestamps, captions |
| `--text-tertiary` | `#6D6D67` | Placeholders, disabled *(was `#9A9A91` — failed AA, see Accessibility)* |
| `--accent-50` | `#FEF6EE` | Accent tint background |
| `--accent-100` | `#FDE8D3` | Accent tint border |
| `--accent-500` | `#E87723` | Accent (non-text) |
| `--accent-600` | `#D2620F` | Primary button, active state |
| `--accent-700` | `#A94D0C` | Primary hover, accent text on light |
| `--success` | `#11694A` | Provider available, ingest complete *(was `#157F5A`)* |
| `--warning` | `#A84E08` | Degraded, length-guard notice *(was `#B45309`)* |
| `--danger` | `#B42318` | Errors, destructive actions |

### Colour — Dark

| Token | Value | Use |
| :---- | :---- | :-- |
| `--bg-canvas` | `#141413` | Chat pane background |
| `--bg-subtle` | `#1C1C1A` | Sidebar, artifact chrome |
| `--bg-elevated` | `#232320` | Cards, composer, popovers |
| `--bg-inset` | `#0F0F0E` | Code blocks, inputs |
| `--bg-hover` | `rgba(255,255,255,0.06)` | Hover |
| `--bg-active` | `rgba(255,255,255,0.10)` | Pressed |
| `--border-subtle` | `#2E2E2A` | Default hairline |
| `--border-strong` | `#3D3D38` | Focused input, drag handle |
| `--text-primary` | `#F5F5F0` | Body and headings |
| `--text-secondary` | `#A8A89E` | Metadata |
| `--text-tertiary` | `#8B8B82` | Placeholders, disabled *(was `#77776E` — failed AA)* |
| `--accent-500` | `#F0873D` | Accent, lifted for dark contrast |
| `--accent-600` | `#E87723` | Primary button |
| `--accent-700` | `#F5A768` | Accent text on dark (inverted ramp direction) |
| `--success` | `#3DBE8B` | — |
| `--warning` | `#E0A44A` | — |
| `--danger` | `#F2685C` | — |

The neutral ramp is warm (a green-red bias, not blue). Against a warm amber accent this reads
considered rather than clinical, and it keeps long reading sessions comfortable.

### Spacing, radius, elevation, motion

```css
--space-1: 4px;   --space-2: 8px;   --space-3: 12px;  --space-4: 16px;
--space-5: 20px;  --space-6: 24px;  --space-8: 32px;  --space-10: 40px;
--space-12: 48px; --space-16: 64px;

--radius-sm: 6px;    /* chips, badges, small buttons  */
--radius-md: 10px;   /* buttons, inputs, list rows    */
--radius-lg: 14px;   /* cards, message bubbles, panes */
--radius-pill: 999px;/* toggle track, skill badges    */

--shadow-sm: 0 1px 2px rgba(0,0,0,0.05);
--shadow-md: 0 4px 12px rgba(0,0,0,0.08);   /* popovers only        */
--shadow-lg: 0 12px 32px rgba(0,0,0,0.12);  /* fullscreen artifact  */

--ease: cubic-bezier(0.2, 0, 0.2, 1);
--dur-micro: 120ms;   /* hover, press, checkbox        */
--dur-base:  180ms;   /* fades, chips, tab switch      */
--dur-pane:  240ms;   /* artifact pane, sidebar toggle */
```

Three radii, three shadows, three durations. Anything outside these lists is a mistake.

---

## Typography

| Role | Family | Size / Line | Weight | Tracking |
| :--- | :----- | :---------- | :----- | :------- |
| Display (empty state) | Inter | 28 / 34 | 600 | −0.02em |
| Section heading | Inter | 22 / 30 | 600 | −0.01em |
| Subheading | Inter | 18 / 26 | 600 | −0.01em |
| Chat body | Inter | 15 / 25 | 400 | 0 |
| Essay / rendered Markdown | Newsreader (serif) | 17 / 29 | 400 | 0 |
| Metadata, captions | Inter | 13 / 20 | 400 | 0 |
| Label (uppercase) | Inter | 11 / 16 | 600 | 0.06em |
| Code, artifact source | JetBrains Mono | 13 / 21 | 400 | 0 |

Font stacks fall back to system faces so the UI never blocks on a webfont:

```css
--font-ui:    'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
--font-serif: 'Newsreader', 'Iowan Old Style', Georgia, 'Times New Roman', serif;
--font-mono:  'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace;
```

**Why two text families.** Chat is UI — Inter is correct: neutral, tight, high-legibility at small
sizes. A Ship30for30 essay is *reading* — a serif at 17/29 signals "this is a document" and
measurably reduces fatigue over 1250 words. The switch happens automatically wherever rendered
Markdown appears (essay responses and Markdown artifacts).

**Prose rules inside chat and artifacts**

- Paragraph spacing `--space-4`; never indent first lines.
- `**bold**` renders at weight 600 in `--text-primary`, never in the accent colour. Bold is
  emphasis, not a link.
- Bullet lists: 8px between items, marker in `--text-tertiary`, hanging indent so wrapped lines
  align to the text, not the marker.
- Blockquotes: 2px `--accent-100` left rule, 16px inset, `--text-secondary`.
- Inline code: `--bg-inset`, `--radius-sm`, 2px×5px padding, no border.
- Headings inside a response start at the subheading scale — an assistant message never competes
  with app-level headings.

---

## Component Specifications

### 1. Sidebar — session history

```
┌──────────────────────────┐
│  ◆ Lenny Growth          │  brand row, 14px/600, 48px tall
│    Assistant             │
├──────────────────────────┤
│  ┌────────────────────┐  │  primary button, full width, 36px,
│  │   +  New chat      │  │  --accent-600, --radius-md
│  └────────────────────┘  │
├──────────────────────────┤
│  TODAY                   │  label token, --text-tertiary, 24px tall
│  ┌────────────────────┐  │
│  │ Retention loops  ⋯ │  │  32px row, --radius-md, 13px title
│  └────────────────────┘  │  active: --bg-active + 2px accent left bar
│    PMF signals           │  hover: --bg-hover, reveals ⋯ menu
│                          │
│  PREVIOUS 7 DAYS         │
│    Ship30 draft on ret…  │  single-line ellipsis truncation
│    Pricing tiers         │
├──────────────────────────┤
│  ◐ Cloud    Local        │  LLM toggle, pinned to bottom
│  ☾ Dark     ⌄ Collapse   │
└──────────────────────────┘
```

- Groups: **Today**, **Previous 7 days**, **Previous 30 days**, **Older**. Empty groups are not
  rendered.
- Sessions are titled from the first user message (first 6–8 words, generated by the small model,
  never a raw truncation mid-word). Rename via the `⋯` menu, inline, `Enter` to commit / `Esc` to
  cancel.
- Delete asks for confirmation inline in the row — no modal dialog. Never a browser `confirm()`.
- Optimistic behaviour: a new chat appears instantly as *New chat* and is retitled when the first
  response completes.
- The list virtualizes past 100 sessions.

### 2. Message — user

Right-aligned, `max-width: 80%` of the content column, `--bg-inset` fill, `--radius-lg` with the
bottom-right corner at `--radius-sm` (a subtle directional tail, no CSS triangle). Plain text with
preserved line breaks — user input is never parsed as Markdown, which also removes an injection
surface.

### 3. Message — assistant

Full content width, no bubble. Prose sits directly on the canvas so long answers read as a
document.

Structure top to bottom:

1. **Skill badge** — pill, 11px uppercase, `--accent-50` on `--accent-100` border.
   `Skill A · Grounded Q&A` / `Skill B · Ship30for30` / `Skill C · Artifact`. This makes the router
   observable to the user, which is the difference between "a chatbot" and "an agent I can reason
   about".
2. **Body** — rendered Markdown; serif for Skill B, UI sans for A and C.
3. **Artifact chip** — appears the moment `artifact_start` arrives (see below).
4. **Sources** — collapsed `Sources (3)` row that expands to a numbered list of
   `Ep. 214 · Guest Name`, each linking to the transcript source. Present for Skills A and B only.
5. **Action row** — revealed on hover, always available to keyboard focus: Copy · Regenerate ·
   provider stamp (`⚑ Cloud · Sonnet 4.6` or `⚑ Local · llama3.1:8b`).

Word count appears next to the Skill B badge (`1,247 words`) — the constraint is visible, and if
the length guard fell short the count turns `--warning` with a tooltip explaining why.

### 4. Composer

```
┌──────────────────────────────────────────────────────────────┐
│  Ask about growth, retention, PMF…                       ↑   │
└──────────────────────────────────────────────────────────────┘
   ↑ 44px min · auto-grow to 200px · --radius-lg · --bg-elevated
   ↑ 1px --border-subtle → --border-strong on focus, no glow ring
```

- `Enter` sends, `Shift+Enter` newlines, `⌘/Ctrl+Enter` also sends.
- Send button is a 28px circle, `--accent-600`, disabled at `--text-tertiary` when empty.
- While streaming the send button becomes a **stop** square that aborts the request (the backend
  detects the disconnect and persists the partial message).
- Sticky to the bottom of the chat pane with a 24px `--bg-canvas` gradient fade above, so text
  scrolling underneath does not collide with it.
- The composer never blocks: a request in flight leaves the field editable so the user can draft
  their next message.

### 5. LLM toggle — Cloud / Local

The specification calls for a clear toggle. A segmented control is the honest form: both options are
visible simultaneously, with their state legible at a glance.

```
       ┌─────────────────┬─────────────────┐
       │  ☁  Cloud       │   ▣  Local      │      --radius-pill track,
       │  ●●●●●●●●●●●●●  │                 │      --bg-inset, 1px border
       └─────────────────┴─────────────────┘
         active: --bg-elevated + --shadow-sm  · thumb slides 180ms
         inactive: --text-secondary
         unavailable: --text-tertiary, cursor not-allowed, tooltip
```

- Under the track, a 11px caption names the resolved model: `Claude Sonnet 4.6` or
  `llama3.1:8b-instruct`.
- A 6px status dot precedes each label — `--success` available, `--danger` unavailable, pulsing
  `--warning` while health is being checked.
- Availability comes from `GET /api/health`. An unavailable side is **disabled, not hidden**, with
  a tooltip that states the fix: *"No ANTHROPIC_API_KEY configured"* / *"Ollama not reachable at
  localhost:11434"*.
- The selection persists in `localStorage` and is sent with every `/api/chat` request. Switching
  mid-conversation is legal — the provider stamp on each message records what was actually used, so
  a mixed thread stays interpretable.

### 6. Skill badge

Small, quiet, and consistent. Skill A uses neutral tokens; Skill B and Skill C use the accent tint.
The badge appears as soon as the `meta` SSE event lands — before the first token — so the user knows
what kind of answer is coming.

---

## The Artifact Viewer

The reason this app is not a chat window. HTML, CSS, and Markdown render **in place**, with no
external redirect and no download-to-view step.

### Chrome

```
┌────────────────────────────────────────────────────────────────┐
│  ◧  Retention Dashboard                    html · 3.1 KB  ⤢ ✕  │  44px header
├────────────────────────────────────────────────────────────────┤
│  ┌──────────┬──────────┐                                       │  36px tabs
│  │ Preview  │   Code   │                                       │
│  └──────────┴──────────┘                                       │
├────────────────────────────────────────────────────────────────┤
│                                                                │
│                     render surface                             │
│                                                                │
├────────────────────────────────────────────────────────────────┤
│  ⧉ Copy      ⬇ Download      ↻ Reload                          │  40px footer
└────────────────────────────────────────────────────────────────┘
```

- **Preview / Code tabs.** Preview is default. Code shows the source in `--font-mono` with syntax
  highlighting and line numbers.
- **⤢ Fullscreen** expands the pane over the whole viewport (`--shadow-lg`); `Esc` returns.
- **✕ Close** collapses the pane. The artifact is not destroyed — its chip stays on the message and
  reopens it.
- **Reload** re-mounts the iframe, which is the correct escape hatch for a mockup with animations
  or a stuck script.
- A vertical drag handle on the left edge resizes between 30% and 70%. It shows a 2px
  `--border-strong` rail on hover and the width persists.

### HTML rendering — security model

HTML artifacts render in a **sandboxed iframe** using `srcdoc`:

```
sandbox="allow-scripts"
```

- `allow-scripts` **without** `allow-same-origin`. This is the important pairing: scripts run, so
  interactive mockups work, but the frame has an opaque origin and cannot reach the parent DOM,
  `localStorage`, cookies, or the session.
- Omitting `allow-forms`, `allow-popups`, `allow-modals`, and `allow-top-navigation` means an
  artifact cannot navigate the app away, open windows, or raise a blocking `alert()`.
- A `Content-Security-Policy` meta tag is injected into the `srcdoc` document permitting inline
  styles and scripts (mockups need them) while blocking network fetches, so an artifact cannot
  exfiltrate anything or load remote trackers.
- The iframe is keyed on artifact id + content hash, so React re-mounts rather than patching when
  content changes. Patching a live document mid-stream produces flicker and half-parsed CSS.

Sanitized `innerHTML` injection was rejected: any sanitizer strict enough to be safe would strip
the `<style>` blocks and scripts that make a mockup worth previewing. Isolation beats filtering.

### Markdown rendering

Parsed to React elements (never `dangerouslySetInnerHTML`), rendered in the serif stack at 17/29
with the prose rules above. Fenced code blocks get highlighting and a copy button. GFM tables get a
horizontal scroll container rather than breaking the layout.

### Streaming behaviour

The pane is populated **live**, because watching an artifact assemble itself is a large part of the
experience.

| Stream event | UI response |
| :----------- | :---------- |
| `artifact_start` | Chip appears on the message; pane slides in over 240ms; header shows the title; Code tab is auto-selected. |
| `artifact_delta` | Source appends in the Code tab with the caret auto-scrolled. Preview does **not** re-render per token. |
| `artifact_end` | Debounced 150ms, then Preview mounts and auto-selects; size and type appear in the header. |

Code-first during the stream is deliberate: mounting an iframe on every token would thrash, and a
half-written `<div>` previews as garbage. The user sees progress in the Code tab, then the finished
result in Preview.

### Empty, error, and multi-artifact states

- **Empty:** the pane does not exist. No placeholder, no "artifacts will appear here" panel.
- **Unterminated tag:** the backend closes it at stream end; the header shows a `--warning`
  `Incomplete` chip and Code is preselected, because the source is the truth in that situation.
- **Multiple artifacts in one conversation:** the pane shows the newest and gains a compact
  breadcrumb strip; any earlier artifact reopens from its chip in the transcript.

---

## Streaming and Motion

The typewriter effect is the app's primary liveness signal, and it must not stutter.

- Tokens are appended into a ref-held buffer and flushed to React state on a
  `requestAnimationFrame` tick — one render per frame at most, regardless of token rate.
- **Caret:** a 2px × 1em `--accent-600` block after the last character, 1s blink. Removed on
  `done`.
- **Pre-first-token:** three 4px dots at `--text-tertiary` cycling opacity, 1.4s loop. If the wait
  exceeds 3 seconds the label changes to `Retrieving from transcripts…`, and at 8 seconds in Local
  mode to `Warming up the local model…`. Specific beats indeterminate.
- **Autoscroll:** follows the stream only while the user is within 80px of the bottom. Scrolling up
  detaches and reveals a `↓ Jump to latest` pill. Nothing yanks the viewport away from something
  being read.
- **Pane entrance:** `translateX(12px)` + opacity over `--dur-pane`; the chat column reflows on the
  same curve so the two read as one motion.
- `@media (prefers-reduced-motion: reduce)` sets all durations to `1ms`, disables the caret blink
  and dot cycle, and replaces sliding with an instant state change. Text still streams — that is
  content arriving, not decoration.

---

## State Coverage

Every state below has a designed appearance. None falls back to a bare spinner or a raw error
string.

| State | Presentation |
| :---- | :----------- |
| Sessions loading | Three shimmer rows in the sidebar, `--bg-hover`, 1.2s sweep. |
| No sessions | "No conversations yet" in `--text-tertiary`; the empty-state hero carries the starter cards. |
| Messages loading | Two skeleton paragraph blocks at 60% / 85% width. |
| Awaiting first token | Skill badge (already known) + cycling dots + escalating status label. |
| Streaming | Live text, blinking caret, composer send button becomes stop. |
| Complete | Caret removed, action row available, sources collapsed, provider stamp shown. |
| Grounding unavailable | Inline notice card, `--warning` left rule: the corpus does not cover this, with two suggested reformulations. Not styled as an error — it is a correct answer. |
| Provider unavailable | Toggle half disabled with reason tooltip; attempting to send shows an inline banner above the composer with a **Switch to Local / Cloud** action. |
| Ollama cold start | "Warming up the local model — first response after startup can take a minute." Sub-caption names the model. |
| Provider timeout | Inline error card retaining any partial text, with **Retry** and **Try the other provider** actions. |
| Rate limited | Countdown ("retrying in 4s") then automatic retry; two failures escalate to a manual Retry button. |
| Database unavailable | Full-pane state: the conversation cannot load, with a Retry action. Composer disabled with an explanatory placeholder rather than silently swallowing input. |
| Network offline | Top banner, `--warning`; composer disabled; queued draft text preserved verbatim. |
| Stream aborted by user | Partial message kept, marked `Stopped` in `--text-secondary`; Regenerate offered. |
| Empty vector store | First-run notice in the empty state: ingestion has not been run, with the exact command. |

---

## Responsive Behaviour

| Breakpoint | Layout |
| :--------- | :----- |
| `≥ 1280px` | All three zones side by side. Full sidebar. |
| `1024–1279px` | Sidebar auto-collapses to a 56px icon rail when an artifact is open; expands on hover as an overlay. |
| `768–1023px` | Artifact becomes a right-side overlay sheet at 92% width with a scrim; sidebar is a drawer. |
| `< 768px` | Single column. Sidebar is a full-height drawer from the left; artifacts open as a full-screen sheet with a back arrow. Composer is fixed to the bottom with safe-area inset padding. |

Touch targets are ≥ 44px below 1024px. The artifact drag handle is replaced by fixed sizes on
touch, since a 2px hit target is unusable with a finger.

---

## Accessibility

- **Contrast:** all body text meets WCAG AA (≥ 4.5:1) in both themes. Accent-on-white uses
  `--accent-700` for text, `--accent-600` only for fills.

  > **Measured in Phase 4, and three tokens had to change (closes O7).** All 7 text tokens were
  > computed against all 4 surface tokens in both themes — 56 pairs. Six failed as originally
  > specified, and the palette table above now carries the corrected values:
  >
  > | Token | Specified | Measured | Corrected | Why |
  > | :---- | :-------- | :------- | :-------- | :-- |
  > | `--text-tertiary` (light) | `#9A9A91` | 2.51–2.84:1 | `#6D6D67` | Largest miss in either theme. |
  > | `--text-tertiary` (dark) | `#77776E` | 4.08:1 | `#8B8B82` | Below AA on `--bg-canvas`. |
  > | `--warning` (light) | `#B45309` | 4.44:1 | `#A84E08` | Fails on `--bg-inset`, the ground the length-guard notice sits on. |
  > | `--success` (light) | `#157F5A` | 4.40:1 | `#11694A` | Same surface. |
  >
  > Tertiary carries captions and metadata, not only placeholders and disabled controls, so the
  > WCAG disabled-element exemption does not cover it. Each replacement is the smallest step on the
  > same warm ramp that clears 4.5:1 against the *darkest* surface the token actually appears on.
- **Focus:** a 2px `--accent-600` outline at 2px offset on every interactive element. `:focus-visible`
  only, never `outline: none`.
- **Keyboard:** `⌘/Ctrl+K` new chat · `⌘/Ctrl+B` toggle sidebar · `⌘/Ctrl+/` focus composer ·
  `⌘/Ctrl+↵` send · `Esc` closes artifact / exits fullscreen / cancels inline rename. Tab order
  follows visual order: sidebar → chat → artifact → composer.
- **Screen readers:** the message list is `role="log"` with `aria-live="polite"` and
  `aria-relevant="additions"` — assistive tech announces added text without re-reading the
  transcript on every token. The stream itself is announced as a single completed message on `done`
  to avoid per-token spam. The artifact pane is `role="complementary"` with
  `aria-label="Artifact viewer"`; tabs use the full `tablist`/`tab`/`tabpanel` pattern.
- **Semantics:** the skill badge is not colour-only — it always carries text. Status dots pair with
  a text label or `aria-label`. Errors are `role="alert"`.
- **Iframe:** carries a `title` derived from the artifact title, so it is not announced as "frame".
- **Motion:** honoured via `prefers-reduced-motion` as described above.
- **Zoom:** layout holds to 200% browser zoom; nothing depends on a fixed viewport height.

---

## Dark Mode

Not an inversion — a separately tuned palette.

- Toggle in the sidebar footer with three states: **System** (default), **Light**, **Dark**;
  persisted to `localStorage`, applied via `data-theme` on `<html>` before first paint to avoid a
  flash.
- Dark surfaces step *up* in lightness with elevation (`#141413` → `#1C1C1A` → `#232320`), while
  light mode steps *down*. Elevation reads correctly in both without shadows.
- Pure black is avoided: `#141413` reduces halation against light serif text at 17px.
- The accent is lifted (`#E87723` → `#F0873D`) because saturated amber on near-black loses apparent
  contrast.
- **Artifacts are exempt.** A generated HTML mockup renders on its own background inside the
  iframe. The app does not force its theme onto artifact content — that would misrepresent what the
  model produced. The surrounding chrome follows the app theme; the render surface shows the
  artifact's own truth.

---

## Design QA Checklist

Verified before Phase 4 is called complete.

- [ ] No hardcoded colour, radius, spacing, or duration outside the token set
- [ ] Chat prose measure ≤ 720px at every breakpoint
- [ ] Skill B responses render in the serif stack; Skills A and C in the UI stack
- [ ] Artifact iframe is `sandbox="allow-scripts"` with no `allow-same-origin`
- [ ] Preview does not re-mount per token; Code tab streams instead
- [ ] Autoscroll detaches on user scroll-up and shows the jump pill
- [ ] Both toggle halves reflect real `/api/health` state, disabled with a reason when unavailable
- [ ] Every state in [State Coverage](#state-coverage) reachable and visually verified
- [ ] Full keyboard traversal with a visible focus ring on every control
- [ ] AA contrast verified in light and dark for all text tokens
- [ ] `prefers-reduced-motion` removes all non-essential motion
- [ ] No browser `alert()`, `confirm()`, or `prompt()` anywhere in the codebase
- [ ] Layout intact at 200% zoom and at 360px viewport width
