# AirPlay 課堂投影控制面板

讓 Windows 電腦接收 iPad／iPhone 的螢幕鏡像（AirPlay），用於課堂投影。
核心使用 [uxplay-windows](https://github.com/leapbtw/uxplay-windows)（內建 [UxPlay](https://github.com/FDH2/UxPlay) 引擎），本專案以 Python（tkinter）提供中文控制面板。

## 功能

| 功能 | 說明 |
|---|---|
| 一鍵啟動／停止 | 啟動、停止、套用設定並重新啟動 uxplay-windows（含藍牙信標子程式） |
| 連線狀態 | 燈號：灰＝已停止、綠＝等待連線、藍＝投影中；顯示連線裝置 IP、投影時間、本機 IP |
| 自訂名稱 | 設定 iPad「螢幕鏡像輸出」清單中顯示的名稱（支援中文） |
| 畫質預設 | **高畫質**（1920×1080／60 格，預設）、**穩定**（1280×720／30 格）；也可個別調整 |
| 全螢幕 | 投影畫面以全螢幕顯示 |
| PIN 碼 | 連線時需輸入 4 位數 PIN，PIN 會大字顯示在面板上，可隨機產生 |
| 切換裝置 | 可選擇新裝置連線時直接取代目前的裝置 |
| 錄影 | 將投影畫面存成 `.h264` 檔（只有影像、無聲音） |
| 自動啟動 | 可設定開啟面板時自動啟動投影服務 |

## 系統需求

- Windows 10／11（64 位元）
- **Bonjour 服務**（安裝 iTunes 或 Apple 的 Bonjour Print Services 即會附帶）
- 電腦與 iPad 在**同一個網路**，且 Windows 網路類型設為「私人」
- 第一次啟動時，Windows 防火牆詢問請勾選「私人網路」並允許

## 安裝（使用打包好的 exe）

1. 準備一個資料夾，例如 `D:\AirPlayClassroom\`，放入 `AirPlayClassroom.exe`。
2. 下載 [uxplay-windows 2.0.0.1736](https://github.com/leapbtw/uxplay-windows/releases/latest)，解壓縮後放到 `vendor\uxplay-windows\`：

   ```
   AirPlayClassroom\
   ├─ AirPlayClassroom.exe
   └─ vendor\
      └─ uxplay-windows\
         ├─ uxplay-windows.exe
         └─ …（其他 dll 檔）
   ```

   若放在其他位置，可在面板「進階 → uxplay-windows 位置 → 變更…」指定。
3. 執行 `AirPlayClassroom.exe`。

## 使用方式

1. 開啟面板，按 **▶ 啟動投影服務**，燈號變綠色「等待連線」。
2. iPad：打開控制中心 →「螢幕鏡像輸出」→ 選擇面板上顯示的名稱。
3. 若有設 PIN，輸入面板右上角的紅色 4 位數字。
4. 連線成功後燈號變藍色「投影中」並開始計時。
5. 下課時按 **■ 停止**。

### 設定說明

- 修改名稱、畫質、全螢幕、PIN、錄影等設定後，要按 **⟳ 套用設定並重新啟動** 才會生效。
- **重新啟動會讓 iPad 斷線**，需在 iPad 上重新點選。建議在上課前調整好設定。
- 畫面卡頓或延遲明顯時，按「穩定（720p／30）」再套用；網路順暢時用「高畫質」。
  AirPlay 本身也會依網路狀況自動降低畫質，不會因此斷線。
- 錄影檔預設存在 `使用者\Videos\AirPlayRecordings\`，檔名為 `airplay_日期_時間.h264`，
  可用 [VLC](https://www.videolan.org/) 播放。錄影路徑不可包含空白，建議只用英文字元。
  需要連同聲音錄影時，可改用 Windows 內建的 Xbox Game Bar（`Win + Alt + R`）。
- 「其他 UxPlay 參數」可輸入任何 [UxPlay 參數](https://github.com/FDH2/UxPlay#usage)，
  完整清單見 `vendor\uxplay-windows\resources\uxplay_arguments_list.txt`。

## 常見問題

| 狀況 | 處理方式 |
|---|---|
| iPad 找不到電腦 | 確認同一網路、網路類型為「私人」、Bonjour 服務執行中；執行 `check_env.bat` 檢查 |
| 名稱改了沒生效 | 確認有按「套用設定並重新啟動」；若 `C:\ProgramData\uxplay-windows\arguments.txt` 存在，它會蓋過面板設定，請刪除 |
| 停止後 iPad 連不回來 | iOS 不會自動重連，請在 iPad 上重新選取 |
| 錄影沒有產生檔案 | 檔案在 iPad 開始投影後才會建立；確認路徑沒有空白或中文 |

## 開發

需要 Python 3.10 以上（含 tkinter），不需額外套件。

> 注意：若電腦上 `python` 指令指向其他程式（例如 Inkscape）內建的 Python，請改用 `py` 啟動器。

```bat
:: 環境檢查（Python、uxplay-windows、Bonjour、網路、防火牆）
check_env.bat

:: 直接執行面板
run_panel.bat

:: 打包成 exe（需 pip install pyinstaller）
py -3 -m PyInstaller --noconfirm AirPlayClassroom.spec
```

打包結果在 `dist\`，再依「安裝」一節放入 `vendor\uxplay-windows\`。

### 專案結構

```
app/
  main.py          控制面板介面（tkinter）
  uxplay_ctl.py    找程式、讀寫 arguments.txt、啟動／停止、查詢連線狀態
  config.py        面板設定（config.json）
  icon.ico         程式圖示（取自 uxplay-windows）
tools/
  check_env.py     環境自動檢查
vendor/            放 uxplay-windows（不納入版本控制）
AirPlayClassroom.spec  PyInstaller 設定
```

### 運作原理

uxplay-windows 2.x 將 UxPlay 引擎內建於 `uxplay-windows.exe`，啟動參數讀自
`%APPDATA%\leapbtw\uxplay-windows\arguments.txt`（若 `%ProgramData%\uxplay-windows\arguments.txt` 存在則優先）。
面板把設定組成 UxPlay 參數寫入該檔，再重新啟動 uxplay-windows；
連線狀態則透過 `netstat` 查詢 uxplay-windows 程序的 TCP 連線判斷。

## 授權

uxplay-windows 與 UxPlay 採用 GPL-3.0 授權，請參考其各自的專案頁面。
