import json
import os
import urllib.request
from typing import Any

from .base import nanoclaw_tool


@nanoclaw_tool
def web_search(query: str, max_results: int = 5) -> str:
    """
    Search the web for current information.

    Use this tool when the user asks for latest or current information, news,
    prices, versions, regulations, public facts, or anything likely to change
    over time.

    Args:
        query: Search query.
        max_results: Number of search results to return, between 1 and 10.
    """
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        return "Web search is not configured: missing TAVILY_API_KEY."

    query = query.strip()
    if not query:
        return "Search query cannot be empty."

    try:
        result_limit = int(max_results)
    except (TypeError, ValueError):
        result_limit = 5
    result_limit = max(1, min(result_limit, 10))

    payload = {
        "api_key": api_key,
        "query": query,
        "max_results": result_limit,
        "include_answer": False,
        "include_raw_content": False,
    }
    request = urllib.request.Request(
        "https://api.tavily.com/search",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            data: dict[str, Any] = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return f"Web search failed: {exc}"

    results = data.get("results", [])
    if not results:
        return "No search results found."

    formatted_results = []
    for index, item in enumerate(results[:result_limit], start=1):
        title = item.get("title") or "Untitled"
        url = item.get("url") or ""
        content = item.get("content") or ""
        if len(content) > 500:
            content = content[:500] + "..."
        formatted_results.append(
            f"{index}. {title}\n"
            f"URL: {url}\n"
            f"Summary: {content}"
        )

    return "\n\n".join(formatted_results)
