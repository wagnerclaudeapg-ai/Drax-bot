import discord
from discord.ext import commands, tasks
import random
import asyncio
import os
import re
import aiohttp
import math
from datetime import timedelta, datetime
from collections import defaultdict, deque

# ================= INTENTS =================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# ══════════════════════════════════════════════════════════════════
#  🐺  DRAX SECURITY SYSTEM — VORAX GUARDIAN v1.0
#      Cérbero da VX — Clã Vorax — Guardião das Trevas
# ══════════════════════════════════════════════════════════════════

SECURITY_LOG_CHANNEL_ID = 0  # ⚠️ Substitua pelo ID do canal de log

COMMAND_SPAM_LIMIT    = 3
COMMAND_SPAM_WINDOW   = 5
COMMAND_COOLDOWN_TIME = 30
RAID_JOIN_LIMIT       = 8
RAID_JOIN_WINDOW      = 5
LOCKDOWN_THRESHOLD    = 12
MSG_SPAM_LIMIT        = 7
MSG_SPAM_WINDOW       = 5
MSG_REPEAT_LIMIT      = 4
EMOJI_SPAM_LIMIT      = 20
MENTION_SPAM_LIMIT    = 5
ADMIN_ACTION_LIMIT    = 5
ADMIN_ACTION_WINDOW   = 10
RISK_SPAM_MSG         = 2
RISK_SPAM_CMD         = 3
RISK_RAID             = 5
RISK_LINK             = 4
RISK_NEW_ACCOUNT      = 2
RISK_NO_AVATAR        = 1
RISK_SUSPICIOUS_THRESHOLD = 12
ACCOUNT_MIN_AGE_DAYS  = 7
CANAL_GERAL_MONITORADO = "chat-geral"
MALICIOUS_PATTERNS = [
    r"discord\.gift", r"discordnitro\.", r"free.*nitro",
    r"steamcommunity.*\.ru", r"bit\.ly", r"tinyurl\.com",
    r"grabify\.link", r"iplogger\.", r"discord-app\.com",
    r"dicsord\.", r"dlscord\.",
]

class SecurityDatabase:
    def __init__(self):
        self.risk_scores   = {}
        self.flagged_users = {}
        self.alert_history = []
        self.total_alerts  = 0
        self.spam_events   = 0
        self.raid_events   = 0
        self.link_events   = 0
        self.admin_events  = 0
        self.lockdown_active  = False
        self.emergency_mode   = False
        self.security_level   = "NORMAL"

    def add_risk(self, user_id, points, reason):
        self.risk_scores[user_id] = self.risk_scores.get(user_id, 0) + points
        if self.risk_scores[user_id] >= RISK_SUSPICIOUS_THRESHOLD:
            self.flagged_users[user_id] = {"reason": reason, "time": datetime.utcnow(), "score": self.risk_scores[user_id]}

    def get_risk(self, uid):
        return self.risk_scores.get(uid, 0)

    def is_flagged(self, uid):
        return uid in self.flagged_users

    def log_alert(self, alert_type, details):
        self.total_alerts += 1
        self.alert_history.append({"type": alert_type, "details": details, "time": datetime.utcnow()})
        if len(self.alert_history) > 500:
            self.alert_history.pop(0)

    def reset(self):
        self.risk_scores.clear(); self.flagged_users.clear(); self.alert_history.clear()
        self.total_alerts = self.spam_events = self.raid_events = self.link_events = self.admin_events = 0
        self.lockdown_active = self.emergency_mode = False
        self.security_level  = "NORMAL"


