#!/usr/bin/env python

import keystoneclient.v2_0.client as ksclient
import glanceclient.v2.client as glclient
from os import path, environ
from sys import exit
from signal import signal, SIGINT
from getpass import getpass
from ConfigParser import SafeConfigParser, NoSectionError
from argparse import ArgumentParser
from novaclient import client as novaclient


CONFIG = '.snapshotmanager.cfg'
VERBOSE = False
FINGERPRINT = '@'

def signal_handler(signal, frame):
    print '\nExiting...'
    exit(1)

def parseargs():
    parser = ArgumentParser()
    mexclusion = parser.add_mutually_exclusive_group(required = True)
    groupRestore = parser.add_argument_group('Restoring from snapshot')
    groupSnapshot = parser.add_argument_group('Snapshot creation')
    groupList = parser.add_argument_group('Snapshots listing')
    mexclusion.add_argument('-s', '--snapshot', help = 'Snapshot entire openstack cluster')
    mexclusion.add_argument('-r', '--restore', help = 'Restore entire openstack cluster')
    mexclusion.add_argument('-l', '--list', action = 'store_true', help = 'List openstack cluster snapshots')
    mexclusion.add_argument('-d', '--delete', help = 'Delete snapshot')
    parser.add_argument('-v', '--verbose', action = 'store_true')
    groupSnapshot.add_argument('-e', '--exclude', help = 'Exclude instances from snapshotting')
    groupRestore.add_argument('-k', '--key', help = 'Key to boot images with upon restore')
    return vars(parser.parse_args())

def configParse(configFile, *sections):
    if not path.isfile(CONFIG):
        print "No config file %s exists, exiting..." % configFile
        exit(1)
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

def getKeystoneCreds():
    creds = {}
    try:
        creds['username'] = environ['OS_USERNAME']
        creds['password'] = environ['OS_PASSWORD']
    except KeyError, e:
        creds['username'] = raw_input('Enter OpenStack username: ')
        creds['password'] = getpass('Enter OpenStack password: ')
    try:
        creds['auth_url'] = environ['OS_AUTH_URL']
        creds['tenant_name'] = environ['OS_TENANT_NAME']
    except KeyError, e:
        if path.isfile(CONFIG):
            parsedConf = configParse(CONFIG, 'Nova')['Nova']
            try:
                creds['auth_url'] = parsedConf['os_auth_url']
                creds['tenant_name'] = parsedConf['os_tenant_name']
            except KeyError:
                creds['auth_url'] = raw_input('Enter OpenStack auth url: ')
                creds['tenant_name'] = raw_input('Enter OpenStack tenant name: ')
        else:
            creds['auth_url'] = raw_input('Enter OpenStack auth url: ')
            creds['tenant_name'] = raw_input('Enter OpenStack tenant name: ')
    return creds

def getNovaCreds():
    creds = {}
    try:
        creds['username'] = environ['OS_USERNAME']
        creds['api_key'] = environ['OS_PASSWORD']
    except KeyError, e:
        creds['username'] = raw_input('Enter OpenStack username: ')
        creds['api_key'] = getpass('Enter OpenStack password: ')
    try:
        creds['auth_url'] = environ['OS_AUTH_URL']
        creds['project_id'] = environ['OS_TENANT_NAME']
    except KeyError, e:
        if path.isfile(CONFIG):
            parsedConf = configParse(CONFIG, 'Nova')['Nova']
            try:
                creds['auth_url'] = parsedConf['os_auth_url']
                creds['project_id'] = parsedConf['os_tenant_name']
            except KeyError:
                creds['auth_url'] = raw_input('Enter OpenStack auth url: ')
                creds['project_id'] = raw_input('Enter OpenStack tenant name: ')
        else:
            creds['auth_url'] = raw_input('Enter OpenStack auth url: ')
            creds['project_id'] = raw_input('Enter OpenStack tenant name: ')
    return creds

def bootInstance(nova, name, image, flavor, key_name, sec_group):
    try:
        nova.servers.create(name, image, flavor, key_name = key_name, security_groups = sec_group)
    except:
        raise

def listKeys(nova):
    keys = []
    for key in nova.keypairs.list():
        keys.append(key.name)
    return keys

def getFlavorId(nova, name):
    """ flavor ID by name """
    for flavor in nova.flavors.list():
        if name == flavor.name:
            return flavor.id

