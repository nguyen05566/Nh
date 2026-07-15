#!/usr/bin/env python3
"""
Xiangqi Bot - gamevh.net (CREATE_TABLE Edition)
Đã tách Cookie sang config_secret.py
Sửa lỗi: Không vào bàn sau một lúc & Treo máy không đi quân khi ở trong bàn
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

# ==================== COOKIE MẶC ĐỊNH (được gộp từ config_secret.py) ====================
COOKIE = (
    "_ga=GA1.2.1268277570.1781579079; "
    "memberName=4F0D0D2A316B7A1688ED292DEE05CCD9; "
    "memberPassword=E71A8D5F227140577E4376EA88F92797; "
    "_gid=GA1.2.1353156256.1781717134; "
    "JSESSIONID=node0zvjox1rf5xidsuavo0720sp048677678.node0; "
    "clientIp=F31E20F28AD2B3BEE29105588C4DC2296D05851A73515915FD86406FA485B8B4; "
    "_gat=1"
)

# Nếu có file config_secret.py thì ưu tiên dùng cookie từ đó (cho phép thay đổi dễ dàng)
try:
    from config_secret import COOKIE as SECRET_COOKIE
    COOKIE = SECRET_COOKIE
    print("[SYSTEM] ✅ Đã nạp cookie từ config_secret.py")
except ImportError:
    print("[SYSTEM] ℹ️ Không tìm thấy config_secret.py, dùng cookie mặc định trong script.")

# Fix import path cho pikafish_terminal
_venv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'venv', 'lib')
for _py_ver in ['python3.12', 'python3.13', 'python3.11']:
    _candidate = os.path.join(_venv_path, _py_ver, 'site-packages')
    if os.path.isdir(_candidate):
        sys.path.insert(0, _candidate)
        break

# Đường dẫn file lưu session an toàn
SESSION_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_session.json")

# ==================== CẤU HÌNH MẶC ĐỊNH ====================
WS_URL = "wss://gamevh.net/ws/gameServer"

CURRENT_PLAYER_NICKNAME = 'nguyen05511'
CURRENT_PLAYER_ID = 65692430
TOKEN = 1238338868
GAME_ID = 'xiangqi'
PLACE_PATH = 'Lobby.xiangqi.0'

BOT_DEPTH = 19  # Tăng lại lên 15 cho tối ưu nước đi

# ===== CẤU HÌNH TẠO BÀN =====
BOT_BET_XU = 1000
BOT_USE_CREATE_TABLE = True

BOT_MATCH_DURATION = '5'     # Phút/ván
BOT_TURN_DURATION = '30'     # Giây/nước
BOT_ACC_DURATION = '0'       # Lũy tiến: 0=không
BOT_BLOCK_SOFTWARE = '0'     # Chặn phần mềm: 0=không

# Tải cấu hình đã lưu trước đó nếu có
if os.path.exists(SESSION_FILE):
    try:
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            saved_data = json.load(f)
            COOKIE = saved_data.get("cookie", COOKIE)
            CURRENT_PLAYER_NICKNAME = saved_data.get("nickname", CURRENT_PLAYER_NICKNAME)
            CURRENT_PLAYER_ID = saved_data.get("player_id", CURRENT_PLAYER_ID)
            TOKEN = saved_data.get("token", TOKEN)
            print("[SYSTEM] 📂 Đã nạp thông tin phiên đăng nhập cũ từ bot_session.json")
    except Exception as e:
        print(f"[SYSTEM] Không thể đọc file session: {e}")

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
                if key == 'token':
                    TOKEN = int(m.group(1))
                elif key == 'currentPlayerId':
                    CURRENT_PLAYER_ID = int(m.group(1))
                elif key == 'currentPlayerNickName':
                    CURRENT_PLAYER_NICKNAME = m.group(1).strip()

        for cookie in session.cookies:
            if cookie.name == 'JSESSIONID':
                COOKIE = re.sub(r'JSESSIONID=[^;]+', f'JSESSIONID={cookie.value}', COOKIE)

        print(f"[SESSION] Token: {TOKEN} | NickName: {CURRENT_PLAYER_NICKNAME} | PlayerID: {CURRENT_PLAYER_ID}")
        
        try:
            with open(SESSION_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "cookie": COOKIE,
                    "nickname": CURRENT_PLAYER_NICKNAME,
                    "player_id": CURRENT_PLAYER_ID,
                    "token": TOKEN
                }, f, ensure_ascii=False, indent=4)
            print("[SYSTEM] 💾 Đã lưu phiên đăng nhập mới vào file 'bot_session.json' an toàn!")
        except Exception as file_err:
            print(f"[SYSTEM] ⚠️ Lỗi khi ghi file JSON: {file_err}")

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
STANDARD_PAWN_POSITIONS = set()
for _c in [0, 2, 4, 6, 8]:
    STANDARD_PAWN_POSITIONS.add(6 * 9 + _c)
    STANDARD_PAWN_POSITIONS.add(3 * 9 + _c)

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
        side = 'w' if len(self.move_history) % 2 == 0 else 'b'
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
        self.bet_amts = []
        self._resolved_bet_id = None
        self._bet_amts_loaded = False
        self.fixed_pawn_positions = set()
        
        # Biến giám sát chống treo bàn (Anti-idle active protection)
        self.last_action_timestamp = time.time()
        
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
            else:
                print("[ENGINE] ⚠️ Không tìm thấy file NNUE, chạy không có neural net.")
            
            self._fsf_cmd("setoption name UseNNUE value false")
            self._fsf_cmd("isready")
            self._fsf_wait_for("readyok")
            self.engine = True
            print(f"[ENGINE] ✅ Sẵn sàng: {pikafish_path}")
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

    def get_best_move(self, fen, moves, fixed_positions=None):
        try:
            if not getattr(self, '_engine_proc', None): return None
            if fixed_positions:
                return self._get_move_avoiding_fixed(fen, moves, fixed_positions)

            pos_cmd = f"position fen {fen}"
            if moves: pos_cmd += " moves " + " ".join(moves)
            self._fsf_cmd(pos_cmd)
            self._fsf_cmd(f"go depth {self.depth}")
            return self._read_bestmove()
        except Exception as e:
            print(f"[ENGINE] Lỗi tính nước đi: {e}")
        return None

    def _read_bestmove(self, timeout=30):
        _go_start = time.time()
        while True:
            line = self._engine_proc.stdout.readline().strip()
            if line.startswith("bestmove"):
                parts = line.split()
                if len(parts) >= 2 and parts[1] not in ["(none)", "0000"]:
                    return parts[1]
                break
            if time.time() - _go_start > timeout:
                print(f"[ENGINE] ⏰ Timeout sau {timeout}s")
                self._fsf_cmd("stop")
                break
        return None

    def _get_move_avoiding_fixed(self, fen, moves, fixed_positions):
        max_pv = 5
        self._fsf_cmd(f"setoption name MultiPV value {max_pv}")
        self._fsf_cmd("isready")
        try:
            self._fsf_wait_for("readyok", timeout=30)
        except RuntimeError:
            pass

        pos_cmd = f"position fen {fen}"
        if moves: pos_cmd += " moves " + " ".join(moves)
        self._fsf_cmd(pos_cmd)
        self._fsf_cmd(f"go depth {self.depth}")

        candidates = []
        _go_start = time.time()
        while True:
            line = self._engine_proc.stdout.readline().strip()
            if line.startswith("bestmove"):
                break
            if "multipv" in line and " pv " in line:
                parts = line.split()
                try:
                    mpv_idx = parts.index("multipv")
                    pv_idx = parts.index("pv")
                    mpv_num = int(parts[mpv_idx + 1])
                    first_move = parts[pv_idx + 1]
                    if first_move not in ["(none)", "0000"]:
                        while len(candidates) < mpv_num:
                            candidates.append(None)
                        candidates[mpv_num - 1] = first_move
                except (ValueError, IndexError):
                    pass
            if time.time() - _go_start > 30:
                print(f"[ENGINE] ⏰ Timeout MultiPV sau 30s")
                self._fsf_cmd("stop")
                break

        self._fsf_cmd("setoption name MultiPV value 1")

        for move in candidates:
            if move is None: continue
            if not self._move_involves_fixed(move, fixed_positions):
                print(f"[ENGINE] 🎯 Nước đi hợp lệ (tránh tốt liệt): {move}")
                return move

        if candidates and candidates[0]:
            print(f"[ENGINE] ⚠️ Tất cả nước đi chạm tốt liệt, dùng nước đầu: {candidates[0]}")
            return candidates[0]
        return None

    def _move_involves_fixed(self, engine_move, fixed_positions):
        try:
            s_col = ord(engine_move[0]) - ord('a')
            s_rank = int(engine_move[1])
            t_col = ord(engine_move[2]) - ord('a')
            t_rank = int(engine_move[3])
            s_row = s_rank if self.board.is_red else 9 - s_rank
            t_row = t_rank if self.board.is_red else 9 - t_rank
            s_game_pos = s_row * 9 + s_col
            t_game_pos = t_row * 9 + t_col
            return s_game_pos in fixed_positions or t_game_pos in fixed_positions
        except Exception:
            return False

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
        self.last_action_timestamp = time.time()
        self._send_login()

    def _on_message(self, ws, message):
        if isinstance(message, bytes): self._handle_binary_message(message)

    def _on_error(self, ws, error): print(f"[WS] Lỗi cổng kết nối: {error}")
    def _on_close(self, ws, code, msg):
        print(f"[WS] Đóng kết nối hệ thống: code={code} msg={msg}")
        self.connected = False
        self.logged_in = False
        self.in_game = False
        self._joining_table = False
        self._returning_to_lobby = False
        self._bet_amts_loaded = False
        self._resolved_bet_id = None
        self.bet_amts = []
        self.fixed_pawn_positions = set()
        self.board.reset()

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

    def send_list_bet_amt(self):
        print("[LOBBY] Lấy danh sách mức cược từ server...")
        self.send_message("LIST_BET_AMT")

    def resolve_bet_amt_id(self):
        if not self.bet_amts: return None
        for ba in self.bet_amts:
            if ba['value'] == BOT_BET_XU: return ba['id']
        lower = [ba for ba in self.bet_amts if 0 < ba['value'] <= BOT_BET_XU]
        if lower:
            best = max(lower, key=lambda x: x['value'])
            return best['id']
        valid = [ba for ba in self.bet_amts if ba['value'] > 0]
        if valid:
            best = max(valid, key=lambda x: x['value'])
            return best['id']
        return 0

    def send_create_table(self, bet_amt_id=None, match_duration=None, turn_duration=None, 
                          acc_duration=None, block_software=None):
        now = time.time()
        if now - self._last_quick_play_time < self._QUICK_PLAY_INTERVAL: return
        self._last_quick_play_time = now

        if bet_amt_id is None:
            if self._resolved_bet_id is not None: bet_amt_id = self._resolved_bet_id
            else:
                bet_amt_id = self.resolve_bet_amt_id()
                if bet_amt_id is None: return
        if match_duration is None: match_duration = BOT_MATCH_DURATION
        if turn_duration is None: turn_duration = BOT_TURN_DURATION
        if acc_duration is None: acc_duration = BOT_ACC_DURATION
        if block_software is None: block_software = BOT_BLOCK_SOFTWARE

        args = [
            ("matchDuration", str(match_duration)),
            ("turnDuration", str(turn_duration)),
            ("accDuration", str(acc_duration)),
            ("blockSoftware", str(block_software)),
        ]

        data = bytearray()
        data.extend(self.conn.pack_byte(bet_amt_id))       
        data.extend(self.conn.pack_byte(len(args)))        

        for arg_name, arg_value in args:
            data.extend(self.conn.pack_ascii(arg_name))    
            data.extend(self.conn.pack_string(arg_value))  

        print("[LOBBY] Đang gửi lệnh tạo bàn lên Server...")
        self.send_message("CREATE_RULE", bytes(data))

    def send_quick_play(self, room_id="", bet_amt_id=-1):
        now = time.time()
        if now - self._last_quick_play_time < self._QUICK_PLAY_INTERVAL: return
        self._last_quick_play_time = now
        data = bytearray()
        data.extend(self.conn.pack_ascii(room_id))
        data.extend(self.conn.pack_byte(bet_amt_id))
        self.send_message("QUICK_PLAY", bytes(data))

    def send_play(self, source_pos, target_pos):
        data = bytearray()
        data.extend(self.conn.pack_byte(source_pos))
        data.extend(self.conn.pack_byte(target_pos))
        self.send_message("PLAY", bytes(data))

    def send_ready(self, is_ready=1):
        """Gửi lệnh SET_READY (434) lên server. is_ready: 1 = Sẵn sàng, 0 = Hủy"""
        print("[GAME] ⏳ Gửi trạng thái Sẵn sàng (READY)...")
        data = bytearray()
        data.extend(self.conn.pack_byte(is_ready))
        self.send_message("SET_READY", bytes(data))

    # ==================== HANDLE PROTOCOL ====================
    def _handle_binary_message(self, data):
        try:
            msg = InboundMessage(data)
            cmd = msg.command

            if cmd == "PING": self.send_message("PONG")
            elif cmd == "LOGIN": self._handle_login_response(msg)
            elif cmd == "ENTER_PLACE": self._handle_enter_place_response(msg)
            elif cmd == "QUICK_PLAY": self._handle_quick_play_response(msg)
            elif cmd == "LIST_BET_AMT": self._handle_list_bet_amt_response(msg)
            elif cmd == "CREATE_RULE": self._handle_create_rule_response(msg)
            elif cmd == "SLOT_IN_TABLE_CHANGED": self._handle_slot_changed(msg)
            elif cmd == "START_MATCH": self._handle_start_match(msg)
            elif cmd == "MOVE": self._handle_move(msg)
            elif cmd == "PLAY" or cmd == "502": self._handle_play_response(msg)
            elif cmd == "SET_TURN": self._handle_set_turn(msg)
            elif cmd == "GAMEOVER": self._handle_gameover(msg)
        except Exception as e: print(f"[RECV ERROR] {cmd if 'cmd' in locals() else ''}: {e}")

    def _handle_login_response(self, msg):
        if msg.read_byte() == 0:
            print("[LOGIN] Đăng nhập vào cổng game chính thức thành công.")
            self.logged_in = True
            path = msg.read_string()
            if path == 'REFRESH':
                fetch_session_info()
                self._send_login()
                return
            self.send_enter_place()

    def _handle_enter_place_response(self, msg):
        if msg.read_byte() == 0:
            if self._joining_table:
                print("[PLACE] Đã chuyển vùng vào phòng chơi thành công.")
                self._joining_table = False
                self.in_game = True
                self.last_action_timestamp = time.time()
                
                # --- Tự động bấm Sẵn sàng sau khi vào bàn 5 giây ---
                def delay_initial_ready():
                    time.sleep(5.0)  
                    self.send_ready(1)
                threading.Thread(target=delay_initial_ready, daemon=True).start()
                
            elif not self.in_game:
                print("[PLACE] Đã vào sảnh chờ. Lấy danh sách mức cược...")
                self._bet_amts_loaded = False
                self._resolved_bet_id = None
                self.send_list_bet_amt()
            else:
                print("[PLACE] ⚠️ Bàn chơi bị giải tán hoặc bị đá ra sảnh! Đang tạo bàn mới...")
                self.in_game = False
                self._joining_table = False
                self.board.reset()

    def _handle_quick_play_response(self, msg):
        if msg.read_byte() == 0:
            self.in_game = True  
            self._joining_table = True
            table_path = msg.read_ascii()
            def async_join():
                time.sleep(1.0)
                self.send_enter_place(path=table_path, mode=1)
            threading.Thread(target=async_join, daemon=True).start()

    def _handle_list_bet_amt_response(self, msg):
        status = msg.read_byte()
        if status != 0: return
        count = msg.read_byte()
        self.bet_amts = []
        for i in range(count):
            value = msg.read_int()
            self.bet_amts.append({"id": i, "value": value})

        chosen = self.resolve_bet_amt_id()
        if chosen is not None:
            self._resolved_bet_id = chosen
        self._bet_amts_loaded = True

    def _handle_create_rule_response(self, msg):
        status = msg.read_byte()
        if status == 0:
            self.in_game = True  
            self._joining_table = True
            table_path = msg.read_ascii()
            msg.read_int()
            def async_join():
                time.sleep(1.0)
                self.send_enter_place(path=table_path, mode=1)
            threading.Thread(target=async_join, daemon=True).start()
        else:
            print(f"[LOBBY] ❌ Tạo bàn không thành công (Status code: {status})")
            self._joining_table = False

    def _handle_slot_changed(self, msg):
        try:
            _ = msg.read_string()
            slot_id = msg.read_byte()
            msg.read_long(); msg.read_long(); msg.read_byte(); msg.read_short(); msg.read_ascii(); msg.read_byte(); msg.read_byte()
            player_id = msg.read_long()
            
            if player_id == CURRENT_PLAYER_ID: 
                self.board.my_slot_id = slot_id
            else:
                if player_id > 0 and not self.board.is_playing:
                    print(f"[GAME] 👤 Phát hiện đối thủ (ID: {player_id}) vào bàn! Chờ 5s rồi Ready...")
                    def delay_ready_on_player():
                        time.sleep(5.0)  # Đợi 5 giây
                        if self.in_game and not self.board.is_playing:
                            self.send_ready(1)
                    threading.Thread(target=delay_ready_on_player, daemon=True).start()
        except: 
            pass

    def _handle_start_match(self, msg):
        print(f"[GAME] 🎮 Khởi tạo ván cờ mới!")
        self.board.reset()
        self.board.is_playing = True
        self.in_game = True
        self._joining_table = False
        self.last_action_timestamp = time.time()

        try:
            player_count = msg.read_byte()
            for _ in range(player_count):
                slot = msg.read_byte(); pid = msg.read_int()

            piece_count = msg.read_byte()
            board_pieces = []
            for i in range(piece_count):
                raw_sid = msg.read_byte()
                raw_face = msg.read_byte()
                pos = msg.read_byte()
                is_open = msg.read_byte()
                sid = self._decode_piece_id(raw_sid)
                face = self._decode_piece_id(raw_face)
                board_pieces.append((sid, face, pos, is_open))

            msg.read_byte(); mystery_count = msg.read_byte()
            for i in range(mystery_count): msg.read_byte()
            msg.read_byte(); msg.read_byte()

            first_turn_slot_id = msg.read_byte()
            my_slot_id = msg.read_byte()

            if my_slot_id < 0 or my_slot_id == 255:
                my_slot_id = self.board.my_slot_id if self.board.my_slot_id >= 0 else first_turn_slot_id

            self.board.set_my_slot(my_slot_id, first_turn_slot_id)

            self.fixed_pawn_positions = set()
            for sid, face, position, is_open in board_pieces:
                piece_type = int(face[1]) if len(face) > 1 else 0
                if piece_type == 7 and position not in STANDARD_PAWN_POSITIONS:
                    self.fixed_pawn_positions.add(position)

            self.board.fen = self._build_fen_from_pieces(board_pieces)
            if my_slot_id == first_turn_slot_id:
                self.board.is_my_turn = True
                threading.Thread(target=self._make_auto_move, daemon=True).start()
        except Exception as e: print(f"[GAME ERROR] START_MATCH: {e}")

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
            fen_row = ""
            empty = 0
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
            source_pos = msg.read_byte()
            target_pos = msg.read_byte()
            engine_move = self.board.pos_to_engine_move(source_pos, target_pos)

            self.last_action_timestamp = time.time()

            if not self.board.move_history or self.board.move_history[-1] != engine_move:
                self.board.move_history.append(engine_move)

            is_red_turn = (len(self.board.move_history) % 2 == 0)
            if (is_red_turn == self.board.is_red) and self.board.is_playing:
                self.board.is_my_turn = True
                threading.Thread(target=self._make_auto_move, daemon=True).start()
            else: self.board.is_my_turn = False
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
                self.last_action_timestamp = time.time()
        except: pass

    def _handle_gameover(self, msg):
        print("[GAME] 🏁 Trận đấu kết thúc. Tự động chuẩn bị cho ván mới...")
        self.board.reset()
        self.board.is_playing = False
        self.board.is_my_turn = False
        self.in_game = True  
        self._joining_table = False
        self.last_action_timestamp = time.time()

        # --- Tự động bấm Sẵn sàng sau khi kết thúc trận đấu 5 giây ---
        def delay_ready():
            time.sleep(5.0)
            self.send_ready(1)
        threading.Thread(target=delay_ready, daemon=True).start()

    def _make_auto_move(self):
        if not self.board.is_my_turn or not self.board.is_playing: return
        fen, moves = self.board.get_current_fen()
        fixed = self.fixed_pawn_positions if self.fixed_pawn_positions else None
        best_move = self.get_best_move(fen, moves, fixed_positions=fixed)

        if best_move and best_move not in ["(none)", "0000"]:
            try:
                source_pos, target_pos = self.board.engine_move_to_pos(best_move)
                time.sleep(1)
                self.send_play(source_pos, target_pos)
            except Exception as e: print(f"[BOT ERROR] Dịch tọa độ lỗi: {e}")

    def _decode_piece_id(self, encoded_id):
        color = 'r'
        if encoded_id < 0: encoded_id = -encoded_id; color = 'b'
        piece_type = encoded_id >> 3
        suffix = encoded_id & 7
        return f"{color}{piece_type}{'' if suffix == 0 else suffix}"

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
                # Bảo vệ chủ động: Nếu đang trong ván chơi mà > 40 giây không có phản hồi gì, tự ngắt để recon
                if self.connected and self.board.is_playing:
                    if time.time() - self.last_action_timestamp > 40:
                        print("[SYSTEM] ⚠️ Quá 40 giây không có thay đổi bàn cờ! Nghi ngờ treo mạng. Chủ động ngắt kết nối để làm mới...")
                        if self.ws:
                            self.ws.close()
                        time.sleep(2)

                if not self.connected:
                    if not fetch_session_info():
                        time.sleep(5); continue
                    self.logged_in = False
                    self.in_game = False
                    self._joining_table = False
                    self._returning_to_lobby = False
                    self._bet_amts_loaded = False
                    self._resolved_bet_id = None
                    self.bet_amts = []
                    self.fixed_pawn_positions = set()
                    self.board.reset()

                    if not self.connect():
                        time.sleep(5); continue
                    self.start_keep_alive()
                    time.sleep(2)

                if self.connected and self.logged_in and not self.in_game and not self._joining_table:
                    now = time.time()
                    if now - self._last_quick_play_time >= self._QUICK_PLAY_INTERVAL:
                        if BOT_USE_CREATE_TABLE:
                            if not self._bet_amts_loaded: self.send_list_bet_amt()
                            else: self.send_create_table()
                        else: self.send_quick_play()
                time.sleep(5) # Giảm thời gian lặp để quét trạng thái nhạy bén hơn
            except KeyboardInterrupt: break
            except Exception as e: time.sleep(5)

    def cleanup(self):
        proc = getattr(self, '_engine_proc', None)
        if proc:
            try:
                proc.stdin.write("quit\n"); proc.stdin.flush(); proc.wait(timeout=2)
            except:
                try: proc.terminate()
                except: pass
        if self.ws:
            try: self.ws.close()
            except: pass

if __name__ == "__main__":
    bot = PikafishBot(depth=BOT_DEPTH)
    def signal_handler(sig, frame): bot.cleanup(); sys.exit(0)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    try: bot.run()
    finally: bot.cleanup()