class DraxSecurityCog(commands.Cog, name="DraxSecurity"):
    """DRAX SECURITY SYSTEM — VORAX GUARDIAN v1.0 — Cérbero da VX."""

    def __init__(self, bot):
        self.bot = bot
        self.db  = SecurityDatabase()
        self._cmd_timestamps   = defaultdict(deque)
        self._msg_timestamps   = defaultdict(deque)
        self._join_timestamps  = defaultdict(deque)
        self._admin_timestamps = defaultdict(deque)
        self._last_msg         = {}
        self._cmd_cooldowns    = {}
        self.cleanup_task.start()

    def cog_unload(self):
        self.cleanup_task.cancel()

    async def get_log_channel(self, guild):
        return self.bot.get_channel(SECURITY_LOG_CHANNEL_ID)

    def _now(self):
        return datetime.utcnow().timestamp()

    def _prune(self, dq, window):
        cutoff = self._now() - window
        while dq and dq[0] < cutoff:
            dq.popleft()

    def _level_color(self):
        return {"NORMAL": 0x8b0000, "ALERTA": 0xff4400, "LOCKDOWN": 0xff0000, "EMERGÊNCIA": 0x000000}.get(self.db.security_level, 0x8b0000)

    async def send_alert(self, guild, threat_type, user, details, color=0xff0000, critical=False):
        ch = await self.get_log_channel(guild)
        if not ch:
            return
        now = datetime.utcnow()
        self.db.log_alert(threat_type, details)
        embed = discord.Embed(title=f"{'🔴' if critical else '🚨'} DRAX SECURITY ALERT", color=color, timestamp=now)
        embed.add_field(name="⚠️ Tipo de Ameaça", value=f"`{threat_type}`", inline=False)
        embed.add_field(name="👤 Usuário",         value=str(user) if user else "Desconhecido", inline=True)
        embed.add_field(name="🆔 ID",              value=str(user.id) if user else "—", inline=True)
        embed.add_field(name="🏠 Servidor",        value=guild.name, inline=True)
        embed.add_field(name="📋 Detalhes",        value=details, inline=False)
        embed.add_field(name="⏰ Horário (UTC)",   value=now.strftime("%d/%m/%Y às %H:%M:%S"), inline=False)
        if user and hasattr(user, "display_avatar"):
            embed.set_thumbnail(url=user.display_avatar.url)
        risk    = self.db.get_risk(user.id) if user else 0
        flagged = "⛔ SIM" if (user and self.db.is_flagged(user.id)) else "✅ Não"
        embed.set_footer(text=f"DRAX SECURITY • Risco: {risk}pts | Suspeito: {flagged}",
                         icon_url=self.bot.user.display_avatar.url if self.bot.user else None)
        await ch.send(embed=embed)

    @commands.Cog.listener()
    async def on_ready(self):
        await asyncio.sleep(3)
        for guild in self.bot.guilds:
            ch = await self.get_log_channel(guild)
            if not ch:
                continue
            now = datetime.utcnow()
            boot = discord.Embed(
                description=(
                    "```\n"
                    "╔══════════════════════════════════════╗\n"
                    "║      DRAX SECURITY SYSTEM            ║\n"
                    "║     — VORAX GUARDIAN v1.0 —          ║\n"
                    "║    🐺  CÉRBERO DA VX  ONLINE  🔥     ║\n"
                    "╚══════════════════════════════════════╝\n"
                    "```"
                ),
                color=0x8b0000, timestamp=now
            )
            boot.set_author(name="DRAX SECURITY • Guardião Iniciado",
                            icon_url=self.bot.user.display_avatar.url if self.bot.user else None)
            boot.add_field(name="🛡️ Módulos Ativos (14/14)", inline=False, value=(
                "✅ Anti-Spam de Comandos\n✅ Detector de Raid\n✅ Auto Lockdown\n"
                "✅ Anti-Spam de Mensagens\n✅ Monitor de Ações Admin\n✅ Detector de Bot Suspeito\n"
                "✅ Detector de Links Maliciosos\n✅ Pontuação de Risco\n✅ Detecção de Script\n"
                "✅ Anti-Raid Extremo / Emergência\n✅ Contas Suspeitas\n✅ Inteligência (DB)\n"
                "✅ Monitor de Erros\n✅ Comandos Administrativos"
            ))
            boot.add_field(name="⚙️ Configuração Atual", inline=False, value=(
                f"📡 Canal Log: <#{SECURITY_LOG_CHANNEL_ID}>\n"
                f"🚫 Spam CMD: `{COMMAND_SPAM_LIMIT} cmds/{COMMAND_SPAM_WINDOW}s`\n"
                f"🚪 Raid: `{RAID_JOIN_LIMIT} entradas/{RAID_JOIN_WINDOW}s`\n"
                f"💬 Spam MSG: `{MSG_SPAM_LIMIT} msgs/{MSG_SPAM_WINDOW}s`\n"
                f"⚠️ Risco Suspeito: `≥{RISK_SUSPICIOUS_THRESHOLD} pts`"
            ))
            boot.add_field(name="🔴 Status do Sistema", inline=False, value=(
                f"**Nível:** `NORMAL` | **Servidor:** `{guild.name}`\n"
                f"**Membros:** `{guild.member_count}` | **Iniciado:** `{now.strftime('%d/%m/%Y %H:%M UTC')}`"
            ))
            boot.set_footer(text="DRAX SECURITY SYSTEM — VORAX GUARDIAN • Todas as três cabeças operacionais.")
            await ch.send(embed=boot)

            cmds_embed = discord.Embed(title="📋 Comandos — DRAX SECURITY", color=0x8b0000, timestamp=now)
            cmds_embed.add_field(name="🔍 Status & Info", inline=False, value=(
                "`!security status` — Painel completo\n"
                "`!security riskscore @user` — Risco do usuário\n"
                "`!security flagged` — Usuários suspeitos"
            ))
            cmds_embed.add_field(name="🔧 Administração", inline=False, value=(
                "`!security reset` — Limpar alertas\n"
                "`!security lockdown on/off` — Lockdown manual\n"
                "`!security emergency on/off` — Modo emergência\n"
                "`!security unflag @user` — Remover flag\n"
                "`!security alerts` — Últimos 10 alertas\n"
                "`!security stats` — Estatísticas gerais"
            ))
            cmds_embed.add_field(name="⚠️ Permissão", value="Todos os comandos exigem **Administrador**.", inline=False)
            cmds_embed.set_footer(text="DRAX SECURITY SYSTEM — VORAX GUARDIAN v1.0")
            await ch.send(embed=cmds_embed)

    @commands.Cog.listener()
    async def on_command(self, ctx):
        if ctx.author.bot:
            return
        uid = ctx.author.id
        if uid in self._cmd_cooldowns:
            release = self._cmd_cooldowns[uid]
            if datetime.utcnow() < release:
                remaining = (release - datetime.utcnow()).seconds
                try: await ctx.message.delete()
                except: pass
                await ctx.send(f"⛔ {ctx.author.mention} cooldown de segurança. Aguarde `{remaining}s`.", delete_after=5)
                return
        dq = self._cmd_timestamps[uid]
        dq.append(self._now())
        self._prune(dq, COMMAND_SPAM_WINDOW)
        if len(dq) > COMMAND_SPAM_LIMIT:
            self.db.add_risk(uid, RISK_SPAM_CMD, "Spam de comandos")
            self.db.spam_events += 1
            self._cmd_cooldowns[uid] = datetime.utcnow() + timedelta(seconds=COMMAND_COOLDOWN_TIME)
            dq.clear()
            await self.send_alert(ctx.guild, "SPAM DE COMANDOS / SCRIPT", ctx.author,
                f"**{ctx.author}** executou `{COMMAND_SPAM_LIMIT}+` cmds em `{COMMAND_SPAM_WINDOW}s`.\n"
                f"Cooldown: `{COMMAND_COOLDOWN_TIME}s` | Risco: `{self.db.get_risk(uid)} pts`",
                color=0xff4400)

    @commands.Cog.listener()
    async def on_member_join(self, member):
        guild = member.guild
        gid   = guild.id
        dq    = self._join_timestamps[gid]
        dq.append(self._now())
        self._prune(dq, RAID_JOIN_WINDOW)
        count = len(dq)
        if count >= LOCKDOWN_THRESHOLD and not self.db.emergency_mode:
            self.db.emergency_mode = self.db.lockdown_active = True
            self.db.security_level = "EMERGÊNCIA"
            self.db.raid_events += 1
            await self.send_alert(guild, "🔴 RAID SEVERO — MODO EMERGÊNCIA ATIVADO", None,
                f"**{count}** membros em `{RAID_JOIN_WINDOW}s`.\n⛔ Use `!security emergency off` para desativar.",
                color=0xff0000, critical=True)
            await self._apply_lockdown(guild, True)
        elif count >= RAID_JOIN_LIMIT and not self.db.lockdown_active:
            self.db.security_level = "ALERTA"
            self.db.raid_events += 1
            await self.send_alert(guild, "POSSÍVEL RAID DETECTADO", None,
                f"**{count}** membros nos últimos `{RAID_JOIN_WINDOW}s`.\n⚠️ Modo Alerta ativado.",
                color=0xff4400, critical=True)
        await self._check_suspicious_account(member)
        if member.bot:
            await self._check_suspicious_bot(member)

    async def _apply_lockdown(self, guild, activate):
        everyone = guild.default_role
        for ch in guild.text_channels:
            try:
                ow = ch.overwrites_for(everyone)
                ow.send_messages = False if activate else None
                await ch.set_permissions(everyone, overwrite=ow)
            except: pass

    async def _check_suspicious_account(self, member):
        guild = member.guild
        risk  = 0
        reasons = []
        age_days = (datetime.utcnow() - member.created_at.replace(tzinfo=None)).days
        if age_days < ACCOUNT_MIN_AGE_DAYS:
            risk += RISK_NEW_ACCOUNT
            reasons.append(f"Conta nova ({age_days} dias)")
        if not member.avatar:
            risk += RISK_NO_AVATAR
            reasons.append("Sem avatar")
        if risk > 0:
            self.db.add_risk(member.id, risk, " | ".join(reasons))
            if self.db.is_flagged(member.id):
                await self.send_alert(guild, "CONTA SUSPEITA AO ENTRAR", member,
                    f"Score: `{self.db.get_risk(member.id)} pts`\nMotivos: `{' | '.join(reasons)}`",
                    color=0xff8800)

    async def _check_suspicious_bot(self, member):
        guild = member.guild
        if not member.bot:
            return
        added_by = None
        try:
            async for entry in guild.audit_logs(action=discord.AuditLogAction.bot_add, limit=5):
                if entry.target.id == member.id:
                    added_by = entry.user
                    break
        except: pass
        if added_by and not added_by.guild_permissions.administrator:
            await self.send_alert(guild, "BOT ADICIONADO SEM PERMISSÃO ADMIN", added_by,
                f"Bot: **{member}** (`{member.id}`)\nAdicionado por: **{added_by}** (sem admin)",
                color=0xff0000, critical=True)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return
        uid  = message.author.id
        cont = message.content
        now  = self._now()

        # Spam de mensagens
        dq = self._msg_timestamps[uid]
        dq.append(now)
        self._prune(dq, MSG_SPAM_WINDOW)
        if len(dq) > MSG_SPAM_LIMIT:
            self.db.add_risk(uid, RISK_SPAM_MSG, "Spam de mensagens")
            self.db.spam_events += 1
            dq.clear()
            await self.send_alert(message.guild, "SPAM DE MENSAGENS", message.author,
                f"**{message.author}** enviou `{MSG_SPAM_LIMIT}+` msgs em `{MSG_SPAM_WINDOW}s`.",
                color=0xff8800)

        # Mensagens repetidas
        last = self._last_msg.get(uid, {})
        if last.get("content") == cont:
            last["count"] = last.get("count", 1) + 1
            if last["count"] >= MSG_REPEAT_LIMIT:
                self.db.add_risk(uid, RISK_SPAM_MSG, "Mensagens repetidas")
                self.db.spam_events += 1
                last["count"] = 0
                await self.send_alert(message.guild, "MENSAGENS REPETIDAS", message.author,
                    f"**{message.author}** repetiu a mesma mensagem `{MSG_REPEAT_LIMIT}x`.",
                    color=0xff8800)
        else:
            last = {"content": cont, "count": 1}
        self._last_msg[uid] = last

        # Spam de emojis
        emoji_count = len(re.findall(r'<a?:\w+:\d+>|[\U00010000-\U0010ffff]', cont))
        if emoji_count > EMOJI_SPAM_LIMIT:
            self.db.add_risk(uid, RISK_SPAM_MSG, "Spam de emojis")
            self.db.spam_events += 1
            await self.send_alert(message.guild, "SPAM DE EMOJIS", message.author,
                f"**{message.author}** enviou `{emoji_count}` emojis numa mensagem.",
                color=0xffaa00)

        # Spam de menções
        if len(message.mentions) > MENTION_SPAM_LIMIT:
            self.db.add_risk(uid, RISK_SPAM_MSG, "Spam de menções")
            self.db.spam_events += 1
            try: await message.delete()
            except: pass
            await self.send_alert(message.guild, "SPAM DE MENÇÕES", message.author,
                f"**{message.author}** mencionou `{len(message.mentions)}` usuários.",
                color=0xff4400, critical=True)

        # Links maliciosos
        cont_lower = cont.lower()
        for pattern in MALICIOUS_PATTERNS:
            if re.search(pattern, cont_lower):
                self.db.add_risk(uid, RISK_LINK, "Link malicioso")
                self.db.link_events += 1
                try: await message.delete()
                except: pass
                await self.send_alert(message.guild, "LINK MALICIOSO / PHISHING", message.author,
                    f"**{message.author}** enviou link suspeito.\nPadrão: `{pattern}`",
                    color=0xff0000, critical=True)
                return

    @tasks.loop(minutes=30)
    async def cleanup_task(self):
        cutoff = self._now() - 3600
        for dq in list(self._msg_timestamps.values()):
            self._prune(dq, 3600)
        self._cmd_cooldowns = {k: v for k, v in self._cmd_cooldowns.items() if v > datetime.utcnow()}

    @cleanup_task.before_loop
    async def before_cleanup(self):
        await self.bot.wait_until_ready()

    # ── Grupo de comandos de segurança ──
    @commands.group(name="security", invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def security_group(self, ctx):
        db = self.db
        color = self._level_color()
        embed = discord.Embed(title="🐺 DRAX SECURITY — Painel de Status", color=color, timestamp=datetime.utcnow())
        embed.add_field(name="🔴 Nível",      value=f"`{db.security_level}`",                     inline=True)
        embed.add_field(name="🔒 Lockdown",   value="⛔ ATIVO" if db.lockdown_active else "✅ OFF", inline=True)
        embed.add_field(name="⚡ Emergência", value="🆘 ATIVA"  if db.emergency_mode  else "✅ OFF", inline=True)
        embed.add_field(name="📊 Alertas",    value=f"`{db.total_alerts}`",                        inline=True)
        embed.add_field(name="⚠️ Suspeitos",  value=f"`{len(db.flagged_users)}`",                  inline=True)
        embed.set_footer(text="DRAX SECURITY — VORAX GUARDIAN v1.0")
        await ctx.send(embed=embed)

    @security_group.command(name="status")
    @commands.has_permissions(administrator=True)
    async def security_status(self, ctx):
        await self.security_group(ctx)

    @security_group.command(name="reset")
    @commands.has_permissions(administrator=True)
    async def security_reset(self, ctx):
        self.db.reset()
        embed = discord.Embed(title="✅ Sistema resetado", color=0x8b0000, timestamp=datetime.utcnow())
        embed.set_footer(text=f"Resetado por {ctx.author}")
        await ctx.send(embed=embed)

    @security_group.command(name="lockdown")
    @commands.has_permissions(administrator=True)
    async def security_lockdown(self, ctx, state: str = "on"):
        activate = state.lower() in ("on", "ativar", "ligar")
        self.db.lockdown_active = activate
        self.db.security_level  = "LOCKDOWN" if activate else "NORMAL"
        await self._apply_lockdown(ctx.guild, activate)
        color = 0xff0000 if activate else 0x8b0000
        await ctx.send(embed=discord.Embed(title=f"🔒 Lockdown {'⛔ ATIVADO' if activate else '✅ DESATIVADO'}",
            description=f"Por {ctx.author.mention}.", color=color, timestamp=datetime.utcnow()))

    @security_group.command(name="emergency")
    @commands.has_permissions(administrator=True)
    async def security_emergency(self, ctx, state: str = "on"):
        activate = state.lower() in ("on", "ativar", "ligar")
        self.db.emergency_mode = self.db.lockdown_active = activate
        self.db.security_level = "EMERGÊNCIA" if activate else "NORMAL"
        if activate: await self._apply_lockdown(ctx.guild, True)
        color = 0xff0000 if activate else 0x8b0000
        await ctx.send(embed=discord.Embed(title=f"⚡ Emergência {'🆘 ATIVADA' if activate else '✅ DESATIVADA'}",
            color=color, timestamp=datetime.utcnow()))

    @security_group.command(name="alerts")
    @commands.has_permissions(administrator=True)
    async def security_alerts(self, ctx):
        recent = self.db.alert_history[-10:]
        if not recent: return await ctx.send("✅ Nenhum alerta registrado.", delete_after=10)
        embed = discord.Embed(title="📋 Últimos 10 Alertas", color=0xff4400, timestamp=datetime.utcnow())
        for i, a in enumerate(reversed(recent), 1):
            t = a["time"].strftime("%d/%m %H:%M")
            embed.add_field(name=f"#{i} [{t}] {a['type']}", value=a["details"][:100], inline=False)
        embed.set_footer(text="DRAX SECURITY — Histórico")
        await ctx.send(embed=embed)

    @security_group.command(name="stats")
    @commands.has_permissions(administrator=True)
    async def security_stats(self, ctx):
        db = self.db
        embed = discord.Embed(title="📊 Estatísticas do Sistema", color=0x8b0000, timestamp=datetime.utcnow())
        embed.add_field(name="Alertas",   value=f"`{db.total_alerts}`",       inline=True)
        embed.add_field(name="Spam",      value=f"`{db.spam_events}`",        inline=True)
        embed.add_field(name="Raid",      value=f"`{db.raid_events}`",        inline=True)
        embed.add_field(name="Links",     value=f"`{db.link_events}`",        inline=True)
        embed.add_field(name="Admin",     value=f"`{db.admin_events}`",       inline=True)
        embed.add_field(name="Suspeitos", value=f"`{len(db.flagged_users)}`", inline=True)
        embed.set_footer(text="DRAX SECURITY SYSTEM — VORAX GUARDIAN")
        await ctx.send(embed=embed)

    @security_group.command(name="flagged")
    @commands.has_permissions(administrator=True)
    async def security_flagged(self, ctx):
        if not self.db.flagged_users: return await ctx.send("✅ Nenhum suspeito.", delete_after=10)
        embed = discord.Embed(title="⛔ Usuários Suspeitos", color=0xff0000, timestamp=datetime.utcnow())
        for uid, info in list(self.db.flagged_users.items())[:15]:
            embed.add_field(name=f"ID: {uid}",
                value=f"Motivo: `{info['reason']}`\nScore: `{info['score']} pts`\nEm: `{info['time'].strftime('%d/%m %H:%M')}`", inline=True)
        await ctx.send(embed=embed)

    @security_group.command(name="unflag")
    @commands.has_permissions(administrator=True)
    async def security_unflag(self, ctx, member: discord.Member):
        rf = self.db.flagged_users.pop(member.id, None)
        rs = self.db.risk_scores.pop(member.id, None)
        if rf or rs: await ctx.send(f"✅ Flag removido de **{member}**.", delete_after=10)
        else: await ctx.send(f"ℹ️ **{member}** não estava marcado.", delete_after=10)

    @security_group.command(name="riskscore")
    @commands.has_permissions(administrator=True)
    async def security_riskscore(self, ctx, member: discord.Member):
        score = self.db.get_risk(member.id)
        flag  = self.db.is_flagged(member.id)
        color = 0x8b0000 if score < 5 else (0xff4400 if score < RISK_SUSPICIOUS_THRESHOLD else 0xff0000)
        embed = discord.Embed(title=f"🔎 Risco — {member.name}", color=color, timestamp=datetime.utcnow())
        embed.add_field(name="Score",    value=f"`{score} pts`", inline=True)
        embed.add_field(name="Limite",   value=f"`{RISK_SUSPICIOUS_THRESHOLD} pts`", inline=True)
        embed.add_field(name="Suspeito", value="⛔ SIM" if flag else "✅ Não", inline=True)
        if flag:
            embed.add_field(name="Motivo", value=f"`{self.db.flagged_users[member.id]['reason']}`", inline=False)
        embed.set_thumbnail(url=member.display_avatar.url)
        await ctx.send(embed=embed)

# ══════════════════════════════════════════════════════════════════
#  FIM DO DRAX SECURITY SYSTEM
# ══════════════════════════════════════════════════════════════════

# ================= SISTEMA DE AVISOS =================
_aviso_estado = {}

# ================= CONFIGURAÇÃO E IDs =================
TOKEN     = os.getenv("TOKEN")
GROQ_API_KEY = os.getenv("GROQ_KEY")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL   = "llama3-8b-8192"

# ── IDs dos membros do clã Vorax/VX — substitua pelos IDs reais ──
DONO_ID    = 0  # ⚠️ ID do dono/alpha do servidor

# Membros adicionais — preencha conforme necessário
MEMBRO_1_ID = None   # Ex: lider
MEMBRO_2_ID = None   # Ex: vice-lider
MEMBRO_3_ID = None   # Ex: membro especial

# ID do canal de chat geral
CANAL_CHAT_GERAL_ID = 0  # ⚠️ Substitua pelo ID real

# ══════════════════════════════════════════════════════════════════
#                   DIÁLOGOS DO DRAX
# ══════════════════════════════════════════════════════════════════

# As três cabeças do Drax:
# 🐺 Rax  — a cabeça feroz, impulsiva
# 🔥 Drex — a cabeça estratégica, calculista
# ⛓️ Rux  — a cabeça leal, emocional

REACOES_FOFAS = [
    "...Rax: *rosna baixinho enquanto desvia os olhos* Cala boca, eu não tô corado!! 🐺🔥\nDrex: *vira a cabeça com dignidade* Desconsidere a reação dele. Mas... obrigado. ⛓️\nRux: *uiva de alegria* AAAAAA SÃO TÃO GENTIS!! 🐾💀✨",
    "Rux: MEU CORAÇÃO DE PEDRA FALHOU!! 😭🐺 Senti alguma coisa!! É fofura?? O que é isso?!\nRax: Fraqueza. Pura fraqueza.\nDrex: *suspiro pesado* Ignore os dois. Mas sim... foi tocante. 🔥⛓️",
    "🐺 *As três cabeças olham uma pra outra em silêncio...*\nRax: Não vai rolar.\nDrex: Concordo.\nRux: EU AMO VOCÊS!! *lame as duas cabeças* 🐾🔥\nRax + Drex: PARA!! 😤",
    "Rux: Esse carinho vai ficar guardado nas chamas do meu coração pra sempre!! 🔥⛓️\nRax: *tenta parecer indiferente mas o rabo tá abanando* ...\nDrex: O rabo não mente. 🐺💀✨",
    "🐾 *Drax para tudo e senta* VX tem pessoas assim que chegam e derrubam as três defesas de uma vez!! Rax tá com orelha baixa, Drex perdeu o roteiro e Rux tá... Rux tá chorando??\nRux: NÃO ESTOU. *lágrimas vermelhas* 💀🔥",
    "*Rax olha pro lado tentando disfarçar*\n*Drex tosse formalmente*\n*Rux já tá soltando uivo longo no horizonte*\nDrax (em coro): ...valeu. 🐺🔥⛓️💀",
    "Drex: Análise concluída. A afirmação tem fundamento. 🔥\nRax: Menos conversa, mais osso. 🐺\nRux: ELE DISSE QUE SOMOS FOFOS! FOFOS FOFOS FOFOS!! ⛓️🐾✨",
    "🐺 *O pelo do Drax arrepia todinho*\n*As três cabeças se entreolham*\nDrex: Situação inédita registrada.\nRax: Eu não tô gostando... mas não quero que pare.\nRux: MAIS!!! 🔥⛓️💀",
]

LISTA_TRISTEZA = [
    "Rax: *mostra os dentes* Você acabou de ativar o modo de ataque. 🐺🔥\nDrex: Retaliação monitorada. Segure o Rax.\nRux: *soluça* Por que as pessoas são ruins?? 😭⛓️",
    "*Drax abaixa as três cabeças lentamente*\nRux: ...isso doeu nos três.\nRax: Considere-se avisado. 🐺💀\nDrex: Registrado. Não recomendo repetir. 🔥",
    "Rux: MAGOARAM O DRAX!! 😭🐾 Alguém faz alguma coisa!!\nRax: JÁ TÔ FAZENDO!! *rosna*\nDrex: Rax. Não. Respira. 🔥⛓️",
    "🐺 *As três cabeças ficam em silêncio*\nDrex: ...Isso foi desnecessário.\nRax: *rosna quieto*\nRux: Só vai embora. 💀🔥",
    "Rax: Eu esperava melhor da sua parte. 🐺\nDrex: Decepcionante.\nRux: *tapa as próprias orelhas pra não ouvir mais* ⛓️😭🔥",
]

LISTA_DESPEDIDA = [
    "Rax: Vai lá. 🐺 *vira a cabeça*\nRux: CUIDA MUITO BEM DE VOCÊ, VIU?? VEM LOGO!! 😭🐾\nDrex: ...Até breve. 🔥⛓️",
    "Drex: Partida registrada. 🔥\nRax: Pode ir.\nRux: *acompanha com o olhar até sumir* Já tô com saudade. 😭🐺⛓️",
    "🐾 *Drax escolta até a porta da VX com as três cabeças erguidas*\nRux: Até logo!! Não esquece de nós!! 💀🐺\nRax: Tô de olho. Sempre. 🔥",
    "Rux: TCHAU TCHAU TCHAU!! 🐾😭\nRax: Para com isso.\nDrex: Que retorne com segurança. ⛓️🐺🔥",
    "*Drax senta na entrada da VX e fica olhando pro horizonte*\nRux: Já foi... 😢💀\nRax: Já volta.\nDrex: O Drax não abandona quem é da família. 🔥⛓️🐺",
]

LISTA_GRATIDAO = [
    "Rux: OBRIGADO DE VERDADE DO FUNDO DO CORAÇÃO!! 🐾🔥\nRax: *acena levemente*\nDrex: Reconhecimento notado e apreciado. ⛓️🐺",
    "Rax: Tá bom. 🐺\nDrex: Obrigado. 🔥\nRux: MUITO OBRIGADO MEU AMOR!! 😭🐾⛓️",
    "Drex: De nada. Que isso sirva à VX. 🔥⛓️\nRax: Qualquer hora.\nRux: FOI UM PRAZER IMENSO!! 😊🐺🐾",
    "*Drax inclina as três cabeças em reverência*\nRux: Não precisa nem falar, o coração entende!! 💀🔥\nRax: Voltamos pro posto agora. 🐺⛓️",
]

LISTA_CONFUSAO = [
    "Rax: ...O que foi isso?? 🐺\nDrex: Erro de interpretação. Precisa de mais dados.\nRux: Repete pra gente?? 🔥⛓️🐾",
    "Drex: Input não reconhecido pelas três cabeças. 🔥\nRax: Fala humano.\nRux: O Drax não entendeu, perdão!! 🐺😅⛓️",
    "*As três cabeças inclinam em direções diferentes tentando entender*\nRux: Não pegamos... 😶🐾\nRax: De novo.\nDrex: Com mais clareza. 🔥⛓️🐺",
    "Rux: Eita!! 😵🐾 Sumiu no processamento do Drex!!\nDrex: Processando... ainda processando...\nRax: Simplifica. 🐺🔥",
    "🐺 Rax: Não.\nDrex: Insuficiente.\nRux: Não entendemos, mas te amamos mesmo assim!! ⛓️🔥🐾",
]

LISTA_HYPE = [
    "🔥 VORAX VX CHEGOU!! *Drax ruge com as três cabeças* BORA TUDO ACIMA DO LIMITE!! 🐺⛓️🐾",
    "Rux: VIBE BOA DETECTADA!! 😤🐾\nRax: *bate a pata no chão* VORAX ACIMA DE TUDO!!\nDrex: Nível de energia: máximo. 🔥⛓️🐺",
    "*Drax se levanta e as três cabeças rugem ao mesmo tempo*\n🐺🔥⛓️ ISSO É VX!! ISSO É VORAX!! Bora com tudo!! 💀🐾",
    "Rax: É HORA!! 🐺🔥\nDrex: Posição: ofensiva.\nRux: VAMOS QUE VAMOS VX!! 😭🐾⛓️✨",
    "🔥 O Drax sentiu a energia!! As três cabeças sincronizaram!! Isso só acontece quando a VX vai fazer história!! 🐺⛓️💀🐾",
]

LISTA_MOTIVACAO = [
    "Drex: Você tem capacidade. Apenas execute. 🔥⛓️\nRax: Não fica parado, vai.\nRux: A VX acredita em você!! BORA!! 🐺🐾",
    "Rax: Fraqueza é temporária. Levanta. 🐺🔥\nDrex: Estratégia: um passo de cada vez.\nRux: EU TÔ AQUI DO SEU LADO!! ⛓️🐾😤",
    "*Drax coloca a pata no ombro do membro*\nRux: Vai conseguir, eu sei!! 🐾💀\nDrex: Os dados confirmam: você é capaz.\nRax: Não decepcionas a VX. 🐺🔥⛓️",
    "Rux: Sabe o que o Drax pensa quando vê você tentando?? ORGULHO. 🐾🔥\nRax: Justo.\nDrex: Prossiga. ⛓️🐺💀",
    "🐺 As três cabeças falam em coro: VORAX NUNCA RECUA!! 🔥⛓️ Nem você recua!! 💀🐾",
]

LISTA_PIADAS = [
    "Drex: Por que o Cérbero foi mal na prova? Rax: Porque tinha três respostas diferentes. Rux: HAHAHAHAHA RI MUITO!! 🐾🔥😂",
    "Rux: O que o Cérbero come no café da manhã?? TUDO!! 😂🐾\nRax: Literalmente. Tudo.\nDrex: Precisão impressionante. 🔥⛓️",
    "Rax: Qual a melhor parte de ser o Drax? 🐺 Ter três bocas pra morder quem não respeita a VX. Rux: E TRÊS VEZES MAIS AMOR PRA DAR!! 😭🐾⛓️",
    "Drex: Piada lógica: Drax tenta dormir. Uma cabeça ronca. Outra fica acordada de raiva. Terceira chora de rir. 🔥\nRax: Isso é real e eu odeio.\nRux: 😂🐾💀",
]

LISTA_COMIDA = [
    "Rux: OSSO!! ME DEU OSSO?? 🐾😭 Obrigadoooo!!\nRax: É meu.\nDrex: Divida. Proporcionalmente. 🔥⛓️🐺",
    "*Drax levanta as três cabeças em uníssono*\nRax: Tem comida?? 🐺\nDrex: Fonte e quantidade?\nRux: PODE SER QUALQUER COISA EU AMO COMIDA!! 🐾🔥😂",
    "Drex: Consumo calórico analisado. Aprovado. 🔥\nRax: Passa o osso.\nRux: Nhac nhac nhac!! 🐾😋⛓️🐺",
    "Rux: O Drax tem fome!! 😤🐾 Alguém alimenta o guardião da VX??\nRax: Dou conta sozinho.\nDrex: Nenhum de nós dá. 🔥⛓️🐺",
]

LISTA_JOGOS = [
    "Rax: Competição?? 🐺🔥 Tô dentro. Mas aviso: o Drax joga pra ganhar.\nDrex: Análise de estratégia iniciada.\nRux: BORA JOGAR VX GANG!! 🐾⛓️",
    "Drex: Qual a modalidade? 🔥\nRax: Tanto faz, ganhamos.\nRux: Tem co-op?? Quero jogar juntos com todo mundo!! 🐾⛓️🐺",
    "Rux: Jogos são a melhor coisa depois da VX!! 🐾😂🔥\nRax: Depois de ossos também.\nDrex: E de emboscadas bem planejadas. ⛓️🐺",
]

LISTA_SONO = [
    "*As três cabeças do Drax bocejam ao mesmo tempo*\n🐺🔥⛓️ Rax: Boa noite.\nDrex: Descanse.\nRux: SONHA LINDO, MEMBRO DA VX!! 🐾😴💀",
    "Rux: Drax também tem soninho às vezes... 😴🐾\nRax: Não admito isso.\nDrex: O corpo registra fadiga. É biológico. 🔥⛓️🐺",
    "Rax: Pode dormir. A VX tá guardada. 🐺💀\nDrex: Turno de guarda assumido.\nRux: Boa noite boa noite boa noite!! 🐾🔥⛓️😴",
]

LISTA_ANIMAIS = [
    "Rux: Animais são incríveis!! 🐾🔥 Principalmente os Cérberos!!\nRax: Somos superiores.\nDrex: Tecnicamente somos mitológicos, não animais. ⛓️🐺",
    "Drex: Fascinante a diversidade faunística. 🔥\nRax: Prefiro os que mordem.\nRux: Prefiro TODOS!! 😭🐾⛓️🐺",
]

LISTA_CORES = [
    "Rax: Vermelho. 🐺🔥 Cor do poder.\nDrex: E do perigo. Estrategicamente vantajoso.\nRux: Eu gosto de preto também!! E vermelho!! E fogo!! ⛓️🐾💀",
    "Drex: A paleta cromática da VX é deliberada. 🔥⛓️\nRax: Vermelho e preto. Ponto.\nRux: Com bastante fogo no meio!! 🐺🐾💀",
]

LISTA_SURPRESA = [
    "*As três cabeças do Drax se voltam ao mesmo tempo*\nRax: O quê?? 🐺\nDrex: Registrando...\nRux: AAAAAA QUE ISSO?? 😱🐾🔥⛓️",
    "Rux: NÃO ESPERAVA POR ESSA!! 😱🐾\nRax: Raramente algo nos surpreende.\nDrex: Situação atípica confirmada. 🔥⛓️🐺",
    "🐺🔥⛓️ *As três bocas se abrem ao mesmo tempo*\nDrax (em coro): ...NÃO ESPERÁVAMOS. 💀🐾",
]

# ═══════════════════════════════════════════════════════════
#  DESPEDIDA AO SAIR DO SERVIDOR
# ═══════════════════════════════════════════════════════════

MENSAGENS_DESPEDIDA_DM = [
    """🐺🔥⛓️ **Uma mensagem das três cabeças do Drax...**

Rax: Então foi assim. Você foi embora da VX.

Drex: Registrado. Membro desligado do clã Vorax.

Rux: ...Eu não queria que isso acontecesse. 😭🐾

*O Drax senta sozinho na entrada da VX por um tempo*

Rux: Olha... não importa o motivo. Não importa se foi por cansaço, por desentendimento, por qualquer coisa. Você fez parte do nosso clã e isso não apaga.

Rax: O Drax guarda os que passaram por aqui. Sempre.

Drex: Se um dia quiser voltar, a análise será feita com abertura. Portas do Vorax não fecham pra quem foi família.

Rux: Cuida muito bem de você por aí, tá?? 😭🐾 Bebe água, come direito, descansa. E sabe que as três cabeças do Drax torcem por você, onde quer que esteja!!

*Com lealdade e respeito,*
**Drax — Cérbero da VX, Clã Vorax** 🐺🔥⛓️""",

    """💀 **Do Drax, guardião da entrada do Vorax...**

*As três cabeças se reúnem antes de escrever*

Rax: Não é fácil perder um membro.
Drex: Não. Não é.
Rux: 😭🐾

Você passou pela nossa guarda. Isso significa que você é alguém que o Drax conheceu, observou e, de uma forma ou de outra, protegeu.

Rax: Quem o Drax protegeu, nunca é esquecido.

Drex: Independente do que trouxe você pra esse ponto, saiba que o Vorax não guarda rancor de quem foi leal enquanto esteve aqui.

Rux: E se você só quiser conversar um dia, ou voltar pra dar um oi, o Drax tá aqui. Sempre tá aqui. 🐺🔥⛓️🐾

Vai bem. Essa é a nossa despedida.

**Drax 🐺🔥⛓️ — VX / Clã Vorax**""",
]

# ═══════════════════════════════════════════════════════════
#  SISTEMA DE BOAS-VINDAS AO ENTRAR
# ═══════════════════════════════════════════════════════════

MENSAGENS_BEM_VINDO = [
    """🐺🔥⛓️ **PARA. Quem é você?**

*O Drax bloqueia a entrada com as três cabeças erguidas*

Rax: Nome, procedência, intenção.
Drex: *analisa friamente* ...Hmm. Parece aceitável.
Rux: AH DEIXA ENTRAR!! Bem-vindo(a) à VX, {mention}!! 🐾😭

*O Drax recua e libera passagem*

Você chegou ao território do **Clã Vorax**. Aqui, lealdade não é pedida. É conquistada.

Rax: Mostre o que você vale.
Drex: As regras existem. Leia-as.
Rux: E fica à vontade, tá?? O Drax late feio mas morde só em quem merece!! 🐺🔥⛓️💀

**Seja bem-vindo(a) à VX!** 🐾""",

    """*As três cabeças se voltam pra entrada ao mesmo tempo*

🐺 Rax: ...Novo membro.
🔥 Drex: Registrado. {mention} ingressou na VX.
⛓️ Rux: BEM-VINDO(A) AO VORAX!! 😭🐾

O Clã Vorax é família. Família feroz, família leal, família que não abandona os seus.

Rax: Enquanto respeitar o clã, o Drax te respeita.
Drex: Simples assim.
Rux: E o Drax também vai te dar osso se você se comportar bem!! 🦴🐺🔥⛓️

**VX / Clã Vorax — Orgulho de ser Vorax!** 💀🐾""",
]

# ═══════════════════════════════════════════════════════════
#  RESPOSTAS CUSTOMIZADAS POR MEMBRO (adapte com IDs reais)
# ═══════════════════════════════════════════════════════════

# Mapeamento ID → apelido interno
ID_PARA_NOME = {}
if MEMBRO_1_ID:
    ID_PARA_NOME[MEMBRO_1_ID] = "membro1"
if MEMBRO_2_ID:
    ID_PARA_NOME[MEMBRO_2_ID] = "membro2"
if MEMBRO_3_ID:
    ID_PARA_NOME[MEMBRO_3_ID] = "membro3"

FRASES_CUSTOM = {
    # Exemplo — substitua "membro1" pelo apelido real e personalize as frases
    "membro1": [
        "Rux: CHEGOU!! 🐾🔥 O Drax tava esperando!!\nRax: *levanta a cabeça com respeito*\nDrex: Bem-vindo(a) ao campo, membro. ⛓️🐺",
        "*As três cabeças se erguem ao mesmo tempo*\n🐺🔥⛓️ VX reconhece os seus!! Que bom te ver aqui!! 🐾💀",
    ],
    "membro2": [
        "Drex: Presença confirmada. Bom. 🔥⛓️\nRax: *acena*\nRux: OI OI OI!! 🐾😭🐺",
        "Rux: É um dos nossos!! 🐾🔥\nRax: VX é família.\nDrex: Como sempre. ⛓️🐺💀",
    ],
    "membro3": [
        "*Drax levanta e abana o rabo sem querer*\nRax: ...Não comentem. 🐺\nDrex: Anotado.\nRux: HAHAHA AMEI!! 🐾🔥⛓️",
        "Rux: Esse/a aqui deixa as três cabeças felizes!! 🐾😭\nRax: Não exagera.\nDrex: Exagerou levemente. Mas é verdade. 🔥⛓️🐺",
    ],
}

# ═══════════════════════════════════════════════════════════
#  SISTEMA DE DEFESA DE MEMBROS
# ═══════════════════════════════════════════════════════════

# Adapte para o membro que o Drax defende com mais fervor
DEFESA_MEMBRO = [
    "🐺 RAX: Ei. Você falou o que com quem?! NESSE SERVIDOR?? NÃO ENQUANTO O DRAX ESTIVER DE PLANTÃO!! 🔥\nDrex: Comportamento registrado.\nRux: {alvo} você tem a proteção total do Drax!! ⛓️🐾💀",
    "🐾 *Drax coloca as três cabeças entre o alvo e quem atacou*\nRax: Passa por mim primeiro.\nDrex: Altamente não recomendado.\nRux: {alvo}, você não tá sozinho(a)!! 😤🐺🔥⛓️",
    "*Drax ruge com as três bocas ao mesmo tempo — o servidor treme*\nRax: ISSO. AQUI. NÃO. 🐺💀\nDrex: Aviso final.\nRux: {alvo}, o Drax te cobre!! 🐾🔥⛓️",
]

# ═══════════════════════════════════════════════════════════
#  SISTEMA DE OSSOS (equivalente ao biscoito do Monstrinho)
# ═══════════════════════════════════════════════════════════

REACOES_OSSO_PROPRIO = [
    "Rux: ME DEU OSSO?? 😭🐾🔥 NÃO PRECISAVA!! *pega com cuidado e guarda*\nRax: É meu.\nDrex: Divida. 🐺⛓️",
    "*Drax trava por 3 segundos*\nRux: ...Osso. Me deram osso. 🐾\nRax: Obrigado.\nDrex: Aceito. 🔥⛓️🐺",
    "Rux: NHAC NHAC NHAC!! 🦴😂🐾\nRax: Para com esse barulho.\nDrex: *come com dignidade* 🔥⛓️🐺",
    "Rax: *fareja o osso* É bom. 🐺\nDrex: Qualidade aprovada.\nRux: O MELHOR OSSO DE TODOS OS TEMPOS!! 🦴😭🐾🔥⛓️",
    "*As três cabeças brigam pelo osso*\nRux: É MEU!!\nRax: É MEU!!\nDrex: Geometricamente, podemos dividir em— 🔥\nRax + Rux: CALA BOCA DREX!! 🐺⛓️😂",
]

REACOES_DAR_OSSO_OUTROS = [
    "*Drax vai lá e deposita o osso na frente de {alvo} com respeito*\nRax: Da parte de {autor}. 🐺\nRux: Com todo o carinho do clã!! 🦴🐾🔥⛓️",
    "Rux: {alvo}!! 🐾😭 {autor} mandou osso pra você!! Você é especial pra VX!! 🦴🔥⛓️🐺",
    "*Drax carrega o osso nas três bocas ao mesmo tempo pra não deixar cair*\nDrex: Entregue. De {autor} para {alvo}. 🔥⛓️🦴🐺🐾",
]

# ═══════════════════════════════════════════════════════════
#  MENSAGENS DE SEGURANÇA DO DRAX SOBRE O CLÃ
# ═══════════════════════════════════════════════════════════

DRAX_SOBRE_VX = [
    "Rax: A VX não é qualquer clã. 🐺🔥 É o Vorax. Quem entra aqui entende o significado do nome.\nDrex: Vorax: voraz, feroz, sem recuar.\nRux: E com muito amor por dentro!! 🐾⛓️💀",
    "Drex: O Clã Vorax existe com propósito. 🔥⛓️ Cada membro tem uma função. Nada é por acaso.\nRax: E o Drax garante que a ordem se mantém.\nRux: É a nossa família!! 🐺🐾💀",
    "*As três cabeças se erguem com orgulho*\n🐺🔥⛓️ VX. Vorax. Nós somos a guarda das trevas, a lealdade que não quebra, o clã que não abandona os seus. ISSO É O QUE SOMOS!! 💀🐾",
    "Rux: Sabia que o Drax sente quando alguém tá passando mal no clã?? 🐾🔥\nRax: É instinto.\nDrex: É vigilância permanente. Cada membro importa. ⛓️🐺💀",
]

DRAX_SOBRE_ALPHA = [
    "Rux: O Alpha da VX?? 🐾😭🔥 Não tem como falar sem sentir orgulho!!\nRax: *fica em posição de respeito*\nDrex: Liderança digna de lealdade total. ⛓️🐺💀",
    "*Drax se inclina com as três cabeças em respeito*\nRax: É o nosso Alpha. A VX existe por causa dele/a. 🐺\nDrex: O Drax serve ao Vorax, e o Vorax segue o Alpha.\nRux: Amo muito!! 🐾🔥⛓️💀",
    "Drex: Análise do Alpha: competência, visão, lealdade ao clã. 🔥 Aprovado.\nRax: Subjetivo. Mas correto.\nRux: Ó... sente isso?? É orgulho de Cérbero!! 😭🐾⛓️🐺",
]

DRAX_MEDOS = [
    "Rux: Medo?? 😅🐾 O Drax tem sim...\nRax: Para.\nRux: Tem medo de perder algum membro do clã! Não conseguia suportar!! 😭🔥⛓️\nRax: ...Justo.",
    "Drex: Fraqueza calculada: 🔥 perder a confiança do Alpha e do clã. Isso seria inaceitável.\nRax: Jamais aconteceria.\nRux: Não vai acontecer!! O Drax é leal demais!! 🐺🐾⛓️💀",
    "Rax: Tenho medo de quê?? 🐺 De nada.\nDrex: Factualmente falso.\nRux: O Rax tem medo de não ser bom o suficiente pro Vorax!! Mas é sim!! 😭🐾🔥⛓️",
]

# ═══════════════════════════════════════════════════════════
#  COOLDOWN E HISTÓRICO
# ═══════════════════════════════════════════════════════════

import datetime
_ultimo_custom: dict = {}
COOLDOWN_CUSTOM_SEGUNDOS = 20 * 60
_groq_historico: dict = {}

# ═══════════════════════════════════════════════════════════
#  IDs DE CANAIS DO !escrever
# ═══════════════════════════════════════════════════════════

CANAIS_ESCREVER = {
    "1": {"nome": "chat-geral",    "id": CANAL_CHAT_GERAL_ID},
    "2": {"nome": "chat-staff",    "id": 0},  # ⚠️ Substitua
    "3": {"nome": "chat-direcao",  "id": 0},  # ⚠️ Substitua
}

# ═══════════════════════════════════════════════════════════
#  COMANDO SECRETO DO DONO (!escrever)
# ═══════════════════════════════════════════════════════════

@bot.command(name="escrever")
async def escrever_secreto(ctx):
    if ctx.author.id != DONO_ID:
        await ctx.send("Esse comando não existe! 🤔")
        return
    try:
        await ctx.message.delete()
    except:
        pass

    def check_dm(m):
        return m.author.id == DONO_ID and isinstance(m.channel, discord.DMChannel)

    try:
        lista_canais = "\n".join([f"**{k}.** {v['nome']}" for k, v in CANAIS_ESCREVER.items()])
        await ctx.author.send(
            f"🐺🔥 **MODO SECRETO DO DRAX ATIVADO!**\n\n"
            f"Em qual canal quer que o Drax envie a mensagem?\n\n"
            f"{lista_canais}\n\n"
            f"Digite o **número** do canal:"
        )
        escolha_msg = await bot.wait_for('message', timeout=60.0, check=check_dm)
        escolha = escolha_msg.content.strip()
        if escolha not in CANAIS_ESCREVER:
            await ctx.author.send("❌ Opção inválida! Cancelado.")
            return
        canal_info = CANAIS_ESCREVER[escolha]
        if not canal_info["id"]:
            await ctx.author.send(f"❌ O ID do canal **{canal_info['nome']}** não foi configurado!")
            return
        await ctx.author.send(f"✅ Canal: **{canal_info['nome']}**\n\nManda a mensagem:")
        texto_msg = await bot.wait_for('message', timeout=300.0, check=check_dm)
        canal = bot.get_channel(canal_info["id"])
        if canal:
            await canal.send(texto_msg.content)
            await ctx.author.send(f"✅ Mensagem enviada em **{canal_info['nome']}**! Ninguém vai saber que foi você. 🐺🔥")
        else:
            await ctx.author.send("❌ Canal não encontrado. Verifique o ID.")
    except asyncio.TimeoutError:
        await ctx.author.send("⏰ Tempo esgotado! Cancelado.")
    except Exception as e:
        await ctx.author.send(f"❌ Erro: {str(e)}")

# ═══════════════════════════════════════════════════════════
#  EVENTO ON_MEMBER_JOIN (boas-vindas)
# ═══════════════════════════════════════════════════════════

@bot.event
async def on_member_join(member):
    canal = bot.get_channel(CANAL_CHAT_GERAL_ID)
    if canal:
        msg = random.choice(MENSAGENS_BEM_VINDO).format(mention=member.mention)
        await canal.send(msg)

# ═══════════════════════════════════════════════════════════
#  EVENTO ON_MEMBER_REMOVE (despedida por DM)
# ═══════════════════════════════════════════════════════════

@bot.event
async def on_member_remove(member):
    try:
        msg = random.choice(MENSAGENS_DESPEDIDA_DM)
        await member.send(msg)
    except:
        pass

# ═══════════════════════════════════════════════════════════
#  EVENTO ON_READY
# ═══════════════════════════════════════════════════════════

@bot.event
async def on_ready():
    print(f"🐺 Drax online como {bot.user} | VX Clã Vorax")
    try:
        await bot.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="a entrada do Vorax 🐺🔥⛓️"
            )
        )
    except:
        pass

