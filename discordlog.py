# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime
from config import TOKEN  # Импортируем TOKEN из config.py

# Создайте экземпляр клиента
intents = discord.Intents.all()  # Включаем все намерения, чтобы бот мог отслеживать все действия
bot = commands.Bot(command_prefix='!', intents=intents)

# Настройки отслеживаемых событий
event_settings = {
    'member_join': True,
    'member_remove': True,
    'member_update': True,
    'voice_state_update': True,
    'channel_create': True,
    'channel_delete': True,
    'channel_update': True,
    'invite_create': True,
    'member_kick': True,
    'member_mute': True,
    'member_unmute': True,
    'first_time_join': True  # Новое событие
}

log_channels = {}
initial_setup_done = {}
first_time_members = {}  # Словарь для отслеживания первых подключений

def get_current_time():
    now = datetime.now()
    return now.strftime("%Y-%m-%d %H:%M:%S")

class SettingsView(discord.ui.View):
    def __init__(self):
        super().__init__()
        self.update_options()

    def update_options(self):
        options = []
        for event, status in event_settings.items():
            label = event.replace('_', ' ').title()
            status_label = 'On' if status else 'Off'
            options.append(discord.SelectOption(label=f'{label} ({status_label})', value=event))

        select = discord.ui.Select(placeholder='Select events to toggle', options=options, custom_id='select_event')
        select.callback = self.select_callback
        self.clear_items()
        self.add_item(select)

    async def select_callback(self, interaction):
        selected_event = interaction.data['values'][0]
        event_settings[selected_event] = not event_settings[selected_event]
        self.update_options()
        await interaction.response.edit_message(view=self)
        status_label = 'On' if event_settings[selected_event] else 'Off'
        await interaction.followup.send(f'{selected_event.replace("_", " ").title()} is now {status_label}')

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')

    # Заполнение словаря first_time_members текущими пользователями
    for guild in bot.guilds:
        first_time_members[guild.id] = set(member.id for member in guild.members)

    await bot.tree.sync()


@bot.event
async def on_guild_join(guild):
    await guild.system_channel.send(
        "Please configure the bot using the command: `/setchannellog`"
    )
    # Инициализация словаря для нового сервера
    first_time_members[guild.id] = set(member.id for member in guild.members)


@bot.event
async def on_member_join(member):
    log_channel = log_channels.get(member.guild.id)
    if event_settings['member_join'] and log_channel:
        await log_channel.send(f'[{get_current_time()}] <@{member.id}> has joined the server.')

    # Проверка первого подключения по приглашению
    if member.guild.id not in first_time_members:
        first_time_members[member.guild.id] = set()

    if member.id not in first_time_members[member.guild.id]:
        first_time_members[member.guild.id].add(member.id)
        if event_settings['first_time_join'] and log_channel:
            await log_channel.send(f'[{get_current_time()}] <@{member.id}> has joined the server for the first time.')

    # Отслеживание подключения по приглашению
    invites_before = await member.guild.invites()
    await bot.wait_until_ready()
    invites_after = await member.guild.invites()
    for invite in invites_before:
        if invite.uses < [inv for inv in invites_after if inv.code == invite.code][0].uses:
            await log_channel.send(
                f'[{get_current_time()}] <@{member.id}> joined the server using invite from <@{invite.inviter.id}>')
            break


@bot.event
async def on_member_remove(member):
    log_channel = log_channels.get(member.guild.id)
    if event_settings['member_remove'] and log_channel:
        try:
            async for entry in member.guild.audit_logs(action=discord.AuditLogAction.kick, limit=1):
                if entry.target.id == member.id:
                    await log_channel.send(
                        f'[{get_current_time()}] <@{member.id}> was kicked from the server by <@{entry.user.id}>.')
                    return
            async for entry in member.guild.audit_logs(action=discord.AuditLogAction.ban, limit=1):
                if entry.target.id == member.id:
                    await log_channel.send(
                        f'[{get_current_time()}] <@{member.id}> was banned from the server by <@{entry.user.id}>.')
                    return
            await log_channel.send(f'[{get_current_time()}] <@{member.id}> has left the server.')
        except discord.errors.Forbidden:
            await log_channel.send(
                f'[{get_current_time()}] <@{member.id}> has left the server. (Unable to access audit logs)')


@bot.event
async def on_member_update(before, after):
    log_channel = log_channels.get(before.guild.id)
    if event_settings['member_update']:
        changes = []
        if before.nick != after.nick:
            changes.append(f'Nickname changed from {before.nick} to {after.nick}')
        if before.roles != after.roles:
            added_roles = [role.name for role in after.roles if role not in before.roles]
            removed_roles = [role.name for role in before.roles if role not in after.roles]
            if added_roles:
                changes.append(f'Roles added: {", ".join(added_roles)}')
            if removed_roles:
                changes.append(f'Roles removed: {", ".join(removed_roles)}')
        if changes and log_channel:
            await log_channel.send(f'[{get_current_time()}] <@{before.id}> has been updated: ' + ', '.join(changes))

        # Отслеживание отключения и включения микрофона другим пользователем
        if before.mute != after.mute:
            mute_status = "muted" if after.mute else "unmuted"
            try:
                async for entry in before.guild.audit_logs(action=discord.AuditLogAction.member_update):
                    if entry.target.id == before.id and entry.before.mute != entry.after.mute:
                        if mute_status == "unmuted":
                            event = "unmute"
                        else:
                            event = "mute"
                        await log_channel.send(
                            f'[{get_current_time()}] <@{before.id}> was {event} by <@{entry.user.id}>')
                        break
            except discord.errors.Forbidden:
                await log_channel.send(f'[{get_current_time()}] Bot does not have permission to view audit logs.')


