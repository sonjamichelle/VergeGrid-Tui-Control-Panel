#!/usr/bin/bash

# If not running under bash (for example launched with /bin/sh), re exec with bash.
if [ -z "$BASH_VERSION" ]; then
    exec /usr/bin/env bash "$0" "$@"
fi

# --------------------------------------------------------------------
# Version info
# --------------------------------------------------------------------
VG_VERSION="v0.6.6-alpha"
VG_DATE="$(date +'%b %d %Y %H:%M')"   # Dec 10 2025 21:07 style

SETTINGS_FILE="$HOME/.vergegrid_settings"

# ---------------------------------------------------------
# Load and save settings
# ---------------------------------------------------------
load_settings() {
    if [ -f "$SETTINGS_FILE" ]; then
        # shellcheck source=/dev/null
        source "$SETTINGS_FILE"
    fi

    BASE="${VG_BASE:-/home/opensim/opensim/bin}"
    ESTATES="${VG_ESTATES:-$BASE/Estates}"
}

save_settings() {
    cat > "$SETTINGS_FILE" <<EOF
VG_BASE="$BASE"
VG_ESTATES="$ESTATES"
EOF
}

load_settings

SESS_DIR="$HOME/.gridstl_sessions"
mkdir -p "$SESS_DIR"

BATCH_SIZE=3
BATCH_DELAY=20

