from .base import Source
from .mock import MockSource
from .portal_sot_kz import PortalSotSource

SOURCES: dict[str, type[Source]] = {
    MockSource.name: MockSource,
    PortalSotSource.name: PortalSotSource,
}

__all__ = ["Source", "MockSource", "PortalSotSource", "SOURCES"]
