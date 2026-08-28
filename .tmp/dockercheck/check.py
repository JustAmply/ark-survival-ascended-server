import logging, os
logging.basicConfig(level=logging.INFO, format="[check] %(message)s")
log = logging.getLogger("check")
from server_runtime.params import prepare_start_params
from asa_ctrl.common.config import AsaSettings
os.environ.setdefault("ASA_MOD_DATABASE_PATH", "/tmp/mods.json")
os.environ.setdefault("ASA_GAME_USER_SETTINGS_PATH", "/tmp/missing.ini")
print("RESULT:", prepare_start_params(log))
s = AsaSettings()
print("RCON_PASSWORD:", s.get_start_param_value("ServerAdminPassword"))
print("RCON_PORT:", s.get_start_param_value("RCONPort"))
