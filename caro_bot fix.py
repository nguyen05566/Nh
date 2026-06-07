#!/usr/bin/env python3
"""
Caro Bot Cải tiến cho gamevh.net
- Kết nối WebSocket, parse binary protocol bằng struct
- AI đánh cờ caro trên bàn 15 cột x 19 dòng
- Minimax + Alpha-Beta Pruning + Iterative Deepening
- Tự động chơi khi đến lượt
- Ở yên trong phòng, không thoát ra
- Đăng nhập bằng username/password (không cần cookies)
"""

import asyncio
import struct
import time
import logging
import sys
import re
from collections import defaultdict
import copy

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
LOGIN_URL = "https://gamevh.net/login.jsp"

# Đăng nhập bằng username/password
USERNAME = "nguyen05511"
PASSWORD = "nhat123456"

# Sẽ được cập nhật từ HTTP handshake
TOKEN = 0
PLACE_PATH = "Lobby.caro.0"
VERSION = "5.0.2"
GAME_ID = "caro"

# Board dimensions
HCOUNT = 15  # columns (x)
VCOUNT = 19  # rows (y)

# AI Config
AI_MAX_DEPTH = 4       # Độ sâu tối đa của minimax
AI_TIME_LIMIT = 4.0    # Giới hạn thời gian tính toán (giây)

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
    def __init__(self, hcount=HCOUNT, vcount=VCOUNT):
        self.hcount = hcount
        self.vcount = vcount
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

    def unplace(self, x: int, y: int):
        """Xóa quân tại vị trí (undo cho minimax)."""
        if 0 <= x < self.hcount and 0 <= y < self.vcount:
            self.board[y][x] = EMPTY
            if self.move_history and self.move_history[-1][:2] == (x, y):
                self.move_history.pop()

    def get(self, x: int, y: int) -> int:
        if 0 <= x < self.hcount and 0 <= y < self.vcount:
            return self.board[y][x]
        return EMPTY

    def fill_from_rle(self, board_data: list):
        self.clear()
        pos = 0
        total_cells = self.hcount * self.vcount
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

    def clone(self):
        """Tạo bản sao của bàn cờ cho minimax."""
        new_board = CaroBoard(self.hcount, self.vcount)
        new_board.board = [row[:] for row in self.board]
        new_board.move_history = self.move_history[:]
        new_board.my_symbol = self.my_symbol
        new_board.opp_symbol = self.opp_symbol
        return new_board


