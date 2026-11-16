# GiTool

GiTool is a Git helper for Windows: it keeps repositories scattered across many folders in one place, scans local/remote divergence automatically, and lets you pick a branch and push from a single window.

The interface is fully custom-drawn with PySide6, and supports both macOS-style and Win11-native window styles, light/dark themes, and optional system identity verification.

## Project Information

- **Project Name**: GiTool
- **Author**: Lisselde_E
- **License**: GNU General Public License v3.0 (see [LICENSE](LICENSE))

## Features

- **Home overview**: repository count, pending pushes, repositories out of sync with their remotes, and repositories without a remote
- **Source management**: add a single Git repository, or add a parent folder and let GiTool scan it recursively for repositories; sources are registered together, folder sources expand/collapse to list their repositories, and any source can be removed
- **Repository detail**: click any repository row to open its detail page, where you can manage remotes (add, edit URL, remove), mark several remotes as batch push targets, and push, fetch, or pull directly; ahead/behind counts and working-tree changes stay visible at a glance
- **Push panel**: pushable entries are pinned to the top and sorted by name within each group; clicking the arrow on the right expands an inline detail card where you choose the remote and push
- **Branch switching**: repositories with multiple local branches can switch branches directly in the row; the detail card and push both follow the selected branch, with an animated content transition
- **Single shared scan**: Home, Sources, and Push share one scan result, so git is not re-run when the sources are unchanged
- **Second-step verification for sensitive actions (Beta)**: experimental, off by default. When enabled, pushing requires Windows Hello (PIN / fingerprint / face) verification first, and turning the protection itself off also requires verification
- **Appearance**: two window styles (macOS-style custom traffic lights, Win11 native title bar), theme follows the system or can be set explicitly, and preferences are persisted locally

## System Support

| OS | Architecture | Notes |
| :--- | :---: | :--- |
| Windows 10 / 11 | x64 | Only supported platform |

Git must be installed and available on `PATH`.

## Installation

### Running from source

Requires Windows 10/11, Python 3.10 or newer (developed on 3.12), and Git.

```bash
pip install -r requirements.txt
python GiTool.py
```

`winrt-runtime` and `winrt-Windows.Security.Credentials.UI` in `requirements.txt` are used only for Windows Hello verification.

### Installer

Release builds are packaged with Nuitka and wrapped by Inno Setup into `GiTool_Setup.exe`; launch GiTool from the Start menu after installing.

## Usage

1. Open the Sources page and click "Add repository" to pick a single Git repository, or "Add folder" to scan a parent folder
2. Folder sources list every discovered repository as a child row; click a folder row to expand or collapse it
3. Click any repository row to open its detail page: manage remotes, choose batch push targets, or push / fetch / pull directly; press Esc or "Back" to return
4. Open Home to review the summary
5. Open Push, click the arrow on the right of a row, confirm the remote and branch, then push
6. The list keeps its scroll position after a push, and the Home summary refreshes in sync

## Settings

- **General**: application name and version
- **Personalization**
  - Window style: macOS style / Win11 system style
  - Theme: follow system / light / dark
- **Security**
  - Second-step verification: off by default. When enabled, pushing requires system verification first; turning it off also requires verification, and the switch stays on if verification fails

## Data & Privacy

- Settings live in `~/.gitool/config.json` under your user directory: repository sources, window style, theme, the security toggle, and batch push targets per repository
- Everything stays on your machine; GiTool collects nothing, uploads nothing, and makes no network requests of its own
- All scanning and pushing runs through your local Git installation

## Tech Stack

- Python 3
- PySide6 (Qt 6, fully custom-drawn UI)
- Local Git CLI
- Windows Hello (winrt)

## Building

```bat
nuitka\nuitka打包.bat
nuitka\lnno编译安装包.bat
```

The first produces `dist\GiTool.dist`; the second produces `GiTool_Setup.exe`.

## Changelog

See [CHANGELOG.md](CHANGELOG.md).

## License

Released under the GNU General Public License v3.0. See [LICENSE](LICENSE).

## Feedback

Email: Lisselde.E@outlook.com
