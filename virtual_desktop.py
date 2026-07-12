"""
virtual_desktop.py
Windows 仮想デスクトップの切り替え・ウィンドウ移動を行うモジュール。

元は virtual_desktoper/ 以下に独立アプリ（SylphyHorn移植版）として実装されていたが、
専用の keyboard ライブラリによるグローバルフックが key_remapper 本体の
低レベルキーボードフックと競合し、数時間で無応答になる不具合があったため、
window_resize.py / calc_overlay.py と同様に単一ファイルへ再構成し、
main.py の同一フックから直接呼び出す形に統合した。

キーボードショートカット（main.py から呼び出す）:
    Alt+Q       : switch_left()               仮想デスクトップを左へ切り替え
    Alt+W       : switch_right()              仮想デスクトップを右へ切り替え
    Alt+Shift+Z : move_left(switch=True)      ウィンドウを左のデスクトップへ移動して切り替え
    Alt+Shift+X : move_right(switch=True)     ウィンドウを右のデスクトップへ移動して切り替え
    Alt+Shift+D : toggle_pin_window()         ウィンドウのピン留め（全デスクトップ表示）を切り替え

使用例:
    import virtual_desktop
    virtual_desktop.switch_left()
    virtual_desktop.switch_right()
    virtual_desktop.move_left(switch=True)
    virtual_desktop.move_right(switch=True)
    virtual_desktop.toggle_pin_window()
"""

import ctypes
import ctypes.wintypes as wt
import sys
import winsound
from typing import Optional

import _ctypes
import win32con
import win32gui
import win32process
import pyvda.pyvda as _pyvda_module
from pyvda import AppView, VirtualDesktop, get_virtual_desktops
from pyvda.utils import Managers

import key_logger


def _reconnect_com() -> None:
    """
    pyvdaが保持しているCOMプロキシ（Explorerのシェルへの接続）を作り直す。

    Explorer.exeが再起動された場合（クラッシュ・手動再起動・更新など、長時間
    起動しっぱなしのアプリでは稀に起こりうる）、既存のCOMプロキシは無効化され、
    以後の呼び出しはずっと失敗し続ける。Managers.__init__を再実行することで
    現在のスレッド用のプロキシを取り直す。
    """
    try:
        Managers.__init__(_pyvda_module.managers)
        key_logger.info("virtual_desktop: COM接続を再初期化しました")
    except Exception:
        key_logger.exception("virtual_desktop: COM再接続に失敗")


def _com_retry(func, *args, **kwargs):
    """COM呼び出しをラップし、失敗時にCOM接続を再初期化して1回だけ再試行する。"""
    try:
        return func(*args, **kwargs)
    except _ctypes.COMError:
        key_logger.warning("virtual_desktop: COM呼び出し失敗、再接続してリトライします")
        _reconnect_com()
        return func(*args, **kwargs)


def _safe(func):
    """
    公開API関数を包み、想定外の例外を握りつぶさずログしてからNoneを返す。

    main.py 側のフックコールバックは ctypes の CFUNCTYPE 経由で呼ばれるため、
    ここで捕まえずに例外を伝播させると、pythonw.exe（コンソール無し）環境では
    トレースバックがどこにも表示されず「何も起きていないように見えて実際は
    落ちている」状態になり、原因調査ができなくなる。
    """
    import functools

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception:
            key_logger.exception(f"virtual_desktop: {func.__name__} で例外発生")
            _play_error_sound()
            return None

    return wrapper


# ── 自ウィンドウ誤操作防止 ─────────────────────────────────
def get_foreground_hwnd() -> Optional[int]:
    hwnd = win32gui.GetForegroundWindow()
    return hwnd or None


