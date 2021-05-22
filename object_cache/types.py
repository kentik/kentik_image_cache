from enum import Enum


class EntryStatus(Enum):
    ACTIVE = "active"
    PENDING = "pending"


class CreationStatus(Enum):
    CREATED = "created"
    EXISTING = "existing"


class ActivationStatus(Enum):
    SUCCESS = "success"
    FAILED = "failed"
