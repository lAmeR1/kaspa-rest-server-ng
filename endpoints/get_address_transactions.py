# encoding: utf-8
import re
import time
from enum import Enum
from typing import List

from fastapi import Path, Query, HTTPException
from kaspa_script_address import to_script
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.future import select
from starlette.responses import Response

from constants import ADDRESS_EXAMPLE, REGEX_KASPA_ADDRESS
from constants import DISABLE_LIMITS, USE_SCRIPT_FOR_ADDRESS
from dbsession import async_session
from endpoints import sql_db_only
from endpoints.get_transactions import search_for_transactions, TxSearch, TxModel
from models.AddressKnown import AddressKnown
from models.TxAddrMapping import TxAddrMapping, TxScriptMapping
from server import app

DESC_RESOLVE_PARAM = (
    "Use this parameter if you want to fetch the TransactionInput previous outpoint details."
    " Light fetches only the adress and amount. Full fetches the whole TransactionOutput and "
    "adds it into each TxInput."
)


class AddressesActiveRequest(BaseModel):
    addresses: list[str] = [ADDRESS_EXAMPLE]


class TxIdResponse(BaseModel):
    address: str
    active: bool


class TransactionsReceivedAndSpent(BaseModel):
    tx_received: str
    tx_spent: str | None
    # received_amount: int = 38240000000


class TransactionForAddressResponse(BaseModel):
    transactions: List[TransactionsReceivedAndSpent]


class TransactionCount(BaseModel):
    total: int
    limit_exceeded: bool


class AddressName(BaseModel):
    address: str
    name: str


class PreviousOutpointLookupMode(str, Enum):
    no = "no"
    light = "light"
    full = "full"


@app.get(
    "/addresses/{kaspaAddress}/full-transactions",
    response_model=List[TxModel],
    response_model_exclude_unset=True,
    tags=["Kaspa addresses"],
    openapi_extra={"strict_query_params": True},
)
@sql_db_only
async def get_full_transactions_for_address(
    kaspaAddress: str = Path(description=f"Kaspa address as string e.g. {ADDRESS_EXAMPLE}", regex=REGEX_KASPA_ADDRESS),
    limit: int = Query(description="The number of records to get", ge=1, le=500, default=50),
    offset: int = Query(description="The offset from which to get records", ge=0, default=0),
    fields: str = "",
    resolve_previous_outpoints: PreviousOutpointLookupMode = Query(default="no", description=DESC_RESOLVE_PARAM),
):
    """
    Get all transactions for a given address from database.
    And then get their related full transaction data
    """
    try:
        script = to_script(kaspaAddress)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid address: {kaspaAddress}")

    async with async_session() as s:
        if USE_SCRIPT_FOR_ADDRESS:
            tx_within_limit_offset = await s.execute(
                select(TxScriptMapping.transaction_id)
                .filter(TxScriptMapping.script_public_key == script)
                .limit(limit)
                .offset(offset)
                .order_by(TxScriptMapping.block_time.desc())
            )
        else:
            tx_within_limit_offset = await s.execute(
                select(TxAddrMapping.transaction_id)
                .filter(TxAddrMapping.address == kaspaAddress)
                .limit(limit)
                .offset(offset)
                .order_by(TxAddrMapping.block_time.desc())
            )

    tx_ids_in_page = [x[0] for x in tx_within_limit_offset.all()]

    return await search_for_transactions(TxSearch(transactionIds=tx_ids_in_page), fields, resolve_previous_outpoints)


@app.post(
    "/addresses/active",
    response_model=List[TxIdResponse],
    response_model_exclude_unset=True,
    tags=["Kaspa addresses"],
    openapi_extra={"strict_query_params": True},
)
@sql_db_only
async def get_addresses_active(addresses_active_request: AddressesActiveRequest):
    """
    This endpoint checks if addresses have had any transaction activity in the past.
    It is specifically designed for HD Wallets to verify historical address activity.
    """
    async with async_session() as s:
        addresses = set(addresses_active_request.addresses)
        script_addresses = set()
        for address in addresses:
            try:
                if not re.search(REGEX_KASPA_ADDRESS, address):
                    raise ValueError
                script_addresses.add(to_script(address))
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid address: {address}")

        if USE_SCRIPT_FOR_ADDRESS:
            result = await s.execute(
                select(TxScriptMapping).filter(TxScriptMapping.script_public_key.in_(script_addresses))
            )
            addresses_used = set(r.script_public_key_address for r in result.scalars().all())
        else:
            result = await s.execute(
                select(TxAddrMapping.address).distinct().filter(TxScriptMapping.address.in_(addresses))
            )
            addresses_used = set(result.scalars().all())

    return [
        TxIdResponse(address=address, active=(address in addresses_used))
        for address in addresses_active_request.addresses
    ]


