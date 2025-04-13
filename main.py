import asyncio
import toml
import discord
from discord.ext import commands, tasks
import subprocess
import shutil
import re
from datetime import datetime
from dotenv import load_dotenv
import os
import sys
import requests

# === CONFIG ===
COMPOSE_FILE_PATH = "/opt/docker/beammp-server/compose.yml"
BACKUP_PATH = "/opt/docker/beammp-server/compose.yml.bak"
COMPOSE_DIR = "/opt/docker/beammp-server"
CONTAINER_NAME = "beammp-server"
ENV_VAR_NAME = "BEAMMP_MAP"
SERVER_CONFIG_PATH = "/opt/docker/beammp-server/ServerConfig.toml"

# Load environment variables from .env file
load_dotenv()

# Load bot token from environment variable
MAPS_JSON_URL = os.getenv("MAPS_JSON_URL")
BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
REFRESH_INTERVAL_MINUTES = 5

# Validate required environment variables
if not BOT_TOKEN:
    print("❌ Error: DISCORD_TOKEN is not set in the .env file.")
    sys.exit(1)

if not MAPS_JSON_URL:
    print("❌ Error: MAPS_JSON_URL is not set in the .env file.")
    sys.exit(1)

MAP_CHOICES = {}


# Load map list from URL
def fetch_maps_from_url():
    try:
        response = requests.get(MAPS_JSON_URL, timeout=5)
        response.raise_for_status()
        print(f"[Map Sync] Map list refreshed from URL. {len(response.json())} maps loaded")
        return response.json()
    except requests.RequestException as e:
        print(f"[Map Sync] Request error while fetching map list: {e}")
    except Exception as e:
        print(f"[Map Sync] Unexpected error: {e}")
    return {}


# Periodic refresh loop
@tasks.loop(minutes=REFRESH_INTERVAL_MINUTES)
async def refresh_map_list():
    global MAP_CHOICES
    MAP_CHOICES = fetch_maps_from_url()


intents = discord.Intents.default()
intents.guilds = True
intents.members = True
bot = commands.Bot(intents=intents)


# === VIEWS ===
class MapDropdown(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.message = None  # Will be set after sending
        options = [
            discord.SelectOption(label=info["label"], value=key)
            for key, info in MAP_CHOICES.items()
        ]
        self.add_item(MapSelector(options, self))  # Pass view to the select

    def disable_all_items(self):
        for item in self.children:
            item.disabled = True


class MapSelector(discord.ui.Select):
    def __init__(self, options, parent_view):
        super().__init__(placeholder="Select a map to apply", options=options)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        selected_key = self.values[0]
        map_info = MAP_CHOICES[selected_key]
        new_value = map_info["value"]
        author = interaction.user.display_name
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Disable all items in the view (like the dropdown)
        self.parent_view.disable_all_items()

        # Immediately disable dropdown in the original message
        if self.parent_view.message:
            await self.parent_view.message.edit(view=self.parent_view)

        # Acknowledge early
        await interaction.response.send_message("Processing your map update...", ephemeral=True)

        # Run the update task
        asyncio.create_task(self.update_docker_compose(interaction, new_value, author, timestamp))

    async def update_docker_compose(self, interaction: discord.Interaction, new_value: str, author: str,
                                    timestamp: str):
        try:
            # Save backup and update the compose file...
            shutil.copy(COMPOSE_FILE_PATH, BACKUP_PATH)
            with open(COMPOSE_FILE_PATH, "r") as f:
                lines = f.readlines()

            updated = False
            for i, line in enumerate(lines):
                match = re.match(rf"(\s*-?\s*){re.escape(ENV_VAR_NAME)}=", line)
                if match:
                    leading_whitespace = match.group(1)
                    lines[i] = f"{leading_whitespace}{ENV_VAR_NAME}={new_value}  # Updated by {author} on {timestamp}\n"
                    updated = True
                    break

            if not updated:
                await interaction.followup.send(f"Couldn't find `{ENV_VAR_NAME}` in the file.", ephemeral=True)
                return

            with open(COMPOSE_FILE_PATH, "w") as f:
                f.writelines(lines)

            subprocess.run("docker compose down", cwd=COMPOSE_DIR, shell=True, check=True)
            subprocess.run("docker compose up -d", cwd=COMPOSE_DIR, shell=True, check=True)

            result = subprocess.run("docker ps --format '{{.Names}}'", shell=True, capture_output=True, text=True)
            running = result.stdout.strip().split("\n")
            if not any(CONTAINER_NAME in c for c in running):
                shutil.copy(BACKUP_PATH, COMPOSE_FILE_PATH)
                subprocess.run("docker compose down", cwd=COMPOSE_DIR, shell=True, check=True)
                subprocess.run("docker compose up -d", cwd=COMPOSE_DIR, shell=True, check=True)

                await interaction.followup.send(
                    f"⚠️ Update failed. Rolled back. Container **{CONTAINER_NAME}** not running.",
                    ephemeral=True
                )
                return

            # Get label
            label_name = next((info["label"] for info in MAP_CHOICES.values() if info["value"] == new_value), new_value)

            # Update the original dropdown message to remove view
            if self.parent_view.message:
                await self.parent_view.message.edit(content=f"✅ Set map to **{label_name}**.", view=None)

            await interaction.followup.send("Map updated and container is running! ✅", ephemeral=True)

        except Exception as e:
            await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)


