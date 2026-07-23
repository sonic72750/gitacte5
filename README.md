# Auto Api Super 使用與維護說明

此專案透過 GitHub Actions 執行 Python 程式，使用 Microsoft Entra 應用程式的 OAuth 2.0 Refresh Token 取得 Access Token，再測試 Microsoft Graph API。

> **重要安全提醒**
>
> - 不要把 Client Secret、Refresh Token、Authorization Code 貼到 Issue、README、Actions Log 或公開儲存庫。
> - 若儲存庫是 Public，請勿把 `token/0.txt` 提交到 Git。
> - Client ID 可以公開，但 Client Secret 和 Refresh Token 必須視為密碼。
> - 憑證疑似外洩時，請立即撤銷工作階段、建立新 Client Secret，並重新取得 Refresh Token。

---

## 需要的 GitHub Actions Secrets

位置：

`Repository → Settings → Secrets and variables → Actions`

### `ID_LIST`

填入 Microsoft Entra 應用程式的 **Application (client) ID**。

只有一個應用程式時：

```json
["你的-Application-Client-ID"]
```

範例格式：

```json
["00000000-0000-0000-0000-000000000000"]
```

### `KEY_LIST`

填入 Microsoft Entra「憑證及祕密」中用戶端密碼的 **值（Value）**。

```json
["你的-Client-Secret-Value"]
```

注意：

- 必須使用 **值（Value）**
- 不可使用 **祕密識別碼（Secret ID）**
- 要保留中括號和半形雙引號
- `ID_LIST` 與 `KEY_LIST` 的項目數量和順序必須相同

多組應用程式時：

```json
["client-id-1", "client-id-2"]
```

```json
["client-secret-value-1", "client-secret-value-2"]
```

---

## Microsoft Entra 應用程式設定

位置：

`Microsoft Entra 系統管理中心 → 應用程式 → 應用程式註冊 → 選擇應用程式`

### 重新導向 URI

進入：

`Authentication / 驗證 → Platform configurations / 平台設定`

Web 平台應包含：

```text
http://localhost:53682/
```

必須完全一致，包括：

- `http`
- Port `53682`
- 最後的 `/`

### API 權限

最低測試權限可使用：

```text
User.Read
Files.Read.All
offline_access
```

其他 Graph API，例如郵件、行事曆、聯絡人或 SharePoint，需另外加入相應的委派權限，並視租戶設定完成管理員同意。

---

## 建立新的 Client Secret

位置：

`Microsoft Entra → 應用程式註冊 → 應用程式 → 憑證及祕密 → 用戶端密碼`

1. 按「新增用戶端密碼」
2. 輸入描述
3. 選擇到期時間
4. 按「新增」
5. 立即複製 **值（Value）**
6. 將新值更新到 GitHub Secret `KEY_LIST`

> Secret Value 只會完整顯示一次。離開頁面後無法再次查看。

---

## MFA 變更後重新取得 Refresh Token

若 GitHub Actions 顯示：

```text
AADSTS50079
```

代表帳號必須完成 MFA 註冊或重新互動式登入。

先完成 MFA，再重新取得 Refresh Token。

### 第 1 步：開啟登入授權頁

在 Windows PowerShell 執行：

```powershell
$tenant = "你的租戶網域，例如 contoso.onmicrosoft.com"
$clientId = "你的 Application Client ID"
$redirectUri = "http://localhost:53682/"
$scope = "offline_access User.Read Files.Read.All"

$authorizeUrl =
    "https://login.microsoftonline.com/$tenant/oauth2/v2.0/authorize" +
    "?client_id=$([uri]::EscapeDataString($clientId))" +
    "&response_type=code" +
    "&redirect_uri=$([uri]::EscapeDataString($redirectUri))" +
    "&response_mode=query" +
    "&scope=$([uri]::EscapeDataString($scope))" +
    "&prompt=consent"

Start-Process $authorizeUrl
```

接著：

1. 使用執行 API 的 Microsoft 365 帳號登入
2. 完成 MFA
3. 接受授權
4. 瀏覽器最後可能顯示 localhost 無法連線，這是正常的
5. 複製網址列中的完整網址

網址格式類似：

```text
http://localhost:53682/?code=很長的授權碼&session_state=...
```

### 第 2 步：從網址取得 Authorization Code

```powershell
$callbackUrl = Read-Host "貼上完整 localhost 網址"

if ($callbackUrl -notmatch '[?&]code=([^&#]+)') {
    throw "網址中找不到 authorization code"
}

$code = [System.Uri]::UnescapeDataString($Matches[1])

Write-Host "已取得 authorization code"
```

### 第 3 步：交換 Refresh Token

```powershell
$clientSecret = Read-Host "貼上 Client Secret 的 Value"

$body = @{
    client_id     = $clientId
    client_secret = $clientSecret.Trim()
    grant_type    = "authorization_code"
    code          = $code
    redirect_uri  = $redirectUri
    scope         = $scope
}

$result = Invoke-RestMethod `
    -Method Post `
    -Uri "https://login.microsoftonline.com/$tenant/oauth2/v2.0/token" `
    -ContentType "application/x-www-form-urlencoded" `
    -Body $body `
    -ErrorAction Stop

