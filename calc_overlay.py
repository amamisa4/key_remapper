"""
calc_overlay.py
Alt+Space で画面中央に電卓ライクな入力オーバーレイを表示するモジュール。

WindowsのEDITコントロールは可視スタイルのテーマ描画がWM_CTLCOLOREDITの
背景色指定を上書きしてしまい、狙った配色にできなかったため使わない。
テキスト・キャレットは自前でWM_PAINTに描画し、文字入力・カーソル移動・
削除もWM_CHAR/WM_KEYDOWNを自前でハンドリングする。

Enterまたは"="キーで入力された式を評価し、「式 = 結果」の形で表示する。
Escキーで閉じる。

式の評価は eval() を使わず、ast モジュールで四則演算のみを許可した
安全な評価器 (safe_eval) で行う。

見た目はタスクトレイアイコン（assets/icon.svg）と同じダーク+ブルーアクセントの
配色に統一し、角丸・ドロップシャドウを付けている。

main.py（remaps.py）から呼び出して使用する。

使用例:
    import calc_overlay
    calc_overlay.toggle_overlay()   # 表示中なら閉じる、非表示なら中央に表示
"""

import ast
import ctypes
import ctypes.wintypes as wt
import operator

user32   = ctypes.windll.user32
gdi32    = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32

# ── Win32 定数 ─────────────────────────────────────────────
WS_POPUP         = 0x80000000
WS_EX_TOPMOST    = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
CS_DROPSHADOW    = 0x00020000
SW_SHOW          = 5
SW_HIDE          = 0
SWP_NOSIZE       = 0x0001
SWP_NOZORDER     = 0x0004
WM_KEYDOWN       = 0x0100
WM_CHAR          = 0x0102
WM_SETFOCUS      = 0x0007
WM_KILLFOCUS     = 0x0008
WM_ACTIVATE      = 0x0006
WM_PAINT         = 0x000F
WM_ERASEBKGND    = 0x0014
WA_INACTIVE      = 0
VK_RETURN        = 0x0D
VK_ESCAPE        = 0x1B
VK_LEFT          = 0x25
VK_RIGHT         = 0x27
VK_HOME          = 0x24
VK_END           = 0x23
VK_DELETE        = 0x2E
MONITOR_DEFAULTTONEAREST = 0x00000002
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_ROUND = 2

WIDTH, HEIGHT = 560, 88
CORNER_RADIUS = 20
PADDING = 24
CARET_WIDTH = 2

# タスクトレイアイコン（assets/icon.svg）と揃えた配色
COLOR_BG     = (0x1c, 0x1c, 0x1e)  # 背景（アイコンの背景と同色）
COLOR_ACCENT = (0x5a, 0xc8, 0xfa)  # アクセント（アイコンの青四角と同色）
COLOR_TEXT   = (0xf2, 0xf2, 0xf2)  # 入力文字

WNDPROCTYPE = ctypes.CFUNCTYPE(ctypes.c_ssize_t, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)

# WPARAM/LPARAM・戻り値（LRESULT等）は64bit環境で32bitに収まらない値になる
# ことがあり、argtypes/restype未指定だとctypesの既定のc_int(32bit)変換で
# OverflowErrorになるため明示的に型を指定する。
user32.DefWindowProcW.restype  = ctypes.c_ssize_t
user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]


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


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize",    ctypes.c_ulong),
        ("rcMonitor", RECT),
        ("rcWork",    RECT),
        ("dwFlags",   ctypes.c_ulong),
    ]


class PAINTSTRUCT(ctypes.Structure):
    _fields_ = [
        ("hdc",         wt.HDC),
        ("fErase",      wt.BOOL),
        ("rcPaint",     wt.RECT),
        ("fRestore",    wt.BOOL),
        ("fIncUpdate",  wt.BOOL),
        ("rgbReserved", ctypes.c_byte * 32),
    ]


