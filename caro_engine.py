#!/usr/bin/env python3
"""
Caro Engine - Python port of caro-ai-pvp (lavantien)
Features: BitBoard, Zobrist hashing, Transposition Table,
          VCF solver, Pattern4 evaluation, PVS + LMR + Null-move pruning,
          Quiescence search, Aspiration windows, Iterative Deepening,
          Move Picker with staged generation, Search Heuristics.
"""

import time
import random
from dataclasses import dataclass, field
from typing import Optional, List, Tuple, Dict, Set

# ═══════════════════════════════════════════════════════════════
# ─── Constants ───────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════

EMPTY = -1
SYMBOL_O = 0
SYMBOL_X = 1

# Score hierarchy (from caro-ai-pvp evaluation)
WIN_SCORE = 30000
MAX_EVAL = 25000
INFINITY = 100000

FIVE_SCORE = 30000
FLEX4_WIN_BONUS = 15000
DOUBLE_B4_BONUS = 14000
B4F3_BONUS = 13000
DOUBLE_F3_BONUS = 12000
FLEX4_SCORE = 10000
BLOCK4_SCORE = 5000
FLEX3_SCORE = 1000
BLOCK3_SCORE = 100
FLEX2_SCORE = 100
BLOCK2_SCORE = 30
FLEX1_SCORE = 10

# Search parameters
ABSOLUTE_MAX_DEPTH = 50
MAX_SEARCH_RADIUS = 7
MAX_QUIESCENCE_DEPTH = 4
ASPIRATION_WINDOW_SIZE = 1500
MAX_ASPIRATION_ATTEMPTS = 3
NULL_MOVE_MIN_DEPTH = 4
NULL_MOVE_REDUCTION = 2
LMR_MIN_DEPTH = 3
LMR_FULL_DEPTH_MOVES = 4
VCF_SEARCH_DEPTH = 12
VCF_TIME_FRACTION = 0.20

# Move picker score constants
TT_MOVE_SCORE = 10_000_000
MUST_BLOCK_SCORE = 8_000_000
WIN_MOVE_SCORE = 5_000_000
THREAT_SCORE_BASE = 800_000
KILLER_SCORE_0 = 500_000
KILLER_SCORE_1 = 400_000
COUNTER_MOVE_SCORE = 350_000
HISTORY_SCORE_CAP = 300_000

# TT flags
TT_EXACT = 0
TT_LOWER_BOUND = 1
TT_UPPER_BOUND = 2

# Directions
DIRS = [(1, 0), (0, 1), (1, 1), (1, -1)]


# ═══════════════════════════════════════════════════════════════
# ─── Zobrist Hashing ─────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════

