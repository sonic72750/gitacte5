# -*- coding: utf-8 -*-

"""
Microsoft Graph API 檢查程式

需要的 GitHub Actions Secrets：
- ID_LIST
- KEY_LIST

可選：
- ID_LIST2
- KEY_LIST2

支援下列兩種 Secret 格式：

格式 1：
["client-id-1", "client-id-2"]

格式 2（相容舊設定）：
id_list = ["client-id-1", "client-id-2"]
"""

from __future__ import annotations

import ast
import os
import sys
import time
from pathlib import Path
from typing import Any

import requests


BASE_DIR = Path(__file__).resolve().parent
TOKEN_DIR = BASE_DIR / "token"
BACKUP_TOKEN_DIR = BASE_DIR / "backuptoken"

TOKEN_URL = (
    "https://login.microsoftonline.com/"
    "common/oauth2/v2.0/token"
)

REDIRECT_URI = "http://localhost:53682/"

CONNECT_TIMEOUT = 10
READ_TIMEOUT = 30
REQUEST_RETRIES = 2
RETRY_DELAY_SECONDS = 3

# 每個帳號執行幾輪。
# 建議保持 1，避免 workflow 執行太久。
ROUNDS = 1

# 每個帳號之間的短暫等待。
ACCOUNT_DELAY_SECONDS = 2

# 每個 API 之間的短暫等待。
API_DELAY_SECONDS = 1


# 使用較穩定、以讀取為主的 Microsoft Graph API。
# 某些端點是否成功仍取決於應用程式取得的權限。
GRAPH_ENDPOINTS = [
    (
        "個人資料",
        "https://graph.microsoft.com/v1.0/me"
        "?$select=id,displayName,userPrincipalName"
    ),
    (
        "OneDrive 資訊",
        "https://graph.microsoft.com/v1.0/me/drive"
        "?$select=id,driveType,quota"
    ),
    (
        "OneDrive 根目錄",
        "https://graph.microsoft.com/v1.0/me/drive/root"
        "?$select=id,name,webUrl"
    ),
    (
        "OneDrive 根目錄項目",
        "https://graph.microsoft.com/v1.0/me/drive/root/children"
        "?$top=1&$select=id,name"
    ),
    (
        "郵件資料夾",
        "https://graph.microsoft.com/v1.0/me/mailFolders"
        "?$top=1&$select=id,displayName"
    ),
    (
        "郵件",
        "https://graph.microsoft.com/v1.0/me/messages"
        "?$top=1&$select=id,subject,receivedDateTime"
    ),
    (
        "行事曆",
        "https://graph.microsoft.com/v1.0/me/calendars"
        "?$top=1&$select=id,name"
    ),
    (
        "行事曆事件",
        "https://graph.microsoft.com/v1.0/me/events"
        "?$top=1&$select=id,subject,start,end"
    ),
    (
        "聯絡人",
        "https://graph.microsoft.com/v1.0/me/contacts"
        "?$top=1&$select=id,displayName"
    ),
    (
        "SharePoint 根網站",
        "https://graph.microsoft.com/v1.0/sites/root"
        "?$select=id,name,webUrl"
    ),
]


class ConfigurationError(RuntimeError):
    """GitHub Secrets 或帳號設定錯誤。"""


class TokenRefreshError(RuntimeError):
    """Microsoft OAuth Token 更新失敗。"""


def log(message: str) -> None:
    """立即輸出訊息，避免 GitHub Actions 看起來沒有反應。"""
    print(message, flush=True)


def mask_text(value: str, visible: int = 4) -> str:
    """遮蔽 ID，避免完整內容出現在執行記錄中。"""
    value = value.strip()

    if len(value) <= visible * 2:
        return "*" * len(value)

    return f"{value[:visible]}...{value[-visible:]}"