# ── 安全な四則演算評価器（eval()は使わない） ─────────────────
_ALLOWED_BINOPS = {
    ast.Add: operator.add, ast.Sub: operator.sub,
    ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_ALLOWED_UNARYOPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def _eval_node(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINOPS:
        return _ALLOWED_BINOPS[type(node.op)](_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARYOPS:
        return _ALLOWED_UNARYOPS[type(node.op)](_eval_node(node.operand))
    raise ValueError(f"unsupported expression: {ast.dump(node)}")


def safe_eval(expr: str):
    """四則演算・括弧・単項+-のみを許可した安全な式評価。"""
    tree = ast.parse(expr, mode="eval")
    return _eval_node(tree.body)


# ── オーバーレイウィンドウ本体 ───────────────────────────────
_frame_hwnd = None
_frame_wndproc_ref = None
_font       = None
_bg_brush   = None
_accent_pen = None

_text  = ""   # 現在の入力文字列（自前管理、EDITコントロールは使わない）
_caret = 0    # キャレット位置（文字インデックス）


def _get_active_monitor_work_area():
    """フォアグラウンドウィンドウ（無ければマウスカーソル位置）が属する
    モニターの作業領域を返す。Returns: (left, top, width, height)"""
    hwnd = user32.GetForegroundWindow()
    hmonitor = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST) if hwnd else None
    if not hmonitor:
        pt = wt.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        hmonitor = user32.MonitorFromPoint(pt, MONITOR_DEFAULTTONEAREST)
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    user32.GetMonitorInfoW(hmonitor, ctypes.byref(info))
    rc = info.rcWork
    return rc.left, rc.top, rc.right - rc.left, rc.bottom - rc.top


def _force_foreground(hwnd):
    """バックグラウンドプロセスからでも確実にフォーカスを奪う。
    グローバルフックから呼ぶだけでは SetForegroundWindow が
    Windowsのフォアグラウンドロックにより無視されることがあるため、
    現在のフォアグラウンドスレッドに入力キューを一時的にアタッチして奪う。"""
    fg_hwnd = user32.GetForegroundWindow()
    cur_thread_id = kernel32.GetCurrentThreadId()
    fg_thread_id = user32.GetWindowThreadProcessId(fg_hwnd, None) if fg_hwnd else 0

    attached = False
    if fg_thread_id and fg_thread_id != cur_thread_id:
        attached = bool(user32.AttachThreadInput(fg_thread_id, cur_thread_id, True))

    user32.ShowWindow(hwnd, SW_SHOW)
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)

    if attached:
        user32.AttachThreadInput(fg_thread_id, cur_thread_id, False)


def _rgb(c):
    return c[0] | (c[1] << 8) | (c[2] << 16)


# ── テキスト編集（自前実装） ───────────────────────────────
def _set_text(new_text, caret=None):
    global _text, _caret
    _text = new_text
    _caret = len(new_text) if caret is None else max(0, min(caret, len(new_text)))
    _redraw()


def _insert_char(ch):
    global _text, _caret
    _text = _text[:_caret] + ch + _text[_caret:]
    _caret += 1
    _redraw()


def _backspace():
    global _text, _caret
    if _caret > 0:
        _text = _text[:_caret - 1] + _text[_caret:]
        _caret -= 1
        _redraw()


def _delete_forward():
    global _text
    if _caret < len(_text):
        _text = _text[:_caret] + _text[_caret + 1:]
        _redraw()


def _move_caret_to(pos):
    global _caret
    _caret = max(0, min(len(_text), pos))
    _redraw()


def _evaluate_current():
    """入力された式を評価し、「式 = 結果」の形でテキストを置き換える（式は消さない）。"""
    text = _text.strip()
    if not text:
        return

    # 既に "式 = 結果" の形になっていれば、式の部分だけを再評価する（Enter連打対策）
    expr = text.split(" = ")[0].strip()
    if not expr:
        return

    try:
        result = safe_eval(expr)
    except Exception:
        new_text = f"{expr} = エラー"
    else:
        if isinstance(result, float) and result.is_integer():
            result = int(result)
        new_text = f"{expr} = {result}"

    _set_text(new_text)  # キャレットは末尾（式は消さない）


def _redraw():
    if _frame_hwnd:
        user32.InvalidateRect(_frame_hwnd, None, False)


# ── キャレット位置計算・描画 ──────────────────────────────────
def _text_width(hdc, text):
    size = wt.SIZE()
    gdi32.GetTextExtentPoint32W(hdc, text, len(text), ctypes.byref(size))
    return size.cx


def _position_caret(hwnd):
    hdc = user32.GetDC(hwnd)
    old_font = gdi32.SelectObject(hdc, _font)
    x = PADDING + _text_width(hdc, _text[:_caret])
    gdi32.SelectObject(hdc, old_font)
    user32.ReleaseDC(hwnd, hdc)
    user32.SetCaretPos(x, (HEIGHT - 32) // 2)


def _paint_frame(hwnd):
    ps = PAINTSTRUCT()
    hdc = user32.BeginPaint(hwnd, ctypes.byref(ps))
    user32.HideCaret(hwnd)

    rc = wt.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rc))

    old_brush = gdi32.SelectObject(hdc, _bg_brush)
    old_pen = gdi32.SelectObject(hdc, _accent_pen)
    gdi32.RoundRect(hdc, 0, 0, rc.right, rc.bottom, CORNER_RADIUS, CORNER_RADIUS)
    gdi32.SelectObject(hdc, old_pen)
    gdi32.SelectObject(hdc, old_brush)

    gdi32.SetBkMode(hdc, 1)  # TRANSPARENT
    gdi32.SetTextColor(hdc, _rgb(COLOR_TEXT))
    old_font = gdi32.SelectObject(hdc, _font)
    text_rc = wt.RECT(PADDING, 0, rc.right - PADDING, rc.bottom)
    DT_LEFT, DT_VCENTER, DT_SINGLELINE = 0x0, 0x4, 0x20
    user32.DrawTextW(hdc, _text, -1, ctypes.byref(text_rc), DT_LEFT | DT_VCENTER | DT_SINGLELINE)
    gdi32.SelectObject(hdc, old_font)

    user32.EndPaint(hwnd, ctypes.byref(ps))

    if user32.GetFocus() == hwnd:
        _position_caret(hwnd)
        user32.ShowCaret(hwnd)


