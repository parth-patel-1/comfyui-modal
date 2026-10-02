"""Bearer-token ASGI proxy in front of ComfyUI (127.0.0.1:8188).

ComfyUI itself has no authentication; exposing it directly on Modal would
let anyone submit GPU jobs. This proxy sits in front inside the same
container and enforces `Authorization: Bearer <token>` on every HTTP
request and WebSocket connection. The token lives in a Modal secret
(genstudio-engine-token) and is shared only with the GenStudio backend.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import os

import httpx
import websockets

UPSTREAM = "http://127.0.0.1:8188"
UPSTREAM_WS = "ws://127.0.0.1:8188"


class ComfyProxy:
    """Raw ASGI application: bearer auth + reverse proxy (HTTP + WebSocket)."""

    def __init__(self, upstream: str = UPSTREAM, upstream_ws: str = UPSTREAM_WS) -> None:
        self.upstream = upstream.rstrip("/")
        self.upstream_ws = upstream_ws.rstrip("/")
        self._client: httpx.AsyncClient | None = None

    @property
    def token(self) -> str:
        return os.environ.get("GENSTUDIO_ENGINE_TOKEN", "")

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "lifespan":
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
                    return

        if not self.token:
            await self._deny(send, scope, "engine token not configured")
            return

        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        presented = headers.get(b"authorization", b"")
        expected = f"Bearer {self.token}".encode()
        if not hmac.compare_digest(presented, expected):
            await self._deny(send, scope, "invalid bearer token")
            return

        if scope["type"] == "http":
            await self._proxy_http(scope, receive, send)
        elif scope["type"] == "websocket":
            await self._proxy_ws(scope, receive, send)

    async def _deny(self, send, scope, reason: str) -> None:
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 4401})
            return
        body = json.dumps({"error": "unauthorized", "detail": reason}).encode()
        await send({
            "type": "http.response.start",
            "status": 401,
            "headers": [(b"content-type", b"application/json")],
        })
        await send({"type": "http.response.body", "body": body})

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.upstream,
                timeout=httpx.Timeout(60.0, read=1800.0),
            )
        return self._client

    async def _proxy_http(self, scope, receive, send) -> None:
        client = await self._get_client()
        headers = [
            (k, v) for k, v in scope.get("headers", [])
            if k.lower() not in (b"host", b"authorization")
        ]

        request_body = b""
        while True:
            message = await receive()
            if message["type"] == "http.request":
                request_body += message.get("body", b"")
                if not message.get("more_body"):
                    break
            elif message["type"] == "http.disconnect":
                return

        # readiness probe: answer /health ourselves so clients get a clean
        # 200 once ComfyUI is up (ComfyUI has no /health route, so forwarding
        # this request upstream would return a misleading 404)
        if scope["path"] == "/health" and scope["method"] == "GET":
            try:
                resp = await client.get("/system_stats")
                resp.aclose()
                if resp.status_code == 200:
                    body = b'{"status":"ok"}'
                    await send({"type": "http.response.start",
                                "status": 200,
                                "headers": [(b"content-type",
                                             b"application/json")]})
                    await send({"type": "http.response.body", "body": body})
                    return
            except httpx.HTTPError:
                pass
            body = b'{"error": "comfyui not ready"}'
            await send({"type": "http.response.start", "status": 503,
                        "headers": [(b"content-type",
                                     b"application/json")]})
            await send({"type": "http.response.body", "body": body})
            return

        req = client.build_request(
            scope["method"],
            scope["path"],
            params=self._query_pairs(scope),
            headers=headers,
            content=request_body,
        )
        try:
            resp = await client.send(req, stream=True)
        except httpx.ConnectError:
            body = b'{"error": "comfyui not ready"}'
            await send({"type": "http.response.start", "status": 503,
                        "headers": [(b"content-type", b"application/json")]})
            await send({"type": "http.response.body", "body": body})
            return

        resp_headers = [
            (k.encode(), v.encode()) for k, v in resp.headers.items()
            if k.lower() not in ("content-length", "transfer-encoding", "connection")
        ]
        await send({
            "type": "http.response.start",
            "status": resp.status_code,
            "headers": resp_headers,
        })
        async for chunk in resp.aiter_bytes():
            await send({"type": "http.response.body", "body": chunk, "more_body": True})
        await send({"type": "http.response.body", "body": b""})
        await resp.aclose()

    async def _proxy_ws(self, scope, receive, send) -> None:
        query = scope.get("query_string", b"").decode()
        url = f"{self.upstream_ws}{scope['path']}"
        if query:
            url += f"?{query}"

        await send({"type": "websocket.accept"})
        try:
            async with websockets.connect(url, max_size=2**27) as upstream:

                async def client_to_upstream() -> None:
                    try:
                        while True:
                            message = await receive()
                            if message["type"] == "websocket.disconnect":
                                return
                            if message.get("bytes") is not None:
                                await upstream.send(message["bytes"])
                            elif message.get("text") is not None:
                                await upstream.send(message["text"])
                    except Exception:
                        pass

                async def upstream_to_client() -> None:
                    try:
                        async for data in upstream:
                            if isinstance(data, bytes):
                                await send({"type": "websocket.send", "bytes": data})
                            else:
                                await send({"type": "websocket.send", "text": data})
                    except Exception:
                        pass

                done, pending = await asyncio.wait(
                    [asyncio.create_task(client_to_upstream()),
                     asyncio.create_task(upstream_to_client())],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
        except Exception:
            pass
        finally:
            try:
                await send({"type": "websocket.close", "code": 1000})
            except Exception:
                pass

    @staticmethod
    def _query_pairs(scope) -> list[tuple[str, str]]:
        raw = scope.get("query_string", b"").decode()
        pairs = []
        for part in raw.split("&"):
            if not part:
                continue
            key, _, value = part.partition("=")
            pairs.append((key, value))
        return pairs


proxy_app = ComfyProxy()