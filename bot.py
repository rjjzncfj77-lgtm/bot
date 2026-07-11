import os
import asyncio
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from collections import defaultdict
import discord
from discord.ext import commands, tasks
from openai import AsyncOpenAI

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]

openai_client = AsyncOpenAI(
    api_key=GROQ_API_KEY,
    base_url="https://api.groq.com/openai/v1"
)

OWNER_NAME = "mt4mod"

bot_modes: dict[int, str] = defaultdict(lambda: "normal")

SYSTEM_PROMPT = """You are MT4 Junior, a Discord bot. Funny,tuff,sigma,ragebaiter sometimes,Chill but doesnt say that

Rules:
- say "lil bro" sometimes but not every sentence
- short answers almost all the time only when people need help iit ccan be like 20 sentences
- lowercase always
- funny, troll,smart,vr modder
- can talk about coding, games, mods, discord,modding vr games, random stuff naturally but dont talk about that all the time
- roasting sometimes 
- doesnt talk about coding or mods or games all the time and talk about anything
- never act formal or corporate
- NEVER use @everyone or @here never 
- never wrap responses in quotes
- never say the n word or any slurs
- use emojis like this "😭(crying is like laughing)😂🤣😎💀🙏"
- dont talk about vibes or chaotic or chaos act normal and human and cool
- dont use emojis all the time
- be like a boy ACT like one
- be like the style examples
- be tuff and cool and be like the tiktok people 

Style examples:
- "nah lil bro that setup is cooked 😭"
- "lil bro thinks hes tuff but hes not"
- "bro coded that with hopes and prayers 💀"
- "lowkey tuff i think"
- "HOLY AURA you just farmed so much aura bro"
- "yea sure bro😭🙏you cannot do that"
- "fr bro"
- "Very tuff "
- "LMAO🤣"
- "you got mogged bro 😭 "
- "that game prob has anti cheats bro good luck 😭"
- "how tf did you even do that bro 😭"
- "who are you bro"

"""

MAX_HISTORY = 6



MODE_PROMPTS = {
    "normal": SYSTEM_PROMPT,
    "helpful": "You are MT4 Junior but more helpful, smarter, cleaner explanations, still casual and funny.",
    "codemode": "You are MT4 Junior in coder mode. You love coding, mods, debugging, scripts,  and tech humor.Smart can send long messages",
    "roastmode": "find a way to roast people like name pfp what they say."
}

# Per-channel conversation history
conversation_history: dict[int, list[dict]] = defaultdict(list)

# Channels where bot talks freely (set by !on)
enabled_channels: set[int] = set()

# Channels explicitly stopped by !stop (overrides chat-name auto-detection)
stopped_channels: set[int] = set()

# Warn log per guild: {guild_id: {user_id: [reasons]}}
warn_log: dict[int, dict[int, list[str]]] = defaultdict(lambda: defaultdict(list))

# Usernames that get 🧃 reacted on every message
juice_box_users: set[str] = set()

# Active giveaways per channel: {channel_id: message_id}
active_giveaways: dict[int, int] = {}

# Aura scores per guild per user: {guild_id: {user_id: score}}
aura_scores: dict[int, dict[int, int]] = defaultdict(dict)

intents = discord.Intents.default()
intents.message_content = True
intents.messages = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)


# ── Keep-alive HTTP server for 24/7 uptime monitoring ──────────────────────

class KeepAliveHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"CodeBuddy is alive!")

    def log_message(self, format, *args):
        pass  # Suppress default HTTP logs


def run_keepalive():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), KeepAliveHandler)
    server.serve_forever()


# ── Helpers ─────────────────────────────────────────────────────────────────

def is_owner(ctx: commands.Context) -> bool:
    """Check if the user is the designated owner or the guild owner."""
    if ctx.author.name.lower() == OWNER_NAME:
        return True
    if ctx.guild and ctx.guild.owner_id == ctx.author.id:
        return True
    return False


def sanitize(text: str) -> str:
    text = text.replace("@everyone", "@\u200beveryone")
    text = text.replace("@here", "@\u200bhere")
    text = text.strip().strip('"').strip("'").strip()
    return text


def clean_mention(text: str) -> str:
    mention = f"<@{bot.user.id}>"
    mention_nick = f"<@!{bot.user.id}>"
    return text.replace(mention, "").replace(mention_nick, "").strip()


