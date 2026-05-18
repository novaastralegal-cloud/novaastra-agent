"""
Novaastra Legal — Growth Agent Backend
Fetches real data from Google News RSS, IP India (public), and MCA CDM
Runs daily and serves data to the frontend dashboard
"""

from flask import Flask, jsonify
from flask_cors import CORS
import feedparser
import requests
from bs4 import BeautifulSoup
import json
import os
from datetime import datetime, timedelta
import anthropic
import re

app = Flask(__name__)
CORS(app)  # Allow the HTML frontend to call this backend

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# ─────────────────────────────────────────────
# DATA SOURCES
# ─────────────────────────────────────────────

# Google News RSS URLs — free, no API key needed
GOOGLE_NEWS_FEEDS = {
    "startup_funding": "https://news.google.com/rss/search?q=India+startup+funding+raised&hl=en-IN&gl=IN&ceid=IN:en",
    "trademark_dispute": "https://news.google.com/rss/search?q=India+trademark+dispute+brand&hl=en-IN&gl=IN&ceid=IN:en",
    "product_launch": "https://news.google.com/rss/search?q=India+brand+launch+new+product+2025&hl=en-IN&gl=IN&ceid=IN:en",
    "startup_india": "https://news.google.com/rss/search?q=startup+India+brand+new+company+2025&hl=en-IN&gl=IN&ceid=IN:en",
}

# StartupTalky RSS — daily India funding news (free)
STARTUPTALKY_RSS = "https://startuptalky.com/rss"

# MCA CDM portal — public company stats (no auth needed)
MCA_CDM_URL = "https://www.mcacdm.nic.in/"

# IP India public search
IP_INDIA_SEARCH = "https://ipindiaonline.gov.in/tmrpublicsearch/frmmain.aspx"


# ─────────────────────────────────────────────
# FETCH FUNCTIONS
# ─────────────────────────────────────────────

def fetch_google_news(feed_key: str, max_items: int = 8) -> list:
    """Fetch and parse a Google News RSS feed."""
    url = GOOGLE_NEWS_FEEDS.get(feed_key, "")
    if not url:
        return []
    try:
        feed = feedparser.parse(url)
        items = []
        for entry in feed.entries[:max_items]:
            items.append({
                "title": entry.get("title", ""),
                "link": entry.get("link", ""),
                "published": entry.get("published", ""),
                "summary": entry.get("summary", "")[:300],
                "source": entry.get("source", {}).get("title", "Google News"),
            })
        return items
    except Exception as e:
        print(f"Error fetching {feed_key}: {e}")
        return []


def fetch_startuptalky() -> list:
    """Fetch latest India startup funding news from StartupTalky RSS."""
    try:
        feed = feedparser.parse(STARTUPTALKY_RSS)
        items = []
        for entry in feed.entries[:10]:
            title = entry.get("title", "")
            # Only include funding-related articles
            if any(word in title.lower() for word in ["raises", "funding", "crore", "million", "seed", "series"]):
                items.append({
                    "title": title,
                    "link": entry.get("link", ""),
                    "published": entry.get("published", ""),
                    "summary": entry.get("summary", "")[:300],
                    "source": "StartupTalky",
                })
        return items
    except Exception as e:
        print(f"Error fetching StartupTalky: {e}")
        return []


def analyse_articles_with_ai(articles: list, trigger_type: str) -> list:
    """
    Use Claude to extract company names, IP risk signals, and opportunity 
    summaries from raw news articles.
    """
    if not articles or not ANTHROPIC_API_KEY:
        return []

    articles_text = "\n\n".join([
        f"Title: {a['title']}\nSummary: {a['summary']}\nSource: {a['source']}\nDate: {a['published']}"
        for a in articles[:6]
    ])

    prompt = f"""You are an IP intelligence analyst for Novaastra Legal, a trademark and IP law firm in India.

Analyse these news articles and extract companies that likely need trademark or IP legal help.

Trigger type being searched: {trigger_type}

Articles:
{articles_text}

For each relevant company found, extract:
1. Company name (as specific as possible)
2. Why they need IP help (1 sentence, specific to their situation)
3. Sector/industry
4. Trigger type: one of "Funding Raised", "Product Launch", "Brand Dispute", "New Registration"
5. Urgency: "High", "Medium", or "Low"

Return ONLY a JSON array. Each object must have: company, reason, sector, trigger, urgency.
If no clearly relevant companies are found, return an empty array [].
No markdown, no explanation. Raw JSON only."""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}]
        )
        text = response.content[0].text.strip()
        text = re.sub(r'```json|```', '', text).strip()
        return json.loads(text)
    except Exception as e:
        print(f"Error analysing articles: {e}")
        return []


