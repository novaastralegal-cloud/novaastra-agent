"""
Novaastra Legal — Growth Agent Backend
Fixed version — robust error handling, simplified dependencies
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

# CORS — allow all origins
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

# ─── CONFIG ───────────────────────────────────
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

GOOGLE_NEWS_FEEDS = {
    "startup_funding": "https://news.google.com/rss/search?q=India+startup+funding+raised&hl=en-IN&gl=IN&ceid=IN:en",
    "trademark_dispute": "https://news.google.com/rss/search?q=India+trademark+brand+dispute&hl=en-IN&gl=IN&ceid=IN:en",
    "product_launch": "https://news.google.com/rss/search?q=India+new+brand+product+launch&hl=en-IN&gl=IN&ceid=IN:en",
}

STARTUPTALKY_RSS = "https://startuptalky.com/rss"

# ─── FETCH FUNCTIONS ──────────────────────────

def fetch_feed(url, max_items=8):
    """Safely fetch any RSS feed."""
    try:
        feed = feedparser.parse(url)
        items = []
        for entry in feed.entries[:max_items]:
            items.append({
                "title": entry.get("title", ""),
                "summary": entry.get("summary", "")[:250],
                "source": entry.get("source", {}).get("title", "News"),
                "published": entry.get("published", ""),
            })
        return items
    except Exception as e:
        print(f"Feed fetch error: {e}")
        return []


def analyse_with_ai(articles, trigger_type):
    """Use Claude to extract IP opportunities from articles."""
    if not articles or not ANTHROPIC_API_KEY:
        return []

    articles_text = "\n\n".join([
        f"Title: {a['title']}\nSummary: {a['summary']}"
        for a in articles[:5]
    ])

    prompt = f"""You are an IP analyst for a trademark law firm in India.

Read these news articles and find companies that likely need trademark or IP legal help.
Trigger: {trigger_type}

Articles:
{articles_text}

Return ONLY a JSON array. Each item must have these exact keys:
- company (string: company name)
- reason (string: one sentence why they need IP help)
- sector (string: industry)
- trigger (string: one of "Funding Raised", "Product Launch", "Brand Dispute", "New Registration")
- urgency (string: "High", "Medium", or "Low")

Return [] if nothing relevant found. No markdown, no explanation. Raw JSON array only."""

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}]
        )
        text = response.content[0].text.strip()
        text = re.sub(r'```json|```', '', text).strip()
        result = json.loads(text)
        return result if isinstance(result, list) else []
    except Exception as e:
        print(f"AI analysis error: {e}")
        return []


# ─── ROUTES ───────────────────────────────────

@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "name": "Novaastra Legal Growth Agent API",
        "status": "running",
        "version": "2.0",
        "endpoints": ["/api/health", "/api/opportunities", "/api/news-summary"]
    })


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "anthropic_configured": bool(ANTHROPIC_API_KEY),
        "version": "2.0"
    })


@app.route("/api/opportunities", methods=["GET"])
def get_opportunities():
    """Fetch real news and extract IP opportunities."""
    all_opps = []

    # Funding news
    funding = fetch_feed(STARTUPTALKY_RSS) + fetch_feed(GOOGLE_NEWS_FEEDS["startup_funding"])
    if funding:
        opps = analyse_with_ai(
            funding,
            "Startups that just raised funding and urgently need trademark protection"
        )
        all_opps.extend(opps)

    # Disputes
    disputes = fetch_feed(GOOGLE_NEWS_FEEDS["trademark_dispute"])
    if disputes:
        opps = analyse_with_ai(
            disputes,
            "Companies in brand or trademark disputes needing legal help"
        )
        all_opps.extend(opps)

    # Launches
    launches = fetch_feed(GOOGLE_NEWS_FEEDS["product_launch"])
    if launches:
        opps = analyse_with_ai(
            launches,
            "Brands launching new products that need trademark filing"
        )
        all_opps.extend(opps)

    # Deduplicate
    seen = set()
    unique = []
    for opp in all_opps:
        name = opp.get("company", "").lower().strip()
        if name and name not in seen and len(name) > 2:
            seen.add(name)
            unique.append(opp)

    return jsonify({
        "success": True,
        "count": len(unique),
        "opportunities": unique,
        "fetched_at": datetime.now().isoformat(),
    })


@app.route("/api/news-summary", methods=["GET"])
def news_summary():
    """Daily IP news digest."""
    articles = fetch_feed(GOOGLE_NEWS_FEEDS["trademark_dispute"], 4)

    if not articles or not ANTHROPIC_API_KEY:
        return jsonify({"success": False, "summary": "No data available."})

    articles_text = "\n".join([f"- {a['title']}" for a in articles])

    prompt = f"""Summarise today's India IP and trademark news in 3 bullet points for a trademark lawyer.
Each bullet: 1-2 sentences. Focus on what's relevant for brand owners.

Headlines:
{articles_text}

Return only 3 bullet points starting with -"""

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
    print(f"Starting Novaastra Agent on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
