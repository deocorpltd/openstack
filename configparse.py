#!/usr/bin/env python

from ConfigParser import SafeConfigParser, NoSectionError


def configParse(configFile, *sections):
    result = {}
    config = SafeConfigParser()
    config.readfp(open(configFile))
    for section in sections:
        try:
            result[section] = {}
            for option, value in config.items(section): result[section][option] = value
        except NoSectionError, e:
            pass
    return result


if __name__ == '__main__':
    print configParse("config.cfg", "main")