"""Fuente Knowledge Base ETL Package."""
import os

from requests.certs import where


os.environ.setdefault("SSL_CERT_FILE", where())

__version__ = "0.2.9"
