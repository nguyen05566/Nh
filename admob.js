// var admobid = {};

function initAppAdmod() {
    if (! admob ) {
        // console.log('Network not ready');
        // ads.banner = 'fb'; ads.interstitial = 'fb'; ads.native = 'fb';
        return;
    }

    document.addEventListener('deviceready', async () => {
        if (cordova.platformId === 'ios') {
            admob.requestTrackingAuthorization().then(console.log);
        }
        await admob.start().catch( (err) => { $('#splashscreen').hide();  dataloadingclose(); console.error(err); } );
        admob.configRequest({
            testDeviceIds: deviceHash,//['988627424537593752'],
        });
    });
}

// if(( /(ipad|iphone|ipod|android|windows phone)/i.test(navigator.userAgent) )) {
//     document.addEventListener('deviceready', initApp, false);
// } else {
//     initApp();
// }

function createSelectedBannerAdmob() {
    document.addEventListener('deviceready', async () => {
        banner = banner ? banner : new admob.BannerAd({
            adUnitId: mobile_is == 'android' ? ads.admobid.android.banner :  ads.admobid.ios.banner ,
            position: "bottom",
            offset: 100,
            size: "SMART_BANNER",
        });
        await removeBannerAdmob();
        await banner.show();
    }, false);
}

// Hide the banner
// admob.banner.hide()
function removeBannerAdmob() {
    if(admob) {
        try{ banner.hide();}
        catch(e) {console.log(e);};
    }
}
function showBannerAtPosition(){
    if(admob) admob.banne.show( admob.AD_POSITION.TOP_CENTER );
}

function prepareInterstitialAdmod(callback) {
    callback = callback != undefined ? callback : null;
    // alert(JSON.stringify(ads.admobid.android.interstitial));
    if (admob && admobid.interstitial) {
        document.addEventListener('deviceready', async () => {
            interstitial = interstitial ? interstitial : new admob.InterstitialAd({
                adUnitId: mobile_is == 'android' ? ads.admobid.android.interstitial : ads.admobid.ios.interstitial,
            });
            // alert(JSON.stringify(interstitial));
            await interstitial.load().catch((err) => { $('#splashscreen').hide();dataloadingclose(); console.error(err); callback(); })
                .then(async () => await interstitial.show());
                
            await interstitial.on('loadfail', async (event) => {
                // document.addEventListener('admob.ad.loadfail', async (event) => {
                $('#splashscreen').hide();
                dataloadingclose();
                callback();
                // overlays.ovlClose();
                // jQuery('#app').show();
            });

            await interstitial.on('load', async (event) => {
                // document.addEventListener('admob.ad.load', async (event) => {
                // console.log(event);
                // alert('1');
                interstitial_loaded = true;

            });
            await interstitial.on('showfail', async (event) => {
                // document.addEventListener('admob.ad.showfail', async (event) => {
                // console.log(event);
                $('#splashscreen').hide();
                dataloadingclose();
                callback();

            });

            await interstitial.on('dismiss', async (event) => {
                // document.addEventListener('admob.ad.dismiss', async () => {
                // jQuery('#splashscreen').hide();
                // dataloadingclose();
                setTimeout(function () { $('#splashscreen').hide();dataloadingclose(); callback(); }, 1000);
                // overlays.ovlClose();
                // jQuery('#app').show();
                // console.log("======");

                if (adsposition.reward == '2') {
                    reward_time_last = reward_time_current;
                    setTimeout(function () { video_panel(); }, reward_time_load);
                }
                // Once a interstitial ad is shown, it cannot be shown again.
                // Starts loading the next interstitial ad as soon as it is dismissed.

                await interstitial.load();
                
            });
        }, false);
    } else {
        $('#splashscreen').hide();
        dataloadingclose();
        callback();
        // overlays.ovlClose();
    }
}
function createReward() {
    if(admob && admobid.rewardvideo) {
        document.addEventListener('deviceready', async () => {
            // admob.rewardVideo.load({
            //     id: {
            //         // replace with your ad unit IDs
            //         android: ads.admobid.android.rewardvideo,
            //         ios: ads.admobid.ios.rewardvideo,
            //     },
            // }).then(() => admob.rewardVideo.show())

            rewarded = rewarded ? rewarded : new admob.RewardedAd({
                adUnitId: mobile_is == 'android' ? ads.admobid.android.rewardvideo :  ads.admobid.ios.rewardvideo ,
            })

            await rewarded.load();
            await rewarded.show();
        }, false)
    }
}