def doSnapshot(snapshotName):
    creds = getNovaCreds()
    nova = novaclient.Client("1.1", **creds)
    for server in nova.servers.list():
        if VERBOSE: print server.human_id, server.flavor['id']
        try:
            server.create_image('%s%s%s' % (server.human_id, FINGERPRINT, snapshotName))
            imageSnapshot = "%s%s%s" % (server.human_id, FINGERPRINT, snapshotName)
            if VERBOSE: print "%s from instance %s" % (imageSnapshot, server.human_id)
        except novaclient.exceptions.ClientException, err:
            print err
            print 'Exiting..'
            exit(1)
    print 'Added snapshots creation to the queue.'

def listImages():
    creds = getKeystoneCreds()
    keystone = ksclient.Client(**creds)
    glance_endpoint = keystone.service_catalog.url_for(service_type = 'image', 
        endpoint_type = 'publicURL')
    glance = glclient.Client(glance_endpoint, token = keystone.auth_token)
    return glance.images.list()

def getServers(nova, name):
    for server in nova.servers.list():
        if server._info['name'] == name: return server._info['id']

def listSnapshotsVersions():
    snapshots = []
    for image in listImages():
        if FINGERPRINT in image.raw['name'] and image.raw['image_type'] == 'snapshot':
            version = image.raw['name'].split(FINGERPRINT)[1]
            if not version in snapshots: snapshots.append(version)
    return snapshots

def deleteSnapshot(name):
    creds = getNovaCreds()
    nova = novaclient.Client("1.1", **creds)
    if name in listSnapshotsVersions():
        for image in listImages():
            try:
                if name == image.raw['name'].split(FINGERPRINT)[1]:
                    nova.images.delete(image.raw['id'])
            except IndexError:
                continue
    else:
        print 'No such snapshot'

def restoreSnapshots(snapshotName, key_name):
    # exit if no such snapshot exists
    if not snapshotName in listSnapshotsVersions():
        print 'Snapshot %s does not exist.' % snapshotName
        exit(0)
    # TODO: get security group mappings
    # Nova authentication
    creds = getNovaCreds()
    nova = novaclient.Client("1.1", **creds)
    # check ssh key existence
    if not key_name in listKeys(nova):
        print 'No such ssh key exists., exiting...'
        exit(1)
    # get mapping of servers to flavors from config
    flavors = configParse(CONFIG, 'Flavors')['Flavors']
    # get mapping of servers to images from nova
    restoreImages = {}
    for image in listImages():
        if ("%s%s" % (FINGERPRINT, snapshotName)) in image.raw['name']:
            name = image.raw['name'].split(FINGERPRINT)[0]
            restoreImages[name] = image.raw['id']
    # get mapping of servers to security groups
    secGroups = configParse(CONFIG, 'Secgroups')['Secgroups']
    for name, flavor in flavors.iteritems():
        try:
            image = restoreImages[name]
        except KeyError:
            if VERBOSE: print "Skipping %s, no image found" % name
            continue
        if secGroups[name]:
            sec_group = [secGroups[name], 'default']
        else:
            sec_group = ['default',]
        if VERBOSE: print "Starting %s as flavor %s using image id %s and security group %s" % (name, flavor, image, sec_group)
        # delete existing instance
        if getServers(nova, name): nova.servers.delete(getServers(nova, name))
        try:
            bootInstance(nova, name, image, getFlavorId(nova, flavor), key_name, sec_group)
        except novaclient.exceptions.OverLimit, e:
            if VERBOSE: print e
            continue

def main():
    if params['snapshot']: doSnapshot(params['snapshot'])
    if params['list']:
        snapshots = listSnapshotsVersions()
        if len(snapshots) > 0:
            print 'Available snapshot versions:'
            for version in snapshots: print version
        else:
            print 'No snapshot available.'
    if params['restore']:
        if params['key']:
            key_name = params['key']
        else:
            key_name = configParse(CONFIG, 'Nova')['Nova']['default_key']
        restoreSnapshots(params['restore'], key_name)
    if params['delete']:
        deleteSnapshot(params['delete'])


if __name__ == '__main__':
    params = parseargs()
    VERBOSE = params['verbose']
    signal(SIGINT, signal_handler)
    main()
