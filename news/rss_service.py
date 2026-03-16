import requests
import xml.etree.ElementTree as ET
from datetime import datetime
from django.utils import timezone
from email.utils import parsedate_to_datetime

class GoogleNewsRSS:
    """
    Fetch news from Yahoo Finance RSS feed.
    (Kept class name for compatibility, but logic is Yahoo)
    """
    # Yahoo Finance RSS
    # General: https://finance.yahoo.com/news/rssindex
    # Ticker: https://feeds.finance.yahoo.com/rss/2.0/headline?s=AAPL
    
    def fetch_news(self, query: str = None, symbol: str = None, **kwargs) -> list:
        """
        Fetch news articles from Yahoo Finance RSS.
        If symbol is provided, use ticker feed.
        If query is provided, we can't easily search Yahoo RSS, so we fallback to general feed or ignore query.
        Actually, for 'stock market' query, general feed is good.
        """
        if symbol:
            url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}"
        else:
            url = "https://finance.yahoo.com/news/rssindex"
            
        try:
            # User-Agent is often required for Yahoo
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            
            root = ET.fromstring(response.content)
            articles = []
            
            # Yahoo RSS structure: channel -> item
            for item in root.findall(".//item"):
                title = item.find("title").text if item.find("title") is not None else "No Title"
                link = item.find("link").text if item.find("link") is not None else ""
                pub_date_str = item.find("pubDate").text if item.find("pubDate") is not None else ""
                description = item.find("description").text if item.find("description") is not None else ""
                
                # Yahoo RSS doesn't always have source, but sometimes in 'guid' or 'link'
                source = "Yahoo Finance" 
                
                # Parse Date
                try:
                    # Yahoo format: "Mon, 02 Dec 2025 01:23:45 GMT"
                    pub_date = parsedate_to_datetime(pub_date_str)
                    if pub_date.tzinfo is None:
                        pub_date = timezone.make_aware(pub_date)
                except Exception:
                    pub_date = timezone.now()

                articles.append({
                    "title": title,
                    "url": link,
                    "published_at": pub_date,
                    "source": source,
                    "description": description
                })
                
            return articles

        except Exception as e:
            print(f"[YahooFinanceRSS] Error fetching news: {e}")
            return []