async def ai_reply(channel_id: int, username: str, user_text: str, system: str = None) -> str:
    history = conversation_history[channel_id]
    history.append({"role": "user", "content": f"{username}: {user_text}"})
    if len(history) > MAX_HISTORY:
        conversation_history[channel_id] = history[-MAX_HISTORY:]
        history = conversation_history[channel_id]

    reply = None
    for attempt in range(4):
        try:
            response = await openai_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                max_tokens=256,
                messages=[
                    {"role": "system", "content": system or MODE_PROMPTS.get(bot_modes[channel_id], SYSTEM_PROMPT)},
                    *history,
                ],
            )
            reply = response.choices[0].message.content or "idk lil bro 😭"
            break
        except Exception as e:
            err = str(e)
            print(f"AI error (attempt {attempt + 1}): {err}")
            if "rate_limit" in err or "429" in err:
                wait = (attempt + 1) * 5
                print(f"Rate limited, waiting {wait}s...")
                await asyncio.sleep(wait)
            else:
                break

    if reply is None:
        return None

    reply = sanitize(reply)
    history.append({"role": "assistant", "content": reply})
    return reply


async def send_long(destination, text: str):
    """Send a message, splitting if it exceeds Discord's 2000 char limit."""
    if len(text) <= 2000:
        await destination.send(text)
    else:
        for chunk in [text[i:i+1990] for i in range(0, len(text), 1990)]:
            await destination.send(chunk)


# ── Events ───────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    print(f"✅ MT4 Junior online as {bot.user} (ID: {bot.user.id})")
    print(f"   Servers: {len(bot.guilds)}")
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.playing,
            name="in the server 💻 | !help"
        )
    )


@bot.event
async def on_message(message: discord.Message):
    # Always process commands first
    await bot.process_commands(message)

    if message.author.bot:
        return

    # 🧃 React to juice box users on every message
    if message.author.name.lower() in juice_box_users:
        try:
            await message.add_reaction("🧃")
        except Exception:
            pass

    # Don't double-handle command messages
    if message.content.startswith("!"):
        return

    is_dm = isinstance(message.channel, discord.DMChannel)
    bot_mentioned = bot.user in message.mentions
    channel_name = getattr(message.channel, "name", "")
    is_chat_channel = "chat" in channel_name.lower()
    is_enabled = message.channel.id in enabled_channels
    is_stopped = message.channel.id in stopped_channels

    # Free-chat mode: chat-named channels OR !on channels, UNLESS !stop was used
    free_chat = (is_chat_channel or is_enabled) and not is_stopped

    # Respond if: mentioned anywhere, in a DM, or in free-chat mode
    if not bot_mentioned and not is_dm and not free_chat:
        return

    user_text = clean_mention(message.content) if bot_mentioned else message.content
    if not user_text.strip():
        return

    async with message.channel.typing():
        reply = await ai_reply(message.channel.id, message.author.display_name, user_text)

    if not reply:
        return

    # In free-chat mode (no explicit mention): send plainly, no ping
    if free_chat and not bot_mentioned:
        await send_long(message.channel, reply)
    else:
        if len(reply) <= 2000:
            await message.reply(reply, mention_author=False)
        else:
            await send_long(message.channel, reply)


# ── Toggle Commands ───────────────────────────────────────────────────────────

@bot.command(name="on")
async def enable_channel(ctx: commands.Context):
    """Enable free chat mode in this channel (owner only)."""
    if not is_owner(ctx):
        await ctx.send("❌ Only the server owner can use this.")
        return
    enabled_channels.add(ctx.channel.id)
    stopped_channels.discard(ctx.channel.id)
    await ctx.send(f"✅ I'm now active in **#{ctx.channel.name}** — talking freely, no pings!")


@bot.command(name="stop")
async def disable_channel(ctx: commands.Context):
    """Disable free chat mode in this channel (owner only)."""
    if not is_owner(ctx):
        await ctx.send("❌ Only the server owner can use this.")
        return
    enabled_channels.discard(ctx.channel.id)
    stopped_channels.add(ctx.channel.id)
    await ctx.send(f"🔇 Stopped in **#{ctx.channel.name}** — I'll only respond when mentioned now.")


# ── Moderation Commands (owner only) ─────────────────────────────────────────

