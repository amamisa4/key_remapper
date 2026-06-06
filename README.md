# key_remapper

Windowsのキーボードショートカットをリマップするスクリプト。  
低レベルキーボードフック（`WH_KEYBOARD_LL`）を使用し、OSレベルで入力を横取りする。

---

## ファイル構成

```
key_remapper/
├── remap.py          # メインスクリプト
└── remap_start.bat   # バックグラウンド起動用
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
| Alt + Q | Ctrl + Win + Left | 仮想デスクトップを左へ |
| Alt + W | Ctrl + Win + Right | 仮想デスクトップを右へ |
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

追加のパッケージは不要。標準ライブラリ（`ctypes`）のみ使用。

---

## 起動方法

### 通常起動（コンソールあり・デバッグ用）

管理者権限のターミナルで実行：

```powershell
python remap.py
```

停止は `Ctrl + C`。

### バックグラウンド起動（コンソールなし・通常使用）

`remap_start.bat` をダブルクリックする。  
UACのプロンプトが表示されるので「はい」を選択する。  
以降はタスクトレイ等には表示されないが、バックグラウンドで動作し続ける。

```bat
@echo off
powershell -Command "Start-Process 'C:\Users\amami\AppData\Local\Programs\Python\Python313\pythonw.exe' '%~dp0remap.py' -Verb RunAs"
```

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
   - プログラム：`C:\Users\amami\AppData\Local\Programs\Python\Python313\pythonw.exe`
   - 引数：`remap.py` のフルパス（例：`C:\Users\amami\myapps\key_remapper\remap.py`）
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