def get_window_center(hwnd: int) -> Optional[tuple[int, int]]:
    """ウィンドウの中央座標（スクリーン座標）を返す。取得失敗時はNone。"""
    try:
        rect = wt.RECT()
        if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
        return ((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2)
    except Exception:
        key_logger.debug(f"virtual_desktop: ウィンドウ中央座標取得失敗 hwnd={hwnd}")
        return None


def _play_error_sound() -> None:
    try:
        winsound.MessageBeep(winsound.MB_ICONASTERISK)
    except Exception:
        key_logger.debug("virtual_desktop: エラー音再生に失敗")


def all_desktops():
    return _com_retry(get_virtual_desktops)


def current_desktop() -> VirtualDesktop:
    return _com_retry(VirtualDesktop.current)


def get_left(current: Optional[VirtualDesktop] = None) -> Optional[VirtualDesktop]:
    """左隣のデスクトップを返す。先頭の場合は末尾へループする。"""
    current = current or current_desktop()
    n = current.number  # 1-indexed
    if n > 1:
        return VirtualDesktop(n - 1)

    desktops = all_desktops()
    if len(desktops) >= 2:
        return desktops[-1]
    return None


def get_right(current: Optional[VirtualDesktop] = None) -> Optional[VirtualDesktop]:
    """右隣のデスクトップを返す。末尾の場合は先頭へループする。"""
    current = current or current_desktop()
    desktops = all_desktops()
    n = current.number
    if n < len(desktops):
        return VirtualDesktop(n + 1)

    if len(desktops) >= 2:
        return desktops[0]
    return None


# ---------------------------------------------------------------------------
# 切り替え（本家 SylphyHorn の Switch() 相当）
#
# Windows標準の SwitchDesktop を呼ぶ前後で次のトリックを使い、
# スライドアニメーションを表示させない（ウィンドウが動いて見えない）:
#   1. 切替前に Immersive Shell ウィンドウへ WM_ACTIVATE を送りつけ、シェルに
#      「アクティブ化中」と誤認させる
#   2. 切替後、移動先デスクトップの代表ウィンドウを強制的にフォアグラウンド化する
# ---------------------------------------------------------------------------

if sys.getwindowsversion().build >= 22000:
    _IMMERSIVE_SHELL_CLASS = "ApplicationManager_ImmersiveShellWindow"
    _TASK_VIEW_CLASS = "XamlExplorerHostIslandWindow"
else:
    _IMMERSIVE_SHELL_CLASS = "ApplicationManager_DesktopShellWindow"
    _TASK_VIEW_CLASS = "Windows.UI.Core.CoreWindow"

_TASKBAR_CLASS = "Shell_TrayWnd"

_immersive_shell_hwnd: Optional[int] = None
_taskbar_hwnd: Optional[int] = None


def _get_cached_shell_handles() -> tuple[int, int]:
    global _immersive_shell_hwnd, _taskbar_hwnd
    if _immersive_shell_hwnd is None:
        _immersive_shell_hwnd = win32gui.FindWindow(_IMMERSIVE_SHELL_CLASS, None) or 0
    if _taskbar_hwnd is None:
        _taskbar_hwnd = win32gui.FindWindow(_TASKBAR_CLASS, None) or 0
    return _immersive_shell_hwnd, _taskbar_hwnd


def _is_pinned_window_or_default(hwnd: int) -> bool:
    try:
        return AppView(hwnd=hwnd).is_pinned()
    except Exception:
        return False


def _get_first_window_on_desktop(target: VirtualDesktop) -> int:
    """移動先デスクトップに存在する代表ウィンドウの hwnd を返す（無ければ 0）。"""
    try:
        for view in target.apps_by_z_order(include_pinned=False):
            return view.hwnd
    except Exception:
        key_logger.debug("virtual_desktop: apps_by_z_order 失敗")
    return 0


def _force_send_activation_message(target_hwnd: int, foreground_hwnd: int) -> None:
    target_tid = win32process.GetWindowThreadProcessId(target_hwnd)[0]
    foreground_tid = win32process.GetWindowThreadProcessId(foreground_hwnd)[0]

    if target_tid == foreground_tid:
        win32gui.SendMessage(target_hwnd, win32con.WM_ACTIVATE, win32con.WA_ACTIVE, target_hwnd)
        return

    attached = win32process.AttachThreadInput(target_tid, foreground_tid, True)
    try:
        win32gui.SendMessage(target_hwnd, win32con.WM_ACTIVATE, win32con.WA_ACTIVE, target_hwnd)
    finally:
        if attached:
            win32process.AttachThreadInput(target_tid, foreground_tid, False)


def _force_set_foreground_window(target_hwnd: int, foreground_hwnd: int) -> None:
    target_tid = win32process.GetWindowThreadProcessId(target_hwnd)[0]
    foreground_tid = win32process.GetWindowThreadProcessId(foreground_hwnd)[0]

    if target_tid == foreground_tid:
        win32gui.SetForegroundWindow(target_hwnd)
        win32gui.BringWindowToTop(target_hwnd)
        return

    attached = win32process.AttachThreadInput(target_tid, foreground_tid, True)
    try:
        win32gui.SendMessage(foreground_hwnd, win32con.WM_ACTIVATE, win32con.WA_INACTIVE, foreground_hwnd)
        win32gui.SendMessage(target_hwnd, win32con.WM_ACTIVATE, win32con.WA_ACTIVE, target_hwnd)
        win32gui.SendMessage(target_hwnd, win32con.WM_SETFOCUS, target_hwnd, 0)
        win32gui.BringWindowToTop(target_hwnd)
    finally:
        if attached:
            win32process.AttachThreadInput(target_tid, foreground_tid, False)


def switch_to(desktop: Optional[VirtualDesktop]) -> Optional[VirtualDesktop]:
    if desktop is None:
        _play_error_sound()
        return None

    try:
        current = current_desktop()
    except Exception:
        current = None

    if current is not None and current.id == desktop.id:
        return desktop

    try:
        current_hwnd = get_foreground_hwnd() or 0
        target_hwnd = _get_first_window_on_desktop(desktop)
        class_name = win32gui.GetClassName(current_hwnd) if current_hwnd else ""
        immersive_shell_hwnd, taskbar_hwnd = _get_cached_shell_handles()

        skip_trick = (
            current_hwnd == 0
            or current_hwnd == target_hwnd
            or _is_pinned_window_or_default(current_hwnd)
            or current_hwnd == taskbar_hwnd
            or class_name == _TASK_VIEW_CLASS
        )

        if skip_trick:
            desktop.go()
            return desktop

        if immersive_shell_hwnd:
            _force_send_activation_message(immersive_shell_hwnd, current_hwnd)

        desktop.go()

        if target_hwnd:
            foreground_hwnd = get_foreground_hwnd() or 0
            if target_hwnd != foreground_hwnd:
                _force_set_foreground_window(target_hwnd, foreground_hwnd)
    except Exception:
        key_logger.debug("virtual_desktop: switch トリック失敗、通常切替にフォールバック")
        desktop.go()

    return desktop


@_safe
def _switch_left_impl() -> Optional[VirtualDesktop]:
    return switch_to(get_left())


@_safe
def _switch_right_impl() -> Optional[VirtualDesktop]:
    return switch_to(get_right())


# ---------------------------------------------------------------------------
# ウィンドウ移動
# ---------------------------------------------------------------------------

def _current_app_view() -> Optional[AppView]:
    hwnd = get_foreground_hwnd()
    if hwnd is None:
        key_logger.debug("virtual_desktop: フォアグラウンドhwnd取得失敗（0またはNone）")
        return None
    try:
        return _com_retry(AppView, hwnd=hwnd)
    except Exception:
        key_logger.exception(f"virtual_desktop: AppView取得失敗 hwnd={hwnd}")
        return None


def move_active_window(target: Optional[VirtualDesktop], switch: bool) -> Optional[VirtualDesktop]:
    if target is None:
        _play_error_sound()
        return None

    view = _current_app_view()
    if view is None:
        _play_error_sound()
        return None

    try:
        view.move(target)
    except Exception:
        key_logger.debug("virtual_desktop: ウィンドウ移動失敗")
        _play_error_sound()
        return None

    if switch:
        switch_to(target)
    return target


@_safe
def _move_left_impl(switch: bool = True) -> Optional[VirtualDesktop]:
    return move_active_window(get_left(), switch)


@_safe
def _move_right_impl(switch: bool = True) -> Optional[VirtualDesktop]:
    return move_active_window(get_right(), switch)


# ---------------------------------------------------------------------------
# ピン留め通知（対象ウィンドウ中央に「ピン留めしました」等を一時表示）
# ---------------------------------------------------------------------------

class _PAINTSTRUCT(ctypes.Structure):
    _fields_ = [
        ("hdc",         wt.HDC),
        ("fErase",      wt.BOOL),
        ("rcPaint",     wt.RECT),
        ("fRestore",    wt.BOOL),
        ("fIncUpdate",  wt.BOOL),
        ("rgbReserved", ctypes.c_byte * 32),
    ]


# タスクトレイアイコン・calc_overlayと揃えた配色
_NOTIFY_COLOR_BG   = (0x1c, 0x1c, 0x1e)
_NOTIFY_COLOR_TEXT = (0xf2, 0xf2, 0xf2)

_NOTIFY_WIDTH, _NOTIFY_HEIGHT = 240, 64
_NOTIFY_CORNER_RADIUS = 16
_NOTIFY_TIMER_ID = 1
_NOTIFY_DURATION_MS = 900

_notify_hwnd: Optional[int] = None
_notify_wndproc_ref = None  # GC回収防止用
_notify_bg_brush = None
_notify_font = None
_notify_text = ""


def _rgb(c) -> int:
    return c[0] | (c[1] << 8) | (c[2] << 16)


def _notify_paint(hwnd) -> None:
    ps = _PAINTSTRUCT()
    hdc = ctypes.windll.user32.BeginPaint(hwnd, ctypes.byref(ps))

    rc = wt.RECT()
    ctypes.windll.user32.GetClientRect(hwnd, ctypes.byref(rc))

    old_brush = ctypes.windll.gdi32.SelectObject(hdc, _notify_bg_brush)
    null_pen = ctypes.windll.gdi32.GetStockObject(5)  # NULL_PEN
    old_pen = ctypes.windll.gdi32.SelectObject(hdc, null_pen)
    ctypes.windll.gdi32.RoundRect(
        hdc, 0, 0, rc.right, rc.bottom, _NOTIFY_CORNER_RADIUS, _NOTIFY_CORNER_RADIUS
    )
    ctypes.windll.gdi32.SelectObject(hdc, old_pen)
    ctypes.windll.gdi32.SelectObject(hdc, old_brush)

    ctypes.windll.gdi32.SetBkMode(hdc, 1)  # TRANSPARENT
    ctypes.windll.gdi32.SetTextColor(hdc, _rgb(_NOTIFY_COLOR_TEXT))
    old_font = ctypes.windll.gdi32.SelectObject(hdc, _notify_font)
    DT_CENTER, DT_VCENTER, DT_SINGLELINE = 0x1, 0x4, 0x20
    ctypes.windll.user32.DrawTextW(
        hdc, _notify_text, -1, ctypes.byref(rc), DT_CENTER | DT_VCENTER | DT_SINGLELINE
    )
    ctypes.windll.gdi32.SelectObject(hdc, old_font)

    ctypes.windll.user32.EndPaint(hwnd, ctypes.byref(ps))


def _notify_wnd_proc(hwnd, msg, wparam, lparam):
    global _notify_hwnd

    WM_PAINT = 0x000F
    WM_ERASEBKGND = 0x0014
    WM_TIMER = 0x0113
    WM_DESTROY = 0x0002

    if msg == WM_ERASEBKGND:
        return 1  # WM_PAINTでまとめて塗るため既定の消去はしない
    if msg == WM_PAINT:
        _notify_paint(hwnd)
        return 0
    if msg == WM_TIMER:
        ctypes.windll.user32.KillTimer(hwnd, _NOTIFY_TIMER_ID)
        ctypes.windll.user32.DestroyWindow(hwnd)
        return 0
    if msg == WM_DESTROY:
        _notify_hwnd = None
        return 0
    return ctypes.windll.user32.DefWindowProcW(hwnd, msg, wparam, lparam)


def _ensure_notify_window_class() -> None:
    global _notify_wndproc_ref, _notify_bg_brush, _notify_font
    if _notify_wndproc_ref is not None:
        return

    _notify_bg_brush = ctypes.windll.gdi32.CreateSolidBrush(_rgb(_NOTIFY_COLOR_BG))
    _notify_font = ctypes.windll.gdi32.CreateFontW(
        -20, 0, 0, 0, 500, 0, 0, 0, 1, 0, 0, 0, 0, "Yu Gothic UI",
    )

    _notify_wndproc_ref = _WNDPROCTYPE(_notify_wnd_proc)
    wc = _WNDCLASSW()
    wc.style         = 0x00020000  # CS_DROPSHADOW
    wc.lpfnWndProc   = _notify_wndproc_ref
    wc.hInstance     = ctypes.windll.kernel32.GetModuleHandleW(None)
    wc.hbrBackground = None
    wc.hCursor       = ctypes.windll.user32.LoadCursorW(None, 32512)  # IDC_ARROW
    wc.lpszClassName = "KeyRemapperPinNotify"
    ctypes.windll.user32.RegisterClassW(ctypes.byref(wc))


def _show_pin_notification(target_hwnd: Optional[int], text: str) -> None:
    """target_hwnd の中央に text を一時的に表示する（約900msで自動的に消える）。"""
    global _notify_hwnd, _notify_text

    try:
        _ensure_notify_window_class()

        if _notify_hwnd:
            ctypes.windll.user32.DestroyWindow(_notify_hwnd)
            _notify_hwnd = None

        center = get_window_center(target_hwnd) if target_hwnd else None
        if center is None:
            pt = wt.POINT()
            ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
            center = (pt.x, pt.y)
        cx, cy = center

        _notify_text = text
        WS_EX_TOPMOST = 0x00000008
        WS_EX_TOOLWINDOW = 0x00000080
        WS_POPUP = 0x80000000
        hinstance = ctypes.windll.kernel32.GetModuleHandleW(None)

        _notify_hwnd = ctypes.windll.user32.CreateWindowExW(
            WS_EX_TOPMOST | WS_EX_TOOLWINDOW,
            "KeyRemapperPinNotify", "KeyRemapperPinNotify",
            WS_POPUP,
            cx - _NOTIFY_WIDTH // 2, cy - _NOTIFY_HEIGHT // 2,
            _NOTIFY_WIDTH, _NOTIFY_HEIGHT,
            None, None, hinstance, None,
        )
        if not _notify_hwnd:
            return

        try:
            pref = ctypes.c_int(2)  # DWMWCP_ROUND
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                _notify_hwnd, 33, ctypes.byref(pref), ctypes.sizeof(pref)  # DWMWA_WINDOW_CORNER_PREFERENCE
            )
        except OSError:
            pass

        SW_SHOWNOACTIVATE = 4
        ctypes.windll.user32.ShowWindow(_notify_hwnd, SW_SHOWNOACTIVATE)
        ctypes.windll.user32.SetTimer(_notify_hwnd, _NOTIFY_TIMER_ID, _NOTIFY_DURATION_MS, None)
    except Exception:
        key_logger.exception("virtual_desktop: ピン留め通知の表示に失敗")


