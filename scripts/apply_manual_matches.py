
import os
import json
import requests

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEEN_PATH = os.path.join(REPO_ROOT, "scripts", "publications_seen.json")
SCHOLAR_AUTHOR_ID = "OR0yLJEAAAAJ"
SERPAPI_KEY = os.environ.get("SERPAPI_API_KEY")


MANUAL_MATCHES = [
    ("Filming multimodal sarcasm detection with attention", "gupta-2021-filming"),
    ("Fuzzy inference system for Internet traffic load forecasting", "maurya-2012-fuzzy"),
    ("Anomaly detection in nuclear power plant data using support vector data description", "maurya-2014-anomaly"),
    ("Online anomaly detection via class-imbalance learning", "maurya-2015-online"),
    ("Large-Scale Contact Tracing, Hotspot Detection, and Safe Route Recommendation", "maurya-2021-large"),
    ("An intelligent recommendation-cum-reminder system", "saxena-2022-intelligent"),
    ("Prediction of Late Payment of Invoices in Account Payable Business Process", "tater-2018-prediction"),
    
]


SKIP_TITLES = [
    "Deep Learning Architecture for Automatic Essay Scoring",  
    "others. 2024. FINDINGS OF THE IWSLT 2024 EVALUATION CAMPAIGN",  
    # NOTE: 
]


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

    with open(SEEN_PATH, "r", encoding="utf-8") as f:
        seen = json.load(f)

    articles = fetch_all_articles()

    applied = 0
    for wanted_title, slug in MANUAL_MATCHES:
        found = False
        for article in articles:
            if article.get("title", "").strip().lower() == wanted_title.strip().lower():
                seen[article["citation_id"]] = slug
                applied += 1
                found = True
                print(f"Mapped '{wanted_title}' -> {slug}")
                break
        if not found:
            print(f"WARNING: could not find exact Scholar title match for: {wanted_title}")

    title_seen_count = {}
    skipped = 0
    for article in articles:
        title = article.get("title", "").strip()
        if title in SKIP_TITLES or title_seen_count.get(title, 0) >= 1:
            if article["citation_id"] not in seen:
                seen[article["citation_id"]] = "__SKIP__"
                skipped += 1
                print(f"Skipping duplicate Scholar entry: {title}")
        title_seen_count[title] = title_seen_count.get(title, 0) + 1

    with open(SEEN_PATH, "w", encoding="utf-8") as f:
        json.dump(seen, f, indent=2, ensure_ascii=False)

    print(f"\nApplied {applied} manual matches and {skipped} duplicate-skips.")
    print(f"publications_seen.json now has {len(seen)} entries.")


if __name__ == "__main__":
    main()