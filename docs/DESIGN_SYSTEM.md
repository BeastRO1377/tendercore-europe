# TenderCore Europe — UI Design Contract v1.0

**Normative:** Shared controls must use the design system at `static/design-system.css`. Do not add page-local button, select, checkbox or input dimensions to `static/styles.css` or JS-generated markup. Every new screen must conform.

## Baseline and spacing

- **Base rhythm:** 4 CSS pixels, vertical measures and padding in multiples of 4.
- **Body/input text:** 13px / **20px line-height**; control/label text: 12px / **20px line-height**.
- **Headings:** h1 30px/36px desktop, 26px/32px mobile; section headings align to 28px line box.
- **Controls:** buttons, selects, text/date/number/search inputs and segmented items are **40px** high. Radius **8px**. Never use 37px/39px overrides. Icons-only: **40×40px**.
- **Checkboxes:** consistently **18×18px** with 40px minimum target area in labels and chips.
- **Field labels in two-column rows:** reserve **40px** for up to two lines; align final label baseline just above its 40px control. Same rule across tax, criteria, and analytics forms.
- **Focus indicator:** shared teal focus outline + ring; keep visible and keyboard accessible.
- **Textareas:** auto or minimum 80px, 20px line-height (intentionally different from single-line controls).

## Appearance and localization

- Three modes: `system` via `prefers-color-scheme`, explicit `light`, explicit `dark`. Theme colors use `--bg`, `--panel`, `--field`, `--text`, `--border`, and semantic tokens. No page-specific hardcoded colors.
- RU / EN: translate headings, controls, status labels, tooltips and `aria-label`s. Original TED notice titles and CPV descriptions may remain in source language; do not pretend these are translations.
- Desktop-first, responsive mobile navigation down to 320px. Sidebar is an accessible toggleable drawer on widths <= 660px; Escape/backdrop close it. No horizontal overflow on screens 320px+.
- Toggle between tiles/list; maintain the same base control dimensions across both.

## Verification gate before release

1. Run Python regression suite: `python -m unittest discover -s tests -v`.
2. Run UI offline visual regression: `python scripts/visual_regression.py` after installing `playwright` and Chromium. It tests five pages, RU/EN, three themes, widths 320/390/768/1024/1440.
3. Manually inspect screenshots for text overflow and layout. Offline mock visual checks do not validate live TED API or business data.
4. Check a populated application with actual user data before production use.

**Source of truth:** `static/design-system.css`. This contract applies to all future TenderCore Europe pages, including dialogs and new analytical modules.