@app.get(
    "/addresses/{kaspaAddress}/full-transactions-page",
    response_model=List[TxModel],
    response_model_exclude_unset=True,
    tags=["Kaspa addresses"],
    openapi_extra={"strict_query_params": True},
)
@sql_db_only
async def get_full_transactions_for_address_page(
    response: Response,
    kaspaAddress: str = Path(description=f"Kaspa address as string e.g. {ADDRESS_EXAMPLE}", regex=REGEX_KASPA_ADDRESS),
    limit: int = Query(
        description="The max number of records to get. "
        "For paging combine with using 'before/after' from oldest previous result. "
        "Use value of X-Next-Page-Before/-After as long as header is present to continue paging. "
        "The actual number of transactions returned for each page can be > limit.",
        ge=1,
        le=500,
        default=50,
    ),
    before: int = Query(
        description="Only include transactions with block time before this (epoch-millis)", ge=0, default=0
    ),
    after: int = Query(
        description="Only include transactions with block time after this (epoch-millis)", ge=0, default=0
    ),
    fields: str = "",
    resolve_previous_outpoints: PreviousOutpointLookupMode = Query(default="no", description=DESC_RESOLVE_PARAM),
):
    """
    Get all transactions for a given address from database.
    And then get their related full transaction data
    """
    try:
        script = to_script(kaspaAddress)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid address: {kaspaAddress}")

    if USE_SCRIPT_FOR_ADDRESS:
        query = (
            select(TxScriptMapping.transaction_id, TxScriptMapping.block_time)
            .filter(TxScriptMapping.script_public_key == script)
            .limit(limit)
        )
    else:
        query = (
            select(TxAddrMapping.transaction_id, TxAddrMapping.block_time)
            .filter(TxAddrMapping.address == kaspaAddress)
            .limit(limit)
        )

    response.headers["X-Page-Count"] = "0"
    if before != 0 and after != 0:
        raise HTTPException(status_code=400, detail="Only one of [before, after] can be present")
    elif before != 0:
        if before <= 1636298787842:  # genesis block_time
            return []
        if USE_SCRIPT_FOR_ADDRESS:
            query = query.filter(TxScriptMapping.block_time < before).order_by(TxScriptMapping.block_time.desc())
        else:
            query = query.filter(TxAddrMapping.block_time < before).order_by(TxAddrMapping.block_time.desc())
    elif after != 0:
        if after > int(time.time() * 1000) + 3600000:  # now + 1 hour
            return []
        if USE_SCRIPT_FOR_ADDRESS:
            query = query.filter(TxScriptMapping.block_time > after).order_by(TxScriptMapping.block_time.asc())
        else:
            query = query.filter(TxAddrMapping.block_time > after).order_by(TxAddrMapping.block_time.asc())
    else:
        if USE_SCRIPT_FOR_ADDRESS:
            query = query.order_by(TxScriptMapping.block_time.desc())
        else:
            query = query.order_by(TxAddrMapping.block_time.desc())

    async with async_session() as s:
        tx_within_limit_before = await s.execute(query)

        tx_ids_and_block_times = [(x.transaction_id, x.block_time) for x in tx_within_limit_before.all()]
        if not tx_ids_and_block_times:
            return []

        tx_ids_and_block_times = sorted(tx_ids_and_block_times, key=lambda x: x[1], reverse=True)
        newest_block_time = tx_ids_and_block_times[0][1]
        oldest_block_time = tx_ids_and_block_times[-1][1]
        tx_ids = {tx_id for tx_id, block_time in tx_ids_and_block_times}
        if len(tx_ids_and_block_times) == limit:
            # To avoid gaps when transactions with the same block_time are at the intersection between pages.
            if USE_SCRIPT_FOR_ADDRESS:
                tx_with_same_block_time = await s.execute(
                    select(TxScriptMapping.transaction_id)
                    .filter(TxScriptMapping.script_public_key == script)
                    .filter(
                        or_(
                            TxScriptMapping.block_time == newest_block_time,
                            TxScriptMapping.block_time == oldest_block_time,
                        )
                    )
                )
            else:
                tx_with_same_block_time = await s.execute(
                    select(TxAddrMapping.transaction_id)
                    .filter(TxAddrMapping.address == kaspaAddress)
                    .filter(
                        or_(
                            TxAddrMapping.block_time == newest_block_time, TxAddrMapping.block_time == oldest_block_time
                        )
                    )
                )
            tx_ids.update([x for x in tx_with_same_block_time.scalars().all()])

    response.headers["X-Page-Count"] = str(len(tx_ids))
    if len(tx_ids) >= limit:
        response.headers["X-Next-Page-After"] = str(newest_block_time)
        response.headers["X-Next-Page-Before"] = str(oldest_block_time)

    # Legacy:
    response.headers["X-Current-Page"] = str(len(tx_ids))
    response.headers["X-Oldest-Epoch-Millis"] = str(oldest_block_time)

    return await search_for_transactions(TxSearch(transactionIds=list(tx_ids)), fields, resolve_previous_outpoints)


