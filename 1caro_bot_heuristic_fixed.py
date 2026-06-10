#!/usr/bin/env python3
"""
-Pure Heuristic, gon nhat co the
Caro Bot - Da sua: luat Viet Nam + nhan dien ria ban
Khong: minimax, self-learning, chat AI, pattern class, zobrist
Chi co: websocket client + heuristic pick move
"""
import asyncio, struct, time, logging, re, random, os, json
from typing import Tuple

try:
    import websockets
except:
    import subprocess
    subprocess.run(["pip", "install", "websockets", "-q"])
    import websockets
try:
    import requests
except:
    import subprocess
    subprocess.run(["pip", "install", "requests", "-q"])
    import requests

# ── Cau hinh ────────────────────────────────────────────────
WS_URL = "wss://gamevh.net/ws/gameServer"
GAME_URL = "https://gamevh.net/play/caro/0"
USER = "nguyen05511"
PASSWD = "nhat123456"
VERSION = "5.0.2"
GAME_ID = "caro"
RUNTIME = 12 * 3600  # 12 gio
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("caro")

# ── CMD map ─────────────────────────────────────────────────
CMD = {
    300: "PONG", 301: "PING", 302: "LOGIN", 303: "ALERT",
    304: "RIBBON_MESSAGE", 311: "BROADCAST", 312: "INVITE",
    314: "SET_CLIENT_MODE", 315: "CONFIG", 401: "ENTER_PLACE",
    402: "ENTER_CHILD_PLACE", 406: "PLAYER_ENTERED",
    407: "PLAYER_EXITED", 408: "QUICK_PLAY", 414: "GET_TABLE_DATA",
    417: "START_MATCH", 418: "GAMEOVER", 419: "ENTER_STATE",
    420: "SET_TURN", 421: "SET_PLAYER_STATUS", 422: "SET_PLAYER_POINT",
    423: "SET_PLAYER_ATTR", 431: "BALANCE_CHANGED",
    432: "OWNER_CHANGED", 433: "GET_TABLE_DATA_EX", 434: "SET_READY",
    501: "BET", 502: "PLAY", 505: "CHAT", 518: "HIGHLIGHT",
    529: "MOVE", 533: "ASK_DRAW", 534: "SURRENDER", 535: "RETREAT",
}

# ── Binary read/write ───────────────────────────────────────
class R:
    def __init__(self, b):
        self.b = b
        self.o = 0

    def rem(self):
        return len(self.b) - self.o

    def u8(self):
        v = self.b[self.o]
        self.o += 1
        return v

    def i8(self):
        v = struct.unpack_from(">b", self.b, self.o)[0]
        self.o += 1
        return v

    def i16(self):
        v = struct.unpack_from(">h", self.b, self.o)[0]
        self.o += 2
        return v

    def u16(self):
        v = struct.unpack_from(">H", self.b, self.o)[0]
        self.o += 2
        return v

    def i32(self):
        v = struct.unpack_from(">i", self.b, self.o)[0]
        self.o += 4
        return v

    def i64(self):
        hi = struct.unpack_from(">i", self.b, self.o)[0]
        lo = struct.unpack_from(">I", self.b, self.o + 4)[0]
        self.o += 8
        return hi * (1 << 32) + lo

    def asc(self):
        n = self.u8()
        s = self.b[self.o : self.o + n]
        self.o += n
        return s.decode("ascii", "replace")

    def utf(self):
        n = self.i16()
        if n <= 0:
            return ""
        s = self.b[self.o : self.o + n * 2]
        self.o += n * 2
        return s.decode("utf-16-be", "replace")

    def arr(self):
        n = self.i16()
        d = list(self.b[self.o : self.o + n])
        self.o += n
        return d

    def cmd(self):
        f = self.i8()
        if f < 0:
            n = -f
            s = self.b[self.o : self.o + n].decode("ascii", "replace")
            self.o += n
            return s
        s = self.u8()
        cid = (f << 8) | s
        return CMD.get(cid, str(cid))


