#!/usr/bin/env python3
"""
Xiangqi Bot - gamevh.net (CREATE_TABLE Edition)
Cơ chế nâng cao: Tự động refresh và đọc lại FEN trực tiếp từ Server khi đối thủ BỎ LƯỢT.
Tối ưu hóa: Depth 15, không hash, không threads, chạy mượt trên GitHub Actions.
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

# Fix import path cho pikafish_terminal
_venv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'venv', 'lib')
for _py_ver in ['python3.12', 'python3.13', 'python3.11']:
    _candidate = os.path.join(_venv_path, _py_ver, 'site-packages')
    if os.path.isdir(_candidate):
        sys.path.insert(0, _candidate)
        break

# ==================== CẤU HÌNH ====================
COOKIE = os.environ.get(
    'GAMEVH_COOKIE',
    "_ga=GA1.2.1268277570.1781579079; "
    "memberName=4F0D0D2A316B7A1688ED292DEE05CCD9; "
    "memberPassword=E71A8D5F227140577E4376EA88F92797; "
    "_gid=GA1.2.1353156256.1781717134; "
    "JSESSIONID=node011fjfobq8490t1dmcevkry1fct23088635.node0; "
    "clientIp=F31E20F28AD2B3BEE29105588C4DC2296D05851A73515915FD86406FA485B8B4; "
    "_gat=1"
)
WS_URL = "wss://gamevh.net/ws/gameServer"

CURRENT_PLAYER_NICKNAME = os.environ.get('GAMEVH_NICKNAME', 'nguyen05522')
CURRENT_PLAYER_ID = int(os.environ.get('GAMEVH_PLAYER_ID', '65692738'))
TOKEN = 0 
GAME_ID = os.environ.get('GAMEVH_GAME_ID', 'xiangqi')
PLACE_PATH = os.environ.get('GAMEVH_PLACE_PATH', 'Lobby.xiangqi.0')

BOT_DEPTH = int(os.environ.get('BOT_DEPTH', '15'))

# ===== CẤU HÌNH TẠO BÀN =====
BOT_BET_AMT_ID = int(os.environ.get('BOT_BET_AMT_ID', '5'))
BOT_USE_CREATE_TABLE = os.environ.get('BOT_USE_CREATE_TABLE', 'true').lower() == 'true'

BOT_MATCH_DURATION = os.environ.get('BOT_MATCH_DURATION', '5')    
BOT_TURN_DURATION = os.environ.get('BOT_TURN_DURATION', '30')        
BOT_ACC_DURATION = os.environ.get('BOT_ACC_DURATION', '0')           
BOT_BLOCK_SOFTWARE = os.environ.get('BOT_BLOCK_SOFTWARE', '0')     

def fetch_session_info():
    global COOKIE, TOKEN, CURRENT_PLAYER_NICKNAME, CURRENT_PLAYER_ID
    try:
        cookies = {}
        for item in COOKIE.split("; "):
            if not item.strip(): continue
            key, val = item.split("=", 1)
            cookies[key.strip()] = val.strip()

        session = requests.Session()
        session.cookies.update(cookies)

        r = session.get("https://gamevh.net/play/xiangqi/0", headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }, timeout=5)

        patterns = {
            'token': r'token\s*=\s*(-?\d+)',
            'currentPlayerId': r'currentPlayerId\s*=\s*(\d+)',
            'currentPlayerNickName': r'currentPlayerNickName\s*=\s*["\']?([^"\';\n]+)',
        }

        for key, pattern in patterns.items():
            m = re.search(pattern, r.text)
            if m:
                if key == 'token': TOKEN = int(m.group(1))
                elif key == 'currentPlayerId': CURRENT_PLAYER_ID = int(m.group(1))
                elif key == 'currentPlayerNickName': CURRENT_PLAYER_NICKNAME = m.group(1).strip()

        for cookie in session.cookies:
            if cookie.name == 'JSESSIONID':
                COOKIE = re.sub(r'JSESSIONID=[^;]+', f'JSESSIONID={cookie.value}', COOKIE)

        print(f"[SESSION] Token: {TOKEN} | NickName: {CURRENT_PLAYER_NICKNAME} | PlayerID: {CURRENT_PLAYER_ID}")
        return True
    except Exception as e:
        print(f"[SESSION] Lỗi cập nhật session: {e}")
        return False

# ==================== MÃ LỆNH PROTOCOL ====================
CMD_NAMES = {
    300: "PONG", 301: "PING", 302: "LOGIN", 303: "ALERT",
    311: "BROADCAST", 314: "SET_CLIENT_MODE", 315: "CONFIG",
    331: "CHAT.SEND", 335: "CHAT.MSG",
    401: "ENTER_PLACE", 405: "CREATE_RULE", 406: "PLAYER_ENTERED", 407: "PLAYER_EXITED",
    408: "QUICK_PLAY", 412: "LIST_ZONE_ROOM", 413: "LIST_BET_AMT",
    414: "GET_TABLE_DATA", 416: "SLOT_IN_TABLE_CHANGED",
    417: "START_MATCH", 418: "GAMEOVER", 419: "ENTER_STATE",
    420: "SET_TURN", 434: "SET_READY",
    502: "PLAY", 529: "MOVE", 533: "ASK_DRAW", 534: "SURRENDER",
    601: "LOGIN_EX",
}

class Conn:
    def pack(self, cmd, data=b''):
        result = bytearray()
        if isinstance(cmd, str):
            cmd_bytes = cmd.encode('ascii')
            result.append((-len(cmd_bytes)) & 0xFF)
            result.extend(cmd_bytes)
        elif isinstance(cmd, int):
            result.extend(struct.pack('>H', cmd))
        result.extend(data)
        return bytes(result)

    def pack_byte(self, value): return struct.pack('>b', value)
    def pack_int(self, value): return struct.pack('>i', value)
    def pack_ascii(self, value):
        encoded = value.encode('ascii')[:255]
        return struct.pack('>b', len(encoded)) + encoded
    def pack_string(self, value):
        encoded = value.encode('utf-16-be')
        return struct.pack('>h', len(encoded) // 2) + encoded

class InboundMessage:
    def __init__(self, data):
        self.data = bytes(data)
        self.offset = 0
        self.command = self._parse_command()

    def _parse_command(self):
        length = self.read_byte()
        if length < 0:
            cmd = self.data[self.offset:self.offset + (-length)].decode('ascii', errors='replace')
            self.offset += (-length)
            return cmd
        else:
            next_byte = self.data[self.offset] & 0xFF
            self.offset += 1
            cmd_id = (length << 8) | next_byte
            return CMD_NAMES.get(cmd_id, str(cmd_id))

    def read_byte(self):
        val = struct.unpack_from('>b', self.data, self.offset)[0]
        self.offset += 1
        return val

    def read_short(self):
        val = struct.unpack_from('>h', self.data, self.offset)[0]
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
        if length < 0: length += 256
        s = self.data[self.offset:self.offset + length].decode('ascii', errors='replace')
        self.offset += length
        return s

    def read_string(self):
        char_count = self.read_short()
        byte_len = char_count * 2
        s = self.data[self.offset:self.offset + byte_len].decode('utf-16-be', errors='replace')
        self.offset += byte_len
        return s

# ==================== LOGIC BÀN CỜ ====================
class XiangqiBoardTracker:
    INITIAL_FEN = "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w"

    def __init__(self):
        self.reset()

    def reset(self):
        self.fen = self.INITIAL_FEN
        self.move_history = []
        self.my_slot_id = -1
        self.first_turn_slot_id = 0
        self.is_my_turn = False
        self.is_playing = False
        self.is_red = None

    def pos_to_engine_move(self, source_pos, target_pos):
        s_col = source_pos % 9
        s_row = source_pos // 9
        t_col = target_pos % 9
        t_row = target_pos // 9
        if not self.is_red:
            s_row = 9 - s_row
            t_row = 9 - t_row
        return f"{chr(ord('a') + s_col)}{s_row}{chr(ord('a') + t_col)}{t_row}"

    def engine_move_to_pos(self, engine_move):
        s_col = ord(engine_move[0]) - ord('a')
        s_rank = int(engine_move[1])
        t_col = ord(engine_move[2]) - ord('a')
        t_rank = int(engine_move[3])
        s_row, t_row = s_rank, t_rank
        if not self.is_red:
            s_row = 9 - s_row
            t_row = 9 - t_row
        return s_row * 9 + s_col, t_row * 9 + t_col

    def get_current_fen(self):
        # Xác định lượt đi thực tế dựa theo flag do server cập nhật
        side = 'w' if self.is_my_turn == self.is_red else 'b'
        board_fen = self.fen.split(' ')[0] if ' ' in self.fen else self.fen
        return f"{board_fen} {side}", self.move_history

    def set_my_slot(self, slot_id, first_turn_slot_id):
        self.my_slot_id = slot_id
        self.first_turn_slot_id = first_turn_slot_id
        self.is_red = (self.my_slot_id == first_turn_slot_id)

# ==================== LỚP ĐIỀU KHIỂN BOT ====================
class PikafishBot:
    def __init__(self, depth=15):
        self.conn = Conn()
        self.board = XiangqiBoardTracker()
        self.engine = None
        self.depth = depth
        self.ws = None
        self.connected = False
        self.logged_in = False
        self.in_game = False
        self._joining_table = False
        self._returning_to_lobby = False
        self._last_quick_play_time = 0
        self._QUICK_PLAY_INTERVAL = 10
        self._init_engine()

    def _init_engine(self):
        possible_paths = [
            os.path.expanduser("~/pikafish"),
            os.path.expanduser("~/Android/pikafish-armv8"),
            "/data/data/com.termux/files/home/pikafish",
            "./pikafish"
        ]
        pikafish_path = next((p for p in possible_paths if os.path.isfile(p) and os.access(p, os.X_OK)), None)

        if not pikafish_path:
            print("[ENGINE] ❌ Không tìm thấy file binary Pikafish!")
            return

        try:
            self._engine_proc = subprocess.Popen(
                [pikafish_path], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1
            )
            self._fsf_cmd("uci")
            self._fsf_wait_for("uciok")
            nnue_path = os.path.expanduser("~/pikafish.nnue")
            if not os.path.isfile(nnue_path):
                nnue_path = os.path.join(os.path.dirname(pikafish_path), "pikafish.nnue")
            if os.path.isfile(nnue_path):
                self._fsf_cmd(f"setoption name EvalFile value {nnue_path}")
                print(f"[ENGINE] 🧠 NNUE: {nnue_path}")
            
            self._fsf_cmd("setoption name Use NNUE value true")
            self._fsf_cmd("isready")
            self._fsf_wait_for("readyok")
            self.engine = True
            print(f"[ENGINE] ✅ Sẵn sàng ở Depth: {self.depth}")
        except Exception as e:
            print(f"[ENGINE] ❌ Lỗi khởi động: {e}")

    def _fsf_cmd(self, text):
        if getattr(self, '_engine_proc', None):
            self._engine_proc.stdin.write(text + "\n")
            self._engine_proc.stdin.flush()

    def _fsf_wait_for(self, token, timeout=10):
        proc = getattr(self, '_engine_proc', None)
        start = time.time()
        while proc:
            line = proc.stdout.readline().strip()
            if token in line: return line
            if time.time() - start > timeout: raise RuntimeError(f"Timeout waiting for {token}")

    def get_best_move(self, fen, moves):
        try:
            if not getattr(self, '_engine_proc', None): return None
            pos_cmd = f"position fen {fen}"
            if moves: pos_cmd += " moves " + " ".join(moves)
            self._fsf_cmd(pos_cmd)
            self._fsf_cmd(f"go depth {self.depth}")

            _go_start = time.time()
            _go_timeout = 30
            while True:
                line = self._engine_proc.stdout.readline().strip()
                if line.startswith("bestmove"):
                    parts = line.split()
                    if len(parts) >= 2 and parts[1] not in ["(none)", "0000"]:
                        return parts[1]
                    break
                if time.time() - _go_start > _go_timeout:
                    self._fsf_cmd("stop")
                    break
        except Exception as e:
            print(f"[ENGINE] Lỗi tính nước đi: {e}")
        return None

    # ==================== WEBSOCKET LAYER ====================
    def connect(self):
        import websocket
        self.connected = False
        self.ws = websocket.WebSocketApp(
            WS_URL, cookie=COOKIE,
            on_open=self._on_open, on_message=self._on_message,
            on_error=self._on_error, on_close=self._on_close,
            header={"Origin": "https://gamevh.net"}
        )
        self.ws_thread = threading.Thread(target=lambda: self.ws.run_forever(ping_interval=25, ping_timeout=10), daemon=True)
        self.ws_thread.start()

        for _ in range(25):
            if self.connected: break
            time.sleep(0.2)
        return self.connected

    def _on_open(self, ws):
        print("[WS] 🌐 Kết nối mạng ổn định.")
        self.connected = True
        self._send_login()

    def _on_message(self, ws, message):
        if isinstance(message, bytes): self._handle_binary_message(message)

    def _on_error(self, ws, error): print(f"[WS] Lỗi cổng kết nối: {error}")
    def _on_close(self, ws, code, msg):
        print(f"[WS] Đóng kết nối hệ thống.")
        self.connected = False; self.logged_in = False; self.in_game = False

    def send_message(self, cmd, data=b''):
        if self.ws and self.connected:
            try:
                msg = self.conn.pack(cmd, data)
                self.ws.send(msg, opcode=0x2)
            except Exception as e: print(f"[SEND ERROR] {e}")

    def _send_login(self):
        data = bytearray()
        data.extend(self.conn.pack_ascii(CURRENT_PLAYER_NICKNAME))
        data.extend(self.conn.pack_int(TOKEN))
        data.extend(self.conn.pack_ascii("5.0.2"))
        data.extend(self.conn.pack_ascii(""))
        data.extend(self.conn.pack_ascii(GAME_ID))
        data.extend(self.conn.pack_byte(1))
        self.send_message("LOGIN", bytes(data))

    def send_enter_place(self, path=PLACE_PATH, mode=1):
        data = bytearray()
        data.extend(self.conn.pack_ascii(path))
        data.extend(self.conn.pack_string(""))
        data.extend(self.conn.pack_byte(mode))
        self.send_message("ENTER_PLACE", bytes(data))

    def send_create_table(self):
        now = time.time()
        if now - self._last_quick_play_time < self._QUICK_PLAY_INTERVAL: return
        self._last_quick_play_time = now

        args = [
            ("matchDuration", str(BOT_MATCH_DURATION)),
            ("turnDuration", str(BOT_TURN_DURATION)),
            ("accDuration", str(BOT_ACC_DURATION)),
            ("blockSoftware", str(BOT_BLOCK_SOFTWARE)),
        ]
        data = bytearray()
        data.extend(self.conn.pack_byte(BOT_BET_AMT_ID))       
        data.extend(self.conn.pack_byte(len(args)))         
        for arg_name, arg_value in args:
            data.extend(self.conn.pack_ascii(arg_name))     
            data.extend(self.conn.pack_string(arg_value))   
        self.send_message("CREATE_RULE", bytes(data))

    def send_quick_play(self):
        now = time.time()
        if now - self._last_quick_play_time < self._QUICK_PLAY_INTERVAL: return
        self._last_quick_play_time = now
        data = bytearray()
        data.extend(self.conn.pack_ascii(""))
        data.extend(self.conn.pack_byte(-1))
        self.send_message("QUICK_PLAY", bytes(data))

    def send_play(self, source_pos, target_pos):
        data = bytearray()
        data.extend(self.conn.pack_byte(source_pos))
        data.extend(self.conn.pack_byte(target_pos))
        self.send_message("PLAY", bytes(data))

    def send_get_table_data(self):
        # Lệnh yêu cầu đồng bộ trực tiếp FEN từ Server
        self.send_message("GET_TABLE_DATA")

    # ==================== HANDLE PROTOCOL ====================
    def _handle_binary_message(self, data):
        try:
            msg = InboundMessage(data)
            cmd = msg.command

            if cmd == "PING": self.send_message("PONG")
            elif cmd == "LOGIN": self._handle_login_response(msg)
            elif cmd == "ENTER_PLACE": self._handle_enter_place_response(msg)
            elif cmd == "QUICK_PLAY": self._handle_quick_play_response(msg)
            elif cmd == "CREATE_RULE": self._handle_create_rule_response(msg)
            elif cmd == "SLOT_IN_TABLE_CHANGED": self._handle_slot_changed(msg)
            elif cmd == "START_MATCH": self._handle_start_match(msg)
            elif cmd == "MOVE": self._handle_move(msg)
            elif cmd == "PLAY" or cmd == "502": self._handle_play_response(msg)
            elif cmd == "SET_TURN": self._handle_set_turn(msg)
            elif cmd == "GET_TABLE_DATA" or cmd == "414": self._handle_table_data_refresh(msg) # Đọc lại FEN sạch
            elif cmd == "GAMEOVER": self._handle_gameover(msg)
        except Exception as e: print(f"[RECV ERROR] {e}")

    def _handle_login_response(self, msg):
        if msg.read_byte() == 0:
            self.logged_in = True
            path = msg.read_string()
            if path == 'REFRESH':
                fetch_session_info(); self._send_login(); return
            self.send_enter_place()

    def _handle_enter_place_response(self, msg):
        if msg.read_byte() == 0:
            if self._joining_table:
                self._joining_table = False; self.in_game = True
            elif not self.in_game: pass
            else:
                self.in_game = False; self._joining_table = False; self.board.reset()

    def _handle_quick_play_response(self, msg):
        if msg.read_byte() == 0:
            self.in_game = True; self._joining_table = True
            table_path = msg.read_ascii()
            threading.Thread(target=lambda: [time.sleep(1.0), self.send_enter_place(path=table_path, mode=1)], daemon=True).start()

    def _handle_create_rule_response(self, msg):
        if msg.read_byte() == 0:
            self.in_game = True; self._joining_table = True
            table_path = msg.read_ascii()
            msg.read_int()
            print(f"[LOBBY] ✅ Tạo bàn thành công: {table_path}")
            threading.Thread(target=lambda: [time.sleep(1.0), self.send_enter_place(path=table_path, mode=1)], daemon=True).start()

    def _handle_slot_changed(self, msg):
        try:
            msg.read_string(); slot_id = msg.read_byte()
            for _ in range(7): msg.read_byte() if _ in [2,5,6] else msg.read_long() if _==0 else msg.read_short() if _==3 else msg.read_ascii()
            if msg.read_long() == CURRENT_PLAYER_ID: self.board.my_slot_id = slot_id
        except: pass

    def _handle_start_match(self, msg):
        print(f"[GAME] 🎮 Bắt đầu ván mới!")
        self.board.reset()
        self.board.is_playing = True; self.in_game = True

        try:
            player_count = msg.read_byte()
            for _ in range(player_count): msg.read_byte(); msg.read_int()
            piece_count = msg.read_byte()
            board_pieces = []
            for _ in range(piece_count):
                board_pieces.append((self._decode_piece_id(msg.read_byte()), self._decode_piece_id(msg.read_byte()), msg.read_byte(), msg.read_byte()))

            msg.read_byte(); mystery_count = msg.read_byte()
            for _ in range(mystery_count): msg.read_byte()
            msg.read_byte(); msg.read_byte()

            first_turn_slot_id = msg.read_byte()
            my_slot_id = msg.read_byte()
            if my_slot_id < 0 or my_slot_id == 255:
                my_slot_id = self.board.my_slot_id if self.board.my_slot_id >= 0 else first_turn_slot_id

            self.board.set_my_slot(my_slot_id, first_turn_slot_id)
            self.board.fen = self._build_fen_from_pieces(board_pieces)
        except Exception as e: print(f"[START_MATCH ERROR] {e}")

    def _build_fen_from_pieces(self, pieces):
        board = [['.' for _ in range(9)] for _ in range(10)]
        for sid, face, position, is_open in pieces:
            if position < 0 or position >= 90: continue
            game_row, col = position // 9, position % 9
            fen_row = 9 - game_row
            color = face[0]
            piece_type = int(face[1]) if len(face) > 1 else 0
            type_to_fen = {1: 'k', 2: 'a', 3: 'b', 4: 'r', 5: 'c', 6: 'n', 7: 'p'}
            fen_char = type_to_fen.get(piece_type, '?')
            if color == 'r': fen_char = fen_char.upper()
            board[fen_row][col] = fen_char

        fen_rows = []
        for row in board:
            fen_row = ""; empty = 0
            for cell in row:
                if cell == '.': empty += 1
                else:
                    if empty > 0: fen_row += str(empty); empty = 0
                    fen_row += cell
            if empty > 0: fen_row += str(empty)
            fen_rows.append(fen_row)
        return '/'.join(fen_rows) + ' w'

    def _handle_move(self, msg):
        try:
            source_pos = msg.read_byte(); target_pos = msg.read_byte()
            engine_move = self.board.pos_to_engine_move(source_pos, target_pos)
            if not self.board.move_history or self.board.move_history[-1] != engine_move:
                self.board.move_history.append(engine_move)
            print(f"[MOVE] Đối thủ đi: {engine_move}")
        except Exception as e: print(f"[MOVE ERROR] {e}")

    def _handle_play_response(self, msg):
        if msg.read_byte() != 0:
            if self.board.move_history: self.board.move_history.pop()
            self.board.is_my_turn = True

    def _handle_set_turn(self, msg):
        try:
            slot_id = msg.read_byte()
            if slot_id != -1:
                self.board.is_my_turn = (slot_id == self.board.my_slot_id)
                
                # CHỐNG BỎ LƯỢT: Mỗi khi tới lượt mình, lập tức ép Server cung cấp lại dữ liệu FEN sạch
                if self.board.is_my_turn and self.board.is_playing:
                    print(f"[TURN] Đến lượt bot (Slot: {slot_id}). Đang gọi Server đồng bộ FEN thực tế...")
                    self.send_get_table_data()
        except Exception as e: print(f"[SET_TURN ERROR] {e}")

    def _handle_table_data_refresh(self, msg):
        try:
            msg.read_ascii() # Bỏ qua tên bàn
            msg.read_byte()  # Bỏ qua trạng thái
            
            # Cập nhật danh sách quân hiện tại trên bàn từ server
            piece_count = msg.read_byte()
            board_pieces = []
            for _ in range(piece_count):
                board_pieces.append((self._decode_piece_id(msg.read_byte()), self._decode_piece_id(msg.read_byte()), msg.read_byte(), msg.read_byte()))
            
            # Khởi tạo lại FEN chuẩn và xóa sạch lịch sử để tránh lệch nhịp
            self.board.fen = self._build_fen_from_pieces(board_pieces)
            self.board.move_history = [] 
            print(f"[REFRESH FEN] Đồng bộ thành công: {self.board.fen}")
            
            # Kích hoạt Pikafish tính toán dựa trên FEN sạch vừa nhận
            if self.board.is_my_turn and self.board.is_playing:
                threading.Thread(target=self._make_auto_move, daemon=True).start()
        except Exception as e: print(f"[REFRESH ERROR] Không thể đọc dữ liệu: {e}")

    def _handle_gameover(self, msg):
        print("[GAME] 🏁 Trận đấu kết thúc.")
        self.board.reset()
        self.board.is_playing = False; self.board.is_my_turn = False; self.in_game = True  

    def _make_auto_move(self):
        if not self.board.is_my_turn or not self.board.is_playing: return

        fen, moves = self.board.get_current_fen()
        best_move = self.get_best_move(fen, moves)

        if best_move and best_move not in ["(none)", "0000"]:
            try:
                source_pos, target_pos = self.board.engine_move_to_pos(best_move)
                time.sleep(1)
                self.send_play(source_pos, target_pos)
            except Exception as e: print(f"[BOT ERROR] Tọa độ lỗi: {e}")

    def _decode_piece_id(self, encoded_id):
        color = 'r'
        if encoded_id < 0: encoded_id = -encoded_id; color = 'b'
        return f"{color}{encoded_id >> 3}{'' if (encoded_id & 7) == 0 else (encoded_id & 7)}"

    def start_keep_alive(self):
        def keep_alive_loop():
            while self.connected:
                time.sleep(10)
                if self.connected: self.send_message("PING")
        threading.Thread(target=keep_alive_loop, daemon=True).start()

    def run(self):
        print("[BOT] Khởi chạy hệ thống giám sát tự động...")
        while True:
            try:
                if not self.connected:
                    if not fetch_session_info(): time.sleep(5); continue
                    self.logged_in = False; self.in_game = False; self.board.reset()
                    if not self.connect(): time.sleep(5); continue
                    self.start_keep_alive(); time.sleep(2)

                if self.connected and self.logged_in and not self.in_game and not self._returning_to_lobby:
                    now = time.time()
                    if now - self._last_quick_play_time >= self._QUICK_PLAY_INTERVAL:
                        if BOT_USE_CREATE_TABLE: self.send_create_table()
                        else: self.send_quick_play()
                time.sleep(7)
            except KeyboardInterrupt: break
            except Exception as e: time.sleep(5)

    def cleanup(self):
        proc = getattr(self, '_engine_proc', None)
        if proc:
            try: proc.stdin.write("quit\n"); proc.stdin.flush(); proc.wait(timeout=2)
            except:
                try: proc.terminate()
                except: pass
        if self.ws:
            try: self.ws.close()
            except: pass

if __name__ == "__main__":
    bot = PikafishBot(depth=BOT_DEPTH)
    signal.signal(signal.SIGINT, lambda s, f: [bot.cleanup(), sys.exit(0)])
    signal.signal(signal.SIGTERM, lambda s, f: [bot.cleanup(), sys.exit(0)])
    try: bot.run()
    finally: bot.cleanup()