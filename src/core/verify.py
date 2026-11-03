"""Windows Hello 系统验证（PIN / 指纹 / 人脸）封装。

UserConsentVerifier 会弹出系统级验证窗口，应用无法拿到 PIN 值本身。
request_verification 是阻塞调用，需在后台线程中执行，避免冻结界面。
"""

from dataclasses import dataclass

from winrt.windows.security.credentials.ui import (
    UserConsentVerificationResult,
    UserConsentVerifier,
    UserConsentVerifierAvailability,
)

_AVAIL_MSG = {
    UserConsentVerifierAvailability.DEVICE_NOT_PRESENT: "系统未提供可用的验证设备",
    UserConsentVerifierAvailability.NOT_CONFIGURED_FOR_USER: "当前用户尚未配置 Windows Hello",
    UserConsentVerifierAvailability.DISABLED_BY_POLICY: "Windows Hello 已被系统策略禁用",
    UserConsentVerifierAvailability.DEVICE_BUSY: "验证设备正忙，请稍后重试",
}

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


def availability() -> tuple[bool, str]:
    """检查当前系统是否可执行 Windows Hello 验证。"""
    try:
        avail = UserConsentVerifier.check_availability_async().get()
    except Exception as exc:  # 系统 API 不可用时不影响程序其余功能
        return False, f"无法调用系统验证：{exc}"
    if avail == UserConsentVerifierAvailability.AVAILABLE:
        return True, ""
    return False, _AVAIL_MSG.get(avail, "系统验证不可用")


def request_verification(message: str) -> VerifyResult:
    """弹出系统验证窗口并等待结果（阻塞，需在后台线程调用）。"""
    ok, reason = availability()
    if not ok:
        return VerifyResult(False, "unavailable", reason)

    try:
        result = UserConsentVerifier.request_verification_async(message).get()
    except Exception as exc:
        return VerifyResult(False, "error", f"验证调用失败：{exc}")

    if result == UserConsentVerificationResult.VERIFIED:
        return VerifyResult(True, "verified", "验证通过")

    code = "retries_exhausted" if result == UserConsentVerificationResult.RETRIES_EXHAUSTED else "failed"
    return VerifyResult(False, code, _RESULT_MSG.get(result, "验证失败"))
