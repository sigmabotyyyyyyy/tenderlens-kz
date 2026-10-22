#!/bin/zsh
# Double-click in Finder after creating .venv with the README instructions.
set -eu
APP_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
PYTHON="$APP_DIR/.venv/bin/python"

fail() {
    print -u2 -- "$1"
    if [[ -t 0 ]]; then
        read -r '?Нажмите Enter, чтобы закрыть окно… '
    fi
    exit 1
}

[[ -x "$PYTHON" ]] || fail "Не найден .venv/bin/python. Создайте окружение Python 3.11+ по README.md в папке проекта."
"$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' || fail "Нужен Python 3.11 или новее. Пересоздайте .venv по README.md."
"$PYTHON" -c 'import streamlit' 2>/dev/null || fail "Не установлен Streamlit. Установите зависимости в .venv по README.md."
cd -- "$APP_DIR"
exec "$PYTHON" -m streamlit run "$APP_DIR/app.py" "$@"
