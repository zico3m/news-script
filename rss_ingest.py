import os
import re
import joblib
import feedparser
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone
from supabase import create_client

# =============================
# CONFI
# =============================

SUPABASE_URL = os.getenv(
    "SUPABASE_URL",
    "https://nophyetcritlguostfsh.supabase.co"
)
SUPABASE_KEY = os.getenv(
    "SUPABASE_KEY",
    "sb_publishable_eSz6tnpyIjCOPk9Z_OoCtw_vZieZWm9"
)

MODEL_PATH = "news_model.pkl"
VECTORIZER_PATH = "vectorizer.pkl"

RSS_SOURCES = {

    "BBC Arabic": "https://feeds.bbci.co.uk/arabic/rss.xml",
    "France24 Arabic": "https://www.france24.com/ar/rss",
    "Alsharq (Qatar)": "https://al-sharq.com/rss/latestNews",
    "RT Arabic": "https://arabic.rt.com/rss/",
    "Al-Masry Al-Youm": "https://almasryalyoum.com/rss/rssfeed",
    "Al Jadeed TV": "https://www.aljadeed.tv/rss",
    "Masrawy": "https://www.masrawy.com/rss",
    "SarayNews": "https://www.sarayanews.com/rss.php",
}

# التصنيفات المعتمدة (كما في قاعدة البيانات)
ALLOWED_CATEGORIES = {
    "politics": 1,
    "sports": 2,
    "technology": 3,
    "health": 4,
    "economy": 5,
    "culture": 6,
}

# Mapping مسموح
CATEGORY_MAPPING = {
    "tech": "technology",
    "technology": "technology",

    "finance": "economy",
    "economics": "economy",
    "economy": "economy",

    "politics": "politics",
    "sports": "sports",
    "health": "health",
    "culture": "culture",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (NabaAI Bot)"
}

# =============================
# INIT
# =============================

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
model = joblib.load(MODEL_PATH)
vectorizer = joblib.load(VECTORIZER_PATH)

# =============================
# HELPERS
# =============================

def now_utc():
    return datetime.now(timezone.utc).isoformat()

def clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    return text.strip()

def classify(text: str) -> str:
    vec = vectorizer.transform([text])
    return model.predict(vec)[0].lower().strip()

def already_exists(title: str) -> bool:
    res = supabase.table("news") \
        .select("id") \
        .eq("title", title) \
        .limit(1) \
        .execute()
    return bool(res.data)

def get_or_create_source(name: str) -> int:
    res = supabase.table("sources") \
        .select("id") \
        .eq("name", name) \
        .limit(1) \
        .execute()

    if res.data:
        return res.data[0]["id"]

    ins = supabase.table("sources").insert({
        "name": name,
        "source_type_id": 1
    }).execute()

    return ins.data[0]["id"]

# =============================
# FULL ARTICLE SCRAPER
# =============================

def fetch_full_article(url: str):
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        paragraphs = soup.find_all("p")
        content = " ".join(p.get_text() for p in paragraphs)
        content = clean_text(content)

        img = soup.find("meta", property="og:image")
        image_url = img["content"] if img else None

        return content, image_url

    except Exception as e:
        print("⚠️ Article fetch failed:", e)
        return None, None

# =============================
# MAIN
# =============================

def main():
    added = 0

    for source_name, rss_url in RSS_SOURCES.items():
        print(f"\n📡 Fetching from {source_name}")
        feed = feedparser.parse(rss_url)
        source_id = get_or_create_source(source_name)

        for item in feed.entries[:15]:
            title = item.get("title")
            link = item.get("link")

            if not title or not link:
                continue

            if already_exists(title):
                continue

            content, image_url = fetch_full_article(link)
            if not content or len(content) < 300:
                continue

            predicted_raw = classify(content)
            mapped_category = CATEGORY_MAPPING.get(predicted_raw)

            # الافتراضي: قيد المراجعة
            status = "pending"
            category_id = None

            # إذا التصنيف معروف → نشر مباشر
            if mapped_category and mapped_category in ALLOWED_CATEGORIES:
                category_id = ALLOWED_CATEGORIES[mapped_category]
                status = "published"

            supabase.table("news").insert({
                "title": title,
                "content": content,
                "primary_image": image_url,
                "category_id": category_id,   # قد تكون NULL
                "source_id": source_id,
                "status": status,             # published أو pending
                "is_external": True,
                "published_at": now_utc(),
            }).execute()

            added += 1
            print(f"✅ Added ({status}): {title}")

    print(f"\n🎉 DONE. Total added: {added}")

# =============================
# RUN
# =============================

if __name__ == "__main__":
    main()