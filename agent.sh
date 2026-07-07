#!/bin/sh
# Brimfull monitoring agent — POSIX sh, no dependencies beyond coreutils + curl
BRIMFULL_VERSION="1.0.0"

# Required env vars — exit silently if missing
[ -z "${BRIMFULL_URL}" ] && exit 0
[ -z "${BRIMFULL_KEY}" ] && exit 0

BRIMFULL_AUTO_UPDATE="${BRIMFULL_AUTO_UPDATE:-false}"

# ---- Collect metrics ----

BRIMFULL_HOSTNAME="${BRIMFULL_HOSTNAME:-$(hostname)}"
COLLECTED_AT=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# CPU load and core count
if [ -f /proc/loadavg ]; then
    # Linux
    LOAD_1M=$(awk '{print $1}' /proc/loadavg)
    CPU_CORES=$(nproc 2>/dev/null || echo 1)
else
    # macOS: vm.loadavg returns "{ 0.45 0.50 0.55 }"
    LOAD_1M=$(sysctl -n vm.loadavg 2>/dev/null | awk '{gsub(/[{}]/, ""); print $1 + 0}')
    CPU_CORES=$(sysctl -n hw.logicalcpu 2>/dev/null || echo 1)
fi
CPU_PERCENT=$(awk -v loadavg="$LOAD_1M" -v cores="$CPU_CORES" \
    'BEGIN { if (cores < 1) cores = 1; printf "%.2f", loadavg / cores * 100 }')

# Memory
if [ -f /proc/meminfo ]; then
    # Linux
    MEM_TOTAL_KB=$(awk '/^MemTotal:/{print $2}' /proc/meminfo)
    MEM_AVAIL_KB=$(awk '/^MemAvailable:/{print $2}' /proc/meminfo)
    MEM_TOTAL_KB=${MEM_TOTAL_KB:-1}
    MEM_AVAIL_KB=${MEM_AVAIL_KB:-0}
    MEM_USED_KB=$((MEM_TOTAL_KB - MEM_AVAIL_KB))
    MEM_TOTAL_MB=$((MEM_TOTAL_KB / 1024))
    MEM_USED_MB=$((MEM_USED_KB / 1024))
    MEM_PERCENT=$(awk -v used="$MEM_USED_KB" -v total="$MEM_TOTAL_KB" \
        'BEGIN { if (total < 1) total = 1; printf "%.2f", used / total * 100 }')
    SWAP_TOTAL_KB=$(awk '/^SwapTotal:/{print $2}' /proc/meminfo)
    SWAP_FREE_KB=$(awk '/^SwapFree:/{print $2}' /proc/meminfo)
    SWAP_TOTAL_KB=${SWAP_TOTAL_KB:-0}
    SWAP_FREE_KB=${SWAP_FREE_KB:-0}
    SWAP_USED_MB=$(( (SWAP_TOTAL_KB - SWAP_FREE_KB) / 1024 ))
    SWAP_TOTAL_MB=$((SWAP_TOTAL_KB / 1024))
else
    # macOS
    MEM_BYTES=$(sysctl -n hw.memsize 2>/dev/null || echo 0)
    MEM_TOTAL_MB=$(awk -v b="${MEM_BYTES:-0}" 'BEGIN { printf "%d", b / 1048576 }')
    PAGE_SIZE=$(sysctl -n hw.pagesize 2>/dev/null || echo 4096)
    VM_STAT=$(vm_stat 2>/dev/null)
    PAGES_FREE=$(printf '%s' "$VM_STAT" | awk '/Pages free:/{gsub(/\./, "", $NF); print $NF + 0}')
    PAGES_SPEC=$(printf '%s' "$VM_STAT" | awk '/Pages speculative:/{gsub(/\./, "", $NF); print $NF + 0}')
    MEM_FREE_MB=$(awk -v pf="${PAGES_FREE:-0}" -v ps="${PAGES_SPEC:-0}" -v pg="$PAGE_SIZE" \
        'BEGIN { printf "%d", (pf + ps) * pg / 1048576 }')
    MEM_USED_MB=$((MEM_TOTAL_MB - MEM_FREE_MB))
    MEM_PERCENT=$(awk -v used="$MEM_USED_MB" -v total="$MEM_TOTAL_MB" \
        'BEGIN { if (total < 1) total = 1; printf "%.2f", used / total * 100 }')
    SWAP_TOTAL_MB=0
    SWAP_USED_MB=0
