"""
main.py
Win+Q -> Win+Left  /  Win+W -> Win+Right  など各種キーリマップ。
Alt+F1 -> アクティブウィンドウを 縦長 にリサイズ
Alt+F2 -> アクティブウィンドウを 横長 にリサイズ

管理者権限で実行すること:
  remap_start.bat をダブルクリック（推奨）
  または管理者権限のターミナルで: python main.py
"""

import ctypes
import ctypes.wintypes as wt
import sys
import threading
from ctypes import CFUNCTYPE, c_int, POINTER, cast

import window_resize  # ウィンドウサイズ変更モジュール

# ── フック識別子（Hook IDs） ──────────────────────────────────
WH_KEYBOARD_LL      = 13      # グローバル低レベルキーボードフック（Low-Level Keyboard Hook）

# ── ウィンドウメッセージ（Window Messages） ───────────────────
WM_KEYDOWN          = 0x0100  # 非システムキー（Altを伴わない）の押下
WM_KEYUP            = 0x0101  # 非システムキーの解放
WM_SYSKEYDOWN       = 0x0104  # システムキー（Altを伴う）の押下
WM_SYSKEYUP         = 0x0105  # システムキーの解放

# ── 仮想キーコード（Virtual Key Codes） ───────────────────────
VK_LWIN             = 0x5B    # 左Windowsロゴキー
VK_RWIN             = 0x5C    # 右Windowsロゴキー
VK_Q                = 0x51    # Qキー
VK_W                = 0x57    # Wキー
VK_Z                = 0x5A    # Zキー
VK_X                = 0x58    # Xキー
VK_C                = 0x43    # Cキー
VK_Y                = 0x59    # Yキー
VK_V                = 0x56    # Vキー
VK_A                = 0x41    # Aキー
VK_S                = 0x53    # Sキー
VK_H                = 0x48    # Hキー
VK_LEFT             = 0x25    # 左矢印キー（Left Arrow）
VK_RIGHT            = 0x27    # 右矢印キー（Right Arrow）
VK_UP               = 0x26    # 上矢印キー（Up Arrow）
VK_SHIFT            = 0x10    # Shiftキー（左右不問の総称コード）
VK_LSHIFT           = 0xA0    # 左Shiftキー
VK_RSHIFT           = 0xA1    # 右Shiftキー
VK_CONTROL          = 0x11    # Ctrlキー（左右不問の総称コード）
VK_LCONTROL         = 0xA2    # 左Ctrlキー
VK_RCONTROL         = 0xA3    # 右Ctrlキー
VK_MENU             = 0x12    # Altキー（左右不問の総称コード、Win32仕様上はMENUと定義）
VK_LMENU            = 0xA4    # 左Altキー
VK_RMENU            = 0xA5    # 右Altキー
VK_F1               = 0x70    # F1キー
VK_F2               = 0x71    # F2キー
VK_F3               = 0x72    # F3キー
VK_ESCAPE           = 0x1B    # Escキー（Escape）
VK_RETURN           = 0x0D    # Enterキー（Win32仕様上はRETURNと定義）
VK_MEDIA_PLAY_PAUSE = 0xB3    # マルチメディア再生 / 一時停止キー
VK_KANJI            = 0xF3    # 半角/全角キー（IME OFF状態等における仮想キーコード）
VK_OEM_AUTO         = 0xF4    # 半角/全角キー（IME ON状態等における仮想キーコード）

LLKHF_INJECTED = 0x10  # 自分が送ったキーを再帰フックしないためのフラグ

# ── 構造体 ─────────────────────────────────────────────────
class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode",      wt.DWORD),
        ("scanCode",    wt.DWORD),
        ("flags",       wt.DWORD),
        ("time",        wt.DWORD),
        ("dwExtraInfo", ctypes.c_uint64),
    ]

# ── SendInput ヘルパー ─────────────────────────────────────
INPUT_KEYBOARD  = 1
KEYEVENTF_KEYUP = 0x0002

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk",         wt.WORD),
        ("wScan",       wt.WORD),
        ("dwFlags",     wt.DWORD),
        ("time",        wt.DWORD),
        ("dwExtraInfo", ctypes.c_uint64),
    ]

class _INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("_pad", ctypes.c_byte * 28)]

class INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("_u", _INPUT_UNION)]


def send_keys(*keys):
    """
    keys: [(vk, is_keyup), ...]
    例: send_keys((VK_LWIN,False),(VK_LEFT,False),(VK_LEFT,True),(VK_LWIN,True))
    """
    inputs = (INPUT * len(keys))()
    for i, (vk, keyup) in enumerate(keys):
        inputs[i].type = INPUT_KEYBOARD
        inputs[i]._u.ki.wVk   = vk
        inputs[i]._u.ki.dwFlags = KEYEVENTF_KEYUP if keyup else 0
    ctypes.windll.user32.SendInput(len(keys), inputs, ctypes.sizeof(INPUT))


def is_physically_down(vk):
    """
    GetAsyncKeyState で物理的なキー押下状態を確認する。
    フック内の状態変数はインジェクトしたキーや
    タイミング次第でズレることがあるため、こちらで補正する。
    """
    return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)


# ── 状態管理 ───────────────────────────────────────────────
win_pressed   = False
shift_pressed = False
alt_pressed   = False
ctrl_pressed  = False
hooked_vk     = None


# ── フックコールバック ──────────────────────────────────────
LowLevelKeyboardProc = CFUNCTYPE(c_int, c_int, wt.WPARAM, POINTER(KBDLLHOOKSTRUCT))