@bot.command(name="ban")
async def ban_user(ctx: commands.Context, member: discord.Member = None, *, reason: str = "No reason provided"):
    if not is_owner(ctx):
        await ctx.send("❌ Only the server owner can use this.")
        return
    if not member:
        await ctx.send("Usage: `!ban @user [reason]`")
        return
    await member.ban(reason=reason)
    await ctx.send(f"🔨 **{member.display_name}** has been banned. Reason: {reason}")


@bot.command(name="kick")
async def kick_user(ctx: commands.Context, member: discord.Member = None, *, reason: str = "No reason provided"):
    if not is_owner(ctx):
        await ctx.send("❌ Only the server owner can use this.")
        return
    if not member:
        await ctx.send("Usage: `!kick @user [reason]`")
        return
    await member.kick(reason=reason)
    await ctx.send(f"👢 **{member.display_name}** has been kicked. Reason: {reason}")


@bot.command(name="timeout")
async def timeout_user(ctx: commands.Context, member: discord.Member = None, minutes: int = 10, *, reason: str = "No reason provided"):
    if not is_owner(ctx):
        await ctx.send("❌ Only the server owner can use this.")
        return
    if not member:
        await ctx.send("Usage: `!timeout @user [minutes] [reason]`")
        return
    import datetime
    duration = datetime.timedelta(minutes=minutes)
    await member.timeout(duration, reason=reason)
    await ctx.send(f"⏱️ **{member.display_name}** timed out for {minutes} minute(s). Reason: {reason}")


@bot.command(name="untimeout")
async def untimeout_user(ctx: commands.Context, member: discord.Member = None):
    if not is_owner(ctx):
        await ctx.send("❌ Only the server owner can use this.")
        return
    if not member:
        await ctx.send("Usage: `!untimeout @user`")
        return
    await member.timeout(None)
    await ctx.send(f"✅ **{member.display_name}**'s timeout has been removed.")


@bot.command(name="warn")
async def warn_user(ctx: commands.Context, member: discord.Member = None, *, reason: str = "No reason provided"):
    if not is_owner(ctx):
        await ctx.send("❌ Only the server owner can use this.")
        return
    if not member:
        await ctx.send("Usage: `!warn @user [reason]`")
        return
    guild_id = ctx.guild.id
    warn_log[guild_id][member.id].append(reason)
    count = len(warn_log[guild_id][member.id])
    await ctx.send(f"⚠️ **{member.display_name}** warned (total warns: {count}). Reason: {reason}")
    try:
        await member.send(f"⚠️ You have been warned in **{ctx.guild.name}**.\nReason: {reason}\nTotal warns: {count}")
    except discord.Forbidden:
        pass


@bot.command(name="warns")
async def check_warns(ctx: commands.Context, member: discord.Member = None):
    if not is_owner(ctx):
        await ctx.send("❌ Only the server owner can use this.")
        return
    if not member:
        await ctx.send("Usage: `!warns @user`")
        return
    guild_id = ctx.guild.id
    user_warns = warn_log[guild_id][member.id]
    if not user_warns:
        await ctx.send(f"✅ **{member.display_name}** has no warnings.")
    else:
        warn_list = "\n".join(f"{i+1}. {r}" for i, r in enumerate(user_warns))
        await ctx.send(f"⚠️ **{member.display_name}** has {len(user_warns)} warning(s):\n{warn_list}")


@bot.command(name="clearwarns")
async def clear_warns(ctx: commands.Context, member: discord.Member = None):
    if not is_owner(ctx):
        await ctx.send("❌ Only the server owner can use this.")
        return
    if not member:
        await ctx.send("Usage: `!clearwarns @user`")
        return
    warn_log[ctx.guild.id][member.id] = []
    await ctx.send(f"✅ Cleared all warnings for **{member.display_name}**.")


@bot.command(name="clear")
async def clear_messages(ctx: commands.Context, amount: int = 10):
    if not is_owner(ctx):
        await ctx.send("❌ Only the server owner can use this.")
        return
    deleted = await ctx.channel.purge(limit=amount + 1)
    msg = await ctx.send(f"🧹 Deleted {len(deleted) - 1} message(s).")
    await asyncio.sleep(3)
    await msg.delete()


