#!/usr/bin/env python3
"""
Xiangqi Bot - gamevh.net
Kết nối WebSocket, phân tích binary protocol, sử dụng Pikafish engine
"""

import struct
import threading
import time
import sys
import os
import json
import signal
import subprocess
import requests
import re

# Fix import path for pikafish_terminal
sys.path.insert(0, '/home/z/.local/lib/python3.13/site-packages')

# ==================== CẤU HÌNH ====================
COOKIE = (
    "_ga=GA1.2.1074447710.1773877026; "
    "memberName=4F0D0D2A316B7A164DB2A42CF7CF85FE; "
    "memberPassword=E71A8D5F227140577E4376EA88F92797; "
    "_gid=GA1.2.1678480358.1780056051; "
    "__zlcmid=1XmoXt5lKumz8jz; "
    "JSESSIONID=node0d8r2bm8321rpqr4gx19uxq1270228023.node0; "
    "clientIp=F31E20F28AD2B3BEEC8A5F858DEE61B8ECDFCF0D9D9092333E4D7D21A246FF94"
)
WS_URL = "wss://gamevh.net/ws/gameServer"

# Thông tin tài khoản (sẽ tự động refresh)
CURRENT_PLAYER_NICKNAME = "nguyen05522"
CURRENT_PLAYER_ID = 65692738
TOKEN = 0  # Will be auto-fetched
GAME_ID = "xiangqi"
PLACE_PATH = "Lobby.xiangqi.0"


def fetch_session_info():
    """Tự động lấy token mới từ trang web"""
    global COOKIE, TOKEN, CURRENT_PLAYER_NICKNAME, CURRENT_PLAYER_ID
    
    cookies = {}
    for item in COOKIE.split("; "):
        key, val = item.split("=", 1)
        cookies[key] = val
    
    session = requests.Session()
    session.cookies.update(cookies)
    
    r = session.get("https://gamevh.net/play/xiangqi/0", headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
    })
    
    patterns = {
        'token': r'token\s*=\s*(-?\d+)',
        'currentPlayerId': r'currentPlayerId\s*=\s*(\d+)',
        'currentPlayerNickName': r'currentPlayerNickName\s*=\s*["\']?([^"\';\n]+)',
    }
    
    for key, pattern in patterns.items():
        m = re.search(pattern, r.text)
        if m:
            if key == 'token':
                TOKEN = int(m.group(1))
            elif key == 'currentPlayerId':
                CURRENT_PLAYER_ID = int(m.group(1))
            elif key == 'currentPlayerNickName':
                CURRENT_PLAYER_NICKNAME = m.group(1).strip()
    
    # Cập nhật JSESSIONID nếu có
    for cookie in session.cookies:
        if cookie.name == 'JSESSIONID':
            COOKIE = re.sub(r'JSESSIONID=[^;]+', f'JSESSIONID={cookie.value}', COOKIE)
    
    print(f"[SESSION] Token={TOKEN}, NickName={CURRENT_PLAYER_NICKNAME}, ID={CURRENT_PLAYER_ID}")
    return True

# Ký tự tượng trưng quân cờ
PIECE_NAMES = {
    'r': 'Xe Đen', 'n': 'Mã Đen', 'b': 'Tượng Đen', 'a': 'Sĩ Đen',
    'k': 'Tướng Đen', 'c': 'Pháo Đen', 'p': 'Tốt Đen',
    'R': 'Xe Đỏ', 'N': 'Mã Đỏ', 'B': 'Tượng Đỏ', 'A': 'Sĩ Đỏ',
    'K': 'Tướng Đỏ', 'C': 'Pháo Đỏ', 'P': 'Tốt Đỏ',
}

# ==================== COMMAND CODES ====================
CMD_PONG = 300
CMD_PING = 301
CMD_LOGIN = 302
CMD_ALERT = 303
CMD_BROADCAST = 311
CMD_SET_CLIENT_MODE = 314
CMD_CONFIG = 315
CMD_CHAT_SEND = 331
CMD_CHAT_MSG = 335
CMD_ENTER_PLACE = 401
CMD_PLAYER_ENTERED = 406
CMD_PLAYER_EXITED = 407
CMD_QUICK_PLAY = 408
CMD_LIST_ZONE_ROOM = 412
CMD_LIST_BET_AMT = 413
CMD_GET_TABLE_DATA = 414
CMD_SLOT_IN_TABLE_CHANGED = 416
CMD_START_MATCH = 417
CMD_GAMEOVER = 418
CMD_ENTER_STATE = 419
CMD_SET_TURN = 420
CMD_SET_READY = 434
CMD_PLAY = 502
CMD_MOVE = 529
CMD_ASK_DRAW = 533
CMD_SURRENDER = 534
CMD_LOGIN_EX = 601

# Map command code -> name
CMD_NAMES = {
    300: "PONG", 301: "PING", 302: "LOGIN", 303: "ALERT",
    311: "BROADCAST", 314: "SET_CLIENT_MODE", 315: "CONFIG",
    331: "CHAT.SEND", 335: "CHAT.MSG",
    401: "ENTER_PLACE", 406: "PLAYER_ENTERED", 407: "PLAYER_EXITED",
    408: "QUICK_PLAY", 412: "LIST_ZONE_ROOM", 413: "LIST_BET_AMT",
    414: "GET_TABLE_DATA", 416: "SLOT_IN_TABLE_CHANGED",
    417: "START_MATCH", 418: "GAMEOVER", 419: "ENTER_STATE",
    420: "SET_TURN", 434: "SET_READY",
    502: "PLAY", 529: "MOVE", 533: "ASK_DRAW", 534: "SURRENDER",
    601: "LOGIN_EX",
}