@bot.event
async def on_voice_state_update(member, before, after):
    log_channel = log_channels.get(member.guild.id)
    changes = []

    # Проверка изменения голосового канала
    if event_settings['voice_state_update'] and before.channel != after.channel:
        before_channel_name = before.channel.name if before.channel else 'None'
        before_channel_id = before.channel.id if before.channel else None
        after_channel_name = after.channel.name if after.channel else 'None'
        after_channel_id = after.channel.id if after.channel else None

        before_channel_link = f'<#{before_channel_id}>' if before_channel_id else before_channel_name
        after_channel_link = f'<#{after_channel_id}>' if after.channel else after_channel_name

        changes.append(f'Voice channel changed from {before_channel_link} to {after_channel_link}')

    # Отслеживание отключения микрофона другим пользователем
    if (event_settings['member_mute'] or event_settings['member_unmute']) and before.mute != after.mute:
        mute_status = "muted" if after.mute else "unmuted"
        if after.mute:
            event = "mute"
        else:
            event = "unmute"
        try:
            async for entry in member.guild.audit_logs(action=discord.AuditLogAction.member_update):
                if entry.target.id == member.id and entry.before.mute != entry.after.mute:
                    changes.append(f'<@{member.id}> was {event} by <@{entry.user.id}>')
                    break
        except discord.errors.Forbidden:
            changes.append(f'[{get_current_time()}] Bot does not have permission to view audit logs.')

    # Запись изменений
    if changes and log_channel:
        await log_channel.send(f'[{get_current_time()}] ' + ', '.join(changes))


@bot.event
async def on_guild_channel_create(channel):
    log_channel = log_channels.get(channel.guild.id)
    if event_settings['channel_create'] and log_channel:
        await log_channel.send(f'[{get_current_time()}] Channel created: <#{channel.id}>')


@bot.event
async def on_guild_channel_delete(channel):
    log_channel = log_channels.get(channel.guild.id)
    if event_settings['channel_delete'] and log_channel:
        await log_channel.send(f'[{get_current_time()}] Channel deleted: {channel.name}')


@bot.event
async def on_guild_channel_update(before, after):
    log_channel = log_channels.get(before.guild.id)
    if event_settings['channel_update'] and log_channel:
        changes = []
        if before.name != after.name:
            changes.append(f'Name changed from {before.name} to {after.name}')
        if before.position != after.position:
            changes.append(f'Position changed from {before.position} to {after.position}')
        if before.category != after.category:
            before_category = before.category.name if before.category else 'None'
            after_category = after.category.name if after.category else 'None'
            changes.append(f'Category changed from {before_category} to {after_category}')
        if before.topic != after.topic:
            before_topic = before.topic if before.topic else 'None'
            after_topic = after.topic if after.topic else 'None'
            changes.append(f'Topic changed from {before_topic} to {after_topic}')
        if before.slowmode_delay != after.slowmode_delay:
            changes.append(f'Slowmode delay changed from {before.slowmode_delay} to {after.slowmode_delay} seconds')
        if changes:
            await log_channel.send(f'[{get_current_time()}] Channel updated: <#{before.id}> -> ' + ', '.join(changes))


@bot.event
async def on_invite_create(invite):
    log_channel = log_channels.get(invite.guild.id)
    if event_settings['invite_create'] and log_channel:
        await log_channel.send(f'[{get_current_time()}] Invite created: {invite.url} by <@{invite.inviter.id}>')


@bot.event
async def on_member_kick(guild, user):
    log_channel = log_channels.get(guild.id)
    if event_settings['member_kick'] and log_channel:
        await log_channel.send(f'[{get_current_time()}] <@{user.id}> was kicked from the server.')


@bot.tree.command(name="botsettings")
async def botsettings(interaction: discord.Interaction):
    """Настройки событий бота."""
    view = SettingsView()
    await interaction.response.send_message('Bot settings:', view=view, ephemeral=True)


@bot.tree.command(name="setchannellog")
@app_commands.describe(log_channel="Select the channel for logging events")
async def setchannellog(interaction: discord.Interaction, log_channel: discord.TextChannel):
    """Установить канал для логирования событий."""
    member = interaction.guild.get_member(interaction.user.id)
    permissions = log_channel.permissions_for(member)
    if not permissions.view_channel:
        await interaction.response.send_message(
            f'[{get_current_time()}] You do not have permission to set this channel.', ephemeral=True)
        return

    log_channels[interaction.guild.id] = log_channel
    await interaction.response.send_message(f'[{get_current_time()}] Log channel set to {log_channel.mention}',
                                            ephemeral=True)


@bot.tree.command(name="allcommands")
async def custom_help(interaction: discord.Interaction):
    """Выводит список всех команд и их описание."""
    help_text = """
    **Команды бота:**
    `/botsettings` - Настройки событий бота.
    `/setchannellog` - Установить канал для логирования событий.
    `/allcommands` - Выводит список всех команд и их описание.
    """
    await interaction.response.send_message(help_text, ephemeral=True)


# Запуск бота
bot.run(TOKEN)