#!/usr/bin/env python3
"""
Xiangqi Bot - gamevh.net 
(Bản Hoàn Chỉnh - Đã sửa lỗi gửi Ready và cập nhật logic lọc điểm MultiPV âm/dương)
"""

import struct
import threading
import time
import sys
import os
import requests
import re
import subprocess
import signal
import json
import random

# ==================== COOKIE MẶC ĐỊNH ====================
COOKIE = (
    "_ga=GA1.2.1268277570.1781579079; "
    "memberName=4F0D0D2A316B7A1688ED292DEE05CCD9; "
    "memberPassword=E71A8D5F227140577E4376EA88F92797; "
    "_gid=GA1.2.1353156256.1781717134; "
    "JSESSIONID=node0zvjox1rf5xidsuavo0720sp048677678.node0; "
    "clientIp=F31E20F28AD2B3BEE29105588C4DC2296D05851A73515915FD86406FA485B8B4; "
    "_gat=1"
)

_venv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'venv', 'lib')
for _py_ver in ['python3.12', 'python3.13', 'python3.11']:
    _candidate = os.path.join(_venv_path, _py_ver, 'site-packages')
    if os.path.isdir(_candidate):
        sys.path.insert(0, _candidate)
        break

WS_URL = "wss://gamevh.net/ws/gameServer"
CURRENT_PLAYER_NICKNAME = 'nguyen05511'
CURRENT_PLAYER_ID = 65692430
TOKEN = 1238338868
GAME_ID = 'xiangqi'
PLACE_PATH = 'Lobby.xiangqi.0'

BOT_BET_XU = 5000
BOT_USE_CREATE_TABLE = True
BOT_MATCH_DURATION = '10'
BOT_TURN_DURATION = '60'
BOT_ACC_DURATION = '0'
BOT_BLOCK_SOFTWARE = '0'

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
        print(f"[SESSION] Lỗi: {e}")
        return False

