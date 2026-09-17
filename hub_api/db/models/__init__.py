"""ORM models, one table per module.

Importing this package registers every table on
:class:`~hub_api.db.base.Base`'s metadata, which the migrations and the test
fixtures both rely on.
"""

from hub_api.db.models.auth_code import AuthCode
from hub_api.db.models.device_code import DeviceCode
from hub_api.db.models.hub_model import HubModel
from hub_api.db.models.identity import Identity
from hub_api.db.models.model_version import ModelVersion
from hub_api.db.models.quota_entry import QuotaEntry
from hub_api.db.models.session import Session
from hub_api.db.models.token import Token
from hub_api.db.models.user import User

__all__ = [
    "AuthCode",
    "DeviceCode",
    "HubModel",
    "Identity",
    "ModelVersion",
    "QuotaEntry",
    "Session",
    "Token",
    "User",
]