def hook_proc(nCode, wParam, lParam):
    global win_pressed, shift_pressed, alt_pressed, ctrl_pressed, hooked_vk

    if nCode < 0:
        return ctypes.windll.user32.CallNextHookEx(None, nCode, wParam, lParam)

    kb       = lParam.contents
    vk       = kb.vkCode
    injected = bool(kb.flags & LLKHF_INJECTED)

    is_down = wParam in (WM_KEYDOWN, WM_SYSKEYDOWN)
    is_up   = wParam in (WM_KEYUP,   WM_SYSKEYUP)

    if injected:
        return ctypes.windll.user32.CallNextHookEx(None, nCode, wParam, lParam)

    # ── 修飾キーの追跡 ─────────────────────────────────────
    if vk in (VK_LWIN, VK_RWIN):
        if is_down:
            win_pressed = True
        elif is_up:
            win_pressed = False
            hooked_vk   = None
        return ctypes.windll.user32.CallNextHookEx(None, nCode, wParam, lParam)

    if vk in (VK_SHIFT, VK_LSHIFT, VK_RSHIFT):
        shift_pressed = is_down
        return ctypes.windll.user32.CallNextHookEx(None, nCode, wParam, lParam)

    if vk in (VK_MENU, VK_LMENU, VK_RMENU):
        alt_pressed = is_down
        return ctypes.windll.user32.CallNextHookEx(None, nCode, wParam, lParam)

    if vk in (VK_CONTROL, VK_LCONTROL, VK_RCONTROL):
        ctrl_pressed = is_down
        return ctypes.windll.user32.CallNextHookEx(None, nCode, wParam, lParam)

    # ── キーリマップ ───────────────────────────────────────

    # Win + Q → Win + Left
    if win_pressed and not shift_pressed and vk == VK_Q and is_down:
        hooked_vk = VK_Q
        send_keys(
            (VK_LWIN,  False),
            (VK_LEFT,  False),
            (VK_LEFT,  True),
            (VK_LWIN,  True),
        )
        return 1

    # Win + W → Win + Right
    if win_pressed and not shift_pressed and vk == VK_W and is_down:
        hooked_vk = VK_W
        send_keys(
            (VK_LWIN,  False),
            (VK_RIGHT, False),
            (VK_RIGHT, True),
            (VK_LWIN,  True),
        )
        return 1

   # Win + 半角/全角 → Win + Up（ウィンドウの最大化）
    if win_pressed and not shift_pressed and not alt_pressed and (vk in (VK_KANJI, VK_OEM_AUTO)) and is_down:
        hooked_vk = vk
        send_keys(
            (VK_LWIN,  False),
            (VK_UP,    False),
            (VK_UP,    True),
            (VK_LWIN,  True),
        )
        return 1
    
    # Win + Shift + Z → Win + Shift + Left
    if win_pressed and shift_pressed and vk == VK_Z and is_down:
        hooked_vk = VK_Z
        send_keys(
            (VK_LWIN,   False),
            (VK_LSHIFT, False),
            (VK_LEFT,   False),
            (VK_LEFT,   True),
            (VK_LSHIFT, True),
            (VK_LWIN,   True),
        )
        return 1

    # Win + Shift + X → Win + Shift + Right
    if win_pressed and shift_pressed and vk == VK_X and is_down:
        hooked_vk = VK_X
        send_keys(
            (VK_LWIN,   False),
            (VK_LSHIFT, False),
            (VK_RIGHT,  False),
            (VK_RIGHT,  True),
            (VK_LSHIFT, True),
            (VK_LWIN,   True),
        )
        return 1

    # F1 → Win + H（音声入力）
    # Alt を押していない場合のみ発火
    if vk == VK_F1 and is_down and not alt_pressed:
        send_keys(
            (VK_LWIN, False),
            (VK_H,    False),
            (VK_H,    True),
            (VK_LWIN, True),
        )
        return 1

      # Alt + F1 → アクティブウィンドウを 横長 にリサイズ
    if alt_pressed and vk == VK_F1 and is_down:
        window_resize.resize_active_window(0.652, 0.681)
        return 1
 
    # Alt + F2 → アクティブウィンドウを 縦長 にリサイズ
    if alt_pressed and vk == VK_F2 and is_down:
        window_resize.resize_active_window(0.477, 0.964)
        return 1
 
    # Alt + F3 → アクティブウィンドウを 横長(小さい) にリサイズ
    if alt_pressed and vk == VK_F3 and is_down:
        window_resize.resize_active_window(0.55, 0.55)
        return 1
 

    # Win + Esc → Media Play/Pause
    if win_pressed and vk == VK_ESCAPE and is_down:
        send_keys(
            (VK_MEDIA_PLAY_PAUSE, False),
            (VK_MEDIA_PLAY_PAUSE, True),
        )
        return 1

    # Alt + A → Left
    # Alt を一時解放してから Left を送り、物理Altが離されていれば戻さない。
    # 「Alt DOWN を末尾に送る」旧実装は、そのDOWNが宙ぶらりんになる原因だったため廃止。
    if alt_pressed and vk == VK_A and is_down:
        send_keys(
            (VK_LMENU, True),   # Alt を一時解放
            (VK_LEFT,  False),
            (VK_LEFT,  True),
        )
        # 物理的にまだAltが押されていれば状態を維持、離されていれば False に補正
        alt_pressed = is_physically_down(VK_LMENU) or is_physically_down(VK_RMENU)
        if alt_pressed:
            send_keys((VK_LMENU, False))  # 物理的に押し続けているなら押し直す
        return 1

    # Alt + S → Right
    if alt_pressed and vk == VK_S and is_down:
        send_keys(
            (VK_LMENU, True),   # Alt を一時解放
            (VK_RIGHT, False),
            (VK_RIGHT, True),
        )
        alt_pressed = is_physically_down(VK_LMENU) or is_physically_down(VK_RMENU)
        if alt_pressed:
            send_keys((VK_LMENU, False))
        return 1

    # Alt + C → Ctrl + Win + V
    if alt_pressed and vk == VK_C and is_down:
        send_keys(
            (VK_LMENU,    True),   # Alt を一時解放
            (VK_LCONTROL, False),
            (VK_LWIN,     False),
            (VK_V,        False),
            (VK_V,        True),
            (VK_LWIN,     True),
            (VK_LCONTROL, True),
        )
        alt_pressed = is_physically_down(VK_LMENU) or is_physically_down(VK_RMENU)
        if alt_pressed:
            send_keys((VK_LMENU, False))
        return 1

    # Alt + Q → Ctrl + Win + Left
    if alt_pressed and vk == VK_Q and is_down:
        send_keys(
            (VK_LMENU,    True),   # Alt を一時解放
            (VK_LCONTROL, False),
            (VK_LWIN,     False),
            (VK_LEFT,     False),
            (VK_LEFT,     True),
            (VK_LWIN,     True),
            (VK_LCONTROL, True),
        )
        alt_pressed = is_physically_down(VK_LMENU) or is_physically_down(VK_RMENU)
        if alt_pressed:
            send_keys((VK_LMENU, False))
        return 1

    # Alt + W → Ctrl + Win + Right
    if alt_pressed and vk == VK_W and is_down:
        send_keys(
            (VK_LMENU,    True),   # Alt を一時解放
            (VK_LCONTROL, False),
            (VK_LWIN,     False),
            (VK_RIGHT,    False),
            (VK_RIGHT,    True),
            (VK_LWIN,     True),
            (VK_LCONTROL, True),
        )
        alt_pressed = is_physically_down(VK_LMENU) or is_physically_down(VK_RMENU)
        if alt_pressed:
            send_keys((VK_LMENU, False))
        return 1

    # Ctrl + Space → Enter
    if ctrl_pressed and vk == 0x20 and is_down:
        send_keys(
            (VK_RETURN, False),
            (VK_RETURN, True),
        )
        return 1

    # Win + C → AI をブラウザで開く。どのAIかはお好みで。
    if win_pressed and not shift_pressed and not alt_pressed and vk == VK_C and is_down:
        hooked_vk = VK_C
        import subprocess
        subprocess.Popen(["start", "https://chatgpt.com/"], shell=True)
        send_keys((VK_LCONTROL, False), (VK_LCONTROL, True))
        return 1


    # キーアップも横取り
    if hooked_vk:
        if vk == hooked_vk and is_up:
            hooked_vk = None
            return 1
        # 半角/全角キーのコード変動に対応する例外処理
        if hooked_vk in (VK_KANJI, VK_OEM_AUTO) and vk in (VK_KANJI, VK_OEM_AUTO) and is_up:
            hooked_vk = None
            return 1

    return ctypes.windll.user32.CallNextHookEx(None, nCode, wParam, lParam)


