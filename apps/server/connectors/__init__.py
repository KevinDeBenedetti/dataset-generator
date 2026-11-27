"""Connectors: the code that fetches a data source and reports its provenance.

``REGISTRY`` maps a data source's ``connector`` to its connector (base.py holds
the contract).
"""

from typing import Dict, Optional, cast

from server.connectors.base import SourceConnector
from server.connectors.datagouv import DatagouvConnector
from server.connectors.rest import RestConnector
from server.connectors.sql_dump import SqlDumpConnector
from server.connectors.sql_remote import SqlRemoteConnector
from server.connectors.upload import UploadConnector
from server.connectors.url import UrlConnector

REGISTRY: Dict[str, SourceConnector] = {
    c.kind: c
    for c in (
        cast(SourceConnector, UploadConnector()),
        cast(SourceConnector, DatagouvConnector()),
        cast(SourceConnector, UrlConnector()),
        cast(SourceConnector, RestConnector()),
        cast(SourceConnector, SqlDumpConnector()),
        cast(SourceConnector, SqlRemoteConnector()),
    )
}


def get_connector(kind: str) -> Optional[SourceConnector]:
    return REGISTRY.get(kind)
