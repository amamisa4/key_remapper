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
import os
import sys
import subprocess
from ctypes import CFUNCTYPE, c_int, POINTER, cast

import pystray
from PIL import Image

import window_resize  # ウィンドウサイズ変更モジュール
import calc_overlay   # Alt+Space の電卓オーバーレイモジュール
import key_logger     # ログユーティリティ（key_logger.py の ENABLE_LOG で ON/OFF）

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
VK_VOLUME_DOWN      = 0xAE    # 音量下げ
VK_VOLUME_UP        = 0xAF    # 音量上げ
VK_1                = 0x31    # 1キー
VK_2                = 0x32    # 2キー
VK_COPILOT          = 0x86    # Copilotキー（vkCode実測値）
VK_SPACE            = 0x20    # スペースキー

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
win_pressed    = False
shift_pressed  = False
alt_pressed    = False
ctrl_pressed   = False
hooked_vk      = None
copilot_down   = False  # Copilotキーが現在押されているか
suppress_win   = False  # Copilot起因のWin UPを握りつぶすか
suppress_shift = False  # Copilot起因のShift UPを握りつぶすか

paused = False  # タスクトレイメニューからの一時停止フラグ（Trueの間は全キーをそのまま素通しする）

tray_icon = None       # pystray.Icon インスタンス（main() で生成）
_main_thread_id = None  # メインの GetMessageW ループを WM_QUIT で止めるために記録


def reset_modifier_states():
    """
    スリープ復帰・ロック解除時など、修飾キーのUPイベントを取り逃がした場合に
    全修飾キー状態をリセットする。
    GetAsyncKeyState で物理状態を再確認し、押されていないキーだけ False にする。
    """
    global win_pressed, shift_pressed, alt_pressed, ctrl_pressed, hooked_vk
    global copilot_down, suppress_win, suppress_shift
    win_pressed   = is_physically_down(VK_LWIN)  or is_physically_down(VK_RWIN)
    shift_pressed = is_physically_down(VK_LSHIFT) or is_physically_down(VK_RSHIFT)
    alt_pressed   = is_physically_down(VK_LMENU)  or is_physically_down(VK_RMENU)
    ctrl_pressed  = is_physically_down(VK_LCONTROL) or is_physically_down(VK_RCONTROL)
    if not win_pressed:
        hooked_vk = None
    copilot_down = suppress_win = suppress_shift = False


# ── フックコールバック ──────────────────────────────────────
LowLevelKeyboardProc = CFUNCTYPE(c_int, c_int, wt.WPARAM, POINTER(KBDLLHOOKSTRUCT))

