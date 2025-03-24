var url = 'http://truyenxuatichcu.com/';
var ratio = 1;
var data = [];
var index = 0;
var data_index = 0;
var is_child = false,
    is_history = false,
    is_items = false;

var screen = '';
var folder = 'Chinese_Chess AI';
var lang = 'en';

var chesspieces = 'wikipedia', theme = 'board', checked_sound = 1;
var time_start = 0;
var interval = '';
var player_ai = 1; //0: 2 player; 1: player with AI


//lấy thông tin setting
getSet();
var versionCode = "6";
var mobile_is = '';
if (!mobile_is) {
    if ((/(ipad|iphone|ipod)/i.test(navigator.userAgent))) {
        mobile_is = 'ios';
    } else if ((/(android)/i.test(navigator.userAgent))) {
        mobile_is = 'android';
    }
}
function dataloading() {
    dataloadingclose();
    var html_loading = '<div id="_loading"><div class="_overlay"></div><div class="loader_ads"></div></div>';
    // overlays.ovlOpen(html_loading, '', '', false);
    $('body').append(html_loading);
}
function dataloadingclose() {
    // $('#splashscreen').hide();
    $('#_loading').remove();
    overlays.ovlClose();
}
document.addEventListener("deviceready", function () {
    fixMobile();
    checkLanguage();
    document.addEventListener("backbutton", function () {
        // e.preventDefault();
        exitgame();
        // createNativeAd();
        // navigator.app.backHistory();
        return;
    }, false);
}, false);

function exitgame() {
    var data = langs[lang].exit;
    overlays.ovlOpen(data, $(window).width() * 0.7, 'auto');
}
function checkLanguage() {
    navigator.globalization.getPreferredLanguage(
        function (language) {
            lang = change_lang[language.value] ? change_lang[language.value] : lang;
            // alert('language: ' + JSON.stringify(language) + '\n');
            fixlang();
        }, function () { fixlang(); }
    );
}
function fixlang() {
    // console.log(langs[lang].app_name);
    // $('#res').html( langs[lang].app_name );
    // $('#lang_resize').html( langs[lang].lang_resize );
    // $('#label_play-size').html( langs[lang].lang_resize );
    // $('#newgame').val( langs[lang].newgame );
    // $('#play').val( langs[lang].play );
    // $('#label_userisX').html( langs[lang].label_userisX );
    // $('#label_userisO').html( langs[lang].label_userisO );
    // $('#label_one').html( langs[lang].label_one );
    // $('#label_two').html( langs[lang].label_two );
    $('[data-lang]').each(function () {
        var valuelang = $(this).data('lang');
        // console.log( valuelang+ ' Lang: '+ langs[lang][valuelang] );
        if (langs[lang][valuelang]) {
            $('[data-lang="' + valuelang + '"]').html(langs[lang][valuelang]);
            $('[data-lang="' + valuelang + '"]').val(langs[lang][valuelang]);
        }
    });
}
function fixMobile() {
    $('[data-showmobile]').each(function () {
        var value = $(this).data('showmobile');
        if (mobile_is != value) {
            $(this).hide();
        }
    });
}
function close() {
    $(".box").hide();
    // $('.footer').hide();
    overlays.ovlClose();
    $('.ads').html('');
    removeNativeAd();
}
function reset() {
    index = 0;
    data_index = 0;
    is_child = is_history = is_items = false;
    data = [];
    $('#menu').css('z-index', 10);
}

function gameback() {
    $('.box').hide();
    // $('#splashscreen').show();
    overlays.ovlClose();
    removeBanner();
    removeNativeAd();
}

function openhistory() {
    $('.box').hide();
}
function info() {
    var info = langs[lang].info;
    // if (/(android)/i.test(navigator.userAgent)) {
    //     info += more_android;
    // } else {
    //     info += more_ios;
    // }
    if (screen == 'menu') {
        $('#splashscreen').hide();
    }
    $('.box').hide();
    $("#res").hide();
    $('#info').show();
    $('#info').html(info);
    $('.ads').html("<div id='nativead'></div>");

    createNativeAd();
    createSelectedBanner();
}
function close_history() {
    $("#history").hide();
    $("#nativead").remove();

    removeBanner();

    if (data_index != 0) {
        $('#board').show();
    } else {
        reset();
    }
}
function close_info() {
    $("#res").show();
    $("#info").hide();
    $('#info').html('');
    $('.box').hide();
    if (screen == 'menu') {
        screen = '';
        $('#splashscreen').show();
    } else {
        $('#board').show();
    }

    $(".ads").html(""); removeBanner();
}

