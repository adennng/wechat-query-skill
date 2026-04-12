# Windows 使用说明

本文件说明 `wechat-query` 在 Windows 环境下的使用方式。主业务逻辑以 `SKILL.md` 为准，这里只补平台差异。

## 适用环境

- Windows 10 / 11
- Docker Desktop
- PowerShell 5.1 或 PowerShell 7

## 前提要求

- 已安装并启动 Docker Desktop
- `docker compose` 命令可用
- OpenClaw agent 可以访问当前工作空间

## Docker Desktop / WSL 前置检查

在 Windows 上真正开始测试前，先确认以下命令都能正常执行：

```powershell
docker --version
docker compose version
docker info
wsl --status
```

说明：

- 如果 `docker` 命令可用，但 `docker info` 中没有正常的 `Server:` 信息，则说明 Docker daemon 还没真正启动，此时不能继续部署
- 只有 `docker info` 显示出正常的 `Server:` 信息后，才可以继续后续部署和测试

## 部署命令

在 PowerShell 中执行：

```powershell
Set-Location <skill-dir>\services\wechat-download-api
Copy-Item env.example .env
docker compose down
docker compose up -d --build
```

如果网络较慢，可先修改 `.env` 中的镜像源配置。

## 基础镜像拉取问题

即使已经把 Debian 源和 pip 源改成更快的镜像源，也不代表 Docker Hub 的基础镜像一定能顺利拉下来。

如果第一次执行：

```powershell
docker compose up -d --build
```

卡在类似下面的步骤：

```text
FROM python:3.11-slim
```

建议先单独执行：

```powershell
docker pull python:3.11-slim
```

如果这一步能成功，再重新执行：

```powershell
docker compose up -d --build
```

这样更容易区分：

- 是 Docker Hub 基础镜像拉取问题
- 还是项目自身的构建问题

## 常用运维命令

```powershell
Set-Location <skill-dir>\services\wechat-download-api
docker compose ps
docker compose logs -f
docker compose restart
docker compose down
```

## 健康检查

```powershell
Invoke-RestMethod http://localhost:5000/api/health
Invoke-RestMethod http://localhost:5000/api/admin/status
```

## 巡检脚本

Windows 下使用：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\check_service_and_login.ps1
```

该脚本输出 JSON，字段结构与 Linux 版 `check_service_and_login.sh` 保持一致。

## 定时任务

优先使用 OpenClaw 自身的定时任务能力。

如果必须使用系统级调度：

- 使用 Windows 任务计划程序
- 调用 PowerShell 脚本而不是 `.sh`

## 数据库查询

复杂 SQL 查询仍然建议在容器内执行，不建议宿主机直接查询挂载出来的 `rss.db`。

推荐方式：

```powershell
docker exec wechat-download-api python -c "print('hello')"
```

## 二维码发送

Windows 下规则不变：

- 首次登录和重登都统一走服务端托管二维码链路
- 先下载二维码到 agent 可访问路径
- 再通过 `message` 工具的 `media` 参数发送图片
- 不允许把本地路径字符串直接发给用户

## 常见问题

### 1. `docker compose` 不可用

- 确认 Docker Desktop 已启动
- 确认 Docker Desktop 安装包含 Compose 插件

### 2. PowerShell 拒绝执行脚本

可用下面命令执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\check_service_and_login.ps1
```

### 3. 服务起来但接口访问失败

优先检查：

```powershell
docker compose ps
docker compose logs --tail 50
Invoke-RestMethod http://localhost:5000/api/health
```
