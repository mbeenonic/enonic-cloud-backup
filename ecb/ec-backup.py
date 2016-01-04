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
from termcolor import cprint
# import git    # for git
# import shutil # for git

##########
# CONFIG #
##########

log_file = "/backup/backup.log"
DEBUG_MODE = True
USE_COLORS = True
SU_PWD_SOURCE = '/srv/xp_su_pwd.txt'

#############
# FUNCTIONS #
#############


def is_fqdn(hostname):
    if len(hostname) > 255:
        return False
    if hostname[-1] == ".":
        hostname = hostname[:-1] # strip exactly one dot from the right, if present
    allowed = re.compile('(?!-)[A-Z\d-]{1,63}(?<!-)$', re.IGNORECASE)
    return all(allowed.match(x) for x in hostname.split("."))


def _error(message):
    if USE_COLORS:
        cprint("[ERROR] %s" % message, "red")
    else:
        print("[ERROR] %s" % message)
    log.write("[ERROR] %s" % message + "\n")


def _info(message, color='white'):
    if USE_COLORS:
        cprint("[INFO] %s" % message, color)
    else:
        print("[INFO] %s" % message)
    log.write("[INFO] %s" % message + "\n")


def _debug(message, force=False):
    if DEBUG_MODE or force :
        if USE_COLORS:
            cprint("[DEBUG] %s" % message, "cyan")
        else:
            print("[DEBUG] %s" % message)


def _help():
    print("HELP - TBD")


def _exit(exit_code=0):
    log.write("[END] " + time.strftime("%Y-%m-%d %H:%M:%S") + "\n\n")
    log.close()
    sys.exit(exit_code)


def command_execute(container_name, command):
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

if not os.path.isfile(log_file):
    log = open(log_file, "w")
else:
    log = open(log_file, "a")
_info("Log file opened")
log.write("[START] " + time.strftime("%Y-%m-%d %H:%M:%S") + "\n")

_info("Check for command line arguments")
if len(sys.argv) > 2:
    _error("Incorrect number of arguments: " + str(len(sys.argv)) + " - expected 0 or 1")
    _help()
    _exit(1)

hostname = sys.argv[1]

_info("Check if argument is proper FQDN")
if not is_fqdn(hostname):
    _error("Hostname contains invalid characters.")
    _help()
    _exit(1)

_info("Connecting to host docker demon")
docker_client = docker.Client(base_url='unix://var/run/docker.sock', version="auto")
_debug(docker_client.version())
_debug(docker_client.info())

_info("")
_info("*** Performing backup on " + hostname + " ***", "green")
_info("")

# clone git repo with host details
# git_server = 'https://github.com/mbeenonic/'
# repo_name = 'io-' + hostname
# repo_dirname = hostname + '.git'
# repo_address = git_server + repo_name
#
# if os.path.exists(repo_dirname):
#    _info("Found old version of " + hostname + " git repo - deleting")
#    shutil.rmtree(repo_dirname)
#
# _info("Clone git repo for " + hostname)
# git.Repo.clone_from(repo_address, repo_dirname)

all_services = []
_info("Search for service directories")
for dir_name in os.listdir("/services"):
    if not os.path.isfile("/services/" + dir_name + "/docker-compose.yml"):
        continue
    all_services.append("/services/" + dir_name)
    _info("Found service directory: " + dir_name)
_debug(all_services)

if len(all_services) == 0:
    _info("No service directories containing docker-compose.yml found.")
    _exit()

for dirname in all_services:
    _info("*** Processing " + dirname + " ***", "green")

    _info("Read yaml config")
    with open(dirname + "/docker-compose.yml", "r") as f:
        ecb_config = yaml.load(f)
    out = yaml.dump(ecb_config)
    _debug(ecb_config)

    if 'ecb' in ecb_config.keys():
        _info(dirname + " seems to be system container directory - skipping", "yellow")
        continue

    _info("Find container types to be backed upXXX")
    container_types_to_backup = {}
    for ctype, cmeta in ecb_config.items():
        if 'labels' in cmeta.keys() and cmeta['labels']['io.enonic.backup'] == 'yes':

            if cmeta['labels']['io.enonic.prescripts'] is not None:
                pre_scripts = [script.strip() for script in cmeta['labels']['io.enonic.prescripts'].split(",")]
            else:
                pre_scripts = ''

            if cmeta['labels']['io.enonic.postscripts'] is not None:
                post_scripts = [script.strip() for script in cmeta['labels']['io.enonic.postscripts'].split(",")]
            else:
                post_scripts = ''

            container_types_to_backup[ctype] = {'pre-scripts' : pre_scripts, 'post-scripts' : post_scripts}
    _info("Container types to backup: " + ', '.join(container_types_to_backup))
    _debug(container_types_to_backup)

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
    _info("Containers to backup: " + ", ".join(containers_to_backup.keys()))
    _debug(containers_to_backup)

    for container_name in containers_to_backup.keys():
        _info("")
        _info("*** Staring backup of " + container_name + " ***", "green")
        _info("")

        _info("Run pre-scripts")
        if containers_to_backup[container_name]['pre-scripts'] is None:
            _info("No pre-scripts defined")
        else:
            for command in containers_to_backup[container_name]['pre-scripts']:
                ret = command_execute(container_name, command)
                _info(ret['command_output'], 'magenta')
                _info("Command exit code: " + str(ret['command_exit_code']), 'yellow')

        _info("Do backup")
        _debug("docker.exec_create(container=" + container_name + ",cmd='DO BACKUP', stdout=True, stderr=True, tty=True)")

        _info("Run post-scripts")
        if containers_to_backup[container_name]['post-scripts'] == '':
            _info("No post-scripts defined")
        else:
            for command in containers_to_backup[container_name]['post-scripts']:
                ret = command_execute(container_name, command)
                _info(ret['command_output'], 'magenta')
                _info("Command exit code: " + str(ret['command_exit_code']), 'yellow')

end_time = time.time()
_info("")
_info("Script was running for " + str(end_time - start_time) + " seconds")
_info("")

_exit()