def _frame_wnd_proc(hwnd, msg, wparam, lparam):
    if msg == WM_ACTIVATE:
        if (wparam & 0xFFFF) == WA_INACTIVE:
            user32.ShowWindow(hwnd, SW_HIDE)
        return 0
    if msg == WM_SETFOCUS:
        user32.CreateCaret(hwnd, None, CARET_WIDTH, 32)
        _position_caret(hwnd)
        user32.ShowCaret(hwnd)
        return 0
    if msg == WM_KILLFOCUS:
        user32.HideCaret(hwnd)
        user32.DestroyCaret()
        return 0
    if msg == WM_ERASEBKGND:
        return 1  # WM_PAINTでまとめて塗るため既定の消去はしない
    if msg == WM_PAINT:
        _paint_frame(hwnd)
        return 0
    if msg == WM_KEYDOWN:
        if wparam == VK_RETURN:
            _evaluate_current()
            return 0
        if wparam == VK_ESCAPE:
            hide_overlay()
            return 0
        if wparam == VK_LEFT:
            _move_caret_to(_caret - 1)
            return 0
        if wparam == VK_RIGHT:
            _move_caret_to(_caret + 1)
            return 0
        if wparam == VK_HOME:
            _move_caret_to(0)
            return 0
        if wparam == VK_END:
            _move_caret_to(len(_text))
            return 0
        if wparam == VK_DELETE:
            _delete_forward()
            return 0
        return 0
    if msg == WM_CHAR:
        ch = wparam
        if ch in (0x0D, 0x1B):  # Enter/Esc（WM_KEYDOWN側で処理済み、ビープ音だけ防ぐ）
            return 0
        if ch == ord("="):
            # "=" 自体は式の一部として入力させず、即座に評価をトリガーする
            _evaluate_current()
            return 0
        if ch == 0x08:  # Backspace
            _backspace()
            return 0
        if ch >= 0x20:  # 制御文字以外の printable
            _insert_char(chr(ch))
            return 0
        return 0
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)


def _ensure_window():
    global _frame_hwnd, _frame_wndproc_ref, _font, _bg_brush, _accent_pen
    if _frame_hwnd:
        return

    hinstance = kernel32.GetModuleHandleW(None)
    class_name = "KeyRemapperCalcOverlay"

    _bg_brush   = gdi32.CreateSolidBrush(_rgb(COLOR_BG))
    _accent_pen = gdi32.CreatePen(0, 2, _rgb(COLOR_ACCENT))  # PS_SOLID, 2px
    _font = gdi32.CreateFontW(
        -28, 0, 0, 0, 500, 0, 0, 0,
        1, 0, 0, 0, 0, "Yu Gothic UI",
    )

    _frame_wndproc_ref = WNDPROCTYPE(_frame_wnd_proc)
    wc = WNDCLASSW()
    wc.style         = CS_DROPSHADOW
    wc.lpfnWndProc   = _frame_wndproc_ref
    wc.hInstance     = hinstance
    wc.hbrBackground = None
    wc.hCursor       = user32.LoadCursorW(None, 32512)  # IDC_ARROW
    wc.lpszClassName = class_name
    user32.RegisterClassW(ctypes.byref(wc))

    _frame_hwnd = user32.CreateWindowExW(
        WS_EX_TOPMOST | WS_EX_TOOLWINDOW,
        class_name, class_name,
        WS_POPUP,
        0, 0, WIDTH, HEIGHT,
        None, None, hinstance, None,
    )

    # Windows 11: ウィンドウ自体の角も丸める（非対応環境では無視）
    try:
        pref = ctypes.c_int(DWMWCP_ROUND)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            _frame_hwnd, DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(pref), ctypes.sizeof(pref),
        )
    except OSError:
        pass


def show_overlay():
    """オーバーレイを画面中央に表示し、入力にフォーカスする。"""
    _ensure_window()

    mon_left, mon_top, mon_w, mon_h = _get_active_monitor_work_area()
    x = mon_left + (mon_w - WIDTH) // 2
    y = mon_top + (mon_h - HEIGHT) // 2
    user32.SetWindowPos(_frame_hwnd, None, x, y, 0, 0, SWP_NOSIZE | SWP_NOZORDER)

    _set_text("")
    _force_foreground(_frame_hwnd)
    user32.SetFocus(_frame_hwnd)


def hide_overlay():
    """オーバーレイを非表示にする。"""
    if _frame_hwnd:
        user32.ShowWindow(_frame_hwnd, SW_HIDE)


def is_visible() -> bool:
    return bool(_frame_hwnd) and bool(user32.IsWindowVisible(_frame_hwnd))


def toggle_overlay():
    """表示中なら閉じる、非表示なら画面中央に表示する。"""
    if is_visible():
        hide_overlay()
    else:
        show_overlay()
