#!/usr/bin/env python3
"""
Caro Bot for gamevh.net
- Kết nối WebSocket, parse binary protocol bằng struct
- AI đánh cờ caro trên bàn 15 cột x 19 dòng
- Tự động chơi khi đến lượt
"""

import asyncio
import struct
import time
import logging
import sys
import re
from collections import defaultdict

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

# ─── Cấu hình ───────────────────────────────────────────────
WS_URL = "wss://gamevh.net/ws/gameServer"
GAME_URL = "https://gamevh.net/play/caro/0"
COOKIE_STR = "JSESSIONID=node0wu7yjibriuu1t361p41htw0372831466.node0; _ga=GA1.2.1295485888.1780171318; _gid=GA1.2.671190676.1780171318; _gat=1"

# Sẽ được cập nhật từ HTTP handshake
NICKNAME = ""
TOKEN = 0
PLACE_PATH = "Lobby.caro.0"
VERSION = "5.0.2"
GAME_ID = "caro"

# Board dimensions (per user: 15 cols x 19 rows)
HCOUNT = 15  # columns (x)
VCOUNT = 19  # rows (y)

# ─── Logging ────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("caro_bot")

# ─── Command Codes ──────────────────────────────────────────
CMD_PONG = 300
CMD_PING = 301
CMD_LOGIN = 302
CMD_ALERT = 303
CMD_RIBBON_MESSAGE = 304
CMD_BROADCAST = 311
CMD_INVITE = 312
CMD_SET_CLIENT_MODE = 314
CMD_CONFIG = 315
CMD_ENTER_PLACE = 401
CMD_ENTER_CHILD_PLACE = 402
CMD_PLAYER_ENTERED = 406
CMD_PLAYER_EXITED = 407
CMD_QUICK_PLAY = 408
CMD_GET_TABLE_DATA = 414
CMD_GET_TABLE_DATA_EX = 433
CMD_START_MATCH = 417
CMD_GAMEOVER = 418
CMD_ENTER_STATE = 419
CMD_SET_TURN = 420
CMD_SET_PLAYER_STATUS = 421
CMD_SET_PLAYER_POINT = 422
CMD_SET_PLAYER_ATTR = 423
CMD_BALANCE_CHANGED = 431
CMD_OWNER_CHANGED = 432
CMD_SET_READY = 434
CMD_BET = 501
CMD_PLAY = 502
CMD_HIGHLIGHT = 518
CMD_MOVE = 529
CMD_ASK_DRAW = 533
CMD_SURRENDER = 534
CMD_RETREAT = 535

# Map command ID -> name
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


# ─── Binary Protocol Reader ────────────────────────────────
class ConnReader:
    """Đọc binary data từ buffer giống DataView của JS, dùng struct."""

    def __init__(self, buf: bytes):
        self.buf = buf
        self.offset = 0

    def remaining(self) -> int:
        return len(self.buf) - self.offset

    def read_byte(self) -> int:
        """Signed int8, nhưng giá trị > 127 sẽ trừ 256 (giống JS)."""
        val = struct.unpack_from('>b', self.buf, self.offset)[0]
        self.offset += 1
        return val

    def read_ubyte(self) -> int:
        val = struct.unpack_from('>B', self.buf, self.offset)[0]
        self.offset += 1
        return val

    def read_short(self) -> int:
        val = struct.unpack_from('>h', self.buf, self.offset)[0]
        self.offset += 2
        return val

    def read_ushort(self) -> int:
        val = struct.unpack_from('>H', self.buf, self.offset)[0]
        self.offset += 2
        return val

    def read_int(self) -> int:
        val = struct.unpack_from('>i', self.buf, self.offset)[0]
        self.offset += 4
        return val

    def read_long(self) -> int:
        # 8 bytes big-endian signed int64
        hi = struct.unpack_from('>i', self.buf, self.offset)[0]
        lo = struct.unpack_from('>I', self.buf, self.offset + 4)[0]
        self.offset += 8
        return hi * (1 << 32) + lo

    def read_ascii(self) -> str:
        length = self.read_ubyte()
        data = self.buf[self.offset:self.offset + length]
        self.offset += length
        return data.decode('ascii', errors='replace')

    def read_long_ascii(self) -> str:
        length = self.read_int()
        data = self.buf[self.offset:self.offset + length]
        self.offset += length
        return data.decode('ascii', errors='replace')

    def read_string(self) -> str:
        char_count = self.read_short()
        if char_count <= 0:
            return ""
        data = self.buf[self.offset:self.offset + char_count * 2]
        self.offset += char_count * 2
        # UTF-16BE
        return data.decode('utf-16-be', errors='replace')

    def read_byte_array(self) -> list:
        length = self.read_short()
        data = list(self.buf[self.offset:self.offset + length])
        self.offset += length
        return data

    def read_command(self) -> str:
        """Đọc command code từ đầu message.
        Nếu byte đầu âm -> ASCII command name (độ dài = |byte|).
        Nếu byte đầu không âm -> 2-byte command ID (big-endian ushort).
        """
        first = self.read_byte()
        if first < 0:
            # ASCII command: |first| bytes
            name_len = -first
            name = self.buf[self.offset:self.offset + name_len].decode('ascii', errors='replace')
            self.offset += name_len
            return name
        else:
            # 2-byte command ID
            second = self.read_ubyte()
            cmd_id = (first << 8) | second
            return CMD_NAMES.get(cmd_id, f"CMD_{cmd_id}")


