"""
window_resize.py
アクティブウィンドウのサイズ・位置をディスプレイサイズの割合で変更するモジュール。

座標系はアクティブウィンドウが属するモニターを基準とする。
main.py（remaps.py）から呼び出して使用する。

使用例:
    # 幅70%, 高さ60%, 左から10%, 上から20% の位置へ移動
    resize_active_window(w_ratio=0.70, h_ratio=0.60, x_ratio=0.10, y_ratio=0.20)

    # サイズのみ変更（位置は現在地のまま）
    resize_active_window(w_ratio=0.70, h_ratio=0.60)
"""

import ctypes
import ctypes.wintypes as wt

user32 = ctypes.windll.user32

# ── Win32 定数 ─────────────────────────────────────────────
SWP_NOMOVE     = 0x0002
SWP_NOZORDER   = 0x0004
SWP_NOACTIVATE = 0x0010
SW_RESTORE     = 9     # 最大化・最小化を解除して通常状態に戻す

# ── MONITORINFO 構造体 ─────────────────────────────────────
class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize",    ctypes.c_ulong),
        ("rcMonitor", RECT),   # モニター全体の矩形
        ("rcWork",    RECT),   # タスクバーを除いた作業領域
        ("dwFlags",   ctypes.c_ulong),
    ]

MONITOR_DEFAULTTONEAREST = 0x00000002


def _get_monitor_work_area(hwnd) -> tuple[int, int, int, int]:
    """
    hwnd が属するモニターの作業領域を返す。
    Returns: (left, top, width, height)
    """
    hmonitor = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    ctypes.windll.user32.GetMonitorInfoW(hmonitor, ctypes.byref(info))
    rc = info.rcWork
    return rc.left, rc.top, rc.right - rc.left, rc.bottom - rc.top


def resize_active_window(
    w_ratio: float,
    h_ratio: float,
    x_ratio: float | None = None,
    y_ratio: float | None = None,
) -> bool:
    """
    現在フォーカスを持つウィンドウを、属するモニターのサイズを基準に
    割合でリサイズ（および移動）する。

    最大化状態のままリサイズするとスナップが残り、ドラッグ時に
    最大化前のサイズに戻る問題があるため、先に SW_RESTORE で通常状態に戻す。

    Parameters
    ----------
    w_ratio : ウィンドウ幅  / モニター作業幅  の比率（0.0 〜 1.0）
    h_ratio : ウィンドウ高さ / モニター作業高さ の比率（0.0 〜 1.0）
    x_ratio : モニター作業領域左端からの X オフセット比率（None = 移動しない）
    y_ratio : モニター作業領域上端からの Y オフセット比率（None = 移動しない）

    Returns
    -------
    bool : 成功時 True
    """
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return False

    # 最大化・スナップ状態を解除してから操作する
    # これをしないと SetWindowPos 後もスナップが残り、
    # ドラッグ移動時に最大化前のサイズに戻ってしまう
    user32.ShowWindow(hwnd, SW_RESTORE)

    mon_left, mon_top, mon_w, mon_h = _get_monitor_work_area(hwnd)

    width  = int(mon_w * w_ratio)
    height = int(mon_h * h_ratio)

    if x_ratio is None or y_ratio is None:
        # 位置変更なし
        flags = SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE
        x = 0
        y = 0
    else:
        flags = SWP_NOZORDER | SWP_NOACTIVATE
        x = mon_left + int(mon_w * x_ratio)
        y = mon_top  + int(mon_h * y_ratio)

    result = user32.SetWindowPos(
        hwnd, None,
        x, y,
        width, height,
        flags,
    )
    return bool(result)