def parse_list_secret(
    variable_name: str,
    required: bool = True,
) -> list[str]:
    """
    讀取 GitHub Actions Secret。

    支援：
    ["value1", "value2"]

    或：
    id_list = ["value1", "value2"]
    """
    raw_value = os.getenv(variable_name, "").strip()

    if not raw_value:
        if required:
            raise ConfigurationError(
                f"找不到 GitHub Secret：{variable_name}"
            )
        return []

    # 相容舊版 Secret，例如：
    # id_list = ["abc", "def"]
    if "=" in raw_value:
        left, right = raw_value.split("=", 1)

        if left.strip().isidentifier():
            raw_value = right.strip()

    try:
        parsed: Any = ast.literal_eval(raw_value)
    except (SyntaxError, ValueError) as exc:
        raise ConfigurationError(
            f"{variable_name} 格式錯誤。"
            "請使用 Python/JSON 陣列格式，例如："
            '["value1", "value2"]'
        ) from exc

    if not isinstance(parsed, (list, tuple)):
        raise ConfigurationError(
            f"{variable_name} 必須是陣列，"
            f"目前型別是 {type(parsed).__name__}"
        )

    result = [
        str(item).strip()
        for item in parsed
        if str(item).strip()
    ]

    if required and not result:
        raise ConfigurationError(
            f"{variable_name} 沒有任何有效內容"
        )

    return result


def validate_account_config(
    client_ids: list[str],
    client_secrets: list[str],
    group_name: str,
) -> None:
    """確認 Client ID 與 Client Secret 數量一致。"""
    if len(client_ids) != len(client_secrets):
        raise ConfigurationError(
            f"{group_name}設定數量不一致："
            f"Client ID 有 {len(client_ids)} 個，"
            f"Client Secret 有 {len(client_secrets)} 個"
        )


def read_refresh_token(
    token_directory: Path,
    account_index: int,
) -> str:
    """從 token/0.txt、token/1.txt 等檔案讀取 refresh token。"""
    token_path = token_directory / f"{account_index}.txt"

    if not token_path.exists():
        raise ConfigurationError(
            f"找不到 Token 檔案：{token_path}"
        )

    refresh_token = token_path.read_text(
        encoding="utf-8"
    ).strip()

    if not refresh_token:
        raise ConfigurationError(
            f"Token 檔案是空的：{token_path}"
        )

    return refresh_token


def safe_json(response: requests.Response) -> dict[str, Any]:
    """安全解析 JSON，避免非 JSON 回應讓程式直接崩潰。"""
    try:
        result = response.json()
    except ValueError:
        return {
            "raw_response": response.text[:500]
        }

    if isinstance(result, dict):
        return result

    return {
        "result": result
    }


def refresh_access_token(
    session: requests.Session,
    refresh_token: str,
    client_id: str,
    client_secret: str,
    account_index: int,
) -> tuple[str, str | None]:
    """
    使用 refresh token 換取 access token。

    回傳：
    (access_token, new_refresh_token)
    """
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": REDIRECT_URI,
    }

    try:
        response = session.post(
            TOKEN_URL,
            data=data,
            headers={
                "Content-Type":
                    "application/x-www-form-urlencoded"
            },
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
        )
    except requests.RequestException as exc:
        raise TokenRefreshError(
            f"帳號 {account_index} 無法連線至 Token endpoint："
            f"{exc}"
        ) from exc

    result = safe_json(response)

    access_token = result.get("access_token")

    if not response.ok or not access_token:
        error_code = result.get(
            "error",
            f"HTTP_{response.status_code}"
        )
        error_description = result.get(
            "error_description",
            result.get(
                "raw_response",
                "Microsoft 未回傳錯誤說明"
            ),
        )

        raise TokenRefreshError(
            f"帳號 {account_index} Token 更新失敗："
            f"HTTP {response.status_code}，"
            f"{error_code}：{error_description}"
        )

    new_refresh_token = result.get("refresh_token")

    return str(access_token), (
        str(new_refresh_token)
        if new_refresh_token
        else None
    )


def save_rotated_refresh_token(
    token_directory: Path,
    account_index: int,
    new_refresh_token: str | None,
) -> None:
    """
    Microsoft 若回傳新的 refresh token，
    就更新 runner 工作目錄中的 token 檔案。

    注意：是否 commit 回 Git 由 workflow 決定。
    """
    if not new_refresh_token:
        return

    token_path = token_directory / f"{account_index}.txt"

    token_path.write_text(
        new_refresh_token,
        encoding="utf-8",
    )

    log(
        f"帳號 {account_index} 已在 runner 中更新 "
        "refresh token 檔案"
    )


