#!/data/data/com.termux/files/usr/bin/sh
# Web 面板启停脚本（Termux / Android）
#
# 为什么需要它：直接在终端前台运行 `python3 web_panel.py` 后把 Termux 切到后台，
# 进程会因终端作业控制收到 SIGTTOU/SIGTTIN 而被挂起（ps 状态显示 T），
# 端口随之停止监听，浏览器访问就会一直转圈最后超时。
# 这里用 setsid + nohup 让进程脱离控制终端，并把输出重定向到日志文件，
# 从而不会再被挂起。
#
# 用法：
#   sh panel.sh          # 后台启动
#   sh panel.sh status   # 查看运行状态
#   sh panel.sh logs     # 跟踪日志
#   sh panel.sh restart  # 重启
#   sh panel.sh stop     # 停止

cd "$(dirname "$0")" || exit 1

LOG_DIR=".tmp"
LOG_FILE="$LOG_DIR/server.log"
PATTERN="python[0-9.]* web_panel\.py"

mkdir -p "$LOG_DIR"

is_running() {
    pgrep -f "$PATTERN" >/dev/null 2>&1
}

start() {
    if is_running; then
        echo "面板已在运行：$(pgrep -f "$PATTERN" | tr '\n' ' ')"
        return 0
    fi
    setsid nohup python3 web_panel.py >>"$LOG_FILE" 2>&1 </dev/null &
    sleep 3
    if is_running; then
        echo "面板已启动，日志：$LOG_FILE"
        grep -E "访问地址|Running on" "$LOG_FILE" | tail -3
    else
        echo "启动失败，请查看日志：$LOG_FILE"
        tail -20 "$LOG_FILE"
        return 1
    fi
}

stop() {
    if ! is_running; then
        echo "面板未在运行"
        return 0
    fi
    # 先恢复再终止：被挂起（T 状态）的进程收不到普通 SIGTERM
    pgrep -f "$PATTERN" | xargs -r kill -CONT 2>/dev/null
    pgrep -f "$PATTERN" | xargs -r kill -TERM 2>/dev/null
    sleep 2
    if is_running; then
        pgrep -f "$PATTERN" | xargs -r kill -KILL 2>/dev/null
        sleep 1
    fi
    echo "面板已停止"
}

case "$1" in
    stop)    stop ;;
    restart) stop; start ;;
    status)
        if is_running; then
            echo "运行中：$(pgrep -f "$PATTERN" | tr '\n' ' ')"
            ps -o pid,stat,etime,args -p "$(pgrep -f "$PATTERN" | tr '\n' ',' | sed 's/,$//')" 2>/dev/null
        else
            echo "未运行"
        fi
        ;;
    logs)    tail -f "$LOG_FILE" ;;
    ""|start) start ;;
    *)       echo "用法: sh panel.sh [start|stop|restart|status|logs]" ;;
esac
