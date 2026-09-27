"""Storage errors every backend raises, so callers never catch a driver's own exception types."""


class StorageError(Exception):
    """A storage backend failed to read or write (database locked, connection lost, constraint broken).

    Backends raise a subclass and chain the driver error as ``__cause__``.
    """
