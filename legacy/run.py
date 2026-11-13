#!/usr/bin/python3

import logging

import appstate
from web import Web

# Config
host = '127.0.0.1'
port = 8000
timezone = "America/Denver"
remove_after = {'days': 8}
debug = False
reloader = False

# Logging
logger = logging.getLogger("shoppin")
logger.setLevel(logging.DEBUG)

streamhandler = logging.StreamHandler()
streamformatter = logging.Formatter('%(levelname)-8s [%(name)s] %(message)s')
streamhandler.setLevel(logging.DEBUG)  # Loglevel for stdout
streamhandler.setFormatter(streamformatter)
logger.addHandler(streamhandler)

filehandler = logging.FileHandler('run.log')
fileformatter = logging.Formatter('%(asctime)s %(levelname)-8s [%(name)s] %(message)s')
filehandler.setLevel(logging.DEBUG)  # Loglevel for stdout
filehandler.setFormatter(fileformatter)
logger.addHandler(filehandler)

logger.debug("Starting application")

logger.info("Managing application state")
my_appstate = appstate.Appstate(timezone=timezone)

if __name__ == '__main__':
    logger.debug("Instantiating the Bottle app")
    webapp = Web(my_appstate, remove_after=remove_after)
    logger.info("Running the Bottle app instance")
    webapp.run(host=host, port=port, debug=debug, reloader=reloader)