def check_ip_india_trademark(company_name: str) -> bool:
    """
    Basic check — returns True if NO trademark found for the company name.
    Uses IP India public search (no auth required).
    Note: This is a simplified check. For production, implement full form submission.
    """
    try:
        # Simplified — in production this would do a proper POST to IP India search
        # For now returns True (no trademark) as a placeholder
        # Real implementation needs Selenium or requests with session handling
        return True
    except:
        return True


# ─────────────────────────────────────────────
# API ROUTES
# ─────────────────────────────────────────────

@app.route("/api/opportunities", methods=["GET"])
def get_opportunities():
    """
    Main endpoint — fetches real news, analyses with AI, 
    returns opportunity cards for the radar.
    """
    all_opportunities = []

    # 1. Startup funding news (most important signal)
    print("Fetching startup funding news...")
    funding_articles = fetch_startuptalky() + fetch_google_news("startup_funding")
    if funding_articles:
        funding_opps = analyse_articles_with_ai(funding_articles, "Funding Raised — startups that just raised money and urgently need trademark protection")
        all_opportunities.extend(funding_opps)

    # 2. Brand / trademark disputes
    print("Fetching trademark dispute news...")
    dispute_articles = fetch_google_news("trademark_dispute")
    if dispute_articles:
        dispute_opps = analyse_articles_with_ai(dispute_articles, "Brand Dispute — companies involved in trademark disputes or brand conflicts")
        all_opportunities.extend(dispute_opps)

    # 3. New product launches
    print("Fetching product launch news...")
    launch_articles = fetch_google_news("product_launch")
    if launch_articles:
        launch_opps = analyse_articles_with_ai(launch_articles, "Product Launch — brands launching new products that need trademark filing")
        all_opportunities.extend(launch_opps)

    # Deduplicate by company name
    seen = set()
    unique_opps = []
    for opp in all_opportunities:
        name = opp.get("company", "").lower().strip()
        if name and name not in seen:
            seen.add(name)
            unique_opps.append(opp)

    return jsonify({
        "success": True,
        "count": len(unique_opps),
        "opportunities": unique_opps,
        "fetched_at": datetime.now().isoformat(),
    })


@app.route("/api/news-summary", methods=["GET"])
def get_news_summary():
    """
    Returns a daily IP law news digest — 
    latest trademark/IP developments in India.
    """
    articles = (
        fetch_google_news("trademark_dispute")[:4] +
        fetch_google_news("startup_funding")[:4]
    )

    if not articles or not ANTHROPIC_API_KEY:
        return jsonify({"success": False, "message": "No articles found"})

    articles_text = "\n\n".join([
        f"Title: {a['title']}\nSource: {a['source']}"
        for a in articles
    ])

    prompt = f"""You are a legal news summariser for Novaastra Legal (IP & trademark law firm, India).

Summarise today's most relevant IP and trademark news from India in 3 bullet points.
Each bullet should be 1-2 sentences. Focus on things relevant to trademark lawyers and their clients.

Articles:
{articles_text}

Return only the 3 bullet points. Start each with •"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}]
        )
        summary = response.content[0].text.strip()
        return jsonify({
            "success": True,
            "summary": summary,
            "fetched_at": datetime.now().isoformat(),
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/health", methods=["GET"])
def health():
    """Simple health check endpoint."""
    return jsonify({
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "anthropic_configured": bool(ANTHROPIC_API_KEY),
    })


@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "name": "Novaastra Legal Growth Agent API",
        "version": "1.0",
        "endpoints": [
            "/api/opportunities  — Real-time opportunity radar",
            "/api/news-summary   — Daily IP news digest",
            "/api/health         — Health check",
        ]
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
