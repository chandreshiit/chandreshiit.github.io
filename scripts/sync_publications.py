import os
import re
import json
import html
import urllib.parse
from datetime import datetime

import requests

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLICATION_DIR = os.path.join(REPO_ROOT, "publication")
TEMPLATE_PATH = os.path.join(PUBLICATION_DIR, "_template", "index.html")
LISTING_PATH = os.path.join(PUBLICATION_DIR, "index.html")
SEEN_PATH = os.path.join(REPO_ROOT, "scripts", "publications_seen.json")

SCHOLAR_AUTHOR_ID = "OR0yLJEAAAAJ"  
SERPAPI_KEY = os.environ.get("SERPAPI_API_KEY")

MARKER_START = "<!-- AUTO-SYNC-PUBLICATIONS-START -->"
MARKER_END = "<!-- AUTO-SYNC-PUBLICATIONS-END -->"


def slugify(text):
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def make_slug(first_author_last_name, year, title):
    base_words = [w for w in slugify(title).split("-") if len(w) > 2][:1]
    keyword = base_words[0] if base_words else "paper"
    slug = f"{slugify(first_author_last_name)}-{year}-{keyword}"
    
    candidate = slug
    n = 2
    while os.path.isdir(os.path.join(PUBLICATION_DIR, candidate)):
        candidate = f"{slug}-{n}"
        n += 1
    return candidate


def clean_venue(venue, year=""):
    """Tidy the venue string Scholar/SerpApi gives us.
    SerpApi appends the year (and sometimes ', 0') to the venue, but the site
    already shows the year separately, like '(2025).' in front of the title."""
    v = (venue or "").strip()
    y = str(year or "").strip()
    if y:
        v = re.sub(r",\s*" + re.escape(y) + r"\s*$", "", v)
    v = re.sub(r",\s*0\s*$", "", v)
    return v.strip(" ,")


def normalize_title(title):
    title = html.unescape(title or "").lower()
    title = re.sub(r"[^a-z0-9 ]+", " ", title)
    return re.sub(r"\s+", " ", title).strip()


