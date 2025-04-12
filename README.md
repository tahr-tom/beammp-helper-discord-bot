# Discord bot for managing BeamMP server

## Features

- show current map
- change map
- force reload maps source JSON (auto reload with 5 mins interval)

## Requirements

1. .env file which includes

- `DISCORD_BOT_TOKEN`: your own bot token
- `MAPS_JSON_URL`: points to a JSON file with following format
   ```json
   {
     "nurburgring": {
       "label": "Nurburgring",
       "value": "/levels/ks_nord/info.json",
       "image": "http://foo.bar.png"
     },
     "c1": {
       "label": "Tokyo Shuto Expressway",
       "value": "/levels/c1/info.json",
       "image": "http://foo.bar.png"
     }
   }
   ```

2. install dependencies with `pip install -r requirements.txt`

3. In Discord Applications -> Settings -> Bot, Enable
    - Server Members Intent
    - Message Content Intent

## Roles

Configure your server with following roles

- `beammp_users`
- `beamp_admin`

## Commands & Permissions

- `show-map`: `beammp_users`, `beammp_admin`
- `set-current-map`: `beammp_users`, `beammp_admin`
- `reload-maps`: `beammp_admin`