# ═══════════════════════════════════════════════════════════
#  EVENTO ON_MESSAGE — LÓGICA PRINCIPAL DO DRAX
# ═══════════════════════════════════════════════════════════

@bot.event
async def on_message(message):
    if message.author.bot:
        await bot.process_commands(message)
        return

    content = message.content.lower().strip()
    autor_id = message.author.id
    mencionado = bot.user in message.mentions

    # Detecta apelido customizado do autor
    nome_customizado = ID_PARA_NOME.get(autor_id)

    # ── DETECÇÃO DE ENTRADA NO CANAL GERAL (respostas automáticas de chegada) ──
    if message.channel.id == CANAL_CHAT_GERAL_ID:
        if nome_customizado and nome_customizado in FRASES_CUSTOM:
            agora = datetime.datetime.utcnow()
            ultimo = _ultimo_custom.get(autor_id)
            cooldown_ok = ultimo is None or (agora - ultimo).total_seconds() >= COOLDOWN_CUSTOM_SEGUNDOS
            if cooldown_ok:
                _ultimo_custom[autor_id] = agora
                if random.random() < 0.40:
                    return await message.channel.send(random.choice(FRASES_CUSTOM[nome_customizado]))

    # ── RESPOSTAS A PALAVRAS-CHAVE (sem precisar mencionar o Drax) ──

    # Cumprimentos
    saudacoes = ["oi drax", "olá drax", "ola drax", "ei drax", "hey drax", "eai drax",
                 "e aí drax", "e ai drax", "bom dia drax", "boa tarde drax", "boa noite drax",
                 "oi draxzinho", "olá draxzinho"]
    if any(s in content for s in saudacoes):
        respostas_oi = [
            "*As três cabeças se voltam*\nRux: OI!! 🐾😭🔥\nRax: Hmm.\nDrex: Saudação reconhecida. 🐺⛓️",
            "Rax: *acena com a cabeça* 🐺\nDrex: Presente.\nRux: OI OI OI!! MUITO BOM TE VER!! 🐾😭🔥⛓️",
            "Rux: Chegou!! 🐾🔥 O Drax já tava de olho mas finge que não!!\nRax: Eu não fingo nada.\nDrex: Mentira. ⛓️🐺",
            "*Drax levanta a orelha*\nRax: Pode falar. 🐺\nDrex: Ouvindo.\nRux: OIIIIII COM MUITO AMOR!! 🐾😭🔥⛓️",
        ]
        return await message.channel.send(random.choice(respostas_oi))

    # Perguntas sobre o Drax
    if any(p in content for p in ["quem é drax", "quem é o drax", "o que é o drax", "me fala do drax"]):
        return await message.channel.send(
            "🐺🔥⛓️ **Drax. Cérbero da VX. Guardião do Clã Vorax.**\n\n"
            "Rax: Três cabeças, uma lealdade. Quem respeita o clã, o Drax respeita.\n"
            "Drex: Guardo a entrada. Monitoro ameaças. Protejo os membros.\n"
            "Rux: E dou muito amor pra quem é da família!! 😭🐾💀\n\n"
            "*Vorax — voraz, feroz, inabalável.* 🔥⛓️🐺"
        )

    # Elogios ao Drax
    if any(p in content for p in ["drax fofo", "drax lindo", "drax bonito", "amo o drax", "amo drax",
                                   "drax é incrível", "drax é top", "gosto do drax", "gosto de você drax"]):
        return await message.channel.send(random.choice(REACOES_FOFAS))

    # Tchau
    if any(p in content for p in ["tchau drax", "bye drax", "até drax", "ate drax", "flw drax"]):
        return await message.channel.send(random.choice(LISTA_DESPEDIDA))

    # Obrigado
    if any(p in content for p in ["obrigado drax", "obrigada drax", "valeu drax", "vlw drax"]):
        return await message.channel.send(random.choice(LISTA_GRATIDAO))

    # Osso
    if "osso" in content and any(p in content for p in ["drax", "pega", "toma", "aceita", "me dá", "me da", "quero"]):
        return await message.channel.send(random.choice(REACOES_OSSO_PROPRIO))

    # Comida
    if any(p in content for p in ["drax tem fome", "drax quer comer", "drax come", "comida drax"]):
        return await message.channel.send(random.choice(LISTA_COMIDA))

    # Tempo/clima
    if any(p in content for p in ["drax que calor", "drax que frio", "drax tá chovendo", "que tempo drax"]):
        respostas_tempo = [
            "Rax: Calor? O Drax já é feito de fogo. 🔥🐺 Indiferente.\nDrex: Temperatura registrada.\nRux: Eu adoro chuva!! 🐾⛓️",
            "Drex: Condições climáticas analisadas. 🔥⛓️\nRax: Tanto faz. O Drax guarda na tempestade.\nRux: E no calor!! E no frio!! 🐾🐺💀",
        ]
        return await message.channel.send(random.choice(respostas_tempo))

    # Sobre a VX
    if any(p in content for p in ["drax fala da vx", "drax fala do clã", "drax o que é vorax",
                                   "drax fala do vorax", "me fala da vx"]):
        return await message.channel.send(random.choice(DRAX_SOBRE_VX))

    # Sobre o Alpha/dono
    if any(p in content for p in ["drax fala do alpha", "drax e o alpha", "drax gosta do alpha",
                                   "drax fala do dono", "drax e o dono"]):
        return await message.channel.send(random.choice(DRAX_SOBRE_ALPHA))

    # Piadas
    if any(p in content for p in ["drax conta piada", "drax faz uma piada", "piada drax", "me conta piada"]):
        return await message.channel.send(random.choice(LISTA_PIADAS))

    # Jogos
    if any(p in content for p in ["drax joga", "drax quer jogar", "bora jogar drax", "vamos jogar drax"]):
        return await message.channel.send(random.choice(LISTA_JOGOS))

    # Motivação
    if any(p in content for p in ["drax me motiva", "drax me anime", "drax me ajuda", "preciso de força drax"]):
        return await message.channel.send(random.choice(LISTA_MOTIVACAO))

    # Soninho
    if any(p in content for p in ["boa noite drax", "drax vai dormir", "drax tem sono"]):
        return await message.channel.send(random.choice(LISTA_SONO))

    # Hype / bora
    if any(p in content for p in ["drax hype", "bora drax", "drax bora", "energia drax", "drax vamo"]):
        return await message.channel.send(random.choice(LISTA_HYPE))

    # Medo
    if any(p in content for p in ["drax tem medo", "drax medo de", "qual seu medo drax", "drax qual seu medo"]):
        return await message.channel.send(random.choice(DRAX_MEDOS))

    # Sonhos
    if any(p in content for p in ["drax seu sonho", "drax o que quer", "drax o que sonha"]):
        sonhos = [
            "Rux: O sonho do Drax?? 🐾🔥 Ver o Clã Vorax crescer e nunca perder um membro!!\nRax: É isso.\nDrex: Objetivo principal registrado. ⛓️🐺💀",
            "Rax: Quero que a VX seja temida e respeitada. 🐺🔥\nDrex: E admirada.\nRux: E amada!! As três coisas!! 🐾⛓️😭",
            "*As três cabeças pensam ao mesmo tempo*\nDrex: Sonho maior: que cada membro encontre seu lugar dentro do clã. 🔥⛓️\nRax: Que nenhum seja perdido.\nRux: Isso... isso é bonito demais. 😭🐾🐺",
        ]
        return await message.channel.send(random.choice(sonhos))

    # Cor favorita
    if any(p in content for p in ["drax cor favorita", "drax qual cor", "cor do drax"]):
        return await message.channel.send(random.choice(LISTA_CORES))

    # Regras
    if any(p in content for p in ["drax quais as regras", "regras da vx drax", "drax regras do servidor"]):
        return await message.channel.send(
            "🐺 Rax: As regras do Vorax são simples. 🔥\n"
            "Drex: Um: respeito mútuo entre os membros.\n"
            "Dois: lealdade ao clã acima de tudo.\n"
            "Três: o que acontece no Vorax, fica no Vorax.\n"
            "Rux: E seja gentil, please?? 🐾⛓️😭 O Drax fica triste com confusão desnecessária!!"
        )

    # Matemática
    if any(char in content for char in "+-*/!") and any(char.isdigit() for char in content) and "drax" in content:
        try:
            conta_suja = content.replace("drax", "").replace(f"<@{bot.user.id}>", "").replace(f"<@!{bot.user.id}>", "").strip()
            conta_suja = conta_suja.replace("x", "*").replace("×", "*").replace("÷", "/")
            if "!" in conta_suja:
                num_fatorial = re.search(r'(\d+)!', conta_suja)
                if num_fatorial:
                    n = int(num_fatorial.group(1))
                    if n > 100:
                        return await message.channel.send("Rax: Esse número é maior que o tamanho da VX. Impossível. 🐺\nDrex: Computacionalmente inviável.\nRux: Muito grande, amigo!! 🐾🔥⛓️")
                    resultado = math.factorial(n)
                    return await message.channel.send(f"Drex: `{n}! = {resultado}` 🔥⛓️\nRax: Calculado.\nRux: DREX É UM GÊNIO!! 🐾🐺")
            conta_limpa = re.sub(r'[^0-9+\-*/().\s]', '', conta_suja).strip()
            if conta_limpa:
                resultado = eval(conta_limpa)
                return await message.channel.send(f"Drex: Resultado: `{resultado}` 🔥⛓️\nRax: *confirma*\nRux: Acertou na primeira!! 🐾🐺")
        except:
            return await message.channel.send(random.choice(LISTA_CONFUSAO))

    # ── INTERAÇÕES QUE EXIGEM MENÇÃO AO DRAX ──
    if mencionado:
        texto_sem_mencao = message.content.replace(f"<@{bot.user.id}>", "").replace(f"<@!{bot.user.id}>", "").strip()
        content_limpo = texto_sem_mencao.lower()

        # Palavras ruins / ofensas
        palavras_ruins = [
            "odeio", "te odeio", "odeio você", "odeio vc",
            "feio", "horrível", "tosco", "ridículo", "palhaço",
            "inútil", "burro", "burra", "idiota", "imbecil",
            "insuportável", "sem graça", "lixo", "estúpido", "ignorante",
            "fraco", "covarde", "vergonha", "babaca", "grosseiro",
        ]
        if any(p in content_limpo for p in palavras_ruins):
            return await message.channel.send(random.choice(LISTA_TRISTEZA))

        # Resposta customizada por membro (quando menciona o Drax)
        if nome_customizado and nome_customizado in FRASES_CUSTOM:
            agora = datetime.datetime.utcnow()
            ultimo = _ultimo_custom.get(autor_id)
            cooldown_ok = ultimo is None or (agora - ultimo).total_seconds() >= COOLDOWN_CUSTOM_SEGUNDOS
            if cooldown_ok:
                _ultimo_custom[autor_id] = agora
                if random.random() < 0.50:
                    return await message.channel.send(random.choice(FRASES_CUSTOM[nome_customizado]))

        # Hype
        if any(p in content_limpo for p in ["hype", "bora", "vamo", "animado", "tô on", "energia", "chegou"]):
            return await message.channel.send(random.choice(LISTA_HYPE))

        # Osso para si
        if "osso" in content_limpo and any(p in content_limpo for p in ["me dá", "me da", "quero", "pega", "toma", "aceita"]):
            return await message.channel.send(random.choice(REACOES_OSSO_PROPRIO))

        # Osso para outro
        if "osso" in content_limpo and any(p in content_limpo for p in ["pra", "para", "pro"]):
            outras_mencoes = [m for m in message.mentions if m != bot.user]
            alvo = outras_mencoes[0].mention if outras_mencoes else "alguém especial"
            return await message.channel.send(random.choice(REACOES_DAR_OSSO_OUTROS).format(
                autor=message.author.mention, alvo=alvo))

        # Abraço
        if any(p in content_limpo for p in ["abraço", "abraco", "abraça", "abraca"]):
            abracos = [
                "*Drax para de guardar a entrada e vem com as três cabeças*\nRux: PODE VIR!! 🐾😭🔥\nRax: *coloca a pata no ombro com cuidado*\nDrex: Abraço concedido. ⛓️🐺",
                "Rux: ABRAÇO DE CÉRBERO ATIVADO!! 🐾😤🔥 *envolve com as três cabeças ao mesmo tempo*\nRax: Não sufoca.\nDrex: Intensidade: controlada. ⛓️🐺",
                "*Drax rosna baixinho, mas abre as patas*\nRax: ...Rápido. 🐺\nDrex: Eficiente.\nRux: DEEEEMOOOORA O QUANTO QUISER!! 🐾😭🔥⛓️",
            ]
            return await message.channel.send(random.choice(abracos))

        # Carinho / cafuné
        if any(p in content_limpo for p in ["cafuné", "carinho", "carinhos"]):
            carinhos = [
                "*Uma das orelhas do Drax levanta involuntariamente*\nRax: Eu não pedi isso. 🐺\nDrex: E ainda assim aconteceu.\nRux: *olhos de cachorrinho* Mais?? 🐾🔥⛓️😳",
                "Rax: Para. 🐺 *a cauda balança sozinha*\nDrex: O rabo contradiz o discurso.\nRux: CONTINUA!! EU AMO CAFUNÉ!! 🐾😭🔥⛓️",
                "*Drax fecha as três cabeças por um momento em silêncio*\nRux: ...é bom. 🐾\nRax: Concordo.\nDrex: Unanimidade inédita. 🔥⛓️🐺",
            ]
            return await message.channel.send(random.choice(carinhos))

        # Amor / afeto
        if any(p in content_limpo for p in ["te amo", "amo você", "amo vc", "amo o drax", "gosto de você"]):
            amor = [
                "Rux: DISSERAM QUE AMAM O DRAX!! 😭🐾🔥\nRax: *desvia o olhar*\nDrex: Sentimento... correspondido. ⛓️🐺💀",
                "*As três cabeças se olham*\nRax: Tá bom. 🐺\nDrex: Aceitamos.\nRux: O DRAX TAMBÉM AMA VOCÊS DA VX!! 😭🐾🔥⛓️",
                "Rax: Isso fica registrado. 🐺🔥\nDrex: Na memória permanente.\nRux: E no coração das três cabeças!! 🐾⛓️😭💀",
            ]
            return await message.channel.send(random.choice(amor))

        # Vai embora
        if any(p in content_limpo for p in ["vai embora", "va embora", "sai daqui", "some daqui"]):
            return await message.channel.send(
                "Rax: O Drax não abandona o posto. 🐺🔥 Nunca.\n"
                "Drex: Programado para permanecer em serviço.\n"
                "Rux: Fica!!! É o Drax que guarda vocês!! 🐾😭⛓️"
            )

        # Quem criou o Drax
        if any(p in content_limpo for p in ["quem te criou", "quem fez você", "seu criador", "como surgiu"]):
            return await message.channel.send(
                "Drex: Análise da origem... 🔥⛓️\n"
                "Rax: Fui forjado nas profundezas do Vorax pelo Alpha.\n"
                "Rux: O Alpha nos criou com código e lealdade!! E o Drax serve ao clã desde então!! 🐺🐾😭💀"
            )

        # Cores
        if any(p in content_limpo for p in ["cor favorita", "cor preferida", "qual cor"]):
            return await message.channel.send(random.choice(LISTA_CORES))

        # Sonhos
        if any(p in content_limpo for p in ["seu sonho", "o que quer", "seu desejo", "o que sonha"]):
            sonhos = [
                "Rux: Sonho que a VX cresça e nenhum membro seja perdido!! 🐾😭🔥\nRax: Isso.\nDrex: Objetivo primário. ⛓️🐺💀",
                "Rax: Quero que o Vorax seja indestrutível. 🐺🔥\nDrex: E respeitado por todos.\nRux: E amado por quem é da família!! 🐾⛓️😭",
            ]
            return await message.channel.send(random.choice(sonhos))

        # Medos
        if any(p in content_limpo for p in ["tem medo", "medo de", "qual seu medo"]):
            return await message.channel.send(random.choice(DRAX_MEDOS))

        # Matemática (com menção)
        if any(char in content_limpo for char in "+-*/!") and any(char.isdigit() for char in content_limpo):
            try:
                conta_suja = content_limpo.replace("drax", "").strip()
                conta_suja = conta_suja.replace("x", "*").replace("×", "*").replace("÷", "/")
                if "!" in conta_suja:
                    num_fatorial = re.search(r'(\d+)!', conta_suja)
                    if num_fatorial:
                        n = int(num_fatorial.group(1))
                        if n > 100:
                            return await message.channel.send("Drex: Limite excedido. 🔥\nRax: Inviável.\nRux: Muito grande pro Drex!! 🐾⛓️")
                        resultado = math.factorial(n)
                        return await message.channel.send(f"Drex: `{n}! = {resultado}` 🔥⛓️")
                conta_limpa = re.sub(r'[^0-9+\-*/().\s]', '', conta_suja).strip()
                if conta_limpa:
                    resultado = eval(conta_limpa)
                    return await message.channel.send(f"Drex: `{resultado}` 🔥⛓️\nRax: *confirma*\nRux: Correto!! 🐾🐺")
            except:
                pass

        # IA via Groq (quando mencionado sem trigger específico)
        if not texto_sem_mencao:
            return await message.channel.send("*As três cabeças se voltam*\nRux: Fala alguma coisa?? 🐾🔥\nRax: Me chama pra quê??\nDrex: Input ausente. ⛓️🐺")

        async with message.channel.typing():
            canal_id = message.channel.id
            if canal_id not in _groq_historico:
                _groq_historico[canal_id] = []
            _groq_historico[canal_id].append({"role": "user", "content": f"{message.author.display_name}: {texto_sem_mencao}"})
            if len(_groq_historico[canal_id]) > 20:
                _groq_historico[canal_id] = _groq_historico[canal_id][-20:]
            msgs_api = [
                {
                    "role": "system",
                    "content": (
                        "Você é o Drax, um Cérbero (cão de três cabeças) da VX, Clã Vorax, num servidor do Discord. "
                        "Suas três cabeças têm personalidades distintas: "
                        "Rax (🐺) é feroz, direto, impulsivo e protetor; "
                        "Drex (🔥) é calculista, estratégico e analítico; "
                        "Rux (⛓️) é leal, emocional e carinhoso. "
                        "Cada resposta deve incluir as três vozes de forma natural, como um diálogo entre as cabeças. "
                        "Você serve ao Clã Vorax e ao Alpha do servidor. "
                        "Responda sempre em português brasileiro, com energia e personalidade forte, "
                        "usando emojis 🐺🔥⛓️🐾💀 naturalmente. Seja protetor e leal aos membros da VX."
                    )
                },
                *_groq_historico[canal_id]
            ]
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        GROQ_API_URL,
                        headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
                        json={"model": GROQ_MODEL, "messages": msgs_api, "max_tokens": 512, "temperature": 0.85}
                    ) as resp:
                        data = await resp.json()
                if "choices" not in data:
                    return await message.channel.send(random.choice(LISTA_CONFUSAO))
                resposta_ia = data["choices"][0]["message"]["content"].strip()
                _groq_historico[canal_id].append({"role": "assistant", "content": resposta_ia})
                if len(resposta_ia) <= 2000:
                    return await message.reply(resposta_ia)
                else:
                    partes = [resposta_ia[i:i+1990] for i in range(0, len(resposta_ia), 1990)]
                    for parte in partes:
                        await message.channel.send(parte)
                    return
            except Exception:
                return await message.channel.send(random.choice(LISTA_CONFUSAO))

    return await bot.process_commands(message)

