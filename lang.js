var change_lang = {"en-US" : "en", "vi-VN": "vi"};
var langs = new Object();
langs.vi = {};
langs.en = {};
langs.vi.app_name = "Cờ Tướng AI";
langs.en.app_name = "Chinese Chess AI";

langs.vi.lang_resize = "Mức";
langs.en.lang_resize = "Level";

langs.vi.newgame = " Ván mới ";
langs.en.newgame = " New game ";
langs.vi.restart = " Ván mới ";
langs.en.restart = " Restart ";
langs.vi.play = " Vào Game ";
langs.en.play = " Play ";

langs.vi.lang_resize = "Mức";
langs.en.lang_resize = "Level";

langs.vi.pause = " Dừng ";
langs.en.pause = " Pause ";
langs.vi.lang_timer = "TGian";
langs.en.lang_timer = "Timer";
langs.vi.lang_move = "Đã đi";
langs.en.lang_move = "Moves";
langs.vi.lang_score = "Điểm";
langs.en.lang_score = "Score";

langs.vi.shared = "Chia sẻ";
langs.en.shared = "Shared";
langs.vi.undo = "Lùi lại";
langs.en.undo = "Undo";
langs.vi.new_reset = "Chơi lại";
langs.en.new_reset = "New/Reset";
langs.vi.finish = "Kết thúc";
langs.en.finish = "Finish";
langs.vi.back = "Quay lại";
langs.en.back = "Back";

langs.vi.tutorial = "Hướng dẫn";
langs.en.tutorial = "Tutorial";

langs.vi.label_one = " Chơi với máy";
langs.en.label_one = " Playing with the machine";
langs.vi.label_two = " Hai người chơi";
langs.en.label_two = " Two players";

langs.vi.userplaying = "Máy đang đi";
langs.en.userplaying = "The machine is playing";
langs.vi.userplease = "Mời bạn đi";
langs.en.userplease = "Invite you to play";

langs.vi.wanning = "Vị trị này đã có nước cờ rồi, bạn hãy chọn vị trí khác!";
langs.en.wanning = "This place has already played, you choose another place!";
langs.vi.lose = "Bạn đã thua rồi, máy đã thắng.<br>Bạn cần tập luyện nhiều hơn!";
langs.en.lose = "You have lost, the machine has won.<br>You need more practice!";

langs.vi.you = "Mời bạn đi";
langs.en.you = "Invite you to play";
langs.vi.player = "Mời người chơi thứ [user]";
langs.en.player = "Invite player [user]";

langs.vi.player1 = "nhất";
langs.en.player1 = "1st";
langs.vi.player2 = "hai";
langs.en.player3 = "second";
langs.vi.namepiece = {
    "rk":"Tướng đỏ", "ra":"Sỹ đỏ", "rb":"Tượng đỏ", "rn":"Mã  đỏ", "rr":"Xe đỏ", "rc": "Pháo  đỏ", "rp":"Tốt đỏ",
    "bk":"Tướng đen", "ba":"Sỹ đen", "bb":"Tượng đen", "bn":"Mã  đen", "br":"Xe đen", "bc": "Pháo  đen", "bp":"Tốt đen"
};
langs.en.namepiece = {
    "rk":"General Red", "ra":"Advisor Red", "rb":"Elephant Red", "rn":"Horse Red", "rr":"Chariot Red", "rc": "Cannon Red", "rp":"Soldier Red",
    "bk":"General Black", "ba":"Advisor Black", "bb":"Elephant Black", "bn":"Horse Black", "br":"Chariot Black", "bc": "Cannon Black", "bp":"Soldier Black"
};

langs.vi.userwin = "Xin chúc mừng người chơi thứ <b>[user]</b>.<br>Bạn là người chiến thắng!";
langs.en.userwin = "Congratulations to the [user] player. You are the winner!";


langs.vi.win = "<div class='alert'><img src='./images/win.png' width='32px' height='32px'><div><b>Xin chúc mừng!.</b><br>Bạn là người chiến thắng!<br>"
    +"Cùng <b><a href='javascript:download();'>chia sẻ</a></b> chiến thắng này với bạn bè bạn nhé?</div></div>";

langs.en.win = "<div class='alert'><img src='./images/win.png' width='32px' height='32px'><div><b>Congratulations!.</b><br>You are the winner!<br>"
    +"Let's enjoy this victory with your friends, <b><a href='javascript:download();'>OKAY</a>?</b></div></div>";



