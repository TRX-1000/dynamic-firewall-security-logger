import eventlet
eventlet.monkey_patch()

import logging
from os_ken.lib import hub

from os_ken import cfg
from os_ken.base import app_manager
from os_ken.controller import ofp_handler
import controller

logging.basicConfig(level=logging.INFO)
cfg.CONF(args=[])
cfg.CONF.set_override("ofp_listen_host", "127.0.0.1")
cfg.CONF.set_override("ofp_tcp_listen_port", 6653)

print("Controller starting; threading mode:", hub.HUB_TYPE, flush=True)
app_manager.AppManager.run_apps(["controller"])
