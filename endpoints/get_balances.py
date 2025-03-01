# encoding: utf-8
from typing import List

from fastapi import HTTPException
from pydantic import BaseModel

from constants import ADDRESS_EXAMPLE
from server import app, kaspad_client


class BalancesByAddressEntry(BaseModel):
    address: str = ADDRESS_EXAMPLE
    balance: int = 12451591699


class BalanceRequest(BaseModel):
    addresses: list[str] = [ADDRESS_EXAMPLE]


@app.post("/addresses/balances", response_model=List[BalancesByAddressEntry], tags=["Kaspa addresses"])
async def get_balances_from_kaspa_addresses(body: BalanceRequest):
    """
    Get balance for a given kaspa address
    """
    resp = await kaspad_client[0].get_balances_by_addresses(body.addresses)

    try:
        resp = resp["getBalancesByAddressesResponse"]
    except KeyError:
        if "getUtxosByAddressesResponse" in resp and "error" in resp["getUtxosByAddressesResponse"]:
            raise HTTPException(status_code=400, detail=resp["getUtxosByAddressesResponse"]["error"])
        else:
            raise

    if resp.get("error"):
        raise HTTPException(500, resp["error"])

    return resp["entries"]
