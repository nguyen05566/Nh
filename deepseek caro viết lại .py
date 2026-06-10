#!/usr/bin/env python3
"""
Caro Bot - Heuristic thuần túy, không AI phức tạp
Chỉ dùng: websocket + heuristic chọn nước đi
"""

import asyncio
import struct
import time
import logging
import re
import random
import os
import json
from typing import List, Tuple, Dict, Optional

try:
    import websockets
    import requests
except ImportError:
    import subprocess
    subprocess.run(["pip", "install", "websockets", "requests", "-q"])
    import websockets
    import requests

# ========================== CẤU HÌNH ==========================
WS_URL = "wss://gamevh.net/ws/gameServer"
GAME_URL = "https://gamevh.net/play/caro/0"
USER = "nguyen05511"
PASSWD = "nhat123456"
VERSION = "5.0.2"
GAME_ID = "caro"
RUNTIME = 12 * 3600  # 12 giờ

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("caro")

# ========================== HẰNG SỐ ==========================
EMPTY = -1
CIRCLE = 0   # O
CROSS = 1    # X

DIRECTIONS = [(1, 0), (0, 1), (1, 1), (1, -1)]

# Map command ID -> tên lệnh
CMD_MAP = {
    300: "PONG", 301: "PING", 302: "LOGIN", 303: "ALERT", 304: "RIBBON_MESSAGE",
    311: "BROADCAST", 312: "INVITE", 314: "SET_CLIENT_MODE", 315: "CONFIG",
    401: "ENTER_PLACE", 402: "ENTER_CHILD_PLACE", 406: "PLAYER_ENTERED",
    407: "PLAYER_EXITED", 408: "QUICK_PLAY", 414: "GET_TABLE_DATA",
    417: "START_MATCH", 418: "GAMEOVER", 419: "ENTER_STATE", 420: "SET_TURN",
    421: "SET_PLAYER_STATUS", 422: "SET_PLAYER_POINT", 423: "SET_PLAYER_ATTR",
    431: "BALANCE_CHANGED", 432: "OWNER_CHANGED", 433: "GET_TABLE_DATA_EX",
    434: "SET_READY", 501: "BET", 502: "PLAY", 505: "CHAT", 518: "HIGHLIGHT",
    529: "MOVE", 533: "ASK_DRAW", 534: "SURRENDER", 535: "RETREAT",
}

# Điểm số cho các pattern
PATTERN_SCORES = {
    'FIVE': 100_000_000,
    'OPEN4': 5_000_000,
    'HALF4': 500_000,
    'OPEN3': 100_000,
    'HALF3': 10_000,
    'OPEN2': 2_000,
    'HALF2': 200
}

# ========================== ĐỌC/GHI NHỊ PHÂN ==========================
class BinaryReader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def remaining(self) -> int:
        return len(self.data) - self.pos

    def u8(self) -> int:
        v = self.data[self.pos]
        self.pos += 1
        return v

    def i8(self) -> int:
        v = struct.unpack_from('>b', self.data, self.pos)[0]
        self.pos += 1
        return v

    def i16(self) -> int:
        v = struct.unpack_from('>h', self.data, self.pos)[0]
        self.pos += 2
        return v

    def u16(self) -> int:
        v = struct.unpack_from('>H', self.data, self.pos)[0]
        self.pos += 2
        return v

    def i32(self) -> int:
        v = struct.unpack_from('>i', self.data, self.pos)[0]
        self.pos += 4
        return v

    def i64(self) -> int:
        hi = struct.unpack_from('>i', self.data, self.pos)[0]
        lo = struct.unpack_from('>I', self.data, self.pos + 4)[0]
        self.pos += 8
        return (hi << 32) + lo

    def read_ascii(self) -> str:
        n = self.u8()
        s = self.data[self.pos:self.pos + n]
        self.pos += n
        return s.decode('ascii', 'replace')

    def read_utf(self) -> str:
        n = self.i16()
        if n <= 0:
            return ""
        s = self.data[self.pos:self.pos + n * 2]
        self.pos += n * 2
        return s.decode('utf-16-be', 'replace')

    def read_bytes(self) -> List[int]:
        n = self.i16()
        return list(self.data[self.pos:self.pos + n])

    def read_command(self) -> str:
        first = self.i8()
        if first < 0:
            n = -first
            s = self.data[self.pos:self.pos + n].decode('ascii', 'replace')
            self.pos += n
            return s
        second = self.u8()
        cmd_id = (first << 8) | second
        return CMD_MAP.get(cmd_id, f"CMD_{cmd_id}")


