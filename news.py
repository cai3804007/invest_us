import requests
from config import SERPAPI_API_KEYS, TAVILY_API_KEYS

SEARCH_QUERIES = [
    "US stock market today NASDAQ S&P 500",
    "Federal Reserve interest rate policy",
    "semiconductor stocks AI market outlook",
]


class NewsFetcher:

    def __init__(self):
        self.articles = []

    def fetch(self, console=None):
        if SERPAPI_API_KEYS:
            self._fetch_serpapi(console)
        if TAVILY_API_KEYS and len(self.articles) < 5:
            self._fetch_tavily(console)
        if not self.articles and console:
            console.print("  [dim]未配置 SERPAPI/TAVILY Key，跳过实时新闻[/]")
        return self.articles

    # ------------------------------------------------------------------
    # SerpAPI - Google News
    # ------------------------------------------------------------------

    def _fetch_serpapi(self, console=None):
        if console:
            console.print("  [dim]SerpAPI: 获取实时新闻...[/]")

        key = SERPAPI_API_KEYS.split(",")[0].strip()
        for query in SEARCH_QUERIES:
            try:
                resp = requests.get("https://serpapi.com/search.json", params={
                    "q": query,
                    "tbm": "nws",
                    "num": 3,
                    "hl": "en",
                    "gl": "us",
                    "api_key": key,
                }, timeout=15)
                data = resp.json()
                for item in data.get("news_results", [])[:3]:
                    self.articles.append({
                        "title": item.get("title", ""),
                        "source": item.get("source", ""),
                        "snippet": item.get("snippet", ""),
                        "date": item.get("date", ""),
                        "link": item.get("link", ""),
                        "from": "SerpAPI",
                    })
            except Exception as e:
                if console:
                    console.print(f"  [dim]SerpAPI query failed: {e}[/]")

    # ------------------------------------------------------------------
    # Tavily Search
    # ------------------------------------------------------------------

    def _fetch_tavily(self, console=None):
        if console:
            console.print("  [dim]Tavily: 获取实时新闻...[/]")

        key = TAVILY_API_KEYS.split(",")[0].strip()
        combined_query = "US stock market NASDAQ S&P 500 Federal Reserve today"
        try:
            resp = requests.post("https://api.tavily.com/search", json={
                "api_key": key,
                "query": combined_query,
                "search_depth": "basic",
                "include_answer": True,
                "max_results": 8,
                "topic": "finance",
            }, timeout=15)
            data = resp.json()

            for item in data.get("results", [])[:8]:
                self.articles.append({
                    "title": item.get("title", ""),
                    "source": item.get("url", "").split("/")[2] if item.get("url") else "",
                    "snippet": item.get("content", "")[:200],
                    "date": "",
                    "link": item.get("url", ""),
                    "from": "Tavily",
                })

            tavily_answer = data.get("answer", "")
            if tavily_answer:
                self.articles.insert(0, {
                    "title": "Tavily AI Summary",
                    "source": "Tavily",
                    "snippet": tavily_answer[:500],
                    "date": "",
                    "link": "",
                    "from": "Tavily",
                })
        except Exception as e:
            if console:
                console.print(f"  [dim]Tavily failed: {e}[/]")

    def get_headlines_text(self, max_items=10):
        lines = []
        for a in self.articles[:max_items]:
            lines.append(f"- [{a['source']}] {a['title']}")
            if a["snippet"]:
                lines.append(f"  {a['snippet'][:150]}")
        return "\n".join(lines)
