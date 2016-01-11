#!/usr/bin/python


###########
# IMPORTS #
###########


import re
import yaml
import sys
import os
import docker
import time
import tarfile
from termcolor import cprint


##########
# CONFIG #
##########


LOG_FILE = "/backup/backup.log"

DEBUG_MODE = True
USE_COLORS = True

BACKUP_LABEL =              'io.enonic.backup.enable'
BACKUP_PRESCRIPT_LABEL =    'io.enonic.backup.prescripts'
BACKUP_POSTSCRIPT_LABEL =   'io.enonic.backup.postscripts'
BACKUP_DATA_LABEL =         'io.enonic.backup.data'

BACKUP_TARGET = '/backup'

ADMIN_USER = 'su'
ADMIN_PWD_FILE = "/services/xp_su_pwd.txt"


#############
# FUNCTIONS #
#############


#def is_fqdn(hostname):
#    # ok, not exactly FQDN check - just checking if there are no illegal characters in hostname
#    if len(hostname) > 255:
#        return False
#    if hostname[-1] == ".":
#        hostname = hostname[:-1]  # strip exactly one dot from the right, if present
#    allowed = re.compile('(?!-)[A-Z\d-]{1,63}(?<!-)$', re.IGNORECASE)
#    return all(allowed.match(x) for x in hostname.split("."))


def _error(message):
    if USE_COLORS:
        cprint("[ERROR] %s" % message, "red")
    else:
        print("[ERROR] %s" % message)
    log.write("[ERROR] %s" % message + "\n")
    sys.stdout.flush()


def _info(message, color='white'):
    if USE_COLORS:
        cprint("[INFO] %s" % message, color)
    else:
        print("[INFO] %s" % message)
    log.write("[INFO] %s" % message + "\n")
    sys.stdout.flush()


def _debug(message, force=False):
    if DEBUG_MODE or force:
        if USE_COLORS:
            cprint("[DEBUG] %s" % message, "cyan")
        else:
            print("[DEBUG] %s" % message)
    sys.stdout.flush()


def _exit(exit_code=0):
    log.write("[END] " + time.strftime("%Y-%m-%d %H:%M:%S") + "\n\n")
    log.close()
    sys.exit(exit_code)


def command_execute(container_name, command):
    # this is slightly retarded way of doing docker exec:
    # first you prepare exec 'session' with docker_client.exec_create()
    # then execute it with docker_client.exec_start(id) (id is returned from exec_create())
    # finally do docker_client.exec_inspect() to learn if it actually succeeded
    _info("Execute '" + command + "' command")
    exec_id = docker_client.exec_create(container=container_name, cmd=command)
    _debug(command)
    exec_out = docker_client.exec_start(exec_id)
    _debug("Command exit code:" + str(docker_client.exec_inspect(exec_id)['ExitCode']))
    out = { 'command_output': exec_out.strip(), 'command_exit_code': docker_client.exec_inspect(exec_id)['ExitCode']}
    return(out)


########
# MAIN #
########


start_time = time.time()
errors = []

# get XP 'su' user password from password file:
# usually /services/xp_su_pwd.txt (within the container), or /srv/xp_su_pwd.txt on the parent host
if not os.path.isfile(ADMIN_PWD_FILE):
    _error(ADMIN_PWD_FILE + " (ADMIN_PWD_FILE) does not exist")
    _exit(1)
else:
    with open(ADMIN_PWD_FILE, "r") as pwd_file:
        data = pwd_file.readlines()
        ADMIN_PASSWORD = data[0].replace('\n', '')

# open or create log file
if not os.path.isfile(LOG_FILE):
    log = open(LOG_FILE, "w")
else:
    log = open(LOG_FILE, "a")
_info("Log file opened")
log.write("[START] " + time.strftime("%Y-%m-%d %H:%M:%S") + "\n")

# expecting only one option - hostname, exit if more
# _info("Check for command line arguments")
# if len(sys.argv) > 2:
#    _error("Incorrect number of arguments: " + str(len(sys.argv)) + " - expected 0 or 1")
#    _exit(1)

# get hostname on which backup should be run - will be hostname or localhost
# hostname = sys.argv[1]

# not exactly FQDN check - just check ift here are no illegal characters in hostname
# _info("Check if hostname contains any illegal characters")
# if not is_fqdn(hostname):
#    _error("Hostname contains invalid characters.")
#    _exit(1)

# since we are running from ECB container, we'll be connecting to docker daemon on parent host through unix socket
_info("Connecting to host docker demon")
docker_client = docker.Client(base_url='unix://var/run/docker.sock', version="auto")
_debug(docker_client.version())
_debug(docker_client.info())