if ([string]::IsNullOrWhiteSpace($result.refresh_token)) {
    throw "Microsoft 沒有回傳 refresh_token"
}

$tokenFile = Join-Path ([Environment]::GetFolderPath("Desktop")) "0.txt"

[System.IO.File]::WriteAllText(
    $tokenFile,
    $result.refresh_token,
    [System.Text.UTF8Encoding]::new($false)
)

Write-Host "完成，新 Refresh Token 已儲存至：$tokenFile"
```

授權碼有效時間很短，而且只能使用一次。取得後請立即交換。

---

## 更新 Token 的建議方式

### 建議：存入 GitHub Actions Secret

將 Refresh Token 建立成 GitHub Secret，例如：

```text
REFRESH_TOKEN_0
```

Workflow 再於執行時寫入暫存檔，避免把 Token 提交至 Git。

### 不建議：提交 `token/0.txt`

若目前程式仍讀取：

```text
token/0.txt
```

至少要確保：

- Repository 是 Private
- `.gitignore` 包含 Token 檔案
- Token 沒有出現在 Git 歷史
- Actions Log 不會輸出 Token 內容

`.gitignore` 建議加入：

```gitignore
token/*.txt
backuptoken/*.txt
.env
```

> 單純加入 `.gitignore` 不會移除已經提交過的歷史內容。曾經公開的 Token 必須撤銷並重新產生。

---

## 執行 GitHub Actions

位置：

`Repository → Actions → Auto Api Super → Run workflow`

正常 Log 應包含：

```text
Auto Api Super 開始
正在更新 Access Token……
✅ Access Token 更新成功
✅ 個人資料：HTTP 200
Auto Api Super 執行完成
```

---

## 常見錯誤

### `AADSTS50079`

```text
Due to a configuration change ... you must enroll in multi-factor authentication
```

原因：

- 帳號需要完成 MFA 註冊
- 條件式存取要求重新驗證
- 登入位置或安全性設定變更

處理：

1. 完成 MFA
2. 重新互動式登入
3. 重新取得 Refresh Token

### `AADSTS7000215`

```text
Invalid client secret provided
```

原因：

- 使用了 Secret ID，而不是 Secret Value
- Secret 已過期
- Secret 被刪除
- 複製時多了空白或貼錯應用程式

處理：

1. 建立新的 Client Secret
2. 複製 **值（Value）**
3. 更新 GitHub Secret `KEY_LIST`
4. 重新取得 Refresh Token

### `invalid_grant`

可能原因：

- Refresh Token 已失效或被撤銷
- Authorization Code 已過期
- Authorization Code 已使用過
- MFA 或條件式存取要求重新登入
- Redirect URI 不一致

處理：

重新走完整互動式授權流程。

### `HTTP 401`

通常代表：

- Access Token 無效
- `Authorization` Header 缺少 `Bearer`
- Token 已過期或 Audience 不符

正確格式：

```python
headers = {
    "Authorization": f"Bearer {access_token}",
    "Accept": "application/json",
}
```

### `HTTP 403`

通常代表：

- 應用程式沒有該 API 權限
- 尚未完成管理員同意
- 使用者或租戶原則禁止存取

某些 API 回傳 403，不一定代表所有測試失敗。

### `AADSTS90002 Tenant not found`

原因：

- Tenant ID 輸入錯誤
- 使用了錯誤租戶
- 租戶已停用或不存在

可改用已確認存在的租戶網域：

```text
yourtenant.onmicrosoft.com
```

---

## Workflow 的 Python 快取錯誤

若出現：

```text
No file matched to requirements.txt or pyproject.toml
```

原因是 `actions/setup-python` 啟用了：

```yaml
cache: "pip"
```

但儲存庫沒有依賴檔案。

解法之一是移除：

```yaml
cache: "pip"
```

或新增 `requirements.txt`：

```text
requests>=2.32,<3
```

---

## 維護檢查表

每次憑證或帳號設定變更後，依序確認：

- [ ] Entra 應用程式仍為啟用狀態
- [ ] Redirect URI 是 `http://localhost:53682/`
- [ ] Client Secret 尚未到期
- [ ] GitHub `ID_LIST` 使用 Client ID
- [ ] GitHub `KEY_LIST` 使用 Secret Value
- [ ] Refresh Token 是完成 MFA 後重新取得的版本
- [ ] `Authorization` Header 包含 `Bearer`
- [ ] Token 未公開提交到 GitHub
- [ ] 手動執行一次 Auto Api Super
- [ ] Log 至少有一個 Graph API 回傳 HTTP 200

---

## 官方文件

- Microsoft identity platform OAuth 2.0 authorization code flow  
  https://learn.microsoft.com/entra/identity-platform/v2-oauth2-auth-code-flow
- Microsoft identity platform refresh tokens  
  https://learn.microsoft.com/entra/identity-platform/refresh-tokens
- Microsoft Entra 錯誤碼  
  https://learn.microsoft.com/entra/identity-platform/reference-error-codes
- 新增重新導向 URI  
  https://learn.microsoft.com/entra/identity-platform/how-to-add-redirect-uri

---

## 最後提醒

絕對不要公開下列內容：

```text
Client Secret Value
Refresh Token
Access Token
Authorization Code
```

任何一項曾經公開，都應視為已外洩並立即更換。
