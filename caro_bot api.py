#!/usr/bin/env python3
"""
Caro Bot gamevh.net - ALL-IN-ONE
- AI tính nước đi tích hợp sẵn (không cần API riêng)
- Chỉ cần chạy 1 file này
- Tự reconnect, keep-alive, chạy 60 phút
"""

import asyncio
import struct
import time
import logging
import sys
import re
import traceback

try:
    import websockets
except ImportError:
    print("Cài websockets: pip install websockets")
    sys.exit(1)

try:
    import requests
except ImportError:
    print("Cài requests: pip install requests")
    sys.exit(1)

# ═══════════════════════════════════════════════════════════════
# CẤU HÌNH
# ═══════════════════════════════════════════════════════════════
WS_URL = "wss://gamevh.net/ws/gameServer"
GAME_URL = "https://gamevh.net/play/caro/0"

USERNAME = "nguyen05511"
PASSWORD = "nhat123456"

TOKEN = 0
PLACE_PATH = "Lobby.caro.0"
VERSION = "5.0.2"
GAME_ID = "caro"

HCOUNT = 15
VCOUNT = 19

# ─── Thời gian & reconnect ──────────────────────────────────
RUN_DURATION_SEC = 60 * 60      # 60 phút
RECONNECT_MAX_RETRIES = 200
RECONNECT_BASE_WAIT = 3
RECONNECT_MAX_WAIT = 60
KEEPALIVE_INTERVAL = 25
QUICK_PLAY_ENABLED = True
QUICK_PLAY_MAX_ATTEMPTS = 3
QUICK_PLAY_RETRY_DELAY = 5

# ═══════════════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    force=True,
)
log = logging.getLogger("caro_bot")

_fh = logging.FileHandler("/home/z/my-project/caro_bot.log", mode="a")
_fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"))
log.addHandler(_fh)

sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

# ═══════════════════════════════════════════════════════════════
# PROTOCOL
# ═══════════════════════════════════════════════════════════════
CMD_NAMES = {
    300: "PONG", 301: "PING", 302: "LOGIN", 303: "ALERT",
    304: "RIBBON_MESSAGE", 311: "BROADCAST", 312: "INVITE",
    314: "SET_CLIENT_MODE", 315: "CONFIG",
    401: "ENTER_PLACE", 402: "ENTER_CHILD_PLACE",
    406: "PLAYER_ENTERED", 407: "PLAYER_EXITED",
    408: "QUICK_PLAY", 414: "GET_TABLE_DATA",
    417: "START_MATCH", 418: "GAMEOVER", 419: "ENTER_STATE",
    420: "SET_TURN", 421: "SET_PLAYER_STATUS",
    422: "SET_PLAYER_POINT", 423: "SET_PLAYER_ATTR",
    431: "BALANCE_CHANGED", 432: "OWNER_CHANGED",
    433: "GET_TABLE_DATA_EX", 434: "SET_READY",
    501: "BET", 502: "PLAY", 518: "HIGHLIGHT",
    529: "MOVE", 533: "ASK_DRAW", 534: "SURRENDER",
    535: "RETREAT",
}

class ConnReader:
    def __init__(self, buf: bytes):
        self.buf = buf
        self.offset = 0
    def remaining(self) -> int:
        return len(self.buf) - self.offset
    def read_byte(self) -> int:
        val = struct.unpack_from('>b', self.buf, self.offset)[0]; self.offset += 1; return val
    def read_ubyte(self) -> int:
        val = struct.unpack_from('>B', self.buf, self.offset)[0]; self.offset += 1; return val
    def read_short(self) -> int:
        val = struct.unpack_from('>h', self.buf, self.offset)[0]; self.offset += 2; return val
    def read_ushort(self) -> int:
        val = struct.unpack_from('>H', self.buf, self.offset)[0]; self.offset += 2; return val
    def read_int(self) -> int:
        val = struct.unpack_from('>i', self.buf, self.offset)[0]; self.offset += 4; return val
    def read_long(self) -> int:
        hi = struct.unpack_from('>i', self.buf, self.offset)[0]
        lo = struct.unpack_from('>I', self.buf, self.offset + 4)[0]
        self.offset += 8
        return hi * (1 << 32) + lo
    def read_ascii(self) -> str:
        length = self.read_ubyte()
        data = self.buf[self.offset:self.offset + length]
        self.offset += length
        return data.decode('ascii', errors='replace')
    def read_string(self) -> str:
        char_count = self.read_short()
        if char_count <= 0: return ""
        data = self.buf[self.offset:self.offset + char_count * 2]
        self.offset += char_count * 2
        return data.decode('utf-16-be', errors='replace')
    def read_byte_array(self) -> list:
        length = self.read_short()
        data = list(self.buf[self.offset:self.offset + length])
        self.offset += length
        return data
    def read_command(self) -> str:
        first = self.read_byte()
        if first < 0:
            name_len = -first
            name = self.buf[self.offset:self.offset + name_len].decode('ascii', errors='replace')
            self.offset += name_len
            return name
        else:
            second = self.read_ubyte()
            cmd_id = (first << 8) | second
            return CMD_NAMES.get(cmd_id, f"CMD_{cmd_id}")

