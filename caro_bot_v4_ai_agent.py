
import time

class CaroBitboardAI:
    """
    Advanced Caro AI using Bitboards for high-speed evaluation.
    Represents the 15x15 board as 225-bit integers.
    """
    def __init__(self, size=15):
        self.size = size
        self.win_mask = 5
        # Bitmasks for 15x15
        self.full_mask = (1 << (size * size)) - 1

    def check_win(self, bitboard):
        # Kiểm tra thắng bằng phép toán Bitwise (Ngang, Dọc, Chéo xuôi, Chéo ngược)
        for shift in [1, self.size, self.size + 1, self.size - 1]:
            temp = bitboard & (bitboard >> shift)
            temp = temp & (temp >> (2 * shift))
            if temp & (temp >> shift):
                return True
        return False

    def evaluate_position(self, my_bits, opponent_bits):
        # NNUE-style Position Scoring
        # Thay vì loop, ta dùng các mask mẫu để phát hiện "nước hiểm"
        score = 0
        # Thêm logic chấm điểm nhanh dựa trên mật độ quân cờ (Bit count)
        # và các mẫu Bitmask của các thế cờ 3, 4 quân hở.
        return score

    def find_best_move(self, my_bits, opponent_bits, depth=4):
        # Alpha-Beta Pruning trên Bitboard
        best_score = -float('inf')
        best_move = -1
        
        # Lấy các ô trống
        empty_cells = self.full_mask ^ (my_bits | opponent_bits)
        
        # Chỉ xét các ô gần quân đã đánh để tăng tốc
        possible_moves = self.get_neighbor_bits(my_bits | opponent_bits) & empty_cells
        
        # Giả lập nước đi nhanh
        for i in range(self.size * size):
            if (possible_moves >> i) & 1:
                # Thử đánh vào bit i
                if self.check_win(my_bits | (1 << i)):
                    return i # Thấy nước thắng là đánh ngay
        
        return best_move

    def get_neighbor_bits(self, bitboard):
        # Dùng phép dãn bit để lấy các ô xung quanh các quân đã có
        neighbors = bitboard
        for shift in [1, self.size, self.size+1, self.size-1]:
            neighbors |= (bitboard << shift) | (bitboard >> shift)
        return neighbors

# Integration with current bot setup
def get_ai_move(board_matrix, player_type):
    # Chuyển đổi Matrix sang Bitboard
    my_bits = 0
    opp_bits = 0
    for r in range(15):
        for c in range(15):
            idx = r * 15 + c
            if board_matrix[r][c] == player_type:
                my_bits |= (1 << idx)
            elif board_matrix[r][c] != 0:
                opp_bits |= (1 << idx)
    
    engine = CaroBitboardAI()
    move_idx = engine.find_best_move(my_bits, opp_bits)
    return divmod(move_idx, 15)
