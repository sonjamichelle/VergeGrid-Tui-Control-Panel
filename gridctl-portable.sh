#!/usr/bin/bash

# If not running under bash (for example launched with /bin/sh), re exec with bash.
if [ -z "$BASH_VERSION" ]; then
    exec /usr/bin/env bash "$0" "$@"
fi

# --------------------------------------------------------------------
# Version info
# --------------------------------------------------------------------
VG_VERSION="v0.9.0-alpha"
VG_DATE="$(git -C "$(dirname "$0")" log -1 --date=format:'%b %d %Y %H:%M' --format='%cd' 2>/dev/null || date +'%b %d %Y %H:%M')"   # git commit timestamp fallback to now

export NCURSES_NO_UTF8_ACS=1
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8

SETTINGS_FILE="$HOME/.vergegrid_settings"
SETTINGS_FOUND=0

# ---------------------------------------------------------
# Load and save settings
# ---------------------------------------------------------
load_settings() {
    SETTINGS_FOUND=0
    if [ -f "$SETTINGS_FILE" ]; then
        # shellcheck source=/dev/null
        source "$SETTINGS_FILE"
        SETTINGS_FOUND=1
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
# tmux backend (required)
# ---------------------------------------------------------
session_safe_name() {
    echo "${1//[^A-Za-z0-9_.-]/_}"
}

ensure_tmux() {
    if command -v tmux >/dev/null 2>&1; then
        return
    fi
    echo "tmux is required for interactive OpenSim/Robust control."
    if ! command -v sudo >/dev/null 2>&1; then
        echo "sudo not available; please install tmux manually." >&2
        exit 1
    fi
    local installer=""
    if command -v apt-get >/dev/null 2>&1; then
        installer="sudo apt-get update && sudo apt-get install -y tmux"
    elif command -v dnf >/dev/null 2>&1; then
        installer="sudo dnf install -y tmux"
    elif command -v yum >/dev/null 2>&1; then
        installer="sudo yum install -y tmux"
    elif command -v zypper >/dev/null 2>&1; then
        installer="sudo zypper install -y tmux"
    elif command -v pacman >/dev/null 2>&1; then
        installer="sudo pacman -Sy --noconfirm tmux"
    fi
    if [ -z "$installer" ]; then
        echo "No supported package manager detected; please install tmux manually." >&2
        exit 1
    fi
    read -rp "Install tmux now? [y/N] " ans
    case "$ans" in
        y|Y) eval "$installer" || { echo "tmux install failed." >&2; exit 1; } ;;
        *)   echo "tmux not installed; exiting." >&2; exit 1 ;;
    esac
    if ! command -v tmux >/dev/null 2>&1; then
        echo "tmux still not found after install attempt; exiting." >&2
        exit 1
    fi
}

ensure_tmux
BACKEND="tmux"
TMUX_SESSION="${VG_TMUX_SESSION:-vgctl}"

backend_init() {
    if ! tmux has-session -t "$TMUX_SESSION" 2>/dev/null; then
        tmux new-session -d -s "$TMUX_SESSION" -x 200 -y 50 >/dev/null
    fi
}

backend_new_session() {
    local title="$1" cmd="$2" name
    backend_init
    name="$(session_safe_name "$title")"
    tmux new-window -t "$TMUX_SESSION" -n "$name" "bash -lc \"$cmd\"" >/dev/null
    echo "${TMUX_SESSION}:${name}"
}

backend_send_text() {
    local session="$1" text="$2"
    tmux send-keys -t "$session" "$text" C-m
}

backend_close() {
    local session="$1"
    tmux kill-window -t "$session" >/dev/null
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
            echo "Process exited cleanly. Closing tmux window..."
            backend_close "$session"
            break
        fi
        sleep 1
    done
}

