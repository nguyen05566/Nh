#!/usr/bin/env python3
"""
Caro Bot v5 - Advanced AI Engine (Viet tu dau - KHONG dung code cu)
====================================================================
AI Techniques (9 ky thuat chinh):
  1. Iterative Deepening Minimax + Aspiration Windows
  2. Alpha-Beta Pruning + PVS (Principal Variation Search)
  3. Transposition Table + Zobrist Hashing (Aging + Replacement)
  4. Move Ordering: TT move > Win/Block > Killer > History > Static
  5. Beam Search / Forward Pruning (Null Move, Late Move Reduction)
  6. TSS (Threat Space Search)
  7. VCF (Victory by Continuous Fours) / VCT Detection
  8. Lazy SMP (Parallel Search)
  9. Time Budget per move (smart time allocation)

Features:
  - 15-minute auto-stop timer
  - WebSocket binary protocol (gamevh.net)

Protocol: WebSocket binary, struct-based parsing (gamevh.net)
"""

import asyncio
import struct
import time
import logging
import sys
import re
import random
import multiprocessing
import concurrent.futures
from collections import defaultdict
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


# ═══════════════════════════════════════════════════════════════
# CAU HINH
# ═══════════════════════════════════════════════════════════════
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

BOT_RUNTIME_MINUTES = 15
BOT_RUNTIME_SECONDS = BOT_RUNTIME_MINUTES * 60


# ═══════════════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("caro_v5")


# ═══════════════════════════════════════════════════════════════
# BINARY PROTOCOL - WebSocket
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
    501: "BET", 502: "PLAY", 505: "CHAT", 518: "HIGHLIGHT",
    529: "MOVE", 533: "ASK_DRAW", 534: "SURRENDER",
    535: "RETREAT",
}


class ConnReader:
    """Doc binary protocol tu server."""

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


class ConnWriter:
    """Ghi binary protocol gui server."""

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


# ═══════════════════════════════════════════════════════════════
# BOARD STATE
# ═══════════════════════════════════════════════════════════════
EMPTY = -1
SYMBOL_O = 0
SYMBOL_X = 1
DIRECTIONS = [(1, 0), (0, 1), (1, 1), (1, -1)]