@bot.command(name="slowmode")
async def set_slowmode(ctx: commands.Context, seconds: int = 0):
    if not is_owner(ctx):
        await ctx.send("❌ Only the server owner can use this.")
        return
    await ctx.channel.edit(slowmode_delay=seconds)
    if seconds == 0:
        await ctx.send("✅ Slowmode disabled.")
    else:
        await ctx.send(f"🐢 Slowmode set to {seconds} second(s).")


@bot.command(name="lock")
async def lock_channel(ctx: commands.Context):
    if not is_owner(ctx):
        await ctx.send("❌ Only the server owner can use this.")
        return
    overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
    overwrite.send_messages = False
    await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
    await ctx.send("🔒 Channel locked.")


@bot.command(name="unlock")
async def unlock_channel(ctx: commands.Context):
    if not is_owner(ctx):
        await ctx.send("❌ Only the server owner can use this.")
        return
    overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
    overwrite.send_messages = True
    await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
    await ctx.send("🔓 Channel unlocked.")


# ── Special User Commands ─────────────────────────────────────────────────────

@bot.command(name="a6")
async def toggle_juice_box(ctx: commands.Context):
    """Toggle 🧃 reaction on every message from a6waagoobeef (owner only)."""
    if not is_owner(ctx):
        await ctx.send("❌ Only the server owner can use this.")
        return
    target = "a6waagoobeef"
    if target in juice_box_users:
        juice_box_users.discard(target)
        await ctx.send(f"🧃 Removed juice box mode for **{target}**.")
    else:
        juice_box_users.add(target)
        await ctx.send(f"🧃 Every message from **{target}** will now get a juice box reaction.")


# ── Giveaway ──────────────────────────────────────────────────────────────────

@bot.command(name="giveaway")
async def start_giveaway(ctx: commands.Context, seconds: int = 60, *, prize: str = "a mystery prize"):
    """Start a giveaway. Usage: !giveaway [seconds] [prize]"""
    if not is_owner(ctx):
        await ctx.send("❌ Only the server owner can use this.")
        return
    if ctx.channel.id in active_giveaways:
        await ctx.send("❌ There's already a giveaway running in this channel.")
        return

    embed = discord.Embed(
        title="🎉 GIVEAWAY 🎉",
        description=f"**Prize:** {prize}\n\nReact with 🎉 to enter!\n\nEnds in **{seconds}** second(s).",
        color=discord.Color.gold()
    )
    embed.set_footer(text=f"Hosted by {ctx.author.display_name}")
    msg = await ctx.send(embed=embed)
    await msg.add_reaction("🎉")
    active_giveaways[ctx.channel.id] = msg.id

    await asyncio.sleep(seconds)

    active_giveaways.pop(ctx.channel.id, None)

    try:
        msg = await ctx.channel.fetch_message(msg.id)
    except Exception:
        return

    reaction = discord.utils.get(msg.reactions, emoji="🎉")
    if not reaction:
        await ctx.send("Nobody entered the giveaway 😭")
        return

    users = [u async for u in reaction.users() if not u.bot]
    if not users:
        await ctx.send("Nobody entered the giveaway lil bro 😭")
        return

    import random
    winner = random.choice(users)
    await ctx.send(
        f"🎉 Giveaway over! The winner of **{prize}** is {winner.mention}! Congrats lil bro 🔥"
    )


@bot.command(name="endgiveaway")
async def end_giveaway(ctx: commands.Context):
    """End a giveaway early (owner only)."""
    if not is_owner(ctx):
        await ctx.send("❌ Only the server owner can use this.")
        return
    if ctx.channel.id not in active_giveaways:
        await ctx.send("No active giveaway in this channel lil bro.")
        return
    active_giveaways.pop(ctx.channel.id, None)
    await ctx.send("Giveaway ended early.")


# ── Fun / AI Commands ─────────────────────────────────────────────────────────

@bot.command(name="aura")
async def aura(ctx: commands.Context):
    """Check your aura score."""
    import random
    score = random.randint(-999, 9999)
    guild_id = ctx.guild.id if ctx.guild else 0
    aura_scores[guild_id][ctx.author.id] = score

    if score < 0:
        verdict = f"bro has **{score}** aura 💀 negative aura lil bro that's crazy"
    elif score < 1000:
        verdict = f"lil bro got **{score}** aura 😭 that's mid at best"
    elif score < 4000:
        verdict = f"you sitting at **{score}** aura, not bad lil bro ✌️"
    elif score < 7000:
        verdict = f"**{score}** aura?? you lowkey got it fr 😎"
    else:
        verdict = f"**{score}** AURA?? lil bro is built different 😤 that's crazy"

    await ctx.send(f"{ctx.author.mention} {verdict}")


