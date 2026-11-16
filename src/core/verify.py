"""Windows Hello 系统验证（PIN / 指纹 / 人脸）封装。

UserConsentVerifier 会弹出系统级验证窗口，应用无法拿到 PIN 值本身。
通过 IUserConsentVerifierInterop 把验证窗口挂到本程序窗口上，否则系统会把它
丢到屏幕底部且不获得焦点。必须在 UI 线程、主窗口处于前台时发起：这样系统
才允许切前台，并在对话框关闭后把焦点还给主窗口。等待结果用轮询，不要阻塞。
"""

import ctypes
import uuid
from dataclasses import dataclass

import winrt._winrt as wrt

from .i18n import tr
from winrt.windows.security.credentials.ui import (
    UserConsentVerificationResult,
    UserConsentVerifier,
)

_INTEROP_IID = uuid.UUID("{39E050C3-4E74-441A-8DC0-B81104DF949C}")
_ASYNC_IID = uuid.UUID("{fd596ffd-2318-558f-9dbe-d21df43764a5}")
_ASYNC_INFO_IID = uuid.UUID("{00000036-0000-0000-C000-000000000046}")

_RESULT_INDEX = 8    # IAsyncOperation::GetResults（6/7 是 put/get_Completed）
_STATUS_INDEX = 7    # IAsyncInfo::get_Status（QI 到 IAsyncInfo 后）

HRESULT = ctypes.c_int32

_RESULT_MSG = {
    UserConsentVerificationResult.DEVICE_NOT_PRESENT: "系统未提供可用的验证设备",
    UserConsentVerificationResult.NOT_CONFIGURED_FOR_USER: "当前用户尚未配置 Windows Hello",
    UserConsentVerificationResult.DISABLED_BY_POLICY: "Windows Hello 已被系统策略禁用",
    UserConsentVerificationResult.DEVICE_BUSY: "验证设备正忙，请稍后重试",
    UserConsentVerificationResult.RETRIES_EXHAUSTED: "验证失败次数过多",
    UserConsentVerificationResult.CANCELED: "已取消验证",
}


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    code: str    # verified / canceled / unavailable / retries_exhausted / error ...
    message: str


def start_verification(message: str, hwnd: int) -> tuple[VerifyResult | None, "VerificationSession | None"]:
    """弹出系统验证窗口；必须在 UI 线程调用。

    返回 (立即结果, 会话)：创建失败时直接返回结果；否则返回会话，
    由界面用 status() 轮询，完成时调用 finish() 取结果。
    """
    try:
        return None, _open_for_window(int(hwnd), message)
    except Exception as exc:
        return VerifyResult(False, "error", tr("验证调用失败：{err}", err=exc)), None


class VerificationSession:
    """一次进行中的系统验证（UI 线程创建，status() 非阻塞轮询）。"""

    def __init__(self, op):
        self._op = op
        self._info = ctypes.c_void_p()
        self._released = False
        query = ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.POINTER(_GUID),
                                   ctypes.POINTER(ctypes.c_void_p))(_slot(op, 0))
        hr = query(op, ctypes.byref(_guid(_ASYNC_INFO_IID)), ctypes.byref(self._info))
        if hr < 0 or not self._info.value:
            self.release()
            raise RuntimeError(tr("获取异步状态接口失败（hr={hr}）", hr=hr))

    def status(self) -> int:
        """0=Started，1=Completed，2=Canceled，3=Error。"""
        status = ctypes.c_int32()
        hr = ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p,
                                ctypes.POINTER(ctypes.c_int32))(
            _slot(self._info, _STATUS_INDEX))(self._info, ctypes.byref(status))
        if hr < 0:
            raise RuntimeError(tr("读取验证状态失败（hr={hr}）", hr=hr))
        return status.value

    def finish(self) -> VerifyResult:
        """读取验证结果并释放接口。"""
        try:
            status = self.status()
            if status == 2:
                return _from_result(UserConsentVerificationResult.CANCELED)
            if status != 1:
                return VerifyResult(False, "error", tr("验证过程出错"))
            value = ctypes.c_int32()
            hr = ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p,
                                    ctypes.POINTER(ctypes.c_int32))(
                _slot(self._op, _RESULT_INDEX))(self._op, ctypes.byref(value))
            if hr < 0:
                return VerifyResult(False, "error", tr("读取验证结果失败（hr={hr}）", hr=hr))
            return _from_result(UserConsentVerificationResult(value.value))
        finally:
            self.release()

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        for ptr in (self._info, self._op):
            if ptr and ptr.value:
                ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(_slot(ptr, 2))(ptr)


def _from_result(result) -> VerifyResult:
    if result == UserConsentVerificationResult.VERIFIED:
        return VerifyResult(True, "verified", tr("验证通过"))
    code = "retries_exhausted" if result == UserConsentVerificationResult.RETRIES_EXHAUSTED else "failed"
    return VerifyResult(False, code, tr(_RESULT_MSG.get(result, "验证失败")))


# ---------- 底层 interop 调用（ctypes 直连 WinRT ABI） ----------

class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
                ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8)]


def _guid(value: uuid.UUID) -> _GUID:
    return _GUID.from_buffer_copy(value.bytes_le)


def _slot(ptr, index):
    vtbl = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_void_p))[0]
    return ctypes.cast(vtbl + index * 8, ctypes.POINTER(ctypes.c_void_p))[0]


_combase = ctypes.WinDLL("combase.dll")
_combase.WindowsCreateString.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32,
                                         ctypes.POINTER(ctypes.c_void_p)]
