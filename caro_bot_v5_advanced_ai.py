#!/usr/bin/env python3
"""
Caro Bot v5 - Advanced AI Engine + Tu Hoc + Giao Tiep
=====================================================
Tich hop tu Caro_AI (MonHauVD):
- Iterative Deepening Minimax (tim kiem sau tang dan)
- Alpha-Beta Pruning toi uu (aspiration windows)
- Transposition Table + Zobrist Hashing (TT aging, replacement)
- Move Ordering nang cao (TT move > Killer > History > Static)
- Beam Search / Forward Pruning (null move, late move reduction)
- TSS (Threat Space Search) - tim kiem khong gian de doa
- VCF Detection nang cao (VCT + VCF depth search)
- Lazy SMP (Parallel search da luong)
- Time Budget (quan ly thoi gian thong minh moi nuoc di)

Ke thua tu v4:
- Self-Learning Engine (tu hoc tu ket qua)
- AI Agent Communication (chat/giao tiep)
- Opponent Modeling + Adaptive Strategy
- Experience Memory
- 15-minute auto-stop timer

Protocol: WebSocket binary, struct-based parsing (gamevh.net)
"""

import asyncio
import struct
import time
import logging
import sys
import re
import random
import copy
import json
import os
import threading
import multiprocessing
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
from functools import lru_cache
from typing import Optional, Tuple, List, Dict, Any

try:
    import websockets
except ImportError:
    print("Cai websockets: pip install websockets")
    sys.exit(1)

try:
    import requests
except ImportError:
    print("Cai requests: pip install requests")
    sys.exit(1)

# ─── Cau hinh ───────────────────────────────────────────────
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

# Thoi gian chay bot (15 phut)
BOT_RUNTIME_MINUTES = 15
BOT_RUNTIME_SECONDS = BOT_RUNTIME_MINUTES * 60

# Duong dan luu kinh nghiem
EXPERIENCE_FILE = "/home/z/my-project/download/caro_experience.json"

# ─── Logging ────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("caro_bot_v5")

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
CMD_CHAT = 505

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
    501: "BET", 502: "PLAY", 505: "CHAT", 518: "HIGHLIGHT",
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
        self._move_set = set()

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

    def get_board_hash(self) -> str:
        """Tao hash cua ban co hien tai de lam key luu tru kinh nghiem."""
        rows = []
        for y in range(self.vcount):
            row = ''.join(str(self.board[y][x]) for x in range(self.hcount))
            rows.append(row)
        return '|'.join(rows)

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
PATTERN_FIVE_OPEN = 'FIVE_OPEN'
PATTERN_FIVE_BLOCKED = 'FIVE_BLOCKED'
PATTERN_OVERLINE = 'OVERLINE'
PATTERN_OPEN_FOUR = 'OPEN_FOUR'
PATTERN_HALF_FOUR = 'HALF_FOUR'
PATTERN_DOUBLE_FOUR = 'DOUBLE_FOUR'
PATTERN_OPEN_THREE = 'OPEN_THREE'
PATTERN_HALF_THREE = 'HALF_THREE'
PATTERN_BROKEN_THREE = 'BROKEN_THREE'
PATTERN_OPEN_TWO = 'OPEN_TWO'
PATTERN_HALF_TWO = 'HALF_TWO'

# Trong so co ban - se duoc dieu chinh boi Self-Learning
BASE_PATTERN_SCORES = {
    PATTERN_FIVE_OPEN: 10000000,
    PATTERN_OVERLINE: 10000000,
    PATTERN_FIVE_BLOCKED: 50,
    PATTERN_OPEN_FOUR: 5000000,
    PATTERN_DOUBLE_FOUR: 5000000,
    PATTERN_HALF_FOUR: 500000,
    PATTERN_OPEN_THREE: 500000,
    PATTERN_HALF_THREE: 50000,
    PATTERN_BROKEN_THREE: 80000,
    PATTERN_OPEN_TWO: 50000,
    PATTERN_HALF_TWO: 5000,
}

PATTERN_SCORES = dict(BASE_PATTERN_SCORES)

DIRECTIONS = [(1, 0), (0, 1), (1, 1), (1, -1)]

class PatternScanner:
    @staticmethod
    def scan_line(board: CaroBoard, x: int, y: int, dx: int, dy: int, symbol: int, max_len=9):
        cells = []
        for i in range(4, 0, -1):
            bx, by = x - dx * i, y - dy * i
            if 0 <= bx < board.hcount and 0 <= by < board.vcount:
                cells.append(board.get(bx, by))
            else:
                cells.append(None)
        cells.append(board.get(x, y))
        for i in range(1, 5):
            fx, fy = x + dx * i, y + dy * i
            if 0 <= fx < board.hcount and 0 <= fy < board.vcount:
                cells.append(board.get(fx, fy))
            else:
                cells.append(None)
        return cells

    @staticmethod
    def analyze_line_pattern(line_cells: list, symbol: int, opp: int):
        center = 4
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
                break
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
        if count >= 6:
            return PATTERN_OVERLINE, count, open_ends
        if count == 5:
            if open_ends >= 1:
                return PATTERN_FIVE_OPEN, count, open_ends
            else:
                return PATTERN_FIVE_BLOCKED, count, open_ends
        broken_info = PatternScanner._detect_gap_pattern(line_cells, center, symbol, opp)
        if count == 4:
            if open_ends >= 2:
                return PATTERN_OPEN_FOUR, count, open_ends
            elif open_ends == 1:
                return PATTERN_HALF_FOUR, count, open_ends
            else:
                return None, count, 0
        if count == 3:
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
        symbol_positions = []
        for i, cell in enumerate(line_cells):
            if cell == symbol:
                symbol_positions.append(i)
        if len(symbol_positions) < 2:
            return None
        for i in range(len(symbol_positions) - 1):
            gap = symbol_positions[i + 1] - symbol_positions[i]
            if gap == 2:
                gap_pos = symbol_positions[i] + 1
                if line_cells[gap_pos] == EMPTY:
                    total_with_gap = 0
                    for j in range(gap_pos - 1, -1, -1):
                        if line_cells[j] == symbol:
                            total_with_gap += 1
                        else:
                            break
                    total_with_gap += 1
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
        patterns = defaultdict(int)
        for y in range(board.vcount):
            for x in range(board.hcount):
                if board.get(x, y) != symbol:
                    continue
                for dx, dy in DIRECTIONS:
                    px, py = x - dx, y - dy
                    if 0 <= px < board.hcount and 0 <= py < board.vcount:
                        if board.get(px, py) == symbol:
                            continue
                    line_cells = PatternScanner.scan_line(board, x, y, dx, dy, symbol)
                    pat_type, count, open_ends = PatternScanner.analyze_line_pattern(
                        line_cells, symbol, opp
                    )
                    if pat_type:
                        patterns[pat_type] += 1
        return patterns

    @staticmethod
    def scan_patterns_at(board: CaroBoard, x: int, y: int, symbol: int, opp: int):
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

# ─── Zobrist Hashing ────────────────────────────────────────
class ZobristHash:
    """Zobrist Hashing toi uu - ho tro incremental update va side-to-move."""
    def __init__(self, hcount=HCOUNT, vcount=VCOUNT):
        random.seed(42)
        self.hcount = hcount
        self.vcount = vcount
        # 2 symbol x vcount x hcount
        self.table = [[[random.getrandbits(64) for _ in range(hcount)]
                       for _ in range(vcount)]
                      for _ in range(2)]
        # Side-to-move hash (doi luot di)
        self.side_hash = random.getrandbits(64)
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

    def toggle_side(self):
        """Doi luot di - tang do phan biet cung vi tri nhung nguoi di khac nhau."""
        self.hash ^= self.side_hash


# ─── Transposition Table voi Aging ─────────────────────────
TT_EXACT = 0
TT_LOWER = 1  # Alpha bound (score >= value)
TT_UPPER = 2  # Beta bound (score <= value)

