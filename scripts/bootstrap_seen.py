
import os
import re
import json
import requests

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLICATION_DIR = os.path.join(REPO_ROOT, "publication")
SEEN_PATH = os.path.join(REPO_ROOT, "scripts", "publications_seen.json")
SCHOLAR_AUTHOR_ID = "OR0yLJEAAAAJ"
SERPAPI_KEY = os.environ.get("SERPAPI_API_KEY")

CONFIDENT_THRESHOLD = 0.6
BORDERLINE_THRESHOLD = 0.35


def normalize(title):
    title = title.lower()
    title = re.sub(r"[^a-z0-9 ]+", " ", title)
    return re.sub(r"\s+", " ", title).strip()


def similarity(a_norm, b_norm):
    wa, wb = set(a_norm.split()), set(b_norm.split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def extract_title_from_bib(bib_text):
    m = re.search(r"title\s*=\s*\{(.+)\}\s*,?\s*$", bib_text, re.IGNORECASE | re.MULTILINE)
    return m.group(1) if m else None


def existing_titles():
    entries = []  
    for name in sorted(os.listdir(PUBLICATION_DIR)):
        folder = os.path.join(PUBLICATION_DIR, name)
        bib_path = os.path.join(folder, "cite.bib")
        if name.startswith("_"):
            continue
        if os.path.isdir(folder) and os.path.exists(bib_path):
            with open(bib_path, "r", encoding="utf-8") as f:
                bib = f.read()
            title = extract_title_from_bib(bib)
            if title:
                entries.append((name, title, normalize(title)))
            else:
                print(f"  WARNING: could not extract title from {name}/cite.bib")
    return entries


def fetch_all_articles():
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


def main():
    if not SERPAPI_KEY:
        raise SystemExit("SERPAPI_API_KEY environment variable is not set.")

    local_entries = existing_titles()
    print(f"Found {len(local_entries)} existing publication folders locally.\n")

    print("Fetching full Scholar list...")
    articles = fetch_all_articles()
    print(f"Found {len(articles)} publications on Scholar.\n")

    used_slugs = set()
    seen = {}
    confident_matches = []
    borderline_matches = []
    new_papers = []

    for article in articles:
        citation_id = article.get("citation_id")
        title = article.get("title", "")
        norm_scholar = normalize(title)

        best_slug, best_title, best_score = None, None, 0.0
        for slug, raw_title, norm_local in local_entries:
            if slug in used_slugs:
                continue
            score = similarity(norm_scholar, norm_local)
            
            prefix_len = min(40, len(norm_scholar), len(norm_local))
            if norm_scholar[:prefix_len] == norm_local[:prefix_len] and prefix_len >= 20:
                score = max(score, 0.9)
            if score > best_score:
                best_score, best_slug, best_title = score, slug, raw_title

        if best_score >= CONFIDENT_THRESHOLD:
            seen[citation_id] = best_slug
            used_slugs.add(best_slug)
            confident_matches.append((title, best_slug, best_title, best_score))
        elif best_score >= BORDERLINE_THRESHOLD:
            borderline_matches.append((title, best_slug, best_title, best_score, citation_id))
        else:
            new_papers.append(title)

    with open(SEEN_PATH, "w", encoding="utf-8") as f:
        json.dump(seen, f, indent=2, ensure_ascii=False)

    print(f"CONFIDENT MATCHES ({len(confident_matches)}) — marked as seen automatically:")
    for scholar_title, slug, local_title, score in confident_matches:
        print(f"  [{score:.2f}] {slug}\n         Scholar: {scholar_title}\n         Local:   {local_title}\n")

    print(f"\nBORDERLINE MATCHES ({len(borderline_matches)}) — NOT auto-marked, please review:")
    for scholar_title, slug, local_title, score, citation_id in borderline_matches:
        print(f"  [{score:.2f}] possible match to '{slug}'")
        print(f"         Scholar: {scholar_title}")
        print(f"         Local:   {local_title}")
        print(f"         citation_id: {citation_id}\n")

    print(f"\nCLEARLY NEW ({len(new_papers)}) — will be added by sync_publications.py:")
    for t in new_papers:
        print(f"  - {t}")

    print(
        f"\nscripts/publications_seen.json written with {len(seen)} confident entries.\n"
        "If any BORDERLINE matches above are actually the same paper, tell me the "
        "Scholar title + local slug pairs and I'll add them to seen.json manually "
        "before you run the sync script."
    )


if __name__ == "__main__":
    main()