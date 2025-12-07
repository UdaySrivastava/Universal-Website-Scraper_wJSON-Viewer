import asyncio
import datetime
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, HttpUrl
from bs4 import BeautifulSoup
from urllib.parse import urljoin

import httpx
from playwright.async_api import async_playwright

app = FastAPI(title="Lyftr Universal Website Scraper")

templates = Jinja2Templates(directory="templates")

# CORS (in case you later call the API from a separate SPA)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- Pydantic models ----------

class ScrapeRequest(BaseModel):
    url: HttpUrl  # enforces http/https


# ---------- Utilities for scraping ----------

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

STATIC_TEXT_THRESHOLD = 500  # heuristic for "enough content"
RAW_HTML_TRUNCATE_CHARS = 3000


async def fetch_static_html(url: str, errors: List[Dict[str, Any]]) -> str:
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(15.0, connect=5.0)
        ) as client:
            resp = await client.get(url, headers={"User-Agent": USER_AGENT})
            resp.raise_for_status()
            return resp.text
    except Exception as e:
        errors.append({"message": f"Static fetch failed: {e}", "phase": "fetch"})
        return ""


def extract_meta(soup: BeautifulSoup, url: str) -> Dict[str, Any]:
    # Title
    title_tag = soup.find("title")
    og_title = soup.find("meta", property="og:title")
    title = ""
    if og_title and og_title.get("content"):
        title = og_title["content"].strip()
    elif title_tag and title_tag.get_text(strip=True):
        title = title_tag.get_text(strip=True)

    # Description
    description = ""
    desc_tag = soup.find("meta", attrs={"name": "description"})
    if not desc_tag:
        desc_tag = soup.find("meta", attrs={"property": "og:description"})
    if desc_tag and desc_tag.get("content"):
        description = desc_tag["content"].strip()

    # Language
    html_tag = soup.find("html")
    language = ""
    if html_tag and html_tag.get("lang"):
        language = html_tag["lang"].strip()
    if not language:
        # Best-effort: you could enhance with langdetect, but spec allows a guess.
        language = "en"

    # Canonical
    canonical_tag = soup.find("link", rel="canonical")
    canonical = canonical_tag["href"].strip() if canonical_tag and canonical_tag.get("href") else None

    return {
        "title": title or "",
        "description": description or "",
        "language": language,
        "canonical": canonical,
    }


def remove_noise(soup: BeautifulSoup) -> None:
    # Very simple cookie / overlay filtering
    selectors = [
        "#cookie-banner",
        ".cookie-banner",
        "[id*='cookie']",
        "[class*='cookie']",
        "[aria-label*='cookie']",
        "[aria-label*='Cookie']",
        ".modal",
        ".newsletter",
    ]
    for sel in selectors:
        for el in soup.select(sel):
            el.decompose()


def derive_section_type(tag_name: str, text: str, index: int) -> str:
    lower_text = (text or "").lower()

    if tag_name == "nav":
        return "nav"
    if tag_name == "footer":
        return "footer"
    if index == 0 and ("hero" in lower_text or "welcome" in lower_text or "home" in lower_text):
        return "hero"
    if "faq" in lower_text or "frequently asked questions" in lower_text:
        return "faq"
    if "pricing" in lower_text or "per month" in lower_text or "plan" in lower_text:
        return "pricing"
    # Could further refine for list/grid but not required
    return "section"


def derive_label(headings: List[str], text: str) -> str:
    if headings:
        return headings[0]
    words = (text or "").split()
    if not words:
        return "Section"
    return " ".join(words[:7])


def make_absolute_links(links: List[Dict[str, str]], base_url: str) -> List[Dict[str, str]]:
    for link in links:
        link["href"] = urljoin(base_url, link["href"])
    return links


