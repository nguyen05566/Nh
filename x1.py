#!/usr/bin/env python3
"""
Xiangqi Bot v3 - gamevh.net (CÓ PONDER)
- Engine Pikafish + NNUE + MultiPV=3
- CP Book tự học
- PONDER: engine suy nghĩ trong lượt đối thủ, phản hồi tức thì nếu đoán đúng
- Auto filter MOVE echo, auto reconnect
"""
import struct, threading, time, sys, os, requests, re, subprocess, json

# ==================== CONFIG ====================
COOKIE = (
    "_ga=GA1.2.1268277570.1781579079; "
    "memberName=4F0D0D2A316B7A1688ED292DEE05CCD9; "
    "memberPassword=E71A8D5F227140577E4376EA88F92797; "
    "_gid=GA1.2.1353156256.1781717134; "
    "JSESSIONID=node0zvjox1rf5xidsuavo0720sp048677678.node0; "
    "clientIp=F31E20F28AD2B3BEE29105588C4DC2296D05851A73515915FD86406FA485B8B4; "
    "_gat=1"
)
WS_URL = "wss://gamevh.net/ws/gameServer"
GAME_ID = "xiangqi"
PLACE_PATH = "Lobby.xiangqi.0"
CURRENT_PLAYER_NICKNAME = "nguyen05511"
CURRENT_PLAYER_ID = 65692430
TOKEN = 0
BOT_BET_XU = 5000
BOT_MATCH_DURATION = "10"
BOT_TURN_DURATION = "60"
ENGINE_TIME_LIMIT = 4000
CP_BOOK_MIN_DEPTH = 20
CP_BOOK_IGNORE_SCORE = -100
PONDER_ENABLED = True
PONDER_MIN_MOVES = 2

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ==================== COMMAND MAP ====================
CMD_NAMES = {
    300:"PONG",301:"PING",302:"LOGIN",310:"UNKNOWN_310",311:"BROADCAST",
    345:"UNKNOWN_345",401:"ENTER_PLACE",405:"CREATE_RULE",
    406:"PLAYER_ENTERED",407:"PLAYER_EXITED",408:"QUICK_PLAY",
    412:"LIST_ZONE_ROOM",413:"LIST_BET_AMT",414:"GET_TABLE_DATA",
    415:"ROOM_LIST_DATA",416:"SLOT_IN_TABLE_CHANGED",
    417:"START_MATCH",418:"GAMEOVER",419:"ENTER_STATE",
    420:"SET_TURN",421:"UNKNOWN_421",424:"UNKNOWN_424",
    431:"TABLE_INFO",432:"UNKNOWN_432",434:"SET_READY",
    502:"PLAY",529:"MOVE",
}