# ---------------------------------------------------------------------------
# ピン留め（全デスクトップに表示させる）
# ---------------------------------------------------------------------------

@_safe
def _toggle_pin_window_impl() -> None:
    view = _current_app_view()
    if view is None:
        _play_error_sound()
        return

    if view.is_pinned():
        view.unpin()
        key_logger.info("virtual_desktop: ウィンドウのピン留めを解除")
        _show_pin_notification(view.hwnd, "ピン留めを解除しました")
    else:
        view.pin()
        key_logger.info("virtual_desktop: ウィンドウをピン留め")
        _show_pin_notification(view.hwnd, "ピン留めしました")


# ---------------------------------------------------------------------------
# ディスパッチ用の隠しウィンドウ
#
# WH_KEYBOARD_LL のコールバックはOSから「入力同期呼び出し」
# として同期的に呼ばれており、その呼び出し中にCOM（pyvdaが使う仮想デスクトップ
# 系API）へアウトゴーイング呼び出しをすると
#   COMError: RPC_E_CANTCALLOUT_ININPUTSYNCCALL
#   「アプリケーションが入力同期呼び出しをディスパッチしているため、呼び出せません」
# で必ず失敗する。これがVer.1で仮想デスクトップ関連の操作だけ動かなかった
# 直接の原因だった。
#
# 対策として、フックコールバックからは実処理を直接呼ばず、隠しウィンドウへ
# PostMessageW でメッセージを投げるだけにする。実処理はメッセージが
# GetMessageW/DispatchMessageW の通常のポンプで配送された時点
# （＝フックの同期呼び出しの外）で実行されるため、COM呼び出しが可能になる。
# ---------------------------------------------------------------------------