def hook_proc(nCode, wParam, lParam):
    global win_pressed, shift_pressed, alt_pressed, ctrl_pressed, hooked_vk
    global copilot_down, suppress_win, suppress_shift

    if nCode < 0:
        return ctypes.windll.user32.CallNextHookEx(None, nCode, wParam, lParam)

    if paused:
        # 一時停止中は一切リマップせずそのまま通す
        return ctypes.windll.user32.CallNextHookEx(None, nCode, wParam, lParam)

    kb       = lParam.contents
    vk       = kb.vkCode
    injected = bool(kb.flags & LLKHF_INJECTED)

    is_down = wParam in (WM_KEYDOWN, WM_SYSKEYDOWN)
    is_up   = wParam in (WM_KEYUP,   WM_SYSKEYUP)

    if injected:
        return ctypes.windll.user32.CallNextHookEx(None, nCode, wParam, lParam)

    # ── 修飾キーの追跡 ─────────────────────────────────────
    # Shift/Alt/Ctrl については、スリープ復帰後のUP取り逃がし対策として
    # GetAsyncKeyState で物理状態を補正する。
    # Win キーは SendInput で Win UP を送った直後に GetAsyncKeyState が
    # 「離された」と返すことがあり、Win+Q 連打などを誤ってキャンセルしてしまう。
    # Win の誤残留はメッセージウィンドウ側（WM_POWERBROADCAST / WM_WTSSESSION_CHANGE）
    # で reset_modifier_states() を呼ぶことで対処済みのため、ここでは補正しない。
    if not is_physically_down(VK_LSHIFT) and not is_physically_down(VK_RSHIFT):
        shift_pressed = False
    if not is_physically_down(VK_LMENU) and not is_physically_down(VK_RMENU):
        alt_pressed = False
    if not is_physically_down(VK_LCONTROL) and not is_physically_down(VK_RCONTROL):
        ctrl_pressed = False

    if vk in (VK_LWIN, VK_RWIN):
        if is_down:
            win_pressed = True
            if not copilot_down:
                suppress_win = True  # Copilotキーが続くか監視
        elif is_up:
            if suppress_win and copilot_down:
                # Copilot起因のWin UPは握りつぶす
                suppress_win = False
                key_logger.debug("Win UP: Copilot起因のため握りつぶし")
                return 1
            suppress_win = False
            win_pressed  = False
            hooked_vk    = None
        return ctypes.windll.user32.CallNextHookEx(None, nCode, wParam, lParam)

    if vk in (VK_SHIFT, VK_LSHIFT, VK_RSHIFT):
        if is_down:
            shift_pressed = True
            if not copilot_down:
                suppress_shift = True  # Copilotキーが続くか監視
        elif is_up:
            if suppress_shift and copilot_down:
                # Copilot起因のShift UPは握りつぶす
                suppress_shift = False
                key_logger.debug("Shift UP: Copilot起因のため握りつぶし")
                return 1
            suppress_shift = False
            shift_pressed  = False
        return ctypes.windll.user32.CallNextHookEx(None, nCode, wParam, lParam)

    if vk in (VK_MENU, VK_LMENU, VK_RMENU):
        alt_pressed = is_down
        return ctypes.windll.user32.CallNextHookEx(None, nCode, wParam, lParam)

    if vk in (VK_CONTROL, VK_LCONTROL, VK_RCONTROL):
        ctrl_pressed = is_down
        return ctypes.windll.user32.CallNextHookEx(None, nCode, wParam, lParam)

    # ── キーリマップ ───────────────────────────────────────

    # Copilotキー → Alt
    # このキーボードは Copilot押下時に Win+Shift+0x86 の順でイベントを送出する。
    # Win UP・Shift UP で残留を消してから Alt DOWN を送る。
    if vk == VK_COPILOT:
        if is_down and not copilot_down:
            copilot_down = True
            seqs = []
            if is_physically_down(VK_LWIN):
                seqs.append((VK_LWIN,   True))
            if is_physically_down(VK_LSHIFT) or is_physically_down(VK_RSHIFT):
                seqs.append((VK_LSHIFT, True))
            seqs.append((VK_LMENU, False))
            send_keys(*seqs)
            key_logger.info(f"Copilot DOWN → Alt DOWN (seqs={seqs})")
            return 1
        elif is_down:   # キーリピート
            return 1
        elif is_up:
            copilot_down = suppress_win = suppress_shift = False
            send_keys((VK_LMENU, True))
            key_logger.info("Copilot UP → Alt UP")
            return 1

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

    # # Win + Shift + Z → Win + Shift + Left
    # if win_pressed and shift_pressed and vk == VK_Z and is_down:
    #     hooked_vk = VK_Z
    #     send_keys(
    #         (VK_LWIN,   False),
    #         (VK_LSHIFT, False),
    #         (VK_LEFT,   False),
    #         (VK_LEFT,   True),
    #         (VK_LSHIFT, True),
    #         (VK_LWIN,   True),
    #     )
    #     return 1

    # # Win + Shift + X → Win + Shift + Right
    # if win_pressed and shift_pressed and vk == VK_X and is_down:
    #     hooked_vk = VK_X
    #     send_keys(
    #         (VK_LWIN,   False),
    #         (VK_LSHIFT, False),
    #         (VK_RIGHT,  False),
    #         (VK_RIGHT,  True),
    #         (VK_LSHIFT, True),
    #         (VK_LWIN,   True),
    #     )
    #     return 1

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
        window_resize.resize_active_window(0.55, 0.681) # 横 , 縦
        return 1

    # Alt + F2 → アクティブウィンドウを 縦長 にリサイズ
    if alt_pressed and vk == VK_F2 and is_down:
        window_resize.resize_active_window(0.477, 0.964, x_ratio=0.001, y_ratio=0.024) # 横 , 縦
        return 1

    # Alt + F3 → アクティブウィンドウを 横長(小さい) にリサイズ
    if alt_pressed and vk == VK_F3 and is_down:
        window_resize.resize_active_window(0.42, 0.55) # 横 , 縦
        return 1

    # Alt + Space → 電卓オーバーレイの表示/非表示切り替え
    if alt_pressed and vk == VK_SPACE and is_down:
        calc_overlay.toggle_overlay()
        return 1

    # Alt + 1 → 音量下げ
    if alt_pressed and vk == VK_1 and is_down:
        send_keys(
            (VK_VOLUME_DOWN,   False),
            (VK_VOLUME_DOWN,   True),
        )
        return 1

    # Alt + 2 → 音量上げ
    if alt_pressed and vk == VK_2 and is_down:
        send_keys(
            (VK_VOLUME_UP, False),
            (VK_VOLUME_UP, True),
        )
        return 1

    # Win + Esc → Media Play/Pause
    if win_pressed and vk == VK_ESCAPE and is_down:
        send_keys(
            (VK_MEDIA_PLAY_PAUSE, False),
            (VK_MEDIA_PLAY_PAUSE, True),
        )
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

    # # Alt + Q → Ctrl + Win + Left
    # if alt_pressed and vk == VK_Q and is_down:
    #     send_keys(
    #         (VK_LMENU,    True),   # Alt を一時解放
    #         (VK_LCONTROL, False),
    #         (VK_LWIN,     False),
    #         (VK_LEFT,     False),
    #         (VK_LEFT,     True),
    #         (VK_LWIN,     True),
    #         (VK_LCONTROL, True),
    #     )
    #     alt_pressed = is_physically_down(VK_LMENU) or is_physically_down(VK_RMENU)
    #     if alt_pressed:
    #         send_keys((VK_LMENU, False))
    #     return 1

    # # Alt + W → Ctrl + Win + Right
    # if alt_pressed and vk == VK_W and is_down:
    #     send_keys(
    #         (VK_LMENU,    True),   # Alt を一時解放
    #         (VK_LCONTROL, False),
    #         (VK_LWIN,     False),
    #         (VK_RIGHT,    False),
    #         (VK_RIGHT,    True),
    #         (VK_LWIN,     True),
    #         (VK_LCONTROL, True),
    #     )
    #     alt_pressed = is_physically_down(VK_LMENU) or is_physically_down(VK_RMENU)
    #     if alt_pressed:
    #         send_keys((VK_LMENU, False))
    #     return 1

    # Ctrl + Space → Enter
    # Ctrl を押したまま Enter を送ると受信側が Ctrl+Enter と解釈するため、
    # Alt+A/S と同様に Ctrl を一時解放してから Enter を送る。
    if ctrl_pressed and vk == 0x20 and is_down:
        send_keys(
            (VK_LCONTROL, True),    # Ctrl を一時解放
            (VK_RETURN,   False),
            (VK_RETURN,   True),
        )
        # 物理的にまだ Ctrl が押されていれば押し直す
        ctrl_pressed = is_physically_down(VK_LCONTROL) or is_physically_down(VK_RCONTROL)
        if ctrl_pressed:
            send_keys((VK_LCONTROL, False))
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


