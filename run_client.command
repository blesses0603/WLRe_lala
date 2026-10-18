#!/bin/bash
# macOS equivalent of run_client.bat (Apple Silicon / Intel).
# Put this file next to run_client.bat and WLRE_Client.py.
set -u

cd "$(dirname "$0")" || exit 1
export PYTHONUTF8=1

pause_on_error() {
    if [[ -t 0 ]]; then
        printf '\n按 Return 鍵關閉此視窗... '
        read -r _unused || true
    fi
}

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo '[錯誤] run_client.command 僅適用於 macOS。'
    pause_on_error
    exit 1
fi

if [[ ! -f 'wlre/launcher.py' || ! -f 'requirements-ui.txt' ]]; then
    echo '[錯誤] 找不到 LaLa 專案檔案。'
    echo '請把 run_client.command 放在 run_client.bat 同一層（專案根目錄）。'
    pause_on_error
    exit 1
fi

# macOS has several Python installation layouts. Prefer 3.12 with Tk support.
candidates=()
add_candidate() {
    local candidate="$1" existing
    [[ -n "$candidate" && -x "$candidate" ]] || return 0
    for existing in "${candidates[@]}"; do
        [[ "$existing" == "$candidate" ]] && return 0
    done
    candidates+=("$candidate")
}

add_candidate "${WLRE_PYTHON:-}"
for version in 3.12 3.11 3.13 3.10 3.14; do
    for prefix in /opt/homebrew /usr/local; do
        add_candidate "$prefix/opt/python@$version/bin/python$version"
    done
    add_candidate "/Library/Frameworks/Python.framework/Versions/$version/bin/python$version"
    if command -v "python$version" >/dev/null 2>&1; then
        add_candidate "$(command -v "python$version")"
    fi
done
add_candidate "$PWD/.ui-env/bin/python"
for name in python3 python; do
    if command -v "$name" >/dev/null 2>&1; then
        add_candidate "$(command -v "$name")"
    fi
done

selected=''
for candidate in "${candidates[@]}"; do
    if "$candidate" -c 'import sys, tkinter; assert (3, 10) <= sys.version_info[:2] <= (3, 14); assert tkinter.TkVersion >= 8.6' >/dev/null 2>&1; then
        selected="$candidate"
        break
    fi
done

if [[ -z "$selected" ]]; then
    echo '[錯誤] 找不到可用的 Python 3.10～3.14 與 Tkinter 8.6 以上版本。'
    echo '請使用 Python 3.12（建議）：'
    echo '  Homebrew：brew install python@3.12 python-tk@3.12'
    echo '  或至 https://www.python.org/downloads/macos/ 安裝含 Tcl/Tk 的版本。'
    echo '安裝後重新執行此檔案即可，不必修改原始碼。'
    pause_on_error
    exit 1
fi

printf '飄流Re:LaLa | macOS 啟動器\n'
"$selected" -c 'import sys, tkinter; print("Python:", sys.version.split()[0], "| Tk:", tkinter.TkVersion)'
printf 'Python 路徑：%s\n\n' "$selected"

# Match run_client.bat: use the existing launcher, including its Pillow setup.
"$selected" -m wlre.launcher "$@"
code=$?
if [[ "$code" -ne 0 ]]; then
    printf '\n[錯誤] LaLa 啟動失敗（結束碼 %s）。請保留上方錯誤訊息。\n' "$code"
    pause_on_error
fi
exit "$code"
