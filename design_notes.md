# Design Notes

 Static Fetch → Parse → Enough Content? → Yes → Done
                                ↓ (if) No
                      JS Rendering → Dynamic Interactions → Parse → Final JSON

## Static vs JS Fallback

- Strategy:
  - Always attempt static HTML scraping first using `httpx + BeautifulSoup`.
  - Parse sections and compute the total length of `content.text` across all sections.
  - If the total text length is **less than 500 characters** or no sections are produced, static HTML is considered insufficient.
  - In that case, we fall back to **Playwright-based JS rendering**, re-extracting meta and sections from the rendered DOM.
- Rationale:
  - Many static/SEO-friendly pages will be usable directly.
  - JS-heavy apps (marketing sites, dashboards) typically have minimal pre-rendered content, triggering the fallback.

## Wait Strategy for JS

- [x] Network idle
- [x] Fixed sleep
- [x] Wait for selectors (implicitly via click flows and pagination)

- Details:
  - On initial navigation, the page uses `wait_until="networkidle"` with a 20s timeout to ensure that JS-driven content is loaded.
  - After each click and scroll, the scraper performs fixed sleeps between **1–1.5 seconds** to allow additional content to render.
  - Pagination navigation uses `page.wait_for_load_state("networkidle")` to ensure the next page fully loads.

## Click & Scroll Strategy

- Click flows implemented (tabs, load more):
  - Tabs:
    - Find elements matching `[role="tab"], button[role="tab"]`.
    - Click up to 3 tabs, recording each click in `interactions.clicks` as `tab:<label>`.
  - Load more / Show more:
    - Attempt to find and click `button:has-text('Load more')`, `button:has-text('Show more')`, `button:has-text('More')`.
    - Each successful click is recorded in `interactions.clicks`.

- Scroll / pagination approach:
  - Scroll:
    - Perform **3 scroll operations** to the bottom of the page (`window.scrollTo(0, document.body.scrollHeight)`), incrementing `interactions.scrolls`.
  - Pagination:
    - Try up to **2 "next page" navigations** by querying `a[rel=next]`, `a:has-text('Next')`, or `a:has-text('›')`.
    - Each successful navigation is recorded as `pagination:next` in `interactions.clicks`.
    - New URLs are appended to `interactions.pages`.

- Stop conditions (max depth / timeout):
  - Scroll depth limited to 3 operations.
  - Pagination limited to 2 "next" clicks (total depth ≥ 3 pages including the initial).
  - Global timeouts:
    - Initial and pagination navigations use a 20s timeout for `networkidle`.
    - Static HTTP fetch uses a 15s timeout.

## Section Grouping & Labels

- How you group DOM into sections:
  - Prefer semantic containers: `header, nav, main, section, footer, article`.
  - Each such container becomes a section.
  - If no such containers exist, use heading-based grouping:
    - Treat each `h1`, `h2`, or `h3` as the start of a section.
    - Group subsequent siblings until the next heading of the same level.

- How you derive section `type` and `label`:
  - `type`:
    - `nav` for `<nav>` tags.
    - `footer` for `<footer>` tags.
    - `hero` for the first section if it includes typical hero cues (e.g., "hero", "welcome", "home").
    - `faq` if the text includes "faq" or "frequently asked questions".
    - `pricing` if the section contains pricing-related terms ("pricing", "per month", "plan").
    - Default: `section`.
  - `label`:
    - If the section has headings, use the first heading text.
    - Otherwise, derive a label from the first 5–7 words of the section text.
    - Fallback: `"Section"` if the section has no usable text.

## Noise Filtering & Truncation

- What you filter out (e.g., cookie banners, overlays):
  - Remove common noise patterns using CSS selectors, such as:
    - `#cookie-banner`, `.cookie-banner`, `[id*='cookie']`, `[class*='cookie']`, `[aria-label*='cookie']`.
    - Generic overlays like `.modal`, `.newsletter`.
  - These elements are decomposed from the BeautifulSoup tree before section parsing.

- How you truncate `rawHtml` and set `truncated`:
  - `rawHtml` is the string representation of the section's DOM node.
  - If the HTML string exceeds **3000 characters**, it is truncated to the first 3000 characters.
  - The `truncated` flag is set to `true` in that case; otherwise `false`.
