import re
import yaml

class Emojify:
    """
    The config file should contain YAML mapping a regex to an emoji
    Best to use decimal or hexadecimal HTML entity codes for the emojis

    For example:
    ---
    '(?i)\btaco\b': "&#127790"

    """
    def __init__(self, configfile="emoji.conf"):
        try:
            with open(configfile) as f:
                self.config = yaml.safe_load(f)
        except Exception as e:
            print("Could not open or parse emoji config file", configfile)
            raise(e)

    def emojify(self, input_string):
        emojis = ""
        for pattern in self.config:
            if re.search(pattern, input_string):
                emojis += self.config[pattern]
        return " " + emojis

    __call__ = emojify