# ==================== BINARY PROTOCOL - Conn class ====================
class Conn:
    """
    Đọc/giao tiếp binary protocol qua WebSocket.
    Server dùng big-endian (network byte order).
    """
    
    def __init__(self):
        self.offset = 0

    def read_byte(self, buf, o):
        """Đọc 1 byte có dấu (int8) từ buffer tại offset o"""
        val = struct.unpack_from('>b', buf, o)[0]
        return val

    def read_ubyte(self, buf, o):
        """Đọc 1 byte không dấu (uint8) từ buffer tại offset o"""
        val = struct.unpack_from('>B', buf, o)[0]
        return val

    def read_short(self, buf, o):
        """Đọc 2 byte có dấu (int16 big-endian)"""
        val = struct.unpack_from('>h', buf, o)[0]
        return val

    def read_ushort(self, buf, o):
        """Đọc 2 byte không dấu (uint16 big-endian)"""
        val = struct.unpack_from('>H', buf, o)[0]
        return val

    def read_int(self, buf, o):
        """Đọc 4 byte có dấu (int32 big-endian)"""
        val = struct.unpack_from('>i', buf, o)[0]
        return val

    def read_long(self, buf, o):
        """Đọc 8 byte (int64 big-endian)"""
        val = struct.unpack_from('>q', buf, o)[0]
        return val

    def read_ascii(self, buf, o):
        """Đọc chuỗi ASCII: 1 byte length + ASCII bytes"""
        length = self.read_byte(buf, o)
        if length < 0:
            length += 256
        o += 1
        s = buf[o:o+length].decode('ascii', errors='replace')
        return s, o + length

    def read_string(self, buf, o):
        """Đọc chuỗi UTF-16: 2 byte length (số ký tự) + UTF-16BE bytes"""
        char_count = self.read_short(buf, o)
        o += 2
        byte_len = char_count * 2
        s = buf[o:o+byte_len].decode('utf-16-be', errors='replace')
        return s, o + byte_len

    def pack(self, cmd, data=b''):
        """
        Đóng gói lệnh gửi đi.
        cmd: string (ví dụ "LOGIN", "PLAY") hoặc int (command ID)
        data: bytes payload
        Trả về bytearray sẵn sàng gửi qua WebSocket
        """
        result = bytearray()
        if isinstance(cmd, str):
            # String command: writeByte(-length) + ASCII bytes
            cmd_bytes = cmd.encode('ascii')
            result.append((-len(cmd_bytes)) & 0xFF)
            result.extend(cmd_bytes)
        elif isinstance(cmd, int):
            # Numeric command ID: writeShort(cmdId)
            result.extend(struct.pack('>H', cmd))
        result.extend(data)
        return bytes(result)

    def pack_byte(self, value):
        """Đóng gói 1 byte có dấu"""
        return struct.pack('>b', value)

    def pack_ubyte(self, value):
        """Đóng gói 1 byte không dấu"""
        return struct.pack('>B', value)

    def pack_short(self, value):
        """Đóng gói 2 byte có dấu"""
        return struct.pack('>h', value)

    def pack_ushort(self, value):
        """Đóng gói 2 byte không dấu"""
        return struct.pack('>H', value)

    def pack_int(self, value):
        """Đóng gói 4 byte"""
        return struct.pack('>i', value)

    def pack_ascii(self, value):
        """Đóng gói chuỗi ASCII: 1 byte length + ASCII"""
        encoded = value.encode('ascii')[:255]
        return struct.pack('>b', len(encoded)) + encoded

    def pack_string(self, value):
        """Đóng gói chuỗi UTF-16: 2 byte char_count + UTF-16BE"""
        encoded = value.encode('utf-16-be')
        char_count = len(encoded) // 2
        return struct.pack('>h', char_count) + encoded


# ==================== MESSAGE PARSER ====================
class InboundMessage:
    """Phân tích message nhận từ server"""
    
    def __init__(self, data):
        self.data = bytes(data)
        self.offset = 0
        self.command = self._parse_command()

    def _parse_command(self):
        """Parse command header - giống JS InboundMessage"""
        length = self.read_byte()
        if length < 0:
            # String command: -length bytes ASCII
            cmd = self.data[self.offset:self.offset + (-length)].decode('ascii', errors='replace')
            self.offset += (-length)
            return cmd
        else:
            # Numeric command: length << 8 | next_byte
            next_byte = self.data[self.offset] & 0xFF
            self.offset += 1
            cmd_id = (length << 8) | next_byte
            return CMD_NAMES.get(cmd_id, str(cmd_id))

    def read_byte(self):
        val = struct.unpack_from('>b', self.data, self.offset)[0]
        self.offset += 1
        return val

    def read_ubyte(self):
        val = struct.unpack_from('>B', self.data, self.offset)[0]
        self.offset += 1
        return val

    def read_short(self):
        val = struct.unpack_from('>h', self.data, self.offset)[0]
        self.offset += 2
        return val

    def read_ushort(self):
        val = struct.unpack_from('>H', self.data, self.offset)[0]
        self.offset += 2
        return val

    def read_int(self):
        val = struct.unpack_from('>i', self.data, self.offset)[0]
        self.offset += 4
        return val

    def read_long(self):
        val = struct.unpack_from('>q', self.data, self.offset)[0]
        self.offset += 8
        return val

    def read_ascii(self):
        length = self.read_byte()
        if length < 0:
            length += 256
        s = self.data[self.offset:self.offset + length].decode('ascii', errors='replace')
        self.offset += length
        return s

    def read_string(self):
        char_count = self.read_short()
        byte_len = char_count * 2
        s = self.data[self.offset:self.offset + byte_len].decode('utf-16-be', errors='replace')
        self.offset += byte_len
        return s

    def remaining(self):
        return len(self.data) - self.offset