class BinaryWriter:
    def __init__(self):
        self.parts = []

    def u8(self, v: int):
        self.parts.append(struct.pack('>B', v))

    def i8(self, v: int):
        self.parts.append(struct.pack('>b', v))

    def i16(self, v: int):
        self.parts.append(struct.pack('>h', v))

    def i32(self, v: int):
        self.parts.append(struct.pack('>i', v))

    def i64(self, v: int):
        self.parts.append(struct.pack('>iI', v >> 32, v & 0xFFFFFFFF))

    def write_ascii(self, s: str):
        encoded = s.encode('ascii', 'replace')
        self.u8(len(encoded))
        self.parts.append(encoded)

    def write_utf(self, s: str):
        encoded = s.encode('utf-16-be')
        self.i16(len(encoded) // 2)
        self.parts.append(encoded)

    def write_command(self, cmd: str):
        cmd_id = next((k for k, v in CMD_MAP.items() if v == cmd), None)
        if cmd_id:
            self.parts.append(struct.pack('>H', cmd_id))
        else:
            b = cmd.encode('ascii')
            self.i8(-len(b))
            self.parts.append(b)

    def build(self) -> bytes:
        return b''.join(self.parts)


# ========================== BÀN CỜ ==========================
class Board:
    def __init__(self, width: int = 15, height: int = 19):
        self.width = width
        self.height = height
        self.grid = [[EMPTY] * width for _ in range(height)]
        self.history = []
        self.placed = set()

    def resize(self, width: int, height: int):
        self.width = width
        self.height = height
        self.grid = [[EMPTY] * width for _ in range(height)]
        self.history.clear()
        self.placed.clear()

    def get(self, x: int, y: int) -> int:
        if 0 <= x < self.width and 0 <= y < self.height:
            return self.grid[y][x]
        return EMPTY

    def put(self, x: int, y: int, symbol: int):
        if 0 <= x < self.width and 0 <= y < self.height:
            self.grid[y][x] = symbol
            self.history.append((x, y, symbol))
            self.placed.add((x, y))

    def undo(self, x: int, y: int):
        if 0 <= x < self.width and 0 <= y < self.height:
            self.grid[y][x] = EMPTY
            if self.history and self.history[-1][:2] == (x, y):
                self.history.pop()
            self.placed.discard((x, y))

    def xy_to_pos(self, x: int, y: int) -> int:
        return y * self.width + x

    def pos_to_xy(self, pos: int) -> Tuple[int, int]:
        return pos % self.width, pos // self.width

    def load_rle(self, data: List[int]):
        """Giải mã RLE từ server"""
        self.grid = [[EMPTY] * self.width for _ in range(self.height)]
        self.history.clear()
        self.placed.clear()
        pos = 0
        for value in data:
            symbol = value - 256 if value > 127 else value
            if symbol >= 0:
                y, x = pos // self.width, pos % self.width
                if 0 <= x < self.width and 0 <= y < self.height:
                    self.grid[y][x] = symbol
                    self.placed.add((x, y))
                pos += 1
            else:
                pos += -symbol

    def get_neighbors(self, radius: int = 2) -> List[Tuple[int, int]]:
        """Lấy các ô trống xung quanh quân cờ đã có"""
        seen = set()
        result = []
        for y in range(self.height):
            for x in range(self.width):
                if self.grid[y][x] != EMPTY:
                    for dy in range(-radius, radius + 1):
                        for dx in range(-radius, radius + 1):
                            nx, ny = x + dx, y + dy
                            if (0 <= nx < self.width and 0 <= ny < self.height and
                                self.grid[ny][nx] == EMPTY and (nx, ny) not in seen):
                                seen.add((nx, ny))
                                result.append((nx, ny))
        return result


# ========================== HEURISTIC ==========================
def count_direction(board: Board, x: int, y: int, dx: int, dy: int, symbol: int) -> int:
    """Đếm số quân liên tiếp theo một hướng"""
    count = 0
    for i in range(1, 6):
        if board.get(x + dx * i, y + dy * i) == symbol:
            count += 1
        else:
            break
    return count


def analyze_position(board: Board, x: int, y: int, symbol: int) -> List[Tuple[str, int]]:
    """Phân tích pattern tại vị trí (x,y) nếu đặt quân symbol"""
    patterns = []
    for dx, dy in DIRECTIONS:
        forward = count_direction(board, x, y, dx, dy, symbol)
        backward = count_direction(board, x, y, -dx, -dy, symbol)
        total = 1 + forward + backward

        # Kiểm tra ô trống ở hai đầu
        front_empty = board.get(x + dx * (forward + 1), y + dy * (forward + 1)) == EMPTY
        back_empty = board.get(x - dx * (backward + 1), y - dy * (backward + 1)) == EMPTY
        open_ends = int(front_empty) + int(back_empty)

        if total >= 5:
            patterns.append(('FIVE', open_ends))
        elif total == 4:
            if open_ends == 2:
                patterns.append(('OPEN4', 2))
            elif open_ends == 1:
                patterns.append(('HALF4', 1))
        elif total == 3:
            if open_ends == 2:
                patterns.append(('OPEN3', 2))
            elif open_ends == 1:
                patterns.append(('HALF3', 1))
        elif total == 2:
            if open_ends == 2:
                patterns.append(('OPEN2', 2))
            elif open_ends == 1:
                patterns.append(('HALF2', 1))
    return patterns


def score_position(board: Board, x: int, y: int, symbol: int) -> int:
    """Tính điểm cho một nước đi"""
    board.put(x, y, symbol)
    patterns = analyze_position(board, x, y, symbol)
    board.undo(x, y)

    base_score = sum(PATTERN_SCORES.get(p, 0) for p, _ in patterns)
    pattern_names = [p for p, _ in patterns]

    # Bonus cho các kết hợp đặc biệt
    if pattern_names.count('OPEN4') >= 2:
        base_score += 8_000_000
    if pattern_names.count('HALF4') >= 2:
        base_score += 1_000_000
    if pattern_names.count('HALF4') >= 1 and pattern_names.count('OPEN3') >= 1:
        base_score += 2_000_000
    if pattern_names.count('OPEN3') >= 2:
        base_score += 500_000
    if pattern_names.count('HALF4') >= 1 and pattern_names.count('HALF3') >= 1:
        base_score += 200_000

    return base_score


def full_score(board: Board, x: int, y: int, my_symbol: int) -> int:
    """Tính tổng điểm tấn công + phòng thủ + trung tâm"""
    opponent = CROSS if my_symbol == CIRCLE else CIRCLE
    attack = score_position(board, x, y, my_symbol)
    defense = score_position(board, x, y, opponent)

    # Thưởng cho vị trí gần trung tâm
    center_x, center_y = board.width // 2, board.height // 2
    center_bonus = max(0, 20 - (abs(x - center_x) + abs(y - center_y)) * 2)

    return int(attack) + int(defense * 1.15) + center_bonus


def find_pattern(board: Board, symbol: int, target_pattern: str) -> Optional[Tuple[int, int]]:
    """Tìm vị trí có pattern cụ thể"""
    for x, y in board.get_neighbors(radius=3):
        board.put(x, y, symbol)
        patterns = analyze_position(board, x, y, symbol)
        board.undo(x, y)
        if any(p == target_pattern for p, _ in patterns):
            return (x, y)
    return None


def pick_best_move(board: Board, my_symbol: int) -> Tuple[int, int]:
    """Chọn nước đi tốt nhất dựa trên heuristic"""
    opponent = CROSS if my_symbol == CIRCLE else CIRCLE
    move_count = len(board.history)

    # Nước đầu tiên: đánh trung tâm
    if move_count == 0:
        return board.width // 2, board.height // 2

    # Nước thứ hai: đánh cạnh nước đầu
    if move_count == 1:
        last_x, last_y, _ = board.history[-1]
        for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1),
                       (1, 1), (-1, -1), (1, -1), (-1, 1)]:
            nx, ny = last_x + dx, last_y + dy
            if 0 <= nx < board.width and 0 <= ny < board.height and board.get(nx, ny) == EMPTY:
                return nx, ny

    # Ưu tiên các pattern theo thứ tự
    # 1. Thắng ngay
    move = find_pattern(board, my_symbol, 'FIVE')
    if move:
        log.info(f"[WIN] {move}")
        return move

    # 2. Chặn thắng của đối thủ
    move = find_pattern(board, opponent, 'FIVE')
    if move:
        log.info(f"[BLOCK WIN] {move}")
        return move

    # 3. Tạo OPEN4
    move = find_pattern(board, my_symbol, 'OPEN4')
    if move:
        log.info(f"[OPEN4] {move}")
        return move

    # 4. Chặn OPEN4 đối thủ
    move = find_pattern(board, opponent, 'OPEN4')
    if move:
        log.info(f"[BLOCK OPEN4] {move}")
        return move

    # 5. Tạo HALF4
    move = find_pattern(board, my_symbol, 'HALF4')
    if move:
        log.info(f"[HALF4] {move}")
        return move

    # 6. Chặn HALF4 đối thủ
    move = find_pattern(board, opponent, 'HALF4')
    if move:
        log.info(f"[BLOCK HALF4] {move}")
        return move

    # 7. Điểm số tổng hợp
    candidates = board.get_neighbors(radius=2)
    if not candidates:
        return board.width // 2, board.height // 2

    best_move = candidates[0]
    best_score = -1
    for x, y in candidates:
        s = full_score(board, x, y, my_symbol)
        if s > best_score:
            best_score = s
            best_move = (x, y)

    log.info(f"[HEURISTIC] {best_move} score={best_score} candidates={len(candidates)}")
    return best_move


