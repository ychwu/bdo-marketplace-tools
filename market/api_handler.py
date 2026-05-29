import asyncio
import json
import pickle
import random
from pathlib import Path

import requests

from market.decoder import unpack


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SESSION_COOKIE_PATH = PROJECT_ROOT / "resources" / "session.json"
LEGACY_SESSION_PATHS = (
    PROJECT_ROOT / "resources" / "session.pkl",
    PROJECT_ROOT / "session.pkl",
)
REQUEST_TIMEOUT = (5, 20)


class MarketplaceAPIError(RuntimeError):
    pass


class MarketplaceNetworkError(MarketplaceAPIError):
    pass


class MarketplaceResponseError(MarketplaceAPIError):
    pass


PURCHASE_RESULT_REASONS = {
    34: "item was unavailable or would create a duplicate pre-order",
    -14: "price mismatch",
    2000: "login session expired",
}


def purchase_result_message(result_code, item_id, price):
    if result_code == 0:
        return f"Purchase request succeeded for {item_id} at {price} silver."

    reason = PURCHASE_RESULT_REASONS.get(result_code)
    if reason:
        return f"Purchase failed for {item_id} at {price} silver: {reason}."
    return f"Purchase failed for {item_id} at {price} silver: resultCode {result_code}."


class APIHandler:
    def __init__(self):
        self.trade_url = "https://na-trade.naeu.playblackdesert.com"
        self.login_url = "https://account.pearlabyss.com/en-US/Member/Login/LoginProcess"
        self.session = requests.Session()
        self.login_status = False
        self.email = None
        self.password = None
        self._session_lock = asyncio.Lock()

        self.load_session()

    async def _request(self, client, method, url, context, **kwargs):
        request_kwargs = dict(kwargs)
        request_kwargs.setdefault("timeout", REQUEST_TIMEOUT)

        def send_request():
            try:
                response = client.request(method, url, **request_kwargs)
                response.raise_for_status()
                return response
            except requests.Timeout as exc:
                raise MarketplaceNetworkError(f"{context} timed out") from exc
            except requests.RequestException as exc:
                raise MarketplaceNetworkError(f"{context} failed: {exc}") from exc

        return await asyncio.to_thread(send_request)

    async def _session_request(self, method, url, context, **kwargs):
        async with self._session_lock:
            return await self._request(self.session, method, url, context, **kwargs)

    def _json_response(self, response, context):
        try:
            data = response.json()
        except ValueError as exc:
            raise MarketplaceResponseError(f"{context} returned invalid JSON") from exc

        if not isinstance(data, dict):
            raise MarketplaceResponseError(f"{context} returned an unexpected JSON shape")
        return data

    def _extract_cookie_dict(self, response=None):
        cookies = {}
        cookies.update(self.session.cookies.get_dict())

        if response is not None:
            request_cookies = getattr(response.request, "_cookies", None)
            if request_cookies is not None:
                cookies.update(request_cookies.get_dict())
            cookies.update(response.cookies.get_dict())

        return cookies

    async def check_stock(self):
        url = "https://na-trade.naeu.playblackdesert.com/Trademarket/GetWorldMarketList"
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "BlackDesert",
        }
        payload_male = {
            "keyType": 0,
            "mainCategory": 55,
            "subCategory": 1,
        }
        payload_female = {
            "keyType": 0,
            "mainCategory": 55,
            "subCategory": 2,
        }

        response_male, response_female = await asyncio.gather(
            self._request(
                requests,
                "POST",
                url,
                "male outfit stock check",
                json=payload_male,
                headers=headers,
            ),
            self._request(
                requests,
                "POST",
                url,
                "female outfit stock check",
                json=payload_female,
                headers=headers,
            ),
        )

        return (
            self._parse_world_market_response(response_male.content, "male outfit stock")
            + self._parse_world_market_response(response_female.content, "female outfit stock")
        )

    def _parse_world_market_response(self, content, context):
        try:
            decoded = unpack(content)
        except Exception as exc:
            raise MarketplaceResponseError(f"{context} response could not be decoded") from exc

        buy_list = []
        for row in decoded.split("|"):
            if not row:
                continue

            parts = row.split("-")
            if len(parts) <= 3:
                raise MarketplaceResponseError(f"{context} row had an unexpected shape: {row}")

            item_id, stock, price = parts[0], parts[1], parts[3]
            try:
                stock_count = int(stock)
            except ValueError as exc:
                raise MarketplaceResponseError(f"{context} row had invalid stock: {row}") from exc

            if stock_count > 0:
                buy_list.append([item_id, str(stock_count), price])

        return buy_list

    async def login(self):
        new_session = requests.Session()
        headers_pastate = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

        async with self._session_lock:
            response_login_page = await self._request(
                new_session,
                "GET",
                self.trade_url,
                "login page request",
                headers=headers_pastate,
            )
            self.session = new_session
            login_page_cookies = self._extract_cookie_dict(response_login_page)
            pastate = login_page_cookies.get("PA-STATE")
            if not pastate:
                raise MarketplaceResponseError("login page did not provide PA-STATE")

            login_payload = {
                "hdAccountUrl": "https://account.pearlabyss.com",
                "_isLinkingLogin": "false",
                "_returnUrl": f"https://account.pearlabyss.com/en-US/Member/Login/AuthorizeOauth?response_type=code&scope=profile&state={pastate}&client_id=client_id&redirect_uri=https://na-trade.naeu.playblackdesert.com/Pearlabyss/Oauth2CallBack",
                "_joinType": 1,
                "_email": self.email,
                "_password": self.password,
                "_isIpCheck": "false",
            }

            headers_login = {
                "User-Agent": headers_pastate["User-Agent"],
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": headers_pastate["Accept"],
                "Accept-Language": headers_pastate["Accept-Language"],
                "Origin": "https://account.pearlabyss.com",
            }

            response_login = await self._request(
                self.session,
                "POST",
                self.login_url,
                "login request",
                data=login_payload,
                headers=headers_login,
            )
            login_cookies = self._extract_cookie_dict(response_login)

        if "TradeAuth_Session" in login_cookies and "__RequestVerificationToken" in login_cookies:
            self.login_status = True
            return 1

        self.login_status = False
        return 0

    async def ensure_session_valid(self):
        status = await self.is_session_expired()
        if status == 0:
            self.login_status = True
            return True

        self.login_status = False
        if not self.email or not self.password:
            return False

        if await self.login() == 1:
            self.login_status = True
            self.save_session()
            return True

        self.login_status = False
        return False

    async def buy_item(self, buy_list):
        url = "https://na-game-trade.naeu.playblackdesert.com/GameTradeMarket/BuyItem"
        headers = {
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9,ko;q=0.8,zh-CN;q=0.7,zh;q=0.6",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        }

        summary = {
            "attempted": 0,
            "purchased": 0,
            "events": [],
            "purchase_records": [],
            "results": [],
        }

        try:
            session_valid = await self.ensure_session_valid()
        except MarketplaceAPIError as exc:
            summary["events"].append({"level": "error", "message": f"Purchase aborted: {exc}"})
            return summary

        if not session_valid:
            summary["events"].append(
                {
                    "level": "error",
                    "message": "Purchase aborted: login session is invalid and re-authentication failed.",
                }
            )
            return summary

        for item in buy_list:
            item_id, stock, price = item[0], item[1], item[2]
            try:
                stock_count = int(stock)
            except ValueError as exc:
                raise MarketplaceResponseError(f"purchase row had invalid stock: {item}") from exc

            for _ in range(stock_count):
                payload = {
                    "buyMainKey": item_id,
                    "buySubKey": "0",
                    "buyKeyType": "0",
                    "isWaitItem": "false",
                    "otp": "",
                    "retryBiddingNo": "",
                    "buyPrice": price,
                    "buyCount": "1",
                    "buyChooseKey": "0",
                }
                summary["attempted"] += 1
                response = await self._session_request(
                    "POST",
                    url,
                    "purchase request",
                    headers=headers,
                    data=payload,
                )
                response_json = self._json_response(response, "purchase request")
                result_code = self._purchase_result_code(response_json)

                result_record = {
                    "item_id": item_id,
                    "price": int(price),
                    "count": 1,
                    "result_code": result_code,
                    "response": response_json,
                }
                summary["results"].append(result_record)

                if result_code == 0:
                    summary["purchased"] += 1
                    purchase_record = {
                        "item_id": item_id,
                        "price": int(price),
                        "count": 1,
                        "result_code": result_code,
                    }
                    summary["purchase_records"].append(purchase_record)
                    summary["events"].append(
                        {
                            "level": "success",
                            "message": purchase_result_message(result_code, item_id, price),
                        }
                    )
                    await asyncio.sleep(random.uniform(1, 2.5))
                    continue

                if result_code == 2000:
                    summary["events"].append(
                        {"level": "warning", "message": "Login session expired. Attempting to re-authenticate."}
                    )
                    try:
                        reauthenticated = await self.ensure_session_valid()
                    except MarketplaceAPIError as exc:
                        summary["events"].append({"level": "error", "message": f"Re-authentication failed: {exc}"})
                        return summary

                    if reauthenticated:
                        summary["events"].append({"level": "success", "message": "Re-authentication succeeded."})
                        continue

                    summary["events"].append({"level": "error", "message": "Re-authentication failed."})
                    return summary

                summary["events"].append(
                    {
                        "level": "warning",
                        "message": purchase_result_message(result_code, item_id, price),
                    }
                )
                break

        return summary

    def _purchase_result_code(self, response_json):
        if "resultCode" not in response_json:
            raise MarketplaceResponseError("purchase response did not include resultCode")
        try:
            return int(response_json["resultCode"])
        except (TypeError, ValueError) as exc:
            raise MarketplaceResponseError("purchase response had an invalid resultCode") from exc

    async def is_session_expired(self):
        if not self.session.cookies:
            return -1

        url = "https://na-trade.naeu.playblackdesert.com/Home/AppSessionRefresh"
        headers = {
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": "https://na-trade.naeu.playblackdesert.com",
            "Referer": "https://na-trade.naeu.playblackdesert.com/Home/list/hot",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        }

        response = await self._session_request("POST", url, "session refresh", headers=headers)
        response_json = self._json_response(response, "session refresh")
        if "_resultCode" not in response_json:
            raise MarketplaceResponseError("session refresh response did not include _resultCode")

        return 0 if response_json["_resultCode"] == 0 else -1

    def save_session(self):
        SESSION_COOKIE_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "cookies": self._serialize_cookies(),
        }
        with SESSION_COOKIE_PATH.open("w", encoding="utf-8") as file:
            json.dump(payload, file, indent=2)
            file.write("\n")

    def _serialize_cookies(self):
        cookies = []
        for cookie in self.session.cookies:
            cookies.append(
                {
                    "name": cookie.name,
                    "value": cookie.value,
                    "domain": cookie.domain,
                    "path": cookie.path,
                    "secure": cookie.secure,
                    "expires": cookie.expires,
                }
            )
        return cookies

    def load_session(self):
        self.session = requests.Session()
        if SESSION_COOKIE_PATH.exists():
            try:
                with SESSION_COOKIE_PATH.open("r", encoding="utf-8-sig") as file:
                    payload = json.load(file)
                self._load_cookies(payload.get("cookies", []))
                return 0
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                pass

        for legacy_path in LEGACY_SESSION_PATHS:
            if not legacy_path.exists():
                continue
            try:
                with legacy_path.open("rb") as file:
                    legacy_session = pickle.load(file)
                if isinstance(legacy_session, requests.Session):
                    self.session = legacy_session
                    self.save_session()
                    return 0
            except Exception:
                if not SESSION_COOKIE_PATH.exists():
                    self.save_session()
                return -1

        if not SESSION_COOKIE_PATH.exists():
            self.save_session()
        return -1

    def _load_cookies(self, cookies):
        jar = requests.cookies.RequestsCookieJar()
        for cookie in cookies:
            name = cookie.get("name")
            value = cookie.get("value")
            if not name or value is None:
                continue

            kwargs = {
                "name": name,
                "value": value,
                "path": cookie.get("path") or "/",
                "secure": bool(cookie.get("secure")),
            }
            if cookie.get("domain"):
                kwargs["domain"] = cookie["domain"]
            if cookie.get("expires"):
                kwargs["expires"] = cookie["expires"]

            jar.set_cookie(requests.cookies.create_cookie(**kwargs))

        self.session.cookies.update(jar)

    async def get_mp_inventory(self):
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
        }
        response = await self._session_request(
            "POST",
            "https://na-trade.naeu.playblackdesert.com/Home/GetMyWalletList",
            "marketplace wallet lookup",
            headers=headers,
        )
        return self._json_response(response, "marketplace wallet lookup")
