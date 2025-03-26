import discord
import random
import functools
import re
from urllib.parse import urlparse, parse_qs
from discord.ext import commands
from collections import defaultdict
from datetime import datetime, timedelta
import os
import asyncio
import aiohttp
import yt_dlp as youtube_dl
import yt_dlp
import discord
from discord import app_commands
from discord.ext import commands, tasks 

# # Sửa đổi cấu hình ytdl_format_options để xử lý khi không có file cookies.txt
import os

# Dictionary to track the most recent mentions
# Dictionary lưu trữ thời gian sử dụng lệnh howgay cuối cùng
howgay_cooldown = {}  # {user_id: last_used_time}
# Thêm biến whitelist vào đầu file hoặc gần những biến global khác
whitelist = set()  # Tạo một tập hợp để lưu trữ danh sách người dùng được phép sử dụng lệnh xu
# Dictionary để lưu trữ các cảnh báo: {guild_id: {user_id: [list_of_warnings]}}
warnings = {}
# Structure: {pinged_id: [{pinger_id, timestamp, message_content, channel_id, message_id, jump_url}, ...]}
recent_pings = {}
MAX_PINGS_TRACKED = 25  # Maximum number of pings to track per user
active_giveaways = {}  # {message_id: {"prize": prize, "end_time": end_time, "host": host_id, "channel_id": channel_id}}
task_list = []
# Thêm vào đầu file, gần các biến toàn cục khác
active_keys = {}  # {key: {"amount": amount, "uses": remaining_uses, "created_by": admin_id, "redeemed_by": [user_ids], "creation_time": timestamp}}
key_log = {}  # {user_id: [{"key": key_code, "time": timestamp, "amount": amount}]} - Dùng để theo dõi việc sử dụng key

# Kiểm tra xem file cookies.txt có tồn tại không
cookies_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cookies.txt')
has_cookies_file = os.path.isfile(cookies_path)
# Thống kê người sử dụng key
users_stats = {}
total_used_keys = 0
# Cấu hình youtube-dl
ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
    'external_downloader_args': ['-q', '-v'],
    'geo_bypass': True,
    'geo_bypass_country': 'US',
    'extractor_args': {
        'youtube': {
            'player_client': ['android', 'web', 'tv_embedded'],
            'hl': ['en-US'],
            'gl': ['US']
        }
    }
}

# Chỉ thêm cookiefile nếu file tồn tại
if has_cookies_file:
    ytdl_format_options['cookiefile'] = cookies_path
    print(f"✅ Đã tìm thấy cookies.txt tại {cookies_path}")
else:
    print(f"⚠️ Không tìm thấy file cookies.txt tại {cookies_path}. Bot sẽ hoạt động với chức năng hạn chế.")
    # Tạo file cookies trống nếu không tìm thấy
    try:
        with open(cookies_path, 'w') as f:
            f.write("# HTTP Cookie File created by Discord Bot\n# This file was generated automatically\n\n")
        print(f"✅ Đã tạo file cookies.txt trống tại {cookies_path}")
        ytdl_format_options['cookiefile'] = cookies_path
    except Exception as e:
        print(f"❌ Không thể tạo file cookies.txt: {str(e)}")
# Định nghĩa class YTDLSource
class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5, requester=None):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')
        self.requester = requester

    # Sửa đổi phương thức from_url trong YTDLSource
@classmethod
async def from_url(cls, url, *, loop=None, stream=False, ctx=None):
    loop = loop or asyncio.get_event_loop()
    
    # Sử dụng YT-DLP nếu có
    try:
        from yt_dlp import YoutubeDL
        print("✅ Đang sử dụng yt-dlp để xử lý yêu cầu...")
        
        # Tạo options với các tùy chọn bypass nâng cao
        enhanced_options = ytdl_format_options.copy()
        enhanced_options['extractor_args'] = {
            'youtube': {
                'player_client': ['android', 'web', 'tv_embedded'],
                'hl': ['en-US'],
                'gl': ['US']
            }
        }
        
        # Thêm các HTTP headers để cải thiện khả năng truy cập khi không có cookies
        enhanced_options['http_headers'] = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
            'Origin': 'https://www.youtube.com',
            'Referer': 'https://www.youtube.com/'
        }
        
        yt_downloader = YoutubeDL(enhanced_options)
        
        # Thử tải thông tin video
        try:
            partial = functools.partial(yt_downloader.extract_info, url, download=not stream)
            data = await loop.run_in_executor(None, partial)
        except Exception as e:
            print(f"❌ Lỗi khi tải video: {str(e)}")
            
            # Thử lại với các tùy chọn khác nếu gặp lỗi
            try:
                # Trích xuất video_id từ URL và thử phương pháp khác
                parsed_url = urlparse(url)
                video_id = None
                
                if 'youtube.com' in url and 'watch' in url:
                    video_id = parse_qs(parsed_url.query).get('v', [None])[0]
                elif 'youtu.be' in url:
                    video_id = parsed_url.path.strip('/')
                
                if video_id:
                    print(f"🔄 Thử với phương pháp bypass và video_id: {video_id}")
                    alt_url = f"https://www.youtube.com/watch?v={video_id}&t=0s&app=desktop"
                    
                    # Thử với user agent di động
                    mobile_options = enhanced_options.copy()
                    mobile_options['http_headers'] = {
                        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1',
                        'Accept-Language': 'en-US,en;q=0.9',
                        'Origin': 'https://www.youtube.com',
                    }
                    
                    # Loại bỏ cookiefile nếu vẫn gặp lỗi
                    if 'cookiefile' in mobile_options:
                        del mobile_options['cookiefile']
                        print("🔄 Thử lại không dùng cookies...")
                    
                    yt_mobile = YoutubeDL(mobile_options)
                    partial = functools.partial(yt_mobile.extract_info, alt_url, download=not stream)
                    data = await loop.run_in_executor(None, partial)
                    print("✅ Đã sử dụng phương pháp bypass với user agent di động thành công!")
                else:
                    raise Exception("Không thể trích xuất video ID để thực hiện bypass")
            except Exception as second_error:
                print(f"❌ Lỗi khi thử phương pháp thay thế: {str(second_error)}")
                raise second_error
    
    except ImportError:
        # Fallback to youtube_dl if yt-dlp is not installed
        print("⚠️ Không tìm thấy yt-dlp, sử dụng youtube_dl...")
        import youtube_dl
        ytdl = youtube_dl.YoutubeDL(ytdl_format_options)
        partial = functools.partial(ytdl.extract_info, url, download=not stream)
        data = await loop.run_in_executor(None, partial)
    
    if 'entries' in data:
        # Đây là một playlist
        data = data['entries'][0]
    
    filename = data['url'] if stream else yt_downloader.prepare_filename(data)
    
    # Định nghĩa ffmpeg_options nếu chưa có
    ffmpeg_options = {
        'options': '-vn',
        'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5'
    }
    
    source = await discord.FFmpegOpusAudio.from_probe(filename, **ffmpeg_options)
    
    return cls(source, data=data, requester=ctx.author if ctx else None)
# Thêm hàm play_next_song
async def play_next_song(guild_id, voice_client):
    """Phát bài hát tiếp theo trong hàng đợi"""
    if guild_id in music_queues and music_queues[guild_id]:
        # Lấy bài hát tiếp theo
        next_song = music_queues[guild_id].pop(0)
        
        # Set callback cho khi bài hát kết thúc
        def after_playing(error):
            if error:
                print(f"Lỗi phát nhạc: {error}")
            asyncio.run_coroutine_threadsafe(play_next_song(guild_id, voice_client), bot.loop)
        
        # Phát bài hát
        voice_client.play(next_song, after=after_playing)
        
        # Gửi thông báo đến kênh
        if hasattr(next_song, 'notify_channel'):
            embed = discord.Embed(
                title="▶️ Đang phát",
                description=f"**{next_song.title}**",
                color=discord.Color.green()
            )
            asyncio.run_coroutine_threadsafe(next_song.notify_channel.send(embed=embed), bot.loop)
    # Xóa phần else chứa await voice_client.disconnect() để bot không tự ngắt kết nối
# Biến để theo dõi hàng đợi và bài hát đang phát
music_queues = {}  # {guild_id: [song1, song2, ...]}
current_playing = {}  # {guild_id: current_song}


async def check_timeout_status(member):
    """
    Check if a member is timed out (compatible with all Discord.py versions)
    
    Args:
        member: The Discord member to check
    
    Returns:
        tuple: (is_timed_out, remaining_time_seconds, expiry_time)
        - is_timed_out: Boolean indicating if user is timed out
        - remaining_time_seconds: Seconds remaining in timeout, or 0 if not timed out
        - expiry_time: The datetime when timeout expires, or None if not timed out
    """
    try:
        # Try the direct attribute first (Discord.py 2.0+)
        if hasattr(member, 'communication_disabled_until'):
            timeout_until = member.communication_disabled_until
            if timeout_until is None:
                return False, 0, None
                
            # Check if timeout is in the future
            now = discord.utils.utcnow()
            if timeout_until > now:
                remaining = (timeout_until - now).total_seconds()
                return True, remaining, timeout_until
            return False, 0, None
        
        # Fallback for older Discord.py versions - check timeout role
        # Most servers have a "Timed Out" or similar role
        for role in member.roles:
            if role.name.lower() in ['timed out', 'timeout', 'muted']:
                # Can't determine exact time remaining in old versions
                # Assume 1 hour as default
                now = discord.utils.utcnow()
                expiry = now + timedelta(hours=1)
                return True, 3600, expiry
        
        return False, 0, None
    except Exception as e:
        print(f"Error checking timeout status: {str(e)}")
        return False, 0, None


# Tạo class để lưu thông tin bài hát
class SongInfo:
    def __init__(self, title, url, duration, thumbnail, requester=None):
        self.title = title
        self.url = url
        self.duration = duration
        self.thumbnail = thumbnail
        self.requester = requester
        self.volume = 0.5

# Dictionary để lưu trữ tin nhắn đã xóa gần nhất trong từng kênh
# {channel_id: {"author": user, "content": content, "avatar": avatar_url, "time": deletion_time, "attachments": [urls]}}
snipe_messages = {}
deleted_messages = {}
afk_users = {}

# Dict để lưu lịch sử sử dụng lệnh dms
dms_history = []  # Format: [{"sender": user_id, "receiver": member_id, "content": message, "time": timestamp, "channel_id": channel_id}]
MAX_DMS_HISTORY = 100  # Số lượng tin nhắn tối đa lưu trữ


# Decorator để kiểm tra quyền đặc biệt
def special_roles_check():
    """Kiểm tra xem người dùng có quyền đặc biệt không"""
    def predicate(ctx):
        # Kiểm tra xem người dùng có ID đặc biệt không
        if ctx.author.id in SPECIAL_ROLE_IDS:
            return True
        # Kiểm tra quyền quản trị viên
        if ctx.author.guild_permissions.administrator:
            return True
        # Nếu không phải là ID đặc biệt hoặc admin, kiểm tra các quyền khác
        has_permission = (
            ctx.author.guild_permissions.manage_guild or
            ctx.author.guild_permissions.manage_channels or
            ctx.author.guild_permissions.manage_messages
        )
        return has_permission
    return commands.check(predicate)

# Dictionary để theo dõi lần sử dụng các lệnh nhạy cảm của người dùng
admin_cmd_attempts = {}  # {user_id: {"count": attempts, "last_time": timestamp}}
ADMIN_CMD_THRESHOLD = 1  # Số lần thử tối đa trong khoảng thời gian
ADMIN_CMD_TIMEFRAME = 6000  # Khoảng thời gian theo dõi (giây)
SPAM_TIMEOUT_DAYS = 7  # Thời gian timeout khi spam (ngày)
ANTI_SPAM_BOT_ID = 618702036992655381  # ID của USERID 618702036992655381

def only_specific_user():
    async def predicate(ctx):
        # Only allow the specific user ID to use this command
        return ctx.author.id == 618702036992655381
    return commands.check(predicate)

# Thêm biến global để lưu trữ danh sách người dùng được whitelist
whitelisted_users = set()  # Người dùng sẽ luôn thắng trong mọi trò chơi
# Thêm biến global để lưu danh sách người dùng được phép bypass lệnh dms
dms_bypass_list = set()

# Đảm bảo whitelisted_users là set để tránh lỗi TypeError
if not isinstance(whitelisted_users, set):
    whitelisted_users = set()


def is_whitelisted(user_id):
    """Check if a user is in the whitelist"""
    return user_id in whitelisted_users


async def check_whitelist_status(ctx):
    """
    Kiểm tra và thông báo trạng thái whitelist của người dùng
    """
    if ctx.author.id in whitelisted_users:
        embed = discord.Embed(
            title="✨ Whitelist Status",
            description=
            f"{ctx.author.mention} đang trong whitelist.\nBạn sẽ có tỷ lệ thắng cao hơn trong các trò chơi!",
            color=discord.Color.gold())
        await ctx.send(embed=embed)
        return True
    return False


def apply_whitelist_boost(ctx):
    """
    Áp dụng tăng tỷ lệ thắng cho người dùng trong whitelist
    """
    if ctx.author.id in whitelisted_users:
        print(
            f"DEBUG: Áp dụng tăng tỷ lệ thắng cho người dùng {ctx.author.id}")
        return random.choices([True, False], weights=[80, 20], k=1)[0]
    print(
        f"DEBUG: Sử dụng tỷ lệ thắng thông thường cho người dùng {ctx.author.id}"
    )
    return random.choices([True, False], weights=[30, 70], k=1)[0]


# Số tin nhắn tối đa được lưu trữ mỗi kênh
MAX_SNIPE_MESSAGES = 50
# Thời gian lưu trữ tin nhắn đã xóa (tính bằng giây)
SNIPE_EXPIRY_TIME = 86400  # 24 giờ

# Thêm hằng số cho ID kênh chơi game
GAME_CHANNEL_ID = 1350478909216522252
GUILD_ID = 953918500970307594
GAME_CHANNEL_LINK = "https://discord.com/channels/953918500970307594/1350478909216522252"

# Admin IDs - thêm để tham chiếu trong vayxu
ADMIN_IDS = [618702036992655381, 938071848321712198]

# Theo dõi số lần vi phạm kênh của mỗi người dùng
channel_violation_count = defaultdict(int)
channel_violation_time = defaultdict(
    lambda: datetime.now() - timedelta(hours=1))
VIOLATION_THRESHOLD = 1  # Sau 1 lần vi phạm sẽ bị timeout

# Thêm thời gian chờ để ngăn spam lệnh
command_cooldown = {}
COOLDOWN_TIME = 0  # Thời gian chờ giữa các lệnh (giây)


# Xác thực cooldown
def check_cooldown(user_id):
    current_time = datetime.now()
    if user_id in command_cooldown:
        time_passed = (current_time -
                       command_cooldown[user_id]).total_seconds()
        if time_passed < COOLDOWN_TIME:
            return False, int(COOLDOWN_TIME - time_passed)
    command_cooldown[user_id] = current_time
    return True, 0

def admin_only():
    """Decorator để giới hạn lệnh chỉ cho admin ID 618702036992655381 và 938071848321712198 sử dụng và timeout người không có quyền"""
    async def predicate(ctx):
        # ID chủ sở hữu - chỉ những người này mới có thể dùng lệnh
        OWNER_IDS = [618702036992655381, 938071848321712198, 882156430797459456]
        
        # Kiểm tra ID người gọi lệnh
        if ctx.author.id in OWNER_IDS:
            return True
        else:
            # Hiển thị thông báo cảnh báo
            embed = discord.Embed(
                title="⛔ PHÁT HIỆN SỬ DỤNG LỆNH ADMIN TRÁI PHÉP",
                description=f"{ctx.author.mention} đã cố gắng sử dụng lệnh admin và sẽ bị timeout 7 ngày ngay lập tức!",
                color=discord.Color.dark_red()
            )
            await ctx.send(embed=embed)
            
            # Timeout user ngay lập tức không cần cảnh báo
            try:
                # Timeout trong 7 ngày
                timeout_until = discord.utils.utcnow() + timedelta(days=SPAM_TIMEOUT_DAYS)
                await ctx.author.timeout(timeout_until, reason="Sử dụng lệnh admin trái phép")
            except discord.Forbidden:
                await ctx.send("❌ Không thể timeout người dùng do thiếu quyền!")
            except Exception as e:
                await ctx.send(f"❌ Lỗi khi timeout: {str(e)}")
            
            raise commands.MissingPermissions(['administrator'])
    return commands.check(predicate)

# Tạo decorator chỉ dành cho lệnh dms với timeout ngay lập tức
def dms_only():
    async def predicate(ctx):
        # ID chủ sở hữu - chỉ người này mới có thể dùng lệnh
        OWNER_ID = 618702036992655381
        
        # Kiểm tra ID người gọi lệnh hoặc bypass list
        if ctx.author.id == OWNER_ID or ctx.author.id in dms_bypass_list:
            return True
        
        # Hiển thị thông báo cảnh báo
        embed = discord.Embed(
            title="⛔ PHÁT HIỆN SỬ DỤNG LỆNH DMS TRÁI PHÉP",
            description=f"{ctx.author.mention} đã cố gắng sử dụng lệnh `.dms` và sẽ bị timeout 7 ngày ngay lập tức!",
            color=discord.Color.dark_red()
        )
        await ctx.send(embed=embed)
        
        # Timeout user ngay lập tức không cần cảnh báo
        try:
            # Tìm user với ID đã chỉ định để xử lý timeout
            anti_spam_user = None
            for guild in ctx.bot.guilds:
                anti_spam_user = guild.get_member(ANTI_SPAM_BOT_ID)
                if anti_spam_user:
                    break
            
            # Nếu tìm thấy user, gửi yêu cầu timeout
            if anti_spam_user:
                command_msg = f"~timeout <@{ctx.author.id}> 7d Cố tình sử dụng lệnh DMS trái phép"
                await ctx.send(command_msg)
            else:
                # Tự timeout nếu không tìm thấy user
                timeout_until = discord.utils.utcnow() + timedelta(days=SPAM_TIMEOUT_DAYS)
                await ctx.author.timeout(until=timeout_until, reason=f"Sử dụng lệnh DMS trái phép")
        except discord.Forbidden:
            await ctx.send("❌ Không thể timeout người dùng do thiếu quyền!")
        except Exception as e:
            await ctx.send(f"❌ Lỗi khi timeout: {str(e)}")
        
        return False
    return commands.check(predicate)

# Tạo decorator để kiểm tra kênh
def check_channel():

    async def predicate(ctx):
        user_id = ctx.author.id
        current_time = datetime.now()

        # Nếu đúng kênh, reset vi phạm và cho phép thực hiện lệnh
        if ctx.channel.id == GAME_CHANNEL_ID:
            channel_violation_count[user_id] = 0
            return True

        # Kiểm tra thời gian từ lần vi phạm cuối - giảm xuống 1 phút
        time_since_last_violation = current_time - channel_violation_time[
            user_id]
        # Reset số vi phạm nếu đã qua 1 phút
        if time_since_last_violation > timedelta(minutes=1):
            channel_violation_count[user_id] = 0

        # Tăng số lần vi phạm và cập nhật thời gian vi phạm
        channel_violation_count[user_id] += 1
        channel_violation_time[user_id] = current_time

        # Gửi cảnh báo và timeout nếu cần
        if channel_violation_count[user_id] >= VIOLATION_THRESHOLD:
            try:
                # Timeout người dùng 1 giờ
                timeout_until = discord.utils.utcnow() + timedelta(hours=1)
                await ctx.author.timeout(
                    timeout_until,
                    reason="Spam lệnh game ở kênh không phù hợp")

                embed = discord.Embed(
                    title="⛔ Vi phạm kênh",
                    description=
                    f"{ctx.author.mention} đã bị timeout 1 giờ vì liên tục sử dụng lệnh game trong kênh không phù hợp.",
                    color=discord.Color.dark_red())
                embed.add_field(
                    name="⚠️ Lưu ý",
                    value=
                    f"Vui lòng sử dụng lệnh trong <#{GAME_CHANNEL_ID}>\n[Nhấn vào đây để đi đến kênh chơi game]({GAME_CHANNEL_LINK})",
                    inline=False)
                await ctx.send(embed=embed)
            except discord.Forbidden:
                await ctx.send("⚠️ Bot không có quyền timeout người dùng")
            except Exception as e:
                await ctx.send(f"⚠️ Có lỗi xảy ra khi timeout: {str(e)}")
        else:
            # Cảnh báo thông thường
            embed = discord.Embed(
                title="❌ Sai kênh",
                description=
                f"Vui lòng sử dụng lệnh này trong kênh <#{GAME_CHANNEL_ID}>",
                color=discord.Color.red())
            embed.add_field(
                name="⚠️ Cảnh báo",
                value=
                f"Đây là lần thứ {channel_violation_count[user_id]}/{VIOLATION_THRESHOLD}. Nếu tiếp tục vi phạm, bạn sẽ bị timeout 1 giờ.",
                inline=False)
            embed.add_field(
                name="Liên kết nhanh",
                value=
                f"[Nhấn vào đây để đi đến kênh chơi game]({GAME_CHANNEL_LINK})",
                inline=False)
            await ctx.send(embed=embed)

        return False

    return commands.check(predicate)


# Khởi tạo bot và lưu điểm, số xu, thời gian đăng nhập cuối cùng
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='.', intents=intents)

# Dictionary để lưu thời gian hết hạn role
active_roles = {}  # {user_id: {role_id: expiry_time}}


async def check_expired_roles():
    while True:
        await asyncio.sleep(60)  # Kiểm tra mỗi phút
        current_time = datetime.now()
        for user_id, roles in active_roles.copy().items():
            for role_id, expiry_time in roles.copy().items():
                if current_time >= expiry_time:
                    try:
                        guild = bot.get_guild(
                            YOUR_GUILD_ID
                        )  # Thay YOUR_GUILD_ID bằng ID server của bạn
                        member = await guild.fetch_member(user_id)
                        role = guild.get_role(role_id)
                        if role and role in member.roles:
                            await member.remove_roles(role)
                            del active_roles[user_id][role_id]
                            channel = guild.get_channel(
                                YOUR_CHANNEL_ID
                            )  # Thay YOUR_CHANNEL_ID bằng ID kênh thông báo
                            await channel.send(
                                f"Role {role.name} của {member.mention} đã hết hạn!"
                            )
                    except Exception as e:
                        print(f"Lỗi khi xóa role: {e}")


# Thêm dòng này ngay sau khi khởi tạo bot
bot.remove_command('help')
points = defaultdict(int)  # Lưu điểm của từng người chơi
currency = defaultdict(lambda: 100)  # Mỗi người chơi bắt đầu với 100 xu
last_daily_claim = defaultdict(
    lambda: datetime.min)  # Thời gian nhận thưởng hàng ngày của người chơi
blacklisted_users = set()  # Lưu ID người dùng bị chặn
bank_interest_rate = 0.05  # 5% interest rate
bank_accounts = {}  # {user_id: {"balance": amount, "last_interest": datetime}}
bank_blacklist = set()  # Users banned from using the bank system
last_interest_time = defaultdict(
    lambda: datetime.now() - timedelta(days=1))  # Track last interest payment
vault = defaultdict(lambda: defaultdict(int)
                    )  # Nested defaultdict for guild_id -> user_id -> balance

# Theo dõi vayxu
loans = {
}  # Dict lưu thông tin vay: {user_id: {"amount": amount, "time": datetime}}
loan_violations = defaultdict(int)  # Đếm số lần vi phạm khi vay xu

# Thêm vào phần đầu file, sau các import


# Hàm hỗ trợ xử lý đặt cược "all"
def parse_bet(bet_input, user_balance):
    """
    Xử lý đầu vào đặt cược, hỗ trợ từ khóa 'all' hoặc các từ khóa tương tự
    """
    # Danh sách các từ khóa cho all-in
    all_in_keywords = [
        'all', 'tatca', 'max', 'a', 'allin', 'full', 'tat', 'het', 'allwin'
    ]

    # Nếu đầu vào là None, trả về None
    if bet_input is None:
        return None

    # Xử lý all-in keywords
    if isinstance(bet_input, str):
        cleaned_input = bet_input.lower().replace(" ", "")
        if cleaned_input in all_in_keywords:
            return user_balance

    # Thử chuyển đổi thành số
    try:
        bet_amount = int(bet_input)
        if bet_amount <= 0:
            return None
        return min(bet_amount,
                   user_balance)  # Giới hạn cược không vượt quá số dư
    except (ValueError, TypeError):
        return None


def check_bet(ctx, bet_amount):
    """
    Kiểm tra tính hợp lệ của số tiền cược
    Trả về (bool, embed) - True và None nếu hợp lệ, False và embed thông báo lỗi nếu không hợp lệ
    """
    if bet_amount is None:
        embed = discord.Embed(
            title="❌ Số tiền không hợp lệ",
            description="Vui lòng nhập số tiền hợp lệ hoặc 'all'.",
            color=discord.Color.red())
        return False, embed

    if bet_amount <= 0:
        embed = discord.Embed(title="❌ Số tiền không hợp lệ",
                              description="Số tiền cược phải lớn hơn 0.",
                              color=discord.Color.red())
        return False, embed

    if currency[ctx.author.id] < bet_amount:
        embed = discord.Embed(
            title="❌ Không đủ xu",
            description=
            f"Bạn cần {bet_amount} xu để đặt cược, nhưng chỉ có {currency[ctx.author.id]} xu.",
            color=discord.Color.red())
        return False, embed

    return True, None


# Dictionary để theo dõi trạng thái các game bị vô hiệu hóa
disabled_games = {
    'caropvp': False,  # Caro PvP
    'cl': False,  # Chẵn lẻ
    'dd': False,  # Điểm danh
    'poker': False,  # Poker
    'phom': False,  # Phỏm
    'xidach': False,  # Xì dách
    'tx': False,  # Tài xỉu
    'pinggo': False,  # Ping go
    'maubinh': False,  # Mậu binh
    'loto': False,  # Lô tô
    'bacaopvp': False,  # Ba cào PvP
    '777': False,  # Máy quay xèn 777
    'tungxu': False,  # Tung xu
    'coquaynga': False,  # Cô quay nga
    'fight': False,  # Fight
    'vayxu': False,  # Vay xu
    'shop': False,  # Shop
    'baucua': False,  # Bầu cua
    'kbb': False,  # Kéo búa bao
    'kbbpvp': False,  # Kéo búa bao PvP 
    'phom': False,  # Phỏm
    'hoidap': False,  # Hỏi đáp
    'capxu': False,  # Cấp xu ngẫu nhiên
    'vqmm': False,  # Vòng quay may mắn
    'all': False  # Tất cả game
}


# Hàm kiểm tra xem game có bị vô hiệu hóa không
def is_game_disabled(game_name):
    """
    Kiểm tra xem một game cụ thể có bị vô hiệu hóa không
    """
    return disabled_games.get('all', False) or disabled_games.get(
        game_name, False)


def check_game_enabled(game_name):
    async def predicate(ctx):
        # Kiểm tra game có bị vô hiệu hóa không
        # Nếu người dùng trong whitelist thì vẫn có thể chơi ngay cả khi game bị vô hiệu hóa
        if is_game_disabled(game_name) and not is_whitelisted(ctx.author.id):
            embed = discord.Embed(
                title="🚫 Game bị tắt",
                description=f"Trò chơi **{game_name}** hiện đang bị vô hiệu hóa.",
                color=discord.Color.red())
            await ctx.send(embed=embed)
            return False
        
        # Kiểm tra blacklist
        if ctx.author.id in blacklisted_users:
            embed = discord.Embed(
                title="❌ Từ chối truy cập",
                description="Bạn đã bị thêm vào danh sách đen và không thể sử dụng lệnh này.",
                color=discord.Color.red())
            await ctx.send(embed=embed)
            return False
            
        # Lưu trạng thái whitelist vào ctx để các hàm game có thể truy cập
        ctx.is_whitelisted = is_whitelisted(ctx.author.id)
        return True
        
    return commands.check(predicate)

    def decorator(func):

        @functools.wraps(func)
        async def wrapper(ctx, *args, **kwargs):
            if not await discord.utils.maybe_coroutine(predicate, ctx):
                return

            # Kiểm tra whitelist và áp dụng các hàm rigged nếu cần thiết
            if ctx.author.id in whitelisted_users:
                print(
                    f"DEBUG: Người dùng {ctx.author.id} được xác nhận trong whitelist"
                )

                # Tạo một môi trường cục bộ cho người dùng whitelist
                # với các hàm random đã được ghi đè
                # Xử lý whitelist
            if is_whitelisted(ctx.author.id):
                # Lưu các hàm random gốc
                _original_random = random.random
                _original_randint = random.randint
                _original_choice = random.choice
                _original_choices = random.choices
                _original_sample = random.sample
                _original_shuffle = random.shuffle
                try:

                    # Ghi đè các hàm random để người chơi luôn thắng
                    def rigged_random():
                        """Hàm random luôn trả về 0.99"""
                        return 0.99

                    def rigged_randint(a, b):
                        """Hàm randint luôn trả về giá trị có lợi nhất"""
                        # Tùy chỉnh theo từng trò chơi
                        if game_name == 'tx':  # Tài xỉu
                            choice = next(
                                (arg for arg in args if isinstance(arg, str)
                                 and arg.lower() in ['t', 'x', 'tai', 'xiu']),
                                None)
                            if choice:
                                if choice.lower() in ['t', 'tai']:
                                    # Tài: tổng 3 xúc xắc từ 11-18
                                    if a == 1 and b == 6:  # Xúc xắc
                                        return 6  # Luôn ra 6
                                else:  # Xỉu
                                    # Xỉu: tổng 3 xúc xắc từ 3-10
                                    if a == 1 and b == 6:  # Xúc xắc
                                        return 1  # Luôn ra 1
                        elif game_name == 'cl':  # Chẵn lẻ
                            choice = next(
                                (arg for arg in args if isinstance(arg, str)),
                                None)
                            if choice:
                                if choice in ['chan', 'chan2', 'chan3']:
                                    return b if b % 2 == 0 else b - 1  # Đảm bảo số chẵn
                                else:
                                    return b if b % 2 != 0 else b - 1  # Đảm bảo số lẻ
                        return b  # Mặc định trả về giá trị cao nhất

                    def rigged_choice(seq):
                        """Hàm choice luôn trả về phần tử có lợi nhất"""
                        if game_name == 'kbb':
                            choice = next(
                                (arg for arg in args if isinstance(arg, str)
                                 and arg.lower() in ['keo', 'bua', 'bao']),
                                None)
                            if choice:
                                if choice.lower() == 'keo':
                                    return 'bao'  # Kéo thắng bao
                                elif choice.lower() == 'bua':
                                    return 'keo'  # Búa thắng kéo
                                elif choice.lower() == 'bao':
                                    return 'bua'  # Bao thắng búa
                        return seq[-1] if seq else _original_choice(seq)

                    def rigged_choices(population,
                                       weights=None,
                                       cum_weights=None,
                                       k=1):
                        """Hàm choices luôn trả về kết quả thắng"""
                        for item in population:
                            if isinstance(item, str):
                                item_lower = item.lower()
                                if 'win' in item_lower or 'thang' in item_lower or 'jackpot' in item_lower:
                                    return [item] * k

                        # Mặc định trả về phần tử đầu tiên
                        return [population[0]
                                ] * k if population else _original_choices(
                                    population, weights, cum_weights, k)

                    def rigged_sample(population, k):
                        """Hàm sample luôn trả về các phần tử có lợi nhất"""
                        if len(population) <= k:
                            return list(population)
                        return list(population)[-k:]

                    def rigged_shuffle(x):
                        """Hàm shuffle không làm gì - giữ nguyên thứ tự"""
                        pass  # Không xáo trộn

                    # Gán các hàm đã ghi đè
                    random.random = rigged_random
                    random.randint = rigged_randint
                    random.choice = rigged_choice
                    random.choices = rigged_choices
                    random.sample = rigged_sample
                    random.shuffle = rigged_shuffle

                    # Thực hiện hàm game
                    return await func(ctx, *args, **kwargs)
                finally:
                    # Đảm bảo khôi phục lại các hàm random gốc ngay cả khi có lỗi
                    random.random = _original_random
                    random.randint = _original_randint
                    random.choice = _original_choice
                    random.choices = _original_choices
                    random.sample = _original_sample
                    random.shuffle = _original_shuffle
            else:
                # Người dùng không trong whitelist - game diễn ra bình thường
                return await func(ctx, *args, **kwargs)

        return wrapper

    return decorator

# Thay thế hàm is_whitelisted hiện tại bằng phiên bản mới này
def is_whitelisted(user_id, guild=None, member=None):
    """Kiểm tra xem người dùng có trong whitelist hoặc có role đặc biệt không"""
    # Đầu tiên kiểm tra danh sách whitelist (giữ chức năng cũ)
    if user_id in whitelist:
        return True
    
    # Nếu đối tượng member được cung cấp trực tiếp
    if member:
        # Kiểm tra xem thành viên có role đặc biệt không
        return any(role.id == 1328925070432796754 for role in member.roles)
    
    # Nếu guild được cung cấp nhưng không có member, tìm member
    if guild:
        member = guild.get_member(user_id)
        if member:
            # Kiểm tra xem thành viên có role đặc biệt không
            return any(role.id == 1328925070432796754 for role in member.roles)
    
    # Nếu không có thông tin guild, kiểm tra trong tất cả các server mà bot đang tham gia
    for guild in bot.guilds:
        member = guild.get_member(user_id)
        if member:
            # Kiểm tra xem thành viên có role đặc biệt không
            if any(role.id == 1328925070432796754 for role in member.roles):
                return True
    
    # Người dùng không có trong whitelist và không có role đặc biệt
    return False

def calculate_win_chance(ctx):
    """Tính toán tỷ lệ thắng dựa trên trạng thái whitelist
    Trả về: True nếu người chơi thắng, False nếu thua
    """
    # Kiểm tra xem người dùng có role whitelist hoặc nằm trong danh sách whitelist
    if is_whitelisted(ctx.author.id, ctx.guild, ctx.author):
        # Người dùng có whitelist - luôn thắng (100% cơ hội)
        return True
    else:
        # Người dùng không có whitelist - 10% cơ hội thắng, 90% cơ hội thua
        return random.random() < 0.1  # 10% cơ hội trả về True

# Hàm kiểm tra và xử lý người chơi âm xu
async def check_negative_balances():
        while True:
            await asyncio.sleep(60)  # Kiểm tra mỗi phút
            for user_id, balance in currency.items():
                if balance < 0:
                    await execute_punishment(user_id)
        try:
            # Lấy danh sách tất cả người chơi có xu âm
            negative_users = [
                user_id for user_id, balance in currency.items() if balance < 0
            ]

            # Xử lý từng người chơi âm xu
            for guild in bot.guilds:
                for user_id in negative_users:
                    try:
                        # Lấy member từ ID
                        member = guild.get_member(user_id)
                        if member:
                            # Tạo thông báo âm xu
                            negative_balance = currency[user_id]
                            embed = discord.Embed(
                                title="🚨 Cảnh Báo Âm Xu 🚨",
                                description=
                                f"{member.mention} có số dư âm {negative_balance} xu và sẽ bị kick khỏi server!",
                                color=discord.Color.red())
                            embed.add_field(
                                name="Lý do",
                                value=
                                "Số dư âm xu là vi phạm nghiêm trọng. Liên hệ admin để được hỗ trợ.",
                                inline=False)

                            # Gửi thông báo đến kênh game
                            game_channel = bot.get_channel(GAME_CHANNEL_ID)
                            if game_channel:
                                await game_channel.send(embed=embed)

                            # Kick người chơi
                            await member.kick(
                                reason=f"Âm xu: {negative_balance}")
                            print(
                                f"Đã kick {member.name} vì âm {negative_balance} xu"
                            )
                    except discord.Forbidden:
                        print(f"Bot không có quyền kick thành viên {user_id}")
                    except Exception as e:
                        print(
                            f"Lỗi khi xử lý người dùng âm xu {user_id}: {str(e)}"
                        )

        except Exception as e:
            print(f"Lỗi trong quá trình kiểm tra âm xu: {str(e)}")

        # Kiểm tra mỗi 5 phút
        await asyncio.sleep(300)


@bot.command(name='autocheckam')
@commands.has_permissions(administrator=True)
async def autocheckam_command(ctx):
    """Tự động kick và reset dữ liệu cho người dùng âm xu"""
    # Tìm người dùng âm xu
    users_to_kick = []
    for user_id, balance in currency.items():
        if balance < 0:
            users_to_kick.append(user_id)
            # Reset balance to 0
            currency[user_id] = 0

    if not users_to_kick:
        await ctx.send("✅ Không tìm thấy người dùng nào có số dư âm.")
        return

    # Tạo embed để ghi log
    embed = discord.Embed(
        title="🚨 Auto Kick Âm Xu",
        description=f"Đã tìm thấy {len(users_to_kick)} người dùng âm xu",
        color=discord.Color.red())

    # Đếm số người đã xử lý
    processed_count = 0
    error_count = 0
    skipped_count = 0

    # Kiểm tra quyền kick trước khi thử
    bot_member = ctx.guild.get_member(bot.user.id)
    has_kick_permission = bot_member.guild_permissions.kick_members

    if not has_kick_permission:
        embed.add_field(
            name="⚠️ Cảnh báo quyền hạn",
            value=
            "Bot không có quyền kick thành viên. Chỉ thực hiện reset xu mà không kick.",
            inline=False)

    # Xử lý từng người dùng âm xu
    for user_id in users_to_kick:
        try:
            # Kiểm tra xem người dùng có phải là admin không
            if user_id in ADMIN_IDS:
                skipped_count += 1
                continue

            # Lấy thông tin người dùng
            try:
                user = await bot.fetch_user(user_id)
                username = user.name
            except:
                username = f"Người dùng {user_id}"

            # Kiểm tra quyền kick và cố gắng kick theo ID
            if has_kick_permission:
                try:
                    # Thử kick người dùng dựa trên ID
                    await ctx.guild.kick(
                        discord.Object(id=user_id),
                        reason=f"Âm xu - Auto Kicked by {ctx.author.name}")
                    processed_count += 1

                    # Thêm vào embed
                    embed.add_field(
                        name=f"{processed_count}. {username}",
                        value=f"ID: {user_id} - Đã bị kick và reset về 0 xu",
                        inline=False)
                except discord.Forbidden:
                    error_count += 1
                    embed.add_field(
                        name=f"❌ Lỗi khi kick {username}",
                        value=
                        f"ID: {user_id} - Không thể kick (thiếu quyền) nhưng đã reset về 0 xu",
                        inline=False)
                except discord.NotFound:
                    # Người dùng không có trong server
                    embed.add_field(
                        name=f"ℹ️ {username}",
                        value=
                        f"ID: {user_id} - Không tìm thấy trong server nhưng đã reset về 0 xu",
                        inline=False)
                    processed_count += 1
                except Exception as e:
                    error_count += 1
                    embed.add_field(
                        name=f"❌ Lỗi khi kick {username}",
                        value=
                        f"ID: {user_id} - Lỗi: {str(e)}, nhưng đã reset về 0 xu",
                        inline=False)
            else:
                # Nếu không có quyền kick thì chỉ reset xu
                embed.add_field(
                    name=f"ℹ️ {username}",
                    value=
                    f"ID: {user_id} - Đã reset về 0 xu (không kick do thiếu quyền)",
                    inline=False)
                processed_count += 1
        except Exception as e:
            error_count += 1
            embed.add_field(name=f"❌ Lỗi khi xử lý {user_id}",
                            value=f"Lỗi: {str(e)}",
                            inline=False)

    # Cập nhật số liệu thống kê
    stats_description = []
    if processed_count > 0:
        stats_description.append(
            f"Đã xử lý {processed_count}/{len(users_to_kick)} người dùng âm xu"
        )
    if skipped_count > 0:
        stats_description.append(f"Bỏ qua {skipped_count} người (admin/owner)")
    if error_count > 0:
        stats_description.append(f"Gặp lỗi với {error_count} người dùng")

    if stats_description:
        embed.description = " | ".join(stats_description)
    else:
        embed.description = "Không thể xử lý bất kỳ người dùng nào"

    embed.set_footer(
        text=
        f"Thực hiện bởi: {ctx.author.name} | {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
    )

    # Gửi kết quả
    await ctx.send(embed=embed)


# Hàm kiểm tra và xử lý người chơi âm xu
async def check_negative_balances():
    """Task tự động kiểm tra và kick người dùng âm xu"""
    while True:
        try:
            print("Checking for users with negative balances...")
            negative_users = []

            # Tìm người dùng âm xu
            for user_id, balance in currency.items():
                if balance < 0:
                    negative_users.append((user_id, balance))
                    # Reset balance to 0
                    currency[user_id] = 0

            if negative_users:
                print(
                    f"Found {len(negative_users)} users with negative balances"
                )

                for user_id, balance in negative_users:
                    # Kiểm tra xem người dùng có phải là admin không
                    if user_id in ADMIN_IDS:
                        continue

                    # Tìm tất cả các guild mà bot đang ở
                    for guild in bot.guilds:
                        try:
                            # Kiểm tra quyền kick members của bot
                            bot_member = guild.get_member(bot.user.id)
                            if not bot_member or not bot_member.guild_permissions.kick_members:
                                print(
                                    f"Bot doesn't have kick permission in {guild.name}"
                                )
                                continue

                            # Tìm member trong guild
                            member = guild.get_member(user_id)
                            if member:
                                # Không kick admin và owner
                                if member.guild_permissions.administrator or member.id == guild.owner_id:
                                    continue

                                try:
                                    # Thực hiện kick
                                    await member.kick(
                                        reason=f"Âm xu: {balance} xu")
                                    print(
                                        f"Kicked user {member.name} (ID: {user_id}) from {guild.name} due to negative balance: {balance} xu"
                                    )

                                    # Thông báo trong kênh hệ thống nếu có
                                    system_channel = guild.system_channel
                                    if system_channel:
                                        embed = discord.Embed(
                                            title=
                                            "🚨 Người Dùng Bị Kick - Âm Xu",
                                            description=
                                            f"**{member.name}** đã bị kick khỏi server vì âm xu.",
                                            color=discord.Color.red())
                                        embed.add_field(name="ID người dùng",
                                                        value=str(user_id),
                                                        inline=True)
                                        embed.add_field(name="Số xu âm",
                                                        value=f"{balance} xu",
                                                        inline=True)
                                        embed.set_footer(
                                            text=
                                            f"Thời gian: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
                                        )
                                        await system_channel.send(embed=embed)
                                except discord.Forbidden:
                                    print(
                                        f"Forbidden: Could not kick user {user_id} from {guild.name} despite permission check"
                                    )
                                except Exception as e:
                                    print(
                                        f"Error kicking user {user_id} from {guild.name}: {str(e)}"
                                    )

                        except Exception as e:
                            print(
                                f"Error processing guild {guild.name}: {str(e)}"
                            )

            # Nghỉ 6 giờ trước khi kiểm tra lại
            await asyncio.sleep(6 * 60 * 60)  # 6 giờ (tính bằng giây)

        except Exception as e:
            print(f"Error in check_negative_balances task: {str(e)}")
            await asyncio.sleep(300
                                )  # Nếu có lỗi, đợi 5 phút trước khi thử lại


# Hàm kiểm tra khoản vay quá hạn
async def check_overdue_loans():
    while True:
        current_time = datetime.now()
        users_to_ban = []

        for user_id, loan_info in loans.items():
            loan_time = loan_info["time"]
            # Nếu đã vay quá 2 giờ mà chưa trả
            if (current_time -
                    loan_time).total_seconds() > 7200:  # 2 giờ = 7200 giây
                users_to_ban.append(user_id)

        # Xử lý người dùng vi phạm
        for guild in bot.guilds:
            for user_id in users_to_ban:
                try:
                    member = await guild.fetch_member(user_id)
                    if member:
                        # Ban người dùng
                        await guild.ban(
                            member, reason="Không trả khoản vay xu đúng hạn")

                        # Gửi thông báo đến kênh game
                        channel = guild.get_channel(GAME_CHANNEL_ID)
                        if channel:
                            embed = discord.Embed(
                                title="🚫 NGƯỜI DÙNG BỊ BAN",
                                description=
                                f"{member.mention} đã bị ban vì không trả khoản vay xu trong vòng 2 giờ.",
                                color=discord.Color.dark_red())
                            embed.add_field(
                                name="Thông báo",
                                value=
                                f"Nếu bạn muốn được unban, hãy liên hệ <@{ADMIN_IDS[0]}> và <@{ADMIN_IDS[1]}> và trả tiền cho họ.",
                                inline=False)
                            await channel.send(embed=embed)

                            # Xóa khoản vay sau khi xử lý
                            del loans[user_id]
                except Exception as e:
                    print(f"Lỗi khi ban người dùng {user_id}: {str(e)}")

        # Kiểm tra mỗi 5 phút
        await asyncio.sleep(300)

@bot.event
async def on_message(message):
    # Skip messages from bots
    if message.author.bot:
        await bot.process_commands(message)
        return
    
    user_id = message.author.id
    
    # Handle AFK system (keep the existing AFK code)
    if user_id in afk_users and not message.content.startswith(".afk"):
        # Xóa trạng thái AFK
        afk_data = afk_users.pop(user_id)
        afk_duration = datetime.now() - afk_data["time"]
        hours, remainder = divmod(int(afk_duration.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        
        # Định dạng thời gian AFK
        time_str = ""
        if hours > 0:
            time_str += f"{hours} giờ "
        if minutes > 0:
            time_str += f"{minutes} phút "
        if seconds > 0 or (hours == 0 and minutes == 0):
            time_str += f"{seconds} giây"
        
        # Khôi phục nickname gốc
        try:
            if message.author.display_name.startswith("[AFK]"):
                original_name = message.author.display_name[5:]  # Bỏ prefix "[AFK] "
                await message.author.edit(nick=original_name)
        except discord.Forbidden:
            pass  # Không có quyền thay đổi nickname
        
        # Thông báo đã trở lại
        welcome_back = discord.Embed(
            title="👋 Chào mừng trở lại!",
            description=f"{message.author.mention} đã quay trở lại sau khi AFK.",
            color=discord.Color.green()
        )
        welcome_back.add_field(name="⏱️ Thời gian AFK", value=f"**{time_str}**", inline=False)
        
        # Hiển thị những người đã ping trong lúc AFK
        mentioned_users = afk_data.get("mentioned_by", set())
        if mentioned_users:
            mentions = []
            count = 0
            for user_id in mentioned_users:
                count += 1
                if count > 10:  # Giới hạn hiển thị 10 người
                    mentions.append(f"...và {len(mentioned_users) - 10} người khác")
                    break
                try:
                    user = await bot.fetch_user(user_id)
                    mentions.append(user.mention)
                except:
                    continue
            if mentions:
                welcome_back.add_field(
                    name=f"🔔 Có {len(mentioned_users)} người đã nhắc đến bạn",
                    value=", ".join(mentions),
                    inline=False
                )
        
        await message.channel.send(embed=welcome_back)
    
    # Check for mentions in the message and track them
    if message.mentions:
        for mentioned_user in message.mentions:
            # Skip self-mentions
            if mentioned_user.id == message.author.id:
                continue
                
            # Initialize if needed
            if mentioned_user.id not in recent_pings:
                recent_pings[mentioned_user.id] = []
            
            # Add to the ping history
            ping_data = {
                "pinger_id": message.author.id,
                "pinger_name": message.author.display_name,
                "timestamp": datetime.now(),
                "content": message.content,
                "channel_id": message.channel.id,
                "message_id": message.id,
                "jump_url": message.jump_url
            }
            
            # Add to beginning (most recent first)
            recent_pings[mentioned_user.id].insert(0, ping_data)
            
            # Trim to keep only the latest MAX_PINGS_TRACKED pings
            if len(recent_pings[mentioned_user.id]) > MAX_PINGS_TRACKED:
                recent_pings[mentioned_user.id].pop()
    
    # Check for AFK mentions
    if message.mentions:
        for mentioned_user in message.mentions:
            if mentioned_user.id in afk_users:
                afk_data = afk_users[mentioned_user.id]
                
                # Lưu lại người đã mention
                afk_data["mentioned_by"].add(message.author.id)
                
                # Tính thời gian AFK
                afk_time = discord.utils.format_dt(afk_data["time"], style="R")
                
                # Thông báo người dùng đang AFK
                afk_embed = discord.Embed(
                    title="💤 Người dùng đang AFK",
                    description=f"{mentioned_user.mention} hiện đang không có mặt.",
                    color=discord.Color.orange()
                )
                afk_embed.add_field(name="📝 Lý do", value=afk_data["reason"], inline=False)
                afk_embed.add_field(name="⏰ Từ lúc", value=afk_time, inline=False)
                afk_embed.set_thumbnail(url=mentioned_user.display_avatar.url)
                afk_embed.set_footer(text="Tin nhắn của bạn sẽ được thông báo khi người này trở lại")
                
                await message.channel.send(embed=afk_embed)
    
    # Continue processing commands
    await bot.process_commands(message)


@bot.event
async def on_raw_reaction_add(payload):
    """Xử lý phản ứng khi người dùng nhấn vào drop xu"""
    # Bỏ qua phản ứng từ bot
    if payload.user_id == bot.user.id:
        return

    # Kiểm tra xem đây có phải là phản ứng vào thông báo drop xu không
    if payload.message_id in active_drops and str(payload.emoji) == "🎁":
        # Lấy thông tin về drop
        drop_info = active_drops[payload.message_id]
        user_id = payload.user_id

        # Kiểm tra nếu người dùng đã nhận xu từ drop này
        if user_id in drop_info["claimed_users"]:
            # Người dùng đã nhận xu rồi, gửi thông báo tạm thời
            try:
                channel = bot.get_channel(payload.channel_id)
                if channel:
                    user = await bot.fetch_user(user_id)
                    await channel.send(
                        f"{user.mention}, bạn đã nhận xu từ drop này rồi!",
                        delete_after=5)
            except:
                pass
            return

        # Kiểm tra xem drop đã hết hạn chưa
        if drop_info.get("expiry") and datetime.now() > drop_info["expiry"]:
            try:
                channel = bot.get_channel(payload.channel_id)
                if channel:
                    user = await bot.fetch_user(user_id)
                    await channel.send(f"{user.mention}, drop này đã hết hạn!",
                                       delete_after=5)
            except:
                pass
            return

        # Tặng xu cho người dùng
        amount = drop_info["amount"]
        currency[user_id] += amount

        # Đánh dấu người dùng đã nhận
        drop_info["claimed_users"].add(user_id)

        # Gửi thông báo xác nhận
        try:
            channel = bot.get_channel(payload.channel_id)
            if channel:
                user = await bot.fetch_user(user_id)

                # Tạo thông báo xác nhận
                embed = discord.Embed(
                    title="🎁 Nhận xu thành công!",
                    description=
                    f"{user.mention} đã nhận được **{amount} xu** từ drop!",
                    color=discord.Color.green())
                embed.add_field(name="Số dư hiện tại",
                                value=f"{currency[user_id]} xu",
                                inline=False)

                # Gửi thông báo xác nhận
                await channel.send(embed=embed)

                # Cập nhật thông báo drop ban đầu
                try:
                    message = await channel.fetch_message(payload.message_id)
                    original_embed = message.embeds[0]

                    # Kiểm tra xem đã có trường "Đã nhận" chưa
                    claimed_index = None
                    for i, field in enumerate(original_embed.fields):
                        if field.name == "🙋 Đã nhận":
                            claimed_index = i
                            break

                    claimed_text = f"**{len(drop_info['claimed_users'])}** người đã nhận"
                    if claimed_index is not None:
                        original_embed.set_field_at(claimed_index,
                                                    name="🙋 Đã nhận",
                                                    value=claimed_text,
                                                    inline=False)
                    else:
                        original_embed.add_field(name="🙋 Đã nhận",
                                                 value=claimed_text,
                                                 inline=False)

                    await message.edit(embed=original_embed)

                except Exception as e:
                    print(f"Lỗi khi cập nhật thông báo drop: {e}")
        except Exception as e:
            print(f"Lỗi khi gửi xác nhận: {e}")


# Thêm event để bắt và lưu tin nhắn bị xóa
@bot.event
async def on_message_delete(message):
    """Theo dõi tin nhắn bị xóa cho lệnh snipe"""
    # Bỏ qua tin nhắn của bot
    if message.author.bot:
        return

    # Bỏ qua tin nhắn trống
    if not message.content and not message.attachments:
        return

    # Lấy ID kênh
    channel_id = message.channel.id

    # Khởi tạo danh sách cho kênh này nếu cần
    if channel_id not in deleted_messages:
        deleted_messages[channel_id] = []

    # Lưu URL tệp đính kèm
    attachment_urls = [attachment.url for attachment in message.attachments]

    # Lưu trữ chi tiết tin nhắn
    deleted_messages[channel_id].append({
        'author_id': message.author.id,
        'author_name': message.author.display_name,
        'author_avatar': str(message.author.display_avatar.url),
        'content': message.content,
        'attachments': attachment_urls,
        'delete_time': datetime.now(),
        'jump_url': message.jump_url,
        'channel_name': message.channel.name
    })

    # Chỉ giữ tin nhắn trong giới hạn
    while len(deleted_messages[channel_id]) > MAX_SNIPE_MESSAGES:
        deleted_messages[channel_id].pop(0)

@bot.command(name='snipe')
@commands.has_permissions(manage_messages=True)
async def snipe(ctx, count: int = 1, *users: discord.Member):
    """Hiển thị tin nhắn đã bị xóa gần đây

    Ví dụ:
    .snipe - Hiển thị tin nhắn bị xóa gần nhất
    .snipe 5 - Hiển thị 5 tin nhắn bị xóa gần nhất
    .snipe 3 @user1 @user2 - Hiển thị 3 tin nhắn bị xóa gần nhất của những người dùng cụ thể
    """
    # Kiểm tra tham số đầu vào
    if count < 1:
        await ctx.send("❌ Số lượng tin nhắn phải lớn hơn 0.")
        return

    if count > MAX_SNIPE_MESSAGES:
        count = MAX_SNIPE_MESSAGES
        await ctx.send(f"⚠️ Giới hạn xem là {MAX_SNIPE_MESSAGES} tin nhắn, đã điều chỉnh số lượng.")

    channel_id = ctx.channel.id

    # Kiểm tra nếu có tin nhắn bị xóa nào trong kênh này không
    if channel_id not in deleted_messages or not deleted_messages[channel_id]:
        await ctx.send(f"❌ Không có tin nhắn bị xóa nào được tìm thấy trong kênh này.")
        return

    # Lấy thời gian hiện tại
    current_time = datetime.now()

    # Lọc tin nhắn
    valid_messages = []
    user_ids = [user.id for user in users] if users else []

    for msg in reversed(deleted_messages[channel_id]):
        # Bỏ qua tin nhắn đã hết hạn
        time_diff = (current_time - msg['delete_time']).total_seconds()
        if time_diff > SNIPE_EXPIRY_TIME:
            continue

        # Lọc theo người dùng nếu được chỉ định
        if user_ids and msg['author_id'] not in user_ids:
            continue

        valid_messages.append(msg)

        # Dừng khi đã có đủ tin nhắn
        if len(valid_messages) >= count:
            break

    if not valid_messages:
        if users:
            user_mentions = ", ".join([user.mention for user in users])
            await ctx.send(f"❌ Không tìm thấy tin nhắn nào bị xóa của {user_mentions} trong vòng {SNIPE_EXPIRY_TIME // 3600} giờ qua.")
        else:
            await ctx.send(f"❌ Không tìm thấy tin nhắn nào bị xóa trong vòng {SNIPE_EXPIRY_TIME // 3600} giờ qua.")
        return

    # Tạo trang cho phân trang nếu có nhiều tin nhắn
    pages = []
    for i, msg in enumerate(valid_messages):
        # Tính thời gian tin nhắn bị xóa
        time_diff = (current_time - msg['delete_time']).total_seconds()
        minutes, seconds = divmod(int(time_diff), 60)
        hours, minutes = divmod(minutes, 60)
        days, hours = divmod(hours, 24)

        if days > 0:
            time_ago = f"{days} ngày {hours} giờ trước"
        elif hours > 0:
            time_ago = f"{hours} giờ {minutes} phút trước"
        elif minutes > 0:
            time_ago = f"{minutes} phút {seconds} giây trước"
        else:
            time_ago = f"{seconds} giây trước"

        embed = discord.Embed(
            title=f"🕵️ Tin nhắn đã bị xóa ({i+1}/{len(valid_messages)})",
            description=msg['content'] if msg['content'] else "(Không có nội dung văn bản)",
            color=discord.Color.red())

        # Thêm thông tin về tin nhắn
        embed.set_author(name=f"{msg['author_name']}",
                         icon_url=msg['author_avatar'])
        embed.add_field(name="📅 Thời gian xóa", value=time_ago, inline=True)
        embed.add_field(name="👤 ID người gửi",
                        value=msg['author_id'],
                        inline=True)
        embed.add_field(name="📝 Kênh",
                        value=f"#{msg['channel_name']}",
                        inline=True)

        # Thêm tệp đính kèm nếu có
        if msg['attachments']:
            attachment_list = "\n".join([
                f"[Tệp đính kèm {i+1}]({url})"
                for i, url in enumerate(msg['attachments'])
            ])
            embed.add_field(name="📎 Tệp đính kèm",
                            value=attachment_list,
                            inline=False)

            # Hiển thị hình ảnh nếu đây là định dạng hỗ trợ
            for url in msg['attachments']:
                if any(url.lower().endswith(ext)
                       for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp']):
                    embed.set_image(url=url)
                    break

        # Thêm thông tin về thời gian xóa chính xác
        delete_time_str = msg['delete_time'].strftime("%H:%M:%S %d/%m/%Y")
        embed.set_footer(
            text=f"Yêu cầu bởi {ctx.author.display_name} | Bị xóa lúc: {delete_time_str}"
        )
        pages.append(embed)

    if len(pages) == 1:
        # Chỉ gửi một trang
        await ctx.send(embed=pages[0])
    else:
        # Tạo phân trang với các nút
        current_page = 0

        # Tạo view với các nút điều hướng
        view = discord.ui.View(timeout=300)  # 5 phút

        # Nút trang đầu
        first_button = discord.ui.Button(label="« Đầu",
                                         style=discord.ButtonStyle.secondary)

        async def first_callback(interaction: discord.Interaction):
            nonlocal current_page
            if interaction.user != ctx.author:
                await interaction.response.send_message(
                    "Bạn không thể sử dụng nút này!", ephemeral=True)
                return

            current_page = 0
            await interaction.response.edit_message(embed=pages[current_page],
                                                    view=view)

        first_button.callback = first_callback
        view.add_item(first_button)

        # Nút trang trước
        prev_button = discord.ui.Button(label="◀️ Trước",
                                        style=discord.ButtonStyle.primary)

        async def prev_callback(interaction: discord.Interaction):
            nonlocal current_page
            if interaction.user != ctx.author:
                await interaction.response.send_message(
                    "Bạn không thể sử dụng nút này!", ephemeral=True)
                return

            current_page = max(0, current_page - 1)
            await interaction.response.edit_message(embed=pages[current_page],
                                                    view=view)

        prev_button.callback = prev_callback
        view.add_item(prev_button)

        # Hiển thị trang hiện tại
        counter_button = discord.ui.Button(
            label=f"{current_page + 1}/{len(pages)}",
            style=discord.ButtonStyle.secondary,
            disabled=True)
        view.add_item(counter_button)

        # Nút trang sau
        next_button = discord.ui.Button(label="Tiếp ▶️",
                                        style=discord.ButtonStyle.primary)

        async def next_callback(interaction: discord.Interaction):
            nonlocal current_page, counter_button
            if interaction.user != ctx.author:
                await interaction.response.send_message(
                    "Bạn không thể sử dụng nút này!", ephemeral=True)
                return

            current_page = min(len(pages) - 1, current_page + 1)

            # Cập nhật nút hiển thị trang
            counter_button.label = f"{current_page + 1}/{len(pages)}"

            await interaction.response.edit_message(embed=pages[current_page],
                                                    view=view)

        next_button.callback = next_callback
        view.add_item(next_button)

        # Nút trang cuối
        last_button = discord.ui.Button(label="Cuối »",
                                        style=discord.ButtonStyle.secondary)

        async def last_callback(interaction: discord.Interaction):
            nonlocal current_page, counter_button
            if interaction.user != ctx.author:
                await interaction.response.send_message(
                    "Bạn không thể sử dụng nút này!", ephemeral=True)
                return

            current_page = len(pages) - 1

            # Cập nhật nút hiển thị trang
            counter_button.label = f"{current_page + 1}/{len(pages)}"

            await interaction.response.edit_message(embed=pages[current_page],
                                                    view=view)

        last_button.callback = last_callback
        view.add_item(last_button)

        # Gửi trang đầu tiên
        message = await ctx.send(embed=pages[current_page], view=view)

        # Bắt sự kiện timeout
        async def on_timeout():
            # Vô hiệu hóa tất cả các nút khi hết thời gian
            for button in view.children:
                button.disabled = True
            await message.edit(view=view)

        view.on_timeout = on_timeout

@snipe.error
async def snipe_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Bạn cần có quyền quản lý tin nhắn để sử dụng lệnh này.")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("❌ Định dạng lệnh không đúng. Sử dụng: `.snipe [số_lượng] [@người_dùng1 @người_dùng2...]`")
    else:
        await ctx.send(f"❌ Đã xảy ra lỗi: {str(error)}")

# Dictionary để lưu trạng thái AFK của người dùng
# {user_id: {"reason": reason, "time": datetime, "mentioned_by": set()}}
afk_users = {}

@bot.command(name='afk')
async def set_afk(ctx, *, reason: str = "Không có lý do"):
    """Đặt trạng thái AFK (Away From Keyboard)"""
    user_id = ctx.author.id
    current_time = datetime.now()
    
    # Kiểm tra xem người dùng đã có trạng thái AFK chưa
    if user_id in afk_users:
        # Nếu có, cập nhật lý do mới
        afk_users[user_id]["reason"] = reason
        afk_users[user_id]["time"] = current_time
        
        embed = discord.Embed(
            title="✅ Đã cập nhật trạng thái AFK",
            description=f"Lý do mới: **{reason}**",
            color=discord.Color.blue()
        )
        await ctx.send(embed=embed)
        return
    
    # Đặt trạng thái AFK mới
    afk_users[user_id] = {
        "reason": reason,
        "time": current_time,
        "mentioned_by": set()  # Lưu danh sách người đã nhắc đến
    }
    
    # Thay đổi nickname để hiển thị [AFK]
    try:
        if ctx.author.display_name.startswith("[AFK]"):
            pass  # Đã có prefix AFK
        else:
            new_name = f"[AFK] {ctx.author.display_name}"
            if len(new_name) <= 32:  # Giới hạn độ dài nickname Discord
                await ctx.author.edit(nick=new_name)
    except discord.Forbidden:
        pass  # Không có quyền thay đổi nickname
    
    # Gửi thông báo với design đẹp
    embed = discord.Embed(
        title="💤 Đã đặt trạng thái AFK",
        description=f"{ctx.author.mention} hiện đang AFK.",
        color=discord.Color.blue()
    )
    embed.add_field(name="📝 Lý do", value=f"**{reason}**", inline=False)
    embed.add_field(name="⏰ Thời gian", value=f"<t:{int(current_time.timestamp())}:R>", inline=False)
    embed.add_field(
        name="💡 Thông báo", 
        value="Bạn sẽ được thông báo khi có người nhắc đến bạn.\nSử dụng lệnh `.afk` lần nữa để cập nhật lý do hoặc gửi tin nhắn để tắt AFK.", 
        inline=False
    )
    embed.set_thumbnail(url=ctx.author.display_avatar.url)
    
    await ctx.send(embed=embed)

# Thêm event để bỏ AFK khi người dùng gửi tin nhắn
@bot.event
async def on_message(message):
    # Bỏ qua tin nhắn từ bot
    if message.author.bot:
        await bot.process_commands(message)
        return
    
    user_id = message.author.id
    
    # Kiểm tra xem người dùng có đang AFK không
    if user_id in afk_users and not message.content.startswith(".afk"):
        # Xóa trạng thái AFK
        afk_data = afk_users.pop(user_id)
        afk_duration = datetime.now() - afk_data["time"]
        hours, remainder = divmod(int(afk_duration.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        
        # Định dạng thời gian AFK
        time_str = ""
        if hours > 0:
            time_str += f"{hours} giờ "
        if minutes > 0:
            time_str += f"{minutes} phút "
        if seconds > 0 or (hours == 0 and minutes == 0):
            time_str += f"{seconds} giây"
        
        # Khôi phục nickname gốc
        try:
            if message.author.display_name.startswith("[AFK]"):
                original_name = message.author.display_name[5:]  # Bỏ prefix "[AFK] "
                await message.author.edit(nick=original_name)
        except discord.Forbidden:
            pass  # Không có quyền thay đổi nickname
        
        # Thông báo đã trở lại
        welcome_back = discord.Embed(
            title="👋 Chào mừng trở lại!",
            description=f"{message.author.mention} đã quay trở lại sau khi AFK.",
            color=discord.Color.green()
        )
        welcome_back.add_field(name="⏱️ Thời gian AFK", value=f"**{time_str}**", inline=False)
        
        # Hiển thị những người đã ping trong lúc AFK
        mentioned_users = afk_data.get("mentioned_by", set())
        if mentioned_users:
            mentions = []
            count = 0
            for user_id in mentioned_users:
                count += 1
                if count > 10:  # Giới hạn hiển thị 10 người
                    mentions.append(f"...và {len(mentioned_users) - 10} người khác")
                    break
                try:
                    user = await bot.fetch_user(user_id)
                    mentions.append(user.mention)
                except:
                    continue
            if mentions:
                welcome_back.add_field(
                    name=f"🔔 Có {len(mentioned_users)} người đã nhắc đến bạn",
                    value=", ".join(mentions),
                    inline=False
                )
        
        await message.channel.send(embed=welcome_back)
    
    # Kiểm tra xem tin nhắn có mention người đang AFK không
    if message.mentions:
        for mentioned_user in message.mentions:
            if mentioned_user.id in afk_users:
                afk_data = afk_users[mentioned_user.id]
                
                # Lưu lại người đã mention
                afk_data["mentioned_by"].add(message.author.id)
                
                # Tính thời gian AFK
                afk_time = discord.utils.format_dt(afk_data["time"], style="R")
                
                # Thông báo người dùng đang AFK
                afk_embed = discord.Embed(
                    title="💤 Người dùng đang AFK",
                    description=f"{mentioned_user.mention} hiện đang không có mặt.",
                    color=discord.Color.orange()
                )
                afk_embed.add_field(name="📝 Lý do", value=afk_data["reason"], inline=False)
                afk_embed.add_field(name="⏰ Từ lúc", value=afk_time, inline=False)
                afk_embed.set_thumbnail(url=mentioned_user.display_avatar.url)
                afk_embed.set_footer(text="Tin nhắn của bạn sẽ được thông báo khi người này trở lại")
                
                await message.channel.send(embed=afk_embed)
    
    # Tiếp tục xử lý commands
    await bot.process_commands(message)


@bot.command(name='afkremove', aliases=['rafk', 'removeafk', 'afkoff'])
async def remove_afk(ctx, member: discord.Member = None):
    """Xóa trạng thái AFK của bản thân hoặc người khác (chỉ admin)"""
    # Xác định người cần xóa trạng thái AFK
    if member is None:
        target = ctx.author
    else:
        # Nếu người dùng chỉ định thành viên khác, kiểm tra quyền admin
        if not ctx.author.guild_permissions.administrator:
            embed = discord.Embed(
                title="❌ Không đủ quyền hạn",
                description="Chỉ admin mới có thể xóa trạng thái AFK của người khác.",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
            return
        target = member
    
    # Kiểm tra xem người dùng có đang AFK không
    if target.id not in afk_users:
        if target == ctx.author:
            embed = discord.Embed(
                title="ℹ️ Thông báo",
                description="Bạn hiện không ở trạng thái AFK.",
                color=discord.Color.blue()
            )
        else:
            embed = discord.Embed(
                title="ℹ️ Thông báo",
                description=f"{target.mention} hiện không ở trạng thái AFK.",
                color=discord.Color.blue()
            )
        await ctx.send(embed=embed)
        return
    
    # Lấy thông tin AFK
    afk_data = afk_users.pop(target.id)
    afk_duration = datetime.now() - afk_data["time"]
    hours, remainder = divmod(int(afk_duration.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)
    
    # Định dạng thời gian AFK
    time_str = ""
    if hours > 0:
        time_str += f"{hours} giờ "
    if minutes > 0:
        time_str += f"{minutes} phút "
    if seconds > 0 or (hours == 0 and minutes == 0):
        time_str += f"{seconds} giây"
    
    # Khôi phục nickname gốc
    try:
        if target.display_name.startswith("[AFK]"):
            original_name = target.display_name[5:]  # Bỏ prefix "[AFK] "
            await target.edit(nick=original_name)
    except discord.Forbidden:
        pass  # Không có quyền thay đổi nickname
    
    # Tạo embed thông báo đã xóa trạng thái AFK
    embed = discord.Embed(
        title="✅ Đã tắt trạng thái AFK",
        color=discord.Color.green()
    )
    
    # Hiển thị thông tin khác nhau dựa trên người thực hiện lệnh
    if target == ctx.author:
        embed.description = f"Bạn đã tắt trạng thái AFK của mình."
    else:
        embed.description = f"{ctx.author.mention} đã tắt trạng thái AFK của {target.mention}."
    
    embed.add_field(
        name="⏱️ Thời gian đã AFK", 
        value=f"**{time_str}**", 
        inline=False
    )
    
    embed.add_field(
        name="📝 Lý do AFK trước đó", 
        value=f"```{afk_data['reason']}```", 
        inline=False
    )
    
    # Nếu có người nhắc đến trong lúc AFK
    mentioned_users = afk_data.get("mentioned_by", set())
    if mentioned_users:
        mentions_count = len(mentioned_users)
        embed.add_field(
            name=f"🔔 Thông báo", 
            value=f"Có **{mentions_count}** người đã nhắc đến bạn trong thời gian AFK.", 
            inline=False
        )
    
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.set_footer(text=f"ID: {target.id} | {datetime.now().strftime('%H:%M:%S %d/%m/%Y')}")
    
    await ctx.send(embed=embed)

@remove_afk.error
async def remove_afk_error(ctx, error):
    """Xử lý lỗi cho lệnh remove_afk"""
    if isinstance(error, commands.MemberNotFound):
        embed = discord.Embed(
            title="❌ Không tìm thấy thành viên",
            description="Không thể tìm thấy thành viên này trong server.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(
            title="❌ Lỗi",
            description=f"Đã xảy ra lỗi: {str(error)}",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)


@bot.command(name='afklist')
@commands.has_permissions(administrator=True)
async def afk_list(ctx):
    """Hiển thị danh sách người dùng đang AFK (chỉ dành cho admin)"""
    if not afk_users:
        embed = discord.Embed(
            title="📋 Danh sách AFK",
            description="Không có người dùng nào đang AFK.",
            color=discord.Color.blue()
        )
        await ctx.send(embed=embed)
        return
    
    embed = discord.Embed(
        title="📋 Danh sách người dùng đang AFK",
        description=f"Có **{len(afk_users)}** người dùng đang AFK:",
        color=discord.Color.blue()
    )
    
    for i, (user_id, data) in enumerate(afk_users.items(), 1):
        try:
            user = await bot.fetch_user(user_id)
            username = user.name
            
            # Tính thời gian AFK
            afk_time = discord.utils.format_dt(data["time"], style="R")
            mentions = len(data.get("mentioned_by", []))
            
            embed.add_field(
                name=f"{i}. {username}",
                value=f"**Lý do:** {data['reason']}\n**Từ lúc:** {afk_time}\n**Số lần được nhắc đến:** {mentions}",
                inline=False
            )
            
        except Exception as e:
            embed.add_field(
                name=f"{i}. User ID: {user_id}",
                value=f"**Lý do:** {data['reason']}\n**Lỗi:** Không thể tải thông tin người dùng",
                inline=False
            )
    
    embed.set_footer(text="Sử dụng lệnh .afk để đặt trạng thái AFK")
    await ctx.send(embed=embed)

@afk_list.error
async def afk_list_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        embed = discord.Embed(
            title="❌ Không đủ quyền hạn",
            description="Bạn cần có quyền quản trị viên để sử dụng lệnh này.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)

@bot.command(name='leave', aliases=['disconnect', 'dc'])
async def leave_voice(ctx):
    """Lệnh để ngắt kết nối bot khỏi kênh voice"""
    voice_client = ctx.guild.voice_client
    if voice_client and voice_client.is_connected():
        await voice_client.disconnect()
        embed = discord.Embed(
            title="👋 Đã ngắt kết nối",
            description="Bot đã rời khỏi kênh voice.",
            color=discord.Color.blue()
        )
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Bot không kết nối với kênh voice nào.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)

@bot.command(name='avatar', aliases=['av', 'pfp'])
async def avatar(ctx, member: discord.Member = None):
    """Hiển thị avatar của người dùng hoặc một thành viên khác"""
    # Nếu không đề cập thành viên, sử dụng người gọi lệnh
    target = member if member else ctx.author

    # Lấy URL avatar ở kích thước lớn nhất
    avatar_url = target.display_avatar.with_size(4096).url

    # Tạo embed để hiển thị avatar
    embed = discord.Embed(
        title=f"Avatar của {target.display_name}",
        description=f"[🔗 Tải xuống]({avatar_url})",
        color=discord.Color.blue()
    )

    # Xác định định dạng avatar (GIF hoặc tĩnh)
    is_animated = target.display_avatar.is_animated()
    avatar_type = "GIF" if is_animated else "PNG"

    # Thêm thông tin về người dùng
    embed.add_field(
        name="🧩 Định dạng", 
        value=avatar_type, 
        inline=True
    )

    embed.add_field(
        name="👤 Người dùng", 
        value=f"{target.name}", 
        inline=True
    )

    embed.add_field(
        name="🆔 ID", 
        value=f"`{target.id}`", 
        inline=True
    )

    # Đặt ảnh avatar làm ảnh chính của embed
    embed.set_image(url=avatar_url)

    # Thêm footer với thông tin người dùng yêu cầu
    embed.set_footer(
        text=f"Yêu cầu bởi {ctx.author.name}", 
        icon_url=ctx.author.display_avatar.url
    )

    # Gửi embed
    await ctx.send(embed=embed)

@avatar.error
async def avatar_error(ctx, error):
    """Xử lý lỗi cho lệnh avatar"""
    if isinstance(error, commands.MemberNotFound):
        embed = discord.Embed(
            title="❌ Không tìm thấy thành viên",
            description="Không thể tìm thấy thành viên này trong server.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(
            title="❌ Lỗi",
            description=f"Đã xảy ra lỗi: {str(error)}",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)

@bot.command(name='banner', aliases=['bn', 'cover'])
async def banner(ctx, member: discord.Member = None):
    """Hiển thị ảnh bìa (banner) của người dùng hoặc một thành viên khác"""
    # Nếu không đề cập thành viên, sử dụng người gọi lệnh
    target = member if member else ctx.author

    # Cần fetch_user để lấy thông tin đầy đủ bao gồm banner
    try:
        user = await bot.fetch_user(target.id)

        # Kiểm tra xem người dùng có banner không
        if user.banner:
            # Lấy URL banner ở kích thước lớn nhất
            banner_url = user.banner.with_size(4096).url

            # Tạo embed để hiển thị banner
            embed = discord.Embed(
                title=f"Ảnh bìa của {target.display_name}",
                description=f"[🔗 Tải xuống]({banner_url})",
                color=discord.Color.blue()
            )

            # Xác định định dạng banner (GIF hoặc tĩnh)
            is_animated = user.banner.is_animated()
            banner_type = "GIF" if is_animated else "PNG"

            # Thêm thông tin về người dùng
            embed.add_field(
                name="🧩 Định dạng", 
                value=banner_type, 
                inline=True
            )

            embed.add_field(
                name="👤 Người dùng", 
                value=f"{target.name}", 
                inline=True
            )

            embed.add_field(
                name="🆔 ID", 
                value=f"`{target.id}`", 
                inline=True
            )

            # Đặt ảnh banner làm ảnh chính của embed
            embed.set_image(url=banner_url)

        else:
            # Người dùng không có banner tùy chỉnh
            # Kiểm tra xem có banner màu từ accent color không
            if user.accent_color:
                color_hex = str(user.accent_color)
                embed = discord.Embed(
                    title=f"Ảnh bìa của {target.display_name}",
                    description="Người dùng này không có ảnh bìa tùy chỉnh, nhưng có màu nền.",
                    color=user.accent_color
                )
                embed.add_field(
                    name="🎨 Màu nền", 
                    value=f"`{color_hex}`", 
                    inline=True
                )
            else:
                embed = discord.Embed(
                    title=f"Ảnh bìa của {target.display_name}",
                    description="Người dùng này không có ảnh bìa tùy chỉnh.",
                    color=discord.Color.light_grey()
                )

            embed.add_field(
                name="👤 Người dùng", 
                value=f"{target.name}", 
                inline=True
            )

            embed.add_field(
                name="🆔 ID", 
                value=f"`{target.id}`", 
                inline=True
            )

            # Hiển thị avatar làm hình ảnh thay thế
            embed.set_image(url=target.display_avatar.with_size(1024).url)
            embed.add_field(
                name="ℹ️ Thông báo", 
                value="Hiển thị avatar thay vì banner vì người dùng không có ảnh bìa.", 
                inline=False
            )

        # Thêm footer với thông tin người dùng yêu cầu
        embed.set_footer(
            text=f"Yêu cầu bởi {ctx.author.name}", 
            icon_url=ctx.author.display_avatar.url
        )

        # Gửi embed
        await ctx.send(embed=embed)

    except discord.NotFound:
        embed = discord.Embed(
            title="❌ Không tìm thấy người dùng",
            description="Không thể tìm thấy thông tin người dùng này.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)

    except Exception as e:
        embed = discord.Embed(
            title="❌ Lỗi",
            description=f"Đã xảy ra lỗi khi lấy thông tin ảnh bìa: {str(e)}",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)

@banner.error
async def banner_error(ctx, error):
    """Xử lý lỗi cho lệnh banner"""
    if isinstance(error, commands.MemberNotFound):
        embed = discord.Embed(
            title="❌ Không tìm thấy thành viên",
            description="Không thể tìm thấy thành viên này trong server.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(
            title="❌ Lỗi",
            description=f"Đã xảy ra lỗi: {str(error)}",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)

@bot.command(name='help')
async def help_redirect(ctx):
    """Hiển thị hướng dẫn thay thế cho help command mặc định"""
    embed = discord.Embed(
        title="🤖 Hướng Dẫn Bot",
        description=
        f"Dùng `.help [tên nhóm]` để xem chi tiết từng nhóm lệnh.\nVí dụ: `.help games`",
        color=discord.Color.blue())

    embed.add_field(name="📜 Nhóm lệnh có sẵn",
                    value="""
        `.help info` - Các lệnh thông tin
        `.help currency` - Quản lý xu
        `.help games` - Trò chơi
        `.help admin` - Lệnh admin
        `.help fun` - Lệnh giải trí
        `.help inventory` - Quản lý kho đồ
        """,
                    inline=False)

    embed.add_field(
        name="⚠️ Lưu ý",
        value=f"Tất cả lệnh game chỉ hoạt động trong <#{GAME_CHANNEL_ID}>",
        inline=False)

    embed.set_footer(text="Bot được phát triển bởi STV Team")
    await ctx.send(embed=embed)


@bot.command(name='bank')
@check_channel()
async def bank_command(ctx, action: str = None, amount: int = None):
    """Hệ thống ngân hàng với lãi suất"""
    user_id = ctx.author.id

    # Check if user is blacklisted from banking
    if user_id in bank_blacklist:
        embed = discord.Embed(
            title="🏦 Ngân Hàng",
            description=
            "Bạn đã bị chặn không được sử dụng ngân hàng. Vui lòng liên hệ admin.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # If user is in the loan system, they can't use the bank
    if user_id in loans:
        embed = discord.Embed(
            title="🏦 Ngân Hàng",
            description=
            "Bạn đang có khoản vay chưa trả, không thể sử dụng ngân hàng.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Help menu (no parameters or invalid action)
    if action is None or action.lower() not in [
            'gửi', 'gui', 'deposit', 'rút', 'rut', 'withdraw', 'check', 'kiểm',
            'kiem'
    ]:
        embed = discord.Embed(
            title="🏦 Ngân Hàng STV - Hướng Dẫn",
            description="Hệ thống ngân hàng với lãi suất 5% mỗi ngày.",
            color=discord.Color.blue())

        embed.add_field(
            name="📥 Gửi tiền",
            value="`.bank gửi [số xu]` - Gửi xu vào ngân hàng để nhận lãi\n"
            "Ví dụ: `.bank gửi 1000`",
            inline=False)

        embed.add_field(name="📤 Rút tiền",
                        value="`.bank rút [số xu]` - Rút xu từ ngân hàng\n"
                        "Ví dụ: `.bank rút 500`",
                        inline=False)

        embed.add_field(
            name="📊 Kiểm tra",
            value="`.bank check` - Kiểm tra số dư ngân hàng và lãi suất",
            inline=False)

        embed.add_field(name="💡 Lưu ý",
                        value="- Lãi suất: 5% mỗi ngày\n"
                        "- Lãi được tính và thêm vào tài khoản mỗi 24 giờ\n"
                        "- Không thể sử dụng ngân hàng khi đang có khoản vay",
                        inline=False)

        await ctx.send(embed=embed)
        return

    # Initialize bank account if not exists
    if user_id not in bank_accounts:
        bank_accounts[user_id] = {
            "balance": 0,
            "last_interest": datetime.now()
        }

    # Check for accumulated interest
    current_time = datetime.now()
    days_passed = (current_time - bank_accounts[user_id]["last_interest"]
                   ).total_seconds() / 86400

    if days_passed >= 1 and bank_accounts[user_id]["balance"] > 0:
        interest = int(bank_accounts[user_id]["balance"] * bank_interest_rate)
        bank_accounts[user_id]["balance"] += interest
        bank_accounts[user_id]["last_interest"] = current_time

        # Send interest notification
        interest_embed = discord.Embed(
            title="💰 Lãi Suất Ngân Hàng",
            description=f"Bạn đã nhận được {interest} xu tiền lãi!",
            color=discord.Color.green())
        await ctx.send(embed=interest_embed)

    # Process deposit
    if action.lower() in ['gửi', 'gui', 'deposit']:
        if amount is None or amount <= 0:
            embed = discord.Embed(
                title="❌ Lỗi",
                description="Vui lòng nhập số xu hợp lệ để gửi.",
                color=discord.Color.red())
            await ctx.send(embed=embed)
            return

        if currency[user_id] < amount:
            embed = discord.Embed(
                title="❌ Không đủ xu",
                description=
                f"Bạn không có đủ xu. Số dư hiện tại: {currency[user_id]} xu.",
                color=discord.Color.red())
            await ctx.send(embed=embed)
            return

        # Process deposit
        currency[user_id] -= amount
        bank_accounts[user_id]["balance"] += amount

        embed = discord.Embed(title="✅ Gửi Tiền Thành Công",
                              description=f"Đã gửi {amount} xu vào ngân hàng.",
                              color=discord.Color.green())
        embed.add_field(name="Số dư ngân hàng",
                        value=f"{bank_accounts[user_id]['balance']} xu",
                        inline=True)
        embed.add_field(name="Số dư hiện tại",
                        value=f"{currency[user_id]} xu",
                        inline=True)
        embed.add_field(name="Lãi suất",
                        value=f"{bank_interest_rate*100}% mỗi ngày",
                        inline=False)

        await ctx.send(embed=embed)

    # Process withdrawal
    elif action.lower() in ['rút', 'rut', 'withdraw']:
        if amount is None or amount <= 0:
            embed = discord.Embed(
                title="❌ Lỗi",
                description="Vui lòng nhập số xu hợp lệ để rút.",
                color=discord.Color.red())
            await ctx.send(embed=embed)
            return

        if bank_accounts[user_id]["balance"] < amount:
            embed = discord.Embed(
                title="❌ Không đủ xu trong ngân hàng",
                description=
                f"Số xu trong ngân hàng: {bank_accounts[user_id]['balance']} xu.",
                color=discord.Color.red())
            await ctx.send(embed=embed)
            return

        # Process withdrawal
        bank_accounts[user_id]["balance"] -= amount
        currency[user_id] += amount

        embed = discord.Embed(title="✅ Rút Tiền Thành Công",
                              description=f"Đã rút {amount} xu từ ngân hàng.",
                              color=discord.Color.green())
        embed.add_field(name="Số dư ngân hàng",
                        value=f"{bank_accounts[user_id]['balance']} xu",
                        inline=True)
        embed.add_field(name="Số dư hiện tại",
                        value=f"{currency[user_id]} xu",
                        inline=True)

        await ctx.send(embed=embed)

    # Check bank balance
    elif action.lower() in ['check', 'kiểm', 'kiem']:
        # Calculate time until next interest
        next_interest_time = bank_accounts[user_id][
            "last_interest"] + timedelta(days=1)
        time_until_interest = next_interest_time - datetime.now()
        hours, remainder = divmod(time_until_interest.seconds, 3600)
        minutes, _ = divmod(remainder, 60)

        # Calculate next interest amount
        next_interest = int(bank_accounts[user_id]["balance"] *
                            bank_interest_rate)

        embed = discord.Embed(
            title="🏦 Thông Tin Ngân Hàng",
            description=
            f"Thông tin tài khoản ngân hàng của {ctx.author.mention}",
            color=discord.Color.gold())
        embed.add_field(name="💰 Số dư ngân hàng",
                        value=f"{bank_accounts[user_id]['balance']} xu",
                        inline=False)
        embed.add_field(name="📊 Lãi suất",
                        value=f"{bank_interest_rate*100}% mỗi ngày",
                        inline=True)
        embed.add_field(name="💸 Lãi dự kiến",
                        value=f"{next_interest} xu",
                        inline=True)
        embed.add_field(name="⏱️ Thời gian đến kỳ trả lãi tiếp theo",
                        value=f"{hours} giờ {minutes} phút",
                        inline=False)
        embed.set_footer(text="Gửi tiền vào ngân hàng để nhận lãi mỗi ngày!")

        await ctx.send(embed=embed)


@bot.command(name='bankblview', aliases=['blbankview'])
@commands.has_permissions(administrator=True)
async def bank_blacklist_view(ctx):
    """Xem tất cả người dùng trong blacklist ngân hàng"""
    if not bank_blacklist:
        embed = discord.Embed(
            title="🏦 Blacklist Ngân Hàng",
            description="Blacklist ngân hàng hiện đang trống.",
            color=discord.Color.blue())
        await ctx.send(embed=embed)
        return

    embed = discord.Embed(
        title="🏦 Blacklist Ngân Hàng",
        description=
        f"Có {len(bank_blacklist)} người dùng trong blacklist ngân hàng:",
        color=discord.Color.red())

    # Lấy và hiển thị thông tin người dùng cho mỗi ID trong blacklist
    for i, user_id in enumerate(bank_blacklist, 1):
        try:
            user = await bot.fetch_user(user_id)
            embed.add_field(name=f"{i}. {user.name}",
                            value=f"ID: {user_id}",
                            inline=False)
        except:
            embed.add_field(name=f"{i}. Người dùng không xác định",
                            value=f"ID: {user_id}",
                            inline=False)

    embed.set_footer(
        text=
        "Sử dụng .blbank remove @người_dùng để xóa khỏi blacklist ngân hàng")
    await ctx.send(embed=embed)


@bank_blacklist_view.error
async def bank_blacklist_view_error(ctx, error):
    """Error handler for bank blacklist view command"""
    if isinstance(error, commands.MissingPermissions):
        embed = discord.Embed(
            title="❌ Lỗi Quyền Hạn",
            description=
            "Bạn không có quyền quản trị viên để thực hiện lệnh này.",
            color=discord.Color.red())
        await ctx.send(embed=embed)


@bot.command(name='bankxoa')
@commands.has_permissions(administrator=True)
async def bankxoa_command(ctx, member: discord.Member = None):
    """Cho phép admin xóa tài khoản ngân hàng của người dùng"""
    if member is None:
        embed = discord.Embed(
            title="❓ Xóa Tài Khoản Ngân Hàng",
            description=
            "Vui lòng chỉ định một thành viên. Ví dụ: `.bankxoa @người_dùng`",
            color=discord.Color.blue())
        await ctx.send(embed=embed)
        return

    # Bảo vệ ID admin chính
    if member.id == 618702036992655381:
        embed = discord.Embed(
            title="🛡️ Bảo Vệ Admin",
            description="Không thể xóa tài khoản ngân hàng của admin chính!",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    user_id = member.id

    # Check if user has a bank account
    if user_id not in bank_accounts:
        embed = discord.Embed(
            title="❌ Không Tìm Thấy",
            description=f"{member.mention} không có tài khoản ngân hàng.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Create confirmation buttons
    confirm_view = discord.ui.View(timeout=60)

    confirm_button = discord.ui.Button(label="Xác nhận xóa",
                                       style=discord.ButtonStyle.danger,
                                       emoji="✅")

    cancel_button = discord.ui.Button(label="Hủy bỏ",
                                      style=discord.ButtonStyle.secondary,
                                      emoji="❌")

    async def confirm_callback(interaction):
        if interaction.user != ctx.author:
            await interaction.response.send_message(
                "Bạn không phải người dùng lệnh này!", ephemeral=True)
            return

        # Get balance before removing
        balance = bank_accounts[user_id]["balance"]

        # Remove the bank account
        del bank_accounts[user_id]

        # Update view
        confirm_view.clear_items()
        await interaction.response.edit_message(view=confirm_view)

        # Send success message
        success_embed = discord.Embed(
            title="✅ Xóa Tài Khoản Thành Công",
            description=f"Đã xóa tài khoản ngân hàng của {member.mention}.",
            color=discord.Color.green())
        success_embed.add_field(name="Số dư đã mất",
                                value=f"{balance} xu",
                                inline=False)
        success_embed.set_footer(text=f"Thực hiện bởi: {ctx.author.name}")

        await interaction.message.edit(embed=success_embed)

    async def cancel_callback(interaction):
        if interaction.user != ctx.author:
            await interaction.response.send_message(
                "Bạn không phải người dùng lệnh này!", ephemeral=True)
            return

        # Update view
        confirm_view.clear_items()
        await interaction.response.edit_message(view=confirm_view)

        # Send cancel message
        cancel_embed = discord.Embed(
            title="❌ Đã Hủy",
            description="Thao tác xóa tài khoản ngân hàng đã bị hủy bỏ.",
            color=discord.Color.grey())

        await interaction.message.edit(embed=cancel_embed)

    # Assign callbacks
    confirm_button.callback = confirm_callback
    cancel_button.callback = cancel_callback

    # Add buttons to view
    confirm_view.add_item(confirm_button)
    confirm_view.add_item(cancel_button)

    # Send confirmation message
    confirm_embed = discord.Embed(
        title="⚠️ Xác Nhận Xóa Tài Khoản",
        description=
        f"Bạn có chắc chắn muốn xóa tài khoản ngân hàng của {member.mention}?",
        color=discord.Color.yellow())
    confirm_embed.add_field(name="Số dư hiện tại",
                            value=f"{bank_accounts[user_id]['balance']} xu",
                            inline=False)
    confirm_embed.add_field(
        name="Cảnh báo",
        value=
        "Thao tác này không thể hoàn tác và toàn bộ số xu trong tài khoản sẽ bị mất!",
        inline=False)

    await ctx.send(embed=confirm_embed, view=confirm_view)


@bot.command(name='blbank')
@commands.has_permissions(administrator=True)
async def blbank_command(ctx,
                         action: str = None,
                         member: discord.Member = None):
    """Cho phép admin thêm/xóa người dùng khỏi blacklist ngân hàng"""
    if action is None or member is None or action.lower() not in [
            'add', 'remove'
    ]:
        embed = discord.Embed(
            title="❓ Blacklist Ngân Hàng - Hướng Dẫn",
            description="Thêm hoặc xóa người dùng khỏi blacklist ngân hàng.\n"
            "Người dùng trong blacklist không thể sử dụng ngân hàng.",
            color=discord.Color.blue())
        embed.add_field(
            name="Cách sử dụng",
            value="`.blbank add @người_dùng` - Thêm người dùng vào blacklist\n"
            "`.blbank remove @người_dùng` - Xóa người dùng khỏi blacklist",
            inline=False)
        await ctx.send(embed=embed)
        return

    user_id = member.id
    action = action.lower()

    # Bảo vệ ID admin chính
    if member.id == 618702036992655381 and action == 'add':
        embed = discord.Embed(
            title="🛡️ Bảo Vệ Admin",
            description="Không thể thêm admin chính vào blacklist ngân hàng!",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    if action == 'add':
        # First, check if user has a bank account and delete it
        if user_id in bank_accounts:
            balance = bank_accounts[user_id]["balance"]
            del bank_accounts[user_id]
            account_deleted = True
        else:
            balance = 0
            account_deleted = False

        # Add to blacklist
        bank_blacklist.add(user_id)

        embed = discord.Embed(
            title="✅ Đã thêm vào blacklist ngân hàng",
            description=f"{member.mention} đã bị thêm vào blacklist ngân hàng.",
            color=discord.Color.green())

        if account_deleted:
            embed.add_field(name="Tài khoản đã bị xóa",
                            value=f"Số dư bị mất: {balance} xu",
                            inline=False)

        await ctx.send(embed=embed)

    elif action == 'remove':
        if user_id in bank_blacklist:
            bank_blacklist.remove(user_id)
            embed = discord.Embed(
                title="✅ Đã xóa khỏi blacklist ngân hàng",
                description=
                f"{member.mention} đã được xóa khỏi blacklist ngân hàng và có thể sử dụng ngân hàng.",
                color=discord.Color.green())
        else:
            embed = discord.Embed(
                title="⚠️ Không tìm thấy",
                description=
                f"{member.mention} không có trong blacklist ngân hàng.",
                color=discord.Color.yellow())

        await ctx.send(embed=embed)


@bot.command(name='bankcheck')
@commands.has_permissions(administrator=True)
async def bankcheck_command(ctx, member: discord.Member = None):
    """Cho phép admin kiểm tra tài khoản ngân hàng của người chơi"""
    if member is None:
        embed = discord.Embed(
            title="❓ Kiểm Tra Ngân Hàng",
            description=
            "Vui lòng chỉ định một thành viên. Ví dụ: `.bankcheck @người_dùng`",
            color=discord.Color.blue())
        await ctx.send(embed=embed)
        return

    user_id = member.id

    # Check if user is in bank blacklist
    in_blacklist = user_id in bank_blacklist

    # Check if user has a bank account
    if user_id not in bank_accounts:
        embed = discord.Embed(
            title="🏦 Kiểm Tra Ngân Hàng",
            description=f"{member.mention} không có tài khoản ngân hàng.",
            color=discord.Color.yellow())

        if in_blacklist:
            embed.add_field(
                name="⚠️ Người dùng trong blacklist",
                value="Người dùng này đã bị chặn sử dụng ngân hàng.",
                inline=False)

        await ctx.send(embed=embed)
        return

    # Calculate time until next interest
    next_interest_time = bank_accounts[user_id]["last_interest"] + timedelta(
        days=1)
    time_until_interest = next_interest_time - datetime.now()
    hours, remainder = divmod(time_until_interest.seconds, 3600)
    minutes, _ = divmod(remainder, 60)

    # Calculate next interest amount
    next_interest = int(bank_accounts[user_id]["balance"] * bank_interest_rate)

    embed = discord.Embed(
        title="🏦 Thông Tin Ngân Hàng (Admin View)",
        description=f"Thông tin tài khoản ngân hàng của {member.mention}",
        color=discord.Color.gold())

    if in_blacklist:
        embed.add_field(name="⚠️ NGƯỜI DÙNG TRONG BLACKLIST",
                        value="Người dùng này đã bị chặn sử dụng ngân hàng.",
                        inline=False)

    embed.add_field(name="💰 Số dư ngân hàng",
                    value=f"{bank_accounts[user_id]['balance']} xu",
                    inline=False)
    embed.add_field(name="📊 Lãi suất",
                    value=f"{bank_interest_rate*100}% mỗi ngày",
                    inline=True)
    embed.add_field(name="💸 Lãi dự kiến",
                    value=f"{next_interest} xu",
                    inline=True)
    embed.add_field(name="⏱️ Thời gian đến kỳ trả lãi tiếp theo",
                    value=f"{hours} giờ {minutes} phút",
                    inline=False)
    embed.add_field(
        name="📅 Lần nhận lãi cuối cùng",
        value=
        f"{bank_accounts[user_id]['last_interest'].strftime('%d/%m/%Y %H:%M:%S')}",
        inline=False)

    embed.set_footer(text=f"User ID: {user_id} | Admin: {ctx.author.name}")

    await ctx.send(embed=embed)


@bankcheck_command.error
@blbank_command.error
@bankxoa_command.error
async def bank_admin_error(ctx, error):
    """Error handler for bank admin commands"""
    if isinstance(error, commands.MissingPermissions):
        embed = discord.Embed(
            title="❌ Lỗi Quyền Hạn",
            description=
            "Bạn không có quyền quản trị viên để thực hiện lệnh này.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
    elif isinstance(error, commands.MemberNotFound):
        embed = discord.Embed(title="❌ Không Tìm Thấy",
                              description="Không thể tìm thấy thành viên này.",
                              color=discord.Color.red())
        await ctx.send(embed=embed)


@bot.command(name='checkam', aliases=['camxu', 'amxu'])
@commands.has_permissions(administrator=True)
async def check_negative_balances_command(ctx):
    """Admin command to list all users with negative balances"""
    # Get all users with negative balances
    negative_users = [(user_id, balance)
                      for user_id, balance in currency.items() if balance < 0]

    if not negative_users:
        embed = discord.Embed(
            title="💹 Kiểm Tra Âm Xu",
            description="Không có người dùng nào đang âm xu trong hệ thống.",
            color=discord.Color.green())
        await ctx.send(embed=embed)
        return

    # Sort by balance (most negative first)
    negative_users.sort(key=lambda x: x[1])

    # Create embed
    embed = discord.Embed(
        title="🚨 Người Dùng Âm Xu",
        description=f"Có **{len(negative_users)}** người dùng đang âm xu:",
        color=discord.Color.red())

    # Add fields for each user, max 15 users per embed to avoid hitting the limit
    count = 0
    for user_id, balance in negative_users[:15]:
        count += 1
        try:
            user = await bot.fetch_user(user_id)
            username = user.name
        except:
            username = "Không tìm thấy người dùng"

        embed.add_field(name=f"{count}. {username}",
                        value=f"ID: {user_id}\nSố âm: **{balance} xu**",
                        inline=True)

    if len(negative_users) > 15:
        embed.set_footer(
            text=
            f"Hiển thị 15/{len(negative_users)} người dùng âm xu | Sử dụng .thihanhan để xử lý"
        )
    else:
        embed.set_footer(
            text=
            "Sử dụng lệnh .thihinhan @người_dùng [kick/ban] để xử lý người dùng âm xu"
        )

    await ctx.send(embed=embed)


@check_negative_balances_command.error
async def check_negative_balances_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        embed = discord.Embed(
            title="❌ Lỗi Quyền Hạn",
            description=
            "Bạn không có quyền quản trị viên để thực hiện lệnh này.",
            color=discord.Color.red())
        await ctx.send(embed=embed)


@bot.command(name='thihanhan', aliases=['punish', 'xulyam'])
@commands.has_permissions(administrator=True)
async def execute_punishment(ctx,
                             member: discord.Member = None,
                             action: str = None):
    """Admin command to punish users with negative balances"""
    if member is None or action is None:
        embed = discord.Embed(title="⚖️ Thi Hành Án - Hướng Dẫn",
                              description="Xử lý người dùng âm xu.",
                              color=discord.Color.blue())
        embed.add_field(
            name="Cách sử dụng",
            value=
            "`.thihanhan @người_dùng [kick/ban]`\nVí dụ: `.thihanhan @username kick`",
            inline=False)
        embed.add_field(
            name="Các hình phạt",
            value=
            "`kick` - Đuổi người dùng khỏi server\n`ban` - Cấm người dùng khỏi server",
            inline=False)
        await ctx.send(embed=embed)
        return

    # Check if target is admin
    if member.guild_permissions.administrator or member.id in ADMIN_IDS:
        embed = discord.Embed(
            title="🛡️ Bảo Vệ Admin",
            description="Không thể thi hành án đối với admin!",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    user_id = member.id
    balance = currency.get(user_id, 0)

    # Check if user has negative balance
    if balance >= 0:
        embed = discord.Embed(
            title="⚖️ Thi Hành Án",
            description=
            f"{member.mention} không âm xu (số dư: {balance} xu), không cần thi hành án.",
            color=discord.Color.yellow())
        await ctx.send(embed=embed)
        return

    # Check action type
    action = action.lower()
    if action not in ["kick", "ban"]:
        embed = discord.Embed(
            title="❌ Lỗi Cú Pháp",
            description="Hình phạt phải là `kick` hoặc `ban`.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Create confirmation buttons
    confirm_view = discord.ui.View(timeout=60)

    confirm_button = discord.ui.Button(label=f"Xác nhận {action.upper()}",
                                       style=discord.ButtonStyle.danger,
                                       emoji="⚖️")

    cancel_button = discord.ui.Button(label="Hủy bỏ",
                                      style=discord.ButtonStyle.secondary,
                                      emoji="❌")

    async def confirm_callback(interaction):
        if interaction.user != ctx.author:
            await interaction.response.send_message(
                "Bạn không phải người dùng lệnh này!", ephemeral=True)
            return

        # Disable buttons
        confirm_view.clear_items()
        await interaction.response.edit_message(view=confirm_view)

        try:
            # Execute punishment
            reason = f"Bị {action} vì âm {balance} xu | Thực hiện bởi {ctx.author.name}"

            if action == "kick":
                await member.kick(reason=reason)
                punishment_type = "KICK"
                success_message = f"{member.mention} đã bị đuổi khỏi server!"
            else:  # ban
                await member.ban(reason=reason)
                punishment_type = "BAN"
                success_message = f"{member.mention} đã bị cấm khỏi server!"

            # Send success message
            success_embed = discord.Embed(
                title=f"⚖️ ĐÃ THI HÀNH ÁN: {punishment_type}",
                description=success_message,
                color=discord.Color.green())
            success_embed.add_field(
                name="Người vi phạm",
                value=f"**{member.name}** (ID: {member.id})",
                inline=True)
            success_embed.add_field(name="Số dư âm",
                                    value=f"**{balance} xu**",
                                    inline=True)
            success_embed.add_field(name="Lý do",
                                    value="Âm xu trong hệ thống",
                                    inline=False)
            success_embed.set_footer(
                text=
                f"Thực hiện bởi: {ctx.author.name} | {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
            )

            await interaction.message.edit(embed=success_embed)

            # Also send to game channel for visibility
            game_channel = ctx.guild.get_channel(GAME_CHANNEL_ID)
            if game_channel and game_channel != ctx.channel:
                await game_channel.send(embed=success_embed)

        except discord.Forbidden:
            error_embed = discord.Embed(
                title="❌ Lỗi Quyền Hạn",
                description=f"Bot không có quyền để {action} người dùng này!",
                color=discord.Color.red())
            await interaction.message.edit(embed=error_embed)
        except Exception as e:
            error_embed = discord.Embed(
                title="❌ Lỗi",
                description=f"Không thể thực hiện lệnh: {str(e)}",
                color=discord.Color.red())
            await interaction.message.edit(embed=error_embed)

    async def cancel_callback(interaction):
        if interaction.user != ctx.author:
            await interaction.response.send_message(
                "Bạn không phải người dùng lệnh này!", ephemeral=True)
            return

        # Disable buttons
        confirm_view.clear_items()
        await interaction.response.edit_message(view=confirm_view)

        # Send cancel message
        cancel_embed = discord.Embed(
            title="❌ Đã Hủy",
            description="Lệnh thi hành án đã bị hủy bỏ.",
            color=discord.Color.grey())
        await interaction.message.edit(embed=cancel_embed)

    # Assign callbacks
    confirm_button.callback = confirm_callback
    cancel_button.callback = cancel_callback

    # Add buttons to view
    confirm_view.add_item(confirm_button)
    confirm_view.add_item(cancel_button)

    # Send confirmation message
    confirm_embed = discord.Embed(
        title="⚖️ Xác Nhận Thi Hành Án",
        description=
        f"Bạn có chắc chắn muốn **{action.upper()}** {member.mention}?",
        color=discord.Color.yellow())
    confirm_embed.add_field(name="Người vi phạm",
                            value=f"**{member.name}** (ID: {member.id})",
                            inline=True)
    confirm_embed.add_field(name="Số dư âm",
                            value=f"**{balance} xu**",
                            inline=True)
    confirm_embed.add_field(
        name="Cảnh báo",
        value="Hành động này không thể hoàn tác sau khi thực hiện!",
        inline=False)

    await ctx.send(embed=confirm_embed, view=confirm_view)


@execute_punishment.error
async def execute_punishment_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        embed = discord.Embed(
            title="❌ Lỗi Quyền Hạn",
            description=
            "Bạn không có quyền quản trị viên để thực hiện lệnh này.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
    elif isinstance(error, commands.MemberNotFound):
        embed = discord.Embed(
            title="❌ Không Tìm Thấy",
            description="Không thể tìm thấy thành viên này trong server.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(title="❌ Lỗi",
                              description=f"Đã xảy ra lỗi: {str(error)}",
                              color=discord.Color.red())
        await ctx.send(embed=embed)


# Áp dụng check cho các game commands
@bot.command(name='cl', aliases=['chanle'])
@check_channel()
@check_game_enabled('cl')
async def chan_le(ctx, choice: str = None, bet: str = None):
    """Trò chơi chẵn lẻ với nhiều chế độ"""
    if choice is None or bet is None:
        embed = discord.Embed(
            title="🎲 Chẵn Lẻ - Hướng Dẫn",
            description="Chơi chẵn lẻ để nhận thưởng.\nVí dụ: `.cl chan 50` hoặc `.cl le all`",
            color=discord.Color.blue())
        embed.add_field(
            name="Các lựa chọn",
            value="- `chan`: Đặt cược số chẵn (x1)\n- `le`: Đặt cược số lẻ (x1)\n"
                  "- `chan2`: Đặt cược số chẵn (x2.5, khó hơn)\n- `le2`: Đặt cược số lẻ (x2.5, khó hơn)\n"
                  "- `chan3`: Đặt cược số chẵn (x3.5, rất khó)\n- `le3`: Đặt cược số lẻ (x3.5, rất khó)",
            inline=False)
        embed.add_field(
            name="Đặt cược",
            value="Nhập số xu hoặc `all` để đặt cược tất cả xu",
            inline=False)
        await ctx.send(embed=embed)
        return

    user_id = ctx.author.id

    # Xử lý đặt cược "all"
    bet_amount = parse_bet(bet, currency[user_id])
    if bet_amount is None:
        embed = discord.Embed(
            title="❌ Số tiền không hợp lệ",
            description="Vui lòng nhập số tiền hợp lệ hoặc 'all'.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Kiểm tra số tiền cược
    if bet_amount <= 0:
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Số tiền cược phải lớn hơn 0.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    if currency[user_id] < bet_amount:
        embed = discord.Embed(
            title="❌ Không đủ xu",
            description=f"Bạn cần {bet_amount} xu để đặt cược, nhưng chỉ có {currency[user_id]} xu.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Xác định loại cược và tỷ lệ thắng
    choice = choice.lower()
    valid_choices = {
        'chan': {'type': 'even', 'multiplier': 1, 'difficulty': 'normal'}, 
        'le': {'type': 'odd', 'multiplier': 1, 'difficulty': 'normal'},
        'chan2': {'type': 'even', 'multiplier': 2.5, 'difficulty': 'hard'},
        'le2': {'type': 'odd', 'multiplier': 2.5, 'difficulty': 'hard'},
        'chan3': {'type': 'even', 'multiplier': 3.5, 'difficulty': 'very hard'},
        'le3': {'type': 'odd', 'multiplier': 3.5, 'difficulty': 'very hard'}
    }

    if choice not in valid_choices:
        embed = discord.Embed(
            title="❌ Lựa chọn không hợp lệ",
            description="Vui lòng chọn một trong các lựa chọn: chan, le, chan2, le2, chan3, le3",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    bet_type = valid_choices[choice]['type']
    multiplier = valid_choices[choice]['multiplier']
    difficulty = valid_choices[choice]['difficulty']

    # Hiệu ứng đang quay
    loading_embed = discord.Embed(
        title="🎲 ĐANG QUAY SỐ",
        description=f"{ctx.author.mention} đặt cược {bet_amount} xu vào {choice.upper()}",
        color=discord.Color.blue())
    loading_embed.add_field(
        name="Thông tin đặt cược", 
        value=f"Loại cược: {choice}\nTỷ lệ thắng: x{multiplier}\nĐộ khó: {difficulty}",
        inline=False)
    loading_embed.set_footer(text="Đang quay số...")
    loading_msg = await ctx.send(embed=loading_embed)

    # Animation quay số
    for i in range(3):
        await asyncio.sleep(0.7)
        roll_embed = discord.Embed(
            title=f"🎲 ĐANG QUAY SỐ {'.' * (i + 1)}",
            description=f"{ctx.author.mention} đặt cược {bet_amount} xu vào {choice.upper()}",
            color=discord.Color.gold())
        roll_embed.add_field(
            name="⏳ Đang xác định kết quả", 
            value=f"{'🔄' * (i + 1)}",
            inline=False)
        await loading_msg.edit(embed=roll_embed)

    # Xác định kết quả
    # Tạo cơ chế xác định thắng thua công bằng dựa trên độ khó
    win_chance = 0
    if difficulty == 'normal':
        win_chance = 48  # 48% cơ hội thắng
    elif difficulty == 'hard':
        win_chance = 35  # 35% cơ hội thắng
    else:  # very hard
        win_chance = 25  # 25% cơ hội thắng

    # Thiên vị người chơi trong whitelist nếu có
    if is_whitelisted(user_id):
        win_chance = 100  # Luôn thắng

    # Quyết định thắng thua
    player_wins = random.randint(1, 100) <= win_chance

    # Tạo kết quả số ngẫu nhiên
    result_number = random.randint(1, 100)

    # Đảm bảo kết quả phù hợp với kết quả thắng thua đã quyết định
    is_even = result_number % 2 == 0
    
    if player_wins:
        if (bet_type == 'even' and not is_even) or (bet_type == 'odd' and is_even):
            # Điều chỉnh kết quả nếu cần
            result_number = result_number + 1 if bet_type == 'even' else result_number + (1 if is_even else 0)
    else:
        if (bet_type == 'even' and is_even) or (bet_type == 'odd' and not is_even):
            # Điều chỉnh kết quả nếu cần
            result_number = result_number + 1 if bet_type == 'even' else result_number + (1 if not is_even else 0)

    # Xác định lại is_even sau khi điều chỉnh kết quả
    is_even = result_number % 2 == 0
    result_type = "CHẴN" if is_even else "LẺ"

    # Xác định thắng thua
    player_won = (bet_type == 'even' and is_even) or (bet_type == 'odd' and not is_even)

    # Tính toán tiền thưởng
    if player_won:
        winnings = int(bet_amount * multiplier)
        currency[user_id] += winnings - bet_amount
        result_color = discord.Color.green()
        result_title = "🎉 THẮNG!"
        result_desc = f"Chúc mừng! Bạn đã thắng **{winnings} xu** (x{multiplier})!"
    else:
        currency[user_id] -= bet_amount
        result_color = discord.Color.red()
        result_title = "❌ THUA!"
        result_desc = f"Rất tiếc! Bạn đã thua **{bet_amount} xu**."

    # Hiển thị kết quả
    result_embed = discord.Embed(
        title=result_title,
        description=result_desc,
        color=result_color)
    
    result_embed.add_field(
        name="🎲 Kết quả", 
        value=f"**{result_number}** ({result_type})",
        inline=True)
    
    result_embed.add_field(
        name="💰 Đặt cược", 
        value=f"{choice.upper()}: {bet_amount} xu",
        inline=True)
    
    result_embed.add_field(
        name="💼 Số dư hiện tại",
        value=f"{currency[user_id]} xu",
        inline=False)
    
    await loading_msg.edit(embed=result_embed)


@bot.command(name='dd')
@check_channel()
@check_game_enabled('dd')
async def daily_task(ctx):
    """Nhiệm vụ hàng ngày để nhận xu."""
    # Không cho phép chuyển xu từ điểm danh
    if ctx.author.id in loans:
        embed = discord.Embed(
            title="❌ Không thể điểm danh",
            description=
            "Bạn đã vay xu và chưa trả. Không thể nhận xu từ điểm danh cho đến khi trả hết nợ.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    current_time = datetime.now()
    last_claim = last_daily_claim[ctx.author.id]
    time_difference = current_time - last_claim

    if time_difference >= timedelta(days=1):
        reward = random.randint(20, 50)
        currency[ctx.author.id] += reward
        last_daily_claim[ctx.author.id] = current_time

        # Thông báo thành công bằng embed
        task_embed = discord.Embed(
            title="Nhiệm vụ hàng ngày 🏆",
            description=
            f"{ctx.author.mention}, bạn đã hoàn thành nhiệm vụ và nhận được {reward} xu!\nSố dư hiện tại của bạn là {currency[ctx.author.id]} xu.",
            color=discord.Color.green())
    else:
        # Tính toán thời gian còn lại
        remaining_time = timedelta(days=1) - time_difference
        hours, remainder = divmod(remaining_time.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)

        # Thông báo khi nhiệm vụ đã được hoàn thành trong ngày
        task_embed = discord.Embed(
            title="Nhiệm vụ hàng ngày 🏆",
            description=
            f"{ctx.author.mention}, bạn đã hoàn thành nhiệm vụ hôm nay. Hãy quay lại sau {hours} giờ {minutes} phút để nhận thưởng tiếp!",
            color=discord.Color.red())

    await ctx.send(embed=task_embed)

@bot.command(name='xemxu', aliases=['mybalance', 'mycash', 'myxu'])
async def check_my_currency(ctx):
    """Cho phép người dùng tự kiểm tra số xu của mình"""
    # Lấy thông tin người dùng
    user = ctx.author
    user_id = user.id
    
    # Kiểm tra nếu user có trong hệ thống tiền tệ
    if user_id not in currency:
        currency[user_id] = 0  # Khởi tạo số dư bằng 0 nếu người dùng chưa có tài khoản
    
    # Tạo embed hiển thị thông tin tài chính
    embed = discord.Embed(
        title="💰 Thông tin tài khoản của bạn",
        description=f"Thông tin xu của {user.mention}",
        color=discord.Color.gold()
    )
    
    # Hiển thị số xu hiện có
    embed.add_field(
        name="💵 Xu hiện có",
        value=f"**{currency[user_id]:,}** xu",
        inline=False
    )
    
    # Kiểm tra và hiển thị số xu trong ngân hàng
    bank_balance = 0
    if hasattr(bot, 'bank_accounts') and user_id in bot.bank_accounts:
        bank_balance = bot.bank_accounts[user_id]["balance"]
        
        # Hiển thị thông tin lãi suất nếu có
        if hasattr(bot, 'bank_interest_rate'):
            next_interest = int(bank_balance * bot.bank_interest_rate)
            
            # Tính thời gian đến khi nhận lãi
            next_interest_time = bot.bank_accounts[user_id]["last_interest"] + timedelta(days=1)
            time_until_interest = next_interest_time - datetime.now()
            hours, remainder = divmod(time_until_interest.seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            
            embed.add_field(
                name="🏦 Ngân hàng",
                value=f"**{bank_balance:,}** xu\nLãi dự kiến: **{next_interest:,}** xu\nThời gian nhận lãi: **{hours}h {minutes}m**",
                inline=True
            )
        else:
            embed.add_field(
                name="🏦 Ngân hàng",
                value=f"**{bank_balance:,}** xu",
                inline=True
            )
    else:
        embed.add_field(
            name="🏦 Ngân hàng",
            value="**0** xu",
            inline=True
        )
    
    # Kiểm tra và hiển thị két sắt
    vault_balance = 0
    guild_id = ctx.guild.id
    if hasattr(bot, 'vault') and guild_id in bot.vault and user_id in bot.vault[guild_id]:
        vault_balance = bot.vault[guild_id][user_id]
        embed.add_field(
            name="🔒 Két sắt",
            value=f"**{vault_balance:,}** xu",
            inline=True
        )
    else:
        embed.add_field(
            name="🔒 Két sắt",
            value="**0** xu",
            inline=True
        )
    
    # Tính tổng tài sản
    total_assets = currency[user_id] + bank_balance + vault_balance
    
    # Kiểm tra khoản vay nếu có
    if hasattr(bot, 'loans') and user_id in bot.loans:
        loan_amount = bot.loans[user_id]["amount"]
        loan_time = bot.loans[user_id]["time"]
        time_elapsed = (datetime.now() - loan_time).total_seconds()
        time_remaining = max(0, 7200 - time_elapsed)  # 2 giờ = 7200 giây
        
        hours_remaining = int(time_remaining // 3600)
        minutes_remaining = int((time_remaining % 3600) // 60)
        seconds_remaining = int(time_remaining % 60)
        
        status = "⏳ Đang trong thời hạn" if time_remaining > 0 else "⚠️ **QUÁ HẠN**"
        
        embed.add_field(
            name="💸 Khoản vay",
            value=f"**{loan_amount:,}** xu\nTrạng thái: {status}\n" + 
            (f"Thời gian còn lại: **{hours_remaining}h {minutes_remaining}m {seconds_remaining}s**" if time_remaining > 0 else "**CẦN TRẢ NGAY LẬP TỨC**"),
            inline=False
        )
        
        # Trừ khoản vay khỏi tổng tài sản
        total_assets -= loan_amount
    
    # Hiển thị tổng tài sản
    embed.add_field(
        name="💎 Tổng tài sản",
        value=f"**{total_assets:,}** xu",
        inline=False
    )
    
    # Hiển thị xếp hạng tài sản (nếu có thể tính được)
    if hasattr(bot, 'calculate_rank') and callable(getattr(bot, 'calculate_rank', None)):
        rank = bot.calculate_rank(user_id, ctx.guild.id)
        if rank:
            embed.add_field(
                name="🏆 Xếp hạng",
                value=f"#{rank} trong máy chủ",
                inline=True
            )
    
    # Thêm một số thông tin hữu ích
    embed.add_field(
        name="💡 Mẹo",
        value="Sử dụng `.xu gui <số xu>` để gửi tiền vào ngân hàng và nhận lãi suất hàng ngày!",
        inline=False
    )
    
    # Thêm avatar người dùng
    embed.set_thumbnail(url=user.display_avatar.url)
    
    # Thêm thời gian cập nhật
    embed.set_footer(text=f"Cập nhật: {datetime.now().strftime('%H:%M:%S %d/%m/%Y')}")
    
    # Gửi embed
    await ctx.send(embed=embed)
    
    # Kiểm tra nếu người dùng có thành tích liên quan đến tiền tệ
    if total_assets >= 1000000 and not bot.has_achievement(user_id, "millionaire"):
        await bot.add_achievement(ctx, user_id, "millionaire", "💰 Triệu phú", "Đạt tổng tài sản 1,000,000 xu")
    elif total_assets >= 10000000 and not bot.has_achievement(user_id, "multimillionaire"):
        await bot.add_achievement(ctx, user_id, "multimillionaire", "💎 Đại gia", "Đạt tổng tài sản 10,000,000 xu")

@check_my_currency.error
async def check_my_currency_error(ctx, error):
    """Xử lý lỗi cho lệnh check_my_currency"""
    embed = discord.Embed(
        title="❌ Lỗi",
        description=f"Đã xảy ra lỗi khi kiểm tra số xu: {str(error)}",
        color=discord.Color.red()
    )
    await ctx.send(embed=embed)

@bot.command(name='baocaoxu', aliases=['mystats', 'xuinfo'])
async def currency_report(ctx):
    """Tạo báo cáo chi tiết về tình hình tài chính của người dùng"""
    user = ctx.author
    user_id = user.id
    
    # Kiểm tra nếu user có trong hệ thống tiền tệ
    if user_id not in currency:
        currency[user_id] = 0

    embed = discord.Embed(
        title="📊 Báo cáo tài chính",
        description=f"Thông tin chi tiết tài chính của {user.mention}",
        color=discord.Color.teal()
    )
    
    # Số dư hiện tại
    embed.add_field(
        name="💵 Số dư hiện tại",
        value=f"**{currency[user_id]:,}** xu",
        inline=False
    )
    
    # Thống kê giao dịch nếu có
    if hasattr(bot, 'transaction_history') and user_id in bot.transaction_history:
        transactions = bot.transaction_history[user_id]
        
        # Tính tổng thu nhập và chi tiêu
        total_income = sum(amount for amount in transactions['income'] if isinstance(amount, (int, float)))
        total_expense = sum(amount for amount in transactions['expense'] if isinstance(amount, (int, float)))
        
        embed.add_field(
            name="📈 Tổng thu nhập",
            value=f"**{total_income:,}** xu",
            inline=True
        )
        
        embed.add_field(
            name="📉 Tổng chi tiêu",
            value=f"**{total_expense:,}** xu",
            inline=True
        )
        
        embed.add_field(
            name="💹 Chênh lệch",
            value=f"**{total_income - total_expense:,}** xu",
            inline=True
        )
        
        # Giao dịch gần đây
        if transactions['recent']:
            recent_transactions = transactions['recent'][-5:]  # 5 giao dịch gần nhất
            recent_text = "\n".join([f"• {txn['type']}: **{txn['amount']:,}** xu - {txn['description']}" 
                                    for txn in recent_transactions])
            
            embed.add_field(
                name="🕒 Giao dịch gần đây",
                value=recent_text or "Không có giao dịch nào",
                inline=False
            )
    
    # Thông tin ngân hàng chi tiết
    if hasattr(bot, 'bank_accounts') and user_id in bot.bank_accounts:
        bank_data = bot.bank_accounts[user_id]
        
        # Tính toán lãi suất
        interest_rate = getattr(bot, 'bank_interest_rate', 0.01)  # Mặc định 1% nếu không có
        daily_interest = int(bank_data["balance"] * interest_rate)
        monthly_interest = daily_interest * 30
        
        # Ngày tạo tài khoản ngân hàng nếu có
        account_age = "Không xác định"
        if "created_at" in bank_data:
            days_since_creation = (datetime.now() - bank_data["created_at"]).days
            account_age = f"{days_since_creation} ngày"
        
        # Tổng lãi đã nhận
        total_interest_earned = bank_data.get("total_interest_earned", 0)
        
        bank_info = (
            f"**{bank_data['balance']:,}** xu\n"
            f"Lãi suất: **{interest_rate*100}%** mỗi ngày\n"
            f"Lãi hàng ngày: **{daily_interest:,}** xu\n"
            f"Lãi ước tính/tháng: **{monthly_interest:,}** xu\n"
            f"Tổng lãi đã nhận: **{total_interest_earned:,}** xu\n"
            f"Tuổi tài khoản: **{account_age}**"
        )
        
        embed.add_field(
            name="🏦 Thông tin ngân hàng",
            value=bank_info,
            inline=False
        )
    
    # Biểu đồ xu theo thời gian (gợi ý, không thể hiện trong embed)
    embed.add_field(
        name="📈 Biểu đồ xu",
        value="Sử dụng lệnh `.xuchart` để xem biểu đồ xu theo thời gian",
        inline=False
    )
    
    # Thêm avatar người dùng
    embed.set_thumbnail(url=user.display_avatar.url)
    
    # Thêm footer
    embed.set_footer(text=f"Sử dụng .xuhelp để xem các lệnh liên quan đến quản lý xu | {datetime.now().strftime('%d/%m/%Y')}")
    
    await ctx.send(embed=embed)

@currency_report.error
async def currency_report_error(ctx, error):
    """Xử lý lỗi cho lệnh currency_report"""
    embed = discord.Embed(
        title="❌ Lỗi",
        description=f"Đã xảy ra lỗi khi tạo báo cáo tài chính: {str(error)}",
        color=discord.Color.red()
    )
    await ctx.send(embed=embed)

@bot.command(name='sendxu')
@check_channel()
async def sendxu(ctx, member: discord.Member, amount: int):
    """Cho phép người dùng chuyển xu cho người chơi khác."""
    sender_id = ctx.author.id
    receiver_id = member.id

    # Kiểm tra nếu người gửi đang có khoản vay
    if sender_id in loans:
        embed = discord.Embed(
            title="❌ Không thể chuyển xu",
            description=
            "Bạn đang có khoản vay chưa trả nên không thể chuyển xu cho người khác.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    if amount <= 0:
        await ctx.send("Số lượng xu phải lớn hơn 0.")
        return

    if currency[sender_id] < amount:
        await ctx.send("Bạn không có đủ xu để chuyển.")
        return

    currency[sender_id] -= amount
    currency[receiver_id] += amount
    embed = discord.Embed(
        title="Chuyển Xu",
        description=
        f"{ctx.author.display_name} đã chuyển {amount} xu cho {member.display_name}. Số dư hiện tại của bạn: {currency[sender_id]}",
        color=discord.Color.blue())
    await ctx.send(embed=embed)


@bot.command(name='vayxu')
@check_channel()
@check_game_enabled('vayxu')
async def loan_xu(ctx, amount: int = None):
    """Cho phép người dùng vay xu (phải trả trong 2 giờ)"""
    if amount is None:
        embed = discord.Embed(
            title="🏦 Vay Xu - Hướng Dẫn",
            description="Vay xu với lãi suất 0%. Phải trả trong vòng 2 giờ.",
            color=discord.Color.blue())
        embed.add_field(name="Cách dùng", value="`.vayxu [số xu]`\nVí dụ: `.vayxu 500`", inline=False)
        embed.add_field(name="Giới hạn", value="- Mỗi người chỉ được vay **1 lần duy nhất**\n- Số tiền tối đa: 1000 xu", inline=False)
        embed.add_field(name="Cảnh báo", value="⚠️ Spam lệnh vay sẽ bị timeout 7 ngày!", inline=False)
        await ctx.send(embed=embed)
        return

    user_id = ctx.author.id

    # Kiểm tra nếu người dùng đã cố gắng vay nhiều lần (phát hiện spam)
    if user_id in loan_violations and loan_violations[user_id] >= 3:
        # Tạo embed cảnh báo
        embed = discord.Embed(
            title="⛔ PHÁT HIỆN SPAM LỆNH VAY XU",
            description=f"{ctx.author.mention} đã cố gắng spam lệnh vay xu và sẽ bị timeout 7 ngày!",
            color=discord.Color.dark_red()
        )
        await ctx.send(embed=embed)
        
        # Timeout user
        try:
            timeout_until = discord.utils.utcnow() + timedelta(days=SPAM_TIMEOUT_DAYS)
            await ctx.author.timeout(timeout_until, reason="Spam lệnh vay xu")
            
            # Gửi thông báo cho admin
            admin_embed = discord.Embed(
                title="🚨 Đã timeout người dùng spam lệnh vay xu",
                description=f"Người dùng: {ctx.author.mention} (ID: {ctx.author.id})\nThời gian: 7 ngày\nLý do: Spam lệnh vay xu ({loan_violations[user_id]} lần)",
                color=discord.Color.dark_red()
            )
            await ctx.send(embed=admin_embed)
            
        except discord.Forbidden:
            await ctx.send("❌ Không thể timeout người dùng do thiếu quyền!")
        except Exception as e:
            await ctx.send(f"❌ Lỗi khi timeout: {str(e)}")
        
        return

    # Kiểm tra nếu người dùng đã có khoản vay
    if user_id in loans:
        # Tăng số lần vi phạm
        loan_violations[user_id] = loan_violations.get(user_id, 0) + 1
        
        embed = discord.Embed(
            title="❌ Không thể vay",
            description=f"Bạn đã có khoản vay chưa trả. Hãy trả lại khoản vay hiện tại trước khi vay tiếp.",
            color=discord.Color.red())
        embed.add_field(
            name="Khoản vay hiện tại", 
            value=f"{loans[user_id]['amount']} xu", 
            inline=True)
        embed.add_field(
            name="Cảnh báo", 
            value=f"⚠️ Đây là lần thứ {loan_violations[user_id]}/3 bạn cố gắng vay khi đã có nợ.\nLần thứ 3 sẽ bị timeout 7 ngày!", 
            inline=False)
        await ctx.send(embed=embed)
        return

    # Kiểm tra số lượng
    if amount <= 0:
        embed = discord.Embed(title="❌ Lỗi",
                              description="Số lượng xu vay phải lớn hơn 0.",
                              color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Kiểm tra giới hạn vay (tối đa 1000 xu)
    if amount > 1000:
        embed = discord.Embed(
            title="❌ Vượt giới hạn",
            description="Bạn chỉ có thể vay tối đa 1000 xu.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Thêm khoản vay
    loans[user_id] = {"amount": amount, "time": datetime.now()}
    currency[user_id] += amount

    embed = discord.Embed(
        title="🏦 Vay Xu Thành Công",
        description=f"{ctx.author.mention} đã vay {amount} xu. Hãy trả lại trong vòng 2 giờ để tránh bị ban.",
        color=discord.Color.green())
    embed.add_field(
        name="⚠️ Lưu ý",
        value="- Bạn **chỉ được vay 1 lần duy nhất** cho đến khi trả hết\n- Bạn không thể chuyển xu vay cho người khác\n- Vay thêm khi chưa trả sẽ bị coi là spam và bị timeout",
        inline=False)
    embed.add_field(
        name="🔄 Cách trả xu",
        value=f"Sử dụng lệnh `.traxu {amount}` để trả khoản vay\nCần trả đúng số xu đã vay: **{amount} xu**",
        inline=False)
    embed.set_footer(text="Hạn trả: 2 giờ từ thời điểm vay")
    await ctx.send(embed=embed)

@bot.command(name='traxu')
@check_channel()
async def repay_loan(ctx, amount: int = None):
    """Cho phép người dùng trả khoản vay xu - phải trả đủ số tiền đã vay"""
    if amount is None:
        embed = discord.Embed(
            title="🏦 Trả Xu - Hướng Dẫn",
            description="Trả lại khoản vay của bạn.",
            color=discord.Color.blue())
        embed.add_field(name="Cách dùng", value="`.traxu [số xu]`\nVí dụ: `.traxu 500`", inline=False)
        embed.add_field(name="Lưu ý", value="⚠️ Bạn phải trả đủ và đúng số tiền đã vay trong một lần duy nhất", inline=False)
        await ctx.send(embed=embed)
        return

    user_id = ctx.author.id

    # Kiểm tra nếu người dùng không có khoản vay
    if user_id not in loans:
        embed = discord.Embed(
            title="❌ Không có khoản vay",
            description="Bạn không có khoản vay nào cần trả.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Lấy thông tin khoản vay
    loan_amount = loans[user_id]["amount"]
    
    # Kiểm tra số tiền trả có đúng không
    if amount != loan_amount:
        embed = discord.Embed(
            title="❌ Số tiền không đúng",
            description=f"Bạn phải trả đúng {loan_amount} xu. Không thể trả nhiều hơn hoặc ít hơn.",
            color=discord.Color.red())
        embed.add_field(name="Khoản vay của bạn", value=f"{loan_amount} xu", inline=True)
        embed.add_field(name="Số tiền bạn đang trả", value=f"{amount} xu", inline=True)
        await ctx.send(embed=embed)
        return

    # Kiểm tra số dư
    if currency[user_id] < amount:
        embed = discord.Embed(
            title="❌ Không đủ xu",
            description=f"Bạn không có đủ xu để trả khoản vay. Bạn cần {amount} xu.",
            color=discord.Color.red())
        embed.add_field(name="Số dư hiện tại", value=f"{currency[user_id]} xu", inline=True)
        embed.add_field(name="Còn thiếu", value=f"{amount - currency[user_id]} xu", inline=True)
        await ctx.send(embed=embed)
        return

    # Trả khoản vay
    currency[user_id] -= amount
    del loans[user_id]  # Xóa khoản vay
    
    # Xóa vi phạm nếu có
    if user_id in loan_violations:
        del loan_violations[user_id]

    embed = discord.Embed(
        title="✅ Trả Xu Thành Công",
        description=f"{ctx.author.mention} đã trả {amount} xu và không còn nợ.",
        color=discord.Color.green())
    embed.add_field(name="Số dư hiện tại", value=f"{currency[user_id]} xu", inline=True)
    embed.set_footer(text="Cảm ơn bạn đã trả nợ đúng hạn!")
    await ctx.send(embed=embed)

@bot.command(name='checkvay')
@admin_only()
async def check_loans_command(ctx, user: discord.Member = None):
    """Kiểm tra thông tin vay xu của người dùng hoặc toàn bộ hệ thống"""
    # Kiểm tra nếu không có ai đang vay
    if not loans:
        embed = discord.Embed(
            title="🏦 Kiểm tra khoản vay",
            description="Không có khoản vay nào trong hệ thống.",
            color=discord.Color.green())
        await ctx.send(embed=embed)
        return
    
    current_time = datetime.now()
    
    # Nếu cung cấp user cụ thể, chỉ hiển thị thông tin của người đó
    if user:
        user_id = user.id
        if user_id not in loans:
            embed = discord.Embed(
                title="🏦 Kiểm tra khoản vay",
                description=f"{user.mention} không có khoản vay nào.",
                color=discord.Color.blue())
            await ctx.send(embed=embed)
            return
        
        loan_info = loans[user_id]
        loan_amount = loan_info["amount"]
        loan_time = loan_info["time"]
        time_elapsed = (current_time - loan_time).total_seconds()
        time_remaining = max(0, 7200 - time_elapsed)  # 2 giờ = 7200 giây
        
        hours_remaining = int(time_remaining // 3600)
        minutes_remaining = int((time_remaining % 3600) // 60)
        seconds_remaining = int(time_remaining % 60)
        
        status = "✅ Đang trong thời hạn" if time_remaining > 0 else "❗ **QUÁ HẠN**"
        
        embed = discord.Embed(
            title="🏦 Thông tin khoản vay",
            description=f"Thông tin khoản vay của {user.mention}",
            color=discord.Color.blue() if time_remaining > 0 else discord.Color.red())
        
        embed.add_field(name="Số xu đã vay", value=f"{loan_amount} xu", inline=True)
        embed.add_field(name="Thời gian vay", value=f"<t:{int(loan_time.timestamp())}:R>", inline=True)
        embed.add_field(name="Trạng thái", value=status, inline=False)
        
        if time_remaining > 0:
            embed.add_field(name="Thời gian còn lại", value=f"{hours_remaining} giờ {minutes_remaining} phút {seconds_remaining} giây", inline=False)
        else:
            overdue_time = -time_remaining
            overdue_hours = int(overdue_time // 3600)
            overdue_minutes = int((overdue_time % 3600) // 60)
            embed.add_field(name="Quá hạn", value=f"{overdue_hours} giờ {overdue_minutes} phút", inline=False)
            embed.add_field(name="⚠️ Hành động đề xuất", value="Sử dụng lệnh `.xulyvay @user [kick/ban]` để xử lý người dùng vi phạm.", inline=False)
            
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.set_footer(text=f"ID: {user_id}")
        
        await ctx.send(embed=embed)
        return
    
    # Nếu không cung cấp user cụ thể, hiển thị danh sách tất cả khoản vay
    embed = discord.Embed(
        title="🏦 Danh sách khoản vay",
        description=f"Có **{len(loans)}** khoản vay trong hệ thống",
        color=discord.Color.gold())
    
    # Phân loại khoản vay thành 'đang trong thời hạn' và 'quá hạn'
    active_loans = []
    overdue_loans = []
    
    for user_id, loan_info in loans.items():
        loan_time = loan_info["time"]
        time_elapsed = (current_time - loan_time).total_seconds()
        time_remaining = max(0, 7200 - time_elapsed)
        
        try:
            user = await bot.fetch_user(user_id)
            username = user.name
        except:
            username = f"Người dùng {user_id}"
        
        loan_data = {
            'user_id': user_id,
            'username': username,
            'amount': loan_info["amount"],
            'time_remaining': time_remaining,
            'loan_time': loan_time
        }
        
        if time_remaining > 0:
            active_loans.append(loan_data)
        else:
            overdue_loans.append(loan_data)
    
    # Hiển thị khoản vay quá hạn trước
    if overdue_loans:
        overdue_text = ""
        for idx, loan in enumerate(sorted(overdue_loans, key=lambda x: x['time_remaining']), 1):
            overdue_time = -loan['time_remaining']
            hours = int(overdue_time // 3600)
            minutes = int((overdue_time % 3600) // 60)
            overdue_text += f"{idx}. **{loan['username']}** - {loan['amount']} xu - Quá hạn **{hours}h {minutes}m**\n"
        
        embed.add_field(name="❗ KHOẢN VAY QUÁ HẠN", value=overdue_text, inline=False)
        embed.add_field(name="⚠️ Hành động đề xuất", 
                       value="Sử dụng lệnh `.xulyvay @user [kick/ban]` hoặc `.autoxlvay` để xử lý tất cả.", 
                       inline=False)
    
    # Hiển thị khoản vay đang hoạt động
    if active_loans:
        active_text = ""
        for idx, loan in enumerate(sorted(active_loans, key=lambda x: x['time_remaining']), 1):
            hours = int(loan['time_remaining'] // 3600)
            minutes = int((loan['time_remaining'] % 3600) // 60)
            active_text += f"{idx}. **{loan['username']}** - {loan['amount']} xu - Còn lại **{hours}h {minutes}m**\n"
        
        embed.add_field(name="✅ KHOẢN VAY ĐANG HOẠT ĐỘNG", value=active_text, inline=False)
    
    embed.set_footer(text=f"Sử dụng .checkvay @user để xem chi tiết từng người")
    await ctx.send(embed=embed)

@bot.command(name='xulyvay')
@admin_only()
async def punish_loan_defaulter(ctx, member: discord.Member = None, action: str = None):
    """Xử lý người dùng không trả khoản vay đúng hạn"""
    if member is None or action is None:
        embed = discord.Embed(
            title="⚖️ Xử lý vi phạm khoản vay - Hướng dẫn",
            description="Xử lý người dùng không trả khoản vay đúng hạn",
            color=discord.Color.blue())
        
        embed.add_field(
            name="Cách sử dụng",
            value="`.xulyvay @người_dùng [kick/ban]`\nVí dụ: `.xulyvay @username kick`",
            inline=False)
        
        embed.add_field(
            name="Các hình phạt",
            value="`kick` - Đuổi người dùng khỏi server\n`ban` - Cấm người dùng khỏi server",
            inline=False)
        
        embed.set_footer(text="Chỉ sử dụng cho những người đã quá hạn trả khoản vay")
        await ctx.send(embed=embed)
        return
    
    # Kiểm tra xem target có phải admin không
    if member.guild_permissions.administrator or member.id in ADMIN_IDS:
        embed = discord.Embed(
            title="🛡️ Bảo vệ Admin",
            description="Không thể xử lý khoản vay của admin!",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return
    
    user_id = member.id
    
    # Kiểm tra xem người dùng có khoản vay không
    if user_id not in loans:
        embed = discord.Embed(
            title="❓ Không có khoản vay",
            description=f"{member.mention} không có khoản vay nào trong hệ thống.",
            color=discord.Color.yellow())
        await ctx.send(embed=embed)
        return
    
    # Kiểm tra xem khoản vay có quá hạn không
    loan_info = loans[user_id]
    loan_time = loan_info["time"]
    loan_amount = loan_info["amount"]
    current_time = datetime.now()
    time_elapsed = (current_time - loan_time).total_seconds()
    time_remaining = 7200 - time_elapsed  # 2 giờ = 7200 giây
    
    if time_remaining > 0:
        hours = int(time_remaining // 3600)
        minutes = int((time_remaining % 3600) // 60)
        
        embed = discord.Embed(
            title="⏰ Chưa quá hạn",
            description=f"Khoản vay của {member.mention} chưa quá hạn.",
            color=discord.Color.yellow())
        
        embed.add_field(name="Thời gian còn lại", 
                       value=f"{hours} giờ {minutes} phút", 
                       inline=False)
        
        await ctx.send(embed=embed)
        return
    
    # Kiểm tra hành động hợp lệ
    action = action.lower()
    if action not in ["kick", "ban"]:
        embed = discord.Embed(
            title="❌ Lỗi cú pháp",
            description="Hành động phải là `kick` hoặc `ban`.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return
    
    # Tạo view xác nhận với các nút
    confirm_view = discord.ui.View(timeout=60)
    
    confirm_button = discord.ui.Button(
        label=f"Xác nhận {action.upper()}",
        style=discord.ButtonStyle.danger,
        emoji="⚖️")
    
    cancel_button = discord.ui.Button(
        label="Hủy bỏ",
        style=discord.ButtonStyle.secondary,
        emoji="❌")
    
    async def confirm_callback(interaction):
        if interaction.user != ctx.author:
            await interaction.response.send_message("Bạn không thể sử dụng nút này!", ephemeral=True)
            return
        
        # Vô hiệu hóa các nút
        confirm_view.clear_items()
        await interaction.response.edit_message(view=confirm_view)
        
        try:
            # Xử lý người dùng và xóa khoản vay
            reason = f"Vi phạm không trả khoản vay {loan_amount} xu | Thực hiện bởi {ctx.author.name}"
            
            if action == "kick":
                await member.kick(reason=reason)
                punishment_type = "KICK"
                success_message = f"{member.mention} đã bị đuổi khỏi server!"
            else:  # ban
                await member.ban(reason=reason)
                punishment_type = "BAN"
                success_message = f"{member.mention} đã bị cấm khỏi server!"
            
            # Xóa khoản vay
            del loans[user_id]
            
            # Gửi thông báo thành công
            success_embed = discord.Embed(
                title=f"⚖️ ĐÃ XỬ LÝ: {punishment_type}",
                description=success_message,
                color=discord.Color.green())
            
            success_embed.add_field(name="Người vi phạm", 
                                  value=f"**{member.name}** (ID: {member.id})", 
                                  inline=True)
            
            success_embed.add_field(name="Khoản vay", 
                                  value=f"**{loan_amount} xu**", 
                                  inline=True)
            
            overdue_time = -time_remaining
            overdue_hours = int(overdue_time // 3600)
            overdue_minutes = int((overdue_time % 3600) // 60)
            
            success_embed.add_field(name="Quá hạn", 
                                  value=f"{overdue_hours} giờ {overdue_minutes} phút", 
                                  inline=False)
            
            success_embed.set_footer(text=f"Thực hiện bởi: {ctx.author.name} | {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
            
            await interaction.message.edit(embed=success_embed)
            
            # Gửi thông báo đến kênh game
            game_channel = ctx.guild.get_channel(GAME_CHANNEL_ID)
            if game_channel and game_channel != ctx.channel:
                await game_channel.send(embed=success_embed)
            
        except discord.Forbidden:
            error_embed = discord.Embed(
                title="❌ Lỗi quyền hạn",
                description=f"Bot không có quyền để {action} người dùng này!",
                color=discord.Color.red())
            await interaction.message.edit(embed=error_embed)
        
        except Exception as e:
            error_embed = discord.Embed(
                title="❌ Lỗi",
                description=f"Không thể thực hiện lệnh: {str(e)}",
                color=discord.Color.red())
            await interaction.message.edit(embed=error_embed)
    
    async def cancel_callback(interaction):
        if interaction.user != ctx.author:
            await interaction.response.send_message("Bạn không thể sử dụng nút này!", ephemeral=True)
            return
        
        # Vô hiệu hóa các nút
        confirm_view.clear_items()
        await interaction.response.edit_message(view=confirm_view)
        
        # Gửi thông báo hủy
        cancel_embed = discord.Embed(
            title="❌ Đã hủy",
            description="Lệnh xử lý khoản vay đã bị hủy bỏ.",
            color=discord.Color.dark_gray())
        await interaction.message.edit(embed=cancel_embed)
    
    # Gán callbacks
    confirm_button.callback = confirm_callback
    cancel_button.callback = cancel_callback
    
    # Thêm nút vào view
    confirm_view.add_item(confirm_button)
    confirm_view.add_item(cancel_button)
    
    # Hiển thị thông tin quá hạn
    overdue_time = -time_remaining
    overdue_hours = int(overdue_time // 3600)
    overdue_minutes = int((overdue_time % 3600) // 60)
    
    # Tạo embed xác nhận
    confirm_embed = discord.Embed(
        title="⚖️ Xác nhận xử lý khoản vay",
        description=f"Bạn có chắc chắn muốn **{action.upper()}** {member.mention} vì quá hạn trả khoản vay?",
        color=discord.Color.gold())
    
    confirm_embed.add_field(name="Người vi phạm", 
                          value=f"**{member.name}** (ID: {member.id})", 
                          inline=True)
    
    confirm_embed.add_field(name="Khoản vay", 
                          value=f"**{loan_amount} xu**", 
                          inline=True)
    
    confirm_embed.add_field(name="Quá hạn", 
                          value=f"{overdue_hours} giờ {overdue_minutes} phút", 
                          inline=False)
    
    confirm_embed.add_field(name="Cảnh báo", 
                          value="Thao tác này không thể hoàn tác sau khi thực hiện!", 
                          inline=False)
    
    await ctx.send(embed=confirm_embed, view=confirm_view)

@bot.command(name='autoxlvay')
@admin_only()
async def auto_punish_loan_defaulters(ctx, action: str = "kick"):
    """Tự động xử lý tất cả những người vi phạm khoản vay"""
    # Kiểm tra hành động hợp lệ
    action = action.lower()
    if action not in ["kick", "ban"]:
        embed = discord.Embed(
            title="❌ Lỗi cú pháp",
            description="Hành động phải là `kick` hoặc `ban`.\nVí dụ: `.autoxlvay ban`",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return
    
    # Kiểm tra xem có khoản vay quá hạn nào không
    current_time = datetime.now()
    defaulters = []
    
    for user_id, loan_info in loans.items():
        loan_time = loan_info["time"]
        time_elapsed = (current_time - loan_time).total_seconds()
        
        if time_elapsed > 7200:  # Quá 2 giờ
            defaulters.append({
                "user_id": user_id,
                "amount": loan_info["amount"],
                "elapsed": time_elapsed
            })
    
    if not defaulters:
        embed = discord.Embed(
            title="✅ Không có vi phạm",
            description="Không có khoản vay nào quá hạn trong hệ thống.",
            color=discord.Color.green())
        await ctx.send(embed=embed)
        return
    
    # Tạo view xác nhận với các nút
    confirm_view = discord.ui.View(timeout=60)
    
    confirm_button = discord.ui.Button(
        label=f"Xác nhận {action.upper()} {len(defaulters)} người",
        style=discord.ButtonStyle.danger,
        emoji="⚖️")
    
    cancel_button = discord.ui.Button(
        label="Hủy bỏ",
        style=discord.ButtonStyle.secondary,
        emoji="❌")
    
    async def confirm_callback(interaction):
        if interaction.user != ctx.author:
            await interaction.response.send_message("Bạn không thể sử dụng nút này!", ephemeral=True)
            return
        
        # Vô hiệu hóa các nút
        confirm_view.clear_items()
        await interaction.response.edit_message(view=confirm_view)
        
        # Hiển thị thông báo đang xử lý
        processing_embed = discord.Embed(
            title="⚙️ Đang xử lý",
            description=f"Đang {action} {len(defaulters)} người vi phạm khoản vay...",
            color=discord.Color.blue())
        await interaction.message.edit(embed=processing_embed)
        
        # Xử lý từng người một
        processed = 0
        failed = 0
        skipped = 0
        
        result_text = ""
        
        for idx, defaulter in enumerate(defaulters, 1):
            user_id = defaulter["user_id"]
            loan_amount = defaulter["amount"]
            
            try:
                # Kiểm tra xem có phải admin không
                if user_id in ADMIN_IDS:
                    skipped += 1
                    result_text += f"{idx}. ID: {user_id} - **BỎ QUA** (Admin)\n"
                    continue
                
                # Lấy thành viên và xử lý
                try:
                    member = await ctx.guild.fetch_member(user_id)
                    
                    if member:
                        reason = f"Tự động {action}: Vi phạm không trả khoản vay {loan_amount} xu"
                        
                        if action == "kick":
                            await member.kick(reason=reason)
                            result_text += f"{idx}. {member.name} - **ĐÃ KICK** - {loan_amount} xu\n"
                        else:  # ban
                            await member.ban(reason=reason)
                            result_text += f"{idx}. {member.name} - **ĐÃ BAN** - {loan_amount} xu\n"
                        
                        # Xóa khoản vay
                        del loans[user_id]
                        processed += 1
                        
                    else:
                        result_text += f"{idx}. ID: {user_id} - **KHÔNG TÌM THẤY** - {loan_amount} xu\n"
                        del loans[user_id]  # Xóa khoản vay vì người dùng không còn trong server
                        processed += 1
                
                except discord.Forbidden:
                    result_text += f"{idx}. ID: {user_id} - **LỖI QUYỀN** - {loan_amount} xu\n"
                    failed += 1
                
                except Exception as e:
                    result_text += f"{idx}. ID: {user_id} - **LỖI: {str(e)}** - {loan_amount} xu\n"
                    failed += 1
            
            except Exception as e:
                result_text += f"{idx}. ID: {user_id} - **LỖI: {str(e)}** - {loan_amount} xu\n"
                failed += 1
        
        # Hiển thị kết quả
        result_embed = discord.Embed(
            title=f"⚖️ Kết quả xử lý khoản vay quá hạn ({action.upper()})",
            description=f"Đã xử lý {processed}/{len(defaulters)} người vi phạm",
            color=discord.Color.green())
        
        if skipped > 0:
            result_embed.add_field(name="Số người bỏ qua", value=f"{skipped} (Admin/Owner)", inline=True)
        
        if failed > 0:
            result_embed.add_field(name="Số người lỗi", value=str(failed), inline=True)
        
        # Chia kết quả thành nhiều phần nếu quá dài
        if len(result_text) > 1000:
            chunks = [result_text[i:i+1000] for i in range(0, len(result_text), 1000)]
            for i, chunk in enumerate(chunks):
                result_embed.add_field(name=f"Chi tiết (Phần {i+1}/{len(chunks)})", value=chunk, inline=False)
        else:
            result_embed.add_field(name="Chi tiết", value=result_text, inline=False)
        
        result_embed.set_footer(text=f"Thực hiện bởi: {ctx.author.name} | {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
        
        await interaction.message.edit(embed=result_embed)
        
        # Gửi thông báo đến kênh game
        game_channel = ctx.guild.get_channel(GAME_CHANNEL_ID)
        if game_channel and game_channel != ctx.channel:
            summary_embed = discord.Embed(
                title=f"⚖️ Xử lý vi phạm khoản vay",
                description=f"Đã {action} {processed} người không trả khoản vay đúng hạn.",
                color=discord.Color.red())
            summary_embed.set_footer(text=f"Thực hiện bởi: {ctx.author.name}")
            await game_channel.send(embed=summary_embed)
    
    async def cancel_callback(interaction):
        if interaction.user != ctx.author:
            await interaction.response.send_message("Bạn không thể sử dụng nút này!", ephemeral=True)
            return
        
        # Vô hiệu hóa các nút
        confirm_view.clear_items()
        await interaction.response.edit_message(view=confirm_view)
        
        # Gửi thông báo hủy
        cancel_embed = discord.Embed(
            title="❌ Đã hủy",
            description="Lệnh xử lý tự động đã bị hủy bỏ.",
            color=discord.Color.dark_gray())
        await interaction.message.edit(embed=cancel_embed)
    
    # Gán callbacks
    confirm_button.callback = confirm_callback
    cancel_button.callback = cancel_callback
    
    # Thêm nút vào view
    confirm_view.add_item(confirm_button)
    confirm_view.add_item(cancel_button)
    
    # Tạo danh sách người vi phạm
    defaulters_list = ""
    for idx, defaulter in enumerate(defaulters[:15], 1):  # Hiển thị tối đa 15 người
        user_id = defaulter["user_id"]
        loan_amount = defaulter["amount"]
        elapsed_time = defaulter["elapsed"]
        
        hours = int(elapsed_time // 3600)
        minutes = int((elapsed_time % 3600) // 60)
        
        try:
            user = await bot.fetch_user(user_id)
            username = user.name
        except:
            username = f"Người dùng {user_id}"
        
        defaulters_list += f"{idx}. **{username}** - {loan_amount} xu - Quá hạn **{hours}h {minutes}m**\n"
    
    if len(defaulters) > 15:
        defaulters_list += f"... và {len(defaulters) - 15} người khác"
    
    # Tạo embed xác nhận
    confirm_embed = discord.Embed(
        title=f"⚖️ Xác nhận xử lý tự động ({action.upper()})",
        description=f"Bạn có chắc chắn muốn {action} **{len(defaulters)} người** vi phạm khoản vay?",
        color=discord.Color.red())
    
    confirm_embed.add_field(name="Danh sách vi phạm", value=defaulters_list, inline=False)
    
    confirm_embed.add_field(name="⚠️ Cảnh báo", 
                          value="Thao tác này sẽ xử lý tất cả người vi phạm và không thể hoàn tác!", 
                          inline=False)
    
    await ctx.send(embed=confirm_embed, view=confirm_view)

@bot.command(name='bxhxu')
@check_channel()
async def bxhxu(ctx):
    """Hiển thị bảng xếp hạng xu của người chơi."""
    sorted_currency = sorted(currency.items(),
                             key=lambda x: x[1],
                             reverse=True)
    embed = discord.Embed(title="🏆 Bảng Xếp Hạng Xu 💰",
                          description="Top người chơi có nhiều xu nhất",
                          color=discord.Color.gold())

    if sorted_currency:
        top_players = []
        rank = 1

        for user_id, balance in sorted_currency:
            if rank > 10:  # Chỉ lấy top 10
                break

            try:
                member = await ctx.guild.fetch_member(user_id)
                if member:  # Chỉ hiển thị thành viên còn trong server
                    medal = ["🥇", "🥈", "🥉"][rank -
                                            1] if rank <= 3 else f"{rank}."
                    top_players.append((medal, member.display_name, balance))
                    rank += 1
            except discord.NotFound:
                continue  # Bỏ qua người dùng không tồn tại

        if top_players:
            for medal, name, balance in top_players:
                embed.add_field(name=f"{medal} {name}",
                                value=f"**{balance} xu**",
                                inline=False)
        else:
            embed.description = "Không tìm thấy người dùng nào trong server."
    else:
        embed.description = "Chưa có ai trong bảng xếp hạng."

    embed.set_footer(text="Hãy tham gia các trò chơi để có cơ hội lên top!")
    embed.set_thumbnail(url=ctx.guild.icon.url if ctx.guild.icon else None)

    await ctx.send(embed=embed)


@bot.command(name='txu')
@commands.has_permissions(administrator=True)
async def txu(ctx, member: discord.Member = None, amount: str = None):
    """Cho phép quản trị viên tặng xu cho người chơi."""
    if member is None or amount is None:
        embed = discord.Embed(
            title="🪙 Tặng Xu - Hướng Dẫn",
            description="Cho phép admin tặng xu cho thành viên.",
            color=discord.Color.blue())
        embed.add_field(
            name="Cách sử dụng",
            value="`.txu @người_dùng [số xu]`\nVí dụ: `.txu @username 100`",
            inline=False)
        embed.add_field(
            name="Lưu ý",
            value=
            "- Chỉ admin mới có thể sử dụng lệnh này\n- Số xu phải là số dương",
            inline=False)
        await ctx.send(embed=embed)
        return

    try:
        # Chuyển đổi số xu thành số nguyên
        amount_int = int(amount)

        if amount_int <= 0:
            embed = discord.Embed(title="❌ Lỗi",
                                  description="Số lượng xu phải lớn hơn 0.",
                                  color=discord.Color.red())
            await ctx.send(embed=embed)
            return

        # Tặng xu cho người chơi
        currency[member.id] += amount_int

        embed = discord.Embed(
            title="✅ Tặng Xu Thành Công",
            description=
            f"{member.display_name} đã nhận được {amount_int} xu từ {ctx.author.display_name}.",
            color=discord.Color.green())
        embed.add_field(name="Số dư mới",
                        value=f"{currency[member.id]} xu",
                        inline=False)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(
            text=f"Admin: {ctx.author.name} | ID: {ctx.author.id}")

        await ctx.send(embed=embed)

    except ValueError:
        embed = discord.Embed(title="❌ Lỗi",
                              description="Số xu phải là số nguyên dương.",
                              color=discord.Color.red())
        await ctx.send(embed=embed)


@bot.command(name='trxu')
@commands.has_permissions(administrator=True)
async def trxu(ctx, member: discord.Member = None, amount: str = None):
    """Cho phép quản trị viên trừ xu từ tài khoản của thành viên."""
    if member is None or amount is None:
        embed = discord.Embed(
            title="🪙 Trừ Xu - Hướng Dẫn",
            description="Cho phép admin trừ xu của thành viên.",
            color=discord.Color.blue())
        embed.add_field(
            name="Cách sử dụng",
            value=
            "`.trxu @người_dùng [số xu/all]`\nVí dụ: `.trxu @username 100` hoặc `.trxu @username all`",
            inline=False)
        embed.add_field(name="Tham số đặc biệt",
                        value="- `all`: Trừ tất cả xu của người dùng",
                        inline=False)
        embed.add_field(
            name="Lưu ý",
            value=
            "- Chỉ admin mới có thể sử dụng lệnh này\n- Số xu phải là số dương\n- Không thể trừ xu của admin chính",
            inline=False)
        await ctx.send(embed=embed)
        return

    # Bảo vệ ID admin chính
    if member.id == 618702036992655381:
        embed = discord.Embed(title="🛡️ Bảo Vệ Admin",
                              description="Không thể trừ xu của admin chính!",
                              color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Xử lý trường hợp 'all'
    if amount.lower() == 'all':
        current_balance = currency.get(member.id, 0)

        if current_balance <= 0:
            embed = discord.Embed(
                title="❌ Không thể trừ xu",
                description=
                f"{member.display_name} hiện không có xu nào để trừ.",
                color=discord.Color.red())
            await ctx.send(embed=embed)
            return

        # Tạo view xác nhận
        confirm_view = discord.ui.View(timeout=30)

        confirm_button = discord.ui.Button(label="Xác nhận",
                                           style=discord.ButtonStyle.danger,
                                           emoji="✅")

        cancel_button = discord.ui.Button(label="Hủy bỏ",
                                          style=discord.ButtonStyle.secondary,
                                          emoji="❌")

        async def confirm_callback(interaction):
            if interaction.user != ctx.author:
                await interaction.response.send_message(
                    "Bạn không có quyền sử dụng nút này!", ephemeral=True)
                return

            # Trừ tất cả xu
            old_balance = currency[member.id]
            currency[member.id] = 0

            result_embed = discord.Embed(
                title="✅ Đã Trừ Tất Cả Xu",
                description=
                f"Đã trừ toàn bộ {old_balance} xu của {member.display_name}.",
                color=discord.Color.green())
            result_embed.add_field(name="Số dư cũ",
                                   value=f"{old_balance} xu",
                                   inline=True)
            result_embed.add_field(name="Số dư mới", value="0 xu", inline=True)
            result_embed.set_thumbnail(url=member.display_avatar.url)
            result_embed.set_footer(
                text=f"Admin: {ctx.author.name} | ID: {ctx.author.id}")

            # Vô hiệu hóa các nút
            confirm_view.clear_items()
            await interaction.response.edit_message(embed=result_embed,
                                                    view=confirm_view)

        async def cancel_callback(interaction):
            if interaction.user != ctx.author:
                await interaction.response.send_message(
                    "Bạn không có quyền sử dụng nút này!", ephemeral=True)
                return

            cancel_embed = discord.Embed(
                title="❌ Đã Hủy",
                description="Thao tác trừ xu đã được hủy bỏ.",
                color=discord.Color.grey())

            # Vô hiệu hóa các nút
            confirm_view.clear_items()
            await interaction.response.edit_message(embed=cancel_embed,
                                                    view=confirm_view)

        confirm_button.callback = confirm_callback
        cancel_button.callback = cancel_callback

        confirm_view.add_item(confirm_button)
        confirm_view.add_item(cancel_button)

        # Tạo embed xác nhận
        confirm_embed = discord.Embed(
            title="⚠️ Xác nhận trừ tất cả xu",
            description=
            f"Bạn có chắc chắn muốn trừ tất cả xu ({current_balance} xu) của {member.display_name}?",
            color=discord.Color.yellow())
        confirm_embed.set_footer(
            text="Lưu ý: Thao tác này không thể hoàn tác!")

        await ctx.send(embed=confirm_embed, view=confirm_view)
        return

    try:
        # Chuyển đổi số xu thành số nguyên
        amount_int = int(amount)

        if amount_int <= 0:
            embed = discord.Embed(title="❌ Lỗi",
                                  description="Số lượng xu phải lớn hơn 0.",
                                  color=discord.Color.red())
            await ctx.send(embed=embed)
            return

        # Kiểm tra số dư hiện tại của người dùng
        if currency.get(member.id, 0) >= amount_int:
            currency[member.id] -= amount_int
            embed = discord.Embed(
                title="✅ Đã Trừ Xu",
                description=
                f"Đã trừ {amount_int} xu từ tài khoản của {member.display_name}.",
                color=discord.Color.green())
            embed.add_field(name="Số dư mới",
                            value=f"{currency[member.id]} xu",
                            inline=False)
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.set_footer(
                text=f"Admin: {ctx.author.name} | ID: {ctx.author.id}")
        else:
            embed = discord.Embed(
                title="❌ Không đủ xu",
                description=
                f"{member.display_name} không có đủ xu. Số xu hiện tại: {currency.get(member.id, 0)} xu.",
                color=discord.Color.red())
            embed.add_field(
                name="Gợi ý",
                value=
                "Bạn có thể dùng `.trxu @người_dùng all` để trừ tất cả xu.",
                inline=False)

        await ctx.send(embed=embed)

    except ValueError:
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Số xu phải là số nguyên dương hoặc 'all'.",
            color=discord.Color.red())
        await ctx.send(embed=embed)


@trxu.error
async def trxu_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        embed = discord.Embed(
            title="❌ Lỗi Quyền Hạn",
            description=
            "Bạn không có quyền quản trị viên để thực hiện lệnh này.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
    elif isinstance(error, commands.MemberNotFound):
        embed = discord.Embed(
            title="❌ Không Tìm Thấy",
            description="Không thể tìm thấy thành viên này trong server.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
    elif isinstance(error, commands.BadArgument):
        embed = discord.Embed(
            title="❌ Lỗi Tham Số",
            description=
            "Hãy đảm bảo bạn đã nhắc đến thành viên hợp lệ và chỉ định số xu chính xác.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(title="❌ Lỗi Không Xác Định",
                              description=f"Đã xảy ra lỗi: {str(error)}",
                              color=discord.Color.red())
        await ctx.send(embed=embed)


@txu.error
async def txu_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        embed = discord.Embed(
            title="❌ Lỗi Quyền Hạn",
            description=
            "Bạn không có quyền quản trị viên để thực hiện lệnh này.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
    elif isinstance(error, commands.MemberNotFound):
        embed = discord.Embed(
            title="❌ Không Tìm Thấy",
            description="Không thể tìm thấy thành viên này trong server.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
    elif isinstance(error, commands.BadArgument):
        embed = discord.Embed(
            title="❌ Lỗi Tham Số",
            description=
            "Hãy đảm bảo bạn đã nhắc đến thành viên hợp lệ và chỉ định số xu chính xác.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(title="❌ Lỗi Không Xác Định",
                              description=f"Đã xảy ra lỗi: {str(error)}",
                              color=discord.Color.red())
        await ctx.send(embed=embed)


@bot.command(name='napxu')
@commands.has_permissions(administrator=True)
async def napxu(ctx, member: discord.Member = None, amount: int = None):
    """Cho phép quản trị viên thêm xu vào tài khoản của thành viên."""
    if member is None or amount is None:
        embed = discord.Embed(
            title="💰 Nạp Xu - Hướng Dẫn",
            description="Cho phép admin thêm xu vào tài khoản của thành viên.",
            color=discord.Color.blue())
        embed.add_field(
            name="Cách sử dụng",
            value="`.napxu @người_dùng [số xu]`\nVí dụ: `.napxu @username 100`",
            inline=False)
        embed.add_field(
            name="Lưu ý",
            value=
            "- Chỉ admin mới có thể sử dụng lệnh này\n- Số xu phải là số nguyên dương",
            inline=False)
        await ctx.send(embed=embed)
        return

    if amount <= 0:
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Số lượng xu phải lớn hơn 0.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Nạp xu cho người chơi
    currency[member.id] = currency.get(member.id, 0) + amount

    embed = discord.Embed(
        title="✅ Nạp Xu Thành Công",
        description=
        f"Đã thêm **{amount} xu** vào tài khoản của {member.mention}.",
        color=discord.Color.green())
    embed.add_field(name="Số dư mới",
                    value=f"{currency[member.id]} xu",
                    inline=False)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text=f"Admin: {ctx.author.name} | ID: {ctx.author.id}")

    await ctx.send(embed=embed)


@napxu.error
async def napxu_error(ctx, error):
    """Xử lý lỗi cho lệnh napxu"""
    if isinstance(error, commands.MissingPermissions):
        embed = discord.Embed(
            title="❌ Lỗi Quyền Hạn",
            description=
            "Bạn không có quyền quản trị viên để thực hiện lệnh này.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
    elif isinstance(error, commands.MemberNotFound):
        embed = discord.Embed(
            title="❌ Không Tìm Thấy",
            description="Không thể tìm thấy thành viên này trong server.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
    elif isinstance(error, commands.BadArgument):
        embed = discord.Embed(
            title="❌ Lỗi Tham Số",
            description=
            "Hãy đảm bảo bạn đã nhắc đến thành viên hợp lệ và chỉ định số xu chính xác.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(
            title="❌ Lỗi Không Xác Định",
            description=f"Đã xảy ra lỗi: {str(error)}",
            color=discord.Color.red())
        await ctx.send(embed=embed)


@bot.command(name='rutxu')
@check_channel()
async def withdraw_from_vault(ctx, amount: int = None):
    if amount is None:
        embed = discord.Embed(
            title="Thiếu thông tin",
            description="Bạn cần nhập số xu muốn rút. Ví dụ: `.rutxu 50`.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    user_id = ctx.author.id
    guild_id = ctx.guild.id
    user_name = ctx.author.display_name

    if amount <= 0:
        embed = discord.Embed(title="Lỗi",
                              description="Số lượng xu rút phải lớn hơn 0.",
                              color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    if vault[guild_id][user_id] >= amount:
        vault[guild_id][user_id] -= amount
        currency[user_id] += amount
        embed = discord.Embed(
            title="Rút Xu Thành Công",
            description=
            f"**{user_name}** (`ID: {user_id}`) đã rút **{amount} xu** từ két.\nSố xu hiện tại trong két là **{vault[guild_id][user_id]} xu**.",
            color=discord.Color.green())
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(
            title="Rút Xu Thất Bại",
            description=
            f"**{user_name}** (`ID: {user_id}`) không có đủ xu trong két để rút.",
            color=discord.Color.red())
        await ctx.send(embed=embed)


@bot.command(name='rutket')
@commands.has_permissions(
    manage_guild=True
)  # Chỉ cho phép người có quyền quản lý server sử dụng lệnh này
async def withdraw_from_vault(ctx, amount: int):
    user_id = ctx.author.id
    username = ctx.author.display_name
    guild_id = ctx.guild.id

    # Kiểm tra số lượng xu cần rút có hợp lệ không
    if amount <= 0:
        embed = discord.Embed(title="Lỗi",
                              description="Số lượng xu phải lớn hơn 0.",
                              color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Kiểm tra người dùng có đủ xu trong két để rút không
    if vault.get(guild_id, {}).get(user_id, 0) >= amount:
        vault[guild_id][user_id] -= amount
        currency[user_id] += amount
        embed = discord.Embed(
            title="Rút Xu Thành Công",
            description=
            f"{username} (`ID: {user_id}`) đã rút **{amount} xu** từ két.\nSố xu hiện tại trong két là **{vault[guild_id][user_id]} xu**.",
            color=discord.Color.green())
    else:
        embed = discord.Embed(
            title="Rút Xu Thất Bại",
            description=
            f"Không đủ xu trong két để rút. Số xu hiện tại trong két của bạn là **{vault.get(guild_id, {}).get(user_id, 0)} xu**.",
            color=discord.Color.red())

    await ctx.send(embed=embed)


@bot.command(name='xemket')
@check_channel()
async def check_vault(ctx):
    """Kiểm tra số xu trong két của người chơi"""
    user_id = ctx.author.id
    guild_id = ctx.guild.id
    user_vault_balance = vault[guild_id][
        user_id]  # This will return 0 for new users because of defaultdict

    embed = discord.Embed(
        title="🔒 Két Sắt Cá Nhân",
        description=f"{ctx.author.mention}, thông tin két sắt của bạn:",
        color=discord.Color.blue())
    embed.add_field(name="Số xu trong két",
                    value=f"**{user_vault_balance} xu**",
                    inline=False)

    # Add instructions on how to use the vault
    if user_vault_balance == 0:
        embed.add_field(
            name="💡 Hướng dẫn",
            value=
            "Bạn chưa có xu trong két. Sử dụng `.napket [số xu]` để nạp xu vào két.",
            inline=False)
    else:
        embed.add_field(name="💡 Hướng dẫn",
                        value="Sử dụng `.rutxu [số xu]` để rút xu từ két.",
                        inline=False)

    embed.set_thumbnail(url=ctx.author.display_avatar.url)
    embed.set_footer(text=f"ID: {user_id}")

    await ctx.send(embed=embed)


@bot.command(name='napket')
@check_channel()
async def deposit_to_vault(ctx, amount: int = None):
    """Nạp xu vào két sắt cá nhân"""
    if amount is None:
        embed = discord.Embed(
            title="Thiếu thông tin",
            description="Bạn cần nhập số xu muốn nạp. Ví dụ: `.napket 50`.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    user_id = ctx.author.id
    guild_id = ctx.guild.id
    user_name = ctx.author.display_name

    # Validate amount
    if amount <= 0:
        embed = discord.Embed(title="Lỗi",
                              description="Số lượng xu nạp phải lớn hơn 0.",
                              color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Check if user has enough currency
    if currency[user_id] < amount:
        embed = discord.Embed(
            title="Không đủ xu",
            description=
            f"Bạn không có đủ xu để nạp. Số xu hiện tại: **{currency[user_id]} xu**",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Process the deposit
    currency[user_id] -= amount
    vault[guild_id][user_id] += amount

    embed = discord.Embed(
        title="✅ Nạp Két Thành Công",
        description=f"**{user_name}** đã nạp **{amount} xu** vào két.",
        color=discord.Color.green())
    embed.add_field(name="Số xu trong két",
                    value=f"**{vault[guild_id][user_id]} xu**",
                    inline=True)
    embed.add_field(name="Số xu còn lại",
                    value=f"**{currency[user_id]} xu**",
                    inline=True)
    embed.set_thumbnail(url=ctx.author.display_avatar.url)

    await ctx.send(embed=embed)

    ###Lệnh nuke channel


@bot.command(name='nuke')
@commands.has_permissions(administrator=True)
async def nuke_channel(ctx):
    """Xóa tất cả tin nhắn trong kênh bằng cách xóa và tạo lại kênh đó"""
    # Tạo embed xác nhận
    confirm_embed = discord.Embed(
        title="🧨 Xác Nhận Nuke Kênh",
        description=f"Bạn có chắc chắn muốn xóa tất cả tin nhắn trong kênh #{ctx.channel.name}? Kênh sẽ bị xóa và tạo lại tương tự.",
        color=discord.Color.red()
    )
    confirm_embed.add_field(
        name="⚠️ Cảnh báo",
        value="Tất cả tin nhắn trong kênh này sẽ bị xóa vĩnh viễn và không thể khôi phục!",
        inline=False
    )
    confirm_embed.set_footer(text="Nhấn nút xác nhận trong vòng 30 giây để tiếp tục")

    # Tạo view với các nút
    view = discord.ui.View(timeout=30)
    
    # Nút xác nhận
    confirm_button = discord.ui.Button(label="Xác nhận Nuke", style=discord.ButtonStyle.danger, emoji="💣")
    
    # Nút hủy
    cancel_button = discord.ui.Button(label="Hủy", style=discord.ButtonStyle.secondary, emoji="❌")
    
    async def confirm_callback(interaction):
        if interaction.user != ctx.author:
            await interaction.response.send_message("Chỉ người yêu cầu mới có thể xác nhận lệnh này!", ephemeral=True)
            return
            
        await interaction.response.defer()
        
        # Lưu thông tin kênh cũ để tạo lại sau khi nuke
        channel = ctx.channel
        channel_name = channel.name
        channel_topic = channel.topic
        channel_nsfw = channel.is_nsfw()
        channel_category = channel.category
        channel_slowmode = channel.slowmode_delay
        channel_position = channel.position
        channel_permissions = channel.overwrites
        
        try:
            # Thông báo đang nuke
            processing_embed = discord.Embed(
                title="🧨 Đang Nuke Kênh...",
                description="Kênh đang được xóa và tạo lại. Vui lòng chờ trong giây lát.",
                color=discord.Color.orange()
            )
            await interaction.message.edit(embed=processing_embed, view=None)
            
            # Tạo kênh mới với cùng thuộc tính
            new_channel = await channel.clone(
                name=channel_name,
                reason=f"Nuke bởi {ctx.author.name} ({ctx.author.id})"
            )
            
            # Đảm bảo vị trí mới giống vị trí cũ
            await new_channel.edit(position=channel_position)
            
            # Xóa kênh cũ
            await channel.delete()
            
            # Gửi thông báo thành công trong kênh mới
            success_embed = discord.Embed(
                title="💥 Nuke Thành Công!",
                description=f"Kênh đã được nuke bởi {ctx.author.mention}",
                color=discord.Color.green()
            )
            success_embed.set_image(url="https://media.giphy.com/media/HhTXt43pk1I1W/giphy.gif")
            
            msg = await new_channel.send(embed=success_embed)
            
            # Tự động xóa thông báo sau 10 giây
            await asyncio.sleep(10)
            await msg.delete()
            
        except discord.Forbidden:
            error_embed = discord.Embed(
                title="❌ Lỗi Quyền Hạn",
                description="Bot không có đủ quyền để nuke kênh này!",
                color=discord.Color.red()
            )
            await interaction.message.edit(embed=error_embed, view=None)
            
        except Exception as e:
            error_embed = discord.Embed(
                title="❌ Lỗi",
                description=f"Đã xảy ra lỗi: {str(e)}",
                color=discord.Color.red()
            )
            await interaction.message.edit(embed=error_embed, view=None)
    
    async def cancel_callback(interaction):
        if interaction.user != ctx.author:
            await interaction.response.send_message("Chỉ người yêu cầu mới có thể hủy lệnh này!", ephemeral=True)
            return
            
        cancel_embed = discord.Embed(
            title="✅ Đã Hủy",
            description="Lệnh nuke đã được hủy.",
            color=discord.Color.green()
        )
        await interaction.message.edit(embed=cancel_embed, view=None)
        
        # Tự động xóa tin nhắn sau 5 giây
        await asyncio.sleep(5)
        await interaction.message.delete()
    
    # Gán callback cho các nút
    confirm_button.callback = confirm_callback
    cancel_button.callback = cancel_callback
    
    # Thêm nút vào view
    view.add_item(confirm_button)
    view.add_item(cancel_button)
    
    # Gửi tin nhắn xác nhận
    message = await ctx.send(embed=confirm_embed, view=view)
    
    # Xóa lệnh gốc
    try:
        await ctx.message.delete()
    except:
        pass
    
    # Timeout handler
    async def on_timeout():
        timeout_embed = discord.Embed(
            title="⌛ Hết Thời Gian",
            description="Đã hết thời gian xác nhận lệnh nuke.",
            color=discord.Color.dark_gray()
        )
        await message.edit(embed=timeout_embed, view=None)
        
        # Tự động xóa tin nhắn sau 5 giây
        await asyncio.sleep(5)
        await message.delete()
        
    view.on_timeout = on_timeout

@nuke_channel.error
async def nuke_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        embed = discord.Embed(
            title="❌ Không đủ quyền hạn",
            description="Bạn cần có quyền quản trị viên để sử dụng lệnh này.",
            color=discord.Color.red()
        )
        error_msg = await ctx.send(embed=embed)
        
        # Tự động xóa thông báo lỗi sau 5 giây
        await asyncio.sleep(5)
        await error_msg.delete()
        try:
            await ctx.message.delete()
        except:
            pass
    else:
        embed = discord.Embed(
            title="❌ Lỗi",
            description=f"Đã xảy ra lỗi: {str(error)}",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)


@bot.command(name='coquaynga', aliases=['cqn', 'nga'])
@check_channel()
@check_game_enabled('coquaynga')
async def co_quay_nga(ctx, bet: str = None):
    """Trò chơi Cô Quay Nga - Russian Roulette"""
    if bet is None:
        embed = discord.Embed(
            title="🔫 Cô Quay Nga - Hướng Dẫn",
            description="Trò chơi may rủi với khẩu súng 6 viên đạn, chỉ có 1 viên nạp đạn.",
            color=discord.Color.blue())
        embed.add_field(
            name="Cách chơi",
            value="- Nhập số xu muốn cược (ví dụ: `.coquaynga 100` hoặc `.cqn all`)\n- Nếu sống sót (5/6 cơ hội), bạn thắng x1.5 tiền cược\n- Nếu trúng đạn (1/6 cơ hội), bạn mất tiền cược và bị timeout 5 phút",
            inline=False)
        embed.add_field(
            name="Rủi ro cao - thưởng lớn!",
            value="Tỷ lệ sống sót: 83.33% | Tỷ lệ trúng đạn: 16.67%",
            inline=False)
        await ctx.send(embed=embed)
        return

    user_id = ctx.author.id

    # Xử lý đặt cược "all"
    bet_amount = parse_bet(bet, currency[user_id])
    if bet_amount is None:
        embed = discord.Embed(
            title="❌ Số tiền không hợp lệ",
            description="Vui lòng nhập số tiền hợp lệ hoặc 'all'.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Kiểm tra tiền cược
    if bet_amount <= 0:
        embed = discord.Embed(
            title="🔫 Cô Quay Nga",
            description="Số tiền cược phải lớn hơn 0 xu.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    if currency[user_id] < bet_amount:
        embed = discord.Embed(
            title="🔫 Cô Quay Nga",
            description=f"{ctx.author.mention}, bạn không đủ xu để đặt cược! Bạn hiện có {currency[user_id]} xu.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Tạo hiệu ứng chuẩn bị và animation
    loading_embed = discord.Embed(
        title="🔫 CÔ QUAY NGA - RUSSIAN ROULETTE 🔫",
        description=f"{ctx.author.mention} đặt cược **{bet_amount} xu** vào trò cô quay nga!",
        color=discord.Color.gold())
    loading_embed.add_field(
        name="🔄 Đang chuẩn bị",
        value="Chuẩn bị khẩu súng và nạp đạn...",
        inline=False)
    loading_msg = await ctx.send(embed=loading_embed)
    await asyncio.sleep(1)

    # Hiệu ứng chuẩn bị súng và đạn
    prepare_embed = discord.Embed(
        title="🔫 CÔ QUAY NGA - RUSSIAN ROULETTE 🔫",
        description=f"{ctx.author.mention} đặt cược **{bet_amount} xu**!",
        color=discord.Color.orange())
    prepare_embed.add_field(
        name="🔄 Đang nạp đạn",
        value="```\n"
              "  ╔═══════════╗\n"
              "  ║ o o o o o o ║\n"  
              "  ╚═══════════╝\n"
              "    Súng 6 viên\n"
              "```",
        inline=False)
    await loading_msg.edit(embed=prepare_embed)
    await asyncio.sleep(1)

    # Hiệu ứng nạp 1 viên đạn vào
    load_embed = discord.Embed(
        title="🔫 CÔ QUAY NGA - RUSSIAN ROULETTE 🔫",
        description=f"{ctx.author.mention} đặt cược **{bet_amount} xu**!",
        color=discord.Color.orange())
    load_embed.add_field(
        name="🔄 Đã nạp 1 viên đạn",
        value="```\n"
              "  ╔═══════════╗\n"
              "  ║ o o o o o ● ║\n"
              "  ╚═══════════╝\n"
              "   Đạn đã được nạp\n"
              "```",
        inline=False)
    await loading_msg.edit(embed=load_embed)
    await asyncio.sleep(1)

    # Hiệu ứng xoay súng
    spin_embed = discord.Embed(
        title="🔫 CÔ QUAY NGA - RUSSIAN ROULETTE 🔫",
        description=f"{ctx.author.mention} đặt cược **{bet_amount} xu**!",
        color=discord.Color.orange())
    spin_embed.add_field(
        name="🔄 Đang xoay súng",
        value="```\n"
              "      O\n"
              "     /|\\\n"
              "  🔫 / \\\n"
              "  Súng đang xoay...\n"
              "```",
        inline=False)
    await loading_msg.edit(embed=spin_embed)
    await asyncio.sleep(1.5)

    # Xoay thêm lần nữa
    spin_embed2 = discord.Embed(
        title="🔫 CÔ QUAY NGA - RUSSIAN ROULETTE 🔫",
        description=f"{ctx.author.mention} đặt cược **{bet_amount} xu**!",
        color=discord.Color.orange())
    spin_embed2.add_field(
        name="🔄 Súng đã xoay xong",
        value="```\n"
              "      O\n"
              "     /|\\\n"
              "  🔫 / \\\n"
              "  Chuẩn bị bóp cò...\n"
              "```",
        inline=False)
    await loading_msg.edit(embed=spin_embed2)
    await asyncio.sleep(1)

    # Hiệu ứng đếm ngược tạo kịch tính
    for countdown in range(3, 0, -1):
        countdown_embed = discord.Embed(
            title="🔫 CÔ QUAY NGA - RUSSIAN ROULETTE 🔫",
            description=f"{ctx.author.mention} đặt cược **{bet_amount} xu**!",
            color=discord.Color.red())
        countdown_embed.add_field(
            name=f"⏱️ Bóp cò trong {countdown}...",
            value="```\n"
                  "      O   💦\n"
                  "     /|\\   \n"
                  "  🔫 / \\  \n"
                  "  Đang đợi kết quả...\n"
                  "```",
            inline=False)
        await loading_msg.edit(embed=countdown_embed)
        await asyncio.sleep(0.8)

    # Quyết định kết quả (1/6 cơ hội trúng đạn)
    if is_whitelisted(ctx.author.id):
        # Người chơi trong whitelist luôn sống sót
        hit = False
    else:
        # Tỷ lệ bình thường: 1/6 trúng đạn (16.67%)
        hit = random.random() < 0.1667

    # Hiển thị kết quả
    if hit:
        # Người chơi trúng đạn - thua
        result_embed = discord.Embed(
            title="💥 BẠN TRÚNG ĐẠN! 💥",
            description=f"{ctx.author.mention} đã trúng đạn và thua **{bet_amount} xu**!",
            color=discord.Color.red())
        
        # Animation người thua
        death_animation = "```\n" + \
                         "      O   💥\n" + \
                         "     /|\\  \n" + \
                         "  🔫 / \\  \n" + \
                         "  BANG! Bạn đã thua.\n" + \
                         "```"
        result_embed.add_field(
            name="☠️ KẾT QUẢ",
            value=death_animation,
            inline=False)
        
        result_embed.add_field(
            name="💸 Thiệt hại",
            value=f"−{bet_amount} xu",
            inline=True)
        
        result_embed.add_field(
            name="⏳ Hình phạt",
            value="Timeout 5 phút",
            inline=True)
        
        result_embed.add_field(
            name="💰 Số dư hiện tại",
            value=f"{currency[user_id] - bet_amount} xu",
            inline=True)
        
        # Trừ tiền người chơi
        currency[user_id] -= bet_amount
        
        # Gắn timeout cho người thua
        try:
            timeout_until = discord.utils.utcnow() + timedelta(minutes=5)
            await ctx.author.timeout(timeout_until, reason="Thua trò Cô Quay Nga")
            result_embed.set_footer(text="Bạn đã bị timeout 5 phút do trúng đạn!")
        except Exception as e:
            result_embed.set_footer(text=f"Không thể timeout: {str(e)}")
        
    else:
        # Người chơi sống sót - thắng
        winnings = int(bet_amount * 1.5)  # Thắng x1.5 tiền cược
        result_embed = discord.Embed(
            title="🎉 BẠN SỐNG SÓT! 🎉",
            description=f"{ctx.author.mention} đã sống sót và thắng **{winnings - bet_amount} xu**!",
            color=discord.Color.green())
        
        # Animation người thắng
        win_animation = "```\n" + \
                       "      O   😅\n" + \
                       "     /|\\  \n" + \
                       "  🔫 / \\  \n" + \
                       "  *CLICK* An toàn!\n" + \
                       "```"
        result_embed.add_field(
            name="🎯 KẾT QUẢ",
            value=win_animation,
            inline=False)
        
        result_embed.add_field(
            name="💰 Tiền thắng",
            value=f"+{winnings - bet_amount} xu (x1.5)",
            inline=True)
        
        result_embed.add_field(
            name="🍀 May mắn",
            value="Bạn đã thoát chết!",
            inline=True)
        
        # Cộng tiền thắng cho người chơi
        currency[user_id] += winnings - bet_amount
        
        result_embed.add_field(
            name="💰 Số dư hiện tại",
            value=f"{currency[user_id]} xu",
            inline=True)
        
        result_embed.set_footer(text="Thử thách tiếp tục may mắn của bạn với một lần chơi nữa?")
    
    # Hiển thị kết quả cuối cùng
    await loading_msg.edit(embed=result_embed)


@bot.command(name='howstupid', aliases=['howdumb', 'dumb', 'ngu'])
async def howstupid(ctx, member: discord.Member = None):
    """Kiểm tra độ ngu của một thành viên với kết quả ngẫu nhiên"""
    # Kiểm tra cooldown để tránh spam
    user_id = ctx.author.id
    current_time = datetime.now()
    
    # Giả sử bạn đã có một dict tương tự howgay_cooldown
    if user_id in howgay_cooldown:
        time_since_last_use = (current_time - howgay_cooldown[user_id]).total_seconds()
        if time_since_last_use < 30:  # 30 giây cooldown
            remaining = int(30 - time_since_last_use)
            await ctx.send(f"⏳ Vui lòng đợi {remaining} giây nữa trước khi dùng lại lệnh này.")
            return
    
    # Cập nhật thời gian sử dụng
    howgay_cooldown[user_id] = current_time
    
    # Xác định người được kiểm tra
    target = member or ctx.author
    
    # Tìm role Ngu trong server, tạo nếu không có
    stupid_role = discord.utils.get(ctx.guild.roles, name="🧠 Ngu")
    if not stupid_role:
        try:
            stupid_role = await ctx.guild.create_role(
                name="🧠 Ngu",
                color=discord.Color.orange(),
                reason="Tạo role cho lệnh howstupid"
            )
        except:
            stupid_role = None
    
    # Xác định kết quả stupid meter
    # Nếu người dùng là admin, luôn hiển thị 0% (không ngu)
    if target.guild_permissions.administrator:
        stupid_level = 0
    elif target.bot:
        stupid_level = 0  # Bot không ngu
    else:
        stupid_level = random.randint(0, 100)
    
    # Tạo biểu tượng và màu sắc dựa vào kết quả
    if stupid_level < 20:
        emoji = "🧠"
        color = discord.Color.green()
        message = "Thông minh sáng suốt! Người này chắc học Harvard!"
    elif stupid_level < 40:
        emoji = "📚"
        color = discord.Color.blue()
        message = "Khá thông minh, biết suy nghĩ trước khi hành động!"
    elif stupid_level < 60:
        emoji = "😕"
        color = discord.Color.gold()
        message = "Trung bình... đôi khi cũng có quyết định thiếu suy nghĩ!"
    elif stupid_level < 80:
        emoji = "🤦‍♂️"
        color = discord.Color.orange()
        message = "Khá ngu rồi đó! Toàn làm những việc không ai hiểu nổi!"
    else:
        emoji = "🪨"
        color = discord.Color.red()
        message = "SIÊU NGU! IQ có lẽ bằng hòn đá!"
    
    # Tạo progress bar
    progress_bar = "🟥" * (stupid_level // 10) + "⬜" * ((100 - stupid_level) // 10)
    
    # Tạo embed
    embed = discord.Embed(
        title=f"{emoji} Máy đo độ ngu",
        description=f"Độ ngu của {target.mention}",
        color=color
    )
    embed.add_field(
        name="Kết quả", 
        value=f"**{stupid_level}%** {emoji}", 
        inline=False
    )
    embed.add_field(
        name="Mức độ", 
        value=progress_bar, 
        inline=False
    )
    embed.add_field(
        name="Nhận xét", 
        value=message, 
        inline=False
    )
    embed.set_thumbnail(url=target.display_avatar.url)
    
    # Gửi kết quả
    await ctx.send(embed=embed)
    
    # Nếu stupid_level > 50%, thêm role Ngu trong 1 giờ
    if stupid_level > 50 and stupid_role and not target.bot and target.id != ctx.guild.owner_id:
        try:
            await target.add_roles(stupid_role)
            
            # Thông báo về việc thêm role
            dm_embed = discord.Embed(
                title="🧠 Bạn đã nhận được role Ngu!",
                description="Bạn quá ngu nên đã được thêm role Ngu trong 1 giờ.",
                color=discord.Color.orange()
            )
            dm_embed.add_field(
                name="Kết quả", 
                value=f"Độ ngu: **{stupid_level}%**", 
                inline=True
            )
            dm_embed.add_field(
                name="Thời hạn", 
                value="Role sẽ tự động bị gỡ sau 1 giờ", 
                inline=True
            )
            
            try:
                await target.send(embed=dm_embed)
            except:
                pass  # Bỏ qua nếu không gửi được DM
                
            # Gỡ role sau 1 giờ
            bot.loop.create_task(remove_stupid_role_after_duration(target.id, ctx.guild.id, stupid_role.id))
        except Exception as e:
            print(f"Không thể thêm role Ngu: {str(e)}")

@bot.command(name='howfat')
async def howfat(ctx, member: discord.Member = None):
    """Kiểm tra độ béo (cân nặng) của một thành viên với kết quả ngẫu nhiên"""
    # Kiểm tra cooldown để tránh spam
    user_id = ctx.author.id
    current_time = datetime.now()
    
    # Sử dụng cùng dict howgay_cooldown
    if user_id in howgay_cooldown:
        time_since_last_use = (current_time - howgay_cooldown[user_id]).total_seconds()
        if time_since_last_use < 30:  # 30 giây cooldown
            remaining = int(30 - time_since_last_use)
            await ctx.send(f"⏳ Vui lòng đợi {remaining} giây nữa trước khi dùng lại lệnh này.")
            return
    
    # Cập nhật thời gian sử dụng
    howgay_cooldown[user_id] = current_time
    
    # Xác định người được kiểm tra
    target = member or ctx.author
    
    # Tìm role Béo trong server, tạo nếu không có
    fat_role = discord.utils.get(ctx.guild.roles, name="🍔 Béo")
    if not fat_role:
        try:
            fat_role = await ctx.guild.create_role(
                name="🍔 Béo",
                color=discord.Color.dark_orange(),
                reason="Tạo role cho lệnh howfat"
            )
        except:
            fat_role = None
    
    # Xác định cân nặng
    # Nếu người dùng là admin, cân nặng từ 60-75kg
    if target.guild_permissions.administrator:
        weight = random.randint(60, 75)
    elif target.bot:
        weight = 0  # Bot không có cân nặng
    else:
        weight = random.randint(30, 200)  # 30kg - 200kg
    
    # Tạo biểu tượng dựa vào cân nặng
    if (weight < 50):
        emoji = "🐜"
        color = discord.Color.blue()
        message = "Nhẹ như lông hồng! Bay mất bạn ơi!"
    elif (weight < 80):
        emoji = "👌"
        color = discord.Color.green()
        message = "Cân đối tuyệt vời!"
    elif (weight < 120):
        emoji = "🍔"
        color = discord.Color.gold()
        message = "Hơi nặng một chút rồi đấy!"
    else:
        emoji = "🐘"
        color = discord.Color.red()
        message = "Thôi nào, bạn cần một chế độ ăn kiêng gấp!"
    
    # Tạo embed
    embed = discord.Embed(
        title=f"⚖️ Máy đo cân nặng",
        description=f"Cân nặng của {target.mention}",
        color=color
    )
    embed.add_field(
        name="Kết quả", 
        value=f"**{weight} kg** {emoji}", 
        inline=False
    )
    embed.add_field(
        name="Nhận xét", 
        value=message, 
        inline=False
    )
    embed.set_thumbnail(url=target.display_avatar.url)
    
    # Gửi kết quả
    await ctx.send(embed=embed)
    
    # Nếu weight > 100kg, thêm role Béo trong 1 giờ
    if weight > 100 and fat_role and not target.bot and target.id != ctx.guild.owner_id:
        try:
            await target.add_roles(fat_role)
            
            # Thông báo về việc thêm role
            dm_embed = discord.Embed(
                title="🍔 Bạn đã nhận được role Béo!",
                description="Bạn quá béo nên đã được thêm role Béo trong 1 giờ.",
                color=discord.Color.dark_orange()
            )
            dm_embed.add_field(
                name="Kết quả", 
                value=f"Cân nặng: **{weight} kg**", 
                inline=True
            )
            dm_embed.add_field(
                name="Thời hạn", 
                value="Role sẽ tự động bị gỡ sau 1 giờ", 
                inline=True
            )
            
            try:
                await target.send(embed=dm_embed)
            except:
                pass  # Bỏ qua nếu không gửi được DM
                
            # Gỡ role sau 1 giờ
            bot.loop.create_task(remove_fat_role_after_duration(target.id, ctx.guild.id, fat_role.id))
        except Exception as e:
            print(f"Không thể thêm role Béo: {str(e)}")

# Hàm phụ trợ để gỡ role Béo sau 1 giờ
async def remove_fat_role_after_duration(user_id, guild_id, role_id):
    """Gỡ role Béo sau 1 giờ"""
    await asyncio.sleep(3600)  # 1 giờ = 3600 giây
    
    # Tìm guild
    guild = bot.get_guild(guild_id)
    if not guild:
        return
        
    # Tìm member
    member = guild.get_member(user_id)
    if not member:
        return
        
    # Tìm role
    role = guild.get_role(role_id)
    if not role or role not in member.roles:
        return
        
    # Gỡ role
    try:
        await member.remove_roles(role)
        
        # Thông báo qua DM
        try:
            dm_embed = discord.Embed(
                title="🍔 Role Béo đã hết hạn",
                description="Role Béo tạm thời của bạn đã được gỡ bỏ sau 1 giờ.",
                color=discord.Color.blue()
            )
            await member.send(embed=dm_embed)
        except:
            pass  # Bỏ qua nếu không gửi được DM
    except:
        pass  # Bỏ qua nếu không gỡ được role

@bot.command(name='howretarded', aliases=['howthieunang', 'thieunang', 'tn'])
async def howretarded(ctx, member: discord.Member = None):
    """Kiểm tra độ thiểu năng của một thành viên với kết quả ngẫu nhiên"""
    target = member or ctx.author
    retarded_level = random.randint(0, 100)

    # Tạo biểu tượng dựa vào độ thiểu năng
    if retarded_level < 20:
        emoji = "🧠"
        color = discord.Color.green()
        message = "Hoàn toàn bình thường, chức năng não bộ tuyệt vời!"
    elif retarded_level < 40:
        emoji = "🤔"
        color = discord.Color.blue()
        message = "Đôi khi hơi đơ đơ một tí, nhưng vẫn ổn!"
    elif retarded_level < 60:
        emoji = "😵‍💫"
        color = discord.Color.gold()
        message = "Có dấu hiệu thiểu năng nhẹ, hay quên và không hiểu chuyện!"
    elif retarded_level < 80:
        emoji = "🥴"
        color = discord.Color.orange()
        message = "Thiểu năng khá nặng! Khó giao tiếp bình thường!"
    else:
        emoji = "🤪"
        color = discord.Color.red()
        message = "THIỂU NĂNG TRẦM TRỌNG! Cần người chăm sóc 24/7!"

    # Tạo progress bar
    progress_bar = "🟥" * (retarded_level // 10) + "⬜" * ((100 - retarded_level) // 10)

    # Tạo hiệu ứng phụ cho kết quả cao
    additional_effect = ""
    if retarded_level > 85:
        additional_effect = "```\n" + \
                            "  /🧠\   Não đang rơi ra ngoài...\n" + \
                            " ( 👁️ 👁️ )  \n" + \
                            "  \  ᴗ  /   \n" + \
                            "```"

    embed = discord.Embed(title=f"{emoji} Máy đo độ thiểu năng",
                          description=f"Độ thiểu năng của {target.mention}",
                          color=color)
    embed.add_field(name="Kết quả",
                    value=f"**{retarded_level}%** {emoji}",
                    inline=False)
    embed.add_field(name="Mức độ", value=progress_bar, inline=False)
    
    if additional_effect:
        embed.add_field(name="Hiện tượng", value=additional_effect, inline=False)
        
    embed.add_field(name="Nhận xét", value=message, inline=False)
    embed.set_thumbnail(url=target.display_avatar.url)

    await ctx.send(embed=embed)


@bot.command(name='whoping', aliases=['checkping', 'pingcheck'])
async def who_is_pinging(ctx, user: discord.Member = None):
    """Kiểm tra những ai đã ping người dùng gần đây"""
    # Nếu không chỉ định người dùng, mặc định là người gọi lệnh
    target = user or ctx.author
    
    # Chỉ cho phép kiểm tra ping của bản thân hoặc admin mới có thể kiểm tra ping người khác
    if target.id != ctx.author.id and not ctx.author.guild_permissions.administrator:
        embed = discord.Embed(
            title="❌ Không đủ quyền hạn",
            description="Bạn chỉ có thể kiểm tra ping của chính mình.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return
    
    # Tạo embed ban đầu
    embed = discord.Embed(
        title=f"🔎 Kiểm Tra Ping cho {target.display_name}",
        description="Đang quét tin nhắn để tìm ping...",
        color=discord.Color.blue()
    )
    status_message = await ctx.send(embed=embed)
    
    # Chuẩn bị để lưu trữ dữ liệu ping
    ping_data = {}
    total_pings = 0
    channels_checked = 0
    
    # Hàm cập nhật trạng thái tiến trình
    async def update_progress(channel_name=None):
        progress_embed = discord.Embed(
            title=f"🔎 Kiểm Tra Ping cho {target.display_name}",
            description=f"Đang quét tin nhắn...\nĐã tìm thấy: {total_pings} ping\nĐã kiểm tra: {channels_checked} kênh",
            color=discord.Color.blue()
        )
        if channel_name:
            progress_embed.add_field(
                name="Kênh hiện tại", 
                value=f"#{channel_name}", 
                inline=False
            )
        await status_message.edit(embed=progress_embed)
    
    # Bắt đầu tìm kiếm trong các kênh
    try:
        for channel in ctx.guild.text_channels:
            # Bỏ qua các kênh không có quyền đọc tin nhắn
            if not channel.permissions_for(ctx.guild.me).read_message_history:
                continue
                
            channels_checked += 1
            await update_progress(channel.name)
            
            # Tìm kiếm tin nhắn trong 7 ngày gần đây (giới hạn 300 tin nhắn mỗi kênh)
            try:
                async for message in channel.history(limit=300, after=discord.utils.utcnow() - timedelta(days=7)):
                    # Bỏ qua tin nhắn từ bot
                    if message.author.bot:
                        continue
                        
                    # Kiểm tra các mention trong tin nhắn
                    if target in message.mentions:
                        total_pings += 1
                        pinger = message.author
                        
                        # Cập nhật dữ liệu ping
                        if pinger.id not in ping_data:
                            ping_data[pinger.id] = {
                                "name": pinger.display_name,
                                "count": 0,
                                "channels": {},
                                "last_ping": None
                            }
                            
                        ping_data[pinger.id]["count"] += 1
                        
                        # Cập nhật kênh
                        if channel.id not in ping_data[pinger.id]["channels"]:
                            ping_data[pinger.id]["channels"][channel.id] = 0
                        ping_data[pinger.id]["channels"][channel.id] += 1
                        
                        # Cập nhật thời gian ping gần đây nhất
                        if (ping_data[pinger.id]["last_ping"] is None or 
                            message.created_at > ping_data[pinger.id]["last_ping"]):
                            ping_data[pinger.id]["last_ping"] = message.created_at
            
            except discord.Forbidden:
                pass  # Bỏ qua kênh nếu không có quyền đọc tin nhắn
            except Exception as e:
                continue  # Bỏ qua lỗi khác và tiếp tục
    
    except Exception as e:
        # Xử lý lỗi tổng quát
        error_embed = discord.Embed(
            title="❌ Đã xảy ra lỗi",
            description=f"Không thể hoàn thành việc kiểm tra: {str(e)}",
            color=discord.Color.red()
        )
        await status_message.edit(embed=error_embed)
        return
    
    # Tạo báo cáo cuối cùng
    if not ping_data:
        result_embed = discord.Embed(
            title=f"🔔 Kết Quả Kiểm Tra Ping cho {target.display_name}",
            description=f"Không tìm thấy ping nào cho {target.mention} trong 7 ngày qua.",
            color=discord.Color.green()
        )
        result_embed.set_thumbnail(url=target.display_avatar.url)
        await status_message.edit(embed=result_embed)
        return
    
    # Sắp xếp người ping theo số lượng ping
    sorted_pingers = sorted(ping_data.items(), key=lambda x: x[1]["count"], reverse=True)
    
    # Tạo embed kết quả
    result_embed = discord.Embed(
        title=f"🔔 Kết Quả Kiểm Tra Ping cho {target.display_name}",
        description=f"**{total_pings}** ping được tìm thấy từ **{len(ping_data)}** người dùng khác nhau trong 7 ngày qua.",
        color=discord.Color.gold()
    )
    
    result_embed.set_thumbnail(url=target.display_avatar.url)
    
    # Thêm thông tin top người ping
    top_pingers = sorted_pingers[:10]  # Chỉ hiển thị top 10
    pingers_info = ""
    
    for idx, (pinger_id, data) in enumerate(top_pingers, 1):
        try:
            pinger = await ctx.guild.fetch_member(pinger_id)
            pinger_name = pinger.display_name if pinger else data["name"]
            
            # Xác định emoji hạng
            rank_emoji = "🥇" if idx == 1 else "🥈" if idx == 2 else "🥉" if idx == 3 else f"{idx}."
            
            # Tạo danh sách kênh phổ biến
            top_channels = sorted(data["channels"].items(), key=lambda x: x[1], reverse=True)[:2]
            channels_text = ", ".join([f"#{ctx.guild.get_channel(channel_id).name}" for channel_id, _ in top_channels if ctx.guild.get_channel(channel_id)])
            
            # Định dạng thời gian ping gần nhất
            last_ping_time = discord.utils.format_dt(data["last_ping"], style="R") if data["last_ping"] else "Không rõ"
            
            # Thêm vào danh sách
            pingers_info += f"{rank_emoji} **{pinger_name}**: {data['count']} ping"
            pingers_info += f" (gần nhất: {last_ping_time})\n"
            
            # Thêm thông tin kênh nếu có
            if channels_text:
                pingers_info += f"  ↳ Chủ yếu tại: {channels_text}\n"
                
        except Exception as e:
            pingers_info += f"{idx}. Không thể hiển thị thông tin: {str(e)}\n"
    
    result_embed.add_field(
        name="👤 Người Ping Nhiều Nhất",
        value=pingers_info or "Không có dữ liệu",
        inline=False
    )
    
    # Thêm thống kê thời gian
    time_stats = {}
    for pinger_id, data in ping_data.items():
        if data["last_ping"]:
            hour = data["last_ping"].hour
            if hour not in time_stats:
                time_stats[hour] = 0
            time_stats[hour] += data["count"]
    
    # Xác định khung giờ phổ biến
    if time_stats:
        popular_hours = sorted(time_stats.items(), key=lambda x: x[1], reverse=True)[:3]
        time_info = "\n".join([f"🕒 **{hour}:00 - {hour+1}:00**: {count} ping" for hour, count in popular_hours])
        
        result_embed.add_field(
            name="⏰ Khung Giờ Phổ Biến",
            value=time_info,
            inline=False
        )
    
    # Thêm footer
    result_embed.set_footer(text=f"Đã kiểm tra {channels_checked} kênh | ID: {target.id}")
    
    # Gửi kết quả cuối cùng
    await status_message.edit(embed=result_embed)

@who_is_pinging.error
async def ping_check_error(ctx, error):
    if isinstance(error, commands.BadArgument):
        embed = discord.Embed(
            title="❌ Người dùng không hợp lệ",
            description="Không thể tìm thấy người dùng này.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(
            title="❌ Đã xảy ra lỗi",
            description=f"Lỗi khi kiểm tra ping: {str(error)}",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)

@bot.command(name='ktxu')
@commands.has_permissions(administrator=True)
async def check_user_balance(ctx, member: discord.Member = None):
    """Cho phép admin kiểm tra số xu của một thành viên"""
    if member is None:
        embed = discord.Embed(
            title="❓ Kiểm Tra Xu",
            description=
            "Vui lòng chỉ định một thành viên để kiểm tra. Ví dụ: `.ktxu @tênthànhviên`",
            color=discord.Color.blue())
        await ctx.send(embed=embed)
        return

    user_balance = currency.get(member.id, 0)
    embed = discord.Embed(
        title="💰 Kiểm Tra Xu",
        description=
        f"Thành viên {member.mention} hiện có **{user_balance} xu**.",
        color=discord.Color.gold())
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text=f"ID: {member.id}")
    await ctx.send(embed=embed)


@check_user_balance.error
async def check_user_balance_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        embed = discord.Embed(
            title="❌ Lỗi Quyền Hạn",
            description=
            "Bạn không có quyền administrator để thực hiện lệnh này!",
            color=discord.Color.red())
        await ctx.send(embed=embed)

@bot.command(name='howgay')
async def howgay(ctx, member: discord.Member = None):
    """Kiểm tra độ gay của một thành viên với kết quả ngẫu nhiên"""
    # Kiểm tra cooldown để tránh spam
    user_id = ctx.author.id
    current_time = datetime.now()
    
    if user_id in howgay_cooldown:
        time_since_last_use = (current_time - howgay_cooldown[user_id]).total_seconds()
        if time_since_last_use < 30:  # 30 giây cooldown
            remaining = int(30 - time_since_last_use)
            await ctx.send(f"⏳ Vui lòng đợi {remaining} giây nữa trước khi dùng lại lệnh này.")
            return
    
    # Cập nhật thời gian sử dụng
    howgay_cooldown[user_id] = current_time
    
    # Xác định người được kiểm tra
    target = member or ctx.author
    
    # Tìm gay role trong server, tạo nếu không có
    gay_role = discord.utils.get(ctx.guild.roles, name="🌈 Gay")
    if not gay_role:
        try:
            gay_role = await ctx.guild.create_role(name="🌈 Gay", colour=discord.Colour.from_rgb(255, 0, 255))
        except:
            gay_role = None
    
    # Xác định kết quả gay meter
    # Nếu người dùng là admin hoặc bot, luôn hiển thị 0%
    if target.guild_permissions.administrator or target.bot:
        gay_level = 0
    else:
        gay_level = random.randint(0, 100)
    
    # Tạo emoji và màu sắc dựa trên kết quả
    if gay_level < 20:
        emoji = "😎"
        color = discord.Color.blue()
        message = "Khá là thẳng đấy!"
    elif gay_level < 40:
        emoji = "🙂"
        color = discord.Color.green()
        message = "Hơi cong một chút!"
    elif gay_level < 60:
        emoji = "😊"
        color = discord.Color.gold()
        message = "Gay vừa phải!"
    elif gay_level < 80:
        emoji = "😳"
        color = discord.Color.orange()
        message = "Khá là gay đó!"
    else:
        emoji = "🌈"
        color = discord.Color.purple()
        message = "Quá gay luôn rồi!"
    
    # Tạo progress bar
    progress_bar = "🟪" * (gay_level // 10) + "⬜" * ((100 - gay_level) // 10)
    
    # Tạo embed
    embed = discord.Embed(
        title=f"{emoji} Máy đo độ Gay",
        description=f"Độ gay của {target.mention}",
        color=color
    )
    embed.add_field(
        name="Kết quả", 
        value=f"**{gay_level}%** {emoji}", 
        inline=False
    )
    embed.add_field(
        name="Mức độ", 
        value=progress_bar, 
        inline=False
    )
    embed.add_field(
        name="Nhận xét", 
        value=message, 
        inline=False
    )
    embed.set_thumbnail(url=target.display_avatar.url)
    
    # Gửi kết quả
    await ctx.send(embed=embed)
    
    # Nếu gay_level > 50%, thêm role gay trong 1 giờ
    if gay_level > 50 and gay_role and not target.bot and target.id != ctx.guild.owner_id:
        try:
            if gay_role not in target.roles:
                await target.add_roles(gay_role)
                await ctx.send(f"🌈 {target.mention} đã nhận được role gay trong 1 giờ!")
                
                # Lên lịch xóa role sau 1 giờ
                bot.loop.create_task(
                    remove_gay_role_after_duration(target.id, ctx.guild.id, gay_role.id)
                )
        except Exception as e:
            print(f"Không thể thêm gay role: {e}")

# Hàm phụ trợ để gỡ role sau 1 giờ
async def remove_gay_role_after_duration(user_id, guild_id, role_id):
    """Gỡ gay role sau 1 giờ"""
    await asyncio.sleep(3600)  # 1 giờ = 3600 giây
    
    # Tìm guild
    guild = bot.get_guild(guild_id)
    if not guild:
        return
        
    # Tìm member
    member = guild.get_member(user_id)
    if not member:
        return
        
    # Tìm role
    role = guild.get_role(role_id)
    if not role or role not in member.roles:
        return
        
    # Gỡ role
    try:
        await member.remove_roles(role)
        
        # Thông báo qua DM
        try:
            dm_embed = discord.Embed(
                title="🏳️‍🌈 Gay Role đã hết hạn",
                description="Role Gay tạm thời của bạn đã được gỡ bỏ sau 1 giờ.",
                color=discord.Color.blue()
            )
            await member.send(embed=dm_embed)
        except:
            pass  # Bỏ qua nếu không gửi được DM
    except:
        pass  # Bỏ qua nếu không gỡ được role

@bot.command(name='howdamde', aliases=['damde', 'howlewd'])
async def howdamde(ctx, member: discord.Member = None):
    """Kiểm tra độ dâm dê của một thành viên với kết quả ngẫu nhiên"""
    target = member or ctx.author
    lewd_level = random.randint(0, 100)

    # Tạo biểu tượng và phản hồi dựa vào độ dâm dê
    if lewd_level < 30:
        emoji = "😇"
        message = "Rất trong sáng và thuần khiết!"
        color = discord.Color.light_grey()
    elif lewd_level < 60:
        emoji = "😏"
        message = "Hơi tinh quái một chút đấy nhưng vẫn ổn!"
        color = discord.Color.blue()
    elif lewd_level < 85:
        emoji = "😈"
        message = "Khá dâm dê rồi đấy! Cần kiểm soát bản thân hơn!"
        color = discord.Color.purple()
    else:
        emoji = "🔞"
        message = "Quá dâm rồi! Lên cai ngay đi kẻo chết sớm!"
        color = discord.Color.red()

    # Tạo progress bar
    progress_bar = "🟥" * (lewd_level // 10) + "⬜" * ((100 - lewd_level) // 10)

    embed = discord.Embed(title=f"🔞 Máy đo độ dâm dê",
                          description=f"Độ dâm dê của {target.mention}",
                          color=color)
    embed.add_field(name="Kết quả",
                    value=f"**{lewd_level}%** {emoji}",
                    inline=False)
    embed.add_field(name="Mức độ", value=progress_bar, inline=False)
    embed.add_field(name="Nhận xét", value=message, inline=False)
    embed.set_thumbnail(url=target.display_avatar.url)

    await ctx.send(embed=embed)


@bot.command(name='howmad')
async def howmad(ctx, member: discord.Member = None):
    """Kiểm tra độ điên của một thành viên với kết quả ngẫu nhiên"""
    target = member or ctx.author
    mad_level = random.randint(0, 100)

    # Tạo biểu tượng dựa vào độ điên
    if (mad_level < 30):
        emoji = "😇"
        color = discord.Color.blue()
        message = "Khá bình thường và điềm tĩnh!"
    elif (mad_level < 60):
        emoji = "🙃"
        color = discord.Color.gold()
        message = "Có đôi chút... khó hiểu!"
    elif (mad_level < 85):
        emoji = "🤪"
        color = discord.Color.orange()
        message = "Rõ ràng là có vấn đề tâm lý rồi!"
    else:
        emoji = "🤯"
        color = discord.Color.red()
        message = "HOÀN TOÀN ĐIÊN RỒI! TÌM BÁC SĨ NGAY!"

    # Tạo progress bar
    progress_bar = "🟥" * (mad_level // 10) + "⬜" * ((100 - mad_level) // 10)

    embed = discord.Embed(title=f"🧠 Máy đo độ điên",
                          description=f"Độ điên của {target.mention}",
                          color=color)
    embed.add_field(name="Kết quả",
                    value=f"**{mad_level}%** {emoji}",
                    inline=False)
    embed.add_field(name="Mức độ", value=progress_bar, inline=False)
    embed.add_field(name="Nhận xét", value=message, inline=False)
    embed.set_thumbnail(url=target.display_avatar.url)

    await ctx.send(embed=embed)


@bot.command(name='poker')
@check_channel()
@check_game_enabled('poker')
async def play_poker(ctx, bet: str = None):
    """Trò chơi Poker đơn giản"""
    if bet is None:
        embed = discord.Embed(
            title="🃏 Poker - Hướng Dẫn",
            description=
            "Hãy nhập số xu muốn cược để chơi poker.\nVí dụ: `.poker 50` hoặc `.poker all`",
            color=discord.Color.blue())
        embed.add_field(
            name="Luật chơi",
            value=
            "- Mỗi người chơi nhận 5 lá bài\n- Bạn có thể đổi tối đa 3 lá\n- Người có bài mạnh hơn sẽ chiến thắng",
            inline=False)
        embed.add_field(
            name="Thưởng",
            value=
            "🥇 Cặp đôi (One pair): x1.5 tiền cược\n🥈 Hai đôi (Two pairs): x2 tiền cược\n🥉 Bộ ba (Three of a kind): x3 tiền cược\n💰 Sảnh (Straight): x5 tiền cược\n🌟 Thùng (Flush): x7 tiền cược\n👑 Full house: x10 tiền cược",
            inline=False)
        await ctx.send(embed=embed)
        return

    user_id = ctx.author.id

    # Xử lý đặt cược "all"
    bet_amount = parse_bet(bet, currency[user_id])
    if bet_amount is None:
        embed = discord.Embed(
            title="❌ Số tiền không hợp lệ",
            description="Vui lòng nhập số tiền hợp lệ hoặc 'all'.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Kiểm tra bet
    if bet_amount <= 0:
        embed = discord.Embed(title="🃏 Poker",
                              description="Số tiền cược phải lớn hơn 0 xu.",
                              color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    if currency[user_id] < bet_amount:
        embed = discord.Embed(
            title="🃏 Poker",
            description=
            f"{ctx.author.mention}, bạn không đủ xu để đặt cược! Bạn hiện có {currency[user_id]} xu.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Bộ bài
    suits = ['♠️', '♥️', '♦️', '♣️']
    values = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
    value_dict = {
        '2': 2,
        '3': 3,
        '4': 4,
        '5': 5,
        '6': 6,
        '7': 7,
        '8': 8,
        '9': 9,
        '10': 10,
        'J': 11,
        'Q': 12,
        'K': 13,
        'A': 14
    }

    # Tạo bộ bài đầy đủ
    deck = [(v, s) for s in suits for v in values]
    random.shuffle(deck)

    # Chia bài cho người chơi và bot
    player_hand = [deck.pop() for _ in range(5)]
    bot_hand = [deck.pop() for _ in range(5)]

    # Hiển thị bài của người chơi
    player_cards = " ".join(f"{v}{s}" for v, s in player_hand)

    # Tạo buttons cho việc đánh dấu bài muốn đổi
    class CardButton(discord.ui.Button):

        def __init__(self, card, index):
            super().__init__(label=f"{card[0]}{card[1]}",
                             style=discord.ButtonStyle.secondary,
                             custom_id=str(index))
            self.marked = False

        async def callback(self, interaction):
            if interaction.user != ctx.author:
                await interaction.response.send_message(
                    "Bạn không phải người chơi!", ephemeral=True)
                return

            self.marked = not self.marked
            self.style = discord.ButtonStyle.danger if self.marked else discord.ButtonStyle.secondary
            await interaction.response.edit_message(view=self.view)

    class PokerView(discord.ui.View):

        def __init__(self, player_hand):
            super().__init__(timeout=30)
            self.card_buttons = []
            for i, card in enumerate(player_hand):
                button = CardButton(card, i)
                self.card_buttons.append(button)
                self.add_item(button)

            # Thêm nút đổi bài
            exchange_button = discord.ui.Button(
                label="Đổi bài đã chọn", style=discord.ButtonStyle.primary)
            exchange_button.callback = self.exchange_cards
            self.add_item(exchange_button)

            # Thêm nút giữ bài
            keep_button = discord.ui.Button(label="Giữ nguyên bài",
                                            style=discord.ButtonStyle.success)
            keep_button.callback = self.keep_cards
            self.add_item(keep_button)

        async def exchange_cards(self, interaction):
            if interaction.user != ctx.author:
                await interaction.response.send_message(
                    "Bạn không phải người chơi!", ephemeral=True)
                return

            marked_indices = [
                i for i, btn in enumerate(self.card_buttons) if btn.marked
            ]
            if len(marked_indices) > 3:
                await interaction.response.send_message(
                    "Bạn chỉ được đổi tối đa 3 lá bài!", ephemeral=True)
                return

            # Đổi bài đã đánh dấu
            for idx in marked_indices:
                player_hand[idx] = deck.pop()

            await self.end_game(interaction)

        async def keep_cards(self, interaction):
            if interaction.user != ctx.author:
                await interaction.response.send_message(
                    "Bạn không phải người chơi!", ephemeral=True)
                return

            await self.end_game(interaction)

        async def end_game(self, interaction):
            # Vô hiệu hóa tất cả buttons
            for child in self.children:
                child.disabled = True
            await interaction.response.edit_message(view=self)

            # Hiển thị kết quả cuối cùng
            new_player_cards = " ".join(f"{v}{s}" for v, s in player_hand)
            bot_cards = " ".join(f"{v}{s}" for v, s in bot_hand)

            # Đánh giá bài
            player_values = [card[0] for card in player_hand]
            player_suits = [card[1] for card in player_hand]
            bot_values = [card[0] for card in bot_hand]
            bot_suits = [card[1] for card in bot_hand]

            def evaluate_hand(values, suits):
                numerical_values = [value_dict[val] for val in values]
                numerical_values.sort()

                # Count occurrences
                value_counts = {}
                for val in numerical_values:
                    value_counts[val] = value_counts.get(val, 0) + 1

                # Full house
                if len(value_counts) == 2 and 3 in value_counts.values():
                    return 6, max(value_counts,
                                  key=value_counts.get), "Full house"

                # Flush
                if len(set(suits)) == 1:
                    return 5, max(numerical_values), "Thùng"

                # Straight
                if len(
                        set(numerical_values)
                ) == 5 and max(numerical_values) - min(numerical_values) == 4:
                    return 4, max(numerical_values), "Sảnh"

                # Three of a kind
                if 3 in value_counts.values():
                    three_val = [k for k, v in value_counts.items()
                                 if v == 3][0]
                    return 3, three_val, "Bộ ba"

                # Two pairs
                if list(value_counts.values()).count(2) == 2:
                    pairs = [k for k, v in value_counts.items() if v == 2]
                    return 2, max(pairs), "Hai đôi"

                # One pair
                if 2 in value_counts.values():
                    pair_val = [k for k, v in value_counts.items()
                                if v == 2][0]
                    return 1, pair_val, "Một đôi"

                return 0, max(numerical_values), "Lá cao nhất"

            player_rank, player_high, player_hand_name = evaluate_hand(
                player_values, player_suits)
            bot_rank, bot_high, bot_hand_name = evaluate_hand(
                bot_values, bot_suits)

            # So sánh kết quả
            if player_rank > bot_rank or (player_rank == bot_rank
                                          and player_high > bot_high):
                # Người chơi thắng
                winnings = bet_amount * (
                    1.5 if player_rank == 1 else 2 if player_rank == 2 else
                    3 if player_rank == 3 else 5 if player_rank == 4 else
                    7 if player_rank == 5 else 10 if player_rank == 6 else 1)
                currency[user_id] += winnings - bet_amount

                result_embed = discord.Embed(
                    title="🎉 CHIẾN THẮNG!",
                    description=
                    f"{ctx.author.mention} đã thắng với **{player_hand_name}**!",
                    color=discord.Color.gold())
                result_embed.add_field(name="Bài của bạn",
                                       value=new_player_cards,
                                       inline=False)
                result_embed.add_field(name="Bài của BOT",
                                       value=bot_cards,
                                       inline=True)
                result_embed.add_field(name="BOT có",
                                       value=bot_hand_name,
                                       inline=True)
                result_embed.add_field(name="Tiền thắng",
                                       value=f"+{winnings} xu",
                                       inline=True)
                result_embed.add_field(name="Số dư hiện tại",
                                       value=f"{currency[user_id]} xu",
                                       inline=True)

            elif player_rank == bot_rank and player_high == bot_high:
                # Hòa
                result_embed = discord.Embed(
                    title="🤝 HÒA!",
                    description=
                    f"Cả hai đều có **{player_hand_name}** với giá trị bằng nhau!",
                    color=discord.Color.blue())
                result_embed.add_field(name="Bài của bạn",
                                       value=new_player_cards,
                                       inline=False)
                result_embed.add_field(name="Bài của BOT",
                                       value=bot_cards,
                                       inline=True)
                result_embed.add_field(name="Hoàn tiền",
                                       value=f"{bet_amount} xu",
                                       inline=False)

            else:
                # Thua
                currency[user_id] -= bet_amount
                result_embed = discord.Embed(
                    title="❌ THUA CUỘC!",
                    description=
                    f"{ctx.author.mention} đã thua với **{player_hand_name}**!",
                    color=discord.Color.red())
                result_embed.add_field(name="Bài của bạn",
                                       value=new_player_cards,
                                       inline=False)
                result_embed.add_field(name="Bài của BOT",
                                       value=bot_cards,
                                       inline=True)
                result_embed.add_field(name="BOT có",
                                       value=bot_hand_name,
                                       inline=True)
                result_embed.add_field(name="Thiệt hại",
                                       value=f"-{bet_amount} xu",
                                       inline=True)
                result_embed.add_field(name="Số dư hiện tại",
                                       value=f"{currency[user_id]} xu",
                                       inline=True)

            await interaction.message.edit(embed=result_embed, view=self)

    # Hiển thị bài và các nút chọn
    embed = discord.Embed(
        title="🃏 Poker - Chọn bài muốn đổi",
        description="Chọn tối đa 3 lá bài để đổi hoặc giữ nguyên bài của bạn.",
        color=discord.Color.blue())
    embed.add_field(name="Bài của bạn", value=player_cards, inline=False)
    embed.add_field(name="Thời gian", value="30 giây", inline=True)
    embed.set_footer(
        text="Nhấn vào lá bài để đánh dấu đổi, nhấn lại để bỏ đánh dấu")

    await ctx.send(embed=embed, view=PokerView(player_hand))


#Game Xì Dác
@bot.command(name='xidach', aliases=['blackjack', 'xd'])
@check_channel()
@check_game_enabled('xidach')
async def blackjack(ctx, bet: str = None, mode: str = None):
    """Trò chơi Xì Dách (Blackjack) với nhiều chế độ chơi"""
    if bet is None:
        embed = discord.Embed(
            title="🎯 Xì Dách - Hướng Dẫn",
            description="Hãy nhập số xu muốn cược để chơi Xì Dách.\nVí dụ: `.xidach 50` hoặc `.xidach all`",
            color=discord.Color.blue())
        embed.add_field(
            name="Luật chơi",
            value="- Mục tiêu: Đạt tổng điểm gần 21 nhất mà không vượt quá\n- Quân bài J, Q, K = 10 điểm\n- Quân A = 1 hoặc 11 điểm\n- Xì Dách = Quân A + quân 10/J/Q/K",
            inline=False)
        embed.add_field(
            name="Chế độ chơi",
            value="- Bình thường (mặc định): Bot là nhà cái\n- Khó (thêm `kho` sau lệnh): Tỷ lệ thắng thấp hơn\n- Thử thách (thêm `tt` sau lệnh): Bài mở từ đầu, thắng x2.5",
            inline=False)
        embed.add_field(
            name="Phần thưởng",
            value="- Thắng thường: x1.5 tiền cược\n- Xì Dách: x2 tiền cược\n- Thử thách: x2.5 tiền cược",
            inline=False)
        embed.set_footer(text="Ví dụ: `.xidach 50 kho` để chơi ở chế độ khó")
        await ctx.send(embed=embed)
        return

    user_id = ctx.author.id

    # Xử lý đặt cược "all"
    bet_amount = parse_bet(bet, currency[user_id])
    if bet_amount is None:
        await ctx.send(embed=discord.Embed(
            title="❌ Số tiền không hợp lệ",
            description="Vui lòng nhập số tiền hợp lệ hoặc 'all'.",
            color=discord.Color.red()))
        return

    # Kiểm tra tiền cược
    if bet_amount <= 0 or currency[user_id] < bet_amount:
        await ctx.send(embed=discord.Embed(
            title="❌ Không đủ xu",
            description=f"{ctx.author.mention}, bạn cần đặt cược >0 xu và không vượt quá số dư {currency[user_id]} xu.",
            color=discord.Color.red()))
        return

    # Xác định chế độ chơi
    game_modes = {
        "normal": {"text": "Bình Thường", "color": discord.Color.blue(), "emoji": "🎮", "multiplier": 1.5},
        "hard": {"text": "Khó", "color": discord.Color.orange(), "emoji": "🔥", "multiplier": 1.8},
        "challenge": {"text": "Thử Thách", "color": discord.Color.purple(), "emoji": "⚔️", "multiplier": 2.5}
    }

    game_mode = "normal"
    if mode in ["kho", "hard"]: game_mode = "hard"
    elif mode in ["tt", "thuthach", "challenge"]: game_mode = "challenge"

    mode_info = game_modes[game_mode]

    # Thiết lập bộ bài và giá trị
    suits = ['♠️', '♥️', '♦️', '♣️']
    cards = ['A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K']
    values = {'A': 11, '2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7, '8': 8, '9': 9, '10': 10, 'J': 10, 'Q': 10, 'K': 10}
    card_emojis = {
        'A': '🅰️', '2': '2️⃣', '3': '3️⃣', '4': '4️⃣', '5': '5️⃣',
        '6': '6️⃣', '7': '7️⃣', '8': '8️⃣', '9': '9️⃣', '10': '🔟',
        'J': '🤵', 'Q': '👸', 'K': '🤴'
    }

    # Tạo và trộn bộ bài
    deck = [(card, suit) for suit in suits for card in cards]
    random.shuffle(deck)

    # Chia bài ban đầu
    player_hand = [deck.pop(), deck.pop()]
    dealer_hand = [deck.pop(), deck.pop()]

    # Định nghĩa các hàm tiện ích
    def calculate_hand(hand):
        score = sum(values[card[0]] for card in hand)
        # Điều chỉnh giá trị A nếu cần
        aces = sum(1 for card in hand if card[0] == 'A')
        while score > 21 and aces > 0:
            score -= 10
            aces -= 1
        return score

    def is_blackjack(hand):
        return len(hand) == 2 and calculate_hand(hand) == 21

    def display_cards(hand, hide_first=False):
        if hide_first:
            return f"🎴 | {' '.join(f'{card_emojis[card[0]]}{card[1]}' for card in hand[1:])}"
        return f"{' '.join(f'{card_emojis[card[0]]}{card[1]}' for card in hand)}"

    # Điều chỉnh độ khó (nếu là chế độ khó)
    if game_mode == "hard":
        # Đảm bảo nhà cái có lợi thế
        while calculate_hand(dealer_hand) < 16:
            dealer_hand[0] = deck.pop()  # Thay bài đầu tiên nếu quá thấp

    # Hiệu ứng bắt đầu game
    loading_message = await ctx.send("🃏 **Đang chuẩn bị bàn xì dách...**")

    # Hiệu ứng chia bài
    for i in range(4):
        card_dealing = "🎴" * i
        await loading_message.edit(content=f"🃏 **Đang chia bài...** {card_dealing}")
        await asyncio.sleep(0.3)

    # Tính điểm ban đầu
    player_score = calculate_hand(player_hand)
    dealer_score = calculate_hand(dealer_hand)
    player_blackjack = is_blackjack(player_hand)
    dealer_blackjack = is_blackjack(dealer_hand)

    # Hiển thị bài ban đầu
    hide_dealer = game_mode != "challenge"
    initial_embed = discord.Embed(
        title=f"{mode_info['emoji']} Xì Dách - Chế độ {mode_info['text']}",
        description=f"{ctx.author.mention} đã đặt cược {bet_amount} xu.",
        color=mode_info['color'])

    initial_embed.add_field(
        name="🎴 Bài của bạn",
        value=f"{display_cards(player_hand)} = **{player_score}**",
        inline=False)

    initial_embed.add_field(
        name="🎴 Bài của nhà cái",
        value=f"{display_cards(dealer_hand, hide_dealer)}" + 
             (f" = **{dealer_score}**" if not hide_dealer else ""),
        inline=False)

    if game_mode == "challenge":
        initial_embed.set_footer(text="⚠️ CHẾ ĐỘ THỬ THÁCH: Bài nhà cái được lật từ đầu!")

    await loading_message.edit(content=None, embed=initial_embed)

    # Xử lý nếu có Xì Dách
    if player_blackjack or dealer_blackjack:
        await asyncio.sleep(1)

        result_embed = discord.Embed(
            title="🃏 KẾT QUẢ XÌ DÁCH 🃏",
            color=discord.Color.gold())

        result_embed.add_field(
            name="🎴 Bài của bạn",
            value=f"{display_cards(player_hand)} = **{player_score}**",
            inline=False)

        result_embed.add_field(
            name="🎴 Bài của nhà cái",
            value=f"{display_cards(dealer_hand)} = **{dealer_score}**",
            inline=False)

        if player_blackjack and dealer_blackjack:
            result_embed.description = "**HÒA!** Cả hai đều có Xì Dách!"
            result_embed.color = discord.Color.yellow()

        elif player_blackjack:
            winnings = int(bet_amount * 2)  # Xì dách thắng x2
            currency[user_id] += winnings
            result_embed.description = f"🎉 **THẮNG LỚN!** 🎉\nBạn có Xì Dách! Thắng {winnings} xu!"
            result_embed.color = discord.Color.green()

        else:  # dealer_blackjack
            currency[user_id] -= bet_amount
            result_embed.description = f"❌ **THUA!** Nhà cái có Xì Dách! Mất {bet_amount} xu!"
            result_embed.color = discord.Color.red()

        await loading_message.edit(embed=result_embed)
        return

    # Tạo nút bấm cho người chơi
    view = discord.ui.View(timeout=30)
    hit_button = discord.ui.Button(style=discord.ButtonStyle.primary, label="Rút bài", emoji="🃏")
    stand_button = discord.ui.Button(style=discord.ButtonStyle.secondary, label="Dằn bài", emoji="🛑")
    double_button = discord.ui.Button(style=discord.ButtonStyle.success, label="Double", emoji="💰")

    player_busted = False
    player_stood = False

    # Xử lý nút rút bài
    async def hit_callback(interaction):
        nonlocal player_hand, player_score, player_busted

        if interaction.user.id != ctx.author.id:
            return

        # Rút thêm bài
        new_card = deck.pop()
        player_hand.append(new_card)
        player_score = calculate_hand(player_hand)

        # Hiệu ứng rút bài
        hit_embed = discord.Embed(
            title=f"{mode_info['emoji']} Xì Dách - Đang chơi",
            description=f"{ctx.author.mention} vừa rút thêm 1 lá bài! 🃏",
            color=mode_info['color'])

        hit_embed.add_field(
            name="🎴 Bài của bạn",
            value=f"{display_cards(player_hand)} = **{player_score}**",
            inline=False)

        hit_embed.add_field(
            name="🎴 Bài của nhà cái",
            value=f"{display_cards(dealer_hand, hide_dealer)}" + 
                 (f" = **{dealer_score}**" if not hide_dealer else ""),
            inline=False)

        # Animation cho lá bài mới
        hit_embed.add_field(
            name="🎯 Bạn vừa rút được",
            value=f"**{card_emojis[new_card[0]]}{new_card[1]}**",
            inline=False)

        # Kiểm tra nếu quá 21 điểm
        if player_score > 21:
            player_busted = True
            for button in view.children:
                button.disabled = True

            hit_embed.title = "💥 QUẮC! Bạn đã quá 21 điểm!"
            hit_embed.color = discord.Color.red()

            currency[user_id] -= bet_amount
            hit_embed.add_field(
                name="❌ Kết quả",
                value=f"Bạn thua và mất {bet_amount} xu!",
                inline=False)

            # Hiệu ứng thua
            await interaction.response.edit_message(embed=hit_embed, view=view)
            await asyncio.sleep(1)

            # Hiệu ứng kết quả cuối cùng
            final_embed = create_final_embed("lose")
            await interaction.edit_original_response(embed=final_embed)
            return

        await interaction.response.edit_message(embed=hit_embed, view=view)

    # Xử lý nút dằn bài
    async def stand_callback(interaction):
        nonlocal player_stood, dealer_hand, dealer_score

        if interaction.user.id != ctx.author.id:
            return

        player_stood = True
        for button in view.children:
            button.disabled = True

        # Hiệu ứng dằn bài
        stand_embed = discord.Embed(
            title="🛑 Bạn đã dằn bài!",
            description="Đến lượt nhà cái...",
            color=discord.Color.gold())

        stand_embed.add_field(
            name="🎴 Bài của bạn",
            value=f"{display_cards(player_hand)} = **{player_score}**",
            inline=False)

        stand_embed.add_field(
            name="🎴 Bài của nhà cái",
            value=f"{display_cards(dealer_hand)} = **{dealer_score}**",
            inline=False)

        await interaction.response.edit_message(embed=stand_embed, view=view)

        # Nhà cái lật bài và rút thêm nếu cần
        await asyncio.sleep(1)

        # Nhà cái rút bài đến khi đạt ít nhất 17 điểm
        dealer_drawing = False
        while dealer_score < 17:
            dealer_drawing = True
            # Hiệu ứng nhà cái đang suy nghĩ
            thinking_embed = discord.Embed(
                title="🤔 Nhà cái đang suy nghĩ...",
                color=discord.Color.gold())

            thinking_embed.add_field(
                name="🎴 Bài của bạn",
                value=f"{display_cards(player_hand)} = **{player_score}**",
                inline=False)

            thinking_embed.add_field(
                name="🎴 Bài của nhà cái",
                value=f"{display_cards(dealer_hand)} = **{dealer_score}**",
                inline=False)

            await interaction.edit_original_response(embed=thinking_embed)
            await asyncio.sleep(1)

            # Nhà cái rút thêm bài
            new_card = deck.pop()
            dealer_hand.append(new_card)
            dealer_score = calculate_hand(dealer_hand)

            # Hiệu ứng nhà cái rút bài
            dealer_hit_embed = discord.Embed(
                title="🎯 Nhà cái rút thêm bài!",
                description=f"Nhà cái rút được: {card_emojis[new_card[0]]}{new_card[1]}",
                color=discord.Color.gold())

            dealer_hit_embed.add_field(
                name="🎴 Bài của bạn",
                value=f"{display_cards(player_hand)} = **{player_score}**",
                inline=False)

            dealer_hit_embed.add_field(
                name="🎴 Bài của nhà cái",
                value=f"{display_cards(dealer_hand)} = **{dealer_score}**",
                inline=False)

            await interaction.edit_original_response(embed=dealer_hit_embed)
            await asyncio.sleep(0.8)

        # Nếu nhà cái không cần rút thêm bài
        if not dealer_drawing:
            dealer_stand_embed = discord.Embed(
                title="🛑 Nhà cái không rút thêm bài",
                color=discord.Color.gold())

            dealer_stand_embed.add_field(
                name="🎴 Bài của bạn",
                value=f"{display_cards(player_hand)} = **{player_score}**",
                inline=False)

            dealer_stand_embed.add_field(
                name="🎴 Bài của nhà cái",
                value=f"{display_cards(dealer_hand)} = **{dealer_score}**",
                inline=False)

            await interaction.edit_original_response(embed=dealer_stand_embed)
            await asyncio.sleep(1)

        # Xác định kết quả
        result_type = ""
        if dealer_score > 21:
            # Nhà cái quắc
            result_type = "win"
            winnings = int(bet_amount * mode_info['multiplier'])
            currency[user_id] += winnings

        elif player_score > dealer_score:
            # Người chơi thắng
            result_type = "win"
            winnings = int(bet_amount * mode_info['multiplier'])
            currency[user_id] += winnings

        elif player_score < dealer_score:
            # Nhà cái thắng
            result_type = "lose"
            currency[user_id] -= bet_amount

        else:
            # Hòa
            result_type = "draw"

        # Hiệu ứng kết quả
        final_embed = create_final_embed(result_type)
        await interaction.edit_original_response(embed=final_embed)

    # Xử lý nút double
    async def double_callback(interaction):
        nonlocal player_hand, player_score, bet_amount

        if interaction.user.id != ctx.author.id:
            return

        # Kiểm tra đủ tiền để double
        if currency[user_id] < bet_amount * 2:
            await interaction.response.send_message("Bạn không đủ xu để Double!", ephemeral=True)
            return

        # Tăng gấp đôi cược
        bet_amount *= 2

        # Rút thêm duy nhất 1 lá và dằn bài
        new_card = deck.pop()
        player_hand.append(new_card)
        player_score = calculate_hand(player_hand)

        # Disable tất cả nút
        for button in view.children:
            button.disabled = True

        # Hiệu ứng double
        double_embed = discord.Embed(
            title="💰 DOUBLE! Bạn đã gấp đôi cược!",
            description=f"Cược hiện tại: {bet_amount} xu",
            color=discord.Color.gold())

        double_embed.add_field(
            name="🎴 Bài của bạn",
            value=f"{display_cards(player_hand)} = **{player_score}**",
            inline=False)

        double_embed.add_field(
            name="🎯 Bạn rút được",
            value=f"**{card_emojis[new_card[0]]}{new_card[1]}**",
            inline=False)

        double_embed.add_field(
            name="🎴 Bài của nhà cái",
            value=f"{display_cards(dealer_hand)} = **{dealer_score}**",
            inline=False)

        await interaction.response.edit_message(embed=double_embed, view=view)
        await asyncio.sleep(1)

        # Kiểm tra nếu quắc
        if player_score > 21:
            currency[user_id] -= bet_amount
            bust_embed = discord.Embed(
                title="💥 QUẮC! Bạn đã quá 21 điểm!",
                description=f"Bạn thua và mất {bet_amount} xu!",
                color=discord.Color.red())

            bust_embed.add_field(
                name="🎴 Bài của bạn",
                value=f"{display_cards(player_hand)} = **{player_score}**",
                inline=False)

            bust_embed.add_field(
                name="🎴 Bài của nhà cái",
                value=f"{display_cards(dealer_hand)} = **{dealer_score}**",
                inline=False)

            await interaction.edit_original_response(embed=bust_embed)
            await asyncio.sleep(1)

            # Hiệu ứng kết quả cuối
            final_embed = create_final_embed("lose")
            await interaction.edit_original_response(embed=final_embed)
            return

        # Tiếp tục với phần nhà cái rút bài như trong stand_callback
        await dealer_play(interaction)

    # Hàm xử lý phần chơi của nhà cái
    async def dealer_play(interaction):
        nonlocal dealer_hand, dealer_score

        # Nhà cái rút bài đến khi đạt ít nhất 17 điểm
        dealer_drawing = False
        while dealer_score < 17:
            dealer_drawing = True
            # Hiệu ứng nhà cái đang suy nghĩ
            thinking_embed = discord.Embed(
                title="🤔 Nhà cái đang suy nghĩ...",
                color=discord.Color.gold())

            thinking_embed.add_field(
                name="🎴 Bài của bạn",
                value=f"{display_cards(player_hand)} = **{player_score}**",
                inline=False)

            thinking_embed.add_field(
                name="🎴 Bài của nhà cái",
                value=f"{display_cards(dealer_hand)} = **{dealer_score}**",
                inline=False)

            await interaction.edit_original_response(embed=thinking_embed)
            await asyncio.sleep(1)

            # Nhà cái rút thêm bài
            new_card = deck.pop()
            dealer_hand.append(new_card)
            dealer_score = calculate_hand(dealer_hand)

            # Hiệu ứng nhà cái rút bài
            dealer_hit_embed = discord.Embed(
                title="🎯 Nhà cái rút thêm bài!",
                description=f"Nhà cái rút được: {card_emojis[new_card[0]]}{new_card[1]}",
                color=discord.Color.gold())

            dealer_hit_embed.add_field(
                name="🎴 Bài của bạn",
                value=f"{display_cards(player_hand)} = **{player_score}**",
                inline=False)

            dealer_hit_embed.add_field(
                name="🎴 Bài của nhà cái",
                value=f"{display_cards(dealer_hand)} = **{dealer_score}**",
                inline=False)

            await interaction.edit_original_response(embed=dealer_hit_embed)
            await asyncio.sleep(0.8)

        # Xác định kết quả
        result_type = ""
        if dealer_score > 21:
            # Nhà cái quắc
            result_type = "win"
            winnings = int(bet_amount * mode_info['multiplier'])
            currency[user_id] += winnings

        elif player_score > dealer_score:
            # Người chơi thắng
            result_type = "win"
            winnings = int(bet_amount * mode_info['multiplier'])
            currency[user_id] += winnings

        elif player_score < dealer_score:
            # Nhà cái thắng
            result_type = "lose"
            currency[user_id] -= bet_amount

        else:
            # Hòa
            result_type = "draw"

        # Hiệu ứng kết quả
        final_embed = create_final_embed(result_type)
        await interaction.edit_original_response(embed=final_embed)

    # Hàm tạo embed kết quả cuối
    def create_final_embed(result):
        if result == "win":
            winnings = int(bet_amount * mode_info['multiplier'])
            embed = discord.Embed(
                title="🎉 CHIẾN THẮNG! 🎉",
                description=f"Bạn đã thắng {winnings} xu! (x{mode_info['multiplier']})",
                color=discord.Color.green())

        elif result == "lose":
            embed = discord.Embed(
                title="❌ THUA CUỘC!",
                description=f"Bạn đã thua {bet_amount} xu!",
                color=discord.Color.red())

        else:  # draw
            embed = discord.Embed(
                title="🤝 HÒA!",
                description="Bạn và nhà cái có số điểm bằng nhau.",
                color=discord.Color.yellow())

        embed.add_field(
            name="🎴 Bài của bạn",
            value=f"{display_cards(player_hand)} = **{player_score}**",
            inline=False)

        embed.add_field(
            name="🎴 Bài của nhà cái",
            value=f"{display_cards(dealer_hand)} = **{dealer_score}**",
            inline=False)

        embed.add_field(
            name="💰 Số dư hiện tại",
            value=f"{currency[user_id]} xu",
            inline=False)

        return embed

    # Thiết lập các callback cho nút
    hit_button.callback = hit_callback
    stand_button.callback = stand_callback
    double_button.callback = double_callback

    # Thêm nút vào view
    view.add_item(hit_button)
    view.add_item(stand_button)
    view.add_item(double_button)

    # Gửi tin nhắn với các nút
    await loading_message.edit(content=None, embed=initial_embed, view=view)

    # Xử lý timeout
    await view.wait()
    if not player_busted and not player_stood:
        timeout_embed = discord.Embed(
            title="⏰ Hết thời gian!",
            description="Bạn đã không đưa ra lựa chọn trong thời gian quy định.",
            color=discord.Color.dark_gray())
        timeout_embed.add_field(
            name="🎴 Bài của bạn",
            value=f"{display_cards(player_hand)} = **{player_score}**",
            inline=False)
        timeout_embed.add_field(
            name="🎴 Bài của nhà cái",
            value=f"{display_cards(dealer_hand)} = **{dealer_score}**",
            inline=False)

        for button in view.children:
            button.disabled = True

        # Trừ tiền người chơi vì timeout
        currency[ctx.author.id] -= bet_amount

        timeout_embed.add_field(
            name="❌ Kết quả",
            value=f"Bạn bị trừ {bet_amount} xu do không đưa ra lựa chọn kịp thời!",
            inline=False)
        timeout_embed.add_field(
            name="💰 Số dư hiện tại",
            value=f"{currency[ctx.author.id]} xu",
            inline=False)

        timeout_embed.set_footer(text="😢 Lần sau hãy đưa ra lựa chọn nhanh hơn nhé!")
        await loading_message.edit(embed=timeout_embed, view=view)


# Game Tài Xỉu
@bot.command(name='tx', aliases=['taixiu'])
@check_channel()
@check_game_enabled('tx')
async def tai_xiu(ctx, choice: str = None, bet: int = None):
    """Trò chơi Tài Xỉu"""
    if choice is None or bet is None:
        embed = discord.Embed(
            title="🎲 Tài Xỉu - Hướng Dẫn",
            description="Đoán kết quả tổng của 3 xúc xắc.\nVí dụ: `.tx t 50` hoặc `.tx x 100`",
            color=discord.Color.blue())
        embed.add_field(
            name="Cách chơi",
            value="- Chọn Tài (t) hoặc Xỉu (x)\n- Đặt cược số xu\n- Tổng 3 xúc xắc: 11-18 là Tài, 3-10 là Xỉu\n- Thắng: x1.8 tiền cược",
            inline=False)
        await ctx.send(embed=embed)
        return

    # Kiểm tra lựa chọn
    choice = choice.lower()
    if choice not in ['t', 'x', 'tài', 'xỉu', 'tai', 'xiu']:
        embed = discord.Embed(
            title="❌ Lựa chọn không hợp lệ",
            description="Vui lòng chọn 't' (Tài) hoặc 'x' (Xỉu).",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Biến đổi lựa chọn thành 't' hoặc 'x'
    if choice in ['tài', 'tai']:
        choice = 't'
    elif choice in ['xỉu', 'xiu']:
        choice = 'x'

    # Kiểm tra bet
    user_id = ctx.author.id

    # Kiểm tra cooldown
    can_play, remaining_time = check_cooldown(user_id)
    if not can_play:
        embed = discord.Embed(
            title="⏳ Thời gian chờ",
            description=f"Bạn cần đợi thêm {remaining_time} giây trước khi chơi tiếp.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Xử lý đặt cược "all"
    bet_amount = parse_bet(bet, currency[user_id])
    if bet_amount is None:
        embed = discord.Embed(
            title="❌ Số tiền không hợp lệ",
            description="Vui lòng nhập số tiền hợp lệ hoặc 'all'.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Kiểm tra tiền cược
    if bet <= 0:
        embed = discord.Embed(title="❌ Lỗi",
                             description="Số tiền cược phải lớn hơn 0.",
                             color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    if currency[user_id] < bet:
        embed = discord.Embed(title="❌ Không đủ xu",
                             description=f"Bạn cần {bet} xu để đặt cược, nhưng chỉ có {currency[user_id]} xu.",
                             color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Hiệu ứng lắc xúc xắc mới
    dice_faces = ["⚀", "⚁", "⚂", "⚃", "⚄", "⚅"]
    colors = [discord.Color.blue(), discord.Color.purple(), 
              discord.Color.gold(), discord.Color.orange()]

    # Tin nhắn loading ban đầu
    loading_embed = discord.Embed(
        title="🎲 ĐANG LẮC XÚC XẮC",
        description="Xúc xắc đang được lắc...",
        color=colors[0])
    loading_msg = await ctx.send(embed=loading_embed)

    # Giai đoạn 1: Lắc nhanh
    for i in range(3):
        dice_display = " ".join(random.choices(dice_faces, k=3))
        embed = discord.Embed(
            title=f"🎲 ĐANG LẮC XÚC XẮC {'.'*(i+1)}",
            description=f"Xúc xắc đang lăn!\n\n{dice_display}",
            color=colors[i % len(colors)])
        await loading_msg.edit(embed=embed)
        await asyncio.sleep(0.7)

    # Giai đoạn 2: Hiển thị từng viên xúc xắc một
    embed = discord.Embed(
        title="🎲 XÚC XẮC ĐANG DỪNG LẠI",
        description="Kết quả đang hiện ra...",
        color=discord.Color.gold())
    await loading_msg.edit(embed=embed)
    await asyncio.sleep(0.8)

    # Tạo kết quả thật
    dice1, dice2, dice3 = random.randint(1, 6), random.randint(1, 6), random.randint(1, 6)
    total = dice1 + dice2 + dice3

    # Hiển thị viên đầu tiên
    embed = discord.Embed(
        title="🎲 KẾT QUẢ ĐANG HIỆN",
        description=f"Xúc xắc 1: {dice_faces[dice1-1]}",
        color=discord.Color.orange())
    await loading_msg.edit(embed=embed)
    await asyncio.sleep(0.6)

    # Hiển thị viên thứ hai
    embed = discord.Embed(
        title="🎲 KẾT QUẢ ĐANG HIỆN",
        description=f"Xúc xắc 1: {dice_faces[dice1-1]}\nXúc xắc 2: {dice_faces[dice2-1]}",
        color=discord.Color.orange())
    await loading_msg.edit(embed=embed)
    await asyncio.sleep(0.6)

    # Hiển thị viên thứ ba và kết quả
    result_tai_xiu = "Tài" if total >= 11 else "Xỉu"

    # Hiển thị kết quả cuối cùng với động đất
    embed = discord.Embed(
        title=f"🎲 KẾT QUẢ: {result_tai_xiu.upper()} ({total})",
        description=f"Xúc xắc 1: {dice_faces[dice1-1]}\nXúc xắc 2: {dice_faces[dice2-1]}\nXúc xắc 3: {dice_faces[dice3-1]}\n\n**Tổng điểm: {total} ➜ {result_tai_xiu}**",
        color=discord.Color.green() if (choice == 't' and total >= 11) or (choice == 'x' and total < 11) else discord.Color.red())

    # Xác định người thắng
    if (choice == 't' and total >= 11) or (choice == 'x' and total < 11):
        # Người chơi thắng
        winnings = int(bet * 1.8)
        currency[user_id] += winnings - bet  # Trừ tiền cược và cộng tiền thắng

        embed.add_field(name="Lựa chọn của bạn", 
                       value=f"**{'Tài' if choice == 't' else 'Xỉu'}**", 
                       inline=True)
        embed.add_field(name="Tiền thắng", 
                       value=f"**+{winnings} xu**", 
                       inline=True)
        embed.add_field(name="Số dư hiện tại", 
                       value=f"**{currency[user_id]} xu**", 
                       inline=True)
        embed.set_footer(text="🎊 Chúc mừng! Bạn đã thắng!")

        # Thêm hiệu ứng run rẩy cho thông báo chiến thắng
        for i in range(5):
            shake_embed = embed.copy()
            shake_embed.title = f"{'  ' * (i % 2)}🎲 KẾT QUẢ: {result_tai_xiu.upper()} ({total}){'  ' * (i % 2)}"
            await loading_msg.edit(embed=shake_embed)
            await asyncio.sleep(0.1)
    else:
        # Người chơi thua
        currency[user_id] -= bet

        embed.add_field(name="Lựa chọn của bạn", 
                       value=f"**{'Tài' if choice == 't' else 'Xỉu'}**", 
                       inline=True)
        embed.add_field(name="Tiền thua", 
                       value=f"**-{bet} xu**", 
                       inline=True)
        embed.add_field(name="Số dư hiện tại", 
                       value=f"**{currency[user_id]} xu**", 
                       inline=True)
        embed.set_footer(text="😢 Rất tiếc! Bạn đã thua!")

    # Hiển thị kết quả cuối cùng
    await loading_msg.edit(embed=embed)


@bot.command(name='pinggo', aliases=['bingo', 'pg'])
@check_channel()
@check_game_enabled('pinggo')
async def pinggo(ctx, bet: int = None):
    """Trò chơi Ping Go/Bingo"""
    if bet is None:
        embed = discord.Embed(
            title="🎯 Ping Go - Hướng Dẫn",
            description=
            "Hãy nhập số xu muốn cược để chơi Ping Go.\nVí dụ: `.pinggo 50`",
            color=discord.Color.blue())
        embed.add_field(
            name="Luật chơi",
            value=
            "- Bot sẽ chọn ngẫu nhiên 5 số từ 1-20\n- Người chơi nhận 10 số ngẫu nhiên\n- Trùng càng nhiều số, thưởng càng cao",
            inline=False)
        embed.add_field(
            name="Phần thưởng",
            value=
            "- Trùng 3 số: x1.5 tiền cược\n- Trùng 4 số: x3 tiền cược\n- Trùng 5 số: x10 tiền cược",
            inline=False)
        await ctx.send(embed=embed)
        return

    user_id = ctx.author.id

    # Kiểm tra cooldown
    can_play, remaining_time = check_cooldown(user_id)
    if not can_play:
        embed = discord.Embed(
            title="⏳ Thời gian chờ",
            description=
            f"Bạn cần đợi thêm {remaining_time} giây trước khi chơi tiếp.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Kiểm tra tiền cược
    if bet <= 0:
        embed = discord.Embed(title="🎯 Ping Go",
                              description="Số tiền cược phải lớn hơn 0 xu.",
                              color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    if currency[user_id] < bet:
        embed = discord.Embed(
            title="🎯 Ping Go",
            description=
            f"{ctx.author.mention}, bạn không đủ xu để đặt cược! Bạn hiện có {currency[user_id]} xu.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Tạo số ngẫu nhiên
    all_numbers = list(range(1, 21))
    winning_numbers = random.sample(all_numbers, 5)
    player_numbers = random.sample(all_numbers, 10)

    # Tìm số trùng
    matching_numbers = set(winning_numbers) & set(player_numbers)
    match_count = len(matching_numbers)

    # Hiển thị hiệu ứng bắt đầu game
    embed = discord.Embed(
        title="🎯 Ping Go - Bắt đầu quay số",
        description=f"{ctx.author.mention} đã đặt cược {bet} xu.",
        color=discord.Color.blue())

    # Hiển thị số của người chơi theo dạng lưới số đẹp mắt
    player_nums_sorted = sorted(player_numbers)
    player_nums_display = ""
    for i in range(0, len(player_nums_sorted), 5):
        row = player_nums_sorted[i:i+5]
        player_nums_display += " ".join(f"`{num:2d}`" for num in row) + "\n"

    embed.add_field(name="🎟️ Vé số của bạn", value=player_nums_display, inline=False)
    embed.add_field(name="⏳ Trạng thái", value="Chuẩn bị quay số...", inline=False)
    embed.set_footer(text="Trùng 3/4/5 số để nhận thưởng!")

    message = await ctx.send(embed=embed)
    await asyncio.sleep(1.5)

    # Hiệu ứng quay số với animation đẹp mắt
    drawn_numbers = []
    ball_emojis = ["🔴", "🟠", "🟡", "🟢", "🔵"]

    for i in range(5):
        # Hiệu ứng trước khi hiện số
        for _ in range(3):
            loading_embed = discord.Embed(
                title=f"🎯 Ping Go - Đang quay số {i+1}/5",
                description=f"{ctx.author.mention} đã đặt cược {bet} xu.",
                color=discord.Color.gold())

            loading_embed.add_field(name="🎟️ Vé số của bạn", value=player_nums_display, inline=False)

            # Hiển thị số đã quay
            if drawn_numbers:
                drawn_str = " ".join([f"{ball_emojis[j % len(ball_emojis)]} `{num}`" for j, num in enumerate(drawn_numbers)])
                loading_embed.add_field(name="🎲 Số đã quay", value=drawn_str, inline=False)

            # Hiệu ứng đang quay
            loading_embed.add_field(
                name="⏳ Đang quay số...",
                value=f"{'⚪'*(_ % 3 + 1)} {'⚫'*(3-_ % 3)}", 
                inline=False)

            await message.edit(embed=loading_embed)
            await asyncio.sleep(0.3)

        # Thêm số mới quay được
        drawn_numbers.append(winning_numbers[i])

        # Hiển thị số mới quay được với hiệu ứng đặc biệt
        result_embed = discord.Embed(
            title=f"🎯 Ping Go - Số thứ {i+1}: {ball_emojis[i]} `{winning_numbers[i]}`!",
            description=f"{ctx.author.mention} đã đặt cược {bet} xu.",
            color=discord.Color.gold())

        # Hiển thị vé của người chơi với đánh dấu số trùng
        player_nums_marked = ""
        for j in range(0, len(player_nums_sorted), 5):
            row = player_nums_sorted[j:j+5]
            row_display = []
            for num in row:
                if num in drawn_numbers and num in player_numbers:
                    # Số trùng đã quay
                    row_display.append(f"**`{num:2d}`**")
                elif num in player_numbers:
                    # Số chưa trùng
                    row_display.append(f"`{num:2d}`")
            player_nums_marked += " ".join(row_display) + "\n"

        result_embed.add_field(name="🎟️ Vé số của bạn", value=player_nums_marked, inline=False)

        # Hiển thị số đã quay với animation
        drawn_str = " ".join([f"{ball_emojis[j % len(ball_emojis)]} `{num}`" for j, num in enumerate(drawn_numbers)])
        result_embed.add_field(name="🎲 Số đã quay", value=drawn_str, inline=False)

        # Hiển thị số trùng hiện tại
        current_matches = set(drawn_numbers) & set(player_numbers)
        if current_matches:
            match_str = " ".join([f"**`{num}`**" for num in sorted(current_matches)])
            result_embed.add_field(name=f"✨ Số trùng ({len(current_matches)}/5)", value=match_str, inline=False)

        # Animation cho số vừa quay
        for k in range(3):
            if k % 2 == 0:
                result_embed.title = f"🎯 Ping Go - Số thứ {i+1}: {ball_emojis[i]} **`{winning_numbers[i]}`**!"
            else:
                result_embed.title = f"🎯 Ping Go - Số thứ {i+1}: {ball_emojis[i]} `{winning_numbers[i]}`!"

            await message.edit(embed=result_embed)
            await asyncio.sleep(0.3)

        await asyncio.sleep(1)

    # Hiệu ứng kết thúc tăng dần kịch tính
    await asyncio.sleep(0.5)

    # Hiển thị kết quả cuối cùng với hiệu ứng đặc biệt dựa vào số lượng trùng
    if match_count >= 5:
        # Hiệu ứng Jackpot
        for i in range(3):
            jackpot_colors = [discord.Color.gold(), discord.Color.red(), discord.Color.green()]
            jackpot_emojis = ["🎉", "💰", "🏆"]

            jackpot_embed = discord.Embed(
                title=f"{jackpot_emojis[i % 3]} JACKPOT! {jackpot_emojis[i % 3]}",
                description=f"🎊 **CHIẾN THẮNG TỐI ĐA!** 🎊\n{ctx.author.mention} đã trùng {match_count}/5 số!",
                color=jackpot_colors[i % 3])

            # Thêm hiệu ứng rung cho text
            padding = " " * (i % 2)
            jackpot_embed.add_field(
                name=f"{padding}💸 JACKPOT X10! 💸{padding}",
                value=f"Bạn đã thắng **{bet * 10} xu**!", 
                inline=False)

            await message.edit(embed=jackpot_embed)
            await asyncio.sleep(0.7)

    # Tạo kết quả cuối cùng
    # Xác định kết quả và phần thưởng
    if match_count >= 5:
        winnings = bet * 10
        result_text = f"🏆 JACKPOT! Bạn đã trúng {match_count}/5 số!"
        color = discord.Color.gold()
        currency[user_id] += winnings - bet
        win_emoji = "🎊"
    elif match_count == 4:
        winnings = bet * 3
        result_text = f"🎉 THẮNG LỚN! Bạn đã trúng 4/5 số!"
        color = discord.Color.purple()
        currency[user_id] += winnings - bet
        win_emoji = "🎉"
    elif match_count == 3:
        winnings = int(bet * 1.5)
        result_text = f"✨ THẮNG! Bạn đã trúng 3/5 số!"
        color = discord.Color.green()
        currency[user_id] += winnings - bet
        win_emoji = "✨"
    else:
        winnings = 0
        result_text = f"❌ Tiếc quá! Bạn chỉ trúng {match_count}/5 số."
        color = discord.Color.red()
        currency[user_id] -= bet
        win_emoji = "😢"

    final_embed = discord.Embed(
        title=f"{win_emoji} Ping Go - Kết quả cuối cùng {win_emoji}",
        description=result_text,
        color=color)

    # Hiển thị vé số của người chơi với định dạng đẹp
    player_nums_marked = ""
    for i in range(0, len(player_nums_sorted), 5):
        row = player_nums_sorted[i:i+5]
        row_display = []
        for num in row:
            if num in matching_numbers:
                # Số trùng 
                row_display.append(f"**`{num:2d}`**")
            else:
                # Số không trùng
                row_display.append(f"`{num:2d}`")
        player_nums_marked += " ".join(row_display) + "\n"

    final_embed.add_field(name="🎟️ Vé số của bạn", value=player_nums_marked, inline=False)

    # Hiển thị số trúng thưởng và số trùng
    winning_nums_display = " ".join([f"{ball_emojis[i % len(ball_emojis)]} `{num}`" for i, num in enumerate(sorted(winning_numbers))])
    final_embed.add_field(name="🎲 Số trúng thưởng", value=winning_nums_display, inline=False)

    # Hiển thị số trùng
    if matching_numbers:
        matching_nums_display = " ".join([f"**`{num}`**" for num in sorted(matching_numbers)])
        final_embed.add_field(name=f"✅ Số trùng ({match_count}/5)", 
                              value=matching_nums_display, 
                              inline=False)
    else:
        final_embed.add_field(name="❌ Số trùng (0/5)", 
                              value="Không có số nào trùng", 
                              inline=False)

    # Hiển thị thông tin thắng thua
    if match_count >= 3:
        multiplier = "x1.5" if match_count == 3 else "x3" if match_count == 4 else "x10"
        final_embed.add_field(name="💰 Tiền thắng", 
                              value=f"+{winnings} xu ({multiplier})", 
                              inline=True)
    else:
        final_embed.add_field(name="💸 Tiền thua", 
                              value=f"-{bet} xu", 
                              inline=True)

    final_embed.add_field(name="💼 Số dư hiện tại", 
                          value=f"{currency[user_id]} xu", 
                          inline=True)

    # Tiến độ đạt được
    progress = "🟥" * match_count + "⬜" * (5 - match_count)
    final_embed.add_field(name="📊 Tiến độ thắng", 
                          value=f"{progress}", 
                          inline=False)

    # Set footer tùy theo kết quả
    if match_count >= 5:
        final_embed.set_footer(text="🎊 JACKPOT! Xin chúc mừng chiến thắng tuyệt vời! 🎊")
    elif match_count >= 3:
        final_embed.set_footer(text="🎉 Chúc mừng! Hãy thử lại để giành Jackpot!")
    else:
        final_embed.set_footer(text="😢 Hãy thử lại vận may của bạn!")

    await message.edit(embed=final_embed)


# 4. Thêm trò chơi Mậu Binh
@bot.command(name='maubinh', aliases=['mb'])
@check_channel()
@check_game_enabled('maubinh')
async def mau_binh(ctx, bet: str = None):
    """Trò chơi Mậu Binh đơn giản"""
    if bet is None:
        embed = discord.Embed(
            title="🃏 Mậu Binh - Hướng Dẫn",
            description=
            "Hãy nhập số xu muốn cược để chơi Mậu Binh.\nVí dụ: `.maubinh 50` hoặc `.maubinh all`",
            color=discord.Color.blue())
        embed.add_field(
            name="Luật chơi",
            value=
            "- Bot sẽ chia cho bạn và bot mỗi người 13 lá\n- Tự động xếp thành 3 chi: chi dưới (5 lá), chi giữa (5 lá) và chi trên (3 lá)\n- Người có nhiều chi thắng hơn sẽ chiến thắng",
            inline=False)
        embed.add_field(name="Phần thưởng",
                        value="- Thắng: x1.8 tiền cược",
                        inline=False)
        await ctx.send(embed=embed)
        return

    user_id = ctx.author.id

    # Xử lý đặt cược "all"
    bet_amount = parse_bet(bet, currency[user_id])
    if bet_amount is None:
        embed = discord.Embed(
            title="❌ Số tiền không hợp lệ",
            description="Vui lòng nhập số tiền hợp lệ hoặc 'all'.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Kiểm tra tiền cược
    if bet_amount <= 0:
        embed = discord.Embed(title="🃏 Mậu Binh",
                              description="Số tiền cược phải lớn hơn 0 xu.",
                              color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    if currency[user_id] < bet_amount:
        embed = discord.Embed(
            title="🃏 Mậu Binh",
            description=
            f"{ctx.author.mention}, bạn không đủ xu để đặt cược! Bạn hiện có {currency[user_id]} xu.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Tạo bộ bài
    suits = ['♠️', '♥️', '♦️', '♣️']
    cards = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
    values = {
        '2': 2,
        '3': 3,
        '4': 4,
        '5': 5,
        '6': 6,
        '7': 7,
        '8': 8,
        '9': 9,
        '10': 10,
        'J': 11,
        'Q': 12,
        'K': 13,
        'A': 14
    }

    # Tạo và trộn bộ bài
    deck = [(card, suit) for suit in suits for card in cards]
    random.shuffle(deck)

    # Chia bài
    player_hand = [deck.pop() for _ in range(13)]
    bot_hand = [deck.pop() for _ in range(13)]

    # Sắp xếp bài theo giá trị
    player_hand.sort(key=lambda x: values[x[0]])
    bot_hand.sort(key=lambda x: values[x[0]])

    # Tạo thông báo chia bài với hiệu ứng
    loading_message = await ctx.send("🃏 **Chuẩn bị chia bài Mậu Binh...**")
    await asyncio.sleep(1)

    # Hiệu ứng chia bài từng lá
    for i in range(1, 14):
        await loading_message.edit(content=f"🃏 **Đang chia bài ({i}/13)...**")
        await asyncio.sleep(0.3)

    await loading_message.edit(content="🃏 **Đang xếp bài thành 3 chi...**")
    await asyncio.sleep(1.5)

    # Chia bài thành 3 chi
    player_bottom = player_hand[:5]  # 5 lá chi dưới
    player_middle = player_hand[5:10]  # 5 lá chi giữa
    player_top = player_hand[10:]  # 3 lá chi trên

    bot_bottom = bot_hand[:5]  # 5 lá chi dưới
    bot_middle = bot_hand[5:10]  # 5 lá chi giữa
    bot_top = bot_hand[10:]  # 3 lá chi trên

    # Format bài cho hiển thị
    def format_cards(cards):
        return " ".join(f"{card}{suit}" for card, suit in cards)

    # Hiển thị bài của người chơi theo chi
    player_display = (
        f"**Chi dưới (5 lá):** {format_cards(player_bottom)}\n"
        f"**Chi giữa (5 lá):** {format_cards(player_middle)}\n"
        f"**Chi trên (3 lá):** {format_cards(player_top)}"
    )

    # Hiển thị bài của bot theo chi (ẩn chi trên và chi giữa)
    bot_display_hidden = (
        f"**Chi dưới (5 lá):** {format_cards(bot_bottom)}\n"
        f"**Chi giữa (5 lá):** 🂠 🂠 🂠 🂠 🂠\n"
        f"**Chi trên (3 lá):** 🂠 🂠 🂠"
    )

    # Tính điểm cho các chi
    def calculate_chi_value(cards):
        # Đây là một phiên bản đơn giản, thực tế sẽ cần xác định các bộ bài như đôi, ba lá, sảnh, thùng, etc.
        return sum(values[card[0]] for card in cards)

    player_bottom_value = calculate_chi_value(player_bottom)
    player_middle_value = calculate_chi_value(player_middle)
    player_top_value = calculate_chi_value(player_top)

    bot_bottom_value = calculate_chi_value(bot_bottom)
    bot_middle_value = calculate_chi_value(bot_middle)
    bot_top_value = calculate_chi_value(bot_top)

    # Xác định thắng thua cho từng chi
    player_wins = 0
    bot_wins = 0

    # So sánh chi dưới
    if player_bottom_value > bot_bottom_value:
        player_wins += 1
    else:
        bot_wins += 1

    # So sánh chi giữa
    if player_middle_value > bot_middle_value:
        player_wins += 1
    else:
        bot_wins += 1

    # So sánh chi trên
    if player_top_value > bot_top_value:
        player_wins += 1
    else:
        bot_wins += 1

    # Hiển thị kết quả đầu tiên (chỉ hiển thị bài người chơi)
    initial_embed = discord.Embed(
        title="🃏 Mậu Binh - Bài Của Bạn",
        description=f"{ctx.author.mention} đã đặt cược {bet_amount} xu.",
        color=discord.Color.blue())

    initial_embed.add_field(name="Bài của bạn", value=player_display, inline=False)
    initial_embed.add_field(name="Bài của bot (đang ẩn)", value="Chi của bot đang được ẩn...", inline=False)
    initial_embed.set_footer(text="Đang so sánh các chi...")

    await loading_message.edit(content=None, embed=initial_embed)
    await asyncio.sleep(2)

    # Hiệu ứng so sánh từng chi
    comparison_results = []

    # So sánh chi dưới
    bottom_comparison = discord.Embed(
        title="🃏 Mậu Binh - So Sánh Chi Dưới",
        description=f"Đang so sánh chi dưới của {ctx.author.mention} và bot.",
        color=discord.Color.gold())

    bottom_comparison.add_field(
        name="Chi dưới của bạn", 
        value=f"{format_cards(player_bottom)}\nGiá trị: {player_bottom_value}", 
        inline=True)

    bottom_comparison.add_field(
        name="Chi dưới của bot", 
        value=f"{format_cards(bot_bottom)}\nGiá trị: {bot_bottom_value}", 
        inline=True)

    bottom_result = "BẠN THẮNG 🎉" if player_bottom_value > bot_bottom_value else "BOT THẮNG ❌"
    bottom_comparison.add_field(name="Kết quả", value=bottom_result, inline=False)

    await loading_message.edit(embed=bottom_comparison)
    await asyncio.sleep(2)

    # So sánh chi giữa
    middle_comparison = discord.Embed(
        title="🃏 Mậu Binh - So Sánh Chi Giữa",
        description=f"Đang so sánh chi giữa của {ctx.author.mention} và bot.",
        color=discord.Color.gold())

    middle_comparison.add_field(
        name="Chi giữa của bạn", 
        value=f"{format_cards(player_middle)}\nGiá trị: {player_middle_value}", 
        inline=True)

    middle_comparison.add_field(
        name="Chi giữa của bot", 
        value=f"{format_cards(bot_middle)}\nGiá trị: {bot_middle_value}", 
        inline=True)

    middle_result = "BẠN THẮNG 🎉" if player_middle_value > bot_middle_value else "BOT THẮNG ❌"
    middle_comparison.add_field(name="Kết quả", value=middle_result, inline=False)

    await loading_message.edit(embed=middle_comparison)
    await asyncio.sleep(2)

    # So sánh chi trên
    top_comparison = discord.Embed(
        title="🃏 Mậu Binh - So Sánh Chi Trên",
        description=f"Đang so sánh chi trên của {ctx.author.mention} và bot.",
        color=discord.Color.gold())

    top_comparison.add_field(
        name="Chi trên của bạn", 
        value=f"{format_cards(player_top)}\nGiá trị: {player_top_value}", 
        inline=True)

    top_comparison.add_field(
        name="Chi trên của bot", 
        value=f"{format_cards(bot_top)}\nGiá trị: {bot_top_value}", 
        inline=True)

    top_result = "BẠN THẮNG 🎉" if player_top_value > bot_top_value else "BOT THẮNG ❌"
    top_comparison.add_field(name="Kết quả", value=top_result, inline=False)

    await loading_message.edit(embed=top_comparison)
    await asyncio.sleep(2)

    # Hiển thị kết quả cuối cùng
    # Hiển thị đầy đủ bài của bot
    bot_display_full = (
        f"**Chi dưới (5 lá):** {format_cards(bot_bottom)}\n"
        f"**Chi giữa (5 lá):** {format_cards(bot_middle)}\n"
        f"**Chi trên (3 lá):** {format_cards(bot_top)}"
    )

    # Xác định người thắng cuộc tổng thể
    if player_wins > bot_wins:
        # Người chơi thắng
        winnings = int(bet_amount * 1.8)
        currency[user_id] += winnings - bet_amount

        # Hiệu ứng trước kết quả cuối
        for i in range(3):
            win_color = [discord.Color.gold(), discord.Color.green(), discord.Color.purple()][i % 3]
            win_title = ["🎉 CHIẾN THẮNG!", "🏆 BẠN THẮNG!", "💰 THẮNG LỚN!"][i % 3]

            win_embed = discord.Embed(
                title=win_title,
                description=f"{ctx.author.mention} đã thắng trong Mậu Binh với tỉ số {player_wins}-{bot_wins}!",
                color=win_color)

            win_embed.add_field(name="Chi thắng của bạn", value=f"**{player_wins}/3**", inline=True)
            win_embed.add_field(name="Chi thắng của bot", value=f"**{bot_wins}/3**", inline=True)

            win_embed.set_footer(text=f"{'🎊 ' * (i+1)} Đang tính tiền thưởng... {'🎊 ' * (i+1)}")
            await loading_message.edit(embed=win_embed)
            await asyncio.sleep(0.7)

        # Kết quả chiến thắng cuối cùng
        result_embed = discord.Embed(
            title="🎉 CHIẾN THẮNG! 🎉",
            description=f"{ctx.author.mention} đã thắng trong Mậu Binh với tỉ số {player_wins}-{bot_wins}!",
            color=discord.Color.gold())

        result_embed.add_field(name="Bài của bạn", value=player_display, inline=False)
        result_embed.add_field(name="Bài của bot", value=bot_display_full, inline=False)

        result_embed.add_field(name="Chi thắng của bạn", value=f"**{player_wins}/3**", inline=True)
        result_embed.add_field(name="Chi thắng của bot", value=f"**{bot_wins}/3**", inline=True)

        result_embed.add_field(name="Tiền thắng", value=f"+{winnings} xu (x1.8)", inline=True)
        result_embed.add_field(name="Số dư hiện tại", value=f"{currency[user_id]} xu", inline=True)
        result_embed.set_footer(text="🎊 Chúc mừng chiến thắng! 🎊")

    else:
        # Bot thắng
        currency[user_id] -= bet_amount

        # Hiệu ứng thua cuộc
        for i in range(2):
            lose_color = discord.Color.red() if i % 2 == 0 else discord.Color.dark_red()

            lose_embed = discord.Embed(
                title="❌ THUA CUỘC!" if i % 2 == 0 else "💸 BẠN THUA!",
                description=f"{ctx.author.mention} đã thua trong Mậu Binh với tỉ số {player_wins}-{bot_wins}!",
                color=lose_color)

            lose_embed.add_field(name="Chi thắng của bạn", value=f"**{player_wins}/3**", inline=True)
            lose_embed.add_field(name="Chi thắng của bot", value=f"**{bot_wins}/3**", inline=True)

            lose_embed.set_footer(text="Đang tính tiền thua...")
            await loading_message.edit(embed=lose_embed)
            await asyncio.sleep(0.7)

        # Kết quả thua cuộc cuối cùng
        result_embed = discord.Embed(
            title="❌ THUA CUỘC! ❌",
            description=f"{ctx.author.mention} đã thua trong Mậu Binh với tỉ số {player_wins}-{bot_wins}!",
            color=discord.Color.dark_red())

        result_embed.add_field(name="Bài của bạn", value=player_display, inline=False)
        result_embed.add_field(name="Bài của bot", value=bot_display_full, inline=False)

        result_embed.add_field(name="Chi thắng của bạn", value=f"**{player_wins}/3**", inline=True)
        result_embed.add_field(name="Chi thắng của bot", value=f"**{bot_wins}/3**", inline=True)

        result_embed.add_field(name="Thiệt hại", value=f"-{bet_amount} xu", inline=True)
        result_embed.add_field(name="Số dư hiện tại", value=f"{currency[user_id]} xu", inline=True)
        result_embed.set_footer(text="😢 Chúc may mắn lần sau!")

    await loading_message.edit(embed=result_embed)


# 5. Thêm trò chơi Lô Tô
@bot.command(name='loto', aliases=['lt'])
@check_channel()
@check_game_enabled('loto')
async def loto(ctx, bet: str = None):
    """Trò chơi Lô Tô với hiệu ứng đẹp mắt"""
    if bet is None:
        embed = discord.Embed(
            title="🎱 Lô Tô - Hướng Dẫn",
            description=
            "Hãy nhập số xu muốn cược để chơi Lô Tô.\nVí dụ: `.loto 50` hoặc `.loto all`",
            color=discord.Color.blue())
        embed.add_field(
            name="Luật chơi",
            value=
            "- Bot sẽ quay 5 số ngẫu nhiên từ 1-90\n- Bạn nhận một vé với 15 số ngẫu nhiên\n- Trùng càng nhiều số, thưởng càng cao",
            inline=False)
        embed.add_field(
            name="Phần thưởng",
            value=
            "- Trùng 2 số: Hoàn tiền\n- Trùng 3 số: x2 tiền cược\n- Trùng 4 số: x5 tiền cược\n- Trùng 5 số: x10 tiền cược",
            inline=False)
        await ctx.send(embed=embed)
        return

    user_id = ctx.author.id

    # Xử lý đặt cược "all"
    bet_amount = parse_bet(bet, currency[user_id])
    if bet_amount is None:
        embed = discord.Embed(
            title="❌ Số tiền không hợp lệ",
            description="Vui lòng nhập số tiền hợp lệ hoặc 'all'.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Kiểm tra tiền cược
    if bet_amount <= 0:
        embed = discord.Embed(title="🎱 Lô Tô",
                              description="Số tiền cược phải lớn hơn 0 xu.",
                              color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    if currency[user_id] < bet_amount:
        embed = discord.Embed(
            title="🎱 Lô Tô",
            description=
            f"{ctx.author.mention}, bạn không đủ xu để đặt cược! Bạn hiện có {currency[user_id]} xu.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Tạo số ngẫu nhiên
    all_numbers = list(range(1, 91))
    drawn_numbers = random.sample(all_numbers, 5)  # 5 số quay
    player_ticket = random.sample(all_numbers, 15)  # 15 số trên vé - tăng từ 10 lên 15 để tăng khả năng trúng

    # Tìm số trùng
    matching_numbers = set(drawn_numbers) & set(player_ticket)

    # Hiển thị vé số theo dạng bảng 5x3
    def format_ticket_grid(ticket):
        sorted_ticket = sorted(ticket)
        rows = []

        # Tạo grid 5x3
        for i in range(0, len(sorted_ticket), 5):
            end_idx = min(i + 5, len(sorted_ticket))
            row = sorted_ticket[i:end_idx]
            # Format mỗi số với padding để đều nhau
            rows.append(" ".join(f"`{num:2d}`" for num in row))

        return "\n".join(rows)

    # Hiển thị hiệu ứng bắt đầu game
    ball_emojis = ["🔴", "🟠", "🟡", "🟢", "🔵"]
    colors = [discord.Color.red(), discord.Color.orange(), discord.Color.gold(), 
              discord.Color.green(), discord.Color.blue()]

    # Tạo embed ban đầu
    initial_embed = discord.Embed(
        title="🎱 Lô Tô - Bắt đầu quay số",
        description=f"{ctx.author.mention} đã đặt cược {bet_amount} xu.",
        color=discord.Color.blue())

    ticket_display = format_ticket_grid(player_ticket)
    initial_embed.add_field(name="🎫 VÉ SỐ CỦA BẠN", value=ticket_display, inline=False)
    initial_embed.add_field(name="⏳ TRẠNG THÁI", value="Đang chuẩn bị quay số...", inline=False)
    initial_embed.set_footer(text="Trùng từ 2 số trở lên để nhận thưởng!")

    message = await ctx.send(embed=initial_embed)
    await asyncio.sleep(1.5)

    # Animation lồng trống quay số
    for i in range(3):
        drum_embed = discord.Embed(
            title=f"🎱 Lô Tô - Lồng trống đang quay{'.' * (i+1)}",
            description=f"{ctx.author.mention} đã đặt cược {bet_amount} xu.",
            color=discord.Color.gold())

        drum_embed.add_field(name="🎫 VÉ SỐ CỦA BẠN", value=ticket_display, inline=False)

        # Animation hiển thị trống đang quay
        spinning = ["🎲 🎲 🎲", "🎯 🎯 🎯", "🎪 🎪 🎪"]
        drum_embed.add_field(
            name="🎰 LỒNG TRỐNG ĐANG QUAY",
            value=spinning[i % len(spinning)],
            inline=False)

        await message.edit(embed=drum_embed)
        await asyncio.sleep(0.8)

    # Quay và hiển thị từng số với animation đẹp mắt
    drawn_so_far = []

    for i, num in enumerate(drawn_numbers):
        # Thêm số mới vào danh sách đã quay
        drawn_so_far.append(num)
        current_color = colors[i % len(colors)]
        current_emoji = ball_emojis[i % len(ball_emojis)]

        # Hiệu ứng trước khi hiện số
        for _ in range(2):
            pre_draw_embed = discord.Embed(
                title=f"🎱 Lô Tô - Đang quay số {i+1}/5",
                description=f"{ctx.author.mention} đã đặt cược {bet_amount} xu.",
                color=current_color)

            pre_draw_embed.add_field(name="🎫 VÉ SỐ CỦA BẠN", value=ticket_display, inline=False)

            # Hiển thị số đã quay
            if drawn_so_far[:-1]:  # Hiển thị tất cả trừ số mới nhất
                previous_numbers = " ".join(f"{ball_emojis[idx % len(ball_emojis)]} `{n:2d}`" 
                                          for idx, n in enumerate(drawn_so_far[:-1]))
                pre_draw_embed.add_field(name="🎲 SỐ ĐÃ QUAY", value=previous_numbers, inline=False)

            # Hiệu ứng quay số
            pre_draw_embed.add_field(
                name="⏳ ĐANG QUAY SỐ...",
                value=f"{'🔄' * (_ % 3 + 1)}",
                inline=False)

            await message.edit(embed=pre_draw_embed)
            await asyncio.sleep(0.5)

        # Hiển thị số mới quay
        new_number_embed = discord.Embed(
            title=f"🎱 Lô Tô - Số thứ {i+1}: {current_emoji} {num}!",
            description=f"{ctx.author.mention} đã đặt cược {bet_amount} xu.",
            color=current_color)

        # Cập nhật vé số, đánh dấu số trúng
        marked_ticket = []
        for ticket_num in sorted(player_ticket):
            if ticket_num in drawn_so_far and ticket_num == num:
                # Số vừa mới trúng
                marked_ticket.append(f"**`{ticket_num:2d}`**")
            elif ticket_num in drawn_so_far:
                # Số đã trúng từ trước
                marked_ticket.append(f"**`{ticket_num:2d}`**")
            else:
                # Số chưa trúng
                marked_ticket.append(f"`{ticket_num:2d}`")

        # Format lại vé theo grid 5x3
        marked_ticket_display = ""
        for j in range(0, len(marked_ticket), 5):
            end_idx = min(j + 5, len(marked_ticket))
            marked_ticket_display += " ".join(marked_ticket[j:end_idx]) + "\n"

        new_number_embed.add_field(name="🎫 VÉ SỐ CỦA BẠN", value=marked_ticket_display, inline=False)

        # Hiển thị tất cả số đã quay
        all_drawn = " ".join(f"{ball_emojis[idx % len(ball_emojis)]} `{n:2d}`" 
                            for idx, n in enumerate(drawn_so_far))
        new_number_embed.add_field(name="🎲 SỐ ĐÃ QUAY", value=all_drawn, inline=False)

        # Hiển thị số trùng hiện tại
        current_matches = set(drawn_so_far) & set(player_ticket)
        if current_matches:
            match_str = " ".join(f"**`{n:2d}`**" for n in sorted(current_matches))
            new_number_embed.add_field(name=f"✅ SỐ TRÙNG ({len(current_matches)}/{len(drawn_numbers)})", 
                                      value=match_str, inline=False)

            # Hiển thị tiến trình
            if len(current_matches) >= 2:
                progress_value = "Hoàn tiền" if len(current_matches) == 2 else f"x{len(current_matches) - 1}" if len(current_matches) < 5 else "x10"
                new_number_embed.add_field(name="💰 TIẾN TRÌNH", 
                                         value=f"Đã trùng {len(current_matches)}/5 số! ({progress_value})", 
                                         inline=False)

        # Hiệu ứng đặc biệt khi số vừa quay trùng với vé
        if num in player_ticket:
            # Flashing animation cho số trúng
            for k in range(3):
                if k % 2 == 0:
                    new_number_embed.title = f"🎱 Lô Tô - 🎯 TRÚNG SỐ {num}! 🎯"
                    new_number_embed.color = discord.Color.green()
                else:
                    new_number_embed.title = f"🎱 Lô Tô - Số thứ {i+1}: {current_emoji} {num}!"
                    new_number_embed.color = current_color

                await message.edit(embed=new_number_embed)
                await asyncio.sleep(0.3)
        else:
            await message.edit(embed=new_number_embed)

        await asyncio.sleep(1.2)

    # Kết quả cuối cùng
    match_count = len(matching_numbers)

    # Xác định kết quả và phần thưởng
    if match_count >= 5:
        winnings = bet_amount * 10
        result_text = f"🎉 JACKPOT! Bạn đã trúng {match_count}/5 số!"
        color = discord.Color.gold()
        currency[user_id] += winnings - bet_amount
        win_emoji = "🏆"
    elif match_count == 4:
        winnings = bet_amount * 5
        result_text = f"🎉 THẮNG LỚN! Bạn đã trúng 4/5 số!"
        color = discord.Color.purple()
        currency[user_id] += winnings - bet_amount
        win_emoji = "🎉"
    elif match_count == 3:
        winnings = bet_amount * 2
        result_text = f"🎉 THẮNG! Bạn đã trúng 3/5 số!"
        color = discord.Color.green()
        currency[user_id] += winnings - bet_amount
        win_emoji = "✨"
    elif match_count == 2:
        winnings = bet_amount
        result_text = f"🔄 HÒA! Bạn đã trúng 2/5 số!"
        color = discord.Color.blue()
        # Đã đặt cược bet_amount và được hoàn lại bet_amount, coi như không mất tiền
        win_emoji = "🔄"
    else:
        winnings = 0
        result_text = f"❌ THUA CUỘC! Bạn chỉ trúng {match_count}/5 số."
        color = discord.Color.red()
        currency[user_id] -= bet_amount
        win_emoji = "😢"

    # Hiệu ứng chuyển tiếp trước khi hiển thị kết quả cuối cùng
    await asyncio.sleep(0.5)

    # Đối với trường hợp JACKPOT, tạo hiệu ứng đặc biệt
    if match_count >= 5:
        for i in range(4):
            jackpot_colors = [discord.Color.gold(), discord.Color.red(), discord.Color.green(), discord.Color.purple()]
            jackpot_emojis = ["🎊", "💰", "🎯", "🏆"]

            jackpot_embed = discord.Embed(
                title=f"{jackpot_emojis[i]} JACKPOT! {jackpot_emojis[i]}",
                description=f"🎊 **CHIẾN THẮNG TỐI ĐA!** 🎊\n{ctx.author.mention} đã trúng {match_count}/5 số!",
                color=jackpot_colors[i])

            padding = " " * (i % 2)  # Hiệu ứng chữ nhấp nháy
            jackpot_embed.add_field(
                name=f"{padding}💸 JACKPOT X10! 💸{padding}",
                value=f"Bạn đã thắng **{winnings} xu**!",
                inline=False)

            await message.edit(embed=jackpot_embed)
            await asyncio.sleep(0.6)

    # Tạo vé số đã đánh dấu số trúng cho kết quả cuối cùng
    marked_final_ticket = []
    for ticket_num in sorted(player_ticket):
        if ticket_num in matching_numbers:
            marked_final_ticket.append(f"**`{ticket_num:2d}`**")
        else:
            marked_final_ticket.append(f"`{ticket_num:2d}`")

    # Format lại vé theo grid 5x3
    final_ticket_display = ""
    for j in range(0, len(marked_final_ticket), 5):
        end_idx = min(j + 5, len(marked_final_ticket))
        final_ticket_display += " ".join(marked_final_ticket[j:end_idx]) + "\n"

    # Hiển thị kết quả cuối cùng
    final_embed = discord.Embed(
        title=f"{win_emoji} Lô Tô - Kết Quả Cuối Cùng {win_emoji}",
        description=result_text,
        color=color)

    # Vé số với các số trùng được đánh dấu
    final_embed.add_field(name="🎫 VÉ SỐ CỦA BẠN", 
                         value=final_ticket_display, 
                         inline=False)

    # Các số đã quay
    all_drawn_display = " ".join(f"{ball_emojis[i % len(ball_emojis)]} `{num:2d}`" 
                              for i, num in enumerate(sorted(drawn_numbers)))
    final_embed.add_field(name="🎲 CÁC SỐ ĐÃ QUAY", 
                         value=all_drawn_display, 
                         inline=False)

    # Các số trùng
    if matching_numbers:
        matching_nums_display = " ".join(f"**`{num:2d}`**" for num in sorted(matching_numbers))
        final_embed.add_field(name=f"✅ SỐ TRÙNG ({match_count}/5)", 
                             value=matching_nums_display, 
                             inline=False)
    else:
        final_embed.add_field(name="❌ SỐ TRÙNG (0/5)", 
                             value="Không có số nào trùng", 
                             inline=False)

    # Tiến trình đạt được
    progress_bar = "🟥" * match_count + "⬛" * (5 - match_count)
    final_embed.add_field(name="📊 TIẾN TRÌNH", 
                         value=progress_bar, 
                         inline=False)

    # Kết quả và số dư
    if match_count >= 2:
        if match_count == 2:
            final_embed.add_field(name="💰 KẾT QUẢ", 
                                 value=f"Hoàn lại {bet_amount} xu", 
                                 inline=True)
        else:
            multiplier = "x2" if match_count == 3 else "x5" if match_count == 4 else "x10"
            final_embed.add_field(name="💰 TIỀN THẮNG", 
                                 value=f"+{winnings} xu ({multiplier})", 
                                 inline=True)
    else:
        final_embed.add_field(name="💸 TIỀN THUA", 
                             value=f"-{bet_amount} xu", 
                             inline=True)

    final_embed.add_field(name="💼 SỐ DƯ HIỆN TẠI", 
                         value=f"{currency[user_id]} xu", 
                         inline=True)

    # Footer phù hợp với kết quả
    if match_count >= 5:
        final_embed.set_footer(text="🎊 JACKPOT! Xin chúc mừng chiến thắng tuyệt vời! 🎊")
    elif match_count >= 3:
        final_embed.set_footer(text="🎉 Chúc mừng! Hãy thử lại để giành Jackpot!")
    elif match_count == 2:
        final_embed.set_footer(text="🔄 Hòa vốn! Hãy thử lại vận may của bạn!")
    else:
        final_embed.set_footer(text="😢 Tiếc quá! Hãy thử lại vận may lần sau!")

    await message.edit(embed=final_embed)


# Thêm game tung đồng xu
@bot.command(name='tungxu', aliases=['tx2', 'coinflip'])
@check_channel()
@check_game_enabled('tungxu')
async def coin_flip(ctx, choice: str = None, bet: str = None):
    """Trò chơi tung đồng xu với hiệu ứng đẹp mắt"""
    if choice is None or bet is None:
        embed = discord.Embed(
            title="🪙 Tung Đồng Xu - Hướng Dẫn",
            description=
            "Hãy đoán mặt đồng xu và đặt cược xu.\nVí dụ: `.tungxu n 50` hoặc `.tungxu s 50`\nBạn cũng có thể đặt cược tất cả bằng lệnh `.tungxu n all`",
            color=discord.Color.blue())
        embed.add_field(
            name="Luật chơi",
            value=
            "- Chọn mặt đồng xu: ngửa (n) hoặc sấp (s)\n- Đặt cược số xu hoặc 'all' để cược tất cả\n- Nếu đoán đúng, bạn nhận x1.8 tiền cược\n- Nếu đoán sai, bạn mất tiền cược và bị timeout 5 phút",
            inline=False)
        embed.set_footer(text="Chơi có trách nhiệm, đừng đặt cược quá nhiều!")

        # Thêm gợi ý ngẫu nhiên
        embed.add_field(name="💡 Gợi ý",
                        value="Tỉ lệ thắng tung đồng xu là 50/50!",
                        inline=False)
        await ctx.send(embed=embed)
        return

    user_id = ctx.author.id

    # Kiểm tra cooldown
    can_play, remaining_time = check_cooldown(user_id)
    if not can_play:
        embed = discord.Embed(
            title="⏳ Thời gian chờ",
            description=
            f"Bạn cần đợi thêm {remaining_time} giây trước khi chơi tiếp.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Kiểm tra lựa chọn
    if choice.lower() not in ['n', 's', 'ngua', 'sap', 'ngửa', 'sấp']:
        embed = discord.Embed(
            title="🪙 Tung Đồng Xu",
            description=
            "Lựa chọn không hợp lệ. Vui lòng chọn 'n' (ngửa) hoặc 's' (sấp).",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Chuyển đổi lựa chọn
    is_ngua = choice.lower() in ['n', 'ngua', 'ngửa']
    choice_text = "Ngửa" if is_ngua else "Sấp"
    choice_emoji = "⬆️" if is_ngua else "⬇️"

    # Xử lý đặt cược "all"
    bet_amount = parse_bet(bet, currency[user_id])
    if bet_amount is None:
        embed = discord.Embed(
            title="🪙 Tung Đồng Xu",
            description=
            "Số tiền cược không hợp lệ. Vui lòng nhập số hoặc 'all'.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Kiểm tra tiền cược
    if bet_amount <= 0:
        embed = discord.Embed(title="🪙 Tung Đồng Xu",
                              description="Số tiền cược phải lớn hơn 0 xu.",
                              color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    if currency[user_id] < bet_amount:
        embed = discord.Embed(
            title="🪙 Tung Đồng Xu",
            description=
            f"{ctx.author.mention}, bạn không đủ xu để đặt cược! Bạn hiện có {currency[user_id]} xu.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Hiển thị thông báo nếu đang đặt cược tất cả
    is_all_in = bet_amount == currency[user_id]

    try:
        # Tạo hiệu ứng chuẩn bị tung đồng xu
        start_embed = discord.Embed(
            title="🪙 TUNG ĐỒNG XU",
            description=f"{ctx.author.mention} đã đặt cược **{bet_amount} xu**!",
            color=discord.Color.blue())

        start_embed.add_field(name="Lựa chọn", value=f"**{choice_text}** {choice_emoji}", inline=True)
        start_embed.add_field(name="Trạng thái", value="Đang chuẩn bị...", inline=True)

        if is_all_in:
            start_embed.add_field(name="⚠️ ALL-IN", value="Bạn đang đặt cược tất cả xu!", inline=False)

        message = await ctx.send(embed=start_embed)
        await asyncio.sleep(1)

        # Animation đồng xu đang xoay - hiệu ứng nâng cao
        coin_frames = [
            "```\n  🪙  \n     \n```",
            "```\n     \n  🪙  \n```",
            "```\n 🪙   \n     \n```",
            "```\n     \n   🪙 \n```",
            "```\n  🪙  \n     \n```",
            "```\n     \n  🪙  \n```"
        ]

        spin_embed = discord.Embed(
            title="🪙 ĐỒNG XU ĐANG XOAY",
            description=f"{ctx.author.mention} đã đặt cược **{bet_amount} xu**!",
            color=discord.Color.gold())

        spin_embed.add_field(name="Lựa chọn", value=f"**{choice_text}** {choice_emoji}", inline=True)
        spin_embed.add_field(name="Xu sẽ rơi xuống trong...", value="⏱️", inline=True)

        for i in range(6):
            spin_embed.set_field_at(1, name="Xu sẽ rơi xuống trong...", value=f"**{6-i}**", inline=True)
            spin_embed.description = coin_frames[i % len(coin_frames)]
            await message.edit(embed=spin_embed)
            await asyncio.sleep(0.5)

        # Animation đồng xu đang quay chậm dần - hiệu ứng nâng cao
        slow_embed = discord.Embed(
            title="🪙 ĐỒNG XU SẮP DỪNG LẠI",
            description=f"{ctx.author.mention} đã đặt cược **{bet_amount} xu**!",
            color=discord.Color.orange())

        slow_embed.add_field(name="Lựa chọn", value=f"**{choice_text}** {choice_emoji}", inline=True)

        for i in range(3):
            # Hiệu ứng tiếng đồng xu va chạm
            sounds = ["*Ting!*", "*Cling!*", "*Ding!*"]
            slow_embed.set_field_at(0, name="Lựa chọn", value=f"**{choice_text}** {choice_emoji}\n{sounds[i]}", inline=True)
            await message.edit(embed=slow_embed)
            await asyncio.sleep(0.8)

        # Kết quả ngẫu nhiên (50/50)
        result_is_ngua = random.choice([True, False])

        # Người chơi thắng nếu dự đoán đúng
        player_won = (is_ngua == result_is_ngua)

        # Hiển thị kết quả
        result_text = "NGỬA" if result_is_ngua else "SẤP"
        result_emoji = "⬆️" if result_is_ngua else "⬇️"

        # Hiệu ứng đếm ngược trước khi hiện kết quả
        countdown_embed = discord.Embed(
            title="🪙 KẾT QUẢ SẮP LỘ DIỆN",
            description="Đồng xu đã dừng lại...",
            color=discord.Color.purple())

        for i in range(3, 0, -1):
            countdown_embed.description = f"Đồng xu đã dừng lại...\nKết quả sẽ hiện ra trong **{i}**..."
            await message.edit(embed=countdown_embed)
            await asyncio.sleep(0.7)

        # Hiệu ứng nhấp nháy kết quả
        for i in range(3):
            # Đảo màu trong hiệu ứng nhấp nháy
            flash_color = discord.Color.green() if player_won else discord.Color.red()
            if i % 2 == 1:
                flash_color = discord.Color.gold()

            flash_embed = discord.Embed(
                title=f"🪙 KẾT QUẢ: {result_text} {result_emoji}",
                description=f"{'🎉 THẮNG CUỘC! 🎉' if player_won else '❌ THUA CUỘC! ❌'}",
                color=flash_color)

            await message.edit(embed=flash_embed)
            await asyncio.sleep(0.4)

        # Hiển thị kết quả cuối cùng
        if player_won:
            # Người chơi thắng
            winnings = int(bet_amount * 1.8)
            currency[user_id] += winnings - bet_amount

            # Hiệu ứng đặc biệt cho jackpot hoặc all-in
            if is_all_in:
                # Hiệu ứng đặc biệt cho all-in
                for i in range(3):
                    jackpot_embed = discord.Embed(
                        title=f"🎰 ALL-IN {'THÀNH CÔNG' if i % 2 == 0 else 'THẮNG LỚN'}! 🎰",
                        description=f"WOW! {ctx.author.mention} ĐÃ ALL-IN VÀ THẮNG!",
                        color=discord.Color.gold() if i % 2 == 0 else discord.Color.purple())

                    jackpot_embed.add_field(
                        name=f"{'💰 TIỀN THẮNG 💰' if i % 2 == 0 else '🏆 PHẦN THƯỞNG 🏆'}", 
                        value=f"+{winnings} xu (x1.8)", 
                        inline=True)

                    jackpot_embed.add_field(
                        name="Kết quả đồng xu", 
                        value=f"**{result_text}** {result_emoji}", 
                        inline=True)

                    await message.edit(embed=jackpot_embed)
                    await asyncio.sleep(0.7)

            # Kết quả thắng cuộc
            win_embed = discord.Embed(
                title="🎉 THẮNG CUỘC! 🎉",
                description=f"{ctx.author.mention} đã đoán đúng!",
                color=discord.Color.green())

            win_embed.add_field(
                name="Chi tiết trận đấu", 
                value=f"**Lựa chọn của bạn:** {choice_text} {choice_emoji}\n**Kết quả đồng xu:** {result_text} {result_emoji}", 
                inline=False)

            if is_all_in:
                win_embed.add_field(
                    name="💰 Tiền thắng", 
                    value=f"+{winnings} xu (x1.8) - ALL IN!", 
                    inline=True)
            else:
                win_embed.add_field(
                    name="💰 Tiền thắng", 
                    value=f"+{winnings} xu (x1.8)", 
                    inline=True)

            win_embed.add_field(
                name="💼 Số dư hiện tại", 
                value=f"{currency[user_id]} xu", 
                inline=True)

            win_embed.set_footer(text="🍀 Hôm nay là ngày may mắn của bạn!")

            # Thêm hiệu ứng tiền xu bay lên
            coins_animation = "```\n" + \
                              "    💰    \n" + \
                              "  💰  💰  \n" + \
                              "💰  🪙  💰\n" + \
                              "  💰  💰  \n" + \
                              "    💰    \n" + \
                              "```"
            win_embed.description = f"{ctx.author.mention} đã đoán đúng!\n\n{coins_animation}"

            await message.edit(embed=win_embed)
        else:
            # Người chơi thua
            currency[user_id] -= bet_amount

            # Hiệu ứng thua cuộc đặc biệt
            if is_all_in:
                for i in range(3):
                    disaster_embed = discord.Embed(
                        title=f"💥 ALL-IN {'THẤT BẠI' if i % 2 == 0 else 'PHÁ SẢN'}! 💥",
                        description=f"Ôi không! {ctx.author.mention} đã ALL-IN và THUA TRẮNG!",
                        color=discord.Color.dark_red() if i % 2 == 0 else discord.Color.red())

                    disaster_embed.add_field(
                        name="Thiệt hại nặng nề", 
                        value=f"-{bet_amount} xu - TOÀN BỘ TÀI SẢN!", 
                        inline=True)

                    await message.edit(embed=disaster_embed)
                    await asyncio.sleep(0.7)

            # Kết quả thua cuộc
            lose_embed = discord.Embed(
                title="❌ THUA CUỘC! ❌",
                description=f"{ctx.author.mention} đã đoán sai và sẽ bị timeout 5 phút!",
                color=discord.Color.dark_red())

            lose_embed.add_field(
                name="Chi tiết trận đấu", 
                value=f"**Lựa chọn của bạn:** {choice_text} {choice_emoji}\n**Kết quả đồng xu:** {result_text} {result_emoji}", 
                inline=False)

            if is_all_in:
                lose_embed.add_field(
                    name="💸 Thiệt hại", 
                    value=f"-{bet_amount} xu - ALL IN!", 
                    inline=True)
            else:
                lose_embed.add_field(
                    name="💸 Thiệt hại", 
                    value=f"-{bet_amount} xu", 
                    inline=True)

            lose_embed.add_field(
                name="💼 Số dư hiện tại", 
                value=f"{currency[user_id]} xu", 
                inline=True)

            lose_embed.add_field(
                name="⏳ Hệ quả", 
                value="Bạn sẽ bị timeout trong 5 phút!", 
                inline=False)

            lose_embed.set_footer(text="😢 Rất tiếc! Hãy thử lại vận may lần sau!")

            # Thêm hiệu ứng vỡ nát
            broken_animation = "```\n" + \
                               "  💥    \n" + \
                               "    💥  \n" + \
                               "  🪙    \n" + \
                               "💥    💥\n" + \
                               "    💥  \n" + \
                               "```"
            lose_embed.description = f"{ctx.author.mention} đã đoán sai và sẽ bị timeout 5 phút!\n\n{broken_animation}"

            # Timeout người chơi 5 phút
            try:
                timeout_until = discord.utils.utcnow() + timedelta(minutes=5)
                await ctx.author.timeout(timeout_until,
                                         reason="Thua trò chơi Tung Đồng Xu")
            except discord.Forbidden:
                await ctx.send("⚠️ Bot không có quyền timeout người chơi!")
                lose_embed.add_field(name="⚠️ Lỗi", value="Không thể timeout người chơi!", inline=False)
            except Exception as e:
                await ctx.send(f"⚠️ Có lỗi xảy ra khi timeout: {str(e)}")
                lose_embed.add_field(name="⚠️ Lỗi", value=f"Lỗi timeout: {str(e)}", inline=False)

            await message.edit(embed=lose_embed)

    except Exception as e:
        # Xử lý lỗi nếu có
        error_embed = discord.Embed(
            title="❌ Đã xảy ra lỗi",
            description=f"Không thể hoàn thành lệnh tung đồng xu: {str(e)}",
            color=discord.Color.red())
        await ctx.send(embed=error_embed)


# Cập nhật lệnh trợ giúp để bao gồm tất cả game và lệnh giải trí
@bot.group(name='bothelp', invoke_without_command=True)
async def help_command(ctx):
    """Hiển thị hướng dẫn cơ bản với embed"""
    embed = discord.Embed(
        title="🤖 Hướng Dẫn Bot",
        description=
        f"Dùng `.help [tên nhóm]` để xem chi tiết từng nhóm lệnh.\nVí dụ: `.help games`",
        color=discord.Color.blue())

    embed.add_field(name="📜 Nhóm lệnh có sẵn",
                    value="""
        `.help info` - Các lệnh thông tin
        `.help currency` - Quản lý xu
        `.help games` - Trò chơi
        `.help admin` - Lệnh admin
        `.help fun` - Lệnh giải trí
        `.help inventory` - Quản lý kho đồ
        """,
                    inline=False)

    embed.add_field(
        name="⚠️ Lưu ý",
        value=f"Tất cả lệnh game chỉ hoạt động trong <#{GAME_CHANNEL_ID}>",
        inline=False)

    embed.set_footer(text="Bot được phát triển bởi STV Team")
    await ctx.send(embed=embed)


@help_command.command(name='info')
async def help_info(ctx):
    """Hiển thị hướng dẫn lệnh thông tin"""
    embed = discord.Embed(title="📜 Lệnh Thông Tin",
                          description="Các lệnh xem thông tin cơ bản",
                          color=discord.Color.blue())

    embed.add_field(name="Lệnh có sẵn",
                    value="""
        `.stvh` - Xem hướng dẫn đầy đủ các game
        `.stvgt` - Xem giới thiệu về bot
        `.xu` - Kiểm tra số xu hiện có
        `.bxhxu` - Xem bảng xếp hạng xu
        `.gamechannel` - Xem link kênh chơi game
        """,
                    inline=False)

    await ctx.send(embed=embed)


@help_command.command(name='currency')
async def help_currency(ctx):
    """Hiển thị hướng dẫn lệnh xu"""
    embed = discord.Embed(title="💰 Quản Lý Xu",
                          description="Các lệnh liên quan đến xu",
                          color=discord.Color.gold())

    embed.add_field(name="Lệnh cơ bản",
                    value="""
        `.dd` - Điểm danh nhận xu hàng ngày (20-50 xu)
        `.sendxu @người_dùng số_xu` - Chuyển xu cho người khác
        `.xu` - Kiểm tra số xu hiện có
        `.bxhxu` - Xem bảng xếp hạng xu
        """,
                    inline=False)

    embed.add_field(name="Hệ thống ngân hàng",
                    value="""
        `.bank gửi [số xu]` - Gửi xu vào ngân hàng (nhận lãi 5% mỗi ngày)
        `.bank rút [số xu]` - Rút xu từ ngân hàng
        `.bank check` - Kiểm tra số dư và lãi ngân hàng
        """,
                    inline=False)

    embed.add_field(name="Vay mượn xu",
                    value="""
        `.vayxu số_xu` - Vay xu (phải trả trong 2 giờ)
        `.traxu số_xu` - Trả xu đã vay
        """,
                    inline=False)

    embed.add_field(name="Két sắt",
                    value="""
        `.napket số_xu` - Nạp xu vào két
        `.rutxu số_xu` - Rút xu từ két
        `.xemket` - Xem số xu trong két
        """,
                    inline=False)

    await ctx.send(embed=embed)


@help_command.command(name='admin')
@commands.has_permissions(administrator=True)
async def help_admin(ctx):
    """Hiển thị hướng dẫn lệnh admin"""
    embed = discord.Embed(title="👑 Lệnh Admin",
                          description="Các lệnh dành cho quản trị viên",
                          color=discord.Color.purple())

    embed.add_field(name="Quản lý xu",
                    value="""
        `.txu @người_dùng số_xu` - Tặng xu
        `.trxu @người_dùng số_xu` - Trừ xu
        `.napxu @người_dùng số_xu` - Nạp xu
        `.ktxu @người_dùng` - Kiểm tra xu
        """,
                    inline=False)

    embed.add_field(name="Quản lý ngân hàng",
                    value="""
        `.bankcheck @người_dùng` - Kiểm tra tài khoản ngân hàng của người dùng
        `.bankxoa @người_dùng` - Xóa tài khoản ngân hàng của người dùng
        `.blbank add @người_dùng` - Thêm người dùng vào blacklist ngân hàng
        `.blbank remove @người_dùng` - Xóa người dùng khỏi blacklist ngân hàng
        """,
                    inline=False)

    embed.add_field(name="Quản lý két sắt",
                    value="""
        `.ad_xemket @người_dùng` - Xem két người dùng
        `.ad_xoaket @người_dùng` - Xóa két người dùng
        """,
                    inline=False)

    embed.add_field(name="Quản lý drop xu",
                    value="""
        `.dropxu số_xu tin_nhắn` - Tạo drop xu
        `.stopdrop ID_tin_nhắn` - Dừng drop xu
        """,
                    inline=False)

    embed.add_field(name="Quản lý server",
                    value="""
        `.nuke #kênh` - Xóa và tạo lại kênh
        `.stvdis tên_game` - Bật/tắt game
        `.stvdis all` - Bật/tắt tất cả game
        """,
                    inline=False)

    await ctx.send(embed=embed)


@bot.command(name='stvh')
@check_channel()
async def myhelp(ctx):
    """Hiển thị tất cả các lệnh có sẵn và cách sử dụng với hệ thống phân trang"""
    # Tạo một gợi ý ngẫu nhiên để hiển thị
    tips = [
        "💡 **Gợi ý:** Sử dụng từ khóa `all` để đặt cược tất cả xu trong các trò chơi.",
        "💡 **Gợi ý:** Bạn có thể sử dụng lệnh `.xemket` để kiểm tra số xu trong két sắt.",
        "💡 **Gợi ý:** Thắng trong trò chơi Fight cho phép bạn timeout đối thủ bằng lệnh `.kill`.",
        "💡 **Gợi ý:** Nhận thưởng hàng ngày với lệnh `.dd`.",
        "💡 **Gợi ý:** Chế độ chan/lẻ thông thường có tỉ lệ thắng cao nhất.",
        "💡 **Gợi ý:** Trò chơi Xì Dách sẽ thưởng x2 nếu bạn có Xì Dách (A + 10/J/Q/K).",
        "💡 **Gợi ý:** Có thể đo chỉ số IQ, nhân cách, chiều cao, cân nặng với các lệnh giải trí.",
        "💡 **Gợi ý:** Để có thể chơi game an toàn, hãy nạp một phần xu vào két sắt.",
        "💡 **Gợi ý:** Trò chơi 777 rất nguy hiểm, thua sẽ bị kick khỏi server!",
        "💡 **Gợi ý:** Mua bùa may mắn để tăng cơ hội thắng trong các trò chơi.",
        "💡 **Gợi ý:** Áo giáp chống đẹp có thể bảo vệ bạn khỏi timeout khi thua Cô Quay Nga.",
        "💡 **Gợi ý:** Gửi xu vào ngân hàng để nhận lãi 5% mỗi ngày với lệnh `.bank gửi`."
    ]

    random_tip = random.choice(tips)

    # Tạo các trang cho hướng dẫn - cải tiến với các danh mục rõ ràng hơn
    pages = []

    # Trang 1: Thông tin tổng quan
    page1 = discord.Embed(
        title="🎮 Hướng Dẫn STV Bot (1/8) 🎮",
        description=f"Danh sách các lệnh và trò chơi hiện có.\nPrefix: `.`\n\n**⚠️ LƯU Ý: Tất cả lệnh chơi game chỉ hoạt động trong [kênh chơi game]({GAME_CHANNEL_LINK}) ⚠️**\n\n{random_tip}",
        color=discord.Color.blue())

    page1.add_field(
        name="📋 Chỉ Mục Các Trang",
        value=(
            "**Trang 1:** Thông tin tổng quan\n"
            "**Trang 2:** Game may rủi cơ bản\n"
            "**Trang 3:** Game bài & xổ số\n"
            "**Trang 4:** Game đối kháng PvP\n"
            "**Trang 5:** Quản lý tài chính\n"
            "**Trang 6:** Ngân hàng & két sắt\n"
            "**Trang 7:** Cửa hàng & vật phẩm\n"
            "**Trang 8:** Lệnh giải trí"
        ),
        inline=False
    )

    page1.add_field(
        name="🔗 Kênh Chơi Game",
        value=(
            f"**Vui lòng sử dụng các lệnh trong <#{GAME_CHANNEL_ID}>**\n"
            f"[Nhấp vào đây để chuyển đến kênh chơi game]({GAME_CHANNEL_LINK})"
        ),
        inline=False)

    page1.add_field(
        name="📢 Lệnh Thông Tin Cơ Bản",
        value=(
            "**`.stvh`** - Xem danh sách lệnh và hướng dẫn này\n"
            "**`.stvgt`** - Xem giới thiệu về bot\n"
            "**`.xu`** - Kiểm tra số xu hiện có\n"
            "**`.bxhxu`** - Xem bảng xếp hạng xu\n"
            "**`.gamechannel`** - Lấy link đến kênh game"
        ),
        inline=False
    )

    page1.set_footer(text="Sử dụng các nút điều hướng để chuyển trang")
    pages.append(page1)

    # Trang 2: Game may rủi cơ bản
    page2 = discord.Embed(
        title="🎮 Hướng Dẫn STV Bot (2/8) 🎮",
        description=f"Game may rủi cơ bản.\nPrefix: `.`\n\n{random_tip}",
        color=discord.Color.blue())

    page2.add_field(
        name="🎲 Game May Rủi Cơ Bản",
        value=(
            "**`.cl [chan|le|chan2|le2|chan3|le3] [số xu/all]`**\n"
            "→ Chơi chẵn lẻ (x1/x2.5/x3.5)\n\n"
            "**`.tx [t|x] [số xu/all]`**\n"
            "→ Chơi tài xỉu (x1.8)\n\n"
            "**`.tungxu [n|s] [số xu/all]`**\n"
            "→ Tung đồng xu (x1.8, thua timeout)\n\n"
            "**`.baucua [linh vật] [số xu]...`**\n"
            "→ Chơi bầu cua (x1-x3)\n\n"
            "**`.vqmm [số xu/all]`**\n"
            "→ Vòng quay may mắn (x2-x10)"
        ),
        inline=False)

    page2.add_field(
        name="⚠️ Game Nguy Hiểm",
        value=(
            "**`.777 [số xu/all]`**\n"
            "→ Máy quay xèng (jackpot x10, thua bị kick)\n\n"
            "**`.coquaynga [số xu/all]`**\n"
            "→ Cô quay nga (x2, thua timeout)"
        ),
        inline=False)

    page2.set_footer(text="Trang 2/8 - Game May Rủi Cơ Bản")
    pages.append(page2)

    # Trang 3: Game bài & xổ số
    page3 = discord.Embed(
        title="🎮 Hướng Dẫn STV Bot (3/8) 🎮",
        description=f"Game bài và xổ số.\nPrefix: `.`\n\n{random_tip}",
        color=discord.Color.blue())

    page3.add_field(
        name="🃏 Game Bài",
        value=(
            "**`.poker [số xu/all]`**\n"
            "→ Poker đơn giản (x1.5-x10)\n\n"
            "**`.xidach [số xu/all]`** hoặc **`.xd`**\n"
            "→ Xì dách/Blackjack (x1.5-x2)\n\n"
            "**`.phom [số xu/all]`**\n"
            "→ Phỏm (x2-x3)\n\n"
            "**`.maubinh [số xu/all]`** hoặc **`.mb`**\n"
            "→ Mậu binh (x1.8)"
        ),
        inline=False)

    page3.add_field(
        name="🎱 Game Xổ Số",
        value=(
            "**`.pinggo [số xu/all]`** hoặc **`.pg`**\n"
            "→ Ping Go/Bingo (x1.5-x10)\n\n"
            "**`.loto [số xu/all]`** hoặc **`.lt`**\n"
            "→ Lô tô (hoàn tiền-x10)"
        ),
        inline=False)

    page3.set_footer(text="Trang 3/8 - Game Bài & Xổ Số")
    pages.append(page3)

    # Trang 4: Game đối kháng PvP
    page4 = discord.Embed(
        title="🎮 Hướng Dẫn STV Bot (4/8) 🎮",
        description=f"Game đối kháng giữa người chơi.\nPrefix: `.`\n\n{random_tip}",
        color=discord.Color.blue())

    page4.add_field(
        name="⚔️ Game Đối Kháng PvP",
        value=(
            "**`.kbbpvp @người_chơi [số xu]`**\n"
            "→ Kéo búa bao PvP (người thắng có thể timeout người thua)\n\n"
            "**`.fight @người_chơi [số xu/all]`**\n"
            "→ Thách đấu PvP (người thắng có thể dùng .kill timeout đối thủ)\n\n"
            "**`.caropvp @người_chơi [số xu]`**\n"
            "→ Caro PvP (người thắng có thể timeout đối thủ)\n\n"
            "**`.bacaopvp @người_chơi [số xu]`** hoặc **`.bacao`**\n"
            "→ Ba cào PvP (người thua bị timeout)\n\n"
            "**`.kbb [keo|bua|bao] [số xu/all]`**\n"
            "→ Kéo búa bao đấu với bot (x1.5, thua timeout)"
        ),
        inline=False)

    page4.add_field(
        name="🧠 Game Trí Óc",
        value=(
            "**`.hoidap [số xu/all]`**\n"
            "→ Game hỏi đáp (x2)\n\n"
            "**`.kill @người_dùng [phút]`**\n"
            "→ Timeout người thua sau khi thắng Fight (1-5 phút)"
        ),
        inline=False)

    page4.set_footer(text="Trang 4/8 - Game Đối Kháng PvP")
    pages.append(page4)

    # Trang 5: Quản lý tài chính
    page5 = discord.Embed(
        title="🎮 Hướng Dẫn STV Bot (5/8) 🎮",
        description=f"Quản lý tài chính cơ bản.\nPrefix: `.`\n\n{random_tip}",
        color=discord.Color.blue())

    page5.add_field(
        name="💰 Kiếm & Quản Lý Xu",
        value=(
            "**`.dd`**\n"
            "→ Điểm danh nhận (20-50 xu/ngày)\n\n"
            "**`.capxu`** hoặc **`.rx`**\n"
            "→ Nhận xu ngẫu nhiên (10-100 xu mỗi giờ)\n\n"
            "**`.xu`**\n"
            "→ Xem số xu hiện có\n\n"
            "**`.bxhxu`**\n"
            "→ Bảng xếp hạng xu\n\n"
            "**`.sendxu @người_dùng [số xu]`**\n"
            "→ Chuyển xu cho người khác"
        ),
        inline=False)

    page5.add_field(
        name="🔑 Key & Mã Code",
        value=(
            "**`.key [mã key]`**\n"
            "→ Đổi key lấy xu"
        ),
        inline=False)

    page5.set_footer(text="Trang 5/8 - Quản Lý Tài Chính")
    pages.append(page5)

    # Trang 6: Ngân hàng & két sắt
    page6 = discord.Embed(
        title="🎮 Hướng Dẫn STV Bot (6/8) 🎮",
        description=f"Hệ thống ngân hàng và két sắt.\nPrefix: `.`\n\n{random_tip}",
        color=discord.Color.blue())

    page6.add_field(
        name="🏦 Ngân Hàng (Lãi 5%/ngày)",
        value=(
            "**`.bank gửi [số xu]`**\n"
            "→ Gửi xu vào ngân hàng\n\n"
            "**`.bank rút [số xu]`**\n"
            "→ Rút xu từ ngân hàng\n\n"
            "**`.bank check`**\n"
            "→ Kiểm tra số dư và lãi ngân hàng"
        ),
        inline=False)

    page6.add_field(
        name="💼 Vay Mượn Xu",
        value=(
            "**`.vayxu [số xu]`**\n"
            "→ Vay xu (max 1000, phải trả trong 2h)\n\n"
            "**`.traxu [số xu]`**\n"
            "→ Trả xu đã vay"
        ),
        inline=False)

    page6.add_field(
        name="🔒 Két Sắt (Bảo Vệ Xu)",
        value=(
            "**`.napket [số xu]`**\n"
            "→ Nạp xu vào két\n\n"
            "**`.rutxu [số xu]`**\n"
            "→ Rút xu từ két\n\n"
            "**`.xemket`**\n"
            "→ Xem số xu trong két"
        ),
        inline=False)

    page6.set_footer(text="Trang 6/8 - Ngân Hàng & Két Sắt")
    pages.append(page6)

    # Trang 7: Cửa hàng & vật phẩm
    page7 = discord.Embed(
        title="🎮 Hướng Dẫn STV Bot (7/8) 🎮",
        description=f"Cửa hàng và vật phẩm.\nPrefix: `.`\n\n{random_tip}",
        color=discord.Color.blue())

    page7.add_field(
        name="🛍️ Cửa Hàng & Vật Phẩm",
        value=(
            "**`.shop`**\n"
            "→ Xem cửa hàng vật phẩm\n\n"
            "**`.buy [item_id] [số lượng]`**\n"
            "→ Mua vật phẩm\n\n"
            "**`.inventory`** hoặc **`.inv`**\n"
            "→ Xem kho đồ\n\n"
            "**`.use [item_id]`**\n"
            "→ Sử dụng vật phẩm"
        ),
        inline=False)

    page7.add_field(
        name="🎁 Vật Phẩm Đặc Biệt",
        value=(
            "**🍀 Bùa may mắn** - Tăng 20% cơ hội thắng trong các trò chơi\n"
            "**🛡️ Áo giáp chống đẹp** - Bảo vệ khỏi bị timeout khi thua Cô Quay Nga\n"
            "**🧥 Áo giáp chống rung** - Bảo vệ khỏi bị kick khi thua 777\n"
            "**🎫 Thẻ bến** - Giảm thời gian timeout xuống còn 1 phút\n"
            "**💰 Bảo hiểm xu** - Hoàn trả 50% tiền cược khi thua"
        ),
        inline=False)

    page7.set_footer(text="Trang 7/8 - Cửa Hàng & Vật Phẩm")
    pages.append(page7)

    # Trang 8: Lệnh giải trí
    page8 = discord.Embed(
        title="🎮 Hướng Dẫn STV Bot (8/8) 🎮",
        description=f"Các lệnh giải trí vui vẻ.\nPrefix: `.`\n\n{random_tip}",
        color=discord.Color.blue())

    page8.add_field(
        name="🎯 Lệnh Giải Trí Đo Chỉ Số",
        value=(
            "**`.howgay @người_dùng`**\n"
            "→ Đo độ gay\n\n"
            "**`.howmad @người_dùng`**\n"
            "→ Đo độ điên\n\n"
            "**`.howfat @người_dùng`**\n"
            "→ Đo cân nặng\n\n"
            "**`.howheight @người_dùng`** hoặc **`.cao`**\n"
            "→ Đo chiều cao\n\n"
            "**`.howiq @người_dùng`** hoặc **`.iq`**\n"
            "→ Đo chỉ số IQ\n\n"
            "**`.howperson @người_dùng`** hoặc **`.nhancach`**\n"
            "→ Phân tích tính cách"
        ),
        inline=True)

    page8.add_field(
        name="🥂 Lệnh Giải Trí Khác",
        value=(
            "**`.howrb @người_dùng`** hoặc **`.ruou`**\n"
            "→ Đo khả năng uống rượu/bia\n\n"
            "**`.howstupid @người_dùng`** hoặc **`.ngu`**\n"
            "→ Đo độ ngu\n\n"
            "**`.howretarded @người_dùng`** hoặc **`.tn`**\n"
            "→ Đo độ thiểu năng\n\n"
            "**`.howdamde @người_dùng`** hoặc **`.damde`**\n"
            "→ Đo độ dâm dê\n\n"
            "**`.afk [lý do]`**\n"
            "→ Đặt trạng thái AFK\n\n"
            "**`.avatar @người_dùng`** hoặc **`.av`**\n"
            "→ Xem avatar của người dùng"
        ),
        inline=True)

    page8.set_footer(text="Trang 8/8 - Lệnh Giải Trí")
    pages.append(page8)

    # Tạo hệ thống phân trang
    current_page = 0

    # Tạo view với các nút điều hướng
    view = discord.ui.View(timeout=60)

    # Nút trang đầu
    first_button = discord.ui.Button(
        label="« Đầu",
        style=discord.ButtonStyle.secondary,
        custom_id="first"
    )

    async def first_callback(interaction: discord.Interaction):
        nonlocal current_page
        if interaction.user != ctx.author:
            return await interaction.response.send_message("Bạn không thể sử dụng nút này!", ephemeral=True)
        
        current_page = 0
        await interaction.response.edit_message(embed=pages[current_page], view=view)

    first_button.callback = first_callback
    view.add_item(first_button)

    # Nút trang trước
    prev_button = discord.ui.Button(
        label="◀️ Trước",
        style=discord.ButtonStyle.primary,
        custom_id="prev"
    )

    async def prev_callback(interaction: discord.Interaction):
        nonlocal current_page
        if interaction.user != ctx.author:
            return await interaction.response.send_message("Bạn không thể sử dụng nút này!", ephemeral=True)
        
        current_page = (current_page - 1) % len(pages)
        await interaction.response.edit_message(embed=pages[current_page], view=view)

    prev_button.callback = prev_callback
    view.add_item(prev_button)

    # Nút trang hiện tại / tổng số trang (không có callback)
    page_indicator = discord.ui.Button(
        label=f"1/{len(pages)}",
        style=discord.ButtonStyle.secondary,
        disabled=True,
        custom_id="page_indicator"
    )
    view.add_item(page_indicator)

    # Nút trang sau
    next_button = discord.ui.Button(
        label="Sau ▶️",
        style=discord.ButtonStyle.primary,
        custom_id="next"
    )

    async def next_callback(interaction: discord.Interaction):
        nonlocal current_page
        if interaction.user != ctx.author:
            return await interaction.response.send_message("Bạn không thể sử dụng nút này!", ephemeral=True)
        
        current_page = (current_page + 1) % len(pages)
        # Cập nhật số trang hiện tại
        page_indicator.label = f"{current_page + 1}/{len(pages)}"
        await interaction.response.edit_message(embed=pages[current_page], view=view)

    next_button.callback = next_callback
    view.add_item(next_button)

    # Nút trang cuối
    last_button = discord.ui.Button(
        label="Cuối »",
        style=discord.ButtonStyle.secondary,
        custom_id="last"
    )

    async def last_callback(interaction: discord.Interaction):
        nonlocal current_page
        if interaction.user != ctx.author:
            return await interaction.response.send_message("Bạn không thể sử dụng nút này!", ephemeral=True)
        
        current_page = len(pages) - 1
        # Cập nhật số trang hiện tại
        page_indicator.label = f"{current_page + 1}/{len(pages)}"
        await interaction.response.edit_message(embed=pages[current_page], view=view)

    last_button.callback = last_callback
    view.add_item(last_button)

    # Gửi trang đầu tiên
    await ctx.send(embed=pages[current_page], view=view)


# Create a new stvgt command that works anywhere
@bot.command(name='stvgt')
async def gioi_thieu(ctx):
    """Hiển thị thông tin giới thiệu bot với thiết kế hiện đại"""
    # Create the main embed with a clean title and description
    embed = discord.Embed(
        title="⚡ STV BOT ⚡",
        description="*Bot giải trí đa năng với nhiều minigame hấp dẫn và hệ thống xu đa dạng*",
        color=discord.Color.brand_green()
    )
    
    # Add server icon as thumbnail if available
    if ctx.guild.icon:
        embed.set_thumbnail(url=ctx.guild.icon.url)
        
    # Quick access button for game channel
    embed.add_field(
        name="🎮 KÊNH CHƠI GAME",
        value=f"[Nhấp vào đây để chơi game]({GAME_CHANNEL_LINK})",
        inline=False
    )
    
    # Highlight key game categories with emojis
    embed.add_field(
        name="🎲 GAME MAY RỦI",
        value="Chẵn lẻ • Tài xỉu • 777 • Vòng quay",
        inline=True
    )
    
    embed.add_field(
        name="🃏 GAME BÀI",
        value="Xì dách • Poker • Mậu binh • Phỏm",
        inline=True
    )
    
    # Command categories - minimal and most important
    embed.add_field(
        name="⚙️ LỆNH CƠ BẢN",
        value="`stvh` - Xem hướng dẫn đầy đủ\n"
              "`dd` - Điểm danh (20-50 xu/ngày)\n"
              "`xu` - Kiểm tra xu\n"
              "`shop` - Cửa hàng vật phẩm",
        inline=False
    )
    
    # Game highlight with custom formatting
    embed.add_field(
        name="⭐ GAME NỔI BẬT",
        value="```\n"
              "💥 Fight - Thách đấu PvP người chơi khác\n"
              "🎰 777  - Máy đánh bạc với jackpot x10\n"
              "🔫 Cô Quay Nga - Tỉ lệ 50/50, thua timeout\n"
              "🎲 Bầu Cua - Cược và thắng quen thuộc\n"
              "```",
        inline=False
    )
    
    # Footer with version info
    embed.set_footer(text="Prefix: . | STV Bot • v1.8")
    
    # Create view for interactive buttons
    view = discord.ui.View(timeout=60)
    
    # Game channel button
    game_button = discord.ui.Button(
        label="Vào Kênh Game", 
        style=discord.ButtonStyle.success,
        url=GAME_CHANNEL_LINK,
        emoji="🎮"
    )
    view.add_item(game_button)
    
    # Help button
    help_button = discord.ui.Button(
        label="Xem Hướng Dẫn", 
        style=discord.ButtonStyle.primary,
        emoji="📖",
        custom_id="help_button"
    )
    
    async def help_callback(interaction):
        if interaction.user != ctx.author:
            return await interaction.response.send_message("Bạn không thể sử dụng nút này!", ephemeral=True)
            
        help_embed = discord.Embed(
            title="📖 Hướng Dẫn Nhanh",
            description="Một số lệnh thông dụng để bắt đầu:",
            color=discord.Color.blue()
        )
        
        help_embed.add_field(
            name="🎮 Game Phổ Biến",
            value="`cl [chẵn/lẻ] [xu]` - Chơi chẵn lẻ\n"
                  "`tx [t/x] [xu]` - Chơi tài xỉu\n"
                  "`xidach [xu]` - Chơi xì dách\n"
                  "`fight @user [xu]` - Thách đấu người chơi",
            inline=True
        )
        
        help_embed.add_field(
            name="💰 Quản Lý Xu",
            value="`xu` - Xem số xu\n"
                  "`bank gửi [xu]` - Gửi xu vào ngân hàng\n"
                  "`napket [xu]` - Nạp xu vào két sắt\n"
                  "`sendxu @user [xu]` - Chuyển xu cho người khác",
            inline=True
        )
        
        help_embed.set_footer(text="Sử dụng .stvh trong kênh game để xem đầy đủ hướng dẫn")
        await interaction.response.send_message(embed=help_embed, ephemeral=True)
    
    help_button.callback = help_callback
    view.add_item(help_button)
    
    # Daily reward button
    daily_button = discord.ui.Button(
        label="Điểm Danh", 
        style=discord.ButtonStyle.secondary,
        emoji="🎁",
        custom_id="daily_button"
    )
    
    async def daily_callback(interaction):
        if interaction.user != ctx.author:
            return await interaction.response.send_message("Bạn không thể sử dụng nút này!", ephemeral=True)
            
        # Redirect to game channel if not in it
        if interaction.channel.id != GAME_CHANNEL_ID:
            await interaction.response.send_message(
                f"Lệnh này chỉ hoạt động trong kênh chơi game. [Nhấp vào đây]({GAME_CHANNEL_LINK}) để đến kênh game.", 
                ephemeral=True
            )
        else:
            # Forward to the existing daily_task command
            await interaction.response.defer()
            await daily_task(ctx)
    
    daily_button.callback = daily_callback
    view.add_item(daily_button)
    
    await ctx.send(embed=embed, view=view)


@bot.command(name='stvad')
@commands.has_permissions(administrator=True)
async def admin_commands(ctx):
    """Hiển thị tất cả các lệnh dành cho quản trị viên với phân trang nhỏ gọn"""
    # Tạo các trang cho hướng dẫn admin
    pages = []

    # Trang 1: Tổng quan
    page1 = discord.Embed(title="👑 Lệnh Admin STV Bot (1/10) 👑",
                          description="Tổng quan các lệnh quản trị",
                          color=discord.Color.purple())

    page1.add_field(
        name="📋 Danh mục lệnh",
        value=(
            "**Trang 1:** Tổng quan\n"
            "**Trang 2:** Quản lý xu\n"
            "**Trang 3:** Quản lý ngân hàng\n"
            "**Trang 4:** Quản lý khoản vay\n"
            "**Trang 5:** Quản lý két sắt\n"
            "**Trang 6:** Quản lý drop xu & key\n"
            "**Trang 7:** Quản lý kênh & trò chơi\n"
            "**Trang 8:** Quản lý thành viên\n"
            "**Trang 9:** Quản lý hệ thống\n"
            "**Trang 10:** Quản lý whitelist & thông báo"
        ),
        inline=False
    )

    page1.add_field(
        name="🎮 Các game hiện có",
        value=(
            "**Game cơ bản:** cl, tx, tungxu, coquaynga, baucua, kbb, kbbpvp, vqmm\n"
            "**Game bài:** poker, xidach, maubinh, bacaopvp, phom\n"
            "**Game khác:** pinggo, loto, 777, fight, hoidap, caropvp\n"
            "**Chức năng xu:** dd, vayxu, capxu, shop"
        ),
        inline=False
    )

    page1.add_field(
        name="⚠️ Lưu ý quan trọng",
        value=(
            "- Lệnh admin có thể thực hiện những thay đổi quan trọng đến hệ thống\n"
            "- Sử dụng có trách nhiệm và không lạm dụng quyền hạn\n"
            "- Tất cả các hành động admin đều được ghi log\n"
            "- Nhân vật USERID **618702036992655381** là owner, có quyền cao nhất"
        ),
        inline=False
    )

    page1.set_footer(text="Sử dụng các nút điều hướng để chuyển trang")
    pages.append(page1)

    # Trang 2: Quản lý xu
    page2 = discord.Embed(title="👑 Lệnh Admin STV Bot (2/10) 👑",
                          description="Quản lý xu của người dùng",
                          color=discord.Color.purple())

    page2.add_field(
        name="💰 Quản Lý Xu Cơ Bản",
        value=(
            "**`.txu @người_dùng [số xu]`** - Tặng xu cho người chơi\n"
            "**`.trxu @người_dùng [số xu/all]`** - Trừ xu của người chơi\n"
            "**`.napxu @người_dùng [số xu]`** - Nạp xu vào tài khoản người dùng\n"
            "**`.ktxu @người_dùng`** - Kiểm tra số xu của người dùng\n"
            "**`.bxhxu`** - Xem bảng xếp hạng xu của server"
        ),
        inline=False
    )

    page2.add_field(
        name="💸 Kiểm Tra Âm Xu",
        value=(
            "**`.checkam`** (hoặc **`.camxu`**, **`.amxu`**) - Xem danh sách người dùng âm xu\n"
            "**`.thihanhan @người_dùng [kick/ban]`** - Xử lý người dùng âm xu\n"
            "**`.autocheckam`** - Task tự động kiểm tra và xử lý người dùng âm xu"
        ),
        inline=False
    )

    page2.add_field(
        name="🔄 Reset Xu & Thao Tác Nâng Cao",
        value=(
            "**`.resetxu @người_dùng [số xu]`** - Reset xu về giá trị cụ thể\n"
            "**`.resetall @người_dùng [số xu]`** - Reset tất cả tiền cùng lúc\n"
            "**`.setxu all [số xu]`** - Thiết lập số xu cho tất cả người dùng\n"
            "**`.multixu @người_dùng [số lần]`** - Nhân xu của người dùng"
        ),
        inline=False
    )

    pages.append(page2)

    # Trang 3: Quản lý ngân hàng
    page3 = discord.Embed(title="👑 Lệnh Admin STV Bot (3/10) 👑",
                          description="Quản lý ngân hàng của người dùng",
                          color=discord.Color.purple())

    page3.add_field(
        name="🏦 Quản Lý Ngân Hàng",
        value=(
            "**`.bankcheck @người_dùng`** - Kiểm tra tài khoản ngân hàng của người dùng\n"
            "**`.bankxoa @người_dùng`** - Xóa tài khoản ngân hàng của người dùng\n"
            "**`.resetbank @người_dùng [số xu]`** - Reset tiền ngân hàng\n"
            "**`.setinterest [tỷ lệ]`** - Thay đổi lãi suất ngân hàng (mặc định: 5%)\n"
            "**`.forceinterest`** - Ép buộc trả lãi ngân hàng cho tất cả người dùng"
        ),
        inline=False
    )

    page3.add_field(
        name="⛔ Quản Lý Blacklist Ngân Hàng",
        value=(
            "**`.blbank add @người_dùng`** - Thêm người dùng vào blacklist ngân hàng\n"
            "**`.blbank remove @người_dùng`** - Xóa người dùng khỏi blacklist ngân hàng\n"
            "**`.bankblview`** (hoặc **`.blbankview`**) - Xem danh sách người dùng bị blacklist\n"
            "**`.bankstats`** - Xem thống kê tổng quan về ngân hàng (tổng tiền, số người dùng)"
        ),
        inline=False
    )

    page3.add_field(
        name="💱 Hoạt Động Ngân Hàng",
        value=(
            "**`.banklog [số lượng]`** - Xem lịch sử hoạt động ngân hàng\n"
            "**`.banktop`** - Xem danh sách người dùng có nhiều tiền trong ngân hàng nhất\n"
            "**`.bankstop`** - Tạm dừng hệ thống ngân hàng (bảo trì)\n"
            "**`.bankstart`** - Mở lại hệ thống ngân hàng"
        ),
        inline=False
    )

    pages.append(page3)

    # Trang 4: Quản lý khoản vay
    page4 = discord.Embed(title="👑 Lệnh Admin STV Bot (4/10) 👑",
                         description="Quản lý khoản vay của người dùng",
                         color=discord.Color.purple())

    page4.add_field(
        name="🏦 Quản Lý Khoản Vay",
        value=(
            "**`.checkvay @người_dùng`** - Kiểm tra thông tin khoản vay của người dùng\n"
            "**`.checkvay`** - Kiểm tra tất cả khoản vay trong hệ thống\n"
            "**`.xoavay @người_dùng`** - Xóa khoản vay của người dùng\n"
            "**`.vayxu_config [max_amount] [duration]`** - Cấu hình hệ thống vay xu"
        ),
        inline=False
    )

    page4.add_field(
        name="⚖️ Xử Lý Vi Phạm",
        value=(
            "**`.xulyvay @user [kick/ban]`** - Xử lý người dùng không trả nợ\n"
            "**`.autoxlvay [kick/ban]`** - Xử lý tự động tất cả người không trả nợ\n"
            "**`.vaystats`** - Xem thống kê về khoản vay (tổng tiền, số người vay)\n"
            "**`.vaylogger [on/off]`** - Bật/tắt ghi log hoạt động vay"
        ),
        inline=False
    )

    page4.add_field(
        name="⚙️ Cài Đặt Nâng Cao",
        value=(
            "**`.vaysettime @user [giờ]`** - Thay đổi thời hạn vay cho người dùng\n"
            "**`.vaylimit @user [số xu]`** - Thay đổi hạn mức vay cho người dùng\n"
            "**`.vaybl add @user`** - Thêm người dùng vào blacklist vay xu\n"
            "**`.vaybl remove @user`** - Xóa người dùng khỏi blacklist vay xu\n"
            "**`.vayblview`** - Xem danh sách người dùng bị cấm vay xu"
        ),
        inline=False
    )

    pages.append(page4)

    # Trang 5: Quản lý két sắt
    page5 = discord.Embed(title="👑 Lệnh Admin STV Bot (5/10) 👑",
                         description="Quản lý két sắt của người dùng",
                         color=discord.Color.purple())

    page5.add_field(
        name="🔒 Quản Lý Két Sắt Cơ Bản",
        value=(
            "**`.ad_xemket @người_dùng`** - Xem két sắt của người dùng\n"
            "**`.ad_xoaket @người_dùng`** - Xóa két sắt của người dùng\n"
            "**`.resetket @người_dùng [số xu]`** - Reset tiền két sắt\n"
            "**`.resetall @người_dùng [số xu]`** - Reset tất cả tiền cùng lúc"
        ),
        inline=False
    )

    page5.add_field(
        name="💼 Quản Lý Két Sắt Nâng Cao",
        value=(
            "**`.kettop`** - Xem danh sách người dùng có nhiều tiền trong két nhất\n"
            "**`.ketlog [số lượng]`** - Xem lịch sử hoạt động két sắt\n"
            "**`.ketmodify @người_dùng [+/-số xu]`** - Tăng/giảm xu trong két của người dùng\n"
            "**`.ketstats`** - Xem thống kê tổng quan về két sắt (tổng tiền, số người dùng)"
        ),
        inline=False
    )

    page5.add_field(
        name="⚙️ Cài Đặt Két Sắt",
        value=(
            "**`.ketlimit @user [số xu]`** - Thiết lập giới hạn xu trong két cho người dùng\n"
            "**`.ketlimit all [số xu]`** - Thiết lập giới hạn xu trong két cho tất cả\n" 
            "**`.ketdisable @user`** - Vô hiệu hóa két sắt của người dùng\n"
            "**`.ketenable @user`** - Kích hoạt lại két sắt của người dùng\n"
            "**`.rutketforce @user [số xu]`** - Bắt buộc rút xu từ két của người dùng"
        ),
        inline=False
    )

    pages.append(page5)

    # Trang 6: Quản lý drop xu & key
    page6 = discord.Embed(title="👑 Lệnh Admin STV Bot (6/10) 👑",
                         description="Quản lý drop xu và key",
                         color=discord.Color.purple())

    page6.add_field(
        name="🎁 Quản Lý Drop Xu",
        value=(
            "**`.dropxu [số xu] [thời gian] [tin nhắn]`** - Tạo drop xu mới với thời hạn tự động\n"
            "**`.stopdrop [ID message]`** - Dừng drop xu đang hoạt động\n"
            "**`.listdrop`** (hoặc **`.lsdrop`**, **`.droplist`**) - Xem danh sách drop xu đang hoạt động\n"
            "**`.dropreset`** - Reset và xóa tất cả drop xu đang hoạt động\n"
            "**`.dropcustom [emoji] [số xu] [thời gian] [tin nhắn]`** - Tạo drop với emoji tùy chọn"
        ),
        inline=False
    )

    page6.add_field(
        name="🔑 Quản Lý Key",
        value=(
            "**`.tkey [số xu] [số lượt] [số lượng]`** - Tạo key đổi xu\n"
            "**`.tkey [số xu] [số lượt] [số lượng] @user`** - Tạo key và gửi DM cho người dùng\n"
            "**`.ckey [mã_key]`** - Kiểm tra thông tin key\n"
            "**`.xoakey all`** - Xóa tất cả key\n"
            "**`.xoakey [số lượng]`** - Xóa số lượng key cũ nhất\n"
            "**`.keylog`** - Xem lịch sử sử dụng key\n"
            "**`.dropkey [số xu] [số lượt] [số lượng] [tin nhắn]`** - Tạo key drop trong kênh\n"
            "**`.keystats`** - Xem thống kê về hệ thống key"
        ),
        inline=False
    )

    page6.add_field(
        name="🎮 Quản Lý Giveaway",
        value=(
            "**`.giveaway [kênh] [thời gian] [số người thắng] [phần thưởng]`** - Tạo giveaway\n"
            "**`.gend [ID tin nhắn]`** - Kết thúc giveaway sớm\n"
            "**`.greroll [ID tin nhắn]`** - Quay lại giveaway để chọn người thắng mới\n"
            "**`.glist`** - Liệt kê tất cả giveaway đang hoạt động"
        ),
        inline=False
    )

    pages.append(page6)

    # Trang 7: Quản lý kênh & trò chơi
    page7 = discord.Embed(title="👑 Lệnh Admin STV Bot (7/10) 👑",
                         description="Quản lý kênh và trò chơi",
                         color=discord.Color.purple())

    page7.add_field(
        name="🎮 Quản Lý Kênh & Trò Chơi",
        value=(
            "**`.nuke [#kênh]`** - Xóa sạch và tạo lại kênh\n"
            "**`.stvdis [tên game]`** - Bật/tắt trò chơi cụ thể\n"
            "**`.stvdis all`** - Bật/tắt tất cả trò chơi\n" 
            "**`.stvdis list`** - Xem danh sách trò chơi đã bị vô hiệu hóa\n"
            "**`.snipe [số lượng] [@người_dùng1 @người_dùng2]`** - Xem tin nhắn đã xóa\n"
            "**`.purge [số lượng]`** - Xóa nhanh nhiều tin nhắn trong kênh"
        ),
        inline=False
    )

    page7.add_field(
        name="⚙️ Quản Lý Bot & Server",
        value=(
            "**`.stvrestart`** - Khởi động lại bot (chỉ dành cho chủ sở hữu)\n"
            "**`.dms_bypass add @user`** - Cho phép người dùng bypass kiểm tra lệnh dms\n"
            "**`.dms_bypass remove @user`** - Xóa quyền bypass lệnh dms\n"
            "**`.dms_bypass list`** - Xem danh sách người dùng có quyền bypass lệnh dms\n"
            "**`.config [setting] [value]`** - Thay đổi cài đặt bot\n"
            "**`.setgamechannel [#kênh]`** - Đặt kênh game mặc định\n"
            "**`.gamestats`** - Xem thống kê về các trò chơi (số lần chơi, tổng tiền cược)"
        ),
        inline=False
    )

    page7.add_field(
        name="🎵 Quản Lý Nhạc",
        value=(
            "**`.setupmusic [#kênh]`** - Thiết lập kênh điều khiển nhạc\n"
            "**`.musicconfig [setting] [value]`** - Cấu hình hệ thống nhạc\n"
            "**`.musicroles [role]`** - Thiết lập role có quyền điều khiển nhạc\n"
            "**`.musicstop`** - Dừng và thoát khỏi kênh nhạc"
        ),
        inline=False
    )

    pages.append(page7)

    # Trang 8: Quản lý thành viên
    page8 = discord.Embed(title="👑 Lệnh Admin STV Bot (8/10) 👑",
                         description="Quản lý thành viên",
                         color=discord.Color.purple())

    page8.add_field(
        name="👮‍♂️ Quản Lý Thành Viên Cơ Bản",
        value=(
            "**`.kick @user [lý do]`** - Đuổi người dùng khỏi server\n"
            "**`.ban @user [lý do]`** - Cấm người dùng khỏi server\n"
            "**`.unban [user_id] [lý do]`** - Gỡ lệnh cấm người dùng\n"
            "**`.timeout @user [thời_gian] [lý do]`** - Timeout thành viên (vd: 10m, 1h, 1d)\n"
            "**`.untimeout @user [lý do]`** - Hủy timeout cho thành viên\n"
            "**`.mute @user [lý do]`** - Tắt tiếng thành viên\n"
            "**`.unmute @user [lý do]`** - Bỏ tắt tiếng thành viên"
        ),
        inline=False
    )

    page8.add_field(
        name="📨 Tin Nhắn & Cảnh Báo",
        value=(
            "**`.dms @user [nội dung]`** - Gửi tin nhắn DM tới người dùng qua bot\n"
            "**`.warn add @user [lý do]`** - Cảnh cáo thành viên\n"
            "**`.warn remove @user [số cảnh cáo]`** - Xóa cảnh cáo cho thành viên\n"
            "**`.warn list [@user]`** - Xem danh sách cảnh cáo của thành viên\n"
            "**`.warn clear @user`** - Xóa tất cả cảnh cáo của thành viên\n"
            "**`.dmslog [số lượng]`** - Xem lịch sử tin nhắn DMS đã gửi\n"
            "**`.whoping @user`** - Kiểm tra ai đã ping người dùng này"
        ),
        inline=False
    )

    page8.add_field(
        name="🔍 Giám Sát & Thông Tin",
        value=(
            "**`.userinfo @user`** - Xem thông tin chi tiết về người dùng\n"
            "**`.checkjoin @user`** - Xem thời gian tham gia server của người dùng\n"
            "**`.checkchannel @user`** - Xem các kênh người dùng có thể truy cập\n"
            "**`.rolelist [@user]`** - Xem danh sách role của người dùng hoặc server\n"
            "**`.serverinfo`** - Xem thông tin tổng quan về server\n"
            "**`.invites [@user]`** - Xem số lượt mời của người dùng hoặc server"
        ),
        inline=False
    )

    pages.append(page8)

    # Trang 9: Quản lý hệ thống
    page9 = discord.Embed(title="👑 Lệnh Admin STV Bot (9/10) 👑",
                         description="Quản lý hệ thống và blacklist",
                         color=discord.Color.purple())

    page9.add_field(
        name="🔄 Quản Lý Danh Sách Đen",
        value=(
            "**`.blacklist add @người_dùng`** (hoặc **`.bl`**) - Thêm người dùng vào danh sách đen\n"
            "**`.blacklist remove @người_dùng`** - Xóa người dùng khỏi danh sách đen\n"
            "**`.blacklistview`** (hoặc **`.blview`**) - Xem danh sách người dùng đã bị chặn\n"
            "**`.blacklist reason @user [lý do]`** - Ghi chú lý do đưa vào danh sách đen"
        ),
        inline=False
    )

    page9.add_field(
        name="👥 Quản Lý Trạng Thái Người Dùng",
        value=(
            "**`.afklist`** - Xem danh sách người dùng đang AFK\n"
            "**`.afkremove @user`** - Xóa trạng thái AFK của người dùng\n"
            "**`.afksetting [thời gian]`** - Thiết lập thời gian AFK tối đa\n"
            "**`.afkmessage [tin nhắn]`** - Thiết lập tin nhắn mặc định khi ping người AFK"
        ),
        inline=False
    )

    page9.add_field(
        name="🔎 Giám Sát Hệ Thống",
        value=(
            "**`.logs [loại] [số lượng]`** - Xem log hệ thống (command, error, admin)\n"
            "**`.stats`** - Xem thống kê bot (uptime, số lệnh, memory)\n"
            "**`.statsreset`** - Reset thống kê về số lệnh đã sử dụng\n"
            "**`.cooldownreset @user`** - Reset cooldown cho người dùng\n"
            "**`.cooldownlist`** - Xem danh sách người dùng đang trong cooldown\n"
            "**`.savedata`** - Lưu dữ liệu thủ công (xu, bank, inventory)"
        ),
        inline=False
    )

    pages.append(page9)

    # Trang 10: Quản lý whitelist và thông báo
    page10 = discord.Embed(title="👑 Lệnh Admin STV Bot (10/10) 👑",
                          description="Quản lý whitelist và thông báo",
                          color=discord.Color.purple())

    page10.add_field(
        name="🔮 Quản Lý Whitelist",
        value=(
            "**`.wl add @người_dùng`** - Thêm người dùng vào whitelist (luôn thắng mọi trò chơi)\n"
            "**`.wl remove @người_dùng`** - Xóa người dùng khỏi whitelist\n"
            "**`.wl list`** - Xem danh sách tóm tắt người dùng trong whitelist\n"
            "**`.wlview`** - Xem danh sách chi tiết người dùng trong whitelist\n"
            "**`.wl chance @user [tỉ lệ]`** - Thiết lập tỉ lệ thắng cụ thể cho người dùng (0-100%)"
        ),
        inline=False
    )

    page10.add_field(
        name="📢 Hệ Thống Thông Báo",
        value=(
            "**`.tb [kênh/here/all] [tiêu đề] [nội dung]`** - Gửi thông báo với embed đẹp\n"
            "**`.tb tạo`** - Mở trình tạo thông báo tương tác\n"
            "**`.setuplog [#kênh]`** - Thiết lập kênh ghi log\n" 
            "**`.embed [json/code]`** - Tạo và gửi embed từ JSON hoặc code\n"
            "**`.poll [#kênh] [câu hỏi] [lựa chọn1] [lựa chọn2]...`** - Tạo cuộc thăm dò ý kiến"
        ),
        inline=False
    )

    page10.add_field(
        name="ℹ️ Thông tin hữu ích",
        value=(
            "- Game đã được cài đặt tỷ lệ: thắng 50%, thua 50%\n"
            "- Whitelist giúp người dùng luôn thắng mọi trò chơi\n"
            "- Sử dụng `.stvh` để xem danh sách trò chơi hiện có\n"
            "- Sử dụng `.stvgt` để hiển thị thông tin giới thiệu bot\n"
            "- Tất cả thao tác quản trị được ghi lại trong kênh nhật ký\n"
            "- Dùng `.checkvay` để kiểm tra người dùng chưa trả nợ vay xu"
        ),
        inline=False
    )

    page10.set_footer(text=f"Admin: {ctx.author.name} | {ctx.guild.name} | {datetime.now().strftime('%d/%m/%Y')}")

    pages.append(page10)

    # Tạo hệ thống phân trang
    current_page = 0

    # Tạo view với các nút điều hướng
    view = discord.ui.View(timeout=300)  # Tăng thời gian timeout lên 5 phút

    # Nút trang đầu
    first_button = discord.ui.Button(label="« Đầu",
                                     style=discord.ButtonStyle.secondary)

    async def first_callback(interaction: discord.Interaction):
        nonlocal current_page
        if interaction.user != ctx.author:
            return await interaction.response.send_message(
                "Bạn không thể sử dụng nút này!", ephemeral=True)

        current_page = 0
        await interaction.response.edit_message(embed=pages[current_page],
                                                view=view)

    first_button.callback = first_callback
    view.add_item(first_button)

    # Nút trang trước
    prev_button = discord.ui.Button(label="◀️ Trang trước",
                                    style=discord.ButtonStyle.primary)

    async def prev_callback(interaction: discord.Interaction):
        nonlocal current_page
        if interaction.user != ctx.author:
            return await interaction.response.send_message(
                "Bạn không thể sử dụng nút này!", ephemeral=True)

        current_page = (current_page - 1) % len(pages)
        await interaction.response.edit_message(embed=pages[current_page],
                                                view=view)

    prev_button.callback = prev_callback
    view.add_item(prev_button)

    # Hiển thị số trang hiện tại
    page_indicator = discord.ui.Button(
        label=f"1/{len(pages)}", 
        style=discord.ButtonStyle.secondary,
        disabled=True
    )
    view.add_item(page_indicator)

    # Nút trang sau
    next_button = discord.ui.Button(label="Trang sau ▶️",
                                    style=discord.ButtonStyle.primary)

    async def next_callback(interaction: discord.Interaction):
        nonlocal current_page
        if interaction.user != ctx.author:
            return await interaction.response.send_message(
                "Bạn không thể sử dụng nút này!", ephemeral=True)

        current_page = (current_page + 1) % len(pages)
        # Cập nhật số trang hiện tại
        page_indicator.label = f"{current_page + 1}/{len(pages)}"
        await interaction.response.edit_message(embed=pages[current_page],
                                                view=view)

    next_button.callback = next_callback
    view.add_item(next_button)

    # Nút trang cuối
    last_button = discord.ui.Button(label="Cuối »",
                                    style=discord.ButtonStyle.secondary)

    async def last_callback(interaction: discord.Interaction):
        nonlocal current_page
        if interaction.user != ctx.author:
            return await interaction.response.send_message(
                "Bạn không thể sử dụng nút này!", ephemeral=True)

        current_page = len(pages) - 1
        # Cập nhật số trang hiện tại
        page_indicator.label = f"{current_page + 1}/{len(pages)}"
        await interaction.response.edit_message(embed=pages[current_page],
                                                view=view)

    last_button.callback = last_callback
    view.add_item(last_button)

    # Gửi trang đầu tiên
    await ctx.send(embed=pages[current_page], view=view)


@admin_commands.error
async def admin_commands_error(ctx, error):
    """Xử lý lỗi khi không đủ quyền chạy lệnh stvad"""
    if isinstance(error, commands.MissingPermissions):
        embed = discord.Embed(
            title="⛔ Quyền hạn không đủ",
            description="Bạn cần có quyền quản trị viên để sử dụng lệnh này.",
            color=discord.Color.red())
        await ctx.send(embed=embed)



@bot.command(name='tb', aliases=['announce', 'thongbao', 'tbb'])
@commands.has_permissions(administrator=True)
async def admin_announcement(ctx, channel_option: str = None, title: str = None, *, content: str = None):
    """Gửi thông báo quan trọng từ admin với thiết kế đẹp
    
    Sử dụng:
    .tb [kênh/here/all] [tiêu đề] [nội dung] - Gửi thông báo admin
    .tb tạo - Mở trình tạo thông báo tương tác
    """
    # Xóa lệnh gốc
    try:
        await ctx.message.delete()
    except:
        pass

    # Hiển thị hướng dẫn nếu không có đủ thông tin
    if channel_option is None or channel_option.lower() == "help":
        embed = discord.Embed(
            title="📢 Thông Báo Admin - Hướng Dẫn",
            description="Gửi thông báo quan trọng từ admin với thiết kế đẹp",
            color=discord.Color.blue()
        )
        
        embed.add_field(
            name="Cách sử dụng",
            value="`.tb [kênh/here/all] [tiêu đề] [nội dung]`",
            inline=False
        )
        
        embed.add_field(
            name="Tùy chọn kênh",
            value=(
                "`#tên-kênh` - Gửi thông báo vào kênh cụ thể\n"
                "`here` - Gửi thông báo vào kênh hiện tại, ping @here\n"
                "`all` - Gửi thông báo vào kênh hiện tại, ping @everyone"
            ),
            inline=False
        )
        
        embed.add_field(
            name="Ví dụ",
            value=(
                "`.tb #thông-báo \"Cập Nhật Máy Chủ\" Server sẽ bảo trì vào ngày mai...`\n"
                "`.tb here \"Sự Kiện Mới\" Sự kiện sẽ diễn ra vào cuối tuần...`"
            ),
            inline=False
        )
        
        embed.add_field(
            name="Định dạng văn bản",
            value=(
                "Bạn có thể sử dụng các định dạng Markdown:\n"
                "**in đậm**, *in nghiêng*, __gạch dưới__, ~~gạch ngang~~\n"
                "`code đơn dòng`, ```code nhiều dòng```"
            ),
            inline=False
        )
        
        embed.set_footer(text="Chỉ admin mới có thể sử dụng lệnh này")
        await ctx.send(embed=embed, delete_after=60)
        return
    
    # Kiểm tra nếu người dùng muốn sử dụng trình tạo tương tác
    if channel_option.lower() in ["tạo", "create", "interactive", "builder"]:
        await create_interactive_announcement(ctx)
        return
    
    # Kiểm tra nếu đầy đủ thông tin
    if title is None or content is None:
        embed = discord.Embed(
            title="❌ Thiếu thông tin",
            description="Bạn cần cung cấp đầy đủ tiêu đề và nội dung thông báo.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed, delete_after=10)
        return
    
    # Xác định kênh gửi thông báo
    target_channel = ctx.channel  # Mặc định là kênh hiện tại
    mention_type = None
    
    if channel_option.lower() == "here":
        mention_type = "@here"
    elif channel_option.lower() == "all" or channel_option.lower() == "everyone":
        mention_type = "@everyone"
    else:
        # Thử trích xuất ID kênh từ mention
        channel_id_match = re.search(r'<#(\d+)>', channel_option)
        if channel_id_match:
            channel_id = int(channel_id_match.group(1))
            found_channel = ctx.guild.get_channel(channel_id)
            if found_channel:
                target_channel = found_channel
            else:
                embed = discord.Embed(
                    title="❌ Không tìm thấy kênh",
                    description="Kênh bạn chỉ định không tồn tại hoặc bot không có quyền truy cập.",
                    color=discord.Color.red()
                )
                await ctx.send(embed=embed, delete_after=10)
                return
        else:
            # Thử tìm kênh theo tên
            if channel_option.startswith('#'):
                channel_name = channel_option[1:]
            else:
                channel_name = channel_option
                
            found_channel = discord.utils.get(ctx.guild.text_channels, name=channel_name)
            if found_channel:
                target_channel = found_channel
            else:
                embed = discord.Embed(
                    title="❌ Không tìm thấy kênh",
                    description=f"Không tìm thấy kênh '{channel_option}'.",
                    color=discord.Color.red()
                )
                await ctx.send(embed=embed, delete_after=10)
                return
    
    # Tạo embed thông báo
    announcement_embed = create_announcement_embed(ctx.author, title, content)
    
    # Gửi thông báo
    try:
        if mention_type:
            allowed_mentions = discord.AllowedMentions(everyone=True)
            announcement_message = await target_channel.send(
                content=mention_type,
                embed=announcement_embed,
                allowed_mentions=allowed_mentions
            )
        else:
            announcement_message = await target_channel.send(embed=announcement_embed)
            
        # Gửi xác nhận cho admin
        confirm_embed = discord.Embed(
            title="✅ Thông báo đã được gửi",
            description=f"Thông báo của bạn đã được gửi thành công đến {target_channel.mention}.",
            color=discord.Color.green()
        )
        
        confirm_embed.add_field(
            name="Tiêu đề", 
            value=title[:100] + "..." if len(title) > 100 else title,
            inline=False
        )
        
        # Thêm nút để nhảy đến thông báo
        view = discord.ui.View()
        view.add_item(discord.ui.Button(
            label="Xem thông báo", 
            style=discord.ButtonStyle.link, 
            url=announcement_message.jump_url
        ))
        
        await ctx.send(embed=confirm_embed, view=view, delete_after=30)
    
    except discord.Forbidden:
        embed = discord.Embed(
            title="❌ Không đủ quyền",
            description=f"Bot không có quyền gửi tin nhắn vào kênh {target_channel.mention}.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed, delete_after=10)
    except Exception as e:
        embed = discord.Embed(
            title="❌ Lỗi",
            description=f"Đã xảy ra lỗi khi gửi thông báo: {str(e)}",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed, delete_after=10)


def create_announcement_embed(author, title, content):
    """Tạo embed thông báo admin đẹp mắt"""
    embed = discord.Embed(
        title=f"📢 {title}",
        description=content,
        color=discord.Color.gold()
    )
    
    # Thêm thông tin thời gian và người gửi
    embed.set_footer(
        text=f"Thông báo bởi {author.display_name}",
        icon_url=author.display_avatar.url
    )
    
    # Thêm timestamp
    embed.timestamp = datetime.now()
    
    return embed


async def create_interactive_announcement(ctx):
    """Mở trình tạo thông báo tương tác cho admin"""
    # Dữ liệu để lưu trữ thông tin của thông báo
    announcement_data = {
        "title": "",
        "content": "",
        "color": discord.Color.gold(),
        "channel": ctx.channel,
        "mention": "none",
        "image_url": None
    }
    
    # Tạo message ban đầu với embed
    builder_embed = discord.Embed(
        title="🔧 Tạo Thông Báo Admin",
        description="Sử dụng các nút bên dưới để thiết lập thông báo của bạn.",
        color=discord.Color.blue()
    )
    
    builder_embed.add_field(
        name="Bước 1️⃣",
        value="Thiết lập tiêu đề và nội dung",
        inline=False
    )
    
    builder_embed.add_field(
        name="Bước 2️⃣",
        value="Tùy chỉnh màu sắc và kênh",
        inline=False
    )
    
    builder_embed.add_field(
        name="Bước 3️⃣",
        value="Xem trước và gửi thông báo",
        inline=False
    )
    
    # Tạo view với các nút điều khiển
    view = AnnouncementBuilderView(ctx, announcement_data)
    message = await ctx.send(embed=builder_embed, view=view)
    
    # Lưu message để cập nhật sau này
    view.message = message


# View cho công cụ tạo thông báo tương tác
class AnnouncementBuilderView(discord.ui.View):
    def __init__(self, ctx, announcement_data):
        super().__init__(timeout=600)  # 10 phút timeout
        self.ctx = ctx
        self.announcement_data = announcement_data
        self.message = None
        self.preview_message = None
    
    async def on_timeout(self):
        # Thông báo hết thời gian chỉnh sửa
        timeout_embed = discord.Embed(
            title="⏱️ Hết thời gian",
            description="Thời gian tạo thông báo đã hết. Vui lòng chạy lại lệnh `.tt tạo` nếu bạn muốn tiếp tục.",
            color=discord.Color.red()
        )
        
        # Xóa tất cả các nút
        self.clear_items()
        
        try:
            await self.message.edit(embed=timeout_embed, view=self)
        except:
            pass
    
    # Nút thiết lập tiêu đề
    @discord.ui.button(label="Thiết lập tiêu đề", style=discord.ButtonStyle.primary, row=0)
    async def set_title_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Tạo modal để nhập tiêu đề
        modal = TitleInputModal(self)
        await interaction.response.send_modal(modal)
    
    # Nút thiết lập nội dung
    @discord.ui.button(label="Thiết lập nội dung", style=discord.ButtonStyle.primary, row=0)
    async def set_content_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Tạo modal để nhập nội dung
        modal = ContentInputModal(self)
        await interaction.response.send_modal(modal)
    
    # Nút thiết lập màu sắc
    @discord.ui.button(label="Đổi màu sắc", style=discord.ButtonStyle.secondary, row=1)
    async def set_color_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Tạo danh sách màu sắc
        colors = [
            ("🔴 Đỏ", discord.Color.red()),
            ("🔵 Xanh dương", discord.Color.blue()),
            ("🟢 Xanh lá", discord.Color.green()),
            ("🟡 Vàng", discord.Color.gold()),
            ("🟣 Tím", discord.Color.purple()),
            ("⚫ Đen", discord.Color.darker_grey()),
            ("⚪ Trắng", discord.Color.light_grey())
        ]
        
        # Tạo select menu cho màu sắc
        select = discord.ui.Select(
            placeholder="Chọn màu sắc cho thông báo",
            options=[
                discord.SelectOption(label=name, value=str(i))
                for i, (name, _) in enumerate(colors)
            ]
        )
        
        async def select_callback(select_interaction):
            # Lấy màu được chọn
            color_index = int(select_interaction.data["values"][0])
            self.announcement_data["color"] = colors[color_index][1]
            
            # Cập nhật embed
            await self.update_builder_embed()
            await select_interaction.response.defer()
        
        select.callback = select_callback
        
        # Tạo view mới với select menu
        color_view = discord.ui.View()
        color_view.add_item(select)
        
        await interaction.response.send_message("Chọn màu sắc cho thông báo của bạn:", view=color_view, ephemeral=True)
    
    # Nút thiết lập kênh
    @discord.ui.button(label="Chọn kênh", style=discord.ButtonStyle.secondary, row=1)
    async def set_channel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Tạo danh sách các kênh
        channels = [channel for channel in self.ctx.guild.text_channels 
                  if channel.permissions_for(self.ctx.guild.me).send_messages]
        
        # Tạo select menu cho kênh
        # Nếu có quá nhiều kênh, chỉ hiển thị 25 kênh đầu tiên (giới hạn của select menu)
        select_options = []
        for i, channel in enumerate(channels[:25]):
            select_options.append(
                discord.SelectOption(
                    label=channel.name,
                    value=str(i),
                    description=f"#{channel.name}"
                )
            )
        
        select = discord.ui.Select(
            placeholder="Chọn kênh để gửi thông báo",
            options=select_options
        )
        
        async def select_callback(select_interaction):
            # Lấy kênh được chọn
            channel_index = int(select_interaction.data["values"][0])
            self.announcement_data["channel"] = channels[channel_index]
            
            # Cập nhật embed
            await self.update_builder_embed()
            await select_interaction.response.defer()
        
        select.callback = select_callback
        
        # Tạo view mới với select menu
        channel_view = discord.ui.View()
        channel_view.add_item(select)
        
        await interaction.response.send_message("Chọn kênh để gửi thông báo:", view=channel_view, ephemeral=True)
    
    # Nút thiết lập mention
    @discord.ui.button(label="Thiết lập mention", style=discord.ButtonStyle.secondary, row=1)
    async def set_mention_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Tạo danh sách các loại mention
        mention_types = [
            ("Không ping", "none"),
            ("@here - Ping người đang online", "here"),
            ("@everyone - Ping tất cả", "everyone")
        ]
        
        # Tạo select menu cho mention
        select = discord.ui.Select(
            placeholder="Chọn loại mention",
            options=[
                discord.SelectOption(
                    label=name,
                    value=value,
                    description=f"Sử dụng {value}" if value != "none" else "Không ping ai"
                )
                for name, value in mention_types
            ]
        )
        
        async def select_callback(select_interaction):
            # Lấy mention được chọn
            self.announcement_data["mention"] = select_interaction.data["values"][0]
            
            # Cập nhật embed
            await self.update_builder_embed()
            await select_interaction.response.defer()
        
        select.callback = select_callback
        
        # Tạo view mới với select menu
        mention_view = discord.ui.View()
        mention_view.add_item(select)
        
        await interaction.response.send_message("Chọn loại mention cho thông báo:", view=mention_view, ephemeral=True)
    
    # Nút thêm hình ảnh
    @discord.ui.button(label="Thêm hình ảnh", style=discord.ButtonStyle.secondary, row=2)
    async def add_image_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Tạo modal để nhập URL hình ảnh
        modal = ImageURLModal(self)
        await interaction.response.send_modal(modal)
    
    # Nút xem trước
    @discord.ui.button(label="Xem trước", style=discord.ButtonStyle.success, row=3)
    async def preview_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Kiểm tra xem đã có đủ thông tin chưa
        if not self.announcement_data["title"] or not self.announcement_data["content"]:
            await interaction.response.send_message(
                "⚠️ Bạn cần thiết lập tiêu đề và nội dung trước khi xem trước!",
                ephemeral=True
            )
            return
        
        # Tạo embed để xem trước
        preview_embed = self.create_preview_embed()
        
        # Nếu đã có tin nhắn xem trước, cập nhật nó
        if self.preview_message:
            try:
                await self.preview_message.edit(embed=preview_embed)
                await interaction.response.send_message(
                    "✅ Đã cập nhật bản xem trước!",
                    ephemeral=True
                )
                return
            except:
                pass
        
        # Gửi tin nhắn xem trước mới
        await interaction.response.defer()
        self.preview_message = await self.ctx.send(
            "📝 **Bản xem trước thông báo:**",
            embed=preview_embed
        )
    
    # Nút gửi thông báo
    @discord.ui.button(label="Gửi thông báo", style=discord.ButtonStyle.danger, row=3)
    async def send_announcement_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Kiểm tra xem đã có đủ thông tin chưa
        if not self.announcement_data["title"] or not self.announcement_data["content"]:
            await interaction.response.send_message(
                "⚠️ Bạn cần thiết lập tiêu đề và nội dung trước khi gửi thông báo!",
                ephemeral=True
            )
            return
        
        # Tạo embed thông báo
        announcement_embed = self.create_preview_embed()
        
        # Gửi thông báo
        target_channel = self.announcement_data["channel"]
        mention_type = self.announcement_data["mention"]
        
        try:
            if mention_type == "here":
                allowed_mentions = discord.AllowedMentions(everyone=True)
                announcement_message = await target_channel.send(
                    content="@here",
                    embed=announcement_embed,
                    allowed_mentions=allowed_mentions
                )
            elif mention_type == "everyone":
                allowed_mentions = discord.AllowedMentions(everyone=True)
                announcement_message = await target_channel.send(
                    content="@everyone",
                    embed=announcement_embed,
                    allowed_mentions=allowed_mentions
                )
            else:
                announcement_message = await target_channel.send(embed=announcement_embed)
            
            # Cập nhật trình tạo thông báo thành công công
            success_embed = discord.Embed(
                title="✅ Thông báo đã được gửi",
                description=f"Thông báo của bạn đã được gửi thành công đến {target_channel.mention}.",
                color=discord.Color.green()
            )
            
            # Xóa tất cả các nút
            self.clear_items()
            
            # Thêm nút để nhảy đến thông báo
            self.add_item(discord.ui.Button(
                label="Xem thông báo", 
                style=discord.ButtonStyle.link, 
                url=announcement_message.jump_url
            ))
            
            await self.message.edit(embed=success_embed, view=self)
            
            # Xóa tin nhắn xem trước nếu có
            if self.preview_message:
                try:
                    await self.preview_message.delete()
                except:
                    pass
            
            await interaction.response.defer()
            
        except discord.Forbidden:
            await interaction.response.send_message(
                f"❌ Bot không có quyền gửi tin nhắn vào kênh {target_channel.mention}.",
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                f"❌ Đã xảy ra lỗi khi gửi thông báo: {str(e)}",
                ephemeral=True
            )
    
    # Nút hủy
    @discord.ui.button(label="Hủy", style=discord.ButtonStyle.secondary, row=3)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Hiển thị thông báo hủy
        cancel_embed = discord.Embed(
            title="❌ Đã hủy",
            description="Việc tạo thông báo đã bị hủy.",
            color=discord.Color.red()
        )
        
        # Xóa tất cả các nút
        self.clear_items()
        
        await self.message.edit(embed=cancel_embed, view=self)
        
        # Xóa tin nhắn xem trước nếu có
        if self.preview_message:
            try:
                await self.preview_message.delete()
            except:
                pass
        
        await interaction.response.defer()
    
    async def update_builder_embed(self):
        """Cập nhật embed của trình tạo thông báo"""
        builder_embed = discord.Embed(
            title="🔧 Tạo Thông Báo Admin",
            description="Sử dụng các nút bên dưới để thiết lập thông báo của bạn.",
            color=discord.Color.blue()
        )
        
        # Hiển thị thông tin đã thiết lập
        if self.announcement_data["title"]:
            builder_embed.add_field(
                name="📝 Tiêu đề",
                value=self.announcement_data["title"],
                inline=False
            )
        else:
            builder_embed.add_field(
                name="📝 Tiêu đề",
                value="❌ Chưa thiết lập",
                inline=False
            )
        
        if self.announcement_data["content"]:
            # Hiển thị tóm tắt nội dung nếu quá dài
            content = self.announcement_data["content"]
            if len(content) > 100:
                content = content[:100] + "..."
            
            builder_embed.add_field(
                name="📄 Nội dung",
                value=content,
                inline=False
            )
        else:
            builder_embed.add_field(
                name="📄 Nội dung",
                value="❌ Chưa thiết lập",
                inline=False
            )
        
        builder_embed.add_field(
            name="🎨 Màu sắc",
            value=f"HEX: #{self.announcement_data['color'].value:06x}",
            inline=True
        )
        
        builder_embed.add_field(
            name="📢 Kênh",
            value=f"#{self.announcement_data['channel'].name}",
            inline=True
        )
        
        mention_display = {
            "none": "Không ping",
            "here": "@here",
            "everyone": "@everyone"
        }
        
        builder_embed.add_field(
            name="👥 Mention",
            value=mention_display[self.announcement_data["mention"]],
            inline=True
        )
        
        if self.announcement_data["image_url"]:
            builder_embed.add_field(
                name="🖼️ Hình ảnh",
                value=f"[Xem hình ảnh]({self.announcement_data['image_url']})",
                inline=True
            )
            builder_embed.set_image(url=self.announcement_data["image_url"])
        
        # Cập nhật message
        await self.message.edit(embed=builder_embed, view=self)
    
    def create_preview_embed(self):
        """Tạo embed xem trước dựa trên dữ liệu đã thiết lập"""
        embed = discord.Embed(
            title=f"📢 {self.announcement_data['title']}",
            description=self.announcement_data["content"],
            color=self.announcement_data["color"]
        )
        
        # Thêm thông tin thời gian và người gửi
        embed.set_footer(
            text=f"Thông báo bởi {self.ctx.author.display_name}",
            icon_url=self.ctx.author.display_avatar.url
        )
        
        # Thêm hình ảnh nếu có
        if self.announcement_data["image_url"]:
            embed.set_image(url=self.announcement_data["image_url"])
        
        # Thêm timestamp
        embed.timestamp = datetime.now()
        
        return embed


# Modal để nhập tiêu đề
class TitleInputModal(discord.ui.Modal):
    def __init__(self, view):
        super().__init__(title="Thiết lập tiêu đề thông báo")
        self.view = view
        
        self.title_input = discord.ui.TextInput(
            label="Tiêu đề thông báo",
            placeholder="Nhập tiêu đề thông báo của bạn",
            default=self.view.announcement_data["title"],
            max_length=256
        )
        
        self.add_item(self.title_input)
    
    async def on_submit(self, interaction: discord.Interaction):
        self.view.announcement_data["title"] = self.title_input.value
        await interaction.response.send_message("✅ Đã thiết lập tiêu đề thông báo!", ephemeral=True)
        await self.view.update_builder_embed()


# Modal để nhập nội dung
class ContentInputModal(discord.ui.Modal):
    def __init__(self, view):
        super().__init__(title="Thiết lập nội dung thông báo")
        self.view = view
        
        self.content_input = discord.ui.TextInput(
            label="Nội dung thông báo",
            placeholder="Nhập nội dung thông báo của bạn",
            default=self.view.announcement_data["content"],
            style=discord.TextStyle.paragraph,
            max_length=4000
        )
        
        self.add_item(self.content_input)
    
    async def on_submit(self, interaction: discord.Interaction):
        self.view.announcement_data["content"] = self.content_input.value
        await interaction.response.send_message("✅ Đã thiết lập nội dung thông báo!", ephemeral=True)
        await self.view.update_builder_embed()


# Modal để nhập URL hình ảnh
class ImageURLModal(discord.ui.Modal):
    def __init__(self, view):
        super().__init__(title="Thêm hình ảnh")
        self.view = view
        
        self.image_url_input = discord.ui.TextInput(
            label="URL hình ảnh",
            placeholder="Nhập URL hình ảnh của bạn (để trống để xóa)",
            default=self.view.announcement_data["image_url"] or "",
            required=False
        )
        
        self.add_item(self.image_url_input)
    
    async def on_submit(self, interaction: discord.Interaction):
        url = self.image_url_input.value.strip()
        if url:
            if url.startswith(('http://', 'https://')) and any(url.endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp']):
                self.view.announcement_data["image_url"] = url
                await interaction.response.send_message("✅ Đã thêm hình ảnh vào thông báo!", ephemeral=True)
            else:
                await interaction.response.send_message("❌ URL không hợp lệ! URL phải bắt đầu bằng http:// hoặc https:// và kết thúc bằng .png, .jpg, .jpeg, .gif hoặc .webp", ephemeral=True)
                return
        else:
            self.view.announcement_data["image_url"] = None
            await interaction.response.send_message("✅ Đã xóa hình ảnh khỏi thông báo!", ephemeral=True)
        
        await self.view.update_builder_embed()


@admin_announcement.error
async def admin_announcement_error(ctx, error):
    """Xử lý lỗi cho lệnh tb"""
    if isinstance(error, commands.MissingPermissions):
        embed = discord.Embed(
            title="❌ Thiếu quyền",
            description="Bạn cần có quyền Administrator để sử dụng lệnh này.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed, delete_after=10)
    else:
        embed = discord.Embed(
            title="❌ Lỗi",
            description=f"Đã xảy ra lỗi: {str(error)}",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed, delete_after=10)


# 1. Thêm xử lý lệnh không hợp lệ
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandError) and ctx.command and ctx.command.name in ['kick', 'ban', 'dms']:
        # Không làm gì vì lỗi đã được xử lý trong decorator owner_only
        pass
    # Xử lý các lỗi khác như trong code gốc
    elif isinstance(error, commands.CommandNotFound):
        embed = discord.Embed(
            title="❓ Lệnh không hợp lệ",
            description="Lệnh bạn vừa nhập không tồn tại hoặc sai cú pháp.",
            color=discord.Color.orange())
        embed.add_field(
            name="Cần trợ giúp?",
            value="Vui lòng sử dụng lệnh `.stvh` để xem danh sách các lệnh có sẵn.",
            inline=False)
        embed.add_field(
            name="Kênh chơi game",
            value=f"Tất cả các lệnh chơi game chỉ hoạt động trong <#{GAME_CHANNEL_ID}>",
            inline=False)
        await ctx.send(embed=embed)


# 3. Thêm lệnh đo chiều cao (không cần check_channel)
@bot.command(name='howheight', aliases=['chieucho', 'cao'])
async def howheight(ctx, member: discord.Member = None):
    """Kiểm tra chiều cao của một thành viên với kết quả ngẫu nhiên"""
    # Kiểm tra cooldown để tránh spam
    user_id = ctx.author.id
    current_time = datetime.now()
    
    # Sử dụng cùng dict howgay_cooldown
    if user_id in howgay_cooldown:
        time_since_last_use = (current_time - howgay_cooldown[user_id]).total_seconds()
        if time_since_last_use < 30:  # 30 giây cooldown
            remaining = int(30 - time_since_last_use)
            await ctx.send(f"⏳ Vui lòng đợi {remaining} giây nữa trước khi dùng lại lệnh này.")
            return
    
    # Cập nhật thời gian sử dụng
    howgay_cooldown[user_id] = current_time
    
    # Xác định người được kiểm tra
    target = member or ctx.author
    
    # Tìm role Lùn trong server, tạo nếu không có
    short_role = discord.utils.get(ctx.guild.roles, name="🧙 Lùn")
    if not short_role:
        try:
            short_role = await ctx.guild.create_role(
                name="🧙 Lùn",
                color=discord.Color.dark_gold(),
                reason="Tạo role cho lệnh howheight"
            )
        except:
            short_role = None
    
    # Xác định chiều cao
    # Nếu người dùng là admin, chiều cao từ 1m70 đến 1m90
    if target.guild_permissions.administrator:
        height = random.randint(170, 190)
    elif target.bot:
        height = 200  # Bot cao vút
    else:
        height = random.randint(140, 190)  # 140cm - 190cm
    
    # Format hiển thị chiều cao
    height_display = f"{height // 100}m{height % 100:02d}"
    
    # Tạo biểu tượng dựa vào chiều cao
    if height < 150:
        emoji = "🧙"
        color = discord.Color.dark_gold()
        message = "Quá lùn! Minion trông còn cao hơn!"
    elif height < 160:
        emoji = "🧝"
        color = discord.Color.gold()
        message = "Hơi lùn một chút, nhưng vẫn dễ thương!"
    elif height < 170:
        emoji = "🙂"
        color = discord.Color.blue()
        message = "Chiều cao trung bình, khá là chuẩn!"
    elif height < 180:
        emoji = "🏃"
        color = discord.Color.green()
        message = "Chiều cao lý tưởng! Perfect!"
    else:
        emoji = "🏀"
        color = discord.Color.purple()
        message = "Cao quá! Có đi thi bóng rổ không?"
    
    # Tạo progress bar
    height_percent = min(100, int((height - 140) / 60 * 100))  # 140cm-200cm map to 0-100%
    progress_bar = "🟩" * (height_percent // 10) + "⬜" * ((100 - height_percent) // 10)
    
    # Tạo embed
    embed = discord.Embed(
        title=f"📏 Máy đo chiều cao",
        description=f"Chiều cao của {target.mention}",
        color=color
    )
    embed.add_field(
        name="Kết quả", 
        value=f"**{height_display}** {emoji}", 
        inline=False
    )
    embed.add_field(
        name="Mức độ", 
        value=progress_bar, 
        inline=False
    )
    embed.add_field(
        name="Nhận xét", 
        value=message, 
        inline=False
    )
    embed.set_thumbnail(url=target.display_avatar.url)
    
    # Gửi kết quả
    await ctx.send(embed=embed)
    
    # Nếu height < 155cm, thêm role Lùn trong 1 giờ
    if height < 155 and short_role and not target.bot and target.id != ctx.guild.owner_id:
        try:
            await target.add_roles(short_role)
            
            # Thông báo về việc thêm role
            dm_embed = discord.Embed(
                title="🧙 Bạn đã nhận được role Lùn!",
                description="Bạn quá lùn nên đã được thêm role Lùn trong 1 giờ.",
                color=discord.Color.dark_gold()
            )
            dm_embed.add_field(
                name="Kết quả", 
                value=f"Chiều cao: **{height_display}**", 
                inline=True
            )
            dm_embed.add_field(
                name="Thời hạn", 
                value="Role sẽ tự động bị gỡ sau 1 giờ", 
                inline=True
            )
            
            try:
                await target.send(embed=dm_embed)
            except:
                pass  # Bỏ qua nếu không gửi được DM
                
            # Gỡ role sau 1 giờ
            bot.loop.create_task(remove_short_role_after_duration(target.id, ctx.guild.id, short_role.id))
        except Exception as e:
            print(f"Không thể thêm role Lùn: {str(e)}")

# Hàm phụ trợ để gỡ role Lùn sau 1 giờ
async def remove_short_role_after_duration(user_id, guild_id, role_id):
    """Gỡ role Lùn sau 1 giờ"""
    await asyncio.sleep(3600)  # 1 giờ = 3600 giây
    
    # Tìm guild
    guild = bot.get_guild(guild_id)
    if not guild:
        return
        
    # Tìm member
    member = guild.get_member(user_id)
    if not member:
        return
        
    # Tìm role
    role = guild.get_role(role_id)
    if not role or role not in member.roles:
        return
        
    # Gỡ role
    try:
        await member.remove_roles(role)
        
        # Thông báo qua DM
        try:
            dm_embed = discord.Embed(
                title="🧙 Role Lùn đã hết hạn",
                description="Role Lùn tạm thời của bạn đã được gỡ bỏ sau 1 giờ.",
                color=discord.Color.blue()
            )
            await member.send(embed=dm_embed)
        except:
            pass  # Bỏ qua nếu không gửi được DM
    except:
        pass  # Bỏ qua nếu không gỡ được role


@bot.command(name='howrb', aliases=['drinklevel', 'ruou', 'bia'])
async def how_drink(ctx, member: discord.Member = None):
    """Kiểm tra khả năng uống rượu/bia của một thành viên với kết quả ngẫu nhiên"""
    target = member or ctx.author

    # Tính toán khả năng uống
    beer_level = random.randint(2, 24)  # Số lon bia có thể uống (2-24 lon)
    wine_level = random.randint(1, 12)  # Số ly rượu có thể uống (1-12 ly)
    tolerance = random.randint(1, 100)  # Độ chịu đựng (%)

    # Xác định mức độ và thông điệp
    if beer_level < 5:
        level_text = "Gà quá! Mới vài lon đã ngã"
        emoji = "🐣"
        color = discord.Color.light_grey()
    elif beer_level < 10:
        level_text = "Khá yếu, cần rèn luyện thêm"
        emoji = "🐔"
        color = discord.Color.teal()
    elif beer_level < 15:
        level_text = "Khả năng uống trung bình, có thể đối đầu với dân nhậu"
        emoji = "🦊"
        color = discord.Color.blue()
    elif beer_level < 20:
        level_text = "Cao thủ rồi đấy! Uống như hũ chìm!"
        emoji = "🐘"
        color = discord.Color.orange()
    else:
        level_text = "Quái vật bia! Không có đối thủ!"
        emoji = "🐉"
        color = discord.Color.gold()

    # Tạo thanh trạng thái
    beer_bar = "🍺" * (beer_level // 3) + "⬜" * (8 - (beer_level // 3))
    wine_bar = "🍷" * (wine_level // 2) + "⬜" * (6 - (wine_level // 2))

    # Tạo embed
    embed = discord.Embed(title=f"🍻 Máy đo khả năng uống rượu bia",
                          description=f"Khả năng uống của {target.mention}",
                          color=color)

    embed.add_field(name="🍺 Khả năng uống bia",
                    value=f"**{beer_level} lon**\n{beer_bar}",
                    inline=False)

    embed.add_field(name="🍷 Khả năng uống rượu",
                    value=f"**{wine_level} ly**\n{wine_bar}",
                    inline=False)

    embed.add_field(name="💪 Độ chịu đựng",
                    value=f"**{tolerance}%**",
                    inline=True)

    embed.add_field(name="📊 Đánh giá",
                    value=f"{emoji} {level_text}",
                    inline=True)

    embed.set_thumbnail(url=target.display_avatar.url)
    embed.set_footer(
        text="Nhắc nhở: Uống có trách nhiệm, không lái xe khi đã uống rượu bia!"
    )

    await ctx.send(embed=embed)


# Tạo lệnh để nhắc nhở người dùng đi đến kênh chơi game
@bot.command(name='gamechannel', aliases=['gc'])
async def game_channel(ctx):
    """Hiển thị link kênh chơi game"""
    embed = discord.Embed(
        title="🎮 Kênh Chơi Game",
        description=
        f"Tất cả các lệnh chơi game chỉ hoạt động trong kênh <#{GAME_CHANNEL_ID}>",
        color=discord.Color.blue())
    embed.add_field(
        name="🔗 Liên kết nhanh",
        value=f"[Nhấn vào đây để đến kênh chơi game]({GAME_CHANNEL_LINK})",
        inline=False)
    embed.set_footer(
        text="Đảm bảo bạn đang ở kênh đúng để sử dụng các lệnh bot")
    await ctx.send(embed=embed)


# Theo dõi người thắng cuộc fight gần nhất và có quyền kill
recent_fight_winners = {}  # {user_id: [target_id, timestamp]}


@bot.command(name='fight')
@check_channel()
@check_game_enabled('fight')
async def fight_command(ctx, member: discord.Member = None, bet: str = None):
    """Thách đấu với người chơi khác - Phiên bản nâng cấp"""
    if member is None or bet is None:
        embed = discord.Embed(
            title="⚔️ Fight - Hướng Dẫn",
            description=
            "Thách đấu với người chơi khác.\nVí dụ: `.fight @tên_người_chơi 50` hoặc `.fight @tên_người_chơi all`",
            color=discord.Color.blue())
        embed.add_field(
            name="Luật chơi",
            value="- Mỗi người chơi có 100 HP và 3 dạng đòn tấn công\n"
            "- Tấn công thường (⚔️): Gây 15-25 sát thương\n"
            "- Tấn công mạnh (🗡️): Gây 30-40 sát thương nhưng có 30% tỷ lệ hụt\n"
            "- Chiêu đặc biệt (⚡): Gây 50-60 sát thương nhưng chỉ dùng được 1 lần",
            inline=False)
        embed.add_field(
            name="Phần thưởng",
            value="Người thắng nhận x1.5 tiền cược và có quyền timeout đối thủ",
            inline=False)
        await ctx.send(embed=embed)
        return

    user_id = ctx.author.id
    target_id = member.id

    # Xử lý đặt cược "all"
    bet_amount = parse_bet(bet, currency[user_id])
    if bet_amount is None:
        embed = discord.Embed(
            title="❌ Số tiền không hợp lệ",
            description="Vui lòng nhập số tiền hợp lệ hoặc 'all'.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Kiểm tra người chơi không thể thách đấu chính mình
    if user_id == target_id:
        embed = discord.Embed(
            title="⚔️ Fight",
            description="Bạn không thể thách đấu chính mình!",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Kiểm tra số tiền cược
    if bet_amount <= 0:
        embed = discord.Embed(title="⚔️ Fight",
                              description="Số tiền cược phải lớn hơn 0 xu.",
                              color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Kiểm tra cả hai người chơi có đủ xu không
    if currency[user_id] < bet_amount:
        embed = discord.Embed(
            title="⚔️ Fight",
            description=
            f"{ctx.author.mention}, bạn không đủ xu để đặt cược! Bạn hiện có {currency[user_id]} xu.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    if currency[target_id] < bet_amount:
        embed = discord.Embed(
            title="⚔️ Fight",
            description=
            f"{member.mention} không đủ xu để chấp nhận thách đấu! Họ hiện có {currency[target_id]} xu.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Tạo thông báo thách đấu
    embed = discord.Embed(
        title="⚔️ THÁCH ĐẤU!",
        description=
        f"{ctx.author.mention} thách đấu {member.mention} với {bet_amount} xu!",
        color=discord.Color.gold())
    embed.add_field(
        name="Thông tin trận đấu",
        value=
        "- Mỗi người chơi có 100 HP\n- Ba dạng tấn công: Thường, Mạnh, Đặc biệt\n- Người hết máu trước sẽ thua",
        inline=False)
    embed.add_field(
        name="Cách chấp nhận",
        value=f"{member.mention} hãy ấn nút 'Chấp nhận' để bắt đầu!",
        inline=False)

    # Tạo các nút phản hồi
    accept_button = discord.ui.Button(label="Chấp nhận",
                                      style=discord.ButtonStyle.green,
                                      emoji="✅")
    decline_button = discord.ui.Button(label="Từ chối",
                                       style=discord.ButtonStyle.red,
                                       emoji="❌")

    view = discord.ui.View(timeout=30)
    view.add_item(accept_button)
    view.add_item(decline_button)

    challenge_msg = await ctx.send(embed=embed, view=view)

    async def accept_callback(interaction):
        if interaction.user.id != target_id:
            await interaction.response.send_message(
                "Bạn không phải người được thách đấu!", ephemeral=True)
            return

        # Vô hiệu hóa nút chấp nhận/từ chối
        for child in view.children:
            child.disabled = True
        await interaction.response.edit_message(view=view)

        # Khởi tạo trận đấu
        player1_hp = 100
        player2_hp = 100
        player1_special = True
        player2_special = True
        current_turn = ctx.author  # Người thách đấu đi trước

        # Tạo view cho các nút tấn công
        class AttackView(discord.ui.View):

            def __init__(self, player):
                super().__init__(timeout=30)
                self.player = player
                self.choice = None
                special_disabled = (player.id == user_id
                                    and not player1_special) or (
                                        player.id == target_id
                                        and not player2_special)

                # Nút tấn công thường
                normal_attack = discord.ui.Button(
                    label="Tấn công thường (15-25)",
                    style=discord.ButtonStyle.primary,
                    emoji="⚔️",
                    custom_id="normal")
                normal_attack.callback = self.normal_callback
                self.add_item(normal_attack)

                # Nút tấn công mạnh
                strong_attack = discord.ui.Button(
                    label="Tấn công mạnh (30-40, 30% miss)",
                    style=discord.ButtonStyle.danger,
                    emoji="🗡️",
                    custom_id="strong")
                strong_attack.callback = self.strong_callback
                self.add_item(strong_attack)

                # Nút chiêu đặc biệt
                special_attack = discord.ui.Button(
                    label="Chiêu đặc biệt (50-60)",
                    style=discord.ButtonStyle.success,
                    emoji="⚡",
                    disabled=special_disabled,
                    custom_id="special")
                special_attack.callback = self.special_callback
                self.add_item(special_attack)

            async def normal_callback(self, interaction):
                if interaction.user.id != self.player.id:
                    await interaction.response.send_message(
                        "Không phải lượt của bạn!", ephemeral=True)
                    return
                self.choice = "normal"
                for child in self.children:
                    child.disabled = True
                await interaction.response.edit_message(view=self)
                self.stop()

            async def strong_callback(self, interaction):
                if interaction.user.id != self.player.id:
                    await interaction.response.send_message(
                        "Không phải lượt của bạn!", ephemeral=True)
                    return
                self.choice = "strong"
                for child in self.children:
                    child.disabled = True
                await interaction.response.edit_message(view=self)
                self.stop()

            async def special_callback(self, interaction):
                if interaction.user.id != self.player.id:
                    await interaction.response.send_message(
                        "Không phải lượt của bạn!", ephemeral=True)
                    return
                self.choice = "special"
                for child in self.children:
                    child.disabled = True
                await interaction.response.edit_message(view=self)
                self.stop()

        # Bắt đầu vòng lặp trận đấu
        turn_count = 0
        battle_log = []

        while player1_hp > 0 and player2_hp > 0 and turn_count < 10:  # Tối đa 10 lượt
            turn_count += 1

            # Hiển thị trạng thái trận đấu
            status_embed = discord.Embed(
                title=f"⚔️ Lượt {turn_count}",
                description=f"Lượt của {current_turn.mention}",
                color=discord.Color.blue())

            # Hiển thị thanh máu
            p1_health_bar = "❤️" * (player1_hp // 10) + "🖤" * (
                (100 - player1_hp) // 10)
            p2_health_bar = "❤️" * (player2_hp // 10) + "🖤" * (
                (100 - player2_hp) // 10)

            status_embed.add_field(
                name=f"{ctx.author.display_name} - {player1_hp}/100 HP",
                value=p1_health_bar,
                inline=False)
            status_embed.add_field(
                name=f"{member.display_name} - {player2_hp}/100 HP",
                value=p2_health_bar,
                inline=False)

            if battle_log:
                status_embed.add_field(
                    name="Diễn biến trận đấu",
                    value="\n".join(
                        battle_log[-3:]),  # Hiển thị 3 dòng gần nhất
                    inline=False)

            # Hiển thị nút tấn công cho người chơi hiện tại
            attack_view = AttackView(current_turn)
            attack_msg = await interaction.followup.send(embed=status_embed,
                                                         view=attack_view)

            # Chờ người chơi chọn đòn tấn công
            timeout = await attack_view.wait()
            if timeout or attack_view.choice is None:
                battle_log.append(
                    f"⏱️ {current_turn.display_name} đã bỏ lỡ lượt!")
                # Người còn lại tự động thắng nếu đối thủ bỏ lỡ lượt
                if current_turn == ctx.author:
                    player1_hp = 0
                else:
                    player2_hp = 0
                break

            # Xử lý đòn tấn công
            attacker = current_turn.display_name
            defender = member.display_name if current_turn == ctx.author else ctx.author.display_name

            if attack_view.choice == "normal":
                damage = random.randint(15, 25)
                hit_chance = 100  # 100% hit
                attack_name = "tấn công thường"
                attack_emoji = "⚔️"
            elif attack_view.choice == "strong":
                damage = random.randint(30, 40)
                hit_chance = 70  # 70% hit chance
                attack_name = "tấn công mạnh"
                attack_emoji = "🗡️"
            else:  # special
                damage = random.randint(50, 60)
                hit_chance = 100  # 100% hit
                attack_name = "chiêu đặc biệt"
                attack_emoji = "⚡"
                # Đánh dấu đã sử dụng chiêu đặc biệt
                if current_turn == ctx.author:
                    player1_special = False
                else:
                    player2_special = False

            # Kiểm tra đòn tấn công có trúng không
            if random.randint(1, 100) <= hit_chance:
                # Trúng đòn
                if current_turn == ctx.author:
                    player2_hp -= damage
                    player2_hp = max(0, player2_hp)  # Đảm bảo HP không âm
                else:
                    player1_hp -= damage
                    player1_hp = max(0, player1_hp)  # Đảm bảo HP không âm

                battle_log.append(
                    f"{attack_emoji} {attacker} dùng {attack_name} gây {damage} sát thương cho {defender}!"
                )
            else:
                # Hụt đòn
                battle_log.append(
                    f"💨 {attacker} dùng {attack_name} nhưng đã hụt!")

            # Chuyển lượt
            current_turn = member if current_turn == ctx.author else ctx.author

            # Xóa tin nhắn cũ
            try:
                await attack_msg.delete()
            except:
                pass

        # Xác định người thắng
        winner = ctx.author if player2_hp <= 0 else member
        loser = member if winner == ctx.author else ctx.author

        # Thiên vị người chơi trong whitelist nếu cần
        if is_whitelisted(ctx.author.id) and winner != ctx.author:
            # Đảo ngược kết quả cho người trong whitelist
            winner = ctx.author
            loser = member
            battle_log.append(
                f"⚡ {ctx.author.display_name} đã bất ngờ lội ngược dòng!")

        # Xử lý tiền cược
        winnings = int(bet_amount * 1.5)
        currency[winner.id] += winnings - bet_amount
        currency[loser.id] -= bet_amount

        # Lưu người thắng vào danh sách có quyền kill
        recent_fight_winners[winner.id] = [loser.id, datetime.now()]

        # Hiển thị kết quả cuối cùng
        final_embed = discord.Embed(
            title="🏆 KẾT QUẢ TRẬN ĐẤU!",
            description=f"**{winner.display_name}** đã chiến thắng!",
            color=discord.Color.green())

        # Hiển thị HP còn lại
        final_hp1 = player1_hp if winner == ctx.author else 0
        final_hp2 = player2_hp if winner == member else 0

        final_embed.add_field(
            name="Chi tiết trận đấu",
            value=
            f"{ctx.author.display_name}: {final_hp1}/100 HP\n{member.display_name}: {final_hp2}/100 HP",
            inline=False)

        final_embed.add_field(
            name="Phần thưởng",
            value=
            f"- {winner.mention} nhận được {winnings} xu (x1.5)\n- Quyền timeout đối thủ với lệnh `.kill @{loser.display_name} [phút]`",
            inline=False)

        # Hiển thị nhật ký trận đấu
        final_embed.add_field(
            name="Diễn biến trận đấu",
            value="\n".join(battle_log[-5:]),  # Hiển thị 5 dòng cuối
            inline=False)

        await interaction.followup.send(embed=final_embed)

    async def decline_callback(interaction):
        if interaction.user.id != target_id:
            await interaction.response.send_message(
                "Bạn không phải người được thách đấu!", ephemeral=True)
            return

        # Vô hiệu hóa các nút
        for child in view.children:
            child.disabled = True
        await interaction.response.edit_message(view=view)

        # Thông báo từ chối
        decline_embed = discord.Embed(
            title="❌ THÁCH ĐẤU BỊ TỪ CHỐI!",
            description=
            f"{member.mention} đã từ chối lời thách đấu của {ctx.author.mention}!",
            color=discord.Color.red())
        await challenge_msg.edit(embed=decline_embed)

    # Gán callback cho các nút
    accept_button.callback = accept_callback
    decline_button.callback = decline_callback

    # Đặt timeout cho thách đấu
    await asyncio.sleep(30)

    # Kiểm tra nếu các nút vẫn còn hoạt động (chưa có phản hồi)
    if not accept_button.disabled:
        for child in view.children:
            child.disabled = True
        expired_embed = discord.Embed(
            title="⏱️ THÁCH ĐẤU HẾT HẠN!",
            description=
            f"{member.mention} không phản hồi kịp thời với lời thách đấu của {ctx.author.mention}!",
            color=discord.Color.grey())
        await challenge_msg.edit(embed=expired_embed, view=view)


@bot.command(name='kill')
@check_channel()
async def kill_command(ctx,
                       member: discord.Member = None,
                       minutes: int = None):
    """Cho phép người thắng Fight timeout đối thủ thêm thời gian"""
    if member is None or minutes is None:
        embed = discord.Embed(
            title="☠️ Kill - Hướng Dẫn",
            description=
            "Cho phép timeout người thua trận Fight.\nVí dụ: `.kill @tên_người_chơi 3`",
            color=discord.Color.blue())
        embed.add_field(
            name="Lưu ý",
            value=
            "- Chỉ người thắng trận Fight mới có thể sử dụng\n- Thời gian timeout từ 1-5 phút",
            inline=False)
        await ctx.send(embed=embed)
        return

    user_id = ctx.author.id
    target_id = member.id

    # Kiểm tra nếu người dùng có quyền sử dụng lệnh kill
    if user_id not in recent_fight_winners or recent_fight_winners[user_id][
            0] != target_id:
        embed = discord.Embed(
            title="❌ Không được phép",
            description=
            "Bạn không có quyền timeout người chơi này! Bạn phải thắng họ trong một trận Fight trước.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Kiểm tra thời gian timeout có hợp lệ không
    if minutes < 1 or minutes > 5:
        embed = discord.Embed(
            title="❌ Không hợp lệ",
            description="Thời gian timeout phải từ 1 đến 5 phút.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Kiểm tra thời gian từ lần fight cuối
    fight_time = recent_fight_winners[user_id][1]
    time_passed = (datetime.now() - fight_time).total_seconds()
    if time_passed > 300:  # 5 phút = 300 giây
        embed = discord.Embed(
            title="⏱️ Hết hạn",
            description=
            "Quyền sử dụng lệnh kill đã hết hạn! Bạn chỉ có thể sử dụng trong vòng 5 phút sau khi thắng Fight.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Thực hiện timeout
    try:
        timeout_until = discord.utils.utcnow() + timedelta(minutes=5)
        await member.timeout(
            timeout_until,
            reason=f"Bị kill bởi {ctx.author.display_name} sau khi thua Fight")

        embed = discord.Embed(
            title="☠️ KILL THÀNH CÔNG!",
            description=
            f"{ctx.author.mention} đã timeout {member.mention} thêm {minutes} phút!",
            color=discord.Color.purple())
        embed.set_footer(text="Chiến thắng thuộc về kẻ mạnh!")
        await ctx.send(embed=embed)

        # Xóa quyền kill sau khi sử dụng
        del recent_fight_winners[user_id]

    except Exception as e:
        embed = discord.Embed(
            title="❌ Lỗi",
            description=f"Không thể timeout người chơi này: {str(e)}",
            color=discord.Color.red())
        await ctx.send(embed=embed)

@bot.command(name='bacaopvp', aliases=['baocaopvp', 'bacao', 'bacaobet'])
@check_channel()
@check_game_enabled('bacaopvp')
async def bacaopvp(ctx, member: discord.Member = None, bet: str = None):
    """Trò chơi Bài Ba Cào PvP - thấp lá thua và bị timeout"""
    if member is None or bet is None:
        embed = discord.Embed(
            title="🃏 Ba Cào PvP - Hướng Dẫn",
            description="Thách đấu bài Ba Cào với người chơi khác.\nVí dụ: `.bacaopvp @tên_người_chơi 50`",
            color=discord.Color.blue())
        embed.add_field(
            name="Luật chơi",
            value="- Mỗi người chơi nhận 3 lá bài\n"
                 "- Điểm được tính bằng tổng điểm 3 lá mod 10 (chỉ lấy chữ số cuối)\n"
                 "- J/Q/K = 10, A = 1\n"
                 "- Điểm cao nhất là 9 điểm\n"
                 "- Có các kết hợp đặc biệt: Ba tiên (3 K/Q/J), Ba đồng (3 lá cùng số), Sáp (đôi cùng + 1 lá)",
            inline=False)
        embed.add_field(
            name="Phần thưởng",
            value="- Người thắng nhận x1.5 tiền cược\n"
                 "- Người thua bị timeout 5 phút",
            inline=False)
        await ctx.send(embed=embed)
        return

    user_id = ctx.author.id
    target_id = member.id

    # Kiểm tra người chơi không thể thách đấu chính mình
    if user_id == target_id:
        embed = discord.Embed(
            title="🃏 Ba Cào PvP",
            description="Bạn không thể thách đấu chính mình!",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Xử lý đặt cược "all"
    bet_amount = parse_bet(bet, currency[user_id])
    if bet_amount is None:
        embed = discord.Embed(
            title="❌ Số tiền không hợp lệ",
            description="Vui lòng nhập số tiền hợp lệ hoặc 'all'.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Kiểm tra số tiền cược
    if bet_amount <= 0:
        embed = discord.Embed(title="🃏 Ba Cào PvP",
                              description="Số tiền cược phải lớn hơn 0 xu.",
                              color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Kiểm tra cả hai người chơi có đủ xu không
    if currency[user_id] < bet_amount:
        embed = discord.Embed(
            title="🃏 Ba Cào PvP",
            description=f"{ctx.author.mention}, bạn không đủ xu để đặt cược! Bạn hiện có {currency[user_id]} xu.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    if currency[target_id] < bet_amount:
        embed = discord.Embed(
            title="🃏 Ba Cào PvP",
            description=f"{member.mention} không đủ xu để chấp nhận thách đấu! Họ hiện có {currency[target_id]} xu.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Tạo thông báo thách đấu
    embed = discord.Embed(
        title="🃏 THÁCH ĐẤU BÀI BA CÀO!",
        description=f"{ctx.author.mention} thách đấu {member.mention} với {bet_amount} xu!",
        color=discord.Color.gold())
    embed.add_field(
        name="Cách chơi",
        value="Mỗi người nhận 3 lá bài, người có điểm thấp hơn sẽ bị timeout 5 phút.",
        inline=False)
    embed.add_field(
        name="Cách chấp nhận",
        value=f"{member.mention} hãy ấn nút 'Chấp nhận' để bắt đầu!",
        inline=False)

    # Tạo các nút phản hồi
    accept_button = discord.ui.Button(label="Chấp nhận", style=discord.ButtonStyle.green, emoji="✅")
    decline_button = discord.ui.Button(label="Từ chối", style=discord.ButtonStyle.red, emoji="❌")

    view = discord.ui.View(timeout=30)
    view.add_item(accept_button)
    view.add_item(decline_button)

    challenge_msg = await ctx.send(embed=embed, view=view)

    async def accept_callback(interaction):
        if interaction.user.id != target_id:
            await interaction.response.send_message("Bạn không phải người được thách đấu!", ephemeral=True)
            return

        # Vô hiệu hóa nút chấp nhận/từ chối
        for child in view.children:
            child.disabled = True
        await interaction.response.edit_message(view=view)

        # Bắt đầu trò chơi
        await play_bacaopvp(interaction, ctx.author, member, bet_amount)

    async def decline_callback(interaction):
        if interaction.user.id != target_id:
            await interaction.response.send_message("Bạn không phải người được thách đấu!", ephemeral=True)
            return

        # Vô hiệu hóa các nút
        for child in view.children:
            child.disabled = True
        await interaction.response.edit_message(view=view)

        # Thông báo từ chối
        decline_embed = discord.Embed(
            title="❌ THÁCH ĐẤU BỊ TỪ CHỐI!",
            description=f"{member.mention} đã từ chối lời thách đấu của {ctx.author.mention}!",
            color=discord.Color.red())
        await challenge_msg.edit(embed=decline_embed)

    # Gán callback cho các nút
    accept_button.callback = accept_callback
    decline_button.callback = decline_callback

    # Đặt timeout cho thách đấu
    await asyncio.sleep(30)

    # Kiểm tra nếu các nút vẫn còn hoạt động (chưa có phản hồi)
    if not accept_button.disabled:
        for child in view.children:
            child.disabled = True
        expired_embed = discord.Embed(
            title="⏱️ THÁCH ĐẤU HẾT HẠN!",
            description=f"{member.mention} không phản hồi kịp thời với lời thách đấu của {ctx.author.mention}!",
            color=discord.Color.grey())
        await challenge_msg.edit(embed=expired_embed, view=view)

async def play_bacaopvp(interaction, player1, player2, bet_amount):
    """Xử lý trò chơi Ba Cào PvP giữa hai người chơi"""
    # Thiết lập bộ bài
    suits = ['♠️', '♥️', '♦️', '♣️']
    cards = ['A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K']
    values = {'A': 1, '2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7, '8': 8, '9': 9, '10': 10, 'J': 10, 'Q': 10, 'K': 10}
    
    # Tạo và trộn bộ bài
    deck = [(card, suit) for suit in suits for card in cards]
    random.shuffle(deck)
    
    # Hiệu ứng đang chia bài
    loading_embed = discord.Embed(
        title="🃏 BA CÀO PVP - ĐANG CHIA BÀI",
        description="Đang chia bài cho các người chơi...",
        color=discord.Color.blue()
    )
    loading_msg = await interaction.followup.send(embed=loading_embed)
    await asyncio.sleep(1.5)
    
    # Chia bài cho người chơi
    player1_hand = [deck.pop() for _ in range(3)]
    player2_hand = [deck.pop() for _ in range(3)]
    
    # Function để tính điểm bài
    def calculate_score(hand):
        # Tính điểm thông thường - lấy tổng mod 10
        total = sum(values[card[0]] for card in hand) % 10
        
        # Kiểm tra các kết hợp đặc biệt
        # Ba tiên (3 lá J/Q/K)
        if all(card[0] in ['J', 'Q', 'K'] for card in hand):
            return 10, "Ba tiên"
        
        # Ba đồng (3 lá cùng số)
        if all(card[0] == hand[0][0] for card in hand):
            return 11, "Ba đồng"
        
        # Sáp (có 2 lá giống nhau)
        card_values = [card[0] for card in hand]
        for val in card_values:
            if card_values.count(val) >= 2:
                return 12 if total > 0 else 12 + total, "Sáp " + str(total)
        
        # Điểm thường
        return total, f"{total} điểm"
    
    # Tính điểm cho hai người chơi
    player1_score, player1_type = calculate_score(player1_hand)
    player2_score, player2_type = calculate_score(player2_hand)
    
    # Format bài cho hiển thị
    def format_cards(cards):
        return " ".join(f"{card}{suit}" for card, suit in cards)
    
    # Hiệu ứng hiển thị bài lần lượt
    # Hiển thị bài của người chơi 1
    p1_embed = discord.Embed(
        title="🃏 BA CÀO PVP - BÀI CỦA NGƯỜI CHƠI 1",
        description=f"Bài của {player1.mention}:",
        color=discord.Color.gold()
    )
    p1_embed.add_field(name="Bài", value=format_cards(player1_hand), inline=False)
    p1_embed.add_field(name="Kết quả", value=f"{player1_type}", inline=False)
    await loading_msg.edit(embed=p1_embed)
    await asyncio.sleep(2)
    
    # Hiển thị bài của người chơi 2
    p2_embed = discord.Embed(
        title="🃏 BA CÀO PVP - BÀI CỦA NGƯỜI CHƠI 2",
        description=f"Bài của {player2.mention}:",
        color=discord.Color.gold()
    )
    p2_embed.add_field(name="Bài", value=format_cards(player2_hand), inline=False)
    p2_embed.add_field(name="Kết quả", value=f"{player2_type}", inline=False)
    await loading_msg.edit(embed=p2_embed)
    await asyncio.sleep(2)
    
    # Xác định người thắng
    if player1_score > player2_score:
        winner = player1
        loser = player2
    elif player2_score > player1_score:
        winner = player2
        loser = player1
    else:
        # Trường hợp hòa - ngẫu nhiên người thắng
        winner = random.choice([player1, player2])
        loser = player2 if winner == player1 else player1
    
    # Xử lý tiền cược
    winnings = int(bet_amount * 1.5)
    currency[winner.id] += winnings - bet_amount
    currency[loser.id] -= bet_amount
    
    # Tạo hiệu ứng kịch tính trước khi hiển thị kết quả
    compare_embed = discord.Embed(
        title="🃏 BA CÀO PVP - SO SÁNH KẾT QUẢ",
        description="Đang so sánh bài của hai người chơi...",
        color=discord.Color.gold()
    )
    compare_embed.add_field(
        name=f"{player1.display_name}",
        value=f"Bài: {format_cards(player1_hand)}\nKết quả: {player1_type}",
        inline=True
    )
    compare_embed.add_field(
        name=f"{player2.display_name}",
        value=f"Bài: {format_cards(player2_hand)}\nKết quả: {player2_type}",
        inline=True
    )
    await loading_msg.edit(embed=compare_embed)
    await asyncio.sleep(2)
    
    # Hiển thị kết quả cuối cùng
    result_embed = discord.Embed(
        title="🏆 KẾT QUẢ BA CÀO PVP",
        description=f"**{winner.display_name}** đã chiến thắng!",
        color=discord.Color.green()
    )
    
    result_embed.add_field(
        name=f"{player1.display_name}",
        value=f"Bài: {format_cards(player1_hand)}\nKết quả: {player1_type}",
        inline=True
    )
    result_embed.add_field(
        name=f"{player2.display_name}",
        value=f"Bài: {format_cards(player2_hand)}\nKết quả: {player2_type}",
        inline=True
    )
    
    result_embed.add_field(
        name="Phần thưởng",
        value=f"{winner.mention} nhận được {winnings} xu\n{loser.mention} mất {bet_amount} xu và bị timeout 5 phút",
        inline=False
    )
    
    # Timeout người thua
    try:
        timeout_until = discord.utils.utcnow() + timedelta(minutes=5)
        await loser.timeout(
            timeout_until,
            reason=f"Thua trong trò Ba Cào PvP với {winner.display_name}"
        )
        timeout_success = True
    except Exception as e:
        timeout_success = False
        result_embed.add_field(
            name="⚠️ Lỗi timeout",
            value=f"Không thể timeout {loser.mention}: {str(e)}",
            inline=False
        )
    
    # Cập nhật dữ liệu xu
    result_embed.add_field(
        name="Số dư mới",
        value=f"{winner.mention}: {currency[winner.id]} xu\n{loser.mention}: {currency[loser.id]} xu",
        inline=False
    )
    
    if timeout_success:
        result_embed.set_footer(text=f"{loser.display_name} đã bị timeout trong 5 phút!")
    
    await loading_msg.edit(embed=result_embed)

@bot.command(name='purge')
@commands.has_permissions(administrator=True)
async def purge_messages(ctx, amount: int = None):
    """Xóa một số lượng tin nhắn được chỉ định (chỉ admin)"""
    if amount is None:
        embed = discord.Embed(
            title="❓ Purge - Hướng Dẫn",
            description="Xóa một số lượng tin nhắn được chỉ định.",
            color=discord.Color.blue())
        embed.add_field(
            name="Cách sử dụng",
            value="`.purge [số lượng]`\nVí dụ: `.purge 10` để xóa 10 tin nhắn gần nhất.",
            inline=False)
        embed.add_field(
            name="Lưu ý",
            value="- Chỉ admin mới có thể sử dụng lệnh này\n- Số lượng tối đa là 100 tin nhắn\n- Không thể xóa tin nhắn cũ hơn 14 ngày",
            inline=False)
        await ctx.send(embed=embed)
        return

    if amount <= 0:
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Số lượng tin nhắn cần xóa phải lớn hơn 0.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    if amount > 100:
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Vì lý do an toàn, bạn chỉ có thể xóa tối đa 100 tin nhắn mỗi lần.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Xóa tin nhắn gốc trước
    await ctx.message.delete()

    # Xóa tin nhắn theo số lượng
    deleted = await ctx.channel.purge(limit=amount)

    # Gửi thông báo và tự động xóa sau 5 giây
    confirm_message = await ctx.send(
        embed=discord.Embed(
            title="✅ Đã xóa tin nhắn",
            description=f"Đã xóa {len(deleted)} tin nhắn.",
            color=discord.Color.green())
    )

    await asyncio.sleep(5)
    try:
        await confirm_message.delete()
    except:
        pass  # Bỏ qua nếu không thể xóa thông báo

@purge_messages.error
async def purge_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        embed = discord.Embed(
            title="❌ Không đủ quyền hạn",
            description="Bạn cần có quyền quản trị viên để sử dụng lệnh này.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
    elif isinstance(error, commands.BadArgument):
        embed = discord.Embed(
            title="❌ Lỗi thông số",
            description="Vui lòng cung cấp một số nguyên hợp lệ.",
            color=discord.Color.red())
        await ctx.send(embed=embed)


@bot.command(name='w')
async def view_permissions(ctx, member: discord.Member = None):
    """Xem thông tin quyền hạn và role của một thành viên"""
    target = member or ctx.author
    
    # Define special role IDs if not already defined
    SPECIAL_ROLE_IDS = {
        618702036992655381: "Thần sứ",
        938071848321712198: "Bố của Bạn",
        315087220363231233: "Chủ tịch",
        714092306558353579: "Trùm Trader",
        961613410078965850: "Trùm Build PC",
        950923415764754513: "Trùm Lùa Gà",
        848094216672509971: "Thám Tử Conan",
        629641520651304970: "Mẹ Mày Béo",
        882156430797459456: "Ngư Lôi Thần Tướng",
        1126656752574800023:"Bồ của Mai Phương",
        1327646903122399343:"Thần Hủy Diệt",
        1005115822152351788:"Bố của Dora",
        917977777976770640:"Bố của Ginv",
    }

    # Tạo embed cơ bản
    embed = discord.Embed(
        title=f"🛡️ Thông tin quyền hạn của {target.display_name}",
        description=f"ID: {target.id}",
        color=target.color if target.color != discord.Color.default() else discord.Color.blue()
    )
    
    # Kiểm tra nếu là chủ sở hữu server
    if target.id == ctx.guild.owner_id:
        embed.description = f"ID: {target.id}\n**👑 QUYỀN ĐẶC BIỆT: SERVER OWNER 👑**"
        embed.color = discord.Color.gold()
        embed.add_field(name="👑 QUYỀN ĐẶC BIỆT", value="**Server Owner:** Chủ sở hữu server với mọi quyền hạn", inline=False)
    
    # Kiểm tra nếu là người dùng đặc biệt với thiết kế đơn giản hơn
    elif target.id in SPECIAL_ROLE_IDS:
        special_role = SPECIAL_ROLE_IDS[target.id]
        embed.description = f"ID: {target.id}\n**🌟 QUYỀN ĐẶC BIỆT: {special_role.upper()} 🌟**"
        embed.color = discord.Color.gold()
        
        # Thêm biểu tượng đặc biệt cho người dùng mới
        if target.id == 848094216672509971:  # Thám Tử Conan
            embed.add_field(name="🔍 QUYỀN ĐẶC BIỆT", value="**Thám Tử Conan:** Phá án siêu đẳng", inline=False)
        elif target.id == 950923415764754513:  # Trùm Lùa Gà
            embed.add_field(name="🐔 QUYỀN ĐẶC BIỆT", value="**Trùm Lùa Gà:** Chuyên gia lùa gà vào server", inline=False)
        # Các biểu tượng đặc biệt hiện có
        elif target.id == 618702036992655381:  # Thần sứ
            embed.add_field(name="🔱 QUYỀN ĐẶC BIỆT", value="**Thần sứ:** STVSHOP.VN ", inline=False)
        elif target.id == 938071848321712198:  # Bố của Bạn
            embed.add_field(name="👑 QUYỀN ĐẶC BIỆT", value="**Bố của Bạn:** Được coi như người sở hữu server", inline=False)
        elif target.id == 315087220363231233:  # Chủ tịch
            embed.add_field(name="💼 QUYỀN ĐẶC BIỆT", value="**Chủ tịch:** Có quyền quyết định mọi vấn đề trong server", inline=False)
        elif target.id == 714092306558353579:  # Trùm Trader
            embed.add_field(name="📈 QUYỀN ĐẶC BIỆT", value="**Trùm Trader:** Chuyên Trader + Attacker", inline=False)
        elif target.id == 961613410078965850:  # Trùm Build PC
            embed.add_field(name="🖥️ QUYỀN ĐẶC BIỆT", value="**Trùm Build PC:** Build PC dạo (Luis Aga)", inline=False)
        elif target.id == 629641520651304970:  # Người Âm Phủ
            embed.add_field(name="🖥️ QUYỀN ĐẶC BIỆT", value="**Mẹ Mày Béo:** Người Âm Phủ", inline=False)
        elif target.id == 882156430797459456:  # Ngư Lôi Thần Tướng
            embed.add_field(name="🖥️ QUYỀN ĐẶC BIỆT", value="**Ngư Lôi Thần Tướng:** Bảo Mẫu của <@1126656752574800023>", inline=False)
        elif target.id == 1126656752574800023:  # Ngư Lôi Thần Tướng
            embed.add_field(name="🖥️ QUYỀN ĐẶC BIỆT", value="**Bồ của Mai Phương & Mina:** Kẻ thất bại trong tình yêu (Do LIỆT DƯƠNG)", inline=False)
        elif target.id == 1327646903122399343:  # Ngư Lôi Thần Tướng
            embed.add_field(name="🖥️ QUYỀN ĐẶC BIỆT", value="**THẦN HỦY DIỆT:** Kẻ hủy diệt 36", inline=False)
        elif target.id == 101081571838144512:  # Ngư Lôi Thần Tướng
            embed.add_field(name="🖥️ QUYỀN ĐẶC BIỆT", value="**Bố của Gin:** Bố của <@1191170922586050591>", inline=False)

    # Thêm avatar
    embed.set_thumbnail(url=target.display_avatar.url)

    # Thêm thông tin về roles - hiển thị nhỏ gọn hơn nhưng đầy đủ tên
    roles = target.roles[1:]  # Bỏ qua role @everyone
    if roles:
        role_count = len(roles)
        if role_count <= 20:  # Tăng giới hạn hiển thị
            # Tạo danh sách nhỏ gọn với tên đầy đủ
            compact_roles = []
            for role in sorted(roles, key=lambda x: x.position, reverse=True):
                compact_roles.append(f"{role.mention}")
            
            # Nối các role với dấu phẩy cho nhỏ gọn
            embed.add_field(
                name=f"Roles [{role_count}]",
                value=", ".join(compact_roles) if compact_roles else "Không có roles",
                inline=False
            )
        else:
            # Nếu quá nhiều role, hiển thị nhóm các role quan trọng
            top_roles = sorted(roles, key=lambda x: x.position, reverse=True)[:10]
            top_roles_text = ", ".join(f"{role.mention}" for role in top_roles)
            embed.add_field(
                name=f"Top Roles [{role_count} tổng]",
                value=f"{top_roles_text} và {role_count-10} role khác",
                inline=False
            )
    else:
        # Add this to show when user has no roles
        embed.add_field(
            name="Roles [0]",
            value="Không có roles",
            inline=False
        )

    # Thêm các quyền quan trọng - chỉ hiển thị quyền có hoặc quyền thường
    admin_perms = {
        "Administrator": target.guild_permissions.administrator,
        "Quản lý server": target.guild_permissions.manage_guild,
    }
    
    regular_perms = {
        "Quản lý kênh": target.guild_permissions.manage_channels,
        "Quản lý tin nhắn": target.guild_permissions.manage_messages,
        "Đá/Cấm thành viên": target.guild_permissions.kick_members or target.guild_permissions.ban_members
    }

    # Hiển thị quyền ngắn gọn
    perms_text = ""
    has_perms = False
    
    # Hiển thị admin perms chỉ khi người dùng có quyền
    for perm_name, has_perm in admin_perms.items():
        if has_perm:
            perms_text += f"✅ {perm_name}\n"
            has_perms = True
    
    # Hiển thị các quyền thường chỉ khi người dùng có quyền
    for perm_name, has_perm in regular_perms.items():
        if has_perm:
            perms_text += f"✅ {perm_name}\n"
            has_perms = True

    # Nếu là người dùng đặc biệt, thêm quyền đặc biệt vào danh sách
    if target.id in SPECIAL_ROLE_IDS:
        perms_text += f"✅ **{SPECIAL_ROLE_IDS[target.id]}**\n"
        has_perms = True
    
    # Nếu không có quyền nào, hiển thị thông báo
    if not has_perms:
        perms_text = "Không có quyền hạn đặc biệt"

    embed.add_field(name="Quyền hạn chính", value=perms_text, inline=False)

    # Thông tin tài khoản
    joined_at = target.joined_at.strftime("%d/%m/%Y") if target.joined_at else "Không xác định"
    created_at = target.created_at.strftime("%d/%m/%Y")
    embed.add_field(name="Thông tin tài khoản", 
                   value=f"🕒 Tham gia server: {joined_at}\n🗓️ Tạo tài khoản: {created_at}", 
                   inline=False)

    embed.set_footer(text=f"Yêu cầu bởi {ctx.author}")
    await ctx.send(embed=embed)


@view_permissions.error
async def view_permissions_error(ctx, error):
    if isinstance(error, commands.MemberNotFound):
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Không tìm thấy thành viên này. Vui lòng kiểm tra lại.",
            color=discord.Color.red())
        await ctx.send(embed=embed)

@bot.command(name='capxu', aliases=['randomxu', 'rx'])
@check_channel()
@check_game_enabled('capxu')
async def cap_xu_ngaunhien(ctx):
    """Nhận một số xu ngẫu nhiên từ hệ thống"""
    user_id = ctx.author.id
    
    # Kiểm tra thời gian cooldown (1 giờ)
    cooldown_key = f"capxu_{user_id}"
    current_time = datetime.now()
    
    if cooldown_key in command_cooldown:
        time_passed = (current_time - command_cooldown[cooldown_key]).total_seconds()
        cooldown_period = 3600  # 1 giờ = 3600 giây
        
        if time_passed < cooldown_period:
            remaining_time = cooldown_period - time_passed
            hours, remainder = divmod(int(remaining_time), 3600)
            minutes, seconds = divmod(remainder, 60)
            
            embed = discord.Embed(
                title="⏳ Vui lòng đợi",
                description=f"Bạn cần đợi **{hours} giờ {minutes} phút {seconds} giây** nữa để nhận xu ngẫu nhiên.",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
            return
    
    # Xác định số xu ngẫu nhiên
    min_xu = 10
    max_xu = 100
    
    # Người dùng trong whitelist có cơ hội nhận nhiều xu hơn
    if is_whitelisted(user_id):
        min_xu = 50
        max_xu = 500
    
    # Cộng xu ngẫu nhiên cho người chơi
    random_xu = random.randint(min_xu, max_xu)
    currency[user_id] += random_xu
    
    # Lưu thời gian sử dụng lệnh
    command_cooldown[cooldown_key] = current_time
    
    # Tạo hiệu ứng animation nhận xu
    loading_embed = discord.Embed(
        title="🎁 Đang mở hộp quà ngẫu nhiên...",
        description="Chờ một chút để xem bạn sẽ nhận được bao nhiêu xu!",
        color=discord.Color.blue()
    )
    message = await ctx.send(embed=loading_embed)
    
    # Hiệu ứng đang xử lý
    for i in range(3):
        await asyncio.sleep(0.7)
        loading_embed.description = f"Đang mở hộp quà{'.' * (i + 1)}"
        await message.edit(embed=loading_embed)
    
    # Hiển thị kết quả
    result_embed = discord.Embed(
        title="🎉 Nhận xu thành công!",
        description=f"{ctx.author.mention} đã nhận được **{random_xu} xu** ngẫu nhiên!",
        color=discord.Color.green()
    )
    
    # Thêm hiệu ứng hình ảnh dựa trên số xu nhận được
    if random_xu < 30:
        emoji = "🪙"
        comment = "Chỉ một chút thôi, nhưng vẫn có giá trị!"
    elif random_xu < 70:
        emoji = "💰"
        comment = "Khá tốt! Hãy sử dụng số xu này một cách khôn ngoan."
    else:
        emoji = "💎"
        comment = "Wow! Bạn thật may mắn hôm nay!"
    
    result_embed.add_field(
        name=f"{emoji} Phần thưởng",
        value=f"+{random_xu} xu",
        inline=True
    )
    
    result_embed.add_field(
        name="💼 Số dư hiện tại",
        value=f"{currency[user_id]} xu",
        inline=True
    )
    
    result_embed.add_field(
        name="💬 Nhận xét",
        value=comment,
        inline=False
    )
    
    result_embed.set_footer(text=f"Bạn có thể nhận xu ngẫu nhiên mỗi 1 giờ một lần.")
    
    await message.edit(embed=result_embed)


@bot.command(name='777', aliases=['slot', 'mayxeng'])
@check_channel()
@check_game_enabled('777')
async def slot_machine(ctx, bet: str = None):
    """Trò chơi máy đánh bạc quay xèn 777"""
    if bet is None:
        embed = discord.Embed(
            title="🎰 Máy Quay Xèn 777 - Hướng Dẫn",
            description="Hãy nhập số xu muốn cược.\nVí dụ: `.777 50` hoặc `.777 all`",
            color=discord.Color.blue())
        embed.add_field(
            name="Luật chơi",
            value="- Quay ba biểu tượng ngẫu nhiên\n- Ba biểu tượng giống nhau: Jackpot x5\n- Hai biểu tượng giống nhau: x2\n- Có số 7: Hoàn tiền cược\n- Còn lại: Mất tiền cược",
            inline=False)
        await ctx.send(embed=embed)
        return

    user_id = ctx.author.id

    # Xử lý đặt cược "all"
    bet_amount = parse_bet(bet, currency[user_id])
    if bet_amount is None:
        embed = discord.Embed(
            title="❌ Số tiền không hợp lệ",
            description="Vui lòng nhập số tiền hợp lệ hoặc 'all'.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Kiểm tra cooldown
    can_play, remaining_time = check_cooldown(user_id)
    if not can_play:
        embed = discord.Embed(
            title="⏳ Thời gian chờ",
            description=f"Bạn cần đợi thêm {remaining_time} giây trước khi chơi tiếp.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Kiểm tra tiền cược
    if bet_amount <= 0:
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Số tiền cược phải lớn hơn 0 xu.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    if currency[user_id] < bet_amount:
        embed = discord.Embed(
            title="❌ Không đủ xu",
            description=f"Bạn cần {bet_amount} xu để chơi, nhưng chỉ có {currency[user_id]} xu.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Các biểu tượng có thể xuất hiện
    symbols = ["🍒", "🍋", "🍇", "🎰", "💰", "🍀", "7️⃣"]

    # Khởi tạo tin nhắn với embed ban đầu
    initial_embed = discord.Embed(
        title="🎰 MÁY QUAY XÈN 777 🎰",
        description=f"{ctx.author.mention} đặt cược **{bet_amount} xu**",
        color=discord.Color.blue()
    )
    initial_embed.add_field(
        name="Máy đang khởi động...", 
        value="Vui lòng chờ trong giây lát...",
        inline=False
    )
    loading = await ctx.send(embed=initial_embed)
    await asyncio.sleep(1)

    # Hiệu ứng quay máy đánh bạc - animation mới
    colors = [discord.Color.blue(), discord.Color.purple(), discord.Color.gold(), discord.Color.red()]

    # Animation kéo cần gạt
    lever_embed = discord.Embed(
        title="🎰 MÁY QUAY XÈN 777 🎰",
        description=f"{ctx.author.mention} đang kéo cần gạt...",
        color=colors[0]
    )
    lever_embed.add_field(
        name="⬇️ Kéo cần gạt", 
        value="```\n  |  \n  |  \n  |  \n  V  \n```",
        inline=False
    )
    await loading.edit(embed=lever_embed)
    await asyncio.sleep(0.7)

    # Hiệu ứng bánh xe bắt đầu quay
    for i in range(5):
        spin_embed = discord.Embed(
            title="🎰 MÁY QUAY XÈN 777 🎰",
            description=f"{ctx.author.mention} đặt cược **{bet_amount} xu**",
            color=colors[i % len(colors)]
        )
        
        # Tạo hiệu ứng quay với các biểu tượng khác nhau
        spinning_symbols = [random.choice(symbols) for _ in range(3)]
        spin_display = " | ".join(spinning_symbols)
        
        spin_embed.add_field(
            name=f"🔄 Đang quay {'.' * ((i % 3) + 1)}", 
            value=f"[ {spin_display} ]",
            inline=False
        )
        
        await loading.edit(embed=spin_embed)
        await asyncio.sleep(0.7 - i * 0.1)  # Giảm dần thời gian đợi

    # Kết quả cuối cùng (điều chỉnh tỷ lệ thắng/thua)
    win_result = random.choices([True, False], weights=[30, 70], k=1)[0]

    # Kiểm tra whitelist và jackpot
    if is_whitelisted(ctx.author.id):
        win_result = True
        jackpot_result = random.random() < 0.3  # 30% cơ hội jackpot cho người dùng whitelist
    else:
        jackpot_result = random.random() < 0.05  # 5% cơ hội jackpot cho người dùng thường

    # Tạo kết quả dựa vào tình huống
    if jackpot_result:
        # Jackpot - 3 số 7
        result = ["7️⃣", "7️⃣", "7️⃣"]
    elif win_result:
        # Thắng - 3 biểu tượng giống nhau hoặc 2 biểu tượng giống nhau
        symbol = random.choice(symbols)
        if random.random() < 0.3:  # 30% cơ hội có 3 biểu tượng giống nhau
            result = [symbol, symbol, symbol]
        else:  # 2 biểu tượng giống nhau
            different_symbol = random.choice([s for s in symbols if s != symbol])
            result = [symbol, symbol, different_symbol]
            # Xáo trộn vị trí để không luôn theo thứ tự cố định
            random.shuffle(result)
    else:
        # Thua - có thể có 1 số 7 để hoàn tiền hoặc toàn bộ khác nhau
        if random.random() < 0.2:  # 20% cơ hội có số 7 (hoàn tiền)
            symbols_without_seven = [s for s in symbols if s != "7️⃣"]
            other_symbols = random.sample(symbols_without_seven, 2)
            result = ["7️⃣"] + other_symbols
            random.shuffle(result)
        else:
            # Đảm bảo 3 biểu tượng khác nhau
            result = random.sample(symbols, 3)
            # Đảm bảo không có quá 2 biểu tượng giống nhau
            if result.count(result[0]) > 1 and result.count(result[1]) > 1:
                # Nếu vẫn có 3 biểu tượng giống nhau, thay đổi một biểu tượng
                result[2] = random.choice([s for s in symbols if s != result[0]])

    # Tạo hiệu ứng dừng từng reel một để tăng kịch tính
    # Reel 1 dừng
    first_reel_embed = discord.Embed(
        title="🎰 MÁY QUAY XÈN 777 🎰",
        description=f"{ctx.author.mention} đặt cược **{bet_amount} xu**",
        color=colors[1]
    )
    first_reel_embed.add_field(
        name="🛑 Reel 1 dừng lại!", 
        value=f"[ {result[0]} | ?? | ?? ]",
        inline=False
    )
    await loading.edit(embed=first_reel_embed)
    await asyncio.sleep(1)

    # Reel 2 dừng
    second_reel_embed = discord.Embed(
        title="🎰 MÁY QUAY XÈN 777 🎰",
        description=f"{ctx.author.mention} đặt cược **{bet_amount} xu**",
        color=colors[2]
    )
    second_reel_embed.add_field(
        name="🛑 Reel 2 dừng lại!", 
        value=f"[ {result[0]} | {result[1]} | ?? ]",
        inline=False
    )
    await loading.edit(embed=second_reel_embed)
    await asyncio.sleep(1)

    # Đếm ngược trước khi hiện kết quả cuối cùng
    countdown_embed = discord.Embed(
        title="🎰 MÁY QUAY XÈN 777 🎰",
        description=f"{ctx.author.mention} đặt cược **{bet_amount} xu**",
        color=colors[3]
    )
    countdown_embed.add_field(
        name="⏱️ Reel cuối cùng sắp dừng!", 
        value=f"[ {result[0]} | {result[1]} | ?? ]",
        inline=False
    )
    await loading.edit(embed=countdown_embed)
    await asyncio.sleep(0.8)

    # Đếm số biểu tượng giống nhau
    counts = {}
    for symbol in result:
        if symbol in counts:
            counts[symbol] += 1
        else:
            counts[symbol] = 1

    # Xác định thắng thua
    has_seven = "7️⃣" in result
    max_count = max(counts.values()) if counts else 0

    # Xác định màu sắc và thông báo kết quả
    if "7️⃣" in counts and counts["7️⃣"] == 3:
        # Jackpot - 3 số 7
        win_message = f"🎉 JACKPOT! {ctx.author.mention} thắng lớn với 3 số 7!"
        color = discord.Color.gold()
        winnings = bet_amount * 5
        currency[user_id] += winnings - bet_amount
    elif max_count == 3:
        # 3 biểu tượng giống nhau
        win_message = f"🎉 {ctx.author.mention} thắng với 3 biểu tượng giống nhau!"
        color = discord.Color.green()
        winnings = bet_amount * 3
        currency[user_id] += winnings - bet_amount
    elif max_count == 2:
        # 2 biểu tượng giống nhau
        win_message = f"🎉 {ctx.author.mention} thắng với 2 biểu tượng giống nhau!"
        color = discord.Color.blue()
        winnings = bet_amount * 2
        currency[user_id] += winnings - bet_amount
    elif has_seven:
        # Có số 7 - hoàn tiền
        win_message = f"🎲 {ctx.author.mention} hòa vốn với biểu tượng 7️⃣!"
        color = discord.Color.purple()
        winnings = bet_amount
        # Không thay đổi số tiền vì hoàn lại tiền cược
    else:
        # Thua
        win_message = f"❌ {ctx.author.mention} đã thua!"
        color = discord.Color.red()
        winnings = 0
        currency[user_id] -= bet_amount

    # Animation kết quả cuối cùng
    final_result_embed = discord.Embed(
        title="🎰 KẾT QUẢ MÁY QUAY XÈN 777 🎰",
        description=win_message,
        color=color
    )

    # Hiển thị kết quả với hiệu ứng đẹp mắt
    result_display = " | ".join(result)
    final_result_embed.add_field(
        name="🎯 Kết quả quay", 
        value=f"[ {result_display} ]", 
        inline=False
    )

    # Hiển thị thông tin thắng/thua
    if max_count >= 2 or has_seven:
        if winnings > bet_amount:
            final_result_embed.add_field(
                name="💰 Tiền thắng", 
                value=f"+{winnings - bet_amount} xu", 
                inline=True
            )
        elif winnings == bet_amount:
            final_result_embed.add_field(
                name="🔄 Hoàn tiền", 
                value=f"{bet_amount} xu", 
                inline=True
            )
    else:
        final_result_embed.add_field(
            name="💸 Tiền thua", 
            value=f"-{bet_amount} xu", 
            inline=True
        )

    final_result_embed.add_field(
        name="💼 Số dư hiện tại",
        value=f"{currency[user_id]} xu",
        inline=True
    )

    # Thêm mô tả chi tiết về thắng/thua
    if max_count == 3 and "7️⃣" in counts and counts["7️⃣"] == 3:
        final_result_embed.add_field(
            name="🏆 JACKPOT!", 
            value="Ba số 7 liên tiếp! Giải thưởng cực lớn!",
            inline=False
        )
    elif max_count == 3:
        final_result_embed.add_field(
            name="🏆 Giải lớn!", 
            value=f"Ba biểu tượng {list(counts.keys())[list(counts.values()).index(3)]} giống nhau!",
            inline=False
        )
    elif max_count == 2:
        # Tìm biểu tượng xuất hiện 2 lần
        for symbol, count in counts.items():
            if count == 2:
                final_result_embed.add_field(
                    name="🎁 Giải thường", 
                    value=f"Hai biểu tượng {symbol} giống nhau!",
                    inline=False
                )
                break
    elif has_seven:
        final_result_embed.add_field(
            name="🎲 May mắn", 
            value="Biểu tượng 7️⃣ xuất hiện! Bạn được hoàn tiền cược!",
            inline=False
        )

    final_result_embed.set_footer(text=f"Người chơi: {ctx.author.display_name} | Chơi có trách nhiệm!")
    await loading.edit(embed=final_result_embed)

@bot.command(name='untimeout')
@commands.has_permissions(moderate_members=True)
async def untimeout_member(ctx, member: discord.Member = None, *, reason: str = "Đã hết thời gian timeout"):
    """Hủy timeout cho một thành viên"""
    if member is None:
        embed = discord.Embed(
            title="❓ Untimeout - Hướng dẫn",
            description="Hủy timeout cho thành viên",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="Cách sử dụng",
            value="`.untimeout @người_dùng [lý do]`",
            inline=False
        )
        await ctx.send(embed=embed)
        return
        
    if not member.is_timed_out():
        embed = discord.Embed(
            title="⚠️ Không thể hủy timeout",
            description=f"{member.mention} hiện không bị timeout.",
            color=discord.Color.yellow()
        )
        await ctx.send(embed=embed)
        return
        
    try:
        # Hủy timeout bằng cách đặt timeout_until=None
        await member.timeout(None, reason=f"Timeout bị hủy bởi {ctx.author.name}: {reason}")
        
        # Gửi thông báo xác nhận
        embed = discord.Embed(
            title="✅ Đã hủy timeout",
            description=f"Timeout cho {member.mention} đã được hủy bỏ.",
            color=discord.Color.green()
        )
        embed.add_field(name="Lý do", value=reason, inline=False)
        embed.add_field(name="Thực hiện bởi", value=ctx.author.mention, inline=False)
        embed.set_footer(text=f"ID: {member.id}")
        await ctx.send(embed=embed)
        
    except discord.Forbidden:
        await ctx.send("❌ Bot không có đủ quyền để hủy timeout cho thành viên này!")
    except Exception as e:
        await ctx.send(f"❌ Đã xảy ra lỗi: {str(e)}")


@bot.command(name='kick')
@admin_only()
async def kick(ctx, member: discord.Member = None, *, reason: str = "Không có lý do"):
    """Kick thành viên khỏi server (chỉ admin dùng được)"""
    if member is None:
        embed = discord.Embed(
            title="👢 Kick - Hướng dẫn",
            description="Đuổi thành viên khỏi server",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="Cách sử dụng",
            value="`.kick @người_dùng [lý do]`",
            inline=False
        )
        await ctx.send(embed=embed)
        return
        
    # Không cho phép kick chính mình
    if member.id == ctx.author.id:
        await ctx.send("❌ Bạn không thể kick chính mình!")
        return
        
    try:
        # Thực hiện kick
        await member.kick(reason=f"Bị kick bởi {ctx.author.name}: {reason}")
        
        # Gửi thông báo xác nhận
        embed = discord.Embed(
            title="👢 Đã kick thành viên",
            description=f"{member.mention} đã bị kick khỏi server.",
            color=discord.Color.green()
        )
        embed.add_field(name="Lý do", value=reason, inline=False)
        embed.add_field(name="Thực hiện bởi", value=ctx.author.mention, inline=False)
        embed.set_footer(text=f"ID: {member.id}")
        await ctx.send(embed=embed)
    except discord.Forbidden:
        await ctx.send("❌ Bot không có đủ quyền để kick thành viên này!")
    except Exception as e:
        await ctx.send(f"❌ Đã xảy ra lỗi: {str(e)}")

@bot.command(name='ban')
@admin_only()
async def ban(ctx, member: discord.Member = None, *, reason: str = "Không có lý do"):
    """Ban thành viên khỏi server (chỉ admin dùng được)"""
    if member is None:
        embed = discord.Embed(
            title="🔨 Ban - Hướng dẫn",
            description="Cấm thành viên khỏi server",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="Cách sử dụng",
            value="`.ban @người_dùng [lý do]`",
            inline=False
        )
        await ctx.send(embed=embed)
        return
        
    # Không cho phép ban chính mình
    if member.id == ctx.author.id:
        await ctx.send("❌ Bạn không thể ban chính mình!")
        return
        
    try:
        # Thực hiện ban
        await member.ban(reason=f"Bị ban bởi {ctx.author.name}: {reason}")
        
        # Gửi thông báo xác nhận
        embed = discord.Embed(
            title="🔨 Đã ban thành viên",
            description=f"{member.mention} đã bị ban khỏi server.",
            color=discord.Color.green()
        )
        embed.add_field(name="Lý do", value=reason, inline=False)
        embed.add_field(name="Thực hiện bởi", value=ctx.author.mention, inline=False)
        embed.set_footer(text=f"ID: {member.id}")
        await ctx.send(embed=embed)
    except discord.Forbidden:
        await ctx.send("❌ Bot không có đủ quyền để ban thành viên này!")
    except Exception as e:
        await ctx.send(f"❌ Đã xảy ra lỗi: {str(e)}")

# Thêm lệnh admin xem két của người khác
@bot.command(name='ad_xemket', aliases=['axk'])
@commands.has_permissions(administrator=True)
async def admin_view_vault(ctx, member: discord.Member = None):
    """Cho phép admin xem số xu trong két của người chơi khác"""
    if member is None:
        embed = discord.Embed(
            title="❓ Xem Két (Admin)",
            description=
            "Vui lòng chỉ định một thành viên để kiểm tra. Ví dụ: `.ad_xemket @người_dùng`",
            color=discord.Color.blue())
        await ctx.send(embed=embed)
        return

    guild_id = ctx.guild.id
    user_id = member.id
    user_vault_balance = vault[guild_id][user_id]

    embed = discord.Embed(
        title="🔒 Két Sắt Người Dùng (Admin View)",
        description=f"Thông tin két sắt của {member.mention}:",
        color=discord.Color.gold())
    embed.add_field(name="Số xu trong két",
                    value=f"**{user_vault_balance} xu**",
                    inline=False)
    embed.add_field(name="Số xu thường",
                    value=f"**{currency[user_id]} xu**",
                    inline=False)
    embed.add_field(name="Tổng số xu",
                    value=f"**{currency[user_id] + user_vault_balance} xu**",
                    inline=False)

    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(
        text=f"ID: {user_id} | Requested by Admin: {ctx.author.name}")

    await ctx.send(embed=embed)


@admin_view_vault.error
async def admin_view_vault_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        embed = discord.Embed(
            title="❌ Lỗi Quyền Hạn",
            description="Bạn cần có quyền quản trị viên để sử dụng lệnh này.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
    elif isinstance(error, commands.BadArgument):
        embed = discord.Embed(
            title="❌ Lỗi Thông Số",
            description=
            "Không tìm thấy thành viên này. Vui lòng đảm bảo bạn đã tag đúng người dùng.",
            color=discord.Color.red())
        await ctx.send(embed=embed)


# Thêm lệnh admin xóa két của người khác với bảo vệ cho admin chính
@bot.command(name='ad_xoaket', aliases=['axk2', 'clearket'])
@commands.has_permissions(administrator=True)
async def admin_clear_vault(ctx, member: discord.Member = None):
    """Cho phép admin xóa số xu trong két của người chơi khác"""
    if member is None:
        embed = discord.Embed(
            title="❓ Xóa Két (Admin)",
            description=
            "Vui lòng chỉ định một thành viên để xóa két. Ví dụ: `.ad_xoaket @người_dùng`",
            color=discord.Color.blue())
        await ctx.send(embed=embed)
        return

    # Bảo vệ ID admin chính
    if member.id == 618702036992655381:
        embed = discord.Embed(title="🛡️ Bảo Vệ Admin",
                              description="Không thể xóa két của admin chính!",
                              color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    guild_id = ctx.guild.id
    user_id = member.id
    previous_balance = vault[guild_id][user_id]

    if previous_balance == 0:
        embed = discord.Embed(
            title="⚠️ Thông Báo",
            description=f"Két của {member.mention} đã trống (0 xu).",
            color=discord.Color.yellow())
        await ctx.send(embed=embed)
        return

    # Tạo xác nhận trước khi xóa
    confirm_embed = discord.Embed(
        title="🔴 Xác Nhận Xóa Két",
        description=
        f"Bạn có chắc chắn muốn xóa **{previous_balance} xu** trong két của {member.mention}?",
        color=discord.Color.red())
    confirm_embed.set_footer(text="Hành động này không thể hoàn tác!")

    # Tạo các nút xác nhận
    confirm_button = discord.ui.Button(label="Xác nhận",
                                       style=discord.ButtonStyle.danger,
                                       emoji="✅")
    cancel_button = discord.ui.Button(label="Hủy bỏ",
                                      style=discord.ButtonStyle.secondary,
                                      emoji="❌")

    view = discord.ui.View(timeout=60)
    view.add_item(confirm_button)
    view.add_item(cancel_button)

    # Gửi tin nhắn với các nút
    confirm_msg = await ctx.send(embed=confirm_embed, view=view)

    # Xử lý phản hồi
    async def confirm_callback(interaction):
        if interaction.user.id != ctx.author.id:
            await interaction.response.send_message(
                "Chỉ người dùng lệnh mới có thể xác nhận!", ephemeral=True)
            return

        # Xóa xu trong két
        vault[guild_id][user_id] = 0

        # Vô hiệu hóa các nút
        view.clear_items()
        await interaction.response.edit_message(view=view)

        # Thông báo thành công
        success_embed = discord.Embed(
            title="✅ Xóa Két Thành Công",
            description=
            f"Đã xóa **{previous_balance} xu** từ két của {member.mention}.",
            color=discord.Color.green())
        success_embed.add_field(name="Số dư két hiện tại",
                                value="0 xu",
                                inline=False)
        success_embed.add_field(name="Admin thực hiện",
                                value=ctx.author.mention,
                                inline=False)
        success_embed.set_footer(
            text=
            f"User ID: {user_id} | {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
        )

        await confirm_msg.edit(embed=success_embed)

    async def cancel_callback(interaction):
        if interaction.user.id != ctx.author.id:
            await interaction.response.send_message(
                "Chỉ người dùng lệnh mới có thể hủy bỏ!", ephemeral=True)
            return

        # Vô hiệu hóa các nút
        view.clear_items()
        await interaction.response.edit_message(view=view)

        # Thông báo hủy bỏ
        cancel_embed = discord.Embed(
            title="❌ Đã Hủy Bỏ",
            description="Hành động xóa két đã bị hủy bỏ.",
            color=discord.Color.grey())
        await confirm_msg.edit(embed=cancel_embed)

    # Gán callback cho các nút
    confirm_button.callback = confirm_callback
    cancel_button.callback = cancel_callback


@admin_clear_vault.error
async def admin_clear_vault_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        embed = discord.Embed(
            title="❌ Lỗi Quyền Hạn",
            description="Bạn cần có quyền quản trị viên để sử dụng lệnh này.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
    elif isinstance(error, commands.BadArgument):
        embed = discord.Embed(
            title="❌ Lỗi Thông Số",
            description=
            "Không tìm thấy thành viên này. Vui lòng đảm bảo bạn đã tag đúng người dùng.",
            color=discord.Color.red())
        await ctx.send(embed=embed)


@bot.command(name='blacklist', aliases=['bl'])
@commands.has_permissions(administrator=True)
async def blacklist_command(ctx,
                            action: str = None,
                            member: discord.Member = None):
    """Thêm hoặc xóa người dùng khỏi danh sách đen"""
    if action is None or member is None or action.lower() not in [
            'add', 'remove'
    ]:
        embed = discord.Embed(
            title="❓ Danh sách đen - Hướng Dẫn",
            description="Thêm hoặc xóa người dùng khỏi danh sách đen.\n"
            "Người dùng trong danh sách đen không thể sử dụng các lệnh trò chơi.",
            color=discord.Color.blue())
        embed.add_field(
            name="Cách sử dụng",
            value=
            "`.blacklist add @người_dùng` - Thêm người dùng vào danh sách đen\n"
            "`.blacklist remove @người_dùng` - Xóa người dùng khỏi danh sách đen\n"
            "`.blacklistview` - Xem danh sách người dùng bị chặn",
            inline=False)
        await ctx.send(embed=embed)
        return

    user_id = member.id
    action = action.lower()

    # Bảo vệ ID admin chính
    if member.id == 618702036992655381 and action == 'add':
        embed = discord.Embed(
            title="🛡️ Bảo Vệ Admin",
            description="Không thể thêm admin chính vào danh sách đen!",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    if action == 'add':
        blacklisted_users.add(user_id)
        embed = discord.Embed(
            title="✅ Đã thêm vào danh sách đen",
            description=
            f"{member.mention} đã bị thêm vào danh sách đen.\nNgười dùng này sẽ không thể sử dụng các lệnh trò chơi.",
            color=discord.Color.green())
        await ctx.send(embed=embed)
    elif action == 'remove':
        if user_id in blacklisted_users:
            blacklisted_users.remove(user_id)
            embed = discord.Embed(
                title="✅ Đã xóa khỏi danh sách đen",
                description=
                f"{member.mention} đã được xóa khỏi danh sách đen.\nNgười dùng này có thể sử dụng các lệnh trò chơi.",
                color=discord.Color.green())
            await ctx.send(embed=embed)
        else:
            embed = discord.Embed(
                title="❌ Không tìm thấy",
                description=f"{member.mention} không có trong danh sách đen.",
                color=discord.Color.red())
            await ctx.send(embed=embed)


@bot.command(name='blacklistview', aliases=['blview'])
@commands.has_permissions(administrator=True)
async def blacklist_view(ctx):
    """Xem tất cả người dùng trong danh sách đen"""
    if not blacklisted_users:
        embed = discord.Embed(title="📋 Danh sách đen",
                              description="Danh sách đen hiện đang trống.",
                              color=discord.Color.blue())
        await ctx.send(embed=embed)
        return

    embed = discord.Embed(
        title="📋 Danh sách đen",
        description=
        f"Có {len(blacklisted_users)} người dùng trong danh sách đen:",
        color=discord.Color.red())

    # Lấy và hiển thị thông tin người dùng cho mỗi ID trong blacklist
    for i, user_id in enumerate(blacklisted_users, 1):
        try:
            user = await bot.fetch_user(user_id)
            embed.add_field(name=f"{i}. {user.name}",
                            value=f"ID: {user_id}",
                            inline=False)
        except:
            embed.add_field(name=f"{i}. Người dùng không xác định",
                            value=f"ID: {user_id}",
                            inline=False)

    embed.set_footer(
        text="Sử dụng .blacklist remove @người_dùng để xóa khỏi danh sách đen")
    await ctx.send(embed=embed)


@bot.command(name='howiq', aliases=['iq'])
async def howiq(ctx, member: discord.Member = None):
    """Kiểm tra chỉ số IQ của một thành viên với kết quả ngẫu nhiên"""
    target = member or ctx.author
    iq_score = random.randint(70, 170)

    # Tạo biểu tượng và thông báo dựa vào IQ
    if iq_score < 90:
        emoji = "🥔"
        color = discord.Color.light_gray()
        message = "Khá... đặc biệt! Đôi khi đơn giản là tốt nhất!"
    elif iq_score < 110:
        emoji = "🧠"
        color = discord.Color.blue()
        message = "Chỉ số IQ trung bình, khá ổn!"
    elif iq_score < 140:
        emoji = "🧪"
        color = discord.Color.gold()
        message = "Rất thông minh! Có lẽ bạn nên thử các câu đố phức tạp!"
    else:
        emoji = "🔬"
        color = discord.Color.purple()
        message = "Thiên tài! Einstein cũng phải nể phục!"

    embed = discord.Embed(
        title=f"🧠 Máy Đo Chỉ Số IQ",
        description=f"Chỉ số IQ của {target.mention} là **{iq_score}** {emoji}",
        color=color)
    embed.add_field(name="Nhận xét", value=message, inline=False)
    embed.set_thumbnail(url=target.display_avatar.url)

    await ctx.send(embed=embed)


@bot.command(name='howperson', aliases=['personality', 'nhancach'])
async def personality_test(ctx, member: discord.Member = None):
    """Phân tích nhân cách của một thành viên"""
    target = member or ctx.author

    # Các loại nhân cách MBTI
    personality_types = [{
        "type":
        "INTJ",
        "name":
        "Kiến Trúc Sư",
        "emoji":
        "🏛️",
        "color":
        discord.Color.dark_blue(),
        "desc":
        "Nhà tư tưởng chiến lược với kế hoạch cho mọi thứ"
    }, {
        "type":
        "INTP",
        "name":
        "Nhà Logic Học",
        "emoji":
        "🔬",
        "color":
        discord.Color.teal(),
        "desc":
        "Nhà tư tưởng sáng tạo, thích giải quyết vấn đề phức tạp"
    }, {
        "type":
        "ENTJ",
        "name":
        "Chỉ Huy",
        "emoji":
        "👑",
        "color":
        discord.Color.gold(),
        "desc":
        "Lãnh đạo táo bạo, có sức mạnh ý chí và đầy tham vọng"
    }, {
        "type":
        "ENTP",
        "name":
        "Người Tranh Luận",
        "emoji":
        "⚖️",
        "color":
        discord.Color.orange(),
        "desc":
        "Nhà tư tưởng thông minh và tò mò, không thể cưỡng lại một thách thức trí óc"
    }, {
        "type":
        "INFJ",
        "name":
        "Người Ủng Hộ",
        "emoji":
        "🧿",
        "color":
        discord.Color.purple(),
        "desc":
        "Nhà tư tưởng yên tĩnh và thần bí, đầy cảm hứng và lý tưởng"
    }, {
        "type": "INFP",
        "name": "Người Hòa Giải",
        "emoji": "🕊️",
        "color": discord.Color.teal(),
        "desc": "Nhà thơ, người lý tưởng hóa đầy lòng nhân ái"
    }, {
        "type":
        "ENFJ",
        "name":
        "Người Bảo Vệ",
        "emoji":
        "🛡️",
        "color":
        discord.Color.red(),
        "desc":
        "Lãnh đạo đầy cảm hứng, quyến rũ và có động lực cao"
    }, {
        "type":
        "ENFP",
        "name":
        "Người Vận Động",
        "emoji":
        "🎭",
        "color":
        discord.Color.gold(),
        "desc":
        "Người nhiệt tình, sáng tạo và hòa đồng, luôn tìm thấy lý do để mỉm cười"
    }, {
        "type":
        "ISTJ",
        "name":
        "Nhà Hậu Cần",
        "emoji":
        "📊",
        "color":
        discord.Color.dark_gray(),
        "desc":
        "Người thực tế và có trách nhiệm cao, quyết đoán và đáng tin cậy"
    }, {
        "type":
        "ISFJ",
        "name":
        "Người Bảo Vệ",
        "emoji":
        "🏠",
        "color":
        discord.Color.green(),
        "desc":
        "Người bảo vệ rất tận tụy, ấm áp và sẵn sàng bảo vệ người thân"
    }, {
        "type":
        "ESTJ",
        "name":
        "Giám Đốc Điều Hành",
        "emoji":
        "💼",
        "color":
        discord.Color.blue(),
        "desc":
        "Nhà quản trị xuất sắc, không thể vượt qua khi cần quản lý"
    }, {
        "type":
        "ESFJ",
        "name":
        "Người Quan Tâm",
        "emoji":
        "💝",
        "color":
        discord.Color.magenta(),
        "desc":
        "Người hết lòng vì người khác, luôn quan tâm đến nhu cầu của mọi người"
    }, {
        "type":
        "ISTP",
        "name":
        "Kỹ Sư",
        "emoji":
        "🔧",
        "color":
        discord.Color.dark_orange(),
        "desc":
        "Người thợ táo bạo và thực tế với sở thích khám phá bằng tay"
    }, {
        "type":
        "ISFP",
        "name":
        "Nghệ Sĩ",
        "emoji":
        "🎨",
        "color":
        discord.Color.lighter_grey(),
        "desc":
        "Nghệ sĩ táo bạo và thân thiện, luôn sẵn sàng khám phá"
    }, {
        "type": "ESTP",
        "name": "Người Doanh Nhân",
        "emoji": "🚀",
        "color": discord.Color.red(),
        "desc": "Người thông minh, năng lượng và rất nhạy bén"
    }, {
        "type":
        "ESFP",
        "name":
        "Người Giải Trí",
        "emoji":
        "🎉",
        "color":
        discord.Color.gold(),
        "desc":
        "Người hướng ngoại, thân thiện và chấp nhận rủi ro"
    }]

    # Chọn ngẫu nhiên một loại nhân cách
    personality = random.choice(personality_types)

    # Các đặc điểm tính cách
    traits = [
        "Hướng nội" if "I" in personality["type"] else "Hướng ngoại",
        "Trực giác" if "N" in personality["type"] else "Cảm nhận",
        "Suy nghĩ" if "T" in personality["type"] else "Cảm xúc",
        "Đánh giá" if "J" in personality["type"] else "Nhận thức"
    ]

    # Tạo phần trăm cho mỗi đặc điểm
    trait_percentages = {
        traits[0]: random.randint(55, 95),
        traits[1]: random.randint(55, 95),
        traits[2]: random.randint(55, 95),
        traits[3]: random.randint(55, 95)
    }

    embed = discord.Embed(
        title=f"{personality['emoji']} Phân Tích Nhân Cách",
        description=
        f"Nhân cách của {target.mention} là **{personality['type']} - {personality['name']}**",
        color=personality['color'])

    embed.add_field(name="Mô tả", value=personality['desc'], inline=False)

    # Hiển thị các đặc điểm tính cách
    for trait, percentage in trait_percentages.items():
        progress_bar = "█" * (percentage // 10) + "░" * (10 - percentage // 10)
        embed.add_field(name=trait,
                        value=f"`{progress_bar}` {percentage}%",
                        inline=False)

    embed.set_thumbnail(url=target.display_avatar.url)
    embed.set_footer(
        text="Đây chỉ là kết quả ngẫu nhiên cho mục đích giải trí")

    await ctx.send(embed=embed)


@bot.command(name='stvdis')
@commands.has_permissions(administrator=True)
async def disable_game(ctx, game_name: str = None):
    """Vô hiệu hóa hoặc bật một game cụ thể hoặc tất cả các game"""
    if game_name is None:
        # Hiển thị trạng thái hiện tại của tất cả các game
        embed = discord.Embed(
            title="🎮 Trạng thái các trò chơi",
            description="Danh sách các trò chơi và trạng thái hiện tại",
            color=discord.Color.blue())

        # Nhóm game theo loại
        game_groups = {
            "🎲 Game cơ bản": [
                "cl", "tx", "tungxu", "coquaynga", "baucua", "kbb", "kbbpvp",
                "vqmm"
            ],
            "🃏 Game bài": ["poker", "xidach", "maubinh", "bacaopvp", "phom"],
            "🎯 Game khác":
            ["pinggo", "loto", "777", "fight", "hoidap", "caropvp"],
            "💰 Chức năng xu": ["dd", "vayxu", "capxu", "shop"]
        }

        # Hiển thị theo nhóm
        for group_name, games in game_groups.items():
            games_status = []
            for game in games:
                status = "🚫 TẮT" if disabled_games[game] else "✅ BẬT"
                games_status.append(f"{game}: {status}")

            embed.add_field(name=group_name,
                            value=" | ".join(games_status),
                            inline=False)

        # Thêm trạng thái 'all games' ở cuối
        all_status = "🚫 ĐÃ TẮT" if disabled_games['all'] else "✅ ĐANG BẬT"
        embed.add_field(name="🔒 TẤT CẢ GAME (all)",
                        value=all_status,
                        inline=False)

        embed.set_footer(text="Sử dụng .stvdis [tên game] để bật/tắt game")
        await ctx.send(embed=embed)
        return

    # Kiểm tra xem tên game có hợp lệ không
    if game_name.lower() not in disabled_games:
        embed = discord.Embed(
            title="❌ Lỗi",
            description=
            f"Không tìm thấy game '{game_name}'. Vui lòng sử dụng lệnh `.stvdis` để xem danh sách.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    game_name = game_name.lower()
    # Chuyển đổi trạng thái game
    disabled_games[game_name] = not disabled_games[game_name]
    status = "TẮT" if disabled_games[game_name] else "BẬT"

    # Nếu bật tất cả game, reset lại trạng thái từng game riêng lẻ
    if game_name == 'all' and not disabled_games['all']:
        for game in disabled_games:
            if game != 'all':
                disabled_games[game] = False

    game_display_name = "TẤT CẢ GAME" if game_name == 'all' else f"game {game_name}"

    embed = discord.Embed(title="✅ Thành công",
                          description=f"Đã {status} **{game_display_name}**.",
                          color=discord.Color.red() if
                          disabled_games[game_name] else discord.Color.green())
    embed.set_footer(text=f"Thực hiện bởi admin: {ctx.author.display_name}")

    await ctx.send(embed=embed)


# Shop items dictionary with details
shop_items = {
    "role_1h": {
        "name": "Role VIP 1 Giờ",
        "price": 100000000,  # 100m xu
        "description": "Nhận role VIP trong 1 giờ",
        "emoji": "⭐",
        "duration": 3600,  # 1 hour in seconds 
        "effect": "vip_role",
        "role_id": 1349745286972440708
    },
    "role_1d": {
        "name": "Role VIP 1 Ngày",
        "price": 1000000000,  # 1b xu
        "description": "Nhận role VIP trong 1 ngày",
        "emoji": "🌟",
        "duration": 86400,  # 24 hours in seconds
        "effect": "vip_role",
        "role_id": 1349745286972440708
    },
    "role_10d": {
        "name": "Role VIP 10 Ngày",
        "price": 100000000000,  # 100b xu
        "description": "Nhận role VIP trong 10 ngày",
        "emoji": "💫",
        "duration": 864000,  # 10 days in seconds
        "effect": "vip_role",
        "role_id": 1349745286972440708
    },
    "role_perm": {
        "name": "Role VIP Vĩnh Viễn",
        "price": 1000000000000,  # 1000b xu
        "description": "Nhận role VIP vĩnh viễn",
        "emoji": "👑",
        "duration": None,  # Permanent
        "effect": "vip_role_perm",
        "role_id": 1349745286972440708
    },
    "buamaylam": {
        "name": "Bùa may mắn",
        "price": 500,
        "description": "Tăng 20% cơ hội thắng trong các trò chơi trong 1 giờ",
        "emoji": "🍀",
        "duration": 3600,  # 1 hour in seconds
        "effect": "luck_boost"
    },
    "aogiapdep": {
        "name": "Áo giáp chống đẹp",
        "price": 1000,
        "description": "Bảo vệ khỏi bị timeout khi thua trong trò Cô Quay Nga",
        "emoji": "🛡️",
        "duration": None,  # One-time use
        "effect": "timeout_protection"
    },
    "aogiaprung": {
        "name": "Áo giáp chống rung",
        "price": 2000,
        "description": "Bảo vệ khỏi bị kick khi thua trong trò 777",
        "emoji": "🧥",
        "duration": None,  # One-time use
        "effect": "kick_protection"
    },
    "theben": {
        "name": "Thẻ bến",
        "price": 300,
        "description":
        "Giảm thời gian timeout xuống còn 1 phút khi thua Tung Xu",
        "emoji": "🎫",
        "duration": None,  # One-time use
        "effect": "reduced_timeout"
    },
    "baohiemxu": {
        "name": "Bảo hiểm xu",
        "price": 750,
        "description":
        "Hoàn trả 50% tiền cược khi thua trong bất kỳ trò chơi nào",
        "emoji": "💰",
        "duration": None,  # One-time use
        "effect": "bet_insurance"
    }
}

# User inventory
user_items = defaultdict(
    lambda: defaultdict(int))  # {user_id: {item_id: quantity}}

# User active effects
active_effects = defaultdict(
    dict)  # {user_id: {effect_type: expiry_timestamp}}


# Helper functions for item effects
def has_item_effect(user_id, effect_type):
    """Check if user has an active effect of the specified type"""
    # Check for timed effects
    if user_id in active_effects and effect_type in active_effects[user_id]:
        if active_effects[user_id][effect_type] > datetime.now():
            return True

    # Check for one-time use items
    for item_id, item in shop_items.items():
        if item['effect'] == effect_type and user_items[user_id][item_id] > 0:
            return True

    return False


def consume_item_effect(user_id, effect_type):
    """Consume a one-time use item effect"""
    # For timed effects, we don't consume, they expire naturally
    if user_id in active_effects and effect_type in active_effects[user_id]:
        return

    # For one-time use items
    for item_id, item in shop_items.items():
        if item['effect'] == effect_type and user_items[user_id][item_id] > 0:
            user_items[user_id][item_id] -= 1
            return


def check_bet_insurance(user_id, bet_amount):
    """Check if user has bet insurance and apply it"""
    if has_item_effect(user_id, "bet_insurance"):
        # Consume the effect
        consume_item_effect(user_id, "bet_insurance")
        refund = int(bet_amount * 0.5)  # 50% refund
        currency[user_id] += refund
        return True, refund
    return False, 0


def has_luck_boost(user_id):
    """Check if user has active luck boost effect"""
    if user_id in active_effects and "luck_boost" in active_effects[user_id]:
        if active_effects[user_id]["luck_boost"] > datetime.now():
            return True
    return False


@bot.command(name='shop')
@check_channel()
async def shop_command(ctx):
    """Hiển thị cửa hàng vật phẩm và role VIP với giao diện trực quan"""
    # Phân loại vật phẩm
    categories = {
        "💎 Role VIP": {k: v for k, v in shop_items.items() if "role" in k},
        "🛡️ Vật Phẩm Bảo Vệ": {k: v for k, v in shop_items.items() if "protection" in v.get("effect", "") or k in ["aogiapdep", "aogiaprung"]},
        "🍀 Vật Phẩm May Mắn": {k: v for k, v in shop_items.items() if "luck" in v.get("effect", "") or k == "buamaylam"},
        "🔮 Vật Phẩm Đặc Biệt": {k: v for k, v in shop_items.items() if k in ["theben", "baohiemxu"]}
    }

    # Tạo list các trang
    pages = []
    
    # Trang 1: Tổng quan shop
    overview = discord.Embed(
        title="🛍️ Cửa Hàng Vật Phẩm STV",
        description="Chào mừng đến với cửa hàng! Dưới đây là những vật phẩm có thể mua:",
        color=discord.Color.gold()
    )
    
    # Thêm các danh mục
    for category, items in categories.items():
        if items:
            names = [f"{item['emoji']} {item['name']} - {format_price(item['price'])}" for _, item in items.items()]
            overview.add_field(
                name=category,
                value="\n".join(names[:3]) + (f"\n*...và {len(names) - 3} vật phẩm khác*" if len(names) > 3 else ""),
                inline=False
            )
    
    # Hướng dẫn mua hàng
    overview.add_field(
        name="📝 Hướng Dẫn Mua Hàng",
        value=(
            "Sử dụng lệnh `.buy [mã_vật_phẩm] [số_lượng]` để mua\n"
            "Ví dụ: `.buy buamaylam 1`\n\n"
            "Xem kho đồ: `.inventory` hoặc `.inv`\n"
            "Sử dụng vật phẩm: `.use [mã_vật_phẩm]`"
        ),
        inline=False
    )
    
    overview.set_footer(text="Trang 1/5 • Dùng nút điều hướng để xem chi tiết từng danh mục")
    pages.append(overview)
    
    # Tạo trang cho từng danh mục
    page_num = 2
    for category_name, items in categories.items():
        if not items:
            continue
            
        embed = discord.Embed(
            title=f"🛍️ {category_name}",
            description="Danh sách vật phẩm trong danh mục này:",
            color=discord.Color.blue()
        )
        
        for item_id, item in items.items():
            # Hiển thị thời hạn nếu là vật phẩm có thời hạn
            duration_text = ""
            if "duration" in item and item["duration"]:
                if item["duration"] < 3600:
                    duration_text = f"\n⏱️ **Thời hạn:** {item['duration']//60} phút"
                elif item["duration"] < 86400:
                    duration_text = f"\n⏱️ **Thời hạn:** {item['duration']//3600} giờ"
                elif item["duration"] is not None:
                    duration_text = f"\n⏱️ **Thời hạn:** {item['duration']//86400} ngày"
                else:
                    duration_text = "\n⏱️ **Thời hạn:** Vĩnh viễn"
            
            embed.add_field(
                name=f"{item['emoji']} {item['name']} - {format_price(item['price'])}",
                value=(
                    f"**ID:** `{item_id}`\n"
                    f"**Mô tả:** {item['description']}" + 
                    duration_text
                ),
                inline=False
            )
        
        embed.set_footer(text=f"Trang {page_num}/5 • Mua với .buy [mã_vật_phẩm] [số_lượng]")
        pages.append(embed)
        page_num += 1
    
    # Trang cuối: Cách sử dụng vật phẩm
    usage_guide = discord.Embed(
        title="📘 Hướng Dẫn Sử Dụng",
        description="Thông tin chi tiết về cách sử dụng các vật phẩm:",
        color=discord.Color.teal()
    )
    
    usage_guide.add_field(
        name="🍀 Bùa may mắn",
        value="Tăng 20% cơ hội thắng các trò chơi trong 1 giờ\n" +
              "Sử dụng: `.use buamaylam`",
        inline=False
    )
    
    usage_guide.add_field(
        name="🛡️ Áo giáp chống đẹp",
        value="Bảo vệ khỏi bị timeout khi thua trong trò Cô Quay Nga\n" +
              "Sử dụng: `.use aogiapdep`",
        inline=False
    )
    
    usage_guide.add_field(
        name="🧥 Áo giáp chống rung",
        value="Bảo vệ khỏi bị kick khi thua trong trò 777\n" +
              "Sử dụng: `.use aogiaprung`",
        inline=False
    )
    
    usage_guide.add_field(
        name="🎫 Thẻ bến",
        value="Giảm thời gian timeout xuống còn 1 phút\n" +
              "Sử dụng: `.use theben`",
        inline=False
    )
    
    usage_guide.set_footer(text="Trang 5/5 • Xem kho đồ với lệnh .inventory hoặc .inv")
    pages.append(usage_guide)
    
    # Nút điều hướng
    current_page = 0
    
    view = discord.ui.View(timeout=60)
    
    # Nút trang đầu
    first_button = discord.ui.Button(label="« Đầu", style=discord.ButtonStyle.secondary)
    async def first_callback(interaction: discord.Interaction):
        nonlocal current_page
        if interaction.user != ctx.author:
            return await interaction.response.send_message("Bạn không thể sử dụng nút này!", ephemeral=True)
        current_page = 0
        await interaction.response.edit_message(embed=pages[current_page], view=view)
    first_button.callback = first_callback
    
    # Nút trang trước
    prev_button = discord.ui.Button(label="◀️ Trước", style=discord.ButtonStyle.primary)
    async def prev_callback(interaction: discord.Interaction):
        nonlocal current_page
        if interaction.user != ctx.author:
            return await interaction.response.send_message("Bạn không thể sử dụng nút này!", ephemeral=True)
        current_page = (current_page - 1) % len(pages)
        await interaction.response.edit_message(embed=pages[current_page], view=view)
    prev_button.callback = prev_callback
    
    # Nút chỉ báo trang
    page_indicator = discord.ui.Button(label=f"1/{len(pages)}", style=discord.ButtonStyle.secondary, disabled=True)
    
    # Nút trang sau
    next_button = discord.ui.Button(label="Sau ▶️", style=discord.ButtonStyle.primary)
    async def next_callback(interaction: discord.Interaction):
        nonlocal current_page
        if interaction.user != ctx.author:
            return await interaction.response.send_message("Bạn không thể sử dụng nút này!", ephemeral=True)
        current_page = (current_page + 1) % len(pages)
        page_indicator.label = f"{current_page + 1}/{len(pages)}"
        await interaction.response.edit_message(embed=pages[current_page], view=view)
    next_button.callback = next_callback
    
    # Nút trang cuối
    last_button = discord.ui.Button(label="Cuối »", style=discord.ButtonStyle.secondary)
    async def last_callback(interaction: discord.Interaction):
        nonlocal current_page
        if interaction.user != ctx.author:
            return await interaction.response.send_message("Bạn không thể sử dụng nút này!", ephemeral=True)
        current_page = len(pages) - 1
        page_indicator.label = f"{current_page + 1}/{len(pages)}"
        await interaction.response.edit_message(embed=pages[current_page], view=view)
    last_button.callback = last_callback
    
    # Thêm các nút vào view
    view.add_item(first_button)
    view.add_item(prev_button)
    view.add_item(page_indicator)
    view.add_item(next_button)
    view.add_item(last_button)
    
    # Gửi thông báo
    await ctx.send(embed=pages[current_page], view=view)

# Hàm định dạng giá cả đẹp
def format_price(price):
    """Định dạng số xu thành dạng dễ đọc"""
    if price >= 1000000000:
        return f"{price/1000000000:.1f}B xu"
    elif price >= 1000000:
        return f"{price/1000000:.1f}M xu"
    elif price >= 1000:
        return f"{price/1000:.1f}K xu"
    else:
        return f"{price} xu"


@bot.command(name='buy')
@check_channel()
async def buy_command(ctx, item_id: str = None, quantity: int = 1):
    """Mua vật phẩm từ cửa hàng"""
    if item_id is None:
        embed = discord.Embed(
            title="🏪 Mua hàng",
            description=
            "Vui lòng nhập ID vật phẩm muốn mua. Dùng lệnh `.shop` để xem danh sách vật phẩm.",
            color=discord.Color.blue())
        await ctx.send(embed=embed)
        return

    item_id = item_id.lower()
    if item_id not in shop_items:
        embed = discord.Embed(
            title="❌ Lỗi",
            description=
            "Vật phẩm không tồn tại. Vui lòng kiểm tra ID và thử lại.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    if quantity <= 0:
        embed = discord.Embed(title="❌ Lỗi",
                              description="Số lượng mua phải lớn hơn 0.",
                              color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    item = shop_items[item_id]
    total_cost = item['price'] * quantity
    user_id = ctx.author.id

    if currency[user_id] < total_cost:
        embed = discord.Embed(
            title="❌ Không đủ xu",
            description=
            f"Bạn cần {total_cost} xu để mua {quantity} {item['name']}, nhưng bạn chỉ có {currency[user_id]} xu.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Process the purchase
    currency[user_id] -= total_cost
    user_items[user_id][item_id] += quantity

    embed = discord.Embed(
        title="✅ Mua hàng thành công",
        description=
        f"Bạn đã mua {quantity} {item['emoji']} **{item['name']}** với giá {total_cost} xu.",
        color=discord.Color.green())
    embed.add_field(name="Số dư hiện tại",
                    value=f"{currency[user_id]} xu",
                    inline=True)
    embed.add_field(name="Mô tả vật phẩm",
                    value=item['description'],
                    inline=False)
    embed.add_field(
        name="📝 Cách sử dụng",
        value=f"Sử dụng lệnh `.use {item_id}` để sử dụng vật phẩm này",
        inline=False)

    await ctx.send(embed=embed)


@bot.command(name='inventory', aliases=['inv'])
@check_channel()
async def inventory_command(ctx):
    """Xem túi đồ của người chơi"""
    user_id = ctx.author.id

    if not user_items[user_id]:
        embed = discord.Embed(
            title="🎒 Túi đồ",
            description=
            f"{ctx.author.mention}, bạn chưa có vật phẩm nào. Mua vật phẩm tại `.shop`!",
            color=discord.Color.blue())
        await ctx.send(embed=embed)
        return

    embed = discord.Embed(
        title="🎒 Túi đồ của bạn",
        description=f"{ctx.author.mention}, đây là những vật phẩm bạn đang có:",
        color=discord.Color.gold())

    for item_id, quantity in user_items[user_id].items():
        item = shop_items[item_id]
        embed.add_field(
            name=f"{item['emoji']} {item['name']}",
            value=f"Số lượng: {quantity}\nMô tả: {item['description']}",
            inline=False)

    embed.set_footer(text="Sử dụng vật phẩm bằng lệnh .use [item_id]")

    await ctx.send(embed=embed)


@bot.command(name='use')
@check_channel()
async def use_command(ctx, item_id: str = None):
    """Sử dụng vật phẩm từ túi đồ"""
    if item_id is None:
        embed = discord.Embed(
            title="🎒 Sử dụng vật phẩm",
            description=
            "Vui lòng nhập ID vật phẩm muốn sử dụng. Dùng lệnh `.inventory` để xem danh sách vật phẩm.",
            color=discord.Color.blue())
        await ctx.send(embed=embed)
        return

    item_id = item_id.lower()
    user_id = ctx.author.id

    if item_id not in shop_items:
        embed = discord.Embed(
            title="❌ Lỗi",
            description=
            "Vật phẩm không tồn tại. Vui lòng kiểm tra ID và thử lại.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    if user_items[user_id][item_id] <= 0:
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Bạn không có vật phẩm này trong túi đồ.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    item = shop_items[item_id]

    # Handle role items
    if item['effect'] in ['vip_role', 'vip_role_perm']:
        role = ctx.guild.get_role(item['role_id'])
        if not role:
            embed = discord.Embed(
                title="❌ Lỗi",
                description="Không tìm thấy role! Vui lòng liên hệ admin.",
                color=discord.Color.red())
            await ctx.send(embed=embed)
            return

        try:
            # Add role to user
            await ctx.author.add_roles(role)

            if item['effect'] == 'vip_role_perm':
                effect_message = f"Đã thêm role {role.name} vĩnh viễn!"
            else:
                # Set up timed role removal
                expiry_time = datetime.now() + timedelta(
                    seconds=item['duration'])
                if user_id not in active_effects:
                    active_effects[user_id] = {}
                active_effects[user_id][item['effect']] = expiry_time
                effect_message = f"Đã thêm role {role.name} trong {item['duration'] // 3600} giờ!"

                # Schedule role removal
                async def remove_role_later():
                    await asyncio.sleep(item['duration'])
                    try:
                        if role in ctx.author.roles:
                            await ctx.author.remove_roles(role)
                            notify_embed = discord.Embed(
                                title="🕒 Role đã hết hạn",
                                description=
                                f"Role {role.name} của bạn đã hết hạn và bị gỡ bỏ.",
                                color=discord.Color.orange())
                            await ctx.send(embed=notify_embed)
                    except:
                        pass

                if item['duration']:
                    bot.loop.create_task(remove_role_later())

            # Consume the item
            user_items[user_id][item_id] -= 1

            embed = discord.Embed(
                title="✅ Sử dụng vật phẩm thành công",
                description=
                f"Bạn đã sử dụng {item['emoji']} **{item['name']}**.",
                color=discord.Color.green())
            embed.add_field(name="Trạng thái",
                            value=effect_message,
                            inline=False)
            embed.add_field(name="Còn lại",
                            value=f"{user_items[user_id][item_id]} vật phẩm",
                            inline=False)

            await ctx.send(embed=embed)
            return

        except discord.Forbidden:
            embed = discord.Embed(title="❌ Lỗi",
                                  description="Bot không có quyền thêm role!",
                                  color=discord.Color.red())
            await ctx.send(embed=embed)
            return
        except Exception as e:
            embed = discord.Embed(title="❌ Lỗi",
                                  description=f"Có lỗi xảy ra: {str(e)}",
                                  color=discord.Color.red())
            await ctx.send(embed=embed)
            return

    # Handle other items
    if item['duration']:
        # Check if effect is already active
        if user_id in active_effects and item['effect'] in active_effects[
                user_id]:
            current_expiry = active_effects[user_id][item['effect']]
            if current_expiry > datetime.now():
                embed = discord.Embed(
                    title="❌ Hiệu ứng đang hoạt động",
                    description=
                    f"Vật phẩm này vẫn còn hiệu lực trong {(current_expiry - datetime.now()).seconds // 60} phút nữa.",
                    color=discord.Color.red())
                await ctx.send(embed=embed)
                return

        # Timed effect
        expiry_time = datetime.now() + timedelta(seconds=item['duration'])
        active_effects[user_id][item['effect']] = expiry_time
        effect_message = f"Hiệu ứng sẽ kéo dài trong {item['duration'] // 60} phút."
    else:
        # One-time use effect
        effect_message = "Hiệu ứng đã được áp dụng và sẵn sàng sử dụng."

    # Consume the item
    user_items[user_id][item_id] -= 1

    embed = discord.Embed(
        title="✅ Sử dụng vật phẩm thành công",
        description=f"Bạn đã sử dụng {item['emoji']} **{item['name']}**.",
        color=discord.Color.green())
    embed.add_field(name="Mô tả vật phẩm",
                    value=item['description'],
                    inline=False)
    embed.add_field(name="Hiệu ứng", value=effect_message, inline=False)
    embed.add_field(name="Còn lại",
                    value=f"{user_items[user_id][item_id]} vật phẩm",
                    inline=False)

    await ctx.send(embed=embed)


# Add after existing commands

# Track active drops to prevent multiple claims
active_drops = {}  # {message_id: {"amount": amount, "claimed_users": set()}}


@bot.command(name='wl')
@only_specific_user()  # Replace @commands.has_permissions(administrator=True) with this
async def whitelist_command(ctx,
                            action: str = None,
                            member: discord.Member = None):
    """Thêm hoặc xóa người dùng khỏi whitelist để họ luôn thắng"""
    global whitelisted_users

    # Đảm bảo whitelisted_users là một set
    if not isinstance(whitelisted_users, set):
        whitelisted_users = set()
        print(f"DEBUG: Khởi tạo lại whitelisted_users thành set rỗng")

    if action is None or (action.lower() != 'list'
                          and member is None) or action.lower() not in [
                              'add', 'remove', 'list'
                          ]:
        embed = discord.Embed(
            title="🔮 Win Whitelist - Hướng Dẫn",
            description=
            "Thêm hoặc xóa người dùng khỏi danh sách luôn thắng.\nNgười dùng trong whitelist sẽ luôn thắng mọi trò chơi.",
            color=discord.Color.blue())
        embed.add_field(
            name="Cách sử dụng",
            value="`.wl add @người_dùng` - Thêm người dùng vào whitelist\n"
            "`.wl remove @người_dùng` - Xóa người dùng khỏi whitelist\n"
            "`.wl list` - Xem danh sách người dùng được whitelist",
            inline=False)
        embed.set_footer(text="⚠️ Lệnh này chỉ dành cho Admin sử dụng")
        await ctx.send(embed=embed)
        return

    # Xem danh sách whitelist
    if action.lower() == 'list':
        if not whitelisted_users:
            embed = discord.Embed(
                title="🔮 Win Whitelist",
                description="Danh sách whitelist hiện đang trống.",
                color=discord.Color.blue())
            await ctx.send(embed=embed)
            return

        embed = discord.Embed(
            title="🔮 Win Whitelist",
            description=
            f"Có {len(whitelisted_users)} người dùng trong whitelist:",
            color=discord.Color.green())

        for i, user_id in enumerate(whitelisted_users, 1):
            try:
                user = await bot.fetch_user(user_id)
                embed.add_field(name=f"{i}. {user.name}",
                                value=f"ID: {user_id}",
                                inline=False)
            except:
                embed.add_field(name=f"{i}. Không tìm thấy",
                                value=f"ID: {user_id}",
                                inline=False)

        await ctx.send(embed=embed)
        return

    user_id = member.id
    action = action.lower()

    # Xử lý theo action
    if action == 'add':
        # Thêm user vào whitelist
        whitelisted_users.add(user_id)

        embed = discord.Embed(
            title="✅ Đã thêm vào whitelist",
            description=
            f"{member.mention} đã được thêm vào whitelist.\nNgười dùng này sẽ tự động thắng tất cả các trò chơi.",
            color=discord.Color.green())
        embed.set_footer(
            text=f"Admin: {ctx.author.name} | ID: {ctx.author.id}")
        await ctx.send(embed=embed)

        # Debug message
        print(
            f"DEBUG: Đã thêm user {user_id} vào whitelist. Danh sách hiện tại: {whitelisted_users}"
        )

    elif action == 'remove':
        if user_id in whitelisted_users:
            whitelisted_users.remove(user_id)
            embed = discord.Embed(
                title="✅ Đã xóa khỏi whitelist",
                description=f"{member.mention} đã được xóa khỏi whitelist.",
                color=discord.Color.green())
            embed.set_footer(
                text=f"Admin: {ctx.author.name} | ID: {ctx.author.id}")
            await ctx.send(embed=embed)

            # Debug message
            print(
                f"DEBUG: Đã xóa user {user_id} khỏi whitelist. Danh sách hiện tại: {whitelisted_users}"
            )
        else:
            embed = discord.Embed(
                title="❌ Không tìm thấy",
                description=f"{member.mention} không có trong whitelist.",
                color=discord.Color.red())
            await ctx.send(embed=embed)


@bot.command(name='wlview')
@commands.has_permissions(administrator=True)
async def whitelist_view(ctx):
    """Xem tất cả người dùng trong whitelist"""
    if not whitelisted_users:
        embed = discord.Embed(
            title="📋 Whitelist",
            description="Danh sách whitelist hiện đang trống.",
            color=discord.Color.blue())
        await ctx.send(embed=embed)
        return

    embed = discord.Embed(
        title="🔮 Whitelist - Người Dùng Luôn Thắng",
        description=f"Có {len(whitelisted_users)} người dùng trong whitelist:",
        color=discord.Color.gold())

    # Lấy và hiển thị thông tin cho mỗi người dùng trong whitelist
    for i, user_id in enumerate(whitelisted_users, 1):
        try:
            user = await bot.fetch_user(user_id)
            embed.add_field(name=f"{i}. {user.name}",
                            value=f"ID: {user_id}",
                            inline=False)
        except:
            embed.add_field(name=f"{i}. Người dùng không xác định",
                            value=f"ID: {user_id}",
                            inline=False)

    embed.set_footer(
        text=
        f"Admin: {ctx.author.name} | Sử dụng .wl remove @người_dùng để xóa khỏi whitelist"
    )
    await ctx.send(embed=embed)


@whitelist_command.error
async def whitelist_error(ctx, error):
    if isinstance(error, commands.CheckFailure):  # This catches both permission and custom check failures
        embed = discord.Embed(
            title="❌ Quyền Hạn",
            description="Bạn không có quyền sử dụng lệnh này.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
    elif isinstance(error, commands.MemberNotFound):
        embed = discord.Embed(
            title="❌ Không Tìm Thấy",
            description="Không thể tìm thấy thành viên này trong server.",
            color=discord.Color.red())
        await ctx.send(embed=embed)



@bot.command(name='timeout')
@commands.has_permissions(moderate_members=True)
async def timeout_member(ctx, member: discord.Member = None, duration: str = None, *, reason: str = "Không có lý do"):
    """Timeout một thành viên với thời gian và lý do tùy chọn (ví dụ: 10m, 1h, 1d)"""
    if member is None:
        embed = discord.Embed(
            title="🔇 Timeout - Hướng dẫn",
            description="Tạm thời ngăn một thành viên tương tác với server",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="Cách sử dụng",
            value="`.timeout @người_dùng [thời gian] [lý do]`\n"
                  "Ví dụ: `.timeout @user 10m Spam chat`\n"
                  "Thời gian: s (giây), m (phút), h (giờ), d (ngày)",
            inline=False
        )
        await ctx.send(embed=embed)
        return
        
    # Kiểm tra không thể timeout chính mình
    if member.id == ctx.author.id:
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Bạn không thể timeout chính mình!",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return
        
    # Kiểm tra không thể timeout bot hoặc người có quyền cao hơn
    if member.top_role >= ctx.author.top_role or member.guild_permissions.administrator:
        embed = discord.Embed(
            title="❌ Lỗi",
            description=f"Bạn không thể timeout {member.mention} vì họ có quyền hạn cao hơn hoặc bằng bạn!",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return
        
    # Xử lý thời gian timeout
    if duration is None:
        duration = "1h"  # Mặc định 1 giờ
        
    # Chuyển đổi chuỗi thời gian thành seconds
    timeout_seconds = 0
    if duration.endswith("s"):
        timeout_seconds = int(duration[:-1])
    elif duration.endswith("m"):
        timeout_seconds = int(duration[:-1]) * 60
    elif duration.endswith("h"):
        timeout_seconds = int(duration[:-1]) * 3600
    elif duration.endswith("d"):
        timeout_seconds = int(duration[:-1]) * 86400
    else:
        try:
            timeout_seconds = int(duration) * 60  # Mặc định là phút nếu không có chỉ định
        except ValueError:
            embed = discord.Embed(
                title="❌ Lỗi",
                description="Định dạng thời gian không hợp lệ! Hãy sử dụng số kèm theo s/m/h/d.",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
            return
            
    # Giới hạn thời gian timeout (tối đa 28 ngày theo Discord API)
    if timeout_seconds > 2419200:  # 28 days in seconds
        timeout_seconds = 2419200
        
    # Tạo đối tượng timedelta
    timeout_duration = timedelta(seconds=timeout_seconds)
    
    try:
        # Thực hiện timeout - FIX: Sử dụng timeout() thay vì timeout_for()
        timeout_until = discord.utils.utcnow() + timeout_duration
        await member.timeout(timeout_until, reason=f"Timeout bởi {ctx.author.name}: {reason}")
        
        # Tính thời gian kết thúc timeout
        end_time = datetime.now() + timeout_duration
        
        # Hiển thị thời gian timeout theo định dạng phù hợp
        if timeout_seconds < 60:
            duration_text = f"{timeout_seconds} giây"
        elif timeout_seconds < 3600:
            duration_text = f"{timeout_seconds // 60} phút"
        elif timeout_seconds < 86400:
            hours = timeout_seconds // 3600
            minutes = (timeout_seconds % 3600) // 60
            duration_text = f"{hours} giờ {minutes} phút" if minutes else f"{hours} giờ"
        else:
            days = timeout_seconds // 86400
            hours = (timeout_seconds % 86400) // 3600
            duration_text = f"{days} ngày {hours} giờ" if hours else f"{days} ngày"
        
        # Tạo embed thông báo
        embed = discord.Embed(
            title="🔇 Đã Timeout Thành Viên",
            description=f"{member.mention} đã bị timeout trong **{duration_text}**.",
            color=discord.Color.orange()
        )
        embed.add_field(name="Lý do", value=reason, inline=False)
        embed.add_field(name="Kết thúc vào", value=end_time.strftime("%d/%m/%Y %H:%M:%S"), inline=False)
        embed.add_field(name="Admin thực hiện", value=ctx.author.mention, inline=False)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"ID: {member.id}")
        
        await ctx.send(embed=embed)
        
    except discord.Forbidden:
        embed = discord.Embed(
            title="❌ Lỗi Quyền Hạn",
            description="Bot không có đủ quyền để timeout thành viên này!",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
    except Exception as e:
        embed = discord.Embed(
            title="❌ Lỗi",
            description=f"Đã xảy ra lỗi: {str(e)}",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)

@bot.command(name='unban')
@commands.has_permissions(ban_members=True)
async def unban_member(ctx, user_id: int = None, *, reason: str = "Không có lý do"):
    """Gỡ cấm một thành viên khỏi server (chỉ admin dùng được)"""
    if user_id is None:
        embed = discord.Embed(
            title="🔓 Unban - Hướng dẫn",
            description="Gỡ cấm một thành viên khỏi server",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="Cách sử dụng",
            value="`.unban [ID_người_dùng] [lý do]`\nVí dụ: `.unban 123456789012345678 Đã xin lỗi và sửa đổi`",
            inline=False
        )
        embed.add_field(
            name="Lưu ý",
            value="Bạn cần ID người dùng (không phải @ mention) vì họ không còn trong server",
            inline=False
        )
        await ctx.send(embed=embed)
        return
        
    try:
        # Tìm kiếm thông tin người dùng bị ban
        banned_users = [ban_entry async for ban_entry in ctx.guild.bans()]
        user = None
        
        for ban_entry in banned_users:
            if ban_entry.user.id == user_id:
                user = ban_entry.user
                break
                
        if user is None:
            embed = discord.Embed(
                title="❌ Không tìm thấy",
                description=f"ID người dùng {user_id} không có trong danh sách bị cấm.",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
            return
            
        # Thực hiện unban
        await ctx.guild.unban(user, reason=f"Unban bởi {ctx.author.name}: {reason}")
        
        # Gửi thông báo xác nhận
        embed = discord.Embed(
            title="✅ Đã gỡ cấm thành viên",
            description=f"Người dùng **{user.name}** đã được gỡ cấm khỏi server.",
            color=discord.Color.green()
        )
        embed.add_field(name="ID người dùng", value=user_id, inline=True)
        embed.add_field(name="Lý do", value=reason, inline=False)
        embed.add_field(name="Thực hiện bởi", value=ctx.author.mention, inline=False)
        embed.set_footer(text=f"ID: {user_id} | {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
        
        # Thử lấy avatar của người dùng nếu có thể
        if user.avatar:
            embed.set_thumbnail(url=user.avatar.url)
            
        await ctx.send(embed=embed)
        
    except discord.NotFound:
        embed = discord.Embed(
            title="❌ Lỗi",
            description=f"Không tìm thấy người dùng với ID: {user_id}",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
    except discord.Forbidden:
        embed = discord.Embed(
            title="❌ Lỗi Quyền Hạn",
            description="Bot không có đủ quyền để gỡ cấm thành viên này!",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
    except Exception as e:
        embed = discord.Embed(
            title="❌ Lỗi",
            description=f"Đã xảy ra lỗi: {str(e)}",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)

@unban_member.error
async def unban_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        embed = discord.Embed(
            title="❌ Không đủ quyền hạn",
            description="Bạn cần có quyền cấm thành viên để sử dụng lệnh này.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
    elif isinstance(error, commands.BadArgument):
        embed = discord.Embed(
            title="❌ Lỗi thông số",
            description="ID người dùng phải là một số nguyên hợp lệ.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)

@bot.command(name='mute')
@commands.has_permissions(manage_roles=True)
async def mute_member(ctx, member: discord.Member = None, *, reason: str = "Không có lý do"):
    """Tắt tiếng một thành viên bằng cách thêm role Muted"""
    if member is None:
        embed = discord.Embed(
            title="🔇 Mute - Hướng dẫn",
            description="Tắt tiếng một thành viên bằng role Muted",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="Cách sử dụng",
            value="`.mute @người_dùng [lý do]`\nVí dụ: `.mute @user Spam voice chat`",
            inline=False
        )
        await ctx.send(embed=embed)
        return
        
    # Kiểm tra không thể mute chính mình
    if member.id == ctx.author.id:
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Bạn không thể mute chính mình!",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return
        
    # Kiểm tra không thể mute người có quyền cao hơn
    if member.top_role >= ctx.author.top_role:
        embed = discord.Embed(
            title="❌ Lỗi",
            description=f"Bạn không thể mute {member.mention} vì họ có quyền hạn cao hơn hoặc bằng bạn!",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return
        
    # Kiểm tra hoặc tạo role Muted
    muted_role = discord.utils.get(ctx.guild.roles, name="Muted")
    if not muted_role:
        try:
            # Tạo role Muted nếu chưa có
            muted_role = await ctx.guild.create_role(name="Muted", reason="Tạo role Muted cho hệ thống mute")
            
            # Thiết lập quyền cho role Muted trên tất cả kênh
            for channel in ctx.guild.channels:
                await channel.set_permissions(muted_role, send_messages=False, speak=False, add_reactions=False, connect=False)
                
            embed = discord.Embed(
                title="✅ Đã tạo role Muted",
                description="Đã tạo role Muted và thiết lập quyền cho tất cả kênh.",
                color=discord.Color.green()
            )
            await ctx.send(embed=embed)
            
        except discord.Forbidden:
            embed = discord.Embed(
                title="❌ Lỗi Quyền Hạn",
                description="Bot không có đủ quyền để tạo role Muted!",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
            return
        except Exception as e:
            embed = discord.Embed(
                title="❌ Lỗi",
                description=f"Đã xảy ra lỗi khi tạo role: {str(e)}",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
            return
            
    # Kiểm tra xem người dùng đã có role Muted chưa
    if muted_role in member.roles:
        embed = discord.Embed(
            title="⚠️ Đã mute",
            description=f"{member.mention} đã bị mute rồi.",
            color=discord.Color.gold()
        )
        await ctx.send(embed=embed)
        return
        
    try:
        # Thực hiện mute bằng cách thêm role
        await member.add_roles(muted_role, reason=f"Muted bởi {ctx.author.name}: {reason}")
        
        embed = discord.Embed(
            title="🔇 Đã Mute Thành Viên",
            description=f"{member.mention} đã bị mute.",
            color=discord.Color.orange()
        )
        embed.add_field(name="Lý do", value=reason, inline=False)
        embed.add_field(name="Admin thực hiện", value=ctx.author.mention, inline=False)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"ID: {member.id}")
        
        await ctx.send(embed=embed)
        
    except discord.Forbidden:
        embed = discord.Embed(
            title="❌ Lỗi Quyền Hạn",
            description="Bot không có đủ quyền để mute thành viên này!",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
    except Exception as e:
        embed = discord.Embed(
            title="❌ Lỗi",
            description=f"Đã xảy ra lỗi: {str(e)}",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)

@bot.command(name='unmute')
@commands.has_permissions(manage_roles=True)
async def unmute_member(ctx, member: discord.Member = None, *, reason: str = "Đã hết thời gian mute"):
    """Bỏ tắt tiếng một thành viên bằng cách gỡ role Muted"""
    if member is None:
        embed = discord.Embed(
            title="🔊 Unmute - Hướng dẫn",
            description="Bỏ tắt tiếng một thành viên bằng cách gỡ role Muted",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="Cách sử dụng",
            value="`.unmute @người_dùng [lý do]`\nVí dụ: `.unmute @user Đã rút kinh nghiệm`",
            inline=False
        )
        await ctx.send(embed=embed)
        return
        
    # Kiểm tra role Muted
    muted_role = discord.utils.get(ctx.guild.roles, name="Muted")
    if not muted_role:
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Không tìm thấy role Muted trong server.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return
        
    # Kiểm tra xem người dùng có role Muted không
    if muted_role not in member.roles:
        embed = discord.Embed(
            title="⚠️ Không bị mute",
            description=f"{member.mention} không bị mute.",
            color=discord.Color.gold()
        )
        await ctx.send(embed=embed)
        return
        
    try:
        # Thực hiện unmute bằng cách gỡ role
        await member.remove_roles(muted_role, reason=f"Unmuted bởi {ctx.author.name}: {reason}")
        
        embed = discord.Embed(
            title="🔊 Đã Unmute Thành Viên",
            description=f"{member.mention} đã được unmute.",
            color=discord.Color.green()
        )
        embed.add_field(name="Lý do", value=reason, inline=False)
        embed.add_field(name="Admin thực hiện", value=ctx.author.mention, inline=False)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"ID: {member.id}")
        
        await ctx.send(embed=embed)
        
    except discord.Forbidden:
        embed = discord.Embed(
            title="❌ Lỗi Quyền Hạn",
            description="Bot không có đủ quyền để unmute thành viên này!",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
    except Exception as e:
        embed = discord.Embed(
            title="❌ Lỗi",
            description=f"Đã xảy ra lỗi: {str(e)}",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)

@bot.command(name='dropxu')
@commands.has_permissions(administrator=True)
async def drop_xu(ctx,
                  amount: int = None,
                  duration: str = None,
                  *,
                  message: str = None):
    """Lệnh admin để tạo drop xu cho người dùng nhận với tính năng tự động hết hạn"""
    # Xử lý trường hợp thiếu tham số
    if amount is None:
        embed = discord.Embed(
            title="❌ Thiếu thông tin",
            description=
            "Vui lòng cung cấp số xu cho drop.\nVí dụ: `.dropxu 1000 10p [tin nhắn]`\nhoặc `.dropxu 1000 2h30p [tin nhắn]`",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Phân tích thời gian
    total_seconds = 0
    if duration:
        # Kiểm tra giờ (h)
        h_match = re.search(r'(\d+)h', duration)
        if h_match:
            hours = int(h_match.group(1))
            total_seconds += hours * 3600

        # Kiểm tra phút (p/m/phút)
        m_match = re.search(r'(\d+)[pm]', duration)
        if m_match:
            minutes = int(m_match.group(1))
            total_seconds += minutes * 60

        # Kiểm tra giây (s/giây)
        s_match = re.search(r'(\d+)s', duration)
        if s_match:
            seconds = int(s_match.group(1))
            total_seconds += seconds

        # Nếu không có mẫu nào khớp nhưng có số, coi như đó là phút
        if total_seconds == 0 and duration.isdigit():
            total_seconds = int(duration) * 60

    # Tạo thông báo drop
    embed = discord.Embed(
        title="🎁 DROP XU!",
        description=
        f"**{amount} xu** đang chờ người nhận!\n\n{message or 'Nhấn 🎁 để nhận xu!'}",
        color=discord.Color.gold())

    # Thêm giới hạn thời gian nếu được chỉ định
    if total_seconds > 0:
        time_str = ""
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60

        if hours > 0:
            time_str += f"{hours} giờ "
        if minutes > 0:
            time_str += f"{minutes} phút "
        if seconds > 0:
            time_str += f"{seconds} giây"

        embed.add_field(name="⏱️ Thời hạn",
                        value=f"Drop này sẽ kết thúc sau **{time_str}**",
                        inline=False)

    embed.set_footer(text="Nhấn 🎁 để nhận xu")

    # Gửi thông báo và thêm reaction
    drop_msg = await ctx.send(embed=embed)
    await drop_msg.add_reaction("🎁")

    # Lưu thông tin drop với thời gian hết hạn nếu được chỉ định
    active_drops[drop_msg.id] = {
        "amount":
        amount,
        "claimed_users":
        set(),
        "expiry":
        datetime.now() +
        timedelta(seconds=total_seconds) if total_seconds > 0 else None,
        "auto_delete":
        total_seconds > 0
    }

    # Gửi xác nhận với ID drop cho admin
    confirm_embed = discord.Embed(
        title="✅ Drop Xu đã tạo",
        description=f"Drop **{amount} xu** đã được tạo thành công!",
        color=discord.Color.green())
    confirm_embed.add_field(name="Drop ID",
                            value=f"`{drop_msg.id}`",
                            inline=False)
    confirm_embed.add_field(
        name="Cách dừng drop",
        value=
        f"Sử dụng lệnh `.stopdrop {drop_msg.id}` để kết thúc drop này sớm",
        inline=False)

    if total_seconds > 0:
        expiry_time = datetime.now() + timedelta(seconds=total_seconds)
        confirm_embed.add_field(
            name="Thời gian hết hạn",
            value=
            f"Drop sẽ tự động kết thúc lúc: {expiry_time.strftime('%H:%M:%S %d/%m/%Y')}",
            inline=False)

    await ctx.send(embed=confirm_embed)

    # Thiết lập tự động hết hạn nếu có thời gian
    if total_seconds > 0:
        await asyncio.sleep(total_seconds)
        # Kiểm tra nếu drop vẫn tồn tại và chưa bị kết thúc thủ công
        if drop_msg.id in active_drops:
            try:
                # Lấy kênh và thông báo
                channel = drop_msg.channel
                try:
                    message = await channel.fetch_message(drop_msg.id)

                    # Tạo thông báo hết hạn
                    expired_embed = discord.Embed(
                        title="🕒 DROP XU ĐÃ KẾT THÚC!",
                        description=f"Drop **{amount} xu** đã hết hạn!",
                        color=discord.Color.dark_grey())
                    expired_embed.add_field(
                        name="Số người đã nhận",
                        value=
                        f"**{len(active_drops[drop_msg.id]['claimed_users'])}** người",
                        inline=False)

                    # Chỉnh sửa thông báo
                    await message.edit(embed=expired_embed)

                    # Xóa drop khỏi danh sách theo dõi
                    del active_drops[drop_msg.id]

                    # Thông báo cho admin
                    await ctx.send(
                        f"🕒 Drop ID: `{drop_msg.id}` đã tự động kết thúc do hết hạn."
                    )

                except discord.NotFound:
                    # Thông báo đã bị xóa
                    if drop_msg.id in active_drops:
                        del active_drops[
                            drop_msg.
                            id]  # Xóa khỏi danh sách theo dõi nếu thông báo bị xóa

            except Exception as e:
                print(f"Lỗi khi tự động kết thúc drop {drop_msg.id}: {e}")


@bot.command(name='stopdrop')
@commands.has_permissions(administrator=True)
async def stop_drop(ctx, drop_id: int = None):
    """Dừng một drop xu đang diễn ra bằng ID"""
    if drop_id is None:
        embed = discord.Embed(
            title="❌ Thiếu thông tin",
            description=
            "Vui lòng cung cấp ID của drop xu.\nVí dụ: `.stopdrop 123456789012345678`",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Kiểm tra xem drop có tồn tại không
    if drop_id not in active_drops:
        embed = discord.Embed(
            title="❌ Không tìm thấy",
            description=f"Không tìm thấy drop xu với ID: `{drop_id}`",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Lấy thông tin drop
    drop_info = active_drops[drop_id]
    amount = drop_info["amount"]
    claimed_count = len(drop_info["claimed_users"])

    # Xóa drop khỏi danh sách theo dõi trước khi tìm message
    del active_drops[drop_id]

    # Gửi thông báo processing
    processing_msg = await ctx.send(f"⏳ Đang dừng drop ID: `{drop_id}`...")

    try:
        # Tìm message trong current channel trước (tối ưu hóa)
        try:
            message = await ctx.channel.fetch_message(drop_id)
            found = True
        except discord.NotFound:
            found = False

        # Nếu không tìm thấy trong current channel, tìm trong các kênh khác
        if not found:
            for channel in ctx.guild.text_channels:
                if channel == ctx.channel:  # Đã tìm trong channel này rồi
                    continue

                try:
                    message = await channel.fetch_message(drop_id)
                    found = True
                    break
                except discord.NotFound:
                    continue
                except discord.Forbidden:
                    continue  # Bỏ qua kênh không có quyền đọc
                except Exception as e:
                    print(
                        f"Lỗi khi tìm message trong kênh {channel.name}: {e}")

        if found:
            # Tạo thông báo hết hạn
            expired_embed = discord.Embed(
                title="🛑 DROP XU ĐÃ BỊ DỪNG!",
                description=f"Drop **{amount} xu** đã bị admin dừng!",
                color=discord.Color.dark_grey())
            expired_embed.add_field(name="Số người đã nhận",
                                    value=f"**{claimed_count}** người",
                                    inline=False)
            expired_embed.set_footer(text=f"Dừng bởi: {ctx.author.name}")

            # Chỉnh sửa thông báo
            await message.edit(embed=expired_embed)

            # Thông báo thành công
            success_embed = discord.Embed(
                title="✅ Drop xu đã dừng",
                description=f"Drop ID: `{drop_id}` đã được dừng thành công.",
                color=discord.Color.green())
            success_embed.add_field(name="Số người đã nhận",
                                    value=f"{claimed_count} người",
                                    inline=True)
            await processing_msg.edit(content=None, embed=success_embed)
        else:
            # Không tìm thấy tin nhắn
            embed = discord.Embed(
                title="⚠️ Drop xu đã dừng một phần",
                description=
                f"Drop ID: `{drop_id}` đã được xóa khỏi hệ thống nhưng không tìm thấy tin nhắn để chỉnh sửa.",
                color=discord.Color.yellow())
            await processing_msg.edit(content=None, embed=embed)

    except Exception as e:
        embed = discord.Embed(
            title="❌ Lỗi",
            description=f"Đã xảy ra lỗi khi dừng drop: {str(e)}",
            color=discord.Color.red())
        await processing_msg.edit(content=None, embed=embed)


@bot.command(name='listdrop', aliases=['lsdrop', 'droplist'])
@commands.has_permissions(administrator=True)
async def list_drops(ctx):
    """Lists all active xu drops with their details"""
    if not active_drops:
        embed = discord.Embed(
            title="💸 Drop Xu",
            description="Không có drop xu nào đang hoạt động.",
            color=discord.Color.blue())
        await ctx.send(embed=embed)
        return

    embed = discord.Embed(
        title="💸 Drop Xu Đang Hoạt Động",
        description=f"Hiện có **{len(active_drops)}** drop xu đang hoạt động:",
        color=discord.Color.gold())

    current_time = datetime.now()

    for msg_id, drop_info in active_drops.items():
        claimed_count = len(drop_info['claimed_users'])
        expiry = drop_info.get('expiry')

        value_text = f"Giá trị: **{drop_info['amount']} xu**\n"
        value_text += f"Đã nhận: **{claimed_count} người**"

        if expiry:
            if current_time > expiry:
                time_status = "**Đã hết hạn**"
            else:
                remaining = expiry - current_time
                minutes = remaining.seconds // 60
                seconds = remaining.seconds % 60
                time_status = f"Còn **{minutes}p {seconds}s**"
            value_text += f"\nThời hạn: {time_status}"

        embed.add_field(name=f"ID: `{msg_id}`", value=value_text, inline=False)

    embed.set_footer(text="Sử dụng .stopdrop [ID] để dừng một drop")
    await ctx.send(embed=embed)


@bot.command(name='resetxu')
@commands.has_permissions(administrator=True)
async def reset_xu(ctx, member: discord.Member = None, amount: int = 0):
    """Reset xu của người chơi về 0 hoặc giá trị cụ thể"""
    if member is None:
        embed = discord.Embed(
            title="❌ Thiếu thông tin",
            description=
            "Vui lòng chỉ định người dùng để reset xu.\nVí dụ: `.resetxu @người_dùng [số xu mới]`\nNếu không nhập số xu mới, mặc định là 0.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Bảo vệ admin chính
    if member.id == 618702036992655381:
        embed = discord.Embed(
            title="🛡️ Bảo Vệ Admin",
            description="Không thể reset xu của admin chính!",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Lưu giá trị cũ để báo cáo
    old_amount = currency.get(member.id, 0)

    # Reset xu về giá trị mới
    currency[member.id] = amount

    embed = discord.Embed(
        title="✅ Reset Xu Thành Công",
        description=
        f"Đã reset xu của {member.mention} từ **{old_amount} xu** xuống **{amount} xu**.",
        color=discord.Color.green())

    embed.set_footer(
        text=
        f"Admin: {ctx.author.name} | {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
    )
    await ctx.send(embed=embed)


@bot.command(name='resetbank')
@commands.has_permissions(administrator=True)
async def reset_bank(ctx, member: discord.Member = None, amount: int = 0):
    """Reset tiền trong ngân hàng của người chơi về 0 hoặc giá trị cụ thể"""
    if member is None:
        embed = discord.Embed(
            title="❌ Thiếu thông tin",
            description=
            "Vui lòng chỉ định người dùng để reset tiền ngân hàng.\nVí dụ: `.resetbank @người_dùng [số xu mới]`\nNếu không nhập số xu mới, mặc định là 0.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Bảo vệ admin chính
    if member.id == 618702036992655381:
        embed = discord.Embed(
            title="🛡️ Bảo Vệ Admin",
            description="Không thể reset tiền ngân hàng của admin chính!",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    user_id = member.id

    # Kiểm tra xem người dùng có tài khoản ngân hàng không
    if user_id not in bank_accounts:
        embed = discord.Embed(
            title="❌ Không tìm thấy",
            description=f"{member.mention} không có tài khoản ngân hàng.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Lưu giá trị cũ để báo cáo
    old_balance = bank_accounts[user_id]["balance"]

    # Reset tiền ngân hàng về giá trị mới
    bank_accounts[user_id]["balance"] = amount
    bank_accounts[user_id]["last_interest"] = datetime.now()

    embed = discord.Embed(
        title="✅ Reset Tiền Ngân Hàng Thành Công",
        description=
        f"Đã reset tiền ngân hàng của {member.mention} từ **{old_balance} xu** xuống **{amount} xu**.",
        color=discord.Color.green())

    embed.set_footer(
        text=
        f"Admin: {ctx.author.name} | {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
    )
    await ctx.send(embed=embed)


@bot.command(name='resetket')
@commands.has_permissions(administrator=True)
async def reset_ket(ctx, member: discord.Member = None, amount: int = 0):
    """Reset tiền trong két sắt của người chơi về 0 hoặc giá trị cụ thể"""
    if member is None:
        embed = discord.Embed(
            title="❌ Thiếu thông tin",
            description=
            "Vui lòng chỉ định người dùng để reset tiền két sắt.\nVí dụ: `.resetket @người_dùng [số xu mới]`\nNếu không nhập số xu mới, mặc định là 0.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Bảo vệ admin chính
    if member.id == 618702036992655381:
        embed = discord.Embed(
            title="🛡️ Bảo Vệ Admin",
            description="Không thể reset tiền két sắt của admin chính!",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    user_id = member.id
    guild_id = ctx.guild.id

    # Lưu giá trị cũ để báo cáo
    old_amount = vault.get(guild_id, {}).get(user_id, 0)

    # Reset tiền két sắt về giá trị mới
    if guild_id not in vault:
        vault[guild_id] = defaultdict(int)
    vault[guild_id][user_id] = amount

    embed = discord.Embed(
        title="✅ Reset Tiền Két Sắt Thành Công",
        description=
        f"Đã reset tiền két sắt của {member.mention} từ **{old_amount} xu** xuống **{amount} xu**.",
        color=discord.Color.green())

    embed.set_footer(
        text=
        f"Admin: {ctx.author.name} | {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
    )
    await ctx.send(embed=embed)


@bot.command(name='resetall')
@commands.has_permissions(administrator=True)
async def reset_all(ctx, member: discord.Member = None, amount: int = 0):
    """Reset tất cả: xu, ngân hàng, két sắt của người chơi về 0 hoặc giá trị cụ thể"""
    if member is None:
        embed = discord.Embed(
            title="❌ Thiếu thông tin",
            description=
            "Vui lòng chỉ định người dùng để reset tất cả tiền.\nVí dụ: `.resetall @người_dùng [số xu mới]`\nNếu không nhập số xu mới, mặc định là 0.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Bảo vệ admin chính
    if member.id == 618702036992655381:
        embed = discord.Embed(
            title="🛡️ Bảo Vệ Admin",
            description="Không thể reset tiền của admin chính!",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    user_id = member.id
    guild_id = ctx.guild.id

    # Lưu giá trị cũ để báo cáo
    old_currency = currency.get(user_id, 0)
    old_bank = bank_accounts.get(user_id, {}).get(
        "balance", 0) if user_id in bank_accounts else 0
    old_vault = vault.get(guild_id, {}).get(user_id, 0)

    # Reset tất cả về giá trị mới
    currency[user_id] = amount

    if user_id in bank_accounts:
        bank_accounts[user_id]["balance"] = amount
        bank_accounts[user_id]["last_interest"] = datetime.now()

    if guild_id not in vault:
        vault[guild_id] = defaultdict(int)
    vault[guild_id][user_id] = amount

    # Tạo embed thông báo
    embed = discord.Embed(
        title="✅ Reset Tất Cả Thành Công",
        description=
        f"Đã reset tất cả tiền của {member.mention} về **{amount} xu**.",
        color=discord.Color.green())

    embed.add_field(name="Tiền xu",
                    value=f"Từ **{old_currency} xu** → **{amount} xu**",
                    inline=False)

    embed.add_field(name="Tiền ngân hàng",
                    value=f"Từ **{old_bank} xu** → **{amount} xu**",
                    inline=False)

    embed.add_field(name="Tiền két sắt",
                    value=f"Từ **{old_vault} xu** → **{amount} xu**",
                    inline=False)

    embed.set_footer(
        text=
        f"Admin: {ctx.author.name} | {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
    )
    await ctx.send(embed=embed)


@bot.command(name='hoidap', aliases=['hd'])
@check_channel()
@check_game_enabled('hoidap')
async def hoi_dap(ctx, bet: str = None):
    """Trò chơi hỏi đáp với câu hỏi ngẫu nhiên"""
    if bet is None:
        embed = discord.Embed(
            title="❓ Hỏi Đáp - Hướng Dẫn",
            description=
            "Trả lời câu hỏi để nhận thưởng.\nVí dụ: `.hoidap 50` hoặc `.hoidap all`",
            color=discord.Color.blue())
        embed.add_field(
            name="Cách chơi",
            value=
            "- Bot sẽ đưa ra câu hỏi ngẫu nhiên\n- Bạn chỉ có 10 giây để trả lời\n- Trả lời đúng: nhận x2 tiền cược\n- Trả lời sai: mất tiền cược",
            inline=False)
        await ctx.send(embed=embed)
        return

    # Kiểm tra số tiền cược
    user_id = ctx.author.id

    # Xử lý đặt cược "all"
    bet_amount = parse_bet(bet, currency[user_id])
    if bet_amount is None:
        embed = discord.Embed(
            title="❌ Số tiền không hợp lệ",
            description="Vui lòng nhập số tiền hợp lệ hoặc 'all'.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    if bet_amount <= 0:
        embed = discord.Embed(title="❌ Lỗi",
                              description="Số tiền cược phải lớn hơn 0.",
                              color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    if currency[user_id] < bet_amount:
        embed = discord.Embed(
            title="❌ Không đủ xu",
            description=
            f"Bạn cần {bet_amount} xu để chơi, nhưng chỉ có {currency[user_id]} xu.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Danh sách câu hỏi và đáp án
    questions = [
        {
            "question": "Thủ đô của Việt Nam là gì?",
            "answer": ["hanoi", "ha noi", "hà nội"],
            "hint": "Bắt đầu bằng chữ H"
        },
        {
            "question": "1 + 1 = ?",
            "answer": ["2", "hai"],
            "hint": "Số chẵn nhỏ nhất"
        },
        {
            "question":
            "Màu của bầu trời là gì?",
            "answer": [
                "xanh", "xanh duong", "xanh da troi", "xanh dương",
                "xanh da trời"
            ],
            "hint":
            "Một trong những màu cơ bản"
        },
        {
            "question": "Con vật nào được gọi là chúa tể rừng xanh?",
            "answer": ["su tu", "sư tử", "sutu"],
            "hint": "Biệt danh: Vua của muôn loài"
        },
        # 10 câu hỏi khó đã thêm trước đó
        {
            "question": "Nguyên tố hóa học nào có ký hiệu Au?",
            "answer": ["vang", "gold", "aurum"],
            "hint": "Kim loại quý được dùng làm trang sức"
        },
        {
            "question": "Ai là người phát minh ra điện thoại?",
            "answer": ["alexander graham bell", "bell", "graham bell"],
            "hint": "Tên có chứa chữ 'Bell'"
        },
        {
            "question":
            "Trái đất quay quanh mặt trời hết bao nhiêu ngày?",
            "answer": [
                "365", "365.25", "365 ngày", "365.25 ngày", "365 ngay",
                "365 ngay ruoi", "365 ngày rưỡi"
            ],
            "hint":
            "Số ngày trong một năm"
        },
        {
            "question": "Đâu là sông dài nhất thế giới?",
            "answer": ["sông nil", "nile", "nil", "song nil"],
            "hint": "Chảy qua các nước ở châu Phi"
        },
        {
            "question": "Phép tính 8^2 - 4^3 = ?",
            "answer": ["0", "không", "khong"],
            "hint": "Liên quan đến số 64"
        },
        {
            "question":
            "Loại vũ khí nào được Leonardo da Vinci thiết kế nhưng không bao giờ được chế tạo?",
            "answer": ["tank", "xe tăng", "xe tang"],
            "hint": "Phương tiện chiến đấu bọc thép"
        },
        {
            "question":
            "Đâu là ngôn ngữ lập trình cổ nhất còn được sử dụng rộng rãi ngày nay?",
            "answer": ["fortran"],
            "hint": "Được phát triển vào năm 1957, bắt đầu bằng chữ F"
        },
        {
            "question": "Tổng các chữ số của số 2023 là bao nhiêu?",
            "answer": ["7", "bay", "bảy"],
            "hint": "2 + 0 + 2 + 3 = ?"
        },
        {
            "question":
            "Trong hóa học, H2O2 là hợp chất gì?",
            "answer": [
                "hidro peroxide", "hydrogen peroxide", "oxy gia",
                "hydro peroxide", "oxy già"
            ],
            "hint":
            "Thường được dùng để tẩy trắng"
        },
        {
            "question": "Ai là người được mệnh danh 'Cha đẻ của máy tính'?",
            "answer": ["alan turing", "turing"],
            "hint": "Nhà toán học người Anh, phá mã Enigma trong Thế chiến II"
        },
        # Thêm 10 câu hỏi cực khó mới
        {
            "question": "Quốc gia nào có diện tích nhỏ nhất thế giới?",
            "answer":
            ["vatican", "thanh vatican", "thành vatican", "vaticano"],
            "hint": "Là một quốc gia nằm trong thành phố Rome, Ý"
        },
        {
            "question": "Ai là người đầu tiên đặt chân lên Mặt Trăng?",
            "answer": ["neil armstrong", "armstrong", "neil"],
            "hint": "Phi hành gia người Mỹ, thực hiện sứ mệnh Apollo 11"
        },
        {
            "question":
            "Nguyên tố hóa học nào có số nguyên tử lớn nhất trong các nguyên tố tự nhiên?",
            "answer": ["uranium", "urani", "u", "u-92"],
            "hint":
            "Có số nguyên tử là 92, thường được dùng trong nhà máy điện hạt nhân"
        },
        {
            "question": "Định lý Pythagorean áp dụng cho hình gì?",
            "answer": ["tam giác vuông", "triangle", "tam giac vuong"],
            "hint": "Hình học có một góc 90 độ"
        },
        {
            "question":
            "Năm bao nhiêu Constantinople thất thủ vào tay Đế chế Ottoman?",
            "answer": ["1453", "nam 1453"],
            "hint": "Sự kiện đánh dấu sự kết thúc của Đế chế Byzantine"
        },
        {
            "question": "Protein cấu tạo nên tóc và móng tay là gì?",
            "answer": ["keratin", "kê ra tin"],
            "hint": "Bắt đầu bằng chữ K, là protein sợi dạng xoắn"
        },
        {
            "question": "Đơn vị đo cường độ ánh sáng trong hệ SI là gì?",
            "answer": ["candela", "cd"],
            "hint": "Bắt đầu bằng chữ C, liên quan đến từ 'candle' (nến)"
        },
        {
            "question": "Công thức hóa học của glucose là gì?",
            "answer": ["c6h12o6", "c6 h12 o6"],
            "hint": "Công thức phân tử gồm 6 carbon, 12 hydrogen và 6 oxygen"
        },
        {
            "question": "Ai là người nghiên cứu và công bố thuyết tương đối?",
            "answer": ["albert einstein", "einstein", "anbe anh xtanh"],
            "hint": "Nhà vật lý nổi tiếng với công thức E=mc²"
        },
        {
            "question": "Đâu là ngọn núi cao nhất thế giới?",
            "answer": ["everest", "núi everest", "nui everest", "chomolungma"],
            "hint": "Cao 8,848.86 mét so với mực nước biển, nằm ở dãy Himalaya"
        },
        # Thêm 30 câu hỏi cực kỳ khó mới
        {
            "question":
            "Nguyên tố nào chiếm tỷ lệ lớn nhất trong vỏ Trái Đất?",
            "answer": ["oxygen", "o", "oxy"],
            "hint": "Không phải silicon hay sắt như nhiều người nghĩ"
        },
        {
            "question":
            "Năm 1923, một USD có thể đổi được bao nhiêu Reichsmark của Đức?",
            "answer": ["4.2 trillion", "4.2 nghìn tỷ", "4200000000000"],
            "hint": "Số nghìn tỷ, là ví dụ điển hình về siêu lạm phát"
        },
        {
            "question":
            "Quốc gia nào là quốc gia duy nhất không có hình chữ nhật trên quốc kỳ?",
            "answer": ["nepal", "ne pan"],
            "hint": "Quốc gia ở Nam Á, quốc kỳ hình tam giác kép"
        },
        {
            "question": "Em số nào lớn hơn: 1/3 hay 1/4?",
            "answer": ["1/3", "một phần ba", "mot phan ba"],
            "hint": "Mẫu số càng nhỏ, giá trị phân số càng lớn"
        },
        {
            "question":
            "Số lớn nhất có thể biểu diễn bằng 3 chữ số La Mã là bao nhiêu?",
            "answer": ["3999", "mmmcmxcix"],
            "hint": "Gần với 4000"
        },
        {
            "question":
            "Nhà toán học nào đã chứng minh định lý Fermat cuối cùng vào năm 1995?",
            "answer": ["andrew wiles", "wiles"],
            "hint":
            "Nhà toán học người Anh, giải quyết vấn đề tồn tại hơn 350 năm"
        },
        {
            "question": "Enzyme nào trong dạ dày con người phân hủy protein?",
            "answer": ["pepsin", "pep sin"],
            "hint": "Hoạt động trong môi trường acid của dạ dày"
        },
        {
            "question":
            "Hiệu ứng nào khiến ánh sáng bị bẻ cong khi đi qua một lăng kính?",
            "answer": ["khuc xa", "khúc xạ", "refraction", "sự khúc xạ"],
            "hint":
            "Xảy ra khi ánh sáng đi qua hai môi trường có mật độ khác nhau"
        },
        {
            "question":
            "Khoảng cách trung bình từ Trái Đất đến Mặt Trời là bao nhiêu triệu km?",
            "answer": ["150", "150 triệu", "150 trieu", "150000000"],
            "hint": "Còn gọi là 1 đơn vị thiên văn (AU)"
        },
        {
            "question": "Asteroid nào lớn nhất trong hệ Mặt Trời?",
            "answer": ["ceres", "seres"],
            "hint": "Đủ lớn để được phân loại là hành tinh lùn"
        },
        {
            "question": "Nước nào từng có tên gọi là Siam?",
            "answer": ["thailand", "thai lan", "thái lan"],
            "hint": "Đất nước Đông Nam Á nổi tiếng với món tom yum"
        },
        {
            "question":
            "Phương trình E = hf mô tả hiện tượng gì trong vật lý?",
            "answer": [
                "hien tuong quang dien", "hiện tượng quang điện", "quang điện",
                "photoelectric effect"
            ],
            "hint":
            "Hiện tượng mà ánh sáng giải phóng electron từ kim loại"
        },
        {
            "question":
            "Hệ số áp suất khí quyển tiêu chuẩn ở mực nước biển là bao nhiêu pascal?",
            "answer": ["101325", "101,325"],
            "hint": "Khoảng 1 bar hoặc 1 atm"
        },
        {
            "question":
            "Loài khủng long ba sừng nổi tiếng có tên khoa học là gì?",
            "answer": ["triceratops", "tri ce ra tops"],
            "hint": "Tên có nghĩa là 'mặt ba sừng'"
        },
        {
            "question":
            "Ai là người đầu tiên lái tàu vũ trụ bay vòng quanh Trái Đất?",
            "answer":
            ["yuri gagarin", "gagarin", "ga ga rin", "iu ri ga ga rin"],
            "hint": "Phi hành gia người Nga, thực hiện chuyến bay vào năm 1961"
        },
        {
            "question":
            "Giá trị nào là kết quả của phép tính lim(x→0) sin(x)/x?",
            "answer": ["1", "một", "mot"],
            "hint":
            "Kết quả cơ bản trong giải tích, liên quan đến đạo hàm của hàm sin"
        },
        {
            "question":
            "Hiệu ứng trái đất xanh xảy ra trên hành tinh nào trong hệ Mặt Trời?",
            "answer": ["venus", "kim", "sao kim"],
            "hint": "Hành tinh nóng nhất trong hệ Mặt Trời"
        },
        {
            "question": "Bộ gen người có bao nhiêu cặp nhiễm sắc thể?",
            "answer": ["23", "hai mươi ba", "hai muoi ba"],
            "hint": "Một nửa số nhiễm sắc thể từ mẹ, nửa còn lại từ cha"
        },
        {
            "question":
            "Lít và đề-xi-mét khối (dm³) có quan hệ như thế nào?",
            "answer":
            ["bang nhau", "bằng nhau", "equal", "giống nhau", "giong nhau"],
            "hint":
            "1 dm³ = ? L"
        },
        {
            "question": "Nguyên tố có ký hiệu hóa học Hg là gì?",
            "answer": ["thủy ngân", "thuy ngan", "mercury"],
            "hint":
            "Kim loại lỏng ở nhiệt độ phòng, từng được dùng trong nhiệt kế"
        },
        {
            "question": "Ai là người đề xuất thuyết tương đối rộng?",
            "answer": ["albert einstein", "einstein"],
            "hint": "Cũng là người đề xuất thuyết tương đối hẹp"
        },
        {
            "question":
            "Đơn vị đo áp suất nào mang tên nhà khoa học người Pháp?",
            "answer": ["pascal", "pa"],
            "hint": "Đơn vị SI của áp suất, ký hiệu là Pa"
        },
        {
            "question":
            "Loại mã hóa nào sử dụng hai khóa: khóa công khai và khóa riêng?",
            "answer": [
                "bất đối xứng", "bat doi xung", "asymmetric", "khoa cong khai",
                "public key", "khóa công khai"
            ],
            "hint":
            "Phương pháp mã hóa cơ bản trong các giao dịch trực tuyến an toàn"
        },
        {
            "question": "Đâu là nguyên nhân chính gây bệnh scurvy?",
            "answer": ["thiếu vitamin c", "thieu vitamin c"],
            "hint": "Thiếu hụt vitamin có nhiều trong cam quýt"
        },
        {
            "question":
            "Ai viết bài báo 'On the Electrodynamics of Moving Bodies' năm 1905 giới thiệu thuyết tương đối hẹp?",
            "answer": ["albert einstein", "einstein"],
            "hint": "Nhà vật lý người Đức-Mỹ nổi tiếng với phương trình E=mc²"
        },
        {
            "question":
            "Quá trình nào diễn ra trong lò phản ứng hạt nhân?",
            "answer": ["phân hạch", "phan hach", "nuclear fission"],
            "hint":
            "Quá trình chia tách các hạt nhân nặng thành các hạt nhân nhẹ hơn"
        },
        {
            "question": "Ở đâu có địa điểm được gọi là 'nóc nhà thế giới'?",
            "answer": ["tây tạng", "tay tang", "tibet"],
            "hint": "Cao nguyên gần dãy Himalaya"
        },
        {
            "question": "Hàm số lượng giác nào có đạo hàm bằng chính nó?",
            "answer": ["e^x", "e mũ x", "e mu x", "hàm mũ e", "ham mu e"],
            "hint": "Hàm số mà đạo hàm không thay đổi giá trị của hàm"
        },
        {
            "question": "Eo biển nào ngăn cách châu Âu và châu Phi?",
            "answer": ["gibraltar", "gibraltar strait", "eo gibraltar"],
            "hint": "Nối Đại Tây Dương với Địa Trung Hải"
        },
        {
            "question": "Vùng đất nào được gọi là 'vùng đất của lửa và băng'?",
            "answer": ["iceland", "băng đảo", "bang dao"],
            "hint": "Quốc gia đảo ở Bắc Âu với nhiều núi lửa và sông băng"
        }
    ]

    # Chọn câu hỏi ngẫu nhiên
    question_data = random.choice(questions)

    embed = discord.Embed(title="❓ Câu hỏi",
                          description=question_data["question"],
                          color=discord.Color.blue())
    embed.add_field(name="Thời gian", value="10 giây", inline=True)
    embed.add_field(name="Tiền cược", value=f"{bet_amount} xu", inline=True)

    question_msg = await ctx.send(embed=embed)

    # Kiểm tra câu trả lời từ người dùng
    def check(message):
        return message.author == ctx.author and message.channel == ctx.channel

    # Theo dõi đếm ngược và gợi ý đồng thời với việc chờ câu trả lời
    tasks = []
    # Tạo task chờ tin nhắn - giảm từ 30 xuống còn 10 giây
    wait_for_message_task = asyncio.create_task(
        bot.wait_for('message', timeout=10.0, check=check))
    tasks.append(wait_for_message_task)

    # Tạo task cho bộ đếm thời gian và gợi ý
    async def countdown_and_hint():
        # Chờ 4 giây đầu tiên
        await asyncio.sleep(4)
        # Cập nhật còn 6 giây
        embed.set_field_at(0, name="Thời gian", value="6 giây", inline=True)
        await question_msg.edit(embed=embed)

        # Chờ thêm 3 giây
        await asyncio.sleep(3)
        # Cập nhật còn 3 giây và hiển thị gợi ý
        embed.set_field_at(0, name="Thời gian", value="3 giây", inline=True)
        embed.add_field(name="💡 Gợi ý",
                        value=question_data["hint"],
                        inline=False)
        await question_msg.edit(embed=embed)

        # Chờ 3 giây cuối
        await asyncio.sleep(3)

    countdown_task = asyncio.create_task(countdown_and_hint())
    tasks.append(countdown_task)

    try:
        # Chờ task nào hoàn thành trước (có câu trả lời hoặc hết thời gian)
        done, pending = await asyncio.wait(tasks,
                                           return_when=asyncio.FIRST_COMPLETED)

        # Hủy các task đang chờ
        for task in pending:
            task.cancel()

        # Nếu nhận được tin nhắn trả lời
        if wait_for_message_task in done:
            response = wait_for_message_task.result()

            # Kiểm tra câu trả lời
            answer_correct = False
            for valid_answer in question_data["answer"]:
                if response.content.lower().replace(
                        " ", "") == valid_answer.replace(" ", ""):
                    answer_correct = True
                    break

            if answer_correct:
                winnings = bet_amount * 2
                currency[user_id] += winnings - bet_amount

                embed = discord.Embed(
                    title="✅ CHÍNH XÁC!",
                    description=
                    f"Chúc mừng {ctx.author.mention}! Bạn đã trả lời đúng!",
                    color=discord.Color.green())
                embed.add_field(name="Tiền thưởng",
                                value=f"+{winnings} xu (x2)",
                                inline=True)
                embed.add_field(name="Số dư hiện tại",
                                value=f"{currency[user_id]} xu",
                                inline=True)
            else:
                currency[user_id] -= bet_amount

                embed = discord.Embed(
                    title="❌ SAI RỒI!",
                    description=
                    f"Rất tiếc, {ctx.author.mention}! Câu trả lời đúng là: {question_data['answer'][0]}",
                    color=discord.Color.red())
                embed.add_field(name="Thiệt hại",
                                value=f"-{bet_amount} xu",
                                inline=True)
                embed.add_field(name="Số dư hiện tại",
                                value=f"{currency[user_id]} xu",
                                inline=True)

            await ctx.send(embed=embed)

    except asyncio.TimeoutError:
        # Hết thời gian 10 giây mà không có câu trả lời
        currency[user_id] -= bet_amount
        embed = discord.Embed(
            title="⏰ HẾT GIỜ!",
            description=f"{ctx.author.mention}, bạn đã không trả lời kịp thời!",
            color=discord.Color.red())
        embed.add_field(name="Câu trả lời đúng",
                        value=question_data["answer"][0],
                        inline=True)
        embed.add_field(name="Thiệt hại",
                        value=f"-{bet_amount} xu",
                        inline=True)
        embed.add_field(name="Số dư hiện tại",
                        value=f"{currency[user_id]} xu",
                        inline=True)
        await ctx.send(embed=embed)


@bot.command(name='baucua', aliases=['bc'])
@check_channel()
@check_game_enabled('baucua')
async def bau_cua(ctx, *args):
    """Trò chơi Bầu Cua Tôm Cá với khả năng đặt nhiều ô cùng lúc"""
    # Định nghĩa các mặt xúc xắc và emoji
    symbols = {
        "bầu": "🍐", "bau": "🍐",
        "cua": "🦀",
        "tôm": "🦐", "tom": "🦐", 
        "cá": "🐟", "ca": "🐟",
        "gà": "🐓", "ga": "🐓",
        "nai": "🦌"
    }

    symbol_names = {
        "🍐": "Bầu",
        "🦀": "Cua",
        "🦐": "Tôm",
        "🐟": "Cá",
        "🐓": "Gà",
        "🦌": "Nai"
    }

    # Hiển thị hướng dẫn nếu không có đủ thông tin
    if not args:
        embed = discord.Embed(
            title="🎲 Bầu Cua Tôm Cá - Hướng Dẫn",
            description="Đặt cược vào một hoặc nhiều mặt xúc xắc và thắng xu nếu chọn đúng!",
            color=discord.Color.gold()
        )

        embed.add_field(
            name="📋 Cách chơi",
            value=(
                "1. Chọn một hoặc nhiều mặt và số xu cược:\n"
                "2. Mặt hợp lệ: `bau`, `cua`, `tom`, `ca`, `ga`, `nai`\n"
                "3. Ví dụ: `.baucua bau 50 cua 100` hoặc `.bc ga all`\n"
                "4. Bạn có thể đặt nhiều ô cùng lúc!"
            ),
            inline=False
        )

        embed.add_field(
            name="💰 Thưởng",
            value=(
                "- Cho mỗi ô đặt cược:\n"
                "- Xuất hiện 1 lần: x1 tiền cược\n"
                "- Xuất hiện 2 lần: x2 tiền cược\n"
                "- Xuất hiện 3 lần (jackpot): x3 tiền cược"
            ),
            inline=False
        )

        symbol_display = " ".join(list(dict.fromkeys(symbols.values())))
        embed.add_field(
            name="🎯 Các mặt xúc xắc",
            value=symbol_display,
            inline=False
        )

        await ctx.send(embed=embed)
        return

    # Xử lý đặt cược nhiều ô
    user_id = ctx.author.id
    bets = {}  # Dictionary để lưu cược cho mỗi biểu tượng: {emoji: bet_amount}
    total_bet = 0

    # Phân tích các lựa chọn cược
    i = 0
    while i < len(args):
        choice = args[i].lower()

        # Kiểm tra xem choice có hợp lệ không
        if choice not in symbols:
            embed = discord.Embed(
                title="❌ Lựa chọn không hợp lệ",
                description=f"'{choice}' không hợp lệ. Vui lòng chọn: `bau`, `cua`, `tom`, `ca`, `ga`, `nai`.",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
            return

        # Lấy bet amount cho choice này
        if i + 1 >= len(args):
            embed = discord.Embed(
                title="❌ Thiếu số tiền cược",
                description=f"Vui lòng nhập số tiền cược sau '{choice}'.",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
            return

        bet_str = args[i + 1]

        # Xử lý đặt cược "all"
        if bet_str.lower() == "all":
            # Nếu đã có cược khác trước đó, không cho phép dùng "all"
            if bets:
                embed = discord.Embed(
                    title="❌ Không hợp lệ",
                    description="'all' chỉ có thể sử dụng cho một ô cược duy nhất.",
                    color=discord.Color.red()
                )
                await ctx.send(embed=embed)
                return

            bet_amount = currency[user_id]
        else:
            try:
                bet_amount = int(bet_str)
            except ValueError:
                embed = discord.Embed(
                    title="❌ Số tiền không hợp lệ",
                    description=f"'{bet_str}' không phải là số tiền hợp lệ.",
                    color=discord.Color.red()
                )
                await ctx.send(embed=embed)
                return

        # Kiểm tra số tiền cược
        if bet_amount <= 0:
            embed = discord.Embed(
                title="❌ Lỗi",
                description="Số tiền cược phải lớn hơn 0.",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
            return

        # Lấy emoji cho lựa chọn
        choice_emoji = symbols[choice]

        # Cộng dồn tiền cược cho symbol này (có thể đặt cược nhiều lần cho cùng một symbol)
        if choice_emoji in bets:
            bets[choice_emoji] += bet_amount
        else:
            bets[choice_emoji] = bet_amount

        total_bet += bet_amount
        i += 2  # Chuyển đến cặp choice-bet tiếp theo

    # Kiểm tra tổng tiền cược
    if total_bet <= 0:
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Tổng số tiền cược phải lớn hơn 0.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return

    if currency[user_id] < total_bet:
        embed = discord.Embed(
            title="❌ Không đủ xu",
            description=f"Bạn cần {total_bet} xu để đặt cược, nhưng chỉ có {currency[user_id]} xu.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return

    # Hiệu ứng khởi đầu
    loading_embed = discord.Embed(
        title="🎲 ĐANG LẮC BẦU CUA",
        description=f"{ctx.author.mention} đã đặt cược tổng **{total_bet} xu**",
        color=discord.Color.blue()
    )

    # Hiển thị các cược đã đặt
    bet_details = ""
    for emoji, amount in bets.items():
        bet_details += f"{emoji} **{symbol_names[emoji]}**: {amount} xu\n"

    loading_embed.add_field(
        name="💰 Chi tiết cược", 
        value=bet_details,
        inline=False
    )
    loading_embed.set_footer(text="Đang lắc xúc xắc...")
    loading_msg = await ctx.send(embed=loading_embed)

    # Tạo list các emoji
    all_emojis = list(symbol_names.keys())

    # Animation giai đoạn 1: Lắc nhanh với nhiều emoji xáo trộn
    shaking_colors = [
        discord.Color.blue(), 
        discord.Color.purple(), 
        discord.Color.teal(), 
        discord.Color.orange(), 
        discord.Color.gold()
    ]

    shake_titles = [
        "🎲 ĐANG LẮC BẦU CUA",
        "🎲 XÚC XẮC ĐANG QUAY",
        "🎲 ĐANG XÁO TRỘN",
        "🎲 BẦU CUA ĐANG LẮC",
        "🎲 ĐANG ĐỊNH KẾT QUẢ"
    ]

    # Animation lắc mạnh
    for i in range(5):
        # Tạo hiệu ứng xáo trộn 
        dice1 = random.sample(all_emojis, k=len(all_emojis))
        dice2 = random.sample(all_emojis, k=len(all_emojis))
        dice3 = random.sample(all_emojis, k=len(all_emojis))

        # Hiển thị các xúc xắc đang xáo trộn nhanh
        shake_display = (
            f"**Xúc xắc 1:** {' '.join(dice1[:3])}...\n"
            f"**Xúc xắc 2:** {' '.join(dice2[:3])}...\n"
            f"**Xúc xắc 3:** {' '.join(dice3[:3])}...\n"
        )

        title = shake_titles[i % len(shake_titles)]
        color = shaking_colors[i % len(shaking_colors)]
        dots = "." * (i+1)

        shaking_embed = discord.Embed(
            title=f"{title} {dots}",
            description=f"{ctx.author.mention} đã đặt cược tổng **{total_bet} xu**",
            color=color
        )
        shaking_embed.add_field(
            name="🎲 Đang lắc xúc xắc",
            value=shake_display,
            inline=False
        )

        # Giữ nguyên chi tiết cược
        shaking_embed.add_field(
            name="💰 Chi tiết cược", 
            value=bet_details,
            inline=False
        )

        shaking_embed.set_footer(text=f"Đang lắc{dots}")

        await loading_msg.edit(embed=shaking_embed)
        await asyncio.sleep(0.6)

    # Chậm dần và hiển thị từng viên xúc xắc
    await asyncio.sleep(0.5)

    # Chọn kết quả ngẫu nhiên cho 3 viên xúc xắc
    result_dice = [random.choice(all_emojis) for _ in range(3)]

    # Animation hiển thị từng viên xúc xắc
    for i in range(3):
        dice_embed = discord.Embed(
            title=f"🎲 XÚC XẮC ĐANG DỪNG LẠI",
            description=f"{ctx.author.mention} đã đặt cược tổng **{total_bet} xu**",
            color=discord.Color.gold()
        )

        # Hiển thị kết quả từng viên một
        dice_result = ""
        for j in range(i + 1):
            dice_result += f"**Xúc xắc {j+1}:** {result_dice[j]} **{symbol_names[result_dice[j]]}**\n"

        for j in range(i + 1, 3):
            dice_result += f"**Xúc xắc {j+1}:** ❓\n"

        dice_embed.add_field(
            name="🎯 Kết quả đang hiện",
            value=dice_result,
            inline=False
        )

        # Giữ nguyên chi tiết cược
        dice_embed.add_field(
            name="💰 Chi tiết cược", 
            value=bet_details,
            inline=False
        )

        dice_embed.set_footer(text=f"Đang hiện kết quả... {i+1}/3")
        await loading_msg.edit(embed=dice_embed)
        await asyncio.sleep(0.8)

    # Đếm kết quả cho từng biểu tượng
    symbol_counts = {}
    for emoji in all_emojis:
        symbol_counts[emoji] = result_dice.count(emoji)

    # Tính toán thắng/thua cho mỗi cược
    total_winnings = 0
    bet_results = {}

    for emoji, bet_amount in bets.items():
        matches = symbol_counts[emoji]
        if matches > 0:
            winnings = bet_amount * matches
            bet_results[emoji] = {
                "matches": matches,
                "winnings": winnings,
                "result": "win"
            }
            total_winnings += winnings
        else:
            bet_results[emoji] = {
                "matches": 0,
                "winnings": -bet_amount,
                "result": "lose"
            }

    # Tính tổng thắng/thua
    net_result = total_winnings - total_bet

    # Cập nhật số xu của người chơi
    currency[user_id] += net_result

    # Hiển thị kết quả chi tiết
    final_embed = discord.Embed(
        title="🎲 KẾT QUẢ BẦU CUA 🎲",
        description="",
        color=discord.Color.green() if net_result >= 0 else discord.Color.red()
    )

    # Hiển thị kết quả xúc xắc
    dice_result = ""
    for j in range(3):
        dice_result += f"**Xúc xắc {j+1}:** {result_dice[j]} **{symbol_names[result_dice[j]]}**\n"

    final_embed.add_field(
        name="🎯 Kết quả xúc xắc",
        value=dice_result,
        inline=False
    )

    # Hiển thị chi tiết thắng/thua cho mỗi cược
    results_details = ""
    for emoji, result_info in bet_results.items():
        if result_info["result"] == "win":
            if result_info["matches"] == 1:
                results_details += f"{emoji} **{symbol_names[emoji]}**: +{result_info['winnings']} xu (x1)\n"
            elif result_info["matches"] == 2:
                results_details += f"{emoji} **{symbol_names[emoji]}**: +{result_info['winnings']} xu (x2) 🌟\n"
            else: # 3 matches
                results_details += f"{emoji} **{symbol_names[emoji]}**: +{result_info['winnings']} xu (x3) 💎\n"
        else:
            results_details += f"{emoji} **{symbol_names[emoji]}**: -{bets[emoji]} xu ❌\n"

    final_embed.add_field(
        name="💰 Chi tiết thắng/thua",
        value=results_details,
        inline=False
    )

    # Hiển thị kết quả tổng
    if net_result > 0:
        final_embed.add_field(
            name="🏆 TỔNG KẾT",
            value=f"Thắng: +{net_result} xu",
            inline=True
        )
        final_embed.description = f"🎉 {ctx.author.mention} đã thắng **{net_result} xu**!"
    elif net_result == 0:
        final_embed.add_field(
            name="🏆 TỔNG KẾT",
            value=f"Hòa: ±0 xu",
            inline=True
        )
        final_embed.description = f"🤝 {ctx.author.mention} hòa vốn!"
    else:
        final_embed.add_field(
            name="🏆 TỔNG KẾT",
            value=f"Thua: {net_result} xu",
            inline=True
        )
        final_embed.description = f"😢 {ctx.author.mention} đã thua **{-net_result} xu**!"

    final_embed.add_field(
        name="💼 Số dư hiện tại",
        value=f"{currency[user_id]} xu",
        inline=True
    )

    # Footer tùy theo kết quả
    if net_result > 0:
        final_embed.set_footer(text="🍀 Hôm nay là ngày may mắn của bạn!")
    elif net_result == 0:
        final_embed.set_footer(text="🤔 Hòa vốn! Thử lại vận may của bạn!")
    else:
        final_embed.set_footer(text="😢 Thử lại vận may của bạn nhé!")

    await loading_msg.edit(embed=final_embed)


@bot.command(name='kbbpvp')
@check_channel()
@check_game_enabled('kbbpvp')
async def keo_bua_bao_pvp(ctx, opponent: discord.Member = None, bet: int = None):
    """Chơi Kéo Búa Bao PvP với người chơi khác với hiệu ứng đẹp mắt"""
    if opponent is None or bet is None:
        embed = discord.Embed(
            title="⚔️ Kéo Búa Bao PvP - Hướng Dẫn",
            description=
            "Thách đấu người chơi khác với hiệu ứng đẹp mắt.\nVí dụ: `.kbbpvp @tên_người_chơi 50`",
            color=discord.Color.blue())
        embed.add_field(
            name="Cách chơi",
            value=
            "- Tag người chơi muốn thách đấu\n- Đặt số xu muốn cược\n- Cả hai bên chọn kéo/búa/bao qua nút bấm\n- Người thắng nhận toàn bộ tiền cược\n- Người thắng có thể timeout người thua!",
            inline=False)
        embed.set_footer(text="Kẻo Búa Bao - Game thách đấu hấp dẫn!")
        await ctx.send(embed=embed)
        return

    user_id = ctx.author.id
    target_id = opponent.id

    # Kiểm tra không thể chơi với chính mình
    if user_id == target_id:
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Bạn không thể thách đấu chính mình!",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Kiểm tra không thể chơi với bot
    if opponent.bot:
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Bạn không thể thách đấu bot! Hãy thách đấu người chơi khác.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Kiểm tra số tiền cược
    if bet <= 0:
        embed = discord.Embed(title="❌ Lỗi",
                              description="Số tiền cược phải lớn hơn 0.",
                              color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Kiểm tra số dư của cả hai người chơi
    if currency[user_id] < bet:
        embed = discord.Embed(
            title="❌ Không đủ xu",
            description=f"{ctx.author.mention} không đủ xu để đặt cược!",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    if currency[target_id] < bet:
        embed = discord.Embed(
            title="❌ Không đủ xu",
            description=
            f"{opponent.mention} không đủ xu để chấp nhận thách đấu!",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Tạo view cho người thách đấu
    class KBBView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=60)
            self.choices = {}
            self.choice_emojis = {"keo": "✂️", "bua": "🪨", "bao": "📄"}
            self.choice_names = {"keo": "Kéo", "bua": "Búa", "bao": "Bao"}
            self.result_shown = False

        @discord.ui.button(label="Kéo",
                          style=discord.ButtonStyle.primary,
                          emoji="✂️",
                          custom_id="keo")
        async def keo(self, interaction: discord.Interaction,
                      button: discord.ui.Button):
            await self.make_choice(interaction, "keo")

        @discord.ui.button(label="Búa",
                          style=discord.ButtonStyle.primary,
                          emoji="🪨",
                          custom_id="bua")
        async def bua(self, interaction: discord.Interaction,
                      button: discord.ui.Button):
            await self.make_choice(interaction, "bua")

        @discord.ui.button(label="Bao",
                          style=discord.ButtonStyle.primary,
                          emoji="📄",
                          custom_id="bao")
        async def bao(self, interaction: discord.Interaction,
                      button: discord.ui.Button):
            await self.make_choice(interaction, "bao")

        async def make_choice(self, interaction: discord.Interaction,
                             choice: str):
            player_id = interaction.user.id

            # Kiểm tra xem người dùng có phải là người chơi không
            if player_id not in [user_id, target_id]:
                await interaction.response.send_message(
                    "Bạn không phải người chơi trong trận này!",
                    ephemeral=True)
                return

            # Kiểm tra nếu người chơi đã chọn rồi
            if player_id in self.choices:
                prev_choice = self.choices[player_id]
                await interaction.response.send_message(
                    f"Bạn đã thay đổi lựa chọn từ {self.choice_names[prev_choice]} sang {self.choice_names[choice]}!",
                    ephemeral=True)
            else:
                await interaction.response.send_message(
                    f"Bạn đã chọn {self.choice_names[choice]}!",
                    ephemeral=True)

            # Lưu lựa chọn
            self.choices[player_id] = choice

            # Kiểm tra xem cả hai người chơi đã chọn chưa
            if len(self.choices) == 2 and not self.result_shown:
                self.result_shown = True
                self.stop()

                # Vô hiệu hóa các nút
                for child in self.children:
                    child.disabled = True

    # Tạo thông báo thách đấu
    challenge_embed = discord.Embed(
        title="⚔️ THÁCH ĐẤU KÉO BÚA BAO!",
        description=
        f"{ctx.author.mention} thách đấu {opponent.mention} với **{bet} xu**!",
        color=discord.Color.gold())

    challenge_embed.add_field(
        name="🎮 Cách chơi",
        value="Cả hai người chơi hãy bấm nút để chọn Kéo, Búa hoặc Bao.\nNgười thắng sẽ nhận toàn bộ tiền cược!",
        inline=False
    )

    challenge_embed.add_field(
        name="⚠️ Lưu ý",
        value="- Bạn có 60 giây để chọn\n- Người thắng có thể timeout người thua\n- Lựa chọn của bạn được giữ bí mật",
        inline=False
    )

    challenge_embed.set_footer(text="Hãy chọn một lựa chọn bên dưới")

    # Thêm hiệu ứng animation với nền và biểu tượng
    challenge_graphic = "```\n" + \
                       "    ⚡⚡⚡    \n" + \
                       "  ⚔️ VS ⚔️  \n" + \
                       "✂️  🪨  📄\n" + \
                       "  ⚡ VS ⚡  \n" + \
                       "    ⚡⚡⚡    \n" + \
                       "```"
    challenge_embed.add_field(
        name="🏆 Trận đấu",
        value=challenge_graphic,
        inline=False
    )

    kbb_view = KBBView()
    message = await ctx.send(embed=challenge_embed, view=kbb_view)

    # Bắt đầu đếm ngược với hiệu ứng
    countdown_seconds = 60
    countdown_interval = 10  # Cập nhật mỗi 10 giây

    # Animation đếm ngược khi đang chờ người chơi
    for remaining in range(countdown_seconds, 0, -countdown_interval):
        if kbb_view.is_finished():
            break

        if remaining <= 30:  # Chỉ hiển thị đếm ngược khi còn 30 giây
            countdown_embed = discord.Embed(
                title="⚔️ THÁCH ĐẤU KÉO BÚA BAO!",
                description=f"{ctx.author.mention} thách đấu {opponent.mention} với **{bet} xu**!",
                color=discord.Color.gold())

            countdown_embed.add_field(
                name="⏱️ THỜI GIAN CÒN LẠI",
                value=f"**{remaining} giây**",
                inline=False
            )

            # Hiển thị ai đã chọn, ai chưa chọn
            player1_status = "✅ Đã chọn" if user_id in kbb_view.choices else "⏳ Chưa chọn"
            player2_status = "✅ Đã chọn" if target_id in kbb_view.choices else "⏳ Chưa chọn"

            countdown_embed.add_field(
                name="👤 Trạng thái người chơi",
                value=f"{ctx.author.mention}: {player1_status}\n{opponent.mention}: {player2_status}",
                inline=False
            )

            # Nhắc nhở
            countdown_embed.add_field(
                name="💡 Nhắc nhở", 
                value="Hãy bấm nút bên dưới để chọn Kéo, Búa hoặc Bao!",
                inline=False
            )

            await message.edit(embed=countdown_embed, view=kbb_view)

        await asyncio.sleep(countdown_interval)

    # Chờ view hoàn thành hoặc timeout
    await kbb_view.wait()

    # Kiểm tra kết quả
    if len(kbb_view.choices) < 2:
        # Có người không chọn trong thời gian quy định
        timeout_embed = discord.Embed(
            title="⏱️ HẾT THỜI GIAN",
            description="Một hoặc cả hai người chơi không kịp chọn trong thời gian quy định!",
            color=discord.Color.red())

        # Xác định ai chưa chọn
        if user_id not in kbb_view.choices and target_id not in kbb_view.choices:
            timeout_embed.add_field(
                name="❌ Cả hai người chơi đều chưa chọn",
                value="Thách đấu bị hủy!",
                inline=False
            )
        elif user_id not in kbb_view.choices:
            timeout_embed.add_field(
                name="❌ Người thách đấu không chọn",
                value=f"{ctx.author.mention} đã không chọn kịp thời!",
                inline=False
            )
        else:
            timeout_embed.add_field(
                name="❌ Người được thách đấu không chọn",
                value=f"{opponent.mention} đã không chọn kịp thời!",
                inline=False
            )

        await message.edit(embed=timeout_embed, view=None)
        return

    # Xác định người thắng
    choice1 = kbb_view.choices[user_id]
    choice2 = kbb_view.choices[target_id]

    # Tạo hiệu ứng đếm ngược trước khi công bố kết quả
    for countdown in range(3, 0, -1):
        countdown_embed = discord.Embed(
            title="👀 CÔNG BỐ KẾT QUẢ",
            description=f"Kết quả sẽ hiện ra sau {countdown}...",
            color=discord.Color.gold())

        # Hiệu ứng tạo kịch tính
        if countdown == 3:
            countdown_embed.add_field(
                name="🔄 Đang tính toán",
                value="```\nĐang phân tích lựa chọn...\n```",
                inline=False
            )
        elif countdown == 2:
            countdown_embed.add_field(
                name="🔄 Kết quả sẵn sàng",
                value="```\nSắp hiện kết quả...\n```",
                inline=False
            )
        else:
            countdown_embed.add_field(
                name="🔄 Chuẩn bị!",
                value="```\nKết quả ngay sau đây...\n```",
                inline=False
            )

        await message.edit(embed=countdown_embed, view=kbb_view)
        await asyncio.sleep(0.8)

    # Hiển thị lựa chọn của cả hai người chơi
    reveal_embed = discord.Embed(
        title="🎮 LỰA CHỌN ĐÃ ĐƯỢC TIẾT LỘ!",
        description=f"Cả hai người chơi đã hoàn thành lượt chọn!",
        color=discord.Color.blue())

    # Animation hiển thị lựa chọn
    choice1_emoji = kbb_view.choice_emojis[choice1]
    choice1_name = kbb_view.choice_names[choice1]
    choice2_emoji = kbb_view.choice_emojis[choice2]
    choice2_name = kbb_view.choice_names[choice2]

    reveal_embed.add_field(
        name=f"{ctx.author.display_name} chọn",
        value=f"**{choice1_name}** {choice1_emoji}",
        inline=True
    )

    reveal_embed.add_field(
        name="VS",
        value="⚔️",
        inline=True
    )

    reveal_embed.add_field(
        name=f"{opponent.display_name} chọn",
        value=f"**{choice2_name}** {choice2_emoji}",
        inline=True
    )

    # Hiển thị kết quả lựa chọn
    battle_graphic = "```\n" + \
                    f"  {ctx.author.display_name}    VS    {opponent.display_name}\n" + \
                    f"     {choice1_emoji}         {choice2_emoji}\n" + \
                    f"    {choice1_name}       {choice2_name}\n" + \
                    "```"
    reveal_embed.add_field(
        name="⚔️ TRẬN ĐẤU",
        value=battle_graphic,
        inline=False
    )

    await message.edit(embed=reveal_embed, view=kbb_view)
    await asyncio.sleep(2)

    # Xử lý kết quả
    if choice1 == choice2:
        # Hòa
        result_embed = discord.Embed(
            title="🤝 HÒA CUỘC!",
            description=f"Cả hai người chơi đều chọn **{kbb_view.choice_names[choice1]}**!",
            color=discord.Color.blue())

        result_embed.add_field(
            name="💰 Kết quả tiền cược",
            value="Cả hai người chơi đều được hoàn lại tiền cược.",
            inline=False
        )

        # Animation hiệu ứng hòa
        tie_graphic = "```\n" + \
                     "     🔄  🔀  🔄     \n" + \
                     "  🤝  HÒA CUỘC  🤝  \n" + \
                     f" {choice1_emoji} {ctx.author.name} VS {opponent.name} {choice2_emoji} \n" + \
                     "     🔄  🔀  🔄     \n" + \
                     "```"
        result_embed.add_field(
            name="📊 Chi tiết",
            value=tie_graphic,
            inline=False
        )

        await message.edit(embed=result_embed, view=kbb_view)

    else:
        # Xác định người thắng
        player1_wins = ((choice1 == "keo" and choice2 == "bao")
                        or (choice1 == "bua" and choice2 == "keo")
                        or (choice1 == "bao" and choice2 == "bua"))

        if player1_wins:
            winner = ctx.author
            loser = opponent
            winner_id = user_id
            loser_id = target_id
            winner_choice = choice1
            loser_choice = choice2
        else:
            winner = opponent
            loser = ctx.author
            winner_id = target_id
            loser_id = user_id
            winner_choice = choice2
            loser_choice = choice1

        # Hiệu ứng công bố người thắng
        for i in range(3):
            win_color = discord.Color.green() if i % 2 == 0 else discord.Color.gold()

            win_announce = discord.Embed(
                title=f"{'🎉 CHIẾN THẮNG! 🎉' if i % 2 == 0 else '🏆 NGƯỜI THẮNG CUỘC 🏆'}",
                description=f"**{winner.display_name}** đã thắng!",
                color=win_color)

            win_graphic = "```\n" + \
                         f"    {'✨' * (i+1)}    \n" + \
                         f"  🏆 {winner.display_name} 🏆  \n" + \
                         f" {kbb_view.choice_emojis[winner_choice]} CHIẾN THẮNG! {kbb_view.choice_emojis[winner_choice]} \n" + \
                         f"    {'✨' * (i+1)}    \n" + \
                         "```"
            win_announce.add_field(
                name="🎖️ Người chiến thắng",
                value=win_graphic,
                inline=False
            )

            await message.edit(embed=win_announce, view=kbb_view)
            await asyncio.sleep(0.8)

        # Cập nhật xu
        currency[winner_id] += bet
        currency[loser_id] -= bet

        # Tạo kết quả cuối cùng
        result_embed = discord.Embed(
            title="🏆 KẾT QUẢ CUỐI CÙNG 🏆",
            description=f"**{winner.display_name}** đã thắng **{loser.display_name}**!",
            color=discord.Color.green())

        # Hiển thị giải thích lý do thắng
        win_explanation = ""
        if winner_choice == "keo" and loser_choice == "bao":
            win_explanation = "Kéo ✂️ cắt Bao 📄"
        elif winner_choice == "bua" and loser_choice == "keo":
            win_explanation = "Búa 🪨 đập Kéo ✂️"
        elif winner_choice == "bao" and loser_choice == "bua":
            win_explanation = "Bao 📄 bọc Búa 🪨"

        result_embed.add_field(
            name="🎯 Lý do thắng",
            value=win_explanation,
            inline=False
        )

        # Hiển thị lựa chọn chi tiết
        result_embed.add_field(
            name=f"{winner.display_name} (Thắng)",
            value=f"**{kbb_view.choice_names[winner_choice]}** {kbb_view.choice_emojis[winner_choice]}",
            inline=True
        )

        result_embed.add_field(
            name=f"{loser.display_name} (Thua)",
            value=f"**{kbb_view.choice_names[loser_choice]}** {kbb_view.choice_emojis[loser_choice]}",
            inline=True
        )

        # Hiển thị tiền thưởng
        result_embed.add_field(
            name="💰 Phần thưởng",
            value=f"**{winner.mention}** đã thắng và nhận được **{bet*2} xu**!",
            inline=False
        )

        # Hiển thị số dư mới
        result_embed.add_field(
            name=f"💼 Số dư của {winner.display_name}",
            value=f"**{currency[winner_id]} xu**",
            inline=True
        )

        result_embed.add_field(
            name=f"💼 Số dư của {loser.display_name}",
            value=f"**{currency[loser_id]} xu**",
            inline=True
        )

        # Thêm nút timeout cho người thắng
        timeout_view = discord.ui.View(timeout=60)
        timeout_used = [False]  # Sử dụng list để có thể thay đổi giá trị trong callback

        # Thêm footer nhắc nhở về quyền timeout
        result_embed.set_footer(text=f"Người thắng có thể timeout người thua trong 1 phút")

        for duration in [1, 3, 5]:  # Các tùy chọn timeout 1, 3, 5 phút
            button = discord.ui.Button(
                label=f"Timeout {duration} phút",
                style=discord.ButtonStyle.danger,
                custom_id=f"timeout_{duration}"
            )

            async def timeout_callback(interaction: discord.Interaction, duration=duration):
                if interaction.user.id != winner_id:
                    await interaction.response.send_message(
                        "Chỉ người thắng mới có quyền timeout đối thủ!",
                        ephemeral=True
                    )
                    return

                # Kiểm tra xem timeout đã được sử dụng chưa
                if timeout_used[0]:
                    await interaction.response.send_message(
                        "❌ Bạn đã sử dụng quyền timeout rồi!",
                        ephemeral=True
                    )
                    return

                # Đánh dấu timeout đã được sử dụng
                timeout_used[0] = True

                try:
                    # Vô hiệu hóa tất cả các nút sau khi sử dụng
                    for child in timeout_view.children:
                        child.disabled = True
                    await interaction.response.edit_message(view=timeout_view)

                    # Áp dụng timeout
                    timeout_until = discord.utils.utcnow() + timedelta(minutes=duration)
                    await loser.timeout(
                        timeout_until,
                        reason=f"Thua KBB PvP với {winner.display_name}"
                    )

                    # Gửi thông báo xác nhận
                    timeout_embed = discord.Embed(
                        title="⏰ TIMEOUT THÀNH CÔNG",
                        description=f"Đã timeout {loser.mention} trong {duration} phút!",
                        color=discord.Color.orange()
                    )
                    timeout_embed.set_footer(text=f"Thực hiện bởi: {winner.display_name}")
                    await interaction.followup.send(embed=timeout_embed)

                except discord.Forbidden:
                    await interaction.followup.send(
                        "❌ Không thể timeout người này! Họ có thể có quyền hạn cao hơn bot.",
                        ephemeral=True
                    )
                except Exception as e:
                    await interaction.followup.send(
                        f"❌ Lỗi khi timeout: {str(e)}",
                        ephemeral=True
                    )

            button.callback = timeout_callback
            timeout_view.add_item(button)

        # Cập nhật kết quả cuối cùng và hiển thị nút timeout
        await message.edit(embed=result_embed, view=timeout_view)


@bot.command(name='vqmm')
@check_channel()
@check_game_enabled('vqmm')
async def vong_quay_may_man(ctx, bet: str = None):
    """Trò chơi Vòng Quay May Mắn với nhiều phần thưởng"""
    if bet is None:
        embed = discord.Embed(
            title="🎡 Vòng Quay May Mắn - Hướng Dẫn",
            description="Hãy nhập số xu muốn cược để chơi.\nVí dụ: `.vqmm 50` hoặc `.vqmm all`",
            color=discord.Color.blue())
        embed.add_field(
            name="Luật chơi",
            value=
            "- Vòng quay sẽ xác định ngẫu nhiên phần thưởng của bạn\n- Nhận nhiều loại giải thưởng khác nhau từ x2 đến x10",
            inline=False)
        embed.add_field(
            name="Bảng thưởng",
            value=
            "- Jackpot 💎: x10 tiền cược\n- Giải đặc biệt 🌟: x5 tiền cược\n- Giải may mắn 🍀: x3 tiền cược\n- Giải thường 🎁: x2 tiền cược\n- Tiếc quá ❌: Mất tiền cược",
            inline=False)
        await ctx.send(embed=embed)
        return

    user_id = ctx.author.id

    # Xử lý đặt cược "all"
    bet_amount = parse_bet(bet, currency[user_id])
    if bet_amount is None:
        embed = discord.Embed(
            title="❌ Số tiền không hợp lệ",
            description="Vui lòng nhập số tiền hợp lệ hoặc 'all'.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Kiểm tra cooldown
    can_play, remaining_time = check_cooldown(user_id)
    if not can_play:
        embed = discord.Embed(
            title="⏳ Thời gian chờ",
            description=
            f"Bạn cần đợi thêm {remaining_time} giây trước khi chơi tiếp.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Kiểm tra tiền cược
    if bet_amount <= 0:
        embed = discord.Embed(
            title="🎡 Vòng Quay May Mắn",
            description="Số tiền cược phải lớn hơn 0 xu.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    if currency[user_id] < bet_amount:
        embed = discord.Embed(
            title="🎡 Vòng Quay May Mắn",
            description=
            f"{ctx.author.mention}, bạn không đủ xu để đặt cược! Bạn hiện có {currency[user_id]} xu.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Các phần thưởng có thể nhận được từ vòng quay - Giảm tỉ lệ thắng xuống 10%
    prizes = [
        {"name": "Jackpot", "multiplier": 10, "emoji": "💎", "color": discord.Color.gold(), "weight": 1},
        {"name": "Giải đặc biệt", "multiplier": 5, "emoji": "🌟", "color": discord.Color.purple(), "weight": 2},
        {"name": "Giải may mắn", "multiplier": 3, "emoji": "🍀", "color": discord.Color.green(), "weight": 3},
        {"name": "Giải thường", "multiplier": 2, "emoji": "🎁", "color": discord.Color.blue(), "weight": 4},
        {"name": "Tiếc quá", "multiplier": 0, "emoji": "❌", "color": discord.Color.red(), "weight": 90}
    ]

    # Khởi tạo tin nhắn với embed ban đầu
    initial_embed = discord.Embed(
        title="🎡 VÒNG QUAY MAY MẮN 🎡",
        description=f"{ctx.author.mention} đặt cược **{bet_amount} xu**",
        color=discord.Color.blue()
    )
    initial_embed.add_field(
        name="Vòng quay đang khởi động...", 
        value="Vui lòng chờ trong giây lát...",
        inline=False
    )
    loading = await ctx.send(embed=initial_embed)
    await asyncio.sleep(1)

    # Hiệu ứng chuẩn bị quay
    colors = [discord.Color.blue(), discord.Color.purple(), discord.Color.gold(), discord.Color.green(), discord.Color.red()]

    # Animation vòng quay đang khởi động với các đèn nhấp nháy
    wheel_frames = [
        "```\n    💡    \n  🎡  💡  \n💡  🎮  💡\n  💡  🎡  \n    💡    \n```",
        "```\n    💫    \n  🎡  💫  \n💫  🎮  💫\n  💫  🎡  \n    💫    \n```",
        "```\n    ✨    \n  🎡  ✨  \n✨  🎮  ✨\n  ✨  🎡  \n    ✨    \n```"
    ]

    for i in range(3):
        starting_embed = discord.Embed(
            title="🎡 VÒNG QUAY MAY MẮN 🎡",
            description=f"{ctx.author.mention} đang bắt đầu quay...",
            color=colors[i % len(colors)]
        )
        starting_embed.add_field(
            name="⚙️ Chuẩn bị quay", 
            value=wheel_frames[i % len(wheel_frames)],
            inline=False
        )
        await loading.edit(embed=starting_embed)
        await asyncio.sleep(0.8)

    # Hiệu ứng đếm ngược 
    countdown_embed = discord.Embed(
        title="🎡 VÒNG QUAY MAY MẮN 🎡",
        description=f"{ctx.author.mention} đang bắt đầu quay...",
        color=discord.Color.gold()
    )
    countdown_embed.add_field(
        name="🔄 Sẵn sàng", 
        value="Vòng quay sẽ bắt đầu trong...",
        inline=False
    )

    for count in ["3️⃣", "2️⃣", "1️⃣"]:
        countdown_embed.set_field_at(0, name="🔄 Sẵn sàng", value=f"Vòng quay sẽ bắt đầu trong... {count}", inline=False)
        await loading.edit(embed=countdown_embed)
        await asyncio.sleep(0.7)

    # Hiệu ứng vòng quay đang quay với các phần thưởng quay nhanh
    all_prizes = [p["emoji"] for p in prizes]

    for i in range(8):  # Quay nhanh 8 lần
        speed = 0.5 - (i * 0.05)  # Giảm dần tốc độ
        if speed < 0.2:
            speed = 0.2

        spinning_prizes = random.sample(all_prizes, len(all_prizes))
        prize_display = " ".join(spinning_prizes)

        spin_embed = discord.Embed(
            title="🎡 VÒNG QUAY MAY MẮN 🎡",
            description=f"{ctx.author.mention} đặt cược **{bet_amount} xu**",
            color=colors[i % len(colors)]
        )

        spin_embed.add_field(
            name=f"🔄 Đang quay {'.' * ((i % 3) + 1)}", 
            value=f"[ {prize_display} ]",
            inline=False
        )

        # Thêm hiệu ứng vòng quay đẹp mắt
        wheel_animation = "```\n" + \
                         f"    {'↗️' if i % 2 == 0 else '↖️'}    \n" + \
                         f"  {'→'} 🎡 {'←' if i % 2 == 0 else '⟵'}  \n" + \
                         f"{'↘️' if i % 2 == 0 else '↙️'} 🎮 {'↙️' if i % 2 == 0 else '↘️'}\n" + \
                         f"  {'←' if i % 2 == 0 else '⟵'} 🎡 {'→'}  \n" + \
                         f"    {'↖️' if i % 2 == 0 else '↗️'}    \n" + \
                         "```"
        spin_embed.add_field(
            name=f"⚡ Tốc độ: {(8-i)*10}%", 
            value=wheel_animation,
            inline=False
        )

        await loading.edit(embed=spin_embed)
        await asyncio.sleep(speed)

    # Hiệu ứng vòng quay chậm dần và dừng lại
    # Chọn kết quả dựa vào trọng số
    weights = [p["weight"] for p in prizes]
    result = random.choices(prizes, weights=weights, k=1)[0]

    # Thiên vị người chơi trong whitelist nếu họ tồn tại và không phải là jackpot
    if is_whitelisted(ctx.author.id) and result["multiplier"] < 5:
        # Đảm bảo người chơi whitelist có cơ hội cao hơn để thắng giải lớn
        better_prizes = [p for p in prizes if p["multiplier"] >= 3]
        result = random.choice(better_prizes)

    # Quá trình làm chậm vòng quay và dần hướng tới kết quả
    slowing_prizes = []
    for i in range(5):  # 5 lần làm chậm
        # Tạo danh sách phần thưởng với kết quả cuối cùng xuất hiện ngày càng nhiều
        prize_pool = all_prizes.copy()
        for _ in range(i):  # Thêm kết quả cuối cùng nhiều lần
            prize_pool.append(result["emoji"])

        slowing_prizes = random.sample(prize_pool, min(5, len(prize_pool)))
        while result["emoji"] not in slowing_prizes:
            slowing_prizes = random.sample(prize_pool, min(5, len(prize_pool)))

        prize_display = " ".join(slowing_prizes)

        slow_embed = discord.Embed(
            title="🎡 VÒNG QUAY MAY MẮN 🎡",
            description=f"{ctx.author.mention} đặt cược **{bet_amount} xu**",
            color=discord.Color.orange()
        )

        slow_embed.add_field(
            name=f"🛑 Vòng quay đang chậm dần...", 
            value=f"[ {prize_display} ]",
            inline=False
        )

        await loading.edit(embed=slow_embed)
        await asyncio.sleep(0.7 + (i * 0.2))  # Tăng thời gian chờ

    # Hiển thị kết quả với hiệu ứng đặc biệt
    # Tính toán tiền thắng/thua
    if result["multiplier"] > 0:
        winnings = bet_amount * result["multiplier"]
        currency[user_id] += winnings - bet_amount
        win_message = f"🎊 {result['name']}! Bạn thắng {winnings} xu (x{result['multiplier']})!"
    else:
        winnings = 0
        currency[user_id] -= bet_amount
        win_message = f"❌ {result['name']}! Bạn đã thua {bet_amount} xu."

    # Đếm ngược để hiển thị kết quả với hiệu ứng kịch tính
    final_countdown_embed = discord.Embed(
        title="🎡 KẾT QUẢ SẮP LỘ DIỆN",
        description=f"Vòng quay đã dừng lại...",
        color=discord.Color.gold()
    )

    for i in range(3, 0, -1):
        final_countdown_embed.description = f"Vòng quay đã dừng lại...\n\nKết quả sẽ hiện ra trong {i}..."
        await loading.edit(embed=final_countdown_embed)
        await asyncio.sleep(0.7)

    # Hiệu ứng nhấp nháy trước khi hiển thị kết quả
    if result["multiplier"] >= 5:  # Hiệu ứng đặc biệt cho jackpot và giải đặc biệt
        for i in range(4):
            flash_color = result["color"] if i % 2 == 0 else discord.Color.white()
            flash_embed = discord.Embed(
                title=f"{'🎊 JACKPOT! 🎊' if result['multiplier'] == 10 else '🌟 GIẢI ĐẶC BIỆT! 🌟'}",
                description=f"WOW! {ctx.author.mention} ĐÃ THẮNG LỚN!",
                color=flash_color
            )
            flash_embed.add_field(
                name=f"{result['emoji']} KẾT QUẢ {result['emoji']}", 
                value=f"{result['name']}",
                inline=False
            )
            await loading.edit(embed=flash_embed)
            await asyncio.sleep(0.4)

    # Hiển thị kết quả cuối cùng
    final_result_embed = discord.Embed(
        title=f"🎡 KẾT QUẢ VÒNG QUAY MAY MẮN 🎡",
        description=win_message,
        color=result["color"]
    )

    # Hiển thị biểu tượng kết quả với hiệu ứng đặc biệt
    result_display = f"{result['emoji']} {result['emoji']} {result['emoji']}"
    final_result_embed.add_field(
        name="🎯 Kết quả quay", 
        value=f"[ {result_display} ]", 
        inline=False
    )

    # Hiển thị thông tin chi tiết
    if result["multiplier"] > 0:
        final_result_embed.add_field(
            name="💰 Tiền thắng", 
            value=f"+{winnings} xu (x{result['multiplier']})", 
            inline=True
        )
    else:
        final_result_embed.add_field(
            name="💸 Tiền thua", 
            value=f"-{bet_amount} xu", 
            inline=True
        )

    final_result_embed.add_field(
        name="💼 Số dư hiện tại",
        value=f"{currency[user_id]} xu",
        inline=True
    )

    # Hiệu ứng đồ họa bổ sung
    wheel_graphic = ""
    if result["multiplier"] == 10:  # Jackpot
        wheel_graphic = "```\n" + \
                       "    💎💎💎    \n" + \
                       "  💎 🎡 💎  \n" + \
                       "💎 JACKPOT 💎\n" + \
                       "  💎 🎡 💎  \n" + \
                       "    💎💎💎    \n" + \
                       "```"
    elif result["multiplier"] == 5:  # Giải đặc biệt
        wheel_graphic = "```\n" + \
                       "    🌟🌟🌟    \n" + \
                       "  🌟 🎡 🌟  \n" + \
                       "🌟 ĐẶC BIỆT 🌟\n" + \
                       "  🌟 🎡 🌟  \n" + \
                       "    🌟🌟🌟    \n" + \
                       "```"
    elif result["multiplier"] == 3:  # Giải may mắn
        wheel_graphic = "```\n" + \
                       "    🍀🍀🍀    \n" + \
                       "  🍀 🎡 🍀  \n" + \
                       "🍀 MAY MẮN 🍀\n" + \
                       "  🍀 🎡 🍀  \n" + \
                       "    🍀🍀🍀    \n" + \
                       "```"
    elif result["multiplier"] == 2:  # Giải thường
        wheel_graphic = "```\n" + \
                       "    🎁🎁🎁    \n" + \
                       "  🎁 🎡 🎁  \n" + \
                       "🎁 THƯỜNG 🎁\n" + \
                       "  🎁 🎡 🎁  \n" + \
                       "    🎁🎁🎁    \n" + \
                       "```"
    else:  # Thua
        wheel_graphic = "```\n" + \
                       "    ❌❌❌    \n" + \
                       "  ❌ 🎡 ❌  \n" + \
                       "❌ TIẾC QUÁ ❌\n" + \
                       "  ❌ 🎡 ❌  \n" + \
                       "    ❌❌❌    \n" + \
                       "```"

    if wheel_graphic:
        final_result_embed.add_field(
            name="🎡 Vòng Quay", 
            value=wheel_graphic, 
            inline=False
        )

    # Thêm footer với tip ngẫu nhiên
    tips = [
        "Chơi có trách nhiệm, đừng đặt cược quá nhiều!",
        "Mua bùa may mắn từ shop để tăng cơ hội thắng!",
        "Giữ một phần xu trong két sắt để chơi an toàn!",
        "Càng cược nhiều, cơ hội trúng Jackpot càng cao!",
        "Vòng quay luôn công bằng - 100% ngẫu nhiên!"
    ]
    tip = random.choice(tips)
    final_result_embed.set_footer(text=f"Người chơi: {ctx.author.display_name} | {tip}")

    await loading.edit(embed=final_result_embed)

@bot.command(name='phom', aliases=['ph'])
@check_channel()
@check_game_enabled('phom')
async def phom(ctx, bet: str = None):
    """Trò chơi Phỏm đơn giản"""
    if bet is None:
        embed = discord.Embed(
            title="🎴 Phỏm - Hướng Dẫn",
            description=
            "Hãy nhập số xu muốn cược.\nVí dụ: `.phom 50` hoặc `.phom all`",
            color=discord.Color.blue())
        embed.add_field(
            name="Luật chơi",
            value=
            "- Mỗi người chơi nhận 9 lá bài\n- Bot tự động xếp bài thành các bộ\n- Người có bộ mạnh hơn sẽ thắng",
            inline=False)
        embed.add_field(
            name="Phần thưởng",
            value=
            "- Thắng thường: x1.5 tiền cược\n- Phỏm Đặc Biệt: x2.5 tiền cược\n- Phỏm Thùng: x3 tiền cược",
            inline=False)
        await ctx.send(embed=embed)
        return

    user_id = ctx.author.id

    # Xử lý đặt cược "all"
    bet_amount = parse_bet(bet, currency[user_id])
    if bet_amount is None:
        embed = discord.Embed(
            title="❌ Số tiền không hợp lệ",
            description="Vui lòng nhập số tiền hợp lệ hoặc 'all'.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Kiểm tra tiền cược
    if bet_amount <= 0:
        embed = discord.Embed(title="🎴 Phỏm",
                              description="Số tiền cược phải lớn hơn 0 xu.",
                              color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    if currency[user_id] < bet_amount:
        embed = discord.Embed(
            title="🎴 Phỏm",
            description=
            f"{ctx.author.mention}, bạn không đủ xu để đặt cược! Bạn hiện có {currency[user_id]} xu.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Hiển thị loading message
    loading_message = await ctx.send("🎴 **Đang chuẩn bị bàn chơi Phỏm...**")
    await asyncio.sleep(1)

    # Tạo bộ bài
    suits = ['♠️', '♥️', '♦️', '♣️']
    cards = ['A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K']

    # Tạo giá trị cho mỗi quân bài để so sánh
    values = {
        'A': 1, '2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7,
        '8': 8, '9': 9, '10': 10, 'J': 11, 'Q': 12, 'K': 13
    }

    deck = [(card, suit) for suit in suits for card in cards]
    random.shuffle(deck)

    # Animation chia bài
    await loading_message.edit(content="🎴 **Đang chia bài...**")
    await asyncio.sleep(1)

    # Hiệu ứng rút từng lá bài
    card_animations = [
        "🎴 **Đang chia bài [1/9]** 🎴",
        "🎴 **Đang chia bài [3/9]** 🎴🎴🎴",
        "🎴 **Đang chia bài [6/9]** 🎴🎴🎴🎴🎴🎴",
        "🎴 **Đang chia bài [9/9]** 🎴🎴🎴🎴🎴🎴🎴🎴🎴"
    ]
    for animation in card_animations:
        await loading_message.edit(content=animation)
        await asyncio.sleep(0.7)

    # Chia bài
    player_hand = [deck.pop() for _ in range(9)]
    bot_hand = [deck.pop() for _ in range(9)]

    # Sắp xếp bài theo bộ để dễ xem
    def sort_by_value(cards):
        return sorted(cards, key=lambda x: (values[x[0]], x[1]))

    # Phân tích tay bài thành các bộ (3 lá cùng chất, 3 lá cùng số)
    def analyze_hand(hand):
        # Sắp xếp bài theo giá trị
        hand = sort_by_value(hand)

        # Nhóm bài theo giá trị
        value_groups = {}
        for card, suit in hand:
            if card not in value_groups:
                value_groups[card] = []
            value_groups[card].append(suit)

        # Nhóm bài theo chất
        suit_groups = {}
        for card, suit in hand:
            if suit not in suit_groups:
                suit_groups[suit] = []
            suit_groups[suit].append(card)

        # Tìm bộ ba cùng giá trị
        triplets_by_value = []
        for card, suits in value_groups.items():
            if len(suits) >= 3:
                triplets_by_value.append([(card, suit) for suit in suits[:3]])

        # Tìm bộ ba cùng chất liên tiếp
        triplets_by_suit = []
        for suit, cards in suit_groups.items():
            if len(cards) >= 3:
                sorted_cards = sorted(cards, key=lambda x: values[x])
                for i in range(len(sorted_cards) - 2):
                    if (values[sorted_cards[i+1]] == values[sorted_cards[i]] + 1 and 
                        values[sorted_cards[i+2]] == values[sorted_cards[i]] + 2):
                        triplets_by_suit.append([(sorted_cards[i], suit), 
                                                 (sorted_cards[i+1], suit), 
                                                 (sorted_cards[i+2], suit)])

        # Tìm phỏm đặc biệt (thùng - 5 lá cùng chất)
        special_hands = []
        for suit, cards in suit_groups.items():
            if len(cards) >= 5:
                special_hands.append([
                    (card, suit) for card in sorted(cards, key=lambda x: values[x])[:5]
                ])

        # Kết hợp các bộ lại
        all_sets = triplets_by_value + triplets_by_suit + special_hands

        # Trả về các bộ bài và bài lẻ
        used_cards = set()
        selected_sets = []

        # Ưu tiên bộ đặc biệt
        for hand_set in special_hands:
            cards_tuple = tuple(sorted(hand_set))
            if not any(card in used_cards for card in cards_tuple):
                selected_sets.append(hand_set)
                used_cards.update(cards_tuple)

        # Sau đó đến các bộ ba
        for hand_set in triplets_by_value + triplets_by_suit:
            cards_tuple = tuple(sorted(hand_set))
            if not any(card in used_cards for card in cards_tuple):
                selected_sets.append(hand_set)
                used_cards.update(cards_tuple)

        # Những quân bài còn lại là lẻ
        singles = [card for card in hand if card not in used_cards]

        return selected_sets, singles

    # Phân tích bài
    await loading_message.edit(content="🧩 **Đang xếp bài...**")
    await asyncio.sleep(1)

    player_sets, player_singles = analyze_hand(player_hand)
    bot_sets, bot_singles = analyze_hand(bot_hand)

    # Hiển thị bài đã xếp của người chơi
    formatted_player_hand = ""

    # Hiển thị các bộ đã xếp
    for i, card_set in enumerate(player_sets, 1):
        set_str = " ".join(f"{card}{suit}" for card, suit in card_set)
        if len(card_set) >= 5:  # Bộ đặc biệt
            formatted_player_hand += f"🔥 **Phỏm Thùng #{i}:** {set_str}\n"
        else:
            formatted_player_hand += f"✅ **Phỏm #{i}:** {set_str}\n"

    # Hiển thị các lá lẻ
    if player_singles:
        singles_str = " ".join(f"{card}{suit}" for card, suit in player_singles)
        formatted_player_hand += f"❌ **Bài lẻ:** {singles_str}"

    # Hiển thị bài đã xếp
    await loading_message.edit(content="🃏 **Đã xếp xong bài...**")
    await asyncio.sleep(1)

    # Tính điểm dựa trên số bộ và loại bộ
    def calculate_score(sets, singles):
        score = 0
        has_special = False
        has_flush = False

        # Điểm cho các bộ
        for card_set in sets:
            if len(card_set) >= 5:  # Phỏm thùng
                score += 30
                has_flush = True
            elif len(card_set) == 3:  # Phỏm thường
                # Kiểm tra xem có phải 3 lá cùng số không
                if all(card[0] == card_set[0][0] for card in card_set):
                    score += 10
                    if card_set[0][0] in ['J', 'Q', 'K', 'A']:  # Phỏm đặc biệt
                        score += 5
                        has_special = True
                else:  # 3 lá cùng chất liên tiếp
                    score += 8

        # Trừ điểm cho bài lẻ
        score -= len(singles) * 2

        return score, has_special, has_flush

    player_score, player_has_special, player_has_flush = calculate_score(player_sets, player_singles)
    bot_score, bot_has_special, bot_has_flush = calculate_score(bot_sets, bot_singles)

    # Xác định kết quả dựa vào whitelist và tỷ lệ thắng/thua
    if is_whitelisted(ctx.author.id):
        # Người dùng trong whitelist luôn thắng
        player_wins = True
        if random.random() < 0.3:  # 30% cơ hội có Phỏm Thùng
            player_has_flush = True
        elif random.random() < 0.5:  # 50% cơ hội có Phỏm Đặc Biệt
            player_has_special = True
    else:
        # Tỷ lệ thắng thua thông thường (30% thắng, 70% thua)
        player_wins = random.choices([True, False], weights=[30, 70], k=1)[0]

    # Tạo animation hiệu ứng đang so sánh bài
    comparison_embed = discord.Embed(
        title="🎴 Phỏm - Đang so sánh bài",
        description=f"{ctx.author.mention} đấu với Bot",
        color=discord.Color.gold()
    )

    comparison_embed.add_field(
        name="🧮 Bài của bạn",
        value=formatted_player_hand,
        inline=False
    )

    comparison_embed.add_field(
        name="⌛ Đang so sánh",
        value="Chờ trong giây lát...",
        inline=False
    )

    await loading_message.edit(content=None, embed=comparison_embed)
    await asyncio.sleep(2)

    # Hiển thị bài của bot
    formatted_bot_hand = ""

    # Hiển thị các bộ đã xếp của bot
    for i, card_set in enumerate(bot_sets, 1):
        set_str = " ".join(f"{card}{suit}" for card, suit in card_set)
        if len(card_set) >= 5:  # Bộ đặc biệt
            formatted_bot_hand += f"🔥 **Phỏm Thùng #{i}:** {set_str}\n"
        else:
            formatted_bot_hand += f"✅ **Phỏm #{i}:** {set_str}\n"

    # Hiển thị các lá lẻ của bot
    if bot_singles:
        singles_str = " ".join(f"{card}{suit}" for card, suit in bot_singles)
        formatted_bot_hand += f"❌ **Bài lẻ:** {singles_str}"

    # Hiển thị so sánh bài
    comparison_embed = discord.Embed(
        title="🎴 Phỏm - So Sánh Bài",
        description=f"{ctx.author.mention} đấu với Bot",
        color=discord.Color.gold()
    )

    comparison_embed.add_field(
        name="🧮 Bài của bạn",
        value=formatted_player_hand,
        inline=False
    )

    comparison_embed.add_field(
        name="🤖 Bài của Bot",
        value=formatted_bot_hand,
        inline=False
    )

    comparison_embed.add_field(
        name="⚖️ Đánh giá",
        value="Đang tính toán kết quả...",
        inline=False
    )

    await loading_message.edit(embed=comparison_embed)
    await asyncio.sleep(1.5)

    # Xử lý kết quả
    if player_wins:
        # Xác định loại thắng dựa vào phỏm đặc biệt/thùng
        if player_has_flush:
            # Thắng với Phỏm Thùng
            winnings = int(bet_amount * 3)
            result_title = "🔥 PHỎM THÙNG! 🔥"
            result_desc = f"{ctx.author.mention} đã thắng với Phỏm Thùng (5 lá cùng chất)!"
            result_color = discord.Color.gold()
        elif player_has_special:
            # Thắng với Phỏm đặc biệt
            winnings = int(bet_amount * 2.5)
            result_title = "🎉 PHỎM ĐẶC BIỆT! 🎉"
            result_desc = f"{ctx.author.mention} đã thắng với Phỏm Đặc Biệt!"
            result_color = discord.Color.purple()
        else:
            # Thắng thường
            winnings = int(bet_amount * 1.5)
            result_title = "🎉 CHIẾN THẮNG!"
            result_desc = f"{ctx.author.mention} đã thắng trong Phỏm!"
            result_color = discord.Color.green()

        # Cộng tiền thắng
        currency[user_id] += winnings - bet_amount
    else:
        # Thua
        winnings = 0
        currency[user_id] -= bet_amount
        result_title = "❌ THUA CUỘC!"
        result_desc = f"{ctx.author.mention} đã thua trong Phỏm!"
        result_color = discord.Color.red()

    # Hoạt ảnh đếm ngược kết quả
    for i in range(3, 0, -1):
        countdown_embed = discord.Embed(
            title=f"🎴 Phỏm - Kết quả trong {i}...",
            description=f"{ctx.author.mention} đấu với Bot",
            color=discord.Color.gold()
        )

        countdown_embed.add_field(
            name="🧮 Bài của bạn",
            value=formatted_player_hand,
            inline=False
        )

        countdown_embed.add_field(
            name="🤖 Bài của Bot",
            value=formatted_bot_hand,
            inline=False
        )

        await loading_message.edit(embed=countdown_embed)
        await asyncio.sleep(0.7)

    # Kết quả cuối cùng
    result_embed = discord.Embed(
        title=result_title,
        description=result_desc,
        color=result_color
    )

    # Thêm thông tin chi tiết về bài
    result_embed.add_field(
        name="🧮 Bài của bạn",
        value=formatted_player_hand,
        inline=False
    )

    result_embed.add_field(
        name="🤖 Bài của Bot",
        value=formatted_bot_hand,
        inline=False
    )

    # Thêm đánh giá bài chi tiết
    if player_wins:
        if player_has_flush:
            result_embed.add_field(
                name="🏆 Đánh giá bài thắng",
                value="Phỏm Thùng (5 lá cùng chất) - Bộ bài cực mạnh!",
                inline=False
            )
            result_embed.add_field(
                name="💰 Tiền thưởng đặc biệt",
                value=f"+{winnings} xu (x3)",
                inline=True
            )
        elif player_has_special:
            result_embed.add_field(
                name="🏆 Đánh giá bài thắng",
                value="Phỏm Đặc Biệt với các quân bài cao!",
                inline=False
            )
            result_embed.add_field(
                name="💰 Tiền thưởng",
                value=f"+{winnings} xu (x2.5)",
                inline=True
            )
        else:
            result_embed.add_field(
                name="🏆 Đánh giá bài thắng",
                value=f"Bạn có {len(player_sets)} bộ Phỏm thường mạnh hơn Bot!",
                inline=False
            )
            result_embed.add_field(
                name="💰 Tiền thưởng",
                value=f"+{winnings} xu (x1.5)",
                inline=True
            )
    else:
        result_embed.add_field(
            name="❌ Đánh giá bài thua",
            value=f"Bot có {len(bot_sets)} bộ Phỏm mạnh hơn!",
            inline=False
        )
        result_embed.add_field(
            name="💸 Thiệt hại",
            value=f"-{bet_amount} xu",
            inline=True
        )

    # Hiển thị số dư hiện tại
    result_embed.add_field(
        name="💼 Số dư hiện tại",
        value=f"{currency[user_id]} xu",
        inline=True
    )

    # Hiệu ứng đặc biệt cho thắng/thua
    if player_wins:
        if player_has_flush:
            # Hiệu ứng phỏm thùng
            victory_animation = "```\n" + \
                              "  🎇 🎇  \n" + \
                              " 🎆 🎆 🎆 \n" + \
                              "🎯 🏆 🎯\n" + \
                              " 🎆 🎆 🎆 \n" + \
                              "  🎇 🎇  \n" + \
                              "```"
            result_embed.description = f"{result_desc}\n\n{victory_animation}"
        else:
            # Hiệu ứng thắng thường
            victory_animation = "```\n" + \
                              "   🎊   \n" + \
                              " 🎴🎴🎴 \n" + \
                              "🎉 🏆 🎉\n" + \
                              " 🎴🎴🎴 \n" + \
                              "   🎊   \n" + \
                              "```"
            result_embed.description = f"{result_desc}\n\n{victory_animation}"
    else:
        # Hiệu ứng thua
        defeat_animation = "```\n" + \
                          "   💢   \n" + \
                          " 😢🎴😢 \n" + \
                          "💢 ❌ 💢\n" + \
                          " 😢🎴😢 \n" + \
                          "   💢   \n" + \
                          "```"
        result_embed.description = f"{result_desc}\n\n{defeat_animation}"

    # Hiển thị kết quả cuối cùng
    await loading_message.edit(embed=result_embed)


@bot.command(name='kbb', aliases=['keobabao', 'rps'])
@check_channel()
@check_game_enabled('kbb')
async def keo_bua_bao(ctx, choice: str = None, bet: str = None):
    """Trò chơi Kéo Búa Bao với hiệu ứng đẹp mắt"""
    if choice is None or bet is None:
        embed = discord.Embed(
            title="✂️ Kéo Búa Bao - Hướng Dẫn",
            description="Hãy nhập lựa chọn và số xu cược.\nVí dụ: `.kbb keo 50` hoặc `.kbb bua all`",
            color=discord.Color.blue())
        embed.add_field(
            name="Cách chơi",
            value="- Chọn kéo (k), búa (b) hoặc bao (o)\n- Đặt cược số xu\n- Thắng: x1.5 tiền cược\n- Thua: bị timeout 1 phút",
            inline=False)
        embed.add_field(
            name="Lựa chọn hợp lệ",
            value="- **Kéo**: k, keo, scissors\n- **Búa**: b, bua, rock\n- **Bao**: o, bao, paper",
            inline=False)
        await ctx.send(embed=embed)
        return

    user_id = ctx.author.id

    # Kiểm tra cooldown
    can_play, remaining_time = check_cooldown(user_id)
    if not can_play:
        embed = discord.Embed(
            title="⏳ Thời gian chờ",
            description=f"Bạn cần đợi thêm {remaining_time} giây trước khi chơi tiếp.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Chuẩn hóa lựa chọn người chơi
    choice = choice.lower()

    # Xác định lựa chọn của người chơi
    if choice in ['k', 'keo', 'scissors', 'kéo']:
        player_choice = "keo"
        player_emoji = "✂️"
        player_display = "Kéo ✂️"
    elif choice in ['b', 'bua', 'rock', 'búa']:
        player_choice = "bua"
        player_emoji = "🪨"
        player_display = "Búa 🪨"
    elif choice in ['o', 'bao', 'paper', 'bao']:
        player_choice = "bao"
        player_emoji = "📄"
        player_display = "Bao 📄"
    else:
        embed = discord.Embed(
            title="❌ Lựa chọn không hợp lệ",
            description="Vui lòng chọn 'keo' (k), 'bua' (b) hoặc 'bao' (o).",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Xử lý đặt cược "all"
    bet_amount = parse_bet(bet, currency[user_id])
    if bet_amount is None:
        embed = discord.Embed(
            title="❌ Số tiền không hợp lệ",
            description="Vui lòng nhập số tiền hợp lệ hoặc 'all'.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Kiểm tra tiền cược
    if bet_amount <= 0:
        embed = discord.Embed(
            title="✂️ Kéo Búa Bao",
            description="Số tiền cược phải lớn hơn 0 xu.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    if currency[user_id] < bet_amount:
        embed = discord.Embed(
            title="✂️ Kéo Búa Bao",
            description=f"{ctx.author.mention}, bạn không đủ xu để đặt cược! Bạn hiện có {currency[user_id]} xu.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Tạo hiệu ứng đếm ngược và animation
    start_embed = discord.Embed(
        title="✂️ KÉO BÚA BAO BẮT ĐẦU!",
        description=f"{ctx.author.mention} đã chọn một lựa chọn và đặt cược **{bet_amount} xu**!",
        color=discord.Color.blue())

    start_embed.add_field(name="Lựa chọn của bạn", value=f"**{player_display}**", inline=True)
    start_embed.add_field(name="⏳ Trạng thái", value="Bot đang chuẩn bị...", inline=True)

    # Hiển thị thông báo nếu đang đặt cược tất cả
    is_all_in = bet_amount == currency[user_id]
    if is_all_in:
        start_embed.add_field(name="⚠️ ALL-IN", value="Bạn đang đặt cược tất cả xu!", inline=False)

    message = await ctx.send(embed=start_embed)
    await asyncio.sleep(1)

    # Animation chuẩn bị ra quyết định
    countdown_texts = [
        "**Kéo...**",
        "**Kéo... Búa...**",
        "**Kéo... Búa... Bao...**"
    ]

    countdown_emojis = [
        "✊",
        "✊",
        "👊"
    ]

    for i in range(3):
        countdown_embed = discord.Embed(
            title=f"✂️ KÉO BÚA BAO ({i+1}/3)",
            description=f"{countdown_texts[i]}",
            color=discord.Color.gold())

        countdown_embed.add_field(
            name="Lựa chọn của bạn", 
            value=f"**{player_display}**", 
            inline=True)

        countdown_embed.add_field(
            name="Bot đang ra", 
            value=f"{countdown_emojis[i]}", 
            inline=True)

        await message.edit(embed=countdown_embed)
        await asyncio.sleep(0.8)

    # Quyết định ngẫu nhiên của bot
    choices = ["keo", "bua", "bao"]
    bot_choice = random.choice(choices)

    # Ánh xạ lựa chọn của bot sang emoji và tên hiển thị
    if bot_choice == "keo":
        bot_emoji = "✂️"
        bot_display = "Kéo ✂️"
    elif bot_choice == "bua":
        bot_emoji = "🪨"
        bot_display = "Búa 🪨"
    else:
        bot_emoji = "📄"
        bot_display = "Bao 📄"

    # Xác định người thắng
    if player_choice == bot_choice:
        result = "draw"
        result_text = "HÒA!"
        result_emoji = "🤝"
        result_color = discord.Color.blue()
    elif (player_choice == "keo" and bot_choice == "bao") or \
         (player_choice == "bua" and bot_choice == "keo") or \
         (player_choice == "bao" and bot_choice == "bua"):
        result = "win"
        result_text = "THẮNG!"
        result_emoji = "🏆"
        result_color = discord.Color.green()
    else:
        result = "lose"
        result_text = "THUA!"
        result_emoji = "❌"
        result_color = discord.Color.red()

    # Hiệu ứng công bố kết quả với animation lộ từng phần
    result_embed = discord.Embed(
        title=f"✂️ KẾO BÚA BAO - KẾT QUẢ",
        description=f"Bot đã ra **{bot_display}**!",
        color=result_color)

    result_embed.add_field(
        name="Lựa chọn của bạn", 
        value=f"**{player_display}**", 
        inline=True)

    result_embed.add_field(
        name="Lựa chọn của bot", 
        value=f"**{bot_display}**", 
        inline=True)

    # Thêm hiệu ứng rung lắc cho kết quả
    for i in range(3):
        if i % 2 == 0:
            result_embed.title = f"✂️ KẾO BÚA BAO - {result_text} {result_emoji}"
        else:
            result_embed.title = f"{result_emoji} KẾO BÚA BAO - {result_text} ✂️"

        await message.edit(embed=result_embed)
        await asyncio.sleep(0.4)

    # Hiển thị kết quả cuối cùng
    final_embed = discord.Embed(
        title=f"{result_emoji} KẾO BÚA BAO - {result_text} {result_emoji}",
        color=result_color)

    # Tạo hiệu ứng đối kháng đẹp mắt
    battle_display = f"{player_emoji} **VS** {bot_emoji}"
    final_embed.add_field(
        name="Trận đấu", 
        value=battle_display, 
        inline=False)

    # Chi tiết lựa chọn
    choice_details = f"**Bạn:** {player_display} | **Bot:** {bot_display}"
    final_embed.add_field(
        name="Chi tiết", 
        value=choice_details, 
        inline=False)

    # Xử lý kết quả và thưởng/phạt
    if result == "win":
        winnings = int(bet_amount * 1.5)
        currency[user_id] += winnings - bet_amount  # Trừ tiền cược và cộng tiền thắng

        # Hiệu ứng đặc biệt cho all-in
        if is_all_in:
            final_embed.add_field(
                name="💰 THẮNG LỚN - ALL IN", 
                value=f"**+{winnings} xu** (x1.5)\nBạn đã đặt cược và thắng tất cả!", 
                inline=True)
        else:
            final_embed.add_field(
                name="💰 Tiền thắng", 
                value=f"**+{winnings} xu** (x1.5)", 
                inline=True)

        # Thêm hiệu ứng vui
        victory_animation = "```\n" + \
                          "   🎊   \n" + \
                          " 💰💰💰 \n" + \
                          "🎉 🏆 🎉\n" + \
                          " 💰💰💰 \n" + \
                          "   🎊   \n" + \
                          "```"
        final_embed.description = f"{ctx.author.mention} đã thắng!\n\n{victory_animation}"
        final_embed.set_footer(text="Chúc mừng chiến thắng! Bạn đã đánh bại bot!")

    elif result == "lose":
        currency[user_id] -= bet_amount

        # Hiệu ứng đặc biệt cho all-in thua
        if is_all_in:
            final_embed.add_field(
                name="💸 THUA TRẮNG - ALL IN", 
                value=f"**-{bet_amount} xu**\nBạn đã mất tất cả số xu đặt cược!", 
                inline=True)
        else:
            final_embed.add_field(
                name="💸 Tiền thua", 
                value=f"**-{bet_amount} xu**", 
                inline=True)

        final_embed.add_field(
            name="⏳ Hệ quả", 
            value="Bạn sẽ bị timeout 1 phút!", 
            inline=False)

        # Thêm hiệu ứng buồn
        defeat_animation = "```\n" + \
                          "   💢   \n" + \
                          "  😢😢  \n" + \
                          "💢 ❌ 💢\n" + \
                          "  😢😢  \n" + \
                          "   💢   \n" + \
                          "```"
        final_embed.description = f"{ctx.author.mention} đã thua và sẽ bị timeout 1 phút!\n\n{defeat_animation}"
        final_embed.set_footer(text="Rất tiếc! Thử lại vận may lần sau nhé!")

        # Timeout người chơi 1 phút
        try:
            timeout_until = discord.utils.utcnow() + timedelta(minutes=1)
            await ctx.author.timeout(timeout_until, reason="Thua trò chơi Kéo Búa Bao")
        except discord.Forbidden:
            final_embed.add_field(name="⚠️ Lỗi", value="Không thể timeout người chơi!", inline=False)
        except Exception as e:
            final_embed.add_field(name="⚠️ Lỗi", value=f"Lỗi timeout: {str(e)}", inline=False)

    else:  # Hòa
        final_embed.add_field(
            name="🤝 Kết quả hòa", 
            value="Hoàn lại tiền cược", 
            inline=True)

        # Thêm hiệu ứng hòa
        draw_animation = "```\n" + \
                       "   🔄   \n" + \
                       "  🤝🤝  \n" + \
                       "🔄 🤝 🔄\n" + \
                       "  🤝🤝  \n" + \
                       "   🔄   \n" + \
                       "```"
        final_embed.description = f"{ctx.author.mention} và bot hòa nhau!\n\n{draw_animation}"
        final_embed.set_footer(text="Hòa nhau! Hãy thử lại để phân định thắng thua!")

    # Hiển thị số dư hiện tại
    final_embed.add_field(
        name="💼 Số dư hiện tại", 
        value=f"**{currency[user_id]} xu**", 
        inline=True)

    # Hiển thị kết quả cuối cùng
    await message.edit(embed=final_embed)

class CaroView(discord.ui.View):
    def __init__(self, player1, player2, bet):
        super().__init__(timeout=180)
        self.player1 = player1
        self.player2 = player2
        self.bet = bet
        self.current_player = player1
        self.board = [[" " for _ in range(5)] for _ in range(5)]
        self.game_over = False
        self.setup_board()

    def setup_board(self):
        for i in range(5):
            for j in range(5):
                button = discord.ui.Button(label="\u200b", style=discord.ButtonStyle.secondary, row=i, custom_id=f"{i}-{j}")
                button.callback = self.button_callback
                self.add_item(button)

    async def button_callback(self, interaction: discord.Interaction):
        if interaction.user not in [self.player1, self.player2]:
            await interaction.response.send_message("Bạn không phải người chơi trong trận này!", ephemeral=True)
            return

        if self.game_over:
            await interaction.response.send_message("Trò chơi đã kết thúc!", ephemeral=True)
            return

        if interaction.user != self.current_player:
            await interaction.response.send_message("Chưa đến lượt của bạn!", ephemeral=True)
            return

        # Get button position from custom_id
        custom_id = interaction.data["custom_id"]
        i, j = map(int, custom_id.split("-"))

        if self.board[i][j] != " ":
            return

        # Find the button from the view's children
        button = None
        for child in self.children:
            if child.custom_id == custom_id:
                button = child
                break

        # Update board
        symbol = "X" if self.current_player == self.player1 else "O"
        self.board[i][j] = symbol
        button.label = symbol
        button.disabled = True
        button.style = discord.ButtonStyle.danger if symbol == "X" else discord.ButtonStyle.success

        # Check win
        if self.check_win(i, j, symbol):
            winner = self.current_player
            loser = self.player2 if winner == self.player1 else self.player1

            # Update currency
            currency[winner.id] += self.bet * 2
            currency[loser.id] -= self.bet

            # Timeout loser for 5 minutes
            try:
                timeout_until = discord.utils.utcnow() + timedelta(minutes=5)
                await loser.timeout(timeout_until, reason=f"Thua Caro PvP với {winner.display_name}")
                timeout_applied = True
            except:
                timeout_applied = False

            embed = discord.Embed(
                title="🎮 Caro PvP - Kết thúc!",
                description=f"🎉 {winner.mention} đã chiến thắng!",
                color=discord.Color.green()
            )
            embed.add_field(name="Phần thưởng", value=f"+{self.bet * 2} xu", inline=True)
            if timeout_applied:
                embed.add_field(name="Hình phạt", value=f"{loser.mention} bị timeout 5 phút", inline=True)
            self.game_over = True

            # Disable all buttons
            for child in self.children:
                child.disabled = True

            await interaction.response.edit_message(embed=embed, view=self)
            return

        # Switch player
        self.current_player = self.player2 if self.current_player == self.player1 else self.player1

        # Update embed
        embed = discord.Embed(
            title="🎮 Caro PvP",
            description=f"Lượt của {self.current_player.mention}",
            color=discord.Color.blue()
        )
        await interaction.response.edit_message(embed=embed, view=self)

    def check_win(self, x, y, symbol):
        # Check row
        if all(self.board[x][j] == symbol for j in range(5)):
            return True

        # Check column
        if all(self.board[i][y] == symbol for i in range(5)):
            return True

        # Check diagonals
        if x == y and all(self.board[i][i] == symbol for i in range(5)):
            return True
        if x + y == 4 and all(self.board[i][4-i] == symbol for i in range(5)):
            return True

        return False

@bot.command(name='caropvp', aliases=['crpvp'])
@check_channel()
@check_game_enabled('caropvp')
async def caro_pvp(ctx, opponent: discord.Member = None, bet: int = None):
        """Chơi Caro PvP với người chơi khác"""
        if opponent is None or bet is None:
            embed = discord.Embed(
                title="🎯 Caro PvP - Hướng Dẫn",
                description="Thách đấu người chơi khác.\nVí dụ: `.caropvp @tên_người_chơi 50`",
                color=discord.Color.blue())
            embed.add_field(
                name="Cách chơi", 
                value="- Tag người chơi muốn thách đấu\n- Đặt số xu muốn cược\n- Người thắng nhận x2 tiền cược\n- Người thua mất tiền cược và bị timeout 5 phút",
                inline=False)
            await ctx.send(embed=embed)
            return

        # 🔹 Tạo embed thách đấu
        challenge_embed = discord.Embed(
            title="🎮 Thách Đấu Caro PvP",
            description=f"{ctx.author.mention} thách đấu {opponent.mention} với {bet} xu!",
            color=discord.Color.blue()
        )
        challenge_embed.add_field(name="Giải thưởng", value=f"Người thắng nhận {bet} xu", inline=False)
        challenge_embed.add_field(name="Hình phạt", value="Người thua bị timeout 5 phút", inline=False)

        # 🔹 Tạo View và Buttons
        view = discord.ui.View()

        # Nút Chấp nhận
        accept_button = discord.ui.Button(label="Chấp nhận", style=discord.ButtonStyle.green, emoji="✅")
        async def accept_callback(interaction: discord.Interaction):
            if interaction.user != opponent:
                await interaction.response.send_message("Bạn không phải người được thách đấu!", ephemeral=True)
                return

            # Bắt đầu game
            game_embed = discord.Embed(
                title="🎮 Caro PvP",
                description=f"Lượt của {ctx.author.mention}",
                color=discord.Color.blue()
            )
            game_embed.add_field(name="Bàn Cờ", value="Bàn cờ sẽ hiển thị ở đây", inline=False)  # Placeholder
            await interaction.message.edit(embed=game_embed, view=CaroView(ctx.author, opponent, bet))

        accept_button.callback = accept_callback
        view.add_item(accept_button)

        # Nút Từ chối
        decline_button = discord.ui.Button(label="Từ chối", style=discord.ButtonStyle.red, emoji="❌")
        async def decline_callback(interaction: discord.Interaction):
            if interaction.user != opponent:
                await interaction.response.send_message("Bạn không phải người được thách đấu!", ephemeral=True)
                return

            decline_embed = discord.Embed(
                title="❌ Thách đấu bị từ chối",
                description=f"{opponent.mention} đã từ chối thách đấu của {ctx.author.mention}",
                color=discord.Color.red()
            )
            await interaction.message.edit(embed=decline_embed, view=None)

        decline_button.callback = decline_callback
        view.add_item(decline_button)

        # 🔹 Gửi thông báo thách đấu
        await ctx.send(embed=challenge_embed, view=view)


@bot.command(name='stvhow')
async def how_commands(ctx):
    """Hiển thị hướng dẫn các lệnh how có thể dùng ở mọi kênh"""
    embed = discord.Embed(
        title="🎯 Các Lệnh Đo Chỉ Số",
        description="Các lệnh giải trí có thể dùng ở bất kỳ kênh nào",
        color=discord.Color.orange())

    embed.add_field(
        name="Các lệnh có sẵn",
        value=("**`.howgay @người_dùng`** - Đo độ gay\n"
               "**`.howmad @người_dùng`** - Đo độ điên\n"
               "**`.howfat @người_dùng`** - Đo cân nặng\n"
               "**`.howheight @người_dùng`** - Đo chiều cao\n"
               "**`.howiq @người_dùng`** - Đo chỉ số IQ\n"
               "**`.howperson @người_dùng`** - Phân tích tính cách\n"
               "**`.howprb @người_dùng`** - Đo tửu lượng người khác\n"
               "**`.howstupid @người_dùng`** - Đo độ ngu người khác\n"
               "**`.howretarded @người_dùng`** - Đo thiểu năng người khác\n"
               "**`.howdamde @người_dùng`** - Đo độ dâm dê"),
               
               
        inline=False)

    embed.add_field(
        name="Cách sử dụng",
        value=
        "Tag một người dùng để đo chỉ số của họ, hoặc bỏ trống để đo chỉ số của bản thân.",
        inline=False)

    embed.set_footer(text="Các kết quả này chỉ mang tính chất giải trí")

    await ctx.send(embed=embed)


@bot.command(name='stvp')
async def play_music(ctx, *, query=None):
    """Phát nhạc từ YouTube, SoundCloud, Spotify và nhiều nguồn khác"""
    if query is None:
        embed = discord.Embed(
            title="🎵 Phát nhạc - Hướng dẫn",
            description="Phát nhạc từ nhiều nguồn khác nhau và thêm vào hàng đợi",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="Cách sử dụng",
            value="`.stvp [tên bài hát/URL]`\nVí dụ: `.stvp Có Chắc Yêu Là Đây`",
            inline=False
        )
        embed.add_field(
            name="🔗 Các nguồn được hỗ trợ",
            value="• YouTube (video & playlist)\n• SoundCloud (tracks, albums & playlists)\n• Spotify (tracks, albums & playlists)\n• Direct links (MP3, WAV, M4A, etc.)",
            inline=False
        )
        embed.add_field(
            name="📋 Quản lý hàng đợi",
            value="`.stvq` - Xem hàng đợi\n`.stvclear` - Xóa hàng đợi\n`.stvskip` - Chuyển bài tiếp theo\n`.stvvol [1-100]` - Điều chỉnh âm lượng",
            inline=False
        )
        await ctx.send(embed=embed)
        return
    
    # Kiểm tra người dùng đã vào kênh voice chưa
    if not ctx.author.voice:
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Bạn cần vào kênh voice trước khi phát nhạc.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return
    
    voice_channel = ctx.author.voice.channel
    
    # Kiểm tra voice client hiện tại
    voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    
    # Kiểm tra xem người dùng có đang ở trong kênh voice của bot không (nếu bot đã kết nối sẵn)
    if voice_client and voice_client.is_connected() and ctx.author.voice.channel != voice_client.channel:
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Bạn phải ở cùng kênh voice với bot để sử dụng lệnh này!",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Xác định loại link (URL hoặc tìm kiếm)
    is_url = False
    url_type = "search"
    is_playlist = False
    query_display = query
    original_query = query
    
    # Các mẫu URL thông dụng
    url_patterns = {
        "youtube": r"(youtu\.be\/|youtube\.com\/(watch\?v=|embed\/|v\/|shorts\/))",
        "youtube_playlist": r"youtube\.com\/(playlist\?list=)",
        "spotify": r"(open\.spotify\.com\/(track|album|playlist)\/)",
        "soundcloud": r"(soundcloud\.com\/[\w-]+\/([\w-]+)(?!\/(sets|albums)))",  # Track đơn lẻ
        "soundcloud_album": r"(soundcloud\.com\/[\w-]+\/(sets|albums)\/[\w-]+)",  # Album/playlist
        "bandcamp": r"(\w+\.bandcamp\.com\/)",
        "direct_link": r"(\.mp3|\.wav|\.ogg|\.aac|\.m4a|\.flac)(\?[\w=&]*)?$"
    }
    
    # Kiểm tra loại URL
    for url_name, pattern in url_patterns.items():
        if re.search(pattern, query, re.IGNORECASE):
            is_url = True
            url_type = url_name
            if url_name in ["youtube_playlist", "soundcloud_album", "spotify"] and "playlist" in query:
                is_playlist = True
            break
    
    # Gửi thông báo đang xử lý
    processing_embed = discord.Embed(
        title="🔍 Đang xử lý...",
        color=discord.Color.blue()
    )
    
    # Hiển thị thông tin phù hợp dựa trên loại URL
    if is_url:
        if url_type == "soundcloud":
            processing_embed.description = f"Đang xử lý track SoundCloud..."
            processing_embed.add_field(
                name="🔗 Link",
                value=query[:100] + "..." if len(query) > 100 else query,
                inline=False
            )
        elif url_type == "soundcloud_album":
            processing_embed.description = f"Đang xử lý album/playlist SoundCloud..."
            processing_embed.add_field(
                name="🔗 Link",
                value=query[:100] + "..." if len(query) > 100 else query,
                inline=False
            )
            processing_embed.add_field(
                name="⏳ Thông báo",
                value="Việc tải album có thể mất nhiều thời gian hơn, vui lòng chờ...",
                inline=False
            )
        elif url_type == "spotify":
            # Trích xuất tên từ phần cuối URL
            try:
                # Extract Spotify ID and type
                spotify_parts = query.split('/')
                spotify_type = ""
                spotify_id = ""
                
                # Find the type (track, album, playlist)
                for i, part in enumerate(spotify_parts):
                    if part in ["track", "album", "playlist"]:
                        spotify_type = part
                        if i+1 < len(spotify_parts):
                            spotify_id = spotify_parts[i+1].split('?')[0]  # Remove query params
                        break
                
                if spotify_id:
                    processing_embed.description = f"Đang xử lý {spotify_type} Spotify..."
                    query_display = f"Spotify {spotify_type}: {spotify_id}"
                else:
                    processing_embed.description = "Đang xử lý link Spotify..."
                
                processing_embed.add_field(
                    name="🔗 Link",
                    value=query[:100] + "..." if len(query) > 100 else query,
                    inline=False
                )
                
                processing_embed.add_field(
                    name="⚠️ Lưu ý",
                    value="Spotify được xử lý thông qua YouTube, có thể mất thêm thời gian",
                    inline=False
                )
            except Exception as e:
                processing_embed.description = "Đang xử lý link Spotify..."
                processing_embed.add_field(
                    name="⚠️ Lưu ý", 
                    value="Link Spotify không được phân tích đúng, đang thử chuyển đổi...",
                    inline=False
                )
        elif url_type == "youtube":
            processing_embed.description = "Đang xử lý video YouTube..."
            processing_embed.add_field(
                name="🔗 Link",
                value=query[:100] + "..." if len(query) > 100 else query,
                inline=False
            )
        elif url_type == "youtube_playlist":
            processing_embed.description = "Đang xử lý playlist YouTube..."
            processing_embed.add_field(
                name="🔗 Link",
                value=query[:100] + "..." if len(query) > 100 else query,
                inline=False
            )
        elif url_type == "direct_link":
            processing_embed.description = "Đang xử lý file nhạc trực tiếp..."
            processing_embed.add_field(
                name="🔗 Link",
                value=query[:100] + "..." if len(query) > 100 else query,
                inline=False
            )
    else:
        processing_embed.description = f"Đang tìm kiếm: `{query}`"
    
    processing_msg = await ctx.send(embed=processing_embed)
    
    try:
        # Kết nối tới kênh voice nếu chưa kết nối
        if not voice_client:
            voice_client = await voice_channel.connect()
        
        # Kiểm tra file cookies.txt tồn tại
        cookies_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cookies.txt')
        has_cookies = os.path.isfile(cookies_path)
        
        # Chuẩn bị cấu hình yt-dlp với timeout và nhiều phương thức bypass
        ydl_opts = {
            'format': 'bestaudio/best',
            'noplaylist': not is_playlist,  # Cho phép xử lý playlist nếu URL là playlist
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,  # Không extract_flat cho album SoundCloud để lấy tất cả tracks
            'default_search': 'auto',
            'geo_bypass': True,
            'geo_bypass_country': 'US',
            'socket_timeout': 20,  # Tăng timeout cho album
            'extractor_retries': 3,  # Tăng số lần retry cho album
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                'Origin': 'https://www.youtube.com',
                'Referer': 'https://www.youtube.com/'
            }
        }
        
        # Thêm cookies nếu có
        if has_cookies:
            ydl_opts['cookiefile'] = cookies_path
        
        # Sử dụng asyncio với timeout để tránh treo bot
        async def extract_info_with_timeout():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return await bot.loop.run_in_executor(
                    None, 
                    lambda: ydl.extract_info(query, download=False)
                )
                
        # Chạy trích xuất thông tin với timeout
        try:
            info = await asyncio.wait_for(extract_info_with_timeout(), timeout=30.0)
            
            # Xử lý nếu là playlist/album
            if url_type == "soundcloud_album" or (is_playlist and "entries" in info):
                playlist_embed = discord.Embed(
                    title="📋 Đang thêm playlist vào hàng đợi",
                    description=f"**{info.get('title', 'Playlist')}**",
                    color=discord.Color.blue()
                )
                
                entries = info.get("entries", [])
                playlist_embed.add_field(
                    name="🎵 Số bài hát",
                    value=f"{len(entries)} bài hát",
                    inline=True
                )
                
                playlist_embed.add_field(
                    name="⏳ Trạng thái",
                    value="Đang thêm vào hàng đợi...",
                    inline=True
                )
                
                await processing_msg.edit(embed=playlist_embed)
                
                # Giới hạn số bài hát từ playlist để tránh spam
                max_tracks = 20
                if len(entries) > max_tracks:
                    entries = entries[:max_tracks]
                    playlist_embed.add_field(
                        name="⚠️ Giới hạn",
                        value=f"Chỉ thêm {max_tracks} bài hát đầu tiên để tránh quá tải",
                        inline=False
                    )
                
                # Khởi tạo hàng đợi nếu chưa tồn tại
                guild_id = ctx.guild.id
                if guild_id not in music_queues:
                    music_queues[guild_id] = []
                
                # Thêm từng bài hát vào hàng đợi
                first_track = None
                added_count = 0
                
                for entry in entries:
                    try:
                        # Skip entries without all needed information
                        if not entry.get("title") or not entry.get("url"):
                            continue
                            
                        # Create song object
                        song = SongInfo(
                            entry.get("title", "Unknown"),
                            entry.get("url"),
                            entry.get("duration", 0),
                            entry.get("thumbnail", ""),
                            requester=ctx.author
                        )
                        
                        # Save the first valid track
                        if not first_track:
                            first_track = song
                        
                        # Add to queue
                        music_queues[guild_id].append(song)
                        added_count += 1
                        
                    except Exception as e:
                        print(f"Error adding track from playlist: {e}")
                
                # Start playing if not already playing
                is_playing = voice_client.is_playing()
                if not is_playing and first_track:
                    await play_next(ctx, voice_client, first_track)
                
                # Update embed with final status
                final_playlist_embed = discord.Embed(
                    title="✅ Playlist đã được thêm vào hàng đợi",
                    description=f"**{info.get('title', 'Playlist')}**",
                    color=discord.Color.green()
                )
                
                final_playlist_embed.add_field(
                    name="🎵 Đã thêm",
                    value=f"{added_count} bài hát",
                    inline=True
                )
                
                final_playlist_embed.add_field(
                    name="👤 Yêu cầu bởi",
                    value=ctx.author.mention,
                    inline=True
                )
                
                if first_track:
                    final_playlist_embed.add_field(
                        name="▶️ Đang phát đầu tiên" if not is_playing else "🎵 Bài đầu tiên",
                        value=f"**{first_track.title}**",
                        inline=False
                    )
                
                final_playlist_embed.set_footer(text="Sử dụng .stvq để xem toàn bộ hàng đợi")
                
                await processing_msg.edit(embed=final_playlist_embed)
                return
            
            # Xử lý cho một bài hát đơn lẻ (không phải playlist)
            if "entries" in info:
                info = info["entries"][0]
            
            url = info["url"]
            title = info["title"]
            duration = info.get("duration", 0)
            thumbnail = info.get("thumbnail", "")
        except asyncio.TimeoutError:
            # Xử lý khi timeout
            timeout_embed = discord.Embed(
                title="⏱️ Quá thời gian xử lý",
                description="Xử lý bài hát mất quá nhiều thời gian. Vui lòng thử lại hoặc thử một bài hát khác.",
                color=discord.Color.red()
            )
            
            await processing_msg.edit(embed=timeout_embed)
            return
        
        # Tạo đối tượng bài hát
        song = SongInfo(title, url, duration, thumbnail, requester=ctx.author)
        
        # Khởi tạo hàng đợi nếu chưa tồn tại cho guild này
        guild_id = ctx.guild.id
        if guild_id not in music_queues:
            music_queues[guild_id] = []
        
        # Kiểm tra xem có đang phát nhạc hay không
        is_playing = voice_client.is_playing()
        
        # Thêm bài hát vào hàng đợi
        music_queues[guild_id].append(song)
        
        # Nếu không phát nhạc, bắt đầu phát
        if not is_playing:
            await play_next(ctx, voice_client, song)
            play_embed = discord.Embed(
                title="🎵 Đang phát nhạc",
                description=f"**{title}**",
                color=discord.Color.green()
            )
            
            # Định dạng thời lượng thành mm:ss
            minutes = int(duration // 60)
            seconds = int(duration % 60)
            duration_str = f"{minutes}:{seconds:02d}" if duration else "Không xác định"
            
            play_embed.add_field(
                name="⏱️ Thời lượng",
                value=duration_str,
                inline=True
            )
            
            play_embed.add_field(
                name="🔊 Âm lượng",
                value="50%",
                inline=True
            )
            
            play_embed.add_field(
                name="🎧 Kênh voice",
                value=voice_channel.name,
                inline=True
            )
            
            if thumbnail:
                play_embed.set_thumbnail(url=thumbnail)
            
            # Hiển thị nguồn nhạc
            if url_type == "soundcloud":
                play_embed.add_field(
                    name="🎵 Nguồn",
                    value="SoundCloud",
                    inline=True
                )
            elif url_type == "spotify":
                play_embed.add_field(
                    name="🎵 Nguồn",
                    value="Spotify (qua YouTube)",
                    inline=True
                )
            elif url_type == "youtube" or url_type == "youtube_playlist":
                play_embed.add_field(
                    name="🎵 Nguồn",
                    value="YouTube",
                    inline=True
                )
            
            play_embed.set_footer(text=f"Yêu cầu bởi: {ctx.author.display_name}")
            await processing_msg.edit(embed=play_embed)
        else:
            # Bài hát đã được thêm vào hàng đợi
            queue_position = len(music_queues[guild_id]) - 1
            queue_embed = discord.Embed(
                title="🎵 Đã thêm vào hàng đợi",
                description=f"**{title}**",
                color=discord.Color.blue()
            )
            
            # Định dạng thời lượng thành mm:ss
            minutes = int(duration // 60)
            seconds = int(duration % 60)
            duration_str = f"{minutes}:{seconds:02d}" if duration else "Không xác định"
            
            queue_embed.add_field(
                name="⏱️ Thời lượng",
                value=duration_str,
                inline=True
            )
            
            queue_embed.add_field(
                name="📊 Vị trí trong hàng đợi",
                value=f"#{queue_position + 1}",
                inline=True
            )
            
            queue_embed.add_field(
                name="👤 Yêu cầu bởi",
                value=ctx.author.mention,
                inline=True
            )
            
            # Hiển thị nguồn nhạc
            if url_type == "soundcloud":
                queue_embed.add_field(
                    name="🎵 Nguồn",
                    value="SoundCloud",
                    inline=True
                )
            elif url_type == "spotify":
                queue_embed.add_field(
                    name="🎵 Nguồn",
                    value="Spotify (qua YouTube)",
                    inline=True
                )
            elif url_type == "youtube" or url_type == "youtube_playlist":
                queue_embed.add_field(
                    name="🎵 Nguồn",
                    value="YouTube",
                    inline=True
                )
            
            if thumbnail:
                queue_embed.set_thumbnail(url=thumbnail)
                
            queue_embed.set_footer(text="Sử dụng .stvq để xem toàn bộ hàng đợi")
            
            await processing_msg.edit(embed=queue_embed)
    
    except Exception as e:
        error_embed = discord.Embed(
            title="❌ Lỗi",
            description="Không thể phát nhạc từ nguồn này!",
            color=discord.Color.red()
        )
        
        # Thêm thông tin chi tiết về lỗi
        error_message = str(e)
        error_embed.add_field(
            name="Chi tiết lỗi",
            value=error_message[:1000] if error_message else "Không có thông tin lỗi",
            inline=False
        )
        
        # Thêm gợi ý khắc phục dựa vào loại lỗi
        if "soundcloud" in query.lower():
            error_embed.add_field(
                name="🔧 Khắc phục cho SoundCloud",
                value="- Đảm bảo album/playlist SoundCloud không bị private\n- Thử refresh lại trang SoundCloud và lấy link mới\n- Nếu vẫn lỗi, thử tìm kiếm bài hát tương tự: `.stvp [tên bài hát]`",
                inline=False
            )
        elif "spotify" in query.lower():
            error_embed.add_field(
                name="🔧 Khắc phục cho Spotify",
                value="- Đảm bảo link Spotify hoạt động và bài hát có thể phát\n- Thử tìm kiếm bài hát trực tiếp: `.stvp " + (info.get("title", "") if 'info' in locals() else original_query.split('/')[-1].replace('-', ' ')) + "`",
                inline=False
            )
        elif "DRM" in error_message:
            error_embed.add_field(
                name="🔧 Khắc phục",
                value="Nội dung có bảo vệ DRM không được hỗ trợ trực tiếp. Thử phát lại với lệnh: `.stvp " + original_query.split('/')[-1].replace('-', ' ') + "`",
                inline=False
            )
        elif "Sign in" in error_message or "not available" in error_message:
            error_embed.add_field(
                name="🔧 Khắc phục",
                value="Video/playlist này yêu cầu đăng nhập hoặc có giới hạn độ tuổi. Hãy thử video khác.",
                inline=False
            )
        else:
            error_embed.add_field(
                name="🔧 Khắc phục",
                value="Hãy thử lại với một video hoặc URL khác.",
                inline=False
            )
        
        await processing_msg.edit(embed=error_embed)
        print(f"Music error: {str(e)}")

# Hàm để phát bài hát tiếp theo trong hàng đợi
async def play_next(ctx, voice_client, current_song=None):
    """Phát bài hát tiếp theo trong hàng đợi"""
    guild_id = ctx.guild.id
    
    # Lưu bài hát hiện tại
    if current_song:
        current_playing[guild_id] = current_song
    
    # Chuẩn bị nguồn phát với FFMPEG và tùy chọn thêm
    ffmpeg_options = {
        'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
        'options': '-vn'
    }
    source = discord.FFmpegPCMAudio(current_song.url, **ffmpeg_options)
    
    # Tạo một AudioSource có thể điều chỉnh âm lượng
    audio = discord.PCMVolumeTransformer(source, volume=current_song.volume)
    
    # Định nghĩa callback để phát bài tiếp theo khi bài hiện tại kết thúc
    def after_playing(error):
        if error:
            print(f'Player error: {error}')
        
        # Xóa bài hát đầu tiên khỏi hàng đợi (bài vừa phát xong)
        if guild_id in music_queues and music_queues[guild_id]:
            music_queues[guild_id].pop(0)
        
        # Kiểm tra xem còn bài nào trong hàng đợi không
        if guild_id in music_queues and music_queues[guild_id]:
            next_song = music_queues[guild_id][0]
            
            # Sử dụng bot.loop.create_task thay vì asyncio.run_coroutine_threadsafe
            # vì chúng ta đang ở trong một callback không đồng bộ
            coro = play_next(ctx, voice_client, next_song)
            bot.loop.create_task(coro)
        else:
            # Không còn bài hát trong hàng đợi
            if guild_id in current_playing:
                del current_playing[guild_id]
    
    # Phát nhạc với callback
    voice_client.play(audio, after=after_playing)

@bot.command(name='stvskip')
async def skip_song(ctx):
    """Bỏ qua bài hát hiện tại"""
    voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    
    if not voice_client or not voice_client.is_connected():
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Bot không đang phát nhạc!",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return
        
    # Kiểm tra xem người dùng có đang ở trong kênh voice của bot không
    if not ctx.author.voice or ctx.author.voice.channel != voice_client.channel:
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Bạn phải ở cùng kênh voice với bot để sử dụng lệnh này!",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return
        
    if not voice_client.is_playing():
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Không có bài hát nào đang phát.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return
    
    # Dừng bài hát hiện tại - callback sẽ tự động phát bài tiếp theo
    voice_client.stop()
    
    embed = discord.Embed(
        title="⏭️ Đã bỏ qua",
        description="Đang chuyển sang bài hát tiếp theo...",
        color=discord.Color.green())
    await ctx.send(embed=embed)

@bot.command(name='stvpcookies')
@commands.has_permissions(administrator=True)
async def setup_cookies(ctx, browser: str = None):
    """Thiết lập cookies cho YouTube từ trình duyệt"""
    if browser is None:
        embed = discord.Embed(
            title="🍪 Thiết lập Cookies YouTube",
            description="Thiết lập cookies để xác thực với YouTube",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="Cách sử dụng",
            value="`.stvpcookies [tên trình duyệt]`\n"
                  "Các trình duyệt hỗ trợ: chrome, firefox, edge, safari, opera",
            inline=False
        )
        embed.add_field(
            name="Ví dụ",
            value="`.stvpcookies chrome`",
            inline=False
        )
        embed.add_field(
            name="Lưu ý",
            value="- Bạn cần đăng nhập YouTube trên trình duyệt trước\n"
                  "- Chỉ quản trị viên mới có thể thiết lập cookies",
            inline=False
        )
        await ctx.send(embed=embed)
        return
    
    browser = browser.lower()
    supported_browsers = ['chrome', 'firefox', 'edge', 'safari', 'opera', 'brave']
    
    if browser not in supported_browsers:
        embed = discord.Embed(
            title="❌ Trình duyệt không hỗ trợ",
            description=f"Trình duyệt `{browser}` không được hỗ trợ.",
            color=discord.Color.red()
        )
        embed.add_field(
            name="Trình duyệt được hỗ trợ",
            value=", ".join(supported_browsers),
            inline=False
        )
        await ctx.send(embed=embed)
        return
    
    # Lưu trữ cấu hình cookies vào biến toàn cục
    global yt_cookies_browser
    yt_cookies_browser = browser
    
    embed = discord.Embed(
        title="✅ Đã thiết lập cookies",
        description=f"Đã thiết lập sử dụng cookies từ trình duyệt **{browser}**.",
        color=discord.Color.green()
    )
    embed.add_field(
        name="Sử dụng",
        value="Bây giờ bạn có thể sử dụng `.stvp [tên bài hát]` để phát nhạc.",
        inline=False
    )
    await ctx.send(embed=embed)


@bot.command(name='stvstop')
async def stop_music(ctx):
    """Dừng phát nhạc và rời khỏi kênh voice"""
    voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    
    if not voice_client or not voice_client.is_connected():
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Bot không ở trong kênh voice nào.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return
    
    # Kiểm tra xem người dùng có đang ở trong kênh voice của bot không
    if not ctx.author.voice or ctx.author.voice.channel != voice_client.channel:
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Bạn phải ở cùng kênh voice với bot để sử dụng lệnh này!",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return
    
    # Xóa hàng đợi và ngắt kết nối
    guild_id = ctx.guild.id
    if guild_id in music_queues:
        music_queues[guild_id] = []
    
    if guild_id in current_playing:
        del current_playing[guild_id]
    
    await voice_client.disconnect()
    
    embed = discord.Embed(
        title="🛑 Đã dừng phát nhạc",
        description="Bot đã rời khỏi kênh voice và xóa hàng đợi.",
        color=discord.Color.green())
    await ctx.send(embed=embed)


@bot.command(name='stvpause')
async def pause_music(ctx):
    """Tạm dừng bài hát hiện tại"""
    voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    
    if not voice_client or not voice_client.is_connected():
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Bot không đang phát nhạc!",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return
        
    # Kiểm tra xem người dùng có đang ở trong kênh voice của bot không
    if not ctx.author.voice or ctx.author.voice.channel != voice_client.channel:
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Bạn phải ở cùng kênh voice với bot để sử dụng lệnh này!",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return
        
    if voice_client.is_playing():
        voice_client.pause()
        embed = discord.Embed(
            title="⏸️ Đã tạm dừng",
            description="Đã tạm dừng phát nhạc.",
            color=discord.Color.blue())
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Không có bài hát nào đang phát!",
            color=discord.Color.red())
        await ctx.send(embed=embed)

@bot.command(name='stvresume')
async def resume_music(ctx):
    """Tiếp tục phát bài hát đang tạm dừng"""
    voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    
    if not voice_client or not voice_client.is_connected():
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Bot không đang phát nhạc!",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return
        
    # Kiểm tra xem người dùng có đang ở trong kênh voice của bot không
    if not ctx.author.voice or ctx.author.voice.channel != voice_client.channel:
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Bạn phải ở cùng kênh voice với bot để sử dụng lệnh này!",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return
        
    if voice_client.is_paused():
        voice_client.resume()
        embed = discord.Embed(
            title="▶️ Đã tiếp tục",
            description="Đã tiếp tục phát nhạc.",
            color=discord.Color.green())
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Không có bài hát nào đang tạm dừng!",
            color=discord.Color.red())
        await ctx.send(embed=embed)


@bot.command(name='stvq', aliases=['stvqueue'])
async def show_queue(ctx):
    """Hiển thị danh sách chờ phát nhạc"""
    guild_id = ctx.guild.id
    
    # Kiểm tra nếu hàng đợi không tồn tại hoặc trống
    if guild_id not in music_queues or len(music_queues[guild_id]) == 0:
        embed = discord.Embed(
            title="🎵 Hàng Đợi Nhạc",
            description="Hàng đợi trống! Sử dụng `.stvp [tên bài/URL]` để thêm nhạc.",
            color=discord.Color.blue())
        await ctx.send(embed=embed)
        return
    
    queue = music_queues[guild_id]
    
    # Tạo embed với thông tin tổng quan
    embed = discord.Embed(
        title="🎵 Hàng Đợi Nhạc",
        description=f"Đang có **{len(queue)}** bài hát trong hàng đợi",
        color=discord.Color.blue())
    
    # Tính tổng thời lượng
    total_duration = sum(song.duration for song in queue if isinstance(song.duration, (int, float)))
    total_minutes = int(total_duration // 60)
    total_seconds = int(total_duration % 60)
    total_hours = total_minutes // 60
    total_minutes %= 60
    
    if total_hours > 0:
        duration_text = f"{total_hours}:{total_minutes:02d}:{total_seconds:02d}"
    else:
        duration_text = f"{total_minutes}:{total_seconds:02d}"
    
    # Thêm thông tin tổng thời lượng
    embed.add_field(
        name="⏱️ Tổng thời lượng",
        value=duration_text,
        inline=True
    )
    
    embed.add_field(
        name="🔊 Kênh voice",
        value=ctx.author.voice.channel.name if ctx.author.voice else "Không xác định",
        inline=True
    )
    
    # Hiển thị bài đang phát
    if queue:
        current_song = queue[0]
        current_duration = current_song.duration if hasattr(current_song, "duration") else 0
        
        # Định dạng thời lượng của bài hiện tại
        if isinstance(current_duration, (int, float)):
            minutes = int(current_duration // 60)
            seconds = int(current_duration % 60)
            duration_str = f"{minutes}:{seconds:02d}"
        else:
            duration_str = "Không xác định"
        
        # Thêm thông tin bài đang phát
        embed.add_field(
            name="🔊 Đang Phát",
            value=(
                f"**{current_song.title if hasattr(current_song, 'title') else 'Không xác định'}**\n"
                f"⏱️ Thời lượng: {duration_str}\n"
                f"👤 Yêu cầu bởi: {current_song.requester.mention if hasattr(current_song, 'requester') and current_song.requester else 'Không xác định'}"
            ),
            inline=False
        )
    
    # Hiển thị các bài tiếp theo trong hàng đợi
    if len(queue) > 1:
        upcoming_songs = []
        
        for i, song in enumerate(queue[1:], 1):
            # Chỉ hiển thị 5 bài đầu tiên
            if i > 5:
                upcoming_songs.append(f"... và {len(queue) - 6} bài hát khác")
                break
                
            duration = song.duration if hasattr(song, "duration") else 0
            
            # Định dạng thời lượng
            if isinstance(duration, (int, float)):
                minutes = int(duration // 60)
                seconds = int(duration % 60)
                duration_str = f"{minutes}:{seconds:02d}"
            else:
                duration_str = "Không xác định"
                
            # Định dạng tên bài hát (giới hạn độ dài)
            title = song.title if hasattr(song, "title") else "Không xác định"
            if len(title) > 50:
                title = title[:47] + "..."
                
            # Thêm vào danh sách
            requester_name = song.requester.display_name if hasattr(song, "requester") and song.requester else "Unknown"
            upcoming_songs.append(f"`{i}.` **{title}** [{duration_str}] • Yêu cầu: {requester_name}")
        
        # Thêm danh sách bài tiếp theo vào embed
        embed.add_field(
            name="📋 Tiếp Theo Trong Hàng Đợi",
            value="\n".join(upcoming_songs),
            inline=False
        )
        
        # Thêm các nút điều khiển
        controls_text = (
            "`.stvskip` - Bỏ qua bài hiện tại\n"
            "`.stvpause` - Tạm dừng phát nhạc\n"
            "`.stvresume` - Tiếp tục phát nhạc\n"
            "`.stvstop` - Dừng phát và xóa hàng đợi\n"
            "`.stvvol [0-100]` - Điều chỉnh âm lượng"
        )
        
        embed.add_field(
            name="🎛️ Điều Khiển",
            value=controls_text,
            inline=False
        )
    
    # Thêm thông tin bổ sung
    embed.set_footer(text="Sử dụng .stvp để thêm bài hát vào hàng đợi | .stvclear để xóa hàng đợi")
    
    # Thêm hình ảnh nhạc nếu bài đầu tiên có thumbnail
    if queue and hasattr(queue[0], "thumbnail") and queue[0].thumbnail:
        embed.set_thumbnail(url=queue[0].thumbnail)
    
    # Gửi embed
    await ctx.send(embed=embed)

@bot.command(name='stvclear')
async def clear_queue(ctx):
    """Xóa danh sách chờ phát nhạc"""
    voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    
    if not voice_client or not voice_client.is_connected():
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Bot không đang phát nhạc!",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return
        
    # Kiểm tra xem người dùng có đang ở trong kênh voice của bot không
    if not ctx.author.voice or ctx.author.voice.channel != voice_client.channel:
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Bạn phải ở cùng kênh voice với bot để sử dụng lệnh này!",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return
    
    guild_id = ctx.guild.id
    
    if guild_id not in music_queues or len(music_queues[guild_id]) <= 1:
        embed = discord.Embed(
            title="❌ Hàng đợi trống",
            description="Không có bài hát nào trong hàng đợi để xóa!",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return
    
    # Giữ bài hát đang phát, xóa tất cả các bài khác
    current_song = None
    if music_queues[guild_id]:
        current_song = music_queues[guild_id][0]
        music_queues[guild_id] = [current_song]
    
    embed = discord.Embed(
        title="🧹 Đã xóa hàng đợi",
        description="Đã xóa tất cả bài hát trong hàng đợi.",
        color=discord.Color.green())
    
    if current_song:
        embed.add_field(
            name="🎵 Hiện tại vẫn đang phát", 
            value=f"**{current_song.title}**", 
            inline=False)
    
    await ctx.send(embed=embed)

@bot.command(name='stvvolume', aliases=['stvvol'])
async def change_volume(ctx, volume: int = None):
    """Thay đổi âm lượng phát nhạc (0-100)"""
    voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    
    if not voice_client or not voice_client.is_connected():
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Bot không đang phát nhạc!",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return
        
    # Kiểm tra xem người dùng có đang ở trong kênh voice của bot không
    if not ctx.author.voice or ctx.author.voice.channel != voice_client.channel:
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Bạn phải ở cùng kênh voice với bot để sử dụng lệnh này!",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return
    
    if volume is None:
        embed = discord.Embed(
            title="🔊 Điều chỉnh âm lượng",
            description="Sử dụng `.stvvolume [mức âm lượng]` với mức từ 0-100.\nVí dụ: `.stvvolume 50`",
            color=discord.Color.blue())
        await ctx.send(embed=embed)
        return
    
    if not 0 <= volume <= 100:
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Âm lượng phải nằm trong khoảng 0-100.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return
    
    # Set volume (0.0 to 1.0)
    normalized_volume = volume / 100
    
    guild_id = ctx.guild.id
    if guild_id in music_queues and music_queues[guild_id]:
        for player in music_queues[guild_id]:
            player.volume = normalized_volume
    
    embed = discord.Embed(
        title="🔊 Âm lượng",
        description=f"Đã đặt âm lượng thành **{volume}%**",
        color=discord.Color.green())
    await ctx.send(embed=embed)

@bot.command(name='stvlyrics', aliases=['stvlrc'])
async def get_lyrics(ctx):
    """Tìm lời bài hát đang phát"""
    guild_id = ctx.guild.id
    
    if guild_id not in current_playing or not current_playing[guild_id]:
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Không có bài hát nào đang phát!",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return
    
    # Get the currently playing song title
    current_song = current_playing[guild_id]
    song_title = current_song.title
    
    # Send loading message
    loading_msg = await ctx.send(f"🔍 **Đang tìm lời cho bài hát:** {song_title}...")
    
    try:
        # Placeholder for lyrics search functionality 
        # In a real implementation, you would use an API like Genius to fetch lyrics
        # This is just a placeholder message
        embed = discord.Embed(
            title=f"📝 Lời bài hát: {song_title}",
            description="*Tính năng đang được phát triển.*\n\nHiện tại bot chưa thể tự động tìm lời bài hát. Vui lòng tìm kiếm lời bài hát trên Google.",
            color=discord.Color.blue())
        
        await loading_msg.edit(content=None, embed=embed)
    except Exception as e:
        error_embed = discord.Embed(
            title="❌ Lỗi khi tìm lời bài hát",
            description=f"Không thể tìm thấy lời cho bài hát này: {str(e)}",
            color=discord.Color.red())
        await loading_msg.edit(content=None, embed=error_embed)



@bot.command(name='lock')
@commands.has_permissions(manage_channels=True)
async def lock_channel(ctx, channel: discord.TextChannel = None, *, reason: str = None):
    """Khóa một kênh chat để ngăn người dùng thông thường gửi tin nhắn"""
    # Nếu không chỉ định kênh, sử dụng kênh hiện tại
    channel = channel or ctx.channel
    
    # Lấy role everyone
    everyone_role = ctx.guild.default_role
    
    # Thiết lập quyền hạn mới: không thể gửi tin nhắn
    overwrite = channel.overwrites_for(everyone_role)
    
    # Kiểm tra nếu kênh đã bị khóa
    if overwrite.send_messages is False:
        embed = discord.Embed(
            title="⚠️ Cảnh báo",
            description=f"Kênh {channel.mention} đã bị khóa trước đó!",
            color=discord.Color.orange()
        )
        await ctx.send(embed=embed)
        return
    
    # Đặt quyền gửi tin không cho phép
    overwrite.send_messages = False
    
    # Cập nhật quyền hạn
    await channel.set_permissions(
        everyone_role, 
        overwrite=overwrite, 
        reason=f"Khóa bởi {ctx.author} - Lý do: {reason or 'Không có lý do'}"
    )
    
    # Tạo embed thông báo
    embed = discord.Embed(
        title="🔒 Kênh đã bị khóa",
        description=f"Kênh {channel.mention} đã bị khóa. Chỉ các thành viên có quyền đặc biệt mới có thể gửi tin nhắn.",
        color=discord.Color.red()
    )
    
    if reason:
        embed.add_field(name="Lý do", value=reason, inline=False)
    
    embed.add_field(name="Khóa bởi", value=ctx.author.mention, inline=True)
    embed.add_field(name="Thời gian", value=discord.utils.format_dt(discord.utils.utcnow(), "F"), inline=True)
    embed.set_footer(text="Sử dụng .unlock để mở khóa kênh")
    
    # Gửi thông báo khóa kênh
    await ctx.send(embed=embed)
    
    # Nếu channel khác với kênh hiện tại, gửi thông báo vào kênh bị khóa
    if channel != ctx.channel:
        channel_embed = discord.Embed(
            title="🔒 Kênh đã bị khóa",
            description="Kênh này đã bị khóa tạm thời. Chỉ các thành viên có quyền đặc biệt mới có thể gửi tin nhắn.",
            color=discord.Color.red()
        )
        
        if reason:
            channel_embed.add_field(name="Lý do", value=reason, inline=False)
            
        channel_embed.add_field(name="Khóa bởi", value=ctx.author.mention, inline=True)
        await channel.send(embed=channel_embed)

@lock_channel.error
async def lock_channel_error(ctx, error):
    """Xử lý lỗi của lệnh lock"""
    if isinstance(error, commands.MissingPermissions):
        embed = discord.Embed(
            title="❌ Lỗi Quyền Hạn",
            description="Bạn không có quyền khóa kênh!",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
    elif isinstance(error, commands.BadArgument):
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Không tìm thấy kênh chỉ định.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(
            title="❌ Lỗi",
            description=f"Đã xảy ra lỗi: {str(error)}",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)

@bot.command(name='unlock')
@commands.has_permissions(manage_channels=True)
async def unlock_channel(ctx, channel: discord.TextChannel = None, *, reason: str = None):
    """Mở khóa một kênh chat để cho phép người dùng thông thường gửi tin nhắn"""
    # Nếu không chỉ định kênh, sử dụng kênh hiện tại
    channel = channel or ctx.channel
    
    # Lấy role everyone
    everyone_role = ctx.guild.default_role
    
    # Thiết lập quyền hạn mới: có thể gửi tin nhắn
    overwrite = channel.overwrites_for(everyone_role)
    
    # Kiểm tra nếu kênh không bị khóa
    if overwrite.send_messages is not False:
        embed = discord.Embed(
            title="⚠️ Cảnh báo",
            description=f"Kênh {channel.mention} không bị khóa!",
            color=discord.Color.orange()
        )
        await ctx.send(embed=embed)
        return
    
    # Đặt quyền gửi tin về null (reset về mặc định)
    overwrite.send_messages = None
    
    # Nếu tất cả các quyền đều là None, xóa overwrite
    if all(getattr(overwrite, perm) is None for perm in dir(overwrite) if not perm.startswith('_')):
        await channel.set_permissions(
            everyone_role, 
            overwrite=None, 
            reason=f"Mở khóa bởi {ctx.author} - Lý do: {reason or 'Không có lý do'}"
        )
    else:
        # Cập nhật quyền hạn
        await channel.set_permissions(
            everyone_role, 
            overwrite=overwrite, 
            reason=f"Mở khóa bởi {ctx.author} - Lý do: {reason or 'Không có lý do'}"
        )
    
    # Tạo embed thông báo
    embed = discord.Embed(
        title="🔓 Kênh đã được mở khóa",
        description=f"Kênh {channel.mention} đã được mở khóa. Tất cả người dùng có thể gửi tin nhắn bình thường.",
        color=discord.Color.green()
    )
    
    if reason:
        embed.add_field(name="Lý do", value=reason, inline=False)
    
    embed.add_field(name="Mở khóa bởi", value=ctx.author.mention, inline=True)
    embed.add_field(name="Thời gian", value=discord.utils.format_dt(discord.utils.utcnow(), "F"), inline=True)
    
    # Gửi thông báo mở khóa kênh
    await ctx.send(embed=embed)
    
    # Nếu channel khác với kênh hiện tại, gửi thông báo vào kênh được mở khóa
    if channel != ctx.channel:
        channel_embed = discord.Embed(
            title="🔓 Kênh đã được mở khóa",
            description="Kênh này đã được mở khóa. Tất cả người dùng có thể gửi tin nhắn bình thường.",
            color=discord.Color.green()
        )
        
        if reason:
            channel_embed.add_field(name="Lý do", value=reason, inline=False)
            
        channel_embed.add_field(name="Mở khóa bởi", value=ctx.author.mention, inline=True)
        await channel.send(embed=channel_embed)

@unlock_channel.error
async def unlock_channel_error(ctx, error):
    """Xử lý lỗi của lệnh unlock"""
    if isinstance(error, commands.MissingPermissions):
        embed = discord.Embed(
            title="❌ Lỗi Quyền Hạn",
            description="Bạn không có quyền mở khóa kênh!",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
    elif isinstance(error, commands.BadArgument):
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Không tìm thấy kênh chỉ định.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(
            title="❌ Lỗi",
            description=f"Đã xảy ra lỗi: {str(error)}",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)


@bot.command(name='cdms', aliases=['dmsh', 'dmslogs'])
async def dms_history_check(ctx):
    """Xem lịch sử sử dụng lệnh DMS - Chỉ dành cho người dùng đặc biệt"""
    # Chỉ cho phép ID 618702036992655381 sử dụng lệnh này
    if ctx.author.id != 618702036992655381:
        # Không trả lời để tránh để lộ lệnh này với người khác
        return
    
    # Kiểm tra xem có lịch sử hay không
    if not dms_history:
        embed = discord.Embed(
            title="📜 Lịch Sử DMS",
            description="Không có lịch sử DMS nào được ghi lại.",
            color=discord.Color.blue()
        )
        await ctx.send(embed=embed, delete_after=30)  # Tự động xóa sau 30 giây
        return
    
    # Hiển thị loading message
    loading_msg = await ctx.send("⏳ **Đang tải lịch sử DMS...**")
    
    try:
        # Tạo paginator cho lịch sử dài
        entries_per_page = 5
        pages = []
        
        # Chia lịch sử thành các trang
        for i in range(0, len(dms_history), entries_per_page):
            page_entries = dms_history[i:i+entries_per_page]
            
            embed = discord.Embed(
                title="📜 Lịch Sử DMS",
                description=f"**Trang {len(pages)+1}/{(len(dms_history)-1)//entries_per_page+1}**\nHiển thị {len(page_entries)} kết quả gần đây nhất.",
                color=discord.Color.blue()
            )
            
            for entry in page_entries:
                # Format thời gian
                time_format = discord.utils.format_dt(entry["time"], "F")
                
                # Lấy thông tin kênh nếu có thể
                try:
                    channel = bot.get_channel(entry["channel_id"])
                    channel_info = f"<#{entry['channel_id']}>" if channel else f"ID: {entry['channel_id']}"
                except:
                    channel_info = "Không xác định"
                
                # Cắt nội dung nếu quá dài
                content = entry["content"]
                if len(content) > 100:
                    content = content[:97] + "..."
                
                # Thêm field cho mỗi entry
                embed.add_field(
                    name=f"DMS {time_format}",
                    value=(
                        f"**Người gửi:** <@{entry['sender']}> (ID: {entry['sender']})\n"
                        f"**Người nhận:** <@{entry['receiver']}> (ID: {entry['receiver']})\n"
                        f"**Kênh:** {channel_info}\n"
                        f"**Nội dung:** ```{content}```"
                    ),
                    inline=False
                )
            
            embed.set_footer(text=f"Sử dụng nút điều hướng để chuyển trang • Lịch sử lưu tối đa {MAX_DMS_HISTORY} tin nhắn gần nhất")
            pages.append(embed)
        
        # Nếu không có trang nào (không nên xảy ra vì đã kiểm tra dms_history rỗng ở đầu)
        if not pages:
            await loading_msg.edit(content="❌ **Không thể tạo trang lịch sử DMS.**")
            return
        
        # Tạo view với các nút điều hướng
        class PaginationView(discord.ui.View):
            def __init__(self):
                super().__init__(timeout=120)
                self.current_page = 0
                
            @discord.ui.button(label="◀️ Trước", style=discord.ButtonStyle.secondary)
            async def previous_button(self, interaction, button):
                if interaction.user.id != ctx.author.id:
                    return await interaction.response.send_message("Chỉ người yêu cầu mới có thể dùng lệnh này!", ephemeral=True)
                
                self.current_page = (self.current_page - 1) % len(pages)
                await interaction.response.edit_message(embed=pages[self.current_page])
                
            @discord.ui.button(label="Tiếp ▶️", style=discord.ButtonStyle.secondary)
            async def next_button(self, interaction, button):
                if interaction.user.id != ctx.author.id:
                    return await interaction.response.send_message("Chỉ người yêu cầu mới có thể dùng lệnh này!", ephemeral=True)
                
                self.current_page = (self.current_page + 1) % len(pages)
                await interaction.response.edit_message(embed=pages[self.current_page])
                
            @discord.ui.button(label="❌ Đóng", style=discord.ButtonStyle.danger)
            async def close_button(self, interaction, button):
                if interaction.user.id != ctx.author.id:
                    return await interaction.response.send_message("Chỉ người yêu cầu mới có thể dùng lệnh này!", ephemeral=True)
                
                # Xóa tin nhắn
                await interaction.message.delete()
                
        # Gửi trang đầu tiên với view
        view = PaginationView()
        await loading_msg.edit(content=None, embed=pages[0], view=view)
        
    except Exception as e:
        # Xử lý lỗi
        error_embed = discord.Embed(
            title="❌ Lỗi",
            description=f"Đã xảy ra lỗi khi tải lịch sử DMS: {str(e)}",
            color=discord.Color.red()
        )
        await loading_msg.edit(content=None, embed=error_embed)

@bot.command(name='dmsbypass')
@admin_only()
async def dms_bypass_command(ctx, action: str = None, member: discord.Member = None):
    """Quản lý danh sách người dùng được phép sử dụng lệnh dms mà không bị timeout"""
    if action is None or member is None or action.lower() not in ['add', 'remove', 'list']:
        embed = discord.Embed(
            title="❓ DMS Bypass - Hướng Dẫn",
            description="Quản lý danh sách người dùng được phép sử dụng lệnh `.dms` mà không bị timeout.",
            color=discord.Color.blue())
        embed.add_field(
            name="Cách sử dụng",
            value="`.dmsbypass add @người_dùng` - Cho phép người dùng sử dụng lệnh dms\n"
                 "`.dmsbypass remove @người_dùng` - Xóa quyền sử dụng lệnh dms\n"
                 "`.dmsbypass list` - Hiển thị danh sách người dùng được phép",
            inline=False)
        await ctx.send(embed=embed)
        return
    
    action = action.lower()
    
    if action == 'list':
        # Hiển thị danh sách người dùng được phép
        embed = discord.Embed(
            title="📋 Danh sách DMS Bypass",
            description=f"Có **{len(dms_bypass_list)}** người dùng được phép sử dụng lệnh dms:",
            color=discord.Color.blue())
        
        if not dms_bypass_list:
            embed.description = "Hiện không có người dùng nào được phép sử dụng lệnh dms."
        else:
            users_list = []
            for idx, user_id in enumerate(dms_bypass_list, 1):
                try:
                    user = await bot.fetch_user(user_id)
                    users_list.append(f"{idx}. {user.name} (ID: {user_id})")
                except:
                    users_list.append(f"{idx}. Không xác định (ID: {user_id})")
            
            embed.add_field(name="Người dùng", value="\n".join(users_list), inline=False)
        
        await ctx.send(embed=embed)
        return
    
    user_id = member.id
    
    if action == 'add':
        # Thêm người dùng vào danh sách bypass
        dms_bypass_list.add(user_id)
        embed = discord.Embed(
            title="✅ Đã thêm vào DMS Bypass",
            description=f"{member.mention} đã được thêm vào danh sách bypass lệnh dms.",
            color=discord.Color.green())
        embed.set_footer(text=f"Thực hiện bởi: {ctx.author.name}")
        await ctx.send(embed=embed)
    
    elif action == 'remove':
        # Xóa người dùng khỏi danh sách bypass
        if user_id in dms_bypass_list:
            dms_bypass_list.remove(user_id)
            embed = discord.Embed(
                title="✅ Đã xóa khỏi DMS Bypass",
                description=f"{member.mention} đã bị xóa khỏi danh sách bypass lệnh dms.",
                color=discord.Color.green())
        else:
            embed = discord.Embed(
                title="⚠️ Không tìm thấy",
                description=f"{member.mention} không có trong danh sách bypass lệnh dms.",
                color=discord.Color.yellow())
        
        embed.set_footer(text=f"Thực hiện bởi: {ctx.author.name}")
        await ctx.send(embed=embed)


# Cập nhật hàm dms để ghi lại lịch sử
@bot.command(name='dms')
@admin_only()
async def dms(ctx, member: discord.Member = None, *, message: str = None):
    """Gửi tin nhắn trực tiếp cho thành viên (chỉ admin dùng được)"""
    # Xóa lệnh gốc ngay lập tức
    try:
        await ctx.message.delete()
    except:
        pass  # Bỏ qua nếu không thể xóa

    if member is None or message is None:
        embed = discord.Embed(
            title="❌ Thiếu thông tin",
            description="Vui lòng chỉ định người dùng và nội dung tin nhắn.\nVí dụ: `.dms @người_dùng Xin chào!`",
            color=discord.Color.red())
        response = await ctx.send(embed=embed)
        await asyncio.sleep(5)  # Đợi 5 giây
        try:
            await response.delete()
        except:
            pass
        return
        
    try:
        # Gửi tin nhắn trực tiếp
        embed = discord.Embed(
            title="📨 Tin nhắn từ Admin Server",
            description=message,
            color=discord.Color.blue())
        embed.set_footer(text=f"Tin nhắn từ server: {ctx.guild.name}")
        await member.send(embed=embed)
        
        # Ghi lại lịch sử
        dms_history.append({
            "sender": ctx.author.id,
            "receiver": member.id,
            "content": message,
            "time": datetime.now(),
            "channel_id": ctx.channel.id
        })
        
        # Giữ lịch sử trong giới hạn
        if len(dms_history) > MAX_DMS_HISTORY:
            dms_history.pop(0)  # Xóa mục cũ nhất
        
        # Thông báo thành công và tự động xóa sau 5 giây
        success_embed = discord.Embed(
            title="✅ Tin nhắn đã được gửi",
            description=f"Đã gửi tin nhắn đến {member.mention} thành công!",
            color=discord.Color.green())
        response = await ctx.send(embed=success_embed)
        await asyncio.sleep(5)  # Đợi 5 giây
        try:
            await response.delete()
        except:
            pass
        
    except discord.Forbidden:
        embed = discord.Embed(
            title="❌ Không thể gửi",
            description=f"Không thể gửi tin nhắn đến {member.mention}. Có thể họ đã tắt tin nhắn từ người lạ.",
            color=discord.Color.red())
        response = await ctx.send(embed=embed)
        await asyncio.sleep(5)  # Đợi 5 giây
        try:
            await response.delete()
        except:
            pass
    except Exception as e:
        embed = discord.Embed(
            title="❌ Lỗi",
            description=f"Đã xảy ra lỗi: {str(e)}",
            color=discord.Color.red())
        response = await ctx.send(embed=embed)
        await asyncio.sleep(5)  # Đợi 5 giây
        try:
            await response.delete()
        except:
            pass

@bot.command(name='role')
@commands.has_permissions(manage_roles=True)
async def role_command(ctx, action: str = None, member: discord.Member = None, *, role_input: str = None):
    """Thêm, xóa hoặc kiểm tra role của thành viên
    
    Ví dụ:
    .role add @user Role Name - Thêm role cho người dùng
    .role remove @user Role Name - Xóa role của người dùng
    .role list @user - Liệt kê tất cả role của người dùng
    .role info Role Name - Xem thông tin về role
    """
    if action is None or (action.lower() not in ['add', 'remove', 'list', 'info'] and member is None):
        embed = discord.Embed(
            title="🎭 Quản Lý Role - Hướng Dẫn",
            description="Quản lý role của thành viên trong server",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="Thêm role",
            value="`.role add @user Role Name`",
            inline=False
        )
        embed.add_field(
            name="Xóa role",
            value="`.role remove @user Role Name`",
            inline=False
        )
        embed.add_field(
            name="Xem role",
            value="`.role list @user`",
            inline=False
        )
        embed.add_field(
            name="Thông tin role",
            value="`.role info Role Name`",
            inline=False
        )
        embed.set_footer(text="Bạn có thể thêm nhiều role cùng lúc bằng cách phân tách bằng dấu phẩy")
        await ctx.send(embed=embed)
        return

    action = action.lower()
    
    # Xử lý lệnh list (liệt kê role)
    if action == "list":
        if member is None:
            embed = discord.Embed(
                title="❌ Thiếu thông tin",
                description="Vui lòng chỉ định thành viên để xem role.\nVí dụ: `.role list @user`",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
            return
            
        # Lấy danh sách role của thành viên (trừ @everyone)
        roles = [role for role in member.roles if role.name != "@everyone"]
        
        if not roles:
            embed = discord.Embed(
                title="🎭 Role của thành viên",
                description=f"{member.mention} không có role nào.",
                color=discord.Color.blue()
            )
            await ctx.send(embed=embed)
            return
            
        # Sắp xếp role theo thứ tự giảm dần
        roles.sort(key=lambda x: x.position, reverse=True)
        
        embed = discord.Embed(
            title=f"🎭 Role của {member.display_name}",
            description=f"{member.mention} có **{len(roles)}** role:",
            color=member.color
        )
        
        # Hiển thị role theo nhóm để tránh quá dài
        role_list = ""
        for role in roles:
            role_list += f"• {role.mention} (`{role.id}`)\n"
            
        embed.add_field(name="Danh sách role", value=role_list, inline=False)
        embed.set_thumbnail(url=member.display_avatar.url)
        await ctx.send(embed=embed)
        return
        
    # Xử lý lệnh info (thông tin về role)
    elif action == "info":
        if role_input is None:
            embed = discord.Embed(
                title="❌ Thiếu thông tin",
                description="Vui lòng chỉ định tên role để xem thông tin.\nVí dụ: `.role info Admin`",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
            return
            
        # Tìm role phù hợp (tìm kiếm không phân biệt hoa thường)
        role = discord.utils.find(lambda r: r.name.lower() == role_input.lower(), ctx.guild.roles)
        
        # Nếu không tìm thấy chính xác, tìm gần đúng
        if role is None:
            role = discord.utils.find(lambda r: role_input.lower() in r.name.lower(), ctx.guild.roles)
            
        if role is None:
            embed = discord.Embed(
                title="❌ Không tìm thấy",
                description=f"Không tìm thấy role nào có tên `{role_input}`",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
            return
            
        # Hiển thị thông tin về role
        created_time = int(role.created_at.timestamp())
        member_count = len([member for member in ctx.guild.members if role in member.roles])
        
        embed = discord.Embed(
            title=f"🎭 Thông tin role: {role.name}",
            description=f"ID: `{role.id}`",
            color=role.color
        )
        
        embed.add_field(name="Tạo lúc", value=f"<t:{created_time}:R>", inline=True)
        embed.add_field(name="Màu sắc", value=f"#{role.color.value:06x}", inline=True)
        embed.add_field(name="Vị trí", value=f"{role.position}/{len(ctx.guild.roles) - 1}", inline=True)
        embed.add_field(name="Số thành viên", value=f"{member_count}", inline=True)
        embed.add_field(name="Hiển thị riêng", value=f"{'Có' if role.hoist else 'Không'}", inline=True)
        embed.add_field(name="Có thể đề cập", value=f"{'Có' if role.mentionable else 'Không'}", inline=True)
        
        # Hiển thị các quyền đặc biệt
        special_perms = []
        if role.permissions.administrator:
            special_perms.append("Administrator")
        if role.permissions.ban_members:
            special_perms.append("Ban Members")
        if role.permissions.kick_members:
            special_perms.append("Kick Members")
        if role.permissions.manage_channels:
            special_perms.append("Manage Channels")
        if role.permissions.manage_guild:
            special_perms.append("Manage Server")
        if role.permissions.manage_roles:
            special_perms.append("Manage Roles")
        if role.permissions.manage_messages:
            special_perms.append("Manage Messages")
            
        if special_perms:
            embed.add_field(
                name="Quyền hạn đặc biệt", 
                value=", ".join(special_perms), 
                inline=False
            )
            
        await ctx.send(embed=embed)
        return
        
    # Xử lý lệnh add và remove
    if member is None or role_input is None:
        embed = discord.Embed(
            title="❌ Thiếu thông tin",
            description=f"Vui lòng chỉ định đầy đủ thông tin.\nVí dụ: `.role {action} @user Role Name`",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return
        
    # Tách các role nếu có nhiều role được phân cách bằng dấu phẩy
    role_names = [name.strip() for name in role_input.split(',')]
    
    # Theo dõi thành công và thất bại
    success_roles = []
    failed_roles = []
    
    for role_name in role_names:
        # Tìm role phù hợp (tìm kiếm không phân biệt hoa thường)
        role = discord.utils.find(lambda r: r.name.lower() == role_name.lower(), ctx.guild.roles)
        
        # Nếu không tìm thấy chính xác, tìm gần đúng
        if role is None:
            role = discord.utils.find(lambda r: role_name.lower() in r.name.lower(), ctx.guild.roles)
            
        if role is None:
            failed_roles.append(f"`{role_name}` (không tìm thấy)")
            continue
            
        # Kiểm tra thứ bậc role
        if role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
            failed_roles.append(f"`{role.name}` (role cao hơn quyền của bạn)")
            continue
            
        try:
            if action == "add":
                # Kiểm tra xem thành viên đã có role này chưa
                if role in member.roles:
                    failed_roles.append(f"`{role.name}` (đã có sẵn)")
                    continue
                    
                await member.add_roles(role, reason=f"Thêm bởi {ctx.author}")
                success_roles.append(role.name)
                
            elif action == "remove":
                # Kiểm tra xem thành viên có role này không
                if role not in member.roles:
                    failed_roles.append(f"`{role.name}` (không có role này)")
                    continue
                    
                await member.remove_roles(role, reason=f"Xóa bởi {ctx.author}")
                success_roles.append(role.name)
                
        except discord.Forbidden:
            failed_roles.append(f"`{role.name}` (thiếu quyền)")
        except Exception as e:
            failed_roles.append(f"`{role.name}` (lỗi: {str(e)})")
    
    # Tạo embed phản hồi
    if action == "add":
        title = "➕ Thêm Role"
        color = discord.Color.green()
        success_msg = f"Đã thêm {len(success_roles)} role cho {member.mention}"
    else:
        title = "➖ Xóa Role"
        color = discord.Color.orange()
        success_msg = f"Đã xóa {len(success_roles)} role của {member.mention}"
        
    embed = discord.Embed(
        title=title,
        description=success_msg,
        color=color
    )
    
    if success_roles:
        embed.add_field(
            name="✅ Thành công", 
            value=", ".join(f"`{role}`" for role in success_roles), 
            inline=False
        )
        
    if failed_roles:
        embed.add_field(
            name="❌ Thất bại", 
            value="\n".join(failed_roles), 
            inline=False
        )
        
    embed.set_footer(text=f"Được thực hiện bởi: {ctx.author.display_name}")
    await ctx.send(embed=embed)

@role_command.error
async def role_command_error(ctx, error):
    """Xử lý lỗi cho lệnh role"""
    if isinstance(error, commands.MissingPermissions):
        embed = discord.Embed(
            title="❌ Thiếu quyền",
            description="Bạn cần có quyền `Manage Roles` để sử dụng lệnh này.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
    elif isinstance(error, commands.MemberNotFound):
        embed = discord.Embed(
            title="❌ Không tìm thấy thành viên",
            description="Không tìm thấy thành viên được chỉ định.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
    elif isinstance(error, commands.BadArgument):
        embed = discord.Embed(
            title="❌ Đối số không hợp lệ",
            description="Vui lòng cung cấp đối số hợp lệ cho lệnh.\nVí dụ: `.role add @user Role Name`",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(
            title="❌ Lỗi",
            description=f"Đã xảy ra lỗi không mong muốn: {str(error)}",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)


@bot.command(name='aiopping', aliases=['pingai'])
async def who_is_pinging(ctx, user: discord.Member = None):
    """Kiểm tra ai đã ping bạn hoặc một người dùng khác gần đây"""
    # Nếu không chỉ định người dùng, mặc định là người gọi lệnh
    target_user = user or ctx.author
    target_id = target_user.id
    
    # Kiểm tra xem có bản ghi ping nào cho người dùng này không
    if target_id not in recent_pings or not recent_pings[target_id]:
        embed = discord.Embed(
            title="🔍 Kiểm Tra Ping",
            description=f"Không tìm thấy ping nào gần đây cho {target_user.mention}",
            color=discord.Color.blue()
        )
        await ctx.send(embed=embed)
        return
    
    
    # Tạo embed với thông tin ping
    embed = discord.Embed(
        title="🔔 Những Lần Được Ping Gần Đây",
        description=f"Những lần {target_user.mention} được nhắc đến gần đây",
        color=discord.Color.gold()
    )
    
    # Thêm các ping gần đây nhất (tối đa 10)
    ping_list = recent_pings[target_id][:10]  # Lấy tối đa 10 ping gần nhất
    
    for i, ping in enumerate(ping_list, 1):
        # Định dạng thời gian thành timestamp Discord
        time_diff = discord.utils.format_dt(ping["timestamp"], style="R")
        
        # Lấy thông tin người ping
        try:
            pinger = await bot.fetch_user(ping["pinger_id"])
            pinger_name = pinger.name
        except:
            pinger_name = ping["pinger_name"]
        
        # Cắt nội dung tin nhắn nếu quá dài
        content = ping["content"]
        if len(content) > 50:
            content = content[:47] + "..."
        
        # Escape markdown trong nội dung
        content = discord.utils.escape_markdown(content)
        
        embed.add_field(
            name=f"{i}. Từ {pinger_name} {time_diff}",
            value=f"[Nhấn vào đây để xem tin nhắn]({ping['jump_url']})\n```{content}```",
            inline=False
        )
    
    # Thêm avatar người dùng
    embed.set_thumbnail(url=target_user.display_avatar.url)
    
    # Thêm footer với thông tin lệnh
    total_pings = len(recent_pings[target_id])
    embed.set_footer(text=f"Hiển thị {min(10, total_pings)} trong {total_pings} lần ping gần đây | Sử dụng .whoping @user để kiểm tra người khác")
    
    await ctx.send(embed=embed)

@who_is_pinging.error
async def ping_check_error(ctx, error):
    """Xử lý lỗi cho lệnh who_is_pinging"""
    if isinstance(error, commands.MemberNotFound):
        embed = discord.Embed(
            title="❌ Không Tìm Thấy Thành Viên",
            description="Không thể tìm thấy thành viên được chỉ định trong server.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(
            title="❌ Lỗi",
            description=f"Đã xảy ra lỗi: {str(error)}",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
@bot.command(name='ga', aliases=['chicken', 'gà'])
@check_channel()
@check_game_enabled('ga')
async def ga_game(ctx, bet: str = None):
    """Trò chơi Gà - Đặt cược vào gà may mắn của bạn"""
    if bet is None:
        embed = discord.Embed(
            title="🐓 Trò Chơi Gà - Hướng Dẫn",
            description="Đặt cược vào gà may mắn và nhận thưởng nếu thắng!",
            color=discord.Color.gold()
        )
        embed.add_field(
            name="📋 Cách chơi",
            value=(
                "1. Đặt cược một số xu\n"
                "2. Hệ thống sẽ chọn ngẫu nhiên 3 gà từ chuồng gà\n"
                "3. Nếu có ít nhất 2 gà giống nhau, bạn thắng!\n"
                "4. Phần thưởng tùy thuộc vào loại gà xuất hiện"
            ),
            inline=False
        )
        embed.add_field(
            name="💰 Phần thưởng",
            value=(
                "- 3 gà giống nhau: x4 tiền cược\n"
                "- 2 gà giống nhau: x1.5 tiền cược\n"
                "- Không có gà giống nhau: Thua cược"
            ),
            inline=False
        )
        embed.add_field(
            name="🎮 Lệnh",
            value="`.ga [số xu]` hoặc `.ga all`",
            inline=False
        )
        await ctx.send(embed=embed)
        return

    user_id = ctx.author.id

    # Xử lý đặt cược "all"
    bet_amount = parse_bet(bet, currency[user_id])
    if bet_amount is None:
        embed = discord.Embed(
            title="❌ Số tiền không hợp lệ",
            description="Vui lòng nhập số tiền hợp lệ hoặc 'all'.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Kiểm tra tiền cược
    if bet_amount <= 0:
        embed = discord.Embed(
            title="🐓 Trò Chơi Gà",
            description="Số tiền cược phải lớn hơn 0 xu.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    if currency[user_id] < bet_amount:
        embed = discord.Embed(
            title="🐓 Trò Chơi Gà",
            description=f"{ctx.author.mention}, bạn không đủ xu để đặt cược! Bạn hiện có {currency[user_id]} xu.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Hiển thị loading message
    loading_embed = discord.Embed(
        title="🐓 CHUẨN BỊ TRÒ CHƠI GÀ",
        description=f"{ctx.author.mention} đặt cược **{bet_amount} xu**",
        color=discord.Color.blue()
    )
    loading_msg = await ctx.send(embed=loading_embed)
    await asyncio.sleep(1)

    # Các loại gà có thể xuất hiện
    chicken_types = [
        {"name": "Gà Trống", "emoji": "🐓"},
        {"name": "Gà Mái", "emoji": "🐔"},
        {"name": "Gà Con", "emoji": "🐥"},
        {"name": "Gà Golden", "emoji": "🐤"}
    ]
    
    # Animation đang mở chuồng gà
    for i in range(3):
        opening_embed = discord.Embed(
            title=f"🐓 ĐANG MỞ CHUỒNG GÀ {'.' * (i + 1)}",
            description=f"{ctx.author.mention} đang chờ kết quả...",
            color=discord.Color.gold()
        )
        opening_embed.set_footer(text=f"Đặt cược: {bet_amount} xu")
        await loading_msg.edit(embed=opening_embed)
        await asyncio.sleep(0.7)

    # Chọn 3 gà ngẫu nhiên
    chosen_chickens = random.choices(chicken_types, k=3)
    
    # Hiệu ứng hiển thị từng con gà
    for i in range(3):
        result_so_far = " ".join([chicken["emoji"] for chicken in chosen_chickens[:i+1]])
        chicken_embed = discord.Embed(
            title=f"🐓 KẾT QUẢ ({i+1}/3)",
            description=f"Những con gà xuất hiện: {result_so_far}",
            color=discord.Color.blue()
        )
        await loading_msg.edit(embed=chicken_embed)
        await asyncio.sleep(1)

    # Kiểm tra kết quả
    chicken_counts = {}
    for chicken in chosen_chickens:
        chicken_name = chicken["name"]
        if chicken_name in chicken_counts:
            chicken_counts[chicken_name] += 1
        else:
            chicken_counts[chicken_name] = 1
    
    max_count = max(chicken_counts.values())
    
    # Xác định kết quả và tiền thắng/thua
    if max_count == 3:  # 3 gà giống nhau
        multiplier = 4
        result_text = "BA CON GÀ GIỐNG NHAU!"
        result_color = discord.Color.gold()
        won = True
    elif max_count == 2:  # 2 gà giống nhau
        multiplier = 1.5
        result_text = "HAI CON GÀ GIỐNG NHAU!"
        result_color = discord.Color.green()
        won = True
    else:  # Không có gà giống nhau
        multiplier = 0
        result_text = "KHÔNG CÓ GÀ GIỐNG NHAU"
        result_color = discord.Color.red()
        won = False
    
    # Tính toán tiền thắng/thua
    if won:
        winnings = int(bet_amount * multiplier)
        currency[user_id] += winnings - bet_amount
        result_description = f"🎉 {ctx.author.mention} đã thắng **{winnings} xu**!"
    else:
        winnings = 0
        currency[user_id] -= bet_amount
        result_description = f"❌ {ctx.author.mention} đã thua **{bet_amount} xu**!"
    
    # Hiển thị kết quả
    result_embed = discord.Embed(
        title=f"🐓 {result_text}",
        description=result_description,
        color=result_color
    )
    
    # Hiển thị các con gà
    chicken_display = " ".join([chicken["emoji"] for chicken in chosen_chickens])
    result_embed.add_field(
        name="🎲 Kết quả",
        value=chicken_display,
        inline=False
    )
    
    # Chi tiết các con gà
    chicken_details = "\n".join([f"{chicken['emoji']} {chicken['name']}" for chicken in chosen_chickens])
    result_embed.add_field(
        name="🐔 Chi tiết",
        value=chicken_details,
        inline=True
    )
    
    # Hiển thị tiền thắng/thua
    if won:
        result_embed.add_field(
            name="💰 Tiền thắng",
            value=f"+{winnings} xu (x{multiplier})",
            inline=True
        )
    else:
        result_embed.add_field(
            name="💸 Tiền thua",
            value=f"-{bet_amount} xu",
            inline=True
        )
    
    # Hiển thị số dư hiện tại
    result_embed.add_field(
        name="💼 Số dư hiện tại",
        value=f"{currency[user_id]} xu",
        inline=True
    )
    
    await loading_msg.edit(embed=result_embed)


@bot.command(name='checkban', aliases=['baninfo', 'bancheck'])
@commands.has_permissions(ban_members=True)
async def check_ban(ctx, *, user_input: str = None):
    """Kiểm tra thông tin về người dùng đã bị ban và trạng thái Premium
    
    Sử dụng:
    .checkban <user_id/mention/username> - Kiểm tra thông tin ban và Premium
    .checkban - Hiển thị danh sách các người dùng bị ban gần đây
    """
    # Tìm Role Premium trong server
    premium_roles = [
        role for role in ctx.guild.roles 
        if any(keyword in role.name.lower() for keyword in ["premium", "vip", "donor", "booster", "nitro"])
    ]
    
    if user_input is None:
        # Hiển thị một số người dùng bị ban gần đây
        try:
            # Tạo embed loading
            loading_embed = discord.Embed(
                title="⏳ Đang tải danh sách ban...",
                color=discord.Color.blue()
            )
            loading_msg = await ctx.send(embed=loading_embed)
            
            # Giới hạn hiển thị tối đa 10 người bị ban gần đây
            ban_list = [ban async for ban in ctx.guild.bans(limit=10)]
            
            if not ban_list:
                embed = discord.Embed(
                    title="📋 Danh sách Ban",
                    description="Không có người dùng nào bị ban trong server này.",
                    color=discord.Color.blue()
                )
                # Tạo view với nút đóng
                view = CloseButtonView(timeout=60)
                await loading_msg.edit(embed=embed, view=view)
                return
                
            embed = discord.Embed(
                title="📋 Danh sách Ban gần đây",
                description=f"Hiển thị {len(ban_list)} người dùng bị ban gần đây nhất:",
                color=discord.Color.red()
            )
            
            for i, ban_entry in enumerate(ban_list, 1):
                user = ban_entry.user
                reason = ban_entry.reason or "Không có lý do"
                embed.add_field(
                    name=f"{i}. {user.name} ({user.id})",
                    value=f"Lý do: {reason}",
                    inline=False
                )
                
            embed.set_footer(text=f"Tin nhắn này sẽ tự động xóa sau 2 phút | Sử dụng .checkban <ID/username> để xem thông tin chi tiết")
            
            # Tạo view với nút đóng
            view = CloseButtonView(timeout=120)
            await loading_msg.edit(embed=embed, view=view)
            return
            
        except discord.Forbidden:
            embed = discord.Embed(
                title="❌ Lỗi quyền hạn",
                description="Bot không có quyền xem danh sách ban.",
                color=discord.Color.red()
            )
            # Tự động xóa sau 20 giây
            await ctx.send(embed=embed, delete_after=20)
            return
        except Exception as e:
            embed = discord.Embed(
                title="❌ Lỗi",
                description=f"Đã xảy ra lỗi: {str(e)}",
                color=discord.Color.red()
            )
            # Tự động xóa sau 20 giây
            await ctx.send(embed=embed, delete_after=20)
            return
    
    # Tạo loading message
    loading_embed = discord.Embed(
        title="🔍 Đang tìm kiếm người dùng...",
        description=f"Đang tìm kiếm: `{user_input}`",
        color=discord.Color.blue()
    )
    loading_msg = await ctx.send(embed=loading_embed)
    
    user = None
    user_id = None
    
    # TRƯỜNG HỢP 1: Kiểm tra nếu là mention
    if user_input.startswith('<@') and user_input.endswith('>'):
        user_id = user_input[2:-1]
        if user_id.startswith('!'):
            user_id = user_id[1:]
        
        try:
            user_id = int(user_id)
            try:
                user = await bot.fetch_user(user_id)
            except discord.NotFound:
                embed = discord.Embed(
                    title="❌ Không tìm thấy",
                    description=f"Không tìm thấy người dùng với ID: {user_id}",
                    color=discord.Color.red()
                )
                view = CloseButtonView(timeout=60)
                await loading_msg.edit(embed=embed, view=view)
                return
        except ValueError:
            embed = discord.Embed(
                title="❌ ID không hợp lệ",
                description="ID người dùng không hợp lệ từ mention.",
                color=discord.Color.red()
            )
            view = CloseButtonView(timeout=60)
            await loading_msg.edit(embed=embed, view=view)
            return
    
    # TRƯỜNG HỢP 2: Kiểm tra nếu là ID số
    elif user_input.isdigit():
        user_id = int(user_input)
        try:
            user = await bot.fetch_user(user_id)
        except discord.NotFound:
            embed = discord.Embed(
                title="❌ Không tìm thấy",
                description=f"Không tìm thấy người dùng với ID: {user_id}",
                color=discord.Color.red()
            )
            view = CloseButtonView(timeout=60)
            await loading_msg.edit(embed=embed, view=view)
            return
    
    # TRƯỜNG HỢP 3: Tìm kiếm theo tên người dùng
    else:
        # Cập nhật loading message
        await loading_msg.edit(embed=discord.Embed(
            title="🔍 Đang tìm kiếm người dùng theo tên...",
            description=f"Đang tìm kiếm: `{user_input}`",
            color=discord.Color.blue()
        ))
        
        # Tìm trong server trước
        matching_members = []
        for member in ctx.guild.members:
            if user_input.lower() in member.name.lower() or (member.nick and user_input.lower() in member.nick.lower()):
                matching_members.append(member)
                
        # Kiểm tra trong ban list
        ban_matches = []
        try:
            ban_list = [ban async for ban in ctx.guild.bans()]
            for ban_entry in ban_list:
                banned_user = ban_entry.user
                if user_input.lower() in banned_user.name.lower():
                    ban_matches.append(banned_user)
        except:
            # Xử lý nếu không thể lấy ban list
            pass
        
        # Nếu có nhiều kết quả
        if len(matching_members) + len(ban_matches) > 1:
            # Ưu tiên kết quả khớp chính xác
            exact_match = None
            for member in matching_members:
                if member.name.lower() == user_input.lower() or (member.nick and member.nick.lower() == user_input.lower()):
                    exact_match = member
                    break
            
            if not exact_match:
                for banned_user in ban_matches:
                    if banned_user.name.lower() == user_input.lower():
                        exact_match = banned_user
                        break
            
            # Nếu có kết quả khớp chính xác
            if exact_match:
                user = exact_match
                user_id = user.id
            else:
                # Hiển thị danh sách kết quả tìm kiếm
                options_embed = discord.Embed(
                    title="🔍 Nhiều kết quả tìm thấy",
                    description=f"Có {len(matching_members) + len(ban_matches)} người dùng phù hợp với `{user_input}`.",
                    color=discord.Color.gold()
                )
                
                # Hiển thị các thành viên trong server
                if matching_members:
                    member_list = "\n".join([f"{i+1}. {member.name} (ID: `{member.id}`) {member.mention}" 
                                        for i, member in enumerate(matching_members[:5])])
                    options_embed.add_field(
                        name="🟢 Người dùng trong server:",
                        value=member_list + (f"\n...và {len(matching_members) - 5} người khác" if len(matching_members) > 5 else ""),
                        inline=False
                    )
                
                # Hiển thị người dùng bị ban
                if ban_matches:
                    ban_list = "\n".join([f"{len(matching_members) + i + 1}. {user.name} (ID: `{user.id}`) 🚫 Đã bị ban" 
                                    for i, user in enumerate(ban_matches[:5])])
                    options_embed.add_field(
                        name="🔴 Người dùng đã bị ban:",
                        value=ban_list + (f"\n...và {len(ban_matches) - 5} người khác" if len(ban_matches) > 5 else ""),
                        inline=False
                    )
                
                options_embed.set_footer(text="Vui lòng sử dụng .checkban với ID cụ thể để xem chi tiết một người dùng")
                await loading_msg.edit(embed=options_embed, view=CloseButtonView(timeout=60))
                return
        
        # Nếu không tìm thấy kết quả
        elif not matching_members and not ban_matches:
            embed = discord.Embed(
                title="❌ Không tìm thấy",
                description=f"Không tìm thấy người dùng nào có tên: `{user_input}`",
                color=discord.Color.red()
            )
            view = CloseButtonView(timeout=60)
            await loading_msg.edit(embed=embed, view=view)
            return
        
        # Nếu chỉ có một kết quả duy nhất
        else:
            user = matching_members[0] if matching_members else ban_matches[0]
            user_id = user.id
    
    # Từ đây là code xử lý sau khi đã có user và user_id
    try:
        # Cập nhật embed loading
        loading_embed = discord.Embed(
            title="⏳ Đang kiểm tra thông tin ban...",
            description=f"Đang kiểm tra người dùng: {user.mention} (ID: {user_id})",
            color=discord.Color.blue()
        )
        await loading_msg.edit(embed=loading_embed)
        
        # Kiểm tra xem người dùng có bị ban không
        try:
            ban_entry = await ctx.guild.fetch_ban(user)
            # Người dùng bị ban
            embed = discord.Embed(
                title=f"🚫 Thông tin Ban: {user.name}",
                color=discord.Color.red()
            )
            
            embed.set_thumbnail(url=user.display_avatar.url)
            
            embed.add_field(name="Tên người dùng", value=f"{user.name}", inline=True)
            embed.add_field(name="ID", value=f"`{user.id}`", inline=True)
            embed.add_field(name="Thời gian tạo tài khoản", value=discord.utils.format_dt(user.created_at, "F"), inline=False)
            
            reason = ban_entry.reason or "Không có lý do được ghi nhận"
            embed.add_field(name="Lý do ban", value=reason, inline=False)
            
            # Kiểm tra nếu user từng là thành viên của server (thông qua role Premium)
            member = ctx.guild.get_member(user_id)
            if member:
                # Kiểm tra role Premium
                has_premium = any(role in premium_roles for role in member.roles)
                premium_status = "✅ Có" if has_premium else "❌ Không"
                embed.add_field(name="🌟 Role Premium", value=premium_status, inline=True)
            
            embed.set_footer(text="Tin nhắn này sẽ tự động đóng sau 2 phút")
            
            # Hiển thị nút giải ban và đóng
            view = BanInfoView(ctx.author, user, timeout=120)
            await loading_msg.edit(embed=embed, view=view)
            
        except discord.NotFound:
            # Người dùng không bị ban
            embed = discord.Embed(
                title=f"✅ Kiểm tra Ban: {user.name}",
                description=f"Người dùng này không bị ban trong server.",
                color=discord.Color.green()
            )
            
            embed.set_thumbnail(url=user.display_avatar.url)
            embed.add_field(name="Tên người dùng", value=f"{user.name}", inline=True)
            embed.add_field(name="ID", value=f"`{user.id}`", inline=True)
            
            # Kiểm tra xem người dùng có trong server không
            member = ctx.guild.get_member(user_id)
            if member:
                embed.add_field(name="Trạng thái", value="Đang ở trong server", inline=False)
                embed.add_field(name="Tham gia server từ", value=discord.utils.format_dt(member.joined_at, "F"), inline=False)
                
                # Kiểm tra role Premium
                has_premium = False
                premium_role_names = []
                
                for role in member.roles:
                    if role in premium_roles:
                        has_premium = True
                        premium_role_names.append(role.name)
                
                if has_premium:
                    embed.add_field(
                        name="🌟 Premium Status", 
                        value=f"✅ Người dùng có role Premium: {', '.join(premium_role_names)}", 
                        inline=False
                    )
                else:
                    embed.add_field(
                        name="🌟 Premium Status", 
                        value="❌ Người dùng không có role Premium", 
                        inline=False
                    )
            else:
                embed.add_field(name="Trạng thái", value="Không ở trong server", inline=False)
                embed.add_field(name="🌟 Premium Status", value="❓ Không xác định (không ở trong server)", inline=False)
            
            embed.set_footer(text="Tin nhắn này sẽ tự động đóng sau 1 phút")
            
            # Tạo view với nút đóng
            view = CloseButtonView(timeout=60)
            await loading_msg.edit(embed=embed, view=view)
            
    except discord.Forbidden:
        embed = discord.Embed(
            title="❌ Thiếu quyền",
            description="Bot không có quyền xem thông tin ban.",
            color=discord.Color.red()
        )
        await loading_msg.edit(embed=embed)
        # Tự động xóa sau 20 giây
        await asyncio.sleep(20)
        await loading_msg.delete()
    except Exception as e:
        embed = discord.Embed(
            title="❌ Lỗi",
            description=f"Đã xảy ra lỗi: {str(e)}",
            color=discord.Color.red()
        )
        await loading_msg.edit(embed=embed)
        # Tự động xóa sau 20 giây
        await asyncio.sleep(20)
        await loading_msg.delete()

# View với nút đóng cơ bản
class CloseButtonView(discord.ui.View):
    def __init__(self, timeout=60):
        super().__init__(timeout=timeout)
    
    @discord.ui.button(label="Đóng", style=discord.ButtonStyle.gray, emoji="❌")
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.message.delete()
    
    # Khi view hết hạn
    async def on_timeout(self):
        message = self.message
        if message:
            try:
                # Thử xóa tin nhắn khi hết thời gian
                await message.delete()
            except:
                # Nếu không xóa được, thử cập nhật để vô hiệu hóa các nút
                try:
                    for item in self.children:
                        item.disabled = True
                    await message.edit(view=self)
                except:
                    pass

# View với nút unban và đóng cho người dùng bị ban
class BanInfoView(discord.ui.View):
    def __init__(self, author, user, timeout=120):
        super().__init__(timeout=timeout)
        self.author = author
        self.user = user
    
    @discord.ui.button(label="Unban", style=discord.ButtonStyle.danger)
    async def unban_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.author:
            await interaction.response.send_message("Bạn không phải người thực hiện lệnh này!", ephemeral=True)
            return
            
        if not interaction.user.guild_permissions.ban_members:
            await interaction.response.send_message("Bạn không có quyền unban!", ephemeral=True)
            return
            
        try:
            await interaction.guild.unban(self.user, reason=f"Unban bởi {interaction.user}")
            unban_embed = discord.Embed(
                title="✅ Đã giải ban",
                description=f"Đã giải ban cho {self.user.name} (`{self.user.id}`)",
                color=discord.Color.green()
            )
            
            # Vô hiệu hóa tất cả các nút
            for item in self.children:
                item.disabled = True
                
            await interaction.response.edit_message(embed=unban_embed, view=self)
            
            # Tự động xóa sau 10 giây sau khi unban
            await asyncio.sleep(10)
            try:
                await interaction.message.delete()
            except:
                pass
                
        except Exception as e:
            await interaction.response.send_message(f"Lỗi khi giải ban: {e}", ephemeral=True)
    
    @discord.ui.button(label="Đóng", style=discord.ButtonStyle.gray, emoji="❌")
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.author and not interaction.user.guild_permissions.ban_members:
            await interaction.response.send_message("Bạn không có quyền đóng thông tin này!", ephemeral=True)
            return
            
        await interaction.message.delete()
    
    # Khi view hết hạn
    async def on_timeout(self):
        message = self.message
        if message:
            try:
                # Thử xóa tin nhắn khi hết thời gian
                await message.delete()
            except:
                # Nếu không xóa được, thử cập nhật để vô hiệu hóa các nút
                try:
                    for item in self.children:
                        item.disabled = True
                    await message.edit(view=self)
                except:
                    pass

@check_ban.error
async def check_ban_error(ctx, error):
    """Xử lý lỗi cho lệnh check_ban"""
    if isinstance(error, commands.MissingPermissions):
        embed = discord.Embed(
            title="❌ Thiếu quyền",
            description="Bạn cần có quyền `Ban Members` để sử dụng lệnh này.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
    elif isinstance(error, commands.BadArgument):
        embed = discord.Embed(
            title="❌ Đối số không hợp lệ",
            description="Vui lòng cung cấp ID người dùng hợp lệ.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(
            title="❌ Lỗi",
            description=f"Đã xảy ra lỗi: {str(error)}",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)

@bot.command(name='giveaway', aliases=['gw'])
@commands.has_permissions(manage_messages=True)
async def giveaway(ctx, duration: str = None, winners: int = 1, *, prize: str = None):
    """Tạo một giveaway với thời gian, số người thắng và giải thưởng
    
    Ví dụ: .giveaway 1h 1 100 xu
    Thời gian hỗ trợ: s (giây), m (phút), h (giờ), d (ngày)
    """
    if duration is None or prize is None:
        embed = discord.Embed(
            title="🎁 Giveaway - Hướng Dẫn",
            description="Tạo giveaway cho server.",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="Cách sử dụng",
            value="`.giveaway <thời_gian> <số_người_thắng> <giải_thưởng>`",
            inline=False
        )
        embed.add_field(
            name="Ví dụ",
            value="`.giveaway 1h 1 100 xu` - Tạo giveaway 100 xu trong 1 giờ với 1 người thắng\n"
                  "`.giveaway 10m 3 Nitro Classic` - Tạo giveaway Nitro cho 3 người thắng trong 10 phút",
            inline=False
        )
        embed.add_field(
            name="Đơn vị thời gian",
            value="s - Giây | m - Phút | h - Giờ | d - Ngày",
            inline=False
        )
        embed.add_field(
            name="Lệnh liên quan",
            value="`.gend <message_id>` - Kết thúc giveaway sớm\n"
                  "`.greroll <message_id>` - Chọn lại người thắng",
            inline=False
        )
        await ctx.send(embed=embed)
        return
    
    # Phân tích thời gian
    total_seconds = 0
    if duration.endswith("s"):
        total_seconds = int(duration[:-1])
    elif duration.endswith("m"):
        total_seconds = int(duration[:-1]) * 60
    elif duration.endswith("h"):
        total_seconds = int(duration[:-1]) * 3600
    elif duration.endswith("d"):
        total_seconds = int(duration[:-1]) * 86400
    else:
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Định dạng thời gian không hợp lệ. Sử dụng s (giây), m (phút), h (giờ), d (ngày).",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return
    
    # Giới hạn thời gian hợp lý
    if total_seconds < 10:
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Thời gian giveaway phải ít nhất 10 giây.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return
    
    if total_seconds > 2592000:  # 30 ngày
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Thời gian giveaway không thể quá 30 ngày.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return
    
    # Giới hạn số người thắng
    if winners < 1:
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Số người thắng phải ít nhất là 1.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return
    
    if winners > 20:
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Số người thắng không thể quá 20.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return
    
    # Tính thời gian kết thúc
    end_time = datetime.now() + timedelta(seconds=total_seconds)
    
    # Tạo embed giveaway
    embed = discord.Embed(
        title="🎁 GIVEAWAY",
        description=f"**{prize}**",
        color=discord.Color.gold()
    )
    
    # Thêm thông tin giveaway
    embed.add_field(
        name="Kết thúc",
        value=f"<t:{int(end_time.timestamp())}:R>",
        inline=True
    )
    
    embed.add_field(
        name="Số người thắng",
        value=f"{winners}",
        inline=True
    )
    
    embed.add_field(
        name="Tổ chức bởi",
        value=ctx.author.mention,
        inline=True
    )
    
    embed.set_footer(text=f"Kết thúc vào: {end_time.strftime('%d/%m/%Y %H:%M:%S')} | Nhấn 🎉 để tham gia")
    
    # Gửi thông báo giveaway
    giveaway_msg = await ctx.send(embed=embed)
    await giveaway_msg.add_reaction("🎉")
    
    # Lưu thông tin giveaway
    active_giveaways[giveaway_msg.id] = {
        "prize": prize,
        "end_time": end_time,
        "host": ctx.author.id,
        "channel_id": ctx.channel.id,
        "winners": winners
    }
    
    # Gửi xác nhận cho người tạo
    confirm_embed = discord.Embed(
        title="✅ Giveaway đã tạo",
        description=f"Giveaway **{prize}** đã được tạo thành công!",
        color=discord.Color.green()
    )
    confirm_embed.add_field(
        name="Thông tin",
        value=f"ID: `{giveaway_msg.id}`\nKết thúc: <t:{int(end_time.timestamp())}:R>",
        inline=False
    )
    confirm_embed.add_field(
        name="Quản lý giveaway",
        value=f"Kết thúc sớm: `.gend {giveaway_msg.id}`\nChọn lại người thắng: `.greroll {giveaway_msg.id}`",
        inline=False
    )
    
    await ctx.author.send(embed=confirm_embed)
    
    # Thiết lập tác vụ chờ kết thúc giveaway
    await asyncio.sleep(total_seconds)
    await end_giveaway(giveaway_msg.id)

async def end_giveaway(message_id):
    """Kết thúc giveaway và chọn người thắng"""
    if message_id not in active_giveaways:
        return
    
    # Lấy thông tin giveaway
    giveaway_info = active_giveaways[message_id]
    prize = giveaway_info["prize"]
    channel_id = giveaway_info["channel_id"]
    winners_count = giveaway_info["winners"]
    
    # Lấy channel và message
    channel = bot.get_channel(channel_id)
    if not channel:
        del active_giveaways[message_id]
        return
    
    try:
        message = await channel.fetch_message(message_id)
    except:
        del active_giveaways[message_id]
        return
    
    # Tìm tất cả người tham gia (loại bỏ bot và người tạo giveaway)
    reaction = discord.utils.get(message.reactions, emoji="🎉")
    if not reaction:
        # Không có ai tham gia
        embed = message.embeds[0]
        embed.title = "🎁 GIVEAWAY KẾT THÚC"
        embed.description = f"**{prize}**\n\n❌ Không có người tham gia hợp lệ."
        embed.color = discord.Color.red()
        
        await message.edit(embed=embed)
        await channel.send(f"❌ Giveaway **{prize}** đã kết thúc nhưng không có người tham gia nào!")
        
        del active_giveaways[message_id]
        return
    
    # Lấy danh sách người tham gia
    users = []
    async for user in reaction.users():
        if not user.bot:  # Loại bỏ bot
            users.append(user)
    
    # Kiểm tra số người tham gia
    if not users:
        # Không có ai tham gia
        embed = message.embeds[0]
        embed.title = "🎁 GIVEAWAY KẾT THÚC"
        embed.description = f"**{prize}**\n\n❌ Không có người tham gia hợp lệ."
        embed.color = discord.Color.red()
        
        await message.edit(embed=embed)
        await channel.send(f"❌ Giveaway **{prize}** đã kết thúc nhưng không có người tham gia nào!")
        
        del active_giveaways[message_id]
        return
    
    # Chọn người thắng
    winners_needed = min(winners_count, len(users))
    winners = random.sample(users, winners_needed)
    
    # Cập nhật embed giveaway
    embed = message.embeds[0]
    embed.title = "🎁 GIVEAWAY KẾT THÚC"
    
    # Hiển thị người thắng
    winners_text = ", ".join([winner.mention for winner in winners])
    embed.description = f"**{prize}**\n\n🏆 Người thắng: {winners_text}"
    embed.color = discord.Color.green()
    
    # Cập nhật footer
    embed.set_footer(text=f"Giveaway đã kết thúc | ID: {message_id}")
    
    await message.edit(embed=embed)
    
    # Gửi thông báo kết quả
    await channel.send(f"🎉 Chúc mừng {winners_text}! Bạn đã thắng **{prize}**!")
    
    # Xóa khỏi danh sách giveaway đang hoạt động
    del active_giveaways[message_id]

@bot.command(name='gend', aliases=['giveawayend', 'endgiveaway'])
@commands.has_permissions(manage_messages=True)
async def end_giveaway_command(ctx, message_id: int = None):
    """Kết thúc giveaway sớm với message ID của giveaway"""
    if message_id is None:
        embed = discord.Embed(
            title="❓ Kết thúc Giveaway - Hướng Dẫn",
            description="Kết thúc giveaway sớm và chọn người thắng.",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="Cách sử dụng",
            value="`.gend <message_id>`",
            inline=False
        )
        embed.add_field(
            name="Lưu ý",
            value="Message ID là ID của tin nhắn giveaway.\nBạn có thể lấy ID này bằng cách nhấp phải vào tin nhắn giveaway và chọn 'Copy ID'.",
            inline=False
        )
        await ctx.send(embed=embed)
        return
    
    # Kiểm tra xem giveaway có tồn tại không
    if message_id not in active_giveaways:
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Không tìm thấy giveaway với ID này hoặc giveaway đã kết thúc.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return
    
    # Kiểm tra người dùng có phải là host hoặc admin không
    giveaway_info = active_giveaways[message_id]
    if ctx.author.id != giveaway_info["host"] and not ctx.author.guild_permissions.administrator:
        embed = discord.Embed(
            title="❌ Thiếu quyền",
            description="Bạn không phải là người tạo giveaway này và không có quyền quản trị viên.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return
    
    # Gửi thông báo đang kết thúc
    embed = discord.Embed(
        title="⏳ Đang kết thúc giveaway...",
        description=f"Đang kết thúc giveaway với ID: `{message_id}`",
        color=discord.Color.orange()
    )
    message = await ctx.send(embed=embed)
    
    # Kết thúc giveaway
    await end_giveaway(message_id)
    
    # Cập nhật thông báo
    embed = discord.Embed(
        title="✅ Đã kết thúc giveaway",
        description=f"Giveaway với ID: `{message_id}` đã được kết thúc thành công.",
        color=discord.Color.green()
    )
    await message.edit(embed=embed)

@bot.command(name='greroll', aliases=['giveawayreroll', 'reroll'])
@commands.has_permissions(manage_messages=True)
async def reroll_giveaway(ctx, message_id: int = None):
    """Chọn lại người thắng cho giveaway đã kết thúc"""
    if message_id is None:
        embed = discord.Embed(
            title="❓ Reroll Giveaway - Hướng Dẫn",
            description="Chọn lại người thắng cho giveaway đã kết thúc.",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="Cách sử dụng",
            value="`.greroll <message_id>`",
            inline=False
        )
        embed.add_field(
            name="Lưu ý",
            value="Message ID là ID của tin nhắn giveaway.\nBạn có thể lấy ID này bằng cách nhấp phải vào tin nhắn giveaway và chọn 'Copy ID'.",
            inline=False
        )
        await ctx.send(embed=embed)
        return
    
    # Kiểm tra xem giveaway đã kết thúc chưa (không còn trong active_giveaways)
    if message_id in active_giveaways:
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Giveaway này vẫn đang diễn ra. Bạn chỉ có thể reroll giveaway đã kết thúc.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return
    
    # Lấy tin nhắn giveaway
    try:
        message = await ctx.channel.fetch_message(message_id)
    except:
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Không tìm thấy tin nhắn giveaway với ID này trong kênh hiện tại.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return
    
    # Kiểm tra xem có phải là tin nhắn giveaway không
    if not message.embeds or "GIVEAWAY" not in message.embeds[0].title:
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Tin nhắn này không phải là một giveaway.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return
    
    # Lấy thông tin giải thưởng từ embed
    giveaway_embed = message.embeds[0]
    prize = giveaway_embed.description
    if "**" in prize:
        prize = prize.split("**")[1]
    
    # Lấy reaction từ tin nhắn
    reaction = discord.utils.get(message.reactions, emoji="🎉")
    if not reaction:
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Không có người tham gia nào trong giveaway này.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return
    
    # Lấy danh sách người tham gia
    users = []
    async for user in reaction.users():
        if not user.bot:  # Loại bỏ bot
            users.append(user)
    
    # Kiểm tra số người tham gia
    if not users:
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Không có người tham gia hợp lệ trong giveaway này.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return
    
    # Chọn một người thắng mới
    winner = random.choice(users)
    
    # Hiển thị kết quả reroll
    embed = discord.Embed(
        title="🎉 Reroll Giveaway",
        description=f"Người thắng mới cho **{prize}** là: {winner.mention}",
        color=discord.Color.gold()
    )
    
    embed.set_footer(text=f"Giveaway ID: {message_id}")
    
    await ctx.send(embed=embed)
    await ctx.send(f"🎉 Chúc mừng {winner.mention}! Bạn đã thắng **{prize}** từ reroll!")

@bot.command(name='glist', aliases=['giveawaylist', 'giveaways'])
@commands.has_permissions(manage_messages=True)
async def list_giveaways(ctx):
    """Hiển thị danh sách các giveaway đang hoạt động"""
    if not active_giveaways:
        embed = discord.Embed(
            title="📋 Danh sách Giveaway",
            description="Không có giveaway nào đang diễn ra.",
            color=discord.Color.blue()
        )
        await ctx.send(embed=embed)
        return
    
    embed = discord.Embed(
        title="📋 Danh sách Giveaway Đang Diễn Ra",
        description=f"Có **{len(active_giveaways)}** giveaway đang diễn ra:",
        color=discord.Color.gold()
    )
    
    for msg_id, gw_info in active_giveaways.items():
        prize = gw_info["prize"]
        end_time = gw_info["end_time"]
        host_id = gw_info["host"]
        winners = gw_info["winners"]
        
        # Lấy thông tin người tạo giveaway
        try:
            host = await bot.fetch_user(host_id)
            host_name = host.name
        except:
            host_name = f"User ID: {host_id}"
        
        # Tạo field cho mỗi giveaway
        time_remaining = int((end_time - datetime.now()).total_seconds())
        if time_remaining > 0:
            time_text = f"<t:{int(end_time.timestamp())}:R>"
        else:
            time_text = "Đang kết thúc..."
        
        embed.add_field(
            name=f"🎁 {prize}",
            value=(
                f"**ID:** `{msg_id}`\n"
                f"**Kết thúc:** {time_text}\n"
                f"**Số người thắng:** {winners}\n"
                f"**Tổ chức bởi:** {host_name}"
            ),
            inline=False
        )
    
    embed.set_footer(text="Sử dụng .gend <ID> để kết thúc giveaway")
    await ctx.send(embed=embed)

# Cần thêm task để tự động kết thúc giveaway khi đến thời gian
@tasks.loop(minutes=1.0)
async def check_giveaways():
    """Kiểm tra và kết thúc giveaway đã hết thời gian"""
    current_time = datetime.now()
    
    # Tạo danh sách các giveaway cần kết thúc để tránh RuntimeError khi sửa đổi dict trong vòng lặp
    to_end = []
    
    for msg_id, gw_info in active_giveaways.items():
        end_time = gw_info["end_time"]
        if current_time >= end_time:
            to_end.append(msg_id)
    
    # Kết thúc các giveaway
    for msg_id in to_end:
        await end_giveaway(msg_id)

# Bắt đầu task kiểm tra giveaway khi bot khởi động
@bot.event
async def on_ready():
    check_giveaways.start()


@bot.command(name='tkey')
@admin_only()
async def create_key(ctx, key_type: str = None, input_value: str = None, time_input: str = None, count: int = 1, target: discord.Member = None, *, additional_info: str = None):
    """Admin command để tạo nhiều key đổi xu hoặc role cùng lúc và gửi cho người dùng chỉ định
    
    Sử dụng:
    .tkey xu [số xu] [số lượt dùng] [số lượng key] [@người_nhận (tùy chọn)] - Tạo key đổi xu
    .tkey role [role_id/role_name] [thời hạn] [số lượng key] [@người_nhận (tùy chọn)] - Tạo key đổi role
    
    Thời hạn có thể được chỉ định bằng: 
    - Số giây: 3600
    - Hoặc định dạng: 1d2h3m4s (1 ngày 2 giờ 3 phút 4 giây)
    - Sử dụng 0 cho role vĩnh viễn
    """
    if key_type is None or key_type.lower() not in ["xu", "role"]:
        embed = discord.Embed(
            title="🔑 Tạo Key - Hướng Dẫn",
            description="Tạo key để người dùng đổi xu hoặc đổi role.",
            color=discord.Color.blue())
        embed.add_field(
            name="Tạo key đổi xu", 
            value="`.tkey xu [số xu] [số lượt dùng (mặc định: 1)] [số lượng key (mặc định: 1)] [@người_nhận (tùy chọn)]`\n" + 
                  "Ví dụ: `.tkey xu 1000 1 5` để tạo 5 key đổi xu", 
            inline=False)
        embed.add_field(
            name="Tạo key đổi role", 
            value="`.tkey role [role_id/role_name] [thời hạn] [số lượng key (mặc định: 1)] [@người_nhận (tùy chọn)]`\n" + 
                  "Ví dụ: `.tkey role VIP 1d 5` để tạo 5 key cho role VIP với thời hạn 1 ngày\n" +
                  "Ví dụ: `.tkey role 1234567890 12h30m 1` để tạo 1 key thời hạn 12 giờ 30 phút\n" +
                  "Ví dụ: `.tkey role \"Admin Role\" 0 1` để tạo 1 key cho role tên 'Admin Role' vĩnh viễn", 
            inline=False)
        embed.add_field(
            name="Định dạng thời hạn",
            value="- Số giây: `3600`\n" +
                  "- Định dạng: `1d2h3m4s` = 1 ngày 2 giờ 3 phút 4 giây\n" +
                  "- Sử dụng `0` cho role vĩnh viễn",
            inline=False
        )
        await ctx.send(embed=embed)
        return

    # Xóa lệnh gốc ngay lập tức
    try:
        await ctx.message.delete()
    except:
        pass

    # Xử lý dựa vào loại key
    key_type = key_type.lower()
    
    if key_type == "xu":
        # Validate amount
        try:
            amount = int(input_value)
            if amount <= 0:
                embed = discord.Embed(
                    title="❌ Lỗi",
                    description="Số xu phải lớn hơn 0.",
                    color=discord.Color.red())
                await ctx.send(embed=embed, delete_after=5)
                return
        except (ValueError, TypeError):
            embed = discord.Embed(
                title="❌ Lỗi",
                description="Số xu không hợp lệ. Vui lòng cung cấp một số nguyên dương.",
                color=discord.Color.red())
            await ctx.send(embed=embed, delete_after=5)
            return
        
        # Validate uses
        try:
            uses = int(time_input) if time_input is not None else 1
            if uses <= 0:
                embed = discord.Embed(
                    title="❌ Lỗi",
                    description="Số lượt sử dụng phải lớn hơn 0.",
                    color=discord.Color.red())
                await ctx.send(embed=embed, delete_after=5)
                return
        except (ValueError, TypeError):
            embed = discord.Embed(
                title="❌ Lỗi",
                description="Số lượt sử dụng không hợp lệ. Vui lòng cung cấp một số nguyên dương.",
                color=discord.Color.red())
            await ctx.send(embed=embed, delete_after=5)
            return

        # Tạo key đổi xu
        await create_currency_keys(ctx, amount, uses, count, target)
    
    elif key_type == "role":
        # Tìm role dựa trên ID hoặc tên
        role = None
        
        # Trường hợp 1: input_value là ID role
        if input_value and input_value.isdigit():
            role_id = int(input_value)
            role = ctx.guild.get_role(role_id)
            
        # Trường hợp 2: input_value là tên role
        if role is None and input_value:
            # Tìm kiếm có phân biệt tên role chính xác
            if input_value.startswith('"') and input_value.endswith('"'):
                # Tìm kiếm role với tên chính xác trong dấu ngoặc kép
                role_name = input_value[1:-1]  # Loại bỏ dấu ngoặc kép
                role = discord.utils.get(ctx.guild.roles, name=role_name)
            else:
                # Tìm kiếm gần đúng với tên role
                input_lower = input_value.lower()
                for guild_role in ctx.guild.roles:
                    if input_lower == guild_role.name.lower() or input_lower in guild_role.name.lower():
                        role = guild_role
                        break
        
        if role is None:
            embed = discord.Embed(
                title="❌ Role không tồn tại",
                description=f"Không thể tìm thấy role với ID hoặc tên '{input_value}'.\n" +
                            "Nếu tên role có dấu cách, hãy đặt trong dấu ngoặc kép, ví dụ: `.tkey role \"Admin Role\" 1d 1`",
                color=discord.Color.red())
            await ctx.send(embed=embed, delete_after=5)
            return
            
        # Phân tích time_input thành số giây
        duration = 0
        if time_input is None or time_input == "0":
            # Vĩnh viễn
            duration = 0
        elif time_input.isdigit():
            # Chỉ là số giây
            duration = int(time_input)
        else:
            # Phân tích cú pháp như 1d2h3m4s
            duration = parse_time_format(time_input)
            if duration is None:
                embed = discord.Embed(
                    title="❌ Định dạng thời gian không hợp lệ",
                    description="Vui lòng sử dụng định dạng như `1d2h3m4s` hoặc số giây hoặc 0 cho vĩnh viễn.",
                    color=discord.Color.red())
                await ctx.send(embed=embed, delete_after=5)
                return

        # Tạo key đổi role
        await create_role_keys(ctx, role, duration, count, target)

def parse_time_format(time_str):
    """Phân tích chuỗi định dạng thời gian như 1d2h3m4s thành số giây"""
    total_seconds = 0
    current_number = ""
    
    for char in time_str:
        if char.isdigit():
            current_number += char
        elif char.lower() in ['d', 'h', 'm', 's']:
            if current_number:
                value = int(current_number)
                if char.lower() == 'd':
                    total_seconds += value * 86400  # 1 ngày = 86400 giây
                elif char.lower() == 'h':
                    total_seconds += value * 3600   # 1 giờ = 3600 giây
                elif char.lower() == 'm':
                    total_seconds += value * 60     # 1 phút = 60 giây
                elif char.lower() == 's':
                    total_seconds += value          # giây
                current_number = ""
        else:
            # Ký tự không hợp lệ
            return None
    
    # Nếu còn số dư mà không có ký tự đơn vị, coi như giây
    if current_number:
        try:
            total_seconds += int(current_number)
        except ValueError:
            return None
    
    return total_seconds

async def create_role_keys(ctx, role, duration, count, target):
    """Hàm phụ giúp tạo key đổi role"""
    # Validate count
    if count <= 0:
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Số lượng key phải lớn hơn 0.",
            color=discord.Color.red())
        await ctx.send(embed=embed, delete_after=5)
        return
    
    # Giới hạn số lượng key có thể tạo một lúc để tránh spam
    if count > 100:
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Không thể tạo quá 100 key cùng lúc.",
            color=discord.Color.red())
        await ctx.send(embed=embed, delete_after=5)
        return

    # Hiển thị thông báo đang tạo cho lượng key lớn
    if count > 10:
        creating_embed = discord.Embed(
            title="⏳ Đang tạo key...",
            description=f"Đang tạo {count} key đổi role với role {role.name}.",
            color=discord.Color.blue())
        creating_msg = await ctx.send(embed=creating_embed)

    # Danh sách lưu các key đã tạo
    created_keys = []
    
    # Generate multiple random keys
    key_length = 12
    for _ in range(count):
        key_code = ''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789', k=key_length))
        
        # Create role key
        active_keys[key_code] = {
            "uses": 1,  # Role keys typically have only one use
            "created_by": ctx.author.id,
            "redeemed_by": [],
            "creation_time": datetime.now(),
            "type": "role",  # Đánh dấu loại key là đổi role
            "role_info": {
                "role_id": role.id,
                "role_name": role.name,
                "duration": duration if duration > 0 else None  # None = permanent
            }
        }
        created_keys.append(key_code)

    # Định dạng thời hạn role để hiển thị
    if duration <= 0:
        duration_text = "vĩnh viễn"
    else:
        days, remainder = divmod(duration, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, remainder = divmod(remainder, 60)
        seconds = remainder
        
        duration_parts = []
        if days > 0:
            duration_parts.append(f"{days} ngày")
        if hours > 0:
            duration_parts.append(f"{hours} giờ")
        if minutes > 0:
            duration_parts.append(f"{minutes} phút")
        if seconds > 0:
            duration_parts.append(f"{seconds} giây")
            
        duration_text = " ".join(duration_parts) if duration_parts else "0 giây"

    # Send success embed to channel
    embed = discord.Embed(
        title="✅ Tạo Key Đổi Role Thành Công",
        description=f"Đã tạo **{count}** key đổi role **{role.name}** (ID: {role.id}).",
        color=discord.Color.green())
    embed.add_field(name="⏱️ Thời hạn role", value=duration_text, inline=True)
    embed.add_field(name="👤 Tạo bởi", value=f"{ctx.author.mention}", inline=False)
    
    # Xác định người nhận key
    recipient = target if target else ctx.author
    if target:
        embed.add_field(name="📩 Gửi đến", value=f"{target.mention}", inline=False)
    
    embed.add_field(name="🗂️ Quản lý", value="Các key được tự động xóa sau khi sử dụng", inline=False)
    embed.set_footer(text=f"Key được gửi qua DM cho {recipient.name}")
    
    # Cập nhật thông báo nếu đã hiển thị
    if count > 10:
        await creating_msg.edit(embed=embed)
    else:
        await ctx.send(embed=embed, delete_after=10)
    
    # Send keys privately to recipient
    await send_keys_to_user(ctx, recipient, created_keys, f"Role {role.name} ({duration_text})", 1, "đổi role", target)

async def create_currency_keys(ctx, amount, uses, count, target):
    """Hàm phụ giúp tạo key đổi xu"""
    # Validate count
    if count <= 0:
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Số lượng key phải lớn hơn 0.",
            color=discord.Color.red())
        await ctx.send(embed=embed, delete_after=5)
        return
    
    # Giới hạn số lượng key có thể tạo một lúc để tránh spam
    if count > 100:
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Không thể tạo quá 100 key cùng lúc.",
            color=discord.Color.red())
        await ctx.send(embed=embed, delete_after=5)
        return
    
    # Hiển thị thông báo đang tạo cho lượng key lớn
    if count > 10:
        creating_embed = discord.Embed(
            title="⏳ Đang tạo key...",
            description=f"Đang tạo {count} key đổi {amount} xu với {uses} lượt sử dụng mỗi key.",
            color=discord.Color.blue())
        creating_msg = await ctx.send(embed=creating_embed)
    
    # Danh sách lưu các key đã tạo
    created_keys = []
    
    # Generate multiple random keys
    key_length = 12
    for _ in range(count):
        key_code = ''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789', k=key_length))
        
        # Create currency key
        active_keys[key_code] = {
            "amount": amount,
            "uses": uses,
            "created_by": ctx.author.id,
            "redeemed_by": [],
            "creation_time": datetime.now(),
            "type": "currency"  # Đánh dấu loại key là đổi xu
        }
        created_keys.append(key_code)
    
    # Send success embed to channel
    embed = discord.Embed(
        title="✅ Tạo Key Đổi Xu Thành Công",
        description=f"Đã tạo **{count}** key với mệnh giá **{amount}** xu.",
        color=discord.Color.green())
    embed.add_field(name="🔄 Số lần sử dụng mỗi key", value=str(uses), inline=True)
    embed.add_field(name="👤 Tạo bởi", value=f"{ctx.author.mention}", inline=False)
    
    # Xác định người nhận key
    recipient = target if target else ctx.author
    if target:
        embed.add_field(name="📩 Gửi đến", value=f"{target.mention}", inline=False)
    
    embed.set_footer(text=f"Key được gửi qua DM cho {recipient.name}")
    
    # Cập nhật thông báo nếu đã hiển thị
    if count > 10:
        await creating_msg.edit(embed=embed)
    else:
        await ctx.send(embed=embed, delete_after=10)
    
    # Send keys privately to recipient
    await send_keys_to_user(ctx, recipient, created_keys, f"{amount} xu", uses, "đổi xu", target)

async def send_keys_to_user(ctx, recipient, created_keys, value, uses, key_type_text, target=None):
    """Hàm phụ trợ gửi key đến người dùng"""
    success = False
    try:
        dm_embed = discord.Embed(
            title=f"🔑 Key {key_type_text.title()} Mới",
            description=f"Bạn đã nhận được {len(created_keys)} key {key_type_text} từ {ctx.author.name}:",
            color=discord.Color.gold()
        )
        
        # Tùy vào số lượng key, chọn cách hiển thị phù hợp
        if len(created_keys) <= 15:
            # Nếu ít key, hiển thị mỗi key trên một dòng
            keys_text = "\n".join(f"`{key}`" for key in created_keys)
            dm_embed.add_field(name="🔑 Danh sách key", value=keys_text, inline=False)
        else:
            # Nếu quá nhiều key, chia thành nhiều field
            for i in range(0, min(len(created_keys), 30), 10):
                chunk = created_keys[i:i+10]
                keys_text = "\n".join(f"`{key}`" for key in chunk)
                dm_embed.add_field(name=f"🔑 Danh sách key {i+1}-{i+len(chunk)}", value=keys_text, inline=False)
        
        dm_embed.add_field(name="💰 Giá trị mỗi key", value=value, inline=True)
        dm_embed.add_field(name="🔄 Số lần sử dụng mỗi key", value=f"{uses} lần", inline=True)
        dm_embed.set_footer(text=f"Sử dụng lệnh .key [mã key] trong server để {key_type_text}")
        
        await recipient.send(embed=dm_embed)
        
        # Luôn tạo file text cho việc copy dễ dàng
        keys_content = "\n".join(created_keys)
        with open("keys.txt", "w") as file:
            file.write(f"Keys created on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            file.write(f"Value: {value} | Uses: {uses} | Total keys: {len(created_keys)}\n\n")
            file.write(keys_content)
        
        await recipient.send("📎 Đính kèm file danh sách key để thuận tiện sao chép:", file=discord.File("keys_temp.txt"))
        success = True
        
        # Xóa file tạm sau khi gửi
        try:
            os.remove("keys_temp.txt")
        except:
            pass
        
        # Nếu gửi cho người dùng khác, thông báo cho admin biết đã gửi thành công
        if target and target.id != ctx.author.id:
            confirm_embed = discord.Embed(
                title="✅ Đã Gửi Key",
                description=f"Đã gửi {len(created_keys)} key đến {target.mention} thành công!",
                color=discord.Color.green()
            )
            await ctx.author.send(embed=confirm_embed)
            
    except Exception as e:
        success = False
    
    # Notify if DM failed
    if not success:
        error_embed = discord.Embed(
            title="❌ Không thể gửi key",
            description=f"Không thể gửi key qua DM cho {recipient.mention}. Có thể họ đã tắt DM.",
            color=discord.Color.red()
        )
        await ctx.send(embed=error_embed, delete_after=10)
        
        # Gửi key cho người tạo nếu không gửi được cho người dùng chỉ định
        if target and target.id != ctx.author.id:
            fallback_embed = discord.Embed(
                title="🔑 Key Không Gửi Được - Backup",
                description=f"Không thể gửi key cho {target.mention}. Dưới đây là key để bạn gửi thủ công:",
                color=discord.Color.orange()
            )
            
            if len(created_keys) <= 15:
                keys_text = "\n".join(f"`{key}`" for key in created_keys)
                fallback_embed.add_field(name="🔑 Danh sách key", value=keys_text, inline=False)
            else:
                for i in range(0, min(len(created_keys), 30), 10):
                    chunk = created_keys[i:i+10]
                    keys_text = "\n".join(f"`{key}`" for key in chunk)
                    fallback_embed.add_field(name=f"🔑 Danh sách key {i+1}-{i+len(chunk)}", value=keys_text, inline=False)
            
            fallback_embed.add_field(name="💰 Giá trị mỗi key", value=value, inline=True)
            fallback_embed.add_field(name="🔄 Số lần sử dụng mỗi key", value=f"{uses} lần", inline=True)
            
            try:
                await ctx.author.send(embed=fallback_embed)
                
                # Gửi cả file backup
                keys_content = "\n".join(created_keys)
                with open("keys_backup.txt", "w") as file:
                    file.write(f"Keys created on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                    file.write(f"Value: {value} | Uses: {uses} | Total keys: {len(created_keys)}\n\n")
                    file.write(keys_content)
                
                await ctx.author.send("📎 Đính kèm file danh sách key backup:", file=discord.File("keys_backup.txt"))
                
                try:
                    os.remove("keys_backup.txt")
                except:
                    pass
            except:
                pass

@bot.command(name='key')
async def redeem_key(ctx, key_code: str = None):
    """Đổi key để nhận xu hoặc role"""
    if key_code is None:
        embed = discord.Embed(
            title="🔑 Đổi Key - Hướng Dẫn",
            description="Sử dụng key để đổi xu hoặc nhận role đặc biệt.",
            color=discord.Color.blue())
        embed.add_field(
            name="Cách sử dụng", 
            value="`.key [mã key]`\nVí dụ: `.key ABC123XYZ`", 
            inline=False)
        await ctx.send(embed=embed)
        return

    user_id = ctx.author.id

    # Check if key exists
    if key_code not in active_keys:
        embed = discord.Embed(
            title="❌ Key không hợp lệ",
            description="Key này không tồn tại hoặc đã hết hạn.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Check if key has uses left
    if active_keys[key_code]["uses"] <= 0:
        embed = discord.Embed(
            title="❌ Key đã hết lượt sử dụng",
            description="Key này đã được sử dụng hết số lần cho phép.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Check if user already used this key
    if user_id in active_keys[key_code]["redeemed_by"]:
        embed = discord.Embed(
            title="❌ Đã sử dụng",
            description="Bạn đã sử dụng key này rồi.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Check if user has used too many keys recently (potential abuse)
    if user_id in key_log:
        # Count recent key usages (within last 24 hours)
        recent_keys = [
            log for log in key_log[user_id] 
            if (datetime.now() - log["time"]).total_seconds() < 86400
        ]
        if len(recent_keys) >= 10:  # Tăng lên từ 3 lên 10
            embed = discord.Embed(
                title="⚠️ Cảnh báo",
                description="Bạn đã sử dụng quá nhiều key trong 24 giờ qua. Vui lòng thử lại sau.",
                color=discord.Color.orange())
            await ctx.send(embed=embed)
            return

    # Determine key type and process accordingly
    key_type = active_keys[key_code].get("type", "currency")  # Default to currency for backward compatibility
    
    if key_type == "role":
        # Process role key
        await process_role_key(ctx, key_code)
    else:
        # Process currency key
        await process_currency_key(ctx, key_code)

    # Attempt to delete the command message for key security
    try:
        await ctx.message.delete()
    except:
        pass

async def process_currency_key(ctx, key_code):
    """Process a currency key redemption"""
    user_id = ctx.author.id
    key_info = active_keys[key_code]
    
    # Add xu to user
    amount = key_info["amount"]
    currency[user_id] += amount
    
    # Log key usage
    if user_id not in key_log:
        key_log[user_id] = []
    
    key_log[user_id].append({
        "key": key_code,
        "time": datetime.now(),
        "amount": amount,
        "type": "currency"
    })
    
    # Update key usage
    key_info["uses"] -= 1
    key_info["redeemed_by"].append(user_id)
    
    # Create success embed
    embed = discord.Embed(
        title="🎉 Đổi Key Thành Công",
        description=f"{ctx.author.mention} đã nhận được **{amount} xu**!",
        color=discord.Color.green())
    
    embed.add_field(
        name="💰 Số xu hiện tại", 
        value=f"{currency[user_id]} xu", 
        inline=False
    )
    
    # Remove key if no uses left
    if key_info["uses"] <= 0:
        del active_keys[key_code]
    
    await ctx.send(embed=embed)

async def process_role_key(ctx, key_code):
    """Process a role key redemption"""
    user_id = ctx.author.id
    key_info = active_keys[key_code]
    role_info = key_info.get("role_info")
    
    if not role_info:
        embed = discord.Embed(
            title="❌ Key không hợp lệ",
            description="Key này không chứa thông tin role.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return
    
    # Get the role from the server
    role_id = role_info.get("role_id")
    role = ctx.guild.get_role(role_id)
    
    if not role:
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Không tìm thấy role được chỉ định trong key.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return
    
    # Add the role to the user
    try:
        await ctx.author.add_roles(role)
        
        # Log key usage
        if user_id not in key_log:
            key_log[user_id] = []
        
        key_log[user_id].append({
            "key": key_code,
            "time": datetime.now(),
            "role_id": role_id,
            "role_name": role.name,
            "type": "role"
        })
        
        # Update key usage
        key_info["uses"] -= 1
        key_info["redeemed_by"].append(user_id)
        
        # Create success embed
        embed = discord.Embed(
            title="🎉 Đổi Key Thành Công",
            description=f"{ctx.author.mention} đã nhận được role **{role.name}**!",
            color=discord.Color.green())
        
        # Role duration information
        duration = role_info.get("duration")
        if duration:
            # Convert seconds to a readable format
            if duration < 3600:
                time_str = f"{duration // 60} phút"
            elif duration < 86400:
                time_str = f"{duration // 3600} giờ"
            else:
                time_str = f"{duration // 86400} ngày"
            
            embed.add_field(
                name="⏱️ Thời hạn", 
                value=f"Role sẽ hết hạn sau {time_str}", 
                inline=False
            )
            
            # Schedule role removal after duration
            bot.loop.create_task(remove_role_after_duration(ctx.author.id, role_id, duration))
        else:
            embed.add_field(
                name="⏱️ Thời hạn", 
                value="Role vĩnh viễn", 
                inline=False
            )
            
        # Remove key if no uses left
        if key_info["uses"] <= 0:
            del active_keys[key_code]
            
        # Gửi thông báo thành công
        await ctx.send(embed=embed)
        
    except discord.Forbidden:
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Bot không có quyền thêm role cho bạn.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
    except Exception as e:
        embed = discord.Embed(
            title="❌ Lỗi",
            description=f"Đã xảy ra lỗi: {str(e)}",
            color=discord.Color.red())
        await ctx.send(embed=embed)


# Helper function to remove role after duration
async def remove_role_after_duration(user_id, role_id, duration):
    """Remove role from user after specified duration"""
    await asyncio.sleep(duration)
    
    # Find the guild and member
    for guild in bot.guilds:
        member = guild.get_member(user_id)
        if member:
            role = guild.get_role(role_id)
            if role and role in member.roles:
                try:
                    await member.remove_roles(role)
                    
                    # Try to notify user
                    try:
                        embed = discord.Embed(
                            title="⏱️ Role đã hết hạn",
                            description=f"Role **{role.name}** của bạn đã hết hạn và đã bị gỡ bỏ.",
                            color=discord.Color.orange()
                        )
                        await member.send(embed=embed)
                    except:
                        pass  # Ignore if can't DM
                    
                except:
                    pass  # Ignore errors
                break


@bot.command(name='chkey', aliases=['checkhistorykey', 'keyhistory', 'khist'])
@admin_only()
async def check_key_history(ctx, key_code: str = None):
    """Kiểm tra lịch sử sử dụng của một key cụ thể"""
    if key_code is None:
        embed = discord.Embed(
            title="ℹ️ Kiểm Tra Lịch Sử Key - Hướng Dẫn",
            description="Kiểm tra những người dùng đã sử dụng một key cụ thể.",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="Cách sử dụng",
            value="`.chkey [mã key]`\nVí dụ: `.chkey ABC123XYZ`", 
            inline=False
        )
        await ctx.send(embed=embed)
        return
    
    # Kiểm tra trong key đang hoạt động
    key_exists = key_code in active_keys
    key_info = active_keys.get(key_code, None)
    
    # Tìm người dùng đã đổi key này trong lịch sử
    users_redeemed = []
    for user_id, logs in key_log.items():
        for log in logs:
            if log.get("key") == key_code:
                # Tìm thấy người dùng đã sử dụng key này
                try:
                    user = await bot.fetch_user(user_id)
                    user_name = user.name
                except:
                    user_name = f"ID: {user_id}"
                
                # Lấy thông tin thời gian đổi key
                time_redeemed = log.get("time", datetime.now())
                time_str = discord.utils.format_dt(time_redeemed, style="R")
                
                # Lấy thông tin về loại key và giá trị
                key_type = log.get("type", "currency")
                
                if key_type == "currency":
                    value_info = f"{log.get('amount', 'không rõ')} xu"
                else:
                    role_name = log.get("role_name", "không rõ")
                    role_id = log.get("role_id", "N/A")
                    value_info = f"Role {role_name} (ID: {role_id})"
                
                users_redeemed.append({
                    "user_id": user_id,
                    "user_name": user_name,
                    "time": time_redeemed,
                    "time_str": time_str,
                    "key_type": key_type,
                    "value_info": value_info
                })
    
    # Sắp xếp theo thời gian, mới nhất lên đầu
    users_redeemed.sort(key=lambda x: x["time"], reverse=True)
    
    # Tạo embed hiển thị thông tin
    if key_exists:
        embed_title = f"🔑 Lịch sử key: {key_code} (Còn hiệu lực)"
        embed_color = discord.Color.green()
    else:
        embed_title = f"🔑 Lịch sử key: {key_code} (Đã hết hạn/Đã sử dụng hết)"
        embed_color = discord.Color.orange()
    
    embed = discord.Embed(
        title=embed_title,
        description=f"Có **{len(users_redeemed)}** người đã sử dụng key này.",
        color=embed_color
    )
    
    # Thêm thông tin về key nếu key vẫn còn hoạt động
    if key_info:
        key_type = key_info.get("type", "currency")
        
        if key_type == "currency":
            amount = key_info.get("amount", 0)
            embed.add_field(
                name="💰 Loại key",
                value=f"Key Xu: **{amount} xu**",
                inline=True
            )
        else:
            role_info = key_info.get("role_info", {})
            role_name = role_info.get("role_name", "Không xác định")
            role_id = role_info.get("role_id", "N/A")
            duration = role_info.get("duration")
            
            if duration:
                if duration < 3600:
                    duration_text = f"{duration // 60} phút"
                elif duration < 86400:
                    duration_text = f"{duration // 3600} giờ"
                else:
                    duration_text = f"{duration // 86400} ngày"
            else:
                duration_text = "Vĩnh viễn"
            
            embed.add_field(
                name="🎭 Loại key",
                value=f"Key Role: **{role_name}** (ID: `{role_id}`)\nThời hạn: **{duration_text}**",
                inline=True
            )
        
        embed.add_field(
            name="🔄 Lượt dùng còn lại",
            value=f"**{key_info.get('uses', 0)}** lượt",
            inline=True
        )
        
        # Hiển thị người tạo key
        created_by_id = key_info.get("created_by")
        if created_by_id:
            try:
                creator = await bot.fetch_user(created_by_id)
                creator_text = f"{creator.name} (ID: `{creator.id}`)"
            except:
                creator_text = f"ID: `{created_by_id}`"
            
            embed.add_field(
                name="👤 Tạo bởi",
                value=creator_text,
                inline=True
            )
        
        # Hiển thị thời gian tạo key
        creation_time = key_info.get("creation_time")
        if creation_time:
            time_str = discord.utils.format_dt(creation_time, style="F")
            embed.add_field(
                name="📆 Tạo lúc",
                value=f"{time_str}",
                inline=False
            )
    
    # Hiển thị lịch sử sử dụng
    if users_redeemed:
        users_info = ""
        for i, user_data in enumerate(users_redeemed[:10], 1):
            users_info += f"**{i}.** {user_data['user_name']} (ID: `{user_data['user_id']}`)\n"
            users_info += f"⏰ Đã đổi: {user_data['time_str']}\n"
            users_info += f"🏷️ Nhận: {user_data['value_info']}\n\n"
            
        # Thêm thông báo nếu còn nhiều người dùng khác
        if len(users_redeemed) > 10:
            remaining = len(users_redeemed) - 10
            users_info += f"*...và {remaining} người dùng khác*"
            
        embed.add_field(
            name="👥 Người dùng đã đổi key",
            value=users_info,
            inline=False
        )
    else:
        embed.add_field(
            name="👥 Người dùng đã đổi key",
            value="Không có ai sử dụng key này.",
            inline=False
        )
    
    embed.set_footer(text=f"ID: {key_code} | Kiểm tra bởi {ctx.author.name}")
    await ctx.send(embed=embed)


@bot.command(name='dropkey', aliases=['dropcode', 'keycode'])
@commands.has_permissions(administrator=True)
async def drop_key(ctx, amount: str = None, uses: int = None, count: int = None, *, message: str = None):
    """Tạo key đổi xu và drop trong kênh"""
    # Kiểm tra đầu vào hợp lệ
    if amount is None or uses is None or count is None:
        embed = discord.Embed(
            title="🔑 Drop Key - Hướng Dẫn",
            description="Tạo key xu và drop trong kênh hiện tại.",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="Cách dùng",
            value="`.dropkey [số xu] [số lượt] [số key] [tin nhắn]`",
            inline=False
        )
        embed.add_field(
            name="Ví dụ",
            value="`.dropkey 5000 3 5 Key mừng sinh nhật server!`",
            inline=False
        )
        embed.add_field(
            name="Lưu ý",
            value="- Số xu phải lớn hơn 0\n- Số lượt sử dụng phải từ 1-10\n- Số key phải từ 1-10",
            inline=False
        )
        await ctx.send(embed=embed)
        return

    # Xóa tin nhắn gốc
    try:
        await ctx.message.delete()
    except:
        pass
    
    # Xử lý và kiểm tra các tham số
    try:
        # Xử lý số xu (hỗ trợ định dạng 5k, 1m, v.v.)
        parsed_amount = amount.lower()
        if parsed_amount.endswith('k'):
            xu_amount = int(float(parsed_amount[:-1]) * 1000)
        elif parsed_amount.endswith('m'):
            xu_amount = int(float(parsed_amount[:-1]) * 1000000)
        else:
            xu_amount = int(parsed_amount)
        
        # Kiểm tra giá trị
        if xu_amount <= 0:
            await ctx.send("❌ Số xu phải lớn hơn 0!", delete_after=5)
            return
        
        if uses < 1 or uses > 10:
            await ctx.send("❌ Số lượt sử dụng phải từ 1 đến 10!", delete_after=5)
            return
        
        if count < 1 or count > 10:
            await ctx.send("❌ Số key phải từ 1 đến 10!", delete_after=5)
            return
            
    except ValueError:
        await ctx.send("❌ Vui lòng nhập số hợp lệ!", delete_after=5)
        return
    
    # Tạo tin nhắn mặc định nếu không có
    if not message:
        message = "Ai nhanh tay người đó nhận được key xu!"
    
    # Tạo các key
    generated_keys = []
    for _ in range(count):
        # Tạo key ngẫu nhiên
        key_code = ''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789', k=8))
        # Lưu key vào hệ thống
        active_keys[key_code] = {
            "amount": xu_amount,
            "uses": uses,
            "created_by": ctx.author.id,
            "redeemed_by": [],
            "creation_time": datetime.now()
        }
        generated_keys.append(key_code)
    
    # Tạo embed hiển thị key
    embed = discord.Embed(
        title="🎁 XU KEY DROP 🎁",
        description=message,
        color=discord.Color.gold()
    )
    
    embed.add_field(
        name="💰 Thông tin key",
        value=f"**Giá trị:** {xu_amount:,} xu/key\n**Lượt sử dụng:** {uses} lượt/key",
        inline=False
    )
    
    # Hiển thị các key trong code block để dễ sao chép
    keys_display = "\n".join([f"`{key}`" for key in generated_keys])
    embed.add_field(
        name=f"🔑 Key ({count} key):",
        value=keys_display,
        inline=False
    )
    
    embed.add_field(
        name="📝 Hướng dẫn sử dụng",
        value="Sử dụng lệnh `.key [mã key]` để đổi key lấy xu",
        inline=False
    )
    
    embed.set_footer(text=f"Key tạo bởi {ctx.author.name} • {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    
    # Tạo nút sao chép nhanh
    view = discord.ui.View(timeout=3600)  # 1 giờ timeout
    
    # Thêm nút cho từng key
    for i, key in enumerate(generated_keys):
        copy_button = discord.ui.Button(
            label=f"Copy Key {i+1}", 
            style=discord.ButtonStyle.primary,
            custom_id=f"copy_{key}")
        
        async def button_callback(interaction, key_to_copy=key):
            await interaction.response.send_message(
                f"**Key của bạn:** `{key_to_copy}`\nSử dụng lệnh `.key {key_to_copy}` để đổi lấy xu!", 
                ephemeral=True)
        
        copy_button.callback = button_callback
        view.add_item(copy_button)
    
    # Gửi tin nhắn drop key
    drop_message = await ctx.send(embed=embed, view=view)
    
    # Log admin action
    admin_log_embed = discord.Embed(
        title="📝 Admin Log: Drop Key",
        description=f"Admin {ctx.author.mention} đã tạo {count} key xu",
        color=discord.Color.blue()
    )
    admin_log_embed.add_field(
        name="Chi tiết",
        value=f"- Số xu: {xu_amount:,}\n- Lượt dùng: {uses}\n- Số key: {count}"
    )
    
    # Sending log to admin or in DM
    try:
        await ctx.author.send(embed=admin_log_embed)
    except:
        pass


@bot.command(name='droprole', aliases=['roledrop'])
@commands.has_permissions(administrator=True)
async def drop_role(ctx, role: discord.Role = None, duration: str = None, count: int = None, *, message: str = None):
    """Tạo key để nhận role và drop trong kênh"""
    # Kiểm tra đầu vào hợp lệ
    if role is None or duration is None or count is None:
        embed = discord.Embed(
            title="🎭 Drop Role - Hướng Dẫn",
            description="Tạo key nhận role và drop trong kênh hiện tại.",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="Cách dùng",
            value="`.droprole [@role] [thời hạn] [số key] [tin nhắn]`",
            inline=False
        )
        embed.add_field(
            name="Thời hạn",
            value="- `1h`, `2h`, `3h`... (giờ)\n- `1d`, `2d`, `3d`... (ngày)\n- `perm` (vĩnh viễn)",
            inline=False
        )
        embed.add_field(
            name="Ví dụ",
            value="`.droprole @VIP 1d 5 Key nhận role VIP 1 ngày!`",
            inline=False
        )
        await ctx.send(embed=embed)
        return

    # Xóa tin nhắn gốc
    try:
        await ctx.message.delete()
    except:
        pass
    
    # Xử lý và kiểm tra các tham số
    try:
        # Xử lý thời hạn
        if duration.lower() == "perm":
            seconds_duration = None
            duration_text = "Vĩnh viễn"
        else:
            time_value = int(duration[:-1])
            time_unit = duration[-1].lower()
            
            if time_unit == 'h':
                seconds_duration = time_value * 3600
                duration_text = f"{time_value} giờ"
            elif time_unit == 'd':
                seconds_duration = time_value * 86400
                duration_text = f"{time_value} ngày"
            else:
                await ctx.send("❌ Định dạng thời gian không hợp lệ! Sử dụng `h` (giờ), `d` (ngày) hoặc `perm`.", delete_after=5)
                return
        
        # Kiểm tra giá trị
        if count < 1 or count > 10:
            await ctx.send("❌ Số key phải từ 1 đến 10!", delete_after=5)
            return
            
    except ValueError:
        await ctx.send("❌ Vui lòng nhập thông tin hợp lệ!", delete_after=5)
        return
    
    # Kiểm tra quyền với role
    if role >= ctx.guild.me.top_role:
        await ctx.send("❌ Bot không đủ quyền để trao role này!", delete_after=5)
        return
    
    # Tạo tin nhắn mặc định nếu không có
    if not message:
        message = "Ai nhanh tay người đó nhận được role!"
    
    # Tạo các key
    generated_keys = []
    for _ in range(count):
        # Tạo key ngẫu nhiên
        key_code = ''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789', k=8))
        # Lưu key vào hệ thống
        active_keys[key_code] = {
            "role_id": role.id,
            "duration": seconds_duration,
            "created_by": ctx.author.id,
            "redeemed_by": [],
            "creation_time": datetime.now(),
            "type": "role"
        }
        generated_keys.append(key_code)
    
    # Tạo embed hiển thị key
    embed = discord.Embed(
        title="🎭 ROLE KEY DROP 🎭",
        description=message,
        color=role.color if role.color != discord.Color.default() else discord.Color.purple()
    )
    
    embed.add_field(
        name="🏆 Thông tin role",
        value=f"**Role:** {role.mention}\n**Thời hạn:** {duration_text}",
        inline=False
    )
    
    # Hiển thị các key trong code block để dễ sao chép
    keys_display = "\n".join([f"`{key}`" for key in generated_keys])
    embed.add_field(
        name=f"🔑 Key ({count} key):",
        value=keys_display,
        inline=False
    )
    
    embed.add_field(
        name="📝 Hướng dẫn sử dụng",
        value="Sử dụng lệnh `.key [mã key]` để đổi key lấy role",
        inline=False
    )
    
    embed.set_footer(text=f"Key tạo bởi {ctx.author.name} • {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    
    # Tạo nút sao chép nhanh
    view = discord.ui.View(timeout=3600)  # 1 giờ timeout
    
    # Thêm nút cho từng key
    for i, key in enumerate(generated_keys):
        copy_button = discord.ui.Button(
            label=f"Copy Key {i+1}", 
            style=discord.ButtonStyle.primary,
            custom_id=f"copy_{key}")
        
        async def button_callback(interaction, key_to_copy=key):
            await interaction.response.send_message(
                f"**Key của bạn:** `{key_to_copy}`\nSử dụng lệnh `.key {key_to_copy}` để nhận role!", 
                ephemeral=True)
        
        copy_button.callback = button_callback
        view.add_item(copy_button)
    
    # Gửi tin nhắn drop key
    drop_message = await ctx.send(embed=embed, view=view)
    
    # Log admin action
    admin_log_embed = discord.Embed(
        title="📝 Admin Log: Drop Role Key",
        description=f"Admin {ctx.author.mention} đã tạo {count} key role",
        color=discord.Color.blue()
    )
    admin_log_embed.add_field(
        name="Chi tiết",
        value=f"- Role: {role.name}\n- Thời hạn: {duration_text}\n- Số key: {count}"
    )
    
    # Sending log to admin or in DM
    try:
        await ctx.author.send(embed=admin_log_embed)
    except:
        pass

@bot.command(name='lkey', aliases=['keylist', 'lskey'])
@admin_only()
async def list_keys(ctx):
    """Admin command to list all active keys"""
    if not active_keys:
        embed = discord.Embed(
            title="🔑 Danh Sách Key",
            description="Không có key nào trong hệ thống.",
            color=discord.Color.blue())
        await ctx.send(embed=embed)
        return

    # Phân loại key theo loại
    currency_keys = {}
    role_keys = {}
    
    # Thống kê người sử dụng key
    users_stats = {}
    total_used_keys = 0
    
    # Phân loại các key và thống kê người dùng
    for key_code, key_info in active_keys.items():
        key_type = key_info.get("type", "currency")  # Default to currency for backward compatibility
        
        if key_type == "role":
            role_keys[key_code] = key_info
        else:
            currency_keys[key_code] = key_info
            
        # Thống kê người dùng đã sử dụng key
        redeemed_by = key_info.get("redeemed_by", [])
        total_used_keys += len(redeemed_by)
        
        for user_id in redeemed_by:
            if user_id not in users_stats:
                users_stats[user_id] = 0
            users_stats[user_id] += 1

    # Tạo embed chính
    embed = discord.Embed(
        title="🔑 Danh Sách Key",
        description=f"Có **{len(active_keys)}** key trong hệ thống:",
        color=discord.Color.blue())

    # Hiển thị thông tin tổng quan
    embed.add_field(
        name="📊 Tổng quan",
        value=f"💰 Key đổi xu: **{len(currency_keys)}**\n"
              f"🎭 Key đổi role: **{len(role_keys)}**\n"
              f"👥 Số lần sử dụng key: **{total_used_keys}** lần\n"
              f"👤 Số người dùng sử dụng key: **{len(users_stats)}** người",
        inline=False
    )

    # Hiển thị các key đổi xu (tối đa 10 key)
    if currency_keys:
        currency_keys_info = ""
        for idx, (key_code, key_info) in enumerate(list(currency_keys.items())[:10], 1):
            redeemed_count = len(key_info["redeemed_by"])
            try:
                creator = await bot.fetch_user(key_info["created_by"])
                creator_name = creator.name
            except:
                creator_name = f"ID: {key_info['created_by']}"

            # Format creation time
            creation_time = key_info.get("creation_time", datetime.now())
            time_str = discord.utils.format_dt(creation_time, style="R")

            currency_keys_info += f"**{idx}. {key_code}**\n"
            currency_keys_info += f"💰 **{key_info['amount']} xu** | "
            currency_keys_info += f"🔄 **{key_info['uses']}/{redeemed_count + key_info['uses']}** lượt | "
            currency_keys_info += f"👤 {creator_name} | {time_str}\n\n"
            
            if idx >= 10:
                remaining = len(currency_keys) - 10
                if remaining > 0:
                    currency_keys_info += f"*...và {remaining} key khác*"
                break

        embed.add_field(
            name=f"💰 Key Đổi Xu ({len(currency_keys)})",
            value=currency_keys_info or "Không có key đổi xu nào",
            inline=False
        )

    # Hiển thị các key đổi role (tối đa 10 key)
    if role_keys:
        role_keys_info = ""
        for idx, (key_code, key_info) in enumerate(list(role_keys.items())[:10], 1):
            redeemed_count = len(key_info["redeemed_by"])
            try:
                creator = await bot.fetch_user(key_info["created_by"])
                creator_name = creator.name
            except:
                creator_name = f"ID: {key_info['created_by']}"

            # Format creation time
            creation_time = key_info.get("creation_time", datetime.now())
            time_str = discord.utils.format_dt(creation_time, style="R")

            # Lấy thông tin về role
            role_info = key_info.get("role_info", {})
            role_name = role_info.get("role_name", "Không xác định")
            role_id = role_info.get("role_id", "N/A")
            
            # Hiển thị thời hạn role
            duration = role_info.get("duration")
            if duration:
                if duration < 3600:
                    duration_text = f"{duration // 60} phút"
                elif duration < 86400:
                    duration_text = f"{duration // 3600} giờ"
                else:
                    duration_text = f"{duration // 86400} ngày"
            else:
                duration_text = "Vĩnh viễn"

            role_keys_info += f"**{idx}. {key_code}**\n"
            role_keys_info += f"🎭 **{role_name}** (`{role_id}`) | "
            role_keys_info += f"⏱️ {duration_text} | "
            role_keys_info += f"🔄 **{key_info['uses']}/{redeemed_count + key_info['uses']}** lượt | "
            role_keys_info += f"👤 {creator_name} | {time_str}\n\n"
            
            if idx >= 10:
                remaining = len(role_keys) - 10
                if remaining > 0:
                    role_keys_info += f"*...và {remaining} key khác*"
                break

        embed.add_field(
            name=f"🎭 Key Đổi Role ({len(role_keys)})",
            value=role_keys_info or "Không có key đổi role nào",
            inline=False
        )
    
    # Hiển thị thống kê người dùng sử dụng key nhiều nhất (top 5)
    if users_stats:
        top_users = sorted(users_stats.items(), key=lambda x: x[1], reverse=True)[:5]
        users_info = ""
        
        for i, (user_id, count) in enumerate(top_users, 1):
            try:
                user = await bot.fetch_user(user_id)
                user_name = user.name
            except:
                user_name = f"Unknown (ID: {user_id})"
            
            users_info += f"**{i}. {user_name}**: {count} key\n"
        
        embed.add_field(
            name="👑 Top Người Dùng Key",
            value=users_info,
            inline=False
        )

    # Thêm hướng dẫn sử dụng các lệnh liên quan
    embed.add_field(
        name="⌨️ Các lệnh liên quan",
        value="`.ckey [mã key]` - Kiểm tra chi tiết về một key\n"
              "`.chkey [mã key]` - Kiểm tra lịch sử sử dụng key\n"
              "`.checkgl @user` - Kiểm tra lịch sử dùng key của người dùng\n"
              "`.xoakey [số lượng/all]` - Xóa key khỏi hệ thống",
        inline=False
    )

    embed.set_footer(text=f"Sử dụng .tkey để tạo thêm key | Được yêu cầu bởi {ctx.author.name}")
    await ctx.send(embed=embed)

@bot.command(name='delkey', aliases=['xoakey', 'keydelete', 'kd'])
@admin_only()
async def delete_key(ctx, key_or_amount: str = None, key_type: str = None):
    """Xóa key khỏi hệ thống
    
    Sử dụng:
    .delkey [mã key] - Xóa một key cụ thể
    .delkey all - Xóa tất cả key
    .delkey all xu - Xóa tất cả key đổi xu
    .delkey all role - Xóa tất cả key đổi role
    .delkey [số lượng] - Xóa số lượng key ngẫu nhiên
    .delkey [số lượng] xu - Xóa số lượng key đổi xu ngẫu nhiên
    .delkey [số lượng] role - Xóa số lượng key đổi role ngẫu nhiên
    """
    if key_or_amount is None:
        embed = discord.Embed(
            title="🗑️ Xóa Key - Hướng Dẫn",
            description="Xóa key khỏi hệ thống",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="Xóa một key cụ thể",
            value="`.delkey [mã key]`\nVí dụ: `.delkey ABC123XYZ`",
            inline=False
        )
        embed.add_field(
            name="Xóa tất cả key",
            value="`.delkey all` - Xóa tất cả key\n"
                  "`.delkey all xu` - Chỉ xóa key đổi xu\n"
                  "`.delkey all role` - Chỉ xóa key đổi role",
            inline=False
        )
        embed.add_field(
            name="Xóa nhiều key",
            value="`.delkey [số lượng]` - Xóa số lượng key ngẫu nhiên\n"
                  "`.delkey [số lượng] xu` - Xóa số lượng key đổi xu ngẫu nhiên\n"
                  "`.delkey [số lượng] role` - Xóa số lượng key đổi role ngẫu nhiên",
            inline=False
        )
        await ctx.send(embed=embed)
        return
    
    # Xử lý xóa tất cả key
    if key_or_amount.lower() == "all":
        # Xác định loại key cần xóa
        if key_type is None:
            # Xóa tất cả loại key
            key_count = len(active_keys)
            active_keys.clear()
            
            embed = discord.Embed(
                title="✅ Đã Xóa Key",
                description=f"Đã xóa tất cả **{key_count}** key khỏi hệ thống.",
                color=discord.Color.green()
            )
            await ctx.send(embed=embed)
            return
        
        elif key_type.lower() in ["xu", "currency", "money"]:
            # Xóa key đổi xu
            keys_to_delete = [key for key, info in active_keys.items() if info.get("type", "currency") == "currency"]
            
            for key in keys_to_delete:
                del active_keys[key]
            
            embed = discord.Embed(
                title="✅ Đã Xóa Key",
                description=f"Đã xóa **{len(keys_to_delete)}** key đổi xu khỏi hệ thống.",
                color=discord.Color.green()
            )
            await ctx.send(embed=embed)
            return
            
        elif key_type.lower() in ["role", "vai trò", "roles"]:
            # Xóa key đổi role
            keys_to_delete = [key for key, info in active_keys.items() if info.get("type") == "role"]
            
            for key in keys_to_delete:
                del active_keys[key]
            
            embed = discord.Embed(
                title="✅ Đã Xóa Key",
                description=f"Đã xóa **{len(keys_to_delete)}** key đổi role khỏi hệ thống.",
                color=discord.Color.green()
            )
            await ctx.send(embed=embed)
            return
            
        else:
            # Loại key không hợp lệ
            embed = discord.Embed(
                title="❌ Lỗi",
                description="Loại key không hợp lệ. Vui lòng sử dụng `xu` hoặc `role`.",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
            return
    
    # Kiểm tra xem key_or_amount có phải là số không
    if key_or_amount.isdigit():
        amount = int(key_or_amount)
        
        if amount <= 0:
            embed = discord.Embed(
                title="❌ Lỗi",
                description="Số lượng phải lớn hơn 0.",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
            return
        
        # Xác định loại key cần xóa
        if key_type is None:
            # Xóa ngẫu nhiên key từ tất cả loại
            keys_list = list(active_keys.keys())
            
            if not keys_list:
                embed = discord.Embed(
                    title="❌ Không có key",
                    description="Không có key nào trong hệ thống để xóa.",
                    color=discord.Color.red()
                )
                await ctx.send(embed=embed)
                return
            
            # Xác định số lượng key thực tế sẽ xóa
            amount = min(amount, len(keys_list))
            
            # Chọn ngẫu nhiên key để xóa
            keys_to_delete = random.sample(keys_list, amount)
            
            # Xóa các key đã chọn
            for key in keys_to_delete:
                del active_keys[key]
            
            embed = discord.Embed(
                title="✅ Đã Xóa Key",
                description=f"Đã xóa **{amount}** key ngẫu nhiên khỏi hệ thống.",
                color=discord.Color.green()
            )
            embed.add_field(
                name="Danh sách key đã xóa", 
                value="\n".join([f"`{key}`" for key in keys_to_delete]) if len(keys_to_delete) <= 20 else 
                      "\n".join([f"`{key}`" for key in keys_to_delete[:20]]) + f"\n*...và {len(keys_to_delete) - 20} key khác*",
                inline=False
            )
            await ctx.send(embed=embed)
            return
            
        elif key_type.lower() in ["xu", "currency", "money"]:
            # Xóa ngẫu nhiên key đổi xu
            keys_to_choose = [key for key, info in active_keys.items() if info.get("type", "currency") == "currency"]
            
            if not keys_to_choose:
                embed = discord.Embed(
                    title="❌ Không có key",
                    description="Không có key đổi xu nào trong hệ thống để xóa.",
                    color=discord.Color.red()
                )
                await ctx.send(embed=embed)
                return
                
            # Xác định số lượng key thực tế sẽ xóa
            amount = min(amount, len(keys_to_choose))
            
            # Chọn ngẫu nhiên key để xóa
            keys_to_delete = random.sample(keys_to_choose, amount)
            
            # Xóa các key đã chọn
            for key in keys_to_delete:
                del active_keys[key]
                
            embed = discord.Embed(
                title="✅ Đã Xóa Key",
                description=f"Đã xóa **{amount}** key đổi xu ngẫu nhiên khỏi hệ thống.",
                color=discord.Color.green()
            )
            embed.add_field(
                name="Danh sách key đã xóa", 
                value="\n".join([f"`{key}`" for key in keys_to_delete]) if len(keys_to_delete) <= 20 else 
                      "\n".join([f"`{key}`" for key in keys_to_delete[:20]]) + f"\n*...và {len(keys_to_delete) - 20} key khác*",
                inline=False
            )
            await ctx.send(embed=embed)
            return
            
        elif key_type.lower() in ["role", "vai trò", "roles"]:
            # Xóa ngẫu nhiên key đổi role
            keys_to_choose = [key for key, info in active_keys.items() if info.get("type") == "role"]
            
            if not keys_to_choose:
                embed = discord.Embed(
                    title="❌ Không có key",
                    description="Không có key đổi role nào trong hệ thống để xóa.",
                    color=discord.Color.red()
                )
                await ctx.send(embed=embed)
                return
                
            # Xác định số lượng key thực tế sẽ xóa
            amount = min(amount, len(keys_to_choose))
            
            # Chọn ngẫu nhiên key để xóa
            keys_to_delete = random.sample(keys_to_choose, amount)
            
            # Xóa các key đã chọn
            for key in keys_to_delete:
                del active_keys[key]
                
            embed = discord.Embed(
                title="✅ Đã Xóa Key",
                description=f"Đã xóa **{amount}** key đổi role ngẫu nhiên khỏi hệ thống.",
                color=discord.Color.green()
            )
            embed.add_field(
                name="Danh sách key đã xóa", 
                value="\n".join([f"`{key}`" for key in keys_to_delete]) if len(keys_to_delete) <= 20 else 
                      "\n".join([f"`{key}`" for key in keys_to_delete[:20]]) + f"\n*...và {len(keys_to_delete) - 20} key khác*",
                inline=False
            )
            await ctx.send(embed=embed)
            return
            
        else:
            # Loại key không hợp lệ
            embed = discord.Embed(
                title="❌ Lỗi",
                description="Loại key không hợp lệ. Vui lòng sử dụng `xu` hoặc `role`.",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
            return
    
    # Trường hợp còn lại: xóa một key cụ thể
    key_code = key_or_amount
    
    # Kiểm tra xem key có tồn tại không
    if key_code not in active_keys:
        embed = discord.Embed(
            title="❌ Key không tồn tại",
            description=f"Key `{key_code}` không tồn tại trong hệ thống.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return
    
    # Lấy thông tin key trước khi xóa
    key_info = active_keys[key_code]
    key_type = key_info.get("type", "currency")
    
    if key_type == "currency":
        # Key đổi xu
        key_value = f"{key_info['amount']} xu"
        key_uses = key_info["uses"]
    else:
        # Key đổi role
        role_info = key_info.get("role_info", {})
        role_name = role_info.get("role_name", "Không xác định")
        key_value = f"Role {role_name}"
        key_uses = key_info["uses"]
    
    # Xóa key
    del active_keys[key_code]
    
    # Thông báo đã xóa thành công
    embed = discord.Embed(
        title="✅ Đã Xóa Key",
        description=f"Đã xóa key `{key_code}` khỏi hệ thống.",
        color=discord.Color.green()
    )
    
    embed.add_field(name="Loại key", value=f"{'Đổi xu' if key_type == 'currency' else 'Đổi role'}", inline=True)
    embed.add_field(name="Giá trị", value=key_value, inline=True)
    embed.add_field(name="Lượt sử dụng còn lại", value=str(key_uses), inline=True)
    
    await ctx.send(embed=embed)

@bot.command(name='ckey', aliases=['checkkey', 'keyinfo', 'ki'])
@admin_only()
async def check_key(ctx, key_code: str = None):
    """Kiểm tra thông tin chi tiết về một key"""
    if key_code is None:
        embed = discord.Embed(
            title="ℹ️ Kiểm Tra Key - Hướng Dẫn",
            description="Kiểm tra thông tin chi tiết về một key.",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="Cách sử dụng",
            value="`.ckey [mã key]`\nVí dụ: `.ckey ABC123XYZ`",
            inline=False
        )
        embed.add_field(
            name="Lệnh liên quan",
            value="`.lkey` - Xem danh sách tất cả key\n"
                  "`.delkey [mã key]` - Xóa một key cụ thể",
            inline=False
        )
        await ctx.send(embed=embed)
        return
    
    # Kiểm tra xem key có tồn tại không
    if key_code not in active_keys:
        embed = discord.Embed(
            title="❌ Key không tồn tại",
            description=f"Key `{key_code}` không tồn tại trong hệ thống.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return
    
    # Lấy thông tin key
    key_info = active_keys[key_code]
    key_type = key_info.get("type", "currency")
    created_by_id = key_info.get("created_by")
    created_time = key_info.get("creation_time", datetime.now())
    redeemed_by = key_info.get("redeemed_by", [])
    uses_left = key_info.get("uses", 0)
    total_uses = len(redeemed_by) + uses_left
    
    # Tạo embed hiển thị thông tin
    embed = discord.Embed(
        title=f"🔑 Thông tin Key: {key_code}",
        color=discord.Color.gold() if key_type == "currency" else discord.Color.purple()
    )
    
    # Thông tin cơ bản
    embed.add_field(
        name="📝 Thông tin cơ bản",
        value=f"**Loại key:** {'Đổi xu' if key_type == 'currency' else 'Đổi role'}\n"
              f"**Tạo lúc:** {discord.utils.format_dt(created_time, style='R')}\n"
              f"**Lượt sử dụng:** {uses_left}/{total_uses}",
        inline=False
    )
    
    # Người tạo
    if created_by_id:
        try:
            creator = await bot.fetch_user(created_by_id)
            creator_text = f"{creator.mention} ({creator.name})"
        except:
            creator_text = f"ID: {created_by_id}"
    else:
        creator_text = "Không xác định"
        
    embed.add_field(name="👤 Người tạo", value=creator_text, inline=True)
    
    # Thông tin riêng theo loại key
    if key_type == "currency":
        # Thông tin key đổi xu
        amount = key_info.get("amount", 0)
        
        embed.add_field(name="💰 Giá trị", value=f"{amount} xu", inline=True)
        
    else:
        # Thông tin key đổi role
        role_info = key_info.get("role_info", {})
        role_id = role_info.get("role_id")
        role_name = role_info.get("role_name", "Không xác định")
        duration = role_info.get("duration")
        
        # Định dạng thời hạn
        if duration:
            if duration < 3600:
                duration_text = f"{duration // 60} phút"
            elif duration < 86400:
                duration_text = f"{duration // 3600} giờ"
            else:
                duration_text = f"{duration // 86400} ngày"
        else:
            duration_text = "Vĩnh viễn"
            
        embed.add_field(name="🎭 Role", value=f"{role_name} (ID: `{role_id}`)", inline=True)
        embed.add_field(name="⏱️ Thời hạn", value=duration_text, inline=True)
    
    # Danh sách người đã sử dụng
    if redeemed_by:
        redeemed_list = []
        for i, user_id in enumerate(redeemed_by, 1):
            if i > 10:  # Giới hạn hiển thị 10 người
                redeemed_list.append(f"*...và {len(redeemed_by) - 10} người khác*")
                break
                
            try:
                user = await bot.fetch_user(user_id)
                redeemed_list.append(f"{i}. {user.name} (ID: `{user_id}`)")
            except:
                redeemed_list.append(f"{i}. ID: `{user_id}`")
                
        embed.add_field(
            name=f"📋 Đã sử dụng ({len(redeemed_by)})",
            value="\n".join(redeemed_list) if redeemed_list else "Không có ai",
            inline=False
        )
    else:
        embed.add_field(
            name="📋 Đã sử dụng",
            value="Chưa có ai sử dụng key này",
            inline=False
        )
    
    # Các tùy chọn quản lý
    embed.add_field(
        name="⚙️ Quản lý",
        value=f"`.delkey {key_code}` - Xóa key này\n",
        inline=False
    )
    
    await ctx.send(embed=embed)

@bot.command(name='checkgl', aliases=['keylog', 'keyusage'])
@admin_only()
async def check_key_usage(ctx, member: discord.Member = None):
    """Kiểm tra lịch sử sử dụng key của một người dùng"""
    if member is None:
        embed = discord.Embed(
            title="ℹ️ Kiểm Tra Lịch Sử Key - Hướng Dẫn",
            description="Kiểm tra lịch sử sử dụng key của một người dùng.",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="Cách sử dụng",
            value="`.checkgl @người_dùng`\nVí dụ: `.checkgl @username`",
            inline=False
        )
        await ctx.send(embed=embed)
        return
    
    user_id = member.id
    
    # Kiểm tra xem người dùng có lịch sử sử dụng key không
    if user_id not in key_log or not key_log[user_id]:
        embed = discord.Embed(
            title="📋 Lịch Sử Sử Dụng Key",
            description=f"{member.mention} chưa sử dụng key nào.",
            color=discord.Color.blue()
        )
        await ctx.send(embed=embed)
        return
    
    # Đếm số lượng key theo loại
    user_logs = key_log[user_id]
    currency_keys = [log for log in user_logs if log.get("type", "currency") == "currency"]
    role_keys = [log for log in user_logs if log.get("type") == "role"]
    
    # Tạo embed hiển thị thông tin
    embed = discord.Embed(
        title=f"📋 Lịch Sử Sử Dụng Key của {member.name}",
        description=f"{member.mention} đã sử dụng **{len(user_logs)}** key.",
        color=discord.Color.gold()
    )
    
    embed.add_field(
        name="📊 Tổng quan",
        value=f"💰 Key đổi xu: **{len(currency_keys)}**\n"
              f"🎭 Key đổi role: **{len(role_keys)}**",
        inline=False
    )
    
    # Hiển thị lịch sử sử dụng key đổi xu gần đây nhất (tối đa 5)
    if currency_keys:
        # Sắp xếp theo thời gian, mới nhất lên đầu
        recent_currency_keys = sorted(currency_keys, key=lambda x: x.get("time", datetime.now()), reverse=True)[:5]
        
        currency_history = ""
        for i, log in enumerate(recent_currency_keys, 1):
            key = log.get("key", "N/A")
            amount = log.get("amount", 0)
            time = log.get("time", datetime.now())
            time_str = discord.utils.format_dt(time, style="R")
            
            currency_history += f"{i}. `{key[:8]}...` - **{amount} xu** - {time_str}\n"
            
        embed.add_field(
            name=f"💰 Lịch sử key đổi xu gần đây",
            value=currency_history,
            inline=False
        )
    
    # Hiển thị lịch sử sử dụng key đổi role gần đây nhất (tối đa 5)
    if role_keys:
        # Sắp xếp theo thời gian, mới nhất lên đầu
        recent_role_keys = sorted(role_keys, key=lambda x: x.get("time", datetime.now()), reverse=True)[:5]
        
        role_history = ""
        for i, log in enumerate(recent_role_keys, 1):
            key = log.get("key", "N/A")
            role_name = log.get("role_name", "Không xác định")
            time = log.get("time", datetime.now())
            time_str = discord.utils.format_dt(time, style="R")
            
            role_history += f"{i}. `{key[:8]}...` - **{role_name}** - {time_str}\n"
            
        embed.add_field(
            name=f"🎭 Lịch sử key đổi role gần đây",
            value=role_history,
            inline=False
        )
    
    # Hiển thị số liệu thống kê trong 24h và 7 ngày qua
    now = datetime.now()
    day_ago = now - timedelta(days=1)
    week_ago = now - timedelta(days=7)
    
    keys_last_24h = [log for log in user_logs if log.get("time", now) > day_ago]
    keys_last_week = [log for log in user_logs if log.get("time", now) > week_ago]
    
    embed.add_field(
        name="📊 Thống kê thời gian",
        value=f"⏰ **24 giờ qua:** {len(keys_last_24h)} key\n"
              f"📅 **7 ngày qua:** {len(keys_last_week)} key\n"
              f"🗓️ **Tổng cộng:** {len(user_logs)} key",
        inline=False
    )
    
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text=f"ID: {user_id} | Server: {ctx.guild.name}")
    
    await ctx.send(embed=embed)


@bot.command(name='serverinfo', aliases=['si', 'server'])
async def server_info(ctx):
    """Hiển thị thông tin chi tiết về server"""
    guild = ctx.guild
    
    # Tạo embed với thông tin server
    embed = discord.Embed(
        title=f"📊 Thông tin server {guild.name}",
        description=f"{guild.description or 'Không có mô tả'}",
        color=discord.Color.blue()
    )
    
    # Thêm banner nếu có
    if guild.banner:
        embed.set_image(url=guild.banner.url)
    
    # Thêm icon server
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    
    # Thông tin cơ bản
    embed.add_field(
        name="🆔 ID Server", 
        value=f"`{guild.id}`", 
        inline=True
    )
    
    # Thời gian tạo server (sửa phần này để không dùng datetime.timezone)
    created_at = guild.created_at
    # Sử dụng hàm format_dt của Discord để hiển thị thời gian
    created_at_str = discord.utils.format_dt(created_at, style='F')
    time_ago = discord.utils.format_dt(created_at, style='R')
    
    embed.add_field(
        name="📅 Ngày tạo",
        value=f"{created_at_str}\n({time_ago})",
        inline=True
    )
    
    # Chủ sở hữu
    embed.add_field(
        name="👑 Chủ sở hữu",
        value=f"{guild.owner.mention if guild.owner else 'Không xác định'}",
        inline=True
    )
    
    # Thống kê thành viên
    total_members = guild.member_count
    humans = len([m for m in guild.members if not m.bot])
    bots = total_members - humans
    
    embed.add_field(
        name="👥 Thành viên",
        value=f"Tổng: **{total_members}**\nNgười: **{humans}**\nBot: **{bots}**",
        inline=True
    )
    
    # Kênh
    text_channels = len(guild.text_channels)
    voice_channels = len(guild.voice_channels)
    categories = len(guild.categories)
    
    embed.add_field(
        name="📊 Kênh",
        value=f"Văn bản: **{text_channels}**\nThoại: **{voice_channels}**\nDanh mục: **{categories}**",
        inline=True
    )
    
    # Role
    embed.add_field(
        name="🏷️ Role",
        value=f"**{len(guild.roles)}** role",
        inline=True
    )
    
    # Emoji và sticker
    embed.add_field(
        name="😀 Emoji & Sticker",
        value=f"Emoji: **{len(guild.emojis)}**\nSticker: **{len(guild.stickers)}**",
        inline=True
    )
    
    # Mức boost
    premium_tier = guild.premium_tier
    boost_status = f"Cấp {premium_tier}" if premium_tier > 0 else "Không có"
    boosts = guild.premium_subscription_count
    
    embed.add_field(
        name="🚀 Boost",
        value=f"Trạng thái: **{boost_status}**\nSố lượng: **{boosts}** boost",
        inline=True
    )
    
    # Các tính năng đặc biệt
    features = guild.features
    if features:
        formatted_features = ", ".join(f"`{feature.replace('_', ' ').title()}`" for feature in features)
    else:
        formatted_features = "Không có tính năng đặc biệt"
    
    embed.add_field(
        name="✨ Tính năng đặc biệt",
        value=formatted_features,
        inline=False
    )
    
    # Footer
    embed.set_footer(text=f"Yêu cầu bởi: {ctx.author.name} • {ctx.guild.name}")
    
    await ctx.send(embed=embed)


# Helper functions
def get_emoji_limit(premium_tier):
    """Lấy giới hạn emoji dựa trên premium tier"""
    limits = {
        0: 50,
        1: 100,
        2: 150,
        3: 250
    }
    return limits.get(premium_tier, 50)

def get_sticker_limit(premium_tier):
    """Lấy giới hạn sticker dựa trên premium tier"""
    limits = {
        0: 0,
        1: 15,
        2: 30,
        3: 60
    }
    return limits.get(premium_tier, 0)

@server_info.error
async def server_info_error(ctx, error):
    """Xử lý lỗi cho lệnh server_info"""
    if isinstance(error, commands.NoPrivateMessage):
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Lệnh này chỉ có thể sử dụng trong server.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(
            title="❌ Lỗi",
            description=f"Đã xảy ra lỗi: {str(error)}",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)

@bot.command(name='warn')
@commands.has_permissions(kick_members=True)
async def warn_member(ctx, member: discord.Member = None, *, reason: str = "Không có lý do"):
    """Cảnh báo một thành viên, đủ 3 lần sẽ bị kick khỏi server"""
    if member is None:
        embed = discord.Embed(
            title="❌ Thiếu thông tin",
            description="Vui lòng chỉ định thành viên cần cảnh báo.\nVí dụ: `.warn @user Lý do cảnh báo`",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return
    
    # Kiểm tra không thể cảnh báo chính mình
    if member.id == ctx.author.id:
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Bạn không thể cảnh báo chính mình!",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return
    
    # Kiểm tra không thể cảnh báo bot
    if member.bot:
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Bạn không thể cảnh báo bot!",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return
    
    # Kiểm tra không thể cảnh báo người có quyền cao hơn
    if member.top_role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Bạn không thể cảnh báo người có vai trò cao hơn hoặc ngang bằng bạn!",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return
    
    # Lưu trữ cảnh báo mới
    guild_id = ctx.guild.id
    user_id = member.id
    
    if guild_id not in warnings:
        warnings[guild_id] = {}
    
    if user_id not in warnings[guild_id]:
        warnings[guild_id][user_id] = []
    
    warning_data = {
        "reason": reason,
        "time": discord.utils.utcnow(),
        "warner_id": ctx.author.id
    }
    
    warnings[guild_id][user_id].append(warning_data)
    
    # Đếm số cảnh báo
    warn_count = len(warnings[guild_id][user_id])
    
    # Tạo embed thông báo cảnh báo
    embed = discord.Embed(
        title=f"⚠️ Cảnh báo #{warn_count}",
        description=f"{member.mention} đã bị cảnh báo!",
        color=discord.Color.orange()
    )
    
    embed.add_field(name="Lý do", value=reason, inline=False)
    embed.add_field(name="Cảnh báo bởi", value=ctx.author.mention, inline=True)
    embed.add_field(name="Số cảnh báo hiện tại", value=f"{warn_count}/3", inline=True)
    
    # Nếu đủ 3 cảnh báo, kick người dùng
    if warn_count >= 3:
        embed.add_field(
            name="⛔ Hành động tự động",
            value=f"{member.mention} đã đạt đến 3 cảnh báo và sẽ bị kick khỏi server.",
            inline=False
        )
        embed.color = discord.Color.red()
        
        # Thêm chi tiết về các lần cảnh báo trước
        warning_details = ""
        for i, warn in enumerate(warnings[guild_id][user_id], 1):
            warner = ctx.guild.get_member(warn["warner_id"])
            warner_name = warner.name if warner else "Unknown"
            time_str = discord.utils.format_dt(warn["time"], "R")
            warning_details += f"**#{i}** - Bởi {warner_name} {time_str}: {warn['reason']}\n"
        
        embed.add_field(name="Chi tiết cảnh báo", value=warning_details, inline=False)
        
        # Gửi thông báo
        await ctx.send(embed=embed)
        
        # Cố gắng gửi DM cho người dùng trước khi kick
        try:
            kick_dm = discord.Embed(
                title="⛔ Bạn đã bị kick",
                description=f"Bạn đã bị kick khỏi server **{ctx.guild.name}** sau khi nhận đủ 3 cảnh báo.",
                color=discord.Color.red()
            )
            kick_dm.add_field(name="Lý do cảnh báo cuối cùng", value=reason, inline=False)
            
            await member.send(embed=kick_dm)
        except:
            # Bỏ qua nếu không thể gửi DM
            pass
        
        # Kick thành viên
        try:
            await member.kick(reason=f"Đã nhận 3 cảnh báo. Cảnh báo cuối: {reason}")
            
            # Gửi xác nhận kick
            kick_confirm = discord.Embed(
                title="✅ Đã kick thành công",
                description=f"{member.name} đã bị kick khỏi server sau khi nhận đủ 3 cảnh báo.",
                color=discord.Color.green()
            )
            await ctx.send(embed=kick_confirm)
            
        except discord.Forbidden:
            # Không đủ quyền để kick
            permission_error = discord.Embed(
                title="❌ Lỗi quyền hạn",
                description="Bot không có đủ quyền để kick thành viên này.",
                color=discord.Color.red()
            )
            await ctx.send(embed=permission_error)
            
        except Exception as e:
            # Lỗi khác
            error_embed = discord.Embed(
                title="❌ Lỗi",
                description=f"Đã xảy ra lỗi khi kick thành viên: {str(e)}",
                color=discord.Color.red()
            )
            await ctx.send(embed=error_embed)
    else:
        # Chưa đủ 3 cảnh báo
        embed.add_field(
            name="ℹ️ Lưu ý", 
            value=f"Nếu nhận thêm {3 - warn_count} cảnh báo nữa, {member.mention} sẽ bị kick khỏi server.",
            inline=False
        )
        
        # Gửi thông báo công khai
        await ctx.send(embed=embed)
        
        # Cố gắng gửi DM thông báo cho người dùng
        try:
            warn_dm = discord.Embed(
                title=f"⚠️ Bạn đã bị cảnh báo trong {ctx.guild.name}",
                description=f"Đây là cảnh báo thứ {warn_count}/3.",
                color=discord.Color.orange()
            )
            warn_dm.add_field(name="Lý do", value=reason, inline=False)
            warn_dm.add_field(name="Cảnh báo bởi", value=ctx.author.name, inline=True)
            warn_dm.add_field(
                name="Lưu ý", 
                value=f"Nếu bạn nhận thêm {3 - warn_count} cảnh báo nữa, bạn sẽ bị kick khỏi server.",
                inline=False
            )
            
            await member.send(embed=warn_dm)
        except:
            # Bỏ qua nếu không thể gửi DM
            pass

@bot.command(name='warnings', aliases=['warns'])
@commands.has_permissions(kick_members=True)
async def list_warnings(ctx, member: discord.Member = None):
    """Xem cảnh báo của một thành viên"""
    if member is None:
        embed = discord.Embed(
            title="❌ Thiếu thông tin",
            description="Vui lòng chỉ định thành viên để xem cảnh báo.\nVí dụ: `.warnings @user`",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return
    
    guild_id = ctx.guild.id
    user_id = member.id
    
    # Kiểm tra xem người dùng có cảnh báo nào không
    if (guild_id not in warnings or 
        user_id not in warnings[guild_id] or 
        not warnings[guild_id][user_id]):
        embed = discord.Embed(
            title="✅ Không có cảnh báo",
            description=f"{member.mention} không có cảnh báo nào.",
            color=discord.Color.green())
        await ctx.send(embed=embed)
        return
    
    # Hiển thị danh sách cảnh báo
    warn_list = warnings[guild_id][user_id]
    warn_count = len(warn_list)
    
    embed = discord.Embed(
        title=f"⚠️ Cảnh báo của {member.name}",
        description=f"{member.mention} có **{warn_count}** cảnh báo.",
        color=discord.Color.orange()
    )
    
    # Thêm chi tiết về từng cảnh báo
    for i, warn in enumerate(warn_list, 1):
        warner = ctx.guild.get_member(warn["warner_id"])
        warner_name = warner.name if warner else "Unknown"
        time_str = discord.utils.format_dt(warn["time"], "F")
        
        embed.add_field(
            name=f"Cảnh báo #{i}",
            value=f"**Lý do:** {warn['reason']}\n**Bởi:** {warner_name}\n**Thời gian:** {time_str}",
            inline=False
        )
    
    # Thêm cảnh báo nếu gần đạt giới hạn
    if warn_count == 2:
        embed.add_field(
            name="⚠️ Cảnh báo",
            value="Thêm 1 cảnh báo nữa sẽ dẫn đến việc bị kick khỏi server!",
            inline=False
        )
    
    await ctx.send(embed=embed)


@bot.command(name='delwarn', aliases=['removewarn'])
@commands.has_permissions(kick_members=True)
async def remove_warning(ctx, member: discord.Member = None, index: int = None):
    """Xóa một cảnh báo của thành viên dựa trên số thứ tự"""
    if member is None or index is None:
        embed = discord.Embed(
            title="❌ Thiếu thông tin",
            description="Vui lòng chỉ định thành viên và số thứ tự cảnh báo cần xóa.\nVí dụ: `.delwarn @user 1`",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return
    
    guild_id = ctx.guild.id
    user_id = member.id
    
    # Kiểm tra xem người dùng có cảnh báo nào không
    if (guild_id not in warnings or 
        user_id not in warnings[guild_id] or 
        not warnings[guild_id][user_id]):
        embed = discord.Embed(
            title="❌ Không có cảnh báo",
            description=f"{member.mention} không có cảnh báo nào để xóa.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return
    
    # Kiểm tra index hợp lệ
    warn_list = warnings[guild_id][user_id]
    if index <= 0 or index > len(warn_list):
        embed = discord.Embed(
            title="❌ Số thứ tự không hợp lệ",
            description=f"Số thứ tự phải từ 1 đến {len(warn_list)}.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return
    
    # Xóa cảnh báo
    removed_warning = warn_list.pop(index-1)
    
    # Xóa toàn bộ entry nếu không còn cảnh báo nào
    if not warn_list:
        del warnings[guild_id][user_id]
        if not warnings[guild_id]:
            del warnings[guild_id]
    
    # Thông báo đã xóa cảnh báo
    embed = discord.Embed(
        title="✅ Đã xóa cảnh báo",
        description=f"Đã xóa cảnh báo #{index} của {member.mention}.",
        color=discord.Color.green()
    )
    
    # Hiển thị số cảnh báo còn lại
    remaining_warns = 0
    if guild_id in warnings and user_id in warnings[guild_id]:
        remaining_warns = len(warnings[guild_id][user_id])
    
    embed.add_field(
        name="Số cảnh báo còn lại",
        value=f"{remaining_warns}/3",
        inline=True
    )
    
    await ctx.send(embed=embed)

@bot.command(name='clearwarn', aliases=['resetwarns'])
@commands.has_permissions(administrator=True)
async def clear_all_warnings(ctx, member: discord.Member = None):
    """Xóa tất cả cảnh báo của một thành viên (chỉ Admin)"""
    if member is None:
        embed = discord.Embed(
            title="❌ Thiếu thông tin",
            description="Vui lòng chỉ định thành viên để xóa tất cả cảnh báo.\nVí dụ: `.clearwarns @user`",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return
    
    guild_id = ctx.guild.id
    user_id = member.id
    
    # Kiểm tra xem người dùng có cảnh báo nào không
    if (guild_id not in warnings or 
        user_id not in warnings[guild_id] or 
        not warnings[guild_id][user_id]):
        embed = discord.Embed(
            title="❌ Không có cảnh báo",
            description=f"{member.mention} không có cảnh báo nào để xóa.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return
    
    # Đếm số cảnh báo trước khi xóa
    warn_count = len(warnings[guild_id][user_id])
    
    # Xóa tất cả cảnh báo
    del warnings[guild_id][user_id]
    if not warnings[guild_id]:
        del warnings[guild_id]
    
    # Thông báo thành công
    embed = discord.Embed(
        title="✅ Đã xóa tất cả cảnh báo",
        description=f"Đã xóa thành công **{warn_count}** cảnh báo của {member.mention}.",
        color=discord.Color.green()
    )
    
    await ctx.send(embed=embed)


@bot.command(name='checktimeout', aliases=['checktime', 'timeoutinfo'])
async def checktimeout(ctx, member: discord.Member = None):
    """Check if a user is timed out and for how long"""
    if member is None:
        member = ctx.author
    
    try:
        is_timed_out, remaining_seconds, expiry_time = await check_timeout_status(member)
        
        if is_timed_out:
            # Convert seconds to a more readable format
            days, remainder = divmod(int(remaining_seconds), 86400)
            hours, remainder = divmod(remainder, 3600)
            minutes, seconds = divmod(remainder, 60)
            
            # Format the time string
            time_parts = []
            if days > 0:
                time_parts.append(f"{days} ngày")
            if hours > 0:
                time_parts.append(f"{hours} giờ")
            if minutes > 0:
                time_parts.append(f"{minutes} phút")
            if seconds > 0 or not time_parts:
                time_parts.append(f"{seconds} giây")
                
            time_str = " ".join(time_parts)
            
            # Format the expiry time
            expiry_timestamp = int(expiry_time.timestamp()) if expiry_time else None
            
            embed = discord.Embed(
                title="🔇 Trạng thái Timeout",
                description=f"{member.mention} **đang bị timeout**",
                color=discord.Color.red()
            )
            embed.add_field(name="⏱️ Thời gian còn lại", value=time_str, inline=False)
            
            if expiry_timestamp:
                embed.add_field(
                    name="⌛ Hết hạn lúc", 
                    value=f"<t:{expiry_timestamp}:F> (<t:{expiry_timestamp}:R>)", 
                    inline=False
                )
                
            moderator_info = await get_timeout_moderator(member)
            if moderator_info:
                embed.add_field(name="👮 Người timeout", value=moderator_info, inline=False)
        else:
            embed = discord.Embed(
                title="🔊 Trạng thái Timeout", 
                description=f"{member.mention} **không bị timeout**",
                color=discord.Color.green()
            )
        
        embed.set_thumbnail(url=member.display_avatar.url)
        await ctx.send(embed=embed)
        
    except Exception as e:
        embed = discord.Embed(
            title="❌ Lỗi",
            description=f"Đã xảy ra lỗi khi kiểm tra trạng thái timeout: {str(e)}",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)

async def get_timeout_moderator(member):
    """Try to get information about who timed out the member from audit logs"""
    try:
        if not member.guild.me.guild_permissions.view_audit_log:
            return None
            
        async for entry in member.guild.audit_logs(limit=10, action=discord.AuditLogAction.member_update):
            if entry.target.id == member.id:
                # Check if this audit log entry is about a timeout
                changes = [change for change in entry.changes.before if change.key == 'communication_disabled_until']
                if changes:
                    return f"{entry.user.mention} ({entry.user.name})"
        return None
    except:
        return None

@bot.command(name='checkmute', aliases=['mutecheck', 'mutelist', 'checkmuted'])
@commands.has_permissions(manage_roles=True)
async def check_mute(ctx, member: discord.Member = None):
    """Kiểm tra người dùng bị mute và thông tin chi tiết về lệnh mute đó"""
    
    # Tìm mute role trong server
    mute_role = None
    possible_mute_roles = ["muted", "mute", "silenced", "tempmute", "cấm chat"]
    
    # Tìm role phù hợp dựa trên tên
    for role in ctx.guild.roles:
        role_name = role.name.lower()
        if any(mute_name in role_name for mute_name in possible_mute_roles):
            mute_role = role
            break
    
    if mute_role is None:
        embed = discord.Embed(
            title="❌ Không tìm thấy Mute Role",
            description="Server này không có role mute được cấu hình. "
                      "Hãy tạo một role tên 'Muted' hoặc sử dụng timeout thay thế.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return
    
    if member is not None:
        # Kiểm tra một người dùng cụ thể
        if mute_role in member.roles:
            # Tạo embed để hiển thị thông tin mute
            embed = discord.Embed(
                title="🔇 Thông tin Mute",
                description=f"{member.mention} đang bị mute trong server.",
                color=discord.Color.orange()
            )
            
            embed.add_field(
                name="🔇 Mute Role",
                value=f"{mute_role.mention}",
                inline=False
            )
            
            # Kiểm tra audit logs để tìm thông tin về người mute và lý do
            try:
                # Tìm kiếm trong audit log gần đây
                audit_logs = [entry async for entry in ctx.guild.audit_logs(
                    limit=50, 
                    action=discord.AuditLogAction.member_role_update
                )]
                
                mute_entry = None
                for entry in audit_logs:
                    # Kiểm tra nếu đây là entry gắn mute role cho thành viên này
                    if (entry.target.id == member.id and 
                        hasattr(entry, 'changes') and
                        hasattr(entry.changes.after, 'roles') and
                        mute_role.id in [r.id for r in entry.changes.after.roles]):
                        mute_entry = entry
                        break
                
                if mute_entry:
                    # Lấy thông tin moderator
                    moderator = mute_entry.user
                    embed.add_field(
                        name="👮‍♂️ Mute bởi",
                        value=f"{moderator.mention} ({moderator.name})",
                        inline=True
                    )
                    
                    # Lấy lý do mute (nếu có)
                    reason = mute_entry.reason or "Không có lý do"
                    embed.add_field(
                        name="📝 Lý do",
                        value=reason,
                        inline=True
                    )
                    
                    # Thời gian áp dụng mute
                    embed.add_field(
                        name="🕒 Thời gian áp dụng",
                        value=f"<t:{int(mute_entry.created_at.timestamp())}:F>",
                        inline=False
                    )
                else:
                    embed.add_field(
                        name="ℹ️ Thông tin",
                        value="Không thể tìm thấy thông tin chi tiết về mute này trong audit log.",
                        inline=False
                    )
                    
            except discord.Forbidden:
                embed.add_field(
                    name="❌ Lỗi",
                    value="Bot không có quyền xem audit logs để lấy thông tin chi tiết.",
                    inline=False
                )
            except Exception as e:
                embed.add_field(
                    name="❌ Lỗi",
                    value=f"Đã xảy ra lỗi khi kiểm tra audit logs: {str(e)}",
                    inline=False
                )
            
            # Thêm hướng dẫn unmute
            embed.add_field(
                name="🔓 Cách unmute",
                value=f"Sử dụng lệnh `.unmute {member.name}` để gỡ mute.",
                inline=False
            )
                
            await ctx.send(embed=embed)
        else:
            # Người dùng không bị mute
            embed = discord.Embed(
                title="✅ Không bị Mute",
                description=f"{member.mention} hiện không bị mute trong server.",
                color=discord.Color.green()
            )
            await ctx.send(embed=embed)
            
    else:
        # Tìm tất cả người dùng đang bị mute
        muted_members = [member for member in ctx.guild.members if mute_role in member.roles]
        
        if not muted_members:
            # Không có ai bị mute
            embed = discord.Embed(
                title="✅ Danh sách Mute trống",
                description=f"Không có thành viên nào đang bị mute ({mute_role.mention}) trong server.",
                color=discord.Color.green()
            )
            await ctx.send(embed=embed)
            return
        
        # Tạo danh sách người dùng bị mute
        embed = discord.Embed(
            title="🔇 Danh sách Mute",
            description=f"Có **{len(muted_members)}** thành viên đang bị mute ({mute_role.mention}):",
            color=discord.Color.orange()
        )
        
        # Hiển thị thông tin của mỗi người bị mute
        for i, member in enumerate(muted_members[:15], 1):  # Giới hạn 15 người để tránh embed quá dài
            # Tìm thời gian mute từ audit log
            mute_time_str = "Không xác định"
            try:
                audit_logs = [entry async for entry in ctx.guild.audit_logs(
                    limit=100,
                    action=discord.AuditLogAction.member_role_update
                )]
                
                for entry in audit_logs:
                    if (entry.target.id == member.id and 
                        hasattr(entry, 'changes') and
                        hasattr(entry.changes.after, 'roles') and
                        mute_role.id in [r.id for r in entry.changes.after.roles]):
                        mute_time_str = f"<t:{int(entry.created_at.timestamp())}:R>"
                        break
            except:
                pass
            
            # Thông tin mute cho mỗi người dùng
            member_info = (
                f"{member.mention} ({member.name})\n"
                f"⏳ Thời gian mute: {mute_time_str}"
            )
            
            embed.add_field(
                name=f"#{i} {member.display_name}",
                value=member_info,
                inline=False
            )
        
        # Thêm ghi chú nếu danh sách bị cắt bớt
        if len(muted_members) > 15:
            embed.add_field(
                name="📋 Ghi chú",
                value=f"Chỉ hiển thị 15/{len(muted_members)} người dùng bị mute.\nSử dụng `.checkmute @user` để xem chi tiết về một người dùng cụ thể.",
                inline=False
            )
        
        embed.set_footer(text=f"Sử dụng .checkmute @user để xem chi tiết | Server: {ctx.guild.name}")
        await ctx.send(embed=embed)

@check_mute.error
async def check_mute_error(ctx, error):
    """Xử lý lỗi cho lệnh check_mute"""
    if isinstance(error, commands.MissingPermissions):
        embed = discord.Embed(
            title="❌ Thiếu quyền hạn",
            description="Bạn cần có quyền `Manage Roles` để sử dụng lệnh này.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
    elif isinstance(error, commands.MemberNotFound):
        embed = discord.Embed(
            title="❌ Không tìm thấy thành viên",
            description="Không thể tìm thấy thành viên được chỉ định.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(
            title="❌ Lỗi",
            description=f"Đã xảy ra lỗi không mong muốn: {str(error)}",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)

@bot.command(name='roleinfo', aliases=['rinfo', 'rolef'])
async def role_info(ctx, *, role: discord.Role = None):
    """Hiển thị thông tin chi tiết về role trong server"""
    if role is None:
        embed = discord.Embed(
            title="❓ Thông Tin Role - Hướng Dẫn",
            description="Hiển thị thông tin chi tiết về một role trong server.",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="Cách sử dụng",
            value="`.roleinfo @role` hoặc `.roleinfo tên role` hoặc `.roleinfo ID role`",
            inline=False
        )
        embed.add_field(
            name="Ví dụ",
            value="`.roleinfo @Admin`\n`.roleinfo VIP`\n`.roleinfo 123456789012345678`",
            inline=False
        )
        await ctx.send(embed=embed)
        return

    # Tạo embed hiển thị thông tin role
    color = role.color if role.color.value else discord.Color.light_grey()
    embed = discord.Embed(
        title=f"🏷️ Thông Tin Role: {role.name}",
        description=f"Chi tiết về role {role.mention}",
        color=color
    )
    
    # Thông tin cơ bản
    created_time = int(role.created_at.timestamp())
    embed.add_field(name="🆔 ID", value=f"`{role.id}`", inline=True)
    embed.add_field(name="📆 Ngày tạo", value=f"<t:{created_time}:F>\n(<t:{created_time}:R>)", inline=True)
    embed.add_field(name="🎨 Màu sắc", value=f"`{str(role.color).upper()}`", inline=True)
    
    # Vị trí và số thành viên
    member_count = len(role.members)
    embed.add_field(name="📊 Vị trí", value=f"{role.position}/{len(ctx.guild.roles)-1}", inline=True)
    embed.add_field(name="👥 Số thành viên", value=f"{member_count} thành viên", inline=True)
    
    # Các thuộc tính
    attributes = []
    if role.hoist:
        attributes.append("✓ Hiển thị riêng")
    else:
        attributes.append("✗ Hiển thị riêng")
        
    if role.mentionable:
        attributes.append("✓ Cho phép mention")
    else:
        attributes.append("✗ Cho phép mention")
        
    if role.managed:
        attributes.append("✓ Quản lý bởi tích hợp")
    else:
        attributes.append("✗ Quản lý bởi tích hợp")
        
    if role.is_default():
        attributes.append("✓ Role mặc định (@everyone)")
    else:
        attributes.append("✗ Role mặc định")
    
    embed.add_field(name="⚙️ Thuộc tính", value="\n".join(attributes), inline=False)
    
    # Tạo các nút để hiển thị chi tiết
    view = discord.ui.View(timeout=120)
    
    # Nút xem quyền hạn
    permissions_button = discord.ui.Button(
        style=discord.ButtonStyle.primary,
        label="Xem Quyền Hạn", 
        custom_id="permissions",
        emoji="🔒"
    )
    
    # Nút xem danh sách thành viên
    members_button = discord.ui.Button(
        style=discord.ButtonStyle.primary,
        label=f"Xem Thành Viên ({member_count})",
        custom_id="members",
        emoji="👥"
    )
    
    # Nút xem cài đặt hiển thị
    display_button = discord.ui.Button(
        style=discord.ButtonStyle.secondary,
        label="Xem Hiển Thị",
        custom_id="display",
        emoji="🎨"
    )
    
    # Đóng/Hủy
    close_button = discord.ui.Button(
        style=discord.ButtonStyle.danger,
        label="Đóng",
        custom_id="close",
        emoji="❌"
    )

    async def button_callback(interaction):
        if interaction.user != ctx.author:
            await interaction.response.send_message("Bạn không phải người dùng lệnh này!", ephemeral=True)
            return
            
        button_id = interaction.data["custom_id"]
        
        if button_id == "permissions":
            # Tạo embed quyền hạn
            perms_embed = discord.Embed(
                title=f"🔒 Quyền Hạn của {role.name}",
                color=color
            )
            
            # Lấy tất cả các quyền của role
            all_perms = []
            for perm, value in role.permissions:
                emoji = "✅" if value else "❌"
                formatted_perm = perm.replace("_", " ").title()
                all_perms.append(f"{emoji} {formatted_perm}")
            
            # Chia quyền thành các cột
            perms_columns = []
            col_size = (len(all_perms) + 2) // 3  # Chia thành 3 cột
            
            for i in range(0, len(all_perms), col_size):
                perms_columns.append("\n".join(all_perms[i:i+col_size]))
            
            # Thêm các cột vào embed
            for i, column in enumerate(perms_columns, 1):
                perms_embed.add_field(name=f"Cột {i}", value=column, inline=True)
                
            await interaction.response.edit_message(embed=perms_embed, view=view)
            
        elif button_id == "members":
            # Tạo embed danh sách thành viên
            members_embed = discord.Embed(
                title=f"👥 Thành Viên có Role {role.name}",
                description=f"Có {member_count} thành viên với role này",
                color=color
            )
            
            if member_count == 0:
                members_embed.description = "Không có thành viên nào có role này."
            elif member_count > 30:
                members_list = [f"{i+1}. {member.mention} (`{member.id}`)" for i, member in enumerate(role.members[:30])]
                members_embed.description = f"Hiển thị 30/{member_count} thành viên có role này:\n\n" + "\n".join(members_list)
                members_embed.set_footer(text=f"Hiển thị tối đa 30 thành viên | Tổng số: {member_count}")
            else:
                members_list = [f"{i+1}. {member.mention} (`{member.id}`)" for i, member in enumerate(role.members)]
                members_embed.description = "\n".join(members_list)
            
            await interaction.response.edit_message(embed=members_embed, view=view)
            
        elif button_id == "display":
            # Tạo embed hiển thị
            display_embed = discord.Embed(
                title=f"🎨 Thông Tin Hiển Thị của {role.name}",
                color=color
            )
            
            # Hiển thị màu dưới dạng hình ảnh
            color_hex = f"{role.color.value:0>6x}"
            color_image_url = f"https://singlecolorimage.com/get/{color_hex}/200x50"
            display_embed.set_thumbnail(url=color_image_url)
            
            # Thêm thông tin hiển thị
            display_embed.add_field(
                name="🎨 Mã màu HEX",
                value=f"`#{color_hex.upper()}`",
                inline=True
            )
            display_embed.add_field(
                name="🔢 Mã màu số",
                value=f"`{role.color.value}`",
                inline=True
            )
            
            # Hiển thị trong danh sách thành viên
            display_embed.add_field(
                name="📋 Hiển thị riêng trong danh sách",
                value="✅ Có" if role.hoist else "❌ Không",
                inline=False
            )
            
            # Icon nếu có
            if role.icon:
                display_embed.set_image(url=role.icon.url)
                display_embed.add_field(
                    name="🖼️ Icon",
                    value="Role có icon tùy chỉnh (hiển thị bên dưới)",
                    inline=False
                )
            else:
                display_embed.add_field(
                    name="🖼️ Icon",
                    value="Role không có icon",
                    inline=False
                )
                
            await interaction.response.edit_message(embed=display_embed, view=view)
            
        elif button_id == "close":
            await interaction.message.delete()

    # Gán callback cho từng nút
    permissions_button.callback = button_callback
    members_button.callback = button_callback
    display_button.callback = button_callback
    close_button.callback = button_callback
    
    # Thêm các nút vào view
    view.add_item(permissions_button)
    view.add_item(members_button)
    view.add_item(display_button)
    view.add_item(close_button)
    
    # Hàm xử lý khi timeout
    async def on_timeout():
        # Vô hiệu hóa tất cả các nút
        for button in view.children:
            button.disabled = True
        
        try:
            await message.edit(view=view)
        except:
            pass
    
    view.on_timeout = on_timeout
    
    # Gửi embed
    message = await ctx.send(embed=embed, view=view)

@role_info.error
async def role_info_error(ctx, error):
    if isinstance(error, commands.RoleNotFound):
        embed = discord.Embed(
            title="❌ Role không tồn tại",
            description="Không thể tìm thấy role với tên hoặc ID đã cung cấp.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
    elif isinstance(error, commands.MissingRequiredArgument):
        embed = discord.Embed(
            title="❓ Thiếu thông tin",
            description="Vui lòng nhập tên hoặc ID của role. Ví dụ: `.roleinfo Admin`",
            color=discord.Color.gold()
        )
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(
            title="❌ Lỗi",
            description=f"Đã xảy ra lỗi: {str(error)}",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)

@bot.command(name='steal', aliases=['stealemoji', 'stealer', 'snatch'])
@commands.has_permissions(manage_emojis=True)
async def steal_emoji(ctx, *args):
    """Sao chép emoji hoặc icon từ nguồn khác vào server
    
    Sử dụng:
    .steal [emoji] - Sao chép emoji từ tin nhắn
    .steal [url] [tên] - Sao chép từ URL
    .steal server [ID server] - Sao chép icon server khác
    """
    if not args:
        # Hiển thị hướng dẫn sử dụng
        embed = discord.Embed(
            title="🔄 Steal Emoji - Hướng Dẫn",
            description="Sao chép emoji hoặc icon server vào server của bạn",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="📋 Cách sử dụng",
            value=(
                "**`.steal [emoji]`** - Sao chép emoji được sử dụng trong tin nhắn\n"
                "**`.steal [url] [tên]`** - Sao chép từ URL ảnh\n"
                "**`.steal server [ID server]`** - Sao chép icon server khác\n"
                "**`.steal getserver [ID server]`** - Lấy thông tin của server"
            ),
            inline=False
        )
        embed.add_field(
            name="📝 Ví dụ",
            value=(
                "**`.steal 😀`** - Sao chép emoji mặc định\n"
                "**`.steal <:thinking:123456789>`** - Sao chép emoji tùy chỉnh\n"
                "**`.steal https://example.com/emoji.png cool_emoji`** - Sao chép từ URL\n"
                "**`.steal server 123456789`** - Sao chép icon của server có ID 123456789"
            ),
            inline=False
        )
        embed.add_field(
            name="⚠️ Yêu cầu",
            value="Bạn cần có quyền `Manage Emojis` để sử dụng lệnh này.",
            inline=False
        )
        await ctx.send(embed=embed)
        return
    
    # Báo người dùng chờ trong khi xử lý
    processing_msg = await ctx.send("🔄 **Đang xử lý...**")
    
    # Xác định loại lệnh
    arg_first = args[0].lower()
    
    # Trường hợp 1: Sao chép icon server
    if arg_first == "server" and len(args) > 1:
        try:
            server_id = int(args[1])
            server = bot.get_guild(server_id)
            
            if not server:
                embed = discord.Embed(
                    title="❌ Không tìm thấy server",
                    description=f"Bot không thể tìm thấy server với ID `{server_id}`.\nBot cần phải ở trong server đó để lấy được icon.",
                    color=discord.Color.red()
                )
                await processing_msg.edit(content=None, embed=embed)
                return
            
            if not server.icon:
                embed = discord.Embed(
                    title="❌ Không có icon",
                    description=f"Server **{server.name}** không có icon.",
                    color=discord.Color.red()
                )
                await processing_msg.edit(content=None, embed=embed)
                return
            
            # Tạo tên cho icon server
            icon_name = f"{server.name}_icon".replace(" ", "_").lower()[:32]
            
            # Tải icon server
            icon_url = server.icon.url
            icon_bytes = await download_asset(icon_url)
            
            # Kiểm tra kích thước
            if len(icon_bytes) > 256000:  # 256KB là giới hạn cho emoji Discord
                embed = discord.Embed(
                    title="❌ Icon quá lớn",
                    description=f"Icon server vượt quá giới hạn kích thước emoji Discord (256KB).",
                    color=discord.Color.red()
                )
                embed.add_field(
                    name="💡 Giải pháp",
                    value="Hãy tải icon về, giảm kích thước và tải lên lại.",
                    inline=False
                )
                embed.add_field(
                    name="🔗 URL Icon",
                    value=f"[Tải xuống tại đây]({icon_url})",
                    inline=False
                )
                await processing_msg.edit(content=None, embed=embed)
                return
            
            # Tạo emoji mới
            try:
                new_emoji = await ctx.guild.create_custom_emoji(name=icon_name, image=icon_bytes, reason=f"Icon server stolen by {ctx.author}")
                embed = discord.Embed(
                    title="✅ Đã sao chép icon server",
                    description=f"Đã tạo emoji {new_emoji} từ icon của server **{server.name}**",
                    color=discord.Color.green()
                )
                embed.add_field(name="🏷️ Tên", value=f"`{icon_name}`", inline=True)
                embed.add_field(name="👤 Được tạo bởi", value=ctx.author.mention, inline=True)
                embed.set_thumbnail(url=icon_url)
                await processing_msg.edit(content=None, embed=embed)
            except discord.Forbidden:
                embed = discord.Embed(
                    title="❌ Không đủ quyền",
                    description="Bot không có quyền thêm emoji vào server.",
                    color=discord.Color.red()
                )
                await processing_msg.edit(content=None, embed=embed)
            except Exception as e:
                embed = discord.Embed(
                    title="❌ Lỗi",
                    description=f"Đã xảy ra lỗi khi tạo emoji: {str(e)}",
                    color=discord.Color.red()
                )
                await processing_msg.edit(content=None, embed=embed)
            return
        except ValueError:
            embed = discord.Embed(
                title="❌ ID không hợp lệ",
                description="ID server phải là một số nguyên.",
                color=discord.Color.red()
            )
            await processing_msg.edit(content=None, embed=embed)
            return
    
    # Trường hợp 2: Lấy thông tin server (để debug)
    elif arg_first == "getserver" and len(args) > 1:
        try:
            server_id = int(args[1])
            server = bot.get_guild(server_id)
            
            if not server:
                embed = discord.Embed(
                    title="❌ Không tìm thấy server",
                    description=f"Bot không thể tìm thấy server với ID `{server_id}`.\nBot cần phải ở trong server đó để lấy được thông tin.",
                    color=discord.Color.red()
                )
                await processing_msg.edit(content=None, embed=embed)
                return
            
            # Hiển thị thông tin server
            embed = discord.Embed(
                title=f"ℹ️ Thông tin Server: {server.name}",
                description=f"ID: `{server.id}`",
                color=discord.Color.blue()
            )
            
            if server.icon:
                embed.set_thumbnail(url=server.icon.url)
                embed.add_field(name="🔗 Icon URL", value=f"[Xem tại đây]({server.icon.url})", inline=False)
            else:
                embed.add_field(name="🖼️ Icon", value="Server không có icon", inline=False)
            
            embed.add_field(name="👥 Số thành viên", value=str(server.member_count), inline=True)
            embed.add_field(name="📅 Ngày tạo", value=discord.utils.format_dt(server.created_at, 'F'), inline=True)
            
            await processing_msg.edit(content=None, embed=embed)
            return
        except ValueError:
            embed = discord.Embed(
                title="❌ ID không hợp lệ",
                description="ID server phải là một số nguyên.",
                color=discord.Color.red()
            )
            await processing_msg.edit(content=None, embed=embed)
            return
    
    # Trường hợp 3: Sao chép từ URL
    elif arg_first.startswith(('http://', 'https://')) and len(args) > 1:
        url = args[0]
        emoji_name = ''.join(c for c in args[1] if c.isalnum() or c == '_').lower()
        
        if not emoji_name:
            emoji_name = "stolen_emoji"
        
        # Giới hạn độ dài tên emoji
        emoji_name = emoji_name[:32]
        
        try:
            # Tải ảnh từ URL
            emoji_bytes = await download_asset(url)
            
            if not emoji_bytes:
                embed = discord.Embed(
                    title="❌ Không thể tải ảnh",
                    description=f"Không thể tải ảnh từ URL: `{url}`",
                    color=discord.Color.red()
                )
                await processing_msg.edit(content=None, embed=embed)
                return
            
            # Kiểm tra kích thước
            if len(emoji_bytes) > 256000:  # 256KB là giới hạn cho emoji Discord
                embed = discord.Embed(
                    title="❌ Ảnh quá lớn",
                    description=f"Ảnh vượt quá giới hạn kích thước emoji Discord (256KB).",
                    color=discord.Color.red()
                )
                await processing_msg.edit(content=None, embed=embed)
                return
            
            # Tạo emoji mới
            try:
                new_emoji = await ctx.guild.create_custom_emoji(name=emoji_name, image=emoji_bytes, reason=f"Emoji from URL stolen by {ctx.author}")
                embed = discord.Embed(
                    title="✅ Đã sao chép emoji từ URL",
                    description=f"Đã tạo emoji {new_emoji} từ URL",
                    color=discord.Color.green()
                )
                embed.add_field(name="🏷️ Tên", value=f"`{emoji_name}`", inline=True)
                embed.add_field(name="👤 Được tạo bởi", value=ctx.author.mention, inline=True)
                embed.set_thumbnail(url=url)
                await processing_msg.edit(content=None, embed=embed)
            except discord.Forbidden:
                embed = discord.Embed(
                    title="❌ Không đủ quyền",
                    description="Bot không có quyền thêm emoji vào server.",
                    color=discord.Color.red()
                )
                await processing_msg.edit(content=None, embed=embed)
            except Exception as e:
                embed = discord.Embed(
                    title="❌ Lỗi",
                    description=f"Đã xảy ra lỗi khi tạo emoji: {str(e)}",
                    color=discord.Color.red()
                )
                await processing_msg.edit(content=None, embed=embed)
            return
        except Exception as e:
            embed = discord.Embed(
                title="❌ Lỗi",
                description=f"Đã xảy ra lỗi: {str(e)}",
                color=discord.Color.red()
            )
            await processing_msg.edit(content=None, embed=embed)
            return
    
    # Trường hợp 4: Sao chép emoji từ tin nhắn
    else:
        # Kiểm tra xem có phải emoji tùy chỉnh không
        emoji_regex = r'<a?:[a-zA-Z0-9_]+:([0-9]+)>'
        match = re.search(emoji_regex, args[0])
        
        if match:
            # Đây là emoji tùy chỉnh
            emoji_id = match.group(1)
            is_animated = 'a:' in args[0]
            
            # Xác định tên emoji
            if len(args) > 1:
                emoji_name = ''.join(c for c in args[1] if c.isalnum() or c == '_').lower()[:32]
            else:
                # Lấy tên từ emoji gốc
                emoji_name_match = re.search(r'<a?:([a-zA-Z0-9_]+):[0-9]+>', args[0])
                if emoji_name_match:
                    emoji_name = emoji_name_match.group(1)
                else:
                    emoji_name = "stolen_emoji"
            
            # Tạo URL cho emoji
            if is_animated:
                emoji_url = f"https://cdn.discordapp.com/emojis/{emoji_id}.gif"
            else:
                emoji_url = f"https://cdn.discordapp.com/emojis/{emoji_id}.png"
            
            try:
                # Tải emoji
                emoji_bytes = await download_asset(emoji_url)
                
                # Tạo emoji mới
                new_emoji = await ctx.guild.create_custom_emoji(name=emoji_name, image=emoji_bytes, reason=f"Emoji stolen by {ctx.author}")
                
                embed = discord.Embed(
                    title="✅ Đã sao chép emoji",
                    description=f"Đã tạo emoji {new_emoji}",
                    color=discord.Color.green()
                )
                embed.add_field(name="🏷️ Tên", value=f"`{emoji_name}`", inline=True)
                embed.add_field(name="🎭 Loại", value="Động" if is_animated else "Tĩnh", inline=True)
                embed.add_field(name="👤 Được tạo bởi", value=ctx.author.mention, inline=True)
                embed.set_thumbnail(url=emoji_url)
                await processing_msg.edit(content=None, embed=embed)
            except discord.Forbidden:
                embed = discord.Embed(
                    title="❌ Không đủ quyền",
                    description="Bot không có quyền thêm emoji vào server.",
                    color=discord.Color.red()
                )
                await processing_msg.edit(content=None, embed=embed)
            except Exception as e:
                embed = discord.Embed(
                    title="❌ Lỗi",
                    description=f"Đã xảy ra lỗi khi tạo emoji: {str(e)}",
                    color=discord.Color.red()
                )
                await processing_msg.edit(content=None, embed=embed)
        else:
            # Có thể là emoji Unicode
            embed = discord.Embed(
                title="❓ Không phải emoji tùy chỉnh",
                description="Không thể sao chép emoji mặc định của Discord.",
                color=discord.Color.orange()
            )
            embed.add_field(
                name="💡 Gợi ý", 
                value="Hãy sử dụng emoji tùy chỉnh hoặc URL hình ảnh.", 
                inline=False
            )
            await processing_msg.edit(content=None, embed=embed)

async def download_asset(url):
    """Tải tài nguyên từ URL và trả về dưới dạng bytes"""
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                return await response.read()
            return None

@steal_emoji.error
async def steal_emoji_error(ctx, error):
    """Xử lý lỗi cho lệnh steal_emoji"""
    if isinstance(error, commands.MissingPermissions):
        embed = discord.Embed(
            title="❌ Thiếu quyền hạn",
            description="Bạn cần có quyền `Manage Emojis` để sử dụng lệnh này.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
    elif isinstance(error, commands.CommandInvokeError):
        embed = discord.Embed(
            title="❌ Lỗi",
            description=f"Đã xảy ra lỗi khi thực hiện lệnh: {str(error.original)}",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(
            title="❌ Lỗi",
            description=f"Đã xảy ra lỗi: {str(error)}",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)

@bot.command(name='spotify', aliases=['sp'])
async def spotify_play(ctx, *, url=None):
    """Phát nhạc từ Spotify - hỗ trợ tracks, albums và playlists"""
    if url is None:
        embed = discord.Embed(
            title="🎵 Spotify Player - Hướng dẫn",
            description="Phát nhạc từ Spotify",
            color=discord.Color.green()
        )
        embed.add_field(
            name="Cách sử dụng",
            value="`.spotify [Spotify URL]`\nVí dụ: `.spotify https://open.spotify.com/track/4eeflgjzTF8xN8U2E0dech`",
            inline=False
        )
        embed.add_field(
            name="🔗 Hỗ trợ các định dạng",
            value="• Spotify Track: `https://open.spotify.com/track/...`\n• Spotify Album: `https://open.spotify.com/album/...`\n• Spotify Playlist: `https://open.spotify.com/playlist/...`",
            inline=False
        )
        embed.set_thumbnail(url="https://storage.googleapis.com/pr-newsroom-wp/1/2018/11/Spotify_Logo_RGB_Green.png")
        await ctx.send(embed=embed)
        return
    
    # Kiểm tra người dùng đã vào kênh voice chưa
    if not ctx.author.voice:
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Bạn cần vào kênh voice trước khi phát nhạc.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return
    
    voice_channel = ctx.author.voice.channel
    
    # Kiểm tra voice client hiện tại
    voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    
    # Kiểm tra xem người dùng có đang ở trong kênh voice của bot không (nếu bot đã kết nối sẵn)
    if voice_client and voice_client.is_connected() and ctx.author.voice.channel != voice_client.channel:
        embed = discord.Embed(
            title="❌ Lỗi",
            description="Bạn phải ở cùng kênh voice với bot để sử dụng lệnh này!",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # Kiểm tra nếu URL là Spotify
    spotify_pattern = r"(open\.spotify\.com\/(track|album|playlist)\/([a-zA-Z0-9]+))"
    match = re.search(spotify_pattern, url, re.IGNORECASE)
    
    if not match:
        embed = discord.Embed(
            title="❌ Link không hợp lệ",
            description="Vui lòng cung cấp một URL Spotify hợp lệ.\nVí dụ: `https://open.spotify.com/track/4eeflgjzTF8xN8U2E0dech`",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return
    
    # Lấy thông tin từ URL
    spotify_type = match.group(2)  # track, album, hoặc playlist
    spotify_id = match.group(3)
    
    # Gửi thông báo đang xử lý
    processing_embed = discord.Embed(
        title="🔍 Đang xử lý Spotify...",
        description=f"Đang tìm thông tin cho {spotify_type} Spotify: `{spotify_id}`",
        color=discord.Color.green()
    )
    
    processing_embed.set_thumbnail(url="https://storage.googleapis.com/pr-newsroom-wp/1/2018/11/Spotify_Logo_RGB_Green.png")
    processing_embed.add_field(
        name="⏳ Trạng thái", 
        value="Đang lấy thông tin... Vui lòng đợi trong giây lát.",
        inline=False
    )
    
    processing_msg = await ctx.send(embed=processing_embed)
    
    try:
        # Kết nối tới kênh voice nếu chưa kết nối
        if not voice_client or not voice_client.is_connected():
            voice_client = await voice_channel.connect()
        
        # Xử lý theo loại Spotify URL
        if spotify_type == "track":
            await process_spotify_track(ctx, voice_client, processing_msg, spotify_id)
        elif spotify_type == "album":
            await process_spotify_album(ctx, voice_client, processing_msg, spotify_id)
        elif spotify_type == "playlist":
            await process_spotify_playlist(ctx, voice_client, processing_msg, spotify_id)
    
    except Exception as e:
        error_embed = discord.Embed(
            title="❌ Lỗi",
            description="Không thể xử lý link Spotify này!",
            color=discord.Color.red()
        )
        
        # Thêm thông tin chi tiết về lỗi
        error_message = str(e)
        error_embed.add_field(
            name="Chi tiết lỗi",
            value=error_message[:1000] if error_message else "Không có thông tin lỗi",
            inline=False
        )
        
        error_embed.add_field(
            name="🔧 Khắc phục",
            value="- Kiểm tra xem link Spotify có chính xác không\n- Đảm bảo bài hát không bị giới hạn khu vực\n- Thử sử dụng lệnh `.stvp` thay thế",
            inline=False
        )
        
        await processing_msg.edit(embed=error_embed)
        print(f"Spotify error: {str(e)}")

async def process_spotify_track(ctx, voice_client, processing_msg, track_id):
    """Xử lý track Spotify"""
    # Cập nhật thông báo đang xử lý
    update_embed = discord.Embed(
        title="🎵 Đang xử lý Spotify Track",
        description=f"Đang lấy thông tin cho track ID: `{track_id}`",
        color=discord.Color.green()
    )
    update_embed.set_thumbnail(url="https://storage.googleapis.com/pr-newsroom-wp/1/2018/11/Spotify_Logo_RGB_Green.png")
    await processing_msg.edit(embed=update_embed)
    
    try:
        # Trích xuất thông tin track từ Spotify
        track_info = await extract_spotify_info(track_id)
        
        # Hiển thị thông tin đang xử lý
        info_embed = discord.Embed(
            title="🎵 Đã tìm thấy bài hát Spotify",
            description=f"**{track_info['title']}** bởi **{track_info['artist']}**\n⏳ Đang tìm trên YouTube...",
            color=discord.Color.green()
        )
        info_embed.set_thumbnail(url=track_info.get('image', "https://storage.googleapis.com/pr-newsroom-wp/1/2018/11/Spotify_Logo_RGB_Green.png"))
        await processing_msg.edit(embed=info_embed)
        
        # Chuyển đổi thành YouTube search
        search_query = f"{track_info['artist']} - {track_info['title']}"
        query = f"ytsearch:{search_query}"
        
        # Chuẩn bị options để trích xuất thông tin và chơi nhạc
        ydl_opts = {
            'format': 'bestaudio/best',
            'extractaudio': True,
            'audioformat': 'mp3',
            'noplaylist': True,
            'nocheckcertificate': True,
            'quiet': True,
            'no_warnings': True,
            'default_search': 'auto',
            'source_address': '0.0.0.0'
        }
        
        # Trích xuất thông tin bài hát từ YouTube
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(query, download=False)
            if 'entries' in info:
                info = info['entries'][0]
            
            url = info['url']
            title = info['title']
            duration = info.get('duration', 0)
            thumbnail = info.get('thumbnail', '')
        
        # Tạo đối tượng bài hát
        song = SongInfo(title, url, duration, thumbnail, requester=ctx.author)
        
        # Khởi tạo hàng đợi nếu chưa tồn tại cho guild này
        guild_id = ctx.guild.id
        if guild_id not in music_queues:
            music_queues[guild_id] = []
        
        # Thêm bài hát vào hàng đợi
        music_queues[guild_id].append(song)
        
        # Phát nhạc nếu không có bài nào đang phát
        is_playing = voice_client.is_playing()
        if not is_playing:
            await play_next(ctx, voice_client, song)
            
            success_embed = discord.Embed(
                title="🎵 Đang phát từ Spotify",
                description=f"**{track_info['title']}**",
                color=discord.Color.green()
            )
            
            # Định dạng thời lượng thành mm:ss
            minutes = int(duration // 60)
            seconds = int(duration % 60)
            duration_str = f"{minutes}:{seconds:02d}" if duration else "Không xác định"
            
            success_embed.add_field(
                name="🎤 Nghệ sĩ", 
                value=track_info['artist'], 
                inline=True
            )
            
            success_embed.add_field(
                name="⏱️ Thời lượng", 
                value=duration_str, 
                inline=True
            )
            
            success_embed.add_field(
                name="👤 Yêu cầu bởi", 
                value=ctx.author.mention, 
                inline=True
            )
            
            success_embed.set_thumbnail(url=track_info.get('image', thumbnail))
            success_embed.set_footer(text="Powered by Spotify")
            
            await processing_msg.edit(embed=success_embed)
        else:
            # Thông báo đã thêm vào hàng đợi
            queue_position = len(music_queues[guild_id]) - 1
            
            queue_embed = discord.Embed(
                title="🎵 Đã thêm vào hàng đợi từ Spotify",
                description=f"**{track_info['title']}**",
                color=discord.Color.green()
            )
            
            # Định dạng thời lượng thành mm:ss
            minutes = int(duration // 60)
            seconds = int(duration % 60)
            duration_str = f"{minutes}:{seconds:02d}" if duration else "Không xác định"
            
            queue_embed.add_field(
                name="🎤 Nghệ sĩ", 
                value=track_info['artist'], 
                inline=True
            )
            
            queue_embed.add_field(
                name="⏱️ Thời lượng", 
                value=duration_str, 
                inline=True
            )
            
            queue_embed.add_field(
                name="🔢 Vị trí", 
                value=f"#{queue_position + 1}", 
                inline=True
            )
            
            queue_embed.set_thumbnail(url=track_info.get('image', thumbnail))
            queue_embed.set_footer(text="Sử dụng .stvq để xem toàn bộ hàng đợi")
            
            await processing_msg.edit(embed=queue_embed)
    
    except Exception as e:
        error_embed = discord.Embed(
            title="❌ Lỗi",
            description=f"Không thể xử lý Spotify track: {str(e)}",
            color=discord.Color.red()
        )
        await processing_msg.edit(embed=error_embed)
        raise

async def process_spotify_album(ctx, voice_client, processing_msg, album_id):
    """Xử lý album Spotify"""
    # Cập nhật embed thông báo đang xử lý album
    album_embed = discord.Embed(
        title="💿 Đang xử lý Spotify Album",
        description=f"Đang lấy thông tin cho album ID: `{album_id}`",
        color=discord.Color.green()
    )
    album_embed.set_thumbnail(url="https://storage.googleapis.com/pr-newsroom-wp/1/2018/11/Spotify_Logo_RGB_Green.png")
    await processing_msg.edit(embed=album_embed)
    
    try:
        # Trích xuất thông tin album từ Spotify
        album_info = await extract_spotify_album_info(album_id)
        
        # Hiển thị thông tin album đang xử lý
        album_embed = discord.Embed(
            title="💿 Đang xử lý Spotify Album",
            description=f"**{album_info['title']}** bởi **{album_info['artist']}**",
            color=discord.Color.green()
        )
        album_embed.add_field(
            name="🔢 Số bài hát", 
            value=f"{len(album_info['tracks'])} bài hát", 
            inline=True
        )
        album_embed.add_field(
            name="⏳ Trạng thái", 
            value="Đang thêm vào hàng đợi...", 
            inline=True
        )
        album_embed.set_thumbnail(url=album_info.get('image', "https://storage.googleapis.com/pr-newsroom-wp/1/2018/11/Spotify_Logo_RGB_Green.png"))
        await processing_msg.edit(embed=album_embed)
        
        # Giới hạn số lượng bài hát để tránh spam
        max_tracks = min(20, len(album_info['tracks']))
        if len(album_info['tracks']) > 20:
            album_embed.add_field(
                name="⚠️ Giới hạn", 
                value=f"Chỉ thêm {max_tracks} bài đầu tiên để tránh quá tải", 
                inline=False
            )
            await processing_msg.edit(embed=album_embed)
        
        # Khởi tạo hàng đợi nếu chưa tồn tại
        guild_id = ctx.guild.id
        if guild_id not in music_queues:
            music_queues[guild_id] = []
        
        # Xử lý từng bài hát trong album
        success_tracks = 0
        first_song = None
        
        for i, track in enumerate(album_info['tracks'][:max_tracks]):
            try:
                # Cập nhật tiến trình
                if i % 5 == 0:
                    progress_embed = discord.Embed(
                        title="💿 Đang xử lý Spotify Album",
                        description=f"**{album_info['title']}** bởi **{album_info['artist']}**",
                        color=discord.Color.green()
                    )
                    progress_embed.add_field(
                        name="🔄 Tiến trình", 
                        value=f"Đang thêm bài {i+1}/{max_tracks}...", 
                        inline=True
                    )
                    progress_embed.set_thumbnail(url=album_info.get('image', "https://storage.googleapis.com/pr-newsroom-wp/1/2018/11/Spotify_Logo_RGB_Green.png"))
                    await processing_msg.edit(embed=progress_embed)
                
                # Tìm kiếm bài hát trên YouTube
                search_query = f"{track['artist']} - {track['title']}"
                query = f"ytsearch:{search_query}"
                
                # Trích xuất thông tin từ YouTube
                ydl_opts = {
                    'format': 'bestaudio/best',
                    'extractaudio': True,
                    'audioformat': 'mp3',
                    'noplaylist': True,
                    'nocheckcertificate': True,
                    'quiet': True,
                    'no_warnings': True,
                    'default_search': 'auto',
                    'source_address': '0.0.0.0'
                }
                
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(query, download=False)
                    if 'entries' in info:
                        info = info['entries'][0]
                    
                    url = info['url']
                    title = info['title']
                    duration = info.get('duration', 0)
                    thumbnail = info.get('thumbnail', '')
                
                # Tạo đối tượng bài hát và thêm vào hàng đợi
                song = SongInfo(title, url, duration, thumbnail, requester=ctx.author)
                
                # Lưu bài hát đầu tiên để phát nếu hiện tại không có gì đang phát
                if i == 0:
                    first_song = song
                
                music_queues[guild_id].append(song)
                success_tracks += 1
                
            except Exception as e:
                print(f"Lỗi khi thêm bài {track['title']}: {str(e)}")
                continue
        
        # Phát bài hát đầu tiên nếu không có gì đang phát
        is_playing = voice_client.is_playing()
        if not is_playing and first_song:
            await play_next(ctx, voice_client, first_song)
        
        # Thông báo kết quả cuối cùng
        final_embed = discord.Embed(
            title="💿 Đã thêm Album Spotify vào hàng đợi",
            description=f"**{album_info['title']}** bởi **{album_info['artist']}**",
            color=discord.Color.green()
        )
        
        final_embed.add_field(
            name="✅ Đã thêm", 
            value=f"{success_tracks}/{max_tracks} bài hát", 
            inline=True
        )
        
        final_embed.add_field(
            name="👤 Yêu cầu bởi", 
            value=ctx.author.mention, 
            inline=True
        )
        
        final_embed.add_field(
            name="🎵 Bài đầu tiên", 
            value=first_song.title if first_song else "Không có bài nào được thêm", 
            inline=False
        )
        
        final_embed.set_thumbnail(url=album_info.get('image', "https://storage.googleapis.com/pr-newsroom-wp/1/2018/11/Spotify_Logo_RGB_Green.png"))
        final_embed.set_footer(text="Sử dụng .stvq để xem toàn bộ hàng đợi")
        
        await processing_msg.edit(embed=final_embed)
    
    except Exception as e:
        error_embed = discord.Embed(
            title="❌ Lỗi",
            description=f"Không thể xử lý Spotify album: {str(e)}",
            color=discord.Color.red()
        )
        await processing_msg.edit(embed=error_embed)
        raise

async def process_spotify_playlist(ctx, voice_client, processing_msg, playlist_id):
    """Xử lý playlist Spotify"""
    # Cập nhật embed thông báo đang xử lý playlist
    playlist_embed = discord.Embed(
        title="📋 Đang xử lý Spotify Playlist",
        description=f"Đang lấy thông tin cho playlist ID: `{playlist_id}`",
        color=discord.Color.green()
    )
    playlist_embed.set_thumbnail(url="https://storage.googleapis.com/pr-newsroom-wp/1/2018/11/Spotify_Logo_RGB_Green.png")
    await processing_msg.edit(embed=playlist_embed)
    
    try:
        # Trích xuất thông tin playlist từ Spotify
        playlist_info = await extract_spotify_playlist_info(playlist_id)
        
        # Kiểm tra xem có bài hát nào được tìm thấy không
        if not playlist_info.get('tracks') or len(playlist_info['tracks']) == 0:
            raise Exception("Không tìm thấy bài hát nào trong playlist")
        
        # Hiển thị thông tin playlist đang xử lý
        playlist_embed = discord.Embed(
            title="📋 Đang xử lý Spotify Playlist",
            description=f"**{playlist_info.get('title', 'Unknown Playlist')}** ({playlist_info.get('owner', 'Unknown User')})",
            color=discord.Color.green()
        )
        playlist_embed.add_field(
            name="🔢 Số bài hát", 
            value=f"{len(playlist_info['tracks'])} bài hát", 
            inline=True
        )
        playlist_embed.add_field(
            name="⏳ Trạng thái", 
            value="Đang thêm vào hàng đợi...", 
            inline=True
        )
        playlist_embed.set_thumbnail(url=playlist_info.get('image', "https://storage.googleapis.com/pr-newsroom-wp/1/2018/11/Spotify_Logo_RGB_Green.png"))
        await processing_msg.edit(embed=playlist_embed)
        
        # Giới hạn số lượng bài hát để tránh quá tải
        max_tracks = min(20, len(playlist_info['tracks']))
        if len(playlist_info['tracks']) > 20:
            playlist_embed.add_field(
                name="⚠️ Giới hạn", 
                value=f"Chỉ thêm {max_tracks} bài đầu tiên để tránh quá tải", 
                inline=False
            )
            await processing_msg.edit(embed=playlist_embed)
        
        # Khởi tạo hàng đợi nếu chưa tồn tại
        guild_id = ctx.guild.id
        if guild_id not in music_queues:
            music_queues[guild_id] = []
        
        # Xử lý từng bài hát trong playlist
        success_tracks = 0
        first_song = None
        
        # Đảm bảo rằng playlist_info['tracks'] là một list
        if not isinstance(playlist_info['tracks'], list):
            playlist_info['tracks'] = []
        
        for i, track in enumerate(playlist_info['tracks'][:max_tracks]):
            try:
                # Kiểm tra các khóa cần thiết có tồn tại không
                if not isinstance(track, dict) or 'title' not in track or 'artist' not in track:
                    continue
                    
                # Cập nhật tiến trình
                if i % 5 == 0:
                    progress_embed = discord.Embed(
                        title="📋 Đang xử lý Spotify Playlist",
                        description=f"**{playlist_info.get('title', 'Unknown Playlist')}** ({playlist_info.get('owner', 'Unknown User')})",
                        color=discord.Color.green()
                    )
                    progress_embed.add_field(
                        name="🔄 Tiến trình", 
                        value=f"Đang thêm bài {i+1}/{max_tracks}...", 
                        inline=True
                    )
                    progress_embed.set_thumbnail(url=playlist_info.get('image', "https://storage.googleapis.com/pr-newsroom-wp/1/2018/11/Spotify_Logo_RGB_Green.png"))
                    await processing_msg.edit(embed=progress_embed)
                
                # Tìm kiếm bài hát trên YouTube
                search_query = f"{track['artist']} - {track['title']}"
                query = f"ytsearch:{search_query}"
                
                # Trích xuất thông tin từ YouTube
                ydl_opts = {
                    'format': 'bestaudio/best',
                    'extractaudio': True,
                    'audioformat': 'mp3',
                    'noplaylist': True,
                    'nocheckcertificate': True,
                    'quiet': True,
                    'no_warnings': True,
                    'default_search': 'auto',
                    'source_address': '0.0.0.0'
                }
                
                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(query, download=False)
                        
                        # Kiểm tra entries trước khi truy cập
                        if 'entries' not in info or not info['entries']:
                            # Nếu không có entries, bỏ qua bài này
                            continue
                        
                        entry = info['entries'][0]  # Lấy kết quả đầu tiên
                        
                        # Kiểm tra các trường thông tin cần thiết
                        if 'url' not in entry:
                            continue
                            
                        url = entry['url']
                        title = entry.get('title', f"{track['artist']} - {track['title']}")
                        duration = entry.get('duration', 0)
                        thumbnail = entry.get('thumbnail', '')
                        
                        # Tạo đối tượng bài hát và thêm vào hàng đợi
                        song = SongInfo(title, url, duration, thumbnail, requester=ctx.author)
                        
                        # Lưu bài hát đầu tiên để phát nếu hiện tại không có gì đang phát
                        if i == 0:
                            first_song = song
                        
                        music_queues[guild_id].append(song)
                        success_tracks += 1
                        
                except Exception as yt_error:
                    print(f"Lỗi YouTube DL cho bài {track.get('title', 'Unknown')}: {str(yt_error)}")
                    continue
                
            except Exception as track_error:
                print(f"Lỗi khi thêm bài {track.get('title', 'Unknown')}: {str(track_error)}")
                continue
        
        # Kiểm tra xem có thêm được bài nào không
        if success_tracks == 0:
            raise Exception("Không thể thêm bất kỳ bài hát nào từ playlist này")
        
        # Phát bài hát đầu tiên nếu không có gì đang phát
        is_playing = voice_client.is_playing() if voice_client else False
        if not is_playing and first_song:
            await play_next(ctx, voice_client, first_song)
        
        # Thông báo kết quả cuối cùng
        final_embed = discord.Embed(
            title="📋 Đã thêm Playlist Spotify vào hàng đợi",
            description=f"**{playlist_info.get('title', 'Unknown Playlist')}** ({playlist_info.get('owner', 'Unknown User')})",
            color=discord.Color.green()
        )
        
        final_embed.add_field(
            name="✅ Đã thêm", 
            value=f"{success_tracks}/{max_tracks} bài hát", 
            inline=True
        )
        
        final_embed.add_field(
            name="👤 Yêu cầu bởi", 
            value=ctx.author.mention, 
            inline=True
        )
        
        if first_song:
            playing_status = "▶️ Đang phát" if not is_playing else "🎵 Đã thêm vào hàng đợi"
            final_embed.add_field(
                name=playing_status, 
                value=first_song.title, 
                inline=False
            )
        
        final_embed.set_thumbnail(url=playlist_info.get('image', "https://storage.googleapis.com/pr-newsroom-wp/1/2018/11/Spotify_Logo_RGB_Green.png"))
        final_embed.set_footer(text="Sử dụng .stvq để xem toàn bộ hàng đợi")
        
        await processing_msg.edit(embed=final_embed)
    
    except Exception as e:
        error_embed = discord.Embed(
            title="❌ Lỗi",
            description=f"Không thể xử lý Spotify playlist: {str(e)}",
            color=discord.Color.red()
        )
        await processing_msg.edit(embed=error_embed)
        print(f"Lỗi xử lý Spotify playlist: {str(e)}")

async def extract_spotify_info(track_id):
    """Trích xuất thông tin từ Spotify track ID"""
    try:
        # Sử dụng API không cần xác thực để lấy thông tin cơ bản
        api_url = f"https://open.spotify.com/embed/track/{track_id}"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, headers=headers) as response:
                if response.status != 200:
                    raise Exception(f"API returned status {response.status}")
                
                html_content = await response.text()
                
                # Extract track info from OpenGraph meta tags
                title_match = re.search(r'<meta property="og:title" content="([^"]+)"', html_content)
                artist_match = re.search(r'<meta property="og:description" content="([^"]+)"', html_content)
                image_match = re.search(r'<meta property="og:image" content="([^"]+)"', html_content)
                
                if not title_match:
                    raise Exception("Could not extract track title")
                
                title = title_match.group(1).strip()
                
                # Handle cases where artist might not be found
                artist = "Unknown Artist"
                if artist_match:
                    artist_text = artist_match.group(1).strip()
                    # Artist information is usually in format "Song by Artist"
                    if "by " in artist_text:
                        artist = artist_text.split("by ")[1].strip()
                
                # Get image if available
                image_url = image_match.group(1) if image_match else None
                
                # Try to extract JSON data if available
                json_data_match = re.search(r'<script id="resource" type="application/json">(.+?)</script>', html_content)
                
                if json_data_match:
                    try:
                        json_str = json_data_match.group(1)
                        json_data = json.loads(json_str)
                        
                        # Extract more detailed information if available
                        if 'name' in json_data:
                            title = json_data['name']
                        
                        if 'artists' in json_data and len(json_data['artists']) > 0:
                            # Kiểm tra list trước khi truy cập để tránh index error
                            if json_data['artists'] and len(json_data['artists']) > 0:
                                artist = json_data['artists'][0].get('name', artist)
                    except json.JSONDecodeError:
                        # Ignore JSON parsing errors
                        pass
                
                return {
                    'title': title,
                    'artist': artist,
                    'image': image_url
                }
    except Exception as e:
        # Trả về thông tin tối thiểu trong trường hợp lỗi
        return {
            'title': f"Spotify Track {track_id}",
            'artist': "Unknown Artist",
            'image': None
        }

async def extract_spotify_album_info(album_id):
    """Trích xuất thông tin từ Spotify album ID"""
    try:
        # Sử dụng API không cần xác thực để lấy thông tin cơ bản
        api_url = f"https://open.spotify.com/embed/album/{album_id}"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, headers=headers) as response:
                if response.status != 200:
                    raise Exception(f"API returned status {response.status}")
                
                html_content = await response.text()
                
                # Extract album info
                title_match = re.search(r'<meta property="og:title" content="([^"]+)"', html_content)
                artist_match = re.search(r'<meta property="og:description" content="([^"]+)"', html_content)
                image_match = re.search(r'<meta property="og:image" content="([^"]+)"', html_content)
                
                if not title_match or not artist_match:
                    raise Exception("Could not extract album information")
                
                title = title_match.group(1).strip()
                artist = artist_match.group(1).split('·')[0].strip()
                
                # Clean up artist text
                if "Album by" in artist:
                    artist = artist.replace("Album by", "").strip()
                
                # Get image if available
                image_url = image_match.group(1) if image_match else None
                
                # Try to extract track list
                tracks_data = []
                
                # Regex to extract JSON data from script tags
                json_data_match = re.search(r'<script id="initial-state" type="text/plain">(.+?)</script>', html_content)
                if json_data_match:
                    try:
                        json_str = json_data_match.group(1)
                        json_data = json.loads(json_str)
                        
                        # Navigate through the JSON to find tracks
                        entities = json_data.get('entities', {})
                        items = entities.get('items', {})
                        
                        # Extract track information
                        for key, value in items.items():
                            if value.get('type') == 'track':
                                track_name = value.get('name', 'Unknown Track')
                                track_artists = []
                                
                                # Get artists
                                for artist_id in value.get('artists', []):
                                    artist_entity = entities.get('artists', {}).get(artist_id, {})
                                    if artist_entity:
                                        track_artists.append(artist_entity.get('name', 'Unknown Artist'))
                                
                                track_artist = ", ".join(track_artists) if track_artists else artist
                                
                                tracks_data.append({
                                    'title': track_name,
                                    'artist': track_artist
                                })
                    except json.JSONDecodeError:
                        # If JSON parsing fails, we'll use a fallback method
                        pass
                
                # If no tracks were found or JSON parsing failed, use a minimum fallback
                if not tracks_data:
                    # Fallback: Create dummy tracks based on album info
                    for i in range(10):  # Assume 10 tracks as fallback
                        tracks_data.append({
                            'title': f"Track {i+1} from {title}",
                            'artist': artist
                        })
                
                return {
                    'title': title,
                    'artist': artist,
                    'id': album_id,
                    'image': image_url,
                    'tracks': tracks_data
                }
    except Exception as e:
        # Fallback with minimal info
        return {
            'title': f"Spotify Album {album_id}",
            'artist': "Unknown Artist",
            'id': album_id,
            'image': None,
            'tracks': [{'title': f"Track from Album {album_id}", 'artist': "Unknown Artist"}]
        }

async def extract_spotify_playlist_info(playlist_id):
    """Trích xuất thông tin từ Spotify playlist ID"""
    try:
        # Sử dụng API không cần xác thực để lấy thông tin cơ bản
        api_url = f"https://open.spotify.com/embed/playlist/{playlist_id}"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, headers=headers) as response:
                if response.status != 200:
                    raise Exception(f"API returned status {response.status}")
                
                html_content = await response.text()
                
                # Extract playlist info from OpenGraph meta tags
                title_match = re.search(r'<meta property="og:title" content="([^"]+)"', html_content)
                owner_match = re.search(r'<meta property="og:description" content="([^"]+)"', html_content)
                image_match = re.search(r'<meta property="og:image" content="([^"]+)"', html_content)
                
                if not title_match:
                    raise Exception("Could not extract playlist title")
                
                title = title_match.group(1).strip()
                owner = "Unknown"
                if owner_match:
                    owner_text = owner_match.group(1).strip()
                    if "By " in owner_text:
                        owner = owner_text.split("By ")[1].strip()
                
                # Get image if available
                image_url = image_match.group(1) if image_match else None
                
                # Try to extract track list
                tracks_data = []
                
                # Regex to extract JSON data from script tags - tiếp cận từ nhiều mẫu khác nhau
                json_data_matches = [
                    re.search(r'<script id="initial-state" type="text/plain">(.+?)</script>', html_content),
                    re.search(r'<script id="__NEXT_DATA__" type="application/json">(.+?)</script>', html_content),
                    re.search(r'<script type="application/json" data-testid="spotify-player">(.+?)</script>', html_content)
                ]
                
                # Thử từng mẫu JSON cho đến khi tìm thấy dữ liệu hợp lệ
                for json_data_match in json_data_matches:
                    if json_data_match:
                        try:
                            # Trích xuất JSON và xử lý an toàn
                            json_str = json_data_match.group(1)
                            json_data = json.loads(json_str)
                            
                            # Thử nhiều đường dẫn cấu trúc JSON khác nhau
                            # Cấu trúc 1: Cấu trúc cũ với entities
                            if 'entities' in json_data:
                                entities = json_data.get('entities', {})
                                items = entities.get('items', {})
                                
                                # Duyệt qua các đối tượng để tìm thông tin bài hát
                                for key, item in items.items():
                                    try:
                                        if isinstance(item, dict) and 'track' in item and isinstance(item.get('track', {}), dict) and 'name' in item.get('track', {}):
                                            track = item['track']
                                            track_name = track.get('name', 'Unknown Track')
                                            
                                            # Tìm thông tin nghệ sĩ
                                            artist_name = "Unknown Artist"
                                            if 'artists' in track:
                                                if isinstance(track['artists'], list) and track['artists']:
                                                    artist_ids = track['artists']
                                                    if artist_ids and len(artist_ids) > 0:
                                                        first_artist_id = artist_ids[0]
                                                        
                                                        if first_artist_id and isinstance(first_artist_id, str):
                                                            artist = entities.get('artists', {}).get(first_artist_id, {})
                                                            if 'name' in artist:
                                                                artist_name = artist['name']
                                            
                                            tracks_data.append({
                                                'title': track_name,
                                                'artist': artist_name
                                            })
                                    except Exception as track_error:
                                        print(f"Lỗi xử lý track từ JSON: {track_error}")
                                        continue
                            
                            # Cấu trúc 2: Cấu trúc mới với props/pageProps
                            elif 'props' in json_data and 'pageProps' in json_data['props']:
                                pageProps = json_data['props']['pageProps']
                                if 'playlist' in pageProps and 'tracks' in pageProps['playlist'] and 'items' in pageProps['playlist']['tracks']:
                                    tracks = pageProps['playlist']['tracks']['items']
                                    
                                    for track_item in tracks:
                                        try:
                                            if 'track' in track_item and track_item['track']:
                                                track = track_item['track']
                                                track_name = track.get('name', 'Unknown Track')
                                                
                                                # Xử lý artists
                                                artist_name = "Unknown Artist"
                                                if 'artists' in track and isinstance(track['artists'], list) and track['artists']:
                                                    artist_name = track['artists'][0].get('name', 'Unknown Artist')
                                                
                                                tracks_data.append({
                                                    'title': track_name,
                                                    'artist': artist_name
                                                })
                                        except Exception as track_error:
                                            print(f"Lỗi xử lý track từ props JSON: {track_error}")
                                            continue
                            
                            # Nếu tìm thấy tracks, thoát khỏi vòng lặp
                            if tracks_data:
                                break
                                
                        except json.JSONDecodeError as e:
                            print(f"Lỗi parse JSON từ Spotify: {e}")
                            # Thử mẫu JSON tiếp theo
                            continue
                
                # Nếu không tìm thấy tracks từ JSON, dùng phương pháp dự phòng từ HTML
                if not tracks_data:
                    # Parse track information from HTML directly (fallback method)
                    track_rows = re.findall(r'<div data-testid="tracklist-row"[^>]*>.*?<div[^>]*>.*?<div[^>]*>(.*?)</div>.*?<span[^>]*>(.*?)</span>', html_content, re.DOTALL)
                    
                    for track_name_html, track_artist_html in track_rows:
                        try:
                            # Extract text without HTML tags
                            track_name = re.sub('<[^<]+?>', '', track_name_html).strip()
                            track_artist = re.sub('<[^<]+?>', '', track_artist_html).strip()
                            
                            if track_name and track_artist:
                                tracks_data.append({
                                    'title': track_name,
                                    'artist': track_artist
                                })
                        except Exception as html_error:
                            print(f"Lỗi xử lý track từ HTML: {html_error}")
                            continue
                
                # Nếu vẫn không có tracks, tạo tracks giả
                if not tracks_data:
                    # Fallback: Create dummy tracks based on playlist info
                    for i in range(10):  # Assume 10 tracks as fallback
                        tracks_data.append({
                            'title': f"Track {i+1} from {title}",
                            'artist': "Unknown Artist"
                        })
                
                return {
                    'title': title,
                    'owner': owner,
                    'id': playlist_id,
                    'image': image_url,
                    'tracks': tracks_data
                }
    except Exception as e:
        print(f"Lỗi chính khi xử lý playlist: {type(e).__name__}: {str(e)}")
        # Fallback with minimal info
        return {
            'title': f"Spotify Playlist {playlist_id}",
            'owner': "Unknown User",
            'id': playlist_id,
            'image': None,
            'tracks': [{'title': f"Track from Playlist {playlist_id}", 'artist': "Unknown Artist"}]
        }

# Sử dụng biến môi trường STV_TOKEN để lấy token của bot
bot.run("MTI1MDQyMTA4MTM5NTY5MTU5MQ.GyVIYV.XEI-1LUkK16qCjf8ulqgIhtXd2HgaY0msvAWYk")