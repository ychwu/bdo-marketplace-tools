import asyncio
import json
import pickle
import random
import stat
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
TRADE_URL = "https://na-trade.naeu.playblackdesert.com"
GAME_TRADE_URL = "https://na-game-trade.naeu.playblackdesert.com"
ACCOUNT_URL = "https://account.pearlabyss.com"
LOGIN_URL = f"{ACCOUNT_URL}/en-US/Member/Login/LoginProcess"
FORM_CONTENT_TYPE = "application/x-www-form-urlencoded; charset=UTF-8"
MARKET_ACCEPT_LANGUAGE = "en-US,en;q=0.9,ko;q=0.8,zh-CN;q=0.7,zh;q=0.6"
MARKET_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/148.0.0.0 Safari/537.36"
)
MARKET_AJAX_HEADER = "XMLHttpRequest"


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


def marketplace_silver_balance(wallet_response):
    if not isinstance(wallet_response, dict):
        raise MarketplaceResponseError("marketplace wallet lookup returned an unexpected JSON shape")

    wallet_items = wallet_response.get("myWalletList", [])
    if wallet_items is None:
        wallet_items = []
    if not isinstance(wallet_items, list):
        raise MarketplaceResponseError("marketplace wallet lookup returned an invalid myWalletList")

    for item in wallet_items:
        if not isinstance(item, dict):
            continue
        if item.get("mainKey") == 1 and item.get("subKey") == 0 and item.get("name") == "Silver":
            try:
                return int(item["count"])
            except (KeyError, TypeError, ValueError) as exc:
                raise MarketplaceResponseError("marketplace wallet silver row had an invalid count") from exc

    return None


class APIHandler:
    def __init__(self):
        self.trade_url = TRADE_URL
        self.game_trade_url = GAME_TRADE_URL
        self.login_url = LOGIN_URL
        self.session = requests.Session()
        self.login_status = False
        self.email = None
        self.password = None
        self._session_lock = asyncio.Lock()

        self.load_session()

    def _trade_url(self):
        return getattr(self, "trade_url", TRADE_URL).rstrip("/")

    def _game_trade_url(self):
        return getattr(self, "game_trade_url", GAME_TRADE_URL).rstrip("/")

    def _market_headers(self, referer=None, *, origin=None, content_type=FORM_CONTENT_TYPE, ajax=False):
        headers = {
            "Accept": "*/*",
            "Accept-Language": MARKET_ACCEPT_LANGUAGE,
            "User-Agent": MARKET_USER_AGENT,
        }
        if content_type is not None:
            headers["Content-Type"] = content_type
        if origin is None:
            origin = self._trade_url()
        if origin:
            headers["Origin"] = origin
        if referer:
            headers["Referer"] = referer
        if ajax:
            headers["X-Requested-With"] = MARKET_AJAX_HEADER
        return headers

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
            "User-Agent": MARKET_USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": MARKET_ACCEPT_LANGUAGE,
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
                "hdAccountUrl": ACCOUNT_URL,
                "_isLinkingLogin": "false",
                "_returnUrl": f"{ACCOUNT_URL}/en-US/Member/Login/AuthorizeOauth?response_type=code&scope=profile&state={pastate}&client_id=client_id&redirect_uri={self._trade_url()}/Pearlabyss/Oauth2CallBack",
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
                "Origin": ACCOUNT_URL,
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
        url = f"{self._game_trade_url()}/GameTradeMarket/BuyItem"
        headers = self._market_headers(
            f"{self._trade_url()}/",
            origin=self._trade_url(),
            ajax=False,
        )

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

        url = f"{self._trade_url()}/Home/AppSessionRefresh"
        headers = self._market_headers(f"{self._trade_url()}/Home/list/hot", ajax=True)

        response = await self._session_request(
            "POST",
            url,
            "session refresh",
            headers=headers,
            data={"_isCalc": "false"},
        )
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
        self._restrict_session_file_permissions()

    def _restrict_session_file_permissions(self):
        try:
            SESSION_COOKIE_PATH.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass

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
        headers = self._market_headers(f"{self._trade_url()}/Home/list/hot", ajax=True)
        response = await self._session_request(
            "POST",
            f"{self._trade_url()}/Home/GetMyWalletList",
            "marketplace wallet lookup",
            headers=headers,
        )
        return self._json_response(response, "marketplace wallet lookup")