def _splitmix64(seed: int) -> int:
    """SplitMix64 PRNG for generating Zobrist keys."""
    seed = (seed + 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF
    seed = ((seed ^ (seed >> 30)) * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
    seed = ((seed ^ (seed >> 27)) * 0x94D049BB133111EB) & 0xFFFFFFFFFFFFFFFF
    return seed ^ (seed >> 31)


def _generate_zobrist_table(max_cells: int = 400) -> List[List[int]]:
    """Generate Zobrist hash table: zobrist[cell * 2 + player_index]."""
    table = []
    seed = 0x58A2C43F5A3B7E91
    for _ in range(max_cells * 2):
        seed = _splitmix64(seed)
        table.append(seed)
    return table


# Global Zobrist table (lazy init)
_ZOBRIST_TABLE: Optional[List[int]] = None
_ZOBRIST_NULL_MOVE: Optional[int] = None


def _get_zobrist_table() -> List[int]:
    global _ZOBRIST_TABLE
    if _ZOBRIST_TABLE is None:
        _ZOBRIST_TABLE = _generate_zobrist_table(400)  # enough for up to 20x20
    return _ZOBRIST_TABLE


def _get_zobrist_null_move() -> int:
    global _ZOBRIST_NULL_MOVE
    if _ZOBRIST_NULL_MOVE is None:
        seed = 0x58A2C43F5A3B7E91
        for _ in range(801):
            seed = _splitmix64(seed)
        _ZOBRIST_NULL_MOVE = seed
    return _ZOBRIST_NULL_MOVE


def zobrist_key(x: int, y: int, w: int, sym: int) -> int:
    """Get Zobrist key for position (x,y) with player sym."""
    idx = y * w + x
    player_idx = 0 if sym == SYMBOL_X else 1
    return _get_zobrist_table()[idx * 2 + player_idx]


# ═══════════════════════════════════════════════════════════════
# ─── Transposition Table ────────────────────────────────────
# ═══════════════════════════════════════════════════════════════

@dataclass
class TTEntry:
    hash_val: int = 0
    score: int = 0
    static_eval: int = 0
    depth: int = 0
    move_x: int = -1
    move_y: int = -1
    flag: int = TT_EXACT
    age: int = 0


class TranspositionTable:
    """Simple dict-based Transposition Table for single-threaded search."""

    def __init__(self, max_size: int = 2_000_000):
        self.table: Dict[int, TTEntry] = {}
        self.max_size = max_size
        self.age = 0
        self.probes = 0
        self.hits = 0

    def increment_age(self):
        self.age += 1
        # Periodically clean to prevent unbounded growth
        if len(self.table) > self.max_size:
            # Remove entries from old generations
            old_keys = [k for k, v in self.table.items() if self.age - v.age > 4]
            for k in old_keys:
                del self.table[k]
            # If still too large, clear half
            if len(self.table) > self.max_size:
                keys = list(self.table.keys())[:self.max_size // 2]
                for k in keys:
                    del self.table[k]

    def lookup(self, h: int) -> Optional[TTEntry]:
        self.probes += 1
        entry = self.table.get(h)
        if entry is not None:
            self.hits += 1
            return entry
        return None

    def store(self, entry: TTEntry):
        existing = self.table.get(entry.hash_val)
        if existing is not None:
            # Depth-age replacement: prefer deeper entries from newer searches
            existing_priority = existing.depth - 8 * (self.age - existing.age)
            new_priority = entry.depth  # new entry is from current age
            if new_priority >= existing_priority:
                self.table[entry.hash_val] = entry
        else:
            self.table[entry.hash_val] = entry

    def reset_stats(self):
        self.probes = 0
        self.hits = 0


# ═══════════════════════════════════════════════════════════════
# ─── Search Board (Mutable board for hot path) ──────────────
# ═══════════════════════════════════════════════════════════════

class SearchBoard:
    """Efficient mutable board with make/unmake and Zobrist hashing."""

    def __init__(self, hcount: int, vcount: int):
        self.w = hcount
        self.h = vcount
        self.total = hcount * vcount
        self.cells: List[int] = [EMPTY] * self.total
        self.hash_val = 0
        self.undo_stack: List[Tuple[int, int, int, int]] = []  # (x, y, prev_cell, prev_hash)

    def cell_index(self, x: int, y: int) -> int:
        return y * self.w + x

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.w and 0 <= y < self.h

    def player_at(self, x: int, y: int) -> int:
        """Returns SYMBOL_X, SYMBOL_O, or EMPTY."""
        if 0 <= x < self.w and 0 <= y < self.h:
            return self.cells[y * self.w + x]
        return EMPTY

    def is_empty(self, x: int, y: int) -> bool:
        if 0 <= x < self.w and 0 <= y < self.h:
            return self.cells[y * self.w + x] == EMPTY
        return False

    def make_move(self, x: int, y: int, player: int):
        idx = self.cell_index(x, y)
        self.undo_stack.append((x, y, self.cells[idx], self.hash_val))
        self.cells[idx] = player
        self.hash_val ^= zobrist_key(x, y, self.w, player)

    def unmake_move(self):
        x, y, prev_cell, prev_hash = self.undo_stack.pop()
        self.cells[y * self.w + x] = prev_cell
        self.hash_val = prev_hash

    def make_null_move(self):
        self.undo_stack.append((-1, -1, EMPTY, self.hash_val))
        self.hash_val ^= _get_zobrist_null_move()

    def unmake_null_move(self):
        _, _, _, prev_hash = self.undo_stack.pop()
        self.hash_val = prev_hash

    def hash(self) -> int:
        return self.hash_val

    def copy_from_caroboard(self, board):
        """Initialize from the bot's CaroBoard."""
        self.cells = [EMPTY] * self.total
        self.hash_val = 0
        self.undo_stack.clear()
        for y in range(self.h):
            for x in range(self.w):
                v = board.board[y][x]
                if v != EMPTY:
                    idx = self.cell_index(x, y)
                    self.cells[idx] = v
                    self.hash_val ^= zobrist_key(x, y, self.w, v)


# ═══════════════════════════════════════════════════════════════
# ─── Pattern4 Classification ────────────────────────────────
# ═══════════════════════════════════════════════════════════════

@dataclass
class PlayerPattern4:
    exactly5: int = 0
    flex4: int = 0
    block4: int = 0
    flex3: int = 0
    block3: int = 0
    flex2: int = 0
    block2: int = 0


def _classify_direction(sb: SearchBoard, x: int, y: int, dx: int, dy: int, player: int):
    """Classify the pattern in one direction from stone at (x,y).
    Returns (count, open_ends) — count includes the stone itself."""
    positive = 0
    positive_open = False
    for i in range(1, 6):
        nx, ny = x + dx * i, y + dy * i
        if not sb.in_bounds(nx, ny):
            break
        p = sb.player_at(nx, ny)
        if p == player:
            positive += 1
        elif p == EMPTY:
            positive_open = True
            break
        else:
            break

    negative = 0
    negative_open = False
    for i in range(1, 6):
        nx, ny = x - dx * i, y - dy * i
        if not sb.in_bounds(nx, ny):
            break
        p = sb.player_at(nx, ny)
        if p == player:
            negative += 1
        elif p == EMPTY:
            negative_open = True
            break
        else:
            break

    count = 1 + positive + negative
    open_ends = (1 if positive_open else 0) + (1 if negative_open else 0)
    return count, open_ends, positive, negative


def classify_direction(sb: SearchBoard, x: int, y: int, dx: int, dy: int, player: int) -> str:
    """Return pattern name for a direction."""
    count, open_ends, _, _ = _classify_direction(sb, x, y, dx, dy, player)

    if count >= 6:
        return "overline"
    if count == 5:
        # Check if both ends blocked by opponent
        return "exactly5"  # simplified; full check done in classify_and_accumulate
    if count == 4:
        if open_ends == 2:
            return "flex4"
        if open_ends == 1:
            return "block4"
        return "none"
    if count == 3:
        if open_ends == 2:
            return "flex3"
        if open_ends == 1:
            return "block3"
        return "none"
    if count == 2:
        if open_ends == 2:
            return "flex2"
        if open_ends == 1:
            return "block2"
        return "none"
    if count == 1:
        return "flex1"
    return "none"


def classify_and_accumulate(sb: SearchBoard, x: int, y: int, dx: int, dy: int, player: int, pp: PlayerPattern4):
    """Classify pattern in one direction and accumulate into pp."""
    count, open_ends, positive, negative = _classify_direction(sb, x, y, dx, dy, player)

    if count >= 6:
        return  # overline — no value
    if count == 5:
        # Check if both ends beyond the five are blocked by opponent
        after_x, after_y = x + dx * (positive + 1), y + dy * (positive + 1)
        before_x, before_y = x - dx * (negative + 1), y - dy * (negative + 1)

        after_blocked = not sb.in_bounds(after_x, after_y) or (
            sb.player_at(after_x, after_y) != EMPTY and sb.player_at(after_x, after_y) != player
        )
        before_blocked = not sb.in_bounds(before_x, before_y) or (
            sb.player_at(before_x, before_y) != EMPTY and sb.player_at(before_x, before_y) != player
        )

        if after_blocked and before_blocked:
            return  # both ends blocked — not a win
        pp.exactly5 += 1
        return

    if count == 4:
        if open_ends == 2:
            pp.flex4 += 1
        elif open_ends == 1:
            pp.block4 += 1
    elif count == 3:
        if open_ends == 2:
            pp.flex3 += 1
        elif open_ends == 1:
            pp.block3 += 1
    elif count == 2:
        if open_ends == 2:
            pp.flex2 += 1
        elif open_ends == 1:
            pp.block2 += 1


def classify_stone(sb: SearchBoard, x: int, y: int, player: int) -> PlayerPattern4:
    """Classify all 4-direction patterns for a single stone.
    Only processes each line once by skipping if preceding cell is same player."""
    pp = PlayerPattern4()
    for dx, dy in DIRS:
        # Skip if a same-color stone precedes this one in this direction
        px, py = x - dx, y - dy
        if sb.in_bounds(px, py) and sb.player_at(px, py) == player:
            continue
        classify_and_accumulate(sb, x, y, dx, dy, player, pp)
    return pp


def classify_board(sb: SearchBoard, player: int) -> PlayerPattern4:
    """Classify all patterns for a player across the entire board."""
    total = PlayerPattern4()
    for y in range(sb.h):
        for x in range(sb.w):
            if sb.player_at(x, y) == player:
                pp = classify_stone(sb, x, y, player)
                total.exactly5 += pp.exactly5
                total.flex4 += pp.flex4
                total.block4 += pp.block4
                total.flex3 += pp.flex3
                total.block3 += pp.block3
                total.flex2 += pp.flex2
                total.block2 += pp.block2
    return total


# ═══════════════════════════════════════════════════════════════
# ─── Win Check ──────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════

def would_win(sb: SearchBoard, x: int, y: int, player: int) -> bool:
    """Check if placing at (x,y) creates 5+ in a row (standard Caro: 5+ wins)."""
    for dx, dy in DIRS:
        count = 1
        for i in range(1, 5):
            nx, ny = x + dx * i, y + dy * i
            if sb.in_bounds(nx, ny) and sb.player_at(nx, ny) == player:
                count += 1
            else:
                break
        for i in range(1, 5):
            nx, ny = x - dx * i, y - dy * i
            if sb.in_bounds(nx, ny) and sb.player_at(nx, ny) == player:
                count += 1
            else:
                break
        if count >= 5:
            return True
    return False


# ═══════════════════════════════════════════════════════════════
# ─── Evaluation ─────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════

def evaluate(sb: SearchBoard, player: int) -> int:
    """Pattern4-based zero-sum evaluation."""
    my_score = _evaluate_for_player(sb, player)
    opp = SYMBOL_O if player == SYMBOL_X else SYMBOL_X
    opp_score = _evaluate_for_player(sb, opp)

    score = my_score - opp_score
    score += _center_bonus(sb, player) - _center_bonus(sb, opp)

    return max(-MAX_EVAL, min(MAX_EVAL, score))


def _evaluate_for_player(sb: SearchBoard, player: int) -> int:
    """Evaluate board position for one player using Pattern4 classification."""
    pp = classify_board(sb, player)

    if pp.exactly5 > 0:
        return FIVE_SCORE

    if pp.flex4 > 0:
        score = FLEX4_WIN_BONUS
        score += pp.block4 * BLOCK4_SCORE
        score += pp.flex3 * FLEX3_SCORE
        return score

    if pp.block4 >= 2:
        score = DOUBLE_B4_BONUS
        score += pp.block4 * BLOCK4_SCORE
        score += pp.flex3 * FLEX3_SCORE
        return score

    if pp.flex3 >= 2:
        score = DOUBLE_F3_BONUS
        score += pp.block4 * BLOCK4_SCORE
        score += pp.flex3 * FLEX3_SCORE
        return score

    if pp.block4 >= 1 and pp.flex3 >= 1:
        score = B4F3_BONUS
        score += pp.block4 * BLOCK4_SCORE
        score += pp.flex3 * FLEX3_SCORE
        return score

    # Normal scoring
    score = 0
    score += pp.flex4 * FLEX4_SCORE
    score += pp.block4 * BLOCK4_SCORE
    score += pp.flex3 * FLEX3_SCORE
    score += pp.block3 * BLOCK3_SCORE
    score += pp.flex2 * FLEX2_SCORE
    score += pp.block2 * BLOCK2_SCORE

    # Stone count bonus
    for y in range(sb.h):
        for x in range(sb.w):
            if sb.player_at(x, y) == player:
                score += FLEX1_SCORE

    return score


def _center_bonus(sb: SearchBoard, player: int) -> int:
    """Center position bonus for player's stones."""
    cx, cy = sb.w // 2, sb.h // 2
    bonus = 0
    for y in range(sb.h):
        for x in range(sb.w):
            if sb.player_at(x, y) == player:
                dist = abs(x - cx) + abs(y - cy)
                bonus += (sb.w - dist) * 2
    return bonus


# ═══════════════════════════════════════════════════════════════
# ─── Candidate Generation ───────────────────────────────────
# ═══════════════════════════════════════════════════════════════

def get_candidates(sb: SearchBoard, radius: int = MAX_SEARCH_RADIUS) -> List[Tuple[int, int]]:
    """Get empty cells near existing stones within radius."""
    has_stones = False
    for idx in range(sb.total):
        if sb.cells[idx] != EMPTY:
            has_stones = True
            break

    if not has_stones:
        # Empty board: return center 3x3
        cx, cy = sb.w // 2, sb.h // 2
        result = []
        for dy in range(-1, 2):
            for dx in range(-1, 2):
                nx, ny = cx + dx, cy + dy
                if sb.in_bounds(nx, ny):
                    result.append((nx, ny))
        return result

    visited: Set[int] = set()
    result = []
    for y in range(sb.h):
        for x in range(sb.w):
            if sb.player_at(x, y) != EMPTY:
                for dy in range(-radius, radius + 1):
                    for dx in range(-radius, radius + 1):
                        nx, ny = x + dx, y + dy
                        if sb.in_bounds(nx, ny) and sb.is_empty(nx, ny):
                            key = ny * sb.w + nx
                            if key not in visited:
                                visited.add(key)
                                result.append((nx, ny))
    return result


def get_tactical_candidates(sb: SearchBoard, player: int, radius: int = 2) -> List[Tuple[int, int]]:
    """Get candidate moves that are tactically significant (win, block, threat)."""
    opp = SYMBOL_O if player == SYMBOL_X else SYMBOL_X
    candidates = get_candidates(sb, radius)
    tactical = []
    for x, y in candidates:
        if _is_tactical_move(sb, x, y, player, opp):
            tactical.append((x, y))
    return tactical


def _is_tactical_move(sb: SearchBoard, x: int, y: int, player: int, opp: int) -> bool:
    """Check if a move is tactically significant."""
    # Win: placing creates 5+
    sb.make_move(x, y, player)
    if would_win(sb, x, y, player):
        sb.unmake_move()
        return True
    sb.unmake_move()

    # Block: opponent would win here
    sb.make_move(x, y, opp)
    if would_win(sb, x, y, opp):
        sb.unmake_move()
        return True
    sb.unmake_move()

    # Creates flex4 or block4
    sb.make_move(x, y, player)
    pp = classify_stone(sb, x, y, player)
    sb.unmake_move()
    if pp.flex4 > 0 or pp.block4 > 0 or pp.flex3 > 0:
        return True

    # Blocks opponent's flex4 or block4 or flex3
    sb.make_move(x, y, opp)
    pp_opp = classify_stone(sb, x, y, opp)
    sb.unmake_move()
    if pp_opp.flex4 > 0 or pp_opp.block4 > 0 or pp_opp.flex3 > 0:
        return True

    return False


# ═══════════════════════════════════════════════════════════════
# ─── VCF Solver ─────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════

VCF_NO_WIN = 0
VCF_WIN = 1
VCF_TIMEOUT = 2


class VCFSolver:
    """Victory by Continuous Fours solver."""

    def __init__(self, sb: SearchBoard, attacker: int, time_limit_ms: int):
        self.sb = sb
        self.attacker = attacker
        self.defender = SYMBOL_O if attacker == SYMBOL_X else SYMBOL_X
        self.time_limit_ms = time_limit_ms
        self.start_time = time.time()
        self.timed_out = False
        self.win_x = -1
        self.win_y = -1

    def _should_stop(self) -> bool:
        if self.timed_out:
            return True
        elapsed_ms = (time.time() - self.start_time) * 1000
        if elapsed_ms >= self.time_limit_ms:
            self.timed_out = True
            return True
        return False

    def solve(self, depth: int = VCF_SEARCH_DEPTH) -> int:
        """Try to find VCF win. Returns VCF_WIN/VCF_NO_WIN/VCF_TIMEOUT."""
        if self._should_stop():
            return VCF_TIMEOUT
        result = self._search(depth)
        if self.timed_out:
            return VCF_TIMEOUT
        return VCF_WIN if result else VCF_NO_WIN

    def _search(self, depth: int) -> bool:
        if self._should_stop():
            return False
        if depth <= 0:
            return False

        candidates = get_candidates(self.sb, 2)

        for cx, cy in candidates:
            if self._should_stop():
                return False

            self.sb.make_move(cx, cy, self.attacker)

            # Check immediate win
            if would_win(self.sb, cx, cy, self.attacker):
                self.sb.unmake_move()
                self.win_x, self.win_y = cx, cy
                return True

            # Check if this move creates a four that must be blocked
            blocks = self._find_four_blocks(cx, cy, self.attacker)
            if not blocks:
                self.sb.unmake_move()
                continue

            # If opponent has an immediate win elsewhere, they won't block our four
            if self._opponent_has_immediate_win(self.defender):
                self.sb.unmake_move()
                continue

            # For each blocking square, opponent plays there, then we must still win
            all_win = True
            for bx, by in blocks:
                self.sb.make_move(bx, by, self.defender)

                # Check if opponent's block itself wins
                if would_win(self.sb, bx, by, self.defender):
                    all_win = False
                    self.sb.unmake_move()
                    break

                if not self._search(depth - 1):
                    all_win = False
                    self.sb.unmake_move()
                    break

                self.sb.unmake_move()

            self.sb.unmake_move()

            if self.timed_out:
                return False
            if all_win:
                self.win_x, self.win_y = cx, cy
                return True

        return False

    def _find_four_blocks(self, x: int, y: int, attacker: int) -> List[Tuple[int, int]]:
        """Find cells the opponent must play to block a four created by placing at (x,y)."""
        blocks = []
        for dx, dy in DIRS:
            positive = 0
            for i in range(1, 5):
                nx, ny = x + dx * i, y + dy * i
                if not self.sb.in_bounds(nx, ny) or self.sb.player_at(nx, ny) != attacker:
                    break
                positive += 1

            negative = 0
            for i in range(1, 5):
                nx, ny = x - dx * i, y - dy * i
                if not self.sb.in_bounds(nx, ny) or self.sb.player_at(nx, ny) != attacker:
                    break
                negative += 1

            count = 1 + positive + negative
            if count != 4:
                continue

            # Check open ends
            after_x, after_y = x + dx * (positive + 1), y + dy * (positive + 1)
            before_x, before_y = x - dx * (negative + 1), y - dy * (negative + 1)

            after_open = (self.sb.in_bounds(after_x, after_y) and self.sb.is_empty(after_x, after_y))
            before_open = (self.sb.in_bounds(before_x, before_y) and self.sb.is_empty(before_x, before_y))

            if after_open:
                # Check that blocking here doesn't create overline (6+)
                beyond_x, beyond_y = after_x + dx, after_y + dy
                if not self.sb.in_bounds(beyond_x, beyond_y) or self.sb.player_at(beyond_x, beyond_y) != attacker:
                    blocks.append((after_x, after_y))

            if before_open:
                beyond_x, beyond_y = before_x - dx, before_y - dy
                if not self.sb.in_bounds(beyond_x, beyond_y) or self.sb.player_at(beyond_x, beyond_y) != attacker:
                    blocks.append((before_x, before_y))

        return blocks

    def _opponent_has_immediate_win(self, opponent: int) -> bool:
        """Check if opponent can win immediately."""
        candidates = get_candidates(self.sb, 2)
        for cx, cy in candidates:
            self.sb.make_move(cx, cy, opponent)
            wins = would_win(self.sb, cx, cy, opponent)
            self.sb.unmake_move()
            if wins:
                return True
        return False


# ═══════════════════════════════════════════════════════════════
# ─── Search Heuristics ──────────────────────────────────────
# ═══════════════════════════════════════════════════════════════

class SearchHeuristics:
    """Killer moves, butterfly history, continuation history, counter-moves."""

    def __init__(self, w: int, h: int):
        self.w = w
        self.h = h
        # Killer moves: 2 slots per depth
        self.killers: Dict[int, List[Optional[Tuple[int, int]]]] = {}
        # Butterfly history
        self.history: Dict[int, Dict[int, int]] = {
            SYMBOL_X: [[0] * w for _ in range(h)],
            SYMBOL_O: [[0] * w for _ in range(h)],
        }
        # Continuation history: player × prev_cell × curr_cell
        self.cont_history: Dict[int, Dict[int, Dict[int, int]]] = {
            SYMBOL_X: {},
            SYMBOL_O: {},
        }
        # Counter moves: player × opponent_cell → our response
        self.counter_moves: Dict[int, Dict[int, Tuple[int, int]]] = {
            SYMBOL_X: {},
            SYMBOL_O: {},
        }

    def clear(self):
        for k in self.killers:
            self.killers[k] = [None, None]
        for p in (SYMBOL_X, SYMBOL_O):
            for row in self.history[p]:
                for i in range(len(row)):
                    row[i] = 0
            self.cont_history[p] = {}
            self.counter_moves[p] = {}

    def record_killer(self, depth: int, pos: Tuple[int, int]):
        if depth not in self.killers:
            self.killers[depth] = [None, None]
        self.killers[depth][1] = self.killers[depth][0]
        self.killers[depth][0] = pos

    def killer_score(self, depth: int, pos: Tuple[int, int]) -> int:
        slots = self.killers.get(depth, [None, None])
        if slots[0] == pos:
            return KILLER_SCORE_0
        if slots[1] == pos:
            return KILLER_SCORE_1
        return 0

    def record_history(self, player: int, x: int, y: int, depth: int):
        bonus = depth * depth
        self.history[player][y][x] = min(self.history[player][y][x] + bonus, 1_000_000)

    def history_score(self, player: int, x: int, y: int) -> int:
        return self.history[player][y][x]

    def record_cont_history(self, player: int, px: int, py: int, x: int, y: int, depth: int):
        prev_key = py * self.w + px
        curr_key = y * self.w + x
        bonus = depth * depth * 300 // 100
        ch = self.cont_history[player]
        if prev_key not in ch:
            ch[prev_key] = {}
        ch[prev_key][curr_key] = min(ch[prev_key].get(curr_key, 0) + bonus, 30_000)

    def cont_history_score(self, player: int, px: int, py: int, x: int, y: int) -> int:
        prev_key = py * self.w + px
        curr_key = y * self.w + x
        return self.cont_history.get(player, {}).get(prev_key, {}).get(curr_key, 0)

    def record_counter_move(self, player: int, ox: int, oy: int, x: int, y: int):
        opp_key = oy * self.w + ox
        self.counter_moves[player][opp_key] = (x, y)

    def counter_move_for(self, player: int, ox: int, oy: int) -> Optional[Tuple[int, int]]:
        opp_key = oy * self.w + ox
        return self.counter_moves.get(player, {}).get(opp_key)


# ═══════════════════════════════════════════════════════════════
# ─── Move Picker ────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════

# Stages
STAGE_TT_MOVE = 0
STAGE_WINNING = 1
STAGE_MUST_BLOCK = 2
STAGE_THREAT = 3
STAGE_KILLER_COUNTER = 4
STAGE_QUIET = 5
STAGE_DONE = 6


class MovePicker:
    """Staged move generation with scoring and sorting."""

    def __init__(self, sb: SearchBoard, player: int, depth: int,
                 candidates: List[Tuple[int, int]],
                 tt_move: Optional[Tuple[int, int]],
                 heuristics: SearchHeuristics,
                 prev_move: Optional[Tuple[int, int]] = None):
        self.sb = sb
        self.player = player
        self.opp = SYMBOL_O if player == SYMBOL_X else SYMBOL_X
        self.depth = depth
        self.candidates = candidates
        self.tt_move = tt_move
        self.heuristics = heuristics
        self.prev_move = prev_move

        self.stage = STAGE_TT_MOVE
        self.moves: List[Tuple[int, int, int]] = []  # (score, x, y)
        self.idx = 0

    def next(self) -> Optional[Tuple[int, int]]:
        """Get next move, or None if exhausted."""
        while True:
            if self.idx < len(self.moves):
                s, x, y = self.moves[self.idx]
                self.idx += 1
                return (x, y)

            # Advance to next stage
            self.stage += 1
            self.idx = 0
            self.moves = []

            if self.stage == STAGE_WINNING:
                self._gen_winning()
                if self.moves:
                    continue
            elif self.stage == STAGE_MUST_BLOCK:
                self._gen_must_block()
                if self.moves:
                    continue
            elif self.stage == STAGE_THREAT:
                self._gen_threats()
                if self.moves:
                    self.moves.sort(reverse=True)
                    # Take top moves
                    if len(self.moves) > 20:
                        self.moves = self.moves[:20]
                    continue
            elif self.stage == STAGE_KILLER_COUNTER:
                self._gen_killer_counter()
                if self.moves:
                    continue
            elif self.stage == STAGE_QUIET:
                self._gen_quiet()
                if self.moves:
                    self.moves.sort(reverse=True)
                    if len(self.moves) > 15:
                        self.moves = self.moves[:15]
                    continue
            elif self.stage == STAGE_DONE:
                return None

    def _gen_winning(self):
        """Moves that create 5+ in a row."""
        for x, y in self.candidates:
            self.sb.make_move(x, y, self.player)
            if would_win(self.sb, x, y, self.player):
                self.sb.unmake_move()
                self.moves.append((WIN_MOVE_SCORE, x, y))
                return  # One winning move is enough
            self.sb.unmake_move()

    def _gen_must_block(self):
        """Moves where opponent would win."""
        for x, y in self.candidates:
            self.sb.make_move(x, y, self.opp)
            if would_win(self.sb, x, y, self.opp):
                self.sb.unmake_move()
                self.moves.append((MUST_BLOCK_SCORE, x, y))
            else:
                self.sb.unmake_move()

    def _gen_threats(self):
        """Scored by threat level."""
        already = set()
        if self.tt_move:
            already.add(self.tt_move)
        for m in self.moves:
            already.add((m[1], m[2]))

        for x, y in self.candidates:
            if (x, y) in already:
                continue
            score = self._threat_score(x, y)
            if score > 0:
                self.moves.append((score, x, y))

    def _threat_score(self, x: int, y: int) -> int:
        """Calculate threat score for a move."""
        score = 0
        # Player threats
        self.sb.make_move(x, y, self.player)
        pp = classify_stone(self.sb, x, y, self.player)
        self.sb.unmake_move()

        if pp.flex4 > 0:
            score += 700_000
        if pp.block4 > 0:
            score += 400_000
        if pp.flex3 > 0:
            score += 300_000

        # Opponent threats (blocking)
        self.sb.make_move(x, y, self.opp)
        pp_opp = classify_stone(self.sb, x, y, self.opp)
        self.sb.unmake_move()

        if pp_opp.flex4 > 0:
            score += 500_000
        if pp_opp.block4 > 0:
            score += 350_000
        if pp_opp.flex3 > 0:
            score += 200_000

        return score

    def _gen_killer_counter(self):
        """Killer moves and counter-move."""
        already = set()
        if self.tt_move:
            already.add(self.tt_move)
        for m in self.moves:
            already.add((m[1], m[2]))

        # Killer moves
        for slot, base_score in [(0, KILLER_SCORE_0), (1, KILLER_SCORE_1)]:
            k = self.heuristics.killers.get(self.depth, [None, None])[slot]
            if k and k not in already and self.sb.in_bounds(k[0], k[1]) and self.sb.is_empty(k[0], k[1]):
                self.moves.append((base_score, k[0], k[1]))
                already.add(k)

        # Counter-move
        if self.prev_move and self.prev_move[0] >= 0:
            cm = self.heuristics.counter_move_for(self.player, self.prev_move[0], self.prev_move[1])
            if cm and cm not in already and self.sb.in_bounds(cm[0], cm[1]) and self.sb.is_empty(cm[0], cm[1]):
                self.moves.append((COUNTER_MOVE_SCORE, cm[0], cm[1]))

    def _gen_quiet(self):
        """Remaining moves scored by history/center/proximity."""
        already = set()
        if self.tt_move:
            already.add(self.tt_move)
        for m in self.moves:
            already.add((m[1], m[2]))

        cx, cy = self.sb.w // 2, self.sb.h // 2
        for x, y in self.candidates:
            if (x, y) in already:
                continue
            score = 0

            # History
            hs = self.heuristics.history_score(self.player, x, y)
            score += min(hs * 2, HISTORY_SCORE_CAP)

            # Continuation history
            if self.prev_move and self.prev_move[0] >= 0:
                chs = self.heuristics.cont_history_score(
                    self.player, self.prev_move[0], self.prev_move[1], x, y)
                score += chs

            # Center proximity
            dist = abs(x - cx) + abs(y - cy)
            score += (self.sb.w * 2 - 4 - dist) * 100

            # Neighbor proximity (count occupied cells in 5×5 area)
            neighbor_count = 0
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    nx, ny = x + dx, y + dy
                    if self.sb.in_bounds(nx, ny) and self.sb.player_at(nx, ny) != EMPTY:
                        neighbor_count += 1
            score += neighbor_count * 10

            self.moves.append((score, x, y))


def order_moves(candidates: List[Tuple[int, int]], sb: SearchBoard, player: int,
                depth: int, tt_move: Optional[Tuple[int, int]],
                heuristics: SearchHeuristics) -> List[Tuple[int, int]]:
    """Convenience: fully sort all moves using MovePicker."""
    picker = MovePicker(sb, player, depth, candidates, tt_move, heuristics)
    result = []
    while True:
        m = picker.next()
        if m is None:
            break
        result.append(m)
    return result


# ═══════════════════════════════════════════════════════════════
# ─── Mate Score Adjustment ──────────────────────────────────
# ═══════════════════════════════════════════════════════════════

def _is_mate_score(score: int) -> bool:
    return score > WIN_SCORE - ABSOLUTE_MAX_DEPTH or score < -WIN_SCORE + ABSOLUTE_MAX_DEPTH


def _adjust_mate_for_store(score: int, ply: int) -> int:
    if score > WIN_SCORE - ABSOLUTE_MAX_DEPTH:
        return score + ply
    if score < -WIN_SCORE + ABSOLUTE_MAX_DEPTH:
        return score - ply
    return score


def _adjust_mate_for_retrieve(stored: int, ply: int) -> int:
    if stored >= WIN_SCORE - ABSOLUTE_MAX_DEPTH + 1:
        return stored - ply
    if stored <= -(WIN_SCORE - ABSOLUTE_MAX_DEPTH) - 1:
        return stored + ply
    return stored


# ═══════════════════════════════════════════════════════════════
# ─── Search Engine ──────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════

class CaroEngine:
    """Main search engine: Iterative Deepening + PVS + LMR + VCF + TT."""

    def __init__(self, hcount: int = 15, vcount: int = 19,
                 time_limit: float = 4.0, use_vcf: bool = True,
                 max_depth: int = 20):
        self.w = hcount
        self.h = vcount
        self.time_limit = time_limit
        self.use_vcf = use_vcf
        self.max_depth = max_depth

        self.tt = TranspositionTable()
        self.heuristics = SearchHeuristics(hcount, vcount)

        self.nodes = 0
        self.start_time = 0.0
        self.stopped = False

    def _should_stop(self) -> bool:
        if self.stopped:
            return True
        elapsed = time.time() - self.start_time
        if elapsed >= self.time_limit:
            self.stopped = True
            return True
        return False

    def find_best_move(self, sb: SearchBoard, player: int) -> Tuple[int, int]:
        """Main entry point: find best move for player."""
        self.start_time = time.time()
        self.stopped = False
        self.nodes = 0
        self.heuristics.clear()
        self.tt.increment_age()
        self.tt.reset_stats()

        opp = SYMBOL_O if player == SYMBOL_X else SYMBOL_X

        # Get candidates
        candidates = get_candidates(sb, MAX_SEARCH_RADIUS)
        if not candidates:
            return (self.w // 2, self.h // 2)
        if len(candidates) == 1:
            return candidates[0]

        # Quick checks: winning move, blocking move
        for x, y in candidates:
            sb.make_move(x, y, player)
            if would_win(sb, x, y, player):
                sb.unmake_move()
                return (x, y)
            sb.unmake_move()

        for x, y in candidates:
            sb.make_move(x, y, opp)
            if would_win(sb, x, y, opp):
                sb.unmake_move()
                return (x, y)
            sb.unmake_move()

        # VCF pre-search
        vcf_preferred = None
        if self.use_vcf:
            vcf_time_ms = self.time_limit * VCF_TIME_FRACTION * 1000
            # Check if opponent has immediate win
            if not self._opponent_has_immediate_win_on_sb(sb, opp):
                vcf = VCFSolver(sb, player, int(vcf_time_ms))
                result = vcf.solve(VCF_SEARCH_DEPTH)
                if result == VCF_WIN and vcf.win_x >= 0:
                    return (vcf.win_x, vcf.win_y)

            # Check if opponent has VCF win — try to block
            vcf_opp_time_ms = vcf_time_ms / 2
            vcf_opp = VCFSolver(sb, opp, int(vcf_opp_time_ms))
            opp_result = vcf_opp.solve(VCF_SEARCH_DEPTH)
            if opp_result == VCF_WIN and vcf_opp.win_x >= 0:
                # Try blocking the VCF move
                bx, by = vcf_opp.win_x, vcf_opp.win_y
                # Verify it's a valid block
                if sb.in_bounds(bx, by) and sb.is_empty(bx, by):
                    vcf_preferred = (bx, by)

        # Iterative deepening with aspiration windows
        best_x, best_y = candidates[0]
        best_score = -INFINITY
        completed_depth = 0
        full_alpha = -INFINITY
        full_beta = INFINITY

        for depth in range(1, self.max_depth + 1):
            if self._should_stop():
                break

            delta = ASPIRATION_WINDOW_SIZE
            a, b = full_alpha, full_beta
            if depth > 1:
                a = max(best_score - delta, full_alpha)
                b = min(best_score + delta, full_beta)

            x, y, score = self._search_root(
                sb, player, depth, a, b, candidates, vcf_preferred)

            if x < 0 or self._should_stop():
                break

            # Aspiration window adjustment
            found = False
            for _ in range(MAX_ASPIRATION_ATTEMPTS):
                if score <= a and a > full_alpha:
                    a = max(a - delta, full_alpha)
                    delta *= 2
                    x, y, score = self._search_root(
                        sb, player, depth, a, b, candidates, vcf_preferred)
                    if x < 0 or self._should_stop():
                        break
                    continue
                if score >= b and b < full_beta:
                    b = min(b + delta, full_beta)
                    delta *= 2
                    x, y, score = self._search_root(
                        sb, player, depth, a, b, candidates, vcf_preferred)
                    if x < 0 or self._should_stop():
                        break
                    continue
                found = True
                break

            if not found and not self._should_stop():
                x, y, score = self._search_root(
                    sb, player, depth, full_alpha, full_beta, candidates, vcf_preferred)
                if x >= 0:
                    found = True

            if found:
                best_x, best_y = x, y
                best_score = score
                completed_depth = depth
                if score >= WIN_SCORE:
                    break

        elapsed = time.time() - self.start_time
        nps = self.nodes / elapsed if elapsed > 0 else 0
        probes, hits = self.tt.probes, self.tt.hits
        hit_rate = hits / probes if probes > 0 else 0

        import logging
        log = logging.getLogger("caro_engine")
        log.info(f"🔍 Depth={completed_depth} Score={best_score} "
                 f"Nodes={self.nodes} NPS={nps:.0f} "
                 f"TT_hit={hit_rate:.1%} Move=({best_x},{best_y}) "
                 f"Time={elapsed:.2f}s")

        return (best_x, best_y)

    def _search_root(self, sb: SearchBoard, player: int, depth: int,
                     alpha: int, beta: int,
                     candidates: List[Tuple[int, int]],
                     preferred_move: Optional[Tuple[int, int]]) -> Tuple[int, int, int]:
        """Search at root level with PVS."""
        self.nodes += 1
        static_eval = evaluate(sb, player)

        # Get TT move or preferred move
        tt_move = preferred_move
        if tt_move is None:
            entry = self.tt.lookup(sb.hash())
            if entry is not None:
                tt_move = (entry.move_x, entry.move_y)

        # Order moves
        ordered = order_moves(candidates, sb, player, depth, tt_move, self.heuristics)

        opp = SYMBOL_O if player == SYMBOL_X else SYMBOL_X
        best_score = -INFINITY
        best_x, best_y = -1, -1

        for i, (mx, my) in enumerate(ordered):
            if self._should_stop():
                break

            sb.make_move(mx, my, player)

            if would_win(sb, mx, my, player):
                score = WIN_SCORE - 1
            elif i == 0:
                score = -self._alpha_beta(sb, opp, depth - 1, -beta, -alpha,
                                          (mx, my), 1)
            else:
                # PVS: null-window search first
                score = -self._alpha_beta(sb, opp, depth - 1, -alpha - 1, -alpha,
                                          (mx, my), 1)
                if score > alpha and score < beta:
                    score = -self._alpha_beta(sb, opp, depth - 1, -beta, -alpha,
                                              (mx, my), 1)

            sb.unmake_move()

            if score > best_score:
                best_score = score
                best_x, best_y = mx, my
            if score > alpha:
                alpha = score

        # Store in TT
        if best_x >= 0 and not self._should_stop():
            self.tt.store(TTEntry(
                hash_val=sb.hash(),
                score=_adjust_mate_for_store(best_score, 0),
                static_eval=static_eval,
                depth=depth,
                move_x=best_x,
                move_y=best_y,
                flag=TT_EXACT,
                age=self.tt.age,
            ))
            self.heuristics.record_killer(depth, (best_x, best_y))

        return best_x, best_y, best_score

    def _alpha_beta(self, sb: SearchBoard, player: int, depth: int,
                    alpha: int, beta: int,
                    prev_move: Tuple[int, int],
                    ply: int) -> int:
        """Alpha-beta with PVS, LMR, null-move pruning, TT."""
        self.nodes += 1
        if self._should_stop():
            return 0

        if depth <= 0:
            return self._quiesce(sb, player, alpha, beta, MAX_QUIESCENCE_DEPTH, ply)

        orig_alpha = alpha
        opp = SYMBOL_O if player == SYMBOL_X else SYMBOL_X

        # Null-move pruning
        if depth >= NULL_MOVE_MIN_DEPTH:
            static_eval = evaluate(sb, player)
            if static_eval >= beta:
                sb.make_null_move()
                null_score = -self._alpha_beta(sb, opp, depth - 1 - NULL_MOVE_REDUCTION,
                                               -beta, -beta + 1, (-1, -1), ply + 1)
                sb.unmake_null_move()
                if null_score >= beta and not self._should_stop():
                    return null_score

        # TT probe
        entry = self.tt.lookup(sb.hash())
        tt_move = None
        if entry is not None and entry.depth >= depth:
            tt_score = _adjust_mate_for_retrieve(entry.score, ply)
            if entry.flag == TT_EXACT:
                return tt_score
            elif entry.flag == TT_LOWER_BOUND and tt_score > alpha:
                alpha = tt_score
            elif entry.flag == TT_UPPER_BOUND and tt_score < beta:
                beta = tt_score
            if alpha >= beta:
                return tt_score

        if entry is not None:
            tt_move = (entry.move_x, entry.move_y)

        # Generate candidates and create move picker
        candidates = get_candidates(sb, MAX_SEARCH_RADIUS)
        picker = MovePicker(sb, player, depth, candidates, tt_move,
                            self.heuristics, prev_move)

        best_score = -INFINITY
        best_x, best_y = -1, -1
        move_idx = 0

        while True:
            move = picker.next()
            if move is None:
                break
            if self._should_stop():
                break

            mx, my = move

            # LMR
            reduction = 0
            if depth >= LMR_MIN_DEPTH and move_idx >= LMR_FULL_DEPTH_MOVES:
                reduction = 1
                if move_idx > 8:
                    reduction = 2
                hist = self.heuristics.history_score(player, mx, my)
                if hist < 0:
                    reduction += 1
                if reduction >= depth:
                    reduction = depth - 1

            sb.make_move(mx, my, player)

            if would_win(sb, mx, my, player):
                score = WIN_SCORE - ply
            else:
                new_depth = depth - 1 - reduction
                if move_idx == 0:
                    score = -self._alpha_beta(sb, opp, new_depth, -beta, -alpha,
                                              (mx, my), ply + 1)
                else:
                    # PVS
                    score = -self._alpha_beta(sb, opp, new_depth, -alpha - 1, -alpha,
                                              (mx, my), ply + 1)
                    if score > alpha and score < beta:
                        score = -self._alpha_beta(sb, opp, depth - 1, -beta, -alpha,
                                                  (mx, my), ply + 1)

            sb.unmake_move()

            if score > best_score:
                best_score = score
                best_x, best_y = mx, my
            if score > alpha:
                alpha = score
            if alpha >= beta:
                # Beta cutoff — record heuristics
                self.heuristics.record_killer(depth, (mx, my))
                self.heuristics.record_history(player, mx, my, depth)
                self.heuristics.record_cont_history(
                    player, prev_move[0], prev_move[1], mx, my, depth)
                if prev_move[0] >= 0:
                    self.heuristics.record_counter_move(
                        player, prev_move[0], prev_move[1], mx, my)
                break

            move_idx += 1

        # Store in TT
        if not self._should_stop():
            flag = TT_EXACT
            if best_score <= orig_alpha:
                flag = TT_UPPER_BOUND
            elif best_score >= beta:
                flag = TT_LOWER_BOUND

            self.tt.store(TTEntry(
                hash_val=sb.hash(),
                score=_adjust_mate_for_store(best_score, ply),
                static_eval=0,
                depth=depth,
                move_x=best_x,
                move_y=best_y,
                flag=flag,
                age=self.tt.age,
            ))

        return best_score

    def _quiesce(self, sb: SearchBoard, player: int,
                 alpha: int, beta: int, max_ply: int, ply: int) -> int:
        """Quiescence search — only tactical moves."""
        self.nodes += 1
        if self._should_stop():
            return 0

        stand_pat = evaluate(sb, player)
        if stand_pat >= beta:
            return beta
        if stand_pat > alpha:
            alpha = stand_pat
        if max_ply <= 0:
            return stand_pat

        opp = SYMBOL_O if player == SYMBOL_X else SYMBOL_X
        tactical = get_tactical_candidates(sb, player, 2)

        for mx, my in tactical:
            if self._should_stop():
                break

            sb.make_move(mx, my, player)

            if would_win(sb, mx, my, player):
                score = WIN_SCORE - ply
            else:
                score = -self._quiesce(sb, opp, -beta, -alpha, max_ply - 1, ply + 1)

            sb.unmake_move()

            if score >= beta:
                return beta
            if score > alpha:
                alpha = score

        return alpha

    def _opponent_has_immediate_win_on_sb(self, sb: SearchBoard, opp: int) -> bool:
        """Check if opponent can win immediately on the given SearchBoard."""
        candidates = get_candidates(sb, 2)
        for cx, cy in candidates:
            sb.make_move(cx, cy, opp)
            wins = would_win(sb, cx, cy, opp)
            sb.unmake_move()
            if wins:
                return True
        return False


# ═══════════════════════════════════════════════════════════════
# ─── CaroAI Adapter ─────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════

class CaroAI:
    """Drop-in replacement for the original CaroAI class.
    Uses the new CaroEngine with BitBoard, VCF, TT, PVS+LMR."""

    def __init__(self, board):
        """Receive shared CaroBoard reference (same interface as original)."""
        self.board = board  # CaroBoard from the bot
        self.engine: Optional[CaroEngine] = None

    def _ensure_engine(self):
        """Create or resize engine if board dimensions changed."""
        w, h = self.board.hcount, self.board.vcount
        if self.engine is None or self.engine.w != w or self.engine.h != h:
            self.engine = CaroEngine(
                hcount=w, vcount=h,
                time_limit=4.0,
                use_vcf=True,
                max_depth=20,
            )

    def find_best_move(self, my_sym: int, opp_sym: int) -> Tuple[int, int]:
        """Find best move. Same interface as original CaroAI."""
        self._ensure_engine()

        # Build SearchBoard from CaroBoard
        sb = SearchBoard(self.board.hcount, self.board.vcount)
        sb.copy_from_caroboard(self.board)

        # Map symbols: the engine uses SYMBOL_X=1, SYMBOL_O=0
        # my_sym and opp_sym already use these constants

        # Use engine to find best move
        result = self.engine.find_best_move(sb, my_sym)
        return result