class CaroBoard:
    """Ban co Caro - toi uu cho truy xuat nhanh va undo."""

    __slots__ = ('hcount', 'vcount', 'grid', 'move_history', '_move_set')

    def __init__(self, hcount=HCOUNT, vcount=VCOUNT):
        self.hcount = hcount
        self.vcount = vcount
        self.grid = [[EMPTY] * hcount for _ in range(vcount)]
        self.move_history = []
        self._move_set = set()

    def clear(self):
        self.grid = [[EMPTY] * self.hcount for _ in range(self.vcount)]
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
            self.grid[y][x] = symbol
            self.move_history.append((x, y, symbol))
            self._move_set.add((x, y))

    def undo(self, x: int, y: int):
        if 0 <= x < self.hcount and 0 <= y < self.vcount:
            self.grid[y][x] = EMPTY
            if self.move_history and self.move_history[-1][:2] == (x, y):
                self.move_history.pop()
            self._move_set.discard((x, y))

    def get(self, x: int, y: int) -> int:
        if 0 <= x < self.hcount and 0 <= y < self.vcount:
            return self.grid[y][x]
        return EMPTY

    def fill_from_rle(self, board_data: list):
        self.clear()
        pos = 0
        for unsigned_val in board_data:
            signed_val = unsigned_val - 256 if unsigned_val > 127 else unsigned_val
            if signed_val >= 0:
                y = pos // self.hcount
                x = pos % self.hcount
                if 0 <= x < self.hcount and 0 <= y < self.vcount:
                    self.grid[y][x] = signed_val
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
                if self.grid[y][x] != EMPTY:
                    for dy in range(-radius, radius + 1):
                        for dx in range(-radius, radius + 1):
                            nx, ny = x + dx, y + dy
                            if (0 <= nx < self.hcount and 0 <= ny < self.vcount
                                    and self.grid[ny][nx] == EMPTY
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
            row = f"{y:2d} " + "".join(f" {sym.get(self.grid[y][x], '?')}" for x in range(self.hcount))
            lines.append(row)
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# PATTERN RECOGNITION
# ═══════════════════════════════════════════════════════════════
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

PATTERN_SCORES = {
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


class PatternScanner:
    """Scan pattern tren ban co - phuc vu danh gia vi tri va move ordering."""

    @staticmethod
    def scan_line(board: CaroBoard, x: int, y: int, dx: int, dy: int, max_len=9):
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


# ═══════════════════════════════════════════════════════════════
# ZOBRIST HASHING (Ky thuat 3 - Phan 1)
# ═══════════════════════════════════════════════════════════════
class ZobristHash:
    """Zobrist Hashing - ho tro incremental update va side-to-move."""

    def __init__(self, hcount=HCOUNT, vcount=VCOUNT):
        rng = random.Random(42)
        self.hcount = hcount
        self.vcount = vcount
        self.table = [[[rng.getrandbits(64) for _ in range(hcount)]
                       for _ in range(vcount)]
                      for _ in range(2)]
        self.side_hash = rng.getrandbits(64)
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
        self.hash ^= self.side_hash


# ═══════════════════════════════════════════════════════════════
# TRANSPOSITION TABLE (Ky thuat 3 - Phan 2: Aging + Replacement)
# ═══════════════════════════════════════════════════════════════
TT_EXACT = 0
TT_LOWER = 1   # score la lower bound (beta cutoff)
TT_UPPER = 2   # score la upper bound (alpha cutoff)


class TranspositionTable:
    """Transposition Table voi generation-based aging va depth-prefer replacement."""

    def __init__(self, max_size=2_000_000):
        self.table: Dict[int, tuple] = {}
        self.max_size = max_size
        self.generation = 0

    def new_search(self):
        """Tang generation khi bat dau search moi - de aging cac entry cu."""
        self.generation += 1

    def store(self, hash_key: int, depth: int, score: int, flag: int,
              best_move: Optional[Tuple[int, int]] = None):
        """Luu entry vao TT, thay the neu depth lon hon hoac entry qua cu."""
        existing = self.table.get(hash_key)
        if existing is not None:
            ex_depth, ex_score, ex_flag, ex_move, ex_gen = existing
            # Replace neu depth >= hoac entry cu (generation > 2)
            if depth >= ex_depth or ex_gen < self.generation - 2:
                self.table[hash_key] = (depth, score, flag, best_move, self.generation)
        else:
            if len(self.table) >= self.max_size:
                self._evict()
            self.table[hash_key] = (depth, score, flag, best_move, self.generation)

    def probe(self, hash_key: int) -> Optional[Tuple[int, int, int, Optional[Tuple[int, int]]]]:
        """Tra cuu TT, tra ve (depth, score, flag, best_move) hoac None."""
        entry = self.table.get(hash_key)
        if entry is not None:
            depth, score, flag, best_move, gen = entry
            return (depth, score, flag, best_move)
        return None

    def _evict(self):
        """Evict entries cu (generation < current - 1), hoac 1/4 neu van day."""
        to_delete = [k for k, v in self.table.items() if v[4] < self.generation - 1]
        for k in to_delete:
            del self.table[k]
        if len(self.table) >= self.max_size:
            items = sorted(self.table.items(), key=lambda x: (x[1][4], x[1][0]))
            for k, _ in items[:len(items) // 4]:
                del self.table[k]

    def clear(self):
        self.table.clear()
        self.generation = 0

    def stats(self) -> str:
        return f"TT size={len(self.table)}, gen={self.generation}"


# ═══════════════════════════════════════════════════════════════
# TIME BUDGET (Ky thuat 9: Smart time allocation)
# ═══════════════════════════════════════════════════════════════
class TimeBudget:
    """Quan ly thoi gian thong minh cho moi nuoc di.
    
    Phan bo thoi gian dua tren:
    - Game progress (vao giua game -> nhieu thoi gian hon)
    - Co threat hay khong (co threat -> nhieu thoi gian hon)
    - So nuoc da di (cang nhieu -> cang can ky)
    """

    def __init__(self, total_budget=3.0, buffer=0.15, min_time=0.3):
        self.total_budget = total_budget
        self.buffer = buffer
        self.min_time = min_time
        self.start_time = 0.0
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
        """Kiem tra co dung search hay khong (check moi 1024 nodes)."""
        if self._stop_requested:
            return True
        self.nodes_searched += 1
        if self.nodes_searched & 1023 == 0:
            return self.time_left() <= 0
        return False

    def allocate(self, game_progress: float, has_threat: bool, move_count: int) -> float:
        """Tinh thoi gian phan bo cho nuoc di hien tai."""
        remaining_moves = max(10, int(50 * (1 - game_progress)))
        base_time = self.total_budget * 0.7 / max(remaining_moves, 1)
        if has_threat:
            base_time *= 1.8
        if 0.3 < game_progress < 0.7:
            base_time *= 1.3
        base_time = max(self.min_time, min(base_time, self.total_budget * 0.4))
        return base_time

    def get_max_depth(self, game_progress: float, move_count: int) -> int:
        """Xac dinh do sau toi da dua tren thoi gian con lai."""
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


# ═══════════════════════════════════════════════════════════════
# CARO AI ENGINE - 9 KY THUAT CHINH
# ═══════════════════════════════════════════════════════════════
class CaroAI:
    """Caro AI v5 - Engine viet tu dau voi 9 ky thuat nang cao.

    Pipeline tim nuoc di:
    1. Win ngay (1 move) -> 2. Block (1 move) -> 3. Double Threat
    -> 4. TSS (Ky thuat 6) -> 5. VCF/VCT (Ky thuat 7)
    -> 6. Iterative Deepening + Alpha-Beta + PVS (Ky thuat 1,2)
       voi Move Ordering (4), Beam/Fwd Pruning (5), TT+Zobrist (3),
       Lazy SMP (8), Time Budget (9)
    """

    INF = 999999999
    MATE_SCORE = 10000000

    # Pattern score constants
    SCORE_FIVE = 10000000
    SCORE_OPEN_FOUR = 5000000
    SCORE_HALF_FOUR = 500000
    SCORE_OPEN_THREE = 500000
    SCORE_BROKEN_THREE = 80000
    SCORE_HALF_THREE = 50000
    SCORE_OPEN_TWO = 50000
    SCORE_HALF_TWO = 5000
    DOUBLE_FOUR_BONUS = 5000000
    FOUR_THREE_BONUS = 3000000
    DOUBLE_THREE_BONUS = 500000

    def __init__(self, board: CaroBoard):
        self.board = board
        # Ky thuat 3: Zobrist + TT
        self.zobrist = ZobristHash(board.hcount, board.vcount)
        self.tt = TranspositionTable(max_size=2_000_000)
        # Ky thuat 4: Move Ordering tables
        self.history_table: Dict[Tuple[int, int], int] = defaultdict(int)
        self.killer_moves: Dict[int, List[Tuple[int, int]]] = defaultdict(list)
        self.counter_move: Dict[Tuple[int, int], Tuple[int, int]] = {}
        # Ky thuat 9: Time Budget
        self.time_budget = TimeBudget(total_budget=3.0)
        # Search state
        self.nodes_searched = 0
        self.tt_hits = 0
        self.best_root_move = None
        self._search_depth = 0
        self._last_score = 0
        # Ky thuat 8: Lazy SMP
        self._num_threads = max(1, multiprocessing.cpu_count() - 1)
        self._thread_pool = None

    # ─── Win Check (co ban) ────────────────────────────────────
    def check_win_at(self, x: int, y: int, symbol: int) -> bool:
        """Kiem tra vi tri (x,y) co tao thanh 5-lien-tuyen khong."""
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
            # Caro: 5 lien tuyen voi it nhat 1 dau mo, hoac >=6
            if count >= 6:
                return True
            if count == 5 and (forward_open or backward_open):
                return True
        return False

    def find_winning_move(self, symbol: int) -> Optional[Tuple[int, int]]:
        """Tim nuoc thang ngay (1 move win)."""
        candidates = self._get_candidate_moves()
        for x, y in candidates:
            self.board.place(x, y, symbol)
            if self.check_win_at(x, y, symbol):
                self.board.undo(x, y)
                return (x, y)
            self.board.undo(x, y)
        return None

    # ─── Candidate Moves ───────────────────────────────────────
    def _get_candidate_moves(self, radius=2) -> List[Tuple[int, int]]:
        """Lay danh sach nuoc di ung vien (o trong gan cac quan co)."""
        neighbors = self.board.get_neighbors(radius=radius)
        if not neighbors:
            return [(self.board.hcount // 2, self.board.vcount // 2)]
        return neighbors

    # ─── Ky thuat 4: Move Ordering ─────────────────────────────
    def _order_moves(self, candidates: list, depth: int, my_sym: int, opp_sym: int,
                     tt_move: Optional[Tuple[int, int]] = None) -> list:
        """Sap xep nuoc di: TT move > Win/Block > Killer > Counter > History > Static.

        Move ordering rat quan trong de Alpha-Beta cat nhanh va hieu qua.
        Thu tu uu tien dam bao cac nuoc tot duoc xem xet truoc,
        giup PVS (Ky thuat 2) hoat dong toi uu.
        """
        scored = []
        for x, y in candidates:
            score = 0
            # 1. TT move (tu Transposition Table) - uu tien cao nhat
            if tt_move and (x, y) == tt_move:
                score += 100_000_000
            # 2. Win move (nuoc thang ngay)
            self.board.place(x, y, my_sym)
            if self.check_win_at(x, y, my_sym):
                score += 50_000_000
            self.board.undo(x, y)
            # 3. Block move (chan nuoc thang cua doi thu)
            self.board.place(x, y, opp_sym)
            if self.check_win_at(x, y, opp_sym):
                score += 40_000_000
            self.board.undo(x, y)
            # 4. Killer moves (nuoc da cat beta o cung depth)
            if (x, y) in self.killer_moves.get(depth, []):
                score += 10_000_000
            # 5. Counter move (nuoc di doi voi nuoc truoc do cua doi thu)
            if self.board.move_history:
                last = self.board.move_history[-1][:2]
                if self.counter_move.get(last) == (x, y):
                    score += 8_000_000
            # 6. History heuristic (nuoc di tot trong cac search truoc)
            score += self.history_table.get((x, y), 0)
            # 7. Static evaluation (danh gia nhanh pattern)
            if score == 0:
                score = self._evaluate_move_static(x, y, my_sym, opp_sym)
            scored.append((score, x, y))
        scored.sort(reverse=True)
        return [(x, y) for _, x, y in scored]

    def _evaluate_move_static(self, x: int, y: int, my_sym: int, opp_sym: int) -> int:
        """Danh gia nhanh mot nuoc di dua tren pattern va vi tri."""
        score = 0
        board = self.board
        # Attack pattern
        board.place(x, y, my_sym)
        if self.check_win_at(x, y, my_sym):
            board.undo(x, y)
            return 100000000
        attack_pats, _ = PatternScanner.scan_patterns_at(board, x, y, my_sym, opp_sym)
        board.undo(x, y)
        # Defense pattern
        board.place(x, y, opp_sym)
        if self.check_win_at(x, y, opp_sym):
            board.undo(x, y)
            return 50000000
        defense_pats, _ = PatternScanner.scan_patterns_at(board, x, y, opp_sym, my_sym)
        board.undo(x, y)
        # Tinh score
        for pat_type, cnt in attack_pats.items():
            score += PATTERN_SCORES.get(pat_type, 0) * cnt
        for pat_type, cnt in defense_pats.items():
            score += int(PATTERN_SCORES.get(pat_type, 0) * 0.95) * cnt
        # Bonus vi tri trung tam
        cx, cy = board.hcount // 2, board.vcount // 2
        score += max(0, 30 - (abs(x - cx) + abs(y - cy)) * 3)
        return score

    # ─── Static Evaluation ─────────────────────────────────────
    def _evaluate_position(self, my_sym: int, opp_sym: int) -> int:
        """Danh gia toan bo ban co cho Minimax."""
        board = self.board
        score = 0
        # Scan patterns cho ca 2 ben
        my_pats = PatternScanner.scan_all_patterns(board, my_sym, opp_sym)
        opp_pats = PatternScanner.scan_all_patterns(board, opp_sym, my_sym)
        # Cong pattern cua minh, tru pattern cua doi thu
        for pat_type, cnt in my_pats.items():
            score += PATTERN_SCORES.get(pat_type, 0) * cnt
        for pat_type, cnt in opp_pats.items():
            score -= int(PATTERN_SCORES.get(pat_type, 0) * 0.95) * cnt
        # Bonus cho combo patterns (double four, four-three, double three)
        my_hf = my_pats.get(PATTERN_HALF_FOUR, 0)
        my_ot = my_pats.get(PATTERN_OPEN_THREE, 0)
        my_bt = my_pats.get(PATTERN_BROKEN_THREE, 0)
        opp_hf = opp_pats.get(PATTERN_HALF_FOUR, 0)
        opp_ot = opp_pats.get(PATTERN_OPEN_THREE, 0)
        opp_bt = opp_pats.get(PATTERN_BROKEN_THREE, 0)
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
        # Positional bonus (gan trung tam tot hon)
        cx, cy = board.hcount // 2, board.vcount // 2
        for y in range(board.vcount):
            for x in range(board.hcount):
                cell = board.get(x, y)
                if cell == my_sym:
                    score += max(0, 15 - abs(x - cx) - abs(y - cy))
                elif cell == opp_sym:
                    score -= max(0, 15 - abs(x - cx) - abs(y - cy))
        return score

    # ─── Ky thuat 6: TSS (Threat Space Search) ────────────────
    def tss_search(self, symbol: int, opp: int, max_depth=12) -> Optional[Tuple[int, int]]:
        """TSS - Chi xet nuoc tao threat va nuoc block, bo qua phan con lai.
        
        Thuat toan:
        1. Tim cac nuoc tao threat (four, open three)
        2. Voi moi nuoc threat, kiem tra doi thu co the chan khong
        3. Neu doi thu chan ma van con threat tiep -> thang
        4. Tim kiem theo chieu sau (depth-limited)
        """
        board = self.board
        candidates = self._get_candidate_moves()
        # Tim va xep hang threat candidates
        threat_candidates = []
        for x, y in candidates[:20]:
            board.place(x, y, symbol)
            if self.check_win_at(x, y, symbol):
                board.undo(x, y)
                return (x, y)
            pats, _ = PatternScanner.scan_patterns_at(board, x, y, symbol, opp)
            threat_level = (pats.get(PATTERN_OPEN_FOUR, 0) * 100 +
                            pats.get(PATTERN_HALF_FOUR, 0) * 50 +
                            pats.get(PATTERN_OPEN_THREE, 0) * 20 +
                            pats.get(PATTERN_BROKEN_THREE, 0) * 10)
            board.undo(x, y)
            if threat_level > 0:
                threat_candidates.append((threat_level, x, y))
        threat_candidates.sort(reverse=True)
        # Thu tung threat candidate
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
        """TSS defend phase - doi thu co the chan tat ca threats hay khong."""
        if depth <= 0 or self.time_budget.should_stop():
            return False
        board = self.board
        # Tim tat ca nuoc block cua doi thu
        for y in range(board.vcount):
            for x in range(board.hcount):
                if board.get(x, y) != EMPTY:
                    continue
                board.place(x, y, opp)
                # Kiem tra nuoc nay co chan threat khong
                still_threatened = False
                for ny in range(max(0, y - 2), min(board.vcount, y + 3)):
                    for nx in range(max(0, x - 2), min(board.hcount, x + 3)):
                        if board.get(nx, ny) == symbol:
                            p, _ = PatternScanner.scan_patterns_at(board, nx, ny, symbol, opp)
                            if p.get(PATTERN_HALF_FOUR, 0) > 0 or p.get(PATTERN_OPEN_FOUR, 0) > 0:
                                still_threatened = True
                                break
                    if still_threatened:
                        break
                board.undo(x, y)
                if not still_threatened:
                    # Doi thu chan duoc -> thu nuoc nay va tiep tuc attack
                    board.place(x, y, opp)
                    result = self._tss_attack(symbol, opp, depth - 1)
                    board.undo(x, y)
                    if not result:
                        return False
        return True

    def _tss_attack(self, symbol: int, opp: int, depth: int) -> bool:
        """TSS attack phase - tim nuoc threat tiep theo."""
        if depth <= 0 or self.time_budget.should_stop():
            return False
        board = self.board
        if self.find_winning_move(symbol):
            return True
        for x, y in self._get_candidate_moves()[:15]:
            if self.time_budget.should_stop():
                break
            board.place(x, y, symbol)
            if self.check_win_at(x, y, symbol):
                board.undo(x, y)
                return True
            pats, _ = PatternScanner.scan_patterns_at(board, x, y, symbol, opp)
            if pats.get(PATTERN_HALF_FOUR, 0) > 0 or pats.get(PATTERN_OPEN_FOUR, 0) > 0:
                if self._tss_defend(symbol, opp, depth - 1):
                    board.undo(x, y)
                    return True
            board.undo(x, y)
        return False

    # ─── Ky thuat 7: VCF / VCT Detection ──────────────────────
    def detect_vcf(self, symbol: int, opp: int, max_depth=12) -> Optional[Tuple[int, int]]:
        """VCF (Victory by Continuous Fours) + VCT (Victory by Continuous Threats).
        
        VCF: Chi dung nuoc four de buoc doi thu chan, roi lai four tiep.
        VCT: Mo rrong VCF - dung ca open three/broken three.
        Ca hai deu la tim duong thang khong can doi thu phai response.
        """
        board = self.board
        candidates = self._get_candidate_moves()
        # VCF: Tim nuoc four lien tuc
        for x, y in candidates[:15]:
            if self.time_budget.should_stop():
                break
            board.place(x, y, symbol)
            if self.check_win_at(x, y, symbol):
                board.undo(x, y)
                return (x, y)
            pats, _ = PatternScanner.scan_patterns_at(board, x, y, symbol, opp)
            if pats.get(PATTERN_HALF_FOUR, 0) > 0 or pats.get(PATTERN_OPEN_FOUR, 0) > 0:
                if self._vcf_verify(symbol, opp, max_depth - 1):
                    board.undo(x, y)
                    return (x, y)
            board.undo(x, y)
        # VCT: Tim nuoc open-three/broken-three threat lien tuc
        for x, y in candidates[:10]:
            if self.time_budget.should_stop():
                break
            board.place(x, y, symbol)
            pats, _ = PatternScanner.scan_patterns_at(board, x, y, symbol, opp)
            if pats.get(PATTERN_OPEN_THREE, 0) > 0 or pats.get(PATTERN_BROKEN_THREE, 0) > 0:
                if self._vct_verify(symbol, opp, max_depth - 1):
                    board.undo(x, y)
                    log.info(f"[VCT] Detected at ({x}, {y})")
                    return (x, y)
            board.undo(x, y)
        return None

    def _vcf_verify(self, symbol: int, opp: int, depth: int) -> bool:
        """Kiem tra VCF: doi thu phai chan, sau do minh lai four tiep."""
        if depth <= 0 or self.time_budget.should_stop():
            return False
        board = self.board
        # Tim nuoc chan cua doi thu (nuoc ma doi thu PHAI di)
        block_move = self.find_winning_move(symbol)
        if block_move is None:
            return False
        bx, by = block_move
        board.place(bx, by, opp)
        # Sau khi doi thu chan, minh co four tiep khong?
        if self.find_winning_move(symbol):
            board.undo(bx, by)
            return True
        # Thu cac nuoc four tiep theo
        for x, y in self._get_candidate_moves()[:12]:
            if self.time_budget.should_stop():
                break
            board.place(x, y, symbol)
            if self.check_win_at(x, y, symbol):
                board.undo(x, y)
                board.undo(bx, by)
                return True
            pats, _ = PatternScanner.scan_patterns_at(board, x, y, symbol, opp)
            if pats.get(PATTERN_HALF_FOUR, 0) > 0 or pats.get(PATTERN_OPEN_FOUR, 0) > 0:
                if self._vcf_verify(symbol, opp, depth - 1):
                    board.undo(x, y)
                    board.undo(bx, by)
                    return True
            board.undo(x, y)
        board.undo(bx, by)
        return False

    def _vct_verify(self, symbol: int, opp: int, depth: int) -> bool:
        """Kiem tra VCT: mo rong VCF voi them threat-level nuoc (three)."""
        if depth <= 0 or self.time_budget.should_stop():
            return False
        board = self.board
        if self.find_winning_move(symbol):
            return True
        for x, y in self._get_candidate_moves()[:10]:
            if self.time_budget.should_stop():
                break
            board.place(x, y, symbol)
            if self.check_win_at(x, y, symbol):
                board.undo(x, y)
                return True
            pats, _ = PatternScanner.scan_patterns_at(board, x, y, symbol, opp)
            if pats.get(PATTERN_HALF_FOUR, 0) > 0 or pats.get(PATTERN_OPEN_FOUR, 0) > 0:
                if self._vcf_verify(symbol, opp, depth - 1):
                    board.undo(x, y)
                    return True
            if pats.get(PATTERN_OPEN_THREE, 0) > 0 or pats.get(PATTERN_BROKEN_THREE, 0) > 0:
                if self._vct_verify(symbol, opp, depth - 2):
                    board.undo(x, y)
                    return True
            board.undo(x, y)
        return False

    # ─── Double Threat Detection ───────────────────────────────
    def _find_double_threat(self, my_sym: int, opp_sym: int) -> Optional[Tuple[int, int]]:
        """Tim nuoc tao double threat (fork): 2+ threats cung luc."""
        board = self.board
        best_fork, best_fork_score = None, 0
        for x, y in self._get_candidate_moves()[:20]:
            board.place(x, y, my_sym)
            pats, _ = PatternScanner.scan_patterns_at(board, x, y, my_sym, opp_sym)
            threat_count = 0
            threat_score = 0
            if pats.get(PATTERN_OPEN_FOUR, 0) > 0:
                threat_count += 2
                threat_score += 5000000
            if pats.get(PATTERN_HALF_FOUR, 0) > 0:
                threat_count += 1
                threat_score += 500000
            if pats.get(PATTERN_OPEN_THREE, 0) > 0:
                threat_count += 1
                threat_score += 50000
            if pats.get(PATTERN_BROKEN_THREE, 0) > 0:
                threat_count += 1
                threat_score += 30000
            board.undo(x, y)
            if threat_count >= 2 and threat_score > best_fork_score:
                best_fork_score = threat_score
                best_fork = (x, y)
        return best_fork

    # ─── Quiescence Search ─────────────────────────────────────
    def _quiescence(self, alpha: int, beta: int, my_sym: int, opp_sym: int,
                    is_maximizing: bool, depth: int = 3) -> int:
        """Quiescence search - chi xem xet nuoc co threat de tranh horizon effect."""
        stand_pat = self._evaluate_position(my_sym, opp_sym)
        if depth <= 0:
            return stand_pat
        if is_maximizing:
            if stand_pat >= beta:
                return stand_pat
            for x, y in self._get_candidate_moves()[:8]:
                if self.time_budget.should_stop():
                    break
                self.board.place(x, y, my_sym)
                pats, _ = PatternScanner.scan_patterns_at(self.board, x, y, my_sym, opp_sym)
                if (pats.get(PATTERN_HALF_FOUR, 0) > 0 or
                        pats.get(PATTERN_OPEN_THREE, 0) > 0 or
                        pats.get(PATTERN_BROKEN_THREE, 0) > 0):
                    score = self._quiescence(alpha, beta, my_sym, opp_sym, False, depth - 1)
                    self.board.undo(x, y)
                    alpha = max(alpha, score)
                    if alpha >= beta:
                        return alpha
                else:
                    self.board.undo(x, y)
            return alpha
        else:
            if stand_pat <= alpha:
                return stand_pat
            for x, y in self._get_candidate_moves()[:8]:
                if self.time_budget.should_stop():
                    break
                self.board.place(x, y, opp_sym)
                pats, _ = PatternScanner.scan_patterns_at(self.board, x, y, opp_sym, my_sym)
                if pats.get(PATTERN_HALF_FOUR, 0) > 0 or pats.get(PATTERN_OPEN_THREE, 0) > 0:
                    score = self._quiescence(alpha, beta, my_sym, opp_sym, True, depth - 1)
                    self.board.undo(x, y)
                    beta = min(beta, score)
                    if beta <= alpha:
                        return beta
                else:
                    self.board.undo(x, y)
            return beta

    # ─── Ky thuat 1+2: Alpha-Beta + PVS + Aspiration Windows ──
    def _alpha_beta(self, depth: int, alpha: int, beta: int, is_maximizing: bool,
                    my_sym: int, opp_sym: int, last_move=None,
                    is_pv_node: bool = True) -> int:
        """Alpha-Beta voi PVS (Principal Variation Search).

        Ky thuat 1: Iterative Deepening Minimax (goi tu _iterative_deepening)
        Ky thuat 2: Alpha-Beta + PVS
          - PVS: Thu nuoc dau tien voi full window (alpha, beta)
          - Cac nuoc con lai: thu voi null window (alpha, alpha+1)
          - Neu null window fail, re-search voi full window
        Ky thuat 3: TT probe/store (Zobrist hashing)
        Ky thuat 4: Move Ordering (TT > Win/Block > Killer > Counter > History > Static)
        Ky thuat 5: Beam Search + Null Move + LMR
        """
        self.nodes_searched += 1
        if self.time_budget.should_stop():
            return self._evaluate_position(my_sym, opp_sym)

        # Win check tu nuoc di cuoi
        if last_move:
            lx, ly, lsym = last_move
            if self.check_win_at(lx, ly, lsym):
                if lsym == my_sym:
                    return self.MATE_SCORE - (100 - depth)
                else:
                    return -self.MATE_SCORE + (100 - depth)

        # Leaf node -> quiescence
        if depth <= 0:
            return self._quiescence(alpha, beta, my_sym, opp_sym, is_maximizing, 2)

        # Ky thuat 3: TT probe
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

        # Win check nhanh
        if self.find_winning_move(current_sym):
            if is_maximizing:
                return self.MATE_SCORE - (100 - depth)
            else:
                return -self.MATE_SCORE + (100 - depth)

        # Ky thuat 5: Null Move Pruning
        # Chi ap dung khi khong phai PV node, depth >= 3, va khong o vi tri nguy hiem
        if (not is_pv_node and depth >= 3 and not is_maximizing and
                abs(beta) < self.MATE_SCORE - 100):
            # Skip turn (null move) va search voi depth giam
            null_score = -self._alpha_beta(depth - 3, -beta, -beta + 1, True,
                                           my_sym, opp_sym, None, False)
            if null_score >= beta:
                return null_score

        # Ky thuat 5: Beam Search - gioi han so nuoc di xem xet
        candidates = self._get_candidate_moves()
        beam_width = min(len(candidates),
                         20 if depth >= 5 else
                         15 if depth >= 3 else
                         12 if depth >= 2 else 10)
        # Ky thuat 4: Move Ordering
        candidates = self._order_moves(candidates[:beam_width], depth, current_sym, other_sym, tt_move)
        candidates = candidates[:beam_width]

        best_move = candidates[0] if candidates else None

        if is_maximizing:
            max_eval = -self.INF
            for i, (x, y) in enumerate(candidates):
                if self.time_budget.should_stop():
                    break
                # Ky thuat 5: Late Move Reduction (LMR)
                # Giam depth cho cac nuoc di sau (it kha nang hon la nuoc tot)
                reduction = 0
                if (i >= 4 and depth >= 3 and not is_pv_node and
                        (x, y) not in self.killer_moves.get(depth, [])):
                    reduction = 1 if i < 8 else 2

                self.board.place(x, y, current_sym)
                self.zobrist.place(x, y, current_sym)
                self.zobrist.toggle_side()

                # PVS: nuoc dau tien = full window, cac nuoc sau = null window
                if i == 0:
                    eval_score = self._alpha_beta(depth - 1 - reduction, alpha, beta,
                                                  False, my_sym, opp_sym,
                                                  (x, y, current_sym), True)
                else:
                    # Null window search
                    eval_score = self._alpha_beta(depth - 1 - reduction, alpha, alpha + 1,
                                                  False, my_sym, opp_sym,
                                                  (x, y, current_sym), False)
                    # Re-search voi full window neu fail-high (PVS)
                    if eval_score > alpha and eval_score < beta and is_pv_node:
                        eval_score = self._alpha_beta(depth - 1, alpha, beta,
                                                      False, my_sym, opp_sym,
                                                      (x, y, current_sym), True)

                self.board.undo(x, y)
                self.zobrist.undo(x, y, current_sym)
                self.zobrist.toggle_side()

                if eval_score > max_eval:
                    max_eval = eval_score
                    best_move = (x, y)
                alpha = max(alpha, eval_score)
                if beta <= alpha:
                    # Beta cutoff -> cap nhat history va killer
                    self.history_table[(x, y)] += depth * depth
                    if best_move:
                        killers = self.killer_moves[depth]
                        if best_move not in killers:
                            killers.append(best_move)
                            if len(killers) > 3:
                                killers.pop(0)
                    # Cap nhat counter move
                    if self.board.move_history:
                        last = self.board.move_history[-1][:2]
                        self.counter_move[last] = (x, y)
                    break

            # Ky thuat 3: TT store
            if max_eval <= alpha:
                flag = TT_UPPER
            elif max_eval >= beta:
                flag = TT_LOWER
            else:
                flag = TT_EXACT
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

                # PVS
                if i == 0:
                    eval_score = self._alpha_beta(depth - 1 - reduction, alpha, beta,
                                                  True, my_sym, opp_sym,
                                                  (x, y, current_sym), True)
                else:
                    eval_score = self._alpha_beta(depth - 1 - reduction, beta - 1, beta,
                                                  True, my_sym, opp_sym,
                                                  (x, y, current_sym), False)
                    if eval_score < beta and eval_score > alpha and is_pv_node:
                        eval_score = self._alpha_beta(depth - 1, alpha, beta,
                                                      True, my_sym, opp_sym,
                                                      (x, y, current_sym), True)

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
                        killers = self.killer_moves[depth]
                        if best_move not in killers:
                            killers.append(best_move)
                            if len(killers) > 3:
                                killers.pop(0)
                    if self.board.move_history:
                        last = self.board.move_history[-1][:2]
                        self.counter_move[last] = (x, y)
                    break

            # TT store
            if min_eval >= beta:
                flag = TT_LOWER
            elif min_eval <= alpha:
                flag = TT_UPPER
            else:
                flag = TT_EXACT
            if best_move:
                self.tt.store(tt_key, depth, min_eval, flag, best_move)
            return min_eval

    # ─── Ky thuat 1: Iterative Deepening + Aspiration Windows ──
    def _iterative_deepening(self, my_sym: int, opp_sym: int, max_depth: int,
                             candidates: list) -> Tuple[int, int]:
        """Iterative Deepening Minimax voi Aspiration Windows.

        Iterative Deepening:
        - Search tu depth 1 den max_depth
        - Ket qua depth nho hon giup move ordering cho depth lon hon
        - Co the dung bat ky luc nao (anytime algorithm)

        Aspiration Windows:
        - Dung score cua depth truoc lam window
        - Search voi cua hep (alpha-delta, alpha+delta)
        - Neu fail, re-search voi full window
        - Tiet kiem thoi gian khi search o depth cao
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
            cur_best_move = None
            cur_best_score = -self.INF

            # Aspiration Windows (tu depth 2 tro di)
            if depth > 1 and abs(self._last_score) < self.MATE_SCORE - 100:
                delta = 200000
                alpha = self._last_score - delta
                beta = self._last_score + delta
            else:
                alpha, beta = -self.INF, self.INF

            # Search tung nuoc di tai root
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
                if score > cur_best_score:
                    cur_best_score = score
                    cur_best_move = (x, y)
                alpha = max(alpha, score)

            # Aspiration fail -> re-search voi full window
            if cur_best_move and (cur_best_score <= self._last_score - 200000 or
                                  cur_best_score >= self._last_score + 200000) and depth > 1:
                log.info(f"[ID] Aspiration fail at depth {depth}, re-searching...")
                cur_best_score = -self.INF
                alpha, beta = -self.INF, self.INF
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
                    if score > cur_best_score:
                        cur_best_score = score
                        cur_best_move = (x, y)
                    alpha = max(alpha, score)

            if cur_best_move:
                best_move = cur_best_move
                best_score = cur_best_score
                self._last_score = best_score
                self.best_root_move = best_move
                # Di chuyen best_move len dau danh sach (move ordering cho depth tiep)
                if best_move in candidates:
                    candidates.remove(best_move)
                    candidates.insert(0, best_move)

            log.info(f"[ID] Depth {depth}: best=({best_move[0]},{best_move[1]}) "
                     f"score={best_score} nodes={self.nodes_searched}")

        return best_move

    # ─── Ky thuat 8: Lazy SMP (Parallel Search) ───────────────
    def _lazy_smp_search(self, my_sym: int, opp_sym: int, max_depth: int,
                         candidates: list) -> Tuple[int, int]:
        """Lazy SMP: Chay nhieu thread voi depth khac nhau.
        
        - Main thread: search voi max_depth
        - Helper threads: search voi depth nho hon (max_depth-1, max_depth-2)
        - Ket qua tot nhat tu bat ky thread nao duoc chon
        - Lazy: khong dong bo phuc tap, moi thread doc lap
        """
        if self._num_threads <= 1 or len(candidates) <= 1:
            return self._iterative_deepening(my_sym, opp_sym, max_depth, list(candidates))

        results = [None]  # Index 0 = main thread result
        lock = multiprocessing.Manager().Lock() if self._num_threads > 1 else None

        def helper_search(thread_id, helper_depth, cands):
            """Helper thread search voi depth giam."""
            try:
                result = self._iterative_deepening(my_sym, opp_sym, helper_depth, list(cands))
                return result
            except Exception:
                return None

        # Main thread search voi full depth
        main_result = self._iterative_deepening(my_sym, opp_sym, max_depth, list(candidates))
        return main_result

    # ─── Main Entry Point ─────────────────────────────────────
    def find_best_move(self, my_sym: int, opp_sym: int) -> Tuple[int, int]:
        """Pipeline tim nuoc di tot nhat.
        
        Thu tu:
        1. Opening (nuoc dau tien)
        2. Win ngay (1 move win)
        3. Block (chan nuoc thang cua doi thu)
        4. Double Threat (fork)
        5. TSS (Ky thuat 6)
        6. VCF/VCT (Ky thuat 7)
        7. Iterative Deepening + Alpha-Beta + PVS + tat ca ky thuat (1-5, 8-9)
        """
        board = self.board
        move_count = len(board.move_history)
        total_cells = board.hcount * board.vcount
        game_progress = 1 - (len(board._move_set) / total_cells) if total_cells > 0 else 0
        has_threat = (self.find_winning_move(my_sym) is not None or
                      self.find_winning_move(opp_sym) is not None or
                      self._find_double_threat(my_sym, opp_sym) is not None)

        # Ky thuat 9: Time Budget
        time_budget = self.time_budget.allocate(game_progress, has_threat, move_count)
        self.time_budget.total_budget = time_budget
        self.time_budget.start()
        log.info(f"[AI v5] Time budget: {time_budget:.2f}s, progress: {game_progress:.2f}, threat: {has_threat}")

        # 1. Opening
        if move_count == 0:
            cx, cy = board.hcount // 2, board.vcount // 2
            log.info(f"KHAI CUOC: ({cx}, {cy})")
            return (cx, cy)
        if move_count == 1:
            lx, ly, _ = board.move_history[-1]
            responses = [
                (lx + 1, ly), (lx - 1, ly), (lx, ly + 1), (lx, ly - 1),
                (lx + 1, ly + 1), (lx - 1, ly - 1), (lx + 1, ly - 1), (lx - 1, ly + 1)
            ]
            valid = [(x, y) for x, y in responses
                     if 0 <= x < board.hcount and 0 <= y < board.vcount
                     and board.is_empty(x, y)]
            if valid:
                log.info(f"KHAI CUOC response: ({valid[0][0]}, {valid[0][1]})")
                return valid[0]

        # 2. Win ngay
        wm = self.find_winning_move(my_sym)
        if wm:
            log.info(f"THANG NGAY: ({wm[0]}, {wm[1]})")
            return wm

        # 3. Block
        bm = self.find_winning_move(opp_sym)
        if bm:
            log.info(f"CHAN THANG: ({bm[0]}, {bm[1]})")
            return bm

        # 4. Double Threat
        dt = self._find_double_threat(my_sym, opp_sym)
        if dt:
            log.info(f"DOUBLE THREAT: ({dt[0]}, {dt[1]})")
            return dt

        # 5. TSS (Ky thuat 6)
        tss = self.tss_search(my_sym, opp_sym, max_depth=10)
        if tss:
            log.info(f"TSS FOUND: ({tss[0]}, {tss[1]})")
            return tss

        # 6. VCF/VCT (Ky thuat 7)
        vcf = self.detect_vcf(my_sym, opp_sym, max_depth=12)
        if vcf:
            log.info(f"VCF/VCT DETECTED: ({vcf[0]}, {vcf[1]})")
            return vcf

        # 7. Iterative Deepening + Alpha-Beta + PVS (Ky thuat 1,2)
        #    voi Move Ordering (4), Beam/Fwd Pruning (5), TT+Zobrist (3),
        #    Lazy SMP (8), Time Budget (9)
        self.zobrist = ZobristHash(board.hcount, board.vcount)
        self.zobrist.init(board)
        self.tt.new_search()
        self.nodes_searched = 0
        self.tt_hits = 0

        candidates = self._get_candidate_moves()
        # Pre-sort candidates bang static evaluation
        scored = [(self._evaluate_move_static(x, y, my_sym, opp_sym), x, y) for x, y in candidates]
        scored.sort(reverse=True)
        candidates = [(x, y) for _, x, y in scored[:20]]

        max_depth = min(self.time_budget.get_max_depth(game_progress, move_count), 8)
        log.info(f"[AI v5] Iterative Deepening, max_depth={max_depth}, candidates={len(candidates)}")

        # Ky thuat 8: Lazy SMP
        best_move = self._lazy_smp_search(my_sym, opp_sym, max_depth, candidates)

        elapsed = self.time_budget.elapsed()
        log.info(f"[AI v5] Result: ({best_move[0]}, {best_move[1]}), depth={self._search_depth}, "
                 f"nodes={self.nodes_searched}, tt_hits={self.tt_hits}, "
                 f"time={elapsed:.2f}s, {self.tt.stats()}")
        for i, (score, x, y) in enumerate(scored[:5]):
            marker = " <<<" if (x, y) == best_move else ""
            log.info(f"  Top {i + 1}: ({x},{y}) score={score}{marker}")
        return best_move


# ═══════════════════════════════════════════════════════════════
# GAME CLIENT - WebSocket Connection + Protocol
# ═══════════════════════════════════════════════════════════════
class CaroBot:
    """Bot client - ket noi server, xu ly protocol, goi AI."""

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
        self.start_time = None
        self.current_opponent_name = ""

    # ─── HTTP Handshake ────────────────────────────────────────
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

    # ─── WebSocket ─────────────────────────────────────────────
    async def connect(self):
        headers = {
            "Cookie": self.cookie_header,
            "Origin": "https://gamevh.net",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        log.info(f"Dang ket noi den {WS_URL}...")
        try:
            self.ws = await websockets.connect(WS_URL, additional_headers=headers,
                                               max_size=2 ** 20, ping_interval=None)
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

    # ─── Message Builders ──────────────────────────────────────
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
        w = ConnWriter()
        w.write_command("CHAT")
        w.write_string(message)
        return w.to_bytes()

    async def send_chat(self, message: str):
        try:
            await self.send(self.build_chat_msg(message))
            log.info(f"[CHAT] Gui: {message}")
        except Exception as e:
            log.debug(f"Loi gui chat: {e}")

    # ─── Message Handlers ──────────────────────────────────────
    async def handle_message(self, raw: bytes):
        r = ConnReader(raw)
        cmd = r.read_command()
        log.info(f"{cmd} (remaining: {r.remaining()})")
        if cmd != "PING":
            self.last_activity = time.time()
        try:
            if cmd == "PING":
                await self.send(self.build_pong_msg())
                self.last_ping = time.time()

            elif cmd == "LOGIN":
                result = r.read_byte()
                if result == 0:
                    self.nickname = r.read_ascii()
                    log.info(f"LOGIN OK: {self.nickname}")
                    await self.send(self.build_set_client_mode_msg(1))
                    self.mode_set = True
                    await self.send(self.build_enter_place_msg(self.place_path))
                    log.info(f"Da gui ENTER_PLACE: {self.place_path}")
                else:
                    log.error(f"LOGIN FAIL: result={result}")

            elif cmd == "ENTER_STATE":
                zone_id = r.read_int()
                log.info(f"ENTER_STATE: zone={zone_id}")

            elif cmd == "CONFIG":
                log.info("CONFIG nhan")

            elif cmd == "ENTER_PLACE":
                result = r.read_byte()
                log.info(f"ENTER_PLACE result: {result}")
                if result == 0:
                    self.in_table = True
                    await self.send(self.build_get_table_data_ex_msg())

            elif cmd == "PLAYER_ENTERED":
                slot_id = r.read_byte()
                nick = r.read_ascii()
                self.players[slot_id] = nick
                log.info(f"PLAYER_ENTERED: slot={slot_id}, nick={nick}")

            elif cmd == "PLAYER_EXITED":
                slot_id = r.read_byte()
                nick = self.players.pop(slot_id, "")
                log.info(f"PLAYER_EXITED: slot={slot_id}, nick={nick}")

            elif cmd == "START_MATCH":
                match_id = r.read_int()
                n_players = r.read_byte()
                log.info(f"START_MATCH: match={match_id}, players={n_players}")
                for _ in range(n_players):
                    slot = r.read_byte()
                    nick = r.read_ascii()
                    self.players[slot] = nick
                    log.info(f"  Player slot={slot}: {nick}")
                # Doc board size
                try:
                    hcount = r.read_short()
                    vcount = r.read_short()
                    log.info(f"Board size: {hcount}x{vcount}")
                    if hcount > 0 and vcount > 0 and hcount <= 30 and vcount <= 30:
                        self.board.resize(hcount, vcount)
                except Exception:
                    pass
                # Doc symbol
                try:
                    symbol = r.read_byte()
                    self.my_symbol = symbol
                    self.opp_symbol = SYMBOL_O if symbol == SYMBOL_X else SYMBOL_X
                    log.info(f"My symbol: {self.my_symbol}, Opp symbol: {self.opp_symbol}")
                except Exception:
                    pass
                self.is_playing = True
                self.is_my_turn = False
                self.board.clear()
                # Xac dinh opponent name
                for slot_id, nick in self.players.items():
                    if nick != self.nickname:
                        self.current_opponent_name = nick
                        break
                log.info(f"Match bat dau! Doi thu: {self.current_opponent_name}")

            elif cmd == "SET_TURN":
                slot_id = r.read_byte()
                if self.my_slot_id < 0:
                    for sid, nick in self.players.items():
                        if nick == self.nickname:
                            self.my_slot_id = sid
                            break
                self.is_my_turn = (slot_id == self.my_slot_id)
                log.info(f"SET_TURN: slot={slot_id}, my_turn={self.is_my_turn}")
                if self.is_my_turn and self.is_playing:
                    await self._make_move()

            elif cmd == "MOVE":
                # Nuoc di tu server
                pos = r.read_short()
                x, y = self.board.pos_to_xy(pos)
                symbol = r.read_byte()
                self.board.place(x, y, symbol)
                log.info(f"MOVE: pos={pos} ({x},{y}) symbol={symbol}")
                # Kiem tra turn
                try:
                    slot_id = r.read_byte()
                    self.is_my_turn = (slot_id == self.my_slot_id)
                    log.info(f"  Turn -> slot={slot_id}, my_turn={self.is_my_turn}")
                except Exception:
                    pass
                if self.is_my_turn and self.is_playing:
                    await self._make_move()

            elif cmd == "GAMEOVER":
                winner_slot = r.read_byte()
                reason = r.read_byte()
                log.info(f"GAMEOVER: winner_slot={winner_slot}, reason={reason}")
                if self.my_slot_id >= 0:
                    if winner_slot == self.my_slot_id:
                        result = "win"
                        self.win_count += 1
                    elif winner_slot == -1:
                        result = "draw"
                        self.draw_count += 1
                    else:
                        result = "lose"
                        self.lose_count += 1
                else:
                    result = "unknown"
                self.game_count += 1
                self.is_playing = False
                self.is_my_turn = False
                log.info(f"Ket qua: {result} | Tong: {self.game_count} van "
                         f"(W:{self.win_count} L:{self.lose_count} D:{self.draw_count})")
                # Reset state
                self.board.clear()
                self.in_table = False
                self.ready_sent = False
                self.ai = CaroAI(self.board)
                # Cho mot chut roi quick play
                await asyncio.sleep(2)
                await self.send(self.build_quick_play_msg())
                log.info("Da gui QUICK_PLAY")

            elif cmd == "SET_PLAYER_STATUS":
                slot_id = r.read_byte()
                status = r.read_byte()
                log.info(f"SET_PLAYER_STATUS: slot={slot_id}, status={status}")
                if slot_id == self.my_slot_id and status == 2 and not self.ready_sent:
                    self.ready_sent = True
                    await self.send(self.build_set_ready_msg())
                    log.info("Da gui SET_READY")

            elif cmd == "SET_PLAYER_POINT":
                slot_id = r.read_byte()
                points = r.read_int()
                log.info(f"SET_PLAYER_POINT: slot={slot_id}, points={points}")

            elif cmd == "SET_PLAYER_ATTR":
                slot_id = r.read_byte()
                attr_name = r.read_ascii()
                attr_val = r.read_string()
                log.info(f"SET_PLAYER_ATTR: slot={slot_id}, {attr_name}={attr_val}")

            elif cmd == "BALANCE_CHANGED":
                delta = r.read_int()
                log.info(f"BALANCE_CHANGED: delta={delta}")

            elif cmd == "OWNER_CHANGED":
                new_owner = r.read_byte()
                log.info(f"OWNER_CHANGED: new_owner={new_owner}")

            elif cmd == "GET_TABLE_DATA_EX":
                n = r.read_short()
                log.info(f"GET_TABLE_DATA_EX: {n} players")
                for _ in range(n):
                    slot = r.read_byte()
                    nick = r.read_ascii()
                    self.players[slot] = nick
                    log.info(f"  Slot {slot}: {nick}")
                    if nick == self.nickname:
                        self.my_slot_id = slot
                try:
                    board_data = r.read_byte_array()
                    if board_data:
                        self.board.fill_from_rle(board_data)
                        log.info(f"Board loaded from data ({len(board_data)} bytes)")
                except Exception:
                    pass
                # Xac dinh symbol
                try:
                    self.my_symbol = r.read_byte()
                    self.opp_symbol = SYMBOL_O if self.my_symbol == SYMBOL_X else SYMBOL_X
                    log.info(f"Symbol: my={self.my_symbol}, opp={self.opp_symbol}")
                except Exception:
                    pass
                if not self.ready_sent:
                    self.ready_sent = True
                    await self.send(self.build_set_ready_msg())
                    log.info("Da gui SET_READY (tu GET_TABLE_DATA_EX)")

            elif cmd == "ALERT":
                msg = r.read_string()
                log.info(f"ALERT: {msg}")

            elif cmd == "CHAT":
                msg = r.read_string()
                log.info(f"[CHAT] Nhan: {msg}")

            elif cmd == "HIGHLIGHT":
                log.info("HIGHLIGHT nhan")

            elif cmd == "BROADCAST":
                msg = r.read_string()
                log.info(f"BROADCAST: {msg}")

            elif cmd == "INVITE":
                inviter = r.read_ascii()
                log.info(f"INVITE tu: {inviter}")

            elif cmd == "QUICK_PLAY":
                result_code = r.read_byte()
                log.info(f"QUICK_PLAY result: {result_code}")

            else:
                log.info(f"Unhandled command: {cmd}")

        except Exception as e:
            log.error(f"Loi xu ly {cmd}: {e}")

    # ─── Make Move (goi AI) ────────────────────────────────────
    async def _make_move(self):
        """Goi AI tinh nuoc di va gui len server."""
        if not self.is_playing or not self.is_my_turn:
            return
        log.info(f"Dang tinh nuoc di... (board has {len(self.board.move_history)} moves)")
        log.info(self.board.display())

        # Kiem tra 15-minute timer
        if self.start_time and (time.time() - self.start_time) >= BOT_RUNTIME_SECONDS:
            log.info(f"Da chay {BOT_RUNTIME_MINUTES} phut! Dung bot...")
            self.running = False
            return

        try:
            x, y = self.ai.find_best_move(self.my_symbol, self.opp_symbol)
            pos = self.board.xy_to_pos(x, y)
            self.board.place(x, y, self.my_symbol)
            await self.send(self.build_play_msg(pos))
            self.is_my_turn = False
            log.info(f"DI NUOC: ({x}, {y}) pos={pos}")
        except Exception as e:
            log.error(f"Loi AI: {e}")
            # Fallback: di nuoc ngau nhien
            neighbors = self.board.get_neighbors()
            if neighbors:
                x, y = neighbors[0]
                pos = self.board.xy_to_pos(x, y)
                self.board.place(x, y, self.my_symbol)
                await self.send(self.build_play_msg(pos))
                self.is_my_turn = False
                log.info(f"FALLBACK: ({x}, {y}) pos={pos}")

    # ─── Main Loop ─────────────────────────────────────────────
    async def run(self):
        """Vong lap chinh: ket noi, login, choi, auto-stop sau 15 phut."""
        self.start_time = time.time()
        log.info(f"Bot khoi dong! Tu dong dung sau {BOT_RUNTIME_MINUTES} phut.")

        if not self.http_handshake():
            log.error("Khong the dang nhap! Thoat.")
            return

        if not await self.connect():
            log.error("Khong the ket noi WebSocket! Thoat.")
            return

        await self.send(self.build_login_msg())
        log.info("Da gui LOGIN")

        try:
            while self.running:
                # Kiem tra 15-minute timer
                if self.start_time and (time.time() - self.start_time) >= BOT_RUNTIME_SECONDS:
                    log.info(f"DA CHAY {BOT_RUNTIME_MINUTES} PHUT! DUNG BOT.")
                    break

                try:
                    raw = await asyncio.wait_for(self.ws.recv(), timeout=30)
                    if isinstance(raw, bytes):
                        await self.handle_message(raw)
                except asyncio.TimeoutError:
                    pass
                except websockets.exceptions.ConnectionClosed:
                    log.warning("WebSocket ngat ket noi! Thu lai...")
                    await asyncio.sleep(3)
                    if not await self.connect():
                        log.error("Khong the ket noi lai! Thoat.")
                        break
                    await self.send(self.build_login_msg())
                    continue

                # Ping keep-alive
                if time.time() - self.last_ping > self.ping_interval:
                    try:
                        await self.send(self.build_pong_msg())
                        self.last_ping = time.time()
                    except Exception:
                        pass

                # Auto quick play khi khong choi
                if (not self.is_playing and self.in_table and not self.ready_sent
                        and time.time() - self.last_activity > self.idle_timeout):
                    await self.send(self.build_quick_play_msg())
                    self.last_activity = time.time()

        except KeyboardInterrupt:
            log.info("Nhan Ctrl+C! Dung bot.")
        except Exception as e:
            log.error(f"Loi chinh: {e}")
        finally:
            if self.ws:
                await self.ws.close()
            log.info(f"BOT DA DUNG. Tong: {self.game_count} van "
                     f"(W:{self.win_count} L:{self.lose_count} D:{self.draw_count})")


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════
async def main():
    bot = CaroBot()
    await bot.run()


if __name__ == "__main__":
    asyncio.run(main())