# ========================== BOT WEBSOCKET ==========================
class CaroBot:
    def __init__(self):
        self.ws = None
        self.board = Board()
        self.slot = -1
        self.my_symbol = CROSS
        self.opponent_symbol = CIRCLE
        self.is_playing = False
        self.in_table = False
        self.ready = False
        self.mode_set = False
        self.players: Dict[int, dict] = {}
        self.nickname = ""
        self.token = 0
        self.cookie = ""
        self.place_path = "Lobby.caro.0"
        self.lock_key = ""
        self.start_time = None
        self.last_activity = time.time()
        self.running = True
        self.wins = 0
        self.losses = 0
        self.draws = 0
        self.total_games = 0
        self.pending_move = False

        # Đọc lịch sử từ file
        try:
            with open("/tmp/caro.json") as f:
                data = json.load(f)
                self.wins = data.get('W', 0)
                self.losses = data.get('L', 0)
                self.draws = data.get('D', 0)
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def save_stats(self):
        """Lưu thống kê"""
        try:
            with open("/tmp/caro.json", "w") as f:
                json.dump({'W': self.wins, 'L': self.losses, 'D': self.draws}, f)
        except Exception:
            pass

    def update_symbols(self):
        """Cập nhật ký hiệu dựa vào slot"""
        self.my_symbol = CROSS if self.slot == 0 else CIRCLE
        self.opponent_symbol = CIRCLE if self.my_symbol == CROSS else CROSS
        log.info(f"Slot={self.slot} Me={'X' if self.my_symbol == CROSS else 'O'}")

    # ====== Tạo gói tin ======
    def make_login(self) -> bytes:
        w = BinaryWriter()
        w.write_command("LOGIN")
        w.write_ascii(self.nickname)
        w.i32(self.token)
        w.write_ascii(VERSION)
        w.write_ascii(self.lock_key)
        w.write_ascii(GAME_ID)
        w.i8(1)
        return w.build()

    def make_enter(self, path: str, password: str = "", mode: int = 1) -> bytes:
        w = BinaryWriter()
        w.write_command("ENTER_PLACE")
        w.write_ascii(path)
        w.write_utf(password)
        w.i8(mode)
        return w.build()

    def make_set_mode(self) -> bytes:
        w = BinaryWriter()
        w.write_command("SET_CLIENT_MODE")
        w.i8(1)
        return w.build()

    def make_get_table(self) -> bytes:
        w = BinaryWriter()
        w.write_command("GET_TABLE_DATA_EX")
        w.write_ascii("")
        return w.build()

    def make_play(self, pos: int) -> bytes:
        w = BinaryWriter()
        w.write_command("PLAY")
        w.i16(pos)
        return w.build()

    def make_pong(self) -> bytes:
        w = BinaryWriter()
        w.write_command("PONG")
        return w.build()

    def make_quick_play(self) -> bytes:
        w = BinaryWriter()
        w.write_command("QUICK_PLAY")
        w.write_ascii("")
        w.i8(-1)
        return w.build()

    def make_ready(self) -> bytes:
        w = BinaryWriter()
        w.write_command("SET_READY")
        return w.build()

    async def send(self, data: bytes):
        if self.ws:
            try:
                await self.ws.send(data)
            except Exception:
                pass

    async def do_move(self):
        """Thực hiện nước đi"""
        if not self.is_playing:
            return
        self.pending_move = False
        start = time.time()
        x, y = pick_best_move(self.board, self.my_symbol)
        pos = self.board.xy_to_pos(x, y)
        log.info(f"MOVE ({x},{y}) took {time.time() - start:.3f}s")
        await self.send(self.make_play(pos))
        self.board.put(x, y, self.my_symbol)

    # ====== Xử lý gói tin ======
    async def handle(self, raw: bytes):
        r = BinaryReader(raw)
        cmd = r.read_command()

        if cmd != "PING":
            log.info(f"RECV {cmd} remaining={r.remaining()}")

        self.last_activity = time.time()

        try:
            if cmd == "PING":
                await self.send(self.make_pong())
            elif cmd == "LOGIN":
                await self.handle_login(r)
            elif cmd == "ENTER_PLACE":
                await self.handle_enter(r)
            elif cmd == "GET_TABLE_DATA_EX":
                await self.handle_table(r)
            elif cmd == "QUICK_PLAY":
                await self.handle_quick_play(r)
            elif cmd == "START_MATCH":
                await self.handle_start(r)
            elif cmd == "SET_TURN":
                await self.handle_turn(r)
            elif cmd == "MOVE":
                await self.handle_move(r)
            elif cmd == "GAMEOVER":
                await self.handle_gameover(r)
            elif cmd == "PLAY":
                status = r.i8()
                if status != 0:
                    error_msg = r.read_utf() if r.remaining() > 0 else ""
                    log.warning(f"PLAY error {status}: {error_msg}")
                    if self.is_playing and self.pending_move:
                        await asyncio.sleep(0.3)
                        await self.do_move()
            elif cmd == "PLAYER_ENTERED":
                await self.handle_player_enter(r)
            elif cmd == "PLAYER_EXITED":
                sid = r.i8()
                self.players.pop(sid, None)
                if sid == self.slot:
                    self.in_table = False
                    self.is_playing = False
        except Exception as e:
            log.error(f"Error handling {cmd}: {e}", exc_info=True)

    async def handle_login(self, r: BinaryReader):
        status = r.i8()
        if status == 0:
            path = r.read_utf()
            if path == "REFRESH":
                await self.send(self.make_enter(self.place_path))
                return
            if r.remaining() > 0:
                self.lock_key = r.read_ascii()
            if r.remaining() > 0:
                r.read_utf()  # bỏ qua
            if r.remaining() > 0:
                r.read_ascii()  # bỏ qua
            await self.send(self.make_enter(self.place_path))
        else:
            error_msg = r.read_utf() if r.remaining() > 0 else ""
            log.error(f"LOGIN failed: {error_msg}")

    async def handle_enter(self, r: BinaryReader):
        r.i8()   # unknown
        r.u16()  # unknown
        if not self.mode_set:
            self.mode_set = True
            await self.send(self.make_set_mode())
        await self.send(self.make_get_table())

    async def handle_quick_play(self, r: BinaryReader):
        status = r.i8()
        if status != 0:
            error_msg = r.read_utf() if r.remaining() > 0 else ""
            if "notinzone" in error_msg.lower() and self.in_table:
                if not self.ready:
                    self.ready = True
                    await self.send(self.make_ready())
                return
            await asyncio.sleep(5)
            await self.send(self.make_quick_play())
            return

        path = r.read_ascii()
        r.read_utf()  # bỏ qua
        if r.remaining() > 0:
            n = r.u8()
            for _ in range(n):
                r.read_ascii()
                r.read_utf()

        if path:
            self.in_table = True
            await self.send(self.make_enter(path))
            await asyncio.sleep(0.5)
            await self.send(self.make_set_mode())
            await asyncio.sleep(0.3)
            await self.send(self.make_get_table())

    async def handle_table(self, r: BinaryReader):
        try:
            first_byte = r.i8()
            if first_byte != 0:
                error_msg = r.read_utf() if r.remaining() > 0 else ""
                if "not in table" in error_msg.lower():
                    await self.send(self.make_quick_play())
                return

            # Đọc thông tin bàn
            seat_count = r.u8()
            for _ in range(seat_count):
                r.u8()
                r.read_ascii()
                r.u8()
                child_count = r.u8()
                for _ in range(child_count):
                    r.u8()
                    r.read_ascii()
                    r.read_utf()
                    r.u8()
                    r.u8()

            r.u8()  # unknown
            self.slot = r.i8()
            is_playing = r.u8() == 1

            # Đọc danh sách người chơi
            player_count = r.u8()
            self.players = {}
            for _ in range(player_count):
                sid = r.i8()
                r.i64()  # user id
                name = r.read_utf()
                r.u16()
                r.read_ascii()
                r.i8()
                r.i64()
                r.i64()
                r.i64()
                r.u8()
                r.u8()
                self.players[sid] = {'name': name}
                log.info(f"  slot {sid}: {name}")

            current_player = r.i8()
            r.i16()
            r.i16()
            r.u8()

            self.in_table = True

            # Đọc trạng thái bàn cờ
            move_count = r.u8()
            for _ in range(move_count):
                r.i8()
                r.i32()

            width = r.u8()
            height = r.u8()
            self.board.resize(width, height)

            r.i16()  # unknown
            board_data = r.read_bytes()
            self.board.load_rle(board_data)
            self.update_symbols()

            r.u8()
            r.u8()
            n = r.u8()
            for _ in range(n):
                r.read_ascii()
                r.read_utf()

            self.is_playing = is_playing
            if is_playing and current_player == self.slot:
                self.pending_move = True
                await self.do_move()
            elif not is_playing:
                if not self.ready:
                    self.ready = True
                    await self.send(self.make_ready())

        except Exception as e:
            log.error(f"Table error: {e}", exc_info=True)

    async def handle_start(self, r: BinaryReader):
        self.total_games += 1
        self.is_playing = True
        self.ready = False

        player_count = r.u8()
        for _ in range(player_count):
            r.i8()
            r.i32()

        width = r.u8()
        height = r.u8()
        self.board.resize(width, height)

        r.i16()  # unknown
        board_data = r.read_bytes()
        self.board.load_rle(board_data)
        self.update_symbols()

        log.info(f"=== GAME {self.total_games} === Me={'X' if self.my_symbol == CROSS else 'O'}")

    async def handle_turn(self, r: BinaryReader):
        sid = r.i8()
        r.i16()
        r.i16()
        is_my_turn = (sid == self.slot)
        log.info(f"TURN slot={sid} my_turn={is_my_turn}")
        if is_my_turn and self.is_playing:
            self.pending_move = True
            await asyncio.sleep(0.15)
            await self.do_move()

    async def handle_move(self, r: BinaryReader):
        pos = r.i16()
        symbol = r.i8()
        x, y = self.board.pos_to_xy(pos)
        current = self.board.get(x, y)
        symbol_name = 'X' if symbol == CROSS else 'O'

        if current == symbol:
            log.info(f"[OK] ({x},{y}) {symbol_name}")
        elif current != EMPTY and current != symbol:
            log.warning(f"[SYNC] swapping symbol at ({x},{y})")
            self.my_symbol = symbol
            self.opponent_symbol = CROSS if symbol == CIRCLE else CIRCLE
            self.board.undo(x, y)
            self.board.put(x, y, symbol)
        else:
            log.info(f"[OPP] ({x},{y}) {symbol_name}")
            self.board.put(x, y, symbol)

    async def handle_gameover(self, r: BinaryReader):
        self.is_playing = False
        self.pending_move = False

        player_count = r.u8()
        my_result = None
        for _ in range(player_count):
            sid = r.i8()
            result = r.i8()
            earn = r.i64()
            if sid == self.slot:
                my_result = result

            result_map = {1: "WIN", 2: "LOSE", 3: "DRAW", 4: "LOSE",
                          10: "DRAW", 11: "WIN", 12: "LOSE"}
            log.info(f"  slot {sid}: {result_map.get(result, str(result))} earn={earn}")

        if my_result in (1, 11):
            self.wins += 1
            log.info(">>> WIN! <<<")
        elif my_result in (2, 4, 12):
            self.losses += 1
            log.info(">>> LOSE! <<<")
        else:
            self.draws += 1
            log.info(">>> DRAW! <<<")

        r.read_utf()  # bỏ qua

        win_rate = (self.wins / self.total_games * 100) if self.total_games else 0
        minutes = (time.time() - self.start_time) / 60 if self.start_time else 0
        log.info(f"STATS: {self.total_games}G {self.wins}W {self.losses}L {self.draws}D WR={win_rate:.0f}% {minutes:.0f}m")
        self.save_stats()

        await asyncio.sleep(2)
        if self.in_table:
            await self.send(self.make_ready())
            self.ready = True
        else:
            await self.send(self.make_quick_play())

    async def handle_player_enter(self, r: BinaryReader):
        sid = r.i8()
        r.i64()
        name = r.read_utf()
        r.u16()
        r.read_ascii()
        r.i8()
        r.i64()
        r.i64()
        r.i64()
        r.u8()
        r.u8()
        self.players[sid] = {'name': name}
        log.info(f"Enter slot {sid}: {name}")

    async def watchdog(self):
        """Giám sát kết nối và trạng thái"""
        while self.running:
            await asyncio.sleep(10)

            if not (self.ws and self.ws.close_code is None):
                continue

            try:
                # Kiểm tra thời gian chạy
                if self.start_time and time.time() - self.start_time > RUNTIME:
                    win_rate = (self.wins / self.total_games * 100) if self.total_games else 0
                    log.info(f"=== TIME'S UP === {self.total_games}G WR={win_rate:.0f}%")
                    self.running = False
                    self.save_stats()
                    await self.ws.close()
                    return

                # Tìm bàn mới nếu quá lâu không hoạt động
                if not self.is_playing and self.in_table and time.time() - self.last_activity > 60:
                    log.info("Idle -> finding new game")
                    self.in_table = False
                    self.ready = False
                    self.last_activity = time.time()
                    await self.send(self.make_enter("Lobby.caro.0"))
                    await asyncio.sleep(1)
                    await self.send(self.make_quick_play())

                # Force move nếu bị treo
                if self.is_playing and self.pending_move and time.time() - self.last_activity > 20:
                    log.warning("Stuck -> force move")
                    await self.do_move()

            except Exception:
                pass

    def http_login(self) -> bool:
        """Đăng nhập qua HTTP để lấy token và cookie"""
        try:
            session = requests.Session()
            ua = "Mozilla/5.0"

            session.get('https://gamevh.net/login.jsp', timeout=10, headers={'User-Agent': ua})
            resp = session.post('https://gamevh.net/login.jsp', timeout=10,
                                data={'redirect': '/', 'USER_NAME': USER, 'PASSWORD': PASSWD,
                                      'AUTO_LOGIN': 'on', 'LOGIN': 'Dang nhap'},
                                headers={'User-Agent': ua, 'Referer': 'https://gamevh.net/login.jsp',
                                         'Content-Type': 'application/x-www-form-urlencoded'})

            if 'login.jsp' in resp.url:
                log.error("HTTP login failed")
                return False

            game_resp = session.get(GAME_URL, timeout=10, headers={'User-Agent': ua})
            self.cookie = '; '.join(f'{k}={v}' for k, v in session.cookies.items())
            html = game_resp.text

            # Lấy token
            token_match = re.search(r'var\s+token\s*=\s*(-?\d+)', html)
            if not token_match:
                return False
            self.token = int(token_match.group(1))

            # Lấy nickname
            nick_match = re.search(r"var\s+currentPlayerNickName\s*=\s*'([^']+)'", html)
            if not nick_match:
                return False
            self.nickname = nick_match.group(1)

            # Lấy place path
            place_match = re.search(r'var\s+placePath\s*=\s*"([^"]+)"', html)
            if place_match:
                self.place_path = place_match.group(1)

            log.info(f"HTTP login OK: {self.nickname}")
            return True

        except Exception as e:
            log.error(f"HTTP login error: {e}")
            return False

    async def connect_ws(self) -> bool:
        """Kết nối WebSocket"""
        try:
            self.ws = await websockets.connect(
                WS_URL,
                additional_headers={
                    "Cookie": self.cookie,
                    "Origin": "https://gamevh.net",
                    "User-Agent": "Mozilla/5.0"
                },
                max_size=2**20,
                ping_interval=None
            )
            return True
        except Exception as e:
            log.error(f"WebSocket connect error: {e}")
            return False

    async def run_ws(self):
        """Chạy vòng lặp WebSocket"""
        if not await self.connect_ws():
            return

        await self.send(self.make_login())
        asyncio.create_task(self.watchdog())

        try:
            async for raw in self.ws:
                if isinstance(raw, bytes):
                    await self.handle(raw)
        except websockets.exceptions.ConnectionClosed as e:
            log.warning(f"Connection closed: {e}")
        except Exception as e:
            log.error(f"WebSocket error: {e}")
        finally:
            self.running = False
            self.save_stats()

    async def run(self):
        """Vòng lặp chính - tự động reconnect"""
        self.start_time = time.time()
        log.info(f"Carobot started - {RUNTIME // 3600} hours")

        retry_count = 0
        while self.running:
            elapsed = time.time() - self.start_time
            if elapsed > RUNTIME:
                win_rate = (self.wins / self.total_games * 100) if self.total_games else 0
                log.info(f"=== FINISHED {RUNTIME // 3600}H === {self.total_games}G {self.wins}W {self.losses}L WR={win_rate:.0f}%")
                break

            self.is_playing = False
            self.pending_move = False
            self.in_table = False
            self.ready = False
            self.mode_set = False
            self.running = True
            self.board = Board()

            # Đăng nhập
            login_ok = False
            for attempt in range(5):
                if self.http_login():
                    login_ok = True
                    break
                log.warning(f"Login attempt {attempt + 1}/5 failed, retry in 10s...")
                await asyncio.sleep(10)

            if not login_ok:
                log.error("Login failed 5 times, waiting 60s...")
                await asyncio.sleep(60)
                retry_count += 1
                continue

            await self.run_ws()

            if not self.running:
                break

            retry_count += 1
            wait_time = min(300* retry_count, 30)
            remaining = (RUNTIME - (time.time() - self.start_time)) / 60
            log.info(f"Reconnecting #{retry_count} in {wait_time}s... ({remaining:.0f}m left)")
            await asyncio.sleep(wait_time)

        self.save_stats()
        win_rate = (self.wins / self.total_games * 100) if self.total_games else 0
        log.info(f"Bot stopped. {self.total_games}G {self.wins}W {self.losses}L {self.draws}D WR={win_rate:.0f}%")


if __name__ == "__main__":
    asyncio.run(CaroBot().run())