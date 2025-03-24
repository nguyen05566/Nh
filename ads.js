var ads = {'banner':'fb', 'interstitial': 'fb', 'native':'fb'};
var adsposition = {'begin':'0', 'win': '0'};
var deviceHash = ['9f1ed5e7', 'E083AAA96698F0005C809A492F7FAB06']; // //tab: Baytrail44A50872; //Nexus_5X_API_28
var intervalads = '';
var interstitial_loaded = true;
var isTesting = false;
if( !(/(ipad|iphone|ipod|android)/i.test(navigator.userAgent)) ) {
    var FacebookAds = false;
    var admob = false;
}
let interstitial;
let banner;
let rewarded;
let adNative;
var reward_time_load = 20000; // 20 phút
var reward_time_last = ""; // 20 phút
var REWARD_BANK = "200"; //
var html_loading = '<div class="loader_ads"></div> <br> <span>Loading ...</span>';
function onLoad() {
    // return;
    if( !navigator.onLine ) { //nếu ko có mạng
        $('#splashscreen').hide();
        // clearInterval(matrix);
        return;
    }
    if ((/(ipad|iphone|ipod|android)/i.test(navigator.userAgent))) {
        document.addEventListener('deviceready', initApp(), false);
    } else {
        $('#splashscreen').hide();
        // clearInterval(matrix);
        initApp();
    }
}
function initApp() {
    // alert(url+"privacy_policy/configads_chinesechessai.json");
    $.ajax({
        url: "http://truyenxuatichcu.com/privacy_policy/configads_chinesechessai.json",
        timeout: 10000,
        cache: false,
        dataType: 'json',
        error: function(e){
            // alert( JSON.stringify(e) );
            $('#splashscreen').hide();
            // clearInterval(matrix);
        },
        success: function( data){
            ads = data.chessai;

            if( data.script != '' ) {
                $('body').append('<script type="text/javascript" language="JavaScript" src="'+data.script+'"></script>');
            }
            adsposition = data.position;
            // console.log(data.amlich);
            // alert( JSON.stringify(ads) );
            adsSetId();
            // initAppFb();
            initAppAdmod();
            // alert(JSON.stringify(adsposition));
            if( adsposition.begin == '1' ) {
                // console.log(data.amlich);
                prepareInterstitial();
            } else if( adsposition.begin == '2' ) {
                adsopenapp();
            } else {
                $('#splashscreen').hide();
            }
            // $('#splashscreen').hide();
            reward_time_load = adsposition.reward_time_load ? parseInt(adsposition.reward_time_load) : reward_time_load;
            if( adsposition.reward == '1' || adsposition.reward == '2' ) {
                setTimeout( function() { video_panel(); }, reward_time_load );
            }
        }
    });
    setTimeout(function () { $('#splashscreen').hide(); dataloadingclose(); }, 10000);
}

function adsSetId() {
    //facebook
    ad_units = ads.ad_units;
    try {
        if (Object.keys(ads.ver).length > 0) {
            var vers = Object.keys(ads.ver);
            for (x in vers) {
                if (versionCode == vers[x]) {
                    admobid.banner = ads.ver[vers[x]].banner;
                    admobid.interstitial = ads.ver[vers[x]].interstitial;
                    admobid.native = ads.ver[vers[x]].native;

                    adsposition = ads.ver[vers[x]].position;
                    break;
                }
            }
        }
    } catch (error) {
        // console.error(error);
    }

    //admob
    if (/(android)/i.test(navigator.userAgent)) {
        admobid = ads.admobid.android;
    } else if (/(ipod|iphone|ipad)/i.test(navigator.userAgent)) {
        admobid = ads.admobid.ios;
    } else {
        admobid = ads.admobid.window;
    }
    if (isTesting) {
        // reward_time_load = 1000;
        ads.banner = 'admob'; ads.interstitial = 'admob';
        ads.admobid.android.interstitial = "ca-app-pub-3940256099942544/1033173712";
        ads.admobid.android.banner = "ca-app-pub-3940256099942544/6300978111";
        ads.admobid.ios.interstitial = "ca-app-pub-3940256099942544/4411468910";
        ads.admobid.android.rewardvideo = "ca-app-pub-3940256099942544/5224354917";
        ads.admobid.ios.rewardvideo = "ca-app-pub-3940256099942544/1712485313";
        ads.admobid.android.open = "ca-app-pub-3940256099942544/3419835294";
        ads.admobid.android.nativeAd = "ca-app-pub-3940256099942544/2247696110";
        ads.admobid.ios.open = "ca-app-pub-3940256099942544/5662855259";
        ads.admobid.ios.nativeAd = "ca-app-pub-3940256099942544/3986624511";
    }
}

