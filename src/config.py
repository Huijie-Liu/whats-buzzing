"""Source configurations, constants, and shared data used across modules."""

import os
from pathlib import Path

# ── Optional dependencies (imported once, shared everywhere) ───────────
try:
    import curl_cffi
    from curl_cffi import CurlFollow
    _CURL_CFFI_AVAILABLE = True
except ImportError:
    curl_cffi = None
    CurlFollow = None
    _CURL_CFFI_AVAILABLE = False

ROOT = Path(__file__).resolve().parent.parent
PUBLIC_DIR = ROOT / "public"
HOST = "127.0.0.1"
PORT = int(os.environ.get("PORT", "8765"))
CACHE_SECONDS = 180

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

REQUEST_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "en-US,en;q=0.9",
}

# XML namespaces used by feed parsers
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "dc": "http://purl.org/dc/elements/1.1/",
    "discourse": "http://www.discourse.org/",
    "image": "http://www.google.com/schemas/sitemap-image/1.1",
    "media": "http://search.yahoo.com/mrss/",
    "news": "http://www.google.com/schemas/sitemap-news/0.9",
    "sm": "http://www.sitemaps.org/schemas/sitemap/0.9",
}

# ---------------------------------------------------------------------------
# Source definitions
# ---------------------------------------------------------------------------