# ---------------------------------------------------------
# Start / Stop Robust
# ---------------------------------------------------------
start_robust() {
    local session
    session=$(backend_new_session "robust" \
        "cd \"$BASE\"; \
         if [ -f Robust.dll ]; then dotnet Robust.dll -inifile=Robust.HG.ini; \
         elif [ -f Robust.exe ]; then mono --desktop -O=all Robust.exe -inifile=Robust.HG.ini; \
         else echo 'ERROR: No Robust.dll or Robust.exe found in \$(pwd)'; fi")
    save_session "$robust_session_file" "$session"
    dialog_cmd --msgbox "Robust started in tmux window: $session\nAttach: tmux attach -t ${TMUX_SESSION}" 10 70
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
            backend_send_text "$session" "shutdown"
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

    if running_instance "$estate"; then
        dialog_cmd --msgbox "$(human_name "$estate") is already running." 8 50
        return
    fi

    local argfile="$ESTATES/$estate/estate.args"
    local extra=""
    [ -f "$argfile" ] && extra=$(cat "$argfile")

    local session
    session=$(backend_new_session "estate-$estate" \
        "cd \"$BASE\"; \
         ulimit -s 262144; \
         exec dotnet OpenSim.dll --hypergrid=true --inidirectory=\"$dir\" $extra")

    save_session "$(estate_session_file "$estate")" "$session"
    [ "$2" = "true" ] || dialog_cmd --msgbox "$(human_name "$estate") started in tmux window: $session\nAttach: tmux attach -t ${TMUX_SESSION}" 10 70
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
            backend_send_text "$session" "shutdown"
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

    backend_send_text "$session" "config reload"
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

    dialog_cmd --exit-label "Back" --textbox /tmp/vg_status.$$ 25 70
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
trap 'stty sane; exit' INT TERM

# Helper to grab CPU counters into an associative array
read_cpu_snapshot() {
    local -n out=$1
    out=()
    while read -r label user nice system idle iowait irq softirq steal rest; do
        [[ "$label" != cpu* ]] && continue
        out["$label"]="$user $nice $system $idle $iowait $irq $softirq $steal"
    done < /proc/stat
}

calc_cpu_pct() {
    local prev_line="$1" curr_line="$2"
    [[ -z "$prev_line" || -z "$curr_line" ]] && { echo 0; return; }
    local pu pn ps pi poi pir psf pst
    local cu cn cs ci coi cir csf cst
    read -r pu pn ps pi poi pir psf pst <<<"$prev_line"
    read -r cu cn cs ci coi cir csf cst <<<"$curr_line"
    local prev_total=$((pu+pn+ps+pi+poi+pir+psf+pst))
    local curr_total=$((cu+cn+cs+ci+coi+cir+csf+cst))
    local totald=$((curr_total-prev_total))
    local idled=$(((ci+coi)-(pi+poi)))
    local usedd=$((totald-idled))
    if (( totald <= 0 )); then
        echo 0
    else
        echo $((100 * usedd / totald))
    fi
}

format_rate() {
    local bytes=${1:-0}
    awk -v b="$bytes" 'BEGIN {
        if (b < 0) b = 0;
        split("B/s KB/s MB/s GB/s", u, " ");
        idx = 1;
        while (b >= 1024 && idx < 4) {
            b /= 1024;
            idx++;
        }
        printf "%.1f %s\n", b, u[idx];
    }'
}

read_disk_bytes() {
    awk '
        BEGIN {rs=0; ws=0}
        $3 ~ /^(loop|ram)/ {next}
        $3 ~ /^(sd|vd|xvd|nvme|md|dm-)/ {
            rs += $6;
            ws += $10;
        }
        END {printf "%.0f %.0f\n", rs*512, ws*512}
    ' /proc/diskstats
}

get_default_iface() {
    local iface=""
    if command -v ip >/dev/null 2>&1; then
        iface=$(ip route get 1.1.1.1 2>/dev/null | awk '/dev/ {for (i=1;i<=NF;i++) if ($i=="dev") {print $(i+1); exit}}')
        if [ -z "$iface" ]; then
            iface=$(ip -o -4 route show to default 2>/dev/null | awk 'NR==1 {for (i=1;i<=NF;i++) if ($i=="dev") {print $(i+1); exit}}')
        fi
        if [ -z "$iface" ]; then
            iface=$(ip -o -4 addr show up scope global 2>/dev/null | awk 'NR==1 {print $2}')
        fi
    fi
    if [ -z "$iface" ]; then
        for dev in /sys/class/net/*; do
            [ -d "$dev" ] || continue
            base=${dev##*/}
            [ "$base" = "lo" ] && continue
            iface="$base"
            break
        done
    fi
    echo "$iface"
}

