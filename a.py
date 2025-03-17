import requests
import time
import os
import json
import random
from time import sleep

# Thêm thư viện giải captcha
from anticaptchaofficial.recaptchav2proxyless import *

# Hàm giải captcha
def solve_captcha(site_key, url):
    solver = recaptchaV2Proxyless()
    solver.set_verbose(1)
    solver.set_key("ANTICAPTCHA_API_KEY")  # Thay bằng API key của bạn
    solver.set_website_url(url)
    solver.set_website_key(site_key)

    token = solver.solve_and_return_solution()
    if token != 0:
        print("Captcha solved! Token: " + token)
        return token
    else:
        print("Error: " + solver.error_code)
        return None

def countdown(time_sec):
    for remaining_time in range(time_sec, -1, -1):
        colors = [
                "\033[1;37mN\033[1;36mD\033[1;35mK \033[1;32mT\033[1;31mO\033[1;34mO\033[1;33mL\033[1;31m\033[1;32m",
                "\033[1;34mN\033[1;31mD\033[1;37mK \033[1;36mT\033[1;32mO\033[1;35mO\033[1;37mL\033[1;31m\033[1;32m",
                "\033[1;31mN\033[1;37mD\033[1;36mK \033[1;33mT\033[1;35mO\033[1;32mO\033[1;34mL\033[1;31m\033[1;32m",
                "\033[1;32mN\033[1;33mD\033[1;34mK \033[1;35mT\033[1;36mO\033[1;37mO\033[1;36mL\033[1;31m\033[1;32m",
                "\033[1;37mN\033[1;34mD\033[1;35mK \033[1;36mT\033[1;32mO\033[1;33mO\033[1;31mL\033[1;31m\033[1;32m",
                "\033[1;34mN\033[1;33mD\033[1;37mK \033[1;35mT\033[1;31mO\033[1;36mO\033[1;36mL\033[1;31m\033[1;32m",
                "\033[1;36mN\033[1;35mD\033[1;31mK \033[1;34mT\033[1;37mO\033[1;35mO\033[1;32mL\033[1;31m\033[1;32m",
        ]
        for color in colors:
            print(f"\r{color}|{remaining_time}| \033[1;31m", end="")
            time.sleep(0.12)

    print("\r                          \r", end="")
    print("\033[1;35mĐang Nhận Tiền         ", end="\r")

from colorama import Fore

