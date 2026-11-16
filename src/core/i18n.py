"""界面文案国际化：以中文原文为键，支持中英文热切换。

语言模式保存在 config.json 的 language 键：zh_CN / en_US / system；
system 表示跟随系统语言，读取时按系统语言解析。
Copyright (c) 2026 Lisselde_E <Lisselde.E@outlook.com>.
Licensed under the GNU General Public License v3.0.
"""

from __future__ import annotations

from PySide6.QtCore import QLocale

from . import store

LANG_ZH = "zh_CN"
LANG_EN = "en_US"
LANG_SYSTEM = "system"
LANGUAGES = (LANG_ZH, LANG_EN, LANG_SYSTEM)

# 中文原文 → 英文，缺少条目时回退中文原文
_EN: dict[str, str] = {
    # ---- 常规 / 导航 ----
    "导航": "Navigation",
    "首页": "Home",
    "仓库": "Repos",
    "推送": "Push",
    "拉取": "Pull",
    "设置": "Settings",
    "关于": "About",
    "常规": "General",
    "通用": "General",
    "显示语言": "Language",
    "个性化": "Appearance",
    "界面风格": "Interface style",
    "深浅色模式": "Color mode",
    "安全": "Security",
    "敏感操作二次校验（Beta）": "Verification for sensitive actions (Beta)",
    "关闭": "Off",
    "开启": "On",
    "简体中文": "简体中文",
    "跟随系统": "System",
    "macOS 风格": "macOS",
    "Win11 系统风格": "Win11",
    "浅色": "Light",
    "深色": "Dark",
    "个性化外观与行为": "Appearance and behaviour",
    "自定义功能待填充": "Custom feature placeholder",
    "内容占位区 — 可在此放入自定义功能模块":
        "Placeholder area — custom modules can go here",

    # ---- 首页 ----
    "仓库总览：数量、待推送与本地/远程状态":
        "Overview: totals, pending pushes and local/remote status",
    "仓库总数": "Repositories",
    "待推送": "Pending",
    "本地/远程不一致": "Diverged",
    "未配置远程": "No remote",
    "还没有添加仓库，到「仓库」页添加仓库或文件夹":
        "No repositories yet. Add repositories or folders on the Repos page.",
    "正在扫描 {n} 个来源…": "Scanning sources ({n})…",
    "{sources} 个来源 · 共 {repos} 个仓库":
        "Sources: {sources} · Repos: {repos}",
    "用户配置": "User configuration",
    "用户名": "Username",
    "邮箱": "Email",
    "未配置": "Not set",
    "点击数值即可修改": "Click a value to edit",
    "修改后写入全局配置：git config --global <键> <值>":
        "Changes are written globally: git config --global <key> <value>",
    "内容不能为空，未修改": "Value cannot be empty; unchanged",
    "已保存": "Saved",
    "保存失败，请检查 git 是否可用":
        "Save failed. Check that git is available.",

    # ---- 仓库页 ----
    "添加仓库": "Add repository",
    "添加文件夹": "Add folder",
    "还没有添加仓库": "No repositories added",
    "添加单个仓库目录，或添加整个文件夹后自动扫描":
        "Add a single repository folder, or add a folder to scan automatically",
    "添加单独的仓库或整个目录，推送页会汇总显示其中的所有仓库":
        "Add individual repositories or whole folders; the Push page aggregates every repository inside",
    "尚未添加仓库或目录": "No repositories or folders added",
    "正在扫描 · 已添加 {n} 项": "Scanning · {n} items",
    "已添加 {n} 项": "Items added: {n}",
    "目录": "Folder",
    "扫描中…": "Scanning…",
    "{n} 个仓库": "Repos: {n}",
    "选择仓库根目录": "Select repository folder",
    "选择要扫描的文件夹": "Select a folder to scan",
    "不是 Git 仓库": "Not a Git repository",
    "所选目录没有检测到 Git 仓库。\n请选择仓库根目录，或改用「添加文件夹」。":
        "No Git repository was found in the selected folder.\n"
        "Choose a repository folder, or use “Add folder” instead.",
    "打开仓库详情：配置远程、推送与拉取":
        "Open repository details: remotes, push and pull",

    # ---- 推送页 ----
    "汇总「仓库」页登记的所有来源，推送前需要系统身份验证":
        "All sources from the Repos page; pushing requires system verification",
    "还没有仓库": "No repositories yet",
    "选择一个目录，扫描其中所有 Git 仓库":
        "Choose a folder to scan for Git repositories",
    "选择目录": "Choose folder",
    "刷新": "Refresh",
    "未推送": "Not pushed",
    "已同步": "Up to date",
    "未配置远程仓库": "No remote configured",
    "{remote} · 新分支": "{remote} · new branch",
    "正在扫描目录…": "Scanning folders…",
    "正在查找其中的 Git 仓库": "Looking for Git repositories",
    "没有找到 Git 仓库": "No Git repositories found",
    "换一个目录试试，其中不含含 .git 的文件夹":
        "Try another folder; this one has no folders containing .git",
    "还没有添加仓库目录": "No repository folders added",
    "到「仓库」页添加仓库或文件夹后再回来":
        "Add repositories or folders on the Repos page, then come back",
    "尚未添加仓库目录": "No repository folders added",
    "{sources} 个来源 · {repos} 个仓库":
        "Sources: {sources} · Repos: {repos}",
    "推送到": "Push to",
    "没有需要推送的远程": "No remotes to push to",
    "即将推送 {n} 个提交": "About to push {n} commits",
    "当前分支：{branch}": "Current branch: {branch}",
    "选择操作以继续": "Choose an action to continue",
    "正在推送到 {remote}…": "Pushing to {remote}…",
    "正在等待系统身份验证…": "Waiting for system verification…",
    "GiTool：请验证身份以继续推送":
        "GiTool: verify your identity to continue pushing",
    "验证调用失败：{err}": "Verification call failed: {err}",
    "{msg}，可重新验证或取消": "{msg}. Verify again or cancel.",
    "验证通过，正在推送到 {remote}…": "Verified. Pushing to {remote}…",
    "无法启动 git，请确认已安装并加入 PATH":
        "Unable to start git. Make sure it is installed and in PATH.",
    "git 命令执行超时": "git command timed out",
    "推送成功，{remote}/{branch} 已更新":
        "Push succeeded. {remote}/{branch} updated.",
    "推送失败：{reason}": "Push failed: {reason}",
    "未知错误": "Unknown error",

    # ---- 仓库详情 ----
    "仓库详情": "Repository details",
    "返回": "Back",
    "返回仓库列表（Esc）": "Back to repository list (Esc)",
    "从「仓库」页点开一个仓库":
        "Open a repository from the Repos page",
    "未加载仓库": "No repository loaded",
    "状态": "Status",
    "无法读取该仓库": "Cannot read repository",
    "无法读取该仓库：目录不存在或不是 git 仓库":
        "Cannot read this repository: the folder is missing or not a git repository",
    "当前分支": "Current branch",
    "工作区": "Working tree",
    "有未提交改动": "Uncommitted changes",
    "干净": "Clean",
    "批量推送目标": "Bulk push targets",
    "游离 HEAD · {n} 个远程": "Detached HEAD · Remotes: {n}",
    "分支 {branch} · {n} 个远程 · 推送目标 {targets}":
        "Branch {branch} · Remotes: {n} · Targets: {targets}",
    "打开目录": "Open folder",
    "在资源管理器中打开仓库目录":
        "Open the repository folder in Explorer",
    "抓取全部": "Fetch all",
    "git fetch --prune（刷新所有远程的领先/落后统计）":
        "git fetch --prune (refresh ahead/behind for all remotes)",
    "重新读取本地状态（不发网络请求）":
        "Reload local state (no network requests)",
    "远程仓库": "Remotes",
    "点左侧圆点加入批量推送目标":
        "Click the dot on the left to add a bulk push target",
    "添加远程": "Add remote",
    "推送全部目标": "Push all targets",
    "选中远程即可推送、拉取；圆点用于批量推送目标":
        "Select a remote to push or pull; dots mark bulk push targets",
    "还没有远程仓库。点击右上角「添加远程」填写名称与地址，之后就能在这里推送、拉取。":
        "No remotes yet. Click “Add remote” at the top right, enter a name and URL, "
        "and you can push and pull here.",
    "抓取": "Fetch",
    "编辑": "Edit",
    "删除": "Delete",
    "推送当前分支到该远程": "Push the current branch to this remote",
    "git pull --ff-only（只允许快进）": "git pull --ff-only (fast-forward only)",
    "修改远程地址": "Change the remote URL",
    "移除该远程（需再次点击确认）":
        "Remove this remote (click again to confirm)",
    "名称，例如 origin": "Name, e.g. origin",
    "地址，例如 https://github.com/user/repo.git":
        "URL, e.g. https://github.com/user/repo.git",
    "取消": "Cancel",
    "保存": "Save",
    "远程名称只能包含字母、数字、点、下划线与连字符":
        "Remote names may only contain letters, digits, dots, underscores and hyphens",
    "请填写远程地址": "Enter the remote URL",
    "更新失败：{err}": "Update failed: {err}",
    "已更新 {name} 的地址": "Updated the URL of {name}",
    "已存在名为 {name} 的远程": "A remote named {name} already exists",
    "添加失败：{err}": "Failed to add: {err}",
    "已添加远程 {name}": "Added remote {name}",
    "再次点击「删除」以移除远程 {name}":
        "Click “Delete” again to remove remote {name}",
    "删除失败：{err}": "Failed to delete: {err}",
    "已移除远程 {name}": "Removed remote {name}",
    "无法打开目录": "Cannot open the folder",
    "当前处于游离 HEAD，无法推送": "Cannot push in detached HEAD state",
    "还没有选择批量推送目标": "No bulk push targets selected",
    "GiTool：请验证身份以继续推送":
        "GiTool: verify your identity to continue pushing",
    "{msg}，可重新推送": "{msg}. You can push again.",
    "推送完成，推送目标已全部更新":
        "Push complete. All targets are updated.",
    "正在推送到 {name}…": "Pushing to {name}…",
    "推送到 {name} 失败：{reason}": "Failed to push to {name}: {reason}",
    "正在抓取 {name}…": "Fetching {name}…",
    "抓取失败：{err}": "Fetch failed: {err}",
    "抓取完成，远端状态已更新": "Fetch complete. Remote status updated.",
    "当前处于游离 HEAD，无法拉取": "Cannot pull in detached HEAD state",
    "正在从 {name} 拉取 {branch}…": "Pulling {branch} from {name}…",
    "已从 {name} 拉取 {branch}": "Pulled {branch} from {name}",
    "拉取失败：{err}": "Pull failed: {err}",
    "正在执行 git 操作，请稍候":
        "A git operation is running. Please wait.",
    "远端有新的提交，请先拉取": "The remote has new commits. Pull first.",
    "没有推送权限，请检查凭据": "No push permission. Check your credentials.",

    # ---- 关于 ----
    "应用信息与运行环境": "Application information and runtime",
    "版本 {version}": "Version {version}",
    "把分散在各处的 Git 仓库集中到一处：统一查看改动、管理远程、批量推送。":
        "Unify your Git repositories: review changes, manage remotes and push in bulk.",
    "所有 git 命令都在本机执行，不收集使用数据，也不会主动联网。":
        "All git commands run locally. No usage data is collected.",
    "作者": "Author",
    "开源协议": "License",
    "运行环境": "Runtime",
    "Windows 10 / 11 · 64 位": "Windows 10 / 11 · 64-bit",
    "配置文件": "Config file",
    "点击邮箱可发送反馈，点击配置文件路径可打开所在目录":
        "Click the email to send feedback; click the config path to open its folder",
    "发送反馈": "Send feedback",
    "打开配置目录": "Open config folder",
    "复制版本信息": "Copy version info",
    "已复制版本信息": "Version info copied",
    "配置文件目录尚不存在": "Config folder does not exist yet",
    "检查更新": "Check for updates",
    "检查更新中…": "Checking for updates…",
    "已是最新版本（{version}）": "You're up to date ({version})",
    "检查更新失败：{err}": "Update check failed: {err}",
    "GiTool：关闭敏感操作二次校验需要验证身份":
        "GiTool: verify your identity to disable verification for sensitive actions",
    "{msg}，保护保持开启": "{msg}. Protection remains on.",
    "应用 · {name}": "Application · {name}",

    # ---- 更新对话框 ----
    "{name} 更新": "{name} Update",
    "发现新版本 {version}": "New version {version} available",
    "当前版本 {version}": "Current version {version}",
    "更新内容": "What's new",
    "暂无更新说明": "No release notes",
    "下载后会自动校验安装包并启动安装程序，安装期间程序将退出。":
        "The installer is verified automatically after download and then launched. "
        "GiTool will exit during installation.",
    "立即更新": "Update now",
    "正在连接下载地址…": "Connecting to download server…",
    "正在下载… {percent}%": "Downloading… {percent}%",
    "正在下载…": "Downloading…",
    "正在校验安装包…": "Verifying installer…",
    "正在启动安装程序…": "Starting installer…",
    "重试": "Retry",
    "更新清单为空": "Update manifest is empty",
    "无法解析更新清单中的版本号":
        "Cannot parse the version in the update manifest",
    "更新清单未提供下载地址":
        "Update manifest does not provide a download URL",
    "更新清单缺少合法的 win_sha256（需 64 位十六进制）":
        "Update manifest is missing a valid win_sha256 (64 hex digits)",
    "无法获取更新清单: {err}": "Failed to fetch update manifest: {err}",
    "无法下载安装包: {err}": "Failed to download installer: {err}",
    "安装包大小不符: 期望 {expected}，实际 {actual}":
        "Installer size mismatch: expected {expected}, got {actual}",
    "安装包校验失败（sha256 不匹配）":
        "Installer verification failed (sha256 mismatch)",
    "已取消下载": "Download cancelled",

    # ---- 系统验证 ----
    "验证通过": "Verification passed",
    "验证失败": "Verification failed",
    "验证过程出错": "Verification failed",
    "已取消验证": "Verification cancelled",
    "系统未提供可用的验证设备":
        "No verification device is available on this system",
    "当前用户尚未配置 Windows Hello":
        "Windows Hello is not configured for this user",
    "Windows Hello 已被系统策略禁用":
        "Windows Hello is disabled by system policy",
    "验证设备正忙，请稍后重试":
        "The verification device is busy. Try again later.",
    "验证失败次数过多": "Too many failed verification attempts",
    "验证调用失败：{err}": "Verification call failed: {err}",
    "验证窗口调用失败（hr={hr}）":
        "Failed to open verification window (hr={hr})",
    "获取异步状态接口失败（hr={hr}）":
        "Failed to get async status interface (hr={hr})",
    "读取验证状态失败（hr={hr}）":
        "Failed to read verification status (hr={hr})",
    "读取验证结果失败（hr={hr}）":
        "Failed to read verification result (hr={hr})",
}