WM_APP = 0x8000
WM_VD_SWITCH_LEFT  = WM_APP + 1
WM_VD_SWITCH_RIGHT = WM_APP + 2
WM_VD_MOVE_LEFT    = WM_APP + 3
WM_VD_MOVE_RIGHT   = WM_APP + 4
WM_VD_TOGGLE_PIN   = WM_APP + 5

ctypes.windll.user32.DefWindowProcW.restype = ctypes.c_ssize_t
ctypes.windll.user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]

# argtypes未指定だと、HWND_MESSAGE(-3)のような負値の親ハンドルが64bit環境で
# 正しく符号拡張されず CreateWindowExW が ERROR_INVALID_PARAMETER で失敗する。
ctypes.windll.user32.CreateWindowExW.restype = wt.HWND
ctypes.windll.user32.CreateWindowExW.argtypes = [
    wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wt.HWND, wt.HANDLE, wt.HINSTANCE, wt.LPVOID,
]

_WNDPROCTYPE = ctypes.CFUNCTYPE(ctypes.c_ssize_t, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)


class _WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style",         wt.UINT),
        ("lpfnWndProc",   _WNDPROCTYPE),
        ("cbClsExtra",    ctypes.c_int),
        ("cbWndExtra",    ctypes.c_int),
        ("hInstance",     wt.HINSTANCE),
        ("hIcon",         wt.HANDLE),
        ("hCursor",       wt.HANDLE),
        ("hbrBackground", wt.HANDLE),
        ("lpszMenuName",  wt.LPCWSTR),
        ("lpszClassName", wt.LPCWSTR),
    ]