class ConnWriter:
    def __init__(self):
        self.parts = []
    def write_byte(self, val: int): self.parts.append(struct.pack('>b', val))
    def write_ubyte(self, val: int): self.parts.append(struct.pack('>B', val))
    def write_short(self, val: int): self.parts.append(struct.pack('>h', val))
    def write_ushort(self, val: int): self.parts.append(struct.pack('>H', val))
    def write_int(self, val: int): self.parts.append(struct.pack('>i', val))
    def write_long(self, val: int):
        hi = val >> 32; lo = val & 0xFFFFFFFF
        self.parts.append(struct.pack('>iI', hi, lo))
    def write_ascii(self, s: str):
        encoded = s.encode('ascii', errors='replace')
        self.parts.append(struct.pack('>B', len(encoded))); self.parts.append(encoded)
    def write_string(self, s: str):
        encoded = s.encode('utf-16-be')
        char_count = len(encoded) // 2
        self.parts.append(struct.pack('>h', char_count)); self.parts.append(encoded)
    def write_command(self, cmd: str):
        cmd_id = None
        for cid, cname in CMD_NAMES.items():
            if cname == cmd: cmd_id = cid; break
        if cmd_id is not None:
            self.parts.append(struct.pack('>H', cmd_id))
        else:
            name_bytes = cmd.encode('ascii')
            self.parts.append(struct.pack('>b', -len(name_bytes))); self.parts.append(name_bytes)
    def to_bytes(self) -> bytes: return b''.join(self.parts)

# ═══════════════════════════════════════════════════════════════
# CARO AI - TÍCH HỢP SẴN (Heuristic, không OOM)
# ═══════════════════════════════════════════════════════════════
EMPTY = -1
SYMBOL_O = 0
SYMBOL_X = 1

