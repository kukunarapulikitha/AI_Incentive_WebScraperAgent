from config.sources import SourceConfig
from extractors.base import BaseExtractor
from extractors.html_extractor import HtmlExtractor
from extractors.pdf_extractor import PdfExtractor
from extractors.api_extractor import ApiExtractor
from extractors.apify_extractor import ApifyExtractor
from extractors.playwright_extractor import PlaywrightExtractor
from extractors.dsire_spider import DSIRESpiderExtractor
from extractors.static_extractor import StaticExtractor

_EXTRACTORS: dict[str, type[BaseExtractor]] = {
    "html": HtmlExtractor,
    "pdf": PdfExtractor,
    "api": ApiExtractor,
    "apify": ApifyExtractor,
    "playwright": PlaywrightExtractor,
    "dsire_spider": DSIRESpiderExtractor,
    "static": StaticExtractor,
}


def get_extractor(source: SourceConfig) -> BaseExtractor:
    import os
    extractor_type = source.extractor_type
    # Graceful fallback: if apify requested but no token, use html
    if extractor_type == "apify" and not os.getenv("APIFY_TOKEN", "").strip():
        import structlog
        structlog.get_logger().warning(
            "apify.no_token_fallback",
            source=source.key,
            fallback="html",
        )
        extractor_type = "html"
    cls = _EXTRACTORS.get(extractor_type)
    if cls is None:
        raise ValueError(f"Unknown extractor_type {extractor_type!r} for source {source.key}")
    return cls()