def extract_graph_error(
    response: requests.Response,
) -> str:
    """取得 Microsoft Graph 的錯誤訊息。"""
    result = safe_json(response)

    error = result.get("error")

    if isinstance(error, dict):
        code = error.get("code", "unknown_error")
        message = error.get(
            "message",
            "Microsoft Graph 未提供說明"
        )
        return f"{code}: {message}"

    if "raw_response" in result:
        return str(result["raw_response"])

    return response.text[:300]


def call_graph_api(
    session: requests.Session,
    access_token: str,
    endpoint_name: str,
    endpoint_url: str,
) -> tuple[bool, int]:
    """呼叫一個 Microsoft Graph API。"""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }

    last_response: requests.Response | None = None

    for attempt in range(1, REQUEST_RETRIES + 1):
        try:
            response = session.get(
                endpoint_url,
                headers=headers,
                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
            )

            last_response = response

        except requests.RequestException as exc:
            log(
                f"  ⚠️ {endpoint_name}："
                f"第 {attempt} 次連線失敗：{exc}"
            )

            if attempt < REQUEST_RETRIES:
                time.sleep(RETRY_DELAY_SECONDS)

            continue

        if response.status_code == 429:
            retry_after_raw = response.headers.get(
                "Retry-After",
                str(RETRY_DELAY_SECONDS),
            )

            try:
                retry_after = min(
                    int(retry_after_raw),
                    30,
                )
            except ValueError:
                retry_after = RETRY_DELAY_SECONDS

            log(
                f"  ⚠️ {endpoint_name}：HTTP 429，"
                f"{retry_after} 秒後重試"
            )

            if attempt < REQUEST_RETRIES:
                time.sleep(retry_after)

            continue

        if 500 <= response.status_code < 600:
            log(
                f"  ⚠️ {endpoint_name}："
                f"HTTP {response.status_code}，"
                f"第 {attempt} 次嘗試失敗"
            )

            if attempt < REQUEST_RETRIES:
                time.sleep(RETRY_DELAY_SECONDS)

            continue

        break

    if last_response is None:
        log(
            f"  ❌ {endpoint_name}："
            "沒有收到 HTTP 回應"
        )
        return False, 0

    status_code = last_response.status_code

    if 200 <= status_code < 300:
        log(
            f"  ✅ {endpoint_name}："
            f"HTTP {status_code}"
        )
        return True, status_code

    error_message = extract_graph_error(last_response)

    if status_code == 401:
        log(
            f"  ❌ {endpoint_name}："
            f"HTTP 401，Access Token 無效；"
            f"{error_message}"
        )
    elif status_code == 403:
        log(
            f"  ⚠️ {endpoint_name}："
            f"HTTP 403，應用程式缺少此 API 權限；"
            f"{error_message}"
        )
    else:
        log(
            f"  ❌ {endpoint_name}："
            f"HTTP {status_code}；"
            f"{error_message}"
        )

    return False, status_code


def process_account(
    session: requests.Session,
    client_id: str,
    client_secret: str,
    token_directory: Path,
    account_index: int,
    group_name: str,
    round_number: int,
) -> tuple[int, int]:
    """更新 Token 並檢查一個帳號的 Graph API。"""
    log("")
    log("=" * 68)
    log(
        f"{group_name}帳號 {account_index}，"
        f"第 {round_number} 輪"
    )
    log(
        f"Client ID：{mask_text(client_id)}"
    )
    log(
        "開始時間："
        f"{time.strftime('%Y-%m-%d %H:%M:%S')}"
    )

    refresh_token = read_refresh_token(
        token_directory,
        account_index,
    )

    log("正在更新 Access Token……")

    access_token, new_refresh_token = refresh_access_token(
        session=session,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        account_index=account_index,
    )

    log("✅ Access Token 更新成功")

    save_rotated_refresh_token(
        token_directory=token_directory,
        account_index=account_index,
        new_refresh_token=new_refresh_token,
    )

    success_count = 0
    failure_count = 0

    for endpoint_name, endpoint_url in GRAPH_ENDPOINTS:
        success, _ = call_graph_api(
            session=session,
            access_token=access_token,
            endpoint_name=endpoint_name,
            endpoint_url=endpoint_url,
        )

        if success:
            success_count += 1
        else:
            failure_count += 1

        if API_DELAY_SECONDS > 0:
            time.sleep(API_DELAY_SECONDS)

    log(
        f"{group_name}帳號 {account_index} 完成："
        f"成功 {success_count}，"
        f"失敗或無權限 {failure_count}"
    )

    return success_count, failure_count