# ── 電源・セッション変化通知用の非表示ウィンドウ ──────────────
# WM_POWERBROADCAST / WM_WTSSESSION_CHANGE はウィンドウプロシージャ経由でのみ受信できる。
# スリープ復帰・ロック解除時に修飾キー状態をリセットするために使用する。
WM_POWERBROADCAST   = 0x0218
PBT_APMRESUMEAUTOMATIC = 0x0012  # スリープ復帰（自動）
PBT_APMRESUMESUSPEND   = 0x0007  # スリープ復帰（ユーザー操作）
WM_WTSSESSION_CHANGE   = 0x02B1
WTS_SESSION_UNLOCK     = 0x0008  # ロック解除

WNDPROCTYPE = ctypes.CFUNCTYPE(ctypes.c_ssize_t, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)

# WPARAM/LPARAM・戻り値(LRESULT)は64bit環境で大きな値になることがあり、
# argtypes/restype未指定だとctypesの既定のc_int(32bit)変換でOverflowErrorになる。
# 明示的に型を指定して回避する。
ctypes.windll.user32.DefWindowProcW.restype = ctypes.c_ssize_t
ctypes.windll.user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style",         wt.UINT),
        ("lpfnWndProc",   WNDPROCTYPE),
        ("cbClsExtra",    ctypes.c_int),
        ("cbWndExtra",    ctypes.c_int),
        ("hInstance",     wt.HINSTANCE),
        ("hIcon",         wt.HANDLE),
        ("hCursor",       wt.HANDLE),
        ("hbrBackground", wt.HANDLE),
        ("lpszMenuName",  wt.LPCWSTR),
        ("lpszClassName", wt.LPCWSTR),
    ]