def parse_sections_from_soup(soup: BeautifulSoup, url: str) -> List[Dict[str, Any]]:
    """
    Parse the page into logical sections.

    Fix for Hacker News / table-based layouts:
    - If no semantic containers (header/main/section/etc.) AND
      no heading-based containers are found, treat the entire
      <body> as a single section so we never return 0 sections.
    """
    remove_noise(soup)

    body = soup.body or soup

    # Primary: semantic containers
    containers = body.select("header, nav, main, section, footer, article")

    # Fallback 1: heading-based grouping
    if not containers:
        containers = body.find_all(["h1", "h2", "h3"])

    # Fallback 2: nothing semantic or headings (e.g. Hacker News: table layout)
    # → treat whole <body> as one section.
    if not containers:
        containers = [body]

    sections: List[Dict[str, Any]] = []

    for idx, container in enumerate(containers):
        # Determine the DOM node we treat as "section root"
        if container.name in ["h1", "h2", "h3"]:
            # Group heading with its following siblings until next top-level heading
            wrapper = soup.new_tag("div")
            wrapper.append(container)
            sibling = container.next_sibling
            while sibling:
                if getattr(sibling, "name", None) in ["h1", "h2", "h3"]:
                    break
                wrapper.append(sibling)
                sibling = sibling.next_sibling
            node = wrapper
            tag_name = "section"
        else:
            node = container
            tag_name = container.name or "section"
            # If the container is <body>, treat it as a generic section
            if tag_name == "body":
                tag_name = "section"

        # Headings
        headings = [h.get_text(" ", strip=True) for h in node.find_all(["h1", "h2", "h3"])]

        # Text
        text = node.get_text(" ", strip=True)

        # Links
        links = []
        for a in node.find_all("a", href=True):
            href = a["href"]
            text_a = a.get_text(" ", strip=True)
            if not href.strip():
                continue
            links.append({"text": text_a, "href": href})
        links = make_absolute_links(links, url)

        # Images
        images = []
        for img in node.find_all("img", src=True):
            src = img["src"]
            alt = img.get("alt", "").strip()
            images.append({"src": urljoin(url, src), "alt": alt})

        # Lists
        lists: List[List[str]] = []
        for ul in node.find_all(["ul", "ol"]):
            items = [li.get_text(" ", strip=True) for li in ul.find_all("li")]
            if items:
                lists.append(items)

        # Tables (list of rows, each row is list of cell texts)
        tables: List[List[List[str]]] = []
        for table in node.find_all("table"):
            table_data: List[List[str]] = []
            for row in table.find_all("tr"):
                cells_text = [c.get_text(" ", strip=True) for c in row.find_all(["td", "th"])]
                if cells_text:
                    table_data.append(cells_text)
            if table_data:
                tables.append(table_data)

        # Raw HTML truncated
        raw_html_full = str(node)
        truncated = len(raw_html_full) > RAW_HTML_TRUNCATE_CHARS
        raw_html = raw_html_full[:RAW_HTML_TRUNCATE_CHARS]

        section_text = text or ""
        section_type = derive_section_type(tag_name, section_text, idx)
        label = derive_label(headings, section_text)

        section = {
            "id": f"{section_type}-{idx}",
            "type": section_type,
            "label": label,
            "sourceUrl": url,
            "content": {
                "headings": headings,
                "text": section_text,
                "links": links,
                "images": images,
                "lists": lists,
                "tables": tables,
            },
            "rawHtml": raw_html,
            "truncated": truncated,
        }

        # Skip totally empty sections
        if section["content"]["text"] or section["content"]["headings"] or section["content"]["links"]:
            sections.append(section)

    return sections


def is_static_sufficient(sections: List[Dict[str, Any]]) -> bool:
    """
    Decide if static HTML alone is "good enough".

    - If there are **no sections**, static is not sufficient.
    - If there is **only one big section**, treat it as NOT sufficient
      (we prefer to try JS fallback to explore more content / structure).
    - Otherwise, check total text length vs STATIC_TEXT_THRESHOLD.
    """
    if not sections:
        return False

    total_len = sum(len(s["content"]["text"]) for s in sections)

    # Force JS fallback for single giant section pages (e.g. table layouts like HN)
    if len(sections) == 1 and total_len >= STATIC_TEXT_THRESHOLD:
        return False

    return total_len >= STATIC_TEXT_THRESHOLD