# ==================== XIANQI BOARD TRACKER ====================
class XiangqiBoardTracker:
    """
    Theo dõi bàn cờ từ FEN, chuyển đổi tọa độ giữa game và engine.
    Bàn cờ: 9 cột x 10 hàng, pos = row * 9 + col
    - row 0 = trên cùng (phía Đen), row 9 = dưới cùng (phía Đỏ)
    Engine (Pikafish): file a-i (trái-phải), rank 0-9 (dưới-trên)
    - file a = col 0, rank 0 = row 9 (đáy Đỏ)
    """
    INITIAL_FEN = "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w"
    
    def __init__(self):
        self.fen = self.INITIAL_FEN
        self.move_history = []  # engine format moves
        self.my_slot_id = -1
        self.first_turn_slot_id = 0
        self.is_my_turn = False
        self.is_playing = False
        self.is_red = None  # True nếu chơi Đỏ, False nếu chơi Đen

    def reset(self):
        self.fen = self.INITIAL_FEN
        self.move_history = []
        self.is_my_turn = False
        self.is_playing = False
        self.is_red = None

    @staticmethod
    def pos_to_engine_move(source_pos, target_pos):
        """Chuyển đổi vị trí game (0-89) sang định dạng engine (a0a3)
        
        Game positions: pos = game_row * 9 + game_col
        - game_row 0 = Red's back rank (FEN row 9, engine rank 0)
        - game_row 9 = Black's back rank (FEN row 0, engine rank 9)
        
        Engine: file a-i = col 0-8, rank 0-9
        - rank 0 = FEN row 9 = game row 0 (bottom/Red side)
        - rank 9 = FEN row 0 = game row 9 (top/Black side)
        
        So: engine_rank = game_row, engine_file = game_col
        """
        s_col = source_pos % 9
        s_row = source_pos // 9
        t_col = target_pos % 9
        t_row = target_pos // 9
        
        s_file = chr(ord('a') + s_col)
        s_rank = s_row  # engine_rank = game_row
        t_file = chr(ord('a') + t_col)
        t_rank = t_row  # engine_rank = game_row
        
        return f"{s_file}{s_rank}{t_file}{t_rank}"

    @staticmethod
    def engine_move_to_pos(engine_move):
        """Chuyển đổi engine move (a0a3) sang game positions"""
        s_col = ord(engine_move[0]) - ord('a')
        s_rank = int(engine_move[1])
        t_col = ord(engine_move[2]) - ord('a')
        t_rank = int(engine_move[3])
        
        s_row = s_rank  # game_row = engine_rank
        t_row = t_rank  # game_row = engine_rank
        
        source_pos = s_row * 9 + s_col
        target_pos = t_row * 9 + t_col
        return source_pos, target_pos

    def apply_move(self, source_pos, target_pos):
        """Áp dụng nước đi vào FEN hiện tại"""
        engine_move = self.pos_to_engine_move(source_pos, target_pos)
        self.move_history.append(engine_move)
        # Rebuild FEN from initial + moves (simplified approach)
        # We'll track this using the engine later for validation

    def get_current_fen(self):
        """Trả về FEN hiện tại (ban đầu + moves)"""
        return self.fen, self.move_history

    def set_my_slot(self, slot_id, first_turn_slot_id):
        """Thiết lập slot của mình để xác định màu quân
        
        Trong cờ tướng, Đỏ luôn đi trước → firstTurnSlotId chính là slot chơi Đỏ.
        is_red = True khi mình là slot đi trước (= firstTurnSlotId)
        """
        self.my_slot_id = slot_id
        self.first_turn_slot_id = first_turn_slot_id
        self.is_red = (self.my_slot_id == first_turn_slot_id)