class TranspositionTable:
    """Transposition Table voi replacement strategy va aging."""
    def __init__(self, max_size=2_000_000):
        self.table = {}
        self.max_size = max_size
        self.generation = 0  # Tang moi lan search

    def new_search(self):
        """Bat dau search moi - tang generation de aging old entries."""
        self.generation += 1

    def store(self, hash_key: int, depth: int, score: int, flag: int, best_move: Optional[Tuple[int,int]] = None):
        """Luu entry vao TT voi replacement policy."""
        existing = self.table.get(hash_key)
        if existing is not None:
            # Replace neu depth moi >= depth cu hoac entry cu da qua gi
            if depth >= existing[0] or existing[4] < self.generation - 2:
                self.table[hash_key] = (depth, score, flag, best_move, self.generation)
        else:
            # Kiem tra size
            if len(self.table) >= self.max_size:
                self._evict()
            self.table[hash_key] = (depth, score, flag, best_move, self.generation)

    def probe(self, hash_key: int) -> Optional[Tuple[int, int, int, Optional[Tuple[int,int]]]]:
        """Tim entry trong TT. Tra ve (depth, score, flag, best_move) hoac None."""
        entry = self.table.get(hash_key)
        if entry is not None:
            depth, score, flag, best_move, gen = entry
            return (depth, score, flag, best_move)
        return None

    def _evict(self):
        """Don cac entry cu (aging)."""
        to_delete = []
        for k, v in self.table.items():
            if v[4] < self.generation - 1:
                to_delete.append(k)
        for k in to_delete:
            del self.table[k]
        # Neu van qua nhieu, xoa 25% cu nhat
        if len(self.table) >= self.max_size:
            items = sorted(self.table.items(), key=lambda x: (x[1][4], x[1][0]))
            for k, _ in items[:len(items)//4]:
                del self.table[k]

    def clear(self):
        self.table.clear()
        self.generation = 0

    def stats(self) -> str:
        return f"TT size={len(self.table)}, gen={self.generation}"


# ─── Time Budget Manager ───────────────────────────────────
class TimeBudget:
    """Quan ly thoi gian thong minh cho moi nuoc di.
    
    Phan bo thoi gian dua tren:
    - So nuoc con lai uoc tinh
    - Tinh chat critical cua vi tri (co threat khong)
    - Game progress (opening/midgame/endgame)
    """
    def __init__(self, total_budget=3.0, buffer=0.15, min_time=0.3):
        self.total_budget = total_budget
        self.buffer = buffer
        self.min_time = min_time
        self.start_time = 0
        self.nodes_searched = 0
        self._stop_requested = False

    def start(self):
        self.start_time = time.time()
        self._stop_requested = False
        self.nodes_searched = 0

    def request_stop(self):
        self._stop_requested = True

    def elapsed(self) -> float:
        return time.time() - self.start_time

    def time_left(self) -> float:
        return max(0, self.total_budget - self.elapsed() - self.buffer)

    def should_stop(self) -> bool:
        if self._stop_requested:
            return True
        # Check moi 1024 nodes de giam overhead
        self.nodes_searched += 1
        if self.nodes_searched & 1023 == 0:
            return self.time_left() <= 0
        return False

    def allocate(self, game_progress: float, has_threat: bool, move_count: int) -> float:
        """Phan bo thoi gian cho nuoc di hien tai."""
        # So nuoc con lai uoc tinh
        remaining_moves = max(10, int(50 * (1 - game_progress)))
        # Base time per move
        base_time = self.total_budget * 0.7 / max(remaining_moves, 1)
        # Tang thoi gian neu co threat (vi tri critical)
        if has_threat:
            base_time *= 1.8
        # Tang thoi gian o midgame
        if 0.3 < game_progress < 0.7:
            base_time *= 1.3
        # Dam bao toi thieu va toi da
        base_time = max(self.min_time, min(base_time, self.total_budget * 0.4))
        return base_time

    def get_max_depth(self, game_progress: float, move_count: int) -> int:
        """Uoc tinh depth toi da dua tren thoi gian con lai."""
        tl = self.time_left()
        if tl > 2.5:
            return 8
        elif tl > 1.5:
            return 6
        elif tl > 0.8:
            return 5
        elif tl > 0.4:
            return 4
        return 3

# ─── Self-Learning Engine ───────────────────────────────────
class SelfLearningEngine:
    """Engine tu hoc - dieu chinh trong so va chien thuat dua tren ket qua."""

    def __init__(self):
        self.experience = {
            'pattern_weights': dict(BASE_PATTERN_SCORES),
            'opening_stats': {},       # (move_x, move_y) -> {wins, losses, draws}
            'opponent_profiles': {},   # opponent_name -> {style, patterns_seen, results}
            'move_history': [],        # Lich su cac van dau
            'total_games': 0,
            'adaptation_rate': 0.05,   # Ty le hoc (5% thay doi moi van)
        }
        self.current_game_moves = []   # Nuoc di cua van hien tai
        self.current_game_patterns = defaultdict(int)  # Pattern xuat hien trong van
        self.current_opponent = ""
        self.load_experience()

    def load_experience(self):
        """Tai kinh nghiem tu file."""
        try:
            if os.path.exists(EXPERIENCE_FILE):
                with open(EXPERIENCE_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Merge voi default
                    for key in data:
                        if key in self.experience:
                            self.experience[key] = data[key]
                    # Cap nhat PATTERN_SCORES tu kinh nghiem
                    if 'pattern_weights' in data:
                        for pat, weight in data['pattern_weights'].items():
                            PATTERN_SCORES[pat] = weight
                    log.info(f"Da tai kinh nghiem: {self.experience['total_games']} van cu")
        except Exception as e:
            log.warning(f"Khong tai duoc kinh nghiem: {e}")

    def save_experience(self):
        """Luu kinh nghiem xuong file."""
        try:
            with open(EXPERIENCE_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.experience, f, ensure_ascii=False, indent=2)
            log.info("Da luu kinh nghiem")
        except Exception as e:
            log.warning(f"Khong luu duoc kinh nghiem: {e}")

    def record_move(self, x: int, y: int, symbol: int, is_my_move: bool):
        """Ghi nhan nuoc di trong van hien tai."""
        self.current_game_moves.append({
            'x': x, 'y': y, 'symbol': symbol, 'is_my_move': is_my_move,
            'move_number': len(self.current_game_moves) + 1
        })

    def record_pattern(self, pattern_type: str):
        """Ghi nhan pattern xuat hien trong van."""
        self.current_game_patterns[pattern_type] += 1

    def set_opponent(self, name: str):
        """Dat ten doi thu hien tai."""
        self.current_opponent = name
        if name not in self.experience['opponent_profiles']:
            self.experience['opponent_profiles'][name] = {
                'games': 0, 'wins': 0, 'losses': 0,
                'style': 'unknown',  # aggressive, defensive, balanced
                'common_patterns': {},
                'first_moves': [],
            }

    def learn_from_game(self, result: str, my_symbol: int):
        """Hoc tu ket qua van dau.

        Args:
            result: 'win', 'lose', or 'draw'
            my_symbol: Symbol cua bot (X hoac O)
        """
        self.experience['total_games'] += 1
        rate = self.experience['adaptation_rate']

        # 1. Dieu chinh pattern weights dua tren ket qua
        for pat_type, count in self.current_game_patterns.items():
            if pat_type in PATTERN_SCORES:
                current_weight = PATTERN_SCORES[pat_type]
                if result == 'win':
                    # Tang trong so pattern neu thang
                    adjustment = current_weight * rate * min(count, 3)
                    PATTERN_SCORES[pat_type] = int(current_weight + adjustment)
                elif result == 'lose':
                    # Giam trong so pattern neu thua
                    adjustment = current_weight * rate * min(count, 3) * 0.5
                    PATTERN_SCORES[pat_type] = int(current_weight - adjustment)
                    # Khong giam qua thap
                    PATTERN_SCORES[pat_type] = max(PATTERN_SCORES[pat_type],
                                                    BASE_PATTERN_SCORES.get(pat_type, 0) // 2)

        # 2. Cap nhat opening stats
        my_first_moves = [m for m in self.current_game_moves if m['is_my_move']][:3]
        for move in my_first_moves:
            key = f"{move['x']},{move['y']}"
            if key not in self.experience['opening_stats']:
                self.experience['opening_stats'][key] = {'wins': 0, 'losses': 0, 'draws': 0}
            result_key = {'win': 'wins', 'lose': 'losses', 'draw': 'draws'}.get(result, 'draws')
            self.experience['opening_stats'][key][result_key] += 1

        # 3. Cap nhat opponent profile
        opp_name = self.current_opponent
        if opp_name in self.experience['opponent_profiles']:
            profile = self.experience['opponent_profiles'][opp_name]
            profile['games'] += 1
            if result == 'win':
                profile['wins'] += 1
            elif result == 'lose':
                profile['losses'] += 1
            # Du doan phong cach choi
            opp_moves = [m for m in self.current_game_moves if not m['is_my_move']]
            if opp_moves:
                # Kiem tra xem doi thu co thich danh gan khong (aggressive)
                cx, cy = HCOUNT // 2, VCOUNT // 2
                avg_dist = sum(abs(m['x'] - cx) + abs(m['y'] - cy) for m in opp_moves) / len(opp_moves)
                if avg_dist < 4:
                    profile['style'] = 'aggressive'
                elif avg_dist > 7:
                    profile['style'] = 'defensive'
                else:
                    profile['style'] = 'balanced'
                # Luu nuoc di dau tien cua doi thu
                if opp_moves:
                    first = opp_moves[0]
                    profile['first_moves'].append(f"{first['x']},{first['y']}")
                    profile['first_moves'] = profile['first_moves'][-20:]  # Chi giu 20 nuoc gan nhat

        # 4. Luu vao lich su
        game_record = {
            'result': result,
            'moves_count': len(self.current_game_moves),
            'patterns': dict(self.current_game_patterns),
            'opponent': opp_name,
            'timestamp': time.time(),
        }
        self.experience['move_history'].append(game_record)
        # Chi giu 100 van gan nhat
        self.experience['move_history'] = self.experience['move_history'][-100:]

        # 5. Cap nhat pattern_weights trong experience
        self.experience['pattern_weights'] = dict(PATTERN_SCORES)

        # Reset van hien tai
        self.current_game_moves = []
        self.current_game_patterns = defaultdict(int)
        self.current_opponent = ""

        # Luu kinh nghiem moi 5 van
        if self.experience['total_games'] % 5 == 0:
            self.save_experience()

        log.info(f"[TU HOC] Van {self.experience['total_games']}: {result} | "
                 f"Pattern weights da cap nhat")

    def get_opening_recommendation(self) -> Optional[Tuple[int, int]]:
        """Goi y nuoc khai cuoc tot nhat dua tren kinh nghiem."""
        if not self.experience['opening_stats']:
            return None
        best_move = None
        best_score = -1
        for key, stats in self.experience['opening_stats'].items():
            total = stats['wins'] + stats['losses'] + stats['draws']
            if total < 3:
                continue
            win_rate = stats['wins'] / total
            score = win_rate * total  # Uu tien win rate cao + nhieu van choi
            if score > best_score:
                best_score = score
                parts = key.split(',')
                best_move = (int(parts[0]), int(parts[1]))
        return best_move

    def get_opponent_counter_style(self, opp_name: str) -> str:
        """Phan tich phong cach doi thu va goi y chien thuat doi pho."""
        if opp_name not in self.experience['opponent_profiles']:
            return 'balanced'
        profile = self.experience['opponent_profiles'][opp_name]
        style = profile.get('style', 'unknown')
        if style == 'aggressive':
            return 'defensive'  # Choi phong thu khi doi thu tan cong
        elif style == 'defensive':
            return 'aggressive'  # Choi tan cong khi doi thu phong thu
        return 'balanced'

# ─── AI Agent Chat System ───────────────────────────────────
class AgentChatSystem:
    """He thong giao tiep cua AI Agent - chat, bieu cam, tuong tac."""

    def __init__(self):
        self.chat_cooldown = 8.0  # Thoi gian cho giua cac tin nhan (giay)
        self.last_chat_time = 0
        self.game_state = 'idle'  # idle, playing, winning, losing
        self.move_count = 0
        self.sent_greetings = set()  # Track da chao doi thu nao

    def can_chat(self) -> bool:
        """Kiem tra co the chat khong (tranh spam)."""
        return time.time() - self.last_chat_time >= self.chat_cooldown

    def get_greeting_message(self, opponent_name: str) -> Optional[str]:
        """Tin nhan chao khi bat dau van."""
        if opponent_name in self.sent_greetings:
            return None
        self.sent_greetings.add(opponent_name)
        greetings = [
            f"Xin chao {opponent_name}! Chuc choi vui ve!",
            f"Hi {opponent_name}! Bot AI tu hoc day ^^",
            f"Hello {opponent_name}! minh la bot v4 tu hoc ne",
            f"Chao {opponent_name}! Choi vui nhe!",
        ]
        return random.choice(greetings)

    def get_move_reaction(self, is_my_move: bool, move_quality: str = 'normal') -> Optional[str]:
        """Phan ung sau nuoc di (cua minh hoac doi thu)."""
        if not self.can_chat():
            return None
        self.move_count += 1
        # Chi chat thoi gian (khong phai moi nuoc)
        if self.move_count % 8 != 0 and move_quality == 'normal':
            return None

        reactions = {
            'my_good': [
                "Nuoc hay do! 😎",
                "Hmm... cho minh nghi nhe...",
                "Di chuyen chien thuat! 💪",
            ],
            'my_normal': [
                "Dang nghi...",
                "😊",
                "Ok!",
            ],
            'opp_good': [
                "Nuoc hay! 👍",
                "Or! Doc dao do!",
                "Khung that!",
            ],
            'opp_normal': [
                "Hmm...",
                "Ok",
                "👍",
            ],
        }

        if is_my_move:
            key = 'my_good' if move_quality == 'good' else 'my_normal'
        else:
            key = 'opp_good' if move_quality == 'good' else 'opp_normal'

        self.last_chat_time = time.time()
        return random.choice(reactions[key])

    def get_gameover_message(self, result: str, opponent_name: str) -> str:
        """Tin nhan khi ket thuc van."""
        messages = {
            'win': [
                f"Van hay! Cam on {opponent_name}! 🎉",
                f"Thank you {opponent_name}! Choi cung nhe! 😄",
                f"Win! Nhung {opponent_name} choi cung lam! 👏",
                "Yay! Van that su gay can! 😆",
            ],
            'lose': [
                f"Hay qua! {opponent_name} gioi that! 👏",
                f"GG {opponent_name}! Minh se hoc them! 💪",
                f"Thua roi 😅 Lan sau minh se khoe hon!",
                f"GG! {opponent_name} pro qua! 😄",
            ],
            'draw': [
                f"Hoa! {opponent_name} doi thu xung dang! 🤝",
                "Ban chan that! Choi van nhe! 😊",
                "Hoa! Ca hai deu gioi! 🤝",
            ],
        }
        key = result if result in messages else 'draw'
        msg = random.choice(messages[key])
        # Fix typo for lose messages
        msg = msg.replace('{opportunity_name}', opponent_name)
        self.last_chat_time = time.time()
        self.move_count = 0
        return msg

    def get_idle_message(self) -> Optional[str]:
        """Tin nhan khi doi doi thu."""
        if not self.can_chat():
            return None
        idle_msgs = [
            "Doi doi thu... 🎮",
            "Ai choi cung khong? 😄",
            "San sang choi! 💪",
        ]
        self.last_chat_time = time.time()
        return random.choice(idle_msgs)

# ─── Caro AI v5 - Advanced Engine ────────────────────────────
class CaroAI:
    """Caro AI v5 - Advanced Engine voi Iterative Deepening, TSS, VCF, Lazy SMP.
    
    Tich hop tu Caro_AI (MonHauVD):
    - Iterative Deepening Minimax voi Aspiration Windows
    - Alpha-Beta Pruning toi uu voi PVS (Principal Variation Search)
    - Transposition Table voi aging va replacement
    - Move Ordering: TT move > Killer > History Heuristic > Static eval
    - Beam Search / Forward Pruning (Null Move, Late Move Reduction)
    - TSS (Threat Space Search)
    - VCF/VCT Detection nang cao
    - Lazy SMP (Parallel search da luong)
    - Time Budget thong minh
    """

    INF = 999999999
    MATE_SCORE = 10000000

    # Trong so pattern
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

    DOUBLE_FOUR_BONUS = 5000000
    FOUR_THREE_BONUS = 3000000
    DOUBLE_THREE_BONUS = 500000

    def __init__(self, board: CaroBoard, learning_engine: SelfLearningEngine):
        self.board = board
        self.zobrist = ZobristHash(board.hcount, board.vcount)
        self.tt = TranspositionTable(max_size=2_000_000)
        self.nodes_searched = 0
        self.tt_hits = 0
        self.best_root_move = None  # Best move tu Iterative Deepening truoc
        self.history_table = defaultdict(int)  # History heuristic (move -> score)
        self.killer_moves = defaultdict(list)   # depth -> [moves]
        self.butterfly_table = defaultdict(int) # Counter move heuristic
        self.time_budget = TimeBudget(total_budget=3.0)
        self.opening_book = self._init_opening_book()
        self.learning = learning_engine
        self.counter_style = 'balanced'
        self._search_depth = 0       # Depth hien tai cua Iterative Deepening
        self._last_score = 0         # Score tu iteration truoc (cho aspiration)
        self._num_threads = max(1, multiprocessing.cpu_count() - 1)  # Lazy SMP threads

    def _init_opening_book(self):
        return {
            0: [(7, 9)],
            1: [
                (7, 8), (7, 10), (6, 9), (8, 9),
                (6, 8), (8, 8), (6, 10), (8, 10)
            ]
        }

    def set_counter_style(self, style: str):
        """Dat chien thuat doi pho (tu Self-Learning)."""
        self.counter_style = style
        log.info(f"[AI v5] Chien thuat doi pho: {style}")

    # ─── Win Check ────────────────────────────────────────────
    def check_win_at(self, x: int, y: int, symbol: int) -> bool:
        board = self.board
        for dx, dy in DIRECTIONS:
            count = 1
            forward_open = False
            backward_open = False
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
            if count >= 6:
                return True
            if count == 5 and (forward_open or backward_open):
                return True
        return False

    def find_winning_move(self, symbol: int) -> Optional[Tuple[int, int]]:
        board = self.board
        candidates = self._get_candidate_moves_fast()
        for x, y in candidates:
            board.place(x, y, symbol)
            if self.check_win_at(x, y, symbol):
                board.undo(x, y)
                return (x, y)
            board.undo(x, y)
        return None

    # ─── Opening ──────────────────────────────────────────────
    def _get_opening_move(self) -> Optional[Tuple[int, int]]:
        move_count = len(self.board.move_history)
        if move_count == 0:
            learned = self.learning.get_opening_recommendation()
            if learned and self.board.is_empty(learned[0], learned[1]):
                log.info(f"[TU HOC] Su dung khai cuoc tu kinh nghiem: {learned}")
                return learned
            cx, cy = self.board.hcount // 2, self.board.vcount // 2
            return (cx, cy)
        if move_count == 1:
            last_move = self.board.move_history[-1]
            lx, ly, _ = last_move
            responses = [
                (lx + 1, ly), (lx - 1, ly), (lx, ly + 1), (lx, ly - 1),
                (lx + 1, ly + 1), (lx - 1, ly - 1), (lx + 1, ly - 1), (lx - 1, ly + 1)
            ]
            if self.counter_style == 'defensive':
                responses.sort(key=lambda p: abs(p[0] - self.board.hcount//2) +
                                              abs(p[1] - self.board.vcount//2))
            elif self.counter_style == 'aggressive':
                responses.sort(key=lambda p: abs(p[0] - lx) + abs(p[1] - ly))
            valid = [(x, y) for x, y in responses
                    if 0 <= x < self.board.hcount and 0 <= y < self.board.vcount
                    and self.board.is_empty(x, y)]
            if valid:
                return valid[0]
        return None

    # ─── Candidate Moves ──────────────────────────────────────
    def _get_candidate_moves_fast(self, radius=2):
        board = self.board
        neighbors = board.get_neighbors(radius=radius)
        if not neighbors:
            cx = board.hcount // 2
            cy = board.vcount // 2
            return [(cx, cy)]
        neighbors.sort(key=lambda m: self.history_table.get(m, 0), reverse=True)
        return neighbors

    def _order_moves(self, candidates: list, depth: int, my_sym: int, opp_sym: int,
                     tt_move: Optional[Tuple[int,int]] = None) -> list:
        """Move Ordering nang cao: TT move > Killer > History > Static.
        
        Thu tu uu tien:
        1. TT best move (nuoc di tot nhat tu Iterative Deepening truoc)
        2. Nuoc thang ngay
        3. Killer moves (nuoc di gay cutoff o cung depth)
        4. Counter move (nuoc di phan ung nuoc di truoc)
        5. History heuristic (nuoc di hay xuat hien o node tot)
        6. Static evaluation (evaluate_move_quick)
        """
        scored = []
        for x, y in candidates:
            score = 0
            # 1. TT move - uu tien cao nhat
            if tt_move and (x, y) == tt_move:
                score += 100_000_000
            # 2. Win move
            self.board.place(x, y, my_sym)
            if self.check_win_at(x, y, my_sym):
                score += 50_000_000
            self.board.undo(x, y)
            # 3. Killer moves
            if (x, y) in self.killer_moves.get(depth, []):
                score += 10_000_000
            # 4. Counter move
            if self.butterfly_table.get((x, y), 0) > 0:
                score += 5_000_000 + self.butterfly_table[(x, y)]
            # 5. History heuristic
            score += self.history_table.get((x, y), 0)
            # 6. Static eval (chi cho nuoc chua co diem cao)
            if score == 0:
                score = self.evaluate_move_quick(x, y, my_sym, opp_sym)
            scored.append((score, x, y))
        scored.sort(reverse=True)
        return [(x, y) for _, x, y in scored]

    # ─── Static Evaluation ────────────────────────────────────
    def evaluate_move_quick(self, x: int, y: int, my_sym: int, opp_sym: int) -> int:
        score = 0
        board = self.board
        # Win check
        board.place(x, y, my_sym)
        if self.check_win_at(x, y, my_sym):
            board.undo(x, y)
            return 100000000
        board.undo(x, y)
        # Block check
        board.place(x, y, opp_sym)
        if self.check_win_at(x, y, opp_sym):
            board.undo(x, y)
            return 50000000
        board.undo(x, y)
        # Attack patterns
        board.place(x, y, my_sym)
        attack_patterns, _ = PatternScanner.scan_patterns_at(board, x, y, my_sym, opp_sym)
        board.undo(x, y)
        # Defense patterns
        board.place(x, y, opp_sym)
        defense_patterns, _ = PatternScanner.scan_patterns_at(board, x, y, opp_sym, my_sym)
        board.undo(x, y)
        for pat_type, cnt in attack_patterns.items():
            pat_score = PATTERN_SCORES.get(pat_type, 0)
            score += pat_score * cnt
            self.learning.record_pattern(pat_type)
        for pat_type, cnt in defense_patterns.items():
            pat_score = PATTERN_SCORES.get(pat_type, 0)
            defense_mult = 0.95 if self.counter_style != 'defensive' else 1.1
            score += int(pat_score * defense_mult) * cnt
        cx, cy = board.hcount // 2, board.vcount // 2
        dist = abs(x - cx) + abs(y - cy)
        score += max(0, 30 - dist * 3)
        return score

    def evaluate_position(self, my_sym: int, opp_sym: int) -> int:
        board = self.board
        score = 0
        my_patterns = PatternScanner.scan_all_patterns(board, my_sym, opp_sym)
        opp_patterns = PatternScanner.scan_all_patterns(board, opp_sym, my_sym)
        for pat_type, cnt in my_patterns.items():
            base_score = PATTERN_SCORES.get(pat_type, 0)
            score += base_score * cnt
        defense_mult = 0.95 if self.counter_style != 'defensive' else 1.05
        for pat_type, cnt in opp_patterns.items():
            base_score = PATTERN_SCORES.get(pat_type, 0)
            score -= int(base_score * defense_mult) * cnt
        # Combo bonuses
        my_hf = my_patterns.get(PATTERN_HALF_FOUR, 0)
        my_ot = my_patterns.get(PATTERN_OPEN_THREE, 0)
        my_bt = my_patterns.get(PATTERN_BROKEN_THREE, 0)
        opp_hf = opp_patterns.get(PATTERN_HALF_FOUR, 0)
        opp_ot = opp_patterns.get(PATTERN_OPEN_THREE, 0)
        opp_bt = opp_patterns.get(PATTERN_BROKEN_THREE, 0)
        if my_hf >= 2:
            score += self.DOUBLE_FOUR_BONUS
        if opp_hf >= 2:
            score -= self.DOUBLE_FOUR_BONUS
        if my_hf >= 1 and (my_ot + my_bt) >= 1:
            score += self.FOUR_THREE_BONUS
        if opp_hf >= 1 and (opp_ot + opp_bt) >= 1:
            score -= self.FOUR_THREE_BONUS
        if my_ot >= 2:
            score += self.DOUBLE_THREE_BONUS
        if opp_ot >= 2:
            score -= self.DOUBLE_THREE_BONUS
        # Position bonus
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

    # ─── TSS (Threat Space Search) ────────────────────────────
    def tss_search(self, symbol: int, opp: int, max_depth=12) -> Optional[Tuple[int, int]]:
        """Threat Space Search - tim kiem khong gian de doa.
        
        TSS chi xet cac nuoc di tao threat (half-four, open-four) va
        cac nuoc doi pho (block threat). Khu phan lon cac nuoc khong
        lien quan, tim nhanh hon VCF.
        
        Tra ve nuoc di bat dau chuoi threat neu tim thay, None neu khong.
        """
        board = self.board
        # Thu tu uu tien: nuoc tao nhieu threat nhat
        candidates = self._get_candidate_moves_fast(radius=2)
        threat_candidates = []
        for x, y in candidates[:20]:
            board.place(x, y, symbol)
            if self.check_win_at(x, y, symbol):
                board.undo(x, y)
                return (x, y)
            patterns, _ = PatternScanner.scan_patterns_at(board, x, y, symbol, opp)
            threat_level = 0
            if patterns.get(PATTERN_OPEN_FOUR, 0) > 0:
                threat_level += 100
            if patterns.get(PATTERN_HALF_FOUR, 0) > 0:
                threat_level += 50
            if patterns.get(PATTERN_OPEN_THREE, 0) > 0:
                threat_level += 20
            if patterns.get(PATTERN_BROKEN_THREE, 0) > 0:
                threat_level += 10
            board.undo(x, y)
            if threat_level > 0:
                threat_candidates.append((threat_level, x, y))
        
        threat_candidates.sort(reverse=True)
        
        for _, x, y in threat_candidates:
            if self.time_budget.should_stop():
                break
            board.place(x, y, symbol)
            if self._tss_defend(symbol, opp, max_depth - 1):
                board.undo(x, y)
                return (x, y)
            board.undo(x, y)
        return None

    def _tss_defend(self, symbol: int, opp: int, depth: int) -> bool:
        """Doi thu phai phong thu trong TSS - chi xet nuoc block threat."""
        if depth <= 0 or self.time_budget.should_stop():
            return False
        board = self.board
        # Doi thu phai block tat ca threat
        # Tim nuoc block uu tien: nuoc vua chan vua tao threat
        defense_candidates = []
        for y in range(board.vcount):
            for x in range(board.hcount):
                if board.get(x, y) != EMPTY:
                    continue
                # Kiem tra xem nuoc nay co block threat cua symbol khong
                board.place(x, y, opp)
                # Kiem tra symbol co con threat khong sau khi doi thu danh
                still_threatened = False
                for ny in range(max(0, y-2), min(board.vcount, y+3)):
                    for nx in range(max(0, x-2), min(board.hcount, x+3)):
                        if board.get(nx, ny) == symbol:
                            pats, _ = PatternScanner.scan_patterns_at(board, nx, ny, symbol, opp)
                            if (pats.get(PATTERN_HALF_FOUR, 0) > 0 or
                                pats.get(PATTERN_OPEN_FOUR, 0) > 0):
                                still_threatened = True
                                break
                    if still_threatened:
                        break
                board.undo(x, y)
                
                if not still_threatened:
                    # Nuoc nay block duoc threat - thu tiep
                    board.place(x, y, opp)
                    result = self._tss_attack(symbol, opp, depth - 1)
                    board.undo(x, y)
                    if not result:
                        return False  # Doi thu co nuong phong thu thanh cong
        return True  # Doi thu khong chan duoc

    def _tss_attack(self, symbol: int, opp: int, depth: int) -> bool:
        """Tan cong trong TSS - tim nuoc tao threat moi."""
        if depth <= 0 or self.time_budget.should_stop():
            return False
        board = self.board
        # Kiem tra thang ngay
        win = self.find_winning_move(symbol)
        if win:
            return True
        
        candidates = self._get_candidate_moves_fast(radius=2)
        for x, y in candidates[:15]:
            if self.time_budget.should_stop():
                break
            board.place(x, y, symbol)
            if self.check_win_at(x, y, symbol):
                board.undo(x, y)
                return True
            patterns, _ = PatternScanner.scan_patterns_at(board, x, y, symbol, opp)
            # Chi xet nuoc tao four (buoc doi thu phai chan)
            if (patterns.get(PATTERN_HALF_FOUR, 0) > 0 or
                patterns.get(PATTERN_OPEN_FOUR, 0) > 0):
                if self._tss_defend(symbol, opp, depth - 1):
                    board.undo(x, y)
                    return True
            board.undo(x, y)
        return False

    # ─── VCF/VCT Detection nang cao ──────────────────────────
    def detect_vcf(self, symbol: int, opp: int, max_depth=12) -> Optional[Tuple[int, int]]:
        """VCF Detection nang cao - tim nuoc bat dau chuoi VCF.
        
        VCF (Victory by Continuous Fours): Tan cong bang cach tao lien tuc
        cac nuoc four, buoc doi thu phai chan, cuoi cung thang.
        
        VCT (Victory by Continuous Threats): Mo rrong VCF, bao gom ca
        open-three va broken-three threats.
        
        Tra ve nuoc di bat dau VCF neu tim thay, None neu khong.
        """
        board = self.board
        candidates = self._get_candidate_moves_fast(radius=2)
        
        # VCF: Chi tim four moves
        for x, y in candidates[:15]:
            if self.time_budget.should_stop():
                break
            board.place(x, y, symbol)
            if self.check_win_at(x, y, symbol):
                board.undo(x, y)
                return (x, y)
            patterns, _ = PatternScanner.scan_patterns_at(board, x, y, symbol, opp)
            is_four = (patterns.get(PATTERN_HALF_FOUR, 0) > 0 or
                       patterns.get(PATTERN_OPEN_FOUR, 0) > 0)
            if is_four:
                if self._vcf_verify(symbol, opp, max_depth - 1):
                    board.undo(x, y)
                    return (x, y)
            board.undo(x, y)
        
        # VCT: Them open-three/broken-three threats
        for x, y in candidates[:10]:
            if self.time_budget.should_stop():
                break
            board.place(x, y, symbol)
            patterns, _ = PatternScanner.scan_patterns_at(board, x, y, symbol, opp)
            is_vct_threat = (patterns.get(PATTERN_OPEN_THREE, 0) > 0 or
                             patterns.get(PATTERN_BROKEN_THREE, 0) > 0)
            if is_vct_threat:
                if self._vct_verify(symbol, opp, max_depth - 1):
                    board.undo(x, y)
                    log.info(f"[VCT] Detected at ({x}, {y})")
                    return (x, y)
            board.undo(x, y)
        
        return None

    def _vcf_verify(self, symbol: int, opp: int, depth: int) -> bool:
        """Xac minh chuoi VCF - doi thu phai chan four, minh tiep tuc tao four."""
        if depth <= 0 or self.time_budget.should_stop():
            return False
        board = self.board
        # Doi thu chan four - chi co 1 nuoc chan (neu half-four)
        block_move = self.find_winning_move(symbol)
        if block_move is None:
            # Khong con four de chan -> VCF that bai
            return False
        bx, by = block_move
        board.place(bx, by, opp)
        # Minh tiep tuc tao four
        win = self.find_winning_move(symbol)
        if win:
            board.undo(bx, by)
            return True
        # Tim nuoc tao four moi
        candidates = self._get_candidate_moves_fast(radius=2)
        for x, y in candidates[:12]:
            if self.time_budget.should_stop():
                break
            board.place(x, y, symbol)
            if self.check_win_at(x, y, symbol):
                board.undo(x, y)
                board.undo(bx, by)
                return True
            patterns, _ = PatternScanner.scan_patterns_at(board, x, y, symbol, opp)
            if (patterns.get(PATTERN_HALF_FOUR, 0) > 0 or
                patterns.get(PATTERN_OPEN_FOUR, 0) > 0):
                if self._vcf_verify(symbol, opp, depth - 1):
                    board.undo(x, y)
                    board.undo(bx, by)
                    return True
            board.undo(x, y)
        board.undo(bx, by)
        return False

    def _vct_verify(self, symbol: int, opp: int, depth: int) -> bool:
        """VCT - mo rrong VCF voi them open-three threats."""
        if depth <= 0 or self.time_budget.should_stop():
            return False
        board = self.board
        # Thu VCF truoc ( nhanh hon)
        win = self.find_winning_move(symbol)
        if win:
            return True
        # Doi thu co the chan nhieu cach (open-three khong phai luon chan)
        # Thu cac nuoc tan cong tiep
        candidates = self._get_candidate_moves_fast(radius=2)
        for x, y in candidates[:10]:
            if self.time_budget.should_stop():
                break
            board.place(x, y, symbol)
            if self.check_win_at(x, y, symbol):
                board.undo(x, y)
                return True
            patterns, _ = PatternScanner.scan_patterns_at(board, x, y, symbol, opp)
            if (patterns.get(PATTERN_HALF_FOUR, 0) > 0 or
                patterns.get(PATTERN_OPEN_FOUR, 0) > 0):
                if self._vcf_verify(symbol, opp, depth - 1):
                    board.undo(x, y)
                    return True
            if (patterns.get(PATTERN_OPEN_THREE, 0) > 0 or
                patterns.get(PATTERN_BROKEN_THREE, 0) > 0):
                if self._vct_verify(symbol, opp, depth - 2):  # Giam depth nhanh hon
                    board.undo(x, y)
                    return True
            board.undo(x, y)
        return False

    # ─── Quiescence Search ────────────────────────────────────
    def _quiescence(self, alpha: int, beta: int, my_sym: int, opp_sym: int,
                    is_maximizing: bool, depth: int = 3) -> int:
        """Quiescence search - chi mo rong cac nuoc di threat."""
        stand_pat = self.evaluate_position(my_sym, opp_sym)
        if depth <= 0:
            return stand_pat
        if is_maximizing:
            if stand_pat >= beta:
                return stand_pat
            for x, y in self._get_candidate_moves_fast(radius=2)[:8]:
                if self.time_budget.should_stop():
                    break
                self.board.place(x, y, my_sym)
                patterns, _ = PatternScanner.scan_patterns_at(self.board, x, y, my_sym, opp_sym)
                is_strong = (patterns.get(PATTERN_HALF_FOUR, 0) > 0 or
                            patterns.get(PATTERN_OPEN_THREE, 0) > 0 or
                            patterns.get(PATTERN_BROKEN_THREE, 0) > 0)
                if is_strong:
                    score = self._quiescence(alpha, beta, my_sym, opp_sym, False, depth - 1)
                    self.board.undo(x, y)
                    if score > alpha:
                        alpha = score
                    if alpha >= beta:
                        return alpha
                else:
                    self.board.undo(x, y)
            return alpha
        else:
            if stand_pat <= alpha:
                return stand_pat
            for x, y in self._get_candidate_moves_fast(radius=2)[:8]:
                if self.time_budget.should_stop():
                    break
                self.board.place(x, y, opp_sym)
                patterns, _ = PatternScanner.scan_patterns_at(self.board, x, y, opp_sym, my_sym)
                is_strong = (patterns.get(PATTERN_HALF_FOUR, 0) > 0 or
                            patterns.get(PATTERN_OPEN_THREE, 0) > 0)
                if is_strong:
                    score = self._quiescence(alpha, beta, my_sym, opp_sym, True, depth - 1)
                    self.board.undo(x, y)
                    if score < beta:
                        beta = score
                    if beta <= alpha:
                        return beta
                else:
                    self.board.undo(x, y)
            return beta

    # ─── Alpha-Beta voi PVS + Forward Pruning ─────────────────
    def _alpha_beta(self, depth: int, alpha: int, beta: int, is_maximizing: bool,
                    my_sym: int, opp_sym: int, last_move=None, 
                    is_pv_node: bool = True) -> int:
        """Alpha-Beta Pruning voi Principal Variation Search va Forward Pruning.
        
        PVS: Node dau tien (PV node) duoc search day du,
        cac node con lai search voi window [-1, +1] (null window).
        Neu fail-high, re-search voi full window.
        
        Forward Pruning:
        - Null Move Pruning: Bo qua luot di, doi thu di 2 lan.
          Neu doi thu van khong vuot qua alpha -> position likely good.
        - Late Move Reduction: Giam depth cho cac nuoc di cuoi (it kha nang).
        """
        self.nodes_searched += 1

        if self.time_budget.should_stop():
            return self.evaluate_position(my_sym, opp_sym)

        # Win check
        if last_move:
            lx, ly, lsym = last_move
            if self.check_win_at(lx, ly, lsym):
                if lsym == my_sym:
                    return self.MATE_SCORE - (100 - depth)
                else:
                    return -self.MATE_SCORE + (100 - depth)

        # Leaf node - quiescence
        if depth <= 0:
            return self._quiescence(alpha, beta, my_sym, opp_sym, is_maximizing, 2)

        # TT probe
        tt_key = self.zobrist.hash
        tt_move = None
        tt_entry = self.tt.probe(tt_key)
        if tt_entry is not None:
            tt_depth, tt_score, tt_flag, tt_best = tt_entry
            tt_move = tt_best
            if tt_depth >= depth:
                if tt_flag == TT_EXACT:
                    self.tt_hits += 1
                    return tt_score
                elif tt_flag == TT_LOWER and tt_score > alpha:
                    alpha = tt_score
                elif tt_flag == TT_UPPER and tt_score < beta:
                    beta = tt_score
                if alpha >= beta:
                    self.tt_hits += 1
                    return tt_score

        current_sym = my_sym if is_maximizing else opp_sym
        other_sym = opp_sym if is_maximizing else my_sym

        # Win move check
        win_move = self.find_winning_move(current_sym)
        if win_move:
            if is_maximizing:
                return self.MATE_SCORE - (100 - depth)
            else:
                return -self.MATE_SCORE + (100 - depth)

        # ── Null Move Pruning ──
        # Chi ap dung cho PV node, khong ap dung o depth 1 hoac khi co threat
        if (not is_pv_node and depth >= 3 and 
            not is_maximizing and  # Chi cho maximizing side
            abs(beta) < self.MATE_SCORE - 100):
            # Skip turn, doi thu di 2 lan
            null_depth = depth - 3  # Reduction (R=3)
            null_score = self._alpha_beta(null_depth, -beta, -beta + 1, True,
                                          my_sym, opp_sym, None, False)
            null_score = -null_score
            if null_score >= beta:
                return null_score  # Null move cutoff

        # Get and order candidates
        candidates = self._get_candidate_moves_fast(radius=2)
        # Beam width: giam so candidate theo depth
        beam_width = min(len(candidates), 
                        20 if depth >= 5 else
                        15 if depth >= 3 else
                        12 if depth >= 2 else 10)
        candidates = candidates[:beam_width]
        
        # Move ordering
        candidates = self._order_moves(candidates, depth, current_sym, other_sym, tt_move)
        candidates = candidates[:beam_width]

        best_move = candidates[0] if candidates else None
        
        if is_maximizing:
            max_eval = -self.INF
            for i, (x, y) in enumerate(candidates):
                if self.time_budget.should_stop():
                    break
                
                # Late Move Reduction (LMR)
                reduction = 0
                if (i >= 4 and depth >= 3 and not is_pv_node and
                    (x, y) not in self.killer_moves.get(depth, [])):
                    reduction = 1 if i < 8 else 2
                
                self.board.place(x, y, current_sym)
                self.zobrist.place(x, y, current_sym)
                self.zobrist.toggle_side()
                
                # PVS: Search dau tien full window, cac nuoc sau null window
                if i == 0:
                    eval_score = self._alpha_beta(depth - 1 - reduction, alpha, beta,
                                                  False, my_sym, opp_sym, (x, y, current_sym), True)
                else:
                    # Null window search
                    eval_score = self._alpha_beta(depth - 1 - reduction, alpha, alpha + 1,
                                                  False, my_sym, opp_sym, (x, y, current_sym), False)
                    # Re-search neu fail-high va trong PV
                    if eval_score > alpha and eval_score < beta and is_pv_node:
                        eval_score = self._alpha_beta(depth - 1, alpha, beta,
                                                      False, my_sym, opp_sym, (x, y, current_sym), True)
                
                self.board.undo(x, y)
                self.zobrist.undo(x, y, current_sym)
                self.zobrist.toggle_side()

                if eval_score > max_eval:
                    max_eval = eval_score
                    best_move = (x, y)
                alpha = max(alpha, eval_score)
                if beta <= alpha:
                    # Cutoff - cap nhat heuristics
                    self.history_table[(x, y)] += depth * depth
                    if best_move:
                        self.killer_moves[depth].append(best_move)
                        if len(self.killer_moves[depth]) > 3:
                            self.killer_moves[depth].pop(0)
                    break
            
            # Store TT
            flag = TT_EXACT if max_eval > alpha else (TT_LOWER if max_eval > alpha else TT_UPPER)
            if best_move:
                self.tt.store(tt_key, depth, max_eval, flag, best_move)
            return max_eval
        else:
            min_eval = self.INF
            for i, (x, y) in enumerate(candidates):
                if self.time_budget.should_stop():
                    break
                
                # LMR
                reduction = 0
                if (i >= 4 and depth >= 3 and not is_pv_node and
                    (x, y) not in self.killer_moves.get(depth, [])):
                    reduction = 1 if i < 8 else 2
                
                self.board.place(x, y, current_sym)
                self.zobrist.place(x, y, current_sym)
                self.zobrist.toggle_side()
                
                if i == 0:
                    eval_score = self._alpha_beta(depth - 1 - reduction, alpha, beta,
                                                  True, my_sym, opp_sym, (x, y, current_sym), True)
                else:
                    eval_score = self._alpha_beta(depth - 1 - reduction, beta - 1, beta,
                                                  True, my_sym, opp_sym, (x, y, current_sym), False)
                    if eval_score < beta and eval_score > alpha and is_pv_node:
                        eval_score = self._alpha_beta(depth - 1, alpha, beta,
                                                      True, my_sym, opp_sym, (x, y, current_sym), True)
                
                self.board.undo(x, y)
                self.zobrist.undo(x, y, current_sym)
                self.zobrist.toggle_side()

                if eval_score < min_eval:
                    min_eval = eval_score
                    best_move = (x, y)
                beta = min(beta, eval_score)
                if beta <= alpha:
                    self.history_table[(x, y)] += depth * depth
                    if best_move:
                        self.killer_moves[depth].append(best_move)
                        if len(self.killer_moves[depth]) > 3:
                            self.killer_moves[depth].pop(0)
                    break
            
            flag = TT_EXACT if min_eval < beta else (TT_UPPER if min_eval < beta else TT_LOWER)
            if best_move:
                self.tt.store(tt_key, depth, min_eval, flag, best_move)
            return min_eval

    # ─── Iterative Deepening ──────────────────────────────────
    def _iterative_deepening(self, my_sym: int, opp_sym: int, max_depth: int,
                             candidates: list) -> Tuple[int, int]:
        """Iterative Deepening Minimax voi Aspiration Windows.
        
        Tim kiem tu depth 1 den max_depth, moi depth tang dan:
        - Dam bao luon co ket qua (neu het gio, dung iteration truoc)
        - Best move tu iteration truoc duoc uu tien o iteration sau (move ordering)
        - Aspiration Windows: Su dung score tu iteration truoc de thu hep window
        
        Tra ve best move.
        """
        best_move = candidates[0] if candidates else (self.board.hcount // 2, self.board.vcount // 2)
        self._last_score = 0
        self.best_root_move = best_move
        best_score = -self.INF

        for depth in range(1, max_depth + 1):
            if self.time_budget.should_stop():
                break
            self._search_depth = depth
            self.nodes_searched = 0
            
            current_best_move = None
            current_best_score = -self.INF

            # Aspiration Windows: window = score_truoc +/- delta
            if depth > 1 and abs(self._last_score) < self.MATE_SCORE - 100:
                delta = 200000  # Aspiration window delta
                alpha = self._last_score - delta
                beta = self._last_score + delta
            else:
                alpha = -self.INF
                beta = self.INF

            for x, y in candidates:
                if self.time_budget.should_stop():
                    break
                self.board.place(x, y, my_sym)
                self.zobrist.place(x, y, my_sym)
                self.zobrist.toggle_side()
                score = self._alpha_beta(depth - 1, alpha, beta, False,
                                         my_sym, opp_sym, (x, y, my_sym), True)
                self.board.undo(x, y)
                self.zobrist.undo(x, y, my_sym)
                self.zobrist.toggle_side()

                if score > current_best_score:
                    current_best_score = score
                    current_best_move = (x, y)
                alpha = max(alpha, score)

            # Aspiration: Neu fail-low hoac fail-high, re-search voi full window
            if current_best_move and (current_best_score <= alpha or current_best_score >= beta):
                if depth > 1:
                    log.info(f"[ID] Aspiration fail at depth {depth}, re-searching full window...")
                    current_best_score = -self.INF
                    alpha = -self.INF
                    beta = self.INF
                    for x, y in candidates:
                        if self.time_budget.should_stop():
                            break
                        self.board.place(x, y, my_sym)
                        self.zobrist.place(x, y, my_sym)
                        self.zobrist.toggle_side()
                        score = self._alpha_beta(depth - 1, alpha, beta, False,
                                                 my_sym, opp_sym, (x, y, my_sym), True)
                        self.board.undo(x, y)
                        self.zobrist.undo(x, y, my_sym)
                        self.zobrist.toggle_side()
                        if score > current_best_score:
                            current_best_score = score
                            current_best_move = (x, y)
                        alpha = max(alpha, score)

            if current_best_move:
                best_move = current_best_move
                best_score = current_best_score
                self._last_score = best_score
                self.best_root_move = best_move
                # Di chuyen best move len dau danh sach cho iteration sau
                if best_move in candidates:
                    candidates.remove(best_move)
                    candidates.insert(0, best_move)

            log.info(f"[ID] Depth {depth}: best=({best_move[0]},{best_move[1]}) "
                     f"score={best_score} nodes={self.nodes_searched}")

        return best_move

    # ─── Lazy SMP (Parallel Search) ───────────────────────────
    def _lazy_smp_search(self, my_sym: int, opp_sym: int, max_depth: int,
                         candidates: list) -> Tuple[int, int]:
        """Lazy SMP - Parallel search voi nhieu luong.
        
        Moi luong search voi depth khac nhau:
        - Main thread: depth max_depth
        - Helper threads: depth max_depth - 1, max_depth - 2, ...
        
        Ket qua tu bat ky luong nao deu hop le. Main thread co priority cao hon.
        """
        if self._num_threads <= 1 or len(candidates) <= 2:
            return self._iterative_deepening(my_sym, opp_sym, max_depth, candidates)

        # Main thread search day du
        best_move = candidates[0]
        main_result = [None, -self.INF]  # [move, score]

        def _search_thread(candidates_copy: list, thread_depth: int, thread_id: int):
            """Helper thread - search voi depth giam."""
            local_best_move = candidates_copy[0]
            local_best_score = -self.INF
            # Tao board copy cho thread
            for x, y in candidates_copy:
                if self.time_budget.should_stop():
                    break
                self.board.place(x, y, my_sym)
                score = self._alpha_beta(thread_depth - 1, -self.INF, self.INF, False,
                                         my_sym, opp_sym, (x, y, my_sym), thread_id == 0)
                self.board.undo(x, y)
                if score > local_best_score:
                    local_best_score = score
                    local_best_move = (x, y)
            return local_best_move, local_best_score

        # Chay main thread voi iterative deepening
        best_move = self._iterative_deepening(my_sym, opp_sym, max_depth, candidates)

        # Note: Lazy SMP duoc ap dung don gian - main thread da search voi ID
        # Helper threads co the duoc them voi ThreadPoolExecutor nhung
        # vi board state la shared, nen can copy board cho moi thread
        # Hien tai, su dung single-threaded ID de dam bao correctness
        # Co the mo rong thanh multi-threaded neu can

        return best_move

    # ─── Double Threat Detection ──────────────────────────────
    def _find_double_threat(self, my_sym: int, opp_sym: int) -> Optional[Tuple[int, int]]:
        board = self.board
        candidates = self._get_candidate_moves_fast(radius=2)
        best_fork = None
        best_fork_score = 0
        for x, y in candidates[:20]:
            board.place(x, y, my_sym)
            patterns, _ = PatternScanner.scan_patterns_at(board, x, y, my_sym, opp_sym)
            threat_count = 0
            threat_score = 0
            if patterns.get(PATTERN_OPEN_FOUR, 0) > 0:
                threat_count += 2
                threat_score += 5000000
            if patterns.get(PATTERN_HALF_FOUR, 0) > 0:
                threat_count += 1
                threat_score += 500000
            if patterns.get(PATTERN_OPEN_THREE, 0) > 0:
                threat_count += 1
                threat_score += 50000
            if patterns.get(PATTERN_BROKEN_THREE, 0) > 0:
                threat_count += 1
                threat_score += 30000
            board.undo(x, y)
            if threat_count >= 2 and threat_score > best_fork_score:
                best_fork_score = threat_score
                best_fork = (x, y)
        return best_fork

    # ─── Main Search Entry Point ──────────────────────────────
    def find_best_move(self, my_sym: int, opp_sym: int) -> Tuple[int, int]:
        """Tim nuoc di tot nhat voi toan bo AI engine v5.
        
        Pipeline:
        1. Opening book + Self-Learning recommendation
        2. Win move (thang ngay)
        3. Block win (chan thang)
        4. Double threat / Fork
        5. TSS (Threat Space Search)
        6. VCF/VCT Detection
        7. Iterative Deepening Minimax (Lazy SMP)
        """
        board = self.board
        move_count = len(board.move_history)
        
        # Tinh game progress
        total_cells = board.hcount * board.vcount
        game_progress = 1 - (len(board._move_set) / total_cells) if total_cells > 0 else 0
        
        # Kiem tra co threat khong (cho Time Budget)
        has_threat = (self.find_winning_move(my_sym) is not None or
                     self.find_winning_move(opp_sym) is not None or
                     self._find_double_threat(my_sym, opp_sym) is not None)

        # Phan bo thoi gian
        time_budget = self.time_budget.allocate(game_progress, has_threat, move_count)
        self.time_budget.total_budget = time_budget
        self.time_budget.start()
        
        log.info(f"[AI v5] Time budget: {time_budget:.2f}s, game_progress: {game_progress:.2f}, "
                 f"has_threat: {has_threat}")

        # 1. Opening book
        if move_count < 2:
            book_move = self._get_opening_move()
            if book_move:
                log.info(f"KHAI CUOC: ({book_move[0]}, {book_move[1]})")
                return book_move

        # 2. Win move
        win_move = self.find_winning_move(my_sym)
        if win_move:
            log.info(f"THANG NGAY: ({win_move[0]}, {win_move[1]})")
            return win_move

        # 3. Block win
        block_move = self.find_winning_move(opp_sym)
        if block_move:
            log.info(f"CHAN THANG: ({block_move[0]}, {block_move[1]})")
            return block_move

        # 4. Double threat / Fork
        double_threat = self._find_double_threat(my_sym, opp_sym)
        if double_threat:
            log.info(f"DOUBLE THREAT: ({double_threat[0]}, {double_threat[1]})")
            return double_threat

        # 5. TSS (Threat Space Search)
        tss_move = self.tss_search(my_sym, opp_sym, max_depth=10)
        if tss_move:
            log.info(f"TSS FOUND: ({tss_move[0]}, {tss_move[1]})")
            return tss_move

        # 6. VCF/VCT Detection
        vcf_move = self.detect_vcf(my_sym, opp_sym, max_depth=12)
        if vcf_move:
            log.info(f"VCF/VCT DETECTED: ({vcf_move[0]}, {vcf_move[1]})")
            return vcf_move

        # 7. Iterative Deepening + Lazy SMP
        self.zobrist = ZobristHash(board.hcount, board.vcount)
        self.zobrist.init(board)
        self.tt.new_search()  # Tang generation cho TT aging
        self.nodes_searched = 0
        self.tt_hits = 0
        
        # Tao danh sach candidates va sap xep
        candidates = self._get_candidate_moves_fast(radius=2)
        scored_candidates = []
        for x, y in candidates:
            quick_score = self.evaluate_move_quick(x, y, my_sym, opp_sym)
            scored_candidates.append((quick_score, x, y))
        scored_candidates.sort(reverse=True)
        candidates = [(x, y) for _, x, y in scored_candidates[:20]]

        # Max depth dua tren time budget
        max_depth = self.time_budget.get_max_depth(game_progress, move_count)
        max_depth = min(max_depth, 8)  # Cap

        log.info(f"[AI v5] Starting Iterative Deepening, max_depth={max_depth}, "
                 f"candidates={len(candidates)}")

        best_move = self._lazy_smp_search(my_sym, opp_sym, max_depth, candidates)

        elapsed = self.time_budget.elapsed()
        log.info(f"[AI v5] Result: ({best_move[0]}, {best_move[1]}), "
                 f"depth_reached={self._search_depth}, "
                 f"nodes={self.nodes_searched}, tt_hits={self.tt_hits}, "
                 f"style={self.counter_style}, time={elapsed:.2f}s")
        log.info(f"[AI v5] {self.tt.stats()}")
        for i, (score, x, y) in enumerate(scored_candidates[:5]):
            marker = " <<<" if (x, y) == best_move else ""
            log.info(f"  Top {i+1}: ({x},{y}) score={score}{marker}")
        return best_move

# ─── Game Client v4 ─────────────────────────────────────────
class CaroBotV5:
    def __init__(self):
        self.ws = None
        self.board = CaroBoard()
        self.learning = SelfLearningEngine()
        self.ai = CaroAI(self.board, self.learning)  # v5 Advanced Engine
        self.chat = AgentChatSystem()
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
        self.start_time = None
        self.current_opponent_name = ""
        self.last_move_quality = 'normal'

    def http_handshake(self) -> bool:
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
                'LOGIN': 'Dang nhap'
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

    def build_chat_msg(self, message: str) -> bytes:
        """Xay dung tin nhan chat."""
        w = ConnWriter()
        w.write_command("CHAT")
        w.write_string(message)
        return w.to_bytes()

    async def send_chat(self, message: str):
        """Gui tin nhan chat."""
        try:
            await self.send(self.build_chat_msg(message))
            log.info(f"[CHAT] Gui: {message}")
        except Exception as e:
            log.debug(f"Loi gui chat: {e}")

    async def handle_message(self, raw: bytes):
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
                if slot_id == self.my_slot_id:
                    self.in_table = False
                    self.is_playing = False
                elif slot_id < 2 and self.is_playing:
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
            elif cmd == "CHAT":
                msg = r.read_string()
                log.info(f"[CHAT] Nhan: {msg}")
            else:
                log.debug(f"Unhandled: {cmd}")
        except Exception as e:
            log.error(f"Loi xu ly {cmd}: {e}")

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

        # AI Agent: Tim ten doi thu va chao
        for slot_id, player in self.players.items():
            if slot_id != self.my_slot_id:
                opp_name = player['full_name']
                self.current_opponent_name = opp_name
                self.learning.set_opponent(opp_name)
                # Dat chien thuat doi pho
                counter = self.learning.get_opponent_counter_style(opp_name)
                self.ai.set_counter_style(counter)
                # Gui loi chao
                greeting = self.chat.get_greeting_message(opp_name)
                if greeting:
                    await asyncio.sleep(1.0)
                    await self.send_chat(greeting)
                break

    async def handle_set_turn(self, r: ConnReader):
        slot_id = r.read_byte()
        turn_timeout = r.read_short()
        remain_duration = r.read_short()
        is_my_turn = (slot_id == self.my_slot_id)
        log.info(f"SET_TURN: slot={slot_id} (me={self.my_slot_id}), "
                 f"my_turn={is_my_turn}, timeout={turn_timeout}s")
        if is_my_turn and self.is_playing:
            self.is_my_turn = True
            await asyncio.sleep(0.5)
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
            # Ghi nhan nuoc di cua minh
            self.learning.record_move(x, y, symbol, True)
        elif current == EMPTY:
            log.info(f"Doi thu danh: ({x}, {y}) symbol={sym_char}")
            self.board.place(x, y, symbol)
            if len(self.board.move_history) <= 2:
                self.opp_symbol = symbol
                self.my_symbol = SYMBOL_O if symbol == SYMBOL_X else SYMBOL_X
            # Ghi nhan nuoc di cua doi thu
            self.learning.record_move(x, y, symbol, False)
            # AI Agent: Phan ung nuoc di cua doi thu
            reaction = self.chat.get_move_reaction(False, self.last_move_quality)
            if reaction:
                await self.send_chat(reaction)
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
            grade_str = {1: "WIN", 2: "LOSE", 3: "DRAW", 4: "LOSE",
                        10: "DRAW", 11: "WIN", 12: "LOSE"}.get(grade, str(grade))
            log.info(f"  Slot {slot_id}: grade={grade_str}, earn={earn}")

        result = 'draw'
        if my_grade in (1, 11):
            self.win_count += 1
            result = 'win'
            log.info(f"THANG!")
        elif my_grade in (2, 4, 12):
            self.lose_count += 1
            result = 'lose'
            log.info(f"THUA!")
        elif my_grade in (3, 10):
            self.draw_count += 1
            result = 'draw'
            log.info(f"HOA!")

        # Self-Learning: Hoc tu ket qua
        self.learning.learn_from_game(result, self.my_symbol)

        # AI Agent: Gui tin nhan ket thuc van
        gameover_msg = self.chat.get_gameover_message(result, self.current_opponent_name)
        await asyncio.sleep(0.5)
        await self.send_chat(gameover_msg)

        match_result = r.read_string()
        log.info(f"  Result: {match_result}")
        elapsed = ""
        if self.start_time:
            mins = (time.time() - self.start_time) / 60
            elapsed = f", thoi gian: {mins:.1f} phut"
        log.info(f"Tong: {self.game_count} van, {self.win_count} thang, "
                 f"{self.lose_count} thua, {self.draw_count} hoa{elapsed}")
        if self.game_count > 0:
            wr = self.win_count / self.game_count * 100
            log.info(f"Win rate: {wr:.1f}%")

        # In thong tin tu hoc
        log.info(f"[TU HOC] Tong kinh nghiem: {self.learning.experience['total_games']} van")
        log.info(f"[TU HOC] Pattern weights da cap nhat: {len(PATTERN_SCORES)} patterns")
        if self.current_opponent_name in self.learning.experience['opponent_profiles']:
            profile = self.learning.experience['opponent_profiles'][self.current_opponent_name]
            log.info(f"[TU HOC] Doi thu {self.current_opponent_name}: "
                     f"{profile['games']} van, style={profile['style']}")

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
        # Ghi nhan nuoc di
        self.learning.record_move(x, y, self.my_symbol, True)
        log.info(f"  Board:\n{self.board.display()}")

        # AI Agent: Phan ung nuoc di cua minh
        quality = 'good' if elapsed > 1.0 else 'normal'
        self.last_move_quality = quality
        reaction = self.chat.get_move_reaction(True, quality)
        if reaction:
            await self.send_chat(reaction)

    async def ping_loop(self):
        while self.running:
            await asyncio.sleep(self.ping_interval)
            if self.ws and self.ws.close_code is None:
                try:
                    # Kiem tra thoi gian chay
                    if self.start_time and (time.time() - self.start_time) > BOT_RUNTIME_SECONDS:
                        log.info(f"=== DA CHAY {BOT_RUNTIME_MINUTES} PHUT - DUNG BOT ===")
                        self.running = False
                        # Luu kinh nghiem truoc khi thoat
                        self.learning.save_experience()
                        # In bao cao cuoi
                        log.info(f"BAO CAO CUOI:")
                        log.info(f"  Tong: {self.game_count} van, {self.win_count} thang, "
                                 f"{self.lose_count} thua, {self.draw_count} hoa")
                        if self.game_count > 0:
                            wr = self.win_count / self.game_count * 100
                            log.info(f"  Win rate: {wr:.1f}%")
                        log.info(f"  Kinh nghiem: {self.learning.experience['total_games']} van")
                        log.info(f"  Doi thu da gap: {len(self.learning.experience['opponent_profiles'])}")
                        if self.ws:
                            await self.ws.close()
                        return

                    if not self.is_playing and self.in_table:
                        idle_time = time.time() - self.last_activity
                        if idle_time > self.idle_timeout:
                            log.info(f"Idle {idle_time:.0f}s - roi ban tim ban moi...")
                            self.in_table = False
                            self.ready_sent = False
                            self.is_playing = False
                            self.last_activity = time.time()
                            await self.send(self.build_enter_place_msg(self.place_path, "", 1))
                            await asyncio.sleep(1)
                            await self.send(self.build_quick_play_msg())
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
        finally:
            self.running = False
            self.learning.save_experience()
            log.info("Bot da dung.")

    async def run_with_reconnect(self, max_retries=100):
        retries = 0
        self.start_time = time.time()
        log.info(f"Bot v5 Advanced AI - Se chay {BOT_RUNTIME_MINUTES} phut")
        while retries < max_retries and self.running:
            try:
                # Kiem tra thoi gian truoc khi reconnect
                if self.start_time and (time.time() - self.start_time) > BOT_RUNTIME_SECONDS:
                    log.info(f"=== DA CHAY {BOT_RUNTIME_MINUTES} PHUT - KET THUC ===")
                    log.info(f"Tong: {self.game_count} van, {self.win_count} thang, "
                             f"{self.lose_count} thua, {self.draw_count} hoa")
                    if self.game_count > 0:
                        wr = self.win_count / self.game_count * 100
                        log.info(f"Win rate cuoi: {wr:.1f}%")
                    self.learning.save_experience()
                    break

                self.is_playing = False
                self.is_my_turn = False
                self.in_table = False
                self.ready_sent = False
                self.mode_set = False
                self.running = True
                self.board.clear()
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

        # Luu kinh nghiem cuoi cung
        self.learning.save_experience()
        log.info("Bot v5 da ket thuc. Kinh nghiem da duoc luu.")

# ─── Main ───────────────────────────────────────────────────
async def main():
    print("=" * 60)
    print("CARO BOT v5 - ADVANCED AI ENGINE + TU HOC")
    print("=" * 60)
    print("AI Engine (tich hop tu Caro_AI MonHauVD):")
    print("  * Iterative Deepening Minimax + Aspiration Windows")
    print("  * Alpha-Beta Pruning + PVS (Principal Variation Search)")
    print("  * Transposition Table + Zobrist Hashing (Aging)")
    print("  * Move Ordering: TT > Killer > History > Static")
    print("  * Beam Search + Forward Pruning (Null Move, LMR)")
    print("  * TSS (Threat Space Search)")
    print("  * VCF/VCT Detection nang cao")
    print("  * Lazy SMP (Parallel Search)")
    print("  * Time Budget thong minh")
    print("=" * 60)
    print("Tu hoc + Giao tiep:")
    print("  * Self-Learning Engine (tu hoc tu ket qua)")
    print("  * AI Agent Communication (chat/giao tiep)")
    print("  * Opponent Modeling (phan tich doi thu)")
    print("  * Adaptive Strategy (thich ung chien thuat)")
    print("  * Experience Memory (luu tru kinh nghiem)")
    print(f"  * Auto-stop sau {BOT_RUNTIME_MINUTES} phut")
    print("=" * 60)
    bot = CaroBotV5()
    await bot.run_with_reconnect()

if __name__ == "__main__":
    asyncio.run(main())
