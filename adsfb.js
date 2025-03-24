
// select the right Ad Id according to platform
var adid = (/(android)/i.test(navigator.userAgent)) ? ad_units.android : ad_units.ios;

function initAppFb() {
    if (! FacebookAds ) {
        // alert('Network not ready');
        ads.banner = 'admob'; ads.interstitial = 'admob';
        return;
    }
    adid = (/(android)/i.test(navigator.userAgent)) ? ad_units.android : ad_units.ios;

    registerAdEvents();
    FacebookAds.setOptions({
        isTesting: false,
        deviceHash: 'samsung-sm_g935f-988627424537593752' //tab: Baytrail44A50872
    });
    //quảng cáo full màn hình, popup
    // prepareInterstitial();
    // createSelectedBanner();
}
var nativeId = null;
function updateClickArea(){
    if (nativeId != null) {
        // change the click area
        var offset = $("#nativead").offset();
        var y = offset.top - $(window).scrollTop();
        var x = offset.left - $(window).scrollLeft();
        var w = $("#nativead").width();
        var h = $("#nativead").height();

        //Adjust based on stuff like headers and footers
        var yNEW = 0;
        var hNEW = 0;

        var topHeaderHeight = $('.app-bar').height();
        var windowHeight = $(window).height();
        var footerHeight = $('#menu').height();

        if( y<=topHeaderHeight ) {
            yNEW = topHeaderHeight;
            hNEW = h - ( topHeaderHeight - y );
        } else if( offset.top+h > ( windowHeight - footerHeight ) ) {
            yNEW = y;
            hNEW = (windowHeight - footerHeight) - offset.top;
        } else {
            yNEW = y;
            hNEW = h;
        }
        // hNEW = 100;
        // if(FacebookAds) FacebookAds.setNativeAdClickArea(nativeId, x, yNEW, w, hNEW);
        // if(FacebookAds) FacebookAds.setNativeAdClickArea(nativeId, x, y, w, h);
    }
}
$(window).scroll(function () {
    updateClickArea();
});
// optional, in case respond to events or handle error
function registerAdEvents() {
    // document.addEventListener('onAdFailLoad', function(data) {
    //     alert('error: ' + data.error + ', reason: ' + data.reason);
    // });
    document.addEventListener('onAdLoaded',function(data) {
        if (data.adType == "native") {
            var adRes = data.adRes;
            // alert( JSON.stringify(adRes) );

            // show ad
            nativeId = data.adId;
            var nativeAdContent = '<div style="padding:5px;border:1px solid #555; text-align: center">'
                +"<div style='float: right'><span onclick='openAdchoice()' class='ad_choice_img_span'><img class='adchoice_logo'  src='" + adRes.adchoice.url + "' width='" + adRes.adchoice.width + "' height='" + adRes.icon.height + "' /></span>"
                +"<a class='ad_choice'  onclick='openadchoicelink();'>AdChoices</a></div>"
                +'<b>'+adRes.title + '</b><br/>'
                // + adRes.body
                + "<br/>"+(adRes.rating != undefined ? ("Rating: " + adRes.rating + ", ") : '') + '<button class="button loading-pulse lighten primary">'+adRes.buttonText + "</button><br/>"
                + adRes.socialContext + "<br/>"
                + (!adRes.coverImage.url ? "<img src='" + adRes.icon.url + "' width='" + adRes.icon.width + "' height='" + adRes.icon.height + "'/>"
                    : "<img src='" + adRes.coverImage.url + "' width='" + adRes.coverImage.width + "' height='" + adRes.coverImage.height + "'/>")
                +"</div><br/>"
            ;
            $('#nativead').html(nativeAdContent);

            // alert(JSON.stringify(adRes));
            updateClickArea();
        }
    });
    document.addEventListener('onAdPresent', function(data) {
    });
    document.addEventListener('onAdLeaveApp', function(data) {
    });
    document.addEventListener('onAdDismiss', function(data) {
    });
    document.addEventListener('touchmove', function(){
        updateClickArea();
    });
}

function createSelectedBannerFb() {
    if( !banner && FacebookAds && adid.banner !='' ) {
        FacebookAds.createBanner({
            adId : adid.banner,
            overlap : false,
            adSize : 'SMART_BANNER',
            position:FacebookAds.AD_POSITION.BOTTOM_CENTER,
            // autoShow:true
        });
        banner = true;
        FacebookAds.showBanner(FacebookAds.AD_POSITION.BOTTOM_CENTER);
    }
}

function removeBannerFb() {
    if( banner && FacebookAds ) {
        FacebookAds.hideBanner();
        banner = false;
    }
}

function prepareInterstitialFb() {
    if(FacebookAds && adid.interstitial !='') {
        FacebookAds.prepareInterstitial({
                adId: adid.interstitial,
                autoShow: true
            }, function () {
                $('#splashscreen').hide();
            },
            function () {
                $('#splashscreen').hide();
            });
    } else {
        $('#splashscreen').hide();
    }
}
function onResize() {
    var s = document.getElementById('sizeinfo');
    s.innerHTML = "web view: " + window.innerWidth + " x "
        + window.innerHeight;
}
function createNativeAd() {
    if(FacebookAds && adid.nativeAd) {
        // FacebookAds.createNativeAd(adid.nativeAd);
    } else {
        $('#nativead').remove();
    }
}
function removeNativeAd() {
    $('#nativead').html("");
    if(FacebookAds) FacebookAds.removeNativeAd(nativeId);
}