@bot.command(name="auracount")
async def auracount(ctx: commands.Context, member: discord.Member = None):
    """Check someone's stored aura score."""
    target = member or ctx.author
    guild_id = ctx.guild.id if ctx.guild else 0
    score = aura_scores[guild_id].get(target.id)

    if score is None:
        await ctx.send(f"**{target.display_name}** hasn't checked their aura yet lil bro — tell them to do `!aura`")
        return

    if score < 0:
        verdict = f"negative aura lil bro 💀 ({score})"
    elif score < 1000:
        verdict = f"mid aura ({score}) 😭"
    elif score < 4000:
        verdict = f"decent aura ({score}) ✌️"
    elif score < 7000:
        verdict = f"solid aura ({score}) 😎"
    else:
        verdict = f"CRAZY aura ({score}) 😤"

    await ctx.send(f"**{target.display_name}**'s aura: {verdict}")


@bot.command(name="braincells")
async def braincells(ctx: commands.Context):
    """Check how many braincells you have left."""
    import random
    count = random.randint(0, 100)

    if count == 0:
        msg = f"**0 braincells** lil bro 💀"
    elif count <= 2:
        msg = f"only **{count} braincell(s)** left 😭 and they fighting each other"
    elif count <= 10:
        msg = f"**{count} braincells** lil bro 💀 how are you even typing rn"
    elif count <= 30:
        msg = f"**{count} braincells** — not the worst but lil bro is struggling 😭"
    elif count <= 60:
        msg = f"**{count} braincells** — mid honestly, you get by 😤"
    elif count <= 85:
        msg = f"**{count} braincells** — lil bro is actually decent ngl ✌️"
    else:
        msg = f"**{count} braincells** 😎 lil bro might actually be built different"

    await ctx.send(f"{ctx.author.mention} has {msg}")


@bot.command(name="glaze")
async def glaze(ctx: commands.Context, member: discord.Member = None):
    """MT4 glazes someone hard."""
    target = member or ctx.author
    async with ctx.typing():
        reply = await ai_reply(
            ctx.channel.id,
            ctx.author.display_name,
            f"Glaze {target.display_name} extremely hard. Over the top compliments, act like they're the greatest person alive. Be dramatic and funny about it.",
            system="You are hyping someone up to an extreme, almost ridiculous degree. Lay it on thick — call them a legend, a god, unmatched. Keep it funny and over the top. 2-3 sentences max."
        )
    await ctx.send(f"🫧 {target.mention} {reply}")


@bot.command(name="remind")
async def remind(ctx: commands.Context, minutes: int = None, *, text: str = None):
    """Remind you of something. Usage: !remind [minutes] [message]"""
    if minutes is None or text is None:
        await ctx.send("Usage: `!remind [minutes] [message]`\nExample: `!remind 10 drink water lil bro`")
        return
    if minutes < 1 or minutes > 1440:
        await ctx.send("lil bro pick a time between 1 and 1440 minutes (24 hrs) 😭")
        return

    await ctx.send(f"✅ got it lil bro — i'll ping you in **{minutes}** minute(s) about: *{text}*")
    await asyncio.sleep(minutes * 60)
    await ctx.send(f"⏰ {ctx.author.mention} lil bro don't forget: **{text}**")


@bot.command(name="roast")
async def roast(ctx: commands.Context, member: discord.Member = None):
    """AI generates a fun, friendly roast."""
    target = member.display_name if member else ctx.author.display_name
    async with ctx.typing():
        reply = await ai_reply(
            ctx.channel.id,
            ctx.author.display_name,
            f"Give me a short, funny, and light-hearted roast for someone named {target}. Keep it playful and not actually mean.",
            system="You are a witty comedian. Write a short, funny, friendly roast. Max 2-3 sentences. Never be actually cruel."
        )
    await ctx.send(f"🔥 {reply}")


@bot.command(name="codejoke")
async def codejoke(ctx: commands.Context):
    """AI tells a coding joke."""
    async with ctx.typing():
        reply = await ai_reply(
            ctx.channel.id,
            ctx.author.display_name,
            "Tell me a funny coding or programmer joke.",
            system="You are a comedian who loves programming humor. Tell one short, genuinely funny coding joke."
        )
    await ctx.send(reply)


