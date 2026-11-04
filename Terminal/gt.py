"""gt (Git Tool) - 终端 Git 辅助工具。

用法:
    gt          交互式推送
    gt logout   清理本地 Git 凭据（Windows）
"""

import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata

try:
    import msvcrt
except ImportError:  # 非 Windows
    msvcrt = None

MODE_NORMAL = "normal"
MODE_ALL = "all"
MODE_MIRROR = "mirror"

CANCEL_NO = "否（取消）"
MIRROR_YES = "是（执行镜像推送）"
DELETE_YES = "是（删除）"

ENV = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}

KEY_ENTER = b"\r"
KEY_ESC = b"\x1b"
KEY_CTRL_C = b"\x03"
KEY_SPACE = b" "
KEY_UP = b"\xe0H"
KEY_DOWN = b"\xe0P"

C_RESET = "\033[0m"
C_GRAY = "\033[90m"
C_CYAN = "\033[36m"
C_BOLD_CYAN = "\033[1;36m"
C_GREEN = "\033[32m"
C_BOLD_GREEN = "\033[1;32m"
C_RED = "\033[1;31m"
C_YELLOW = "\033[33m"

POINTER = "❯"

_output_lines = 0


class InteractiveExit(Exception):
    """用户按下 Esc 或 Ctrl+C 退出交互。"""


def emit(message=""):
    """输出一行并记录显示行数，用于退出时清理。"""
    global _output_lines
    text = str(message)
    sys.stdout.write(text + "\n")
    sys.stdout.flush()
    _output_lines += _visual_lines(text, _terminal_width())


def clear_session():
    """擦除本次程序产生的全部输出。"""
    global _output_lines
    if _output_lines > 0:
        sys.stdout.write(f"\033[{_output_lines}A\r\033[J")
        sys.stdout.flush()
        _output_lines = 0


def red(text):
    return f"{C_RED}{text}{C_RESET}"


def green(text):
    return f"{C_GREEN}{text}{C_RESET}"


def yellow(text):
    return f"{C_YELLOW}{text}{C_RESET}"


def bold_cyan(text):
    return f"{C_BOLD_CYAN}{text}{C_RESET}"


def available():
    """当前环境是否支持交互。"""
    return msvcrt is not None and sys.stdin.isatty() and sys.stdout.isatty()


def enable_vt():
    """在 Windows 控制台开启 VT100 转义序列。"""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        kernel32.GetConsoleMode(handle, ctypes.byref(mode))
        kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        pass


def _get_key():
    ch = msvcrt.getch()
    if ch in (b"\xe0", b"\x00"):
        return ch + msvcrt.getch()
    return ch


