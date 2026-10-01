"""Tests for the launch line contract."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from asa_ctrl.common.constants import DEFAULT_LAUNCH_BASE  # noqa: E402
from asa_ctrl.common.launch_config import (  # noqa: E402
    LaunchConfiguration,
    coerce_bool,
    coerce_int,
    tokenize,
)


COMPOSE_LINE = (
    "TheIsland_WP?listen?Port=7777?RCONPort=27020?RCONEnabled=True"
    "?ServerAdminPassword=change_this_password -WinLiveMaxPlayers=50 "
    '-clusterid=default -ClusterDirOverride="/home/gameserver/cluster-shared"'
)


# --- parsing --------------------------------------------------------------


def test_parse_splits_map_query_and_flags():
    config = LaunchConfiguration.parse(COMPOSE_LINE)

    assert config.map_name == "TheIsland_WP"
    assert [entry.key for entry in config.query] == [
        "listen",
        "Port",
        "RCONPort",
        "RCONEnabled",
        "ServerAdminPassword",
    ]
    assert config.query[0].value is None
    assert config.flags == [
        "-WinLiveMaxPlayers=50",
        "-clusterid=default",
        '-ClusterDirOverride="/home/gameserver/cluster-shared"',
    ]


def test_parse_empty_line_yields_empty_configuration():
    assert LaunchConfiguration.parse("").is_empty()
    assert LaunchConfiguration.parse(None).is_empty()
    assert LaunchConfiguration.parse("   ").is_empty()


def test_parse_line_without_map_keeps_every_token_as_flag():
    config = LaunchConfiguration.parse("-nosteam -NoBattlEye")

    assert config.map_name == ""
    assert config.query == []
    assert config.flags == ["-nosteam", "-NoBattlEye"]


def test_tokenize_keeps_quoted_spans_together():
    assert tokenize('-A="one two" -B') == ['-A="one two"', "-B"]


# --- round trip -----------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        COMPOSE_LINE,
        DEFAULT_LAUNCH_BASE,
        "TheIsland_WP",
        "TheIsland_WP?listen",
        "Ragnarok_WP?listen?Port=7778 -mods=1,2,3 -nosteam",
        "-nosteam",
        'Map?listen -ClusterDirOverride="/a b/c"',
    ],
)
def test_render_round_trips_existing_launch_lines(line):
    """Backward compatibility rests on this being an identity."""
    assert LaunchConfiguration.parse(line).render() == line


def test_render_collapses_only_whitespace():
    folded = "TheIsland_WP?listen  -WinLiveMaxPlayers=50 \n -nosteam"
    assert (
        LaunchConfiguration.parse(folded).render()
        == "TheIsland_WP?listen -WinLiveMaxPlayers=50 -nosteam"
    )


def test_render_for_logging_hides_passwords_without_changing_launch_line():
    line = (
        "Map?ServerAdminPassword=admin-secret?serverpassword=join-secret"
        "?SpectatorPassword=spectator-secret?Port=7777"
        " -ExtraPassword=extra-secret -nosteam"
    )
    config = LaunchConfiguration.parse(line)

    logged = config.render_for_logging()

    assert logged == (
        "Map?ServerAdminPassword=<redacted>?serverpassword=<redacted>"
        "?SpectatorPassword=<redacted>?Port=7777"
        " -ExtraPassword=<redacted> -nosteam"
    )
    assert config.render() == line


# --- lookups --------------------------------------------------------------


def test_value_prefers_query_segment_over_flags():
    config = LaunchConfiguration.parse("Map?Port=7777 -Port=9999")
    assert config.value("Port") == "7777"


def test_value_reads_flags_when_query_has_no_entry():
    config = LaunchConfiguration.parse("Map?listen -WinLiveMaxPlayers=50")
    assert config.value("WinLiveMaxPlayers") == "50"


def test_value_does_not_match_a_longer_key_suffix():
    """The previous substring scanner answered 27020 for 'Port'."""
    config = LaunchConfiguration.parse("Map?listen?RCONPort=27020")
    assert config.value("Port") is None
    assert config.value("RCONPort") == "27020"


def test_value_strips_surrounding_quotes():
    config = LaunchConfiguration.parse('Map?listen -ClusterDirOverride="/a/b"')
    assert config.value("ClusterDirOverride") == "/a/b"


def test_value_returns_none_for_bare_switches():
    config = LaunchConfiguration.parse("Map?listen -nosteam")
    assert config.value("listen") is None
    assert config.value("nosteam") is None
    assert config.has_flag("nosteam")
    assert config.has_flag("-nosteam")


def test_as_mapping_flattens_query_and_valued_flags():
    mapping = LaunchConfiguration.parse(COMPOSE_LINE).as_mapping()

    assert mapping["_map"] == "TheIsland_WP"
    assert mapping["RCONPort"] == "27020"
    assert mapping["WinLiveMaxPlayers"] == "50"
    assert mapping["ClusterDirOverride"] == "/home/gameserver/cluster-shared"
    assert "listen" not in mapping


# --- mutation -------------------------------------------------------------


def test_set_query_keeps_position_and_drops_duplicates():
    config = LaunchConfiguration.parse("Map?Port=1?listen?Port=2")
    config.set_query("Port", "7777")

    assert config.render() == "Map?Port=7777?listen"


def test_set_query_appends_unknown_keys():
    config = LaunchConfiguration.parse("Map?listen")
    config.set_query("SessionName", "MyServer")

    assert config.render() == "Map?listen?SessionName=MyServer"


def test_set_flag_keeps_position():
    config = LaunchConfiguration.parse("Map?listen -clusterid=a -nosteam")
    config.set_flag("clusterid", "b")

    assert config.render() == "Map?listen -clusterid=b -nosteam"


def test_ensure_flag_is_idempotent():
    config = LaunchConfiguration.parse("Map?listen -nosteam")
    config.ensure_flag("-nosteam")
    config.ensure_flag("-nosteam")

    assert config.render().count("-nosteam") == 1


def test_merge_mods_folds_into_a_single_flag():
    config = LaunchConfiguration.parse("Map?listen -mods=100,200 -nosteam")
    config.merge_mods([200, 300])

    assert config.render() == "Map?listen -mods=100,200,300 -nosteam"


def test_merge_mods_appends_flag_when_absent():
    config = LaunchConfiguration.parse("Map?listen")
    config.merge_mods([1, 2])

    assert config.render() == "Map?listen -mods=1,2"


def test_merge_mods_without_ids_is_a_no_op():
    config = LaunchConfiguration.parse("Map?listen")
    config.merge_mods([])

    assert config.render() == "Map?listen"


# --- environment overlay --------------------------------------------------


def test_from_env_passes_legacy_start_params_through_untouched():
    env = {"ASA_START_PARAMS": COMPOSE_LINE}
    assert LaunchConfiguration.from_env(env).render() == COMPOSE_LINE


def test_from_env_without_any_configuration_is_empty():
    assert LaunchConfiguration.from_env({}).is_empty()


def test_from_env_blank_values_count_as_unset():
    env = {"ASA_START_PARAMS": COMPOSE_LINE, "ASA_MAP": "   "}
    assert LaunchConfiguration.from_env(env).render() == COMPOSE_LINE


def test_from_env_overlays_discrete_variables_on_the_legacy_line():
    env = {
        "ASA_START_PARAMS": COMPOSE_LINE,
        "ASA_RCON_PORT": "27030",
        "ASA_MAX_PLAYERS": "70",
    }
    config = LaunchConfiguration.from_env(env)

    assert config.value("RCONPort") == "27030"
    assert config.value("WinLiveMaxPlayers") == "70"
    # untouched entries keep their place
    assert config.value("Port") == "7777"
    assert config.render().index("RCONPort") < config.render().index("RCONEnabled")


def test_from_env_seeds_defaults_when_only_discrete_variables_are_set():
    config = LaunchConfiguration.from_env({"ASA_MAP": "Ragnarok_WP"})

    assert config.map_name == "Ragnarok_WP"
    assert config.value("Port") == "7777"
    assert config.value("RCONPort") == "27020"
    assert config.value("RCONEnabled") == "True"
    # the seed deliberately carries no password so the fallback warning fires
    assert config.value("ServerAdminPassword") is None


def test_from_env_normalizes_rcon_enabled_spelling():
    config = LaunchConfiguration.from_env({"ASA_RCON_ENABLED": "yes"})
    assert config.value("RCONEnabled") == "True"

    config = LaunchConfiguration.from_env({"ASA_RCON_ENABLED": "0"})
    assert config.value("RCONEnabled") == "False"


def test_from_env_battleye_toggles_the_no_battleye_flag():
    disabled = LaunchConfiguration.from_env({"ASA_BATTLEYE": "false"})
    assert disabled.has_flag("NoBattlEye")

    enabled = LaunchConfiguration.from_env(
        {"ASA_START_PARAMS": "Map?listen -NoBattlEye", "ASA_BATTLEYE": "true"}
    )
    assert not enabled.has_flag("NoBattlEye")


def test_from_env_extra_query_and_flags_are_appended():
    env = {
        "ASA_START_PARAMS": "Map?listen",
        "ASA_EXTRA_QUERY_PARAMS": "?AllowFlyerCarry=True?ForceRespawnDinos=True",
        "ASA_EXTRA_FLAGS": "-servergamelog -NoBattlEye",
    }
    config = LaunchConfiguration.from_env(env)

    assert config.render() == (
        "Map?listen?AllowFlyerCarry=True?ForceRespawnDinos=True "
        "-servergamelog -NoBattlEye"
    )


def test_from_env_extra_flags_override_named_variables():
    env = {
        "ASA_START_PARAMS": "Map?listen",
        "ASA_CLUSTER_ID": "from-named",
        "ASA_EXTRA_FLAGS": "-clusterid=from-extra",
    }
    config = LaunchConfiguration.from_env(env)

    assert config.value("clusterid") == "from-extra"
    assert config.render().count("clusterid") == 1


def test_from_env_mods_variable_replaces_the_legacy_mods_flag():
    env = {
        "ASA_START_PARAMS": "Map?listen -mods=1,2",
        "ASA_MODS": "3,4",
    }
    config = LaunchConfiguration.from_env(env)

    assert config.value("mods") == "3,4"


# --- coercion -------------------------------------------------------------


@pytest.mark.parametrize("raw", ["1", "true", "TRUE", " yes ", "on"])
def test_coerce_bool_truthy(raw):
    assert coerce_bool(raw) is True


@pytest.mark.parametrize("raw", ["0", "false", "No", "off"])
def test_coerce_bool_falsy(raw):
    assert coerce_bool(raw, default=True) is False


def test_coerce_bool_falls_back_on_garbage():
    assert coerce_bool("maybe", default=True) is True
    assert coerce_bool(None, default=True) is True


def test_coerce_int_falls_back_on_garbage():
    assert coerce_int("42", 7) == 42
    assert coerce_int("  42 ", 7) == 42
    assert coerce_int("nope", 7) == 7
    assert coerce_int(None, 7) == 7
    assert coerce_int("", 7) == 7