# ── メインループ ───────────────────────────────────────────
def main():
    if not ctypes.windll.shell32.IsUserAnAdmin():
        print("[ERROR] 管理者権限で実行してください。")
        sys.exit(1)

    callback = LowLevelKeyboardProc(hook_proc)
    hook = ctypes.windll.user32.SetWindowsHookExW(
        WH_KEYBOARD_LL,
        callback,
        None,
        0
    )
    if not hook:
        print("[ERROR] フックの設置に失敗しました。")
        sys.exit(1)

    print("起動しました。")
    print("  Win+Q        -> Win+Left          (ウィンドウを左にスナップ)")
    print("  Win+W        -> Win+Right         (ウィンドウを右にスナップ)")
    print("  Win+半角/全角 -> Win+Up             (ウィンドウを最大化)")
    print("  Win+Shift+Z  -> Win+Shift+Left    (ウィンドウを左モニターへ移動)")
    print("  Win+Shift+X  -> Win+Shift+Right   (ウィンドウを右モニターへ移動)")
    print("  Alt+A        -> Left              (左矢印)")
    print("  Alt+S        -> Right             (右矢印)")
    print("  Alt+Q        -> Ctrl+Win+Left     (仮想デスクトップを左へ)")
    print("  Alt+W        -> Ctrl+Win+Right    (仮想デスクトップを右へ)")
    print("  F1           -> Win+H             (音声入力)")
    print("  Win+Esc      -> Media Play/Pause  (再生/一時停止)")
    print("  Alt+C        -> Ctrl+Win+V        (クリップボード履歴)")
    print("  Ctrl+Space   -> Enter")
    print("  Win+C        -> LLM をブラウザで開く")
    print("  Alt+F1       -> アクティブウィンドウを 横長 にリサイズ")
    print("  Alt+F2       -> アクティブウィンドウを 縦長 にリサイズ")
    print("  Alt+F3       -> アクティブウィンドウを 横長(小) にリサイズ")
    print("  停止: Ctrl+Cは不可なのでウインドウごと落とすか、タスクマネージャーからプロセスを終了してください。")

    msg = wt.MSG()
    try:
        while ctypes.windll.user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            ctypes.windll.user32.TranslateMessage(ctypes.byref(msg))
            ctypes.windll.user32.DispatchMessageW(ctypes.byref(msg))
    except KeyboardInterrupt:
        pass
    finally:
        ctypes.windll.user32.UnhookWindowsHookEx(hook)
        print("終了しました。")


if __name__ == "__main__":
    main()