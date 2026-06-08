#!/bin/bash
# Останавливает и удаляет launchd-агент бота.
set -e
PLIST_DST="$HOME/Library/LaunchAgents/com.tradingbot.plist"
launchctl unload "$PLIST_DST" 2>/dev/null || true
rm -f "$PLIST_DST"
echo "✅ Агент остановлен и удалён."
echo "Если включал работу с закрытой крышкой, верни сон: sudo pmset -a disablesleep 0"
