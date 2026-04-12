#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (C) 2026 tmwgsicp
# Licensed under the GNU Affero General Public License v3.0
# See LICENSE file in the project root for full license text.
# SPDX-License-Identifier: AGPL-3.0-only
"""
认证管理器 - FastAPI版本
管理微信登录凭证（Token、Cookie等）
"""

import os
import time
from pathlib import Path
from typing import Optional, Dict
from dotenv import load_dotenv
from utils.login_state_store import (
    ack_invalid_alert,
    clear_login_state,
    get_login_state,
    mark_login_invalid,
    mark_login_valid,
)

class AuthManager:
    """认证管理单例类"""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(AuthManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        # 设置.env文件路径（python-api目录下）
        self.base_dir = Path(__file__).parent.parent
        self.env_path = self.base_dir / ".env"
        
        # 加载环境变量
        self._load_credentials()
        self._initialized = True

    def _update_env_values(self, updates: Dict[str, str]) -> None:
        """原地更新 .env，避免 bind mount 单文件时 rename 失败。"""
        lines = []
        if self.env_path.exists():
            lines = self.env_path.read_text(encoding="utf-8").splitlines()

        found = set()
        new_lines = []
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in line:
                new_lines.append(line)
                continue

            key, _ = line.split("=", 1)
            key = key.strip()
            if key in updates:
                new_lines.append(f"{key}={updates[key]}")
                found.add(key)
            else:
                new_lines.append(line)

        for key, value in updates.items():
            if key not in found:
                new_lines.append(f"{key}={value}")

        content = "\n".join(new_lines).rstrip() + "\n"
        self.env_path.write_text(content, encoding="utf-8")
    
    def _load_credentials(self):
        """从.env文件加载凭证"""
        if self.env_path.exists():
            load_dotenv(self.env_path, override=True)
        
        self.credentials = {
            "token": os.getenv("WECHAT_TOKEN", ""),
            "cookie": os.getenv("WECHAT_COOKIE", ""),
            "fakeid": os.getenv("WECHAT_FAKEID", ""),
            "nickname": os.getenv("WECHAT_NICKNAME", ""),
            "expire_time": int(os.getenv("WECHAT_EXPIRE_TIME") or 0)
        }
    
    def save_credentials(self, token: str, cookie: str, fakeid: str, 
                        nickname: str, expire_time: int) -> bool:
        """
        保存凭证到.env文件
        
        Args:
            token: 微信Token
            cookie: 微信Cookie
            fakeid: 公众号ID
            nickname: 公众号名称
            expire_time: 过期时间（毫秒时间戳）
        
        Returns:
            保存是否成功
        """
        try:
            # 更新内存中的凭证
            self.credentials.update({
                "token": token,
                "cookie": cookie,
                "fakeid": fakeid,
                "nickname": nickname,
                "expire_time": expire_time
            })
            
            # 确保.env文件存在
            if not self.env_path.exists():
                self.env_path.touch()
            
            # 保存到.env文件
            self._update_env_values({
                "WECHAT_TOKEN": token,
                "WECHAT_COOKIE": cookie,
                "WECHAT_FAKEID": fakeid,
                "WECHAT_NICKNAME": nickname,
                "WECHAT_EXPIRE_TIME": str(expire_time),
            })
            mark_login_valid()
            
            print(f"✅ 凭证已保存到: {self.env_path}")
            return True
        except Exception as e:
            print(f"❌ 保存凭证失败: {e}")
            return False
    
    def get_credentials(self) -> Optional[Dict[str, any]]:
        """
        获取有效的凭证
        
        Returns:
            凭证字典，如果未登录则返回None
        """
        # 重新加载以获取最新的凭证
        self._load_credentials()
        
        if not self.credentials.get("token") or not self.credentials.get("cookie"):
            return None
        
        return self.credentials
    
    def get_token(self) -> Optional[str]:
        """获取Token"""
        creds = self.get_credentials()
        return creds["token"] if creds else None
    
    def get_cookie(self) -> Optional[str]:
        """获取Cookie"""
        creds = self.get_credentials()
        return creds["cookie"] if creds else None
    
    def get_status(self) -> Dict:
        """
        获取登录状态
        
        Returns:
            状态字典
        """
        # 重新加载凭证
        self._load_credentials()
        state = get_login_state()
        ttl_hours = int(os.getenv("WECHAT_LOGIN_ESTIMATED_TTL_HOURS", "96") or 96)
        ttl_ms = ttl_hours * 3600 * 1000
        last_login_time = int(state.get("last_login_time") or 0)
        estimated_expire_time = last_login_time + ttl_ms if last_login_time else 0
        current_time = int(time.time() * 1000)
        login_state = state.get("login_state") or "unknown"
        is_estimated_expired = estimated_expire_time > 0 and current_time > estimated_expire_time
        is_expired = login_state == "invalid" or is_estimated_expired
        if login_state == "invalid":
            status_text = "登录已失效，请重新登录"
        elif is_estimated_expired:
            status_text = "登录可能已过期，建议重新登录"
        elif self.credentials.get("token") and self.credentials.get("cookie"):
            status_text = "登录正常"
        else:
            status_text = "未登录，请先扫码登录"
        
        if not self.credentials.get("token") or not self.credentials.get("cookie"):
            return {
                "authenticated": False,
                "loggedIn": False,
                "account": "",
                "nickname": "",
                "fakeid": "",
                "expireTime": estimated_expire_time,
                "estimatedExpireTime": estimated_expire_time,
                "estimatedRemainingSeconds": max(0, (estimated_expire_time - current_time) // 1000) if estimated_expire_time else 0,
                "isExpired": is_expired,
                "loginState": login_state,
                "lastLoginTime": last_login_time,
                "lastInvalidTime": int(state.get("last_invalid_time") or 0),
                "lastInvalidReason": state.get("last_invalid_reason", ""),
                "invalidAlertPending": bool(state.get("invalid_alert_pending", 0)),
                "status": status_text
            }

        return {
            "authenticated": True,
            "loggedIn": True,
            "account": self.credentials.get("nickname", ""),
            "nickname": self.credentials.get("nickname", ""),
            "fakeid": self.credentials.get("fakeid", ""),
            "expireTime": estimated_expire_time,
            "estimatedExpireTime": estimated_expire_time,
            "estimatedRemainingSeconds": max(0, (estimated_expire_time - current_time) // 1000) if estimated_expire_time else 0,
            "isExpired": is_expired,
            "loginState": login_state,
            "lastLoginTime": last_login_time,
            "lastInvalidTime": int(state.get("last_invalid_time") or 0),
            "lastInvalidReason": state.get("last_invalid_reason", ""),
            "invalidAlertPending": bool(state.get("invalid_alert_pending", 0)),
            "status": status_text
        }
    
    def clear_credentials(self) -> bool:
        """
        清除凭证
        
        Returns:
            清除是否成功
        """
        try:
            # 清除内存中的凭证
            self.credentials = {
                "token": "",
                "cookie": "",
                "fakeid": "",
                "nickname": "",
                "expire_time": 0
            }
            
            # 清除进程环境变量中残留的凭证
            env_keys = [
                "WECHAT_TOKEN", "WECHAT_COOKIE", "WECHAT_FAKEID",
                "WECHAT_NICKNAME", "WECHAT_EXPIRE_TIME"
            ]
            for key in env_keys:
                os.environ.pop(key, None)
            
            # 清空 .env 文件中的凭证字段（保留其他配置）
            if self.env_path.exists():
                self._update_env_values({key: "" for key in env_keys})
                print(f"✅ 凭证已清除: {self.env_path}")
            clear_login_state()
            
            return True
        except Exception as e:
            print(f"❌ 清除凭证失败: {e}")
            return False

    def mark_invalid(self, source: str, reason: str) -> bool:
        """统一标记登录失效。"""
        return mark_login_invalid(source, reason)

    def ack_invalid_alert(self) -> None:
        """确认失效提醒已处理。"""
        ack_invalid_alert()

# 创建全局单例
auth_manager = AuthManager()