def INSTAGRAM():
    url1_2 = 'https://gateway.golike.net/api/instagram-account'
    checkurl1_2 = ses.get(url1_2, headers=headers).json()
    user_INS = []
    account_id1 = []
    account = []
    STT = []
    STATUS = []
    tong = 0
    dem = 0
    i = 1
    for data in checkurl1_2['data']:
        usernametk = data['instagram_username']
        user_INS.append(data['username'])
        account_id1.append(data['id'])
        STT.append(i)
        STATUS.append(Fore.GREEN + "Hoạt Động" + Fore.RED)
        account.append(usernametk)
        print(f'\033[1;97m•[🌸]➭\033[1;36m [{i}] \033[1;91m=> \033[1;97mTên Tài Khoản┊\033[1;32m🌸 :\033[1;93m {usernametk} \033[1;91m=> \033[1;97mStatus|\033[1;32m🌸 :\033[1;93m {STATUS[-1]}')
        i += 1
    print(Fore.RED + '_________________________________________________________')
    choose = int(input('\033[1;97m[\033[1;91m🌸\033[1;97m] \033[1;36m  Nhập Tài Khoản : '))
    os.system('cls' if os.name == 'nt' else 'clear')
    if choose >= 1 or choose <= len(user_INS):
        user_INS = user_INS[choose - 1:choose]
        account_id1 = account_id1[choose - 1:choose]
        user_tiktok = user_INS[0]
        account_id = account_id1[0]
        checkfile2 = os.path.isfile('COOKIEINS' + str(account_id) + '.txt')
        if checkfile2 == False:
            banner()
            cookieX = input(Fore.GREEN + '\033[1;97m[\033[1;91m🌸\033[1;97m] \033[1;36m  Nhập Cookie Instagram: ')
            createfile = open('COOKIEINS' + str(account_id) + '.txt', 'w')
            createfile.write(cookieX)
            createfile.close()
            readfile = open('COOKIEINS' + str(account_id) + '.txt', 'r')
            cookieINS = readfile.read()
            readfile.close()
        else:
            readfile = open('COOKIEINS' + str(account_id) + '.txt', 'r')
            cookieINS = readfile.read()
            readfile.close()
        os.system('cls' if os.name == 'nt' else 'clear')
        banner()
        choose = int(input(Fore.RED + '\033[1;97m[\033[1;91m🌸\033[1;97m] \033[1;36m  Nhập Số Lượng Job : '))
        headerINS = {
            'accept': '*/*',
            'accept-language': 'vi,en-US;q=0.9,en;q=0.8',
            'content-type': 'application/x-www-form-urlencoded',
            'cookie': cookieINS,
            'origin': 'https://www.instagram.com',
            'priority': 'u=1, i',
            'referer': 'https://www.instagram.com/p/C9RAZEJNjPC/',
            'sec-ch-prefers-color-scheme': 'dark',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
            'user-agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1',
            'x-asbd-id': '129477',
            'x-csrftoken': cookieINS.split('csrftoken=')[1].split(';')[0],
            'x-ig-app-id': '936619743392459',
            'x-ig-www-claim': 'hmac.AR1Jw2LrciyrzAQskwSVGREElPZZJZjW74y38oTjDnNHOu9e',
            'x-instagram-ajax': '1014868636',
            'x-requested-with': 'XMLHttpRequest',
        }
        param = {
            'instagram_account_id': account_id,
            'data': 'null',
        }
        DELAY = int(input(Fore.RED + '\033[1;97m[\033[1;91m🌸\033[1;97m] \033[1;36m  Nhập Delay : '))
        print("\033[97m════════════════════════════════════════════════")

        for i in range(choose):
            try:
                job = f'https://gateway.golike.net/api/advertising/publishers/instagram/jobs?instagram_account_id={account_id}&data=null'
                nos = ses.get(job, headers=headers, params=param).json()

                if nos['status'] == 200:
                    ads_id = nos['data']['id']
                    object_id = nos['data']['object_id']
                    job_type = nos['data']['type']

                    if job_type == 'follow':
                        url = f'https://www.instagram.com/api/v1/friendships/create/{object_id}/'
                        data = {
                            'container_module': 'profile',
                            'nav_chain': 'PolarisFeedRoot:feedPage:8:topnav-link',
                            'user_id': object_id,
                        }
                        response = requests.post(url, headers=headerINS, data=data).text
                        countdown(DELAY)

                        if '"status":"ok"' in response:
                            url = 'https://gateway.golike.net/api/advertising/publishers/instagram/complete-jobs'
                            json_data = {
                                'instagram_account_id': account_id,
                                'instagram_users_advertising_id': ads_id,
                                'async': True,
                                'data': 'null',
                            }
                            time.sleep(3)
                            response = requests.post(url, headers=headers, json=json_data).json()

                            if response.get('success') == True:
                                dem += 1
                                local_time = time.localtime()
                                h, m, s = [f"{t:02d}" for t in (local_time.tm_hour, local_time.tm_min, local_time.tm_sec)]
                                prices = response['data']['prices']
                                tong += prices

                                chuoi = (
                                    f"\033[1;31m\033[1;36m{dem}\033[1;31m\033[1;97m | "
                                    f"\033[1;33m{h}:{m}:{s}\033[1;31m\033[1;97m | "
                                    f"\033[1;32msuccess\033[1;31m\033[1;97m | "
                                    f"\033[1;31mfollow\033[1;31m\033[1;32m\033[1;97m | "
                                    f"\033[1;32m Ẩn ID\033[1;97m | \033[1;32m+{prices} \033[1;97m| "
                                    f"\033[1;33m{tong} vnđ"
                                )
                                print(chuoi)
                            else:
                                # Xử lý skip job
                                skipjob = 'https://gateway.golike.net/api/advertising/publishers/twitter/skip-jobs'
                                params = {
                                    'ads_id': ads_id,
                                    'account_id': account_id,
                                    'object_id': object_id,
                                    'async': 'true',
                                    'data': 'null',
                                    'type': job_type,
                                }
                                checkskipjob = ses.post(skipjob, params=params).json()

                                if checkskipjob['status'] == 200:
                                    print(Fore.RED + str(checkskipjob['message']))

                        elif '"status":"fail"' in response and '"spam":true' in response:
                            print(Fore.RED + "Tài khoản này bị nhã Follow")
                        elif '"status":"fail"' in response and '"require_login":true' in response:
                            print('Cookie die rồi! Tôi rất tiếc')
                            os.remove(f'COOKIEINS{account_id}.txt')
                            return 0

                    elif job_type == 'like':
                        like_id = nos['data']['description']
                        url = f'https://www.instagram.com/api/v1/web/likes/{like_id}/like/'
                        response = requests.post(url, headers=headerINS).text
                        countdown(DELAY)

                        if '"status":"ok"' in response:
                            # Tương tự như trên với 'follow', xử lý 'like' công việc
                            url = 'https://gateway.golike.net/api/advertising/publishers/instagram/complete-jobs'
                            json_data = {
                                'instagram_account_id': account_id,
                                'instagram_users_advertising_id': ads_id,
                                'async': True,
                                'data': 'null',
                            }
                            time.sleep(3)
                            response = requests.post(
                                'https://gateway.golike.net/api/advertising/publishers/instagram/complete-jobs',
                                headers=headers,
                                json=json_data,
                            ).json()
                            if response['success'] == True:
                                dem += 1
                                local_time = time.localtime()
                                hour = local_time.tm_hour
                                minute = local_time.tm_min
                                second = local_time.tm_sec

                                # Định dạng giờ, phút, giây
                                h = f"{hour:02d}"
                                m = f"{minute:02d}"
                                s = f"{second:02d}"
                                prices = response['data']['prices']

                                # Cộng dồn giá trị prices vào tổng tiền
                                tong += prices

                                chuoi = (
                                    f"\033[1;31m\033[1;36m{dem}\033[1;31m\033[1;97m | "
                                    f"\033[1;33m{h}:{m}:{s}\033[1;31m\033[1;97m | "
                                    f"\033[1;32msuccess\033[1;31m\033[1;97m | "
                                    f"\033[1;31mlike\033[1;31m\033[1;32m\033[1;32m\033[1;97m |"
                                    f"\033[1;32m Ẩn ID\033[1;97m | \033[1;32m+{prices} \033[1;97m| "
                                    f"\033[1;33m{tong} vnđ"
                                )
                                print(chuoi)
                            else:
                                skipjob = 'https://gateway.golike.net/api/advertising/publishers/twitter/skip-jobs'
                                PARAMS = {
                                    'ads_id': ads_id,
                                    'account_id': account_id,
                                    'object_id': object_id,
                                    'async': 'true',
                                    'data': 'null',
                                    'type': type,
                                }
                                checkskipjob = ses.post(skipjob, params=PARAMS).json()
                                if checkskipjob['status'] == 200:
                                    message = checkskipjob['message']
                                    print(Fore.RED + str(message))
                                    PARAMSr = {
                                        'ads_id': ads_id,
                                        'account_id': account_id,
                                        'object_id': object_id,
                                        'async': 'true',
                                        'data': 'null',
                                        'type': type,
                                    }
                        elif '"status":"fail"' in response and '"spam":true' in response:
                            print(Fore.RED + "Tài khoản này bị chặn like")
                        elif '"status":"fail"' in response and '"require_login":true' in response:
                            print('Cookie die rồi! Tôi rất tiếc')
                            os.remove(f'COOKIEINS{account_id}.txt')
                            return 0
                        # pass

                else:
                    print(nos['message'])
                    countdown(15)

            except Exception as e:
                print(f"Lỗi xảy ra: {str(e)}")
                continue