read_net_bytes() {
    local iface="$1" rx tx
    if [ -n "$iface" ] && [ -r "/sys/class/net/$iface/statistics/rx_bytes" ]; then
        read -r rx < "/sys/class/net/$iface/statistics/rx_bytes"
        read -r tx < "/sys/class/net/$iface/statistics/tx_bytes"
    else
        read -r rx tx <<<"$(awk -F'[: ]+' 'NR>2 {if ($1 == "lo") next; rx+=$3; tx+=$11} END {printf "%.0f %.0f", rx, tx}' /proc/net/dev)"
    fi
    rx=${rx:-0}
    tx=${tx:-0}
    echo "$rx $tx"
}

declare -A prev_cpu curr_cpu
read_cpu_snapshot prev_cpu
net_iface="$(get_default_iface)"
read -r prev_rx prev_tx <<<"$(read_net_bytes "$net_iface")"
read -r prev_disk_read prev_disk_write <<<"$(read_disk_bytes)"

while true; do
    read_cpu_snapshot curr_cpu
    cpu_pct=$(calc_cpu_pct "${prev_cpu[cpu]}" "${curr_cpu[cpu]}")

    mapfile -t core_labels < <(printf '%s\n' "${!curr_cpu[@]}" | grep -E '^cpu[0-9]+' | sort -V)
    core_lines=()
    for label in "${core_labels[@]}"; do
        pct=$(calc_cpu_pct "${prev_cpu[$label]}" "${curr_cpu[$label]}")
        core="${label#cpu}"
        core_lines+=("Core ${core} : ${pct}%")
    done
    for key in "${!curr_cpu[@]}"; do
        prev_cpu["$key"]="${curr_cpu[$key]}"
    done

    # Disk IO (bytes per interval)
    read -r disk_read disk_write <<<"$(read_disk_bytes)"
    disk_read_diff=$((disk_read-prev_disk_read))
    disk_write_diff=$((disk_write-prev_disk_write))
    (( disk_read_diff < 0 )) && disk_read_diff=0
    (( disk_write_diff < 0 )) && disk_write_diff=0
    prev_disk_read=$disk_read
    prev_disk_write=$disk_write

    # RAM
    ram_str=$(awk '/MemTotal/ {t=$2} /MemAvailable/ {a=$2} \
        END {u=(t-a)/1024/1024; tt=t/1024/1024; printf "%.1fG / %.1fG", u, tt}' /proc/meminfo)

    # Disk
    disk_str=$(df -h / | awk 'NR==2 {print $3 " / " $2 " used (" $5 ")"}')

    # Network
    read -r rx tx <<<"$(read_net_bytes "$net_iface")"
    net_rx_diff=$((rx-prev_rx))
    net_tx_diff=$((tx-prev_tx))
    (( net_rx_diff < 0 )) && net_rx_diff=0
    (( net_tx_diff < 0 )) && net_tx_diff=0
    prev_rx=$rx
    prev_tx=$tx

    disk_read_rate=$(format_rate "$disk_read_diff")
    disk_write_rate=$(format_rate "$disk_write_diff")
    net_rx_rate=$(format_rate "$net_rx_diff")
    net_tx_rate=$(format_rate "$net_tx_diff")
    net_label=${net_iface:-All}

    clear
    echo "VergeGrid Control Panel - Live System Stats"
    echo
    echo "CPU Usage : ${cpu_pct}%"
    if ((${#core_lines[@]} > 0)); then
        echo "Per-Core:"
        for line in "${core_lines[@]}"; do
            echo "  $line"
        done
        echo
    fi
    echo "RAM Usage : ${ram_str}"
    echo "Disk Root : ${disk_str}"
    echo "Disk I/O  : Read ${disk_read_rate} | Write ${disk_write_rate}"
    echo
    echo "Network (${net_label}):"
    echo "RX Rate : ${net_rx_rate}"
    echo "TX Rate : ${net_tx_rate}"
    echo
    echo "Press q to return..."

    key=""
    read -t 1 -n 1 key || true
    if [[ "$key" == "q" ]]; then
        break
    fi
done

stty sane
EOF

    chmod +x "$script"

    "$script"
    rm -f "$script"
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
        dialog_cmd --infobox "Starting estate:\n\n$(human_name "$e")" 6 60
        start_instance "$e" true
        sleep 2

        if running_instance "$e"; then
            dialog_cmd --infobox "Estate started successfully:\n\n$(human_name "$e")" 6 60
        else
            dialog_cmd --infobox "FAILED to start estate:\n\n$(human_name "$e")" 6 60
        fi

        count=$((count+1))
        sleep 1

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
        if ! running_instance "$e"; then
            continue
        fi

        dialog_cmd --infobox "Stopping estate:\n\n$(human_name "$e")" 6 60
        stop_instance "$e" "$mode"
        sleep 2

        if running_instance "$e"; then
            dialog_cmd --infobox "FAILED to stop estate:\n\n$(human_name "$e")" 6 60
        else
            dialog_cmd --infobox "Estate stopped:\n\n$(human_name "$e")" 6 60
        fi

        sleep 1
    done
}

robust_controls_menu() {
    while true; do
        local choice
        choice=$(dialog_cmd --stdout --menu "Robust Controls" 18 60 6 \
            1 "Start Robust" \
            2 "Stop Robust" \
            3 "Attach to Robust console (tmux)" \
            4 "Back")

        case "$choice" in
            1) start_robust ;;
            2) stop_robust ;;
            3) attach_robust_console ;;
            *) return ;;
        esac
    done
}