SOURCES = {
    "hn": {
        "label": "Hacker News",
        "short": "HN",
        "kind": "hn",
        "home": "https://news.ycombinator.com/",
        "accent": "#f0652f",
        "category": "hot",
        "story_limit": 20,
    },
    "economist": {
        "label": "经济学人",
        "short": "Economist",
        "kind": "rss",
        "home": "https://www.economist.com/latest",
        "accent": "#d71920",
        "category": "business",
        "story_limit": 20,
        "feeds": ["https://www.economist.com/latest/rss.xml"],
    },
    "reuters": {
        "label": "路透社",
        "short": "Reuters",
        "kind": "reuters_sitemap",
        "home": "https://www.reuters.com/",
        "accent": "#ff8000",
        "category": "general",
        "story_limit": 20,
        "feeds": [
            "https://www.reuters.com/arc/outboundfeeds/news-sitemap/?outputType=xml",
            "https://www.reuters.com/arc/outboundfeeds/news-sitemap/?outputType=xml&from=100",
            "https://www.reuters.com/arc/outboundfeeds/news-sitemap/?outputType=xml&from=200",
        ],
    },
    "bloomberg": {
        "label": "彭博社",
        "short": "Bloomberg",
        "kind": "rss",
        "home": "https://www.bloomberg.com/",
        "accent": "#0068ff",
        "category": "business",
        "story_limit": 20,
        "feeds": [
            "https://feeds.bloomberg.com/markets/news.rss",
            "https://feeds.bloomberg.com/economics/news.rss",
            "https://feeds.bloomberg.com/technology/news.rss",
            "https://feeds.bloomberg.com/politics/news.rss",
            "https://feeds.bloomberg.com/industries/news.rss",
            "https://feeds.bloomberg.com/wealth/news.rss",
            "https://feeds.bloomberg.com/green/news.rss",
            "https://feeds.bloomberg.com/businessweek/news.rss",
            "https://feeds.bloomberg.com/pursuits/news.rss",
        ],
    },
    "guardian": {
        "label": "卫报",
        "short": "Guardian",
        "kind": "rss",
        "home": "https://www.theguardian.com/",
        "accent": "#052962",
        "category": "general",
        "story_limit": 20,
        "feeds": [
            "https://www.theguardian.com/world/rss",
            "https://www.theguardian.com/us-news/rss",
            "https://www.theguardian.com/uk-news/rss",
            "https://www.theguardian.com/business/rss",
            "https://www.theguardian.com/technology/rss",
            "https://www.theguardian.com/politics/rss",
        ],
    },
    "bbc": {
        "label": "BBC",
        "short": "BBC",
        "kind": "rss",
        "home": "https://www.bbc.com/news",
        "accent": "#b80000",
        "category": "general",
        "story_limit": 20,
        "feeds": [
            "https://feeds.bbci.co.uk/news/world/rss.xml",
            "https://feeds.bbci.co.uk/news/uk/rss.xml",
            "https://feeds.bbci.co.uk/news/business/rss.xml",
            "https://feeds.bbci.co.uk/news/technology/rss.xml",
            "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
            "https://feeds.bbci.co.uk/news/politics/rss.xml",
        ],
    },
    "verge": {
        "label": "The Verge",
        "short": "Verge",
        "kind": "atom",
        "home": "https://www.theverge.com/",
        "accent": "#e2127a",
        "category": "tech",
        "story_limit": 20,
        "feeds": ["https://www.theverge.com/rss/index.xml"],
    },
    "google_zh": {
        "label": "Google News 中国",
        "short": "Google 中国",
        "kind": "google_rss",
        "home": "https://news.google.com/topstories?hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
        "accent": "#34a853",
        "category": "hot",
        "story_limit": 20,
        "feeds": [
            "https://news.google.com/rss?hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
            "https://news.google.com/rss/headlines/section/topic/WORLD?hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
            "https://news.google.com/rss/headlines/section/topic/NATION?hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
            "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
            "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
            "https://news.google.com/rss/headlines/section/topic/SCIENCE?hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
            "https://news.google.com/rss/headlines/section/topic/HEALTH?hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
        ],
    },
    "atlantic": {
        "label": "大西洋周刊",
        "short": "Atlantic",
        "kind": "atom",
        "home": "https://www.theatlantic.com/",
        "accent": "#111111",
        "category": "general",
        "story_limit": 20,
        "feeds": ["https://www.theatlantic.com/feed/all/"],
    },
    "newyorker": {
        "label": "纽约客",
        "short": "NewYorker",
        "kind": "rss",
        "home": "https://www.newyorker.com/",
        "accent": "#e60000",
        "category": "general",
        "story_limit": 20,
        "feeds": ["https://www.newyorker.com/feed/everything"],
    },
    "mit_tech": {
        "label": "MIT 科技评论",
        "short": "MIT Tech",
        "kind": "rss",
        "home": "https://www.technologyreview.com/",
        "accent": "#ff5a00",
        "category": "tech",
        "story_limit": 20,
        "feeds": ["https://www.technologyreview.com/feed/"],
    },
    "zhihu": {
        "label": "知乎热榜",
        "short": "知乎",
        "kind": "zhihu",
        "home": "https://www.zhihu.com/hot",
        "accent": "#0066ff",
        "category": "hot",
        "story_limit": 20,
    },
    "washingtonpost": {
        "label": "华盛顿邮报",
        "short": "WaPo",
        "kind": "rss",
        "home": "https://www.washingtonpost.com/",
        "accent": "#1a1a1a",
        "category": "general",
        "story_limit": 20,
        "feeds": [
            "https://feeds.washingtonpost.com/rss/world",
            "https://feeds.washingtonpost.com/rss/national",
            "https://feeds.washingtonpost.com/rss/business",
            "https://feeds.washingtonpost.com/rss/politics",
            "https://feeds.washingtonpost.com/rss/technology",
        ],
    },
    "linux_do": {
        "label": "LINUX DO",
        "short": "LINUX DO",
        "kind": "discourse",
        "home": "https://linux.do/new",
        "accent": "#0088cc",
        "category": "tech",
        "story_limit": 20,
        "feeds": ["https://linux.do/latest.rss"],
        "headers": {
            "User-Agent": USER_AGENT,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
    },
    "linux_do_top": {
        "label": "LINUX DO 热榜",
        "short": "LINUX DO 热榜",
        "kind": "discourse",
        "home": "https://linux.do/top",
        "accent": "#0a8ed6",
        "category": "hot",
        "story_limit": 20,
        "feeds": ["https://linux.do/top/daily.rss"],
        "headers": {
            "User-Agent": USER_AGENT,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
    },
    "hupu_nba": {
        "label": "虎扑-篮球",
        "short": "虎扑NBA",
        "kind": "hupu_sub",
        "home": "https://bbs.hupu.com/all-nba",
        "accent": "#c41230",
        "category": "sports",
        "story_limit": 20,
    },
    "hupu_soccer": {
        "label": "虎扑-足球",
        "short": "虎扑足球",
        "kind": "hupu_sub",
        "home": "https://bbs.hupu.com/all-soccer",
        "accent": "#019f4b",
        "category": "sports",
        "story_limit": 20,
    },
    "hupu_lol": {
        "label": "虎扑-LOL",
        "short": "虎扑LOL",
        "kind": "hupu_sub",
        "home": "https://bbs.hupu.com/lol",
        "accent": "#6b3fa0",
        "category": "sports",
        "story_limit": 20,
    },
}

# ---------------------------------------------------------------------------
# Translation configuration
# ---------------------------------------------------------------------------

# Sources whose content is already Chinese — skip translation entirely.
NON_TRANSLATABLE_SOURCES = {
    "zhihu", "google_zh", "linux_do", "linux_do_top",
    "hupu_nba", "hupu_soccer", "hupu_lol",
}

# Sources whose summary field carries meaningful prose worth translating.
# HN (author name), Reuters (no summary), Google (publisher name) are excluded.
SUMMARY_TRANSLATABLE_SOURCES = {
    "economist", "bloomberg", "guardian", "bbc", "verge",
    "atlantic", "newyorker", "mit_tech", "washingtonpost",
}
