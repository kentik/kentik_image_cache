from enum import Enum


class EntryStatus(Enum):
    ACTIVE = 'active'
    PENDING = 'pending'
    NOT_FOUND = 'not found'


class CreationStatus(Enum):
    CREATED = 'created'
    EXISTING = 'existing'


class ActivationStatus(Enum):
    SUCCESS = 'success'
    FAILED = 'failed'


class CacheEntryType(Enum):
    REQUEST = 'api_request'
    ERROR_MSG = 'api_error'
    IMAGE = 'image'
    INVALID = 'invalid'