# ---------------------------------------------------------
# UI helpers: header and footer lines
# ---------------------------------------------------------
build_header() {
    # Left: title, Right: build info, padded to roughly dialog width (70)
    local left="VergeGrid Control Panel"
    local right="Build: $VG_VERSION ($VG_DATE)"
    local width=68   # inner width target

    local pad=$(( width - ${#left} - ${#right} ))
    (( pad < 1 )) && pad=1

    printf "%s%*s%s" "$left" "$pad" "" "$right"
}

build_hostline() {
    local hn pretty uptime_str

    hn="$(hostname)"

    if [ -r /etc/os-release ]; then
        # shellcheck source=/dev/null
        . /etc/os-release
        pretty="$PRETTY_NAME"

        # Try to detect Kubuntu specifically
        if command -v dpkg >/dev/null 2>&1 && dpkg -l 2>/dev/null | grep -q '^ii\s*kubuntu-desktop'; then
            if [ -n "$VERSION_ID" ] && [ -n "$UBUNTU_CODENAME" ]; then
                pretty="Kubuntu $VERSION_ID ($UBUNTU_CODENAME)"
            else
                pretty="Kubuntu (detected)"
            fi
        fi
    else
        pretty="$(uname -s)"
    fi

    if uptime -p >/dev/null 2>&1; then
        uptime_str="$(uptime -p | sed 's/^up //')"
    else
        uptime_str="$(uptime | sed 's/^ *//')"
    fi

    local left="Host: $hn"
    local mid="$pretty"
    local right="Uptime: $uptime_str"

    local width=68
    local used=$(( ${#left} + ${#mid} + ${#right} ))
    local rem=$(( width - used ))

    local spacer1=1
    local spacer2=1

    if (( rem > 2 )); then
        spacer1=$(( rem / 2 ))
        spacer2=$(( rem - spacer1 ))
    fi

    printf "%s%*s%s%*s%s" \
        "$left" "$spacer1" "" \
        "$mid"  "$spacer2" "" \
        "$right"
}

VG_HOSTLINE="$(build_hostline)"

# Wrapper around dialog so every box gets the footer / backtitle
dialog_cmd() {
    dialog --backtitle "$VG_HOSTLINE" "$@"
}

# ---------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------
human_name() {
    echo "${1//_/ }"
}

is_valid_estate() {
    local estate="$1"
    local dir="$ESTATES/$estate"

    [ -f "$dir/OpenSim.ini" ] || return 1
    [ -d "$dir/Regions" ] || return 1

    shopt -s nullglob
    local files=("$dir"/Regions/*.ini)
    shopt -u nullglob

    [ ${#files[@]} -gt 0 ] || return 1
    return 0
}

running_instance() {
    local dir="$ESTATES/$1"
    ps aux | grep -v grep | grep -F "inidirectory=$dir" >/dev/null
}

detect_estates() {
    for d in "$ESTATES"/*; do
        [ -d "$d" ] || continue
        local est
        est=$(basename "$d")
        is_valid_estate "$est" && echo "$est"
    done
}

# ---------------------------------------------------------
# Konsole DBus detection
# ---------------------------------------------------------
get_konsole_service() {
    local svc

    if [ -n "$KONSOLE_DBUS_SERVICE" ]; then
        svc="$KONSOLE_DBUS_SERVICE"
    else
        svc=$(qdbus 2>/dev/null | awk '/org\.kde\.konsole-/{print $1; exit}')
        [ -z "$svc" ] && svc="org.kde.konsole"
    fi

    echo "$svc"
}

KONSOLE_SERVICE="$(get_konsole_service)"

if [ -n "$KONSOLE_DBUS_WINDOW" ]; then
    WINDOW="$KONSOLE_DBUS_WINDOW"
else
    WINDOW="$(qdbus "$KONSOLE_SERVICE" 2>/dev/null | awk '/\/Windows\//{print $1; exit}')"
    [ -z "$WINDOW" ] && WINDOW="/Windows/1"
fi

# ---------------------------------------------------------
# DBus helpers
# ---------------------------------------------------------
new_tab() {
    local path
    path=$(qdbus "$KONSOLE_SERVICE" "$WINDOW" org.kde.konsole.Window.newSession)
    echo "${path#/Sessions/}"
}

run_in_tab() {
    qdbus "$KONSOLE_SERVICE" "/Sessions/$1" org.kde.konsole.Session.runCommand "$2"
}

set_tab_title() {
    qdbus "$KONSOLE_SERVICE" "/Sessions/$1" org.kde.konsole.Session.setTitle 1 "$2"
}

send_text() {
    qdbus "$KONSOLE_SERVICE" "$WINDOW" org.kde.konsole.Window.setCurrentSession "$1"
    qdbus "$KONSOLE_SERVICE" "/Sessions/$1" org.kde.konsole.Session.runCommand "$2"
}

# ---------------------------------------------------------
# Session tracking
# ---------------------------------------------------------
robust_session_file="$SESS_DIR/robust.session"

estate_session_file() {
    echo "$SESS_DIR/estate_$1.session"
}

save_session() {
    echo "$2" > "$1"
}

load_session() {
    [ -f "$1" ] && cat "$1"
}

clear_session() {
    [ -f "$1" ] && rm "$1"
}

# ---------------------------------------------------------
# Wait for exit and close
# ---------------------------------------------------------
wait_for_exit_and_close() {
    local session="$1"
    local match="$2"

    echo "Waiting for region process shutdown..."

    while true; do
        if ! pgrep -f "$match" >/dev/null; then
            echo "Process exited cleanly. Sending exit to Konsole..."
            send_text "$session" "exit"
            break
        fi
        sleep 1
    done

    qdbus "$KONSOLE_SERVICE" "/Sessions/$session" org.kde.konsole.Session.close
}

# ---------------------------------------------------------
# Start / Stop Robust
# ---------------------------------------------------------
start_robust() {
    local session
    session=$(new_tab)

    set_tab_title "$session" "Robust"
    save_session "$robust_session_file" "$session"

    run_in_tab "$session" \
        "cd \"$BASE\"; ulimit -s 1048576; \
         if [ -f Robust.dll ]; then dotnet Robust.dll -inifile=Robust.HG.ini; \
         elif [ -f Robust.exe ]; then mono --desktop -O=all Robust.exe -inifile=Robust.HG.ini; \
         else echo 'ERROR: No Robust.dll or Robust.exe found in \$(pwd)'; fi"
}

stop_robust() {
    local session
    session=$(load_session "$robust_session_file")
    [ -z "$session" ] && return

    local choice
    choice=$(dialog_cmd --stdout --menu "STOP Robust" 15 60 5 \
        1 "Graceful" \
        2 "Force Kill" \
        3 "Cancel")

    case "$choice" in
        1)
            send_text "$session" "shutdown"
            wait_for_exit_and_close "$session" "Robust"
            ;;
        2)
            pkill -f Robust
            clear_session "$robust_session_file"
            ;;
    esac
}

# ---------------------------------------------------------
# Start / Stop Estate
# ---------------------------------------------------------
start_instance() {
    local estate="$1"
    local dir="$ESTATES/$estate"
    local session
    session=$(new_tab)

    set_tab_title "$session" "$(human_name "$estate")"
    save_session "$(estate_session_file "$estate")" "$session"

    local argfile="$ESTATES/$estate/estate.args"
    local extra=""
    [ -f "$argfile" ] && extra=$(cat "$argfile")

    run_in_tab "$session" \
        "cd \"$BASE\"; ulimit -s 1048576; \
         if [ -f OpenSim.dll ]; then dotnet OpenSim.dll --hypergrid=true --inidirectory=\"$dir\" $extra; \
         elif [ -f OpenSim.exe ]; then mono --desktop -O=all OpenSim.exe --hypergrid=true --inidirectory=\"$dir\" $extra; \
         else echo 'ERROR: No OpenSim.dll or OpenSim.exe found in \$(pwd)'; fi"
}

stop_instance() {
    local estate="$1"
    local mode="${2:-ask}"
    local file
    file="$(estate_session_file "$estate")"
    local session
    session=$(load_session "$file")
    [ -z "$session" ] && return

    local choice

    if [ "$mode" = "ask" ]; then
        choice=$(dialog_cmd --stdout --menu "STOP $(human_name "$estate")" 15 60 5 \
            1 "Graceful" \
            2 "Force Kill" \
            3 "Cancel")
        case "$choice" in
            1) mode="graceful" ;;
            2) mode="force" ;;
            *) return ;;
        esac
    fi

    case "$mode" in
        graceful)
            send_text "$session" "shutdown"
            wait_for_exit_and_close "$session" "$ESTATES/$estate"
            ;;
        force)
            pkill -f "$ESTATES/$estate"
            clear_session "$file"
            ;;
    esac
}

restart_instance() {
    stop_instance "$1"
    sleep 2
    start_instance "$1"
}

reload_config() {
    local estate="$1"
    local session
    session=$(load_session "$(estate_session_file "$estate")")
    [ -z "$session" ] && return

    send_text "$session" "config reload"
    dialog_cmd --msgbox "Reload sent." 10 40
}

edit_estate_args() {
    local estate="$1"
    local file="$ESTATES/$estate/estate.args"

    [ -f "$file" ] || echo "" > "$file"

    local new
    new=$(dialog_cmd --stdout --editbox "$file" 20 80)
    [ -n "$new" ] && echo "$new" > "$file"
}

# ---------------------------------------------------------
# Region Status view
# ---------------------------------------------------------
view_status() {
    mapfile -t estates < <(detect_estates)

    if [ ${#estates[@]} -eq 0 ]; then
        dialog_cmd --msgbox "No estates detected in $ESTATES" 10 50
        return
    fi

    local lines=()
    for e in "${estates[@]}"; do
        if running_instance "$e"; then
            lines+=("$(printf '%-30s : RUNNING' "$(human_name "$e")")")
        else
            lines+=("$(printf '%-30s : STOPPED' "$(human_name "$e")")")
        fi
    done

    {
        echo "REGION STATUS"
        echo "-------------"
        for l in "${lines[@]}"; do
            echo "$l"
        done
    } > /tmp/vg_status.$$

    dialog_cmd --textbox /tmp/vg_status.$$ 25 70
    rm -f /tmp/vg_status.$$
}

# ---------------------------------------------------------
# Static System Stats (snapshot)
# ---------------------------------------------------------
static_stats() {
    local cpu_line user nice system idle iowait irq softirq steal guest
    cpu_line=$(grep '^cpu ' /proc/stat)
    read -r _ user nice system idle iowait irq softirq steal guest _ <<<"$cpu_line"
    local total=$((user+nice+system+idle+iowait+irq+softirq+steal))
    local used=$((total-idle-iowait))
    local cpu_pct=$((100 * used / total))

    local ram_str
    ram_str=$(awk '/MemTotal/ {t=$2} /MemAvailable/ {a=$2} END {u=(t-a)/1024/1024; tt=t/1024/1024; printf "%.1fG / %.1fG", u, tt}' /proc/meminfo)

    local disk_str
    disk_str=$(df -h / | awk 'NR==2 {print $3 " / " $2 " used (" $5 ")"}')

    local rx tx
    read -r rx tx <<<"$(awk -F'[: ]+' 'NR>2 && $1 != "lo" {rx+=$3; tx+=$11} END {print rx, tx}' /proc/net/dev)"

    {
        echo "STATIC SYSTEM SNAPSHOT"
        echo "----------------------"
        echo
        echo "CPU Usage : ${cpu_pct}%"
        echo "RAM Usage : ${ram_str}"
        echo "Disk Root : ${disk_str}"
        echo
        echo "Network (raw counters):"
        echo "RX Bytes : ${rx}"
        echo "TX Bytes : ${tx}"
    } > /tmp/vg_sysstat.$$

    dialog_cmd --textbox /tmp/vg_sysstat.$$ 22 70
    rm -f /tmp/vg_sysstat.$$
}

# ---------------------------------------------------------
# Live System Stats (terminal mode, fully working)
# ---------------------------------------------------------
live_stats_terminal() {

    # Create temp script
    local script="/tmp/live_stats_$$.sh"

    cat > "$script" <<'EOF'
#!/usr/bin/env bash

clear
echo "VergeGrid Control Panel - Live System Stats"
echo "-------------------------------------------"
echo "Press q to exit."
echo

# Turn off echo and enable immediate read
stty -icanon -echo min 1 time 0

while true; do
    # CPU
    cpu_line=$(grep '^cpu ' /proc/stat)
    read -r _ user nice system idle iowait irq softirq steal guest _ <<<"$cpu_line"
    total=$((user+nice+system+idle+iowait+irq+softirq+steal))
    used=$((total-idle-iowait))
    cpu_pct=$((100 * used / total))

    # RAM
    ram_str=$(awk '/MemTotal/ {t=$2} /MemAvailable/ {a=$2} \
        END {u=(t-a)/1024/1024; tt=t/1024/1024; printf "%.1fG / %.1fG", u, tt}' /proc/meminfo)

    # Disk
    disk_str=$(df -h / | awk 'NR==2 {print $3 " / " $2 " used (" $5 ")"}')

    # Network
    read -r rx tx <<<"$(awk -F'[: ]+' 'NR>2 && $1!="lo" {rx+=$3; tx+=$11} END {print rx, tx}' /proc/net/dev)"

    clear
    echo "VergeGrid Control Panel - Live System Stats"
    echo
    echo "CPU Usage : ${cpu_pct}%"
    echo "RAM Usage : ${ram_str}"
    echo "Disk Root : ${disk_str}"
    echo
    echo "Network:"
    echo "RX Bytes : ${rx}"
    echo "TX Bytes : ${tx}"
    echo
    echo "Press q to return..."

    read -t 1 -n 1 key
    if [[ "$key" == "q" ]]; then
        break
    fi
done

stty sane
EOF

    chmod +x "$script"

    # Open tab and run the script directly
    local session
    session=$(new_tab)
    set_tab_title "$session" "Live Stats"

    run_in_tab "$session" "$script; exit"
}

# ---------------------------------------------------------
# System Info Menu
# ---------------------------------------------------------
system_info_menu() {
    while true; do
        local choice
        choice=$(dialog_cmd --stdout --menu "System Information" 20 70 10 \
            1 "Operating System details" \
            2 "Kernel details" \
            3 "Hardware info (CPU / RAM)" \
            4 "System Stats (Static)" \
            5 "Live System Stats (Terminal)" \
            6 "Back")

        case "$choice" in
            1)
                {
                    echo "OS RELEASE (/etc/os-release)"
                    echo "--------------------------------"
                    if [ -r /etc/os-release ]; then
                        cat /etc/os-release
                    else
                        echo "No /etc/os-release found."
                    fi
                } > /tmp/vg_osinfo.$$
                dialog_cmd --textbox /tmp/vg_osinfo.$$ 25 80
                rm -f /tmp/vg_osinfo.$$
                ;;
            2)
                {
                    echo "KERNEL DETAILS"
                    echo "--------------"
                    echo
                    echo "uname -a:"
                    uname -a
                    echo
                    if command -v lsb_release >/dev/null 2>&1; then
                        echo "lsb_release -a:"
                        lsb_release -a
                    fi
                } > /tmp/vg_kernel.$$
                dialog_cmd --textbox /tmp/vg_kernel.$$ 25 80
                rm -f /tmp/vg_kernel.$$
                ;;
            3)
                {
                    echo "HARDWARE INFO"
                    echo "-------------"
                    echo
                    if command -v lscpu >/dev/null 2>&1; then
                        echo "lscpu:"
                        lscpu
                        echo
                    fi
                    echo "Memory:"
                    free -h || echo "free -h not available."
                } > /tmp/vg_hw.$$
                dialog_cmd --textbox /tmp/vg_hw.$$ 25 80
                rm -f /tmp/vg_hw.$$
                ;;
            4)
                static_stats
                ;;
            5)
                # Leave dialog, show live stats in terminal
                clear
                live_stats_terminal
                ;;
            *)
                return
                ;;
        esac
    done
}

# ---------------------------------------------------------
# Batch operations
# ---------------------------------------------------------
start_all() {
    mapfile -t estates < <(detect_estates)
    local to_start=()

    # Only start estates that are STOPPED
    for e in "${estates[@]}"; do
        if ! running_instance "$e"; then
            to_start+=("$e")
        fi
    done

    if [ ${#to_start[@]} -eq 0 ]; then
        dialog_cmd --msgbox "All estates are already running." 10 40
        return
    fi

    local total="${#to_start[@]}"
    local count=0

    for e in "${to_start[@]}"; do
        start_instance "$e"
        count=$((count+1))

        if (( count % BATCH_SIZE == 0 && count < total )); then
            dialog_cmd --infobox "Cooling for ${BATCH_DELAY}s…" 5 40
            sleep "$BATCH_DELAY"
        fi
    done
}

stop_all() {
    mapfile -t estates < <(detect_estates)
    [ ${#estates[@]} -eq 0 ] && return

    local choice
    choice=$(dialog_cmd --stdout --menu "STOP ALL ESTATES" 15 60 5 \
        1 "Graceful" \
        2 "Force Kill" \
        3 "Cancel")

    local mode
    case "$choice" in
        1) mode="graceful" ;;
        2) mode="force" ;;
        *) return ;;
    esac

    for e in "${estates[@]}"; do
        stop_instance "$e" "$mode"
    done
}

# ---------------------------------------------------------
# Login Control Functions
# ---------------------------------------------------------
login_menu() {
    local choice
    choice=$(dialog_cmd --stdout --menu "Login Controls" 15 60 10 \
        1 "Enable logins on ONE region" \
        2 "Disable logins on ONE region" \
        3 "Show login status on ONE region" \
        4 "Enable logins on ALL RUNNING regions" \
        5 "Disable logins on ALL RUNNING regions" \
        6 "Show login status on ALL RUNNING regions" \
        7 "Set Robust login level" \
        8 "Reset Robust login level" \
        9 "Set Robust login message" \
        10 "Back")

    case "$choice" in
        1) login_region_single enable ;;
        2) login_region_single disable ;;
        3) login_region_single status ;;
        4) login_region_all enable ;;
        5) login_region_all disable ;;
        6) login_region_all status ;;
        7) login_robust_level ;;
        8) login_robust_reset ;;
        9) login_robust_text ;;
        *) return ;;
    esac
}

# Region login commands (single)
login_region_single() {
    local action="$1"

    mapfile -t estates < <(detect_estates)

    local running=()
    for e in "${estates[@]}"; do
        running_instance "$e" && running+=("$e")
    done

    if [ ${#running[@]} -eq 0 ]; then
        dialog_cmd --msgbox "No running regions available." 10 40
        return
    fi

    local menu=()
    for e in "${running[@]}"; do
        menu+=("$e" "$(human_name "$e")")
    done

    local sel
    sel=$(dialog_cmd --stdout --menu "Select Running Region" 20 60 12 "${menu[@]}")
    [ -z "$sel" ] && return

    local session
    session=$(load_session "$(estate_session_file "$sel")")

    case "$action" in
        enable) send_text "$session" "login enable" ;;
        disable) send_text "$session" "login disable" ;;
        status) send_text "$session" "login status" ;;
    esac
}

# Region login commands (ALL running)
login_region_all() {
    local action="$1"

    mapfile -t estates < <(detect_estates)

    local running=()
    for e in "${estates[@]}"; do
        running_instance "$e" && running+=("$e")
    done

    if [ ${#running[@]} -eq 0 ]; then
        dialog_cmd --msgbox "No running regions to update." 10 40
        return
    fi

    for e in "${running[@]}"; do
        local session
        session=$(load_session "$(estate_session_file "$e")")

        case "$action" in
            enable) send_text "$session" "login enable" ;;
            disable) send_text "$session" "login disable" ;;
            status) send_text "$session" "login status" ;;
        esac
    done
}

# Robust login controls
login_robust_level() {
    local lvl
    lvl=$(dialog_cmd --stdout --inputbox "Enter minimum login level:" 10 50)
    [ -z "$lvl" ] && return

    local session
    session=$(load_session "$robust_session_file")
    send_text "$session" "login level $lvl"
}

login_robust_reset() {
    local session
    session=$(load_session "$robust_session_file")
    send_text "$session" "login reset"
}

login_robust_text() {
    local text
    text=$(dialog_cmd --stdout --inputbox "Enter login message:" 10 60)
    [ -z "$text" ] && return

    local session
    session=$(load_session "$robust_session_file")
    send_text "$session" "login text $text"
}

# ---------------------------------------------------------
# Instance selection (generic actions)
# ---------------------------------------------------------
instance_select() {
    local action="$1"

    mapfile -t estates < <(detect_estates)

    local menu=()
    for e in "${estates[@]}"; do
        if running_instance "$e"; then
            menu+=("$e" "Running")
        else
            menu+=("$e" "Stopped")
        fi
    done

    local sel
    sel=$(dialog_cmd --stdout --menu "Select Estate" 20 60 12 "${menu[@]}")
    [ -z "$sel" ] && return

    case "$action" in
        start)    start_instance "$sel" ;;
        stop)     stop_instance "$sel" ;;
        restart)  restart_instance "$sel" ;;
        reload)   reload_config "$sel" ;;
        editargs) edit_estate_args "$sel" ;;
    esac
}

# ---------------------------------------------------------
# Settings Menu
# ---------------------------------------------------------
settings_menu() {
    while true; do
        local choice
        choice=$(dialog_cmd --stdout --menu "Settings" 15 70 10 \
            1 "Set BASE (Current: $BASE)" \
            2 "Set ESTATES (Current: $ESTATES)" \
            3 "Save and Exit")

        case "$choice" in
            1)
                new=$(dialog_cmd --stdout --inputbox "New BASE path:" 10 70 "$BASE")
                [ -n "$new" ] && BASE="$new"
                ;;
            2)
                new=$(dialog_cmd --stdout --inputbox "New ESTATES path:" 10 70 "$ESTATES")
                [ -n "$new" ] && ESTATES="$new"
                ;;
            3)
                save_settings
                return
                ;;
        esac
    done
}

# ---------------------------------------------------------
# Main Menu
# ---------------------------------------------------------
main_menu() {
    while true; do
        local title
        title="$(build_header)"

        local choice
        choice=$(dialog_cmd --stdout --menu "$title" 22 70 15 \
            1  "Start Robust" \
            2  "Stop Robust" \
            3  "Start ALL Estates" \
            4  "Stop ALL Estates" \
            5  "Start One Estate" \
            6  "Stop One Estate" \
            7  "Restart One Estate" \
            8  "Reload Config" \
            9  "Edit Estate Args" \
            10 "Region Status" \
            11 "System Info" \
            12 "Login Controls" \
            13 "Settings" \
            14 "Quit")

        case "$choice" in
            1)  start_robust ;;
            2)  stop_robust ;;
            3)  start_all ;;
            4)  stop_all ;;
            5)  instance_select start ;;
            6)  instance_select stop ;;
            7)  instance_select restart ;;
            8)  instance_select reload ;;
            9)  instance_select editargs ;;
            10) view_status ;;
            11) system_info_menu ;;
            12) login_menu ;;
            13) settings_menu ;;
            14) clear; exit 0 ;;
        esac
    done
}

main_menu
