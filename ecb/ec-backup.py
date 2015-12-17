#!/usr/bin/python

### CONFIG ###
log_file = "/backup/backup.log"
### END CONFIG ###

import re
import subprocess
import git
import yaml
import sys
import os
import shutil
import docker
import time

# register start time
start_time = time.time()

# check if log file exists, create if not
if os.path.isfile(log_file) != True:
    log = open(log_file, "w")
else:
    log = open(log_file, "a")
log.write("[START] " + time.strftime("%Y-%m-%d %H:%M:%S") + "\n")

def is_fqdn(hostname):
    if len(hostname) > 255:
        return False
    if hostname[-1] == ".":
        hostname = hostname[:-1] # strip exactly one dot from the right, if present
    allowed = re.compile("(?!-)[A-Z\d-]{1,63}(?<!-)$", re.IGNORECASE)
    return all(allowed.match(x) for x in hostname.split("."))

def _error(message):
    print("[ERROR] %s" % message)
    log.write("[ERROR] %s" % message + "\n")

def _info(message):
    print("[INFO] %s" % message)
    log.write("[INFO] %s" % message + "\n")

def _debug(message):
    print("[DEBUG] %s" % message)

def _help():
    print("HELP - TBD")

def _exit(exit_code=0):
    log.write("[END] " + time.strftime("%Y-%m-%d %H:%M:%S") + "\n\n")
    log.close()
    sys.exit(exit_code)

# check for amount of arguments
_info("Check for command line arguments")
if len(sys.argv) != 2:
    _error("Incorrect number of arguments: " + len(sys.argv))
    _help()
    _exit(1)

# get hostname from command line arguments
hostname = sys.argv[1]

_info("")
_info(" *** Performing remote backup on " + hostname + " ***")
_info("")

# check if argument is proper FQDN
_info("Check if argument is proper FQDN")
if is_fqdn(hostname) == False:
    _error("Hostname contains invalid characters.")
    _help()
    _exit(1)

# clone git repo with host details
#git_server = 'https://github.com/mbeenonic/'
#repo_name = 'io-' + hostname
#repo_dirname = hostname + '.git'
#repo_address = git_server + repo_name
#
#if os.path.exists(repo_dirname):
#    _info("Found old version of " + hostname + " git repo - deleting")
#    shutil.rmtree(repo_dirname)
#
#_info("Clone git repo for " + hostname)
#git.Repo.clone_from(repo_address, repo_dirname)

# get all directories under /services
all_services = []
_info("Search for service directories")
for dir_name in os.listdir("/services"):
    if os.path.isfile("/services/" + dir_name + "/docker-compose.yml") != True:
        continue
    all_services.append("/services/" + dir_name)
    _info("Found service directory: " + dir_name)

if len(all_services) == 0:
    _info("No service directories containing docker-compose.yml found.")
    _exit()

for dirname in all_services:
    _info("Read yaml config")
    with open(dirname + "/docker-compose.yml", "r") as f:
        ecb_config = yaml.load(f)
        #print(yaml.dump(ecb_config))

    _info("Find container types to be backed up")
    container_types_to_backup = {}
    for ctype, cmeta in ecb_config.items():
        if 'labels' in cmeta.keys() and cmeta['labels']['io.enonic.backup'] == 'yes':
            pre_scripts = [script.strip() for script in cmeta['labels']['io.enonic.prescripts'].split(",")]
            post_scripts = [script.strip() for script in cmeta['labels']['io.enonic.postscripts'].split(",")]
            container_types_to_backup[ctype] = {'pre-scripts' : pre_scripts, 'post-scripts' : post_scripts}
    _info("Container types to backup: " + ', '.join(container_types_to_backup))
    _debug(container_types_to_backup)
    _exit()

    _info("Connecting to host docker demon")
    docker_client = docker.Client(base_url='unix://var/run/docker.sock', version="auto")

    _info("Get names of the containers to be backed up")
    containers_to_backup = {}
    for image in docker_client.containers():
        for container_name in image['Names']:
            docker_compose_prefix = hostname.replace('.', '')
            for container_type in container_types_to_backup.keys():
                re_string = '^' + docker_compose_prefix + '_' + container_type + '_[0-9]+$'
                p = re.compile(re_string, re.IGNORECASE)
                if p.match(container_name[1:]):
                    containers_to_backup[container_name[1:]] = container_types_to_backup[container_type]
    _info("Containers to backup: " + ", ".join(containers_to_backup.keys()))
    #_debug(containers_to_backup)

    for container_name in containers_to_backup.keys():
        _info("")
        _info(" *** Staring backup of " + container_name + " ***")
        _info("")

        _info(" * Run pre-scripts")
        for command in containers_to_backup[container_name]['pre-scripts']:
            _debug("    docker.exec_create(container=" + container_name + ",cmd='" + command + "',stdout=True,stderr=True,tty=True)")
            #_debug("Container: " + container_name + "     run command: '" + command + "'")

        _info(" * Do backup")
        _debug("    docker.exec_create(container=" + container_name + ",cmd='DO BACKUP',stdout=True,stderr=True,tty=True)")

        _info(" * Run post-scripts")
        for command in containers_to_backup[container_name]['post-scripts']:
            _debug("    docker.exec_create(container=" + container_name + ",cmd='" + command + "',stdout=True,stderr=True,tty=True)")

# register end time
end_time = time.time()
_info("")
_info("Script was running for " + str(end_time - start_time) + " seconds")

_exit()