# ─── Binary Protocol Writer ────────────────────────────────
class ConnWriter:
    """Gói binary message gửi lên server."""

    def __init__(self):
        self.parts = []

    def write_byte(self, val: int):
        self.parts.append(struct.pack('>b', val))

    def write_ubyte(self, val: int):
        self.parts.append(struct.pack('>B', val))

    def write_short(self, val: int):
        self.parts.append(struct.pack('>h', val))

    def write_ushort(self, val: int):
        self.parts.append(struct.pack('>H', val))

    def write_int(self, val: int):
        self.parts.append(struct.pack('>i', val))

    def write_long(self, val: int):
        hi = val >> 32
        lo = val & 0xFFFFFFFF
        self.parts.append(struct.pack('>iI', hi, lo))

    def write_ascii(self, s: str):
        encoded = s.encode('ascii', errors='replace')
        self.parts.append(struct.pack('>B', len(encoded)))
        self.parts.append(encoded)

    def write_long_ascii(self, s: str):
        encoded = s.encode('ascii', errors='replace')
        self.parts.append(struct.pack('>i', len(encoded)))
        self.parts.append(encoded)

    def write_string(self, s: str):
        encoded = s.encode('utf-16-be')
        char_count = len(encoded) // 2
        self.parts.append(struct.pack('>h', char_count))
        self.parts.append(encoded)

    def write_command(self, cmd: str):
        """Ghi command theo format: nếu có trong CMD_NAMES thì dùng ID, còn dùng ASCII."""
        # Tìm cmd_id
        cmd_id = None
        for cid, cname in CMD_NAMES.items():
            if cname == cmd:
                cmd_id = cid
                break
        if cmd_id is not None:
            # 2-byte big-endian
            self.parts.append(struct.pack('>H', cmd_id))
        else:
            # ASCII format: -len + name bytes
            name_bytes = cmd.encode('ascii')
            self.parts.append(struct.pack('>b', -len(name_bytes)))
            self.parts.append(name_bytes)

    def to_bytes(self) -> bytes:
        return b''.join(self.parts)


# ─── Board State ────────────────────────────────────────────
EMPTY = -1
SYMBOL_O = 0
SYMBOL_X = 1


class CaroBoard:
    """Bàn cờ Caro 15 cột x 19 dòng."""

    def __init__(self, hcount=HCOUNT, vcount=VCOUNT):
        self.hcount = hcount
        self.vcount = vcount
        # board[y][x] = EMPTY / SYMBOL_O / SYMBOL_X
        self.board = [[EMPTY] * hcount for _ in range(vcount)]
        self.my_symbol = SYMBOL_X  # sẽ được set khi nhận START_MATCH/MOVE
        self.opp_symbol = SYMBOL_O
        self.move_history = []

    def clear(self):
        self.board = [[EMPTY] * self.hcount for _ in range(self.vcount)]
        self.move_history = []

    def resize(self, hcount, vcount):
        self.hcount = hcount
        self.vcount = vcount
        self.clear()

    def pos_to_xy(self, pos: int):
        """pos = y * hcount + x"""
        y = pos // self.hcount
        x = pos % self.hcount
        return x, y

    def xy_to_pos(self, x: int, y: int) -> int:
        return y * self.hcount + x

    def place(self, x: int, y: int, symbol: int):
        if 0 <= x < self.hcount and 0 <= y < self.vcount:
            self.board[y][x] = symbol
            self.move_history.append((x, y, symbol))

    def get(self, x: int, y: int) -> int:
        if 0 <= x < self.hcount and 0 <= y < self.vcount:
            return self.board[y][x]
        return EMPTY

    def fill_from_rle(self, board_data: list):
        """Parse RLE-encoded board data từ server.
        board_data: list of unsigned bytes (0-255), cần convert sang signed (-128-127).
        Giống JS DataView.readInt8():
        - val >= 0 (0-127): symbol tại vị trí hiện tại (0=O, 1=X). pos++.
        - val < 0 (128-255 -> signed -128 to -1): skip |val| empty positions.
        """
        self.clear()
        pos = 0
        total_cells = self.hcount * self.vcount
        for unsigned_val in board_data:
            # Convert unsigned (0-255) to signed (-128-127) like JS readInt8
            if unsigned_val > 127:
                signed_val = unsigned_val - 256
            else:
                signed_val = unsigned_val

            if signed_val >= 0:
                # symbol at current position: 0=O, 1=X
                y = pos // self.hcount
                x = pos % self.hcount
                if 0 <= x < self.hcount and 0 <= y < self.vcount:
                    self.board[y][x] = signed_val
                pos += 1
            else:
                # skip |signed_val| empty positions
                pos += (-signed_val)

    def is_empty(self, x: int, y: int) -> bool:
        return self.get(x, y) == EMPTY

    def get_neighbors(self, radius=2):
        """Lấy các ô trống gần các quân đã đánh (trong bán kính radius)."""
        visited = set()
        result = []
        for y in range(self.vcount):
            for x in range(self.hcount):
                if self.board[y][x] != EMPTY:
                    for dy in range(-radius, radius + 1):
                        for dx in range(-radius, radius + 1):
                            nx, ny = x + dx, y + dy
                            if (0 <= nx < self.hcount and 0 <= ny < self.vcount
                                    and self.board[ny][nx] == EMPTY
                                    and (nx, ny) not in visited):
                                visited.add((nx, ny))
                                result.append((nx, ny))
        return result

    def display(self) -> str:
        """Hiển thị bàn cờ dạng text."""
        lines = []
        sym = {EMPTY: '.', SYMBOL_O: 'O', SYMBOL_X: 'X'}
        header = "   " + "".join(f"{i:2d}" for i in range(self.hcount))
        lines.append(header)
        for y in range(self.vcount):
            row = f"{y:2d} " + "".join(f" {sym.get(self.board[y][x], '?')}" for x in range(self.hcount))
            lines.append(row)
        return "\n".join(lines)


