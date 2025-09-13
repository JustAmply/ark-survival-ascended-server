# ARK: Survival Ascended Server - Detailed Setup Guide

This guide provides comprehensive instructions for setting up and configuring ARK: Survival Ascended dedicated servers using Docker.

## Table of Contents

- [Hardware Requirements](#hardware-requirements)
- [Installation](#installation)
- [Server Configuration](#server-configuration)
- [Port Configuration](#port-configuration)
- [Server Administration](#server-administration)
- [Cluster Setup](#cluster-setup)
- [Mod Management](#mod-management)
- [Plugin Support](#plugin-support)
- [Map Information](#map-information)
- [Container Updates](#container-updates)

## Hardware Requirements

The hardware requirements might change over time, but as of today you can expect:

* ~13 GB RAM usage per server instance
* ~31 GB disk space (the server files alone, without any savegames)

I cannot tell you what CPU to use, as I didn't do any testing on this, but this is the hardware I'm running one ASA server on:

* Intel Xeon E3-1275v5
* 2x SSD M.2 NVMe 512 GB
* 4x RAM 16384 MB DDR4 ECC

The server runs next to other services and it runs pretty well.

## Installation

Required Linux experience: **Beginner**

In theory, you can use these steps on any Linux system where Docker is installed. It has been tested with:

* openSUSE Leap 15.6
* Debian 12 (bookworm)
* **NOT WORKING:** Ubuntu 22.04.x LTS (Jammy Jellyfish) [As of March 28th 2025, a recent distro update causes the container to have a constant high CPU usage, well beyond 400% and the server won't launch. Use Ubuntu 24.04.x if you can]
* Ubuntu 24.04.1 (Noble Numbat)

You need to be root user (`su root`) to perform these steps, but don't worry, the ASA server itself will run rootless.

### 1. Install Docker & Docker Compose

#### openSUSE Leap 15.6:

```
zypper in -y docker docker-compose
```

#### Debian 12

It is recommended to install the docker engine from Docker's official repository. Follow the instructions in [this guide](https://docs.docker.com/engine/install/debian/#install-using-the-repository)
and refer to the "Install using the apt repository" section.

#### Ubuntu (24.04.x):

The docker engine is not part of the official Ubuntu 24.x repositories, thus you need to install it from the Docker's repository instead. Please refer to
[this guide](https://docs.docker.com/engine/install/ubuntu/#install-using-the-repository) and follow the steps outlined in the "Install using the apt repository" section.

### 2. Start docker daemon

```
systemctl start docker
systemctl enable docker
```

### 3. Create the Docker Compose config

Create a directory called `asa-server` wherever you like and download [my docker-compose.yml](https://github.com/justamply/ark-survival-ascended-linux-container-image/blob/main/docker-compose.yml) example.

```
mkdir asa-server
cd asa-server
wget https://raw.githubusercontent.com/justamply/ark-survival-ascended-linux-container-image/main/docker-compose.yml
```

### 4. First server start

Now start the server for the first time. It will install Steam, Proton, and downloads the ARK: Survival Ascended server files.

Go to the directory of your `docker-compose.yml` file and execute the following command:

```
docker compose up -d
```

It will download my docker image and then spins up a container called `asa-server-1` (defined in `docker-compose.yml`). You can follow the installation and the start of your server by running:

```
docker logs -f asa-server-1
```

(Note: You can safely run `CTRL + C` to exit the log window again without causing the server to stop)

Once the log shows the following line:

```
Starting the ARK: Survival Ascended dedicated server...
```

... the server should be reachable and discoverable through the server browser in ~2-5 minutes.

#### Note on Proton download and checksum verification

On first run, the container downloads a GE-Proton release from the official repository to run the Windows server under Linux.
The script downloads the release's `GE-Proton<version>.sha512sum` file and verifies with `sha512sum -c`

If both checks are unavailable or fail and you still want to proceed, you may set `PROTON_SKIP_CHECKSUM=1` in the container environment as a last resort. This is not recommended; use it only temporarily if the release assets are in flux.

You can pin a specific Proton version via the `PROTON_VERSION` environment variable (for example `9-17`). If omitted, the script tries to auto-detect the latest GE-Proton tag via the GitHub API, then falls back to a built-in default.

The server name is randomly generated upon the first start. Please execute the following command to see under which name the server is discoverable in the server browser:
```
docker exec asa-server-1 cat server-files/ShooterGame/Saved/Config/WindowsServer/GameUserSettings.ini | grep SessionName
```

If the command fails in execution and reports an `No such file or directory` error, just wait some more minutes and it should eventually work. Once the command executed successfully, it should output something like this:
```
SessionName=ARK #334850
```

Now try to find the server by its name. Just search in the "Unofficial" section in ASA for the number of the server. In my case it is `334850`. If you are not able to connect to it right away, wait up to 5 more minutes and
try it again. If it's still not possible, [open an issue on GitHub](https://github.com/justamply/ark-survival-ascended-linux-container-image/issues/new) to get help.

Once confirmed that you are able to connect, stop the server again:

```
docker stop asa-server-1
```

## Server Configuration

### File Locations

The `docker-compose.yml` config defines three docker volumes, which serve as a storage for your server files, Steam, and Proton. They are directly mounted to the docker container and can be edited outside of the container. The
location of these volumes is `/var/lib/docker/volumes`. If you followed the steps 1:1, then you should find the following directories at that location:

```
asa-server_cluster-shared/
asa-server_server-files-1/
asa-server_steam-1/
asa-server_steamcmd-1/
```

The prefix `asa-server` is defined by the directory name of your `docker-compose.yml` file.

You can ignore `asa-server_steam-1` and `asa-server_steamcmd-1`, these volumes are being used by the container to avoid setting up `Steam` and `steamcmd` on every launch again. Server files including config files are stored at `asa-server_server-files-1`. `asa-server_cluster-shared` provides support for server clusters, so that survivors can travel between your servers with their characters and dinos.

The `GameUserSettings.ini` and `Game.ini` file can be found at `/var/lib/docker/volumes/asa-server_server-files-1/_data/ShooterGame/Saved/Config/WindowsServer`. The `Game.ini` file is not there by default, so you might want to create it yourself.

You don't need to worry about file permissions. The container now adjusts the file permissions automatically at startup and then drops privileges to the `gameserver` user (`25000:25000`). These ids are not bound to any user on your system and that's fine and not an issue.

### Changing Start Parameters and Player Limit

Start parameters are defined in the `docker-compose.yml`:

```yml
...
    environment:
      - ASA_START_PARAMS=TheIsland_WP?listen?Port=7777?RCONPort=27020?RCONEnabled=True -WinLiveMaxPlayers=50
...
```

Please note:
* The value before `?listen` is the name of the map the server launches with. ([See all official map names](#map-names))
* Please do not remove `?listen` from the parameters, otherwise the server is not binding ports
* `?Port=` is the server port players connect to
* `?RCONPort=` is the port of the RCON server that allows remote administration of the server
* The player limit is set by `-WinLiveMaxPlayers`. Please note that for ASA servers, editing the player limit via `GameUserSettings.ini` is not working.

## Port Configuration

### Port Forwarding

There should not be the need to forward any ports if your server runs in a public cloud. This is because docker configures `iptables` by itself. In a home setup, where a router is in between, it is very likely that you need to forward ports.

In any case, you ONLY need to forward the following ports:

```
7777 (UDP only - This is the game port to allow players to connect to the server)
27020 (TCP only - This is the port to connect through RCON and is therefore optional to forward)
```

As of today, ASA does no longer offer a way to query the server, so there's no query port and you won't be able to find your server through the Steam server browser, only via the ingame browser.

### Changing Game Port and RCON Port

You already learned that ports are defined by `ASA_START_PARAMS` in the `docker-compose.yml` file. This just tells the ASA server what ports to bind.
As a first step for port changes adjust the start parameters accordingly.

E. g. if you want to change the game port from `7777` to `7755` your new start parameters would look like this:

```yml
...
    environment:
      - ASA_START_PARAMS=TheIsland_WP?listen?Port=7755?RCONPort=27020?RCONEnabled=True -WinLiveMaxPlayers=50 -clusterid=default -ClusterDirOverride="/home/gameserver/cluster-shared"
      - ENABLE_DEBUG=0
...
```

But this alone is not enough and you need to apply the following changes as well.

Open the `docker-compose.yml` file again and edit the lines where the container ports are defined:

```yml
...
    ports:
      # Game port for player connections through the server browser
      - 0.0.0.0:7777:7777/udp
      # RCON port for remote server administration
      - 0.0.0.0:27020:27020/tcp
...
```

Adjust the port to your liking, but make sure that you change both numbers (the one before and after the `:`). Assuming the above game port changes to `7755` this would be the result:

```yml
...
    ports:
      # Game port for player connections through the server browser
      - 0.0.0.0:7755:7755/udp
      # RCON port for remote server administration
      - 0.0.0.0:27020:27020/tcp
...
```

Now that your port changes are set, you have to recreate your container. Therefore you need to use `docker compose up -d` in order to apply your port changes.

### Start/Restart/Stop

To perform any of the actions, execute the following commands (you need to be in the directory of the `docker-compose.yml` file):

```
docker compose start asa-server-1
docker compose restart asa-server-1
docker compose stop asa-server-1
```

You can also use the native docker commands, where you do not need to be in the directory of the `docker-compose.yml` file. However using this method would not check for changes in your `docker-compose.yml` file.
So in case you edited the `docker-compose.yml` file (e.g. because you adjusted the start parameters), you need to use `docker compose` commands instead.
```
docker start/restart/stop asa-server-1
```

## Server Administration

### Debug Mode

Sometimes you want to test something inside the container without starting the ASA server. The debug mode can be enabled by changing `- ENABLE_DEBUG=0` to `1` in the `docker-compose.yml` file.
Once done, the result will look like this:

```yml
...
services:
  asa-server-1:
    container_name: asa-server-1
    hostname: asa-server-1
    entrypoint: "/usr/bin/start_server"
    user: gameserver
    image: "justamply/asa-linux-server:latest"
    environment:
      - ASA_START_PARAMS=TheIsland_WP?listen?Port=7777?RCONPort=27020?RCONEnabled=True -WinLiveMaxPlayers=50
      - ENABLE_DEBUG=1
...
```

Now run `docker compose up -d` and the container will just start without launching the server or validating server files.

Check if the container launched in debug mode by running `docker logs -f asa-server-1` and check whether it's saying "Entering debug mode...". If that's the case, you are good.

You can enter the shell of your server by running

```
docker exec -ti asa-server-1 bash
```

If you need root access run

```
docker exec -ti -u root asa-server-1 bash
```

### Applying Server Updates

Updates will be automatically downloaded or applied once you restart the container with ...

```
docker restart asa-server-1
```

It is totally possible that after a restart and applying all updates, the client is still one or more versions ahead. This is because Wildcard does sometimes run client-only updates, since not all
updates are affecting the server software. This is not a problem at all. As long as you can connect to your server, everything is fine. The server software checks for incompatible client
versions anyway.

In general you can check when the latest server update was published by Wildcard, by checking [this link](https://steamdb.info/app/2430930/depots/). The section mentioning the last update of the `public` branch
tells you when the last update was rolled out for the server software.

If you have any doubts on this, open a GitHub issue.

### Daily Restarts

As `root` user of your server (or any other user that is member of the `docker` group) open your crontab configuration:

```
crontab -e
```

Add the following lines to it:
```
30 3 * * * docker exec asa-server-1 asa-ctrl rcon --exec 'serverchat Server restart in 30 minutes'
50 3 * * * docker exec asa-server-1 asa-ctrl rcon --exec 'serverchat Server restart in 10 minutes'
57 3 * * * docker exec asa-server-1 asa-ctrl rcon --exec 'serverchat Server restart in 3 minutes'
58 3 * * * docker exec asa-server-1 asa-ctrl rcon --exec 'saveworld'
0 4 * * * docker restart asa-server-1
```

Explanation:
* Line 1: Every day at 03:30am of your server's timezone, a message will be sent to all players announcing a restart in 30 minutes.
* Line 2: Every day at 03:50am of your server's timezone, a message will be sent to all players announcing a restart in 10 minutes.
* Line 3: Every day at 03:57am of your server's timezone, a message will be sent to all players announcing a restart in 3 minutes.
* Line 4: Every day at 03:58am of your server's timezone, the server saves the world before the restart happens.
* Line 5: Every day at 04:00am of your server's timezone, the ASA server gets restarted and installs pending updates from Steam.

Read more about the crontab syntax [here](https://www.adminschoice.com/crontab-quick-reference).

**NOTE:** The first 4 lines execute RCON commands, which requires you to have a working RCON setup. Please follow the instructions in section "[Executing RCON commands](#executing-rcon-commands)" to
ensure you can execute RCON commands.

### Executing RCON Commands

You can run RCON commands by accessing the `rcon` subcommand of the `asa-ctrl` tool which is shipped with the container image. There's no need to enter your server password, IP, or RCON port manually. As long as
you have set your RCON password and port, either as a start parameter or in the `GameUserSettings.ini` file of your server, `asa-ctrl` is able to figure those details out by itself.

The following variables need to be present in `GameUserSettings.ini` under the `[ServerSettings]` section:

```
RCONEnabled=True
ServerAdminPassword=mysecretpass
RCONPort=27020
```

**NOTE:** There can be issues setting `ServerAdminPassword` as command line option. I'd suggest to set it in the `GameUserSettings.ini` file only.

Example:

```
docker exec -t asa-server-1 asa-ctrl rcon --exec 'saveworld'
```

**NOTE:** As opposed to ingame cheat commands, you must not put `admincheat` or `cheat` in front of the command.

## Cluster Setup

Setting up a second server is quite easy and you can easily add more if you want (given that your hardware is capable of running multiple instances). There's already a definition for a second server in the `docker-compose.yml` file,
but the definition is commented out by a leading `#`. If you remove these `#`, and run `docker compose up -d` again, then the second server should start and it will listen on the game port `7778` and the query port `27021`. Please note that
the server files, as well as Steam, and steamcmd will be downloaded again and the first start can take a while.

You can edit the start parameters in the same way like for the first server and the files of the second server are located at the same location, except that the second server has its suffix changed from `-1` to `-2`. The directories will therefore,
named like this:

```
asa-server_server-files-2/
asa-server_steam-2/
asa-server_steamcmd-2/
```

That's it! Your second server is now running in a cluster setup. This means that travelling between your servers is possible through Obelisks. If you do not want players to travel between your servers, you need to remove the `-clusterid` option
from the start parameters. It's advised to change the `-clusterid` parameter for all of your servers to a random string and keep it secret (e.g. `-clusterid=aSM42F6PLaPk` as opposed to `-clusterid=default`). The reason for that is that you will
end up seeing also other servers from the community that use `default` as their `clusterid`. If you only want players to travel between your own servers, then the `clusterid` must be different.

If you want to spin up more servers, you need to add more entries to the `docker-compose.yml` file. The following sections need to be edited: `services` and `volumes`. Make sure that you adjust all suffixes and replace them with a new one
(e.g. `-3` now) for the newly added entries.

## Mod Management

There are two supported ways to manage mods:

1. Static method: Add a `-mods=` option directly to `ASA_START_PARAMS` in `docker-compose.yml` (works but requires editing and restarting for every change)
2. Dynamic method: Use the built-in mod database and CLI to enable/disable mods without manually editing the compose file.

### Static Method

You can still hard-code mods in `ASA_START_PARAMS` by adding a `-mods=` option:

```
[...]
- ASA_START_PARAMS=TheIsland_WP?listen?Port=7777?RCONPort=27020?RCONEnabled=True -WinLiveMaxPlayers=50 -mods=12345,67891
[...]
```

Changing this list requires editing the compose file and recreating/restarting the container. Mixing both methods is safe: statically defined mods are merged with dynamically enabled ones (duplicates are ignored by the game server).

### Dynamic Method

The container maintains a JSON database (`mods.json`) inside the server files directory. You can enable, disable and list mods via the `asa-ctrl` CLI:

```
docker exec asa-server-1 asa-ctrl mods enable 12345
docker exec asa-server-1 asa-ctrl mods enable 67891
docker exec asa-server-1 asa-ctrl mods list --enabled-only
docker exec asa-server-1 asa-ctrl mods disable 12345
```

Enabled mods are automatically injected into the server start parameters through an internal helper command `asa-ctrl mods-string` when the container (re)starts. After enabling or disabling mods you only need to restart the container for downloads / changes to take effect:

```
docker restart asa-server-1
```

Mod IDs are usually listed on the mod's CurseForge page.

### Adding Mod Maps

Search for a map on curseforge.com and find out what mod id the map has and what the map name is. For the map [Svartalfheim](https://www.curseforge.com/ark-survival-ascended/mods/svartalfheim) the map name
is `Svartalfheim_WP` and the mod id is `893657`.

Once you found out the information you need, you need to adjust your start parameters in the `docker-compose.yml` file and add the map name, as well as either:

* enable the map mod dynamically (`docker exec asa-server-1 asa-ctrl mods enable 893657`) OR
* add / keep a static `-mods=893657` option

e.g.

```
[...]
- ASA_START_PARAMS=Svartalfheim_WP?listen?Port=7777?RCONPort=27020?RCONEnabled=True -WinLiveMaxPlayers=50 -mods=893657
[...]
```

Restart your server using `docker compose up -d`. It may take a while, as the server has to download the map, so be patient.

## Plugin Support

Plugin support was introduced by version 1.4.0 of this container image. So make sure that you updated to the latest version of the container image or to version 1.4.0 as described [here](#updating-the-container-image).

There's a project ([see here](https://gameservershub.com/forums/resources/ark-survival-ascended-serverapi-crossplay-supported.683/)) that allows you to load plugins on your server (e.g. permission handling). To install the plugin loader, please visit [gameservershub.com](https://gameservershub.com/forums/resources/ark-survival-ascended-serverapi-crossplay-supported.683/) and refer to the "ServerAPI Installation Steps" section and download the zip archive. A `gameservershub.com` account is required in order to download the plugin loader.

When the download of the zip archive is completed, follow these steps to install the plugin loader:

1. Make sure that you launched the ASA server at least once without the plugin loader.
2. Stop the ASA server container by running `docker stop asa-server-1`
3. Enter the server files binary directory as `root` user: `cd /var/lib/docker/volumes/asa-server_server-files-1/_data/ShooterGame/Binaries/Win64`
4. Place the downloaded zip archive in that directory (the name of the archive must start with `AsaApi_`). Do not unzip the content.
5. Restart your server using `docker compose up -d`

The installation happens automatically by the container start script. You can follow the installation process by running `docker logs -f asa-server-1`. Once the log says "Detected ASA Server API loader. Launching server through AsaApiLoader.exe",
the installation is complete. In the following log lines your should see the start process of the plugin loader.

How to install plugins is described on gameservershub.com, from which you obtained the plugin loader. Please refer to their guide instead.

## Map Information

This is a list of all official map names with their map id. The map id is used as start parameter in the `docker-compose.yml` file.

| Map Name  | Map ID (for the start parameter) |
| ------------- | ------------- |
| The Island    | TheIsland_WP  |
| Scorched Earth  | ScorchedEarth_WP  |
| The Center  | TheCenter_WP  |
| Aberration | Aberration_WP |
| Extinction | Extinction_WP |

**NOTE:** Mod Maps have their own id! (See [Adding Mod Maps](#adding-mod-maps))

## Container Updates

The container image will be updated from time to time. In general, we try to not break previous installations by an update, but to add certain features, it might be necessary to introduce backward incompatibilities.
The default `docker-compose.yml` file suggests to use the `latest` branch of the container image. If you want to stay on one specific version, you can force the container image to launch with that said version, by
changing `image: "justamply/asa-linux-server:latest"` in your `docker-compose.yml` file (as outlined below) to whatever version suits you. A list of all versions can be
found [here](https://hub.docker.com/r/justamply/asa-linux-server/tags).

For example:

If you want to stay on version `1.4.0` for your ASA server, you must change `image: "justamply/asa-linux-server:latest"` to `image: "justamply/asa-linux-server:1.4.0"`.

Even if you stay on branch `latest`, your container image won't be updated automatically if we roll out an update. You explicitly need to run `docker pull justamply/asa-linux-server:latest` to obtain the newest version.

We strongly suggest to read through the [releases page](https://github.com/justamply/ark-survival-ascended-linux-container-image/releases) of this repository to see what has changed between versions. If there's
a backward incompatibility being introduced, it will be mentioned there with an explanation what to change.

## Credits

* Glorius Eggroll - For his version of Proton to run the ARK Windows binaries on Linux ([click](https://github.com/GloriousEggroll/proton-ge-custom))
* cdp1337 - For his Linux guide of installing Proton and running ARK on Linux ([click](https://github.com/cdp1337/ARKSurvivalAscended-Linux))
* tesfabpel - For his Valve RCON implementation in Ruby ([click](https://github.com/tesfabpel/srcon-rb))