#!/usr/bin/env python3
"""
Xiangqi Bot - gamevh.net - GitHub Actions Edition
Tự động lấy token, chạy 24/7 với auto-reconnect
Tích hợp Logic: Tự động né khi vào bàn của đối thủ gài cờ (Blacklist) khi chưa bắt đầu trận.
Auto-search bàn: Tự động tìm bàn liên tục khi ở ngoài sảnh.
Pikafish: Cấu hình Threads + Hash Table để tối ưu hiệu suất.
"""

import struct
import threading
import time
import sys
import os
import json
import signal
import re
import requests

# ==================== CẤU HÌNH TỪ ENVIRONMENT VARIABLES ====================
COOKIE = os.environ.get(
    'GAMEVH_COOKIE',
    "_ga=GA1.2.1074447710.1773877026; "
    "memberName=4F0D0D2A316B7A164DB2A42CF7CF85FE; "
    "memberPassword=E71A8D5F227140577E4376EA88F92797; "
    "_gid=GA1.2.1678480358.1780056051; "
    "__zlcmid=1XmoXt5lKumz8jz; "
    "JSESSIONID=node0d8r2bm8321rpqr4gx19uxq1270228023.node0; "
    "clientIp=F31E20F28AD2B3BEEC8A5F858DEE61B8ECDFCF0D9D9092333E4D7D21A246FF94"
)
NICKNAME = os.environ.get('GAMEVH_NICKNAME', 'nguyen05522')
PLAYER_ID = int(os.environ.get('GAMEVH_PLAYER_ID', '65692738'))
GAME_ID = os.environ.get('GAMEVH_GAME_ID', 'xiangqi')
PLACE_PATH = os.environ.get('GAMEVH_PLACE_PATH', 'Lobby.xiangqi.0')
BOT_DEPTH = int(os.environ.get('BOT_DEPTH', '20'))
AUTO_SEARCH_INTERVAL = int(os.environ.get('AUTO_SEARCH_INTERVAL', '3'))  # Tìm bàn mỗi 3s khi ở sảnh

# ========== CẤU HÌNH PIKAFISH ==========
PIKAFISH_THREADS = int(os.environ.get('PIKAFISH_THREADS', '4'))  # Số luồng engine (mặc định 4)
PIKAFISH_HASH_MB = int(os.environ.get('PIKAFISH_HASH_MB', '256'))  # Hash table size (MB) (mặc định 256MB)

WS_URL = "wss://gamevh.net/ws/gameServer"
TOKEN = 0
BLACKLIST_FILE = "blacklist.txt"

# Session state (mutable dict để tránh global declaration issue)
_SESSION_STATE = {'cookie': COOKIE, 'nickname': NICKNAME}

# ==================== COMMAND CODES ====================
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

