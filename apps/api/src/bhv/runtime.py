"""Event loop untuk uvicorn.

psycopg async tidak bisa memakai ProactorEventLoop (default Windows), jadi API selalu dijalankan
dengan SelectorEventLoop:  uvicorn bhv.main:app --loop bhv.runtime:new_event_loop
Di Linux ini sama dengan loop asyncio standar.
"""

import asyncio


def new_event_loop() -> asyncio.AbstractEventLoop:
    return asyncio.SelectorEventLoop()
