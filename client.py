"""Async httpx CRM client with bounded retries and optional circuit breaker."""

from __future__ import annotations

import asyncio
import json
import random
from typing import TYPE_CHECKING, Any

import httpx

from auth import AuthContext, auth_headers
from circuit_breaker import CircuitOpen, EndpointCircuitBreaker
from circuit_path import normalize_circuit_path
from errors import http_status_to_code, safe_upstream_detail
from tracing import get_request_id

if TYPE_CHECKING:
    pass


class UpstreamError(Exception):
    def __init__(self, code: str, status: int | None, message: str):
        super().__init__(message)
        self.code = code
        self.status = status
        self.message = message


class CRMClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout_s: float = 10.0,
        max_retries: int = 2,
        circuit: EndpointCircuitBreaker | None = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout_s
        self._max_retries = max_retries
        self._circuit = circuit or EndpointCircuitBreaker()
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(timeout_s))

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request_with_retries(
        self,
        method: str,
        path: str,
        *,
        auth: AuthContext,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        """
        Optional conditional request headers (e.g. ``If-Match``, ``If-Unmodified-Since``)
        may be passed via ``headers`` when the upstream API supports them.
        """
        rid = get_request_id() or ""
        h = auth_headers(auth, rid)
        if headers:
            h.update(headers)
        if idempotency_key:
            h["X-Idempotency-Key"] = idempotency_key

        url = f"{self._base}{path}" if path.startswith("/") else f"{self._base}/{path}"
        method_u = method.upper()
        route_shape = normalize_circuit_path(path)
        circuit_key = EndpointCircuitBreaker.key(method_u, route_shape, auth.workspace_id)
        try:
            self._circuit.check_before_request(circuit_key)
        except CircuitOpen:
            raise UpstreamError("upstream_unavailable", None, "circuit open") from None

        allow_retry = method_u == "GET" or (
            bool(idempotency_key) and method_u in ("POST", "PUT", "PATCH", "DELETE")
        )
        attempt = 0
        while True:
            try:
                resp = await self._client.request(
                    method_u,
                    url,
                    params=params,
                    json=json_body,
                    headers=h,
                )
                if allow_retry and resp.status_code >= 500 and attempt < self._max_retries:
                    self._circuit.record_failure(circuit_key)
                    await self._backoff(attempt)
                    attempt += 1
                    continue
                if resp.status_code >= 500:
                    self._circuit.record_failure(circuit_key)
                else:
                    self._circuit.record_success(circuit_key)
                return resp
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                if allow_retry and attempt < self._max_retries:
                    self._circuit.record_failure(circuit_key)
                    await self._backoff(attempt)
                    attempt += 1
                    continue
                # Idempotent write may have completed server-side; avoid poisoning circuit.
                if idempotency_key:
                    return _idempotent_unknown_response()
                self._circuit.record_failure(circuit_key)
                raise UpstreamError("upstream_error", None, "network error") from e

    async def _backoff(self, attempt: int) -> None:
        base = 0.1 * (2**attempt)
        jitter = random.uniform(0, 0.05)
        await asyncio.sleep(base + jitter)

    @staticmethod
    def raise_for_status(resp: httpx.Response) -> dict[str, Any] | list[Any]:
        if 200 <= resp.status_code < 300:
            try:
                out = resp.json()
            except Exception:
                return {}
            if isinstance(out, dict):
                return out
            return {"_data": out}
        code = http_status_to_code(resp.status_code)
        detail = safe_upstream_detail(_safe_json(resp))
        raise UpstreamError(code, resp.status_code, detail)


def _safe_json(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except Exception:
        return None


def _idempotent_unknown_response() -> httpx.Response:
    """Synthetic 200 body when the transport failed but a retry might duplicate work."""
    body = {
        "status": "unknown",
        "message": "Operation may have succeeded. Retry is safe.",
    }
    return httpx.Response(
        200,
        content=json.dumps(body).encode("utf-8"),
        headers={"content-type": "application/json"},
    )
