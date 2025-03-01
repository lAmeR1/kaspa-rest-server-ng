# encoding: utf-8

from pydantic import BaseModel

from server import app, kaspad_client
from fastapi.responses import PlainTextResponse


class CoinSupplyResponse(BaseModel):
    circulatingSupply: str = "1000900697580640180"
    maxSupply: str = "2900000000000000000"


@app.get("/info/coinsupply", response_model=CoinSupplyResponse, tags=["Kaspa network info"])
async def get_coinsupply():
    """
    Get $KAS coin supply information
    """
    resp = await kaspad_client[0].get_coin_supply()
    return {
        "circulatingSupply": resp["getCoinSupplyResponse"]["circulatingSompi"],
        "totalSupply": resp["getCoinSupplyResponse"]["circulatingSompi"],
        "maxSupply": resp["getCoinSupplyResponse"]["maxSompi"],
    }


@app.get("/info/coinsupply/circulating", tags=["Kaspa network info"], response_class=PlainTextResponse)
async def get_circulating_coins(in_billion: bool = False):
    """
    Get circulating amount of $KAS token as numerical value
    """
    resp = await kaspad_client[0].get_coin_supply()
    coins = str(float(resp["getCoinSupplyResponse"]["circulatingSompi"]) / 100000000)
    if in_billion:
        return str(round(float(coins) / 1000000000, 2))
    else:
        return coins


@app.get("/info/coinsupply/total", tags=["Kaspa network info"], response_class=PlainTextResponse)
async def get_total_coins():
    """
    Get total amount of $KAS token as numerical value
    """
    resp = await kaspad_client[0].get_coin_supply()
    return str(float(resp["getCoinSupplyResponse"]["circulatingSompi"]) / 100000000)
