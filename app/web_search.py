"""Tavily web search for the "web" and "hybrid" intents (weather, official announcements, traffic)."""
import httpx

TAVILY_URL = "https://api.tavily.com/search"
# Video/social posts make weak, unverifiable sources for an operations answer
SOCIAL = ["facebook.com", "instagram.com", "tiktok.com", "youtube.com", "x.com", "twitter.com"]


class Tavily:
    def __init__(self, api_key, timeout=12.0):
        self.api_key = api_key
        self.timeout = timeout

    @property
    def enabled(self):
        return bool(self.api_key)

    def search(self, query, max_results=4):
        r = httpx.post(
            TAVILY_URL,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"query": query, "max_results": max_results, "search_depth": "basic",
                  "include_answer": True, "topic": "general",
                  "exclude_domains": SOCIAL},
            timeout=self.timeout)
        r.raise_for_status()
        data = r.json()
        return {
            "answer": data.get("answer") or "",
            "results": [{"title": x.get("title", ""), "url": x.get("url", ""),
                         "content": (x.get("content") or "")[:600]}
                        for x in data.get("results", [])],
        }
