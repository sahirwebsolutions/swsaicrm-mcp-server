"""
SSE transport identical to `mcp.server.sse.SseServerTransport` but with 20s heartbeat pings
and bounded outbound queue (backpressure protection).
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import quote
from uuid import uuid4

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from sse_starlette import EventSourceResponse
from starlette.requests import Request
from starlette.types import Receive, Scope, Send

from mcp.server.sse import SseServerTransport
from mcp.shared.message import SessionMessage

logger = logging.getLogger(__name__)

MCP_SSE_HEARTBEAT_SECONDS = 20
MAX_QUEUE_SIZE = 100


class CrmSseServerTransport(SseServerTransport):
    """MCP SSE with 20s heartbeat + bounded outbound event queue."""

    @asynccontextmanager
    async def connect_sse(self, scope: Scope, receive: Receive, send: Send):  # pragma: no cover
        if scope["type"] != "http":
            logger.error("connect_sse received non-HTTP request")
            raise ValueError("connect_sse can only handle HTTP requests")

        request = Request(scope, receive)
        lei = request.headers.get("last-event-id") or request.headers.get("Last-Event-ID")
        if lei:
            logger.info("mcp_sse_last_event_id_present")

        error_response = await self._security.validate_request(request, is_post=False)
        if error_response:
            await error_response(scope, receive, send)
            raise ValueError("Request validation failed")

        read_stream_writer: MemoryObjectSendStream[SessionMessage | Exception]
        read_stream: MemoryObjectReceiveStream[SessionMessage | Exception]
        write_stream: MemoryObjectSendStream[SessionMessage]
        write_stream_reader: MemoryObjectReceiveStream[SessionMessage]

        read_stream_writer, read_stream = anyio.create_memory_object_stream(0)
        write_stream, write_stream_reader = anyio.create_memory_object_stream(0)

        session_id = uuid4()
        self._read_stream_writers[session_id] = read_stream_writer
        logger.debug("Created new session with ID: %s", session_id)

        root_path = scope.get("root_path", "")
        full_message_path_for_client = root_path.rstrip("/") + self._endpoint
        client_post_uri_data = f"{quote(full_message_path_for_client)}?session_id={session_id.hex}"

        sse_stream_writer, sse_stream_reader = anyio.create_memory_object_stream[dict[str, Any]](0)

        async def sse_writer():
            queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=MAX_QUEUE_SIZE)
            event_seq = [0]

            async def forward_to_http():
                event_seq[0] += 1
                await sse_stream_writer.send(
                    {
                        "event_id": event_seq[0],
                        "event": "endpoint",
                        "data": client_post_uri_data,
                    }
                )
                while True:
                    ev = await queue.get()
                    event_seq[0] += 1
                    await sse_stream_writer.send({**ev, "event_id": event_seq[0]})

            async with sse_stream_writer, write_stream_reader:
                forwarder = asyncio.create_task(forward_to_http())
                try:
                    async for session_message in write_stream_reader:
                        payload: dict[str, Any] = {
                            "event": "message",
                            "data": session_message.message.model_dump_json(
                                by_alias=True, exclude_none=True
                            ),
                        }
                        while True:
                            try:
                                queue.put_nowait(payload)
                                break
                            except asyncio.QueueFull:
                                try:
                                    queue.get_nowait()
                                    logger.info(
                                        json.dumps(
                                            {"event": "sse_backpressure", "action": "dropped"}
                                        )
                                    )
                                except asyncio.QueueEmpty:
                                    continue
                finally:
                    forwarder.cancel()
                    try:
                        await forwarder
                    except asyncio.CancelledError:
                        pass

        async with anyio.create_task_group() as tg:

            async def response_wrapper(sc: Scope, rcv: Receive, snd: Send):
                await EventSourceResponse(
                    content=sse_stream_reader,
                    data_sender_callable=sse_writer,
                    ping=MCP_SSE_HEARTBEAT_SECONDS,
                )(sc, rcv, snd)
                await read_stream_writer.aclose()
                await write_stream_reader.aclose()
                logger.debug("Client session disconnected %s", session_id)

            tg.start_soon(response_wrapper, scope, receive, send)
            yield (read_stream, write_stream)
