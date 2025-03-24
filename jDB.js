/**
 * Created by vietnux on 27/10/2017.
 */
var database = "chess_ai";
var ver = "1.1";
var tb = "chess_ai_history";
var db;
var key_setting = '';
var value_setting = '';

//biến
var data_db = [];
// PhoneGap is ready
function onInsert( ) {
    try {
        onOpen();
        db.transaction( populate, error, success);
        deletedbold( tb );
    } catch (err) {
        alert("Error processing open SQL: " + err);
    }
}
function onOpen() {
    try {
        if( !db ) {
            db = window.openDatabase(database, ver, tb, 200000);
            db.transaction( function(tx) {
                tx.executeSql('CREATE TABLE IF NOT EXISTS '+tb+' ( difficulty, time, timeplay )');
            }, error, success);

        }
    } catch (err) {
        alert("Error processing open database: " + err);
    }
}

function setItems( ) {
    // onOpen();
    // db.transaction( function(tx){
    //     var time = Date.now();
    //     var difficulty = parseInt(difficulty.options[difficulty.selectedIndex].value);
    //     tx.executeSql('CREATE TABLE IF NOT EXISTS '+tb+' ( difficulty, time, timeplay )');
    //     tx.executeSql("INSERT INTO "+tb+" (difficulty, time, timeplay) VALUES ('"+difficulty+"', '"+time+"', '"+timeFinished+"')");
    //
    // }, error, success);

    var time = Date.now();
    var score = {
        difficulty: difficulty,
        time: time,
        timeplay: timeFinished,
    };
    console.log( score );
    var scores = JSON.parse(localStorage.getItem(tb));

    if (scores === null) {
        scores = [];
    }
    scores.push(score);
    localStorage.setItem(tb, JSON.stringify(scores));
}

// Populate the database
function populate(tx) {
    try {
        // onOpen();
        // tx.executeSql('DROP TABLE IF EXISTS angiodau');
        var time = Date.now();
        // var id = data_index>0 ? data_index : 0;
        var diff = parseInt($('#difficulty').val());
        tx.executeSql('CREATE TABLE IF NOT EXISTS '+tb+' ( difficulty, time, timeplay )');
        tx.executeSql("REPLACE INTO "+tb+" (difficulty, time, timeplay) VALUES ('"+diff+"', '"+time+"', '"+timeFinished+"')");
    } catch (err) {
        alert("Error processing SQL: " + err);
    }
}
function select( ) {
    // return $("#history").show();
    try{
        onOpen();
        // var db = window.openDatabase(database, ver, db_title, 200000);
        db.transaction( function(tx) {
            var sql = "SELECT * FROM "+tb;
            if( where!='' ) {
                sql += " WHERE "+where;
            }
            sql += " ORDER BY time DESC";
            return tx.executeSql( sql, [],
                function(tx, results) {
                    var len = results.rows.length;
                    $('#history ul').html('');
                    if(len>0) {
                        for (var i = 0; i < len; i++) {
                            // alert(results.rows.item(i)['title']);
                            var item = difficultys[results.rows.item(i)['difficulty']-1];
                            var timeplay = results.rows.item(i)['timeplay'];
                            var d = new Date();
                                d.setTime(results.rows.item(i)['time']);
                            var time = d.toLocaleTimeString() +' '+d.toLocaleDateString();
                            data_db.push( item );
                            var html = "<li id='"+i+"'>" +
                                "<a class='delete' onclick='delete_history(\""+item+"\", "+i+");'></a>" +
                                "<label for='item_"+i+"'>"+item+" - "+timeplay+"<div style='float: right'>"+time+"</div></label>" +
                                "</li>";
                            $('#history ul').append(html);
                            if(i==5) {
                                $('#history ul').append("<li><div id='nativead'></div></li>");
                            }
                        }
                    }else {
                        var html = "<li style='color: red'><b><i>[Chưa có lịch sử]</i></b></li>";
                        $('#history ul').append(html);
                        $('#history ul').append("<li><div id='nativead'></div></li>");
                    }
                    close();
                    $("#history").show();

                    // createSelectedBanner();
                    // createNativeAd();
                }, error );
        }, error, success);
    } catch (err) {
        alert("Truy vấn lỗi: "+err.message);
    }
}

// Transaction error callback
function error (tx, err) {
    alert("Error trace processing SQL: "+err);
}

// Transaction success callback
function success() {
    // alert("success!");
}

// Transaction delete
function deletedbold( tb ) {
    try{
        onOpen();
        db.transaction( function(tx) {
            var sql = "delete from "+tb + " WHERE time<(UNIX_TIMESTAMP()-(30*24*3600))";
            return tx.executeSql( sql );
        }, null, null);
    } catch (err) {
        alert("Xóa dũ liệu cũ lỗi: "+err.message);
    }
}
function delete_history( title, i ) {
    if( confirm("Bạn chắc chắn muốn xóa "+title+" chứ?") ) {
        try{
            onOpen();
            db.transaction( function(tx) {
                // alert("DELETE FROM "+history+" WHERE title='"+title+"'");
                tx.executeSql("DELETE FROM "+tb+" WHERE title='"+title+"'");
            }, error, function() {
                $('#history ul #'+i).remove();
            });
        } catch (err) {
            alert("Xóa lịch sử "+title+" lỗi: "+err.message);
        }
    }

}


function onOpenSetting() {
    try {
        if( !db ) {
            db = window.openDatabase(database, ver, 'setting', 200000);
            db.transaction( function(tx) {
                tx.executeSql('CREATE TABLE IF NOT EXISTS setting ( key, value )');
            }, error, success);
        }
    } catch (err) {
        alert("Error processing open database setting: " + err);
    }
}

function onSetting( key, value ) {
    key_setting = key;
    value_setting = value;
    localStorage.setItem(key_setting, value_setting);
}
function getSet() {
    if( player_ai == 1 ) {$('#user').prop('checked', 'checked');}
    //theme
    var dbtheme = localStorage.getItem('theme');

    if( dbtheme ) {
        $('#board').removeClass();
        theme = results.rows.item(1);
        $('#board').addClass(theme);
    }

    //quân cờ
    var dbchesspieces = localStorage.getItem('chesspieces' );
    if( dbchesspieces ) {
        chesspieces = dbchesspieces;
        cfg.pieceTheme = 'img/chesspieces/'+chesspieces+'/{piece}.png';
        board = ChessBoard('board', cfg);
        if(game.fen() > 1) {
            // console.log(game.fen());
            board.position(game.fen());
        }

    }

    //âm thanh
    var chk_sound = localStorage.getItem('sound');
    checked_sound = chk_sound ? chk_sound : checked_sound;
    if( checked_sound == 1 ) {
        $('#sound').prop('checked', 'checked');
    } else {
        $('#sound').prop('checked', '');
    }
}