def banner():
    os.system("cls" if os.name == "nt" else "clear")
    banner = f"""
\033[1;31m ██████╗ ██╗   ██╗██╗   ██╗██╗  ██╗██╗  ██╗ █████╗ ███╗   ██╗██╗  ██╗
\033[1;36m ██╔══██╗██║   ██║╚██╗ ██╔╝██║ ██╔╝██║  ██║██╔══██╗████╗  ██║██║  ██║
\033[1;32m ██║  ██║██║   ██║ ╚████╔╝ █████╔╝ ███████║███████║██╔██╗ ██║███████║
\033[1;34m ██║  ██║██║   ██║  ╚██╔╝  ██╔═██╗ ██╔══██║██╔══██║██║╚██╗██║██╔══██║
\033[1;35m ██████╔╝╚██████╔╝   ██║   ██║  ██╗██║  ██║██║  ██║██║ ╚████║██║  ██║
\033[1;31m ╚═════╝  ╚═════╝    ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═══╝╚═╝  ╚═╝

               BOX ZALO: https://zalo.me/g/nguadz335
               ADMIN : DUY KHÁNH
               YTB : REVIEWTOOL247NDK
\033[1;97m= = = = = = = = = = = = = = = = = = = = = = = = = = = = = 
"""
    for X in banner:
        sys.stdout.write(X)
        sys.stdout.flush()
        sleep(0.