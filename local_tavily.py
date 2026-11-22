import asyncio
import json
import re
from urllib.parse import parse_qs, urlparse
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
from crawl4ai.content_filter_strategy import PruningContentFilter
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator
from ddgs import DDGS
from youtube_transcript_api import YouTubeTranscriptApi

GEAR_KEYWORDS = {
    "amp", "amplifier", "pedal", "pedalboard", "overdrive", "distortion",
    "fuzz", "delay", "reverb", "compressor", "guitar", "pickup", "humbucker",
    "single-coil", "tube", "cabinet", "speaker", "gain", "tone", "signal",
    "marshall", "mesa", "fender", "vox", "rectifier", "plexi", "jcm",
    "settings", "bass", "mids", "treble", "recording", "studio", "producer",
    "tuning", "drop", "rig", "rundown", "equipboard", "chug", "lead"
}


def extract_youtube_id(url: str) -> str | None:
    parsed = urlparse(url)
    if "youtube.com" in parsed.netloc:
        return parse_qs(parsed.query).get("v", [None])[0]
    if "youtu.be" in parsed.netloc:
        return parsed.path.lstrip("/") or None
    return None


def get_yt_transcript(video_id: str) -> str:
    try:
        ytt = YouTubeTranscriptApi()
        transcript = ytt.fetch(video_id, languages=["en", "en-US", "en-GB"])
        return " ".join(chunk.text for chunk in transcript)
    except Exception:
        return ""


def score_and_chunk(text: str, chunk_size: int = 350, top_k: int = 4) -> list[dict]:
    """Splits text into overlapping chunks and ranks by gear keyword density."""
    words = text.split()
    if not words:
        return []

    chunks = [
        " ".join(words[i : i + chunk_size])
        for i in range(0, len(words), chunk_size - 50)
    ]

    scored = []
    for chunk in chunks:
        lower_words = set(re.findall(r"\b\w+\b", chunk.lower()))
        score = len(lower_words.intersection(GEAR_KEYWORDS))
        if score > 0:
            scored.append({"score": score, "text": chunk})

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]


async def search_and_extract(song: str, artist: str, max_per_query: int = 3) -> dict:
    queries = {
        "studio_articles": f'"{artist}" "{song}" ("guitar tone" OR "amp" OR "recording" OR "gear") -site:youtube.com',
        "gear_databases": f'(site:equipboard.com OR site:premierguitar.com OR site:guitarworld.com) "{artist}" "{song}"',
        "forums": f'(site:reddit.com OR site:thegearpage.net) "{artist}" "{song}" ("amp settings" OR "tone" OR "gear")',
        "youtube": f'site:youtube.com "{artist}" "{song}" ("guitar tone" OR "rig" OR "settings")',
    }

    seen_urls = set()
    discovered = []

    with DDGS() as ddgs:
        for category, q in queries.items():
            print(f"[Search:{category}] {q}")
            try:
                results = list(ddgs.text(q, max_results=max_per_query))
                for r in results:
                    url = r.get("href", "")
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        discovered.append({
                            "category": category,
                            "title": r.get("title", ""),
                            "url": url,
                            "snippet": r.get("body", ""),
                        })
            except Exception as e:
                print(f"[Search Warning:{category}] {e}")
            await asyncio.sleep(1.5)

    browser_cfg = BrowserConfig(headless=True, verbose=False)
    md_generator = DefaultMarkdownGenerator(
        content_filter=PruningContentFilter(threshold=0.45, threshold_type="fixed")
    )
    run_cfg = CrawlerRunConfig(
        markdown_generator=md_generator,
        magic=True,
        remove_overlay_elements=True,
        page_timeout=15000,
    )

    extracted_sources = []
    async with AsyncWebCrawler(config=browser_cfg) as crawler:
        for item in discovered:
            url = item["url"]
            yt_id = extract_youtube_id(url)

            if yt_id:
                print(f"[Extract:YouTube] {item['title']}")
                raw_text = get_yt_transcript(yt_id)
                medium = "youtube_transcript"
            else:
                print(f"[Extract:Web] {item['title']}")
                try:
                    res = await crawler.arun(url=url, config=run_cfg)
                    raw_text = res.markdown.fit_markdown if res.success else ""
                except Exception:
                    raw_text = ""
                medium = "web_page"

            if not raw_text and item["snippet"]:
                raw_text = item["snippet"]
                medium = "snippet_fallback"

            if raw_text:
                chunks = score_and_chunk(raw_text)
                if chunks:
                    extracted_sources.append({
                        "category": item["category"],
                        "medium": medium,
                        "title": item["title"],
                        "url": url,
                        "chunks": chunks,
                    })

            await asyncio.sleep(1.0)

    return {
        "song": song,
        "artist": artist,
        "sources_count": len(extracted_sources),
        "sources": extracted_sources,
    }


if __name__ == "__main__":
    raw_data = asyncio.run(search_and_extract("One Step Closer", "Linkin Park", max_per_query=3))
    with open("raw_extraction.json", "w", encoding="utf-8") as f:
        json.dump(raw_data, f, indent=2, ensure_ascii=False)
    print(f"Saved {raw_data['sources_count']} sources to raw_extraction.json")