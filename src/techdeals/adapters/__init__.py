"""Source adapters for TechDeals v2 ingestion."""
from __future__ import annotations

from techdeals.adapters.base import (
    SourceAdapter,
    get_adapter,
    list_sources,
    load_all,
    register_adapter,
)
from techdeals.adapters.govdeals import GovDealsAdapter
from techdeals.adapters.liquidation import LiquidationComAdapter
from techdeals.adapters.rackrat import RackRatAdapter
from techdeals.adapters.reddit import (
    RedditAtomAdapter,
    RedditHardwareswapAdapter,
    RedditHomelabsalesAdapter,
)
from techdeals.adapters.rss_csv import (
    AtlasGen5SsdAdapter,
    GoogleShoppingAdapter,
    SlickdealsAdapter,
    SplPsuTierListAdapter,
    SsdPricingRun1Adapter,
)
from techdeals.adapters.shopify import (
    FusionwwAdapter,
    ServerPartDealsAdapter,
    ShopifyAdapter,
    WaterpantherAdapter,
)

__all__ = [
    "AtlasGen5SsdAdapter",
    "FusionwwAdapter",
    "GoogleShoppingAdapter",
    "GovDealsAdapter",
    "LiquidationComAdapter",
    "RackRatAdapter",
    "RedditAtomAdapter",
    "RedditHardwareswapAdapter",
    "RedditHomelabsalesAdapter",
    "ServerPartDealsAdapter",
    "ShopifyAdapter",
    "SlickdealsAdapter",
    "SourceAdapter",
    "SplPsuTierListAdapter",
    "SsdPricingRun1Adapter",
    "WaterpantherAdapter",
    "get_adapter",
    "list_sources",
    "load_all",
    "register_adapter",
]
