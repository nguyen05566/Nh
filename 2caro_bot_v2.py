#!/usr/bin/env python3
"""
Caro Bot v2 for gamevh.net - Thuật toán AI mới
================================================
Đặc điểm AI mới:
- Pattern Recognition Engine: Nhận diện pattern hình ảnh trên bàn cờ
  (open/half/closed five, four, three, two, broken patterns với gap)
- Minimax + Alpha-Beta Pruning depth 3-4
- VCF (Victory by Continuous Four) & VCT (Victory by Continuous Three) detection
- Zobrist Hashing + Transposition Table
- Move ordering thông minh (killer moves, history heuristic)
- Luật Caro Việt Nam: 5 bị chặn 2 đầu KHÔNG thắng, overline 6+ LUÔN thắng

Protocol: WebSocket binary, struct-based parsing (giữ nguyên từ v1)
"""

import asyncio
import struct
import time
import logging
import sys
import re
import random
import copy
from collections import defaultdict
from functools import lru_cache

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
LOGIN_USERNAME = "nguyen05511"
LOGIN_PASSWORD = "nhat123456"
COOKIE_STR = ""

NICKNAME = ""
TOKEN = 0
PLACE_PATH = "Lobby.caro.0"
VERSION = "5.0.2"
GAME_ID = "caro"

HCOUNT = 15
VCOUNT = 19

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
    def __init__(self, buf: bytes):
        self.buf = buf
        self.offset = 0

    def remaining(self) -> int:
        return len(self.buf) - self.offset

    def read_byte(self) -> int:
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


# ─── Binary Protocol Writer ────────────────────────────────
class ConnWriter:
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
        cmd_id = None
        for cid, cname in CMD_NAMES.items():
            if cname == cmd:
                cmd_id = cid
                break
        if cmd_id is not None:
            self.parts.append(struct.pack('>H', cmd_id))
        else:
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
    """Ban co Caro - toi uu cho truy xuat nhanh."""

    def __init__(self, hcount=HCOUNT, vcount=VCOUNT):
        self.hcount = hcount
        self.vcount = vcount
        self.board = [[EMPTY] * hcount for _ in range(vcount)]
        self.my_symbol = SYMBOL_X
        self.opp_symbol = SYMBOL_O
        self.move_history = []
        self._move_set = set()  # Fast lookup for occupied positions

    def clear(self):
        self.board = [[EMPTY] * self.hcount for _ in range(self.vcount)]
        self.move_history = []
        self._move_set = set()

    def resize(self, hcount, vcount):
        self.hcount = hcount
        self.vcount = vcount
        self.clear()

    def pos_to_xy(self, pos: int):
        y = pos // self.hcount
        x = pos % self.hcount
        return x, y

    def xy_to_pos(self, x: int, y: int) -> int:
        return y * self.hcount + x

    def place(self, x: int, y: int, symbol: int):
        if 0 <= x < self.hcount and 0 <= y < self.vcount:
            self.board[y][x] = symbol
            self.move_history.append((x, y, symbol))
            self._move_set.add((x, y))

    def undo(self, x: int, y: int):
        """Undo a move - used by minimax."""
        if 0 <= x < self.hcount and 0 <= y < self.vcount:
            self.board[y][x] = EMPTY
            if self.move_history and self.move_history[-1][:2] == (x, y):
                self.move_history.pop()
            self._move_set.discard((x, y))

    def get(self, x: int, y: int) -> int:
        if 0 <= x < self.hcount and 0 <= y < self.vcount:
            return self.board[y][x]
        return EMPTY

    def fill_from_rle(self, board_data: list):
        self.clear()
        pos = 0
        for unsigned_val in board_data:
            if unsigned_val > 127:
                signed_val = unsigned_val - 256
            else:
                signed_val = unsigned_val
            if signed_val >= 0:
                y = pos // self.hcount
                x = pos % self.hcount
                if 0 <= x < self.hcount and 0 <= y < self.vcount:
                    self.board[y][x] = signed_val
                    self._move_set.add((x, y))
                pos += 1
            else:
                pos += (-signed_val)

    def is_empty(self, x: int, y: int) -> bool:
        return self.get(x, y) == EMPTY

    def get_neighbors(self, radius=2):
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
        lines = []
        sym = {EMPTY: '.', SYMBOL_O: 'O', SYMBOL_X: 'X'}
        header = "   " + "".join(f"{i:2d}" for i in range(self.hcount))
        lines.append(header)
        for y in range(self.vcount):
            row = f"{y:2d} " + "".join(f" {sym.get(self.board[y][x], '?')}" for x in range(self.hcount))
            lines.append(row)
        return "\n".join(lines)


# ─── Pattern Recognition Engine ────────────────────────────
# Pattern types cho nhận diện hình ảnh
PATTERN_FIVE_OPEN = 'FIVE_OPEN'           # 5 quân có ít nhất 1 đầu mở = THẮNG (luật VN)
PATTERN_FIVE_BLOCKED = 'FIVE_BLOCKED'      # 5 quân bị chặn cả 2 đầu = KHÔNG thắng (luật VN)
PATTERN_OVERLINE = 'OVERLINE'              # 6+ quân liên tiếp = THẮNG (miễn nhiễm)
PATTERN_OPEN_FOUR = 'OPEN_FOUR'            # _XXXX_ = chắc chắn thắng
PATTERN_HALF_FOUR = 'HALF_FOUR'            # OXXXX_ hoặc _XXXXO = 1 nước thắng
PATTERN_DOUBLE_FOUR = 'DOUBLE_FOUR'        # 2 half-four cùng lúc = chắc chắn thắng
PATTERN_OPEN_THREE = 'OPEN_THREE'          # __XXX__ = có thể thành open four
PATTERN_HALF_THREE = 'HALF_THREE'          # _XXX_ bị chặn 1 đầu
PATTERN_BROKEN_THREE = 'BROKEN_THREE'      # X_XX_ hoặc XX_X_ = 3 quân có gap
PATTERN_OPEN_TWO = 'OPEN_TWO'              # __XX__ = tiềm năng phát triển
PATTERN_HALF_TWO = 'HALF_TWO'              # _XX_ bị chặn 1 đầu

# Score cho từng pattern
PATTERN_SCORES = {
    PATTERN_FIVE_OPEN: 10000000,
    PATTERN_OVERLINE: 10000000,
    PATTERN_FIVE_BLOCKED: 50,           # Không thắng - giá trị thấp
    PATTERN_OPEN_FOUR: 5000000,
    PATTERN_DOUBLE_FOUR: 5000000,
    PATTERN_HALF_FOUR: 500000,
    PATTERN_OPEN_THREE: 500000,
    PATTERN_HALF_THREE: 50000,
    PATTERN_BROKEN_THREE: 80000,
    PATTERN_OPEN_TWO: 50000,
    PATTERN_HALF_TWO: 5000,
}

