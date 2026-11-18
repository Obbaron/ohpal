#!/bin/bash
# Uninstall AMPM Viewer (macOS). On the disk image beside the app; double-click
# it, or run:  bash "Uninstall AMPM Viewer.command"
#
# Lists what it finds, with sizes, in one window where items can be unticked,
# and removes the ticked ones after one OK:
#   - the app (ticked)
#   - caches and leftovers (ticked): crash reports, Qt's caches, macOS's saved
#     window state and preferences for the app
#   - settings and recent lists (not ticked): ampm-viewer.conf
# Macros, saved plots and builds (in ~/Library/Application Support/AMPM) are
# always kept.
set -u

APP_NAME="AMPM Viewer"
BUNDLE_ID="io.github.obbaron.ampmviewer"
DATA="$HOME/Library/Application Support/AMPM"
LSREGISTER="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"

say() {  # a message window (plain text is enough when there's no window server)
    osascript - "$1" >/dev/null 2>&1 <<'EOF' || printf '%s\n' "$1"
on run argv
    display dialog (item 1 of argv) with title "Uninstall AMPM Viewer" buttons {"OK"} default button "OK"
end run
EOF
}

size_of() {  # total size of the paths given, for a person to read
    local kb
    kb=$(du -skc "$@" 2>/dev/null | tail -1 | cut -f1)
    kb=${kb:-0}
    if [ "$kb" -ge 1048576 ]; then
        awk -v k="$kb" 'BEGIN { printf "%.1f GB", k / 1048576 }'
    elif [ "$kb" -ge 1024 ]; then
        awk -v k="$kb" 'BEGIN { printf "%.0f MB", k / 1024 }'
    else
        printf '%s KB' "$kb"
    fi
}

# -- what is there --------------------------------------------------------
apps=()
for candidate in "/Applications/$APP_NAME.app" "$HOME/Applications/$APP_NAME.app"; do
    [ -d "$candidate" ] && apps+=("$candidate")
done
while IFS= read -r found; do  # copies elsewhere, by bundle id (Spotlight)
    case "$found" in /Volumes/*) continue ;; esac  # not the disk image itself
    seen=0
    for a in "${apps[@]+"${apps[@]}"}"; do [ "$a" = "$found" ] && seen=1; done
    [ "$seen" = 0 ] && [ -d "$found" ] && apps+=("$found")
done < <(mdfind "kMDItemCFBundleIdentifier == '$BUNDLE_ID'" 2>/dev/null)

caches=()
for path in \
    "$DATA/crash-reports" \
    "$HOME/Library/Caches/AMPM/AMPM Viewer" \
    "$HOME/Library/Caches/$BUNDLE_ID" \
    "$HOME/Library/Application Support/AMPM Viewer" \
    "$HOME/Library/Saved Application State/$BUNDLE_ID.savedState" \
    "$HOME/Library/Preferences/$BUNDLE_ID.plist" \
    "$HOME/Library/HTTPStorages/$BUNDLE_ID"; do
    [ -e "$path" ] && caches+=("$path")
done

settings=()
for path in "$DATA/ampm-viewer.conf" "$DATA/ampm-viewer.conf.lock"; do
    [ -e "$path" ] && settings+=("$path")
done

if [ ${#apps[@]} -eq 0 ] && [ ${#caches[@]} -eq 0 ] && [ ${#settings[@]} -eq 0 ]; then
    rmdir "$DATA" 2>/dev/null
    say "AMPM Viewer isn't installed on this Mac, and it left nothing behind."
    exit 0
fi

# -- choose ---------------------------------------------------------------
items=() ticked=()
if [ ${#apps[@]} -gt 0 ]; then
    ITEM_APP="The app: ${apps[*]} ($(size_of "${apps[@]}"))"
    items+=("$ITEM_APP"); ticked+=("$ITEM_APP")
fi
if [ ${#caches[@]} -gt 0 ]; then
    ITEM_CACHES="Caches and leftovers: crash reports, caches, saved window state ($(size_of "${caches[@]}"))"
    items+=("$ITEM_CACHES"); ticked+=("$ITEM_CACHES")
fi
if [ ${#settings[@]} -gt 0 ]; then
    ITEM_SETTINGS="Settings and recent lists: theme, folders, recent builds, favourites"
    items+=("$ITEM_SETTINGS")
fi

# One window: every item listed, the ticked ones selected; Command-click to
# change. Returns the chosen items one per line, or nothing for Cancel.
chosen=$(osascript - "${#ticked[@]}" "${ticked[@]+"${ticked[@]}"}" "${items[@]}" <<'EOF'
on run argv
    set nTicked to (item 1 of argv) as integer
    set ticked to {}
    repeat with i from 2 to nTicked + 1
        set end of ticked to item i of argv
    end repeat
    set allItems to items (nTicked + 2) thru -1 of argv
    set question to "Remove the selected items? Command-click to change the selection. Your macros, saved plots and builds are kept."
    set picked to choose from list allItems with title "Uninstall AMPM Viewer" with prompt question default items ticked OK button name "Remove" cancel button name "Cancel" with multiple selections allowed
    if picked is false then return ""
    set AppleScript's text item delimiters to linefeed
    return picked as text
end run
EOF
) || exit 1
[ -z "$chosen" ] && exit 0
picked() { printf '%s\n' "$chosen" | grep -qxF -- "$1"; }

# -- remove ---------------------------------------------------------------
remove() {  # rm, asking for an administrator's password only if needed
    rm -rf "$@" 2>/dev/null && return 0
    osascript - "$@" >/dev/null <<'EOF'
on run argv
    set cmd to "rm -rf"
    repeat with p in argv
        set cmd to cmd & " " & quoted form of (p as text)
    end repeat
    do shell script cmd with administrator privileges
end run
EOF
}

if [ ${#apps[@]} -gt 0 ] && picked "$ITEM_APP"; then
    if pgrep -f "$APP_NAME.app/Contents/MacOS/" >/dev/null; then
        osascript -e "tell application id \"$BUNDLE_ID\" to quit" >/dev/null 2>&1
        for _ in 1 2 3 4 5 6 7 8 9 10; do
            pgrep -f "$APP_NAME.app/Contents/MacOS/" >/dev/null || break
            sleep 1
        done
        if pgrep -f "$APP_NAME.app/Contents/MacOS/" >/dev/null; then
            say "AMPM Viewer is still running. Quit it, then run this again."
            exit 1
        fi
    fi
    for a in "${apps[@]}"; do
        [ -x "$LSREGISTER" ] && "$LSREGISTER" -u "$a" >/dev/null 2>&1
        remove "$a" || { say "Couldn't remove $a."; exit 1; }
    done
fi
if [ ${#caches[@]} -gt 0 ] && picked "$ITEM_CACHES"; then
    defaults delete "$BUNDLE_ID" >/dev/null 2>&1
    remove "${caches[@]}"
    rmdir "$HOME/Library/Caches/AMPM" 2>/dev/null
fi
if [ ${#settings[@]} -gt 0 ] && picked "$ITEM_SETTINGS"; then
    remove "${settings[@]}"
fi
rmdir "$DATA" 2>/dev/null  # only if nothing of yours is left in it

if [ -d "$DATA" ]; then
    say "Done. Your macros, saved plots and builds are still in $DATA."
else
    say "Done."
fi