# Get the current map path from the ServerConfig.toml file
def get_current_map_path():
    try:
        config = toml.load(SERVER_CONFIG_PATH)
        return config.get("General", {}).get("Map")
    except Exception as e:
        print(f"Error reading TOML: {e}")
        return None


# === COMMANDS ===
@bot.event
async def on_ready():
    print(f"✅ Bot is online as {bot.user}")
    refresh_map_list.start()

    # Initial fetch
    global MAP_CHOICES
    MAP_CHOICES = fetch_maps_from_url()
    if not MAP_CHOICES:
        print("⚠️ Warning: MAP_CHOICES is empty after initial fetch.")


@bot.slash_command(name="set-map", description="Set BEAMMP_MAP from a list of maps")
async def set_map(ctx: discord.ApplicationContext):
    allowed_roles = {"beammp_admin", "beammp_users"}
    if not any(role.name in allowed_roles for role in ctx.author.roles):
        await ctx.respond("🚫 You don't have the required role.", ephemeral=True)
        return

    view = MapDropdown()
    msg = await ctx.respond("Choose a map:", view=view)
    view.message = await msg.original_response()


@bot.slash_command(name="show-current-map", description="Show the currently set map info")
async def show_current_map(interaction: discord.Interaction):
    allowed_roles = {"beammp_admin", "beammp_users"}
    if not any(role.name in allowed_roles for role in interaction.user.roles):
        await interaction.response.send_message("🚫 You don't have the required role.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    current_map_path = get_current_map_path()

    if not current_map_path:
        await interaction.followup.send("⚠️ Could not retrieve the current map from the server config.", ephemeral=True)
        return

    selected_entry = None
    for label, data in MAP_CHOICES.items():
        if data["value"] == current_map_path:
            selected_entry = {"label": label, **data}
            break

    if selected_entry:
        embed = discord.Embed(
            title=f"Current Map: {selected_entry['label']}",
            color=discord.Color.blurple()
        )
        embed.set_image(url=selected_entry["image"])
        await interaction.followup.send(embed=embed)
    else:
        await interaction.followup.send(
            f"Current map path: `{current_map_path}` (not found in map list)",
            ephemeral=True
        )


@bot.slash_command(name="reload-maps", description="Manually reload the map list from the remote URL")
async def reload_maps(interaction: discord.Interaction):
    allowed_roles = {"beammp_admin"}
    if not any(role.name in allowed_roles for role in interaction.user.roles):
        await interaction.response.send_message("🚫 You don't have the required role.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    global MAP_CHOICES
    new_maps = fetch_maps_from_url()

    if new_maps:
        MAP_CHOICES = new_maps
        await interaction.followup.send(f"✅ Map list reloaded. Loaded {len(MAP_CHOICES)} maps.")
    else:
        await interaction.followup.send("⚠️ Failed to reload map list.")


# === START BOT ===
bot.run(BOT_TOKEN)
