# -*- coding: UTF-8 -*-
import requests as req
import json,sys,time,random


dd2=[1]
id_list2=[1]






 


def gettoken(refresh_token):
    headers = {
        "Content-Type": "application/x-www-form-urlencoded"
    }

    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token.strip(),
        "client_id": id_lists[a],
        "client_secret": secret_lists[a],
        "redirect_uri": "http://localhost:53682/"
    }

    response = req.post(
        "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        data=data,
        headers=headers,
        timeout=30
    )

    try:
        result = response.json()
    except ValueError:
        raise RuntimeError(
            f"Token endpoint returned non-JSON response, "
            f"HTTP {response.status_code}: {response.text[:500]}"
        )

    if not response.ok or "access_token" not in result:
        error = result.get("error", "unknown_error")
        description = result.get(
            "error_description",
            "No error_description returned"
        )

        # 不輸出 client_secret 或 refresh_token
        raise RuntimeError(
            f"Account index {a} token refresh failed: "
            f"HTTP {response.status_code}, {error}: {description}"
        )

    new_refresh_token = result.get("refresh_token", refresh_token)

    with open(path, "w", encoding="utf-8") as file:
        file.write(new_refresh_token)

    return result["access_token"]