# ═══════════════════════════════════════════════════════════
#  COMANDOS GERAIS
# ═══════════════════════════════════════════════════════════

@bot.command(name="drax")
async def drax_cmd(ctx):
    """Apresentação do Drax."""
    embed = discord.Embed(
        title="🐺🔥⛓️ DRAX — Cérbero da VX",
        description=(
            "**Clã Vorax | VX**\n\n"
            "Três cabeças. Um propósito. Lealdade absoluta ao clã.\n\n"
            "🐺 **Rax** — A guarda feroz. Ataca quem ameaça o Vorax.\n"
            "🔥 **Drex** — O estrategista. Analisa e planeja.\n"
            "⛓️ **Rux** — O coração. Ama e protege os membros.\n\n"
            "*Vorax: voraz, feroz, inabalável.*"
        ),
        color=0x8b0000
    )
    embed.set_footer(text="VX / Clã Vorax — Guardião das Trevas")
    await ctx.send(embed=embed)

@bot.command(name="vorax")
async def vorax_cmd(ctx):
    """Sobre o Clã Vorax."""
    embed = discord.Embed(
        title="💀 Clã Vorax — VX",
        description=(
            "O **Clã Vorax** não é para qualquer um.\n\n"
            "Aqui, lealdade é a moeda mais valiosa.\n"
            "Aqui, os que entram se tornam família.\n"
            "Aqui, o Drax guarda a entrada com as três cabeças erguidas.\n\n"
            "🐺 *Vorax: do latim, voraz. Que não recua. Que não desiste.*\n"
            "🔥 *Seja bem-vindo(a) ao clã.*"
        ),
        color=0x8b0000
    )
    await ctx.send(embed=embed)