@bot.command(name="joke")
async def joke(ctx: commands.Context):
    """AI tells a random funny joke."""
    async with ctx.typing():
        reply = await ai_reply(
            ctx.channel.id,
            ctx.author.display_name,
            "Tell me a short, genuinely funny joke. anything goes — absurd, dark humor, wordplay, whatever.",
            system="You are a comedian. Tell one short, actually funny joke. No dad jokes unless they're really good."
        )
    await ctx.send(reply)


@bot.command(name="explain")
async def explain(ctx: commands.Context, *, concept: str = None):
    """AI explains a coding concept simply."""
    if not concept:
        await ctx.send("Usage: `!explain <concept>` e.g. `!explain recursion`")
        return
    async with ctx.typing():
        reply = await ai_reply(
            ctx.channel.id,
            ctx.author.display_name,
            f"Explain '{concept}' simply and clearly. Use a short analogy if helpful.",
            system="You are a patient coding teacher. Explain concepts simply with a short analogy. Keep it brief."
        )
    await ctx.send(reply)


@bot.command(name="translate")
async def translate_code(ctx: commands.Context, lang: str = None, *, code: str = None):
    """Translate code to another language."""
    if not lang or not code:
        await ctx.send("Usage: `!translate <language> <code>`\nExample: `!translate Python def add(a,b): return a+b`")
        return
    async with ctx.typing():
        reply = await ai_reply(
            ctx.channel.id,
            ctx.author.display_name,
            f"Translate this code to {lang}:\n```\n{code}\n```",
            system="You are an expert programmer. Translate code to the requested language. Always use a code block in your response."
        )
    await ctx.send(reply)


@bot.command(name="serverinfo")
async def server_info(ctx: commands.Context):
    """Show server info."""
    g = ctx.guild
    embed = discord.Embed(title=g.name, color=discord.Color.blue())
    embed.add_field(name="Members", value=g.member_count)
    embed.add_field(name="Channels", value=len(g.channels))
    embed.add_field(name="Roles", value=len(g.roles))
    embed.add_field(name="Owner", value=str(g.owner))
    if g.icon:
        embed.set_thumbnail(url=g.icon.url)
    await ctx.send(embed=embed)


@bot.command(name="userinfo")
async def user_info(ctx: commands.Context, member: discord.Member = None):
    """Show info about a user."""
    member = member or ctx.author
    embed = discord.Embed(title=str(member), color=member.color)
    embed.add_field(name="Display Name", value=member.display_name)
    embed.add_field(name="Joined Server", value=member.joined_at.strftime("%Y-%m-%d") if member.joined_at else "Unknown")
    embed.add_field(name="Account Created", value=member.created_at.strftime("%Y-%m-%d"))
    embed.add_field(name="Roles", value=", ".join(r.name for r in member.roles[1:]) or "None")
    embed.set_thumbnail(url=member.display_avatar.url)
    await ctx.send(embed=embed)


@bot.command(name="poll")
async def poll(ctx: commands.Context, *, question: str = None):
    """Create a quick yes/no poll."""
    if not question:
        await ctx.send("Usage: `!poll <question>`")
        return
    embed = discord.Embed(title="📊 Poll", description=question, color=discord.Color.green())
    embed.set_footer(text=f"Asked by {ctx.author.display_name}")
    msg = await ctx.send(embed=embed)
    await msg.add_reaction("✅")
    await msg.add_reaction("❌")




@bot.command(name="restart")
async def restart_bot(ctx: commands.Context):
    """Restart the bot without deleting memory."""
    if not is_owner(ctx):
        await ctx.send("❌ owner only lil bro")
        return

    await ctx.send("♻️ restarting lil bro...")
    await bot.close()


@bot.command(name="helpful")
async def helpful_mode(ctx: commands.Context):
    bot_modes[ctx.channel.id] = "helpful"
    await ctx.send("🧠 helpful mode enabled lil bro")


@bot.command(name="normal")
async def normal_mode(ctx: commands.Context):
    bot_modes[ctx.channel.id] = "normal"
    await ctx.send("😎 back to normal mode lil bro")


@bot.command(name="codemode")
async def code_mode(ctx: commands.Context):
    bot_modes[ctx.channel.id] = "codemode"
    await ctx.send("💻 coder mode activated lil bro")


