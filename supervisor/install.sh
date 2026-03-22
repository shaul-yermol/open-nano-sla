#!/bin/bash -x

# Install supervisord
sudo apt-get update
sudo apt-get install -y supervisor
# Create directory for supervisord conf.d
sudo mkdir -p /etc/supervisor/conf.d
# Create symbolic link to supervisord.conf in /etc/supervisor/conf.d
sudo rm -f /etc/supervisor/supervisord.conf
sudo ln -s /home/shaul/open-nano-dlp/supervisor/supervisord.conf /etc/supervisor/supervisord.conf

# Create supervisor user and group
sudo groupadd supervisor

# Add current user to supervisor group
sudo usermod -aG supervisor $USER