fi

# Uptime in seconds
if [ -f /proc/uptime ]; then
    # Linux: first field is fractional seconds since boot
    UPTIME_SECONDS=$(awk '{ printf "%d", $1 }' /proc/uptime)
else
    # macOS: kern.boottime = "{ sec = 1234567890, usec = 0 } ..."
    BOOT_SEC=$(sysctl -n kern.boottime 2>/dev/null | \
        awk '{ for (i = 1; i <= NF; i++) { if ($i == "sec") { gsub(/,/, "", $(i+1)); print $(i+1) + 0; exit } } }')
    NOW_SEC=$(date +%s)
    UPTIME_SECONDS=$((NOW_SEC - BOOT_SEC))
fi

# Disk metrics — build JSON array, filtering noise filesystems and tiny mounts
DISKS_JSON=$(df -P -k 2>/dev/null | awk '
NR > 1 {
    if (NF < 6) next
    fs = $1; total = $2; used = $3; pct = $5; mount = $NF
    sub(/%/, "", pct)
    if (total + 0 < 512000) next
    if (substr(mount, 1, 6) == "/snap/") next
    if (fs ~ /^(tmpfs|devtmpfs|sysfs|proc|overlay|udev|none|devfs)$/) next
    if (substr(fs, 1, 6) == "cgroup") next
    n++
    e[n] = sprintf("{\"mount\":\"%s\",\"device\":\"%s\",\"used_gb\":%.1f,\"total_gb\":%.1f,\"percent\":%.1f}", mount, fs, used / 1048576, total / 1048576, pct + 0)
}
END {
    printf "["
    for (i = 1; i <= n; i++) {
        if (i > 1) printf ","
        printf "%s", e[i]
    }
    printf "]"
}')

# ---- Assemble JSON payload ----
PAYLOAD=$(printf \
    '{"version":"%s","hostname":"%s","collected_at":"%s","cpu":{"load_1m":%s,"cores":%s,"percent":%s},"memory":{"used_mb":%s,"total_mb":%s,"percent":%s},"swap":{"used_mb":%s,"total_mb":%s},"uptime_seconds":%s,"disks":%s}' \
    "$BRIMFULL_VERSION" \
    "$BRIMFULL_HOSTNAME" \
    "$COLLECTED_AT" \
    "$LOAD_1M" \
    "$CPU_CORES" \
    "$CPU_PERCENT" \
    "$MEM_USED_MB" \
    "$MEM_TOTAL_MB" \
    "$MEM_PERCENT" \
    "$SWAP_USED_MB" \
    "$SWAP_TOTAL_MB" \
    "$UPTIME_SECONDS" \
    "$DISKS_JSON")

# ---- POST metrics to server ----
RESPONSE=$(curl -sf -w '\n__HTTP_STATUS__:%{http_code}' -H "Content-Type: application/json" -H "X-Brimfull-Key: ${BRIMFULL_KEY}" -d "$PAYLOAD" "${BRIMFULL_URL}/api/v1/ingest") || { printf '[%s] brimfull-agent error: ingest failed (http %s)\n' "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" "$(printf '%s' "$RESPONSE" | grep '__HTTP_STATUS__' | cut -d: -f2)"; exit 1; }

printf '[%s] brimfull-agent ok host=%s cpu=%s%% mem=%s%%\n' "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" "$BRIMFULL_HOSTNAME" "$CPU_PERCENT" "$MEM_PERCENT"

# ---- Auto-update (opt-in) ----
if [ "$BRIMFULL_AUTO_UPDATE" = "true" ]; then
    UPDATE_URL=$(printf '%s' "$RESPONSE" | awk -F'"update_url"' '
    NF > 1 {
        url_part = $2
        sub(/^[[:space:]]*:[[:space:]]*"/, "", url_part)
        n = split(url_part, a, "\"")
        if (n >= 1 && substr(a[1], 1, 1) == "/") print a[1]
    }')
    if [ -n "$UPDATE_URL" ]; then
        curl -sf "${BRIMFULL_URL}${UPDATE_URL}" -o "$0" || exit 1
        chmod +x "$0"
    fi
fi