# 4 hướng duyệt
DIRECTIONS = [(1, 0), (0, 1), (1, 1), (1, -1)]


class PatternScanner:
    """Quét bàn cờ để nhận diện các pattern hình ảnh - như mắt người nhìn."""

    @staticmethod
    def scan_line(board: CaroBoard, x: int, y: int, dx: int, dy: int, symbol: int, max_len=9):
        """Quét 1 dòng từ (x,y) theo hướng (dx,dy), trả về danh sách các ô.
        Kết quả: list of tuples (cell_value, relative_pos)
        Quét tối đa max_len ô theo hướng thuận + ngược.
        """
        cells = []
        # Quét ngược (backward) từ -4 đến -1
        back_cells = []
        for i in range(4, 0, -1):
            bx, by = x - dx * i, y - dy * i
            if 0 <= bx < board.hcount and 0 <= by < board.vcount:
                back_cells.append(board.get(bx, by))
            else:
                back_cells.append(None)  # Wall = blocked
        # Ô hiện tại
        back_cells.append(board.get(x, y))
        # Quét thuận (forward) từ +1 đến +4
        for i in range(1, 5):
            fx, fy = x + dx * i, y + dy * i
            if 0 <= fx < board.hcount and 0 <= fy < board.vcount:
                back_cells.append(board.get(fx, fy))
            else:
                back_cells.append(None)
        return back_cells

    @staticmethod
    def analyze_line_pattern(line_cells: list, symbol: int, opp: int):
        """Phân tích pattern từ 1 dòng 9 ô (4 trước + center + 4 sau).
        Trả về: (pattern_type, count, open_ends) hoặc None nếu không có pattern.

        Phân tích như nhận diện hình ảnh:
        - Đếm số quân liên tiếp từ center ra 2 phía
        - Đếm số đầu mở (empty/wall)
        - Phát hiện gap patterns (quân bị ngăn cách bởi 1 ô trống)
        """
        center = 4  # Vị trí center trong mảng 9 ô

        # Đếm quân liên tiếp từ center ra 2 phía
        count = 1  # Tính cả center

        # Đếm về bên trái (backward)
        backward_count = 0
        backward_open = False
        for i in range(center - 1, -1, -1):
            cell = line_cells[i]
            if cell == symbol:
                backward_count += 1
            elif cell == EMPTY:
                backward_open = True
                break
            else:
                # None (wall) hoặc opp -> blocked
                break

        # Đếm về bên phải (forward)
        forward_count = 0
        forward_open = False
        for i in range(center + 1, len(line_cells)):
            cell = line_cells[i]
            if cell == symbol:
                forward_count += 1
            elif cell == EMPTY:
                forward_open = True
                break
            else:
                break

        count = 1 + backward_count + forward_count
        open_ends = int(backward_open) + int(forward_open)

        # Kiểm tra overline (6+ quân liên tiếp)
        if count >= 6:
            return PATTERN_OVERLINE, count, open_ends

        # 5 quân liên tiếp - áp dụng luật VN
        if count == 5:
            if open_ends >= 1:
                return PATTERN_FIVE_OPEN, count, open_ends
            else:
                return PATTERN_FIVE_BLOCKED, count, open_ends

        # Kiểm tra broken/gap patterns (X_XX, XX_X, X_X_X, etc.)
        # Scan xa hơn để tìm gap patterns
        broken_info = PatternScanner._detect_gap_pattern(line_cells, center, symbol, opp)

        if count == 4:
            if open_ends >= 2:
                return PATTERN_OPEN_FOUR, count, open_ends
            elif open_ends == 1:
                return PATTERN_HALF_FOUR, count, open_ends
            else:
                return None, count, 0  # Closed four = vô dụng

        if count == 3:
            # Kiểm tra gap patterns có thể tạo thành 4
            if broken_info and broken_info[0] in ('gap_to_four', 'gap_extend'):
                return PATTERN_BROKEN_THREE, count, open_ends
            if open_ends >= 2:
                return PATTERN_OPEN_THREE, count, open_ends
            elif open_ends == 1:
                return PATTERN_HALF_THREE, count, open_ends

        if count == 2:
            if broken_info and broken_info[0] == 'gap_extend':
                return PATTERN_BROKEN_THREE, count, open_ends
            if open_ends >= 2:
                return PATTERN_OPEN_TWO, count, open_ends
            elif open_ends == 1:
                return PATTERN_HALF_TWO, count, open_ends

        return None, count, open_ends

    @staticmethod
    def _detect_gap_pattern(line_cells: list, center: int, symbol: int, opp: int):
        """Phát hiện gap patterns: X_XX, XX_X, X_X, XX__X, etc.
        Đây là pattern có 1 ô trống xen giữa, khi填 ô đó sẽ tạo thành dải dài hơn.
        """
        # Tìm tất cả vị trí của symbol trong line_cells
        symbol_positions = []
        for i, cell in enumerate(line_cells):
            if cell == symbol:
                symbol_positions.append(i)

        if len(symbol_positions) < 2:
            return None

        # Tìm gap (1 ô trống giữa 2 quân cùng loại)
        for i in range(len(symbol_positions) - 1):
            gap = symbol_positions[i + 1] - symbol_positions[i]
            if gap == 2:  # Có 1 ô trống giữa 2 quân
                gap_pos = symbol_positions[i] + 1
                # Kiểm tra ô gap có phải empty không
                if line_cells[gap_pos] == EMPTY:
                    # Đếm tổng quân nếu điền gap
                    total_with_gap = 0
                    # Đếm liên tục từ gap_pos
                    for j in range(gap_pos - 1, -1, -1):
                        if line_cells[j] == symbol:
                            total_with_gap += 1
                        else:
                            break
                    total_with_gap += 1  # gap position
                    for j in range(gap_pos + 1, len(line_cells)):
                        if line_cells[j] == symbol:
                            total_with_gap += 1
                        else:
                            break
                    if total_with_gap >= 4:
                        return ('gap_to_four', gap_pos, total_with_gap)
                    elif total_with_gap >= 3:
                        return ('gap_extend', gap_pos, total_with_gap)

        return None

    @staticmethod
    def scan_all_patterns(board: CaroBoard, symbol: int, opp: int):
        """Quét toàn bộ bàn cờ để tìm tất cả patterns cho symbol.
        Trả về: dict pattern_type -> count
        """
        patterns = defaultdict(int)
        checked = set()

        for y in range(board.vcount):
            for x in range(board.hcount):
                if board.get(x, y) != symbol:
                    continue
                for dx, dy in DIRECTIONS:
                    # Chỉ quét từ đầu dải (để không đếm trùng)
                    px, py = x - dx, y - dy
                    if 0 <= px < board.hcount and 0 <= py < board.vcount:
                        if board.get(px, py) == symbol:
                            continue  # Không phải đầu dải
                    line_cells = PatternScanner.scan_line(board, x, y, dx, dy, symbol)
                    pat_type, count, open_ends = PatternScanner.analyze_line_pattern(
                        line_cells, symbol, opp
                    )
                    if pat_type:
                        patterns[pat_type] += 1

        return patterns

    @staticmethod
    def scan_patterns_at(board: CaroBoard, x: int, y: int, symbol: int, opp: int):
        """Quét patterns tại vị trí (x,y) cho symbol (giả sử đã đặt quân).
        Trả về: dict pattern_type -> count + danh sách patterns
        """
        patterns = defaultdict(int)
        pattern_list = []

        for dx, dy in DIRECTIONS:
            line_cells = PatternScanner.scan_line(board, x, y, dx, dy, symbol)
            pat_type, count, open_ends = PatternScanner.analyze_line_pattern(
                line_cells, symbol, opp
            )
            if pat_type:
                patterns[pat_type] += 1
                pattern_list.append((pat_type, count, open_ends, (dx, dy)))

        return patterns, pattern_list