class W:
    def __init__(self):
        self.p = []

    def u8(self, v):
        self.p.append(struct.pack(">B", v))

    def i8(self, v):
        self.p.append(struct.pack(">b", v))

    def i16(self, v):
        self.p.append(struct.pack(">h", v))

    def i32(self, v):
        self.p.append(struct.pack(">i", v))

    def i64(self, v):
        self.p.append(struct.pack(">iI", v >> 32, v & 0xFFFFFFFF))

    def asc(self, s):
        e = s.encode("ascii", "replace")
        self.p.append(struct.pack(">B", len(e)))
        self.p.append(e)

    def utf(self, s):
        e = s.encode("utf-16-be")
        self.p.append(struct.pack(">h", len(e) // 2))
        self.p.append(e)

    def cmd(self, c):
        cid = next((k for k, v in CMD.items() if v == c), None)
        if cid:
            self.p.append(struct.pack(">H", cid))
        else:
            b = c.encode("ascii")
            self.p.append(struct.pack(">b", -len(b)))
            self.p.append(b)

    def build(self):
        return b"".join(self.p)


# ── Board ────────────────────────────────────────────────────
# SỬA 1: Thêm OUT để phân biệt "ngoài bàn" vs "ô trống trong bàn"
E = -1   # Ô trống trong bàn
OUT = -2  # Ngoài bàn (ria bàn)
O = 0
X = 1
DIRS = [(1, 0), (0, 1), (1, 1), (1, -1)]


class Board:
    def __init__(self, h=15, v=19):
        self.h = h
        self.v = v
        self.g = [[E] * h for _ in range(v)]
        self.hist = []
        self.placed = set()

    def resize(self, h, v):
        self.h = h
        self.v = v
        self.g = [[E] * h for _ in range(v)]
        self.hist = []
        self.placed = set()

    # SỬA 2: get() trả về OUT cho ngoài bàn, E cho ô trống trong bàn
    def get(self, x, y):
        if 0 <= x < self.h and 0 <= y < self.v:
            return self.g[y][x]
        return OUT

    def put(self, x, y, s):
        if 0 <= x < self.h and 0 <= y < self.v:
            self.g[y][x] = s
            self.hist.append((x, y, s))
            self.placed.add((x, y))

    def undo(self, x, y):
        if 0 <= x < self.h and 0 <= y < self.v:
            self.g[y][x] = E
            if self.hist and self.hist[-1][:2] == (x, y):
                self.hist.pop()
            self.placed.discard((x, y))

    def pos2xy(self, p):
        return p % self.h, p // self.h

    def xy2pos(self, x, y):
        return y * self.h + x

    def load_rle(self, data):
        self.g = [[E] * self.h for _ in range(self.v)]
        self.hist = []
        self.placed = set()
        pos = 0
        for u in data:
            s = u - 256 if u > 127 else u
            if s >= 0:
                x, y = self.pos2xy(pos)
                if 0 <= x < self.h and 0 <= y < self.v:
                    self.g[y][x] = s
                    self.placed.add((x, y))
                pos += 1
            else:
                pos += -s

    def neighbors(self, r=2):
        seen = set()
        res = []
        for y in range(self.v):
            for x in range(self.h):
                if self.g[y][x] != E:
                    for dy in range(-r, r + 1):
                        for dx in range(-r, r + 1):
                            nx, ny = x + dx, y + dy
                            if (
                                0 <= nx < self.h
                                and 0 <= ny < self.v
                                and self.g[ny][nx] == E
                                and (nx, ny) not in seen
                            ):
                                seen.add((nx, ny))
                                res.append((nx, ny))
        return res


# ═══════════════════════════════════════════════════════════
#  HEURISTIC ENGINE - ĐÃ SỬA
# ═══════════════════════════════════════════════════════════

def cdir(b, x, y, dx, dy, sym):
    n = 0
    for i in range(1, 6):
        v = b.get(x + dx * i, y + dy * i)
        if v == sym:
            n += 1
        else:
            break
    return n


# SỬA 3: analyze() nhận diện đúng rìa bàn và luật VN
def analyze(b, x, y, sym):
    res = []
    for dx, dy in DIRS:
        fwd = cdir(b, x, y, dx, dy, sym)
        bwd = cdir(b, x, y, -dx, -dy, sym)
        total = 1 + fwd + bwd

        # Kiểm tra ô ngay sau chuỗi quân
        fex, fey = x + dx * (fwd + 1), y + dy * (fwd + 1)
        bex, bey = x - dx * (bwd + 1), y - dy * (bwd + 1)
        fe = b.get(fex, fey)
        be = b.get(bex, bey)

        # SỬA: Chỉ ô trống THỰC SỰ trong bàn (E) mới là "mở"
        # Ô ngoài bàn (OUT) = bị chặn bởi tường, KHÔNG phải mở
        fo = fe == E
        bo = be == E
        opens = int(fo) + int(bo)

        # SỬA 4: Theo luật Caro VN, 5 quân bị chặn 2 đầu KHÔNG thắng
        # Chỉ tính FIVE khi có ít nhất 1 đầu mở (opens >= 1)
        if total >= 5:
            if opens >= 1:
                res.append(("FIVE", opens))
            else:
                # 5 quân bị chặn 2 đầu - không thắng, cho điểm thấp như HALF4
                res.append(("BLOCKED5", 0))
        elif total == 4:
            if opens == 2:
                res.append(("OPEN4", 2))
            elif opens == 1:
                res.append(("HALF4", 1))
        elif total == 3:
            if opens == 2:
                res.append(("OPEN3", 2))
            elif opens == 1:
                res.append(("HALF3", 1))
        elif total == 2:
            if opens == 2:
                res.append(("OPEN2", 2))
            elif opens == 1:
                res.append(("HALF2", 1))
    return res


# SỬA 5: Bảng điểm - BLOCKED5 = 0 (không thắng)
SC = {
    "FIVE": 100_000_000,
    "OPEN4": 5_000_000,
    "HALF4": 500_000,
    "OPEN3": 100_000,
    "HALF3": 10_000,
    "OPEN2": 2_000,
    "HALF2": 200,
    "BLOCKED5": 0,  # 5 bị chặn 2 đầu = vô dụng theo luật VN
}


def score_pos(b, x, y, sym):
    b.put(x, y, sym)
    pats = analyze(b, x, y, sym)
    b.undo(x, y)
    base = sum(SC.get(p, 0) for p, _ in pats)
    names = [p for p, _ in pats]
    n4o = names.count("OPEN4")
    n4h = names.count("HALF4")
    n3o = names.count("OPEN3")
    n3h = names.count("HALF3")
    if n4o >= 2:
        base += 8_000_000
    if n4h >= 2:
        base += 1_000_000
    if n4h >= 1 and n3o >= 1:
        base += 2_000_000
    if n3o >= 2:
        base += 500_000
    if n4h >= 1 and n3h >= 1:
        base += 200_000
    return base


# SỬA 6: full_score() phạt nước đi rìa bàn mạnh hơn
def full_score(b, x, y, my):
    opp = X if my == O else O
    atk = score_pos(b, x, y, my)
    dfc = score_pos(b, x, y, opp)
    cx, cy = b.h // 2, b.v // 2

    # Điểm trung tâm: ưu tiên giữa bàn
    ctr = max(0, 20 - (abs(x - cx) + abs(y - cy)) * 2)

    # SỬA: Phạt nước đi sát rìa bàn (không tạo được OPEN4/OPEN3 thật sự)
    edge_penalty = 0
    if x == 0 or x == b.h - 1 or y == 0 or y == b.v - 1:
        # Rìa bàn: khó tạo OPEN4 vì 1 đầu bị tường chặn
        edge_penalty = -50_000
    if x < 2 or x >= b.h - 2 or y < 2 or y >= b.v - 2:
        # Gần rìa: phạt nhẹ
        edge_penalty += -5_000

    return int(atk) + int(dfc * 1.15) + ctr + edge_penalty


def find_pat(b, sym, target):
    for x, y in b.neighbors(r=3):
        b.put(x, y, sym)
        pats = analyze(b, x, y, sym)
        b.undo(x, y)
        if any(p == target for p, _ in pats):
            return (x, y)
    return None


def pick(b, my):
    opp = X if my == O else O
    mc = len(b.hist)
    if mc == 0:
        return b.h // 2, b.v // 2
    if mc == 1:
        lx, ly, _ = b.hist[-1]
        for dx, dy in [
            (1, 0),
            (-1, 0),
            (0, 1),
            (0, -1),
            (1, 1),
            (-1, -1),
            (1, -1),
            (-1, 1),
        ]:
            nx, ny = lx + dx, ly + dy
            if 0 <= nx < b.h and 0 <= ny < b.v and b.g[ny][nx] == E:
                return nx, ny

    # Ưu tiên: FIVE thật sự (mở ít nhất 1 đầu)
    m = find_pat(b, my, "FIVE")
    if m:
        log.info(f"[P1] WIN {m}")
        return m
    m = find_pat(b, opp, "FIVE")
    if m:
        log.info(f"[P2] BLOCK {m}")
        return m
    m = find_pat(b, my, "OPEN4")
    if m:
        log.info(f"[P3] OPEN4 {m}")
        return m
    m = find_pat(b, opp, "OPEN4")
    if m:
        log.info(f"[P4] BLK_O4 {m}")
        return m
    m = find_pat(b, my, "HALF4")
    if m:
        log.info(f"[P5] HALF4 {m}")
        return m
    m = find_pat(b, opp, "HALF4")
    if m:
        log.info(f"[P6] BLK_H4 {m}")
        return m

    cands = b.neighbors(r=2)
    if not cands:
        return b.h // 2, b.v // 2

    # SỬA 7: Lọc bỏ các nước đi rìa bàn tệ hại trừ khi bắt buộc
    good_cands = []
    for x, y in cands:
        # Kiểm tra nước đi này có tạo được pattern có ích không
        b.put(x, y, my)
        pats = analyze(b, x, y, my)
        b.undo(x, y)
        # Chỉ giữ lại nếu không phải toàn BLOCKED5 hoặc nước rìa vô dụng
        has_real_threat = any(p in ("FIVE", "OPEN4", "HALF4", "OPEN3", "HALF3") for p, _ in pats)
        if has_real_threat or not (x == 0 or x == b.h - 1 or y == 0 or y == b.v - 1):
            good_cands.append((x, y))

    if not good_cands:
        good_cands = cands  # Fallback

    best = good_cands[0]
    best_s = -1
    for x, y in good_cands:
        s = full_score(b, x, y, my)
        if s > best_s:
            best_s = s
            best = (x, y)
    log.info(f"[P7] {best} s={best_s} n={len(good_cands)}")
    return best


# ═══════════════════════════════════════════════════════════
#  WEBSOCKET BOT
# ═══════════════════════════════════════════════════════════


class Bot:
    def __init__(self):
        self.ws = None
        self.board = Board()
        self.slot = -1
        self.my = X
        self.opp = O
        self.playing = False
        self.in_table = False
        self.ready = False
        self.mode_ok = False
        self.players = {}
        self.nick = ""
        self.token = 0
        self.cookie = ""
        self.place = "Lobby.caro.0"
        self.lck = ""
        self.t0 = None
        self.last = time.time()
        self.running = True
        self.W = 0
        self.L = 0
        self.D = 0
        self.G = 0
        self.pending = False
        try:
            d = json.load(open("/tmp/caro.json"))
            self.W = d.get("W", 0)
            self.L = d.get("L", 0)
            self.D = d.get("D", 0)
        except:
            pass

    def save(self):
        try:
            json.dump(
                {"W": self.W, "L": self.L, "D": self.D},
                open("/tmp/caro.json", "w"),
            )
        except:
            pass

    def set_sym(self):
        self.my = X if self.slot == 0 else O
        self.opp = O if self.my == X else X
        log.info(f"slot={self.slot} me={'X' if self.my == X else 'O'}")

    def mk_login(self):
        w = W()
        w.cmd("LOGIN")
        w.asc(self.nick)
        w.i32(self.token)
        w.asc(VERSION)
        w.asc(self.lck)
        w.asc(GAME_ID)
        w.i8(1)
        return w.build()

    def mk_enter(self, path, pw="", mode=1):
        w = W()
        w.cmd("ENTER_PLACE")
        w.asc(path)
        w.utf(pw)
        w.i8(mode)
        return w.build()

    def mk_mode(self):
        w = W()
        w.cmd("SET_CLIENT_MODE")
        w.i8(1)
        return w.build()

    def mk_tbl(self):
        w = W()
        w.cmd("GET_TABLE_DATA_EX")
        w.asc("")
        return w.build()

    def mk_play(self, pos):
        w = W()
        w.cmd("PLAY")
        w.i16(pos)
        return w.build()

    def mk_pong(self):
        w = W()
        w.cmd("PONG")
        return w.build()

    def mk_qplay(self):
        w = W()
        w.cmd("QUICK_PLAY")
        w.asc("")
        w.i8(-1)
        return w.build()

    def mk_ready(self):
        w = W()
        w.cmd("SET_READY")
        return w.build()

    async def tx(self, d):
        if self.ws:
            try:
                await self.ws.send(d)
            except:
                pass

    async def move(self):
        if not self.playing:
            return
        self.pending = False
        t0 = time.time()
        x, y = pick(self.board, self.my)
        pos = self.board.xy2pos(x, y)
        log.info(f"DANH ({x},{y}) {time.time()-t0:.3f}s")
        await self.tx(self.mk_play(pos))
        self.board.put(x, y, self.my)

    async def handle(self, raw):
        r = R(raw)
        c = r.cmd()
        if c != "PING":
            log.info(f"{c} rem={r.rem()}")
        self.last = time.time()
        try:
            if c == "PING":
                await self.tx(self.mk_pong())
            elif c == "LOGIN":
                await self._login(r)
            elif c == "ENTER_PLACE":
                await self._enter(r)
            elif c == "GET_TABLE_DATA_EX":
                await self._table(r)
            elif c == "QUICK_PLAY":
                await self._qplay(r)
            elif c == "START_MATCH":
                await self._start(r)
            elif c == "SET_TURN":
                await self._turn(r)
            elif c == "MOVE":
                await self._move(r)
            elif c == "GAMEOVER":
                await self._over(r)
            elif c == "PLAY":
                st = r.i8()
                if st != 0:
                    em = r.utf() if r.rem() > 0 else ""
                    log.warning(f"PLAY err {st}:{em}")
                    if self.playing and self.pending:
                        await asyncio.sleep(0.3)
                        await self.move()
            elif c == "PLAYER_ENTERED":
                await self._penter(r)
            elif c == "PLAYER_EXITED":
                sid = r.i8()
                self.players.pop(sid, None)
                if sid == self.slot:
                    self.in_table = False
                    self.playing = False
        except Exception as e:
            log.error(f"ERR {c}:{e}", exc_info=True)

    async def _login(self, r):
        st = r.i8()
        if st == 0:
            path = r.utf()
            if path == "REFRESH":
                await self.tx(self.mk_enter(self.place))
                return
            if r.rem() > 0:
                self.lck = r.asc()
            if r.rem() > 0:
                r.utf()
            if r.rem() > 0:
                r.asc()
            await self.tx(self.mk_enter(self.place))
        else:
            em = r.utf() if r.rem() > 0 else ""
            log.error(f"LOGIN FAIL:{em}")

    async def _enter(self, r):
        if not self.mode_ok:
            self.mode_ok = True
            await self.tx(self.mk_mode())
        await self.tx(self.mk_tbl())

    async def _qplay(self, r):
        st = r.i8()
        if st != 0:
            em = r.utf() if r.rem() > 0 else ""
            if "notinzone" in em.lower() and self.in_table:
                if not self.ready:
                    self.ready = True
                    await self.tx(self.mk_ready())
                return
            await asyncio.sleep(5)
            await self.tx(self.mk_qplay())
            return
        path = r.asc()
        r.utf()
        if r.rem() > 0:
            n = r.u8()
            for _ in range(n):
                r.asc()
                r.utf()
        if path:
            self.in_table = True
            await self.tx(self.mk_enter(path))
            await asyncio.sleep(0.5)
            await self.tx(self.mk_mode())
            await asyncio.sleep(0.3)
            await self.tx(self.mk_tbl())

    async def _table(self, r):
        try:
            fb = r.i8()
            if fb != 0:
                em = r.utf() if r.rem() > 0 else ""
                if "not in table" in em.lower():
                    await self.tx(self.mk_qplay())
                    return
            sc = r.u8()
            for _ in range(sc):
                r.u8()
                r.asc()
                r.u8()
            nc = r.u8()
            for _ in range(nc):
                r.u8()
                r.asc()
                r.utf()
                r.u8()
                r.u8()
            r.u8()
            self.slot = r.i8()
            playing = r.u8() == 1
            cur = r.i8()
            pc = r.u8()
            self.players = {}
            for _ in range(pc):
                sid = r.i8()
                r.i64()
                fn = r.utf()
                r.u16()
                r.asc()
                r.i8()
                r.i64()
                r.i64()
                r.i64()
                r.u8()
                r.u8()
                self.players[sid] = {"name": fn}
                log.info(f"slot {sid}:{fn}")
            mpc = r.u8()
            for _ in range(mpc):
                r.i8()
                r.i32()
            h = r.u8()
            v = r.u8()
            self.board.resize(h, v)
            r.i16()
            bd = r.arr()
            self.board.load_rle(bd)
            self.set_sym()
            r.u8()
            r.u8()
            n = r.u8()
            for _ in range(n):
                r.asc()
                r.utf()
            self.playing = playing
            if playing and cur == self.slot:
                self.pending = True
                await self.move()
            elif not playing:
                if not self.ready:
                    self.ready = True
                    await self.tx(self.mk_ready())
        except Exception as e:
            log.error(f"Table: {e}", exc_info=True)

    async def _start(self, r):
        self.G += 1
        self.playing = True
        self.ready = False
        pc = r.u8()
        for _ in range(pc):
            r.i8()
            r.i32()
        h = r.u8()
        v = r.u8()
        self.board.resize(h, v)
        r.i16()
        bd = r.arr()
        self.board.load_rle(bd)
        self.set_sym()
        log.info(f"===VAN {self.G}=== me={'X' if self.my == X else 'O'}")

    async def _turn(self, r):
        sid = r.i8()
        r.i16()
        r.i16()
        mine = sid == self.slot
        log.info(f"TURN slot={sid} mine={mine}")
        if mine and self.playing:
            self.pending = True
            await asyncio.sleep(0.15)
            await self.move()

    async def _move(self, r):
        pos = r.i16()
        sym = r.i8()
        x, y = self.board.pos2xy(pos)
        cur = self.board.get(x, y)
        sc = "X" if sym == X else "O"
        if cur == sym:
            log.info(f"[ok] ({x},{y}) {sc}")
        elif cur != E and cur != sym:
            log.warning(f"[sym fix] swap")
            self.my = sym
            self.opp = X if sym == O else O
            self.board.undo(x, y)
            self.board.put(x, y, sym)
        else:
            log.info(f"[opp] ({x},{y}) {sc}")
            self.board.put(x, y, sym)

    async def _over(self, r):
        self.playing = False
        self.pending = False
        pc = r.u8()
        mg = None
        for _ in range(pc):
            sid = r.i8()
            g = r.i8()
            earn = r.i64()
            if sid == self.slot:
                mg = g
            gs = {1: "WIN", 2: "LOSE", 3: "DRAW", 4: "LOSE", 10: "DRAW", 11: "WIN", 12: "LOSE"}.get(
                g, str(g)
            )
            log.info(f"  slot {sid}: {gs} earn={earn}")
        if mg in (1, 11):
            self.W += 1
            log.info("THANG!")
        elif mg in (2, 4, 12):
            self.L += 1
            log.info("THUA!")
        else:
            self.D += 1
            log.info("HOA!")
        r.utf()
        wr = self.W / self.G * 100 if self.G else 0
        mins = (time.time() - self.t0) / 60 if self.t0 else 0
        log.info(f"=> {self.G}G {self.W}W {self.L}L {self.D}D WR={wr:.0f}% {mins:.0f}m")
        self.save()
        await asyncio.sleep(2)
        if self.in_table:
            await self.tx(self.mk_ready())
            self.ready = True
        else:
            await self.tx(self.mk_qplay())

    async def _penter(self, r):
        sid = r.i8()
        r.i64()
        fn = r.utf()
        r.u16()
        r.asc()
        r.i8()
        r.i64()
        r.i64()
        r.i64()
        r.u8()
        r.u8()
        self.players[sid] = {"name": fn}
        log.info(f"Enter slot {sid}:{fn}")

    async def watchdog(self):
        while self.running:
            await asyncio.sleep(10)
            if not (self.ws and self.ws.close_code is None):
                continue
            try:
                if self.t0 and time.time() - self.t0 > RUNTIME:
                    wr = self.W / self.G * 100 if self.G else 0
                    log.info(f"===HET GIO === {self.G}G WR={wr:.0f}%")
                    self.running = False
                    self.save()
                    await self.ws.close()
                    return
                if (
                    not self.playing
                    and self.in_table
                    and time.time() - self.last > 45
                ):
                    log.info("Idle -> tim ban moi")
                    self.in_table = False
                    self.ready = False
                    self.last = time.time()
                    await self.tx(self.mk_enter("Lobby.caro.0"))
                    await asyncio.sleep(1)
                    await self.tx(self.mk_qplay())
                if (
                    self.playing
                    and self.pending
                    and time.time() - self.last > 50
                ):
                    log.warning("Stuck -> force move")
                    await self.move()
            except:
                pass

    def login_http(self):
        try:
            s = requests.Session()
            ua = "Mozilla/5.0"
            s.get(
                "https://gamevh.net/login.jsp",
                timeout=10,
                headers={"User-Agent": ua},
            )
            r = s.post(
                "https://gamevh.net/login.jsp",
                timeout=10,
                data={
                    "redirect": "/",
                    "USER_NAME": USER,
                    "PASSWORD": PASSWD,
                    "AUTO_LOGIN": "on",
                    "LOGIN": "Dang nhap",
                },
                headers={
                    "User-Agent": ua,
                    "Referer": "https://gamevh.net/login.jsp",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
            if "login.jsp" in r.url:
                log.error("Login fail")
                return False
            self.cookie = ";".join(f"{k}={v}" for k, v in s.cookies.items())
            r2 = s.get("https://gamevh.net/", timeout=10, headers={"User-Agent": ua})
            m = re.search(r'"token":(\d+)', r2.text)
            if not m:
                return False
            self.token = int(m.group(1))
            m = re.search(r'"nick":"([^"]+)"', r2.text)
            if not m:
                return False
            self.nick = m.group(1)
            log.info(f"Login OK: {self.nick}")
            return True
        except Exception as e:
            log.error(f"HTTP: {e}")
            return False

    async def connect(self):
        try:
            self.ws = await websockets.connect(
                WS_URL,
                additional_headers={
                    "Cookie": self.cookie,
                    "Origin": "https://gamevh.net",
                    "User-Agent": "Mozilla/5.0",
                },
                max_size=2**20,
                ping_interval=None,
            )
            return True
        except Exception as e:
            log.error(f"Connect: {e}")
            return False

    async def run_ws(self):
        if not await self.connect():
            return
        await self.tx(self.mk_login())
        asyncio.create_task(self.watchdog())
        try:
            async for raw in self.ws:
                if isinstance(raw, bytes):
                    await self.handle(raw)
        except websockets.exceptions.ConnectionClosed as e:
            log.warning(f"Closed: {e}")
        except Exception as e:
            log.error(f"WS: {e}")
        finally:
            self.running = False
            self.save()

    async def run(self):
        self.t0 = time.time()
        log.info(f"Bot start - {RUNTIME//3600}h")
        retry = 0
        while True:
            elapsed = time.time() - self.t0
            if elapsed > RUNTIME:
                wr = self.W / self.G * 100 if self.G else 0
                log.info(f"===HET {RUNTIME//3600}H === WR={wr:.0f}%")
                break
            self.playing = False
            self.pending = False
            self.ready = False
            self.mode_ok = False
            self.board = Board()
            login_ok = False
            for attempt in range(5):
                if self.login_http():
                    login_ok = True
                    break
                log.warning(f"Login fail lan {attempt+1}/5, thu lai sau 5s")
                await asyncio.sleep(5)
            if not login_ok:
                log.error("Login that bai 5 lan lien tiep, doi 60s")
                await asyncio.sleep(60)
                retry += 1
                continue
            await self.run_ws()
            if not self.running:
                break
            retry += 1
            wait = min(3 * retry, 30)
            remaining = (RUNTIME - (time.time() - self.t0)) / 60
            log.info(f"Reconnect lan {retry} sau {wait}s... (con {remaining:.0f} phut)")
            await asyncio.sleep(wait)
        self.save()
        wr = self.W / self.G * 100 if self.G else 0
        log.info(f"Bot ket thuc. {self.G}G {self.W}W {self.L}L {self.D}D WR={wr:.0f}%")


if __name__ == "__main__":
    asyncio.run(Bot().run())