estate_controls_menu() {
    while true; do
        local choice
        choice=$(dialog_cmd --stdout --menu "Estate Controls" 22 70 13 \
            1 "Start ALL Estates" \
            2 "Stop ALL Estates" \
            3 "Start ONE Estate" \
            4 "Stop ONE Estate" \
            5 "Restart ONE Estate" \
            6 "Reload Config on ONE Estate" \
            7 "Edit Estate Args" \
            8 "Attach to Estate console (tmux)" \
            9 "Region Status" \
            10 "Back")

        case "$choice" in
            1) start_all ;;
            2) stop_all ;;
            3) instance_select start ;;
            4) instance_select stop ;;
            5) instance_select restart ;;
            6) instance_select reload ;;
            7) instance_select editargs ;;
            8) attach_estate_console ;;
            9) view_status ;;
            *) return ;;
        esac
    done
}

# ---------------------------------------------------------
# Login Control Functions
# ---------------------------------------------------------

# Send a console command, wait briefly, and capture the lines that appear
# after it. Used for commands where we must read the response (login status).
capture_session_command_output() {
    local session="$1" cmd="$2" delay="${3:-1}"

    [ -z "$session" ] && return

    backend_send_text "$session" "$cmd"
    sleep "$delay"

    local capture
    if ! capture=$(tmux capture-pane -t "$session" -p -S -200 2>/dev/null); then
        return
    fi
    capture="${capture//$'\r'/}"

    mapfile -t lines <<<"$capture"

    local idx=-1 i
    for i in "${!lines[@]}"; do
        [[ "${lines[$i]}" == *"$cmd"* ]] && idx=$i
    done

    (( idx == -1 )) && return

    local out=()
    local prompt_re='[[:space:]]*[#>]$'
    local count=0
    for ((i=idx+1; i<${#lines[@]}; i++)); do
        local line="${lines[$i]}"
        if [[ "$line" =~ $prompt_re ]]; then
            break
        fi
        out+=("$line")
        count=$((count+1))
        (( count >= 8 )) && break
    done

    printf '%s\n' "${out[@]}"
}

extract_login_status_line() {
    local session="$1"
    local raw
    raw="$(capture_session_command_output "$session" "login status")"

    if [ -z "$raw" ]; then
        echo "No response"
        return
    fi

    local line trimmed fallback=""
    while IFS= read -r line; do
        trimmed="$(echo "$line" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
        [ -z "$trimmed" ] && continue
        if [[ "$trimmed" =~ [Ll]ogin ]]; then
            echo "$trimmed"
            return
        fi
        [ -z "$fallback" ] && fallback="$trimmed"
    done <<<"$raw"

    if [ -n "$fallback" ]; then
        echo "$fallback"
    else
        echo "No response"
    fi
}

show_login_status_report() {
    local regions=("$@")
    local outfile="/tmp/vg_login_status.$$"

    {
        echo "LOGIN STATUS (RUNNING REGIONS)"
        echo "--------------------------------"
        for e in "${regions[@]}"; do
            local session human status
            human="$(human_name "$e")"
            session=$(load_session "$(estate_session_file "$e")")
            if [ -z "$session" ]; then
                printf '%-30s : %s\n' "$human" "Session not found"
                continue
            fi
            status="$(extract_login_status_line "$session")"
            [ -z "$status" ] && status="No response"
            printf '%-30s : %s\n' "$human" "$status"
        done
    } > "$outfile"

    dialog_cmd --exit-label "Back" --textbox "$outfile" 25 80
    rm -f "$outfile"
}

login_menu() {
    while true; do
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
            6) login_status_all_panel ;;
            7) login_robust_level ;;
            8) login_robust_reset ;;
            9) login_robust_text ;;
            *) return ;;
        esac
    done
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
        enable) backend_send_text "$session" "login enable" ;;
        disable) backend_send_text "$session" "login disable" ;;
        status) backend_send_text "$session" "login status" ;;
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

    if [ "$action" = "status" ]; then
        show_login_status_report "${running[@]}"
        return
    fi

    for e in "${running[@]}"; do
        local session
        session=$(load_session "$(estate_session_file "$e")")

        case "$action" in
            enable) backend_send_text "$session" "login enable" ;;
            disable) backend_send_text "$session" "login disable" ;;
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
    backend_send_text "$session" "login level $lvl"
}