CMD_NAMES = {
    300: "PONG", 301: "PING", 302: "LOGIN", 303: "ALERT",
    311: "BROADCAST", 314: "SET_CLIENT_MODE", 315: "CONFIG",
    331: "CHAT.SEND", 335: "CHAT.MSG",
    401: "ENTER_PLACE", 405: "CREATE_RULE", 406: "PLAYER_ENTERED", 407: "PLAYER_EXITED",
    408: "QUICK_PLAY", 412: "LIST_ZONE_ROOM", 413: "LIST_BET_AMT",
    414: "GET_TABLE_DATA", 416: "SLOT_IN_TABLE_CHANGED",
    417: "START_MATCH", 418: "GAMEOVER", 419: "ENTER_STATE",
    420: "SET_TURN", 434: "SET_READY",
    502: "PLAY", 529: "MOVE", 533: "ASK_DRAW", 534: "SURRENDER", 601: "LOGIN_EX",
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
            return CMD_NAMES.get((length << 8) | next_byte, str((length << 8) | next_byte))
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
        s = self.data[self.offset:self.offset + char_count * 2].decode('utf-16-be', errors='replace')
        self.offset += char_count * 2
        return s

STANDARD_PAWN_POSITIONS = set()
for _c in [0, 2, 4, 6, 8]:
    STANDARD_PAWN_POSITIONS.add(6 * 9 + _c)
    STANDARD_PAWN_POSITIONS.add(3 * 9 + _c)

class XiangqiBoardTracker:
    INITIAL_FEN = "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w"
    def __init__(self): self.reset()
    def reset(self):
        self.fen = self.INITIAL_FEN
        self.move_history = []
        self.my_slot_id = -1
        self.first_turn_slot_id = 0
        self.is_my_turn = False
        self.is_playing = False
        self.is_red = None
    def pos_to_engine_move(self, source_pos, target_pos):
        s_col, s_row = source_pos % 9, source_pos // 9
        t_col, t_row = target_pos % 9, target_pos // 9
        if not self.is_red:
            s_row, t_row = 9 - s_row, 9 - t_row
        return f"{chr(ord('a') + s_col)}{s_row}{chr(ord('a') + t_col)}{t_row}"
    def engine_move_to_pos(self, engine_move):
        s_col, s_rank = ord(engine_move[0]) - ord('a'), int(engine_move[1])
        t_col, t_rank = ord(engine_move[2]) - ord('a'), int(engine_move[3])
        s_row, t_row = s_rank, t_rank
        if not self.is_red:
            s_row, t_row = 9 - s_row, 9 - t_row
        return s_row * 9 + s_col, t_row * 9 + t_col
    def get_current_fen(self):
        side = 'w' if len(self.move_history) % 2 == 0 else 'b'
        board_fen = self.fen.split(' ')[0] if ' ' in self.fen else self.fen
        return f"{board_fen} {side}", self.move_history
    def set_my_slot(self, slot_id, first_turn_slot_id):
        self.my_slot_id = slot_id
        self.first_turn_slot_id = first_turn_slot_id
        self.is_red = (self.my_slot_id == first_turn_slot_id)

class MultiPVSelector:
    def __init__(self):
        self.pv_data = []
        self.info_regex = re.compile(r"info.*multipv (\d+).*score (cp|mate) (-?\d+).*pv (.+)")

    def clear(self):
        self.pv_data.clear()

    def parse_line(self, line_str):
        match = self.info_regex.search(line_str)
        if match:
            pv_id = int(match.group(1))
            score_type = match.group(2)
            score_val = int(match.group(3))
            pv_line = match.group(4).split()
            
            if pv_line:
                first_move = pv_line[0]
                actual_score = 99999 if (score_type == "mate" and score_val > 0) else \
                              -99999 if (score_type == "mate" and score_val < 0) else score_val

                updated = False
                for i, item in enumerate(self.pv_data):
                    if item['pv_id'] == pv_id:
                        self.pv_data[i] = {"pv_id": pv_id, "move": first_move, "score": actual_score, "mate": score_type == "mate", "mate_val": score_val}
                        updated = True
                        break
                if not updated:
                    self.pv_data.append({"pv_id": pv_id, "move": first_move, "score": actual_score, "mate": score_type == "mate", "mate_val": score_val})

    def select_move(self):
        if not self.pv_data: 
            return None
            
        # Sắp xếp các nhánh từ điểm cao nhất đến thấp nhất
        self.pv_data.sort(key=lambda x: x['score'], reverse=True)
        
        # 1. Nếu phát hiện có sát cục thắng (Mate), dứt điểm ngay lập tức
        if self.pv_data[0]['mate'] and self.pv_data[0]['mate_val'] > 0:
            print(f"[SMART-PV] 🔥 Dứt điểm sát cục: {self.pv_data[0]['move']}")
            return self.pv_data[0]['move']

        best_score = self.pv_data[0]['score']

        # 2. Xử lý theo điểm âm/dương để chặn đứng lỗi chọn nước đi ngẫu nhiên bừa bãi
        # - Nếu điểm < 50: Thế cờ lép vế (điểm âm) hoặc cờ hòa hoãn, sát nút. Buộc phải đi nước tối ưu nhất để phòng thủ.
        # - Nếu điểm > 350: Thế cờ ưu lớn sắp thắng. Buộc đi nước tối ưu nhất để kết liễu trận đấu nhanh chóng.
        if best_score < 50 or best_score > 350:
            print(f"[SMART-PV] 🎯 Trạng thái đặc biệt ({best_score} cp). Chọn nước tốt nhất: {self.pv_data[0]['move']}")
            return self.pv_data[0]['move']

        # 3. Chỉ cho phép đa dạng hóa (random) khi điểm dương ổn định (từ +50 đến +350 cp)
        viable_moves = [item['move'] for item in self.pv_data if best_score - item['score'] <= 30]

        if len(viable_moves) > 1:
            chosen = random.choice(viable_moves)
            print(f"[SMART-PV] 🎲 Ưu thế ổn định ({best_score} cp). Ngẫu nhiên: {chosen} trong {len(viable_moves)} nhánh.")
            return chosen
        else:
            print(f"[SMART-PV] 🎯 Chọn nước đi tối ưu nhất: {self.pv_data[0]['move']}")
            return self.pv_data[0]['move']

class PikafishBot:
    def __init__(self):
        self.conn = Conn()
        self.board = XiangqiBoardTracker()
        self.multi_pv_selector = MultiPVSelector()  
        self._move_lock = threading.Lock()  
        self.engine = None
        self.ws = None
        self.connected = False
        self.logged_in = False
        self.in_game = False
        self._joining_table = False
        self._last_quick_play_time = 0
        self._QUICK_PLAY_INTERVAL = 10
        self.bet_amts = []
        self._resolved_bet_id = None
        self._bet_amts_loaded = False
        self.fixed_pawn_positions = set()
        self.last_action_timestamp = time.time()
        self._latest_bestmove = None
        self._mate_status = None
        self._mate_regex = re.compile(r"score mate (-?\d+)")
        
        self._ready_sent = False 

        self.cp_book = {}
        self.cp_book_file = "cp_book.json"
        self._load_cp_book()
        self._init_engine()

    def _load_cp_book(self):
        if os.path.exists(self.cp_book_file):
            try:
                with open(self.cp_book_file, 'r', encoding='utf-8') as f:
                    self.cp_book = json.load(f)
                print(f"[CP-BOOK] 📚 Đã tải {len(self.cp_book)} thế cờ đã học.")
            except:
                self.cp_book = {}

    def _save_cp_book(self):
        try:
            with open(self.cp_book_file, 'w', encoding='utf-8') as f:
                json.dump(self.cp_book, f, indent=4)
        except Exception as e:
            print(f"[CP-BOOK] Lỗi lưu file: {e}")

    def _init_engine(self):
        possible_paths = [
            os.path.expanduser("~/pikafish"),
            os.path.expanduser("~/Android/pikafish-armv8"),
            "/data/data/com.termux/files/home/pikafish",
            "./pikafish"
        ]
        pikafish_path = next((p for p in possible_paths if os.path.isfile(p) and os.access(p, os.X_OK)), None)
        if not pikafish_path: return

        try:
            self._engine_proc = subprocess.Popen(
                [pikafish_path], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1
            )
            
            def consume_stderr(proc):
                try:
                    while proc.poll() is None:
                        if not proc.stderr.readline(): break
                except: pass
            threading.Thread(target=consume_stderr, args=(self._engine_proc,), daemon=True).start()

            def consume_stdout_and_filter(proc):
                try:
                    while proc.poll() is None:
                        line = proc.stdout.readline()
                        if not line: break
                        line_str = line.strip()
                        self.multi_pv_selector.parse_line(line_str)
                        
                        if "score mate" in line_str and "lowerbound" not in line_str and "upperbound" not in line_str:
                            match = self._mate_regex.search(line_str)
                            if match:
                                val = int(match.group(1))
                                if val > 0: self._mate_status = f"WIN_IN_{val}"
                                elif val < 0: self._mate_status = f"LOSE_IN_{abs(val)}"
                        
                        if line_str.startswith("bestmove"):
                            self._latest_bestmove = line_str
                except: pass
            threading.Thread(target=consume_stdout_and_filter, args=(self._engine_proc,), daemon=True).start()

            self._fsf_cmd("uci")
            self._fsf_cmd("setoption name Threads value 2")
            self._fsf_cmd("setoption name Hash value 512")
            self._fsf_cmd("setoption name MultiPV value 2")
            time.sleep(2)
            
            nnue_path = os.path.expanduser("~/pikafish.nnue")
            if not os.path.isfile(nnue_path):
                nnue_path = os.path.join(os.path.dirname(pikafish_path), "pikafish.nnue")
            if os.path.isfile(nnue_path):
                self._fsf_cmd(f"setoption name EvalFile value {nnue_path}")
                self._fsf_cmd("setoption name UseNNUE value true")
            else:
                self._fsf_cmd("setoption name UseNNUE value false")
            self._fsf_cmd("isready")
            self.engine = True
            print(f"[ENGINE] ✅ Sẵn sàng (MultiPV=2, Hash=512).")
        except Exception as e:
            print(f"[ENGINE] ❌ Lỗi khởi tạo: {e}")

    def _fsf_cmd(self, text):
        if getattr(self, '_engine_proc', None) and self._engine_proc.poll() is None:
            self._engine_proc.stdin.write(text + "\n")
            self._engine_proc.stdin.flush()

    def get_best_move(self, fen, moves, fixed_positions=None, time_limit=4000):
        try:
            if not getattr(self, '_engine_proc', None) or self._engine_proc.poll() is not None: return None
            self.multi_pv_selector.clear() 
            if fixed_positions: return self._get_move_avoiding_fixed(fen, moves, fixed_positions)
            pos_cmd = f"position fen {fen}"
            if moves: pos_cmd += " moves " + " ".join(moves)
            self._fsf_cmd(pos_cmd)
            self._fsf_cmd(f"go movetime {time_limit}") 
            return self._read_bestmove(timeout=time_limit/1000 + 1)
        except Exception as e: print(f"[ENGINE] Lỗi tính toán: {e}")
        return None

    def _read_bestmove(self, timeout=5):
        _go_start = time.time()
        self._latest_bestmove = None 
        self._mate_status = None     
        while True:
            if self._engine_proc.poll() is not None: return None
            if self._latest_bestmove: return self._latest_bestmove
            if self._mate_status and self._mate_status.startswith("WIN_IN_"):
                print(f"[MATE-FAST] ⚡️ Phát hiện Mate! Ngắt Engine để dứt điểm tức thì...")
                self._fsf_cmd("stop")
                time.sleep(1)
                if self._latest_bestmove: return self._latest_bestmove
            if time.time() - _go_start > timeout:
                self._fsf_cmd("stop")
                time.sleep(1)
                if self._latest_bestmove: return self._latest_bestmove
                break
            time.sleep(1)
        return None

    def _get_move_avoiding_fixed(self, fen, moves, fixed_positions):
        pos_cmd = f"position fen {fen}"
        if moves: pos_cmd += " moves " + " ".join(moves)
        self._fsf_cmd(pos_cmd)
        self._latest_bestmove = None
        self._mate_status = None
        self._fsf_cmd("go movetime 2500")
        _wait_start = time.time()
        while time.time() - _wait_start < 2:
            if self._latest_bestmove: break
            time.sleep(0.5)
        self._fsf_cmd("stop")
        time.sleep(0.5)
        if self._latest_bestmove: return self._latest_bestmove
        return None

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
            time.sleep(0.5)
        return self.connected

    def _on_open(self, ws):
        self.connected = True
        self.last_action_timestamp = time.time()
        self._send_login()

    def _on_message(self, ws, message):
        if isinstance(message, bytes): self._handle_binary_message(message)
    def _on_error(self, ws, error): pass
    def _on_close(self, ws, code, msg):
        self.connected = False
        self.logged_in = False
        self.in_game = False
        self._joining_table = False
        self._bet_amts_loaded = False
        self._resolved_bet_id = None
        self.bet_amts = []
        self.fixed_pawn_positions = set()
        self._ready_sent = False  
        self.board.reset()

    def send_message(self, cmd, data=b''):
        if self.ws and self.connected:
            try: self.ws.send(self.conn.pack(cmd, data), opcode=0x2)
            except: pass

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

    def send_list_bet_amt(self): self.send_message("LIST_BET_AMT")

    def resolve_bet_amt_id(self):
        if not self.bet_amts: return None
        for ba in self.bet_amts:
            if ba['value'] == BOT_BET_XU: return ba['id']
        lower = [ba for ba in self.bet_amts if 0 < ba['value'] <= BOT_BET_XU]
        if lower: return max(lower, key=lambda x: x['value'])['id']
        return 0

    def send_create_table(self):
        now = time.time()
        if now - self._last_quick_play_time < self._QUICK_PLAY_INTERVAL: return
        self._last_quick_play_time = now
        bet_amt_id = self._resolved_bet_id if self._resolved_bet_id is not None else self.resolve_bet_amt_id()
        if bet_amt_id is None: return
        args = [
            ("matchDuration", str(BOT_MATCH_DURATION)),
            ("turnDuration", str(BOT_TURN_DURATION)),
            ("accDuration", str(BOT_ACC_DURATION)),
            ("blockSoftware", str(BOT_BLOCK_SOFTWARE)),
        ]
        data = bytearray()
        data.extend(self.conn.pack_byte(bet_amt_id))       
        data.extend(self.conn.pack_byte(len(args)))        
        for arg_name, arg_value in args:
            data.extend(self.conn.pack_ascii(arg_name))    
            data.extend(self.conn.pack_string(arg_value))  
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

    def send_ready(self, is_ready=1000):
        if self.board.is_playing or self._ready_sent: return
        self._ready_sent = True 
        print("[GAME] ⏳ Gửi trạng thái READY (Chỉ gửi duy nhất 1 lần)...")
        data = bytearray()
        data.extend(self.conn.pack_byte(is_ready))
        self.send_message("SET_READY", bytes(data))

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
        except Exception as e: print(f"[RECV ERROR] {e}")

    def _handle_login_response(self, msg):
        if msg.read_byte() == 0:
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
                self._joining_table = False
                self.in_game = True
                self.last_action_timestamp = time.time()
                self._ready_sent = False 
                def delay_initial_ready():
                    time.sleep(5.0)  
                    self.send_ready(1)
                threading.Thread(target=delay_initial_ready, daemon=True).start()
            elif not self.in_game:
                self._bet_amts_loaded = False
                self._resolved_bet_id = None
                self.send_list_bet_amt()
            else:
                self.in_game = False
                self._joining_table = False
                self._ready_sent = False
                self.board.reset()

    def _handle_quick_play_response(self, msg):
        if msg.read_byte() == 0:
            self.in_game = True  
            self._joining_table = True
            table_path = msg.read_ascii()
            def async_join():
                time.sleep(0.5)
                self.send_enter_place(path=table_path, mode=1)
            threading.Thread(target=async_join, daemon=True).start()

    def _handle_list_bet_amt_response(self, msg):
        if msg.read_byte() != 0: return
        count = msg.read_byte()
        self.bet_amts = [{"id": i, "value": msg.read_int()} for i in range(count)]
        self._resolved_bet_id = self.resolve_bet_amt_id()
        self._bet_amts_loaded = True

    def _handle_create_rule_response(self, msg):
        if msg.read_byte() == 0:
            self.in_game = True  
            self._joining_table = True
            table_path = msg.read_ascii()
            def async_join():
                time.sleep(0.5)
                self.send_enter_place(path=table_path, mode=1)
            threading.Thread(target=async_join, daemon=True).start()
        else: self._joining_table = False

    def _handle_slot_changed(self, msg):
        try:
            _ = msg.read_string()
            slot_id = msg.read_byte()
            msg.read_long(); msg.read_long(); msg.read_byte(); msg.read_short(); msg.read_ascii(); msg.read_byte(); msg.read_byte()
            player_id = msg.read_long()
            if player_id == CURRENT_PLAYER_ID: 
                self.board.my_slot_id = slot_id
            else:
                if player_id > 0 and not self.board.is_playing and not self._ready_sent:
                    def delay_ready_on_player():
                        time.sleep(5.0)  
                        self.send_ready(1)
                    threading.Thread(target=delay_ready_on_player, daemon=True).start()
        except: pass

    def _handle_start_match(self, msg):
        print(f"[GAME] 🎮 Trận chiến bắt đầu!")
        self.board.reset()
        self.fixed_pawn_positions.clear()
        self.board.is_playing = True
        self.in_game = True
        self._joining_table = False
        self.last_action_timestamp = time.time()

        try:
            player_count = msg.read_byte()
            for _ in range(player_count): msg.read_byte(); msg.read_int()
            piece_count = msg.read_byte()
            board_pieces = []
            for _ in range(piece_count):
                raw_sid = msg.read_byte(); raw_face = msg.read_byte(); pos = msg.read_byte(); is_open = msg.read_byte()
                board_pieces.append((self._decode_piece_id(raw_sid), self._decode_piece_id(raw_face), pos, is_open))

            msg.read_byte(); mystery_count = msg.read_byte()
            for _ in range(mystery_count): msg.read_byte()
            msg.read_byte(); msg.read_byte()

            first_turn_slot_id = msg.read_byte()
            my_slot_id = msg.read_byte()
            if my_slot_id < 0 or my_slot_id == 255:
                my_slot_id = self.board.my_slot_id if self.board.my_slot_id >= 0 else first_turn_slot_id

            self.board.set_my_slot(my_slot_id, first_turn_slot_id)

            for sid, face, position, is_open in board_pieces:
                piece_type = int(face[1]) if len(face) > 1 else 0
                if piece_type == 7 and position not in STANDARD_PAWN_POSITIONS:
                    self.fixed_pawn_positions.add(position)

            self.board.fen = self._build_fen_from_pieces(board_pieces)
            if my_slot_id == first_turn_slot_id:
                self.board.is_my_turn = True
                threading.Thread(target=self._make_auto_move, daemon=True).start()
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
        except Exception as e: print(f"[MOVE ERROR] {e}")

    def _handle_play_response(self, msg):
        if msg.read_byte() != 0:
            if self.board.move_history: self.board.move_history.pop()
            self.board.is_my_turn = True

    def _handle_set_turn(self, msg):
        try:
            slot_id = msg.read_byte()
            if slot_id != -1 and self.board.is_playing:  
                was_my_turn = self.board.is_my_turn
                self.board.is_my_turn = (slot_id == self.board.my_slot_id)
                self.last_action_timestamp = time.time()
                if self.board.is_my_turn and not was_my_turn:
                    threading.Thread(target=self._make_auto_move, daemon=True).start()
        except: pass

    def _handle_gameover(self, msg):
        print("[GAME] 🏁 Trận đấu kết thúc.")
        self.fixed_pawn_positions.clear()
        self.board.reset()
        self.board.is_playing = False
        self.board.is_my_turn = False
        self.in_game = True  
        self._joining_table = False
        self._ready_sent = False 
        self.last_action_timestamp = time.time()
        
        if getattr(self, '_engine_proc', None) and self._engine_proc.poll() is None:
            self._fsf_cmd("ucinewgame")
            self._fsf_cmd("isready")

        def delay_ready():
            time.sleep(3.0)
            self.send_ready(1)
        threading.Thread(target=delay_ready, daemon=True).start()

    def _make_auto_move(self):
        if not self.board.is_my_turn or not self.board.is_playing: return
        if not self._move_lock.acquire(blocking=False): return
        try:
            if not self.board.is_my_turn or not self.board.is_playing: return
            if not getattr(self, '_engine_proc', None) or self._engine_proc.poll() is not None:
                self._init_engine()
                if not self.engine: return

            fen, moves = self.board.get_current_fen()
            fixed = self.fixed_pawn_positions if self.fixed_pawn_positions else None
            book_key = f"{fen}_{'_'.join(moves)}"

            is_in_book = book_key in self.cp_book
            book_move = self.cp_book[book_key]["move"] if is_in_book else None
            book_score = self.cp_book[book_key]["score"] if is_in_book else None

            if is_in_book:
                print(f"[CP-BOOK] 📖 Đã có trong Book (Nước cũ: {book_move}, CP: {book_score}). Đang kiểm tra nước CP cao hơn...")
                raw_bestmove_line = self.get_best_move(fen, moves, fixed_positions=fixed, time_limit=1500)
            else:
                print(f"[CP-BOOK] 🔍 Chưa có trong Book. Engine đang suy nghĩ sâu (4s)...")
                raw_bestmove_line = self.get_best_move(fen, moves, fixed_positions=fixed, time_limit=3000)

            if not raw_bestmove_line: 
                self.board.is_my_turn = False
                return
            parts = raw_bestmove_line.split()
            if len(parts) < 2: 
                self.board.is_my_turn = False
                return
            engine_move = parts[1]

            smart_move = engine_move
            best_score = 0
            if self.multi_pv_selector.pv_data:
                self.multi_pv_selector.pv_data.sort(key=lambda x: x['score'], reverse=True)
                best_score = self.multi_pv_selector.pv_data[0]['score']
                if engine_move not in ["(none)", "0000"]:
                    smart_move = self.multi_pv_selector.select_move() or engine_move

            if smart_move in ["(none)", "0000"]:
                print("\n[HỆ THỐNG TÀN CUỘC] ⚠️ Hết nước hợp lệ.")
                self.board.is_my_turn = False
                return

            if is_in_book:
                if smart_move != book_move and best_score > book_score + 15:
                    print(f"[CP-BOOK] 🚀 Tìm thấy nước ưu việt hơn! Cập nhật: {book_move}({book_score}) -> {smart_move}({best_score})")
                    self.cp_book[book_key] = {"move": smart_move, "score": best_score}
                    self._save_cp_book()
                    best_move = smart_move
                else:
                    print(f"[CP-BOOK] ✅ Nước cũ vẫn tốt nhất. Giữ nguyên: {book_move}")
                    best_move = book_move
                    time.sleep(1.0)
            else:
                self.cp_book[book_key] = {"move": smart_move, "score": best_score}
                self._save_cp_book()
                print(f"[CP-BOOK] 💾 Đã lưu nước đi {smart_move} (CP: {best_score}) vào Book.")
                best_move = smart_move

            try:
                source_pos, target_pos = self.board.engine_move_to_pos(best_move)
                time.sleep(0.2)
                if self.board.is_my_turn and self.board.is_playing:
                    print(f"-> Hành động: Xuất quân: {best_move}")
                    self.send_play(source_pos, target_pos)
                    if not self.board.move_history or self.board.move_history[-1] != best_move:
                        self.board.move_history.append(best_move)
                    self.board.is_my_turn = False
            except Exception as e: 
                print(f"[BOT ERROR] Dịch tọa độ lỗi: {e}")
                self.board.is_my_turn = False
        finally:
            self._move_lock.release()

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
                if self.connected and self.board.is_playing:
                    if time.time() - self.last_action_timestamp > 180:
                        if self.ws: self.ws.close()
                        time.sleep(2)

                if not self.connected:
                    if not fetch_session_info():
                        time.sleep(5); continue
                    self.logged_in = False
                    self.in_game = False
                    self._joining_table = False
                    self._bet_amts_loaded = False
                    self._resolved_bet_id = None
                    self.bet_amts = []
                    self.fixed_pawn_positions = set()
                    self._ready_sent = False
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
                time.sleep(3)
            except KeyboardInterrupt: break
            except: time.sleep(5)

    def cleanup(self):
        proc = getattr(self, '_engine_proc', None)
        if proc:
            try: 
                if proc.poll() is None:
                    proc.stdin.write("quit\n"); proc.stdin.flush(); proc.wait(timeout=2)
            except:
                try: proc.terminate()
                except: pass
        if self.ws:
            try: self.ws.close()
            except: pass

if __name__ == "__main__":
    bot = PikafishBot()
    def signal_handler(sig, frame): bot.cleanup(); sys.exit(0)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    try: bot.run()
    finally: bot.cleanup()
