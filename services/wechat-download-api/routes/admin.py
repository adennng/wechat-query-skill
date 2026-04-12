#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (C) 2026 tmwgsicp
# Licensed under the GNU Affero General Public License v3.0
# See LICENSE file in the project root for full license text.
# SPDX-License-Identifier: AGPL-3.0-only
"""
管理路由 - FastAPI版本
"""

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
from utils.auth_manager import auth_manager

router = APIRouter()

class StatusResponse(BaseModel):
    """状态响应模型"""
    authenticated: bool
    loggedIn: bool
    account: str
    nickname: Optional[str] = ""
    fakeid: Optional[str] = ""
    expireTime: Optional[int] = 0
    estimatedExpireTime: Optional[int] = 0
    estimatedRemainingSeconds: Optional[int] = 0
    isExpired: Optional[bool] = False
    loginState: Optional[str] = "unknown"
    lastLoginTime: Optional[int] = 0
    lastInvalidTime: Optional[int] = 0
    lastInvalidReason: Optional[str] = ""
    invalidAlertPending: Optional[bool] = False
    status: str

@router.get("/status", response_model=StatusResponse, summary="获取登录状态")
async def get_status():
    """
    获取当前登录状态
    
    Returns:
        登录状态信息
    """
    return auth_manager.get_status()

@router.post("/logout", summary="退出登录")
async def logout():
    """
    退出登录，清除凭证
    
    Returns:
        操作结果
    """
    success = auth_manager.clear_credentials()
    if success:
        return {"success": True, "message": "已退出登录"}
    else:
        return {"success": False, "message": "退出登录失败"}

@router.post("/ack-invalid-alert", summary="确认登录失效提醒已发送")
async def ack_login_invalid_alert():
    """供上层 skill 在发送提醒后确认，避免重复提醒。"""
    auth_manager.ack_invalid_alert()
    return {"success": True, "message": "已确认提醒"}
