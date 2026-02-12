import random
import asyncio
import time
import os
import json
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
PORT = int(os.environ.get("PORT", 8000))
# ===================== CONFIG =====================
GRID_W, GRID_H = 20, 20
N_ROBOTS = 20
N_OBSTACLES = 40
N_PRIZES = 30
DT = 0.5  # seconds

MOVE_MAP = {
    "RIGHT": (1, 0),
    "LEFT": (-1, 0),
    "UP": (0, 1),
    "DOWN": (0, -1),
    "STAY": (0, 0)
}

# ===================== STATE =====================
state_lock = asyncio.Lock()
running = False
step_counter = 0

robots = []
obstacles = set()
prizes = {}
pending_cmds = {}   # robot_id -> (dx,dy)

# ===================== INIT =====================
def random_empty(occupied):
    while True:
        p = (random.randrange(GRID_W), random.randrange(GRID_H))
        if p not in occupied:
            return p

def reset_state():
    global robots, obstacles, prizes, pending_cmds, step_counter, running

    occupied = set()
    obstacles = set(random_empty(occupied) for _ in range(N_OBSTACLES))
    occupied |= obstacles

    prizes = {}
    for _ in range(N_PRIZES):
        pos = random_empty(occupied)
        occupied.add(pos)
        prizes[pos] = random.randint(1, 5)

    robots = []
    for i in range(N_ROBOTS):
        pos = random_empty(occupied)
        occupied.add(pos)
        robots.append({
            "id": i,
            "pos": pos,
            "score": 0
        })

    pending_cmds = {}
    step_counter = 0
    running = False

reset_state()

# ===================== FASTAPI =====================
app = FastAPI()

# ---------- WebSocket manager ----------
class WSManager:
    def __init__(self):
        self.clients = set()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.clients.add(ws)

    def disconnect(self, ws: WebSocket):
        self.clients.discard(ws)

    async def broadcast(self, data):
        dead = []
        for ws in self.clients:
            try:
                await ws.send_json(data)
            except:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

manager = WSManager()

def build_snapshot():
    return {
        "step": step_counter,
        "running": running,
        "robots": [
            {
                "id": r["id"],
                "pos": [r["pos"][0], r["pos"][1]],
                "score": r["score"]
            } for r in robots
        ],
        "obstacles": [[x, y] for x, y in obstacles],
        "prizes": [
            {"pos": [x, y], "value": v}
            for (x, y), v in prizes.items()
        ]
    }

# ===================== SIM LOOP =====================
async def simulation_loop():
    global step_counter
    next_tick = time.monotonic()

    while True:
        next_tick += DT
        await asyncio.sleep(max(0.0, next_tick - time.monotonic()))

        async with state_lock:
            if not running:
                continue

            occupied = {r["pos"] for r in robots}
            proposals = {}

            for r in robots:
                rid = r["id"]
                dx, dy = pending_cmds.get(rid, (0, 0))
                x, y = r["pos"]
                nx, ny = x + dx, y + dy

                if 0 <= nx < GRID_W and 0 <= ny < GRID_H and (nx, ny) not in obstacles:
                    proposals.setdefault((nx, ny), []).append(rid)

            for pos, ids in proposals.items():
                if pos in occupied:
                    continue
                winner = random.choice(ids)
                robots[winner]["pos"] = pos
                if pos in prizes:
                    robots[winner]["score"] += prizes[pos]
                    del prizes[pos]

            pending_cmds.clear()
            step_counter += 1

            snapshot = build_snapshot()

        await manager.broadcast(snapshot)

# ===================== HTTP API =====================
@app.get("/ACT")
async def act():
    global running
    async with state_lock:
        running = True
    return {"status": "RUNNING"}

@app.get("/RST")
async def rst():
    async with state_lock:
        reset_state()
    return {"status": "RESET"}

@app.get("/CMD")
async def cmd(robot: int, move: str):
    move = move.upper()
    if move not in MOVE_MAP:
        return JSONResponse({"error": "bad move"}, status_code=400)

    async with state_lock:
        if not running:
            return JSONResponse({"error": "not running"}, status_code=400)

        if robot not in pending_cmds:
            pending_cmds[robot] = MOVE_MAP[move]

    return {"ok": True}

# ===================== WEBSOCKET =====================
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    async with state_lock:
        await ws.send_json(build_snapshot())
    try:
        while True:
            msg = await ws.receive_text()
            try:
                data = json.loads(msg)
            except Exception:
                continue

            msg_type = str(data.get("type", "")).upper()
            async with state_lock:
                if msg_type == "ACT":
                    global running
                    running = True
                elif msg_type == "RST":
                    reset_state()
                elif msg_type == "CMD":
                    robot = int(data.get("robot", -1))
                    move = str(data.get("move", "")).upper()
                    if move in MOVE_MAP and robot >= 0:
                        pending_cmds[robot] = MOVE_MAP[move]
    except WebSocketDisconnect:
        manager.disconnect(ws)

# ===================== STARTUP =====================
@app.on_event("startup")
async def startup():
    asyncio.create_task(simulation_loop())

# ===================== ENTRY =====================
# uvicorn server_ws:app --host 0.0.0.0 --port 8002
