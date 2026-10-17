SRC="/mnt/c/Users/Пользователь/Desktop/хакатон/backend"
cd ~/kompas && rm -rf app knowledge tools && cp -r "$SRC/app" "$SRC/knowledge" "$SRC/tools" .
pkill -f "uvicorn app.main:app" 2>/dev/null; sleep 1
rm -rf data
.venv/bin/python -m app.seed --reset >/dev/null
nohup .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8100 --workers 4 --log-level warning > server.log 2>&1 &
sleep 6
.venv/bin/python tools/alert_latency.py --base http://127.0.0.1:8100 --runs 30 | tr -d '\n '; echo
.venv/bin/python tools/load_test.py --base http://127.0.0.1:8100 --levels 10 50 100 200 --seconds 20 --out load_test.json
grep -E "^[a-zA-Z_.]+(Error|Exception)" server.log | sort | uniq -c | sort -rn | head -5