function nativeAds(native_element) {
    nativeAdsHide();
    document.addEventListener('deviceready', async () => {
        adNative = new admob.NativeAd({
            adUnitId: mobile_is == 'android' ? ads.admobid.android.nativeAd :  ads.admobid.ios.nativeAd ,
        })
        var native = document.createElement("div");
        native.setAttribute("id","native");
        $(native_element).html("");
        $(native_element).append(native);
        return await adNative.load().then(  () =>$(native_element).show() )
            .then(() => adNative.showWith( native ) );
    })

    document.addEventListener('admob.ad.load', async (evt) => {
        if (evt.ad instanceof admob.NativeAd) {
            // handle event here
        }
    })
}
function nativeAdsHide() {
    adNative ? adNative.hide() : '';
    $('#native').remove();
}

document.addEventListener('admob.banner.loadfail', async (event) => {
    console.log(event);
    // overlays.ovlOpen("<h4>Video failed to load, please wait a few minutes and try again</h4>");
});

document.addEventListener('admob.banner.load', async (event) => {
    console.log(event);
    // document.getElementById('showAd').disabled = false
});
document.addEventListener('admob.banner.open', async (event) => {
    console.log(event);
    // document.getElementById('showAd').disabled = false
});
document.addEventListener('admob.banner.impression', async () => {
    await banner.hide();
});

// document.addEventListener('admob.banner.close', async (event) => {
//     console.log(event)
//     // admob.rewardvideo.prepare()
// });
// document.addEventListener('admob.banner.exit_app', async (event) => {
//     console.log(event)
//     // admob.rewardvideo.prepare()
//     $('#splashscreen').hide();
//     overlays.ovlClose();
//     $(".messages").remove();
// });


document.addEventListener('admob.rewarded.loadfail', async (event) => {
    console.log(event);
});

// document.addEventListener('admob.rewardvideo.load', async (event) => {
//     console.log(event)
//     // document.getElementById('showAd').disabled = false
// });
// document.addEventListener('admob.rewardvideo.open', async (event) => {
//     console.log(event)
//     // document.getElementById('showAd').disabled = false
// });
// document.addEventListener('admob.rewardvideo.exit_app', async (event) => {
//     console.log(event)
//     // document.getElementById('showAd').disabled = false
// });
// document.addEventListener('admob.rewardvideo.start', async (event) => {
//     console.log(event)
//     // document.getElementById('showAd').disabled = false
// });
document.addEventListener('admob.rewarded.reward', async (event) => {
    console.log(event);
    // document.getElementById('showAd').disabled = false
});

document.addEventListener('admob.rewarded.dismiss', async (event) => {
    // console.log(event)

    // admob.rewardvideo.prepare()
    if( adsposition.reward == '1' ) {
        setTimeout( function() { video_panel(); }, reward_time_load );
    }
    overlays.ovlClose();
    // overlays.ovlClose();
});

//Called when reward video ad completes playing.
document.addEventListener('admob.rewarded.impression', () => {
    // handle event
})

function adsopenapp() {
    if( admob ) {
        document.addEventListener('deviceready', async () => {
            // await admob.start()
            const ad = await new admob.AppOpenAd({
                adUnitId: mobile_is == 'android' ? ads.admobid.android.open : ads.admobid.ios.open,
                // orientation: orientation_screen,
            })
            // alert(ads.admobid.android.open);
            if(ad) {
                await ad.load().catch((err) => {
                    $('#splashscreen').hide();
                    dataloadingclose();
                    console.error(err);
                });
                await ad.show();
            } else {
                $('#splashscreen').hide();dataloadingclose();
            }

            document.addEventListener('resume', async () => {
                // console.error("Resum");
                setTimeout( function(){ $('#splashscreen').hide(); dataloadingclose(); }, 1500);
                // if (!await ad.show()) {
                //     await ad.load().catch((err) => {
                //         console.error(err);
                //     });
                // }
            }, false,)
        }, false)
    } else {
        $('#splashscreen').hide();dataloadingclose();
    }

    document.addEventListener('admob.ad.show', async (evt) => {
        if (evt.ad instanceof admob.AppOpenAd) {
            // handle event here
        }
    })

}

document.addEventListener('admob.ad.loadfail', async (evt) => {
    $('#splashscreen').hide(); dataloadingclose();console.error(evt);
})
document.addEventListener('admob.ad.showfail', async (evt) => {
    $('#splashscreen').hide(); dataloadingclose();console.error(evt);
})
document.addEventListener('admob.ad.dismiss', async (evt) => {
    // $('#splashscreen').hide(); dataloadingclose();console.error(evt);
})
document.addEventListener('admob.ad.impression', async (evt) => {
    // $('#splashscreen').hide(); dataloadingclose();console.error(err);
})

