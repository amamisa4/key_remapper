# key_remapper

Windowsのキーボードショートカットをリマップするスクリプト。  
低レベルキーボードフック（`WH_KEYBOARD_LL`）を使用し、OSレベルで入力を横取りする。

---

## ファイル構成

```
key_remapper/
├── main.py             # メインスクリプト
├── virtual_desktop.py  # 仮想デスクトップ操作モジュール
├── window_resize.py    # ウィンドウリサイズモジュール
├── calc_overlay.py     # 電卓オーバーレイモジュール
└── start_remap.bat     # バックグラウンド起動用
```

---

## キーマッピング一覧

| 入力 | 出力 | 用途 |
|------|------|------|
| Win + Q | Win + Left | ウィンドウを左にスナップ |
| Win + W | Win + Right | ウィンドウを右にスナップ |
| Win + Shift + Z | Win + Shift + Left | ウィンドウを左モニターへ移動 |
| Win + Shift + X | Win + Shift + Right | ウィンドウを右モニターへ移動 |
| Alt + A | ← | 左矢印 |
| Alt + S | → | 右矢印 |
| Alt + Q | - | 仮想デスクトップを左へ切り替え |
| Alt + W | - | 仮想デスクトップを右へ切り替え |
| Alt + Shift + Z | - | ウィンドウを左の仮想デスクトップへ移動して切り替え |
| Alt + Shift + X | - | ウィンドウを右の仮想デスクトップへ移動して切り替え |
| Alt + Shift + D | - | ウィンドウのピン留め（全デスクトップ表示）を切り替え |
| Alt + C | Ctrl + Win + V | クリップボード履歴を開く |
| F1 | Win + H | 音声入力 |
| Win + Esc | Media Play/Pause | 再生・一時停止 |
| Ctrl + Space | Enter | Enterキー |
| Win + C | ブラウザで ChatGPT を開く | https://chatgpt.com/ |
| Win + Y | ブラウザで YouTube を開く | https://www.youtube.com/ |

---

## 動作要件

- Windows 10 / 11
- Python 3.x（`pythonw.exe` が同梱されていること）
- 管理者権限（低レベルフックの設置に必要）

仮想デスクトップ操作（`virtual_desktop.py`）には `pyvda` / `pywin32` が必要。`pip install -r requirements.txt` でまとめて導入できる。

---

## 起動方法

### 通常起動（コンソールあり・デバッグ用）

管理者権限のターミナルで実行：

```powershell
python main.py
```

停止は `Ctrl + C`。

### バックグラウンド起動（コンソールなし・通常使用）

`start_remap.bat` をダブルクリックする。  
UACのプロンプトが表示されるので「はい」を選択する。  
以降はタスクトレイに常駐し、バックグラウンドで動作し続ける。

`start_remap.bat` はPythonの実行ファイルパスをハードコードせず、以下の順でその場のPC環境から自動解決する（別PCへ持って行っても変更不要）:

1. `pyw`（公式Pythonインストーラが入れるランチャー。バージョン・インストール場所非依存）
2. `py -3` でデフォルトのPythonの場所を特定し、同フォルダの `pythonw.exe`
3. `PATH` 上に見つかった最初の `pythonw.exe`（フォールバック。複数環境がある場合は意図しないものが選ばれる可能性あり）

いずれも見つからない場合はエラーメッセージを表示して終了する。

`pythonw.exe` はコンソールウィンドウを生成しないPython実行ファイルで、`python.exe` と同じフォルダに同梱されている。

---

## 停止方法

タスクマネージャーを開き、`pythonw.exe` のプロセスを終了する。

```
Ctrl + Shift + Esc → 詳細 → pythonw.exe → タスクの終了
```

---

## ログオン時の自動起動設定（任意）

タスクスケジューラを使用することで、ログオン時に自動的に起動させることができる。

1. `taskschd.msc` を実行してタスクスケジューラを開く
2. 「タスクの作成」を選択
3. **全般タブ**：「最上位の特権で実行する」にチェックを入れる
4. **トリガータブ**：「ログオン時」を選択
5. **操作タブ**：
   - プログラム：`start_remap.bat` のフルパス（Pythonのパスはbatが自動解決するため、ここではbatを直接指定する）
6. **条件タブ**：「AC電源時のみ」のチェックを外す
7. 「OK」で保存

これにより、次回ログオン以降はUACプロンプトなしで自動起動する。

---

## 注意事項

- 本スクリプトはOSレベルで全キー入力を監視する。セキュリティソフトが警告を出す場合がある。
- `Win + C` および `Win + Y` はブラウザを起動するため、`subprocess` を使用している。
- リマップ対象キーのキーアップイベントはOSに渡さず破棄する設計になっている。


## exe化
以下をbatにして起動
@echo off
powershell -Command "Start-Process '%~dp0dist\KeyRemapper.exe' -Verb RunAs"