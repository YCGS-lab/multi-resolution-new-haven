# Accessibility: audit and plan

Status: **plan for review** (audit of 2026-11-04, branch `accessibility`). Nothing
below except the footer has been changed yet.

## What Yale requires

[Yale Policy 1605, Web Accessibility](https://your.yale.edu/policies-procedures/1605-web-accessibility-policy)
and [Procedure 1605 PR.01](https://your.yale.edu/policies-procedures/procedures/1605-pr01-web-accessibility-procedure):

- **Standard:** WCAG 2.0 Level AA "or its most recent version". We target **WCAG 2.1 AA**,
  which is what the ADA Title II rule also names, and note WCAG 2.2 where it is cheap to meet.
- **Scope:** websites and web applications used for University business on Yale-controlled
  domains. Sites that are new or substantially redesigned after 1 Sep 2018 *must* comply.
  Bowerbird is new, so it must.
- **Accessibility statement and feedback:** every site must link to the accessibility
  statement at <https://usability.yale.edu/web-accessibility/accessibility-yale>, which itself
  links the ITS *Accessibility Comments* form. A footer link on every page is the preferred
  placement. **Done:** the footer (commit `0c9aff4`).
- **Evaluation:** automated scanning (WAVE, Siteimprove) plus manual checklists, testing with
  assistive technology, and optionally an expert review. Contact: accessibility@yale.edu.
- **Exceptions:** granted only where compliance is not technically feasible, and the site
  owner may have to provide an accommodation plan. This may be relevant to the imagery itself
  (see "Maps" below).

## How the audit was done

- A code review of `website/index.html`, `css/style.css` and `js/*.js` against WCAG 2.1 AA.
- Checks in the running page (Chromium): the accessibility tree, accessible names, landmarks
  and headings, computed text contrast, target sizes, and layout at 320 CSS px.
- **Not done yet:** a WAVE or axe scan, and testing with a screen reader (VoiceOver / NVDA).
  Both are in phase 4.

## Findings and fixes

Severity: **H** blocks a task for some users or clearly fails a criterion; **M** is a partial
failure or makes a task harder; **L** is minor or advisory. Each numbered item would be one
commit.

### Phase 1: blockers (H)

1. **The Space key on the Animation tab hijacks buttons** (2.1.1). The page-wide shortcut
   (`js/main.js`, keyboard region) calls `preventDefault` on Space and the arrow keys unless an
   input is focused. So Space on a focused *Load imagery*, tab or picker button toggles
   playback instead. *Fix:* also skip when focus is on a `button`, `a`, `[role=slider]` or
   `canvas`.
2. **Map canvases are tab stops with no visible focus** (2.4.7). deck.gl sets `tabindex=0` and
   an inline `outline:none` on each canvas, so focus disappears into the map. *Fix:*
   `.map canvas:focus-visible, #grid-deck canvas:focus-visible { outline: 3px solid … !important }`.
   Also give the canvas `role="img"` and an `aria-label` such as "Map: Landsat 8-9 true color,
   20 Oct 2026, Greater New Haven" (1.1.1).
3. **Place search isn't announced** (4.1.2). The combobox highlights suggestions with a CSS
   class only. *Fix:* give options ids and `role=option`, and set `aria-activedescendant`,
   `aria-selected`, `aria-autocomplete="list"` and `aria-expanded`. Keep focus in the input on
   Escape or after choosing a place, instead of calling `blur()`. Add `role=status` to the
   "Searching… / No places found" note.
4. **The swipe divider slider has no value** (4.1.2). `role=slider` without `aria-valuenow`,
   `aria-valuemin`, `aria-valuemax` or `aria-valuetext`. *Fix:* set them in `viewer.js`
   `render()`.
5. **The image picker loses focus** (2.4.3). Expanding or collapsing a group re-renders the
   tree, focus drops to `<body>`, and the arrow keys stop working. *Fix:* re-focus the same
   `[data-key]` after rendering. In the same commit, fix the roles: the trigger gets
   `aria-expanded`, and the tree uses plain buttons (or `tree`/`treeitem`) instead of a
   `listbox` that contains buttons.
6. **Grid rearranging is drag-and-drop only** (2.1.1, 2.5.7). *Fix:* in rearrange mode, each
   slot gets "Move earlier" and "Move later" buttons.
7. **The header doesn't reflow** (1.4.10). At 320 CSS px wide (or 400% zoom) the place
   search, Location tools and Credentials buttons are off-screen and can't be reached, and the
   fixed 102 px header takes up much of the height. *Fix:* a narrow-screen layout: the header
   wraps and becomes `position: static`, the tabs scroll, and the panels drop their
   `height: calc(100vh - …)` for a minimum height.

### Phase 2: names, roles, states (M)

8. **Icon-only buttons are named by their glyph** (4.1.2). A `title` doesn't override the
   content, so these read as "black left-pointing triangle", "+", "⤢" and so on. The affected
   buttons are ◀ ▶, ⇆, + − ⤢, ×, ⏮ ‹ › ⏭ and Play/❚❚. *Fix:* add an `aria-label` to each
   ("Previous image", "Zoom in", "Reset view", "Swap A and B", "Play"/"Pause") and
   `aria-hidden` on the glyphs and ▾ carets.
9. **Tabs** (4.1.2). Add `aria-controls` and `aria-labelledby`, a roving tabindex and
   Left/Right arrow keys. The ICESat-2 panel has no tab, so all tabs show
   `aria-selected=false` while it is open. Drop `role=tabpanel` there and label it as a region
   instead.
10. **Compare mode** is a `radiogroup` of `aria-pressed` buttons. *Fix:* use `role=radio` with
    `aria-checked` and arrow keys.
11. **Location tools menu.** It has `role=menu` without menu keyboard behaviour. *Fix:* make
    it a plain disclosure: a button with `aria-expanded` and a list of buttons.
12. **Labels in context** (1.3.1, 2.4.6). Label the A and B pickers "Image A" and "Image B".
    In grid slots, include the slot number ("Slot 3: select an image", "Remove slot 3"). Keep
    the cloud-cover label in compact time controls visually hidden instead of `display:none`.
    Give "locked", "cloud only" and "no data in view" in the picker visually hidden text
    instead of only a `title`.
13. **Sliders.** Set `aria-valuetext` to the date on the animation frame slider. Give the
    ICESat-2 arrow `aria-valuemin` and `aria-valuemax`. The profile canvas gets
    `role=slider`, or `role=img` plus the readout. Calendar day buttons get the full date as
    their `aria-label`, and the calendar popup gets a name.
14. **Status messages** (4.1.3). Add `role=status` to map "Loading…" and "N tiles failed",
    and to the animation progress (plus `role=progressbar` with values). Keep live regions in
    the DOM and change only their text, rather than toggling `hidden`.
15. **Focus management** (2.4.3). Close the picker and calendar popups when focus leaves them.
    When a button hides itself (Load ↔ Cancel, tools items, grid ×), move focus to a sensible
    neighbour first. Return focus from the credentials dialog to whatever opened it.
16. **Place-search focus style** (2.4.7). `outline:none`, and the only replacement is a
    1.4:1 background change. Add a visible outline on `:focus-within`.

### Phase 3: visual (M/L)

17. **Text contrast** (1.4.3). `--gray-500` #757575 on the page background #f7f7f7 is
    **4.30:1**, below 4.5:1 for the 11-13 px muted text: date labels, source lines, counts and
    help. *Fix:* `--gray-500: #6b6b6b` (4.97:1). Picker items with no data in view are
    #757575 at 0.7 opacity (**≈2.7:1**). Drop the opacity and rely on the icon and the text
    from item 12.
18. **Control borders** (1.4.11). `--gray-300` #bababa as an input, select or picker border is
    **1.8-1.9:1**. *Fix:* use #8a8a8a or darker for form-control borders (≥3:1).
19. **Small text and targets.** Raise the 11 px text to 12 px or more. Make the ◀ ▶ step
    buttons and the clear × at least 24×24 px (2.5.8, WCAG 2.2). Use rem for font sizes so
    text-only zoom works (1.4.4).
20. **Color-only distinctions** (1.4.1). ICESat-2 photon classes differ by color alone in the
    profile. *Fix:* use distinct marker shapes, or per-class show/hide toggles. Check the
    white numbers on the beam-colored circles for 4.5:1.

### Phase 4: page-level and verification (L)

21. **Skip link** ("Skip to map") before the header (2.4.1). Restore the `nav` landmark: put
    `role=tablist` on an inner element.
22. **Keyboard shortcuts** (2.1.4). `[ ] , . 0` and Space act page-wide. Either act only when
    the map or panel has focus, or add a "Keyboard shortcuts" toggle. List the shortcuts in a
    help popover.
23. **Motion.** Cap the animation at 3 frames/s, or warn above it: fast changes between
    bright and dark frames can exceed three flashes per second (2.3.1). Honour
    `prefers-reduced-motion` for smooth scrolling and map inertia.
24. **Verification.** Run WAVE and axe on every tab. Do a keyboard-only pass and a VoiceOver
    (Safari) pass on the main tasks: pick an image, change the date, compare, build a grid,
    play an animation, search for a place. Record the results here.

### Maps themselves

The satellite images and deck.gl maps can't be made fully accessible to screen-reader
users. Under WCAG, the text around them is what counts as their alternative: the title, the
date, the legend with its labels, and the source line. Items 2 and 13 make that text
programmatically tied to the map. If a user can't use the imagery, Yale's procedure is an
accessible alternative format on request (for example, the data values for a point or area).
Consider saying so on the site.

## Already in good shape

`lang="en"`, a descriptive `<title>`, header, main and footer landmarks, an h1 and h2 titles.
Alt text on the logo, decorative icons `aria-hidden`. The credentials form is a native modal
`<dialog>` with labelled fields and fieldsets. Escape closes the picker and calendar and
returns focus. `aria-expanded` is set on Location tools and Advanced. The ICESat-2 arrow is a
proper slider with a focus style. Every visible form field has a label. Nothing autoplays,
and the animation has play/pause, speed and loop. Legends have text labels, and A/B are
letters, not just colors. White on Yale blue is 12.2:1 and links are 5.3:1.