# let's go
_info("")
# _info("*** Performing backup on " + hostname + " ***", "green")
_info("*** Starting backup ***", "green")
_info("")

# service is a XP installation, and to be exact a directory with
# docker-compose.yaml file in it
all_services = []
_info("Search for service directories")
for dir_name in os.listdir("/services"):
    # skip if there is no docker-compose.yaml
    if not os.path.isfile("/services/" + dir_name + "/docker-compose.yml"):
        continue
    all_services.append("/services/" + dir_name)
    _info("Found service directory: " + dir_name)
_debug(all_services)

# 404 :(
if len(all_services) == 0:
    _info("No service directories containing docker-compose.yml found.")
    _exit()

# ok, let's find actual containers we want to backup for each service
for dirname in all_services:
    _info("*** Processing " + dirname + " ***", "green")

    _info("Read yaml config")
    with open(dirname + "/docker-compose.yml", "r") as f:
        ecb_config = yaml.load(f)
    out = yaml.dump(ecb_config)
    _debug(ecb_config)

    # 'ecb' is the name of backup container - skip
    # if 'ecb' in ecb_config.keys():
    #    _info(dirname + " seems to be system container directory - skipping")
    #    continue

    # We're finding container types first, since that is how it is defined in yaml file
    # Container type -> post/pre scripts
    # and the you might have more than one container of given type, each with unique name
    _info("Find container types to be backed up")
    container_types_to_backup = {}
    for ctype, cmeta in ecb_config.items():
        if 'labels' in cmeta.keys() and cmeta['labels'][BACKUP_LABEL] == 'yes':

            # get prescripts
            if cmeta['labels'][BACKUP_PRESCRIPT_LABEL] is not None:
                pre_scripts = [script.strip() for script in cmeta['labels'][BACKUP_PRESCRIPT_LABEL].split(",")]
            else:
                pre_scripts = ''

            # get postscripts
            if cmeta['labels'][BACKUP_POSTSCRIPT_LABEL] is not None:
                post_scripts = [script.strip() for script in cmeta['labels'][BACKUP_POSTSCRIPT_LABEL].split(",")]
            else:
                post_scripts = ''

            # get data locations
            if cmeta['labels'][BACKUP_DATA_LABEL] is not None:
                data_locations = [script.strip() for script in cmeta['labels'][BACKUP_DATA_LABEL].split(",")]
            else:
                # no data locations - skip
                continue

            # types to backup (in most cases only exp probably)
            container_types_to_backup[ctype] = {'pre-scripts': pre_scripts, 'post-scripts': post_scripts, 'data_locations': data_locations}
    _info("Container types to backup: " + ', '.join(container_types_to_backup))
    _debug(container_types_to_backup)

    # now, get the actual names of the containers of each type
    _info("Get names of the containers to be backed up")
    containers_to_backup = {}
    for image in docker_client.containers():
        for container_name in image['Names']:
            docker_compose_prefix = dirname.split('/')[2].replace('.', '')
            for container_type in container_types_to_backup.keys():
                re_string = '^' + docker_compose_prefix + '_' + container_type + '_[0-9]+$'
                p = re.compile(re_string, re.IGNORECASE)
                if p.match(container_name[1:]):
                    containers_to_backup[container_name[1:]] = container_types_to_backup[container_type]
    # ... aaad we've got list of containers
    _info("Containers to backup: " + ", ".join(containers_to_backup.keys()))
    _debug(containers_to_backup)

    # backup each container
    for container_name in containers_to_backup.keys():
        _info("")
        _info("*** Staring backup of " + container_name + " ***", "green")

        # PRE-SCRIPTS
        _info("")
        _info("Run pre-scripts")
        if containers_to_backup[container_name]['pre-scripts'] == '':
            _info("No pre-scripts defined")
        else:
            for command in containers_to_backup[container_name]['pre-scripts']:
                # if there is '$user$' string in the docker-compose.yaml it will be replaced with admin user for XP
                if '$user$' in command:
                    command = command.replace('$user$', ADMIN_USER)
                # if there is '$password$' string in the docker-compose.yaml it will be replaced with admin user for XP
                if '$password$' in command:
                    command = command.replace('$password$', ADMIN_PASSWORD)
                _debug('Command to run: ' + command)
                ret = command_execute(container_name, command)
                _info("command output:\n" + ret['command_output'], 'yellow')
                _debug("Command exit code: " + str(ret['command_exit_code']))
                if str(ret['command_exit_code']) != 0:
                    errors.append('Command [' + command + '] (pre-script) exited with code ' + str(ret['command_exit_code']))
                    continue

        # BACKUP
        _info("")
        _info("Do backup")

        # create backup directory
        DIRNAME = BACKUP_TARGET + '/' + container_name + '_' + time.strftime("%Y-%m-%d_%H.%M.%S")
        os.mkdir(DIRNAME)

        # transfer backup_locations
        for location in containers_to_backup[container_name]['data_locations']:
            _info("Backing up " + location)
            stream, stats = docker_client.get_archive(container_name, location)

            path = location[1:].split('/')
            path_unique = DIRNAME + '/' + '_'.join(path)
            os.mkdir(path_unique)

            with open(path_unique + '/tmp.tar', 'wb') as out:
                out.write(stream.data)

            tar = tarfile.open(path_unique + '/tmp.tar')
            tar.extractall(path=path_unique)
            tar.close()
            os.remove(path_unique + '/tmp.tar')