def _text_width(text):
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def _visual_lines(text, width):
    """按终端宽度计算一段文本实际占用的行数。"""
    plain = _ANSI_RE.sub("", text)
    rows = 0
    for line in plain.split("\n"):
        rows += max(1, -(-_text_width(line) // width))
    return rows


def _fit(text, width):
    """按终端显示宽度截断，避免折行导致重绘行数计算错误。"""
    if width <= 0:
        return ""
    if _text_width(text) <= width:
        return text
    kept = []
    used = 0
    for ch in text:
        char_width = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if used + char_width > width - 1:
            break
        kept.append(ch)
        used += char_width
    return "".join(kept) + "…"


def _terminal_width():
    return max(20, shutil.get_terminal_size((80, 24)).columns)


def _clear(lines):
    global _output_lines
    if lines > 0:
        sys.stdout.write(f"\033[{lines}A\r\033[J")
        sys.stdout.flush()
        _output_lines = max(0, _output_lines - lines)


def _window(total, current, page_size):
    if not page_size or total <= page_size:
        return 0, total
    half = page_size // 2
    start = max(0, current - half)
    end = min(total, start + page_size)
    return max(0, end - page_size), end


def select(title, options, default_index=0, subtitle="（↑↓ 移动，回车确认，Esc 退出）", page_size=10):
    """单选。options 为 (value, label) 列表，返回 value；取消返回 None。"""
    if not available() or not options:
        return None

    enable_vt()
    width = _terminal_width()
    selected = min(max(default_index, 0), len(options) - 1)
    last_lines = 0

    def render():
        nonlocal last_lines
        global _output_lines
        _clear(last_lines)

        lines = [
            f"{C_CYAN}{_fit(title, width)}{C_RESET}",
            f"{C_GRAY}{_fit(subtitle, width)}{C_RESET}",
            "",
        ]
        start, end = _window(len(options), selected, page_size)
        if start > 0:
            lines.append(f"{C_GRAY}  ↑ {start}{C_RESET}")
        for index in range(start, end):
            label = _fit(options[index][1], width - 2)
            if index == selected:
                lines.append(f"{C_GREEN}{POINTER}{C_RESET} {C_BOLD_GREEN}{label}{C_RESET}")
            else:
                lines.append(f"  {label}")
        if end < len(options):
            lines.append(f"{C_GRAY}  ↓ {len(options) - end}{C_RESET}")
        lines.append("")

        sys.stdout.write("\n".join(lines))
        sys.stdout.flush()
        last_lines = len(lines) - 1
        _output_lines += last_lines

    render()
    while True:
        try:
            key = _get_key()
        except KeyboardInterrupt:
            _clear(last_lines)
            raise InteractiveExit()
        if key == KEY_ENTER:
            _clear(last_lines)
            return options[selected][0]
        if key == KEY_ESC:
            _clear(last_lines)
            clear_session()
            raise InteractiveExit()
        if key == KEY_CTRL_C:
            _clear(last_lines)
            raise InteractiveExit()
        if key == KEY_UP:
            selected = (selected - 1) % len(options)
        elif key == KEY_DOWN:
            selected = (selected + 1) % len(options)
        else:
            continue
        render()


def checkbox(title, options, subtitle="（空格选择，回车确认，Esc 退出）", page_size=10):
    """多选。options 为 (value, label) 列表，返回 value 列表；取消返回 None。"""
    if not available() or not options:
        return None

    enable_vt()
    width = _terminal_width()
    cursor = 0
    chosen = set()
    last_lines = 0

    def render():
        nonlocal last_lines
        global _output_lines
        _clear(last_lines)

        lines = [
            f"{C_CYAN}{_fit(title, width)}{C_RESET}",
            f"{C_GRAY}{_fit(subtitle, width)}{C_RESET}",
            "",
        ]
        start, end = _window(len(options), cursor, page_size)
        if start > 0:
            lines.append(f"{C_GRAY}  ↑ {start}{C_RESET}")
        for index in range(start, end):
            value, label = options[index]
            mark = f"{C_GREEN}[x]{C_RESET}" if value in chosen else "[ ]"
            label = _fit(label, width - 6)
            prefix = f"{C_GREEN}{POINTER}{C_RESET}" if index == cursor else " "
            lines.append(f"{prefix} {mark} {label}")
        if end < len(options):
            lines.append(f"{C_GRAY}  ↓ {len(options) - end}{C_RESET}")
        lines.append("")

        sys.stdout.write("\n".join(lines))
        sys.stdout.flush()
        last_lines = len(lines) - 1
        _output_lines += last_lines

    render()
    while True:
        try:
            key = _get_key()
        except KeyboardInterrupt:
            _clear(last_lines)
            raise InteractiveExit()
        if key == KEY_ENTER:
            _clear(last_lines)
            return [value for value, _ in options if value in chosen]
        if key == KEY_ESC:
            _clear(last_lines)
            clear_session()
            raise InteractiveExit()
        if key == KEY_CTRL_C:
            _clear(last_lines)
            raise InteractiveExit()
        if key == KEY_UP:
            cursor = (cursor - 1) % len(options)
        elif key == KEY_DOWN:
            cursor = (cursor + 1) % len(options)
        elif key == KEY_SPACE:
            value = options[cursor][0]
            if value in chosen:
                chosen.remove(value)
            else:
                chosen.add(value)
        else:
            continue
        render()


def require_console():
    enable_vt()
    if available():
        return True
    emit(red("错误：交互界面需要 Windows 控制台（stdin/stdout 必须是终端）。"))
    return False


def run_command(cmd):
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=ENV,
    )


def git(*args):
    return run_command(["git", *args])


def print_command_output(result, max_lines=40):
    output = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
    if not output:
        return
    lines = output.splitlines()
    if len(lines) > max_lines:
        emit(f"...（省略 {len(lines) - max_lines} 行）")
        lines = lines[-max_lines:]
    emit("\n".join(lines))


def ensure_repository():
    result = git("rev-parse", "--is-inside-work-tree")
    if result.returncode != 0 or result.stdout.strip() != "true":
        emit(red("错误：当前目录不是 Git 仓库。"))
        return False
    return True


def repository_info():
    root = git("rev-parse", "--show-toplevel").stdout.strip()
    branch_result = git("symbolic-ref", "--short", "-q", "HEAD")
    branch = branch_result.stdout.strip() if branch_result.returncode == 0 else ""
    upstream_result = git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    upstream = upstream_result.stdout.strip() if upstream_result.returncode == 0 else ""
    return root, branch, upstream


def print_header():
    root, branch, upstream = repository_info()
    emit(bold_cyan("\nGT - Git 控制台"))
    emit(f"  仓库：{root}")
    emit(f"  分支：{branch or '游离 HEAD'}")
    emit(f"  上游：{upstream or '无'}")
    return branch


def get_remotes():
    remotes = []
    for name in git("remote").stdout.split():
        url_result = git("remote", "get-url", "--push", name)
        if url_result.returncode != 0:
            url_result = git("remote", "get-url", name)
        urls = [line.strip() for line in url_result.stdout.splitlines() if line.strip()]
        remotes.append({"name": name, "url": " | ".join(urls) or "(未知 URL)"})
    return remotes


def choose_remote(remotes):
    if len(remotes) == 1:
        remote = remotes[0]
        emit(f"\n远程仓库：{remote['name']}  ({remote['url']})")
        return remote

    remote = select(
        "请选择目标远程仓库：",
        [(item, f"{item['name']}  ({item['url']})") for item in remotes],
        subtitle="（↑↓ 移动，回车选择，Esc 退出）",
    )
    if remote is not None:
        emit(f"远程仓库：{remote['name']}  ({remote['url']})")
    return remote


def choose_mode():
    emit()
    return select(
        "请选择推送模式：",
        [
            (MODE_NORMAL, "1. 普通推送（当前分支）"),
            (MODE_ALL, "2. 全量推送（所有分支 + 标签，分两条命令执行）"),
            (MODE_MIRROR, "3. 镜像推送（--mirror，高危）"),
        ],
    )


def confirm_mirror(remote):
    emit(red("\n高危操作：镜像推送"))
    emit("  - 远端存在、本地没有的分支和标签会被删除")
    emit("  - 本地的 refs/remotes/* 会一并写入远端")
    emit("  - 操作不可撤销")
    emit(f"  目标：{remote['name']} -> {remote['url']}")
    answer = select(
        "确认执行镜像推送？",
        [(CANCEL_NO, CANCEL_NO), (MIRROR_YES, MIRROR_YES)],
        subtitle="（Esc 退出）",
    )
    return answer == MIRROR_YES


def push_commands(mode, remote):
    if mode == MODE_NORMAL:
        return [["git", "push", remote, "HEAD"]]
    if mode == MODE_ALL:
        return [["git", "push", remote, "--all"], ["git", "push", remote, "--tags"]]
    return [["git", "push", remote, "--mirror"]]


def auth_failed(text):
    lowered = text.lower()
    markers = ("authentication failed", "could not read username", "terminal prompts disabled")
    return any(marker in lowered for marker in markers)


def perform_push(remote, mode):
    if mode == MODE_MIRROR and not confirm_mirror(remote):
        emit("已取消。")
        return True

    labels = {MODE_NORMAL: "普通推送", MODE_ALL: "全量推送", MODE_MIRROR: "镜像推送"}
    emit(f"\n正在向 {remote['name']} 执行{labels[mode]}...")
    started = time.perf_counter()
    outputs = []

    for cmd in push_commands(mode, remote["name"]):
        result = run_command(cmd)
        print_command_output(result)
        outputs.append((result.stdout or "") + (result.stderr or ""))
        if result.returncode != 0:
            elapsed = time.perf_counter() - started
            emit(red(f"推送失败（{elapsed:.1f}s，exit {result.returncode}）"))
            if auth_failed("\n".join(outputs)):
                emit("提示：认证失败，可执行 gt logout 清理本地凭据后重试。")
            return False

    elapsed = time.perf_counter() - started
    emit(green(f"推送成功，耗时 {elapsed:.1f}s"))
    return True


def push_flow():
    if not require_console():
        return False
    if not ensure_repository():
        return False
    branch = print_header()
    remotes = get_remotes()
    if not remotes:
        emit(red("\n当前仓库没有配置远程仓库。"))
        return False
    remote = choose_remote(remotes)
    if remote is None:
        emit("已取消。")
        return True
    mode = choose_mode()
    if mode is None:
        emit("已取消。")
        return True
    if mode == MODE_NORMAL and not branch:
        emit(red("当前为游离 HEAD，普通推送需要先切换到分支。"))
        return False
    return perform_push(remote, mode)


def scan_credentials():
    """扫描 Windows 凭据管理器中的 git: 条目，按主机分组。

    非 Windows 平台返回 None。
    """
    if sys.platform != "win32":
        return None
    result = run_command(["cmdkey", "/list"])
    if result.returncode != 0:
        return None

    groups = {}
    for line in result.stdout.splitlines():
        match = re.search(r"git:(https?://\S+)", line)
        if not match:
            continue
        url = match.group(1)
        label = url.replace("://refresh_token.", "://")
        target = f"git:{url}"
        groups.setdefault(label, [])
        if target not in groups[label]:
            groups[label].append(target)
    return [{"url": label, "targets": targets} for label, targets in groups.items()]


def delete_credential(target):
    return run_command(["cmdkey", f"/delete:{target}"]).returncode == 0


def logout_flow():
    if sys.platform != "win32":
        emit(yellow("gt logout 当前仅支持 Windows。"))
        return False
    if not require_console():
        return False

    credentials = scan_credentials()
    if credentials is None:
        emit(red("读取凭据列表失败（cmdkey /list）。"))
        return False
    if not credentials:
        emit(green("未发现本地保存的 Git 凭据。"))
        return True

    emit(bold_cyan("\nGT - Git 凭据清理"))
    for credential in credentials:
        emit(f"  - {credential['url']}（{len(credential['targets'])} 条）")

    selected = checkbox(
        "选择要登出的条目：",
        [(credential["url"], credential["url"]) for credential in credentials],
    )
    if not selected:
        emit("未选择，已取消。")
        return True

    targets = []
    for credential in credentials:
        if credential["url"] in selected:
            targets.extend(credential["targets"])

    answer = select(
        f"确认删除 {len(targets)} 条凭据？",
        [(CANCEL_NO, CANCEL_NO), (DELETE_YES, DELETE_YES)],
        subtitle="（Esc 退出）",
    )
    if answer != DELETE_YES:
        emit("已取消。")
        return True

    failed = [target for target in targets if not delete_credential(target)]
    deleted = len(targets) - len(failed)
    if failed:
        emit(red(f"已删除 {deleted} 条，失败 {len(failed)} 条"))
        for target in failed:
            emit(f"  - {target}")
    else:
        emit(green(f"已删除 {deleted} 条凭据。"))

    remaining = scan_credentials()
    if remaining is None:
        emit("重新扫描凭据失败。")
    elif not remaining:
        emit("当前剩余凭据：无")
    else:
        emit("当前剩余凭据：")
        for credential in remaining:
            emit(f"  - {credential['url']}（{len(credential['targets'])} 条）")
    return not failed


USAGE = """用法:
  gt          交互式推送（当前 Git 仓库）
  gt logout   清理本地保存的 Git 凭据（Windows）"""


def main():
    enable_vt()
    args = sys.argv[1:]
    if args and args[0] in ("-h", "--help", "help"):
        emit(USAGE)
        return 0
    if args and args[0] == "logout":
        return 0 if logout_flow() else 1
    if args:
        emit(red(f"未知命令：{args[0]}"))
        emit(USAGE)
        return 1
    return 0 if push_flow() else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except InteractiveExit:
        sys.exit(0)
    except (KeyboardInterrupt, EOFError):
        sys.exit(0)