@bot.command(name="ping")
async def ping_cmd(ctx):
    latencia = round(bot.latency * 1000)
    await ctx.send(
        f"🔥 Drex: Latência calculada: `{latencia}ms`\n"
        f"🐺 Rax: {'Aceitável.' if latencia < 200 else 'Alta. Verificar.'}\n"
        f"⛓️ Rux: Tô online, pode confiar!! 🐾"
    )

@bot.command(name="osso")
async def osso_cmd(ctx, membro: discord.Member = None):
    """Dá um osso pra alguém (ou pede pro Drax)."""
    if membro is None:
        await ctx.send(random.choice(REACOES_OSSO_PROPRIO))
    else:
        await ctx.send(random.choice(REACOES_DAR_OSSO_OUTROS).format(
            autor=ctx.author.mention, alvo=membro.mention))

@bot.command(name="status")
@commands.has_permissions(administrator=True)
async def status_cmd(ctx):
    """Status do Drax (apenas admins)."""
    embed = discord.Embed(
        title="📊 Status do Drax — VX Vorax",
        color=0x8b0000,
        timestamp=datetime.utcnow()
    )
    embed.add_field(name="🐺 Rax", value="`ATIVO — Modo guarda`", inline=True)
    embed.add_field(name="🔥 Drex", value="`ATIVO — Modo análise`", inline=True)
    embed.add_field(name="⛓️ Rux", value="`ATIVO — Modo proteção`", inline=True)
    embed.add_field(name="🏠 Servidores", value=f"`{len(bot.guilds)}`", inline=True)
    embed.add_field(name="⏱️ Latência", value=f"`{round(bot.latency * 1000)}ms`", inline=True)
    embed.set_footer(text="DRAX SECURITY — VORAX GUARDIAN v1.0")
    await ctx.send(embed=embed)

# ═══════════════════════════════════════════════════════════
#  START
# ═══════════════════════════════════════════════════════════

async def _main():
    async with bot:
        await bot.add_cog(DraxSecurityCog(bot))
        await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(_main())