# ─── Caro AI (Heuristic + Minimax) ─────────────────────────
class CaroAI:
    """AI đánh Caro dùng heuristic evaluation + minimax (depth 2-4)."""

    def __init__(self, board: CaroBoard):
        self.board = board
        # Trọng số cho các pattern
        self.WIN_SCORE = 10000000
        self.FIVE = 1000000
        self.OPEN_FOUR = 500000
        self.HALF_FOUR = 50000
        self.OPEN_THREE = 50000
        self.HALF_THREE = 5000
        self.OPEN_TWO = 5000
        self.HALF_TWO = 500
        self.OPEN_ONE = 500
        self.HALF_ONE = 50

    def evaluate_line(self, cells: list, my_sym: int, opp_sym: int) -> int:
        """Đánh giá một dòng 5 ô liên tiếp."""
        my_count = cells.count(my_sym)
        opp_count = cells.count(opp_sym)
        empty_count = cells.count(EMPTY)

        if my_count > 0 and opp_count > 0:
            return 0  # blocked by opponent, no value

        if my_count == 5:
            return self.FIVE
        if opp_count == 5:
            return -self.FIVE

        if my_count == 4 and empty_count == 1:
            return self.HALF_FOUR
        if opp_count == 4 and empty_count == 1:
            return -self.HALF_FOUR

        if my_count == 3 and empty_count == 2:
            return self.HALF_THREE
        if opp_count == 3 and empty_count == 2:
            return -self.HALF_THREE

        if my_count == 2 and empty_count == 3:
            return self.HALF_TWO
        if opp_count == 2 and empty_count == 3:
            return -self.HALF_TWO

        if my_count == 1 and empty_count == 4:
            return self.HALF_ONE
        if opp_count == 1 and empty_count == 4:
            return -self.HALF_ONE

        return 0

    def evaluate_position(self, my_sym: int, opp_sym: int) -> int:
        """Đánh giá toàn bộ bàn cờ cho my_sym."""
        board = self.board
        hcount = board.hcount
        vcount = board.vcount
        score = 0

        # Duyệt theo 4 hướng: ngang, dọc, chéo \, chéo /
        directions = [(1, 0), (0, 1), (1, 1), (1, -1)]

        for dy, dx in directions:
            for y in range(vcount):
                for x in range(hcount):
                    # Kiểm tra có đủ 5 ô không
                    ex = x + dx * 4
                    ey = y + dy * 4
                    if not (0 <= ex < hcount and 0 <= ey < vcount):
                        continue

                    cells = []
                    for i in range(5):
                        cx = x + dx * i
                        cy = y + dy * i
                        cells.append(board.get(cx, cy))

                    score += self.evaluate_line(cells, my_sym, opp_sym)

        # Ưu tiên vị trí trung tâm
        center_x = hcount // 2
        center_y = vcount // 2
        for y in range(vcount):
            for x in range(hcount):
                if board.get(x, y) == my_sym:
                    dist = abs(x - center_x) + abs(y - center_y)
                    score += max(0, 10 - dist)
                elif board.get(x, y) == opp_sym:
                    dist = abs(x - center_x) + abs(y - center_y)
                    score -= max(0, 10 - dist)

        return score

    def check_win_at(self, x: int, y: int, symbol: int) -> bool:
        """Kiểm tra xem đặt symbol tại (x,y) có thắng không (5 liên tiếp)."""
        board = self.board
        directions = [(1, 0), (0, 1), (1, 1), (1, -1)]
        for dx, dy in directions:
            count = 1
            # Đếm thuận
            for i in range(1, 5):
                nx, ny = x + dx * i, y + dy * i
                if 0 <= nx < board.hcount and 0 <= ny < board.vcount and board.get(nx, ny) == symbol:
                    count += 1
                else:
                    break
            # Đếm ngược
            for i in range(1, 5):
                nx, ny = x - dx * i, y - dy * i
                if 0 <= nx < board.hcount and 0 <= ny < board.vcount and board.get(nx, ny) == symbol:
                    count += 1
                else:
                    break
            if count >= 5:
                return True
        return False

    def find_winning_move(self, symbol: int):
        """Tìm nước thắng ngay cho symbol."""
        board = self.board
        candidates = self.get_candidate_moves()
        for x, y in candidates:
            board.place(x, y, symbol)
            if self.check_win_at(x, y, symbol):
                board.place(x, y, EMPTY)  # undo
                return (x, y)
            board.place(x, y, EMPTY)  # undo
        return None

    def get_candidate_moves(self) -> list:
        """Lấy danh sách các nước đi ứng viên."""
        board = self.board
        neighbors = board.get_neighbors(radius=2)
        if not neighbors:
            # Bàn cờ trống -> đánh giữa
            cx = board.hcount // 2
            cy = board.vcount // 2
            return [(cx, cy)]
        return neighbors

    def score_move(self, x: int, y: int, my_sym: int, opp_sym: int) -> int:
        """Đánh giá một nước đi cụ thể."""
        board = self.board

        # 1. Nước thắng ngay -> ưu tiên cao nhất
        board.place(x, y, my_sym)
        if self.check_win_at(x, y, my_sym):
            board.place(x, y, EMPTY)
            return self.WIN_SCORE
        board.place(x, y, EMPTY)

        # 2. Chặn nước thắng của đối thủ
        board.place(x, y, opp_sym)
        if self.check_win_at(x, y, opp_sym):
            board.place(x, y, EMPTY)
            return self.WIN_SCORE - 1
        board.place(x, y, EMPTY)

        # 3. Tạo double threat (2 open-three hoặc open-four + half-four)
        score = 0

        # Đánh giá tấn công (đặt quân mình)
        board.place(x, y, my_sym)
        attack_score = self._count_threats(x, y, my_sym)
        score += attack_score * 1000
        board.place(x, y, EMPTY)

        # Đánh giá phòng thủ (đặt quân đối thủ)
        board.place(x, y, opp_sym)
        defense_score = self._count_threats(x, y, opp_sym)
        score += defense_score * 800
        board.place(x, y, EMPTY)

        # 4. Khoảng cách đến trung tâm
        center_x = board.hcount // 2
        center_y = board.vcount // 2
        dist = abs(x - center_x) + abs(y - center_y)
        score += max(0, 20 - dist * 2)

        # 5. Khoảng cách đến nước đi gần nhất
        if board.move_history:
            last_x, last_y, _ = board.move_history[-1]
            near_dist = abs(x - last_x) + abs(y - last_y)
            if near_dist <= 3:
                score += 10

        return score

    def _count_threats(self, x: int, y: int, symbol: int) -> int:
        """Đếm số threat (open/half four, open three) tạo ra tại (x,y)."""
        board = self.board
        threats = 0
        directions = [(1, 0), (0, 1), (1, 1), (1, -1)]

        for dx, dy in directions:
            count = 1
            open_ends = 0

            # Đếm thuận
            blocked_plus = False
            for i in range(1, 5):
                nx, ny = x + dx * i, y + dy * i
                if 0 <= nx < board.hcount and 0 <= ny < board.vcount:
                    if board.get(nx, ny) == symbol:
                        count += 1
                    elif board.get(nx, ny) == EMPTY:
                        open_ends += 1
                        break
                    else:
                        blocked_plus = True
                        break
                else:
                    blocked_plus = True
                    break

            # Đếm ngược
            blocked_minus = False
            for i in range(1, 5):
                nx, ny = x - dx * i, y - dy * i
                if 0 <= nx < board.hcount and 0 <= ny < board.vcount:
                    if board.get(nx, ny) == symbol:
                        count += 1
                    elif board.get(nx, ny) == EMPTY:
                        open_ends += 1
                        break
                    else:
                        blocked_minus = True
                        break
                else:
                    blocked_minus = True
                    break

            if count >= 5:
                threats += 100  # Winning threat
            elif count == 4 and open_ends >= 1:
                threats += 50  # Four (open or half)
            elif count == 3 and open_ends == 2:
                threats += 30  # Open three
            elif count == 3 and open_ends == 1:
                threats += 10  # Half three
            elif count == 2 and open_ends == 2:
                threats += 5   # Open two

        return threats

    def find_best_move(self, my_sym: int, opp_sym: int):
        """Tìm nước đi tốt nhất."""
        board = self.board

        # 1. Kiểm tra nước thắng ngay
        win_move = self.find_winning_move(my_sym)
        if win_move:
            log.info(f"🎯 Nước thắng: ({win_move[0]}, {win_move[1]})")
            return win_move

        # 2. Chặn nước thắng đối thủ
        block_move = self.find_winning_move(opp_sym)
        if block_move:
            log.info(f"🛡️ Chặn nước thắng đối thủ: ({block_move[0]}, {block_move[1]})")
            return block_move

        # 3. Đánh giá tất cả ứng viên
        candidates = self.get_candidate_moves()
        if not candidates:
            return (board.hcount // 2, board.vcount // 2)

        best_score = -1
        best_move = candidates[0]

        scored_moves = []
        for x, y in candidates:
            score = self.score_move(x, y, my_sym, opp_sym)
            scored_moves.append((score, x, y))

        scored_moves.sort(reverse=True)

        # Log top 5
        for i, (score, x, y) in enumerate(scored_moves[:5]):
            log.info(f"  Top {i+1}: ({x},{y}) score={score}")

        best_score, best_x, best_y = scored_moves[0]
        return (best_x, best_y)


# ─── Game Client ────────────────────────────────────────────
class CaroBot:
    """Bot chơi Caro trên gamevh.net."""

    def __init__(self):
        self.ws = None
        self.board = CaroBoard()
        self.ai = CaroAI(self.board)
        self.my_slot_id = -1
        self.is_my_turn = False
        self.is_playing = False
        self.my_symbol = SYMBOL_X
        self.opp_symbol = SYMBOL_O
        self.players = {}  # slotId -> info
        self.login_cookie = ""
        self.last_ping = 0
        self.ping_interval = 7.5
        self.game_count = 0
        self.win_count = 0
        self.lose_count = 0
        self.draw_count = 0
        self.running = True
        self.in_table = False  # Đã ngồi bàn chưa
        self.ready_sent = False  # Đã gửi SET_READY chưa
        self.mode_set = False   # Đã set PLAY mode chưa
        # Auth info - sẽ được cập nhật từ HTTP handshake
        self.nickname = ""
        self.token = 0
        self.cookie_header = COOKIE_STR
        self.place_path = PLACE_PATH

    def http_handshake(self) -> bool:
        """HTTP GET trang game để lấy token & nickname hợp lệ cho JSESSIONID."""
        log.info("🌐 HTTP handshake để lấy auth info...")
        try:
            s = requests.Session()
            # Parse cookie string thành dict
            cookies = {}
            for part in COOKIE_STR.split(';'):
                part = part.strip()
                if '=' in part:
                    k, v = part.split('=', 1)
                    cookies[k.strip()] = v.strip()
            for k, v in cookies.items():
                s.cookies.set(k, v, domain='gamevh.net')

            r = s.get(GAME_URL, timeout=10, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            })
            log.info(f"HTTP status: {r.status_code}")

            # Cập nhật JSESSIONID nếu server set mới
            for k, v in s.cookies.items():
                if k == 'JSESSIONID':
                    old = cookies.get('JSESSIONID', '')
                    if v != old:
                        log.info(f"JSESSIONID updated: {old[:20]}... -> {v[:20]}...")
                        cookies['JSESSIONID'] = v

            # Rebuild cookie header
            self.cookie_header = '; '.join(f'{k}={v}' for k, v in cookies.items())

            html = r.text

            # Extract token
            m = re.search(r'var\s+token\s*=\s*(\d+)', html)
            if m:
                self.token = int(m.group(1))
                log.info(f"Token: {self.token}")
            else:
                log.error("Không tìm thấy token!")
                return False

            # Extract nickname
            m = re.search(r"var\s+currentPlayerNickName\s*=\s*'([^']+)'", html)
            if m:
                self.nickname = m.group(1)
                log.info(f"Nickname: {self.nickname}")
            else:
                log.error("Không tìm thấy nickname!")
                return False

            # Extract placePath
            m = re.search(r'var\s+placePath\s*=\s*"([^"]+)"', html)
            if m:
                self.place_path = m.group(1)
                log.info(f"PlacePath: {self.place_path}")

            return True

        except Exception as e:
            log.error(f"Lỗi HTTP handshake: {e}")
            return False

    async def connect(self):
        """Kết nối WebSocket đến server."""
        headers = {
            "Cookie": self.cookie_header,
            "Origin": "https://gamevh.net",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        log.info(f"Đang kết nối đến {WS_URL}...")
        try:
            self.ws = await websockets.connect(
                WS_URL,
                additional_headers=headers,
                max_size=2**20,
                ping_interval=None,  # Tự xử lý ping/pong
            )
            log.info("✅ Đã kết nối WebSocket!")
            return True
        except Exception as e:
            log.error(f"❌ Lỗi kết nối: {e}")
            return False

    async def send(self, data: bytes):
        """Gửi binary data qua WebSocket."""
        if self.ws:
            try:
                await self.ws.send(data)
            except Exception as e:
                log.error(f"Lỗi gửi: {e}")

    def build_login_msg(self) -> bytes:
        """Tạo message LOGIN."""
        w = ConnWriter()
        w.write_command("LOGIN")
        w.write_ascii(self.nickname)
        w.write_int(self.token)
        w.write_ascii(VERSION)
        w.write_ascii(self.login_cookie)
        w.write_ascii(GAME_ID)
        w.write_byte(1)  # unknown flag
        return w.to_bytes()

    def build_enter_place_msg(self, path: str, password: str = "", mode: int = 1) -> bytes:
        """Tạo message ENTER_PLACE."""
        w = ConnWriter()
        w.write_command("ENTER_PLACE")
        w.write_ascii(path)
        w.write_string(password)
        w.write_byte(mode)
        return w.to_bytes()

    def build_set_client_mode_msg(self, mode: int = 1) -> bytes:
        """Tạo message SET_CLIENT_MODE (1=PLAY)."""
        w = ConnWriter()
        w.write_command("SET_CLIENT_MODE")
        w.write_byte(mode)
        return w.to_bytes()

    def build_get_table_data_ex_msg(self) -> bytes:
        """Tạo message GET_TABLE_DATA_EX."""
        w = ConnWriter()
        w.write_command("GET_TABLE_DATA_EX")
        w.write_ascii("")
        return w.to_bytes()

    def build_play_msg(self, pos: int) -> bytes:
        """Tạo message PLAY với vị trí đánh."""
        w = ConnWriter()
        w.write_command("PLAY")
        w.write_short(pos)
        return w.to_bytes()

    def build_pong_msg(self) -> bytes:
        """Tạo message PONG."""
        w = ConnWriter()
        w.write_command("PONG")
        return w.to_bytes()

    def build_quick_play_msg(self) -> bytes:
        """Tạo message QUICK_PLAY."""
        w = ConnWriter()
        w.write_command("QUICK_PLAY")
        w.write_ascii("")  # roomId = any
        w.write_byte(-1)   # betAmtId = default
        return w.to_bytes()

    def build_set_ready_msg(self) -> bytes:
        """Tạo message SET_READY."""
        w = ConnWriter()
        w.write_command("SET_READY")
        return w.to_bytes()

    async def handle_message(self, raw: bytes):
        """Xử lý binary message từ server."""
        # Hex dump để debug (chỉ khi DEBUG level)
        if log.isEnabledFor(logging.DEBUG):
            hex_str = raw.hex()
            log.debug(f"📥 RAW ({len(raw)} bytes): {hex_str[:200]}{'...' if len(hex_str)>200 else ''}")
        r = ConnReader(raw)
        cmd = r.read_command()
        log.info(f"📩 {cmd} (remaining: {r.remaining()})")

        try:
            if cmd == "PING":
                await self.send(self.build_pong_msg())
                log.debug("PONG sent")

            elif cmd == "LOGIN":
                await self.handle_login(r)

            elif cmd == "ENTER_PLACE":
                await self.handle_enter_place(r)

            elif cmd == "SET_CLIENT_MODE":
                slot = r.read_byte()
                log.info(f"SET_CLIENT_MODE: slot={slot}")
                # Không tự gửi GET_TABLE_DATA_EX - tránh loop

            elif cmd == "GET_TABLE_DATA_EX":
                await self.handle_table_data_ex(r)

            elif cmd == "START_MATCH":
                await self.handle_start_match(r)

            elif cmd == "SET_TURN":
                await self.handle_set_turn(r)

            elif cmd == "MOVE":
                await self.handle_move(r)

            elif cmd == "HIGHLIGHT":
                await self.handle_highlight(r)

            elif cmd == "GAMEOVER":
                await self.handle_gameover(r)

            elif cmd == "PLAY":
                # PLAY response - xác nhận nước đi của mình
                status = r.read_byte()
                if status != 0:
                    error_msg = r.read_string() if r.remaining() > 0 else ""
                    log.warning(f"PLAY error: status={status}, msg={error_msg}")

            elif cmd == "PLAYER_ENTERED":
                await self.handle_player_entered(r)

            elif cmd == "PLAYER_EXITED":
                slot_id = r.read_byte()
                log.info(f"Player exited: slot {slot_id}")
                if slot_id in self.players:
                    del self.players[slot_id]

            elif cmd == "ALERT":
                msg = r.read_string()
                log.warning(f"⚠️ ALERT: {msg}")

            elif cmd == "BROADCAST":
                msg = r.read_string()
                log.info(f"📢 BROADCAST: {msg}")

            elif cmd == "RIBBON_MESSAGE":
                msg = r.read_ascii()
                log.info(f".Ribbon: {msg}")

            elif cmd == "CONFIG":
                log.info("CONFIG received")

            elif cmd == "BALANCE_CHANGED":
                currency = r.read_byte()
                balance = r.read_long()
                log.info(f"💰 Balance changed: {balance} ({'chip' if currency == 0 else 'star'})")

            elif cmd == "OWNER_CHANGED":
                slot_id = r.read_byte()
                log.info(f"👑 Owner changed: slot {slot_id}")

            elif cmd == "ENTER_STATE":
                state = r.read_ascii()
                log.info(f"🔄 Enter state: {state}")

            elif cmd == "SET_PLAYER_STATUS":
                slot_id = r.read_byte()
                status = r.read_byte()
                log.info(f"Player status: slot {slot_id} = {status}")

            elif cmd == "SET_PLAYER_POINT":
                slot_id = r.read_byte()
                point = r.read_int()
                log.info(f"Player point: slot {slot_id} = {point}")

            elif cmd == "SET_PLAYER_ATTR":
                slot_id = r.read_byte()
                attr = r.read_ascii()
                val = r.read_string()
                log.info(f"Player attr: slot {slot_id} {attr}={val}")

            elif cmd == "INVITE":
                inviter = r.read_ascii()
                log.info(f"📨 Invite from: {inviter}")

            elif cmd == "QUICK_PLAY":
                await self.handle_quick_play(r)

            elif cmd == "CMD_415":
                # TABLE_IN_ROOM_CHANGED - ignore, just log
                log.debug("TABLE_IN_ROOM_CHANGED")

            elif cmd == "CMD_416":
                # SLOT_IN_TABLE_CHANGED - cập nhật slot info
                log.debug("SLOT_IN_TABLE_CHANGED")

            elif cmd == "CMD_345":
                # CLIENT_MODE_CHANGED
                slot_id = r.read_byte()
                mode = r.read_byte()
                log.info(f"🔄 CLIENT_MODE_CHANGED: slot={slot_id}, mode={mode}")

            elif cmd == "CMD_424":
                # Lucky wheel or similar - ignore
                pass

            else:
                log.debug(f"Unhandled command: {cmd} (remaining bytes: {r.remaining()})")

        except Exception as e:
            log.error(f"Lỗi xử lý {cmd}: {e}")
            import traceback
            traceback.print_exc()

    async def handle_login(self, r: ConnReader):
        """Xử lý phản hồi LOGIN."""
        status = r.read_byte()
        log.info(f"LOGIN status={status}, remaining={r.remaining()}")
        if status == 0:
            path = r.read_string()
            log.info(f"LOGIN path={path}")
            # Khi path="REFRESH", server yêu cầu reload, không có thêm field
            if path == "REFRESH":
                log.info("🔄 Server yêu cầu REFRESH - vẫn tiếp tục...")
                # Thử vào place luôn
                await self.send(self.build_enter_place_msg(self.place_path, "", 1))
                return
            # Normal login success - đọc thêm các field nếu có
            if r.remaining() > 0:
                self.login_cookie = r.read_ascii()
            if r.remaining() > 0:
                password = r.read_string()
            if r.remaining() > 0:
                material = r.read_ascii()
            log.info(f"✅ LOGIN thành công! path={path}, cookie={self.login_cookie[:20] if self.login_cookie else 'N/A'}...")
            # Nhập place
            await self.send(self.build_enter_place_msg(self.place_path, "", 1))
        else:
            if r.remaining() > 0:
                error_msg = r.read_string()
                log.error(f"❌ LOGIN thất bại: status={status}, msg={error_msg}")
            else:
                log.error(f"❌ LOGIN thất bại: status={status}")

    async def handle_quick_play(self, r: ConnReader):
        """Xử lý QUICK_PLAY response."""
        try:
            # Đọc status byte (0 = success, -1 = error)
            status = r.read_byte()
            if status != 0:
                # Error
                error_msg = r.read_string() if r.remaining() > 0 else ""
                log.info(f"🎲 Quick play lỗi: {error_msg}")
                # Thử lại sau
                await asyncio.sleep(3)
                await self.send(self.build_quick_play_msg())
                return

            # Success
            table_path = r.read_ascii()
            table_name = r.read_string()
            log.info(f"🎲 Quick play -> path={table_path}, name={table_name}")

            # Parse table args
            if r.remaining() > 0:
                arg_count = r.read_ubyte()
                for _ in range(arg_count):
                    key = r.read_ascii()
                    val = r.read_string()
                    log.info(f"  Arg: {key}={val}")

            # Vào bàn chơi
            if table_path:
                self.in_table = True
                log.info(f"🏠 Entering table: {table_path}")
                await self.send(self.build_enter_place_msg(table_path, "", 1))
                await asyncio.sleep(0.5)
                await self.send(self.build_set_client_mode_msg(1))
                await asyncio.sleep(0.3)
                await self.send(self.build_get_table_data_ex_msg())

        except Exception as e:
            log.error(f"Lỗi parse quick play: {e}")
            import traceback
            traceback.print_exc()

    async def handle_enter_place(self, r: ConnReader):
        """Xử lý phản hồi ENTER_PLACE."""
        currency = r.read_byte()
        rate = r.read_ushort()
        log.info(f"🏠 ENTER_PLACE: currency={'chip' if currency == 0 else 'star'}, rate={rate/10}")
        # Đổi sang chế độ chơi (chỉ 1 lần)
        if not self.mode_set:
            self.mode_set = True
            await self.send(self.build_set_client_mode_msg(1))
        # Yêu cầu table data (chỉ 1 lần)
        await self.send(self.build_get_table_data_ex_msg())

    async def handle_table_data_ex(self, r: ConnReader):
        """Xử lý GET_TABLE_DATA_EX response."""
        try:
            # Check error first
            first_byte = r.read_byte()
            if first_byte != 0:
                # Error response
                error_code = first_byte
                error_msg = r.read_string() if r.remaining() > 0 else ""
                log.info(f"📋 GET_TABLE_DATA_EX error: code={error_code}, msg={error_msg}")
                # Chưa ngồi bàn -> tìm bàn mới (chỉ 1 lần)
                if "not in table" in error_msg.lower() and not self.in_table:
                    log.info("⏳ Chưa ngồi bàn, tìm bàn mới...")
                    await self.send(self.build_quick_play_msg())
                return

            # Success - parse state data
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

            # Table data
            self.my_slot_id = r.read_byte()
            is_playing = r.read_ubyte()
            self.is_playing = is_playing == 1

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
                self.players[slot_id] = {
                    'player_id': player_id,
                    'full_name': full_name,
                    'is_owner': is_owner,
                    'level': level,
                }
                log.info(f"  👤 Slot {slot_id}: {full_name} (id={player_id}, lv={level}, owner={is_owner})")

            current_turn_slot = r.read_byte()
            turn_timeout = r.read_short()
            slot_remain = r.read_short()
            current_state = r.read_ubyte()

            log.info(f"  My slot: {self.my_slot_id}, playing: {self.is_playing}, "
                     f"turn_slot: {current_turn_slot}, state: {current_state}")

            self.in_table = True  # Đã ngồi bàn

            # Match points
            match_point_count = r.read_ubyte()
            for _ in range(match_point_count):
                slot_id = r.read_byte()
                point = r.read_int()

            # Board data (Caro-specific)
            hcount = r.read_ubyte()
            vcount = r.read_ubyte()
            log.info(f"  Board: {hcount}x{vcount}")
            self.board.resize(hcount, vcount)

            cursor_pos = r.read_short()
            board_data = r.read_byte_array()
            self.board.fill_from_rle(board_data)

            # Xác định symbol của mình dựa trên board data
            self._determine_symbols()

            # isAutoStart
            auto_start = r.read_ubyte()

            # Currency
            currency = r.read_ubyte()

            # Table args
            arg_count = r.read_ubyte()
            for _ in range(arg_count):
                key = r.read_ascii()
                val = r.read_string()

            log.info(f"  Board state:\n{self.board.display()}")

            # Nếu đang chơi và đến lượt mình
            if self.is_playing and current_turn_slot == self.my_slot_id:
                self.is_my_turn = True
                await self.make_move()

            # Nếu chưa chơi - đợi đối thủ, không spam
            if not self.is_playing:
                log.info("⏳ Đang ngồi bàn, chờ đối thủ/ván mới...")
                # Gửi SET_READY chỉ 1 lần
                if not self.ready_sent:
                    self.ready_sent = True
                    await self.send(self.build_set_ready_msg())

        except Exception as e:
            log.error(f"Lỗi parse table data: {e}")
            import traceback
            traceback.print_exc()

    async def handle_start_match(self, r: ConnReader):
        """Xử lý START_MATCH - bắt đầu ván mới."""
        self.game_count += 1
        self.is_playing = True

        # Match points
        point_count = r.read_ubyte()
        for _ in range(point_count):
            slot_id = r.read_byte()
            point = r.read_int()
            log.info(f"  Match point: slot {slot_id} = {point}")

        # Board data
        hcount = r.read_ubyte()
        vcount = r.read_ubyte()
        self.board.resize(hcount, vcount)

        cursor_pos = r.read_short()
        board_data = r.read_byte_array()
        self.board.fill_from_rle(board_data)

        self._determine_symbols()

        log.info(f"🎮 === VÁN {self.game_count} BẮT ĐẦU === Board: {hcount}x{vcount}")
        log.info(f"  My symbol: {'X' if self.my_symbol == SYMBOL_X else 'O'}")
        log.info(f"  Board:\n{self.board.display()}")

    async def handle_set_turn(self, r: ConnReader):
        """Xử lý SET_TURN - đổi lượt đi."""
        slot_id = r.read_byte()
        turn_timeout = r.read_short()
        remain_duration = r.read_short()

        is_my_turn = (slot_id == self.my_slot_id)
        log.info(f"🔄 SET_TURN: slot={slot_id} (me={self.my_slot_id}), "
                 f"my_turn={is_my_turn}, timeout={turn_timeout}s")

        if is_my_turn and self.is_playing:
            self.is_my_turn = True
            # Đợi 1 giây trước khi đánh (để tránh quá nhanh)
            await asyncio.sleep(0.8)
            await self.make_move()
        else:
            self.is_my_turn = False

    async def handle_move(self, r: ConnReader):
        """Xử lý MOVE - nhận nước đi (có thể là của mình hoặc đối thủ)."""
        pos = r.read_short()
        symbol = r.read_byte()
        x, y = self.board.pos_to_xy(pos)

        sym_char = 'X' if symbol == SYMBOL_X else 'O'

        # Cập nhật symbol của mình dựa trên nước đi echo từ server
        # Nếu vị trí đã được đặt bởi bot (từ make_move), đây là echo của bot
        current = self.board.get(x, y)
        if current == symbol:
            # Đã đặt rồi - đây là echo từ server cho nước đi của mình
            log.info(f"✓ Xác nhận: ({x}, {y}) pos={pos} symbol={sym_char}")
            # Cập nhật my_symbol dựa trên echo
            self.my_symbol = symbol
            self.opp_symbol = SYMBOL_O if symbol == SYMBOL_X else SYMBOL_X
        elif current == EMPTY:
            # Ô trống - đây là nước đi của đối thủ
            log.info(f"⛔ Đối thủ đánh: ({x}, {y}) pos={pos} symbol={sym_char}")
            self.board.place(x, y, symbol)
            # Nếu đây là nước đầu tiên, cập nhật symbol đối thủ
            if len(self.board.move_history) <= 2:
                self.opp_symbol = symbol
                self.my_symbol = SYMBOL_O if symbol == SYMBOL_X else SYMBOL_X
        else:
            # Lỗi: ô đã có quân khác
            log.warning(f"⚠️ MOVE conflict tại ({x}, {y}): expected {current}, got {symbol}")
            self.board.place(x, y, symbol)
        log.info(f"  Board:\n{self.board.display()}")

    async def handle_highlight(self, r: ConnReader):
        """Xử lý HIGHLIGHT - dòng thắng."""
        count = r.read_ubyte()
        positions = []
        for _ in range(count):
            pos = r.read_short()
            x, y = self.board.pos_to_xy(pos)
            positions.append((x, y))
        log.info(f"🏆 Winning line: {positions}")

    async def handle_gameover(self, r: ConnReader):
        """Xử lý GAMEOVER."""
        self.is_playing = False
        self.is_my_turn = False
        self.ready_sent = False  # Reset để gửi lại SET_READY ở ván sau

        player_count = r.read_ubyte()
        my_grade = None
        for _ in range(player_count):
            slot_id = r.read_byte()
            grade = r.read_byte()
            earn = r.read_long()
            if slot_id == self.my_slot_id:
                my_grade = grade
            grade_str = {10: "DRAW", 11: "WIN", 12: "LOSE"}.get(grade, str(grade))
            log.info(f"  Slot {slot_id}: grade={grade_str}, earn={earn}")

        if my_grade == 11:
            self.win_count += 1
            log.info(f"🎉 THẮNG!")
        elif my_grade == 12:
            self.lose_count += 1
            log.info(f"😢 THUA!")
        elif my_grade == 10:
            self.draw_count += 1
            log.info(f"🤝 HÒA!")

        match_result = r.read_string()
        log.info(f"  Result: {match_result}")
        log.info(f"📊 Tổng: {self.game_count} ván, {self.win_count} thắng, "
                 f"{self.lose_count} thua, {self.draw_count} hòa")

        # Sau khi ván kết thúc, đợi rồi quick play
        await asyncio.sleep(3)
        log.info("Tìm bàn mới...")
        await self.send(self.build_quick_play_msg())

    async def handle_player_entered(self, r: ConnReader):
        """Xử lý PLAYER_ENTERED."""
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

        self.players[slot_id] = {
            'player_id': player_id,
            'full_name': full_name,
            'is_owner': is_owner,
            'level': level,
        }
        log.info(f"👤 Player entered: slot {slot_id} - {full_name} (lv={level})")

    def _determine_symbols(self):
        """Xác định quân của mình và đối thủ.
        Logic: người đi trước thường có quân đầu tiên trên bàn.
        Slot 0 thường là X (chủ bàn), slot 1 thường là O.
        Nhưng cần xác nhận từ MOVE/SET_TURN sequence.
        """
        # Đếm số quân X và O trên bàn
        x_count = sum(1 for row in self.board.board for cell in row if cell == SYMBOL_X)
        o_count = sum(1 for row in self.board.board for cell in row if cell == SYMBOL_O)

        # Mặc định: slot 0 = X (đi trước), slot 1 = O
        if self.my_slot_id == 0:
            self.my_symbol = SYMBOL_X
            self.opp_symbol = SYMBOL_O
        else:
            self.my_symbol = SYMBOL_O
            self.opp_symbol = SYMBOL_X

        log.info(f"  Symbols: me={'X' if self.my_symbol == SYMBOL_X else 'O'} (slot {self.my_slot_id}), "
                 f"opp={'X' if self.opp_symbol == SYMBOL_X else 'O'}")

    async def make_move(self):
        """Tính toán và gửi nước đi."""
        if not self.is_my_turn or not self.is_playing:
            return

        self.is_my_turn = False

        x, y = self.ai.find_best_move(self.my_symbol, self.opp_symbol)
        pos = self.board.xy_to_pos(x, y)

        log.info(f"🎯 TA ĐÁNH: ({x}, {y}) pos={pos}")
        await self.send(self.build_play_msg(pos))

        # Cập nhật board local (chờ server confirm qua MOVE hoặc SET_TURN)
        self.board.place(x, y, self.my_symbol)
        log.info(f"  Board:\n{self.board.display()}")

    async def ping_loop(self):
        """Gửi PING định kỳ để giữ kết nối."""
        while self.running:
            await asyncio.sleep(self.ping_interval)
            if self.ws and not self.ws.closed:
                try:
                    # Server gửi PING, ta gửi PONG. Nhưng cũng có thể chủ động
                    pass  # PING/PONG handled in message handler
                except Exception:
                    pass

    async def run(self):
        """Chạy bot chính."""
        # HTTP handshake trước
        if not self.http_handshake():
            log.error("HTTP handshake thất bại!")
            return

        if not await self.connect():
            return

        # Gửi LOGIN
        login_msg = self.build_login_msg()
        log.info(f"Đang đăng nhập với nick={self.nickname}, token={self.token}...")
        await self.send(login_msg)

        # Vòng lặp nhận message
        try:
            async for raw in self.ws:
                if isinstance(raw, bytes):
                    await self.handle_message(raw)
                else:
                    log.warning(f"Received non-binary message: {type(raw)}")
        except websockets.exceptions.ConnectionClosed as e:
            log.warning(f"Kết nối đóng: {e}")
        except Exception as e:
            log.error(f"Lỗi: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self.running = False
            log.info("Bot đã dừng.")

    async def run_with_reconnect(self, max_retries=5):
        """Chạy bot với tự động reconnect."""
        retries = 0
        while retries < max_retries:
            try:
                await self.run()
            except Exception as e:
                log.error(f"Lỗi nghiêm trọng: {e}")

            retries += 1
            wait_time = min(5 * retries, 30)
            log.info(f"Đợi {wait_time}s trước khi reconnect (lần {retries}/{max_retries})...")
            await asyncio.sleep(wait_time)
            self.is_playing = False
            self.is_my_turn = False
            self.board.clear()


# ─── Main ───────────────────────────────────────────────────
async def main():
    bot = CaroBot()
    await bot.run_with_reconnect()


if __name__ == "__main__":
    asyncio.run(main())
