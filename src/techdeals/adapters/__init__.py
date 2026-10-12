"""Source adapters for TechDeals v2 ingestion."""
from __future__ import annotations

from techdeals.adapters.base import (
    SourceAdapter,
    get_adapter,
    list_sources,
    load_all,
    register_adapter,
)
from techdeals.adapters.rackrat import RackRatAdapter
from techdeals.adapters.reddit import (
    RedditAtomAdapter,
    RedditHardwareswapAdapter,
    RedditHomelabsalesAdapter,
)
from techdeals.adapters.shopify import (
    FusionwwAdapter,
    ServerPartDealsAdapter,
    ShopifyAdapter,
    WaterpantherAdapter,
)

__all__ = [
    "FusionwwAdapter",
    "RackRatAdapter",
    "RedditAtomAdapter",
    "RedditHardwareswapAdapter",
    "RedditHomelabsalesAdapter",
    "ServerPartDealsAdapter",
    "ShopifyAdapter",
    "SourceAdapter",
    "WaterpantherAdapter",
    "get_adapter",
    "list_sources",
    "load_all",
    "register_adapter",
]