langs.vi.info = "<h2>Thông tin</h2>"+
    "<a class='close' onclick='close_info()'></a>"+
    "<p><b>Chinese Chess AI</b> hay game Cờ tướng là một trò chơi giải trí mang tính Trí tuệ cao. Môn đánh cờ này gây \"nghiện\" cho rất nhiều người và bạn cũng có thể không ngoại lệ. </p>" +
    "<p>Game Chinese Chess AI có một sự khác biệt lớn là bạn có thể chơi ở cấp độ người mới chơi hoặc chơi ở cấp độ bình thường; game kết hợp công nghệ AI giúp cho bạn có những trải nghiệm thú vị.</p>"+
    "<p></p>"+
    "<p class='ads'></p>"+
"<p></p>"+
"<h4>Một số ứng dụng thú vị khác có thể bạn quan tâm:</h4>";

langs.en.info = "<h2> Information </h2>" +
    "<a class='close' onclick='close_info()'> </a>" +
    "<p><b>Chinese Chess AI</b> or Chinese chess game is a highly intellectual game. Many people are addicted to this chess game and you can be no exception. </p>" +
    "<p>Game Chinese Chess AI has a big difference that you can play at the beginner level or play at the normal level; The game combines AI technology to help you have fun experiences.</p> "+
    "<p> </p>" +
    "<p class='ads'></p>" +
    "<p> </p>" +
    "<h4>More Game/App:</h4>"
    ;

langs.vi.rating = '<div class="win">'+
    '<h2 class="spin">Đánh giá ứng dụng</h2>'+
    '<p>Xin hãy giúp cho chúng tôi <b onclick="rating()">5*</b> để chúng tôi có động lực phát triển.</p>'+
    '<p>Hoặc bạn có thể <b onclick="download()">chia sẻ</b> cho bạn bè cùng trải nghiệm!</p>'+
    '<p style="text-align: center;" onclick="rating()"><img src="images/5start.png"></p>'+
    '<b>Cám ơn bạn đã ủng hộ chúng tôi!</b>'+
    '<div class="btn">'+
        '<button onclick="rating()" class="ui-btn-inline ui-icon-navigation ui-btn-icon-left">Đánh giá </button>'+
        '<button onclick="shared()" class="ui-btn-inline ui-icon-navigation ui-btn-icon-left">Chia sẻ</button>'+
    '</div>'+
    '</div>';
langs.en.rating = '<div class="win">'+
    '<h2 class = "spin"> App Review </h2>' +
    '<p> Please help us <b onclick="rating()">5*</b> so that we have a momentum for development.</p>' +
    '<p> Or you can <b onclick="download()"> share </b> to your friends with the same experience!</p>' +
    '<p style="text-align:center;" onclick="rating()"> <img src="images/5start.png"></p>'+
    '<b> Thanks for supporting us! </b>' +
    '<div class="btn">' +
        '<button onclick="rating()" class="ui-btn-inline ui-icon-navigation ui-btn-icon-left">Rating </button>' +
        '<button onclick="shared()" class="ui-btn-inline ui-icon-navigation ui-btn-icon-left">Share</button> '+
    '</div>' +
    '</div>';

langs.vi.exit = '<h2 class="spin">Thoát ứng dụng</h2>'+
    '<h3 style="color: red">Bạn chắc chắn muốn thoát ứng dụng chứ?</h3>'+
    '<p>Xin hãy giúp cho chúng tôi <b onclick="rating()">5*</b> để chúng tôi có động lực phát triển.</p>'+
    '<p>Hoặc bạn có thể <b onclick="shared()">chia sẻ</b> cho bạn bè cùng trải nghiệm!</p>'+
    '<p class="ads"></p>'+
    '<b>Cám ơn bạn đã ủng hộ chúng tôi!</b>'+
    '<div class="btn">'+
        '<button onclick="rating()" class="ui-btn ui-btn-inline ui-icon-navigation ui-btn-icon-left">Đánh giá </button>'+
        '<button onclick="shared()" class="ui-btn ui-btn-inline ui-icon-navigation ui-btn-icon-left">Chia sẻ</button>'+
        '<button onclick="exit()" class="ui-btn ui-btn-inline ui-icon-navigation ui-btn-icon-left">Thoát</button>'+
    '</div>';