#        # pre-scripts prepared /tmp/backup.tar.gz, now we want to download it from target container to ecb container
#        stream, stats = docker_client.get_archive(container_name, '/tmp/backup.tar.gz')
#        _debug(stats)
#        _debug(stream)
#        _debug(stream.getheaders())

#        # now, this is slightly weird part:
#        # docker_client.get_archive() is downloading target and taring it, so tmp.tar will have backup.tar.gz inside...
#        TMP_FILENAME = BACKUP_TARGET + '/tmp.tar'

#        _info("Saving " + TMP_FILENAME)

#        with open(TMP_FILENAME, 'wb') as out:
#            out.write(stream.data)

#        if not os.path.isfile(TMP_FILENAME):
#            _error("Backup file does not exist: " + TMP_FILENAME)

#        # since file is copied as a tar stream, we need to extract actual backup.tar.gz file with backup
#        _info("Extracting backup archive from " + TMP_FILENAME)
#        tar = tarfile.open(TMP_FILENAME)
#        # extract all to current dir
#        tar.extractall(path=BACKUP_TARGET)
#        tar.close()

#        # rename backup.tar.gz to BACKUP_FILENAME
#        TAR_FILENAME = container_name + '_' + time.strftime("%Y-%m-%d_%H.%M.%S") + '.tar.gz'
#        BACKUP_FILENAME = BACKUP_TARGET + '/' + TAR_FILENAME
#        _info("Rename " + TMP_FILENAME + " to " + BACKUP_FILENAME)
#        os.rename(BACKUP_TARGET + '/backup.tar.gz', BACKUP_FILENAME)

#        size = os.path.getsize(BACKUP_FILENAME)
#        if size >= 1048576:
#            size = float(size) / 1048576
#            unit = 'MB'
#        elif size >= 1024:
#            size = float(size) / 1024
#            unit = 'KB'
#        else:
#            unit = 'B'
#        _info(BACKUP_FILENAME + " saved: " + ("%.2f" % size) + ' ' + unit, 'yellow')

#        # cleanup
#        _info("Cleanup - remove " + TMP_FILENAME)
#        os.remove(TMP_FILENAME)

#        # this is to notify ec-backup.sh which file is the newest (for info and download purposes)
#        _info("Write current file")
#        with open(BACKUP_TARGET + "/current", "w") as text_file:
#            text_file.write('/srv/_backup/' + TAR_FILENAME + "\n")

        # POST-SCRIPTS
        _info("")
        _info("Run post-scripts")
        if containers_to_backup[container_name]['post-scripts'] == '':
            _info("No post-scripts defined")
        else:
            for command in containers_to_backup[container_name]['post-scripts']:
                if '$user$' in command:
                    command = command.replace('$user$', ADMIN_USER)
                if '$password$' in command:
                    command = command.replace('$password$', ADMIN_PASSWORD)
                _debug('Command to run: ' + command)
                ret = command_execute(container_name, command)
                _info(ret['command_output'], 'magenta')
                _info("Command exit code: " + str(ret['command_exit_code']), 'yellow')
                if str(ret['command_exit_code']) != 0:
                    errors.append('Command [' + command + '] (post-script) exited with code ' + str(ret['command_exit_code']))
                    continue

# check for errors
if len(errors) > 0:
    _info("there were some errors:")
    for line in errors:
        _info(line)

end_time = time.time()
_info("")
_info("Script was running for " + str(int(end_time - start_time)) + " seconds")
_info("")

_exit()
