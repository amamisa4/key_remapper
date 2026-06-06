import ctypes
import ctypes.wintypes as wt
import sys

# ── Win32定数 ──────────────────────────────────────────────
WH_KEYBOARD_LL = 13
WM_KEYDOWN     = 0x0100
WM_KEYUP       = 0x0101
WM_SYSKEYDOWN  = 0x0104
WM_SYSKEYUP    = 0x0105

# ── 構造体 ─────────────────────────────────────────────────
class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode",      wt.DWORD),
        ("scanCode",    wt.DWORD),
        ("flags",       wt.DWORD),
        ("time",        wt.DWORD),
        ("dwExtraInfo", ctypes.c_uint64),
    ]

LowLevelKeyboardProc = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int, wt.WPARAM, ctypes.POINTER(KBDLLHOOKSTRUCT))

# ── フックコールバック ──────────────────────────────────────
def hook_proc(nCode, wParam, lParam):
    if nCode >= 0:
        kb = lParam.contents
        vk = kb.vkCode
        scan = kb.scanCode
        
        # イベント種別の判別
        if wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
            event_type = "KeyDown"
        elif wParam in (WM_KEYUP, WM_SYSKEYUP):
            event_type = "KeyUp"
        else:
            event_type = "Unknown"
            
        # 取得したコードを16進数および10進数で出力
        print(f"[{event_type}] 仮想キーコード(vkCode): 0x{vk:02X} ({vk}), スキャンコード(scanCode): 0x{scan:02X} ({scan})")
        sys.stdout.flush()

    # フックチェーンを継続させ、OSや他アプリの入力を妨げない
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

    print("キー入力監視テストスクリプトを起動しました。")
    print("確認したいキーを押下してください。")
    print("終了するには Ctrl + C を入力してください。\n")

    msg = wt.MSG()
    try:
        while ctypes.windll.user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            ctypes.windll.user32.TranslateMessage(ctypes.byref(msg))
            ctypes.windll.user32.DispatchMessageW(ctypes.byref(msg))
    except KeyboardInterrupt:
        pass
    finally:
        ctypes.windll.user32.UnhookWindowsHookEx(hook)
        print("\n監視を終了しました。")

if __name__ == "__main__":
    main()