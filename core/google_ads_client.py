"""Google Ads client construction + account-level reads.

Engine-layer module. Receives credentials as a dict (spec §2: config injected,
not read from globals). Raw google-ads objects are isolated here.
"""
from google.ads.googleads.client import GoogleAdsClient


def build_client(credentials: dict) -> GoogleAdsClient:
    """Build a GoogleAdsClient from a credentials dict.

    Required keys: developer_token, client_id, client_secret, refresh_token,
    login_customer_id. `use_proto_plus` is forced True so enum/field access is
    consistent across the engine.
    """
    cfg = dict(credentials)
    cfg.setdefault("use_proto_plus", True)
    return GoogleAdsClient.load_from_dict(cfg)


def get_account_currency(client: GoogleAdsClient, customer_id: str) -> str:
    """Read customer.currency_code via GAQL. Spec §1: assert INR; spec §4.1: cache."""
    ga_service = client.get_service("GoogleAdsService")
    query = "SELECT customer.currency_code FROM customer LIMIT 1"
    response = ga_service.search(customer_id=customer_id, query=query)
    for row in response:
        return row.customer.currency_code
    raise RuntimeError("currency_code query returned no rows")
