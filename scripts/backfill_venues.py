
import os
import re
import sys
import html

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUB_DIR = os.path.join(REPO_ROOT, "publication")
LISTING = os.path.join(PUB_DIR, "index.html")
MARKER_START = "<!-- AUTO-SYNC-PUBLICATIONS-START -->"
MARKER_END = "<!-- AUTO-SYNC-PUBLICATIONS-END -->"
DRY = "--dry-run" in sys.argv

CARD_SPLIT = re.compile(r'(?=<div class="grid-sizer col-lg-12 isotope-item)')


def clean_venue(venue, year=""):
    v = (venue or "").strip()
    y = str(year or "").strip()
    if y:
        v = re.sub(r",\s*" + re.escape(y) + r"\s*$", "", v)
    v = re.sub(r",\s*0\s*$", "", v)
    return v.strip(" ,")


def sort_cards_newest_first(block):
    parts = CARD_SPLIT.split(block)
    head, cards = parts[0], parts[1:]

    def year_of(card):
        m = re.search(r'year-(\d*)"', card)
        return int(m.group(1)) if m and m.group(1) else 0

    cards.sort(key=year_of, reverse=True)
    return head + "".join(cards)


def main():
    with open(LISTING, "r", encoding="utf-8") as f:
        listing = f.read()

    if MARKER_START not in listing or MARKER_END not in listing:
        raise SystemExit("AUTO-SYNC markers not found in publication/index.html")

    filled, bib_updated, no_venue, truncated, problems = [], [], [], [], []

    for slug in sorted(os.listdir(PUB_DIR)):
        page_path = os.path.join(PUB_DIR, slug, "index.html")
        if slug.startswith("_") or not os.path.isfile(page_path):
            continue

        anchor = re.compile(
            r'(<a href="/publication/' + re.escape(slug) + r'/">[^<]*</a>\.)(?!\s*<em>)'
        )
        matches = anchor.findall(listing)
        if not matches:
            continue  # card missing, or it already shows a venue
        if len(matches) > 1:
            problems.append(f"{slug}: card found {len(matches)} times, skipped")
            continue

        with open(page_path, "r", encoding="utf-8") as f:
            page = f.read()

        m = re.search(
            r'Publication</div>\s*<div class="col-12 col-md-9"><em>(.*?)</em></div>',
            page, re.S,
        )
        year_m = re.search(r'article:published_time" content="(\d{4})', page)
        year = year_m.group(1) if year_m else ""
        venue_html = clean_venue(m.group(1), year) if m else ""

        if not venue_html:
            no_venue.append(slug)
            continue

        listing = anchor.sub(lambda mo: mo.group(1) + f"\n  <em>{venue_html}</em>.", listing, count=1)
        filled.append(slug)
        if venue_html.endswith("\u2026"):
            truncated.append((slug, html.unescape(venue_html)))

        # cite.bib: add journal line if there is no venue field yet
        bib_path = os.path.join(PUB_DIR, slug, "cite.bib")
        if os.path.isfile(bib_path):
            with open(bib_path, "r", encoding="utf-8") as f:
                bib = f.read()
            if not re.search(r"^\s*(journal|booktitle)\s*=", bib, re.M):
                venue_bib = html.unescape(venue_html).replace("&", r"\&")
                new_bib, n = re.subn(r"\n year = ", f"\n journal = {{{venue_bib}}},\n year = ", bib, count=1)
                if n:
                    bib_updated.append(slug)
                    if not DRY:
                        with open(bib_path, "w", encoding="utf-8") as f:
                            f.write(new_bib)

    # papers with no year: drop the empty "()."
    empty_years = len(re.findall(r"</span>\s*\(\)\.\n", listing))
    listing = re.sub(r"(</span>)\s*\(\)\.\n", r"\1\n", listing)

    # newest first inside the auto-generated block
    s = listing.index(MARKER_START) + len(MARKER_START)
    e = listing.index(MARKER_END)
    listing = listing[:s] + sort_cards_newest_first(listing[s:e]) + listing[e:]

    if not DRY:
        with open(LISTING, "w", encoding="utf-8") as f:
            f.write(listing)

    tag = "[dry run] would update" if DRY else "Updated"
    print(f"{tag} {len(filled)} listing cards with a venue")
    print(f"{tag} {len(bib_updated)} cite.bib files with a journal line")
    print(f"Removed {empty_years} empty year '().'; auto-generated cards re-sorted newest first")
    if no_venue:
        print(f"\nNo venue found for {len(no_venue)} (these never had one, left as they are): {', '.join(no_venue)}")
    if truncated:
        print(f"\nScholar cut these venue names short with '...' - fix by hand if you want the full name ({len(truncated)}):")
        for slug, v in truncated:
            print(f"  {slug}: {v}")
    for p in problems:
        print("WARNING:", p)


if __name__ == "__main__":
    main()