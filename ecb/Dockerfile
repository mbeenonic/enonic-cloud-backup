FROM ubuntu:14.04

MAINTAINER Marek Bettman <mbe@enonic.com>

LABEL description="Enonic Cloud Backup container"

RUN apt-get update && apt-get -y upgrade && apt-get -y install apt-transport-https
RUN apt-get -y install htop mc git python-setuptools curl links wget python-pip python-termcolor && apt-get clean

RUN curl -sSL https://get.docker.com/ | sh

RUN wget -O /tmp/get-pip.py https://bootstrap.pypa.io/get-pip.py && python /tmp/get-pip.py

RUN pip install gitpython docker-py pyyaml

COPY ./ec-backup.py /bin/ec-backup.py
RUN chmod a+x /bin/ec-backup.py

ENTRYPOINT ["/bin/ec-backup.py"]