langs.en.exit = '<h2 class="spin">Exit game</h2>'+
    '<h3 style="color: red">Are you sure you want to quit the game?</h3>'+
    '<p> Please help us <b onclick="rating()">5*</b> so that we have a momentum for development.</p>' +
    '<p> Or you can <b onclick="shared()"> share </b> to your friends with the same experience!</p>' +
    '<p class="ads"></p>'+
    '<b> Thanks for supporting us! </b>' +
    '<div class="btn">'+
    '<button onclick="rating()" class="ui-btn ui-btn-inline ui-icon-navigation ui-btn-icon-left">Rating </button>'+
    '<button onclick="shared()" class="ui-btn ui-btn-inline ui-icon-navigation ui-btn-icon-left">Share</button>'+
    '<button onclick="exit()" class="ui-btn ui-btn-inline ui-icon-navigation ui-btn-icon-left">Exit</button>'+
    '</div>';

var more_android = "<div class='app-other'>"+
    "<a href='javascript:openapp(\"com.thegioilaptrinh.danhcocaro\");'>"+
    "<img src='images/app/ic-caro.png'>"+
    "<label>Playing chess Caro - Tic tac toe - Gomoku</label>"+
    "</a>"+
    " </div>"+
    "<div class='app-other'>"+
    " <a href='javascript:openapp(\"net.thegioilaptrinh.chessai\");'>"+
    "<img src='images/app/ic-chessai.png'>"+
    "<label>Chess Kingdom AI</label>"+
    "</a>"+
    " </div>"+
    "<div class='app-other'>"+
    " <a href='javascript:openapp(\"com.thegioilaptrinh.sudoku\");'>"+
    "<img src='images/app/ic_sudoku.png'>"+
    "<label>Sudoku Kingdom</label>"+
    "</a>"+
    " </div>"+
    "<div class='app-other'>"+
    " <a href='javascript:openapp(\"com.thegioilaptrinh.drawcolor\");'>"+
    "<img src='images/app/ic-babyanddraw.png'>"+
    "<label>Draw And Color - Fill color</label>"+
    "</a>"+
    " </div>"+
    "<div class='app-other'>"+
    " <a href=\"javascript:openapp('com.truyenxuatichcu.truyenxuatichcu');\">"+
    "<img src='images/app/ic_amlich.png'>"+
    "<label>Xem lịch vạn niên - Tử Vi</label>"+
    "</a>"+
    "</div>"+
    "<div class='app-other'>"+
    " <a href='javascript:openapp(\"com.truyenxuatichcu.thuocloban\");'>"+
    "<img src='images/app/ic_thuocloban-web.png'>"+
    "<label>Ứng dụng phong thủy: Thước Lỗ Ban</label>"+
    "</a>"+
    " </div>"+
    "<div class='app-other'>"+
    " <a href=\"javascript:openapp('com.truyenxuatichcu.truyenxuatichcu');\">"+
    " <img src='images/app/ic_truyenxuatichcu-web.png'>"+
    "<label>Truyện Xưa Tích Cũ</label>"+
    " </a>"+
    "</div>"+
    "<div class='app-other'>"+
    "<a href=\"javascript:openapp('com.ynghiacacloaihoa');\">"+
    "<img src='images/app/ic_ynghiacacloaihoa-web.png'>"+
    "<label>Ý Nghĩa Các Loại Hoa</label>"+
    "</a>"+
    "</div>"+
    "<div class='app-other'>"+
    "<a href=\"javascript:openapp('net.thegioilaptrinh.cardssolitaire');\">"+
    "<img src='images/app/ic-card.png'>"+
    "<label>Bài Solitaire - Game xếp bài</label>"+
    "</a>"+
    "</div>"+
    "<div style='clear:both'><br></div>";