_combase.WindowsCreateString.restype = HRESULT
_combase.WindowsDeleteString.argtypes = [ctypes.c_void_p]

_capsule_ptr = ctypes.pythonapi.PyCapsule_GetPointer
_capsule_ptr.restype = ctypes.c_void_p
_capsule_ptr.argtypes = [ctypes.py_object, ctypes.c_char_p]


def _open_for_window(hwnd: int, message: str) -> VerificationSession:
    factory = wrt.get_activation_factory(UserConsentVerifier, _INTEROP_IID)
    interop = _capsule_ptr(ctypes.py_object(factory), b"winrt.interface")

    request = ctypes.WINFUNCTYPE(
        HRESULT, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
        ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p))(_slot(interop, 6))

    hstr = ctypes.c_void_p()
    _combase.WindowsCreateString(message, len(message), ctypes.byref(hstr))
    op = ctypes.c_void_p()
    try:
        hr = request(interop, ctypes.c_void_p(hwnd), hstr,
                     ctypes.byref(_guid(_ASYNC_IID)), ctypes.byref(op))
    finally:
        _combase.WindowsDeleteString(hstr)
    if hr < 0 or not op.value:
        raise RuntimeError(tr("验证窗口调用失败（hr={hr}）", hr=hr))
    return VerificationSession(op)


# ---------- 验证对话框前台化与焦点交还 ----------
# interop 只负责把对话框贴到本程序窗口上，不会自动激活它；主窗口处于前台时
# 普通 SetForegroundWindow 就会被允许，不要用 AttachThreadInput 硬抢（那会
# 破坏激活链）。对话框关闭时系统会把前台交给激活历史里的上一个窗口（常见是
# 启动本程序的 IDE），所以验证期间把主窗口与对话框一起置顶：交接瞬间那个
# 窗口只能在置顶带之下激活，屏幕上什么都不会变；置顶在焦点收回后再撤销。

_PROMPT_CLASS = "Credential Dialog Xaml Host"

_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002
_SWP_NOACTIVATE = 0x0010

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_EnumProc = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
_user32.EnumWindows.argtypes = [_EnumProc, ctypes.c_void_p]
_user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
_user32.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
_user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
_user32.SetWindowPos.argtypes = [
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
    ctypes.c_int, ctypes.c_int, ctypes.c_uint,
]
_user32.BringWindowToTop.argtypes = [ctypes.c_void_p]
_user32.GetForegroundWindow.restype = ctypes.c_void_p
_user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
_user32.GetWindowThreadProcessId.restype = ctypes.c_uint32
_user32.AttachThreadInput.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_int]
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.GetCurrentThreadId.restype = ctypes.c_uint32


def foreground_window() -> int:
    """当前前台窗口句柄。"""
    return int(_user32.GetForegroundWindow() or 0)


def activate_window(hwnd: int) -> bool:
    """把本程序窗口切回前台。

    验证对话框关闭时系统会把焦点交给激活历史里的上一个窗口（例如 IDE），
    所以在检测到验证结束的同一时刻调用；普通调用被前台锁拒绝时附加输入线程重试。
    """
    try:
        if _user32.SetForegroundWindow(hwnd):
            return True
        fg = _user32.GetForegroundWindow()
        fg_thread = _user32.GetWindowThreadProcessId(fg, None)
        cur_thread = _kernel32.GetCurrentThreadId()
        attached = bool(_user32.AttachThreadInput(cur_thread, fg_thread, True))
        try:
            return bool(_user32.SetForegroundWindow(hwnd))
        finally:
            if attached:
                _user32.AttachThreadInput(cur_thread, fg_thread, False)
    except Exception:
        return False


def prompt_windows() -> set[int]:
    """枚举当前可见的系统验证对话框窗口。"""
    found: set[int] = set()

    def collect(hwnd, _):
        if _user32.IsWindowVisible(hwnd):
            name = ctypes.create_unicode_buffer(256)
            _user32.GetClassNameW(hwnd, name, 256)
            if name.value == _PROMPT_CLASS:
                found.add(hwnd)
        return 1

    _user32.EnumWindows(_EnumProc(collect), 0)
    return found


def set_topmost(hwnd: int, on: bool) -> bool:
    """置顶 / 取消置顶，不改位置也不改焦点。"""
    try:
        return bool(_user32.SetWindowPos(
            int(hwnd), -1 if on else -2, 0, 0, 0, 0,
            _SWP_NOSIZE | _SWP_NOMOVE | _SWP_NOACTIVATE))
    except Exception:
        return False


def activate_prompt(hwnd: int, guard_hwnd: int) -> bool:
    """把验证对话框切到前台，并让 guard_hwnd 一起置顶。

    对话框属于 CredentialUIBroker 进程且没有 owner：关闭时系统会把前台交给
    激活历史里的上一个窗口（常常是启动本程序的 IDE）。把主窗口与对话框都
    放在置顶带（对话框在最上层）后，那个窗口只能在置顶带之下激活，屏幕上不会
    出现任何切换；主窗口的键盘焦点稍后由轮询立即收回。
    """
    try:
        # 顺序固定：主窗口先占住最上层，再把对话框压到它上面
        if not set_topmost(guard_hwnd, True):
            return False
        if not set_topmost(hwnd, True):
            set_topmost(guard_hwnd, False)
            return False
        activated = bool(_user32.SetForegroundWindow(hwnd))
        if activated:
            _user32.BringWindowToTop(hwnd)
        return True
    except Exception:
        return False
