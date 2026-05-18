"""
Novaastra Legal — Growth Agent Backend v4
Fixed 405 error on /api/generate
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
import feedparser
import json
import os
from datetime import datetime
import anthropic
import re

app = Flask(__name__)
CORS(app, origins="*", methods=["GET", "POST", "OPTIONS"], allow_headers=["Content-Type"])

@app.after_request
def add_cors(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response

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
            if title:
                items.append({
                    "title": title,
                    "summary": entry.get("summary", "").strip()[:300],
                    "source": entry.get("source", {}).get("title", "News"),
                })
        return items
    except Exception as e:
        print(f"Feed error: {e}")
        return []


def extract_opportunities(articles):
    if not articles or not ANTHROPIC_API_KEY:
        return []

    text = "\n".join([f"- {a['title']}" for a in articles[:12]])

    prompt = f"""You are an IP analyst for a trademark law firm in India (Novaastra Legal).

Below are today's Indian business news headlines. Extract ANY company or brand that could benefit from trademark or IP legal services.

Be GENEROUS — include companies that:
- Just raised funding (they need trademark protection before scaling)
- Launched a new product or brand
- Are expanding to new markets
- Are new startups or D2C brands
- Had any brand/name related news

Headlines:
{text}

Return a JSON array. Each item must have:
- company (string)
- reason (string: one sentence why they need IP help)
- sector (string)
- trigger (string: one of "Funding Raised", "Product Launch", "Brand Dispute", "New Registration", "Market Expansion")
- urgency (string: "High", "Medium", or "Low")

Include at least 3-5 companies if possible. Raw JSON array only. No markdown."""

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}]
        )
        text_out = re.sub(r'```json|```', '', response.content[0].text.strip()).strip()
        result = json.loads(text_out)
        return result if isinstance(result, list) else []
    except Exception as e:
        print(f"AI error: {e}")
        return []


# ─── ROUTES ───────────────────────────────────

@app.route("/", methods=["GET"])
def index():
    return jsonify({"name": "Novaastra Legal Growth Agent API", "status": "running", "version": "4.0"})


@app.route("/api/health", methods=["GET", "OPTIONS"])
def health():
    if request.method == "OPTIONS":
        return '', 204
    return jsonify({
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "anthropic_configured": bool(ANTHROPIC_API_KEY),
        "version": "4.0"
    })


@app.route("/api/generate", methods=["GET", "POST", "OPTIONS"])
def generate_content():
    """AI content generation — used by all dashboard tabs."""
    if request.method == "OPTIONS":
        return '', 204

    if request.method == "GET":
        return jsonify({"status": "ok", "endpoint": "generate", "method": "POST required"})

    data = request.get_json(silent=True) or {}
    prompt = data.get("prompt", "")
    max_tokens = int(data.get("max_tokens", 800))

    if not prompt:
        return jsonify({"success": False, "error": "No prompt provided"}), 400

    if not ANTHROPIC_API_KEY:
        return jsonify({"success": False, "error": "API key not configured"}), 500

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}]
        )
        text = response.content[0].text.strip()
        return jsonify({
            "success": True,
            "text": text,
            "generated_at": datetime.now().isoformat(),
        })
    except Exception as e:
        print(f"Generate error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/opportunities", methods=["GET", "OPTIONS"])
def get_opportunities():
    if request.method == "OPTIONS":
        return '', 204

    all_articles = []
    for key, url in FEEDS.items():
        articles = fetch_feed(url, 8)
        all_articles.extend(articles)
        print(f"Feed {key}: {len(articles)} articles")

    st_articles = fetch_feed(STARTUPTALKY, 10)
    all_articles.extend(st_articles)
    print(f"Total articles: {len(all_articles)}")

    # Deduplicate
    seen_titles = set()
    unique_articles = []
    for a in all_articles:
        t = a['title'].lower()[:60]
        if t not in seen_titles:
            seen_titles.add(t)
            unique_articles.append(a)

    opps = extract_opportunities(unique_articles) if unique_articles else []

    # Deduplicate companies
    seen_companies = set()
    unique_opps = []
    for opp in opps:
        name = opp.get("company", "").lower().strip()
        if name and name not in seen_companies and len(name) > 2:
            seen_companies.add(name)
            unique_opps.append(opp)

    if not unique_opps:
        unique_opps = [{
            "company": "No results today",
            "reason": "RSS feeds returned no relevant articles today. Try again tomorrow morning.",
            "sector": "System",
            "trigger": "New Registration",
            "urgency": "Low"
        }]

    return jsonify({
        "success": True,
        "count": len(unique_opps),
        "opportunities": unique_opps,
        "articles_scanned": len(unique_articles),
        "fetched_at": datetime.now().isoformat(),
    })


@app.route("/api/news-summary", methods=["GET", "OPTIONS"])
def news_summary():
    if request.method == "OPTIONS":
        return '', 204

    articles = fetch_feed(FEEDS["brand"], 5)
    if not articles or not ANTHROPIC_API_KEY:
        return jsonify({"success": False, "summary": "No data today."})

    headlines = "\n".join([f"- {a['title']}" for a in articles])
    prompt = f"""Summarise these India business/brand news headlines in 3 bullet points for a trademark lawyer.
Headlines:\n{headlines}\nReturn 3 bullet points starting with -"""

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
    port = int(os.environ.get("PORT", 8080))
    print(f"Starting Novaastra Agent v4 on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