_current = LANG_ZH
_mode = LANG_SYSTEM


def detect_system_language() -> str:
    """按系统界面语言返回 zh_CN 或 en_US。"""
    try:
        chinese = QLocale.system().language() == QLocale.Language.Chinese
    except Exception:
        chinese = False
    return LANG_ZH if chinese else LANG_EN


def resolve(mode: str | None) -> str:
    """把语言模式解析为实际生效的语言。"""
    if mode == LANG_SYSTEM:
        return detect_system_language()
    return mode if mode in (LANG_ZH, LANG_EN) else detect_system_language()


def initialize() -> str:
    """启动时初始化：配置缺失或非法时默认「跟随系统」并写入一次。"""
    global _mode, _current
    mode = store.get("language")
    if mode not in LANGUAGES:
        mode = LANG_SYSTEM
        store.set_value("language", mode)
    _mode = mode
    _current = resolve(mode)
    return _current


def set_language(mode: str) -> str:
    """切换语言模式并写回配置，返回实际生效的语言。"""
    global _mode, _current
    if mode not in LANGUAGES:
        mode = detect_system_language()
    _mode = mode
    _current = resolve(mode)
    store.set_value("language", mode)
    return _current


def language() -> str:
    return _current


def mode() -> str:
    return _mode


def is_english() -> bool:
    return _current == LANG_EN


def tr(text: str, **kwargs) -> str:
    """翻译一段中文原文；带参数时按 str.format 插值。"""
    out = _EN.get(text, text) if _current == LANG_EN else text
    return out.format(**kwargs) if kwargs else out


def language_label(value: str) -> str:
    """语言选项在设置里的显示名称。"""
    if value == LANG_ZH:
        return "简体中文"
    if value == LANG_EN:
        return "English"
    return tr("跟随系统")