# ─── Caro AI (Minimax + Alpha-Beta + Iterative Deepening) ───
class CaroAI:
    """AI đánh Caro dùng Minimax + Alpha-Beta Pruning + Iterative Deepening.
    
    Điểm cải tiến so với bản cũ:
    1. Minimax thực sự với độ sâu 2-4 (không chỉ greedy)
    2. Alpha-Beta Pruning cắt nhánh không cần thiết
    3. Iterative Deepening với time limit
    4. Hàm đánh giá cải tiến: đếm pattern chi tiết hơn
    5. Phát hiện double threat (tạo 2 mối đe dọa cùng lúc)
    6. Ưu tiên nước thắng > chặn thua > tạo threat > phòng thủ
    """

    def __init__(self, board: CaroBoard):
        self.board = board
        self.nodes_searched = 0
        self.time_limit = AI_TIME_LIMIT
        self.start_time = 0
        self.timeout_flag = False

        # Trọng số pattern cho hàm đánh giá
        self.SCORES = {
            'FIVE':          10000000,   # 5 liên tiếp = thắng
            'OPEN_FOUR':      5000000,   # 4 mở 2 đầu
            'HALF_FOUR':        500000,   # 4 mở 1 đầu
            'OPEN_THREE':       200000,   # 3 mở 2 đầu
            'HALF_THREE':        50000,   # 3 mở 1 đầu
            'OPEN_TWO':          20000,   # 2 mở 2 đầu
            'HALF_TWO':           5000,   # 2 mở 1 đầu
        }

        # Điểm thưởng cho double threats
        self.DOUBLE_THREAT_BONUS = 1000000  # Tạo 2 mối đe dọa cùng lúc

    def check_win_at(self, board: CaroBoard, x: int, y: int, symbol: int) -> bool:
        """Kiểm tra 5 liên tiếp tại (x,y)."""
        directions = [(1, 0), (0, 1), (1, 1), (1, -1)]
        for dx, dy in directions:
            count = 1
            for i in range(1, 5):
                nx, ny = x + dx * i, y + dy * i
                if 0 <= nx < board.hcount and 0 <= ny < board.vcount and board.get(nx, ny) == symbol:
                    count += 1
                else:
                    break
            for i in range(1, 5):
                nx, ny = x - dx * i, y - dy * i
                if 0 <= nx < board.hcount and 0 <= ny < board.vcount and board.get(nx, ny) == symbol:
                    count += 1
                else:
                    break
            if count >= 5:
                return True
        return False

    def analyze_line_pattern(self, board: CaroBoard, x: int, y: int, dx: int, dy: int, symbol: int):
        """Phân tích pattern theo 1 hướng từ vị trí (x,y).
        Trả về (count, open_ends) - số quân liên tiếp và số đầu mở.
        """
        count = 1
        open_ends = 0

        # Đếm thuận
        for i in range(1, 6):
            nx, ny = x + dx * i, y + dy * i
            if 0 <= nx < board.hcount and 0 <= ny < board.vcount:
                if board.get(nx, ny) == symbol:
                    count += 1
                elif board.get(nx, ny) == EMPTY:
                    open_ends += 1
                    break
                else:
                    break
            else:
                break  # Ra ngoài biên = bị chặn

        # Đếm ngược
        for i in range(1, 6):
            nx, ny = x - dx * i, y - dy * i
            if 0 <= nx < board.hcount and 0 <= ny < board.vcount:
                if board.get(nx, ny) == symbol:
                    count += 1
                elif board.get(nx, ny) == EMPTY:
                    open_ends += 1
                    break
                else:
                    break
            else:
                break

        return count, open_ends

    def evaluate_point(self, board: CaroBoard, x: int, y: int, symbol: int) -> int:
        """Đánh giá giá trị của quân tại (x,y) cho symbol."""
        total = 0
        directions = [(1, 0), (0, 1), (1, 1), (1, -1)]
        threat_count_half_four = 0
        threat_count_open_three = 0

        for dx, dy in directions:
            count, open_ends = self.analyze_line_pattern(board, x, y, dx, dy, symbol)

            if count >= 5:
                total += self.SCORES['FIVE']
            elif count == 4:
                if open_ends == 2:
                    total += self.SCORES['OPEN_FOUR']
                    threat_count_half_four += 1
                elif open_ends == 1:
                    total += self.SCORES['HALF_FOUR']
                    threat_count_half_four += 1
            elif count == 3:
                if open_ends == 2:
                    total += self.SCORES['OPEN_THREE']
                    threat_count_open_three += 1
                elif open_ends == 1:
                    total += self.SCORES['HALF_THREE']
            elif count == 2:
                if open_ends == 2:
                    total += self.SCORES['OPEN_TWO']
                elif open_ends == 1:
                    total += self.SCORES['HALF_TWO']

        # Thưởng double threat
        if threat_count_half_four >= 2:
            total += self.DOUBLE_THREAT_BONUS
        if threat_count_half_four >= 1 and threat_count_open_three >= 1:
            total += self.DOUBLE_THREAT_BONUS // 2
        if threat_count_open_three >= 2:
            total += self.DOUBLE_THREAT_BONUS // 3

        return total

    def evaluate_board(self, board: CaroBoard, my_sym: int, opp_sym: int) -> int:
        """Đánh giá toàn bộ bàn cờ."""
        score = 0
        counted = set()  # Tránh đếm trùng

        # Đánh giá từng quân đã đặt
        for y in range(board.vcount):
            for x in range(board.hcount):
                cell = board.get(x, y)
                if cell == my_sym:
                    key = (x, y, my_sym)
                    if key not in counted:
                        counted.add(key)
                        score += self.evaluate_point(board, x, y, my_sym)
                elif cell == opp_sym:
                    key = (x, y, opp_sym)
                    if key not in counted:
                        counted.add(key)
                        score -= self.evaluate_point(board, x, y, opp_sym) * 1.1  # Phòng thủ quan trọng hơn chút

        # Ưu tiên vị trí trung tâm
        center_x = board.hcount // 2
        center_y = board.vcount // 2
        for y in range(board.vcount):
            for x in range(board.hcount):
                cell = board.get(x, y)
                if cell == my_sym:
                    dist = abs(x - center_x) + abs(y - center_y)
                    score += max(0, 15 - dist * 2)
                elif cell == opp_sym:
                    dist = abs(x - center_x) + abs(y - center_y)
                    score -= max(0, 10 - dist)

        return int(score)

    def get_candidate_moves(self, board: CaroBoard) -> list:
        """Lấy danh sách nước đi ứng viên, sắp xếp theo heuristic."""
        neighbors = board.get_neighbors(radius=2)
        if not neighbors:
            cx = board.hcount // 2
            cy = board.vcount // 2
            return [(cx, cy)]
        return neighbors

    def order_moves(self, board: CaroBoard, moves: list, my_sym: int, opp_sym: int) -> list:
        """Sắp xếp nước đi theo heuristic để alpha-beta cắt được nhiều nhánh."""
        scored = []
        for x, y in moves:
            score = 0

            # Nước thắng ngay
            board.place(x, y, my_sym)
            if self.check_win_at(board, x, y, my_sym):
                board.unplace(x, y)
                return [(x, y)]  # Trả về ngay nước thắng
            score += self.evaluate_point(board, x, y, my_sym)
            board.unplace(x, y)

            # Chặn nước thắng đối thủ
            board.place(x, y, opp_sym)
            if self.check_win_at(board, x, y, opp_sym):
                score += self.SCORES['FIVE'] - 1  # Rất quan trọng
            score += self.evaluate_point(board, x, y, opp_sym) * 0.9
            board.unplace(x, y)

            # Ưu tiên gần trung tâm
            center_x = board.hcount // 2
            center_y = board.vcount // 2
            dist = abs(x - center_x) + abs(y - center_y)
            score += max(0, 20 - dist * 2)

            scored.append((score, x, y))

        scored.sort(reverse=True)
        # Chỉ lấy top moves để giới hạn branching factor
        top_n = min(len(scored), 15)
        return [(x, y) for _, x, y in scored[:top_n]]

    def minimax(self, board: CaroBoard, depth: int, alpha: float, beta: float,
                is_maximizing: bool, my_sym: int, opp_sym: int) -> int:
        """Minimax với Alpha-Beta Pruning."""
        self.nodes_searched += 1

        # Kiểm tra timeout
        if self.timeout_flag or (time.time() - self.start_time) > self.time_limit:
            return self.evaluate_board(board, my_sym, opp_sym)

        # Terminal: depth = 0
        if depth == 0:
            return self.evaluate_board(board, my_sym, opp_sym)

        moves = self.get_candidate_moves(board)
        if not moves:
            return self.evaluate_board(board, my_sym, opp_sym)

        # Sắp xếp nước đi
        current_sym = my_sym if is_maximizing else opp_sym
        other_sym = opp_sym if is_maximizing else my_sym
        moves = self.order_moves(board, moves, current_sym, other_sym)

        if is_maximizing:
            max_eval = float('-inf')
            for x, y in moves:
                # Kiểm tra nước thắng ngay
                board.place(x, y, my_sym)
                if self.check_win_at(board, x, y, my_sym):
                    board.unplace(x, y)
                    return self.SCORES['FIVE'] + depth * 1000  # Thắng sớm = điểm cao hơn
                eval_score = self.minimax(board, depth - 1, alpha, beta, False, my_sym, opp_sym)
                board.unplace(x, y)
                max_eval = max(max_eval, eval_score)
                alpha = max(alpha, eval_score)
                if beta <= alpha:
                    break  # Cắt nhánh
            return max_eval
        else:
            min_eval = float('inf')
            for x, y in moves:
                # Kiểm tra đối thủ thắng
                board.place(x, y, opp_sym)
                if self.check_win_at(board, x, y, opp_sym):
                    board.unplace(x, y)
                    return -(self.SCORES['FIVE'] + depth * 1000)  # Thua sớm = điểm rất thấp
                eval_score = self.minimax(board, depth - 1, alpha, beta, True, my_sym, opp_sym)
                board.unplace(x, y)
                min_eval = min(min_eval, eval_score)
                beta = min(beta, eval_score)
                if beta <= alpha:
                    break  # Cắt nhánh
            return min_eval

    def find_best_move(self, my_sym: int, opp_sym: int):
        """Tìm nước đi tốt nhất dùng Iterative Deepening Minimax."""
        board = self.board
        self.start_time = time.time()
        self.timeout_flag = False

        # 1. Kiểm tra nước thắng ngay
        candidates = self.get_candidate_moves(board)
        for x, y in candidates:
            board.place(x, y, my_sym)
            if self.check_win_at(board, x, y, my_sym):
                board.unplace(x, y)
                log.info(f"🎯 Nước thắng ngay: ({x}, {y})")
                return (x, y)
            board.unplace(x, y)

        # 2. Chặn nước thắng đối thủ
        for x, y in candidates:
            board.place(x, y, opp_sym)
            if self.check_win_at(board, x, y, opp_sym):
                board.unplace(x, y)
                log.info(f"🛡️ Chặn nước thắng: ({x}, {y})")
                return (x, y)
            board.unplace(x, y)

        # 3. Iterative Deepening Minimax
        best_move = candidates[0] if candidates else (board.hcount // 2, board.vcount // 2)
        best_score = float('-inf')

        for depth in range(1, AI_MAX_DEPTH + 1):
            if self.timeout_flag or (time.time() - self.start_time) > self.time_limit:
                break

            self.nodes_searched = 0
            current_best_move = None
            current_best_score = float('-inf')

            # Lấy và sắp xếp nước đi
            moves = self.order_moves(board, candidates, my_sym, opp_sym)

            for x, y in moves:
                if self.timeout_flag or (time.time() - self.start_time) > self.time_limit:
                    break

                board.place(x, y, my_sym)
                if self.check_win_at(board, x, y, my_sym):
                    board.unplace(x, y)
                    log.info(f"🎯 Thắng ở depth {depth}: ({x}, {y})")
                    return (x, y)

                score = self.minimax(board, depth - 1, float('-inf'), float('inf'),
                                     False, my_sym, opp_sym)
                board.unplace(x, y)

                if score > current_best_score:
                    current_best_score = score
                    current_best_move = (x, y)

            if current_best_move and not self.timeout_flag:
                best_move = current_best_move
                best_score = current_best_score
                elapsed = time.time() - self.start_time
                log.info(f"  Depth {depth}: best=({best_move[0]},{best_move[1]}) "
                         f"score={best_score} nodes={self.nodes_searched} time={elapsed:.2f}s")

        elapsed = time.time() - self.start_time
        log.info(f"🧠 AI chọn: ({best_move[0]}, {best_move[1]}) score={best_score} "
                 f"total_time={elapsed:.2f}s nodes={self.nodes_searched}")
        return best_move


# ─── Game Client ────────────────────────────────────────────
class CaroBot:
    """Bot chơi Caro trên gamevh.net - Cải tiến: ở yên phòng, không thoát."""

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
        self.nickname = ""
        self.token = 0
        self.cookie_header = ""
        self.place_path = PLACE_PATH
        self.session = None  # requests.Session để giữ cookie
        self.current_table_path = ""  # Path bàn hiện tại

    def login_and_handshake(self) -> bool:
        """Đăng nhập bằng username/password rồi lấy token & nickname.
        
        Quan trọng: Phải POST đúng URL (có port 443) và gửi đủ tất cả form fields
        để server set các cookie cần thiết (clientIp, memberName, memberPassword).
        """
        log.info(f"🔐 Đăng nhập với username={USERNAME}...")

        try:
            self.session = requests.Session()

            # Bước 1: GET trang game trước để lấy JSESSIONID
            r = self.session.get(GAME_URL, timeout=10, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            })
            log.info(f"GET game page: status={r.status_code}")

            # Bước 2: GET trang login.jsp để lấy form (và giữ cùng JSESSIONID)
            r = self.session.get("https://gamevh.net/login.jsp", timeout=10, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            })
            log.info(f"GET login.jsp: status={r.status_code}")

            # Bước 3: POST đăng nhập với ĐỦ form fields và đúng URL (có port 443)
            # Form action: https://gamevh.net:443/login.jsp
            # Fields: USER_NAME, PASSWORD, redirect, AUTO_LOGIN, LOGIN
            login_data = {
                "USER_NAME": USERNAME,
                "PASSWORD": PASSWORD,
                "redirect": "/",
                "AUTO_LOGIN": "true",
                "LOGIN": "Đăng nhập",
            }
            r = self.session.post("https://gamevh.net:443/login.jsp", data=login_data, timeout=10, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Origin": "https://gamevh.net",
                "Referer": "https://gamevh.net/login.jsp",
                "Content-Type": "application/x-www-form-urlencoded",
            }, allow_redirects=True)
            log.info(f"POST login: status={r.status_code}, url={r.url}")

            # Kiểm tra cookies xác thực - cần có memberName và memberPassword
            cookies = self.session.cookies.get_dict()
            log.info(f"Cookies sau login: {list(cookies.keys())}")
            
            if 'memberName' not in cookies or 'memberPassword' not in cookies:
                log.error("❌ Thiếu cookie xác thực (memberName/memberPassword)! Đăng nhập có thể thất bại.")
                log.error(f"Cookies có: {cookies}")
                return False

            # Bước 4: GET trang game lại để lấy token & nickname
            r = self.session.get(GAME_URL, timeout=10, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            })
            log.info(f"GET game page after login: status={r.status_code}")

            # Build cookie header từ session (gồm JSESSIONID, clientIp, memberName, memberPassword)
            cookies = self.session.cookies.get_dict()
            self.cookie_header = '; '.join(f'{k}={v}' for k, v in cookies.items())
            log.info(f"Cookie header: {self.cookie_header[:80]}...")

            html = r.text

            # Extract token (với retry nhiều lần)
            import time as _t
            token_found = False
            for attempt in range(5):
                m = re.search(r'var\s+token\s*=\s*(\d+)', html)
                if m:
                    self.token = int(m.group(1))
                    log.info(f"Token: {self.token}")
                    token_found = True
                    break
                else:
                    log.warning(f"Lần {attempt+1}/5: Không tìm thấy token, thử lại sau 2s...")
                    _t.sleep(2)
                    r = self.session.get(GAME_URL, timeout=10, headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                    })
                    html = r.text

            if not token_found:
                log.error("Không tìm thấy token sau 5 lần thử!")
                return False

            # Extract nickname
            m = re.search(r"var\s+currentPlayerNickName\s*=\s*'([^']+)'", html)
            if m:
                self.nickname = m.group(1)
                log.info(f"Nickname: {self.nickname}")
            else:
                log.error("Không tìm thấy nickname!")
                return False

            # Verify nickname matches our username
            if self.nickname != USERNAME:
                log.warning(f"⚠️ Nickname ({self.nickname}) != username ({USERNAME})! Có thể đăng nhập sai tài khoản.")

            # Extract placePath
            m = re.search(r'var\s+placePath\s*=\s*"([^"]+)"', html)
            if m:
                self.place_path = m.group(1)
                log.info(f"PlacePath: {self.place_path}")

            log.info(f"✅ Đăng nhập thành công! nickname={self.nickname}")
            return True

        except Exception as e:
            log.error(f"Lỗi đăng nhập: {e}")
            import traceback
            traceback.print_exc()
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
            log.info("✅ Đã kết nối WebSocket!")
            return True
        except Exception as e:
            log.error(f"❌ Lỗi kết nối: {e}")
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

            elif cmd == "SET_READY":
                status = r.read_byte()
                log.info(f"SET_READY response: {status}")

            elif cmd == "CMD_415":
                log.debug("TABLE_IN_ROOM_CHANGED")

            elif cmd == "CMD_416":
                log.debug("SLOT_IN_TABLE_CHANGED")

            elif cmd == "CMD_345":
                slot_id = r.read_byte()
                mode = r.read_byte()
                log.info(f"🔄 CLIENT_MODE_CHANGED: slot={slot_id}, mode={mode}")

            elif cmd == "CMD_424":
                pass

            else:
                log.debug(f"Unhandled command: {cmd} (remaining bytes: {r.remaining()})")

        except Exception as e:
            log.error(f"Lỗi xử lý {cmd}: {e}")
            import traceback
            traceback.print_exc()

    async def handle_login(self, r: ConnReader):
        status = r.read_byte()
        log.info(f"LOGIN status={status}, remaining={r.remaining()}")
        if status == 0:
            path = r.read_string()
            log.info(f"LOGIN path={path}")
            if path == "REFRESH":
                log.info("🔄 Server yêu cầu REFRESH - vẫn tiếp tục...")
                await self.send(self.build_enter_place_msg(self.place_path, "", 1))
                return
            if r.remaining() > 0:
                self.login_cookie = r.read_ascii()
            if r.remaining() > 0:
                password = r.read_string()
            if r.remaining() > 0:
                material = r.read_ascii()
            log.info(f"✅ LOGIN thành công! path={path}")
            await self.send(self.build_enter_place_msg(self.place_path, "", 1))
        else:
            if r.remaining() > 0:
                error_msg = r.read_string()
                log.error(f"❌ LOGIN thất bại: status={status}, msg={error_msg}")
            else:
                log.error(f"❌ LOGIN thất bại: status={status}")

    async def handle_quick_play(self, r: ConnReader):
        try:
            status = r.read_byte()
            if status != 0:
                error_msg = r.read_string() if r.remaining() > 0 else ""
                log.info(f"🎲 Quick play lỗi: {error_msg}")
                await asyncio.sleep(3)
                await self.send(self.build_quick_play_msg())
                return

            table_path = r.read_ascii()
            table_name = r.read_string()
            log.info(f"🎲 Quick play -> path={table_path}, name={table_name}")

            if r.remaining() > 0:
                arg_count = r.read_ubyte()
                for _ in range(arg_count):
                    key = r.read_ascii()
                    val = r.read_string()
                    log.info(f"  Arg: {key}={val}")

            if table_path:
                self.current_table_path = table_path
                self.in_table = True
                self.ready_sent = False  # Reset cho bàn mới
                self.mode_set = False    # Reset cho bàn mới
                log.info(f"🏠 Entering table: {table_path}")
                await self.send(self.build_enter_place_msg(table_path, "", 1))
                # SET_CLIENT_MODE và GET_TABLE_DATA_EX sẽ được gửi trong handle_enter_place

        except Exception as e:
            log.error(f"Lỗi parse quick play: {e}")
            import traceback
            traceback.print_exc()

    async def handle_enter_place(self, r: ConnReader):
        currency = r.read_byte()
        rate = r.read_ushort()
        log.info(f"🏠 ENTER_PLACE: currency={'chip' if currency == 0 else 'star'}, rate={rate/10}")
        # Luôn gửi SET_CLIENT_MODE(1) = PLAY khi vào place mới
        await asyncio.sleep(0.3)
        await self.send(self.build_set_client_mode_msg(1))
        self.mode_set = True
        await asyncio.sleep(0.3)
        await self.send(self.build_get_table_data_ex_msg())

    async def handle_table_data_ex(self, r: ConnReader):
        try:
            first_byte = r.read_byte()
            if first_byte != 0:
                error_code = first_byte
                error_msg = r.read_string() if r.remaining() > 0 else ""
                log.info(f"📋 GET_TABLE_DATA_EX error: code={error_code}, msg={error_msg}")
                if not self.in_table:
                    log.info("⏳ Chưa ngồi bàn, tìm bàn mới...")
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
                log.info(f"  👤 Slot {slot_id}: {full_name} (id={player_id}, lv={level}, owner={is_owner})")

            current_turn_slot = r.read_byte()
            turn_timeout = r.read_short()
            slot_remain = r.read_short()
            current_state = r.read_ubyte()

            log.info(f"  My slot: {self.my_slot_id}, playing: {self.is_playing}, "
                     f"turn_slot: {current_turn_slot}, state: {current_state}")

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
                log.info("⏳ Đang ngồi bàn, chờ đối thủ/ván mới...")
                # Gửi SET_CLIENT_MODE(1) = PLAY rồi SET_READY
                if not self.ready_sent:
                    self.ready_sent = True
                    await asyncio.sleep(0.5)
                    await self.send(self.build_set_client_mode_msg(1))
                    log.info("✅ Gửi SET_CLIENT_MODE(PLAY)")
                    await asyncio.sleep(0.5)
                    await self.send(self.build_set_ready_msg())
                    log.info("✅ Đã gửi SET_READY - chờ đối thủ")

        except Exception as e:
            log.error(f"Lỗi parse table data: {e}")
            import traceback
            traceback.print_exc()

    async def handle_start_match(self, r: ConnReader):
        self.game_count += 1
        self.is_playing = True

        point_count = r.read_ubyte()
        for _ in range(point_count):
            slot_id = r.read_byte()
            point = r.read_int()
            log.info(f"  Match point: slot {slot_id} = {point}")

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
        slot_id = r.read_byte()
        turn_timeout = r.read_short()
        remain_duration = r.read_short()

        is_my_turn = (slot_id == self.my_slot_id)
        log.info(f"🔄 SET_TURN: slot={slot_id} (me={self.my_slot_id}), "
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
            log.info(f"✓ Xác nhận: ({x}, {y}) pos={pos} symbol={sym_char}")
            self.my_symbol = symbol
            self.opp_symbol = SYMBOL_O if symbol == SYMBOL_X else SYMBOL_X
        elif current == EMPTY:
            log.info(f"⛔ Đối thủ đánh: ({x}, {y}) pos={pos} symbol={sym_char}")
            self.board.place(x, y, symbol)
            if len(self.board.move_history) <= 2:
                self.opp_symbol = symbol
                self.my_symbol = SYMBOL_O if symbol == SYMBOL_X else SYMBOL_X
        else:
            log.warning(f"⚠️ MOVE conflict tại ({x}, {y}): expected {current}, got {symbol}")
            self.board.place(x, y, symbol)
        log.info(f"  Board:\n{self.board.display()}")

    async def handle_highlight(self, r: ConnReader):
        count = r.read_ubyte()
        positions = []
        for _ in range(count):
            pos = r.read_short()
            x, y = self.board.pos_to_xy(pos)
            positions.append((x, y))
        log.info(f"🏆 Winning line: {positions}")

    async def handle_gameover(self, r: ConnReader):
        """Xử lý GAMEOVER - Ở YÊN TRONG BÀN, KHÔNG THOÁT RA."""
        self.is_playing = False
        self.is_my_turn = False
        self.ready_sent = False  # Reset để gửi lại SET_READY

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

        # ⭐ CẢI TIẾN: Ở YÊN TRONG BÀN, chỉ gửi SET_READY chờ ván mới
        # KHÔNG gửi QUICK_PLAY (sẽ thoát bàn)
        await asyncio.sleep(2)
        log.info("🏠 Ở yên trong bàn, gửi SET_READY chờ ván mới...")
        self.ready_sent = True
        await self.send(self.build_set_ready_msg())
        log.info("✅ Đã gửi SET_READY - chờ đối thủ sẵn sàng")

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
        log.info(f"👤 Player entered: slot {slot_id} - {full_name} (lv={level})")

        # Nếu có người vào bàn và mình chưa ready
        if not self.is_playing and not self.ready_sent:
            self.ready_sent = True
            await asyncio.sleep(0.5)
            await self.send(self.build_set_client_mode_msg(1))
            log.info("✅ Đối thủ vào bàn, gửi SET_CLIENT_MODE(PLAY)")
            await asyncio.sleep(0.5)
            await self.send(self.build_set_ready_msg())
            log.info("✅ Đối thủ vào bàn, gửi SET_READY")

    def _determine_symbols(self):
        x_count = sum(1 for row in self.board.board for cell in row if cell == SYMBOL_X)
        o_count = sum(1 for row in self.board.board for cell in row if cell == SYMBOL_O)

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

        x, y = self.ai.find_best_move(self.my_symbol, self.opp_symbol)
        pos = self.board.xy_to_pos(x, y)

        log.info(f"🎯 TA ĐÁNH: ({x}, {y}) pos={pos}")
        await self.send(self.build_play_msg(pos))

        self.board.place(x, y, self.my_symbol)
        log.info(f"  Board:\n{self.board.display()}")

    async def run(self):
        # Đăng nhập bằng username/password
        if not self.login_and_handshake():
            log.error("Đăng nhập thất bại!")
            return

        if not await self.connect():
            return

        login_msg = self.build_login_msg()
        log.info(f"Đang đăng nhập với nick={self.nickname}, token={self.token}...")
        await self.send(login_msg)

        try:
            # Dùng asyncio.wait_for để phát hiện kết nối chết (không nhận msg quá 60s)
            while self.running:
                try:
                    raw = await asyncio.wait_for(self.ws.recv(), timeout=60.0)
                except asyncio.TimeoutError:
                    log.warning("⏰ Không nhận message trong 60s - gửi ping...")
                    try:
                        ping_w = ConnWriter()
                        ping_w.write_command("PING")
                        await self.send(ping_w.to_bytes())
                        # Chờ pong
                        raw = await asyncio.wait_for(self.ws.recv(), timeout=15.0)
                    except asyncio.TimeoutError:
                        log.warning("❌ Không nhận PONG - kết nối chết!")
                        break
                    except Exception:
                        break

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

    async def run_with_reconnect(self, max_retries=50):
        """Chạy bot với tự động reconnect - cố gắng nhiều lần."""
        retries = 0
        while retries < max_retries:
            try:
                # Reset state cho lần reconnect
                self.is_playing = False
                self.is_my_turn = False
                self.in_table = False
                self.ready_sent = False
                self.mode_set = False
                self.running = True
                self.board.clear()

                await self.run()
            except Exception as e:
                log.error(f"Lỗi nghiêm trọng: {e}")

            retries += 1
            wait_time = min(5 * retries, 30)
            log.info(f"Đợi {wait_time}s trước khi reconnect (lần {retries}/{max_retries})...")
            await asyncio.sleep(wait_time)


# ─── Main ───────────────────────────────────────────────────
async def main():
    bot = CaroBot()
    await bot.run_with_reconnect()


if __name__ == "__main__":
    asyncio.run(main())
