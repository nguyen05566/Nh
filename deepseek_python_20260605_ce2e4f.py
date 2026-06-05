#!/usr/bin/env python3
"""
Caro Bot v3 - AI Siêu Thông Minh cho gamevh.net
================================================
Tính năng nâng cao:
- Pattern Recognition Engine cao cấp
- Minimax + Alpha-Beta Pruning depth 4-6
- Quiescence Search (tránh hiệu ứng horizon)
- Opening Book (khai cuộc thông minh)
- Double Threat Detection (phát hiện fork)
- VCF/VCT Detection nâng cao
- Time Management (quản lý thời gian)
- Zobrist Hashing + Transposition Table
- Move ordering thông minh (killer moves, history heuristic)
- Adaptive Depth theo giai đoạn ván
- Luật Caro Việt Nam đầy đủ

Protocol: WebSocket binary, struct-based parsing
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
from typing import Optional, Tuple, List, Dict, Any

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
    """Bàn cờ Caro - tối ưu cho truy xuất nhanh."""
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
        count = 1
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
    def __init__(self, hcount=HCOUNT, vcount=VCOUNT):
        random.seed(42)
        self.hcount = hcount
        self.vcount = vcount
        self.table = [[[random.getrandbits(64) for _ in range(hcount)]
                       for _ in range(vcount)]
                      for _ in range(2)]
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

# ─── Time Management ────────────────────────────────────────
class TimeManager:
    def __init__(self, max_time_per_move=2.0, buffer_time=0.3):
        self.max_time_per_move = max_time_per_move
        self.buffer_time = buffer_time
        self.start_time = 0
        
    def start(self):
        self.start_time = time.time()
        
    def time_left(self) -> float:
        elapsed = time.time() - self.start_time
        return max(0, self.max_time_per_move - elapsed - self.buffer_time)
    
    def should_stop(self) -> bool:
        return self.time_left() <= 0
    
    def get_adaptive_depth(self, game_progress: float, move_count: int) -> int:
        if move_count < 10:
            return 4
        if game_progress > 0.7 and self.time_left() > 1.0:
            return 6
        elif game_progress > 0.4 and self.time_left() > 0.8:
            return 5
        return 4 if self.time_left() > 0.5 else 3

# ─── Caro AI v3 - Siêu Thông Minh ───────────────────────────
class CaroAI:
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

    def __init__(self, board: CaroBoard):
        self.board = board
        self.zobrist = ZobristHash(board.hcount, board.vcount)
        self.tt = {}
        self.nodes_searched = 0
        self.tt_hits = 0
        self.move_scores = defaultdict(int)
        self.killer_moves = defaultdict(list)
        self.time_mgr = TimeManager()
        self.opening_book = self._init_opening_book()

    def _init_opening_book(self):
        return {
            0: [(7, 9)],  # Nước đầu - center lệch
            1: [  # Đáp trả nước đầu đối thủ
                (7, 8), (7, 10), (6, 9), (8, 9),
                (6, 8), (8, 8), (6, 10), (8, 10)
            ]
        }

    def _get_opening_move(self) -> Optional[Tuple[int, int]]:
        move_count = len(self.board.move_history)
        if move_count == 0:
            cx, cy = self.board.hcount // 2, self.board.vcount // 2
            return (cx, cy)
        if move_count == 1:
            last_move = self.board.move_history[-1]
            lx, ly, _ = last_move
            responses = [
                (lx + 1, ly), (lx - 1, ly), (lx, ly + 1), (lx, ly - 1),
                (lx + 1, ly + 1), (lx - 1, ly - 1), (lx + 1, ly - 1), (lx - 1, ly + 1)
            ]
            valid = [(x, y) for x, y in responses 
                    if 0 <= x < self.board.hcount and 0 <= y < self.board.vcount 
                    and self.board.is_empty(x, y)]
            if valid:
                return valid[0]
        return None

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

    def _get_candidate_moves_fast(self, radius=2):
        board = self.board
        neighbors = board.get_neighbors(radius=radius)
        if not neighbors:
            cx = board.hcount // 2
            cy = board.vcount // 2
            return [(cx, cy)]
        neighbors.sort(key=lambda m: self.move_scores.get(m, 0), reverse=True)
        return neighbors

    def evaluate_move_quick(self, x: int, y: int, my_sym: int, opp_sym: int) -> int:
        score = 0
        board = self.board
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
        board.place(x, y, my_sym)
        attack_patterns, _ = PatternScanner.scan_patterns_at(board, x, y, my_sym, opp_sym)
        board.undo(x, y)
        board.place(x, y, opp_sym)
        defense_patterns, _ = PatternScanner.scan_patterns_at(board, x, y, opp_sym, my_sym)
        board.undo(x, y)
        for pat_type, cnt in attack_patterns.items():
            pat_score = PATTERN_SCORES.get(pat_type, 0)
            score += pat_score * cnt
        for pat_type, cnt in defense_patterns.items():
            pat_score = PATTERN_SCORES.get(pat_type, 0)
            score += int(pat_score * 0.9) * cnt
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
        for pat_type, cnt in opp_patterns.items():
            base_score = PATTERN_SCORES.get(pat_type, 0)
            score -= int(base_score * 0.95) * cnt
        my_half_fours = my_patterns.get(PATTERN_HALF_FOUR, 0)
        my_open_threes = my_patterns.get(PATTERN_OPEN_THREE, 0)
        my_broken_threes = my_patterns.get(PATTERN_BROKEN_THREE, 0)
        opp_half_fours = opp_patterns.get(PATTERN_HALF_FOUR, 0)
        opp_open_threes = opp_patterns.get(PATTERN_OPEN_THREE, 0)
        opp_broken_threes = opp_patterns.get(PATTERN_BROKEN_THREE, 0)
        if my_half_fours >= 2:
            score += self.DOUBLE_FOUR_BONUS
        if opp_half_fours >= 2:
            score -= self.DOUBLE_FOUR_BONUS
        if my_half_fours >= 1 and (my_open_threes + my_broken_threes) >= 1:
            score += self.FOUR_THREE_BONUS
        if opp_half_fours >= 1 and (opp_open_threes + opp_broken_threes) >= 1:
            score -= self.FOUR_THREE_BONUS
        if my_open_threes >= 2:
            score += self.DOUBLE_THREE_BONUS
        if opp_open_threes >= 2:
            score -= self.DOUBLE_THREE_BONUS
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

    def _quiescence_search(self, alpha: int, beta: int, my_sym: int, opp_sym: int, 
                           is_maximizing: bool, depth: int = 3) -> int:
        stand_pat = self.evaluate_position(my_sym, opp_sym)
        if depth <= 0:
            return stand_pat
        if is_maximizing:
            if stand_pat >= beta:
                return stand_pat
            for x, y in self._get_candidate_moves_fast(radius=2)[:10]:
                if self.time_mgr.should_stop():
                    break
                self.board.place(x, y, my_sym)
                patterns, _ = PatternScanner.scan_patterns_at(self.board, x, y, my_sym, opp_sym)
                is_strong = (patterns.get(PATTERN_HALF_FOUR, 0) > 0 or 
                            patterns.get(PATTERN_OPEN_THREE, 0) > 0 or
                            patterns.get(PATTERN_BROKEN_THREE, 0) > 0)
                if is_strong:
                    score = self._quiescence_search(alpha, beta, my_sym, opp_sym, 
                                                     False, depth - 1)
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
            for x, y in self._get_candidate_moves_fast(radius=2)[:10]:
                if self.time_mgr.should_stop():
                    break
                self.board.place(x, y, opp_sym)
                patterns, _ = PatternScanner.scan_patterns_at(self.board, x, y, opp_sym, my_sym)
                is_strong = (patterns.get(PATTERN_HALF_FOUR, 0) > 0 or 
                            patterns.get(PATTERN_OPEN_THREE, 0) > 0)
                if is_strong:
                    score = self._quiescence_search(alpha, beta, my_sym, opp_sym, 
                                                     True, depth - 1)
                    self.board.undo(x, y)
                    if score < beta:
                        beta = score
                    if beta <= alpha:
                        return beta
                else:
                    self.board.undo(x, y)
            return beta

    def minimax(self, depth: int, alpha: int, beta: int, is_maximizing: bool,
                my_sym: int, opp_sym: int, last_move=None) -> int:
        self.nodes_searched += 1
        if self.time_mgr.should_stop():
            return self.evaluate_position(my_sym, opp_sym)
        if last_move:
            lx, ly, lsym = last_move
            if self.check_win_at(lx, ly, lsym):
                if lsym == my_sym:
                    return self.SCORE_FIVE_OPEN - (100 - depth)
                else:
                    return -self.SCORE_FIVE_OPEN + (100 - depth)
        if depth <= 0:
            return self._quiescence_search(alpha, beta, my_sym, opp_sym, is_maximizing, 2)
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
        current_sym = my_sym if is_maximizing else opp_sym
        win_move = self.find_winning_move(current_sym)
        if win_move:
            if is_maximizing:
                return self.SCORE_FIVE_OPEN - (100 - depth)
            else:
                return -self.SCORE_FIVE_OPEN + (100 - depth)
        candidates = self._get_candidate_moves_fast(radius=2)
        max_candidates = min(len(candidates), 15 if depth >= 3 else 12 if depth >= 2 else 10)
        candidates = candidates[:max_candidates]
        scored_candidates = []
        for x, y in candidates:
            quick_score = self.evaluate_move_quick(x, y, my_sym, opp_sym)
            hist_score = self.move_scores.get((x, y), 0)
            killer_score = 0
            if (x, y) in self.killer_moves[depth]:
                killer_score = 10000
            scored_candidates.append((quick_score + hist_score + killer_score, x, y))
        scored_candidates.sort(reverse=True)
        candidates = [(x, y) for _, x, y in scored_candidates[:max_candidates]]
        if is_maximizing:
            max_eval = -999999999
            best_move = None
            for x, y in candidates:
                if self.time_mgr.should_stop():
                    break
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
                    if best_move:
                        self.move_scores[best_move] += depth * depth
                        self.killer_moves[depth].append(best_move)
                        if len(self.killer_moves[depth]) > 3:
                            self.killer_moves[depth].pop(0)
                    break
            self.tt[tt_key] = (depth, max_eval, 'exact')
            return max_eval
        else:
            min_eval = 999999999
            best_move = None
            for x, y in candidates:
                if self.time_mgr.should_stop():
                    break
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
                        self.killer_moves[depth].append(best_move)
                        if len(self.killer_moves[depth]) > 3:
                            self.killer_moves[depth].pop(0)
                    break
            self.tt[tt_key] = (depth, min_eval, 'exact')
            return min_eval

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

    def detect_vcf(self, symbol: int, opp: int, max_depth=10) -> bool:
        board = self.board
        def vcf_recursive(depth: int, is_attacker: bool) -> bool:
            if depth <= 0 or self.time_mgr.should_stop():
                return False
            if is_attacker:
                candidates = self._get_candidate_moves_fast(radius=2)
                for x, y in candidates[:12]:
                    board.place(x, y, symbol)
                    if self.check_win_at(x, y, symbol):
                        board.undo(x, y)
                        return True
                    patterns, _ = PatternScanner.scan_patterns_at(board, x, y, symbol, opp)
                    if (patterns.get(PATTERN_HALF_FOUR, 0) > 0 or
                            patterns.get(PATTERN_OPEN_FOUR, 0) > 0):
                        if vcf_recursive(depth - 1, False):
                            board.undo(x, y)
                            return True
                    board.undo(x, y)
                return False
            else:
                block_move = self.find_winning_move(symbol)
                if block_move is None:
                    return False
                bx, by = block_move
                board.place(bx, by, opp)
                result = vcf_recursive(depth - 1, True)
                board.undo(bx, by)
                return result
        return vcf_recursive(max_depth, True)

    def find_best_move(self, my_sym: int, opp_sym: int) -> Tuple[int, int]:
        board = self.board
        self.time_mgr.start()
        move_count = len(board.move_history)
        # Opening book
        if move_count < 2:
            book_move = self._get_opening_move()
            if book_move:
                log.info(f"📖 KHAI CUỘC: ({book_move[0]}, {book_move[1]})")
                return book_move
        # Win move
        win_move = self.find_winning_move(my_sym)
        if win_move:
            log.info(f"⚡ THẮNG NGAY: ({win_move[0]}, {win_move[1]})")
            return win_move
        # Block win
        block_move = self.find_winning_move(opp_sym)
        if block_move:
            log.info(f"🛡️ CHẶN THẮNG: ({block_move[0]}, {block_move[1]})")
            return block_move
        # Double threat
        double_threat = self._find_double_threat(my_sym, opp_sym)
        if double_threat:
            log.info(f"🎯 DOUBLE THREAT: ({double_threat[0]}, {double_threat[1]})")
            return double_threat
        # VCF detection
        candidates = self._get_candidate_moves_fast(radius=2)
        for x, y in candidates[:15]:
            if self.time_mgr.should_stop():
                break
            board.place(x, y, my_sym)
            if self.detect_vcf(my_sym, opp_sym, max_depth=8):
                board.undo(x, y)
                log.info(f"🔗 VCF DETECTED: ({x}, {y})")
                return (x, y)
            board.undo(x, y)
        # Adaptive depth
        total_cells = board.hcount * board.vcount
        game_progress = 1 - (len(board._move_set) / total_cells)
        max_depth = self.time_mgr.get_adaptive_depth(game_progress, move_count)
        # Minimax
        self.zobrist = ZobristHash(board.hcount, board.vcount)
        self.zobrist.init(board)
        self.nodes_searched = 0
        self.tt_hits = 0
        scored_candidates = []
        for x, y in candidates:
            quick_score = self.evaluate_move_quick(x, y, my_sym, opp_sym)
            scored_candidates.append((quick_score, x, y))
        scored_candidates.sort(reverse=True)
        top_candidates = [(x, y) for _, x, y in scored_candidates[:12]]
        best_move = top_candidates[0] if top_candidates else (board.hcount // 2, board.vcount // 2)
        best_score = -999999999
        for x, y in top_candidates:
            if self.time_mgr.should_stop():
                break
            board.place(x, y, my_sym)
            self.zobrist.place(x, y, my_sym)
            score = self.minimax(max_depth - 1, -999999999, 999999999,
                                 False, my_sym, opp_sym, (x, y, my_sym))
            self.board.undo(x, y)
            self.zobrist.undo(x, y, my_sym)
            if score > best_score:
                best_score = score
                best_move = (x, y)
        log.info(f"🧠 AI v3 - Depth: {max_depth}, Nodes: {self.nodes_searched}, TT hits: {self.tt_hits}")
        for i, (score, x, y) in enumerate(scored_candidates[:5]):
            marker = " <<<" if (x, y) == best_move else ""
            log.info(f"  Top {i+1}: ({x},{y}) score={score}{marker}")
        return best_move

# ─── Game Client ────────────────────────────────────────────
class CaroBot:
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

    def http_handshake(self) -> bool:
        log.info("Đăng nhập bằng username/password...")
        try:
            s = requests.Session()
            ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            s.get('https://gamevh.net/login.jsp', timeout=10, headers={'User-Agent': ua})
            log.info(f"Đăng nhập: user={LOGIN_USERNAME}")
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
                log.error("Đăng nhập thất bại! Sai tên/mật khẩu?")
                return False
            log.info("Đăng nhập HTTP thành công!")
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
                log.error("Không tìm thấy token!")
                return False
            m = re.search(r"var\s+currentPlayerNickName\s*=\s*'([^']+)'", html)
            if m:
                self.nickname = m.group(1)
                log.info(f"Nickname: {self.nickname}")
            else:
                log.error("Không tìm thấy nickname!")
                return False
            m = re.search(r'var\s+placePath\s*=\s*"([^"]+)"', html)
            if m:
                self.place_path = m.group(1)
                log.info(f"PlacePath: {self.place_path}")
            return True
        except Exception as e:
            log.error(f"Lỗi HTTP handshake: {e}")
            return False

    async def connect(self):
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
                ping_interval=None,
            )
            log.info("Đã kết nối WebSocket!")
            return True
        except Exception as e:
            log.error(f"Lỗi kết nối: {e}")
            return False

    async def send(self, data: bytes):
        if self.ws:
            try:
                await self.ws.send(data)
            except Exception as e:
                log.error(f"Lỗi gửi: {e}")

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
            else:
                log.debug(f"Unhandled: {cmd}")
        except Exception as e:
            log.error(f"Lỗi xử lý {cmd}: {e}")

    async def handle_login(self, r: ConnReader):
        status = r.read_byte()
        log.info(f"LOGIN status={status}, remaining={r.remaining()}")
        if status == 0:
            path = r.read_string()
            log.info(f"LOGIN path={path}")
            if path == "REFRESH":
                log.info("Server yêu cầu REFRESH - tiếp tục...")
                await self.send(self.build_enter_place_msg(self.place_path, "", 1))
                return
            if r.remaining() > 0:
                self.login_cookie = r.read_ascii()
            if r.remaining() > 0:
                password = r.read_string()
            if r.remaining() > 0:
                material = r.read_ascii()
            log.info(f"LOGIN thành công! path={path}")
            await self.send(self.build_enter_place_msg(self.place_path, "", 1))
        else:
            if r.remaining() > 0:
                error_msg = r.read_string()
                log.error(f"LOGIN thất bại: status={status}, msg={error_msg}")
            else:
                log.error(f"LOGIN thất bại: status={status}")

    async def handle_quick_play(self, r: ConnReader):
        try:
            status = r.read_byte()
            if status != 0:
                error_msg = r.read_string() if r.remaining() > 0 else ""
                log.info(f"Quick play lỗi: {error_msg}")
                if "notinzone" in error_msg.lower() and self.in_table:
                    log.info("Đang trong bàn, gửi SET_READY...")
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
            log.error(f"Lỗi parse quick play: {e}")

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
                    log.info("Chưa ngồi bàn, tìm bàn mới...")
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
                log.info("Đang chờ đối thủ/ván mới...")
                if not self.ready_sent:
                    self.ready_sent = True
                    await self.send(self.build_set_ready_msg())
        except Exception as e:
            log.error(f"Lỗi parse table data: {e}")

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
        log.info(f"=== VÁN {self.game_count} BẮT ĐẦU === Board: {hcount}x{vcount}")
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
            log.info(f"Xác nhận: ({x}, {y}) symbol={sym_char}")
            self.my_symbol = symbol
            self.opp_symbol = SYMBOL_O if symbol == SYMBOL_X else SYMBOL_X
        elif current == EMPTY:
            log.info(f"Đối thủ đánh: ({x}, {y}) symbol={sym_char}")
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
            log.info(f"🎉 THẮNG!")
        elif my_grade in (2, 4, 12):
            self.lose_count += 1
            log.info(f"😢 THUA!")
        elif my_grade in (3, 10):
            self.draw_count += 1
            log.info(f"🤝 HÒA!")
        match_result = r.read_string()
        log.info(f"  Result: {match_result}")
        elapsed = ""
        if self.start_time:
            mins = (time.time() - self.start_time) / 60
            elapsed = f", thời gian: {mins:.1f} phút"
        log.info(f"📊 Tổng: {self.game_count} ván, {self.win_count} thắng, "
                 f"{self.lose_count} thua, {self.draw_count} hòa{elapsed}")
        if self.game_count > 0:
            wr = self.win_count / self.game_count * 100
            log.info(f"🏆 Win rate: {wr:.1f}%")
        await asyncio.sleep(3)
        if self.in_table:
            self.ready_sent = False
            log.info("Gửi SET_READY cho đối thủ mới...")
            await self.send(self.build_set_ready_msg())
            self.ready_sent = True
        else:
            log.info("Tìm bàn mới...")
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
        log.info(f"🎯 TA ĐÁNH: ({x}, {y}) pos={pos} [{elapsed:.2f}s]")
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
                            log.info(f"Idle {idle_time:.0f}s - rời bàn tìm bàn mới...")
                            self.in_table = False
                            self.ready_sent = False
                            self.is_playing = False
                            self.last_activity = time.time()
                            await self.send(self.build_enter_place_msg(self.place_path, "", 1))
                            await asyncio.sleep(1)
                            await self.send(self.build_quick_play_msg())
                    if self.start_time and (time.time() - self.start_time) > 30 * 60:
                        log.info("=== ĐÃ CHẠY 30 PHÚT - DỪNG BOT ===")
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
        log.info(f"Đăng nhập nick={self.nickname}, token={self.token}...")
        await self.send(login_msg)
        asyncio.create_task(self.ping_loop())
        try:
            async for raw in self.ws:
                if isinstance(raw, bytes):
                    await self.handle_message(raw)
        except websockets.exceptions.ConnectionClosed as e:
            log.warning(f"Kết nối đóng: {e}")
        except Exception as e:
            log.error(f"Lỗi: {e}")
        finally:
            self.running = False
            log.info("Bot đã dừng.")

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
                if self.start_time and (time.time() - self.start_time) > 30 * 60:
                    log.info("=== ĐÃ CHẠY 30 PHÚT - KẾT THÚC ===")
                    log.info(f"📊 Tổng: {self.game_count} ván, {self.win_count} thắng, "
                             f"{self.lose_count} thua, {self.draw_count} hòa")
                    if self.game_count > 0:
                        wr = self.win_count / self.game_count * 100
                        log.info(f"🏆 Win rate cuối: {wr:.1f}%")
                    break
                if not self.http_handshake():
                    log.error("Đăng nhập thất bại!")
                    continue
                await self.run()
            except Exception as e:
                log.error(f"Lỗi nghiêm trọng: {e}")
            if not self.running:
                break
            retries += 1
            wait_time = min(5 * retries, 30)
            log.info(f"Đợi {wait_time}s trước khi reconnect (lần {retries}/{max_retries})...")
            await asyncio.sleep(wait_time)

# ─── Main ───────────────────────────────────────────────────
async def main():
    print("=" * 60)
    print("🤖 CARO BOT v3 - AI SIÊU THÔNG MINH")
    print("=" * 60)
    print("Tính năng:")
    print("  • Pattern Recognition cao cấp")
    print("  • Minimax + Alpha-Beta depth 4-6")
    print("  • Quiescence Search")
    print("  • Opening Book thông minh")
    print("  • Double Threat Detection")
    print("  • VCF/VCT Detection")
    print("  • Time Management")
    print("=" * 60)
    bot = CaroBot()
    await bot.run_with_reconnect()

if __name__ == "__main__":
    asyncio.run(main())