@app.get(
    "/addresses/{kaspaAddress}/transactions-count",
    response_model=TransactionCount,
    tags=["Kaspa addresses"],
    openapi_extra={"strict_query_params": True},
)
@sql_db_only
async def get_transaction_count_for_address(
    response: Response,
    kaspaAddress: str = Path(description=f"Kaspa address as string e.g. {ADDRESS_EXAMPLE}", regex=REGEX_KASPA_ADDRESS),
):
    """
    Count the number of transactions associated with this address
    """
    try:
        script = to_script(kaspaAddress)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid address: {kaspaAddress}")

    async with async_session() as s:
        if DISABLE_LIMITS:
            if USE_SCRIPT_FOR_ADDRESS:
                result = await s.execute(select(func.count()).filter(TxScriptMapping.script_public_key == script))
            else:
                result = await s.execute(select(func.count()).filter(TxAddrMapping.address == kaspaAddress))
        else:
            if USE_SCRIPT_FOR_ADDRESS:
                result = await s.execute(
                    select(func.count()).select_from(
                        select(1).filter(TxScriptMapping.script_public_key == script).limit(100001).subquery()
                    )
                )
            else:
                result = await s.execute(
                    select(func.count()).select_from(
                        select(1).filter(TxAddrMapping.address == kaspaAddress).limit(100001).subquery()
                    )
                )
        tx_count = result.scalar()
        limit_exceeded = False
        ttl = 8
        if not DISABLE_LIMITS:
            if tx_count > 10000:
                tx_count = 10000
                limit_exceeded = True
                ttl = 86400
            elif tx_count > 1000:
                ttl = 30

    response.headers["Cache-Control"] = f"public, max-age={ttl}"
    return TransactionCount(total=tx_count, limit_exceeded=limit_exceeded)


@app.get(
    "/addresses/{kaspaAddress}/name",
    response_model=AddressName | None,
    tags=["Kaspa addresses"],
    openapi_extra={"strict_query_params": True},
)
@sql_db_only
async def get_name_for_address(
    response: Response,
    kaspaAddress: str = Path(
        description="Kaspa address as string e.g. kaspa:qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqkx9awp4e",
        regex=REGEX_KASPA_ADDRESS,
    ),
):
    """
    Get the name for an address
    """
    try:
        to_script(kaspaAddress)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid address: {kaspaAddress}")

    async with async_session() as s:
        r = (await s.execute(select(AddressKnown).filter(AddressKnown.address == kaspaAddress))).first()

    response.headers["Cache-Control"] = "public, max-age=600"
    if r:
        return AddressName(address=r.AddressKnown.address, name=r.AddressKnown.name)
    else:
        raise HTTPException(
            status_code=404, detail="Address name not found", headers={"Cache-Control": "public, max-age=600"}
        )
