#!/bin/bash
test -f /.kconfig && . /.kconfig
test -f /.profile && . /.profile
echo "Configure image: [$kiwi_iname]..."

# Set default timezone
rm -f /etc/localtime

groupmod -g 25000 gameserver
usermod -u 25000 gameserver

chmod 0755 /usr/bin/start_server
chmod 0755 /usr/bin/cli-asa-mods
chmod 0755 /usr/bin/health-check

# install ruby gems
cd /usr/share/asa-ctrl
bundle.ruby3.4

if [ "$kiwi_profiles" = "development" ]; then
  # will be mounted to ease development
  rm -r /usr/share/asa-ctrl
  gem.ruby3.4 install byebug
else
  chmod 0755 /usr/share/asa-ctrl/main.rb
fi

ln -s /usr/share/asa-ctrl/main.rb /usr/bin/asa-ctrl

exit 0