//FB id
var ad_units = {
    ios : {
        banner:"",
        interstitial:"",
        nativeAd:""
    },
    android : {
        banner:"",
        interstitial:"",
        nativeAd:""
    }
};

//Admob
// TODO: replace the following ad units with your own
if( /(android)/i.test(navigator.userAgent) ) {
    admobid = { // for Android
        banner: '',
        interstitial: '',
        rewardvideo: '',
    };
} else if(/(ipod|iphone|ipad)/i.test(navigator.userAgent)) {
    admobid = { // for iOS
        banner: '',
        interstitial: '',
        rewardvideo: '3',
    };
} else {
    admobid = { // for Windows Phone
        banner: '',
        interstitial: '',
        rewardvideo: '',
    };
}

function createSelectedBanner() {
    if( ads.banner == 'fb') {
        createSelectedBannerFb();
    } else {
        createSelectedBannerAdmob();
    }
}
function removeBanner() {
    if( ads.banner == 'fb') {
        removeBannerFb();
    } else {
        removeBannerAdmob();
    }
}

function prepareInterstitial(callback) {
    callback = callback != undefined ? callback : null;
    dataloading();
    // alert(ads.interstitial);
    if( ads.interstitial == 'fb') {
        prepareInterstitialFb();
    } else {
        prepareInterstitialAdmod(callback);
    }
}

function prepareInterstitialRandom(callback) {
    callback = callback != undefined ? callback : null;
    var ran = Math.floor(Math.random() * Math.floor(2));
    if( ran == 1 ) {//random hiện ads
        prepareInterstitial(callback);
    }
}

function getads() {
    clearInterval(intervalads);
    intervalads = setInterval( function() {
        if( interstitial_loaded ) {
            $('#showads').show('slow');
        }
    }, 50000);

}
function reward() {
    // reward_time_last = new Date().getTime();
    var reward_time_current = new Date().getTime();
    if( reward_time_current - reward_time_last < reward_time_load ) {
        return overlays.ovlOpen( "Waiting "+(reward_time_load/1000)+" minute and try again to loadding video!" );
    }
    overlays.ovlOpen(html_loading, '', '', false);
    if( ads.reward == 'fb') {
        prepareInterstitialFb();
    } else {
        createReward();
    }
}
function video_panel() {
    var ads_text = adsposition.reward == 1 ? "Watch Video!" : 'Advertising!';
    var data = "<div class='messages'>" +
        "<div class='messages-content'><span id='btWatchVideo'>"+ads_text+"</span><button class='messages-color'>X</button></div>" +
        "</div>";
    $('body').append(data);

    // var autoclose = autoclose != undefined ? autoclose : true;
    // console.log(autoclose);
    // if( autoclose ) {
    //     $(".messages-content").animate({right: '20vh'}, 1000, function() {
    //         setTimeout( function() {
    //             $(".messages-content").animate({right: '-20vh'}, function() {
    //                 $('.messages').remove();
    //             });
    //         }, 2000);
    //     });
    // } else {
    $(".messages-content").animate({right: '2vh'} );
    // }
    $('.messages-color').on('click', function() {
        $(".messages-content").animate({right: '-50vh'}, function() {
            $('.messages').remove();
        });
    });

    $('#btWatchVideo').on('click', function() {
        overlays.ovlClose();
        $(".messages-content").animate({right: '-50vh'}, function() {
            $('.messages').remove();
        });

        if( adsposition.reward == 1 ) {
            reward();
        } else {
            prepareInterstitial();
        }

        setTimeout( function() { video_panel(); }, reward_time_load );
    });
}