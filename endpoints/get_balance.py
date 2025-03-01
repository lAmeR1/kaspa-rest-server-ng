# encoding: utf-8

from fastapi import Path, HTTPException
from pydantic import BaseModel

from constants import ADDRESS_EXAMPLE, REGEX_KASPA_ADDRESS
from server import app, kaspad_client


class BalanceResponse(BaseModel):
    address: str = ADDRESS_EXAMPLE
    balance: int = 38240000000


@app.get("/addresses/{kaspaAddress}/balance", response_model=BalanceResponse, tags=["Kaspa addresses"])
async def get_balance_from_kaspa_address(
    kaspaAddress: str = Path(description=f"Kaspa address as string e.g. {ADDRESS_EXAMPLE}", regex=REGEX_KASPA_ADDRESS),
):
    """
    Get balance for a given kaspa address
    """
    resp = await kaspad_client[0].get_balance_by_address(kaspaAddress)

    try:
        resp = resp["getBalanceByAddressResponse"]
    except KeyError:
        if "getUtxosByAddressesResponse" in resp and "error" in resp["getUtxosByAddressesResponse"]:
            raise HTTPException(status_code=400, detail=resp["getUtxosByAddressesResponse"]["error"])
        else:
            raise

    if resp.get("error"):
        raise HTTPException(500, resp["error"])

    try:
        balance = int(resp["balance"])

    # return 0 if address is ok, but no utxos there
    except KeyError:
        balance = 0

    return {"address": kaspaAddress, "balance": balance}
