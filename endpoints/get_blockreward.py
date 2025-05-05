# encoding: utf-8

from pydantic import BaseModel

from helper.deflationary_table import calc_block_reward
from server import app, kaspad_client


class BlockRewardResponse(BaseModel):
    blockreward: float = 12000132


@app.get("/info/blockreward", response_model=BlockRewardResponse | str, tags=["Kaspa network info"])
async def get_blockreward(stringOnly: bool = False):
    """
    Returns the current blockreward in KAS/block
    """
    resp = await kaspad_client.request("getBlockDagInfoRequest")
    daa_score = int(resp["getBlockDagInfoResponse"]["virtualDaaScore"])
    reward_info = calc_block_reward(daa_score)
    reward = reward_info["current"]

    if not stringOnly:
        return {"blockreward": reward}

    else:
        return f"{reward:.2f}"