def process_group(
    session: requests.Session,
    client_ids: list[str],
    client_secrets: list[str],
    token_directory: Path,
    group_name: str,
) -> tuple[int, int, int]:
    """處理主應用程式或備用應用程式帳號群組。"""
    total_success = 0
    total_failure = 0
    token_failure = 0

    for round_number in range(1, ROUNDS + 1):
        log("")
        log(
            f"開始執行{group_name}第 "
            f"{round_number}/{ROUNDS} 輪"
        )

        for account_index, (
            client_id,
            client_secret,
        ) in enumerate(zip(client_ids, client_secrets)):
            try:
                success_count, failure_count = (
                    process_account(
                        session=session,
                        client_id=client_id,
                        client_secret=client_secret,
                        token_directory=token_directory,
                        account_index=account_index,
                        group_name=group_name,
                        round_number=round_number,
                    )
                )

                total_success += success_count
                total_failure += failure_count

            except (
                ConfigurationError,
                TokenRefreshError,
            ) as exc:
                token_failure += 1
                log(
                    f"❌ {group_name}帳號 "
                    f"{account_index} 執行失敗：{exc}"
                )

            except Exception as exc:
                token_failure += 1
                log(
                    f"❌ {group_name}帳號 "
                    f"{account_index} 發生未預期錯誤："
                    f"{type(exc).__name__}: {exc}"
                )

            if ACCOUNT_DELAY_SECONDS > 0:
                time.sleep(ACCOUNT_DELAY_SECONDS)

    return total_success, total_failure, token_failure


def main() -> int:
    """程式進入點。"""
    log("Auto Api Super 開始")
    log(
        "執行時間："
        f"{time.strftime('%Y-%m-%d %H:%M:%S')}"
    )

    try:
        primary_ids = parse_list_secret(
            "ID_LIST",
            required=True,
        )
        primary_secrets = parse_list_secret(
            "KEY_LIST",
            required=True,
        )

        backup_ids = parse_list_secret(
            "ID_LIST2",
            required=False,
        )
        backup_secrets = parse_list_secret(
            "KEY_LIST2",
            required=False,
        )

        validate_account_config(
            primary_ids,
            primary_secrets,
            "主應用程式",
        )

        if backup_ids or backup_secrets:
            validate_account_config(
                backup_ids,
                backup_secrets,
                "備用應用程式",
            )

    except ConfigurationError as exc:
        log(f"❌ 設定錯誤：{exc}")
        return 2

    log(
        f"主應用程式帳號數：{len(primary_ids)}"
    )
    log(
        f"備用應用程式帳號數：{len(backup_ids)}"
    )

    session = requests.Session()

    total_success = 0
    total_failure = 0
    total_token_failure = 0

    try:
        success, failure, token_failure = process_group(
            session=session,
            client_ids=primary_ids,
            client_secrets=primary_secrets,
            token_directory=TOKEN_DIR,
            group_name="主應用程式",
        )

        total_success += success
        total_failure += failure
        total_token_failure += token_failure

        if backup_ids:
            success, failure, token_failure = process_group(
                session=session,
                client_ids=backup_ids,
                client_secrets=backup_secrets,
                token_directory=BACKUP_TOKEN_DIR,
                group_name="備用應用程式",
            )

            total_success += success
            total_failure += failure
            total_token_failure += token_failure

    finally:
        session.close()

    log("")
    log("=" * 68)
    log("Auto Api Super 執行完成")
    log(f"API 成功總數：{total_success}")
    log(
        f"API 失敗或權限不足總數："
        f"{total_failure}"
    )
    log(
        f"Token／帳號失敗總數："
        f"{total_token_failure}"
    )

    # Token 更新失敗一定讓 workflow 顯示失敗。
    if total_token_failure > 0:
        log(
            "❌ 至少一個帳號無法更新 Token，"
            "workflow 將回傳失敗"
        )
        return 1

    # 完全沒有任何 API 成功也視為失敗。
    if total_success == 0:
        log(
            "❌ 沒有任何 Microsoft Graph API 成功，"
            "請檢查 Token 與 API 權限"
        )
        return 1

    # 某些 API 回傳 403 通常只是沒有該項權限，
    # 只要至少有 API 成功，就完成執行。
    log("✅ 至少一個 API 成功，執行完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
