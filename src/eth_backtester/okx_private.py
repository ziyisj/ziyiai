from __future__ import annotations

import base64
import hashlib
import hmac
import json
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


OKX_REST_BASE_URL = "https://www.okx.com"


@dataclass(frozen=True)
class OKXCredentials:
    api_key: str
    api_secret: str
    passphrase: str
    simulated: bool = False


class OKXAPIError(RuntimeError):
    pass


class OKXPrivateRESTClient:
    def __init__(self, credentials: OKXCredentials, base_url: str = OKX_REST_BASE_URL) -> None:
        self.credentials = credentials
        self.base_url = base_url.rstrip("/")

    def _timestamp(self) -> str:
        return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    def _sign(self, timestamp: str, method: str, request_path: str, body: str = "") -> str:
        message = f"{timestamp}{method.upper()}{request_path}{body}".encode("utf-8")
        digest = hmac.new(self.credentials.api_secret.encode("utf-8"), message, hashlib.sha256).digest()
        return base64.b64encode(digest).decode("utf-8")

    def _request(self, method: str, path: str, params: dict[str, Any] | None = None, body: dict[str, Any] | None = None) -> dict[str, Any]:
        query = f"?{urlencode(params)}" if params else ""
        request_path = f"{path}{query}"
        body_text = json.dumps(body, separators=(",", ":")) if body else ""
        timestamp = self._timestamp()
        headers = {
            "OK-ACCESS-KEY": self.credentials.api_key,
            "OK-ACCESS-SIGN": self._sign(timestamp, method, request_path, body_text),
            "OK-ACCESS-TIMESTAMP": timestamp,
            "OK-ACCESS-PASSPHRASE": self.credentials.passphrase,
            "Content-Type": "application/json",
        }
        if self.credentials.simulated:
            headers["x-simulated-trading"] = "1"

        request = Request(
            url=f"{self.base_url}{request_path}",
            data=body_text.encode("utf-8") if body_text else None,
            headers=headers,
            method=method.upper(),
        )
        try:
            with urlopen(request, timeout=15) as response:
                payload = json.load(response)
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise OKXAPIError(f"HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise OKXAPIError(str(exc)) from exc

        if payload.get("code") not in {None, "0", 0}:
            raise OKXAPIError(payload.get("msg") or str(payload))
        return payload

    def fetch_balance(self) -> dict[str, Any]:
        return self._request("GET", "/api/v5/account/balance")

    def fetch_positions(self, inst_id: str) -> dict[str, Any]:
        return self._request("GET", "/api/v5/account/positions", params={"instId": inst_id})

    def fetch_account_snapshot(self, inst_id: str) -> dict[str, Any]:
        balance_payload = self.fetch_balance()
        positions_payload = self.fetch_positions(inst_id)

        account_rows = balance_payload.get("data") or [{}]
        account = account_rows[0] if account_rows else {}
        details = account.get("details") or []
        usdt_detail = next((item for item in details if item.get("ccy") == "USDT"), {})
        cash_balance = _safe_float(
            usdt_detail.get("cashBal")
            or usdt_detail.get("availBal")
            or usdt_detail.get("eq")
            or account.get("totalEq")
        )
        equity = _safe_float(account.get("totalEq") or usdt_detail.get("eqUsd") or usdt_detail.get("eq"))

        positions = positions_payload.get("data") or []
        target_position = next((row for row in positions if row.get("instId") == inst_id), None)
        position_qty = 0.0
        position_state = "flat"
        position_side = "空仓"
        if target_position:
            position_qty = abs(_safe_float(target_position.get("pos")))
            pos_side = (target_position.get("posSide") or "").lower()
            if pos_side == "long" or _safe_float(target_position.get("pos")) > 0:
                position_state = "long"
                position_side = "持多"
            elif pos_side == "short" or _safe_float(target_position.get("pos")) < 0:
                position_state = "short"
                position_side = "持空"

        return {
            "connected": True,
            "simulated": self.credentials.simulated,
            "equity": round(equity, 6),
            "cash": round(cash_balance, 6),
            "current_position_state": position_state,
            "current_position_qty": round(position_qty, 8),
            "position_side_label": position_side,
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "api_key_hint": _mask_key(self.credentials.api_key),
            "inst_id": inst_id,
            "error": None,
        }


class OKXAccountSession:
    def __init__(self) -> None:
        self._credentials: OKXCredentials | None = None
        self._lock = threading.Lock()
        self._cache: dict[str, Any] | None = None
        self._cache_ts: float = 0.0

    def is_authenticated(self) -> bool:
        with self._lock:
            return self._credentials is not None

    def set_credentials(self, credentials: OKXCredentials) -> None:
        with self._lock:
            self._credentials = credentials
            self._cache = None
            self._cache_ts = 0.0

    def clear(self) -> None:
        with self._lock:
            self._credentials = None
            self._cache = None
            self._cache_ts = 0.0

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            credentials = self._credentials
            cache = dict(self._cache) if self._cache else None
        return {
            "connected": credentials is not None,
            "simulated": credentials.simulated if credentials else False,
            "api_key_hint": _mask_key(credentials.api_key) if credentials else None,
            "account": cache,
        }

    def fetch_account_snapshot(self, inst_id: str, force: bool = False, ttl_seconds: float = 2.0) -> dict[str, Any]:
        with self._lock:
            credentials = self._credentials
            cache = self._cache
            cache_ts = self._cache_ts

        if credentials is None:
            return {
                "connected": False,
                "simulated": False,
                "equity": None,
                "cash": None,
                "current_position_state": "unauthorized",
                "current_position_qty": None,
                "position_side_label": "未授权",
                "updated_at": None,
                "api_key_hint": None,
                "inst_id": inst_id,
                "error": None,
            }

        if not force and cache and time.time() - cache_ts < ttl_seconds:
            return dict(cache)

        client = OKXPrivateRESTClient(credentials)
        snapshot = client.fetch_account_snapshot(inst_id)
        with self._lock:
            self._cache = dict(snapshot)
            self._cache_ts = time.time()
        return snapshot


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _mask_key(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 8:
        return value[0] + "***" + value[-1]
    return f"{value[:4]}***{value[-4:]}"
