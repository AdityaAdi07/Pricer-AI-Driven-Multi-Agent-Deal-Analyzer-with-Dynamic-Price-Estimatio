from pydantic import BaseModel
from typing import List, Dict, Self
from bs4 import BeautifulSoup
import re
import feedparser
from tqdm import tqdm
import requests
import time
import logging

# -----------------------------------------------------------
# INDIA RSS DEAL FEEDS
# -----------------------------------------------------------
feeds = [
    "https://www.desidime.com/deals.rss",
    "https://www.desidime.com/stores/amazon-india.rss",
    "https://www.desidime.com/stores/flipkart.rss",
    "https://www.desidime.com/stores/reliance-digital.rss",
    "https://www.desidime.com/stores/tata-cliq.rss",
    "https://www.desidime.com/stores/croma.rss",
    "https://www.desidime.com/stores/ajio.rss",
    "https://www.desidime.com/stores/myntra.rss",
    "https://www.desidime.com/stores/nykaa.rss",

    "https://www.reddit.com/r/indiandeals/.rss",
    "https://www.reddit.com/r/IndianGaming/.rss",
    "https://www.reddit.com/r/buildapcsalesindia/.rss",
]

logger = logging.getLogger("ScrapedDeal")
logger.setLevel(logging.INFO)


# -----------------------------------------------------------
# CLEAN HTML SNIPPET FROM RSS
# -----------------------------------------------------------
def extract(html_snippet: str) -> str:
    soup = BeautifulSoup(html_snippet, 'html.parser')
    snippet_div = soup.find('div', class_='snippet summary')

    if snippet_div:
        description = snippet_div.get_text(strip=True)
        description = BeautifulSoup(description, 'html.parser').get_text()
        description = re.sub('<[^<]+?>', '', description)
        result = description.strip()
    else:
        result = html_snippet

    return result.replace('\n', ' ')


# -----------------------------------------------------------
# EXTRACT INDIAN PRICES FROM TEXT (₹, Rs, INR)
# -----------------------------------------------------------
def extract_indian_price(text: str):
    patterns = [
        r"₹\s*([\d,]+)",
        r"Rs\.?\s*([\d,]+)",
        r"INR\s*([\d,]+)"
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            return float(m.group(1).replace(",", ""))
    return None


# -----------------------------------------------------------
# SCRAPED DEAL CLASS (INDIA-READY)
# -----------------------------------------------------------
class ScrapedDeal:
    category: str
    title: str
    summary: str
    url: str
    details: str
    features: str
    raw_price: float | None

    def __init__(self, entry: Dict[str, str]):
        # Basic entry info
        self.title = entry.get("title", "").strip()
        self.summary = extract(entry.get("summary", "") or entry.get("description", ""))

        if "links" in entry:
            self.url = entry["links"][0].get("href", "")
        else:
            self.url = entry.get("link", "")

        self.details = ""
        self.features = ""
        self.raw_price = None

        # -------- Fetch source page safely --------
        try:
            headers = {
                "User-Agent":
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120 Safari/537.36"
            }
            r = requests.get(self.url, headers=headers, timeout=10)
            soup = BeautifulSoup(r.content, "html.parser")

            # Try multiple content selectors (covers 95% of Indian sites)
            candidates = [
                soup.find("div", {"class": "deal-desc"}),        # DesiDime
                soup.find("div", {"class": "content-section"}),  # DealNews style
                soup.find("div", {"class": "description"}),
                soup.find("div", {"id": "content"}),
                soup.find("article"),
                soup.find("div", {"class": "post-content"}),
                soup.find("div", {"class": "entry-content"}),
            ]

            node = next((x for x in candidates if x), None)

            if node:
                content = node.get_text(" ", strip=True)
            else:
                # fallback meta
                meta = soup.find("meta", {"name": "description"}) or \
                       soup.find("meta", {"property": "og:description"})

                if meta:
                    content = meta.get("content", "")
                else:
                    content = self.summary

            # Clean text
            content = re.sub(r"\s+", " ", content).strip()

            # Extract features if present
            if "Features" in content:
                parts = re.split(r"\bFeatures\b", content, maxsplit=1)
                self.details = parts[0].strip()
                self.features = parts[1].strip()
            else:
                self.details = content
                self.features = ""

            # -------- Extract Indian price --------
            self.raw_price = (
                extract_indian_price(self.details)
                or extract_indian_price(self.summary)
                or None
            )

        except Exception as e:
            logger.warning(f"Failed to scrape {self.url}: {e}")
            self.details = self.summary
            self.features = ""
            self.raw_price = extract_indian_price(self.summary)

    def __repr__(self):
        return f"<{self.title}>"

    def describe(self):
        return (
            f"Title: {self.title}\n"
            f"Raw Price: {self.raw_price}\n"
            f"Details: {self.details}\n"
            f"Features: {self.features}\n"
            f"URL: {self.url}"
        )


    # -----------------------------------------------------------
    # FETCH ALL DEALS
    # -----------------------------------------------------------
    @classmethod
    def fetch(cls, show_progress: bool = False) -> List[Self]:
        deals = []
        feed_iter = tqdm(feeds) if show_progress else feeds

        for feed_url in feed_iter:
            try:
                feed = feedparser.parse(feed_url)
            except Exception as e:
                logger.warning(f"Failed to parse feed {feed_url}: {e}")
                continue

            for entry in feed.entries[:10]:
                try:
                    deals.append(cls(entry))
                except Exception as e:
                    logger.warning(f"Bad entry skipped: {e}")

                time.sleep(0.4)  # be polite to servers

        return deals


# -----------------------------------------------------------
# DATA MODELS
# -----------------------------------------------------------
class Deal(BaseModel):
    product_description: str
    price: float
    url: str


class DealSelection(BaseModel):
    deals: List[Deal]


class Opportunity(BaseModel):
    deal: Deal
    estimate: float
    discount: float
