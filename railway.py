import os
import random
import threading
import time
from flask import Flask, jsonify, request

# ===================== CONFIG =====================
GRID_W, GRID_H = 20, 20
N_ROBOTS = 20
N_OBSTACLES = 40
N_PRIZES = 30
DT = float(os.environ.get("DT", "0.2"))
CONTROLLED_ROBOT_ID = 1

MOVE_MAP = {
    "RIGHT": (1,0),
    "LEFT": (-1,0),
    "UP": (0,1),
    "DOWN": (0,-1),
    "STAY": (0,0)
}
MOVES = list(MOVE_MAP.values())

# ===================== STATE =====================
state_lock = threading.Lock()
running = False
step_counter = 0
pending_cmds = {}

robots = []
obstacles = set()
prizes = {}

# ===================== INIT =====================
def random_empty(occ):
    while True:
        p = (random.randint(0,GRID_W-1), random.randint(0,GRID_H-1))
        if p not in occ:
            return p

def reset():
    global robots, obstacles, prizes, step_counter, running, pending_cmds
    step_counter = 0
    running = False
    pending_cmds = {}

    occupied = set()
    obstacles = set(random_empty(occupied) for _ in range(N_OBSTACLES))
    occupied |= obstacles

    prizes = {}
    for _ in range(N_PRIZES):
        pos = random_empty(occupied)
        occupied.add(pos)
        prizes[pos] = random.randint(0, 5)

    robots = []
    for i in range(N_ROBOTS):
        pos = random_empty(occupied)
        occupied.add(pos)
        robots.append({
            "id": i,
            "pos": pos,
            "score": 0
        })

reset()

# ===================== SIM LOOP =====================
def sim_loop():
    global step_counter
    while True:
        time.sleep(DT)
        with state_lock:
            if not running:
                continue

            occupied = {r["pos"] for r in robots}
            proposals = {}

            for r in robots:
                rid = r["id"]
                dx,dy = pending_cmds.get(rid, (0,0))
                nx,ny = r["pos"][0]+dx, r["pos"][1]+dy
                if (0 <= nx < GRID_W and 0 <= ny < GRID_H and
                    (nx,ny) not in obstacles):
                    proposals.setdefault((nx,ny), []).append(rid)

            for pos, ids in proposals.items():
                if pos in occupied:
                    continue
                winner = random.choice(ids)
                robots[winner]["pos"] = pos
                if pos in prizes:
                    robots[winner]["score"] += prizes[pos]
                    del prizes[pos]

            step_counter += 1

threading.Thread(target=sim_loop, daemon=True).start()

# ===================== API =====================
app = Flask(__name__)

@app.route("/ACT")
def act():
    global running
    with state_lock:
        running = True
    return jsonify({"status":"RUNNING"})

@app.route("/RST")
def rst():
    with state_lock:
        reset()
    return jsonify({"status":"RESET"})

@app.route("/STT")
def stt():
    with state_lock:
        return jsonify({
            "step": step_counter,
            "running": running,
            "robots": [
                {
                    "id": int(r["id"]),
                    "pos": [int(r["pos"][0]), int(r["pos"][1])],
                    "score": int(r["score"])
                }
                for r in robots
            ],
            "obstacles": [[int(x), int(y)] for x, y in obstacles],
            "prizes": [
                {"pos": [int(x), int(y)], "value": int(v)}
                for (x, y), v in prizes.items()
            ]
        })

@app.route("/CMD")
def cmd():
    robot = int(request.args.get("robot"))
    move = request.args.get("move","").upper()
    if move not in MOVE_MAP:
        return jsonify({"error":"bad move"}),400
    with state_lock:
        pending_cmds[robot] = MOVE_MAP[move]
    return jsonify({"ok":True})
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)