# ==================== BINARY PROTOCOL ====================
class Conn:
    def __init__(self): self.offset = 0
    def read_byte(self, buf, o): return struct.unpack_from('>b', buf, o)[0]
    def read_ubyte(self, buf, o): return struct.unpack_from('>B', buf, o)[0]
    def read_short(self, buf, o): return struct.unpack_from('>h', buf, o)[0]
    def read_int(self, buf, o): return struct.unpack_from('>i', buf, o)[0]
    def read_long(self, buf, o): return struct.unpack_from('>q', buf, o)[0]
    def read_ascii(self, buf, o):
        length = self.read_byte(buf, o)
        if length < 0: length += 256
        o += 1
        s = buf[o:o+length].decode('ascii', errors='replace')
        return s, o + length
    def read_string(self, buf, o):
        char_count = self.read_short(buf, o)
        o += 2
        s = buf[o:o+char_count*2].decode('utf-16-be', errors='replace')
        return s, o + char_count*2
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
    def pack_byte(self, v): return struct.pack('>b', v)
    def pack_ubyte(self, v): return struct.pack('>B', v)
    def pack_short(self, v): return struct.pack('>h', v)
    def pack_int(self, v): return struct.pack('>i', v)
    def pack_ascii(self, v):
        enc = v.encode('ascii')[:255]
        return struct.pack('>b', len(enc)) + enc
    def pack_string(self, v):
        enc = v.encode('utf-16-be')
        return struct.pack('>h', len(enc)//2) + enc

class InboundMessage:
    def __init__(self, data):
        self.data = bytes(data); self.offset = 0
        self.command = self._parse_command()
    def _parse_command(self):
        length = self.read_byte()
        if length < 0:
            cmd = self.data[self.offset:self.offset+(-length)].decode('ascii', errors='replace')
            self.offset += (-length); return cmd
        else:
            next_byte = self.data[self.offset] & 0xFF; self.offset += 1
            cmd_id = (length << 8) | next_byte
            return CMD_NAMES.get(cmd_id, str(cmd_id))
    def read_byte(self):
        v = struct.unpack_from('>b', self.data, self.offset)[0]; self.offset += 1; return v
    def read_ubyte(self):
        v = struct.unpack_from('>B', self.data, self.offset)[0]; self.offset += 1; return v
    def read_short(self):
        v = struct.unpack_from('>h', self.data, self.offset)[0]; self.offset += 2; return v
    def read_int(self):
        v = struct.unpack_from('>i', self.data, self.offset)[0]; self.offset += 4; return v
    def read_long(self):
        v = struct.unpack_from('>q', self.data, self.offset)[0]; self.offset += 8; return v
    def read_ascii(self):
        length = self.read_byte()
        if length < 0: length += 256
        s = self.data[self.offset:self.offset+length].decode('ascii', errors='replace')
        self.offset += length; return s
    def read_string(self):
        cc = self.read_short(); s = self.data[self.offset:self.offset+cc*2].decode('utf-16-be', errors='replace')
        self.offset += cc*2; return s
    def remaining(self): return len(self.data) - self.offset

# ==================== BOARD TRACKER ====================
class XiangqiBoardTracker:
    INITIAL_FEN = "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w"
    def __init__(self):
        self.fen = self.INITIAL_FEN; self.move_history = []
        self.my_slot_id = -1; self.first_turn_slot_id = 0
        self.is_my_turn = False; self.is_playing = False; self.is_red = None
    def reset(self):
        self.fen = self.INITIAL_FEN; self.move_history = []
        self.is_my_turn = False; self.is_playing = False; self.is_red = None
    @staticmethod
    def pos_to_engine_move(s, t):
        return f"{chr(ord('a')+s%9)}{s//9}{chr(ord('a')+t%9)}{t//9}"
    @staticmethod
    def engine_move_to_pos(m):
        return int(m[1])*9+ord(m[0])-ord('a'), int(m[3])*9+ord(m[2])-ord('a')
    def apply_move(self, s, t): self.move_history.append(self.pos_to_engine_move(s, t))
    def get_current_fen(self): return self.fen, self.move_history
    def set_my_slot(self, sid, ftid):
        self.my_slot_id = sid; self.first_turn_slot_id = ftid
        self.is_red = (sid == ftid)

# ==================== ENGINE WRAPPER ====================
class PikafishBot:
    def __init__(self, depth=15):
        self.conn = Conn(); self.board = XiangqiBoardTracker()
        self.engine = None; self.depth = depth; self.ws = None
        self.connected = False; self.logged_in = False; self.in_game = False
        self._engine_mode = None
        self.table_players = {}  # {slot_id: nickname}
        self.table_master_slot = -1  # Lưu ID ghế của chủ bàn hiện tại
        self.in_lobby = False  # Trạng thái ở sảnh
        self.auto_search_thread = None  # Thread tự động tìm bàn
        self._init_engine()
        self._load_blacklist()

    def _init_engine(self):
        try:
            from pikafish_terminal.engine import PikafishEngine
            from pikafish_terminal.difficulty import create_custom_difficulty
            
            # Tạo custom difficulty với cấu hình threads và hash
            difficulty = create_custom_difficulty(
                depth=self.depth,
                threads=PIKAFISH_THREADS,
                hash_mb=PIKAFISH_HASH_MB
            )
            self.engine = PikafishEngine(difficulty=difficulty)
            self.engine.new_game()
            self._engine_mode = 'pikafish_terminal'
            
            print(f"[ENGINE] ✅ Pikafish terminal initialized")
            print(f"[ENGINE]    Depth: {self.depth}")
            print(f"[ENGINE]    Threads: {PIKAFISH_THREADS}")
            print(f"[ENGINE]    Hash: {PIKAFISH_HASH_MB}MB")
            return
        except TypeError:
            # Nếu pikafish_terminal không hỗ trợ threads/hash_mb, thử cách khác
            try:
                from pikafish_terminal.engine import PikafishEngine
                from pikafish_terminal.difficulty import create_custom_difficulty
                
                difficulty = create_custom_difficulty(depth=self.depth)
                self.engine = PikafishEngine(difficulty=difficulty)
                self.engine.new_game()
                self._engine_mode = 'pikafish_terminal'
                
                # Cố gắng cấu hình engine sau khi tạo
                try:
                    self.engine.setoption("Threads", str(PIKAFISH_THREADS))
                    self.engine.setoption("Hash", str(PIKAFISH_HASH_MB))
                except:
                    pass
                
                print(f"[ENGINE] ✅ Pikafish terminal (depth={self.depth})")
                print(f"[ENGINE]    Threads: {PIKAFISH_THREADS}")
                print(f"[ENGINE]    Hash: {PIKAFISH_HASH_MB}MB")
                return
            except Exception as e2:
                print(f"[ENGINE] ⚠️ pikafish-terminal (fallback): {e2}")
        except Exception as e:
            print(f"[ENGINE] ⚠️ pikafish-terminal: {e}")
        
        print("[ENGINE] ❌ Không có engine nào khả dụng!")

    def _load_blacklist(self):
        self.blacklist = set()
        if os.path.exists(BLACKLIST_FILE):
            try:
                with open(BLACKLIST_FILE, "r", encoding="utf-8") as f:
                    for line in f:
                        name = line.strip()
                        if name: self.blacklist.add(name)
                print(f"[BLACKLIST] Đã tải {len(self.blacklist)} đối thủ gài thế cờ từng thắng BOT.")
            except Exception as e:
                print(f"[BLACKLIST] Lỗi đọc file: {e}")
        else:
            with open(BLACKLIST_FILE, "w", encoding="utf-8") as f: pass

    def _add_to_blacklist(self, nickname):
        if nickname and nickname != NICKNAME and nickname not in self.blacklist:
            self.blacklist.add(nickname)
            try:
                with open(BLACKLIST_FILE, "a", encoding="utf-8") as f:
                    f.write(nickname + "\n")
                print(f"[BLACKLIST] 🛑 Đã thêm '{nickname}' vào danh sách đen do nghi vấn gài thế cờ.")
            except Exception as e:
                print(f"[BLACKLIST] Lỗi ghi file: {e}")

    def _check_and_escape_blacklist(self):
        """Logic kiểm tra Blacklist thông minh theo yêu cầu của bạn"""
        # Điều kiện 1: Nếu trận đấu đang chơi rồi thì CỨ CHƠI TIẾP, KHÔNG THOÁT
        if self.board.is_playing:
            return False
            
        # Điều kiện 2: Nếu BOT đang là CHỦ BÀN thì KHÔNG THOÁT (vì đối thủ vào bàn mình không gài thế cờ lỗi được)
        if self.board.my_slot_id == self.table_master_slot and self.board.my_slot_id != -1:
            return False

        # Điều kiện 3: Trận chưa bắt đầu + Mình là khách + Gặp người trong danh sách đen làm chủ bàn -> THOÁT NGAY
        for sid, name in self.table_players.items():
            if name in self.blacklist:
                # Đảm bảo người thuộc blacklist này chính là CHỦ BÀN gài thế cờ
                if sid == self.table_master_slot:
                    print(f"[BLACKLIST] 🚨 Né gài thế cờ! Chủ bàn '{name}' nằm trong danh sách đen. Đang tự động rời bàn...")
                    self.send_surrender() # Thoát bàn
                    return True
        return False

    def _start_auto_search(self):
        """Bắt đầu luồng tự động tìm bàn khi ở sảnh"""
        if self.auto_search_thread and self.auto_search_thread.is_alive():
            return  # Đã có luồng chạy rồi
        
        def auto_search_loop():
            print(f"[AUTO-SEARCH] ✅ Bắt đầu tìm bàn tự động (mỗi {AUTO_SEARCH_INTERVAL}s)")
            while self.in_lobby and self.connected and not self.in_game:
                try:
                    print(f"[AUTO-SEARCH] 🔍 Tìm bàn...")
                    self.send_quick_play()
                    time.sleep(AUTO_SEARCH_INTERVAL)
                except Exception as e:
                    print(f"[AUTO-SEARCH] ❌ Error: {e}")
                    time.sleep(AUTO_SEARCH_INTERVAL)
            print(f"[AUTO-SEARCH] ⛔ Dừng tìm bàn (in_lobby={self.in_lobby}, in_game={self.in_game})")
        
        self.auto_search_thread = threading.Thread(target=auto_search_loop, daemon=True)
        self.auto_search_thread.start()

    def _stop_auto_search(self):
        """Dừng tìm bàn tự động"""
        self.in_lobby = False
        if self.auto_search_thread and self.auto_search_thread.is_alive():
            print("[AUTO-SEARCH] ⛔ Dừng luồng tìm bàn")

    def get_best_move(self, fen, moves):
        try:
            if self._engine_mode == 'pikafish_terminal' and self.engine:
                return self.engine.best_move(fen, moves)
            else:
                print("[ENGINE] ❌ No engine!"); return None
        except Exception as e:
            print(f"[ENGINE] ❌ Error: {e}"); return None
    def connect(self):
        import websocket; websocket.enableTrace(False)
        self.ws = websocket.WebSocketApp(
            WS_URL, cookie=_SESSION_STATE['cookie'],
            on_open=self._on_open, on_message=self._on_message,
            on_error=self._on_error, on_close=self._on_close,
            header={"Origin": "https://gamevh.net"})
        self.ws_thread = threading.Thread(target=self._run_ws, daemon=True)
        self.ws_thread.start()
        for _ in range(50):
            if self.connected: break
            time.sleep(0.2)
        return self.connected
    def _run_ws(self):
        try: self.ws.run_forever(ping_interval=25, ping_timeout=10)
        except Exception as e: print(f"[WS] run_forever error: {e}")
    def _on_open(self, ws): print("[WS] ✅ Connected!"); self.connected = True; self._send_login()
    def _on_message(self, ws, msg):
        if isinstance(msg, bytes): self._handle_binary_message(msg)
        else: print(f"[WS] Text: {msg[:200]}")
    def _on_error(self, ws, error): print(f"[WS] ❌ Error: {error}")
    def _on_close(self, ws, code, msg): print(f"[WS] 🔌 Closed: code={code} msg={msg}"); self.connected = False
    def send_message(self, cmd, data=b''):
        if self.ws and self.connected:
            try:
                msg = self.conn.pack(cmd, data); self.ws.send(msg, opcode=0x2)
                cn = cmd if isinstance(cmd, str) else CMD_NAMES.get(cmd, str(cmd))
                print(f"[SEND] {cn} ({len(msg)} bytes)")
            except Exception as e: print(f"[SEND] ❌ {e}")
    def _send_login(self):
        data = bytearray()
        data.extend(self.conn.pack_ascii(NICKNAME))
        data.extend(self.conn.pack_int(TOKEN))
        data.extend(self.conn.pack_ascii("5.0.2"))
        data.extend(self.conn.pack_ascii(""))
        data.extend(self.conn.pack_ascii(GAME_ID))
        data.extend(self.conn.pack_byte(1))
        self.send_message("LOGIN", bytes(data))
        print(f"[LOGIN] nickname={NICKNAME}, token={TOKEN}")
    def send_enter_place(self, path=PLACE_PATH, mode=1):
        data = bytearray()
        data.extend(self.conn.pack_ascii(path))
        data.extend(self.conn.pack_string(""))
        data.extend(self.conn.pack_byte(mode))
        self.send_message("ENTER_PLACE", bytes(data))
        print(f"[ENTER_PLACE] path={path}, mode={mode}")
    def send_quick_play(self, room_id="", bet_amt_id=-1):
        data = bytearray()
        data.extend(self.conn.pack_ascii(room_id))
        data.extend(self.conn.pack_byte(bet_amt_id))
        self.send_message("QUICK_PLAY", bytes(data))
        print(f"[QUICK_PLAY] roomId={room_id}, betAmtId={bet_amt_id}")
    def send_play(self, s, t):
        data = bytearray()
        data.extend(self.conn.pack_byte(s))
        data.extend(self.conn.pack_byte(t))
        self.send_message("PLAY", bytes(data))
    def send_ping(self): self.send_message("PING")
    def send_set_ready(self): self.send_message("SET_READY")
    def send_surrender(self): self.send_message("SURRENDER")
    def _handle_binary_message(self, data):
        try:
            msg = InboundMessage(data); cmd = msg.command
            print(f"[RECV] {cmd} ({len(data)}b) {data[:20].hex()}...")
            if cmd == "PING": self._handle_ping()
            elif cmd == "LOGIN": self._handle_login_response(msg)
            elif cmd == "ENTER_PLACE": self._handle_enter_place_response(msg)
            elif cmd == "QUICK_PLAY": self._handle_quick_play_response(msg)
            elif cmd == "SLOT_IN_TABLE_CHANGED": self._handle_slot_changed(msg)
            elif cmd == "START_MATCH": self._handle_start_match(msg)
            elif cmd == "PLAY" or cmd == "502": self._handle_play_response(msg)
            elif cmd == "MOVE": self._handle_move(msg)
            elif cmd == "SET_TURN": self._handle_set_turn(msg)
            elif cmd == "GAMEOVER": self._handle_gameover(msg)
            elif cmd == "ENTER_STATE": self._handle_enter_state(msg)
            elif cmd == "PLAYER_ENTERED": self._handle_player_entered(msg)
            elif cmd == "PLAYER_EXITED": self._handle_player_exited(msg)
            elif cmd == "BROADCAST": self._handle_broadcast(msg)
            elif cmd == "ALERT": self._handle_alert(msg)
            elif cmd == "CONFIG": self._handle_config(msg)
            elif cmd == "SET_CLIENT_MODE": self._handle_set_client_mode(msg)
            else: print(f"[RECV] Unhandled: {cmd}")
        except Exception as e: print(f"[RECV] ❌ Parse error: {e}")
    def _handle_ping(self): self.send_message("PONG")
    def _handle_login_response(self, msg):
        status = msg.read_byte()
        if status != 0:
            try: err = msg.read_string()
            except: err = ""
            print(f"[LOGIN] ❌ Fail: status={status}, msg={err}"); return
        print("[LOGIN] ✅ Success!"); self.logged_in = True
        try:
            path = msg.read_string(); print(f"[LOGIN] Path: {path}")
            if path == 'REFRESH': print("[LOGIN] Server asks refresh!"); fetch_session_info(); time.sleep(1); self._send_login(); return
            try: c = msg.read_ascii();
            except: pass
            time.sleep(1); self.send_enter_place()
        except Exception as e: print(f"[LOGIN] Read error: {e}")
    def _handle_enter_place_response(self, msg):
        status = msg.read_byte()
        if status != 0:
            try: err = msg.read_string()
            except: err = "Unknown"
            print(f"[ENTER_PLACE] ❌ {err}"); return
        print("[ENTER_PLACE] ✅ Success! Bạn đã vào sảnh, bắt đầu tìm bàn...")
        self.in_lobby = True
        try: currency = msg.read_byte(); rate = msg.read_short()/10.0; print(f"[ENTER_PLACE] Currency={currency}, Rate={rate}")
        except: pass
        if not self.in_game: 
            time.sleep(0.5)
            self._start_auto_search()  # Bắt đầu tìm bàn tự động
    def _handle_quick_play_response(self, msg):
        status = msg.read_byte()
        if status != 0:
            try: err = msg.read_string()
            except: err = "Unknown"
            print(f"[QUICK_PLAY] ❌ {err}"); return
        print("[QUICK_PLAY] ✅ Found table!"); self.in_game = True; self.in_lobby = False
        self._stop_auto_search()  # Dừng tìm bàn khi tìm được bàn
        try:
            tp = msg.read_ascii(); tn = msg.read_string()
            print(f"[QUICK_PLAY] Table: {tn} ({tp})")
            cnt = msg.read_byte()
            for i in range(cnt): an = msg.read_ascii(); av = msg.read_string(); print(f"  {an}={av}")
            tt = msg.read_byte(); ba = msg.read_byte(); print(f"  tableType={tt}, betAmtId={ba}")
            time.sleep(1); self.send_enter_place(path=tp, mode=1)
        except Exception as e: print(f"[QUICK_PLAY] Read error: {e}")
    def _handle_slot_changed(self, msg):
        try:
            fn = msg.read_string(); sid = msg.read_byte(); cb = msg.read_long(); sc = msg.read_long()
            lv = msg.read_byte(); aid = msg.read_short(); av = msg.read_ascii(); tid = msg.read_byte()
            io = msg.read_byte() == 1; pid = msg.read_long(); sb = msg.read_long()
            
            is_me = (pid == PLAYER_ID)
            c = "🟢" if is_me else "👤"
            print(f"[SLOT] {c} {fn} (slot={sid}, chips={cb}, id={pid}, master_id={tid})")
            
            # Cập nhật ID ghế của chủ bàn
            if tid >= 0:
                self.table_master_slot = tid

            if is_me: 
                self.board.my_slot_id = sid; print(f"[SLOT] Me at slot {sid} (Master Slot is {self.table_master_slot})")
                # Tự check lại sau khi mình đổi chỗ
                self._check_and_escape_blacklist()
            else:
                if fn: 
                    self.table_players[sid] = fn
                    # Kiểm tra người vừa cập nhật ghế
                    self._check_and_escape_blacklist()
        except Exception as e: print(f"[SLOT] Read error: {e}")
    def _handle_start_match(self, msg):
        print("[GAME] 🎮 Match started!"); self.board.reset(); self.board.is_playing = True; self.in_game = True
        try:
            pc = msg.read_byte()
            for i in range(pc): sid = msg.read_byte(); pt = msg.read_int()
            pcc = msg.read_byte(); print(f"[GAME] Pieces: {pcc}")
            bp = []
            for i in range(pcc):
                es = msg.read_byte(); ef = msg.read_byte(); pos = msg.read_byte(); op = msg.read_byte()
                sid = self._decode_piece_id(es); face = self._decode_piece_id(ef)
                bp.append((sid, face, pos, op))
                if i < 5 or pos >= 0: print(f"  [{i}] sid={sid} face={face} pos={pos} (r{pos//9 if pos>=0 else -1}c{pos%9 if pos>=0 else -1}) open={op}")
            apr = msg.read_byte(); mc = msg.read_byte()
            for i in range(mc): mp = msg.read_byte()
            ls = msg.read_byte(); lt = msg.read_byte()
            ftsid = msg.read_byte(); msid = msg.read_byte()
            print(f"[GAME] firstTurn={ftsid}, mySlot={msid}, remain={msg.remaining()}")
            
            if msid < 0 and self.board.my_slot_id >= 0: 
                msid = self.board.my_slot_id; print(f"[GAME] ⚠️ Using known slot={msid}")
            else:
                self.board.my_slot_id = msid

            self.board.set_my_slot(msid, ftsid)
            
            # Lúc này is_playing đã lên True -> _check_and_escape_blacklist() sẽ tự trả về False không thoát nữa.
            if self._check_and_escape_blacklist():
                return

            fen = self._build_fen_from_pieces(bp, ftsid)
            self.board.fen = fen; self.board.move_history = []
            cn = "ĐỎ" if self.board.is_red else "ĐEN"
            print(f"[GAME] Slot {msid}, first={ftsid} → {cn}"); print(f"[GAME] FEN: {fen}")
            
            if msid == ftsid: 
                self.board.is_my_turn = True
                print("[GAME] 🎯 My turn! Thinking...")
                threading.Thread(target=self._make_auto_move, daemon=True).start()
            else: 
                self.board.is_my_turn = False; print("[GAME] Opponent's turn...")
        except Exception as e: print(f"[GAME] ❌ START_MATCH error: {e}"); import traceback; traceback.print_exc()
    def _build_fen_from_pieces(self, pieces, ftsid):
        board = [['.' for _ in range(9)] for _ in range(10)]
        for sid, face, pos, op in pieces:
            if pos < 0 or pos >= 90: continue
            gr = pos // 9; c = pos % 9; fr = 9 - gr
            color = face[0]; pt = int(face[1]) if len(face) > 1 else 0
            t2f = {1:'k',2:'a',3:'b',4:'r',5:'c',6:'n',7:'p'}
            fc = t2f.get(pt, '?')
            if color == 'r': fc = fc.upper()
            board[fr][c] = fc
        frs = []
        for row in board:
            fr = ""; e = 0
            for cell in row:
                if cell == '.': e += 1
                else:
                    if e > 0: fr += str(e); e = 0
                    fr += cell
            if e > 0: fr += str(e)
            frs.append(fr)
        return '/'.join(frs) + ' w'
    def _handle_move(self, msg):
        try:
            sp = msg.read_byte(); tp = msg.read_byte()
            em = self.board.pos_to_engine_move(sp, tp)
            if not self.board.move_history or self.board.move_history[-1] != em: self.board.move_history.append(em)
            print(f"[MOVE] 🏃 {sp}->{tp} = {em}"); print(f"[MOVE] History: {' '.join(self.board.move_history[-6:])}")
            try: cnt = msg.read_byte(); 
            except: pass
        except Exception as e: print(f"[MOVE] ❌ Error: {e}"); import traceback; traceback.print_exc()
    def _handle_play_response(self, msg):
        try:
            status = msg.read_byte()
            if status != 0:
                err = ""
                try: err = msg.read_string()
                except: pass
                print(f"[PLAY] ❌ Invalid: status={status}, msg={err}")
                if self.board.move_history: rm = self.board.move_history.pop(); print(f"[PLAY] Removed: {rm}")
                self.board.is_my_turn = True
            else: print("[PLAY] ✅ Move accepted")
        except Exception as e: print(f"[PLAY] ❌ Read error: {e}")
    def _handle_set_turn(self, msg):
        try:
            sid = msg.read_byte(); tt = msg.read_short()
            if sid == -2: print(f"[TURN] Countdown: {tt}"); return
            pr = msg.read_short()
            imt = (sid == self.board.my_slot_id); self.board.is_my_turn = imt
            ts = "🎯 MY TURN" if imt else f"Opponent (slot={sid})"
            print(f"[TURN] ⏱️ {ts}, timeout={tt}s, remain={pr}s")
            
            if imt and self.board.is_playing:
                print("[TURN] 🧠 Triggering auto move from SET_TURN...")
                threading.Thread(target=self._make_auto_move, daemon=True).start()
        except Exception as e: print(f"[TURN] ❌ Read error: {e}")
    def _handle_gameover(self, msg):
        print("[GAME] 🏁 Game over!")
        if not self.board.is_playing: return
        
        self.board.is_playing = False; self.in_game = False; self.board.is_my_turn = False
        try:
            cnt = msg.read_byte()
            for i in range(cnt):
                sid = msg.read_byte(); gr = msg.read_byte(); ev = msg.read_long()
                is_me = (sid == self.board.my_slot_id)
                r = "🏆 WIN" if gr == 1 else "💀 LOSE" if gr == 2 else "🤝 DRAW"
                
                if is_me: 
                    print(f"[GAME] Result: {r} (earn={ev})")
                    # Nếu BOT THUA (gr == 2), tìm xem đối thủ gài thế cờ ở slot nào để lưu tên vào danh sách đen
                    if gr == 2:
                        for opp_sid, opp_name in self.table_players.items():
                            if opp_sid != self.board.my_slot_id and opp_sid == self.table_master_slot:
                                self._add_to_blacklist(opp_name)
            
            mr = msg.read_string(); print(f"[GAME] Detail: {mr}")
        except Exception as e: print(f"[GAME] Gameover read error: {e}")
        
        self.table_players.clear()
        self.table_master_slot = -1
        
        def delay_next_match():
            print("[GAME] Quay lại sảnh, tìm bàn mới...")
            self.in_lobby = True
            time.sleep(2)
            if not self.in_game and self.connected:
                self._start_auto_search()
        threading.Thread(target=delay_next_match, daemon=True).start()

    def _handle_enter_state(self, msg):
        try: print(f"[STATE] State: {msg.read_byte()}")
        except: pass
    def _handle_player_entered(self, msg):
        try: 
            name = msg.read_string()
            print(f"[PLAYER] 👋 {name} joined")
            # Người vào xem thoải mái, không cần kích hoạt logic check thoát bàn ở đây nữa
        except: pass
    def _handle_player_exited(self, msg):
        try: 
            name = msg.read_string()
            print(f"[PLAYER] 👋 {name} left")
            for sid, n in list(self.table_players.items()):
                if n == name: del self.table_players[sid]
        except: pass
    def _handle_broadcast(self, msg):
        try: print(f"[BROADCAST] 📢 {msg.read_string()}")
        except: pass
    def _handle_alert(self, msg):
        try: print(f"[ALERT] ⚠️ {msg.read_byte()}: {msg.read_string()}")
        except: pass
    def _handle_config(self, msg):
        try:
            cnt = msg.read_byte()
            for i in range(cnt): print(f"[CONFIG] {msg.read_ascii()}={msg.read_string()}")
        except: pass
    def _handle_set_client_mode(self, msg):
        try: print(f"[MODE] Client mode: {msg.read_byte()}")
        except: pass
    def _make_auto_move(self):
        if not self.board.is_my_turn or not self.board.is_playing: return
        fen, moves = self.board.get_current_fen()
        print(f"[BOT] 🧠 Thinking..."); print(f"[BOT] FEN: {fen}")
        if moves: print(f"[BOT] Moves: {' '.join(moves[-6:])}")
        bm = self.get_best_move(fen, moves)
        if bm and bm != "(none)" and bm != "0000":
            try:
                sp, tp = self.board.engine_move_to_pos(bm)
                print(f"[BOT] ✅ Best: {bm} -> {sp}->{tp}")
                self.board.move_history.append(bm); self.board.is_my_turn = False
                time.sleep(0.3); self.send_play(sp, tp)
            except Exception as e: print(f"[BOT] ❌ Convert error: {e}")
        else: print(f"[BOT] ❌ No move! (best_move={bm})")
    def _decode_piece_id(self, eid):
        color = 'r'
        if eid < 0: eid = -eid; color = 'b'
        pt = eid >> 3; suf = eid & 7
        return f"{color}{pt}{suf if suf else ''}"
    def start_keep_alive(self):
        def kal():
            while self.connected:
                time.sleep(7)
                if self.connected:
                    try: self.send_ping()
                    except Exception as e: print(f"[KEEP-ALIVE] ❌ {e}")
        self.kat = threading.Thread(target=kal, daemon=True); self.kat.start()
        print("[KEEP-ALIVE] PING every 7s")
    def run(self):
        print("=" * 60); print("  XIANGQI BOT - gamevh.net"); print("  Engine: Pikafish"); print("  Auto-reconnect: ON"); print("  Auto-search: ON"); print("=" * 60)
        rc = 0
        while True:
            try:
                print(f"\n[0] Fetching token... (connect #{rc+1})"); fetch_session_info()
                self.logged_in = False; self.in_game = False; self.in_lobby = False; self.board.reset(); self.table_players.clear(); self.table_master_slot = -1
                print("\n[1] Connecting WebSocket...")
                if not self.connect(): print("❌ WS fail! Retry in 10s..."); time.sleep(10); rc += 1; continue
                print("✅ WS connected!"); self.start_keep_alive()
                print("\n[2] Logging in...")
                for _ in range(50):
                    if self.logged_in: break
                    time.sleep(0.2)
                if not self.logged_in: print("❌ Login fail! Retry in 10s..."); time.sleep(10); rc += 1; continue
                print("✅ Logged in!")
                print("\n[3] Entering lobby...")
                for _ in range(300):
                    if self.in_lobby: break
                    time.sleep(0.2)
                if not self.in_lobby: print("⚠️ Lobby not reached, continuing...")
                print("\n[4] Bot running. Auto-search enabled.\n")
                while self.connected: time.sleep(1)
                print(f"\n[RECONNECT] Disconnected! (#{rc+1})"); rc += 1; time.sleep(5)
            except KeyboardInterrupt: print("\n[BOT] Stopping..."); break
            except Exception as e: print(f"\n[BOT] ❌ Error: {e}"); rc += 1; time.sleep(10)
        return True
    def cleanup(self):
        self._stop_auto_search()
        if self.engine:
            try: self.engine.quit()
            except: pass
        if self.ws:
            try: self.ws.close()
            except: pass

def fetch_session_info():
    global TOKEN
    cookies = {}
    for item in _SESSION_STATE['cookie'].split("; "):
        if "=" in item: key, val = item.split("=", 1); cookies[key] = val
    session = requests.Session(); session.cookies.update(cookies)
    r = session.get("https://gamevh.net/play/xiangqi/0", headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"})
    patterns = {
        'token': r'token\s*=\s*(-?\d+)',
        'currentPlayerId': r'currentPlayerId\s*=\s*(\d+)',
        'currentPlayerNickName': r'currentPlayerNickName\s*=\s*["\']?([^"\';\n]+)',
    }
    for key, pattern in patterns.items():
        m = re.search(pattern, r.text)
        if m:
            if key == 'token': TOKEN = int(m.group(1))
            elif key == 'currentPlayerNickName': _SESSION_STATE['nickname'] = m.group(1).strip()
    for cookie in session.cookies:
        if cookie.name == 'JSESSIONID':
            _SESSION_STATE['cookie'] = re.sub(r'JSESSIONID=[^;]+', f'JSESSIONID={cookie.value}', _SESSION_STATE['cookie'])
    print(f"[SESSION] Token={TOKEN}, Nick={_SESSION_STATE['nickname']}, ID={PLAYER_ID}")

# ==================== CHẠY BOT ====================
if __name__ == "__main__":
    bot = PikafishBot(depth=BOT_DEPTH)
    def signal_handler(sig, frame):
        print("\n[SIGNAL] Stopping..."); bot.cleanup(); sys.exit(0)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    try:
        bot.run()
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback; traceback.print_exc()
    finally:
        bot.cleanup()
