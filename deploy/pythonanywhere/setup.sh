#!/bin/bash
# Puts the Business Reports web app on your free PythonAnywhere account, or updates it to the newest version.
# Paste this line into a PythonAnywhere "Bash" console (see README.md, "Put it online for free"):
#   bash <(curl -sL https://raw.githubusercontent.com/THE-AAV/EXCEL_PROJECT/claude/excel-debtor-creditor-pl-reports-o0o0zm/deploy/pythonanywhere/setup.sh)
set -e
REPO=https://github.com/THE-AAV/EXCEL_PROJECT.git
BRANCH=${BRANCH:-claude/excel-debtor-creditor-pl-reports-o0o0zm}
APP=$HOME/business-reports            # the program (replaced on every update)
DATA=$HOME/business-data              # your data, files and backups (never touched by updates)
VENV=$HOME/.virtualenvs/business-reports
DOMAIN="$USER.${PYTHONANYWHERE_DOMAIN:-pythonanywhere.com}"
PY=python3.13
command -v $PY >/dev/null || PY=python3

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }

if [ -z "$API_TOKEN" ]; then
    say "One thing first: open the Account page (menu at the top right), click the 'API token' tab and"
    say "'Create a new API token'. Then close this console, open a new Bash console and paste the line again."
    exit 1
fi

say "1/4  Getting the newest version of the app..."
if [ -d "$APP/.git" ]; then
    git -C "$APP" fetch -q --depth 1 origin "$BRANCH"
    git -C "$APP" reset -q --hard FETCH_HEAD
else
    git clone -q --depth 1 --branch "$BRANCH" "$REPO" "$APP"
fi

say "2/4  Installing what it needs (the first time takes a few minutes)..."
[ -x "$VENV/bin/python" ] || $PY -m venv --system-site-packages "$VENV"
"$VENV/bin/pip" install -q --no-cache-dir -r "$APP/deploy/pythonanywhere/requirements.txt"
pip3 install -q --user --upgrade pythonanywhere >/dev/null 2>&1 || true
PA=$(command -v pa || echo "$HOME/.local/bin/pa")

mkdir -p "$DATA"
# The free plan has 512 MB in all; the program takes some of it, the rest is for your data and files.
cat > "$DATA/settings.env" <<SETTINGS
DATA_DIR=$DATA
PUBLIC_URL=https://$DOMAIN
SECURE_COOKIES=1
MAX_FILE_MB=${MAX_FILE_MB:-100}
STORAGE_MB=${STORAGE_MB:-250}
SETTINGS

if [ ! -f "$DATA/business.db" ]; then
    say "3/4  Choose the admin password (at least 8 characters; nothing shows while you type):"
    while true; do
        read -rs -p "Admin password: " P1; echo
        read -rs -p "Type it again:  " P2; echo
        [ "$P1" = "$P2" ] && [ ${#P1} -ge 8 ] && break
        echo "They don't match or are shorter than 8 characters. Try again."
    done
    (cd "$APP" && set -a && . "$DATA/settings.env" && ADMIN_USERNAME=admin ADMIN_PASSWORD="$P1" \
        "$VENV/bin/python" -c "from server.main import create_app; create_app()")
    unset P1 P2
else
    say "3/4  Your data is kept as it is."
fi

say "4/4  Starting the website..."
CMD="/usr/bin/env $(tr '\n' ' ' < "$DATA/settings.env") $VENV/bin/uvicorn --app-dir $APP --uds \${DOMAIN_SOCKET} --factory server.main:create_app"
if "$PA" website get --domain "$DOMAIN" >/dev/null 2>&1; then
    "$PA" website delete --domain "$DOMAIN" >/dev/null     # so the start command is always the newest one
fi
"$PA" website create --domain "$DOMAIN" --command "$CMD"

say "Done. Open https://$DOMAIN and sign in as 'admin'."
echo "To update later, paste the same line into a Bash console again. Your data stays."