_dispatch_hwnd: Optional[int] = None
_dispatch_wndproc_ref = None  # GC回収防止用


def _dispatch_wnd_proc(hwnd, msg, wparam, lparam):
    if msg == WM_VD_SWITCH_LEFT:
        _switch_left_impl()
    elif msg == WM_VD_SWITCH_RIGHT:
        _switch_right_impl()
    elif msg == WM_VD_MOVE_LEFT:
        _move_left_impl(switch=bool(wparam))
    elif msg == WM_VD_MOVE_RIGHT:
        _move_right_impl(switch=bool(wparam))
    elif msg == WM_VD_TOGGLE_PIN:
        _toggle_pin_window_impl()
    return ctypes.windll.user32.DefWindowProcW(hwnd, msg, wparam, lparam)


def _ensure_dispatch_window() -> Optional[int]:
    """ディスパッチ用の隠しウィンドウを（未作成なら）作成して hwnd を返す。"""
    global _dispatch_hwnd, _dispatch_wndproc_ref

    if _dispatch_hwnd:
        return _dispatch_hwnd

    hinstance = ctypes.windll.kernel32.GetModuleHandleW(None)
    class_name = "KeyRemapperVirtualDesktopDispatch"

    _dispatch_wndproc_ref = _WNDPROCTYPE(_dispatch_wnd_proc)

    wc = _WNDCLASSW()
    wc.lpfnWndProc   = _dispatch_wndproc_ref
    wc.hInstance     = hinstance
    wc.lpszClassName = class_name
    ctypes.windll.user32.RegisterClassW(ctypes.byref(wc))

    # HWND_MESSAGE (-3) 配下のメッセージ専用ウィンドウ。画面には一切表示されない。
    HWND_MESSAGE = wt.HWND(-3)
    _dispatch_hwnd = ctypes.windll.user32.CreateWindowExW(
        0, class_name, class_name,
        0, 0, 0, 0, 0,
        HWND_MESSAGE, None, hinstance, None,
    )
    if not _dispatch_hwnd:
        key_logger.warning(f"virtual_desktop: ディスパッチウィンドウの作成に失敗 GetLastError={ctypes.GetLastError()}")
    return _dispatch_hwnd


def _post(msg: int, wparam: int = 0, lparam: int = 0) -> None:
    hwnd = _ensure_dispatch_window()
    if not hwnd:
        _play_error_sound()
        return
    ctypes.windll.user32.PostMessageW(hwnd, msg, wparam, lparam)


# ── 公開API（フック・マウスジェスチャーから呼ぶ。すべて非同期） ──────
def switch_left() -> None:
    _post(WM_VD_SWITCH_LEFT)


def switch_right() -> None:
    _post(WM_VD_SWITCH_RIGHT)


def move_left(switch: bool = True) -> None:
    _post(WM_VD_MOVE_LEFT, wparam=int(switch))


def move_right(switch: bool = True) -> None:
    _post(WM_VD_MOVE_RIGHT, wparam=int(switch))


def toggle_pin_window() -> None:
    _post(WM_VD_TOGGLE_PIN)
