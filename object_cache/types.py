from enum import Enum


class EntryStatus(Enum):
    """
    Enum representing status of CacheEntry
    """

    ACTIVE = "active"
    PENDING = "pending"


class CreationStatus(Enum):
    """
    Enum representing result of cache entry creation request
    """

    CREATED = "created"
    EXISTING = "existing"


class ActivationStatus(Enum):
    """
    Enum representing result of cache entry activation attempt
    """

    SUCCESS = "success"
    FAILED = "failed"
