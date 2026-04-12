#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (C) 2026 tmwgsicp
# Licensed under the GNU Affero General Public License v3.0
# See LICENSE file in the project root for full license text.
# SPDX-License-Identifier: AGPL-3.0-only
"""
服务端托管的重登会话。
供 skill 直接获取二维码并轮询状态，不依赖浏览器 Cookie 会话。
"""

import os
import re
import time
from pathlib import Path
from typing import Any, Dict
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import httpx

from utils.auth_manager import auth_manager
from utils.webhook import webhook

MP_BASE_URL = "https://mp.weixin.qq.com"
QR_ENDPOINT = f"{MP_BASE_URL}/cgi-bin/scanloginqrcode"
BIZ_LOGIN_ENDPOINT = f"{MP_BASE_URL}/cgi-bin/bizlogin"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://mp.weixin.qq.com/",
    "Origin": "https://mp.weixin.qq.com",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


class ReloginManager:
    def __init__(self):
        self._sessions: dict[str, Dict[str, Any]] = {}
        self._base_dir = Path(__file__).resolve().parent.parent
        self._qrcode_dir = self._base_dir / "static" / "qrcodes"
        self._qrcode_dir.mkdir(parents=True, exist_ok=True)

    async def start(self) -> Dict[str, Any]:
        request_id = uuid4().hex
        sessionid = f"{int(time.time() * 1000)}{request_id[:6]}"
        client = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers=DEFAULT_HEADERS.copy(),
        )
        try:
            body = {
                "userlang": "zh_CN",
                "redirect_url": "",
                "login_type": 3,
                "sessionid": sessionid,
                "token": "",
                "lang": "zh_CN",
                "f": "json",
                "ajax": 1,
            }
            resp = await client.post(
                BIZ_LOGIN_ENDPOINT,
                params={"action": "startlogin"},
                data=body,
            )
            resp.raise_for_status()

            qr_resp = await client.get(
                QR_ENDPOINT,
                params={
                    "action": "getqrcode",
                    "random": int(time.time() * 1000),
                },
            )
            qr_resp.raise_for_status()

            content = qr_resp.content
            if not content:
                raise ValueError("empty qrcode response")

            media_type = qr_resp.headers.get("content-type", "image/png")
            is_png = content.startswith(b"\x89PNG")
            is_jpeg = content.startswith(b"\xff\xd8\xff")
            is_image = "image" in media_type or is_png or is_jpeg
            if not is_image:
                raise ValueError("qrcode endpoint did not return image content")
            suffix = ".png"
            if is_jpeg or "jpeg" in media_type:
                suffix = ".jpg"
                media_type = "image/jpeg"
            elif is_png or "png" in media_type:
                media_type = "image/png"

            qrcode_path = self._qrcode_dir / f"relogin_{request_id}{suffix}"
            qrcode_path.write_bytes(content)

            session = {
                "request_id": request_id,
                "sessionid": sessionid,
                "created_at": int(time.time() * 1000),
                "status": "waiting_scan",
                "message": "请使用微信公众号管理员微信扫码",
                "client": client,
                "qrcode_path": str(qrcode_path),
                "qrcode_media_type": media_type,
                "account": "",
                "fakeid": "",
                "completed_at": 0,
            }
            self._sessions[request_id] = session

            return self._public_session(session)
        except Exception:
            await client.aclose()
            raise

    async def get_status(self, request_id: str) -> Dict[str, Any]:
        session = self._sessions.get(request_id)
        if not session:
            raise KeyError(request_id)

        if session["status"] in {"success", "expired", "failed", "cancelled"}:
            return self._public_session(session)

        client: httpx.AsyncClient = session["client"]
        resp = await client.get(
            QR_ENDPOINT,
            params={
                "action": "ask",
                "token": "",
                "lang": "zh_CN",
                "f": "json",
                "ajax": 1,
            },
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("base_resp", {}).get("ret") != 0:
            session["status"] = "failed"
            session["message"] = "检查扫码状态失败"
            await self._close_client(session)
            return self._public_session(session)

        wx_status = data.get("status", 0)
        if wx_status == 1:
            await self._complete_login(session)
        elif wx_status in (4, 6):
            if (data.get("acct_size") or 0) > 1:
                session["status"] = "scanned_wait_select"
                session["message"] = "已扫码，请在手机上选择公众号账号"
            else:
                session["status"] = "scanned_wait_confirm"
                session["message"] = "已扫码，请在手机上确认登录"
        elif wx_status == 2:
            session["status"] = "expired"
            session["message"] = "二维码已过期"
            await self._close_client(session)
        elif wx_status == 3:
            session["status"] = "failed"
            session["message"] = "扫码失败，请重新发起"
            await self._close_client(session)
        else:
            session["status"] = "waiting_scan"
            session["message"] = "等待扫码"

        return self._public_session(session)

    async def cancel(self, request_id: str) -> Dict[str, Any]:
        session = self._sessions.get(request_id)
        if not session:
            raise KeyError(request_id)
        session["status"] = "cancelled"
        session["message"] = "重登会话已取消"
        await self._close_client(session)
        return self._public_session(session)

    def get_qrcode_path(self, request_id: str) -> Path:
        session = self._sessions.get(request_id)
        if not session:
            raise KeyError(request_id)
        return Path(session["qrcode_path"])

    def get_qrcode_media_type(self, request_id: str) -> str:
        session = self._sessions.get(request_id)
        if not session:
            raise KeyError(request_id)
        return session.get("qrcode_media_type", "image/png")

    async def _complete_login(self, session: Dict[str, Any]) -> None:
        client: httpx.AsyncClient = session["client"]
        login_data = {
            "userlang": "zh_CN",
            "redirect_url": "",
            "cookie_forbidden": 0,
            "cookie_cleaned": 0,
            "plugin_used": 0,
            "login_type": 3,
            "token": "",
            "lang": "zh_CN",
            "f": "json",
            "ajax": 1,
        }
        resp = await client.post(
            BIZ_LOGIN_ENDPOINT,
            params={"action": "login"},
            data=login_data,
        )
        resp.raise_for_status()
        result = resp.json()

        if result.get("base_resp", {}).get("ret") != 0:
            session["status"] = "failed"
            session["message"] = result.get("base_resp", {}).get("err_msg", "登录失败")
            await self._close_client(session)
            return

        redirect_url = result.get("redirect_url", "")
        token = parse_qs(urlparse(f"http://localhost{redirect_url}").query).get("token", [""])[0]
        if not token:
            session["status"] = "failed"
            session["message"] = "未获取到 token"
            await self._close_client(session)
            return

        cookie_str = "; ".join([f"{k}={v}" for k, v in client.cookies.items()])
        nickname, fakeid = await self._fetch_account_info(client, token, cookie_str)

        ttl_hours = int(os.getenv("WECHAT_LOGIN_ESTIMATED_TTL_HOURS", "96") or 96)
        expire_time = int((time.time() + ttl_hours * 3600) * 1000)
        auth_manager.save_credentials(
            token=token,
            cookie=cookie_str,
            fakeid=fakeid,
            nickname=nickname,
            expire_time=expire_time,
        )
        await webhook.notify("login_success", {"nickname": nickname, "fakeid": fakeid})

        session["status"] = "success"
        session["message"] = "重新登录成功"
        session["account"] = nickname
        session["fakeid"] = fakeid
        session["completed_at"] = int(time.time() * 1000)
        await self._close_client(session)

    async def _fetch_account_info(
        self, client: httpx.AsyncClient, token: str, cookie_str: str
    ) -> tuple[str, str]:
        nickname = "公众号"
        fakeid = ""
        common_headers = {
            "Cookie": cookie_str,
            "User-Agent": DEFAULT_HEADERS["User-Agent"],
        }

        info_response = await client.get(
            f"{MP_BASE_URL}/cgi-bin/home",
            params={"t": "home/index", "token": token, "lang": "zh_CN"},
            headers=common_headers,
        )
        html = info_response.text
        nick_match = re.search(r'nick_name\s*[:=]\s*["\']([^"\']+)["\']', html)
        if nick_match:
            nickname = nick_match.group(1)

        try:
            search_response = await client.get(
                f"{MP_BASE_URL}/cgi-bin/searchbiz",
                params={
                    "action": "search_biz",
                    "token": token,
                    "lang": "zh_CN",
                    "f": "json",
                    "ajax": 1,
                    "random": time.time(),
                    "query": nickname,
                    "begin": 0,
                    "count": 5,
                },
                headers=common_headers,
            )
            search_result = search_response.json()
            if search_result.get("base_resp", {}).get("ret") == 0:
                accounts = search_result.get("list", [])
                for account in accounts:
                    if account.get("nickname") == nickname:
                        fakeid = account.get("fakeid", "")
                        break
                if not fakeid and accounts:
                    fakeid = accounts[0].get("fakeid", "")
        except Exception:
            pass

        return nickname, fakeid

    async def _close_client(self, session: Dict[str, Any]) -> None:
        client = session.get("client")
        if client is not None:
            await client.aclose()
            session["client"] = None

    def _public_session(self, session: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "request_id": session["request_id"],
            "status": session["status"],
            "message": session["message"],
            "qrcode_path": session["qrcode_path"],
            "created_at": session["created_at"],
            "completed_at": session.get("completed_at", 0),
            "account": session.get("account", ""),
            "fakeid": session.get("fakeid", ""),
        }


relogin_manager = ReloginManager()
