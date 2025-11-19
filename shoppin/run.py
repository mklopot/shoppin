#!/usr/bin/python3

import appstate
from web import Web

my_appstate = appstate.Appstate(timezone="America/Denver")


if __name__ == '__main__':
    webapp = Web(my_appstate)
    webapp.run(host='127.0.0.1', port=8000, debug=True, reloader=True)