def title_similarity(a_norm, b_norm):
    wa, wb = set(a_norm.split()), set(b_norm.split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def load_local_titles():
    """(slug, normalized_title) for every publication folder already on the site."""
    titles = []
    for name in sorted(os.listdir(PUBLICATION_DIR)):
        if name.startswith("_"):
            continue
        bib_path = os.path.join(PUBLICATION_DIR, name, "cite.bib")
        if not os.path.exists(bib_path):
            continue
        with open(bib_path, "r", encoding="utf-8") as f:
            bib = f.read()
        m = re.search(r"title\s*=\s*\{(.+)\}\s*,?\s*$", bib, re.IGNORECASE | re.MULTILINE)
        if m:
            titles.append((name, normalize_title(m.group(1))))
    return titles


def find_same_title(title, local_titles, threshold=0.9):
    """Slug of an existing publication with (nearly) the same title, else None.
    Guards against Scholar handing out a new citation_id for a paper we already have."""
    norm = normalize_title(title)
    best_slug, best_score = None, 0.0
    for slug, local_norm in local_titles:
        score = title_similarity(norm, local_norm)
        if score > best_score:
            best_slug, best_score = slug, score
    return best_slug if best_score >= threshold else None


CARD_SPLIT = re.compile(r'(?=<div class="grid-sizer col-lg-12 isotope-item)')


def sort_cards_newest_first(block):
    """Stable sort of the auto-generated cards by year, newest first."""
    parts = CARD_SPLIT.split(block)
    head, cards = parts[0], parts[1:]

    def year_of(card):
        m = re.search(r'year-(\d*)"', card)
        return int(m.group(1)) if m and m.group(1) else 0

    cards.sort(key=year_of, reverse=True)
    return head + "".join(cards)


def load_seen():
    if os.path.exists(SEEN_PATH):
        with open(SEEN_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_seen(seen):
    os.makedirs(os.path.dirname(SEEN_PATH), exist_ok=True)
    with open(SEEN_PATH, "w", encoding="utf-8") as f:
        json.dump(seen, f, indent=2, ensure_ascii=False)


def fetch_author_publications():
    """Calls SerpApi google_scholar_author engine, paginating as needed."""
    all_articles = []
    start = 0
    while True:
        params = {
            "engine": "google_scholar_author",
            "author_id": SCHOLAR_AUTHOR_ID,
            "sort": "pubdate",
            "start": start,
            "api_key": SERPAPI_KEY,
        }
        resp = requests.get("https://serpapi.com/search.json", params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        articles = data.get("articles", [])
        if not articles:
            break
        all_articles.extend(articles)
        
        if len(articles) < 20:
            break
        start += 20
    return all_articles


def fetch_bibtex(citation_id):
    
    try:
        params = {
            "engine": "google_scholar_cite",
            "q": citation_id,
            "api_key": SERPAPI_KEY,
        }
        resp = requests.get("https://serpapi.com/search.json", params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        for link in data.get("links", []):
            if link.get("name", "").lower() == "bibtex":
                bib_resp = requests.get(link["link"], timeout=30)
                bib_resp.raise_for_status()
                return bib_resp.text
    except Exception as e:
        print(f"  (could not fetch bibtex: {e})")
    return None


def build_fallback_bibtex(article):
    authors = article.get("authors", "")
    title = article.get("title", "")
    year = article.get("year", "")
    venue = clean_venue(article.get("publication", ""), year).replace("&", r"\&")
    first_author_last = authors.split(",")[0].strip().split(" ")[-1] if authors else "unknown"
    key = f"{slugify(first_author_last)}{year}"
    lines = [f"@article{{{key},", f" author = {{{authors}}},", f" title = {{{title}}},"]
    if venue:
        lines.append(f" journal = {{{venue}}},")
    lines.append(f" year = {{{year}}}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def render_publication_page(slug, article):
    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        template = f.read()

    title = article.get("title", "Untitled")
    authors_raw = article.get("authors", "")
    author_names = [a.strip() for a in authors_raw.split(",") if a.strip()]
    year = article.get("year", "")
    venue = clean_venue(article.get("publication", ""), year)
    link = article.get("link", "")

    author_links_html = ", ".join(
        f"<span>{html.escape(name)}</span>" for name in author_names
    ) or "<span>Unknown</span>"

    date_display = str(year) if year else ""
    date_iso = f"{year}-01-01T00:00:00Z" if year else ""

    external_link_button = ""
    if link:
        external_link_button = (
            f'<a class="btn btn-outline-primary my-1 mr-1" href="{html.escape(link)}" '
            f'target="_blank" rel="noopener">\n  <i class="fas fa-external-link-alt"></i> View\n</a>'
        )

    authors_json = json.dumps(
        [{"@type": "Person", "name": n} for n in author_names] or
        [{"@type": "Person", "name": "Unknown"}]
    )

    replacements = {
        "{{SLUG}}": slug,
        "{{TITLE}}": html.escape(title),
        "{{TITLE_JSON}}": title.replace('"', '\\"'),
        "{{TITLE_URLENCODED}}": urllib.parse.quote(title),
        "{{AUTHOR_LINKS_HTML}}": author_links_html,
        "{{AUTHORS_JSON}}": authors_json,
        "{{DATE_DISPLAY}}": date_display,
        "{{DATE_ISO}}": date_iso,
        "{{VENUE}}": html.escape(venue),
        "{{EXTERNAL_LINK_BUTTON}}": external_link_button,
    }

    out = template
    for placeholder, value in replacements.items():
        out = out.replace(placeholder, value)
    return out


def render_listing_card(slug, article):
    title = article.get("title", "Untitled")
    authors_raw = article.get("authors", "")
    author_names = [a.strip() for a in authors_raw.split(",") if a.strip()]
    year = article.get("year", "")
    venue = clean_venue(article.get("publication", ""), year)

    author_spans = ", ".join(f"<span>{html.escape(n)}</span>" for n in author_names)
    year_html = f"\n  ({year})." if year else "."
    venue_html = f"\n  <em>{html.escape(venue)}</em>." if venue else ""

    return f"""
        <div class="grid-sizer col-lg-12 isotope-item pubtype-2 year-{year}">
          <div class="pub-list-item" style="margin-bottom: 1rem">
  <i class="far fa-file-alt pub-icon" aria-hidden="true"></i>

  <span class="article-metadata li-cite-author">
  {author_spans}
  </span>{year_html}
  <a href="/publication/{slug}/">{html.escape(title)}</a>.{venue_html}

  <p>
<button type="button" class="btn btn-outline-primary my-1 mr-1 btn-sm js-cite-modal"
        data-filename="/publication/{slug}/cite.bib">
  Cite
</button>
  </p>
</div>
        </div>
"""


def insert_into_listing(new_cards_html):
    with open(LISTING_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    if MARKER_START not in content or MARKER_END not in content:
        raise RuntimeError(
            "Could not find AUTO-SYNC markers in publication/index.html. "
            "Add '<!-- AUTO-SYNC-PUBLICATIONS-START -->' and "
            "'<!-- AUTO-SYNC-PUBLICATIONS-END -->' right before your first "
            "existing publication card, inside <div id=\"container-publications\">."
        )

    start_idx = content.index(MARKER_START) + len(MARKER_START)
    end_idx = content.index(MARKER_END)
    existing_between = content[start_idx:end_idx]
    auto_block = sort_cards_newest_first(existing_between + new_cards_html)
    updated = content[:start_idx] + auto_block + content[end_idx:]

    with open(LISTING_PATH, "w", encoding="utf-8") as f:
        f.write(updated)


def main():
    if not SERPAPI_KEY:
        raise SystemExit("SERPAPI_API_KEY environment variable is not set.")

    print("Fetching publications from Google Scholar via SerpApi...")
    articles = fetch_author_publications()
    print(f"Found {len(articles)} total publications on Scholar.")

    seen = load_seen()
    local_titles = load_local_titles()
    new_cards_html = ""
    added_count = 0
    seen_changed = False

    for article in articles:
        citation_id = article.get("citation_id")
        if not citation_id:
            continue
        if citation_id in seen:
            continue

        title = article.get("title", "Untitled")

        # Scholar sometimes re-issues a citation_id for a paper we already have
        # (e.g. author list reformatted). Same title => same paper => skip it.
        existing_slug = find_same_title(title, local_titles)
        if existing_slug:
            print(f"Skipping '{title}' - already on site as publication/{existing_slug}/")
            seen[citation_id] = existing_slug
            seen_changed = True
            continue

        authors_raw = article.get("authors", "")
        first_author_last = (
            authors_raw.split(",")[0].strip().split(" ")[-1] if authors_raw else "unknown"
        )
        year = article.get("year", datetime.now().year)

        slug = make_slug(first_author_last, year, title)
        pub_folder = os.path.join(PUBLICATION_DIR, slug)
        os.makedirs(pub_folder, exist_ok=True)

        print(f"Adding new publication: {title} -> publication/{slug}/")

        bibtex = fetch_bibtex(citation_id) or build_fallback_bibtex(article)
        with open(os.path.join(pub_folder, "cite.bib"), "w", encoding="utf-8") as f:
            f.write(bibtex)

        page_html = render_publication_page(slug, article)
        with open(os.path.join(pub_folder, "index.html"), "w", encoding="utf-8") as f:
            f.write(page_html)

        new_cards_html += render_listing_card(slug, article)
        local_titles.append((slug, normalize_title(title)))

        seen[citation_id] = slug
        added_count += 1
        seen_changed = True

    if added_count:
        insert_into_listing(new_cards_html)
    if seen_changed:
        save_seen(seen)

    if added_count:
        print(f"\nDone. Added {added_count} new publication(s).")
    else:
        print("\nNo new publications found. Nothing to do.")


if __name__ == "__main__":
    main()