# ── タスクトレイ（pystray） ────────────────────────────────
# 自前のTrackPopupMenu/オーナードロー/自前描画ポップアップはいずれもテーマ・DPI
# 環境で文字が描画されない不具合が解消できなかったため、Win32のメニュー表示・
# フォーカス制御を正しく実装済みの pystray (win32バックエンド) に置き換える。
WM_QUIT = 0x0012


_ICON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "icon.png")

# key_remapper専用の固定uID。
# pystrayのwin32バックエンドは NOTIFYICONDATAW に uID ではなく誤って hID という
# 存在しないキーワードで値を渡しており(pystray自体のバグ)、ctypesがそれを
# 黙って無視するため実際の uID は常に既定値の 0 のまま登録されてしまう。
# 同じ pythonw.exe から起動する別の pystray 常駐アプリも同様に uID=0 になり、
# Windows側でタスクトレイの格納・並び替えが連動してしまう原因になっていた。
# _message を差し替えて正しいキーワード名で固定のuIDを注入し直す。
_TRAY_ICON_UID = 0x4B52  # 'KR' (KeyRemapper) 由来の固定値


def _patch_tray_uid(icon):
    """Shell_NotifyIconへの全呼び出しに正しい uID を注入するよう _message を差し替える。"""
    orig_message = icon._message

    def patched_message(code, flags, **kwargs):
        kwargs.setdefault("uID", _TRAY_ICON_UID)
        return orig_message(code, flags, **kwargs)

    icon._message = patched_message


def _build_tray_image():
    """トレイアイコン用画像を読み込む（assets/icon.svg をラスタライズしたもの）。"""
    return Image.open(_ICON_PATH)


def _on_toggle_pause(icon, item):
    """タスクトレイメニューの「一時停止/再開」クリック時に呼ばれる。"""
    global paused
    paused = not paused
    if not paused:
        # 再開時は物理的なキー状態を再取得してズレを防ぐ
        reset_modifier_states()
    key_logger.info(f"タスクトレイ: {'一時停止' if paused else '再開'}")
    icon.update_menu()


def _on_exit(icon, item):
    """タスクトレイメニューの「終了」クリック時に呼ばれる。"""
    key_logger.info("タスクトレイ: 終了")
    icon.stop()
    # PostQuitMessage は呼び出しスレッド（pystrayの別スレッド）のキューに積まれて
    # main() の GetMessageW ループには届かないため、明示的にメインスレッドへ送る。
    ctypes.windll.user32.PostThreadMessageW(_main_thread_id, WM_QUIT, 0, 0)


def _setup_tray(icon):
    """pystrayのrun_detachedから専用スレッドで呼ばれるセットアップ処理。"""
    _patch_tray_uid(icon)
    icon.visible = True