async def fetch_js_html_and_interact(
    url: str,
    interactions: Dict[str, Any],
    errors: List[Dict[str, Any]],
) -> str:
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(user_agent=USER_AGENT)
            page = await context.new_page()

            await page.goto(url, wait_until="networkidle", timeout=20000)
            interactions["pages"] = [page.url]

            # Click tabs ([role="tab"])
            try:
                tab_elements = await page.query_selector_all("[role='tab'], button[role='tab']")
                for el in tab_elements[:3]:
                    try:
                        label = await el.get_attribute("aria-label") or await el.inner_text()
                        label = (label or "").strip()
                        interactions["clicks"].append(f"tab:{label[:40]}")
                        await el.click()
                        await page.wait_for_timeout(1000)
                    except Exception as e:
                        errors.append({"message": f"Tab click failed: {e}", "phase": "render"})
                        continue
            except Exception as e:
                errors.append({"message": f"Tab discovery failed: {e}", "phase": "render"})

            # "Load more / Show more" style buttons
            for label in ["Load more", "Show more", "More"]:
                try:
                    btn = await page.query_selector(f"button:has-text('{label}')")
                    if btn:
                        interactions["clicks"].append(f"button:has-text('{label}')")
                        await btn.click()
                        await page.wait_for_timeout(1500)
                except Exception as e:
                    errors.append({"message": f'Load more click "{label}" failed: {e}', "phase": "render"})

            # Infinite scroll (depth >= 3)
            for _ in range(3):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                interactions["scrolls"] += 1
                await page.wait_for_timeout(1500)

            # Pagination links (try to reach 3 pages total)
            try:
                for _ in range(2):  # we already have page 1
                    next_link = await page.query_selector("a[rel=next], a:has-text('Next'), a:has-text('›')")
                    if not next_link:
                        break
                    interactions["clicks"].append("pagination:next")
                    await next_link.click()
                    await page.wait_for_load_state("networkidle", timeout=20000)
                    url_after = page.url
                    if url_after not in interactions["pages"]:
                        interactions["pages"].append(url_after)
            except Exception as e:
                errors.append({"message": f"Pagination failed: {e}", "phase": "render"})

            html = await page.content()
            await context.close()
            await browser.close()
            return html
    except Exception as e:
        errors.append({"message": f"JS rendering failed: {e}", "phase": "render"})
        return ""


async def scrape_url(url: str) -> Dict[str, Any]:
    errors: List[Dict[str, Any]] = []
    interactions: Dict[str, Any] = {
        "clicks": [],
        "scrolls": 0,
        "pages": [url],
    }

    # 1. Static scraping
    static_html = await fetch_static_html(url, errors)
    sections: List[Dict[str, Any]] = []
    meta: Dict[str, Any] = {"title": "", "description": "", "language": "en", "canonical": None}

    if static_html:
        soup = BeautifulSoup(static_html, "lxml")
        meta = extract_meta(soup, url)
        sections = parse_sections_from_soup(soup, url)

    # 2. Decide whether to fallback to JS
    use_js = not is_static_sufficient(sections)

    if use_js:
        js_html = await fetch_js_html_and_interact(url, interactions, errors)
        if js_html:
            soup_js = BeautifulSoup(js_html, "lxml")
            meta = extract_meta(soup_js, url)
            sections = parse_sections_from_soup(soup_js, url)
        # If JS failed, we keep whatever static data we had (even if limited)

    scraped_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    result = {
        "url": url,
        "scrapedAt": scraped_at,
        "meta": meta,
        "sections": sections or [],  # ensure list
        "interactions": interactions,
        "errors": errors,
    }
    return result


# ---------- Routes ----------

@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/scrape")
async def scrape_endpoint(payload: ScrapeRequest):
    url_str = str(payload.url)

    # Scheme check (HttpUrl already restricts to http/https, but we add explicit guard)
    if not (url_str.startswith("http://") or url_str.startswith("https://")):
        raise HTTPException(
            status_code=400,
            detail="Only http(s) URLs are supported.",
        )

    result = await scrape_url(url_str)

    response = {"result": result}
    return JSONResponse(content=response)