class ZobristHash:
    """Zobrist hashing cho transposition table."""

    def __init__(self, hcount=HCOUNT, vcount=VCOUNT):
        random.seed(42)  # Deterministic
        self.hcount = hcount
        self.vcount = vcount
        # 2 bảng: [symbol][y][x] -> random 64-bit value
        self.table = [[[random.getrandbits(64) for _ in range(hcount)]
                       for _ in range(vcount)]
                      for _ in range(2)]  # 0=O, 1=X
        self.hash = 0

    def init(self, board: CaroBoard):
        self.hash = 0
        for y in range(board.vcount):
            for x in range(board.hcount):
                cell = board.get(x, y)
                if cell in (SYMBOL_O, SYMBOL_X):
                    self.hash ^= self.table[cell][y][x]

    def place(self, x: int, y: int, symbol: int):
        self.hash ^= self.table[symbol][y][x]

    def undo(self, x: int, y: int, symbol: int):
        self.hash ^= self.table[symbol][y][x]


# ─── Caro AI v2 - Pattern Recognition + Minimax ───────────
class CaroAI:
    """AI đánh Caro v2:
    - Pattern Recognition: Nhận diện hình ảnh pattern trên bàn cờ
    - Minimax + Alpha-Beta depth 3-4
    - VCF/VCT detection: Tìm chuỗi ép buộc thắng
    - Transposition Table với Zobrist hashing
    - Move ordering thông minh
    - Luật Caro Việt Nam đầy đủ
    """

    # Điểm số cho evaluation
    SCORE_FIVE_OPEN = 10000000
    SCORE_OVERLINE = 10000000
    SCORE_OPEN_FOUR = 5000000
    SCORE_HALF_FOUR = 500000
    SCORE_OPEN_THREE = 500000
    SCORE_BROKEN_THREE = 80000
    SCORE_HALF_THREE = 50000
    SCORE_OPEN_TWO = 50000
    SCORE_HALF_TWO = 5000
    SCORE_FIVE_BLOCKED = 50

    # Combo bonuses
    DOUBLE_FOUR_BONUS = 5000000
    FOUR_THREE_BONUS = 3000000
    DOUBLE_THREE_BONUS = 500000

    def __init__(self, board: CaroBoard):
        self.board = board
        self.zobrist = ZobristHash(board.hcount, board.vcount)
        self.tt = {}  # Transposition table: hash -> (depth, score, flag)
        self.nodes_searched = 0
        self.tt_hits = 0
        self.move_scores = defaultdict(int)  # History heuristic

    def check_win_at(self, x: int, y: int, symbol: int) -> bool:
        """Kiểm tra thắng theo luật Caro Việt Nam tại (x,y)."""
        board = self.board
        for dx, dy in DIRECTIONS:
            count = 1
            forward_open = False
            backward_open = False

            # Đếm thuận
            i = 1
            while True:
                nx, ny = x + dx * i, y + dy * i
                if 0 <= nx < board.hcount and 0 <= ny < board.vcount:
                    if board.get(nx, ny) == symbol:
                        count += 1
                        i += 1
                    elif board.get(nx, ny) == EMPTY:
                        forward_open = True
                        break
                    else:
                        break
                else:
                    break

            # Đếm ngược
            i = 1
            while True:
                nx, ny = x - dx * i, y - dy * i
                if 0 <= nx < board.hcount and 0 <= ny < board.vcount:
                    if board.get(nx, ny) == symbol:
                        count += 1
                        i += 1
                    elif board.get(nx, ny) == EMPTY:
                        backward_open = True
                        break
                    else:
                        break
                else:
                    break

            # Luật Caro Việt Nam
            if count >= 6:
                return True  # Overline luôn thắng
            if count == 5 and (forward_open or backward_open):
                return True  # 5 quân có ít nhất 1 đầu mở
            # count == 5 và cả 2 đầu bị chặn -> KHÔNG thắng (luật VN)
        return False

    def find_winning_move(self, symbol: int):
        """Tìm nước thắng ngay cho symbol."""
        board = self.board
        candidates = self._get_candidate_moves_fast()
        for x, y in candidates:
            board.place(x, y, symbol)
            if self.check_win_at(x, y, symbol):
                board.undo(x, y)
                return (x, y)
            board.undo(x, y)
        return None

    def _get_candidate_moves_fast(self, radius=2):
        """Lấy candidate moves nhanh, sắp xếp theo history heuristic."""
        board = self.board
        neighbors = board.get_neighbors(radius=radius)
        if not neighbors:
            cx = board.hcount // 2
            cy = board.vcount // 2
            return [(cx, cy)]
        # Sắp xếp theo history heuristic score
        neighbors.sort(key=lambda m: self.move_scores.get(m, 0), reverse=True)
        return neighbors

    def evaluate_move_quick(self, x: int, y: int, my_sym: int, opp_sym: int) -> int:
        """Đánh giá nhanh 1 nước đi - dùng cho move ordering."""
        score = 0
        board = self.board

        # Kiểm tra thắng/chặn thắng
        board.place(x, y, my_sym)
        if self.check_win_at(x, y, my_sym):
            board.undo(x, y)
            return 100000000
        board.undo(x, y)

        board.place(x, y, opp_sym)
        if self.check_win_at(x, y, opp_sym):
            board.undo(x, y)
            return 50000000
        board.undo(x, y)

        # Pattern scanning nhanh
        board.place(x, y, my_sym)
        attack_patterns, _ = PatternScanner.scan_patterns_at(board, x, y, my_sym, opp_sym)
        board.undo(x, y)

        board.place(x, y, opp_sym)
        defense_patterns, _ = PatternScanner.scan_patterns_at(board, x, y, opp_sym, my_sym)
        board.undo(x, y)

        # Attack score
        for pat_type, cnt in attack_patterns.items():
            pat_score = PATTERN_SCORES.get(pat_type, 0)
            score += pat_score * cnt

        # Defense score (90% weight - phòng thủ quan trọng)
        for pat_type, cnt in defense_patterns.items():
            pat_score = PATTERN_SCORES.get(pat_type, 0)
            score += int(pat_score * 0.9) * cnt

        # Center bonus
        cx, cy = board.hcount // 2, board.vcount // 2
        dist = abs(x - cx) + abs(y - cy)
        score += max(0, 30 - dist * 3)

        return score

    def evaluate_position(self, my_sym: int, opp_sym: int) -> int:
        """Đánh giá toàn bộ bàn cờ bằng pattern recognition."""
        board = self.board
        score = 0

        # Scan patterns cho mình
        my_patterns = PatternScanner.scan_all_patterns(board, my_sym, opp_sym)
        # Scan patterns cho đối thủ
        opp_patterns = PatternScanner.scan_all_patterns(board, opp_sym, my_sym)

        # Tính điểm attack
        for pat_type, cnt in my_patterns.items():
            base_score = PATTERN_SCORES.get(pat_type, 0)
            score += base_score * cnt

        # Tính điểm defense (âm)
        for pat_type, cnt in opp_patterns.items():
            base_score = PATTERN_SCORES.get(pat_type, 0)
            score -= int(base_score * 0.95) * cnt

        # Combo detection
        my_half_fours = my_patterns.get(PATTERN_HALF_FOUR, 0)
        my_open_threes = my_patterns.get(PATTERN_OPEN_THREE, 0)
        my_broken_threes = my_patterns.get(PATTERN_BROKEN_THREE, 0)

        opp_half_fours = opp_patterns.get(PATTERN_HALF_FOUR, 0)
        opp_open_threes = opp_patterns.get(PATTERN_OPEN_THREE, 0)
        opp_broken_threes = opp_patterns.get(PATTERN_BROKEN_THREE, 0)

        # Double four (2 half-four = chắc chắn thắng)
        if my_half_fours >= 2:
            score += self.DOUBLE_FOUR_BONUS
        if opp_half_fours >= 2:
            score -= self.DOUBLE_FOUR_BONUS

        # Four + Three (1 half-four + 1 open-three = chắc chắn thắng)
        if my_half_fours >= 1 and (my_open_threes + my_broken_threes) >= 1:
            score += self.FOUR_THREE_BONUS
        if opp_half_fours >= 1 and (opp_open_threes + opp_broken_threes) >= 1:
            score -= self.FOUR_THREE_BONUS

        # Double three (2 open-three)
        if my_open_threes >= 2:
            score += self.DOUBLE_THREE_BONUS
        if opp_open_threes >= 2:
            score -= self.DOUBLE_THREE_BONUS

        # Center bonus
        cx, cy = board.hcount // 2, board.vcount // 2
        for y in range(board.vcount):
            for x in range(board.hcount):
                cell = board.get(x, y)
                if cell == my_sym:
                    dist = abs(x - cx) + abs(y - cy)
                    score += max(0, 15 - dist)
                elif cell == opp_sym:
                    dist = abs(x - cx) + abs(y - cy)
                    score -= max(0, 15 - dist)

        return score

    def minimax(self, depth: int, alpha: int, beta: int, is_maximizing: bool,
                my_sym: int, opp_sym: int, last_move=None) -> int:
        """Minimax với Alpha-Beta pruning + Transposition Table."""
        self.nodes_searched += 1

        # Kiểm tra thắng/thua tại last_move
        if last_move:
            lx, ly, lsym = last_move
            if self.check_win_at(lx, ly, lsym):
                if lsym == my_sym:
                    return self.SCORE_FIVE_OPEN - (100 - depth)  # Thắng sớm hơn = tốt hơn
                else:
                    return -self.SCORE_FIVE_OPEN + (100 - depth)

        # Leaf node
        if depth <= 0:
            return self.evaluate_position(my_sym, opp_sym)

        # Transposition table lookup
        tt_key = self.zobrist.hash
        tt_entry = self.tt.get(tt_key)
        if tt_entry and tt_entry[0] >= depth:
            flag = tt_entry[2]
            if flag == 'exact':
                self.tt_hits += 1
                return tt_entry[1]
            elif flag == 'lower' and tt_entry[1] > alpha:
                alpha = tt_entry[1]
            elif flag == 'upper' and tt_entry[1] < beta:
                beta = tt_entry[1]
            if alpha >= beta:
                self.tt_hits += 1
                return tt_entry[1]

        # Quét nước thắng ngay (null-move check)
        current_sym = my_sym if is_maximizing else opp_sym
        other_sym = opp_sym if is_maximizing else my_sym

        # Nếu đang maximizing, kiểm tra mình có thể thắng ngay không
        win_move = self.find_winning_move(current_sym)
        if win_move:
            if is_maximizing:
                return self.SCORE_FIVE_OPEN - (100 - depth)
            else:
                return -self.SCORE_FIVE_OPEN + (100 - depth)

        # Lấy candidates và sắp xếp
        candidates = self._get_candidate_moves_fast(radius=2)
        # Giới hạn số candidates theo depth
        max_candidates = min(len(candidates), 15 if depth >= 3 else 12 if depth >= 2 else 10)
        candidates = candidates[:max_candidates]

        # Move ordering: đánh giá nhanh + history heuristic
        scored_candidates = []
        for x, y in candidates:
            quick_score = self.evaluate_move_quick(x, y, my_sym, opp_sym)
            hist_score = self.move_scores.get((x, y), 0)
            scored_candidates.append((quick_score + hist_score, x, y))
        scored_candidates.sort(reverse=True)
        candidates = [(x, y) for _, x, y in scored_candidates[:max_candidates]]

        if is_maximizing:
            max_eval = -999999999
            best_move = None
            for x, y in candidates:
                self.board.place(x, y, current_sym)
                self.zobrist.place(x, y, current_sym)
                eval_score = self.minimax(depth - 1, alpha, beta, False,
                                          my_sym, opp_sym, (x, y, current_sym))
                self.board.undo(x, y)
                self.zobrist.undo(x, y, current_sym)

                if eval_score > max_eval:
                    max_eval = eval_score
                    best_move = (x, y)
                alpha = max(alpha, eval_score)
                if beta <= alpha:
                    # Killer move bonus
                    if best_move:
                        self.move_scores[best_move] += depth * depth
                    break

            # Store in TT
            self.tt[tt_key] = (depth, max_eval, 'exact')
            return max_eval
        else:
            min_eval = 999999999
            best_move = None
            for x, y in candidates:
                self.board.place(x, y, current_sym)
                self.zobrist.place(x, y, current_sym)
                eval_score = self.minimax(depth - 1, alpha, beta, True,
                                          my_sym, opp_sym, (x, y, current_sym))
                self.board.undo(x, y)
                self.zobrist.undo(x, y, current_sym)

                if eval_score < min_eval:
                    min_eval = eval_score
                    best_move = (x, y)
                beta = min(beta, eval_score)
                if beta <= alpha:
                    if best_move:
                        self.move_scores[best_move] += depth * depth
                    break

            self.tt[tt_key] = (depth, min_eval, 'exact')
            return min_eval

    def detect_vcf(self, symbol: int, opp: int, max_depth=10):
        """VCF (Victory by Continuous Four) detection.
        Tìm chuỗi liên tục tạo 4 để ép buộc đối thủ phải chặn,
        đến khi tạo được 5 không thể chặn.
        """
        board = self.board

        def vcf_recursive(depth: int, is_attacker: bool) -> bool:
            if depth <= 0:
                return False

            if is_attacker:
                # Tìm nước tạo four (half-four hoặc open-four)
                candidates = self._get_candidate_moves_fast(radius=2)
                for x, y in candidates[:12]:
                    board.place(x, y, symbol)
                    # Kiểm tra thắng
                    if self.check_win_at(x, y, symbol):
                        board.undo(x, y)
                        return True
                    # Kiểm tra tạo four
                    patterns, _ = PatternScanner.scan_patterns_at(board, x, y, symbol, opp)
                    if (patterns.get(PATTERN_HALF_FOUR, 0) > 0 or
                            patterns.get(PATTERN_OPEN_FOUR, 0) > 0):
                        # Đối thủ phải chặn
                        if vcf_recursive(depth - 1, False):
                            board.undo(x, y)
                            return True
                    board.undo(x, y)
                return False
            else:
                # Defender: phải chặn four - tìm nước chặn
                block_move = self.find_winning_move(symbol)
                if block_move is None:
                    # Không cần chặn (hoặc không tìm thấy) -> thử tất cả defenses
                    return False
                # Chặn nước đó
                bx, by = block_move
                board.place(bx, by, opp)
                result = vcf_recursive(depth - 1, True)
                board.undo(bx, by)
                return result

        return vcf_recursive(max_depth, True)

    def detect_vct(self, symbol: int, opp: int, max_depth=8):
        """VCT (Victory by Continuous Three) detection.
        Tìm chuỗi liên tục tạo three (open-three) để ép buộc đối thủ chặn.
        """
        board = self.board

        def vct_recursive(depth: int, is_attacker: bool) -> bool:
            if depth <= 0:
                return False

            if is_attacker:
                candidates = self._get_candidate_moves_fast(radius=2)
                for x, y in candidates[:10]:
                    board.place(x, y, symbol)
                    if self.check_win_at(x, y, symbol):
                        board.undo(x, y)
                        return True
                    patterns, _ = PatternScanner.scan_patterns_at(board, x, y, symbol, opp)
                    # Tạo open-three hoặc half-four
                    if (patterns.get(PATTERN_OPEN_THREE, 0) > 0 or
                            patterns.get(PATTERN_BROKEN_THREE, 0) > 0 or
                            patterns.get(PATTERN_HALF_FOUR, 0) > 0):
                        if vct_recursive(depth - 1, False):
                            board.undo(x, y)
                            return True
                    board.undo(x, y)
                return False
            else:
                # Defender: tìm nước chặn threat lớn nhất
                # Đơn giản: tìm nước mà nếu symbol đánh sẽ thắng hoặc tạo four
                block_move = self.find_winning_move(symbol)
                if block_move:
                    bx, by = block_move
                    board.place(bx, by, opp)
                    result = vct_recursive(depth - 1, True)
                    board.undo(bx, by)
                    return result
                return False

        return vct_recursive(max_depth, True)

    def find_best_move(self, my_sym: int, opp_sym: int):
        """Tìm nước đi tốt nhất với thuật toán mới."""
        board = self.board
        self.nodes_searched = 0
        self.tt_hits = 0

        # 1. Kiểm tra nước thắng ngay
        win_move = self.find_winning_move(my_sym)
        if win_move:
            log.info(f">>> NUOC THANG NGAY: ({win_move[0]}, {win_move[1]})")
            return win_move

        # 2. Chặn nước thắng của đối thủ
        block_move = self.find_winning_move(opp_sym)
        if block_move:
            log.info(f">>> CHAN NUOC THANG DOI THU: ({block_move[0]}, {block_move[1]})")
            return block_move

        # 3. VCF detection - tìm chuỗi ép buộc thắng
        candidates = self._get_candidate_moves_fast(radius=2)
        for x, y in candidates[:15]:
            board.place(x, y, my_sym)
            if self.detect_vcf(my_sym, opp_sym, max_depth=8):
                board.undo(x, y)
                log.info(f">>> VCF detected: ({x}, {y})")
                return (x, y)
            board.undo(x, y)

        # 4. Kiểm tra VCF của đối thủ (phải chặn)
        for x, y in candidates[:15]:
            board.place(x, y, opp_sym)
            if self.detect_vcf(opp_sym, my_sym, max_depth=8):
                board.undo(x, y)
                # Nước này đối thủ có thể tạo VCF -> phải chặn/chiếm
                log.info(f">>> CHAN VCF doi thu: ({x}, {y})")
                # Không return ngay - vẫn dùng minimax nhưng ưu tiên nước này
                break
            board.undo(x, y)

        # 5. Minimax với iterative deepening
        # Khởi tạo Zobrist
        self.zobrist = ZobristHash(board.hcount, board.vcount)
        self.zobrist.init(board)

        best_move = None
        best_score = -999999999

        # Đánh giá nhanh tất cả candidates để sắp xếp
        scored_candidates = []
        for x, y in candidates:
            quick_score = self.evaluate_move_quick(x, y, my_sym, opp_sym)
            scored_candidates.append((quick_score, x, y))
        scored_candidates.sort(reverse=True)

        # Giới hạn candidates
        top_candidates = [(x, y) for _, x, y in scored_candidates[:15]]

        # Iterative deepening từ depth 1 đến 3
        for current_depth in range(1, 4):
            if current_depth == 1:
                # Depth 1: chỉ dùng quick evaluation
                if scored_candidates:
                    best_score, best_x, best_y = scored_candidates[0]
                    best_move = (best_x, best_y)
                continue

            # Depth 2+: minimax
            depth_best_score = -999999999
            depth_best_move = best_move

            for x, y in top_candidates[:12]:
                board.place(x, y, my_sym)
                self.zobrist.place(x, y, my_sym)
                score = self.minimax(current_depth - 1, -999999999, 999999999,
                                     False, my_sym, opp_sym, (x, y, my_sym))
                self.board.undo(x, y)
                self.zobrist.undo(x, y, my_sym)

                if score > depth_best_score:
                    depth_best_score = score
                    depth_best_move = (x, y)

            if depth_best_move:
                best_move = depth_best_move
                best_score = depth_best_score

        # 6. Nếu minimax không tìm được tốt hơn, dùng quick evaluation
        if best_move is None and top_candidates:
            best_move = top_candidates[0]

        # 7. Fallback: center
        if best_move is None:
            best_move = (board.hcount // 2, board.vcount // 2)

        # Log top 5 candidates
        log.info(f">>> AI v2 - Nodes: {self.nodes_searched}, TT hits: {self.tt_hits}")
        for i, (score, x, y) in enumerate(scored_candidates[:5]):
            marker = " <<<<" if (x, y) == best_move else ""
            log.info(f"  Top {i+1}: ({x},{y}) score={score}{marker}")

        return best_move


# ─── Game Client ────────────────────────────────────────────
class CaroBot:
    """Bot choi Caro tren gamevh.net - AI v2."""

    def __init__(self):
        self.ws = None
        self.board = CaroBoard()
        self.ai = CaroAI(self.board)
        self.my_slot_id = -1
        self.is_my_turn = False
        self.is_playing = False
        self.my_symbol = SYMBOL_X
        self.opp_symbol = SYMBOL_O
        self.players = {}
        self.login_cookie = ""
        self.last_ping = 0
        self.ping_interval = 7.5
        self.game_count = 0
        self.win_count = 0
        self.lose_count = 0
        self.draw_count = 0
        self.running = True
        self.in_table = False
        self.ready_sent = False
        self.mode_set = False
        self.last_activity = time.time()
        self.idle_timeout = 45
        self.nickname = ""
        self.token = 0
        self.cookie_header = COOKIE_STR
        self.place_path = PLACE_PATH
        self.start_time = None  # Thời gian bắt đầu chạy bot

    def http_handshake(self) -> bool:
        """Dang nhap bang username/password."""
        log.info("Dang nhap bang username/password...")
        try:
            s = requests.Session()
            ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

            s.get('https://gamevh.net/login.jsp', timeout=10, headers={'User-Agent': ua})

            log.info(f"Dang nhap: user={LOGIN_USERNAME}")
            r = s.post('https://gamevh.net:443/login.jsp', data={
                'redirect': '/',
                'USER_NAME': LOGIN_USERNAME,
                'PASSWORD': LOGIN_PASSWORD,
                'AUTO_LOGIN': 'on',
                'LOGIN': 'Đăng nhập'
            }, timeout=10, headers={
                'User-Agent': ua,
                'Referer': 'https://gamevh.net/login.jsp',
                'Content-Type': 'application/x-www-form-urlencoded'
            })
            log.info(f"Login response: status={r.status_code}, url={r.url}")

            if 'login.jsp' in r.url:
                log.error("Dang nhap that bai! Sai ten/mat khau?")
                return False

            log.info("Dang nhap HTTP thanh cong!")

            r2 = s.get(GAME_URL, timeout=10, headers={'User-Agent': ua})
            log.info(f"Game page status: {r2.status_code}")

            self.cookie_header = '; '.join(f'{k}={v}' for k, v in s.cookies.items())
            log.info(f"Cookies: {self.cookie_header[:60]}...")

            html = r2.text

            m = re.search(r'var\s+token\s*=\s*(-?\d+)', html)
            if m:
                self.token = int(m.group(1))
                log.info(f"Token: {self.token}")
            else:
                log.error("Khong tim thay token!")
                return False

            m = re.search(r"var\s+currentPlayerNickName\s*=\s*'([^']+)'", html)
            if m:
                self.nickname = m.group(1)
                log.info(f"Nickname: {self.nickname}")
            else:
                log.error("Khong tim thay nickname!")
                return False

            m = re.search(r'var\s+placePath\s*=\s*"([^"]+)"', html)
            if m:
                self.place_path = m.group(1)
                log.info(f"PlacePath: {self.place_path}")

            return True

        except Exception as e:
            log.error(f"Loi HTTP handshake: {e}")
            return False

    async def connect(self):
        headers = {
            "Cookie": self.cookie_header,
            "Origin": "https://gamevh.net",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        log.info(f"Dang ket noi den {WS_URL}...")
        try:
            self.ws = await websockets.connect(
                WS_URL,
                additional_headers=headers,
                max_size=2**20,
                ping_interval=None,
            )
            log.info("Da ket noi WebSocket!")
            return True
        except Exception as e:
            log.error(f"Loi ket noi: {e}")
            return False

    async def send(self, data: bytes):
        if self.ws:
            try:
                await self.ws.send(data)
            except Exception as e:
                log.error(f"Loi gui: {e}")

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

    async def handle_message(self, raw: bytes):
        if log.isEnabledFor(logging.DEBUG):
            hex_str = raw.hex()
            log.debug(f"RAW ({len(raw)} bytes): {hex_str[:200]}...")
        r = ConnReader(raw)
        cmd = r.read_command()
        log.info(f"{cmd} (remaining: {r.remaining()})")
        if cmd != "PING":
            self.last_activity = time.time()

        try:
            if cmd == "PING":
                await self.send(self.build_pong_msg())

            elif cmd == "LOGIN":
                await self.handle_login(r)

            elif cmd == "ENTER_PLACE":
                await self.handle_enter_place(r)

            elif cmd == "SET_CLIENT_MODE":
                slot = r.read_byte()
                log.info(f"SET_CLIENT_MODE: slot={slot}")

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
                # Reset in_table nếu mình bị kick
                if slot_id == self.my_slot_id:
                    self.in_table = False
                    self.is_playing = False
                elif slot_id < 2 and self.is_playing:
                    # Slot 0 hoặc 1 là người chơi thực sự, slot 2+ là khán giả
                    log.info(f"Doi thu slot {slot_id} roi ban")
                    self.is_playing = False
                    self.is_my_turn = False
                    self.ready_sent = False

            elif cmd == "ALERT":
                msg = r.read_string()
                log.warning(f"ALERT: {msg}")

            elif cmd == "BROADCAST":
                msg = r.read_string()
                log.info(f"BROADCAST: {msg}")

            elif cmd == "RIBBON_MESSAGE":
                msg = r.read_ascii()
                log.info(f"Ribbon: {msg}")

            elif cmd == "CONFIG":
                log.info("CONFIG received")

            elif cmd == "BALANCE_CHANGED":
                currency = r.read_byte()
                balance = r.read_long()
                log.info(f"Balance changed: {balance} ({'chip' if currency == 0 else 'star'})")

            elif cmd == "OWNER_CHANGED":
                slot_id = r.read_byte()
                log.info(f"Owner changed: slot {slot_id}")

            elif cmd == "ENTER_STATE":
                state = r.read_ascii()
                log.info(f"Enter state: {state}")

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
                log.info(f"Invite from: {inviter}")

            elif cmd == "QUICK_PLAY":
                await self.handle_quick_play(r)

            elif cmd == "CMD_345":
                slot_id = r.read_byte()
                mode = r.read_byte()
                log.info(f"CLIENT_MODE_CHANGED: slot={slot_id}, mode={mode}")

            else:
                log.debug(f"Unhandled: {cmd}")

        except Exception as e:
            log.error(f"Loi xu ly {cmd}: {e}")
            import traceback
            traceback.print_exc()

    async def handle_login(self, r: ConnReader):
        status = r.read_byte()
        log.info(f"LOGIN status={status}, remaining={r.remaining()}")
        if status == 0:
            path = r.read_string()
            log.info(f"LOGIN path={path}")
            if path == "REFRESH":
                log.info("Server yeu cau REFRESH - tiep tuc...")
                await self.send(self.build_enter_place_msg(self.place_path, "", 1))
                return
            if r.remaining() > 0:
                self.login_cookie = r.read_ascii()
            if r.remaining() > 0:
                password = r.read_string()
            if r.remaining() > 0:
                material = r.read_ascii()
            log.info(f"LOGIN thanh cong! path={path}")
            await self.send(self.build_enter_place_msg(self.place_path, "", 1))
        else:
            if r.remaining() > 0:
                error_msg = r.read_string()
                log.error(f"LOGIN that bai: status={status}, msg={error_msg}")
            else:
                log.error(f"LOGIN that bai: status={status}")

    async def handle_quick_play(self, r: ConnReader):
        try:
            status = r.read_byte()
            if status != 0:
                error_msg = r.read_string() if r.remaining() > 0 else ""
                log.info(f"Quick play loi: {error_msg}")
                if "notinzone" in error_msg.lower() and self.in_table:
                    log.info("Dang trong ban, gui SET_READY...")
                    if not self.ready_sent:
                        self.ready_sent = True
                        await self.send(self.build_set_ready_msg())
                    return
                await asyncio.sleep(5)
                await self.send(self.build_quick_play_msg())
                return

            table_path = r.read_ascii()
            table_name = r.read_string()
            log.info(f"Quick play -> path={table_path}, name={table_name}")

            if r.remaining() > 0:
                arg_count = r.read_ubyte()
                for _ in range(arg_count):
                    key = r.read_ascii()
                    val = r.read_string()

            if table_path:
                self.in_table = True
                log.info(f"Entering table: {table_path}")
                await self.send(self.build_enter_place_msg(table_path, "", 1))
                await asyncio.sleep(0.5)
                await self.send(self.build_set_client_mode_msg(1))
                await asyncio.sleep(0.3)
                await self.send(self.build_get_table_data_ex_msg())

        except Exception as e:
            log.error(f"Loi parse quick play: {e}")

    async def handle_enter_place(self, r: ConnReader):
        currency = r.read_byte()
        rate = r.read_ushort()
        log.info(f"ENTER_PLACE: currency={'chip' if currency == 0 else 'star'}, rate={rate/10}")
        if not self.mode_set:
            self.mode_set = True
            await self.send(self.build_set_client_mode_msg(1))
        await self.send(self.build_get_table_data_ex_msg())

    async def handle_table_data_ex(self, r: ConnReader):
        try:
            first_byte = r.read_byte()
            if first_byte != 0:
                error_code = first_byte
                error_msg = r.read_string() if r.remaining() > 0 else ""
                log.info(f"GET_TABLE_DATA_EX error: code={error_code}, msg={error_msg}")
                if "not in table" in error_msg.lower() and not self.in_table:
                    log.info("Chua ngoi ban, tim ban moi...")
                    await self.send(self.build_quick_play_msg())
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
                log.info(f"  Slot {slot_id}: {full_name} (lv={level})")

            current_turn_slot = r.read_byte()
            turn_timeout = r.read_short()
            slot_remain = r.read_short()
            current_state = r.read_ubyte()

            log.info(f"  My slot: {self.my_slot_id}, playing: {self.is_playing}, "
                     f"turn: {current_turn_slot}, state: {current_state}")

            self.in_table = True

            match_point_count = r.read_ubyte()
            for _ in range(match_point_count):
                slot_id = r.read_byte()
                point = r.read_int()

            hcount = r.read_ubyte()
            vcount = r.read_ubyte()
            log.info(f"  Board: {hcount}x{vcount}")
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

            log.info(f"  Board state:\n{self.board.display()}")

            if self.is_playing and current_turn_slot == self.my_slot_id:
                self.is_my_turn = True
                await self.make_move()

            if not self.is_playing:
                log.info("Dang cho doi thu/van moi...")
                if not self.ready_sent:
                    self.ready_sent = True
                    await self.send(self.build_set_ready_msg())

        except Exception as e:
            log.error(f"Loi parse table data: {e}")
            import traceback
            traceback.print_exc()

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

        log.info(f"=== VAN {self.game_count} BAT DAU === Board: {hcount}x{vcount}")
        log.info(f"  My symbol: {'X' if self.my_symbol == SYMBOL_X else 'O'}")
        log.info(f"  Board:\n{self.board.display()}")

    async def handle_set_turn(self, r: ConnReader):
        slot_id = r.read_byte()
        turn_timeout = r.read_short()
        remain_duration = r.read_short()

        is_my_turn = (slot_id == self.my_slot_id)
        log.info(f"SET_TURN: slot={slot_id} (me={self.my_slot_id}), "
                 f"my_turn={is_my_turn}, timeout={turn_timeout}s")

        if is_my_turn and self.is_playing:
            self.is_my_turn = True
            await asyncio.sleep(0.8)
            await self.make_move()
        else:
            self.is_my_turn = False

    async def handle_move(self, r: ConnReader):
        pos = r.read_short()
        symbol = r.read_byte()
        x, y = self.board.pos_to_xy(pos)
        sym_char = 'X' if symbol == SYMBOL_X else 'O'

        current = self.board.get(x, y)
        if current == symbol:
            log.info(f"Xac nhan: ({x}, {y}) symbol={sym_char}")
            self.my_symbol = symbol
            self.opp_symbol = SYMBOL_O if symbol == SYMBOL_X else SYMBOL_X
        elif current == EMPTY:
            log.info(f"Doi thu danh: ({x}, {y}) symbol={sym_char}")
            self.board.place(x, y, symbol)
            if len(self.board.move_history) <= 2:
                self.opp_symbol = symbol
                self.my_symbol = SYMBOL_O if symbol == SYMBOL_X else SYMBOL_X
        else:
            log.warning(f"MOVE conflict ({x}, {y}): expected {current}, got {symbol}")
            self.board.place(x, y, symbol)
        log.info(f"  Board:\n{self.board.display()}")

    async def handle_highlight(self, r: ConnReader):
        count = r.read_ubyte()
        positions = []
        for _ in range(count):
            pos = r.read_short()
            x, y = self.board.pos_to_xy(pos)
            positions.append((x, y))
        log.info(f"Winning line: {positions}")

    async def handle_gameover(self, r: ConnReader):
        self.is_playing = False
        self.is_my_turn = False
        self.ready_sent = False

        player_count = r.read_ubyte()
        my_grade = None
        for _ in range(player_count):
            slot_id = r.read_byte()
            grade = r.read_byte()
            earn = r.read_long()
            if slot_id == self.my_slot_id:
                my_grade = grade
            grade_str = {1: "WIN", 2: "LOSE", 3: "DRAW", 4: "LOSE", 10: "DRAW", 11: "WIN", 12: "LOSE"}.get(grade, str(grade))
            log.info(f"  Slot {slot_id}: grade={grade_str}, earn={earn}")

        if my_grade in (1, 11):
            self.win_count += 1
            log.info(f"THANG!")
        elif my_grade in (2, 4, 12):
            self.lose_count += 1
            log.info(f"THUA!")
        elif my_grade in (3, 10):
            self.draw_count += 1
            log.info(f"HOA!")

        match_result = r.read_string()
        log.info(f"  Result: {match_result}")

        # In thống kê
        elapsed = ""
        if self.start_time:
            mins = (time.time() - self.start_time) / 60
            elapsed = f", thoi gian: {mins:.1f} phut"
        log.info(f"Tong: {self.game_count} van, {self.win_count} thang, "
                 f"{self.lose_count} thua, {self.draw_count} hoa{elapsed}")

        # Win rate
        if self.game_count > 0:
            wr = self.win_count / self.game_count * 100
            log.info(f"Win rate: {wr:.1f}%")

        await asyncio.sleep(3)
        if self.in_table:
            self.ready_sent = False
            log.info("Gui SET_READY cho doi thu moi...")
            await self.send(self.build_set_ready_msg())
            self.ready_sent = True
        else:
            log.info("Tim ban moi...")
            await self.send(self.build_quick_play_msg())

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

        self.players[slot_id] = {
            'player_id': player_id,
            'full_name': full_name,
            'is_owner': is_owner,
            'level': level,
        }
        log.info(f"Player entered: slot {slot_id} - {full_name} (lv={level})")

    def _determine_symbols(self):
        if self.my_slot_id == 0:
            self.my_symbol = SYMBOL_X
            self.opp_symbol = SYMBOL_O
        else:
            self.my_symbol = SYMBOL_O
            self.opp_symbol = SYMBOL_X
        log.info(f"  Symbols: me={'X' if self.my_symbol == SYMBOL_X else 'O'} (slot {self.my_slot_id}), "
                 f"opp={'X' if self.opp_symbol == SYMBOL_X else 'O'}")

    async def make_move(self):
        if not self.is_my_turn or not self.is_playing:
            return
        self.is_my_turn = False

        t0 = time.time()
        x, y = self.ai.find_best_move(self.my_symbol, self.opp_symbol)
        elapsed = time.time() - t0
        pos = self.board.xy_to_pos(x, y)

        log.info(f"TA DANH: ({x}, {y}) pos={pos} [{elapsed:.2f}s]")
        await self.send(self.build_play_msg(pos))
        self.board.place(x, y, self.my_symbol)
        log.info(f"  Board:\n{self.board.display()}")

    async def ping_loop(self):
        while self.running:
            await asyncio.sleep(self.ping_interval)
            if self.ws and self.ws.close_code is None:
                try:
                    if not self.is_playing and self.in_table:
                        idle_time = time.time() - self.last_activity
                        if idle_time > self.idle_timeout:
                            log.info(f"Idle {idle_time:.0f}s - roi ban tim ban moi...")
                            self.in_table = False
                            self.ready_sent = False
                            self.is_playing = False
                            self.last_activity = time.time()
                            # Thoát bàn hiện tại bằng cách enter place chính
                            await self.send(self.build_enter_place_msg(self.place_path, "", 1))
                            await asyncio.sleep(1)
                            await self.send(self.build_quick_play_msg())

                    # Kiểm tra timeout 30 phút
                    if self.start_time and (time.time() - self.start_time) > 30 * 60:
                        log.info("=== DA CHAY 30 PHUT - DUNG BOT ===")
                        self.running = False
                        if self.ws:
                            await self.ws.close()
                        return
                except Exception as e:
                    log.debug(f"Ping loop error: {e}")

    async def run(self):
        if not await self.connect():
            return

        login_msg = self.build_login_msg()
        log.info(f"Dang nhap nick={self.nickname}, token={self.token}...")
        await self.send(login_msg)

        asyncio.create_task(self.ping_loop())

        try:
            async for raw in self.ws:
                if isinstance(raw, bytes):
                    await self.handle_message(raw)
        except websockets.exceptions.ConnectionClosed as e:
            log.warning(f"Ket noi dong: {e}")
        except Exception as e:
            log.error(f"Loi: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self.running = False
            log.info("Bot da dung.")

    async def run_with_reconnect(self, max_retries=100):
        retries = 0
        self.start_time = time.time()
        while retries < max_retries and self.running:
            try:
                self.is_playing = False
                self.is_my_turn = False
                self.in_table = False
                self.ready_sent = False
                self.mode_set = False
                self.running = True
                self.board.clear()

                # Kiểm tra timeout 30 phút
                if self.start_time and (time.time() - self.start_time) > 30 * 60:
                    log.info("=== DA CHAY 30 PHUT - KET THUC ===")
                    log.info(f"Tong: {self.game_count} van, {self.win_count} thang, "
                             f"{self.lose_count} thua, {self.draw_count} hoa")
                    if self.game_count > 0:
                        wr = self.win_count / self.game_count * 100
                        log.info(f"Win rate cuoi: {wr:.1f}%")
                    break

                if not self.http_handshake():
                    log.error("Dang nhap that bai!")
                    continue
                await self.run()
            except Exception as e:
                log.error(f"Loi nghiem trong: {e}")

            if not self.running:
                break

            retries += 1
            wait_time = min(5 * retries, 30)
            log.info(f"Doi {wait_time}s truoc khi reconnect (lan {retries}/{max_retries})...")
            await asyncio.sleep(wait_time)


# ─── Main ───────────────────────────────────────────────────
async def main():
    bot = CaroBot()
    await bot.run_with_reconnect()


if __name__ == "__main__":
    asyncio.run(main())
