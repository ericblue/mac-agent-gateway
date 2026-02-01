"""Service adapters for CLI tools."""

from mag.services.contacts import ContactCache, get_contact_cache
from mag.services.imsg import ImsgError

__all__ = ["ContactCache", "ImsgError", "get_contact_cache"]
