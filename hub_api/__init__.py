"""Accounts, quotas, and community model hosting for spikeforge.

The service owns three things the toolkit deliberately does not: identity,
per-account storage accounting, and the hosted index of community-published
artifacts. It never runs a model, never imports ``torch``, and never writes to
the host's root filesystem.
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