# ==================== PROTOCOL ====================
class Conn:
    def pack(self, cmd, data=b""):
        r = bytearray()
        if isinstance(cmd, str):
            cb = cmd.encode("ascii"); r.append((-len(cb)) & 0xFF); r.extend(cb)
        elif isinstance(cmd, int): r.extend(struct.pack(">H", cmd))
        r.extend(data); return bytes(r)
    def pb(self, v): return struct.pack(">b", v)
    def pi(self, v): return struct.pack(">i", v)
    def pa(self, v): e = v.encode("ascii")[:255]; return struct.pack(">b", len(e)) + e
    def ps(self, v): e = v.encode("utf-16-be"); return struct.pack(">h", len(e)//2) + e

class InboundMessage:
    def __init__(self, data):
        self.data = bytes(data); self.off = 0; self.command = self._parse()
    def _parse(self):
        l = self.rb()
        if l < 0:
            s = self.data[self.off:self.off+(-l)].decode("ascii","replace")
            self.off += (-l); return s
        nb = self.data[self.off] & 0xFF; self.off += 1
        return CMD_NAMES.get((l<<8)|nb, f"0x{(l<<8)|nb:04x}")
    def rb(self): v = struct.unpack_from(">b", self.data, self.off)[0]; self.off+=1; return v
    def rs(self): v = struct.unpack_from(">h", self.data, self.off)[0]; self.off+=2; return v
    def ri(self): v = struct.unpack_from(">i", self.data, self.off)[0]; self.off+=4; return v
    def rl(self): v = struct.unpack_from(">q", self.data, self.off)[0]; self.off+=8; return v
    def ra(self):
        l = self.rb()
        if l < 0: l += 256
        s = self.data[self.off:self.off+l].decode("ascii","replace"); self.off+=l; return s
    def rstr(self):
        cc = self.rs()
        s = self.data[self.off:self.off+cc*2].decode("utf-16-be","replace")
        self.off += cc*2; return s

# ==================== SESSION ====================
def fetch_session():
    global TOKEN, CURRENT_PLAYER_NICKNAME, CURRENT_PLAYER_ID, COOKIE
    try:
        cookies = {}
        for item in COOKIE.split("; "):
            if not item.strip(): continue
            k, v = item.split("=", 1); cookies[k.strip()] = v.strip()
        s = requests.Session(); s.cookies.update(cookies)
        r = s.get("https://gamevh.net/play/xiangqi/0",
                  headers={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"},
                  timeout=5)
        for key, pat in [("token",r"token\s*=\s*(-?\d+)"),
                         ("currentPlayerId",r"currentPlayerId\s*=\s*(\d+)"),
                         ("currentPlayerNickName",r"currentPlayerNickName\s*=\s*[\"']?([^\"'\n;]+)")]:
            m = re.search(pat, r.text)
            if m:
                if key=="token": TOKEN=int(m.group(1))
                elif key=="currentPlayerId": CURRENT_PLAYER_ID=int(m.group(1))
                elif key=="currentPlayerNickName": CURRENT_PLAYER_NICKNAME=m.group(1).strip()
        for ck in s.cookies:
            if ck.name=="JSESSIONID":
                COOKIE = re.sub(r"JSESSIONID=[^;]+", f"JSESSIONID={ck.value}", COOKIE)
        print(f"[SESSION] ✅ Token={TOKEN} | {CURRENT_PLAYER_NICKNAME} | PID={CURRENT_PLAYER_ID}")
        return True
    except Exception as e:
        print(f"[SESSION] ❌ {e}"); return False

# ==================== ENGINE VỚI PONDER ====================
class PikafishEngine:
    def __init__(self):
        self.proc = None
        self._latest_bestmove = None
        self._bestmove_event = threading.Event()
        self._pondering = False
        self._ponder_lock = threading.Lock()
        self._init()

    def _init(self):
        paths = [os.path.expanduser("~/pikafish"), os.path.join(SCRIPT_DIR,"pikafish"),
                 os.path.expanduser("~/Android/pikafish-armv8"),
                 "/data/data/com.termux/files/home/pikafish","/home/user/pikafish"]
        exe = next((p for p in paths if os.path.isfile(p) and os.access(p, os.X_OK)), None)
        if not exe:
            print(f"[ENGINE] ❌ Không tìm thấy pikafish!"); return
        try:
            self.proc = subprocess.Popen([exe], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                          stderr=subprocess.PIPE, text=True, bufsize=1)
            def _stderr():
                try:
                    while self.proc and self.proc.poll() is None: self.proc.stderr.readline()
                except: pass
            threading.Thread(target=_stderr, daemon=True).start()

            # === THREAD ĐỌC STDOUT LIÊN TỤC (bắt bestmove từ cả tính thường lẫn ponder) ===
            def _stdout_reader():
                try:
                    while self.proc and self.proc.poll() is None:
                        line = self.proc.stdout.readline()
                        if not line: break
                        line = line.strip()
                        if line.startswith("bestmove"):
                            self._latest_bestmove = line
                            self._bestmove_event.set()
                            if self._pondering:
                                parts = line.split()
                                bm = parts[1] if len(parts)>=2 else "?"
                                print(f"[PONDER] 💭 Engine đã có bestmove sẵn: {bm}")
                except: pass
            threading.Thread(target=_stdout_reader, daemon=True).start()

            self._cmd("uci")
            self._cmd("setoption name Threads value 2")
            self._cmd("setoption name Hash value 512")
            self._cmd("setoption name MultiPV value 3")
            self._cmd("setoption name Ponder value true")
            nnue_paths = [os.path.expanduser("~/pikafish.nnue"),
                          os.path.join(SCRIPT_DIR,"pikafish.nnue"),
                          os.path.join(os.path.dirname(exe),"pikafish.nnue"),
                          "/home/user/pikafish.nnue"]
            nnue = next((p for p in nnue_paths if os.path.isfile(p)), None)
            if nnue: self._cmd(f"setoption name EvalFile value {nnue}")
            self._cmd("isready"); time.sleep(2)
            print(f"[ENGINE] ✅ Sẵn sàng (MultiPV=3, Hash=512MB, Ponder=ON)")
        except Exception as e:
            print(f"[ENGINE] ❌ {e}")

    def _cmd(self, text):
        if self.proc and self.proc.poll() is None:
            try: self.proc.stdin.write(text+"\n"); self.proc.stdin.flush()
            except: pass

    def is_alive(self): return self.proc is not None and self.proc.poll() is None

    # ==================== PONDER API ====================
    def start_ponder(self, fen, moves, predicted_opp_move):
        """Bắt đầu ponder với dự đoán nước đối thủ"""
        if not PONDER_ENABLED or not predicted_opp_move: return False
        with self._ponder_lock:
            if self._pondering: return False
            all_moves = moves + [predicted_opp_move]
            cmd = f"position fen {fen}"
            if all_moves: cmd += " moves " + " ".join(all_moves)
            self._cmd(cmd); self._cmd("go ponder")
            self._pondering = True
            self._latest_bestmove = None; self._bestmove_event.clear()
            print(f"[PONDER] 🧠 Bắt đầu: dự đoán đối thủ đi {predicted_opp_move}")
            return True

    def ponderhit(self):
        """Gọi khi đối thủ đi đúng dự đoán → engine đã có bestmove sẵn"""
        with self._ponder_lock:
            if self._pondering:
                self._cmd("ponderhit"); self._pondering = False
                print(f"[PONDER] ✅ Ponderhit! Đợi bestmove...")
                if self._bestmove_event.wait(timeout=3):
                    return self._latest_bestmove
        return None

    def stop_ponder(self):
        """Dừng ponder khi đối thủ đi khác dự đoán"""
        with self._ponder_lock:
            if self._pondering:
                self._cmd("stop"); self._pondering = False
                print(f"[PONDER] 🛑 Dừng ponder.")
                time.sleep(0.2)

    def get_bestmove(self, fen, moves, time_limit=4000):
        """Tính nước đi bình thường (không dùng ponder)"""
        if not self.is_alive(): return None
        self.stop_ponder()
        self._latest_bestmove = None; self._bestmove_event.clear()
        cmd = f"position fen {fen}"
        if moves: cmd += " moves " + " ".join(moves)
        self._cmd(cmd); self._cmd(f"go movetime {time_limit}")
        if self._bestmove_event.wait(timeout=time_limit/1000+3):
            parts = self._latest_bestmove.split()
            return parts[1] if len(parts)>=2 else None
        return None

    def get_last_pv_opponent_move(self):
        """Lấy nước dự đoán của đối thủ từ PV line cuối cùng.
        bestmove X ponder Y → Y là nước đối thủ dự đoán"""
        if self._latest_bestmove:
            parts = self._latest_bestmove.split()
            if len(parts) >= 4 and parts[2] == "ponder":
                return parts[3]
        return None

    def newgame(self):
        self.stop_ponder(); self._cmd("ucinewgame"); self._cmd("isready")

    def stop(self):
        if self.is_alive(): self._cmd("stop")
    def quit(self):
        if self.is_alive():
            try: self.proc.stdin.write("quit\n"); self.proc.stdin.flush(); self.proc.wait(timeout=2)
            except:
                try: self.proc.terminate()
                except: pass

# ==================== BOARD ====================
class BoardTracker:
    INITIAL_FEN = "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w"
    def __init__(self): self.reset()
    def reset(self):
        self.fen = self.INITIAL_FEN; self.move_history = []
        self.my_slot = -1; self.first_turn_slot = 0
        self.is_my_turn = False; self.is_playing = False; self.is_red = None
    def set_slot(self, ms, fs): self.my_slot = ms; self.first_turn_slot = fs; self.is_red = (ms == fs)
    def get_fen_and_moves(self):
        board = self.fen.split(" ")[0] if " " in self.fen else self.fen
        return f"{board} w", list(self.move_history)
    def pos_to_engine(self, src, tgt):
        sc, sr = src % 9, src // 9; tc, tr = tgt % 9, tgt // 9
        return f"{chr(ord('a')+sc)}{sr}{chr(ord('a')+tc)}{tr}"
    def engine_to_pos(self, em):
        sc, sr = ord(em[0])-ord("a"), int(em[1])
        tc, tr = ord(em[2])-ord("a"), int(em[3])
        return sr*9+sc, tr*9+tc
    def build_fen_from_pieces(self, pieces):
        board = [["." for _ in range(9)] for _ in range(10)]
        tm = {1:"k",2:"a",3:"b",4:"r",5:"c",6:"n",7:"p"}
        for face, pos in pieces:
            if pos < 0 or pos >= 90: continue
            r, c = pos//9, pos%9; fr = 9-r
            clr = face[0]; pt = int(face[1]) if len(face)>1 else 0
            fc = tm.get(pt,"?"); 
            if clr == "r": fc = fc.upper()
            board[fr][c] = fc
        rows = []
        for row in board:
            rs = ""; e = 0
            for cell in row:
                if cell == ".": e += 1
                else:
                    if e: rs += str(e); e = 0
                    rs += cell
            if e: rs += str(e)
            rows.append(rs)
        return "/".join(rows) + " w"
    @staticmethod
    def decode_piece_id(enc):
        clr = "r"
        if enc < 0: enc = -enc; clr = "b"
        return f"{clr}{enc>>3}{'' if (enc&7)==0 else (enc&7)}"

# ==================== CP BOOK ====================
class CPBook:
    def __init__(self):
        self.filename = os.path.join(SCRIPT_DIR, "cp_book.json")
        self.book = {}; self._load()
    def _load(self):
        print(f"[CP-BOOK] 📁 {self.filename}")
        if os.path.exists(self.filename):
            try:
                with open(self.filename,"r") as f: self.book = json.load(f)
                print(f"[CP-BOOK] 📚 Đã tải {len(self.book)} thế cờ.")
            except Exception as e:
                print(f"[CP-BOOK] ❌ {e}"); self.book = {}
    def _save(self):
        try:
            with open(self.filename,"w") as f: json.dump(self.book, f, separators=(",",":"))
        except Exception as e: print(f"[CP-BOOK] ❌ Lỗi lưu: {e}")
    def lookup(self, fen, moves=None):
        key = fen
        if moves: key = fen + "|" + "|".join(moves)
        if key in self.book:
            e = self.book[key]; s = e.get("score",0); d = e.get("depth",0)
            if s < CP_BOOK_IGNORE_SCORE: return None
            if d < CP_BOOK_MIN_DEPTH: return None
            print(f"[CP-BOOK] 📖 HIT! {e['move']} (CP:{s} D:{d})")
            return e["move"], s, d
        return None
    def save(self, fen, move, score, depth, moves=None):
        key = fen
        if moves: key = fen + "|" + "|".join(moves)
        old = self.book.get(key)
        if old and old.get("depth",0) >= depth and old.get("score",0) >= score: return
        self.book[key] = {"move":move,"score":score,"depth":depth,"ts":int(time.time())}
        self._save()
        print(f"[CP-BOOK] 💾 Đã lưu: {move} (CP:{score} D:{depth}) → {len(self.book)} entries")

# ==================== MAIN BOT ====================
class XiangqiBot:
    def __init__(self):
        self.conn = Conn(); self.board = BoardTracker()
        self.engine = PikafishEngine(); self.book = CPBook()
        self.ws = None; self.connected = False; self.logged_in = False
        self.in_game = False; self.in_table = False
        self._ready_sent = False; self._last_action = time.time()
        self.bet_amts = []; self.bet_id = None; self._bet_loaded = False
        self._move_lock = threading.Lock()
        self._gen = 0
        print(f"\n{'='*55}\n  XIANGQI BOT v3 - PONDER ENABLED\n  Script: {SCRIPT_DIR}\n  Book:   {os.path.join(SCRIPT_DIR,'cp_book.json')}\n{'='*55}")

    # ==================== SEND ====================
    def _send(self, cmd, data=b""):
        if self.ws and self.connected:
            try: self.ws.send(self.conn.pack(cmd, data), opcode=0x2)
            except Exception as e: print(f"[SEND] ❌ {e}")
    def _send_login(self):
        d = bytearray()
        d.extend(self.conn.pa(CURRENT_PLAYER_NICKNAME)); d.extend(self.conn.pi(TOKEN))
        d.extend(self.conn.pa("5.0.2")); d.extend(self.conn.pa(""))
        d.extend(self.conn.pa(GAME_ID)); d.extend(self.conn.pb(1))
        self._send("LOGIN", bytes(d))
        print(f"[LOGIN] 📤 {CURRENT_PLAYER_NICKNAME} token={TOKEN}")
    def _send_enter_place(self, path=PLACE_PATH, mode=1):
        d = bytearray(); d.extend(self.conn.pa(path))
        d.extend(bytearray([0,0])); d.extend(self.conn.pb(mode))
        self._send("ENTER_PLACE", bytes(d))
    def _send_list_bet_amt(self): self._send("LIST_BET_AMT")
    def _send_create_table(self):
        if self.bet_id is None: return
        args = [("matchDuration",BOT_MATCH_DURATION),("turnDuration",BOT_TURN_DURATION),
                ("accDuration","0"),("blockSoftware","0")]
        d = bytearray(); d.extend(self.conn.pb(self.bet_id)); d.extend(self.conn.pb(len(args)))
        for an, av in args: d.extend(self.conn.pa(an)); d.extend(self.conn.ps(av))
        self._send("CREATE_RULE", bytes(d))
        print(f"[CREATE_RULE] 📤 bet_id={self.bet_id} ({BOT_BET_XU}xu)")
    def _send_ready(self, gen=None):
        if gen is not None and gen != self._gen: return
        if self._ready_sent or self.board.is_playing: return
        if not self.connected: return
        self._ready_sent = False
        self._send("SET_READY", self.conn.pb(1))
        print("[SET_READY] 📤 isReady=1")
    def _send_play(self, src, tgt):
        d = bytearray(); d.extend(self.conn.pb(src)); d.extend(self.conn.pb(tgt))
        self._send("PLAY", bytes(d))
        print(f"-> 🎯 Xuất quân: {self.board.pos_to_engine(src, tgt)}")

    # ==================== AUTO MOVE + PONDER ====================
    def _make_auto_move(self):
        if not self.board.is_my_turn or not self.board.is_playing: return
        if not self._move_lock.acquire(blocking=False): return
        try:
            if not self.board.is_my_turn or not self.board.is_playing: return
            if not self.engine.is_alive(): self.engine._init()
            if not self.engine.is_alive(): return

            fen, moves = self.board.get_fen_and_moves()
            side = "🔴 ĐỎ" if self.board.is_red else "⚫ ĐEN"
            print(f"\n[TURN] 🎯 Lượt BOT ({side}) | {len(moves)} nước đã đi")

            # === PONDER PATH: Kiểm tra nếu đối thủ vừa đi đúng dự đoán ===
            ponder_bm = self.engine.ponderhit()
            if ponder_bm:
                parts = ponder_bm.split()
                best_move = parts[1] if len(parts)>=2 else None
                if best_move and best_move not in ("(none)","0000"):
                    print(f"[PONDER] ⚡️ Dùng nước đã tính sẵn từ ponder!")
                    try:
                        src, tgt = self.board.engine_to_pos(best_move)
                        if self.board.is_my_turn and self.board.is_playing:
                            self._send_play(src, tgt)
                            self.board.move_history.append(best_move)
                            self.board.is_my_turn = False
                    except Exception as e:
                        print(f"[BOT] ❌ Lỗi ponder {best_move}: {e}")
                    return

            # 1. CP Book
            book = self.book.lookup(fen, moves)
            if book:
                best_move, _, _ = book
            else:
                print(f"[ENGINE] 🔍 Tính toán (go movetime {ENGINE_TIME_LIMIT})...")
                best_move = self.engine.get_bestmove(fen, moves, ENGINE_TIME_LIMIT)
                if best_move and best_move not in ("(none)","0000"):
                    self.book.save(fen, best_move, 0, 20, moves)

            if not best_move or best_move in ("(none)","0000"):
                print("[BOT] ⚠️ Hết nước hợp lệ!")
                return

            try:
                src, tgt = self.board.engine_to_pos(best_move)
                if self.board.is_my_turn and self.board.is_playing:
                    self._send_play(src, tgt)
                    self.board.move_history.append(best_move)
                    self.board.is_my_turn = False
            except Exception as e:
                print(f"[BOT] ❌ Lỗi tọa độ {best_move}: {e}")
        finally:
            self._move_lock.release()

    def _start_ponder_on_opponent_turn(self):
        """Gọi khi SET_TURN báo đến lượt đối thủ"""
        if not PONDER_ENABLED: return
        if not self.board.is_playing: return
        if self.board.is_my_turn: return
        if len(self.board.move_history) < PONDER_MIN_MOVES:
            return
        predicted = self.engine.get_last_pv_opponent_move()
        if not predicted: return
        fen, moves = self.board.get_fen_and_moves()
        self.engine.start_ponder(fen, moves, predicted)

    # ==================== HANDLERS ====================
    def _on_open(self, ws):
        self.ws = ws; self.connected = True; self._last_action = time.time()
        print("[WS] ✅ Connected!"); self._send_login()

    def _on_message(self, ws, message):
        if not isinstance(message, bytes): return
        try: self._dispatch(InboundMessage(message))
        except Exception as e: print(f"[MSG] ❌ {e}")

    def _dispatch(self, msg):
        cmd = msg.command
        if cmd == "PING": self._send("PONG")
        elif cmd == "LOGIN":
            code = msg.rb()
            if code == 0:
                self.logged_in = True; path = msg.rstr()
                print(f"[LOGIN] ✅ path='{path}'")
                if path == "REFRESH": fetch_session(); self._send_login()
                else: time.sleep(0.3); self._send_enter_place(PLACE_PATH)
            else: print(f"[LOGIN] ❌ code={code}")
        elif cmd == "ENTER_PLACE":
            code = msg.rb()
            if code == 0 or (code == -1 and self.in_table):
                if self.in_table:
                    self.in_table = False; self.in_game = True
                    self._last_action = time.time(); self._ready_sent = False
                    print("[TABLE] 🎯 Đã vào bàn!")
                    threading.Thread(target=lambda g=self._gen: (time.sleep(3), self._send_ready(g)), daemon=True).start()
                elif not self.in_game:
                    self._bet_loaded = False; self.bet_id = None
                    time.sleep(0.3); self._send_list_bet_amt()
        elif cmd == "LIST_BET_AMT":
            code = msg.rb()
            if code == 0:
                count = msg.rb()
                self.bet_amts = [{"id":i,"value":msg.ri()} for i in range(count)]
                for ba in self.bet_amts:
                    if ba["value"] == BOT_BET_XU: self.bet_id = ba["id"]; break
                if self.bet_id is None and self.bet_amts: self.bet_id = 0
                self._bet_loaded = True
                print(f"[LIST_BET_AMT] 📥 {len(self.bet_amts)} mức → id={self.bet_id} ({BOT_BET_XU}xu)")
                time.sleep(0.2); self._send_create_table()
        elif cmd == "CREATE_RULE":
            code = msg.rb()
            if code == 0:
                tp = msg.ra(); self.in_game = True; self.in_table = True
                print(f"[CREATE_RULE] ✅ Bàn: {tp}")
                threading.Thread(target=lambda: (time.sleep(0.3), self._send_enter_place(tp,1)), daemon=True).start()
            else: print(f"[CREATE_RULE] ❌ code={code}")
        elif cmd == "SLOT_IN_TABLE_CHANGED":
            try:
                _ = msg.rstr(); sid = msg.rb()
                msg.rl(); msg.rl(); msg.rb(); msg.rs(); msg.ra(); msg.rb(); msg.rb()
                pid = msg.rl()
                tag = "(MÌNH)" if pid == CURRENT_PLAYER_ID else "(đối thủ)"
                print(f"[SLOT] slot={sid} player={pid} {tag}")
                if pid == CURRENT_PLAYER_ID: self.board.my_slot = sid
                elif pid > 0 and not self.board.is_playing and not self._ready_sent:
                    threading.Thread(target=lambda g=self._gen: (time.sleep(3), self._send_ready(g)), daemon=True).start()
            except Exception as e: print(f"[SLOT] err: {e}")
        elif cmd == "START_MATCH":
            print(f"\n[GAME] {'='*40}\n[GAME] 🎮 TRẬN CHIẾN BẮT ĐẦU!")
            self.engine.stop_ponder()
            self.board.reset(); self.board.is_playing = True; self.in_game = True
            self._ready_sent = False; self._last_action = time.time()
            try:
                pc = msg.rb()
                for _ in range(pc): msg.rb(); msg.ri()
                pcnt = msg.rb(); pieces = []
                for _ in range(pcnt):
                    rsid=msg.rb(); rface=msg.rb(); pos=msg.rb(); iso=msg.rb()
                    pieces.append((BoardTracker.decode_piece_id(rsid),
                                   BoardTracker.decode_piece_id(rface), pos, iso))
                msg.rb(); mc = msg.rb()
                for _ in range(mc): msg.rb()
                msg.rb(); msg.rb()
                first_slot = msg.rb(); my_slot = msg.rb()
                if my_slot < 0 or my_slot == 255:
                    my_slot = self.board.my_slot if self.board.my_slot >= 0 else 0
                self.board.set_slot(my_slot, first_slot)
                bp = [(face, pos) for _, face, pos, _ in pieces]
                self.board.fen = self.board.build_fen_from_pieces(bp)
                side = "🔴 ĐỎ" if self.board.is_red else "⚫ ĐEN"
                print(f"[GAME] {side} | Slot={my_slot}")
                print(f"[GAME] {'='*40}")
                if self.board.is_red:
                    self.board.is_my_turn = True
                    threading.Thread(target=self._make_auto_move, daemon=True).start()
                else: print("[GAME] ⏳ Chờ đối thủ đi trước...")
            except Exception as e: print(f"[START_MATCH] ❌ {e}")
        elif cmd == "MOVE":
            try:
                src = msg.rb(); tgt = msg.rb()
                em = self.board.pos_to_engine(src, tgt)
                self._last_action = time.time()
                if self.board.move_history and self.board.move_history[-1] == em:
                    print(f"[MOVE] 🔄 Echo: {em} (bỏ qua)")
                else:
                    print(f"[MOVE] 📥 Đối thủ: {em}")
                    self.board.move_history.append(em)
                    # Nếu đối thủ đi khác dự đoán → dừng ponder
                    # (Nếu đi đúng → để ponderhit xử lý trong _make_auto_move)
                    if self.engine._pondering:
                        predicted = self.engine.get_last_pv_opponent_move()
                        if em == predicted:
                            print(f'[PONDER] ✅ Đối thủ đi ĐÚNG dự đoán {predicted}! Giữ ponder...')
                        else:
                            self.engine.stop_ponder()
            except Exception as e: print(f"[MOVE] ❌ {e}")
        elif cmd == "PLAY":
            code = msg.rb()
            if code != 0:
                if self.board.move_history: self.board.move_history.pop()
                print(f"[PLAY] ❌ Bị từ chối! Chờ SET_TURN...")
        elif cmd == "SET_TURN":
            sid = msg.rb()
            was_my = self.board.is_my_turn
            self.board.is_my_turn = (sid == self.board.my_slot)
            self._last_action = time.time()
            arrow = "🎯 BOT" if self.board.is_my_turn else "⏳ đối thủ"
            print(f"[SET_TURN] 🔄 slot={sid} → {arrow}")
            if self.board.is_my_turn and not was_my and self.board.is_playing:
                threading.Thread(target=self._make_auto_move, daemon=True).start()
            if not self.board.is_my_turn and self.board.is_playing:
                threading.Thread(target=self._start_ponder_on_opponent_turn, daemon=True).start()
        elif cmd == "GAMEOVER":
            print(f"\n[GAME] 🏁 KẾT THÚC!\n")
            self.engine.stop_ponder()
            self.board.is_playing = False; self.board.is_my_turn = False
            self.board.move_history = []; self._ready_sent = False
            self.in_game = True; self._last_action = time.time()
            if self.engine.is_alive(): self.engine.newgame()
            threading.Thread(target=lambda g=self._gen: (time.sleep(3), self._send_ready(g)), daemon=True).start()
        elif cmd in ("PLAYER_ENTERED","PLAYER_EXITED","ROOM_LIST_DATA","TABLE_INFO",
                     "ENTER_STATE","SET_READY","BROADCAST","LIST_ZONE_ROOM","GET_TABLE_DATA",
                     "QUICK_PLAY","UNKNOWN_310","UNKNOWN_345","UNKNOWN_421","UNKNOWN_424","UNKNOWN_432"):
            pass

    def _on_error(self, ws, error):
        err_str = str(error)
        if "opcode=8" in err_str or "1000" in err_str: pass  # close frame bình thường
        else: print(f"[WS] ❌ Error: {error}")
    def _on_close(self, ws, code, msg):
        print(f"[WS] 🔴 Close: code={code}")
        self.connected = False; self.logged_in = False
        self.in_game = False; self.in_table = False
        self._ready_sent = False; self._bet_loaded = False
        self.bet_id = None; self.bet_amts = []; self.board.reset()

    def connect(self):
        import websocket
        self.connected = False
        self.ws = websocket.WebSocketApp(WS_URL, cookie=COOKIE,
            on_open=self._on_open, on_message=self._on_message,
            on_error=self._on_error, on_close=self._on_close,
            header={"Origin":"https://gamevh.net"})
        threading.Thread(target=lambda: self.ws.run_forever(ping_interval=25, ping_timeout=10),
                         daemon=True).start()
        for _ in range(25):
            if self.connected: break
            time.sleep(0.5)
        return self.connected

    def _keep_alive(self):
        while self.connected:
            time.sleep(10)
            if self.connected: self._send("PING")

    def run(self):
        print("[BOT] 🚀 Khởi động...")
        while True:
            try:
                if self.connected and self.board.is_playing:
                    if time.time() - self._last_action > 180:
                        print("[WATCHDOG] ⏰ 3ph → reconnect")
                        if self.ws: self.ws.close()
                        time.sleep(2)
                if not self.connected:
                    self._gen += 1
                    if not fetch_session():
                        time.sleep(5); continue
                    self.logged_in = False; self.in_game = False; self.in_table = False
                    self._ready_sent = False; self._bet_loaded = False
                    self.bet_id = None; self.bet_amts = []; self.board.reset()
                    if not self.connect():
                        print("[CONNECT] ❌ Thử lại 5s...")
                        time.sleep(5); continue
                    threading.Thread(target=self._keep_alive, daemon=True).start()
                    time.sleep(2)
                if self.connected and self.logged_in and not self.in_game and not self.in_table:
                    if self._bet_loaded: self._send_create_table()
                    else: self._send_list_bet_amt()
                    time.sleep(3)
                time.sleep(1)
            except KeyboardInterrupt: print("\n[BOT] ⏹ Dừng..."); break
            except Exception as e: print(f"[RUN] ❌ {e}"); time.sleep(5)

    def cleanup(self):
        self.engine.stop_ponder(); self.engine.stop(); self.engine.quit()
        if self.ws:
            try: self.ws.close()
            except: pass

if __name__ == "__main__":
    bot = XiangqiBot()
    import signal
    def _sig(s,f): bot.cleanup(); sys.exit(0)
    signal.signal(signal.SIGINT, _sig); signal.signal(signal.SIGTERM, _sig)
    try: bot.run()
    finally: bot.cleanup()