class CaroBoard:
    def __init__(self, hcount=HCOUNT, vcount=VCOUNT, board=None):
        self.hcount = hcount
        self.vcount = vcount
        if board:
            self.board = [row[:] for row in board]
        else:
            self.board = [[EMPTY] * hcount for _ in range(vcount)]
        self.my_symbol = SYMBOL_X
        self.opp_symbol = SYMBOL_O
        self.move_history = []

    def clear(self):
        self.board = [[EMPTY] * self.hcount for _ in range(self.vcount)]
        self.move_history = []

    def resize(self, hcount, vcount):
        self.hcount = hcount
        self.vcount = vcount
        self.clear()

    def get(self, x: int, y: int) -> int:
        if 0 <= x < self.hcount and 0 <= y < self.vcount:
            return self.board[y][x]
        return EMPTY

    def place(self, x: int, y: int, symbol: int):
        if 0 <= x < self.hcount and 0 <= y < self.vcount:
            self.board[y][x] = symbol
            self.move_history.append((x, y, symbol))

    def unplace(self, x: int, y: int):
        if 0 <= x < self.hcount and 0 <= y < self.vcount:
            self.board[y][x] = EMPTY
            if self.move_history and self.move_history[-1][:2] == (x, y):
                self.move_history.pop()

    def get_neighbors(self, radius=2):
        visited = set()
        result = []
        has_piece = False
        for y in range(self.vcount):
            for x in range(self.hcount):
                if self.board[y][x] != EMPTY:
                    has_piece = True
                    for dy in range(-radius, radius + 1):
                        for dx in range(-radius, radius + 1):
                            nx, ny = x + dx, y + dy
                            if (0 <= nx < self.hcount and 0 <= ny < self.vcount
                                    and self.board[ny][nx] == EMPTY
                                    and (nx, ny) not in visited):
                                visited.add((nx, ny))
                                result.append((nx, ny))
        if not has_piece:
            return [(self.hcount // 2, self.vcount // 2)]
        return result

    def pos_to_xy(self, pos: int):
        y = pos // self.hcount
        x = pos % self.hcount
        return x, y

    def xy_to_pos(self, x: int, y: int) -> int:
        return y * self.hcount + x

    def fill_from_rle(self, board_data: list):
        self.clear()
        pos = 0
        for unsigned_val in board_data:
            signed_val = unsigned_val - 256 if unsigned_val > 127 else unsigned_val
            if signed_val >= 0:
                y = pos // self.hcount
                x = pos % self.hcount
                if 0 <= x < self.hcount and 0 <= y < self.vcount:
                    self.board[y][x] = signed_val
                pos += 1
            else:
                pos += (-signed_val)

    def to_matrix(self):
        return [[self.board[y][x] for x in range(self.hcount)] for y in range(self.vcount)]

    def display(self) -> str:
        lines = []
        sym = {EMPTY: '.', SYMBOL_O: 'O', SYMBOL_X: 'X'}
        header = " " + "".join(f"{i:2d}" for i in range(self.hcount))
        lines.append(header)
        for y in range(self.vcount):
            row = f"{y:2d} " + "".join(f" {sym.get(self.board[y][x], '?')}" for x in range(self.hcount))
            lines.append(row)
        return "\n".join(lines)


class CaroAI:
    """AI Caro Việt Nam - Heuristic 1-ply, không OOM"""

    SCORES = {
        'FIVE': 10000000,
        'OPEN_FOUR': 5000000,
        'HALF_FOUR': 500000,
        'OPEN_THREE': 200000,
        'HALF_THREE': 50000,
        'OPEN_TWO': 20000,
        'HALF_TWO': 5000,
    }

    @staticmethod
    def check_win_at(board: CaroBoard, x: int, y: int, symbol: int) -> bool:
        """Kiểm tra thắng tại (x,y) - luật VN: đúng 5, bị chặn 2 đầu không thắng"""
        dirs = [(1, 0), (0, 1), (1, 1), (1, -1)]
        for dx, dy in dirs:
            cnt = 1
            nx, ny = x + dx, y + dy
            while 0 <= nx < board.hcount and 0 <= ny < board.vcount and board.get(nx, ny) == symbol:
                cnt += 1; nx += dx; ny += dy
            blocked1 = not (0 <= nx < board.hcount and 0 <= ny < board.vcount and board.get(nx, ny) == EMPTY)
            nx, ny = x - dx, y - dy
            while 0 <= nx < board.hcount and 0 <= ny < board.vcount and board.get(nx, ny) == symbol:
                cnt += 1; nx -= dx; ny -= dy
            blocked2 = not (0 <= nx < board.hcount and 0 <= ny < board.vcount and board.get(nx, ny) == EMPTY)
            if cnt == 5 and not (blocked1 and blocked2):
                return True
        return False

    @staticmethod
    def analyze_line(board: CaroBoard, x: int, y: int, dx: int, dy: int, symbol: int):
        """Đếm số quân liên tiếp và số đầu mở"""
        cnt = 1; open_ends = 0
        nx, ny = x + dx, y + dy
        while 0 <= nx < board.hcount and 0 <= ny < board.vcount and board.get(nx, ny) == symbol:
            cnt += 1; nx += dx; ny += dy
        if 0 <= nx < board.hcount and 0 <= ny < board.vcount and board.get(nx, ny) == EMPTY:
            open_ends += 1
        nx, ny = x - dx, y - dy
        while 0 <= nx < board.hcount and 0 <= ny < board.vcount and board.get(nx, ny) == symbol:
            cnt += 1; nx -= dx; ny -= dy
        if 0 <= nx < board.hcount and 0 <= ny < board.vcount and board.get(nx, ny) == EMPTY:
            open_ends += 1
        return cnt, open_ends

    def evaluate_point(self, board: CaroBoard, x: int, y: int, symbol: int) -> int:
        """Chấm điểm 1 vị trí cho 1 symbol"""
        total = 0
        threat_half_four = 0
        threat_open_three = 0
        for dx, dy in [(1, 0), (0, 1), (1, 1), (1, -1)]:
            cnt, open_ends = self.analyze_line(board, x, y, dx, dy, symbol)
            if cnt >= 5 and open_ends > 0:
                total += self.SCORES['FIVE']
            elif cnt == 4:
                if open_ends == 2:
                    total += self.SCORES['OPEN_FOUR']; threat_half_four += 1
                elif open_ends == 1:
                    total += self.SCORES['HALF_FOUR']; threat_half_four += 1
            elif cnt == 3:
                if open_ends == 2:
                    total += self.SCORES['OPEN_THREE']; threat_open_three += 1
                elif open_ends == 1:
                    total += self.SCORES['HALF_THREE']
            elif cnt == 2:
                if open_ends == 2:
                    total += self.SCORES['OPEN_TWO']
                elif open_ends == 1:
                    total += self.SCORES['HALF_TWO']
        # Double threat bonus
        if threat_half_four >= 2: total += 1000000
        if threat_half_four >= 1 and threat_open_three >= 1: total += 500000
        if threat_open_three >= 2: total += 300000
        return total

    def find_best_move(self, board: CaroBoard, my_sym: int, opp_sym: int):
        """Tìm nước đi tốt nhất - gọi trực tiếp, không cần HTTP"""
        candidates = board.get_neighbors()
        if not candidates:
            return (board.hcount // 2, board.vcount // 2), 'center'

        # 1. Thắng ngay
        for x, y in candidates:
            board.place(x, y, my_sym)
            if self.check_win_at(board, x, y, my_sym):
                board.unplace(x, y)
                return (x, y), 'win_now'
            board.unplace(x, y)

        # 2. Chặn thắng đối thủ
        for x, y in candidates:
            board.place(x, y, opp_sym)
            if self.check_win_at(board, x, y, opp_sym):
                board.unplace(x, y)
                return (x, y), 'block_win'
            board.unplace(x, y)

        # 3. Heuristic scoring
        scored = []
        cx, cy = board.hcount // 2, board.vcount // 2
        for x, y in candidates:
            score = 0
            board.place(x, y, my_sym)
            score += self.evaluate_point(board, x, y, my_sym)
            board.unplace(x, y)
            board.place(x, y, opp_sym)
            score += self.evaluate_point(board, x, y, opp_sym) * 0.9
            board.unplace(x, y)
            dist = abs(x - cx) + abs(y - cy)
            score += max(0, 20 - dist * 2)
            scored.append((score, x, y))

        scored.sort(reverse=True)
        _, x, y = scored[0]
        return (x, y), 'heuristic'


# ═══════════════════════════════════════════════════════════════
# CARO BOT - KẾT NỐI WEBSOCKET
# ═══════════════════════════════════════════════════════════════
class CaroBot:
    def __init__(self):
        self.ws = None
        self.board = CaroBoard()
        self.ai = CaroAI()
        self.my_slot_id = -1
        self.is_my_turn = False
        self.is_playing = False
        self.my_symbol = SYMBOL_X
        self.opp_symbol = SYMBOL_O
        self.players = {}
        self.login_cookie = ""
        self.game_count = 0
        self.running = True
        self.in_table = False
        self.ready_sent = False
        self.mode_set = False
        self.nickname = ""
        self.token = 0
        self.cookie_header = ""
        self.place_path = PLACE_PATH
        self.session = None
        self.current_table_path = ""
        # Keep-alive & reconnect
        self.start_time = time.time()
        self.last_msg_time = time.time()
        self.quick_play_attempts = 0
        self.keepalive_task = None

    # ─── Đăng nhập HTTP ───────────────────────────────────────
    def login_and_handshake(self) -> bool:
        log.info(f"🔐 Đăng nhập {USERNAME}...")
        try:
            self.session = requests.Session()
            ua = {"User-Agent": "Mozilla/5.0"}
            self.session.get(GAME_URL, timeout=10, headers=ua)
            self.session.get("https://gamevh.net/login.jsp", timeout=10, headers=ua)
            r = self.session.post("https://gamevh.net:443/login.jsp", data={
                "USER_NAME": USERNAME, "PASSWORD": PASSWORD,
                "redirect": "/", "AUTO_LOGIN": "true", "LOGIN": "Đăng nhập",
            }, timeout=10, headers={
                "User-Agent": "Mozilla/5.0",
                "Origin": "https://gamevh.net",
                "Referer": "https://gamevh.net/login.jsp",
                "Content-Type": "application/x-www-form-urlencoded",
            }, allow_redirects=True)
            cookies = self.session.cookies.get_dict()
            if 'memberName' not in cookies or 'memberPassword' not in cookies:
                log.error("❌ Thiếu cookie xác thực!")
                return False
            r = self.session.get(GAME_URL, timeout=10, headers=ua)
            self.cookie_header = '; '.join(f'{k}={v}' for k, v in cookies.items())
            html = r.text
            for _ in range(5):
                m = re.search(r'var\s+token\s*=\s*(\d+)', html)
                if m:
                    self.token = int(m.group(1))
                    break
                time.sleep(2)
                r = self.session.get(GAME_URL, timeout=10)
                html = r.text
            m = re.search(r"var\s+currentPlayerNickName\s*=\s*'([^']+)'", html)
            if m: self.nickname = m.group(1)
            m = re.search(r'var\s+placePath\s*=\s*"([^"]+)"', html)
            if m: self.place_path = m.group(1)
            log.info(f"✅ Login OK! nickname={self.nickname}")
            return True
        except Exception as e:
            log.error(f"Lỗi đăng nhập: {e}")
            return False

    # ─── WebSocket ─────────────────────────────────────────────
    async def connect(self):
        self.ws = await websockets.connect(
            WS_URL,
            additional_headers={
                "Cookie": self.cookie_header,
                "Origin": "https://gamevh.net",
                "User-Agent": "Mozilla/5.0",
            },
            max_size=2**20, ping_interval=None, close_timeout=5,
        )
        log.info("✅ WebSocket kết nối!")
        self.last_msg_time = time.time()

    async def send(self, data: bytes):
        if self.ws:
            await self.ws.send(data)

    # ─── Keep-alive ────────────────────────────────────────────
    async def keepalive_loop(self):
        while self.running:
            await asyncio.sleep(KEEPALIVE_INTERVAL)
            if not self.running: break
            idle = time.time() - self.last_msg_time
            if idle > 90:
                log.warning(f"⚠️ Idle {idle:.0f}s -> reconnect")
                self.running = False
                break
            if self.ws and self.ws.open:
                try:
                    await self.send(self.build_pong_msg())
                except Exception:
                    self.running = False
                    break

    def should_stop(self) -> bool:
        if time.time() - self.start_time >= RUN_DURATION_SEC:
            log.info(f"⏰ Đã chạy {RUN_DURATION_SEC/60:.0f} phút -> DỪNG")
            return True
        return False

    # ─── Build messages ────────────────────────────────────────
    def build_login_msg(self) -> bytes:
        w = ConnWriter()
        w.write_command("LOGIN")
        w.write_ascii(self.nickname)
        w.write_int(self.token)
        w.write_ascii(VERSION)
        w.write_ascii(self.login_cookie)
        w.write_ascii(GAME_ID)
        w.write_byte(1)
        return w.to_bytes()

    def build_enter_place_msg(self, path: str, password: str = "", mode: int = 1) -> bytes:
        w = ConnWriter()
        w.write_command("ENTER_PLACE")
        w.write_ascii(path)
        w.write_string(password)
        w.write_byte(mode)
        return w.to_bytes()

    def build_set_client_mode_msg(self, mode: int = 1) -> bytes:
        w = ConnWriter()
        w.write_command("SET_CLIENT_MODE")
        w.write_byte(mode)
        return w.to_bytes()

    def build_get_table_data_ex_msg(self) -> bytes:
        w = ConnWriter()
        w.write_command("GET_TABLE_DATA_EX")
        w.write_ascii("")
        return w.to_bytes()

    def build_play_msg(self, pos: int) -> bytes:
        w = ConnWriter()
        w.write_command("PLAY")
        w.write_short(pos)
        return w.to_bytes()

    def build_pong_msg(self) -> bytes:
        w = ConnWriter()
        w.write_command("PONG")
        return w.to_bytes()

    def build_quick_play_msg(self) -> bytes:
        w = ConnWriter()
        w.write_command("QUICK_PLAY")
        w.write_ascii("")
        w.write_byte(-1)
        return w.to_bytes()

    def build_set_ready_msg(self) -> bytes:
        w = ConnWriter()
        w.write_command("SET_READY")
        return w.to_bytes()

    # ─── Handle messages ───────────────────────────────────────
    async def handle_message(self, raw: bytes):
        self.last_msg_time = time.time()
        r = ConnReader(raw)
        cmd = r.read_command()
        log.info(f"📩 {cmd}")
        try:
            handler = getattr(self, f"handle_{cmd.lower()}", None)
            if handler:
                await handler(r)
        except Exception as e:
            log.error(f"Lỗi xử lý {cmd}: {e}")
            traceback.print_exc()

    async def handle_ping(self, r: ConnReader):
        await self.send(self.build_pong_msg())

    async def handle_login(self, r: ConnReader):
        status = r.read_byte()
        if status == 0:
            path = r.read_string()
            if path == "REFRESH":
                await self.send(self.build_enter_place_msg(self.place_path, "", 1))
                return
            if r.remaining() > 0:
                self.login_cookie = r.read_ascii()
            log.info("✅ LOGIN OK")
            await self.send(self.build_enter_place_msg(self.place_path, "", 1))

    async def handle_quick_play(self, r: ConnReader):
        status = r.read_byte()
        if status != 0:
            if self.quick_play_attempts < QUICK_PLAY_MAX_ATTEMPTS:
                self.quick_play_attempts += 1
                log.info(f"🔄 Quick play thất bại, thử lại ({self.quick_play_attempts}/{QUICK_PLAY_MAX_ATTEMPTS})...")
                await asyncio.sleep(QUICK_PLAY_RETRY_DELAY)
                await self.send(self.build_quick_play_msg())
            else:
                log.info("⏸️ Hết lượt quick play, chờ đối thủ...")
            return
        table_path = r.read_ascii()
        table_name = r.read_string()
        if r.remaining() > 0:
            arg_count = r.read_ubyte()
            for _ in range(arg_count):
                key = r.read_ascii()
                val = r.read_string()
        if table_path:
            self.current_table_path = table_path
            self.in_table = True
            self.ready_sent = False
            self.mode_set = False
            self.quick_play_attempts = 0
            log.info(f"🏠 Quick play OK! Bàn: {table_path}")
            await self.send(self.build_enter_place_msg(table_path, "", 1))

    async def handle_enter_place(self, r: ConnReader):
        currency = r.read_byte()
        rate = r.read_ushort()
        await asyncio.sleep(0.3)
        await self.send(self.build_set_client_mode_msg(1))
        self.mode_set = True
        await asyncio.sleep(0.3)
        await self.send(self.build_get_table_data_ex_msg())

    async def handle_get_table_data_ex(self, r: ConnReader):
        first_byte = r.read_byte()
        if first_byte != 0:
            if not self.in_table and QUICK_PLAY_ENABLED and self.quick_play_attempts < QUICK_PLAY_MAX_ATTEMPTS:
                self.quick_play_attempts += 1
                log.info(f"🔄 Quick play ({self.quick_play_attempts}/{QUICK_PLAY_MAX_ATTEMPTS})...")
                await asyncio.sleep(1)
                await self.send(self.build_quick_play_msg())
            elif not self.in_table:
                log.info("⏸️ Hết lượt quick play, chờ...")
            return
        state_count = r.read_ubyte()
        for _ in range(state_count):
            state_id = r.read_ubyte()
            state_code = r.read_ascii()
            mode = r.read_ubyte()
            cmd_count = r.read_ubyte()
            for _ in range(cmd_count):
                position = r.read_ubyte()
                code = r.read_ascii()
                name = r.read_string()
                fill_board = r.read_ubyte()
                take_confirm = r.read_ubyte()
        begin_state_id = r.read_ubyte()
        self.my_slot_id = r.read_byte()
        is_playing = r.read_ubyte()
        self.is_playing = is_playing == 1
        log.info(f"TABLE_DATA: slot={self.my_slot_id} playing={self.is_playing}")
        player_count = r.read_ubyte()
        self.players = {}
        for _ in range(player_count):
            slot_id = r.read_byte()
            player_id = r.read_long()
            full_name = r.read_string()
            avatar_id = r.read_short()
            avatar = r.read_ascii()
            tag_id = r.read_byte()
            chip_balance = r.read_long()
            star_balance = r.read_long()
            score = r.read_long()
            level = r.read_ubyte()
            is_owner = r.read_ubyte()
            self.players[slot_id] = {'full_name': full_name}
        current_turn_slot = r.read_byte()
        turn_timeout = r.read_short()
        slot_remain = r.read_short()
        current_state = r.read_ubyte()
        self.in_table = True
        match_point_count = r.read_ubyte()
        for _ in range(match_point_count):
            slot_id = r.read_byte()
            point = r.read_int()
        hcount = r.read_ubyte()
        vcount = r.read_ubyte()
        self.board.resize(hcount, vcount)
        cursor_pos = r.read_short()
        board_data = r.read_byte_array()
        self.board.fill_from_rle(board_data)
        self._determine_symbols()
        auto_start = r.read_ubyte()
        currency = r.read_ubyte()
        arg_count = r.read_ubyte()
        for _ in range(arg_count):
            key = r.read_ascii()
            val = r.read_string()
        if self.is_playing and current_turn_slot == self.my_slot_id:
            self.is_my_turn = True
            await self.make_move()
        if not self.is_playing and not self.ready_sent:
            self.ready_sent = True
            await asyncio.sleep(0.5)
            await self.send(self.build_set_client_mode_msg(1))
            await asyncio.sleep(0.5)
            await self.send(self.build_set_ready_msg())

    async def handle_start_match(self, r: ConnReader):
        self.game_count += 1
        self.is_playing = True
        point_count = r.read_ubyte()
        for _ in range(point_count):
            slot_id = r.read_byte()
            point = r.read_int()
        hcount = r.read_ubyte()
        vcount = r.read_ubyte()
        self.board.resize(hcount, vcount)
        cursor_pos = r.read_short()
        board_data = r.read_byte_array()
        self.board.fill_from_rle(board_data)
        self._determine_symbols()
        log.info(f"🎮 VÁN {self.game_count} | slot={self.my_slot_id} sym={self.my_symbol}")

    async def handle_set_turn(self, r: ConnReader):
        slot_id = r.read_byte()
        turn_timeout = r.read_short()
        remain_duration = r.read_short()
        log.info(f"SET_TURN: slot={slot_id} my={self.my_slot_id} playing={self.is_playing}")
        if slot_id == self.my_slot_id and self.is_playing:
            self.is_my_turn = True
            await asyncio.sleep(0.3)
            await self.make_move()
        else:
            self.is_my_turn = False

    async def handle_move(self, r: ConnReader):
        pos = r.read_short()
        symbol = r.read_byte()
        x, y = self.board.pos_to_xy(pos)
        current = self.board.get(x, y)
        if current == EMPTY:
            self.board.place(x, y, symbol)
            if len(self.board.move_history) <= 2:
                self.opp_symbol = symbol
                self.my_symbol = SYMBOL_O if symbol == SYMBOL_X else SYMBOL_X

    async def handle_gameover(self, r: ConnReader):
        self.is_playing = False
        self.is_my_turn = False
        self.ready_sent = False
        self.quick_play_attempts = 0
        player_count = r.read_ubyte()
        for _ in range(player_count):
            slot_id = r.read_byte()
            grade = r.read_byte()
            earn = r.read_long()
        match_result = r.read_string()
        elapsed = time.time() - self.start_time
        log.info(f"🏁 GAMEOVER: {match_result} | {self.game_count} ván | {elapsed/60:.1f} phút")
        await asyncio.sleep(2)
        self.ready_sent = True
        await self.send(self.build_set_ready_msg())

    async def handle_player_entered(self, r: ConnReader):
        slot_id = r.read_byte()
        player_id = r.read_long()
        full_name = r.read_string()
        avatar_id = r.read_short()
        avatar = r.read_ascii()
        tag_id = r.read_byte()
        chip = r.read_long()
        star = r.read_long()
        score = r.read_long()
        level = r.read_ubyte()
        is_owner = r.read_ubyte()
        self.players[slot_id] = {'full_name': full_name}
        if not self.is_playing and not self.ready_sent:
            self.ready_sent = True
            await asyncio.sleep(0.5)
            await self.send(self.build_set_client_mode_msg(1))
            await asyncio.sleep(0.5)
            await self.send(self.build_set_ready_msg())

    def _determine_symbols(self):
        if self.my_slot_id == 0:
            self.my_symbol = SYMBOL_X
            self.opp_symbol = SYMBOL_O
        else:
            self.my_symbol = SYMBOL_O
            self.opp_symbol = SYMBOL_X

    # ─── TÍNH NƯỚC ĐI (gọi AI trực tiếp, không cần API) ──────
    async def make_move(self):
        if not self.is_my_turn or not self.is_playing:
            return
        self.is_my_turn = False
        log.info("⏳ Tính nước đi...")

        # Chạy AI trong thread để không block event loop
        def _compute():
            t0 = time.time()
            (x, y), reason = self.ai.find_best_move(self.board, self.my_symbol, self.opp_symbol)
            ms = int((time.time() - t0) * 1000)
            return x, y, reason, ms

        try:
            x, y, reason, ms = await asyncio.to_thread(_compute)
            log.info(f"🧠 AI: ({x},{y}) {reason} [{ms}ms]")
        except Exception as e:
            log.error(f"Lỗi AI: {e}, fallback")
            candidates = self.board.get_neighbors()
            if candidates:
                x, y = candidates[0]
            else:
                x, y = self.board.hcount // 2, self.board.vcount // 2

        pos = self.board.xy_to_pos(x, y)
        log.info(f"🎯 ĐÁNH: ({x},{y}) pos={pos}")
        await self.send(self.build_play_msg(pos))
        self.board.place(x, y, self.my_symbol)

    # ─── Run & Reconnect ──────────────────────────────────────
    async def run(self):
        if not self.login_and_handshake():
            return
        await self.connect()
        await self.send(self.build_login_msg())
        self.keepalive_task = asyncio.create_task(self.keepalive_loop())
        try:
            while self.running:
                if self.should_stop():
                    self.running = False
                    break
                try:
                    raw = await asyncio.wait_for(self.ws.recv(), timeout=60.0)
                except asyncio.TimeoutError:
                    if self.ws and self.ws.open:
                        await self.send(self.build_pong_msg())
                    continue
                except websockets.exceptions.ConnectionClosedOK:
                    log.info("🔌 Connection đóng bình thường")
                    break
                except websockets.exceptions.ConnectionClosedError as e:
                    log.warning(f"🔌 Connection lỗi: {e}")
                    break
                if isinstance(raw, bytes):
                    await self.handle_message(raw)
        except Exception as e:
            log.error(f"Lỗi WebSocket: {e}")
            traceback.print_exc()
        finally:
            if self.keepalive_task and not self.keepalive_task.done():
                self.keepalive_task.cancel()
                try:
                    await self.keepalive_task
                except asyncio.CancelledError:
                    pass
            if self.ws:
                try:
                    await self.ws.close()
                except Exception:
                    pass

    async def run_with_reconnect(self):
        retries = 0
        self.start_time = time.time()
        while retries < RECONNECT_MAX_RETRIES:
            if self.should_stop():
                break
            try:
                self.is_playing = False
                self.is_my_turn = False
                self.in_table = False
                self.ready_sent = False
                self.mode_set = False
                self.running = True
                self.quick_play_attempts = 0
                self.board.clear()
                elapsed = time.time() - self.start_time
                log.info(f"🔄 Kết nối lần {retries + 1}/{RECONNECT_MAX_RETRIES} | {elapsed/60:.1f} phút")
                await self.run()
            except Exception as e:
                log.error(f"Lỗi nghiêm trọng: {e}")
                traceback.print_exc()
            if self.should_stop():
                break
            retries += 1
            wait = min(RECONNECT_BASE_WAIT * (2 ** min(retries, 4)), RECONNECT_MAX_WAIT)
            log.info(f"⏳ Đợi {wait}s reconnect...")
            await asyncio.sleep(wait)
        total = time.time() - self.start_time
        log.info(f"🛑 Bot dừng sau {total/60:.1f} phút, {self.game_count} ván, {retries} reconnect")


# ═══════════════════════════════════════════════════════════════
# MAIN - Chỉ cần chạy file này
# ═══════════════════════════════════════════════════════════════
async def main():
    bot = CaroBot()
    await bot.run_with_reconnect()

if __name__ == "__main__":
    asyncio.run(main())