login_robust_reset() {
    local session
    session=$(load_session "$robust_session_file")
    backend_send_text "$session" "login reset"
}

login_robust_text() {
    local text
    text=$(dialog_cmd --stdout --inputbox "Enter login message:" 10 60)
    [ -z "$text" ] && return

    local session
    session=$(load_session "$robust_session_file")
    backend_send_text "$session" "login text $text"
}

# ---------------------------------------------------------
# Login status panel (all running regions)
# ---------------------------------------------------------
get_login_status() {
    local estate="$1"
    local session
    session=$(load_session "$(estate_session_file "$estate")")
    [ -z "$session" ] && { echo "UNKNOWN"; return; }

    # Ask console, then capture recent pane output to infer status.
    backend_send_text "$session" "login status"
    sleep 1

    local status="UNKNOWN"
    local pane
    pane=$(tmux capture-pane -pt "$session" -S -200 2>/dev/null | tail -n 200)

    while IFS= read -r line; do
        line_lower=${line,,}
        case "$line_lower" in
            *logins*enabled*|*login*enable*)   status="ENABLED" ;;
            *logins*disabled*|*login*disable*) status="DISABLED" ;;
        esac
    done <<< "$pane"

    echo "$status"
}

login_status_all_panel() {
    mapfile -t estates < <(detect_estates)

    local running=()
    for e in "${estates[@]}"; do
        running_instance "$e" && running+=("$e")
    done

    if [ ${#running[@]} -eq 0 ]; then
        dialog_cmd --msgbox "No running regions to query." 10 40
        return
    fi

    local lines=()
    for e in "${running[@]}"; do
        local status
        status=$(get_login_status "$e")
        lines+=("$(printf '%-30s : %s' "$(human_name "$e")" "$status")")
    done

    {
        echo "LOGIN STATUS"
        echo "------------"
        for l in "${lines[@]}"; do
            echo "$l"
        done
    } > /tmp/vg_loginstatus.$$

    dialog_cmd --exit-label "Back" --textbox /tmp/vg_loginstatus.$$ 25 70
    rm -f /tmp/vg_loginstatus.$$
}

# ---------------------------------------------------------
# Attach to tmux session
# ---------------------------------------------------------
attach_tmux_session() {
    if ! tmux has-session -t "$TMUX_SESSION" 2>/dev/null; then
        dialog_cmd --msgbox "tmux session '$TMUX_SESSION' not found.\nStart Robust or a region first." 10 70
        return
    fi

    clear
    echo "Attaching to tmux session '$TMUX_SESSION'."
    echo "Detach with Ctrl-b then d to return to this menu."
    tmux attach -t "$TMUX_SESSION"
    clear
}

attach_estate_console() {
    mapfile -t estates < <(detect_estates)
    declare -A estate_sessions=()
    local menu=()

    for e in "${estates[@]}"; do
        local session
        session=$(load_session "$(estate_session_file "$e")")
        [ -z "$session" ] && continue
        if ! tmux has-session -t "${session%%:*}" 2>/dev/null; then
            continue
        fi
        estate_sessions["$e"]="$session"
        menu+=("$e" "$(human_name "$e")")
    done

    if [ ${#menu[@]} -eq 0 ]; then
        dialog_cmd --msgbox "No estate tmux consoles available." 10 60
        return
    fi

    local sel
    sel=$(dialog_cmd --stdout --menu "Select Estate Console" 20 70 12 "${menu[@]}")
    [ -z "$sel" ] && return

    clear
    echo "Attaching to estate console (${estate_sessions[$sel]})."
    echo "Detach with Ctrl-b then d to return to this menu."
    tmux attach -t "${estate_sessions[$sel]}"
    clear
}

attach_robust_console() {
    local session
    session=$(load_session "$robust_session_file")
    if [ -z "$session" ]; then
        dialog_cmd --msgbox "No Robust session found.\nStart Robust first." 10 60
        return
    fi

    if ! tmux has-session -t "${session%%:*}" 2>/dev/null; then
        dialog_cmd --msgbox "tmux session for Robust not found.\nStart Robust first." 10 60
        return
    fi

    clear
    echo "Attaching directly to Robust console ($session)."
    echo "Detach with Ctrl-b then d to return to this menu."
    tmux attach -t "$session"
    clear
}

# ---------------------------------------------------------
# Instance selection (generic actions)
# ---------------------------------------------------------
instance_select() {
    local action="$1"

    mapfile -t estates < <(detect_estates)

    local menu=()
    for e in "${estates[@]}"; do
        local state
        if running_instance "$e"; then
            state="Running"
            if [ "$action" = "start" ]; then
                continue    # do not show running estates in the Start menu
            fi
        else
            state="Stopped"
        fi
        menu+=("$e" "$state")
    done

    if [ ${#menu[@]} -eq 0 ]; then
        dialog_cmd --msgbox "No eligible estates for this action." 10 60
        return
    fi

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

# Ensure we have user-provided BASE/ESTATES on first launch instead of defaults.
ensure_settings_configured() {
    if [ "$SETTINGS_FOUND" -eq 1 ]; then
        return
    fi

    dialog_cmd --msgbox "First run detected. Please configure BASE and ESTATES directories." 10 70
    settings_menu
    load_settings
    SETTINGS_FOUND=1
}

# ---------------------------------------------------------
# Main Menu
# ---------------------------------------------------------
main_menu() {
    while true; do
        local title
        title="$(build_header)"

        local choice
        choice=$(dialog_cmd --stdout --menu "$title" 22 70 6 \
            1 "Robust Controls" \
            2 "Estate Controls" \
            3 "Login Controls" \
            4 "System Info" \
            5 "Settings" \
            6 "Quit")

        case "$choice" in
            1) robust_controls_menu ;;
            2) estate_controls_menu ;;
            3) login_menu ;;
            4) system_info_menu ;;
            5) settings_menu ;;
            6) clear; exit 0 ;;
        esac
    done
}

ensure_settings_configured
main_menu