function setRating() {
    var data = langs[lang].rating;
    overlays.ovlOpen(data, $(window).width() * 0.7, 'auto');
}
function rating() {
    overlays.ovlClose();
    var http = 'https://play.google.com/store/apps/details?id=net.thegioilaptrinh.chinesechessai';
    if (/(android)/i.test(navigator.userAgent)) {
        http = 'market://details?id=net.thegioilaptrinh.chinesechessai';
    } else if (/(ipod|iphone|ipad)/i.test(navigator.userAgent)) {
        http = 'itms-apps://itunes.apple.com/app/apple-store/id1455059392';
    }

    window.open(http, '_system');
    $('.ads').html('');
    removeNativeAd();
}

function shared(title, subject, image, link) {
    overlays.ovlClose();
    overlays.ovlOpen('<div class="loader"></div><br><h4>Loading ...</h4>', $(window).width() * 0.5, 'auto');
    $('#_ovl .centerOvl').css('background', 'none');

    title = title ? title : langs[lang].app_name;
    subject = subject ? subject : langs[lang].about;
    image = image ? image : '';
    link = link ? link : '';
    if (/(android)/i.test(navigator.userAgent)) {
        link = 'https://play.google.com/store/apps/details?id=net.thegioilaptrinh.chinesechessai';
    } else {
        link = 'https://itunes.apple.com/us/app/apple-store/id1455059392';
    }
    // return alert(link);
    window.plugins.socialsharing.share(title, subject, [image], link, overlays.ovlClose(), overlays.ovlClose());
    $('.ads').html('');
    removeNativeAd();
    prepareInterstitialRandom();
}

function download(callback) {
    callback = (typeof callback === 'function') ? callback : function (file) {
        // if( confim("Hãy chia sẻ chiến thắng với bạn bè nhé?") ) {
        shared('', '', file, '');
        // }
    };
    overlays.ovlClose();

    var filetype = 'image/jpeg';
    //Get data from canvas
    // var img_b64 = canvas.toDataURL(filetype);
    //Create blob from DataURL
    // var img_blob = dataURItoBlob(img_b64);
    var filename = Date.now();
    return html2canvas($("#board")[0]).then(function (canvas) {
        // canvas.getContext("2d");
        var base64 = canvas.toDataURL(filetype);
        // return base64;
        // $("[id*=hfImageData]").val(base64);
        // __doPostBack(btnExport.name, "");
        // window.location = base64;
        // return;
        var img_blob = dataURItoBlob(base64);
        window.requestFileSystem(LocalFileSystem.PERSISTENT, 0, function (fs) {
            // alert('file system open: ' + JSON.stringify(fs.root) + ' == '+filename );
            createDirectory(fs.root, folder);
            fs.root.getFile(folder + "/" + filename + ".jpg", { create: true, exclusive: false }, function (fileEntry) {
                writeFile(fileEntry, img_blob, callback);
                // closeloading();

                return fs.root.nativeURL + filename + ".jpg";
            });
        });
    });
}
// downloadLnk.addEventListener('click', download, false);

function exit() {
    navigator.app.exitApp();
}

function openapp(app_id) {
    var http = 'https://play.google.com/store/apps/details?id=';
    if (/(android)/i.test(navigator.userAgent)) {
        http = 'market://details?id=';
    } else if (/(ipod|iphone|ipad)/i.test(navigator.userAgent)) {
        http = 'itms-apps://itunes.apple.com/app/apple-store/';
    }
    window.open(http + app_id, '_system');
}

function lose() {
    var html = '<section id="falling-demo"><div id="container"><div class="leaf-01">' +
        '<img src="./images/cry.png" width="32px" height="32px"></div>' +
        '<div class="leaf-02"><img src="./images/cry.png" width="32px" height="32px"></div>' +
        '<div class="leaf-03"><img src="./images/cry.png" width="32px" height="32px"></div></div></section>';
    $('body').append(html);

    // $('#search-depth').prop('disabled', '');
    clearInterval(interval);
    var html_lose = langs[lang].lose;
    setTimeout(overlays.ovlOpen(html_lose, $(window).width() * 0.7, 'auto'), 3000);
    setTimeout(function () { $('#falling-demo').remove(); }, 10000);

    if (adsposition.win == '1') {
        prepareInterstitialRandom();
    }

    if (!checked_sound) {
        return;
    }
    // document.getElementById('audio_lose').play();
}