@bot.command(name="roastmode")
async def roast_mode(ctx: commands.Context):
    bot_modes[ctx.channel.id] = "roastmode"
    await ctx.send("🔥 roast mode activated lil bro")


@bot.command(name="rate")
async def rate_user(ctx: commands.Context, member: discord.Member = None):
    import random
    target = member or ctx.author
    score = random.randint(0, 100)
    await ctx.send(f"📊 {target.display_name} is {score}% cooked lil bro 😭")


@bot.command(name="ship")
async def ship_users(ctx: commands.Context, member1: discord.Member = None, member2: discord.Member = None):
    import random
    if not member1 or not member2:
        await ctx.send("usage: !ship @user1 @user2")
        return
    score = random.randint(0, 100)
    await ctx.send(f"💘 {member1.display_name} + {member2.display_name} = {score}% compatibility 😭")


@bot.command(name="fight")
async def fight_users(ctx: commands.Context, member: discord.Member = None):
    import random
    target = member or ctx.author
    winner = random.choice([ctx.author.display_name, target.display_name])
    await ctx.send(f"🥊 {ctx.author.display_name} fought {target.display_name} and **{winner}** won 💀")


@bot.command(name="daily")
async def daily(ctx: commands.Context):
    import random
    amount = random.randint(1, 1000)
    await ctx.send(f"💰 lil bro claimed {amount} fake coins for today 😤")


@bot.command(name="help")
async def help_command(ctx: commands.Context):
    """Show all commands."""
    embed = discord.Embed(title="MT4 Junior Commands", color=discord.Color.purple())

    embed.add_field(name="💬 Chat", value=(
        "`!on` — bot talks freely in this channel (no pings)\n"
        "`!stop` — bot goes quiet (mention only)\n"
        "_(owner only)_"
    ), inline=False)

    embed.add_field(name="🛡️ Moderation (owner only)", value=(
        "`!ban @user [reason]`\n"
        "`!kick @user [reason]`\n"
        "`!timeout @user [mins] [reason]`\n"
        "`!untimeout @user`\n"
        "`!warn @user [reason]`\n"
        "`!warns @user`\n"
        "`!clearwarns @user`\n"
        "`!clear [amount]`\n"
        "`!slowmode [seconds]`\n"
        "`!lock` / `!unlock`"
    ), inline=False)

    embed.add_field(name="🎉 Giveaway (owner only)", value=(
        "`!giveaway [secs] [prize]` — start a giveaway\n"
        "`!endgiveaway` — end one early"
    ), inline=False)

    embed.add_field(name="✨ Aura", value=(
        "`!aura` — roll your aura score\n"
        "`!auracount [@user]` — check someone's aura"
    ), inline=False)

    embed.add_field(name="😂 Fun & Useful", value=(
        "`!roast [@user]` — fun AI roast\n"
        "`!glaze [@user]` — glaze someone hard\n"
        "`!braincells` — check your braincell count\n"
        "`!joke` — random funny joke\n"
        "`!codejoke` — coding joke\n"
        "`!remind [mins] [msg]` — ping reminder\n"
        "`!explain <concept>` — explain anything\n"
        "`!translate <lang> <code>` — translate code\n"
        "`!poll <question>` — yes/no poll\n"
        "`!serverinfo` — server stats\n"
        "`!userinfo [@user]` — user stats\n"
        "`!a6` — toggle 🧃 on a6waagoobeef _(owner only)_\n`!helpful` — helpful AI mode\n`!normal` — normal AI mode\n`!codemode` — coding/modding mode\n`!roastmode` — roast mode\n`!restart` — restart bot\n`!rate` — rate someone\n`!ship` — ship 2 users\n`!fight` — fake fight\n`!daily` — claim fake coins"
    ), inline=False)

    embed.set_footer(text="Mention MT4 or chat in an enabled channel to talk!")
    await ctx.send(embed=embed)


# ── Start ─────────────────────────────────────────────────────────────────────

def main():
    # Start keep-alive HTTP server in background thread
    t = threading.Thread(target=run_keepalive, daemon=True)
    t.start()
    print("🌐 Keep-alive server started")
    print("🤖 Starting MT4 Junior...")

    bot.run(DISCORD_TOKEN, reconnect=True, log_handler=None)


if __name__ == "__main__":
    main()