var more_ios = "<div class='app-other'>"+
    "<a href='javascript:openapp(\"id1385943418\");'>"+
    "<img src='images/app/ic-caro.png'>"+
    "<label>Playing chess Caro - Tic tac toe - Gomoku</label>"+
    "</a>"+
    " </div>"+
    "<div class='app-other'>"+
    " <a href='javascript:openapp(\"id1450468092\");'>"+
    "<img src='images/app/ic-chessai.png'>"+
    "<label>Chess Kingdom AI</label>"+
    "</a>"+
    " </div>"+
    "<div class='app-other'>"+
    " <a href='javascript:openapp(\"id1330360647\");'>"+
    "<img src='images/app/ic_thuocloban-web.png'>"+
    "<label>Ứng dụng phong thủy: Thước Lỗ Ban</label>"+
    "</a>"+
    " </div>"+
    "<div class='app-other'>"+
    " <a href='javascript:openapp(\"id1385943418\");'>"+
    "<img src='images/app/ic_sudoku.png'>"+
    "<label>Sudoku Kingdom</label>"+
    "</a>"+
    " </div>"+
    "<div class='app-other'>"+
    " <a href='javascript:openapp(\"id1412502126\");'>"+
    "<img src='images/app/ic-babyanddraw.png'>"+
    "<label>Draw And Color - Fill color</label>"+
    "</a>"+
    " </div>"+
    "<div style='clear:both'><br></div>";

langs.vi.setting = '<div class="win">'+
    '<h2 class="spin">Cài đặt ứng dụng</h2>'+
    '<p><img id="sound-icon" src=\'images/ic-sound.png\' width="20px"><label for="sound"> Âm thanh: </label><input id="sound" name="sound" type="checkbox" value="1" class="fr"></p>'+
    '<p><img id="sound-icon" src=\'images/ic-player-ai.png\' width="20px"><label for="user"> Two-player or AI: </label><input id="user" name="user" type="checkbox" value="1" checked class="fr"></p>'+
    '<p>Bàn cờ: </p>'+
    '<div id="theme">' +
        '<img src=\'images/themes/board.jpg\' width="64px" data-value="board">' +
        '<img src=\'images/themes/board-1.jpg\' width="64px" data-value="board-1">'+
    '</div>'+
    '<p>Quân cờ: </p>'+
    '<div id="chess-pieces">' +
        '<img src=\'images/chess-pieces/wikipedia.jpg\' width="64px" data-value="wikipedia">' +
        '<img src=\'images/chess-pieces/QuanCo.jpg\' width="64px" data-value="QuanCo">'+
        '<img src=\'images/chess-pieces/2.jpg\' width="64px" data-value="2">'+
        // '<img src=\'images/chess-pieces/3.jpg\' width="64px" data-value="3">'+
        // '<img src=\'images/chess-pieces/4.png\' width="64px" data-value="4">'+
        // '<img src=\'images/chess-pieces/5.png\' width="64px" data-value="5">'+
    '</div>'+
    '<div class="btn">'+
    '<button onclick="overlays.ovlClose()">Đóng</button>'+
    '</div>'+
    '</div>';
langs.en.setting = '<div class="win">'+
    '<h2 class="spin"> Setting App </h2>' +
    '<p><img id="sound-icon" src=\'images/ic-sound.png\' width="20px"><label for="sound"> Sound: </label><input id="sound" name="sound" type="checkbox" value="1" class="fr"></p>'+
    '<p><img id="sound-icon" src=\'images/ic-player-ai.png\' width="20px"><label for="user"> Two-player or AI: </label><input id="user" name="user" type="checkbox" value="1" checked class="fr"></p>'+
    '<p>Chess board: </p>'+
    '<div id="theme">' +
        '<img src=\'images/themes/board.jpg\' width="64px" data-value="board">' +
        '<img src=\'images/themes/board-1.jpg\' width="64px" data-value="board-1">'+
    '</div>'+
    '<p>Chess pieces: </p>'+
    '<div id="chess-pieces">' +
        '<img src=\'images/chess-pieces/wikipedia.jpg\' width="64px" data-value="wikipedia">' +
        '<img src=\'images/chess-pieces/QuanCo.jpg\' width="64px" data-value="QuanCo">'+
        '<img src=\'images/chess-pieces/2.jpg\' width="64px" data-value="2">'+
        // '<img src=\'images/chess-pieces/3.jpg\' width="64px" data-value="3">'+
        // '<img src=\'images/chess-pieces/4.png\' width="64px" data-value="4">'+
        // '<img src=\'images/chess-pieces/5.png\' width="64px" data-value="5">'+
    '</div>'+
    '<div class="btn">' +
    '<button onclick="overlays.ovlClose()">Close</button> '+
    '</div>' +
    '</div>';