function showVietTimePlay() {
    var time = new Date().getTime();
    // window.status = time
    time_start = time_start ? time_start : time;
    $('#res-time').html(Math.round((time - time_start) / 1000) + 's');
    // alert( Math.round( time-time_start) );
    clearInterval(interval);
    interval = setInterval(showVietTimePlay, 1000);
}

function setting() {
    var data = $('#setting').html();//langs[lang].setting;
    overlays.ovlOpen(data, $(window).width() * 0.8, 'auto');

    $('.selMoveMode').on('change', function () {
        $(".selMoveMode").val(this.value);
    });

    $('#theme img').on('click', function () {
        theme = $(this).data('value');
        $('#board').removeClass();
        $('#board').addClass(theme);
        // console.log(theme);
        onSetting('theme', theme);
        $('#theme img').css('border', '0');
        $(this).css('border', '1px solid green');
    });
    $('#chess-pieces img').on('click', function () {
        chesspieces = $(this).data('value');
        cfg.pieceTheme = 'img/chesspieces/' + chesspieces + '/{piece}.png';
        // var folder = $('.piece-417db').data('src', 'chesspieces/', '/' );
        // $('.piece-417db').earch(function( index ) {
        //     $(this).data('src');
        // });
        // console.log(folder);
        // game.board( game.fen() );
        board = ChessBoard('board', cfg);
        board.position(game.fen());
        onSetting('chesspieces', chesspieces);
        $('#chess-pieces img').css('border', '0');
        $(this).css('border', '1px solid green');
    });

    $('#sound').on('click', function () {
        checked_sound = $("input[name='sound']:checked").val() || 0;
        if (checked_sound == 1) {
            $('#sound-icon').prop('src', 'images/ic-sound.png');
        } else {
            $('#sound-icon').prop('src', 'images/ic-sound-mute.png');
        }
        onSetting('sound', checked_sound ? 1 : 0);
    });

    $('#user').on('click', function () {
        player_ai = $(this).data('value');
        cfg.onDrop = 'n/a';
        cfg.onSnapEnd = 'n/a';
        if (player_ai) {
            cfg.onDrop = 'onDrop';
            cfg.onSnapEnd = 'onSnapEnd';
        }
        startGame();
    });
    // console.log(theme);
    $('#theme img').each(function () {
        if ($(this).data('value') == theme) {
            $(this).css('border', '1px solid green');
        }
    });
    $('#chess-pieces img').each(function () {
        if ($(this).data('value') == chesspieces) {
            $(this).css('border', '1px solid green');
        }
    });
    // checked_sound = 1;
    if (checked_sound == 1) {
        $('#sound').prop('checked', 'checked');
        $('#sound-icon').prop('src', 'images/ic-sound.png');
    } else {
        $('#sound').prop('checked', '');
        $('#sound-icon').prop('src', 'images/ic-sound-mute.png');
    }
}

function game_win() {
    win();
    // $('#search-depth').prop('disabled', '');
    clearInterval(interval);
    var html = langs[lang].win;
    setTimeout(overlays.ovlOpen(html, $(window).width() * 0.7, 'auto'), 3000);

    if (adsposition.win == '1') {
        prepareInterstitialRandom();
    }
}
var changeUser = function () {
    var Temp = document.getElementById("iCoDen").src;
    document.getElementById("iCoDen").src = document.getElementById("iCoDo").src;
    document.getElementById("iCoDo").src = Temp;
}

function getHuongdan(datafile) {
    var datalink = 'huong-dan/index_' + lang + '.html';
    // alert(datalink);
    // resolveIosPath("cdvfile://"+datalink).then((src) => {
    //     alert(src)
    // })
    // return;
    // console.log(datalink);
    var xhr = new XMLHttpRequest();
    xhr.open("POST", datalink, true);
    xhr.responseType = "text";
    xhr.onload = function () {
        var info = "";
        if (this.readyState == 4 && (this.status == 200 || this.status == 0)) {
            info += xhr.response;
        } else {
            info += 'Chúng tôi không tìm thấy phần mà bạn yêu cầu ! Có thể nó không có trong hệ thống hay đã bị loại bỏ!';
        }
        if (screen == 'menu') {
            $('#splashscreen').hide();
        }
        $('.box').hide();
        $("#res").hide();
        $('#info').show();
        $('#info').html(info);
        $('.ads').html("<div id='nativead'></div>");

        // if (mobile_is == 'ios')
        //     $('#info').css('top', 'calc(0px - env(safe-area-inset-top, 0) )');
        createNativeAd();
        createSelectedBanner();

    };
    // xhr.addEventListener("load", dataloading() );
    xhr.send();
}