def start_tray_icon():
    """タスクトレイアイコンとメニューを構築し、専用スレッドで起動する。"""
    global tray_icon
    menu = pystray.Menu(
        pystray.MenuItem(lambda item: "再開" if paused else "一時停止", _on_toggle_pause),
        pystray.MenuItem("終了", _on_exit),
    )
    tray_icon = pystray.Icon("key_remapper", _build_tray_image(), "key_remapper", menu)
    tray_icon.run_detached(setup=_setup_tray)


def _make_notify_window():
    """
    スリープ復帰・ロック解除通知を受け取るための非表示ウィンドウを生成する。
    """
    hinstance = ctypes.windll.kernel32.GetModuleHandleW(None)
    class_name = "KeyRemapperNotify"

    def wnd_proc(hwnd, msg, wparam, lparam):
        if msg == WM_POWERBROADCAST:
            if wparam in (PBT_APMRESUMEAUTOMATIC, PBT_APMRESUMESUSPEND):
                reset_modifier_states()
        elif msg == WM_WTSSESSION_CHANGE:
            if wparam == WTS_SESSION_UNLOCK:
                reset_modifier_states()
        return ctypes.windll.user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    # コールバックをグローバルに保持してGC回収を防ぐ
    global _wnd_proc_ref
    _wnd_proc_ref = WNDPROCTYPE(wnd_proc)

    wc = WNDCLASSW()
    wc.lpfnWndProc   = _wnd_proc_ref
    wc.hInstance     = hinstance
    wc.lpszClassName = class_name
    ctypes.windll.user32.RegisterClassW(ctypes.byref(wc))

    hwnd = ctypes.windll.user32.CreateWindowExW(
        0, class_name, class_name,
        0, 0, 0, 0, 0,
        None, None, hinstance, None,
    )

    # セッション変化通知を登録（WM_WTSSESSION_CHANGE を受け取るために必要）
    ctypes.windll.wtsapi32.WTSRegisterSessionNotification(hwnd, 0)

    return hwnd

_wnd_proc_ref = None  # GC回収防止用グローバル


# ── メインループ ───────────────────────────────────────────
def main():
    # AppUserModelIDを明示しないと、同じ pythonw.exe から起動する別の常駐アプリ
    # （タスクトレイアイコンを持つスクリプト等）とWindowsから「同一アプリ」と
    # 誤認識され、タスクトレイでの格納・並び替えが連動してしまうことがある。
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("amamisa4.KeyRemapper")
    except OSError:
        pass

    # DPI対応を明示しないと、拡大率のかかったディスプレイでタスクトレイの
    # 右クリックメニューが正しく描画されず、文字が表示されないことがある。
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    except (AttributeError, OSError):
        ctypes.windll.user32.SetProcessDPIAware()

    if not ctypes.windll.shell32.IsUserAnAdmin():
        print("[ERROR] 管理者権限で実行してください。")
        sys.exit(1)

    global _main_thread_id
    _main_thread_id = ctypes.windll.kernel32.GetCurrentThreadId()

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

    # スリープ復帰・ロック解除通知用ウィンドウを生成
    _make_notify_window()

    # タスクトレイアイコン・右クリックメニューを起動（専用スレッドで動作）
    start_tray_icon()

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
    print("  Copilot      -> Alt               (Altキーとして動作)")
    print("  タスクトレイに常駐します。右クリックメニューから「一時停止/再開」「終了」を選べます。")

    msg = wt.MSG()
    try:
        while ctypes.windll.user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            ctypes.windll.user32.TranslateMessage(ctypes.byref(msg))
            ctypes.windll.user32.DispatchMessageW(ctypes.byref(msg))
    except KeyboardInterrupt:
        pass
    finally:
        try:
            tray_icon.stop()
        except Exception:
            pass
        ctypes.windll.user32.UnhookWindowsHookEx(hook)
        print("終了しました。")


if __name__ == "__main__":
    main()