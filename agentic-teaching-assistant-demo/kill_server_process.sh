fuser -k 8999/tcp 2>/dev/null || kill $(ss -tlnp 'sport = :8999' | awk 'NR>1 {print $NF}' | grep -oP 'pid=\K[0-9]+' | head -1) 2>/dev/null; ss -tlnp | grep 8999 || echo "Port 8999: nothing listening"
