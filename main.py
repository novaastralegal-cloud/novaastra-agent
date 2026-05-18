"""
Novaastra Legal — Growth Agent Backend v3
More generous AI extraction + fallback sample data if feeds return nothing
"""

from flask import Flask, jsonify
from flask_cors import CORS
import feedparser
import json
import os
from datetime import datetime
import anthropic
import re

app = Flask(__name__)
CORS(app)

@app.after_request
def add_cors(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response

@app.route('/api/<path:path>', methods=['OPTIONS'])
def options_handler(path):
    return '', 204

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

FEEDS = {
    "funding":  "https://news.google.com/rss/search?q=India+startup+funding+crore+raised&hl=en-IN&gl=IN&ceid=IN:en",
    "brand":    "https://news.google.com/rss/search?q=India+brand+trademark+launch&hl=en-IN&gl=IN&ceid=IN:en",
    "startup":  "https://news.google.com/rss/search?q=India+new+startup+company+launch+2026&hl=en-IN&gl=IN&ceid=IN:en",
    "msme":     "https://news.google.com/rss/search?q=India+MSME+small+business+brand+2026&hl=en-IN&gl=IN&ceid=IN:en",
}

STARTUPTALKY = "https://startuptalky.com/rss"


def fetch_feed(url, max_items=10):
    try:
        feed = feedparser.parse(url)
        items = []
        for entry in feed.entries[:max_items]:
            title = entry.get("title", "").strip()
            summary = entry.get("summary", "").strip()[:300]
            if title:
                items.append({
                    "title": title,
                    "summary": summary,
                    "source": entry.get("source", {}).get("title", "News"),
                })
        return items
    except Exception as e:
        print(f"Feed error {url}: {e}")
        return []


def extract_opportunities(articles):
    """Use Claude to extract companies needing IP help - generous extraction."""
    if not articles or not ANTHROPIC_API_KEY:
        return []

    text = "\n".join([f"- {a['title']}" for a in articles[:12]])

    prompt = f"""You are an IP intelligence analyst for a trademark law firm in India (Novaastra Legal).

Below are today's Indian business news headlines. Extract ANY company or brand that could benefit from trademark or IP legal services.

Be GENEROUS — include companies that:
- Just raised funding (they need trademark protection before scaling)
- Launched a new product or brand
- Are expanding to new markets
- Are new startups or D2C brands
- Had any brand/name related news
- Are in consumer goods, fashion, food, tech, pharma, or any product sector

Headlines:
{text}

For each relevant company, return a JSON object with:
- company: company or brand name (string)
- reason: specific one-sentence reason they need IP/trademark help (string)
- sector: industry sector (string)
- trigger: one of "Funding Raised", "Product Launch", "Brand Dispute", "New Registration", "Market Expansion" (string)
- urgency: "High", "Medium", or "Low" (string)

Return a JSON array. Include at least 3-5 companies if possible. Be inclusive rather than exclusive.
If truly no companies found, return [].
Raw JSON array only. No markdown, no explanation."""

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}]
        )
        text_out = response.content[0].text.strip()
        text_out = re.sub(r'```json|```', '', text_out).strip()
        result = json.loads(text_out)
        return result if isinstance(result, list) else []
    except Exception as e:
        print(f"AI error: {e}")
        return []


def get_sample_opportunities():
    """Fallback sample data when feeds return nothing useful."""
    return [
        {
            "company": "Sample — Real data unavailable today",
            "reason": "RSS feeds returned no relevant articles today. Try again tomorrow morning when fresh news is available.",
            "sector": "System Message",
            "trigger": "New Registration",
            "urgency": "Low"
        }
    ]


@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "name": "Novaastra Legal Growth Agent API",
        "status": "running",
        "version": "3.0"
    })


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "anthropic_configured": bool(ANTHROPIC_API_KEY),
        "version": "3.0"
    })


@app.route("/api/opportunities", methods=["GET"])
def get_opportunities():
    all_articles = []

    # Collect from all feeds
    for key, url in FEEDS.items():
        articles = fetch_feed(url, 8)
        all_articles.extend(articles)
        print(f"Feed {key}: {len(articles)} articles")

    # Also try StartupTalky
    st_articles = fetch_feed(STARTUPTALKY, 10)
    all_articles.extend(st_articles)
    print(f"StartupTalky: {len(st_articles)} articles")

    print(f"Total articles collected: {len(all_articles)}")

    # Deduplicate articles by title
    seen_titles = set()
    unique_articles = []
    for a in all_articles:
        t = a['title'].lower()[:60]
        if t not in seen_titles:
            seen_titles.add(t)
            unique_articles.append(a)

    print(f"Unique articles: {len(unique_articles)}")

    # Extract opportunities
    opps = []
    if unique_articles:
        opps = extract_opportunities(unique_articles)
        print(f"Opportunities extracted: {len(opps)}")

    # Deduplicate by company name
    seen_companies = set()
    unique_opps = []
    for opp in opps:
        name = opp.get("company", "").lower().strip()
        if name and name not in seen_companies and len(name) > 2:
            seen_companies.add(name)
            unique_opps.append(opp)

    # If nothing found use sample
    if not unique_opps:
        print("No opportunities found — returning sample data")
        unique_opps = get_sample_opportunities()

    return jsonify({
        "success": True,
        "count": len(unique_opps),
        "opportunities": unique_opps,
        "articles_scanned": len(unique_articles),
        "fetched_at": datetime.now().isoformat(),
    })


@app.route("/api/news-summary", methods=["GET"])
def news_summary():
    articles = fetch_feed(FEEDS["brand"], 5)
    if not articles or not ANTHROPIC_API_KEY:
        return jsonify({"success": False, "summary": "No data today."})

    headlines = "\n".join([f"- {a['title']}" for a in articles])
    prompt = f"""Summarise these India business/brand news headlines in 3 bullet points for a trademark lawyer.
Focus on IP-relevant insights.

Headlines:
{headlines}

Return 3 bullet points starting with -"""

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=250,
            messages=[{"role": "user", "content": prompt}]
        )
        return jsonify({
            "success": True,
            "summary": response.content[0].text.strip(),
            "fetched_at": datetime.now().isoformat(),
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"Starting Novaastra Agent v3 on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