# ==================== PIKAFISH ENGINE WRAPPER ====================
class PikafishBot:
    """Wrapper Pikafish engine cho bot chơi cờ tướng"""
    
    def __init__(self, depth=15):
        self.conn = Conn()
        self.board = XiangqiBoardTracker()
        self.engine = None
        self.depth = depth
        self.ws = None
        self.connected = False
        self.logged_in = False
        self.in_game = False
        self.keep_alive_timer = None
        self._init_engine()

    def _init_engine(self):
        """Khởi tạo Pikafish engine (chỉ dùng pikafish_terminal - binary bị segfault)"""
        try:
            from pikafish_terminal.engine import PikafishEngine
            from pikafish_terminal.difficulty import create_custom_difficulty
            
            difficulty = create_custom_difficulty(depth=self.depth)
            self.engine = PikafishEngine(difficulty=difficulty)
            self.engine.new_game()
            self._engine_mode = 'pikafish_terminal'
            print(f"[ENGINE] Pikafish engine (terminal) khởi tạo thành công (depth={self.depth})")
        except Exception as e:
            print(f"[ENGINE] ❌ Pikafish-terminal không khả dụng: {e}")
            self.engine = None
            self._engine_mode = None

    def _fsf_cmd(self, text):
        proc = getattr(self, '_engine_proc', None)
        if proc:
            proc.stdin.write(text + "\n")
            proc.stdin.flush()

    def _fsf_wait_for(self, token, timeout=10):
        proc = getattr(self, '_engine_proc', None)
        start = time.time()
        while proc:
            line = proc.stdout.readline().strip()
            if token in line:
                return line
            if time.time() - start > timeout:
                raise RuntimeError(f"Timeout waiting for '{token}'")

    def get_best_move(self, fen, moves):
        """Lấy nước đi tốt nhất từ engine"""
        try:
            mode = getattr(self, '_engine_mode', None)
            
            if mode == 'pikafish_terminal' and self.engine is not None:
                # PikafishTerminal engine
                move = self.engine.best_move(fen, moves)
                return move
            elif mode == 'binary':
                # Pikafish binary trực tiếp
                pos_cmd = f"position fen {fen}"
                if moves:
                    pos_cmd += " moves " + " ".join(moves)
                self._fsf_cmd(pos_cmd)
                self._fsf_cmd(f"go depth {self.depth}")
                
                start = time.time()
                proc = getattr(self, '_engine_proc', None)
                while proc:
                    line = proc.stdout.readline().strip()
                    if line.startswith("bestmove"):
                        move = line.split()[1]
                        return move
                    if time.time() - start > 30:
                        print("[ENGINE] Timeout!")
                        return None
            else:
                print("[ENGINE] Không có engine nào khả dụng!")
                return None
        except Exception as e:
            print(f"[ENGINE] Lỗi get_best_move: {e}")
            import traceback
            traceback.print_exc()
            return None

    # ==================== WEBSOCKET CONNECTION ====================
    
    def connect(self):
        """Kết nối WebSocket đến game server"""
        import websocket
        websocket.enableTrace(False)
        
        self.ws = websocket.WebSocketApp(
            WS_URL,
            cookie=COOKIE,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
            header={"Origin": "https://gamevh.net"}
        )
        
        # Chạy trong thread riêng
        self.ws_thread = threading.Thread(target=self._run_ws, daemon=True)
        self.ws_thread.start()
        
        # Đợi kết nối
        for _ in range(50):
            if self.connected:
                break
            time.sleep(0.2)
        
        return self.connected

    def _run_ws(self):
        try:
            self.ws.run_forever(ping_interval=25, ping_timeout=10)
        except Exception as e:
            print(f"[WS] Lỗi run_forever: {e}")

    def _on_open(self, ws):
        print("[WS] ✅ Kết nối WebSocket thành công!")
        self.connected = True
        # Gửi LOGIN ngay sau khi kết nối
        self._send_login()

    def _on_message(self, ws, message):
        """Xử lý message nhận từ server"""
        if isinstance(message, bytes):
            self._handle_binary_message(message)
        else:
            print(f"[WS] Nhận text message: {message[:200]}")

    def _on_error(self, ws, error):
        print(f"[WS] ❌ Lỗi: {error}")

    def _on_close(self, ws, close_status_code, close_msg):
        print(f"[WS] 🔌 Đóng kết nối: code={close_status_code} msg={close_msg}")
        self.connected = False

    # ==================== SEND MESSAGES ====================
    
    def send_message(self, cmd, data=b''):
        """Gửi binary message qua WebSocket"""
        if self.ws and self.connected:
            try:
                msg = self.conn.pack(cmd, data)
                self.ws.send(msg, opcode=0x2)  # binary frame
                cmd_name = cmd if isinstance(cmd, str) else CMD_NAMES.get(cmd, str(cmd))
                print(f"[SEND] {cmd_name} ({len(msg)} bytes)")
            except Exception as e:
                print(f"[SEND] Lỗi: {e}")

    def _send_login(self):
        """Gửi lệnh LOGIN"""
        data = bytearray()
        # writeAscii(nickname)
        data.extend(self.conn.pack_ascii(CURRENT_PLAYER_NICKNAME))
        # writeInt(token)
        data.extend(self.conn.pack_int(TOKEN))
        # writeAscii(version)
        data.extend(self.conn.pack_ascii("5.0.2"))
        # writeAscii(cookie) - loginCookie
        data.extend(self.conn.pack_ascii(""))
        # writeAscii(gameId)
        data.extend(self.conn.pack_ascii(GAME_ID))
        # writeByte(1)
        data.extend(self.conn.pack_byte(1))
        
        self.send_message("LOGIN", bytes(data))
        print(f"[LOGIN] Gửi login: nickname={CURRENT_PLAYER_NICKNAME}, token={TOKEN}")

    def send_enter_place(self, path=PLACE_PATH, mode=1):
        """Gửi lệnh ENTER_PLACE"""
        data = bytearray()
        # writeAscii(path)
        data.extend(self.conn.pack_ascii(path))
        # writeString(password)
        data.extend(self.conn.pack_string(""))
        # writeByte(mode) - 1=PLAY, 0=VIEW
        data.extend(self.conn.pack_byte(mode))
        
        self.send_message("ENTER_PLACE", bytes(data))
        print(f"[ENTER_PLACE] path={path}, mode={mode}")

    def send_quick_play(self, room_id="", bet_amt_id=-1):
        """Gửi lệnh QUICK_PLAY"""
        data = bytearray()
        # writeAscii(roomId)
        data.extend(self.conn.pack_ascii(room_id))
        # writeByte(betAmtId)
        data.extend(self.conn.pack_byte(bet_amt_id))
        
        self.send_message("QUICK_PLAY", bytes(data))
        print(f"[QUICK_PLAY] roomId={room_id}, betAmtId={bet_amt_id}")

    def send_play(self, source_pos, target_pos):
        """Gửi nước đi"""
        data = bytearray()
        # writeByte(sourcePosition)
        data.extend(self.conn.pack_byte(source_pos))
        # writeByte(targetPosition)
        data.extend(self.conn.pack_byte(target_pos))
        
        self.send_message("PLAY", bytes(data))

    def send_ping(self):
        """Gửi PING giữ kết nối"""
        self.send_message("PING")

    def send_set_ready(self):
        """Gửi SET_READY"""
        self.send_message("SET_READY")

    def send_surrender(self):
        """Gửi SURRENDER"""
        self.send_message("SURRENDER")

    # ==================== HANDLE INCOMING MESSAGES ====================
    
    def _handle_binary_message(self, data):
        """Phân tích và xử lý binary message"""
        try:
            msg = InboundMessage(data)
            cmd = msg.command
            
            # Hiển thị log
            hex_preview = data[:20].hex()
            print(f"[RECV] {cmd} ({len(data)} bytes) hex={hex_preview}...")
            
            # Xử lý theo loại lệnh
            if cmd == "PING":
                self._handle_ping()
            elif cmd == "PONG":
                pass  # PONG response, nothing to do
            elif cmd == "LOGIN":
                self._handle_login_response(msg)
            elif cmd == "ENTER_PLACE":
                self._handle_enter_place_response(msg)
            elif cmd == "QUICK_PLAY":
                self._handle_quick_play_response(msg)
            elif cmd == "SLOT_IN_TABLE_CHANGED":
                self._handle_slot_changed(msg)
            elif cmd == "START_MATCH":
                self._handle_start_match(msg)
            elif cmd == "PLAY" or cmd == "502":
                self._handle_play_response(msg)
            elif cmd == "MOVE":
                self._handle_move(msg)
            elif cmd == "SET_TURN":
                self._handle_set_turn(msg)
            elif cmd == "GAMEOVER":
                self._handle_gameover(msg)
            elif cmd == "ENTER_STATE":
                self._handle_enter_state(msg)
            elif cmd == "PLAYER_ENTERED":
                self._handle_player_entered(msg)
            elif cmd == "PLAYER_EXITED":
                self._handle_player_exited(msg)
            elif cmd == "BROADCAST":
                self._handle_broadcast(msg)
            elif cmd == "ALERT":
                self._handle_alert(msg)
            elif cmd == "CONFIG":
                self._handle_config(msg)
            elif cmd == "SET_CLIENT_MODE":
                self._handle_set_client_mode(msg)
            else:
                print(f"[RECV] Unhandled command: {cmd}")
                
        except Exception as e:
            print(f"[RECV] Lỗi xử lý message: {e}")
            import traceback
            traceback.print_exc()

    def _handle_ping(self):
        """Phản hồi PING -> gửi PONG"""
        self.send_message("PONG")

    def _handle_login_response(self, msg):
        """Xử lý phản hồi LOGIN"""
        status = msg.read_byte()
        if status != 0:
            error_msg = ""
            try:
                error_msg = msg.read_string()
            except:
                pass
            print(f"[LOGIN] ❌ Đăng nhập thất bại: status={status}, msg={error_msg}")
            return
        
        print(f"[LOGIN] ✅ Đăng nhập thành công!")
        self.logged_in = True
        
        # Đọc path
        try:
            path = msg.read_string()
            print(f"[LOGIN] Path: {path}")
            
            if path == 'REFRESH':
                print("[LOGIN] Server yêu cầu refresh! Re-fetching token...")
                # Re-fetch token and retry login
                fetch_session_info()
                time.sleep(1)
                self._send_login()
                return
            
            # Đọc loginCookie
            try:
                cookie = msg.read_ascii()
                if cookie:
                    print(f"[LOGIN] Cookie: {cookie}")
            except:
                pass
            
            # Tự động vào phòng
            time.sleep(1)
            self.send_enter_place()
        except Exception as e:
            print(f"[LOGIN] Lỗi đọc response: {e}")

    def _handle_enter_place_response(self, msg):
        """Xử lý phản hồi ENTER_PLACE"""
        status = msg.read_byte()
        if status != 0:
            try:
                error_msg = msg.read_string()
            except:
                error_msg = "Unknown error"
            print(f"[ENTER_PLACE] ❌ Lỗi: {error_msg}")
            return
        
        print(f"[ENTER_PLACE] ✅ Vào phòng thành công!")
        
        try:
            currency = msg.read_byte()
            entrance_rate = msg.read_short() / 10.0
            print(f"[ENTER_PLACE] Currency: {currency}, Entrance rate: {entrance_rate}")
        except:
            pass
        
        # Chỉ gửi QUICK_PLAY nếu chưa ở trong bàn
        if not self.in_game:
            time.sleep(1.5)
            self.send_quick_play()

    def _handle_quick_play_response(self, msg):
        """Xử lý phản hồi QUICK_PLAY"""
        status = msg.read_byte()
        if status != 0:
            try:
                error_msg = msg.read_string()
            except:
                error_msg = "Unknown"
            print(f"[QUICK_PLAY] ❌ Lỗi: {error_msg}")
            return
        
        print(f"[QUICK_PLAY] ✅ Tìm bàn thành công!")
        self.in_game = True
        
        try:
            table_path = msg.read_ascii()
            table_name = msg.read_string()
            print(f"[QUICK_PLAY] Table: {table_name} ({table_path})")
            
            # Đọc table args
            count = msg.read_byte()
            table_args = {}
            for i in range(count):
                attr_name = msg.read_ascii()
                attr_value = msg.read_string()
                table_args[attr_name] = attr_value
                print(f"  {attr_name} = {attr_value}")
            
            table_type = msg.read_byte()
            bet_amt_id = msg.read_byte()
            print(f"  tableType={table_type}, betAmtId={bet_amt_id}")
            
            # Vào bàn
            time.sleep(1)
            self.send_enter_place(path=table_path, mode=1)
        except Exception as e:
            print(f"[QUICK_PLAY] Lỗi đọc response: {e}")

    def _handle_slot_changed(self, msg):
        """Xử lý SLOT_IN_TABLE_CHANGED - người chơi vào/rời bàn"""
        try:
            full_name = msg.read_string()
            slot_id = msg.read_byte()
            chip_balance = msg.read_long()
            score = msg.read_long()
            level = msg.read_byte()
            avatar_id = msg.read_short()
            avatar = msg.read_ascii()
            tag_id = msg.read_byte()
            is_owner = msg.read_byte() == 1
            player_id = msg.read_long()
            star_balance = msg.read_long()
            
            is_me = (player_id == CURRENT_PLAYER_ID)
            color = "🟢" if is_me else "👤"
            print(f"[SLOT] {color} {full_name} (slot={slot_id}, chips={chip_balance}, "
                  f"playerId={player_id}, owner={is_owner})")
            
            if is_me:
                self.board.my_slot_id = slot_id
                print(f"[SLOT] Tôi ở slot {slot_id}")
        except Exception as e:
            print(f"[SLOT] Lỗi đọc: {e}")

    def _handle_start_match(self, msg):
        """Xử lý START_MATCH - ván đấu bắt đầu"""
        print(f"[GAME] 🎮 Ván đấu bắt đầu!")
        self.board.reset()
        self.board.is_playing = True
        self.in_game = True
        
        try:
            # 1. fillPlayerMatchPoint: count + (slotId + point) * count
            player_count = msg.read_byte()
            for i in range(player_count):
                slot_id = msg.read_byte()
                point = msg.read_int()
            
            # 2. fillBoardData (gọi từ onStartMatch)
            #    Board data: piece_count + (sid + face + pos + open) * count
            piece_count = msg.read_byte()
            print(f"[GAME] Số quân cờ: {piece_count}")
            
            board_pieces = []
            for i in range(piece_count):
                encoded_sid = msg.read_byte()
                encoded_face = msg.read_byte()
                position = msg.read_byte()
                is_open = msg.read_byte()
                sid = self._decode_piece_id(encoded_sid)
                face = self._decode_piece_id(encoded_face)
                board_pieces.append((sid, face, position, is_open))
                if i < 5 or position >= 0:
                    row = position // 9 if position >= 0 else -1
                    col = position % 9 if position >= 0 else -1
                    print(f"  [{i}] sid={sid} face={face} pos={position} (r{row}c{col}) open={is_open}")
            
            allow_pass_river = msg.read_byte()
            
            # Mystery pieces
            mystery_count = msg.read_byte()
            for i in range(mystery_count):
                mystery_piece = msg.read_byte()
            
            # Last move
            last_source = msg.read_byte()
            last_target = msg.read_byte()
            
            # 3. onStartMatch: firstTurnSlotId + mySlotId
            first_turn_slot_id = msg.read_byte()
            my_slot_id = msg.read_byte()
            
            # Debug: hiển thị raw data còn lại
            print(f"[GAME] DEBUG firstTurnSlotId={first_turn_slot_id}, mySlotId={my_slot_id}, remaining={msg.remaining()}")
            if msg.remaining() > 0:
                print(f"[GAME] DEBUG raw remaining: {msg.data[msg.offset:msg.offset+20].hex()}")
            
            # Fallback: nếu my_slot_id chưa xác định từ SLOT_CHANGED, dùng START_MATCH
            # my_slot_id = -1 nghĩa là byte 0xFF (unsigned) → cần đọc lại
            if my_slot_id < 0:
                # Thử dùng slot đã biết từ SLOT_CHANGED
                if self.board.my_slot_id >= 0:
                    print(f"[GAME] ⚠️ mySlotId từ START_MATCH = {my_slot_id}, dùng slot từ SLOT_CHANGED = {self.board.my_slot_id}")
                    my_slot_id = self.board.my_slot_id
                else:
                    # Đọc unsigned
                    print(f"[GAME] ⚠️ mySlotId không xác định! Dùng firstTurnSlotId={first_turn_slot_id} làm slot mặc định")
                    my_slot_id = first_turn_slot_id
            
            self.board.set_my_slot(my_slot_id, first_turn_slot_id)
            
            # Xây dựng FEN từ board data
            fen = self._build_fen_from_pieces(board_pieces, first_turn_slot_id)
            self.board.fen = fen
            self.board.move_history = []
            
            color_name = "ĐỎ (Red)" if self.board.is_red else "ĐEN (Black)"
            print(f"[GAME] Tôi slot {my_slot_id}, first={first_turn_slot_id} → {color_name}")
            print(f"[GAME] FEN: {fen}")
            
            # Kiểm tra có phải đi trước không
            # Đỏ luôn đi trước trong cờ tướng
            # firstTurnSlotId = slot đi trước
            my_turn_first = (my_slot_id == first_turn_slot_id)
            if my_turn_first:
                self.board.is_my_turn = True
                print(f"[GAME] 🎯 Đi trước! Đang tính nước đi...")
                self._make_auto_move()
            else:
                self.board.is_my_turn = False
                print(f"[GAME] Đối thủ đi trước. Chờ...")
                
        except Exception as e:
            print(f"[GAME] Lỗi đọc START_MATCH: {e}")
            import traceback
            traceback.print_exc()

    def _build_fen_from_pieces(self, pieces, first_turn_slot_id):
        """Xây dựng FEN từ danh sách quân cờ
        
        Lưu ý: Hệ thống tọa độ của game:
        - Row 0 = hàng sau của ĐỎ (trên màn hình khi redInBottom=false)
        - Row 9 = hàng sau của ĐEN (dưới màn hình)
        
        Standard FEN:
        - Row 0 = hàng sau của ĐEN (trên bàn cờ)
        - Row 9 = hàng sau của ĐỎ (dưới bàn cờ)
        
        => Cần flip: fen_row = 9 - game_row
        """
        # Bàn cờ 9x10, tạo mảng trống (theo FEN orientation)
        board = [['.' for _ in range(9)] for _ in range(10)]
        
        for sid, face, position, is_open in pieces:
            if position < 0 or position >= 90:
                continue
            game_row = position // 9
            col = position % 9
            
            # Flip row: game row 0 -> FEN row 9
            fen_row = 9 - game_row
            
            # Xác định màu và loại quân từ face
            color = face[0]  # 'r' or 'b'
            piece_type = int(face[1]) if len(face) > 1 else 0
            
            # Map type -> FEN character (STANDARD notation: n=knight, b=elephant)
            type_to_fen = {1: 'k', 2: 'a', 3: 'b', 4: 'r', 5: 'c', 6: 'n', 7: 'p'}
            fen_char = type_to_fen.get(piece_type, '?')
            
            # Pikafish FEN convention (VERIFIED):
            # 'w' side = UPPERCASE pieces (Red/White, goes first)
            # 'b' side = lowercase pieces (Black)
            # Red (color='r') → UPPERCASE, Black (color='b') → lowercase
            if color == 'r':
                fen_char = fen_char.upper()
            
            board[fen_row][col] = fen_char
        
        # Xây dựng FEN string
        fen_rows = []
        for row in board:
            fen_row = ""
            empty = 0
            for cell in row:
                if cell == '.':
                    empty += 1
                else:
                    if empty > 0:
                        fen_row += str(empty)
                        empty = 0
                    fen_row += cell
            if empty > 0:
                fen_row += str(empty)
            fen_rows.append(fen_row)
        
        # firstTurnSlotId = slot đi trước = Đỏ (Red = white in FEN)
        side = 'w'  # Đỏ = white, luôn đi trước
        return '/'.join(fen_rows) + ' ' + side

    def _handle_move(self, msg):
        """Xử lý MOVE - một nước đi đã được thực hiện"""
        try:
            source_pos = msg.read_byte()
            target_pos = msg.read_byte()
            
            engine_move = self.board.pos_to_engine_move(source_pos, target_pos)
            
            # Thêm vào lịch sử nước đi (không duplicate)
            if not self.board.move_history or self.board.move_history[-1] != engine_move:
                self.board.move_history.append(engine_move)
            
            print(f"[MOVE] 🏃 Nước đi: pos({source_pos}->{target_pos}) = engine({engine_move})")
            print(f"[MOVE] Lịch sử: {' '.join(self.board.move_history[-6:])}")
            
            # Đọc additional piece data (mystery xiangqi)
            try:
                count = msg.read_byte()
                for i in range(count):
                    sid_encoded = msg.read_byte()
                    face_encoded = msg.read_byte()
            except:
                pass
            
            # Kiểm tra có phải lượt mình không (dựa trên SET_TURN)
            # MOVE có thể là nước đi của mình (echo) hoặc đối thủ
            # Đếm số nước đi để xác định lượt
            # Nếu số nước đi chẵn -> lượt Đỏ, lẻ -> lượt Đen
            is_red_turn = (len(self.board.move_history) % 2 == 0)
            is_my_turn_now = (is_red_turn == self.board.is_red)
            
            if is_my_turn_now and self.board.is_playing:
                self.board.is_my_turn = True
                print(f"[MOVE] 🎯 Đến lượt mình! Đang tính nước đi...")
                time.sleep(0.5)
                self._make_auto_move()
            else:
                self.board.is_my_turn = False
                print(f"[MOVE] Chờ đối thủ...")
            
        except Exception as e:
            print(f"[MOVE] Lỗi xử lý: {e}")
            import traceback
            traceback.print_exc()

    def _handle_play_response(self, msg):
        """Xử lý phản hồi PLAY - kết quả nước đi"""
        try:
            status = msg.read_byte()
            if status != 0:
                error_msg = ""
                try:
                    error_msg = msg.read_string()
                except:
                    pass
                print(f"[PLAY] ❌ Nước đi không hợp lệ: status={status}, msg={error_msg}")
                # Xóa nước đi cuối cùng khỏi lịch sử
                if self.board.move_history:
                    removed = self.board.move_history.pop()
                    print(f"[PLAY] Đã xóa nước đi: {removed}")
                self.board.is_my_turn = True
            else:
                print(f"[PLAY] ✅ Nước đi được chấp nhận")
        except Exception as e:
            print(f"[PLAY] Lỗi đọc response: {e}")

    def _handle_set_turn(self, msg):
        """Xử lý SET_TURN"""
        try:
            slot_id = msg.read_byte()
            turn_timeout = msg.read_short()
            
            if slot_id == -2:
                print(f"[TURN] Countdown: {turn_timeout}")
                return
            
            player_remain = msg.read_short()
            is_my_turn = (slot_id == self.board.my_slot_id)
            self.board.is_my_turn = is_my_turn
            
            turn_str = "LƯỢT MÌNH" if is_my_turn else f"Lượt đối thủ (slot={slot_id})"
            print(f"[TURN] ⏱️ {turn_str}, timeout={turn_timeout}s, remain={player_remain}s")
            
        except Exception as e:
            print(f"[TURN] Lỗi đọc: {e}")

    def _handle_gameover(self, msg):
        """Xử lý GAMEOVER"""
        print(f"[GAME] 🏁 Ván đấu kết thúc!")
        self.board.is_playing = False
        self.in_game = False
        self.board.is_my_turn = False
        
        try:
            count = msg.read_byte()
            for i in range(count):
                slot_id = msg.read_byte()
                grade = msg.read_byte()
                earn_value = msg.read_long()
                is_me = (slot_id == self.board.my_slot_id)
                result = "🏆 THẮNG" if grade == 1 else "💀 THUA" if grade == 2 else "🤝 HÒA"
                if is_me:
                    print(f"[GAME] Kết quả: {result} (earn={earn_value})")
            
            match_result = msg.read_string()
            print(f"[GAME] Chi tiết: {match_result}")
        except Exception as e:
            print(f"[GAME] Lỗi đọc gameover: {e}")
        
        # Chơi ván mới sau 5 giây
        print(f"[GAME] Sẽ tìm ván mới sau 5 giây...")
        time.sleep(5)
        self.send_quick_play()

    def _handle_enter_state(self, msg):
        """Xử lý ENTER_STATE"""
        try:
            state_id = msg.read_byte()
            print(f"[STATE] Trạng thái: {state_id}")
        except:
            pass

    def _handle_player_entered(self, msg):
        try:
            name = msg.read_string()
            print(f"[PLAYER] 👋 {name} vào bàn")
        except:
            pass

    def _handle_player_exited(self, msg):
        try:
            name = msg.read_string()
            print(f"[PLAYER] 👋 {name} rời bàn")
        except:
            pass

    def _handle_broadcast(self, msg):
        try:
            content = msg.read_string()
            print(f"[BROADCAST] 📢 {content}")
        except:
            pass

    def _handle_alert(self, msg):
        try:
            status = msg.read_byte()
            content = msg.read_string()
            print(f"[ALERT] ⚠️ status={status}: {content}")
        except:
            pass

    def _handle_config(self, msg):
        try:
            count = msg.read_byte()
            for i in range(count):
                key = msg.read_ascii()
                value = msg.read_string()
                print(f"[CONFIG] {key} = {value}")
        except:
            pass

    def _handle_set_client_mode(self, msg):
        try:
            mode = msg.read_byte()
            print(f"[MODE] Client mode: {mode}")
        except:
            pass

    # ==================== AUTO PLAY ====================
    
    def _make_auto_move(self):
        """Tính nước đi tốt nhất và gửi"""
        if not self.board.is_my_turn or not self.board.is_playing:
            return
        
        fen, moves = self.board.get_current_fen()
        
        print(f"[BOT] 🧠 Đang tính nước đi...")
        print(f"[BOT] FEN: {fen}")
        if moves:
            print(f"[BOT] Moves: {' '.join(moves[-6:])}")
        
        best_move = self.get_best_move(fen, moves)
        
        if best_move and best_move != "(none)" and best_move != "0000":
            try:
                source_pos, target_pos = self.board.engine_move_to_pos(best_move)
                print(f"[BOT] ✅ Nước đi tốt nhất: {best_move} -> pos({source_pos}->{target_pos})")
                
                # Thêm vào lịch sử trước khi gửi
                self.board.move_history.append(best_move)
                self.board.is_my_turn = False
                
                # Gửi nước đi
                time.sleep(0.3)  # Delay nhỏ để tự nhiên
                self.send_play(source_pos, target_pos)
                
            except Exception as e:
                print(f"[BOT] Lỗi chuyển đổi nước đi: {e}")
        else:
            print(f"[BOT] ❌ Không tìm được nước đi! (best_move={best_move})")

    def _decode_piece_id(self, encoded_id):
        """Giải mã encoded piece ID (như JS decodePieceId)"""
        color = 'r'
        if encoded_id < 0:
            encoded_id = -encoded_id
            color = 'b'
        piece_type = encoded_id >> 3
        suffix = encoded_id & 7
        if suffix == 0:
            suffix = ''
        return f"{color}{piece_type}{suffix}"

    # ==================== KEEP ALIVE ====================
    
    def start_keep_alive(self):
        """Bắt đầu gửi PING định kỳ 7s - đảm bảo WebSocket không bị timeout"""
        def keep_alive_loop():
            while self.connected:
                time.sleep(7)
                if self.connected:
                    try:
                        self.send_ping()
                    except Exception as e:
                        print(f"[KEEP-ALIVE] Lỗi gửi PING: {e}")
        
        self.keep_alive_thread = threading.Thread(target=keep_alive_loop, daemon=True)
        self.keep_alive_thread.start()
        print("[KEEP-ALIVE] Bắt đầu gửi PING mỗi 7 giây")

    # ==================== MAIN LOOP ====================
    
    def run(self):
        """Chạy bot chính với auto-reconnect"""
        print("=" * 60)
        print("  XIANGQI BOT - gamevh.net")
        print("  Engine: Pikafish")
        print("  Auto-reconnect: BẬT")
        print("=" * 60)
        
        reconnect_count = 0
        max_reconnects = 999  # Gần như vô hạn
        
        while reconnect_count < max_reconnects:
            try:
                # Lấy token mới
                print(f"\n[0] Lấy token mới từ server... (lần kết nối thứ {reconnect_count + 1})")
                fetch_session_info()
                
                # Reset trạng thái
                self.logged_in = False
                self.in_game = False
                self.board.reset()
                
                print("\n[1] Đang kết nối WebSocket...")
                if not self.connect():
                    print("❌ Không thể kết nối WebSocket! Thử lại sau 10s...")
                    time.sleep(10)
                    reconnect_count += 1
                    continue
                
                print("✅ Đã kết nối WebSocket!")
                
                # Bắt đầu keep-alive
                self.start_keep_alive()
                
                # Chờ login
                print("\n[2] Đang đăng nhập...")
                for _ in range(50):
                    if self.logged_in:
                        break
                    time.sleep(0.2)
                
                if not self.logged_in:
                    print("❌ Đăng nhập thất bại! Thử lại sau 10s...")
                    time.sleep(10)
                    reconnect_count += 1
                    continue
                
                print("✅ Đã đăng nhập!")
                
                # Chờ vào game
                print("\n[3] Đang tìm bàn chơi...")
                for _ in range(300):  # Chờ tối đa 60 giây
                    if self.in_game and self.board.is_playing:
                        break
                    time.sleep(0.2)
                
                if not self.in_game:
                    print("⚠️ Chưa vào bàn chơi, tiếp tục chờ...")
                
                # Main loop - chờ mất kết nối
                print("\n[4] Bot đang chạy tự động. Auto-reconnect khi mất kết nối.\n")
                while self.connected:
                    time.sleep(1)
                
                # Nếu đến đây = mất kết nối
                print(f"\n[RECONNECT] Mất kết nối! Đang kết nối lại... (lần {reconnect_count + 1})")
                reconnect_count += 1
                time.sleep(5)  # Đợi 5s trước khi reconnect
                
            except KeyboardInterrupt:
                print("\n[BOT] Dừng bot...")
                break
            except Exception as e:
                print(f"\n[BOT] Lỗi không xác định: {e}")
                reconnect_count += 1
                time.sleep(10)
        
        return True

    def cleanup(self):
        """Dọn dẹp"""
        if self.engine:
            try:
                self.engine.quit()
            except:
                pass
        proc = getattr(self, '_engine_proc', None)
        if proc:
            try:
                proc.stdin.write("quit\n")
                proc.stdin.flush()
                proc.wait(timeout=3)
            except:
                try:
                    proc.terminate()
                except:
                    pass
        if self.ws:
            try:
                self.ws.close()
            except:
                pass


# ==================== CHẠY BOT ====================
if __name__ == "__main__":
    bot = PikafishBot(depth=15)
    
    def signal_handler(sig, frame):
        print("\n[SIGNAL] Nhận tín hiệu dừng...")
        bot.cleanup()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        success = bot.run()
        if not success:
            print("\n❌ Bot chạy thất bại!")
            sys.exit(1)
    except Exception as e:
        print(f"\n❌ Lỗi: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        bot.cleanup()
